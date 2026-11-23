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
// data/shareholding.json, and the top holders in data/top-holders.json,
// both read directly so the static Pages build and the live Vercel build
// use them. Institutions come from SEC Form 13F filings; insiders from
// each holder's most recent Form 4; public is the aggregate remainder —
// no named public holders exist in any filing.
function fmtShares(value) {
  if (value == null) return '—';
  if (value >= 1e6) return `${Math.round(value / 1e6).toLocaleString('en-US')}M`;
  return Number(value).toLocaleString('en-US');
}
function shareholdingSummaryRows(instPct, insidersPct) {
  if (insidersPct == null) return [['Institutions', fmtPct(instPct)], ['Insiders', '—'], ['Public (includes insiders)', fmtPct(1 - instPct)]];
  return [['Institutions', fmtPct(instPct)], ['Insiders', fmtPct(insidersPct)], ['Public (aggregate)', fmtPct(1 - instPct - insidersPct)]];
}
function topInstitutionRows(top) {
  return (top || []).map((holder, i) => [i + 1, holder.name || '—', fmtShares(holder.shares), fmtPct(holder.pct)]);
}
function topInsiderRows(top) {
  return (top || []).map((holder, i) => [i + 1, holder.name || '—', fmtShares(holder.shares), fmtPct(holder.pct), holder.filing_date || '—']);
}
let shareholdingData = null;
let shareholdingLoaded = false;
let topHoldersData = null;
let topHoldersLoaded = false;
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
      emptyTable('topInstitutionsTable', ['#', 'Manager', 'Shares', '%'], 'No institutional holders reported for this company in the latest 13F quarter.');
      emptyTable('topInsidersTable', ['#', 'Insider', 'Shares', '%', 'Latest Form 4'], 'No Form 4 insider holdings reported for this company.');
      return;
    }
    // Top holders are best-effort: an older deploy may not have the file yet.
    let topEntry = null;
    try {
      if (!topHoldersLoaded) {
        const topResponse = await fetch('data/top-holders.json', { cache: 'no-store' });
        if (!topResponse.ok) throw new Error('top holders unavailable');
        topHoldersData = await topResponse.json();
        topHoldersLoaded = true;
      }
      topEntry = topHoldersData.entries && topHoldersData.entries[symbol];
    } catch (error) {
      topEntry = null;
    }
    const insiders = topEntry && topEntry.insiders;
    const insidersPct = insiders && insiders.total_pct;
    if (note && shareholdingData.label) {
      let text = topEntry
        ? `Who holds the shares — institutions from SEC Form 13F filings, ${shareholdingData.label}, and insiders from each holder's most recent Form 4. ${(entry.filers || 0).toLocaleString('en-US')} managers reported ${fmtPct(entry.institutions_pct)} of shares outstanding. A shared-discretion block counts once, attributed to the manager who reported the largest amount; large investment complexes file through several separate entities, so one complex can appear on several rows. Public is the aggregate remainder — no named public holders exist in any filing.`
        : `Who holds the shares, from SEC Form 13F filings — ${shareholdingData.label}. ${(entry.filers || 0).toLocaleString('en-US')} managers reported ${fmtPct(entry.institutions_pct)} of shares outstanding. Insiders are not in 13F filings, so the public figure includes them.`;
      if (topEntry && insiders && insiders.overlap) text += ` ${insiders.overlap_note || 'Insider holdings overlap across related holders, so no insider total is shown for this company.'}`;
      note.textContent = text;
    }
    table('shareholdingTable', ['Holder', 'Share'], shareholdingSummaryRows(entry.institutions_pct, insidersPct));
    const instTop = topEntry && topEntry.institutions && topEntry.institutions.top;
    if (instTop && instTop.length) table('topInstitutionsTable', ['#', 'Manager', 'Shares', '%'], topInstitutionRows(instTop));
    else emptyTable('topInstitutionsTable', ['#', 'Manager', 'Shares', '%'], topHoldersData ? 'No institutional holders reported for this company in the latest 13F quarter.' : 'Top holder data is still being built — check back soon.');
    const insiderTop = insiders && insiders.top;
    if (insiderTop && insiderTop.length) table('topInsidersTable', ['#', 'Insider', 'Shares', '%', 'Latest Form 4'], topInsiderRows(insiderTop));
    else emptyTable('topInsidersTable', ['#', 'Insider', 'Shares', '%', 'Latest Form 4'], topHoldersData ? 'No Form 4 insider holdings reported for this company.' : 'Top holder data is still being built — check back soon.');
  } catch (error) {
    emptyTable('shareholdingTable', ['Holder', 'Share'], 'Shareholding data is still being built — check back soon.');
    emptyTable('topInstitutionsTable', ['#', 'Manager', 'Shares', '%'], 'Shareholding data is still being built — check back soon.');
    emptyTable('topInsidersTable', ['#', 'Insider', 'Shares', '%', 'Latest Form 4'], 'Shareholding data is still being built — check back soon.');
  }
}
// SEC Documents: filing indexes on EDGAR, built from the company's CIK
// (data/cik-map.json, built from the SEC company_tickers list). The
// 10-digit zero-padded CIK is what the classic browse-edgar URLs take;
// the modern browse page takes the plain number.
let cikMapData = null;
let cikMapLoaded = false;
function edgarLinks(cik) {
  const padded = String(cik).padStart(10, '0');
  const base = 'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany';
  return [
    ['10-K filings', `${base}&CIK=${padded}&type=10-K&dateb=&owner=include&count=10`],
    ['10-Q filings', `${base}&CIK=${padded}&type=10-Q&dateb=&owner=include&count=10`],
    ['All filings', `https://www.sec.gov/edgar/browse/?CIK=${cik}`],
  ];
}
async function loadDocuments(symbol) {
  try {
    if (!cikMapLoaded) {
      const response = await fetch('data/cik-map.json', { cache: 'no-store' });
      if (!response.ok) throw new Error('CIK map unavailable');
      cikMapData = await response.json();
      cikMapLoaded = true;
    }
    const entry = cikMapData && cikMapData[symbol];
    if (!entry || !entry.cik) {
      emptyTable('documentsTable', ['Document', 'EDGAR'], 'No SEC filing index is available for this ticker.');
      return;
    }
    table('documentsTable', ['Document', 'EDGAR'],
      edgarLinks(entry.cik).map(([label, url]) => [label, `<a href="${url}" target="_blank" rel="noopener">View on EDGAR</a>`]));
  } catch (error) {
    emptyTable('documentsTable', ['Document', 'EDGAR'], 'SEC filing links are unavailable right now.');
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
const HALF_FLOW_FIELDS = ['revenue', 'cogs', 'expenses', 'operating_income', 'other_income', 'interest', 'depreciation', 'pbt', 'tax', 'net_income', 'eps', 'cfo', 'capex', 'fcf', 'dividends'];
const HALF_STOCK_FIELDS = ['cash', 'assets', 'debt', 'equity', 'curr_assets', 'curr_liab', 'receivables', 'inventory', 'payables'];
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
    // Day-count ratios use the same trailing basis as the returns above.
    const debtor_d = (h.receivables != null && ttmRev) ? h.receivables / ttmRev * 365 : null;
    const inventory_d = (h.inventory != null && ttmCogs) ? h.inventory / ttmCogs * 365 : null;
    const payable_d = (h.payables != null && ttmCogs) ? h.payables / ttmCogs * 365 : null;
    return {
      label: h.label,
      opm: (h.operating_income != null && h.revenue) ? h.operating_income / h.revenue : null,
      net_margin: (h.net_income != null && h.revenue) ? h.net_income / h.revenue : null,
      roe: (ttmNi != null && h.equity) ? ttmNi / h.equity : null,
      roce: (ttmEbit != null && h.equity && h.debt != null) ? ttmEbit / (h.equity + h.debt) : null,
      debt_equity: (h.debt != null && h.equity) ? h.debt / h.equity : null,
      current_ratio: (h.curr_assets && h.curr_liab) ? h.curr_assets / h.curr_liab : null,
      asset_turnover: (ttmRev != null && h.assets) ? ttmRev / h.assets : null,
      debtor_days: debtor_d,
      inventory_days: inventory_d,
      payable_days: payable_d,
      working_capital_days: (h.curr_assets != null && h.curr_liab != null && ttmRev) ? (h.curr_assets - h.curr_liab) / ttmRev * 365 : null,
      ccc: (debtor_d != null && inventory_d != null && payable_d != null) ? debtor_d + inventory_d - payable_d : null,
    };
  });
}
let profitData = null;
// Trailing twelve months from the last four reported quarters. A figure
// is null unless all four quarters report it — never estimated from
// fewer quarters.
function ttmFor(quarterly) {
  const last4 = (quarterly || []).slice(-4);
  if (last4.length < 4) return null;
  const sum = field => last4.every(q => q[field] != null) ? last4.reduce((a, q) => a + q[field], 0) : null;
  return { revenue: sum('revenue'), cogs: sum('cogs'), expenses: sum('expenses'), operating_income: sum('operating_income'), other_income: sum('other_income'), interest: sum('interest'), depreciation: sum('depreciation'), pbt: sum('pbt'), tax: sum('tax'), net_income: sum('net_income'), eps: sum('eps') };
}
// Latest quarter vs the same quarter a year ago (YoY) and vs the prior
// quarter (QoQ), from reported figures only. A growth figure is null
// when either side is missing or the base is zero.
function growthFor(quarterly) {
  const qs = quarterly || [];
  if (!qs.length) return null;
  const latest = qs[qs.length - 1];
  const prev = qs.length > 1 ? qs[qs.length - 2] : null;
  const m = /^Q([1-4]) FY(\d{4})$/.exec(latest.label || '');
  const yearAgo = m ? qs.find(q => q.label === `Q${m[1]} FY${Number(m[2]) - 1}`) : null;
  const growth = (cur, base) => (cur != null && base != null && base !== 0) ? (cur - base) / base : null;
  const one = field => ({
    yoy: yearAgo ? growth(latest[field], yearAgo[field]) : null,
    qoq: prev ? growth(latest[field], prev[field]) : null,
    yoyLabel: yearAgo ? `${latest.label} vs ${yearAgo.label}` : null,
    qoqLabel: prev ? `${latest.label} vs ${prev.label}` : null,
  });
  return { latest: latest.label, revenue: one('revenue'), net_income: one('net_income'), eps: one('eps') };
}
function profitRowsFor(period) {
  const { annual, quarterly } = profitData || { annual: [], quarterly: [] };
  // A fuller P&L row only appears when at least one period reports
  // the figure — companies that never report it get no empty row.
  // Tax % is the reported income-tax expense over profit before tax.
  const has = (list, field) => list.some(r => r[field] != null);
  const taxRow = list => ['Tax %', ...list.map(r => (r.tax != null && r.pbt) ? fmtPct(r.tax / r.pbt) : '—')];
  const fullerRows = list => [
    ...(has(list, 'expenses') ? [['Expenses', ...list.map(r => fmtMillions(r.expenses))]] : []),
    ['Operating income', ...list.map(r => fmtMillions(r.operating_income))],
    ...(has(list, 'other_income') ? [['Other income', ...list.map(r => fmtMillions(r.other_income))]] : []),
    ...(has(list, 'interest') ? [['Interest', ...list.map(r => fmtMillions(r.interest))]] : []),
    ...(has(list, 'depreciation') ? [['Depreciation', ...list.map(r => fmtMillions(r.depreciation))]] : []),
    ...(has(list, 'pbt') ? [['Profit before tax', ...list.map(r => fmtMillions(r.pbt))]] : []),
    ...(has(list, 'tax') ? [taxRow(list)] : []),
  ];
  if (period === 'quarter') {
    if (!quarterly.length) return null;
    return { headers: ['Metric', ...quarterly.map(q => q.label)], rows: [
      ['Revenue', ...quarterly.map(q => fmtMillions(q.revenue))],
      ...fullerRows(quarterly),
      ['Net income', ...quarterly.map(q => fmtMillions(q.net_income))],
      ['EPS diluted', ...quarterly.map(q => fmtDollars(q.eps))],
      ['Operating margin', ...quarterly.map(q => (q.operating_income != null && q.revenue) ? fmtPct(q.operating_income / q.revenue) : '—')]] };
  }
  if (period === 'half') {
    const halves = halfYearly(quarterly);
    if (!halves.length) return null;
    return { headers: ['Metric', ...halves.map(h => h.label)], rows: [
      ['Revenue', ...halves.map(h => fmtMillions(h.revenue))],
      ...fullerRows(halves),
      ['Net income', ...halves.map(h => fmtMillions(h.net_income))],
      ['EPS diluted', ...halves.map(h => fmtDollars(h.eps))],
      ['Operating margin', ...halves.map(h => (h.operating_income != null && h.revenue) ? fmtPct(h.operating_income / h.revenue) : '—')]] };
  }
  if (!annual.length) return null;
  // The TTM column sits alongside the annual columns: the sum of the
  // last four reported quarters. Quarterly advertising is not reported,
  // so that cell is always blank.
  const ttm = ttmFor(quarterly);
  const ttmVal = field => (ttm ? ttm[field] : null);
  const hasTtm = field => has(annual, field) || ttmVal(field) != null;
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`), 'TTM'], rows: [
    ['Revenue', ...annual.map(r => fmtMillions(r.revenue)), fmtMillions(ttmVal('revenue'))],
    ...(hasTtm('cogs') ? [['Cost of revenue', ...annual.map(r => fmtMillions(r.cogs)), fmtMillions(ttmVal('cogs'))]] : []),
    ...(hasTtm('expenses') ? [['Expenses', ...annual.map(r => fmtMillions(r.expenses)), fmtMillions(ttmVal('expenses'))]] : []),
    ['Operating income', ...annual.map(r => fmtMillions(r.operating_income)), fmtMillions(ttmVal('operating_income'))],
    ...(hasTtm('other_income') ? [['Other income', ...annual.map(r => fmtMillions(r.other_income)), fmtMillions(ttmVal('other_income'))]] : []),
    ...(hasTtm('interest') ? [['Interest', ...annual.map(r => fmtMillions(r.interest)), fmtMillions(ttmVal('interest'))]] : []),
    ...(hasTtm('depreciation') ? [['Depreciation', ...annual.map(r => fmtMillions(r.depreciation)), fmtMillions(ttmVal('depreciation'))]] : []),
    ...(hasTtm('pbt') ? [['Profit before tax', ...annual.map(r => fmtMillions(r.pbt)), fmtMillions(ttmVal('pbt'))]] : []),
    ...(hasTtm('tax') ? [['Tax %', ...annual.map(r => (r.tax != null && r.pbt) ? fmtPct(r.tax / r.pbt) : '—'), (ttmVal('tax') != null && ttmVal('pbt')) ? fmtPct(ttmVal('tax') / ttmVal('pbt')) : '—']] : []),
    ['Net income', ...annual.map(r => fmtMillions(r.net_income)), fmtMillions(ttmVal('net_income'))],
    ['EPS diluted', ...annual.map(r => fmtDollars(r.eps)), fmtDollars(ttmVal('eps'))],
    ...(annual.some(r => r.advertising != null) ? [['Advertising expense', ...annual.map(r => fmtMillions(r.advertising)), '—']] : []),
  ]};
}
function renderProfit(period) {
  const copy = {
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions. TTM is the sum of the last four reported quarters.'],
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
    ['Accounts payable', ...list.map(r => fmtMillions(r.payables))],
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
  // The Latest Q column sits alongside the annual columns: the most
  // recent reported quarter's balances. For a Q4 latest quarter it
  // matches the last annual column — both are the year-end balance.
  const latest = quarterly[quarterly.length - 1];
  if (!latest) return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`)], rows: rows(annual) };
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`), latest.label], rows: rows([...annual, latest]) };
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
  // The Latest Q column sits alongside the annual columns: the most
  // recent reported quarter's cash flow.
  const latest = quarterly[quarterly.length - 1];
  if (!latest) return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`)], rows: rows(annual) };
  return { headers: ['Metric', ...annual.map(r => `FY${r.fy}`), latest.label], rows: rows([...annual, latest]) };
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
    ['Days payable', ...list.map(r => fmtDays(r.payable_days))],
    ['Working capital days', ...list.map(r => fmtDays(r.working_capital_days))],
    ['Cash conversion cycle', ...list.map(r => fmtDays(r.ccc))],
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
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions. Latest Q is the most recent reported quarter.'],
    half: ['HALF-YEARLY', 'Half-end balances from reported quarters, in USD millions. Only halves with both quarters reported are shown.'],
    quarter: ['LAST 12 QUARTERS', 'Quarter-end balances, in USD millions.'],
  }, balanceRowsFor);
}
function renderCashflow(period) {
  renderPeriodSection(period, 'cashflowTable', 'cashflowPeriodSwitch', 'cashflowEyebrow', 'cashflowSubtitle', {
    yearly: ['ANNUAL HISTORY', 'Last ten reported financial years, in USD millions. Latest Q is the most recent reported quarter.'],
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
// Compound annual growth over a window of yearly values, oldest to
// newest. A window needs all its years present and positive — a
// missing or non-positive year makes the rate undefined, never
// estimated. The window counts years, so a 10-year CAGR spans nine
// intervals between the first and the last year.
function cagrFor(values, window) {
  if (!values || values.length < window) return null;
  const base = values[values.length - window];
  const latest = values[values.length - 1];
  if (base == null || latest == null || base <= 0 || latest <= 0) return null;
  return Math.pow(latest / base, 1 / (window - 1)) - 1;
}
// Average return on equity over the last `window` annual ratios.
// Every year in the window must be present, or the average is blank.
function roeAvgFor(ratios, window) {
  const vals = (ratios || []).slice(-window).map(r => r.roe);
  if (vals.length < window || vals.some(v => v == null)) return null;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}
// Trailing-twelve-month growth: the last four quarters vs the four
// before them. All eight quarters must report the figure, and the
// base period must be positive.
function ttmGrowthFor(quarterly, field) {
  const qs = quarterly || [];
  if (qs.length < 8) return null;
  const now = qs.slice(-4);
  const prior = qs.slice(-8, -4);
  if (![...now, ...prior].every(q => q[field] != null)) return null;
  const a = now.reduce((s, q) => s + q[field], 0);
  const b = prior.reduce((s, q) => s + q[field], 0);
  if (b <= 0) return null;
  return (a - b) / b;
}
// Price CAGR from a price history ([[timestamp, close], ...],
// ascending). The start is the close nearest to `years` before the
// latest close; blank unless a point sits within 60 days of that
// target — a series too short for the window gives no rate. The
// exponent uses the actual elapsed time, not the nominal window.
function priceCagrFor(points, years) {
  if (!points || points.length < 2) return null;
  const latest = points[points.length - 1];
  const target = latest[0] - years * 365.25 * 86400;
  let best = null;
  let bestDiff = Infinity;
  for (const p of points) {
    const d = Math.abs(p[0] - target);
    if (d < bestDiff) { bestDiff = d; best = p; }
  }
  if (!best || bestDiff > 60 * 86400 || best[1] <= 0 || latest[1] <= 0) return null;
  const elapsed = (latest[0] - best[0]) / (365.25 * 86400);
  if (elapsed <= 0) return null;
  return Math.pow(latest[1] / best[1], 1 / elapsed) - 1;
}
// Compound-growth values for the four CAGR cards. Sales and profit
// come from the annual series, ROE is the average annual ROE, and
// price comes from the 10-year chart history when it has loaded
// (null until then — the card renders with blanks, then refills).
function cagrValues(data, chartPoints) {
  const annual = (data && data.annual) || [];
  const ratios = (data && data.ratios) || [];
  const quarterly = (data && data.quarterly) || [];
  const series = field => annual.map(r => r[field]);
  const windows = [[10, 'y10'], [5, 'y5'], [3, 'y3']];
  const one = (values, isRoe) => {
    const out = {};
    for (const [w, key] of windows) out[key] = isRoe ? roeAvgFor(ratios, w) : cagrFor(values, w);
    return out;
  };
  const sales = one(series('revenue'), false);
  sales.ttm = (data.metrics && data.metrics.growth != null) ? data.metrics.growth : null;
  const profit = one(series('net_income'), false);
  profit.ttm = ttmGrowthFor(quarterly, 'net_income');
  const roe = one(null, true);
  roe.ttm = (data.metrics && data.metrics.roe != null) ? data.metrics.roe : null;
  const price = {};
  for (const [w, key] of windows) price[key] = chartPoints ? priceCagrFor(chartPoints, w) : null;
  price.ttm = chartPoints ? priceCagrFor(chartPoints, 1) : null;
  return { sales, profit, price, roe };
}
function growthCardsHtml(g, cagr) {
  const line = (label, item, key) => {
    const value = item[key];
    const vs = item[key === 'yoy' ? 'yoyLabel' : 'qoqLabel'];
    if (value == null) return `${label}: —${vs ? ` (${vs})` : ''}`;
    return `${label}: ${fmtSignedPct(value)} (${vs})`;
  };
  const card = (title, item) => `<article class="insight-card"><i data-lucide="trending-up"></i><h3>${title}</h3><p>${line('Year over year', item, 'yoy')}<br>${line('Prior quarter', item, 'qoq')}</p></article>`;
  const cagrLine = (label, value) => `${label}: ${value == null ? '—' : fmtSignedPct(value)}`;
  const cagrCard = (title, item) => `<article class="insight-card"><i data-lucide="trending-up"></i><h3>${title}</h3><p>${cagrLine('10Y', item.y10)}<br>${cagrLine('5Y', item.y5)}<br>${cagrLine('3Y', item.y3)}<br>${cagrLine('TTM', item.ttm)}</p></article>`;
  return card('Revenue', g.revenue) + card('Net income', g.net_income) + card('EPS diluted', g.eps)
    + cagrCard('Sales CAGR', cagr.sales) + cagrCard('Profit CAGR', cagr.profit)
    + cagrCard('Price CAGR', cagr.price) + cagrCard('ROE', cagr.roe);
}
async function renderGrowth(data) {
  const grid = document.querySelector('#growthGrid');
  if (!grid) return;
  const g = data ? growthFor(data.quarterly) : null;
  if (!g) {
    grid.innerHTML = '<article class="insight-card"><h3>Growth</h3><p>No quarterly filings reported for this company yet.</p></article>';
    return;
  }
  grid.innerHTML = growthCardsHtml(g, cagrValues(data, null));
  lucide.createIcons();
  // Price CAGR needs the 10-year chart history; it fills in once
  // that loads, and stays blank if the history is unavailable.
  try {
    const chart = await NorthstarAPI.chart(data.symbol, '10y');
    grid.innerHTML = growthCardsHtml(g, cagrValues(data, chart.points));
    lucide.createIcons();
  } catch (error) { /* price CAGR lines stay blank */ }
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
  renderGrowth(data);
  loadShareholding(data.symbol);
  loadDocuments(data.symbol);
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
  document.querySelector('#keyMetrics').innerHTML = [['Market cap', fmtCap(m.cap)], ['P/E ratio', fmtNum(m.pe, 1)], ['ROE', fmtPct(m.roe)], ['Debt / equity', fmtNum(m.debt_equity)], ['EPS (TTM)', fmtDollars(m.eps_ttm)], ['Book value / share', fmtDollars(m.book_value_per_share)], ['Dividend yield', fmtPct(m.dividend_yield)], ['52W range', '<span id="metric52w">—</span>'], ['50-day avg', `<span id="metricMA50">${ma50Value != null ? fmtDollars(ma50Value) : '—'}</span>`], ['200-day avg', `<span id="metricMA200">${ma200Value != null ? fmtDollars(ma200Value) : '—'}</span>`]].map(([name, value]) => `<div><span>${name}</span><strong>${value}</strong></div>`).join('');
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
  const growthGrid = document.querySelector('#growthGrid');
  if (growthGrid) growthGrid.innerHTML = `<article class="insight-card"><h3>Growth</h3><p>${message}</p></article>`;
  ['comparisonTable', 'quarterlyTable', 'profitTable', 'balanceTable', 'cashflowTable', 'ratiosTable', 'shareholdingTable', 'topInstitutionsTable', 'topInsidersTable', 'documentsTable'].forEach(id => {
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
    // Moving averages: only daily series support day-based averages, so
    // they are drawn and valued from daily closes (1mo/6mo/1y/3y). The
    // 5y/max files are weekly/monthly points and get no average lines.
    // The values in At a glance always come from the daily series, so
    // switching the chart range never changes what they mean.
    const daily = isDailySeries(points);
    const ma50 = daily ? movingAverageSeries(values, 50) : [];
    const ma200 = daily ? movingAverageSeries(values, 200) : [];
    if (daily) {
      const last50 = movingAverage(values, 50);
      const last200 = movingAverage(values, 200);
      if (last50 != null) ma50Value = last50;
      if (last200 != null) ma200Value = last200;
      fillMovingAverages();
    }
    const maPath = (series, cls) => {
      const pts = [];
      series.forEach((v, i) => {
        if (v == null) return;
        pts.push(`${(i / Math.max(values.length - 1, 1) * 1000).toFixed(2)},${(282 - ((v - min) / span * 242)).toFixed(2)}`);
      });
      return pts.length ? `<path class="${cls}" d="M${pts.join(' L')}"></path>` : '';
    };
    svg.innerHTML = `<path class="area" d="M0,300 L${coords.join(' L')} L1000,300 Z"></path><path class="line" d="M${coords.join(' L')}"></path>${maPath(ma50, 'ma50')}${maPath(ma200, 'ma200')}`;
    const legend = document.querySelector('#chartLegend');
    if (legend) {
      const show50 = ma50.some(v => v != null);
      const show200 = ma200.some(v => v != null);
      legend.hidden = !(show50 || show200);
      const l50 = legend.querySelector('.legend-ma50');
      const l200 = legend.querySelector('.legend-ma200');
      if (l50) l50.hidden = !show50;
      if (l200) l200.hidden = !show200;
    }
    loading.hidden = true;
  } catch (error) {
    loading.textContent = 'Price history unavailable right now.';
  }
}
// 50/200-day moving averages of the share price. A value is the mean of
// the last `window` closes, and null when the series is shorter than
// the window — never a partial average over fewer days.
let ma50Value = null;
let ma200Value = null;
function movingAverage(values, window) {
  if (!values || values.length < window) return null;
  let sum = 0;
  for (let i = values.length - window; i < values.length; i++) sum += values[i];
  return sum / window;
}
function movingAverageSeries(values, window) {
  if (!values) return [];
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    if (i >= window - 1) out[i] = sum / window;
  }
  return out;
}
function isDailySeries(points) {
  // Daily closes are ~1 day apart; weekly/monthly series are ~7/30.
  // The median gap decides, so a holiday gap or two cannot flip it.
  if (!points || points.length < 2) return false;
  const gaps = [];
  for (let i = 1; i < points.length; i++) gaps.push(points[i][0] - points[i - 1][0]);
  gaps.sort((a, b) => a - b);
  return gaps[Math.floor(gaps.length / 2)] < 2.5 * 86400;
}
function fillMovingAverages() {
  const ma50 = document.querySelector('#metricMA50');
  if (ma50) ma50.textContent = fmtDollars(ma50Value);
  const ma200 = document.querySelector('#metricMA200');
  if (ma200) ma200.textContent = fmtDollars(ma200Value);
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
  profileSymbol = symbol; ma50Value = null; ma200Value = null; const profile = profileFor(symbol); const stock = stocks.find(item => item.ticker === symbol);
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
