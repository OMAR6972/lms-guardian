"""Discord webhook sender. One webhook = one channel; any number of channels/servers can be used."""
import json
import re
import time
import urllib.error
import urllib.request

HOOK_RE = re.compile(r"^https://(?:(?:canary|ptb)\.)?(?:discord|discordapp)\.com/api/webhooks/\d+/[\w-]+$")
UA = "DiscordBot (https://github.com/OMAR6972/lms-guardian, 1.0)"


class DiscordError(Exception):
    """Never contains the webhook URL (it is a secret)."""


def valid_webhook(url):
    return bool(HOOK_RE.match(url or ""))


class Discord:
    def __init__(self, pause=0.5):
        self.pause = pause

    def send(self, url, markdown):
        if not valid_webhook(url):
            raise DiscordError("not a Discord webhook link")
        body = json.dumps({
            "embeds": [{"description": markdown[:4096], "color": 0x2F80D6}],
            "allowed_mentions": {"parse": []},  # never ping @everyone / roles from a Moodle title
        }).encode()
        for attempt in range(2):
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=30):
                    time.sleep(self.pause)  # stay under Discord's per-webhook rate limit
                    return
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt == 0:
                    try:
                        wait = float(json.loads(e.read().decode()).get("retry_after", 2))
                    except (ValueError, TypeError):
                        wait = 2.0
                    time.sleep(min(wait, 10) + 0.5)
                    continue
                raise DiscordError(f"HTTP {e.code}")
            except Exception as e:
                raise DiscordError(type(e).__name__)
