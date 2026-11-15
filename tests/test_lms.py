import json
from datetime import datetime, timezone

import pytest

from lms import vault
from lms.discord import DiscordError, valid_webhook
from lms.engine import Engine
from lms.moodle import LoginError, MoodleError
from lms.telegram import TgError
from lms.util import chunk_blocks, fmt_delta, fmt_ts, html_to_md, split_course

NOW = 1_800_000_000
OWNER_CHAT = "42"
KEY = "test-passphrase"


def ts(y, mo, d, h, mi):  # Cairo is UTC+2 in November
    return int(datetime(y, mo, d, h - 2, mi, tzinfo=timezone.utc).timestamp())


class FakeTelegram:
    def __init__(self):
        self.chat_id = OWNER_CHAT
        self.sent, self.queue, self.fail_for, self.docs = [], [], set(), []

    def send(self, text, markup=None, chat_id=None):
        chat = str(chat_id or self.chat_id)
        if chat in self.fail_for:
            raise TgError("boom")
        self.sent.append((chat, text))

    def send_document(self, filename, data, caption="", chat_id=None):
        chat = str(chat_id or self.chat_id)
        if chat in self.fail_for:
            raise TgError("boom")
        self.docs.append((chat, filename, data, caption))

    def get_me(self):
        return {"username": "lms_test_bot"}

    def get_updates(self, offset):
        return [u for u in self.queue if u["update_id"] >= offset]

    def texts(self, chat=None):
        return "\n".join(t for c, t in self.sent if chat is None or c == str(chat))


class FakeDiscord:
    def __init__(self):
        self.sent, self.fail, self.files = [], set(), []

    def send_file(self, url, filename, data, text=""):
        if url in self.fail:
            raise DiscordError("HTTP 500")
        self.files.append((url, filename, data, text))

    def send(self, url, markdown):
        if url in self.fail:
            raise DiscordError("HTTP 500")
        self.sent.append((url, markdown))

    def texts(self, url):
        return "\n".join(m for u, m in self.sent if u == url)


HOOK_A = "https://discord.com/api/webhooks/111111111/aaaa-AAAA_1"
HOOK_B = "https://discord.com/api/webhooks/222222222/bbbb-BBBB_2"


class FakeMoodle:
    base = "https://lms.test"

    def __init__(self):
        self.token, self.logins, self.valid = None, 0, "tok"
        self.userid, self.grades, self.fail_grades = 7, None, False
        self.courses = [
            {"id": 1, "fullname": "CSE333s (UG2023) - Data Structures and Algorithms (40954)", "lastaccess": NOW - 86400},
            {"id": 2, "fullname": "CSE334s (UG2023) - Database Systems (40955)", "lastaccess": NOW - 400 * 86400},
        ]
        self.contents = {1: [{"name": "Week 1", "modules": [
            {"id": 11, "modname": "folder", "name": "Lectures", "url": "https://lms.test/mod/folder/view.php?id=11",
             "description": "", "contents": [{"type": "file", "filename": "lec1.pdf", "filepath": "/", "filesize": 2048, "timemodified": 100}]},
            {"id": 12, "modname": "assign", "name": "Assignment 1", "url": "https://lms.test/mod/assign/view.php?id=12", "description": ""},
        ]}], 2: [{"name": "General", "modules": [
            {"id": 21, "modname": "resource", "name": "Syllabus", "url": "https://lms.test/mod/resource/view.php?id=21",
             "description": "", "contents": []}]}]}
        self.assigns = {1: [{"id": 5, "cmid": 12, "name": "Assignment 1", "duedate": ts(2026, 11, 20, 23, 59),
                             "allowsubmissionsfromdate": 0, "cutoffdate": 0, "intro": "<p>Do it</p>"}], 2: []}
        self.quizzes, self.discs, self.fail_contents = [], {1: [], 2: []}, set()
        self.blobs, self.downloads, self.fail_download = {}, [], False

    def download(self, url, max_bytes):
        self.downloads.append(url)
        if self.fail_download:
            raise MoodleError("Moodle refused the file download")
        return self.blobs.get(url, b"%PDF-1.4 fake " + url.encode())

    def login(self):
        self.logins += 1
        self.token = self.valid

    def enrolled(self):
        if self.token != self.valid:
            raise LoginError("invalidtoken")
        return self.courses

    def call(self, fn, **p):
        cids = [v for k, v in p.items() if k.startswith("courseids[")]
        if fn == "gradereport_user_get_grade_items":
            if self.grades is None or self.fail_grades:
                raise MoodleError("grades: boom")
            return {"usergrades": [{"gradeitems": self.grades.get(p["courseid"], [])}]}
        if fn == "core_course_get_contents":
            if p["courseid"] in self.fail_contents:
                raise MoodleError("core_course_get_contents: boom")
            return self.contents[p["courseid"]]
        if fn == "mod_assign_get_assignments":
            return {"courses": [{"id": c, "assignments": self.assigns.get(c, [])} for c in cids], "warnings": []}
        if fn == "mod_quiz_get_quizzes_by_courses":
            return {"quizzes": [q for q in self.quizzes if q["course"] in cids], "warnings": []}
        if fn == "mod_forum_get_forums_by_courses":
            return [{"id": 100 + c, "course": c, "type": "news", "name": "Announcements"} for c in cids]
        if fn == "mod_forum_get_forum_discussions":
            return {"discussions": self.discs.get(p["forumid"] - 100, [])}
        raise AssertionError(fn)


