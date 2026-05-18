# Phase 8 — Kubernetes Tools

## 1. Architecture Explanation
Allowing an LLM to interface with Kubernetes (K8s) requires the highest degree of infrastructure protection. If an LLM executes a generic `kubectl delete pods --all -A`, it can take down your entire cluster. 

To safely interface with Kubernetes in an enterprise MCP, we **abandon the `kubectl` CLI** entirely in favor of the official programmatic Kubernetes API Client. 

The architecture relies on:
1. **API Client wrappers (No `kubectl` shell execution):** Shelling out to `kubectl` invites injection attacks. Programmatic API usage enforces strict Python typing.
2. **Namespace Jailing:** Every tool requires a `namespace` argument. The backend validates this against a strict allowlist. The LLM is **never** allowed to execute cluster-scoped resources (like `Nodes` or `ClusterRoles`).
3. **Delegated ServiceAccounts:** The MCP backend should run inside a Pod using an impoverished default ServiceAccount. When it executes a tool, it assumes the identity of a specific, strictly-scoped ServiceAccount (e.g., `ai-operator-sa`) bound via RBAC to the target namespace.
4. **Read-Heavy, Write-Gated:** Read operations (`get_pods`, `get_logs`) are sandboxed but fluid. Write operations (`rollout_restart`, `scale_deployment`) require secondary human approval logic (which will be orchestrated in Phase 10).

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── kubernetes/
│       ├── __init__.py
│       ├── client.py        # K8s python API client initialization
│       ├── security.py      # Namespace and RBAC validation logic
│       └── handlers.py      # Safe Pod, Deployment, and Log inspection tools
```

## 3. Exact Code Implementation

### A. Kubernetes Client Initialization (`tools/kubernetes/client.py`)
This securely initializes the Kubernetes client. It assumes the MCP Gateway is running inside the cluster.

```python
import logging
from kubernetes import client, config

logger = logging.getLogger(__name__)

# Initialize the global client
try:
    # In cluster: reads the /var/run/secrets/kubernetes.io/serviceaccount/token
    config.load_incluster_config()
    logger.info("Loaded in-cluster K8s config.")
except config.ConfigException:
    try:
        # Local development fallback
        config.load_kube_config()
        logger.warning("Loaded local kubeconfig for K8s.")
    except config.ConfigException as e:
        logger.error(f"Failed to load any K8s configuration: {e}")

# Core API for Pods/Services
v1_core = client.CoreV1Api()
# Apps API for Deployments/StatefulSets
v1_apps = client.AppsV1Api()
```

### B. Security & Namespace Isolation (`tools/kubernetes/security.py`)
This enforces strict boundaries on what namespaces the LLM can touch.

```python
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
```

### C. Safe Inspection Handlers (`tools/kubernetes/handlers.py`)
These are the tools exposed to the MCP Registry. Notice the strict error handling and parameterization.

```python
from typing import Dict, Any, List
from kubernetes.client.rest import ApiException
from app.tools.kubernetes.client import v1_core, v1_apps
from app.tools.kubernetes.security import KubernetesJail

