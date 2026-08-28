"""Motor de base de datos async + sesión por request."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from .config import get_settings

settings = get_settings()

if settings.echo_env == "test":
    # En tests cada TestClient crea su propio event loop: sin pool para no
    # compartir conexiones asyncpg entre loops.
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
else:
    engine = create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
    )

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
