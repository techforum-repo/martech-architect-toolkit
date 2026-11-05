const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const store = require("../src/store");
const profiles = require("../src/profiles");
const { start } = require("../src/app-server");

const T = "/conf/s/settings/wcm/templates";
const FAKE_MASTER = path.join(__dirname, "fixtures", "fake-master.js");

// prod: two runs (a template added in between) and a failed one; stage: one run.
function history() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "app-history-"));
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

async function app(t, port, extra = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "app-settings-"));
  const started = await start({ dir, root: history(), port, open: false, script: FAKE_MASTER, ...extra });
  t.after(() => started.server.close());
  const request = (pathname, { method = "GET", body, host = `127.0.0.1:${started.port}`, headers = {} } = {}) =>
    new Promise((resolve, reject) => {
      const req = http.request({ host: "127.0.0.1", port: started.port, path: pathname, method,
                                 headers: { Host: host, ...headers } }, response => {
        const chunks = [];
        response.on("data", chunk => chunks.push(chunk));
        response.on("end", () => {
          const text = Buffer.concat(chunks);
          let data = null;
          try { data = JSON.parse(text); } catch { /* not JSON */ }
          resolve({ status: response.statusCode, headers: response.headers, body: text, data });
        });
      });
      req.on("error", reject);
      if (body !== undefined) req.end(typeof body === "string" ? body : JSON.stringify(body));
      else req.end();
    });
  const post = (pathname, body, headers = {}) => request(pathname, {
    method: "POST", body, headers: { "Content-Type": "application/json", "X-App-Key": started.key, ...headers } });
  return { ...started, dir, request, post };
}

const VALID = {
  AEM_AUTHOR_URL: "https://author-p1-e2.adobeaemcloud.com",
  AEM_LOCAL_TOKEN: "secret-token-value",
  AEM_POLICY_ROOT: "/conf/s/settings/wcm/policies",
  AEM_TEMPLATE_ROOT: "/conf/s/settings/wcm/templates"
};

test("history and compare: over time and between environments", async t => {
  const { request } = await app(t, 18610);
  const page = await request("/");
  assert.match(page.body.toString(), /Compare environments/);
  assert.doesNotMatch(page.body.toString(), /__APP_KEY__/);

  const environments = (await request("/api/environments")).data;
  assert.deepEqual(environments.map(e => e.label), ["stage (p1-e3)", "prod (p1-e2)"]);
  const prod = environments[1];
  const compare = async (before, after) =>
    (await request(`/api/compare?before=${encodeURIComponent(before)}&after=${encodeURIComponent(after)}`)).data;
  assert.deepEqual((await compare(prod.runs[2].key, prod.runs[1].key)).rows.map(r => r.item), ["campaign (Campaign)"]);
  assert.deepEqual((await compare(prod.runs[1].key, environments[0].runs[0].key)).rows.map(r => r.item), ["event (Event)"]);

  const workbook = await request("/api/workbook?run=" + encodeURIComponent(prod.runs[1].key));
  assert.match(workbook.headers["content-disposition"], /Style-System_prod_2026-11-02_100000Z\.xlsx/);
  assert.equal((await request(`/api/compare?before=${encodeURIComponent(prod.runs[0].key)}&after=${encodeURIComponent(prod.runs[1].key)}`)).status, 404);
  assert.equal((await request("/api/workbook?run=../../etc")).status, 404);
  assert.equal((await request("/", { host: "evil.example:18610" })).status, 403);
});

test("changes need this session's key, a JSON body and no foreign origin", async t => {
  const { request, post } = await app(t, 18620);
  const body = { key: "prod", isNew: true, values: VALID };
  assert.equal((await post("/api/profiles", body, { "X-App-Key": "wrong" })).status, 403);
  assert.equal((await post("/api/profiles", body, { Origin: "https://evil.example" })).status, 403);
  // What a form on another website could send: no key, not JSON.
  const form = await request("/api/profiles", { method: "POST", body: "key=prod",
                                                headers: { "Content-Type": "application/x-www-form-urlencoded" } });
  assert.equal(form.status, 403);
  assert.equal((await post("/api/profiles", body, { "Content-Type": "text/plain" })).status, 415);
  assert.equal((await request("/api/profiles", { method: "DELETE" })).status, 405);
});