async def list_pods(namespace: str, label_selector: str = "") -> Dict[str, Any]:
    """Tool: List pods in a specific namespace."""
    try:
        KubernetesJail.validate_namespace(namespace)
        
        # The Python client uses threads under the hood, but for FastAPI we keep it simple.
        # In a strict async setup, you might wrap this in a ThreadPool or use `kubernetes_asyncio`.
        pods = v1_core.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector,
            limit=50 # Hard limit to prevent memory blowout
        )
        
        results = []
        for pod in pods.items:
            results.append({
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "restarts": sum([c.restart_count for c in pod.status.container_statuses]) if pod.status.container_statuses else 0,
                "age_seconds": (pod.metadata.creation_timestamp.now(pod.metadata.creation_timestamp.tzinfo) - pod.metadata.creation_timestamp).total_seconds()
            })
            
        return {"success": True, "pods": results}
    except ApiException as e:
        return {"success": False, "error": f"K8s API Error: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 100) -> Dict[str, Any]:
    """Tool: Get recent logs for a specific pod."""
    try:
        KubernetesJail.validate_namespace(namespace)
        
        # Enforce strict tail limits so the LLM context isn't destroyed
        safe_tail = min(tail_lines, 500)
        
        logs = v1_core.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            tail_lines=safe_tail
        )
        
        return {"success": True, "logs": logs}
    except ApiException as e:
        return {"success": False, "error": f"K8s API Error: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def restart_deployment(namespace: str, deployment_name: str) -> Dict[str, Any]:
    """Tool: Safely trigger a rollout restart of a deployment."""
    try:
        KubernetesJail.validate_namespace(namespace)
        
        # To restart a deployment programmatically, we patch an annotation 
        # (exactly like `kubectl rollout restart` does under the hood).
        import datetime
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "mcp.ai/restartedAt": datetime.datetime.utcnow().isoformat()
                        }
                    }
                }
            }
        }
        
        v1_apps.patch_namespaced_deployment(
            name=deployment_name,
            namespace=namespace,
            body=patch
        )
        
        return {"success": True, "message": f"Deployment {deployment_name} restarted successfully."}
    except ApiException as e:
        return {"success": False, "error": f"K8s API Error: {e.reason}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

## 4. Security Reasoning
- **Programmatic API > Subprocess:** Executing `subprocess.run(["kubectl", ...])` is inherently dangerous. If the LLM hallucinates an argument like `--insecure-skip-tls-verify`, it alters the security profile. The programmatic API forces strict struct typing.
- **Namespace Whitelisting:** By explicitly declaring `ALLOWED_NAMESPACES`, we ensure that even if the underlying `ServiceAccount` has broader RBAC permissions due to a DevOps misconfiguration, the application layer will violently reject attempts to touch `kube-system` or adjacent tenant namespaces.
- **Log Truncation (`tail_lines`):** Container logs can be gigabytes in size. Forcing a hard cap (`min(tail_lines, 500)`) guarantees the tool response remains small enough for the LLM to process without causing a context window explosion.

## 5. Scaling Reasoning
- **Async API Clients:** The official `kubernetes` python client is synchronous. In a high-throughput production gateway, you should switch to the `kubernetes_asyncio` package, which natively hooks into the FastAPI ASGI event loop, allowing thousands of concurrent pod queries without thread starvation.
- **Pagination (`limit=50`):** Querying `list_namespaced_pod` without a `limit` in a massive cluster returns thousands of objects, crashing the JSON serializer and consuming massive RAM. Always paginate K8s API lists.

## 6. Common Production Pitfalls
- **`cluster-admin` ServiceAccounts:** The single biggest mistake is binding the `cluster-admin` ClusterRole to the Pod running the MCP backend. You MUST create a dedicated Role with strict `get`, `list`, `watch`, `patch` verbs bounded by a `RoleBinding` to the specific target namespaces.
- **Multi-Container Pod Logs:** `read_namespaced_pod_log` will fail if a Pod has multiple containers and you don't specify the `container=` argument. You must either provide a tool parameter for the container name or dynamically fetch the first container in the pod.

## 7. Enterprise Best Practices
- **Audit Webhooks:** Kubernetes API servers should be configured with Audit Webhooks. Any `patch` or `delete` operation executed by the MCP's ServiceAccount should generate an immutable audit log sent to Datadog/Splunk for SIEM alerting.
- **Impersonation:** If the MCP Gateway serves multiple human engineers, use K8s API Impersonation Headers (`Impersonate-User: bob@company.com`). The K8s API will evaluate the request against Bob's RBAC, not the MCP's ServiceAccount.

## 8. Step-by-Step Setup Instructions
1. Install the client: `pip install kubernetes`.
2. Apply strict RBAC to the ServiceAccount running your FastAPI pod:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: ai-sandbox
  name: mcp-operator-role
rules:
- apiGroups: ["", "apps"]
  resources: ["pods", "pods/log", "deployments"]
  verbs: ["get", "list", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: mcp-operator-binding
  namespace: ai-sandbox
subjects:
- kind: ServiceAccount
  name: mcp-backend-sa
roleRef:
  kind: Role
  name: mcp-operator-role
  apiGroup: rbac.authorization.k8s.io
```
3. Register the handlers in the MCP Tool Registry.

## 9. Example Request / Response

**LLM Intent:** "Restart the frontend deployment in the ai-sandbox namespace."
**Tool Request:**
```json
{
  "tool_name": "kubernetes.restart_deployment",
  "arguments": {
    "namespace": "ai-sandbox",
    "deployment_name": "frontend"
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "message": "Deployment frontend restarted successfully."
  }
}
```

**Malicious Intent:** "List all pods in the kube-system namespace."
**Tool Request:**
```json
{
  "tool_name": "kubernetes.list_pods",
  "arguments": {
    "namespace": "kube-system"
  }
}
```

**Secure Response:**
```json
{
  "success": false,
  "error": "Access denied: Namespace 'kube-system' is restricted."
}
```

---
**Status:** Phase 8 complete. Awaiting confirmation to proceed to Phase 9 (Email Tools).
