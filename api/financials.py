"""Vercel serverless function: full fundamentals for one ticker.

Real figures from SEC EDGAR company facts (10-K / 10-Q): ten years of
annuals, twelve quarters, ten years of ratios, live metrics, and a peer
comparison. Nothing here is seeded or estimated.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import lib.edgar as edgar


def get_financials(symbol):
    symbol = symbol.upper()
    peer_symbols = edgar.peers_for(symbol)
    # Warm the EDGAR + price caches for the company and its peers in parallel,
    # so the wall time is one slow fetch, not the sum of them.
    loaded = {}

    def _warm(sym, kind):
        try:
            loaded[(sym, kind)] = edgar.facts(sym) if kind == "facts" else edgar.live_price(sym)
        except Exception:
            loaded[(sym, kind)] = None

    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = [executor.submit(_warm, sym, kind)
                for sym in [symbol, *peer_symbols] for kind in ("facts", "price")]
        for job in as_completed(jobs):
            pass
    price = loaded.get((symbol, "price"))
    if not price or not price.get("price"):
        try:
            price = edgar.live_price(symbol)
        except Exception:
            # No live price: if the ticker has no SEC filings either, it is
            # an unknown ticker (404), not a transient outage (503).
            edgar.facts(symbol)
            raise
    metrics = edgar.metrics(symbol, price["price"])
    metrics["changePercent"] = price["changePercent"]
    stmts = edgar.statements(symbol)
    peers = []
    for peer in peer_symbols:
        peer_price = loaded.get((peer, "price"))
        if not peer_price or not peer_price.get("price"):
            continue
        try:
            peer_metrics = edgar.metrics(peer, peer_price["price"])
            peer_metrics["changePercent"] = peer_price["changePercent"]
            peers.append(peer_metrics)
        except Exception:
            pass
    peers.sort(key=lambda p: p.get("cap") or 0, reverse=True)
    pc = edgar.pros_cons(metrics, stmts["annual"], stmts["ratios"], peers)
    entry = edgar.universe_entry(symbol)
    return {
        "symbol": symbol,
        "name": edgar.company_name(symbol),
        "sector": entry["sector"] if entry else None,
        "price": price["price"],
        "changePercent": price["changePercent"],
        "metrics": metrics,
        "annual": stmts["annual"],
        "quarterly": stmts["quarterly"],
        "ratios": stmts["ratios"],
        "peers": peers,
        "pros": pc["pros"],
        "cons": pc["cons"],
        "asOf": int(time.time()),
        "source": "SEC EDGAR company facts + Yahoo Finance price",
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        import urllib.parse
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        symbol = query.get("symbol", [""])[0].upper()
        if not symbol.isalnum():
            self._send(400, {"error": "Provide a ticker symbol"})
            return
        try:
            body = get_financials(symbol)
        except ValueError as exc:
            self._send(404, {"error": str(exc)})
            return
        except Exception:
            self._send(503, {"error": "Financials service temporarily unavailable"})
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
