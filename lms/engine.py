"""One monitoring run: sync Telegram, crawl Moodle, diff, notify the right people/channels, persist.

Data lives in two ENCRYPTED files (see vault.py):
  config.enc  what the panel edits: recipients (Telegram people, Discord channels) and their subjects
  state.enc   what the bot remembers: snapshots, history, Telegram connections, Moodle token
A recipient with a "discord" key is a Discord channel (webhook link); otherwise it is a Telegram person.
"""
import os
import time

from . import diff, snapshot, vault
from .discord import Discord, DiscordError, valid_webhook
from .moodle import LoginError, MoodleError
from .telegram import TgError
from .util import NetError, chunk_blocks, esc, fmt_delta, fmt_ts, html_to_md, split_course

HISTORY_MAX = 200
RECENT_DAYS = 60  # first run only: pre-select subjects opened within this many days

HELP = (
    "<b>LMS Guardian</b>\n\n"
    "/courses – your subjects\n"
    "/upcoming – deadlines and quizzes coming up\n"
    "/history – latest detected changes\n"
    "/status – what the bot is watching\n\n"
    "Subjects are chosen in the panel."
)


def render_event(e):
    lines = [f"{e['emoji']} <b>{esc(e['kind'])}</b>: {esc(e['title'])}"]
    for l in e["lines"]:
        lines.append("   " + esc(l).replace("\n", "\n   "))
    if e["url"]:
        lines.append(f'   🔗 <a href="{esc(e["url"], quote=True)}">Open in Moodle</a>')
    return "\n".join(lines)


