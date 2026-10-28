"""The day's report, from the run folder: leaderboard, luck test, best and worst trades, rejected orders, cost, speed.

    py -3 report.py --run <run_id> [--sims 10000]      writes runs/<run>/report.md and report.json

Returns are replayed at the round prices (the same basis as the luck test). In live mode the Alpaca equity from the
last mark sits next to them, so slippage between the snapshot and the real fill is visible.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import dashboard
import luck
from snapshot import RUNS

LABEL = {"B1": "dsh + DeepSeek", "B2": "dsh + Haiku", "B3": "Claude Code + DeepSeek", "B4": "Claude Code + Haiku",
         "B5": "TradingAgents (DeepSeek)"}


def per_symbol(run_dir: Path, book: str, prices: list[dict], final: dict) -> dict[str, float]:
    """Profit by symbol over the day, at round prices: money in, money out, and what is left at the final price."""
    flow: dict[str, float] = {}
    shares: dict[str, float] = {}
    for k, rd in enumerate(sorted(run_dir.glob("round_*"))):
        px = prices[min(k, len(prices) - 1)]
        tools = rd / book / "tools.jsonl"
        for line in tools.read_text(encoding="utf-8").splitlines() if tools.exists() else []:
            c = json.loads(line)
            if c["tool"] != "place_order" or c.get("verdict") != "accepted":
                continue
            o, s = c["order"], c["order"]["symbol"]
            if o["side"] == "buy":
                shares[s] = shares.get(s, 0.0) + o["dollars"] / px[s]
                flow[s] = flow.get(s, 0.0) - o["dollars"]
            else:
                q = shares.get(s, 0.0) if o.get("all") else min(o["qty"], shares.get(s, 0.0))
                shares[s] = shares.get(s, 0.0) - q
                flow[s] = flow.get(s, 0.0) + q * px[s]
    return {s: flow[s] + shares.get(s, 0.0) * final.get(s, 0.0) for s in flow}


def timeline(run_dir: Path, book: str) -> list[dict]:
    """Round by round: the time, every order the agent asked for (with its own reason and the verdict), its note."""
    out = []
    for rd in sorted(run_dir.glob("round_*")):
        if not (rd / book).exists():
            continue
        snap = json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))
        orders = []
        t = rd / book / "tools.jsonl"
        for line in t.read_text(encoding="utf-8").splitlines() if t.exists() else []:
            c = json.loads(line)
            if c["tool"] == "place_order":
                a = c["args"]
                amt = (f"${a['dollars']:,.0f}" if a.get("dollars") else "all" if a.get("sell_all") else f"{a.get('qty')} sh")
                orders.append({"ok": c.get("verdict") == "accepted", "side": a.get("side"), "symbol": str(a.get("symbol", "")).upper(),
                               "amount": amt, "reason": a.get("reason", ""), "result": c["result"]})
        note = (rd / book / "note.md").read_text(encoding="utf-8").strip() if (rd / book / "note.md").exists() else ""
        out.append({"round": int(rd.name[-2:]), "time": snap["time_et"][-5:], "orders": orders, "note": note})
    return out


def b5_logic(run_dir: Path) -> list[dict]:
    rows = []
    for d in sorted((run_dir / "B5").glob("*/result.json")):
        r = json.loads(d.read_text(encoding="utf-8"))
        rows.append({"ticker": r["ticker"], "rating": r["rating"], "decision": (r.get("final_trade_decision") or "")[:600]})
    return rows


def html_page(run: str, L: dict, detail: dict, curves: dict, times: list[str], I: dict | None = None) -> str:
    import html as H

    I = I or {"books": {}}

    def e(s: str) -> str:
        return H.escape(s).replace("**", "")

    cols = []
    for b, d in detail.items():
        steps = []
        for r in d.get("timeline", []):
            orders = "".join(f'<li class="{"ok" if o["ok"] else "bad"}"><b>{e(str(o["side"]))} {e(o["symbol"])} {e(o["amount"])}</b>'
                             f'{"" if o["ok"] else " (rejected: " + e(o["result"].replace("REJECTED: ", "")) + ")"}'
                             f'<div class="why">{e(o["reason"])}</div></li>' for o in r["orders"]) or '<li class="hold">no orders: held</li>'
            steps.append(f'<div class="round"><h4>Round {r["round"]} &middot; {r["time"]} New York</h4><ul>{orders}</ul>'
                         f'<details><summary>its note</summary><p>{e(r["note"][:1500])}</p></details></div>')
        if b == "B5":
            steps = [f'<div class="round"><h4>{x["ticker"]}: {e(x["rating"])}</h4><details><summary>decision</summary><p>{e(x["decision"])}</p></details></div>'
                     for x in d.get("b5", [])]
        ret = 100 * d["replayed_return"]
        x = I["books"].get(b, {})
        extra = ""
        if x:
            dd = f'{100 * x["max_drawdown"]:.2f}%' if x.get("max_drawdown") is not None else "n/a"
            inv = " &rsaquo; ".join(f"{100 * v:.0f}%" for v in x.get("invested_by_round", [])) or "n/a"
            extra = (f'<div class="kpi">P&amp;L ${x["pnl_usd"]:+,.2f} &middot; after the AI bill ${x["pnl_after_ai_usd"]:+,.2f}'
                     f' &middot; after est. trading costs ${x["pnl_after_all_costs_usd"]:+,.2f} (turnover ${x["turnover_usd"]:,.0f})'
                     f' &middot; max drawdown {dd}<br>invested by round: {inv}</div>')
        if d.get("debrief"):
            extra += f'<div class="grade"><b>Its own grade after the close</b><p>{e(d["debrief"])}</p></div>'
        cols.append(f'<section><h3>{b} {LABEL[b]}</h3><div class="kpi"><span class="{"up" if ret >= 0 else "dn"}">{ret:+.3f}%</span>'
                    f' vs SPY {100 * (d["replayed_return"] - L["spy_return"]):+.3f} pts &middot; beats {100 * d["percentile"]:.0f}% of random books'
                    f' &middot; {d["trades"]} trades, {len(d["rejected"])} rejected &middot; cost {"≈" if b != "B4" and b != "B2" else ""}${d["cost_usd"]:.3f}</div>'
                    f'{extra}{"".join(steps)}</section>')
    summary = ""
    if "harness_effect_pts" in I:
        summary += (f'<div class="kpi">Harness vs model: Claude Code minus dsh <b>{I["harness_effect_pts"]:+.3f} pts</b> &middot; '
                    f'Haiku minus DeepSeek <b>{I["model_effect_pts"]:+.3f} pts</b></div>')
    if I.get("herding"):
        summary += '<div class="kpi">Herding: ' + " &middot; ".join(
            f'R{h["round"]} overlap {h["overlap"]:.2f} (all held {", ".join(h["held_by_all"]) or "none"})' for h in I["herding"]) + "</div>"
    if I.get("spy_ghost"):
        summary += '<div class="kpi">SPY ghost book: ' + " &middot; ".join(f'{g["at"]} ${g["usd"]:,.0f}' for g in I["spy_ghost"]) + "</div>"
    if summary:
        cols.insert(0, f'<section style="grid-column:1/-1"><h3>The whole field</h3>{summary}</section>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Harness Arena report</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap" rel="stylesheet">
<style>
body{{margin:0;background:#070b12;color:#e6ebf2;font:15px/1.5 Inter,sans-serif}}
header{{padding:28px 32px 8px}} h1{{margin:0;font-size:28px;letter-spacing:.06em}} .sub{{color:#6b7a90;margin-top:6px}}
.chart{{margin:18px 32px;background:#0e1521;border:1px solid #1c2738;border-radius:14px;padding:8px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;padding:0 32px 40px}}
section{{background:#0e1521;border:1px solid #1c2738;border-radius:14px;padding:16px 18px}}
h3{{margin:0 0 6px;font-size:18px}} .kpi{{color:#94a3b8;font-size:13px;margin-bottom:10px}} .kpi span{{font-size:22px;font-weight:800;margin-right:6px}}
.up{{color:#22c55e}} .dn{{color:#f87171}} .round{{border-top:1px dashed #1c2738;padding:8px 0}} h4{{margin:0 0 4px;color:#94a3b8;font-weight:600;font-size:13px}}
ul{{margin:0;padding-left:18px}} li{{margin:3px 0}} li.ok b{{color:#22c55e}} li.bad b{{color:#f87171}} li.hold{{color:#6b7a90}}
.why{{color:#cbd5e1;font-size:13px}} details{{color:#94a3b8;font-size:13px}} summary{{cursor:pointer;color:#38bdf8}} p{{white-space:pre-wrap}}
.grade{{background:#121c2c;border-left:3px solid #fbbf24;border-radius:6px;padding:8px 10px;margin:8px 0;font-size:13px}}
.grade p{{margin:4px 0 0;color:#e6ebf2}}
.grid line{{stroke:#1c2738}} line.grid{{stroke:#1c2738}} .ax{{fill:#94a3b8;font:12px monospace}} .legend{{color:#94a3b8;font-size:13px;margin:4px 8px}} .legend span{{margin-right:14px}}
</style></head><body><header><h1>HARNESS ARENA &middot; {e(run)}</h1>
<div class="sub">SPY {100 * L["spy_return"]:+.3f}% over the same span &middot; luck test: {L["sims"]:,} random books per book with the same habits</div></header>
<div class="chart">{curves if 'class="legend"' in curves else '<div class="legend">' + "".join(f'<span style="color:{c}">&#9679; {b} {LABEL[b]}</span>' for b, (_, _, _, c) in dashboard.BOOKS.items()) + '<span>- - SPY</span></div>' + curves}</div>
<div class="grid">{"".join(cols)}</div></body></html>"""


