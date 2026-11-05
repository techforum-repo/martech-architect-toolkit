
const fs = require("node:fs");
const path = require("node:path");
const { URL } = require("node:url");

const settings = require("./settings");

settings.load();
const dataDir = settings.dataDir();

const author = process.env.AEM_AUTHOR_URL?.replace(/\/$/, "");
const token = process.env.AEM_LOCAL_TOKEN?.trim();
const policyRoot = process.env.AEM_POLICY_ROOT;
const templateRoot = process.env.AEM_TEMPLATE_ROOT;

const maxDepth = Number(process.env.MAX_DEPTH || 30);
const maxNodes = Number(process.env.MAX_NODES || 15000);
const requestTimeout = Number(process.env.REQUEST_TIMEOUT || 30000);
const progressInterval = Number(process.env.PROGRESS_INTERVAL || 25);
const fetchDepth = Number(process.env.FETCH_DEPTH || 3);
const concurrency = Number(process.env.CONCURRENCY || 4);

if (!author || !token || !policyRoot || !templateRoot) {
  throw new Error("Missing required AEM configuration in .env");
}

if (!/^https:\/\//.test(author)) {
  throw new Error("AEM_AUTHOR_URL must use HTTPS");
}

for (const [name, value, suffix] of [
  ["AEM_POLICY_ROOT", policyRoot, "/settings/wcm/policies"],
  ["AEM_TEMPLATE_ROOT", templateRoot, "/settings/wcm/templates"]
]) {
  if (!value.startsWith("/conf/") || !value.endsWith(suffix)) {
    throw new Error(`Invalid ${name}: ${value}`);
  }
}

for (const [name, value] of [
  ["MAX_DEPTH", maxDepth],
  ["MAX_NODES", maxNodes],
  ["REQUEST_TIMEOUT", requestTimeout],
  ["PROGRESS_INTERVAL", progressInterval],
  ["FETCH_DEPTH", fetchDepth],
  ["CONCURRENCY", concurrency]
]) {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
}

const started = Date.now();
const nodes = new Map();
const visited = new Set();
const errors = [];
const policyPaths = new Set();

let requests = 0;
let truncated = false;

function log(level, message) {
  const time = new Date().toLocaleTimeString("en-US", {
    hour12: false
  });

  console.log(`[${time}] [${level}] ${message}`);
}

function printProgress() {
  log(
    "PROGRESS",
    `Nodes: ${nodes.size} | Requests: ${requests} | ` +
    `Policies: ${policyPaths.size} | Errors: ${errors.length}`
  );
}



function isTemplateNode(resourcePath) {
  if (!resourcePath.startsWith(templateRoot + "/")) return false;
  return !resourcePath.slice(templateRoot.length + 1).includes("/");
}

function getChildNames(data, parentPath = "") {
  // Template policy mappings (cq:policy) live only under <template>/policies,
  // and its title and status in <template>/jcr:content (that node only);
  // structure, initial content and thumbnails are not needed.
  if (isTemplateNode(parentPath)) {
    return ["jcr:content", "policies"].filter(name => {
      const child = data[name];
      return child && typeof child === "object" && !Array.isArray(child);
    });
  }

  if (
    parentPath.endsWith("/jcr:content") &&
    isTemplateNode(parentPath.slice(0, -"/jcr:content".length))
  ) {
    return [];
  }

  return Object.entries(data)
    .filter(([key, value]) => {
      if (
        value === null ||
        typeof value !== "object" ||
        Array.isArray(value) ||
        key.startsWith(":")
      ) {
        return false;
      }

      // These embedded objects are not actual children
      // under the template policy jcr:content node.
      if (
        parentPath.startsWith(templateRoot + "/") &&
        parentPath.endsWith("/policies/jcr:content") &&
        (key === "jcr:content" || key === "cq:styleGroups")
      ) {
        return false;
      }

      return true;
    })
    .map(([key]) => key);
}



function getProperties(node) {
  return Object.fromEntries(
    Object.entries(node).filter(([, value]) =>
      value === null ||
      typeof value !== "object" ||
      Array.isArray(value)
    )
  );
}

function getPolicyPath(resourcePath) {
  if (!resourcePath.startsWith(policyRoot + "/")) return null;

  const relative = resourcePath.slice(policyRoot.length + 1);
  const parts = relative.split("/");

  const index = parts.findIndex(part => /^policy_/.test(part));

  if (index === -1) return null;

  return policyRoot + "/" + parts.slice(0, index + 1).join("/");
}

