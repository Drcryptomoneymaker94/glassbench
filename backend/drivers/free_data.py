"""Free data for AI Hedge Fund: Yahoo Finance prices and earnings dates, SEC EDGAR statements.

Not native to AI Hedge Fund. Its own data client reads everything from
Financial Datasets (prepaid credits, Virat Singh's company). This is
Glassbench's own adapter, written against AI Hedge Fund's `DataClient`
protocol, so every analyst runs unchanged on data that costs nothing:

- Prices: daily bars from Yahoo Finance, closes adjusted for splits only.
- Fundamentals: every 10-Q and 10-K in SEC EDGAR is one trailing twelve month
  row, dated by the day it was filed, so a row is visible only from the day it
  became public (the protocol's point-in-time rule). Flows are the fiscal year
  itself, or the last fiscal year plus this year to date minus last year to
  date, all as filed by that day. Ratios are computed here from those figures.
- Earnings surprises for the drift model: Yahoo's earnings calendar (reported
  against estimated EPS), dated by the announcement, labelled 8-K because the
  release is furnished on one that day.
- Sector and industry: Yahoo's current profile, the same accepted
  approximation AI Hedge Fund makes with Financial Datasets' company facts.

Where it falls short of the native data: Financial Datasets normalises every
filer into one schema, while XBRL tags differ between companies, so a figure a
filer tags unusually comes back empty here; Yahoo's EPS are the adjusted figures
analysts estimate, not GAAP; news and insider trades are not served (no
analyst in 2.5.0 reads them). Results can differ from a Financial Datasets run.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
QUARTERLY_FORMS = ("10-Q", "10-K")

REVENUE = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "RevenuesNetOfInterestExpense")
COST_OF_REVENUE = ("CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold")
GROSS_PROFIT = ("GrossProfit",)
OPERATING_INCOME = ("OperatingIncomeLoss",)
NET_INCOME = ("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic")
OPERATING_CASH = ("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
CAPEX = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
EQUITY = ("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")
CURRENT_ASSETS = ("AssetsCurrent",)
CURRENT_LIABILITIES = ("LiabilitiesCurrent",)
DEBT_TOTAL = ("LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "LongTermDebtAndCapitalLeaseObligations")
DEBT_PARTS = ("LongTermDebtNoncurrent", "LongTermDebtCurrent", "CommercialPaper", "ShortTermBorrowings")
SHARES_BALANCE = ("CommonStockSharesOutstanding",)
SHARES_COVER = ("EntityCommonStockSharesOutstanding",)


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


def _span(fact: dict) -> int:
    return (_day(fact["end"]) - _day(fact["start"])).days if fact.get("start") else 0


class FreeDataClient:
    """AI Hedge Fund's DataClient protocol on Yahoo Finance and SEC EDGAR."""

    source = "yahoo"

    def __init__(self, cache_dir: Path | str | None = None):
        self._dir = Path(cache_dir) if cache_dir else None
        email = os.environ.get("SEC_EDGAR_EMAIL", "").strip()
        # SEC refuses a User-Agent without a contact address.
        self._agent = f"Glassbench free data adapter {email or 'contact@example.com'}"
        self._facts: dict[str, dict] = {}
        self._yf: dict[str, object] = {}
        self._history: dict[str, tuple] = {}

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------
    def _sec(self, url: str, name: str, max_age: float) -> dict:
        import requests

        cached = self._dir / "sec" / name if self._dir else None
        if cached and cached.exists() and time.time() - cached.stat().st_mtime < max_age:
            return json.loads(cached.read_text(encoding="utf-8"))
        res = requests.get(url, headers={"User-Agent": self._agent, "Accept-Encoding": "gzip, deflate"}, timeout=30)
        if res.status_code != 200:
            raise RuntimeError(f"SEC EDGAR returned {res.status_code} for {url}")
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            tmp = cached.with_suffix(".tmp")
            tmp.write_text(res.text, encoding="utf-8")
            os.replace(tmp, cached)
        time.sleep(0.12)  # far below SEC's 10 requests a second
        return res.json()

    def _cik(self, ticker: str) -> int | None:
        symbol = ticker.upper().replace(".", "-")
        for row in self._sec(TICKERS_URL, "company_tickers.json", 7 * 86400).values():
            if str(row.get("ticker", "")).upper() == symbol:
                return int(row["cik_str"])
        return None

    def _company(self, ticker: str) -> dict:
        key = ticker.upper()
        if key not in self._facts:
            cik = self._cik(key)
            self._facts[key] = {} if cik is None else self._sec(FACTS_URL.format(cik=cik), f"CIK{cik:010d}.json", 86400)
        return self._facts[key]

    def _ticker(self, ticker: str):
        import yfinance as yf

        key = ticker.upper()
        if key not in self._yf:
            self._yf[key] = yf.Ticker(key.replace(".", "-"))
        return self._yf[key]

    # ------------------------------------------------------------------
    # DataClient protocol
    # ------------------------------------------------------------------
    def get_prices(self, ticker, start_date, end_date, interval="day", interval_multiplier=1, **kwargs):
        from hedge_fund.data.models import Price

        if interval != "day" or interval_multiplier != 1:
            raise NotImplementedError("the free data adapter serves daily bars only")
        end = (_day(end_date) + timedelta(days=1)).isoformat()  # Yahoo's end is exclusive
        frame = self._ticker(ticker).history(start=start_date, end=end, auto_adjust=False, raise_errors=True)
        bars = []
        for when, row in frame.iterrows():
            day = when.date().isoformat()
            if not (start_date <= day <= end_date) or row["Close"] != row["Close"]:  # NaN close: no bar
                continue
            bars.append(Price(open=round(float(row["Open"]), 4), close=round(float(row["Close"]), 4),
                              high=round(float(row["High"]), 4), low=round(float(row["Low"]), 4),
                              volume=int(row["Volume"] or 0), time=day))
        return bars

    def get_financial_metrics(self, ticker, end_date, period="ttm", limit=10):
        from hedge_fund.data.models import FinancialMetrics

        if period != "ttm":
            raise NotImplementedError("the free data adapter serves trailing twelve month rows only")
        return [FinancialMetrics(**r) for r in self.visible_rows(ticker, end_date, limit)]

    def visible_rows(self, ticker: str, end_date: str, limit: int = 10) -> list[dict]:
        """The rows public by `end_date` (filed on or before it), newest period first."""
        rows = [r for r in self._ttm_rows(ticker) if r["filing_date"] <= end_date[:10]]
        rows.sort(key=lambda r: r["report_period"], reverse=True)
        return rows[:limit]

    def get_company_facts(self, ticker):
        from hedge_fund.data.models import CompanyFacts

        facts = self._company(ticker)
        try:
            info = self._ticker(ticker).get_info() or {}
        except Exception:  # the profile is optional context; statements and prices carry the analysis
            info = {}
        if not facts and not info:
            return None
        cik = facts.get("cik")
        return CompanyFacts(ticker=ticker.upper(), name=facts.get("entityName") or info.get("longName"),
                            cik=f"{int(cik):010d}" if cik else None, sector=info.get("sector"),
                            industry=info.get("industry"), exchange=info.get("exchange"))

    def get_earnings_history(self, ticker, limit=12):
        from hedge_fund.data.models import EarningsData, EarningsRecord

        frame = self._ticker(ticker).get_earnings_dates(limit=max(limit, 12) + 4)
        if frame is None or frame.empty:
            return []
        periods = sorted({f["report_period"] for f in self._filings(ticker)}, reverse=True)
        records = []
        for when, row in frame.iterrows():
            reported, estimate = row.get("Reported EPS"), row.get("EPS Estimate")
            if reported != reported or reported is None:  # announced later, nothing reported yet
                continue
            announced = when.tz_convert("America/New_York").date() if when.tzinfo else when.date()
            # The quarter it reports: the latest period end before the announcement, within a quarter.
            period = next((p for p in periods if 0 < (announced - _day(p)).days <= 100), None)
            if period is None:
                continue
            surprise = None
            if estimate == estimate and estimate is not None:
                surprise = "BEAT" if reported > estimate else "MISS" if reported < estimate else "MEET"
            records.append(EarningsRecord(
                ticker=ticker.upper(), report_period=period, source_type="8-K", filing_date=announced.isoformat(),
                quarterly=EarningsData(earnings_per_share=float(reported),
                                       estimated_earnings_per_share=None if estimate != estimate else float(estimate),
                                       eps_surprise=surprise)))
        records.sort(key=lambda r: r.filing_date, reverse=True)
        return records[:limit]

    def get_earnings(self, ticker):
        raise NotImplementedError("the free data adapter serves the earnings history, not the latest earnings card")

    def get_news(self, ticker, end_date, start_date=None, limit=1000):
        raise NotImplementedError("the free data adapter serves no news (no AI Hedge Fund 2.5.0 analyst reads it)")

    def get_insider_trades(self, ticker, end_date, start_date=None, limit=1000):
        raise NotImplementedError("the free data adapter serves no insider trades (no AI Hedge Fund 2.5.0 analyst reads them)")

    def get_market_cap(self, ticker, end_date):
        rows = self.get_financial_metrics(ticker, end_date, limit=1)
        return rows[0].market_cap if rows else None

    # ------------------------------------------------------------------
    # Statements as filed
    # ------------------------------------------------------------------
    def _filings(self, ticker: str) -> list[dict]:
        """Every original 10-Q and 10-K: the period it reports and the day it was filed."""
        gaap = self._company(ticker).get("facts", {}).get("us-gaap", {})
        seen: dict[str, dict] = {}
        for tag in NET_INCOME + REVENUE + EQUITY:
            for unit in gaap.get(tag, {}).get("units", {}).values():
                for f in unit:
                    if f.get("form") not in QUARTERLY_FORMS or not f.get("accn"):
                        continue
                    filing = seen.setdefault(f["accn"], {"accn": f["accn"], "form": f["form"], "filed": f["filed"],
                                                         "report_period": f["end"]})
                    filing["report_period"] = max(filing["report_period"], f["end"])
        # One row per period: the first filing that reported it (an amendment later is not the moment it became public).
        first: dict[str, dict] = {}
        for filing in sorted(seen.values(), key=lambda x: x["filed"]):
            first.setdefault(filing["report_period"], filing)
        return sorted(first.values(), key=lambda x: x["report_period"])

    def _known(self, tag: str, filed_by: str, unit: str = "USD", taxonomy: str = "us-gaap",
               facts: dict | None = None) -> list[dict]:
        """One tag's facts filed by a date, keeping the latest filing of each period."""
        node = (facts or {}).get("facts", {}).get(taxonomy, {})
        latest: dict[tuple, dict] = {}
        for f in node.get(tag, {}).get("units", {}).get(unit, []):
            if f.get("filed", "9999") <= filed_by:
                key = (f.get("start"), f["end"])
                if key not in latest or f["filed"] > latest[key]["filed"]:
                    latest[key] = f
        return list(latest.values())

    def _flow_ttm(self, facts: dict, tags: tuple[str, ...], end: str, filed_by: str, largest: bool = False) -> float | None:
        """Twelve months to `end` as known on `filed_by`, from the first tag that reports the period.

        Filers change tags over the years (NVIDIA moved its revenue between tags), so the tag is chosen per
        period. With `largest`, the biggest figure wins: a bank's contract revenue is a slice of its total.
        """
        values = [v for v in (self._tag_ttm(facts, tag, end, filed_by) for tag in tags) if v is not None]
        if not values:
            return None
        return max(values) if largest else values[0]

    def _tag_ttm(self, facts: dict, tag: str, end: str, filed_by: str) -> float | None:
        """The fiscal year itself, else the last fiscal year plus this year to date minus last year to date."""
        rows = [f for f in self._known(tag, filed_by, facts=facts) if f.get("start")]
        at_end = [f for f in rows if f["end"] == end]
        year = [f for f in at_end if 350 <= _span(f) <= 380]
        if year:
            return float(year[0]["val"])
        if not at_end:
            return None
        ytd = max(at_end, key=_span)
        length = _span(ytd)
        if length > 350:
            return None
        end_day, start_day = _day(end), _day(ytd["start"])
        prior = [f for f in rows if abs((_day(f["end"]) - (end_day - timedelta(days=364))).days) <= 10
                 and abs(_span(f) - length) <= 15]
        fiscal = [f for f in rows if 350 <= _span(f) <= 380
                  and abs((_day(f["end"]) - (start_day - timedelta(days=1))).days) <= 10]
        if not prior or not fiscal:
            return None
        return float(fiscal[0]["val"]) + float(ytd["val"]) - float(prior[0]["val"])

    def _instant(self, facts: dict, tags: tuple[str, ...], end: str, filed_by: str, unit: str = "USD",
                 taxonomy: str = "us-gaap") -> float | None:
        """A balance at `end` as known on `filed_by`, from the first tag that reports it."""
        for tag in tags:
            rows = [f for f in self._known(tag, filed_by, unit, taxonomy, facts) if not f.get("start") and f["end"] == end]
            if rows:
                return float(rows[0]["val"])
        return None

    def _debt(self, facts: dict, end: str, filed_by: str) -> float | None:
        """Borrowings counted once: long-term debt (current and noncurrent), commercial paper, short-term borrowings.

        Financial Datasets' debt to equity came out higher on the rows checked (AAPL, NVDA): its debt matches
        total long-term debt plus the current portion again, so the current portion counts twice there.
        """
        parts = [self._instant(facts, (tag,), end, filed_by) for tag in DEBT_PARTS]
        if any(p is not None for p in parts):
            return sum(p for p in parts if p is not None)
        return self._instant(facts, DEBT_TOTAL, end, filed_by)

    def _shares(self, facts: dict, filing: dict) -> float | None:
        """The count on the filing's cover page, else the balance sheet count at the period end."""
        cover = [f for f in facts.get("facts", {}).get("dei", {}).get(SHARES_COVER[0], {}).get("units", {}).get("shares", [])
                 if f.get("accn") == filing["accn"]]
        if cover:
            return float(sum(f["val"] for f in cover if f["end"] == max(c["end"] for c in cover)))
        return self._instant(facts, SHARES_BALANCE, filing["report_period"], filing["filed"], unit="shares")

    def _closes(self, ticker: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
        """Every daily close (split adjusted, as Yahoo serves it) and every split, fetched once per ticker."""
        key = ticker.upper()
        if key not in self._history:
            handle = self._ticker(ticker)
            frame = handle.history(period="max", auto_adjust=False)
            closes = [] if frame is None or frame.empty else [
                (when.date().isoformat(), float(c)) for when, c in frame["Close"].items() if c == c]
            splits = [(when.date().isoformat(), float(r)) for when, r in handle.splits.items() if r]
            self._history[key] = (closes, splits)
        return self._history[key]

    def _close_on(self, ticker: str, day: str) -> float | None:
        """Close on the day or the last session within ten days before it, on that day's share basis.

        Yahoo restates past closes for later splits while a filed share count keeps the basis of its own
        date, so the splits after the session are undone on the close.
        """
        closes, splits = self._closes(ticker)
        floor = (_day(day) - timedelta(days=10)).isoformat()
        past = [c for c in closes if floor <= c[0] <= day[:10]]
        if not past:
            return None
        traded, close = past[-1]
        for when, ratio in splits:
            if when > traded:
                close *= ratio
        return close

    def _ttm_rows(self, ticker: str) -> list[dict]:
        facts = self._company(ticker)
        if not facts:
            return []
        rows: list[dict] = []
        for filing in self._filings(ticker):
            end, filed = filing["report_period"], filing["filed"]
            revenue = self._flow_ttm(facts, REVENUE, end, filed, largest=True)
            net_income = self._flow_ttm(facts, NET_INCOME, end, filed)
            if revenue is None and net_income is None:
                continue
            gross = self._flow_ttm(facts, GROSS_PROFIT, end, filed)
            if gross is None and revenue is not None:
                cost = self._flow_ttm(facts, COST_OF_REVENUE, end, filed)
                gross = revenue - cost if cost is not None else None
            operating = self._flow_ttm(facts, OPERATING_INCOME, end, filed)
            cash_ops = self._flow_ttm(facts, OPERATING_CASH, end, filed)
            capex = self._flow_ttm(facts, CAPEX, end, filed)
            equity = self._instant(facts, EQUITY, end, filed)
            assets_now = self._instant(facts, CURRENT_ASSETS, end, filed)
            liabilities_now = self._instant(facts, CURRENT_LIABILITIES, end, filed)
            debt = self._debt(facts, end, filed)
            shares = self._shares(facts, filing)
            # Priced on the day the filing became public: the row is a market view from that day on.
            close = self._close_on(ticker, filed)
            market_cap = close * shares if close and shares else None
            free_cash = cash_ops - capex if cash_ops is not None and capex is not None else None

            def ratio(a, b, positive=False):
                if a is None or not b or (positive and b <= 0):
                    return None
                return a / b

            rows.append({
                "ticker": ticker.upper(), "report_period": end, "period": "ttm", "currency": "USD", "filing_date": filed,
                "market_cap": market_cap, "price_to_earnings_ratio": ratio(market_cap, net_income, positive=True),
                "price_to_book_ratio": ratio(market_cap, equity, positive=True),
                "price_to_sales_ratio": ratio(market_cap, revenue, positive=True),
                "gross_margin": ratio(gross, revenue, positive=True), "operating_margin": ratio(operating, revenue, positive=True),
                "net_margin": ratio(net_income, revenue, positive=True), "return_on_equity": ratio(net_income, equity, positive=True),
                "current_ratio": ratio(assets_now, liabilities_now, positive=True),
                "debt_to_equity": ratio(debt, equity, positive=True),
                "earnings_per_share": ratio(net_income, shares, positive=True),
                "book_value_per_share": ratio(equity, shares, positive=True),
                "free_cash_flow_per_share": ratio(free_cash, shares, positive=True),
                "free_cash_flow_yield": ratio(free_cash, market_cap, positive=True),
                "_revenue": revenue,
            })
        # Growth against the row a year earlier, which was public before this one.
        by_end = {r["report_period"]: r for r in rows}
        for r in rows:
            target = _day(r["report_period"]) - timedelta(days=364)
            prior = next((p for e, p in by_end.items() if abs((_day(e) - target).days) <= 15), None)
            prev, now = (prior or {}).get("_revenue"), r["_revenue"]
            r["revenue_growth"] = now / prev - 1 if now is not None and prev and prev > 0 else None
        for r in rows:
            r.pop("_revenue", None)
        return rows
