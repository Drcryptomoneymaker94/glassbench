"""Several arena days as one experiment: each book's real Alpaca equity day by day, against SPY over the same span.

    py -3 combine.py live-1026 live-1027        writes runs/summary_<first>_<last>.md and .json

Per day: the start and end equity at Alpaca (first and last minute mark), the day's return, SPY's return over the
same minutes, the luck percentile and the costs from that day's report. In total: compounded returns, the AI bill,
the estimated trading costs and what Alpaca itself charged between days (cash that moved while every book was flat).
"""
from __future__ import annotations

import json
import sys

from report import LABEL, minute_marks
from snapshot import RUNS

BOOKS = ["B1", "B2", "B3", "B4", "B5"]


def day(run: str) -> dict:
    d = RUNS / run
    marks = minute_marks(d)
    rep = json.loads((d / "report.json").read_text(encoding="utf-8")) if (d / "report.json").exists() else {}
    spy = marks.get("SPY", [])
    out = {"run": run, "spy_return": spy[-1][1] / spy[0][1] - 1 if len(spy) > 1 else None, "books": {}}
    for b in BOOKS:
        s = marks.get(b, [])
        if len(s) < 2:
            continue
        x = rep.get("books", {}).get(b, {})
        i = rep.get("insights", {}).get("books", {}).get(b, {})
        out["books"][b] = {"start": s[0][1], "end": s[-1][1], "return": s[-1][1] / s[0][1] - 1,
                           "percentile": x.get("percentile"), "ai_cost": x.get("cost_usd", 0.0),
                           "trading_cost_est": i.get("est_trading_cost_usd", 0.0), "turnover": i.get("turnover_usd", 0.0),
                           "slippage_est": i.get("est_slippage_usd", 0.0), "sec_fee_est": i.get("est_sec_fee_usd", 0.0),
                           "trades": x.get("trades"), "max_drawdown": i.get("max_drawdown")}
    return out


def combine(runs: list[str]) -> dict:
    days = [day(r) for r in runs]
    total: dict = {}
    for b in BOOKS:
        rows = [dd["books"][b] for dd in days if b in dd["books"]]
        if not rows:
            continue
        growth = 1.0
        for r in rows:
            growth *= 1 + r["return"]
        between = [days[k + 1]["books"][b]["start"] - days[k]["books"][b]["end"]
                   for k in range(len(days) - 1) if b in days[k]["books"] and b in days[k + 1]["books"]]
        # Alpaca posts each day's SEC fee the next morning, so the end equity already holds every day's fee but the last.
        pnl, ai, slip, fee_due = rows[-1]["end"] - 100_000.0, sum(r["ai_cost"] for r in rows), \
            sum(r["slippage_est"] for r in rows), rows[-1]["sec_fee_est"]
        total[b] = {"return": growth - 1, "pnl_from_100k": pnl,
                    "ai_cost": ai, "trading_cost_est": sum(r["trading_cost_est"] for r in rows),
                    "slippage_est": slip, "sec_fee_due_last_day": fee_due,
                    "pnl_after_costs": pnl - ai - slip - fee_due,
                    "turnover": sum(r["turnover"] for r in rows), "alpaca_charged_between_days": sum(between),
                    "percentiles": [r["percentile"] for r in rows]}
    spy = 1.0
    for dd in days:
        spy *= 1 + (dd["spy_return"] or 0)
    return {"runs": runs, "days": days, "total": total, "spy_return": spy - 1}


def write(c: dict) -> str:
    name = f"summary_{c['runs'][0]}_{c['runs'][-1]}"
    lines = [f"# Harness Arena: {len(c['runs'])} days ({', '.join(c['runs'])})", "",
             f"SPY over the same minutes: {100 * c['spy_return']:+.2f}%", "",
             "| Book | " + " | ".join(f"Day {k + 1}" for k in range(len(c["days"]))) +
             " | Total | vs SPY (pts) | End equity | AI bill | Est. slippage | Equity change between days |"
             " Last day's SEC fee, due | P&L after costs | Beats random (by day) |",
             "|---|" + "---|" * len(c["days"]) + "---|---|---|---|---|---|---|---|---|"]
    for b, t in sorted(c["total"].items(), key=lambda kv: -kv[1]["return"]):
        per = " | ".join(f"{100 * dd['books'][b]['return']:+.2f}%" if b in dd["books"] else "n/a" for dd in c["days"])
        pct = ", ".join(f"{100 * p:.0f}%" if p is not None else "n/a" for p in t["percentiles"])
        lines.append(f"| {b} {LABEL[b]} | {per} | {100 * t['return']:+.2f}% | {100 * (t['return'] - c['spy_return']):+.2f} | "
                     f"${100_000 + t['pnl_from_100k']:,.2f} | ${t['ai_cost']:.3f} | ${t['slippage_est']:.2f} | "
                     f"${t['alpaca_charged_between_days']:+.2f} | ${t['sec_fee_due_last_day']:.2f} | "
                     f"${t['pnl_after_costs']:+,.2f} | {pct} |")
    lines += ["", "Returns from Alpaca's own equity, first to last minute mark each day, compounded. "
              "AI bill: Haiku from Claude Code's own report or tokens at Anthropic's price; DeepSeek estimated from "
              "tokens (B5's TradingAgents research is settled from the DeepSeek balance, about $2 a day, and is not in "
              "this column). Est. slippage: 2 bps a trade, which paper fills leave out. Equity change between days: "
              "Alpaca's SEC and CAT fees on the day's sales, posted the next morning (B5's also holds the price move of "
              "its late close on day 1). The last day's SEC fee is not posted yet, so it is estimated at $20.6 per $1M of "
              "sales. P&L after costs = end equity minus $100,000, the AI bill, the slippage and the fee still due."]
    md = "\n".join(lines) + "\n"
    (RUNS / f"{name}.md").write_text(md, encoding="utf-8")
    (RUNS / f"{name}.json").write_text(json.dumps(c, indent=1), encoding="utf-8")
    return md


if __name__ == "__main__":
    print(write(combine(sys.argv[1:] or ["live-1026", "live-1027"])))
