"""Main FastAPI application factory"""

import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from app.config import settings
from app.routes import health_router, mcp_router
from app.routes.agent import router as agent_router
from app.services.agent_runtime import create_agent_runtime
from app.middleware import SecurityProxyMiddleware

# NEW: Import your tools and registry engine from Phase 1
from app.services.registry_engine import registry
from app.models.mcp_registry import ToolDefinition, ToolSchema

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# NEW: Placeholder dummy function for testing
async def dummy_weather(location: str):
    return {"temp": 72, "location": location}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle application startup and shutdown"""
    logger.info("Starting MCP Security Proxy (Phase 2D: Agent Orchestration)...")
    
    # 1. CLEAN INTEGRATION: Register your Phase 1 tools here inside lifespan
    try:
        registry.register_tool(
            ToolDefinition(
                name="weather.get",
                description="Get weather for a location",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"location": {"type": "string"}},
                    required=["location"]
                )
            ),
            dummy_weather
        )
        
        # Register Phase 3 safe filesystem tools
        from app.tools.filesystem import read_file, write_file, list_directory
        registry.register_tool(
            ToolDefinition(
                name="fs.read_file",
                description="Read a file inside the sandboxed workspace safely.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"file_path": {"type": "string"}},
                    required=["file_path"]
                )
            ),
            read_file
        )
        registry.register_tool(
            ToolDefinition(
                name="fs.write_file",
                description="Write contents to a file inside the sandboxed workspace safely.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "file_path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    required=["file_path", "content"]
                )
            ),
            write_file
        )
        registry.register_tool(
            ToolDefinition(
                name="fs.list_dir",
                description="List contents of a directory inside the sandboxed workspace safely.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"directory_path": {"type": "string", "default": "."}},
                    required=[]
                )
            ),
            list_directory
        )

        # Register Phase 4 Database Tools
        from app.tools.database import search_customers, get_invoice_summary
        registry.register_tool(
            ToolDefinition(
                name="db.search_customers",
                description="Search for customers by email domain securely via parameter binding.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"email_domain": {"type": "string"}},
                    required=["email_domain"]
                )
            ),
            search_customers
        )
        registry.register_tool(
            ToolDefinition(
                name="db.get_invoice_summary",
                description="Get aggregated invoice summary for a customer ID.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"customer_id": {"type": "string"}},
                    required=["customer_id"]
                )
            ),
            get_invoice_summary
        )

        # Register Phase 5 Salesforce Tools
        from app.tools.salesforce import search_contacts, get_opportunity_details, create_lead
        registry.register_tool(
            ToolDefinition(
                name="salesforce.search_contacts",
                description="Find a Salesforce Contact by Email.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"email": {"type": "string"}},
                    required=["email"]
                )
            ),
            search_contacts
        )
        registry.register_tool(
            ToolDefinition(
                name="salesforce.get_opportunity_details",
                description="Get details of a specific opportunity.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"opp_id": {"type": "string"}},
                    required=["opp_id"]
                )
            ),
            get_opportunity_details
        )
        registry.register_tool(
            ToolDefinition(
                name="salesforce.create_lead",
                description="Create a new Lead in Salesforce.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "first_name": {"type": "string"},
                        "last_name": {"type": "string"},
                        "company": {"type": "string"},
                        "email": {"type": "string"}
                    },
                    required=["first_name", "last_name", "company", "email"]
                )
            ),
            create_lead
        )

        # Register Phase 6 Terminal Tools
        from app.tools.terminal import execute_terminal_command
        registry.register_tool(
            ToolDefinition(
                name="terminal.execute",
                description="Execute a terminal command in a secure sandbox.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={"command": {"type": "string"}},
                    required=["command"]
                )
            ),
            execute_terminal_command
        )

        # Register Phase 7 GitHub Tools
        from app.tools.github import read_github_file, create_pull_request
        registry.register_tool(
            ToolDefinition(
                name="github.read_file",
                description="Read the contents of a file directly from a GitHub repository.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "repo_owner": {"type": "string"},
                        "repo_name": {"type": "string"},
                        "file_path": {"type": "string"}
                    },
                    required=["repo_owner", "repo_name", "file_path"]
                )
            ),
            read_github_file
        )
        registry.register_tool(
            ToolDefinition(
                name="github.create_pr",
                description="Create a new Pull Request.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "repo_owner": {"type": "string"},
                        "repo_name": {"type": "string"},
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "head_branch": {"type": "string"},
                        "base_branch": {"type": "string"}
                    },
                    required=["repo_owner", "repo_name", "title", "body", "head_branch", "base_branch"]
                )
            ),
            create_pull_request
        )

        # Register Phase 8 Kubernetes Tools
        from app.tools.kubernetes import list_pods, get_pod_logs, restart_deployment
        registry.register_tool(
            ToolDefinition(
                name="kubernetes.list_pods",
                description="List pods in a specific namespace.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "namespace": {"type": "string"},
                        "label_selector": {"type": "string"}
                    },
                    required=["namespace"]
                )
            ),
            list_pods
        )
        registry.register_tool(
            ToolDefinition(
                name="kubernetes.get_pod_logs",
                description="Get recent logs for a specific pod.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "namespace": {"type": "string"},
                        "pod_name": {"type": "string"},
                        "tail_lines": {"type": "integer"}
                    },
                    required=["namespace", "pod_name"]
                )
            ),
            get_pod_logs
        )
        registry.register_tool(
            ToolDefinition(
                name="kubernetes.restart_deployment",
                description="Safely trigger a rollout restart of a deployment.",
                inputSchema=ToolSchema(
                    type="object",
                    properties={
                        "namespace": {"type": "string"},
                        "deployment_name": {"type": "string"}
                    },
                    required=["namespace", "deployment_name"]
                )
            ),
            restart_deployment
        )

        logger.info("Phase 1, Phase 3, Phase 4, Phase 5, Phase 6, Phase 7, and Phase 8 Tool Registries successfully populated on startup.")
    except Exception as e:
        logger.error(f"Failed to register startup tools: {e}")
    
    # 2. Initialize Agent Runtime
    # Normally we'd pass the real Redis cache here
    agent_runtime = create_agent_runtime(cache=None)
    app.state.agent_runtime = agent_runtime
    logger.info("Phase 2D Agent Reasoning Runtime initialized")
    
    yield
    logger.info("Shutting down MCP Security Proxy...")


from app.core.telemetry import setup_telemetry
from app.core.logging import setup_logging

# Initialize Phase 12 JSON structured logging immediately
setup_logging()

def create_app() -> FastAPI:
    """Create and configure the FastAPI application"""

    app = FastAPI(
        title="MCP Security Proxy",
        description="Security middleware for Model Context Protocol agents accessing Salesforce",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Phase 12: Mount OpenTelemetry & Prometheus /metrics route
    setup_telemetry(app)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000", "http://localhost:8080"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Security middleware
    app.add_middleware(SecurityProxyMiddleware)

    # Include routers
    app.include_router(health_router)
    app.include_router(mcp_router)
    app.include_router(agent_router)

    return app


# Create app instance
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )