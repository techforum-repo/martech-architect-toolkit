// The app: one local page to run exports, manage environments' settings,
// see each environment's runs, and compare runs over time or between
// environments. Started by start.bat / sh start.sh (compare.bat opens it on
// the History tab).
//
// Local and guarded: it listens on 127.0.0.1 only and answers only requests
// addressed to that host (so other websites can't reach it through DNS
// tricks). Reads are open to the page; anything that changes something
// (saving settings, running or cancelling an export, testing a connection)
// also needs this session's key, which only the page served here has, and a
// JSON body, which a form on another website can't send. Runs and files are
// only ever named by keys the listings returned, never by a path.

const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

const profiles = require("./profiles");
const settings = require("./settings");
const store = require("./store");
const { Jobs } = require("./jobs");
const { compareRuns, comparisonName, comparisonWorkbook, migrate } = require("./compare");

const PAGE = path.join(__dirname, "app", "index.html");
const PORT_TRIES = 20;
const MAX_BODY = 64 * 1024;
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

function failure(status, message) {
  return Object.assign(new Error(message), { status });
}

// Environments and their runs, newest first.
function environments(root) {
  return store.listEnvironments(root).map(environment => ({
    id: environment.id,
    name: environment.name,
    label: store.label(environment),
    author: environment.author,
    runs: store.listRuns(environment.dir).reverse().map(run => ({
      key: `${environment.id}/${run.id}`,
      id: run.id,
      createdAt: run.meta.createdAt || "",
      status: run.meta.status,
      settingsFile: run.meta.settingsFile || "",
      changes: run.meta.changes || null,
      counts: run.meta.counts || null,
      machine: run.meta.machine || "",
      warnings: run.meta.warnings || [],
      reasons: run.meta.reasons || [],
      findings: run.meta.findings || [],
      error: run.meta.error || null,
      workbook: Boolean(store.workbookFile(run.dir))
    }))
  })).sort((a, b) => (b.runs[0]?.createdAt || "").localeCompare(a.runs[0]?.createdAt || ""));
}

// Only a key the listing returned, never a path from the request.
function runDir(root, key, { usable = true } = {}) {
  const [envId, runId] = String(key || "").split("/");
  const environment = store.listEnvironments(root).find(env => env.id === envId);
  const run = environment && store.listRuns(environment.dir, { usable }).find(item => item.id === runId);
  if (!run) throw failure(404, "Unknown run: " + key);
  return run.dir;
}

// A settings file's environment, if it has an author URL.
function profileView(profile, root) {
  const author = profile.values.AEM_AUTHOR_URL;
  const environment = author ? store.findEnvironment(root, store.environmentId(author)) : null;
  return {
    ...profile,
    environmentId: author ? store.environmentId(author) : null,
    environment: environment ? store.label(environment) : null,
    lastRun: environment ? (store.listRuns(environment.dir).pop()?.meta || null) : null
  };
}

function profileKey(value, dir) {
  const key = String(value || "");
  const known = profiles.list(dir).some(profile => profile.key === key);
  if (!known) throw failure(404, "Unknown settings: " + key);
  return key;
}

function send(response, status, type, body, headers = {}) {
  response.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; frame-ancestors 'none'",
    ...headers
  });
  response.end(body);
}

function json(response, status, value) {
  send(response, status, "application/json; charset=utf-8", JSON.stringify(value));
}

function readBody(request) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    request.on("data", chunk => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(failure(413, "Too large"));
        request.destroy();
      } else chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString("utf8")) : {});
      } catch {
        reject(failure(400, "Expected JSON"));
      }
    });
    request.on("error", reject);
  });
}

