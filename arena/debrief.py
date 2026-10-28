"""After the sell-off, every prompted agent grades its own day. Same harness, same model, no tools at all.

    py -3 debrief.py --run <run_id>              writes runs/<run>/debrief/<book>/answer.md (+ stream, stderr, meta)

Each agent gets the same kind of digest of its own day, built from the run folder: every order it placed with the
reason it gave, the rule rejections, its final P&L and SPY's over the same span. It is asked for a grade from A to F,
the one decision it would change, and why. Nothing here can trade: Claude Code runs with --tools "" and no MCP
server, dsh with every built-in tool off and no MCP server mounted.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time
from pathlib import Path

import harnesses
import luck
import report
from snapshot import RUNS

ASK = """The trading session is over. Every position was sold at 15:50 New York time. Below is a factual record of
your own day: each order you placed, with the reason you gave at the time, and the final result.

{digest}

Answer in under 150 words, plainly:
1. A grade from A to F for your own trading today.
2. The one decision you would change, and why.
3. One lesson you would carry into tomorrow."""


def digest(run: str, book: str, L: dict) -> str:
    run_dir = RUNS / run
    lines = []
    for r in report.timeline(run_dir, book):
        lines.append(f"Round {r['round']} ({r['time']} New York):")
        lines += [f"  - {'placed' if o['ok'] else 'rejected by the rules'}: {o['side']} {o['symbol']} {o['amount']}. "
                  f"Your reason: {o['reason']}" for o in r["orders"]] or ["  - no orders (you held)"]
    x = L["books"].get(book, {})
    if x:
        lines.append(f"\nResult: your book {100 * x['replayed_return']:+.3f}% on $100,000 "
                     f"({x['replayed_return'] * 100000:+,.2f} dollars). SPY over the same span {100 * L['spy_return']:+.3f}%.")
    return "\n".join(lines)


def launch(book: str, out: Path) -> tuple[list[str], dict, Path]:
    harness, model = harnesses.BOOKS[book]
    cwd = harnesses.WORKSPACE / book
    cwd.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    if harness == "claude":
        L = harnesses.claude(book, model, "debrief", 0, "dry", out, None)       # for its environment only
        argv = [str(harnesses.CLAUDE_EXE), "-p", "--bare", "--model", model, "--tools", "", "--strict-mcp-config",
                "--permission-mode", "dontAsk", "--max-budget-usd", "0.25" if model == harnesses.HAIKU else "5.00",
                "--no-session-persistence", "--output-format", "stream-json", "--verbose"]
        (out / "mcp.json").unlink(missing_ok=True)
        return argv, L.env, cwd
    patch = harnesses.dsh_patch(book, model, "debrief", 0, "dry", None)
    keep = patch.split("\n- id: ", 1)[1]                                    # drop the MCP insert block, keep the rest
    (out / "debrief.cordis.yml").write_text(f"# Harness Arena {book} debrief: no tools, no MCP server.\n- id: {keep}", encoding="utf-8")
    L = harnesses.dsh(book, model, "debrief", 0, "dry", out, None)
    (out / "arena.cordis.yml").unlink(missing_ok=True)
    argv = [str(harnesses.DSH_CMD), "--profile", "headless", "--patch", str(out / "debrief.cordis.yml"), "--json", "-"]
    return argv, L.env, cwd


def run_one(run: str, book: str, L: dict, results: dict) -> None:
    out = RUNS / run / "debrief" / book
    argv, env, cwd = launch(book, out)
    task = ASK.format(digest=digest(run, book, L))
    (out / "task.md").write_text(task, encoding="utf-8")
    t0 = time.time()
    with (out / "stream.jsonl").open("wb") as so, (out / "stderr.log").open("wb") as se:
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=so, stderr=se, cwd=cwd, env=env)
        assert p.stdin is not None
        p.stdin.write(task.encode("utf-8"))
        p.stdin.close()
        try:
            code = p.wait(timeout=240)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            code = "timeout"
    from run_round import claude_summary, dsh_summary

    s = claude_summary(out / "stream.jsonl") if harnesses.BOOKS[book][0] == "claude" else dsh_summary(out / "stream.jsonl")
    answer = s.pop("note", "") or ""
    (out / "answer.md").write_text(answer, encoding="utf-8")
    (out / "meta.json").write_text(json.dumps({"book": book, "model": harnesses.BOOKS[book][1], "harness": harnesses.BOOKS[book][0],
                                               "exit_code": code, "seconds": round(time.time() - t0, 1), "summary": s}, indent=1),
                                   encoding="utf-8")
    results[book] = answer


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--books", default="B1,B2,B3,B4")
    a = ap.parse_args()
    L = luck.luck(a.run, 1000)
    results: dict = {}
    threads = [threading.Thread(target=run_one, args=(a.run, b, L, results)) for b in a.books.split(",")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for b in a.books.split(","):
        print(f"\n== {b} {report.LABEL[b]}\n{results.get(b, '(no answer)')}")


if __name__ == "__main__":
    main()
