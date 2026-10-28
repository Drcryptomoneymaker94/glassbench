"""B5: TradingAgents v0.7.0 as released, on DeepSeek. It rates the universe before the open; at the open its Buy and
Overweight names are bought with the trader's stop-loss attached, and held until the day's sell-off.

    py -3 ta_book.py rate   --run <run_id> [--workers 6] [--tickers NVDA,AAPL] [--date YYYY-MM-DD]
    py -3 ta_book.py orders --run <run_id> --mode dry|live

Rate: one TradingAgents run per stock (ta_worker.py in the TradingAgents venv, ARENA_TA_PYTHON), several at a time, each in its own
folder runs/<run>/B5/<ticker>/ with the full result and TradingAgents' logs.
Orders: Buy = 2 units, Overweight = 1, Hold or lower = 0. Weight = units / total units, at most 20% of the book per
stock, so the rest stays in cash. Whole shares, market day orders; when the trader states a stop-loss below the
price, the order carries it as an OTO stop. Every order is logged in runs/<run>/B5/orders.jsonl.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
from snapshot import RUNS, universe

# Python of a separate venv with TradingAgents v0.7.0 installed; this one when unset.
TA_PY = Path(os.environ.get("ARENA_TA_PYTHON") or sys.executable)
ET = ZoneInfo("America/New_York")
UNITS = {"Buy": 2, "Overweight": 1}
MAX_WEIGHT = 0.20
LIMIT_S = 1200


def rate_one(ticker: str, date: str, out: Path, env: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    with (out / "stdout.log").open("wb") as so, (out / "stderr.log").open("wb") as se:
        p = subprocess.Popen([str(TA_PY), str(HERE / "ta_worker.py"), ticker, date, str(out)], stdout=so, stderr=se, env=env)
        try:
            code = p.wait(timeout=LIMIT_S)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            code = "timeout"
    res = out / "result.json"
    rating = json.loads(res.read_text(encoding="utf-8"))["rating"] if res.exists() else None
    return {"ticker": ticker, "rating": rating, "exit": code, "seconds": round(time.time() - t0, 1)}


def rate(run: str, tickers: list[str], date: str, workers: int) -> list[dict]:
    import env_keys

    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("CLAUDE", "ANTHROPIC", "MCP_", "DSH_", "OPENAI"))}
    env |= {"DEEPSEEK_API_KEY": env_keys.obter("DEEPSEEK_API_KEY"), "FRED_API_KEY": env_keys.obter("FRED_API_KEY"), "PYTHONUTF8": "1",
            "ARENA_TA_CACHE": str(RUNS / run / "B5" / "_data_cache")}
    base = RUNS / run / "B5"
    with ThreadPoolExecutor(workers) as pool:
        rows = list(pool.map(lambda t: rate_one(t, date, base / t, env), tickers))
    (base / "ratings.json").write_text(json.dumps({"date": date, "rows": rows}, indent=1), encoding="utf-8")
    return rows


def stop_level(plan: str, price: float) -> float | None:
    """The trader's stop-loss, when the plan states one as a price below today's."""
    m = re.search(r"stop[\s-]*loss[^0-9$]{0,40}\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)", plan or "", re.I)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    return v if 0.5 * price < v < price else None


def plan_orders(run: str, equity: float, prices: dict[str, float]) -> list[dict]:
    base = RUNS / run / "B5"
    picks = []
    for d in sorted(p for p in base.iterdir() if (p / "result.json").exists()):
        r = json.loads((d / "result.json").read_text(encoding="utf-8"))
        if r["rating"] in UNITS:
            picks.append(r)
    total = sum(UNITS[r["rating"]] for r in picks)
    orders = []
    for r in picks:
        px = prices.get(r["ticker"])
        if not px:
            continue
        w = min(MAX_WEIGHT, UNITS[r["rating"]] / total)
        qty = math.floor(w * equity / px)
        if qty < 1:
            continue
        orders.append({"symbol": r["ticker"], "rating": r["rating"], "weight": round(w, 4), "qty": qty, "price": px,
                       "stop": stop_level(r.get("trader_investment_plan", ""), px)})
    return orders


def place(run: str, mode: str) -> list[dict]:
    from broker import Broker
    from snapshot import freeze

    log = RUNS / run / "B5" / "orders.jsonl"
    rd = freeze(run, 1)
    prices = {r["ticker"]: r["last"] for r in json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))["rows"] if r["last"]}
    if mode == "live":
        b = Broker("B5")
        equity = float(b.account()["equity"])
    else:
        b, equity = None, 100_000.0
    out = []
    for o in plan_orders(run, equity, prices):
        body = {"symbol": o["symbol"], "side": "buy", "type": "market", "time_in_force": "day", "qty": str(o["qty"]),
                "client_order_id": f"{run}-B5-open-{o['symbol']}"}
        if o["stop"]:
            body |= {"order_class": "oto", "stop_loss": {"stop_price": f"{o['stop']:.2f}"}}
        if b is not None:
            res = b.api.post("/orders", json=body)
            resp = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text[:300]
            rec = {**o, "status_code": res.status_code, "response": resp}
        else:
            rec = {**o, "status_code": 200, "response": {"status": "dry", "filled_avg_price": o["price"], "filled_qty": o["qty"]}}
        rec["ts"] = datetime.now(ET).isoformat()
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        out.append(rec)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("cmd", choices=["rate", "orders"])
    ap.add_argument("--run", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tickers")
    ap.add_argument("--date", default=datetime.now(ET).date().isoformat())
    ap.add_argument("--mode", choices=["dry", "live"], default="dry")
    a = ap.parse_args()
    if a.cmd == "rate":
        tickers = a.tickers.split(",") if a.tickers else [u["ticker"] for u in universe()]
        for r in rate(a.run, tickers, a.date, a.workers):
            print(f"  {r['ticker']:<6} {str(r['rating']):<12} exit {r['exit']}  {r['seconds']} s")
    else:
        for o in place(a.run, a.mode):
            print(f"  {o['symbol']:<6} {o['rating']:<10} {o['qty']} sh  weight {o['weight']:.0%}  stop {o['stop']}  -> {o['status_code']}")


if __name__ == "__main__":
    main()
