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
