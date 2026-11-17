// Run: node tests/extension_sis.test.mjs   (pure functions of extension/lib.js against real-markup fixtures)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { parseMarks, parseMyCourses, blockedByFees, parseAdvisorBadge, parseAdvisorThread, newAdvisor } from "../extension/lib.js";
const fx = (n) => readFileSync(new URL(`./fixtures/sis/${n}`, import.meta.url), "utf8");

// fees block: detected by redirect target and by the message; normal pages are not blocked
assert.ok(blockedByFees("https://eng.asu.edu.eg/payments/student_fees", ""));
assert.ok(blockedByFees("https://eng.asu.edu.eg/students/1", fx("fees_block.html")));
assert.ok(!blockedByFees("https://eng.asu.edu.eg/dashboard", fx("dashboard.html")));
// the fees page's own boxes (Unpaid / 2645.1 EGP) must never be mistaken for marks
assert.deepEqual(parseMarks(fx("fees_block.html")), []);
// normal pages still parse
assert.ok(parseMyCourses(fx("my_courses.html")).length > 0);
assert.ok(parseMarks(fx("course_10268.html")).length > 0);

// advisor
assert.equal(parseAdvisorBadge(fx("dashboard_badge.html")), 3);
assert.equal(parseAdvisorBadge(fx("dashboard.html")), parseAdvisorBadge(fx("dashboard.html")));
const th = parseAdvisorThread(fx("advisor_thread.html"), "188161");
assert.equal(th.length, 3);
assert.deepEqual(th.map((x) => x.mine), [false, true, false]);
assert.equal(th[0].text, "Approved. Good luck!");
assert.equal(new Set(th.map((x) => x.key)).size, 3, "identical replies at different times keep different keys");
assert.deepEqual(newAdvisor({ messages: th }, undefined), [], "first read: nothing is new");
assert.equal(newAdvisor({ messages: th }, th.map((x) => x.key)).length, 0);
const fresh = { ...th[0], key: "1281|Please send the form|1", text: "Please send the form" };
assert.deepEqual(newAdvisor({ messages: [fresh, ...th] }, th.map((x) => x.key)).map((x) => x.text), ["Please send the form"]);
assert.equal(newAdvisor({ messages: [{ ...fresh, mine: true }, ...th] }, th.map((x) => x.key)).length, 0, "your own message is never an advisor reply");
console.log("extension SIS tests OK");
