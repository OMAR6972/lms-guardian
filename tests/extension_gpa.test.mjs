import { createRequire } from "node:module";
import assert from "node:assert/strict";
import fs from "node:fs";
const G = createRequire(import.meta.url)("../extension/gpa.js");
// scale from the college table
for (const [p, g] of [[100, "A+"], [97, "A+"], [96.9, "A"], [93, "A"], [92.9, "A-"], [89, "A-"], [88.9, "B+"], [84, "B+"], [80, "B"], [76, "B-"], [73, "C+"], [70, "C"], [67, "C-"], [64, "D+"], [60, "D"], [59.9, "F"], [0, "F"]]) assert.equal(G.pctToGrade(p), g, p);
assert.equal(G.POINTS["A+"], 4); assert.equal(G.POINTS["A"], 4); assert.equal(G.POINTS["A-"], 3.7); assert.equal(G.POINTS["B+"], 3.3); assert.equal(G.POINTS["D"], 1); assert.equal(G.POINTS["F"], 0);
// GPA: hours-weighted; empty grade / no hours rows are ignored; F counts as 0 points but its hours count
const r = G.calc([{ hours: 3, grade: "A" }, { hours: 3, grade: "B+" }, { hours: 2, grade: "A-" }, { hours: 3, grade: "" }, { hours: "", grade: "A" }]);
assert.equal(r.hours, 8); assert.equal(r.counted, 3); assert.ok(Math.abs(r.gpa - 29.3 / 8) < 1e-9);
assert.equal(G.calc([{ hours: 3, grade: "A" }, { hours: 3, grade: "F" }]).gpa, 2);
assert.equal(G.calc([]).gpa, 0);
// SIS rows: oldest term first, this term's subjects empty, own rows survive a refill
const rows = G.fromSis({ "B|Spring 2024": { code: "B", name: "b", term: "Spring 2024", grade: "A", hours: 3 }, "A|Fall 2023": { code: "A", name: "a", term: "Fall 2023", grade: "B+", hours: 2 } }, { C: { name: "c", term: "Fall 2026" } });
assert.deepEqual(rows.map((x) => x.key), ["sis:A|Fall 2023", "sis:B|Spring 2024", "sis:C|Fall 2026"]);
const merged = G.merge([{ key: "sis:C|Fall 2026", grade: "A", hours: 3, pct: "" }, { name: "mine", hours: 1, grade: "B" }], rows);
assert.equal(merged.find((x) => x.key === "sis:C|Fall 2026").grade, "A"); assert.ok(merged.some((x) => x.name === "mine"));
// parseFinals now keeps the credit hours ("3 Hours")
const lib = fs.readFileSync(new URL("../extension/lib.js", import.meta.url), "utf8");
const { parseFinals } = await import("data:text/javascript," + encodeURIComponent(lib));
const f = parseFinals(fs.readFileSync(new URL("./fixtures/sis/profile.html", import.meta.url), "utf8"));
assert.ok(Object.values(f).length && Object.values(f).every((x) => x.hours > 0), JSON.stringify(f));
console.log("gpa ok");
