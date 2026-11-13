import json
from datetime import datetime, timezone

import pytest

from lms import vault
from lms.engine import Engine
from lms.moodle import LoginError, MoodleError
from lms.telegram import TgError
from lms.util import chunk_blocks, fmt_delta, fmt_ts, split_course

NOW = 1_800_000_000
OWNER_CHAT = "42"
KEY = "test-passphrase"


def ts(y, mo, d, h, mi):  # Cairo is UTC+2 in November
    return int(datetime(y, mo, d, h - 2, mi, tzinfo=timezone.utc).timestamp())


class FakeTelegram:
    def __init__(self):
        self.chat_id = OWNER_CHAT
        self.sent, self.queue, self.fail_for = [], [], set()

    def send(self, text, markup=None, chat_id=None):
        chat = str(chat_id or self.chat_id)
        if chat in self.fail_for:
            raise TgError("boom")
        self.sent.append((chat, text))

    def get_me(self):
        return {"username": "lms_test_bot"}

    def get_updates(self, offset):
        return [u for u in self.queue if u["update_id"] >= offset]

    def texts(self, chat=None):
        return "\n".join(t for c, t in self.sent if chat is None or c == str(chat))


class FakeMoodle:
    base = "https://lms.test"

    def __init__(self):
        self.token, self.logins, self.valid = None, 0, "tok"
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

    def login(self):
        self.logins += 1
        self.token = self.valid

    def enrolled(self):
        if self.token != self.valid:
            raise LoginError("invalidtoken")
        return self.courses

    def call(self, fn, **p):
        cids = [v for k, v in p.items() if k.startswith("courseids[")]
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


def run(tmp_path, m, tg, now=NOW):
    e = Engine(m, tg, root=str(tmp_path), key=KEY, now=now, log=lambda *_: None)
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
    assert "LMS Guardian is live" in txt and "Now following: CSE333s" in txt
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
    assert "Now following: CSE334s" in tg.texts(777)
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
    assert "You follow 1 subjects" in txt and "Assignment 1" in txt and "in 10 days" in txt
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
