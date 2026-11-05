// The export store: environments, and every run of the exporter on each.
//
//   <history root>/environments/<environment id>/
//     environment.json             id, name, author URL
//     <run id>/                    e.g. 2026-11-05_103012Z (UTC)
//       run.json                   status, times, roots, counts, changes
//       Style-System_<name>_<run id>.xlsx
//       data/                      the run's data (policies.json, …)
//
// The environment id comes from the author URL: author-p12345-e67890.
// adobeaemcloud.com is "p12345-e67890" (other hosts: the host name). A
// readable name (AEM_ENV_NAME, e.g. "prod") can be given once; it may not be
// reused for another environment. Runs are never changed after they finish,
// so several people can share one store (HISTORY_DIR).

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const ENVIRONMENT_FILE = "environment.json";
const RUN_FILE = "run.json";

// Where each part of a run lives, for comparisons (see diff.js).
const FILES = {
  meta: RUN_FILE,
  policies: "data/policies.json",
  templates: "data/templates.json",
  usage: "data/policy-usage.json",
  tokens: "data/tokens.json",
  css: "data/css-summary.json"
};

const USABLE = new Set(["complete", "incomplete"]);
// A run still "running" after this long was stopped without finishing (the
// console closed, the machine slept): shown as interrupted, never compared.
const INTERRUPTED_AFTER_MS = 12 * 60 * 60 * 1000;

function readJson(file, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw new Error(`Unreadable ${file}: ${error.message}`);
  }
}

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2));
  fs.renameSync(temporary, file);
}

// --- Environments ---------------------------------------------------------------

function environmentId(authorUrl) {
  let host = "";
  try {
    host = new URL(authorUrl).hostname.toLowerCase();
  } catch {
    host = String(authorUrl || "").toLowerCase();
  }
  const cloud = host.match(/^author-(p\d+-e\d+)\./);
  if (cloud) return cloud[1];
  return host.replace(/[^a-z0-9.-]+/g, "-") || "unknown";
}

function cleanName(name) {
  const value = String(name || "").trim();
  if (!value) return null;
  if (!/^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$/.test(value)) {
    throw new Error(`Environment name "${value}": use letters, digits, "-" or "_" (up to 40), e.g. prod`);
  }
  return value.toLowerCase();
}

function environmentsDir(root) {
  return path.join(root, "environments");
}

function listEnvironments(root) {
  const dir = environmentsDir(root);
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).sort()
    .map(id => ({ dir: path.join(dir, id), info: readJson(path.join(dir, id, ENVIRONMENT_FILE)) }))
    .filter(item => item.info)
    .map(item => ({ ...item.info, dir: item.dir }));
}

function label(environment) {
  return environment.name ? `${environment.name} (${environment.id})` : environment.id;
}

// The environment for an author URL, created or updated. name (AEM_ENV_NAME)
// names or renames it; fallbackName (the settings file's, e.g. "prod" for
// .env.prod) only names an environment that has no name yet. A name may not
// belong to another environment.
function registerEnvironment(root, { author, name = null, fallbackName = null }) {
  const id = environmentId(author);
  const dir = path.join(environmentsDir(root), id);
  const existing = readJson(path.join(dir, ENVIRONMENT_FILE), {});
  const clean = cleanName(name) ?? (existing.name ? null : cleanName(fallbackName));
  const others = listEnvironments(root).filter(env => env.id !== id);
  const taken = clean && others.find(env => env.name === clean);
  if (taken) {
    throw new Error(`The name "${clean}" already belongs to ${taken.id} (${taken.author}), not ${author}. ` +
                    "Use another AEM_ENV_NAME.");
  }
  const info = { id, name: clean ?? existing.name ?? null, author, createdAt: existing.createdAt || new Date().toISOString() };
  if (JSON.stringify(existing) !== JSON.stringify(info)) writeJson(path.join(dir, ENVIRONMENT_FILE), info);
  // Same author URL under another name: one environment, renamed.
  const renamedFrom = existing.name && clean && existing.name !== clean ? existing.name : null;
  return { ...info, dir, renamedFrom };
}

// By name or id, case-insensitive.
function findEnvironment(root, spec) {
  const wanted = String(spec || "").toLowerCase();
  return listEnvironments(root).find(env => env.id === wanted || env.name === wanted) || null;
}

// --- Runs -----------------------------------------------------------------------

// 2026-11-05T10:30:12.345Z -> 2026-11-05_103012Z
function runId(date = new Date()) {
  const iso = date.toISOString();
  return `${iso.slice(0, 10)}_${iso.slice(11, 19).replace(/:/g, "")}Z`;
}

// A new run folder; two runs in the same second get -2, -3, … (shared stores).
function createRun(environment, details, date = new Date()) {
  const base = runId(date);
  for (let n = 1; n < 100; n++) {
    const id = n === 1 ? base : `${base}-${n}`;
    const dir = path.join(environment.dir, id);
    try {
      fs.mkdirSync(dir);
    } catch (error) {
      if (error.code === "EEXIST") continue;
      throw error;
    }
    const meta = {
      id,
      environment: environment.id,
      environmentName: environment.name,
      author: environment.author,
      status: "running",
      createdAt: date.toISOString(),
      finishedAt: null,
      machine: os.hostname(),
      ...details
    };
    writeJson(path.join(dir, RUN_FILE), meta);
    return { id, dir, meta };
  }
  throw new Error("Couldn't create a run folder in " + environment.dir);
}