def run(tmp_path, m, tg, now=NOW, dc=None):
    e = Engine(m, tg, root=str(tmp_path), key=KEY, now=now, log=lambda *_: None, dc=dc or FakeDiscord())
    try:
        e.run()
    finally:
        e.save()
    return e


def cfg(tmp_path):
    return vault.load(str(tmp_path / "config.enc"), KEY)[0]


def set_cfg(tmp_path, obj):
    (tmp_path / "config.enc").write_text(vault.encrypt(obj, KEY))


def state(tmp_path):
    return vault.load(str(tmp_path / "state.enc"), KEY)[0]


def friend(courses, active=True):
    return {"id": "f1", "name": "Yousef", "active": active, "invite": "abc123", "courses": courses}


def test_helpers():
    assert split_course("CSE333s (UG2023) - Data Structures and Algorithms (40954)") == ("CSE333s", "Data Structures and Algorithms")
    assert split_course("EPM211s (UG2023) - Electric Circuits (1) (34864)") == ("EPM211s", "Electric Circuits (1)")
    assert fmt_ts(ts(2026, 11, 20, 23, 59)) == "Fri 20 Nov 2026, 11:59 PM"
    assert fmt_delta(3 * 86400 + 5 * 3600) == "3 days 5 h"
    assert all(len(c) <= 3800 for c in chunk_blocks("H", ["x" * 1000] * 10))


def test_vault_roundtrip_and_wrong_key(tmp_path):
    t = vault.encrypt({"a": 1}, "k1")
    assert vault.decrypt(t, "k1") == {"a": 1}
    with pytest.raises(vault.VaultError):
        vault.decrypt(t, "k2")
    run(tmp_path, FakeMoodle(), FakeTelegram())
    with pytest.raises(vault.VaultError):
        Engine(FakeMoodle(), FakeTelegram(), root=str(tmp_path), key="wrong")


