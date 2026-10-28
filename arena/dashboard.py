"""The arena dashboard, built from a run's recorded files: one 1920x1080 page, the size of the video frame.

    py -3 dashboard.py --run dry-1026b            writes runs/<run>/dashboard.html
    py -3 dashboard.py --run <run> --refresh 15   same, and the page reloads itself every 15 s (for watching live)

Top: one terminal per prompted book, replaying its own event stream (thinking, tool calls, orders with their
reasons, the note it leaves). Bottom left: kept empty for the camera. Bottom right: equity against SPY by round and
the leaderboard. Every number comes from the run folder: snapshots, tools.jsonl, meta.json.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

from snapshot import RUNS

BOOKS = {
    "B1": ("dsh", "DeepSeek", "deepseek-flash", "#60a5fa"),
    "B2": ("dsh", "Haiku", "claude-haiku-5-5", "#f472b6"),
    "B3": ("Claude Code", "DeepSeek", "deepseek-flash", "#34d399"),
    "B4": ("Claude Code", "Haiku", "claude-haiku-5-5", "#fbbf24"),
}
# $ per million tokens. Haiku 5.5 from Anthropic's table; DeepSeek is an estimate until the day's balance settles it.
PRICE = {"claude-haiku-5-5": (0.10, 0.01, 0.125, 0.50), "deepseek-flash": (0.14, 0.0028, 0.14, 0.28)}
START = 100_000.0


def esc(s: str) -> str:
    return html.escape(re.sub(r"\*\*|__|`", "", s))


def short_tool(name: str) -> str:
    return name.replace("mcp__arena__", "")


def call_text(tool: str, inp: dict) -> str:
    if tool == "place_order":
        amt = f"${inp['dollars']:,.0f}" if inp.get("dollars") else ("all" if inp.get("sell_all") else f"{inp.get('qty')} sh")
        return f"place_order {inp.get('side', '')} {str(inp.get('symbol', '')).upper()} {amt}"
    return f"{tool}()"


def result_line(tool: str, text: str) -> tuple[str, str]:
    if tool == "place_order":
        kind = "ok" if text.startswith("ACCEPTED") else "bad"
        return kind, text.split(" (order")[0]
    if tool == "get_snapshot":
        n = len(re.findall(r"^- \d\d-\d\d", text, re.M))
        return "res", f"snapshot: 20 stocks + SPY, {n} headlines, last note read"
    if tool == "get_portfolio":
        return "res", text.splitlines()[0] if text else ""
    return "res", text[:120]


def events(book_dir: Path) -> list[tuple[str, str]]:
    """(kind, text) lines from one book's stream, either harness."""
    out: list[tuple[str, str]] = []
    pending: dict[str, str] = {}
    lines = (book_dir / "stream.jsonl").read_text(encoding="utf-8", errors="replace").splitlines()
    final = ""
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = e.get("type")
        if t == "assistant":                                   # Claude Code
            for c in e["message"].get("content", []):
                if c["type"] == "thinking" and c.get("thinking", "").strip():
                    out.append(("think", c["thinking"]))
                elif c["type"] == "text" and c["text"].strip():
                    out.append(("text", c["text"]))
                elif c["type"] == "tool_use":
                    tool = short_tool(c["name"])
                    pending[c["id"]] = tool
                    out.append(("call", call_text(tool, c.get("input", {}))))
        elif t == "user":
            for c in e["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    raw = c.get("content")
                    if isinstance(raw, list):
                        raw = " ".join(x.get("text", "") for x in raw if isinstance(x, dict))
                    try:
                        raw = json.loads(str(raw)).get("result", raw)
                    except (TypeError, ValueError, AttributeError):
                        pass
                    out.append(result_line(pending.get(str(c.get("tool_use_id")), ""), str(raw)))
        elif t == "result":
            final = e.get("result") or ""
        elif t == "thinking" and e.get("text", "").strip():     # dsh
            out.append(("think", e["text"]))
        elif t == "text" and e.get("text", "").strip():
            out.append(("text", e["text"]))
        elif t == "tool_call":
            tool = short_tool(e["tool"])
            pending[e["callId"]] = tool
            out.append(("call", call_text(tool, e.get("input") or {})))
        elif t == "tool_result":
            out.append(result_line(pending.get(e.get("callId"), ""), str(e.get("result", ""))))
        elif t == "final":
            final = e.get("text") or ""
    if final:
        out = [x for x in out if not (x[0] == "text" and x[1].strip() == final.strip())]
        out.append(("note", final))
    return out


def cost(model: str, meta: dict) -> tuple[float, int]:
    s = meta.get("summary", {})
    u = s.get("usage") or {}
    i, cr, cw, o = (u.get("input_tokens", u.get("inputTokens", 0)), u.get("cache_read_input_tokens", u.get("cacheReadTokens", 0)),
                    u.get("cache_creation_input_tokens", u.get("cacheWriteTokens", 0)), u.get("output_tokens", u.get("outputTokens", 0)))
    p = PRICE[model]
    est = (i * p[0] + cr * p[1] + cw * p[2] + o * p[3]) / 1e6
    if meta.get("harness") == "claude-code" and model.startswith("claude") and s.get("cost_usd") is not None:
        est = s["cost_usd"]
    return est, i + cr + cw + o


def ledger(run_dir: Path, rounds: list[Path]) -> dict:
    """Replay accepted orders round by round; mark each book at every round's snapshot prices."""
    books = {b: {"cash": START, "qty": {}, "curve": [], "trades": 0, "rejected": 0, "cost": 0.0, "tokens": 0} for b in BOOKS}
    spy, times = [], []
    for rd in rounds:
        snap = json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))
        px = {r["ticker"]: r["last"] for r in snap["rows"] if r["last"]}
        times.append(snap["time_et"][-5:])
        spy.append(px["SPY"])
        for b, st in books.items():
            tools = rd / b / "tools.jsonl"
            fills_f = rd / b / "fills.json"
            fills = {f.get("client_order_id"): f for f in json.loads(fills_f.read_text(encoding="utf-8"))} if fills_f.exists() else {}
            for line in tools.read_text(encoding="utf-8").splitlines() if tools.exists() else []:
                c = json.loads(line)
                if c["tool"] != "place_order":
                    continue
                if c.get("verdict") != "accepted":
                    st["rejected"] += 1
                    continue
                r = c["broker"]["response"]
                f = fills.get(r.get("client_order_id"), r)          # live: Alpaca's own fill; dry: the dry broker's
                o, s = c["order"], c["order"]["symbol"]
                if f.get("filled_avg_price") and float(f.get("filled_qty") or 0) > 0:
                    q, p = float(f["filled_qty"]), float(f["filled_avg_price"])
                else:                                               # not filled yet: count it at the snapshot price
                    p = px.get(s, 0.0)
                    q = (o["dollars"] / p if p else 0.0) if o["side"] == "buy" else float(o.get("qty") or 0)
                sign = 1 if o["side"] == "buy" else -1
                st["qty"][s] = st["qty"].get(s, 0.0) + sign * q
                st["cash"] -= sign * q * p
                st["trades"] += 1
            meta = rd / b / "meta.json"
            if meta.exists():
                m = json.loads(meta.read_text(encoding="utf-8"))
                c_, t_ = cost(BOOKS[b][2], m)
                st["cost"] += c_
                st["tokens"] += t_
            eq = st["cash"] + sum(q * px.get(s, 0) for s, q in st["qty"].items())
            st["curve"].append(eq)
            st["weights"] = {s: q * px.get(s, 0) / eq for s, q in st["qty"].items() if q > 1e-9}
    return {"books": books, "spy": [START * x / spy[0] for x in spy], "times": times}


