// Compare any two saved exports, e.g. last week's with today's, or stage
// with prod.
//
//   compare.bat / sh compare.sh        opens the compare page in the browser
//   npm run compare -- --list          lists saved exports
//   npm run compare -- <before> <after>
//
// <before> and <after> are each a snapshot folder, "<environment>/<id>" as
// --list prints it, "<environment>" for its latest export, or
// "<environment>~1" for the one before that (~2, … further back).
// The command line writes output/comparisons/<before>__<after>.xlsx and .json.

const fs = require("node:fs");
const path = require("node:path");
const ExcelJS = require("exceljs");

const { diffSnapshots } = require("./diff");
const snapshots = require("./snapshot");
const { changesSheet } = require("./workbook");

const root = path.resolve(__dirname, "..");
const historyDir = path.join(root, "output", "history");
const comparisonsDir = path.join(root, "output", "comparisons");

function resolve(spec, dir = historyDir) {
  const asPath = path.resolve(spec);
  if (fs.existsSync(path.join(asPath, snapshots.FILES.meta))) return asPath;
  const inHistory = path.join(dir, spec);
  if (fs.existsSync(path.join(inHistory, snapshots.FILES.meta))) return inHistory;

  const [environment, back = "0"] = spec.split("~");
  const all = snapshots.list(dir, environment);
  const index = all.length - 1 - Number(back);
  if (!all.length) throw new Error(`No saved exports for "${environment}" (see --list)`);
  if (!Number.isInteger(Number(back)) || index < 0) {
    throw new Error(`"${spec}": ${environment} has ${all.length} saved export(s)`);
  }
  return all[index].dir;
}

// What changed from one saved export to another (snapshot folders).
function compareSnapshots(beforeDir, afterDir) {
  const before = snapshots.load(beforeDir);
  const after = snapshots.load(afterDir);
  return { comparedWith: before.meta, current: after.meta, ...diffSnapshots(before, after) };
}

function comparisonName(changes) {
  const { comparedWith: a, current: b } = changes;
  return `${a.environment}_${a.id}__${b.environment}_${b.id}`;
}

function comparisonWorkbook(changes) {
  const book = new ExcelJS.Workbook();
  book.creator = "AEM Style System Exporter";
  changesSheet(book, changes);
  return book;
}

function printList() {
  const all = snapshots.list(historyDir);
  if (!all.length) {
    console.log("No saved exports yet: each run of the exporter saves one.");
    return;
  }
  for (const item of all) {
    const meta = snapshots.load(item.dir).meta;
    console.log(`${item.environment}/${item.id}` + (meta.complete ? "" : "  (incomplete)"));
  }
}

async function main(args) {
  if (args.length === 0) return require("./ui-server").start();
  if (args[0] === "--list") return printList();
  if (args.length !== 2) {
    console.log("Usage: npm run compare -- <before> <after>   (or --list; no arguments opens the compare page)");
    process.exitCode = 1;
    return;
  }
  const changes = compareSnapshots(resolve(args[0]), resolve(args[1]));
  const name = comparisonName(changes);
  fs.mkdirSync(comparisonsDir, { recursive: true });
  fs.writeFileSync(path.join(comparisonsDir, name + ".json"), JSON.stringify(changes, null, 2));
  const dest = path.join(comparisonsDir, name + ".xlsx");
  await comparisonWorkbook(changes).xlsx.writeFile(dest);

  console.log(`[COMPARE] ${changes.rows.length} change(s)`);
  for (const note of changes.notes) console.log(`[COMPARE] ${note}`);
  console.log(`[COMPARE] Saved ${dest}`);
}

// Exported before main runs: the compare page (ui-server.js) uses these.
module.exports = { compareSnapshots, comparisonName, comparisonWorkbook, historyDir, resolve };

if (require.main === module) {
  main(process.argv.slice(2)).catch(error => {
    console.error("[COMPARE ERROR]", error.message);
    process.exitCode = 1;
  });
}

