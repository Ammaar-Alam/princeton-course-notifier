Princeton Course Notifier (ntfy) — CLI + Web

Simple notifier that polls Princeton Student App course seats for your selected sections and sends push notifications via ntfy. Includes:
- CLI watcher (local) — `watcher.py`
- Minimal web dashboard (Heroku) to select sections and manage your ntfy topic

Requirements (CLI)
- Python 3.9+
- `pip install -r requirements.txt`
- Environment variables (no secrets checked into code):
  - `CONSUMER_KEY` and `CONSUMER_SECRET` (from your Heroku config vars)
  - `NTFY_TOPIC` (your topic on https://ntfy.sh, e.g., a long random string)
  - Optional: `TERM_CODE` (e.g., `1252`); if not set, the script auto-detects latest term

Run examples (CLI)
- COS333 lecture 01 and precept 01, poll every 20s:
  - `python watcher.py --courses COS333:L01,P01 --interval 20`

- Multiple courses:
  - `python watcher.py --courses COS333:L01,P01 COS126:L01`

- Using course/class IDs directly (bypasses lookup):
  - `python watcher.py --ids 002054:21931,21927`

Flags
- `--interval <secs>`: polling cadence (default 30)
- `--min-renotify <mins>`: minimum minutes before repeating a notification for the same open-count (default 2)
- `--topic <topic>`: overrides `NTFY_TOPIC` env var
- `--ntfy-url <url>`: override ntfy base (`https://ntfy.sh` by default)

Notes
- Student App endpoints are rate-limited; keep intervals reasonable (10–30s is generally fine).
- Reserved-seat courses can be Open while still not enrollable for you; the script notifies on `status==Open` and `capacity > enrollment`.
- For iOS/Android, install the ntfy app and subscribe to your topic.

Web dashboard (Heroku)
- App location: `webapp/` (Flask + SQLAlchemy). Worker polls subscriptions stored in DB and pushes to per-user ntfy topics.
- Configure env vars (Heroku dashboard or CLI):
  - `CONSUMER_KEY`, `CONSUMER_SECRET` — Student App credentials
  - `SECRET_KEY` — Flask session secret
  - `ADMIN_TOKEN` — simple access token required to login
  - `DATABASE_URL` — Postgres URL (Heroku Postgres add-on)
  - `INTERVAL_SECS` — poll cadence (e.g., 20–30)
  - `MIN_RENOTIFY_SECS` — re-notify throttle (default 20)
  - Optional: `TERM_CODE`, `NTFY_URL`

Deploy steps (Heroku)
1. Create app & add Python buildpack.
2. Provision Postgres: `heroku addons:create heroku-postgresql:hobby-dev -a <app>`
3. Set env vars above.
4. Push repo; scale dynos: `heroku ps:scale web=1 worker=1 -a <app>`
5. Visit `/login`, enter `ADMIN_TOKEN`, set your `ntfy_topic`, search courses, and subscribe.

