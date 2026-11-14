import { settings, readEnc, eventId } from "./lib.js";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const CAT = { materials: "📄 Materials", edits: "🔄 Edits", assignments: "📝 Assignments", quizzes: "❓ Quizzes", posts: "📢 Announcements", grades: "🎯 Moodle grades", sis: "🎓 SIS grades" };
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
    let html = "";
    for (const [cid, snap] of Object.entries(S.st.courses || {})) {
      const g = Object.values(snap.grades || {}).filter((x) => x.grade && x.grade !== "-");
      if (g.length) html += `<div class="card"><b>${esc(full(cid))}</b>` + g.map((x) => `<div class="row between"><span>${esc(x.name)}</span><span>${esc(x.grade)}${x.max ? " / " + esc(x.max) : ""}</span></div>`).join("") + "</div>";
    }
    for (const page of Object.values(S.st.sis || {})) {
      html += `<div class="card"><b>🎓 ${esc(page.title || "SIS")}</b>` + Object.values(page.rows).map((cells) => `<div class="mute">${esc(cells.filter(Boolean).join(" · "))}</div>`).join("") + "</div>";
    }
    list.innerHTML = html || '<div class="card mute">No grades recorded yet.</div>';
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

async function boot() {
  const cfg = await settings();
  if (!cfg.token || !cfg.pass || !cfg.repo) { $("setup").hidden = false; $("app").hidden = true; return; }
  $("msg").textContent = "Loading…";
  try {
    S.st = await readEnc(cfg, "state.enc");
  } catch (e) { $("msg").textContent = ""; $("setup").hidden = false; $("serr").textContent = e.message; return; }
  $("msg").textContent = "";
  if (!S.st) { $("msg").textContent = "The bot has not saved anything yet."; return; }
  const local = await chrome.storage.local.get(["read", "visits"]);
  S.read = local.read || {};
  S.visits = [Date.now(), ...(local.visits || [])].slice(0, 20); // newest first; visits[1] = previous visit
  await chrome.storage.local.set({ visits: S.visits });
  $("visit").innerHTML = S.visits.slice(0, -1).map((v, i) => `<option value="${i}">${i === 0 ? "Now" : new Date(v).toLocaleString()}</option>`).join("") || '<option value="0">Now</option>';
  const ids = [...new Set(events().map((e) => String(e.cid)))];
  $("fCourse").innerHTML = '<option value="">All subjects</option>' + ids.map((c) => `<option value="${esc(c)}">${esc(full(c === "null" ? null : c))}</option>`).join("");
  $("fCat").innerHTML = '<option value="">All kinds</option>' + Object.entries(CAT).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("setup").hidden = true; $("app").hidden = false;
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
$("gear").onclick = async () => { const c = await settings(); $("repo").value = c.repo || ""; $("setup").hidden = !$("setup").hidden; };
$("setup").onsubmit = async (e) => {
  e.preventDefault();
  const cur = await settings();
  await chrome.storage.local.set({ repo: $("repo").value.trim(), token: $("token").value.trim() || cur.token || "", pass: $("pass").value || cur.pass || "" });
  $("serr").textContent = ""; boot();
};
boot();
