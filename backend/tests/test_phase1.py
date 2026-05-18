import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services import AuthenticationService
from app.services.registry_engine import registry
from app.models.mcp_registry import ToolDefinition, ToolSchema

@pytest.fixture
def client():
    app = create_app()
    # Using 'with' context manager to guarantee lifespan events (startup tools registration) run!
    with TestClient(app) as c:
        yield c

@pytest.fixture
def auth_header():
    # Create a valid test JWT using the app's AuthenticationService
    token = AuthenticationService.create_token(
        user_id="test_user",
        email="test@example.com",
        scopes=["mcp:execute"]
    )
    return {"Authorization": f"Bearer {token}"}

def test_discover_tools(client, auth_header):
    # Retrieve the list of tools
    response = client.get("/api/v1/mcp/tools", headers=auth_header)
    assert response.status_code == 200
    
    tools = response.json()
    assert len(tools) > 0
    
    # Check that our startup tool weather.get is present
    weather_tool = next((t for t in tools if t["name"] == "weather.get"), None)
    assert weather_tool is not None
    assert weather_tool["description"] == "Get weather for a location"

def test_execute_dynamic_tool(client, auth_header):
    # Execute the weather.get tool registered on startup
    payload = {
        "tool_name": "weather.get",
        "arguments": {"location": "San Francisco"}
    }
    
    response = client.post("/api/v1/mcp/execute", json=payload, headers=auth_header)
    assert response.status_code == 200
    
    result = response.json()
    assert result["success"] is True
    assert result["data"]["temp"] == 72
    assert result["data"]["location"] == "San Francisco"

def test_execute_non_existent_tool(client, auth_header):
    payload = {
        "tool_name": "non_existent_tool",
        "arguments": {}
    }
    
    response = client.post("/api/v1/mcp/execute", json=payload, headers=auth_header)
    assert response.status_code == 200
    
    result = response.json()
    assert result["success"] is False
    assert "not found" in result["error"].lower()
