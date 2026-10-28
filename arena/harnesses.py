"""How each prompted book's harness starts for one round: command line, environment, working folder, task on stdin.

    B1  dsh 0.2 headless + deepseek-flash          B3  Claude Code --bare + deepseek-flash (DeepSeek's Anthropic API)
    B2  dsh 0.2 headless + claude-haiku-5-5        B4  Claude Code --bare + claude-haiku-5-5

Both harnesses get the same task (prompt.md) and only the arena's three MCP tools: Claude Code through --tools "" and
--strict-mcp-config, dsh through a patch that switches every built-in tool off. Each runs in an empty folder outside
this repository. The child environment starts from this process's, minus every CLAUDE*, ANTHROPIC*, DSH_*, MCP_*,
DEEPSEEK* and OPENAI* name, so no setting or token of the session that launches it leaks in. Keys come from
env_keys.obter into the child's environment only; launch records keep the variable names, never the values.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Agents work in WORKSPACE/<book>, empty folders outside this repository. The two harness executables are found on
# PATH unless ARENA_CLAUDE_EXE / ARENA_DSH_CMD name them.
WORKSPACE = Path(os.environ.get("ARENA_WORKSPACE") or Path.home() / "arena-workspace")
CLAUDE_EXE = Path(os.environ.get("ARENA_CLAUDE_EXE") or shutil.which("claude") or "claude")
DSH_CMD = Path(os.environ.get("ARENA_DSH_CMD") or shutil.which("dsh") or "dsh")
HAIKU, DEEPSEEK = "claude-haiku-5-5", "deepseek-flash"
DEEPSEEK_ANTHROPIC_URL = "https://api.deepseek.com/anthropic"
BOOKS = {"B1": ("dsh", DEEPSEEK), "B2": ("dsh", HAIKU), "B3": ("claude", DEEPSEEK), "B4": ("claude", HAIKU)}
TOOLS = ["get_snapshot", "get_portfolio", "place_order"]
MAX_USD_PER_ROUND = "0.25"
# Claude Code prices an unknown model as a Claude one, about 40x DeepSeek's real rate, so its cap for B3 is set
# from that inflated estimate. The real DeepSeek spend comes from tokens and the account balance.
MAX_USD_DEEPSEEK_ESTIMATE = "5.00"
DSH_TOOLS_OFF = ["tool-bash", "tool-pwsh", "tool-jobs", "tool-fs", "tool-fs-search", "tool-skill", "tool-subagent-control",
                 "tool-subagent-list-agents", "tool-subagent", "tool-subagent-fork", "tool-workflow", "tool-todo",
                 "tool-goal", "tool-ralph", "tool-web"]
STRIP = ("CLAUDE", "ANTHROPIC", "DSH_", "MCP_", "DEEPSEEK", "OPENAI")


@dataclass
class Launch:
    book: str
    harness: str
    model: str
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    env_names_added: list[str]

    def record(self) -> dict:
        return {"book": self.book, "harness": self.harness, "model": self.model, "argv": self.argv,
                "cwd": str(self.cwd), "env_added": self.env_names_added}


def mcp_args(run: str, book: str, rnd: int, mode: str, now_et: str | None) -> list[str]:
    a = ["-3", str(HERE / "arena_mcp.py"), "--run", run, "--book", book, "--round", str(rnd), "--mode", mode]
    return a + (["--now-et", now_et] if now_et else [])


def base_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(STRIP)}


def _keys(**names: str) -> dict[str, str]:
    import env_keys

    return {var: env_keys.obter(src) for var, src in names.items()}


def claude(book: str, model: str, run: str, rnd: int, mode: str, out: Path, now_et: str | None) -> Launch:
    cfg = {"mcpServers": {"arena": {"type": "stdio", "command": "py", "args": mcp_args(run, book, rnd, mode, now_et)}}}
    (out / "mcp.json").write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    env = base_env()
    added = {"CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1"}
    if model == DEEPSEEK:
        added |= {"ANTHROPIC_BASE_URL": DEEPSEEK_ANTHROPIC_URL, "ANTHROPIC_DEFAULT_HAIKU_MODEL": DEEPSEEK,
                  "ANTHROPIC_SMALL_FAST_MODEL": DEEPSEEK}
        added |= _keys(ANTHROPIC_API_KEY="DEEPSEEK_API_KEY")
    else:
        added |= _keys(ANTHROPIC_API_KEY="ANTHROPIC_API_KEY")
    env |= added
    argv = [str(CLAUDE_EXE), "-p", "--bare", "--model", model, "--tools", "",
            "--strict-mcp-config", "--mcp-config", str(out / "mcp.json"),
            "--allowedTools", ",".join(f"mcp__arena__{t}" for t in TOOLS),
            "--permission-mode", "dontAsk", "--max-budget-usd", MAX_USD_PER_ROUND if model == HAIKU else MAX_USD_DEEPSEEK_ESTIMATE,
            "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
    return Launch(book, "claude-code", model, argv, env, WORKSPACE / book, sorted(added))


def dsh_patch(book: str, model: str, run: str, rnd: int, mode: str, now_et: str | None) -> str:
    args = ", ".join(f"'{a.replace(chr(92), '/')}'" for a in mcp_args(run, book, rnd, mode, now_et))
    lines = [
        f"# Harness Arena {book}: dsh headless + {model}. Only the arena's three MCP tools; every built-in tool is off.",
        "- insert:",
        "    - id: arena-mcp",
        "      name: '@deepseek-ai/dsh-mcp-client'",
        "      config:",
        "        serverName: arena",
        "        transport: stdio",
        "        command: 'py'",
        f"        args: [{args}]",
        f"        cwd: '{HERE.as_posix()}'",
        "        toolCallTimeoutMs: 60000",
        "        failOnStartupError: true",
    ]
    for t in DSH_TOOLS_OFF:
        lines += [f"- id: {t}", "  disabled: true"]
    # No built-in tool is left that could write, run or fetch, so the only calls to approve are the arena's own.
    # Read-only sandbox with no prompts is declared as a preset: the permission plugin refuses a combination that
    # matches none. Never danger-full-access, which also removes the file boundary.
    lines += ["- id: approval", "  config:", "    policy: never",
              "- id: sandbox-policy", "  config:", "    mode: read-only", f"    workspaceRoot: '{(WORKSPACE / book).as_posix()}'",
              "- id: permission", "  config:", "    defaultPreset: arena", "    presets:", "      arena:",
              "        sandbox: read-only", "        approval: never", "        name: arena",
              "        description: 'Harness Arena: only the arena MCP tools, no prompts.'"]
    if model == HAIKU:
        # pi-ai's catalog in dsh 0.2.0-rc.2 stops at Haiku 4.5, so Haiku 5.5 is declared here. Its compat matches the
        # catalog's own entries for the current Claude models: adaptive thinking only, no temperature field.
        lines += ["- id: llm-pi-ai", "  config:", "    providers:", "      anthropic:", "        apiKeyEnv: ANTHROPIC_API_KEY",
                  "        models:", f"          - id: {HAIKU}", "            name: Claude Haiku 5.5",
                  "            contextWindow: 1000000", "            maxTokens: 64000", "            input: [text, image]",
                  "            compat:", "              forceAdaptiveThinking: true", "              supportsTemperature: false",
                  "              supportsStrictTools: true",
                  "- id: agent-default-model", "  config:", "    provider: anthropic", f"    model: {HAIKU}"]
    return "\n".join(lines) + "\n"


def dsh(book: str, model: str, run: str, rnd: int, mode: str, out: Path, now_et: str | None) -> Launch:
    patch = out / "arena.cordis.yml"
    patch.write_text(dsh_patch(book, model, run, rnd, mode, now_et), encoding="utf-8")
    env = base_env()
    added = {"DSH_HOME": str(WORKSPACE / "dsh-home")}
    added |= _keys(DEEPSEEK_API_KEY="DEEPSEEK_API_KEY")
    if model == HAIKU:
        added |= _keys(ANTHROPIC_API_KEY="ANTHROPIC_API_KEY")
    env |= added
    argv = [str(DSH_CMD), "--profile", "headless", "--patch", str(patch), "--json", "-"]
    return Launch(book, "dsh", model, argv, env, WORKSPACE / book, sorted(added))


def launch(book: str, run: str, rnd: int, mode: str, out: Path, now_et: str | None = None) -> Launch:
    harness, model = BOOKS[book]
    (WORKSPACE / book).mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    return (claude if harness == "claude" else dsh)(book, model, run, rnd, mode, out, now_et)
