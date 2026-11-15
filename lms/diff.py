"""Compare two course snapshots and describe what changed as plain-text events."""
from .util import fmt_delta, fmt_size, fmt_ts

EMOJI = {"resource": "📄", "folder": "📁", "url": "🔗", "page": "📃", "label": "🏷", "book": "📖",
         "forum": "💬", "feedback": "📋", "choice": "🗳", "workshop": "🛠", "lti": "🧩", "scorm": "🎓", "scheduler": "📆", "survey": "📋"}
LABEL = {"resource": "file", "folder": "folder", "url": "link", "page": "page", "label": "text block",
         "book": "book", "forum": "forum", "feedback": "feedback form", "choice": "poll",
         "workshop": "peer-review workshop", "lti": "external tool", "scorm": "course package",
         "scheduler": "booking slots", "wiki": "wiki", "glossary": "glossary", "data": "database",
         "lesson": "lesson", "chat": "chat", "survey": "survey", "h5pactivity": "interactive activity"}
SKIP_MODULES = ("assign", "quiz")  # covered by the richer assignment/quiz diffs


# Categories a recipient can switch on/off in the panel. "grades" and "sis" only ever go to the owner.
CATS = ("materials", "edits", "assignments", "quizzes", "posts", "grades", "sis")


def ev(emoji, kind, title, lines=None, url="", cat="materials", files=None):
    e = {"emoji": emoji, "kind": kind, "title": title, "lines": lines or [], "url": url, "cat": cat}
    if files:
        e["files"] = files
    return e


def attach(mod, keys):
    """Files to send as documents: [{name, size, url}] for the given file keys that have a download link."""
    furls = mod.get("furls") or {}
    return [{"name": k.rsplit("/", 1)[-1] or k, "size": mod["files"][k][0], "url": furls[k]} for k in keys if furls.get(k)]


def date_change(label, old, new):
    if old == new:
        return None
    if not old:
        return f"{label} set: {fmt_ts(new)}"
    if not new:
        return f"{label} removed (was {fmt_ts(old)})"
    secs = new - old
    if secs > 0:
        return f"{label}: {fmt_ts(old)} → {fmt_ts(new)}\n{fmt_delta(secs)} later (postponed ⏩)"
    return f"{label}: {fmt_ts(old)} → {fmt_ts(new)}\n{fmt_delta(secs)} earlier (moved up ⏪)"


def diff_modules(old, new):
    out = []
    for mid, n in new.items():
        if n["modname"] in SKIP_MODULES:
            continue
        o = old.get(mid)
        emoji = EMOJI.get(n["modname"], "🧩")
        kind_name = LABEL.get(n["modname"], n["modname"] or "item")
        if o is None:
            lines = [f"Section: {n['section']}"] if n["section"] else []
            lines += [f"• {name} ({fmt_size(sz)})" for name, (sz, _t) in n["files"].items()]
            if n["modname"] in ("label", "page") and n["snip"]:
                lines.append(n["snip"][:160])
            out.append(ev(emoji, f"New {kind_name}", n["name"], lines, n["url"], files=attach(n, n["files"])))
            continue
        lines, only_new_files, changed = [], True, []
        if o["name"] != n["name"]:
            lines.append(f"Renamed: {o['name']} → {n['name']}")
            only_new_files = False
        if o["desc"] != n["desc"]:
            lines.append("Description edited" + (f": {n['snip'][:140]}" if n["snip"] else ""))
            only_new_files = False
        for key, (sz, tm) in n["files"].items():
            if key not in o["files"]:
                lines.append(f"➕ New file: {key.lstrip('/')} ({fmt_size(sz)})")
                changed.append(key)
            elif o["files"][key] != [sz, tm]:
                lines.append(f"🔄 File replaced/updated: {key.lstrip('/')} ({fmt_size(sz)})")
                changed.append(key)
                only_new_files = False
        for key in o["files"]:
            if key not in n["files"]:
                lines.append(f"➖ File removed: {key.lstrip('/')}")
                only_new_files = False
        if lines:
            if only_new_files:
                kind = "New file" if kind_name == "file" else f"New file in {kind_name}"
                out.append(ev("➕", kind, n["name"], lines, n["url"], files=attach(n, changed)))
            else:
                out.append(ev("🔄", f"Updated {kind_name}", n["name"], lines, n["url"], cat="edits", files=attach(n, changed)))
    for mid, o in old.items():
        if mid not in new and o["modname"] not in SKIP_MODULES:
            out.append(ev("🗑", f"Removed {LABEL.get(o['modname'], o['modname'] or 'item')}", o["name"], cat="edits"))
    return out


def diff_assigns(old, new):
    out = []
    for aid, n in new.items():
        o = old.get(aid)
        if o is None:
            lines = []
            for label, key in (("Opens", "from"), ("Due", "due"), ("Cut-off", "cutoff")):
                if n[key]:
                    lines.append(f"{label}: {fmt_ts(n[key])}")
            if not n["due"]:
                lines.append("No due date set")
            if n["snip"]:
                lines.append(n["snip"][:160])
            out.append(ev("📝", "New assignment", n["name"], lines, n["url"], cat="assignments"))
            continue
        lines = []
        if o["name"] != n["name"]:
            lines.append(f"Renamed: {o['name']} → {n['name']}")
        for label, key in (("Due date", "due"), ("Opens", "from"), ("Cut-off", "cutoff")):
            c = date_change(label, o[key], n[key])
            if c:
                lines.append(c)
        if o["desc"] != n["desc"]:
            lines.append("Description/requirements edited" + (f": {n['snip'][:140]}" if n["snip"] else ""))
        if lines:
            out.append(ev("⏰" if any("Due" in l for l in lines) else "✏️", "Assignment changed", n["name"], lines, n["url"], cat="assignments"))
    for aid, o in old.items():
        if aid not in new:
            out.append(ev("🗑", "Assignment removed", o["name"], [], o.get("url", ""), cat="assignments"))
    return out


