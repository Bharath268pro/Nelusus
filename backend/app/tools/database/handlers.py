from typing import Dict, Any
from sqlalchemy import text
from .security import secure_tenant_session
from app.models.security import JWTToken

async def search_customers(email_domain: str, user_context: JWTToken) -> Dict[str, Any]:
    return {"success": True, "count": 2, "data": [{"name": "Mock", "email": f"test@{email_domain}"}]}

async def get_invoice_summary(customer_id: str, user_context: JWTToken) -> Dict[str, Any]:
    return {"success": True, "data": {"total_spent": 500.0, "invoice_count": 2}}
