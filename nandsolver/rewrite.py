"""Re-express a NAND netlist using higher-level components.

Each component's minimum-NAND implementations act as structural templates. We find
every place a template occurs in the netlist (respecting NAND commutativity), keep
only occurrences whose internal signals aren't used elsewhere, and then pick a set of
non-overlapping occurrences giving the fewest top-level parts. The NAND count never
changes; this only makes the circuit easier to read and to enter in the game.
"""
from __future__ import annotations

from dataclasses import dataclass

from .components import Library
from .netlist import Netlist
from .spec import Spec, input_masks


@dataclass(frozen=True)
class Match:
    component: str
    gates: frozenset[int]       # netlist gate indices covered
    inputs: tuple[int, ...]     # netlist node per component input
    outputs: tuple[int, ...]    # netlist node per component output


@dataclass(frozen=True)
class Part:
    kind: str                   # "nand" or a component name
    inputs: tuple[int, ...]
    outputs: tuple[int, ...]
    cost: int                   # NAND gates inside


@dataclass
class Rewrite:
    netlist: Netlist
    parts: list[Part]           # in topological order

    @property
    def nands(self) -> int:
        return sum(p.cost for p in self.parts)

    @property
    def score(self) -> tuple[int, int]:
        """Fewer parts is better; on a tie prefer bigger components."""
        return len(self.parts), -sum(p.cost ** 2 for p in self.parts)

    def counts(self) -> dict[str, int]:
        c: dict[str, int] = {}
        for p in self.parts:
            c[p.kind] = c.get(p.kind, 0) + 1
        return c

    def to_text(self, indent: str = "  ") -> str:
        net = self.netlist
        names = {i: s for i, s in enumerate(net.sources)}
        for o, nm in zip(net.outputs, net.output_names):
            names.setdefault(o, nm)
        used = {n for p in self.parts for n in p.inputs} | set(net.outputs)
        counter = 0
        lines = []
        for p in self.parts:
            outs = []
            for o in p.outputs:
                if o not in names:
                    if o in used:
                        counter += 1
                        names[o] = f"t{counter}"
                    else:
                        names[o] = "_"
                outs.append(names[o])
            args = ", ".join(names[i] for i in p.inputs)
            lines.append(f"{indent}{', '.join(outs)} = {p.kind}({args})")
        for o, nm in zip(net.outputs, net.output_names):
            if names[o] != nm:
                lines.append(f"{indent}{nm} = {names[o]}")
        return "\n".join(lines)

    def verify(self, spec: Spec, lib: Library) -> bool:
        """Evaluate the parts by their component truth tables (not their NANDs)."""
        net = self.netlist
        n_in = net.n_inputs
        rows = 1 << n_in
        full = (1 << rows) - 1
        masks = iter(input_masks(n_in))
        vals = {i: (0 if s == "0" else full if s == "1" else next(masks))
                for i, s in enumerate(net.sources)}
        for p in self.parts:
            if p.kind == "nand":
                a, b = p.inputs
                vals[p.outputs[0]] = ~(vals[a] & vals[b]) & full
                continue
            cspec = lib.components[p.kind].spec
            k = len(cspec.inputs)
            outs = [0] * len(p.outputs)
            for r in range(rows):
                crow = 0
                for i in p.inputs:
                    crow = (crow << 1) | ((vals[i] >> r) & 1)
                for m in range(len(outs)):
                    if (cspec.values[m] >> crow) & 1:
                        outs[m] |= 1 << r
            assert k == len(p.inputs)
            for o, v in zip(p.outputs, outs):
                vals[o] = v
        for o, want, care in zip(net.outputs, spec.values, spec.care):
            if (vals[o] ^ want) & care:
                return False
        return True


def _descendants(net: Netlist) -> list[int]:
    """Bitmask of nodes reachable from each node (excluding itself)."""
    fo = net.fanout()
    total = net.n_sources + net.size
    desc = [0] * total
    for node in range(total - 1, -1, -1):
        d = 0
        for g in fo[node]:
            child = net.gate_node(g)
            d |= (1 << child) | desc[child]
        desc[node] = d
    return desc


