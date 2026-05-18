from typing import Dict, Any
from app.tools.terminal.security import parse_and_validate_command
from app.tools.terminal.jail import run_in_docker_jail

async def execute_terminal_command(command: str) -> Dict[str, Any]:
    """
    Tool: Execute a terminal command in a secure sandbox.
    LLM Payload Example: {"command": "python3 -c 'print(\"hello\")'"}
    """
    try:
        # 1. Parse and validate against the strict allowlist
        safe_command_list = parse_and_validate_command(command)
        
        # 2. Execute inside the Docker jail
        result = await run_in_docker_jail(safe_command_list, timeout=10)
        
        return {
            "success": True if result["exit_code"] == 0 else False,
            "data": result
        }
    except ValueError as ve:
        return {"success": False, "error": str(ve)}
    except Exception as e:
        return {"success": False, "error": f"Execution failed: {str(e)}"}
