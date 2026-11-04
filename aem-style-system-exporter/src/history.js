// Saves this run as a snapshot (output/history/<environment>/<time>/) and
// writes output/changes.json: what changed since the previous export of the
// same environment and repository roots. The Excel step turns it into the
// workbook's Changes sheet.

const fs = require("node:fs");
const path = require("node:path");

const { diffSnapshots } = require("./diff");
const snapshots = require("./snapshot");

const root = path.resolve(__dirname, "..");
const out = path.join(root, "output");
const historyDir = path.join(out, "history");

const envFile = path.join(root, ".env");
if (typeof process.loadEnvFile === "function" && fs.existsSync(envFile)) {
  process.loadEnvFile(envFile);
}

const keep = Number(process.env.HISTORY_KEEP || 20);

function previousSnapshot(environment, policyRoot, templateRoot) {
  // Newest first; only runs over the same roots compare meaningfully.
  for (const item of snapshots.list(historyDir, environment).reverse()) {
    const before = snapshots.load(item.dir);
    if (before.meta.policyRoot === policyRoot && before.meta.templateRoot === templateRoot) return before;
  }
  return null;
}

function main() {
  if (!Number.isInteger(keep) || keep < 2) {
    throw new Error("HISTORY_KEEP must be a whole number of at least 2");
  }
  const author = process.env.AEM_AUTHOR_URL || "";
  const policyRoot = process.env.AEM_POLICY_ROOT || "";
  const templateRoot = process.env.AEM_TEMPLATE_ROOT || "";
  let aemStatus = null;
  try {
    aemStatus = JSON.parse(fs.readFileSync(path.join(out, "master-status.json"), "utf8")).aemStatus ?? null;
  } catch {
    // run on its own: no master status
  }

  const current = snapshots.fromOutput(out, { author, policyRoot, templateRoot, aemStatus });
  const before = previousSnapshot(current.meta.environment, policyRoot, templateRoot);
  const saved = snapshots.save(historyDir, current);
  const pruned = snapshots.prune(historyDir, current.meta.environment, keep);

  const changes = before
    ? { comparedWith: before.meta, current: current.meta, ...diffSnapshots(before, current) }
    : { comparedWith: null, current: current.meta, rows: [], counts: {},
        notes: ["First export for this environment: the next export will list what changed."] };
  fs.writeFileSync(path.join(out, "changes.json"), JSON.stringify(changes, null, 2));

  console.log(`[HISTORY] Saved ${path.relative(root, saved)}` + (pruned ? ` (removed ${pruned} old)` : ""));
  if (before) {
    console.log(`[HISTORY] ${changes.rows.length} change(s) since ${before.meta.createdAt}`);
  }
  for (const note of changes.notes) console.log(`[HISTORY] ${note}`);
}

try {
  main();
} catch (error) {
  console.error("[HISTORY ERROR]", error.message);
  process.exitCode = 1;
}
