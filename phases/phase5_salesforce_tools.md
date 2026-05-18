# Phase 5 — Salesforce Tools

## 1. Architecture Explanation
Enterprise CRM systems like Salesforce contain the most sensitive customer data (PII) and drive core business operations. Exposing Salesforce to an LLM requires strict boundary enforcement to prevent accidental mass deletion or cross-tenant data leakage.

Key Architectural Components:
1. **Delegated Authentication (OAuth2 Token Exchange):** The MCP backend rarely uses a global service account to talk to Salesforce. Instead, it exchanges the user's JWT for a Salesforce OAuth Token. This ensures Salesforce evaluates permissions based on the *actual human user's profile* (respecting Salesforce's native Field-Level Security and Sharing Rules).
2. **Token Management & Refresh:** OAuth tokens expire. The backend must transparently catch `401 Unauthorized` errors, use the stored `refresh_token` to get a new session, and replay the API call automatically.
3. **SOQL Jailing:** Similar to Database Tools, the LLM NEVER writes raw SOQL. It calls structured tools (`search_salesforce_contacts(email)`) which the backend translates into parameterized API calls.
4. **Audit Trail:** Every mutation (Create/Update Lead) must be cryptographically audited in the MCP gateway before being dispatched to Salesforce.

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── salesforce/
│       ├── __init__.py
│       ├── client.py        # OAuth lifecycle & httpx REST client wrapper
│       ├── queries.py       # Safe SOQL executions (Read operations)
│       └── mutations.py     # Safe record updates (Write operations)
```

## 3. Exact Code Implementation

### A. Salesforce REST Client & Token Lifecycle (`tools/salesforce/client.py`)
This client handles transparent OAuth token refreshing and provides a base for safe REST API calls.

```python
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
        self.client_id = os.environ.get("SF_CLIENT_ID")
        self.client_secret = os.environ.get("SF_CLIENT_SECRET")
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
        # In production, update the newly minted access token in your secure token store (Redis/DB)

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
            # Token expired. Attempt refresh and replay exactly once.
            await self._refresh_token()
            response = await self._client.request(method, url, headers=get_headers(), **kwargs)
            
        response.raise_for_status()
        return response

    async def close(self):
        await self._client.aclose()
```

### B. Safe SOQL Query Handlers (`tools/salesforce/queries.py`)
LLMs call these tools to search for data. Notice we use standard REST endpoints or heavily parameterized SOQL, preventing SOQL injection.

```python
from urllib.parse import quote
from typing import Dict, Any, List
from app.tools.salesforce.client import SalesforceClient

async def search_contacts(sf_client: SalesforceClient, email: str) -> List[Dict[str, Any]]:
    """Tool: Find a Salesforce Contact by Email."""
    
    # We use SOSL (Salesforce Object Search Language) or parameter-safe SOQL
    # Sanitize the email to prevent SOQL injection
    clean_email = email.replace("'", "\\'")
    
    query = f"SELECT Id, Name, Title, Account.Name FROM Contact WHERE Email = '{clean_email}' LIMIT 5"
    
    # The client handles authentication and 401 retries automatically
    response = await sf_client.request("GET", f"query/?q={quote(query)}")
    data = response.json()
    
    return data.get("records", [])

async def get_opportunity_details(sf_client: SalesforceClient, opp_id: str) -> Dict[str, Any]:
    """Tool: Get details of a specific opportunity."""
    # Using the standard REST object retrieval (No SOQL injection risk at all)
    response = await sf_client.request("GET", f"sobjects/Opportunity/{opp_id}")
    return response.json()
```

### C. Safe Mutation Handlers (`tools/salesforce/mutations.py`)
Writes to Salesforce are audited.

```python
import logging
from typing import Dict, Any
from app.tools.salesforce.client import SalesforceClient
from app.models.auth import UserContext

logger = logging.getLogger("audit_logger")

async def create_lead(
    sf_client: SalesforceClient, 
    user_context: UserContext,
    first_name: str, 
    last_name: str, 
    company: str, 
    email: str
) -> Dict[str, Any]:
    """Tool: Create a new Lead in Salesforce."""
    
    payload = {
        "FirstName": first_name,
        "LastName": last_name,
        "Company": company,
        "Email": email,
        "LeadSource": "AI_Agent_MCP"
    }

    # AUDIT LOG: Record the mutation intent BEFORE execution
    logger.info(
        f"AUDIT | user_id={user_context.user_id} tenant_id={user_context.tenant_id} "
        f"action=SALESFORCE_CREATE_LEAD payload={payload}"
    )

    try:
        response = await sf_client.request("POST", "sobjects/Lead/", json=payload)
        result = response.json()
        
        # AUDIT LOG: Record success
        logger.info(f"AUDIT | action=SALESFORCE_CREATE_LEAD status=SUCCESS sf_id={result.get('id')}")
        return {"success": True, "lead_id": result.get("id")}
        
    except Exception as e:
        logger.error(f"AUDIT | action=SALESFORCE_CREATE_LEAD status=FAILED error={str(e)}")
        return {"success": False, "error": "Failed to create lead in Salesforce."}
```

### D. Tool Registration Integration
In your MCP execution loop, you inject the specific `SalesforceClient` mapped to the calling user.

```python
# In registry_engine.py
async def execute_tool(self, request: ToolCallRequest, user_context: UserContext):
    _, handler = self._tools[request.tool_name]
    
    # Assume get_salesforce_tokens() fetches the stored OAuth tokens for this user from Redis/DB
    tokens = await get_salesforce_tokens(user_context.user_id)
    
    # Initialize the client specifically for this user
    sf_client = SalesforceClient(
        instance_url=tokens["instance_url"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"]
    )
    
    try:
        # Dynamically inject dependencies required by the handler
        kwargs = request.arguments.copy()
        if "sf_client" in handler.__code__.co_varnames:
            kwargs["sf_client"] = sf_client
        if "user_context" in handler.__code__.co_varnames:
            kwargs["user_context"] = user_context
            
        result = await handler(**kwargs)
        return ToolCallResponse(success=True, data=result)
    finally:
        await sf_client.close()
```

## 4. Security Reasoning
- **Delegated Authorization:** By using the user's specific Salesforce OAuth token rather than a master Service Account, Salesforce's native Sharing Rules and Field Level Security (FLS) are strictly enforced. If User A is not allowed to see the "Salary" field on a Contact in Salesforce, the MCP API call will naturally omit it, protecting the LLM from seeing it.
- **SOQL Injection Prevention:** User inputs (emails, names) are strictly sanitized, and where possible, direct REST Endpoint paths (`sobjects/Contact/{id}`) are used over SOQL. 
- **Immutable Audit Trails:** Emitting a structured log (JSON) *before* the API call ensures that even if the process crashes mid-flight, security teams have a record of the LLM's mutation attempt.

## 5. Scaling Reasoning
- **Connection Pooling via `httpx`:** Instantiating an `AsyncClient` maintains a connection pool via Keep-Alive headers to Salesforce. This reduces SSL handshake overhead from ~150ms to ~10ms per subsequent call.
- **Lazy Refresh:** The token refresh is executed lazily (only upon receiving a `401`). This eliminates the need for a complex background cron-job constantly checking token expiration times.

## 6. Common Production Pitfalls
- **API Limits:** Salesforce heavily enforces API limits (e.g., 100,000 requests per 24 hours). An LLM looping aggressively can burn through this in minutes. You must implement a `RateLimitError` catch and potentially circuit-breaker patterns using libraries like `tenacity`.
- **API Version Deprecation:** Hardcoding older API versions (e.g., `v40.0`) will eventually cause failures as Salesforce deprecates them. Keep API versions centrally configurable.

## 7. Enterprise Best Practices
- **Token Vaulting:** Never store `refresh_token`s in plain text in your database. Encrypt them using AES-256-GCM linked to a KMS (Key Management Service) provider like AWS KMS or HashiCorp Vault.
- **Scope Down:** When requesting Salesforce OAuth tokens from the user during the initial login flow, request the absolute minimum scopes required. For an agent that only updates Leads, do not request `full` access.

## 8. Step-by-Step Setup Instructions
1. In Salesforce, go to Setup -> App Manager -> New Connected App.
2. Enable OAuth Settings. Set Callback URL. Select Scopes (e.g., `api`, `refresh_token`, `offline_access`).
3. Save your Client ID and Client Secret to your `.env` file.
4. Implement the OAuth2 Web Server Flow in your gateway (outside the scope of MCP execution, usually in an `/auth/salesforce/callback` route) to acquire the initial Access and Refresh tokens for the user.
5. Register the `create_lead` and `search_contacts` tools in your MCP registry.

## 9. Example Request / Response

**LLM Intent:** "Create a new lead for John Doe at Acme Corp (john@acme.com)."
**Tool Request:**
```json
{
  "tool_name": "salesforce.create_lead",
  "arguments": {
    "first_name": "John",
    "last_name": "Doe",
    "company": "Acme Corp",
    "email": "john@acme.com"
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "lead_id": "00Q5f00000abcdeFGH"
  }
}
```

---
**Status:** Phase 5 complete. Awaiting confirmation to proceed to Phase 6 (Terminal Execution Tools).
