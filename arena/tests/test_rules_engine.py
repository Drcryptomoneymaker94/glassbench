"""rules_engine.check: every order rule, with no network and no clock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rules_engine import MAX_ORDERS, Book, Order, Position, after, check  # noqa: E402

U = {"NVDA", "AAPL", "JPM", "XOM", "BRK.B"}
OPEN, T = True, "10:00"


def book(cash=100_000.0, equity=100_000.0, **pos):
    return Book(equity=equity, cash=cash, positions={s: Position(q, v) for s, (q, v) in pos.items()})


def test_buy_within_limits_is_accepted_and_normalised():
    v = check(Order(" nvda ", "BUY", dollars=10_000.004), book(), U, OPEN, T)
    assert v.ok and v.order == Order("NVDA", "buy", dollars=10_000.0)


def test_symbol_outside_the_universe_is_rejected():
    assert "not in the universe" in check(Order("MSFT", "buy", dollars=1_000), book(), U, OPEN, T).reason


def test_market_closed_and_late_orders_are_rejected():
    assert check(Order("NVDA", "buy", dollars=1_000), book(), U, False, T).reason == "market is closed"
    assert "after 15:40" in check(Order("NVDA", "buy", dollars=1_000), book(), U, OPEN, "15:40").reason
    assert check(Order("NVDA", "buy", dollars=1_000), book(), U, OPEN, "15:39").ok


def test_bad_side_is_rejected():
    assert "buy or sell" in check(Order("NVDA", "short", dollars=1_000), book(), U, OPEN, T).reason


def test_buy_below_the_minimum_is_rejected():
    assert "at least" in check(Order("NVDA", "buy", dollars=499.99), book(), U, OPEN, T).reason


def test_buy_needs_dollars_only():
    assert not check(Order("NVDA", "buy", qty=10), book(), U, OPEN, T).ok
    assert not check(Order("NVDA", "buy", dollars=float("nan")), book(), U, OPEN, T).ok
    assert not check(Order("NVDA", "buy", dollars=1_000, all=True), book(), U, OPEN, T).ok


def test_buy_cannot_use_margin_or_pending_cash():
    assert "cash available" in check(Order("NVDA", "buy", dollars=5_000), book(cash=4_000), U, OPEN, T).reason
    b = Book(equity=100_000, cash=10_000, pending_buys=8_000)
    assert "2,000.00" in check(Order("NVDA", "buy", dollars=3_000), b, U, OPEN, T).reason


def test_position_cap_counts_what_is_already_held():
    b = book(NVDA=(100, 15_000.0))
    v = check(Order("NVDA", "buy", dollars=6_000), b, U, OPEN, T)
    assert not v.ok and "at most $5,000.00 more" in v.reason
    assert check(Order("NVDA", "buy", dollars=5_000), b, U, OPEN, T).ok


def test_sell_all_takes_the_whole_position():
    v = check(Order("JPM", "sell", all=True), book(JPM=(12.5, 4_000.0)), U, OPEN, T)
    assert v.ok and v.order.qty == 12.5


def test_sell_more_than_held_or_nothing_held_is_rejected():
    assert "only 3 JPM held" in check(Order("JPM", "sell", qty=4), book(JPM=(3, 900.0)), U, OPEN, T).reason
    assert "no XOM held" in check(Order("XOM", "sell", qty=1), book(), U, OPEN, T).reason


def test_sell_takes_shares_not_dollars():
    assert not check(Order("JPM", "sell", dollars=500), book(JPM=(3, 900.0)), U, OPEN, T).ok
    assert not check(Order("JPM", "sell", qty=0), book(JPM=(3, 900.0)), U, OPEN, T).ok


def test_fractional_sell_is_floored_to_six_decimals():
    v = check(Order("JPM", "sell", qty=1.23456789), book(JPM=(3, 900.0)), U, OPEN, T)
    assert v.ok and v.order.qty == 1.234567


def test_one_order_per_symbol_and_a_cap_per_round():
    b = after(book(), Order("NVDA", "buy", dollars=1_000))
    assert "already has an order" in check(Order("NVDA", "buy", dollars=1_000), b, U, OPEN, T).reason
    full = Book(equity=100_000, cash=100_000, ordered_this_round=tuple(f"X{i}" for i in range(MAX_ORDERS)))
    assert "limit of" in check(Order("NVDA", "buy", dollars=1_000), full, U, OPEN, T).reason


def test_after_counts_pending_buys_but_not_sells():
    b = after(book(), Order("NVDA", "buy", dollars=2_000))
    b = after(b, Order("JPM", "sell", qty=1))
    assert b.pending_buys == 2_000 and b.ordered_this_round == ("NVDA", "JPM")
