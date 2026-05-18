from urllib.parse import quote
from typing import Dict, Any, List
from .client import SalesforceClient

async def search_contacts(sf_client: SalesforceClient, email: str) -> List[Dict[str, Any]]:
    """Tool: Find a Salesforce Contact by Email."""
    
    # We use SOSL (Salesforce Object Search Language) or parameter-safe SOQL
    # Sanitize the email to prevent SOQL injection
    clean_email = email.replace("'", "\\'")
    
    query = f"SELECT Id, Name, Title, Account.Name FROM Contact WHERE Email = '{clean_email}' LIMIT 5"
    
    # The client handles authentication and 401 retries automatically
    try:
        response = await sf_client.request("GET", f"query/?q={quote(query)}")
        data = response.json()
        return data.get("records", [])
    except Exception as e:
        return [{"error": str(e)}]

async def get_opportunity_details(sf_client: SalesforceClient, opp_id: str) -> Dict[str, Any]:
    """Tool: Get details of a specific opportunity."""
    # Using the standard REST object retrieval (No SOQL injection risk at all)
    try:
        response = await sf_client.request("GET", f"sobjects/Opportunity/{opp_id}")
        return response.json()
    except Exception as e:
        return {"error": str(e)}
