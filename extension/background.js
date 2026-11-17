// Service worker: unread badge, and SIS marks checks while Chrome is open.
// SIS: uses your own signed-in session (you log in yourself; the CAPTCHA is never touched). A light ping every
// 2 minutes keeps an idle session alive; a full read of your subjects and final grades runs every 10 minutes,
// and right away when you open any SIS page. Nothing is read from the SIS except marks and grades.
import { settings, readFeed, readEnc, writeEnc, REPO, eventId, SIS, looksLoggedOut, profileUrl, parseMyCourses, parseMarks, parseFinals,
  unseenSis, baseline, changes, sisPages, blockedByFees, parseAdvisorBadge, parseAdvisorThread, newAdvisor } from "./lib.js";

const PING_MINUTES = 2;
const FULL_EVERY_MS = 10 * 60e3;
const VISIT_FRESH_MS = 2 * 60e3;   // opening a SIS page re-reads if the data is older than this
const HEARTBEAT_MS = 3 * 3600e3;   // re-send unchanged SIS data to the bot this often
const LOG_MAX = 150;

function schedule() {
  chrome.alarms.create("tick", { periodInMinutes: 5 });
  chrome.alarms.create("sis", { periodInMinutes: PING_MINUTES });
}
chrome.runtime.onInstalled.addListener(() => { schedule(); tick(); sisTick(true); });
chrome.runtime.onStartup.addListener(() => { schedule(); tick(); sisTick(true); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "tick") tick(); else if (a.name === "sis") sisTick(false); });

async function tick() {
  const cfg = await settings();
  if (cfg.code) await refreshBadge(cfg).catch(() => {});
}

// ---------- badge: unread updates + SIS marks you haven't looked at ----------
async function refreshBadge(cfg) {
  cfg = cfg || (await settings());
  let n = 0;
  if (cfg.code) {
    try {
      const st = await readFeed(cfg.code);
      const { read = {} } = await chrome.storage.local.get("read");
      n = (st.history || []).filter((e) => !read[eventId(e)]).length;
      await chrome.storage.local.set({ unread: n });
    } catch (e) { const v = await chrome.storage.local.get("unread"); n = v.unread || 0; }
  }
  const { sis, sisSeen = {}, advSeen } = await chrome.storage.local.get(["sis", "sisSeen", "advSeen"]);
  const sisNew = unseenSis(sis, sisSeen).length + newAdvisor(sis && sis.advisor, advSeen).length;
  await chrome.storage.local.set({ sisUnseen: sisNew });
  const total = n + sisNew;
  chrome.action.setBadgeBackgroundColor({ color: "#2f80d6" });
  chrome.action.setBadgeText({ text: total ? String(Math.min(total, 99)) : "" });
}

// ---------- SIS ----------
let running = null;
async function get(path) {
  const r = await fetch(path.startsWith("http") ? path : SIS + path, { credentials: "include", cache: "no-store", redirect: "follow" });
  const html = await r.text();
  if (looksLoggedOut(r.url || path, html)) { const e = new Error("logged out"); e.loggedOut = true; throw e; }
  if (!/payments\/student_fees/.test(path) && blockedByFees(r.url || path, html)) { const e = new Error("fees"); e.fees = true; throw e; }
  if (!r.ok) throw new Error(`SIS answered ${r.status}`);
  return html;
}

async function sisTick(force) {
  const { sis } = await chrome.storage.local.get("sis");
  if (!force && (!sis || sis.status === "logged_out" || sis.status === "never")) {
    // Not logged in: don't knock on the door every 2 minutes; the next SIS page you open restarts checks.
    return;
  }
  const due = force || !sis.fullAt || Date.now() - sis.fullAt >= FULL_EVERY_MS;
  return due ? sisFull() : sisPing();
}

async function sisPing() {
  try {
    await get("/dashboard");
    const { sis } = await chrome.storage.local.get("sis");
    await patch({ status: sis && sis.status === "fees" ? "fees" : "ok", pingAt: Date.now() });
  }
  catch (e) { await patch({ status: e.loggedOut ? "logged_out" : "error", error: e.loggedOut ? "" : e.message, pingAt: Date.now() }); }
}

async function patch(fields) {
  const { sis = { status: "never" } } = await chrome.storage.local.get("sis");
  Object.assign(sis, fields);
  await chrome.storage.local.set({ sis });
  return sis;
}

