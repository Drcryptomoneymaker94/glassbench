"""The arena's trading day: a round every 30 minutes on the market clock, equity marks every minute, the sell-off,
Keeps the PC awake while it runs (Windows).

    py -3 day.py --run <run_id> --mode live                    a full session: rounds 09:30, 10:00 ... 15:30 New York
    py -3 day.py --run <run_id> --mode live --from-now         join a session already open, from the next half hour
    py -3 day.py --run <run_id> --mode dry --rounds 3 --interval 2   quick dry rehearsal, a round every 2 minutes

Rounds sit on fixed half hours from the open (Alpaca's calendar), so they never drift: round k starts at
open + 30 (k - 1) minutes, the last one at least 30 minutes before the close. Every book is sold 10 minutes before
the close. The four prompted books trade in every round; B5 (TradingAgents) is handled by ta_book.py at the open when
it is in --books. Everything lands in runs/<run>/: the rounds, marks.csv, day.log, dashboard.html.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

import dashboard
from broker import DATA, Broker, DryBroker, headers
from run_round import play_round
from snapshot import RUNS

HERE = Path(__file__).resolve().parent
ET = ZoneInfo("America/New_York")
STEP = timedelta(minutes=30)
FLATTEN_BEFORE_CLOSE = timedelta(minutes=10)
COST_CAP_USD = 15.0
RATE_BEFORE_OPEN = timedelta(minutes=45)
PROMPTED = ["B1", "B2", "B3", "B4"]


class Day:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.dir = RUNS / a.run
        self.dir.mkdir(parents=True, exist_ok=True)
        self.books = [b.strip() for b in a.books.split(",") if b.strip()]
        self.stop = threading.Event()

    # ------------------------------------------------------------------ log
    def log(self, msg: str) -> None:
        line = f"{datetime.now(ET).strftime('%H:%M:%S')} ET  {msg}"
        print(line, flush=True)
        with (self.dir / "day.log").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ------------------------------------------------------------- schedule
    def schedule(self) -> tuple[list[datetime], datetime]:
        now = datetime.now(ET)
        if self.a.mode == "dry" and self.a.interval:
            first = now + timedelta(seconds=20)
            slots = [first + timedelta(minutes=self.a.interval * k) for k in range(self.a.rounds or 3)]
            return slots, slots[-1] + timedelta(minutes=self.a.interval)
        cal = Broker("B1").api.get("/calendar", params={"start": now.date().isoformat(), "end": now.date().isoformat()}).json()
        if not cal:
            raise SystemExit("no trading session today (Alpaca calendar)")
        day = cal[0]
        open_ = datetime.fromisoformat(f"{day['date']}T{day['open']}").replace(tzinfo=ET)
        close = datetime.fromisoformat(f"{day['date']}T{day['close']}").replace(tzinfo=ET)
        slots, t = [], open_
        if self.a.start_now:                       # first round right away, then every 30 minutes from there
            t = now + timedelta(seconds=20)
        while t <= close - STEP:
            slots.append(t)
            t += STEP
        if self.a.from_now:
            slots = [s for s in slots if s >= now - timedelta(seconds=30)]
        if self.a.rounds:
            slots = slots[: self.a.rounds]
        return slots, close - FLATTEN_BEFORE_CLOSE

    def wait_until(self, t: datetime) -> None:
        while not self.stop.is_set():
            left = (t - datetime.now(ET)).total_seconds()
            if left <= 0:
                return
            time.sleep(min(20.0, left))

    # ---------------------------------------------------------------- marks
    def marks(self) -> None:
        f = self.dir / "marks.csv"
        if not f.exists():
            f.write_text("ts_utc,book,equity,cash,long_value\n", encoding="utf-8")
        brokers = {b: Broker(b) for b in self.books}
        while not self.stop.is_set():
            rows = []
            for b, br in brokers.items():
                try:
                    acc = br.account()
                    rows.append(f"{datetime.now(timezone.utc).isoformat()},{b},{acc['equity']},{acc['cash']},{acc.get('long_market_value', '')}")
                except Exception as e:
                    self.log(f"mark {b} failed: {e.__class__.__name__}")
            try:
                r = httpx.get(f"{DATA}/v2/stocks/trades/latest", params={"symbols": "SPY", "feed": "iex"}, headers=headers("B1"), timeout=10)
                rows.append(f"{datetime.now(timezone.utc).isoformat()},SPY,{r.json()['trades']['SPY']['p']},,")
            except Exception as e:
                self.log(f"mark SPY failed: {e.__class__.__name__}")
            with f.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(rows) + "\n")
            self.stop.wait(60)

    # -------------------------------------------------------------- the day
    def flatten(self) -> None:
        if self.a.mode == "live":
            # Cancel first: an open stop order holds its shares, and on 26 Oct B5's close was refused while its
            # OTO stops were still being cancelled. Then close, check, and close again what is left.
            for b in self.books:
                try:
                    self.log(f"cancel open orders {b}: HTTP {Broker(b).cancel_all()}")
                except Exception as e:
                    self.log(f"cancel {b} FAILED: {e}")
            time.sleep(5)
            for attempt in range(3):
                for b in self.books:
                    try:
                        if Broker(b).positions():
                            self.log(f"flatten {b}: HTTP {Broker(b).close_all()}")
                    except Exception as e:
                        self.log(f"flatten {b} FAILED: {e}")
                time.sleep(30)
                left = {b: list(Broker(b).positions()) for b in self.books}
                for b, pos in left.items():
                    self.log(f"{b} after flatten: {len(pos)} positions{' ' + ', '.join(pos) if pos else ''}")
                if not any(left.values()):
                    break
            return
        last = sorted(self.dir.glob("round_*"))[-1]
        px = {r["ticker"]: r["last"] for r in json.loads((last / "snapshot.json").read_text(encoding="utf-8"))["rows"] if r["last"]}
        for b in self.books:
            state = self.dir / "books" / f"{b}.json"
            if state.exists():
                d = DryBroker(b, px.__getitem__).restore(json.loads(state.read_text(encoding="utf-8")))
                d.close_all()
                state.write_text(json.dumps(d.dump(), indent=1), encoding="utf-8")
                self.log(f"flatten {b} (dry): cash {d.cash:,.2f}")

    def b5_when_rated(self) -> None:
        """Mid-session start: TradingAgents rates the universe now and B5 buys as soon as the ratings are in."""
        import ta_book

        self.log("B5 TradingAgents: rating 20 stocks, 6 at a time (orders as soon as it finishes)")
        for r in ta_book.rate(self.a.run, [u["ticker"] for u in ta_book.universe()], datetime.now(ET).date().isoformat(), 6):
            self.log(f"  B5 {r['ticker']:<6} {str(r['rating']):<12} exit {r['exit']} {r['seconds']} s")
        if self.stop.is_set():
            return
        for o in ta_book.place(self.a.run, self.a.mode):
            self.log(f"  B5 order {o['symbol']} {o['rating']} {o['qty']} sh, stop {o['stop']} -> HTTP {o['status_code']}")

    def save_final_prices(self) -> None:
        """Last trade of every stock and SPY just before the sell-off: the price every book is marked at."""
        try:
            syms = [u["ticker"] for u in json.loads((HERE / "universe.json").read_text(encoding="utf-8"))["universe"]] + ["SPY"]
            r = httpx.get(f"{DATA}/v2/stocks/trades/latest", params={"symbols": ",".join(syms), "feed": "iex"},
                          headers=headers("B1"), timeout=15).json()["trades"]
            (self.dir / "final_prices.json").write_text(json.dumps({s: t["p"] for s, t in r.items()}, indent=1), encoding="utf-8")
            self.log(f"final prices saved for {len(r)} symbols")
        except Exception as e:
            self.log(f"final prices failed: {e.__class__.__name__}")

    def spent(self) -> float:
        total = 0.0
        for meta in self.dir.glob("round_*/B*/meta.json"):
            m = json.loads(meta.read_text(encoding="utf-8"))
            total += dashboard.cost(m["model"], m)[0]
        return total

    def run(self) -> None:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)   # stay awake until the day ends
        slots, flatten_at = self.schedule()
        n = len(slots)
        self.log(f"run {self.a.run} ({self.a.mode}), books {', '.join(self.books)}, {n} rounds: "
                 + ", ".join(s.strftime("%H:%M") for s in slots) + f"; flatten {flatten_at.strftime('%H:%M')} ET")
        if self.a.mode == "live":
            threading.Thread(target=self.marks, daemon=True).start()
        prompted = [b for b in self.books if b in PROMPTED]
        try:
            if "B5" in self.books and self.a.start_now:
                threading.Thread(target=self.b5_when_rated, daemon=True).start()
            elif "B5" in self.books:
                rate_at = slots[0] - RATE_BEFORE_OPEN
                if rate_at > datetime.now(ET):
                    self.log(f"B5 TradingAgents rates the universe at {rate_at.strftime('%H:%M')} ET")
                    self.wait_until(rate_at)
                self.log("B5 TradingAgents: rating 20 stocks, 6 at a time")
                import ta_book
                for r in ta_book.rate(self.a.run, [u["ticker"] for u in ta_book.universe()],
                                      datetime.now(ET).date().isoformat(), 6):
                    self.log(f"  B5 {r['ticker']:<6} {str(r['rating']):<12} exit {r['exit']} {r['seconds']} s")
            for k, slot in enumerate(slots, 1):
                self.wait_until(slot)
                if "B5" in self.books and k == 1 and not self.a.start_now:
                    import ta_book
                    for o in ta_book.place(self.a.run, self.a.mode):
                        self.log(f"  B5 order {o['symbol']} {o['rating']} {o['qty']} sh, stop {o['stop']} -> HTTP {o['status_code']}")
                if self.spent() > COST_CAP_USD:
                    self.log(f"cost cap ${COST_CAP_USD:.0f} reached: no more rounds")
                    break
                self.log(f"round {k} of {n} starts")
                for line in play_round(self.a.run, k, prompted, self.a.mode, self.a.now_et, rounds=n):
                    self.log(line)
                dashboard.build(self.a.run, refresh=30)
                self.log(f"round {k} done, spend so far about ${self.spent():.3f}")
            self.wait_until(flatten_at)
            self.save_final_prices()
            self.log("sell-off: closing every position")
            self.flatten()
            dashboard.build(self.a.run, refresh=30)
            try:
                import report

                self.log(f"report: {report.build(self.a.run, 10_000)}")
            except Exception as e:
                self.log(f"report failed: {e.__class__.__name__}: {e}")
            self.log(f"day done. spend about ${self.spent():.3f}. files in {self.dir}")
        finally:
            self.stop.set()
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--mode", choices=["dry", "live"], default="dry")
    ap.add_argument("--books", default="B1,B2,B3,B4,B5")
    ap.add_argument("--from-now", action="store_true", help="skip slots already past")
    ap.add_argument("--start-now", action="store_true", help="first round right away, then every 30 minutes")
    ap.add_argument("--rounds", type=int, help="at most this many rounds")
    ap.add_argument("--interval", type=float, help="dry mode only: minutes between rounds instead of the half hours")
    ap.add_argument("--now-et", help="dry mode only: the New York time the order rules see")
    Day(ap.parse_args()).run()


if __name__ == "__main__":
    main()
