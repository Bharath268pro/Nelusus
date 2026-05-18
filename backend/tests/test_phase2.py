import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services import AuthenticationService

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_missing_authorization_header(client):
    # Discovery endpoint
    response = client.get("/api/v1/mcp/tools")
    assert response.status_code == 401
    assert "Missing or invalid authorization token" in response.json()["detail"]

    # Execution endpoint
    response = client.post("/api/v1/mcp/execute", json={})
    assert response.status_code == 401
    assert "Missing or invalid authorization token" in response.json()["detail"]

def test_invalid_jwt_token(client):
    headers = {"Authorization": "Bearer invalid_token_value_here"}
    
    response = client.get("/api/v1/mcp/tools", headers=headers)
    assert response.status_code == 401
    assert "Invalid or expired token" in response.json()["detail"]

def test_missing_required_scope(client):
    # Mint token without 'mcp:execute' scope
    token = AuthenticationService.create_token(
        user_id="user123",
        email="test@example.com",
        scopes=["other:scope"] # Missing 'mcp:execute'
    )
    headers = {"Authorization": f"Bearer {token}"}
    
    # Discovery only requires a valid user context (scopes not strictly specified for list_tools)
    response = client.get("/api/v1/mcp/tools", headers=headers)
    assert response.status_code == 200

    # Execution requires 'mcp:execute' scope
    payload = {
        "tool_name": "weather.get",
        "arguments": {"location": "San Francisco"}
    }
    response = client.post("/api/v1/mcp/execute", json=payload, headers=headers)
    assert response.status_code == 403
    assert "Missing required scope" in response.json()["detail"]

def test_successful_scope_auth(client):
    # Mint token with correct scope
    token = AuthenticationService.create_token(
        user_id="user123",
        email="test@example.com",
        scopes=["mcp:execute"]
    )
    headers = {"Authorization": f"Bearer {token}"}
    
    payload = {
        "tool_name": "weather.get",
        "arguments": {"location": "San Francisco"}
    }
    response = client.post("/api/v1/mcp/execute", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["success"] is True
