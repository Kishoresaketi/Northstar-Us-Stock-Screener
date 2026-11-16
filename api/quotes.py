"""Vercel serverless function: live quotes via Yahoo Finance chart API (no key)."""

import json
import re
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler

CACHE_SECONDS = 15
_cache = {"timestamp": 0, "symbols": "", "quotes": []}
_SYMBOL_RE = re.compile(r"^[A-Z0-9.^\\-]{1,12}$")


def get_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1m"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Screener)"})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
    meta = payload["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice", meta.get("previousClose"))
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    if price is None or previous is None:
        raise ValueError("No quote data returned")
    return {"symbol": symbol, "price": price, "changePercent": ((price - previous) / previous) * 100}


def get_quotes(symbols):
    now = time.time()
    key = ",".join(symbols)
    if _cache["symbols"] == key and now - _cache["timestamp"] < CACHE_SECONDS:
        return _cache["quotes"], _cache["timestamp"], True
    quotes = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(get_quote, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                quotes.append(future.result())
            except Exception:
                pass
    if not quotes:
        raise RuntimeError("Quote service temporarily unavailable")
    _cache.update({"timestamp": now, "symbols": key, "quotes": quotes})
    return quotes, now, False


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw = query.get("symbols", [""])[0]
        symbols = [s.upper() for s in raw.split(",") if _SYMBOL_RE.match(s.strip().upper())]
        if not symbols:
            self._send(400, {"error": "Provide at least one symbol"})
            return
        try:
            quotes, updated_at, cached = get_quotes(symbols)
        except Exception:
            self._send(503, {"error": "Quote service temporarily unavailable"})
            return
        self._send(200, {"quotes": quotes, "updatedAt": int(updated_at), "cached": cached})

    def _send(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
