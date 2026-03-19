from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOTS = (
    ROOT / "assets",
    ROOT / "src" / "battinfo" / "data",
)


def test_records_with_source_url_have_citation() -> None:
    offenders: list[str] = []

    for root in DATA_ROOTS:
        for path in root.rglob("*.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue

            if not isinstance(doc, dict):
                continue
            provenance = doc.get("provenance")
            if not isinstance(provenance, dict):
                continue

            source_url = provenance.get("source_url")
            citation = provenance.get("citation")
            if isinstance(source_url, str) and source_url and not isinstance(citation, str):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == [], "Missing provenance.citation for records with provenance.source_url:\n" + "\n".join(offenders)
