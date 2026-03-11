# Domain-Battery Semantic Mapping (Draft)

This folder holds BattINFO semantic mapping artifacts for quantitative properties.

Principles:

- Human-authored canonical JSON remains simple (no ontology IRIs required in records).
- Ontology IRIs are resolved through mapping artifacts owned by tooling.
- JSON-LD/RDF export is deterministic from canonical JSON + mapping tables.

Artifacts:

- `property_map.curated.json`: reviewed/approved property-key to ontology-class mapping.
- `unit_map.curated.json`: reviewed/approved unit-symbol to ontology-unit mapping.
- `property_map.candidates.json`: auto-generated mapping candidates.
- `unit_map.candidates.json`: auto-generated unit candidates.
- `quantitative_mapping_report.md`: generation summary for review.

Generate first-pass candidates:

```bash
python .tools/semantic/generate_semantic_mapping_candidates.py \
  --ontology https://w3id.org/emmo/domain/battery/inferred \
  --sample-json assets/examples/cell-types/A123__ANR26650M1-B.json \
  --out-dir assets/mappings/domain-battery \
  --overwrite
```

