"""Small shared helpers: HTTP, text normalising, Cairo-time formatting, message chunking."""
import hashlib
import html
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

CAIRO = ZoneInfo("Africa/Cairo")
UA = "Mozilla/5.0 (LMS-Guardian personal monitor)"


class NetError(Exception):
    """Network-level failure. The message never contains a URL (URLs can hold tokens)."""


def http_post(url, data, retries=2, timeout=40):
    """POST form data. Returns (status, text). Retries network errors and 5xx."""
    body = urllib.parse.urlencode(data).encode()
    last = "unknown"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code >= 500 and attempt < retries:
                last = f"HTTP {e.code}"
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, text
        except Exception as e:  # DNS, timeout, TLS, reset
            last = type(e).__name__
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
    raise NetError(f"network error ({last})")


class TooBig(Exception):
    pass


def http_get_bytes(url, max_bytes, timeout=120):
    """GET a file. Returns (bytes, content_type). Raises TooBig past max_bytes, NetError on failure (no URL in it)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = int(r.headers.get("Content-Length") or 0)
            if n > max_bytes:
                raise TooBig(n)
            data = r.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise TooBig(len(data))
            return data, r.headers.get("Content-Type", "")
    except TooBig:
        raise
    except urllib.error.HTTPError as e:
        raise NetError(f"download failed (HTTP {e.code})")
    except Exception as e:
        raise NetError(f"download failed ({type(e).__name__})")


def multipart(fields, files):
    """Encode form fields + files as multipart/form-data. files: [(field, filename, bytes)]."""
    boundary = "----lmsguardian" + hashlib.sha1(str(time.time()).encode()).hexdigest()[:16]
    out = []
    q = lambda v: v.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")
    for k, v in fields.items():
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode() + str(v).encode() + b"\r\n")
    for field, name, data in files:
        out.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{q(name)}"\r\n'
                   "Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def http_post_multipart(url, fields, files, timeout=180, headers=None):
    """POST multipart. Returns (status, text). One retry on network errors and 5xx. Never puts the URL in errors."""
    body, ctype = multipart(fields, files)
    last = "unknown"
    for attempt in range(2):
        req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Content-Type": ctype, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            if e.code >= 500 and attempt == 0:
                last = f"HTTP {e.code}"
                time.sleep(3)
                continue
            return e.code, text
        except Exception as e:
            last = type(e).__name__
            if attempt == 0:
                time.sleep(3)
                continue
    raise NetError(f"network error ({last})")


esc = html.escape


def norm_text(s):
    """Plain, whitespace-collapsed text from Moodle HTML, with volatile tokens removed."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"token=[0-9a-fA-F]+", "", s)
    return re.sub(r"\s+", " ", s).strip()


def digest(s):
    return hashlib.sha1(norm_text(s).encode()).hexdigest()[:12]


def fmt_ts(ts):
    if not ts:
        return "none"
    d = datetime.fromtimestamp(ts, CAIRO)
    return f"{d:%a} {d.day} {d:%b} {d:%Y}, {int(d.strftime('%I'))}:{d:%M} {d:%p}"


def fmt_delta(secs):
    s = abs(int(secs))
    days, rest = divmod(s, 86400)
    hours, rest = divmod(rest, 3600)
    mins = rest // 60
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} h")
    if mins and not days:
        parts.append(f"{mins} min")
    return " ".join(parts) or "0 min"


def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def chunk_blocks(header, blocks, limit=3800):
    """Join blocks into messages no longer than `limit`, repeating the header."""
    out, cur = [], header
    for b in blocks:
        piece = b if len(b) <= limit - len(header) - 4 else b[: limit - len(header) - 8] + "…"
        if len(cur) + len(piece) + 2 > limit and cur != header:
            out.append(cur)
            cur = header
        cur += "\n\n" + piece
    if cur != header:
        out.append(cur)
    return out


COURSE_RE = re.compile(r"^(\S+)\s*\(.*?\)\s*-\s*(.*?)\s*\(\d+\)\s*$")


def split_course(fullname):
    """'CSE333s (UG2023) - Data Structures (40954)' -> ('CSE333s', 'Data Structures')."""
    m = COURSE_RE.match(fullname or "")
    if m:
        return m.group(1), m.group(2)
    return (fullname or "?")[:12], fullname or "?"


_MD_SPECIAL = re.compile(r"([\\*_~`|>\[\]])")


def md_escape(text):
    text = _MD_SPECIAL.sub(r"\\\1", text)
    return re.sub(r"(?m)^(#+\s|-\s)", r"\\\1", text)


def html_to_md(s):
    """Convert the small HTML subset used for Telegram (<b>, <i>, <a href>) into Discord markdown."""
    out, href = [], ""
    for tok in re.split(r"(<[^>]+>)", s):
        if not tok:
            continue
        if tok.startswith("<"):
            t = tok.lower()
            if t in ("<b>", "</b>"):
                out.append("**")
            elif t in ("<i>", "</i>"):
                out.append("*")
            elif t.startswith("<a "):
                m = re.search(r'href="([^"]*)"', tok)
                href = html.unescape(m.group(1)).replace(")", "%29") if m else ""
                out.append("[")
            elif t == "</a>":
                out.append(f"]({href})")
        else:
            out.append(md_escape(html.unescape(tok)))
    return "".join(out)