def holdings_by_round(run_dir: Path, book: str, prices: list[dict]) -> list[tuple[set[str], float]]:
    """After each round: the stocks held and the share of the book invested, replayed at round prices."""
    cash, shares, out = luck.START, {}, []
    for k, rd in enumerate(sorted(run_dir.glob("round_*"))):
        px = prices[min(k, len(prices) - 1)]
        t = rd / book / "tools.jsonl"
        for line in t.read_text(encoding="utf-8").splitlines() if t.exists() else []:
            c = json.loads(line)
            if c["tool"] != "place_order" or c.get("verdict") != "accepted":
                continue
            o, s = c["order"], c["order"]["symbol"]
            if o["side"] == "buy":
                shares[s] = shares.get(s, 0.0) + o["dollars"] / px[s]
                cash -= o["dollars"]
            else:
                q = shares.get(s, 0.0) if o.get("all") else min(o["qty"], shares.get(s, 0.0))
                shares[s] = shares.get(s, 0.0) - q
                cash += q * px[s]
        value = sum(q * px.get(s, 0.0) for s, q in shares.items())
        out.append(({s for s, q in shares.items() if q > 1e-6}, value / (cash + value) if cash + value else 0.0))
    return out


# Trading costs. Commissions are zero at Alpaca, live too. The spread is roughly inside the paper fill; 2 bps a trade
# stands in for what is not (impact, quotes moving), and paper never charges it. The SEC fee on sales Alpaca does charge,
# paper included: a "REG fee" posted the next morning, $20.6 per $1M of sales on 26 Oct 2026 (Section 31, reset each
# year), plus a CAT fee of a cent a day. The day's P&L here is replayed at snapshot prices, so it holds neither.
SLIPPAGE_BPS = 2.0
SEC_FEE_PER_USD = 20.6 / 1e6


