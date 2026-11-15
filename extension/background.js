// Service worker: keeps the unread badge fresh.
// The SIS part below is dormant while SIS is skipped: no SIS page script is loaded and it needs owner keys.
import { settings, readFeed, writeEnc, parseTables, looksLoggedOut, pageKey, eventId } from "./lib.js";

const CHECK_MINUTES = 5;        // how often watched SIS pages are re-read while the browser is open
const HEARTBEAT_MS = 3 * 3600e3; // re-send unchanged data this often so the bot knows the extension is alive

chrome.runtime.onInstalled.addListener(() => { chrome.alarms.create("tick", { periodInMinutes: CHECK_MINUTES }); tick(); });
chrome.runtime.onStartup.addListener(() => chrome.alarms.create("tick", { periodInMinutes: CHECK_MINUTES }));
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "tick") tick(); });

async function ready() {
  const cfg = await settings();
  return cfg.code ? cfg : null;
}
const sisReady = (cfg) => cfg && cfg.token && cfg.pass && cfg.repo;

async function tick() {
  const cfg = await ready();
  if (!cfg) return;
  await refreshBadge(cfg).catch(() => {});
  if (sisReady(cfg)) await recheckSis(cfg).catch((e) => console.warn("sis recheck:", e.message));
}

async function refreshBadge(cfg) {
  const st = await readFeed(cfg.code);
  const { read = {} } = await chrome.storage.local.get("read");
  const n = ((st && st.history) || []).filter((e) => !read[eventId(e)]).length;
  await chrome.storage.local.set({ unread: n });
  chrome.action.setBadgeBackgroundColor({ color: "#2f80d6" });
  chrome.action.setBadgeText({ text: n ? String(Math.min(n, 99)) : "" });
}

// ---------- SIS ----------
async function recordPage(url, title, html) {
  const { sis = { status: "ok", pages: {} } } = await chrome.storage.local.get("sis");
  if (looksLoggedOut(url, html)) { sis.status = "logged_out"; }
  else {
    const rows = parseTables(html);
    sis.status = "ok";
    sis.seen = Math.floor(Date.now() / 1000);
    if (Object.keys(rows).length) sis.pages[pageKey(url)] = { title: title || "SIS", url, rows };
  }
  await chrome.storage.local.set({ sis });
  return sis;
}

async function pushSis(cfg, sis) {
  const body = JSON.stringify({ status: sis.status, pages: sis.pages });
  const { sisPushed = {} } = await chrome.storage.local.get("sisPushed");
  if (sisPushed.body === body && Date.now() - (sisPushed.at || 0) < HEARTBEAT_MS) return;
  await writeEnc(cfg, "sis.enc", { v: 1, seen: sis.seen || 0, status: sis.status, pages: sis.pages }, "SIS snapshot");
  await chrome.storage.local.set({ sisPushed: { body, at: Date.now() } });
}

async function recheckSis(cfg) {
  const { sisWatch = [] } = await chrome.storage.local.get("sisWatch");
  if (!sisWatch.length) return;
  let sis;
  for (const url of sisWatch) {
    // Uses your own signed-in session cookies. If the session ended this lands on the login page.
    const r = await fetch(url, { credentials: "include", redirect: "follow", cache: "no-store" });
    sis = await recordPage(r.url || url, "", await r.text());
    if (sis.status === "logged_out") break;
  }
  if (sis) await pushSis(cfg, sis);
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    const cfg = await ready();
    if (msg.type === "sisPage") {
      const { sisWatch = [] } = await chrome.storage.local.get("sisWatch");
      if (!sisWatch.includes(msg.url)) return reply({ watching: false });
      const sis = await recordPage(msg.url, msg.title, msg.html);
      if (sisReady(cfg)) await pushSis(cfg, sis).catch((e) => console.warn(e.message));
      reply({ watching: true, rows: Object.keys((sis.pages[pageKey(msg.url)] || {}).rows || {}).length });
    } else if (msg.type === "sisToggle") {
      let { sisWatch = [] } = await chrome.storage.local.get("sisWatch");
      sisWatch = sisWatch.includes(msg.url) ? sisWatch.filter((u) => u !== msg.url) : sisWatch.concat(msg.url);
      await chrome.storage.local.set({ sisWatch });
      reply({ watching: sisWatch.includes(msg.url) });
    } else if (msg.type === "refresh") {
      if (cfg) await refreshBadge(cfg).catch(() => {});
      reply({});
    } else reply({});
  })();
  return true; // async reply
});
