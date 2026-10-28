"""Runs TradingAgents with full event capture. Same steps as propagate(), plus streaming."""

from __future__ import annotations

import contextlib
import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

from . import adapter, aihf, vibe
from .capture import CURRENT_CAPTURE, EngineLogCapture, RunCapture, _text_of, install_local_usage
from .events import EventBus
from .reasoning import install_reasoning_tap
from .runconfig import CURRENT_CONFIG, install_run_config
from .variants import ensure_available, install_variants
from .settings import AIHF_ENGINE, BACKTESTS_DIR, MAX_CONCURRENT_RUNS, RUNS_DIR, VT_ENGINE, engine_config, engine_version
from .store import Store

log = logging.getLogger("deskapp.runner")


class RunCancelled(Exception):
    pass


class RunManager:
    def __init__(self, store: Store, bus: EventBus, workers: int = MAX_CONCURRENT_RUNS):
        self.store = store
        self.bus = bus
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="desk-run")
        self._cancel: dict[str, threading.Event] = {}
        self.aihf_fixture = False  # tests only: canned data and answers for AI Hedge Fund runs
        self._log_capture = EngineLogCapture()
        logging.getLogger("tradingagents").addHandler(self._log_capture)
        install_reasoning_tap()
        install_variants()
        install_local_usage()

    def submit(self, ticker: str, trade_date: str, analysts: list[str], depth: int, deep_model: str, quick_model: str,
               purpose: str = "live", backtest_id: str | None = None, memory: str = "shared", variant: str = "",
               provider: str = "deepseek") -> str:
        ensure_available(variant)
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + ticker.replace("/", "_").upper() + "-" + uuid.uuid4().hex[:4]
        self.store.create_run({
            "id": run_id, "ticker": ticker.upper(), "trade_date": trade_date, "analysts": analysts, "depth": depth,
            "deep_model": deep_model, "quick_model": quick_model, "status": "queued", "created_at": time.time(),
            "engine": "tradingagents", "engine_version": engine_version(), "provider": provider,
            "purpose": purpose, "backtest_id": backtest_id, "memory": memory, "variant": variant,
        })
        self._cancel[run_id] = threading.Event()
        self.bus.emit(run_id, "run.queued", None, ticker=ticker.upper(), trade_date=trade_date, analysts=analysts,
                      depth=depth, deep_model=deep_model, quick_model=quick_model, purpose=purpose, backtest_id=backtest_id, memory=memory, variant=variant, provider=provider,
                      agents=[a["id"] for a in adapter.agents_for(analysts)])
        self.pool.submit(self._execute, run_id)
        return run_id

    def submit_aihf(self, ticker: str, trade_date: str, strategy: str | None, analysts: list[str] | None, model: str,
                    purpose: str = "live", data_source: str = "financial-datasets") -> str:
        """Queue one AI Hedge Fund cycle: a library strategy or a custom set of analysts, on one model and one data source."""
        staff, variant = aihf.plan(strategy, analysts)
        if data_source not in aihf.DATA_SOURCES:
            raise ValueError(f"Unknown data source {data_source!r}. Choose one of: {', '.join(aihf.DATA_SOURCES)}.")
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + ticker.replace("/", "_").upper() + "-" + uuid.uuid4().hex[:4]
        self.store.create_run({
            "id": run_id, "ticker": ticker.upper(), "trade_date": trade_date, "analysts": staff, "depth": 0,
            "deep_model": model, "quick_model": model, "status": "queued", "created_at": time.time(),
            "engine": AIHF_ENGINE, "engine_version": aihf.version(), "provider": (aihf.model_key(model) or "").split("_")[0].lower(),
            "purpose": purpose, "backtest_id": None, "memory": "off", "variant": variant, "data_source": data_source,
        })
        self._cancel[run_id] = threading.Event()
        meta = aihf.agent_meta(staff, data_source)
        self.bus.emit(run_id, "run.queued", None, ticker=ticker.upper(), trade_date=trade_date, analysts=staff, depth=0,
                      deep_model=model, quick_model=model, purpose=purpose, backtest_id=None, memory="off", variant=variant,
                      provider=(aihf.model_key(model) or "").split("_")[0].lower(), engine=AIHF_ENGINE,
                      agents=[a["id"] for a in meta], agent_meta=meta, stages=aihf.STAGES, data_source=data_source,
                      data_label=aihf.DATA_SOURCES[data_source]["label"])
        self.pool.submit(self._execute, run_id)
        return run_id

    def submit_vibe(self, ticker: str, trade_date: str, model: str, provider: str = "ollama", mode: str = "committee",
                    purpose: str = "live") -> str:
        """Queue one Vibe-Trading analysis on one model with read-only tools: its investment committee, or one agent."""
        if provider not in vibe.PROVIDERS:
            raise ValueError(f"Vibe-Trading runs on {', '.join(vibe.PROVIDERS)} for now, not {provider!r}.")
        if mode not in vibe.MODES:
            raise ValueError(f"Unknown Vibe-Trading mode {mode!r}. Choose one of: {', '.join(vibe.MODES)}.")
        layout = vibe.LAYOUTS[mode]
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + ticker.replace("/", "_").upper() + "-" + uuid.uuid4().hex[:4]
        self.store.create_run({
            "id": run_id, "ticker": ticker.upper(), "trade_date": trade_date, "analysts": ["vibe"], "depth": 0,
            "deep_model": model, "quick_model": model, "status": "queued", "created_at": time.time(),
            "engine": VT_ENGINE, "engine_version": vibe.version(), "provider": provider,
            "purpose": purpose, "backtest_id": None, "memory": "off", "variant": mode,
        })
        self._cancel[run_id] = threading.Event()
        self.bus.emit(run_id, "run.queued", None, ticker=ticker.upper(), trade_date=trade_date, analysts=["vibe"], depth=0,
                      deep_model=model, quick_model=model, purpose=purpose, backtest_id=None, memory="off", variant=mode,
                      provider=provider, engine=VT_ENGINE, agents=[a["id"] for a in layout["agents"]],
                      agent_meta=layout["agents"], stages=layout["stages"])
        self.pool.submit(self._execute, run_id)
        return run_id

    def cancel(self, run_id: str) -> bool:
        flag = self._cancel.get(run_id)
        if flag is None:
            return False
        flag.set()
        run = self.store.get_run(run_id)
        if run and run["status"] == "queued":
            # Not started yet: settle it now instead of when a worker frees up.
            self._finish_cancelled(run_id, None)
        return True

    # ------------------------------------------------------------------------
    def _execute(self, run_id: str) -> None:
        run = self.store.get_run(run_id)
        if run is None or run["status"] != "queued":
            return  # cancelled while waiting in the queue
        cancel = self._cancel.setdefault(run_id, threading.Event())
        if cancel.is_set():
            self._finish_cancelled(run_id, None)
            return

        if run.get("engine") == AIHF_ENGINE:
            self._execute_aihf(run_id, run, cancel)
            return
        if run.get("engine") == VT_ENGINE:
            self._execute_foreign(vibe.execute, run_id, run, cancel)
            return

        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        capture = RunCapture(self.bus, run_id, run_dir)
        capture.variant = run.get("variant") or ""
        token = CURRENT_CAPTURE.set(capture)
        config_token = None
        ticker, trade_date = run["ticker"], run["trade_date"]
        self.store.update_run(run_id, status="running", started_at=time.time())
        self.bus.emit(run_id, "run.started", None, ticker=ticker, trade_date=trade_date)

        try:
            from tradingagents.graph.trading_graph import TradingAgentsGraph
            from tradingagents.reporting import write_report_tree

            shared_memory = run.get("memory", "shared") != "off"
            # Memory off (backtests): an isolated log that is never read or scored, so no lesson from another
            # date can reach this decision and the shared live log stays untouched.
            isolated_log = None if shared_memory else BACKTESTS_DIR / (run.get("backtest_id") or "adhoc") / "memory_unused.md"
            config = engine_config(run["depth"], run["deep_model"], run["quick_model"], memory_log_path=isolated_log,
                                   variant=run.get("variant") or "", provider=run.get("provider") or "deepseek")
            # The engine's data config is process-wide; this run must read its own (see runconfig.py).
            install_run_config()
            config_token = CURRENT_CONFIG.set(config)
            graph = TradingAgentsGraph(selected_analysts=run["analysts"], debug=False, config=config)

            if hasattr(graph, "create_run_state"):
                # 0.5.1: the engine settles this ticker's pending decisions, loads the lessons known by the date and
                # resolves the instrument itself. With memory off the log is the isolated one, so nothing carries over.
                try:
                    state = graph.create_run_state(ticker, trade_date, "stock")
                except Exception as exc:  # settling needs prices; never block the run on it
                    capture.add_flag(None, "Memory scoring skipped", str(exc))
                    state = graph.propagator.create_initial_state(
                        ticker, trade_date, asset_type="stock",
                        instrument_context=graph.resolve_instrument_context(ticker, "stock", trade_date),
                    )
                past_context = state.get("past_context") or "" if shared_memory else ""
                instrument_context = state.get("instrument_context")
            else:
                # 0.5.0: the same steps by hand (what the CLI skipped).
                graph.ticker = ticker
                past_context = ""
                if shared_memory:
                    try:
                        graph._resolve_pending_entries(ticker)
                    except Exception as exc:  # scoring needs prices; never block the run on it
                        capture.add_flag(None, "Memory scoring skipped", str(exc))
                    past_context = graph.memory_log.get_past_context(ticker, as_of=graph._memory_as_of(trade_date))
                instrument_context = graph.resolve_instrument_context(ticker, "stock")
                state = graph.propagator.create_initial_state(
                    ticker, trade_date, asset_type="stock", past_context=past_context, instrument_context=instrument_context,
                )
            if past_context:
                self.bus.emit(run_id, "memory.context", "portfolio_manager", chars=len(past_context), preview=past_context[:1200])
            self.bus.emit(run_id, "instrument.resolved", None, context=instrument_context)
            args = graph.propagator.get_graph_args(callbacks=[capture])
            args["stream_mode"] = ["updates", "messages"]
            try:  # 0.6.0: the engine serves each run its own config while it runs
                from tradingagents.dataflows.config import run_config as engine_run_config
            except ImportError:
                engine_run_config = None

            final_state = dict(state)
            reported: dict[str, str] = {}  # last report shown per agent, so a report filed once is shown once
            # Since 0.6.0 each analyst works in a graph of its own, whose tokens and report reach the stream only
            # with subgraphs on; on older engines every step simply comes with an empty namespace.
            with engine_run_config(config) if engine_run_config else contextlib.nullcontext():
                for namespace, mode, chunk in graph.graph.stream(state, subgraphs=True, **args):
                    if cancel.is_set():
                        raise RunCancelled()
                    if mode == "messages":
                        message, meta = chunk
                        agent_id = adapter.speaker(meta)
                        text = _text_of(getattr(message, "content", ""))
                        if agent_id and text and type(message).__name__.endswith("Chunk"):
                            capture.add_delta(agent_id, text)
                        continue
                    if namespace:
                        self._analyst_step(run_id, namespace, chunk, final_state, reported)
                        continue
                    for node, update in (chunk or {}).items():
                        if not isinstance(update, dict):
                            continue
                        final_state.update(update)
                        if node == "Memory Log" and update.get("past_context") and shared_memory:  # 0.6.0
                            text = update["past_context"]
                            self.bus.emit(run_id, "memory.context", "portfolio_manager", chars=len(text), preview=text[:1200])
                        agent_id, kind = adapter.NODE_MAP.get(node, (None, None))
                        if kind != "agent":
                            continue
                        text = adapter.agent_text(agent_id, final_state)
                        if text and reported.get(agent_id) != text:
                            reported[agent_id] = text
                            self.bus.emit(run_id, "report.updated", agent_id, text=text)
                        if agent_id == "research_manager":
                            self.bus.emit(run_id, "decision.structured", agent_id, **adapter.parse_research_plan(final_state.get("investment_plan", "")))
                        elif agent_id == "trader":
                            self.bus.emit(run_id, "decision.structured", agent_id, **adapter.parse_trader_plan(final_state.get("trader_investment_plan", "")))
                        elif agent_id == "portfolio_manager":
                            self.bus.emit(run_id, "decision.structured", agent_id, **adapter.parse_pm_decision(final_state.get("final_trade_decision", "")))
                    self._sync_totals(run_id, capture)
            capture.flush()

            try:
                from tradingagents.agents.rating import run_rating  # 0.6.0 replaced process_signal
                rating = run_rating(final_state)
            except ImportError:
                rating = graph.process_signal(final_state.get("final_trade_decision", ""))
            try:
                graph._log_state(trade_date, final_state)
            except Exception as exc:
                log.warning("engine state log failed: %s", exc)
            if shared_memory:
                if hasattr(graph, "record_decision"):  # 0.5.1
                    graph.record_decision(ticker, trade_date, final_state)
                else:
                    graph.memory_log.store_decision(
                        ticker=ticker, trade_date=trade_date, final_trade_decision=final_state.get("final_trade_decision", ""),
                    )

            write_report_tree(final_state, ticker, run_dir / "reports")
            (run_dir / "state.json").write_text(json.dumps(adapter.state_snapshot(final_state), indent=2, ensure_ascii=False), encoding="utf-8")
            decision = adapter.parse_decision(final_state)
            self._sync_totals(run_id, capture)
            self.store.update_run(run_id, status="finished", finished_at=time.time(), rating=rating, decision=decision,
                                  models_served=sorted(capture.models_served))
            self.bus.emit(run_id, "run.finished", None, rating=rating, decision=decision, **capture.totals)
        except RunCancelled:
            self._finish_cancelled(run_id, capture)
        except Exception as exc:
            capture.flush()
            self._sync_totals(run_id, capture)
            tb = traceback.format_exc(limit=6)
            log.error("run %s failed: %s", run_id, tb)
            self.store.update_run(run_id, status="failed", finished_at=time.time(), error=f"{type(exc).__name__}: {exc}"[:1000])
            self.bus.emit(run_id, "run.failed", None, error=f"{type(exc).__name__}: {exc}"[:1000], traceback=tb[-3000:])
        finally:
            CURRENT_CAPTURE.reset(token)
            if config_token is not None:
                CURRENT_CONFIG.reset(config_token)
            self._cancel.pop(run_id, None)

    def _analyst_step(self, run_id: str, namespace: tuple, chunk, final_state: dict, reported: dict[str, str]) -> None:
        """A step inside an analyst's own graph (0.6.0+): show its report as soon as the analyst files it.

        The run's state takes the analysts' reports only when the slowest analyst has finished; the step
        that writes a report arrives earlier, so the board fills as each analyst finishes.
        """
        outer = str(namespace[0]).split(":", 1)[0]
        agent_id, kind = adapter.NODE_MAP.get(outer, (None, None))
        if kind != "agent":
            return
        report_key = adapter.AGENT_BY_ID[agent_id]["text"][0]
        for update in (chunk or {}).values():
            text = update.get(report_key) if isinstance(update, dict) else None
            if isinstance(text, str) and text.strip() and reported.get(agent_id) != text:
                final_state[report_key] = text
                reported[agent_id] = text
                self.bus.emit(run_id, "report.updated", agent_id, text=text)

    def _execute_aihf(self, run_id: str, run: dict, cancel: threading.Event) -> None:
        self._execute_foreign(lambda m, r_id, r, c: aihf.execute(m, r_id, r, c, fixture=self.aihf_fixture), run_id, run, cancel)

    def _execute_foreign(self, execute, run_id: str, run: dict, cancel: threading.Event) -> None:
        """A framework driven as a subprocess (AI Hedge Fund, Vibe-Trading): same start, cancel and failure handling."""
        self.store.update_run(run_id, status="running", started_at=time.time())
        self.bus.emit(run_id, "run.started", None, ticker=run["ticker"], trade_date=run["trade_date"])
        try:
            execute(self, run_id, run, cancel)
        except RunCancelled:
            self._finish_cancelled(run_id, None)
        except Exception as exc:
            tb = traceback.format_exc(limit=6)
            log.error("run %s failed: %s", run_id, tb)
            self.store.update_run(run_id, status="failed", finished_at=time.time(), error=f"{type(exc).__name__}: {exc}"[:1000])
            self.bus.emit(run_id, "run.failed", None, error=f"{type(exc).__name__}: {exc}"[:1000], traceback=tb[-3000:])
        finally:
            self._cancel.pop(run_id, None)

    def _sync_totals(self, run_id: str, capture: RunCapture) -> None:
        t = capture.totals
        self.store.update_run(run_id, tokens_in=t["tokens_in"], tokens_out=t["tokens_out"], cost_usd=round(t["cost_usd"], 6),
                              llm_calls=t["llm_calls"], tool_calls=t["tool_calls"], flags=t["flags"])

    def _finish_cancelled(self, run_id: str, capture: RunCapture | None) -> None:
        if capture:
            capture.flush()
            self._sync_totals(run_id, capture)
        self.store.update_run(run_id, status="cancelled", finished_at=time.time())
        self.bus.emit(run_id, "run.cancelled", None)