def turnover(run_dir: Path, book: str, prices: list[dict]) -> tuple[float, float]:
    """Dollars bought and sold over the day, including the sell-off at the final prices."""
    if book == "B5":
        log = run_dir / "B5" / "orders.jsonl"
        rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
        b = sum(o["qty"] * o["price"] for o in rows if o.get("status_code", 500) < 300)
        return b, b
    bought = sold = 0.0
    shares: dict[str, float] = {}
    for k, rd in enumerate(sorted(run_dir.glob("round_*"))):
        px = prices[min(k, len(prices) - 1)]
        t = rd / book / "tools.jsonl"
        for line in t.read_text(encoding="utf-8").splitlines() if t.exists() else []:
            c = json.loads(line)
            if c["tool"] != "place_order" or c.get("verdict") != "accepted":
                continue
            o, s = c["order"], c["order"]["symbol"]
            if o["side"] == "buy":
                bought += o["dollars"]
                shares[s] = shares.get(s, 0.0) + o["dollars"] / px[s]
            else:
                q = shares.get(s, 0.0) if o.get("all") else min(o["qty"], shares.get(s, 0.0))
                shares[s] = shares.get(s, 0.0) - q
                sold += q * px[s]
    final = prices[-1]
    sold += sum(q * final.get(s, 0.0) for s, q in shares.items() if q > 0)        # the sell-off
    return bought, sold


