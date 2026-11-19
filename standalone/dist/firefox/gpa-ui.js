// GPA calculator widget: one long list of subjects, college grading scale, optional "fill from SIS". Classic script.
// LMSG_GPA_UI.mount(el, { load: async()=>rows, save: async(rows)=>void, sis: async()=>({finals, courses, hint}) })
(function (root) {
  "use strict";
  const G = root.LMSG_GPA;
  const CSS = `.gp{font:14px system-ui,sans-serif;color:var(--fg,#10243a)}
.gp *{box-sizing:border-box}
.gp .sum{background:var(--panel2,#eef5fc);border:1px solid var(--line,#d5e3f3);border-radius:12px;padding:10px 12px;margin-bottom:8px}
.gp .big{font-size:1.9rem;font-weight:800;line-height:1.1;color:var(--acc,#1f6fc0)}
.gp .mute{color:var(--mute,#5b7491);font-size:.82rem}
.gp .bar{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}
.gp button{font:inherit;border:1px solid var(--line,#c5d6ea);background:var(--panel,#fff);color:var(--fg,#10243a);border-radius:8px;padding:6px 10px;cursor:pointer}
.gp button.pri{background:var(--acc,#2f80d6);color:var(--acc-fg,#fff);border-color:transparent;font-weight:700}
.gp .rowg{display:grid;grid-template-columns:minmax(0,1fr) 46px 52px 62px 28px;gap:4px;align-items:center;padding:5px 0;border-bottom:1px solid var(--line,#e1ebf6)}
.gp .rowg.head{font-size:.75rem;color:var(--mute,#5b7491);border-bottom:2px solid var(--line,#d5e3f3)}
.gp input,.gp select{width:100%;font:inherit;color:var(--fg,#10243a);background:var(--panel,#fff);border:1px solid var(--line,#c5d6ea);border-radius:6px;padding:4px 5px;min-width:0}
.gp .rowg.empty input.nm{font-style:italic}
.gp .x{padding:2px 6px;border:0;background:none;color:var(--bad,#b3261e)}
.gp .scale{margin-top:10px;font-size:.78rem}`;
  function mount(el, io) {
    const root_ = document.createElement("div"); root_.className = "gp";
    const st = document.createElement("style"); st.textContent = CSS;
    el.innerHTML = ""; el.append(st, root_);
    let rows = [], timer = null;
    const persist = () => { clearTimeout(timer); timer = setTimeout(() => io.save(rows), 250); };
    const html = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    function summary() {
      const r = G.calc(rows), box = root_.querySelector(".sum");
      box.innerHTML = `<div class="big">${r.counted ? r.gpa.toFixed(2) : "—"}</div><div class="mute">${r.counted} subjects · ${r.hours} credit hours counted. Rows with no grade are ignored (use them for “what if”).</div>`;
    }
    function draw() {
      root_.innerHTML = `<div class="sum"></div>
<div class="bar"><button class="pri" data-a="sis">Fill from my SIS</button><button data-a="add">+ Add subject</button><button data-a="clear">Clear all</button></div>
<div class="mute" data-r="hint"></div>
<div class="rowg head"><span>Subject</span><span>Hours</span><span>%</span><span>Grade</span><span></span></div>
<div data-r="list"></div>
<div class="scale mute">Scale: A+ and A = 4.0 · A- 3.7 · B+ 3.3 · B 3.0 · B- 2.7 · C+ 2.3 · C 2.0 · C- 1.7 · D+ 1.3 · D 1.0 · F 0. Typing a percentage picks the letter for you (97+ A+, 93 A, 89 A-, 84 B+, 80 B, 76 B-, 73 C+, 70 C, 67 C-, 64 D+, 60 D).</div>`;
      const list = root_.querySelector('[data-r="list"]');
      rows.forEach((r, i) => {
        const d = document.createElement("div"); d.className = "rowg" + (r.grade ? "" : " empty");
        d.innerHTML = `<div><input class="nm" data-k="name" value="${html(r.name)}" placeholder="Subject name">${r.term ? `<div class="mute">${html(r.term)}</div>` : ""}</div>
<input data-k="hours" type="number" min="0" step="0.5" inputmode="decimal" value="${html(r.hours)}">
<input data-k="pct" type="number" min="0" max="100" step="0.1" inputmode="decimal" value="${html(r.pct)}" placeholder="%">
<select data-k="grade"><option value=""></option>${G.LETTERS.map((l) => `<option${l === r.grade ? " selected" : ""}>${l}</option>`).join("")}</select>
<button class="x" data-a="del" title="Remove">✕</button>`;
        d.oninput = (e) => {
          const k = e.target.dataset.k; if (!k) return;
          r[k] = e.target.value;
          if (k === "pct") { r.grade = G.pctToGrade(r.pct); d.querySelector('[data-k="grade"]').value = r.grade; }
          if (k === "grade") { r.pct = ""; d.querySelector('[data-k="pct"]').value = ""; }
          d.classList.toggle("empty", !r.grade);
          summary(); persist();
        };
        d.querySelector('[data-a="del"]').onclick = () => { rows.splice(i, 1); persist(); draw(); };
        list.append(d);
      });
      summary();
      io.sis && io.sis().then((s) => { root_.querySelector('[data-r="hint"]').textContent = (s && s.hint) || ""; });
    }
    root_.onclick = async (e) => {
      const a = e.target.dataset && e.target.dataset.a; if (!a) return;
      if (a === "add") { rows.push({ name: "", hours: "", grade: "", pct: "" }); persist(); draw(); const n = root_.querySelectorAll(".nm"); n[n.length - 1].focus(); }
      if (a === "clear" && rows.length && confirm("Remove every subject from the list?")) { rows = []; persist(); draw(); }
      if (a === "sis") {
        const s = io.sis ? await io.sis() : null;
        if (!s || (!Object.keys(s.finals || {}).length && !Object.keys(s.courses || {}).length)) { root_.querySelector('[data-r="hint"]').textContent = (s && s.hint) || "No SIS data yet."; return; }
        rows = G.merge(rows, G.fromSis(s.finals, s.courses)); persist(); draw();
      }
    };
    io.load().then((r) => { rows = Array.isArray(r) ? r : []; draw(); });
  }
  root.LMSG_GPA_UI = { mount };
})(typeof window !== "undefined" ? window : globalThis);
