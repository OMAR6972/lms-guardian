// Builds the standalone LMS Guardian from the shared extension code:
//   dist/chromium/  (Chrome, Edge, Brave, Opera: Load unpacked)      dist/firefox/ (Firefox desktop + Android, MV2)
//   dist/lms-guardian.user.js (Violentmonkey/Tampermonkey: Firefox Android and anywhere else)
// Run: node standalone/build.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url)), ext = path.join(here, "..", "extension"), src = path.join(here, "src"), dist = path.join(here, "dist");
const rd = (p) => fs.readFileSync(p, "utf8");
const version = JSON.parse(rd(path.join(ext, "manifest.json"))).version;

// SIS page readers, cut out of lib.js (the part between the SIS section header and the bookkeeping section)
const lib = rd(path.join(ext, "lib.js"));
const a = lib.indexOf("export const SIS"), b = lib.indexOf("// ---------- SIS bookkeeping");
if (a < 0 || b < a) throw new Error("lib.js layout changed: cannot cut the SIS readers");
const sisParse = "(function(){\n" + lib.slice(a, b).replace(/^export /gm, "") +
  "\nwindow.LMSG_SIS = { parseMyCourses, parseFinals, profileUrl, looksLoggedOut };\n})();\n";
for (const n of ["parseMyCourses", "parseFinals", "profileUrl", "looksLoggedOut"]) if (!sisParse.includes("function " + n)) throw new Error("missing " + n);

const shared = ["lms-theme.js", "jszip.min.js", "gpa.js", "gpa-ui.js", "lms-tools.js"].map((f) => [f, path.join(ext, f)])
  .concat([["sa-panel.js", path.join(src, "sa-panel.js")], ["sa-sis.js", path.join(src, "sa-sis.js")]]);

fs.rmSync(dist, { recursive: true, force: true });
for (const [name, manifest] of [["chromium", "manifest.chromium.json"], ["firefox", "manifest.firefox.json"]]) {
  const d = path.join(dist, name); fs.mkdirSync(path.join(d, "icons"), { recursive: true });
  for (const [f, p] of shared) fs.copyFileSync(p, path.join(d, f));
  fs.writeFileSync(path.join(d, "sis-parse.js"), sisParse);
  for (const i of fs.readdirSync(path.join(ext, "icons"))) fs.copyFileSync(path.join(ext, "icons", i), path.join(d, "icons", i));
  fs.writeFileSync(path.join(d, "manifest.json"), rd(path.join(src, manifest)).replace("__VERSION__", version));
}

// Userscript: same code, with a tiny "chrome.storage" made from GM_getValue/GM_setValue.
const body = (f) => (f === "sis-parse.js" ? sisParse : rd(path.join(dist, "chromium", f)));
const shim = `
  const listeners = [];
  const all = () => { try { return GM_getValue("lmsg", {}) || {}; } catch (e) { return {}; } };
  const pick = (o, k) => { if (k == null) return { ...o }; const ks = typeof k === "string" ? [k] : Array.isArray(k) ? k : Object.keys(k); const r = typeof k === "object" && !Array.isArray(k) ? { ...k } : {}; ks.forEach((x) => { if (x in o) r[x] = o[x]; }); return r; };
  const fire = (oldV, newV) => { const c = {}; Object.keys(newV).forEach((k) => { if (JSON.stringify(oldV[k]) !== JSON.stringify(newV[k])) c[k] = { oldValue: oldV[k], newValue: newV[k] }; }); if (Object.keys(c).length) listeners.forEach((f) => { try { f(c, "local"); } catch (e) {} }); };
  const chrome = { storage: { local: {
    get(k, cb) { const r = pick(all(), k); if (cb) cb(r); return Promise.resolve(r); },
    set(o, cb) { const old = all(), nw = { ...old, ...o }; GM_setValue("lmsg", nw); fire(old, nw); if (cb) cb(); return Promise.resolve(); } },
    onChanged: { addListener(f) { listeners.push(f); } } } };
  try { GM_addValueChangeListener("lmsg", (n, o, v, remote) => { if (remote) fire(o || {}, v || {}); }); } catch (e) {}
  const ready = (f) => (document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", f) : f());
`;
const lmsPart = ["lms-theme.js"].map(body).join("\n") + "\n  ready(() => {\n" + ["jszip.min.js", "gpa.js", "gpa-ui.js", "lms-tools.js", "sa-panel.js"].map(body).join("\n;\n") + "\n  });\n";
const sisPart = "  ready(() => {\n" + ["sis-parse.js", "sa-sis.js"].map(body).join("\n;\n") + "\n  });\n";
const header = `// ==UserScript==
// @name         LMS Guardian (standalone)
// @namespace    https://github.com/OMAR6972/lms-guardian
// @version      ${version}
// @description  Ain Shams Engineering Moodle: themes, compact layout, phone fixes, not-submitted deadlines, download all files, GPA calculator. Everything stays in your browser.
// @match        https://lms.eng.asu.edu.eg/*
// @match        https://eng.asu.edu.eg/*
// @run-at       document-start
// @noframes
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_addValueChangeListener
// @downloadURL  https://raw.githubusercontent.com/OMAR6972/lms-guardian/main/standalone/dist/lms-guardian.user.js
// @updateURL    https://raw.githubusercontent.com/OMAR6972/lms-guardian/main/standalone/dist/lms-guardian.user.js
// ==/UserScript==
`;
fs.writeFileSync(path.join(dist, "lms-guardian.user.js"), header + "(function () {\n  \"use strict\";\n" + shim +
  "  if (location.hostname === \"lms.eng.asu.edu.eg\") {\n" + lmsPart + "  } else if (location.hostname === \"eng.asu.edu.eg\") {\n" + sisPart + "  }\n})();\n");
import { execSync } from "node:child_process";
for (const n of ["chromium", "firefox"]) {
  try { execSync(`cd "${path.join(dist, n)}" && zip -qr "../lms-guardian-${n}.zip" .`); } catch (e) { console.warn("zip not available for", n); }
}
console.log("built", version);
