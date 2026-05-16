#!/bin/bash
# Quick startup script for local development

set -e

echo "🚀 Starting MCP Security Proxy Development Environment..."

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check prerequisites
echo -e "${BLUE}Checking prerequisites...${NC}"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.10+"
    exit 1
fi

if ! command -v docker &> /dev/null && ! command -v redis-cli &> /dev/null; then
    echo "⚠️  Neither Docker nor Redis found. You'll need one for caching."
fi

# Setup backend
echo -e "${BLUE}Setting up backend...${NC}"
cd backend

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "Created virtual environment"
fi

source venv/bin/activate

pip install --quiet -r requirements.txt
echo -e "${GREEN}✓ Backend dependencies installed${NC}"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${BLUE}Created .env file. Please edit with your credentials:${NC}"
    echo "  - JWT_SECRET_KEY"
    echo "  - AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET"
    echo "  - SALESFORCE_CLIENT_ID, SALESFORCE_CLIENT_SECRET, SALESFORCE_INSTANCE_URL"
    echo "  - REDIS_HOST (localhost or docker container)"
fi

echo -e "${GREEN}✓ Backend setup complete${NC}"

# Offer to start backend
echo -e "${BLUE}Backend ready to start.${NC}"
echo "To start the backend, run:"
echo "  cd backend"
echo "  source venv/bin/activate"
echo "  python -m uvicorn app.main:app --reload --port 8000"

echo ""
echo "To start Redis (if not already running):"
echo "  docker run -d -p 6379:6379 redis:7"
echo "  OR"
echo "  redis-server"

echo ""
echo -e "${GREEN}✓ Setup complete!${NC}"
