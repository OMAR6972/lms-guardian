"""SIS client: the bot logs in to eng.asu.edu.eg by itself and solves the login CAPTCHA.

Used by the Engine when the SIS_USER / SIS_PASS secrets are set. Reads the same pages the browser
extension reads (marks, final grades) into the same shape it writes to sis.enc, so the diffing and
Telegram alerts are shared.

CAPTCHA solving: if the TWOCAPTCHA_KEY secret is set, the image goes to 2captcha.com (very reliable,
~$3 per 1000 solves). Otherwise it is read locally with tesseract OCR (free, needs the apt/pip
packages installed in the workflow). Each login attempt tries up to LOGIN_TRIES fresh captchas.
"""
import base64
import io
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://eng.asu.edu.eg"
UA = "Mozilla/5.0 (LMS-Guardian personal monitor)"
LOGIN_TRIES = 20       # fresh CAPTCHA per try (each is ~2 seconds)


class SisError(Exception):
    """Resource labels never contain the password."""


class FeesBlocked(SisError):
    pass


# ---------- small HTML helpers (ports of the extension's parsers) ----------
def _clean(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'),
                 ("&#039;", "'"), ("&#0?39;", "'")):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip()


def looks_logged_out(url, html):
    try:
        if re.search(r"^/(ar/)?login\b", urllib.parse.urlparse(url).path, re.I):
            return True
    except ValueError:
        pass
    return bool(re.search(r'type=["\']?password', html or "", re.I)) and bool(re.search(r"captcha", html or "", re.I))


def blocked_by_fees(url, html):
    try:
        if re.search(r"^/payments/student_fees\b", urllib.parse.urlparse(url).path, re.I):
            return True
    except ValueError:
        pass
    return "cannot use this service, unless you pay the tuition fees" in (html or "").lower()


def profile_url(html):
    m = re.search(r'href="(?:https://eng\.asu\.edu\.eg)?(/users/\d+/profile)"', html or "")
    return BASE + m.group(1) if m else ""


_COURSE_LINK = re.compile(r'<a href="((?:https://eng\.asu\.edu\.eg)?/dashboard/courses/show/\d+[^"]*)"\s*>([\s\S]*?)</a>')
_COURSE_TEXT = re.compile(r"^([A-Z]{2,5}[0-9x]{2,4}[a-z]?)\s*:\s*(.+?)\s*\(([^()]+)\)\s*$")


def parse_my_courses(html):
    out, seen = [], set()
    for m in _COURSE_LINK.finditer(html or ""):
        text = _clean(m.group(2))
        t = _COURSE_TEXT.match(text)
        url = m.group(1) if m.group(1).startswith("http") else BASE + m.group(1)
        url = url.replace("&amp;", "&")
        if not t or url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "code": t.group(1), "name": t.group(2), "term": t.group(3)})
    return out


_MARK_ROW = re.compile(r'<ul class="row no-gutters">\s*<li[^>]*>([\s\S]*?)</li>\s*<li[^>]*>([\s\S]*?)</li>\s*</ul>')
_MARK_VAL = re.compile(r"^(.*?)\s*/\s*([\d.]+)$")


def parse_marks(html):
    out = []
    for m in _MARK_ROW.finditer(html or ""):
        label, raw = _clean(m.group(1)), _clean(m.group(2))
        p = _MARK_VAL.match(raw)
        if not label or not p:
            continue
        v = p.group(1).strip()
        out.append({"label": label, "value": "" if v == "-" else v, "max": p.group(2)})
    return out


_TD = r"<td[^>]*>(?:(?!</?\s*(?:td|tr|table)\b)[\s\S])*?</td>"
_FINAL_ROW = re.compile(r"<tr\b[^>]*>\s*((?:" + _TD + r"\s*){6})</tr>")
_FINAL_CODE = re.compile(r"^[A-Z]{2,5}[0-9x]{2,4}[a-z]?$")
_FINAL_TERM = re.compile(r"^(Fall|Spring|Summer|Winter) \d{4}$")


def parse_finals(html):
    out = {}
    for m in _FINAL_ROW.finditer(html or ""):
        cells = [_clean(c) for c in re.findall(_TD, m.group(1))]
        code, name, term, grade, gpa, hrs = (cells + [""] * 6)[:6]
        if not _FINAL_CODE.match(code) or not _FINAL_TERM.match(term) or not grade:
            continue
        h = re.search(r"\d+(?:\.\d+)?", hrs or "")
        out["%s|%s" % (code, term)] = {"code": code, "name": name, "term": term,
                                      "grade": grade, "gpa": gpa, "hours": float(h.group()) if h else 0}
    return out


def _form_fields(html):
    fields = {}
    for m in re.finditer(r"<input\b[^>]*>", html or ""):
        tag = m.group(0)
        n = re.search(r'name="([^"]+)"', tag)
        if not n:
            continue
        v = re.search(r'value="([^"]*)"', tag)
        fields[n.group(1)] = v.group(1) if v else ""
    return fields


# ---------- CAPTCHA solving ----------
def _solve_ocr(img):
    """Read the CAPTCHA locally with tesseract: distorted digits + noise lines + speckles.
    Free. Tries many preprocessing variants and votes on the most frequent digit reading."""
    import pytesseract
    from PIL import Image, ImageFilter, ImageOps

    im = Image.open(io.BytesIO(img)).convert("L")
    im = im.resize((im.width * 4, im.height * 4), Image.LANCZOS)
    im = im.filter(ImageFilter.MedianFilter(3))  # scrub the speckle dots
    if sum(im.getdata()) / (im.width * im.height) < 128:  # light text on dark bg: flip
        im = ImageOps.invert(im)

    votes = {}
    for threshold in (100, 130, 160, 190, 220):
        bw = im.point(lambda p: 0 if p < threshold else 255)
        for psm in (7, 6, 8, 13):
            txt = pytesseract.image_to_string(bw, config="--psm %d -c tessedit_char_whitelist=0123456789" % psm).strip()
            txt = "".join(ch for ch in txt if ch.isdigit())
            if len(txt) >= 5:
                votes[txt] = votes.get(txt, 0) + 1
    if not votes:
        return ""
    return max(votes, key=votes.get)




