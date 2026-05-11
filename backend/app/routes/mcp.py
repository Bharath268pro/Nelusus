"""MCP tool execution routes"""

import logging
from fastapi import APIRouter, Request, HTTPException, status, Depends
from app.models.mcp_protocol import MCPRequest, MCPResponse
from app.services.oauth import OAuthService
from app.services.rls import RowLevelSecurityService
from app.services.salesforce import SalesforceService
from app.services import AuthenticationService
import time

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

# Service instances
oauth_service = OAuthService()
rls_service = RowLevelSecurityService()
salesforce_service = SalesforceService()


@router.post("/tool-call", response_model=MCPResponse)
async def execute_tool(request: Request, mcp_request: MCPRequest):
    """
    Execute an MCP tool call with full security validation.

    Security pipeline:
    1. Validate JWT token
    2. Check OAuth scopes
    3. Validate row-level security
    4. Apply PII redaction
    5. Execute tool
    6. Cache result
    """
    start_time = time.time()
    request_id = mcp_request.tool_call.request_id

    try:
        # Step 1: Validate JWT
        jwt_token = AuthenticationService.decode_token(mcp_request.auth_token)
        if not jwt_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        user_id = jwt_token.sub

        # Step 2: Check tool availability and scopes
        tool_name = mcp_request.tool_call.tool_name
        logger.info(f"User {user_id} requesting tool: {tool_name}")

        # Example: Read Salesforce Account
        if tool_name == "read_salesforce_account":
            # Get scope
            authorized, missing_scope = await oauth_service.validate_scopes(
                user_id, ["sfdc:read_account"]
            )
            if not authorized:
                logger.warning(
                    f"User {user_id} lacks scope {missing_scope} for {tool_name}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Missing required scope: {missing_scope}",
                )

            # Step 3: Get user context for RLS
            user_context = await oauth_service.get_user_context(user_id)
            if not user_context:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not retrieve user context",
                )

            # Get account ID from arguments
            account_id = mcp_request.tool_call.arguments.get("account_id")
            if not account_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Missing required argument: account_id",
                )

            # Step 3: Validate RLS
            rls_result = rls_service.check_row_access(user_context, "Account", account_id)
            if not rls_result.authorized:
                logger.warning(
                    f"User {user_id} denied access to Account {account_id}: {rls_result.reason}"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not authorized to access this record",
                )

            # Step 4: Fetch from Salesforce
            account_data = await salesforce_service.get_account(account_id)
            if not account_data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Account {account_id} not found",
                )

            # Step 5: Apply PII redaction
            redacted_data = rls_service.redact_record(account_data, rls_result.redaction_rules)

            execution_time = (time.time() - start_time) * 1000  # Convert to ms

            return MCPResponse(
                request_id=request_id,
                status="success",
                data=redacted_data,
                redaction_applied=len(rls_result.redaction_rules) > 0,
                cache_hit=False,
                execution_time_ms=execution_time,
            )

        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown tool: {tool_name}",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Tool execution error for request {request_id}: {e}")
        execution_time = (time.time() - start_time) * 1000
        return MCPResponse(
            request_id=request_id,
            status="error",
            error=str(e),
            execution_time_ms=execution_time,
        )
