from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "registry" / "site"
SOURCE_DIRS = [
    ROOT / "assets" / "examples" / "cell-types",
    ROOT / "assets" / "examples" / "cell-instances",
    ROOT / "assets" / "examples" / "datasets",
]


def _iri_tail(iri: str) -> tuple[str, str]:
    parts = iri.rstrip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"Invalid IRI: {iri}")
    return parts[-2], parts[-1]


def _entity_id(doc: dict[str, Any]) -> str:
    if isinstance(doc.get("cell_type"), dict) and isinstance(doc["cell_type"].get("id"), str):
        return doc["cell_type"]["id"]
    if isinstance(doc.get("cell_instance"), dict) and isinstance(doc["cell_instance"].get("id"), str):
        return doc["cell_instance"]["id"]
    if isinstance(doc.get("dataset"), dict) and isinstance(doc["dataset"].get("id"), str):
        return doc["dataset"]["id"]
    raise ValueError("Could not locate canonical entity id in document.")


def _to_jsonld(doc: dict[str, Any]) -> dict[str, Any]:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)

    context = [
        "https://w3id.org/emmo/domain/battery/context",
        {
            "schema": "https://schema.org/",
            "battinfo": "https://w3id.org/battinfo#",
        },
    ]

    if entity_type == "cell-type":
        cell = doc["cell_type"]
        out: dict[str, Any] = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellType",
            "schema:identifier": uid,
            "schema:name": cell.get("model_name"),
            "schema:manufacturer": {"@type": "schema:Organization", "schema:name": cell.get("manufacturer")},
            "battinfo:chemistry": cell.get("chemistry"),
            "battinfo:format": cell.get("format"),
        }
        if cell.get("size_code"):
            out["battinfo:sizeCode"] = cell.get("size_code")
        return out

    if entity_type == "cell":
        cell = doc["cell_instance"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "battinfo:BatteryCellInstance",
            "schema:identifier": uid,
            "battinfo:typeId": {"@id": cell.get("type_id")},
        }
        if cell.get("serial_number"):
            out["battinfo:serialNumber"] = cell.get("serial_number")
        datasets: list[dict[str, str]] = []
        for dataset in doc.get("datasets", []):
            if isinstance(dataset, dict) and isinstance(dataset.get("id"), str):
                datasets.append({"@id": dataset["id"]})
        if datasets:
            out["battinfo:hasDataset"] = datasets
        return out

    if entity_type == "dataset":
        dataset = doc["dataset"]
        out = {
            "@context": context,
            "@id": entity_iri,
            "@type": "schema:Dataset",
            "schema:identifier": uid,
            "schema:name": dataset.get("title"),
            "schema:description": dataset.get("description"),
            "schema:license": dataset.get("license"),
            "schema:encodingFormat": dataset.get("format"),
        }
        if dataset.get("access_url"):
            out["schema:url"] = dataset.get("access_url")
        related = dataset.get("related_entities", {})
        if isinstance(related, dict):
            cells = related.get("cell_ids")
            if isinstance(cells, list):
                out["battinfo:aboutCell"] = [{"@id": cell_id} for cell_id in cells if isinstance(cell_id, str)]
        return out

    raise ValueError(f"Unsupported entity type '{entity_type}' for {entity_iri}.")


def _to_html(doc: dict[str, Any]) -> str:
    entity_iri = _entity_id(doc)
    entity_type, uid = _iri_tail(entity_iri)
    pretty = html.escape(json.dumps(doc, indent=2, ensure_ascii=False))
    title = html.escape(f"BattINFO {entity_type} {uid}")
    iri_escaped = html.escape(entity_iri)
    return (
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\" />\n"
        f"  <title>{title}</title>\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />\n"
        "  <style>body{font-family:Arial,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;line-height:1.5}"
        "code,pre{background:#f6f8fa;border-radius:4px}pre{padding:1rem;overflow:auto}"
        "a{color:#0b5fff;text-decoration:none}a:hover{text-decoration:underline}</style>\n"
        "</head>\n"
        "<body>\n"
        f"  <h1>{title}</h1>\n"
        f"  <p><strong>Canonical IRI:</strong> <code>{iri_escaped}</code></p>\n"
        "  <p>\n"
        "    <a href=\"index.json\">JSON</a> |\n"
        "    <a href=\"index.jsonld\">JSON-LD</a>\n"
        "  </p>\n"
        "  <h2>Metadata</h2>\n"
        f"  <pre>{pretty}</pre>\n"
        "</body>\n"
        "</html>\n"
    )


def main() -> None:
    SITE_ROOT.mkdir(parents=True, exist_ok=True)
    written = 0

    for src_dir in SOURCE_DIRS:
        if not src_dir.exists():
            continue
        for path in sorted(src_dir.glob("*.json")):
            doc = json.loads(path.read_text(encoding="utf-8"))
            iri = _entity_id(doc)
            entity_type, uid = _iri_tail(iri)

            out_dir = SITE_ROOT / entity_type / uid
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / "index.json").write_text(
                json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out_dir / "index.jsonld").write_text(
                json.dumps(_to_jsonld(doc), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (out_dir / "index.html").write_text(_to_html(doc), encoding="utf-8")
            written += 1

    print(f"wrote_artifacts_for={written}")


if __name__ == "__main__":
    main()
