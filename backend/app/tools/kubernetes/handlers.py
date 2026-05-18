from typing import Dict, Any
from kubernetes.client.rest import ApiException
from app.tools.kubernetes.client import v1_core, v1_apps
from app.tools.kubernetes.security import KubernetesJail

async def list_pods(namespace: str, label_selector: str = "") -> Dict[str, Any]:
    """Tool: List pods in a specific namespace."""
    try:
        KubernetesJail.validate_namespace(namespace)
        
        pods = v1_core.list_namespaced_pod(
            namespace=namespace,
            label_selector=label_selector,
            limit=50
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
