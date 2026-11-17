/* Data access for the Northstar front end.
 *
 * Two modes, same response shapes:
 * - API mode (local server.py, or Vercel): live /api/* endpoints.
 * - Static mode (GitHub Pages, which cannot run Python): pre-built JSON files
 *   under data/, refreshed hourly by .github/workflows/refresh-data.yml.
 * Static mode is active on *.github.io hostnames, or with ?static=1.
 */
const NorthstarAPI = (() => {
  const params = new URLSearchParams(window.location.search);
  const staticMode = window.location.hostname.endsWith('github.io') || params.get('static') === '1';

  async function getJSON(url) {
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) {
      const error = new Error(`Request failed: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  function fileFor(symbol) {
    return symbol.replace(/[^A-Za-z0-9.]/g, '_');
  }

  async function quotes(symbols) {
    if (!staticMode) {
      return getJSON(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`);
    }
    const results = await Promise.allSettled(symbols.map(symbol => getJSON(`data/quotes/${fileFor(symbol)}.json`)));
    const ok = results.filter(result => result.status === 'fulfilled').map(result => result.value);
    if (!ok.length) throw new Error('Quote data unavailable');
    return { quotes: ok, updatedAt: Math.max(...ok.map(quote => quote.generatedAt || 0)), cached: false };
  }

  async function chart(symbol, range) {
    if (!staticMode) return getJSON(`/api/chart?symbol=${symbol}&range=${range}`);
    return getJSON(`data/chart/${fileFor(symbol)}-${range}.json`);
  }

  async function fundamentals(symbols) {
    if (!staticMode) {
      return getJSON(`/api/fundamentals?symbols=${symbols.join(',')}`);
    }
    const results = await Promise.allSettled(symbols.map(symbol => getJSON(`data/fundamentals/${fileFor(symbol)}.json`)));
    const out = {};
    results.forEach((result, index) => { if (result.status === 'fulfilled') out[symbols[index]] = result.value; });
    if (!Object.keys(out).length) throw new Error('Fundamentals unavailable');
    return { fundamentals: out, updatedAt: Math.floor(Date.now() / 1000) };
  }

  async function financials(symbol) {
    if (!staticMode) return getJSON(`/api/financials?symbol=${symbol}`);
    return getJSON(`data/financials/${fileFor(symbol)}.json`);
  }

  let searchIndex = null;
  async function search(query) {
    const text = (query || '').trim().toUpperCase();
    if (!text) return [];
    if (!staticMode) {
      const data = await getJSON(`/api/search?q=${encodeURIComponent(text)}`);
      return data.results || [];
    }
    // Static mode: the pre-built index covers the S&P 500 + Nasdaq-100
    // universe (518 companies). Anything outside it needs the live API.
    if (!searchIndex) searchIndex = await getJSON('data/search-index.json');
    const matches = searchIndex.filter(entry =>
      entry.symbol.includes(text) || entry.name.toUpperCase().includes(text));
    matches.sort((a, b) => (a.symbol.startsWith(text) ? 0 : 1) - (b.symbol.startsWith(text) ? 0 : 1) || a.symbol.localeCompare(b.symbol));
    return matches.slice(0, 10).map(entry => ({ ...entry, inUniverse: true }));
  }

  return { quotes, chart, fundamentals, financials, search, staticMode };
})();
