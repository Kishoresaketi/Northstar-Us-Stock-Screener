"""Vercel serverless function: batch table metrics for the screener.

Live market cap, P/E, ROE and revenue growth per symbol, computed from SEC
EDGAR filings and the live price. Feeds the screener table's fundamental
columns so they stop being seeded values.
"""

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.edgar as edgar

_SYMBOL_RE = re.compile(r"^[A-Z0-9.^\\-]{1,12}$")


def _one(symbol):
    price = edgar.live_price(symbol)
    metrics = edgar.metrics(symbol, price["price"])
    metrics["changePercent"] = price["changePercent"]
    return metrics


def get_fundamentals(symbols):
    out = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_one, symbol): symbol for symbol in symbols}
        for future in as_completed(futures):
            try:
                result = future.result()
                out[result["symbol"]] = result
            except Exception:
                pass
    if not out:
        raise RuntimeError("Fundamentals service temporarily unavailable")
    return {"fundamentals": out, "updatedAt": int(time.time())}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        raw = query.get("symbols", [""])[0]
        symbols = [s.upper() for s in raw.split(",") if _SYMBOL_RE.match(s.strip().upper())]
        if not symbols:
            self._send(400, {"error": "Provide at least one symbol"})
            return
        try:
            body = get_fundamentals(symbols)
        except Exception:
            self._send(503, {"error": "Fundamentals service temporarily unavailable"})
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
