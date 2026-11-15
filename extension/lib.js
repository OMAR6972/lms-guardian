// Shared helpers: encryption (same format as lms/vault.py), reading your feed, and (for later) SIS table reading.
const enc = new TextEncoder(), dec = new TextDecoder();
const b64d = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
const b64e = (u) => { let s = ""; for (const b of u) s += String.fromCharCode(b); return btoa(s); };

async function key(pass, salt, usage) {
  const base = await crypto.subtle.importKey("raw", enc.encode(pass), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations: 200000, hash: "SHA-256" }, base,
    { name: "AES-GCM", length: 256 }, false, [usage]);
}
export async function decrypt(text, pass) {
  try {
    const d = JSON.parse(text);
    const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64d(d.iv) }, await key(pass, b64d(d.salt), "decrypt"), b64d(d.ct));
    return JSON.parse(dec.decode(pt));
  } catch (e) { throw new Error("Wrong data passphrase."); }
}
export async function encrypt(obj, pass) {
  const salt = crypto.getRandomValues(new Uint8Array(16)), iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(pass, salt, "encrypt"), enc.encode(JSON.stringify(obj)));
  return JSON.stringify({ v: 1, salt: b64e(salt), iv: b64e(iv), ct: b64e(new Uint8Array(ct)) });
}

export const REPO = "OMAR6972/lms-guardian";

export function settings() {
  return chrome.storage.local.get(["code", "token", "pass", "repo"]);
}

