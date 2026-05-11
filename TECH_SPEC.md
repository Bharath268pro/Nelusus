"""Phase 1 Technical Specification"""

# MCP SECURITY PROXY - TECHNICAL SPECIFICATION

## 1. SYSTEM OVERVIEW

### 1.1 Purpose
The MCP Security Proxy is a middleware layer that enforces security controls between MCP agents and tools (Salesforce). It implements the "Secure Handshake" protocol.

### 1.2 Key Responsibilities
1. Authentication: Validate JWT tokens
2. Authorization: Enforce OAuth scopes
3. Access Control: Implement row-level security
4. Data Protection: Redact PII
5. Performance: Maintain < 50ms overhead
6. Audit: Log all access decisions

### 1.3 Non-Goals (Phase 1)
- Multi-region deployment
- Rate limiting / throttling
- Custom authentication providers
- End-to-end encryption
- Advanced threat detection

---

## 2. AUTHENTICATION (JWT)

### 2.1 Token Format
Standard JWT with HS256 signature

Header:
```json
{
  "alg": "HS256",
  "typ": "JWT"
}
```

Payload:
```json
{
  "sub": "user_id",
  "email": "user@example.com",
  "org_id": "org_123",
  "iat": 1715425800,
  "exp": 1715512200,
  "iss": "nelusus-security-proxy",
  "aud": "mcp-agents",
  "scopes": ["sfdc:read_account", "sfdc:read_contact"],
  "custom_claims": {}
}
```

### 2.2 Token Validation
- Extract from `Authorization: Bearer <token>` header
- Verify signature with `JWT_SECRET_KEY`
- Check expiration time
- Validate issuer and audience claims
- Return 401 if invalid

### 2.3 Token Lifecycle
- Issued by Auth0/Okta during user login
- TTL: 24 hours (configurable)
- Refresh token flow: Phase 2
- Revocation: Not implemented (Phase 2)

---

## 3. AUTHORIZATION (OAuth Scopes)

### 3.1 Scope Definition
Scopes define what resources a user can access:

```
sfdc:read_account     - Read Salesforce Account records
sfdc:write_account    - Write/update Account records
sfdc:delete_account   - Delete Account records
sfdc:read_contact     - Read Contact records
sfdc:write_contact    - Write Contact records
mcp:admin             - Administrative access (Phase 2)
```

### 3.2 Scope Validation Flow
1. Extract scopes from JWT token
2. Get required scope for the tool
3. Check if user has scope in cache (Redis)
4. If cache miss, fetch from Auth0/Okta
5. Cache result for 5 minutes
6. Return 403 if scope not found

### 3.3 Tool-to-Scope Mapping
```python
{
    "read_salesforce_account": ["sfdc:read_account"],
    "read_salesforce_contact": ["sfdc:read_contact"],
    "write_salesforce_account": ["sfdc:write_account"],
    "write_salesforce_contact": ["sfdc:write_contact"],
}
```

### 3.4 Redis Caching Strategy
- Key: `user_context:{user_id}`
- Value: Serialized UserContext (JSON)
- TTL: 5 minutes (configurable)
- Cache hit rate target: > 90%
- Latency with cache: < 10ms
- Latency without cache: < 50ms

---

## 4. ROW-LEVEL SECURITY (RLS)

### 4.1 RLS Policy Types

#### 4.1.1 Field-Based (Primary Key Filter)
```python
{
    "policy_id": "account_owner_policy",
    "resource": "Account",
    "policy_type": "field_based",
    "filter_conditions": {
        "OwnerId": "{current_user_id}"
    }
}
```

#### 4.1.2 Rule-Based (Multiple Conditions)
```python
{
    "policy_id": "emea_sales_policy",
    "resource": "Account",
    "policy_type": "rule_based",
    "filter_conditions": {
        "Region": "EMEA",
        "Status": "Active"
    }
}
```

#### 4.1.3 Whitelist (Explicit IDs)
```python
{
    "policy_id": "vip_accounts_policy",
    "resource": "Account",
    "policy_type": "whitelist",
    "allowed_row_ids": [
        "001XX000000001",
        "001YY000000002"
    ]
}
```

### 4.2 RLS Evaluation
1. Get user's RLS policies for the resource
2. For each policy:
   - Check if requested row_id matches conditions
   - If any policy denies, return 403
   - Collect PII redaction rules
3. Return authorized + redaction rules

### 4.3 Default Behavior
- No policy = allow access (open model)
- Multiple policies = all must allow (AND logic)
- Can be overridden with configuration

---

## 5. PII REDACTION

### 5.1 Redaction Rules
- Defined in RLS policies
- Fields marked as PII are automatically masked
- Redaction happens before response sent to agent

### 5.2 Redaction Strategies

#### 5.2.1 Email
```
Before: john.doe@acme.com
After:  j***.doe@acme.com
```

#### 5.2.2 Phone Number
```
Before: 555-123-4567
After:  [REDACTED]
```

#### 5.2.3 Street Address
```
Before: 123 Main Street
After:  [REDACTED]
```

#### 5.2.4 Names
```
Before: John Doe
After:  J*** D**
```

### 5.3 Configuration
PII fields per resource type:
```python
REDACTION_RULES = {
    "Account": ["BillingStreet", "BillingCity", "Phone"],
    "Contact": ["Email", "Phone", "MobilePhone"],
    "Lead": ["Email", "Phone", "Street"]
}
```