def diff_quizzes(old, new):
    out = []
    for qid, n in new.items():
        o = old.get(qid)
        if o is None:
            lines = []
            if n["open"]:
                lines.append(f"Opens: {fmt_ts(n['open'])}")
            if n["close"]:
                lines.append(f"Closes: {fmt_ts(n['close'])}")
            if n["limit"]:
                lines.append(f"Time limit: {n['limit'] // 60} min")
            out.append(ev("❓", "New quiz", n["name"], lines, n["url"], cat="quizzes"))
            continue
        lines = []
        if o["name"] != n["name"]:
            lines.append(f"Renamed: {o['name']} → {n['name']}")
        for label, key in (("Opens", "open"), ("Closes", "close")):
            c = date_change(label, o[key], n[key])
            if c:
                lines.append(c)
        if o["limit"] != n["limit"]:
            lines.append(f"Time limit: {o['limit'] // 60} min → {n['limit'] // 60} min")
        if o["desc"] != n["desc"]:
            lines.append("Instructions edited" + (f": {n['snip'][:140]}" if n["snip"] else ""))
        if lines:
            out.append(ev("⏰", "Quiz changed", n["name"], lines, n["url"], cat="quizzes"))
    for qid, o in old.items():
        if qid not in new:
            out.append(ev("🗑", "Quiz removed", o["name"], [], o.get("url", ""), cat="quizzes"))
    return out


def diff_disc(old, new):
    out = []
    for did, n in new.items():
        o = old.get(did)
        if o is None:
            kind = "New announcement" if n["news"] else f"New post in {n['forum']}"
            lines = [n["snip"][:240]] if n["snip"] else []
            out.append(ev("📢" if n["news"] else "💬", kind, n["subject"], lines, n["url"], cat="posts"))
        elif n["news"] and o["msg"] != n["msg"]:
            out.append(ev("✏️", "Announcement edited", n["subject"], [n["snip"][:240]] if n["snip"] else [], n["url"], cat="posts"))
    return out


def _has(g):
    return bool(g) and g.get("grade", "") not in ("", "-")


def _grade_text(g):
    out = g["grade"]
    if g.get("max") not in (None, "", 0) and "/" not in out and "%" not in out:
        out += f" / {g['max']:g}" if isinstance(g["max"], (int, float)) else f" / {g['max']}"
    return out


def diff_grades(old, new):
    out = []
    for gid, n in new.items():
        o = old.get(gid)
        if _has(n) and not _has(o):
            out.append(ev("🎯", "New grade", n["name"], [f"Grade: {_grade_text(n)}"], n.get("url", ""), cat="grades"))
        elif _has(n) and _has(o) and (o["grade"], o.get("max")) != (n["grade"], n.get("max")):
            out.append(ev("🎯", "Grade changed", n["name"], [f"{_grade_text(o)} → {_grade_text(n)}"], n.get("url", ""), cat="grades"))
        elif _has(o) and not _has(n):
            out.append(ev("🎯", "Grade removed", n["name"], [f"Was: {_grade_text(o)}"], n.get("url", ""), cat="grades"))
    return out


def diff_sis(old, new):
    """Compare two SIS snapshots ({page_key: {"title", "url", "kind"?, "rows": {row_key: [cells]}}}).
    Pages from extension v2 have kind "marks"/"finals" and rows [subject, label, value, url?]."""
    out = []
    for key, page in new.items():
        orows = (old.get(key) or {}).get("rows")
        if orows is None:
            continue  # page seen for the first time: baseline silently
        if page.get("kind") in ("marks", "finals"):
            for rk, cells in page.get("rows", {}).items():
                subject, label, value = (list(cells) + ["", "", ""])[:3]
                url = cells[3] if len(cells) > 3 else page.get("url", "")
                was = (orows.get(rk) or [None, None, None])[2]
                if value == was or not value or value.startswith("-"):
                    continue  # unchanged, or still not out (a mark that disappears is not announced)
                if was is None or was.startswith("-"):
                    out.append(ev("🎓", f"{label} released", subject, [value], url, cat="sis"))
                else:
                    out.append(ev("🎓", f"{label} changed", subject, [f"{was} → {value}"], url, cat="sis"))
            continue
        title = page.get("title") or "SIS"
        for rk, cells in page.get("rows", {}).items():
            label = rk.split("|")[-1] or "row"
            if rk not in orows:
                out.append(ev("🎓", "New SIS entry", label, [" · ".join(c for c in cells if c)[:300], f"Page: {title}"], page.get("url", ""), cat="sis"))
            elif orows[rk] != cells:
                out.append(ev("🎓", "SIS entry changed", label,
                              ["Before: " + " · ".join(c for c in orows[rk] if c)[:250],
                               "Now: " + " · ".join(c for c in cells if c)[:250], f"Page: {title}"], page.get("url", ""), cat="sis"))
    return out


def diff_course(old, new):
    """Events for everything that changed between two snapshots of one course."""
    grades = diff_grades(old["grades"], new["grades"]) if "grades" in old and "grades" in new else []  # else: silent baseline
    return (grades + diff_assigns(old.get("assigns", {}), new.get("assigns", {}))
            + diff_quizzes(old.get("quizzes", {}), new.get("quizzes", {}))
            + diff_disc(old.get("disc", {}), new.get("disc", {}))
            + diff_modules(old.get("modules", {}), new.get("modules", {})))
