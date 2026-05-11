"""Tests for authentication service"""

import pytest
from app.services import AuthenticationService


def test_create_and_decode_token():
    """Test JWT token creation and decoding"""
    token = AuthenticationService.create_token(
        user_id="user123", email="test@example.com", scopes=["sfdc:read"]
    )

    decoded = AuthenticationService.decode_token(token)
    assert decoded is not None
    assert decoded.sub == "user123"
    assert decoded.email == "test@example.com"
    assert "sfdc:read" in decoded.scopes


def test_invalid_token():
    """Test decoding invalid token returns None"""
    result = AuthenticationService.decode_token("invalid.token.here")
    assert result is None


def test_extract_bearer_token():
    """Test Bearer token extraction"""
    token = AuthenticationService.extract_bearer_token("Bearer eyJhbGc...")
    assert token == "eyJhbGc..."

    token = AuthenticationService.extract_bearer_token("Invalid token")
    assert token is None

    token = AuthenticationService.extract_bearer_token(None)
    assert token is None
