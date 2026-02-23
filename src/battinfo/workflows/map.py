from __future__ import annotations

from typing import Any

from battinfo.transform.json_to_jsonld import to_jsonld


def run_mapping(data: dict[str, Any], target: str) -> dict[str, Any]:
    return to_jsonld(data, target=target)
