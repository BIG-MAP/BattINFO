PYTHON := .venv/Scripts/python
CONTEXT_OUT := src/battinfo/data/context/records.context.json

.PHONY: gen-all gen-context check-freshness help

help:
	@echo "Targets:"
	@echo "  gen-all          Run all generators (context)"
	@echo "  gen-context      Assemble records.context.json from schema/*.yaml"
	@echo "  check-freshness  Exit non-zero if records.context.json is stale"

gen-all: gen-context

gen-context:
	$(PYTHON) scripts/assemble_context.py
	@echo "Context written to $(CONTEXT_OUT)"

check-freshness:
	$(PYTHON) scripts/assemble_context.py --check
