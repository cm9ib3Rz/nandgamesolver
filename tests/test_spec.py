from nandsolver.netlist import Netlist
from nandsolver.spec import Spec, input_masks


def test_input_masks_first_input_is_msb():
    a, b = input_masks(2)
    # rows 0..3 = (a,b) 00 01 10 11
    assert a == 0b1100
    assert b == 0b1010


def test_from_function_and_dont_cares():
    s = Spec.from_function("t", ["a", "b"], ["y"], lambda a, b: None if a and b else a | b)
    assert s.values == (0b0110,)
    assert s.care == (0b0111,)
    assert s.output_bit(0, 3) is None
    assert "x" in s.format_table()


def test_from_table_and_dict_results():
    s = Spec.from_table("t", ["a"], ["y", "z"], {(0,): (1, 0), (1,): (0, 1)})
    assert s.values == (0b01, 0b10)
    d = Spec.from_function("t", ["a"], ["y", "z"], lambda a: {"y": 1 - a, "z": a})
    assert d.values == s.values and d.key() == s.key()


def test_netlist_verify_and_prune():
    xor = Spec.from_function("xor", ["a", "b"], ["out"], lambda a, b: a ^ b)
    net = Netlist(("a", "b"), [(0, 1), (0, 2), (1, 2), (3, 4), (0, 0)], (5,), ("out",))
    assert net.verify(xor)
    pruned = net.pruned()
    assert pruned.size == 4 and pruned.verify(xor)
    bad = Netlist(("a", "b"), [(0, 1)], (2,), ("out",))
    assert not bad.verify(xor)
