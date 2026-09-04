"""Generate docs/records/ — one page per record family, the single door.

Every family page carries everything about its thing, in one place:

  1. curated model prose, injected from docs/records/_fragments/<slug>.md
     (edit the fragment, then regenerate — never the page),
  2. reference examples: authoring snippets whose SOURCE is what the page
     shows and whose EXECUTION produced the records beside them, each
     validated under the STRICT policy (generation fails on any issue) and
     emitted as JSON-LD where an emitter exists,
  3. a field reference generated from the packaged JSON Schemas — the same
     files `battinfo validate` and the registry gate enforce.

tests/test_reference_records.py regenerates the chapter in memory and fails
on drift, so any PR that changes what these pages show must regenerate them:

    uv run python scripts/gen_reference_records.py           # write
    uv run python scripts/gen_reference_records.py --check   # CI drift gate

The chapter is the review surface for change propagation: the git history of
docs/records/ is the record of how schema, API, and emitter changes reached
real examples.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Shared determinism helpers: the SAME uid-placeholder pool and timestamp
# freezing the web showcase uses, so one record authored in both surfaces
# renders identically in both.
_spec = importlib.util.spec_from_file_location(
    "gen_web_examples", Path(__file__).resolve().parent / "gen_web_examples.py"
)
assert _spec is not None and _spec.loader is not None
_web = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_web)
normalize = _web.normalize
snippet_source = _web.snippet_source

OUT_DIR = ROOT / "docs" / "records"
FRAGMENT_DIR = OUT_DIR / "_fragments"
SCHEMA_DIR = ROOT / "src" / "battinfo" / "data" / "schemas"
SCHEMA_URL_BASE = "https://w3id.org/battinfo/schema/"
NL = chr(10)

# Record-envelope keys shared by every family; everything else on a schema's
# top level is family content and gets rendered.
ENVELOPE_KEYS = {"schema_version", "provenance", "notes", "funding", "contributor", "license"}


# ── Snippets: the code shown on the page IS the code that ran ────────────────
# Each function returns the canonical record dict. Explicit IRIs/uids are shown
# the way the workspace would mint them; in the ws.add()/ws.save() flow you
# never set them yourself.


def snippet_cell_spec():
    from battinfo import CellSpec

    spec = CellSpec(
        # The published flagship IRI — dereference it (Accept:
        # application/ld+json) to get this exact record.
        id="https://w3id.org/battinfo/spec/pge5-wer6-2q82-v9k0",
        manufacturer="A123",
        model="ANR26650M1-B",
        format="cylindrical",
        chemistry="Li-ion",
        positive_electrode_basis="LFP",
        properties={
            "nominal_capacity": {"value": 2.5, "unit": "Ah"},
            "nominal_voltage": {"value": 3.3, "unit": "V"},
            "mass": {"value": 76.0, "unit": "g"},
        },
        source={"type": "datasheet", "retrieved_at": 1750000000},
    )
    record = spec.to_record()
    return record


def snippet_cell_instance():
    from battinfo import Cell, CellSpec

    spec = CellSpec(
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        manufacturer="Samsung SDI",
        model="INR21700-50E",
        format="cylindrical",
        chemistry="Li-ion",
    )
    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=spec,                    # every cell links to its spec
        serial_number="LAB-2026-0001",
        batch_id="2026-W03",
        manufactured_at="2026-01-15",
        source={"type": "lab", "retrieved_at": 1750000000},
    )
    record = cell.to_record()
    return record


def snippet_half_cell_spec():
    from battinfo import CellSpec

    spec = CellSpec(
        id="https://w3id.org/battinfo/spec/t4wz-ff8s-6vp6-af48",
        manufacturer="Example Lab",
        model="HC-GR-01",
        format="coin",
        chemistry="Li-ion",
        # The half-cell flavor: electrodes are named by ROLE, not polarity.
        cell_configuration="half_cell",
        # The design under test, referenced by its electrode-spec IRI.
        working_electrode_spec_id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        # The counter is described inline: lithium foil the lab treats as
        # interchangeable earns a description, not a tracked record. In a
        # two-electrode half cell it is also the potential reference.
        counter_electrode={
            "coating": {"component": {"active_material": [{"name": "Lithium metal"}]}}
        },
        source={"type": "lab", "retrieved_at": 1750000000},
    )
    record = spec.to_record()
    return record


def snippet_material_spec():
    from battinfo.api import create_material_spec

    record = create_material_spec(
        uid="7d9k-2m4p-8t3x-6nq5",
        name="NMC811 cathode powder",
        kind="nmc811",                     # Level-1 key from the curated vocabulary
        source_type="datasheet",
    )
    return record


def snippet_material():
    from battinfo.api import create_material

    record = create_material(
        uid="y9xy-kr0v-y5tn-dfj7",
        name="NMC811 lot 2026-04",
        material_spec_id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        source_type="lab",
    )
    return record


def snippet_electrode_spec():
    from battinfo.api import create_electrode_spec

    record = create_electrode_spec(
        uid="kxwy-5f5f-f682-hhch",
        name="NMC811 cathode design A",
        kind="nmc811",                     # the ACTIVE material's kind
        active_material_spec_id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        source_type="lab",
    )
    return record


def snippet_electrode():
    from battinfo.api import create_electrode

    record = create_electrode(
        uid="3w87-0ddf-ryjg-evxe",
        name="Cathode disc, cell LAB-2026-0001",
        electrode_spec_id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        source_type="lab",
    )
    return record


def snippet_separator_spec():
    from battinfo.api import create_component_spec

    record = create_component_spec(
        "separator",
        uid="6nec-h262-tthy-4rnt",
        name="Celgard 2500",
        source_type="datasheet",
    )
    return record


def snippet_electrolyte_spec():
    from battinfo.api import create_component_spec

    record = create_component_spec(
        "electrolyte",
        uid="0rp6-kncv-cyem-qwcd",
        name="1M LiPF6 in EC:EMC 3:7 + 2% VC",
        # Composition fields go through body= (the class field is also named
        # "family" — the function's first argument). Every constituent can
        # cite its material-spec by IRI, so the formulation is assembled from
        # materials, never retyped.
        body={
            "family": "organic",
            "salt": {
                "name": "LiPF6",
                "material_spec_id": "https://w3id.org/battinfo/spec/t4wz-ff8s-6vp6-af48",
                "cation": "Li+",
                "anion": "PF6-",
                "property": {"concentration": {"value": 1.0, "unit": "mol/L"}},
            },
            "solvent_mixture": {
                "component": [
                    {
                        "name": "EC",
                        "material_spec_id": "https://w3id.org/battinfo/spec/xcv1-hpy1-b0bw-z5s2",
                        "property": {"volume_fraction": {"value": 0.3, "unit": "1"}},
                    },
                    {
                        "name": "EMC",
                        "material_spec_id": "https://w3id.org/battinfo/spec/7p3d-2e22-7yae-spyb",
                        "property": {"volume_fraction": {"value": 0.7, "unit": "1"}},
                    },
                ]
            },
            "additive": [
                {
                    "name": "VC",
                    "material_spec_id": "https://w3id.org/battinfo/spec/s6y8-5mne-94gx-e5ve",
                    "property": {"mass_fraction": {"value": 0.02, "unit": "1"}},
                }
            ],
            "property": {"conductivity": {"value": 10.0, "unit": "mS/cm"}},
        },
        source_type="datasheet",
    )
    return record


def snippet_electrolyte():
    from battinfo.api import create_component_instance

    record = create_component_instance(
        "electrolyte",
        uid="me0t-k16f-eh5y-rq0k",
        spec_id="https://w3id.org/battinfo/spec/0rp6-kncv-cyem-qwcd",
    )
    return record


def snippet_test_protocol():
    from battinfo import TestSpec

    protocol = TestSpec(
        id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        name="1C cycle life at 25 degC",
        kind="cycling",
        experiment=[                       # PyBaMM syntax — runnable as-is
            "Charge at 1C until 4.2 V",
            "Hold at 4.2 V until C/20",
            "Discharge at 1C until 2.5 V",
            "Rest for 10 minutes",
        ],
        # Conditions are quantities ({value, unit}), by contract (#363).
        conditions={"ambient_temperature": {"value": 25.0, "unit": "degC"}},
        source={"type": "manual", "retrieved_at": 1750000000},
    )
    record = protocol.to_record()
    return record


def snippet_test():
    from battinfo import Cell, CellSpec, Test

    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=CellSpec(
            id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            manufacturer="Samsung SDI", model="INR21700-50E",
            format="cylindrical", chemistry="Li-ion",
        ),
        serial_number="LAB-2026-0001",
    )
    test = Test(
        id="https://w3id.org/battinfo/test/3w87-0ddf-ryjg-evxe",
        cell=cell,                         # what you did, to which cell
        kind="cycling",
        protocol_id="https://w3id.org/battinfo/spec/kxwy-5f5f-f682-hhch",
        protocol="1C cycle life at 25 degC",
        instrument="Biologic VMP-300",
        status="completed",
        # As-run conditions: what actually applied, as {value, unit}
        # quantities (planned conditions live on the protocol).
        conditions={"ambient_temperature": {"value": 24.6, "unit": "degC"}},
        started_at=1750000000,
        source={"type": "measurement", "retrieved_at": 1750000000},
    )
    record = test.to_record()
    return record


def snippet_dataset():
    from battinfo import Cell, CellSpec, Dataset, Test

    cell = Cell(
        id="https://w3id.org/battinfo/cell/y9xy-kr0v-y5tn-dfj7",
        cell_spec=CellSpec(
            id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
            manufacturer="Samsung SDI", model="INR21700-50E",
            format="cylindrical", chemistry="Li-ion",
        ),
        serial_number="LAB-2026-0001",
    )
    test = Test(
        id="https://w3id.org/battinfo/test/3w87-0ddf-ryjg-evxe",
        cell=cell, kind="cycling", status="completed",
    )
    dataset = Dataset(
        id="https://w3id.org/battinfo/dataset/6nec-h262-tthy-4rnt",
        name="INR21700-50E cycle-life dataset",
        description="Cycle-life time series for cell LAB-2026-0001.",
        cell=cell,
        test=test,
        license="https://creativecommons.org/licenses/by/4.0/",
        access_url="https://doi.org/10.5281/zenodo.1234567",
        download_url="https://zenodo.org/records/1234567/files/run.parquet",
        data_format="application/x-parquet",
        checksum_algorithm="md5",
        checksum_value="9e107d9d372bb6826bd81d3542a419d6",
        # Membership in a dataset series (a collection record): emitted as
        # dcat:inSeries and schema:isPartOf. The collection publishes first.
        series_id="https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
        source={"type": "measurement", "retrieved_at": 1750000000},
    )
    record = dataset.to_record()
    return record


def snippet_dataset_series():
    from battinfo import Dataset

    collection = Dataset(
        id="https://w3id.org/battinfo/dataset/0rp6-kncv-cyem-qwcd",
        name="INR21700-50E cycle-life collection",
        description="All cycle-life datasets of the 2026 INR21700-50E study.",
        # The series flavor: an ordinary dataset record, typed
        # dcat:DatasetSeries by this marker — no separate record type.
        additional_type=["DatasetSeries"],
        # The collection IS the deposit, so the deposit DOI is its own
        # external identifier.
        identifier={"property_id": "doi", "value": "10.5281/zenodo.1234567"},
        license="https://creativecommons.org/licenses/by/4.0/",
        access_url="https://doi.org/10.5281/zenodo.1234567",
        # No cell, test, or distributions: the member datasets carry those.
        source={"type": "catalog", "retrieved_at": 1750000000},
    )
    record = collection.to_record()
    return record


def snippet_equipment_spec():
    from battinfo.api import create_equipment_spec

    record = create_equipment_spec(
        id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        name="SkyRC MC3000",
        manufacturer="SkyRC",
        model="MC3000",
        equipment_class="cycler",          # category is data, never a namespace
        channel_count=4,
        supported_chemistries=["NiMH", "Li-ion", "LiFePO4", "Na-ion"],
    )
    return record


def snippet_equipment():
    from battinfo.api import create_equipment

    record = create_equipment(
        id="https://w3id.org/battinfo/equipment/y9xy-kr0v-y5tn-dfj7",
        equipment_spec_id="https://w3id.org/battinfo/spec/7d9k-2m4p-8t3x-6nq5",
        serial_number="MC3K-2026-0001",
        name="Cycler 1",
        location="Lab B",
        status="active",
    )
    return record


def snippet_channel():
    from battinfo.api import create_channel

    # The channel uid is deterministic from (unit, index): registering the
    # same bench twice never duplicates channels.
    record = create_channel(
        equipment_id="https://w3id.org/battinfo/equipment/y9xy-kr0v-y5tn-dfj7",
        index=1,
        label="MC3000-A/CH1",
    )
    return record


def snippet_parameter_set():
    from battinfo.api import create_parameter_set

    record = create_parameter_set(
        uid="fm9p-sqkk-tbx3-rr66",
        name="Graphite density claims, Smith 2026",
        material_kind="graphite",
        claims=[
            {
                "parameter": "density",
                "quantity": {"value": 2.26, "unit": "g/cm3"},
                "provenance_class": "literature",
            }
        ],
    )
    return record


def snippet_organization():
    # No authoring API exists for organizations yet, so the reference example
    # is the record itself (data-first, the documented fallback).
    record = {
        "schema_version": "0.2.0",
        "organization": {
            "id": "https://w3id.org/battinfo/organization/s6y8-5mne-94gx-e5ve",
            "short_id": "s6y85m",
            "type": "Manufacturer",
            "name": "Example Instruments",
            "url": "https://www.example-instruments.test",
            "same_as": ["https://ror.org/000000000"],
            "description": "Fictional bench-equipment manufacturer for this example.",
        },
        "provenance": {
            "source_type": "manual",
            "source_url": "https://www.example-instruments.test",
            "retrieved_at": 1750000000,
        },
    }
    return record


# ── Families ─────────────────────────────────────────────────────────────────
# One entry per record family = one page = the single door. `notice` lines
# name what a reader should find in the emitted JSON-LD — keep every claim
# true of the current output. `jsonld` names the record_to_jsonld type, or
# None where no emitter exists yet (the page says so instead of hiding it).

FAMILIES = [
    {
        "slug": "cells",
        "title": "Cells",
        "intro": (
            "How to describe a cell: the design as a **cell spec**, each "
            "physical unit as a **cell instance** under it."
        ),
        "sections": [
            {
                "heading": "A cell spec, from its datasheet",
                "fn": snippet_cell_spec,
                "record_type": "cell-spec",
                "notice": [
                    "The node is EMMO-typed (`BatteryCellSpecification`) and each "
                    "spec property becomes a typed quantity under `hasProperty`.",
                    "`schema:manufacturer` and `schema:model` carry the identity "
                    "that seeded the IRI.",
                ],
            },
            {
                "heading": "A cell instance under that spec",
                "fn": snippet_cell_instance,
                "record_type": "cell-instance",
                "notice": [
                    "`cell_spec_id` is the instantiation edge; the JSON-LD states "
                    "it as a reference to the spec node.",
                    "`schema:serialNumber` carries the physical identity.",
                ],
            },
        ],
        "schemas": ["cell-spec.schema.json", "cell-instance.schema.json"],
    },
    {
        "slug": "half-cells",
        "title": "Half cells",
        "intro": (
            "How to describe a half cell: one electrode under test against a "
            "counter/reference. Not a separate record type — a **cell** "
            "flavored by `cell_configuration: \"half_cell\"`, with electrodes "
            "named by role."
        ),
        "sections": [
            {
                "heading": "A coin half cell for electrode characterization",
                "fn": snippet_half_cell_spec,
                "record_type": "cell-spec",
                "notice": [
                    "The described device types as `HalfCellDevice` (never "
                    "`ElectrochemicalHalfCell`).",
                    "The working electrode emits under `hasWorkingElectrode` "
                    "as a reference to its spec; the counter node types as "
                    "BOTH `CounterElectrode` and `ReferenceElectrode`.",
                ],
            },
        ],
        "schemas": [],
        "field_reference_note": (
            "Half cells are cell records — the field reference lives on "
            "[Cells](cells.md#fields), and `cell_configuration`, "
            "the role holders, and their `*_spec_id` siblings appear in the "
            "cell-spec table there."
        ),
    },
    {
        "slug": "materials",
        "title": "Materials",
        "intro": (
            "How to describe a material: the manufactured product as a "
            "**material spec**, a physical lot or batch as a **material** "
            "instance, both under a curated Level-1 kind."
        ),
        "sections": [
            {
                "heading": "A material spec (the powder as a product)",
                "fn": snippet_material_spec,
                "record_type": "material-spec",
                "notice": [
                    "The `kind` resolves to the chemical-substance class IRI that "
                    "types the emitted node — the genome's aggregation axis.",
                ],
            },
            {
                "heading": "A material instance (one physical lot)",
                "fn": snippet_material,
                "record_type": "material",
                "notice": [
                    "`material_spec_id` links the lot to its product; the lot is "
                    "what an electrode batch actually consumed.",
                ],
            },
        ],
        "schemas": ["material-spec.schema.json", "material.schema.json"],
    },
    {
        "slug": "electrodes",
        "title": "Electrodes",
        "intro": (
            "How to describe an electrode: the design as an **electrode spec** "
            "(composition, route, design values), a physical coated disc or "
            "batch as an **electrode** instance."
        ),
        "sections": [
            {
                "heading": "An electrode spec (the design)",
                "fn": snippet_electrode_spec,
                "record_type": "electrode-spec",
                "notice": [
                    "`active_material_spec_id` cites the powder, so no design "
                    "points at a bare vocabulary key.",
                ],
            },
            {
                "heading": "An electrode (the disc in one cell)",
                "fn": snippet_electrode,
                "record_type": "electrode",
                "notice": [
                    "`electrode_spec_id` carries the design; a cell instance "
                    "points at this disc through `working_electrode_id`.",
                ],
            },
        ],
        "schemas": ["electrode-spec.schema.json", "electrode.schema.json"],
    },
    {
        "slug": "electrolytes",
        "title": "Electrolytes",
        "intro": (
            "How to describe an electrolyte: the formulation as an "
            "**electrolyte spec** (its family and its composition, assembled "
            "from material-specs), a mixed batch as an **electrolyte** "
            "instance."
        ),
        "sections": [
            {
                "heading": "An electrolyte spec (the formulation)",
                "fn": snippet_electrolyte_spec,
                "record_type": "electrolyte-spec",
                "notice": [
                    "The node types by its family (`OrganicElectrolyte`), and "
                    "the composition emits as typed constituents: the salt "
                    "under `hasSolute` (itself EMMO-typed, e.g. "
                    "`LithiumHexafluorophosphate`), the solvents under "
                    "`hasSolvent`, the additive under `hasAdditive`.",
                    "Every constituent cites its material-spec by IRI, so the "
                    "formulation is assembled from materials, never retyped.",
                ],
            },
            {
                "heading": "An electrolyte (one mixed batch)",
                "fn": snippet_electrolyte,
                "record_type": "electrolyte",
                "notice": [
                    "`spec_id` carries the formulation; the batch is what a "
                    "cell build actually consumed.",
                ],
            },
        ],
        "schemas": ["electrolyte-spec.schema.json", "electrolyte.schema.json"],
    },
    {
        "slug": "components",
        "title": "Components",
        "intro": (
            "How to describe the remaining cell components — separator, "
            "current collector, housing. The three families share one generic "
            "spec + instance surface; only their fields differ. Electrolytes "
            "ride the same machinery but have [their own page](electrolytes.md)."
        ),
        "sections": [
            {
                "heading": "A separator spec",
                "fn": snippet_separator_spec,
                "record_type": "separator-spec",
                "notice": [
                    "The same `create_component_spec(family, ...)` call authors "
                    "every component family; the family picks the schema.",
                ],
            },
        ],
        "schemas": [
            "separator-spec.schema.json", "separator.schema.json",
            "current-collector-spec.schema.json", "current-collector.schema.json",
            "housing-spec.schema.json", "housing.schema.json",
        ],
    },
    {
        "slug": "tests",
        "title": "Tests",
        "intro": (
            "How to describe testing: the plan as a **test protocol**, each "
            "execution on one cell as a **test**. Planned conditions live on "
            "the protocol; as-run conditions on the test; both are "
            "`{value, unit}` quantities by contract."
        ),
        "sections": [
            {
                "heading": "The protocol",
                "fn": snippet_test_protocol,
                "record_type": "test-protocol",
                "notice": [
                    "The PyBaMM-style `experiment` strings become the structured "
                    "`method` steps at the record top level, and the JSON-LD "
                    "emits a typed EMMO workflow (`prov:Plan` / `schema:HowTo`).",
                ],
            },
            {
                "heading": "The execution",
                "fn": snippet_test,
                "record_type": "test",
                "notice": [
                    "`hasTestObject` / `schema:object` point at the cell; "
                    "`dcterms:conformsTo` points at the protocol.",
                    "As-run conditions emit as `schema:PropertyValue` entries "
                    "under `schema:additionalProperty`.",
                ],
            },
        ],
        "schemas": ["test-protocol.schema.json", "test.schema.json"],
    },
    {
        "slug": "datasets",
        "title": "Datasets",
        "intro": (
            "How to describe measured data: a **dataset** record per data "
            "artifact, and a **dataset series** (collection) record for the "
            "deposit or study they belong to."
        ),
        "sections": [
            {
                "heading": "A member dataset",
                "fn": snippet_dataset,
                "record_type": "dataset",
                "notice": [
                    "`series_id` emits BOTH `dcat:inSeries` (the DCAT 3 "
                    "membership edge) and `schema:isPartOf` (what dataset "
                    "search engines read).",
                    "`about` links the cell and the test; the distribution "
                    "carries the download URL and checksum.",
                ],
            },
            {
                "heading": "The collection (dataset series)",
                "fn": snippet_dataset_series,
                "record_type": "dataset",
                "notice": [
                    "`@type` carries `dcat:DatasetSeries` alongside "
                    "`dcat:Dataset` — no new record type exists.",
                    "No `about` and no distributions: the members hold the cell "
                    "links and the files, and the strict policy admits that "
                    "for the series flavor only.",
                ],
            },
        ],
        "schemas": ["dataset.schema.json"],
    },
    {
        "slug": "equipment",
        "title": "Equipment",
        "intro": (
            "How to describe lab equipment: the product as an **equipment "
            "spec**, each bench unit as **equipment**, each addressable slot "
            "as a **channel**."
        ),
        "sections": [
            {
                "heading": "An equipment spec (the product)",
                "fn": snippet_equipment_spec,
                "record_type": None,
                "gap": "No JSON-LD emitter exists for equipment records yet; the "
                       "canonical record is the published form.",
            },
            {
                "heading": "An equipment unit",
                "fn": snippet_equipment,
                "record_type": None,
                "gap": "No JSON-LD emitter exists for equipment records yet.",
            },
            {
                "heading": "A channel on that unit",
                "fn": snippet_channel,
                "record_type": None,
                "gap": "No JSON-LD emitter exists for channel records yet.",
            },
        ],
        "schemas": ["equipment-spec.schema.json", "equipment.schema.json", "channel.schema.json"],
    },
    {
        "slug": "parameter-sets",
        "title": "Parameter sets",
        "intro": (
            "How to describe parameter claims: a **parameter set** is a batch "
            "of claims about a target, each naming a curated parameter, a "
            "quantity, and a provenance class."
        ),
        "sections": [
            {
                "heading": "A claim batch from the literature",
                "fn": snippet_parameter_set,
                "record_type": "parameter-set",
                "notice": [
                    "The claim batch emits as one `schema:Dataset` node: scalar "
                    "claims as EMMO-typed quantities, the target on "
                    "`schema:about`.",
                ],
            },
        ],
        "schemas": ["parameter-set.schema.json"],
    },
    {
        "slug": "organizations",
        "title": "Organizations",
        "intro": (
            "How to describe an organization — the manufacturers, labs, and "
            "publishers other records point at."
        ),
        "sections": [
            {
                "heading": "A manufacturer",
                "fn": snippet_organization,
                "record_type": None,
                "gap": "Three gaps meet on this family: no authoring API "
                       "(the record above is authored directly, data-first), "
                       "no JSON-LD emitter, and no entities-registry kind — "
                       "so organization records are outside the semantic "
                       "validation path and are checked against the JSON "
                       "Schema only.",
                "schema_only": "organization.schema.json",
            },
        ],
        "schemas": ["organization.schema.json"],
    },
]


# ── Field reference from the packaged JSON Schemas ───────────────────────────

def _type_str(prop: dict) -> str:
    """A compact, human-readable type for one schema property."""
    if "$ref" in prop:
        return "→ " + prop["$ref"].split("/")[-1].replace(".schema.json", "")
    if "const" in prop:
        return f"const `{prop['const']}`"
    if "enum" in prop:
        values = prop["enum"]
        shown = " \\| ".join(f"`{v}`" for v in values[:4])
        return shown + (f" … ({len(values)} values)" if len(values) > 4 else "")
    if "anyOf" in prop:
        parts = []
        for sub in prop["anyOf"]:
            part = _type_str(sub)
            if part not in parts:
                parts.append(part)
        return " or ".join(parts)
    kind = prop.get("type")
    if kind == "array":
        items = prop.get("items")
        return "array of " + (_type_str(items) if isinstance(items, dict) else "any")
    if kind == "object":
        if prop.get("patternProperties"):
            return "object (open keys)"
        return "object"
    if isinstance(kind, list):
        return " or ".join(kind)
    return kind or "any"


def _clean_description(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def render_field_tables(schema_file: str) -> str:
    schema = json.loads((SCHEMA_DIR / schema_file).read_text(encoding="utf-8"))
    top_props = schema.get("properties", {})
    top_required = set(schema.get("required", []))
    body_keys = [k for k in top_props if k not in ENVELOPE_KEYS]
    label = schema_file.replace(".schema.json", "")

    parts = [f"### {label} fields", NL, NL]
    parts += [
        f"Schema: [`{schema_file}`]({SCHEMA_URL_BASE}{schema_file}) · "
        f"required at top level: " + ", ".join(f"`{k}`" for k in schema.get("required", [])) + NL, NL,
    ]
    for key in body_keys:
        body = top_props[key]
        props = body.get("properties")
        if not isinstance(props, dict):
            description = body.get("description")
            marker = " (required)" if key in top_required else ""
            parts += [
                f"Top-level `{key}`{marker}: "
                + (_clean_description(description) if description else _type_str(body))
                + NL, NL,
            ]
            continue
        required = set(body.get("required", []))
        if len(body_keys) > 1:
            parts += [f"The `{key}` block:", NL, NL]
        parts += ["| Field | Type | Required | Description |", NL, "|---|---|---|---|", NL]
        for name, prop in props.items():
            if not isinstance(prop, dict):
                continue
            req = "yes" if name in required else ""
            desc = _clean_description(prop.get("description", ""))
            parts += [f"| `{name}` | {_type_str(prop)} | {req} | {desc} |", NL]
        parts += [NL]
    return "".join(parts)


# ── Build ────────────────────────────────────────────────────────────────────

def _validate_or_die(record: dict, where: str, *, schema_only: str | None = None) -> str:
    """Strict-validate; die loudly on ANY issue; return the verdict line.

    ``schema_only`` names a schema file for the one family the semantic
    validation path cannot reach (organizations have no entities-registry
    kind, so ``validate_record_report`` rejects them — a known gap the page
    states rather than hides).
    """
    import battinfo
    from battinfo.validate.record import validate_record_report
    from battinfo.validate.schema import validate_schema_data

    if schema_only is not None:
        schema = json.loads((SCHEMA_DIR / schema_only).read_text(encoding="utf-8"))
        report = validate_schema_data(record, schema)
        if not report.ok:
            raise SystemExit(
                f"gen_reference_records: the '{where}' reference record no longer "
                f"validates against {schema_only}."
            )
        return (
            "**Schema-validated** — 0 errors against "
            f"`{schema_only}` (battinfo {battinfo.__version__}); this family is "
            "outside the semantic validation path (see the known gap above)."
        )

    report = validate_record_report(record, policy="strict")
    if report.issues:
        details = NL.join(
            f"  - {issue.severity} {issue.code} at {issue.path}: {issue.message}"
            for issue in report.issues
        )
        raise SystemExit(
            f"gen_reference_records: the '{where}' reference record no longer "
            f"validates clean under the strict policy:{NL}{details}{NL}"
            "A reference record is contract — fix the record shape or the "
            "change that broke it, in this same PR."
        )
    return (
        "**Validated clean** — strict policy, 0 errors, 0 warnings "
        f"(battinfo {battinfo.__version__})."
    )


def build_sections(family: dict) -> list[dict]:
    from battinfo import record_to_jsonld

    sections = []
    for section in family["sections"]:
        record = normalize(section["fn"]())
        verdict = _validate_or_die(
            record,
            f"{family['slug']}: {section['heading']}",
            schema_only=section.get("schema_only"),
        )
        jsonld = (
            record_to_jsonld(record, section["record_type"])
            if section.get("record_type")
            else None
        )
        sections.append({**section, "record": record, "jsonld": jsonld, "verdict": verdict})
    return sections


# The chapter reads in assembly order: the parts a cell is made from first
# (materials up through components), then the flavored and full cells built
# from them, then what is done with a cell and what comes out of it.
_PAGE_ORDER = [
    "materials", "electrodes", "electrolytes", "components", "cells",
    "half-cells", "tests", "datasets", "equipment", "parameter-sets", "organizations",
]
assert sorted(_PAGE_ORDER) == sorted(f["slug"] for f in FAMILIES)
FAMILIES.sort(key=lambda f: _PAGE_ORDER.index(f["slug"]))


# ── Visible rules per page: the facts that change what you type ──────────────
# At most four per page; everything longer belongs in the design-notes
# fragment or a how-to guide.
PAGE_RULES: dict[str, list[str]] = {
    "materials": [
        "`kind` is required and curated: aliases resolve on input (NMC 811, LiFePO4, Si/Gr), an unknown kind is rejected at save.",
        "A kind's `roles` list is informative, never restrictive - the role a material plays is stated where it is used.",
        "The **spec** is the manufactured product (Targray NMC811, grade X); the **material** instance is one physical lot.",
        "Other records reference a material at whichever level you know - kind key, spec IRI, or lot IRI - and upgrade later without re-modeling.",
    ],
    "electrodes": [
        "`kind` names the active material, from the same curated vocabulary as powders; a non-active kind warns but saves.",
        "The **spec** is the coated design (composition, route, design values); the **electrode** instance is a physical disc or batch.",
        "`active_material_spec_id` cites the powder product, so a design never points at a bare vocabulary key.",
        "`polarity` is authored or absent; half and three-electrode cells name electrodes by role instead (see [half cells](half-cells.md)).",
    ],
    "electrolytes": [
        "`family` (organic, aqueous, ...) is required.",
        "The composition is assembled from materials: `salt`, `solvent_mixture.component[]`, and `additive[]` each cite a material-spec by IRI.",
        "The **spec** is the formulation; the **electrolyte** instance is one mixed batch.",
    ],
    "components": [
        "Separator, current collector, and housing share one generic surface: `create_<family>_spec(...)` or `create_component_spec(family, ...)`, plus the instance equivalents.",
        "Fields whose names collide with an argument go through `body={...}`.",
        "Family identifiers use underscores (`current_collector`); IRIs use hyphens.",
        "[Electrolytes](electrolytes.md) ride the same machinery but have their own page.",
    ],
    "half-cells": [
        "Not a record type: a cell with `cell_configuration` set to `half_cell`.",
        "Electrodes are named by **role** - `working_electrode` / `counter_electrode` (or their `*_spec_id` siblings) - never by polarity.",
        "In a two-electrode half cell the counter also carries the reference role; a `three_electrode_cell` separates them.",
        "Reference the working electrode's spec; describe the interchangeable counter (lithium foil) inline on its holder.",
    ],
    "cells": [
        "The **spec** is the design (the datasheet); the **cell** instance is one physical unit - the (spec, serial) pair makes re-registration a no-op.",
        "A spec composes from parts by IRI: seven optional `*_spec_id` reference fields (electrodes, electrolyte, separator, housing), checked at save.",
        "The as-built engineering layer (housing, tabs, `construction` geometry) follows one pattern: identity fields plus a `property` dict of quantities.",
        "An instance can name the physical parts inside it, e.g. `working_electrode_id` points at the disc.",
    ],
    "tests": [
        "The **protocol** is the plan; the **test** is one execution on one cell (`cell_id`), linked by `protocol_id`.",
        "Conditions are `{value, unit}` quantities - planned ones on the protocol, as-run ones on the test.",
        "PyBaMM-style `experiment` strings become structured `method` steps automatically.",
        "Deviations from the plan go in the test's `conformance` block.",
    ],
    "datasets": [
        "A dataset describes data files (URLs, checksums, measured variables); the files stay where they are published.",
        "`about` links the cell and the test the data came from.",
        "A **series** is an ordinary dataset flavored `additional_type: [\"DatasetSeries\"]`; members point at it with `series_id`, so the collection publishes first.",
    ],
    "equipment": [
        "**Spec** = the product; **equipment** = one bench unit (serial, location); **channel** = one addressable slot on a unit.",
        "Channel identity is deterministic from (unit, index): re-registering a bench never duplicates channels.",
        "Tests point at the unit and channel via `equipment_id` / `channel_id`.",
    ],
    "parameter-sets": [
        "A batch of **claims** about a target: each names a curated parameter, a quantity or curve, and a provenance class (literature, measured, fitted, assumed).",
        "Claims are records so sources can disagree; consumers select among them.",
    ],
    "organizations": [
        "Identity is the `same_as` registry link (ROR, Wikidata); the body carries the display name and its variants.",
        "Other records point here: `manufacturer.id` on specs, publisher on datasets.",
        "An `editorial` block records curation decisions (for example, supersession on a name change).",
    ],
}


# ── Common-example shelves ───────────────────────────────────────────────────
# The curated selection each family page surfaces from the CI-gated examples/
# corpus (the registry is the full library; this is the docs' reasonable
# selection). The only curated input is the pick list — display names are read
# from the record files at generation time, so renaming an example updates the
# shelf on regeneration and a deleted pick fails generation loudly.

REGISTRY_BROWSE = {
    "cells": "https://www.battery-genome.org/cells",
    "datasets": "https://www.battery-genome.org/datasets",
}
REGISTRY_BROWSE_DEFAULT = "https://www.battery-genome.org/explore"

SHELVES: dict[str, list[str]] = {
    "cells": [
        "cell-spec/A123__ANR26650M1-B.json",
        "cell-spec/research/cylindrical-detailed.example.json",
        "cell-spec/research/prismatic-detailed.example.json",
        "cell-spec/research/pouch-multilayer-detailed.example.json",
        "cell-spec/research/coin-detailed.example.json",
        "cell-spec/cell-spec-tme2-0sy6-q89b-8m92.json",
        "cell-spec/cell-spec-86k6-6tzd-c4sf-5s01.json",
        "cell-spec/cell-spec-jgyy-x3h5-drmv-5tn5.json",
    ],
    "materials": [
        "material-spec/npa4-0dnw-evyh-hhdm.json",
        "material-spec/5ms1-9jv8-hr54-mn4e.json",
        "material-spec/gwck-k5kf-ae1f-gfgc.json",
        "material-spec/jnab-ggw9-cbn8-hhjr.json",
        "material-spec/83bd-jmk7-2x47-s04a.json",
        "material-spec/bkrw-7shb-tzbm-j664.json",
        "material-spec/r5xt-4hrh-jm2k-yg4m.json",
        "material-spec/fpeg-3wg8-e6cs-2vn1.json",
        "material-spec/efxx-b9yg-wh00-d23a.json",
    ],
    "electrodes": [
        "electrode-spec/qfjh-7xyr-ga1k-tjez.json",
        "electrode-spec/d7qr-n581-74c3-7g7r.json",
        "electrode-spec/m6y0-tkfg-sn40-q10p.json",
        "electrode-spec/qw3j-we77-zzj1-ya55.json",
        "electrode/k81p-5wxb-gaph-z6ee.json",
    ],
    "electrolytes": [
        "electrolyte-spec/gpkh-74nj-6sdb-vcsc.json",
        "electrolyte-spec/gzt2-hrqq-gsfn-sp94.json",
    ],
    "components": [
        "separator-spec/wgym-4xfa-pws1-ek1b.json",
        "separator-spec/v94j-jm2h-t8d1-t5a6.json",
        "current-collector-spec/vkaf-f5bv-fwt2-e6yz.json",
        "current-collector-spec/z25y-gab5-hd3n-qfpr.json",
        "housing-spec/38af-bpnv-1zmm-32hs.json",
        "housing-spec/k2q4-dk79-g890-7veq.json",
        "housing-spec/ypyh-v38v-r276-snmk.json",
    ],
    "tests": [
        "test-protocol/test-protocol-8r2m-4v6k-9p3t-7n5x.json",
        "test-protocol/test-protocol-fj4k-hj6f-cd5v-36fb.json",
        "test-protocol/test-protocol-5v3n-8x1m-4k7p-9r2t.json",
        "test-protocol/test-protocol-j19t-9cm0-f219-zh4y.json",
        "test-protocol/test-protocol-7m4t-1n9v-6r3k-2p8x.json",
        "test-protocol/test-protocol-3p7k-2m9r-6t4n-1v8x.json",
        "test-protocol/test-protocol-wmqd-1fbt-zyya-k4bw.json",
        "test-protocol/test-protocol-t163-7ba5-r0kn-h9my.json",
    ],
    "datasets": [
        "dataset/dataset-nns1-gh5p-v5n1-td17.json",
        "dataset/dataset-nxv4-ecrt-9wnm-a2yt.json",
    ],
    "equipment": [
        "equipment-spec/rchb-csx8-3vp8-ekcs.json",
        "equipment/bw1k-j56y-r2ax-2adv.json",
    ],
    "parameter-sets": [
        "parameter-set/parameter-set-8qqs-rh43-wt8d-172n.json",
    ],
    "organizations": [
        "organization/A123.json",
        "organization/Celgard.json",
        "organization/EMPA.json",
    ],
}


def render_shelf(family: dict) -> str:
    picks = SHELVES.get(family["slug"], [])
    if not picks:
        return ""
    browse = REGISTRY_BROWSE.get(family["slug"], REGISTRY_BROWSE_DEFAULT)
    parts = [NL, "## Common examples", NL, NL]
    parts += [
        "A selection of real, validated records from the packaged examples "
        "corpus — each one click away, included from its single source under "
        f"`examples/`. The full, living library is the registry: "
        f"[browse it there]({browse})." + NL, NL,
    ]
    for rel in picks:
        path = ROOT / "examples" / rel
        if not path.is_file():
            raise SystemExit(
                f"gen_reference_records: shelf pick examples/{rel} does not exist "
                f"(page '{family['slug']}'). Fix the pick list or restore the example."
            )
        doc = json.loads(path.read_text(encoding="utf-8"))
        body = next(
            (v for k, v in doc.items() if k not in ENVELOPE_KEYS and isinstance(v, dict)),
            {},
        )
        name = body.get("name") or body.get("title")
        if not name:
            raise SystemExit(
                f"gen_reference_records: shelf pick examples/{rel} carries no name "
                "— shelf entries must be recognizable by name."
            )
        type_label = rel.split("/")[0]
        # Same three-view tabs as the reference examples. The Python view is
        # the load pattern (these records ship inside the wheel); the JSON-LD
        # view is emitted live where an emitter exists, so shelf entries are
        # one more surface where an emitter change must show its diff.
        loader = (
            "import json" + NL
            + "from importlib import resources" + NL + NL
            + "record = json.loads(" + NL
            + '    resources.files("battinfo")' + NL
            + f'    .joinpath("data/examples/{rel}")' + NL
            + '    .read_text(encoding="utf-8")' + NL
            + ")"
        )
        parts += [f"::::::{{dropdown}} {name} ({type_label})", NL]
        parts += [":::::{tab-set}", NL, NL]
        parts += ["::::{tab-item} Python", NL,
                  "The record ships in the installed wheel — load it as a starting point:", NL, NL,
                  "```python", NL, loader, NL, "```", NL, "::::", NL, NL]
        parts += ["::::{tab-item} Canonical record", NL,
                  f"```{{literalinclude}} ../../examples/{rel}", NL,
                  ":language: json", NL, "```", NL, "::::", NL, NL]
        jsonld = _shelf_jsonld(doc, type_label)
        if jsonld is not None:
            parts += ["::::{tab-item} JSON-LD", NL,
                      "Emitted by `record_to_jsonld`, hosted-context mode.", NL, NL,
                      "```json", NL, json.dumps(jsonld, indent=2, ensure_ascii=False),
                      NL, "```", NL, "::::", NL, NL]
        parts += [":::::", NL, "::::::", NL, NL]
    return "".join(parts)


# Record types record_to_jsonld can emit; equipment, channel, and organization
# records have no emitter yet (stated as known gaps on their pages).
_EMITTABLE_TYPES = {
    "cell-spec", "cell-instance", "test", "test-protocol", "dataset",
    "material-spec", "material", "electrode-spec", "electrode",
    "separator-spec", "separator", "current-collector-spec", "current-collector",
    "electrolyte-spec", "electrolyte", "housing-spec", "housing", "parameter-set",
}


def _shelf_jsonld(doc: dict, type_label: str):
    if type_label not in _EMITTABLE_TYPES:
        return None
    from battinfo import record_to_jsonld

    return record_to_jsonld(doc, type_label)


BANNER = (
    "<!-- GENERATED by scripts/gen_reference_records.py — do not edit this page." + NL
    + "     Model prose is injected from docs/records/_fragments/<slug>.md:" + NL
    + "     edit the fragment, then regenerate:" + NL
    + "     uv run python scripts/gen_reference_records.py" + NL
    + "     tests/test_reference_records.py fails when this page drifts. -->" + NL
)


VISIBLE_FRAGMENT_BUDGET = 25  # non-empty lines; overflow goes to <slug>-notes.md or how-to


def _notes_fragment(slug: str):
    path = FRAGMENT_DIR / f"{slug}-notes.md"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip() + NL


def _fragment(slug: str) -> str:
    """Optional extra VISIBLE prose. Hard-budgeted so pages stay scannable."""
    path = FRAGMENT_DIR / f"{slug}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip()
    n = sum(1 for line in text.splitlines() if line.strip())
    if n > VISIBLE_FRAGMENT_BUDGET:
        raise SystemExit(
            f"gen_reference_records: _fragments/{slug}.md carries {n} non-empty "
            f"lines (budget {VISIBLE_FRAGMENT_BUDGET}). Visible prose stays slim: "
            "move rationale to the design-notes fragment "
            f"(_fragments/{slug}-notes.md) or a how-to guide."
        )
    return text + NL


def render_page(family: dict, sections: list[dict]) -> str:
    parts = [BANNER, NL, f"# {family['title']}", NL, NL, family["intro"], NL, NL]
    for rule in PAGE_RULES.get(family["slug"], []):
        parts += [f"- {rule}", NL]
    if PAGE_RULES.get(family["slug"]):
        parts += [NL]
    visible = _fragment(family["slug"])
    if visible:
        parts += [visible, NL]

    parts += ["## Define one", NL]
    for section in sections:
        parts += [NL, f"### {section['heading']}", NL, NL]
        # One artifact, three views: the tabs mirror the Python/JSON pairing
        # the docs landing page already uses. Python first — the authoring
        # code is the teaching artifact; the JSON views are what it becomes.
        parts += ["::::{tab-set}", NL, NL]
        parts += [":::{tab-item} Python", NL, "```python", NL,
                  snippet_source(section["fn"]), NL, "```", NL, ":::", NL, NL]
        parts += [":::{tab-item} Canonical record", NL, "```json", NL,
                  json.dumps(section["record"], indent=2, ensure_ascii=False),
                  NL, "```", NL, ":::", NL, NL]
        if section.get("jsonld") is not None:
            parts += [":::{tab-item} JSON-LD", NL,
                      "Emitted by `record_to_jsonld`, hosted-context mode.", NL, NL,
                      "```json", NL,
                      json.dumps(section["jsonld"], indent=2, ensure_ascii=False),
                      NL, "```", NL, ":::", NL, NL]
        parts += ["::::", NL, NL]
        if section.get("gap"):
            parts += ["```{admonition} Known gap", NL, ":class: warning", NL, NL,
                      section["gap"], NL, "```", NL, NL]
        if section.get("notice"):
            parts += ["What to notice:", NL, NL]
            for line in section["notice"]:
                parts += [f"- {line}", NL]
            parts += [NL]
        parts += [section["verdict"], NL]

    parts += [render_shelf(family)]

    if not family["schemas"]:
        if family.get("field_reference_note"):
            parts += [NL, "## Fields", NL, NL, family["field_reference_note"], NL]
        _append_notes(parts, family)
        return "".join(parts)

    parts += [NL, "## Fields", NL, NL]
    parts += [
        "Generated from the packaged JSON Schemas — the same files "
        "`battinfo validate` and the registry's publish gate enforce. Every "
        "record also carries the shared envelope (`schema_version`, "
        "`provenance`, and optional `notes`, `funding`, `contributor`, "
        "`license`)." + NL, NL,
    ]
    for schema_file in family["schemas"]:
        parts += [render_field_tables(schema_file)]

    _append_notes(parts, family)
    return "".join(parts)


def _append_notes(parts: list, family: dict) -> None:
    notes = _notes_fragment(family["slug"])
    if notes is None:
        return
    parts += [NL, "## Design notes", NL, NL,
              ":::{dropdown} The reasoning behind the model", NL,
              notes, ":::", NL]


def render_index() -> str:
    rows = NL.join(
        f"| [{family['title']}]({family['slug']}.md) | "
        + " · ".join(s["heading"] for s in family["sections"]) + " |"
        for family in FAMILIES
    )
    toc = NL.join(family["slug"] for family in FAMILIES)
    return (
        BANNER + NL
        + "# Record types" + NL + NL
        + "One page per record family, and each page is the whole story: what "
        + "the thing is, a reference example (authoring code, the canonical "
        + "record it produces, the JSON-LD that record emits), and the field "
        + "reference from the JSON Schemas. When someone asks how to describe "
        + "a cell, a material, or a separator — the answer is one link below." + NL + NL
        + "Everything generated here is produced against the current library "
        + "on every change, validated clean under the strict policy, and "
        + "drift-gated: a schema, API, or emitter change must regenerate this "
        + "chapter in the same PR, so the git history of `docs/records/` is "
        + "the record of how changes propagate to real examples." + NL + NL
        + "Each page also carries a shelf of common, real examples — the "
        + "docs' reasonable selection; the registry is the full library." + NL + NL
        + "| Family | Reference examples |" + NL
        + "|---|---|" + NL
        + rows + NL + NL
        + "Coverage accounting (every schema property exercised by a reference "
        + "example, or waived with a reason) arrives with the next expansion "
        + "of this chapter." + NL + NL
        + "```{toctree}" + NL + ":hidden:" + NL + NL
        + toc + NL
        + "```" + NL
    )


def render_all() -> dict[str, str]:
    files = {"index.md": render_index()}
    for family in FAMILIES:
        files[f"{family['slug']}.md"] = render_page(family, build_sections(family))
    return files


def main() -> int:
    files = render_all()
    if "--check" in sys.argv:
        stale = []
        for name, text in files.items():
            path = OUT_DIR / name
            current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else ""
            if current != text.replace("\r\n", "\n"):
                stale.append(name)
        if stale:
            print(
                "docs/records/ drifts: " + ", ".join(sorted(stale))
                + " — run `uv run python scripts/gen_reference_records.py`",
                file=sys.stderr,
            )
            return 1
        print(f"reference records in sync ({len(files)} pages).")
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale_page in OUT_DIR.glob("*.md"):
        if stale_page.name not in files:
            stale_page.unlink()
    for name, text in files.items():
        (OUT_DIR / name).write_text(text, encoding="utf-8", newline=NL)
    print(f"Wrote {len(files)} pages -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
