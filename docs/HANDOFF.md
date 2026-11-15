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
| `tests/test_lms.py` | 26 tests with fake Moodle/Telegram/Discord |

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
4. **Install the extension** (DONE 2026-11-15: owner installed it, code works, dashboard shows his feed): panel -> People -> Make extension code -> Save & check now;
   `chrome://extensions` -> Developer mode -> Load unpacked -> the `extension` folder (repo ZIP); paste the code.
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
- **Files:** DONE 2026-11-15, see below.
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

Live check 2026-11-15 after this change: run succeeded, `forums found: 5 in 5 subjects`,
`checked 5/5 subjects: 106 items, 0 forum posts, 0 failed`, no `grades skipped` (Moodle grades read works live).
Owner's current subjects use only files, folders, assignment slots and an empty forum; marks for projects,
assignments and quizzes are on Moodle; only midterm, lab and final are on the SIS.

## 2026-11-15: files as documents, friends' install guide

- New and updated files are sent as the actual file to everyone following the subject (Telegram people and
  Discord channels) who has "New materials & files" on. Downloaded once per run via the mobile token
  (`Moodle.download`, pluginfile.php on this site only). Limits: Telegram 50 MB, Discord 10 MB; bigger files or
  failed downloads get a short note. Folders: first 10 files + note. A file failure never repeats the alert.
- Live proof: Actions "Run workflow" with **selftest** ticked sends the newest file in the owner's subjects to the
  owner. Run on 2026-11-15 downloaded the Software Design Patterns (CSE336s) Course Project Specification PDF
  (146,680 bytes) and sent it with no error, to Telegram and (input `channel`) to the "Discord Alerts" channel.
- `install.html` on the panel's site: English/Arabic install guide for friends. Panel People tab:
  "Send code + guide on WhatsApp" and "Install guide" link next to each code.

## 2026-11-15: SIS marks in the extension

How the real SIS looks (checked live with the owner logged in, read-only):
- `/dashboard/my_courses`: current-year subjects as links `/dashboard/courses/show/<id>?committee_id=<n>` with text
  `CODE: Name (Fall 2026)`.
- Each subject page: marks boxes `<ul class="row no-gutters"><li>Midterm</li><li>- / 20</li></ul>` (Midterm,
  Activities, Practical; "-" = not out). Server-rendered.
- Profile (`/users/<id>/profile`, redirects to `/students/<id>`): "Study Grades" card, per-term tables of
  `<tr ><td>CODE</td><td>Name</td><td>Term</td><td>Grade</td><td>GPA</td><td>Hours</td></tr>`. The page also has
  personal data (national ID etc.); only these rows are read. 42 grades over 6 terms read correctly.
- Logout is idle-based (owner). Laravel-style session cookie.

Extension 0.3.0:
- Background: ping `/dashboard` every 2 min while logged in (keeps the session alive), full read every 10 min and
  when any SIS page is opened. Logged out = checks pause until a SIS page is opened again. Chrome sends the Lax
  session cookie on these requests (verified against a real local HTTPS server; Playwright route interception hides
  it, so don't trust routed tests for cookies).
- Nothing is changed on SIS pages (owner asked: no highlights, no button). The page script only says "logged in now".
- Grades tab (for everyone): table of current subjects (Midterm/Activities/Practical/Final), recent changes, past
  terms, plus Moodle marks for the owner. "Seen" state is per browser.
- Owner only: GitHub key + data passphrase under ⚙ → writes `sis.enc` v2 (pages "marks"/"finals", rows
  `[subject, label, value, url]`); the bot sends "Midterm released: CSE… — …" messages. Logged-out/stale warnings
  are off unless `settings.sisWarnings` is true in config.
- Tests: `tests/fixtures/sis/` (fake pages, real markup), `test_sis_v2_messages_in_plain_words`.

## Where we stopped (2026-11-15, 08:17 Cairo) — start here tomorrow

Live now (main): bot with files-as-documents, extension codes/feeds, extension 0.3.1 (SIS marks read in the
background, Grades tab, nothing changed on SIS pages). Omar installed 0.3.1; the Grades tab said
"SIS marks read just now", so reading works in his real Chrome. He does NOT want SIS marks on Telegram for now
(owner keys section left empty).

To do, in order:
1. **Friends choose subjects in Telegram** — code is on branch `wip-telegram-subjects` (not merged, not live).
   Done there: /subjects picker (inline buttons ✅/⬜, owner-followed subjects + the friend's own), sent after a
   friend connects; taps are collected per run into a set (repeated taps = one tap), applied once, one reply with
   "Now following / Stopped following" lists, keyboard updated, owner told "X changed their subjects", config.enc
   updated (panel shows it), st.sub updated so no extra "Now following" message; setMyCommands menu.
   Still needed: tests (fake Telegram send must return message_id; edit_markup/answer_cb/set_commands fakes),
   panel: on a 409 save conflict reload the config and ask to redo the change instead of overwriting a friend's
   Telegram change; live check via a test person; Omar's rules: the bot must tell them the ~2-minute wait before
   they tap (PICK_NOTE does), reply only once, several subjects in one message.
2. **Update the friends' install guide** (install.html, English + Arabic): add the SIS part (log in to the SIS in
   Chrome, Grades tab, marks table, nothing changes on SIS pages), the Telegram part (invite link → Start →
   /subjects, wait ~2 min), and safe updating (replace files in the SAME folder and press ↻; never Remove, or the
   code has to be entered again; two cards = new folder was loaded separately). Omar wants to send it to a friend.
3. **Floating button on SIS pages**: Omar noticed it disappeared in 0.3.1 and called it broken. It was removed
   together with the highlights after he said he didn't want things on the SIS pages. Ask: bring back just the
   🎓 button (opens the marks table), or keep pages untouched.
4. **New idea: advisor replies.** The extension should notice when the advisor sends/replies something on the SIS
   (no notifications exist today). Candidate places to look first (seen in the SIS menu): My Advisor
   (/dashboard/my_advisor), Notifications (/notifications?user=…, bell count), Suggestions and Complaints
   (/tickets), My Requests (/my_requests), the "discuss" counter (/study/studies/discuss). Look at them live
   with Omar logged in (read-only), then ask what counts as "the advisor replied".

Lessons from today:
- Playwright route interception drops cookies on extension service-worker requests; test cookies against a real
  local HTTPS server (`--host-resolver-rules`), where Chrome does send the SIS Lax session cookie.
- Commit author must not be Omar's Gmail (blocked); use OMAR6972@users.noreply.github.com.
- Updating an unpacked extension: replace files in the same folder + ↻ keeps the code; Remove wipes it.
