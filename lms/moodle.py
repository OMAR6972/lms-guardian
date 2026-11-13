"""Read-only Moodle web-service client (mobile app service). Only ever calls get_* functions."""
import json

from .util import http_post


class LoginError(Exception):
    """Credentials rejected / no token."""


class MoodleError(Exception):
    def __init__(self, msg, code=""):
        super().__init__(msg)
        self.code = code


class Moodle:
    def __init__(self, base, user, password, post=http_post):
        self.base = base.rstrip("/")
        self._user = user
        self._password = password
        self._post = post
        self.token = None
        self.userid = None

    def login(self):
        status, text = self._post(
            f"{self.base}/login/token.php",
            {"username": self._user, "password": self._password, "service": "moodle_mobile_app"},
        )
        try:
            d = json.loads(text)
        except ValueError:
            raise MoodleError(f"login endpoint returned non-JSON (HTTP {status})")
        if not d.get("token"):
            raise LoginError(d.get("error") or "no token returned")
        self.token = d["token"]

    def call(self, fn, **params):
        if "_get_" not in fn:  # safety: this client is strictly read-only
            raise MoodleError(f"refusing non-read function {fn}")
        data = {"wstoken": self.token, "wsfunction": fn, "moodlewsrestformat": "json"}
        data.update(params)
        status, text = self._post(f"{self.base}/webservice/rest/server.php", data)
        try:
            d = json.loads(text)
        except ValueError:
            raise MoodleError(f"{fn}: non-JSON response (HTTP {status})")
        if isinstance(d, dict) and "exception" in d:
            code = d.get("errorcode", "")
            if code == "invalidtoken":
                raise LoginError(f"{fn}: {code}")
            raise MoodleError(f"{fn}: {code or d['exception']}: {str(d.get('message', ''))[:120]}", code)
        return d

    def enrolled(self):
        if self.userid is None:
            self.userid = self.call("core_webservice_get_site_info")["userid"]
        return self.call("core_enrol_get_users_courses", userid=self.userid)
