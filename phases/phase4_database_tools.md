# Phase 4 — Database Tools

## 1. Architecture Explanation
Exposing an enterprise database (like PostgreSQL) to an LLM is extremely high-risk. A naïve implementation would allow an LLM to hallucinate a `DROP TABLE users` command or read data belonging to another tenant via a poorly crafted `WHERE` clause.

To execute queries securely in an MCP environment:
1. **Never Accept Raw SQL from the LLM:** The LLM must call structured tools like `search_users(email: str)` or `get_invoice(id: str)`. The backend maps these to strict, parameterized SQL.
2. **Row-Level Security (RLS):** For multi-tenant databases, queries must automatically execute under a specific `tenant_id`. PostgreSQL natively supports RLS via `SET LOCAL rls.tenant_id = 'XYZ'`.
3. **Connection Pooling & Async:** Machine-driven querying is high-volume. You must use `AsyncPG` with `SQLAlchemy 2.0` connection pooling to prevent starving the database of connections.
4. **Timeouts & Limits:** The agent might request `SELECT * FROM massive_logs`. Queries must be capped with a hard `LIMIT` and enforced statement timeouts.

## 2. Folder Structure
```text
backend/app/
├── tools/
│   └── database/
│       ├── __init__.py
│       ├── engine.py       # Async SQLAlchemy engine & pooling setup
│       ├── security.py     # RLS injection and timeout wrappers
│       └── handlers.py     # Specific database tool implementations
```

## 3. Exact Code Implementation

### A. Async Engine & Pooling (`tools/database/engine.py`)
Setup the high-performance async connection pool.

```python
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

# Environment variable, e.g., postgresql+asyncpg://user:pass@host/dbname
DATABASE_URL = os.environ.get("DATABASE_URL")

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    pool_size=20,         # Core connection pool size
    max_overflow=10,      # Overflow connections allowed during spikes
    pool_timeout=30,      # Give up if no connection available in 30s
)

# Factory for creating database sessions
AsyncSessionFactory = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)
```

### B. Security & RLS Execution (`tools/database/security.py`)
This context manager handles acquiring a session, setting the Postgres timeout, and injecting the Tenant ID for Row-Level Security.

```python
import logging
from contextlib import asynccontextmanager
from sqlalchemy import text
from app.tools.database.engine import AsyncSessionFactory
from app.models.auth import UserContext

logger = logging.getLogger(__name__)

@asynccontextmanager
async def secure_tenant_session(user: UserContext):
    """
    Yields a secure database session bound to the user's tenant,
    with strict execution timeouts to prevent DoS.
    """
    async with AsyncSessionFactory() as session:
        try:
            # 1. Enforce strict query timeout (e.g., 5 seconds)
            # This prevents the LLM from triggering complex, long-running queries
            await session.execute(text("SET statement_timeout = 5000;"))
            
            # 2. Inject RLS Tenant ID
            # Assumes Postgres has RLS policies defined using current_setting('app.current_tenant')
            tenant_stmt = text("SET LOCAL app.current_tenant = :tenant_id;")
            await session.execute(tenant_stmt, {"tenant_id": user.tenant_id})
            
            # Yield the secured session for the tool to use
            yield session
            
        except Exception as e:
            logger.error(f"Database session error for tenant {user.tenant_id}: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
```

### C. Tool Handlers (`tools/database/handlers.py`)
Here we define the explicit tools the LLM can call. Notice the SQL is strictly parameterized.

```python
from typing import Dict, Any, List
from sqlalchemy import text
from app.tools.database.security import secure_tenant_session
from app.models.auth import UserContext

async def search_customers(
    email_domain: str, 
    user_context: UserContext
) -> Dict[str, Any]:
    """
    Tool: Search for customers by email domain.
    LLM Payload Example: {"email_domain": "acme.com"}
    """
    query = text("""
        SELECT id, name, email, status 
        FROM customers 
        WHERE email LIKE :domain
        ORDER BY created_at DESC
        LIMIT 50; -- Hard limit enforced in code
    """)
    
    # Notice we pass the UserContext injected by the router middleware!
    async with secure_tenant_session(user_context) as session:
        try:
            # Use strict parameter binding to prevent SQL Injection
            result = await session.execute(query, {"domain": f"%@{email_domain}"})
            
            # Convert SQLAlchemy rows to a list of dicts
            rows = result.mappings().all()
            return {
                "success": True,
                "count": len(rows),
                "data": [dict(row) for row in rows]
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

async def get_invoice_summary(
    customer_id: str, 
    user_context: UserContext
) -> Dict[str, Any]:
    """Tool: Get invoice totals for a customer."""
    query = text("""
        SELECT SUM(amount) as total_spent, COUNT(id) as invoice_count
        FROM invoices
        WHERE customer_id = :cust_id
    """)
    
    async with secure_tenant_session(user_context) as session:
        try:
            result = await session.execute(query, {"cust_id": customer_id})
            row = result.mappings().first()
            return {"success": True, "data": dict(row) if row else {}}
        except Exception as e:
            return {"success": False, "error": str(e)}
```

