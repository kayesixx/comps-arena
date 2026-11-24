"""Build the comps set: pick peers, compute multiples, and value the target off the peers."""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

from . import sec
from .fundamentals import Fundamentals, extract
from .prices import Quote, quote

FINANCIALS = range(6000, 6800)  # banks, insurers, brokers, REITs: EV/EBITDA means little for them

# Industries the SIC system splits across codes that don't share a prefix. Used only when the
# target's own code (and its neighbours) hold too few listed companies.
RELATED_SIC = [
    {"3021", "3140", "3149", "2300", "2320", "2330", "2340", "3100"},  # footwear, apparel, accessories (Nike)
    {"2080", "2082", "2084", "2085", "2086"},                          # beverages: soft drinks, beer, wine, spirits
    {"7370", "7371", "7372", "7373", "7374"},                          # software and IT services
    {"2833", "2834", "2835", "2836"},                                  # pharma and biotech
    {"5311", "5331", "5399", "5411"},                                  # general merchandise and grocery retail
]
# Filed under clothing codes but really uniform-rental services: never a peer from a wider tier
NOT_GROUP_PEERS = {"CTAS", "UNF"}


@dataclass
class Company:
    ticker: str
    name: str
    cik: int
    sic: str
    sic_name: str
    fx: Fundamentals
    q: Quote

    # all money in USD millions from here on
    @property
    def price(self) -> float:
        return self.q.price

    @property
    def shares_m(self) -> float:
        return (self.fx.shares or 0) / 1e6

    @property
    def market_cap(self) -> float:
        return self.price * self.shares_m

    @property
    def debt(self) -> float:
        return self.fx.debt / 1e6

    @property
    def cash(self) -> float:
        return self.fx.cash / 1e6

    @property
    def minority(self) -> float:
        return self.fx.minority / 1e6

    @property
    def net_debt(self) -> float:
        return self.debt - self.cash

    @property
    def ev(self) -> float:
        return self.market_cap + self.net_debt + self.minority

    @property
    def revenue(self) -> float:
        return self.fx.revenue.value / 1e6

    @property
    def ebitda(self) -> float | None:
        e = self.fx.ebitda
        return e / 1e6 if e is not None else None

    @property
    def net_income(self) -> float | None:
        return self.fx.net_income.value / 1e6 if self.fx.net_income else None

    @property
    def growth(self) -> float | None:
        return self.fx.revenue_growth

    @property
    def margin(self) -> float | None:
        return self.ebitda / self.revenue if self.ebitda is not None and self.revenue > 0 else None

    @property
    def ev_revenue(self) -> float | None:
        return self.ev / self.revenue if self.revenue > 0 else None

    @property
    def ev_ebitda(self) -> float | None:
        return self.ev / self.ebitda if self.ebitda and self.ebitda > 0 else None

    @property
    def pe(self) -> float | None:
        return self.market_cap / self.net_income if self.net_income and self.net_income > 0 else None


MULTIPLES = {
    "EV / Revenue": ("ev_revenue", "revenue"),
    "EV / EBITDA": ("ev_ebitda", "ebitda"),
    "P / E": ("pe", "net_income"),
}


def load(ticker: str) -> Company:
    rec = sec.lookup(ticker)
    sub = sec.submissions(rec["cik"])
    sic = str(sub.get("sic") or "")
    try:
        fx = extract(sec.company_facts(rec["cik"]))
    except (ValueError, sec.ArenaError) as e:
        raise sec.ArenaError(f"{rec['ticker']}: {e}") from e
    if not fx.shares:
        raise sec.ArenaError(f"{rec['ticker']}: no share count in its filings")
    q = quote(rec["ticker"])
    if q.currency != "USD":
        raise sec.ArenaError(f"{rec['ticker']}: trades in {q.currency}, not USD")
    return Company(rec["ticker"], sub.get("name") or rec["name"], rec["cik"], sic, sub.get("sicDescription") or "", fx, q)


def check_allowed(c: Company) -> None:
    if c.sic.isdigit() and int(c.sic) in FINANCIALS:
        raise sec.ArenaError(
            f"{c.ticker} is a financial ({c.sic_name}). Banks, insurers and REITs are banned from the arena: "
            "they're valued on P/B and P/E, not EV/EBITDA."
        )


