"""Order checks for the arena. Pure functions: no network, no clock, no keys.

Every order an agent asks for goes through check() before it reaches a broker. A rejected order is logged with its
reason and returned to the agent, which may try again in the same round. Only accepted orders count toward the
per-round limits.

    Buy    dollars, at least MIN_BUY, paid from cash (no margin), position after the trade at most MAX_WEIGHT of equity
    Sell   shares, at most what is held (long only); all=True sells the whole position
    Both   symbol in the universe, market open, before LAST_ORDER_ET, at most MAX_ORDERS per round, one per symbol
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import TypeGuard

MIN_BUY = 500.0
MAX_WEIGHT = 0.20
MAX_ORDERS = 10
LAST_ORDER_ET = "15:40"


@dataclass(frozen=True)
class Position:
    qty: float
    market_value: float


@dataclass(frozen=True)
class Book:
    equity: float
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    ordered_this_round: tuple[str, ...] = ()       # symbols with an accepted order this round
    pending_buys: float = 0.0                       # dollars of accepted buys not yet filled


@dataclass(frozen=True)
class Order:
    symbol: str
    side: str
    dollars: float | None = None
    qty: float | None = None
    all: bool = False


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str
    order: Order | None = None


def _finite(x: object) -> TypeGuard[float]:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def check(order: Order, book: Book, universe: set[str], market_open: bool, now_et: str) -> Verdict:
    sym, side = order.symbol.strip().upper(), order.side.strip().lower()
    if sym not in universe:
        return Verdict(False, f"{sym} is not in the universe")
    if side not in ("buy", "sell"):
        return Verdict(False, f"side must be buy or sell, got {order.side!r}")
    if not market_open:
        return Verdict(False, "market is closed")
    if now_et >= LAST_ORDER_ET:
        return Verdict(False, f"no new orders after {LAST_ORDER_ET} ET")
    if len(book.ordered_this_round) >= MAX_ORDERS:
        return Verdict(False, f"limit of {MAX_ORDERS} orders this round reached")
    if sym in book.ordered_this_round:
        return Verdict(False, f"{sym} already has an order this round")
    held = book.positions.get(sym, Position(0.0, 0.0))

    if side == "buy":
        raw = order.dollars
        if not _finite(raw) or order.qty is not None or order.all:
            return Verdict(False, "a buy takes dollars only")
        dollars = round(float(raw), 2)
        if dollars < MIN_BUY:
            return Verdict(False, f"buy at least ${MIN_BUY:,.0f}")
        cash = book.cash - book.pending_buys
        if dollars > cash:
            return Verdict(False, f"only ${max(cash, 0):,.2f} of cash available (no margin)")
        room = MAX_WEIGHT * book.equity - held.market_value
        if dollars > room:
            return Verdict(False, f"{sym} would exceed {MAX_WEIGHT:.0%} of equity: at most ${max(room, 0):,.2f} more")
        return Verdict(True, "accepted", Order(sym, "buy", dollars=dollars))

    if held.qty <= 0:
        return Verdict(False, f"no {sym} held (long only)")
    if order.all:
        return Verdict(True, "accepted", Order(sym, "sell", qty=held.qty, all=True))
    raw = order.qty
    if not _finite(raw) or order.dollars is not None or raw <= 0:
        return Verdict(False, "a sell takes a positive share quantity, or all=True")
    qty = math.floor(float(raw) * 1e6) / 1e6
    if qty > held.qty + 1e-9:
        return Verdict(False, f"only {held.qty:g} {sym} held (long only)")
    return Verdict(True, "accepted", Order(sym, "sell", qty=qty))


def after(book: Book, order: Order) -> Book:
    """The book once an accepted order is counted for this round (fills arrive later from the broker)."""
    added = (order.dollars or 0.0) if order.side == "buy" else 0.0
    return replace(book, ordered_this_round=book.ordered_this_round + (order.symbol,), pending_buys=book.pending_buys + added)
