"""Health check of a running arena day: is everything still alive?

    py -3 health.py --run live-1026                    one report now
    py -3 health.py --run live-1026 --wait 600         wait until the next round finishes, a problem shows, or 600 s pass

Checks: day.log still moving, minute marks fresh, each book's equity at Alpaca, the latest round's exits, timeouts and
errors, B5's rating progress and orders, the DeepSeek balance. Prints names and numbers only.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from broker import Broker
from snapshot import RUNS


def rounds_done(run_dir: Path) -> int:
    n = 0
    for rd in sorted(run_dir.glob("round_*")):
        if all((rd / b / "meta.json").exists() for b in ("B1", "B2", "B3", "B4")):
            n += 1
    return n


def problems_and_report(run: str) -> tuple[list[str], list[str]]:
    d = RUNS / run
    rep, bad = [], []
    log = d / "day.log"
    age = time.time() - log.stat().st_mtime if log.exists() else 1e9
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    rep.append(f"day.log: last line {age / 60:.1f} min ago: {lines[-1][:110] if lines else '(empty)'}")
    if lines and "day done" in lines[-1]:
        rep.append("the day has finished")
    marks = d / "marks.csv"
    if marks.exists():
        m_age = time.time() - marks.stat().st_mtime
        rep.append(f"marks.csv: {sum(1 for _ in marks.open(encoding='utf-8')) - 1} rows, last write {m_age:.0f} s ago")
        if m_age > 180 and not (lines and "day done" in lines[-1]):
            bad.append(f"marks stale for {m_age / 60:.1f} min: is day.py still running?")
    for b in ("B1", "B2", "B3", "B4", "B5"):
        try:
            br = Broker(b)
            a, pos = br.account(), br.positions()
            rep.append(f"{b} Alpaca equity ${float(a['equity']):,.2f}, cash ${float(a['cash']):,.2f}, {len(pos)} positions")
        except Exception as e:
            bad.append(f"{b} Alpaca read failed: {e.__class__.__name__}")
    rounds = sorted(d.glob("round_*"))
    if rounds:
        last = rounds[-1]
        for b in ("B1", "B2", "B3", "B4"):
            mf = last / b / "meta.json"
            if not mf.exists():
                rep.append(f"{last.name} {b}: running")
                continue
            m = json.loads(mf.read_text(encoding="utf-8"))
            err = (last / b / "stderr.log").read_text(encoding="utf-8", errors="replace") if (last / b / "stderr.log").exists() else ""
            calls = (last / b / "tools.jsonl").read_text(encoding="utf-8").count('"place_order"') if (last / b / "tools.jsonl").exists() else 0
            rep.append(f"{last.name} {b}: exit {m.get('exit_code')}, {m.get('seconds')} s, {calls} orders asked")
            if m.get("exit_code") != 0 or m.get("timed_out"):
                bad.append(f"{last.name} {b}: exit {m.get('exit_code')}, timed out {m.get('timed_out')}")
            if "Error" in err:
                bad.append(f"{last.name} {b}: stderr has an Error line")
    b5 = d / "B5"
    if b5.exists():
        done = len(list(b5.glob("*/result.json")))
        started = len([p for p in b5.iterdir() if p.is_dir() and not p.name.startswith("_")])
        orders = (b5 / "orders.jsonl").read_text(encoding="utf-8").splitlines() if (b5 / "orders.jsonl").exists() else []
        rep.append(f"B5 TradingAgents: {done} of 20 rated ({started} started), {len(orders)} orders placed")
        for o in map(json.loads, orders):
            if o.get("status_code", 500) >= 300:
                bad.append(f"B5 order {o['symbol']} HTTP {o['status_code']}")
    try:
        import env_keys

        bal = httpx.get("https://api.deepseek.com/user/balance", headers={"Authorization": f"Bearer {env_keys.obter('DEEPSEEK_API_KEY')}"},
                        timeout=15).json()
        info = (bal.get("balance_infos") or [{}])[0]
        total = float(info.get("total_balance", 0))
        rep.append(f"DeepSeek balance {info.get('currency', '')} {total:.2f}")
        if total < 1:
            bad.append(f"DeepSeek balance low: {total:.2f}")
    except Exception as e:
        rep.append(f"DeepSeek balance unknown ({e.__class__.__name__})")
    return bad, rep


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--wait", type=int, default=0)
    a = ap.parse_args()
    d = RUNS / a.run
    if a.wait:
        start, n0 = time.time(), rounds_done(d)
        def kinds(problems: list[str]) -> set[str]:                 # "balance low: 0.98" and "...: 0.90" are one kind
            return {re.sub(r"[\d.,$]+", "#", p) for p in problems}

        known = kinds(problems_and_report(a.run)[0])                # wake only for problems that are new
        while time.time() - start < a.wait:
            time.sleep(30)
            if rounds_done(d) > n0:
                time.sleep(10)
                break
            bad, _ = problems_and_report(a.run)
            if kinds(bad) - known:
                break
    bad, rep = problems_and_report(a.run)
    print(datetime.now(timezone.utc).astimezone().strftime("%H:%M:%S"), f"rounds done {rounds_done(d)}")
    print("PROBLEMS:\n  " + "\n  ".join(bad) if bad else "no problems found")
    print("\n".join("  " + x for x in rep))


if __name__ == "__main__":
    main()
