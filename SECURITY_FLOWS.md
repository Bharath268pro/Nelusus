"""SECURE HANDSHAKE - Visual Flow Diagram"""

# ============================================================================
# PHASE 1: MCP SECURITY PROXY - REQUEST FLOW
# ============================================================================

## FLOW 1: SUCCESSFUL REQUEST WITH PII REDACTION

```
┌─────────────────────────────────────────────────────────────────────┐
│ Agent (Claude) sends tool request                                   │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ POST /api/v1/mcp/tool-call                                          │
│ Authorization: Bearer eyJhbGc...                                    │
│ {                                                                   │
│   "user_id": "user123",                                             │
│   "auth_token": "eyJhbGc...",                                       │
│   "tool_call": {                                                    │
│     "tool_name": "read_salesforce_account",                         │
│     "arguments": {"account_id": "001XX000000000"},                  │
│     "request_id": "req_001"                                         │
│   }                                                                 │
│ }                                                                   │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
            ┌───────────▼───────────┐
            │ 🔐 SECURITY PIPELINE  │
            └───────────┬───────────┘
                        │
            ┌───────────▼───────────────────────┐
            │ 1️⃣  JWT VALIDATION                │
            │ Extract & decode token            │
            │ ✓ Signature valid                 │
            │ ✓ Token not expired               │
            │ ✓ Issuer & audience match         │
            └───────────┬───────────────────────┘
                        │
            ┌───────────▼───────────────────────┐
            │ 2️⃣  SCOPE VALIDATION              │
            │ Required: sfdc:read_account       │
            │ ┌─────────────────────────────┐   │
            │ │ Check Redis cache           │   │
            │ │ Key: user_context:user123   │   │
            │ └──────────┬──────────────────┘   │
            │            │                      │
            │            ├─→ ✓ Cache hit        │
            │            │   (10ms)             │
            │            │                      │
            │            └─→ ✗ Cache miss       │
            │                → fetch Auth0/Okta │
            │                (45ms)              │
            └───────────┬───────────────────────┘
                        │
            ┌───────────▼───────────────────────┐
            │ 3️⃣  RLS VALIDATION                │
            │ Get user RLS policies             │
            │ Check if user can access this row │
            │ Collect PII redaction rules       │
            │ ✓ User owns Account 001XX000000   │
            │ ✓ PII fields: [Email, Phone]      │
            └───────────┬───────────────────────┘
                        │
            ┌───────────▼───────────────────────┐
            │ 4️⃣  SALESFORCE FETCH              │
            │ GET /services/data/v57.0/        │
            │  sobjects/Account/001XX000000     │
            │ Authorization: Bearer sfdc_token  │
            │ ✓ Found account                   │
            └───────────┬───────────────────────┘
                        │
            ┌───────────▼───────────────────────┐
            │ 5️⃣  PII REDACTION                 │
            │ Original:                         │
            │ {                                 │
            │   "Name": "Acme Corp",            │
            │   "Email": "admin@acme.com",      │
            │   "Phone": "555-1234",            │
            │   "Revenue": 1000000              │
            │ }                                 │
            │                                   │
            │ Redacted (by policy):             │
            │ {                                 │
            │   "Name": "Acme Corp",            │
            │   "Email": "a****@acme.com",      │
            │   "Phone": "[REDACTED]",          │
            │   "Revenue": 1000000              │
            │ }                                 │
            └───────────┬───────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ 200 OK                                                              │
│ {                                                                   │
│   "request_id": "req_001",                                          │
│   "status": "success",                                              │
│   "data": {                                                         │
│     "id": "001XX000000000",                                         │
│     "Name": "Acme Corp",                                            │
│     "Email": "a****@acme.com",      ← REDACTED                      │
│     "Phone": "[REDACTED]",          ← REDACTED                      │
│     "Revenue": 1000000                                              │
│   },                                                                │
│   "redaction_applied": true,                                        │
│   "cache_hit": true,                                                │
│   "execution_time_ms": 35.2                                         │
│ }                                                                   │
└───────────────────────┬─────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Agent receives secured, redacted data                              │
│ PII is masked, RLS enforced, all audited                           │
└─────────────────────────────────────────────────────────────────────┘
```

