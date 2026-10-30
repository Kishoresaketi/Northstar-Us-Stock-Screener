const stocks = [
  { ticker: 'AAPL', name: 'Apple Inc.', sector: 'technology', price: '$221.27', change: '+1.14%', cap: '$3.39T', pe: '34.2', roe: '147.9%', growth: '2.6%', icon: 'A' },
  { ticker: 'MSFT', name: 'Microsoft Corp.', sector: 'technology', price: '$446.34', change: '+0.75%', cap: '$3.32T', pe: '36.7', roe: '35.1%', growth: '16.4%', icon: 'M' },
  { ticker: 'NVDA', name: 'NVIDIA Corp.', sector: 'technology', price: '$128.28', change: '+3.54%', cap: '$3.15T', pe: '73.1', roe: '91.5%', growth: '122.4%', icon: 'N' },
  { ticker: 'GOOGL', name: 'Alphabet Inc.', sector: 'technology', price: '$162.78', change: '-0.19%', cap: '$2.01T', pe: '24.8', roe: '30.8%', growth: '15.4%', icon: 'G' },
  { ticker: 'LLY', name: 'Eli Lilly & Co.', sector: 'healthcare', price: '$905.16', change: '+1.85%', cap: '$860.2B', pe: '111.3', roe: '61.7%', growth: '35.9%', icon: 'L' },
  { ticker: 'JPM', name: 'JPMorgan Chase', sector: 'financials', price: '$221.88', change: '-0.54%', cap: '$624.4B', pe: '12.2', roe: '17.6%', growth: '21.8%', icon: 'J' },
  { ticker: 'XOM', name: 'Exxon Mobil Corp.', sector: 'energy', price: '$114.73', change: '+0.37%', cap: '$452.9B', pe: '14.3', roe: '15.2%', growth: '-5.4%', icon: 'X' }
];
const tbody = document.querySelector('#stockRows');
let activeSector = 'all';
let favorites = new Set();
function renderRows() {
  const visible = stocks.filter(s => activeSector === 'all' || s.sector === activeSector);
  tbody.innerHTML = visible.map((s, index) => `<tr><td><button class="star ${favorites.has(s.ticker) ? 'active' : ''}" data-star="${s.ticker}" aria-label="Save ${s.ticker}"><i data-lucide="star"></i></button></td><td><button class="company-cell row-button" data-stock="${s.ticker}"><span class="company-icon">${s.icon}</span><span><span class="company-name">${s.name}</span><span class="company-ticker">${s.ticker}</span></span></button></td><td>${s.price}</td><td class="${s.change.startsWith('-') ? 'negative' : 'positive'}">${s.change}</td><td>${s.cap}</td><td>${s.pe}</td><td>${s.roe}</td><td class="${s.growth.startsWith('-') ? 'negative' : 'growth'}">${s.growth}</td><td><button class="row-button" data-stock="${s.ticker}" aria-label="View ${s.name}"><i data-lucide="chevron-right"></i></button></td></tr>`).join('');
  document.querySelector('#resultCount').textContent = activeSector === 'all' ? '247' : String(Math.max(15, visible.length * 18));
  lucide.createIcons();
}
async function refreshQuotes() {
  const refreshTime = document.querySelector('#refreshTime');
  const marketStatus = document.querySelector('#marketStatus');
  try {
    const symbols = stocks.map(stock => stock.ticker).join(',');
    const response = await fetch(`/api/quotes?symbols=${symbols}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Quote service unavailable');
    const { quotes, updatedAt } = await response.json();
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
document.querySelector('#quickFilters').addEventListener('click', e => { const button = e.target.closest('[data-filter]'); if (!button) return; activeSector = button.dataset.filter; document.querySelectorAll('.chip').forEach(c => c.classList.toggle('selected', c === button)); renderRows(); });
tbody.addEventListener('click', e => { const star = e.target.closest('[data-star]'); if (star) { const t = star.dataset.star; favorites.has(t) ? favorites.delete(t) : favorites.add(t); renderRows(); return; } const row = e.target.closest('[data-stock]'); if (row) window.openProfile?.(row.dataset.stock); });
document.querySelector('#closeDrawer').addEventListener('click', closeDrawer); scrim.addEventListener('click', closeDrawer); function closeDrawer(){detailDrawer.classList.remove('open');scrim.classList.remove('open');detailDrawer.setAttribute('aria-hidden','true')}
document.querySelectorAll('.filter-toggle').forEach(button => button.addEventListener('click', () => { const content = button.nextElementSibling; if (!content || !content.classList.contains('filter-content')) return; const open = button.getAttribute('aria-expanded') === 'true'; button.setAttribute('aria-expanded', !open); content.hidden = open; button.querySelector('svg')?.setAttribute('data-lucide', open ? 'chevron-down' : 'chevron-up'); lucide.createIcons(); }));
document.querySelector('#resetFilters').addEventListener('click', () => { document.querySelector('#marketCap').value='all'; document.querySelector('#roe').value='all'; document.querySelectorAll('.active-filter').forEach(f=>f.remove()); });
const stockSearch = document.querySelector('#stockSearch');
const searchInput = document.querySelector('#stockSearchInput');
const searchMessage = document.querySelector('#searchMessage');
document.querySelector('#openSearch').addEventListener('click', () => { stockSearch.hidden = false; searchInput.focus(); });
document.querySelector('#closeSearch').addEventListener('click', () => { stockSearch.hidden = true; });
document.querySelector('#stockSearchForm').addEventListener('submit', async event => {
  event.preventDefault();
  const query = searchInput.value.trim().toUpperCase();
  const knownNames = { 'VISTRA': 'VST', 'VISTRA CORP': 'VST', 'APPLE': 'AAPL', 'APPLE INC': 'AAPL', 'MICROSOFT': 'MSFT', 'NVIDIA': 'NVDA', 'ALPHABET': 'GOOGL', 'GOOGLE': 'GOOGL', 'ELI LILLY': 'LLY', 'JPMORGAN': 'JPM', 'EXXON': 'XOM' };
  const ticker = knownNames[query] || query;
  if (!/^[A-Z.]{1,8}$/.test(ticker)) { searchMessage.textContent = 'Enter a valid US ticker, such as VST or MSFT.'; return; }
  searchMessage.textContent = `Looking up ${ticker}...`;
  try {
    const response = await fetch(`/api/quotes?symbols=${ticker}`, { cache: 'no-store' });
    if (!response.ok) throw new Error('Not found');
    const quote = (await response.json()).quotes[0];
    const existing = stocks.find(stock => stock.ticker === ticker);
    const entry = existing || { ticker, name: ticker === 'VST' ? 'Vistra Corp.' : ticker, sector: 'all', cap: '—', pe: '—', roe: '—', growth: '—', icon: ticker.slice(0, 1) };
    entry.price = `$${Number(quote.price).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    entry.change = `${quote.changePercent >= 0 ? '+' : ''}${quote.changePercent.toFixed(2)}%`;
    if (!existing) stocks.unshift(entry);
    activeSector = 'all';
    document.querySelectorAll('.chip').forEach(chip => chip.classList.toggle('selected', chip.dataset.filter === 'all'));
    renderRows(); window.openProfile?.(ticker); stockSearch.hidden = true; searchInput.value = ''; searchMessage.textContent = 'Enter a US ticker to add it to this screen.';
  } catch (error) { searchMessage.textContent = `Could not find a current quote for ${ticker}. Try a listed US ticker.`; }
});
renderRows(); lucide.createIcons();
refreshQuotes();
setInterval(refreshQuotes, 60000);