// Encode each path segment so names containing #, ?, %, spaces etc. address
// the right resource. ":" is kept readable (jcr:content); Sling decodes either.
function encodePath(resourcePath) {
  return resourcePath
    .split("/")
    .map(segment => encodeURIComponent(segment).replace(/%3A/gi, ":"))
    .join("/");
}

// Fetches resourcePath as Sling JSON `levels` deep. Returns { data, levels }:
// Sling answers 300 when a deep tree exceeds its result limit, in which case
// this falls back to a single level.
async function requestJson(resourcePath, levels = 1) {
  const url = new URL(
    `${author}${encodePath(resourcePath)}.${levels}.json`
  );

  const start = Date.now();
  requests++;

  log("GET", `${resourcePath} (.${levels}.json)`);

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json"
    },
    signal: AbortSignal.timeout(requestTimeout)
  });

  const elapsed = Date.now() - start;

  if (response.status === 300 && levels > 1) {
    await response.body?.cancel();
    log("INFO", `Tree too large at .${levels}.json; retrying one level`);
    return requestJson(resourcePath, 1);
  }

  if (!response.ok) {
    log("ERROR", `HTTP ${response.status} | ${resourcePath}`);
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Unexpected JSON response");
  }

  log("OK", `HTTP ${response.status} | ${elapsed} ms`);

  return { data, levels };
}

function registerNode(resourcePath, node, section) {
  nodes.set(resourcePath, node);
  section.count++;

  const policyPath = getPolicyPath(resourcePath);

  if (policyPath && !policyPaths.has(policyPath)) {
    policyPaths.add(policyPath);
    log("POLICY", `Found ${policyPath}`);
  }

  if (nodes.size % progressInterval === 0) {
    printProgress();
  }
}

// Fetches one node several levels deep and registers every node in the
// response whose children are fully known. Nodes at the deepest returned
// level may have unlisted children, so they are returned for their own fetch.
async function visit({ path: resourcePath, depth }, section) {
  if (visited.has(resourcePath)) return [];
  visited.add(resourcePath);

  try {
    const { data, levels } =
      await requestJson(resourcePath, fetchDepth);

    const frontier = [];

    const expand = (nodePath, node, nodeDepth, level) => {
      if (nodeDepth > maxDepth || section.count >= maxNodes) {
        truncated = true;
        log("LIMIT", `Traversal limit reached at ${nodePath}`);
        return;
      }

      if (level === levels) {
        frontier.push({ path: nodePath, depth: nodeDepth });
        return;
      }

      if (level > 0) visited.add(nodePath);
      registerNode(nodePath, node, section);

      for (const child of getChildNames(node, nodePath)) {
        expand(`${nodePath}/${child}`, node[child], nodeDepth + 1, level + 1);
      }
    };

    expand(resourcePath, data, depth, 0);

    return frontier;

  } catch (error) {
    errors.push({
      path: resourcePath,
      error: error.message
    });

    log("FAILED", `${resourcePath}: ${error.message}`);

    return [];
  }
}

// Crawls one root with up to CONCURRENCY requests in flight. MAX_NODES
// applies per root, so a large policy tree cannot starve the template scan.
async function crawl(rootPath) {
  const section = { count: 0 };
  const queue = [{ path: rootPath, depth: 0 }];
  const pending = new Set();

  while (queue.length || pending.size) {
    while (queue.length && pending.size < concurrency) {
      const task = visit(queue.shift(), section)
        .then(children => queue.push(...children))
        .finally(() => pending.delete(task));

      pending.add(task);
    }

    if (pending.size) await Promise.race(pending);
  }
}

// Parallel fetches finish in any order; rebuild repository (document) order
// so styles and groups keep the order authors defined in AEM.
function restoreRepositoryOrder(rootPaths) {
  const ordered = new Map();

  const walk = resourcePath => {
    const node = nodes.get(resourcePath);
    if (!node || ordered.has(resourcePath)) return;

    ordered.set(resourcePath, node);

    for (const child of getChildNames(node, resourcePath)) {
      walk(`${resourcePath}/${child}`);
    }
  };

  rootPaths.forEach(walk);

  for (const [resourcePath, node] of nodes) {
    if (!ordered.has(resourcePath)) ordered.set(resourcePath, node);
  }

  nodes.clear();
  for (const [resourcePath, node] of ordered) nodes.set(resourcePath, node);
}

