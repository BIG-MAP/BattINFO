"""Validate component and record examples against their schemas."""
from __future__ import annotations
import json
import pathlib
import referencing
import referencing.jsonschema
import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "assets" / "schemas"

EXAMPLES = [
    # component examples
    ("examples/components/lfp-positive-electrode.example.json",
     "https://w3id.org/battinfo/schema/modules/components/electrode.schema.json"),
    ("examples/components/graphite-negative-electrode.example.json",
     "https://w3id.org/battinfo/schema/modules/components/electrode.schema.json"),
    ("examples/components/lp30-organic-electrolyte.example.json",
     "https://w3id.org/battinfo/schema/modules/components/electrolyte.schema.json"),
    ("examples/components/celgard-2400-separator.example.json",
     "https://w3id.org/battinfo/schema/modules/components/separator.schema.json"),
    ("examples/components/aluminium-current-collector.example.json",
     "https://w3id.org/battinfo/schema/modules/components/current-collector.schema.json"),
    ("examples/components/lfp-active-material.example.json",
     "https://w3id.org/battinfo/schema/modules/components/material-component.schema.json"),
    # organization example
    ("examples/organization/SINTEF.json",
     "https://w3id.org/battinfo/schema/organization.schema.json"),
]


def build_registry() -> referencing.Registry:
    pairs = []
    for p in SCHEMA_DIR.rglob("*.schema.json"):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if "$id" in doc:
            resource = referencing.Resource(
                contents=doc,
                specification=referencing.jsonschema.DRAFT202012,
            )
            pairs.append((doc["$id"], resource))
    return referencing.Registry().with_resources(pairs)


def main() -> int:
    registry = build_registry()
    failed = 0
    for rel_path, schema_id in EXAMPLES:
        path = ROOT / rel_path
        doc = json.loads(path.read_text(encoding="utf-8"))
        stripped = {k: v for k, v in doc.items() if not k.startswith("_")}
        validator = jsonschema.Draft202012Validator({"$ref": schema_id}, registry=registry)
        errors = list(validator.iter_errors(stripped))
        if errors:
            print(f"ERR  {path.name}")
            for err in errors[:5]:
                print(f"     {err.json_path}: {err.message}")
            failed += 1
        else:
            print(f"OK   {path.name}")
    return failed


if __name__ == "__main__":
    raise SystemExit(main())
