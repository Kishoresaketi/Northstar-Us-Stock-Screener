# Northstar | US Stock Screener

Find quality companies at the right price. A web-based US stock screener with a
live screener table, watchlists, a discover section, ticker search, and a stock
profile view with price history.

## Live data

Prices, daily changes, and charts come from Yahoo Finance's public chart API
(`query1.finance.yahoo.com/v8/finance/chart`) — no API key needed. The
screener table refreshes live once a minute; market-index values in the header
strip (S&P 500, NASDAQ, Dow Jones, VIX) refresh the same way.

Fundamentals come from the US Securities and Exchange Commission's EDGAR
database (`data.sec.gov/api/xbrl/companyfacts`) — free, no API key, straight
from the company's own 10-K and 10-Q filings:

- The screener table's market cap, P/E, ROE, and revenue growth are computed
  live from filings plus the current price (trailing twelve months for P/E,
  ROE, and growth). A dash means the filings do not support that figure.
- The profile page shows peer comparison, quarterly results (last 12
  quarters), profit & loss, balance sheet, cash flow, and ratios for the last
  ten reported financial years, all from the filings.
- The shareholding pattern section was removed: there is no free source for
  historical institutional/insider ownership, and the previous table was
  generated placeholder data.

Prices may be delayed by the public data source. This is a research tool, not
investment advice.

## Run locally

Requires Python 3 (standard library only, no packages to install).

```sh
python3 server.py
```

Then open <http://127.0.0.1:4175>. The local server serves the site and the
`/api/quotes`, `/api/chart`, `/api/financials`, and `/api/fundamentals`
endpoints used by the front end.

## Deploy (Vercel)

The site is static plus four Python serverless functions in `api/`:

- `api/quotes.py` — `GET /api/quotes?symbols=AAPL,MSFT` returns live price and
  daily change per symbol (15-second server cache).
- `api/chart.py` — `GET /api/chart?symbol=AAPL&range=1y` returns daily closes
  for the profile chart (`1mo`, `6mo`, `1y`, `3y`, `5y`, `10y`, `max`), plus
  the 52-week high and low.
- `api/financials.py` — `GET /api/financials?symbol=AAPL` returns the full
  profile payload: live metrics, ten years of annuals, twelve quarters, ten
  years of ratios, and the peer comparison, all from SEC EDGAR filings.
- `api/fundamentals.py` — `GET /api/fundamentals?symbols=AAPL,MSFT` returns
  live metrics (market cap, P/E, ROE, growth) for the screener table.

1. Import `KishoreSaketi/Northstar-Us-Stock-Screener` from the Vercel dashboard.
2. Use the repository root, the **Other** framework preset, no build command,
   and `.` as the output directory. No `vercel.json` is needed; Vercel serves
   the static files and the `api/` functions automatically.
3. The front end calls the same-origin `/api/*` paths, so nothing else needs
   configuring. This is the fully live deployment: prices refresh every
   minute and financials are computed on demand.

## Deploy (GitHub Pages)

GitHub Pages cannot run the Python backend, so the Pages site reads pre-built
data files instead. `scripts/build_static_data.py` fetches the same live data
the `/api/*` endpoints use (quotes, charts, fundamentals, financials for the
screener's tickers plus VST and the four market indices) and writes it to
`data/*.json`. A GitHub Action (`.github/workflows/refresh-data.yml`) runs
the script every hour and commits the refreshed files to `main`.

1. In the repository, go to Settings → Pages → Build and deployment → Source:
   **Deploy from a branch**, Branch: **main**, Folder: **/(root)**.
2. The site is live at
   `https://kishoresaketi.github.io/Northstar-Us-Stock-Screener/`.
3. The front end (`api-client.js`) detects the `*.github.io` hostname and
   reads `data/*.json` instead of `/api/*`; nothing else changes.

Trade-off versus Vercel: on Pages the data is as fresh as the last hourly
refresh, not minute-live, and ticker search only works for the tickers the
build script covers (AAPL, MSFT, NVDA, GOOGL, LLY, JPM, XOM, VST). The
financial statements change rarely, so hourly is plenty for those.

## Endpoints (local and deployed)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/quotes?symbols=AAPL,MSFT` | Live price + daily change % per symbol. Also accepts index symbols (`^GSPC`, `^IXIC`, `^DJI`, `^VIX`). |
| `GET /api/chart?symbol=AAPL&range=1y` | Daily closing points for the profile chart, plus 52-week high/low. |
| `GET /api/financials?symbol=AAPL` | Live metrics, 10 years of annuals, 12 quarters, 10 years of ratios, and peers, from SEC EDGAR filings. Returns 404 when the ticker has no SEC filings. |
| `GET /api/fundamentals?symbols=AAPL,MSFT` | Live metrics (market cap, P/E, ROE, growth) per symbol for the screener table. |

## Notes

- Yahoo Finance's chart API is unofficial and may rate-limit; the UI falls back
  to the last shown values and reports "Quote feed unavailable" when the feed
  is down.
- `server.py` is only for local development. Vercel deployments use `api/`.
- EDGAR data is only as complete as the company's own filings. Exxon Mobil's
  current SEC filer is a newer entity with no 10-K annual history yet, so its
  profile shows quarterly data only and some metrics are blank; foreign
  issuers such as Novo Nordisk file under a different reporting regime and
  may show blank peer figures. Where a figure cannot be derived from the
  filings, the UI shows a dash rather than an estimate.