/** Read all current subjects' marks and all final grades. One run at a time. */
function sisFull() {
  if (!running) running = sisFullInner().finally(() => { running = null; });
  return running;
}
async function sisFullInner() {
  const { sis: old = { status: "never" }, sisSeen, sisLog = [], advSeen } = await chrome.storage.local.get(["sis", "sisSeen", "sisLog", "advSeen"]);
  try {
    const dash = await get("/dashboard");
    const profile = profileUrl(dash) || old.profile || "";
    const ownId = (/\/users\/(\d+)\/profile/.exec(profile) || [])[1] || "";
    // Advisor chat: its own try, so a problem here never stops marks, and a fees block never stops this.
    let advisor = old.advisor;
    try {
      const thread = parseAdvisorThread(await get("/study/studies/discuss"), ownId);
      advisor = { badge: parseAdvisorBadge(dash), messages: thread.slice(0, 40), at: Date.now() };
      if (!advSeen) await chrome.storage.local.set({ advSeen: thread.map((x) => x.key) }); // first read: nothing is new
    } catch (e) { if (e.loggedOut) throw e; if (advisor) advisor = { ...advisor, badge: parseAdvisorBadge(dash) }; }
    let sis;
    try {
      const list = parseMyCourses(await get("/dashboard/my_courses"));
      const courses = {};
      for (const c of list) {
        const marks = parseMarks(await get(c.url));
        courses[c.code] = { name: c.name, term: c.term, url: c.url, marks };
      }
      let finals = old.finals || {};
      if (profile) {
        const f = parseFinals(await get(profile));
        if (Object.keys(f).length || !Object.keys(finals).length) finals = f; // an empty read never wipes known grades
      }
      if (!list.length && old.courses && Object.keys(old.courses).length) throw new Error("subject list read empty");
      sis = { status: "ok", error: "", fullAt: Date.now(), pingAt: Date.now(), profile, courses, finals, advisor };
    } catch (e) {
      if (!e.fees) throw e;
      // Unpaid fees: the faculty hides all grade pages. Keep everything read before and say why nothing new can be read.
      sis = { ...old, status: "fees", error: "", fullAt: Date.now(), pingAt: Date.now(), profile, advisor };
    }
    // what changed since the last read (kept for the Grades tab)
    const log = sisLog.concat(sis.status === "ok" ? changes(old, sis) : []).slice(-LOG_MAX);
    const save = { sis, sisLog: log };
    if (!sisSeen) save.sisSeen = baseline(sis); // first read ever: nothing counts as new
    await chrome.storage.local.set(save);
    const cfg = await settings();
    if (sis.status === "ok" && cfg.token && cfg.pass) await pushSis(cfg, sis).catch((e) => console.warn("sis push:", e.message));
    await refreshBadge(cfg);
    return sis;
  } catch (e) {
    return patch({ status: e.loggedOut ? "logged_out" : "error", error: e.loggedOut ? "" : e.message });
  }
}


async function pushSis(cfg, sis) {
  const pages = sisPages(sis), body = JSON.stringify(pages);
  const { sisPushed = {} } = await chrome.storage.local.get("sisPushed");
  if (sisPushed.body === body && Date.now() - (sisPushed.at || 0) < HEARTBEAT_MS) return;
  await writeEnc({ ...cfg, repo: cfg.repo || REPO }, "sis.enc", { v: 2, seen: Math.floor(Date.now() / 1000), status: "ok", pages }, "SIS snapshot");
  await chrome.storage.local.set({ sisPushed: { body, at: Date.now() } });
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  (async () => {
    if (msg.type === "sisVisit") {
      // You opened a SIS page while logged in: read now if the data is a bit old.
      const { sis } = await chrome.storage.local.get("sis");
      if (!sis || sis.status !== "ok" || !sis.fullAt || Date.now() - sis.fullAt > VISIT_FRESH_MS) await sisFull();
      reply({});
    } else if (msg.type === "sisCheckNow") {
      reply(await sisFull());
    } else if (msg.type === "checkKeys") {
      try {
        const st = await readEnc({ repo: REPO, token: msg.token, pass: msg.pass }, "state.enc");
        reply({ ok: !!st });
      } catch (e) { reply({ ok: false, error: e.message }); }
    } else if (msg.type === "refresh") {
      await refreshBadge().catch(() => {});
      reply({});
    } else reply({});
  })();
  return true; // async reply
});
