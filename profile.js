const companyProfiles = {
  VST: { name: 'Vistra Corp.', sector: 'Utilities' },
  AAPL: { name: 'Apple Inc.', sector: 'Information Technology' },
  MSFT: { name: 'Microsoft Corp.', sector: 'Information Technology' },
  NVDA: { name: 'NVIDIA Corp.', sector: 'Information Technology' },
  GOOGL: { name: 'Alphabet Inc.', sector: 'Communication Services' },
  LLY: { name: 'Eli Lilly & Co.', sector: 'Health Care' },
  JPM: { name: 'JPMorgan Chase', sector: 'Financials' },
  XOM: { name: 'Exxon Mobil Corp.', sector: 'Energy' },
};
const profileMain = document.querySelector('#profileView');
let profileSymbol = 'VST';
let profileRange = '1y';
let profileTimer = null;

function profileFor(symbol) {
  const base = companyProfiles[symbol] || { name: symbol, sector: 'US Equity' };
  return { ...base, symbol };
}
function money(value) { return value === null ? '—' : `$${Number(value).toLocaleString('en-US')}`; }
function table(id, headers, rows) { document.querySelector(`#${id}`).innerHTML = `<thead><tr>${headers.map(header => `<th>${header}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map((cell, i) => `<td class="${i && String(cell).startsWith('-') ? 'negative-text' : ''}">${cell}</td>`).join('')}</tr>`).join('')}</tbody>`; }
function emptyTable(id, headers, message) { document.querySelector(`#${id}`).innerHTML = `<thead><tr>${headers.map(header => `<th>${header}</th>`).join('')}</tr></thead><tbody><tr><td colspan="${headers.length}">${message}</td></tr></tbody>`; }
function fmtMillions(value) { return value == null ? '—' : `$${Math.round(value / 1e6).toLocaleString('en-US')}`; }
function fmtCap(value) { if (value == null) return '—'; if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`; if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`; return `$${(value / 1e6).toFixed(0)}M`; }
function fmtPct(ratio) { return ratio == null ? '—' : `${(ratio * 100).toFixed(1)}%`; }
function fmtSignedPct(ratio) { return ratio == null ? '—' : `${ratio >= 0 ? '+' : ''}${(ratio * 100).toFixed(1)}%`; }
function fmtNum(value, digits = 2) { return value == null ? '—' : Number(value).toFixed(digits); }
function fmtDollars(value) { return value == null ? '—' : `$${Number(value).toFixed(2)}`; }
function fmtDays(value) { return value == null ? '—' : Number(value).toFixed(1); }

