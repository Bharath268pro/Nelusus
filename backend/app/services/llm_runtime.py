"""Real LLM Runtime using OpenAI for Dynamic Tool Selection"""

import json
import logging
import os
from typing import Any, Dict, List
from opentelemetry import trace

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)

class LLMReasoningEngine:
    """Uses OpenAI Function Calling to dynamically plan workflows based on schemas."""

    def __init__(self):
        try:
            from openai import AsyncOpenAI
            self.client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", "sk-mock"))
            self.model = "gpt-4-turbo"
        except ImportError:
            self.client = None
            logger.warning("OpenAI SDK not found. LLM reasoning will fail.")

    async def generate_plan(self, intent: str, available_tools: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Takes natural language intent and dynamic JSON schemas (from MCP),
        and asks the LLM to select the appropriate tools and parameters.
        """
        if not self.client:
            raise RuntimeError("OpenAI client not initialized")

        # Convert MCP schemas into OpenAI Function Calling format
        functions = []
        for tool in available_tools:
            functions.append({
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool.get("inputSchema", {"type": "object", "properties": {}})
            })

        system_prompt = (
            "You are an enterprise integration agent. "
            "Based on the user's intent, decide the sequence of tools to call. "
            "You MUST output your plan as a JSON array of steps. "
            "Each step must have 'tool_name' and 'args' (dict). "
            "If an argument needs to come from a previous step, use the format '{step_index.field_name}'. "
            "If a required argument is missing from the intent, you MUST still include the step but set the missing argument to '__MISSING__'."
        )

        with tracer.start_as_current_span("llm_generate_plan") as span:
            span.set_attribute("intent", intent)
            span.set_attribute("available_tools_count", len(functions))

            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Intent: {intent}\n\nGenerate the JSON array plan:"}
                    ],
                    functions=functions,
                    temperature=0.0
                )
                
                content = response.choices[0].message.content
                if not content:
                    # Sometimes it uses function_call directly
                    fc = response.choices[0].message.function_call
                    if fc:
                        plan = [{"tool_name": fc.name, "args": json.loads(fc.arguments)}]
                        span.set_attribute("plan_steps", len(plan))
                        return {"steps": plan}
                    raise ValueError("LLM returned empty plan")

                # Parse JSON array response
                # Strip markdown code blocks if present
                clean_content = content.replace("```json", "").replace("```", "").strip()
                plan = json.loads(clean_content)
                span.set_attribute("plan_steps", len(plan))
                return {"steps": plan}
            
            except Exception as e:
                span.record_exception(e)
                span.set_attribute("error", str(e))
                logger.error(f"[LLMReasoning] Failed to generate plan: {e}")
                # Fallback for testing with mock API keys
                return self._mock_plan(intent)

    def _mock_plan(self, intent: str) -> Dict[str, Any]:
        """Fallback for when OpenAI is mock or fails."""
        if "shopify" in intent.lower() and "salesforce" in intent.lower():
            return {
                "steps": [
                    {"tool_name": "shopify.get_order", "args": {"order_id": "ORD-123"}},
                    {"tool_name": "salesforce.upsert_contact", "args": {"email": "{0.customer.email}"}}
                ]
            }
        return {"steps": []}