### D. Tool Registration & Execution
In your `routes/mcp.py` (from Phase 2), you modify the dispatcher to pass the `user_context` into the handler.

```python
# In registry_engine.py:
async def execute_tool(self, request: ToolCallRequest, user_context: UserContext):
    _, handler = self._tools[request.tool_name]
    # Inject the user context dynamically so the tool knows who is calling it
    result = await handler(**request.arguments, user_context=user_context)
    return ToolCallResponse(success=True, data=result)
```

## 4. Security Reasoning
- **Postgres RLS (`app.current_tenant`):** Even if the developer forgets to add `WHERE tenant_id = XYZ` in the SQL string, the Postgres database engine itself will drop rows belonging to other tenants. This is a critical defense-in-depth layer.
- **`text()` Binding:** Using SQLAlchemy's `text("... :var")` and passing a dictionary natively uses Postgres prepared statements. It is impossible for the LLM to inject `' OR 1=1; DROP TABLE users;` via the `email_domain` argument.
- **No Raw SQL Tool:** We never expose a tool like `execute_sql(query="...")`. The LLM's capability is bounded to the specific business questions codified by engineers.

## 5. Scaling Reasoning
- **AsyncPG:** The underlying driver (AsyncPG) is 3x-4x faster than synchronous `psycopg2`. It allows a single FastAPI worker to handle hundreds of concurrent database reads while waiting for I/O.
- **Connection Pooling:** By limiting `pool_size`, we ensure that 1,000 LLM agents making simultaneous requests don't spawn 1,000 Postgres connections (which would crash Postgres via Out-Of-Memory). Requests queue gracefully at the application layer.

## 6. Common Production Pitfalls
- **Missing Limits:** An LLM might ask for "all users". If your code does `SELECT * FROM users` without a `LIMIT 100`, millions of rows serialize into RAM, crashing the pod, and then crashing the LLM prompt due to token limits. Always hardcode `LIMIT`s.
- **Transaction Deadlocks:** If a tool tries to write data (e.g., `create_user`), keep transactions extremely short. LLM latency is high; never hold a database lock open while waiting for an LLM network response.

## 7. Enterprise Best Practices
- **Read Replicas:** Route LLM-driven query tools to a Postgres Read Replica. LLM workloads are unpredictable and can be computationally heavy. They should not impact the primary write database serving human users.
- **Data Masking:** Within your SQL queries, actively mask PII (e.g., `CONCAT('****', SUBSTRING(ssn FROM 6))`) before returning it to the LLM. The LLM rarely needs raw PII to reason about workflows.

## 8. Step-by-Step Setup Instructions
1. Install dependencies: `pip install sqlalchemy asyncpg greenlet`.
2. Configure your Postgres database to enforce RLS (Requires `CREATE POLICY ... ON table USING (tenant_id = current_setting('app.current_tenant'))`).
3. Add the `engine.py`, `security.py`, and `handlers.py` files.
4. Register the tools in your main registry logic.

## 9. Example Request / Response

**LLM Intent:** "Find all acme.com customers."
**Tool Request:**
```json
{
  "tool_name": "db.search_customers",
  "arguments": {
    "email_domain": "acme.com"
  }
}
```

**Secure Response:**
```json
{
  "success": true,
  "data": {
    "count": 2,
    "data": [
      {"id": "c_123", "name": "Alice", "email": "alice@acme.com", "status": "active"},
      {"id": "c_456", "name": "Bob", "email": "bob@acme.com", "status": "churned"}
    ]
  }
}
```

---
**Status:** Phase 4 complete. Awaiting confirmation to proceed to Phase 5 (Salesforce Tools).
