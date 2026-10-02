"""Command line interface: ``python -m nandsolver ...``."""
from __future__ import annotations

import argparse
import sys
import time
from html import escape
from pathlib import Path

from . import levels
from .cache import DEFAULT_DIR, Cache
from .components import Builder, Library
from .netlist import Netlist
from .diagram import render_svg
from .rewrite import best_rewrite, rewrite
from .spec import Spec


def _library(args) -> Library:
    progress = (lambda msg: print(f"    [{msg}]", file=sys.stderr, flush=True)) if args.verbose else None
    return Library(levels.COMPONENTS, Cache(None if args.no_cache else DEFAULT_DIR), progress)


def _timeout(args) -> float | None:
    return args.timeout if args.timeout and args.timeout > 0 else None


def _time_limit(args) -> float | None:
    return args.time_limit if args.time_limit and args.time_limit > 0 else None


def add_time_opts(sp):
    sp.add_argument("--timeout", type=float, default=20,
                    help="seconds per gate budget before giving up on it (0 = no limit; default 20)")
    sp.add_argument("--time-limit", type=float, default=120,
                    help="seconds for the whole search of one level (0 = no limit; default 120)")


def _report(spec: Spec, lib: Library, args, components: list[str], reference: Netlist | None = None,
            game_nands: int | None = None, title: str | None = None, note: str = "") -> int:
    print(f"{title or spec.name}")
    print(f"  inputs:  {' '.join(spec.inputs)}")
    print(f"  outputs: {' '.join(spec.outputs)}")
    if note:
        print(f"  note:    {note}")
    if args.table:
        print()
        print("\n".join("  " + line for line in spec.format_table().splitlines()))
    print()

    t0 = time.monotonic()
    res = lib.solve(spec, enumerate_limit=args.variants, timeout=_timeout(args),
                    time_limit=_time_limit(args), reference=reference, use_cache=not args.no_cache)
    elapsed = time.monotonic() - t0
    if res.best is None:
        print(f"No circuit found (proven lower bound {res.lower_bound} NANDs; "
              f"timed out at {res.timed_out}). Try a larger --timeout or --time-limit.")
        return 1

    if res.proven:
        status = "proven minimum"
    else:
        status = f"not proven; lower bound {res.lower_bound}"
    label = "Minimum" if res.proven else "Best found"
    line = f"{label}: {res.size} NAND{'' if res.size == 1 else 's'} ({status})"
    if game_nands is not None:
        line += f"   game target: {game_nands}"
    print(line)
    if reference is not None and reference.size > res.size:
        print(f"  (the obvious component design costs {reference.size}; this saves {reference.size - res.size})")
    src = {"cache": "from cache", "reference": "reference design", "sat": f"{elapsed:.1f}s"}[res.source]
    print(f"  [{src}; {len(res.netlists)} optimal variant(s) examined]")
    print()

    rw = best_rewrite(res.netlists, lib, components)
    assert rw.verify(spec, lib)
    used = ", ".join(f"{n} x{c}" for n, c in sorted(rw.counts().items()))
    print(f"Using components ({used}):")
    print(rw.to_text())
    if args.raw or args.show_all:
        print()
        print("Raw NAND netlist:")
        print(rw.netlist.to_text())
    if args.show_all and len(res.netlists) > 1:
        for i, net in enumerate(res.netlists):
            if net is rw.netlist:
                continue
            print(f"\nVariant {i + 1}:")
            print(net.to_text())
    if args.svg:
        subtitle = _subtitle(res, game_nands)
        view = rewrite(rw.netlist, lib, []) if args.svg_raw else rw
        Path(args.svg).write_text(render_svg(view, lib, title or spec.name, subtitle), encoding="utf-8")
        print(f"\nDiagram written to {args.svg}")
    return 0


def _subtitle(res, game_nands=None) -> str:
    parts = [f"{res.size} NAND{'' if res.size == 1 else 's'}",
             "proven minimum" if res.proven else f"best found (lower bound {res.lower_bound})"]
    if game_nands is not None:
        parts.append(f"game target {game_nands}")
    return " · ".join(parts)


def cmd_list(args) -> int:
    lib = _library(args)
    print(f"{'level':22} {'group':22} {'in':>3} {'out':>3} {'game':>5} {'solved':>7}  notes")
    for lv in levels.LEVELS:
        spec = lv.spec()
        cached = lib.cache.load(spec, (), 1)
        solved = str(cached.size) if cached else "-"
        game = str(lv.game_nands) if lv.game_nands is not None else "-"
        notes = []
        if lv.default_width:
            notes.append(f"width {lv.default_width}")
        if lv.component:
            notes.append(f"unlocks {lv.component}")
        if lv.note:
            notes.append(lv.note)
        print(f"{lv.slug:22} {lv.group:22} {len(spec.inputs):>3} {len(spec.outputs):>3} "
              f"{game:>5} {solved:>7}  {'; '.join(notes)}")
    return 0


