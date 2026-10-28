"""Run one round for some prompted books and record everything the video needs.

    py -3 run_round.py --run <run_id> --round N --books B1,B2,B3,B4 --mode dry [--now-et HH:MM]

Freezes the round snapshot once, then starts every book's harness at the same moment, each with a 5-minute limit.
Saved per book in runs/<run>/round_NN/<book>/:
    stream.jsonl   the harness's own event stream, untouched
    stderr.log     its diagnostics
    tools.jsonl    every tool call and its result, written by the MCP server
    meta.json      command and env names (no keys), model, start, seconds, exit code, tokens and cost when reported
    note.md        the agent's final message, which it reads at the start of the next round
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import harnesses
from snapshot import RUNS, freeze

HERE = Path(__file__).resolve().parent
LIMIT_S = 300


def versions() -> dict:
    out = {}
    for name, cmd in {"claude-code": [str(harnesses.CLAUDE_EXE), "--version"], "dsh": [str(harnesses.DSH_CMD), "--version"]}.items():
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception as e:
            out[name] = f"unknown ({e.__class__.__name__})"
    return out


def claude_summary(stream: Path) -> dict:
    res = {}
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("type") == "result":
            res = {"note": e.get("result") or "", "cost_usd": e.get("total_cost_usd"), "usage": e.get("usage"),
                   "turns": e.get("num_turns"), "is_error": e.get("is_error"), "subtype": e.get("subtype")}
    return res


def dsh_summary(stream: Path) -> dict:
    """dsh --json events: session, status (usage on each step_end), thinking, tool_call, tool_result, text, final."""
    note, usage, kinds, thinking = "", {}, {}, 0
    for line in stream.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        k = str(e.get("type", "?"))
        kinds[k] = kinds.get(k, 0) + 1
        if k == "final":
            note = e.get("text") or ""
        elif k == "thinking":
            thinking += len(e.get("text") or "")
        elif k == "status" and e.get("phase") == "step_end":
            for n, v in (e.get("usage") or {}).items():
                usage[n] = usage.get(n, 0) + v
    return {"note": note, "usage": usage, "thinking_chars": thinking, "event_types": kinds}


def keep_dsh_session(book: str, since: float, out: Path) -> dict:
    """Copy dsh's own session log (requests, system prompt, model) beside the round's files; return the served model."""
    import glob
    import re
    import shutil

    import zstandard

    pattern = str(harnesses.WORKSPACE / "dsh-home" / "sessions" / f"*{book}*" / "*" / "session.v4.jsonl.zstd")
    files = [f for f in glob.glob(pattern) if Path(f).stat().st_mtime >= since]
    if not files:
        return {}
    f = max(files, key=lambda p: Path(p).stat().st_mtime)
    shutil.copy2(f, out / "dsh_session.jsonl.zstd")
    raw = zstandard.ZstdDecompressor().stream_reader(open(f, "rb")).read().decode("utf-8", "replace")
    return {"dsh_session": Path(f).parent.name,
            "served_models": sorted(set(re.findall(r'"model"\s*:\s*"([^"]+)"', raw))),
            "providers": sorted(set(re.findall(r'"provider"\s*:\s*"([^"]+)"', raw)))}


def run_book(book: str, args: argparse.Namespace, rd: Path, start_at: float, results: dict) -> None:
    out = rd / book
    L = harnesses.launch(book, args.run, args.round, args.mode, out, args.now_et)
    task = (HERE / "prompt.md").read_text(encoding="utf-8")
    meta = {**L.record(), "run": args.run, "round": args.round, "mode": args.mode,
            "prompt_sha256": hashlib.sha256(task.encode()).hexdigest(), "limit_s": LIMIT_S}
    while time.time() < start_at:
        time.sleep(0.05)
    t0 = time.time()
    meta["start_utc"] = datetime.now(timezone.utc).isoformat()
    with (out / "stream.jsonl").open("wb") as so, (out / "stderr.log").open("wb") as se:
        p = subprocess.Popen(L.argv, stdin=subprocess.PIPE, stdout=so, stderr=se, cwd=L.cwd, env=L.env)
        assert p.stdin is not None
        p.stdin.write(task.encode("utf-8"))
        p.stdin.close()
        try:
            code = p.wait(timeout=LIMIT_S)
            meta["timed_out"] = False
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
            code = p.wait()
            meta["timed_out"] = True
    meta["seconds"] = round(time.time() - t0, 1)
    meta["exit_code"] = code
    if args.mode == "live":                       # real fill prices arrive after the order; keep Alpaca's own record
        try:
            from broker import Broker

            time.sleep(3)
            fills = Broker(book).api.get("/orders", params={"status": "all", "after": meta["start_utc"], "limit": 100,
                                                            "direction": "asc"}).json()
            (out / "fills.json").write_text(json.dumps(fills, indent=1), encoding="utf-8")
        except Exception as e:
            meta["fills_error"] = e.__class__.__name__
    s = claude_summary(out / "stream.jsonl") if L.harness == "claude-code" else dsh_summary(out / "stream.jsonl")
    (out / "note.md").write_text(s.pop("note", "") or "", encoding="utf-8")
    if L.harness == "dsh":
        s |= keep_dsh_session(book, t0 - 1, out)
    else:
        for line in (out / "stream.jsonl").read_text(encoding="utf-8", errors="replace").splitlines():
            if '"subtype":"init"' in line.replace(" ", ""):
                init = json.loads(line)
                s |= {"served_models": [init.get("model")], "tools_seen": init.get("tools")}
                break
    meta["summary"] = s
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    results[book] = meta


def play_round(run: str, rnd: int, books: list[str], mode: str, now_et: str | None = None, rounds: int = 13) -> list[str]:
    """Freeze the snapshot, run every book at the same moment, return one summary line per book."""
    args = argparse.Namespace(run=run, round=rnd, mode=mode, now_et=now_et)
    run_file = RUNS / run / "run.json"
    if not run_file.exists():
        run_file.parent.mkdir(parents=True, exist_ok=True)
        run_file.write_text(json.dumps({"run": run, "mode": mode, "created_utc": datetime.now(timezone.utc).isoformat(),
                                        "versions": versions(), "books": {b: harnesses.BOOKS[b] for b in books}}, indent=1), encoding="utf-8")
    rd = freeze(run, rnd, rounds)
    results: dict = {}
    start_at = time.time() + 2
    threads = [threading.Thread(target=run_book, args=(b, args, rd, start_at, results)) for b in books]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return summarize(rd, books, results)


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--books", default="B1,B2,B3,B4")
    ap.add_argument("--mode", choices=["dry", "live"], default="dry")
    ap.add_argument("--now-et")
    a = ap.parse_args()
    for line in play_round(a.run, a.round, [b.strip() for b in a.books.split(",") if b.strip()], a.mode, a.now_et):
        print(line)


def summarize(rd: Path, books: list[str], results: dict) -> list[str]:
    lines = [f"round {rd.name[-2:]}  {rd}"]
    for b in books:
        m = results.get(b, {})
        tools = rd / b / "tools.jsonl"
        calls = [json.loads(x) for x in tools.read_text(encoding="utf-8").splitlines()] if tools.exists() else []
        orders = [c for c in calls if c["tool"] == "place_order"]
        acc = sum(c.get("verdict") == "accepted" for c in orders)
        s = m.get("summary", {})
        u = s.get("usage") or {}
        tin = u.get("input_tokens", u.get("inputTokens", 0)) + u.get("cache_read_input_tokens", u.get("cacheReadTokens", 0))
        tout = u.get("output_tokens", u.get("outputTokens", 0))
        cost = f"${s['cost_usd']:.4f}" if m.get("model") == harnesses.HAIKU and s.get("cost_usd") is not None else "from balance"
        err = (rd / b / "stderr.log").read_text(encoding="utf-8", errors="replace") if (rd / b / "stderr.log").exists() else ""
        note = rd / b / "note.md"
        lines.append(f"  {b} {m.get('harness', '?'):<11} {m.get('model', '?'):<17} exit {m.get('exit_code')} {m.get('seconds')}s"
                     f"{' TIMEOUT' if m.get('timed_out') else ''} | tool calls {sum(c['tool'] != 'server_start' for c in calls)},"
                     f" orders {acc} ok / {len(orders) - acc} rejected | tokens {tin:,} in {tout:,} out | {cost}"
                     f" | note {len(note.read_text(encoding='utf-8')) if note.exists() else 0} chars"
                     f"{' | STDERR HAS Error' if 'Error' in err else ''}")
    return lines


if __name__ == "__main__":
    main()
