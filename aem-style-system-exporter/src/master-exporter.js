// One export run: export.bat [environment] / sh export.sh [environment].
//
// Uses the settings file .env.<environment> (.env without one), and writes
// everything into a run folder of its own under the environment
// (store.js): the workbook, the run's data, and run.json saying how it went.
// Nothing from an earlier run, or another environment, is overwritten.

const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const settings = require('./settings');
const store = require('./store');

const warnings = [];

function step(name, env) {
  console.log(`\n[MASTER] Running ${name}`);
  const p = spawnSync(process.execPath, [path.join(settings.root, 'src', name)], {
    cwd: settings.root,
    stdio: 'inherit',
    env
  });
  return p.error ? 1 : (p.status ?? 1);
}

function settingsFor(environmentArg) {
  const file = settings.settingsFile(environmentArg);
  if (!fs.existsSync(file)) {
    const available = fs.readdirSync(settings.root)
      .filter(name => /^\.env\.[A-Za-z0-9_-]+$/.test(name) && name !== '.env.example')
      .map(name => name.slice(5));
    throw Error(`No settings file ${path.basename(file)}` +
                (available.length ? ` (available: ${available.join(', ')})` : ' (copy .env.example)'));
  }
  return settings.load(file);
}

function exportRun(run, env, data) {
  const aem = step('exporter.js', env);
  if (![0, 2].includes(aem)) throw Error(`AEM extraction failed (exit ${aem})`);
  for (const name of ['policies.json', 'policy-usage.json', 'validation-report.json']) {
    if (!fs.existsSync(path.join(data, name))) throw Error(`Missing AEM output ${name}`);
  }
  if (aem === 2) warnings.push('AEM exporter reported incomplete results');

  const fe = process.env.FE_PROJECT_PATH?.trim();
  if (!fe) {
    console.log('[MASTER] FE path not set; AEM-only workbook');
  } else if (!fs.existsSync(fe) || !fs.statSync(fe).isDirectory()) {
    warnings.push(`Invalid FE path: ${fe}`);
  } else {
    if (process.env.FE_BUILD === 'true') {
      const p = spawnSync(process.env.FE_BUILD_COMMAND || 'npm run build', {cwd: fe, stdio: 'inherit', shell: true});
      if (p.status !== 0) warnings.push(`FE build failed (${p.status}); compiled CSS may be stale`);
    }
    const status = step('css-extractor.js', env);
    if (status === 0) {
      if (step('style-mapper.js', env) !== 0) {
        warnings.push('FE mapping failed');
        fs.rmSync(path.join(data, 'style-css-mapping.json'), {force: true});
      }
    } else {
      warnings.push(`FE extraction unavailable (exit ${status})`);
      fs.rmSync(path.join(data, 'fe-data.json'), {force: true});
    }
  }

  store.writeJson(path.join(data, 'master-status.json'),
                  {warnings, aemStatus: aem, createdAt: run.meta.createdAt});

  // Saves what comparisons need and lists what changed since the last run.
  if (step('history.js', env) !== 0) {
    warnings.push('Change history unavailable; the workbook has no Changes sheet');
    fs.rmSync(path.join(data, 'changes.json'), {force: true});
  }

  if (step('excel-exporter.js', env) !== 0) throw Error('Excel export failed');
  return aem;
}

// Why a run is incomplete, in words, from its validation report: nodes AEM
// didn't return, the crawl limit, no policies at all.
function incompleteReasons(validation, policyRoot) {
  const reasons = [];
  const byError = new Map();
  for (const error of validation.errors || []) {
    byError.set(error.error, [...(byError.get(error.error) || []), error.path]);
  }
  for (const [message, paths] of byError) {
    reasons.push(`${paths.length} node(s) couldn't be read (${message}), e.g. ${paths[0]}`);
  }
  if (validation.truncated) {
    reasons.push('The crawl stopped at a limit (MAX_NODES or MAX_DEPTH): raise it in the settings');
  }
  if (validation.counts && validation.counts.policies === 0) {
    reasons.push(`No policies found under ${policyRoot}: check AEM_POLICY_ROOT`);
  }
  return reasons;
}

// Findings about AEM itself, not the export: templates that point to a
// policy found nowhere (the site's configuration, its parents, /conf/global,
// /apps/conf, /libs/conf). The run is still complete.
function findings(validation, policyRoot) {
  const found = [];
  const missing = validation.missingReferences || [];
  if (missing.length) {
    const policies = [...new Set(missing.map(ref => ref.resolvedPolicyPath))];
    const notFound = missing.filter(ref => ref.status === 'Not Found in AEM').length;
    const one = policies.length === 1;
    found.push(`${policies.length} polic${one ? 'y' : 'ies'} that templates use (${missing.length} reference(s)) ` +
                 (notFound === missing.length ? (one ? "isn't in AEM" : "aren't in AEM")
                   : `couldn't be checked or ${one ? "isn't" : "aren't"} in AEM`) +
                 `, e.g. ${String(policies[0]).replace(policyRoot + '/', '')}`);
  }
  return found;
}

