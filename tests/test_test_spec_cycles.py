"""A test spec's ``cycles`` takes any whole number and refuses anything else.

``TestSpec(cycles=100)`` wraps the steps in one loop that runs them 100 times.
``cycles="100"``, ``100.0`` or ``numpy.int64(100)``, given to the model or held
in a test-spec draft, were dropped without a word, so the steps ran once.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import battinfo
from battinfo import api
from battinfo._workspace import Workspace
from battinfo.testmethod import parse_experiment

STEPS = ["Charge at 1 C until 4.2 V", "Discharge at 1 C until 2.5 V"]
WHOLE = [100, "100", " 100\n", 100.0]
NOT_WHOLE = [True, False, 2.5, "three", "1e2", "", "-3", float("nan")]


def _spec(cycles: object) -> battinfo.TestSpec:
    return battinfo.TestSpec(name="1C cycling", kind="cycling", experiment=STEPS, cycles=cycles)


def _loops(method: list) -> int | None:
    """The repeat count of a method that is one loop, else None."""
    if len(method) == 1 and method[0].mode == "group":
        assert type(method[0].count) is int
        return method[0].count
    return None


@pytest.mark.parametrize("cycles", WHOLE, ids=repr)
def test_a_whole_number_repeats_the_steps(cycles: object) -> None:
    assert _loops(_spec(cycles).method) == 100


def test_numpy_numbers_repeat_the_steps() -> None:
    np = pytest.importorskip("numpy")
    for cycles in (np.int64(100), np.int32(100), np.float64(100.0)):
        assert _loops(_spec(cycles).method) == 100


@pytest.mark.parametrize("cycles", NOT_WHOLE, ids=repr)
def test_anything_else_is_refused(cycles: object) -> None:
    with pytest.raises(ValueError, match="'cycles' must be a whole number") as caught:
        _spec(cycles)
    assert repr(cycles) in str(caught.value)


@pytest.mark.parametrize("cycles", [1, 0, -3])
def test_one_zero_and_negative_counts_run_the_steps_once(cycles: int) -> None:
    """As before: no loop, and no error."""
    assert _spec(cycles).method == parse_experiment(STEPS)


def test_an_int_gives_the_spec_it_gave_before() -> None:
    assert _spec(3).method == parse_experiment(STEPS, 3)
    assert _spec("3").model_dump() == _spec(3).model_dump()


def test_a_draft_reads_any_whole_number(tmp_path: Path) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    for i, cycles in enumerate((3, "100", 100.0)):
        draft = tmp_path / f"p{i}.test-spec.json"
        draft.write_text(
            json.dumps({"name": f"Cycling {i}", "type": "cycling", "steps": STEPS, "cycles": cycles}), encoding="utf-8"
        )
        assert _loops(ws.load(draft).method) == int(cycles)


@pytest.mark.parametrize("cycles", ["three", 2.5, True])
def test_a_draft_that_is_not_a_whole_number_is_not_loaded(tmp_path: Path, cycles: object) -> None:
    ws = battinfo.workspace(tmp_path, registry_url=None)
    draft = tmp_path / "cycling.test-spec.json"
    draft.write_text(
        json.dumps({"name": "Cycling", "type": "cycling", "steps": STEPS, "cycles": cycles}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cycling.test-spec.json: 'cycles' must be a whole number") as caught:
        ws.load(draft)
    assert f"not {cycles!r}. Nothing was loaded." in str(caught.value)
    assert ws._ws.test_specs == []


def test_an_authoring_payload_reads_cycles_the_same_way(tmp_path: Path) -> None:
    engine = Workspace(tmp_path)
    payload = {"name": "1C cycling", "kind": "cycling", "experiment": STEPS}
    assert _loops(engine.load_test_spec({**payload, "cycles": "100"}).method) == 100
    with pytest.raises(ValueError, match="'cycles' must be a whole number, such as 3, not 'three'"):
        engine.load_test_spec({**payload, "name": "Other", "cycles": "three"})


def test_cycles_does_not_move_the_iri(tmp_path: Path) -> None:
    ids = {
        repr(cycles): api.save_test_spec(_spec(cycles), source_root=tmp_path / str(i), build_html=False)["id"]
        for i, cycles in enumerate((100, "100", 100.0, None))
    }
    assert len(set(ids.values())) == 1, ids
