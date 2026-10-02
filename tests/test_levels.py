import pytest

from nandsolver import levels
from nandsolver.cache import Cache
from nandsolver.components import Builder, Library


@pytest.fixture(scope="module")
def lib():
    return Library(levels.COMPONENTS, Cache(None))


@pytest.mark.parametrize("lv", [lv for lv in levels.LEVELS if lv.reference], ids=lambda lv: lv.slug)
@pytest.mark.parametrize("width", [1, 2, 3])
def test_reference_designs_meet_spec(lib, lv, width):
    if not lv.default_width and width > 1:
        pytest.skip("fixed size")
    spec = lv.spec(width)
    b = Builder(lib, spec)
    assert b.build(lv.reference(b, width)).verify(spec)


def test_lookup_by_various_names():
    assert levels.find("full-adder") is levels.find("FULLADD") is levels.find("Full Adder")
    with pytest.raises(KeyError):
        levels.find("nope")


def test_components_unlock_in_game_order():
    assert levels.components_before(levels.find("xor")) == ["inv", "and", "or"]
    assert "halfadd" in levels.components_before(levels.find("full-adder"))
    assert "select" not in levels.components_before(levels.find("selector"))


def test_alu_semantics_samples():
    spec = levels.find("alu").spec(2)
    names = spec.inputs

    def run(**kw):
        r = 0
        for nm in names:
            r = (r << 1) | kw.get(nm, 0)
        return tuple(spec.output_bit(m, r) for m in range(len(spec.outputs)))

    # u=1 op1=1 op0=0: X - Y with X=1 (01), Y=2 (10): -1 -> 11
    assert run(u=1, op1=1, x0=1, y1=1) == (1, 1)
    # sw swaps operands: Y - X = 2 - 1 = 1
    assert run(u=1, op1=1, sw=1, x0=1, y1=1) == (0, 1)
    # zx zeroes the left operand: 0 - Y = -2 -> 10
    assert run(u=1, op1=1, zx=1, x0=1, y1=1) == (1, 0)
    # logic: invert X
    assert run(op1=1, op0=1, x0=1) == (1, 0)


def test_condition_semantics():
    spec = levels.find("condition").spec(2)
    # lt eq gt x1 x0 ; x = -2 (10): lt -> 1, gt -> 0
    assert spec.output_bit(0, 0b10010) == 1
    assert spec.output_bit(0, 0b00110) == 0
    assert spec.output_bit(0, 0b01000) == 1  # eq and x == 0
