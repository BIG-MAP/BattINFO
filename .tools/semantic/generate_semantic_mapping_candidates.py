from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCHEMA_PATH = ROOT / "assets" / "schemas" / "cell-canonical.schema.json"
DEFAULT_OUT_DIR = ROOT / "assets" / "mappings" / "domain-battery"
DEFAULT_ONTOLOGY = "https://w3id.org/emmo/domain/battery/inferred"

# Lightweight symbol aliases for candidate unit matching.
UNIT_ALIASES: dict[str, list[str]] = {
    "1": ["dimensionless", "unitless"],
    "A": ["ampere"],
    "Ah": ["amperehour", "ampere hour"],
    "C": ["celsius", "degree celsius"],
    "J": ["joule"],
    "K": ["kelvin"],
    "V": ["volt"],
    "W": ["watt"],
    "Wh": ["watt hour", "watthour"],
    "g": ["gram"],
    "kg": ["kilogram"],
    "m": ["metre", "meter"],
    "m2": ["square metre", "square meter"],
    "m3": ["cubic metre", "cubic meter"],
    "mm": ["millimetre", "millimeter"],
    "mΩ": ["milliohm", "milli ohm"],
    "mol": ["mole"],
    "mol/L": ["molar", "mole per litre", "mole per liter"],
    "ohm": ["ohm"],
    "s": ["second"],
}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate first-pass ontology-backed mapping candidates for BattINFO "
            "quantitative property keys and units."
        )
    )
    parser.add_argument(
        "--ontology",
        type=str,
        default=DEFAULT_ONTOLOGY,
        help="Ontology source (URI or local .ttl/.rdf/.jsonld file).",
    )
    parser.add_argument(
        "--keys-file",
        type=Path,
        default=None,
        help="Optional JSON file (array of strings) or newline text file with quantity keys.",
    )
    parser.add_argument(
        "--sample-json",
        type=Path,
        action="append",
        default=[],
        help="Optional JSON record(s) used to collect observed unit symbols.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Output directory for generated candidate maps and report.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files.",
    )
    return parser.parse_args()


def _to_norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _to_tokens(text: str) -> set[str]:
    return {tok for tok in re.split(r"[^a-z0-9]+", text.lower()) if tok}


def _iri_local_name(iri: str) -> str:
    if "#" in iri:
        return iri.rsplit("#", 1)[-1]
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_property_keys(keys_file: Path | None) -> list[str]:
    if keys_file is None:
        schema = json.loads(DEFAULT_SCHEMA_PATH.read_text(encoding="utf-8"))
        props = schema.get("$defs", {}).get("SpecSet", {}).get("properties", {})
        if not isinstance(props, dict):
            raise ValueError("Could not extract keys from cell-canonical SpecSet.")
        return sorted([k for k in props.keys() if isinstance(k, str)])

    text = keys_file.read_text(encoding="utf-8")
    if keys_file.suffix.lower() == ".json":
        raw = json.loads(text)
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise ValueError("keys-file JSON must be an array of strings.")
        return sorted(set(raw))

    keys: list[str] = []
    for line in text.splitlines():
        key = line.strip()
        if key and not key.startswith("#"):
            keys.append(key)
    return sorted(set(keys))


def _iter_units_from_json(obj: Any) -> list[str]:
    units: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {"unit", "unit_code", "unit_text"} and isinstance(value, str):
                units.append(value.strip())
            else:
                units.extend(_iter_units_from_json(value))
    elif isinstance(obj, list):
        for item in obj:
            units.extend(_iter_units_from_json(item))
    return units


def _collect_units(sample_json_paths: list[Path]) -> list[str]:
    observed: set[str] = set()
    for path in sample_json_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        for unit in _iter_units_from_json(data):
            if unit:
                observed.add(unit)
    return sorted(observed)


def _load_graph(source: str) -> Graph:
    graph = Graph()
    if Path(source).exists():
        graph.parse(Path(source).as_posix())
        return graph

    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        graph.parse(source)
        return graph

    raise FileNotFoundError(f"Ontology source not found: {source}")


