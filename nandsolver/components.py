"""Reusable components (inv, and, xor, half adder, ...) and the solving session that owns them."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .cache import Cache
from .netlist import Netlist
from .spec import Spec
from .synth import SynthResult, synthesize

TEMPLATE_LIMIT = 32  # optimal variants per component used for pattern matching


@dataclass(frozen=True)
class Component:
    name: str         # display name, e.g. "xor"
    level: str        # key of the level that unlocks it
    spec: Spec


class Library:
    """Solves specs (with caching) and provides component netlists."""

    def __init__(self, components: dict[str, Component], cache: Cache | None = None,
                 progress: Callable[[str], None] | None = None):
        self.components = components
        self.cache = cache or Cache(None)
        self.progress = progress
        self._templates: dict[str, list[Netlist]] = {}

    def solve(self, spec: Spec, *, constants: tuple[str, ...] = (), enumerate_limit: int = 1,
              timeout: float | None = None, time_limit: float | None = None,
              reference: Netlist | None = None, use_cache: bool = True) -> SynthResult:
        if use_cache:
            cached = self.cache.load(spec, constants, enumerate_limit)
            if cached is not None:
                return cached
        result = synthesize(spec, constants=constants, timeout=timeout, time_limit=time_limit,
                            enumerate_limit=enumerate_limit, reference=reference,
                            progress=self.progress)
        self.cache.store(result, constants, enumerate_limit)
        return result

    def templates(self, name: str) -> list[Netlist]:
        """All minimum-NAND implementations of a component (up to TEMPLATE_LIMIT)."""
        if name not in self._templates:
            res = self.solve(self.components[name].spec, enumerate_limit=TEMPLATE_LIMIT)
            self._templates[name] = res.netlists
        return self._templates[name]

    def netlist(self, name: str) -> Netlist:
        return self.templates(name)[0]


class Builder:
    """Composes a netlist from NANDs and components, e.g. for reference designs."""

    def __init__(self, lib: Library, spec: Spec, constants: tuple[str, ...] = ()):
        self.lib, self.spec = lib, spec
        self.sources = spec.inputs + constants
        self.gates: list[tuple[int, int]] = []

    def __getitem__(self, name: str) -> int:
        return self.sources.index(name)

    def nand(self, a: int, b: int) -> int:
        self.gates.append((a, b))
        return len(self.sources) + len(self.gates) - 1

    def use(self, name: str, *ins: int):
        """Instantiate component ``name``; returns its output node(s)."""
        tpl = self.lib.netlist(name)
        if len(ins) != tpl.n_sources:
            raise ValueError(f"{name} takes {tpl.n_sources} inputs, got {len(ins)}")
        node = list(ins)
        for a, b in tpl.gates:
            node.append(self.nand(node[a], node[b]))
        outs = tuple(node[o] for o in tpl.outputs)
        return outs[0] if len(outs) == 1 else outs

    def build(self, outputs: dict[str, int]) -> Netlist:
        net = Netlist(self.sources, list(self.gates),
                      tuple(outputs[o] for o in self.spec.outputs), self.spec.outputs)
        return net.pruned()
