// After the AEM and front-end steps of a run: saves what comparisons need
// (theme tokens and a CSS fingerprint per style, next to the run's data) and
// writes data/changes.json, what changed since the previous usable run of the
// same environment and repository roots. The Excel step turns it into the
// workbook's Changes sheet.

const fs = require("node:fs");
const path = require("node:path");

const { diffSnapshots } = require("./diff");
const settings = require("./settings");
const store = require("./store");

settings.load();

function previousRun(current) {
  // Newest first; only runs over the same roots compare meaningfully.
  return store.listRuns(path.dirname(current.dir), { usable: true })
    .filter(run => run.dir !== current.dir)
    .reverse()
    .find(run => run.meta.policyRoot === current.meta.policyRoot &&
                 run.meta.templateRoot === current.meta.templateRoot) || null;
}

function main() {
  const runDir = settings.runDir();
  if (!fs.existsSync(path.join(runDir, store.RUN_FILE))) {
    console.log("[HISTORY] Not part of a run (use export.bat / export.sh): nothing saved.");
    return;
  }
  const data = settings.dataDir();
  const read = name => store.readJson(path.join(data, name));

  const policies = read("policies.json") || [];
  const fe = read("fe-data.json");
  if (fe) {
    store.writeJson(path.join(runDir, store.FILES.tokens), fe.tokens || []);
    const css = store.cssSummary(read("style-css-mapping.json"), policies);
    if (css) store.writeJson(path.join(runDir, store.FILES.css), css);
  }
  const complete = (read("validation-report.json") || {}).complete !== false;
  store.updateRun(runDir, {
    themes: fe?.loadedThemes ?? fe?.themes ?? [],
    counts: {
      policies: policies.length,
      templates: (read("templates.json") || []).length,
      styles: policies.reduce((sum, p) => sum + (p.styleGroups || []).reduce((n, g) => n + (g.styles || []).length, 0)
                                             + (p.ungroupedStyles || []).length, 0)
    }
  });

  const current = store.loadRun(runDir);
  current.meta.complete = complete;
  const before = previousRun(current);
  const changes = before
    ? { comparedWith: store.loadRun(before.dir).meta, current: current.meta,
        ...diffSnapshots(store.loadRun(before.dir), current) }
    : { comparedWith: null, current: current.meta, rows: [], counts: {},
        notes: ["First export of this environment: the next export will list what changed."] };
  store.writeJson(path.join(data, "changes.json"), changes);
  store.updateRun(runDir, { changes: { comparedWith: before ? before.id : null, total: changes.rows.length } });

  console.log(before
    ? `[HISTORY] ${changes.rows.length} change(s) since run ${before.id}`
    : "[HISTORY] First export of this environment: nothing to compare with yet.");
  for (const note of before ? changes.notes : []) console.log(`[HISTORY] ${note}`);
}

try {
  main();
} catch (error) {
  console.error("[HISTORY ERROR]", error.message);
  process.exitCode = 1;
}