def minute_marks(run_dir: Path) -> dict[str, list[tuple[str, float]]]:
    f = run_dir / "marks.csv"
    series: dict[str, list[tuple[str, float]]] = {}
    if f.exists():
        for row in csv.DictReader(f.open(encoding="utf-8")):
            if row["equity"]:
                series.setdefault(row["book"], []).append((row["ts_utc"], float(row["equity"])))
    return series


def insights(run_dir: Path, L: dict, detail: dict, prices: list[dict], final: dict) -> dict:
    """The numbers viewers of other AI-trading videos asked for: cost against profit, drawdown, cash left idle,
    harness against model, herding, the order funnel, and SPY as a ghost book in dollars."""
    rounds = sorted(run_dir.glob("round_*"))
    times = [json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))["time_et"][-5:] for rd in rounds]
    marks = minute_marks(run_dir)
    out: dict = {"books": {}, "times": times}
    for b, d in detail.items():
        ret = d["replayed_return"]
        pnl = ret * luck.START
        orders = sum(len([o for o in r["orders"] if o["ok"]]) for r in d.get("timeline", []))
        dd = None
        if b in marks:
            peak, worst = marks[b][0][1], 0.0
            for _, e in marks[b]:
                peak = max(peak, e)
                worst = max(worst, (peak - e) / peak)
            dd = worst
        funnel = {"asked": 0, "accepted": 0, "rejected_by_rules": 0, "broker_rejected": 0, "filled_at_alpaca": 0,
                  "harness_errors": 0, "timeouts": d.get("timeouts", 0)}
        for rd in rounds:
            t = rd / b / "tools.jsonl"
            for line in t.read_text(encoding="utf-8").splitlines() if t.exists() else []:
                c = json.loads(line)
                if c["tool"] == "place_order":
                    funnel["asked"] += 1
                    v = c.get("verdict")
                    funnel["accepted" if v == "accepted" else "broker_rejected" if v == "broker_rejected" else "rejected_by_rules"] += 1
            fills = rd / b / "fills.json"
            if fills.exists():
                funnel["filled_at_alpaca"] += sum(o.get("status") == "filled" for o in json.loads(fills.read_text(encoding="utf-8")))
            err = rd / b / "stderr.log"
            if err.exists() and "Error" in err.read_text(encoding="utf-8", errors="replace"):
                funnel["harness_errors"] += 1
        held = holdings_by_round(run_dir, b, prices) if b != "B5" else []
        bought, sold = turnover(run_dir, b, prices)
        slippage, sec_fee = (bought + sold) * SLIPPAGE_BPS / 1e4, sold * SEC_FEE_PER_USD
        trading_cost = slippage + sec_fee
        out["books"][b] = {"pnl_usd": pnl, "pnl_after_ai_usd": pnl - d["cost_usd"],
                           "turnover_usd": bought + sold, "est_trading_cost_usd": trading_cost,
                           "est_slippage_usd": slippage, "est_sec_fee_usd": sec_fee,
                           "pnl_after_all_costs_usd": pnl - d["cost_usd"] - trading_cost,
                           "cost_per_order_usd": d["cost_usd"] / orders if orders else None, "max_drawdown": dd,
                           "invested_by_round": [round(h[1], 3) for h in held], "funnel": funnel,
                           "holdings_by_round": [sorted(h[0]) for h in held]}
    r = {b: detail[b]["replayed_return"] for b in ("B1", "B2", "B3", "B4") if b in detail}
    if len(r) == 4:
        out["harness_effect_pts"] = 100 * ((r["B3"] + r["B4"]) / 2 - (r["B1"] + r["B2"]) / 2)   # Claude Code minus dsh
        out["model_effect_pts"] = 100 * ((r["B2"] + r["B4"]) / 2 - (r["B1"] + r["B3"]) / 2)     # Haiku minus DeepSeek
    herd = []
    prompted = [b for b in ("B1", "B2", "B3", "B4") if b in out["books"]]
    for k in range(len(rounds)):
        sets = [set(out["books"][b]["holdings_by_round"][k]) for b in prompted if k < len(out["books"][b]["holdings_by_round"])]
        if len(sets) < 2:
            continue
        pairs = [(a, c) for i, a in enumerate(sets) for c in sets[i + 1:]]
        jac = sum(len(a & c) / len(a | c) for a, c in pairs if a | c) / len(pairs)
        herd.append({"round": k + 1, "time": times[k], "held_by_all": sorted(set.intersection(*sets)), "overlap": round(jac, 2)})
    out["herding"] = herd
    spy0 = prices[0]["SPY"]
    out["spy_ghost"] = [{"at": times[k], "usd": luck.START * prices[k]["SPY"] / spy0} for k in range(len(prices))] + \
                       [{"at": "close", "usd": luck.START * final["SPY"] / spy0}]
    out["data_feed"] = "Alpaca market data, free IEX feed (one exchange's trades; the paid SIP feed covers all exchanges)"
    return out


