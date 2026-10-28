"""Drives one Vibe-Trading analysis for Glassbench. Runs inside Vibe-Trading's own virtual environment.

Glassbench starts this script with that clone's Python and reads JSON lines from stdout:
  driver.started, agent.started, llm.started, llm.delta, llm.finished, llm.failed, tool.called, tool.result,
  tool.failed, report.updated, agent.finished, then driver.finished (the answer) or driver.failed.

Two modes:
  committee  Vibe-Trading's own investment_committee swarm preset: bull and bear researchers in parallel, then the chief
             risk officer, then the portfolio manager, with the preset's own prompts. Glassbench adds one paragraph to
             each prompt (no shell here, compute with quantlib_call) and asks the portfolio manager to close with a
             JSON block.
  single     One research agent (src.agent.loop.AgentLoop) on a fixed Glassbench prompt that ends with the same block.

Both are research only. Every agent gets an allowlist of read-only data tools plus quantlib_call, Vibe-Trading's
shell-free gate to its finance maths: no shell, no file access, no backtests (they run generated code on the host) and
no broker tools. Vibe-Trading's home (memory, sessions, swarm runs, caches) is the run folder, so nothing is shared
between runs and no ~/.vibe-trading/.env is read.

    <vt python> vt_driver.py --ticker NVDA --date 2026-10-28 --model qwen3.6-35b-a3b --provider ollama \\
                             --base-url http://127.0.0.1:8080/v1 --run-dir data/runs/<run_id> --mode committee
    <vt python> vt_driver.py --describe
"""
from __future__ import annotations

import argparse
import contextvars
import itertools
import json
import os
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

AGENT = "vibe"   # the single agent's lane
COMMITTEE = ("bull_advocate", "bear_advocate", "risk_officer", "portfolio_manager")
# Read-only research tools, plus quantlib_call (pure computation over Vibe-Trading's allowlisted maths modules) and
# options_payoff (pure computation). Everything else Vibe-Trading ships (bash, read_file, write_file, backtest,
# factor_analysis, trading_*, etoro_*, swarms, schedulers) stays out of every registry.
TOOL_ALLOWLIST = (
    "get_market_data", "technical_indicators", "get_fundamentals", "get_financial_statements", "get_stock_profile",
    "get_sector_info", "get_institutional_holdings", "get_sec_filings", "get_options_chain", "options_pricing",
    "options_payoff", "quantlib_call", "get_stock_news", "sentiment", "get_macro_series", "prediction_market",
    "web_search", "read_url", "search_symbol", "get_fund_flow", "get_margin_trading", "get_research_reports",
    "load_skill", "compact",
)
# Given to every committee member on top of the preset's own list, so the maths the prompts ask for stays reachable.
COMMITTEE_EXTRA_TOOLS = ("quantlib_call", "technical_indicators")
PREVIEW_CHARS = 700
DECISION_BLOCK = """End your answer with one JSON block in ```json fences``` with exactly these keys:
  "rating": one of "Buy", "Overweight", "Hold", "Underweight", "Sell"
  "action": one of "long", "short", "wait", "hedge"
  "entry", "stop", "target": prices in USD, or null
  "horizon": for example "3 months"
  "confidence": 0 to 100
  "thesis": one sentence"""
PROMPT = """Analyse {ticker}, a US listed stock, as of {date}. Use only information available up to that date.
Research the price action and technical indicators, the fundamentals and latest financial statements, recent news
and sentiment, then take a position for the next 1 to 3 months.

""" + DECISION_BLOCK
NO_SHELL_NOTE = """

## Environment for this run (Glassbench)
There is no bash, no file access and no backtest tool here. Compute risk and valuation numbers with the quantlib_call
tool, which calls public functions of src.quantlib (for example src.quantlib.risk.historical_var) on data you fetched
with the data tools. If a number cannot be computed that way, say it is unavailable instead of estimating it."""
PM_NOTE = """

## Closing block (Glassbench)
""" + DECISION_BLOCK

_LOCK = threading.Lock()
_COUNTER = itertools.count(1)
CURRENT_AGENT: contextvars.ContextVar[str] = contextvars.ContextVar("vt_agent", default=AGENT)


def emit(type_: str, agent: str | None = None, **payload) -> None:
    line = {"type": type_, "agent": agent, **payload}
    with _LOCK:
        sys.stdout.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


