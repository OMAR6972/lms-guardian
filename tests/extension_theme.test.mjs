// Run: node tests/extension_theme.test.mjs   (dark theme CSS for Moodle: pure functions of extension/lms-theme.js)
import assert from "node:assert/strict";
import { createRequire } from "node:module";
const { themeCss, resolve, PALETTES, darkenBg, needsLightText } = createRequire(import.meta.url)("../extension/lms-theme.js");

assert.equal(themeCss("off"), "", "off adds nothing");
assert.equal(themeCss("bogus"), "", "unknown value adds nothing");
assert.ok(themeCss("dark").includes("invert(0.93)"));
assert.ok(themeCss("dim").includes("invert(0.85)"), "dim is softer than dark");
for (const m of ["dark", "dim"]) {
  const css = themeCss(m);
  assert.ok(/img[^{]*\{filter:invert\(1\) hue-rotate\(180deg\)/.test(css), "pictures are flipped back");
  assert.ok(css.includes("#lmsg-bell") && css.includes("#lmsg-frame"), "the extension's own button and panel are flipped back");
}
for (const n of ["cyberpunk", "synthwave", "matrix", "midnight"]) {
  const css = themeCss(n);
  assert.ok(css.includes(PALETTES[n].bg) && css.includes(PALETTES[n].ac), n + " uses its palette");
  assert.ok(!css.includes("invert(0."), n + " recolours instead of inverting");
  assert.equal(resolve(n), n);
  for (const k of ["bg", "pn", "p2", "tx", "mu", "ln", "ac", "hd", "bt", "btbg", "ok", "bad"]) assert.match(PALETTES[n][k], /^#[0-9a-f]{6}$/i, n + "." + k);
}
// catch-all for light backgrounds
const cy = PALETTES.cyberpunk;
assert.equal(darkenBg("rgb(255, 255, 255)", cy), "rgb(14,14,22)", "white becomes the panel colour");
assert.equal(darkenBg("rgb(248, 249, 250)", cy), "rgb(14,14,22)");
assert.equal(darkenBg("rgb(222, 226, 230)", cy), "rgb(26,26,38)", "light grey becomes the input/hover colour");
assert.notEqual(darkenBg("rgb(212, 237, 218)", cy), "rgb(14,14,22)", "pale green keeps a greenish tint");
assert.equal(darkenBg("rgb(14, 14, 22)", cy), null, "already dark: untouched");
assert.equal(darkenBg("rgba(0, 0, 0, 0)", cy), null, "transparent: untouched");
assert.equal(darkenBg("rgb(252, 238, 10)", cy), null, "vivid accent colours: untouched");
assert.equal(needsLightText("rgb(33, 37, 41)", "rgb(14, 14, 22)"), true, "dark text on a dark background");
assert.equal(needsLightText("rgb(5, 5, 9)", "rgb(252, 238, 10)"), false, "dark text on a bright button stays");
assert.equal(needsLightText("rgb(233, 247, 250)", "rgb(14, 14, 22)"), false, "light text is fine");
assert.equal(resolve("dark"), "dark");
assert.equal(resolve("dim"), "dim");
assert.equal(resolve("off"), "off");
assert.equal(resolve(undefined), "off");
assert.equal(resolve("auto"), "off", "auto outside a browser falls back to off");
console.log("extension theme tests OK");