function handler({ root, port, key, jobs, dir }) {
  const origins = new Set([`http://127.0.0.1:${port}`, `http://localhost:${port}`]);
  const hosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`]);
  const page = () => fs.readFileSync(PAGE, "utf8").replace("__APP_KEY__", key);

  const guardChange = request => {
    const origin = request.headers.origin;
    if (origin && !origins.has(origin)) throw failure(403, "Forbidden");
    if (request.headers["x-app-key"] !== key) throw failure(403, "Forbidden");
    if (!/^application\/json\b/.test(request.headers["content-type"] || "")) throw failure(415, "Expected JSON");
  };

  return async (request, response) => {
    try {
      if (!hosts.has(request.headers.host || "")) return send(response, 403, "text/plain", "Forbidden");
      const url = new URL(request.url, `http://127.0.0.1:${port}`);
      const param = name => url.searchParams.get(name) || "";
      const route = `${request.method} ${url.pathname}`;

      if (request.method === "GET") {
        if (url.pathname === "/") return send(response, 200, "text/html; charset=utf-8", page());
        if (url.pathname === "/api/environments") return json(response, 200, environments(root));
        if (url.pathname === "/api/profiles") {
          return json(response, 200, {
            profiles: profiles.list(dir).map(profile => profileView(profile, root)),
            fields: profiles.FIELDS.map(({ check, ...field }) => field),
            historyRoot: root
          });
        }
        if (url.pathname === "/api/jobs") return json(response, 200, jobs.list());
        const jobMatch = url.pathname.match(/^\/api\/jobs\/(\d+)$/);
        if (jobMatch) {
          const job = jobs.get(jobMatch[1]);
          if (!job) throw failure(404, "Unknown run");
          return json(response, 200, jobs.view(job, Number(param("from")) || 0));
        }
        if (url.pathname === "/api/compare" || url.pathname === "/api/compare.xlsx") {
          const changes = compareRuns(runDir(root, param("before")), runDir(root, param("after")));
          if (url.pathname === "/api/compare") return json(response, 200, changes);
          const buffer = await comparisonWorkbook(changes).xlsx.writeBuffer();
          return send(response, 200, XLSX, Buffer.from(buffer),
                      { "Content-Disposition": `attachment; filename="compare_${comparisonName(changes)}.xlsx"` });
        }
        if (url.pathname === "/api/workbook") {
          const file = store.workbookFile(runDir(root, param("run"), { usable: false }));
          if (!file) throw failure(404, "This run has no workbook");
          return send(response, 200, XLSX, fs.readFileSync(file),
                      { "Content-Disposition": `attachment; filename="${path.basename(file)}"` });
        }
        return send(response, 404, "text/plain", "Not found");
      }

      if (request.method !== "POST") return send(response, 405, "text/plain", "Method not allowed", { Allow: "GET, POST" });
      guardChange(request);
      const body = await readBody(request);

      if (route === "POST /api/profiles") {
        const isNew = Boolean(body.isNew);
        const key = String(body.key || "");
        if (!profiles.validKey(key)) return json(response, 422, { errors: { key: "Use lowercase letters, digits, - or _ (up to 40), e.g. prod" } });
        if (!isNew) profileKey(key, dir);
        const values = profiles.merged(key, body.values || {}, dir);
        const errors = profiles.validate(key, values, { isNew, dir });
        if (Object.keys(errors).length) return json(response, 422, { errors });
        const author = values.AEM_AUTHOR_URL;
        const taken = store.listEnvironments(root)
          .find(env => env.name === key && env.id !== store.environmentId(author) && key !== profiles.DEFAULT_KEY);
        if (taken) {
          return json(response, 422, { errors: { key: `"${key}" is already the name of ${store.label(taken)} (${taken.author})` } });
        }
        profiles.write(key, values, dir);
        return json(response, 200, { saved: key });
      }
      if (route === "POST /api/profiles/test") {
        const key = String(body.key || "");
        const values = profiles.merged(key, body.values || {}, dir);
        const errors = profiles.validate(key, values, { dir });
        delete errors.key;
        if (Object.keys(errors).length) return json(response, 422, { errors });
        return json(response, 200, await profiles.testConnection(values));
      }
      if (route === "POST /api/jobs") {
        const job = jobs.start(profileKey(body.profile, dir));
        return json(response, 200, jobs.view(job));
      }
      if (route === "POST /api/runs/delete") {
        const key = String(body.run || "");
        const folder = runDir(root, key, { usable: false });
        if (jobs.list().some(job => job.status === "running" && job.runKey === key)) {
          throw failure(409, "This run is still running: cancel it first");
        }
        try {
          return json(response, 200, store.deleteRun(path.dirname(folder), path.basename(folder)));
        } catch (error) {
          throw failure(409, error.message);
        }
      }
      const cancel = url.pathname.match(/^\/api\/jobs\/(\d+)\/cancel$/);
      if (cancel) return json(response, 200, { cancelled: jobs.cancel(cancel[1]) });
      return send(response, 404, "text/plain", "Not found");
    } catch (error) {
      return json(response, error.status || 500, { error: error.message });
    }
  };
}

function listen(server, port, triesLeft) {
  return new Promise((resolve, reject) => {
    server.once("error", error => {
      if (error.code === "EADDRINUSE" && triesLeft > 1) resolve(listen(server, port + 1, triesLeft - 1));
      else reject(error);
    });
    server.listen(port, "127.0.0.1", () => resolve(port));
  });
}

function openBrowser(url) {
  const [command, args] = process.platform === "win32" ? ["cmd", ["/c", "start", "", url]]
    : process.platform === "darwin" ? ["open", [url]]
    : ["xdg-open", [url]];
  try {
    spawn(command, args, { stdio: "ignore", detached: true }).on("error", () => {}).unref();
  } catch {
    // no browser to open: the address is printed
  }
}

// base: .env's values (HISTORY_DIR, COMPARE_UI_PORT), read, not loaded.
async function start({ dir = settings.root,
                       base = profiles.readFile(profiles.fileFor(profiles.DEFAULT_KEY, dir)) || {},
                       root = settings.historyRoot({ HISTORY_DIR: process.env.HISTORY_DIR || base.HISTORY_DIR }),
                       port = Number(process.env.COMPARE_UI_PORT || base.COMPARE_UI_PORT || 8510),
                       open = process.env.COMPARE_UI_NO_BROWSER !== "1", tab = "run",
                       jobs = null, script = undefined } = {}) {
  migrate(root);
  const server = http.createServer();
  const actual = await listen(server, port, PORT_TRIES);
  const runner = jobs || new Jobs({ projectRoot: settings.root, historyRoot: root, script });
  const key = crypto.randomBytes(24).toString("base64url");
  server.on("request", handler({ root, port: actual, key, jobs: runner, dir }));

  // Ctrl+C: stop exports started here too, and record them as cancelled.
  const stop = () => {
    for (const job of runner.list()) if (job.status === "running") runner.cancel(job.id);
    setTimeout(() => process.exit(0), 300);
  };
  if (!jobs) {
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
  }

  const url = `http://127.0.0.1:${actual}/#tab=${tab}`;
  console.log(`[APP] AEM Style System Exporter: ${url}  (Ctrl+C to stop)`);
  console.log(`[APP] Runs are kept in ${store.environmentsDir(root)}`);
  if (open) openBrowser(url);
  return { server, port: actual, url, key, jobs: runner };
}

if (require.main === module) {
  const tab = (process.argv.find(arg => arg.startsWith("--tab=")) || "").slice(6) || "run";
  start({ tab }).catch(error => {
    console.error("[APP ERROR]", error.message);
    process.exitCode = 1;
  });
}

module.exports = { environments, start };
