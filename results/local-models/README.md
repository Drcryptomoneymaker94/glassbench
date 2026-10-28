# TradingAgents on local models

Two open-weight models ran TradingAgents on one desktop machine, with no API and no cost: 12 large US stocks, as of 21 Oct 2026, four analysts (market, social, news, fundamentals), one debate round. Same stocks, date and frozen data as a DeepSeek V4.1 Flash baseline, so the ratings can be compared.

| | Qwen3-30B-A3B-Instruct-2507 | Qwen3.6-35B-A3B |
|---|---|---|
| Quantisation | Q6_K | UD Q5_K_M |
| Runs | 12 of 12 finished | 12 of 12 finished |
| Time per run, median | 468 s | 608 s |
| Generation speed, median | 56.3 tokens/s | 52.8 tokens/s |
| Prompt processing, median | 894 tokens/s | 1,292 tokens/s |
| Cost | $0 | $0 |
| Ratings that match a DeepSeek run | 2 of 12 | 5 of 12 |
| Distance to the closest DeepSeek rating, mean (5 step scale) | 1.33 | 0.75 |
| Buy or Sell ratings | 10 of 12 | 1 of 12 |

DeepSeek V4.1 Flash gave 1 Buy or Sell in its 17 runs on the same stocks.

## Ratings

| Ticker | Qwen3-30B | Qwen3.6-35B | DeepSeek V4.1 Flash (baseline runs) |
|---|---|---|---|
| AAPL | Sell | Hold | Underweight, Underweight |
| AMD | Sell | Overweight | Overweight, Underweight |
| AMZN | Overweight | Overweight | Overweight |
| COIN | Buy | Hold | Underweight |
| GOOGL | Sell | Buy | Underweight |
| JPM | Buy | Underweight | Hold |
| META | Sell | Hold | Underweight |
| MSFT | Underweight | Hold | Hold, Underweight |
| NFLX | Buy | Underweight | Sell |
| NVDA | Buy | Overweight | Underweight, Overweight |
| PLTR | Sell | Hold | Underweight |
| TSLA | Sell | Underweight | Underweight, Underweight |

Every run's reports are in `runs/<model>/<TICKER>.md`: the Portfolio Manager's decision first, then the trader, the research manager and the four analysts, as the engine wrote them. `ratings.csv` has one row per run (time, LLM calls, tool calls, tokens, structured output fallbacks) and `speed.csv` the throughput measured from the server's own timings.

## What to watch for

- **Qwen3-30B rates at the extremes.** Ten of twelve ratings are Buy or Sell, where DeepSeek almost never goes past Overweight or Underweight.
- **Qwen3.6 misses the structured output.** The engine asks the Trader and the Portfolio Manager for a schema; Qwen3.6 returned nothing parseable for the Trader in 11 runs and the Portfolio Manager in 10, and TradingAgents fell back to free text each time. Ratings still came through, from the free text. Qwen3-30B had no fallbacks.
- **Numbers the model got wrong.** The Qwen3-30B NVDA memo puts NVIDIA's cash at "$11.65 trillion", a units error; the rating rests partly on it. Check figures in these reports before quoting them.
- **Some tool calls reached live data.** Both models sometimes called a data tool with arguments the frozen snapshot did not hold, so those calls fetched current data (prediction markets, macro, indicators, prices). A look-ahead check on those runs has not been done yet, so treat the comparison with DeepSeek as provisional.
- **One long call.** In the Qwen3.6 JPM run a single reply ran to about 40,000 tokens and filled the context window; the run still finished, in 22 minutes.
- **Small sample.** One run per stock and model, one date. Rating agreement says nothing about returns.

## How the runs were made

TradingAgents 0.7.0 (commit 57a9d30), models served by [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-server` with the Vulkan backend on an AMD Radeon 8060S (integrated GPU, shared memory), one request at a time: `-c 49152 -np 1 --jinja`, with the model alias set to the model id the engine asks for. Deep and quick model are the same local model. A separate benchmark harness drove the runs; it is not part of this repository, and only its results are published here.

**To do the same in Glassbench**, start `llama-server` and point the Ollama provider at it, since TradingAgents talks to both through the same OpenAI compatible client:

```
llama-server -m <model>.gguf --alias <model-id> -c 49152 -np 1 --jinja --port 8080
```

Then put `OLLAMA_BASE_URL=http://127.0.0.1:8080/v1` in `.env`, choose **Ollama (local)** in the New run dialog and type `<model-id>` as both the deep and the quick model. LM Studio, vLLM and any other server with an OpenAI compatible `/v1` endpoint work the same way.

Model output, published for research. Not investment advice.
