#!/usr/bin/env node
// Local verification for the fuller Screener.in remainder: fuller
// quarterly P&L rows (expenses, other income, interest, depreciation,
// PBT, tax %), the Latest Q column on Balance sheet / Cash flow, the
// CAGR growth cards, and the book value / dividend yield source data.
// Extracts the pure functions from profile.js and runs them against
// the real rebuilt data/financials/*.json and data/chart/*.json
// files — no DOM, no network, no push.
//
// Run:  node tests/test_profile_fuller.js
//
// NOTE: no 'use strict' here on purpose — the extracted functions are
// loaded with a direct eval in sloppy mode so their declarations land
// in this file's scope (same harness as test_profile_screenerin.js).
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'profile.js'), 'utf8');

// Extract top-level function declarations by name (brace matching).
// Keeps an `async ` prefix when the function is async, so an await
// inside the body still parses.
function extract(name) {
  let start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found in profile.js`);
  if (src.slice(start - 6, start) === 'async ') start -= 6;
  let i = src.indexOf('{', start);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error(`unbalanced braces in ${name}`);
}

// Minimal DOM stub: records table/grid HTML per id.
const tables = {};
const grids = {};
global.document = {
  querySelector(sel) {
    if (sel.startsWith('#') && sel.endsWith('Table')) {
      const id = sel.slice(1);
      tables[id] = tables[id] || { innerHTML: '' };
      return tables[id];
    }
    if (sel === '#growthGrid') {
      grids.growth = grids.growth || { innerHTML: '' };
      return grids.growth;
    }
    if (sel.startsWith('#') && (sel.endsWith('Eyebrow') || sel.endsWith('Subtitle'))) {
      return { textContent: '' };
    }
    return { textContent: '' };
  },
  querySelectorAll(sel) {
    if (sel.includes('PeriodSwitch')) {
      const id = sel.match(/#(\w+)/)[1];
      return [{ dataset: { period: 'yearly' }, classList: { toggle() {} } }];
    }
    return [];
  },
};
globalThis.lucide = { createIcons() {} };

const fns = ['fmtMillions', 'fmtCap', 'fmtPct', 'fmtSignedPct', 'fmtNum',
  'fmtDollars', 'fmtDays', 'table', 'emptyTable', 'halfYearly',
  'halfYearlyRatios', 'ttmFor', 'growthFor', 'profitRowsFor',
  'renderProfit', 'balanceRowsFor', 'cashflowRowsFor', 'ratiosRowsFor',
  'renderPeriodSection', 'renderBalance', 'renderCashflow', 'renderRatios',
  'renderGrowth', 'edgarLinks', 'movingAverage', 'movingAverageSeries',
  'isDailySeries', 'cagrFor', 'roeAvgFor', 'ttmGrowthFor', 'priceCagrFor',
  'cagrValues', 'growthCardsHtml'];
for (const name of fns) eval(extract(name));
// halfYearly reads the field lists, which are consts in profile.js —
// const/let never leak out of an eval, so put them on globalThis,
// where the eval'd functions resolve them as bare identifiers.
for (const name of ['HALF_FLOW_FIELDS', 'HALF_STOCK_FIELDS']) {
  const m = src.match(new RegExp(`const ${name} = (\\[[^\\]]*\\]);`));
  if (!m) throw new Error(`${name} not found in profile.js`);
  globalThis[name] = eval(m[1]);
}
let profitData = null;
let periodData = null;

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures++; console.log('FAIL:', msg); }
  else console.log('ok:', msg);
}
function load(sym) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'financials', `${sym}.json`), 'utf8'));
}
function loadChart(sym, range) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'chart', `${sym}-${range}.json`), 'utf8'));
}
global.NorthstarAPI = {
  async chart(sym, range) { return loadChart(sym, range); },
};

const aapl = load('AAPL');
const msft = load('MSFT');
const dow = load('DOW');
const chart10y = loadChart('AAPL', '10y');

// Row values are "$X,XXX" strings or "—"; strip to numbers ($M).
// The returned array has one entry per year plus the trailing
// column (TTM on the yearly P&L, Latest Q on Balance sheet /
// Cash flow) at index years.length.
function values(row, years) {
  const out = years.map((y, i) => {
    const cell = row[i + 1];
    if (cell === '—' || cell === undefined) return null;
    return Number(String(cell).replace(/[$,]/g, ''));
  });
  const last = row[row.length - 1];
  out.push(last === '—' || last === undefined ? null
    : Number(String(last).replace(/[$,]/g, '')));
  return out;
}
function rowsByLabel(result) {
  return Object.fromEntries(result.rows.map((r) => [r[0], r]));
}
function approx(actual, expected, tol, msg) {
  check(actual != null && Math.abs(actual - expected) < tol,
    `${msg} (got ${actual == null ? 'null' : (actual * 100).toFixed(2) + '%'}, expected ~${(expected * 100).toFixed(1)}%)`);
}

async function main() {
  // --- 1. Fuller P&L rows (yearly) ---------------------------------
  profitData = { annual: aapl.annual, quarterly: aapl.quarterly };
  const aaplYears = aapl.annual.map((r) => `FY${r.fy}`);
  const aaplRows = rowsByLabel(profitRowsFor('yearly'));
  const fy26 = aaplYears.indexOf('FY2026');
  check(values(aaplRows['Expenses'], aaplYears)[fy26] === 320771,
    'AAPL FY2026 expenses $320,771M = revenue - operating income');
  check(values(aaplRows['Other income'], aaplYears)[fy26] === 1174,
    'AAPL FY2026 other income $1,174M');
  check(values(aaplRows['Interest'], aaplYears)[fy26] === null,
    'AAPL FY2026 interest blank (no separate interest line after FY2023)');
  check(values(aaplRows['Depreciation'], aaplYears)[fy26] === 13423,
    'AAPL FY2026 depreciation $13,423M');
  check(values(aaplRows['Profit before tax'], aaplYears)[fy26] === 159237,
    'AAPL FY2026 PBT $159,237M');
  check(aaplRows['Tax %'][fy26 + 1] === '17.0%',
    'AAPL FY2026 tax rate 17.0%');
  check(aaplRows['Tax'] === undefined,
    'no Tax $ row: tax is shown as Tax % only');

  // MSFT FY2026: interest via the InterestExpenseNonoperating tag.
  profitData = { annual: msft.annual, quarterly: msft.quarterly };
  const msftYears = msft.annual.map((r) => `FY${r.fy}`);
  const msftRows = rowsByLabel(profitRowsFor('yearly'));
  const m26 = msftYears.indexOf('FY2026');
  check(values(msftRows['Interest'], msftYears)[m26] === 3051,
    'MSFT FY2026 interest $3,051M (InterestExpenseNonoperating tag)');
  check(values(msftRows['Profit before tax'], msftYears)[m26] === 165934,
    'MSFT FY2026 PBT $165,934M');
  check(msftRows['Tax %'][m26 + 1] === '19.4%',
    'MSFT FY2026 tax rate 19.4%');

  // DOW FY2025: no operating income anywhere, so no Expenses row at
  // all; PBT is a loss and tax is a benefit.
  profitData = { annual: dow.annual, quarterly: dow.quarterly };
  const dowYears = dow.annual.map((r) => `FY${r.fy}`);
  const dowRows = rowsByLabel(profitRowsFor('yearly'));
  const d25 = dowYears.indexOf('FY2025');
  check(dowRows['Expenses'] === undefined,
    'DOW has no Expenses row (no operating income reported in any year)');
  check(values(dowRows['Profit before tax'], dowYears)[d25] === -2511,
    'DOW FY2025 PBT -$2,511M (a loss year)');
  check(dowRows['Tax %'][d25 + 1] === '2.7%',
    'DOW FY2025 tax rate 2.7% (benefit on a pre-tax loss)');

  // --- 2. TTM column still sums the fuller rows --------------------
  profitData = { annual: aapl.annual, quarterly: aapl.quarterly };
  const ttmRows = rowsByLabel(profitRowsFor('yearly'));
  check(values(ttmRows['Expenses'], aaplYears)[aaplYears.length] === 320771,
    'AAPL TTM expenses $320,771M = FY2026 annual (latest quarter is Q4 FY2026)');
  check(values(ttmRows['Interest'], aaplYears)[aaplYears.length] === null,
    'AAPL TTM interest blank (all four quarters missing)');

  // --- 3. Fuller P&L rows (quarterly) ------------------------------
  const qRows = rowsByLabel(profitRowsFor('quarter'));
  const qLabels = aapl.quarterly.map((q) => q.label);
  const q4 = qLabels.indexOf('Q4 FY2026');
  check(values(qRows['Expenses'], qLabels)[q4] === 78846,
    'AAPL Q4 FY2026 expenses $78,846M');
  check(values(qRows['Depreciation'], qLabels)[q4] === 3450,
    'AAPL Q4 FY2026 depreciation $3,450M (YTD differencing: FY - 9M)');
  check(values(qRows['Profit before tax'], qLabels)[q4] === 36135,
    'AAPL Q4 FY2026 PBT $36,135M');
  check(qRows['Tax %'][q4 + 1] === '15.0%',
    'AAPL Q4 FY2026 tax rate 15.0%');

  // --- 4. Latest Q column: Balance sheet ---------------------------
  periodData = { annual: aapl.annual, quarterly: aapl.quarterly,
    ratios: aapl.ratios, quarterly_ratios: aapl.quarterly_ratios };
  const bs = balanceRowsFor('yearly');
  const bsRows = rowsByLabel(bs);
  check(bs.headers[bs.headers.length - 1] === 'Q4 FY2026',
    'Balance sheet yearly view has a Q4 FY2026 column last');
  check(values(bsRows['Total assets'], aaplYears)[aaplYears.length] === 404548,
    'Balance sheet Latest Q total assets = Q4 FY2026 $404,548M');
  check(values(bsRows['Cash & equivalents'], aaplYears)[aaplYears.length] === 36305,
    'Balance sheet Latest Q cash = Q4 FY2026 $36,305M');

  // --- 5. Latest Q column: Cash flow -------------------------------
  const cf = cashflowRowsFor('yearly');
  const cfRows = rowsByLabel(cf);
  check(cf.headers[cf.headers.length - 1] === 'Q4 FY2026',
    'Cash flow yearly view has a Q4 FY2026 column last');
  const latestQ = aapl.quarterly[aapl.quarterly.length - 1];
  check(values(cfRows['Cash from operations'], aaplYears)[aaplYears.length]
      === Math.round(latestQ.cfo / 1e6),
    "Cash flow Latest Q CFO = latest quarter's CFO");
  check(values(cfRows['Capital expenditure'], aaplYears)[aaplYears.length]
      === Math.round(latestQ.capex / 1e6),
    "Cash flow Latest Q capex = latest quarter's capex");

  // --- 6. CAGR math (hand-computed values) -------------------------
  const aaplRev = aapl.annual.map((r) => r.revenue);
  approx(cagrFor(aaplRev, 10), 0.085, 0.002, 'AAPL revenue 10Y CAGR ~8.5%');
  approx(cagrFor(aaplRev, 5), 0.050, 0.002, 'AAPL revenue 5Y CAGR ~5.0%');
  approx(cagrFor(aaplRev, 3), 0.107, 0.002, 'AAPL revenue 3Y CAGR ~10.7%');
  approx(roeAvgFor(aapl.ratios, 10), 1.178, 0.003, 'AAPL ROE 10Y avg ~117.8%');
  check(cagrFor(dow.annual.map((r) => r.revenue), 10) === null,
    'DOW 10Y revenue CAGR blank (only 9 annual rows)');
  check(cagrFor(dow.annual.map((r) => r.revenue), 5) < 0,
    'DOW revenue 5Y CAGR is negative (-7.7%)');
  approx(ttmGrowthFor(aapl.quarterly, 'revenue'), 0.151, 0.002,
    'AAPL TTM revenue growth ~15.1%');
  approx(priceCagrFor(chart10y.points, 10), 0.292, 0.01,
    'AAPL price 10Y CAGR ~29.2% ($27.51 in Nov 2016 to $356.27)');
  const vals = cagrValues(aapl, chart10y.points);
  approx(vals.sales.y10, 0.085, 0.002, 'cagrValues sales 10Y ~8.5%');
  approx(vals.roe.y10, 1.178, 0.003, 'cagrValues ROE 10Y ~117.8%');
  approx(vals.price.y10, 0.292, 0.01, 'cagrValues price 10Y ~29.2%');
  check(vals.sales.ttm === aapl.metrics.growth,
    'cagrValues sales TTM = metrics.growth');
  check(cagrValues(dow, null).sales.y10 === null,
    'DOW 10Y sales CAGR blank in cagrValues');

  // --- 7. Growth cards render (async: needs the 10y chart) --------
  await renderGrowth(aapl);
  const grid = grids.growth.innerHTML;
  check((grid.match(/insight-card/g) || []).length === 7,
    `AAPL renders 7 growth cards, got ${(grid.match(/insight-card/g) || []).length}`);
  check(grid.includes('8.5%'), 'Sales CAGR card shows 10Y 8.5%');
  check(grid.includes('117.8%'), 'ROE card shows 10Y average 117.8%');
  check(grid.includes('15.1%'), 'Sales CAGR card shows TTM growth 15.1%');
  check(grid.includes('29.2%'), 'Price CAGR card shows 10Y 29.2%');

  // --- 8. Key numbers source data ----------------------------------
  check(Math.abs(aapl.metrics.book_value_per_share - 7.71) < 0.01,
    'AAPL book value per share $7.71 (equity $112.1B / 14.53B shares)');
  check(Math.abs(aapl.metrics.dividend_yield - 0.00307) < 0.0001,
    'AAPL dividend yield 0.31% (DPS $1.08 / price $352.78)');
  check(Math.abs(msft.metrics.dividend_yield - 0.00687) < 0.0001,
    'MSFT dividend yield 0.69% (DPS $3.56 / price $517.99)');
  check(Math.abs(dow.metrics.dividend_yield - 0.0644) < 0.0005,
    'DOW dividend yield 6.44% (DPS $2.06 / price $31.96)');
}

main().then(() => {
  if (failures) { console.log(`${failures} CHECK(S) FAILED`); process.exit(1); }
  console.log('ALL CHECKS PASSED');
}).catch((err) => { console.error(err); process.exit(1); });
