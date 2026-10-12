"""The README banner, as HTML rendered headless to PNG: the frameworks on the left, Glassbench in the middle, what
it gives on the right.

    pip install playwright && playwright install chromium
    python assets/banner-src/make_banners.py [out_dir]

banner_a.png (2000x800) is assets/banner.png. banner_b.png (2000x1100, the glass bench render in the middle) is an
alternative layout, rendered only when GLASSBENCH_HERO points at the render. Fonts load from Google Fonts:
Schibsted Grotesk, JetBrains Mono, Instrument Serif (the website's). Change a chip in LEFT or RIGHT and rerun.
"""
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
HERO_FILE = Path(os.environ["GLASSBENCH_HERO"]) if os.environ.get("GLASSBENCH_HERO") else None
HERO = HERO_FILE.as_uri() if HERO_FILE and HERO_FILE.exists() else None
LOGO = (REPO / "assets" / "logo.png").as_uri()

ICON = {
    "committee": '<circle cx="12" cy="5.5" r="2.8"/><circle cx="5" cy="17.5" r="2.8"/><circle cx="19" cy="17.5" r="2.8"/><path d="M10.4 7.9 L6.5 15 M13.6 7.9 L17.5 15 M7.8 17.5 H16.2"/>',
    "fund": '<path d="M3 20.5 H21"/><path d="M6 17 V12 M10.5 17 V7 M15 17 V10 M19.5 17 V4.5"/>',
    "wave": '<path d="M2 13 C4.5 5, 7 5, 9 12 C11 19, 13.5 19, 16 12 C17.5 7.5, 19.5 6.5, 22 8"/>',
    "code": '<path d="M8 6.5 L3 12 L8 17.5 M16 6.5 L21 12 L16 17.5 M13.6 4.5 L10.4 19.5"/>',
    "window": '<rect x="2.8" y="4" width="18.4" height="16" rx="2.2"/><path d="M2.8 8.8 H21.2"/><circle cx="6" cy="6.4" r="0.6"/><circle cx="8.6" cy="6.4" r="0.6"/>',
    "gauge": '<circle cx="12" cy="13.5" r="8"/><path d="M12 13.5 L16.2 9.3"/><path d="M9.5 2.8 H14.5 M12 2.8 V5.5"/>',
    "rewind": '<path d="M4.2 9.5 A8.5 8.5 0 1 1 3.6 13.8"/><path d="M3.2 4.8 V9.8 H8.2"/><path d="M12 8 V12.5 L15.2 14.5"/>',
    "plug": '<path d="M9 2.8 V7 M15 2.8 V7"/><path d="M6.3 7 H17.7 V10.8 A5.7 5.7 0 0 1 6.3 10.8 Z"/><path d="M12 16.5 V21.2"/>',
}
LEFT = [("committee", "TradingAgents", "v0.6.0, connected", True), ("fund", "AI Hedge Fund", "v2.5.0, connected", True),
        ("wave", "Vibe Trading", "connected", True), ("code", "Your own system", "write one adapter", False)]
RIGHT = [("window", "Front end", "live committee, replay"), ("gauge", "Benchmark", "models and frameworks"),
         ("rewind", "Backtesting", "replay any period"), ("plug", "Broker connection", "IBKR paper trading")]

FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Schibsted+Grotesk:wght@400;500;600;700;800'
         '&family=JetBrains+Mono:wght@400;500;600&family=Instrument+Serif:ital@1&display=swap" rel="stylesheet">')
BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:transparent}
:root{--ink:#eef1f8;--muted:#a3abc0;--dim:#6f7891;--accent:#9fb0ff;--wire:#6f86ff;--gold:#e9a85c;
  --sans:'Schibsted Grotesk',sans-serif;--mono:'JetBrains Mono',monospace;--serif:'Instrument Serif',serif}
