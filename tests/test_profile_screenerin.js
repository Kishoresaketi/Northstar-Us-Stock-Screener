#!/usr/bin/env node
// Local verification for the Screener.in additions: TTM column on the
// Profit & loss table, growth cards, the three new ratios, SEC
// Documents links, and the 50/200-day moving averages. Extracts the
// pure functions from profile.js and runs them against the real
// rebuilt data/financials/*.json and data/chart/*.json files — no DOM,
// no network, no push.
//
// Run:  node tests/test_profile_screenerin.js
//
// NOTE: no 'use strict' here on purpose — the extracted functions are
// loaded with a direct eval in sloppy mode so their declarations land
// in this file's scope.
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

const aapl = load('AAPL');
const q = aapl.quarterly;
const last4 = q.slice(-4);

// --- TTM column on the P&L yearly view ---
profitData = { annual: aapl.annual, quarterly: q };
const yearly = profitRowsFor('yearly');
check(yearly.headers[yearly.headers.length - 1] === 'TTM', 'P&L yearly view has a TTM column last');
const ttm = ttmFor(q);
const sum4 = f => last4.reduce((a, x) => a + x[f], 0);
check(ttm.revenue === sum4('revenue'), `AAPL TTM revenue = sum of last 4 quarters (${ttm.revenue})`);
check(ttm.net_income === sum4('net_income'), 'AAPL TTM net income = sum of last 4 quarters');
check(ttm.operating_income === sum4('operating_income'), 'AAPL TTM operating income = sum of last 4 quarters');
check(Math.abs(ttm.eps - aapl.metrics.eps_ttm) < 0.02, `AAPL TTM EPS (${ttm.eps.toFixed(2)}) matches metrics.eps_ttm (${aapl.metrics.eps_ttm.toFixed(2)})`);
const revRow = yearly.rows.find(r => r[0] === 'Revenue');
check(revRow[revRow.length - 1] === `$${Math.round(ttm.revenue / 1e6).toLocaleString('en-US')}`, 'P&L TTM revenue cell renders the TTM value');
// Fewer than four quarters: TTM is null, never estimated.
check(ttmFor(q.slice(0, 3)) === null, 'TTM is null with only 3 quarters');
check(ttmFor([]) === null, 'TTM is null with no quarters');
const arm = load('ARM');
profitData = { annual: arm.annual, quarterly: arm.quarterly };
const armYearly = profitRowsFor('yearly');
if (armYearly) {
  const armRev = armYearly.rows.find(r => r[0] === 'Revenue');
  check(armRev[armRev.length - 1] === '—', 'ARM TTM column shows — (no quarters to sum)');
}

// --- Growth cards ---
const g = growthFor(q);
const latest = q[q.length - 1];
const prevQ = q[q.length - 2];
const yearAgo = q.find(x => x.label === `Q${latest.label[1]} FY${Number(latest.label.slice(5)) - 1}`);
check(g.latest === latest.label, `growth latest quarter is ${latest.label}`);
check(Math.abs(g.revenue.yoy - (latest.revenue - yearAgo.revenue) / yearAgo.revenue) < 1e-12, 'AAPL revenue YoY matches hand computation');
check(Math.abs(g.revenue.qoq - (latest.revenue - prevQ.revenue) / prevQ.revenue) < 1e-12, 'AAPL revenue QoQ matches hand computation');
check(Math.abs(g.eps.yoy - (latest.eps - yearAgo.eps) / yearAgo.eps) < 1e-12, 'AAPL EPS YoY matches hand computation');
check(g.revenue.yoyLabel === `${latest.label} vs ${yearAgo.label}`, 'YoY label names both quarters');
periodData = { annual: aapl.annual, quarterly: q, ratios: aapl.ratios, quarterly_ratios: aapl.quarterly_ratios };
renderGrowth(aapl);
check((grids.growth.innerHTML.match(/insight-card/g) || []).length === 7, 'growth grid renders 7 cards (Revenue, Net income, EPS + Sales CAGR, Profit CAGR, Price CAGR, ROE)');
check(grids.growth.innerHTML.includes('Year over year'), 'growth cards show the YoY line');
check(grids.growth.innerHTML.includes('Prior quarter'), 'growth cards show the QoQ line');
renderGrowth(arm);
check(grids.growth.innerHTML.includes('No quarterly filings'), 'ARM growth grid shows the empty state');