// A failed root request (bad token, wrong URL/path) means nothing useful
// was exported, so fail hard instead of reporting "completed with issues".
function assertRootLoaded(rootPath) {
  if (nodes.has(rootPath)) return;

  const error =
    errors.find(item => item.path === rootPath)?.error || "not retrieved";

  const hint = /HTTP 40[13]\b/.test(error)
    ? " - check AEM_LOCAL_TOKEN (it may have expired)"
    : "";

  throw new Error(`Could not read ${rootPath}: ${error}${hint}`);
}

function collectPolicies() {
  const policies = new Map();

  // Follow repository order (nodes is reordered after the parallel crawl),
  // not the order in which policies happened to be discovered.
  const orderedPolicyPaths = [
    ...[...nodes.keys()].filter(p => policyPaths.has(p)),
    ...[...policyPaths].filter(p => !nodes.has(p))
  ];

  for (const policyPath of orderedPolicyPaths) {
    const relative = policyPath.slice(policyRoot.length + 1);
    const segments = relative.split("/");

    policies.set(policyPath, {
      path: policyPath,
      componentPath: segments.slice(0, -1).join("/"),
      properties: getProperties(nodes.get(policyPath) || {}),
      styleGroups: [],
      ungroupedStyles: []
    });
  }

  for (const [resourcePath, node] of nodes) {
    const policyPath = getPolicyPath(resourcePath);

    if (!policyPath || !policies.has(policyPath)) continue;

    if (node["cq:styleGroupLabel"] !== undefined) {
      policies.get(policyPath).styleGroups.push({
        path: resourcePath,
        label: node["cq:styleGroupLabel"],
        styles: []
      });
    }
  }

  for (const [resourcePath, node] of nodes) {
    const policyPath = getPolicyPath(resourcePath);

    if (!policyPath || !policies.has(policyPath)) continue;

    if (
      node["cq:styleLabel"] === undefined &&
      node["cq:styleClasses"] === undefined
    ) continue;

    const policy = policies.get(policyPath);

    const group = policy.styleGroups
      .filter(item =>
        resourcePath.startsWith(item.path + "/")
      )
      .sort((a, b) => b.path.length - a.path.length)[0];

    const style = {
      path: resourcePath,
      id: node["cq:styleId"] ?? null,
      label: node["cq:styleLabel"] ?? null,
      classes: node["cq:styleClasses"] ?? null,
      properties: getProperties(node)
    };

    if (group) {
      group.styles.push(style);
    } else {
      policy.ungroupedStyles.push(style);
    }
  }

  return [...policies.values()];
}



function collectTemplatesAndReferences(policies) {
  const templates = [];
  const references = [];
  const policySet = new Set(policies.map(p => p.path));

  for (const [resourcePath, node] of nodes) {
    if (!resourcePath.startsWith(templateRoot + "/")) continue;

    const relative = resourcePath.slice(templateRoot.length + 1);

    // Include only valid AEM editable templates.
    if (
      relative &&
      !relative.includes("/") &&
      node["jcr:primaryType"] === "cq:Template"
    ) {
      const content = nodes.get(resourcePath + "/jcr:content") || {};

      templates.push({
        path: resourcePath,
        name: relative,
        title: content["jcr:title"] ?? null,
        // "enabled", "disabled" or "draft" in the template console.
        status: content.status ?? null,
        lastModified:
          content["cq:lastModified"] ?? content["jcr:lastModified"] ?? null,
        lastModifiedBy:
          content["cq:lastModifiedBy"] ?? content["jcr:lastModifiedBy"] ?? null,
        properties: getProperties(node)
      });
    }

    if (node["cq:policy"] === undefined) continue;

    const values = Array.isArray(node["cq:policy"])
      ? node["cq:policy"]
      : [node["cq:policy"]];

    for (const value of values) {
      if (typeof value !== "string") continue;

      const resolved = value.startsWith("/")
        ? value
        : `${policyRoot}/${value.replace(/^\/+/, "")}`;

      const found = policySet.has(resolved);

      references.push({
        templatePath: resourcePath,
        rawReference: value,
        resolvedPolicyPath: resolved,
        found,
        status: found ? "Resolved" : "Unverified"
      });
    }
  }

  return { templates, references };
}