.banner{position:relative;width:2000px;overflow:hidden;border-radius:30px;background:#05070c;color:var(--ink);font-family:var(--sans)}
.tile{background:#fff;display:flex;align-items:center;justify-content:center;flex:0 0 auto}
.tile img{display:block}
.kicker{position:absolute;font-family:var(--mono);font-weight:500;letter-spacing:.42em;color:#c4c9d6}
.word{position:absolute;font-weight:700;letter-spacing:-.035em;line-height:1}
.tag{position:absolute;font-weight:500;color:#e3e7f0;line-height:1.22}
.tag i{font-family:var(--serif);font-style:italic;font-weight:400;color:var(--accent);letter-spacing:0}
.tested{position:absolute}
.tested .k{font-family:var(--mono);font-size:22px;letter-spacing:.42em;color:#a6adbd;margin-bottom:26px}
.tested .row{display:flex;align-items:stretch;gap:48px}
.tested .sep{width:1.5px;background:#343a4a}
.tested .n{font-weight:600;letter-spacing:-.02em;line-height:1}
.tested .v{margin-top:14px;font-size:26px;color:#a9b0c0}
.tested .v b{font-family:var(--mono);font-weight:500;color:#dde2ec;margin-right:10px}
.chip{position:absolute;display:flex;align-items:center;gap:16px;padding:0 20px;border-radius:14px;
  background:linear-gradient(180deg,rgba(26,32,52,.92),rgba(16,20,34,.92));border:1.5px solid rgba(150,170,255,.20);
  box-shadow:0 0 0 1px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.45)}
.chip.dim{border-style:dashed;border-color:rgba(150,170,255,.28);background:rgba(14,18,30,.75)}
.chip svg{flex:0 0 auto;fill:none;stroke:#c8d2ff;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
.chip .t{font-weight:600;letter-spacing:-.01em;color:#f1f3f9;white-space:nowrap;line-height:1.1}
.chip .s{font-family:var(--mono);color:#8f98b0;margin-top:5px;white-space:nowrap}
.chip.dim .t{color:#cfd5e4}
.colhead{position:absolute;font-family:var(--mono);font-size:17px;letter-spacing:.3em;color:#7f88a1}
svg.wires{position:absolute;left:0;top:0;overflow:visible}
.stars{position:absolute;inset:0}
"""


def stars(w: int, h: int, n: int, seed: int, avoid=None) -> str:
    out, s = [], seed
    for _ in range(n):
        s = (s * 1103515245 + 12345) % 2**31
        x = s % w
        s = (s * 1103515245 + 12345) % 2**31
        y = s % h
        s = (s * 1103515245 + 12345) % 2**31
        r = 0.6 + (s % 100) / 100 * 1.1
        o = 0.15 + (s % 37) / 37 * 0.45
        if avoid and avoid(x, y):
            continue
        out.append(f'<circle cx="{x}" cy="{y}" r="{r:.2f}" fill="#cfd8ff" opacity="{o:.2f}"/>')
    return f'<svg class="stars" width="{w}" height="{h}">{"".join(out)}</svg>'


def chip(x, y, w, h, icon, name, sub, solid=True, name_px=27, sub_px=15, icon_px=34) -> str:
    return (f'<div class="chip{"" if solid else " dim"}" style="left:{x}px;top:{y}px;width:{w}px;height:{h}px">'
            f'<svg width="{icon_px}" height="{icon_px}" viewBox="0 0 24 24">{ICON[icon]}</svg>'
            f'<div><div class="t" style="font-size:{name_px}px">{name}</div><div class="s" style="font-size:{sub_px}px">{sub}</div></div></div>')


def wire(x0, y0, x1, y1, dashed=False) -> str:
    mx = (x0 + x1) / 2
    d = f"M {x0} {y0} C {mx} {y0}, {mx} {y1}, {x1} {y1}"
    dash = ' stroke-dasharray="7 8"' if dashed else ""
    return (f'<path d="{d}" fill="none" stroke="#6f86ff" stroke-width="7" opacity=".16" filter="url(#glow)"{dash}/>'
            f'<path d="{d}" fill="none" stroke="#8d9fff" stroke-width="2.2" opacity="{.55 if dashed else .9}"{dash}/>')


def node(x, y, r=7) -> str:
    return (f'<circle cx="{x}" cy="{y}" r="{r + 6}" fill="#6f86ff" opacity=".18"/>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="#05070c" stroke="#a9b7ff" stroke-width="2.4"/>')


def tested(x, y, name_px=46) -> str:
    return (f'<div class="tested" style="left:{x}px;top:{y}px"><div class="k">TESTED WITH</div><div class="row">'
            f'<div><div class="n" style="font-size:{name_px}px">TradingAgents</div><div class="v"><b>v0.6.0</b>Tauric Research</div></div>'
            f'<div class="sep"></div>'
            f'<div><div class="n" style="font-size:{name_px}px">AI Hedge Fund</div><div class="v"><b>v2.5.0</b>virattt</div></div></div></div>')


GLOW = '<defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4"/></filter></defs>'


# ------------------------------------------------------------------ A: the current layout, the diagram on the right
def banner_a() -> str:
    W, H = 2000, 800
    cw, rw, chh, gap = 282, 302, 92, 26             # chips: left width, right width
    top = 150
    lx, rx = 846, 1648                              # left and right chip columns
    cx0, cx1, cy0, cy1 = 1248, 1508, 168, 640       # the platform card
    ys = [top + i * (chh + gap) + chh / 2 for i in range(4)]
    jin, jout = (cx0, (cy0 + cy1) / 2), (cx1, (cy0 + cy1) / 2)
    wires = "".join(wire(lx + cw, y, *jin, dashed=not LEFT[i][3]) for i, y in enumerate(ys))
    wires += "".join(wire(*jout, rx, y) for y in ys)
    wires += node(*jin) + node(*jout)
    chips = "".join(chip(lx, y - chh / 2, cw, chh, ic, n, s, solid, name_px=24, sub_px=14) for (ic, n, s, solid), y in zip(LEFT, ys))
    chips += "".join(chip(rx, y - chh / 2, rw, chh, ic, n, s, name_px=24, sub_px=14) for (ic, n, s), y in zip(RIGHT, ys))
    card = f"""
<div style="position:absolute;left:{cx0}px;top:{cy0}px;width:{cx1 - cx0}px;height:{cy1 - cy0}px;border-radius:20px;
  background:linear-gradient(160deg,rgba(40,52,92,.55),rgba(14,18,32,.85) 55%);border:1.5px solid rgba(170,190,255,.35);
  box-shadow:0 0 60px rgba(90,110,255,.18),inset 0 1px 0 rgba(255,255,255,.12);display:flex;flex-direction:column;align-items:center;padding-top:46px">
  <div class="tile" style="width:84px;height:84px;border-radius:20px"><img src="{LOGO}" style="width:64px;height:64px"></div>
  <div style="margin-top:22px;font-weight:700;font-size:40px;letter-spacing:-.03em">Glassbench</div>
  <div style="margin-top:8px;font-family:var(--mono);font-size:15px;letter-spacing:.24em;color:#8f98b0">THE PLATFORM</div>
  <div style="margin-top:34px;width:206px;font-family:var(--mono);font-size:16px;line-height:1.75;color:#c7cee0">
    <div><span style="color:#6f7891">01</span>&nbsp; one adapter each</div>
    <div><span style="color:#6f7891">02</span>&nbsp; every call logged</div>
    <div><span style="color:#6f7891">03</span>&nbsp; one runs database</div>
  </div>
</div>"""
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>{BASE_CSS}</style></head><body>
<div class="banner" style="height:{H}px;background:radial-gradient(1100px 700px at 72% 40%,#0f1630 0%,#070a14 55%,#04060b 100%)">
  {stars(W, H, 260, 11, avoid=lambda x, y: x < 820)}
  <div class="tile" style="position:absolute;left:88px;top:62px;width:58px;height:58px;border-radius:14px"><img src="{LOGO}" style="width:44px;height:44px"></div>
  <div class="kicker" style="left:96px;top:160px;font-size:25px">OPEN SOURCE · APACHE 2.0</div>
  <div class="word" style="left:90px;top:220px;font-size:124px">Glassbench</div>
  <div class="tag" style="left:96px;top:380px;width:720px;font-size:36px">Connect and benchmark finance agent systems in one platform, then <i>trade on them.</i></div>
  {tested(96, 548, 42)}
  <div class="colhead" style="left:{lx + 4}px;top:104px">FRAMEWORKS</div>
  <div class="colhead" style="left:{rx + 4}px;top:104px">WHAT YOU GET</div>
  <svg class="wires" width="{W}" height="{H}">{GLOW}{wires}</svg>
  {card}
  {chips}
</div></body></html>"""


# ------------------------------------------------------------------ B: the glass bench in the middle as the platform
def banner_b() -> str:
    W, H = 2000, 1100
    s, ox, oy = 0.62, -466, 190                     # v5.png (3168 x 1344) scaled and placed: the glass centred at x 1000
    P = lambda x, y: (x * s + ox, y * s + oy)       # a point of v5.png on the banner
    ins = [P(1965, 414), P(1965, 531), P(1965, 642), P(1965, 759)]   # the four input nodes drawn on the glass
    out = P(2612, 570)                                                # the output node on the glass
    cw, chh, gap = 372, 96, 30
    lx, rx = 70, 2000 - 70 - cw
    top = 372
    ys = [top + i * (chh + gap) + chh / 2 for i in range(4)]
    wires = "".join(wire(lx + cw, y, ix - 26, iy, dashed=not LEFT[i][3]) for i, (y, (ix, iy)) in enumerate(zip(ys, ins)))
    wires += "".join(wire(out[0] + 40, out[1], rx, y) for y in ys)
    wires += "".join(node(ix - 26, iy, 6) for ix, iy in ins) + node(out[0] + 40, out[1], 6)
    chips = "".join(chip(lx, y - chh / 2, cw, chh, ic, n, s_, solid, name_px=30, sub_px=16, icon_px=38) for (ic, n, s_, solid), y in zip(LEFT, ys))
    chips += "".join(chip(rx, y - chh / 2, cw, chh, ic, n, s_, name_px=30, sub_px=16, icon_px=38) for (ic, n, s_), y in zip(RIGHT, ys))
    img_w = 3168 * s
    return f"""<!doctype html><html><head><meta charset="utf-8">{FONTS}<style>{BASE_CSS}</style></head><body>
<div class="banner" style="height:{H}px;background:#05070c">
  <img src="{HERO}" style="position:absolute;left:{ox}px;top:{oy}px;width:{img_w}px;
    -webkit-mask-image:linear-gradient(90deg,transparent 0,#000 18%,#000 82%,transparent 100%),linear-gradient(180deg,transparent 0,#000 12%,#000 88%,transparent 100%);
    -webkit-mask-composite:source-in;mask-composite:intersect">
  {stars(W, H, 140, 5, avoid=lambda x, y: 560 < x < 1440 and y > 280)}
  <div style="position:absolute;left:0;top:44px;width:{W}px;display:flex;flex-direction:column;align-items:center">
    <div style="display:flex;align-items:center;gap:28px"><div class="tile" style="width:66px;height:66px;border-radius:16px"><img src="{LOGO}" style="width:50px;height:50px"></div>
      <div style="font-weight:700;font-size:112px;letter-spacing:-.035em;line-height:1">Glassbench</div></div>
    <div class="tag" style="position:static;margin-top:22px;font-size:38px;text-align:center">Connect and benchmark finance agent systems in one platform, then <i>trade on them.</i></div>
    <div class="kicker" style="position:static;margin-top:20px;font-size:19px">OPEN SOURCE · APACHE 2.0</div>
  </div>
  <div class="colhead" style="left:{lx + 4}px;top:{top - 46}px">FRAMEWORKS</div>
  <div class="colhead" style="left:{rx + 4}px;top:{top - 46}px">WHAT YOU GET</div>
  <svg class="wires" width="{W}" height="{H}">{GLOW}{wires}</svg>
  {chips}
  <div style="position:absolute;left:0;top:938px;width:{W}px;display:flex;justify-content:center">{tested(0, 0, 40).replace('class="tested" style="left:0px;top:0px"', 'class="tested" style="position:static"')}</div>
</div></body></html>"""


def main():
    pages = {"banner_a": (banner_a(), 800)}
    if HERO:
        pages["banner_b"] = (banner_b(), 1100)
    tmp = Path(tempfile.mkdtemp(prefix="glassbench-banner-"))   # the pages carry local file paths: never in the repo
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        for name, (html, h) in pages.items():
            src = tmp / f"{name}.html"
            src.write_text(html, encoding="utf-8")
            pg = b.new_page(viewport={"width": 2000, "height": h}, device_scale_factor=1)
            pg.goto(src.as_uri())
            pg.wait_for_load_state("networkidle")
            pg.evaluate("document.fonts.ready")
            pg.wait_for_timeout(400)
            pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True, clip={"x": 0, "y": 0, "width": 2000, "height": h})
            print(OUT / f"{name}.png")
        b.close()


if __name__ == "__main__":
    main()