def test_first_run_bootstraps_encrypted_files_silently(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    c = cfg(tmp_path)
    assert c["people"][0]["owner"] and c["people"][0]["courses"] == [1]
    raw = (tmp_path / "config.enc").read_text() + (tmp_path / "state.enc").read_text()
    assert "CSE333s" not in raw and "Assignment" not in raw and "tok" not in raw  # nothing readable on disk
    assert state(tmp_path)["bot"] == "lms_test_bot"
    txt = tg.texts(OWNER_CHAT)
    assert "LMS Guardian is live" in txt and "Now following" in txt and "• CSE333s — Data Structures and Algorithms" in txt
    assert "New file" not in txt


def test_no_commit_churn_when_nothing_changes(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)  # settle (sub bookkeeping)
    before = ((tmp_path / "config.enc").read_bytes(), (tmp_path / "state.enc").read_bytes())
    run(tmp_path, m, tg)
    assert before == ((tmp_path / "config.enc").read_bytes(), (tmp_path / "state.enc").read_bytes())


def test_token_is_reused_and_refreshed(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)
    assert m.logins == 1  # second run reused the saved token
    m2 = FakeMoodle()
    m2.valid = "tok2"  # the server rotated the token: the saved one is rejected
    run(tmp_path, m2, tg)
    assert m2.logins == 1 and state(tmp_path)["token"] == "tok2"


def test_detects_changes_once(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)
    tg.sent.clear()
    m.assigns[1][0]["duedate"] = ts(2026, 11, 17, 23, 59)
    m.contents[1][0]["modules"][0]["contents"].append(
        {"type": "file", "filename": "lec2.pdf", "filepath": "/", "filesize": 4096, "timemodified": 200})
    m.contents[1][0]["modules"][0]["contents"][0]["timemodified"] = 300
    m.quizzes.append({"id": 9, "course": 1, "coursemodule": 99, "name": "Quiz 1", "timeopen": ts(2026, 11, 25, 10, 0),
                      "timeclose": ts(2026, 11, 25, 11, 0), "timelimit": 1800, "intro": ""})
    m.discs[1].append({"discussion": 7, "subject": "Section moved", "message": "<p>Room B3</p>", "created": NOW})
    run(tmp_path, m, tg)
    txt = tg.texts(OWNER_CHAT)
    assert "Fri 20 Nov 2026, 11:59 PM → Tue 17 Nov 2026, 11:59 PM" in txt and "3 days earlier" in txt
    assert "New file: lec2.pdf" in txt and "File replaced/updated: lec1.pdf" in txt
    assert "New quiz" in txt and "30 min" in txt and "New announcement" in txt and "Room B3" in txt
    tg.sent.clear()
    run(tmp_path, m, tg)
    assert tg.sent == []


def test_failed_fetch_never_looks_like_deletion(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)
    tg.sent.clear()
    m.fail_contents = {1}
    run(tmp_path, m, tg)
    m.fail_contents = set()
    run(tmp_path, m, tg)
    assert tg.sent == []


def test_removed_items_reported(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)
    tg.sent.clear()
    m.contents[1][0]["modules"].pop(0)
    m.assigns[1] = []
    run(tmp_path, m, tg)
    assert "Removed folder" in tg.texts() and "Assignment removed" in tg.texts()


def test_owner_telegram_failure_retries_next_run(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    run(tmp_path, m, tg)
    tg.sent.clear()
    m.assigns[1][0]["duedate"] += 3600
    tg.fail_for = {OWNER_CHAT}
    run(tmp_path, m, tg)
    tg.fail_for = set()
    run(tmp_path, m, tg)
    assert "Assignment changed" in tg.texts()


def test_people_invites_and_per_person_subjects(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    c = cfg(tmp_path)
    c["people"][0]["courses"] = [1, 2]
    c["people"].append(friend([2]))  # the panel saved a friend who follows only course 2
    set_cfg(tmp_path, c)
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 777}, "text": "/start abc123"}}]
    tg.sent.clear()
    run(tmp_path, m, tg)
    assert state(tmp_path)["chats"]["f1"] == "777"
    assert "Connected, Yousef" in tg.texts(777) and "just connected" in tg.texts(OWNER_CHAT)
    assert "Now following" in tg.texts(777) and "• CSE334s — Database Systems" in tg.texts(777)
    run(tmp_path, m, tg)
    tg.sent.clear()
    m.assigns[1][0]["duedate"] += 3600           # course 1 change: owner only
    m.contents[2][0]["modules"][0]["name"] = "Syllabus v2"   # course 2 change: owner and friend
    run(tmp_path, m, tg)
    assert "Assignment changed" in tg.texts(OWNER_CHAT) and "Syllabus v2" in tg.texts(OWNER_CHAT)
    assert "Syllabus v2" in tg.texts(777) and "Assignment" not in tg.texts(777)


def test_inactive_person_gets_nothing_and_untracked_course_is_dropped(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    c = cfg(tmp_path)
    c["people"][0]["courses"] = [1, 2]
    c["people"].append(friend([1, 2], active=False))
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg)
    assert set(state(tmp_path)["courses"]) == {"1", "2"}
    c["people"][0]["courses"] = [1]
    c["people"] = c["people"][:1]
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg)
    assert set(state(tmp_path)["courses"]) == {"1"}


def test_bad_invite_and_strangers(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    tg.sent.clear()
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 999}, "text": "/start nope"}},
                {"update_id": 2, "message": {"chat": {"id": 999}, "text": "/upcoming"}},
                {"update_id": 3, "message": {"chat": {"id": 999}, "text": "hello"}}]
    run(tmp_path, m, tg)
    assert "isn't valid" in tg.texts(999) and tg.texts(999).count("\n") == 0  # one polite reply, nothing else
    assert state(tmp_path)["chats"] == {"me": OWNER_CHAT}


