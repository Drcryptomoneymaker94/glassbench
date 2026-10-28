"""Import sessions run in Vibe-Trading's own app (its CLI, web UI or desktop app) into the runs database.

Glassbench reads what Vibe-Trading already writes and runs nothing: a single-agent session's trace
(<home>/sessions/<id>/trace.jsonl) with its token usage (<home>/runs/<run>/llm_usage.json), or a swarm run
(<home>/swarm/runs/<id>/run.json with events.jsonl). Each becomes a Vibe-Trading run with purpose "imported" and
variant "imported", replayed on its original timestamps. Imported runs are the real product with any prompt, any tools
and any date, so they are labelled as such and kept apart from controlled runs; the rating is read from a closing JSON
block when the answer has one, and is missing otherwise.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .settings import VT_ENGINE, estimate_cost, vt_version
from . import vibe

PREVIEW_CHARS = 700


def vt_home() -> Path:
    """Vibe-Trading's runtime root: GLASSBENCH_VT_HOME, else VIBE_TRADING_HOME, else ~/.vibe-trading."""
    for name in ("GLASSBENCH_VT_HOME", "VIBE_TRADING_HOME"):
        if os.environ.get(name):
            return Path(os.environ[name]).expanduser().resolve()
    return Path.home() / ".vibe-trading"


def _records(path: Path) -> list[dict]:
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return out


