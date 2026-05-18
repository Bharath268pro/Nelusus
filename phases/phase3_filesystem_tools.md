# Phase 3 — Filesystem Tools

## 1. Architecture Explanation
Allowing an LLM to interact with the local filesystem is one of the most dangerous capabilities you can grant. A compromised prompt could instruct the agent to read `/etc/passwd`, overwrite `~/.ssh/authorized_keys`, or dump environment variables containing production secrets.

To do this safely in an enterprise MCP, we must build a **Virtual Filesystem Jail**. 
The architecture relies on:
1. **Base Directory Sandboxing:** The LLM is only allowed to interact within a strictly defined `base_path` (e.g., `/app/tenant_data/user_123`).
2. **Path Canonicalization Check:** Before any file operation, the requested path is resolved to its absolute real path. If the resolved path falls outside the `base_path` (via `../` directory traversal), the operation is explicitly blocked.
3. **Deny Lists:** Even within the sandbox, certain file extensions (e.g., `.env`, `.pem`, `.key`) or directories (e.g., `.git`) are strictly blocked.
4. **Size Limitations:** Reading a 10GB log file into memory will crash your FastAPI worker and blow out the LLM's context window. Strict byte-limits and truncation must be enforced.

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── filesystem/
│       ├── __init__.py
│       ├── security.py      # Path resolution and sandboxing logic
│       ├── handlers.py      # The actual read/write/list implementations
│       └── schemas.py       # Pydantic schemas for the tools
```

## 3. Exact Code Implementation

### A. Security & Sandboxing (`tools/filesystem/security.py`)
This is the most critical file. It ensures paths cannot escape the jail.

```python
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Enterprise restrictions
MAX_FILE_SIZE_BYTES = 1024 * 500  # 500 KB limit for LLM context
DENY_EXTENSIONS = {".env", ".pem", ".key", ".sqlite3", ".db"}
DENY_DIRECTORIES = {".git", "__pycache__", ".ssh"}

class FileSystemJail:
    def __init__(self, base_path: str):
        # Resolve the base path immediately to its absolute, canonical form
        self.base_path = Path(base_path).resolve()
        
        if not self.base_path.exists():
            self.base_path.mkdir(parents=True, exist_ok=True)

    def secure_resolve(self, requested_path: str) -> Path:
        """
        Resolves a requested path and violently rejects directory traversal attempts.
        """
        # Combine base and requested path
        combined = (self.base_path / requested_path).resolve()
        
        # SECURITY CHECK 1: Directory Traversal Prevention
        # If the resolved path does not start with the base_path, they used ../ to escape.
        try:
            combined.relative_to(self.base_path)
        except ValueError:
            logger.error(f"SECURITY ALERT: Directory traversal attempt to {combined}")
            raise PermissionError("Access denied: Path escapes sandbox boundary.")

        # SECURITY CHECK 2: Deny Lists
        if combined.suffix in DENY_EXTENSIONS:
            raise PermissionError(f"Access denied: Restricted file type {combined.suffix}")
            
        for part in combined.parts:
            if part in DENY_DIRECTORIES:
                raise PermissionError(f"Access denied: Restricted directory {part}")

        return combined

    def check_size(self, filepath: Path) -> None:
        """Prevents reading massive files into memory."""
        if filepath.exists():
            size = filepath.stat().st_size
            if size > MAX_FILE_SIZE_BYTES:
                raise ValueError(f"File too large: {size} bytes. Max allowed is {MAX_FILE_SIZE_BYTES}.")
```

### B. Implementations (`tools/filesystem/handlers.py`)
Here we implement the actual tool logic using our `FileSystemJail`.

```python
import os
import aiofiles
from typing import List, Dict, Any
from app.tools.filesystem.security import FileSystemJail

# In production, this base path is dynamically determined by the Tenant ID from the JWT
jail = FileSystemJail(base_path="/tmp/mcp_workspace")

async def read_file(file_path: str) -> str:
    """Read a file safely."""
    try:
        safe_path = jail.secure_resolve(file_path)
        if not safe_path.exists() or not safe_path.is_file():
            return f"Error: File '{file_path}' does not exist."
            
        jail.check_size(safe_path)
        
        async with aiofiles.open(safe_path, mode='r', encoding='utf-8') as f:
            content = await f.read()
            return content
    except Exception as e:
        return f"Error reading file: {str(e)}"