def test_commands(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    n = ts(2026, 11, 10, 12, 0)
    run(tmp_path, m, tg, now=n)
    tg.sent.clear()
    tg.queue = [{"update_id": i, "message": {"chat": {"id": 42}, "text": c}}
                for i, c in enumerate(["/status", "/upcoming", "/history", "/courses", "/start"], 1)]
    run(tmp_path, m, tg, now=n)
    txt = tg.texts(OWNER_CHAT)
    assert "Following 1 subject" in txt and "Assignment 1" in txt and "in 10 days" in txt
    assert "No changes detected yet" in txt and "CSE333s" in txt and "/upcoming" in txt


def test_outage_warning_and_recovery(tmp_path):
    class Down(FakeMoodle):
        valid_after = None

        def __init__(self):
            super().__init__()
            self.valid = "never"  # saved token is rejected and a fresh login fails

        def login(self):
            raise LoginError("Invalid login")
    tg = FakeTelegram()
    run(tmp_path, FakeMoodle(), tg)
    run(tmp_path, FakeMoodle(), tg)
    tg.sent.clear()
    for _ in range(3):
        d = Down()
        run(tmp_path, d, tg)
    assert "Monitoring is interrupted" in tg.texts() and "Invalid login" in tg.texts()
    run(tmp_path, Down(), tg)
    assert tg.texts().count("interrupted") == 1
    tg.sent.clear()
    run(tmp_path, FakeMoodle(), tg)
    assert "working again" in tg.texts()


def test_moodle_client_is_read_only():
    from lms.moodle import Moodle
    m = Moodle("https://x", "u", "p", post=lambda *a, **k: (200, "{}"))
    with pytest.raises(MoodleError):
        m.call("mod_assign_save_submission")


def test_html_to_md_and_webhook_validation():
    assert html_to_md('<b>A_B *x*</b> <a href="https://l.test/v?id=1&amp;x=2">Open</a>') == "**A\\_B \\*x\\***" + " [Open](https://l.test/v?id=1&x=2)"
    assert valid_webhook(HOOK_A)
    for bad in ("", "http://discord.com/api/webhooks/1/a", "https://evil.com/api/webhooks/1/a",
                "https://discord.com.evil.com/api/webhooks/1/a", "https://discord.com/api/webhooks/1/a/extra",
                "https://discord.com/api/webhooks/abc/a"):
        assert not valid_webhook(bad)


def test_discord_channels_follow_their_own_subjects(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"][0]["courses"] = [1, 2]
    c["people"] += [
        {"id": "dA", "name": "Class server", "active": True, "discord": HOOK_A, "courses": [1]},
        {"id": "dB", "name": "Study group", "active": True, "discord": HOOK_B, "courses": [1, 2]},
        {"id": "dC", "name": "Unfinished", "active": True, "discord": "not-a-link", "courses": [1]},
    ]
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg, dc=dc)
    assert "Now following" in dc.texts(HOOK_A) and "• CSE333s — Data Structures and Algorithms" in dc.texts(HOOK_A)
    assert "CSE334s — Database Systems" in dc.texts(HOOK_B) and "CSE333s" in dc.texts(HOOK_B)
    run(tmp_path, m, tg, dc=dc)
    dc.sent.clear()
    m.assigns[1][0]["duedate"] += 3600
    m.contents[2][0]["modules"][0]["name"] = "Syllabus v2"
    run(tmp_path, m, tg, dc=dc)
    a, b = dc.texts(HOOK_A), dc.texts(HOOK_B)
    assert "**CSE333s — Data Structures and Algorithms**" in a and "Assignment changed" in a
    assert "[Open in Moodle](https://lms.test/mod/assign/view.php?id=12)" in a
    assert "Syllabus v2" not in a and "Syllabus v2" in b and "Assignment changed" in b
    assert all(u in (HOOK_A, HOOK_B) for u, _ in dc.sent)  # the invalid link was never contacted
    assert "Syllabus v2" in tg.texts(OWNER_CHAT)


def test_discord_failure_does_not_block_owner_or_crash(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1]})
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg, dc=dc)
    run(tmp_path, m, tg, dc=dc)
    tg.sent.clear()
    dc.fail = {HOOK_A}
    m.assigns[1][0]["duedate"] += 3600
    run(tmp_path, m, tg, dc=dc)
    assert "Assignment changed" in tg.texts(OWNER_CHAT)
    tg.sent.clear()
    run(tmp_path, m, tg, dc=dc)
    assert tg.sent == []  # owner already notified; no duplicates


def put_sis(tmp_path, obj):
    (tmp_path / "sis.enc").write_text(vault.encrypt(obj, KEY))


def test_watch_switches_filter_per_recipient(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"][0]["watch"] = {"edits": False}
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1],
                        "watch": {"assignments": False, "materials": False}})
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg, dc=dc)
    run(tmp_path, m, tg, dc=dc)
    tg.sent.clear(); dc.sent.clear()
    m.assigns[1][0]["duedate"] += 3600                       # assignments
    m.contents[1][0]["modules"][0]["contents"][0]["timemodified"] = 999   # edits (file replaced)
    run(tmp_path, m, tg, dc=dc)
    assert "Assignment changed" in tg.texts(OWNER_CHAT) and "replaced" not in tg.texts(OWNER_CHAT)
    assert "replaced" in dc.texts(HOOK_A) and "Assignment changed" not in dc.texts(HOOK_A)
    h = state(tmp_path)["history"]
    assert {x["cat"] for x in h} == {"assignments", "edits"} and all("url" in x for x in h)
    tg.sent.clear(); dc.sent.clear()
    run(tmp_path, m, tg, dc=dc)
    assert tg.sent == [] and dc.sent == []


