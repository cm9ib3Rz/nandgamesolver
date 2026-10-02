"""On-disk JSON cache of solved specs, keyed by the spec's function hash."""
from __future__ import annotations

import json
import os
from pathlib import Path

from .netlist import Netlist
from .spec import Spec
from .synth import SynthResult

DEFAULT_DIR = Path(os.environ.get("NANDSOLVER_CACHE", Path(__file__).resolve().parent.parent / ".nandcache"))


class Cache:
    def __init__(self, directory: Path | str | None = DEFAULT_DIR):
        self.dir = Path(directory) if directory is not None else None

    def _path(self, spec: Spec, constants: tuple[str, ...]) -> Path:
        suffix = "".join(constants)
        return self.dir / f"{spec.key()}{'-' + suffix if suffix else ''}.json"

    def load(self, spec: Spec, constants: tuple[str, ...], want: int) -> SynthResult | None:
        """Return a cached proven result holding at least ``want`` netlists (or all of them)."""
        if self.dir is None:
            return None
        path = self._path(spec, constants)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if not data["proven"]:
            return None
        nets = [Netlist.from_dict(d) for d in data["netlists"]]
        if len(nets) < want and not data["complete"]:
            return None
        if not all(n.verify(spec) for n in nets):
            return None
        return SynthResult(spec, nets[:want], data["lower_bound"], True, [], 0.0, "cache")

    def store(self, result: SynthResult, constants: tuple[str, ...], requested: int):
        if self.dir is None or not result.proven or result.source == "cache":
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        data = {
            "name": result.spec.name,
            "proven": result.proven,
            "lower_bound": result.lower_bound,
            "complete": len(result.netlists) < requested,
            "netlists": [n.to_dict() for n in result.netlists],
        }
        self._path(result.spec, constants).write_text(json.dumps(data, indent=1))
