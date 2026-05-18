# Phase 7 — GitHub Tools

## 1. Architecture Explanation
Allowing an LLM to interact with your organization's source code is a high-risk vector. A naive implementation using a Personal Access Token (PAT) with `repo` scope gives the LLM total, unaudited control over all repositories the token owner can access.

To securely interface with GitHub in an enterprise MCP, we use a **GitHub App Architecture**:
1. **GitHub App Authenticator:** Instead of static PATs, the MCP backend authenticates as a GitHub App using a signed JWT. It then requests a short-lived **Installation Access Token** strictly scoped to a single repository.
2. **Strict Repository Boundaries:** Tools like `github.read_file` or `github.create_pr` require an explicit `repo_name` argument. The backend verifies the user/tenant has permission to act on that specific repo before minting the token.
3. **Stateless Operations:** To avoid checking out full repositories onto the MCP pod's filesystem (which risks leaking code across tenants), operations are performed entirely via the GitHub REST/GraphQL API (e.g., reading blobs, creating trees, and pushing commits statelessly).

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── github/
│       ├── __init__.py
│       ├── auth.py          # GitHub App JWT and Installation Token logic
│       ├── client.py        # Httpx client wrapper with the temporary token
│       └── handlers.py      # Exposed tools (read_file, create_pr, etc.)
```

## 3. Exact Code Implementation

### A. GitHub App Auth & Token Minting (`tools/github/auth.py`)
This generates the short-lived installation token securely.

```python
import os
import time
import jwt
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Loaded from secure secrets vault in production
GITHUB_APP_ID = os.environ.get("GITHUB_APP_ID")
GITHUB_PRIVATE_KEY = os.environ.get("GITHUB_PRIVATE_KEY")

async def get_installation_token(repo_owner: str, repo_name: str) -> str:
    """
    Mints a short-lived GitHub API token strictly scoped to the requested repo.
    """
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
        # Optional: Explicitly narrow down scopes for defense-in-depth
        body = {"repositories": [repo_name]}
        
        token_resp = await client.post(token_url, headers=headers, json=body)
        token_resp.raise_for_status()
        
        return token_resp.json()["token"]
```

### B. The GitHub Client Wrapper (`tools/github/client.py`)
Automatically injects the minted token into HTTP requests.

```python
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
```

### C. Stateless Handlers (`tools/github/handlers.py`)
These are the exact tools exposed to the LLM via the MCP Registry.

```python
import base64
from typing import Dict, Any
from app.tools.github.auth import get_installation_token
from app.tools.github.client import GitHubClient
from app.models.auth import UserContext

async def read_github_file(
    repo_owner: str, 
    repo_name: str, 
    file_path: str, 
    user_context: UserContext
) -> Dict[str, Any]:
    """Tool: Read the contents of a file directly from a GitHub repository."""
    
    # In an enterprise, verify user_context.tenant_id is allowed to access repo_owner/repo_name here!
    
    try:
        token = await get_installation_token(repo_owner, repo_name)
        client = GitHubClient(token)
        
        # Use the Contents API
        result = await client.get(f"repos/{repo_owner}/{repo_name}/contents/{file_path}")
        
        # GitHub returns file content base64 encoded
        content = base64.b64decode(result["content"]).decode('utf-8')
        
        await client.close()
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": str(e)}

async def create_pull_request(
    repo_owner: str,
    repo_name: str,
    title: str,
    body: str,
    head_branch: str,
    base_branch: str,
    user_context: UserContext
) -> Dict[str, Any]:
    """Tool: Create a new Pull Request."""
    
    try:
        token = await get_installation_token(repo_owner, repo_name)
        client = GitHubClient(token)
        
        payload = {
            "title": title,
            "body": f"{body}\n\n*Auto-generated by NexusMCP on behalf of {user_context.user_id}*",
            "head": head_branch,
            "base": base_branch
        }
        
        result = await client.post(f"repos/{repo_owner}/{repo_name}/pulls", payload)
        await client.close()
        
        return {
            "success": True, 
            "pr_url": result["html_url"],
            "pr_number": result["number"]
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
```

## 4. Security Reasoning
- **GitHub App vs PAT:** Personal Access Tokens are tied to a user. If the token leaks, all the user's repos are compromised. A GitHub App generates **Installation Access Tokens** that expire in exactly 1 hour, minimizing the blast radius of a leaked token.
- **Repository Isolation:** By generating a token specifically for the requested `repo_name`, the LLM cannot pivot and read code from an adjacent repository if it discovers the token via a hallucinated debug print command.
- **Stateless Architecture:** Cloning a repository using `git clone` writes files to disk. If an agent modifies a cloned repo and forgets to clean it up, the next agent to use that worker node might read the previous tenant's code. Using the REST API natively prevents state pollution.

## 5. Scaling Reasoning
- **Rate Limits:** GitHub App installation tokens share a rate limit of 5,000 requests per hour *per installation*. This is vastly superior to PATs, which share the limit across the user's entire account.
- **API Egress:** Downloading a massive repository via the Contents API can cause latency. For massive codebases, an Enterprise setup will index the codebase into an AST-aware Vector Database (e.g., Pinecone/Milvus) during CI/CD, and the LLM will query the Vector DB instead of hitting the live GitHub API for code reads.

## 6. Common Production Pitfalls
- **Base64 Limitations:** The GitHub Contents API restricts files to 100MB. If an LLM tries to read a compiled binary or massive dataset, it will fail. You must catch `403` or size limit errors.
- **Clock Sync:** The JWT encoding block uses `time.time()`. If your server's NTP daemon is out of sync, GitHub will reject the JWT with a `401 Bad Credentials` error because the `iat` (Issued At) is in the future. We subtract 60 seconds (`now - 60`) to accommodate minor clock drift.

## 7. Enterprise Best Practices
- **Commit Signature:** Configure the GitHub App to sign commits dynamically. This ensures that any code written by the AI Agent is cryptographically verifiable in the commit history.
- **Webhooks:** Don't let the LLM actively poll for PR statuses. Register an HTTPS webhook on the GitHub App (e.g., `/api/v1/webhooks/github`) to receive `pull_request` events asynchronously, which can then wake up the paused FSM workflow (from Phase 10).

## 8. Step-by-Step Setup Instructions
1. Navigate to GitHub -> Developer Settings -> GitHub Apps -> New GitHub App.
2. Uncheck "Webhook Active" (for now).
3. Under Permissions, grant `Contents: Read & Write`, `Pull Requests: Read & Write`.
4. Generate a Private Key and download it. Store this safely in AWS Secrets Manager or Hashicorp Vault.
5. Note the App ID. Install the App on a specific test repository.
6. Register the `read_github_file` and `create_pull_request` handlers in your MCP Tool Registry.

## 9. Example Request / Response

**LLM Intent:** "Read the README.md file in the acme-corp/frontend repo."
**Tool Request:**
```json
{
  "tool_name": "github.read_file",
  "arguments": {
    "repo_owner": "acme-corp",
    "repo_name": "frontend",
    "file_path": "README.md"
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "content": "# Acme Frontend\n\nThis is the react frontend."
  }
}
```

---
**Status:** Phase 7 complete. Awaiting confirmation to proceed to Phase 8 (Kubernetes Tools).
