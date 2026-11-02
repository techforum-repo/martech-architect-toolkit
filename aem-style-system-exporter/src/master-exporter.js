
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

const root = path.resolve(__dirname, '..');
process.loadEnvFile(path.join(root, '.env'));

const out = path.join(root, 'output');
fs.mkdirSync(out, {recursive: true});

const warnings = [];

function run(name) {
  console.log(`\n[MASTER] Running ${name}`);

  const p = spawnSync(
    process.execPath,
    [path.join(root, 'src', name)],
    {
      cwd: root,
      stdio: 'inherit',
      env: process.env
    }
  );

  return p.error ? 1 : (p.status ?? 1);
}

function remove(name) {
  try {
    fs.unlinkSync(path.join(out, name));
  } catch(e) {
    if(e.code !== 'ENOENT') throw e;
  }
}

function main() {
  // Avoid accidentally reusing data from a previous run.
  for (const f of [
    'policies.json',
    'templates.json',
    'policy-usage.json',
    'referenced-styles.json',
    'unreferenced-policies.json',
    'validation-report.json',
    'fe-data.json',
    'style-css-mapping.json',
    'EWP_Style_System_Export.xlsx'
  ]) {
    remove(f);
  }

  const aem = run('exporter.js');

  if (![0, 2].includes(aem)) {
    throw Error(`AEM extraction failed (exit ${aem})`);
  }

  for (const name of [
    'policies.json',
    'policy-usage.json',
    'validation-report.json'
  ]) {
    if (!fs.existsSync(path.join(out, name))) {
      throw Error(`Missing AEM output ${name}`);
    }
  }

  if (aem === 2) {
    warnings.push('AEM exporter reported incomplete results');
  }

  const fe = process.env.FE_PROJECT_PATH?.trim();

  if (!fe) {
    console.log('[MASTER] FE path not set; AEM-only workbook');
  } else if (!fs.existsSync(fe) || !fs.statSync(fe).isDirectory()) {
    warnings.push(`Invalid FE path: ${fe}`);
  } else {
    if (process.env.FE_BUILD === 'true') {
      const cmd = process.env.FE_BUILD_COMMAND || 'npm run build';

      const p = spawnSync(cmd, {
        cwd: fe,
        stdio: 'inherit',
        shell: true
      });

      if (p.status !== 0) {
        warnings.push(
          `FE build failed (${p.status}); compiled CSS may be stale`
        );
      }
    }

    const status = run('css-extractor.js');

    if (status === 0) {
      const mapping = run('style-mapper.js');

      if (mapping !== 0) {
        warnings.push('FE mapping failed');
        remove('style-css-mapping.json');
      }
    } else {
      warnings.push(`FE extraction unavailable (exit ${status})`);
      remove('fe-data.json');
    }
  }

  fs.writeFileSync(
    path.join(out, 'master-status.json'),
    JSON.stringify({
      warnings,
      aemStatus: aem,
      createdAt: new Date().toISOString()
    }, null, 2)
  );

  if (run('excel-exporter.js') !== 0) {
    throw Error('Excel export failed');
  }

  for (const w of warnings) {
    console.warn('[WARNING]', w);
  }

  console.log(
    '\n[MASTER] Workbook: ' +
    path.join(out, 'EWP_Style_System_Export.xlsx')
  );

  if (warnings.length) {
    process.exitCode = 2;
  }
}

try {
  main();
} catch(e) {
  console.error('[MASTER ERROR]', e.message);
  process.exitCode = 1;
}
