# NexusMCP Gateway - Phase 1 Foundation

**Production-Grade MCP Security Gateway with JSON-RPC 2.0 Support**

This is Phase 1 of the NexusMCP platform - the foundational security and gateway layer for the Model Context Protocol.

## ✅ Phase 1 Deliverables

### Core Architecture
- ✅ FastAPI ASGI application with async/await throughout
- ✅ JSON-RPC 2.0 protocol engine (tools/call, tools/list, batch requests)
- ✅ RS256 JWT validation with JWKS caching
- ✅ OAuth2 scope enforcement
- ✅ Row-Level Security (RLS) context injection
- ✅ Prompt injection attack detection
- ✅ OpenTelemetry tracing (OTLP, Jaeger, AWS X-Ray)
- ✅ Redis caching with namespaced keys and TTLs
- ✅ Structured JSON logging

### Middleware Chain (6-layer)
1. **TLSTerminationMiddleware** - Validates TLS/HTTPS headers
2. **RequestIDMiddleware** - Generates correlation IDs
3. **JWTValidationMiddleware** - Validates RS256 tokens, injects identity
4. **ScopeEnforcementMiddleware** - Validates OAuth scopes (prepared for Phase 2)
5. **RLSEnforcementMiddleware** - Injects RLS context (prepared for Phase 2)
6. **PromptShieldMiddleware** - Detects prompt injection attacks

### Endpoints
- `POST /api/v1/rpc` - Main JSON-RPC 2.0 endpoint
- `GET /api/v1/health` - Health check with dependency status
- `GET /api/v1/ready` - Kubernetes readiness probe
- `GET /api/v1/version` - Service version info
- `GET /api/v1/info` - Detailed service information

### Caching Layer
- JWKS endpoint results (1 hour)
- Token validation results (30 minutes)
- Tool schemas (2 hours)
- RLS policies (1 hour)
- Scope mappings (2 hours)

### Error Handling
Custom JSON-RPC 2.0 error codes:
- `-32001` - SCOPE_VIOLATION
- `-32002` - RLS_DENIED
- `-32003` - TOOL_NOT_FOUND
- `-32004` - PROMPT_INJECTION_DETECTED
- `-32005` - ELICITATION_REQUIRED
- `-32006` - TOKEN_VALIDATION_FAILED
- `-32007` - TENANT_MISMATCH
- `-32008` - INVALID_TOOL_NAMESPACE
- `-32009` - RATE_LIMIT_EXCEEDED
- `-32010` - CONNECTOR_UNAVAILABLE
- `-32011` - CACHE_ERROR
- `-32012` - RLS_POLICY_EVAL_TIMEOUT

## 🚀 Quick Start

### Prerequisites
- Python 3.12+
- Redis 7.x
- PostgreSQL 15+ (for audit logs, optional for Phase 1)
- Docker & Docker Compose (recommended)

### Local Development

#### Option 1: Docker Compose (Recommended)

```bash
# Clone repository
git clone https://github.com/your-org/nelusus
cd Nelusus

# Start services
docker-compose up

# View logs
docker-compose logs -f gateway

# Access the application
# - Gateway API: http://localhost:8000
# - Health check: http://localhost:8000/api/v1/health
# - Jaeger UI: http://localhost:16686
# - Documentation: http://localhost:8000/api/v1/docs (if DEBUG=true)
```

#### Option 2: Manual Setup

```bash
# Create virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Configure environment
cp backend/.env.example backend/.env
# Edit backend/.env with your settings

# Start Redis
redis-server

# Run gateway
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Configuration

Create a `.env` file in the `backend/` directory:

```bash
# Required: JWT Configuration
JWT_ALGORITHM=RS256
JWKS_URI=https://your-idp.com/.well-known/jwks.json
JWT_ISSUER=https://your-idp.com/
JWT_AUDIENCE=nexusmcp

