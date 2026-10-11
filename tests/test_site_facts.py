"""battinfo.org states facts about the release; keep them in step with the repo."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _site_value(name: str) -> str:
    site = (ROOT / "web" / "lib" / "site.ts").read_text(encoding="utf-8")
    match = re.search(rf'\b{name}: "([^"]*)"', site)
    assert match, f"{name} not found in web/lib/site.ts"
    return match.group(1)


def test_site_ontology_versions_match_the_pinned_imports() -> None:
    ttl = (ROOT / "battinfo.ttl").read_text(encoding="utf-8")
    pins = dict(re.findall(r"owl:imports <https://w3id\.org/emmo/domain/([a-z-]+)/([0-9.]+)/", ttl))
    assert _site_value("domainBattery") == pins["battery"]
    assert _site_value("domainElectrochemistry") == pins["electrochemistry"]


def test_site_readme_and_citation_cite_one_doi() -> None:
    doi = _site_value("doi")
    assert doi.startswith("10.5281/zenodo.")
    assert f'doi: "{doi}"' in (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"https://doi.org/{doi}" in readme
    assert "XXXXXXX" not in readme