def chart(L: dict) -> str:
    w, h, pad = 700, 330, 44
    left = 92
    series = [(b, BOOKS[b][3], L["books"][b]["curve"]) for b in BOOKS] + [("SPY", "#9ca3af", L["spy"])]
    vals = [v for _, _, c in series for v in c] + [START]
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 200.0)
    lo, hi = lo - span * 0.15, hi + span * 0.15
    n = max(len(L["times"]), 2)

    def xy(i: int, v: float) -> tuple[float, float]:
        return left + i * (w - left - pad) / (n - 1), h - pad - (v - lo) * (h - 2 * pad) / (hi - lo)

    parts = [f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">']
    for k in range(5):
        v = lo + k * (hi - lo) / 4
        _, y = xy(0, v)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - pad}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 8}" y="{y + 4:.1f}" class="ax" text-anchor="end">${v:,.0f}</text>')
    for i, t in enumerate(L["times"]):
        x, _ = xy(i, lo)
        parts.append(f'<text x="{x:.1f}" y="{h - pad + 18}" class="ax" text-anchor="middle">R{i + 1} {t}</text>')
    for name, col, c in series:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (xy(i, v) for i, v in enumerate(c)))
        dash = ' stroke-dasharray="6 5"' if name == "SPY" else ""
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="3"{dash}/>')
        x, y = xy(len(c) - 1, c[-1])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{col}"/>')
    parts.append("</svg>")
    return "".join(parts)


