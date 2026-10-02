"""Render a solution (a Rewrite) as an SVG schematic.

Layout is a simple layered (Sugiyama-style) drawing, left to right:
  * inputs in the first column, outputs in the last, each part in the column after
    the latest part feeding it;
  * signals that skip columns get a "pass-through" slot in every column they cross,
    so wires never run behind boxes;
  * parts within a column are ordered by the barycentre of their neighbours to cut
    crossings, then positioned vertically to keep wires as straight as possible;
  * wires are orthogonal, each signal getting its own vertical track in the gap
    between two columns, and its own colour.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from .components import Library
from .rewrite import Part, Rewrite

PITCH = 24          # vertical distance between pins
NODE_GAP = 28       # vertical gap between stacked nodes
SLOT_H = 8          # height of a pass-through slot
SLOT_GAP = 14       # vertical gap next to a pass-through slot
TRACK = 14          # horizontal distance between wire tracks
GAP_PAD = 30        # clear space either side of the tracks in a gap
MARGIN = 30
TITLE_H = 46
COLOURS = ["#1f6feb", "#d1242f", "#1a7f37", "#8250df", "#bf8700", "#0a7d8c",
           "#cf222e", "#6639ba", "#953800", "#116329", "#0550ae", "#a40e26"]


@dataclass
class _Node:
    kind: str                         # "in", "out", "part", "slot"
    layer: int
    label: str = ""
    in_names: list[str] = field(default_factory=list)
    out_names: list[str] = field(default_factory=list)
    part: Part | None = None
    signal: int | None = None         # for "slot", "in" and "out" nodes
    width: float = 0
    height: float = 0
    x: float = 0
    y: float = 0                      # top

    def in_pin(self, i: int) -> tuple[float, float]:
        if self.kind == "slot":
            return self.x, self.y + self.height / 2
        n = max(len(self.in_names), 1)
        return self.x, self._pin_y(i, n)

    def out_pin(self, i: int) -> tuple[float, float]:
        if self.kind == "slot":
            return self.x + self.width, self.y + self.height / 2
        n = max(len(self.out_names), 1)
        return self.x + self.width, self._pin_y(i, n)

    def _pin_y(self, i: int, n: int) -> float:
        span = (n - 1) * PITCH
        return self.y + self.height / 2 - span / 2 + i * PITCH


def _size(node: _Node):
    if node.kind == "slot":
        node.height = SLOT_H
    elif node.kind in ("in", "out"):
        node.width, node.height = 16 + 8 * len(node.label), 24
    elif node.label == "nand":
        node.width, node.height = 48, 2 * PITCH + 8
    elif node.label == "inv":
        node.width, node.height = 42, PITCH + 10
    else:
        pins = max(len(node.in_names), len(node.out_names), 1)
        label_w = 7 * (max(map(len, node.in_names), default=0) + max(map(len, node.out_names), default=0))
        node.width = max(76, 8.5 * len(node.label) + label_w + 26)
        node.height = pins * PITCH + 14


def render_svg(rw: Rewrite, lib: Library, title: str = "", subtitle: str = "") -> str:
    net = rw.netlist
    nodes: list[_Node] = []
    producer: dict[int, tuple[_Node, int]] = {}     # signal -> (node, out pin)
    consumers: dict[int, list[tuple[_Node, int]]] = {}

    for i, name in enumerate(net.sources):
        n = _Node("in", 0, name, out_names=[name], signal=i)
        nodes.append(n)
        producer[i] = (n, 0)

    for p in rw.parts:
        if p.kind == "nand":
            ins, outs = ["a", "b"], ["out"]
        else:
            cs = lib.components[p.kind].spec
            ins, outs = list(cs.inputs), list(cs.outputs)
        layer = 1 + max((producer[s][0].layer for s in p.inputs), default=0)
        n = _Node("part", layer, p.kind, ins, outs, part=p)
        nodes.append(n)
        for k, s in enumerate(p.inputs):
            consumers.setdefault(s, []).append((n, k))
        for k, s in enumerate(p.outputs):
            producer[s] = (n, k)

    last = 1 + max((n.layer for n in nodes), default=0)
    for s, name in zip(net.outputs, net.output_names):
        n = _Node("out", last, name, in_names=[name], signal=s)
        nodes.append(n)
        consumers.setdefault(s, []).append((n, 0))

    # Pass-through slots for signals that skip columns.
    slot_at: dict[tuple[int, int], _Node] = {}
    for s, cons in consumers.items():
        src_layer = producer[s][0].layer
        far = max(c.layer for c, _ in cons)
        for layer in range(src_layer + 1, far):
            slot = _Node("slot", layer, signal=s)
            nodes.append(slot)
            slot_at[(s, layer)] = slot

    for n in nodes:
        _size(n)

    def source_at(s: int, layer: int) -> tuple[_Node, int] | None:
        node, pin = producer[s]
        if node.layer == layer:
            return node, pin
        slot = slot_at.get((s, layer))
        return (slot, 0) if slot else None

    # Edges between adjacent layers: (src node, src pin, dst node, dst pin, signal).
    edges = []
    for s, cons in consumers.items():
        for c, k in cons:
            src = source_at(s, c.layer - 1)
            edges.append((src[0], src[1], c, k, s))
    for (s, layer), slot in slot_at.items():
        src = source_at(s, layer - 1)
        edges.append((src[0], src[1], slot, 0, s))

    layers: list[list[_Node]] = [[] for _ in range(last + 1)]
    for n in nodes:
        layers[n.layer].append(n)
    _order(layers, edges)
    _place_y(layers, edges, MARGIN + (TITLE_H if title or subtitle else 0))
    gaps = _place_x(layers, edges)

    width = max((n.x + n.width for n in nodes), default=0) + MARGIN
    height = max((n.y + n.height for n in nodes), default=0) + MARGIN
    colour = {s: COLOURS[k % len(COLOURS)] for k, s in enumerate(sorted(consumers))}

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
           f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="Segoe UI, Helvetica, Arial, sans-serif">',
           f'<rect width="100%" height="100%" fill="#ffffff"/>']
    if title:
        out.append(f'<text x="{MARGIN}" y="26" font-size="17" font-weight="600" fill="#1f2328">{escape(title)}</text>')
    if subtitle:
        out.append(f'<text x="{MARGIN}" y="44" font-size="12" fill="#59636e">{escape(subtitle)}</text>')

    out.append('<g fill="none" stroke-width="1.8" stroke-linejoin="round">')
    for gap in gaps:
        out.extend(_draw_gap(gap, colour))
    for n in nodes:
        if n.kind == "slot":
            x1, y = n.in_pin(0)
            x2, _ = n.out_pin(0)
            out.append(f'<path d="M{x1:.1f},{y:.1f}H{x2:.1f}" stroke="{colour[n.signal]}"/>')
    out.append('</g>')

    for n in nodes:
        out.extend(_draw_node(n))
    out.append('</svg>')
    return "\n".join(out)


# --- ordering and placement -----------------------------------------------------------

def _order(layers, edges, sweeps: int = 8):
    """Barycentre ordering; the input and output columns keep their given order."""
    def pos_map():
        return {id(n): (i, n) for layer in layers for i, n in enumerate(layer)}

    for sweep in range(sweeps):
        down = sweep % 2 == 0
        rng = range(1, len(layers) - 1) if down else range(len(layers) - 2, 0, -1)
        for li in rng:
            pm = pos_map()
            keys = {}
            for idx, n in enumerate(layers[li]):
                if down:
                    nb = [pm[id(e[0])][0] + 0.1 * e[1] for e in edges if e[2] is n]
                else:
                    nb = [pm[id(e[2])][0] + 0.1 * e[3] for e in edges if e[0] is n]
                keys[id(n)] = sum(nb) / len(nb) if nb else idx
            layers[li].sort(key=lambda n: keys[id(n)])


def _place_y(layers, edges, top_y: float, iterations: int = 30):
    # Start stacked, then repeatedly pull each node toward its neighbours' pins.
    for layer in layers:
        y = top_y
        for n in layer:
            n.y = y
            y += n.height + NODE_GAP
    for it in range(iterations):
        down = it % 2 == 0
        rng = range(len(layers)) if down else range(len(layers) - 1, -1, -1)
        for li in rng:
            desired = []
            for n in layers[li]:
                pulls = []
                for src, sp, dst, dp, _ in edges:
                    if dst is n:
                        pulls.append(src.out_pin(sp)[1] - (n.in_pin(dp)[1] - n.y))
                    elif src is n:
                        pulls.append(dst.in_pin(dp)[1] - (n.out_pin(sp)[1] - n.y))
                desired.append(sum(pulls) / len(pulls) if pulls else n.y)
            _pack(layers[li], desired)
    _straighten(layers, edges)
    top = min((n.y for layer in layers for n in layer), default=0)
    for layer in layers:
        for n in layer:
            n.y += top_y - top


def _spacing(a: _Node, b: _Node) -> float:
    """Clear space required between vertically adjacent nodes a (above) and b."""
    return NODE_GAP if a.kind != "slot" and b.kind != "slot" else SLOT_GAP


def _straighten(layers, edges, max_move: float = 14, passes: int = 3):
    """Remove small kinks: nudge each node (by at most ``max_move``) so that one of its
    wires runs dead straight, where there is room. Pass-throughs and outputs are lined
    up with their source whenever space allows; inputs with a consumer."""
    for _ in range(passes):
        for layer in layers:
            for idx, n in enumerate(layer):
                cands = []
                for src, sp, dst, dp, _ in edges:
                    if dst is n:
                        cands.append(src.out_pin(sp)[1] - (n.in_pin(dp)[1] - n.y))
                    elif src is n and n.kind not in ("slot", "out"):
                        cands.append(dst.in_pin(dp)[1] - (n.out_pin(sp)[1] - n.y))
                limit = float("inf") if n.kind in ("slot", "out") else max_move
                above = layer[idx - 1] if idx > 0 else None
                below = layer[idx + 1] if idx + 1 < len(layer) else None
                for top in sorted(cands, key=lambda t: abs(t - n.y)):
                    if abs(top - n.y) < 0.01 or abs(top - n.y) > limit:
                        break
                    if above is not None and above.y + above.height + _spacing(above, n) > top + 0.01:
                        continue
                    if below is not None and top + n.height + _spacing(n, below) > below.y + 0.01:
                        continue
                    n.y = top
                    break


def _offsets(layer, start, end):
    """Offset of each node from the top of a packed run layer[start..end]."""
    offs, off = [], 0.0
    for j in range(start, end + 1):
        if j > start:
            off += layer[j - 1].height + _spacing(layer[j - 1], layer[j])
        offs.append(off)
    return offs


def _pack(layer, desired):
    """Positions as close as possible to ``desired`` while keeping order and spacing
    (pool-adjacent-violators on block means)."""
    blocks = []  # [start index, end index, top]
    for i in range(len(layer)):
        blocks.append([i, i, desired[i]])
        while len(blocks) > 1:
            a, b = blocks[-2], blocks[-1]
            a_bottom = a[2] + _offsets(layer, a[0], a[1])[-1] + layer[a[1]].height
            if a_bottom + _spacing(layer[a[1]], layer[b[0]]) <= b[2]:
                break
            start, end = a[0], b[1]
            offs = _offsets(layer, start, end)
            tops = [desired[j] - offs[j - start] for j in range(start, end + 1)]
            blocks[-2:] = [[start, end, sum(tops) / len(tops)]]
    for start, end, top in blocks:
        for j, off in zip(range(start, end + 1), _offsets(layer, start, end)):
            layer[j].y = top + off


@dataclass
class _Gap:
    x0: float = 0
    tracks: list = field(default_factory=list)  # (x, signal, (sx, sy), [(tx, ty), ...])


def _place_x(layers, edges) -> list[_Gap]:
    # Group the edges leaving each layer by signal: one vertical track per signal per gap.
    per_gap: list[dict] = [dict() for _ in range(len(layers) - 1)]
    for src, sp, dst, dp, s in edges:
        per_gap[src.layer].setdefault((s, id(src), sp), (src, sp, []))[2].append((dst, dp))

    gaps = []
    x = MARGIN
    for li, layer in enumerate(layers):
        col_w = max((n.width for n in layer if n.kind != "slot"), default=20)
        for n in layer:
            if n.kind == "slot":
                n.x, n.width = x, col_w
            elif n.kind == "out":
                n.x = x
            elif n.kind == "in":
                n.x = x + col_w - n.width
            else:
                n.x = x + (col_w - n.width) / 2
        x += col_w
        if li == len(layers) - 1:
            break
        groups = list(per_gap[li].values())
        gap = _Gap(x0=x)
        # Track order: downward wires left-to-right from the bottom source up, upward
        # wires to the right of them from the top source down - this avoids crossings
        # between wires that nest.
        def key(g):
            src, sp, dsts = g
            sy = src.out_pin(sp)[1]
            ty = sum(d.in_pin(p)[1] for d, p in dsts) / len(dsts)
            return (0, -sy) if ty >= sy else (1, sy)
        groups.sort(key=key)
        straight = [g for g in groups if _is_straight(g)]
        bent = [g for g in groups if not _is_straight(g)]
        width = 2 * GAP_PAD + max(len(bent) - 1, 0) * TRACK
        for k, g in enumerate(bent):
            gap.tracks.append((x + GAP_PAD + k * TRACK, g))
        for g in straight:
            gap.tracks.append((None, g))
        gaps.append(gap)
        x += max(width, 60)
    return gaps


def _is_straight(group) -> bool:
    src, sp, dsts = group
    sy = src.out_pin(sp)[1]
    return all(abs(d.in_pin(p)[1] - sy) < 0.5 for d, p in dsts)


# --- drawing --------------------------------------------------------------------------

def _draw_gap(gap: _Gap, colour) -> list[str]:
    out = []
    for tx, (src, sp, dsts) in gap.tracks:
        s = src.signal if src.kind in ("slot", "in") else None
        if s is None:
            s = src.part.outputs[sp]
        c = colour[s]
        sx, sy = src.out_pin(sp)
        ends = [d.in_pin(p) for d, p in dsts]
        if tx is None:
            for ex, ey in ends:
                out.append(f'<path d="M{sx:.1f},{sy:.1f}H{ex:.1f}" stroke="{c}"/>')
            continue
        ys = [sy] + [ey for _, ey in ends]
        lo, hi = min(ys), max(ys)
        out.append(f'<path d="M{sx:.1f},{sy:.1f}H{tx:.1f}" stroke="{c}"/>')
        if hi - lo > 0.5:
            out.append(f'<path d="M{tx:.1f},{lo:.1f}V{hi:.1f}" stroke="{c}"/>')
        for ex, ey in ends:
            out.append(f'<path d="M{tx:.1f},{ey:.1f}H{ex:.1f}" stroke="{c}"/>')
        # junction dots where a wire branches off mid-track
        dots = {round(y, 1) for y in ys if lo + 0.5 < y < hi - 0.5}
        if len(ends) > 1 and abs(sy - lo) > 0.5 and abs(sy - hi) > 0.5:
            dots.add(round(sy, 1))
        for y in sorted(dots):
            out.append(f'<circle cx="{tx:.1f}" cy="{y:.1f}" r="3.2" fill="{c}" stroke="none"/>')
    return out


def _draw_node(n: _Node) -> list[str]:
    if n.kind == "slot":
        return []
    x, y, w, h = n.x, n.y, n.width, n.height
    stroke, fill = "#1f2328", "#f6f8fa"
    if n.kind in ("in", "out"):
        tint = "#ddf4ff" if n.kind == "in" else "#dafbe1"
        return [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="12" '
                f'fill="{tint}" stroke="{stroke}" stroke-width="1.4"/>',
                f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 4.5:.1f}" font-size="13" font-weight="600" '
                f'text-anchor="middle" fill="#1f2328">{escape(n.label)}</text>']
    if n.label == "nand":
        bx = x + w - 9  # body ends before the bubble
        r = h / 2
        body = (f'M{x:.1f},{y:.1f}H{bx - r:.1f}A{r:.1f},{r:.1f} 0 0 1 {bx - r:.1f},{y + h:.1f}'
                f'H{x:.1f}Z')
        return [f'<path d="{body}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>',
                f'<circle cx="{bx + 4:.1f}" cy="{y + h / 2:.1f}" r="4" fill="#fff" stroke="{stroke}" stroke-width="1.6"/>']
    if n.label == "inv":
        bx = x + w - 9
        tri = f'M{x:.1f},{y:.1f}L{bx:.1f},{y + h / 2:.1f}L{x:.1f},{y + h:.1f}Z'
        return [f'<path d="{tri}" fill="{fill}" stroke="{stroke}" stroke-width="1.6"/>',
                f'<circle cx="{bx + 4:.1f}" cy="{y + h / 2:.1f}" r="4" fill="#fff" stroke="{stroke}" stroke-width="1.6"/>']
    out = [f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="6" '
           f'fill="#fff8c5" stroke="{stroke}" stroke-width="1.6"/>',
           f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 5:.1f}" font-size="14" font-weight="700" '
           f'text-anchor="middle" fill="#1f2328">{escape(n.label)}</text>']
    if len(n.in_names) > 1:
        for i, nm in enumerate(n.in_names):
            px, py = n.in_pin(i)
            out.append(f'<text x="{px + 5:.1f}" y="{py + 4:.1f}" font-size="10.5" fill="#59636e">{escape(nm)}</text>')
    if len(n.out_names) > 1:
        for i, nm in enumerate(n.out_names):
            px, py = n.out_pin(i)
            out.append(f'<text x="{px - 5:.1f}" y="{py + 4:.1f}" font-size="10.5" text-anchor="end" '
                       f'fill="#59636e">{escape(nm)}</text>')
    return out
