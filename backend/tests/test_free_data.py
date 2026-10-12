"""The free data adapter for AI Hedge Fund (drivers/free_data.py): arithmetic and point-in-time rules, offline.

Filings are a hand-made SEC companyfacts payload shaped like NVIDIA's around its 2024 split: fiscal year to
2024-01-28 (10-K filed 2024-02-21), first quarter to 2024-04-28 (10-Q filed 2024-05-29), a 10:1 split on
2024-06-10. Prices are served the way Yahoo does, already divided by the later split.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("free_data", Path(__file__).resolve().parents[1] / "drivers" / "free_data.py")
free_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(free_data)

K, Q = "0001045810-24-000029", "0001045810-24-000124"  # accession numbers: the 10-K and the 10-Q


def _flow(start, end, val, form, filed, accn):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "accn": accn}


def _point(end, val, form, filed, accn):
    return {"end": end, "val": val, "form": form, "filed": filed, "accn": accn}


def _usd(*facts):
    return {"units": {"USD": list(facts)}}


FACTS = {"cik": 1045810, "entityName": "NVIDIA CORP", "facts": {
    "us-gaap": {
        "Revenues": _usd(
            _flow("2023-01-30", "2024-01-28", 60_922e6, "10-K", "2024-02-21", K),
            _flow("2024-01-29", "2024-04-28", 26_044e6, "10-Q", "2024-05-29", Q),
            _flow("2023-01-30", "2023-04-30", 7_192e6, "10-Q", "2024-05-29", Q),
            # A later amendment restating the quarter: not what was public on 2024-05-29.
            _flow("2024-01-29", "2024-04-28", 99_999e6, "10-Q/A", "2024-07-01", "amendment"),
        ),
        # A narrower tag reporting a slice of revenue in the same filing: the largest revenue figure wins.
        "RevenueFromContractWithCustomerExcludingAssessedTax": _usd(
            _flow("2024-01-29", "2024-04-28", 1_000e6, "10-Q", "2024-05-29", Q),
        ),
        "NetIncomeLoss": _usd(
            _flow("2023-01-30", "2024-01-28", 29_760e6, "10-K", "2024-02-21", K),
            _flow("2024-01-29", "2024-04-28", 14_881e6, "10-Q", "2024-05-29", Q),
            _flow("2023-01-30", "2023-04-30", 2_043e6, "10-Q", "2024-05-29", Q),
        ),
        "StockholdersEquity": _usd(_point("2024-01-28", 42_978e6, "10-K", "2024-02-21", K),
                                   _point("2024-04-28", 49_142e6, "10-Q", "2024-05-29", Q)),
        "AssetsCurrent": _usd(_point("2024-04-28", 53_729e6, "10-Q", "2024-05-29", Q)),
        "LiabilitiesCurrent": _usd(_point("2024-04-28", 13_997e6, "10-Q", "2024-05-29", Q)),
        "LongTermDebtNoncurrent": _usd(_point("2024-04-28", 8_460e6, "10-Q", "2024-05-29", Q)),
        "LongTermDebtCurrent": _usd(_point("2024-04-28", 1_250e6, "10-Q", "2024-05-29", Q)),
        # The total of the two above: counted once, not added on top.
        "LongTermDebt": _usd(_point("2024-04-28", 9_710e6, "10-Q", "2024-05-29", Q)),
    },
    "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [
        _point("2024-02-16", 2_464e6, "10-K", "2024-02-21", K),
        _point("2024-05-24", 2_460e6, "10-Q", "2024-05-29", Q),
    ]}}},
}}

# Yahoo's closes for these days come divided by the 10:1 split that followed.
CLOSES = [("2024-02-21", 67.48), ("2024-05-24", 106.47), ("2024-05-28", 113.90), ("2024-05-29", 114.83)]
SPLITS = [("2024-06-10", 10.0)]


def _client():
    client = free_data.FreeDataClient(cache_dir=None)
    client._facts["NVDA"] = FACTS
    client._history["NVDA"] = (CLOSES, SPLITS)
    return client


class FreeDataTest(unittest.TestCase):
    def test_one_row_per_filing_dated_by_the_filing_day(self):
        rows = _client()._ttm_rows("NVDA")
        self.assertEqual([(r["report_period"], r["filing_date"]) for r in rows],
                         [("2024-01-28", "2024-02-21"), ("2024-04-28", "2024-05-29")])

    def test_a_row_is_invisible_until_the_day_it_was_filed(self):
        client = _client()
        self.assertEqual([r["report_period"] for r in client.visible_rows("NVDA", "2024-05-28")], ["2024-01-28"])
        self.assertEqual([r["report_period"] for r in client.visible_rows("NVDA", "2024-05-29")], ["2024-04-28", "2024-01-28"])

    def test_quarterly_ttm_is_fiscal_year_plus_ytd_minus_prior_ytd_as_filed(self):
        q = _client().visible_rows("NVDA", "2024-12-31")[0]
        revenue = 60_922e6 + 26_044e6 - 7_192e6  # the amendment and the narrower tag change nothing
        net = 29_760e6 + 14_881e6 - 2_043e6
        self.assertAlmostEqual(q["net_margin"], net / revenue)
        self.assertAlmostEqual(q["earnings_per_share"], net / 2_460e6)
        self.assertAlmostEqual(q["return_on_equity"], net / 49_142e6)
        self.assertAlmostEqual(q["current_ratio"], 53_729e6 / 13_997e6)

    def test_market_cap_uses_the_close_of_the_filing_day_on_its_own_share_basis(self):
        q = _client().visible_rows("NVDA", "2024-12-31")[0]
        self.assertAlmostEqual(q["market_cap"], 114.83 * 10 * 2_460e6)  # split undone: 1,148.30 traded on 2024-05-29
        k = _client().visible_rows("NVDA", "2024-12-31")[1]
        self.assertAlmostEqual(k["market_cap"], 67.48 * 10 * 2_464e6)
        self.assertAlmostEqual(k["price_to_earnings_ratio"], 67.48 * 10 * 2_464e6 / 29_760e6)

    def test_debt_counts_the_current_portion_once(self):
        q = _client().visible_rows("NVDA", "2024-12-31")[0]
        self.assertAlmostEqual(q["debt_to_equity"], (8_460e6 + 1_250e6) / 49_142e6)

    def test_growth_needs_the_row_a_year_earlier(self):
        rows = _client().visible_rows("NVDA", "2024-12-31")
        self.assertIsNone(rows[0]["revenue_growth"])  # no filing a year before in this payload: no number invented

    def test_a_ticker_sec_does_not_know_has_no_rows(self):
        client = _client()
        client._facts["ZZZZ"] = {}
        self.assertEqual(client.visible_rows("ZZZZ", "2024-12-31"), [])


if __name__ == "__main__":
    unittest.main()
