// Runs on the SIS. Adds a small button to mark a page as a grades page; watched pages are read
// (tables only) and sent to the extension's background, which encrypts them before they leave the browser.
(function () {
  if (window.top !== window) return;
  const url = location.href.split("#")[0];
  const btn = document.createElement("button");
  btn.style.cssText = "position:fixed;right:14px;bottom:14px;z-index:2147483647;padding:8px 12px;border-radius:99px;border:1px solid #2f80d6;background:#fff;color:#10243a;font:600 13px system-ui;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.2)";
  const paint = (w, rows) => { btn.textContent = w ? `🎓 Watching this page${rows != null ? ` (${rows} rows)` : ""}` : "🎓 Watch this page for grades"; };
  const send = () => chrome.runtime.sendMessage({ type: "sisPage", url, title: document.title, html: document.documentElement.outerHTML }, (r) => paint(r && r.watching, r && r.rows));
  btn.onclick = () => chrome.runtime.sendMessage({ type: "sisToggle", url }, (r) => { paint(r && r.watching); if (r && r.watching) send(); });
  if (/\/login/i.test(location.pathname)) return; // nothing to watch on the login page
  document.body.appendChild(btn);
  paint(false);
  setTimeout(send, 1500); // let late-loading tables render
})();