/** File name of a person's feed; same rule as feed_id() in lms/engine.py. */
export async function feedId(code) {
  const h = new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode("lms-guardian-feed:" + code)));
  return [...h].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 24);
}
/** Read this person's own feed (public repo, so no GitHub key needed). Only their code opens it. */
export async function readFeed(code, fetcher = fetch) {
  code = (code || "").trim();
  if (code.length < 16) throw new Error("That code looks too short. Copy it again from the panel.");
  const url = `https://raw.githubusercontent.com/${REPO}/main/feeds/${await feedId(code)}.enc?t=${Date.now()}`;
  const r = await fetcher(url, { cache: "no-store" });
  if (r.status === 404) throw new Error("No updates for this code yet. If it was just made, wait about 2 minutes and try again.");
  if (!r.ok) throw new Error(`Could not reach GitHub (${r.status}).`);
  try { return await decrypt(await r.text(), code); }
  catch (e) { throw new Error("This code doesn't open the feed. Copy it again from the panel."); }
}
async function gh(cfg, path, opts = {}) {
  const r = await fetch(`https://api.github.com/repos/${cfg.repo}${path}`, {
    ...opts, headers: { Authorization: `Bearer ${cfg.token}`, Accept: "application/vnd.github+json", ...(opts.headers || {}) },
  });
  if (r.status === 401) throw new Error("GitHub did not accept the key.");
  return r;
}
/** Read and decrypt a file from the repo. Returns null when it does not exist. */
export async function readEnc(cfg, name) {
  const r = await gh(cfg, `/contents/${name}?ref=main&_=${Date.now()}`, { headers: { Accept: "application/vnd.github.raw+json" } });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GitHub said ${r.status}`);
  return decrypt(await r.text(), cfg.pass);
}
/** Encrypt and write a file to the repo (creates or replaces it). */
export async function writeEnc(cfg, name, obj, message) {
  const text = (await encrypt(obj, cfg.pass)) + "\n";
  for (let attempt = 0; attempt < 2; attempt++) {
    const cur = await gh(cfg, `/contents/${name}?ref=main&_=${Date.now()}`);
    const sha = cur.ok ? (await cur.json()).sha : undefined;
    const r = await gh(cfg, `/contents/${name}`, { method: "PUT", body: JSON.stringify({ message, content: btoa(text), sha, branch: "main" }) });
    if (r.ok) return;
    if (r.status !== 409 && r.status !== 422) throw new Error(`GitHub said ${r.status} while saving`);
  }
  throw new Error("Could not save (file kept changing).");
}

// ---------- SIS page reading (eng.asu.edu.eg; plain server-rendered HTML, read with regexes so it also works in the service worker) ----------
export const SIS = "https://eng.asu.edu.eg";
const clean = (s) => String(s).replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
  .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#0?39;/g, "'").replace(/\s+/g, " ").trim();
const CODE = /^[A-Z]{2,5}[0-9x]{2,4}[a-z]?$/;
const TERM = /^(Fall|Spring|Summer|Winter) \d{4}$/;

/** True when the HTML/URL is the login page rather than a signed-in page. */
export function looksLoggedOut(url, html) {
  try { if (/^\/(ar\/)?login\b/i.test(new URL(url).pathname)) return true; } catch (e) { /* not a URL */ }
  return /type=["']?password/i.test(html || "") && /captcha/i.test(html || "");
}
/** Profile link from any signed-in page: /users/<id>/profile */
export function profileUrl(html) {
  const m = /href="(?:https:\/\/eng\.asu\.edu\.eg)?(\/users\/\d+\/profile)"/.exec(html || "");
  return m ? SIS + m[1] : "";
}
/** My Courses page -> [{url, code, name, term}] for the current year. */
export function parseMyCourses(html) {
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
export function parseMarks(html) {
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
export function parseFinals(html) {
  const out = {};
  // A cell may not contain another row or table, so a wrapper row can never swallow the first real row.
  const TD = "<td[^>]*>(?:(?!<\\/?(?:td|tr|table)\\b)[\\s\\S])*?<\\/td>";
  const re = new RegExp(`<tr\\b[^>]*>\\s*((?:${TD}\\s*){6})<\\/tr>`, "g");
  for (let m; (m = re.exec(html || ""));) {
    const cells = (m[1].match(new RegExp(TD, "g")) || []).map(clean);
    const [code, name, term, grade, gpa] = cells;
    if (!CODE.test(code) || !TERM.test(term) || !grade) continue;
    out[`${code}|${term}`] = { code, name, term, grade, gpa };
  }
  return out;
}
// ---------- SIS bookkeeping (pure; shared by the background, the dashboard and the SIS page script) ----------
/** Marks/grades that are out but that you haven't looked at yet (seen = what you last saw). */
export function unseenSis(sis, seen) {
  const out = [];
  if (!sis || !sis.courses) return out;
  for (const [code, c] of Object.entries(sis.courses))
    for (const mk of c.marks || []) if (mk.value && seen[`${code}|${mk.label}`] !== mk.value) out.push(`${code}|${mk.label}`);
  for (const [k, f] of Object.entries(sis.finals || {})) if (seen[k] !== f.grade) out.push(k);
  return out;
}
/** First read ever: everything already out counts as seen. */
export function baseline(sis) {
  const seen = {};
  for (const [code, c] of Object.entries(sis.courses || {})) for (const mk of c.marks || []) if (mk.value) seen[`${code}|${mk.label}`] = mk.value;
  for (const [k, f] of Object.entries(sis.finals || {})) seen[k] = f.grade;
  return seen;
}
/** What changed between two reads, for the Grades tab's "Recent changes". */
export function changes(old, now) {
  const out = [], t = Date.now();
  if (!old || !old.courses) return out;
  for (const [code, c] of Object.entries(now.courses)) {
    const prev = ((old.courses[code] || {}).marks || []);
    for (const mk of c.marks) {
      const was = (prev.find((p) => p.label === mk.label) || {}).value || "";
      if (mk.value && mk.value !== was) out.push({ t, code, name: c.name, label: mk.label, was, now: mk.value, max: mk.max });
    }
  }
  for (const [k, f] of Object.entries(now.finals)) {
    const was = ((old.finals || {})[k] || {}).grade || "";
    if (f.grade !== was && Object.keys(old.finals || {}).length) out.push({ t, code: f.code, name: f.name, label: `Final grade (${f.term})`, was, now: f.grade });
  }
  return out;
}
/** Owner only: the shape the bot reads from sis.enc (it sends the Telegram messages). */
export function sisPages(sis) {
  const marks = {}, finals = {};
  for (const [code, c] of Object.entries(sis.courses || {}))
    for (const mk of c.marks || []) marks[`${code}|${mk.label}`] = [`${code} — ${c.name}`, mk.label, `${mk.value || "-"} / ${mk.max}`, c.url];
  for (const [k, f] of Object.entries(sis.finals || {}))
    finals[k] = [`${f.code} — ${f.name}`, "Final grade", `${f.grade}${f.gpa ? " · GPA " + f.gpa : ""} · ${f.term}`, sis.profile || ""];
  return {
    marks: { title: "Subject marks", kind: "marks", url: SIS + "/dashboard/my_courses", rows: marks },
    finals: { title: "Final grades", kind: "finals", url: sis.profile || "", rows: finals },
  };
}

export const eventId = (e) => `${e.t}|${e.cid}|${e.text}`;
