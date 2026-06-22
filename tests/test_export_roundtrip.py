"""Regression tests: interop export/round-trip must not silently lose data
(audit theme E).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.interop.bpx import from_bpx, to_bpx  # noqa: E402
from battinfo.interop.converter import import_converter_jsonld_record  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "converter" / "coincell_reference_v3.jsonld"


def test_bpx_roundtrip_recovers_mass() -> None:
    spec = {
        "cell_spec": {"name": "X", "cell_format": "cylindrical"},
        "properties": {
            "nominal_capacity": {"value": 5.0, "unit": "Ah"},
            "mass": {"value": 48.0, "unit": "g"},
            "diameter": {"value": 21.0, "unit": "mm"},
            "height": {"value": 70.0, "unit": "mm"},
        },
    }
    back = from_bpx(to_bpx(spec).bpx)
    assert back.specs.get("mass") is not None
    assert abs(back.specs["mass"]["value"] - 48.0) < 0.01


def _bump_lifsi(node: object, value: float) -> None:
    if isinstance(node, dict):
        if node.get("@type") == "LithiumBisfluorosulfonylimide":
            node["hasMeasuredProperty"]["hasNumericalPart"]["hasNumberValue"] = value
        for v in node.values():
            _bump_lifsi(v, value)
    elif isinstance(node, list):
        for v in node:
            _bump_lifsi(v, value)


def test_converter_blended_salt_preserved_in_comment() -> None:
    src = json.loads(FIXTURE.read_text(encoding="utf-8"))
    blended = copy.deepcopy(src)
    _bump_lifsi(blended, 0.5)  # give the co-salt a real concentration

    electrolyte = import_converter_jsonld_record(blended).specification.to_json().get("electrolyte", {})
    comment = electrolyte.get("comment") or ""
    assert "LiFSI" in comment and "0.5" in comment  # the co-salt is not lost


def test_converter_zero_concentration_solute_adds_no_comment() -> None:
    # The shipped fixture's second solute is a 0 mol/L placeholder — it must not
    # pollute the electrolyte comment.
    src = json.loads(FIXTURE.read_text(encoding="utf-8"))
    electrolyte = import_converter_jsonld_record(src).specification.to_json().get("electrolyte", {})
    assert electrolyte.get("comment") is None
