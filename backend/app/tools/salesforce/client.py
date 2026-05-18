import os
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class SalesforceClient:
    """Manages Salesforce OAuth Lifecycle and REST API requests."""
    
    def __init__(self, instance_url: str, access_token: str, refresh_token: Optional[str] = None):
        self.instance_url = instance_url
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = os.environ.get("SF_CLIENT_ID", "mock_client_id")
        self.client_secret = os.environ.get("SF_CLIENT_SECRET", "mock_client_secret")
        self.api_version = "v57.0"
        self.base_url = f"{self.instance_url}/services/data/{self.api_version}"
        self._client = httpx.AsyncClient(timeout=10.0)

    async def _refresh_token(self):
        """Perform OAuth2 Refresh Token Grant."""
        if not self.refresh_token:
            raise PermissionError("Salesforce token expired and no refresh token is available.")
            
        logger.info(f"Refreshing Salesforce token for instance {self.instance_url}")
        token_url = f"{self.instance_url}/services/oauth2/token"
        
        response = await self._client.post(token_url, data={
            "grant_type": "refresh_token",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token
        })
        
        response.raise_for_status()
        tokens = response.json()
        self.access_token = tokens["access_token"]

    async def request(self, method: str, endpoint: str, **kwargs) -> httpx.Response:
        """Wrapper for httpx that transparently handles 401 Expirations."""
        url = f"{self.base_url}/{endpoint}"
        
        # Helper to attach Auth header
        def get_headers():
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {self.access_token}"
            return headers

        response = await self._client.request(method, url, headers=get_headers(), **kwargs)
        
        if response.status_code == 401:
            await self._refresh_token()
            response = await self._client.request(method, url, headers=get_headers(), **kwargs)
            
        response.raise_for_status()
        return response

    async def close(self):
        await self._client.aclose()
