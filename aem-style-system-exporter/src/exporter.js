
const fs = require("node:fs");
const path = require("node:path");
const { URL } = require("node:url");

const root = path.resolve(__dirname, "..");
process.loadEnvFile(path.join(root, ".env"));

const author = process.env.AEM_AUTHOR_URL?.replace(/\/$/, "");
const token = process.env.AEM_LOCAL_TOKEN?.trim();
const policyRoot = process.env.AEM_POLICY_ROOT;
const templateRoot = process.env.AEM_TEMPLATE_ROOT;

const maxDepth = Number(process.env.MAX_DEPTH || 30);
const maxNodes = Number(process.env.MAX_NODES || 15000);
const requestTimeout = Number(process.env.REQUEST_TIMEOUT || 30000);
const progressInterval = Number(process.env.PROGRESS_INTERVAL || 25);

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
  ["PROGRESS_INTERVAL", progressInterval]
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
let currentSection = "";

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

function getChildNames(data) {
  return Object.entries(data)
    .filter(([key, value]) =>
      value !== null &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      !key.startsWith(":")
    )
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

async function requestJson(resourcePath) {
  const url = new URL(
    `${author}${resourcePath}.1.json`
  );

  const start = Date.now();
  requests++;

  log("GET", resourcePath);

  const response = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/json"
    },
    signal: AbortSignal.timeout(requestTimeout)
  });

  const elapsed = Date.now() - start;

  if (!response.ok) {
    log("ERROR", `HTTP ${response.status} | ${resourcePath}`);
    throw new Error(`HTTP ${response.status}`);
  }

  const data = await response.json();

  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Unexpected JSON response");
  }

  log("OK", `HTTP ${response.status} | ${elapsed} ms`);

  return data;
}

async function crawl(resourcePath, depth = 0) {
  if (visited.has(resourcePath)) return;

  if (nodes.size >= maxNodes || depth > maxDepth) {
    truncated = true;
    log("LIMIT", `Traversal limit reached at ${resourcePath}`);
    return;
  }

  visited.add(resourcePath);

  try {
    const data = await requestJson(resourcePath);

    nodes.set(resourcePath, data);

    const policyPath = getPolicyPath(resourcePath);

    if (policyPath && !policyPaths.has(policyPath)) {
      policyPaths.add(policyPath);
      log("POLICY", `Found ${policyPath}`);
    }

    if (nodes.size % progressInterval === 0) {
      printProgress();
    }

    const children = getChildNames(data);

    for (const child of children) {
      await crawl(
        `${resourcePath}/${child}`,
        depth + 1
      );
    }

  } catch (error) {
    errors.push({
      path: resourcePath,
      error: error.message
    });

    log("FAILED", `${resourcePath}: ${error.message}`);
  }
}

function collectPolicies() {
  const policies = new Map();

  for (const policyPath of policyPaths) {
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

    if (relative && !relative.includes("/")) {
      templates.push({
        path: resourcePath,
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

      references.push({
        templatePath: resourcePath,
        rawReference: value,
        resolvedPolicyPath: resolved,
        found: policySet.has(resolved)
      });
    }
  }

  return { templates, references };
}

function save(filename, data) {
  const outputPath = path.join(root, "output", filename);

  fs.writeFileSync(
    outputPath,
    JSON.stringify(data, null, 2)
  );

  log("SAVE", filename);
}

async function main() {
  fs.mkdirSync(path.join(root, "output"), {
    recursive: true
  });

  console.log("=".repeat(60));
  console.log(" AEM STYLE SYSTEM EXPORTER - EWP");
  console.log("=".repeat(60));
  console.log("Author:       ", author);
  console.log("Policy root:  ", policyRoot);
  console.log("Template root:", templateRoot);
  console.log("Token:         Configured (value hidden)");
  console.log("Max depth:    ", maxDepth);
  console.log("Max nodes:    ", maxNodes);
  console.log("=".repeat(60));

  log("START", "Export started");

  currentSection = "policies";
  log("SCAN", "Scanning policies...");
  await crawl(policyRoot);

  printProgress();

  currentSection = "templates";
  log("SCAN", "Scanning templates...");
  await crawl(templateRoot);

  printProgress();

  log("PROCESS", "Extracting policies and styles...");
  const policies = collectPolicies();

  log("PROCESS", "Resolving template references...");
  const { templates, references } =
    collectTemplatesAndReferences(policies);

  const used = new Set(
    references.map(ref => ref.resolvedPolicyPath)
  );

  const referencedStyles = policies.filter(
    policy => used.has(policy.path)
  );

  const unreferencedPolicies = policies.filter(
    policy => !used.has(policy.path)
  );

  const validation = {
    complete: errors.length === 0 && !truncated,
    errors,
    truncated,
    missingReferences: references.filter(ref => !ref.found),
    counts: {
      nodes: nodes.size,
      requests,
      policies: policies.length,
      templates: templates.length,
      references: references.length,
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
  console.log("Errors:              ", errors.length);
  console.log("Duration:            ", duration, "seconds");
  console.log("Output directory:    ", path.join(root, "output"));
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
