"""Exact minimum-NAND synthesis via SAT.

For a gate budget ``k`` we ask a SAT solver whether some circuit of exactly ``k``
NAND gates realises the spec (Kojevnikov-Kulikov / Knuth TAOCP 7.1.2 style
encoding, specialised to NAND). Budgets are tried in increasing order, so the first
satisfiable one is optimal.

Variables:
  s[i][p]  gate i reads node pair p = (j, l), j <= l < node(i)   (exactly one per gate)
  x[i][t]  value of gate i on truth-table row t
  o[m][v]  output m is driven by node v                          (exactly one per output)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from pysat.card import CardEnc, EncType
from pysat.formula import IDPool
from pysat.solvers import Solver

from .netlist import Netlist
from .spec import Spec, input_masks

INTERRUPTIBLE_SOLVERS = {"glucose4", "glucose3", "minisat22", "maplechrono", "lingeling"}


@dataclass
class SynthResult:
    spec: Spec
    netlists: list[Netlist]          # all optimal (or best-found) netlists collected
    lower_bound: int                 # proven: no circuit with fewer gates exists
    proven: bool                     # netlists[0] is proven minimal
    timed_out: list[int] = field(default_factory=list)  # budgets the solver gave up on
    seconds: float = 0.0
    source: str = "sat"              # "sat", "reference" or "cache"

    @property
    def best(self) -> Netlist | None:
        return self.netlists[0] if self.netlists else None

    @property
    def size(self) -> int | None:
        return self.best.size if self.best else None


class _Encoding:
    def __init__(self, spec: Spec, k: int, constants: tuple[str, ...], symmetry: bool):
        self.spec, self.k = spec, k
        self.sources = spec.inputs + constants
        self.ns = len(self.sources)
        self.pool = IDPool()
        self.clauses: list[list[int]] = []

        care_any = 0
        for c in spec.care:
            care_any |= c
        self.rows = [r for r in range(spec.n_rows) if (care_any >> r) & 1]

        masks = input_masks(len(spec.inputs))
        full = spec.full_mask
        self.source_vals = masks + [0 if c == "0" else full for c in constants]

        # Pair lists are prefixes of each other: gate i+1's pairs are gate i's pairs
        # plus those involving gate i's own node. The ordering constraint relies on this.
        self.pairs = []
        for i in range(k):
            top = self.ns + i
            self.pairs.append([(j, l) for l in range(top) for j in range(l + 1)])

        self._encode(symmetry)

    def var(self, *key) -> int:
        return self.pool.id(key)

    def val(self, node: int, t: int):
        """Literal for node's value on row t, or a Python bool for sources."""
        if node < self.ns:
            return bool((self.source_vals[node] >> t) & 1)
        return self.var("x", node - self.ns, t)

    def add(self, *lits):
        clause = []
        for lit in lits:
            if lit is True:
                return
            if lit is False:
                continue
            clause.append(lit)
        if not clause:
            clause = [self.var("false")]
            self.clauses.append([-clause[0]])
        self.clauses.append(clause)

    def exactly_one(self, lits: list[int]):
        if not lits:
            self.add()  # empty clause: unsatisfiable
            return
        cnf = CardEnc.equals(lits=lits, bound=1, vpool=self.pool, encoding=EncType.seqcounter)
        self.clauses.extend(cnf.clauses)

    @staticmethod
    def neg(lit):
        return (not lit) if isinstance(lit, bool) else -lit

    def _encode(self, symmetry: bool):
        spec, k, ns = self.spec, self.k, self.ns

        # Gate structure and semantics.
        for i in range(k):
            sel = [self.var("s", i, p) for p in range(len(self.pairs[i]))]
            self.exactly_one(sel)
            for p, (j, l) in enumerate(self.pairs[i]):
                s = sel[p]
                for t in self.rows:
                    x = self.var("x", i, t)
                    vj, vl = self.val(j, t), self.val(l, t)
                    # x == NAND(vj, vl)
                    self.add(-s, self.neg(vj), self.neg(vl), -x)
                    self.add(-s, vj, x)
                    if l != j:
                        self.add(-s, vl, x)

        # Output selection.
        for m in range(len(spec.outputs)):
            care, want = spec.care[m], spec.values[m]
            cands = []
            for v in range(ns):
                if not ((self.source_vals[v] ^ want) & care):
                    cands.append(v)
            cands.extend(range(ns, ns + k))
            olits = [self.var("o", m, v) for v in cands]
            self.exactly_one(olits)
            for v, o in zip(cands, olits):
                if v < ns:
                    continue
                for t in self.rows:
                    if (care >> t) & 1:
                        x = self.var("x", v - ns, t)
                        self.add(-o, x if (want >> t) & 1 else -x)

        if not symmetry:
            return

        # Every gate is used by a later gate or drives an output.
        for i in range(k):
            node = ns + i
            users = [self.var("o", m, node) for m in range(len(spec.outputs))]
            for i2 in range(i + 1, k):
                users += [self.var("s", i2, p) for p, (j, l) in enumerate(self.pairs[i2])
                          if node in (j, l)]
            self.add(*users)

        # Consecutive independent gates appear in strictly increasing pair order.
        # lt(i, q) <=> gate i's pair index < q.
        for i in range(k - 1):
            npairs = len(self.pairs[i])
            self.add(-self.var("lt", i, 0))
            for q in range(1, npairs + 1):
                self.add(-self.var("lt", i, q), self.var("lt", i, q - 1), self.var("s", i, q - 1))
            for q in range(npairs):  # pairs of gate i+1 that don't use gate i
                self.add(-self.var("s", i + 1, q), self.var("lt", i, q))

        # Redundancies never present in a minimum circuit: two gates reading the same
        # pair, inverting an inverter, and nand(x, not x) - a constant 1, only ever
        # useful to drive a constant output.
        constant_output = any(not (v & c) or (v & c) == c for v, c in zip(spec.values, spec.care))
        for i in range(k):
            for i2 in range(i + 1, k):
                for p in range(len(self.pairs[i])):
                    self.add(-self.var("s", i, p), -self.var("s", i2, p))
        for j in range(k):
            nj = ns + j
            for a in range(nj):
                inv = self.var("s", j, self.pair_index(a, a))
                for i in range(j + 1, k):
                    self.add(-inv, -self.var("s", i, self.pair_index(nj, nj)))
                    if not constant_output:
                        self.add(-inv, -self.var("s", i, self.pair_index(a, nj)))

    @staticmethod
    def pair_index(j: int, l: int) -> int:
        """Index of pair (j, l), j <= l, in the gate pair lists."""
        if j > l:
            j, l = l, j
        return l * (l + 1) // 2 + j

    def decode(self, model: list[int]) -> Netlist:
        true = {v for v in model if v > 0}
        gates = []
        for i in range(self.k):
            for p, pair in enumerate(self.pairs[i]):
                if self.var("s", i, p) in true:
                    gates.append(pair)
                    break
        outputs = []
        for m in range(len(self.spec.outputs)):
            for v in range(self.ns + self.k):
                key = ("o", m, v)
                if key in self.pool.obj2id and self.pool.obj2id[key] in true:
                    outputs.append(v)
                    break
        return Netlist(self.sources, gates, tuple(outputs), self.spec.outputs)

    def blocking_clause(self, net: Netlist) -> list[int]:
        lits = [-self.var("s", i, self.pair_index(*g)) for i, g in enumerate(net.gates)]
        lits += [-self.var("o", m, v) for m, v in enumerate(net.outputs)]
        return lits