// Verify unique unresolved policy references directly in AEM.
// Uses the existing requestJson() and local JWT authentication.
async function verifyPolicyReferences(references) {
  const unresolvedPaths = [
    ...new Set(
      references
        .filter(ref => !ref.found)
        .map(ref => ref.resolvedPolicyPath)
    )
  ];

  console.log(
    `[AEM] Verifying ${unresolvedPaths.length} unique unresolved policies`
  );

  const results = new Map();

  for (const policyPath of unresolvedPaths) {
    try {
      await requestJson(policyPath, 0);

      results.set(policyPath, {
        status: "Exists in AEM - Not Exported"
      });

      console.log(`[AEM] EXISTS: ${policyPath}`);

    } catch (error) {
      const message = error.message || String(error);

      const status = /HTTP 404\b/.test(message)
        ? "Not Found in AEM"
        : "Verification Failed";

      results.set(policyPath, {
        status,
        verificationError: message
      });

      console.warn(
        `[AEM] ${status}: ${policyPath} (${message})`
      );
    }
  }

  for (const ref of references) {
    if (ref.found) continue;

    const result = results.get(ref.resolvedPolicyPath);

    if (result) {
      ref.status = result.status;

      if (result.verificationError) {
        ref.verificationError = result.verificationError;
      }
    }
  }

  return references;
}



function save(filename, data) {
  const outputPath = path.join(dataDir, filename);

  fs.writeFileSync(
    outputPath,
    JSON.stringify(data, null, 2)
  );

  log("SAVE", filename);
}

async function main() {

  console.log("=".repeat(60));
  console.log(" AEM STYLE SYSTEM EXPORTER - EWP");
  console.log("=".repeat(60));
  console.log("Author:       ", author);
  console.log("Policy root:  ", policyRoot);
  console.log("Template root:", templateRoot);
  console.log("Token:         Configured (value hidden)");
  console.log("Max depth:    ", maxDepth);
  console.log("Max nodes:    ", maxNodes, "(per root)");
  console.log("Fetch depth:  ", fetchDepth);
  console.log("Concurrency:  ", concurrency);
  console.log("=".repeat(60));

  log("START", "Export started");

  log("SCAN", "Scanning policies...");
  await crawl(policyRoot);
  assertRootLoaded(policyRoot);

  printProgress();

  log("SCAN", "Scanning templates...");
  await crawl(templateRoot);
  assertRootLoaded(templateRoot);

  printProgress();

  restoreRepositoryOrder([policyRoot, templateRoot]);

  log("PROCESS", "Extracting policies and styles...");
  const policies = collectPolicies();

  log("PROCESS", "Resolving template references...");
  const { templates, references } =
    collectTemplatesAndReferences(policies);
	
  await verifyPolicyReferences(references);

  const used = new Set(
    references.map(ref => ref.resolvedPolicyPath)
  );

  const referencedStyles = policies.filter(
    policy => used.has(policy.path)
  );

  const unreferencedPolicies = policies.filter(
    policy => !used.has(policy.path)
  );

  // Any template reference that did not resolve to an exported policy means
  // the export is incomplete (policy outside the scanned root) or the
  // template configuration is broken (policy missing in AEM).
  const missingReferences = references.filter(ref => !ref.found);

  const validation = {
    complete:
      errors.length === 0 &&
      !truncated &&
      missingReferences.length === 0,
    errors,
    truncated,
    missingReferences,
    counts: {
      nodes: nodes.size,
      requests,
      policies: policies.length,
      templates: templates.length,
      references: references.length,
      missingReferences: missingReferences.length,
      referencedPolicies: referencedStyles.length,
      unreferencedPolicies: unreferencedPolicies.length
    }
  };

  save("policies.json", policies);
  save("templates.json", templates);
  save("policy-usage.json", references);
  save("referenced-styles.json", referencedStyles);
  save("unreferenced-policies.json", unreferencedPolicies);
  save("validation-report.json", validation);

  const duration = Math.round((Date.now() - started) / 1000);

  console.log("");
  console.log("=".repeat(60));
  console.log(" EXPORT SUMMARY");
  console.log("=".repeat(60));
  console.log("Nodes retrieved:     ", nodes.size);
  console.log("Requests made:       ", requests);
  console.log("Policies discovered: ", policies.length);
  console.log("Templates discovered:", templates.length);
  console.log("Policy references:   ", references.length);
  console.log("Missing references:  ", missingReferences.length);
  console.log("Errors:              ", errors.length);
  console.log("Truncated:           ", truncated);
  console.log("Duration:            ", duration, "seconds");
  console.log("Output directory:    ", dataDir);
  console.log("=".repeat(60));

  if (!validation.complete || policies.length === 0) {
    log(
      "WARNING",
      "Export may be incomplete. Review validation-report.json"
    );
    process.exitCode = 2;
  } else {
    log("SUCCESS", "Export finished without reported request errors");
  }
}

main().catch(error => {
  log("FATAL", error.message);
  process.exitCode = 1;
});
