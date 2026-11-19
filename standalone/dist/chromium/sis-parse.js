(function(){
const SIS = "https://eng.asu.edu.eg";
const clean = (s) => String(s).replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
  .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#0?39;/g, "'").replace(/\s+/g, " ").trim();
const CODE = /^[A-Z]{2,5}[0-9x]{2,4}[a-z]?$/;
const TERM = /^(Fall|Spring|Summer|Winter) \d{4}$/;

/** True when the HTML/URL is the login page rather than a signed-in page. */
function looksLoggedOut(url, html) {
  try { if (/^\/(ar\/)?login\b/i.test(new URL(url).pathname)) return true; } catch (e) { /* not a URL */ }
  return /type=["']?password/i.test(html || "") && /captcha/i.test(html || "");
}
/** The SIS refuses grade pages (subjects, profile) while tuition is unpaid and sends you to the fees page instead. */
function blockedByFees(url, html) {
  try { if (/^\/payments\/student_fees\b/i.test(new URL(url, SIS).pathname)) return true; } catch (e) { /* not a URL */ }
  return /cannot use this service, unless you pay the tuition fees/i.test(html || "");
}
/** Unread count on the dashboard's "Discuss with your advisor" button. */
function parseAdvisorBadge(html) {
  const m = /title="Discuss with your advisor"[\s\S]*?<span class="badge[^"]*"[^>]*>\s*(\d+)\s*<\/span>/.exec(html || "");
  return m ? Number(m[1]) : 0;
}
/** The advisor discussion thread -> [{key, mine, who, when, text}], newest first as the page lists them.
 *  key ignores the relative date ("18 days ago" changes daily); mine = written by you (own = your user id). */
function parseAdvisorThread(html, ownId) {
  const out = [];
  const re = /<div class="media-body">\s*<h5[^>]*>\s*<a[^>]*href="[^"]*\/users\/(\d+)\/profile"[^>]*>([\s\S]*?)<\/a>\s*<span class="date"[^>]*>([\s\S]*?)<\/span>\s*<\/h5>\s*<p[^>]*>([\s\S]*?)<\/p>/g;
  const seen = {};
  for (let m; (m = re.exec(html || ""));) {
    const who = clean(m[2]), text = clean(m[4].replace(/<br\s*\/?>/gi, " "));
    const base = `${m[1]}|${text.slice(0, 160)}`;
    seen[base] = (seen[base] || 0) + 1;
    out.push({ key: `${base}|${seen[base]}`, mine: String(m[1]) === String(ownId), who, when: clean(m[3]), text: text.slice(0, 300) });
  }
  return out;
}
/** Advisor messages you haven't seen yet. First read ever (seen === undefined) counts nothing as new. */
function newAdvisor(adv, seen) {
  if (!adv || !seen) return [];
  const have = new Set(seen);
  return (adv.messages || []).filter((x) => !x.mine && !have.has(x.key));
}
/** Profile link from any signed-in page: /users/<id>/profile */
function profileUrl(html) {
  const m = /href="(?:https:\/\/eng\.asu\.edu\.eg)?(\/users\/\d+\/profile)"/.exec(html || "");
  return m ? SIS + m[1] : "";
}
/** My Courses page -> [{url, code, name, term}] for the current year. */
function parseMyCourses(html) {
  const out = [], seen = new Set();
  const re = /<a href="((?:https:\/\/eng\.asu\.edu\.eg)?\/dashboard\/courses\/show\/\d+[^"]*)"\s*>([\s\S]*?)<\/a>/g;
  for (let m; (m = re.exec(html || ""));) {
    const text = clean(m[2]), t = /^([A-Z]{2,5}[0-9x]{2,4}[a-z]?)\s*:\s*(.+?)\s*\(([^()]+)\)\s*$/.exec(text);
    const url = (m[1].startsWith("/") ? SIS + m[1] : m[1]).replace(/&amp;/g, "&");
    if (!t || seen.has(url)) continue;
    seen.add(url);
    out.push({ url, code: t[1], name: t[2], term: t[3] });
  }
  return out;
}
/** A subject page -> [{label, value, max}] from the marks boxes ("Midterm  - / 20"). value is "" when not out yet. */
function parseMarks(html) {
  const out = [];
  const re = /<ul class="row no-gutters">\s*<li[^>]*>([\s\S]*?)<\/li>\s*<li[^>]*>([\s\S]*?)<\/li>\s*<\/ul>/g;
  for (let m; (m = re.exec(html || ""));) {
    const label = clean(m[1]), raw = clean(m[2]), p = /^(.*?)\s*\/\s*([\d.]+)$/.exec(raw);
    if (!label || !p) continue;
    const v = p[1].trim();
    out.push({ label, value: v === "-" ? "" : v, max: p[2] });
  }
  return out;
}
/** Profile -> final grades {"CODE|Term": {code, name, term, grade, gpa}}, from the per-term tables. Nothing personal is read. */
function parseFinals(html) {
  const out = {};
  // A cell may not contain another row or table, so a wrapper row can never swallow the first real row.
  const TD = "<td[^>]*>(?:(?!<\\/?(?:td|tr|table)\\b)[\\s\\S])*?<\\/td>";
  const re = new RegExp(`<tr\\b[^>]*>\\s*((?:${TD}\\s*){6})<\\/tr>`, "g");
  for (let m; (m = re.exec(html || ""));) {
    const cells = (m[1].match(new RegExp(TD, "g")) || []).map(clean);
    const [code, name, term, grade, gpa, hrs] = cells;
    if (!CODE.test(code) || !TERM.test(term) || !grade) continue;
    const h = /(\d+(?:\.\d+)?)/.exec(hrs || "");
    out[`${code}|${term}`] = { code, name, term, grade, gpa, hours: h ? Number(h[1]) : 0 };
  }
  return out;
}

window.LMSG_SIS = { parseMyCourses, parseFinals, profileUrl, looksLoggedOut };
})();
