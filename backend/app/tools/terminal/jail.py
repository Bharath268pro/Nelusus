import asyncio
import docker
import logging
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# We use ThreadPool because docker-py is synchronous.
pool = ThreadPoolExecutor(max_workers=10)
client = docker.from_env()

# Context limit for the LLM output
MAX_OUTPUT_BYTES = 8000  # ~2000 tokens

async def run_in_docker_jail(command_parts: List[str], timeout: int = 10) -> Dict[str, Any]:
    """
    Spawns an ephemeral Docker container, executes the command list without a shell,
    and returns the truncated stdout/stderr.
    """
    loop = asyncio.get_running_loop()
    
    def _execute():
        container = None
        try:
            # Spin up a totally isolated, ephemeral container
            container = client.containers.run(
                image="python:3.11-slim",       # Pre-built image with allowed tools
                command=command_parts,          # Passed as list (No Shell!)
                detach=True,
                network_mode="none",            # SECURITY: Disable all outbound internet access!
                mem_limit="128m",               # SECURITY: Max 128MB RAM
                cpu_period=100000,
                cpu_quota=50000,                # SECURITY: Max 0.5 CPU core
                read_only=True,                 # SECURITY: Read-only root filesystem
                tmpfs={"/tmp": ""},             # Allow writing only to an ephemeral /tmp
                user="1000:1000",               # SECURITY: Run as non-root user
            )
            
            # Wait for completion with timeout
            result = container.wait(timeout=timeout)
            
            # Fetch logs
            stdout_logs = container.logs(stdout=True, stderr=False)
            stderr_logs = container.logs(stdout=False, stderr=True)
            
            # Truncate to prevent context window explosion
            stdout_str = stdout_logs.decode('utf-8')[:MAX_OUTPUT_BYTES]
            stderr_str = stderr_logs.decode('utf-8')[:MAX_OUTPUT_BYTES]
            
            if len(stdout_logs) > MAX_OUTPUT_BYTES:
                stdout_str += "\n...[TRUNCATED]"
                
            return {
                "exit_code": result["StatusCode"],
                "stdout": stdout_str,
                "stderr": stderr_str,
                "timeout": False
            }
            
        except Exception as e:
            logger.error(f"Docker jail execution error: {e}")
            raise e
        finally:
            if container:
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    try:
        return await asyncio.wait_for(loop.run_in_executor(pool, _execute), timeout=timeout + 2)
    except asyncio.TimeoutError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command execution timed out after {timeout} seconds.",
            "timeout": True
        }
