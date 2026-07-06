"""The curated top-level namespace stays curated (R2-B / beta-hardening 4.1)."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402


def test_curated_surface_is_small_and_silent() -> None:
    assert len(battinfo.__all__) <= 35, (
        f"__all__ grew to {len(battinfo.__all__)} — additions to the curated surface "
        "are a deliberate decision, not a side effect"
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        for name in battinfo.__all__:
            getattr(battinfo, name)
    assert not caught, f"curated names must import silently: {[str(w.message)[:60] for w in caught]}"


def test_demoted_names_warn_and_resolve_identically() -> None:
    import battinfo.interop as interop

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        via_top = battinfo.__getattr__("from_bpx")
    assert via_top is interop.from_bpx
    assert any("battinfo.interop" in str(w.message) for w in caught)


def test_engine_is_demoted_with_the_one_workspace_message() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        engine = battinfo.__getattr__("Workspace")
    from battinfo._workspace import Workspace

    assert engine is Workspace
    assert any("workspace()" in str(w.message) for w in caught)


def test_component_wrappers_stay_reachable_with_a_pointer() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        wrapper = battinfo.__getattr__("create_separator_spec")
    from battinfo import api

    assert wrapper is api.create_separator_spec
    assert any("battinfo.api" in str(w.message) for w in caught)


def test_dir_advertises_the_full_reachable_surface() -> None:
    names = dir(battinfo)
    for expected in ("CellSpec", "workspace", "from_bpx", "Workspace", "create_electrode_spec"):
        assert expected in names
