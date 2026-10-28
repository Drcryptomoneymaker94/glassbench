"""Vibe-Trading (HKUDS/Vibe-Trading) as a Glassbench framework.

Vibe-Trading is a general research agent: one ReAct loop over a large tool catalogue, with no fixed pipeline and no
rating scale. Glassbench drives one analysis per run through backend/drivers/vt_driver.py, in Vibe-Trading's own
virtual environment, with a fixed prompt and read-only data tools only, and maps the closing JSON block of the answer
to the same five ratings the other frameworks use (RATING_RULE). Vibe-Trading has no date input: its prompt says
today's date and its news and web tools return current items, so runs dated in the past are flagged as not point in time.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from datetime import date
from pathlib import Path

from .settings import KEY_ALLOWLIST, RUNS_DIR, VT_DIR, VT_DRIVER, VT_ENGINE, VT_MAX_ITERATIONS, VT_PYTHON, estimate_cost, vt_version

# Two modes, stored in the run's variant field. "committee" is Vibe-Trading's own investment_committee swarm preset,
# "single" one research agent on Glassbench's prompt.
MODES = ("committee", "single")
DECISION_AGENT = {"id": "decision", "label": "Decision", "name": "Closing decision", "stage": "decision", "role": "rule",
                  "reads": ["the JSON block that ends the portfolio manager's answer"], "analyst_key": None}
LAYOUTS = {
    "committee": {
        "stages": [{"id": "research", "label": "Bull and bear"}, {"id": "risk", "label": "Risk"},
                   {"id": "pm", "label": "Portfolio manager"}, {"id": "decision", "label": "Decision"}],
        "agents": [
            {"id": "bull_advocate", "label": "Bull", "name": "Bull-side researcher", "stage": "research", "role": "quick",
             "reads": ["prices and technicals", "statements, flows, research reports", "news"], "analyst_key": None},
            {"id": "bear_advocate", "label": "Bear", "name": "Bear-side researcher", "stage": "research", "role": "quick",
             "reads": ["prices and technicals", "statements, options", "news"], "analyst_key": None},
            {"id": "risk_officer", "label": "Risk officer", "name": "Chief risk officer", "stage": "risk", "role": "quick",
             "reads": ["the bull and bear reports", "prices, options, statements"], "analyst_key": None},
            {"id": "portfolio_manager", "label": "Portfolio manager", "name": "Portfolio manager", "stage": "pm",
             "role": "quick", "reads": ["the risk review with both reports"], "analyst_key": None},
            DECISION_AGENT,
        ],
    },
    "single": {
        "stages": [{"id": "research", "label": "Research"}, {"id": "decision", "label": "Decision"}],
        "agents": [
            {"id": "vibe", "label": "Vibe-Trading", "name": "Vibe-Trading research agent", "stage": "research", "role": "quick",
             "reads": ["prices and technical indicators", "fundamentals and financial statements", "news, sentiment and the web"],
             "analyst_key": None},
            {**DECISION_AGENT, "reads": ["the JSON block that ends the agent's answer"]},
        ],
    },
}
RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
ACTION_RATING = {"long": "Overweight", "short": "Underweight", "wait": "Hold", "hedge": "Hold"}
RATING_RULE = ("Glassbench asks Vibe-Trading to end its answer with a JSON block holding a rating on the five-step scale. "
               "When the block has no valid rating, its action is mapped instead: long to Overweight, short to "
               "Underweight, wait or hedge to Hold. With neither, the run has no rating.")
PROVIDERS = {"ollama": None, "deepseek": "DEEPSEEK_API_KEY"}   # provider -> the key it needs (None = none)


def installed() -> bool:
    return VT_PYTHON.exists() and VT_DRIVER.exists()


def meta_for_ui() -> dict:
    return {"installed": installed(), "version": vt_version() if installed() else None, "providers": list(PROVIDERS),
            "modes": list(MODES), "rating_rule": RATING_RULE, "dir": str(VT_DIR)}


def version() -> str:
    return vt_version()


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"-?\d[\d,]*\.?\d*", str(value))
    return float(m.group(0).replace(",", "")) if m else None


def parse_decision(content: str) -> tuple[str | None, dict]:
    """The rating and the decision fields from the last JSON block of the answer."""
    blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", content or "", re.S)
    data: dict = {}
    for raw in reversed(blocks):
        # Vibe-Trading's grounding guard replaces numbers it cannot match to the session's tool data with
        # "(omitted※)", also as a bare JSON value; read those as null.
        raw = re.sub(r":\s*\(omitted[^)\n]*\)", ": null", raw)
        try:
            data = json.loads(raw)
            break
        except json.JSONDecodeError:
            continue
    decision = {
        "action": str(data.get("action") or "").strip().lower() or None,
        "entry": _number(data.get("entry")), "stop": _number(data.get("stop")), "target": _number(data.get("target")),
        "horizon": data.get("horizon"), "confidence": _number(data.get("confidence")), "thesis": data.get("thesis"),
        "rating_rule": RATING_RULE,
    }
    rating = next((r for r in RATINGS if str(data.get("rating") or "").strip().lower() == r.lower()), None)
    if rating:
        decision["rating_how"] = "stated"
    elif decision["action"] in ACTION_RATING:
        rating = ACTION_RATING[decision["action"]]
        decision["rating_how"] = "mapped from action"
    else:
        decision["rating_how"] = "missing"
    return rating, decision


def _child_env(keys: set[str]) -> dict:
    """The parent environment without the API keys this run does not need."""
    env = {k: v for k, v in os.environ.items() if k not in KEY_ALLOWLIST or k in keys}
    env.pop("OPENAI_API_KEY", None)   # Vibe-Trading falls back to it for other providers; never hand it over
    env["PYTHONUTF8"] = "1"
    return env


def execute(manager, run_id: str, run: dict, cancel: threading.Event) -> None:
    """Drive one analysis and relay its events. Raises RunCancelled on cancel; any other failure marks the run failed."""
    from .runner import RunCancelled

    store, bus = manager.store, manager.bus
    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    provider, model = run.get("provider") or "ollama", run["quick_model"]
    base_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    argv = [str(VT_PYTHON), str(VT_DRIVER), "--ticker", run["ticker"], "--date", run["trade_date"], "--model", model,
            "--provider", provider, "--base-url", base_url, "--run-dir", str(run_dir), "--vt-dir", str(VT_DIR),
            "--max-iter", str(VT_MAX_ITERATIONS), "--mode", run.get("variant") or "committee"]
    keys = {PROVIDERS.get(provider) or ""}

    totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "llm_calls": 0, "tool_calls": 0, "flags": 0}
    served: set[str] = set()
    finished: dict | None = None
    failure: str | None = None
    engine_info: dict = {}

    def sync():
        store.update_run(run_id, tokens_in=totals["tokens_in"], tokens_out=totals["tokens_out"],
                         cost_usd=round(totals["cost_usd"], 6), llm_calls=totals["llm_calls"],
                         tool_calls=totals["tool_calls"], flags=totals["flags"])

    if run["trade_date"] < date.today().isoformat():
        totals["flags"] += 1
        bus.emit(run_id, "data.flag", None, label="Not point in time", source="Vibe-Trading",
                 detail="Vibe-Trading has no date input: its prompt carries today's date and its news and web tools return current items.")
    with open(run_dir / "vibe_trading.log", "w", encoding="utf-8") as errlog:
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=errlog, text=True, encoding="utf-8",
                                cwd=run_dir, env=_child_env(keys))
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                if cancel.is_set():
                    raise RunCancelled()
                try:
                    line = json.loads(raw)
                except json.JSONDecodeError:
                    errlog.write(raw)
                    continue
                type_, agent = line.pop("type", ""), line.pop("agent", None)
                if type_ == "driver.version":
                    engine_info = line
                    continue
                if type_ == "driver.started":
                    bus.emit(run_id, "engine.started", None, engine=VT_ENGINE, version=engine_info.get("vt_version"),
                             model=engine_info.get("model"), mode=line.get("mode"), preset=line.get("preset"),
                             tools=line.get("tools"), max_iterations=line.get("max_iterations"))
                    continue
                if type_ == "driver.finished":
                    finished = line
                    continue
                if type_ == "driver.failed":
                    failure = line.get("error") or "Vibe-Trading failed"
                    errlog.write(line.get("traceback") or "")
                    continue
                if type_ == "llm.started":
                    totals["llm_calls"] += 1
                elif type_ == "llm.finished":
                    if line.get("served_model"):
                        served.add(f"{model} -> {line['served_model']}")
                    cost = estimate_cost(model, line.get("tokens_in", 0), line.get("tokens_out", 0))
                    line["cost_usd"] = cost
                    totals["tokens_in"] += line.get("tokens_in", 0)
                    totals["tokens_out"] += line.get("tokens_out", 0)
                    totals["cost_usd"] += cost or 0.0
                elif type_ == "tool.called":
                    totals["tool_calls"] += 1
                elif type_ == "data.flag":
                    totals["flags"] += 1
                bus.emit(run_id, type_, agent, **line)
                if type_ == "tool.result" and line.get("flag"):
                    totals["flags"] += 1
                    bus.emit(run_id, "data.flag", agent, label=line["flag"], source=line.get("tool"),
                             detail=str(line.get("preview") or "")[:200])
                if type_ in ("llm.finished", "tool.result", "agent.finished"):
                    sync()
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
            proc.stdout.close()
    code = proc.wait()
    sync()
    if finished is None:
        raise RuntimeError(failure or f"Vibe-Trading exited with code {code} before finishing; see vibe_trading.log in the run folder")
    rating, decision = parse_decision(finished.get("content") or "")
    vt_status = str(finished.get("status") or "")
    if rating is None and vt_status in ("failed", "cancelled", "error", "timeout"):
        # The framework itself did not finish (a worker failed or timed out): a failed run, not a finished one without a
        # rating. Its flags and vibe_trading.log say which agent stopped and why.
        raise RuntimeError(f"Vibe-Trading's {run.get('variant') or 'committee'} ended with status '{vt_status}' before a decision; "
                           "see the run's flags and vibe_trading.log")
    decision["iterations"] = finished.get("iterations")
    decision["vt_status"] = finished.get("status")
    decision["mode"] = run.get("variant") or "committee"
    if finished.get("swarm_run_id"):
        decision["swarm_run_id"] = finished["swarm_run_id"]
    bus.emit(run_id, "agent.started", "decision", visit=1)
    bus.emit(run_id, "decision.structured", "decision", rating=rating, **decision)
    lines = [f"**Rating**: {rating or 'none'} ({decision['rating_how']})"]
    lines += [f"**{k.title()}**: {decision[k]}" for k in ("action", "entry", "stop", "target", "horizon", "confidence", "thesis")
              if decision.get(k) not in (None, "")]
    bus.emit(run_id, "report.updated", "decision", text="\n\n".join(lines))
    bus.emit(run_id, "agent.finished", "decision", duration=0)
    if rating is None:
        totals["flags"] += 1
        bus.emit(run_id, "data.flag", "decision", label="No rating", source="Vibe-Trading",
                 detail="The answer had no JSON block with a rating or an action.")
    omitted = len(re.findall(r"\(omitted", finished.get("content") or ""))
    if omitted:
        decision["numbers_omitted"] = omitted
        totals["flags"] += 1
        bus.emit(run_id, "data.flag", None, label="Numbers withheld", source="Vibe-Trading",
                 detail=f"Vibe-Trading's own grounding check replaced {omitted} figure(s) it could not match to this session's tool data with (omitted).")
    store.update_run(run_id, status="finished", finished_at=time.time(), rating=rating, decision=decision,
                     models_served=sorted(served), flags=totals["flags"])
    bus.emit(run_id, "run.finished", None, rating=rating, decision=decision, **totals)


def run_dir_for(run_id: str) -> Path:
    return RUNS_DIR / run_id
