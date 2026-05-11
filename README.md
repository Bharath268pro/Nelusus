# README - MCP Security Proxy

> Secure Gateway for MCP Agents accessing Salesforce

## 🔐 Phase 1: Foundation & Security Proxy

This is the foundational phase of the MCP Security Proxy project. The goal is to establish a "Secure Handshake" between MCP agents and tools (Salesforce) with comprehensive security controls.

### 🎯 Phase 1 Objectives

1. **Authentication** - Validate JWT tokens from agents
2. **Authorization** - Enforce OAuth scopes for tool access
3. **Row-Level Security** - Control which records users can access
4. **Data Redaction** - Mask PII before returning data to agents
5. **Performance** - Maintain < 50ms proxy overhead via Redis caching

### 📋 Project Status

| Week | Goal | Status |
|------|------|--------|
| 1 | Architecture & Schema Definition | ✅ Complete |
| 2 | FastAPI Backend Scaffolding | 🔄 In Progress |
| 3 | Next.js Frontend Setup | ⏳ Not Started |
| 4 | Salesforce Integration & "Hello World" | ⏳ Not Started |

## 🏗️ Architecture

```
Agent → Security Proxy → Salesforce API
        ↓
        1. JWT Validation
        2. OAuth Scopes Check
        3. RLS Verification
        4. PII Redaction
        5. Tool Execution
        6. Redis Caching
```

See `docs/ARCHITECTURE.md` for detailed system design.

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Redis 6.0+
- Docker & Docker Compose (optional)

### Local Development

```bash
# Backend setup
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Copy and edit environment
cp .env.example .env
# Edit .env with your Auth0, Salesforce, Redis credentials

# Run backend
python -m uvicorn app.main:app --reload --port 8000

# Run tests
pytest
```

### Using Docker

```bash
docker-compose up
```

This starts:
- FastAPI backend: http://localhost:8000
- Redis cache: localhost:6379
- PostgreSQL: localhost:5432

See `SETUP.md` for detailed setup instructions.

## 📁 Project Structure

```
Nelusus/
├── backend/                  # FastAPI application
│   ├── app/
│   │   ├── models/          # Pydantic schemas
│   │   ├── services/        # Business logic
│   │   ├── routes/          # API endpoints
│   │   ├── middleware/      # Request/response handling
│   │   ├── utils/           # Helper utilities
│   │   ├── config.py        # Configuration
│   │   └── main.py          # FastAPI app
│   ├── tests/               # Unit tests
│   ├── requirements.txt     # Python dependencies
│   ├── .env.example         # Environment template
│   └── Dockerfile           # Container image
├── frontend/                # Next.js application (Phase 3)
│   └── src/
├── docs/
│   └── ARCHITECTURE.md      # System design
├── SETUP.md                 # Development setup guide
├── PROGRESS.md              # Phase tracking
└── docker-compose.yml       # Local dev environment
```

## 🔑 Key Services

### AuthenticationService
Validates JWT tokens from the request header.

```python
from app.services import AuthenticationService

token = AuthenticationService.create_token(
    user_id="user123",
    email="user@example.com",
    scopes=["sfdc:read_account"]
)
```

### OAuthService
Checks if user has required OAuth scopes. Caches results in Redis.

```python
authorized, missing_scope = await oauth_service.validate_scopes(
    user_id="user123",
    required_scopes=["sfdc:read_account"]
)
```

### RowLevelSecurityService
Validates row-level access and applies PII redaction.

```python
result = rls_service.check_row_access(
    user_context=user_context,
    resource_type="Account",
    row_id="001XX000..."
)

redacted_data = rls_service.redact_record(
    record=salesforce_data,
    redaction_rules=result.redaction_rules
)
```

## 📊 API Endpoints

### Health Check
```
GET /api/v1/health
```

### Tool Execution (Main Endpoint)
```
POST /api/v1/mcp/tool-call
Authorization: Bearer <JWT>
Content-Type: application/json

Request:
{
  "user_id": "user123",
  "auth_token": "eyJhbGc...",
  "tool_call": {
    "tool_name": "read_salesforce_account",
    "arguments": { "account_id": "001XX000..." },
    "request_id": "req_123",
    "timestamp": "2026-05-11T10:30:00Z"
  }
}

Response:
{
  "request_id": "req_123",
  "status": "success",
  "data": { /* redacted record */ },
  "redaction_applied": true,
  "execution_time_ms": 35.2
}
```

## ⚙️ Configuration

Environment variables in `.env`:

```
# Security
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Auth0/Okta
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_CLIENT_ID=your-client-id
AUTH0_CLIENT_SECRET=your-client-secret

# Redis Caching
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_CACHE_TTL=3600

# Salesforce
SALESFORCE_CLIENT_ID=your-client-id
SALESFORCE_CLIENT_SECRET=your-client-secret
SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## 🧪 Testing

Run the test suite:

```bash
pytest                  # Run all tests
pytest -v             # Verbose output
pytest --cov          # With coverage report
pytest tests/test_auth.py  # Specific test file
```

## 📈 Performance Goals

- **JWT Validation**: < 1ms
- **OAuth Scope Check**: < 50ms (with Redis caching)
- **RLS Evaluation**: < 20ms
- **Total Proxy Overhead**: < 50ms

## 🔒 Security Highlights

✅ **Authentication**: JWT-based with HS256 signatures
✅ **Authorization**: OAuth 2.0 scopes with Redis caching
✅ **Row-Level Security**: Policy-based access control
✅ **Data Redaction**: Automatic PII masking
✅ **Audit Logging**: All access decisions logged
✅ **Rate Limiting**: Prevents abuse (Phase 2)
✅ **Encryption**: TLS for all API communication (Phase 2)

## 📚 Documentation

- `ARCHITECTURE.md` - Detailed system design
- `SETUP.md` - Development environment setup
- `PROGRESS.md` - Phase tracking and milestones
- API docs (Swagger): http://localhost:8000/docs (when running)

## 🤝 Contributing

Team members working on Phase 1:
- Principal Architect - Security design & decision-making
- Backend Engineer - Implementation & testing
- DevOps - Infrastructure & deployment

## 📅 Timeline

- **Week 1** ✅ Architecture & schema definition
- **Week 2** 🔄 Backend scaffolding & Redis integration
- **Week 3** ⏳ Frontend setup with Auth0/Okta
- **Week 4** ⏳ Salesforce integration & "Hello World" sync

**Launch Target**: End of May 2026

## ❓ FAQ

**Q: What about database persistence?**
A: Phase 2 will add PostgreSQL for audit logs and user metadata.

**Q: Will this support other tools besides Salesforce?**
A: The architecture is tool-agnostic. Phase 2+ will add support for other APIs.

**Q: How do we handle Salesforce rate limits?**
A: Token caching reduces API calls. Phase 2 will add request queuing.

## 📞 Support

For questions or issues:
1. Check the `SETUP.md` and `ARCHITECTURE.md` documentation
2. Review test files for usage examples
3. Check application logs for error details

---

**Phase**: 1 of 4
**Status**: Week 1 Complete, Week 2 Starting
**Last Updated**: May 11, 2026
