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

# How many peers get a full live metric fetch. The peer map is cap-sorted,
# so the top 7 are the largest, most relevant peers — and 7 still satisfies
# the "at least seven peers" requirement. Fetching live EDGAR facts +
# metrics for all 10-12 peers pushed the handler past Vercel's 10-second
# function limit (503s); the rest of the peers use their pre-built static
# metrics (same shape, build-time values) instead of a live fetch.
LIVE_PEER_COUNT = 7


def _static_financials(symbol):
    """The pre-built data/financials/{symbol}.json for this ticker, if the
    static build has one. Same shape as this endpoint's response."""
    safe = "".join(c if c.isalnum() or c == "." else "_" for c in symbol)
    path = os.path.join(os.path.dirname(__file__), "..", "data", "financials", safe + ".json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def get_financials(symbol):
    symbol = symbol.upper()
    try:
        return _get_financials_live(symbol)
    except ValueError:
        # Unknown ticker (no SEC filings): no static file can save it.
        raise
    except Exception:
        # Transient EDGAR/Yahoo outage or a slow fetch: serve the pre-built
        # static file (same shape) instead of a 503. The profile's 60-second
        # quote refresh corrects the build-time price.
        static = _static_financials(symbol)
        if static is None:
            raise
        static["source"] = "Static build (live source unavailable) — SEC EDGAR company facts + Yahoo Finance price"
        return static


def _get_financials_live(symbol):
    peer_symbols = edgar.peers_for(symbol)
    live_peers = peer_symbols[:LIVE_PEER_COUNT]
    # Warm the EDGAR + price caches for the company and its top peers in
    # parallel, so the wall time is one slow fetch, not the sum of them.
    # Peers beyond the live cap do not get warmed: their metrics come from
    # their pre-built static files.
    loaded = {}

    def _warm(sym, kind):
        try:
            loaded[(sym, kind)] = edgar.facts(sym) if kind == "facts" else edgar.live_price(sym)
        except Exception:
            loaded[(sym, kind)] = None

    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs = [executor.submit(_warm, sym, kind)
                for sym in [symbol, *live_peers] for kind in ("facts", "price")]
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
    # Main metrics + statements and the top peers' metrics in parallel.
    with ThreadPoolExecutor(max_workers=8) as executor:
        main_future = executor.submit(lambda: (edgar.metrics(symbol, price["price"]), edgar.statements(symbol)))
        peer_futures = {peer: executor.submit(_peer_metrics_live, peer, loaded) for peer in live_peers}
        metrics, stmts = main_future.result()
        peer_metrics = {}
        for peer, future in peer_futures.items():
            result = future.result()
            if result is not None:
                peer_metrics[peer] = result
    metrics["changePercent"] = price["changePercent"]
    peers = []
    for peer in peer_symbols:
        if peer in peer_metrics:
            peers.append(peer_metrics[peer])
            continue
        # Beyond the live cap: pre-built static metrics, same shape.
        static = _static_financials(peer)
        if static and static.get("metrics"):
            peers.append(static["metrics"])
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
        "quarterly_ratios": stmts["quarterly_ratios"],
        "peers": peers,
        "pros": pc["pros"],
        "cons": pc["cons"],
        "asOf": int(time.time()),
        "source": "SEC EDGAR company facts + Yahoo Finance price",
    }


def _peer_metrics_live(peer, loaded):
    peer_price = loaded.get((peer, "price"))
    if not peer_price or not peer_price.get("price"):
        return None
    try:
        peer_metrics = edgar.metrics(peer, peer_price["price"])
        peer_metrics["changePercent"] = peer_price["changePercent"]
        return peer_metrics
    except Exception:
        return None


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
