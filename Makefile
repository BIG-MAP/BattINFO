PYTHON := .venv/Scripts/python
SCHEMA := schema/battinfo.yaml
CONTEXT_OUT := src/battinfo/data/context/records.context.json

.PHONY: gen-all gen-context gen-pydantic check-freshness help

help:
	@echo "Targets:"
	@echo "  gen-all          Run all generators (context)"
	@echo "  gen-context      Assemble records.context.json from schema/*.yaml"
	@echo "  gen-pydantic     Generate Pydantic models from LinkML YAML (Phase 2)"
	@echo "  check-freshness  Exit non-zero if records.context.json is stale"

gen-all: gen-context

gen-context:
	$(PYTHON) scripts/assemble_context.py
	@echo "Context written to $(CONTEXT_OUT)"

gen-pydantic:
	@echo "Generating Pydantic models (Phase 2 — overwrites src/battinfo/bundle.py)"
	.venv/Scripts/gen-pydantic --pydantic-version 2 $(SCHEMA) \
		> src/battinfo/bundle_generated.py
	@echo "Written to src/battinfo/bundle_generated.py (review before replacing bundle.py)"

check-freshness:
	$(PYTHON) scripts/assemble_context.py --check
