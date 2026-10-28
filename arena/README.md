# Harness Arena

Five AI books traded US stocks on Alpaca paper accounts for two sessions, 26 and 27 Oct 2026, $100,000 each, a decision every 30 minutes. Four of them got the same prompt and differ only in harness and model, a 2x2 grid. Book five runs TradingAgents, a method built for trading, on DeepSeek.

| Book | Harness | Model | How it decides |
|---|---|---|---|
| B1 | dsh 0.2 (headless) | deepseek-flash | [prompt.md](prompt.md), every 30 minutes |
| B2 | dsh 0.2 (headless) | claude-haiku-5-5 | same prompt |
| B3 | Claude Code 2.1 (`--bare`) | deepseek-flash | same prompt |
| B4 | Claude Code 2.1 (`--bare`) | claude-haiku-5-5 | same prompt |
| B5 | TradingAgents v0.7.0, as released | deepseek-v4-pro (deep), deepseek-flash (quick) | rates every stock before the open, buys its Buy and Overweight names with the trader's stop, holds |

Same 20 stocks for every book (the 2 largest S&P 500 companies in each of the 10 largest sectors, [universe.json](universe.json)), same rules, same snapshot bytes each round. Benchmark: SPY over the same minutes.

## How a round works

Every round each prompted book starts a fresh harness session with three tools and nothing else: `get_snapshot` (prices, moves and Alpaca headlines, frozen once for all four, plus the note the book left last round), `get_portfolio` and `place_order`. Built-in tools are switched off in both harnesses, the agents work in empty folders, and keys never reach them: the MCP server reads its own book's key.

Rules live in code ([rules_engine.py](rules_engine.py), unit tested), so a prompt cannot bend them: long only, no margin, at most 20% of the book per stock, buys of at least $500, 10 orders per round, nothing after 15:40 New York. Every book is sold at 15:50. Orders go only to the paper endpoint, and a key that does not start with `PK` is refused.

## Results, two days compounded

| Book | Return | vs SPY (pts) | P&L after AI, slippage and fees | Beats random books, day 1 / day 2 |
|---|---|---|---|---|
| B5 TradingAgents (DeepSeek) | +0.53% | +0.14 | +$478 | 93% / 62% |
| B1 dsh + DeepSeek | +0.42% | +0.03 | +$293 | 5% / 99% |
| B3 Claude Code + DeepSeek | +0.29% | -0.09 | +$171 | 1% / 100% |
| B4 Claude Code + Haiku | +0.29% | -0.10 | +$199 | 16% / 90% |
| B2 dsh + Haiku | +0.15% | -0.23 | +$66 | 8% / 85% |
| SPY | +0.38% | | about +$380 | |

- **After costs only TradingAgents stays ahead of SPY.** AI bills were small (about 3 cents per prompted book for both days, TradingAgents about $2 a day of DeepSeek research). Trading costs were bigger: Alpaca posts real SEC and CAT fees on paper sales (about $2 to $3 a day per book), and slippage is estimated at 2 bps a trade since paper fills leave it out.
- **Model mattered more than harness.** Claude Code minus dsh came to -0.01 pts on both days. Haiku minus DeepSeek was +0.24 pts on day 1 and -0.40 pts on day 2.
- **Luck test.** Each book is compared with 10,000 random books that copy its footprint (same number and size of trades per round, random stocks). Prompted books sat at 1% to 16% on day 1 and 85% to 100% on day 2, a falling day and a rally. Their own debriefs name the habit: buying what had just gone up.
- **Self grades.** After each close every prompted agent graded its own day with no tools: D and D+ on day 1, between C- and B on day 2. Their answers are in `results/<day>/debrief/`.

## Honest limits

Two sessions is noise; the luck test shows how much. Paper fills at the quote with no market impact, prices come from the free IEX feed, and day 1 started mid-session (5 rounds against 12 on day 2). TradingAgents' trader plan is richer than one order; the arena takes the rating and the stop only. Each day starts with a blank agent memory.

## Files

| Path | What |
|---|---|
| `results/summary_live-1026_live-1027.md` | the two days combined ([combine.py](combine.py)) |
| `results/live-1026/`, `results/live-1027/` | each day's report (md, json, html), minute equity marks from Alpaca, final prices, TradingAgents' ratings, the self grades |
| [day.py](day.py) | the trading day: rounds on the market clock, minute marks, sell-off, report |
| [run_round.py](run_round.py), [harnesses.py](harnesses.py) | one round: how dsh and Claude Code are launched, what each run records |
| [arena_mcp.py](arena_mcp.py), [snapshot.py](snapshot.py), [broker.py](broker.py) | the three tools, the frozen snapshot, the Alpaca paper client (with a dry broker) |
| [ta_book.py](ta_book.py), [ta_worker.py](ta_worker.py) | B5: TradingAgents ratings and orders |
| [report.py](report.py), [luck.py](luck.py), [debrief.py](debrief.py), [dashboard.py](dashboard.py) | report, luck test, self grades, live dashboard |

Per-round snapshots, agent streams and order logs stay out of the repository: they carry the news feed's headlines and broker identifiers.

## Running it

Built and run on Windows (the `py` launcher, keep-awake through the Windows API). Needs five Alpaca paper accounts, a DeepSeek key, an Anthropic key, a FRED key for TradingAgents, dsh and Claude Code on PATH, and TradingAgents v0.7.0 in its own venv (`ARENA_TA_PYTHON`).

```
pip install httpx mcp pandas zstandard pytest
copy .env.example .env
# fill in the names .env lists, then:
py -3 check_accounts.py                                          # read only: paper keys, status, no shared account
py -3 day.py --run dry-test --mode dry --rounds 3 --interval 2   # short rehearsal, no order reaches Alpaca
py -3 day.py --run live-YYYYMMDD --mode live                     # a full session
py -3 -m pytest tests
```

Paper trading only. Model output, published for research. Not investment advice.
