"""Every schema-declared record link is a validation DECISION, not an accident.

The 0.8.0 review's F6 class of defect — reference fields that strict
validation silently ignored — existed because the validated links were a hand
list with no gate against the schemas. This inventory closes that hole: it
scans every record schema for fields typed as record-IRI references and
requires each to be either validated by ``battinfo.validate.references`` or
exempted HERE with a stated reason. Adding a link field to a schema now fails
this test until someone decides which it is.

The expected sets are authored here, independently of references.py, on
purpose: a generator must not certify itself (review §2).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SCHEMAS = ROOT / "src" / "battinfo" / "data" / "schemas"

# Fields whose $ref names one of these $defs are record links. Bare *Iri defs
# that identify the record ITSELF (the ``id`` field) are excluded per-field.
_IRI_DEF = re.compile(r"#/\$defs/\w+Iri$")

# Links that strict reference validation resolves against source_root today
# (validate/references.py — the per-kind spec_ref_field registry mechanism
# plus the explicit blocks).
VALIDATED: set[tuple[str, str]] = {
    ("cell-instance.schema.json", "cell_spec_id"),
    ("cell-instance.schema.json", "working_electrode_id"),
    ("cell-instance.schema.json", "counter_electrode_id"),
    ("cell-spec.schema.json", "positive_electrode_spec_id"),
    ("cell-spec.schema.json", "negative_electrode_spec_id"),
    ("cell-spec.schema.json", "working_electrode_spec_id"),
    ("cell-spec.schema.json", "counter_electrode_spec_id"),
    ("cell-spec.schema.json", "reference_electrode_spec_id"),
    ("cell-spec.schema.json", "electrolyte_spec_id"),
    ("cell-spec.schema.json", "separator_spec_id"),
    ("cell-spec.schema.json", "housing_spec_id"),
    ("channel.schema.json", "equipment_id"),
    ("current-collector.schema.json", "current_collector_spec_id"),
    ("electrode.schema.json", "electrode_spec_id"),
    ("electrode-spec.schema.json", "active_material_spec_id"),
    ("electrolyte.schema.json", "electrolyte_spec_id"),
    ("equipment.schema.json", "equipment_spec_id"),
    ("housing.schema.json", "housing_spec_id"),
    ("material.schema.json", "material_spec_id"),
    ("separator.schema.json", "separator_spec_id"),
    ("test.schema.json", "cell_id"),
    ("test.schema.json", "protocol_id"),
    ("test.schema.json", "equipment_id"),
    ("test.schema.json", "channel_id"),
    ("test.schema.json", "dataset_ids"),
}

# Links deliberately NOT resolved against source_root — each with the reason.
# Moving a row out of here requires adding the validation and its tests.
EXEMPT: dict[tuple[str, str], str] = {
    ("cell-instance.schema.json", "supersedes"): (
        "lineage pointer — the superseded record may be retired or archived "
        "outside the current source_root by design"
    ),
    ("dataset.schema.json", "series_id"): (
        "dataset-series backlink — the collection record is published in the "
        "same batch and checked by the series emitter, and a member may cite "
        "a series archived elsewhere"
    ),
    ("electrode.schema.json", "parent_id"): (
        "component-hierarchy pointer within a build; cross-record resolution "
        "deferred (0.9 candidate — promote to VALIDATED with tests)"
    ),
    ("organization.schema.json", "parentOrganization"): (
        "organization tree may reference a parent org that has no record "
        "(publishing a subsidiary must not require describing the parent)"
    ),
    ("organization.schema.json", "parent_organization"): (
        "snake_case canon of parentOrganization — same reason"
    ),
    ("parameter-set.schema.json", "material_spec_id"): (
        "claim target — claims may target specs published elsewhere; targets "
        "are resolved by the downstream resolve cascade, not save-time "
        "reference validation"
    ),
    ("parameter-set.schema.json", "cell_spec_id"): (
        "claim target — same policy as material_spec_id"
    ),
    **{
        ("parameter-set.schema.json", block): (
            "parameterisation-set membership — resolved and error-checked by "
            "load_parameter_set_members(), which raises on a missing member"
        )
        for block in (
            "negative_material", "negative_electrode", "positive_material",
            "positive_electrode", "separator", "electrolyte",
        )
    },
    ("parameter-set.schema.json", "set_id"): (
        "member backlink of the parameterisation set — the set record is "
        "minted in the same import and carried alongside its members"
    ),
}


def _schema_link_fields() -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for schema_file in sorted(SCHEMAS.glob("*.schema.json")):
        doc = json.loads(schema_file.read_text(encoding="utf-8"))

        def walk(node, field: str | None):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str) and _IRI_DEF.search(ref) and field and field != "id":
                    found.add((schema_file.name, field))
                for key, value in node.items():
                    if key == "properties" and isinstance(value, dict):
                        for prop_name, prop_schema in value.items():
                            walk(prop_schema, prop_name)
                    elif key in ("items", "anyOf", "oneOf", "allOf", "$defs", "definitions"):
                        walk(value, field)
            elif isinstance(node, list):
                for item in node:
                    walk(item, field)

        # Top-level record keys (cell_spec, test, ...) nest their own
        # properties; wrapping the root makes the walker treat both levels
        # uniformly.
        walk({"properties": doc.get("properties", {})}, None)
    return found


def test_every_schema_link_field_is_validated_or_exempted() -> None:
    links = _schema_link_fields()
    # The record's own `id` and the members' inner keys collapse onto their
    # carrying field, so the scan yields carrying-field granularity.
    assert len(links) > 20, f"schema scan looks broken: {sorted(links)}"

    undecided = links - VALIDATED - set(EXEMPT)
    assert not undecided, (
        "schema-declared record links with no validation decision "
        "(add to references.py + VALIDATED, or EXEMPT with a reason): "
        f"{sorted(undecided)}"
    )

    phantom = (VALIDATED | set(EXEMPT)) - links
    assert not phantom, f"decisions for links no schema declares: {sorted(phantom)}"

    both = VALIDATED & set(EXEMPT)
    assert not both, f"links both validated and exempt: {sorted(both)}"
