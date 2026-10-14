"""0.8.0 has no Battery Pass target, and the draft profile schema stays served.

The `batterypass` mapping target added one placeholder type in an unregistered
namespace, and the `batterypass` validation profile checked a draft envelope;
neither was Battery Pass data. Both are removed. The profile schema is
published at https://w3id.org/battinfo/schema/profiles/batterypass.schema.json,
and battinfo-registry deletes every vendored schema BattINFO stops shipping,
so the file stays in both schema trees with its description marked withdrawn.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from battinfo.transform.json_to_jsonld import to_jsonld  # noqa: E402
from battinfo.validate.schema import PROFILE_TO_SCHEMA, validate_profile  # noqa: E402

SCHEMA_TREES = (ROOT / "assets" / "schemas", ROOT / "src" / "battinfo" / "data" / "schemas")
PROFILE_SCHEMA = Path("profiles") / "batterypass.schema.json"
PROFILE_SCHEMA_ID = "https://w3id.org/battinfo/schema/profiles/batterypass.schema.json"
# sha256 of the published profile schema without its description and $comment.
# A published schema must not validate differently at the same URL
# (IDENTIFIER_POLICY 11.1), so only those two annotations may change.
PROFILE_SCHEMA_RULES_SHA256 = "1f4ff1c5ce331b69a6f39504c4b051f4ad865e1cd2ca15edcb64be3fb79e7931"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_batterypass_is_not_a_validation_profile() -> None:
    assert "batterypass" not in PROFILE_TO_SCHEMA
    report = validate_profile({"profile": "batterypass"}, "batterypass")
    assert [issue.code for issue in report.errors] == ["schema.profile_unknown"]


@pytest.mark.parametrize("tree", SCHEMA_TREES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_withdrawn_profile_schema_still_ships_unchanged_in_its_rules(tree: Path) -> None:
    path = tree / PROFILE_SCHEMA
    assert path.is_file(), "deleting the file would make its published URL return 404 after the registry sync"
    schema = _load(path)
    assert schema["$id"] == PROFILE_SCHEMA_ID
    assert schema["description"].startswith("Withdrawn"), schema["description"]
    assert "will be tightened" not in schema.get("$comment", "")
    rules = {key: value for key, value in schema.items() if key not in {"description", "$comment"}}
    digest = hashlib.sha256(json.dumps(rules, sort_keys=True).encode("utf-8")).hexdigest()
    assert digest == PROFILE_SCHEMA_RULES_SHA256, "the published profile must validate as it did"


@pytest.mark.parametrize("tree", SCHEMA_TREES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_base_schema_does_not_offer_batterypass_as_a_profile(tree: Path) -> None:
    description = _load(tree / "battinfo.base.schema.json")["properties"]["profile"]["description"]
    assert "batterypass" not in description.lower()


def test_to_jsonld_refuses_the_batterypass_target() -> None:
    record = _load(ROOT / "examples" / "cell-spec" / "A123__ANR26650M1-B.json")
    with pytest.raises(ValueError, match="removed in 0.8.0"):
        to_jsonld(record, target="batterypass")


@pytest.mark.parametrize("tree", ["examples", "src/battinfo/data/examples"])
def test_no_example_is_a_battery_pass_fixture(tree: str) -> None:
    root = ROOT / tree
    offenders = [
        path.relative_to(root).as_posix()
        for path in sorted(root.rglob("*.json"))
        if "batterypass" in path.read_text(encoding="utf-8").lower()
    ]
    assert not offenders
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "Battery Pass" not in readme and "profiles/" not in readme


def test_scope_lists_the_battery_pass_crosswalk_as_in_development() -> None:
    scope = (ROOT / "docs" / "scope.md").read_text(encoding="utf-8")
    in_development = scope.partition("\n## In development\n")[2].partition("\n## ")[0]
    assert "Battery Pass crosswalk" in in_development
