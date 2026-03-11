from __future__ import annotations

import argparse
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

CELL_TYPE_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/cell-type/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
DATASET_IRI_RE = re.compile(
    r"^https://w3id\.org/battinfo/dataset/[0-9a-hjkmnp-tv-z]{4}(?:-[0-9a-hjkmnp-tv-z]{4}){3}$"
)
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
    parser.add_argument("--cell-type", required=True, help="Path to cell-type JSON")
    parser.add_argument("--serial", required=True, help="Serial number for instance")
    parser.add_argument("--out", required=True, help="Output cell-instance JSON")
    parser.add_argument(
        "--uid",
        default=None,
        help="Optional BattINFO UID (dashed or undashed). If omitted, a random UID is minted.",
    )
    parser.add_argument(
        "--dataset-id",
        default=None,
        help="Optional BattINFO dataset IRI: https://w3id.org/battinfo/dataset/{uid}",
    )
    args = parser.parse_args()

    cell_type = load_json(Path(args.cell_type))
    cell_type_id = cell_type.get("cell_type", {}).get("id")
    if not cell_type_id:
        raise SystemExit("cell_type.id missing in cell-type JSON")
    if not CELL_TYPE_IRI_RE.fullmatch(cell_type_id):
        raise SystemExit(
            "cell_type.id must be a BattINFO cell-type IRI "
            "(https://w3id.org/battinfo/cell-type/{uid})."
        )

    uid = normalize_uid(args.uid) if args.uid else mint_uid()
    instance_id = f"https://w3id.org/battinfo/cell/{uid}"

    provenance = {
        "source_type": "measurement",
        "retrieved_at": now_iso(),
    }
    if args.dataset_id is not None:
        dataset_id = args.dataset_id.strip()
        if not DATASET_IRI_RE.fullmatch(dataset_id):
            raise SystemExit(
                "--dataset-id must match https://w3id.org/battinfo/dataset/{uid}."
            )
        provenance["dataset_id"] = dataset_id
        provenance["dataset_ids"] = [dataset_id]

    out = {
        "schema_version": "0.1.0",
        "cell_instance": {
            "id": instance_id,
            "type_id": cell_type_id,
            "short_id": uid.replace("-", "")[:6],
            "serial_number": args.serial,
        },
        "provenance": provenance,
    }

    write_json(Path(args.out), out)


if __name__ == "__main__":
    main()
