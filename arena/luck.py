"""The luck test: could a monkey with the same habits have done as well?

For each book, 10,000 random books copy its footprint round by round: the same number of buys of the same dollar sizes
and the same sells (the same fraction of a position), but on symbols drawn at random from the universe, under the same
20% cap and no margin, filled at the same round prices and marked at the same final prices. The book's percentile is
the share of random books it beat. Prices are the round snapshots for everyone (the real book is replayed the same
way), so the comparison is like for like; the report shows Alpaca's actual fills next to it.

    py -3 luck.py --run <run_id> [--sims 10000]
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from snapshot import RUNS, universe

START = 100_000.0
MAX_WEIGHT = 0.20


def round_prices(run_dir: Path) -> list[dict[str, float]]:
    out = []
    for rd in sorted(run_dir.glob("round_*")):
        snap = json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))
        out.append({r["ticker"]: r["last"] for r in snap["rows"] if r["last"]})
    return out


def final_prices(run_dir: Path, rounds: list[dict[str, float]]) -> dict[str, float]:
    f = run_dir / "final_prices.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else rounds[-1]


def footprint(run_dir: Path, book: str, prices: list[dict[str, float]]) -> list[list[tuple]]:
    """Per round: ('buy', symbol, dollars) and ('sell', symbol, fraction of the position held then). Shares held are
    tracked at the round prices, so a partial sell becomes the same fraction for the random books."""
    rounds = []
    shares: dict[str, float] = {}
    for k, rd in enumerate(sorted(run_dir.glob("round_*"))):
        px = prices[min(k, len(prices) - 1)]
        acts = []
        tools = rd / book / "tools.jsonl"
        for line in tools.read_text(encoding="utf-8").splitlines() if tools.exists() else []:
            c = json.loads(line)
            if c["tool"] != "place_order" or c.get("verdict") != "accepted":
                continue
            o = c["order"]
            s = o["symbol"]
            if o["side"] == "buy":
                acts.append(("buy", s, float(o["dollars"])))
                shares[s] = shares.get(s, 0.0) + float(o["dollars"]) / px[s]
            else:
                held = shares.get(s, 0.0)
                frac = 1.0 if o.get("all") or held <= 0 else min(1.0, float(o["qty"]) / held)
                shares[s] = held * (1 - frac)
                acts.append(("sell", s, frac))
        rounds.append(acts)
    return rounds


def b5_footprint(run_dir: Path) -> list[list[tuple]]:
    log = run_dir / "B5" / "orders.jsonl"
    if not log.exists():
        return []
    buys = [("buy", o["symbol"], o["qty"] * o["price"]) for o in map(json.loads, log.read_text(encoding="utf-8").splitlines())
            if o.get("status_code", 500) < 300]
    return [buys]


def play(acts_by_round: list[list[tuple]], prices: list[dict[str, float]], final: dict[str, float],
         pick=None, symbols: list[str] | None = None) -> float:
    """Return of a book that follows the footprint; pick=None replays the real symbols, else draws them."""
    cash, qty = START, {}
    for k, acts in enumerate(acts_by_round):
        px = prices[min(k, len(prices) - 1)]
        equity = cash + sum(q * px[s] for s, q in qty.items())
        used = set()
        for kind, sym, amount in acts:
            if kind == "sell":
                if pick:
                    choices = [s for s, q in qty.items() if q > 1e-9 and s not in used]
                    if not choices:
                        continue
                    sym = pick(choices)
                q = qty.get(sym, 0.0) * amount
                if q <= 0:
                    continue
                qty[sym] -= q
                cash += q * px[sym]
            else:
                if pick:
                    choices = [s for s in (symbols or []) if s not in used and s in px]
                    sym = pick(choices)
                room = MAX_WEIGHT * equity - qty.get(sym, 0.0) * px[sym]
                d = min(amount, cash, max(0.0, room))
                if d < 1:
                    continue
                qty[sym] = qty.get(sym, 0.0) + d / px[sym]
                cash -= d
            used.add(sym)
    return (cash + sum(q * final.get(s, 0.0) for s, q in qty.items())) / START - 1


def luck(run: str, sims: int = 10_000, seed: int = 7) -> dict:
    run_dir = RUNS / run
    prices = round_prices(run_dir)
    final = final_prices(run_dir, prices)
    symbols = [u["ticker"] for u in universe()]
    rng = random.Random(seed)
    out = {"spy_return": final["SPY"] / prices[0]["SPY"] - 1, "sims": sims, "books": {}}
    books = {b: footprint(run_dir, b, prices) for b in ("B1", "B2", "B3", "B4")}
    if (run_dir / "B5" / "orders.jsonl").exists():
        books["B5"] = b5_footprint(run_dir)
    for b, fp in books.items():
        if not any(fp):
            continue
        real = play(fp, prices, final)
        rand = sorted(play(fp, prices, final, pick=rng.choice, symbols=symbols) for _ in range(sims))
        beat = sum(r < real for r in rand) / sims
        out["books"][b] = {"replayed_return": real, "percentile": beat, "random_median": rand[sims // 2],
                           "random_p05": rand[int(sims * 0.05)], "random_p95": rand[int(sims * 0.95)],
                           "trades": sum(len(a) for a in fp)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--sims", type=int, default=10_000)
    a = ap.parse_args()
    r = luck(a.run, a.sims)
    print(f"SPY {100 * r['spy_return']:+.2f}%   ({r['sims']:,} random books per book)")
    for b, x in r["books"].items():
        print(f"  {b}  return {100 * x['replayed_return']:+.3f}%  beats {100 * x['percentile']:.0f}% of random books"
              f"  (random median {100 * x['random_median']:+.3f}%, 90% range {100 * x['random_p05']:+.3f}% to {100 * x['random_p95']:+.3f}%)")


if __name__ == "__main__":
    main()