def terminal(b: str, run_dir: Path, rounds: list[Path]) -> str:
    harness, model_label, model, col = BOOKS[b]
    rows = []
    for k, rd in enumerate(rounds, 1):
        if not (rd / b / "stream.jsonl").exists():
            continue
        snap = json.loads((rd / "snapshot.json").read_text(encoding="utf-8"))
        rows.append(f'<div class="sep">round {k} &middot; {snap["time_et"][-5:]} New York</div>')
        for kind, text in events(rd / b):
            if kind == "think":
                rows.append(f'<div class="think">&middot; {esc(text[:260])}{"..." if len(text) > 260 else ""}</div>')
            elif kind == "call":
                rows.append(f'<div class="call">&rsaquo; {esc(text)}</div>')
            elif kind in ("ok", "bad"):
                rows.append(f'<div class="{kind}">{esc(text)}</div>')
            elif kind == "res":
                rows.append(f'<div class="res">{esc(text)}</div>')
            elif kind == "text":
                rows.append(f'<div class="txt">{esc(text[:220])}</div>')
            elif kind == "note":
                rows.append(f'<div class="note"><b>note</b> {esc(text[:420])}{"..." if len(text) > 420 else ""}</div>')
    return (f'<section class="term"><header><i style="background:{col}"></i><span>{b}</span> {harness} + {model_label}'
            f'<em>{model}</em></header><div class="feed"><div class="scroll">{"".join(rows)}</div></div></section>')


