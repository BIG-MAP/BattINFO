"""An ORCID is recognised by parsing its URL (battinfo._util.orcid_id).

The host has to be orcid.org or www.orcid.org and the path one iD. A URL that only holds ``orcid.org`` somewhere in its text, or that ends in an iD on another host, names no ORCID, so it is never written as one into DataCite metadata or a deposit graph.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import battinfo  # noqa: E402
from battinfo._util import orcid_id  # noqa: E402
from battinfo.publication import _datacite_creators  # noqa: E402
from battinfo.ws import _agent_from_record_contributor, _agent_node, _normalize_orcid  # noqa: E402

ORCID = "0000-0002-1825-0097"
ORCID_X = "0000-0002-1694-233X"
ORCID_URL = f"https://orcid.org/{ORCID}"
HOSTILE = f"https://evil.example/orcid.org/{ORCID}"

_ORCIDS = [
    pytest.param(ORCID, ORCID, id="bare"),
    pytest.param(ORCID_URL, ORCID, id="https"),
    pytest.param(f"http://orcid.org/{ORCID}", ORCID, id="http"),
    pytest.param(f"https://www.orcid.org/{ORCID}", ORCID, id="www"),
    pytest.param(f"HTTPS://ORCID.ORG/{ORCID}/", ORCID, id="capitals-and-closing-slash"),
    pytest.param(f"orcid.org/{ORCID}", ORCID, id="no-scheme"),
    pytest.param(f"www.orcid.org/{ORCID}", ORCID, id="www-no-scheme"),
    pytest.param(f"  https://orcid.org/{ORCID_X.lower()}\n", ORCID_X, id="padded-small-x"),
    pytest.param(f"{ORCID}/", ORCID, id="bare-closing-slash"),
]

_NOT_ORCIDS = [
    pytest.param(HOSTILE, id="orcid-host-in-the-path"),
    pytest.param(f"https://evil.example/people/{ORCID}", id="id-on-another-host"),
    pytest.param(f"evil.example/orcid.org/{ORCID}", id="orcid-host-in-the-path-no-scheme"),
    pytest.param(f"https://orcid.org.evil.example/{ORCID}", id="orcid-host-as-subdomain"),
    pytest.param(f"https://notorcid.org/{ORCID}", id="host-that-ends-in-orcid-org"),
    pytest.param(f"https://sandbox.orcid.org/{ORCID}", id="sandbox"),
    pytest.param(f"https://orcid.org@evil.example/{ORCID}", id="orcid-host-as-user-name"),
    pytest.param(f"https://someone@orcid.org/{ORCID}", id="user-name"),
    pytest.param(f"https://orcid.org:8443/{ORCID}", id="port"),
    pytest.param(f"https://evil.example/?next=https://orcid.org/{ORCID}", id="orcid-url-in-a-query"),
    pytest.param(f"https://evil.example/#orcid.org/{ORCID}", id="orcid-host-in-a-fragment"),
    pytest.param(f"ftp://orcid.org/{ORCID}", id="other-scheme"),
    pytest.param(f"https://orcid.org/{ORCID}?lang=en", id="query"),
    pytest.param(f"https://orcid.org/{ORCID}#top", id="fragment"),
    pytest.param(f"https://orcid.org/{ORCID}/works", id="longer-path"),
    pytest.param(f"https://orcid.org//{ORCID}", id="double-slash"),
    pytest.param(f"https://orcid.org/{ORCID} {ORCID}", id="two-ids"),
    pytest.param("https://orcid.org/0000-0002-\n1825-0097", id="line-break-inside"),
    pytest.param("https://orcid.org/", id="no-id"),
    pytest.param("https://orcid.org/0000-0002-1825", id="short-id"),
    pytest.param("0000-0002-1825-009Y", id="bad-checksum-character"),
    pytest.param("0000000218250097", id="no-dashes"),
    pytest.param("https://ror.org/01abcde23", id="ror"),
    pytest.param("", id="empty"),
    pytest.param(None, id="none"),
    pytest.param(1234, id="number"),
]


@pytest.mark.parametrize(("value", "orcid"), _ORCIDS)
def test_an_orcid_is_read_from_an_id_or_its_url(value: str, orcid: str) -> None:
    assert orcid_id(value) == orcid
    assert _normalize_orcid(value) == orcid


@pytest.mark.parametrize("value", _NOT_ORCIDS)
def test_a_value_that_only_looks_like_an_orcid_names_none(value: Any) -> None:
    assert orcid_id(value) is None
    with pytest.raises(ValueError, match="invalid ORCID iD"):
        _normalize_orcid(value)


def _name_identifiers(same_as: str) -> list[dict[str, str]] | None:
    """The DataCite ``nameIdentifiers`` of a creator whose ``same_as`` is *same_as*."""
    dataset = battinfo.Dataset(name="Example data", creators=[{"name": "Carberry, Josiah"}])
    # Set on the stored creator, under the key the model keeps, so a value the model would refuse can be tried too.
    dataset.creators[0]["same_as"] = same_as
    return _datacite_creators(dataset)[0].get("nameIdentifiers")


@pytest.mark.parametrize("key", ["same_as", "sameAs"])
def test_datacite_names_the_orcid_of_a_creator_given_to_the_model(key: str) -> None:
    creator = {"type": "Person", "name": "Carberry, Josiah", key: ORCID_URL}
    dataset = battinfo.Dataset(name="Example data", creators=[creator])
    assert _datacite_creators(dataset)[0]["nameIdentifiers"] == [
        {"nameIdentifier": ORCID_URL, "nameIdentifierScheme": "ORCID", "schemeUri": "https://orcid.org"}
    ]


@pytest.mark.parametrize("same_as", [ORCID_URL, f"http://www.orcid.org/{ORCID}", f"orcid.org/{ORCID}"])
def test_datacite_names_an_orcid_for_a_url_on_the_orcid_host(same_as: str) -> None:
    assert _name_identifiers(same_as) == [
        {"nameIdentifier": same_as, "nameIdentifierScheme": "ORCID", "schemeUri": "https://orcid.org"}
    ]


@pytest.mark.parametrize(
    "same_as",
    [
        HOSTILE,
        f"https://orcid.org.evil.example/{ORCID}",
        f"https://sandbox.orcid.org/{ORCID}",
        "https://ror.org/01abcde23",
    ],
)
def test_datacite_names_no_orcid_for_a_url_on_another_host(same_as: str) -> None:
    assert _name_identifiers(same_as) is None


@pytest.mark.parametrize("same_as", [ORCID_URL, f"https://orcid.org/{ORCID}/", f"orcid.org/{ORCID}", ORCID])
def test_a_record_contributor_is_credited_by_the_orcid_its_same_as_names(same_as: str) -> None:
    agent = _agent_from_record_contributor({"name": "Carberry, Josiah", "same_as": same_as})
    assert agent == {"name": "Carberry, Josiah", "orcid": ORCID}
    assert _agent_node(agent)["@id"] == ORCID_URL


@pytest.mark.parametrize(
    "same_as", [HOSTILE, f"https://evil.example/people/{ORCID}", "https://ror.org/01abcde23", None]
)
def test_a_record_contributor_gets_no_orcid_from_a_url_on_another_host(same_as: str | None) -> None:
    agent = _agent_from_record_contributor({"name": "Carberry, Josiah", "same_as": same_as})
    assert agent == {"name": "Carberry, Josiah"}
    assert "@id" not in _agent_node(agent)
