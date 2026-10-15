# Publish a BPX parameter file

A [BPX](https://github.com/FaradayInstitution/BPX) file is a battery-model parameter set in the JSON format the PyBaMM project defined. In BattINFO one BPX file becomes one parameter-set record. The record holds every value of the file as claims grouped by part (cell, each electrode's material and build, separator, electrolyte, state), carries the file itself, and gets an IRI derived from the file's parameters. Anyone can then hand that IRI to a solver and run exactly those parameters, and search finds the file's graphite claims next to every other source's.

This page imports a small file, links it to its cell, attaches the file and publishes the record through a workspace. The last sections cover corrections, who owns an IRI, and how a reader gets from the IRI to a PyBaMM simulation.

## 1. Read the file

`from_bpx_parameters` reads the file and says what it holds. The example writes a small partial file so the page runs offline; pass the path of your own file instead.

```python
import json
from pathlib import Path

from battinfo.interop import from_bpx_parameters

bpx_file = Path("example-cell.bpx.json")
bpx_file.write_text(json.dumps({
    "Header": {"BPX": "1.1.0", "Title": "Example pouch cell", "Model": "Partial"},
    "Parameterisation": {
        "Cell": {
            "Nominal cell capacity [A.h]": 5.0,
            "Lower voltage cut-off [V]": 2.5,
            "Upper voltage cut-off [V]": 4.2,
            "Electrode area [m2]": 0.1,
            "Number of electrode pairs connected in parallel to make a cell": 1,
        },
        "Negative electrode": {
            "Particle radius [m]": 5.86e-6,
            "Thickness [m]": 8.52e-5,
            "Minimum stoichiometry": 0.03,
            "Maximum stoichiometry": 0.9,
            "Maximum concentration [mol.m-3]": 33133,
            "Surface area per unit volume [m-1]": 383959,
            "Diffusivity [m2.s-1]": 3.3e-14,
            "Reaction rate constant [mol.m-2.s-1]": 6.7e-11,
            "OCP [V]": {"x": [0.0, 0.5, 1.0], "y": [1.2, 0.2, 0.05]},
        },
    },
    "State": {"Initial conditions": {"Initial state-of-charge": 1.0}},
}, indent=2), encoding="utf-8")

result = from_bpx_parameters(bpx_file)
print(result.file_uid())                       # the record's uid, known before the record exists
print([part["part"] for part in result.parts])
print(result.not_imported)                     # BPX paths of values the record will not hold
for warning in result.warnings:
    print("-", warning)
```

The uid comes from the SHA-256 of the file's canonical JSON (RFC 8785), so a re-indented copy, a CRLF checkout or a copy written by another JSON library has the same uid, and any changed value gives a new one. The record's IRI is `https://w3id.org/battinfo/dataset/<uid>`: a parameter set is a dataset, one piece of data from one source, so it shares the `dataset/` namespace with dataset records (IDENTIFIER_POLICY 6.3). A file that repeats a key inside an object is refused, because JSON parsers disagree on which of the two values counts.

Some values have no home in a record yet: the `Particle` blocks of a blended electrode, the initial hysteresis state, `Degradation` and `Validation`. They are named in the warnings and listed in `not_imported`, which the record keeps, so a reader knows what only the file holds. `to_bpx(record)` says so too, and sets `complete=False` on its result.

A transport value of zero or less (an ionic conductivity, a diffusivity, a transference number) cannot drive a physics model, and in published files it usually marks a placeholder for a model kept elsewhere, such as in `User-defined`. Such a value is read as the file states it, so the record still says exactly what the file says, and a warning names its BPX path and value. The claim gets no provenance class, and validating the record warns about it every time (`semantic.parameter_transport_not_positive`).

## 2. Say which cell the file describes

BattINFO never guesses the cell. Pass exactly one link:

- The cell is in the genome: `cell_spec_id=` its cell spec IRI, or `cell_instance_id=` the one physical cell a fit was made on. Search first (`ws.search(...)`, or [Find existing records](find-existing-records.md)).
- It is a real cell that is not in the genome yet: search for a duplicate by maker and model. If there is none, describe the cell spec with its identity only (name, maker, model, format, chemistry) and, if the maker has no organization record, create that too. Then link the new spec. The file's numbers (capacity, cut-offs, geometry, temperatures) stay on the parameter set as cell claims; they do not go on the spec.
- There is no real cell, as for an example file or a made-up design: `virtual_cell=True`.

The rest of this page takes the second path, as if the example file described a real cell, Example Lab's EX-5. A cell spec written as a draft file gets its IRI only when the workspace saves it, so save it before you build the parameter set. The search below runs offline and only looks in the workspace; with the default `registry_url` it searches the genome as well.

```python
import battinfo

ws = battinfo.workspace("bpx-lab", registry_url=None)
ws.license("cc-by-4.0")
print(ws.search("Example Lab EX-5"))  # []: the cell is not described yet

draft = Path("bpx-lab") / "example-lab-ex-5.cell-spec.json"
draft.write_text(json.dumps({
    "name": "Example Lab EX-5",
    "manufacturer": "Example Lab",
    "model": "EX-5",
    "format": "pouch",
    "chemistry": "li-ion",
}, indent=2), encoding="utf-8")
spec = ws.load(draft.name)  # a relative draft path resolves against the workspace root
ws.save()                   # the draft gets its IRI here
cell_spec_id = spec.id
print(cell_spec_id)
```

BPX does not name its materials, so name each electrode's material with `materials=` to make its claims findable by material. A value is a material kind (`battinfo.materials.material_kind_keys()` lists them) or a material-spec IRI. Leave out an electrode that is blended: its per-particle values are not imported yet, so there is no material part to name.

Each claim can say how its value was obtained. BPX does not say, so the claims of the `cell` and `state` parts get no provenance class: a file's capacity, cut-offs, geometry and temperatures may be datasheet values or conventions as easily as fits. The material, electrode, separator and electrolyte claims are marked `fitted` (`default_provenance_class=` changes that), except a zero or negative transport placeholder, which gets no class either. If you know where a part's values came from, say so by part name, for example `provenance_classes={"cell": "measured"}`.

## 3. Put the file where a solver can fetch it

The record points at the file's exact bytes, with their SHA-256, at an https URL whose content never changes. There are two ways to get such a URL today:

- The registry's artifact store. Uploads are run by a registry operator for now (`scripts/publish_artifact_release.py` in battinfo-registry). The files land under `parameter-sets/<uid>/v1/<file name>`, which is why `result.file_uid()` is useful before the record exists.
- Any https archive at a fixed version: a Zenodo record version, a GitHub raw URL pinned to a commit (not to a branch), an institutional repository. Not a URL whose content can change. A GitHub or GitLab raw-file URL that names a branch or a tag instead of a commit earns a warning.

`bpx_file_distribution` hashes the bytes and builds the entry. `check_bpx` records whether the official `bpx` parser accepts the file:

```python
from battinfo.interop import bpx_file_distribution, check_bpx

source = bpx_file_distribution(
    bpx_file,
    content_url="https://files.example.org/parameter-sets/example-cell.bpx.json",
    checks=[check_bpx(bpx_file)],
)
print(source["checksum"]["value"], source["checks"][0]["passed"])
```

A passing `bpx_parse` check means the parser accepts the file, not that a solver runs it. If you ran a simulation, say a 1C discharge in PyBaMM, record it as a second check named `simulation_smoke`.

Some files need software beyond BPX itself. About:Energy's files made with AEPyBaMM keep functions in their `User-defined` block that only that package evaluates, so their entry says `software_requirements=["aepybamm>=0.2.3"]`.

### A runnable copy, when the parser rejects the file

Some exporters write a file that declares BPX 1.0 or later but keeps the v0.x layout, with the temperatures in `Cell` and the initial electrolyte concentration in `Electrolyte`. The BattMo export of Schmitt et al. 2026 is one. Every parser since BPX 1.0 rejects such a file. `upgrade_bpx` rewrites it in the v1 layout: it moves those fields into `State` and adds the State values the bpx package's own v0-to-v1 migration adds (an initial state of charge of 1, and the temperatures it resolves), naming each one. Upload the result next to the source and attach it with role `runnable`:

<!-- doc-snippet: skip -->
```python
from battinfo.interop import upgrade_bpx

upgraded = upgrade_bpx("schmitt2026_hydra.json")
upgraded.save("schmitt2026_hydra.runnable.bpx.json")
runnable = bpx_file_distribution(
    "schmitt2026_hydra.runnable.bpx.json",
    content_url="https://files.example.org/parameter-sets/<uid>/v1/schmitt2026_hydra.runnable.bpx.json",
    role="runnable",
    derived_from=source["checksum"]["value"],
    conversion=upgraded.conversion_note("battinfo 0.8.0"),
)
```

A runnable copy is only ever that conversion. `to_parameter_set(..., runnable_file=...)` refuses a copy whose parameters differ from `upgrade_bpx` of the source, and the registry checks the same thing when it downloads the files. Make one only when the parser rejects the source; next to a source that parses, it earns a warning.

### Mirrors

The same bytes served from another place go in with role `mirror`. Build the entry from the same file, so the checksum matches the source's: `bpx_file_distribution(bpx_file, content_url=..., role="mirror")`.

## 4. Build the record and publish it

The record goes into a workspace like any other: `ws.add("parameter_set", record=...)` queues it, `ws.save()` validates and writes it, and `ws.submit()` sends what the last save wrote to the registry's review queue.

`ws.submit()` validates every record under the `publisher` policy before it contacts the registry, and that policy requires the file. A record without its source saves for local work (the default policy says nothing, `strict` warns) but is refused at submission, and nothing is sent. The credentials below are placeholders that are never used, because the check comes first:

```python
from battinfo.ws import SubmitError

draft = result.to_parameter_set(cell_spec_id=cell_spec_id, materials={"negative": "graphite"})
ws.add("parameter_set", record=draft)
ws.save()
try:
    ws.submit(
        registry_url="https://registry.example.org", api_key="placeholder",
        workspace_id="placeholder", publisher_id="placeholder",
    )
except SubmitError as exc:
    print(exc.failed[0]["error"])  # "a parameter file is published with its file: attach the source"
```

Attach the file and add the record again. It has the same IRI, because it is the same file, so it replaces the draft:

```python
record = result.to_parameter_set(
    cell_spec_id=cell_spec_id,
    materials={"negative": "graphite"},
    distributions=[source],
)
ws.add("parameter_set", record=record)
ws.save()
```

With your registry credentials (from `ws.login(...)` or the `BATTINFO_*` environment variables), submit it:

<!-- doc-snippet: skip -->
```python
ws.submit()
```

The checks that bind the record to its file are errors under every policy: the IRI must be the one `parameters_sha256` gives, a runnable copy must name the source's checksum, and a mirror must carry the source's checksum. The registry also downloads the files and checks them itself: the source's checksum and fingerprint, the runnable copy against the conversion of the source, and each mirror's checksum.

## Corrections

A corrected file has other parameters, so it is a new record with a new IRI. The old IRI keeps resolving to the old file, because a solver may already have been handed it. Name the record the new one replaces:

<!-- doc-snippet: skip -->
```python
record = from_bpx_parameters("corrected.bpx.json").to_parameter_set(
    virtual_cell=True,
    distributions=[corrected_source],
    supersedes="https://w3id.org/battinfo/dataset/<old uid>",
)
```

Only the publisher of the old record can supersede it. The registry refuses a `supersedes` from anyone else; when it accepts the new record, it marks the old one superseded and points it at the new one.

## Records published under spec/

Parameter sets published before 2026-10-11 have `spec/` IRIs, and they keep them: the old IRI keeps resolving, and a local copy still loads, validates and is found by its IRI, with the warning `semantic.parameter_set_legacy_namespace`, which names the `dataset/` IRI of its replacement. Nothing is published under `spec/` any more, though, so the `publisher` policy makes that warning an error, and `ws.submit()` and `ws.zenodo()` refuse the record. Its new version is a new `dataset/` record that supersedes it, and `supersede_parameter_set` builds it. The IRI is minted from the current seeds (a file's from its `parameters_sha256`, a claim batch's from its target, scope and name), `supersedes` names the old IRI, and everything else is copied as it is, the file entries included, since a file's URL is not its identity. For the Schmitt et al. 2026 file:

<!-- doc-snippet: skip -->
```python
from battinfo.api import supersede_parameter_set

old = json.loads(Path("parameter-set-szxp-xwnx-vhyf-rvm0.json").read_text(encoding="utf-8"))
new = supersede_parameter_set(old)
print(new["parameter_set"]["id"])          # https://w3id.org/battinfo/dataset/7jnc-cjtw-5h3a-5t52
print(new["parameter_set"]["supersedes"])  # https://w3id.org/battinfo/spec/szxp-xwnx-vhyf-rvm0
ws.add("parameter_set", record=new)
ws.save()
```

Do not move the old uid to `dataset/` by editing the IRI. A uid is never reused, not even under another namespace, so a `dataset/` record that keeps the uid it had under `spec/` is refused under every policy, whether or not it names the old record in `supersedes`. Once both records sit in a workspace, `query_parameter_sets` and `collate_claims` return the new one only, and `ws.zenodo()` deposits the new one and leaves the old one out, saying so. You can keep the old file; there is no need to delete it.

## Who owns a file's IRI

The first publisher to submit a file owns its IRI. Another publisher submitting the same parameters, in any formatting, is refused. The owner can publish new versions of the record (a corrected cell link or material name, say), but the source file stays the one first given: a new version keeps the same source checksum. Values that differ only beyond double precision (`0.1000000000000000001` and `0.1`) are the same number in JSON, so they share an IRI.

## From the IRI to PyBaMM

The `battery-genome` client reads the record, downloads its BPX file (the runnable copy when there is one), checks the bytes against the record's SHA-256 and returns the JSON, which PyBaMM takes as it is:

<!-- doc-snippet: skip -->
```python
import battery_genome as bg
import pybamm

doc = bg.bpx("https://w3id.org/battinfo/dataset/<uid>")
parameter_values = pybamm.ParameterValues.create_from_bpx_obj(doc)
```

Without Python, ask the IRI for the file. curl does not check the checksum; the client does.

```bash
curl -L "https://w3id.org/battinfo/dataset/<uid>?format=bpx" -o cell.bpx.json
```
