"""SEC EDGAR access: ticker lookup, company facts (XBRL), revenue frames and SIC peer lists.

The SEC asks automated tools to identify themselves with a contact email. The user agent
is read from ~/.config/comps-arena/user_agent (or COMPS_ARENA_UA) and is never stored in
the repo. Responses are cached under ~/.cache/comps-arena.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("COMPS_ARENA_CACHE", Path.home() / ".cache" / "comps-arena"))
UA_FILE = Path.home() / ".config" / "comps-arena" / "user_agent"

DAY = 86400
_last_sec_call = 0.0


class ArenaError(Exception):
    """A problem worth showing to the user as-is."""


def user_agent() -> str:
    ua = os.environ.get("COMPS_ARENA_UA") or (UA_FILE.read_text().strip() if UA_FILE.exists() else "")
    if "@" not in ua:
        raise ArenaError(
            "The SEC needs a contact email in each request.\n"
            f"Put 'Comps Arena you@example.com' in {UA_FILE} (or set COMPS_ARENA_UA)."
        )
    return ua


def _fetch(url: str, headers: dict, sec: bool) -> bytes:
    global _last_sec_call
    if sec:  # SEC fair access: stay well under 10 requests a second
        wait = 0.15 - (time.time() - _last_sec_call)
        if wait > 0:
            time.sleep(wait)
        _last_sec_call = time.time()
    req = urllib.request.Request(url, headers={**headers, "Accept-Encoding": "gzip"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            if attempt == 2:
                raise
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError("unreachable")


def cached(url: str, ttl: int, *, sec: bool = True, headers: dict | None = None) -> bytes:
    key = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])[:180]
    path = CACHE / key
    if path.exists() and time.time() - path.stat().st_mtime < ttl:
        return path.read_bytes()
    hdrs = headers or {"User-Agent": user_agent()}
    body = _fetch(url, hdrs, sec)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def get_json(url: str, ttl: int) -> dict:
    return json.loads(cached(url, ttl))


# ---------------------------------------------------------------- tickers

LISTED = {"NYSE", "Nasdaq", "CBOE", "NYSE American", "NYSE Arca"}


def ticker_table() -> dict[str, dict]:
    """ticker -> {cik, name, exchange} for exchange-listed companies."""
    raw = get_json("https://www.sec.gov/files/company_tickers_exchange.json", 7 * DAY)
    fields = raw["fields"]
    out = {}
    for row in raw["data"]:
        rec = dict(zip(fields, row))
        if rec.get("exchange") not in LISTED or not rec.get("ticker"):
            continue
        out.setdefault(rec["ticker"].upper(), {"cik": int(rec["cik"]), "name": rec["name"], "exchange": rec["exchange"]})
    return out


def lookup(ticker: str) -> dict:
    table = ticker_table()
    base = ticker.upper().strip()
    for t in (base, base.replace(".", "-"), base.replace("-", "."), base.replace("/", "-")):
        if t in table:
            return {"ticker": t, **table[t]}
    raise ArenaError(f"{ticker} isn't a US exchange-listed ticker the SEC knows about.")


def primary_ticker_by_cik() -> dict[int, str]:
    out: dict[int, str] = {}
    for t, rec in ticker_table().items():
        out.setdefault(rec["cik"], t)
    return out


# ---------------------------------------------------------------- filings data


def submissions(cik: int) -> dict:
    return get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", 7 * DAY)


def company_facts(cik: int) -> dict:
    try:
        return get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", DAY)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ArenaError("no XBRL financial data on EDGAR") from e
        raise


def revenue_frame(year: int) -> dict[int, float]:
    """cik -> calendar-year revenue, from SEC XBRL frames (one call covers every filer)."""
    out: dict[int, float] = {}
    for tag in ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"):
        try:
            raw = get_json(f"https://data.sec.gov/api/xbrl/frames/us-gaap/{tag}/USD/CY{year}.json", 30 * DAY)
        except urllib.error.HTTPError:
            continue
        for row in raw.get("data", []):
            cik, val = int(row["cik"]), float(row["val"])
            if val > out.get(cik, 0):
                out[cik] = val
    return out


def companies_in_sic(sic: str, max_pages: int = 12) -> list[int]:
    """CIKs of every company EDGAR files under a 4-digit SIC code (live and dead)."""
    ciks: list[int] = []
    for page in range(max_pages):
        url = (
            "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            f"&SIC={sic}&type=10-K&owner=include&count=100&start={page * 100}&output=atom"
        )
        body = cached(url, 30 * DAY).decode("utf-8", "replace")
        found = [int(c) for c in re.findall(r"<cik>(\d+)</cik>", body)]
        ciks.extend(found)
        if len(found) < 100:
            break
    return ciks
