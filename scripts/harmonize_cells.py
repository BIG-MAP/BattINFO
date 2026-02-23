from __future__ import annotations

import json
import re
import hashlib
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "assets" / "examples" / "cells"
CLEAN_DIR = ROOT / "assets" / "examples" / "cells-clean"
PKG_RAW_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells"
PKG_CLEAN_DIR = ROOT / "src" / "battinfo" / "data" / "examples" / "cells-clean"
MODEL_MANUFACTURERS = ROOT / "assets" / "registry" / "model-manufacturers.json"
UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def slug(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9_.-]", "", value)
    return value


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def infer_format(model: str) -> str:
    upper = model.upper()
    if re.search(r"\b2032\b", model) or upper.startswith("LIR2032"):
        return "coin"
    if upper.startswith("SLP") or "LIPO" in upper:
        return "pouch"
    if upper.startswith("MB-LFP") or re.match(r"^L\d{3}", model):
        return "prismatic"
    if re.search(r"(18650|21700|26650|32140|32135|40152|4680)", model):
        return "cylindrical"
    return "unknown"


def infer_chemistry(model: str, text_hint: str | None = None) -> str:
    upper = model.upper()
    hint = (text_hint or "").lower()
    if "lifepo4" in hint or re.search(r"\blfp\b", hint) or upper.startswith(("IFR", "IFPR", "ANR")):
        return "LFP"
    if upper.startswith("LIR"):
        return "Li-ion"
    if upper.startswith("ICR"):
        return "LCO"
    if upper.startswith("INR"):
        return "NMC"
    if upper.startswith("NCR"):
        return "NCA"
    return "Li-ion"


def infer_size_code(model: str) -> str | None:
    match = re.search(r"(\d{4,5})", model)
    return match.group(1) if match else None


