TigerSnatch Priority Watcher (ntfy)

Simple standalone script that polls Princeton Student App course seats for your selected sections and sends push notifications via ntfy. It does not depend on, nor modify, the TigerSnatch app.

Requirements
- Python 3.9+
- `pip install -r requirements.txt`
- Environment variables (no secrets checked into code):
  - `CONSUMER_KEY` and `CONSUMER_SECRET` (from your Heroku config vars)
  - `NTFY_TOPIC` (your topic on https://ntfy.sh, e.g., a long random string)
  - Optional: `TERM_CODE` (e.g., `1252`); if not set, the script auto-detects latest term

Run examples
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

