// The compare page: compare.bat / sh compare.sh (or `npm run compare`).
// Over time: one environment's runs, any two compared. Between environments:
// one run of each (e.g. stage and prod).
//
// Read-only and local: it listens on 127.0.0.1 only, answers only requests
// addressed to that host (so other websites can't reach it through DNS
// tricks), and only reads runs the store lists, never a path from a request.

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

const store = require("./store");
const { compareRuns, comparisonName, comparisonWorkbook, historyRoot: defaultRoot } = require("./compare");

const PAGE = path.join(__dirname, "ui", "compare.html");
const PORT_TRIES = 20;
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

// Environments and their runs, newest first, as the page shows them.
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
      changes: run.meta.changes || null,
      counts: run.meta.counts || null,
      machine: run.meta.machine || "",
      warnings: run.meta.warnings || [],
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
  if (!run) {
    const error = new Error("Unknown run: " + key);
    error.status = 404;
    throw error;
  }
  return run.dir;
}

function send(response, status, type, body, headers = {}) {
  response.writeHead(status, {
    "Content-Type": type,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'",
    ...headers
  });
  response.end(body);
}

function json(response, status, value) {
  send(response, status, "application/json; charset=utf-8", JSON.stringify(value));
}

function handler(root, port) {
  const allowedHosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`]);

  return async (request, response) => {
    try {
      if (!allowedHosts.has(request.headers.host || "")) return send(response, 403, "text/plain", "Forbidden");
      if (request.method !== "GET") return send(response, 405, "text/plain", "Read-only", { Allow: "GET" });
      const url = new URL(request.url, `http://127.0.0.1:${port}`);
      const param = name => url.searchParams.get(name) || "";

      if (url.pathname === "/") return send(response, 200, "text/html; charset=utf-8", fs.readFileSync(PAGE));
      if (url.pathname === "/api/environments") return json(response, 200, environments(root));

      if (url.pathname === "/api/compare" || url.pathname === "/api/compare.xlsx") {
        const changes = compareRuns(runDir(root, param("before")), runDir(root, param("after")));
        if (url.pathname === "/api/compare") return json(response, 200, changes);
        const buffer = await comparisonWorkbook(changes).xlsx.writeBuffer();
        return send(response, 200, XLSX, Buffer.from(buffer),
                    { "Content-Disposition": `attachment; filename="compare_${comparisonName(changes)}.xlsx"` });
      }

      if (url.pathname === "/api/workbook") {
        const file = store.workbookFile(runDir(root, param("run"), { usable: false }));
        if (!file) return json(response, 404, { error: "This run has no workbook" });
        return send(response, 200, XLSX, fs.readFileSync(file),
                    { "Content-Disposition": `attachment; filename="${path.basename(file)}"` });
      }
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

async function start({ root = defaultRoot(), port = Number(process.env.COMPARE_UI_PORT || 8510),
                       open = process.env.COMPARE_UI_NO_BROWSER !== "1" } = {}) {
  const server = http.createServer();
  const actual = await listen(server, port, PORT_TRIES);
  server.on("request", handler(root, actual));
  const url = `http://127.0.0.1:${actual}/`;
  console.log(`[COMPARE] Compare page: ${url}  (Ctrl+C to stop)`);
  console.log(`[COMPARE] Exports in ${store.environmentsDir(root)}`);
  if (open) openBrowser(url);
  return { server, port: actual, url };
}

module.exports = { environments, start };
