// Runs on the course pages of Moodle. Read-only: compact layout, phone fixes, "not submitted + time left" badges, download-subject zip.
(function () {
  "use strict";
  const pad = (n) => String(n).padStart(2, "0");
  // time left -> "2d 5h left" / "3h 20m left" / "overdue 1d 2h"
  function timeLeft(due, now) {
    let s = Math.round(due - now), late = s < 0; s = Math.abs(s);
    const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    const txt = d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${Math.max(m, 1)}m`;
    return { late, txt: late ? `overdue ${txt}` : `${txt} left`, urgent: !late && s < 86400 };
  }
  function cmidOf(url) { const m = /[?&]id=(\d+)/.exec(url || ""); return m ? m[1] : null; }
  function safeName(s) { return String(s || "file").replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "_").replace(/\s+/g, " ").trim().slice(0, 120) || "file"; }
  function nameFromDisposition(h) {
    if (!h) return null;
    let m = /filename\*=UTF-8''([^;]+)/i.exec(h); if (m) { try { return decodeURIComponent(m[1]); } catch (e) {} }
    m = /filename="?([^";]+)"?/i.exec(h); return m ? m[1] : null;
  }
  function nameFromUrl(u) { try { const p = new URL(u).pathname.split("/").filter(Boolean); return decodeURIComponent(p[p.length - 1] || "file"); } catch (e) { return "file"; } }
  if (typeof module !== "undefined") { module.exports = { timeLeft, cmidOf, safeName, nameFromDisposition, nameFromUrl }; }
  if (typeof window !== "undefined") window.LMSG_TOOLS = { timeLeft, cmidOf, safeName };
  if (typeof document === "undefined" || typeof chrome === "undefined" || !chrome.storage) return;
  if (window.top !== window) return;

  // ---------- Layout (compact + phone) ----------
  const CSS = `
  @media (max-width:767px){
    body.limitedwidth #page.drawers .main-inner, #page-content{padding-left:8px!important;padding-right:8px!important}
    .generaltable{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch}
    .generaltable th,.generaltable td{white-space:normal!important;word-break:break-word}
    .drawer-toggler .btn,.drawer-toggler button{width:38px!important;height:38px!important;padding:6px!important;opacity:.9}
    .btn-footer-popover{transform:scale(.8);transform-origin:bottom right;bottom:8px!important;right:8px!important}
    form[action*="removesubmission"] .btn,.singlebutton form .btn{margin-top:14px!important}
    #lmsg-bell{bottom:72px!important}
  }
  html[data-lmsg-layout=compact] li.activity{padding-top:2px!important;padding-bottom:2px!important;margin-top:0!important;margin-bottom:0!important}
  html[data-lmsg-layout=compact] li.activity .activity-item{padding:.25rem .5rem!important}
  html[data-lmsg-layout=compact] li.activity .activityiconcontainer{width:28px!important;height:28px!important;margin-right:.5rem!important;padding:3px!important}
  html[data-lmsg-layout=compact] li.activity .activity-header,html[data-lmsg-layout=compact] li.activity .activity-description,html[data-lmsg-layout=compact] li.activity .description{margin-top:0!important;margin-bottom:0!important;padding-top:0!important;padding-bottom:0!important}
  html[data-lmsg-layout=compact] .course-section{margin-bottom:.4rem!important;padding-bottom:0!important}
  html[data-lmsg-layout=compact] .course-section-header,html[data-lmsg-layout=compact] .section-item{padding-top:.25rem!important;padding-bottom:.25rem!important}
  html[data-lmsg-layout=compact] .section .content,html[data-lmsg-layout=compact] ul.section{margin-top:0!important;margin-bottom:0!important}
  html[data-lmsg-layout=compact] #page-header{margin-bottom:.4rem!important}
  html[data-lmsg-layout=compact] .page-header-headings h1{font-size:1.4rem!important}
  .lmsg-badge{display:inline-block;margin:2px 0 2px 8px;padding:1px 8px;border-radius:10px;font:600 12px/18px system-ui,sans-serif;background:#fff3cd;color:#664d03;border:1px solid #e6c65c;white-space:nowrap}
  .lmsg-badge.urgent{background:#ffe0e0;color:#8a1c1c;border-color:#e08a8a}
  .lmsg-badge.late{background:#8a1c1c;color:#fff;border-color:#8a1c1c}
  #lmsg-strip{margin:8px 0;padding:8px 12px;border-radius:8px;background:#fff8e1;border:1px solid #e6c65c;color:#4a3b00;font:14px system-ui,sans-serif}
  #lmsg-strip b{font-weight:700}#lmsg-strip a{color:inherit;text-decoration:underline}
  #lmsg-zip{margin:6px 0;padding:6px 12px;border-radius:6px;border:1px solid #2f80d6;background:#2f80d6;color:#fff;font:600 14px system-ui,sans-serif;cursor:pointer}
  #lmsg-zip[disabled]{opacity:.7;cursor:progress}`;
  const st = document.createElement("style"); st.id = "lmsg-tools-css"; st.textContent = CSS;
  (document.head || document.documentElement).appendChild(st);
  const setLayout = (v) => { if (v === "compact") document.documentElement.dataset.lmsgLayout = "compact"; else delete document.documentElement.dataset.lmsgLayout; };
  chrome.storage.local.get("lmsLayout", (v) => setLayout(v.lmsLayout));
  chrome.storage.onChanged.addListener((c) => { if (c.lmsLayout) setLayout(c.lmsLayout.newValue); });

  // ---------- Course page only ----------
  const cm = /\bcourse-(\d+)\b/.exec(document.body.className) || /[?&]id=(\d+)/.exec(location.search);
  if (!/\/course\/view\.php/.test(location.pathname) || !cm) return;
  const courseId = Number(cm[1]);

  function sesskey() {
    const a = document.querySelector('a[href*="logout.php?sesskey="]');
    if (a) { const m = /sesskey=([A-Za-z0-9]+)/.exec(a.href); if (m) return m[1]; }
    for (const s of document.scripts) { const m = /"sesskey":"([A-Za-z0-9]+)"/.exec(s.textContent || ""); if (m) return m[1]; }
    return null;
  }
  async function loadEvents() {
    const key = sesskey(); if (!key) return [];
    const method = "core_calendar_get_action_events_by_course";
    const now = Math.floor(Date.now() / 1000);
    const r = await fetch(`/lib/ajax/service.php?sesskey=${key}&info=${method}`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify([{ index: 0, methodname: method, args: { courseid: courseId, timesortfrom: now - 60 * 86400, limitnum: 100 } }]),
    });
    const j = await r.json();
    if (!j[0] || j[0].error) return [];
    return j[0].data.events || [];
  }
  async function badges() {
    let ev; try { ev = await loadEvents(); } catch (e) { return; }
    const now = Date.now() / 1000, todo = [];
    for (const e of ev) {
      if (e.modulename !== "assign" && e.modulename !== "quiz") continue;
      const id = cmidOf(e.url || (e.action && e.action.url));
      const due = e.timesort; if (!id || !due) continue;
      const t = timeLeft(due, now);
      const li = document.getElementById("module-" + id) || document.querySelector(`li.activity[data-id="${id}"]`);
      if (li && !li.querySelector(".lmsg-badge")) {
        const b = document.createElement("span");
        b.className = "lmsg-badge" + (t.late ? " late" : t.urgent ? " urgent" : "");
        b.textContent = `Not submitted · ${t.txt}`;
        const anchor = li.querySelector(".activityname, .instancename, a.aalink") || li;
        (anchor.parentNode || li).insertBefore(b, anchor.nextSibling);
      }
      todo.push({ name: e.name, url: e.url, due, t });
    }
    if (!todo.length || document.getElementById("lmsg-strip")) return;
    todo.sort((a, b) => a.due - b.due);
    const strip = document.createElement("div"); strip.id = "lmsg-strip";
    const items = todo.slice(0, 5).map((x) => {
      const a = document.createElement("a"); a.href = x.url; a.textContent = x.name; return [a, ` — ${x.t.txt}`];
    });
    strip.append("⏰ Still not submitted: ");
    items.forEach(([a, tx], i) => { if (i) strip.append(" · "); strip.append(a, tx); });
    const host = document.querySelector("#region-main, [role=main]") || document.body;
    host.insertBefore(strip, host.firstChild);
  }

  // ---------- Download whole subject ----------
  async function fetchFile(url) {
    const r = await fetch(url, { credentials: "same-origin" }); if (!r.ok) throw new Error(r.status);
    const ct = r.headers.get("content-type") || "";
    if (/text\/html/.test(ct)) { // resource page that embeds the file
      const doc = new DOMParser().parseFromString(await r.text(), "text/html");
      const el = doc.querySelector('a[href*="pluginfile.php"], object[data*="pluginfile.php"], iframe[src*="pluginfile.php"], embed[src*="pluginfile.php"]');
      const u = el && (el.getAttribute("href") || el.getAttribute("data") || el.getAttribute("src"));
      if (!u) return [];
      const abs = new URL(u, r.url).href;
      return [await oneFile(abs)];
    }
    return [{ name: nameFromDisposition(r.headers.get("content-disposition")) || nameFromUrl(r.url), blob: await r.blob() }];
  }
  async function oneFile(u) {
    const r = await fetch(u, { credentials: "same-origin" }); if (!r.ok) throw new Error(r.status);
    return { name: nameFromDisposition(r.headers.get("content-disposition")) || nameFromUrl(r.url), blob: await r.blob() };
  }
  async function folderFiles(url) {
    const r = await fetch(url, { credentials: "same-origin" }); if (!r.ok) return [];
    const doc = new DOMParser().parseFromString(await r.text(), "text/html");
    const links = [...new Set([...doc.querySelectorAll('a[href*="pluginfile.php"]')].map((a) => new URL(a.getAttribute("href"), r.url).href))];
    const out = []; for (const l of links) { try { out.push(await oneFile(l)); } catch (e) {} } return out;
  }
  async function downloadAll(btn) {
    if (typeof JSZip === "undefined") { btn.textContent = "Zip library missing"; return; }
    const reset = () => { btn.disabled = false; btn.textContent = "⬇ Download all files (zip)"; };
    const zip = new JSZip(), used = new Set();
    const items = [];
    document.querySelectorAll("li.activity.modtype_resource, li.activity.modtype_folder").forEach((li) => {
      const a = li.querySelector("a.aalink, a[href*='/mod/']"); if (!a) return;
      const sec = li.closest("li.section, .course-section"); 
      const secName = safeName((sec && (sec.getAttribute("data-sectionname") || (sec.querySelector(".sectionname, .course-section-header h3, h3") || {}).textContent)) || "Section");
      items.push({ url: a.href, folder: li.classList.contains("modtype_folder"), sec: secName });
    });
    if (!items.length) { btn.textContent = "No files found"; setTimeout(reset, 2500); return; }
    btn.disabled = true; let n = 0, fail = 0;
    for (const it of items) {
      btn.textContent = `Downloading ${++n}/${items.length}…`;
      try {
        const files = it.folder ? await folderFiles(it.url) : await fetchFile(it.url);
        for (const f of files) {
          let p = it.sec + "/" + safeName(f.name), k = 1;
          while (used.has(p)) p = it.sec + "/" + (k++) + "_" + safeName(f.name);
          used.add(p); zip.file(p, f.blob);
        }
      } catch (e) { fail++; }
    }
    btn.textContent = "Packing zip…";
    const blob = await zip.generateAsync({ type: "blob" });
    const title = safeName((document.querySelector(".page-header-headings h1, h1") || {}).textContent || "subject");
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = title + ".zip";
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    btn.disabled = false; btn.textContent = fail ? `Done (${fail} failed) — download again` : "⬇ Download all files (zip)";
  }
  function addZipButton() {
    if (document.getElementById("lmsg-zip")) return;
    const b = document.createElement("button"); b.id = "lmsg-zip"; b.type = "button"; b.textContent = "⬇ Download all files (zip)";
    b.onclick = () => downloadAll(b);
    const host = document.querySelector("#region-main, [role=main]") || document.body;
    host.insertBefore(b, host.firstChild);
  }
  addZipButton();
  badges();
})();