---

## FLOW 2: AUTHORIZATION DENIED (Missing Scope)

```
Request → JWT Validation ✓
        → Scope Validation ✗
        
┌─────────────────────────────────────────────┐
│ User lacks required scope                    │
│ Required: sfdc:read_account                  │
│ User has: [sfdc:read_contact]                │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│ 403 Forbidden                                │
│ {                                            │
│   "request_id": "req_001",                   │
│   "status": "error",                         │
│   "error": "Missing required scope:          │
│             sfdc:read_account",              │
│   "execution_time_ms": 12.5                  │
│ }                                            │
└─────────────────────────────────────────────┘
```

---

## FLOW 3: RLS DENIED (Row Access Denied)

```
Request → JWT Validation ✓
        → Scope Validation ✓
        → RLS Validation ✗
        
┌──────────────────────────────────────────────┐
│ User cannot access this Account               │
│ User policies:                                 │
│  - OwnerId = user123 (doesn't match)          │
│  - Region = EMEA (this is APAC)               │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────┐
│ 403 Forbidden                                 │
│ {                                             │
│   "request_id": "req_001",                    │
│   "status": "error",                          │
│   "error": "Not authorized to access this     │
│             record",                          │
│   "execution_time_ms": 18.3                   │
│ }                                             │
└──────────────────────────────────────────────┘
```

---

## FLOW 4: Invalid Token

```
Request → JWT Validation ✗
        
┌──────────────────────────────────────────────┐
│ Token is expired or signature is invalid       │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────┐
│ 401 Unauthorized                              │
│ {                                             │
│   "request_id": "req_001",                    │
│   "status": "error",                          │
│   "error": "Invalid or expired token",        │
│   "execution_time_ms": 2.1                    │
│ }                                             │
└──────────────────────────────────────────────┘
```

---

## FLOW 5: SALESFORCE API ERROR

```
Request → JWT ✓ → Scope ✓ → RLS ✓ → Salesforce API ✗

┌──────────────────────────────────────────────┐
│ Salesforce returns 404 Not Found              │
└─────────────────┬──────────────────────────┘
                  │
                  ▼
┌──────────────────────────────────────────────┐
│ 404 Not Found                                 │
│ {                                             │
│   "request_id": "req_001",                    │
│   "status": "error",                          │
│   "error": "Account 001XX000000000 not        │
│             found",                           │
│   "execution_time_ms": 45.7                   │
│ }                                             │
└──────────────────────────────────────────────┘
```

---

## DECISION TREE: REQUEST AUTHORIZATION

```
                         ┌────────────────────────────┐
                         │ Request arrives            │
                         └────────────┬───────────────┘
                                      │
                         ┌────────────▼───────────────┐
                         │ Is JWT token valid?        │
                         └──┬──────────────────────┬──┘
                           NO                     YES
                            │                      │
                ┌───────────┐│ 401 Unauthorized    │
                │ ✗ DENIED  ││ Invalid token       ▼
                └───────────┘│                     
                             │         ┌────────────────────────────┐
                             │         │ Has required OAuth scope?   │
                             │         └──┬──────────────────────┬──┘
                             │           NO                     YES
                             │            │                      │
                             │ ┌──────────┐│ 403 Forbidden       │
                             │ │ ✗ DENIED ││ Missing scope       ▼
                             │ └──────────┘│                     
                             │             │     ┌────────────────────────────┐
                             │             │     │ RLS allows this row access? │
                             │             │     └──┬──────────────────────┬──┘
                             │             │       NO                     YES
                             │             │        │                      │
                             │             │ ┌──────────┐                  │
                             │             │ │ ✗ DENIED ││ 403 Forbidden   ▼
                             │             │ └──────────┘│ RLS denies      
                             │             │             │ ┌────────────────────────────┐
                             │             │             │ │ Can fetch from Salesforce?  │
                             │             │             │ └──┬──────────────────────┬──┘
                             │             │             │   NO                    YES
                             │             │             │    │                     │
                             │             │             │ ┌──────────┐             │
                             │             │             │ │ ✗ DENIED ││ 404/500     ▼
                             │             │             │ └──────────┘│ Not found/
                             │             │             │             │ Server error
                             │             │             │     ┌──────────────────┐
                             │             │             │     │ 200 OK            │
                             │             │             │     │ ✓ ALLOWED         │
                             │             │             │     │ (redacted data)   │
                             │             │             │     └──────────────────┘
```

