// What changed between two export snapshots (see snapshot.js): templates,
// the policies templates map to components, policies, styles, theme tokens
// and the CSS that styles' classes reach.
//
// Pure functions, no I/O, so they can be tested on their own.

// Repository bookkeeping that changes without the configuration changing.
const VOLATILE = new Set([
  "jcr:created", "jcr:createdBy", "jcr:lastModified", "jcr:lastModifiedBy",
  "cq:lastModified", "cq:lastModifiedBy", "jcr:uuid", "jcr:mixinTypes",
  "cq:lastReplicated", "cq:lastReplicatedBy", "cq:lastReplicationAction",
  "cq:lastReplicated_publish", "cq:lastReplicatedBy_publish", "cq:lastReplicationAction_publish"
]);

const MAX_VALUE = 80;
const MAX_PROPERTIES = 6;

function short(value) {
  const text = value === undefined ? "(none)" : JSON.stringify(value);
  return text.length > MAX_VALUE ? text.slice(0, MAX_VALUE - 1) + "…" : text;
}

function byKey(items, key) {
  const map = new Map();
  for (const item of items || []) map.set(key(item), item);
  return map;
}

// Every key in either map: [key, before or undefined, after or undefined].
function* pairs(before, after) {
  for (const [key, value] of before) yield [key, value, after.get(key)];
  for (const [key, value] of after) {
    if (!before.has(key)) yield [key, undefined, value];
  }
}

function changedFields(before, after, fields) {
  return fields
    .filter(([, get]) => JSON.stringify(get(before)) !== JSON.stringify(get(after)))
    .map(([name, get]) => `${name}: ${short(get(before))} → ${short(get(after))}`);
}

function changedProperties(before = {}, after = {}) {
  const names = [...new Set([...Object.keys(before), ...Object.keys(after)])]
    .filter(name => !VOLATILE.has(name))
    .filter(name => JSON.stringify(before[name]) !== JSON.stringify(after[name]))
    .sort();
  const shown = names.slice(0, MAX_PROPERTIES)
    .map(name => `${name}: ${short(before[name])} → ${short(after[name])}`);
  if (names.length > MAX_PROPERTIES) shown.push(`+${names.length - MAX_PROPERTIES} more`);
  return shown;
}

function templateName(templatePath) {
  return templatePath.split("/templates/")[1]?.split("/")[0] || templatePath;
}

function policyLabel(policy) {
  const name = policy.properties?.["jcr:title"] || policy.path.split("/").pop();
  return `${policy.componentPath || ""} › ${name}`;
}

function classes(value) {
  const text = Array.isArray(value) ? value.join(" ") : String(value || "");
  return text.split(/\s+/).filter(Boolean).sort().join(" ");
}

function styles(policies) {
  const rows = [];
  for (const policy of policies || []) {
    const grouped = (policy.styleGroups || []).flatMap(group =>
      (group.styles || []).map(style => ({ style, group: group.label || "" })));
    const ungrouped = (policy.ungroupedStyles || []).map(style => ({ style, group: "Ungrouped" }));
    for (const { style, group } of [...grouped, ...ungrouped]) {
      rows.push({
        // The style ID survives reordering, which renames item0, item1, …
        key: `${policy.path}|${style.id ?? style.path}`,
        policy,
        label: style.label ?? "",
        classes: classes(style.classes),
        group
      });
    }
  }
  return rows;
}

function modified(item) {
  return { by: item?.lastModifiedBy ?? item?.properties?.["jcr:lastModifiedBy"] ?? "",
           at: item?.lastModified ?? item?.properties?.["jcr:lastModified"] ?? "" };
}

