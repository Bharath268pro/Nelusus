"""Tests for JSON-RPC engine and handler"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from app.services.jsonrpc_handler import JSONRPCHandler, ToolCallHandler, ToolListHandler
from app.models.jsonrpc import (
    JSONRPCRequest,
    ToolCallRequest,
    ToolCallParams,
    Identity,
)
from app.models.error_codes import ErrorCode


@pytest.fixture
def jsonrpc_handler():
    """Create JSON-RPC handler"""
    return JSONRPCHandler()


@pytest.fixture
def sample_identity():
    """Create sample identity"""
    return Identity(
        sub="user123",
        tenant_id="tenant456",
        scopes=["read_accounts"],
        roles=["user"],
    )


class TestJSONRPCHandler:
    """Test JSON-RPC 2.0 handler"""

    def test_parse_valid_request(self, jsonrpc_handler):
        """Test parsing valid JSON-RPC request"""
        data = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": "req-123",
        }
        request = jsonrpc_handler.parse_request(json.dumps(data))
        assert request is not None
        assert request.method == "tools/list"
        assert request.id == "req-123"

    def test_parse_invalid_json(self, jsonrpc_handler):
        """Test parsing invalid JSON"""
        request = jsonrpc_handler.parse_request("invalid json")
        assert request is None

    def test_parse_batch_request(self, jsonrpc_handler):
        """Test parsing batch request"""
        data = [
            {"jsonrpc": "2.0", "method": "tools/list", "id": "1"},
            {"jsonrpc": "2.0", "method": "tools/list", "id": "2"},
        ]
        requests = jsonrpc_handler.parse_batch_request(json.dumps(data))
        assert requests is not None
        assert len(requests) == 2

    def test_validate_tool_name_valid(self, jsonrpc_handler):
        """Test valid tool name format"""
        assert jsonrpc_handler.validate_tool_name("salesforce.read_accounts") is True

    def test_validate_tool_name_invalid(self, jsonrpc_handler):
        """Test invalid tool name format"""
        assert jsonrpc_handler.validate_tool_name("invalid-name") is False
        assert jsonrpc_handler.validate_tool_name("InvalidName") is False

    def test_create_result_response(self, jsonrpc_handler):
        """Test creating result response"""
        result = jsonrpc_handler.create_result_response("req-123", {"data": "value"})
        assert result.jsonrpc == "2.0"
        assert result.id == "req-123"
        assert result.result == {"data": "value"}

    def test_create_error_response(self, jsonrpc_handler):
        """Test creating error response"""
        error = jsonrpc_handler.create_error_response(
            "req-123", ErrorCode.METHOD_NOT_FOUND
        )
        assert error.jsonrpc == "2.0"
        assert error.id == "req-123"
        assert error.error.code == -32601

    def test_serialize_response(self, jsonrpc_handler):
        """Test serializing response"""
        result = jsonrpc_handler.create_result_response("req-1", {"test": "data"})
        serialized = jsonrpc_handler.serialize_response(result)
        parsed = json.loads(serialized)
        assert parsed["jsonrpc"] == "2.0"
        assert parsed["id"] == "req-1"


class TestToolCallHandler:
    """Test tool call handler"""

    @pytest.fixture
    def tool_call_handler(self, jsonrpc_handler):
        """Create tool call handler"""
        return ToolCallHandler(jsonrpc_handler)

    @pytest.mark.asyncio
    async def test_tool_call_invalid_namespace(self, tool_call_handler, sample_identity):
        """Test tool call with invalid namespace"""
        request = ToolCallRequest(
            jsonrpc="2.0",
            method="tools/call",
            params=ToolCallParams(name="invalid-name", arguments={}),
            id="req-1",
        )
        response = await tool_call_handler.handle_tool_call(request, sample_identity)
        assert response.error.code == ErrorCode.INVALID_TOOL_NAMESPACE

    @pytest.mark.asyncio
    async def test_tool_call_missing_identity(self, tool_call_handler):
        """Test tool call without identity"""
        request = ToolCallRequest(
            jsonrpc="2.0",
            method="tools/call",
            params=ToolCallParams(name="salesforce.read_accounts", arguments={}),
            id="req-1",
        )
        response = await tool_call_handler.handle_tool_call(request, None)
        assert response.error.code == ErrorCode.TOKEN_VALIDATION_FAILED

    @pytest.mark.asyncio
    async def test_tool_call_success_stub(self, tool_call_handler, sample_identity):
        """Test successful tool call (Phase 1 stub)"""
        request = ToolCallRequest(
            jsonrpc="2.0",
            method="tools/call",
            params=ToolCallParams(name="salesforce.read_accounts", arguments={}),
            id="req-1",
        )
        response = await tool_call_handler.handle_tool_call(request, sample_identity)
        assert response.result.is_error is False
        assert len(response.result.content) > 0


class TestToolListHandler:
    """Test tool list handler"""

    @pytest.fixture
    def tool_list_handler(self, jsonrpc_handler):
        """Create tool list handler"""
        return ToolListHandler(jsonrpc_handler)

    @pytest.mark.asyncio
    async def test_tool_list_missing_identity(self, tool_list_handler):
        """Test tool list without identity"""
        request = ToolListRequest(
            jsonrpc="2.0",
            method="tools/list",
            id="req-1",
        )
        response = await tool_list_handler.handle_tool_list(request, None)
        assert response.error.code == ErrorCode.TOKEN_VALIDATION_FAILED

    @pytest.mark.asyncio
    async def test_tool_list_success(self, tool_list_handler, sample_identity):
        """Test successful tool list"""
        request = ToolListRequest(
            jsonrpc="2.0",
            method="tools/list",
            id="req-1",
        )
        response = await tool_list_handler.handle_tool_list(request, sample_identity)
        assert response.result.total > 0
        assert len(response.result.tools) > 0
