# Harness Arena: 2 days (live-1026, live-1027)

SPY over the same minutes: +0.38%

| Book | Day 1 | Day 2 | Total | vs SPY (pts) | End equity | AI bill | Est. slippage | Equity change between days | Last day's SEC fee, due | P&L after costs | Beats random (by day) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| B5 TradingAgents (DeepSeek) | +0.11% | +0.42% | +0.53% | +0.14 | $100,519.04 | $0.000 | $39.79 | $-8.46 | $1.23 | $+478.02 | 93%, 62% |
| B1 dsh + DeepSeek | -0.52% | +0.94% | +0.42% | +0.03 | $100,414.29 | $0.035 | $117.85 | $-3.08 | $3.00 | $+293.40 | 5%, 99% |
| B3 Claude Code + DeepSeek | -0.63% | +0.93% | +0.29% | -0.09 | $100,285.31 | $0.030 | $111.07 | $-2.72 | $3.02 | $+171.19 | 1%, 100% |
| B4 Claude Code + Haiku | -0.29% | +0.58% | +0.29% | -0.10 | $100,285.42 | $0.027 | $84.48 | $-2.04 | $2.33 | $+198.58 | 16%, 90% |
| B2 dsh + Haiku | -0.38% | +0.53% | +0.15% | -0.23 | $100,147.44 | $0.028 | $79.67 | $-2.06 | $2.06 | $+65.68 | 8%, 85% |

Returns from Alpaca's own equity, first to last minute mark each day, compounded. AI bill: Haiku from Claude Code's own report or tokens at Anthropic's price; DeepSeek estimated from tokens (B5's TradingAgents research is settled from the DeepSeek balance, about $2 a day, and is not in this column). Est. slippage: 2 bps a trade, which paper fills leave out. Equity change between days: Alpaca's SEC and CAT fees on the day's sales, posted the next morning (B5's also holds the price move of its late close on day 1). The last day's SEC fee is not posted yet, so it is estimated at $20.6 per $1M of sales. P&L after costs = end equity minus $100,000, the AI bill, the slippage and the fee still due.
