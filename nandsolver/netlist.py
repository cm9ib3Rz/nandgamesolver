"""NAND-only netlists: simulation, verification and printing."""
from __future__ import annotations

from dataclasses import dataclass, field

from .spec import Spec, input_masks

CONSTANTS = ("0", "1")


@dataclass
class Netlist:
    """A circuit made only of 2-input NAND gates.

    Nodes ``0 .. len(sources)-1`` are sources: the spec's inputs in order, optionally
    followed by constant sources named "0"/"1". Node ``len(sources) + i`` is gate ``i``,
    computing ``NAND(gates[i][0], gates[i][1])``; a gate whose two inputs are the
    same node is an inverter. Gates only reference lower-numbered nodes.
    """
    sources: tuple[str, ...]
    gates: list[tuple[int, int]]
    outputs: tuple[int, ...]
    output_names: tuple[str, ...]
    meta: dict = field(default_factory=dict, compare=False)

    @property
    def n_sources(self) -> int:
        return len(self.sources)

    @property
    def n_inputs(self) -> int:
        return sum(1 for s in self.sources if s not in CONSTANTS)

    @property
    def size(self) -> int:
        return len(self.gates)

    def gate_node(self, i: int) -> int:
        return self.n_sources + i

    def simulate(self) -> list[int]:
        """Bit-parallel value of every node over all input rows."""
        n_in = self.n_inputs
        full = (1 << (1 << n_in)) - 1
        masks = iter(input_masks(n_in))
        vals = []
        for s in self.sources:
            vals.append(0 if s == "0" else full if s == "1" else next(masks))
        for a, b in self.gates:
            vals.append(~(vals[a] & vals[b]) & full)
        return vals

    def output_values(self) -> list[int]:
        vals = self.simulate()
        return [vals[o] for o in self.outputs]

    def verify(self, spec: Spec) -> bool:
        if tuple(s for s in self.sources if s not in CONSTANTS) != spec.inputs:
            return False
        if self.output_names != spec.outputs:
            return False
        for got, want, care in zip(self.output_values(), spec.values, spec.care):
            if (got ^ want) & care:
                return False
        return True

    def fanout(self) -> list[list[int]]:
        """For each node, the gate indices that read it."""
        fo: list[list[int]] = [[] for _ in range(self.n_sources + self.size)]
        for i, (a, b) in enumerate(self.gates):
            fo[a].append(i)
            if b != a:
                fo[b].append(i)
        return fo

    def node_names(self) -> list[str]:
        names = list(self.sources)
        driven = {}
        for o, nm in zip(self.outputs, self.output_names):
            driven.setdefault(o, nm)
        for i in range(self.size):
            node = self.gate_node(i)
            names.append(driven.get(node, f"n{i + 1}"))
        return names

    def to_text(self, indent: str = "  ") -> str:
        names = self.node_names()
        lines = []
        for i, (a, b) in enumerate(self.gates):
            lines.append(f"{indent}{names[self.gate_node(i)]} = nand({names[a]}, {names[b]})")
        for o, nm in zip(self.outputs, self.output_names):
            if names[o] != nm:
                lines.append(f"{indent}{nm} = {names[o]}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"sources": list(self.sources), "gates": [list(g) for g in self.gates],
                "outputs": list(self.outputs), "output_names": list(self.output_names)}

    @classmethod
    def from_dict(cls, d: dict) -> Netlist:
        return cls(tuple(d["sources"]), [tuple(g) for g in d["gates"]],
                   tuple(d["outputs"]), tuple(d["output_names"]))

    def pruned(self) -> Netlist:
        """Copy with gates that don't reach any output removed."""
        live = set(self.outputs)
        for i in range(self.size - 1, -1, -1):
            node = self.gate_node(i)
            if node in live:
                live.update(self.gates[i])
        remap = {s: s for s in range(self.n_sources)}
        gates = []
        for i, (a, b) in enumerate(self.gates):
            node = self.gate_node(i)
            if node in live:
                remap[node] = self.n_sources + len(gates)
                gates.append((remap[a], remap[b]))
        return Netlist(self.sources, gates, tuple(remap[o] for o in self.outputs),
                       self.output_names, dict(self.meta))
