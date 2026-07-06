"""Deprecation shims for the retired *Input DTOs and the legacy publish call (3.6).

Downstream pinners upgrading across the consolidation get a DeprecationWarning
naming the replacement, not an ImportError. Shims last one release — see the
deprecation policy in CONTRIBUTING.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402

ALIASES = {
    "CellSpecificationInput": battinfo.CellSpecification,
    "CellInstanceInput": battinfo.CellInstance,
    "TestInput": battinfo.Test,
    "DatasetInput": battinfo.Dataset,
    "TestSpecInput": battinfo.TestSpec,
    "TestProtocolInput": battinfo.TestSpec,
}


@pytest.mark.parametrize("name", sorted(ALIASES))
def test_retired_input_names_resolve_with_a_deprecation_warning(name: str) -> None:
    with pytest.warns(DeprecationWarning, match=name):
        resolved = getattr(battinfo, name)
    assert resolved is ALIASES[name], "the shim must forward to the model itself"


def test_unknown_attribute_still_raises_attribute_error() -> None:
    with pytest.raises(AttributeError, match="no_such_thing"):
        battinfo.no_such_thing  # noqa: B018


def test_publish_is_the_function_and_the_submodule_is_gone() -> None:
    import importlib

    assert callable(battinfo.publish)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("battinfo.publish")


def test_legacy_publish_kwargs_shape_warns_and_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    from battinfo import _publish

    called: dict = {}

    def fake_legacy(**kwargs):
        called.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(_publish, "_legacy_publish", fake_legacy)
    with pytest.warns(DeprecationWarning, match="publish_publication_package"):
        result = battinfo.publish(cell_spec="spec-sentinel")
    assert result == {"ok": True}
    assert called == {"cell_spec": "spec-sentinel"}
