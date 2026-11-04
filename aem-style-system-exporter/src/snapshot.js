// Export snapshots: a compact copy of each run's results under
// output/history/<environment>/<time>/, so later runs (or any two runs,
// e.g. stage against prod) can be compared (see diff.js).
//
// A snapshot holds what a comparison needs, not the whole output: policies,
// templates, template policy mappings, theme tokens and, per style and
// theme, a fingerprint of the CSS its classes reach.

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const FILES = {
  meta: "meta.json",
  policies: "policies.json",
  templates: "templates.json",
  usage: "policy-usage.json",
  tokens: "tokens.json",
  css: "css-summary.json"
};

function readJson(file, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw new Error(`Unreadable ${file}: ${error.message}`);
  }
}

function environmentName(authorUrl) {
  let host = "";
  try {
    host = new URL(authorUrl).hostname;
  } catch {
    host = String(authorUrl || "");
  }
  return host.toLowerCase().replace(/[^a-z0-9.-]+/g, "-") || "unknown-environment";
}

// 2026-11-04T17:30:05.123Z -> 2026-11-04T17-30-05Z (no ":" for Windows paths)
function snapshotId(date = new Date()) {
  return date.toISOString().replace(/\.\d+Z$/, "Z").replace(/:/g, "-");
}

function cssSummary(mapping, policies) {
  if (!mapping?.rows) return null;
  const labels = new Map();
  for (const policy of policies || []) {
    const all = [...(policy.styleGroups || []).flatMap(g => g.styles || []), ...(policy.ungroupedStyles || [])];
    for (const style of all) labels.set(style.path, style.label || style.path.split("/").pop());
  }
  return mapping.rows.map(row => ({
    stylePath: row.stylePath,
    theme: row.theme,
    label: labels.get(row.stylePath) || "",
    matchStatus: row.matchStatus,
    rules: (row.cssRules || []).length,
    // Selector, at-rule context and declarations of each rule, in a stable order.
    hash: crypto.createHash("sha256").update(JSON.stringify(
      (row.cssRules || [])
        .map(r => [r.source, r.contexts, r.selector, r.declarations])
        .map(item => JSON.stringify(item))
        .sort()
    )).digest("hex").slice(0, 16)
  }));
}

// The current run's snapshot, built from the files in outputDir.
function fromOutput(outputDir, { author, policyRoot, templateRoot, aemStatus = null, createdAt = new Date() }) {
  const file = name => path.join(outputDir, name);
  const policies = readJson(file("policies.json"));
  if (!Array.isArray(policies)) throw new Error("No policies.json in " + outputDir);
  const validation = readJson(file("validation-report.json"), {});
  const fe = readJson(file("fe-data.json"));
  const mapping = readJson(file("style-css-mapping.json"));
  return {
    meta: {
      id: snapshotId(createdAt),
      environment: environmentName(author),
      author: author || "",
      policyRoot: policyRoot || "",
      templateRoot: templateRoot || "",
      createdAt: createdAt.toISOString(),
      complete: validation.complete !== false,
      aemStatus,
      themes: fe?.loadedThemes ?? fe?.themes ?? []
    },
    policies,
    templates: readJson(file("templates.json"), []),
    usage: readJson(file("policy-usage.json"), []),
    tokens: fe ? fe.tokens || [] : null,
    css: fe ? cssSummary(mapping, policies) : null
  };
}

function save(historyDir, snapshot) {
  const dir = path.join(historyDir, snapshot.meta.environment, snapshot.meta.id);
  fs.mkdirSync(dir, { recursive: true });
  for (const [key, name] of Object.entries(FILES)) {
    if (snapshot[key] !== null && snapshot[key] !== undefined) {
      fs.writeFileSync(path.join(dir, name), JSON.stringify(snapshot[key], null, 2));
    }
  }
  return dir;
}

function load(dir) {
  const meta = readJson(path.join(dir, FILES.meta));
  if (!meta) throw new Error("Not an export snapshot: " + dir);
  const snapshot = { dir };
  for (const [key, name] of Object.entries(FILES)) snapshot[key] = readJson(path.join(dir, name));
  return snapshot;
}

// Snapshots, oldest first: [{environment, id, dir}], optionally for one environment.
function list(historyDir, environment = null) {
  const found = [];
  if (!fs.existsSync(historyDir)) return found;
  for (const env of fs.readdirSync(historyDir).sort()) {
    if (environment && env !== environment) continue;
    const envDir = path.join(historyDir, env);
    if (!fs.statSync(envDir).isDirectory()) continue;
    for (const id of fs.readdirSync(envDir).sort()) {
      const dir = path.join(envDir, id);
      if (fs.existsSync(path.join(dir, FILES.meta))) found.push({ environment: env, id, dir });
    }
  }
  return found;
}

// Keep the newest `keep` snapshots of an environment.
function prune(historyDir, environment, keep) {
  const all = list(historyDir, environment);
  const removed = all.slice(0, Math.max(0, all.length - keep));
  for (const item of removed) fs.rmSync(item.dir, { recursive: true, force: true });
  return removed.length;
}

module.exports = { FILES, cssSummary, environmentName, fromOutput, list, load, prune, save, snapshotId };
