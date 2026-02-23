from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

UID_UNDASHED_RE = re.compile(r"^[0-9a-hjkmnp-tv-z]{16}$")
UID_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def dashed_uid(token: str) -> str:
    return "-".join((token[:4], token[4:8], token[8:12], token[12:16]))


def normalize_uid(value: str) -> str:
    token = value.strip().lower().replace("-", "")
    token = token.replace("o", "0").replace("i", "1").replace("l", "1")
    if not UID_UNDASHED_RE.fullmatch(token):
        raise SystemExit(
            "Invalid UID. Expected 16 Crockford Base32 characters (dashed or undashed)."
        )
    return dashed_uid(token)


def mint_uid() -> str:
    token = "".join(secrets.choice(UID_ALPHABET) for _ in range(16))
    return dashed_uid(token)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasheet", required=True, help="Path to cell-datasheet JSON")
    parser.add_argument("--out", required=True, help="Output cell-type JSON")
    parser.add_argument(
        "--uid",
        default=None,
        help="Optional BattINFO UID (dashed or undashed). If omitted, a random UID is minted.",
    )
    args = parser.parse_args()

    doc = load_json(Path(args.datasheet))

    cell = doc.get("cell", {})
    specs = doc.get("specs", {})
    source = doc.get("source", {})

    manufacturer = cell.get("manufacturer") or source.get("manufacturer") or "Unknown"
    model = cell.get("model_name") or source.get("model_name") or "unknown"
    uid = normalize_uid(args.uid) if args.uid else mint_uid()
    cell_id = f"https://w3id.org/battinfo/cell-type/{uid}"

    out = {
        "schema_version": "0.1.0",
        "cell_type": {
            "id": cell_id,
            "short_id": uid.replace("-", "")[:6],
            "model_name": model,
            "manufacturer": manufacturer,
            "format": cell.get("format", "unknown"),
            "chemistry": cell.get("chemistry", "unknown"),
        },
        "specs": specs,
        "provenance": {
            "source_type": "datasheet",
            "source_file": source.get("filename"),
            "source_url": source.get("source_url"),
            "file_hash": source.get("file_hash"),
            "retrieved_at": source.get("extracted_at") or now_iso(),
        },
    }

    if cell.get("size_code"):
        out["cell_type"]["size_code"] = cell["size_code"]
    if cell.get("datasheet_revision"):
        out["cell_type"]["datasheet_revision"] = cell["datasheet_revision"]

    write_json(Path(args.out), out)


if __name__ == "__main__":
    main()