def setup_env(args) -> Path:
    """Vibe-Trading reads its whole configuration from the environment: set it before any of its modules load."""
    home = Path(args.run_dir) / "vt_home"
    home.mkdir(parents=True, exist_ok=True)
    for name in list(os.environ):
        if name.startswith(("LANGSMITH_", "LANGCHAIN_TRACING", "LANGCHAIN_API_KEY")):
            os.environ.pop(name)
    os.environ.update(VIBE_TRADING_HOME=str(home), USERPROFILE=str(home), HOME=str(home), PYTHONUTF8="1",
                      LANGCHAIN_MODEL_NAME=args.model)
    # The same cap Glassbench gives TradingAgents (max_tokens 8192). Without one, a local model's runaway answer once ran
    # to 84k tokens and held the server for half an hour.
    os.environ.setdefault("LANGCHAIN_MAX_TOKENS", "8192")
    # Vibe-Trading sizes each agent's context from the model's window and assumes 128k for models it does not know. That
    # stopped a committee's risk officer at about 102k on DeepSeek Flash, whose window is 1M, and would overrun a local
    # server's smaller one, so the real window is set here.
    if args.provider == "ollama":
        # Any local server with an OpenAI compatible /v1 endpoint (llama.cpp, Ollama, LM Studio). The key is a placeholder
        # Vibe-Trading insists on; no real OpenAI key reaches this process.
        os.environ.update(LANGCHAIN_PROVIDER="openai", OPENAI_BASE_URL=args.base_url, OPENAI_API_KEY="sk-local")
        window = local_context_window(args.base_url)
        if window:
            os.environ["VIBE_TRADING_CONTEXT_WINDOW"] = str(window)
        # A local server writes about 50 tokens a second and often serves one request at a time. Run the committee's
        # workers one after the other, and give a request and a worker the time a long answer takes there: with the
        # defaults (120 s per request, four workers at once) a queued request timed out behind a long one.
        os.environ.update(TIMEOUT_SECONDS="1800", SWARM_MAX_WORKERS="1", SWARM_TIMEOUT="10800")
        # Shorter replies than on a hosted model: a local committee's bear wrote 66k tokens in 11 replies and filled a
        # 128k window before the risk officer was reached.
        os.environ["LANGCHAIN_MAX_TOKENS"] = "4096"
    elif args.provider == "deepseek":
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ["LANGCHAIN_PROVIDER"] = "deepseek"
        os.environ.setdefault("VIBE_TRADING_CONTEXT_WINDOW", "1000000")   # 1M per api-docs.deepseek.com, read 2026-10-28
    else:
        raise SystemExit(f"provider {args.provider!r} is not wired for Vibe-Trading yet (ollama, deepseek)")
    vt_dir = Path(args.vt_dir).resolve()
    sys.path.insert(0, str(vt_dir / "agent"))
    os.chdir(args.run_dir)
    return vt_dir


def local_context_window(base_url: str) -> int | None:
    """The context size a local server actually serves: llama.cpp's /props (n_ctx), else None (Vibe-Trading's default)."""
    import urllib.request

    root = base_url.rstrip("/").removesuffix("/v1")
    try:
        props = json.loads(urllib.request.urlopen(f"{root}/props", timeout=3).read())
        n_ctx = int((props.get("default_generation_settings") or {}).get("n_ctx") or 0)
        return n_ctx or None
    except Exception:
        return None