function main() {
  const environmentArg = (process.argv[2] || '').trim();
  const file = settingsFor(environmentArg);
  const author = process.env.AEM_AUTHOR_URL?.trim();
  if (!author) throw Error(`AEM_AUTHOR_URL is not set in ${path.basename(file)}`);

  const keep = Number(process.env.HISTORY_KEEP || 20);
  if (!Number.isInteger(keep) || keep < 2) throw Error('HISTORY_KEEP must be a whole number of at least 2');

  const root = settings.historyRoot();
  const moved = store.migrateLegacy(root, path.join(settings.root, 'output', 'history'));
  if (moved) console.log(`[MASTER] Moved ${moved} earlier export(s) into ${store.environmentsDir(root)}`);

  const environment = store.registerEnvironment(root, {
    author,
    name: process.env.AEM_ENV_NAME?.trim() || null,
    fallbackName: environmentArg || null
  });
  if (environmentArg && environment.name && environment.name !== environmentArg.toLowerCase()) {
    console.log(`[MASTER] ${path.basename(file)} points at ${store.label(environment)}: its runs are kept there.`);
  }
  if (environment.renamedFrom) {
    console.warn(`[WARNING] ${environment.id} was named "${environment.renamedFrom}"; it is now "${environment.name}" ` +
                 '(same author URL, so the same environment and history).');
  }
  const run = store.createRun(environment, {
    settingsFile: path.basename(file),
    policyRoot: process.env.AEM_POLICY_ROOT || '',
    templateRoot: process.env.AEM_TEMPLATE_ROOT || ''
  });
  const workbook = `Style-System_${environment.name || environment.id}_${run.id}.xlsx`;
  const data = path.join(run.dir, 'data');
  fs.mkdirSync(data, {recursive: true});
  const env = {...process.env, EXPORT_SETTINGS_FILE: file, EXPORT_RUN_DIR: run.dir, EXPORT_WORKBOOK_NAME: workbook};

  console.log(`[MASTER] Environment: ${store.label(environment)}  ${author}`);
  console.log(`[MASTER] Run:         ${run.id}  (${path.relative(process.cwd(), run.dir) || run.dir})`);
  console.log(`[MASTER] Run key:     ${environment.id}/${run.id}`);  // read by the app (jobs.js)

  let aem;
  try {
    aem = exportRun(run, env, data);
  } catch (error) {
    store.updateRun(run.dir, {status: 'failed', finishedAt: new Date().toISOString(), error: error.message, warnings});
    throw error;
  }

  const validation = store.readJson(path.join(data, 'validation-report.json'), {});
  const incomplete = validation.complete === false || aem === 2;
  const reasons = incomplete ? incompleteReasons(validation, process.env.AEM_POLICY_ROOT || '') : [];
  const notes = findings(validation, process.env.AEM_POLICY_ROOT || '');
  const meta = store.updateRun(run.dir, {
    status: incomplete ? 'incomplete' : 'complete',
    finishedAt: new Date().toISOString(),
    aemStatus: aem,
    reasons,
    findings: notes,
    // "AEM exporter reported incomplete results" just repeats the status; the reasons say why.
    warnings: warnings.filter(w => w !== 'AEM exporter reported incomplete results'),
    workbook
  });

  // The front-end data is large and the workbook has it; comparisons use
  // the tokens and CSS fingerprints saved by history.js.
  if (process.env.KEEP_RAW_DATA !== 'true') {
    for (const name of ['fe-data.json', 'style-css-mapping.json']) fs.rmSync(path.join(data, name), {force: true});
  }
  const pruned = store.pruneRuns(environment.dir, keep, run.dir);

  for (const w of meta.warnings) console.warn('[WARNING]', w);
  for (const reason of reasons) console.warn('[INCOMPLETE]', reason);
  for (const note of notes) console.log('[FINDING]', note, '(see the [CHECK] lines above)');
  console.log(`\n[MASTER] Status:   ${meta.status}` +
              (meta.changes?.comparedWith ? `; ${meta.changes.total} change(s) since run ${meta.changes.comparedWith}`
                : meta.changes ? '; first run of this environment' : ''));
  console.log(`[MASTER] Workbook: ${path.join(run.dir, workbook)}`);
  if (pruned) console.log(`[MASTER] Removed ${pruned} old run(s) of ${store.label(environment)} (HISTORY_KEEP=${keep})`);

  if (warnings.length) process.exitCode = 2;
}

try {
  main();
} catch (e) {
  console.error('[MASTER ERROR]', e.message);
  process.exitCode = 1;
}