def load_manufacturer_map() -> dict[str, str]:
    if MODEL_MANUFACTURERS.exists():
        try:
            return json.loads(MODEL_MANUFACTURERS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def infer_manufacturer(model: str, doc: dict, mapping: dict[str, str]) -> tuple[str, list[str]]:
    inferred = []
    manufacturer = None

    battery = doc.get("battery", {})
    if isinstance(battery, dict):
        manu = battery.get("manufacturer")
        if isinstance(manu, dict):
            manufacturer = manu.get("name")
        elif isinstance(manu, str):
            manufacturer = manu

    if not manufacturer:
        manufacturer = mapping.get(model)
        if manufacturer:
            inferred.append("cell.manufacturer")

    if not manufacturer:
        tokens = [
            "A123",
            "ATL",
            "AMPEX",
            "CALB",
            "EVE",
            "PANASONIC",
            "SAMSUNG",
            "LG",
            "SONY",
            "MURATA",
            "CATL",
        ]
        upper = model.upper()
        for token in tokens:
            if token in upper:
                manufacturer = token.title()
                inferred.append("cell.manufacturer")
                break

    return manufacturer or "Unknown", inferred


def to_spec_item(quantity: dict) -> dict | None:
    if not isinstance(quantity, dict):
        return None
    value = quantity.get("value")
    unit = quantity.get("unit")
    if value is None or unit is None:
        return None
    return {"value": value, "unit": unit}


def uid_from_seed(seed: str, taken: set[str]) -> str:
    # Deterministic 80-bit UID from seed with collision fallback.
    counter = 0
    while True:
        material = seed if counter == 0 else f"{seed}#{counter}"
        digest = hashlib.sha256(material.encode("utf-8")).digest()[:10]
        number = int.from_bytes(digest, "big")
        chars = []
        for _ in range(16):
            chars.append(UID_ALPHABET[number & 31])
            number >>= 5
        token = "".join(reversed(chars))
        uid = f"{token[:4]}-{token[4:8]}-{token[8:12]}-{token[12:16]}"
        if uid not in taken:
            taken.add(uid)
            return uid
        counter += 1


def map_curated(doc: dict, source_file: str, mapping: dict[str, str]) -> dict:
    record = doc.get("record", {})
    battery = doc.get("battery", {})
    measurements = doc.get("measurements", []) or []

    model = battery.get("id") or record.get("title") or source_file
    model = str(model)

    manufacturer, inferred = infer_manufacturer(model, doc, mapping)
    chemistry = battery.get("chemistry") or infer_chemistry(model)
    size_code = infer_size_code(model)
    fmt = infer_format(model)

    cell = {
        "model_name": model,
        "manufacturer": manufacturer,
        "format": fmt,
        "chemistry": chemistry,
    }
    if size_code:
        cell["size_code"] = size_code

    specs = {}
    extra_measurements = []

    for prop in measurements:
        name = prop.get("name") or prop.get("property")
        quantity = prop.get("quantity", {})
        spec = to_spec_item(quantity)
        if not name or not spec:
            continue
        if name == "CycleLife":
            specs["cycle_life"] = spec
        elif name == "UpperVoltageLimit":
            specs["charge_voltage"] = spec
        elif name == "LowerVoltageLimit":
            specs["discharge_cutoff_voltage"] = spec
        elif name == "ChargingCurrent":
            specs["charging_current"] = spec
        elif name == "MaximumContinuousChargingCurrent":
            specs["max_charge_current"] = spec
        elif name == "DischargingCurrent":
            specs["discharging_current"] = spec
        elif name == "MaximumContinuousDischargingCurrent":
            specs["max_discharge_current"] = spec
            specs["continuous_discharge_current"] = spec
        elif name == "Height":
            specs["height"] = spec
        elif name == "Width":
            specs["width"] = spec
        elif name == "Length":
            specs["length"] = spec
        elif name == "Diameter":
            specs["diameter"] = spec
        else:
            extra_measurements.append(
                {
                    "name": name,
                    "property": prop.get("property"),
                    "quantity": spec,
                    "source": prop.get("method"),
                }
            )

    nominal_capacity = to_spec_item(battery.get("nominal_capacity", {}))
    nominal_voltage = to_spec_item(battery.get("nominal_voltage", {}))
    mass = to_spec_item(battery.get("mass", {}))
    if nominal_capacity:
        specs["nominal_capacity"] = nominal_capacity
    if nominal_voltage:
        specs["nominal_voltage"] = nominal_voltage
    if mass:
        specs["mass"] = mass

    if fmt == "unknown":
        if "diameter" in specs:
            fmt = "cylindrical"
        elif all(k in specs for k in ("length", "width", "height")):
            fmt = "prismatic"
        if fmt != "unknown":
            inferred.append("cell.format")
    cell["format"] = fmt

    provenance = {
        "source_type": "curated",
        "source_file": source_file,
        "source_id": record.get("id"),
        "source_url": record.get("source"),
        "extracted_at": now_iso(),
    }

    return {
        "provenance": provenance,
        "cell": cell,
        "specs": specs or None,
        "measurements": extra_measurements or None,
        "inferred_fields": inferred,
    }


def map_datasheet(doc: dict, source_file: str, mapping: dict[str, str]) -> dict:
    cell_doc = doc.get("cell", {})
    model = cell_doc.get("model_name") or source_file
    model = str(model)
    manufacturer, inferred = infer_manufacturer(model, doc, mapping)
    chemistry = cell_doc.get("chemistry") or infer_chemistry(model)
    fmt = cell_doc.get("format") or infer_format(model)
    size_code = cell_doc.get("size_code") or infer_size_code(model)

    cell = {
        "model_name": model,
        "manufacturer": manufacturer,
        "format": fmt,
        "chemistry": chemistry,
    }
    if size_code:
        cell["size_code"] = size_code
    if cell_doc.get("datasheet_revision"):
        cell["datasheet_revision"] = cell_doc.get("datasheet_revision")

    provenance = {
        "source_type": "datasheet",
        "source_file": source_file,
        "source_id": doc.get("source", {}).get("model_name"),
        "source_url": doc.get("source", {}).get("source_url"),
        "extracted_at": doc.get("source", {}).get("extracted_at") or now_iso(),
    }

    specs = {}
    for key in ("specs", "performance", "dimensions", "operating_conditions"):
        block = doc.get(key)
        if isinstance(block, dict):
            specs.update(block)

    return {
        "provenance": provenance,
        "cell": cell,
        "specs": specs or None,
        "inferred_fields": inferred,
    }


def apply_quality(doc: dict, inferred: list[str]) -> None:
    missing = []
    cell = doc.get("cell", {})
    if cell.get("manufacturer") in (None, "", "Unknown"):
        missing.append("cell.manufacturer")
    if cell.get("model_name") in (None, "", "unknown"):
        missing.append("cell.model_name")
    if cell.get("chemistry") in (None, "", "Li-ion") and "cell.chemistry" not in inferred:
        missing.append("cell.chemistry")
    if cell.get("format") in (None, "", "unknown"):
        missing.append("cell.format")

    doc["quality"] = {
        "missing_fields": missing,
        "inferred_fields": inferred,
        "warnings": [],
    }


def main() -> None:
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    PKG_CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    mapping = load_manufacturer_map()
    seen_uids: set[str] = set()
    for path in RAW_DIR.glob("*.json"):
        source_file = path.name
        doc = load_json(path)
        if source_file.endswith(".curated.json"):
            mapped = map_curated(doc, source_file, mapping)
        else:
            mapped = map_datasheet(doc, source_file, mapping)

        inferred = mapped.pop("inferred_fields", [])

        cell = mapped["cell"]
        manufacturer = cell.get("manufacturer") or "Unknown"
        model_name = cell.get("model_name") or "unknown"
        if manufacturer != "Unknown":
            upper_model = model_name.upper()
            upper_man = manufacturer.upper()
            if upper_model.startswith(upper_man):
                semantic_id = slug(model_name)
            else:
                semantic_id = slug(f"{manufacturer}__{model_name}")
        else:
            semantic_id = slug(model_name)

        uid = uid_from_seed(f"cell-type::{semantic_id}", seen_uids)
        cell["id"] = f"https://w3id.org/battinfo/cell-type/{uid}"

        clean = {
            "schema_version": "0.1.0",
            **{k: v for k, v in mapped.items() if v is not None},
        }

        apply_quality(clean, inferred)

        name = f"{semantic_id}.json"
        write_json(CLEAN_DIR / name, clean)
        write_json(PKG_CLEAN_DIR / name, clean)

    print(f"Generated {len(list(CLEAN_DIR.glob('*.json')))} clean cell instances.")


if __name__ == "__main__":
    main()
