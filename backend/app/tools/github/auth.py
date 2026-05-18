import os
import time
import jwt
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Loaded from secure secrets vault in production
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID", "mock_app_id")
GITHUB_PRIVATE_KEY = os.environ.get("GITHUB_PRIVATE_KEY", "mock_private_key")

async def get_installation_token(repo_owner: str, repo_name: str) -> str:
    """
    Mints a short-lived GitHub API token strictly scoped to the requested repo.
    """
    if GITHUB_PRIVATE_KEY == "mock_private_key":
        return f"mock_gh_token_for_{repo_owner}_{repo_name}"

    # 1. Generate JWT to authenticate as the GitHub App
    now = int(time.time())
    payload = {
        "iat": now - 60,  # Issued 60s ago to allow for clock drift
        "exp": now + (10 * 60), # 10 minute expiration
        "iss": GITHUB_APP_ID
    }
    
    app_jwt = jwt.encode(payload, GITHUB_PRIVATE_KEY, algorithm="RS256")
    
    async with httpx.AsyncClient() as client:
        # 2. Get the Installation ID for the specific repository
        headers = {
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        repo_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/installation"
        repo_resp = await client.get(repo_url, headers=headers)
        
        if repo_resp.status_code == 404:
            raise PermissionError("App is not installed on this repository or it does not exist.")
        repo_resp.raise_for_status()
        
        installation_id = repo_resp.json()["id"]
        
        # 3. Mint the short-lived Installation Access Token
        token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        body = {"repositories": [repo_name]}
        
        token_resp = await client.post(token_url, headers=headers, json=body)
        token_resp.raise_for_status()
        
        return token_resp.json()["token"]
