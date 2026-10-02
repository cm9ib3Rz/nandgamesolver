"""The HTML gallery page written by ``render-all``: a summary table plus each level's diagrams."""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape


@dataclass
class Entry:
    slug: str
    heading: str
    group: str
    nands: int
    proven: bool
    lower_bound: int
    game: int | None = None
    note: str = ""
    figures: list[tuple[str, str]] = field(default_factory=list)  # (caption, svg file)


def _status_chip(e: Entry) -> str:
    if e.proven:
        return '<span class="chip ok">Proven minimum</span>'
    return f'<span class="chip warn">Best found · ≥ {e.lower_bound}</span>'


def _target_cell(e: Entry) -> str:
    if e.game is None:
        return '<span class="muted">—</span>'
    mark = "match" if e.nands == e.game else ("beat" if e.nands < e.game else "over")
    label = {"match": "matches", "beat": "beats", "over": "above"}[mark]
    return f'<span class="num">{e.game}</span> <span class="tgt {mark}">{label}</span>'


CSS = """
:root {
  color-scheme: light;
  --ground: #eef1f5; --surface: #ffffff; --ink: #1b2430; --muted: #5d6b7c; --rule: #d5dce5;
  --accent: #1f6feb; --ok-bg: #dcf5e3; --ok-ink: #116329; --warn-bg: #fff1c7; --warn-ink: #7a4d00;
  --sheet: #ffffff; --sheet-edge: #cfd7e1;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --ground: #12161c; --surface: #1a2029; --ink: #dde3ea; --muted: #94a1b2; --rule: #2c3542;
    --accent: #6cb6ff; --ok-bg: #133a22; --ok-ink: #7ee2a0; --warn-bg: #3d2e0a; --warn-ink: #f2c45a;
    --sheet: #ffffff; --sheet-edge: #3a4554;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --ground: #12161c; --surface: #1a2029; --ink: #dde3ea; --muted: #94a1b2; --rule: #2c3542;
  --accent: #6cb6ff; --ok-bg: #133a22; --ok-ink: #7ee2a0; --warn-bg: #3d2e0a; --warn-ink: #f2c45a;
  --sheet: #ffffff; --sheet-edge: #3a4554;
}
body { margin: 0; background: var(--ground); color: var(--ink);
       font: 16px/1.55 "Source Sans 3", "Segoe UI", system-ui, sans-serif; }
.wrap { max-width: 1240px; margin: 0 auto; padding-inline: 20px; padding-block: 36px 64px; display: grid; gap: 40px; }
h1, h2 { font-family: "Barlow Semi Condensed", "Arial Narrow", sans-serif; text-wrap: balance; margin: 0; }
h1 { font-size: clamp(30px, 5vw, 44px); font-weight: 700; letter-spacing: .005em; }
.intro { display: grid; gap: 10px; max-width: 70ch; }
.intro p { margin: 0; color: var(--muted); }
.num { font-family: "JetBrains Mono", ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
a:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 2px; }
.muted { color: var(--muted); }
.chip { display: inline-block; font-size: 12.5px; font-weight: 600; padding: 1px 9px; border-radius: 999px; white-space: nowrap; }
.chip.ok { background: var(--ok-bg); color: var(--ok-ink); }
.chip.warn { background: var(--warn-bg); color: var(--warn-ink); }
.tgt { font-size: 13px; color: var(--muted); }
.tgt.match, .tgt.beat { color: var(--ok-ink); font-weight: 600; }
.tgt.over { color: var(--warn-ink); font-weight: 600; }
.summary { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 560px; font-size: 15px; }
th, td { text-align: left; padding: 9px 14px; border-bottom: 1px solid var(--rule); white-space: nowrap; }
th { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); }
tr:last-child td { border-bottom: 0; }
td.r, th.r { text-align: right; }
td.grp { color: var(--muted); }
section { display: grid; gap: 10px; padding-top: 28px; border-top: 1px solid var(--rule); scroll-margin-top: 16px; }
section header { display: flex; flex-wrap: wrap; align-items: baseline; gap: 4px 14px; }
h2 { font-size: 28px; font-weight: 600; }
.grp { font-size: 14px; color: var(--muted); }
.meta { margin: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; color: var(--muted); }
.meta .big { font-size: 20px; color: var(--ink); }
.note { margin: 0; font-size: 14px; color: var(--warn-ink); }
.figs { display: flex; flex-wrap: wrap; gap: 18px; align-items: flex-start; margin-top: 6px; }
figure { margin: 0; display: grid; gap: 6px; max-width: 100%; }
figcaption { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.sheet { background: var(--sheet); border: 1px solid var(--sheet-edge); border-radius: 8px; padding: 6px;
         overflow-x: auto; max-width: 100%; }
.sheet img { display: block; max-width: none; }
"""

FONTS = ("https://fonts.googleapis.com/css2?family=Barlow+Semi+Condensed:wght@500;600;700"
         "&family=Source+Sans+3:wght@400;600&family=JetBrains+Mono:wght@500&display=swap")


def build_page(entries: list[Entry], svg_dir: str = "svg") -> str:
    rows = "\n".join(
        f'<tr><td><a href="#{e.slug}">{escape(e.heading)}</a></td><td class="grp">{escape(e.group)}</td>'
        f'<td class="num r">{e.nands}</td><td>{_status_chip(e)}</td><td>{_target_cell(e)}</td></tr>'
        for e in entries)

    blocks = []
    for e in entries:
        figs = "".join(
            f'<figure><figcaption>{escape(cap)}</figcaption><div class="sheet"><img src="{svg_dir}/{escape(f)}" '
            f'alt="{escape(e.heading)}: {escape(cap.lower())}" loading="lazy"></div></figure>'
            for cap, f in e.figures)
        game = (f'<span>game target <span class="num">{e.game}</span></span>' if e.game is not None else "")
        note = f'<p class="note">{escape(e.note)}</p>' if e.note else ""
        plural = "" if e.nands == 1 else "s"
        blocks.append(f"""<section id="{e.slug}">
  <header><h2>{escape(e.heading)}</h2><span class="grp">{escape(e.group)}</span></header>
  <p class="meta"><span class="num big">{e.nands}</span> NAND{plural} {_status_chip(e)}{game}</p>
  {note}
  <div class="figs">{figs}</div>
</section>""")

    proven = sum(e.proven for e in entries)
    targets = [e for e in entries if e.game is not None]
    met = sum(e.nands <= e.game for e in targets)
    met_text = (f"All <span class=\"num\">{met}</span> levels with a game target meet it."
                if met == len(targets) else
                f"<span class=\"num\">{met}</span> of <span class=\"num\">{len(targets)}</span> levels with a "
                f"game target meet it.")

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NandGame Solutions</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{FONTS}">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
  <div class="intro">
    <h1>NandGame Solutions</h1>
    <p>Circuits for the combinational levels of <a href="https://nandgame.com/">nandgame.com</a> using as few NAND
       gates as possible, found with a SAT solver. Each level is shown built from the components unlocked by earlier
       levels, and as plain NAND gates.</p>
    <p><span class="num">{proven}</span> of <span class="num">{len(entries)}</span> levels are proven minimal.
       {met_text} Levels that are 16-bit in the game are solved here at 1 or 2 bits.</p>
    <p>Generated by <a href="https://github.com/cm9ib3Rz/nandgamesolver">nandgamesolver</a>.</p>
  </div>

  <div class="summary">
    <table>
      <thead><tr><th>Level</th><th>Group</th><th class="r">NANDs</th><th>Status</th><th>Game target</th></tr></thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>

{chr(10).join(blocks)}
</div>
</body>
</html>
"""
