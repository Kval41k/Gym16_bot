"""Inspect a portable backup; restore only explicitly, into an empty database."""
import argparse
import asyncio
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, func, select, text
from config import settings
from database import Base, engine
import models  # Register every table, including audit history.


async def restore(path: Path, apply: bool):
    with zipfile.ZipFile(path) as archive:
        data = json.loads(archive.read("data.json"))
        if data.get("format") != "gym16-backup-v1":
            raise ValueError("Unknown backup format")
        tables = {table.name: table for table in Base.metadata.sorted_tables}
        unknown = set(data["tables"]) - set(tables)
        if unknown:
            raise ValueError("Unknown tables in archive")
        media = []
        for name in archive.namelist():
            if not name.startswith("uploads/") or name.endswith("/"):
                continue
            destination = (settings.UPLOAD_DIR / name[len("uploads/"):]).resolve()
            if not destination.is_relative_to(settings.UPLOAD_DIR.resolve()):
                raise ValueError("Unsafe media path in archive")
            media.append((name, destination))
        print("Backup:", data["created_at"])
        print("Rows:", sum(len(rows) for rows in data["tables"].values()), "Media files:", len(media))
        if not apply:
            print("Inspection only. Stop the application and use --apply with an EMPTY destination database to restore.")
            return
        if any(destination.exists() for _, destination in media):
            raise ValueError("Destination media already exists; restore into a fresh UPLOAD_DIR")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for table in tables.values():
                if await conn.scalar(select(func.count()).select_from(table)):
                    raise ValueError("Destination database is not empty; restore refused")
            for table in Base.metadata.sorted_tables:
                rows = data["tables"].get(table.name, [])
                for row in rows:
                    for column in table.columns:
                        if isinstance(column.type, DateTime) and row.get(column.name):
                            parsed = datetime.fromisoformat(row[column.name])
                            row[column.name] = parsed.replace(tzinfo=timezone.utc) if column.type.timezone and parsed.tzinfo is None else parsed
                if rows:
                    await conn.execute(table.insert(), rows)
                if engine.dialect.name == "postgresql" and "id" in table.c and table.c.id.autoincrement is not False and table.c.id.primary_key:
                    sequence = await conn.scalar(text("SELECT pg_get_serial_sequence(:table, 'id')"), {"table": table.name})
                    if sequence:
                        await conn.execute(text(f"SELECT setval(:sequence, COALESCE((SELECT MAX(id) FROM {table.name}), 1), EXISTS(SELECT 1 FROM {table.name}))"), {"sequence": sequence})
            # Write media while the DB transaction can still be rolled back.
            written = []
            try:
                for name, destination in media:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(name))
                    written.append(destination)
            except Exception:
                for destination in written:
                    destination.unlink(missing_ok=True)
                raise
        print("Restored. Start the application only after checking the destination database and uploads.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    async def main():
        try:
            await restore(args.archive, args.apply)
        finally:
            await engine.dispose()
    asyncio.run(main())
