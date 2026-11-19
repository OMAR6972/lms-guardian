// Standalone LMS Guardian, SIS side: when YOU open your own profile / subjects page, remember your grades in this browser
// so the GPA calculator can fill itself. It only reads the page you are looking at. Nothing is sent anywhere.
(function () {
  "use strict";
  if (window.top !== window || typeof chrome === "undefined" || !chrome.storage || !window.LMSG_SIS) return;
  if (window.LMSG_SIS.looksLoggedOut(location.href, document.documentElement.outerHTML)) return;
  const html = document.documentElement.outerHTML, S = window.LMSG_SIS, save = {};
  const pl = document.querySelector('a[href*="/users/"][href$="/profile"]');
  if (pl) { const m = /(\/users\/\d+\/profile)/.exec(pl.getAttribute("href")); if (m) save.sisProfile = "https://eng.asu.edu.eg" + m[1]; }
  const finals = S.parseFinals(html);
  if (Object.keys(finals).length) { save.sisFinals = finals; save.sisAt = Date.now(); }
  const list = S.parseMyCourses(html);
  if (list.length) { const c = {}; list.forEach((x) => { c[x.code] = { name: x.name, term: x.term }; }); save.sisCourses = c; }
  if (!Object.keys(save).length) return;
  chrome.storage.local.set(save, () => {
    if (!save.sisFinals) return;
    const t = document.createElement("div");
    t.textContent = `🎓 LMS Guardian saved your ${Object.keys(finals).length} grades for the GPA calculator.`;
    t.style.cssText = "position:fixed;left:14px;bottom:14px;z-index:2147483646;background:#10243a;color:#fff;padding:9px 13px;border-radius:10px;font:13px system-ui;box-shadow:0 3px 12px rgba(0,0,0,.35)";
    document.body.append(t); setTimeout(() => t.remove(), 4500);
  });
})();