def test_moodle_grades_owner_only_and_silent_baseline(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)                       # grades unavailable at first: nothing recorded
    c = cfg(tmp_path)
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1]})
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg, dc=dc)
    m.grades = {1: [{"id": 50, "itemname": "Midterm", "gradeformatted": "18.00", "grademax": 20},
                    {"id": 51, "itemname": "Quiz 1", "gradeformatted": "-", "grademax": 10}]}
    tg.sent.clear(); dc.sent.clear()
    run(tmp_path, m, tg, dc=dc)                       # first successful read = silent baseline
    assert tg.sent == [] and dc.sent == []
    m.grades[1][1]["gradeformatted"] = "9.00"
    m.grades[1][0]["gradeformatted"] = "19.00"
    run(tmp_path, m, tg, dc=dc)
    t = tg.texts(OWNER_CHAT)
    assert "New grade" in t and "Quiz 1" in t and "9.00 / 10" in t
    assert "Grade changed" in t and "18.00 / 20 → 19.00 / 20" in t
    assert dc.sent == []                              # grades never go to channels or friends
    tg.sent.clear()
    m.fail_grades = True
    run(tmp_path, m, tg, dc=dc)
    m.fail_grades = False
    run(tmp_path, m, tg, dc=dc)
    assert tg.sent == []                              # a failed read is not a removal or a change


def test_sis_intake(tmp_path):
    m, tg = FakeMoodle(), FakeTelegram()
    run(tmp_path, m, tg)
    tg.sent.clear()
    page = {"title": "Grades", "url": "https://eng.asu.edu.eg/x", "rows": {"t0|CSE333": ["CSE333", "Midterm", ""]}}
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "ok", "pages": {"g": page}})
    run(tmp_path, m, tg)
    assert "SIS connected" in tg.texts() and "CSE333" not in tg.texts()
    tg.sent.clear()
    run(tmp_path, m, tg)
    assert tg.sent == []
    page["rows"]["t0|CSE333"] = ["CSE333", "Midterm", "17"]
    page["rows"]["t0|CSE334"] = ["CSE334", "Midterm", "15"]
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "ok", "pages": {"g": page}})
    run(tmp_path, m, tg)
    t = tg.texts(OWNER_CHAT)
    assert "<b>SIS grades</b>" in t and "SIS entry changed" in t and "Now: CSE333 · Midterm · 17" in t and "New SIS entry" in t
    tg.sent.clear()
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "ok", "pages": {"g": {"title": "Grades", "rows": {}}}})
    run(tmp_path, m, tg)                              # page read empty: ignored
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "ok", "pages": {"g": page}})
    run(tmp_path, m, tg)
    assert tg.sent == []
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "logged_out", "pages": {}})
    run(tmp_path, m, tg); run(tmp_path, m, tg, now=NOW + 13 * 3600)
    assert tg.sent == []                              # logged out / silent is normal: no warnings by default
    c = cfg(tmp_path); c["settings"] = {"sisWarnings": True}; set_cfg(tmp_path, c)
    run(tmp_path, m, tg); run(tmp_path, m, tg)
    assert tg.texts().count("not being checked") == 1 and "session ended" in tg.texts()
    tg.sent.clear()
    put_sis(tmp_path, {"v": 1, "seen": NOW, "status": "ok", "pages": {"g": page}})
    run(tmp_path, m, tg)
    assert "running again" in tg.texts()
    tg.sent.clear()
    run(tmp_path, m, tg, now=NOW + 13 * 3600)        # extension silent for 13 h
    assert "has not reported" in tg.texts()


