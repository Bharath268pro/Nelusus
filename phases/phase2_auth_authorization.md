# Phase 2 — Authentication + Authorization

## 1. Architecture Explanation
When an enterprise LLM agent accesses internal systems, **Authentication (Who are you?)** and **Authorization (What are you allowed to do?)** become the most critical security boundaries.

In an MCP gateway, the LLM itself doesn't possess permissions. Instead, it acts *on behalf of a user* (Delegated Authorization) or *on behalf of a system* (Service Account). 

We secure the platform using:
1. **Stateless JWTs (JSON Web Tokens):** Issued by an Identity Provider (Auth0, Okta, Azure AD). The MCP Gateway verifies the RS256 signature using a cached JWKS (JSON Web Key Set).
2. **RBAC + Scopes:** The JWT contains `scopes` (e.g., `salesforce:read`) and `roles`. The registry strictly enforces these before a tool executes.
3. **Tenant Isolation:** Multi-tenant systems extract a `tenant_id` from the token and inject it into the `RequestContext`. Every downstream database or API call automatically appends `tenant_id=XYZ` to prevent data leakage.

## 2. Folder Structure
```text
backend/app/
├── core/
│   └── security.py          # JWKS fetching, JWT validation logic
├── middleware/
│   └── auth_middleware.py   # FastAPI Middleware to intercept all requests
├── models/
│   └── auth.py              # UserContext and Permission schemas
└── dependencies/
    └── auth.py              # FastAPI Depends() for route-level enforcement
```

## 3. Exact Code Implementation

### A. Data Contracts (`models/auth.py`)
```python
from typing import List, Optional
from pydantic import BaseModel

class UserContext(BaseModel):
    """The identity injected into every request."""
    user_id: str
    tenant_id: str
    roles: List[str]
    scopes: List[str]
    email: Optional[str] = None
```

### B. Core Security (`core/security.py`)
This securely validates the JWT using `authlib` or `PyJWT`. It requires verifying the issuer, audience, and the RSA signature.

```python
import jwt
import logging
from fastapi import HTTPException
from app.models.auth import UserContext

logger = logging.getLogger(__name__)

# In production, fetch this dynamically from Auth0/Okta via /.well-known/jwks.json
# and cache it in Redis.
MOCK_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----...-----END PUBLIC KEY-----"""

def verify_jwt(token: str, expected_audience: str, expected_issuer: str) -> UserContext:
    """Verifies the RS256 JWT and extracts the user context."""
    try:
        payload = jwt.decode(
            token,
            MOCK_PUBLIC_KEY,
            algorithms=["RS256"],
            audience=expected_audience,
            issuer=expected_issuer
        )
        
        # Enterprise tokens often use custom claims for tenant/roles
        return UserContext(
            user_id=payload.get("sub"),
            tenant_id=payload.get("https://yourdomain.com/tenant_id", "default"),
            roles=payload.get("https://yourdomain.com/roles", []),
            scopes=payload.get("scope", "").split(" "),
            email=payload.get("email")
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        logger.error(f"Invalid JWT: {e}")
        raise HTTPException(status_code=401, detail="Invalid authentication token")
```

### C. FastAPI Dependencies (`dependencies/auth.py`)
We use FastAPI's dependency injection to require authentication on specific endpoints.

```python
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import verify_jwt
from app.models.auth import UserContext

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> UserContext:
    """Extracts and validates the JWT from the Authorization header."""
    # Read from environment variables in production
    audience = "api://nexusmcp"
    issuer = "https://your-tenant.auth0.com/"
    
    return verify_jwt(credentials.credentials, audience, issuer)

def require_scope(required_scope: str):
    """Factory dependency to enforce specific OAuth scopes."""
    def scope_checker(user: UserContext = Depends(get_current_user)) -> UserContext:
        if required_scope not in user.scopes:
            raise HTTPException(
                status_code=403, 
                detail=f"Missing required scope: {required_scope}"
            )
        return user
    return scope_checker
```

