import xml.etree.ElementTree as ET

import pytest

from nandsolver import levels
from nandsolver.cache import Cache
from nandsolver.components import Library
from nandsolver.diagram import render_svg
from nandsolver.rewrite import best_rewrite, rewrite


@pytest.fixture(scope="module")
def lib():
    return Library(levels.COMPONENTS, Cache(None))


@pytest.mark.parametrize("name", ["invert", "full-adder", "switch", "less-than-zero", "condition"])
def test_renders_valid_svg(lib, name):
    lv = levels.find(name)
    res = lib.solve(lv.spec(), enumerate_limit=5)
    rw = best_rewrite(res.netlists, lib, levels.components_before(lv))
    for view in (rw, rewrite(rw.netlist, lib, [])):
        root = ET.fromstring(render_svg(view, lib, lv.title, "subtitle"))
        assert root.tag.endswith("svg")
        texts = {t.text for t in root.iter() if t.tag.endswith("text")}
        assert set(lv.spec().inputs) <= texts and set(lv.spec().outputs) <= texts
