import { settings, readFeed, eventId, unseenSis, baseline, newAdvisor } from "./lib.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CAT = { materials: "📄 Materials", edits: "🔄 Edits", assignments: "📝 Assignments", quizzes: "❓ Quizzes", posts: "💬 Forum posts", grades: "🎯 Moodle grades", sis: "🎓 SIS grades" };
const S = { st: null, read: {}, visits: [], tab: "new" };
const when = (t) => new Date(t * 1000).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const full = (cid) => { const i = cid == null ? null : S.st.course_info[String(cid)]; return cid == null ? "SIS grades" : i ? `${i.code} — ${i.name}` : `course ${cid}`; };
const safeUrl = (u) => (/^https:\/\//.test(u || "") ? u : "");

function events() { return (S.st.history || []).slice().reverse(); }

function evCard(e) {
  const id = eventId(e), unread = !S.read[id], u = safeUrl(e.url);
  return `<div class="card ev${unread ? " unread" : ""}" data-id="${esc(id)}">
    <span class="t">${esc(e.text)}</span><span class="mute">${esc(full(e.cid))}</span>
    <span class="mute">${esc(CAT[e.cat] || "")} · ${esc(when(e.t))}${u ? ` · <a href="${esc(u)}" target="_blank" rel="noopener">Open</a>` : ""}</span></div>`;
}

function render() {
  const list = $("list"), all = events();
  $("filters").hidden = S.tab !== "all";
  $("visitRow").hidden = S.tab !== "new" || S.visits.length < 2;
  const unread = all.filter((e) => !S.read[eventId(e)]).length;
  $("count").textContent = unread ? `${unread} unread` : "all read";
  $("markAll").hidden = !unread;
  if (S.tab === "new") {
    const i = +$("visit").value || 0, from = S.visits[i + 1] || 0, to = i === 0 ? Infinity : S.visits[i];
    const ev = all.filter((e) => e.t * 1000 > from && e.t * 1000 <= to);
    list.innerHTML = ev.length ? ev.map(evCard).join("") : `<div class="card mute">Nothing new ${from ? "since " + new Date(from).toLocaleString() : "yet"}.</div>`;
  } else if (S.tab === "all") {
    const q = $("q").value.trim().toLowerCase(), c = $("fCourse").value, k = $("fCat").value, r = $("fRead").value;
    const d = $("fDate").value ? new Date($("fDate").value).getTime() / 1000 : 0;
    const ev = all.filter((e) => (!q || (e.text + " " + full(e.cid)).toLowerCase().includes(q)) && (!c || String(e.cid) === c)
      && (!k || e.cat === k) && (!r || !S.read[eventId(e)]) && e.t >= d);
    list.innerHTML = ev.length ? ev.map(evCard).join("") : '<div class="card mute">Nothing matches.</div>';
  } else if (S.tab === "due") {
    const now = Date.now() / 1000, items = [];
    for (const [cid, snap] of Object.entries(S.st.courses || {})) {
      for (const a of Object.values(snap.assigns || {})) if (a.due > now) items.push([a.due, "📝", a.name, "Due", cid, a.url]);
      for (const z of Object.values(snap.quizzes || {})) if (z.close > now) items.push([z.close, "❓", z.name, "Closes", cid, z.url]);
    }
    items.sort((a, b) => a[0] - b[0]);
    list.innerHTML = items.length ? items.map(([t, ic, name, word, cid, url]) => {
      const days = Math.floor((t - now) / 86400), u = safeUrl(url);
      return `<div class="card ev"><span class="t">${ic} ${esc(name)}</span><span class="mute">${esc(full(cid))}</span>
        <span class="mute">${word} ${esc(when(t))} · in ${days ? days + " d" : Math.max(1, Math.round((t - now) / 3600)) + " h"}${u ? ` · <a href="${esc(u)}" target="_blank" rel="noopener">Open</a>` : ""}</span></div>`;
    }).join("") : '<div class="card mute">No upcoming deadlines in tracked subjects.</div>';
  } else {
    renderGrades(list);
  }
}

const ago = (ms) => { const m = Math.round((Date.now() - ms) / 60000); return !ms ? "never" : m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const LABEL_ORDER = ["Midterm", "Activities", "Practical"];

function sisStatus(sis) {
  if (!sis || sis.status === "never" || !sis.fullAt)
    return '<div class="card mute">🎓 SIS marks: not read yet. Log in to the SIS in this browser and open any page; your marks appear here within a minute.</div>';
  const when = ago(sis.fullAt), btn = ' <button class="link" id="sisNow">Check now</button>';
  if (sis.status === "logged_out")
    return `<div class="card mute">🎓 You're logged out of the SIS, so checks are paused. Showing what was read ${esc(when)}. Log in to the SIS and they resume by themselves.</div>`;
  if (sis.status === "fees")
    return `<div class="card mute">🎓 The SIS is hiding your grades: it says you can't use the grade pages until the tuition fees are paid, so nothing new can be read. Showing what was read before. Checks keep running and resume by themselves once the SIS lets you in again.<br>${btn}</div>`;
  if (sis.status === "error")
    return `<div class="card mute">🎓 The last SIS read failed (${esc(sis.error || "no answer")}). Showing what was read ${esc(when)}.${btn}</div>`;
  return `<div class="row between mute" style="margin-bottom:6px"><span>🎓 SIS marks · read ${esc(when)}</span>${btn}</div>`;
}

async function renderGrades(list) {
  const { sis, sisSeen = {}, sisLog = [], advSeen } = await chrome.storage.local.get(["sis", "sisSeen", "sisLog", "advSeen"]);
  if (S.tab !== "grades") return;
  const unseen = new Set(unseenSis(sis, sisSeen));
  let html = sisStatus(sis);
  const adv = sis && sis.advisor, advNew = new Set(newAdvisor(adv, advSeen).map((x) => x.key));
  if (adv && (adv.messages || []).length) {
    const last = adv.messages.slice(0, 3);
    html += '<div class="card"><b>💬 Your advisor</b>' + (adv.badge ? ` <span class="mute">· ${adv.badge} unread on the SIS</span>` : "") +
      last.map((x) => `<div style="margin-top:6px${advNew.has(x.key) ? ";background:#fff1bf;color:#10243a;border-radius:6px;padding:4px" : ""}"><span class="mute">${x.mine ? "You" : esc(x.who)} · ${esc(x.when)}</span><br>${esc(x.text)}</div>`).join("") +
      '<div style="margin-top:6px"><a href="https://eng.asu.edu.eg/study/studies/discuss" target="_blank">Open the conversation</a></div></div>';
  }
  const courses = (sis && sis.courses) || {};
  const codes = Object.keys(courses).sort();
  if (codes.length) {
    const labels = [];
    codes.forEach((c) => courses[c].marks.forEach((m) => { if (!labels.includes(m.label)) labels.push(m.label); }));
    labels.sort((a, b) => ((LABEL_ORDER.indexOf(a) + 1) || 99) - ((LABEL_ORDER.indexOf(b) + 1) || 99));
    html += '<div class="card" style="overflow-x:auto"><table class="marks"><thead><tr><th>Subject</th>' + labels.map((l) => `<th>${esc(l)}</th>`).join("") + "<th>Final</th></tr></thead><tbody>";
    for (const code of codes) {
      const c = courses[code];
      html += `<tr><td><a href="${esc(c.url)}" target="_blank" rel="noopener" style="color:inherit;text-decoration:none"><b>${esc(code)}</b> — ${esc(c.name)}</a></td>`;
      for (const l of labels) {
        const m = c.marks.find((x) => x.label === l), key = `${code}|${l}`;
        if (!m) { html += '<td class="mute">·</td>'; continue; }
        const isNew = unseen.has(key);
        html += `<td class="${isNew ? "new" : m.value ? "" : "mute"}" title="${m.value ? "" : "not out yet"}">${m.value ? esc(m.value) : "–"}<span class="mute"> / ${esc(m.max)}</span>${isNew ? '<span class="newtag">new</span>' : ""}</td>`;
      }
      const fk = `${code}|${c.term}`, f = (sis.finals || {})[fk];
      html += f ? `<td class="${unseen.has(fk) ? "new" : ""}"><b>${esc(f.grade)}</b>${unseen.has(fk) ? '<span class="newtag">new</span>' : ""}</td>` : '<td class="mute" title="not out yet">–</td>';
      html += "</tr>";
    }
    html += "</tbody></table></div>";
    const recent = sisLog.slice(-8).reverse();
    if (recent.length) html += '<div class="card"><h3>Recent SIS changes</h3>' + recent.map((x) =>
      `<div><b>${esc(x.label)}</b> ${x.was ? esc(x.was) + " → " : ""}<b>${esc(x.now)}</b>${x.max ? " / " + esc(x.max) : ""} · ${esc(x.code)} — ${esc(x.name)} <span class="mute">· ${esc(new Date(x.t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }))}</span></div>`).join("") + "</div>";
  }
  const past = Object.values((sis && sis.finals) || {}).filter((f) => !codes.some((c) => `${c}|${courses[c].term}` === `${f.code}|${f.term}`));
  if (past.length) {
    const terms = {};
    past.forEach((f) => (terms[f.term] = terms[f.term] || []).push(f));
    const yr = (t) => { const [s, y] = t.split(" "); return +y * 10 + ({ Spring: 1, Summer: 2, Fall: 3, Winter: 4 }[s] || 0); };
    html += '<div class="card"><details><summary>Past terms (final grades)</summary>' + Object.keys(terms).sort((a, b) => yr(b) - yr(a)).map((t) =>
      `<h3>${esc(t)}</h3>` + terms[t].sort((a, b) => a.code.localeCompare(b.code)).map((f) =>
        `<div class="row between"><span>${esc(f.code)} — ${esc(f.name)}</span><span${unseen.has(`${f.code}|${f.term}`) ? ' class="newtag"' : ""}><b>${esc(f.grade)}</b>${f.gpa ? ` <span class="mute">(${esc(f.gpa)})</span>` : ""}</span></div>`).join("")).join("") + "</details></div>";
  }
  let moodle = "";
  for (const [cid, snap] of Object.entries((S.st && S.st.courses) || {})) {
    const g = Object.values(snap.grades || {}).filter((x) => x.grade && x.grade !== "-");
    if (g.length) moodle += `<div class="card"><b>${esc(full(cid))}</b>` + g.map((x) => `<div class="row between"><span>${esc(x.name)}</span><span>${esc(x.grade)}${x.max ? " / " + esc(x.max) : ""}</span></div>`).join("") + "</div>";
  }
  if (moodle) html += '<h3 style="margin-top:12px">Moodle marks</h3>' + moodle;
  list.innerHTML = html;
  const nb = document.getElementById("sisNow");
  if (nb) nb.onclick = async () => { nb.textContent = "Checking…"; nb.disabled = true; await chrome.runtime.sendMessage({ type: "sisCheckNow" }); if (S.tab === "grades") render(); };
  if (advNew.size) { // you've now seen the advisor's messages
    await chrome.storage.local.set({ advSeen: (adv.messages || []).map((x) => x.key) });
    chrome.runtime.sendMessage({ type: "refresh" });
  }
  if (sis && unseen.size) { // you've now seen them: clear the badge (they stay highlighted until you leave this tab)
    await chrome.storage.local.set({ sisSeen: { ...sisSeen, ...baseline(sis) } });
    chrome.runtime.sendMessage({ type: "refresh" });
  }
}

async function markRead(ids) {
  ids.forEach((id) => { S.read[id] = 1; });
  const keep = new Set(events().map(eventId)); // forget ids that left the history
  for (const id of Object.keys(S.read)) if (!keep.has(id)) delete S.read[id];
  await chrome.storage.local.set({ read: S.read });
  chrome.runtime.sendMessage({ type: "refresh" });
  render();
}

const QS = new URLSearchParams(location.search), IN_TAB = QS.has("tab");
if (QS.get("open") === "grades") S.tab = "grades";
if (IN_TAB) { document.body.classList.add("tab"); $("openTab").hidden = true; }

async function boot() {
  const cfg = await settings();
  if (!cfg.code) { $("setup").hidden = false; $("app").hidden = true; return; }
  $("msg").textContent = "Loading…";
  try {
    S.st = await readFeed(cfg.code);
  } catch (e) { $("msg").textContent = ""; $("setup").hidden = false; $("app").hidden = true; $("serr").textContent = e.message; return; }
  $("msg").textContent = "";
  if (!S.st) { $("msg").textContent = "The bot has not saved anything yet."; return; }
  const local = await chrome.storage.local.get(["read", "visits"]);
  S.read = local.read || {};
  S.visits = [Date.now(), ...(local.visits || [])].slice(0, 20); // newest first; visits[1] = previous visit
  await chrome.storage.local.set({ visits: S.visits });
  $("visit").innerHTML = S.visits.slice(0, -1).map((v, i) => `<option value="${i}">${i === 0 ? "Now" : new Date(v).toLocaleString()}</option>`).join("") || '<option value="0">Now</option>';
  const ids = [...new Set(events().map((e) => String(e.cid)))];
  $("fCourse").innerHTML = '<option value="">All subjects</option>' + ids.map((c) => `<option value="${esc(c)}">${esc(full(c === "null" ? null : c))}</option>`).join("");
  $("who").textContent = S.st.name ? "· " + S.st.name : "";
  $("fCat").innerHTML = '<option value="">All kinds</option>' + Object.entries(CAT).filter(([k]) => S.st.owner || (k !== "grades" && k !== "sis")).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("setup").hidden = true; $("app").hidden = false;
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-pressed", x.dataset.tab === S.tab));
  render();
}

document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  S.tab = b.dataset.tab;
  document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-pressed", x === b));
  render();
});
["q", "fCourse", "fCat", "fRead", "fDate", "visit"].forEach((id) => $(id).addEventListener("input", render));
$("list").onclick = (e) => { const c = e.target.closest(".ev[data-id]"); if (c && c.classList.contains("unread")) markRead([c.dataset.id]); };
$("markAll").onclick = () => markRead(events().map(eventId));
$("gear").onclick = async () => {
  const c = await settings();
  $("code").value = ""; $("token").value = ""; $("pass").value = ""; $("serr").textContent = "";
  $("keysState").textContent = c.token && c.pass ? "✓ Saved. SIS marks are also sent to your Telegram. Fill both fields again to change them." : "";
  $("setup").hidden = !$("setup").hidden;
};
$("openTab").onclick = () => {
  const url = chrome.runtime.getURL("dashboard.html?tab=1");
  if (chrome.tabs && chrome.tabs.create) chrome.tabs.create({ url }); else window.open(url, "_blank");
};
$("setup").onsubmit = async (e) => {
  e.preventDefault();
  const cur = await settings(), code = $("code").value.trim(), token = $("token").value.trim(), pass = $("pass").value;
  if (token || pass) {
    if (!token || !pass) { $("serr").textContent = "Fill in both the GitHub key and the data passphrase (or neither)."; return; }
    $("serr").textContent = "Checking the keys…";
    const r = await chrome.runtime.sendMessage({ type: "checkKeys", token, pass });
    if (!r || !r.ok) { $("serr").textContent = (r && r.error) || "Those keys don't open the bot's data."; return; }
    await chrome.storage.local.set({ token, pass, repo: "" });
  }
  if (!code && !cur.code) { $("serr").textContent = "Paste your extension code."; return; }
  if (code) await chrome.storage.local.set({ code });
  $("serr").textContent = ""; await boot();
  chrome.runtime.sendMessage({ type: "refresh" });
};
boot();
