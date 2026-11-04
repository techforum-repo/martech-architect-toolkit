const assert = require("node:assert/strict");
const test = require("node:test");

const { diffSnapshots } = require("../src/diff");

const T = "/conf/site/settings/wcm/templates";
const P = "/conf/site/settings/wcm/policies";

function template(name, extra = {}) {
  return { path: `${T}/${name}`, name, title: name, status: "enabled", properties: {}, ...extra };
}

function policy(id, styles, properties = {}) {
  return {
    path: `${P}/site/components/teaser/${id}`,
    componentPath: "site/components/teaser",
    properties: { "jcr:title": "Teaser " + id, ...properties },
    styleGroups: [{ label: "Look", styles }],
    ungroupedStyles: []
  };
}

function style(item, id, label, classes) {
  return { path: `${P}/site/components/teaser/x/cq:styleGroups/item0/cq:styles/${item}`, id, label, classes };
}

function usage(templateName, location, policyId) {
  return { templatePath: `${T}/${templateName}/policies/jcr:content${location}`,
           resolvedPolicyPath: `${P}/site/components/teaser/${policyId}` };
}

function snapshot(parts = {}) {
  return { meta: { environment: "author.example.com", complete: true }, templates: [], usage: [], policies: [],
           tokens: null, css: null, ...parts };
}

const find = (result, area, change) => result.rows.filter(r => r.area === area && r.change === change);

test("templates added, removed and changed", () => {
  const result = diffSnapshots(
    snapshot({ templates: [template("article"), template("landing"), template("old")] }),
    snapshot({ templates: [template("article", { status: "disabled", lastModifiedBy: "jane" }),
                           template("landing"), template("campaign", { status: "draft" })] }));
  assert.deepEqual(find(result, "Template", "Added").map(r => [r.item, r.details]),
                   [["campaign (campaign)", "status: draft"]]);
  assert.deepEqual(find(result, "Template", "Removed").map(r => r.item), ["old (old)"]);
  const [changed] = find(result, "Template", "Changed");
  assert.equal(changed.details, 'status: "enabled" → "disabled"');
  assert.equal(changed.modifiedBy, "jane");
  assert.deepEqual(result.counts.Template, { Added: 1, Removed: 1, Changed: 1 });
});

test("the policy a template maps to a component", () => {
  const result = diffSnapshots(
    snapshot({ usage: [usage("article", "/root/teaser", "policy_1"), usage("article", "/root/old", "policy_1")] }),
    snapshot({ usage: [usage("article", "/root/teaser", "policy_2"), usage("article", "/root/hero", "policy_1"),
                       usage("article", "", "policy_9")] }));
  assert.deepEqual(find(result, "Template policy", "Changed").map(r => r.item), ["article › root/teaser"]);
  assert.match(find(result, "Template policy", "Changed")[0].details, /policy_1 → .*policy_2/);
  assert.deepEqual(find(result, "Template policy", "Added").map(r => r.item).sort(),
                   ["article › (page)", "article › root/hero"]);
  assert.deepEqual(find(result, "Template policy", "Removed").map(r => r.item), ["article › root/old"]);
});

test("policy properties, ignoring repository bookkeeping", () => {
  const result = diffSnapshots(
    snapshot({ policies: [policy("policy_1", [], { "jcr:lastModified": "Mon", allowedHeadingSizes: ["h2"] })] }),
    snapshot({ policies: [policy("policy_1", [], { "jcr:lastModified": "Tue", allowedHeadingSizes: ["h2", "h3"] }),
                          policy("policy_2", [])] }));
  assert.deepEqual(find(result, "Policy", "Changed").map(r => r.details),
                   ['allowedHeadingSizes: ["h2"] → ["h2","h3"]']);
  assert.equal(find(result, "Policy", "Added").length, 1);
  // Only lastModified changing isn't a change.
  const same = diffSnapshots(snapshot({ policies: [policy("policy_1", [], { "jcr:lastModified": "Mon" })] }),
                             snapshot({ policies: [policy("policy_1", [], { "jcr:lastModified": "Tue" })] }));
  assert.deepEqual(same.rows, []);
});

test("styles are matched by style ID, so reordering isn't a change", () => {
  const before = [style("item0", "1", "Dark", "theme-dark"), style("item1", "2", "Wide", "wide full")];
  const reordered = [style("item0", "2", "Wide", "full wide"), style("item1", "1", "Dark", "theme-dark")];
  assert.deepEqual(diffSnapshots(snapshot({ policies: [policy("policy_1", before)] }),
                                 snapshot({ policies: [policy("policy_1", reordered)] })).rows, []);

  const after = [style("item0", "1", "Dark mode", "theme-dark"), style("item2", "3", "Compact", "compact")];
  const result = diffSnapshots(snapshot({ policies: [policy("policy_1", before)] }),
                               snapshot({ policies: [policy("policy_1", after)] }));
  assert.deepEqual(find(result, "Style", "Changed").map(r => r.details), ['label: "Dark" → "Dark mode"']);
  assert.deepEqual(find(result, "Style", "Added").map(r => r.item), ["site/components/teaser › Teaser policy_1 › Compact"]);
  assert.deepEqual(find(result, "Style", "Removed").map(r => r.details), ["classes: full wide; group: Look"]);
});

test("theme tokens and CSS only when both exports read the front end", () => {
  const token = (name, value) => ({ theme: "corporate", name, value, context: ":root" });
  const css = (hash, rules) => [{ stylePath: "/s/1", theme: "corporate", label: "Dark", matchStatus: "Direct", hash, rules }];
  const result = diffSnapshots(
    snapshot({ tokens: [token("--brand", "#036"), token("--old", "1px")], css: css("a", 2) }),
    snapshot({ tokens: [token("--brand", "#047"), token("--new", "2px")], css: css("b", 3) }));
  assert.deepEqual(find(result, "Theme token", "Changed").map(r => r.details), ["value: #036 → #047"]);
  assert.equal(find(result, "Theme token", "Added").length, 1);
  assert.equal(find(result, "Theme token", "Removed").length, 1);
  assert.deepEqual(find(result, "Style CSS", "Changed").map(r => r.details), ["2 → 3 rule(s)"]);

  const withoutFe = diffSnapshots(snapshot({ tokens: [token("--brand", "#036")] }), snapshot());
  assert.deepEqual(withoutFe.rows, []);
  assert.ok(withoutFe.notes.some(n => n.includes("not compared")));
});

test("notes for incomplete exports and other environments", () => {
  const result = diffSnapshots(snapshot({ meta: { environment: "stage", complete: false } }),
                               snapshot({ meta: { environment: "prod", complete: true } }));
  assert.ok(result.notes.some(n => n.includes("incomplete")));
  assert.ok(result.notes.some(n => n.includes("stage → prod")));
});
