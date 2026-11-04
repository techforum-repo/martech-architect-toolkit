const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const snapshots = require("../src/snapshot");
const { start } = require("../src/ui-server");

function history() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "compare-ui-"));
  const save = (day, templates) => snapshots.save(dir, {
    meta: { id: `2026-11-0${day}T10-00-00Z`, environment: "author.example.com", createdAt: `2026-11-0${day}T10:00:00.000Z`,
            complete: true, policyRoot: "/conf/s/settings/wcm/policies", templateRoot: "/conf/s/settings/wcm/templates" },
    policies: [], templates, usage: [], tokens: null, css: null
  });
  save(1, [{ path: "/conf/s/settings/wcm/templates/page", name: "page", title: "Page", status: "enabled" }]);
  save(2, [{ path: "/conf/s/settings/wcm/templates/page", name: "page", title: "Page", status: "enabled" },
           { path: "/conf/s/settings/wcm/templates/campaign", name: "campaign", title: "Campaign", status: "draft" }]);
  return dir;
}

function get(port, pathname, { host = `127.0.0.1:${port}`, method = "GET" } = {}) {
  return new Promise((resolve, reject) => {
    const request = http.request({ host: "127.0.0.1", port, path: pathname, method, headers: { Host: host } }, response => {
      const chunks = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode, type: response.headers["content-type"],
                                         body: Buffer.concat(chunks) }));
    });
    request.on("error", reject);
    request.end();
  });
}

test("the compare page lists exports, compares them and refuses anything else", async t => {
  const { server, port } = await start({ historyDir: history(), port: 18510, open: false });
  t.after(() => server.close());

  const page = await get(port, "/");
  assert.equal(page.status, 200);
  assert.match(page.body.toString(), /Compare exports/);

  const exports = JSON.parse((await get(port, "/api/exports")).body);
  assert.deepEqual(exports.map(e => e.key),
                   ["author.example.com/2026-11-02T10-00-00Z", "author.example.com/2026-11-01T10-00-00Z"]);

  const query = `before=${encodeURIComponent(exports[1].key)}&after=${encodeURIComponent(exports[0].key)}`;
  const changes = JSON.parse((await get(port, "/api/compare?" + query)).body);
  assert.deepEqual(changes.rows.map(r => [r.area, r.change, r.item]), [["Template", "Added", "campaign (Campaign)"]]);

  const workbook = await get(port, "/api/compare.xlsx?" + query);
  assert.equal(workbook.status, 200);
  assert.equal(workbook.body.subarray(0, 2).toString(), "PK");  // an .xlsx is a zip

  // Only exports the listing returned, never a path from the request.
  assert.equal((await get(port, "/api/compare?before=../../etc&after=" + encodeURIComponent(exports[0].key))).status, 404);
  // Only requests addressed to this machine's own address, and only reads.
  assert.equal((await get(port, "/", { host: `evil.example:${port}` })).status, 403);
  assert.equal((await get(port, "/api/exports", { method: "POST" })).status, 405);
});
