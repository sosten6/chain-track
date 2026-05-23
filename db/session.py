from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from config.settings import settings
import logging

logger = logging.getLogger(__name__)

# Create async engine with better settings for Neon + Windows
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    connect_args={"server_settings": {"application_name": "smartchain-tracker"}}
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def get_db():
    """Get database session"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

async def init_db():
    """Create all tables on startup"""
    from db.models.base import Base
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {e}")
        raise