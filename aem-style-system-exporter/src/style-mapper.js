
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


function classifySelector(selector, targetClass) {
  try {
    const results = [];

    selectorParser(selectors => {
      selectors.each(selectorNode => {
        const classes = new Set();

        selectorNode.walkClasses(node => {
          classes.add(node.value);
        });

        if (!classes.has(targetClass)) return;

        const additionalClasses = [...classes]
          .filter(name => name !== targetClass);

        results.push({
          selector: selectorNode.toString(),
          matchType: additionalClasses.length
            ? "Conditional"
            : "Direct",
          additionalClasses
        });
      });
    }).processSync(selector);

    return results;
  } catch (error) {
    console.warn(
      `[MAP] Failed to classify selector: ${selector}`
    );
    return [];
  }
}


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
			classes.flatMap(targetClass =>
			  (classIndex.get(`${theme}\u0000${targetClass}`) || [])
				.flatMap(rule =>
				  classifySelector(rule.selector, targetClass)
					.map(classification => ({
					  ...rule,
					  selector: classification.selector,
					  matchType: classification.matchType,
					  additionalClasses: classification.additionalClasses
					}))
				)
			).map(rule => [
			  [
				rule.source,
				rule.selector,
				rule.contexts.join("|"),
				JSON.stringify(rule.declarations)
			  ].join("|"),
			  rule
			])
		  ).values()
		];


		const directCount = matches.filter(
		  rule => rule.matchType === "Direct"
		).length;

		const conditionalCount = matches.filter(
		  rule => rule.matchType === "Conditional"
		).length;

		let matchStatus = "Not Found";

		if (directCount && conditionalCount) {
		  matchStatus = "Mixed";
		} else if (directCount) {
		  matchStatus = "Direct";
		} else if (conditionalCount) {
		  matchStatus = "Conditional";
		}

		rows.push({
		  policyPath: policy.path,
		  stylePath: style.path,
		  theme,
		  matchStatus,
		  directCount,
		  conditionalCount,
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
