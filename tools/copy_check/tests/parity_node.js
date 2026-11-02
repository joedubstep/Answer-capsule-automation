// Runs the Copy Checker page's own JavaScript (extracted from the built HTML) over a corpus.
// Usage: node parity_node.js <built page.html> <corpus.json>   -> prints a JSON array of results.
// corpus.json: {"cases": [{"id", "context", "text", "opts"}]}
"use strict";
const fs = require("fs");
const vm = require("vm");

const [pagePath, corpusPath] = process.argv.slice(2);
const html = fs.readFileSync(pagePath, "utf8");
const data = html.match(/<script id="rules-data" type="application\/json">([\s\S]*?)<\/script>/);
if (!data) throw new Error("rules-data script not found in page");
const a = html.indexOf("/* CHECKER START */"), b = html.indexOf("/* CHECKER END */");
if (a < 0 || b < a) throw new Error("checker markers not found in page");

const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(html.slice(a, b), sandbox);
const rules = JSON.parse(data[1]);

// Every pattern must compile in JavaScript too.
const bad = [];
for (const r of rules.rules) {
  const pats = (r._res || []).map(p => [p.re, p.flags]);
  if (r.pattern && r.kind === "metric") pats.push([r.pattern, "i"]);
  if (r.template_ok) pats.push([r.template_ok, "i"]);
  for (const s of r.skip_if || []) pats.push([s.pattern, s.flags === undefined ? "i" : s.flags]);
  for (const e of r._entries || []) pats.push(["^(?:" + e.re + ")$", "i"]);
  if (r.suggest) pats.push([r.suggest[0], "i"]);
  if (r.before) pats.push([r.before, ""]);
  for (const [src, flags] of pats) {
    try { new RegExp(src, flags.includes("i") ? "gi" : "g"); } catch (err) { bad.push(r.id + ": " + err.message); }
  }
}
if (bad.length) { process.stderr.write("JS regex errors:\n" + bad.join("\n") + "\n"); process.exit(3); }

const corpus = JSON.parse(fs.readFileSync(corpusPath, "utf8"));
const out = corpus.cases.map(c => {
  const r = sandbox.SurvenCopyCheck.check(rules, c.text, c.context, c.opts || {});
  return {
    id: c.id, ok: r.ok, grade: r.grade, counts: r.counts,
    issues: r.issues.map(i => ({ rule: i.rule, severity: i.severity, match: i.match, line: i.line, fix: i.fix })),
  };
});
process.stdout.write(JSON.stringify(out));
