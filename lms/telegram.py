"""Minimal Telegram Bot API client."""
import json
import time

from .util import NetError, http_post


class TgError(Exception):
    pass


class Telegram:
    def __init__(self, token, chat_id):
        self._token = token
        self.chat_id = str(chat_id)

    def _api(self, method, **params):
        data = {}
        for k, v in params.items():
            if v is None:
                continue
            data[k] = json.dumps(v) if isinstance(v, (dict, list)) else v
        for attempt in range(2):
            try:
                status, text = http_post(f"https://api.telegram.org/bot{self._token}/{method}", data)
            except NetError as e:
                raise TgError(str(e))
            try:
                d = json.loads(text)
            except ValueError:
                raise TgError(f"{method}: HTTP {status}")
            if d.get("ok"):
                return d["result"]
            if d.get("error_code") == 429 and attempt == 0:
                time.sleep(min(int(d.get("parameters", {}).get("retry_after", 5)), 20) + 1)
                continue
            raise TgError(f"{method}: {d.get('description')}")

    def send(self, text, markup=None, chat_id=None):
        return self._api(
            "sendMessage", chat_id=chat_id or self.chat_id, text=text, parse_mode="HTML",
            disable_web_page_preview="true", reply_markup=markup,
        )

    def get_me(self):
        return self._api("getMe")

    def get_updates(self, offset):
        return self._api(
            "getUpdates", offset=offset, timeout=0, allowed_updates=["message", "callback_query"]
        )

    def answer_cb(self, cb_id, text=""):
        return self._api("answerCallbackQuery", callback_query_id=cb_id, text=text or None)

    def edit_markup(self, message_id, markup):
        return self._api(
            "editMessageReplyMarkup", chat_id=self.chat_id, message_id=message_id, reply_markup=markup
        )