class Engine:
    def __init__(self, moodle, tg, root=".", key="", now=None, log=print, dc=None):
        self.m, self.tg, self.log, self.key = moodle, tg, log, key
        self.dc = dc or Discord()
        self.cfg_path = os.path.join(root, "config.enc")
        self.st_path = os.path.join(root, "state.enc")
        self.cfg, self._cfg_prev = vault.load(self.cfg_path, key, None)
        self.st, self._st_prev = vault.load(self.st_path, key, {})
        for k, v in (("courses", {}), ("course_info", {}), ("history", []), ("offset", 0),
                     ("chats", {}), ("sub", {}), ("token", ""), ("bot", ""), ("fail_streak", 0)):
            self.st.setdefault(k, v)
        self.now = now if now is not None else int(time.time())
        self.logged_in = False
        self.error = None
        self.recent = []
        self.crawl_failed_all = False

    # ---------- persistence ----------
    def save(self):
        self.st["history"] = self.st["history"][-HISTORY_MAX:]
        if self.cfg is not None:
            vault.save_if_changed(self.cfg_path, self.cfg, self.key, self._cfg_prev)
        vault.save_if_changed(self.st_path, self.st, self.key, self._st_prev)

    # ---------- recipients ----------
    def people(self):
        return (self.cfg or {}).get("people", [])

    def owner(self):
        return next((p for p in self.people() if p.get("owner")), None)

    def active_people(self):
        return [p for p in self.people() if p.get("active", True)]

    def mine(self, p):
        return {int(c) for c in p.get("courses", [])}

    def tracked(self):
        out = set()
        for p in self.active_people():
            out |= self.mine(p)
        return out

    @staticmethod
    def is_discord(p):
        return "discord" in p

    def connected(self, p):
        if self.is_discord(p):
            return valid_webhook(p.get("discord"))
        return bool(self.st["chats"].get(p["id"]))

    def person_for_chat(self, chat):
        for pid, c in self.st["chats"].items():
            if str(c) == str(chat):
                return next((p for p in self.people() if p["id"] == pid and not self.is_discord(p)), None)
        return None

    # ---------- naming ----------
    def full(self, cid):
        info = self.st["course_info"].get(str(cid))
        return f"{info['code']} — {info['name']}" if info else f"course {cid}"

    def bullets(self, cids):
        return "\n".join(f"• {esc(self.full(c))}" for c in cids)

    # ---------- sending ----------
    def deliver(self, p, html_text):
        """True = sent, False = failed, None = recipient not connected."""
        try:
            if self.is_discord(p):
                if not valid_webhook(p.get("discord")):
                    return None
                self.dc.send(p["discord"], html_to_md(html_text))
            else:
                chat = self.st["chats"].get(p["id"])
                if not chat:
                    return None
                self.tg.send(html_text, chat_id=chat)
            return True
        except (TgError, DiscordError) as e:
            self.log(f"send to {'discord' if self.is_discord(p) else 'telegram'} failed: {e}")
            return False

    def say_to(self, pid, html_text):
        p = next((p for p in self.people() if p["id"] == pid), None)
        return self.deliver(p, html_text) if p else None

    def reply(self, chat, text):
        try:
            self.tg.send(text, chat_id=chat)
        except TgError as e:
            self.log(f"telegram reply failed: {e}")

    # ---------- commands (Telegram only; Discord webhooks are one-way) ----------
    def handle_updates(self):
        try:
            updates = self.tg.get_updates(self.st["offset"])
        except TgError as e:
            self.log(f"getUpdates failed: {e}")
            return
        for u in updates:
            self.st["offset"] = max(self.st["offset"], u["update_id"] + 1)
            try:
                self.handle_one(u)
            except (TgError, KeyError, ValueError) as e:
                self.log(f"update {u.get('update_id')} not handled: {type(e).__name__}")

    def handle_one(self, u):
        msg = u.get("message")
        if not msg or "text" not in msg:
            return
        chat = str(msg["chat"]["id"])
        parts = msg["text"].strip().split()
        if not parts or not parts[0].startswith("/"):
            return
        cmd, args = parts[0].split("@")[0].lower(), parts[1:]
        if cmd == "/start" and args:
            p = next((p for p in self.people() if p.get("invite") == args[0] and not self.is_discord(p)), None)
            if not p:
                return self.reply(chat, "That invite link isn't valid any more. Ask for a new one.")
            self.st["chats"][p["id"]] = chat
            n = len(p.get("courses", []))
            self.reply(chat, f"✅ <b>Connected, {esc(p['name'])}.</b>\nYou follow {n} subject{'s' if n != 1 else ''}. Try /courses.")
            owner = self.owner()
            if owner and owner["id"] != p["id"]:
                self.say_to(owner["id"], f"👤 <b>{esc(p['name'])}</b> just connected.")
            return
        p = self.person_for_chat(chat)
        if not p:
            return self.reply(chat, "Ask for an invite link first.") if cmd == "/start" else None
        if cmd in ("/start", "/help"):
            self.reply(chat, HELP)
        elif cmd == "/courses":
            self.reply(chat, self.text_courses(p))
        elif cmd == "/status":
            self.reply(chat, self.text_status(p))
        elif cmd == "/upcoming":
            self.reply(chat, self.text_upcoming(p))
        elif cmd == "/history":
            self.reply(chat, self.text_history(p))

    def text_courses(self, p):
        cids = sorted(self.mine(p), key=lambda c: self.full(c))
        return "<b>Your subjects</b>\n\n" + (self.bullets(cids) if cids else "None selected yet (use the panel).")

    def text_status(self, p):
        h = [x for x in self.st["history"] if x.get("cid") in self.mine(p)]
        lines = ["<b>Status</b>: running ✅", "",
                 f"Following {len(self.mine(p))} subject{'s' if len(self.mine(p)) != 1 else ''}",
                 f"Last change: {esc(fmt_ts(h[-1]['t']))}" if h else "No changes detected yet"]
        if self.st.get("fail_streak"):
            lines.append(f"⚠️ {self.st['fail_streak']} failed checks in a row")
        return "\n".join(lines)

    def text_upcoming(self, p):
        items = []
        for cid in self.mine(p):
            snap = self.st["courses"].get(str(cid))
            if not snap:
                continue
            for a in snap["assigns"].values():
                if a["due"] > self.now:
                    items.append((a["due"], "📝", a["name"], "Due", cid))
            for q in snap["quizzes"].values():
                if q["close"] > self.now:
                    items.append((q["close"], "❓", q["name"], "Closes", cid))
        items.sort()
        if not items:
            return "Nothing due soon in your subjects."
        blocks = [f"{icon} <b>{esc(name)}</b>\n   {esc(self.full(cid))}\n   {word} {esc(fmt_ts(ts))} · in {fmt_delta(ts - self.now)}"
                  for ts, icon, name, word, cid in items[:15]]
        return "<b>Upcoming</b>\n\n" + "\n\n".join(blocks)

    def text_history(self, p):
        h = [x for x in self.st["history"] if x.get("cid") in self.mine(p)][-10:]
        if not h:
            return "No changes detected yet."
        blocks = [f"<b>{esc(x['text'])}</b>\n   {esc(self.full(x['cid']))}\n   {esc(fmt_ts(x['t']))}" for x in reversed(h)]
        return "<b>Latest changes</b>\n\n" + "\n\n".join(blocks)

    # ---------- the run ----------
    def connect(self):
        """Reuse the saved token; log in only when it is missing or rejected."""
        if self.st.get("token"):
            self.m.token = self.st["token"]
            try:
                return self.refresh_courses()
            except LoginError:
                self.log("saved token rejected; logging in again")
        self.m.login()
        self.st["token"] = self.m.token
        self.refresh_courses()

    def refresh_courses(self):
        for c in self.m.enrolled():
            code, name = split_course(c.get("fullname", ""))
            self.st["course_info"][str(c["id"])] = {"code": code, "name": name}
            if c.get("lastaccess", 0) and self.now - c["lastaccess"] < RECENT_DAYS * 86400:
                self.recent.append(c["id"])

    def bootstrap_config(self):
        """No config yet: create one with the owner and the recently opened subjects."""
        self.cfg = {"people": [{"id": "me", "name": "Me", "owner": True, "active": True,
                                "courses": sorted(self.recent)}]}
        self.log(f"created first config with {len(self.recent)} subjects")

    def run(self):
        try:
            self.connect()
            self.logged_in = True
        except (LoginError, MoodleError, NetError) as e:
            self.error = f"{type(e).__name__}: {e}"
            self.log(f"moodle unavailable: {self.error}")
        first_config = self.cfg is None
        if first_config and self.logged_in:
            self.bootstrap_config()
        if not self.st["bot"]:
            try:
                self.st["bot"] = self.tg.get_me().get("username", "")
            except TgError:
                pass
        owner = self.owner()
        if owner and getattr(self.tg, "chat_id", None):
            self.st["chats"][owner["id"]] = str(self.tg.chat_id)
        if self.cfg is not None:
            self.handle_updates()
        if first_config and self.logged_in:
            n = len(self.mine(self.owner()))
            self.say_to("me", "✅ <b>LMS Guardian is live.</b>\n\n"
                        f"I picked {n} subject{'s' if n != 1 else ''} you opened recently and recorded "
                        "their current state silently, so you'll only get <i>new</i> changes from now on.\n\n"
                        "Open the panel to change subjects or add people and Discord channels.")
        if self.logged_in and self.cfg is not None:
            self.crawl()
        self.update_health()

    def crawl(self):
        on = [c for c in sorted(self.tracked()) if str(c) in self.st["course_info"]]
        for key in list(self.st["courses"]):
            if int(key) not in on:
                del self.st["courses"][key]  # nobody follows it any more; re-adding baselines silently
        snaps, failed = snapshot.build(self.m, on, self.st["courses"], self.log)
        self.crawl_failed_all = bool(on) and len(failed) == len(on)
        items = sum(len(s["modules"]) + len(s["assigns"]) + len(s["quizzes"]) for s in snaps.values())
        posts = sum(len(s["disc"]) for s in snaps.values())
        self.log(f"checked {len(snaps)}/{len(on)} subjects: {items} items, {posts} forum posts, {len(failed)} failed")
        for cid, new in snaps.items():
            key = str(cid)
            old = self.st["courses"].get(key)
            if old is None:
                self.st["courses"][key] = new
                continue
            events = diff.diff_course(old, new)
            if events and not self.notify(cid, events):
                continue  # keep the old snapshot so the change is retried next run
            self.st["courses"][key] = new
        self.announce_subscriptions()

    def announce_subscriptions(self):
        """Tell each recipient about subjects that just became theirs (silent baseline) and remember them."""
        for p in self.active_people():
            now_mine = {c for c in self.mine(p) if str(c) in self.st["courses"]}
            seen = set(self.st["sub"].get(p["id"], []))
            new = sorted(now_mine - seen, key=lambda c: self.full(c))
            if new and self.connected(p):
                ok = self.deliver(p, "📌 <b>Now following</b>\n\n" + self.bullets(new) +
                                  "\n\nYou'll get changes from now on.")
                if ok is False:
                    continue  # retry next run
            if self.connected(p) or not new:
                self.st["sub"][p["id"]] = sorted(now_mine)

    def notify(self, cid, events):
        header = f"<b>{esc(self.full(cid))}</b>"
        texts = chunk_blocks(header, [render_event(e) for e in events])
        recipients = [p for p in self.active_people() if cid in self.mine(p)]
        owner_ids = {p["id"] for p in recipients if p.get("owner")}
        results = {}
        for p in recipients:
            if self.connected(p) and cid in {int(c) for c in self.st["sub"].get(p["id"], [])}:
                results[p["id"]] = all([self.deliver(p, t) for t in texts])
        critical = [results[i] for i in (owner_ids or results) if i in results]
        ok = all(critical)
        if ok:
            code = self.st["course_info"][str(cid)]["code"]
            for e in events:
                self.st["history"].append({"t": self.now, "cid": cid, "course": code,
                                           "text": f"{e['kind']}: {e['title']}"})
        return ok

    def update_health(self):
        bad = (not self.logged_in) or self.crawl_failed_all
        owner = self.owner()
        if bad:
            self.st["fail_streak"] += 1
            if self.st["fail_streak"] >= 3 and not self.st.get("warned") and owner:
                reason = esc(self.error or "every subject failed to load")
                if self.say_to(owner["id"], f"⚠️ <b>Monitoring is interrupted</b>\n\n{self.st['fail_streak']} failed checks in a row.\n{reason}"):
                    self.st["warned"] = True
        else:
            if self.st.get("warned") and owner:
                self.say_to(owner["id"], "✅ <b>Monitoring is working again.</b>")
            self.st["fail_streak"] = 0
            self.st["warned"] = False
