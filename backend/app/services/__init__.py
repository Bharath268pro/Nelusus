"""Service layer for JWT and OAuth token validation"""

import jwt
from datetime import datetime, timedelta
from typing import Optional
from app.models.security import JWTToken, UserContext, OAuthScope
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class AuthenticationService:
    """Handles JWT token generation and validation"""

    @staticmethod
    def decode_token(token: str) -> Optional[JWTToken]:
        """
        Decode and validate a JWT token.

        Args:
            token: JWT token string (without 'Bearer ' prefix)

        Returns:
            Decoded JWTToken model or None if invalid
        """
        try:
            payload = jwt.decode(
                token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                audience="mcp-agents"
            )
            return JWTToken(**payload)
        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid token: {e}")
            return None

    @staticmethod
    def create_token(user_id: str, email: str, scopes: Optional[list[str]] = None) -> str:
        """
        Create a new JWT token.

        Args:
            user_id: User identifier
            email: User email
            scopes: List of OAuth scopes

        Returns:
            Encoded JWT token
        """
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "email": email,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=settings.jwt_expiration_hours)).timestamp()),
            "iss": "nelusus-security-proxy",
            "aud": "mcp-agents",
            "scopes": scopes or [],
        }
        return jwt.encode(
            payload,
            settings.jwt_secret_key,
            algorithm=settings.jwt_algorithm,
        )

    @staticmethod
    def extract_bearer_token(auth_header: Optional[str]) -> Optional[str]:
        """
        Extract JWT token from Authorization header.

        Args:
            auth_header: Authorization header value

        Returns:
            Token string or None
        """
        if not auth_header:
            return None
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1]
        return None
