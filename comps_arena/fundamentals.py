"""Turn SEC XBRL company facts into LTM financials and a latest balance sheet.

LTM (last twelve months) = last fiscal year + current year-to-date - prior year-to-date.
That is the standard banker's calculation, and it works on income statement and cash flow
tags alike because 10-Qs always report year-to-date figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

REVENUE = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
]
OPERATING_INCOME = ["OperatingIncomeLoss"]
DA = [
    "DepreciationDepletionAndAmortization",
    "DepreciationAndAmortization",
    "DepreciationAmortizationAndAccretionNet",
    "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
]
NET_INCOME = ["NetIncomeLoss", "ProfitLoss"]

CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
SHORT_INVESTMENTS = [
    "ShortTermInvestments",
    "MarketableSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
    "AvailableForSaleSecuritiesDebtSecurities",
]
LTD_NONCURRENT = ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"]
LTD_TOTAL = ["LongTermDebt"]
DEBT_CURRENT = ["DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"]
DEBT_CURRENT_PARTS = ["LongTermDebtCurrent", "ShortTermBorrowings", "CommercialPaper"]
MINORITY = ["MinorityInterest"]

ANNUAL = (350, 380)
FORMS = {"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "8-K"}


@dataclass
class Duration:
    start: date
    end: date
    val: float
    filed: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass
class LTM:
    value: float
    end: date
    method: str


@dataclass
class Fundamentals:
    period_end: date | None = None
    revenue: LTM | None = None
    revenue_prior: LTM | None = None
    operating_income: LTM | None = None
    da: LTM | None = None
    net_income: LTM | None = None
    bs_date: date | None = None
    cash: float = 0.0
    debt: float = 0.0
    minority: float = 0.0
    shares: float | None = None
    shares_date: date | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ebitda(self) -> float | None:
        if self.operating_income and self.da:
            return self.operating_income.value + self.da.value
        return None

    @property
    def net_debt(self) -> float:
        return self.debt - self.cash

    @property
    def revenue_growth(self) -> float | None:
        if self.revenue and self.revenue_prior and self.revenue_prior.value > 0:
            return self.revenue.value / self.revenue_prior.value - 1
        return None


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _units(facts: dict, tag: str, unit: str = "USD") -> list[dict]:
    for ns in ("us-gaap", "dei"):
        node = facts.get("facts", {}).get(ns, {}).get(tag)
        if node and unit in node.get("units", {}):
            return node["units"][unit]
    return []


def durations(facts: dict, tags: list[str]) -> list[Duration]:
    """Duration facts across tags. For each (start, end) the earliest tag in the list wins,
    and within a tag the most recently filed figure wins (so restatements replace old numbers)."""
    best: dict[tuple, tuple[int, Duration]] = {}
    for rank, tag in enumerate(tags):
        for f in _units(facts, tag):
            if "start" not in f or f.get("form") not in FORMS:
                continue
            d = Duration(_d(f["start"]), _d(f["end"]), float(f["val"]), f.get("filed", ""))
            key = (d.start, d.end)
            cur = best.get(key)
            if cur is None or rank < cur[0] or (rank == cur[0] and d.filed > cur[1].filed):
                best[key] = (rank, d)
    return [d for _, d in best.values()]


def _near(a: date, b: date, days: int = 12) -> bool:
    return abs((a - b).days) <= days


def ltm(entries: list[Duration], as_of: date | None = None) -> LTM | None:
    """Last-twelve-months value as of the latest period end on or before `as_of`."""
    pool = [e for e in entries if as_of is None or e.end <= as_of]
    if not pool:
        return None
    latest = max(e.end for e in pool)
    at_latest = [e for e in pool if e.end == latest]

    annual = [e for e in at_latest if ANNUAL[0] <= e.days <= ANNUAL[1]]
    if annual:
        return LTM(annual[0].val, latest, "fiscal year")

    # FY + YTD - prior YTD
    ytds = sorted((e for e in at_latest if e.days < ANNUAL[0]), key=lambda e: -e.days)
    for ytd in ytds:
        fy = [e for e in pool if ANNUAL[0] <= e.days <= ANNUAL[1] and _near(e.end, ytd.start - timedelta(days=1))]
        prior = [
            e for e in pool
            if _near(e.end, ytd.end - timedelta(days=365)) and abs(e.days - ytd.days) <= 12
        ]
        if fy and prior:
            return LTM(fy[0].val + ytd.val - prior[0].val, latest, "FY + YTD - prior YTD")

    # Sum of the four latest back-to-back quarters
    quarters = {e.end: e for e in pool if 80 <= e.days <= 100}
    chain, end = [], latest
    while end in quarters and len(chain) < 4:
        q = quarters[end]
        chain.append(q)
        prev = [k for k in quarters if _near(k, q.start - timedelta(days=1), 5)]
        if not prev:
            break
        end = prev[0]
    if len(chain) == 4:
        return LTM(sum(q.val for q in chain), latest, "sum of 4 quarters")

    # Fall back to the latest full fiscal year
    annuals = [e for e in pool if ANNUAL[0] <= e.days <= ANNUAL[1]]
    if annuals:
        a = max(annuals, key=lambda e: e.end)
        return LTM(a.val, a.end, "latest fiscal year (stale)")
    return None


def instants(facts: dict, tags: list[str], unit: str = "USD") -> dict[date, float]:
    """end date -> value for point-in-time facts; earliest tag in the list wins."""
    out: dict[date, tuple[int, str, float]] = {}
    for rank, tag in enumerate(tags):
        for f in _units(facts, tag, unit):
            if "start" in f or f.get("form") not in FORMS:
                continue
            end, filed = _d(f["end"]), f.get("filed", "")
            cur = out.get(end)
            if cur is None or rank < cur[0] or (rank == cur[0] and filed > cur[1]):
                out[end] = (rank, filed, float(f["val"]))
    return {k: v[2] for k, v in out.items()}


def _at(series: dict[date, float], when: date) -> float | None:
    return series.get(when)


def extract(facts: dict) -> Fundamentals:
    if "us-gaap" not in facts.get("facts", {}):
        raise ValueError("files under IFRS, not US GAAP")
    fx = Fundamentals()

    rev = durations(facts, REVENUE)
    fx.revenue = ltm(rev)
    if fx.revenue is None:
        raise ValueError("no revenue figures found")
    fx.period_end = fx.revenue.end
    fx.revenue_prior = ltm(rev, as_of=fx.period_end - timedelta(days=350))
    if fx.revenue_prior and not _near(fx.revenue_prior.end, fx.period_end - timedelta(days=365), 20):
        fx.revenue_prior = None

    for attr, tags in (("operating_income", OPERATING_INCOME), ("da", DA), ("net_income", NET_INCOME)):
        val = ltm(durations(facts, tags))
        if val and not _near(val.end, fx.period_end, 100):
            # A figure from another period would silently corrupt EBITDA or P/E: drop it
            if attr != "da":
                fx.notes.append(f"latest {attr.replace('_', ' ')} is from {val.end}, so it is left out")
            val = None
        setattr(fx, attr, val)
    if fx.operating_income is None:
        # No operating income line (Nike reports straight to pre-tax): EBIT ~ pre-tax income + net interest
        pretax = ltm(durations(facts, ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                                        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]))
        interest = ltm(durations(facts, ["InterestIncomeExpenseNonoperatingNet", "InterestIncomeExpenseNet"]))
        if pretax and _near(pretax.end, fx.period_end, 100):
            net_interest = interest.value if interest and interest.end == pretax.end else 0.0
            fx.operating_income = LTM(pretax.value - net_interest, pretax.end, pretax.method)
            fx.notes.append("no operating income line: EBIT rebuilt as pre-tax income + net interest expense")
    if fx.da is None:  # some filers (Alphabet) report depreciation and amortisation separately
        dep = ltm(durations(facts, ["Depreciation"]))
        amort = ltm(durations(facts, ["AmortizationOfIntangibleAssets"]))
        if dep and _near(dep.end, fx.period_end, 100):
            amort_val = amort.value if amort and amort.end == dep.end else 0.0
            fx.da = LTM(dep.value + amort_val, dep.end, dep.method + " (depreciation + amortisation)")
    if fx.da is None:
        fx.notes.append("no D&A tag found, so no EBITDA")
    if fx.operating_income is None:
        fx.notes.append("no operating income figure found, so no EBITDA")

    # Balance sheet at the latest date that reports cash
    cash = instants(facts, CASH)
    if cash:
        fx.bs_date = max(cash)
        fx.cash = cash[fx.bs_date]
        sti = _at(instants(facts, SHORT_INVESTMENTS), fx.bs_date)
        if sti:
            fx.cash += sti
        noncurrent = _at(instants(facts, LTD_NONCURRENT), fx.bs_date)
        current = _at(instants(facts, DEBT_CURRENT), fx.bs_date)
        if current is None:
            parts = [_at(instants(facts, [t]), fx.bs_date) for t in DEBT_CURRENT_PARTS]
            current = sum(p for p in parts if p) if any(parts) else None
        if noncurrent is not None:
            fx.debt = noncurrent + (current or 0)
        else:
            total = _at(instants(facts, LTD_TOTAL), fx.bs_date)
            extra = [_at(instants(facts, [t]), fx.bs_date) for t in ("ShortTermBorrowings", "CommercialPaper")]
            fx.debt = (total or 0) + sum(e for e in extra if e)
            if total is None and not any(extra):
                carrying = _at(instants(facts, ["DebtInstrumentCarryingAmount"]), fx.bs_date)
                if carrying:
                    fx.debt = carrying
                    fx.notes.append("debt from DebtInstrumentCarryingAmount")
                else:
                    fx.notes.append(
                        "no standard debt tags at the balance sheet date, so debt is taken as zero: right for a debt-free "
                        "company, but check the 10-Q if it has debt under custom tags (e.g. a captive finance arm)"
                    )
        fx.minority = _at(instants(facts, MINORITY), fx.bs_date) or 0.0
    else:
        fx.notes.append("no cash tag found, so net debt is unreliable")

    _shares(facts, fx)
    return fx


def _shares(facts: dict, fx: Fundamentals) -> None:
    """Cover-page share count, checked against the diluted weighted average.

    Companies with several share classes (Nike, Alphabet) often tag the cover page per class,
    which the SEC's standard data leaves out, so the cover figure can cover one class only.
    The diluted weighted average always covers every class."""
    wad = durations_units(facts, "WeightedAverageNumberOfDilutedSharesOutstanding", "shares")
    diluted = None
    if wad:
        last_end = max(e.end for e in wad)
        diluted = min((e for e in wad if e.end == last_end), key=lambda e: e.days)

    recent = lambda d: fx.period_end is None or (fx.period_end - d).days < 200  # noqa: E731
    for tags, label in ((["EntityCommonStockSharesOutstanding"], None), (["CommonStockSharesOutstanding"], "balance sheet")):
        series = instants(facts, tags, "shares")
        if not series:
            continue
        when = max(series)
        val = series[when]
        if not recent(when):
            continue
        if diluted and recent(diluted.end) and val < 0.87 * diluted.val:
            continue  # looks like one share class only
        fx.shares, fx.shares_date = val, when
        if label:
            fx.notes.append(f"shares from the {label}")
        return
    if diluted:
        fx.shares, fx.shares_date = diluted.val, diluted.end
        fx.notes.append("shares = latest diluted weighted average (covers all share classes)")


def durations_units(facts: dict, tag: str, unit: str) -> list[Duration]:
    out = []
    for f in _units(facts, tag, unit):
        if "start" in f and f.get("form") in FORMS:
            out.append(Duration(_d(f["start"]), _d(f["end"]), float(f["val"]), f.get("filed", "")))
    return out
