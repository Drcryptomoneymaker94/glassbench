"""One TradingAgents v0.7.0 run, as released, on DeepSeek. Runs inside a venv with TradingAgents installed (ARENA_TA_PYTHON).

    <ta-venv python> ta_worker.py <TICKER> <YYYY-MM-DD> <out_dir>

All four analysts, one debate round and one risk round (the release defaults), deep model deepseek-v4-pro, quick
model deepseek-flash. Memory starts empty for every run, so no ticker reads another's lessons. Writes result.json
(rating, the trader's plan, the final decision, every report) and TradingAgents' own logs into out_dir.
"""
import json
import os
import sys
import time
from pathlib import Path

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

ticker, date, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
cfg = dict(DEFAULT_CONFIG)
cfg.update(llm_provider="deepseek", deep_think_llm="deepseek-v4-pro", quick_think_llm="deepseek-flash",
           results_dir=str(out / "logs"), memory_log_path=str(out / "memory.md"),
           data_cache_dir=str(Path(os.environ.get("ARENA_TA_CACHE", out / "cache"))))
t0 = time.time()
state, rating = TradingAgentsGraph(debug=False, config=cfg).propagate(ticker, date)
keep = ["market_report", "sentiment_report", "news_report", "fundamentals_report", "investment_plan",
        "trader_investment_plan", "final_trade_decision"]
res = {"ticker": ticker, "date": date, "rating": str(rating), "seconds": round(time.time() - t0, 1),
       **{k: state.get(k) for k in keep if isinstance(state.get(k), str)}}
(out / "result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print(json.dumps({"ticker": ticker, "rating": str(rating), "seconds": res["seconds"]}))
