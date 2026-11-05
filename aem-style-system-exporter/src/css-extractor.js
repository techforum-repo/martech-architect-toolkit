
const fs = require('node:fs');
const path = require('node:path');
const postcss = require('postcss');

const settings = require('./settings');

settings.load();
const out = path.join(settings.dataDir(), 'fe-data.json');

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
const loadedThemes = [];


function category(name) {
  const n = String(name || '').toLowerCase().trim();

  // Typography
  if (
    /^--(fs-|ffs-|ff-|fw-|lh-|ls-)/.test(n) ||
    /font|typograph|line-height|letter-spacing|text-size/.test(n)
  ) {
    return 'Typography';
  }

  // Spacing
  if (
    /^--(space-|spacing-|gap-|padding-|margin-)/.test(n) ||
    /gutter|column-gap|row-gap/.test(n)
  ) {
    return 'Spacing';
  }

  // Breakpoints
  if (
    /^--(breakpoint-|screen-|media-)/.test(n) ||
    /viewport/.test(n)
  ) {
    return 'Breakpoint';
  }

  // Shadows
  if (/shadow|elevation/.test(n)) {
    return 'Shadow';
  }

  // Borders
  if (/border|radius|outline/.test(n)) {
    return 'Border';
  }

  // Backgrounds and surfaces
  if (
    /^--(surface-|background-|bg-|gradient-)/.test(n) ||
    /background-image/.test(n)
  ) {
    return 'Background';
  }

  // Colors
  if (
    /^--(color-|neutral-|accent-|brand-|action-|feedback-)/.test(n) ||
    /color|palette|primary-|secondary-|tertiary-/.test(n)
  ) {
    return 'Color';
  }

  // Sizing and dimensions
  if (
    /^--(size-|width-|height-|max-width-|min-width-)/.test(n) ||
    /dimension/.test(n)
  ) {
    return 'Sizing';
  }

  // Motion and animation
  if (
    /animation|transition|duration|easing|motion/.test(n)
  ) {
    return 'Animation';
  }

  // Layering
  if (
    /z-index|zindex|layer/.test(n)
  ) {
    return 'Layering';
  }

  // Opacity
  if (/opacity|alpha/.test(n)) {
    return 'Opacity';
  }

  // Uncategorized
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

    if (found) {
      loadedThemes.push(theme);
    } else {
      warnings.push(`Theme ${theme} has no usable CSS`);
    }
  }

  fs.writeFileSync(
    out,
    JSON.stringify({
      themes,
      loadedThemes,
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
