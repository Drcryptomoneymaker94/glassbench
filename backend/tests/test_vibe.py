"""Vibe-Trading engine: reading the closing decision, the child environment, the driver's tool allowlist and tap, and
importing sessions run in Vibe-Trading's own app."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from deskapp import events, vibe, vibe_import
from deskapp.events import EventBus
from deskapp.store import Store

DRIVER = Path(__file__).resolve().parents[1] / "drivers" / "vt_driver.py"


def _driver():
    spec = importlib.util.spec_from_file_location("vt_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParseDecision(unittest.TestCase):
    def test_stated_rating_and_levels(self):
        text = 'Analysis...\n```json\n{"rating": "overweight", "action": "long", "entry": "$212.50", "stop": 198, ' \
               '"target": "1,240", "horizon": "3 months", "confidence": 65, "thesis": "x"}\n```'
        rating, d = vibe.parse_decision(text)
        self.assertEqual(rating, "Overweight")
        self.assertEqual((d["entry"], d["stop"], d["target"], d["confidence"]), (212.5, 198.0, 1240.0, 65.0))
        self.assertEqual(d["rating_how"], "stated")

    def test_grounding_redaction_reads_as_null(self):
        # From a real run: Vibe-Trading's grounding guard blanks unmatched figures, also as bare JSON values.
        text = '```json\n{\n  "rating": "Overweight",\n  "entry": 216,\n  "target": (omitted※),\n' \
               '  "thesis": "margin of (omitted※) and a 13.7x multiple"\n}\n```'
        rating, d = vibe.parse_decision(text)
        self.assertEqual((rating, d["entry"], d["target"]), ("Overweight", 216.0, None))
        self.assertIn("(omitted※)", d["thesis"])

    def test_action_mapped_when_rating_missing(self):
        rating, d = vibe.parse_decision('```json\n{"action": "short"}\n```')
        self.assertEqual((rating, d["rating_how"]), ("Underweight", "mapped from action"))

    def test_last_valid_block_wins_and_none_without_block(self):
        text = '```json\n{"rating": "Sell"}\n```\nrevised:\n```json\n{"rating": "Hold"}\n```\n```json\n{broken\n```'
        self.assertEqual(vibe.parse_decision(text)[0], "Hold")
        self.assertEqual(vibe.parse_decision("no block at all"), (None, vibe.parse_decision("")[1]))


class ChildEnv(unittest.TestCase):
    def test_only_the_needed_key_and_never_openai(self):
        env = {"DEEPSEEK_API_KEY": "d", "OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a", "PATH": "p"}
        with mock.patch.dict(os.environ, env, clear=True):
            child = vibe._child_env({"DEEPSEEK_API_KEY"})
        self.assertEqual(child.get("DEEPSEEK_API_KEY"), "d")
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn("ANTHROPIC_API_KEY", child)
        self.assertEqual(child["PATH"], "p")


class FakeTool:
    def __init__(self, name):
        self.name = name

    def execute(self, **params):
        return json.dumps({"status": "ok", "tool": self.name, "params": params})


class FakeRegistry:
    def __init__(self, names):
        self._tools = {n: FakeTool(n) for n in names}

    def execute(self, name, params):
        return self._tools[name].execute(**params)


class DriverTap(unittest.TestCase):
    def test_allowlist_and_tap_survive_a_registry_copy(self):
        driver = _driver()
        registry = FakeRegistry(["get_market_data", "bash", "write_file", "trading_place_order", "backtest", "web_search"])
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(io.StringIO()) as out:
            kept = driver.restrict_and_tap(registry, Path(tmp))
            copy = FakeRegistry([])
            copy._tools = dict(registry._tools)   # what AgentLoop's DeferredToolRegistry does
            copy.execute("get_market_data", {"symbol": "NVDA"})
            files = os.listdir(Path(tmp) / "tool_outputs")
        self.assertEqual(kept, ["get_market_data", "web_search"])
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual([e["type"] for e in events], ["tool.called", "tool.result"])
        self.assertEqual(events[1]["file"], "tool_outputs/001_vibe_get_market_data.txt")
        self.assertEqual(files, ["001_vibe_get_market_data.txt"])


DECISION = '```json\n{"rating": "Hold", "action": "wait", "entry": null, "stop": 180, "target": 230, "horizon": "3 months", "confidence": 55, "thesis": "t"}\n```'


def _fake_home(root: Path) -> Path:
    home = root / "vt_home"
    session = home / "sessions" / "s1"
    session.mkdir(parents=True)
    trace = [
        {"type": "start", "prompt": "Should I buy NVDA here?", "ts": 1793000000.0},
        {"type": "tool_call", "tool": "search_symbol", "call_id": "c1", "args": "{'query': 'NVDA'}", "ts": 1793000001.0},
        {"type": "identity_state", "identity": "{'status': 'locked', 'authorized_symbols': ['NVDA.US']}", "ts": 1793000002.0},
        {"type": "tool_result", "tool": "search_symbol", "call_id": "c1", "status": "ok", "result": "{\"ok\": true}", "ts": 1793000003.0},
        {"type": "answer_rejected", "issues": "[numeric_claim_conflict]", "ts": 1793000010.0},
        {"type": "answer", "content": "Analysis.\n" + DECISION, "ts": 1793000020.0},
        {"type": "end", "status": "success", "ts": 1793000021.0},
    ]
    (session / "trace.jsonl").write_text("\n".join(json.dumps(r) for r in trace), encoding="utf-8")
    vt_run = home / "runs" / "r1"
    vt_run.mkdir(parents=True)
    (vt_run / "req.json").write_text(json.dumps({"prompt": "x", "context": {"session_id": "s1"}}), encoding="utf-8")
    (vt_run / "llm_usage.json").write_text(json.dumps({"model": "deepseek-v4-flash", "provider": "deepseek", "per_iteration": [
        {"input_tokens": 1000, "output_tokens": 100, "cache_read_tokens": 800}, {"input_tokens": 2000, "output_tokens": 200}]}),
        encoding="utf-8")
    swarm = home / "swarm" / "runs" / "w1"
    swarm.mkdir(parents=True)
    (swarm / "run.json").write_text(json.dumps({
        "id": "w1", "preset_name": "investment_committee", "user_vars": {"target": "AAPL", "market": "US"}, "status": "completed",
        "created_at": "2026-10-28T10:00:00+00:00", "completed_at": "2026-10-28T10:20:00+00:00", "model": "deepseek-v4-flash",
        "provider": "deepseek", "total_input_tokens": 5000, "total_output_tokens": 500,
        "agents": [{"id": a} for a in ("bull_advocate", "bear_advocate", "risk_officer", "portfolio_manager")],
        "tasks": [{"agent_id": "bull_advocate", "summary": "bull", "status": "completed"},
                  {"agent_id": "portfolio_manager", "summary": "PM.\n" + DECISION, "status": "completed"}]}), encoding="utf-8")
    (swarm / "events.jsonl").write_text(json.dumps({"type": "tool_call", "agent_id": "bull_advocate", "timestamp": "2026-10-28T10:01:00+00:00",
                                                    "data": {"tool": "get_market_data", "call_id": "x"}}), encoding="utf-8")
    return home


class Importer(unittest.TestCase):
    def test_list_and_import_a_session_and_a_swarm_run_once(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            home, runs_dir = _fake_home(root), root / "runs"
            with mock.patch.object(events, "RUNS_DIR", runs_dir):
                store = Store(root / "desk.db")
                manager = types.SimpleNamespace(store=store, bus=EventBus(store))
                listed = vibe_import.list_sessions(store, home)["sessions"]
                self.assertEqual(sorted(i["key"] for i in listed), ["session:s1", "swarm:w1"])

                run_id = vibe_import.import_session(manager, "s1", home)
                run = store.get_run(run_id)
                self.assertEqual((run["ticker"], run["purpose"], run["variant"], run["rating"]), ("NVDA", "imported", "imported", "Hold"))
                self.assertEqual((run["tokens_in"], run["tokens_out"], run["llm_calls"], run["tool_calls"]), (3000, 300, 2, 1))
                self.assertEqual(run["trade_date"], "2026-10-26")
                with self.assertRaises(ValueError):
                    vibe_import.import_session(manager, "s1", home)   # once only
                with self.assertRaises(ValueError):
                    vibe_import.import_session(manager, "../s1", home)   # never outside the home folder

                swarm_id = vibe_import.import_swarm(manager, "w1", home)
                swarm = store.get_run(swarm_id)
                self.assertEqual((swarm["ticker"], swarm["rating"], swarm["tool_calls"]), ("AAPL", "Hold", 1))
                again = {i["key"]: i["imported_run"] for i in vibe_import.list_sessions(store, home)["sessions"]}
                self.assertEqual(again, {"session:s1": run_id, "swarm:w1": swarm_id})
                store._conn.close()


if __name__ == "__main__":
    unittest.main()
