# Setup Instructions - MCP Security Proxy

## Prerequisites

- Python 3.10+
- Node.js 18+ (for frontend)
- Redis 6.0+ (for caching)
- PostgreSQL 14+ (optional, for audit logging)
- Auth0 or Okta account
- Salesforce sandbox or production org

## Backend Setup

### 1. Virtual Environment

```bash
cd backend
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 2. Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Configuration

```bash
cp .env.example .env
# Edit .env with your Auth0, Salesforce, and Redis credentials
```

### 4. Redis Setup (Local Development)

```bash
# Option 1: Using Docker
docker run -d -p 6379:6379 redis:7

# Option 2: Using Homebrew (macOS)
brew install redis
redis-server

# Option 3: Using apt (Linux)
sudo apt-get install redis-server
redis-server
```

### 5. Run Backend

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at `http://localhost:8000`

### 6. Run Tests

```bash
pytest
pytest -v  # Verbose
pytest --cov  # With coverage
```

## Frontend Setup

### 1. Create Next.js Project

```bash
cd ../frontend
npx create-next-app@latest . --typescript --tailwind --eslint
```

### 2. Install Dependencies

```bash
npm install
npm install -D shadcn-ui
npm install @auth0/nextjs-auth0  # or okta-react
```

### 3. Configure Auth0/Okta

Create `.env.local`:

```
NEXT_PUBLIC_AUTH0_DOMAIN=your-domain.auth0.com
NEXT_PUBLIC_AUTH0_CLIENT_ID=your-client-id
AUTH0_CLIENT_SECRET=your-client-secret
AUTH0_BASE_URL=http://localhost:3000
```

### 4. Run Frontend

```bash
npm run dev
```

Available at `http://localhost:3000`

## Docker Compose (Recommended)

For a complete local development environment:

```bash
# In root directory
docker-compose up
```

This starts:
- FastAPI backend on port 8000
- Next.js frontend on port 3000
- Redis on port 6379

## Quick Test

### 1. Generate Test JWT

```bash
python3 << 'EOF'
from app.services import AuthenticationService

token = AuthenticationService.create_token(
    user_id="test_user",
    email="test@example.com",
    scopes=["sfdc:read_account"]
)
print(f"Bearer {token}")
EOF
```

### 2. Call the API

```bash
curl -X POST http://localhost:8000/api/v1/mcp/tool-call \
  -H "Authorization: Bearer YOUR_TOKEN_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "test_user",
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

## Phase 1 Milestones

### Week 1 ✅
- [x] Architecture documented
- [x] Pydantic models created
- [x] Directory structure established

### Week 2 🔄
- [ ] Complete OAuthService implementation
- [ ] Connect to Redis
- [ ] Add comprehensive logging
- [ ] Write unit tests

### Week 3 ⏳
- [ ] Frontend scaffolding
- [ ] Auth integration
- [ ] Tool execution UI

### Week 4 ⏳
- [ ] Salesforce API integration
- [ ] End-to-end "Hello World" test
- [ ] Performance optimization

## Troubleshooting

### Import Errors

If you see import errors when running the backend:

```bash
# Make sure venv is activated
source venv/bin/activate

# Reinstall requirements
pip install --upgrade -r requirements.txt
```

### Redis Connection Error

```bash
# Check Redis is running
redis-cli ping
# Should output: PONG

# If not running, start it:
redis-server
```

### Port Already in Use

```bash
# Find and kill process on port 8000
lsof -i :8000
kill -9 <PID>

# Or change port:
python -m uvicorn app.main:app --reload --port 8001
```

## Documentation

- `ARCHITECTURE.md` - System design and security pipeline
- `docs/` folder - Additional documentation (to be added)

## Support

For issues or questions:
1. Check logs in console output
2. Review error message in API response
3. Check environment variables are set correctly
4. Verify all services (Redis, Salesforce API) are accessible
