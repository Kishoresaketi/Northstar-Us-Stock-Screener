// The screener list is the full S&P 500 + Nasdaq-100 universe (517
// companies), loaded from the pre-built search index — the same file the
// search box uses. It is a static snapshot (names/sectors change rarely);
// prices and fundamentals are fetched live per page, below.
let stocks = [];
let stocksLoaded = false;
const PAGE_SIZE = 15;
let currentPage = 1;
const tbody = document.querySelector('#stockRows');
let activeSector = 'all';
let favorites = new Set();

function sectorSlug(gics) {
  const map = {
    'Information Technology': 'technology', 'Health Care': 'healthcare',
    'Financials': 'financials', 'Energy': 'energy', 'Industrials': 'industrials',
    'Consumer Discretionary': 'consumer-discretionary',
    'Consumer Staples': 'consumer-staples', 'Materials': 'materials',
    'Utilities': 'utilities', 'Real Estate': 'real-estate',
    'Communication Services': 'communication-services',
  };
  return map[gics] || (gics || 'all').toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

async function loadUniverse() {
  try {
    const response = await fetch('data/search-index.json', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Universe list unavailable: ${response.status}`);
    const index = await response.json();
    stocks = index.map(entry => ({
      ticker: entry.symbol, name: entry.name, sector: sectorSlug(entry.sector),
      icon: entry.symbol[0], price: '—', change: '—', cap: '—', pe: '—', roe: '—', growth: '—',
    }));
    stocksLoaded = true;
    currentPage = 1;
    renderRows();
    loadPageData();
  } catch (error) {
    document.querySelector('#resultRange').textContent = 'Could not load the company list. Search still works.';
  }
}

function visibleStocks() {
  return stocks.filter(s => activeSector === 'all' || s.sector === activeSector);
}

function currentPageStocks() {
  const visible = visibleStocks();
  const start = (currentPage - 1) * PAGE_SIZE;
  return visible.slice(start, start + PAGE_SIZE);
}

function pageLabels(totalPages) {
  // Compact pager: first pages, current neighbourhood, last page.
  const pages = new Set([1, 2, 3, totalPages, currentPage - 1, currentPage, currentPage + 1]);
  const sorted = [...pages].filter(p => p >= 1 && p <= totalPages).sort((a, b) => a - b);
  const labels = [];
  sorted.forEach((p, i) => {
    if (i && p - sorted[i - 1] > 1) labels.push('…');
    labels.push(p);
  });
  return labels;
}

function renderPager(totalPages) {
  const pager = document.querySelector('.pager');
  if (!pager) return;
  pager.style.display = totalPages > 1 ? '' : 'none';
  if (totalPages <= 1) { pager.innerHTML = ''; return; }
  const buttons = pageLabels(totalPages).map(label =>
    label === '…'
      ? '<span>…</span>'
      : `<button data-page="${label}"${label === currentPage ? ' class="page-current"' : ''}>${label}</button>`).join('');
  pager.innerHTML = `<button data-page="prev" ${currentPage <= 1 ? 'disabled' : ''} aria-label="Previous page"><i data-lucide="chevron-left"></i></button>${buttons}<button data-page="next" ${currentPage >= totalPages ? 'disabled' : ''} aria-label="Next page"><i data-lucide="chevron-right"></i></button>`;
}

function renderRows() {
  const visible = visibleStocks();
  const totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  const start = (currentPage - 1) * PAGE_SIZE;
  const page = visible.slice(start, start + PAGE_SIZE);
  tbody.innerHTML = page.map((s, index) => `<tr><td><button class="star ${favorites.has(s.ticker) ? 'active' : ''}" data-star="${s.ticker}" aria-label="Save ${s.ticker}"><i data-lucide="star"></i></button></td><td><button class="company-cell row-button" data-stock="${s.ticker}"><span class="company-icon">${s.icon}</span><span><span class="company-name">${s.name}</span><span class="company-ticker">${s.ticker}</span></span></button></td><td>${s.price}</td><td class="${s.change.startsWith('-') ? 'negative' : 'positive'}">${s.change}</td><td>${s.cap}</td><td>${s.pe}</td><td>${s.roe}</td><td class="${s.growth.startsWith('-') ? 'negative' : 'growth'}">${s.growth}</td><td><button class="row-button" data-stock="${s.ticker}" aria-label="View ${s.name}"><i data-lucide="chevron-right"></i></button></td></tr>`).join('');
  document.querySelector('#resultCount').textContent = String(visible.length);
  const range = document.querySelector('#resultRange');
  if (range) range.textContent = !stocksLoaded ? 'Loading companies…' : visible.length ? `Showing ${start + 1}–${Math.min(start + PAGE_SIZE, visible.length)} of ${visible.length} results` : 'No companies match these filters';
  renderPager(totalPages);
  lucide.createIcons();
}
async function refreshQuotes() {
  const page = currentPageStocks();
  if (!page.length) return;
  const refreshTime = document.querySelector('#refreshTime');
  const marketStatus = document.querySelector('#marketStatus');
  try {
    const { quotes, updatedAt } = await NorthstarAPI.quotes(page.map(stock => stock.ticker));
    quotes.forEach(quote => {
      const stock = stocks.find(item => item.ticker === quote.symbol);
      if (!stock) return;
      stock.price = `$${Number(quote.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      stock.change = `${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%`;
    });
    renderRows();
    marketStatus.textContent = 'Live refresh';
    refreshTime.textContent = `Updated ${new Date(updatedAt * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
  } catch (error) {
    marketStatus.textContent = 'Quote feed unavailable';
    refreshTime.textContent = 'Showing last values';
  }
}
function openDrawer(ticker) {
  const s = stocks.find(stock => stock.ticker === ticker); if (!s) return;
  detailName.textContent = s.name; detailTicker.textContent = `${s.ticker} · ${s.sector[0].toUpperCase() + s.sector.slice(1)}`; detailInitial.textContent = s.icon; detailPrice.textContent = s.price; detailChange.textContent = s.change; detailChange.className = s.change.startsWith('-') ? 'negative' : 'positive'; detailCap.textContent = s.cap; detailPE.textContent = s.pe; detailROE.textContent = s.roe; detailGrowth.textContent = s.growth; detailDrawer.classList.add('open'); scrim.classList.add('open'); detailDrawer.setAttribute('aria-hidden','false');
}
document.querySelector('#quickFilters').addEventListener('click', e => { const button = e.target.closest('[data-filter]'); if (!button) return; activeSector = button.dataset.filter; currentPage = 1; document.querySelectorAll('.chip').forEach(c => c.classList.toggle('selected', c === button)); renderRows(); loadPageData(); });
document.querySelector('.pager').addEventListener('click', e => {
  const button = e.target.closest('[data-page]');
  if (!button || button.disabled) return;
  const target = button.dataset.page;
  const totalPages = Math.max(1, Math.ceil(visibleStocks().length / PAGE_SIZE));
  if (target === 'prev') currentPage = Math.max(1, currentPage - 1);
  else if (target === 'next') currentPage = Math.min(totalPages, currentPage + 1);
  else currentPage = Math.min(totalPages, Math.max(1, parseInt(target, 10) || 1));
  renderRows();
  loadPageData();
});
tbody.addEventListener('click', e => { const star = e.target.closest('[data-star]'); if (star) { const t = star.dataset.star; favorites.has(t) ? favorites.delete(t) : favorites.add(t); renderRows(); return; } const row = e.target.closest('[data-stock]'); if (row) window.openProfile?.(row.dataset.stock); });
document.querySelector('#closeDrawer').addEventListener('click', closeDrawer); scrim.addEventListener('click', closeDrawer); function closeDrawer(){detailDrawer.classList.remove('open');scrim.classList.remove('open');detailDrawer.setAttribute('aria-hidden','true')}
document.querySelectorAll('.filter-toggle').forEach(button => button.addEventListener('click', () => { const content = button.nextElementSibling; if (!content || !content.classList.contains('filter-content')) return; const open = button.getAttribute('aria-expanded') === 'true'; button.setAttribute('aria-expanded', !open); content.hidden = open; button.querySelector('svg')?.setAttribute('data-lucide', open ? 'chevron-down' : 'chevron-up'); lucide.createIcons(); }));
document.querySelector('#resetFilters').addEventListener('click', () => { document.querySelector('#marketCap').value='all'; document.querySelector('#roe').value='all'; document.querySelectorAll('.active-filter').forEach(f=>f.remove()); });
const stockSearch = document.querySelector('#stockSearch');
const searchInput = document.querySelector('#stockSearchInput');
const searchMessage = document.querySelector('#searchMessage');
const searchResults = document.querySelector('#searchResults');
document.querySelector('#openSearch').addEventListener('click', () => { stockSearch.hidden = false; searchInput.focus(); });
document.querySelector('#closeSearch').addEventListener('click', () => { stockSearch.hidden = true; searchResults.hidden = true; });
let searchTimer = null;
let lastSuggestions = [];
searchInput.addEventListener('input', () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (query.length < 2) { searchResults.hidden = true; searchResults.innerHTML = ''; lastSuggestions = []; return; }
  searchTimer = setTimeout(async () => {
    try {
      const results = await NorthstarAPI.search(query);
      lastSuggestions = results;
      if (!results.length) {
        searchResults.innerHTML = '';
        searchResults.hidden = true;
        searchMessage.textContent = NorthstarAPI.staticMode
          ? 'No match in the S&P 500 / Nasdaq-100 set. Try a ticker instead.'
          : 'No match. Try a ticker instead.';
        return;
      }
      searchResults.innerHTML = results.map(result =>
        `<button type="button" data-symbol="${result.symbol}"><b>${result.symbol}</b><span>${result.name}</span><em>${result.sector || ''}</em></button>`).join('');
      searchResults.hidden = false;
    } catch (error) {
      searchResults.hidden = true;
    }
  }, 250);
});
searchResults.addEventListener('click', event => {
  const button = event.target.closest('[data-symbol]');
  if (!button) return;
  openSearchedTicker(button.dataset.symbol);
});
async function openSearchedTicker(ticker, fallbackName) {
  searchMessage.textContent = `Looking up ${ticker}...`;
  try {
    const quote = (await NorthstarAPI.quotes([ticker])).quotes[0];
    const index = stocks.findIndex(stock => stock.ticker === ticker);
    if (index >= 0) {
      // In the universe: jump the table to the page holding this ticker.
      activeSector = 'all';
      document.querySelectorAll('.chip').forEach(chip => chip.classList.toggle('selected', chip.dataset.filter === 'all'));
      currentPage = Math.floor(index / PAGE_SIZE) + 1;
      const entry = stocks[index];
      entry.price = `$${Number(quote.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
      entry.change = `${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%`;
    }
    // Outside the universe (live mode only): the profile still opens from
    // the API; the ticker is not added to the universe table.
    renderRows(); window.openProfile?.(ticker); stockSearch.hidden = true; searchResults.hidden = true; searchInput.value = '';
    searchMessage.textContent = 'Search any company in the S&P 500 or Nasdaq-100, or enter a US ticker.';
  } catch (error) {
    searchMessage.textContent = NorthstarAPI.staticMode
      ? `No data for ${ticker} on this site — it is outside the S&P 500 / Nasdaq-100 set. The live version covers any US ticker.`
      : `Could not find a current quote for ${ticker}. Try a listed US ticker.`;
  }
}
document.querySelector('#stockSearchForm').addEventListener('submit', async event => {
  event.preventDefault();
  const query = searchInput.value.trim().toUpperCase();
  const first = lastSuggestions.find(result => result.symbol === query) || lastSuggestions[0];
  if (first && (first.symbol === query || first.name.toUpperCase().includes(query))) {
    openSearchedTicker(first.symbol, first.name);
    return;
  }
  if (!/^[A-Z0-9.\-]{1,10}$/.test(query)) { searchMessage.textContent = 'Enter a valid US ticker, such as VST or MSFT.'; return; }
  openSearchedTicker(query);
});
const stripMap = [['#mkt-sp', '^GSPC'], ['#mkt-nq', '^IXIC'], ['#mkt-dj', '^DJI'], ['#mkt-vix', '^VIX']];
async function refreshStrip() {
  try {
    const { quotes } = await NorthstarAPI.quotes(stripMap.map(([, symbol]) => symbol));
    stripMap.forEach(([selector, symbol]) => {
      const item = document.querySelector(selector);
      const quote = quotes.find(q => q.symbol === symbol);
      if (!item || !quote) return;
      const value = item.querySelector('strong');
      const change = item.querySelector('em');
      if (value) value.textContent = Number(quote.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      if (change) {
        change.textContent = `${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%`;
        change.className = quote.changePercent >= 0 ? 'positive' : 'negative';
      }
    });
  } catch (error) {
    /* keep the seeded strip values when the feed is down */
  }
}
function fmtCap(value) { if (value == null) return '—'; if (value >= 1e12) return `$${(value / 1e12).toFixed(2)}T`; if (value >= 1e9) return `$${(value / 1e9).toFixed(1)}B`; return `$${(value / 1e6).toFixed(0)}M`; }
async function refreshFundamentals() {
  const page = currentPageStocks();
  if (!page.length) return;
  try {
    const { fundamentals } = await NorthstarAPI.fundamentals(page.map(stock => stock.ticker));
    page.forEach(stock => {
      const f = fundamentals[stock.ticker];
      if (!f) return;
      stock.cap = fmtCap(f.cap);
      stock.pe = f.pe != null ? f.pe.toFixed(1) : '—';
      stock.roe = f.roe != null ? `${(f.roe * 100).toFixed(1)}%` : '—';
      stock.growth = f.growth != null ? `${f.growth >= 0 ? '+' : ''}${(f.growth * 100).toFixed(1)}%` : '—';
    });
    renderRows();
  } catch (error) {
    /* keep the seeded values when the fundamentals feed is down */
  }
}
function loadPageData() {
  // Quotes + fundamentals for the visible page only — never all 517 at once.
  refreshQuotes();
  refreshFundamentals();
}
renderRows(); lucide.createIcons();
loadUniverse(); refreshStrip();
setInterval(() => { refreshQuotes(); refreshStrip(); refreshFundamentals(); }, 60000);