function updateRun(dir, changes) {
  const meta = { ...readJson(path.join(dir, RUN_FILE), {}), ...changes };
  writeJson(path.join(dir, RUN_FILE), meta);
  return meta;
}

// Runs of an environment, oldest first; usable: finished with data
// (complete or incomplete), not failed or still running.
function listRuns(environmentDir, { usable = false } = {}) {
  if (!fs.existsSync(environmentDir)) return [];
  return fs.readdirSync(environmentDir, { withFileTypes: true })
    .filter(entry => entry.isDirectory())
    .map(entry => entry.name).sort()
    .map(id => ({ id, dir: path.join(environmentDir, id) }))
    .map(item => ({ ...item, meta: readJson(path.join(item.dir, RUN_FILE)) }))
    .filter(item => item.meta)
    .map(item => item.meta.status === "running" && Date.now() - Date.parse(item.meta.createdAt) > INTERRUPTED_AFTER_MS
      ? { ...item, meta: { ...item.meta, status: "interrupted", error: item.meta.error || "Stopped before it finished" } }
      : item)
    .filter(item => !usable || USABLE.has(item.meta.status));
}

// What a comparison needs from a run (see diff.js).
function loadRun(dir) {
  const meta = readJson(path.join(dir, RUN_FILE));
  if (!meta) throw new Error("Not an export run: " + dir);
  const run = { dir };
  for (const [key, file] of Object.entries(FILES)) run[key] = readJson(path.join(dir, file));
  run.meta = { ...meta, complete: meta.status === "complete" };
  return run;
}

// Keep the newest `keep` runs of an environment, never `protect`.
function pruneRuns(environmentDir, keep, protect = null) {
  const runs = listRuns(environmentDir).filter(run => run.dir !== protect);
  const removed = runs.slice(0, Math.max(0, runs.length - (protect ? keep - 1 : keep)));
  for (const run of removed) fs.rmSync(run.dir, { recursive: true, force: true });
  return removed.length;
}

const RUN_ID_PATTERN = /^\d{4}-\d{2}-\d{2}_\d{6}Z(-\d+)?$/;

// Deletes one run (its workbook and data). A run still in progress can't be
// deleted; one stopped long ago (interrupted) can. An environment left with
// no runs is removed too: it comes back with its next run.
function deleteRun(environmentDir, id) {
  if (!RUN_ID_PATTERN.test(String(id))) throw new Error("Not a run id: " + id);
  const run = listRuns(environmentDir).find(item => item.id === id);
  if (!run) throw new Error("No run " + id);
  if (run.meta.status === "running") throw new Error(`Run ${id} is still running`);
  fs.rmSync(run.dir, { recursive: true, force: true });
  const environmentRemoved = listRuns(environmentDir).length === 0;
  if (environmentRemoved) fs.rmSync(environmentDir, { recursive: true, force: true });
  return { deleted: id, environmentRemoved };
}

function workbookFile(dir) {
  const name = fs.existsSync(dir) && fs.readdirSync(dir).find(file => file.endsWith(".xlsx"));
  return name ? path.join(dir, name) : null;
}

// --- Run data for comparisons --------------------------------------------------------

// Per style and theme: a fingerprint of the CSS its classes reach.
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
        .map(r => JSON.stringify([r.source, r.contexts, r.selector, r.declarations]))
        .sort()
    )).digest("hex").slice(0, 16)
  }));
}

// --- Exports saved by the earlier layout (output/history/<host>/<time>/) -------------

function migrateLegacy(root, legacyDir) {
  if (!fs.existsSync(legacyDir)) return 0;
  let moved = 0;
  for (const host of fs.readdirSync(legacyDir)) {
    const hostDir = path.join(legacyDir, host);
    if (!fs.statSync(hostDir).isDirectory()) continue;
    for (const old of fs.readdirSync(hostDir).sort()) {
      const from = path.join(hostDir, old);
      const meta = readJson(path.join(from, "meta.json"));
      if (!meta) continue;
      const environment = registerEnvironment(root, { author: meta.author || `https://${host}` });
      const created = new Date(meta.createdAt || Date.now());
      const run = createRun(environment, {
        policyRoot: meta.policyRoot || "", templateRoot: meta.templateRoot || "",
        themes: meta.themes || [], aemStatus: meta.aemStatus ?? null, migrated: true
      }, created);
      fs.mkdirSync(path.join(run.dir, "data"), { recursive: true });
      for (const [file, target] of [["policies.json", FILES.policies], ["templates.json", FILES.templates],
                                    ["policy-usage.json", FILES.usage], ["tokens.json", FILES.tokens],
                                    ["css-summary.json", FILES.css]]) {
        if (fs.existsSync(path.join(from, file))) fs.renameSync(path.join(from, file), path.join(run.dir, target));
      }
      updateRun(run.dir, { status: meta.complete === false ? "incomplete" : "complete", finishedAt: meta.createdAt || null,
                           machine: null });
      fs.rmSync(from, { recursive: true, force: true });
      moved++;
    }
    if (!fs.readdirSync(hostDir).length) fs.rmdirSync(hostDir);
  }
  if (!fs.readdirSync(legacyDir).length) fs.rmdirSync(legacyDir);
  return moved;
}

module.exports = {
  FILES, RUN_FILE, cleanName, createRun, cssSummary, deleteRun, environmentId, environmentsDir, findEnvironment, label,
  listEnvironments, listRuns, loadRun, migrateLegacy, pruneRuns, readJson, registerEnvironment, runId, updateRun,
  workbookFile, writeJson
};
