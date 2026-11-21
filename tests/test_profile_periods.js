#!/usr/bin/env node
// Local verification for the chunk-2 period tabs (Balance / Cash flow /
// Ratios). Extracts the pure period functions from profile.js and runs
// them against the real rebuilt data/financials/*.json files — no DOM,
// no network, no push.
//
// Run:  node tests/test_profile_periods.js
//
// NOTE: no 'use strict' here on purpose — the extracted functions are
// loaded with a direct eval in sloppy mode so their declarations land
// in this file's scope.
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const src = fs.readFileSync(path.join(ROOT, 'profile.js'), 'utf8');

// Extract top-level function declarations by name (brace matching).
function extract(name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`function ${name} not found in profile.js`);
  let i = src.indexOf('{', start);
  let depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error(`unbalanced braces in ${name}`);
}

// Minimal DOM stub: records table HTML per id.
const tables = {};
const switches = {};
global.document = {
  querySelector(sel) {
    if (sel.startsWith('#') && sel.endsWith('Table')) {
      const id = sel.slice(1);
      tables[id] = tables[id] || { innerHTML: '' };
      return tables[id];
    }
    if (sel.startsWith('#') && (sel.endsWith('Eyebrow') || sel.endsWith('Subtitle'))) {
      return { textContent: '' };
    }
    return { textContent: '' };
  },
  querySelectorAll(sel) {
    if (sel.includes('PeriodSwitch')) {
      const id = sel.match(/#(\w+)/)[1];
      switches[id] = switches[id] || [{ dataset: { period: 'yearly' }, classList: { toggle() {} } }];
      return switches[id];
    }
    return [];
  },
};

const fns = ['fmtMillions', 'fmtCap', 'fmtPct', 'fmtSignedPct', 'fmtNum',
  'fmtDollars', 'fmtDays', 'table', 'emptyTable', 'halfYearly',
  'halfYearlyRatios', 'balanceRowsFor', 'cashflowRowsFor', 'ratiosRowsFor',
  'renderPeriodSection', 'renderBalance', 'renderCashflow', 'renderRatios'];
for (const name of fns) eval(extract(name));
// halfYearly reads the field lists, which are consts in profile.js —
// const/let never leak out of an eval, so put them on globalThis,
// where the eval'd functions resolve them as bare identifiers.
for (const name of ['HALF_FLOW_FIELDS', 'HALF_STOCK_FIELDS']) {
  const m = src.match(new RegExp(`const ${name} = (\\[[^\\]]*\\]);`));
  if (!m) throw new Error(`${name} not found in profile.js`);
  globalThis[name] = eval(m[1]);
}
let periodData = null;

let failures = 0;
function check(cond, msg) {
  if (!cond) { failures++; console.log('FAIL:', msg); }
  else console.log('ok:', msg);
}
function load(sym) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'financials', `${sym}.json`), 'utf8'));
}

const aapl = load('AAPL');
const q = aapl.quarterly;
const halves = halfYearly(q);

// Half-yearly derivation: flows sum, balances are the half-end value.
const h1fy25 = halves.find(h => h.label === 'H1 FY2025');
const q1 = q.find(x => x.label === 'Q1 FY2025');
const q2 = q.find(x => x.label === 'Q2 FY2025');
check(h1fy25.revenue === q1.revenue + q2.revenue, 'AAPL H1 FY2025 revenue = Q1+Q2');
check(h1fy25.cfo === q1.cfo + q2.cfo, 'AAPL H1 FY2025 cfo = Q1+Q2');
check(h1fy25.cash === q2.cash, 'AAPL H1 FY2025 cash = Q2 (half-end) balance, not a sum');
check(h1fy25.assets === q2.assets, 'AAPL H1 FY2025 assets = Q2 balance');
check(halves.length === 6, `AAPL has 6 complete halves (got ${halves.length})`);

// DOW: Q2 FY2026 is missing, so H1 FY2026 must be skipped, never estimated.
const dow = load('DOW');
const dowHalves = halfYearly(dow.quarterly);
check(!dowHalves.some(h => h.label === 'H1 FY2026'), 'DOW H1 FY2026 skipped (Q2 missing)');
check(dowHalves.some(h => h.label === 'H2 FY2025'), 'DOW H2 FY2025 present');

