"""Compare two course snapshots and describe what changed as plain-text events."""
from .util import fmt_delta, fmt_size, fmt_ts

EMOJI = {"resource": "📄", "folder": "📁", "url": "🔗", "page": "📃", "label": "🏷", "book": "📖",
         "forum": "💬", "feedback": "📋", "choice": "🗳", "workshop": "🛠", "lti": "🧩", "scorm": "🎓"}
LABEL = {"resource": "file", "folder": "folder", "url": "link", "page": "page", "label": "text block",
         "book": "book", "forum": "forum", "feedback": "feedback form", "choice": "poll"}
SKIP_MODULES = ("assign", "quiz")  # covered by the richer assignment/quiz diffs


def ev(emoji, kind, title, lines=None, url=""):
    return {"emoji": emoji, "kind": kind, "title": title, "lines": lines or [], "url": url}


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
            out.append(ev(emoji, f"New {kind_name}", n["name"], lines, n["url"]))
            continue
        lines, only_new_files = [], True
        if o["name"] != n["name"]:
            lines.append(f"Renamed: {o['name']} → {n['name']}")
            only_new_files = False
        if o["desc"] != n["desc"]:
            lines.append("Description edited" + (f": {n['snip'][:140]}" if n["snip"] else ""))
            only_new_files = False
        for key, (sz, tm) in n["files"].items():
            if key not in o["files"]:
                lines.append(f"➕ New file: {key.lstrip('/')} ({fmt_size(sz)})")
            elif o["files"][key] != [sz, tm]:
                lines.append(f"🔄 File replaced/updated: {key.lstrip('/')} ({fmt_size(sz)})")
                only_new_files = False
        for key in o["files"]:
            if key not in n["files"]:
                lines.append(f"➖ File removed: {key.lstrip('/')}")
                only_new_files = False
        if lines:
            if only_new_files:
                out.append(ev("➕", f"New file in {kind_name}", n["name"], lines, n["url"]))
            else:
                out.append(ev("🔄", f"Updated {kind_name}", n["name"], lines, n["url"]))
    for mid, o in old.items():
        if mid not in new and o["modname"] not in SKIP_MODULES:
            out.append(ev("🗑", f"Removed {LABEL.get(o['modname'], o['modname'] or 'item')}", o["name"]))
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
            out.append(ev("📝", "New assignment", n["name"], lines, n["url"]))
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
            out.append(ev("⏰" if any("Due" in l for l in lines) else "✏️", "Assignment changed", n["name"], lines, n["url"]))
    for aid, o in old.items():
        if aid not in new:
            out.append(ev("🗑", "Assignment removed", o["name"], [], o.get("url", "")))
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
            out.append(ev("❓", "New quiz", n["name"], lines, n["url"]))
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
            out.append(ev("⏰", "Quiz changed", n["name"], lines, n["url"]))
    for qid, o in old.items():
        if qid not in new:
            out.append(ev("🗑", "Quiz removed", o["name"], [], o.get("url", "")))
    return out


def diff_disc(old, new):
    out = []
    for did, n in new.items():
        o = old.get(did)
        if o is None:
            kind = "New announcement" if n["news"] else f"New post in {n['forum']}"
            lines = [n["snip"][:240]] if n["snip"] else []
            out.append(ev("📢" if n["news"] else "💬", kind, n["subject"], lines, n["url"]))
        elif n["news"] and o["msg"] != n["msg"]:
            out.append(ev("✏️", "Announcement edited", n["subject"], [n["snip"][:240]] if n["snip"] else [], n["url"]))
    return out


def diff_course(old, new):
    """Events for everything that changed between two snapshots of one course."""
    return (diff_assigns(old.get("assigns", {}), new.get("assigns", {}))
            + diff_quizzes(old.get("quizzes", {}), new.get("quizzes", {}))
            + diff_disc(old.get("disc", {}), new.get("disc", {}))
            + diff_modules(old.get("modules", {}), new.get("modules", {})))
