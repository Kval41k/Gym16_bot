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

## Student tools and administration

- Schedule supports day/week views, current/next lesson emphasis, notes and profile filters. 11Б remains empty until an administrator publishes its real timetable. Monday times are shared by the lesson cards and reminders. Saturday reminders require explicit Saturday bells in `bell_schedules`; unknown times are never invented.
- Profile settings opt into Telegram reminders (5, 10 or 15 minutes) and notifications about published schedule changes. A user must start the bot first. Reminders run every 30 seconds while the API process is awake. Missed reminders are not sent after the service wakes up. Sending is reserved atomically: uncertain deliveries are not retried automatically, to avoid duplicates.
- EGE materials have text/topic/task search, bookmarks and studied marks, stored per Telegram account in the database.
- News authors can see their last 100 submissions and moderation status. An administrator can optionally supply a rejection reason visible to the author. Telegram moderation continues to work; reasons are entered through the app.
- Admin → Schedule loads one class's week into an editable grid. CSV import supports UTF-8, comma/semicolon separators and Russian or English headers. Preview validates profiles and duplicate slots. Publishing uses a revision check and replaces only the selected class, preserving other classes. An empty preview explicitly clears that class. Students who opted into change notifications receive a summary.
- Admin → Logs shows committed additions, changes and deletions from the app and bot, with actor, Telegram ID, time, section and field values. Reactions, deleted comments, profile changes, EGE progress and timetable changes are recorded. Failed or rolled-back transactions do not leave audit records. Search, action/section/date filters and cursor pagination are available. Existing historical actions cannot be reconstructed; logging begins with this version. Logs are visible only to verified administrators.

Example CSV (day 0 = Monday; empty profile = whole class):

```csv
день;урок;предмет;учитель;кабинет;профиль;группа;примечание
Пн;1;История;Иванов И. И.;12;Соц-гум;;Замена кабинета
Вт;2;Литература;Петрова А. А.;15;;;
```

## Backups and recovery

Admin → Data downloads a ZIP containing `data.json` (all database tables, including logs) and local `uploads/`. Credentials and `.env` are excluded. A daily local backup is made while the API process is running; the last seven archives are retained. Set `BACKUP_DIR` to change its location. The default is `backups/` next to `uploads/`. That directory is private and is never exposed as static content.

Local backups on an ephemeral Render disk are lost with the disk. Store downloaded copies elsewhere, or set `DATABASE_URL` to external PostgreSQL and place `UPLOAD_DIR` and `BACKUP_DIR` on a persistent Render disk. This code does not provision an external database, a disk or an offsite backup service. The Data screen reports the current storage configuration.

To recover, stop the application, set `DATABASE_URL` to an **empty** destination database and `UPLOAD_DIR` to an empty folder, then run:

```sh
python backup_restore.py /path/to/gym16-backup.zip
python backup_restore.py /path/to/gym16-backup.zip --apply
```

The first command only inspects the archive. Restore refuses to overwrite an existing database or existing media. Verify recovery before starting the service. Deploying code against an existing database creates the new tables without clearing the existing ones.

## Checks

```sh
python tests/check_features.py
```

The check uses a temporary SQLite database, fake signed Telegram identities and no real Telegram sends. It covers admin authorization, isolation of personal data, atomic audit history (including bot actions), news status, reactions and comments, EGE progress, CSV validation, schedule revision conflicts, reminder/send deduplication and backup export/restore. An uncertain Telegram response is simulated to verify that it cannot cause a duplicate send. Recovery is also checked against an already populated database and must be refused.
