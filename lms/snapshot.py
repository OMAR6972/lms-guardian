"""Turn Moodle API responses into a compact, comparable snapshot per course."""
from .moodle import MoodleError
from .util import digest, norm_text


def ids(name, values):
    return {f"{name}[{i}]": v for i, v in enumerate(values)}


def parse_modules(contents):
    out = {}
    for sec in contents or []:
        for mod in sec.get("modules", []):
            if mod.get("uservisible") is False:
                continue
            files = {}
            for c in mod.get("contents") or []:
                if c.get("type") == "file":
                    key = (c.get("filepath") or "/") + c.get("filename", "")
                    files[key] = [c.get("filesize", 0), c.get("timemodified", 0)]
            out[str(mod["id"])] = {
                "name": norm_text(mod.get("name")) or norm_text(mod.get("description"))[:60],
                "modname": mod.get("modname", ""),
                "section": norm_text(sec.get("name")),
                "url": mod.get("url", ""),
                "desc": digest(mod.get("description")),
                "snip": norm_text(mod.get("description"))[:200],
                "files": files,
            }
    return out


def build(m, cids, old, log=print):
    """Fetch snapshots for `cids`. Returns (snaps, failed). A course with ANY failed component is
    reported as failed and left out, so a flaky API call can never look like 'everything was deleted'."""
    snaps, failed = {}, set()

    def view_url(modules, cmid, modname):
        mod = modules.get(str(cmid))
        return mod["url"] if mod and mod.get("url") else f"{m.base}/mod/{modname}/view.php?id={cmid}"

    for cid in cids:
        try:
            snaps[cid] = {"modules": parse_modules(m.call("core_course_get_contents", courseid=cid)),
                          "assigns": {}, "quizzes": {}, "disc": {}}
        except MoodleError as e:
            log(f"course {cid}: contents failed: {e}")
            failed.add(cid)
    live = [c for c in cids if c in snaps]
    if not live:
        return snaps, failed

    def batch(fn, key):
        """Return {cid: [items]} for the live courses, falling back to one call per course."""
        res, bad = {}, set()
        try:
            data = m.call(fn, **ids("courseids", live))
            res = _group(data, key, live)
            if data.get("warnings") if isinstance(data, dict) else False:
                bad |= {c for c in live if c not in res}
        except MoodleError as e:
            log(f"{fn}: batch failed ({e}); trying per course")
            for c in live:
                try:
                    res.update(_group(m.call(fn, **ids("courseids", [c])), key, [c]))
                except MoodleError as e2:
                    log(f"course {c}: {fn} failed: {e2}")
                    bad.add(c)
        return res, bad

    assigns, bad_a = batch("mod_assign_get_assignments", "assign")
    quizzes, bad_q = batch("mod_quiz_get_quizzes_by_courses", "quiz")
    forums, bad_f = batch("mod_forum_get_forums_by_courses", "forum")
    bad = bad_a | bad_q | bad_f

    log(f"forums found: {sum(len(v) for v in forums.values())} in {len(forums)} subjects")
    for cid in live:
        if cid in bad:
            failed.add(cid)
            snaps.pop(cid, None)
            continue
        snap = snaps[cid]
        for a in assigns.get(cid, []):
            snap["assigns"][str(a["id"])] = {
                "name": norm_text(a.get("name")), "due": a.get("duedate", 0),
                "from": a.get("allowsubmissionsfromdate", 0), "cutoff": a.get("cutoffdate", 0),
                "desc": digest(a.get("intro")), "snip": norm_text(a.get("intro"))[:200],
                "url": view_url(snap["modules"], a.get("cmid"), "assign"),
            }
        for q in quizzes.get(cid, []):
            snap["quizzes"][str(q["id"])] = {
                "name": norm_text(q.get("name")), "open": q.get("timeopen", 0),
                "close": q.get("timeclose", 0), "limit": q.get("timelimit", 0),
                "desc": digest(q.get("intro")), "snip": norm_text(q.get("intro"))[:200],
                "url": view_url(snap["modules"], q.get("coursemodule"), "quiz"),
            }
        prev = (old.get(str(cid)) or {}).get("disc", {})
        for f in forums.get(cid, []):
            try:
                data = m.call("mod_forum_get_forum_discussions", forumid=f["id"], perpage=10)
            except MoodleError as e:
                log(f"forum {f['id']} skipped: {e}")
                # keep what we knew so a later success doesn't re-announce old posts
                snap["disc"].update({k: v for k, v in prev.items() if v.get("fid") == f["id"]})
                continue
            for d in data.get("discussions", []):
                did = str(d.get("discussion") or d.get("id"))
                snap["disc"][did] = {
                    "fid": f["id"], "forum": norm_text(f.get("name")), "news": f.get("type") == "news",
                    "subject": norm_text(d.get("subject") or d.get("name")),
                    "msg": digest(d.get("message")), "snip": norm_text(d.get("message"))[:300],
                    "created": d.get("created", 0),
                    "url": f"{m.base}/mod/forum/discuss.php?d={did}",
                }
    return snaps, failed


def _group(data, key, cids):
    res = {}
    if key == "assign":
        for c in data.get("courses", []):
            res[c["id"]] = c.get("assignments", [])
    elif key == "quiz":
        for q in data.get("quizzes", []):
            res.setdefault(q["course"], []).append(q)
        for c in cids:
            res.setdefault(c, [])
    elif key == "forum":
        for f in data if isinstance(data, list) else []:
            res.setdefault(f["course"], []).append(f)
        for c in cids:
            res.setdefault(c, [])
    return res
