"""One monitoring run: sync Telegram, crawl Moodle, diff, notify the right people/channels, persist.

Data lives in two ENCRYPTED files (see vault.py):
  config.enc  what the panel edits: recipients (Telegram people, Discord channels) and their subjects
  state.enc   what the bot remembers: snapshots, history, Telegram connections, Moodle token
A recipient with a "discord" key is a Discord channel (webhook link); otherwise it is a Telegram person.
"""
import hashlib
import os
import time

from . import diff, snapshot, vault
from .discord import Discord, DiscordError, valid_webhook
from .moodle import LoginError, Moodle, MoodleError
from .telegram import TgError
from .util import NetError, TooBig, chunk_blocks, esc, fmt_delta, fmt_size, fmt_ts, html_to_md, split_course

HISTORY_MAX = 600
OWNER_ONLY = ("grades", "sis")  # personal: never sent to friends or Discord channels
SIS_STALE_HOURS = 12
RECENT_DAYS = 60  # first run only: pre-select subjects opened within this many days
PICK_DAYS = 150   # a friend's own account: subjects opened within this many days are offered in /subjects
FEED_HISTORY = 300  # newest events kept in each person's extension feed
TG_FILE_MAX = 50 * 1024 * 1024       # Telegram bots can upload up to 50 MB
DC_FILE_MAX = 10 * 1024 * 1024 - 65536  # Discord webhooks without server boosts: 10 MB
FILES_PER_EVENT = 10                 # a folder with more new files gets the first 10 + a note


def feed_id(code):
    """File name of a person's extension feed. Derived from their code, so it reveals nothing about them."""
    return hashlib.sha256(("lms-guardian-feed:" + code).encode("utf-8")).hexdigest()[:24]

COMMANDS = [("subjects", "Choose which subjects you follow"), ("connect", "Use your own Moodle account"), ("courses", "Your subjects"),
            ("upcoming", "Deadlines coming up"), ("history", "Latest changes"), ("status", "What I'm watching")]
PICK_NOTE = ("⏳ <b>Changes aren't instant.</b> I apply taps at my next check, about every 2 minutes. "
             "Tap every subject you want to switch once, then wait: I'll reply <b>once</b> with all your changes.\n"
             "Tapping the same subject again before I reply still counts as one tap.")

HELP = (
    "<b>LMS Guardian</b>\n\n"
    "/subjects – choose which subjects you follow\n"
    "/connect – use your own Moodle account (if your subjects differ; also gives you your Moodle marks)\n"
    "/disconnect – go back to the shared subject list\n"
    "/courses – your subjects\n"
    "/upcoming – deadlines and quizzes coming up\n"
    "/history – latest detected changes\n"
    "/status – what the bot is watching\n\n"
    "Replies come at my next check, within about 2 minutes."
)


def render_event(e):
    """One message block. A line with a line break inside is a small titled block (bold title, blank line before it)."""
    lines = [f"{e['emoji']} <b>{esc(e['kind'])}</b>: {esc(e['title'])}"]
    blocks = False
    for l in e["lines"]:
        if "\n" in l:
            head, rest = l.split("\n", 1)
            blocks = True
            lines += ["", f"   <b>{esc(head)}</b>"] + ["      " + esc(r) for r in rest.split("\n")]
        else:
            lines.append("   " + esc(l))
    if e["url"]:
        where = "SIS" if e.get("cat") == "sis" else "Moodle"
        lines += ([""] if blocks else []) + [f'   🔗 <a href="{esc(e["url"], quote=True)}">Open in {where}</a>']
    return "\n".join(lines)