def cmd_solve(args) -> int:
    try:
        lv = levels.find(args.level)
    except KeyError as e:
        print(e.args[0], file=sys.stderr)
        return 2
    if args.width and not lv.default_width:
        print(f"{lv.title} has a fixed size; --width ignored", file=sys.stderr)
        args.width = None
    width = args.width or lv.default_width
    spec = lv.spec(width)
    lib = _library(args)
    reference = None
    if lv.reference:
        b = Builder(lib, spec)
        reference = b.build(lv.reference(b, width or 0))
        assert reference.verify(spec), f"reference design for {lv.title} is wrong"
    title = f"{lv.title}  [{lv.group}]" + (f"  width={width}" if width else "")
    return _report(spec, lib, args, levels.components_before(lv), reference,
                   lv.game_nands if not lv.default_width else None, title, lv.note)


def cmd_custom(args) -> int:
    inputs = [s.strip() for s in args.inputs.split(",") if s.strip()]
    outputs = [s.strip() for s in args.outputs.split(",") if s.strip()]
    exprs = {}
    for e in args.expr:
        name, _, body = e.partition("=")
        exprs[name.strip()] = compile(body.strip(), f"<{name.strip()}>", "eval")
    missing = set(outputs) - set(exprs)
    if missing:
        print(f"missing --expr for outputs: {', '.join(sorted(missing))}", file=sys.stderr)
        return 2

    def fn(*bits):
        env = dict(zip(inputs, bits))
        res = []
        for o in outputs:
            v = eval(exprs[o], {"__builtins__": {}, "x": None}, env)
            res.append(None if v is None else int(bool(v) if not isinstance(v, int) else v & 1))
        return res

    spec = Spec.from_function(args.name, inputs, outputs, fn)
    lib = _library(args)
    comps = list(levels.COMPONENTS) if args.components == "all" else \
        [c for c in args.components.split(",") if c]
    return _report(spec, lib, args, comps)


def cmd_build(args) -> int:
    lib = _library(args)
    for lv in levels.LEVELS:
        spec = lv.spec()
        t0 = time.monotonic()
        reference = None
        if lv.reference:
            b = Builder(lib, spec)
            reference = b.build(lv.reference(b, lv.default_width or 0))
        res = lib.solve(spec, enumerate_limit=args.variants, timeout=_timeout(args),
                        time_limit=_time_limit(args), reference=reference)
        state = "proven" if res.proven else f"unproven (lb {res.lower_bound})"
        size = res.size if res.best else "?"
        print(f"{lv.slug:22} {size!s:>4} NANDs  {state:22} {time.monotonic() - t0:6.1f}s", flush=True)
    return 0


