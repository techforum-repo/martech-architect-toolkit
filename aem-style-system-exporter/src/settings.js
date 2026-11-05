// Where an export step reads its settings and writes its files.
//
// export.bat <environment> runs the steps with the settings file
// .env.<environment> (.env without one) and a run folder of its own,
// handed to each step as EXPORT_SETTINGS_FILE and EXPORT_RUN_DIR. A step run
// on its own (npm run export:aem, …) uses .env and output/work instead.

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve(__dirname, "..");

function settingsFile(environment = "") {
  return path.join(root, environment ? `.env.${environment}` : ".env");
}

// Loads the settings file into process.env; values already set win, so a
// step started by the master keeps the master's choice.
function load(file = process.env.EXPORT_SETTINGS_FILE || settingsFile()) {
  if (fs.existsSync(file)) {
    if (typeof process.loadEnvFile !== "function") {
      throw new Error(`Node.js 22 or later is required (found ${process.version})`);
    }
    process.loadEnvFile(file);
  }
  return file;
}

function runDir() {
  return process.env.EXPORT_RUN_DIR || path.join(root, "output", "work");
}

// The run's data files (policies.json, …).
function dataDir() {
  const dir = path.join(runDir(), "data");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

// Where environments, their runs and comparisons are kept: HISTORY_DIR
// (relative to this folder, or absolute, e.g. a shared drive) or output/.
function historyRoot() {
  const configured = (process.env.HISTORY_DIR || "").trim();
  return configured ? path.resolve(root, configured) : path.join(root, "output");
}

function workbookPath() {
  return path.join(runDir(), process.env.EXPORT_WORKBOOK_NAME || "Style-System.xlsx");
}

module.exports = { dataDir, historyRoot, load, root, runDir, settingsFile, workbookPath };