---

## LATENCY BREAKDOWN (Typical Request)

```
Total Request Time: 35ms

┌─────────────────────────────────────────────┐
│ Timeline (milliseconds)                      │
├──────┬──────┬──────┬──────┬──────────────────┤
│ 0-2  │ 2-12 │ 12-30│ 30-35│ Total           │
├──────┼──────┼──────┼──────┼──────────────────┤
│ JWT  │Scope │ RLS  │SFDC+ │ Proxy overhead: │
│Val   │Check │Check │PII   │ ~12ms (excl.    │
│      │      │      │      │ Salesforce)     │
│      │      │      │      │                 │
│ ✓1ms │✓10ms │✓18ms │✓5ms  │ Cache hit!      │
└──────┴──────┴──────┴──────┴──────────────────┘

Breakdown:
  JWT Validation:     1ms   (signature check)
  Scope Check:        10ms  (Redis cache hit)
  RLS Evaluation:     18ms  (policy matching)
  Salesforce API:     Variable (external)
  PII Redaction:      5ms   (string manipulation)
  Network Overhead:   1ms   (round trips)
  ─────────────────────────
  TOTAL:              35ms  ✓ Under 50ms!
```

---

## REDIS CACHING FLOW

```
Request #1:
  User Context cache MISS
  ├─ Query Redis: user_context:user123 → NOT FOUND
  ├─ Fetch from Auth0/Okta API (~40ms)
  ├─ Parse OAuth scopes
  ├─ Store in Redis with 5min TTL
  └─ Return to agent (50ms total)

Request #2 (within 5 min):
  User Context cache HIT
  ├─ Query Redis: user_context:user123 → FOUND
  ├─ Deserialize JSON
  ├─ Return to agent (10ms total)
  └─ Saves 40ms! ✓

After 5 minutes:
  Redis entry expires → Next request will fetch fresh data
```

---

## SECURITY LAYERS (Defense in Depth)

```
                 ┌─────────────────────┐
                 │ MCP Agent           │
                 │ (Potentially          │
                 │  Untrusted)          │
                 └──────────┬──────────┘
                            │
              ┌─────────────▼──────────────┐
              │ LAYER 1: Authentication    │
              │ JWT signature validation   │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │ LAYER 2: Authorization     │
              │ OAuth scope validation     │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │ LAYER 3: Access Control    │
              │ Row-level security (RLS)   │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │ LAYER 4: Data Protection   │
              │ PII redaction              │
              └─────────────┬──────────────┘
                            │
              ┌─────────────▼──────────────┐
              │ LAYER 5: Audit             │
              │ Log all access decisions   │
              └─────────────┬──────────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Salesforce API      │
                 │ (Trusted Source)    │
                 └─────────────────────┘
```

---

## DEPLOYMENT CHECKLIST

- [ ] JWT_SECRET_KEY configured (change from default)
- [ ] Auth0/Okta credentials configured
- [ ] Salesforce OAuth configured
- [ ] Redis instance running
- [ ] Database backups configured
- [ ] Logging configured to centralized system
- [ ] Monitoring/alerting configured
- [ ] Load testing passed
- [ ] Security audit completed
- [ ] Documentation reviewed

---

**Visual Guide Version**: 1.0
**Last Updated**: May 11, 2026