def _ts(value, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return fallback


def _ticker(text: str, records: list[dict]) -> str:
    """The symbol Vibe-Trading locked for the session, else the first symbol argument, else a ticker-shaped word."""
    for r in records:
        m = re.search(r"authorized_symbols['\"]?:\s*\[['\"]([A-Z0-9.\-^=]+)", str(r.get("identity") or ""))
        if m:
            return m.group(1).split(".")[0]
    for r in records:
        if r.get("type") == "tool_call":
            m = re.search(r"['\"](?:symbol|code|ticker|query)['\"]:\s*['\"]([A-Za-z0-9.\-^=]{1,15})['\"]", str(r.get("args") or ""))
            if m:
                return m.group(1).upper().split(".")[0]
    m = re.search(r"\b[A-Z]{1,5}\b", text or "")
    return m.group(0) if m else "UNKNOWN"


def _imported(store) -> dict[str, str]:
    """source key -> Glassbench run id, for sessions already in the database."""
    out = {}
    for run in store.list_runs(100_000):
        if run.get("engine") == VT_ENGINE and run.get("variant") == "imported":
            source = (run.get("decision") or {}).get("import_source") or {}
            if source.get("key"):
                out[source["key"]] = run["id"]
    return out


def list_sessions(store, home: Path | None = None) -> dict:
    home = home or vt_home()
    done = _imported(store)
    items = []
    for trace in sorted(home.glob("sessions/*/trace.jsonl")):
        recs = _records(trace)
        start = next((r for r in recs if r.get("type") == "start"), {})
        end = next((r for r in reversed(recs) if r.get("type") == "end"), {})
        key = f"session:{trace.parent.name}"
        items.append({"kind": "session", "id": trace.parent.name, "key": key, "prompt": str(start.get("prompt") or "")[:240],
                      "started": _ts(start.get("ts"), trace.stat().st_mtime), "status": end.get("status"),
                      "tool_calls": sum(1 for r in recs if r.get("type") == "tool_call"),
                      "answered": any(r.get("type") == "answer" for r in recs), "imported_run": done.get(key)})
    for run_json in sorted(home.glob("swarm/runs/*/run.json")):
        try:
            run = json.loads(run_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        key = f"swarm:{run.get('id') or run_json.parent.name}"
        items.append({"kind": "swarm", "id": run.get("id") or run_json.parent.name, "key": key,
                      "prompt": f"{run.get('preset_name')}: {json.dumps(run.get('user_vars') or {}, ensure_ascii=False)}"[:240],
                      "started": _ts(run.get("created_at"), run_json.stat().st_mtime), "status": run.get("status"),
                      "tool_calls": None, "answered": bool(run.get("final_report")), "imported_run": done.get(key)})
    items.sort(key=lambda i: i["started"], reverse=True)
    return {"home": str(home), "exists": home.exists(), "sessions": items}


def _usage_for_session(home: Path, session_id: str) -> dict:
    """llm_usage.json of the Vibe-Trading run that belongs to this session (req.json names the session)."""
    for req in home.glob("runs/*/req.json"):
        try:
            if session_id in req.read_text(encoding="utf-8"):
                return json.loads((req.parent / "llm_usage.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _new_run(manager, ticker: str, trade_date: str, model: str, provider: str, layout: dict, created: float) -> str:
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + ticker.replace("/", "_").upper() + "-" + uuid.uuid4().hex[:4]
    manager.store.create_run({
        "id": run_id, "ticker": ticker.upper(), "trade_date": trade_date, "analysts": ["vibe"], "depth": 0,
        "deep_model": model, "quick_model": model, "status": "queued", "created_at": created, "engine": VT_ENGINE,
        "engine_version": vt_version(), "provider": provider, "purpose": "imported", "backtest_id": None, "memory": "off",
        "variant": "imported",
    })
    manager.bus.emit(run_id, "run.queued", None, at=created, ticker=ticker.upper(), trade_date=trade_date, analysts=["vibe"],
                     depth=0, deep_model=model, quick_model=model, purpose="imported", backtest_id=None, memory="off",
                     variant="imported", provider=provider, engine=VT_ENGINE, agents=[a["id"] for a in layout["agents"]],
                     agent_meta=layout["agents"], stages=layout["stages"])
    manager.store.update_run(run_id, status="running", started_at=created)
    manager.bus.emit(run_id, "run.started", None, at=created, ticker=ticker.upper(), trade_date=trade_date)
    return run_id


def _finish(manager, run_id: str, answer: str, totals: dict, source: dict, served: list[str], ended: float, lead: str | None) -> str:
    bus, store = manager.bus, manager.store
    rating, decision = vibe.parse_decision(answer)
    decision["import_source"] = source
    decision["mode"] = "imported"
    bus.emit(run_id, "agent.started", "decision", at=ended, visit=1)
    bus.emit(run_id, "decision.structured", "decision", at=ended, rating=rating, **decision)
    bus.emit(run_id, "report.updated", "decision", at=ended,
             text=f"**Rating**: {rating or 'none'} ({decision['rating_how']})\n\nImported from Vibe-Trading ({source['kind']} {source['id']}).")
    bus.emit(run_id, "agent.finished", "decision", at=ended, duration=0)
    totals["flags"] += 1
    bus.emit(run_id, "data.flag", lead, at=ended, label="Imported", source="Vibe-Trading",
             detail="Run in Vibe-Trading's own app with its own prompt, tools and date, then imported. Not a controlled Glassbench run.")
    store.update_run(run_id, status="finished", finished_at=ended, rating=rating, decision=decision, models_served=served,
                     tokens_in=totals["tokens_in"], tokens_out=totals["tokens_out"], cost_usd=round(totals["cost_usd"], 6),
                     llm_calls=totals["llm_calls"], tool_calls=totals["tool_calls"], flags=totals["flags"])
    bus.emit(run_id, "run.finished", None, at=ended, rating=rating, decision=decision, **totals)
    return run_id


def import_session(manager, session_id: str, home: Path | None = None) -> str:
    home = home or vt_home()
    session_dir = (home / "sessions" / session_id).resolve()
    if session_dir.parent != (home / "sessions").resolve() or not (session_dir / "trace.jsonl").exists():
        raise ValueError(f"No Vibe-Trading session {session_id!r} under {home}")
    key = f"session:{session_id}"
    if key in _imported(manager.store):
        raise ValueError("This session is already in the database.")
    recs = _records(session_dir / "trace.jsonl")
    start = next((r for r in recs if r.get("type") == "start"), {})
    t0 = _ts(start.get("ts"), time.time())
    usage = _usage_for_session(home, session_id)
    model = usage.get("model") or "unknown"
    provider = str(usage.get("provider") or "unknown").lower()
    answer = next((str(r.get("content") or "") for r in reversed(recs) if r.get("type") == "answer"), "")
    trade_date = datetime.fromtimestamp(t0, tz=timezone.utc).date().isoformat()
    layout = vibe.LAYOUTS["single"]
    run_id = _new_run(manager, _ticker(str(start.get("prompt") or ""), recs), trade_date, model, provider, layout, t0)
    bus, agent = manager.bus, "vibe"
    totals = {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "llm_calls": 0, "tool_calls": 0, "flags": 0}
    bus.emit(run_id, "agent.started", agent, at=t0, visit=1)
    calls = {}
    for r in recs:
        kind, at = r.get("type"), _ts(r.get("ts"), t0)
        if kind == "tool_call":
            calls[r.get("call_id")] = at
            totals["tool_calls"] += 1
            bus.emit(run_id, "tool.called", agent, at=at, call=r.get("call_id"), tool=r.get("tool"), args=str(r.get("args") or "")[:2000])
        elif kind == "tool_result":
            text = str(r.get("result") or r.get("preview") or "")
            bus.emit(run_id, "tool.result", agent, at=at, call=r.get("call_id"), tool=r.get("tool"),
                     duration=round(at - calls.get(r.get("call_id"), at), 3), chars=len(text), preview=text[:PREVIEW_CHARS],
                     flag=None if str(r.get("status")) == "ok" else f"tool {r.get('status')}")
        elif kind == "answer_rejected":
            totals["flags"] += 1
            bus.emit(run_id, "data.flag", agent, at=at, label="Answer rejected by its grounding check", source="Vibe-Trading",
                     detail=str(r.get("issues") or "")[:300])
    for i, it in enumerate(usage.get("per_iteration") or []):
        tin, tout = int(it.get("input_tokens") or 0), int(it.get("output_tokens") or 0)
        cost = estimate_cost(model, tin, tout)
        totals["llm_calls"] += 1
        totals["tokens_in"] += tin
        totals["tokens_out"] += tout
        totals["cost_usd"] += cost or 0.0
        bus.emit(run_id, "llm.started", agent, at=t0, call=f"iter-{i + 1}", model=model, prompt_chars=0)
        bus.emit(run_id, "llm.finished", agent, at=t0, call=f"iter-{i + 1}", model=model, served_model=None, tokens_in=tin,
                 tokens_out=tout, reasoning=int(it.get("reasoning_tokens") or 0), cached=int(it.get("cache_read_tokens") or 0),
                 cost_usd=cost, duration=0)
    end = next((r for r in reversed(recs) if r.get("type") == "end"), {})
    ended = _ts(end.get("ts"), t0)
    bus.emit(run_id, "report.updated", agent, at=ended, text=answer)
    bus.emit(run_id, "agent.finished", agent, at=ended, duration=round(ended - t0, 3))
    source = {"kind": "session", "id": session_id, "key": key, "home": str(home), "prompt": str(start.get("prompt") or "")[:2000]}
    return _finish(manager, run_id, answer, totals, source, [model] if model != "unknown" else [], ended, agent)


def import_swarm(manager, swarm_id: str, home: Path | None = None) -> str:
    home = home or vt_home()
    run_dir = (home / "swarm" / "runs" / swarm_id).resolve()
    if run_dir.parent != (home / "swarm" / "runs").resolve() or not (run_dir / "run.json").exists():
        raise ValueError(f"No Vibe-Trading swarm run {swarm_id!r} under {home}")
    key = f"swarm:{swarm_id}"
    if key in _imported(manager.store):
        raise ValueError("This swarm run is already in the database.")
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    t0 = _ts(run.get("created_at"), time.time())
    ended = _ts(run.get("completed_at"), t0)
    model = str(run.get("model") or "unknown")
    provider = str(run.get("provider") or "unknown").lower()
    target = str((run.get("user_vars") or {}).get("target") or "UNKNOWN").split(".")[0]
    committee = run.get("preset_name") == "investment_committee"
    agent_ids = [a.get("id") for a in run.get("agents") or []]
    layout = vibe.LAYOUTS["committee"] if committee else {
        "stages": [{"id": "research", "label": run.get("preset_name") or "Swarm"}, {"id": "decision", "label": "Decision"}],
        "agents": [{"id": a, "label": a.replace("_", " ").title(), "name": a, "stage": "research", "role": "quick",
                    "reads": [], "analyst_key": None} for a in agent_ids] + [vibe.DECISION_AGENT]}
    trade_date = datetime.fromtimestamp(t0, tz=timezone.utc).date().isoformat()
    gb_run = _new_run(manager, target, trade_date, model, provider, layout, t0)
    bus = manager.bus
    totals = {"tokens_in": int(run.get("total_input_tokens") or 0), "tokens_out": int(run.get("total_output_tokens") or 0),
              "cost_usd": 0.0, "llm_calls": 0, "tool_calls": 0, "flags": 0}
    totals["cost_usd"] = estimate_cost(model, totals["tokens_in"], totals["tokens_out"]) or 0.0
    for ev in _records(run_dir / "events.jsonl"):
        kind, agent, at, data = ev.get("type"), ev.get("agent_id"), _ts(ev.get("timestamp"), t0), ev.get("data") or {}
        if kind == "worker_started" and agent:
            bus.emit(gb_run, "agent.started", agent, at=at, visit=1)
        elif kind == "tool_call" and agent:
            totals["tool_calls"] += 1
            bus.emit(gb_run, "tool.called", agent, at=at, call=data.get("call_id") or uuid.uuid4().hex, tool=data.get("tool"),
                     args=str(data.get("arguments") or data.get("args") or "")[:2000])
        elif kind == "tool_result" and agent:
            text = str(data.get("preview") or "")
            bus.emit(gb_run, "tool.result", agent, at=at, call=data.get("call_id"), tool=data.get("tool"), chars=len(text),
                     preview=text[:PREVIEW_CHARS], flag=None if str(data.get("status", "ok")) == "ok" else f"tool {data.get('status')}")
    summaries = {}
    for task in run.get("tasks") or []:
        agent, summary = task.get("agent_id"), task.get("summary") or ""
        summaries[agent] = summary
        bus.emit(gb_run, "report.updated", agent, at=ended, text=summary)
        bus.emit(gb_run, "agent.finished", agent, at=ended, duration=0, status=task.get("status"))
    # The committee's decision is the portfolio manager's; another preset's is its final report.
    answer = summaries.get("portfolio_manager") or run.get("final_report") or ""
    source = {"kind": "swarm", "id": swarm_id, "key": key, "home": str(home), "preset": run.get("preset_name"),
              "user_vars": run.get("user_vars")}
    lead = "portfolio_manager" if committee else (agent_ids[-1] if agent_ids else None)
    return _finish(manager, gb_run, answer, totals, source, [model] if model != "unknown" else [], ended, lead)
