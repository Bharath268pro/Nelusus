# MCP Security Proxy - Phase 1 Architecture

## Overview

The MCP Security Proxy is a stateful middleware that sits between MCP agents and tools (specifically Salesforce). It enforces a "Secure Handshake" that validates:

1. **Authentication (JWT)** - User identity verification
2. **Authorization (OAuth Scopes)** - What resources the user can access
3. **Row-Level Security (RLS)** - Which specific records the user can view
4. **Data Redaction (PII)** - Masking sensitive information before response

## Architecture Diagram

```
┌─────────────────┐
│   MCP Agent     │
│  (Claude, etc)  │
└────────┬────────┘
         │ 1. Tool Request (JWT)
         ▼
┌────────────────────────────────────┐
│   Security Proxy                   │
│                                    │
│ 1. JWT Validation ─────────────┐  │
│ 2. Scope Check (OAuth) ────────┼─ │
│ 3. RLS Validation ─────────────┼─ │
│ 4. PII Redaction ──────────────┼─ │
│ 5. Redis Caching (< 50ms) ─────┼─ │
└─────────────────┬────────────────┘
                  │ 2. Tool Call
                  ▼
┌────────────────────────────────────┐
│   Tool (Salesforce API)            │
│                                    │
│ - read_salesforce_account          │
│ - read_salesforce_contact          │
│ - (more tools in future)           │
└────────────────────────────────────┘
```

## Security Pipeline Details

### 1. JWT Validation (Authentication)

- Extract `Authorization: Bearer <token>` from request
- Decode JWT using HS256 algorithm
- Verify signature and expiration
- Extract user_id, email, scopes from token
- Fail fast if invalid

**Files**: `app/services/__init__.py` (AuthenticationService)

### 2. OAuth Scope Validation

- Check if user has required scope (e.g., `sfdc:read_account`)
- Scope-to-tool mapping:
  - `sfdc:read_account` → `read_salesforce_account`
  - `sfdc:read_contact` → `read_salesforce_contact`
  - `sfdc:write_account` → `write_salesforce_account`
- Redis cache for scope lookup (**target: < 50ms**)
- Fallback to Auth0/Okta API if cache miss

**Files**: `app/services/oauth.py` (OAuthService)

### 3. Row-Level Security (RLS)

User context includes RLS policies that define which rows they can access:

```
Policy: "Account owner can see their accounts"
  Resource: Account
  Type: field_based
  Filter: { OwnerId: user_id }

Policy: "Sales reps can see EMEA region"
  Resource: Account
  Type: rule_based
  Filter: { Region: 'EMEA' }

Policy: "Explicit whitelist for VIP accounts"
  Resource: Account
  Type: whitelist
  AllowedRowIds: ['001XX000...', '001YY000...']
```

For each tool call:
1. Get applicable RLS policies for the resource
2. Check if requested row_id matches policy
3. Collect PII fields that need redaction

**Files**: `app/services/rls.py` (RowLevelSecurityService)

### 4. PII Redaction

After fetching data from Salesforce, redact fields marked as PII:

```python
# Example
record = {
  "Id": "001XX000...",
  "Name": "Acme Corp",
  "Email": "admin@acme.com",        # PII - redact
  "Phone": "555-1234",               # PII - redact
  "BillingStreet": "123 Main St"     # PII - redact
}

# After redaction
{
  "Id": "001XX000...",
  "Name": "Acme Corp",
  "Email": "a*****@acme.com",
  "Phone": "[REDACTED]",
  "BillingStreet": "[REDACTED]"
}
```

**Files**: `app/services/rls.py` (RowLevelSecurityService.redact_record)

## Phase 1 Timeline

### Week 1: Architecture Design Review & Schema Definition
- ✅ Schema definition for Security Proxy
- ✅ Pydantic models for MCP protocol
- ✅ Security models (JWT, OAuth, RLS)
- Documentation of architecture

**Deliverable**: This document + all model definitions

