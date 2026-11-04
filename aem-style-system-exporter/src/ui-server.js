// The compare page: a local web page to pick two saved exports and see what
// changed between them. Started by compare.bat / compare.sh (or
// `npm run compare` without arguments).
//
// Read-only and local: it listens on 127.0.0.1 only, answers only requests
// addressed to that host (so other websites can't reach it through DNS
// tricks), and only reads snapshots listed in output/history.

const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawn } = require("node:child_process");

const snapshots = require("./snapshot");
const { compareSnapshots, comparisonName, comparisonWorkbook, historyDir: defaultHistory } = require("./compare");

const PAGE = path.join(__dirname, "ui", "compare.html");
const FIRST_PORT = Number(process.env.COMPARE_UI_PORT || 8510);
const PORT_TRIES = 20;

function readMeta(dir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(dir, snapshots.FILES.meta), "utf8"));
  } catch {
    return null;
  }
}

// Saved exports, newest first, as the page lists them.
function savedExports(historyDir) {
  return snapshots.list(historyDir).map(item => {
    const meta = readMeta(item.dir) || {};
    return {
      key: `${item.environment}/${item.id}`,
      environment: item.environment,
      id: item.id,
      createdAt: meta.createdAt || "",
      complete: meta.complete !== false,
      author: meta.author || "",
      themes: meta.themes || []
    };
  }).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

// Only a key the listing returned, never a path from the request.
function snapshotDir(historyDir, key) {
  const found = snapshots.list(historyDir).find(item => `${item.environment}/${item.id}` === key);
  if (!found) {
    const error = new Error("Unknown export: " + key);
    error.status = 404;
    throw error;
  }
  return found.dir;
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

function handler(historyDir, port) {
  const allowedHosts = new Set([`127.0.0.1:${port}`, `localhost:${port}`]);

  return async (request, response) => {
    try {
      if (!allowedHosts.has(request.headers.host || "")) {
        return send(response, 403, "text/plain", "Forbidden");
      }
      if (request.method !== "GET") {
        return send(response, 405, "text/plain", "Read-only", { Allow: "GET" });
      }
      const url = new URL(request.url, `http://127.0.0.1:${port}`);

      if (url.pathname === "/") {
        return send(response, 200, "text/html; charset=utf-8", fs.readFileSync(PAGE));
      }
      if (url.pathname === "/api/exports") {
        return json(response, 200, savedExports(historyDir));
      }
      if (url.pathname === "/api/compare" || url.pathname === "/api/compare.xlsx") {
        const before = snapshotDir(historyDir, url.searchParams.get("before") || "");
        const after = snapshotDir(historyDir, url.searchParams.get("after") || "");
        const changes = compareSnapshots(before, after);
        if (url.pathname === "/api/compare") return json(response, 200, changes);
        const buffer = await comparisonWorkbook(changes).xlsx.writeBuffer();
        return send(response, 200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", Buffer.from(buffer), {
          "Content-Disposition": `attachment; filename="compare_${comparisonName(changes)}.xlsx"`
        });
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
      if (error.code === "EADDRINUSE" && triesLeft > 1) {
        resolve(listen(server, port + 1, triesLeft - 1));
      } else {
        reject(error);
      }
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

async function start({ historyDir = defaultHistory, port = FIRST_PORT,
                       open = process.env.COMPARE_UI_NO_BROWSER !== "1" } = {}) {
  const server = http.createServer();
  const actual = await listen(server, port, PORT_TRIES);
  server.on("request", handler(historyDir, actual));
  const url = `http://127.0.0.1:${actual}/`;
  console.log(`[COMPARE] Compare page: ${url}  (Ctrl+C to stop)`);
  if (!fs.existsSync(historyDir)) console.log("[COMPARE] No saved exports yet: run the export first.");
  if (open) openBrowser(url);
  return { server, port: actual, url };
}

if (require.main === module) {
  start().catch(error => {
    console.error("[COMPARE ERROR]", error.message);
    process.exitCode = 1;
  });
}

module.exports = { savedExports, start };