### D. Securing the Tool Registry (`routes/mcp.py`)
Now we update Phase 1's route to enforce authorization.

```python
from fastapi import APIRouter, Depends
from app.dependencies.auth import get_current_user, require_scope
from app.models.auth import UserContext
from app.models.mcp_registry import ToolCallRequest, ToolCallResponse

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

@router.post("/execute", response_model=ToolCallResponse)
async def execute_tool(
    request: ToolCallRequest,
    # 1. Enforce valid JWT
    user: UserContext = Depends(get_current_user),
    # 2. Require base MCP execution scope
    _: UserContext = Depends(require_scope("mcp:execute"))
):
    """
    The orchestrator hits this with a valid JWT.
    The tool executor can now access `user.tenant_id` to enforce RLS.
    """
    
    # Example: Dynamic RBAC check based on the requested tool
    if request.tool_name.startswith("salesforce.") and "salesforce:write" not in user.scopes:
        return ToolCallResponse(success=False, error="Forbidden: Missing salesforce scopes")

    # In a real system, you pass `user` into `execute_tool` so the connector
    # knows WHICH tenant's data to query.
    return await registry.execute_tool(request, user_context=user)
```

## 4. Security Reasoning
- **Never Trust the Client/LLM:** The LLM might generate a payload saying `{"tenant_id": "admin"}`. By extracting identity cryptographically from the RS256 JWT, we ignore LLM-provided identity parameters.
- **Audience & Issuer Validation:** Prevents "confused deputy" attacks where a valid token minted for an entirely different application is replayed against your MCP gateway.
- **Short-lived Tokens:** JWTs should expire quickly (e.g., 15 minutes). The client orchestrator handles refresh tokens, ensuring the MCP backend never deals with long-lived session state.

## 5. Scaling Reasoning
- **Statelessness:** Because JWTs contain the claims (tenant, roles), the backend does not need to perform a database lookup to authenticate the user. This saves massive DB overhead on every tool execution.
- **JWKS Caching:** Fetching the public keys (`jwks.json`) from Auth0 blocks the thread. In production, fetch this asynchronously in a background task and cache it in Redis or memory, updating it only when a kid (Key ID) is not found.

## 6. Common Production Pitfalls
- **Clock Skew:** Distributed systems have slightly different clocks. Always allow a `leeway` of ~30 seconds when verifying `exp` (expiration) and `nbf` (not before) claims.
- **Leaking PII:** Never put sensitive data (SSNs, API keys) inside the JWT payload, as it is merely Base64 encoded, not encrypted.

## 7. Enterprise Best Practices
- **Token Exchange (RFC 8693):** If your MCP gateway needs to call a downstream system (like Salesforce) on behalf of the user, use the JWT to perform an OAuth2 Token Exchange to get a system-specific scoped token, rather than using a global service account.
- **Audit Logging:** Every successful AND failed authorization attempt must be logged with the JWT's `sub` (user_id) and `jti` (JWT ID) for compliance (SOC2/HIPAA).

## 8. Step-by-Step Setup Instructions
1. Create an API in Auth0 or Okta. Note the Audience and Issuer.
2. Install dependencies: `pip install PyJWT cryptography`.
3. Add the code above to your folder structure.
4. Update `main.py` to handle `HTTPException` globally to return clean 401/403 JSON responses.

## 9. Testing Instructions
Generate a test JWT using `jwt.io` (signed with a test HS256 secret for local dev, though RS256 is required for production).

```bash
# Valid Request
curl -X POST http://localhost:8000/api/v1/mcp/execute \
     -H "Authorization: Bearer eyJhbGci..." \
     -H "Content-Type: application/json" \
     -d '{"tool_name": "weather.get", "arguments": {}}'

# Expect 401
curl -X POST http://localhost:8000/api/v1/mcp/execute \
     -H "Content-Type: application/json" \
     -d '{"tool_name": "weather.get"}'
```

---
**Status:** Phase 2 complete. Awaiting confirmation to proceed to Phase 3 (Filesystem Tools).