// Shareholding (13F institutional ownership) lives in one quarterly file,
// data/shareholding.json, read directly so both the static Pages build and
// the live Vercel build use it. Insiders % is not in 13F filings and no
// free source supplies it, so insiders render as "—" and the public
// figure is the remainder, labelled as including insiders.
let shareholdingData = null;
let shareholdingLoaded = false;
async function loadShareholding(symbol) {
  const note = document.querySelector('#shareholdingNote');
  try {
    if (!shareholdingLoaded) {
      const response = await fetch('data/shareholding.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('shareholding unavailable');
      shareholdingData = await response.json();
      shareholdingLoaded = true;
    }
    const entry = shareholdingData.entries && shareholdingData.entries[symbol];
    if (!entry || entry.institutions_pct == null) {
      emptyTable('shareholdingTable', ['Holder', 'Share'], 'No institutional holdings reported for this company in the latest 13F quarter.');
      return;
    }
    if (note && shareholdingData.label) note.textContent = `Who holds the shares, from SEC Form 13F filings — ${shareholdingData.label}. ${(entry.filers || 0).toLocaleString('en-US')} managers reported ${fmtPct(entry.institutions_pct)} of shares outstanding. Insiders are not in 13F filings, so the public figure includes them.`;
    table('shareholdingTable', ['Holder', 'Share'],
      [['Institutions', fmtPct(entry.institutions_pct)],
       ['Insiders', '—'],
       ['Public (includes insiders)', fmtPct(1 - entry.institutions_pct)]]);
  } catch (error) {
    emptyTable('shareholdingTable', ['Holder', 'Share'], 'Shareholding data is still being built — check back soon.');
  }
}
// Data notes: per-company exceptions in the SEC figures, shown directly
// below the tab bar. Only renders when something is actually off, so
// clean companies get no block at all.
function renderDataNotes(data) {
  const box = document.querySelector('#dataNotes');
  const list = document.querySelector('#dataNotesList');
  if (!box || !list) return;
  const notes = [];
  const m = data.metrics || {};
  const annual = data.annual || [];
  const quarterly = data.quarterly || [];
  if (!annual.length) {
    notes.push('No 10-K annual history is available for this company, so the ten-year Profit &amp; loss, Balance sheet, Cash flow and Ratios tables are empty.');
  }
  const opMissingAnnual = annual.length && annual.every(r => r.operating_income == null);
  const opMissingQuarterly = quarterly.length && quarterly.every(q => q.operating_income == null);
  if (opMissingAnnual || opMissingQuarterly) {
    notes.push('Operating income is not reported by this company in its SEC filings. The Operating income rows, and the operating-margin and return-on-capital ratios that depend on it, show —.');
  }
  const negRev = quarterly.filter(q => q.revenue != null && q.revenue < 0);
  if (negRev.length) {
    const shown = negRev.map(q => `${q.label}: ${fmtMillions(q.revenue)}M`).join(', ');
    notes.push(`Quarterly revenue shows a negative figure (${shown}). Revenue can't be negative — the fourth quarter is calculated as the full year minus the first three quarters, and the yearly and quarterly figures can come from different restated versions of this company's filings after a spin-off, merger or divestiture.`);
  }
  if (annual.length) {
    const missing = [];
    if (annual.every(r => r.cfo == null)) missing.push('operating cash flow');
    if (annual.every(r => r.capex == null)) missing.push('capital expenditure');
    if (annual.every(r => r.fcf == null)) missing.push('free cash flow');
    if (missing.length) {
      notes.push(`Cash flow: ${missing.join(', ')} ${missing.length > 1 ? 'are' : 'is'} not reported under the labels this screener reads, so the row shows —.`);
    }
    if (negRev.length) {
      const negCfoYears = annual.filter(r => r.cfo != null && r.cfo < 0).map(r => `FY${r.fy}`);
      if (negCfoYears.length) {
        notes.push(`Operating cash flow is also negative in ${negCfoYears.join(', ')}. Those years come from the company's latest restated filings.`);
      }
    }
  }
  if (m.cap == null) {
    notes.push("Market cap is blank because the share count isn't reported in this company's filings.");
  }
  list.innerHTML = notes.map(n => `<li>${n}</li>`).join('');
  box.hidden = !notes.length;
  if (notes.length) lucide.createIcons();
}
// Half-yearly derivation: flows sum the two quarters, balances take
// the later quarter's (half-end) value. Only halves with both quarters
// reported are shown; a half with a missing quarter is skipped, never
// estimated. EPS sums the quarters.
const HALF_FLOW_FIELDS = ['revenue', 'cogs', 'operating_income', 'net_income', 'eps', 'cfo', 'capex', 'fcf', 'dividends'];
const HALF_STOCK_FIELDS = ['cash', 'assets', 'debt', 'equity', 'curr_assets', 'curr_liab', 'receivables', 'inventory'];
function halfYearly(quarterly) {
  const byFy = {};
  for (const q of quarterly || []) {
    const m = /^Q([1-4]) FY(\d{4})$/.exec(q.label || '');
    if (!m) continue;
    (byFy[m[2]] = byFy[m[2]] || {})[Number(m[1])] = q;
  }
  const halves = [];
  for (const fy of Object.keys(byFy).sort()) {
    for (const [half, qs] of [['H1', [1, 2]], ['H2', [3, 4]]]) {
      const a = byFy[fy][qs[0]];
      const b = byFy[fy][qs[1]];
      if (!a || !b) continue;
      const sum = field => (a[field] != null && b[field] != null) ? a[field] + b[field] : null;
      const entry = { label: `${half} FY${fy}` };
      for (const field of HALF_FLOW_FIELDS) entry[field] = sum(field);
      for (const field of HALF_STOCK_FIELDS) entry[field] = b[field] != null ? b[field] : null;
      halves.push(entry);
    }
  }
  return halves;
}
function halfYearlyRatios(halves) {
  // Ratios for half-year periods, recomputed from the half-yearly
  // flows and half-end balances. Returns and turnover use trailing
  // flows (the current half plus the immediately preceding half);
  // a half whose preceding half is missing — a skipped half-year in
  // the quarters — gets no trailing figure, never an estimate.
  const byKey = {};
  for (const h of halves) {
    const m = /^H([12]) FY(\d{4})$/.exec(h.label || '');
    if (m) byKey[`${m[2]}-H${m[1]}`] = h;
  }
  const prevHalf = h => {
    const m = /^H([12]) FY(\d{4})$/.exec(h.label || '');
    if (!m) return null;
    return m[1] === '1' ? byKey[`${Number(m[2]) - 1}-H2`] || null : byKey[`${m[2]}-H1`] || null;
  };
  const trailing = (h, field) => {
    const p = prevHalf(h);
    if (!p || h[field] == null || p[field] == null) return null;
    return h[field] + p[field];
  };
  return halves.map(h => {
    const ttmRev = trailing(h, 'revenue');
    const ttmNi = trailing(h, 'net_income');
    const ttmEbit = trailing(h, 'operating_income');
    const ttmCogs = trailing(h, 'cogs');
    return {
      label: h.label,
      opm: (h.operating_income != null && h.revenue) ? h.operating_income / h.revenue : null,
      net_margin: (h.net_income != null && h.revenue) ? h.net_income / h.revenue : null,
      roe: (ttmNi != null && h.equity) ? ttmNi / h.equity : null,
      roce: (ttmEbit != null && h.equity && h.debt != null) ? ttmEbit / (h.equity + h.debt) : null,
      debt_equity: (h.debt != null && h.equity) ? h.debt / h.equity : null,
      current_ratio: (h.curr_assets && h.curr_liab) ? h.curr_assets / h.curr_liab : null,
      asset_turnover: (ttmRev != null && h.assets) ? ttmRev / h.assets : null,
      debtor_days: (h.receivables != null && ttmRev) ? h.receivables / ttmRev * 365 : null,
      inventory_days: (h.inventory != null && ttmCogs) ? h.inventory / ttmCogs * 365 : null,
    };
  });
}
let profitData = null;
function profitRowsFor(period) {
  const { annual, quarterly } = profitData || { annual: [], quarterly: [] };
  if (period === 'quarter') {
    if (!quarterly.length) return null;
    return { headers: ['Metric', ...quarterly.map(q => q.label)], rows: [
      ['Revenue', ...quarterly.map(q => fmtMillions(q.revenue))],
      ['Operating income', ...quarterly.map(q => fmtMillions(q.operating_income))],
      ['Net income', ...quarterly.map(q => fmtMillions(q.net_income))],
      ['EPS diluted', ...quarterly.map(q => fmtDollars(q.eps))],
      ['Operating margin', ...quarterly.map(q => (q.operating_income != null && q.revenue) ? fmtPct(q.operating_income / q.revenue) : '—')]] };
  }
  if (period === 'half') {
    const halves = halfYearly(quarterly);
    if (!halves.length) return null;
    return { headers: ['Metric', ...halves.map(h => h.label)], rows: [
      ['Revenue', ...halves.map(h => fmtMillions(h.revenue))],
      ['Operating income', ...halves.map(h => fmtMillions(h.operating_income))],
      ['Net income', ...halves.map(h => fmtMillions(h.net_income))],
      ['EPS diluted', ...halves.map(h => fmtDollars(h.eps))],
      ['Operating margin', ...halves.map(h => (h.operating_income != null && h.revenue) ? fmtPct(h.operating_income / h.revenue) : '—')]] };
  }
  if (!annual.length) return null;
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`)], rows: [
    ['Revenue', ...annual.map(r => fmtMillions(r.revenue))],
    ...(annual.some(r => r.cogs != null) ? [['Cost of revenue', ...annual.map(r => fmtMillions(r.cogs))]] : []),
    ['Operating income', ...annual.map(r => fmtMillions(r.operating_income))],
    ['Net income', ...annual.map(r => fmtMillions(r.net_income))],
    ['EPS diluted', ...annual.map(r => fmtDollars(r.eps))],
    ...(annual.some(r => r.advertising != null) ? [['Advertising expense', ...annual.map(r => fmtMillions(r.advertising))]] : []),
  ]};
}
function renderProfit(period) {
  const copy = {
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions.'],
    half: ['HALF-YEARLY', 'Half-year totals derived from reported quarters, in USD millions. Only halves with both quarters reported are shown.'],
    quarter: ['LAST 12 QUARTERS', 'Quarter-by-quarter operating performance, in USD millions.'],
  }[period];
  const eyebrow = document.querySelector('#profitEyebrow');
  const subtitle = document.querySelector('#profitSubtitle');
  if (eyebrow) eyebrow.textContent = copy[0];
  if (subtitle) subtitle.textContent = copy[1];
  const built = profitRowsFor(period);
  if (built) table('profitTable', built.headers, built.rows);
  else emptyTable('profitTable', ['Metric'], period === 'yearly' ? 'No 10-K annuals filed yet for this company, so the ten-year history is not available.' : 'No complete periods reported for this company yet.');
  document.querySelectorAll('#profitPeriodSwitch button').forEach(btn => btn.classList.toggle('selected', btn.dataset.period === period));
}
let periodData = null;
function balanceRowsFor(period) {
  const { annual, quarterly } = periodData || { annual: [], quarterly: [] };
  const rows = list => [
    ['Cash & equivalents', ...list.map(r => fmtMillions(r.cash))],
    ['Total assets', ...list.map(r => fmtMillions(r.assets))],
    ['Total debt', ...list.map(r => fmtMillions(r.debt))],
    ['Shareholders equity', ...list.map(r => fmtMillions(r.equity))],
  ];
  if (period === 'quarter') {
    if (!quarterly.length) return null;
    return { headers: ['Metric', ...quarterly.map(q => q.label)], rows: rows(quarterly) };
  }
  if (period === 'half') {
    const halves = halfYearly(quarterly);
    if (!halves.length) return null;
    return { headers: ['Metric', ...halves.map(h => h.label)], rows: rows(halves) };
  }
  if (!annual.length) return null;
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`)], rows: rows(annual) };
}
function cashflowRowsFor(period) {
  const { annual, quarterly } = periodData || { annual: [], quarterly: [] };
  const rows = list => [
    ['Cash from operations', ...list.map(r => fmtMillions(r.cfo))],
    ['Capital expenditure', ...list.map(r => fmtMillions(r.capex))],
    ['Free cash flow', ...list.map(r => fmtMillions(r.fcf))],
    ['Dividends paid', ...list.map(r => fmtMillions(r.dividends))],
  ];
  if (period === 'quarter') {
    if (!quarterly.length) return null;
    return { headers: ['Metric', ...quarterly.map(q => q.label)], rows: rows(quarterly) };
  }
  if (period === 'half') {
    const halves = halfYearly(quarterly);
    if (!halves.length) return null;
    return { headers: ['Metric', ...halves.map(h => h.label)], rows: rows(halves) };
  }
  if (!annual.length) return null;
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`)], rows: rows(annual) };
}
function ratiosRowsFor(period) {
  const { annual, quarterly, ratios, quarterly_ratios } = periodData || { annual: [], quarterly: [], ratios: [], quarterly_ratios: [] };
  const rows = list => [
    ['Return on equity', ...list.map(r => fmtPct(r.roe))],
    ['Return on capital employed', ...list.map(r => fmtPct(r.roce))],
    ['Operating margin', ...list.map(r => fmtPct(r.opm))],
    ['Net margin', ...list.map(r => fmtPct(r.net_margin))],
    ['Debt / equity', ...list.map(r => fmtNum(r.debt_equity))],
    ['Current ratio', ...list.map(r => fmtNum(r.current_ratio))],
    ['Asset turnover', ...list.map(r => fmtNum(r.asset_turnover))],
    ['Debtor days', ...list.map(r => fmtDays(r.debtor_days))],
    ['Inventory days', ...list.map(r => fmtDays(r.inventory_days))],
  ];
  if (period === 'quarter') {
    if (!quarterly_ratios.length) return null;
    return { headers: ['Ratio', ...quarterly_ratios.map(r => r.label)], rows: rows(quarterly_ratios) };
  }
  if (period === 'half') {
    const halves = halfYearlyRatios(halfYearly(quarterly));
    if (!halves.length) return null;
    return { headers: ['Ratio', ...halves.map(h => h.label)], rows: rows(halves) };
  }
  if (!annual.length) return null;
  const built = rows(ratios);
  // Advertising expense only shows for filers that break it out in
  // their 10-K; the rest get no row, never a made-up number. Quarterly
  // advertising is not reported, so the row is yearly only.
  if (ratios.some(r => r.ad_pct != null)) built.push(['Ad spend / revenue', ...ratios.map(r => fmtPct(r.ad_pct))]);
  return { headers: ['Ratio', ...annual.map(r => `FY${r.fy}`)], rows: built };
}
function renderPeriodSection(period, tableId, switchId, eyebrowId, subtitleId, copy, rowsFor) {
  const [eyebrow, subtitle] = copy[period];
  const eyebrowEl = document.querySelector(`#${eyebrowId}`);
  const subtitleEl = document.querySelector(`#${subtitleId}`);
  if (eyebrowEl) eyebrowEl.textContent = eyebrow;
  if (subtitleEl) subtitleEl.textContent = subtitle;
  const built = rowsFor(period);
  if (built) table(tableId, built.headers, built.rows);
  else emptyTable(tableId, [tableId === 'ratiosTable' ? 'Ratio' : 'Metric'], period === 'yearly' ? 'No 10-K annuals filed yet for this company, so the ten-year history is not available.' : 'No complete periods reported for this company yet.');
  document.querySelectorAll(`#${switchId} button`).forEach(btn => btn.classList.toggle('selected', btn.dataset.period === period));
}
function renderBalance(period) {
  renderPeriodSection(period, 'balanceTable', 'balancePeriodSwitch', 'balanceEyebrow', 'balanceSubtitle', {
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions.'],
    half: ['HALF-YEARLY', 'Half-end balances from reported quarters, in USD millions. Only halves with both quarters reported are shown.'],
    quarter: ['LAST 12 QUARTERS', 'Quarter-end balances, in USD millions.'],
  }, balanceRowsFor);
}
function renderCashflow(period) {
  renderPeriodSection(period, 'cashflowTable', 'cashflowPeriodSwitch', 'cashflowEyebrow', 'cashflowSubtitle', {
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions.'],
    half: ['HALF-YEARLY', 'Half-year totals derived from reported quarters, in USD millions. Only halves with both quarters reported are shown.'],
    quarter: ['LAST 12 QUARTERS', 'Quarter-by-quarter cash flow, in USD millions.'],
  }, cashflowRowsFor);
}
function renderRatios(period) {
  renderPeriodSection(period, 'ratiosTable', 'ratiosPeriodSwitch', 'ratiosEyebrow', 'ratiosSubtitle', {
    yearly: ['ANNUAL HISTORY', 'Efficiency, leverage, and returns across the last ten years.'],
    half: ['HALF-YEARLY', 'Half-year ratios from half-yearly flows and half-end balances. Returns and turnover use trailing flows (the current half plus the preceding half).'],
    quarter: ['LAST 12 QUARTERS', 'Quarterly ratios. Returns and turnover use trailing-twelve-month flows over the quarter-end balance.'],
  }, ratiosRowsFor);
}
function renderFinancials(data) {
  const m = data.metrics || {};
  const annual = data.annual || [];
  const quarterly = data.quarterly || [];
  const ratios = data.ratios || [];
  const peers = data.peers || [];
  renderDataNotes(data);

  table('comparisonTable', ['Company', 'Market cap', 'P/E', 'ROE', 'Revenue growth', 'Debt / equity'],
    [[data.name || data.symbol, fmtCap(m.cap), fmtNum(m.pe, 1), fmtPct(m.roe), fmtSignedPct(m.growth), fmtNum(m.debt_equity)],
     ...peers.map(p => [p.name || p.symbol, fmtCap(p.cap), fmtNum(p.pe, 1), fmtPct(p.roe), fmtSignedPct(p.growth), fmtNum(p.debt_equity)])]);

  if (quarterly.length) {
    const labels = quarterly.map(q => q.label);
    table('quarterlyTable', ['Metric', ...labels],
      [['Revenue', ...quarterly.map(q => fmtMillions(q.revenue))],
       ['Operating income', ...quarterly.map(q => fmtMillions(q.operating_income))],
       ['Net income', ...quarterly.map(q => fmtMillions(q.net_income))],
       ['EPS diluted', ...quarterly.map(q => fmtDollars(q.eps))],
       ['Operating margin', ...quarterly.map(q => (q.operating_income != null && q.revenue) ? fmtPct(q.operating_income / q.revenue) : '—')]]);
  } else {
    emptyTable('quarterlyTable', ['Metric'], 'No quarterly filings reported for this company yet.');
  }

  profitData = { annual, quarterly };
  renderProfit('yearly');
  periodData = { annual, quarterly, ratios, quarterly_ratios: data.quarterly_ratios || [] };
  renderBalance('yearly');
  renderCashflow('yearly');
  renderRatios('yearly');
  loadShareholding(data.symbol);
}

