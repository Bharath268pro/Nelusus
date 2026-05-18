import logging
from typing import Set

logger = logging.getLogger(__name__)

# Enterprise constraints: Never allow 'kube-system', 'default', or wildcard namespaces.
ALLOWED_NAMESPACES: Set[str] = {"tenant-a-prod", "tenant-b-staging", "ai-sandbox"}

class KubernetesJail:
    @staticmethod
    def validate_namespace(namespace: str) -> None:
        """
        Ensures the requested namespace is explicitly allowed.
        """
        if namespace not in ALLOWED_NAMESPACES:
            logger.error(f"SECURITY ALERT: Attempt to access unauthorized namespace: {namespace}")
            raise PermissionError(f"Access denied: Namespace '{namespace}' is restricted.")
