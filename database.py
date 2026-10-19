from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from config import settings

def get_db_url() -> str:
    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

DB_URL = get_db_url()

# Async SQLAlchemy engine
engine = create_async_engine(
    DB_URL,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in DB_URL else {}
)

# Async session factory
async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

# Base class for all models
class Base(DeclarativeBase):
    pass

# FastAPI Dependency for database session
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

# Database initialization (creates tables and initial seeds)
async def init_db() -> None:
    from models import SchoolClass, Profile, BellSchedule
    from config import DEFAULT_CLASSES, ALL_PROFILES, DEFAULT_BELLS
    from sqlalchemy import select

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # 1. Seed classes if missing
        class_res = await session.execute(select(SchoolClass))
        existing_classes = {c.name for c in class_res.scalars().all()}
        for name in DEFAULT_CLASSES:
            if name not in existing_classes:
                session.add(SchoolClass(name=name))

        # 2. Seed profiles if missing
        prof_res = await session.execute(select(Profile))
        existing_profiles = {p.name for p in prof_res.scalars().all()}
        for name in ALL_PROFILES:
            if name not in existing_profiles:
                session.add(Profile(name=name))

        # 3. Seed bell schedule if empty
        bell_res = await session.execute(select(BellSchedule))
        if not bell_res.scalars().first():
            for b in DEFAULT_BELLS:
                session.add(BellSchedule(
                    lesson_number=b["lesson_number"],
                    start_time=b["start_time"],
                    end_time=b["end_time"],
                    is_saturday=False
                ))

        await session.commit()
