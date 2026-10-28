"""Read-only check of the five Alpaca paper books. Prints no key, only whether each is a paper key.

    py -3 check_accounts.py

For each book: key present and paper (PK), status, equity, cash, positions, open orders,
PDT flag. Then one market data call (SPY snapshot, free IEX feed) and a check that no two books share an account.
"""
from __future__ import annotations

import httpx

import env_keys
from broker import BOOK_KEYS as BOOKS

PAPER = "https://paper-api.alpaca.markets/v2"
DATA = "https://data.alpaca.markets/v2"


def headers(book: str) -> dict | None:
    k, s = BOOKS[book]
    try:
        return {"APCA-API-KEY-ID": env_keys.obter(k), "APCA-API-SECRET-KEY": env_keys.obter(s)}
    except RuntimeError:
        return None


def main() -> int:
    seen, ok, data_headers = {}, True, None
    for book in BOOKS:
        h = headers(book)
        if h is None:
            print(f"{book}  key or secret missing from the environment (see .env.example)")
            ok = False
            continue
        if not h["APCA-API-KEY-ID"].startswith("PK"):
            print(f"{book}  key does not start with PK: not a paper key, not used")
            ok = False
            continue
        with httpx.Client(base_url=PAPER, headers=h, timeout=15) as api:
            r = api.get("/account")
            if r.status_code != 200:
                print(f"{book}  paper key, account call HTTP {r.status_code}")
                ok = False
                continue
            a = r.json()
            n_pos = len(api.get("/positions").json())
            n_ord = len(api.get("/orders", params={"status": "open"}).json())
        acct = str(a["account_number"])
        seen.setdefault(acct, []).append(book)
        data_headers = data_headers or h
        print(f"{book}  paper key  {a['status']:<7} equity {float(a['equity']):>12,.2f}  "
              f"cash {float(a['cash']):>12,.2f}  positions {n_pos}  open orders {n_ord}  PDT {a.get('pattern_day_trader')}")
    shared = {acct: books for acct, books in seen.items() if len(books) > 1}
    for acct, books in shared.items():
        print(f"SHARED ACCOUNT: {', '.join(books)} use the same paper account")
        ok = False
    if data_headers:
        r = httpx.get(f"{DATA}/stocks/snapshots", params={"symbols": "SPY", "feed": "iex"}, headers=data_headers, timeout=15)
        last = r.json().get("SPY", {}).get("latestTrade", {}) if r.status_code == 200 else {}
        print(f"market data (IEX)  HTTP {r.status_code}  SPY last {last.get('p')} at {str(last.get('t'))[:19]}")
        ok = ok and r.status_code == 200
    print("all five books ready" if ok and len(seen) == 5 else "not ready, see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
