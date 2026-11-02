
const fs = require('node:fs');
const path = require('node:path');
const ExcelJS = require('exceljs');

const root = path.resolve(__dirname, '..');
const dir = path.join(root, 'output');

const read = (name, fallback) => {
  const p = path.join(dir, name);
  return fs.existsSync(p)
    ? JSON.parse(fs.readFileSync(p, 'utf8'))
    : fallback;
};

const policies = read('policies.json', []);
const refs = read('policy-usage.json', []);
const validation = read('validation-report.json', {});
const fe = read('fe-data.json', null);
const mapping = read('style-css-mapping.json', null);
const master = read('master-status.json', {warnings: []});

const lookup = new Map(
  (mapping?.rows || []).map(r => [
    `${r.stylePath}\u0000${r.theme}`, r
  ])
);

const usage = new Map();

for (const r of refs) {
  const p = r.resolvedPolicyPath;
  const t = r.templatePath
    ?.split('/templates/')[1]
    ?.split('/')[0];

  if (!p || !t) continue;

  if (!usage.has(p)) usage.set(p, new Set());
  usage.get(p).add(t);
}

function safe(v) {
  const s = v == null ? '' : String(v);
  return /^[\s]*[=+\-@]/.test(s) ? "'" + s : s;
}

function sheet(book, name, headers, rows) {
  const ws = book.addWorksheet(name, {
    views: [{state:'frozen',ySplit:1}]
  });

  ws.columns = headers.map(h => ({
    header: h,
    key: h,
    width: /Actual FE CSS/.test(h) ? 80
      : /Templates/.test(h) ? 48
      : /Context|Source|CSS Class/.test(h) ? 42
      : 25
  }));

  for (const row of rows) {
    ws.addRow(row.map(safe));
  }

  ws.getRow(1).height = 28;

  ws.getRow(1).eachCell(c => {
    c.font = {
      bold: true,
      color: {argb:'FFFFFFFF'}
    };
    c.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: {argb:'FF183A5B'}
    };
    c.alignment = {
      wrapText: true,
      vertical: 'middle'
    };
  });

  ws.autoFilter = {
    from: {row:1,column:1},
    to: {row:1,column:headers.length}
  };

  for(let i=2;i<=ws.rowCount;i++) {
    const row = ws.getRow(i);
    row.height = 32;

    row.eachCell(c => {
      c.alignment = {
        wrapText: true,
        vertical: 'top'
      };
      c.font = {
        name: 'Aptos',
        size: 10,
        color: {argb:'FF16603D'}
      };
      if(i%2===0) {
        c.fill = {
          type: 'pattern',
          pattern: 'solid',
          fgColor: {argb:'FFF0F5FA'}
        };
      }
    });
  }

  console.log(`[EXCEL] ${name}: ${rows.length} rows`);
}

function cssText(rules) {
  return rules.map(r => {
    const declarations = r.declarations.map(d =>
      `  ${d.property}: ${d.value}` +
      `${d.important ? ' !important' : ''};`
    ).join('\n');

    let result =
      `${r.selector} {\n${declarations}\n}`;

    for(const context of [...r.contexts].reverse()) {
      result = `${context} {\n${result}\n}`;
    }

    return result;
  }).join('\n\n');
}

async function main() {
  if (!Array.isArray(policies) || !Array.isArray(refs)) {
    throw Error('Invalid AEM exports');
  }

  const book = new ExcelJS.Workbook();
  book.creator = 'EWP AEM Style Exporter';

  const styleRows = [];
  const policyRows = [];

  for (const p of policies) {
    const props = p.properties || {};
    const component = p.componentPath || '';
    const name =
      props['jcr:title'] || p.path.split('/').pop();

    const templates = [
      ...(usage.get(p.path) || [])
    ].sort().join(', ');

    const styles = [
      ...(p.styleGroups || []).flatMap(g =>
        (g.styles || []).map(s => ({
          style: s,
          group: g.label || ''
        }))
      ),
      ...(p.ungroupedStyles || []).map(s => ({
        style: s,
        group: 'Ungrouped'
      }))
    ];

    policyRows.push([
      component,
      name,
      styles.length,
      templates,
      templates
        ? 'Referenced in scanned templates'
        : 'No reference found'
    ]);

    for(const {style,group} of styles) {
      const themes = fe?.themes?.length
        ? fe.themes
        : [''];

      for(const theme of themes) {
        const match = lookup.get(
          `${style.path}\u0000${theme}`
        );

        const css = match
          ? cssText(match.cssRules)
          : '';

        // Excel cell limit: 32,767 characters.
        styleRows.push([
          component,
          name,
          group,
          style.label,
          Array.isArray(style.classes)
            ? style.classes.join(' ')
            : style.classes,
          templates,
          theme,
          css.slice(0, 32000),
          match?.matchStatus ||
            (theme
              ? 'FE unavailable'
              : 'FE not configured')
        ]);
      }
    }
  }

  sheet(
    book,
    'Style System',
    [
      'Component',
      'Policy Name',
      'Style Group',
      'Style Name',
      'CSS Class',
      'Associated Templates',
      'Theme',
      'Actual FE CSS',
      'CSS Match Status'
    ],
    styleRows
  );

  sheet(
    book,
    'Policy Summary',
    [
      'Component',
      'Policy Name',
      'Number of Styles',
      'Associated Templates',
      'Reference Status'
    ],
    policyRows
  );

  if(fe) {
    const usedNames = new Set([
      'Style System',
      'Policy Summary'
    ]);

    for(const theme of fe.themes) {
      let name = `Theme - ${theme}`
        .slice(0,31)
        .replace(/[\\/*?:\[\]]/g,'_');

      let n = 1;

      while(usedNames.has(name)) {
        name = `Theme - ${theme}`.slice(0,27) +
          ` ${n++}`;
      }

      usedNames.add(name);

      const rows = fe.tokens
        .filter(t => t.theme === theme)
        .map(t => [
          t.category,
          t.name,
          t.value,
          t.type,
          t.context,
          t.source
        ]);

      sheet(
        book,
        name,
        [
          'Category',
          'Token / Variable',
          'Value',
          'Type',
          'Selector / Context',
          'Source'
        ],
        rows
      );
    }
  }

  const dest = path.join(
    dir,
    'EWP_Style_System_Export.xlsx'
  );

  await book.xlsx.writeFile(dest);

  console.log('[EXCEL] Saved:',dest);

  if(validation.complete === false) {
    console.warn(
      '[WARNING] AEM validation incomplete; ' +
      'see output/validation-report.json'
    );
  }

  for(const w of [
    ...(master.warnings || []),
    ...(fe?.warnings || [])
  ]) {
    console.warn('[WARNING]',w);
  }
}

main().catch(e => {
  console.error('[EXCEL ERROR]',e.message);
  process.exitCode = 1;
});