def build(run: str, refresh: int | None) -> Path:
    run_dir = RUNS / run
    rounds = sorted(p for p in run_dir.glob("round_*") if (p / "snapshot.json").exists())
    L = ledger(run_dir, rounds)
    last = json.loads((rounds[-1] / "snapshot.json").read_text(encoding="utf-8"))
    spy_row = next(r for r in last["rows"] if r["ticker"] == "SPY")
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8")) if (run_dir / "run.json").exists() else {}
    board = []
    ranked = sorted(BOOKS, key=lambda b: -L["books"][b]["curve"][-1])
    for pos, b in enumerate(ranked, 1):
        st = L["books"][b]
        eq = st["curve"][-1]
        ret = round(100 * (eq / START - 1), 2) + 0.0                 # + 0.0 turns -0.0 into 0.0
        vs = round(ret - 100 * (L["spy"][-1] / START - 1), 2) + 0.0
        top = ", ".join(f"{s} {100 * w:.0f}%" for s, w in sorted(st["weights"].items(), key=lambda x: -x[1])[:4])
        rej = f" / {st['rejected']} rej" if st["rejected"] else ""
        board.append(f'<tr><td class="pos">{pos}</td><td><i style="background:{BOOKS[b][3]}"></i>{b} {BOOKS[b][0]} + {BOOKS[b][1]}'
                     f'<div class="hold">{esc(top) or "cash"}</div></td><td>${eq:,.0f}</td>'
                     f'<td class="{"up" if ret >= 0 else "dn"}">{ret:+.2f}%</td><td class="{"up" if vs >= 0 else "dn"}">{vs:+.2f}</td>'
                     f'<td>{st["trades"]}<span class="rej">{rej}</span></td>'
                     f'<td>{"&asymp;" if BOOKS[b][2] == "deepseek-flash" else ""}${st["cost"]:.3f}</td></tr>')
    mode = "dry test" if meta.get("mode", "dry") == "dry" else "live paper"
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Harness Arena</title>
{f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ''}
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#070b12;--panel:#0e1521;--line:#1c2738;--txt:#e6ebf2;--dim:#6b7a90;--cyan:#38bdf8;--ok:#22c55e;--bad:#f87171}}
html,body{{margin:0;height:100%;background:#000;overflow:hidden}}
#stage{{position:absolute;left:0;top:0;width:1920px;height:1080px;background:var(--bg);color:var(--txt);font:16px Inter,sans-serif;transform-origin:0 0}}
.top{{position:absolute;left:28px;right:28px;top:18px;height:52px;display:flex;align-items:center;gap:28px}}
.brand{{font-weight:800;letter-spacing:.14em;font-size:22px}} .brand b{{color:var(--cyan)}}
.pill{{border:1px solid var(--line);border-radius:999px;padding:7px 16px;color:var(--dim);font-size:15px}}
.pill strong{{color:var(--txt)}} .grow{{flex:1}}
.terms{{position:absolute;left:28px;right:28px;top:84px;height:560px;display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}
.term{{background:var(--panel);border:1px solid var(--line);border-radius:14px;display:flex;flex-direction:column;overflow:hidden}}
.term header{{padding:12px 16px;border-bottom:1px solid var(--line);font-weight:600;font-size:16px;display:flex;align-items:center;gap:8px}}
.term header i,.board i{{width:10px;height:10px;border-radius:50%;display:inline-block}}
.term header span{{color:var(--dim)}} .term header em{{margin-left:auto;font:400 12px 'JetBrains Mono',monospace;color:var(--dim);font-style:normal}}
.feed{{flex:1;overflow:hidden;display:flex;flex-direction:column;justify-content:flex-end;padding:8px 14px 12px}}
.scroll{{font:12.5px/1.5 'JetBrains Mono',monospace}}
.scroll div{{margin:2px 0;word-break:break-word}}
.sep{{color:var(--dim);border-top:1px dashed var(--line);padding-top:6px;margin-top:8px!important}}
.think{{color:#7d8aa3;font-style:italic}} .call{{color:var(--cyan)}} .res{{color:#94a3b8}}
.ok{{color:var(--ok)}} .bad{{color:var(--bad)}} .txt{{color:#cbd5e1}}
.note{{color:var(--txt);background:#121c2c;border-left:3px solid var(--cyan);padding:6px 8px;border-radius:4px}}
.cam{{position:absolute;left:28px;top:664px;width:540px;height:388px;border:1px dashed #243146;border-radius:14px;color:#2c3a50;display:flex;align-items:center;justify-content:center;font-size:14px;letter-spacing:.2em}}
.chart{{position:absolute;left:588px;top:664px;width:720px;height:388px;background:var(--panel);border:1px solid var(--line);border-radius:14px}}
.chart h3,.board h3{{margin:14px 18px 0;font-size:14px;letter-spacing:.12em;color:var(--dim);font-weight:600}}
.grid{{stroke:#1c2738}} .ax{{fill:#6b7a90;font:12px 'JetBrains Mono',monospace}}
.board{{position:absolute;left:1328px;top:664px;width:564px;height:388px;background:var(--panel);border:1px solid var(--line);border-radius:14px}}
.board table{{width:100%;border-collapse:collapse;margin-top:2px;font-size:15px}}
.board th{{color:var(--dim);font-weight:400;font-size:12px;text-align:left;padding:6px 10px}}
.board td{{padding:7px 10px;border-top:1px solid var(--line);vertical-align:top}} .board td i{{margin-right:7px}}
.pos{{color:var(--dim)}} .up{{color:var(--ok)}} .dn{{color:var(--bad)}} .rej{{color:var(--bad);font-size:12px}}
.hold{{color:var(--dim);font:11.5px 'JetBrains Mono',monospace;margin-top:3px}}
.legend{{position:absolute;right:18px;top:12px;font-size:12px;color:var(--dim)}} .legend span{{margin-left:12px}}
</style></head><body><div id="stage">
<div class="top"><div class="brand">HARNESS <b>ARENA</b></div>
<div class="pill">{mode} &middot; <strong>{esc(run)}</strong></div>
<div class="pill">round <strong>{len(rounds)}</strong> of 13 &middot; <strong>{last["time_et"][-5:]}</strong> New York</div>
<div class="grow"></div>
<div class="pill">SPY <strong class="{"up" if (spy_row["chg_prev_pct"] or 0) >= 0 else "dn"}">{(spy_row["chg_prev_pct"] or 0):+.2f}%</strong> today</div>
<div class="pill">4 agents &middot; same prompt &middot; same tools &middot; $100,000 each</div></div>
<div class="terms">{"".join(terminal(b, run_dir, rounds) for b in BOOKS)}</div>
<div class="cam">CAMERA</div>
<div class="chart"><h3>EQUITY BY ROUND</h3><div class="legend">{"".join(f'<span style="color:{BOOKS[b][3]}">&#9679; {b}</span>' for b in BOOKS)}<span>- - SPY</span></div>{chart(L)}</div>
<div class="board"><h3>LEADERBOARD</h3><table><tr><th></th><th>book</th><th>equity</th><th>return</th><th>vs SPY</th><th>trades</th><th>cost</th></tr>{"".join(board)}</table></div>
</div><script>
function fit(){{const s=Math.min(innerWidth/1920,innerHeight/1080);const st=document.getElementById('stage');st.style.transform='scale('+s+')';st.style.left=((innerWidth-1920*s)/2)+'px';st.style.top=((innerHeight-1080*s)/2)+'px'}}
addEventListener('resize',fit);fit();
</script></body></html>"""
    out = run_dir / "dashboard.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--run", required=True)
    ap.add_argument("--refresh", type=int)
    a = ap.parse_args()
    print(build(a.run, a.refresh))


if __name__ == "__main__":
    main()
