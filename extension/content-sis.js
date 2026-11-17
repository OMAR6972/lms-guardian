// Runs on the SIS (eng.asu.edu.eg). It tells the extension "you're logged in now" (so it re-reads your marks if they're
// old and resumes background checks), and shows one small 🎓 button that opens the marks table. Nothing else on the page is touched.
(function () {
  if (window.top !== window) return;
  if (/^\/(ar\/)?login\b/i.test(location.pathname) || document.querySelector('input[type="password"]')) return;
  chrome.runtime.sendMessage({ type: "sisVisit" }, () => void chrome.runtime.lastError);
  const b = document.createElement("button");
  b.setAttribute("aria-label", "LMS Guardian: marks and advisor");
  b.title = "LMS Guardian: marks and advisor";
  b.style.cssText = "position:fixed;right:18px;bottom:18px;z-index:2147483646;width:54px;height:54px;border-radius:50%;border:0;background:#2f80d6;color:#fff;font:700 22px system-ui;cursor:pointer;box-shadow:0 3px 12px rgba(0,0,0,.3)";
  b.textContent = "🎓";
  const badge = document.createElement("span");
  badge.style.cssText = "position:absolute;top:-4px;right:-4px;min-width:20px;height:20px;border-radius:10px;background:#c23b3b;color:#fff;font:700 12px/20px system-ui;padding:0 5px;display:none";
  b.appendChild(badge);
  let frame = null;
  b.onclick = () => {
    if (frame) { frame.remove(); frame = null; return; }
    frame = document.createElement("iframe");
    frame.src = chrome.runtime.getURL("dashboard.html?open=grades");
    frame.style.cssText = "position:fixed;right:18px;bottom:82px;z-index:2147483646;width:min(430px,calc(100vw - 36px));height:min(640px,calc(100vh - 110px));border:1px solid #d5e3f3;border-radius:16px;background:#fff;box-shadow:0 8px 30px rgba(0,0,0,.3)";
    document.body.appendChild(frame);
  };
  document.body.appendChild(b);
  const paint = (n) => { badge.style.display = n ? "block" : "none"; badge.textContent = n > 99 ? "99+" : String(n || ""); };
  chrome.storage.local.get("sisUnseen", (v) => paint(v.sisUnseen));
  chrome.storage.onChanged.addListener((c) => { if (c.sisUnseen) paint(c.sisUnseen.newValue); });
})();
