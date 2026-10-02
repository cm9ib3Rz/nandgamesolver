import random

import pytest

from nandsolver.spec import Spec
from nandsolver.synth import solve_exact, synthesize

KNOWN = [
    ("inv", ["a"], ["out"], lambda a: 1 - a, 1),
    ("and", ["a", "b"], ["out"], lambda a, b: a & b, 2),
    ("or", ["a", "b"], ["out"], lambda a, b: a | b, 3),
    ("xor", ["a", "b"], ["out"], lambda a, b: a ^ b, 4),
    ("half", ["a", "b"], ["h", "l"], lambda a, b: divmod(a + b, 2), 5),
    ("mux", ["s", "d1", "d0"], ["out"], lambda s, d1, d0: d1 if s else d0, 4),
    ("demux", ["s", "d"], ["c1", "c0"], lambda s, d: (s & d, (1 - s) & d), 4),
    ("full", ["a", "b", "c"], ["h", "l"], lambda a, b, c: divmod(a + b + c, 2), 9),
]


@pytest.mark.parametrize("name,ins,outs,fn,size", KNOWN, ids=[k[0] for k in KNOWN])
def test_known_optima(name, ins, outs, fn, size):
    spec = Spec.from_function(name, ins, outs, fn)
    res = synthesize(spec)
    assert res.proven and res.size == size
    assert all(n.verify(spec) for n in res.netlists)
    # The budget below the optimum is genuinely unsatisfiable (also without symmetry breaking).
    assert solve_exact(spec, size - 1, symmetry=False) == []


def test_output_can_be_an_input():
    spec = Spec.from_function("wire", ["a", "b"], ["y", "z"], lambda a, b: (b, 1 - a))
    res = synthesize(spec)
    assert res.size == 1
    assert res.best.outputs[0] == 1


def test_dont_cares_are_exploited():
    # Fully specified this is XOR (4 NANDs); with row 00 free, nand(a, b) fits.
    xor = Spec.from_function("t", ["a", "b"], ["y"], lambda a, b: a ^ b)
    partial = Spec.from_function("t", ["a", "b"], ["y"], lambda a, b: None if a == b == 0 else a ^ b)
    assert synthesize(xor).size == 4
    assert synthesize(partial).size == 1


def test_constants_option():
    one = Spec.from_function("one", ["a"], ["y"], lambda a: 1)
    assert synthesize(one).size == 2          # nand(a, nand(a, a))
    assert synthesize(one, constants=("1",)).size == 0


def test_symmetry_breaking_preserves_optimum():
    rng = random.Random(7)
    for _ in range(12):
        table = rng.getrandbits(8)
        spec = Spec.from_function("r", ["a", "b", "c"], ["y"],
                                  lambda a, b, c, t=table: (t >> (a * 4 + b * 2 + c)) & 1)
        res = synthesize(spec)
        k = res.size
        assert res.proven
        if k > 0:
            assert solve_exact(spec, k - 1, symmetry=False) == []
        assert solve_exact(spec, k, symmetry=False)


def test_timeout_reports_unproven():
    spec = Spec.from_function("add2", ["a1", "a0", "b1", "b0", "c"], ["co", "s1", "s0"],
                              lambda a1, a0, b1, b0, c: tuple(((2*a1+a0+2*b1+b0+c) >> i) & 1 for i in (2, 1, 0)))
    res = synthesize(spec, timeout=0.01, max_gates=6)
    assert not res.proven and res.best is None


def test_time_limit_returns_reference():
    import time
    from nandsolver.netlist import Netlist
    spec = Spec.from_function("add2", ["a1", "a0", "b1", "b0", "c"], ["co", "s1", "s0"],
                              lambda a1, a0, b1, b0, c: tuple(((2*a1+a0+2*b1+b0+c) >> i) & 1 for i in (2, 1, 0)))
    # Ripple of two textbook full adders (9 NANDs each), as nandgame's reference.
    full = synthesize(Spec.from_function("f", ["a", "b", "c"], ["h", "l"],
                                         lambda a, b, c: divmod(a + b + c, 2))).best
    src = list(range(5))
    gates = []

    def place(ins):
        loc = list(ins)
        for a, b in full.gates:
            gates.append((loc[a], loc[b]))
            loc.append(5 + len(gates) - 1)
        return [loc[o] for o in full.outputs]
    c1, s0 = place([src[1], src[3], src[4]])
    co, s1 = place([src[0], src[2], c1])
    ref = Netlist(("a1", "a0", "b1", "b0", "c"), gates, (co, s1, s0), ("co", "s1", "s0"))
    assert ref.verify(spec)
    t0 = time.monotonic()
    res = synthesize(spec, reference=ref, time_limit=2)
    assert time.monotonic() - t0 < 10
    assert res.best.verify(spec) and res.size <= 18 and not res.proven
