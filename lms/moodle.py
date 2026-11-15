"""Read-only Moodle web-service client (mobile app service). Only ever calls get_* functions."""
import json

import urllib.parse

from .util import http_get_bytes, http_post


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

    def download(self, fileurl, max_bytes, get=None):
        """Read-only file download with the mobile-app token. Only this site's pluginfile.php URLs are allowed."""
        get = get or http_get_bytes
        if not fileurl.startswith(self.base + "/") or "/pluginfile.php/" not in fileurl:
            raise MoodleError("not a Moodle file link")
        if "/webservice/pluginfile.php/" not in fileurl:
            fileurl = fileurl.replace("/pluginfile.php/", "/webservice/pluginfile.php/", 1)
        parts = urllib.parse.urlsplit(fileurl)
        query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "token"] + [("token", self.token)]
        data, ctype = get(urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))), max_bytes)
        head = data[:400].lstrip().lower()
        if ("json" in ctype and head.startswith(b"{") and b"error" in head) or (
                "text/html" in ctype and not urllib.parse.unquote(parts.path).lower().endswith((".html", ".htm"))):
            raise MoodleError("Moodle refused the file download")
        return data
