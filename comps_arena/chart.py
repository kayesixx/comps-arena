"""Football field chart: implied share price ranges against the current price."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .comps import Fight  # noqa: E402


def football_field(fight: Fight, path: Path) -> Path | None:
    t = fight.target
    bars = [(f"{i.method}\n({i.multiple_low:.1f}x – {i.multiple_high:.1f}x)", i.low, i.high, i.mid) for i in fight.implied()]
    bars = [b for b in bars if b[2] > 0]
    if not bars:
        return None
    bars.append(("52-week trading range", t.q.low_52w, t.q.high_52w, None))
    bars.reverse()

    fig, ax = plt.subplots(figsize=(9, 0.9 * len(bars) + 1.4), dpi=150)
    for y, (label, lo, hi, mid) in enumerate(bars):
        lo = max(lo, 0)
        color = "#8EA9DB" if mid is not None else "#BFBFBF"
        ax.barh(y, hi - lo, left=lo, height=0.55, color=color, edgecolor="#1F3864", linewidth=0.8)
        ax.text(lo, y, f"${lo:,.0f} ", va="center", ha="right", fontsize=8)
        ax.text(hi, y, f" ${hi:,.0f}", va="center", ha="left", fontsize=8)
        if mid is not None:
            ax.plot([mid, mid], [y - 0.27, y + 0.27], color="#1F3864", linewidth=1.5)
    ax.axvline(t.price, color="#C00000", linestyle="--", linewidth=1.2)
    ax.text(t.price, len(bars) - 0.45, f"Current ${t.price:,.2f}", color="#C00000", ha="center", fontsize=8)
    ax.set_yticks(range(len(bars)), [b[0] for b in bars], fontsize=8)
    ax.set_ylim(-0.6, len(bars) - 0.2)
    xmax = max(b[2] for b in bars + [("", 0, t.price, None)])
    ax.set_xlim(0, xmax * 1.18)
    ax.xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("${x:,.0f}"))
    ax.tick_params(axis="x", labelsize=8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.set_title(
        f"{t.name} ({t.ticker}): implied share price, peer 25th–75th percentile (line = median)",
        fontsize=9, loc="left",
    )
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path
