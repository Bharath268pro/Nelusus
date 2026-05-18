import logging
from contextlib import asynccontextmanager
from sqlalchemy import text
from .engine import AsyncSessionFactory
from app.models.security import JWTToken

logger = logging.getLogger(__name__)

@asynccontextmanager
async def secure_tenant_session(user: JWTToken):
    async with AsyncSessionFactory() as session:
        try:
            await session.execute(text("SET statement_timeout = 5000;"))
            # In a real RLS setup, we'd uncomment this:
            # await session.execute(text("SET LOCAL app.current_tenant = :tenant;"), {"tenant": user.tenant_id})
            yield session
        except Exception as e:
            logger.error(f"DB session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
