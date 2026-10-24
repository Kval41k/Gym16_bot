from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import inspect, event
from config import BASE_DIR, settings

def get_db_url() -> str:
    url = settings.database_url
    if "sqlite" in url and ("./gym16.db" in url or ":///./" in url):
        return f"sqlite+aiosqlite:///{BASE_DIR}/gym16.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

DB_URL = get_db_url()

# High-performance async SQLAlchemy engine with connection pooling
is_sqlite = "sqlite" in DB_URL
engine_kwargs = {
    "echo": False,
    "future": True,
}
if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    engine_kwargs["pool_size"] = 25
    engine_kwargs["max_overflow"] = 35
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300

engine = create_async_engine(DB_URL, **engine_kwargs)

if is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def sqlite_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

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
    from sqlalchemy import select, text

    async with engine.begin() as conn:
        if is_sqlite:
            await conn.execute(text("PRAGMA journal_mode = WAL;"))
            await conn.execute(text("PRAGMA synchronous = NORMAL;"))
            await conn.execute(text("PRAGMA cache_size = -64000;"))
            await conn.execute(text("PRAGMA foreign_keys = ON;"))
        await conn.run_sync(Base.metadata.create_all)
        user_columns = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_columns("users"))
        if "is_banned" not in {column["name"] for column in user_columns}:
            await conn.execute(text("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT FALSE NOT NULL"))
        lesson_columns = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_columns("lessons"))
        for name in ("start_time", "end_time"):
            if name not in {column["name"] for column in lesson_columns}:
                await conn.execute(text(f"ALTER TABLE lessons ADD COLUMN {name} VARCHAR(5)"))

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

        # 4. Seed EGE subjects (Russian 27 tasks, Math 20 tasks).
        # Materials list is left empty initially per user request.
        from models import EgeSubject
        subj_res = await session.execute(select(EgeSubject))
        existing_subjects = {s.code: s for s in subj_res.scalars().all()}
        
        if "russian" not in existing_subjects:
            session.add(EgeSubject(code="russian", name="Русский язык", icon="📖", tasks_count=27))
        else:
            existing_subjects["russian"].tasks_count = 27

        if "math" not in existing_subjects:
            session.add(EgeSubject(code="math", name="Математика", icon="📐", tasks_count=20))
        else:
            existing_subjects["math"].tasks_count = 20

        await session.commit()
