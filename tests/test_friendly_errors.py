"""Validation errors aggregate and teach (beta-hardening plan 2.3).

Save/publish used to surface only the FIRST schema error, phrased in canonical record
paths. Now: every error in one message, canonical paths translated back to the authoring
vocabulary (cell_spec.cell_format → format=), quantity-shape errors carry a
copy-pasteable example, and unknown-kwarg typos get a did-you-mean.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import _validate_canonical_record
from battinfo.bundle import CellSpecification, Dataset, Test

SPEC_IRI = "https://w3id.org/battinfo/spec/aaaa-aaaa-aaaa-aaaa"


def _bad_cell_spec_doc() -> dict:
    return {
        "schema_version": "0.2.0",
        "cell_spec": {
            "id": SPEC_IRI,
            "short_id": "aaaaaa",
            "name": "X",
            "manufacturer": {"type": "Organization", "name": "Acme"},
            "model": "X1",
            "cell_format": "not-a-real-format",   # enum error
            "chemistry": "LFP",
        },
        "properties": {"nominal_capacity": 2.5},   # bare number, not a quantity object
        "provenance": {},                           # missing required source_type
    }


def test_all_errors_surface_in_one_message() -> None:
    with pytest.raises(ValueError) as exc:
        _validate_canonical_record(_bad_cell_spec_doc())
    message = str(exc.value)
    # Previously only the first of these three appeared.
    assert "cell_format" in message
    assert "nominal_capacity" in message
    assert "source_type" in message
    assert "3 errors" in message


def test_canonical_paths_translate_to_authoring_kwargs() -> None:
    with pytest.raises(ValueError) as exc:
        _validate_canonical_record(_bad_cell_spec_doc())
    message = str(exc.value)
    assert "authoring field: format=" in message          # cell_spec.cell_format
    assert "authoring field: source_type=" in message     # provenance.'source_type' required


def test_quantity_shape_error_shows_example_and_command() -> None:
    with pytest.raises(ValueError) as exc:
        _validate_canonical_record(_bad_cell_spec_doc())
    message = str(exc.value)
    assert '"nominal_capacity": {"value": 0.0, "unit": "ah"}' in message
    assert "battinfo properties show nominal_capacity" in message


def test_required_error_path_names_the_missing_field() -> None:
    with pytest.raises(ValueError) as exc:
        _validate_canonical_record(_bad_cell_spec_doc())
    # "provenance: 'source_type' is a required property" reads as the parent object;
    # the rendered path points at the actual missing field.
    assert "provenance.source_type" in str(exc.value)


# ── did-you-mean on unknown kwargs (the manufacture= scenario) ─────────────────


def test_kwarg_typo_gets_a_did_you_mean() -> None:
    with pytest.raises(TypeError, match=r"manufacture=.*did you mean manufacturer=\?"):
        CellSpecification(manufacture="Acme", model_name="X", chemistry="LFP", format="cylindrical")


def test_spec_property_typo_gets_a_did_you_mean() -> None:
    with pytest.raises(TypeError, match=r"did you mean nominal_capacity=\?"):
        CellSpecification(
            manufacturer="Acme", model_name="X", chemistry="LFP", format="cylindrical",
            nominal_capacit={"value": 2.0, "unit": "Ah"},
        )


def test_absorbed_authoring_aliases_still_accepted() -> None:
    # The pre-flight check must not reject the flat authoring vocabulary that the
    # custom __init__s absorb (kind=, cell_id=, title=, notes=, source_type=, ...).
    test = Test(
        cell_id="https://w3id.org/battinfo/cell/bbbb-bbbb-bbbb-bbbb",
        name="T", kind="cycling", notes=["n"], source_type="lab",
    )
    assert test.test_type.value == "cycling"
    dataset = Dataset(title="D", access_url="https://x.example/d", source_type="other")
    assert dataset.name == "D"


def test_dataset_kwarg_typo_gets_a_did_you_mean() -> None:
    with pytest.raises(TypeError, match=r"acces_url=.*did you mean access_url=\?"):
        Dataset(title="D", acces_url="https://x.example/d")
