from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.api import build_cell_spec_library_rdf, query_library_cell_specs, save_library_cell_spec
from battinfo.validate.pydantic import validate_json


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_alpha_detailed_descriptor_matrix_validates_builds_and_queries(tmp_path: Path) -> None:
    examples_dir = ROOT / "examples" / "cell-spec" / "research"
    example_names = [
        "alpha-coin-detailed.example.json",
        "alpha-cylindrical-detailed.example.json",
        "alpha-pouch-single-layer-detailed.example.json",
        "alpha-pouch-multilayer-detailed.example.json",
        "alpha-prismatic-detailed.example.json",
    ]

    library_root = tmp_path / "library" / "cell-spec"
    package_root = tmp_path / "package" / "cell-spec"
    rdf_root = tmp_path / "library-rdf" / "cell-spec"
    aggregate_jsonld = tmp_path / "ontology" / "library" / "cell-spec.jsonld"
    manifest_json = tmp_path / "library-rdf" / "cell-spec.index.json"

    for example_name in example_names:
        record = _load_json(examples_dir / example_name)
        result = validate_json(record, profile="cell-spec")
        assert result.ok, f"{example_name} failed validation: {result.errors}"

        payload = save_library_cell_spec(
            record,
            library_root=library_root,
            package_root=package_root,
        )
        assert payload["status"] == "created"

    build_result = build_cell_spec_library_rdf(
        input_dir=library_root,
        output_jsonld_dir=rdf_root,
        aggregate_jsonld=aggregate_jsonld,
        manifest_json=manifest_json,
    )
    assert build_result["status"] == "ok"
    assert build_result["entry_count"] == 5
    assert aggregate_jsonld.exists()
    assert manifest_json.exists()

    coin_rows = query_library_cell_specs(directory=library_root, format="coin")
    assert len(coin_rows) == 1
    assert coin_rows[0]["construction"]["assembly_type"] == "stacked"

    cylindrical_rows = query_library_cell_specs(directory=library_root, format="cylindrical")
    assert len(cylindrical_rows) == 1
    assert cylindrical_rows[0]["construction"]["assembly_type"] == "wound"

    pouch_rows = query_library_cell_specs(directory=library_root, format="pouch")
    assert len(pouch_rows) == 2
    pouch_layerings = {row["construction"]["layering"] for row in pouch_rows}
    assert pouch_layerings == {"single_layer", "multilayer"}

    prismatic_rows = query_library_cell_specs(directory=library_root, format="prismatic")
    assert len(prismatic_rows) == 1
    assert prismatic_rows[0]["construction"]["layer_count"] == 24





