"""The hosted records @context: complete, generated, versioned, offline-resolvable.

records.context.v1.json is the frozen superset a document references instead of
inlining ~370 terms. It is generated (scripts/gen_context.py) and must not drift;
a URL-referencing document must expand to the same graph as the inline form and
validate fully offline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pyld import jsonld as _jsonld  # noqa: E402

from battinfo.jsonld import _CONTEXT_URL, record_to_jsonld  # noqa: E402
from battinfo.validate.jsonld import (  # noqa: E402
    _BATTINFO_RECORDS_CONTEXT_URL,
    _inline_local_contexts,
    _resolve_local_context,
    validate_jsonld_report,
)

A123 = ROOT / "src" / "battinfo" / "data" / "examples" / "cell-spec" / "A123__ANR26650M1-B.json"


def _load_gen():
    spec = importlib.util.spec_from_file_location("gen_context", ROOT / "scripts" / "gen_context.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _nquads(doc: dict) -> str:
    expanded = _jsonld.expand(_inline_local_contexts(doc))
    return _jsonld.normalize(expanded, {"algorithm": "URDNA2015", "format": "application/n-quads"})


def test_generated_context_is_in_sync() -> None:
    gen = _load_gen()
    committed = gen.OUT.read_text(encoding="utf-8")
    assert committed == gen.render(), (
        "records.context.v1.json is stale — regenerate with `uv run python scripts/gen_context.py`"
    )


def test_hosted_context_resolves_offline() -> None:
    # The URL the transform references resolves to the bundled complete context.
    resolved = _resolve_local_context(_BATTINFO_RECORDS_CONTEXT_URL)
    assert isinstance(resolved, dict)
    terms = resolved.get("@context", resolved)
    assert isinstance(terms, dict) and len(terms) > 300


def test_url_mode_is_compact_and_equivalent_to_inline() -> None:
    record = json.loads(A123.read_text(encoding="utf-8"))
    inline = record_to_jsonld(record, "cell-spec")  # default
    referenced = record_to_jsonld(record, "cell-spec", context="url")

    assert isinstance(inline["@context"], dict)
    assert referenced["@context"] == _CONTEXT_URL
    # A compact document is just its body plus the URL.
    assert set(referenced) - {"@context"} == set(inline) - {"@context"}
    # Both forms expand to exactly the same RDF graph (offline).
    assert _nquads(referenced) == _nquads(inline)


def test_url_mode_validates_offline() -> None:
    record = json.loads(A123.read_text(encoding="utf-8"))
    referenced = record_to_jsonld(record, "cell-spec", context="url")
    report = validate_jsonld_report(referenced)
    errors = [issue.message for issue in report.issues if issue.severity == "error"]
    assert not errors, errors
