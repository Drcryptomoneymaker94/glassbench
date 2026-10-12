<p align="center">
  <a href="https://davidariasfinance.com/glassbench/"><img src="assets/banner.png" alt="Glassbench: watch AI trading agents think. Tested with TradingAgents v0.6.0 by Tauric Research and AI Hedge Fund v2.5.0 by virattt. Live committee, runs database, LLM benchmark, backtests, paper trading." width="100%"></a>
</p>

<p align="center">
  <a href="https://davidariasfinance.com/glassbench/"><img src="https://img.shields.io/badge/Website-davidariasfinance.com%2Fglassbench-0b2545" alt="Website"></a>
  <a href="https://youtu.be/Bvucb9BpJ1U"><img src="https://img.shields.io/badge/Watch_the_video-13_min-FF0000?logo=youtube&logoColor=white" alt="Watch the video"></a>
  <a href="https://github.com/TauricResearch/TradingAgents"><img src="https://img.shields.io/badge/Engine-TradingAgents_0.6.0-1a1d1b?logo=github" alt="TradingAgents 0.6.0"></a>
  <a href="https://github.com/virattt/ai-hedge-fund"><img src="https://img.shields.io/badge/Engine-AI_Hedge_Fund_2.5.0-1a1d1b?logo=github" alt="AI Hedge Fund 2.5.0"></a>
  <a href="https://arxiv.org/abs/2412.20138"><img src="https://img.shields.io/badge/Paper-arXiv_2412.20138-b31b1b?logo=arxiv&logoColor=white" alt="Paper"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache_2.0-2e4bc9" alt="Apache 2.0"></a>
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/React-19-20232a?logo=react&logoColor=61DAFB" alt="React 19">
</p>

## What it is

