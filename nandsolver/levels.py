"""The combinational nandgame.com levels, in game order.

Pin names, semantics and the game's own NAND targets were taken from the level
definitions in the nandgame.com client bundle (October 2026). Levels that work on
16-bit words in the game take a ``width`` here, because exact synthesis is only
feasible for small widths; their ``game_nands`` is therefore not comparable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .components import Builder, Component
from .spec import Spec

Ref = Callable[[Builder, int], dict[str, int]]


@dataclass(frozen=True)
class Level:
    key: str
    title: str
    group: str
    build_spec: Callable[[int], Spec]
    default_width: int | None = None   # None: fixed size as in the game
    game_nands: int | None = None      # the game's NAND target for this level
    component: str | None = None       # component name this level unlocks
    reference: Ref | None = None       # textbook design from earlier components
    note: str = ""

    @property
    def slug(self) -> str:
        return self.title.lower().replace(" ", "-")

    def spec(self, width: int | None = None) -> Spec:
        return self.build_spec(width or self.default_width or 0)


def bits(name: str, w: int) -> list[str]:
    """Bit names, most significant first: x2 x1 x0."""
    return [f"{name}{i}" for i in reversed(range(w))]


def to_int(bs) -> int:
    v = 0
    for b in bs:
        v = (v << 1) | b
    return v


def to_bits(v: int, w: int) -> tuple[int, ...]:
    return tuple((v >> i) & 1 for i in reversed(range(w)))


def signed(v: int, w: int) -> int:
    return v - (1 << w) if v >> (w - 1) else v


def fixed(name, inputs, outputs, fn) -> Callable[[int], Spec]:
    return lambda _w: Spec.from_function(name, inputs, outputs, fn)


# --- spec builders for word-sized levels ------------------------------------------

def _inc(w):
    return Spec.from_function(f"increment{w}", bits("x", w), bits("s", w),
                              lambda *x: to_bits(to_int(x) + 1, w))


def _sub(w):
    return Spec.from_function(f"subtraction{w}", bits("a", w) + bits("b", w), bits("d", w),
                              lambda *v: to_bits(to_int(v[:w]) - to_int(v[w:]), w))


def _sign(w):
    return Spec.from_function(f"less-than-zero{w}", bits("x", w), ["out"], lambda *x: x[0])


def _logic(op1, op0, x, y):
    return [x & y, x | y, x ^ y, ~x][op1 * 2 + op0]


def _arith(op1, op0, x, y):
    return [x + y, x + 1, x - y, x - 1][op1 * 2 + op0]


def _logic_unit(w):
    return Spec.from_function(
        f"logic-unit{w}", ["op1", "op0"] + bits("x", w) + bits("y", w), bits("r", w),
        lambda op1, op0, *v: to_bits(_logic(op1, op0, to_int(v[:w]), to_int(v[w:])) % (1 << w), w))


def _arith_unit(w):
    return Spec.from_function(
        f"arithmetic-unit{w}", ["op1", "op0"] + bits("x", w) + bits("y", w), bits("r", w),
        lambda op1, op0, *v: to_bits(_arith(op1, op0, to_int(v[:w]), to_int(v[w:])) % (1 << w), w))


def _alu(w):
    def f(u, op1, op0, zx, sw, *v):
        x, y = to_int(v[:w]), to_int(v[w:])
        if sw:
            x, y = y, x
        if zx:
            x = 0
        r = (_arith if u else _logic)(op1, op0, x, y)
        return to_bits(r % (1 << w), w)
    return Spec.from_function(f"alu{w}", ["u", "op1", "op0", "zx", "sw"] + bits("x", w) + bits("y", w),
                              bits("r", w), f)


def _condition(w):
    def f(lt, eq, gt, *x):
        v = signed(to_int(x), w)
        return int((lt and v < 0) or (eq and v == 0) or (gt and v > 0))
    return Spec.from_function(f"condition{w}", ["lt", "eq", "gt"] + bits("x", w), ["out"], f)


# --- reference ("obvious") designs built from earlier components ------------------

def _ref_xor(b, _w):
    return {"out": b.use("and", b.use("or", b["a"], b["b"]), b.nand(b["a"], b["b"]))}


def _ref_halfadd(b, _w):
    return {"h": b.use("and", b["a"], b["b"]), "l": b.use("xor", b["a"], b["b"])}


def _ref_fulladd(b, _w):
    h1, l1 = b.use("halfadd", b["a"], b["b"])
    h2, l2 = b.use("halfadd", l1, b["c"])
    return {"h": b.use("or", h1, h2), "l": l2}


def _ref_add2(b, _w):
    c1, s0 = b.use("fulladd", b["a0"], b["b0"], b["c"])
    co, s1 = b.use("fulladd", b["a1"], b["b1"], c1)
    return {"cout": co, "s1": s1, "s0": s0}


def _ref_inc(b, w):
    out = {"s0": b.use("inv", b["x0"])}
    carry = b["x0"]
    for i in range(1, w):
        carry, out[f"s{i}"] = b.use("halfadd", b[f"x{i}"], carry)
    return out


def _ref_sub(b, w):
    # a - b = a + ~b + 1; the +1 is folded into bit 0's carry.
    out = {"d0": b.use("xor", b["a0"], b["b0"])}
    carry = b.use("or", b["a0"], b.use("inv", b["b0"]))
    for i in range(1, w):
        carry, out[f"d{i}"] = b.use("fulladd", b[f"a{i}"], b.use("inv", b[f"b{i}"]), carry)
    return out


def _ref_iszero(b, _w):
    any1 = b.use("or", b.use("or", b["b3"], b["b2"]), b.use("or", b["b1"], b["b0"]))
    return {"out": b.use("inv", any1)}


def _ref_mux(b, _w):
    hi = b.use("and", b["s"], b["d1"])
    lo = b.use("and", b.use("inv", b["s"]), b["d0"])
    return {"out": b.use("or", hi, lo)}


def _ref_demux(b, _w):
    return {"c1": b.use("and", b["s"], b["d"]), "c0": b.use("and", b.use("inv", b["s"]), b["d"])}


def _logic_bits(b, op1, op0, xs, ys):
    """Per bit: select(op1, select(op0, ~x, x^y), select(op0, x|y, x&y)). Bits LSB first."""
    out = []
    for x, y in zip(xs, ys):
        lo = b.use("select", op0, b.use("or", x, y), b.use("and", x, y))
        hi = b.use("select", op0, b.use("inv", x), b.use("xor", x, y))
        out.append(b.use("select", op1, hi, lo))
    return out


def _arith_bits(b, op1, op0, xs, ys):
    """x + (op0 ? 1 : y), or x - (op0 ? 1 : y) when op1, as x + (operand ^ op1) + op1."""
    nop0 = b.use("inv", op0)
    carry, out = op1, []
    for i, (x, y) in enumerate(zip(xs, ys)):
        operand = b.use("or", op0, y) if i == 0 else b.use("and", nop0, y)
        carry, s = b.use("fulladd", x, b.use("xor", operand, op1), carry)
        out.append(s)
    return out


def _word(b, name, w):
    return [b[f"{name}{i}"] for i in range(w)]


def _ref_logic_unit(b, w):
    rs = _logic_bits(b, b["op1"], b["op0"], _word(b, "x", w), _word(b, "y", w))
    return {f"r{i}": r for i, r in enumerate(rs)}


def _ref_arith_unit(b, w):
    rs = _arith_bits(b, b["op1"], b["op0"], _word(b, "x", w), _word(b, "y", w))
    return {f"r{i}": r for i, r in enumerate(rs)}


def _ref_alu(b, w):
    xs, ys = _word(b, "x", w), _word(b, "y", w)
    left = [b.use("select", b["sw"], y, x) for x, y in zip(xs, ys)]
    right = [b.use("select", b["sw"], x, y) for x, y in zip(xs, ys)]
    nzx = b.use("inv", b["zx"])
    left = [b.use("and", nzx, x) for x in left]
    logic = _logic_bits(b, b["op1"], b["op0"], left, right)
    arith = _arith_bits(b, b["op1"], b["op0"], left, right)
    return {f"r{i}": b.use("select", b["u"], a, l) for i, (a, l) in enumerate(zip(arith, logic))}


def _ref_condition(b, w):
    xs = _word(b, "x", w)
    neg = xs[-1]
    nonzero = xs[0]
    for x in xs[1:]:
        nonzero = b.use("or", nonzero, x)
    zero = b.use("inv", nonzero)
    pos = b.use("inv", b.use("or", neg, zero))
    hit = b.use("or", b.use("and", b["lt"], neg), b.use("and", b["eq"], zero))
    return {"out": b.use("or", hit, b.use("and", b["gt"], pos))}


LEVELS: list[Level] = [
    Level("INV", "Invert", "Logic Gates", fixed("invert", ["a"], ["out"], lambda a: 1 - a),
          game_nands=1, component="inv"),
    Level("AND", "And", "Logic Gates", fixed("and", ["a", "b"], ["out"], lambda a, b: a & b),
          game_nands=2, component="and",
          reference=lambda b, w: {"out": b.use("inv", b.nand(b["a"], b["b"]))}),
    Level("OR", "Or", "Logic Gates", fixed("or", ["a", "b"], ["out"], lambda a, b: a | b),
          game_nands=3, component="or",
          reference=lambda b, w: {"out": b.nand(b.use("inv", b["a"]), b.use("inv", b["b"]))}),
    Level("XOR", "Xor", "Logic Gates", fixed("xor", ["a", "b"], ["out"], lambda a, b: a ^ b),
          game_nands=4, component="xor", reference=_ref_xor),
    Level("HALFADD", "Half Adder", "Arithmetics",
          fixed("half-adder", ["a", "b"], ["h", "l"], lambda a, b: divmod(a + b, 2)),
          game_nands=5, component="halfadd", reference=_ref_halfadd),
    Level("FULLADD", "Full Adder", "Arithmetics",
          fixed("full-adder", ["a", "b", "c"], ["h", "l"], lambda a, b, c: divmod(a + b + c, 2)),
          game_nands=9, component="fulladd", reference=_ref_fulladd),
    Level("ADD2", "Multi-bit Adder", "Arithmetics",
          fixed("multi-bit-adder", ["a1", "a0", "b1", "b0", "c"], ["cout", "s1", "s0"],
                lambda a1, a0, b1, b0, c: to_bits(2 * a1 + a0 + 2 * b1 + b0 + c, 3)),
          game_nands=18, reference=_ref_add2,
          note="output carry is named 'cout' here (the game calls both carries 'c')"),
    Level("INC", "Increment", "Arithmetics", _inc, default_width=2, reference=_ref_inc,
          note="16-bit in the game"),
    Level("SUB", "Subtraction", "Arithmetics", _sub, default_width=2, reference=_ref_sub,
          note="16-bit in the game"),
    Level("ISZERO", "Equal to Zero", "Arithmetics",
          fixed("equal-to-zero", ["b3", "b2", "b1", "b0"], ["out"], lambda *v: int(not any(v))),
          game_nands=10, reference=_ref_iszero),
    Level("SIGN", "Less than Zero", "Arithmetics", _sign, default_width=2,
          note="16-bit in the game; the answer is just the sign bit"),
    Level("MULTIPLEXER", "Selector", "Switching",
          fixed("selector", ["s", "d1", "d0"], ["out"], lambda s, d1, d0: d1 if s else d0),
          game_nands=4, component="select", reference=_ref_mux),
    Level("DEMUX", "Switch", "Switching",
          fixed("switch", ["s", "d"], ["c1", "c0"], lambda s, d: (s & d, (1 - s) & d)),
          game_nands=4, component="switch", reference=_ref_demux),
    Level("ALU_LOGIC", "Logic Unit", "Arithmetic Logic Unit", _logic_unit, default_width=1,
          reference=_ref_logic_unit, note="16-bit in the game"),
    Level("ALU_ARITHMETIC", "Arithmetic Unit", "Arithmetic Logic Unit", _arith_unit, default_width=1,
          reference=_ref_arith_unit, note="16-bit in the game"),
    Level("ALU2", "ALU", "Arithmetic Logic Unit", _alu, default_width=1, reference=_ref_alu,
          note="16-bit in the game"),
    Level("CONDITION", "Condition", "Arithmetic Logic Unit", _condition, default_width=2,
          reference=_ref_condition, note="16-bit in the game"),
]

BY_NAME = {}
for _lv in LEVELS:
    for _n in (_lv.key, _lv.slug, _lv.title.lower()):
        BY_NAME[_n.lower()] = _lv
BY_NAME.update({"inverter": LEVELS[0], "half-adder": LEVELS[4], "full-adder": LEVELS[5],
                "mux": LEVELS[11], "demux": LEVELS[12], "is-zero": LEVELS[9]})

COMPONENTS: dict[str, Component] = {
    lv.component: Component(lv.component, lv.key, lv.spec()) for lv in LEVELS if lv.component
}


def find(name: str) -> Level:
    try:
        return BY_NAME[name.lower()]
    except KeyError:
        raise KeyError(f"unknown level {name!r}; try one of: "
                       + ", ".join(lv.slug for lv in LEVELS)) from None


def components_before(level: Level) -> list[str]:
    """Components unlocked by levels earlier in the game than ``level``."""
    names = []
    for lv in LEVELS:
        if lv is level:
            break
        if lv.component:
            names.append(lv.component)
    return names
