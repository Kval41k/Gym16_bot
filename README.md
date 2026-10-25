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

The `Procfile` runs the idempotent `seed_data.py` before the service starts. It inserts the built-in timetable only when the lessons table is empty and does not replace later edits. The reviewed photo snapshots now include 11Б; each source is applied once with a backup before replacement.

The current Render process runs the web API and Telegram long-polling bot together. A restart or free-service sleep stops both. For a larger deployment, run the bot as a separate always-on worker and use shared PostgreSQL, Redis, and persistent media storage.

## Student tools and administration

- Schedule supports day/week views, current/next lesson emphasis, notes and profile filters. 11Б now uses the supplied photographed timetable. Monday times are shared by the lesson cards and reminders. Saturday reminders require explicit Saturday bells in `bell_schedules`; unknown times are never invented.
- Each lesson may have its own `start_time`/`end_time` in Tyumen time; those values take precedence over the bell defaults in cards, live status and reminders. The reviewed 11А Soc-gum timetable is in `data/11a_socgum_schedule.json`, checked against two matching weeks and the recurring school events in Google Calendar on 2026-10-24. The current administrator-corrected snapshot contains 36 weekly activities: IT Lab and the informatics consultation are excluded; the Saturday profile-maths consultation is shared by both 11А profiles (10:00–12:00, Ермакова М.В., 3/306). Ordinary informatics remains. Other personal calendar events and account identifiers are excluded. Live status uses actual class/profile lessons, including Saturday's 10:00–12:00 consultation.
- `data_updates.py` applies that reviewed snapshot once per revision during seeding/startup. Before applying, it saves the previous 11А rows in the private backup directory. Former common 11А rows are retained for the philology profile; the Soc-gum rows receive the calendar's exact subjects, teachers, rooms and times. An `applied_data_updates` marker prevents subsequent restarts from overwriting later admin edits. This is a reviewed snapshot, not a background connection to a personal Google account.
- Profile settings opt into Telegram reminders (5, 10 or 15 minutes) and notifications about published schedule changes. A user must start the bot first. Reminders run every 30 seconds while the API process is awake. Missed reminders are not sent after the service wakes up. Sending is reserved atomically: uncertain deliveries are not retried automatically, to avoid duplicates.
- EGE materials have text/topic/task search, bookmarks and studied marks, stored per Telegram account. The reviewed 2027 draft catalog seeds 47 original theory notes and a private 150-item practice bank; see below.
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
python tests/check_calendar_sync.py
python tests/check_security_and_comments.py
node tests/check_theme.cjs
```

The check uses a temporary SQLite database, fake signed Telegram identities and no real Telegram sends. It covers admin authorization, isolation of personal data, atomic audit history (including bot actions), news status, reactions and comments, EGE progress, CSV validation, schedule revision conflicts, reminder/send deduplication and backup export/restore. An uncertain Telegram response is simulated to verify that it cannot cause a duplicate send. Recovery is also checked against an already populated database and must be refused.

## Themes, comments and frontend build

Profile → Appearance offers Telegram automatic, light and dark themes. Preferences are stored per account; changing the theme preserves notification settings. Authors can edit their comments, with revision conflict protection and an audit history.

Private images use authenticated fetches and blob URLs. Do not embed `/uploads/` or `/api/media/` directly in unauthenticated image elements; use `protectedImageAttrs` / `setProtectedImage`. Uploads are decoded and re-encoded; HEIC must first be converted to JPEG.

Tailwind CSS is built locally; the generated `static/ui.css` is committed and Render does not require Node. After editing templates/classes, run `pnpm install --ignore-scripts` and `pnpm run build:css`. Runtime versions are constrained in `requirements.lock.txt`. Review and test dependency updates before changing the lock.

See [PROJECT_REVIEW.md](PROJECT_REVIEW.md) for the dated security review, test coverage, remaining infrastructure limitations and proposed improvements.

## Dated changes, invitations and editors

- Admin → Schedule → **Замены и отмены на дату** loads a complete class day, including both profiles. Edit individual rows or cancel all lessons, review the confirmation and publish. A date override replaces that day only. **Вернуть обычное расписание** removes the override and uses the current weekly schedule again. Revision conflicts require reloading the date. Cards, live status, next lesson and reminders all use date overrides; publishing cancels queued lesson reminders for that class/date.
- Students use weekday buttons, day/week views, Today and Tomorrow; arbitrary date selection is restricted to administration. The personal next-lesson card always uses the student's own class/profile and the actual current time, independently of which class/week is being viewed.
- News search runs on the server before pagination, matches title/content and ignores Russian letter case. Up to three approved announcements may be pinned by an administrator or editor. Draft text and anonymity are saved privately per account, with revision protection against overwriting another device's draft. Images must be selected again after closing the composer; the UI explicitly explains this. Draft text is not copied into the administrative activity log.
- Invitations are optional and **off by default**. Admin → Invitations creates codes with expiration (1–90 days), a maximum activation count and revocation. The clear code is shown once; only its hash is stored. Enabling invitation-only access retains all accounts registered at that moment. Accounts registered afterwards must redeem a valid code. Revoking a code stops future activations; ban a user separately to remove their access. Public timetables remain available without an invitation. Class membership is still chosen by the user; the code confirms access to the community, not enrollment in a specific class.
- Administrators may assign or remove `editor` in Admin → Users. Editors can moderate/edit/delete news, pin announcements, remove comments and manage EGE materials. They cannot edit another author's comment text, manage users/invitations, change schedules, read logs, export users or download backups. Only configured environment identities are administrators; application APIs cannot promote a user to administrator. Editorial permissions take effect on the server immediately; reopen the Mini App to refresh the affected user's navigation.
- The bot also enforces the optional membership gate. Hosting, persistence and the existing Render plan have not been changed.

Additional integration checks: `python tests/check_community.py` (including concurrent invite redemption, dated replacement/cancellation/reset, next lessons/reminders, role separation, private drafts and a backup round trip with the new tables).

## School/EGE-2027 release

See [SCHOOL_RELEASE_2027.md](SCHOOL_RELEASE_2027.md) for official sources, format mapping, photo-transcription decisions and training boundaries. `learning.py` seeds the reviewed study catalog once and serves authenticated practice sessions. Correctly solved items are excluded permanently from the account queue; mistakes remain for review. Duplicate submissions are idempotent and answer keys are never served as static assets. Longer-answer tasks train objective subskills rather than pretending to grade a whole proof or essay.

`data/photo_timetables_20261025.json` contains the approved photo transcription. `apply_photo_timetables` replaces 11В/11Г/11Д/11Ж and the separate 11Б snapshot once, backs up old rows, and aligns 11А philology times. `data/ege_2027.json` contains the theory; `data/practice_2027.json` is the server-side question bank. Rebuild authored content with `python scripts/build_ege_content.py`. Changing published content later requires a reviewed version/migration so existing administrator edits and user progress are preserved.

Additional release checks: `python tests/check_school_release.py`. The profile reminder control is a keyboard-accessible 5/10/15 minute slider, and subgroup selection is explicit. Hosting and persistent-storage provisioning remain deferred.

## Старосты и чаты классов

Добавлена роль старосты с отдельной вкладкой: расписание своего класса, посещаемость и питание. Подключение группы, опрос на 07:00, меню и ограничения бесплатного хостинга описаны в [HEADMAN_RELEASE.md](HEADMAN_RELEASE.md).
