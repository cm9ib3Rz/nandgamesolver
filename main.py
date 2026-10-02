"""PyCharm entry point; same as ``python -m nandsolver``. Edit the run configuration's
parameters to pass arguments, e.g. ``solve full-adder``."""
import sys

from nandsolver.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["list"]))