def _iter_class_entries(graph: Graph) -> list[dict[str, Any]]:
    classes: set[URIRef] = set()
    for cls in graph.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef):
            classes.add(cls)
    for cls in graph.subjects(RDF.type, RDFS.Class):
        if isinstance(cls, URIRef):
            classes.add(cls)

    out: list[dict[str, Any]] = []
    for iri in sorted(classes, key=str):
        rdfs_labels: list[str] = []
        for value in graph.objects(iri, RDFS.label):
            if isinstance(value, Literal):
                label = str(value).strip()
                if label:
                    rdfs_labels.append(label)

        skos_pref_labels: list[str] = []
        for value in graph.objects(iri, SKOS.prefLabel):
            if isinstance(value, Literal):
                label = str(value).strip()
                if label:
                    skos_pref_labels.append(label)

        labels = [*skos_pref_labels, *rdfs_labels]
        local = _iri_local_name(str(iri))
        names = [local, *labels]
        names_norm = sorted({_to_norm(name) for name in names if name})
        tokens: set[str] = set()
        for name in names:
            tokens |= _to_tokens(name)
        pref_label = skos_pref_labels[0] if skos_pref_labels else (rdfs_labels[0] if rdfs_labels else local)
        out.append(
            {
                "iri": str(iri),
                "local_name": local,
                "labels": sorted(set(labels)),
                "pref_label": pref_label,
                "names_norm": names_norm,
                "tokens": sorted(tokens),
            }
        )
    return out


def _score_key_to_entry(key: str, entry: dict[str, Any]) -> float:
    key_norm = _to_norm(key)
    key_tokens = _to_tokens(key.replace("_", " "))
    name_norms = entry.get("names_norm", [])
    entry_tokens = set(entry.get("tokens", []))

    best = 0.0
    if key_norm in name_norms:
        best = max(best, 1.0)
    if any(key_norm in name and len(key_norm) >= 8 for name in name_norms):
        best = max(best, 0.9)
    if any(name in key_norm and len(name) >= 8 for name in name_norms):
        best = max(best, 0.75)
    if key_tokens and entry_tokens:
        overlap = len(key_tokens & entry_tokens)
        if overlap:
            best = max(best, overlap / len(key_tokens))
    return round(best, 3)


def _best_match(key: str, entries: list[dict[str, Any]], threshold: float = 0.5) -> dict[str, Any] | None:
    scored: list[tuple[float, dict[str, Any]]] = []
    for entry in entries:
        score = _score_key_to_entry(key, entry)
        if score > 0:
            scored.append((score, entry))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], len(row[1].get("labels", []))), reverse=True)
    score, entry = scored[0]
    if score < threshold:
        return None
    return {
        "class_iri": entry["iri"],
        "class_pref_label": entry.get("pref_label") or (entry.get("labels") or [entry.get("local_name")])[0],
        "class_label": (entry.get("labels") or [entry.get("local_name")])[0],  # backward-compatible alias
        "confidence": score,
    }


def _best_unit_match(symbol: str, entries: list[dict[str, Any]], threshold: float = 0.5) -> dict[str, Any] | None:
    aliases = UNIT_ALIASES.get(symbol, [symbol])
    best: dict[str, Any] | None = None
    best_score = 0.0
    for alias in aliases:
        alias_norm = _to_norm(alias)
        alias_tokens = _to_tokens(alias)
        for entry in entries:
            name_norms = set(entry.get("names_norm", []))
            entry_tokens = set(entry.get("tokens", []))
            score = 0.0
            if alias_norm and alias_norm in name_norms:
                score = 1.0
            elif alias_tokens and alias_tokens.issubset(entry_tokens):
                # Token subset matches are useful but weaker than exact lexical matches.
                score = max(score, 0.8)
            elif alias_norm and len(alias_norm) >= 8 and any(alias_norm in name for name in name_norms):
                score = max(score, 0.7)
            if score > best_score:
                best_score = score
                best = {
                    "class_iri": entry["iri"],
                    "class_pref_label": entry.get("pref_label") or (entry.get("labels") or [entry.get("local_name")])[0],
                    "class_label": (entry.get("labels") or [entry.get("local_name")])[0],  # backward-compatible alias
                    "confidence": round(score, 3),
                }
    if best is None or best_score < threshold:
        return None
    return best


