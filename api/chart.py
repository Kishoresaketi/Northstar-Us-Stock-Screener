"""Vercel serverless function: price history via Yahoo Finance chart API (no key)."""

import json
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler

VALID_RANGES = {"1mo", "6mo", "1y", "3y", "5y", "10y", "max"}


def get_chart(symbol, period):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={urllib.parse.quote(period)}&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Northstar Screener)"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    result = payload["chart"]["result"][0]
    closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    points = [{"time": stamp, "close": close} for stamp, close in zip(result.get("timestamp", []), closes) if close is not None]
    return {"symbol": symbol, "points": points, "price": result["meta"].get("regularMarketPrice")}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        symbol = query.get("symbol", [""])[0].upper()
        period = query.get("range", ["1y"])[0]
        if not symbol.isalnum() or period not in VALID_RANGES:
            self._send(400, {"error": "Invalid chart request"})
            return
        try:
            body = get_chart(symbol, period)
        except Exception:
            self._send(503, {"error": "Chart service temporarily unavailable"})
            return
        self._send(200, body)

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
