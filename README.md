# nandgamesolver

Finds circuits with the fewest possible NAND gates for the combinational levels of
[nandgame.com](https://nandgame.com/), then shows each one built from the components
unlocked by earlier levels (inverter, and, or, xor, half adder, full adder, selector,
switch).

**Gallery:** every solution drawn as a circuit diagram, at
<https://cm9ib3rz.github.io/nandgamesolver/>.

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
| Multi-bit Adder | 18 | best found (proven at least 13) | 18 |
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
python -m nandsolver render-all                # rebuild the gallery in gallery/
```

In `solve-custom` an expression may return `x` for a don't-care row.

Hard levels are bounded in time: `--timeout` (default 20 s) limits each gate budget and
`--time-limit` (default 120 s) the whole level. When a budget can't be decided in time,
the result is reported as "best found" with the proven lower bound, and the search
continues upward from there towards a known design built from earlier components. Use
`--timeout 0 --time-limit 0` to search without limits.

Proven results are cached in `.nandcache/`.

The gallery in `gallery/` is committed and published to GitHub Pages by
`.github/workflows/pages.yml` on every push to `main` (after the tests pass). It is not
rebuilt in CI, so run `render-all` and commit `gallery/` to update it.

## SAT solvers, and how this uses one

### What a SAT solver is

SAT is the Boolean satisfiability problem: given a formula over true/false variables,
is there an assignment of values that makes it true? A
[SAT solver](https://en.wikipedia.org/wiki/SAT_solver) is a program that answers this.
Solvers take the formula in
*conjunctive normal form* (CNF), a list of clauses that must all hold, where each clause
is an OR of variables or their negations:

```
(x1 OR NOT x2) AND (x2 OR x3) AND (NOT x1 OR NOT x3)
```

A SAT solver either returns an assignment that satisfies every clause (**SAT**) or
reports that none exists (**UNSAT**). An UNSAT answer is a proof: the solver has ruled out
every possible assignment, without trying them one by one. SAT is NP-complete, so some
inputs are intractable. But modern CDCL (conflict-driven clause learning) solvers
routinely handle problems with millions of clauses. They learn a new clause from each
dead end, so the same mistake is never explored twice.

### Which solver

The solvers come from [PySAT](https://pysathq.github.io/) (`python-sat`), a Python
wrapper around several C/C++ solvers:

- **CaDiCaL 1.9.5** is the default, used when there is no time limit. It is one of the
  strongest current solvers.
- **Glucose 4** is used when a time limit is set, because PySAT can interrupt a running
  Glucose search but not a CaDiCaL one.

On the problems here the two perform about the same.

### How it finds a minimum circuit

The question "is there a circuit of exactly *k* NAND gates that computes this truth
table?" is written as CNF (`synth.py`, after Kojevnikov, Kulikov and Yaroslavtsev, and
Knuth, TAOCP 7.1.2):

- **Wiring variables.** For each gate *i* and each pair of earlier signals (*j*, *l*),
  one variable means "gate *i* is NAND(*j*, *l*)". Exactly one pair is chosen per gate. A
  pair with *j* = *l* is an inverter.
- **Value variables.** For each gate and each row of the truth table, one variable holds
  the gate's output on that row. Clauses tie it to the chosen inputs: if gate *i* is
  NAND(*j*, *l*), then on every row its value is NOT(*j* AND *l*).
- **Output variables.** Each output pin is connected to exactly one signal (an input or a
  gate), whose value must equal the spec on every row it cares about. Don't-care rows are
  left out entirely.
- **Symmetry breaking.** Many different variable assignments describe the same circuit,
  for example by numbering independent gates in a different order. Extra clauses rule out
  these duplicates, and also gates that can never appear in a minimum circuit (unused
  gates, two identical gates, NOT(NOT *x*)). They don't change the answer, but they make
  UNSAT proofs much faster.

The solver is asked this for *k* = lower bound, then *k* + 1, and so on:

- **UNSAT** proves that no circuit with *k* gates exists.
- **SAT** comes with a model: the true wiring variables *are* the circuit. It is
  decoded and checked against the truth table.

The first SAT answer is therefore a proven minimum. Asking again with a clause blocking
the circuit already found yields other optimal circuits. The component rewrite step uses
these alternatives to find the most readable one.

The UNSAT answers are what take time. The Full Adder's 9 gates are found and proven
optimal in under a second. For the 2-bit adder, ruling out 12 gates takes about 15
seconds, and 13 to 17 gates could not be ruled out within the default time limits. That's
why some levels are reported as "best found" with a proven lower bound rather than as a
proven minimum.

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
- `gallery.py`: the HTML gallery page.

## Tests

```
pytest
```