function diffSnapshots(before, after) {
  const rows = [];
  const add = (area, change, item, details = "", source = undefined) => {
    const { by, at } = modified(source);
    rows.push({ area, change, item, details, modifiedBy: by, modifiedAt: at });
  };

  // Templates
  for (const [, old, now] of pairs(byKey(before.templates, t => t.path), byKey(after.templates, t => t.path))) {
    const name = (now || old).name || templateName((now || old).path);
    const label = (now || old).title ? `${name} (${(now || old).title})` : name;
    if (!old) add("Template", "Added", label, now.status ? `status: ${now.status}` : "", now);
    else if (!now) add("Template", "Removed", label, "", old);
    else {
      const details = changedFields(old, now, [["title", t => t.title], ["status", t => t.status]]);
      if (details.length) add("Template", "Changed", label, details.join("; "), now);
    }
  }

  // Which policy each template assigns to each component location
  const mappings = refs => {
    const map = new Map();
    for (const ref of refs || []) {
      const key = ref.templatePath;
      map.set(key, [...(map.get(key) || []), ref.resolvedPolicyPath].sort());
    }
    return map;
  };
  for (const [location, old, now] of pairs(mappings(before.usage), mappings(after.usage))) {
    const where = location.split("/policies/jcr:content")[1] || "(page)";
    const item = `${templateName(location)} › ${where.replace(/^\//, "") || "(page)"}`;
    if (!old) add("Template policy", "Added", item, `policy: ${now.join(", ")}`);
    else if (!now) add("Template policy", "Removed", item, `policy was: ${old.join(", ")}`);
    else if (old.join() !== now.join()) {
      add("Template policy", "Changed", item, `policy: ${old.join(", ")} → ${now.join(", ")}`);
    }
  }

  // Policies (their own properties; styles are compared one by one below)
  for (const [, old, now] of pairs(byKey(before.policies, p => p.path), byKey(after.policies, p => p.path))) {
    if (!old) add("Policy", "Added", policyLabel(now), now.path, now);
    else if (!now) add("Policy", "Removed", policyLabel(old), old.path, old);
    else {
      const details = changedProperties(old.properties, now.properties);
      if (details.length) add("Policy", "Changed", policyLabel(now), details.join("; "), now);
    }
  }

  // Styles
  const styleItem = style => `${policyLabel(style.policy)} › ${style.label || style.classes || "(no label)"}`;
  for (const [, old, now] of pairs(byKey(styles(before.policies), s => s.key), byKey(styles(after.policies), s => s.key))) {
    if (!old) add("Style", "Added", styleItem(now), `classes: ${now.classes}; group: ${now.group}`, now.policy);
    else if (!now) add("Style", "Removed", styleItem(old), `classes: ${old.classes}; group: ${old.group}`, old.policy);
    else {
      const details = changedFields(old, now, [["label", s => s.label], ["classes", s => s.classes],
                                               ["group", s => s.group]]);
      if (details.length) add("Style", "Changed", styleItem(now), details.join("; "), now.policy);
    }
  }

  // Theme tokens, only when both exports read the front-end CSS
  const compareFe = Boolean(before.tokens && after.tokens);
  if (compareFe) {
    const tokenKey = t => `${t.theme}|${t.name}|${t.context}`;
    const tokenItem = t => `${t.theme} › ${t.name}` + (t.context ? ` (${t.context})` : "");
    for (const [, old, now] of pairs(byKey(before.tokens, tokenKey), byKey(after.tokens, tokenKey))) {
      if (!old) add("Theme token", "Added", tokenItem(now), `value: ${now.value}`);
      else if (!now) add("Theme token", "Removed", tokenItem(old), `value was: ${old.value}`);
      else if (old.value !== now.value) add("Theme token", "Changed", tokenItem(now), `value: ${old.value} → ${now.value}`);
    }
  }

  // The CSS each style's classes reach, per theme (styles added or removed
  // are reported above; this is CSS changing under an unchanged style)
  const compareCss = Boolean(before.css && after.css);
  if (compareCss) {
    const cssKey = c => `${c.stylePath}|${c.theme}`;
    for (const [, old, now] of pairs(byKey(before.css, cssKey), byKey(after.css, cssKey))) {
      if (!old || !now || old.hash === now.hash) continue;
      const details = [`${old.rules} → ${now.rules} rule(s)`];
      if (old.matchStatus !== now.matchStatus) details.push(`match: ${old.matchStatus} → ${now.matchStatus}`);
      add("Style CSS", "Changed", `${now.theme} › ${now.label || now.stylePath}`, details.join("; "));
    }
  }

  const order = ["Template", "Template policy", "Policy", "Style", "Theme token", "Style CSS"];
  const changeOrder = ["Added", "Removed", "Changed"];
  rows.sort((a, b) =>
    order.indexOf(a.area) - order.indexOf(b.area) ||
    changeOrder.indexOf(a.change) - changeOrder.indexOf(b.change) ||
    a.item.localeCompare(b.item));

  const counts = {};
  for (const row of rows) {
    counts[row.area] = counts[row.area] || { Added: 0, Removed: 0, Changed: 0 };
    counts[row.area][row.change]++;
  }

  const notes = [];
  if (before.meta?.complete === false || after.meta?.complete === false) {
    notes.push("One of the exports was incomplete (see its validation report): some additions or removals may only be missing data.");
  }
  if (!compareFe) notes.push("Theme tokens and CSS not compared: front-end CSS wasn't read in both exports.");
  if (before.meta?.environment && after.meta?.environment && before.meta.environment !== after.meta.environment) {
    notes.push(`Different environments: ${before.meta.environment} → ${after.meta.environment}.`);
  }

  return { rows, counts, notes };
}

module.exports = { diffSnapshots, VOLATILE };