def _build_property_candidates(keys: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for key in keys:
        match = _best_match(key, entries)
        row: dict[str, Any] = {"key": key}
        if match is None:
            row.update(
                {
                    "status": "unmapped",
                    "class_iri": None,
                    "class_pref_label": None,
                    "class_label": None,
                    "confidence": 0.0,
                }
            )
        else:
            row.update({"status": "candidate", **match})
        candidates.append(row)
    return candidates


def _build_unit_candidates(units: list[str], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for symbol in units:
        match = _best_unit_match(symbol, entries, threshold=0.75)
        row: dict[str, Any] = {"symbol": symbol}
        if match is None:
            row.update(
                {
                    "status": "unmapped",
                    "unit_iri": None,
                    "unit_pref_label": None,
                    "unit_label": None,
                    "confidence": 0.0,
                }
            )
        else:
            row.update(
                {
                    "status": "candidate",
                    "unit_iri": match["class_iri"],
                    "unit_pref_label": match["class_pref_label"],
                    "unit_label": match["class_label"],  # backward-compatible alias
                    "confidence": match["confidence"],
                }
            )
        candidates.append(row)
    return candidates


def _write_json(path: Path, payload: dict[str, Any], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output exists, pass --overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_report(
    path: Path,
    *,
    ontology: str,
    key_count: int,
    unit_count: int,
    property_candidates: list[dict[str, Any]],
    unit_candidates: list[dict[str, Any]],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output exists, pass --overwrite: {path}")

    mapped_props = [row for row in property_candidates if row["status"] == "candidate"]
    mapped_units = [row for row in unit_candidates if row["status"] == "candidate"]

    lines = [
        "# Quantitative Property Mapping Candidate Report",
        "",
        f"- Generated at: `{_now_iso()}`",
        f"- Ontology source: `{ontology}`",
        f"- Property keys: `{key_count}`",
        f"- Property candidates mapped: `{len(mapped_props)}`",
        f"- Unit symbols: `{unit_count}`",
        f"- Unit candidates mapped: `{len(mapped_units)}`",
        "",
        "## Property Candidates",
        "",
        "| Key | Status | Candidate Class IRI | prefLabel | Confidence |",
        "|---|---|---|---|---|",
    ]
    for row in property_candidates:
        candidate = row["class_iri"] or "-"
        pref_label = row.get("class_pref_label") or "-"
        conf = f"{row['confidence']:.3f}"
        lines.append(f"| `{row['key']}` | `{row['status']}` | `{candidate}` | `{pref_label}` | `{conf}` |")

    lines.extend(
        [
            "",
            "## Unit Candidates",
            "",
            "| Symbol | Status | Candidate Unit IRI | prefLabel | Confidence |",
            "|---|---|---|---|---|",
        ]
    )
    for row in unit_candidates:
        candidate = row.get("unit_iri") or "-"
        pref_label = row.get("unit_pref_label") or "-"
        conf = f"{row['confidence']:.3f}"
        lines.append(f"| `{row['symbol']}` | `{row['status']}` | `{candidate}` | `{pref_label}` | `{conf}` |")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = _parse_args()

    try:
        keys = _load_property_keys(args.keys_file)
        graph = _load_graph(args.ontology)
        entries = _iter_class_entries(graph)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed setup: {exc}", file=sys.stderr)
        return 2

    units = _collect_units(args.sample_json)
    property_candidates = _build_property_candidates(keys, entries)
    unit_candidates = _build_unit_candidates(units, entries)

    out_dir = args.out_dir
    property_out = out_dir / "property_map.candidates.json"
    unit_out = out_dir / "unit_map.candidates.json"
    report_out = out_dir / "quantitative_mapping_report.md"

    property_payload = {
        "version": "0.1.0-draft",
        "generated_at": _now_iso(),
        "ontology_source": args.ontology,
        "key_count": len(keys),
        "mappings": property_candidates,
    }
    unit_payload = {
        "version": "0.1.0-draft",
        "generated_at": _now_iso(),
        "ontology_source": args.ontology,
        "unit_count": len(units),
        "mappings": unit_candidates,
    }

    try:
        _write_json(property_out, property_payload, overwrite=args.overwrite)
        _write_json(unit_out, unit_payload, overwrite=args.overwrite)
        _write_report(
            report_out,
            ontology=args.ontology,
            key_count=len(keys),
            unit_count=len(units),
            property_candidates=property_candidates,
            unit_candidates=unit_candidates,
            overwrite=args.overwrite,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] Failed writing outputs: {exc}", file=sys.stderr)
        return 3

    print(f"wrote_property_map={property_out}")
    print(f"wrote_unit_map={unit_out}")
    print(f"wrote_report={report_out}")
    print(f"mapped_properties={sum(1 for row in property_candidates if row['status'] == 'candidate')}")
    print(f"mapped_units={sum(1 for row in unit_candidates if row['status'] == 'candidate')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