def test_extension_feeds_are_per_person_and_private(tmp_path):
    from lms.engine import feed_id
    m, tg = FakeMoodle(), FakeTelegram()
    m.grades = {1: [{"id": 50, "itemname": "Midterm", "gradeformatted": "18.00", "grademax": 20}]}
    run(tmp_path, m, tg)
    c = cfg(tmp_path)
    own_code, fr_code = "o" * 16 + "wnerCODE", "f" * 16 + "riendCODE"
    c["people"][0].update(courses=[1, 2], ext=own_code)
    fr = friend([2]); fr["ext"] = fr_code; fr["watch"] = {"assignments": False}
    c["people"].append(fr)
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1], "ext": "x" * 20})
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg)
    m.assigns[1][0]["duedate"] += 3600
    m.contents[2][0]["modules"][0]["name"] = "Syllabus v2"
    run(tmp_path, m, tg)
    files = sorted(p.name for p in (tmp_path / "feeds").glob("*.enc"))
    assert files == sorted([feed_id(own_code) + ".enc", feed_id(fr_code) + ".enc"])   # Discord channels get none
    read = lambda code: vault.decrypt((tmp_path / "feeds" / (feed_id(code) + ".enc")).read_text(), code)
    with pytest.raises(vault.VaultError):
        vault.decrypt((tmp_path / "feeds" / (feed_id(fr_code) + ".enc")).read_text(), own_code)
    with pytest.raises(vault.VaultError):
        vault.decrypt((tmp_path / "feeds" / (feed_id(fr_code) + ".enc")).read_text(), KEY)
    o, f = read(own_code), read(fr_code)
    assert o["owner"] and not f["owner"]
    assert set(o["course_info"]) == {"1", "2"} and set(f["course_info"]) == {"2"}
    assert o["courses"]["1"]["grades"]["50"]["grade"] == "18.00"
    assert "grades" not in json.dumps(f["courses"]) and "assigns" not in json.dumps(f["courses"])
    assert any("Syllabus v2" in h["text"] for h in f["history"])
    assert all(h["cid"] == 2 for h in f["history"])                                   # nothing from course 1
    assert o["courses"]["1"]["assigns"]["5"]["due"] == m.assigns[1][0]["duedate"]
    # unchanged run: no rewrite (no commit churn)
    before = {p.name: p.read_text() for p in (tmp_path / "feeds").glob("*.enc")}
    run(tmp_path, m, tg)
    assert before == {p.name: p.read_text() for p in (tmp_path / "feeds").glob("*.enc")}
    # new code for the friend: old file disappears, old code stops working
    c = cfg(tmp_path); c["people"][1]["ext"] = "n" * 16 + "ewCODE"; set_cfg(tmp_path, c)
    run(tmp_path, m, tg)
    assert not (tmp_path / "feeds" / (feed_id(fr_code) + ".enc")).exists()
    assert read("n" * 16 + "ewCODE")["name"] == "Yousef"
    # paused person: feed removed
    c = cfg(tmp_path); c["people"][1]["active"] = False; set_cfg(tmp_path, c)
    run(tmp_path, m, tg)
    assert len(list((tmp_path / "feeds").glob("*.enc"))) == 1



def add_file(m, cid, name, size=2048, tm=300, mod=0):
    url = f"https://lms.test/webservice/pluginfile.php/9/mod_folder/content/0/{name}?forcedownload=1"
    m.contents[cid][0]["modules"][mod]["contents"].append(
        {"type": "file", "filename": name, "filepath": "/", "filesize": size, "timemodified": tm, "fileurl": url})
    return url


def test_files_are_sent_as_documents_to_everyone_following(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"].append(friend([1]))
    c["people"].append({"id": "f2", "name": "NoFiles", "active": True, "invite": "zz", "courses": [1], "watch": {"materials": False}})
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1]})
    set_cfg(tmp_path, c)
    tg.queue = [{"update_id": 1, "message": {"chat": {"id": 777}, "text": "/start abc123"}},
                {"update_id": 2, "message": {"chat": {"id": 888}, "text": "/start zz"}}]
    run(tmp_path, m, tg, dc=dc)
    tg.docs.clear(); dc.files.clear()
    u = add_file(m, 1, "محاضرة 2.pdf", size=900_000)
    run(tmp_path, m, tg, dc=dc)
    assert sorted(d[0] for d in tg.docs) == [OWNER_CHAT, "777"]                 # owner + friend, not the one who switched materials off
    assert all(d[1] == "محاضرة 2.pdf" and d[2].startswith(b"%PDF") for d in tg.docs)
    assert "Data Structures and Algorithms" in tg.docs[0][3] and "📁 Lectures" in tg.docs[0][3] and "محاضرة" not in tg.docs[0][3]
    assert [f[1] for f in dc.files] == ["محاضرة 2.pdf"]
    assert m.downloads == [u]                                                  # downloaded once, sent three times
    # replaced with a new version -> sent again (edits)
    tg.docs.clear(); dc.files.clear(); m.downloads.clear()
    m.contents[1][0]["modules"][0]["contents"][-1].update(filesize=950_000, timemodified=400)
    run(tmp_path, m, tg, dc=dc)
    assert len(tg.docs) == 2 and len(dc.files) == 1 and "File replaced/updated" in tg.texts(OWNER_CHAT)
    # quiet run: nothing re-sent
    tg.docs.clear(); dc.files.clear(); m.downloads.clear()
    run(tmp_path, m, tg, dc=dc)
    assert tg.docs == [] and dc.files == [] and m.downloads == []


