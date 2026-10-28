"""The arena's three trading tools for one book, served over MCP: get_snapshot, get_portfolio, place_order.

    py -3 arena_mcp.py --run <run_id> --book B1 --round 3 --mode dry|live [--now-et HH:MM]

Each harness starts it at the beginning of a round: dsh through its mcp-client plugin, Claude Code through
--mcp-config. Settings arrive as arguments because dsh strips KEY/SECRET/TOKEN names from a server's environment;
the server reads the book's Alpaca keys itself, so an agent never sees one. Every order passes rules_engine.check()
first, and every call is appended to runs/<run>/round_NN/<book>/tools.jsonl.

Dry mode fills orders in memory at the round's snapshot prices and keeps the book in runs/<run>/books/<book>.json.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP

from broker import Broker, DryBroker
from rules_engine import Order, after, check
from snapshot import RUNS, round_dir, universe

ET = ZoneInfo("America/New_York")
NOTE_BEGIN, NOTE_END, NOTE_MAX = "----- begin note -----", "----- end note -----", 4000
mcp = FastMCP("arena", log_level="WARNING")
A: argparse.Namespace


def paths() -> tuple[Path, Path, Path]:
    rd = round_dir(A.run, A.round)
    bd = rd / A.book
    bd.mkdir(parents=True, exist_ok=True)
    return rd, bd, RUNS / A.run / "books" / f"{A.book}.json"


def log(tool: str, args: dict, result: str, extra: dict | None = None) -> None:
    _, bd, _ = paths()
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "run": A.run, "round": A.round, "book": A.book,
           "tool": tool, "args": args, "result": result, **(extra or {})}
    with (bd / "tools.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


def prices() -> dict[str, float]:
    rd, _, _ = paths()
    data = json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))
    return {r["ticker"]: r["last"] for r in data["rows"] if r["last"]}


def broker():
    if A.mode == "live":
        return Broker(A.book)
    _, _, state = paths()
    b = DryBroker(A.book, prices().__getitem__)
    if state.exists():
        b.restore(json.loads(state.read_text(encoding="utf-8")))
    return b


def save(b) -> None:
    if isinstance(b, DryBroker):
        _, _, state = paths()
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps(b.dump(), indent=1), encoding="utf-8")


def clock(b) -> tuple[bool, str]:
    if A.mode == "live":
        c = b.clock()
        return bool(c["is_open"]), datetime.fromisoformat(c["timestamp"]).astimezone(ET).strftime("%H:%M")
    return True, A.now_et or datetime.now(ET).strftime("%H:%M")


def ordered() -> tuple[str, ...]:
    _, bd, _ = paths()
    f = bd / "round_state.json"
    return tuple(json.loads(f.read_text(encoding="utf-8"))["ordered"]) if f.exists() else ()


def money(x: float) -> str:
    return f"-${-x:,.2f}" if x < 0 else f"${x:,.2f}"


@mcp.tool()
def get_snapshot() -> str:
    """This round's market snapshot (the 20 tradable stocks, prices, moves today, latest headlines) and the note you
    left at the end of the previous round."""
    rd, _, _ = paths()
    text = (rd / "snapshot.md").read_text(encoding="utf-8")
    prev = round_dir(A.run, A.round - 1) / A.book / "note.md"
    note = prev.read_text(encoding="utf-8").strip() if prev.exists() else "(none: this is your first round)"
    note = note.replace(NOTE_BEGIN, "").replace(NOTE_END, "")
    if len(note) > NOTE_MAX:
        note = note[:NOTE_MAX] + " [cut at 4,000 characters]"
    out = f"{text}\n## Your note from the previous round\n\n{NOTE_BEGIN}\n{note}\n{NOTE_END}\n"
    log("get_snapshot", {}, f"snapshot sha256 {json.loads((rd / 'snapshot.json').read_text())['sha256'][:12]}, note {len(note)} chars")
    return out


@mcp.tool()
def get_portfolio() -> str:
    """Your book now: equity, cash, positions with cost and profit, and the orders already placed this round."""
    b = broker()
    acct, pos = b.account(), b.positions()
    equity, cash = float(acct["equity"]), float(acct["cash"])
    lines = [f"Equity {money(equity)} | cash {money(cash)} | invested {100 * (1 - cash / equity):.1f}% | started at $100,000.00"]
    if pos:
        lines.append("Positions:")
        for s, p in sorted(pos.items()):
            q, v, avg = float(p["qty"]), float(p["market_value"]), float(p["avg_entry_price"])
            pl = v - q * avg
            lines.append(f"  {s:<6} {q:g} shares, avg cost {money(avg)}, now {money(float(p['current_price']))}, "
                         f"value {money(v)}, P&L {money(pl)} ({100 * pl / (q * avg):+.2f}%), {100 * v / equity:.1f}% of book")
    else:
        lines.append("Positions: none")
    done = ordered()
    lines.append(f"Orders placed this round: {', '.join(done) if done else 'none'}")
    opens = b.open_orders()
    if opens:
        lines.append("Open (not yet filled) orders: " + ", ".join(f"{o['side']} {o['symbol']}" for o in opens))
    out = "\n".join(lines)
    log("get_portfolio", {}, out)
    return out


@mcp.tool()
def place_order(symbol: str, side: str, dollars: float | None = None, qty: float | None = None,
                sell_all: bool = False, reason: str = "") -> str:
    """Place a market order now. Buy: give dollars (at least 500). Sell: give qty in shares, or sell_all=true.
    Always give a short reason. Returns ACCEPTED with the fill, or REJECTED with why."""
    args = {"symbol": symbol, "side": side, "dollars": dollars, "qty": qty, "sell_all": sell_all, "reason": reason}
    b = broker()
    is_open, now = clock(b)
    opens = b.open_orders()
    pending = sum(float(o.get("notional") or 0) for o in opens if o["side"] == "buy")
    book = b.state(ordered(), pending)
    v = check(Order(symbol, side, dollars=dollars, qty=qty, all=sell_all), book, {u["ticker"] for u in universe()}, is_open, now)
    if not v.ok or v.order is None:
        out = f"REJECTED: {v.reason}"
        log("place_order", args, out, {"verdict": "rejected", "now_et": now})
        return out
    o = v.order
    cid = f"{A.run}-{A.book}-r{A.round:02d}-{o.symbol}-{o.side}"[:128]
    res = b.submit(o, cid)
    save(b)
    r = res["response"] if isinstance(res["response"], dict) else {"message": str(res["response"])}
    if res["status_code"] >= 300:
        out = f"REJECTED by the broker: {r.get('message', res['status_code'])}"
        log("place_order", args, out, {"verdict": "broker_rejected", "now_et": now, "broker": res})
        return out
    _, bd, _ = paths()
    (bd / "round_state.json").write_text(json.dumps({"ordered": list(after(book, o).ordered_this_round)}), encoding="utf-8")
    what = f"buy {money(o.dollars or 0)} of {o.symbol}" if o.side == "buy" else f"sell {o.qty:g} {o.symbol}"
    fill = (f", filled {float(r['filled_qty']):.4f} shares at {money(float(r['filled_avg_price']))}"
            if r.get("filled_avg_price") else f", status {r.get('status')}")
    out = f"ACCEPTED: {what}{fill} (order {str(r.get('id', ''))[:8]})"
    log("place_order", args, out, {"verdict": "accepted", "now_et": now, "order": o.__dict__, "broker": res})
    return out


def main() -> None:
    global A
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--book", required=True, choices=["B1", "B2", "B3", "B4", "B5"])
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--mode", choices=["dry", "live"], default="dry")
    ap.add_argument("--now-et", help="dry mode only: the New York time the rules see, HH:MM")
    A = ap.parse_args()
    paths()
    log("server_start", {"mode": A.mode, "pid_time": time.time()}, "started")
    mcp.run()


if __name__ == "__main__":
    main()
