// Runs on Moodle at document_start. Optional themes for the LMS, chosen in the LMS Guardian panel.
// Pure display change: nothing on the page is edited or sent anywhere.
(function () {
  const ID = "lmsg-theme-style", KEY = "lmsg-theme";

  // Dark and Dim flip the page's own colours; pictures, video and embeds are flipped back.
  const INVERT = { dark: 0.93, dim: 0.85 };

  // Colour themes recolour Moodle directly. bg page, pn panels/nav, p2 inputs/hover, tx text, mu muted text,
  // ln borders, ac links, hd headings, bt text on buttons, ok/bad status colours.
  const PALETTES = {
    cyberpunk: { bg: "#050509", pn: "#0e0e16", p2: "#1a1a26", tx: "#e9f7fa", mu: "#8a93a6", ln: "#3b3b10", ac: "#00f0ff", hd: "#fcee0a", bt: "#050509", btbg: "#fcee0a", ok: "#00ff9f", bad: "#ff2a55",
      font: '"Rajdhani","Bahnschrift","Segoe UI Semibold","Segoe UI",system-ui,sans-serif', caps: true, cut: true, glow: "#fcee0a" },
    synthwave: { bg: "#160a2b", pn: "#221145", p2: "#2e1a5e", tx: "#f6ecff", mu: "#b69ee0", ln: "#4b2b8c", ac: "#36f9f6", hd: "#ff7edb", bt: "#160a2b", btbg: "#ff4fd8", ok: "#72f1b8", bad: "#ff6b8b", glow: "#ff4fd8", caps: false },
    matrix: { bg: "#000000", pn: "#02130a", p2: "#04240f", tx: "#a8f5b4", mu: "#4fa862", ln: "#0b5a22", ac: "#00ff41", hd: "#39ff6e", bt: "#000000", btbg: "#00ff41", ok: "#00ff41", bad: "#ff5555",
      font: 'ui-monospace,"Cascadia Mono",Consolas,"Courier New",monospace', glow: "#00ff41", caps: false },
    midnight: { bg: "#0a101d", pn: "#111a2d", p2: "#192741", tx: "#e5ecf7", mu: "#8ea2c2", ln: "#243652", ac: "#5ca9ff", hd: "#ffffff", bt: "#06101f", btbg: "#5ca9ff", ok: "#5fd68f", bad: "#ff8a80", caps: false },
  };

  const NAMES = { off: "Off", dark: "Dark", dim: "Dim (softer)", cyberpunk: "Cyberpunk", synthwave: "Synthwave", matrix: "Matrix", midnight: "Midnight", auto: "Auto (follow my device)" };

  function invertCss(a) {
    return `html{filter:invert(${a}) hue-rotate(180deg)!important;background:#fff!important}
img,picture,video,canvas,iframe,embed,object,svg image,.userpicture,.icon.navicon,[style*="background-image"]{filter:invert(1) hue-rotate(180deg)!important}
#lmsg-bell,#lmsg-frame{filter:invert(1) hue-rotate(180deg)!important}
img.icon,.icon img{filter:none!important}
::selection{background:#f2b705;color:#000}`;
  }

  function paletteCss(p) {
    const glow = p.glow ? `text-shadow:0 0 8px ${p.glow}66!important;` : "";
    const caps = p.caps ? "text-transform:uppercase!important;letter-spacing:.06em!important;" : "";
    const cut = p.cut ? `clip-path:polygon(0 0,calc(100% - 10px) 0,100% 10px,100% 100%,10px 100%,0 calc(100% - 10px))!important;` : "";
    const font = p.font ? `font-family:${p.font}!important;` : "";
    const bgs = `.drawer,.drawer-left,.drawer-right,.courseindex,.block,.card,.card-body,.card-header,.card-footer,.activity-item,.course-section,.modal-content,.dropdown-menu,.popover,.popover-body,.list-group-item,.jumbotron,.alert,.box,.generalbox,.que .content,.que .info,.moodle-dialogue-base .moodle-dialogue-wrap,.bg-white,.bg-light,.bg-secondary,.activity-header,.activity-information,.description,.footer-popover,.tox,.tox-tinymce`;
    return `html{color-scheme:dark;scrollbar-color:${p.ac} ${p.bg}}
html,body,#page,#page-wrapper,#page-content,#region-main,#region-main-box,.main-inner,.drawers,.pagelayout-login #page{background:${p.bg}!important;color:${p.tx}!important;${font}}
#page-header,.primary-navigation,.navbar,.fixed-top,.moremenu,.secondary-navigation,.tertiary-navigation,#page-footer,.nav-tabs,.breadcrumb{background:${p.pn}!important;border-color:${p.ln}!important}
${bgs}{background-color:${p.pn}!important;color:${p.tx}!important;border-color:${p.ln}!important}
.courseindex .courseindex-item:hover,.list-group-item-action:hover,.dropdown-item:hover,.table-hover tbody tr:hover{background-color:${p.p2}!important}
.table,.generaltable,.table th,.table td,.generaltable th,.generaltable td{background-color:transparent!important;color:${p.tx}!important;border-color:${p.ln}!important}
.generaltable th,.generaltable td.cell.c0,.table-striped tbody tr:nth-of-type(odd){background-color:${p.p2}!important}
.submissionstatussubmitted,td.submissionstatussubmitted,.alert-success{background-color:${p.ok}22!important;color:${p.tx}!important}
.submissionstatusnotsubmitted,.alert-danger,.alert-warning{background-color:${p.bad}22!important;color:${p.tx}!important}
.text-muted,.small,.text-secondary,.dimmed_text,.muted,.activity-dates,.text-black-50{color:${p.mu}!important}
a:not(.btn):not(.dropdown-item),.btn-link{color:${p.ac}!important}
h1,h2,h3,h4,h5,h6,.h1,.h2,.h3,.h4,.h5,.h6,.sectionname,.sectionname a,.page-header-headings h1{color:${p.hd}!important;${glow}${caps}}
.btn-primary,.btn-success,.btn-info,.btn-primary:hover{background:${p.btbg}!important;color:${p.bt}!important;border-color:${p.btbg}!important;font-weight:700!important;${cut}${caps}}
.btn-secondary,.btn-outline-secondary,.btn-light,.btn-outline-primary,.btn-default{background:${p.p2}!important;color:${p.tx}!important;border-color:${p.ln}!important;${cut}}
.btn-danger{background:${p.bad}!important;color:#fff!important;border-color:${p.bad}!important;${cut}}
.form-control,input:not([type=checkbox]):not([type=radio]):not([type=submit]),select,textarea,.custom-select,.input-group-text{background-color:${p.p2}!important;color:${p.tx}!important;border-color:${p.ln}!important}
.form-control:focus,input:focus,select:focus,textarea:focus{border-color:${p.ac}!important;box-shadow:0 0 0 .15rem ${p.ac}44!important;outline:0}
::placeholder{color:${p.mu}!important}
.nav-tabs .nav-link{color:${p.ac}!important;border-color:transparent!important;background:transparent!important}
.nav-tabs .nav-link.active,.nav-tabs .nav-item.show .nav-link{color:${p.hd}!important;border-bottom:2px solid ${p.ac}!important}
.page-link{background:${p.pn}!important;color:${p.ac}!important;border-color:${p.ln}!important}
.badge-primary,.badge-info{background:${p.ac}!important;color:${p.bt}!important}
.drawer-toggler .btn,.btn-footer-popover{background:${p.btbg}!important;color:${p.bt}!important;border-color:${p.btbg}!important}
hr,.border,.border-bottom,.border-top{border-color:${p.ln}!important}
.card,.activity-item,.block{${p.cut ? `border-left:3px solid ${p.hd}!important;` : ""}}
.activity-item,.card{${p.glow ? `box-shadow:0 0 12px ${p.glow}1f!important;` : ""}}
.icon,.fa,.navbar-toggler,.navbar .btn,.navbar .nav-link,.usermenu .dropdown-toggle,#user-menu-toggle,.btn-icon,.fa-bars{color:${p.ac}!important}
.navbar-toggler-icon{filter:invert(1)!important}
.drawer-toggler .btn .icon,.drawer-toggler .btn .fa,.btn-footer-popover .icon,.btn-primary .icon,.btn-primary .fa{color:${p.bt}!important}
.userinitials,.avatar{background:${p.p2}!important;color:${p.hd}!important}
img.icon,.icon img{filter:invert(1) brightness(1.6)!important}
.activityiconcontainer .icon{color:inherit}
::selection{background:${p.hd};color:${p.bg}}
body,button,input,select,textarea{${font}}`;
  }

  function themeCss(mode) {
    if (INVERT[mode]) return invertCss(INVERT[mode]);
    if (PALETTES[mode]) return paletteCss(PALETTES[mode]);
    return "";
  }

  function resolve(choice) {
    if (choice === "auto") {
      return typeof matchMedia === "function" && matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "off";
    }
    return INVERT[choice] || PALETTES[choice] ? choice : "off";
  }

  if (typeof module !== "undefined") module.exports = { themeCss, resolve, INVERT, PALETTES, NAMES };
  if (typeof document === "undefined" || typeof chrome === "undefined" || !chrome.storage) return;
  if (window.top !== window) return;

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