COLORS = {"B1": "#60a5fa", "B2": "#f472b6", "B3": "#34d399", "B4": "#fbbf24", "B5": "#a78bfa", "SPY": "#9ca3af"}


def marks_chart(run_dir: Path) -> str:
    """Every book's real Alpaca equity, minute by minute, and SPY scaled to $100,000 at the first mark."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    s = minute_marks(run_dir)
    if not s or "SPY" not in s:
        return ""
    t0 = datetime.fromisoformat(s["SPY"][0][0])
    spy0 = s["SPY"][0][1]
    series = {b: [((datetime.fromisoformat(t) - t0).total_seconds() / 60, v) for t, v in pts] for b, pts in s.items() if b != "SPY"}
    series["SPY"] = [((datetime.fromisoformat(t) - t0).total_seconds() / 60, luck.START * v / spy0) for t, v in s["SPY"]]
    w, h, left, pad = 1480, 380, 96, 40
    xs = [x for pts in series.values() for x, _ in pts]
    ys = [y for pts in series.values() for _, y in pts] + [luck.START]
    x1, lo, hi = max(xs), min(ys), max(ys)
    span = max(hi - lo, 100.0)
    lo, hi = lo - 0.08 * span, hi + 0.08 * span

    def P(x: float, y: float) -> tuple[float, float]:
        return left + x * (w - left - pad) / max(x1, 1), h - pad - (y - lo) * (h - 2 * pad) / (hi - lo)

    out = [f'<svg viewBox="0 0 {w} {h}" width="100%">']
    for k in range(5):
        v = lo + k * (hi - lo) / 4
        _, y = P(0, v)
        out.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" class="grid"/><text x="{left - 8}" y="{y + 4:.1f}" class="ax" text-anchor="end">${v:,.0f}</text>')
    et = ZoneInfo("America/New_York")
    for m in range(0, int(x1) + 1, 30):
        x, _ = P(m, lo)
        label = (t0.astimezone(et).timestamp() + m * 60)
        out.append(f'<text x="{x:.1f}" y="{h - 12}" class="ax" text-anchor="middle">{datetime.fromtimestamp(label, et).strftime("%H:%M")}</text>')
    for b, pts in series.items():
        line = " ".join(f"{a:.1f},{c:.1f}" for a, c in (P(x, y) for x, y in pts))
        dash = ' stroke-dasharray="7 6"' if b == "SPY" else ""
        out.append(f'<polyline points="{line}" fill="none" stroke="{COLORS.get(b, "#fff")}" stroke-width="2.6"{dash}/>')
        x, y = P(*pts[-1])
        out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{COLORS.get(b, "#fff")}"/>')
    out.append("</svg>")
    legend = "".join(f'<span style="color:{COLORS[b]}">&#9679; {b} {LABEL.get(b, "($100,000 at the start, dashed)")}</span>' for b in series)
    return f'<div class="legend">{legend} (New York time)</div>' + "".join(out)


def last_marks(run_dir: Path) -> dict[str, float]:
    f = run_dir / "marks.csv"
    if not f.exists():
        return {}
    out = {}
    for row in csv.DictReader(f.open(encoding="utf-8")):
        if row["book"] != "SPY" and row["equity"]:
            out[row["book"]] = float(row["equity"])
    return out


def build(run: str, sims: int) -> Path:
    run_dir = RUNS / run
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) if (run_dir / "run.json").exists() else {}
    L = luck.luck(run, sims)
    prices = luck.round_prices(run_dir)
    final = luck.final_prices(run_dir, prices)
    marks = last_marks(run_dir)
    rounds = sorted(run_dir.glob("round_*"))
    rows, detail = [], {}
    for b, x in sorted(L["books"].items(), key=lambda kv: -kv[1]["replayed_return"]):
        metas = [json.loads(p.read_text(encoding="utf-8")) for p in run_dir.glob(f"round_*/{b}/meta.json")]
        cost = sum(dashboard.cost(m["model"], m)[0] for m in metas)
        tokens = sum(dashboard.cost(m["model"], m)[1] for m in metas)
        rejected = []
        for rd in rounds:
            t = rd / b / "tools.jsonl"
            for line in t.read_text(encoding="utf-8").splitlines() if t.exists() else []:
                c = json.loads(line)
                if c["tool"] == "place_order" and c.get("verdict") != "accepted":
                    rejected.append(f"round {rd.name[-2:]}: {c['args'].get('side')} {c['args'].get('symbol')} -> {c['result']}")
        pnl = per_symbol(run_dir, b, prices, final) if b != "B5" else {}
        best = max(pnl.items(), key=lambda kv: kv[1]) if pnl else None
        worst = min(pnl.items(), key=lambda kv: kv[1]) if pnl else None
        secs = [m.get("seconds", 0) for m in metas]
        detail[b] = {**x, "cost_usd": cost, "tokens": tokens, "rejected": rejected, "pnl_by_symbol": pnl,
                     "alpaca_equity": marks.get(b), "avg_seconds": sum(secs) / len(secs) if secs else None,
                     "timeouts": sum(bool(m.get("timed_out")) for m in metas)}
        rows.append(f"| {b} {LABEL[b]} | {100 * x['replayed_return']:+.3f}% | {100 * (x['replayed_return'] - L['spy_return']):+.3f} | "
                    f"{x['trades']} | {len(rejected)} | {100 * x['percentile']:.0f}% | "
                    f"{('$%s' % format(marks[b], ',.2f')) if b in marks else 'n/a'} | {tokens:,} | "
                    f"{'≈' if 'deepseek' in LABEL[b].lower() or b == 'B5' else ''}${cost:.3f} | "
                    f"{(best[0] + ' ' + format(best[1], '+,.0f')) if best else 'n/a'} / {(worst[0] + ' ' + format(worst[1], '+,.0f')) if worst else 'n/a'} |")
    lines = [f"# Harness Arena report: {run}", "",
             f"Mode {meta.get('mode', '?')}. {len(rounds)} rounds. SPY over the same span {100 * L['spy_return']:+.3f}%. "
             f"Luck test: {L['sims']:,} random books per book, same footprint, random symbols.", "",
             "| Book | Return | vs SPY (pts) | Trades | Rejected | Beats random | Alpaca equity | Tokens | Cost | Best / worst stock ($) |",
             "|---|---|---|---|---|---|---|---|---|---|", *rows, "",
             "Returns are replayed at the round snapshot prices, the same basis as the luck test. "
             "≈ marks DeepSeek costs estimated from tokens; the day's DeepSeek balance settles them.", ""]
    for b, d in detail.items():
        if d["rejected"]:
            lines += [f"## {b} rejected orders", "", *[f"- {r}" for r in d["rejected"][:12]], ""]
    for b in detail:
        grade = run_dir / "debrief" / b / "answer.md"
        detail[b]["debrief"] = grade.read_text(encoding="utf-8").strip() if grade.exists() else ""
        if detail[b]["debrief"]:
            lines += [f"## {b} {LABEL[b]}: its own grade after the close (debrief.py)", "", detail[b]["debrief"], ""]
    for b in detail:
        detail[b]["timeline"] = timeline(run_dir, b) if b != "B5" else []
        if b == "B5":
            detail[b]["b5"] = b5_logic(run_dir)
        lines += [f"## {b} {LABEL[b]}: logic round by round", ""]
        for r in detail[b]["timeline"]:
            lines.append(f"**Round {r['round']}, {r['time']}**")
            lines += [f"- {'ok' if o['ok'] else 'REJECTED'} {o['side']} {o['symbol']} {o['amount']}: {o['reason']}" for o in r["orders"]] or ["- no orders"]
            lines += [f"  - note: {r['note'][:400]}", ""]
    I = insights(run_dir, L, detail, prices, final)
    head = ["## Headline numbers", "",
            "| Book | P&L | AI cost | P&L after AI | Turnover | Est. trading costs | P&L after all costs | Cost per order | Max drawdown | % invested by round | Orders asked / ok / rule-rejected / filled at Alpaca |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for b, x in I["books"].items():
        f = x["funnel"]
        head.append(f"| {b} {LABEL[b]} | {x['pnl_usd']:+,.2f} | {detail[b]['cost_usd']:.3f} | {x['pnl_after_ai_usd']:+,.2f} | "
                    f"${x['turnover_usd']:,.0f} | {x['est_trading_cost_usd']:.2f} | {x['pnl_after_all_costs_usd']:+,.2f} | "
                    f"{('$%.4f' % x['cost_per_order_usd']) if x['cost_per_order_usd'] else 'n/a'} | "
                    f"{('%.2f%%' % (100 * x['max_drawdown'])) if x['max_drawdown'] is not None else 'n/a'} | "
                    f"{' > '.join(f'{100 * v:.0f}%' for v in x['invested_by_round']) or 'n/a'} | "
                    f"{f['asked']} / {f['accepted']} / {f['rejected_by_rules']} / {f['filled_at_alpaca']} |")
    if "harness_effect_pts" in I:
        head += ["", f"**Harness vs model (2x2):** Claude Code minus dsh {I['harness_effect_pts']:+.3f} pts; "
                     f"Haiku minus DeepSeek {I['model_effect_pts']:+.3f} pts."]
    head += ["", "**Herding:** " + "; ".join(f"R{h['round']} {h['time']}: overlap {h['overlap']:.2f}, held by all {', '.join(h['held_by_all']) or 'none'}"
                                            for h in I["herding"]),
             "", "**SPY as a ghost book:** " + ", ".join(f"{g['at']} ${g['usd']:,.0f}" for g in I["spy_ghost"]),
             "", f"Data: {I['data_feed']}.", ""]
    at = 6 + len(rows) + 3                      # after the title block, the leaderboard rows and its footnote
    lines[at:at] = head
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    (run_dir / "report.json").write_text(json.dumps({"run": run, "luck": L, "books": detail, "insights": I}, indent=1, default=str), encoding="utf-8")
    led = dashboard.ledger(run_dir, rounds)
    chart = marks_chart(run_dir) or dashboard.chart(led)          # live: real minute marks of all five books
    (run_dir / "report.html").write_text(html_page(run, L, detail, chart, led["times"], I), encoding="utf-8")
    return run_dir / "report.md"


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--sims", type=int, default=10_000)
    a = ap.parse_args()
    p = build(a.run, a.sims)
    print(p.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
