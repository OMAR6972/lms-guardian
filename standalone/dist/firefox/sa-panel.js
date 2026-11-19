// Standalone LMS Guardian, Moodle side: one floating button -> panel with Deadlines (not submitted yet), GPA calculator, Settings.
// Everything stays in this browser. No bot, no token, no account of ours. Read-only: it only reads pages you can already see.
(function () {
  "use strict";
  if (window.top !== window || typeof chrome === "undefined" || !chrome.storage) return;
  const st = {
    get: (k) => new Promise((r) => chrome.storage.local.get(k, (v) => r(v || {}))),
    set: (o) => new Promise((r) => chrome.storage.local.set(o, () => r())),
  };
  const THEMES = [["off", "Off (normal)"], ["dark", "Dark"], ["dim", "Dim (softer)"], ["cyberpunk", "Cyberpunk"], ["synthwave", "Synthwave"], ["matrix", "Matrix"], ["midnight", "Midnight"], ["auto", "Auto (follow my device)"]];
  const CSS = `:host{all:initial}
*{box-sizing:border-box}
.panel{position:fixed;right:18px;bottom:148px;z-index:2147483646;width:min(430px,calc(100vw - 36px));height:min(640px,calc(100vh - 176px));background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:16px;box-shadow:0 8px 30px rgba(0,0,0,.35);display:flex;flex-direction:column;overflow:hidden;font:14px system-ui,sans-serif;
--bg:#fff;--panel:#fff;--panel2:#eef5fc;--fg:#10243a;--mute:#5b7491;--line:#d5e3f3;--acc:#2f80d6;--acc-fg:#fff;--bad:#b3261e}
.panel.dark{--bg:#0d1824;--panel:#14263a;--panel2:#1b3149;--fg:#eaf3fc;--mute:#97aec6;--line:#25405c;--acc:#6db4f5;--acc-fg:#06223e;--bad:#ff9a92}
.panel[hidden]{display:none}
.hd{display:flex;align-items:center;gap:6px;padding:8px 10px;border-bottom:1px solid var(--line)}
.hd b{flex:1}.hd button{border:0;background:none;color:var(--fg);font-size:18px;cursor:pointer}
.tabs{display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid var(--line)}
.tabs button{flex:1;border:0;background:none;color:var(--fg);padding:6px 4px;border-radius:8px;font:inherit;cursor:pointer}
.tabs button[aria-pressed=true]{background:var(--acc);color:var(--acc-fg);font-weight:700}
.body{flex:1;overflow:auto;padding:10px 12px}
.card{border:1px solid var(--line);background:var(--panel2);border-radius:10px;padding:8px 10px;margin-bottom:8px}
.card a{color:var(--acc)}.mute{color:var(--mute);font-size:.84rem}
.late{color:var(--bad);font-weight:700}
select{font:inherit;color:var(--fg);background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:5px}
label{display:block;margin:10px 0 4px;font-weight:600}`;
  const host = document.createElement("div"); host.id = "lmsg-host";
  const sh = host.attachShadow({ mode: "open" });
  const style = document.createElement("style"); style.textContent = CSS;
  const panel = document.createElement("div"); panel.className = "panel"; panel.hidden = true;
  panel.innerHTML = `<div class="hd"><b>🛡️ LMS Guardian</b><button data-x title="Close">✕</button></div>
<div class="tabs"><button data-t="due" aria-pressed="true">Deadlines</button><button data-t="gpa" aria-pressed="false">GPA</button><button data-t="set" aria-pressed="false">Settings</button></div><div class="body"></div>`;
  sh.append(style, panel);
  const body = panel.querySelector(".body");
  let tab = "due";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const safe = (u) => (/^https:\/\/lms\.eng\.asu\.edu\.eg\//.test(u || "") ? u : "");

  function sesskey() {
    const a = document.querySelector('a[href*="logout.php?sesskey="]');
    if (a) { const m = /sesskey=([A-Za-z0-9]+)/.exec(a.href); if (m) return m[1]; }
    for (const s of document.scripts) { const m = /"sesskey":"([A-Za-z0-9]+)"/.exec(s.textContent || ""); if (m) return m[1]; }
    return null;
  }
  async function actionEvents() {
    const key = sesskey(); if (!key) throw new Error("Open a normal Moodle page while logged in, then try again.");
    const method = "core_calendar_get_action_events_by_timesort";
    const ac = new AbortController(); setTimeout(() => ac.abort(), 20000);
    const r = await fetch(`/lib/ajax/service.php?sesskey=${key}&info=${method}`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, signal: ac.signal,
      body: JSON.stringify([{ index: 0, methodname: method, args: { timesortfrom: Math.floor(Date.now() / 1000) - 45 * 86400, limitnum: 60, limittononsuspendedevents: true } }]),
    });
    const j = await r.json();
    if (!j[0] || j[0].error) throw new Error("Moodle did not return your deadlines.");
    return j[0].data.events || [];
  }
  const T = () => window.LMSG_TOOLS;
  async function showDue() {
    body.innerHTML = '<div class="mute">Loading…</div>';
    try {
      const ev = (await actionEvents()).filter((e) => e.timesort).sort((a, b) => a.timesort - b.timesort), now = Date.now() / 1000;
      body.innerHTML = '<div class="mute" style="margin-bottom:8px">Things Moodle says are still waiting for you (not submitted yet).</div>' + (ev.length ? ev.map((e) => {
        const t = T().timeLeft(e.timesort, now), u = safe(e.url || (e.action && e.action.url));
        const c = e.course && (e.course.fullname || e.course.shortname);
        return `<div class="card"><b>${esc(e.name)}</b><div class="mute">${esc(c || "")}</div><div class="${t.late ? "late" : ""}">${t.late ? "⚠ " : "⏰ "}${esc(t.txt)} · ${esc(new Date(e.timesort * 1000).toLocaleString())}</div>${u ? `<a href="${esc(u)}">Open</a>` : ""}</div>`;
      }).join("") : '<div class="card">Nothing is waiting. 🎉</div>');
    } catch (e) { body.innerHTML = `<div class="card">Couldn't load the full deadline list: the LMS didn't answer (it may be slow or busy). Open a course page instead: the “Not submitted” badges there use a backup method. ${/sesskey|Open a normal/.test(e.message) ? esc(e.message) : ""}</div><button id="retry">Try again</button>`; const rb = body.querySelector("#retry"); if (rb) rb.onclick = showDue; }
  }
  async function showSet() {
    const v = await st.get(["lmsTheme", "lmsLayout"]);
    body.innerHTML = `<label>Moodle theme</label><select id="th">${THEMES.map(([k, n]) => `<option value="${k}"${k === (v.lmsTheme || "off") ? " selected" : ""}>${n}</option>`).join("")}</select>
<label>Moodle layout</label><select id="ly"><option value="normal">Normal</option><option value="compact"${v.lmsLayout === "compact" ? " selected" : ""}>Compact</option></select>
<div class="card mute" style="margin-top:14px">This add-on reads pages you can already see and saves your choices in this browser only. It never sends anything anywhere and never changes or submits anything on Moodle or the SIS.</div>`;
    body.querySelector("#th").onchange = (e) => { st.set({ lmsTheme: e.target.value }); paintTheme(e.target.value); };
    body.querySelector("#ly").onchange = (e) => st.set({ lmsLayout: e.target.value });
  }
  async function showGpa() {
    body.innerHTML = "";
    const box = document.createElement("div"); body.append(box);
    window.LMSG_GPA_UI.mount(box, {
      load: async () => (await st.get("gpaRows")).gpaRows || [],
      save: (rows) => st.set({ gpaRows: rows }),
      sis: async () => {
        const v = await st.get(["sisFinals", "sisCourses", "sisProfile", "sisAt"]);
        if (!v.sisFinals || !Object.keys(v.sisFinals).length)
          return { hint: v.sisProfile ? "No grades saved yet. Open your SIS profile page (while logged in) once, then come back and press the button." : "To fill this from your SIS: log in to the SIS (eng.asu.edu.eg) and open your profile page once. It is saved here automatically." };
        return { finals: v.sisFinals, courses: v.sisCourses, hint: `SIS grades saved ${new Date(v.sisAt).toLocaleDateString()} (${Object.keys(v.sisFinals).length} subjects). Open your SIS profile again to refresh. This term's subjects come in empty so you can try grades.` };
      },
    });
  }
  function paintTheme(choice) {
    const dark = choice === "auto" ? matchMedia("(prefers-color-scheme: dark)").matches : choice && choice !== "off";
    panel.classList.toggle("dark", !!dark);
  }
  function render() {
    panel.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.t === tab));
    (tab === "due" ? showDue : tab === "gpa" ? showGpa : showSet)();
  }
  panel.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => { tab = b.dataset.t; render(); });
  panel.querySelector("[data-x]").onclick = () => { panel.hidden = true; };
  addEventListener("keydown", (e) => { if (e.key === "Escape") panel.hidden = true; });

  const bell = document.createElement("button");
  bell.id = "lmsg-bell"; bell.textContent = "🛡️"; bell.setAttribute("aria-label", "LMS Guardian");
  bell.style.cssText = "position:fixed;right:18px;bottom:84px;z-index:2147483646;width:54px;height:54px;border-radius:50%;border:0;background:#2f80d6;color:#fff;font:700 22px system-ui;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.3)";
  bell.onclick = () => { panel.hidden = !panel.hidden; if (!panel.hidden) render(); };
  document.body.append(host, bell);
  st.get("lmsTheme").then((v) => paintTheme(v.lmsTheme || "off"));
})();
