// Runs on the SIS (eng.asu.edu.eg). Changes nothing on the page.
// It only tells the extension "you're logged in now", so it re-reads your marks if they're old
// and resumes its background checks after you were logged out.
(function () {
  if (window.top !== window) return;
  if (/^\/(ar\/)?login\b/i.test(location.pathname) || document.querySelector('input[type="password"]')) return;
  chrome.runtime.sendMessage({ type: "sisVisit" }, () => void chrome.runtime.lastError);
})();
