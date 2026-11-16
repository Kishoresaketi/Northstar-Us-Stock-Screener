# Northstar | US Stock Screener

Find quality companies at the right price. A web-based US stock screener with a
live screener table, watchlists, a discover section, ticker search, and a stock
profile view with price history.

## Live data

Prices, daily changes, and charts come from Yahoo Finance's public chart API
(`query1.finance.yahoo.com/v8/finance/chart`) — no API key needed. The
screener table refreshes live once a minute; market-index values in the header
strip (S&P 500, NASDAQ, Dow Jones, VIX) refresh the same way. Market cap, P/E,
ROE, and revenue growth are currently seeded values and are being wired to live
SEC EDGAR company facts; see `api/fundamentals.py` when it lands.

Prices may be delayed by the public data source. This is a research tool, not
investment advice.

## Run locally

Requires Python 3 (standard library only, no packages to install).

```sh
python3 server.py
```

Then open <http://127.0.0.1:4175>. The local server serves the site and the
`/api/quotes` and `/api/chart` endpoints used by the front end.

## Deploy (Vercel)

The site is static plus two Python serverless functions in `api/`:

- `api/quotes.py` — `GET /api/quotes?symbols=AAPL,MSFT` returns live price and
  daily change per symbol (15-second server cache).
- `api/chart.py` — `GET /api/chart?symbol=AAPL&range=1y` returns daily closes
  for the profile chart (`1mo`, `6mo`, `1y`, `3y`, `5y`, `10y`, `max`).

1. Import `KishoreSaketi/Northstar-Us-Stock-Screener` from the Vercel dashboard.
2. Use the repository root, the **Other** framework preset, no build command,
   and `.` as the output directory. No `vercel.json` is needed; Vercel serves
   the static files and the `api/` functions automatically.
3. The front end calls the same-origin `/api/*` paths, so nothing else needs
   configuring.

## Endpoints (local and deployed)

| Endpoint | Purpose |
| --- | --- |
| `GET /api/quotes?symbols=AAPL,MSFT` | Live price + daily change % per symbol. Also accepts index symbols (`^GSPC`, `^IXIC`, `^DJI`, `^VIX`). |
| `GET /api/chart?symbol=AAPL&range=1y` | Daily closing points for the profile chart. |

## Notes

- Yahoo Finance's chart API is unofficial and may rate-limit; the UI falls back
  to the last shown values and reports "Quote feed unavailable" when the feed
  is down.
- `server.py` is only for local development. Vercel deployments use `api/`.
- Company profile research notes and the quarterly/annual statement tables are
  placeholders until the SEC EDGAR wiring lands; do not treat them as reported
  figures.
