"""Quick reference for common development tasks"""

# AUTHENTICATION & TOKEN GENERATION

## Generate test JWT token:
```python
from app.services import AuthenticationService

token = AuthenticationService.create_token(
    user_id="test_user_123",
    email="test@example.com",
    scopes=["sfdc:read_account", "sfdc:read_contact"]
)
print(f"Authorization: Bearer {token}")
```

## Validate a token:
```python
jwt_token = AuthenticationService.decode_token(token)
if jwt_token:
    print(f"User: {jwt_token.sub}")
    print(f"Scopes: {jwt_token.scopes}")
```

---

# TESTING THE API

## 1. Start backend
```bash
cd backend
source venv/bin/activate
python -m uvicorn app.main:app --reload --port 8000
```

## 2. In another terminal, generate token
```bash
python3 << 'EOF'
from app.services import AuthenticationService
token = AuthenticationService.create_token(
    user_id="user123",
    email="user@example.com",
    scopes=["sfdc:read_account"]
)
print(token)
EOF
```

## 3. Test health endpoint
```bash
curl http://localhost:8000/api/v1/health
```

## 4. Test tool execution
```bash
curl -X POST http://localhost:8000/api/v1/mcp/tool-call \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "auth_token": "YOUR_TOKEN_HERE",
    "tool_call": {
      "tool_name": "read_salesforce_account",
      "tool_version": "1.0",
      "arguments": {
        "account_id": "001XX000000000"
      },
      "request_id": "req_001",
      "timestamp": "2026-05-11T10:30:00Z"
    }
  }'
```

---

# UNIT TESTS

## Run all tests
```bash
cd backend
pytest
```

## Run specific test file
```bash
pytest tests/test_auth.py -v
```

## Run with coverage
```bash
pytest --cov=app --cov-report=html
# Open htmlcov/index.html to view coverage
```

## Run a specific test function
```bash
pytest tests/test_auth.py::test_create_and_decode_token -v
```

---

# WORKING WITH REDIS

## Start Redis (Docker)
```bash
docker run -d -p 6379:6379 --name redis-nelusus redis:7
```

## Test Redis connection
```bash
redis-cli ping
# Should output: PONG
```

## Monitor Redis operations
```bash
redis-cli MONITOR
```

## Clear all Redis cache
```bash
redis-cli FLUSHALL
```

## View cached keys
```bash
redis-cli KEYS "user_context:*"
```

---

# ENVIRONMENT SETUP

## Create .env file
```bash
cp backend/.env.example backend/.env
```

## Minimum required for testing
```
JWT_SECRET_KEY=test-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_CLIENT_ID=test-client-id
AUTH0_CLIENT_SECRET=test-client-secret
AUTH0_API_IDENTIFIER=https://your-api

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_CACHE_TTL=3600

DATABASE_URL=postgresql://user:password@localhost:5432/nelusus_db

SALESFORCE_CLIENT_ID=test-client-id
SALESFORCE_CLIENT_SECRET=test-client-secret
SALESFORCE_INSTANCE_URL=https://your-instance.salesforce.com
```

---

# LOGGING & DEBUGGING

## Check logs
```bash
# Backend logs show in console when running with --reload
python -m uvicorn app.main:app --reload --log-level=debug
```

## Add debug logging to code
```python
import logging
logger = logging.getLogger(__name__)

logger.debug("Debug message")
logger.info("Info message")
logger.warning("Warning message")
logger.error("Error message")
```

## Check request/response with curl -v
```bash
curl -v -X POST http://localhost:8000/api/v1/mcp/tool-call \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"..."}'
```

---

# DATABASE (PostgreSQL)

## Start PostgreSQL (Docker)
```bash
docker run -d -p 5432:5432 \
  -e POSTGRES_USER=user \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=nelusus \
  --name postgres-nelusus \
  postgres:15
```

## Connect to database
```bash
psql -h localhost -U user -d nelusus_db
```

## Create database (if using local PostgreSQL)
```bash
createdb -U user nelusus_db
```

---

# COMMON ISSUES & FIXES

## "ModuleNotFoundError: No module named 'fastapi'"
```bash
# Make sure venv is activated
source venv/bin/activate
# Reinstall requirements
pip install -r requirements.txt
```

## "ConnectionRefusedError" when connecting to Redis
```bash
# Check if Redis is running
redis-cli ping

# If not, start it:
docker run -d -p 6379:6379 redis:7
# OR
redis-server
```

## Port 8000 already in use
```bash
# Find process using port 8000
lsof -i :8000

# Kill it
kill -9 <PID>

# OR use different port
python -m uvicorn app.main:app --reload --port 8001
```

## "Invalid token" error
```bash
# Generate a new token:
python3 << 'EOF'
from app.services import AuthenticationService
token = AuthenticationService.create_token(
    user_id="test",
    email="test@example.com"
)
print(f"Bearer {token}")
EOF
```

---

# USEFUL COMMANDS

## View API documentation (when running)
```
http://localhost:8000/docs
```

## Test async code in Python REPL
```bash
python3 -c "
import asyncio
from app.services.oauth import OAuthService

async def test():
    service = OAuthService()
    result = await service.validate_scope('user123', 'sfdc:read_account')
    print(result)

asyncio.run(test())
"
```

## Count lines of code
```bash
wc -l app/**/*.py
# or
find app -name "*.py" | xargs wc -l
```

---

# NEXT STEPS (Week 2)

- [ ] Set up Redis and test caching
- [ ] Implement OAuth scope fetching from Auth0/Okta
- [ ] Add comprehensive logging
- [ ] Write more unit tests
- [ ] Create integration tests
- [ ] Set up CI/CD pipeline

See PROGRESS.md for detailed tasks.
