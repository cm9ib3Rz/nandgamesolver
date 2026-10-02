import pytest

from nandsolver import levels
from nandsolver.cache import Cache
from nandsolver.components import Builder, Library
from nandsolver.netlist import Netlist
from nandsolver.rewrite import best_rewrite, rewrite


@pytest.fixture(scope="module")
def lib():
    return Library(levels.COMPONENTS, Cache(None))


def _flatten(rw, lib) -> Netlist:
    """Rebuild a NAND netlist from the parts, expanding components via their templates."""
    net = rw.netlist
    spec_like = type("S", (), {"inputs": net.sources, "outputs": net.output_names})
    b = Builder(lib, spec_like)
    node = {i: i for i in range(net.n_sources)}
    for p in rw.parts:
        ins = [node[i] for i in p.inputs]
        outs = (b.nand(*ins),) if p.kind == "nand" else b.use(p.kind, *ins)
        outs = outs if isinstance(outs, tuple) else (outs,)
        node.update(zip(p.outputs, outs))
    return b.build({nm: node[o] for o, nm in zip(net.outputs, net.output_names)})


def test_reference_full_adder_is_recognised(lib):
    lv = levels.find("full-adder")
    spec = lv.spec()
    b = Builder(lib, spec)
    ref = b.build(lv.reference(b, 0))
    rw = rewrite(ref, lib, levels.components_before(lv))
    assert rw.counts() == {"halfadd": 2, "or": 1}
    assert rw.nands == ref.size == 13
    assert rw.verify(spec, lib)


@pytest.mark.parametrize("name", ["half-adder", "full-adder", "selector", "switch", "is-zero"])
def test_rewrite_preserves_semantics(lib, name):
    lv = levels.find(name)
    spec = lv.spec()
    res = lib.solve(spec, enumerate_limit=10, timeout=60)
    if res.best is None:
        pytest.skip("solver timed out")
    rw = best_rewrite(res.netlists, lib, levels.components_before(lv))
    assert rw.nands == res.size
    assert rw.verify(spec, lib)
    assert _flatten(rw, lib).verify(spec)


def test_internal_fanout_blocks_match(lib):
    # and(a, b) whose inner nand is also an output must not become an "and" component.
    net = Netlist(("a", "b"), [(0, 1), (2, 2)], (3, 2), ("y", "n"))
    rw = rewrite(net, lib, ["inv", "and"])
    assert rw.counts() == {"nand": 1, "inv": 1}


def test_non_convex_match_rejected(lib):
    # g0 = nand(a,b); g1 = nand(g0,g0) [inv]; g2 = nand(g0, g1) - an "and" (g0,g1) would be
    # fine, but a template spanning g0 and g2 while g1 sits between them must be rejected.
    net = Netlist(("a", "b"), [(0, 1), (2, 2), (2, 3)], (4,), ("y",))
    for p in rewrite(net, lib, ["inv", "and", "or", "xor"]).parts:
        gates = set(p.outputs)
        assert not ({2, 4} <= gates and 3 not in gates)
