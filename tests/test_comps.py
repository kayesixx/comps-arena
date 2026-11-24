from datetime import date

import pytest

from comps_arena.comps import Stats
from comps_arena.fundamentals import Duration, Fundamentals, _shares, ltm


def d(start, end, val):
    return Duration(date.fromisoformat(start), date.fromisoformat(end), val, "2026-01-01")


def test_ltm_uses_fiscal_year_when_latest():
    e = [d("2025-01-01", "2025-12-31", 100), d("2025-01-01", "2025-09-30", 70)]
    r = ltm(e)
    assert r.value == 100 and r.method == "fiscal year"


def test_ltm_fy_plus_ytd_minus_prior_ytd():
    e = [
        d("2025-01-01", "2025-12-31", 100),  # FY25
        d("2026-01-01", "2026-06-30", 60),   # H1 26
        d("2025-01-01", "2025-06-30", 45),   # H1 25
        d("2026-04-01", "2026-06-30", 31),   # Q2 26, ignored in favour of YTD
    ]
    r = ltm(e)
    assert r.value == pytest.approx(115) and r.end == date(2026, 6, 30)


def test_ltm_sums_four_quarters_when_no_ytd():
    e = [
        d("2025-07-01", "2025-09-30", 10), d("2025-10-01", "2025-12-31", 11),
        d("2026-01-01", "2026-03-31", 12), d("2026-04-01", "2026-06-30", 13),
    ]
    assert ltm(e).value == 46


def test_ltm_as_of_gives_prior_year():
    e = [d("2024-01-01", "2024-12-31", 80), d("2025-01-01", "2025-12-31", 100)]
    assert ltm(e, as_of=date(2025, 1, 15)).value == 80


def _facts(cover=None, diluted=None):
    f = {"facts": {"us-gaap": {}, "dei": {}}}
    if cover:
        f["facts"]["dei"]["EntityCommonStockSharesOutstanding"] = {
            "units": {"shares": [{"end": "2026-07-20", "val": cover, "form": "10-Q", "filed": "2026-07-25"}]}}
    if diluted:
        f["facts"]["us-gaap"]["WeightedAverageNumberOfDilutedSharesOutstanding"] = {
            "units": {"shares": [{"start": "2026-04-01", "end": "2026-06-30", "val": diluted, "form": "10-Q", "filed": "2026-07-25"}]}}
    return f


def test_shares_prefers_cover_page():
    fx = Fundamentals(period_end=date(2026, 6, 30))
    _shares(_facts(cover=1000, diluted=1010), fx)
    assert fx.shares == 1000


def test_shares_falls_back_when_cover_is_one_class():
    fx = Fundamentals(period_end=date(2026, 6, 30))
    _shares(_facts(cover=300, diluted=1500), fx)
    assert fx.shares == 1500


def test_quartiles_match_excel():
    s = Stats([11.2, 12.6, 14.5, 21.6])
    assert s.median == pytest.approx(13.55)
    assert s.q(0.25) == pytest.approx(12.25)  # Excel QUARTILE(...,1)
    assert s.q(0.75) == pytest.approx(16.275)
