"""Bank-style trading comps workbook.

Conventions: blue font = hard-coded input from filings or market data, black = formula.
Multiples and statistics are live Excel formulas, so the workbook can be audited and edited.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .comps import Company, Fight

BLUE = Font(name="Arial", size=9, color="0000CC")
BLACK = Font(name="Arial", size=9)
BOLD = Font(name="Arial", size=9, bold=True)
WHITE_BOLD = Font(name="Arial", size=9, bold=True, color="FFFFFF")
TITLE = Font(name="Arial", size=12, bold=True)
NAVY = PatternFill("solid", fgColor="1F3864")
TARGET_FILL = PatternFill("solid", fgColor="FFF2CC")
STAT_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="808080")

MILLIONS = '#,##0;(#,##0);"–"'
PRICE = '$#,##0.00'
MULTIPLE = '0.0"x";(0.0"x");"–"'
PCT = '0.0%;(0.0%);"–"'

# column -> (header, kind, number format)
COLS = [
    ("Company", "name", None),
    ("Ticker", "ticker", None),
    ("Share price ($)", "in", PRICE),
    ("Diluted shares (m)", "in", MILLIONS),
    ("Market cap ($m)", "f", MILLIONS),
    ("Debt ($m)", "in", MILLIONS),
    ("Cash & ST inv. ($m)", "in", MILLIONS),
    ("Minority int. ($m)", "in", MILLIONS),
    ("Enterprise value ($m)", "f", MILLIONS),
    ("LTM revenue ($m)", "in", MILLIONS),
    ("LTM EBITDA ($m)", "in", MILLIONS),
    ("LTM net income ($m)", "in", MILLIONS),
    ("Revenue growth", "in", PCT),
    ("EBITDA margin", "f", PCT),
    ("EV / Revenue", "f", MULTIPLE),
    ("EV / EBITDA", "f", MULTIPLE),
    ("P / E", "f", MULTIPLE),
]
L = {h: get_column_letter(i + 1) for i, (h, _, _) in enumerate(COLS)}


def _inputs(c: Company) -> dict[str, object]:
    return {
        "Company": c.name,
        "Ticker": c.ticker,
        "Share price ($)": c.price,
        "Diluted shares (m)": c.shares_m,
        "Debt ($m)": c.debt,
        "Cash & ST inv. ($m)": c.cash,
        "Minority int. ($m)": c.minority,
        "LTM revenue ($m)": c.revenue,
        "LTM EBITDA ($m)": c.ebitda,
        "LTM net income ($m)": c.net_income,
        "Revenue growth": c.growth,
    }


def _formulas(r: int) -> dict[str, str]:
    g = {h: f"{L[h]}{r}" for h in L}
    return {
        "Market cap ($m)": f"={g['Share price ($)']}*{g['Diluted shares (m)']}",
        "Enterprise value ($m)": f"={g['Market cap ($m)']}+{g['Debt ($m)']}-{g['Cash & ST inv. ($m)']}+{g['Minority int. ($m)']}",
        "EBITDA margin": f'=IF(AND(ISNUMBER({g["LTM EBITDA ($m)"]}),{g["LTM revenue ($m)"]}>0),{g["LTM EBITDA ($m)"]}/{g["LTM revenue ($m)"]},"NM")',
        "EV / Revenue": f'=IF({g["LTM revenue ($m)"]}>0,{g["Enterprise value ($m)"]}/{g["LTM revenue ($m)"]},"NM")',
        "EV / EBITDA": f'=IF(AND(ISNUMBER({g["LTM EBITDA ($m)"]}),N({g["LTM EBITDA ($m)"]})>0),{g["Enterprise value ($m)"]}/{g["LTM EBITDA ($m)"]},"NM")',
        "P / E": f'=IF(AND(ISNUMBER({g["LTM net income ($m)"]}),N({g["LTM net income ($m)"]})>0),{g["Market cap ($m)"]}/{g["LTM net income ($m)"]},"NM")',
    }


def _write_row(ws, r: int, c: Company, fill=None) -> None:
    vals, forms = _inputs(c), _formulas(r)
    for i, (h, kind, fmt) in enumerate(COLS, start=1):
        cell = ws.cell(row=r, column=i)
        if h in forms:
            cell.value, cell.font = forms[h], BLACK
        else:
            v = vals.get(h)
            cell.value = "NM" if v is None else v
            cell.font = BLUE if kind == "in" else BOLD if h == "Company" else BLACK
        if fmt:
            cell.number_format = fmt
            cell.alignment = Alignment(horizontal="right")
        if fill:
            cell.fill = fill


def write(fight: Fight, path: Path, chart_png: Path | None) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Comps"
    t = fight.target

    ws["A1"] = f"{t.name} ({t.ticker}): trading comparables"
    ws["A1"].font = TITLE
    ws["A2"] = (
        f"USD millions except per-share data. LTM to each company's latest filing; prices as of {date.today():%d %b %Y}. "
        "Blue = input from SEC filings / market data, black = formula."
    )
    ws["A2"].font = Font(name="Arial", size=8, italic=True, color="595959")

    hdr = 4
    for i, (h, _, _) in enumerate(COLS, start=1):
        cell = ws.cell(row=hdr, column=i, value=h)
        cell.font, cell.fill = WHITE_BOLD, NAVY
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[hdr].height = 30

    ws.cell(row=hdr + 1, column=1, value="Target").font = BOLD
    _write_row(ws, hdr + 2, t, TARGET_FILL)

    ws.cell(row=hdr + 4, column=1, value="Peers").font = BOLD
    first = hdr + 5
    for k, p in enumerate(fight.peers):
        _write_row(ws, first + k, p)
    last = first + len(fight.peers) - 1
    for i in range(1, len(COLS) + 1):
        ws.cell(row=last, column=i).border = Border(bottom=THIN)

    stats_at = {}
    stat_rows = [
        ("Maximum", "MAX({r})"),
        ("75th percentile", "QUARTILE({r},3)"),
        ("Median", "MEDIAN({r})"),
        ("Mean", "AVERAGE({r})"),
        ("25th percentile", "QUARTILE({r},1)"),
        ("Minimum", "MIN({r})"),
    ]
    for k, (label, fn) in enumerate(stat_rows):
        r = last + 2 + k
        stats_at[label] = r
        ws.cell(row=r, column=1, value=label).font = BOLD
        for i, (h, _, fmt) in enumerate(COLS, start=1):
            cell = ws.cell(row=r, column=i)
            cell.fill = STAT_FILL
            if h in ("Revenue growth", "EBITDA margin", "EV / Revenue", "EV / EBITDA", "P / E"):
                col = L[h]
                cell.value = "=IFERROR(" + fn.format(r=f"{col}{first}:{col}{last}") + ',"NM")'
                cell.font, cell.number_format = BOLD, fmt
                cell.alignment = Alignment(horizontal="right")

    widths = [30, 7, 10, 10, 12, 10, 10, 10, 12, 11, 11, 11, 9, 9, 9, 9, 8]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=hdr + 1, column=3)
    ws.sheet_view.showGridLines = False

    _valuation(wb, fight, hdr + 2, stats_at, chart_png)
    _notes(wb, fight)
    wb.save(path)


def _valuation(wb, fight: Fight, trow: int, stats_at: dict, chart_png: Path | None) -> None:
    ws = wb.create_sheet("Valuation")
    t = fight.target
    ws["A1"] = f"{t.ticker}: implied share price from peer multiples"
    ws["A1"].font = TITLE
    heads = ["Method", "Target metric ($m)", "25th pct multiple", "Median multiple", "75th pct multiple",
             "Implied price: low", "Implied price: mid", "Implied price: high", "Current price", "Upside at median"]
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=3, column=i, value=h)
        c.font, c.fill = WHITE_BOLD, NAVY
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    ws.row_dimensions[3].height = 30

    C = "Comps!"
    rows = [
        ("EV / Revenue", L["LTM revenue ($m)"], True),
        ("EV / EBITDA", L["LTM EBITDA ($m)"], True),
        ("P / E", L["LTM net income ($m)"], False),
    ]
    r = 4
    for method, metric_col, is_ev in rows:
        mcol = L[method]
        ws.cell(row=r, column=1, value=method).font = BOLD
        ws.cell(row=r, column=2, value=f"={C}{metric_col}{trow}").number_format = MILLIONS
        for j, stat in enumerate(("25th percentile", "Median", "75th percentile")):
            ws.cell(row=r, column=3 + j, value=f"={C}{mcol}{stats_at[stat]}").number_format = MULTIPLE
        net_claims = f"({C}{L['Debt ($m)']}{trow}-{C}{L['Cash & ST inv. ($m)']}{trow}+{C}{L['Minority int. ($m)']}{trow})"
        shares = f"{C}{L['Diluted shares (m)']}{trow}"
        for j in range(3):
            mult = f"{get_column_letter(3 + j)}{r}"
            body = f"({mult}*B{r}-{net_claims})/{shares}" if is_ev else f"{mult}*B{r}/{shares}"
            ws.cell(row=r, column=6 + j, value=f'=IFERROR(IF(N(B{r})>0,{body},"NM"),"NM")').number_format = PRICE
        ws.cell(row=r, column=9, value=f"={C}{L['Share price ($)']}{trow}").number_format = PRICE
        ws.cell(row=r, column=10, value=f'=IFERROR(G{r}/I{r}-1,"NM")').number_format = PCT
        for col in range(2, 11):
            ws.cell(row=r, column=col).font = BLACK
        r += 1
    ws.cell(row=r + 1, column=1, value="52-week range").font = BOLD
    ws.cell(row=r + 1, column=6, value=t.q.low_52w).number_format = PRICE
    ws.cell(row=r + 1, column=8, value=t.q.high_52w).number_format = PRICE
    for col in (6, 8):
        ws.cell(row=r + 1, column=col).font = BLUE
    for i, w in enumerate([16, 12, 10, 10, 10, 12, 12, 12, 10, 10], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.sheet_view.showGridLines = False
    if chart_png and chart_png.exists():
        img = Image(str(chart_png))
        img.width, img.height = 760, 380
        ws.add_image(img, f"A{r + 4}")


def _notes(wb, fight: Fight) -> None:
    ws = wb.create_sheet("Notes")
    ws["A1"] = "Sources, periods and adjustments"
    ws["A1"].font = TITLE
    lines = [
        "Financials: SEC EDGAR XBRL company facts (US GAAP). Prices and 52-week range: Yahoo Finance.",
        "LTM = last fiscal year + current year-to-date - prior year-to-date.",
        "EBITDA = operating income + depreciation & amortisation (from the cash flow statement). Not adjusted for one-offs or SBC.",
        "Debt = long-term debt (incl. current portion) + short-term borrowings. Leases excluded. Cash includes short-term investments.",
        "EV = market cap + debt - cash + minority interest. Multiples marked NM where the denominator is negative.",
        "Peers: same SIC code as the target, ranked by closeness in revenue (or chosen by hand with --peers).",
        "",
    ]
    r = 3
    for line in lines:
        ws.cell(row=r, column=1, value=line).font = BLACK
        r += 1
    heads = ["Ticker", "LTM period end", "LTM method", "Balance sheet date", "Shares as of", "Flags"]
    for i, h in enumerate(heads, start=1):
        c = ws.cell(row=r, column=i, value=h)
        c.font, c.fill = WHITE_BOLD, NAVY
    for c in [fight.target, *fight.peers]:
        r += 1
        fx = c.fx
        vals = [c.ticker, fx.period_end, fx.revenue.method, fx.bs_date, fx.shares_date, "; ".join(fx.notes) or "–"]
        for i, v in enumerate(vals, start=1):
            cell = ws.cell(row=r, column=i, value=v)
            cell.font = BLACK
            if isinstance(v, date):
                cell.number_format = "dd mmm yyyy"
    if fight.dropped:
        r += 2
        ws.cell(row=r, column=1, value="Peers left out").font = BOLD
        for d in fight.dropped:
            r += 1
            ws.cell(row=r, column=1, value=d).font = BLACK
    for i, w in enumerate([10, 14, 26, 16, 13, 90], start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.column_dimensions["A"].width = 12
    ws.sheet_view.showGridLines = False
