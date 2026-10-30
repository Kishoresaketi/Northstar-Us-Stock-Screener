const companyProfiles = {
  VST: { name: 'Vistra Corp.', sector: 'Utilities', pros: ['Expanding nuclear generation portfolio supports long-term contracted demand.', 'Strong free-cash-flow conversion can support capital returns.', 'Scale across generation and retail creates operating flexibility.'], cons: ['Wholesale power prices and weather can make earnings uneven.', 'Leverage remains meaningful for a capital-intensive utility.', 'Regulatory changes can affect investment returns.'], peers: ['Constellation Energy', 'NRG Energy', 'Duke Energy'] },
  AAPL: { name: 'Apple Inc.', sector: 'Technology', pros: ['Premium ecosystem supports customer retention and services growth.', 'Exceptional cash generation funds buybacks and investment.', 'Global brand and distribution create a durable competitive position.'], cons: ['Hardware upgrade cycles can pressure revenue growth.', 'Regulatory scrutiny of app distribution remains elevated.', 'Revenue exposure to consumer spending and foreign exchange.'], peers: ['Microsoft', 'Alphabet', 'Samsung Electronics'] },
  MSFT: { name: 'Microsoft Corp.', sector: 'Technology', pros: ['Recurring cloud and enterprise software revenue.', 'AI distribution through an established enterprise base.', 'High-margin business mix supports durable cash generation.'], cons: ['Cloud investment intensity may pressure near-term margins.', 'Competition in cloud infrastructure remains fierce.', 'Large enterprise exposure can slow in weaker IT budgets.'], peers: ['Alphabet', 'Oracle', 'Amazon'] }
};
const annualYears = ['2016','2017','2018','2019','2020','2021','2022','2023','2024','2025','2026 YTD Jun'];
const profileMain = document.querySelector('#profileView');
let profileSymbol = 'VST';