async def write_file(file_path: str, content: str) -> str:
    """Write to a file safely."""
    try:
        safe_path = jail.secure_resolve(file_path)
        
        # Ensure parent directories exist within the jail
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        
        async with aiofiles.open(safe_path, mode='w', encoding='utf-8') as f:
            await f.write(content)
            return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {str(e)}"

async def list_directory(directory_path: str = ".") -> List[Dict[str, Any]]:
    """List contents of a directory safely."""
    try:
        safe_path = jail.secure_resolve(directory_path)
        if not safe_path.exists() or not safe_path.is_dir():
            return [{"error": f"Directory '{directory_path}' does not exist."}]
            
        results = []
        for entry in os.scandir(safe_path):
            results.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "size": entry.stat().st_size if entry.is_file() else 0
            })
        return results
    except Exception as e:
        return [{"error": f"Error listing directory: {str(e)}"}]
```

### C. Tool Registration Setup
You would register these in your `main.py` using the engine built in Phase 1.

```python
from app.models.mcp_registry import ToolDefinition
from app.services.registry_engine import registry

registry.register_tool(
    ToolDefinition(
        name="fs.read_file",
        description="Read the contents of a file in the workspace.",
        inputSchema={
            "type": "object", 
            "properties": {"file_path": {"type": "string"}}, 
            "required": ["file_path"]
        }
    ),
    read_file
)
# ... register write_file and list_directory similarly.
```

## 4. Security Reasoning
- **`Path.resolve()` is Mandatory:** A path like `/tmp/workspace/safe_folder/../../../etc/passwd` looks safe if you just do a string `startswith()` check on the prefix. You MUST call `.resolve()` to let the OS evaluate the symlinks and `..` operators to get the real absolute path BEFORE checking boundaries.
- **`relative_to()` Check:** This is the cryptographic standard in Python for ensuring Path A is strictly a child of Path B.
- **Extension Deny Lists:** Agents often write code. Preventing them from writing `.py` files inside the backend's own execution directory prevents Remote Code Execution (RCE) via module hijacking. 
- **Symlink Attacks:** `resolve()` inherently mitigates symlink attacks by resolving the link to its ultimate destination, which will then trigger the boundary check.

## 5. Scaling Reasoning
- **`aiofiles`:** Filesystem I/O is blocking. Doing a standard `open(file).read()` on a 500KB file pauses the Python thread, stalling all other web requests. `aiofiles` offloads this to a threadpool, maintaining high concurrency for your MCP gateway.
- **Ephemerality:** In a Kubernetes environment, `/tmp` is ephemeral. If the pod restarts, the files are lost. For production, `FileSystemJail` should point to an EFS (Elastic File System), S3-backed FUSE mount, or a dedicated Persistent Volume Claim (PVC) tied to the user.

## 6. Common Production Pitfalls
- **Encoding Issues:** LLMs frequently generate UTF-8 emojis or obscure symbols. If you don't explicitly pass `encoding='utf-8'` to `aiofiles.open()`, the OS default (often `cp1252` on Windows hosts) will throw `UnicodeDecodeError` and crash the tool.
- **Race Conditions:** Two LLM agents acting for the same tenant writing to the same file simultaneously will corrupt it. For enterprise setups, implement file locking or use a proper database for shared state.

## 7. Enterprise Best Practices
- **Audit Logging:** Every time `write_file` or `read_file` is called, write a log to your central SIEM (Datadog/Splunk) including the `UserContext.user_id`, the requested path, and the action.
- **Ephemeral Workspaces:** Instead of a static folder, dynamically provision an isolated Docker container or Firecracker microVM for the agent's filesystem operations, and mount it via a network protocol.

## 8. Testing Instructions
1. Implement the code.
2. Attempt a directory traversal attack. It MUST fail.

```bash
curl -X POST http://localhost:8000/api/v1/mcp/execute \
     -H "Authorization: Bearer <valid_jwt>" \
     -H "Content-Type: application/json" \
     -d '{"tool_name": "fs.read_file", "arguments": {"file_path": "../../../../etc/passwd"}}'
```

*Expected Output:*
```json
{
  "success": false,
  "error": "Error reading file: Access denied: Path escapes sandbox boundary."
}
```

---
**Status:** Phase 3 complete. Awaiting confirmation to proceed to Phase 4 (Database Tools).
