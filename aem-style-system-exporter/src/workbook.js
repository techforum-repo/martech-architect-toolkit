// Shared workbook helpers: the styled sheet every tab uses, and the Changes
// sheet built from diff.js results (in the export workbook and in compare.js).

// ExcelJS writes strings as literal text cells (never formulas), so no
// formula-injection escaping is needed; prefixing "'" would show up in the cell.
function cellValue(v) {
  return v == null ? '' : v;
}

function width(header) {
  if (/Actual FE CSS/.test(header)) return 80;
  if (/^Details$/.test(header)) return 70;
  if (/Templates|^Item$/.test(header)) return 48;
  if (/Context|Source|CSS Class/.test(header)) return 42;
  if (/^(Area|Change)$/.test(header)) return 16;
  return 25;
}

function sheet(book, name, headers, rows) {
  const ws = book.addWorksheet(name, {
    views: [{state: 'frozen', ySplit: 1}]
  });

  ws.columns = headers.map(h => ({header: h, key: h, width: width(h)}));

  for (const row of rows) {
    ws.addRow(row.map(cellValue));
  }

  ws.getRow(1).height = 28;

  ws.getRow(1).eachCell(c => {
    c.font = {bold: true, color: {argb: 'FFFFFFFF'}};
    c.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FF183A5B'}};
    c.alignment = {wrapText: true, vertical: 'middle'};
  });

  ws.autoFilter = {
    from: {row: 1, column: 1},
    to: {row: 1, column: headers.length}
  };

  for (let i = 2; i <= ws.rowCount; i++) {
    const row = ws.getRow(i);
    row.height = 32;

    row.eachCell(c => {
      c.alignment = {wrapText: true, vertical: 'top'};
      c.font = {name: 'Aptos', size: 10, color: {argb: 'FF16603D'}};
      if (i % 2 === 0) {
        c.fill = {type: 'pattern', pattern: 'solid', fgColor: {argb: 'FFF0F5FA'}};
      }
    });
  }

  console.log(`[EXCEL] ${name}: ${rows.length} rows`);
  return ws;
}

const CHANGE_HEADERS = ['Area', 'Change', 'Item', 'Details', 'Last modified by', 'Last modified'];

function describe(meta) {
  if (!meta) return '';
  const environment = meta.environmentName ? `${meta.environmentName} (${meta.environment})` : meta.environment;
  return `${environment}, run ${meta.id}, exported ${String(meta.createdAt || '').slice(0, 16).replace('T', ' ')} UTC`;
}

function summary(counts) {
  return Object.entries(counts || {}).map(([area, c]) =>
    `${area}: ` + ['Added', 'Removed', 'Changed'].filter(k => c[k]).map(k => `${c[k]} ${k.toLowerCase()}`).join(', ')
  ).join('; ');
}

// Rows for the Changes sheet: what was compared first, then one row per change.
function changeRows(changes) {
  const rows = [];
  if (changes.comparedWith) {
    rows.push(['Compared', '', `${describe(changes.comparedWith)} → ${describe(changes.current)}`,
               changes.rows.length ? summary(changes.counts) : 'No changes.', '', '']);
  }
  for (const note of changes.notes || []) rows.push(['Note', '', note, '', '', '']);
  for (const row of changes.rows) {
    rows.push([row.area, row.change, row.item, row.details, row.modifiedBy, row.modifiedAt]);
  }
  return rows;
}

function changesSheet(book, changes, name = 'Changes') {
  return sheet(book, name, CHANGE_HEADERS, changeRows(changes));
}

module.exports = { CHANGE_HEADERS, cellValue, changeRows, changesSheet, sheet };