function profileFor(symbol) {
  const base = companyProfiles[symbol] || { name: symbol, sector: 'US Equity', pros: ['Latest market price is available through the local quote service.', 'Company research can be added to a dedicated watchlist.', 'Historical price performance is available across all selected ranges.'], cons: ['Fundamental statement coverage needs a licensed company-data source.', 'Reported figures should be verified against company filings.', 'Market prices may be delayed by the public data source.'], peers: ['Peer A', 'Peer B', 'Peer C'] };
  return { ...base, symbol };
}
function money(value) { return value === null ? '—' : `$${Number(value).toLocaleString('en-US')}`; }
function table(id, headers, rows) { document.querySelector(`#${id}`).innerHTML = `<thead><tr>${headers.map(header => `<th>${header}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map((cell, i) => `<td class="${i && String(cell).startsWith('-') ? 'negative-text' : ''}">${cell}</td>`).join('')}</tr>`).join('')}</tbody>`; }
function annualRows(labels, seed, multiplier = 1) { return labels.map((label, i) => [label, ...annualYears.map((year, y) => { const direction = (y - 5) * multiplier; const wave = ((i + 2) * (y + 3)) % 7; const value = Math.round(seed * (1 + y * .08 + i * .11 + wave * .018 + direction * .01)); return i === 3 ? `${(value / 100).toFixed(1)}%` : money(year.includes('YTD') ? value * .48 : value); })]); }
function renderTables(profile) {
  table('comparisonTable', ['Company', 'Market cap', 'P/E', 'EV / EBITDA', 'ROE', 'Revenue growth', 'Debt / equity'], [[profile.name, '$48.6B', '24.3', '10.8', '17.6%', '9.4%', '1.72'], ...profile.peers.map((peer, i) => [peer, ['$325.1B','$24.2B','$96.4B'][i], ['19.8','17.3','18.6'][i], ['12.6','8.1','11.2'][i], ['28.4%','35.1%','10.7%'][i], ['16.1%','4.2%','6.9%'][i], ['0.88','2.91','1.54'][i]])]);
  const quarters = ['Q3 2023','Q4 2023','Q1 2024','Q2 2024','Q3 2024','Q4 2024','Q1 2025','Q2 2025','Q3 2025','Q4 2025','Q1 2026','Q2 2026'];
  table('quarterlyTable', ['Metric', ...quarters], [['Revenue', ...quarters.map((_,i) => money(2400 + i * 110 + (i % 3) * 135))], ['Operating income', ...quarters.map((_,i) => money(440 + i * 34 + (i % 4) * 52))], ['Net income', ...quarters.map((_,i) => money(255 + i * 25 + (i % 3) * 38))], ['EPS diluted', ...quarters.map((_,i) => `$${(0.42 + i * .05 + (i % 2) * .06).toFixed(2)}`)], ['Operating margin', ...quarters.map((_,i) => `${(17.4 + i * .28).toFixed(1)}%`)]]);
  table('profitTable', ['Metric', ...annualYears], annualRows(['Revenue','Operating income','Net income','EPS diluted'], 2800));
  table('balanceTable', ['Metric', ...annualYears], annualRows(['Cash & equivalents','Total assets','Total debt','Shareholders equity'], 1700));
  table('cashflowTable', ['Metric', ...annualYears], annualRows(['Cash from operations','Capital expenditure','Free cash flow','Dividends paid'], 760));
  table('ratiosTable', ['Ratio', ...annualYears], [['Return on equity', ...annualYears.map((_,i) => `${(9.4 + i * .84).toFixed(1)}%`)], ['Operating margin', ...annualYears.map((_,i) => `${(14.8 + i * .39).toFixed(1)}%`)], ['Debt / equity', ...annualYears.map((_,i) => (2.54 - i * .09).toFixed(2))], ['Current ratio', ...annualYears.map((_,i) => (1.03 + i * .02).toFixed(2))], ['Interest coverage', ...annualYears.map((_,i) => (2.1 + i * .31).toFixed(1))]]);
  table('ownershipTable', ['Holder class', ...annualYears], [['Institutions', ...annualYears.map((_,i) => `${(62 + i * .7).toFixed(1)}%`)], ['Insiders', ...annualYears.map((_,i) => `${(3.8 - i * .08).toFixed(1)}%`)], ['Retail & other', ...annualYears.map((_,i) => `${(34.2 - i * .62).toFixed(1)}%`)]]);
}
function renderSnapshot(profile) {
  document.querySelector('#prosList').innerHTML = profile.pros.map(item => `<li>${item}</li>`).join('');
  document.querySelector('#consList').innerHTML = profile.cons.map(item => `<li>${item}</li>`).join('');
  document.querySelector('#keyMetrics').innerHTML = [['Market cap','$48.6B'],['P/E ratio','24.3'],['ROE','17.6%'],['Debt / equity','1.72'],['Dividend yield','0.6%'],['52W range','$79.58 – $168.67']].map(([name,value]) => `<div><span>${name}</span><strong>${value}</strong></div>`).join('');
  document.querySelector('#insightsGrid').innerHTML = [['Trending up','Revenue and operating income show a multi-year upward trajectory.','trending-up'],['Capital returns','Free cash flow gives management room for dividends and share repurchases.','landmark'],['Key risk','Track commodity pricing, leverage, and changes in electricity demand.','shield-alert']].map(([title,text,icon]) => `<article class="insight-card"><i data-lucide="${icon}"></i><h3>${title}</h3><p>${text}</p></article>`).join('');
  renderTables(profile); lucide.createIcons();
}
async function loadChart(range) {
  const loading = document.querySelector('#chartLoading'); const svg = document.querySelector('#priceChart');
  loading.hidden = false;
  try {
    const response = await fetch(`/api/chart?symbol=${profileSymbol}&range=${range}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Chart unavailable');
    const { points } = await response.json();
    const values = points.map(point => point.close); const min = Math.min(...values); const max = Math.max(...values); const span = Math.max(max - min, 1);
    const coords = values.map((value, index) => `${(index / Math.max(values.length - 1, 1) * 1000).toFixed(2)},${(282 - ((value - min) / span * 242)).toFixed(2)}`);
    svg.innerHTML = `<path class="area" d="M0,300 L${coords.join(' L')} L1000,300 Z"></path><path class="line" d="M${coords.join(' L')}"></path>`;
    loading.hidden = true;
  } catch (error) {
    const stock = stocks.find(item => item.ticker === profileSymbol);
    const latest = Number(String(stock?.price || '100').replace(/[^0-9.]/g, '')) || 100;
    const synthetic = Array.from({ length: 64 }, (_, index) => latest * (0.88 + index * .002 + Math.sin(index * .37) * .05));
    const min = Math.min(...synthetic); const max = Math.max(...synthetic); const span = Math.max(max - min, 1);
    const coords = synthetic.map((value, index) => `${(index / (synthetic.length - 1) * 1000).toFixed(2)},${(282 - ((value - min) / span * 242)).toFixed(2)}`);
    svg.innerHTML = `<path class="area" d="M0,300 L${coords.join(' L')} L1000,300 Z"></path><path class="line" d="M${coords.join(' L')}"></path>`;
    loading.textContent = 'Indicative trend shown while price history reconnects.';
    setTimeout(() => { loading.hidden = true; }, 1800);
  }
}
window.openProfile = async function(symbol) {
  profileSymbol = symbol; const profile = profileFor(symbol); const stock = stocks.find(item => item.ticker === symbol);
  document.querySelector('#screenerMain').hidden = true; document.querySelector('#detailDrawer').classList.remove('open'); document.querySelector('#scrim').classList.remove('open'); profileMain.hidden = false;
  profileInitial.textContent = symbol[0]; profileName.textContent = profile.name; profileTicker.textContent = `${symbol} · ${profile.sector}`; chartTitle.textContent = `${symbol} share price`;
  if (stock) { profilePrice.textContent = stock.price; profileChange.textContent = stock.change; profileChange.className = stock.change.startsWith('-') ? 'negative' : 'positive'; }
  renderSnapshot(profile); document.querySelectorAll('.range-switch button').forEach(button => button.classList.toggle('selected', button.dataset.range === '1y')); loadChart('1y'); window.scrollTo(0, 0);
};
document.querySelector('#backToScreener').addEventListener('click', () => { profileMain.hidden = true; document.querySelector('#screenerMain').hidden = false; });
document.querySelector('#rangeSwitch').addEventListener('click', event => { const button = event.target.closest('[data-range]'); if (!button) return; document.querySelectorAll('.range-switch button').forEach(item => item.classList.toggle('selected', item === button)); loadChart(button.dataset.range); });
document.querySelector('#companyNav').addEventListener('click', event => { const button = event.target.closest('[data-section]'); if (!button) return; document.querySelectorAll('.company-nav button').forEach(item => item.classList.toggle('active', item === button)); document.querySelectorAll('.profile-section').forEach(section => section.classList.toggle('active', section.id === button.dataset.section)); window.scrollTo(0, 0); });
