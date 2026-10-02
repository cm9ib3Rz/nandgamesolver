# nandgamesolver

Finds circuits with the fewest possible NAND gates for the combinational levels of
[nandgame.com](https://nandgame.com/), then shows each one built from the components
unlocked by earlier levels (inverter, and, or, xor, half adder, full adder, selector,
switch).

It uses exact synthesis with a SAT solver: for a gate budget *k* it asks whether any
circuit of exactly *k* NANDs implements the truth table, trying *k* = 1, 2, 3, ... The
first budget that works is a proven minimum.

## Results

| Level | NANDs | Status | Game target |
|---|---|---|---|
| Invert | 1 | proven minimum | 1 |
| And | 2 | proven minimum | 2 |
| Or | 3 | proven minimum | 3 |
| Xor | 4 | proven minimum | 4 |
| Half Adder | 5 | proven minimum | 5 |
| Full Adder | 9 | proven minimum | 9 |
| Multi-bit Adder | 18 | best found (at least 13) | 18 |
| Equal to Zero | 10 | proven minimum | 10 |
| Selector | 4 | proven minimum | 4 |
| Switch | 4 | proven minimum | 4 |

Levels that work on 16-bit words in the game (Increment, Subtraction, Less than Zero,
Logic Unit, Arithmetic Unit, ALU, Condition) are solved here at 1 or 2 bits, because exact
synthesis does not scale to 16. Sequential levels (latches, flip-flops, RAM) are not
covered.

## Setup

Requires Python 3.10+.

```
pip install -e .[dev]
```

This installs [python-sat](https://pysathq.github.io/), which bundles the CaDiCaL and
Glucose solvers.

## Usage

```
python -m nandsolver list                      # levels, game targets, cached results
python -m nandsolver solve full-adder          # minimum circuit, as components and NANDs
python -m nandsolver solve alu --width 2       # word-sized levels take a bit width
python -m nandsolver solve xor --svg xor.svg   # also draw a diagram (--svg-raw for NANDs only)
python -m nandsolver solve-custom --inputs a,b,c --outputs y --expr "y = (a and b) or not c"
python -m nandsolver build-library             # solve every level and fill the cache
python -m nandsolver render-all                # diagrams for every level in diagrams/index.html
```

In `solve-custom` an expression may return `x` for a don't-care row.

Hard levels are bounded in time: `--timeout` (default 20 s) limits each gate budget and
`--time-limit` (default 120 s) the whole level. When a budget can't be decided in time,
the result is reported as "best found" with the proven lower bound, and the search
continues upward from there towards a known design built from earlier components. Use
`--timeout 0 --time-limit 0` to search without limits.

Proven results are cached in `.nandcache/`.

## How it works

- `spec.py`: truth tables with don't-cares.
- `synth.py`: the SAT encoding. Each gate selects a pair of earlier nodes; truth-table
  values are constrained per row. Symmetry breaking (every gate used, consecutive
  independent gates in order, no duplicate gates, no double inversion) keeps the
  unsatisfiable budgets fast enough to prove.
- `levels.py`: the level catalogue. Pin names, semantics and NAND targets were taken
  from the game's own level definitions.
- `rewrite.py`: matches the minimum netlist against every minimum implementation of
  each unlocked component, and picks the cover with the fewest parts. The NAND count never
  changes. A component is only used where its internal signals aren't needed elsewhere,
  so, for example, the 9-NAND full adder stays as plain NANDs.
- `diagram.py`: a dependency-free SVG renderer with a layered left-to-right layout.

## Tests

```
pytest
```