function renderSnapshot(profile, data) {
  // Pros & cons are computed from the filing data (see lib/edgar.py
  // pros_cons) — nothing here is editorial. Before the data loads, or when
  // the filings support no statement either way, say so plainly.
  const pros = data ? (data.pros || []) : null;
  const cons = data ? (data.cons || []) : null;
  document.querySelector('#prosList').innerHTML = pros === null
    ? '<li>Loading strengths from the company filings…</li>'
    : (pros.length ? pros.map(item => `<li>${item}</li>`).join('') : '<li>No strengths stand out from the filings.</li>');
  document.querySelector('#consList').innerHTML = cons === null
    ? '<li>Loading watchouts from the company filings…</li>'
    : (cons.length ? cons.map(item => `<li>${item}</li>`).join('') : '<li>No watchouts stand out from the filings.</li>');
  const m = data ? (data.metrics || {}) : {};
  const annual = data ? (data.annual || []) : [];
  const latest = annual.length ? annual[annual.length - 1] : null;
  document.querySelector('#keyMetrics').innerHTML = [['Market cap', fmtCap(m.cap)], ['P/E ratio', fmtNum(m.pe, 1)], ['ROE', fmtPct(m.roe)], ['Debt / equity', fmtNum(m.debt_equity)], ['EPS (TTM)', fmtDollars(m.eps_ttm)], ['52W range', '<span id="metric52w">—</span>']].map(([name, value]) => `<div><span>${name}</span><strong>${value}</strong></div>`).join('');
  const growthCard = m.growth == null
    ? ['Revenue trend', 'Trailing revenue growth is not available from the company filings.', 'trending-up']
    : ['Revenue trend', m.growth >= 0 ? `Revenue grew ${fmtPct(m.growth)} over the last twelve months.` : `Revenue was down ${fmtPct(Math.abs(m.growth))} over the last twelve months.`, 'trending-up'];
  const returnsCard = m.roe == null
    ? ['Returns', 'Return on equity is not available from the company filings.', 'landmark']
    : ['Returns', `Return on equity is ${fmtPct(m.roe)} on trailing earnings${m.roce != null ? `, with return on capital employed at ${fmtPct(m.roce)}` : ''}.`, 'landmark'];
  const cashCard = latest && latest.fcf != null
    ? ['Capital returns', `Free cash flow was ${fmtMillions(latest.fcf)} in FY${latest.fy}.`, 'shield-alert']
    : ['Capital returns', 'Free cash flow is not reported in the company filings.', 'shield-alert'];
  document.querySelector('#insightsGrid').innerHTML = [growthCard, returnsCard, cashCard].map(([title, text, icon]) => `<article class="insight-card"><i data-lucide="${icon}"></i><h3>${title}</h3><p>${text}</p></article>`).join('');
  lucide.createIcons();
}
function renderFinancialsUnavailable(message) {
  profitData = null;
  periodData = null;
  const notesBox = document.querySelector('#dataNotes');
  if (notesBox) { notesBox.hidden = true; const notesList = document.querySelector('#dataNotesList'); if (notesList) notesList.innerHTML = ''; }
  ['comparisonTable', 'quarterlyTable', 'profitTable', 'balanceTable', 'cashflowTable', 'ratiosTable', 'shareholdingTable'].forEach(id => {
    const el = document.querySelector(`#${id}`);
    if (el) el.innerHTML = `<tbody><tr><td>${message}</td></tr></tbody>`;
  });
}
async function loadChart(range) {
  const loading = document.querySelector('#chartLoading'); const svg = document.querySelector('#priceChart');
  loading.hidden = false; loading.textContent = 'Loading price history...';
  try {
    const data = await NorthstarAPI.chart(profileSymbol, range);
    const { points } = data;
    const cell = document.querySelector('#metric52w');
    if (cell && data.fiftyTwoWeekHigh != null && data.fiftyTwoWeekLow != null) {
      cell.textContent = `$${Number(data.fiftyTwoWeekLow).toLocaleString('en-US', { maximumFractionDigits: 2 })} – $${Number(data.fiftyTwoWeekHigh).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
    }
    const values = points.map(point => Array.isArray(point) ? point[1] : point.close); const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(max - min, 1);
    const coords = values.map((value, index) => `${(index / Math.max(values.length - 1, 1) * 1000).toFixed(2)},${(282 - ((value - min) / span * 242)).toFixed(2)}`);
    svg.innerHTML = `<path class="area" d="M0,300 L${coords.join(' L')} L1000,300 Z"></path><path class="line" d="M${coords.join(' L')}"></path>`;
    loading.hidden = true;
  } catch (error) {
    loading.textContent = 'Price history unavailable right now.';
  }
}
async function refreshProfileQuote() {
  try {
    const quote = (await NorthstarAPI.quotes([profileSymbol])).quotes[0];
    if (!quote) return;
    profilePrice.textContent = `$${Number(quote.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    profileChange.textContent = `${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%`;
    profileChange.className = quote.changePercent < 0 ? 'negative' : 'positive';
    document.querySelector('#profileUpdated').textContent = `Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  } catch (error) {
    /* keep the last price when the quote feed is down */
  }
}
function startProfileRefresh() {
  if (profileTimer) clearInterval(profileTimer);
  // Refresh the price every minute while a profile is open, and the chart
  // too in live mode. In static mode the chart is a snapshot rebuilt by
  // the hourly/daily workflow, so re-fetching it would only return the
  // same file — the quote still refreshes from the rebuilt data.
  profileTimer = setInterval(() => {
    refreshProfileQuote();
    if (!NorthstarAPI.staticMode) loadChart(profileRange);
  }, 60000);
}
function stopProfileRefresh() {
  if (profileTimer) { clearInterval(profileTimer); profileTimer = null; }
}
window.openProfile = async function(symbol) {
  profileSymbol = symbol; const profile = profileFor(symbol); const stock = stocks.find(item => item.ticker === symbol);
  document.querySelector('#screenerMain').hidden = true; document.querySelector('#detailDrawer').classList.remove('open'); document.querySelector('#scrim').classList.remove('open'); profileMain.hidden = false;
  profileInitial.textContent = symbol[0]; profileName.textContent = profile.name; profileTicker.textContent = `${symbol} · ${profile.sector}`; chartTitle.textContent = `${symbol} share price`;
  if (stock) { profilePrice.textContent = stock.price; profileChange.textContent = stock.change; profileChange.className = stock.change.startsWith('-') ? 'negative' : 'positive'; }
  renderFinancialsUnavailable('Loading filings…');
  renderSnapshot(profile, null);
  profileRange = '1y';
  document.querySelectorAll('#rangeSwitch button').forEach(button => button.classList.toggle('selected', button.dataset.range === '1y'));
  loadChart('1y');
  startProfileRefresh();
  try {
    const data = await NorthstarAPI.financials(symbol);
    profileName.textContent = data.name || profile.name;
    if (data.sector) profileTicker.textContent = `${symbol} · ${data.sector}`;
    profilePrice.textContent = `$${Number(data.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    const change = data.changePercent;
    profileChange.textContent = `${change >= 0 ? '+' : ''}${change.toFixed(2)}%`;
    profileChange.className = change < 0 ? 'negative' : 'positive';
    document.querySelector('#profileUpdated').textContent = `Updated ${new Date(data.asOf * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} · ${data.source}`;
    renderFinancials(data);
    renderSnapshot(profile, data);
  } catch (error) {
    if (error.status === 404) {
      renderFinancialsUnavailable('No SEC filings found for this ticker. Financial statements are only available for US-listed companies that file with the SEC.');
    } else {
      renderFinancialsUnavailable('Financials temporarily unavailable. Try again shortly.');
    }
  }
  window.scrollTo(0, 0);
};
document.querySelector('#backToScreener').addEventListener('click', () => { stopProfileRefresh(); profileMain.hidden = true; document.querySelector('#screenerMain').hidden = false; });
document.querySelector('#rangeSwitch').addEventListener('click', event => { const button = event.target.closest('[data-range]'); if (!button) return; profileRange = button.dataset.range; document.querySelectorAll('#rangeSwitch button').forEach(item => item.classList.toggle('selected', item === button)); loadChart(button.dataset.range); });
document.querySelector('#profitPeriodSwitch').addEventListener('click', event => { const button = event.target.closest('[data-period]'); if (!button || !profitData) return; renderProfit(button.dataset.period); });
document.querySelector('#balancePeriodSwitch').addEventListener('click', event => { const button = event.target.closest('[data-period]'); if (!button || !periodData) return; renderBalance(button.dataset.period); });
document.querySelector('#cashflowPeriodSwitch').addEventListener('click', event => { const button = event.target.closest('[data-period]'); if (!button || !periodData) return; renderCashflow(button.dataset.period); });
document.querySelector('#ratiosPeriodSwitch').addEventListener('click', event => { const button = event.target.closest('[data-period]'); if (!button || !periodData) return; renderRatios(button.dataset.period); });
