// Runs on the SIS (eng.asu.edu.eg). Content scripts can't import modules, so the few readers it needs are inline.
// 1) Tells the extension you're logged in, so it re-reads your marks if they're old.
// 2) Highlights marks and final grades that are new or changed since you last looked.
// 3) Adds a 🎓 button that opens the marks table.
(function () {
  if (window.top !== window) return;
  const path = location.pathname;
  if (/^\/(ar\/)?login\b/i.test(path) || document.querySelector('input[type="password"]')) return; // login page: nothing to do

  chrome.runtime.sendMessage({ type: "sisVisit" }, () => void chrome.runtime.lastError);

  const txt = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  const CODE = /^[A-Z]{2,5}[0-9x]{2,4}[a-z]?$/, TERM = /^(Fall|Spring|Summer|Winter) \d{4}$/;

  const style = document.createElement("style");
  style.textContent = `
    .lmsg-new{outline:3px solid #f2b705!important;outline-offset:2px;background:#fff6d5!important;color:#10243a!important;border-radius:6px;position:relative}
    .lmsg-tag{display:inline-block;margin-inline-start:8px;padding:1px 8px;border-radius:99px;background:#f2b705;color:#10243a;font:700 12px system-ui;vertical-align:middle}`;
  document.documentElement.appendChild(style);
  const tag = (el, text) => {
    if (el.querySelector(".lmsg-tag")) return;
    const s = document.createElement("span"); s.className = "lmsg-tag"; s.textContent = text; el.appendChild(s);
  };

  async function highlight() {
    const { sisSeen } = await chrome.storage.local.get("sisSeen");
    if (!sisSeen) return; // the extension hasn't made its first (silent) read yet
    const seen = { ...sisSeen };
    let changed = 0;

    // A subject page: the marks boxes
    if (/\/dashboard\/courses\/show\//.test(path)) {
      const th = [...document.querySelectorAll("th")].find((t) => txt(t) === "Code");
      const code = txt(th && th.nextElementSibling);
      if (CODE.test(code)) {
        document.querySelectorAll("ul.row.no-gutters").forEach((ul) => {
          const li = ul.querySelectorAll("li");
          if (li.length < 2) return;
          const label = txt(li[0]), m = /^(.*?)\s*\/\s*([\d.]+)$/.exec(txt(li[1]).replace(/NEW|CHANGED.*$/, "").trim());
          if (!label || !m) return;
          const v = m[1].trim() === "-" ? "" : m[1].trim(), key = `${code}|${label}`;
          if (v && seen[key] !== v) {
            ul.classList.add("lmsg-new");
            tag(li[0], seen[key] ? `CHANGED (was ${seen[key]})` : "NEW");
            seen[key] = v; changed++;
          }
        });
      }
    }
    // The profile: final grades per term
    // Study Grades rows first (the same grade also appears under "Taken Courses"; highlight it where you read it)
    const terms = document.getElementById("collapseCardTerms");
    const rows = [...document.querySelectorAll("tr")].sort((a, b) => (terms && terms.contains(b) ? 1 : 0) - (terms && terms.contains(a) ? 1 : 0));
    rows.forEach((tr) => {
      const c = [...tr.children];
      if (c.length !== 6 || c.some((x) => x.tagName !== "TD")) return;
      const code = txt(c[0]), term = txt(c[2]), grade = txt(c[3]).replace(/NEW|CHANGED.*$/, "").trim();
      if (!CODE.test(code) || !TERM.test(term) || !grade) return;
      const key = `${code}|${term}`;
      if (seen[key] !== grade) {
        tr.classList.add("lmsg-new");
        tag(c[3], seen[key] ? `CHANGED (was ${seen[key]})` : "NEW");
        // open the term's hidden table so you see it
        const wrap = tr.closest('tr[style*="display: none"]');
        if (wrap) wrap.style.display = "";
        seen[key] = grade; changed++;
      }
    });
    if (changed) {
      await chrome.storage.local.set({ sisSeen: seen });
      chrome.runtime.sendMessage({ type: "refresh" }, () => void chrome.runtime.lastError);
    }
  }
  highlight();

  // 🎓 button: the marks table in a small panel
  const b = document.createElement("button");
  b.setAttribute("aria-label", "LMS Guardian marks table");
  b.title = "Your marks (LMS Guardian)";
  b.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483646;width:54px;height:54px;border-radius:50%;border:0;background:#2f80d6;color:#fff;font:700 24px system-ui;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.3)";
  b.textContent = "🎓";
  let frame = null;
  b.onclick = () => {
    if (frame) { frame.remove(); frame = null; return; }
    frame = document.createElement("iframe");
    frame.src = chrome.runtime.getURL("dashboard.html?open=grades");
    frame.style.cssText = "position:fixed;right:18px;bottom:82px;z-index:2147483646;width:min(560px,calc(100vw - 36px));height:min(640px,calc(100vh - 110px));border:1px solid #d5e3f3;border-radius:16px;background:#fff;box-shadow:0 8px 30px rgba(0,0,0,.3)";
    document.body.appendChild(frame);
  };
  document.body.appendChild(b);
})();