def suggest_peers(target: Company, n: int = 6, exclude: frozenset = frozenset()) -> list[str]:
    """Listed companies with the same SIC code, closest to the target in revenue."""
    by_cik = sec.primary_ticker_by_cik()
    year = date.today().year - 1
    revs = {**sec.revenue_frame(year - 1), **sec.revenue_frame(year)}

    def scored(codes: list[str]) -> list[tuple[float, str]]:
        ciks = {c for code in codes for c in sec.companies_in_sic(code)}
        return sorted(
            (abs(math.log(revs[c] / 1e6 / target.revenue)), by_cik[c])
            for c in ciks
            if c in by_cik and c != target.cik and revs.get(c, 0) > 0 and target.revenue > 0
        )

    def size_filtered(ranked):
        # Prefer peers within ~20x of the target's revenue; keep the rest only to make up numbers
        close = [r for r in ranked if r[0] <= math.log(20)]
        far = [r for r in ranked if r[0] > math.log(20)]
        return [t for _, t in (close if len(close) >= 3 else close + far[: 3 - len(close) + n])]

    # Tiers: exact industry first, then neighbouring codes, then the related-industry group.
    # A wider tier only fills the places the narrower one couldn't.
    tiers = [[target.sic]]
    if len(target.sic) == 4:
        tiers.append([f"{target.sic[:3]}{i}" for i in range(10)])
    tiers += [sorted(g) for g in RELATED_SIC if target.sic in g]
    picked: list[str] = []
    for depth, codes in enumerate(tiers):
        for t in size_filtered(scored(codes)):
            if depth >= 2 and t in NOT_GROUP_PEERS:
                continue
            if t not in picked and t not in exclude:
                picked.append(t)
        if len(picked) >= n + 2:  # a couple in reserve: some peers drop out (IFRS filers, missing data)
            break
    return picked[: n * 2]


@dataclass
class Stats:
    values: list[float]

    @property
    def ok(self) -> bool:
        return len(self.values) >= 2

    def q(self, p: float) -> float:
        v = sorted(self.values)
        k = (len(v) - 1) * p
        lo, hi = math.floor(k), math.ceil(k)
        return v[lo] + (v[hi] - v[lo]) * (k - lo)

    @property
    def median(self) -> float:
        return statistics.median(self.values)

    @property
    def mean(self) -> float:
        return statistics.mean(self.values)


def peer_stats(peers: list[Company], attr: str) -> Stats:
    return Stats([v for p in peers if (v := getattr(p, attr)) is not None])


@dataclass
class Implied:
    method: str
    low: float
    mid: float
    high: float
    multiple_low: float
    multiple_mid: float
    multiple_high: float


@dataclass
class Fight:
    target: Company
    peers: list[Company]
    dropped: list[str] = field(default_factory=list)

    def implied(self) -> list[Implied]:
        """Target share price implied by the peers' 25th / median / 75th percentile multiples."""
        t, out = self.target, []
        for label, (mult_attr, metric_attr) in MULTIPLES.items():
            s = peer_stats(self.peers, mult_attr)
            metric = getattr(t, metric_attr)
            if not s.ok or metric is None or metric <= 0:
                continue
            ms = (s.q(0.25), s.median, s.q(0.75))
            if label.startswith("EV"):
                prices = [(m * metric - t.net_debt - t.minority) / t.shares_m for m in ms]
            else:
                prices = [m * metric / t.shares_m for m in ms]
            out.append(Implied(label, *prices, *ms))
        return out

    def premium(self, attr: str) -> float | None:
        s = peer_stats(self.peers, attr)
        mine = getattr(self.target, attr)
        if not s.ok or mine is None or s.median <= 0:
            return None
        return mine / s.median - 1


def build(ticker: str, peer_tickers: list[str] | None, n: int, log=print, exclude=()) -> Fight:
    target = load(ticker)
    check_allowed(target)
    auto = peer_tickers is None
    if auto:
        log(f"Scouting fighters in SIC {target.sic} ({target.sic_name})...")
        peer_tickers = suggest_peers(target, n, frozenset(t.upper() for t in exclude))
        if len(peer_tickers) < 3:
            raise sec.ArenaError(
                f"Only {len(peer_tickers)} listed companies share {target.ticker}'s SIC code. "
                "Pick the peers yourself with --peers A,B,C"
            )
    peers, dropped = [], []
    for t in peer_tickers:
        if auto and len(peers) >= n:
            break
        try:
            p = load(t)
            check_allowed(p)
            peers.append(p)
            log(f"  {p.ticker:<6} {p.name}")
        except Exception as e:  # one broken filer shouldn't end the fight
            msg = str(e)
            dropped.append(msg if msg.startswith(t) else f"{t}: {msg}")
    if len(peers) < 2:
        raise sec.ArenaError("Fewer than 2 usable peers. Try --peers with names you choose.\n" + "\n".join(dropped))
    return Fight(target, peers, dropped)
