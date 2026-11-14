// Shared helpers: encryption (same format as lms/vault.py), GitHub file access, SIS table reading.
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

export function settings() {
  return chrome.storage.local.get(["token", "pass", "repo"]);
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

// ---------- SIS page reading ----------
const clean = (s) => s.replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/&amp;/gi, "&").replace(/&lt;/gi, "<")
  .replace(/&gt;/gi, ">").replace(/&quot;/gi, '"').replace(/&#0?39;/g, "'").replace(/\s+/g, " ").trim();

/** True when the HTML/URL is the login page rather than a signed-in page. */
export function looksLoggedOut(url, html) {
  if (/\/login(\b|\/|\?|$)/i.test(new URL(url).pathname)) return true;
  return /type=["']?password/i.test(html) && /captcha/i.test(html);
}
/** Every table row on the page as {rowKey: [cells]}. Generic on purpose: tuned once the real pages are seen. */
export function parseTables(html) {
  const rows = {}, seen = {};
  const body = html.replace(/<(script|style|noscript)[\s\S]*?<\/\1>/gi, "");
  const tables = body.match(/<table[\s\S]*?<\/table>/gi) || [];
  tables.slice(0, 40).forEach((t, ti) => {
    (t.match(/<tr[\s\S]*?<\/tr>/gi) || []).slice(0, 400).forEach((tr) => {
      if (!/<td/i.test(tr)) return; // header rows carry no values
      const cells = (tr.match(/<t[dh][\s\S]*?<\/t[dh]>/gi) || []).slice(0, 14).map(clean);
      const named = cells.filter(Boolean);
      if (named.length < 2) return;
      let k = `t${ti}|${named[0].slice(0, 80)}`;
      seen[k] = (seen[k] || 0) + 1;
      if (seen[k] > 1) k += ` #${seen[k]}`;
      rows[k] = cells;
    });
  });
  return rows;
}
export const pageKey = (url) => { const u = new URL(url); return (u.pathname + u.search).replace(/[^\w/?=&-]/g, "").slice(0, 120); };
export const eventId = (e) => `${e.t}|${e.cid}|${e.text}`;