test("settings: create, list without the token, refuse a name another environment has", async t => {
  const { request, post, dir } = await app(t, 18630);
  assert.equal((await post("/api/profiles", { key: "prod", isNew: true, values: VALID })).status, 200);
  assert.ok(fs.existsSync(path.join(dir, ".env.prod")));

  const listed = (await request("/api/profiles")).data;
  assert.deepEqual(listed.profiles.map(p => [p.key, p.environment]), [["prod", "prod (p1-e2)"]]);
  assert.equal(listed.profiles[0].token.set, true);
  assert.ok(!JSON.stringify(listed).includes("secret-token-value"));
  assert.ok(listed.fields.some(f => f.key === "AEM_LOCAL_TOKEN" && f.secret));

  // "stage" already names p1-e3; a settings file called stage for p1-e2 would mix them up.
  const clash = await post("/api/profiles", { key: "stage", isNew: true, values: VALID });
  assert.equal(clash.status, 422);
  assert.match(clash.data.errors.key, /already the name of stage \(p1-e3\)/);
  const invalid = await post("/api/profiles", { key: "qa", isNew: true, values: { ...VALID, AEM_POLICY_ROOT: "/x" } });
  assert.deepEqual(Object.keys(invalid.data.errors), ["AEM_POLICY_ROOT"]);
});

test("runs: one at a time per settings file, with its log; cancel stops it", async t => {
  const { request, post, dir } = await app(t, 18640);
  profiles.write("prod", VALID, dir);
  // The app reads settings files, never loads them: a run gets only its own file's values.
  fs.writeFileSync(path.join(dir, ".env"), "AEM_AUTHOR_URL=https://default.example.com\n");
  assert.equal((await request("/api/profiles")).data.profiles.length, 2);
  assert.equal(process.env.AEM_AUTHOR_URL, undefined);

  process.env.FAKE_SECONDS = "5";
  const job = (await post("/api/jobs", { profile: "prod" })).data;
  delete process.env.FAKE_SECONDS;
  assert.equal(job.status, "running");
  assert.equal((await post("/api/jobs", { profile: "prod" })).status, 409);
  assert.equal((await post("/api/jobs", { profile: "nope" })).status, 404);

  let view;
  for (let i = 0; i < 50; i++) {
    view = (await request(`/api/jobs/${job.id}`)).data;
    if (view.lines.length >= 4) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(view.runKey, "env-prod/2026-11-05_120000Z");
  assert.ok(view.lines.some(line => line.includes("History dir: ")));
  assert.ok(view.lines.includes("[MASTER] Leaked: none"));
  assert.equal((await request(`/api/jobs/${job.id}?from=2`)).data.lines.length, view.lineCount - 2);

  assert.equal((await post(`/api/jobs/${job.id}/cancel`, {})).data.cancelled, true);
  for (let i = 0; i < 50 && view.finishedAt === null; i++) {
    await new Promise(resolve => setTimeout(resolve, 100));
    view = (await request(`/api/jobs/${job.id}`)).data;
  }
  assert.equal(view.status, "cancelled");
});

test("deleting a run from History: guarded, only listed runs, gone afterwards", async t => {
  const { request, post } = await app(t, 18650);
  const prod = (await request("/api/environments")).data.find(env => env.name === "prod");
  const oldest = prod.runs[prod.runs.length - 1].key;

  assert.equal((await post("/api/runs/delete", { run: oldest }, { "X-App-Key": "wrong" })).status, 403);
  assert.equal((await post("/api/runs/delete", { run: "../../etc" })).status, 404);
  const deleted = await post("/api/runs/delete", { run: oldest });
  assert.equal(deleted.status, 200);
  assert.equal(deleted.data.environmentRemoved, false);

  const after = (await request("/api/environments")).data.find(env => env.name === "prod");
  assert.deepEqual(after.runs.map(run => run.key).includes(oldest), false);
  assert.equal((await request("/api/workbook?run=" + encodeURIComponent(oldest))).status, 404);
});
