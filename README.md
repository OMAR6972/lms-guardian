# LMS Guardian

Personal, **read-only** Moodle monitor for Ain Shams Engineering.

- `lms/` – the bot (Python). Logs in through Moodle's mobile web service and only calls `*_get_*` functions.
  Detects new/changed/removed materials, files, assignments, quizzes, announcements and forum posts,
  with old → new values for deadline changes, and sends them over Telegram.
- `index.html` – the panel (GitHub Pages). Tick which subjects each person follows, add people, save once.
- `scheduler/` – Cloudflare Worker that starts the workflow every 2 minutes.
- `config.enc`, `state.enc` – **encrypted** (AES-256-GCM, key = the `DATA_KEY` secret). This repo is public,
  so nothing readable is ever committed: only code and encrypted blobs. Keep logs free of names too.

Secrets (GitHub → Settings → Secrets → Actions): `LMS_USER`, `LMS_PASS`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `DATA_KEY`.

Tests: `pip install -r requirements.txt pytest && pytest -q`.
