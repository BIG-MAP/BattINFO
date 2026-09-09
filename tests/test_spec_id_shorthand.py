"""The uniform authoring shorthand: every instance type accepts ``spec_id=``.

The record keeps its self-describing ``<type>_spec_id`` key; ``spec_id=`` is
the kwarg a person types. The prefixed kwarg stays accepted, and disagreeing
spellings are an error, never a silent pick.
"""
from __future__ import annotations

import pytest

import battinfo.api as api

SPEC = "https://w3id.org/battinfo/spec/abcd-2345-6789-abcd"


def test_material_accepts_spec_id() -> None:
    rec = api.create_material(spec_id=SPEC, name="Lot A", validate=False)
    assert rec["material"]["material_spec_id"] == SPEC


def test_electrode_accepts_spec_id() -> None:
    rec = api.create_electrode(spec_id=SPEC, batch_id="B1", validate=False)
    assert rec["electrode"]["electrode_spec_id"] == SPEC


def test_component_families_accept_both_spellings() -> None:
    short = api.create_component_instance("separator", spec_id=SPEC, name="S1", validate=False)
    long = api.create_component_instance("separator", separator_spec_id=SPEC, name="S1", validate=False)
    assert short["separator"]["separator_spec_id"] == SPEC
    assert long["separator"]["separator_spec_id"] == SPEC


def test_equipment_accepts_spec_id() -> None:
    rec = api.create_equipment(
        spec_id=SPEC, serial_number="SN-1", name="Cycler 1", validate=False
    )
    assert rec["equipment"]["equipment_spec_id"] == SPEC


def test_disagreeing_spellings_are_rejected() -> None:
    other = "https://w3id.org/battinfo/spec/ffff-2345-6789-abcd"
    with pytest.raises(ValueError, match="disagree"):
        api.create_component_instance(
            "separator", spec_id=SPEC, separator_spec_id=other, validate=False
        )
