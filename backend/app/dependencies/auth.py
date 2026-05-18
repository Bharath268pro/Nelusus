from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services import AuthenticationService
from app.models.security import JWTToken

security = HTTPBearer()

def get_current_user_jwt(credentials: HTTPAuthorizationCredentials = Depends(security)) -> JWTToken:
    """Extracts and validates the JWT from the Authorization header."""
    token = credentials.credentials
    jwt_token = AuthenticationService.decode_token(token)
    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
    return jwt_token

def require_scope(required_scope: str):
    """Enforces that the authenticated JWT contains the required scope."""
    def scope_checker(jwt_token: JWTToken = Depends(get_current_user_jwt)) -> JWTToken:
        if required_scope not in jwt_token.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {required_scope}"
            )
        return jwt_token
    return scope_checker