class Engine:
    def __init__(self, moodle, tg, root=".", key="", now=None, log=print, dc=None, selftest="", mk_moodle=None):
        self.m, self.tg, self.log, self.key = moodle, tg, log, key
        self._mk = mk_moodle
        self._cur = None  # the Moodle client of the friend being processed (their own token), else the owner's
        self.selftest = selftest
        self._dl = {}  # file url -> bytes or the exception, so each file is downloaded once per run
        self.dc = dc or Discord()
        self.root = root
        self.cfg_path = os.path.join(root, "config.enc")
        self.st_path = os.path.join(root, "state.enc")
        self.sis_path = os.path.join(root, "sis.enc")  # written by the browser extension, only read here
        self.cfg, self._cfg_prev = vault.load(self.cfg_path, key, None)
        self.st, self._st_prev = vault.load(self.st_path, key, {})
        for k, v in (("courses", {}), ("course_info", {}), ("history", []), ("offset", 0),
                     ("chats", {}), ("sub", {}), ("token", ""), ("bot", ""), ("fail_streak", 0), ("accts", {})):
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

    def wants(self, p, cat):
        """Does this recipient get this kind of event? Missing switch = on. Grades/SIS: owner only."""
        if cat == "sis" and not p.get("owner"):
            return False
        if cat == "grades" and not (p.get("owner") or self.acct(p)):
            return False  # Moodle marks: the owner's, or a person's OWN marks read with their own account
        return (p.get("watch") or {}).get(cat, True)

    def tracked(self):
        """Subjects read with the OWNER's Moodle login. People who connected their own account are read with their own."""
        out = set()
        for p in self.active_people():
            if not self.acct(p):
                out |= self.mine(p)
        return out

    # ---------- people who connected their own Moodle account (/connect) ----------
    def acct(self, p):
        return self.st["accts"].get(p["id"]) if p else None

    def store(self, p):
        """Where this person's subject snapshots live."""
        a = self.acct(p)
        return a["courses"] if a else self.st["courses"]

    def new_client(self, token):
        if self._mk:
            return self._mk(token)
        c = Moodle(self.m.base, "", "", post=self.m._post)
        c.token = token
        return c

    def refresh_acct(self, p, a, m, courses=None):
        """Read the subjects this person's own account is enrolled in. Raises LoginError if the token is dead."""
        courses = courses if courses is not None else m.enrolled()
        a["userid"] = m.userid
        info, pick, recent = {}, [], []
        for c in courses:
            code, name = split_course(c.get("fullname", ""))
            info[str(c["id"])] = {"code": code, "name": name}
            la = c.get("lastaccess", 0)
            if la and self.now - la < PICK_DAYS * 86400:
                pick.append(c["id"])
            if la and self.now - la < RECENT_DAYS * 86400:
                recent.append(c["id"])
        a["info"] = {k: v for k, v in info.items()}
        a["pick"] = sorted(pick)
        a["recent"] = sorted(recent)
        for k, v in info.items():
            self.st["course_info"].setdefault(k, v)  # so every message can name the subject
        return recent

    def connect_account(self, p, chat, msg_id, token):
        try:  # the token is a key to their account: remove it from the chat first, whatever happens next
            self.tg.delete(chat, msg_id)
        except (TgError, AttributeError):
            pass
        if p.get("owner"):
            return self.reply(chat, "You're the owner: the bot already reads Moodle with your own login.")
        m = self.new_client(token)
        a = {"token": token, "userid": None, "courses": {}, "info": {}, "pick": [], "recent": []}
        try:
            recent = self.refresh_acct(p, a, m)
        except (LoginError, MoodleError, NetError):
            return self.reply(chat, "❌ That token didn't work, so nothing was saved. Get a fresh one from the extension and send <code>/connect TOKEN</code> again.")
        self.st["accts"][p["id"]] = a
        p["courses"] = sorted(recent)  # start with the subjects you opened recently; change them with /subjects
        self.st["sub"][p["id"]] = []   # so the next run tells them what they now follow
        self.reply(chat, "✅ <b>Your own Moodle account is connected.</b>\n"
                   f"I deleted your message with the token. You follow {len(recent)} subject{'s' if len(recent) != 1 else ''} you opened recently, "
                   "read from <b>your</b> Moodle from now on, and you'll also get your own Moodle marks when they're posted. I'll tell you within about 2 minutes, then use /subjects to change them.")
        owner = self.owner()
        if owner and owner["id"] != p["id"]:
            self.say_to(owner["id"], f"👤 <b>{esc(p['name'])}</b> connected their own Moodle account.")

    def disconnect_account(self, p, chat):
        if not self.acct(p):
            return self.reply(chat, "You haven't connected your own account.")
        del self.st["accts"][p["id"]]
        owner = self.owner()
        shared = {int(c) for c in self.st.get("owner_enrolled", [])} if owner else set()
        p["courses"] = sorted(c for c in self.mine(p) if c in shared)  # the shared list can only serve what the owner has
        self.reply(chat, "Disconnected. I deleted your Moodle token. You're back on the shared subject list "
                   f"({len(p['courses'])} subject{'s' if len(p['courses']) != 1 else ''} in common). "
                   "To make Moodle forget the token too, see Profile → Preferences → Security keys.")

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
        if cid is None:
            return "SIS grades"
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
        picks = {}  # chat -> {"cids": set, "msg": message id, "cbs": [callback ids]}; many taps -> one reply
        for u in updates:
            self.st["offset"] = max(self.st["offset"], u["update_id"] + 1)
            try:
                cq = u.get("callback_query")
                if cq:
                    self.collect_pick(cq, picks)
                else:
                    self.handle_one(u)
            except (TgError, KeyError, ValueError, TypeError) as e:
                self.log(f"update {u.get('update_id')} not handled: {type(e).__name__}")
        for chat, pk in picks.items():
            try:
                self.apply_picks(chat, pk)
            except (TgError, KeyError, ValueError, TypeError) as e:
                self.log(f"subject picks not applied: {type(e).__name__}")
        if self.st.get("cmds") != len(COMMANDS):
            try:
                self.tg.set_commands(COMMANDS)
                self.st["cmds"] = len(COMMANDS)
            except (TgError, AttributeError):
                pass

    # ---------- choosing subjects from Telegram ----------
    def short(self, cid):
        t = self.full(cid)
        return t if len(t) <= 60 else t[:57] + "…"

    def pickable(self, p):
        """Owner: every subject Moodle lists. Others: the subjects the owner follows, plus their own."""
        a = self.acct(p)
        if a:
            ids = {int(c) for c in a["pick"]} | (self.mine(p) & {int(c) for c in a["info"]})
        elif p.get("owner"):
            ids = {int(c) for c in self.st.get("owner_enrolled") or self.st["course_info"]}
        else:
            o = self.owner()
            ids = (self.mine(o) if o else set()) | self.mine(p)
        return sorted((c for c in ids if str(c) in self.st["course_info"]), key=lambda c: self.full(c))

    def picker_markup(self, p):
        mine = self.mine(p)
        return {"inline_keyboard": [[{"text": ("✅ " if c in mine else "⬜ ") + self.short(c), "callback_data": f"t:{c}"}]
                                    for c in self.pickable(p)]}

    def send_picker(self, p, chat):
        if not self.pickable(p):
            return self.reply(chat, "There are no subjects to choose from yet.")
        text = ("📚 <b>Choose your subjects</b>\n\n✅ = you get alerts for it, ⬜ = you don't. "
                "Tap a subject to switch it on or off.\n\n" + PICK_NOTE)
        try:
            self.tg.send(text, markup=self.picker_markup(p), chat_id=chat)
        except TgError as e:
            self.log(f"telegram picker failed: {e}")

    @staticmethod
    def collect_pick(cq, picks):
        data = cq.get("data") or ""
        chat = str(cq["message"]["chat"]["id"])
        pk = picks.setdefault(chat, {"cids": set(), "msg": None, "cbs": []})
        pk["cbs"].append(cq["id"])
        pk["msg"] = cq["message"]["message_id"]
        if data.startswith("t:") and data[2:].isdigit():
            pk["cids"].add(int(data[2:]))  # a set: tapping the same subject 5 times is one tap

    def apply_picks(self, chat, pk):
        p = self.person_for_chat(chat)
        for cb in pk["cbs"]:
            try:
                self.tg.answer_cb(cb, "Saved ✓" if p else "")
            except TgError:
                pass  # taps older than a few seconds can't be answered any more; that's fine
        if not p or self.cfg is None:
            return
        allowed = set(self.pickable(p))
        mine = set(self.mine(p))
        added = sorted((c for c in pk["cids"] if c in allowed and c not in mine), key=self.full)
        removed = sorted((c for c in pk["cids"] if c in allowed and c in mine), key=self.full)
        if not added and not removed:
            return
        mine = (mine | set(added)) - set(removed)
        p["courses"] = sorted(mine)  # saved to config.enc at the end of the run: the panel shows it too
        self.st["sub"][p["id"]] = sorted(mine)  # this reply already tells them; no extra "Now following" later
        if pk["msg"]:
            try:
                self.tg.edit_markup(pk["msg"], self.picker_markup(p), chat_id=chat)
            except TgError:
                pass
        parts = ["✅ <b>Saved.</b>"]
        if added:
            parts.append("<b>Now following:</b>\n" + self.bullets(added))
        if removed:
            parts.append("<b>Stopped following:</b>\n" + self.bullets(removed))
        parts.append(f"You follow {len(mine)} subject{'s' if len(mine) != 1 else ''} now. /subjects to change again.")
        self.reply(chat, "\n\n".join(parts))
        owner = self.owner()
        if owner and owner["id"] != p["id"]:
            change = ", ".join([f"+{self.st['course_info'][str(c)]['code']}" for c in added] +
                               [f"−{self.st['course_info'][str(c)]['code']}" for c in removed])
            self.say_to(owner["id"], f"👤 <b>{esc(p['name'])}</b> changed their subjects in Telegram ({esc(change)}).")

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
            self.reply(chat, f"✅ <b>Connected, {esc(p['name'])}.</b>\nYou follow {n} subject{'s' if n != 1 else ''}.")
            self.send_picker(p, chat)
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
        elif cmd in ("/subjects", "/choose"):
            self.send_picker(p, chat)
        elif cmd == "/connect":
            if not args:
                self.reply(chat, "To use your own Moodle account, open the LMS Guardian extension in Chrome → <b>Connect my Moodle</b>, then send me <code>/connect TOKEN</code> with the token it shows. I'll delete your message right away.")
            else:
                self.connect_account(p, chat, msg["message_id"], args[0])
        elif cmd == "/disconnect":
            self.disconnect_account(p, chat)
        elif cmd == "/status":
            self.reply(chat, self.text_status(p))
        elif cmd == "/upcoming":
            self.reply(chat, self.text_upcoming(p))
        elif cmd == "/history":
            self.reply(chat, self.text_history(p))

    def my_history(self, p):
        mine = self.mine(p)
        return [x for x in self.st["history"]
                if (x.get("cid") in mine or (x.get("cid") is None and p.get("owner"))) and self.wants(p, x.get("cat", "materials"))]

    def text_courses(self, p):
        cids = sorted(self.mine(p), key=lambda c: self.full(c))
        return "<b>Your subjects</b>\n\n" + (self.bullets(cids) if cids else "None yet.") + "\n\nChange them with /subjects."

    def text_status(self, p):
        h = self.my_history(p)
        lines = ["<b>Status</b>: running ✅", "",
                 f"Following {len(self.mine(p))} subject{'s' if len(self.mine(p)) != 1 else ''}",
                 f"Last change: {esc(fmt_ts(h[-1]['t']))}" if h else "No changes detected yet"]
        if self.st.get("fail_streak"):
            lines.append(f"⚠️ {self.st['fail_streak']} failed checks in a row")
        return "\n".join(lines)

    def text_upcoming(self, p):
        items = []
        for cid in self.mine(p):
            snap = self.store(p).get(str(cid))
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
        h = self.my_history(p)[-10:]
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
        courses = self.m.enrolled()
        self.st["owner_enrolled"] = sorted(c["id"] for c in courses)
        for c in courses:
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
            if self.selftest == "files":
                self.selftest_files(os.environ.get("LMS_SELFTEST_CHANNEL", ""))
        if self.cfg is not None:
            self.crawl_accts()
            try:
                self.process_sis()
            except vault.VaultError:
                self.log("sis.enc could not be decrypted; ignoring it")
            self.write_feeds()
        self.update_health()

    def crawl(self):
        on = [c for c in sorted(self.tracked()) if str(c) in self.st["course_info"]]
        for key in list(self.st["courses"]):
            if int(key) not in on:
                del self.st["courses"][key]  # nobody follows it any more; re-adding baselines silently
        owner = self.owner()
        want_grades = bool(owner) and owner.get("active", True) and self.wants(owner, "grades")
        snaps, failed = snapshot.build(self.m, on, self.st["courses"], self.log, grades=want_grades)
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

    def crawl_accts(self):
        """People who connected their own Moodle account: read THEIR subjects with THEIR token, tell only them."""
        for p in self.active_people():
            a = self.acct(p)
            if not a or self.is_discord(p) or a.get("dead"):
                continue
            m = self.new_client(a["token"])
            m.userid = a.get("userid")
            try:
                self.refresh_acct(p, a, m)
            except LoginError:
                a["dead"] = True  # revoked or expired: stop knocking; they connect again when they like
                self.say_to(p["id"], "⚠️ <b>Your Moodle connection stopped working</b> (the token was revoked or expired). Send <code>/connect TOKEN</code> again to restart it.")
                continue
            except (MoodleError, NetError) as e:
                self.log(f"account of {p['id']}: moodle unavailable ({type(e).__name__})")
                continue
            on = [c for c in sorted(self.mine(p)) if str(c) in a["info"]]
            for key in list(a["courses"]):
                if int(key) not in on:
                    del a["courses"][key]
            snaps, failed = snapshot.build(m, on, a["courses"], self.log, grades=self.wants(p, "grades"))
            self.log(f"account {p['id']}: checked {len(snaps)}/{len(on)} subjects, {len(failed)} failed")
            self._cur = m
            try:
                for cid, new in snaps.items():
                    key = str(cid)
                    old = a["courses"].get(key)
                    if old is None:
                        a["courses"][key] = new
                        continue
                    events = diff.diff_course(old, new)
                    if events and not self.notify(cid, events, only=p):
                        continue  # retry next run
                    a["courses"][key] = new
            finally:
                self._cur = None
        self.announce_subscriptions()

    def announce_subscriptions(self):
        """Tell each recipient about subjects that just became theirs (silent baseline) and remember them."""
        for p in self.active_people():
            now_mine = {c for c in self.mine(p) if str(c) in self.store(p)}
            seen = set(self.st["sub"].get(p["id"], []))
            new = sorted(now_mine - seen, key=lambda c: self.full(c))
            if new and self.connected(p):
                ok = self.deliver(p, "📌 <b>Now following</b>\n\n" + self.bullets(new) +
                                  "\n\nYou'll get changes from now on.")
                if ok is False:
                    continue  # retry next run
            if self.connected(p) or not new:
                self.st["sub"][p["id"]] = sorted(now_mine)

    def notify(self, cid, events, only=None):
        """Send each recipient only the kinds of events they switched on. True = safe to remember the change.
        `only` = a person with their own Moodle account: just them, from their own crawl."""
        header = f"<b>{esc(self.full(cid))}</b>"
        if only is not None:
            recipients = [only] if cid in {int(c) for c in self.st["sub"].get(only["id"], [])} else []
        elif cid is None:
            recipients = [p for p in self.active_people() if p.get("owner")]
        else:
            recipients = [p for p in self.active_people() if cid in self.mine(p) and not self.acct(p)
                          and cid in {int(c) for c in self.st["sub"].get(p["id"], [])}]
        owner_ok, any_fail = None, False
        for p in recipients:
            mine = [e for e in events if self.wants(p, e.get("cat", "materials"))]
            if not mine or not self.connected(p):
                continue
            ok = all([self.deliver(p, t) for t in chunk_blocks(header, [render_event(e) for e in mine])])
            any_fail = any_fail or not ok
            if ok:
                self.send_files(p, cid, mine)
            if p.get("owner"):
                owner_ok = ok
        ok = owner_ok if owner_ok is not None else not any_fail
        if ok:
            code = "SIS" if cid is None else self.st["course_info"][str(cid)]["code"]
            for e in events:
                self.st["history"].append({"t": self.now, "cid": cid, "course": code, "cat": e.get("cat", "materials"),
                                           "text": f"{e['kind']}: {e['title']}", "url": e.get("url", "")})
        return ok

    # ---------- files as documents ----------
    def fetch(self, f, limit):
        if f["url"] not in self._dl:
            try:
                self._dl[f["url"]] = (self._cur or self.m).download(f["url"], TG_FILE_MAX)
            except (TooBig, MoodleError, NetError, LoginError) as e:
                self._dl[f["url"]] = e
                self.log(f"file download failed: {type(e).__name__}: {e}"[:200])
        got = self._dl[f["url"]]
        if isinstance(got, TooBig) or (isinstance(got, bytes) and len(got) > limit):
            raise TooBig()
        if isinstance(got, Exception):
            raise got
        return got

    def send_files(self, p, cid, events):
        """After the text alert: the files themselves. A failure here never blocks or repeats the alert."""
        if not self.wants(p, "materials"):
            return  # the files themselves follow the "New materials & files" switch
        discord = self.is_discord(p)
        limit = DC_FILE_MAX if discord else TG_FILE_MAX
        where = "Discord" if discord else "Telegram"
        for e in events:
            files = e.get("files") or []
            for f in files[:FILES_PER_EVENT]:
                caption = f"<b>{esc(self.full(cid))}</b>"
                stem = f["name"].rsplit(".", 1)[0]
                if e["title"] and e["title"] not in (f["name"], stem):  # Telegram already shows the file name
                    caption += f"\n📁 {esc(e['title'])}"
                try:
                    if f.get("size", 0) > limit:
                        raise TooBig()
                    data = self.fetch(f, limit)
                    if discord:
                        self.dc.send_file(p["discord"], f["name"], data, html_to_md(caption))
                    else:
                        self.tg.send_document(f["name"], data, caption, chat_id=self.st["chats"][p["id"]])
                except TooBig:
                    self.deliver(p, f"📎 <b>{esc(f['name'])}</b> ({esc(fmt_size(f.get('size', 0)))}) is too big to send on {where}. Open it in Moodle from the alert above.")
                except (MoodleError, NetError, LoginError):
                    self.deliver(p, f"📎 <b>{esc(f['name'])}</b> couldn't be downloaded from Moodle. Open it from the alert above.")
                except (TgError, DiscordError) as x:
                    self.log(f"file send to {where.lower()} failed: {x}"[:200])
            if len(files) > FILES_PER_EVENT:
                self.deliver(p, f"📁 {len(files) - FILES_PER_EVENT} more file{'s' if len(files) - FILES_PER_EVENT != 1 else ''} in <b>{esc(e['title'])}</b>. Open it in Moodle from the alert above.")

    def selftest_files(self, channel=""):
        """Manual test (Actions -> Run workflow -> self-test): send the newest file in your subjects to you only,
        or, when `channel` names a Discord channel in the panel, to that channel only."""
        owner = self.owner()
        best = None
        for cid in self.mine(owner) if owner else []:
            for mod in (self.st["courses"].get(str(cid)) or {}).get("modules", {}).values():
                for key, (size, tm) in mod["files"].items():
                    if (mod.get("furls") or {}).get(key) and (best is None or tm > best[0]):
                        best = (tm, cid, mod, key)
        if not best:
            return self.log("selftest: no file with a download link found in your subjects")
        tm, cid, mod, key = best
        f = {"name": key.rsplit("/", 1)[-1], "size": mod["files"][key][0], "url": mod["furls"][key]}
        e = {"title": mod["name"], "files": [f]}
        target = owner
        if channel:
            target = next((p for p in self.people() if self.is_discord(p) and p.get("name", "").strip().lower() == channel.strip().lower()), None)
            if not target:
                return self.log(f"selftest: no Discord channel named {channel!r} in the panel")
        self.deliver(target, f"🧪 <b>File test</b>\nSending the newest file in your subjects: {esc(f['name'])} ({esc(fmt_size(f['size']))}).")
        sent_before = len(self._dl)
        self.send_files(target, cid, [e])
        got = self._dl.get(f["url"])
        self.log(f"selftest: {f['name']!r} {fmt_size(f['size'])} downloaded={isinstance(got, bytes)}"
                 + (f" bytes={len(got)}" if isinstance(got, bytes) else f" error={type(got).__name__}") + f" new_downloads={len(self._dl) - sent_before}")

    # ---------- SIS (grades pushed by the browser extension) ----------
    def process_sis(self):
        sis, _ = vault.load(self.sis_path, self.key, None)
        owner = self.owner()
        if not sis or not owner or not owner.get("active", True) or not self.wants(owner, "sis"):
            return
        settings = self.cfg.get("settings") or {}
        stale_hours = settings.get("sisStaleHours") or SIS_STALE_HOURS
        logged_out = sis.get("status") == "logged_out"
        stale = self.now - int(sis.get("seen", 0)) > stale_hours * 3600
        # Logged out / silent is the normal state when Chrome is closed, so these warnings are opt-in.
        if not settings.get("sisWarnings"):
            pass
        elif logged_out or stale:
            if not self.st.get("sis_warned"):
                why = ("your SIS session ended. Log in to the SIS again and the extension resumes by itself."
                       if logged_out else
                       f"the extension has not reported for over {stale_hours} hours (browser closed, or SIS session ended).")
                if self.say_to(owner["id"], f"⚠️ <b>SIS grades are not being checked</b>\n\n{esc(why[0].upper() + why[1:])}"):
                    self.st["sis_warned"] = True
        elif self.st.get("sis_warned"):
            self.say_to(owner["id"], "✅ <b>SIS grade checks are running again.</b>")
            self.st["sis_warned"] = False
        if logged_out:
            return
        old = self.st.get("sis")
        pages = {}
        for key, page in (sis.get("pages") or {}).items():
            rows = page.get("rows") or {}
            if not rows and (old or {}).get(key, {}).get("rows"):
                continue  # a page that suddenly reads empty is a bad read, not "all grades deleted"
            pages[key] = {"title": page.get("title", ""), "url": page.get("url", ""), "rows": rows}
            if page.get("kind"):
                pages[key]["kind"] = page["kind"]
        if not pages:
            return
        if old is None:
            n = sum(len(p["rows"]) for p in pages.values())
            if self.say_to(owner["id"], f"🎓 <b>SIS connected.</b>\n\nRecorded your current marks ({n} entries) silently. You'll get a message when a mark is released or changes, while Chrome is open."):
                self.st["sis"] = pages
            return
        events = diff.diff_sis(old, pages)
        if events and not self.notify(None, events):
            return  # retry next run
        merged = dict(old)
        for key, page in pages.items():
            rows = dict((old.get(key) or {}).get("rows", {}))
            rows.update(page["rows"])  # rows that vanish are kept: a half-loaded page must not erase history
            merged[key] = {"title": page["title"], "url": page["url"], "rows": rows}
            if page.get("kind"):
                merged[key]["kind"] = page["kind"]
        self.st["sis"] = merged

    # ---------- browser extension feeds ----------
    def build_feed(self, p):
        """Only what this person may see: their subjects, their switches. Grades and SIS for the owner only."""
        owner = bool(p.get("owner"))
        info, courses = {}, {}
        for cid in sorted(self.mine(p)):
            key = str(cid)
            if key in self.st["course_info"]:
                info[key] = self.st["course_info"][key]
            snap = self.store(p).get(key)
            if not snap:
                continue
            c = {}
            if self.wants(p, "assignments"):
                c["assigns"] = {k: {"name": a["name"], "due": a["due"], "url": a.get("url", "")} for k, a in snap["assigns"].items()}
            if self.wants(p, "quizzes"):
                c["quizzes"] = {k: {"name": q["name"], "close": q["close"], "url": q.get("url", "")} for k, q in snap["quizzes"].items()}
            if self.wants(p, "grades") and snap.get("grades"):
                c["grades"] = snap["grades"]
            courses[key] = c
        feed = {"v": 1, "name": p.get("name", ""), "owner": owner, "grades_on": self.wants(p, "grades"), "course_info": info, "courses": courses,
                "history": self.my_history(p)[-FEED_HISTORY:]}
        if owner and self.wants(p, "sis") and self.st.get("sis"):
            feed["sis"] = self.st["sis"]
        return feed

    def write_feeds(self):
        """One encrypted file per person with an extension code (feeds/<id>.enc). Written only when it changes."""
        folder = os.path.join(self.root, "feeds")
        want = {feed_id(p["ext"]): p for p in self.active_people()
                if not self.is_discord(p) and isinstance(p.get("ext"), str) and len(p["ext"]) >= 16}
        known = self.st.setdefault("feeds", {})
        if want:
            os.makedirs(folder, exist_ok=True)
        for fid, p in want.items():
            feed = self.build_feed(p)
            digest = hashlib.sha256(vault.canonical(feed).encode("utf-8")).hexdigest()
            path = os.path.join(folder, fid + ".enc")
            if known.get(fid) != digest or not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write(vault.encrypt(feed, p["ext"]) + "\n")
                known[fid] = digest
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                if name.endswith(".enc") and name[:-4] not in want:
                    os.remove(os.path.join(folder, name))  # person removed, paused, or given a new code
        for fid in list(known):
            if fid not in want:
                del known[fid]

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
