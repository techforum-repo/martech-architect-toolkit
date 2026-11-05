const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const store = require("../src/store");

const PROD = "https://author-p12345-e67890.adobeaemcloud.com";
const STAGE = "https://author-p12345-e11111.adobeaemcloud.com";

const tempRoot = () => fs.mkdtempSync(path.join(os.tmpdir(), "export-store-"));

test("environment ids come from the author URL", () => {
  assert.equal(store.environmentId(PROD), "p12345-e67890");
  assert.equal(store.environmentId("https://Author.Example.com:4502/"), "author.example.com");
  assert.equal(store.cleanName(" Prod "), "prod");
  assert.equal(store.cleanName(""), null);
  assert.throws(() => store.cleanName("prod env"), /letters, digits/);
});

test("a name belongs to one environment", () => {
  const root = tempRoot();
  const prod = store.registerEnvironment(root, { author: PROD, name: "prod" });
  assert.equal(store.label(prod), "prod (p12345-e67890)");
  assert.throws(() => store.registerEnvironment(root, { author: STAGE, name: "prod" }), /already belongs to p12345-e67890/);
  // Registering again without a name keeps it; found by name or id.
  assert.equal(store.registerEnvironment(root, { author: PROD }).name, "prod");
  assert.equal(store.findEnvironment(root, "PROD").id, "p12345-e67890");
  assert.equal(store.findEnvironment(root, "p12345-e67890").name, "prod");
  assert.equal(store.findEnvironment(root, "stage"), null);
});

test("runs get their own folders, also within one second", () => {
  const root = tempRoot();
  const env = store.registerEnvironment(root, { author: PROD, name: "prod" });
  const at = new Date("2026-11-05T10:30:12.345Z");
  const first = store.createRun(env, { policyRoot: "/conf/s/settings/wcm/policies" }, at);
  const second = store.createRun(env, {}, at);
  assert.equal(first.id, "2026-11-05_103012Z");
  assert.equal(second.id, "2026-11-05_103012Z-2");
  assert.equal(first.meta.status, "running");
  assert.equal(first.meta.environmentName, "prod");
  assert.deepEqual(store.listRuns(env.dir).map(r => r.id), [first.id, second.id]);
});

test("only finished runs with data are usable; pruning keeps the current run", () => {
  const root = tempRoot();
  const env = store.registerEnvironment(root, { author: PROD });
  const statuses = ["complete", "failed", "incomplete", "complete", "running"];
  const runs = statuses.map((status, day) => {
    const run = store.createRun(env, {}, new Date(`2026-11-0${day + 1}T10:00:00Z`));
    store.updateRun(run.dir, { status });
    return run;
  });
  assert.deepEqual(store.listRuns(env.dir, { usable: true }).map(r => r.meta.status), ["complete", "incomplete", "complete"]);

  assert.equal(store.pruneRuns(env.dir, 2, runs[4].dir), 3);
  assert.deepEqual(store.listRuns(env.dir).map(r => r.id), [runs[3].id, runs[4].id]);
});

test("a run loads for comparing, complete only when its status says so", () => {
  const root = tempRoot();
  const env = store.registerEnvironment(root, { author: PROD });
  const run = store.createRun(env, {});
  store.writeJson(path.join(run.dir, store.FILES.policies), [{ path: "/p" }]);
  store.updateRun(run.dir, { status: "incomplete" });
  const loaded = store.loadRun(run.dir);
  assert.deepEqual(loaded.policies, [{ path: "/p" }]);
  assert.equal(loaded.meta.complete, false);
  assert.equal(loaded.templates, null);
});

test("exports saved in the earlier layout are moved into their environment", () => {
  const root = tempRoot();
  const legacy = path.join(root, "history");
  const old = path.join(legacy, "author-p12345-e67890.adobeaemcloud.com", "2026-11-04T17-36-41Z");
  fs.mkdirSync(old, { recursive: true });
  fs.writeFileSync(path.join(old, "meta.json"), JSON.stringify({
    author: PROD, createdAt: "2026-11-04T17:36:41.000Z", complete: false,
    policyRoot: "/conf/s/settings/wcm/policies", templateRoot: "/conf/s/settings/wcm/templates"
  }));
  fs.writeFileSync(path.join(old, "policies.json"), "[]");
  fs.writeFileSync(path.join(old, "tokens.json"), "[]");

  assert.equal(store.migrateLegacy(root, legacy), 1);
  assert.equal(fs.existsSync(legacy), false);
  const [run] = store.listRuns(path.join(store.environmentsDir(root), "p12345-e67890"));
  assert.equal(run.id, "2026-11-04_173641Z");
  assert.equal(run.meta.status, "incomplete");
  assert.equal(run.meta.policyRoot, "/conf/s/settings/wcm/policies");
  assert.ok(fs.existsSync(path.join(run.dir, store.FILES.policies)));
  assert.ok(fs.existsSync(path.join(run.dir, store.FILES.tokens)));
});