def test_file_limits_failures_and_big_folders(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1]})
    set_cfg(tmp_path, c)
    run(tmp_path, m, tg, dc=dc)
    tg.sent.clear(); tg.docs.clear(); dc.files.clear(); dc.sent.clear()
    add_file(m, 1, "video.mp4", size=20 * 1024 * 1024)                       # fine for Telegram, too big for Discord
    add_file(m, 1, "huge.zip", size=80 * 1024 * 1024)                        # too big for both: never downloaded
    run(tmp_path, m, tg, dc=dc)
    assert [d[1] for d in tg.docs] == ["video.mp4"]
    assert "huge.zip" in tg.texts(OWNER_CHAT) and "too big to send on Telegram" in tg.texts(OWNER_CHAT)
    assert dc.files == [] and "too big to send on Discord" in dc.texts(HOOK_A) and "video.mp4" in dc.texts(HOOK_A)
    assert not any("huge.zip" in u for u in m.downloads)
    # download refused: a short note, the alert itself is not repeated next run
    tg.sent.clear(); tg.docs.clear()
    m.fail_download = True
    add_file(m, 1, "notes.pdf")
    run(tmp_path, m, tg, dc=dc)
    assert tg.docs == [] and "couldn't be downloaded" in tg.texts(OWNER_CHAT) and "notes.pdf" in tg.texts(OWNER_CHAT)
    tg.sent.clear(); m.fail_download = False
    run(tmp_path, m, tg, dc=dc)
    assert tg.sent == [] and tg.docs == []
    # a folder with 12 new files: first 10 + one note
    tg.sent.clear(); tg.docs.clear()
    for i in range(12):
        add_file(m, 1, f"sheet{i:02}.pdf")
    run(tmp_path, m, tg, dc=dc)
    assert len(tg.docs) == 10 and "2 more files" in tg.texts(OWNER_CHAT)
    # Telegram upload failure doesn't block the owner's alert or crash
    tg.sent.clear(); tg.docs.clear()
    real = tg.send_document
    tg.send_document = lambda *a, **k: (_ for _ in ()).throw(TgError("Bad Request: file too large"))
    add_file(m, 1, "late.pdf")
    e = run(tmp_path, m, tg, dc=dc)
    assert "late.pdf" in tg.texts(OWNER_CHAT)
    tg.send_document = real


def test_moodle_download_is_safe():
    from lms.moodle import Moodle
    from lms.util import TooBig
    seen = []
    mo = Moodle("https://lms.test", "u", "p"); mo.token = "SECRET"
    def get(url, mx):
        seen.append(url)
        return b"%PDF", "application/pdf"
    assert mo.download("https://lms.test/pluginfile.php/5/mod_resource/content/1/a%20b.pdf?forcedownload=1", 100, get) == b"%PDF"
    assert seen[-1] == "https://lms.test/webservice/pluginfile.php/5/mod_resource/content/1/a%20b.pdf?forcedownload=1&token=SECRET"
    mo.download("https://lms.test/webservice/pluginfile.php/5/x.pdf?token=old", 100, get)
    assert seen[-1].endswith("x.pdf?token=SECRET")
    for bad in ("https://evil.test/pluginfile.php/5/x.pdf", "https://lms.test/login/index.php", "https://lms.test.evil.com/pluginfile.php/1/x"):
        with pytest.raises(MoodleError):
            mo.download(bad, 100, get)
    with pytest.raises(MoodleError):   # token rejected: Moodle answers with an error page instead of the PDF
        mo.download("https://lms.test/webservice/pluginfile.php/5/x.pdf", 100, lambda u, mx: (b"<html>login</html>", "text/html"))
    with pytest.raises(MoodleError):
        mo.download("https://lms.test/webservice/pluginfile.php/5/x.pdf", 100, lambda u, mx: (b'{"error":"invalidtoken"}', "application/json"))


