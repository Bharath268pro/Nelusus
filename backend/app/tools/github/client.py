import httpx
from typing import Dict, Any

class GitHubClient:
    def __init__(self, token: str):
        self.base_url = "https://api.github.com"
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28"
            },
            timeout=15.0
        )

    async def get(self, path: str) -> Dict[str, Any]:
        response = await self._client.get(f"{self.base_url}/{path}")
        response.raise_for_status()
        return response.json()

    async def post(self, path: str, payload: dict) -> Dict[str, Any]:
        response = await self._client.post(f"{self.base_url}/{path}", json=payload)
        response.raise_for_status()
        return response.json()
        
    async def close(self):
        await self._client.aclose()
