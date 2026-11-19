// Run: node tests/extension_theme.test.mjs   (dark theme CSS for Moodle: pure functions of extension/lms-theme.js)
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const { themeCss, resolve } = createRequire(import.meta.url)("../extension/lms-theme.js");

assert.equal(themeCss("off"), "", "off adds nothing");
assert.equal(themeCss("bogus"), "", "unknown value adds nothing");
assert.ok(themeCss("dark").includes("invert(0.93)"));
assert.ok(themeCss("dim").includes("invert(0.85)"), "dim is softer than dark");
for (const m of ["dark", "dim"]) {
  const css = themeCss(m);
  assert.ok(/img[^{]*\{filter:invert\(1\) hue-rotate\(180deg\)/.test(css), "pictures are flipped back");
  assert.ok(css.includes("#lmsg-bell") && css.includes("#lmsg-frame"), "the extension's own button and panel are flipped back");
}
assert.equal(resolve("dark"), "dark");
assert.equal(resolve("dim"), "dim");
assert.equal(resolve("off"), "off");
assert.equal(resolve(undefined), "off");
assert.equal(resolve("auto"), "off", "auto outside a browser falls back to off");
console.log("extension theme tests OK");
