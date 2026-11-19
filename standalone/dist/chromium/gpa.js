// GPA maths and the college grading scale (percent -> letter -> points). Pure; works in a page, an extension and node.
(function (root) {
  "use strict";
  const POINTS = { "A+": 4, "A": 4, "A-": 3.7, "B+": 3.3, "B": 3, "B-": 2.7, "C+": 2.3, "C": 2, "C-": 1.7, "D+": 1.3, "D": 1, "F": 0 };
  const LETTERS = Object.keys(POINTS);
  // lowest percent for each letter (A+ is "more than 97", A is "93 to under 97"; both are 4.0, so 97 exactly counts as A+)
  const MIN = [[97, "A+"], [93, "A"], [89, "A-"], [84, "B+"], [80, "B"], [76, "B-"], [73, "C+"], [70, "C"], [67, "C-"], [64, "D+"], [60, "D"]];
  function pctToGrade(p) {
    p = Number(p); if (!isFinite(p) || p < 0) return "";
    for (const [m, g] of MIN) if (p >= m) return g;
    return "F";
  }
  // lowest percent that still gives this letter, and how many marks you may lose out of 100 to keep it
  function minPct(letter) { const m = MIN.find((x) => x[1] === letter); return m ? m[0] : letter === "F" ? 0 : null; }
  function maxLost(letter) { const m = minPct(letter); return m == null ? null : 100 - m; }
  // marks lost out of 100 -> letter
  function lostToGrade(l) { const n = Number(l); return l === "" || l == null || !isFinite(n) || n < 0 || n > 100 ? "" : pctToGrade(100 - n); }
  function normGrade(s) {
    const g = String(s == null ? "" : s).trim().toUpperCase().replace(/\s+/g, "");
    return Object.prototype.hasOwnProperty.call(POINTS, g) ? g : "";
  }
  // rows: [{hours, grade}]. A row counts only when it has hours and a valid grade; empty ones are the "what-if" rows.
  function calc(rows) {
    let pts = 0, hrs = 0, n = 0;
    for (const r of rows || []) {
      const h = Number(r.hours), g = normGrade(r.grade);
      if (!(h > 0) || !g) continue;
      pts += h * POINTS[g]; hrs += h; n++;
    }
    return { gpa: hrs ? pts / hrs : 0, hours: hrs, points: pts, counted: n };
  }
  // "Fall 2023" -> sortable number (Winter < Spring < Summer < Fall inside a year)
  function termKey(t) {
    const m = /^(Winter|Spring|Summer|Fall)\s+(\d{4})$/i.exec(String(t || "").trim());
    if (!m) return 0;
    return Number(m[2]) * 10 + { winter: 0, spring: 1, summer: 2, fall: 3 }[m[1].toLowerCase()];
  }
  // SIS data -> list rows. finals: {"CODE|Term": {code,name,term,grade,hours}}, courses: {CODE: {name,term}} (current subjects, left empty)
  function fromSis(finals, courses) {
    const rows = [], have = new Set();
    Object.values(finals || {}).sort((a, b) => termKey(a.term) - termKey(b.term) || String(a.code).localeCompare(b.code)).forEach((f) => {
      have.add(f.code + "|" + f.term);
      rows.push({ key: "sis:" + f.code + "|" + f.term, name: `${f.code} — ${f.name}`, term: f.term, hours: f.hours || "", grade: normGrade(f.grade), lost: "" });
    });
    Object.entries(courses || {}).forEach(([code, c]) => {
      if (have.has(code + "|" + c.term)) return;
      rows.push({ key: "sis:" + code + "|" + c.term, name: `${code} — ${c.name}`, term: c.term, hours: "", grade: "", lost: "" });
    });
    return rows;
  }
  // keep your own rows, replace the SIS ones; a grade you typed into a SIS row for a subject with no final yet is kept
  function merge(existing, fresh) {
    const mine = (existing || []).filter((r) => !String(r.key || "").startsWith("sis:"));
    const old = new Map((existing || []).filter((r) => String(r.key || "").startsWith("sis:")).map((r) => [r.key, r]));
    const sis = fresh.map((r) => { const o = old.get(r.key); return o && !r.grade && o.grade ? { ...r, grade: o.grade, lost: o.lost || "", hours: r.hours || o.hours } : o && !r.hours && o.hours ? { ...r, hours: o.hours } : r; });
    return sis.concat(mine);
  }
  const api = { POINTS, LETTERS, MIN, pctToGrade, minPct, maxLost, lostToGrade, normGrade, calc, termKey, fromSis, merge };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.LMSG_GPA = api;
})(typeof window !== "undefined" ? window : typeof self !== "undefined" ? self : globalThis);
