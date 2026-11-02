
const fs = require('node:fs');
const path = require('node:path');
const selectorParser = require('postcss-selector-parser');

const root = path.resolve(__dirname, '..');
const dir = path.join(root, 'output');

const read = n => JSON.parse(
  fs.readFileSync(path.join(dir, n), 'utf8')
);

const fe = read('fe-data.json');
const policies = read('policies.json');

const classIndex = new Map();

for (const rule of fe.rules) {
  try {
    const classes = new Set();

    selectorParser(selectors =>
      selectors.walkClasses(c => classes.add(c.value))
    ).processSync(rule.selector);

    for (const c of classes) {
      const key = `${rule.theme}\u0000${c}`;

      if (!classIndex.has(key)) {
        classIndex.set(key, []);
      }

      classIndex.get(key).push(rule);
    }
  } catch(e) {
    fe.warnings.push(
      `Selector parse failed: ${rule.selector}`
    );
  }
}

const rows = [];

for (const policy of policies) {
  const styles = [
    ...(policy.styleGroups || []).flatMap(g =>
      (g.styles || []).map(s => ({
        ...s,
        group: g.label || ''
      }))
    ),
    ...(policy.ungroupedStyles || []).map(s => ({
      ...s,
      group: 'Ungrouped'
    }))
  ];

  for (const style of styles) {
    const classes = (
      Array.isArray(style.classes)
        ? style.classes.join(' ')
        : String(style.classes || '')
    ).split(/\s+/).filter(Boolean);

    for (const theme of fe.themes) {
      const matches = [
        ...new Map(
          classes.flatMap(c =>
            classIndex.get(`${theme}\u0000${c}`) || []
          ).map(r => [
            `${r.source}|${r.selector}|` +
            `${r.contexts.join('|')}|` +
            `${JSON.stringify(r.declarations)}`,
            r
          ])
        ).values()
      ];

      rows.push({
        policyPath: policy.path,
        stylePath: style.path,
        theme,
        matchStatus: matches.length
          ? 'Matched selector (not computed style)'
          : 'Not found',
        cssRules: matches
      });
    }
  }
}

fs.writeFileSync(
  path.join(dir, 'style-css-mapping.json'),
  JSON.stringify({
    rows,
    warnings: fe.warnings
  }, null, 2)
);

console.log(
  `[MAP] ${rows.length} style-theme combinations mapped`
);
