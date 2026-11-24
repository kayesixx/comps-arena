"""The arena: a fighting-game style HTML page for one comps run.

The target fights "The Median", a boss built from the peers' median figures, over three
rounds: growth, margins and valuation. Then a fighter-select roster and the final verdict.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

from .comps import Company, Fight, peer_stats

PALETTE = ["#ff3b3b", "#ffb800", "#2ee6a6", "#3ba8ff", "#c45bff", "#ff6fb5", "#9cff3b", "#ff8a3b"]


def _fmt_money(m: float) -> str:
    return f"${m / 1e6:,.2f}T" if abs(m) >= 1e6 else f"${m / 1e3:,.1f}B" if abs(m) >= 1e3 else f"${m:,.0f}M"


def _pct(v):
    return "–" if v is None else f"{v * 100:+.1f}%" if abs(v) < 10 else f"{v * 100:+,.0f}%"


def _x(v):
    return "NM" if v is None else f"{v:.1f}x"


def _fighter(c: Company, color: str) -> dict:
    return {
        "ticker": c.ticker,
        "name": c.name.title() if c.name.isupper() else c.name,
        "color": color,
        "mcap": _fmt_money(c.market_cap),
        "power": min(100, max(8, 12 * math.log10(max(c.market_cap, 1)))),
        "speed": None if c.growth is None else min(100, max(4, 50 + c.growth * 150)),
        "stamina": None if c.margin is None else min(100, max(4, c.margin * 180)),
        "growth": _pct(c.growth),
        "margin": "–" if c.margin is None else f"{c.margin * 100:.1f}%",
        "evebitda": _x(c.ev_ebitda),
        "evrev": _x(c.ev_revenue),
        "pe": _x(c.pe),
    }


def _rounds(f: Fight) -> list[dict]:
    t = f.target
    g, m, v = peer_stats(f.peers, "growth"), peer_stats(f.peers, "margin"), peer_stats(f.peers, "ev_ebitda")
    out = []

    def add(title, sub, mine, theirs, fmt, higher_wins, win_line, lose_line):
        if mine is None or not theirs.ok:
            out.append({"title": title, "sub": sub, "skip": True})
            return
        med = theirs.median
        target_wins = mine > med if higher_wins else mine < med
        gap = abs(mine - med)
        scale = max(abs(med), 1e-9)
        dmg = min(45, 12 + 60 * gap / scale) if gap else 0
        out.append({
            "title": title, "sub": sub, "skip": False,
            "you": fmt(mine), "boss": fmt(med),
            "winner": "you" if target_wins else ("draw" if gap == 0 else "boss"),
            "dmg": round(dmg, 1),
            "line": (win_line if target_wins else lose_line),
        })

    add("ROUND 1", "GROWTH", t.growth, g, lambda x: _pct(x), True,
        f"{t.ticker} outgrows the pack!", f"The peers grow faster than {t.ticker}.")
    add("ROUND 2", "MARGINS", t.margin, m, lambda x: f"{x * 100:.1f}%", True,
        f"{t.ticker} squeezes more EBITDA from every dollar!", f"The peers run fatter margins.")
    add("ROUND 3", "PRICE TAG", t.ev_ebitda, v, lambda x: f"{x:.1f}x", False,
        f"{t.ticker} is the cheaper fighter on EV/EBITDA!", f"{t.ticker} costs more per dollar of EBITDA.")
    return out


def _verdict(f: Fight) -> str:
    t = f.target
    prem = f.premium("ev_ebitda")
    g = peer_stats(f.peers, "growth")
    m = peer_stats(f.peers, "margin")
    if prem is None:
        return f"{t.ticker} has no meaningful EV/EBITDA (negative or missing EBITDA), so judge it on revenue and P/E."
    side = "premium" if prem > 0 else "discount"
    parts = [f"{t.ticker} trades at {_x(t.ev_ebitda)} LTM EBITDA, a {abs(prem) * 100:.0f}% {side} to the peer median of {_x(peer_stats(f.peers, 'ev_ebitda').median)}."]
    reasons = []
    if t.growth is not None and g.ok:
        reasons.append(f"revenue growth of {_pct(t.growth)} vs {_pct(g.median)}")
    if t.margin is not None and m.ok:
        reasons.append(f"an EBITDA margin of {t.margin * 100:.0f}% vs {m.median * 100:.0f}%")
    if reasons:
        parts.append("The case for or against it: " + " and ".join(reasons) + ".")
    better = sum(1 for ok in (
        t.growth is not None and g.ok and t.growth > g.median,
        t.margin is not None and m.ok and t.margin > m.median,
    ) if ok)
    if prem > 0.15 and better == 0:
        parts.append("It costs more than its peers while growing slower and earning less: the premium looks hard to justify on these numbers.")
    elif prem > 0.15:
        parts.append("The premium is backed by stronger fundamentals, so the question is whether it's big enough or too big.")
    elif prem < -0.15 and better >= 1:
        parts.append("Cheaper than peers despite better fundamentals: either the market sees a risk the numbers don't show, or it's mispriced.")
    elif prem < -0.15:
        parts.append("The discount lines up with weaker fundamentals.")
    else:
        parts.append("It's priced roughly in line with its peers.")
    return " ".join(parts)


def write(fight: Fight, path: Path) -> None:
    t = fight.target
    you = _fighter(t, "#ffb800")
    peers = [_fighter(p, PALETTE[i % len(PALETTE)]) for i, p in enumerate(fight.peers)]
    implied = [
        {"method": i.method, "low": i.low, "mid": i.mid, "high": i.high, "mlo": i.multiple_low, "mhi": i.multiple_high}
        for i in fight.implied()
    ]
    data = {
        "you": you,
        "peers": peers,
        "rounds": _rounds(fight),
        "verdict": _verdict(fight),
        "price": t.price,
        "lo52": t.q.low_52w,
        "hi52": t.q.high_52w,
        "implied": implied,
        "period": f"LTM to {t.fx.period_end:%b %Y}",
        "sic": t.sic_name,
    }
    blob = json.dumps(data).replace("</", "<\\/")
    path.write_text(TEMPLATE.replace("__DATA__", blob).replace("__TITLE__", html.escape(f"{t.ticker} vs the peers")))


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ | Comps Arena</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{--bg:#0b0710;--panel:#160f1f;--line:#3a2a4d;--ink:#f3eefa;--dim:#a99bbd;--gold:#ffb800;--red:#ff3b3b;--green:#2ee6a6;
  --pixel:"Press Start 2P",ui-monospace,monospace;--sans:Inter,system-ui,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:radial-gradient(ellipse at 50% -10%,#3b0d1f 0%,var(--bg) 60%) fixed,var(--bg);color:var(--ink);font-family:var(--sans);min-height:100vh}
.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
.logo{font-family:var(--pixel);text-align:center;font-size:clamp(22px,5vw,44px);letter-spacing:2px;margin:8px 0 2px;
  color:var(--gold);text-shadow:0 0 0 #000,3px 3px 0 #8a1010,6px 6px 0 #000;transform:skewX(-6deg)}
.tag{text-align:center;font-family:var(--pixel);font-size:9px;color:var(--dim);letter-spacing:2px;margin-bottom:28px}
.vs{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center;margin-bottom:22px}
.card{background:var(--panel);border:3px solid var(--line);padding:16px;position:relative;overflow:hidden}
.card.you{border-color:var(--gold);box-shadow:0 0 24px #ffb80033}
.card.boss{border-color:var(--red);box-shadow:0 0 24px #ff3b3b33;text-align:right}
.avatar{width:72px;height:72px;display:grid;place-items:center;font-family:var(--pixel);font-size:13px;color:#000;
  image-rendering:pixelated;box-shadow:inset -6px -6px 0 #0004,inset 6px 6px 0 #fff3;margin-bottom:10px}
.boss .avatar{margin-left:auto}
.fname{font-family:var(--pixel);font-size:13px;line-height:1.5}
.fsub{color:var(--dim);font-size:13px;margin-top:4px}
.vsmark{font-family:var(--pixel);font-size:clamp(26px,6vw,48px);color:var(--red);text-shadow:4px 4px 0 #000;transform:skewX(-8deg)}
.bars{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:10px 0 6px}
.hp{height:22px;border:3px solid #000;outline:2px solid var(--line);background:#2a0a0a;position:relative}
.hp i{position:absolute;inset:0;background:linear-gradient(#ffe066,#ffb800 60%,#d98a00);transition:width .9s steps(12)}
.hp.boss i{right:0;left:auto;background:linear-gradient(#ff8a8a,#ff3b3b 60%,#b51c1c)}
.hp-label{font-family:var(--pixel);font-size:9px;margin-bottom:6px;color:var(--dim)}
.hp-label.r{text-align:right}
.stage{background:var(--panel);border:3px solid var(--line);min-height:210px;display:grid;place-items:center;text-align:center;padding:22px;position:relative}
.announce{font-family:var(--pixel);font-size:clamp(20px,5vw,40px);color:var(--gold);text-shadow:4px 4px 0 #8a1010}
.announce.fight{color:var(--red);text-shadow:4px 4px 0 #000}
.stat-duel{display:flex;gap:20px;justify-content:center;align-items:baseline;flex-wrap:wrap;margin:14px 0 8px;font-family:var(--pixel)}
.stat-duel b{font-size:clamp(16px,3.4vw,26px)}
.stat-duel small{display:block;font-size:8px;color:var(--dim);margin-top:8px}
.line{font-size:15px;color:var(--ink);max-width:560px;margin:6px auto 0}
.pow{position:absolute;font-family:var(--pixel);font-size:22px;color:#fff;text-shadow:3px 3px 0 var(--red);animation:pow .7s ease-out forwards;pointer-events:none}
@keyframes pow{0%{transform:scale(.3) rotate(-12deg);opacity:0}30%{transform:scale(1.3) rotate(4deg);opacity:1}100%{transform:scale(1) translateY(-30px);opacity:0}}
.shake{animation:shake .35s}
@keyframes shake{25%{transform:translateX(-6px)}50%{transform:translateX(6px)}75%{transform:translateX(-3px)}}
.controls{display:flex;gap:10px;justify-content:center;margin:14px 0 34px;flex-wrap:wrap}
button{font-family:var(--pixel);font-size:10px;padding:12px 16px;background:var(--gold);color:#000;border:3px solid #000;box-shadow:4px 4px 0 #000;cursor:pointer}
button.ghost{background:transparent;color:var(--dim);border-color:var(--line);box-shadow:none}
button:active{transform:translate(2px,2px);box-shadow:2px 2px 0 #000}
h2{font-family:var(--pixel);font-size:14px;color:var(--gold);margin:36px 0 14px;letter-spacing:1px}
.roster{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px}
.fc{background:var(--panel);border:3px solid var(--line);padding:12px;transition:transform .15s,border-color .15s}
.fc:hover{transform:translateY(-3px);border-color:var(--c)}
.fc .avatar{width:48px;height:48px;font-size:10px}
.fc .fname{font-size:10px}
.meter{display:grid;grid-template-columns:64px 1fr 52px;gap:6px;align-items:center;font-size:11px;margin-top:6px;color:var(--dim)}
.meter span:last-child{text-align:right;color:var(--ink);font-variant-numeric:tabular-nums}
.meter div{height:8px;background:#2a2036;border:1px solid #000}
.meter div i{display:block;height:100%;background:var(--c)}
.multis{display:flex;justify-content:space-between;margin-top:10px;font-size:11px;color:var(--dim)}
.multis b{color:var(--ink);font-weight:600}
.ff{background:var(--panel);border:3px solid var(--line);padding:18px}
.ffrow{display:grid;grid-template-columns:150px 1fr;gap:10px;align-items:center;margin:12px 0}
.ffrow .lab{font-size:12px;color:var(--dim)}
.ffrow .lab b{display:block;color:var(--ink);font-size:12px}
.track{position:relative;height:26px}
.seg{position:absolute;top:3px;height:20px;background:repeating-linear-gradient(90deg,var(--c) 0 6px,color-mix(in srgb,var(--c) 75%,#000) 6px 8px);border:2px solid #000}
.seg em{position:absolute;top:-1px;bottom:-1px;width:3px;background:#fff}
.seg .l,.seg .h{position:absolute;top:2px;font-size:11px;white-space:nowrap;color:var(--ink)}
.seg .l{right:calc(100% + 6px)}.seg .h{left:calc(100% + 6px)}
.now{position:absolute;top:-6px;bottom:-6px;width:0;border-left:3px dashed var(--red)}
.nowlab{font-family:var(--pixel);font-size:8px;color:var(--red);text-align:right;margin-bottom:6px}
.verdict{background:linear-gradient(135deg,#2b0d16,#160f1f);border:3px solid var(--gold);padding:20px;font-size:16px;line-height:1.6}
.verdict .k{font-family:var(--pixel);font-size:12px;color:var(--gold);display:block;margin-bottom:10px}
.foot{color:var(--dim);font-size:12px;margin-top:28px;text-align:center;line-height:1.6}
@media (max-width:620px){.vs{grid-template-columns:1fr}.vsmark{text-align:center}.card.boss{text-align:left}.boss .avatar{margin-left:0}.ffrow{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">COMPS ARENA</div>
  <div class="tag" id="tag"></div>

  <div class="bars">
    <div><div class="hp-label" id="hpYouLab"></div><div class="hp"><i id="hpYou" style="width:100%"></i></div></div>
    <div><div class="hp-label r">THE MEDIAN</div><div class="hp boss"><i id="hpBoss" style="width:100%"></i></div></div>
  </div>

  <div class="vs">
    <div class="card you" id="cardYou"></div>
    <div class="vsmark">VS</div>
    <div class="card boss" id="cardBoss"></div>
  </div>

  <div class="stage" id="stage"><div><div class="announce">PRESS START</div><div class="line">Three rounds against the peer median: growth, margins, price tag.</div></div></div>
  <div class="controls">
    <button id="go">START FIGHT</button>
    <button class="ghost" id="skip">SKIP TO RESULTS</button>
  </div>

  <h2>&gt; SELECT YOUR FIGHTER: THE PEERS</h2>
  <div class="roster" id="roster"></div>

  <h2>&gt; FINAL SCORE: IMPLIED SHARE PRICE</h2>
  <div class="ff" id="ff"></div>

  <h2>&gt; VERDICT</h2>
  <div class="verdict"><span class="k" id="vk"></span><span id="vt"></span></div>

  <div class="foot" id="foot"></div>
</div>
<script>
const D = __DATA__;
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const avatar = f => `<div class="avatar" style="background:${f.color}">${esc(f.ticker.slice(0,4))}</div>`;
const money = v => "$" + v.toLocaleString(undefined,{maximumFractionDigits:v<100?2:0});

$("tag").textContent = `${D.sic.toUpperCase()} · ${D.period.toUpperCase()}`;
$("hpYouLab").textContent = D.you.ticker;
$("cardYou").innerHTML = `${avatar(D.you)}<div class="fname">${esc(D.you.ticker)}</div><div class="fsub">${esc(D.you.name)} · ${D.you.mcap}</div>`;
$("cardBoss").innerHTML = `<div class="avatar" style="background:#ff3b3b">MED</div><div class="fname">THE MEDIAN</div><div class="fsub">Boss built from ${D.peers.length} peers</div>`;

$("roster").innerHTML = D.peers.map(p => `
  <div class="fc" style="--c:${p.color}">
    ${avatar(p)}<div class="fname">${esc(p.ticker)}</div><div class="fsub">${esc(p.name)}</div>
    ${meter("POWER", p.power, p.mcap)}${meter("SPEED", p.speed, p.growth)}${meter("STAMINA", p.stamina, p.margin)}
    <div class="multis"><span>EV/EBITDA <b>${p.evebitda}</b></span><span>P/E <b>${p.pe}</b></span></div>
  </div>`).join("");
function meter(lab, v, txt){ return `<div class="meter"><span>${lab}</span><div><i style="width:${v==null?0:v}%"></i></div><span>${txt}</span></div>`; }

// Football field
(function(){
  const rows = D.implied.map(i => ({lab:i.method, sub:`${i.mlo.toFixed(1)}x – ${i.mhi.toFixed(1)}x`, lo:Math.max(0,i.low), hi:i.high, mid:i.mid, c:"#3ba8ff"}))
    .filter(r => r.hi > 0);
  rows.push({lab:"52-week range", sub:"where it has traded", lo:D.lo52, hi:D.hi52, mid:null, c:"#8a7aa3"});
  const max = Math.max(D.price, ...rows.map(r => r.hi)) * 1.15;
  const pct = v => (v / max * 100).toFixed(2) + "%";
  $("ff").innerHTML = `<div class="nowlab">CURRENT ${money(D.price)}</div>` + rows.map(r => `
    <div class="ffrow"><div class="lab"><b>${r.lab}</b>${r.sub}</div>
      <div class="track"><div class="now" style="left:${pct(D.price)}"></div>
        <div class="seg" style="--c:${r.c};left:${pct(r.lo)};width:calc(${pct(r.hi - r.lo)} + 2px)">
          ${r.mid!=null?`<em style="left:${((r.mid-r.lo)/Math.max(r.hi-r.lo,1e-9)*100).toFixed(1)}%"></em>`:""}
          <span class="l">${money(r.lo)}</span><span class="h">${money(r.hi)}</span></div></div></div>`).join("")
    + `<div class="fsub">Bars show the price implied by the peers' 25th–75th percentile multiples; the white tick is the median.</div>`;
})();

$("vt").textContent = D.verdict;
$("foot").textContent = `Data: SEC EDGAR filings (US GAAP) and Yahoo Finance prices. Rough-and-ready LTM figures, not investment advice.`;

// The fight
const sleep = ms => new Promise(r => setTimeout(r, ms));
let hpYou = 100, hpBoss = 100, running = false, done = false;
function setHp(){ $("hpYou").style.width = hpYou + "%"; $("hpBoss").style.width = hpBoss + "%"; }
function pow(target){
  const card = $(target === "you" ? "cardYou" : "cardBoss");
  card.classList.remove("shake"); void card.offsetWidth; card.classList.add("shake");
  const p = document.createElement("div"); p.className = "pow";
  p.textContent = ["POW!","WHAM!","CRACK!","BAM!"][Math.floor(Math.random()*4)];
  p.style.left = (20 + Math.random()*60) + "%"; p.style.top = "30%";
  $("stage").appendChild(p); setTimeout(() => p.remove(), 800);
}
async function fight(){
  if (running) return; running = true; done = false; hpYou = hpBoss = 100; setHp();
  const st = $("stage");
  for (const r of D.rounds){
    st.innerHTML = `<div><div class="announce">${r.title}</div><div class="line" style="font-family:var(--pixel);font-size:12px;color:var(--dim);margin-top:12px">${r.sub}</div></div>`;
    await sleep(1100);
    if (r.skip){ st.innerHTML = `<div><div class="announce">NO CONTEST</div><div class="line">Not enough data for this round.</div></div>`; await sleep(1300); continue; }
    st.innerHTML = `<div><div class="announce fight">FIGHT!</div></div>`; await sleep(650);
    st.innerHTML = `<div><div class="stat-duel"><div><b style="color:var(--gold)">${r.you}</b><small>${esc(D.you.ticker)}</small></div><div style="font-size:14px;color:var(--dim)">vs</div><div><b style="color:var(--red)">${r.boss}</b><small>PEER MEDIAN</small></div></div><div class="line">${esc(r.line)}</div></div>`;
    await sleep(500);
    if (r.winner === "you"){ hpBoss = Math.max(5, hpBoss - r.dmg); pow("boss"); }
    else if (r.winner === "boss"){ hpYou = Math.max(5, hpYou - r.dmg); pow("you"); }
    setHp(); await sleep(1900);
  }
  const youWin = hpYou > hpBoss, draw = Math.abs(hpYou - hpBoss) < 0.5;
  st.innerHTML = `<div><div class="announce ${youWin?"":"fight"}">${draw?"DRAW":"K.O."}</div><div class="line" style="margin-top:14px">${draw?"Dead level with the peers.":youWin?esc(D.you.ticker)+" beats the peer median.":"The peer median wins this one."}</div></div>`;
  if (!draw) pow(youWin ? "boss" : "you");
  $("vk").textContent = draw ? "DRAW" : youWin ? `${D.you.ticker} WINS` : "THE MEDIAN WINS";
  running = false; done = true;
  $("go").textContent = "REMATCH";
}
$("go").onclick = fight;
$("skip").onclick = () => document.querySelector("h2").scrollIntoView({behavior:"smooth"});
// Pre-compute the result for the verdict header, so it reads right even without watching the fight
(function(){
  let y=100,b=100; for (const r of D.rounds){ if (r.skip) continue; if (r.winner==="you") b=Math.max(5,b-r.dmg); else if (r.winner==="boss") y=Math.max(5,y-r.dmg); }
  $("vk").textContent = Math.abs(y-b)<0.5 ? "DRAW" : y>b ? `${D.you.ticker} WINS` : "THE MEDIAN WINS";
})();
</script>
</body>
</html>
"""
