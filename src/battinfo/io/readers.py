from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, Any]]:
    raise NotImplementedError("CSV ingestion is planned but not implemented yet.")


def read_excel(path: Path) -> list[dict[str, Any]]:
    raise NotImplementedError("Excel ingestion is planned but not implemented yet.")


def read_parquet(path: Path) -> list[dict[str, Any]]:
    raise NotImplementedError("Parquet ingestion is planned but not implemented yet.")
