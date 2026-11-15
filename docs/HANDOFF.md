# LMS Guardian: status and next steps

Written 2026-11-15. Contains no passwords, tokens, webhook links or passphrases, on purpose.

## What it is

A read-only monitor for the Ain Shams Engineering Moodle (`lms.eng.asu.edu.eg`, Moodle 3.7.8) that sends
alerts to Telegram and Discord, with a control panel, and (not yet live) SIS grade capture through a
browser extension.

- Repo: `OMAR6972/lms-guardian` (public). All data files are encrypted, so only code is readable.
- Panel: `https://omar6972.github.io/lms-guardian/` (GitHub Pages, `index.html`).
- Telegram bot: `@omar_lms_guardian_bot`.

## How it fits together

```
Cloudflare Worker (every 2 min)  ->  GitHub Actions "LMS Guardian"  ->  python -m lms
                                         reads config.enc (panel edits this)
                                         reads state.enc  (bot memory)
                                         reads sis.enc    (written by the extension)
                                         Moodle web-service API (get_* calls only)
                                         -> Telegram people / Discord webhooks
Panel (index.html) and extension both decrypt in the browser with the DATA_KEY passphrase.
```

| Path | What it is |
|---|---|
| `lms/engine.py` | One run: Telegram commands, crawl, diff, notify, SIS intake, health warnings |
| `lms/snapshot.py`, `lms/diff.py` | Build per-subject snapshots; turn differences into events with a category |
| `lms/moodle.py`, `telegram.py`, `discord.py` | Clients. Moodle client refuses anything that is not a `_get_` call |
| `lms/vault.py` | AES-256-GCM + PBKDF2 (200k). Same format as the browser code |
| `index.html` | Panel: Subjects (chip per recipient), People (Telegram people, Discord channels, what-to-watch switches), Activity |
| `scheduler/` | Cloudflare Worker that dispatches the workflow |
| `extension/` | Chrome extension (MV3): dashboard (popup or full tab), floating Moodle bell. Opens with a per-person extension code |
| `feeds/` | One encrypted file per person with an extension code: only their subjects and switches (marks for the owner only) |
| `tests/test_lms.py` | 21 tests with fake Moodle/Telegram/Discord |

Secrets in GitHub Actions: `LMS_USER`, `LMS_PASS`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DATA_KEY`.

## Done and confirmed on the real systems

- Login through the Moodle mobile web service from GitHub's servers; all needed API functions allowed.
- Silent baseline, then real change alerts on Telegram (4 real changes logged in the first day).
- Panel unlock, subject ticking, adding a Discord channel, "Save & check now".
- Discord "Now following" message arrived in the owner's channel.

## Built and tested only with fakes or a mocked browser (NOT yet proven live)

1. **What-to-watch switches** (panel, People tab): materials, edits and removals, assignments, quizzes,
   announcements; owner also has Moodle grades and SIS grades. A missing switch means "on".
2. **Moodle grades**: `gradereport_user_get_grade_items` per tracked subject. First successful read is a
   silent baseline. Grades and SIS events go to the owner only, never to friends or Discord.
   If the call fails on the real server the log line is `grades skipped`, and nothing else breaks.
3. **SIS intake** (`process_sis`): reads `sis.enc`, baselines silently, alerts on new or changed rows,
   warns once when the extension reports "logged out" or has been silent for 12 hours.
4. **Extension**: dashboard (since last visit, history with search and filters, deadlines, grades,
   read/unread), floating bell on Moodle, "Watch this page for grades" button on the SIS,
   background re-read of watched SIS pages every 5 minutes while the browser is open.
   Loaded in headless Chromium and the dashboard was exercised; the SIS capture has never seen the real site.

## Next steps, in order

1. **Cloudflare timer** (owner was about to do this): Worker with the code from `scheduler/src/index.js`,
   variable `GITHUB_REPO=OMAR6972/lms-guardian`, secret `GITHUB_TOKEN` (Actions read and write on this
   repo), cron `*/2 * * * *`. Confirm runs appear every 2 minutes in Actions.
2. **Read one Actions log** and check three lines: `forums found N`, `checked X/Y subjects ...`, and
   whether `grades skipped` appears. Forum posts have been 0 in every subject; each subject has exactly one
   forum, so either nobody posted or the discussions call fails (a fallback call was added).
3. **Confirm the switches** suit him in the panel; adjust the category list if he wants finer control.
4. **Install the extension**: `chrome://extensions` -> Developer mode -> Load unpacked -> the `extension`
   folder (download the repo as ZIP first). Enter repo, GitHub key, data passphrase.
5. **SIS**: owner logs in himself (CAPTCHA is never bypassed), opens the grades page, presses
   "Watch this page for grades". Then tune `parseTables` in `extension/lib.js` to the real page.

## Questions to ask before finishing each part

- **Grades (Moodle):** do lecturers actually put grades on Moodle, or only on the SIS?
- **SIS session:** how long does a session last, and does it end when idle or after a fixed time even while
  in use? If idle-based, the 5-minute background re-read should keep it alive while the browser is open.
  If fixed, he logs in again when the bot warns him. Either way nothing is checked while the browser is closed.
- **SIS pages:** which pages show midterm, lab and final grades? Server-rendered tables or loaded by script?
  One page per term or per subject? Does the URL change per term?
- **SIS on a phone:** the extension is desktop Chrome only. Is that acceptable?
- **Extension dashboard:** popup size fine, or does he want a full tab? Should read/unread sync between devices?
- **Files:** still want new files sent as Telegram documents (the spec's "cached copy")? Not built.
- **Friends:** should friends ever get grade alerts for their own accounts? (Would need their own login; not planned.)

## Known limits

- Telegram commands are answered at the next run (about 2 to 3 minutes with the timer).
- Discord webhooks are one-way.
- The sandbox cannot reach the LMS, SIS, Telegram or Discord; live behaviour is verified through Actions
  and through what the owner sees. This session's GitHub access could push code but not read Actions logs
  or set secrets.
- The old private repo of the same name was replaced; if alerts ever arrive twice, check for a leftover.

## 2026-11-15: extension reworked for several people

- Panel, People tab: "Make extension code" / "Copy extension code" per Telegram person (owner too). A new code
  replaces the old one; the old feed file is deleted at the next run.
- The bot writes `feeds/<sha256("lms-guardian-feed:"+code)[:24]>.enc`, encrypted with that code, only when it changes.
  Friends' feeds never contain marks, SIS, or other people's subjects.
- The extension needs only the code (reads the feed from raw.githubusercontent.com; no GitHub key, no data passphrase).
  Grades tab shows for the owner only. "Open in tab" button. SIS page script removed from the manifest while SIS is
  skipped; the SIS code in background.js is dormant and needs owner keys again when SIS is resumed.
- "Announcements & posts" switch renamed "Forum posts".