def test_multipart_upload_format_against_a_real_server():
    """Telegram and Discord both take multipart/form-data; check the bytes a strict parser sees."""
    import threading
    from email import message_from_bytes
    from email.policy import HTTP
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from lms import discord as dmod
    from lms.util import http_post_multipart, http_get_bytes, TooBig
    got = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            msg = message_from_bytes(b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body, policy=HTTP)
            got["parts"] = {p.get_param("name", header="content-disposition"): (p.get_filename(), p.get_payload(decode=True)) for p in msg.iter_parts()}
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true,"result":{}}')
        def do_GET(self):
            self.send_response(200); self.send_header("Content-Length", "5000"); self.end_headers(); self.wfile.write(b"x" * 5000)
        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_port}/"
    pdf = bytes(range(256)) * 40 + b"\r\n--boundary-like\r\n"
    status, _ = http_post_multipart(url, {"chat_id": "42", "caption": "📎 محاضرة \"1\"", "parse_mode": "HTML"}, [("document", 'ملف "2".pdf', pdf)])
    p = got["parts"]
    assert status == 200 and p["document"][1] == pdf and p["chat_id"][1] == b"42"
    assert p["caption"][1].decode() == '📎 محاضرة "1"'
    assert p["document"][0] in ('ملف "2".pdf', 'ملف \\"2\\".pdf')   # quote kept, escaped per RFC 7578
    # Discord's shape: payload_json + files[0]
    calls = []
    dmod.http_post_multipart = lambda u, f, files, headers=None: (calls.append((f, files)) or (200, "{}"))
    try:
        dmod.Discord(pause=0).send_file("https://discord.com/api/webhooks/1/abc", "a.pdf", b"PDF", "**hi** @everyone")
    finally:
        dmod.http_post_multipart = http_post_multipart
    f, files = calls[0]
    pj = json.loads(f["payload_json"])
    assert pj["allowed_mentions"] == {"parse": []} and pj["attachments"][0]["filename"] == "a.pdf" and files[0][0] == "files[0]"
    with pytest.raises(TooBig):
        http_get_bytes(url, 1000)
    assert http_get_bytes(url, 10000)[0] == b"x" * 5000
    srv.shutdown()



def test_sis_v2_messages_in_plain_words(tmp_path):
    m, tg, dc = FakeMoodle(), FakeTelegram(), FakeDiscord()
    run(tmp_path, m, tg, dc=dc)
    c = cfg(tmp_path)
    c["people"].append({"id": "dA", "name": "Server", "active": True, "discord": HOOK_A, "courses": [1]})
    set_cfg(tmp_path, c)
    u = "https://eng.asu.edu.eg/dashboard/courses/show/10302?committee_id=1"
    marks = {"title": "Subject marks", "kind": "marks", "url": "https://eng.asu.edu.eg/dashboard/my_courses", "rows": {
        "CSE336s|Midterm": ["CSE336s — Software Design Patterns", "Midterm", "- / 20", u],
        "CSE336s|Activities": ["CSE336s — Software Design Patterns", "Activities", "- / 30", u]}}
    finals = {"title": "Final grades", "kind": "finals", "url": "https://eng.asu.edu.eg/users/1/profile", "rows": {
        "CSE313s|Spring 2026": ["CSE313s — Computer Architecture", "Final grade", "A · GPA 4 · Spring 2026"]}}
    sis = lambda: put_sis(tmp_path, {"v": 2, "seen": NOW, "status": "ok", "pages": {"marks": marks, "finals": finals}})
    sis(); run(tmp_path, m, tg, dc=dc)
    assert "SIS connected" in tg.texts() and "CSE313s" not in tg.texts()        # silent baseline, old finals not announced
    tg.sent.clear(); dc.sent.clear()
    marks["rows"]["CSE336s|Midterm"][2] = "17 / 20"
    finals["rows"]["CSE472s|Fall 2026"] = ["CSE472s — Digital Image Processing", "Final grade", "A- · GPA 3.7 · Fall 2026"]
    marks["rows"]["CSE411s|Midterm"] = ["CSE411s — Real-Time Embedded Systems Design", "Midterm", "- / 20", u]  # new subject, nothing out
    sis(); run(tmp_path, m, tg, dc=dc)
    t = tg.texts(OWNER_CHAT)
    assert "Midterm released</b>: CSE336s — Software Design Patterns" in t and "17 / 20" in t
    assert "Final grade released</b>: CSE472s — Digital Image Processing" in t and "A- · GPA 3.7" in t
    assert "Open in SIS" in t and "Open in Moodle" not in t and "CSE411s" not in t and "Activities" not in t
    assert dc.sent == []                                                          # marks never go to channels
    tg.sent.clear()
    marks["rows"]["CSE336s|Midterm"][2] = "18 / 20"
    sis(); run(tmp_path, m, tg, dc=dc)
    assert "Midterm changed" in tg.texts() and "17 / 20 → 18 / 20" in tg.texts()
    tg.sent.clear()
    sis(); run(tmp_path, m, tg, dc=dc)
    assert tg.sent == []
