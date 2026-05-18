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
