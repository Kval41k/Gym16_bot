"""Use the application's transaction; async CLI is supported too."""
import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from database import Base, get_db_url
import models


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.config.attributes.get('connection') is not None:
    run(context.config.attributes['connection'])
elif context.is_offline_mode():
    raise RuntimeError('Baseline requires a live schema inspection; use an empty test database')
else:
    async def online():
        engine=create_async_engine(get_db_url())
        async with engine.begin() as conn:
            await conn.run_sync(run)
        await engine.dispose()
    asyncio.run(online())
