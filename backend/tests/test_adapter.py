"""Run after every `git pull` of TradingAgents:  ..\\.venv\\Scripts\\python.exe -m unittest discover tests

Fails loudly if the engine renamed a node, a state key or the decision markdown Desk parses.
"""

import unittest

from deskapp import adapter


class AdapterMatchesEngine(unittest.TestCase):
    def test_node_names(self):
        from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
        from tradingagents.graph.setup import DEBATE_PATH_MAP, RISK_ANALYSIS_PATH_MAP

        specs = list(ANALYST_NODE_SPECS.values())
        agents = set(DEBATE_PATH_MAP) | set(RISK_ANALYSIS_PATH_MAP) | {"Trader"} | {s.agent_node for s in specs}
        # Tool and message clearing nodes exist up to 0.5.x only; 0.6.0 runs each analyst as a graph of its own.
        helpers = {getattr(s, "tool_node", None) for s in specs} | {getattr(s, "clear_node", None) for s in specs}
        engine = agents | (helpers - {None})
        self.assertLessEqual(engine, set(adapter.NODE_MAP), "Engine node names changed: update adapter.AGENTS")
        self.assertEqual(agents, {n for n, (_, kind) in adapter.NODE_MAP.items() if kind == "agent"},
                         "Engine agent nodes changed: update adapter.AGENTS")

    def test_calls_inside_an_analyst_graph_resolve_to_the_analyst(self):
        ns = "Market Analyst:7df3|agent:34fb"
        self.assertEqual(adapter.resolve({"langgraph_node": "Market Analyst", "langgraph_checkpoint_ns": "Market Analyst:7df3"}),
                         ("market", "agent"))
        self.assertEqual(adapter.resolve({"langgraph_node": "agent", "langgraph_checkpoint_ns": ns}), ("market", "inner"))
        self.assertEqual(adapter.resolve({"langgraph_node": "tools", "langgraph_checkpoint_ns": "News Analyst:1|tools:2"}),
                         ("news", "tools"))
        self.assertEqual(adapter.speaker({"langgraph_node": "wrap_up", "langgraph_checkpoint_ns": "Fundamentals Analyst:1|wrap_up:2"}),
                         "fundamentals")
        self.assertIsNone(adapter.speaker({"langgraph_node": "tools", "langgraph_checkpoint_ns": "News Analyst:1|tools:2"}))
        self.assertEqual(adapter.resolve({"langgraph_node": "tools_market"}), ("market", "tools"))  # 0.5.x layout
        self.assertIsNone(adapter.resolve({"langgraph_node": "agent", "langgraph_checkpoint_ns": "Something Else:1|agent:2"}))

    def test_analyst_keys(self):
        from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS

        self.assertEqual(set(ANALYST_NODE_SPECS), {a["analyst_key"] for a in adapter.AGENTS if a["stage"] == "analysts"})

    def test_state_keys(self):
        from tradingagents.graph.propagation import Propagator

        state = Propagator().create_initial_state("SPY", "2026-09-13")
        for agent in adapter.AGENTS:
            root = agent["text"][0]
            if root in ("investment_plan", "trader_investment_plan", "final_trade_decision"):
                continue  # written by the engine later, not present in the initial state
            self.assertIn(root, state, f"{agent['id']}: state key '{root}' missing")
            if len(agent["text"]) > 1:
                self.assertIn(agent["text"][1], state[root], f"{agent['id']}: nested key missing")

    def test_decision_markdown(self):
        from tradingagents.agents.schemas import (
            PortfolioDecision, PortfolioRating, ResearchPlan, TraderAction, TraderProposal,
            render_pm_decision, render_research_plan, render_trader_proposal,
        )

        rm = adapter.parse_research_plan(render_research_plan(ResearchPlan(
            recommendation=PortfolioRating.HOLD, rationale="Both sides overreach.", strategic_actions="Keep size.")))
        self.assertEqual(rm["recommendation"], "Hold")
        self.assertEqual(rm["rationale"], "Both sides overreach.")

        tr = adapter.parse_trader_plan(render_trader_proposal(TraderProposal(
            action=TraderAction.HOLD, reasoning="Split tape.", entry_price=766.88, stop_loss=757.5, position_sizing="neutral")))
        self.assertEqual((tr["action"], tr["entry_price"], tr["stop_loss"]), ("Hold", 766.88, 757.5))

        # 0.6.0's research manager writes its fields as bullets (NVDA, 2026-10-09)
        bullets = adapter.parse_research_plan("- **Recommendation**: Overweight\n\n- **Rationale**: The bull's case is stronger.\n\n"
                                              "- **Strategic Actions**:  \n  Build in tranches.")
        self.assertEqual((bullets["recommendation"], bullets["rationale"]), ("Overweight", "The bull's case is stronger."))

        pm = adapter.parse_pm_decision(render_pm_decision(PortfolioDecision(
            rating=PortfolioRating.OVERWEIGHT, executive_summary="Add slowly.", investment_thesis="Trend intact.",
            price_target=230.0, time_horizon="1-3 months")))
        self.assertEqual((pm["rating"], pm["price_target"], pm["time_horizon"]), ("Overweight", 230.0, "1-3 months"))


if __name__ == "__main__":
    unittest.main()
