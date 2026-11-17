"""Vercel serverless function: search companies by ticker or name.

Matches against the S&P 500 + Nasdaq-100 universe snapshot first (so the
results always have a sector and a known name), then falls back to SEC
company_tickers.json for any other US-listed ticker.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.edgar as edgar

MAX_RESULTS = 10


def search_companies(query):
    query = (query or "").strip().upper()
    if not query:
        return []
    results = []
    seen = set()
    universe = edgar.universe()
    for symbol, entry in universe.items():
        if query in symbol or query in entry["name"].upper():
            results.append({"symbol": symbol, "name": entry["name"],
                            "sector": entry.get("sector"), "inUniverse": True})
            seen.add(symbol)
    # Ticker-prefix matches first, then name matches.
    results.sort(key=lambda r: (0 if r["symbol"].startswith(query) else 1, r["symbol"]))
    if len(results) < MAX_RESULTS:
        for symbol, (cik, title) in edgar.tickers().items():
            if symbol in seen:
                continue
            if query in symbol or query in title.upper():
                results.append({"symbol": symbol, "name": title.title(),
                                "sector": None, "inUniverse": False})
                seen.add(symbol)
            if len(results) >= MAX_RESULTS:
                break
    return results[:MAX_RESULTS]


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        text = query.get("q", [""])[0]
        if not text.strip():
            self._send(400, {"error": "Provide a search query"})
            return
        try:
            body = {"results": search_companies(text)}
        except Exception:
            self._send(503, {"error": "Search service temporarily unavailable"})
            return
        self._send(200, body)

    def _send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "max-age=3600")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