### Week 2: FastAPI Backend Scaffolding
- ✅ FastAPI application setup
- ✅ Uvicorn configuration
- ✅ Service layer implementation
  - AuthenticationService
  - OAuthService
  - RLSService
  - SalesforceService
- ✅ Middleware for request handling
- ✅ Route handlers for tool execution
- Redis integration

**Deliverable**: Runnable backend with `/api/v1/mcp/tool-call` endpoint

### Week 3: Next.js Frontend Setup
- Next.js project with TypeScript
- Tailwind CSS + Shadcn UI setup
- Auth0/Okta integration
- JWT token management
- Testing

**Deliverable**: Login page + tool execution UI

### Week 4: Salesforce Integration & "Hello World" Sync
- Salesforce OAuth 2.0 setup
- read_salesforce_account tool implementation
- End-to-end test: user authenticates → tool fetches account → result redacted
- Performance testing

**Deliverable**: Working "Hello World" sync with metrics

## Risk Mitigation

### Risk 1: Latency from Proxy
**Target**: < 50ms overhead

**Mitigation**:
- Redis caching for OAuth token validation
- Cache TTL = 5 minutes for scopes
- Async/await throughout
- No blocking I/O

**Monitoring**:
- Execution time tracked in `MCPResponse.execution_time_ms`
- Alert if > 50ms

### Risk 2: Token Expiration
**Mitigation**:
- Implement refresh token flow
- Token TTL = 24 hours (configurable)
- Graceful error when token expired

### Risk 3: RLS Policy Misconfiguration
**Mitigation**:
- Comprehensive test suite for RLS logic
- Audit logging of all access decisions
- Default-deny policy (fail closed)

### Risk 4: PII Exposure
**Mitigation**:
- RLS policies explicitly define which fields are PII
- Redaction applied to ALL responses
- Regular security audit of redaction rules

## Configuration

See `.env.example` for all configuration variables:

```
# JWT
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Auth0/Okta
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_CLIENT_ID=your-client-id
AUTH0_CLIENT_SECRET=your-client-secret

# Redis (for caching)
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_CACHE_TTL=3600

# Salesforce
SALESFORCE_CLIENT_ID=your-client-id
SALESFORCE_CLIENT_SECRET=your-client-secret
SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com
```

## Running the Backend

```bash
cd backend

# Install dependencies
pip install -r requirements.txt

# Copy .env
cp .env.example .env
# Edit .env with your values

# Run development server
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run tests
pytest
```

## API Endpoints

### Health Check
```
GET /api/v1/health
Response: { "status": "healthy", "service": "mcp-security-proxy" }
```

### Tool Execution
```
POST /api/v1/mcp/tool-call
Authorization: Bearer <JWT>
Content-Type: application/json

{
  "user_id": "user123",
  "auth_token": "eyJhbGc...",
  "tool_call": {
    "tool_name": "read_salesforce_account",
    "tool_version": "1.0",
    "arguments": { "account_id": "001XX000..." },
    "request_id": "req_123",
    "timestamp": "2026-05-11T10:30:00Z"
  }
}

Response:
{
  "request_id": "req_123",
  "status": "success",
  "data": { /* redacted Salesforce record */ },
  "redaction_applied": true,
  "cache_hit": false,
  "execution_time_ms": 35.2
}
```

## Next Steps

1. **Week 1 tasks** (this document):
   - [ ] Review architecture with stakeholders
   - [ ] Approve schema definitions
   - [ ] Finalize JWT structure

2. **Week 2 tasks**:
   - [ ] Set up Redis instance
   - [ ] Implement complete OAuthService
   - [ ] Add audit logging
   - [ ] Write comprehensive tests

3. **Week 3 tasks**:
   - [ ] Frontend scaffolding
   - [ ] Auth0/Okta setup
   - [ ] Integration tests

4. **Week 4 tasks**:
   - [ ] Salesforce OAuth setup
   - [ ] End-to-end "Hello World" test
   - [ ] Performance testing & optimization
