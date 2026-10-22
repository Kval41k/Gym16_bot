# Gymnasium 16 Telegram Mini App

Telegram Mini App and bot for the 11th-grade classes: timetable, school news and moderation, user profiles, and EGE materials.

## Run locally

1. Create a virtual environment and install `requirements.txt`.
2. Copy `.env.example` to `.env` and set `BOT_TOKEN`, `ADMIN_IDS` or `ADMIN_USERNAME`, and `BASE_URL`.
3. Run `python seed_data.py` once to create the initial timetable, then run `python run.py`.
4. Open the HTTPS `BASE_URL` as the Telegram Mini App URL. For local development, use the existing tunnel workflow.

`python run.py --api-only` starts the HTTP API. `python run.py --bot-only` starts the bot and initializes the database.

## Configuration

- `BOT_TOKEN` — Telegram bot token.
- `ADMIN_IDS` — comma-separated Telegram IDs. `ADMIN_USERNAME` can contain one or more comma-separated usernames.
- `BASE_URL` — public HTTPS application URL; used for Telegram links and as the default allowed CORS origin.
- `CORS_ORIGINS` — optional comma-separated allowed origins. Leave unset to allow only `BASE_URL`.
- `DATABASE_URL` — SQLAlchemy async database URL. PostgreSQL URLs are normalized to `asyncpg` automatically. If omitted, SQLite is used.
- `UPLOAD_DIR` — optional upload directory. If omitted, `RENDER_DISK_PATH/uploads` is used when Render exposes a mounted disk; otherwise uploads go under the project directory.
- `BOT_STORAGE_URL` — optional Redis URL for persistent bot conversation state. Without it, temporary conversations use in-memory storage and disappear on process restart.

## Hosting and data persistence

Render's free web service has an ephemeral filesystem. SQLite and uploads stored there can be lost on deploy, restart, or spin-down. For persistent SQLite and uploads, attach a Render disk and set `RENDER_DISK_PATH` to its mount path. Alternatively, set `DATABASE_URL` to a managed PostgreSQL database and `UPLOAD_DIR` to persistent or object storage. Keep backups for any production data.

The `Procfile` runs the idempotent `seed_data.py` before the service starts. It inserts the built-in timetable only when the lessons table is empty and does not replace later edits. There is intentionally no timetable seeded for 11Б until its source data is provided; the app reports that it has not been uploaded.

The current Render process runs the web API and Telegram long-polling bot together. A restart or free-service sleep stops both. For a larger deployment, run the bot as a separate always-on worker and use shared PostgreSQL, Redis, and persistent media storage.