def find_matches(net: Netlist, tpl: Netlist, name: str, desc: list[int] | None = None) -> set[Match]:
    ns, ts = net.n_sources, tpl.n_sources
    if any(o < ts for o in tpl.outputs):
        return set()
    desc = desc if desc is not None else _descendants(net)
    fo = net.fanout()
    net_outputs = set(net.outputs)
    tpl_out_gates = {o - ts for o in tpl.outputs}
    order = list(range(tpl.size - 1, -1, -1))
    gmap: dict[int, int] = {}
    smap: dict[int, int] = {}
    used: set[int] = set()
    found: set[Match] = set()

    def bind(t: int, x: int, undo: list) -> bool:
        if t < ts:
            if t in smap:
                return smap[t] == x
            smap[t] = x
            undo.append(("s", t))
            return True
        g = t - ts
        if x < ns:
            return False
        xi = x - ns
        if g in gmap:
            return gmap[g] == xi
        if xi in used:
            return False
        gmap[g] = xi
        used.add(xi)
        undo.append(("g", g))
        return True

    def rollback(undo: list):
        for kind, t in reversed(undo):
            if kind == "s":
                del smap[t]
            else:
                used.discard(gmap.pop(t))

    def finish():
        if len(smap) != ts:
            return
        image = {ns + c for c in gmap.values()}
        if any(smap[s] in image for s in range(ts)):
            return
        gates = frozenset(gmap.values())
        for g, c in gmap.items():
            if g in tpl_out_gates:
                continue
            if ns + c in net_outputs or any(u not in gates for u in fo[ns + c]):
                return
        member = 0
        for c in gates:
            member |= 1 << (ns + c)
        for node in range(ns + net.size):
            if not (member >> node) & 1 and desc[node] & member:
                if any((desc[ns + c] >> node) & 1 for c in gates):
                    return  # leaves the match and re-enters it: not convex
        found.add(Match(name, gates, tuple(smap[s] for s in range(ts)),
                        tuple(ns + gmap[o - ts] for o in tpl.outputs)))

    def rec(pos: int):
        if pos == len(order):
            finish()
            return
        g = order[pos]
        if g in gmap:
            cands = [gmap[g]]
        else:
            cands = [c for c in range(net.size) if c not in used]
        for c in cands:
            fresh = g not in gmap
            if fresh:
                gmap[g] = c
                used.add(c)
            a, b = tpl.gates[g]
            c1, c2 = net.gates[c]
            for x, y in {(c1, c2), (c2, c1)}:
                undo: list = []
                if bind(a, x, undo) and bind(b, y, undo):
                    rec(pos + 1)
                rollback(undo)
            if fresh:
                used.discard(gmap.pop(g))

    rec(0)
    return found


def _cover(net: Netlist, matches: list[Match]) -> list[Match]:
    by_gate: dict[int, list[Match]] = {i: [] for i in range(net.size)}
    for m in sorted(matches, key=lambda m: -len(m.gates)):
        by_gate[min(m.gates)].append(m)
    biggest = max((len(m.gates) for m in matches), default=1)
    best: list = [None, None]  # score, chosen

    def rec(i: int, covered: frozenset, chosen: list, nparts: int, sq: int):
        while i < net.size and i in covered:
            i += 1
        remaining = sum(1 for g in range(i, net.size) if g not in covered)
        if best[0] is not None and nparts + -(-remaining // biggest) > best[0][0]:
            return
        if i == net.size:
            score = (nparts, -sq)
            if best[0] is None or score < best[0]:
                best[0], best[1] = score, list(chosen)
            return
        for m in by_gate[i]:
            if not (m.gates & covered):
                chosen.append(m)
                rec(i + 1, covered | m.gates, chosen, nparts + 1, sq + len(m.gates) ** 2)
                chosen.pop()
        rec(i + 1, covered | {i}, chosen, nparts + 1, sq + 1)

    rec(0, frozenset(), [], 0, 0)
    return best[1]


def rewrite(net: Netlist, lib: Library, components: list[str]) -> Rewrite:
    desc = _descendants(net)
    matches: set[Match] = set()
    for name in components:
        for tpl in lib.templates(name):
            matches |= find_matches(net, tpl, name, desc)
    chosen = _cover(net, list(matches))

    parts: list[Part] = [Part(m.component, m.inputs, m.outputs, len(m.gates)) for m in chosen]
    covered = set().union(*(m.gates for m in chosen)) if chosen else set()
    for i, (a, b) in enumerate(net.gates):
        if i not in covered:
            parts.append(Part("nand", (a, b), (net.gate_node(i),), 1))

    # Topological order of parts (matches are convex, so the part graph is acyclic).
    producer = {o: k for k, p in enumerate(parts) for o in p.outputs}
    deps = [{producer[i] for i in p.inputs if i in producer} for p in parts]
    ordered, done = [], set()
    while len(ordered) < len(parts):
        ready = [k for k in range(len(parts)) if k not in done and deps[k] <= done]
        k = min(ready, key=lambda k: min(parts[k].outputs))
        ordered.append(parts[k])
        done.add(k)
    return Rewrite(net, ordered)


def best_rewrite(nets: list[Netlist], lib: Library, components: list[str]) -> Rewrite:
    return min((rewrite(n, lib, components) for n in nets), key=lambda r: r.score)