# Required: OAuth2 Configuration
OAUTH2_CLIENT_ID=your-client-id
OAUTH2_CLIENT_SECRET=your-client-secret
OAUTH2_JWKS_ENDPOINT=https://your-idp.com/.well-known/jwks.json

# Optional: Redis (defaults to localhost:6379)
REDIS_HOST=localhost
REDIS_PORT=6379

# Optional: OpenTelemetry
OTEL_ENABLED=true
OTEL_EXPORTER_TYPE=otlp
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

See `backend/.env.example` for all available options.

## 🧪 Testing

```bash
# Run all tests
pytest backend/tests/

# Run with coverage
pytest backend/tests/ --cov=app --cov-report=html

# Run specific test file
pytest backend/tests/test_auth.py

# Run async tests
pytest backend/tests/test_rls.py -v
```

## 🔍 Usage Examples

### Example 1: List Available Tools

```bash
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/list",
    "id": "req-1"
  }'
```

Response:
```json
{
  "jsonrpc": "2.0",
  "result": {
    "tools": [
      {
        "name": "salesforce.query_opportunities",
        "description": "Query Salesforce opportunities",
        "input_schema": { "type": "object", "properties": {} },
        "required_scopes": ["read_opportunities"],
        "rls_required": true
      }
    ],
    "total": 1,
    "timestamp": "2024-05-16T12:00:00Z"
  },
  "id": "req-1"
}
```

### Example 2: Call a Tool

```bash
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "salesforce.query_opportunities",
      "arguments": {
        "stage": "Closed Won"
      }
    },
    "id": "req-2"
  }'
```

### Example 3: Batch Request

```bash
curl -X POST http://localhost:8000/api/v1/rpc \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '[
    {
      "jsonrpc": "2.0",
      "method": "tools/list",
      "id": "req-1"
    },
    {
      "jsonrpc": "2.0",
      "method": "tools/list",
      "id": "req-2"
    }
  ]'
```

## 📊 Observability

### Tracing with Jaeger
Access the Jaeger UI at `http://localhost:16686` to view distributed traces of requests through the middleware chain.

### Metrics
Each request generates:
- Request ID and correlation ID
- Timing information
- Middleware execution traces
- Cache hits/misses
- Error codes and reasons

### Structured Logs
Logs are output in JSON format (configurable) with:
```json
{
  "timestamp": "2024-05-16T12:00:00Z",
  "level": "INFO",
  "logger": "nexusmcp-gateway",
  "message": "JWT validated for user",
  "service": "nexusmcp-gateway",
  "request_id": "req-123",
  "trace_id": "trace-456",
  "user_id": "user789"
}
```

## 🔐 Security Features

### Phase 1
- ✅ RS256 JWT validation with JWKS caching
- ✅ OAuth2 scope extraction and enforcement preparation
- ✅ TLS/HTTPS enforcement (optional)
- ✅ Prompt injection attack detection
- ✅ Request correlation tracking
- ✅ mTLS client certificate support (optional)

### Phase 2+ (Coming Soon)
- Tool-specific scope validation
- RLS policy evaluation from DynamoDB
- Fine-grained access control
- Advanced threat detection (ML-based)
- Audit logging to PostgreSQL

