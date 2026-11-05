// Environment settings files (profiles): .env.<name> for each environment,
// .env as "default". The app lists, edits and tests them; export.bat <name>
// and the app's Run use them.
//
// Files are read as data here, never loaded into this process: a run gets
// exactly its own file's values (see jobs.js). The token is write-only: it is
// never returned, only whether it is set and, if it says, when it expires.

const fs = require("node:fs");
const path = require("node:path");
const util = require("node:util");

const { root } = require("./settings");

const DEFAULT_KEY = "default";
const KEY_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/;

const positiveInt = value => /^\d+$/.test(value) && Number(value) > 0 ? null : "a whole number above 0";
const FIELDS = [
  { key: "AEM_AUTHOR_URL", group: "AEM", label: "Author URL", required: true,
    check: value => /^https:\/\/[^\s/?#]+\/?$/.test(value) ? null : "an HTTPS address like https://author-p1-e2.adobeaemcloud.com" },
  { key: "AEM_LOCAL_TOKEN", group: "AEM", label: "Local Development Token", secret: true },
  { key: "AEM_POLICY_ROOT", group: "AEM", label: "Policy root", required: true,
    check: value => /^\/conf\/[^\s]+\/settings\/wcm\/policies$/.test(value) ? null : "/conf/<site>/settings/wcm/policies" },
  { key: "AEM_TEMPLATE_ROOT", group: "AEM", label: "Template root", required: true,
    check: value => /^\/conf\/[^\s]+\/settings\/wcm\/templates$/.test(value) ? null : "/conf/<site>/settings/wcm/templates" },
  { key: "FE_PROJECT_PATH", group: "Front end", label: "Front-end project folder" },
  { key: "FE_THEMES", group: "Front end", label: "Themes", placeholder: "corporate",
    // Theme names become file paths (dist/clientlib-<theme>/<theme>.css): names only.
    check: value => /^\s*[A-Za-z0-9_-]+(\s*,\s*[A-Za-z0-9_-]+)*\s*$/.test(value) ? null : "names separated by commas, e.g. corporate,retail" },
  { key: "FE_BUILD", group: "Front end", label: "Build the front end first", boolean: true },
  { key: "FE_BUILD_COMMAND", group: "Front end", label: "Build command", placeholder: "npm run build" },
  { key: "FE_SHARED_CSS", group: "Front end", label: "Shared CSS files" },
  { key: "MAX_NODES", group: "Limits", label: "Nodes per root", placeholder: "15000", check: positiveInt },
  { key: "MAX_DEPTH", group: "Limits", label: "Depth", placeholder: "30", check: positiveInt },
  { key: "FETCH_DEPTH", group: "Limits", label: "Levels per request", placeholder: "3", check: positiveInt },
  { key: "CONCURRENCY", group: "Limits", label: "Parallel requests", placeholder: "4", check: positiveInt },
  { key: "REQUEST_TIMEOUT", group: "Limits", label: "Request timeout (ms)", placeholder: "30000", check: positiveInt }
];

function fileFor(key, dir = root) {
  return path.join(dir, key === DEFAULT_KEY ? ".env" : `.env.${key}`);
}

// KEY=value pairs of a settings file, as Node reads them (values already in
// this process's environment play no part).
function readFile(file) {
  if (!fs.existsSync(file)) return null;
  const text = fs.readFileSync(file, "utf8");
  if (typeof util.parseEnv === "function") return util.parseEnv(text);
  const values = {};  // Node < 21.7: the same simple rules
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/);
    if (!match) continue;
    let value = match[2];
    if (/^(['"`]).*\1$/.test(value)) value = value.slice(1, -1);
    else value = value.replace(/\s+#.*$/, "");
    values[match[1]] = value;
  }
  return values;
}

// Expiry from a JWT's payload (exp, or IMS created_at + expires_in), if it has one.
function tokenExpiry(token) {
  try {
    const payload = JSON.parse(Buffer.from(String(token).split(".")[1], "base64url").toString("utf8"));
    if (Number.isFinite(payload.exp)) return new Date(payload.exp * 1000).toISOString();
    if (payload.created_at && payload.expires_in) {
      return new Date(Number(payload.created_at) + Number(payload.expires_in)).toISOString();
    }
  } catch {
    // not a JWT: expiry unknown
  }
  return null;
}

function summary(key, values) {
  const shown = {};
  for (const field of FIELDS) if (!field.secret) shown[field.key] = values[field.key] ?? "";
  const token = values.AEM_LOCAL_TOKEN || "";
  return {
    key,
    file: path.basename(fileFor(key)),
    values: shown,
    token: { set: Boolean(token), expires: token ? tokenExpiry(token) : null },
    historyDir: values.HISTORY_DIR || ""
  };
}

function list(dir = root) {
  const keys = fs.readdirSync(dir)
    .filter(name => /^\.env\.[a-z0-9][a-z0-9_-]{0,39}$/.test(name) && name !== ".env.example")
    .map(name => name.slice(5));
  const profiles = keys.sort().map(key => summary(key, readFile(fileFor(key, dir)) || {}));
  const fallback = readFile(fileFor(DEFAULT_KEY, dir));
  if (fallback?.AEM_AUTHOR_URL) profiles.unshift(summary(DEFAULT_KEY, fallback));
  return profiles;
}

// Saved values merged with the form's; an empty token keeps the saved one.
// Only a valid name reads a saved file: never a path built from a request.
function merged(key, form, dir = root) {
  const saved = (validKey(key) && readFile(fileFor(key, dir))) || {};
  const values = { ...saved };
  for (const field of FIELDS) {
    if (!(field.key in form)) continue;
    const value = String(form[field.key] ?? "").trim();
    if (field.secret && !value) continue;
    values[field.key] = field.boolean ? (value === "true" ? "true" : "false") : value;
  }
  return values;
}

function validKey(key) {
  return KEY_PATTERN.test(key) && key !== "example";
}

function validate(key, values, { isNew = false, dir = root } = {}) {
  const errors = {};
  if (!validKey(key)) {
    errors.key = "Use lowercase letters, digits, - or _ (up to 40), e.g. prod";
  } else if (isNew && fs.existsSync(fileFor(key, dir))) {
    errors.key = `${path.basename(fileFor(key, dir))} already exists`;
  }
  for (const field of FIELDS) {
    const value = values[field.key] ?? "";
    if (field.required && !value) errors[field.key] = "Required";
    else if (value && field.check) {
      const problem = field.check(value);
      if (problem) errors[field.key] = "Expected " + problem;
    }
    if (/[\r\n]/.test(value) || quote(value) === null) {
      errors[field.key] = "Can't contain line breaks, or a ' together with a \\, \" or ` and spaces or #";
    }
  }
  if (!values.AEM_LOCAL_TOKEN) errors.AEM_LOCAL_TOKEN = "Required";
  return errors;
}

// How a value is written so Node reads exactly it back (Node's .env rules:
// single quotes are literal, but end at the next '; double quotes turn \n
// into a line break; unquoted values end at a space before #). null: no
// way to write it.
function quote(value) {
  if (!/[\s#"'`\\]/.test(value)) return value;
  if (!value.includes("'")) return `'${value}'`;
  if (!/[\s#"`\\]/.test(value) && !/^['"`]/.test(value)) return value;  // e.g. O'Brien
  if (!/[\\"`]/.test(value)) return `"${value}"`;
  return null;
}

// Writes the file: known keys updated where they are, comments and other
// lines kept, new keys added at the end. Owner-only where the OS supports it.
function write(key, values, dir = root) {
  const file = fileFor(key, dir);
  const lines = fs.existsSync(file) ? fs.readFileSync(file, "utf8").split(/\r?\n/) : [
    `# Settings for the "${key}" environment, written by the AEM Style System Exporter app.`
  ];
  const pending = new Map(FIELDS.filter(f => values[f.key] !== undefined).map(f => [f.key, values[f.key]]));
  // An empty value means "use the default": its line is removed, not written.
  const out = lines.flatMap(line => {
    const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=/);
    if (!match || !pending.has(match[1])) return [line];
    const value = pending.get(match[1]);
    pending.delete(match[1]);
    return value === "" ? [] : [`${match[1]}=${quote(value)}`];
  });
  while (out.length && out[out.length - 1] === "") out.pop();
  for (const [name, value] of pending) if (value !== "") out.push(`${name}=${quote(value)}`);
  const temporary = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, out.join("\n") + "\n", { mode: 0o600 });
  fs.renameSync(temporary, file);
  return file;
}

// One read of the policy root with the token: says whether the URL, token
// and root work, without following redirects (the token stays with author).
async function testConnection(values, { timeout = 15000 } = {}) {
  const url = values.AEM_AUTHOR_URL.replace(/\/$/, "") + values.AEM_POLICY_ROOT + ".0.json";  // as the exporter reads it
  try {
    const response = await fetch(url, {
      headers: { Authorization: `Bearer ${values.AEM_LOCAL_TOKEN}`, Accept: "application/json" },
      redirect: "manual",
      signal: AbortSignal.timeout(timeout)
    });
    const reasons = {
      200: "Connected: the token can read the policy root.",
      401: "AEM rejected the token: it may have expired. Get a new Local Development Token.",
      403: "The token's user can't read the policy root.",
      404: "The policy root wasn't found: check the path."
    };
    const redirect = response.status >= 300 && response.status < 400;
    return {
      ok: response.status === 200,
      status: response.status,
      message: reasons[response.status] ||
               (redirect ? "AEM redirected to a sign-in page: the token isn't accepted." : `AEM answered HTTP ${response.status}.`)
    };
  } catch (error) {
    return { ok: false, status: 0, message: `Couldn't reach ${new URL(url).host}: ${error.cause?.code || error.message}` };
  }
}

module.exports = { DEFAULT_KEY, FIELDS, fileFor, list, merged, quote, readFile, testConnection, tokenExpiry, validKey, validate, write };
