"""Real PostgreSQL regressions in disposable databases; never use a production DSN."""
import asyncio,os,subprocess,sys
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
ROOT=Path(__file__).resolve().parents[1]
async def run():
    dsn=os.getenv('GYM16_POSTGRES_TEST_ADMIN_URL')
    if not dsn:
        print('SKIP: disposable PostgreSQL service is provided by CI');return
    import asyncpg
    admin=await asyncpg.connect(dsn)
    try:
        for suite in ('check_security_and_comments','check_headman','check_features','check_community'):
            name='gym16_ci_'+suite
            # Prefix and fixed names prevent accidental use of an existing database.
            if await admin.fetchval('SELECT 1 FROM pg_database WHERE datname=$1',name):
                raise RuntimeError('Refusing to overwrite existing test database')
            await admin.execute(f'CREATE DATABASE "{name}"')
            parts=urlsplit(dsn);url=urlunsplit((parts.scheme,parts.netloc,'/'+name,'',''))
            try:
                env={**os.environ,'GYM16_TEST_DATABASE_URL':url.replace('postgresql://','postgresql+asyncpg://',1)}
                result=await asyncio.to_thread(subprocess.run,[sys.executable,str(ROOT/'tests'/f'{suite}.py')],env=env,capture_output=True,text=True)
                if result.returncode:raise AssertionError(suite+'\n'+(result.stdout+result.stderr)[-5000:])
                print('PASS PostgreSQL '+suite,flush=True)
            finally:
                await admin.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
    finally:await admin.close()
asyncio.run(run())