Glassbench is a UI and local workbench for LLM trading frameworks. Today it runs the official [TradingAgents](https://github.com/TauricResearch/TradingAgents) engine (v0.6.0, unmodified) and [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund) (v2.5.0, unmodified), and records what their agents read, argued and decided, so you can judge the method yourself instead of trusting a rating.

For people curious about AI trading agents but unconvinced: every run is recorded, every flag is shown, every cost is counted.

- **Live run and replay.** Twelve agents in five stages (analysts, research debate, trader, risk committee, portfolio manager), one card per agent with what it is doing right now and what it concluded, the DeepSeek reasoning stream if you want it, and a timeline of every LLM and tool call. An AI Hedge Fund run gets the same page: one lane per investor agent and the earnings drift model, then the blend, the risk limits and the simulated fill.
- **A database of every run.** Framework and version, models, ticker, date, rating, entry, stop, target, horizon, tokens, cost, flags. Filter by any of them, full-text search inside the logs, export to CSV. This repository ships the author's database as a courtesy: [77 runs](#the-runs-database) on 9 tickers, 69 from TradingAgents and 8 from AI Hedge Fund.
- **Frameworks page.** A reference sheet per framework: how it decides, what it reads, what the evidence says, with an SVG of the mechanism.
- **Backtests with an honest simulator.** Weekly grids, next-open fills, trading costs, buy-and-hold and moving-average baselines, a shuffled-rating placebo, and side-by-side variants of the same decisions.
- **A trade at the broker.** `trade.py` turns a finished run into one bracket order on an Interactive Brokers paper account, with the trader's stop and the portfolio manager's target attached, and links the order back to the run that produced it.

Nothing here is a ready system to trade with. See [Honest limits](#honest-limits).

<p align="center">
  <img src="docs/img/glassbench-tour.gif" alt="A 30 second tour: runs from both frameworks, the New run dialog, a stored NVIDIA run replayed at about 75 times its real speed with the committee filling and the timeline growing, one agent's reasoning and the decision, the framework sheets with their diagrams, and the database with a filter and a log search" width="900">
  <br><sub>Tour of the app. Shown here: a stored TradingAgents run replayed about 75 times faster than it ran; a real run takes four to nine minutes.</sub>
</p>

> **Not investment advice.** Glassbench is a research and education tool. Every rating, price level and report in this repository and its database is output from language models, published so the method can be judged. None of it is a recommendation to buy, sell or hold any security, by the author or anyone else. Orders go to paper accounts only.

---

## Highlights

**The committee, live.** One card per agent, grouped by stage, with what it is reading, what it is writing and its one-line conclusion. Click a card for the full output: every LLM call, every tool call with its result, the reasoning stream. A stage strip shows where the run is, and a timeline shows who ran when and for how long. Every run can be replayed step by step afterwards.

**A database of every run, not a log folder.** Runs from both frameworks share one table, with a switch on the Runs page to show all of them or one framework. Each run lands in SQLite with its framework and version, provider and models, ticker, date, analysts, debate depth, rating, entry, stop, target, horizon, tokens, tool calls, cost and flags. The Runs page filters on all of it; the Database page facets it (framework version, variant, quick and deep model, the model actually served, ticker, rating, horizon, purpose) and searches the full text of every report and every reasoning trace. Export any view to CSV. An AI Hedge Fund run also keeps each analyst's signal, confidence and reasoning, the blended conviction, the weight after risk limits and the simulated fill.

**Benchmark LLMs on the same harness.** The framework is fixed; the models are yours to choose. Pick the provider and type any model id for the quick role (reads and debates) and the deep role (the two managers decide). DeepSeek is the default; OpenAI, Anthropic, Google, xAI, Qwen, GLM, MiniMax, Mistral, Kimi, Groq, OpenRouter and a local Ollama are one key away. Every run records which model was asked for and which was actually served, so two models on the same stock and date sit side by side in the same table with their cost.

**Choose the agents.** One to four analysts, one to five debate rounds, and named variants that change how the agents are fed (prompt wording, SEC EDGAR statements as filed, point-in-time valuation) without touching the engine. Matched pairs of variants on the same cells are compared by reading what the agents wrote, not just by their ratings ([the valuation matched pair](docs/evaluation-valuation-pair.md)).

**Backtest honestly.** Weekly grids of runs with a budget cap, replayed against buy-and-hold, a moving-average rule and a shuffled-rating placebo, with next-open fills and trading costs ([the method](docs/backtest-method.md)).

**Then trade it, on paper.** `trade.py` sends the decision to an Interactive Brokers paper account as one bracket order, and the order stays linked to the run that produced it.

## Screenshots

| Runs, the record of every analysis | A run, with the committee board |
|---|---|
| ![Runs page](docs/img/runs.png) | ![Run page with the committee board](docs/img/run-committee.png) |

| Database, faceted over every run | Frameworks, the reference sheet |
|---|---|
| ![Database page](docs/img/database.png) | ![Frameworks page](docs/img/frameworks.png) |

| New run: any provider, any model id, your choice of agents | An agent opened: its calls, tools and output |
|---|---|
| ![New run dialog](docs/img/new-run.png) | ![Agent detail](docs/img/agent-detail.png) |

| A paper trade: the committee's decision becomes a bracket order at Interactive Brokers, target and stop attached |
|---|
| ![Terminal and Interactive Brokers TWS during a paper trade](docs/img/trade-ibkr.gif) |

## Frameworks

| Framework | Status | Notes |
|---|---|---|
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) 0.6.0 | Connected | Engine runs untouched. Glassbench observes it through LangChain callbacks and reads its state; every node name and state key it depends on lives in one file, `backend/deskapp/adapter.py`, with tests. Optional variants (prompt wording, SEC EDGAR point-in-time valuation) are applied at runtime and never change the clone. Release 0.5.1 includes a fix and a bug report that came out of Glassbench runs ([#1370](https://github.com/TauricResearch/TradingAgents/pull/1370), [#1369](https://github.com/TauricResearch/TradingAgents/issues/1369)). Release 0.5.1 also rewrote its own Hold guidance ("conflicting arguments alone are not a reason to Hold"), the idea the prompt wording variant tested, so that variant applies to 0.4.0 and 0.5.0 only; on later releases Glassbench reports it as unavailable instead of editing text that is no longer there. Release 0.6.0 runs each analyst as a graph of its own, with its own message history, and reads statements from SEC EDGAR by default; Glassbench streams those inner graphs, so every analyst's tokens, tool calls and report still land on its own card. |
| [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund) 2.5.0 | Connected | Runs untouched in its own clone and virtual environment, because it pins other LangChain versions; `backend/drivers/aihf_driver.py` drives one cycle and streams it as events. Release 2.5.0 splits a cycle into two steps, assess at a close and execute at the next completed close, and Glassbench sequences them for one stock and date. Data comes from Financial Datasets, the framework's own client, or from [a free route Glassbench adds](#free-data-for-ai-hedge-fund), which is not native and is labelled on every run that uses it. Each investor agent and the earnings drift model is a lane, followed by the blend, the risk limits and the simulated execution. Every run keeps its own prompt cache, so a rerun asks the model again. AI Hedge Fund returns portfolio weights, and Glassbench maps the blended conviction to five tiers (0.50 or more Buy, 0.15 Overweight, above -0.15 Hold, above -0.50 Underweight, else Sell) so both frameworks share one table, and a run where most analysts abstained is REVIEW. |

Every table's Framework column shows the framework and version only (`TradingAgents 0.6.0`, `AI Hedge Fund 2.5.0`). A build that contains changes on top of the release is labelled `adjusted`, with the changes listed in the tooltip.

## Quick start

You need Python 3.11 or newer, Node 22 or newer, Git, and an API key for one LLM provider. DeepSeek is the default and costs about $0.06 per full run; eleven other providers and local Ollama are listed in `.env.example`.

**1. Clone Glassbench and the engine.**

```powershell
git clone https://github.com/davidalmeida90/glassbench.git
cd glassbench
git clone --branch v0.6.0 --depth 1 https://github.com/TauricResearch/TradingAgents.git
```

The engine is expected at `./TradingAgents` (or a sibling `../TradingAgents`, or wherever `GLASSBENCH_ENGINE_DIR` points).

**2. Python environment.**

```powershell
py -3.11 -m venv .venv            # Mac or Linux: python3 -m venv .venv
.\.venv\Scripts\Activate.ps1      #                source .venv/bin/activate
pip install -r requirements.txt
pip install -e .\TradingAgents
```

**3. Keys.** Copy `.env.example` to `.env` and paste your key after the equals sign (`DEEPSEEK_API_KEY`, or the variable of the provider you will pick). Only the names listed there are read, and values never reach the browser.

**4. Optional: AI Hedge Fund.**

```powershell
git clone https://github.com/virattt/ai-hedge-fund.git
cd ai-hedge-fund
py -3.11 -m venv .venv            # its own environment: it pins other LangChain versions
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m pip install yfinance==1.7.0   # only for the free data route
cd ..
```

It is found at `./ai-hedge-fund`, a sibling `../ai-hedge-fund`, or wherever `GLASSBENCH_AIHF_DIR` points. Its own prices and fundamentals come from [Financial Datasets](https://www.financialdatasets.ai): add `FINANCIAL_DATASETS_API_KEY` to `.env`. Its key is free and its data prepaid, about $0.02 a request, and a run takes four to six. Its entry plan returns the last twelve months only, and each investor agent needs four filed quarters, so on that plan pick a recent date. Without that key, pick **Yahoo Finance (free)** under Data, described below. Then choose AI Hedge Fund in **New run**: a library strategy or your own analysts, one model for all of them, and the data.

### Free data for AI Hedge Fund

<p align="center">
  <img src="docs/img/aihf-free-data.png" alt="The New run dialog with AI Hedge Fund selected and the Data choice set to Yahoo Finance (free), showing the note that the route is not native to AI Hedge Fund" width="720">
</p>

In **New run**, the **Data** choice has a second option, **Yahoo Finance (free)**. It is not native to AI Hedge Fund: it is Glassbench's own adapter, `backend/drivers/free_data.py`, written against the framework's data protocol, so every analyst runs unchanged and nothing in the clone is edited. Results might not be ideal, and every run on this route says so on its run page, in its decision card and in the runs table.

- Prices and earnings surprises come from Yahoo Finance, statements from SEC EDGAR. Each 10-Q and 10-K becomes one trailing twelve month row, dated by the day it was filed, so a row is visible only from the day it became public.
- It costs nothing and needs no key. `SEC_EDGAR_EMAIL`, when set, goes to the SEC, which asks callers to identify themselves.
- It reaches back through every filing, where the Financial Datasets entry plan returns twelve months, so investor agents that abstained for lack of four filed quarters have them.
- Checked against Financial Datasets on six rows (NVIDIA, Apple and JPMorgan, two quarters each): margins, return on equity, earnings and book value per share, free cash flow per share, revenue growth and the current ratio agree to the third or fourth decimal where both report them. Two figures differ on purpose. Market cap is priced at the close of the filing day, within about 6% of Financial Datasets' figure. Debt counts the current portion of long-term debt once, where Financial Datasets' debt to equity came out higher.
- Not served: news and insider trades (no 2.5.0 analyst reads them). Sector and industry are Yahoo's current profile, the same approximation the framework makes with Financial Datasets. Yahoo's earnings figures are the adjusted ones analysts estimate.

**5. Start.**

```powershell
.\glassbench.ps1                  # Mac or Linux: ./glassbench.sh
```

The first start builds the frontend, then the app is at http://127.0.0.1:8765. Press **New run**, pick a ticker, a date, the analysts, the provider and the two models, and watch the committee work. A full four-analyst run takes about eight minutes and costs about six cents on DeepSeek.

**Headless, without the browser:**

```powershell
cd backend
python -m deskapp run NVDA --analysts market,news,fundamentals
```

## The runs database

`data/desk.db` is SQLite, and this repository ships the author's own database as a courtesy: 100 runs on 14 tickers (NVDA, AAPL, MSFT, INTC, PFE, JPM, KO, MCD, O, T, TSLA, XOM, AMZN, GOOGL), September and October 2026.

- **TradingAgents, 88 runs** on 0.4.0, 0.5.0, 0.5.1 and 0.6.0, with DeepSeek V4 Flash as the quick model and V4 Pro as the deep model. They include the two Microsoft runs from the video that disagree on the same day, the NVIDIA run that became a paper order, a weekly backtest pilot, matched pairs of variants, and a batch of twin runs on eight stocks (25 September 2026) in which seven runs failed when the DeepSeek balance ran out; they stay in the database as failed. Each run's reports, tool outputs and final state are under `data/runs/<run_id>/`.
- **AI Hedge Fund, 12 runs** with DeepSeek V4.1 Flash. Nine on 2.4.0: four complete cycles on four companies and four strategies (NVIDIA, Apple, JPMorgan and Tesla, late August to mid September 2026), one more on NVIDIA in October, and four that show the limits of the entry data plan: two dates older than its twelve months fail, and on two others the investor agents had fewer than four filed quarters and abstained. Three on 2.5.0, all NVIDIA on 8 October 2026 with Deep Value: one on Financial Datasets (Hold) and two on the free route (Overweight both times), labelled as free data. One draw per route at most, so the ratings show that the routes can disagree, not why.

AI Hedge Fund runs publish derived outputs only: each analyst's signal and reasoning, the blend, the weights and the simulated fill (`record.json`). Financial Datasets responses and the prompts that quote them stay out of the repository, because its licence allows sharing only what is derived from the data; the event log records each data call as a row count and a date span. Runs on the free route are published the same way.

```sql
-- ratings by ticker
SELECT ticker, rating, COUNT(*) FROM runs WHERE status = 'finished' GROUP BY 1, 2 ORDER BY 1;

-- what the portfolio manager wrote, full text search
SELECT run_id, agent, snippet(event_text, 4, '[', ']', '...', 12) FROM event_text WHERE event_text MATCH 'valuation' LIMIT 20;
```

The Runs and Database pages export any filtered view to CSV. Every finished run stays in the database, by design: the disagreements are the point.

| Where | What |
|---|---|
| `data/desk.db` | the runs table, every event, and a full-text index of the logs |
| `data/runs/<run_id>/reports/` | analyst reports, both debates, trader proposal, risk debate, final decision |
| `data/runs/<run_id>/tool_outputs/` | the full output of every tool call the agents made |
| `data/runs/<run_id>/state.json` | the final state of the graph |
| `data/runs/<run_id>/record.json` | an AI Hedge Fund cycle: every signal, the blend, the risk limits, the simulated orders and fills |
| `data/aihf_private/<run_id>/` | AI Hedge Fund's raw data responses and prompts, local only and ignored by Git |
| `data/orders.jsonl` | paper orders sent by `trade.py`, each linked to its run |
| `state/trading_memory.md` | the engine's decision memory (created on first run) |

## Data and keys

| Source | Used for | Key |
|---|---|---|
| DeepSeek (default), OpenAI, Anthropic, Google, xAI, Qwen, GLM, MiniMax, Mistral, Kimi, Groq, OpenRouter, or a local Ollama | the agents, chosen per run | that provider's key in `.env` (`DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, ...); Ollama needs none |
| Yahoo Finance | prices, indicators, news; prices and earnings surprises on AI Hedge Fund's free route | none |
| SEC EDGAR | statements as filed (TradingAgents' default since 0.6.0), the point-in-time valuation variant, and AI Hedge Fund's free route | `SEC_EDGAR_EMAIL` (the SEC asks callers to identify themselves) |
| FRED | macro series | `FRED_API_KEY`, free |
| StockTwits, Reddit | the sentiment analyst | none |
| Financial Datasets | AI Hedge Fund's own prices, fundamentals and earnings | `FINANCIAL_DATASETS_API_KEY`, prepaid credits; not needed on the free route |
| TypeSafe | Jev as AI Hedge Fund's model, and TradingAgents' screening of social posts (since 0.5.1) | `TYPESAFE_API_KEY`, optional |
| Interactive Brokers, Alpaca | paper orders and connection checks | TWS or IB Gateway logged into a paper account; `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` for Alpaca paper |

Everything the engine downloads goes into `state/cache/`. Keys are read once, from `.env`, by the backend process; the browser gets their names and lengths, never their values.

## A trade at the broker

```powershell
py -3 trade.py NVDA MSFT              # run the twelve agents on each stock, then trade
py -3 trade.py NVDA MSFT --reuse      # replay each stock's latest finished run, then trade
py -3 trade.py NVDA --dry-run         # everything except sending the orders
```

Long only, one decision, fixed size: Buy or Overweight becomes one marketable limit order for $10,000 worth with the trader's stop and the portfolio manager's target attached as a bracket; Hold does nothing; Underweight or Sell closes what is held. Paper ports and paper accounts only, one working order per stock, size capped, and a y/N confirmation before anything is sent. It needs Glassbench running and Trader Workstation or IB Gateway logged into a paper account.

## What a run records

Twelve agents: four data analysts (market, sentiment, news, fundamentals) with tools, a bull and a bear researcher, a research manager, a trader, three risk debaters and a portfolio manager. Cheap fast models do the reading and the debating; the expensive model is called only by the two managers. Every tool returns data dated on or before the run date, which is what makes a backtest possible.

An AI Hedge Fund run records each analyst's lane (the data it fetched, as counts and dates, and its one LLM call), the blend, the risk limits and the simulated fill at the next close.

The full mechanism, agent by agent, with the tool calls from a real run: [docs/how-a-run-works.md](docs/how-a-run-works.md). The backtest method and the pilot: [docs/backtest-method.md](docs/backtest-method.md). What serving point-in-time valuation changes in what the agents write, measured on 24 runs: [docs/evaluation-valuation-pair.md](docs/evaluation-valuation-pair.md). Notes on how to evaluate these systems, and which published results hold up: [docs/backtest-research.md](docs/backtest-research.md).

## Honest limits

- The TradingAgents paper reports one backtest on three stocks over three months (January to March 2024). An independent test over longer windows landed below buy-and-hold. A Sharpe of 8 over one quarter says the idea deserves a test, not that it works.
- Two runs on the same ticker and date can differ. The database holds twin runs two minutes apart with opposite ratings. Measure how often that happens before trusting any single rating.
- The backtest pilot in this repository (AAPL and NVDA, weekly, 2025 to 2026) had the agents' trader levels lose money while buy-and-hold gained, and the ratings alone never traded. Trading costs, next-open fills and a shuffled-rating placebo are in the simulator so the comparison stays fair.
- AI Hedge Fund's valuation fields come from the latest filed period, so its investor agents can see a price from months before the run date, and they abstain when fewer than four quarters are on file.
- Glassbench's free data route rebuilds AI Hedge Fund's inputs from SEC filings and Yahoo. It is not the framework's own data, the two can differ, and a run on one route says nothing about a run on the other until the same cells have been run on both.
- The order in the video was sent to a paper account. No real money moved. Nothing in this repository is investment advice.

## Layout

```
glassbench/
├── glassbench.ps1, glassbench.sh   launchers (build the frontend once, then serve)
├── trade.py                        one bracket order per stock at an IB paper account
├── backend/deskapp/
│   ├── adapter.py      every TradingAgents node name, state key and parser (the one file to fix after an engine update)
│   ├── capture.py      LangChain callbacks and engine warnings turned into events
│   ├── runner.py       runs the graph with streaming, memory and reports; hands AI Hedge Fund runs to aihf.py
│   ├── aihf.py         AI Hedge Fund: what the clone offers, the subprocess runner, costs, the rating mapping
│   ├── runconfig.py    one engine config per run (the engine keeps a process-wide one)
│   ├── variants.py     runtime variants: prompt wording, SEC EDGAR statements and valuation
│   ├── edgar.py        point-in-time fundamentals from SEC EDGAR
│   ├── backtest.py     weekly grids of runs with a budget cap
│   ├── simulate.py     the simulator: fills, costs, baselines, placebo
│   ├── paired.py       matched-pair reading of what agents wrote
│   ├── brokers.py      Alpaca and Interactive Brokers paper connection checks
│   ├── frameworks.py   the reference sheets on the Frameworks page
│   ├── store.py        SQLite, events, full-text index
│   ├── api.py          REST and Server-Sent Events (replay, then live)
│   └── settings.py     paths, models, price table, engine config
├── backend/drivers/    aihf_driver.py: one AI Hedge Fund cycle inside its own environment, printed as events
├── backend/tests/      adapter, backtest, simulator, variants, run config, AI Hedge Fund
├── frontend/src/       React and TypeScript (Vite)
├── data/               the runs database and the run files
└── docs/               how a run works, backtest method, the valuation matched pair, research notes, screenshots
```

After updating the engine, run the adapter tests; a failing test names what changed upstream, and `adapter.py` is where to fix it:

```powershell
cd backend
python -m unittest discover tests
```

## Development

```powershell
cd frontend && npm run dev        # Vite on http://127.0.0.1:5173, /api proxied to the backend on 8765
cd backend && python -m unittest discover tests
```

Engine internals live in one place, `backend/deskapp/adapter.py`; `capture.py` turns LangChain callbacks into numbered events; `store.py` keeps them in SQLite with a full-text index; `api.py` replays them over Server-Sent Events and then switches to live. Anything that changes how the agents think is a named variant in `variants.py`, applied per run through `runconfig.py`, so the engine clone is never edited.

## Roadmap

- **Both data routes on the same cells.** AI Hedge Fund's free route now runs ([see above](#free-data-for-ai-hedge-fund)); next is running the same stocks and dates on both routes, several times each, to measure how much of a rating moves with the data rather than with the model's draw.
- **Transparency pack.** A grounding check of each report against the data it pulled, rerun dispersion (how often twin runs disagree), and a compare view.
- **Scheduled sessions.** A watchlist run on a clock, with rules that turn ratings into orders only when several runs agree.
- **More brokers and guardrails.** Alpaca paper orders next to Interactive Brokers, a kill switch, a cost budget.

## Contributing

Issues and pull requests are welcome, in particular more framework adapters, more brokers, and evaluation methods. Keep engines untouched: anything Glassbench needs from a framework goes through its adapter, and anything that changes how agents think is a named variant applied at runtime.

## Credits and license

Glassbench is by [David Arias, CFA](https://davidariasfinance.com), released under the [Apache License 2.0](LICENSE). It runs on top of [TradingAgents](https://github.com/TauricResearch/TradingAgents) by Tauric Research (Apache 2.0), which is not bundled here; see the [paper](https://arxiv.org/abs/2412.20138) by Yijia Xiao, Edward Sun, Di Luo and Wei Wang. It also runs [AI Hedge Fund](https://github.com/virattt/ai-hedge-fund) by Virat Singh (MIT), also not bundled. The video that walks through all of this: [Open Source AI Trading Agents on DeepSeek: Setup to a Broker Order](https://youtu.be/Bvucb9BpJ1U).

## Disclaimer

Glassbench is software for research and education. It is not investment advice, a recommendation, or an offer to buy or sell any security, and it is not a trading system.

- Ratings, price levels, reports and debates in the published runs are output from language models. They are wrong often, two runs on the same stock and date can disagree, and they are published so the method can be examined, never so they can be followed.
- Backtests and paper trades describe the past on a handful of decisions. They say nothing reliable about future returns.
- The software connects to paper broker accounts only. Anyone who adapts it to trade real money does so at their own risk and under their own responsibility.
- Views expressed here are the author's own and do not represent any employer or client. Glassbench is independent of Tauric Research, the TradingAgents project and AI Hedge Fund.
- The software is provided "as is", without warranty of any kind, under the Apache License 2.0.

## Citation

If you use the runs database or the simulator in research, cite the TradingAgents paper and link this repository:

```bibtex
@misc{xiao2025tradingagents,
  title  = {TradingAgents: Multi-Agents LLM Financial Trading Framework},
  author = {Yijia Xiao and Edward Sun and Di Luo and Wei Wang},
  year   = {2025},
  eprint = {2412.20138},
  archivePrefix = {arXiv},
  url    = {https://arxiv.org/abs/2412.20138}
}
```
