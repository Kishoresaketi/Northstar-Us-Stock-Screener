# Northstar | US Stock Screener

Find quality companies at the right price. A web-based US stock screener with a
live screener table, watchlists, a discover section, ticker search, and a stock
profile view with price history.

## Universe

The screener covers the **S&P 500 + Nasdaq-100 — 517 unique tickers**
(snapshot in `scripts/universe/`, fetched by
`scripts/universe/fetch_universe.py` from the datasets S&P 500 CSV and the
Wikipedia Nasdaq-100 list). Every one of them gets the full profile: price
history in all seven ranges, peer comparison, quarterly results, ten years of
financials and ratios, and data-driven pros & cons.

## Live data

Prices, daily changes, and charts come from Yahoo Finance's public chart API
(`query1.finance.yahoo.com/v8/finance/chart`) — no API key needed. The
screener table refreshes live once a minute; market-index values in the header
strip (S&P 500, NASDAQ, Dow Jones, VIX) refresh the same way. While a company
profile is open, its price refreshes every minute and its chart reloads every
minute in live mode.

Fundamentals come from the US Securities and Exchange Commission's EDGAR
database (`data.sec.gov/api/xbrl/companyfacts`) — free, no API key, straight
from the company's own 10-K and 10-Q filings:

- The screener table's market cap, P/E, ROE, and revenue growth are computed
  live from filings plus the current price (trailing twelve months for P/E,
  ROE, and growth). A dash means the filings do not support that figure.
- The profile page shows peer comparison, quarterly results (last 12
  quarters), profit & loss, balance sheet, cash flow, and ratios for the last
  ten reported financial years, all from the filings.
- **Peers:** the eight seeded stocks (AAPL, MSFT, NVDA, GOOGL, LLY, JPM, XOM,
  VST) use curated peer lists of 10–12 same-industry names. Every other
  ticker gets peers from `data/peer-map.json`, built from the universe:
  same sub-industry first, then same sector, ranked by market cap (10 peers).
- **Pros & cons** are computed from the filing data (`lib/edgar.py`
  `pros_cons`): ROE, ROCE, margins, revenue growth, free-cash-flow trend,
  leverage, dividends, and valuation versus the peer median. Each item cites
  its figure; anything the data cannot support is left out, and the section
  says so when nothing stands out either way.
- **Search** (`GET /api/search?q=...`) matches ticker or company name across
  the universe first, then any SEC-listed ticker. On the Pages site the
  search index covers the 517 built tickers; the live deployment searches
  any US ticker on demand.
- The shareholding pattern is not shown: there is no free source for
  institutional/insider ownership (Yahoo's ownership endpoint is dead,
  Nasdaq's institutional-holdings API returns 404, and aggregating SEC 13F
  filings across thousands of funds is not feasible here). The earlier
  placeholder table was removed rather than show invented numbers.

Prices may be delayed by the public data source. This is a research tool, not
investment advice.

## Run locally

Requires Python 3 (standard library only, no packages to install).

```sh
python3 server.py
```

Then open <http://127.0.0.1:4175>. The local server serves the site and the
`/api/quotes`, `/api/chart`, `/api/financials`, `/api/fundamentals`, and
`/api/search` endpoints used by the front end.

## Deploy (Vercel)

The site is static plus five Python serverless functions in `api/`:

- `api/quotes.py` — `GET /api/quotes?symbols=AAPL,MSFT` returns live price and
  daily change per symbol (15-second server cache).
- `api/chart.py` — `GET /api/chart?symbol=AAPL&range=1y` returns closing
  points for the profile chart (`1mo`, `6mo`, `1y`, `3y`, `5y`, `10y`, `max`),
  plus the 52-week high and low. Points are compact `[timestamp, close]`
  pairs; the 5y/10y ranges are weekly sampled (a 10-year daily series is
  ~2,500 points on a 1,000px chart, so weekly looks identical).
- `api/financials.py` — `GET /api/financials?symbol=AAPL` returns the full
  profile payload: live metrics, ten years of annuals, twelve quarters, ten
  years of ratios, peer comparison, and data-driven pros & cons, all from
  SEC EDGAR filings.
- `api/fundamentals.py` — `GET /api/fundamentals?symbols=AAPL,MSFT` returns
  live metrics (market cap, P/E, ROE, growth) for the screener table.
- `api/search.py` — `GET /api/search?q=apple` returns up to 10 ticker/name
  matches, universe first, then any SEC-listed ticker.