// --- New ratios ---
renderRatios('yearly');
check(tables.ratiosTable.innerHTML.includes('Working capital days'), 'ratios yearly view has Working capital days');
check(tables.ratiosTable.innerHTML.includes('Days payable'), 'ratios yearly view has Days payable');
check(tables.ratiosTable.innerHTML.includes('Cash conversion cycle'), 'ratios yearly view has Cash conversion cycle');
renderRatios('quarter');
check(tables.ratiosTable.innerHTML.includes('Cash conversion cycle'), 'ratios quarterly view has Cash conversion cycle');
const aaplRatio25 = aapl.ratios.find(r => r.fy === 2025);
check(Math.abs(aaplRatio25.payable_days - 115.4) < 0.2, `AAPL FY2025 payable days ${aaplRatio25.payable_days.toFixed(1)} (rebuilt file)`);
check(Math.abs(aaplRatio25.working_capital_days - (-15.5)) < 0.2, `AAPL FY2025 working capital days ${aaplRatio25.working_capital_days.toFixed(1)} (negative, as expected)`);
check(Math.abs(aaplRatio25.ccc - (-71.1)) < 0.2, `AAPL FY2025 CCC ${aaplRatio25.ccc.toFixed(1)} (negative, as expected)`);
// Half-yearly ratios: H2 FY2025 CCC is debtor + inventory - payable
// from the same half, and working capital days use the trailing basis.
const halves = halfYearly(q);
const halfRatios = halfYearlyRatios(halves);
const h2 = halfRatios.find(r => r.label === 'H2 FY2025');
check(Math.abs(h2.ccc - (h2.debtor_days + h2.inventory_days - h2.payable_days)) < 1e-9, 'H2 FY2025 CCC = debtor + inventory - payable');
const h1 = halves.find(h => h.label === 'H1 FY2025');
const h2h = halves.find(h => h.label === 'H2 FY2025');
const ttmRevH2 = h1.revenue + h2h.revenue;
check(Math.abs(h2.working_capital_days - (h2h.curr_assets - h2h.curr_liab) / ttmRevH2 * 365) < 1e-9, 'H2 FY2025 working capital days use half-end working capital over trailing revenue');
// Balance sheet shows the Accounts payable row.
renderBalance('yearly');
check(tables.balanceTable.innerHTML.includes('Accounts payable'), 'balance sheet yearly view has Accounts payable');

// --- SEC Documents links ---
const links = edgarLinks('320193');
check(links[0][1] === 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000320193&type=10-K&dateb=&owner=include&count=10', 'AAPL 10-K link uses the 10-digit CIK and type=10-K');
check(links[1][1].includes('type=10-Q'), 'AAPL 10-Q link filters type=10-Q');
check(links[2][1] === 'https://www.sec.gov/edgar/browse/?CIK=320193', 'AAPL all-filings link uses the plain CIK');
check(edgarLinks('789019')[0][1].includes('CIK=0000789019'), 'MSFT CIK pads to 10 digits');

// --- Moving averages ---
check(movingAverage([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 3) === 9, 'movingAverage([1..10], 3) = 9');
check(movingAverage([1, 2], 5) === null, 'movingAverage shorter than the window is null');
check(movingAverage([], 50) === null, 'movingAverage of an empty series is null');
check(JSON.stringify(movingAverageSeries([1, 2, 3, 4, 5], 3)) === JSON.stringify([null, null, 2, 3, 4]), 'movingAverageSeries aligns the mean to each point');
const closes1y = loadChart('AAPL', '1y').points.map(p => p[1]);
const ma50 = movingAverage(closes1y, 50);
const ma200 = movingAverage(closes1y, 200);
let s50 = 0; for (let i = closes1y.length - 50; i < closes1y.length; i++) s50 += closes1y[i];
let s200 = 0; for (let i = closes1y.length - 200; i < closes1y.length; i++) s200 += closes1y[i];
check(Math.abs(ma50 - s50 / 50) < 1e-9, `AAPL 50-day avg $${ma50.toFixed(2)} matches an independent mean of the last 50 closes`);
check(Math.abs(ma200 - s200 / 200) < 1e-9, `AAPL 200-day avg $${ma200.toFixed(2)} matches an independent mean of the last 200 closes`);
check(ma50 >= Math.min(...closes1y) && ma50 <= Math.max(...closes1y), 'AAPL 50-day avg lies within the price range');
check(closes1y.length === 250, `AAPL 1y chart has 250 daily closes (got ${closes1y.length})`);
check(isDailySeries(loadChart('AAPL', '1y').points), 'AAPL 1y series is daily');
check(isDailySeries(loadChart('AAPL', '3y').points), 'AAPL 3y series is daily');
check(!isDailySeries(loadChart('AAPL', '5y').points), 'AAPL 5y series is not daily (weekly points, no day averages)');
check(!isDailySeries(loadChart('AAPL', 'max').points), 'AAPL max series is not daily (monthly points, no day averages)');
check(!isDailySeries(loadChart('AAPL', '1mo').points.slice(0, 1)), 'a single point is not a daily series');
const msftCloses = loadChart('MSFT', '1y').points.map(p => p[1]);
check(movingAverage(msftCloses, 200) !== null, 'MSFT 200-day avg computes from its 1y series too');

console.log(failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECKS FAILED`);
process.exit(failures === 0 ? 0 : 1);
