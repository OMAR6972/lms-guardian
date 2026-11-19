// Runs on Moodle at document_start. Optional dark theme for the LMS, chosen in the LMS Guardian panel
// (Moodle theme: Off / Dark / Dim / Auto). Pure display change: nothing on the page is edited or sent anywhere.
(function () {
  const MODES = { dark: 0.93, dim: 0.85 }; // how far the page colours are inverted (higher = darker)
  const ID = "lmsg-theme-style", KEY = "lmsg-theme";

  function themeCss(mode) {
    const a = MODES[mode];
    if (!a) return "";
    // Invert + rotate hue keeps colours recognisable; pictures, video, icons and embeds are flipped back.
    return `html{filter:invert(${a}) hue-rotate(180deg)!important;background:#fff!important}
img,picture,video,canvas,iframe,embed,object,svg image,.userpicture,.icon.navicon,[style*="background-image"]{filter:invert(1) hue-rotate(180deg)!important}
#lmsg-bell,#lmsg-frame{filter:invert(1) hue-rotate(180deg)!important}
img.icon,.icon img{filter:none!important}
::selection{background:#f2b705;color:#000}`;
  }

  function resolve(choice) {
    if (choice === "auto") {
      return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "off";
    }
    return MODES[choice] ? choice : "off";
  }

  if (typeof module !== "undefined") module.exports = { themeCss, resolve, MODES };
  if (typeof document === "undefined" || typeof chrome === "undefined" || !chrome.storage) return;
  if (window.top !== window) return; // only the top page; embedded frames are flipped back by the rule above

  let choice = "off";
  function apply() {
    let el = document.getElementById(ID);
    const css = themeCss(resolve(choice));
    if (!css) { if (el) el.remove(); return; }
    if (!el) { el = document.createElement("style"); el.id = ID; (document.head || document.documentElement).appendChild(el); }
    if (el.textContent !== css) el.textContent = css;
  }
  try { choice = localStorage.getItem(KEY) || "off"; } catch (_) {} // instant, so there is no white flash on load
  apply();
  chrome.storage.local.get("lmsTheme", (v) => {
    choice = v.lmsTheme || "off";
    try { localStorage.setItem(KEY, choice); } catch (_) {}
    apply();
  });
  chrome.storage.onChanged.addListener((c) => {
    if (!c.lmsTheme) return;
    choice = c.lmsTheme.newValue || "off";
    try { localStorage.setItem(KEY, choice); } catch (_) {}
    apply();
  });
  if (typeof matchMedia === "function") matchMedia("(prefers-color-scheme: dark)").addEventListener("change", apply);
})();
