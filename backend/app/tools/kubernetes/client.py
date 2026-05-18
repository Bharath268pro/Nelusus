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
        logger.warning(f"Failed to load any K8s configuration: {e}")

# Core API for Pods/Services
v1_core = client.CoreV1Api()
# Apps API for Deployments/StatefulSets
v1_apps = client.AppsV1Api()