// Half-yearly ratios: H2 FY2025 trailing = H1+H2 FY2025 = the FY2025
// annual figures, so H2 roe must match the annual roe basis.
const aaplRatios = halfYearlyRatios(halves);
const h2 = aaplRatios.find(r => r.label === 'H2 FY2025');
const ann25 = aapl.annual.find(a => a.fy === 2025);
const annRatio25 = aapl.ratios.find(a => a.fy === 2025);
check(Math.abs(h2.roe - annRatio25.roe) < 1e-9, `AAPL H2 FY2025 roe matches annual roe (${h2.roe} vs ${annRatio25.roe})`);
// opm is the half's own margin, not the annual one: H2 opm must equal
// (Q3+Q4 operating income) / (Q3+Q4 revenue) from the quarters.
const q3 = q.find(x => x.label === 'Q3 FY2025');
const q4 = q.find(x => x.label === 'Q4 FY2025');
const h2opm = (q3.operating_income + q4.operating_income) / (q3.revenue + q4.revenue);
check(Math.abs(h2.opm - h2opm) < 1e-9, 'AAPL H2 FY2025 opm equals (Q3+Q4 ebit)/(Q3+Q4 revenue)');
// H2 FY2023 is the first half in DOW's window: its preceding half
// (H1 FY2023) is missing, so trailing ratios are null while the
// half's own margin is still computed.
const dowRatios = halfYearlyRatios(dowHalves);
const dowH2fy23 = dowRatios.find(r => r.label === 'H2 FY2023');
check(dowH2fy23 && dowH2fy23.roe === null, 'DOW H2 FY2023 roe is null (preceding half missing, not estimated)');
// DOW's Q3/Q4 FY2023 operating income is not reported quarterly, so
// the half's opm is null too — but its net margin is computable from
// the reported net income of both quarters.
check(dowH2fy23 && dowH2fy23.net_margin !== null, 'DOW H2 FY2023 net margin still computed (needs only the half itself)');
check(dowH2fy23 && dowH2fy23.opm === null, 'DOW H2 FY2023 opm is null (operating income not reported for those quarters)');
check(!dowHalves.some(h => h.label === 'H2 FY2026'), 'DOW H2 FY2026 absent (Q4 not yet reported)');

// Quarterly ratios from the pipeline match the half-yearly trailing
// basis: Q4 FY2025 roe (TTM ni / Q4 equity) equals the annual roe.
const q4ratio = aapl.quarterly_ratios.find(r => r.label === 'Q4 FY2025');
check(Math.abs(q4ratio.roe - annRatio25.roe) < 1e-9, 'AAPL Q4 FY2025 roe matches annual roe');

// Render functions produce tables for all three periods, all sections.
periodData = { annual: aapl.annual, quarterly: aapl.quarterly, ratios: aapl.ratios, quarterly_ratios: aapl.quarterly_ratios };
for (const [fn, tableId] of [[renderBalance, 'balanceTable'], [renderCashflow, 'cashflowTable'], [renderRatios, 'ratiosTable']]) {
  for (const period of ['yearly', 'half', 'quarter']) {
    fn(period);
    const html = tables[tableId].innerHTML;
    check(html.includes('<th>'), `${tableId} ${period} renders a table`);
  }
}
check(tables.balanceTable.innerHTML.includes('Q1 FY2025'), 'balance quarterly view shows quarter labels');
renderBalance('half');
check(tables.balanceTable.innerHTML.includes('H1 FY2025'), 'balance half-yearly view shows half labels');
renderRatios('quarter');
check(tables.ratiosTable.innerHTML.includes('Q4 FY2025'), 'ratios quarterly view shows quarter labels');
// Yearly ratios keep the ad row when the filer breaks out advertising.
check(tables.ratiosTable.innerHTML.includes('Ad spend') === false, 'ratios quarterly view omits the ad row (yearly only)');
renderRatios('yearly');
check(tables.ratiosTable.innerHTML.includes('FY2025'), 'ratios yearly view shows FY labels');

// Empty states: a ticker with no quarters renders the empty message.
const arm = load('ARM');
periodData = { annual: arm.annual, quarterly: arm.quarterly, ratios: arm.ratios, quarterly_ratios: arm.quarterly_ratios || [] };
renderBalance('quarter');
check(tables.balanceTable.innerHTML.includes('No complete periods'), 'ARM quarterly balance shows the empty state');

console.log(failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECKS FAILED`);
process.exit(failures === 0 ? 0 : 1);
