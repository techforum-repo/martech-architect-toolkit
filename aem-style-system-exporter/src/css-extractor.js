
const fs = require('node:fs');
const path = require('node:path');
const postcss = require('postcss');

const root = path.resolve(__dirname, '..');
const out = path.join(root, 'output', 'fe-data.json');

const project = process.env.FE_PROJECT_PATH?.trim();

const themes = [
  ...new Set(
    (process.env.FE_THEMES || 'corporate')
      .split(',')
      .map(s => s.trim())
      .filter(Boolean)
  )
];

const shared = (process.env.FE_SHARED_CSS || '')
  .split(',')
  .map(s => s.trim())
  .filter(Boolean);

const records = [];
const warnings = [];
const tokenRows = [];
const rules = [];

function category(name) {
  const n = name.toLowerCase();

  if (/color|background|accent|brand|neutral/.test(n))
    return 'Color';

  if (/font|typograph|line-height|letter/.test(n))
    return 'Typography';

  if (/space|padding|margin|gap/.test(n))
    return 'Spacing';

  if (/breakpoint|screen|media/.test(n))
    return 'Breakpoint';

  if (/shadow/.test(n)) return 'Shadow';
  if (/border|radius/.test(n)) return 'Border';

  return 'Other';
}

function parseFile(theme, file) {
  const css = fs.readFileSync(file, 'utf8');
  const ast = postcss.parse(css, {from: file});

  let count = 0;

  ast.walkRules(rule => {
    const contexts = [];
    let parent = rule.parent;

    while (parent && parent.type !== 'root') {
      if (parent.type === 'atrule') {
        contexts.unshift(`@${parent.name} ${parent.params}`);
      }
      parent = parent.parent;
    }

    const declarations = [];

    rule.walkDecls(d => {
      if (d.parent !== rule) return;

      declarations.push({
        property: d.prop,
        value: d.value,
        important: !!d.important
      });

      if (d.prop.startsWith('--')) {
        tokenRows.push({
          theme,
          category: category(d.prop),
          name: d.prop,
          value: d.value,
          type: 'CSS custom property',
          context: [...contexts, rule.selector].join(' | '),
          source: path.relative(project, file)
            .replace(/\\/g, '/')
        });
      }
    });

    rules.push({
      theme,
      selector: rule.selector,
      contexts,
      declarations,
      source: path.relative(project, file)
        .replace(/\\/g, '/')
    });

    count++;
  });

  records.push({theme, file, ruleCount: count});

  console.log(
    `[FE] ${theme}: ${path.basename(file)} - ${count} CSS rules`
  );
}

function main() {
  if (
    !project ||
    !fs.existsSync(project) ||
    !fs.statSync(project).isDirectory()
  ) {
    throw Error('FE project folder is missing');
  }

  for (const theme of themes) {
    const candidates = [
      path.join(
        project,
        'dist',
        `clientlib-${theme}`,
        `${theme}.css`
      ),
      ...shared.map(s =>
        path.isAbsolute(s) ? s : path.join(project, s)
      )
    ];

    const seen = new Set();
    let found = false;

    for (const file of candidates) {
      if (seen.has(file)) continue;
      seen.add(file);

      if (!fs.existsSync(file)) {
        warnings.push(`Missing CSS for ${theme}: ${file}`);
        continue;
      }

      try {
        parseFile(theme, file);
        found = true;
      } catch(e) {
        warnings.push(`Failed parsing ${file}: ${e.message}`);
      }
    }

    if (!found) {
      warnings.push(`Theme ${theme} has no usable CSS`);
    }
  }

  fs.writeFileSync(
    out,
    JSON.stringify({
      themes,
      records,
      warnings,
      tokens: tokenRows,
      rules
    }, null, 2)
  );

  console.log(
    `[FE] ${rules.length} rules, ` +
    `${tokenRows.length} CSS variables; ` +
    `${warnings.length} warnings`
  );

  if (!rules.length) {
    process.exitCode = 2;
  }
}

try {
  main();
} catch(e) {
  console.error('[FE ERROR]', e.message);
  process.exitCode = 1;
}
