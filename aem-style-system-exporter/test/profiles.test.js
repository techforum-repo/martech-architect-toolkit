const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const profiles = require("../src/profiles");

const VALID = {
  AEM_AUTHOR_URL: "https://author-p1-e2.adobeaemcloud.com",
  AEM_LOCAL_TOKEN: "eyJhbGciOiJub25lIn0." + Buffer.from(JSON.stringify({ exp: 1893456000 })).toString("base64url") + ".",
  AEM_POLICY_ROOT: "/conf/site/settings/wcm/policies",
  AEM_TEMPLATE_ROOT: "/conf/site/settings/wcm/templates"
};

const folder = () => fs.mkdtempSync(path.join(os.tmpdir(), "profiles-"));

test("writing keeps comments and other settings, and quotes paths safely", () => {
  const dir = folder();
  fs.writeFileSync(path.join(dir, ".env.prod"), "# prod author\nAEM_AUTHOR_URL=https://old.example.com\nHISTORY_DIR=//share/exports\n");
  profiles.write("prod", { ...VALID, FE_PROJECT_PATH: "C:\\Projects\\new site\\fe" }, dir);
  const text = fs.readFileSync(path.join(dir, ".env.prod"), "utf8");
  assert.match(text, /^# prod author\nAEM_AUTHOR_URL=https:\/\/author-p1-e2/);
  assert.match(text, /HISTORY_DIR=\/\/share\/exports/);
  assert.match(text, /FE_PROJECT_PATH='C:\\Projects\\new site\\fe'/);
  const read = profiles.readFile(path.join(dir, ".env.prod"));
  assert.equal(read.FE_PROJECT_PATH, "C:\\Projects\\new site\\fe");  // backslashes kept as typed
  assert.equal(read.AEM_POLICY_ROOT, VALID.AEM_POLICY_ROOT);

  // Clearing a value removes its line; empty values aren't written.
  profiles.write("prod", { ...VALID, FE_PROJECT_PATH: "", MAX_NODES: "" }, dir);
  const cleared = fs.readFileSync(path.join(dir, ".env.prod"), "utf8");
  assert.doesNotMatch(cleared, /FE_PROJECT_PATH|MAX_NODES/);
  assert.match(cleared, /HISTORY_DIR=/);
});

test("the token is write-only: listed as set with its expiry, kept when left empty", () => {
  const dir = folder();
  profiles.write("prod", VALID, dir);
  const [listed] = profiles.list(dir);
  assert.equal(listed.key, "prod");
  assert.deepEqual(listed.token, { set: true, expires: "2030-01-01T00:00:00.000Z" });
  assert.ok(!JSON.stringify(listed).includes(VALID.AEM_LOCAL_TOKEN));

  const merged = profiles.merged("prod", { AEM_LOCAL_TOKEN: "", FE_THEMES: "corporate,retail" }, dir);
  assert.equal(merged.AEM_LOCAL_TOKEN, VALID.AEM_LOCAL_TOKEN);
  assert.equal(merged.FE_THEMES, "corporate,retail");
});

test("validation", () => {
  const dir = folder();
  assert.deepEqual(profiles.validate("prod", VALID, { isNew: true, dir }), {});
  const errors = profiles.validate("Prod env", { ...VALID, AEM_AUTHOR_URL: "http://author", AEM_LOCAL_TOKEN: "",
                                                 AEM_POLICY_ROOT: "/content/x", MAX_NODES: "0", FE_THEMES: "a\nb" }, { dir });
  assert.deepEqual(Object.keys(errors).sort(),
                   ["AEM_AUTHOR_URL", "AEM_LOCAL_TOKEN", "AEM_POLICY_ROOT", "FE_THEMES", "MAX_NODES", "key"]);
  profiles.write("prod", VALID, dir);
  assert.match(profiles.validate("prod", VALID, { isNew: true, dir }).key, /already exists/);
  assert.ok(profiles.validate("example", VALID, { dir }).key);
});

test(".env is listed as default when it has an author URL", () => {
  const dir = folder();
  fs.writeFileSync(path.join(dir, ".env"), "HISTORY_DIR=x\n");
  fs.writeFileSync(path.join(dir, ".env.example"), "AEM_AUTHOR_URL=https://x\n");
  assert.deepEqual(profiles.list(dir), []);
  fs.writeFileSync(path.join(dir, ".env"), `AEM_AUTHOR_URL=${VALID.AEM_AUTHOR_URL}\n`);
  profiles.write("stage", VALID, dir);
  assert.deepEqual(profiles.list(dir).map(p => p.key), ["default", "stage"]);
});

test("values are written so Node reads them back exactly, or refused", () => {
  const dir = folder();
  const values = ["/home/obrien/fe", "/home/o'brien/fe", "/home/o'brien/my fe", "C:\\Projects\\new site\\fe",
                  "C:\\fe\\new", "O'Brien", "a#b", "corporate"];
  for (const value of values) {
    assert.deepEqual(profiles.validate("qa", { ...VALID, FE_PROJECT_PATH: value }, { dir }), {}, value);
    profiles.write("qa", { ...VALID, FE_PROJECT_PATH: value }, dir);
    assert.equal(profiles.readFile(path.join(dir, ".env.qa")).FE_PROJECT_PATH, value, value);
  }
  // A ' with a \ and a space can't be written for Node's reader: refused, not cut short.
  assert.ok(profiles.validate("qa", { ...VALID, FE_PROJECT_PATH: "C:\\Users\\O'Brien\\my fe" }, { dir }).FE_PROJECT_PATH);
  assert.equal(profiles.quote("C:\\Users\\O'Brien\\my fe"), null);
});

test("theme names only, and a name that isn't one never reads a file", () => {
  const dir = folder();
  assert.deepEqual(profiles.validate("qa", { ...VALID, FE_THEMES: "corporate, retail" }, { dir }), {});
  assert.ok(profiles.validate("qa", { ...VALID, FE_THEMES: "../secret" }, { dir }).FE_THEMES);
  fs.writeFileSync(path.join(dir, ".env.prod"), `AEM_LOCAL_TOKEN=saved\n`);
  assert.equal(profiles.merged("prod", {}, dir).AEM_LOCAL_TOKEN, "saved");
  assert.equal(profiles.merged("../prod", {}, dir).AEM_LOCAL_TOKEN, undefined);
});
