"""comps TICKER [--peers A,B,C] [--n 6] [--out DIR] [--open]"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from . import arena, chart, excel
from .comps import Fight, build, peer_stats
from .sec import ArenaError

BANNER = r"""
  ___ ___  __  __ ___  ___     _   ___ ___ _  _   _
 / __/ _ \|  \/  | _ \/ __|   /_\ | _ \ __| \| | /_\
| (_| (_) | |\/| |  _/\__ \  / _ \|   / _|| .` |/ _ \
 \___\___/|_|  |_|_|  |___/ /_/ \_\_|_\___|_|\_/_/ \_\
"""


def _x(v):
    return "   NM" if v is None else f"{v:5.1f}x"


def _p(v):
    return "    –" if v is None else f"{v * 100:5.0f}%"


def table(f: Fight) -> str:
    rows = [f"{'':2}{'Ticker':<7}{'Mkt cap $bn':>12}{'Growth':>8}{'Margin':>8}{'EV/Rev':>8}{'EV/EBITDA':>11}{'P/E':>8}"]
    for i, c in enumerate([f.target, *f.peers]):
        mark = "▶ " if i == 0 else "  "
        rows.append(
            f"{mark}{c.ticker:<7}{c.market_cap / 1e3:>12,.1f}{_p(c.growth):>8}{_p(c.margin):>8}"
            f"{_x(c.ev_revenue):>8}{_x(c.ev_ebitda):>11}{_x(c.pe):>8}"
        )
        if i == 0:
            rows.append("  " + "-" * 60)
    med = {a: peer_stats(f.peers, a) for a in ("growth", "margin", "ev_revenue", "ev_ebitda", "pe")}
    m = {a: (s.median if s.ok else None) for a, s in med.items()}
    rows.append("  " + "-" * 60)
    rows.append(
        f"  {'Median':<7}{'':>12}{_p(m['growth']):>8}{_p(m['margin']):>8}"
        f"{_x(m['ev_revenue']):>8}{_x(m['ev_ebitda']):>11}{_x(m['pe']):>8}"
    )
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="comps", description="Trading comps for any US-listed non-financial company.")
    ap.add_argument("ticker")
    ap.add_argument("--peers", help="comma-separated peer tickers (default: picked by SIC code and size)")
    ap.add_argument("--n", type=int, default=6, help="number of peers to pick automatically (default 6)")
    ap.add_argument("--out", type=Path, default=Path("out"), help="output folder (default ./out)")
    ap.add_argument("--open", action="store_true", help="open the arena page when done")
    a = ap.parse_args(argv)

    print(BANNER)
    peers = [p.strip() for p in a.peers.split(",") if p.strip()] if a.peers else None
    try:
        print(f"Loading {a.ticker.upper()}...")
        f = build(a.ticker, peers, a.n)
    except ArenaError as e:
        print(f"\n✖ {e}", file=sys.stderr)
        return 1

    out = a.out / f.target.ticker
    out.mkdir(parents=True, exist_ok=True)
    png = chart.football_field(f, out / "football_field.png")
    excel.write(f, out / "comps.xlsx", png)
    arena.write(f, out / "arena.html")

    print("\n" + table(f))
    print()
    for i in f.implied():
        print(f"  {i.method:<13} implies ${i.low:,.2f} – ${i.high:,.2f}  (median ${i.mid:,.2f})")
    print(f"  {'Trading at':<13} ${f.target.price:,.2f}")
    if f.dropped:
        print("\n  Left out:\n" + "\n".join("    " + d.rstrip(".") for d in f.dropped))
    print(f"\n  {arena._verdict(f)}\n")
    print(f"  Workbook: {(out / 'comps.xlsx').resolve()}")
    print(f"  Arena:    {(out / 'arena.html').resolve()}")
    if a.open:
        subprocess.Popen(["xdg-open", str(out / "arena.html")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