def vt_version(vt_dir: Path) -> str:
    import importlib.metadata as md
    import subprocess

    try:
        pkg = md.version("vibe-trading-ai")
    except md.PackageNotFoundError:
        pkg = "unknown"
    sha = subprocess.run(["git", "-C", str(vt_dir), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    return f"{pkg}+{sha}" if sha else pkg


def make_llm_tap(model: str, agent: str):
    from langchain_core.callbacks import BaseCallbackHandler

    class LlmTap(BaseCallbackHandler):
        def __init__(self):
            self._start: dict[str, float] = {}

        def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
            self._start[str(run_id)] = time.time()
            chars = sum(len(str(getattr(m, "content", ""))) for batch in messages for m in batch)
            emit("llm.started", agent, call=str(run_id), model=model, prompt_chars=chars)

        def on_llm_end(self, response, *, run_id, **kwargs):
            tokens_in = tokens_out = reasoning = cached = 0
            served = None
            try:
                message = response.generations[0][0].message
                usage = getattr(message, "usage_metadata", None) or {}
                tokens_in, tokens_out = int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0)
                reasoning = int((usage.get("output_token_details") or {}).get("reasoning") or 0)
                cached = int((usage.get("input_token_details") or {}).get("cache_read") or 0)
                served = (getattr(message, "response_metadata", None) or {}).get("model_name")
            except (AttributeError, IndexError, TypeError, ValueError):
                pass
            start = self._start.pop(str(run_id), time.time())
            emit("llm.finished", agent, call=str(run_id), model=model, served_model=served, tokens_in=tokens_in,
                 tokens_out=tokens_out, reasoning=reasoning, cached=cached, duration=round(time.time() - start, 3))

        def on_llm_error(self, error, *, run_id, **kwargs):
            self._start.pop(str(run_id), None)
            emit("llm.failed", agent, call=str(run_id), error=str(error)[:500])

    return LlmTap()


def restrict_and_tap(registry, run_dir: Path, agent: str = AGENT) -> list[str]:
    """Keep the allowlisted tools only, and report every call with its full output saved under tool_outputs/.

    The tap sits on each tool object, not on the registry: AgentLoop wraps the registry in a DeferredToolRegistry (its
    load_tools meta tool) that copies the tool objects, so a registry-level patch is bypassed. load_tools can only expose
    tools present in the registry, so the allowlist also bounds what it can load. Each registry build makes new tool
    objects, so a committee member's tools carry that member's lane."""
    registry._tools = {name: tool for name, tool in registry._tools.items() if name in TOOL_ALLOWLIST}
    out_dir = run_dir / "tool_outputs"
    out_dir.mkdir(parents=True, exist_ok=True)

    def tap(name, execute):
        def tapped(**params):
            call = uuid.uuid4().hex
            n = next(_COUNTER)
            start = time.time()
            shown = {k: v for k, v in params.items() if k != "run_dir"}   # Vibe-Trading's own working folder: a local path, no signal
            emit("tool.called", agent, call=call, tool=name, args=json.dumps(shown, ensure_ascii=False, default=str)[:2000])
            try:
                result = execute(**params)
            except Exception as exc:
                emit("tool.failed", agent, call=call, tool=name, error=str(exc)[:500])
                raise
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
            file_name = f"{n:03d}_{agent}_{name}.txt"
            (out_dir / file_name).write_text(text, encoding="utf-8")
            low = text[:300].lower()
            flag = "tool error" if low.startswith(("error", "{\"error", "{\"status\": \"error")) or "\"status\": \"error\"" in low else None
            emit("tool.result", agent, call=call, tool=name, duration=round(time.time() - start, 3), chars=len(text),
                 preview=text[:PREVIEW_CHARS], file=f"tool_outputs/{file_name}", flag=flag)
            return result

        return tapped

    for name, tool in registry._tools.items():
        if name != "compact":
            tool.execute = tap(name, tool.execute)
    return sorted(registry._tools)


def describe(args) -> int:
    vt_dir = setup_env(args)
    from src.tools import build_registry

    registry = build_registry(include_shell_tools=False)
    names = list(registry._tools)
    print(json.dumps({"version": vt_version(vt_dir), "tools": sorted(n for n in names if n in TOOL_ALLOWLIST),
                      "tools_total": len(names), "left_out": sorted(n for n in names if n not in TOOL_ALLOWLIST)}))
    return 0


def run_single(args, run_dir: Path) -> dict:
    from src.agent.loop import AgentLoop
    from src.memory.persistent import PersistentMemory
    from src.providers.chat import ChatLLM
    from src.tools import build_registry

    session = f"glassbench-{uuid.uuid4().hex[:8]}"
    memory = PersistentMemory()
    registry = build_registry(persistent_memory=memory, include_shell_tools=False, session_id=session, interactive=False)
    tools = restrict_and_tap(registry, run_dir)
    llm = ChatLLM(model_name=args.model)
    llm._llm.callbacks = [*(getattr(llm._llm, "callbacks", None) or []), make_llm_tap(args.model, AGENT)]
    emit("driver.started", None, mode="single", tools=tools, max_iterations=args.max_iter)

    def on_event(kind, data):
        if kind == "text_delta" and data.get("delta"):
            emit("llm.delta", AGENT, text=data["delta"])

    prompt = PROMPT.format(ticker=args.ticker, date=args.date)
    emit("agent.started", AGENT, visit=1)
    start = time.time()
    agent = AgentLoop(registry=registry, llm=llm, event_callback=on_event, max_iterations=args.max_iter,
                      persistent_memory=memory)
    result = agent.run(prompt, session_id=session)
    content = str(result.get("content") or "")
    (run_dir / "reports" / "vibe_trading.md").write_text(content, encoding="utf-8")
    emit("report.updated", AGENT, text=content)
    emit("agent.finished", AGENT, duration=round(time.time() - start, 3))
    return {"status": result.get("status"), "content": content, "iterations": result.get("iterations"), "prompt": prompt}


def run_committee(args, run_dir: Path) -> dict:
    """Vibe-Trading's investment_committee preset through its own SwarmRuntime, with Glassbench's hooks around it."""
    import src.swarm.runtime as runtime
    import src.swarm.worker as worker
    from src.config.loader import load_swarm_agent_config
    from src.config.paths import get_swarm_runs_dir
    from src.swarm.store import SwarmStore

    build_run = runtime.build_run_from_preset

    def build_run_for_glassbench(name, user_vars):
        run = build_run(name, user_vars)
        for spec in run.agents:
            spec.tools = [t for t in dict.fromkeys([*spec.tools, *COMMITTEE_EXTRA_TOOLS]) if t in TOOL_ALLOWLIST]
            spec.system_prompt += NO_SHELL_NOTE + (PM_NOTE if spec.id == "portfolio_manager" else "")
            # Fewer steps per agent on a local server, so each one's context stays inside the window it serves.
            cap = min(args.max_iter, 10) if args.provider == "ollama" else args.max_iter
            spec.max_iterations = min(spec.max_iterations or cap, cap)
            if args.provider == "ollama":
                spec.timeout_seconds = max(spec.timeout_seconds or 0, 3600)
        return run

    run_worker = runtime.run_worker

    def run_worker_in_lane(*a, **kw):
        token = CURRENT_AGENT.set(kw["agent_spec"].id)
        try:
            return run_worker(*a, **kw)
        finally:
            CURRENT_AGENT.reset(token)

    build_registry = worker.build_swarm_registry

    def build_tapped_registry(tool_names, **kw):
        registry = build_registry([t for t in tool_names if t in TOOL_ALLOWLIST], **kw)
        restrict_and_tap(registry, run_dir, CURRENT_AGENT.get())
        return registry

    chat_cls = worker.ChatLLM

    class TappedChatLLM(chat_cls):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self._llm.callbacks = [*(getattr(self._llm, "callbacks", None) or []), make_llm_tap(args.model, CURRENT_AGENT.get())]

    runtime.build_run_from_preset = build_run_for_glassbench
    runtime.run_worker = run_worker_in_lane
    worker.build_swarm_registry = build_tapped_registry
    worker.ChatLLM = TappedChatLLM

    store = SwarmStore(base_dir=get_swarm_runs_dir())
    from src.config.accessor import get_env_config

    # The constructor defaults to four workers and does not read SWARM_MAX_WORKERS; pass it as Vibe-Trading's own tool does.
    swarm = runtime.SwarmRuntime(store=store, max_workers=get_env_config().swarm.swarm_max_workers,
                                 agent_config=load_swarm_agent_config())
    done = threading.Event()
    started: dict[str, float] = {}
    reported: set[str] = set()
    closed: set[str] = set()
    holder: dict = {}

    def report_finished_tasks():
        run = store.load_run(holder["id"]) if holder.get("id") else None
        if run is None:
            return run
        for task in run.tasks:
            if task.agent_id in reported or not task.summary:
                continue
            reported.add(task.agent_id)
            emit("report.updated", task.agent_id, text=task.summary)
            finish(task.agent_id, str(getattr(task.status, "value", task.status)))
        return run

    def finish(agent: str, status: str):
        # A worker ends before its task's summary reaches the store, so the card closes on the worker's own event.
        if agent and agent not in closed:
            closed.add(agent)
            emit("agent.finished", agent, duration=round(time.time() - started.get(agent, time.time()), 3), status=status)

    def on_swarm(event):
        kind, agent, data = event.type, event.agent_id, event.data or {}
        if kind == "worker_started" and agent:
            started.setdefault(agent, time.time())
            emit("agent.started", agent, visit=1)
        elif kind == "worker_text" and agent and data.get("content"):
            emit("llm.delta", agent, text=data["content"])
        elif kind == "worker_completed":
            finish(agent, "completed")
        elif kind in ("worker_failed", "worker_timeout", "worker_iteration_limit", "worker_token_limit", "worker_incomplete"):
            emit("data.flag", agent, label=kind.replace("worker_", "").replace("_", " "), source="Vibe-Trading",
                 detail=str(data.get("error") or data.get("tokens") or "")[:300])
            finish(agent, kind.replace("worker_", ""))
        elif kind == "task_completed":
            report_finished_tasks()
        elif kind in ("run_completed", "run_error"):
            holder["final_status"] = data.get("status") or kind
            done.set()

    emit("driver.started", None, mode="committee", preset="investment_committee", tools=list(TOOL_ALLOWLIST),
         max_iterations=args.max_iter)
    run = swarm.start_run("investment_committee", {"target": args.ticker, "market": "US"}, live_callback=on_swarm,
                          include_shell_tools=False)
    holder["id"] = run.id
    # The runtime runs the swarm on its own thread and signals the end through run_completed. If that thread dies first
    # (an unhandled error inside Vibe-Trading), nothing would ever signal, so watch the thread and a deadline too.
    timeout = args.timeout or (10800 if args.provider == "ollama" else 3600)
    deadline = time.time() + timeout
    while not done.wait(5):
        if not any(t.name == f"swarm-{run.id}" and t.is_alive() for t in threading.enumerate()) and not done.is_set():
            raise RuntimeError("Vibe-Trading's swarm stopped without finishing; its error is in the run's log")
        if time.time() > deadline:
            swarm.cancel_run(run.id)
            raise RuntimeError(f"Vibe-Trading's committee did not finish within {timeout} s")
    run = report_finished_tasks() or run
    summaries = {t.agent_id: t.summary or "" for t in run.tasks}
    decision_text = summaries.get("portfolio_manager", "")
    reports = run_dir / "reports"
    for agent_id, text in summaries.items():
        (reports / f"{agent_id}.md").write_text(text, encoding="utf-8")
    (reports / "final_report.md").write_text(run.final_report or "", encoding="utf-8")
    return {"status": holder.get("final_status"), "content": decision_text, "final_report": run.final_report,
            "iterations": None, "swarm_run_id": run.id, "tokens_reported": [run.total_input_tokens, run.total_output_tokens]}


def main() -> int:
    # The answer can hold any character; the parent reads UTF-8 whatever the console code page is.
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker")
    ap.add_argument("--date")
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--base-url", default="http://127.0.0.1:11434/v1")
    ap.add_argument("--run-dir", default=".")
    ap.add_argument("--vt-dir", default=str(Path(__file__).resolve().parents[2] / "Vibe-Trading"))
    ap.add_argument("--mode", choices=("committee", "single"), default="committee")
    ap.add_argument("--max-iter", type=int, default=25)
    ap.add_argument("--timeout", type=int, default=None,
                    help="seconds a committee may run before it is cancelled (default 3 h on a local server, 1 h otherwise)")
    ap.add_argument("--describe", action="store_true")
    args = ap.parse_args()
    if args.describe:
        return describe(args)

    run_dir = Path(args.run_dir).resolve()
    args.run_dir = str(run_dir)
    vt_dir = setup_env(args)
    (run_dir / "reports").mkdir(exist_ok=True)
    try:
        emit("driver.version", None, vt_version=vt_version(vt_dir), model=args.model, provider=args.provider)
        result = run_committee(args, run_dir) if args.mode == "committee" else run_single(args, run_dir)
        emit("driver.finished", None, **result)
        return 0
    except Exception as exc:
        emit("driver.failed", None, error=f"{type(exc).__name__}: {exc}"[:1000], traceback=traceback.format_exc()[-4000:])
        return 1


if __name__ == "__main__":
    sys.exit(main())
