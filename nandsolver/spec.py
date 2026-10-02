"""Boolean specifications: named inputs/outputs plus a (possibly partial) truth table."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

Bit = int | None  # 0, 1, or None for "don't care"


def input_masks(n_inputs: int) -> list[int]:
    """Bit-parallel value of each input over all 2^n rows.

    Row r assigns input i the bit (r >> (n-1-i)) & 1, so the first input is the
    most significant bit and rows enumerate in the natural truth-table order.
    """
    rows = 1 << n_inputs
    masks = []
    for i in range(n_inputs):
        shift = n_inputs - 1 - i
        m = 0
        for r in range(rows):
            if (r >> shift) & 1:
                m |= 1 << r
        masks.append(m)
    return masks


@dataclass(frozen=True)
class Spec:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    values: tuple[int, ...]  # per output: bit r set when the output is 1 on row r
    care: tuple[int, ...]    # per output: bit r set when row r is specified

    def __post_init__(self):
        names = self.inputs + self.outputs
        if len(set(names)) != len(names):
            raise ValueError(f"{self.name}: input/output names must be unique: {names}")

    @property
    def n_rows(self) -> int:
        return 1 << len(self.inputs)

    @property
    def full_mask(self) -> int:
        return (1 << self.n_rows) - 1

    def row_bits(self, r: int) -> tuple[int, ...]:
        n = len(self.inputs)
        return tuple((r >> (n - 1 - i)) & 1 for i in range(n))

    def output_bit(self, m: int, r: int) -> Bit:
        if not (self.care[m] >> r) & 1:
            return None
        return (self.values[m] >> r) & 1

    @classmethod
    def from_function(cls, name: str, inputs: Sequence[str], outputs: Sequence[str],
                      fn: Callable[..., object]) -> Spec:
        """Build a spec by calling ``fn(*input_bits)`` for every row.

        ``fn`` may return a single bit (single output), a tuple/list in output order,
        or a dict keyed by output name. A value of ``None`` means don't-care.
        """
        inputs, outputs = tuple(inputs), tuple(outputs)
        values = [0] * len(outputs)
        care = [0] * len(outputs)
        n = len(inputs)
        for r in range(1 << n):
            bits = tuple((r >> (n - 1 - i)) & 1 for i in range(n))
            res = fn(*bits)
            if isinstance(res, Mapping):
                row = [res[o] for o in outputs]
            elif isinstance(res, (tuple, list)):
                row = list(res)
            else:
                row = [res]
            if len(row) != len(outputs):
                raise ValueError(f"{name}: expected {len(outputs)} outputs, got {row!r}")
            for m, v in enumerate(row):
                if v is None:
                    continue
                care[m] |= 1 << r
                if v:
                    values[m] |= 1 << r
        return cls(name, inputs, outputs, tuple(values), tuple(care))

    @classmethod
    def from_table(cls, name: str, inputs: Sequence[str], outputs: Sequence[str],
                   table: Mapping[tuple[int, ...], Sequence[Bit]]) -> Spec:
        """Build a spec from ``{input_bits: output_bits}``; missing rows are don't-care."""
        return cls.from_function(name, inputs, outputs,
                                 lambda *bits: tuple(table.get(bits, (None,) * len(outputs))))

    def key(self) -> str:
        """Stable hash of the function (not the name), used for caching."""
        payload = json.dumps([self.inputs, self.outputs, self.values, self.care])
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def format_table(self) -> str:
        head = " ".join(self.inputs) + " | " + " ".join(self.outputs)
        lines = [head, "-" * len(head)]
        for r in range(self.n_rows):
            ins = " ".join(str(b).rjust(len(nm)) for b, nm in zip(self.row_bits(r), self.inputs))
            outs = []
            for m, nm in enumerate(self.outputs):
                b = self.output_bit(m, r)
                outs.append(("x" if b is None else str(b)).rjust(len(nm)))
            lines.append(ins + " | " + " ".join(outs))
        return "\n".join(lines)