# ---------- the client ----------
class Sis:
    def __init__(self, email, password, log=print, key2captcha="", cookies=None):
        self.email, self.password, self.log = email, password, log
        self.key2 = key2captcha
        self.cookies = dict(cookies or {})

    def _req(self, url, data=None, retries=2):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        last = "unknown"
        for attempt in range(retries + 1):
            req = urllib.request.Request(url, data=body,
                                        headers={"User-Agent": UA, **({"Cookie": "; ".join("%s=%s" % kv for kv in self.cookies.items())} if self.cookies else {})})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    for h in r.headers.get_all("Set-Cookie") or []:
                        kv = h.split(";", 1)[0]
                        if "=" in kv:
                            k, v = kv.split("=", 1)
                            if v.strip():
                                self.cookies[k] = v.strip()
                            else:
                                self.cookies.pop(k, None)
                    return r.status, r.geturl(), r.read()
            except urllib.error.HTTPError as e:
                return e.code, url, e.read()
            except Exception as e:
                last = type(e).__name__
                if attempt < retries:
                    time.sleep(2 * (attempt + 1))
        raise SisError("network error (%s)" % last)

    def _get(self, url):
        status, final, raw = self._req(url)
        return status, final, raw.decode("utf-8", "replace")

    def _login(self):
        for attempt in range(1, LOGIN_TRIES + 1):
            _s, _u, form_html = self._get(BASE + "/login")
            if not looks_logged_out(BASE + "/login", form_html):
                return  # session cookie still valid
            action = re.search(r'<form[^>]*action="([^"]+)"', form_html or "")
            post = action.group(1) if action else "/login"
            if post.startswith("/"):
                post = BASE + post
            fields = _form_fields(form_html)
            img_m = re.search(r'src="([^"]*captcha[^"]*)"', form_html or "")
            if not img_m:
                raise SisError("no captcha image found on the login page (form had: %s)" % ", ".join(fields))
            src = img_m.group(1)
            if src.startswith("/"):
                src = BASE + src
            src += ("&" if "?" in src else "?") + str(random.random())  # never the cached image
            _cs, _cu, img = self._req(src)
            try:
                answer = _solve_ocr(img)
            except Exception as e:  # tesseract/PIL problem: fresh captcha and try again
                self.log("sis login: captcha solve crashed: %s" % e)
                continue
            self.log("sis login: attempt %d, captcha reads %r" % (attempt, answer or "(nothing)"))
            if not answer:
                continue
            fields.update({"email": self.email, "password": self.password, "captcha": answer})
            _st, final, raw = self._req(post, data=fields)
            page = raw.decode("utf-8", "replace")
            if not looks_logged_out(final, page):
                self.log("sis: logged in (captcha solved on attempt %d)" % attempt)
                return
            grr = re.search(r"(?:invalid|wrong|incorrect|not correct)[^<]{0,80}", page, re.I)
            self.log("sis login: rejected (attempt %d%s)" % (attempt, (" · page says: " + grr.group(0)) if grr else ""))
        raise SisError("could not log in to the SIS after %d captcha attempts" % LOGIN_TRIES)


    def snapshot(self, known_profile=""):
        """The same shape the extension writes to sis.enc: {v, seen, status, profile, pages}."""
        _s, url, dash = self._get(BASE + "/dashboard")
        if looks_logged_out(url, dash):
            self._login()
            _s, url, dash = self._get(BASE + "/dashboard")
            if looks_logged_out(url, dash):
                raise SisError("still logged out after login")
        if blocked_by_fees(url, dash):
            return {"v": 2, "seen": int(time.time()), "status": "fees", "pages": {}}
        profile = profile_url(dash) or known_profile
        courses = parse_my_courses(self._get(BASE + "/dashboard/my_courses")[2])
        if not courses:
            raise SisError("subject list read empty")
        marks = {}
        for c in courses:
            _s, cu, page = self._get(c["url"])
            if looks_logged_out(cu, page) or blocked_by_fees(cu, page):
                raise SisError("subject %s read failed" % c["code"])
            for mk in parse_marks(page):
                marks["%s|%s" % (c["code"], mk["label"])] = [
                    "%s — %s" % (c["code"], c["name"]), mk["label"], "%s / %s" % (mk["value"] or "-", mk["max"]), c["url"]]
        finals = {}
        if profile:
            _s, pu, page = self._get(profile)
            if not looks_logged_out(pu, page) and not blocked_by_fees(pu, page):
                for k, f in parse_finals(page).items():
                    finals[k] = ["%s — %s" % (f["code"], f["name"]), "Final grade",
                                 "%s%s · %s" % (f["grade"], (" · GPA " + f["gpa"]) if f["gpa"] else "", f["term"]), profile]
        return {"v": 2, "seen": int(time.time()), "status": "ok", "profile": profile,
                "pages": {
                    "marks": {"title": "Subject marks", "kind": "marks", "url": BASE + "/dashboard/my_courses", "rows": marks},
                    "finals": {"title": "Final grades", "kind": "finals", "url": profile, "rows": finals},
                }}