## 📁 Project Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app factory
│   ├── config.py                  # Configuration management
│   ├── middleware/                # 6-layer middleware chain
│   │   ├── tls_termination.py
│   │   ├── request_id.py
│   │   ├── jwt_validation.py
│   │   ├── scope_enforcement.py
│   │   ├── rls_enforcement.py
│   │   └── prompt_shield.py
│   ├── models/                    # Data models
│   │   ├── jsonrpc.py             # JSON-RPC 2.0 models
│   │   ├── error_codes.py         # Custom error codes
│   │   └── registry.py            # Tool registry models
│   ├── routes/                    # API endpoints
│   │   ├── health.py              # Health check endpoints
│   │   └── mcp.py                 # JSON-RPC endpoint
│   ├── services/                  # Business logic
│   │   ├── jwt_auth.py            # JWT validation
│   │   └── jsonrpc_handler.py     # JSON-RPC engine
│   └── utils/                     # Utilities
│       ├── cache.py               # Redis caching
│       └── tracing.py             # OpenTelemetry setup
├── tests/                         # Unit & integration tests
│   ├── test_auth.py               # Auth tests
│   ├── test_rls.py                # JSON-RPC tests
│   └── conftest.py                # Pytest configuration
├── Dockerfile                     # Multi-stage Docker build
├── requirements.txt               # Python dependencies
├── .env.example                   # Environment template
└── README.md                      # This file
```

## 🔄 Middleware Execution Flow

Incoming Request
↓
TLSTerminationMiddleware (validates HTTPS)
↓
RequestIDMiddleware (generates correlation IDs)
↓
JWTValidationMiddleware (validates JWT, injects identity)
↓
ScopeEnforcementMiddleware (prepares scope validation)
↓
RLSEnforcementMiddleware (injects RLS context)
↓
PromptShieldMiddleware (detects injection attacks)
↓
JSON-RPC Handler (routes to tools/call or tools/list)
↓
Response (with request ID in headers)

## 🗂️ Environment Variables

See `backend/.env.example` for complete list. Key variables:

```
# Authentication
JWT_ALGORITHM=RS256
JWKS_URI=https://...
JWT_ISSUER=https://...
JWT_AUDIENCE=nexusmcp

# Cache
REDIS_HOST=localhost
REDIS_PORT=6379

# Tracing
OTEL_ENABLED=true
OTEL_EXPORTER_TYPE=otlp

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## 📈 Performance Targets

- JWT validation + identity injection: < 50ms
- Cache operations: < 10ms
- Middleware chain overhead: < 100ms
- Health check response: < 100ms

## 🐛 Troubleshooting

### Gateway won't start
```bash
# Check if Redis is running
redis-cli ping

# Check Python version
python --version  # Should be 3.12+

# View detailed logs
LOG_LEVEL=DEBUG python -m uvicorn app.main:app --reload
```

### JWT validation failing
1. Verify JWKS_URI is correct
2. Check JWT_ISSUER and JWT_AUDIENCE match your token
3. Ensure JWKS cache is fresh (check Redis)

### Tests failing
```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run with verbose output
pytest backend/tests/ -vv

# Run specific test
pytest backend/tests/test_auth.py::TestScopeValidator -vv
```

## 📝 Development Checklist

- ✅ FastAPI application factory
- ✅ Pydantic v2 models
- ✅ Async middleware chain
- ✅ JWT RS256 validation
- ✅ Redis integration
- ✅ JSON-RPC 2.0 engine
- ✅ Error handling
- ✅ OpenTelemetry tracing
- ✅ Unit tests
- ✅ Docker multi-stage build
- ✅ docker-compose for local dev
- ✅ Comprehensive documentation
- ⏳ Integration tests (in progress)
- ⏳ Load testing (Phase 2+)

## 🚦 Next Steps (Phase 2+)

- [ ] Tool connector factory
- [ ] Salesforce connector implementation
- [ ] RLS policy evaluation engine
- [ ] Tool registry DynamoDB integration
- [ ] Advanced threat detection (ML)
- [ ] Audit logging
- [ ] Multi-tenant support enhancements
- [ ] Rate limiting implementation
- [ ] Circuit breaker pattern
- [ ] Service mesh integration (Istio/App Mesh)

## 📖 References

- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification)
- [Model Context Protocol](https://modelcontextprotocol.io)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [Pydantic v2](https://docs.pydantic.dev/latest/)

## 📄 License

[Your License Here]

## 👥 Contributors

[Your Team]

---

**Phase 1 Status:** ✅ Complete
**Last Updated:** 2024-05-16
**Next Phase:** Phase 2 - Dynamic Discovery & Agentic Logic
