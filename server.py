#!/usr/bin/env python3
"""Small local server with a cached, same-origin quote endpoint."""

import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

CACHE_SECONDS = 15
quote_cache = {"timestamp": 0, "symbols": "", "quotes": []}


def get_quote(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=1d&interval=1m"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Local Screener)"})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
    meta = payload["chart"]["result"][0]["meta"]
    price = meta.get("regularMarketPrice", meta.get("previousClose"))
    previous = meta.get("chartPreviousClose", meta.get("previousClose"))
    if price is None or previous is None:
        raise ValueError("No quote data returned")
    return {"symbol": symbol, "price": price, "changePercent": ((price - previous) / previous) * 100}


def get_chart(symbol, period):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={urllib.parse.quote(period)}&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Local Screener)"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    points = [{"time": stamp, "close": close} for stamp, close in zip(result.get("timestamp", []), closes) if close is not None]
    return {"symbol": symbol, "points": points, "price": result["meta"].get("regularMarketPrice")}


class Server(SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/chart":
            query = urllib.parse.parse_qs(parsed.query)
            symbol = query.get("symbol", [""])[0].upper()
            period = query.get("range", ["1y"])[0]
            if not symbol.isalnum() or period not in {"1mo", "6mo", "1y", "3y", "5y", "10y", "max"}:
                self.send_error(400, "Invalid chart request")
                return
            try:
                body = json.dumps(get_chart(symbol, period)).encode()
            except Exception:
                self.send_error(503, "Chart service temporarily unavailable")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path != "/api/quotes":
            return super().do_GET()

        symbols = urllib.parse.parse_qs(parsed.query).get("symbols", [""])[0]
        symbols = ",".join(symbol.upper() for symbol in symbols.split(",") if symbol.isalnum())
        if not symbols:
            self.send_error(400, "Provide at least one symbol")
            return

        now = time.time()
        if quote_cache["symbols"] == symbols and now - quote_cache["timestamp"] < CACHE_SECONDS:
            quotes = quote_cache["quotes"]
            cached = True
        else:
            quotes = []
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {executor.submit(get_quote, symbol): symbol for symbol in symbols.split(",")}
                for future in as_completed(futures):
                    try:
                        quotes.append(future.result())
                    except Exception:
                        pass
            if not quotes:
                self.send_error(503, "Quote service temporarily unavailable")
                return
            quote_cache.update({"timestamp": now, "symbols": symbols, "quotes": quotes})
            cached = False

        body = json.dumps({"quotes": quotes, "updatedAt": int(quote_cache["timestamp"]), "cached": cached}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("Northstar local server: http://localhost:4175")
    ThreadingHTTPServer(("127.0.0.1", 4175), Server).serve_forever()
