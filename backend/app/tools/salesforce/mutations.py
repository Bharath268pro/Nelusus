import logging
from typing import Dict, Any
from .client import SalesforceClient
from app.models.security import JWTToken

logger = logging.getLogger("audit_logger")

async def create_lead(
    sf_client: SalesforceClient, 
    user_context: JWTToken,
    first_name: str, 
    last_name: str, 
    company: str, 
    email: str
) -> Dict[str, Any]:
    """Tool: Create a new Lead in Salesforce."""
    
    payload = {
        "FirstName": first_name,
        "LastName": last_name,
        "Company": company,
        "Email": email,
        "LeadSource": "AI_Agent_MCP"
    }

    # AUDIT LOG: Record the mutation intent BEFORE execution
    logger.info(
        f"AUDIT | user_id={user_context.sub} "
        f"action=SALESFORCE_CREATE_LEAD payload={payload}"
    )

    try:
        response = await sf_client.request("POST", "sobjects/Lead/", json=payload)
        result = response.json()
        
        # AUDIT LOG: Record success
        logger.info(f"AUDIT | action=SALESFORCE_CREATE_LEAD status=SUCCESS sf_id={result.get('id')}")
        return {"success": True, "lead_id": result.get("id")}
        
    except Exception as e:
        logger.error(f"AUDIT | action=SALESFORCE_CREATE_LEAD status=FAILED error={str(e)}")
        return {"success": False, "error": "Failed to create lead in Salesforce."}
