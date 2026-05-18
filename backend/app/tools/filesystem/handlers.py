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