def cmd_render_all(args) -> int:
    lib = _library(args)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sections = []
    for lv in levels.LEVELS:
        spec = lv.spec()
        reference = None
        if lv.reference:
            b = Builder(lib, spec)
            reference = b.build(lv.reference(b, lv.default_width or 0))
        res = lib.solve(spec, enumerate_limit=args.variants, timeout=_timeout(args),
                        time_limit=_time_limit(args), reference=reference)
        if res.best is None:
            print(f"{lv.slug:22} no circuit found", flush=True)
            continue
        game = lv.game_nands if not lv.default_width else None
        rw = best_rewrite(res.netlists, lib, levels.components_before(lv))
        raw = rewrite(rw.netlist, lib, [])
        subtitle = _subtitle(res, game)
        files = []
        for suffix, view, heading in (("", rw, "Using earlier components"), ("-nand", raw, "Plain NAND gates")):
            if suffix and rw.counts().keys() <= {"nand"}:
                continue  # component view is already all NANDs
            name = f"{lv.slug}{suffix}.svg"
            (out_dir / name).write_text(render_svg(view, lib),
                                        encoding="utf-8")
            files.append((name, heading))
        sections.append((lv, subtitle, files))
        print(f"{lv.slug:22} {subtitle.replace(' · ', ', ')}", flush=True)

    body = []
    for lv, subtitle, files in sections:
        figs = "".join(f'<figure><figcaption>{escape(h)}</figcaption><img src="{escape(f)}" alt="{escape(lv.title)} '
                       f'circuit"></figure>' for f, h in files)
        note = f'<p class="note">{escape(lv.note)}</p>' if lv.note else ""
        heading = lv.title + (f" ({lv.default_width}-bit)" if lv.default_width else "")
        body.append(f'<section id="{lv.slug}"><h2>{escape(heading)} <span>{escape(lv.group)}</span></h2>'
                    f'<p class="sub">{escape(subtitle)}</p>{note}<div class="figs">{figs}</div></section>')
    toc = " · ".join(f'<a href="#{lv.slug}">{escape(lv.title)}</a>' for lv, _, _ in sections)
    (out_dir / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NandGame Solutions</title>
<style>
body {{ font-family: "Segoe UI", Helvetica, Arial, sans-serif; margin: 0 auto; max-width: 1400px; padding: 24px 16px;
       color: #1f2328; background: #ffffff; }}
h1 {{ margin: 0 0 8px; }} nav {{ line-height: 1.8; margin-bottom: 24px; }}
a {{ color: #0969da; text-decoration: none; }} a:hover {{ text-decoration: underline; }}
section {{ border-top: 1px solid #d1d9e0; padding: 18px 0 28px; }}
h2 {{ margin: 0; font-size: 22px; }} h2 span {{ font-size: 13px; font-weight: 400; color: #59636e; margin-left: 8px; }}
.sub {{ margin: 4px 0 0; color: #59636e; }} .note {{ margin: 4px 0 0; font-size: 13px; color: #9a6700; }}
.figs {{ display: flex; flex-wrap: wrap; gap: 20px; margin-top: 14px; align-items: flex-start; }}
figure {{ margin: 0; border: 1px solid #d1d9e0; border-radius: 8px; padding: 8px; overflow-x: auto; max-width: 100%; }}
figcaption {{ font-size: 12px; color: #59636e; margin: 0 0 4px 4px; text-transform: uppercase; letter-spacing: .04em; }}
img {{ display: block; max-width: none; }}
</style></head><body>
<h1>NandGame minimum-NAND solutions</h1>
<nav>{toc}</nav>
{''.join(body)}
</body></html>
""", encoding="utf-8")
    print(f"\nWrote {out_dir / 'index.html'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nandsolver", description="Minimum-NAND solver for nandgame.com levels")
    p.add_argument("--no-cache", action="store_true", help="ignore and don't write the solution cache")
    p.add_argument("-v", "--verbose", action="store_true", help="show solver progress")
    sub = p.add_subparsers(dest="cmd", required=True)

    def solve_opts(sp):
        add_time_opts(sp)
        sp.add_argument("--variants", type=int, default=50,
                        help="optimal netlists to collect when choosing the component form")
        sp.add_argument("--raw", action="store_true", help="also print the raw NAND netlist")
        sp.add_argument("--show-all", action="store_true", help="print every optimal variant found")
        sp.add_argument("--table", action="store_true", help="print the truth table")
        sp.add_argument("--svg", metavar="FILE", help="write a circuit diagram (SVG)")
        sp.add_argument("--svg-raw", action="store_true", help="draw the diagram as plain NANDs")

    sp = sub.add_parser("list", help="list the levels")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("solve", help="solve a nandgame level")
    sp.add_argument("level", help="level name, e.g. xor, full-adder, selector")
    sp.add_argument("--width", type=int, help="bit width for word-sized levels")
    solve_opts(sp)
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("solve-custom", help="solve an ad-hoc boolean function",
                        description="Example: solve-custom --inputs a,b,c --outputs y "
                                    "--expr \"y = (a and b) or not c\". Return x for don't-care.")
    sp.add_argument("--name", default="custom")
    sp.add_argument("--inputs", required=True, help="comma-separated input names")
    sp.add_argument("--outputs", required=True, help="comma-separated output names")
    sp.add_argument("--expr", action="append", default=[], help="'out = python expression' (repeatable)")
    sp.add_argument("--components", default="all", help="comma-separated components to use, or 'all'")
    solve_opts(sp)
    sp.set_defaults(func=cmd_custom)

    sp = sub.add_parser("build-library", help="solve every level in order and fill the cache")
    add_time_opts(sp)
    sp.add_argument("--variants", type=int, default=50)
    sp.set_defaults(func=cmd_build)

    sp = sub.add_parser("render-all", help="draw every level's solution into an HTML gallery")
    sp.add_argument("--out", default="diagrams", help="output directory (default: diagrams)")
    add_time_opts(sp)
    sp.add_argument("--variants", type=int, default=50)
    sp.set_defaults(func=cmd_render_all)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