def lower_bound(spec: Spec, constants: tuple[str, ...] = ()) -> int:
    """Trivial bound: each distinct output that isn't a source needs its own gate."""
    srcs = input_masks(len(spec.inputs)) + [0 if c == "0" else spec.full_mask for c in constants]
    needed = []
    for want, care in zip(spec.values, spec.care):
        if any(not ((s ^ want) & care) for s in srcs):
            continue
        needed.append((want & care, care))
    if not needed:
        return 0
    if all(c == spec.full_mask for _, c in needed):
        return len(set(needed))
    return 1


MAX_ENCODING = 3_000_000  # approximate clauses; larger budgets take too long just to build


def encoding_size(spec: Spec, k: int, constants: tuple[str, ...] = ()) -> int:
    """Rough clause count of the gate-semantics part of the encoding for budget k."""
    care_any = 0
    for c in spec.care:
        care_any |= c
    rows = bin(care_any).count("1")
    ns = len(spec.inputs) + len(constants)
    pairs = sum((ns + i) * (ns + i + 1) // 2 for i in range(k))
    return 3 * pairs * rows


def solve_exact(spec: Spec, k: int, *, constants: tuple[str, ...] = (), timeout: float | None = None,
                limit: int = 1, symmetry: bool = True, solver: str = "cadical195") -> list[Netlist] | None:
    """Find up to ``limit`` distinct circuits with exactly ``k`` gates.

    Returns a (possibly empty) list, or None if the solver timed out before
    deciding satisfiability.
    """
    enc = _Encoding(spec, k, constants, symmetry)
    if timeout is not None and solver not in INTERRUPTIBLE_SOLVERS:
        solver = "glucose4"
    found: list[Netlist] = []
    with Solver(name=solver, bootstrap_with=enc.clauses) as s:
        deadline = None if timeout is None else time.monotonic() + timeout
        while len(found) < limit:
            if deadline is None:
                ok = s.solve()
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return found or None
                timer = threading.Timer(remaining, s.interrupt)
                timer.start()
                try:
                    ok = s.solve_limited(expect_interrupt=True)
                finally:
                    timer.cancel()
                    s.clear_interrupt()
                if ok is None:
                    return found or None
            if not ok:
                break
            net = enc.decode(s.get_model())
            assert net.verify(spec), "SAT decode produced an incorrect circuit"
            found.append(net)
            s.add_clause(enc.blocking_clause(net))
    return found


def synthesize(spec: Spec, *, constants: tuple[str, ...] = (), max_gates: int = 64,
               timeout: float | None = None, time_limit: float | None = None,
               enumerate_limit: int = 1, reference: Netlist | None = None, symmetry: bool = True,
               progress: Callable[[str], None] | None = None) -> SynthResult:
    """Find a minimum circuit.

    Budgets k = lower bound, lower bound + 1, ... are tried in turn; the first
    satisfiable one is a proven optimum. ``timeout`` applies per budget. Once a budget
    times out, optimality can no longer be proven, so the search switches to looking
    for improvements below the best known circuit (``reference``, e.g. a textbook
    component design), working downwards; without a reference it carries on upwards.
    ``time_limit`` caps the whole search; when it runs out the best circuit so far
    is returned.
    """
    t0 = time.monotonic()
    deadline = None if time_limit is None else t0 + time_limit
    timed_out: list[int] = []

    def attempt(k: int) -> list[Netlist] | None:
        budget = timeout
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out.append(k)
                return None
            budget = remaining if budget is None else min(budget, remaining)
        if progress:
            progress(f"trying {k} gates")
        t1 = time.monotonic()
        res = solve_exact(spec, k, constants=constants, timeout=budget,
                          limit=enumerate_limit, symmetry=symmetry)
        if progress:
            status = "timeout" if res is None else ("SAT" if res else "UNSAT")
            progress(f"  {k} gates: {status} ({time.monotonic() - t1:.1f}s)")
        if res is None:
            timed_out.append(k)
        return res

    def result(nets, lb, proven, source="sat"):
        return SynthResult(spec, nets, lb, proven, timed_out, time.monotonic() - t0, source)

    best_size = reference.size if reference is not None else max_gates + 1
    proven_lb = lower_bound(spec, constants)
    k = proven_lb
    while k < best_size:
        if encoding_size(spec, k, constants) > MAX_ENCODING:
            break
        res = attempt(k)
        if res is None:
            break
        if res:
            return result(res, k, True)
        proven_lb = k = k + 1
    else:
        if reference is not None:
            return result([reference], proven_lb, True, "reference")
        return result([], proven_lb, False)

    # Budget ``k`` is undecided, so optimality can't be proven any more. Keep climbing
    # towards the best known size: the first satisfiable budget is the smallest
    # circuit we can find, and small budgets keep the encodings cheap.
    for k in range(k + 1, best_size):
        if deadline is not None and time.monotonic() >= deadline:
            break
        if encoding_size(spec, k, constants) > MAX_ENCODING:
            break
        res = attempt(k)
        if res:
            return result(res, proven_lb, False)
    if reference is not None:
        return result([reference], proven_lb, False, "reference")
    return result([], proven_lb, False)
