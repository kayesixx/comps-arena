"""Share prices from Yahoo Finance's public chart endpoint (no key needed)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from .sec import ArenaError, cached

YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?range=1y&interval=1d"
HEADERS = {"User-Agent": "Mozilla/5.0"}


@dataclass
class Quote:
    price: float
    currency: str
    low_52w: float
    high_52w: float


def quote(ticker: str) -> Quote:
    symbol = ticker.replace(".", "-")
    raw = json.loads(cached(YAHOO.format(symbol), 3600, sec=False, headers=HEADERS))
    result = (raw.get("chart") or {}).get("result")
    if not result:
        raise ArenaError(f"no price found for {ticker}")
    meta = result[0]["meta"]
    closes = [c for c in result[0]["indicators"]["quote"][0].get("close", []) if c]
    price = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    if not price:
        raise ArenaError(f"no price found for {ticker}")
    return Quote(
        price=float(price),
        currency=meta.get("currency", "USD"),
        low_52w=float(min(closes)) if closes else float(price),
        high_52w=float(max(closes)) if closes else float(price),
    )
