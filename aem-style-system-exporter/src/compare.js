// Compare two export runs: over time on one environment, or between
// environments (e.g. stage and prod).
//
//   compare.bat / sh compare.sh          opens the compare page in the browser
//   compare.bat --list                   environments and their runs
//   compare.bat <before> <after>         e.g. prod~1 prod, or stage prod
//
// A run is "<environment>" (its latest usable run), "<environment>~1" (the
// one before, ~2 …), "<environment>/<run id>", or a run folder. The
// environment is its name (AEM_ENV_NAME) or id (p12345-e67890).
// The command line writes <history>/comparisons/<before>__<after>.xlsx and .json.

const fs = require("node:fs");
const path = require("node:path");
const ExcelJS = require("exceljs");

const { diffSnapshots } = require("./diff");
const settings = require("./settings");
const store = require("./store");
const { changesSheet } = require("./workbook");

// Command line: HISTORY_DIR from the environment or .env. The app passes
// its own root instead (it never loads settings files into its process).
function historyRoot() {
  return settings.historyRoot();
}

function migrate(root = historyRoot()) {
  const moved = store.migrateLegacy(root, path.join(settings.root, "output", "history"));
  if (moved) console.log(`[COMPARE] Moved ${moved} earlier export(s) into ${store.environmentsDir(root)}`);
}

function resolve(spec, root = historyRoot()) {
  if (fs.existsSync(path.join(path.resolve(spec), store.RUN_FILE))) return path.resolve(spec);

  const [envPart, runPart] = spec.split("/");
  const [envSpec, back = "0"] = envPart.split("~");
  const environment = store.findEnvironment(root, envSpec);
  if (!environment) {
    const known = store.listEnvironments(root).map(store.label).join(", ");
    throw new Error(`No environment "${envSpec}"` + (known ? ` (known: ${known})` : " (no exports yet)"));
  }
  if (runPart) {
    const dir = path.join(environment.dir, runPart);
    if (!fs.existsSync(path.join(dir, store.RUN_FILE))) throw new Error(`No run ${runPart} in ${store.label(environment)}`);
    return dir;
  }
  const runs = store.listRuns(environment.dir, { usable: true });
  const index = runs.length - 1 - Number(back);
  if (!Number.isInteger(Number(back)) || index < 0) {
    throw new Error(`"${spec}": ${store.label(environment)} has ${runs.length} usable run(s)`);
  }
  return runs[index].dir;
}

// What changed from one run to another (run folders).
function compareRuns(beforeDir, afterDir) {
  const before = store.loadRun(beforeDir);
  const after = store.loadRun(afterDir);
  return { comparedWith: before.meta, current: after.meta, ...diffSnapshots(before, after) };
}

function comparisonName(changes) {
  const part = meta => `${meta.environmentName || meta.environment}_${meta.id}`;
  return `${part(changes.comparedWith)}__${part(changes.current)}`;
}

function comparisonWorkbook(changes) {
  const book = new ExcelJS.Workbook();
  book.creator = "AEM Style System Exporter";
  changesSheet(book, changes);
  return book;
}

function printList() {
  const environments = store.listEnvironments(historyRoot());
  if (!environments.length) {
    console.log("No exports yet: run export.bat (or sh export.sh).");
    return;
  }
  for (const environment of environments) {
    console.log(`${store.label(environment)}  ${environment.author}`);
    for (const run of store.listRuns(environment.dir).reverse()) {
      const changes = run.meta.changes;
      console.log(`  ${run.id}  ${run.meta.status.padEnd(10)}` +
                  (changes?.comparedWith ? `  ${changes.total} change(s) since ${changes.comparedWith}` : ""));
    }
  }
}

async function main(args) {
  if (args.length === 0) return require("./app-server").start({ tab: "history" });
  settings.load();
  migrate();
  if (args[0] === "--list") return printList();
  if (args.length !== 2) {
    console.log("Usage: compare.bat <before> <after>   (e.g. prod~1 prod, or stage prod)\n" +
                "       compare.bat --list             environments and runs\n" +
                "       compare.bat                    the compare page");
    process.exitCode = 1;
    return;
  }
  const changes = compareRuns(resolve(args[0]), resolve(args[1]));
  const dir = path.join(historyRoot(), "comparisons");
  const name = comparisonName(changes);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, name + ".json"), JSON.stringify(changes, null, 2));
  const dest = path.join(dir, name + ".xlsx");
  await comparisonWorkbook(changes).xlsx.writeFile(dest);

  console.log(`[COMPARE] ${changes.rows.length} change(s)`);
  for (const note of changes.notes) console.log(`[COMPARE] ${note}`);
  console.log(`[COMPARE] Saved ${dest}`);
}

// Exported before main runs: the app (app-server.js) uses these.
module.exports = { compareRuns, comparisonName, comparisonWorkbook, historyRoot, migrate, resolve };

if (require.main === module) {
  main(process.argv.slice(2)).catch(error => {
    console.error("[COMPARE ERROR]", error.message);
    process.exitCode = 1;
  });
}
