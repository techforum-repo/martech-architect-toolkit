const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const snapshots = require("../src/snapshot");

function outputDir() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "export-output-"));
  const write = (name, value) => fs.writeFileSync(path.join(dir, name), JSON.stringify(value));
  write("policies.json", [{ path: "/conf/s/settings/wcm/policies/x/policy_1", styleGroups: [{ styles: [
    { path: "/p/style1", label: "Dark" }] }], ungroupedStyles: [] }]);
  write("templates.json", [{ path: "/conf/s/settings/wcm/templates/page", name: "page" }]);
  write("policy-usage.json", []);
  write("validation-report.json", { complete: false });
  write("fe-data.json", { themes: ["a", "b"], loadedThemes: ["a"], tokens: [{ theme: "a", name: "--x", value: "1" }] });
  write("style-css-mapping.json", { rows: [{ stylePath: "/p/style1", theme: "a", matchStatus: "Direct",
    cssRules: [{ source: "a.css", contexts: [], selector: ".dark", declarations: [{ property: "color", value: "#000" }] }] }] });
  return dir;
}

test("environment names and snapshot ids are safe folder names", () => {
  assert.equal(snapshots.environmentName("https://Author-p1-e2.adobeaemcloud.com/"), "author-p1-e2.adobeaemcloud.com");
  assert.equal(snapshots.snapshotId(new Date("2026-11-04T17:30:05.123Z")), "2026-11-04T17-30-05Z");
});

test("a snapshot from an export's output, saved, listed and loaded", () => {
  const out = outputDir();
  const history = path.join(out, "history");
  const current = snapshots.fromOutput(out, { author: "https://author.example.com", policyRoot: "/conf/s/settings/wcm/policies",
                                              createdAt: new Date("2026-11-04T10:00:00Z") });
  assert.equal(current.meta.complete, false);
  assert.deepEqual(current.meta.themes, ["a"]);
  assert.equal(current.css[0].label, "Dark");
  assert.equal(current.css[0].rules, 1);

  const dir = snapshots.save(history, current);
  assert.equal(path.relative(history, dir), path.join("author.example.com", "2026-11-04T10-00-00Z"));
  const loaded = snapshots.load(dir);
  assert.deepEqual(loaded.policies, current.policies);
  assert.deepEqual(snapshots.list(history).map(s => s.id), ["2026-11-04T10-00-00Z"]);
});

test("the same CSS gives the same fingerprint, whatever the rule order", () => {
  const rule = selector => ({ source: "a.css", contexts: [], selector, declarations: [] });
  const one = snapshots.cssSummary({ rows: [{ stylePath: "/s", theme: "a", cssRules: [rule(".a"), rule(".b")] }]}, []);
  const two = snapshots.cssSummary({ rows: [{ stylePath: "/s", theme: "a", cssRules: [rule(".b"), rule(".a")] }]}, []);
  const three = snapshots.cssSummary({ rows: [{ stylePath: "/s", theme: "a", cssRules: [rule(".c")] }]}, []);
  assert.equal(one[0].hash, two[0].hash);
  assert.notEqual(one[0].hash, three[0].hash);
});

test("old snapshots are pruned per environment", () => {
  const out = outputDir();
  const history = path.join(out, "history");
  for (let day = 1; day <= 4; day++) {
    snapshots.save(history, snapshots.fromOutput(out, { author: "https://a.example.com",
                                                        createdAt: new Date(`2026-11-0${day}T10:00:00Z`) }));
  }
  snapshots.save(history, snapshots.fromOutput(out, { author: "https://b.example.com" }));
  assert.equal(snapshots.prune(history, "a.example.com", 2), 2);
  assert.deepEqual(snapshots.list(history, "a.example.com").map(s => s.id),
                   ["2026-11-03T10-00-00Z", "2026-11-04T10-00-00Z"]);
  assert.equal(snapshots.list(history, "b.example.com").length, 1);
});
