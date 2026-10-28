"""broker: the dry broker's bookkeeping, and the live broker's paper-only guards. No network."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import broker  # noqa: E402
from broker import PAPER, Broker, DryBroker, order_body  # noqa: E402
from rules_engine import Order  # noqa: E402

PRICES = {"NVDA": 200.0, "JPM": 300.0}


def dry():
    return DryBroker("B1", PRICES.__getitem__)


def test_buy_then_sell_updates_cash_positions_and_equity():
    b = dry()
    assert b.submit(Order("NVDA", "buy", dollars=10_000), "r1-NVDA")["status_code"] == 200
    assert b.positions()["NVDA"]["qty"] == "50.0" and b.account()["cash"] == "90000.00"
    PRICES["NVDA"] = 220.0
    assert b.account()["equity"] == "101000.00"
    b.submit(Order("NVDA", "sell", qty=25), "r2-NVDA")
    assert float(b.account()["cash"]) == 90_000 + 25 * 220
    assert b.positions()["NVDA"]["avg_entry_price"] == "200.0000"
    PRICES["NVDA"] = 200.0


def test_duplicate_client_order_id_is_refused_like_alpaca():
    b = dry()
    b.submit(Order("JPM", "buy", dollars=600), "same")
    assert b.submit(Order("JPM", "buy", dollars=600), "same")["status_code"] == 422


def test_close_all_flattens_the_book():
    b = dry()
    b.submit(Order("NVDA", "buy", dollars=1_000), "a")
    b.submit(Order("JPM", "buy", dollars=900), "b")
    b.close_all()
    assert b.positions() == {} and b.account()["cash"] == "100000.00"


def test_state_maps_the_account_into_a_rules_book():
    b = dry()
    b.submit(Order("JPM", "buy", dollars=3_000), "x")
    s = b.state(ordered=("JPM",), pending=500.0)
    assert s.cash == 97_000 and s.positions["JPM"].qty == 10 and s.pending_buys == 500.0


def test_order_body_is_a_market_day_order():
    assert order_body(Order("NVDA", "buy", dollars=1234.5), "id") == {
        "symbol": "NVDA", "side": "buy", "type": "market", "time_in_force": "day", "client_order_id": "id",
        "notional": "1234.50"}
    assert order_body(Order("NVDA", "sell", qty=2.5), "id")["qty"] == "2.5"


def test_live_broker_refuses_a_key_that_is_not_paper(monkeypatch):
    import env_keys

    monkeypatch.setattr(env_keys, "obter", lambda name: "AKLIVEKEY" if name.endswith("KEY") else "secret")
    with pytest.raises(ValueError, match="not a paper key"):
        broker.headers("B1")


def test_live_broker_refuses_a_non_paper_endpoint():
    with pytest.raises(ValueError, match="non-paper"):
        Broker("B1", client=httpx.Client(base_url="https://api.alpaca.markets/v2"))
    assert str(Broker("B1", client=httpx.Client(base_url=PAPER)).api.base_url).rstrip("/") == PAPER
