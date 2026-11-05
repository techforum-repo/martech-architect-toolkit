const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const store = require("../src/store");
const { start } = require("../src/ui-server");

const T = "/conf/s/settings/wcm/templates";

// prod: two runs (a template added in between) and a failed one; stage: one run.
function exports() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "compare-ui-"));
  const run = (env, day, status, templates) => {
    const created = store.createRun(env, { policyRoot: "/conf/s/settings/wcm/policies", templateRoot: T },
                                    new Date(`2026-11-0${day}T10:00:00Z`));
    store.writeJson(path.join(created.dir, store.FILES.policies), []);
    store.writeJson(path.join(created.dir, store.FILES.templates), templates);
    store.writeJson(path.join(created.dir, store.FILES.usage), []);
    store.updateRun(created.dir, { status });
    if (status === "complete") fs.writeFileSync(path.join(created.dir, `Style-System_${env.name}_${created.id}.xlsx`), "PK");
    return created;
  };
  const page = { path: `${T}/page`, name: "page", title: "Page", status: "enabled" };
  const campaign = { path: `${T}/campaign`, name: "campaign", title: "Campaign", status: "draft" };
  const prod = store.registerEnvironment(root, { author: "https://author-p1-e2.adobeaemcloud.com", name: "prod" });
  const stage = store.registerEnvironment(root, { author: "https://author-p1-e3.adobeaemcloud.com", name: "stage" });
  run(prod, 1, "complete", [page]);
  run(prod, 2, "complete", [page, campaign]);
  run(prod, 3, "failed", []);
  run(stage, 4, "complete", [page, campaign, { ...campaign, path: `${T}/event`, name: "event", title: "Event" }]);
  return root;
}

function get(port, pathname, { host = `127.0.0.1:${port}`, method = "GET" } = {}) {
  return new Promise((resolve, reject) => {
    const request = http.request({ host: "127.0.0.1", port, path: pathname, method, headers: { Host: host } }, response => {
      const chunks = [];
      response.on("data", chunk => chunks.push(chunk));
      response.on("end", () => resolve({ status: response.statusCode, headers: response.headers, body: Buffer.concat(chunks) }));
    });
    request.on("error", reject);
    request.end();
  });
}

test("the compare page: environments, runs, comparisons and downloads", async t => {
  const { server, port } = await start({ root: exports(), port: 18510, open: false });
  t.after(() => server.close());

  assert.match((await get(port, "/")).body.toString(), /Between environments/);

  const environments = JSON.parse((await get(port, "/api/environments")).body);
  assert.deepEqual(environments.map(e => e.label), ["stage (p1-e3)", "prod (p1-e2)"]);  // latest run first
  const prod = environments[1];
  assert.deepEqual(prod.runs.map(r => r.status), ["failed", "complete", "complete"]);  // newest first
  assert.equal(prod.runs[1].workbook, true);

  const compare = async (before, after) =>
    JSON.parse((await get(port, `/api/compare?before=${encodeURIComponent(before)}&after=${encodeURIComponent(after)}`)).body);

  // Over time, on prod.
  const overTime = await compare(prod.runs[2].key, prod.runs[1].key);
  assert.deepEqual(overTime.rows.map(r => [r.change, r.item]), [["Added", "campaign (Campaign)"]]);

  // Between environments: what stage has that prod doesn't.
  const between = await compare(prod.runs[1].key, environments[0].runs[0].key);
  assert.deepEqual(between.rows.map(r => [r.change, r.item]), [["Added", "event (Event)"]]);
  assert.ok(between.notes.some(n => n.includes("prod → stage")));

  // A run's own workbook, and the comparison as a workbook.
  const workbook = await get(port, "/api/workbook?run=" + encodeURIComponent(prod.runs[1].key));
  assert.equal(workbook.status, 200);
  assert.match(workbook.headers["content-disposition"], /Style-System_prod_2026-11-02_100000Z\.xlsx/);
  const comparison = await get(port, `/api/compare.xlsx?before=${encodeURIComponent(prod.runs[2].key)}&after=${encodeURIComponent(prod.runs[1].key)}`);
  assert.equal(comparison.body.subarray(0, 2).toString(), "PK");

  // Failed runs aren't compared; only listed runs, never a path; only this host; only reads.
  assert.equal((await get(port, `/api/compare?before=${encodeURIComponent(prod.runs[0].key)}&after=${encodeURIComponent(prod.runs[1].key)}`)).status, 404);
  assert.equal((await get(port, "/api/workbook?run=../../etc")).status, 404);
  assert.equal((await get(port, "/", { host: `evil.example:${port}` })).status, 403);
  assert.equal((await get(port, "/api/environments", { method: "POST" })).status, 405);
});
