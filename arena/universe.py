"""The arena's universe: the 2 largest S&P 500 companies in each of the 10 largest GICS sectors.

    py -3 universe.py             writes universe.json (run the evening before the show day, then freeze it)

Size is the company's weight in SPY (float-adjusted market cap). Sector membership comes from the 11 Select Sector
SPDR funds, which hold exactly the S&P 500 members of each GICS sector. Both files are State Street's daily holdings.
Share classes of one company (GOOGL / GOOG) count once, under the larger class.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sys
from pathlib import Path

import httpx
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "universe.json"
URL = "https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/etfs/us/holdings-daily-us-en-{}.xlsx"
SECTOR_FUNDS = {
    "XLK": "Information Technology", "XLF": "Financials", "XLV": "Health Care", "XLY": "Consumer Discretionary",
    "XLC": "Communication Services", "XLI": "Industrials", "XLP": "Consumer Staples", "XLE": "Energy",
    "XLU": "Utilities", "XLRE": "Real Estate", "XLB": "Materials",
}
SECTORS, PER_SECTOR = 10, 2
TICKER = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def holdings(fund: str) -> tuple[pd.DataFrame, str]:
    r = httpx.get(URL.format(fund.lower()), timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    raw = pd.read_excel(io.BytesIO(r.content), header=None)
    as_of = str(raw.iloc[2, 1]).replace("As of ", "")
    df = pd.read_excel(io.BytesIO(r.content), header=4)
    df = df[df["Ticker"].astype(str).str.match(TICKER)]
    return df[["Name", "Ticker", "Weight"]].copy(), as_of


def company(name: str) -> str:
    return re.sub(r"\s+(CL(ASS)?\s+[A-Z]|SHS)\b.*$", "", name.upper()).strip()


def build() -> dict:
    spy, as_of = holdings("SPY")
    sector_of = {}
    for fund, sector in SECTOR_FUNDS.items():
        members, _ = holdings(fund)
        for t in members["Ticker"]:
            sector_of[t] = sector
    spy["Sector"] = spy["Ticker"].map(sector_of)
    missing = spy[spy["Sector"].isna()]
    spy = spy.dropna(subset=["Sector"])
    by_sector = spy.groupby("Sector")["Weight"].sum().sort_values(ascending=False)   # every share class counts here
    spy["Company"] = spy["Name"].map(company)
    spy = spy.sort_values("Weight", ascending=False).drop_duplicates("Company")
    picks = []
    for sector in by_sector.index[:SECTORS]:
        for _, row in spy[spy["Sector"] == sector].head(PER_SECTOR).iterrows():
            picks.append({"ticker": row["Ticker"], "name": row["Name"], "sector": sector, "spy_weight": round(float(row["Weight"]), 4)})
    out = {
        "rule": f"{PER_SECTOR} largest S&P 500 companies (SPY weight) in each of the {SECTORS} largest GICS sectors",
        "holdings_as_of": as_of,
        "sectors": [{"sector": s, "spy_weight": round(float(w), 2)} for s, w in by_sector.items()],
        "unmatched_spy_tickers": sorted(missing["Ticker"].tolist()),
        "universe": picks,
    }
    out["sha256"] = hashlib.sha256(json.dumps(picks, sort_keys=True).encode()).hexdigest()
    return out


def main() -> int:
    u = build()
    OUT.write_text(json.dumps(u, indent=1), encoding="utf-8")
    print(f"holdings as of {u['holdings_as_of']}, {len(u['universe'])} stocks, sha256 {u['sha256'][:12]}")
    for p in u["universe"]:
        print(f"  {p['ticker']:<6} {p['sector']:<24} {p['spy_weight']:>6.2f}%  {p['name']}")
    if u["unmatched_spy_tickers"]:
        print("SPY tickers with no sector fund:", ", ".join(u["unmatched_spy_tickers"]))
    return 0 if len(u["universe"]) == SECTORS * PER_SECTOR else 1


if __name__ == "__main__":
    sys.exit(main())