---

## 6. SALESFORCE INTEGRATION

### 6.1 OAuth 2.0 Flow
- Client: MCP Security Proxy
- Provider: Salesforce
- Grant Type: JWT Bearer (Phase 1) or Username/Password (for dev)
- Scopes: `api full`

### 6.2 Tools (Phase 1)

#### 6.2.1 read_salesforce_account
```
Tool Name: read_salesforce_account
Scope Required: sfdc:read_account
Arguments:
  - account_id (string, required)
Returns:
  Account object with PII redacted
```

#### 6.2.2 read_salesforce_contact
```
Tool Name: read_salesforce_contact
Scope Required: sfdc:read_contact
Arguments:
  - contact_id (string, required)
Returns:
  Contact object with PII redacted
```

---

## 7. API SPECIFICATION

### 7.1 Tool Execution Endpoint

```
POST /api/v1/mcp/tool-call
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

Request Body:
{
  "user_id": "string",
  "auth_token": "string",
  "tool_call": {
    "tool_name": "string",
    "tool_version": "string",
    "arguments": {
      "key": "value"
    },
    "request_id": "string",
    "timestamp": "ISO-8601 datetime"
  },
  "context": {
    "optional": "metadata"
  }
}

Response:
{
  "request_id": "string",
  "status": "success|error",
  "data": {
    "key": "value"
  },
  "error": "error message or null",
  "redaction_applied": boolean,
  "cache_hit": boolean,
  "execution_time_ms": number
}

Status Codes:
  200 OK - Success
  400 Bad Request - Invalid arguments
  401 Unauthorized - Invalid token
  403 Forbidden - Insufficient permissions
  404 Not Found - Resource not found
  500 Internal Server Error - Server error
```

### 7.2 Health Endpoint

```
GET /api/v1/health

Response:
{
  "status": "healthy",
  "service": "mcp-security-proxy"
}
```

---

## 8. PERFORMANCE REQUIREMENTS

### 8.1 Latency Budget
| Component | Target | Notes |
|-----------|--------|-------|
| JWT Validation | < 1ms | Local operation |
| OAuth Check (cached) | < 10ms | Redis lookup |
| OAuth Check (uncached) | < 50ms | API call to Auth0 |
| RLS Evaluation | < 20ms | Policy matching |
| Salesforce API | Variable | External dependency |
| PII Redaction | < 5ms | String manipulation |
| **Total Proxy Overhead** | **< 50ms** | Without Salesforce |

### 8.2 Caching Strategy
- Cache: Redis
- TTL: 5 minutes (scopes), 1 hour (full context)
- Cache key: `{scope_type}:{user_id}:{resource}`
- Cache invalidation: TTL-based

### 8.3 Monitoring
- Track execution_time_ms in every response
- Alert if proxy overhead > 50ms
- Log cache hit rates
- Monitor Redis connection

---

## 9. ERROR HANDLING

### 9.1 Authentication Errors
```json
{
  "status": "error",
  "error": "Invalid or expired token",
  "execution_time_ms": 2.3
}
```
Status: 401 Unauthorized

### 9.2 Authorization Errors
```json
{
  "status": "error",
  "error": "Missing required scope: sfdc:read_account",
  "execution_time_ms": 15.7
}
```
Status: 403 Forbidden

### 9.3 RLS Errors
```json
{
  "status": "error",
  "error": "Not authorized to access this record",
  "execution_time_ms": 18.2
}
```
Status: 403 Forbidden

### 9.4 Tool Errors
```json
{
  "status": "error",
  "error": "Account not found",
  "execution_time_ms": 45.1
}
```
Status: 404 Not Found or 500 Internal Server Error

---

## 10. LOGGING & AUDIT

### 10.1 Audit Events
Every tool access is logged:
```json
{
  "timestamp": "2026-05-11T10:30:45Z",
  "event_type": "tool_access",
  "user_id": "user123",
  "tool_name": "read_salesforce_account",
  "resource_id": "001XX000000000",
  "status": "allowed|denied",
  "reason": "scope_required:sfdc:read_account",
  "execution_time_ms": 35.2
}
```

### 10.2 Logging Levels
- DEBUG: Token validation details, cache hits/misses
- INFO: Tool access events, API calls
- WARNING: Scope mismatches, RLS denials
- ERROR: API errors, unexpected failures

---

## 11. SECURITY ASSUMPTIONS

- JWT tokens are signed with a secret key (not public keys)
- Auth0/Okta is the source of truth for scopes
- Salesforce API returns accurate data
- Network communication is over HTTPS
- Redis password is set (in production)
- Database credentials are secure

---

## 12. FUTURE ENHANCEMENTS (Phase 2+)

- [ ] Public key JWT validation (JWKS)
- [ ] Rate limiting / throttling
- [ ] Request signing / verification
- [ ] Encrypted responses
- [ ] Audit database persistence
- [ ] Multi-region deployment
- [ ] Advanced threat detection
- [ ] Custom redaction rules
- [ ] Data masking (not just redaction)
- [ ] Consent-based access

---

**Document Version**: 1.0
**Date**: May 11, 2026
**Phase**: 1 - Foundation
**Status**: Active Development
