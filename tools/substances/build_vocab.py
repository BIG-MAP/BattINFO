"""Build the substance vocabulary (substances.json) from the seed CSV.

Sources, joined on identity with loud failure on disagreement:
  1. seed.csv               - hand-reviewed (symbol, pubchem_cid, roles, ion refs)
  2. PubChem                - Title, InChIKey, SMILES, formula, molar mass, CAS
  3. domain-chemical-substance (chemsub) - EMMO class IRI, matched by PubChem CID

The emitted vocabulary is the runtime SSoT: the resolver never touches the
network, and the JSON-LD emitter uses it as the InChIKey -> EMMO IRI reverse
index. Only this script goes online, and only when a maintainer runs it.

Usage:
  python build_vocab.py                # uses cached fixtures where present
  python build_vocab.py --refresh      # refetch PubChem data into fixtures/
  python build_vocab.py --chemsub PATH # chemsub checkout (default: sibling Ontologies path)

Cross-checks (build fails or flags loudly):
  - every CID resolves at PubChem and returns an InChIKey
  - salt/IL SMILES equals the dot-join of its referenced ions' SMILES
  - a chemsub entry matched by CID must not disagree on InChI connectivity
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"
DEFAULT_CHEMSUB = Path(
    r"C:\Users\simonc\Documents\Github-local\Ontologies\domain-chemical-substance"
)
OUT = HERE.parent.parent / "src" / "battinfo" / "data" / "vocab" / "substances.json"

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=120) as resp:
        return json.load(resp)


def load_or_fetch(name: str, url: str, refresh: bool) -> dict:
    FIXTURES.mkdir(exist_ok=True)
    path = FIXTURES / name
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch_json(url)
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    time.sleep(0.2)  # PubChem rate courtesy
    return data


def read_seed() -> list[dict]:
    with open(HERE / "seed.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pubchem_properties(cids: list[int], refresh: bool) -> dict[int, dict]:
    url = (
        f"{PUG}/compound/cid/" + ",".join(map(str, cids))
        + "/property/Title,InChIKey,InChI,ConnectivitySMILES,MolecularFormula,MolecularWeight/JSON"
    )
    data = load_or_fetch("pubchem_properties.json", url, refresh)
    return {p["CID"]: p for p in data["PropertyTable"]["Properties"]}


def pubchem_cas(cid: int, refresh: bool) -> str | None:
    try:
        data = load_or_fetch(
            f"synonyms_{cid}.json", f"{PUG}/compound/cid/{cid}/synonyms/JSON", refresh
        )
    except Exception:
        return None
    syns = data.get("InformationList", {}).get("Information", [{}])[0].get("Synonym", [])
    for s in syns:
        if CAS_RE.match(s):
            return s
    return None


def parse_chemsub(chemsub_dir: Path) -> tuple[str, dict[int, dict]]:
    """Parse chemical-substance.ttl into {pubchem_cid: {iri, label, inchi}}.

    The TTL annotates each substance class with a PubChem compound URL and a
    standard InChI via hash-named annotation properties; we first read the
    property table (prefLabel -> property id) so the parse survives hash renames.
    """
    ttl = (chemsub_dir / "chemical-substance.ttl").read_text(encoding="utf-8")
    version = "unknown"
    try:
        version = subprocess.run(
            ["git", "-C", str(chemsub_dir), "describe", "--tags", "--always"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception:
        pass

    prop_ids = {}
    for m in re.finditer(
        r"###\s+\S+#(\S+)\s+:(\S+)\s+rdf:type\s+owl:AnnotationProperty\s*;.*?"
        r'skos:prefLabel\s+"([^"]+)"', ttl, re.S):
        prop_ids[m.group(3)] = m.group(2)
    inchi_prop = prop_ids.get("standardInChI")

    entries: dict[int, dict] = {}
    # Split on resource declarations; keep blocks that carry a PubChem compound URL.
    for block in re.split(r"\n###\s+", ttl):
        m_iri = re.match(r"(\S+)", block)
        m_cid = re.search(r"pubchem\.ncbi\.nlm\.nih\.gov/compound/(\d+)", block)
        m_label = re.search(r'skos:prefLabel\s+"([^"]+)"', block)
        if not (m_iri and m_cid and m_label):
            continue
        entry = {
            "iri": m_iri.group(1),
            "label": m_label.group(1),
            "inchi": None,
        }
        if inchi_prop:
            m_inchi = re.search(
                re.escape(f":{inchi_prop}") + r'\s+"([^"]+)"', block)
            if m_inchi:
                entry["inchi"] = m_inchi.group(1)
        entries[int(m_cid.group(1))] = entry
    return version, entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--chemsub", type=Path, default=DEFAULT_CHEMSUB)
    args = ap.parse_args()

    seed = read_seed()
    cids = sorted({int(r["pubchem_cid"]) for r in seed if r["pubchem_cid"]})
    props = pubchem_properties(cids, args.refresh)

    chemsub_version, chemsub = ("absent", {})
    if (args.chemsub / "chemical-substance.ttl").exists():
        chemsub_version, chemsub = parse_chemsub(args.chemsub)

    errors: list[str] = []
    warnings: list[str] = []

    smiles_by_symbol = {
        r["symbol"]: props.get(int(r["pubchem_cid"]), {}).get("ConnectivitySMILES", "")
        for r in seed if r["pubchem_cid"]
    }

    substances = []
    for r in seed:
        sym = r["symbol"]
        entry: dict = {
            "symbol": sym,
            "roles": [x for x in r["roles"].split("|") if x],
            "note": r["note"],
        }
        if r["pubchem_cid"]:
            cid = int(r["pubchem_cid"])
            p = props.get(cid)
            if not p:
                errors.append(f"{sym}: CID {cid} not returned by PubChem")
                continue
            if not p.get("InChIKey"):
                errors.append(f"{sym}: CID {cid} has no InChIKey")
                continue
            entry.update(
                identity_basis="structure",
                inchikey=p["InChIKey"],
                pubchem_cid=cid,
                label=p.get("Title", ""),
                smiles=p.get("ConnectivitySMILES", ""),
                formula=p.get("MolecularFormula", ""),
                molar_mass=float(p["MolecularWeight"]) if p.get("MolecularWeight") else None,
            )
            cas = pubchem_cas(cid, args.refresh)
            if cas:
                entry["cas_number"] = cas
            cs = chemsub.get(cid)
            if cs:
                entry["chemsub_iri"] = cs["iri"]
                entry["chemsub_label"] = cs["label"]
                if cs.get("inchi") and p.get("InChI") and cs["inchi"] != p["InChI"]:
                    # Compare the connectivity sublayer only: chemsub may record an ion
                    # as the deprotonated acid (/p-1, H kept in formula) while PubChem
                    # records the intrinsic ion (/q-1) - same species, different layers.
                    def c_layer(inchi: str) -> str | None:
                        for part in inchi.split("/"):
                            if part.startswith("c"):
                                return part
                        return None
                    core_a = c_layer(cs["inchi"])
                    core_b = c_layer(p["InChI"])
                    if core_a is not None and core_b is not None and core_a != core_b:
                        errors.append(
                            f"{sym}: chemsub InChI disagrees with PubChem for CID {cid}: "
                            f"{cs['inchi']!r} vs {p['InChI']!r}"
                        )
            else:
                warnings.append(f"{sym}: no chemsub class (CID {cid}) - ontology-additions candidate")
        else:
            entry.update(identity_basis="label", label=r["note"].split(";")[0])

        if r["cation_ref"] and r["anion_ref"]:
            for ref in (r["cation_ref"], r["anion_ref"]):
                if ref not in smiles_by_symbol:
                    errors.append(f"{sym}: ion ref {ref} not in seed")
            salt_parts = sorted(smiles_by_symbol.get(sym, "").split("."))
            ion_parts = sorted(
                [smiles_by_symbol.get(r["cation_ref"], ""), smiles_by_symbol.get(r["anion_ref"], "")]
            )
            if salt_parts != ion_parts:
                errors.append(f"{sym}: SMILES dot-join mismatch with ions {r['cation_ref']}/{r['anion_ref']}")
            entry["ions"] = {"cation": r["cation_ref"], "anion": r["anion_ref"]}
        substances.append(entry)

    # symbol collision sanity: same symbol may appear only with disjoint roles
    seen: dict[str, list] = {}
    for e in substances:
        seen.setdefault(e["symbol"], []).append(e)
    for sym, group in seen.items():
        if len(group) > 1:
            all_roles = [set(e["roles"]) for e in group]
            for i, a in enumerate(all_roles):
                for b in all_roles[i + 1:]:
                    if not a or not b or a & b:
                        errors.append(f"{sym}: colliding entries lack disjoint roles")

    if errors:
        print("BUILD FAILED:")
        for e in errors:
            print("  ERROR:", e)
        return 1

    seed_sha = hashlib.sha256((HERE / "seed.csv").read_bytes()).hexdigest()
    out = {
        "version": "0.1.0",
        "generated_from": {
            "seed_sha256": seed_sha,
            "chemsub_version": chemsub_version,
            "pubchem_fixture": "tools/substances/fixtures/",
        },
        "substances": sorted(substances, key=lambda e: (e["symbol"], e.get("pubchem_cid") or 0)),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    n_chemsub = sum(1 for s in substances if s.get("chemsub_iri"))
    n_cas = sum(1 for s in substances if s.get("cas_number"))
    print(f"OK: {len(substances)} substances -> {OUT}")
    print(f"    chemsub-linked: {n_chemsub}, CAS: {n_cas}, chemsub version: {chemsub_version}")
    for w in warnings:
        print("  note:", w)
    return 0


if __name__ == "__main__":
    sys.exit(main())