1. Import `KishoreSaketi/Northstar-Us-Stock-Screener` from the Vercel dashboard.
2. Use the repository root, the **Other** framework preset, no build command,
   and `.` as the output directory. No `vercel.json` is needed; Vercel serves
   the static files and the `api/` functions automatically.
3. The front end calls the same-origin `/api/*` paths, so nothing else needs
   configuring. This is the fully live deployment: prices and charts refresh
   every minute and financials are computed on demand for any ticker.

## Deploy (GitHub Pages)

GitHub Pages cannot run the Python backend, so the Pages site reads pre-built
data files instead. `scripts/build_static_data.py` fetches the same live data
the `/api/*` endpoints use and writes it to `data/*.json` for all 517
universe tickers plus the four market indices (~5,000 files). A GitHub Action
(`.github/workflows/refresh-data.yml`) keeps them fresh:

- **Hourly:** quotes only (`--mode fast`). Prices move every hour.
- **Daily at 02:07 UTC:** full rebuild (`--mode full`) — peer map, search
  index, fundamentals, financials, all chart ranges. Filings only change on
  new 10-K/10-Q releases and charts only gain a new daily close, so daily is
  the honest refresh rate for those files. A full rebuild every hour would
  hammer the free Yahoo/EDGAR sources and churn the git history for nothing.

The workflow file cannot be pushed by automation (GitHub blocks workflow
files from app tokens), so it must be added through the GitHub web UI:
repository → Actions → New workflow → paste
`.github/workflows/refresh-data.yml` from this repo.

1. In the repository, go to Settings → Pages → Build and deployment → Source:
   **Deploy from a branch**, Branch: **main**, Folder: **/(root)**.
2. The site is live at
   `https://kishoresaketi.github.io/Northstar-Us-Stock-Screener/`.
3. The front end (`api-client.js`) detects the `*.github.io` hostname and
   reads `data/*.json` instead of `/api/*`; nothing else changes.

Trade-off versus Vercel: on Pages the data is as fresh as the last rebuild
(quotes hourly, everything else daily), and search covers the 517 built
tickers rather than any ticker. The live deployment has no such limits.

## Endpoints (local and deployed)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/quotes?symbols=AAPL,MSFT` | Live price + daily change % per symbol. Also accepts index symbols (`^GSPC`, `^IXIC`, `^DJI`, `^VIX`). |
| `GET /api/chart?symbol=AAPL&range=1y` | Closing points for the profile chart, plus 52-week high/low. |
| `GET /api/financials?symbol=AAPL` | Live metrics, 10 years of annuals, 12 quarters, 10 years of ratios, peers, and pros & cons, from SEC EDGAR filings. Returns 404 when the ticker has no SEC filings. |
| `GET /api/fundamentals?symbols=AAPL,MSFT` | Live metrics (market cap, P/E, ROE, growth) per symbol for the screener table. |
| `GET /api/search?q=apple` | Up to 10 ticker/name matches, universe first, then any SEC-listed ticker. |

## Notes

- Yahoo Finance's chart API is unofficial and may rate-limit; the UI falls back
  to the last shown values and reports "Quote feed unavailable" when the feed
  is down.
- `server.py` is only for local development. Vercel deployments use `api/`.
- EDGAR data is only as complete as the company's own filings. Exxon Mobil's
  current SEC filer is a newer entity with no 10-K annual history yet, so its
  profile shows quarterly data only and some metrics are blank; foreign
  issuers such as Novo Nordisk and ASML file under a different reporting
  regime and may show blank peer figures. Where a figure cannot be derived
  from the filings, the UI shows a dash rather than an estimate.
- Share counts come from the filings two ways: the cover-page figure when
  it is current, otherwise the weighted-average shares from the latest 10-K
  (the EPS denominator — the consistent choice for P/E). A cover-page count
  older than two years is ignored, since mixing a stale count with today's
  price produces nonsense (Berkshire showed P/E 0.007 that way). Six
  tickers have no usable share count in EDGAR at all — mostly dual-class
  filers (Berkshire Hathaway, Visa, Erie Indemnity, Constellation Brands,
  Tyson Foods) and foreign filer Thomson Reuters — so their market cap and
  P/E show as dashes while ROE, growth, and leverage still render. No free
  source was found for those share counts; nothing is estimated.
- SpaceX (SPCX) appeared as a bad row in the Wikipedia Nasdaq-100 list
  (a private company with no public ticker) and is explicitly excluded
  from the universe in `scripts/universe/fetch_universe.py`.
