import os
import sys

from .discord import Discord
from .engine import Engine
from .moodle import Moodle
from .telegram import Telegram
from .vault import VaultError

DEFAULT_BASE = "https://lms.eng.asu.edu.eg"


def main():
    need = ["LMS_USER", "LMS_PASS", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DATA_KEY"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        print("missing secrets:", ", ".join(missing))
        return 1
    m = Moodle(os.environ.get("LMS_BASE", DEFAULT_BASE), os.environ["LMS_USER"], os.environ["LMS_PASS"])
    tg = Telegram(os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"])
    try:
        eng = Engine(m, tg, key=os.environ["DATA_KEY"], dc=Discord())
    except VaultError as e:
        print(f"stopping: {e}")
        return 1
    try:
        eng.run()
    finally:
        eng.save()  # always keep the Telegram offset and snapshots, even after a crash
    return 0


if __name__ == "__main__":
    sys.exit(main())
