"""One arena book's broker: its own Alpaca PAPER account, or an in-memory dry broker with the same interface.

Safety: paper keys only (they start with PK), the paper endpoint only,
keys read from environment variables (env_keys.py) and never printed. Every order is a market day order with a client order ID,
so Alpaca refuses a second copy of the same order. Orders reach a broker only after rules_engine.check() accepts them.
"""
from __future__ import annotations

import itertools
from typing import Callable

import httpx

from rules_engine import Book, Order, Position

PAPER = "https://paper-api.alpaca.markets/v2"
DATA = "https://data.alpaca.markets"
BOOK_KEYS = {
    "B1": ("ALPACA_B1_KEY", "ALPACA_B1_SECRET"),
    "B2": ("ALPACA_B2_KEY", "ALPACA_B2_SECRET"),
    "B3": ("ALPACA_B3_KEY", "ALPACA_B3_SECRET"),
    "B4": ("ALPACA_B4_KEY", "ALPACA_B4_SECRET"),
    "B5": ("ALPACA_B5_KEY", "ALPACA_B5_SECRET"),
}


def headers(book: str) -> dict[str, str]:
    import env_keys

    k, s = BOOK_KEYS[book]
    key, secret = env_keys.obter(k), env_keys.obter(s)
    if not key.startswith("PK"):
        raise ValueError(f"{book}: key does not start with PK, so it is not a paper key")
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def book_state(account: dict, positions: dict[str, dict], ordered: tuple[str, ...] = (), pending: float = 0.0) -> Book:
    return Book(
        equity=float(account["equity"]),
        cash=float(account["cash"]),
        positions={s: Position(float(p["qty"]), float(p["market_value"])) for s, p in positions.items()},
        ordered_this_round=ordered,
        pending_buys=pending,
    )


def order_body(order: Order, client_order_id: str) -> dict:
    body = {"symbol": order.symbol, "side": order.side, "type": "market", "time_in_force": "day",
            "client_order_id": client_order_id}
    if order.side == "buy":
        body["notional"] = f"{order.dollars:.2f}"
    else:
        body["qty"] = f"{order.qty}"
    return body


class Broker:
    """A book's Alpaca paper account."""

    def __init__(self, book: str, client: httpx.Client | None = None):
        self.book = book
        self.api = client or httpx.Client(base_url=PAPER, timeout=15, headers=headers(book))
        if str(self.api.base_url).rstrip("/") != PAPER:
            raise ValueError(f"{book}: refusing a non-paper endpoint")

    def account(self) -> dict:
        return self.api.get("/account").raise_for_status().json()

    def positions(self) -> dict[str, dict]:
        return {p["symbol"]: p for p in self.api.get("/positions").raise_for_status().json()}

    def open_orders(self) -> list[dict]:
        return self.api.get("/orders", params={"status": "open"}).raise_for_status().json()

    def clock(self) -> dict:
        return self.api.get("/clock").raise_for_status().json()

    def state(self, ordered: tuple[str, ...] = (), pending: float = 0.0) -> Book:
        return book_state(self.account(), self.positions(), ordered, pending)

    def submit(self, order: Order, client_order_id: str) -> dict:
        res = self.api.post("/orders", json=order_body(order, client_order_id))
        out: dict = {"status_code": res.status_code}
        out["response"] = res.json() if res.headers.get("content-type", "").startswith("application/json") else res.text[:300]
        return out

    def cancel_all(self) -> int:
        return self.api.delete("/orders").status_code

    def close_all(self) -> int:
        return self.api.delete("/positions", params={"cancel_orders": "true"}).status_code


class DryBroker:
    """Same interface, in memory: every market order fills at once at price(symbol). For tests and dry runs."""

    def __init__(self, book: str, price: Callable[[str], float], cash: float = 100_000.0, is_open: bool = True):
        self.book, self.price, self.cash, self.is_open = book, price, cash, is_open
        self.qty: dict[str, float] = {}
        self.cost: dict[str, float] = {}
        self.ids: set[str] = set()
        self.log: list[dict] = []
        self._n = itertools.count(1)

    def account(self) -> dict:
        equity = self.cash + sum(q * self.price(s) for s, q in self.qty.items())
        return {"equity": f"{equity:.2f}", "cash": f"{self.cash:.2f}", "status": "ACTIVE", "account_number": f"DRY{self.book}"}

    def positions(self) -> dict[str, dict]:
        return {s: {"symbol": s, "qty": f"{q}", "market_value": f"{q * self.price(s):.2f}",
                    "current_price": f"{self.price(s)}", "avg_entry_price": f"{self.cost[s] / q:.4f}"}
                for s, q in self.qty.items() if q > 1e-9}

    def open_orders(self) -> list[dict]:
        return []

    def clock(self) -> dict:
        return {"is_open": self.is_open}

    def state(self, ordered: tuple[str, ...] = (), pending: float = 0.0) -> Book:
        return book_state(self.account(), self.positions(), ordered, pending)

    def submit(self, order: Order, client_order_id: str) -> dict:
        if client_order_id in self.ids:
            return {"status_code": 422, "response": {"message": "client_order_id must be unique"}}
        self.ids.add(client_order_id)
        px = self.price(order.symbol)
        if order.side == "buy":
            q = (order.dollars or 0.0) / px
            self.cash -= order.dollars or 0.0
            self.qty[order.symbol] = self.qty.get(order.symbol, 0.0) + q
            self.cost[order.symbol] = self.cost.get(order.symbol, 0.0) + (order.dollars or 0.0)
        else:
            q = min(order.qty or 0.0, self.qty.get(order.symbol, 0.0))
            avg = self.cost[order.symbol] / self.qty[order.symbol]
            self.cash += q * px
            self.qty[order.symbol] -= q
            self.cost[order.symbol] -= q * avg
        resp = {"id": f"dry-{next(self._n)}", "status": "filled", "symbol": order.symbol, "side": order.side,
                "filled_qty": f"{q}", "filled_avg_price": f"{px}", "client_order_id": client_order_id}
        self.log.append(resp)
        return {"status_code": 200, "response": resp}

    def dump(self) -> dict:
        return {"cash": self.cash, "qty": self.qty, "cost": self.cost, "ids": sorted(self.ids), "log": self.log}

    def restore(self, d: dict) -> DryBroker:
        self.cash, self.qty, self.cost = d["cash"], dict(d["qty"]), dict(d["cost"])
        self.ids, self.log = set(d["ids"]), list(d["log"])
        self._n = itertools.count(len(self.log) + 1)
        return self

    def cancel_all(self) -> int:
        return 207

    def close_all(self) -> int:
        for s, q in list(self.qty.items()):
            if q > 1e-9:
                self.submit(Order(s, "sell", qty=q), f"dry-close-{s}-{next(self._n)}")
        return 207
