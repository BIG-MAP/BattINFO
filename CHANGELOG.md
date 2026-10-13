# Changelog

All notable changes to BattINFO are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

---

## [Unreleased]

## [0.8.0] - 2026-10-13

0.8.0 is the first release of `battinfo` on PyPI (`pip install battinfo`). Version 0.7.0 was never tagged or uploaded, so 0.7.x users installed it from a Git checkout. This release gives one record model and SDK for describing and publishing battery data: 22 record types from materials to datasets, each with a JSON Schema, a JSON-LD emitter and a stable `https://w3id.org/battinfo/` IRI minted from the record's identity, so saving the same thing again, or from another folder, gives the same IRI. The workspace (`battinfo.workspace()`) goes from raw cycler files to validated records, a Zenodo deposit and the registry review queue, and the new `battinfo.registry.Registry` reads published records and data files back (provisional in 0.8). BPX parameter files import as one parameter-set record that exports back to BPX, and a dataset collection groups datasets into a DCAT dataset series. Code written for 0.7.x needs some changes: the record classes are now `CellSpec`, `Cell`, `TestSpec`, `Test` and `Dataset`, the `*Input` classes are replaced by those models, `battinfo.Workspace` gives way to `battinfo.workspace()`, and pandas, pyarrow, openpyxl and rocrate moved into the `tabular` and `publish` extras; the old names keep importing with a `DeprecationWarning` for one more release. Records and their JSON-LD changed as well: material, electrode and the other component specs now mint under `spec/` like cell and test specs, a spec's physical facts sit on the individual under `isDescriptionFor`, and older keys such as `co_type` and `solvent_mixture` still load but are written in their new form. Some identity seeds changed during this cycle (a cell with both a name and a serial number, a dataset made from a local file), so re-saving such a record from 0.7.x code can give a new IRI; pin one you already published with `iris=` on `ws.add("cell")` or `dataset_iris=` on `ws.add("test")`.

### Known limitations

The gaps known at release, with workarounds where they exist, are listed in [Scope and capabilities](docs/scope.md#known-limitations-in-080): BPX files with blended electrodes or a hysteresis state, a set of workspace and submission papercuts, a new version of a published dataset that loses its preview files unless they are copied across, and the batterydf release candidate behind the `processing` extra.

### Added

- **A BPX file is one parameter-set record, addressed by its parameters.** `from_bpx_parameters(path).to_parameter_set(...)` turns one BPX file into one record that holds every value of the file, grouped by part: `cell`, each electrode's material part (OCP, diffusivity, stoichiometry window) and electrode part (thickness, porosity), `separator`, `electrolyte` and `state`. The Cell and State blocks are claims now as well, read the same from the v0.x layout and from the v1 `State` block, and `model_context.layout` (`v0` or `v1`) records which layout the file actually uses, since a file declaring BPX 1.0 may keep the v0.x one. The parameter vocabulary goes from 0.1.0 to 0.2.0 for this: a `state` scope, keys for the Cell and State values (nominal capacity, both cut-offs, the electrode area of one electrode pair and the pair count, volume, lumped density, specific heat capacity and thermal conductivity, reference, initial and ambient temperature, initial state of charge, heat transfer coefficient) and `ocp_hysteresis_decay_constant`, and a BPX mapping may name the BPX unit when it differs from the canonical one. A single-phase electrode's `OCP (lithiation) [V]` and `OCP (delithiation) [V]` tables are `ocp` curves with their `branch`. The `User-defined` block rides the record verbatim as its `annex`. What the record does not model yet (blended-electrode `Particle` blocks, initial hysteresis state, `Degradation`, `Validation` curves, unknown fields) is named in a warning and listed by BPX path in the record's new `not_imported` field. The caller says which cell the file describes, with exactly one of `cell_spec_id`, `cell_instance_id` or `virtual_cell=True`: the importer never guesses and creates no cell record, and a cell spec made for a new cell gets its identity only, since the file's cell numbers stay on the parameter set. The record's uid derives from the SHA-256 of the file's RFC 8785 canonical JSON, stored on the record as `parameters_sha256`, so a re-indented or CRLF copy, or one written by another JSON library that spells `1.0` as `1`, lands on the same IRI and any changed value mints a new one; the record validator refuses an `id` the fingerprint does not give under every policy (IDENTIFIER_POLICY 6.3, amended). The canonicaliser is vendored in `battinfo._jcs`, which also parses files strictly: a repeated key is refused with its path (JSON parsers disagree on which value counts), a UTF-8 byte order mark is skipped, and a number too large for a double or a NaN is refused in those words. A part's `phase` (reserved for blended electrodes) is allowed on material parts only. `ws.add("parameter_set", record=...)` queues a ready-built parameter-set record of either flavour, so `ws.save()` and `ws.submit()` publish it like any other record. A corrected file is a new record that names the old one in the new `supersedes` field (`to_parameter_set(supersedes=...)`, `dcterms:replaces` in JSON-LD). `query_parameter_sets` and `collate_claims` read the parts, so a search by material finds a file's material parts next to the literature claim batches. In JSON-LD the parts are blank `schema:Dataset` nodes under `schema:hasPart` and the fingerprint is a `schema:identifier`. Every claim node, in parts and in claim batches, names its parameter key in `schema:propertyID`, so `electrode_area` and `external_surface_area`, both an `Area`, stay apart in RDF. Seven of the new keys type as published EMMO classes (SpecificHeatCapacity, ThermalConductivity, ThermodynamicTemperature for the reference and initial temperatures, StateOfCharge, SurfaceCoefficientOfHeatTransfer, NumberOfEntities). `ambient_temperature` and `ocp_hysteresis_decay_constant` have no published class yet, so their claims are typed by value basis alone and validation warns `semantic.property_unmapped`; both are on the upstream list. The property reference lists the keys that are parameter-set claims only in a section of their own instead of as cell-spec properties. The five FaradayInstitution/BPX examples (MIT, (c) 2022 University of Oxford) ship as five such records, marked `virtual_cell` and with their source pinned to a commit of that repository. The how-to [Publish a BPX parameter file](docs/howto/publish-a-bpx-parameter-file.md) walks through it.
- **A parameter-file record carries its file, and the file is checked.** The file rides the record under `distributions`: exactly one `source`, checked against the bytes the parameters were read from, at most one `runnable` conversion, and any number of `mirror` copies of the same bytes, all on https, with checks named `bpx_parse` or `simulation_smoke`. `bpx_file_distribution` builds an entry from a file. A runnable copy needs `runnable_file=`: its sha256 must be its entry's checksum and its parameters those of `upgrade_bpx` applied to the source, so it can only be the source's layout conversion. `upgrade_bpx` rewrites a file in the v0.x layout (a 0.x file, or one that declares BPX 1.0 or later and keeps the old fields, as the BattMo export of Schmitt et al. 2026 does) in the v1 layout. It moves the fields BPX 1.0 relocated and adds the State values the bpx package's own migration adds when a file has none (initial state of charge 1, the ambient temperature from the reference temperature or 298.15 K, the initial temperature from the ambient one), naming each in its changes and in `conversion_note`; the lumped thermal conductivity moves to `User-defined`, where the bpx package drops it. The conversion is one standard-library module, `battinfo._bpx_layout`, which the registry vendors to check runnable copies. `check_bpx` records whether the official `bpx` parser accepts a file, with every parser warning in full and first. `to_bpx(record)` rebuilds the BPX document from the parts, at the file's own version or at `bpx_version=`, in that version's layout; a record whose `model_context.layout` is `v0` exported at 1.x goes through the same conversion, so the FaradayInstitution hysteresis example exported at 1.1.0 now gives PyBaMM the original's 1C capacity (12.254 Ah, where the missing initial state of charge gave 13.139 Ah). A value in another unit than BPX states is converted, a curve's x axis included, or the export raises `ValueError` naming the claim, as it does for a curve tabulated against another quantity than its BPX field and for an OCP branch at a 0.x version. `Header.BPX` is written as a string. The result's `complete` is false and its warnings say so when the document lacks a value the source file held (`strict=True` raises instead), and when the `bpx` package is installed its verdict on the document is in the warnings. An input that is neither a parameter-file record nor a cell spec raises `TypeError`; a registry resource JSON is unwrapped. On the eleven single-phase BPX files in our test corpus the official parser accepts the result and Parameterisation and State come back value for value. The record validator holds the file rules (a runnable naming its source, a mirror carrying the source's checksum, each part once) as errors under every policy. A parameter file without a source is fine for local work, a warning under `strict` and an error under `publisher`, so `ws.submit()` refuses it before sending anything. A record that is neither flavour gets a message saying what is missing or misplaced instead of a dump of the record, and a distributions count error names the role. In JSON-LD each file is a `schema:DataDownload` with `dcterms:conformsTo` and `schema:sha256`, and a conversion points at its source with `prov:wasDerivedFrom`.

- **Research titles lead with their source.** `battinfo.naming.title_for()` takes `source=` (author and year), so a title reads `Flores 2026 graphite AQ-1 electrode spec` and stays distinguishable among many graphite records. A common-word subject loses its capital after the source; abbreviations keep theirs. Products keep their manufacturer-and-model titles, and a collection's label names its source.

- **`ws.add("test", data=...)` can put its datasets in a collection.** `series_id=` takes the collection's dataset IRI (`https://w3id.org/battinfo/dataset/...`) and sets it on every dataset made from `data=`, so members whose data files are on disk no longer have to be written with `battinfo.Dataset` and `battinfo.save_dataset`. The IRI form is checked before anything is created, and `series_id=` without `data=` is refused. Membership is not identity: the test and dataset IRIs are the same with or without it. The collection itself is still made with `Dataset` and `save_dataset`. docs/howto/publish-a-dataset-collection.md shows the route in a new section.

- **Products are named by their manufacturer and model.** `battinfo.naming.handle_for()` and `title_for()` take `manufacturer=` and `model=` for the spec types a manufacturer or supplier makes (`PRODUCT_KINDS`). The handle is `<manufacturer>/<model>-<kind>` (`samsung-sdi/inr18650-35e-cell-spec`) and the title is the manufacturer's name and the model with no kind words (`Samsung SDI INR18650-35E`); a model that repeats the maker's name is not doubled. The group is the manufacturer's organization handle when the reference carries one, so two spellings of one company land in one group. `organization_handle()` builds an organization's handle, a single bare segment that, like a collection's, carries no kind word, and the kind-word warning no longer asks organizations for one.

- **Records can carry a handle, and `battinfo.naming` builds handles and titles.** Every record type now has an optional `handle` next to its `name`: a short slug such as `flores-ocv/graphite-aq-1-063b77-cell`, unique within one registry workspace and shown as `<workspace>/<handle>`. It is display text, never identity, so it can be corrected without moving the IRI. The schemas define it once per file as `$defs/Handle` (lowercase ASCII segments joined by `/`, each made of letters and digits separated by single hyphens, at most 120 characters), so a handle off that grammar is a `schema.pattern` error. A handle that follows the grammar but does not end with its record type's kind word (`cell-spec`, `material-lot`, `test-spec`, ...) gets a `semantic.handle_kind_word_expected` warning, under every policy; collections carry no kind word and are not checked. `battinfo.naming.handle_for()` and `title_for()` build both names from structured parts (group, material kind, the source's variant label with its material prefix dropped, sample, method), `KIND_WORDS` holds one kind word per entity kind, and `is_valid_handle()` checks the grammar. `record_to_jsonld()` emits the handle as one more `schema:identifier`, a `schema:PropertyValue` with `schema:propertyID` `battinfo-handle`, so no context term was added. The record models, the `battinfo.api` builders, `ws.add(...)` (cells take `handles=[...]`) and the draft files read by `ws.load()` all accept a handle; none of them makes one up. How-to: docs/howto/name-your-records.md. The registry and the website vendor the schemas and need a re-sync.

- **`ws.add("test")` can pin a published identity.** A test's IRI is seeded from its cell, type, protocol and name, and its datasets' IRIs from the test and their own names, so retitling a test minted a new test and new datasets. `iri=` (a full `https://w3id.org/battinfo/test/...` IRI) or `uid=` now pins the test, and `dataset_iris=[...]` pins the datasets made from `data=`, one per file in order. They are checked before anything is created, and a pin already used by another test in the session is refused.

- **How-to: publish a dataset collection.** A new page, `docs/howto/publish-a-dataset-collection.md`, walks through a collection of three datasets: when a collection is worth having, how to save the collection and its members with `Dataset` and `save_dataset`, how to check the deposit graph with `preview_jsonld()` and `validate_publication_report`, and what the JSON-LD looks like. It also states the rules that keep the links stable: the collection IRI is seeded from its access URL and name, so the name is frozen once published; the collection publishes before its members; and a collection has no distributions and no `about`. Its code runs in the doc-snippets CI job.

- **`chemistry` has a proper vocabulary: 33 labels in two levels.** The
  nine recognised labels mixed three things: the couple (`li-ion`),
  rechargeability (`li-primary`) and the electrolyte (`alkaline`). That
  left no correct label for a rechargeable lithium-metal cell, and made
  `li-mno2` and `li-metal` look like alternatives when one is a kind of
  the other. A label now names the electrochemical couple only.
  Rechargeability stays in `rechargeable`, and Li-ion electrode materials
  in the electrode basis fields. A label may be narrower than another
  (`li-mno2`, `li-fes2`, `li-socl2`, `li-s` and others under `li-metal`;
  `alkaline-zn-mno2` and `zinc-carbon` under `zn-mno2`; `leclanche` and
  `zinc-chloride` under `zinc-carbon`), and each maps to its own
  domain-battery class. New families: `k-ion`, `mg-ion`, `ca-ion`,
  `zn-air`, `zn-hgo`, `ni-mh`, `ni-cd`, `ni-fe`, `ni-zn`, `lead-acid`,
  five metal-air systems and three flow systems. The full table is
  generated into the property reference page. `li-primary`, `alkaline`
  and `znmno2` keep resolving as aliases; validation flags them with a
  `semantic.controlled_value_superseded` warning that names the label
  to use. Two mappings were wrong and are corrected: `zn-mno2` resolved
  to the alkaline class, one of its three variants, and now resolves to
  `ZincBattery`; `zinc-carbon` resolved to `AlkalineCell` and now
  resolves to `ZincCarbonBattery`. The records context gains the 28 new
  class terms (append-only, 617 to 645).

- **Read side of the registry: `battinfo.registry.Registry`.** Until now
  the package could publish to a registry and search titles, but offered
  no way to get from a dataset record to its measurement data. `Registry`
  lists records of any type with full pagination, fetches a full record
  with its links and files, downloads a dataset's data file with SHA-256
  verification into a local cache, and loads it as a DataFrame.
  `Registry.catalog()` returns one row per dataset joined with its test
  kind, cell, cell spec, format, chemistry and stated capacity, which is
  the table to filter before downloading. `read()` renames columns to
  machine-readable BDF names by default, because published files spell
  them in more than one way. Listing and lookup need only the core
  install; `read()` and `catalog()` need the `tabular` extra. Marked
  provisional: method names are expected to stay, catalog columns may
  grow. How-to: docs/howto/read-registry-data.md.

- **Semantic contracts, first slice (post-review hardening roadmap).**
  Three new contract gates make the emission promises machine-checked by
  an independent consumer:
  - *Graph equivalence:* inline and URL emission modes are compared as
    RDF GRAPHS (rdflib + structural blank-node hashing) over the whole
    packaged corpus - not as JSON spelling, so a defect shared by a
    generator and its expected output can no longer certify itself. The
    sweep caught a residual mode divergence: the per-document context
    override that keeps PrismaticBattery on its current underscore-named
    class (the hyphen twin is deprecated upstream, domain-battery 0.20.2
    issue #73) was silently dropped in URL mode. URL mode now emits the
    hosted context plus a local override patch whenever a document term
    disagrees with the append-only v1 context, so both modes expand to
    the same graph and carry the current class.
  - *SPARQL domain questions:* the merged corpus graph answers consumer
    questions with independently stated expectations - every cell
    instance names a spec the corpus describes, a nominal capacity is
    retrievable by class and explicitly a ConventionalProperty with the
    record's own value, and parameter claims expose their epistemic
    basis (provenance_class) per claim.
  - *Reference-link inventory:* every schema-declared record-IRI link
    must be either resolved by strict reference validation or exempted
    with a stated reason - adding a link field to a schema now forces the
    decision (the F6 class of defect cannot recur silently). The gate
    immediately surfaced two more unvalidated links, both now validated:
    `electrode_spec.active_material_spec_id` and `channel.equipment_id`.

### Changed (breaking — identifiers)

- **Every parameter set now mints under `dataset/`, with a new uid.** Claim batches and parameter files get `https://w3id.org/battinfo/dataset/{uid}` IRIs instead of `spec/` ones. Nothing is ever an instance of a parameter set: it is one piece of data from one source, produced by one calibration or extraction, so it is a dataset (IDENTIFIER_POLICY 6.1 and 6.3, ruling of 2026-10-11). The seeds changed with the namespace, so no uid minted under `spec/` comes back under `dataset/`. A claim batch's uid is `stable_uid("parameter-claims:<target>:<scope>[:<electrode_polarity>]:<name>")` (it was `parameter-set:...`) and a parameter file's is `stable_uid("parameter-file:<parameters_sha256>")` (it was `parameter-set-file:...`). The builders and a save of a record without an id mint through the same two recipes, never under `spec/`, and an explicit `id=` on a claim batch must be a `dataset/` IRI. The five packaged parameter-set examples, all BPX files, carry their new IRIs.
- **The 18 parameter sets published under `spec/` are republished, not moved.** The 17 claim batches and the Schmitt et al. 2026 file are published again as new `dataset/` records that name the old IRI in `supersedes`, and the old IRIs keep resolving as superseded pages that point at their replacements. The Schmitt file record `spec/szxp-xwnx-vhyf-rvm0` is superseded by `dataset/7jnc-cjtw-5h3a-5t52`. `supersedes` now belongs to both flavours (`create_parameter_set(supersedes=...)`, `to_parameter_set(supersedes=...)`, `dcterms:replaces` in JSON-LD) and takes a `dataset/` or a `spec/` IRI. Only the publisher of the old record can supersede it: the registry refuses a `supersedes` from anyone else.
- **Local `spec/` parameter sets still load and validate, with a warning.** The schema's `parameter_set.id` accepts a `spec/` IRI for a record minted before 2026-10-11, so such a record validates, saves and is found by its IRI, and gets the warning `semantic.parameter_set_legacy_namespace`, which names the `dataset/` IRI its replacement mints. Under the publisher policy that warning is an error, so `ws.submit()` and `ws.zenodo()` refuse the record (`ws.zenodo()` before it sends anything to Zenodo, a draft included) and say what to do instead: `supersede_parameter_set(record)` makes its replacement, a `dataset/` record minted from the current seeds that supersedes it, with everything else unchanged. `query_parameter_sets()` marks such rows with `minted_under_spec`. It and `collate_claims()` leave out a record that another record in the result names in `supersedes`, so a source whose old and new records both sit in a workspace is not counted twice; `include_superseded=True` keeps it. A parameter set that supersedes itself, keeps the uid of the record it supersedes, or carries the uid its fields had under `spec/` (the old uid moved to `dataset/`, with or without `supersedes`) is an error under every policy, and the builders refuse such a uid.
- **`dataset/` holds two kinds of record.** Dataset records and parameter sets share it, and tooling reads the record, not the namespace, to tell them apart. `save_record` and the `save_*` functions refuse to save a record over one of another kind at the same IRI. The deposit checks that a dataset node names what it is about and carries at least one file apply to nodes typed as dataset records (`dcat:Dataset` in a workspace deposit, `BatteryTestResult` in a dataset publication package), the types every dataset record's node carries, so a parameter set, a plain `schema:Dataset` node, is not held to them. A deposit's catalog lists its parameter sets as members (`dcat:dataset`, `schema:hasPart`) after its per-test datasets, so a deposit holding only parameter sets passes the publication checks, and a cell spec, cell or material spec a parameter set names but the deposit does not carry gets a "defined elsewhere" stub node, as an external cell spec does; a parameter set minted under `spec/` that another record in the workspace supersedes is left out of the deposit, with a line saying so; a parameter file's file entries name the record in `schema:isPartOf`, and the validator reads a single `schema:about` or `schema:distribution` object as a one-item list (both as in #438).

### Changed

- **EMMO pins: domain-battery 0.20.2 → 0.21.0, domain-electrochemistry 0.37.2 → 0.39.0** (chemical-substance 0.15.0, EMMO 1.0.2 and CHAMEO 1.0.2 unchanged). The bundled domain-battery context is refreshed to the 0.21.0 release, which adds 224 terms and changes none. Every EMMO IRI in the curated maps, the class tables, both records contexts, the generated labels file and the JSON-LD of the packaged examples was checked against the new closure for existence and deprecation. All exist except `emmo:Percent`, which the records contexts bind to `%` and EMMO declares in a units module the closure does not import. The only deprecated one is `LithiumNickelManganeseOxideElectrode`, which upstream deprecated before 0.37.2 and BattINFO still emits for `positive_electrode_basis: lnmo`.

  domain-electrochemistry 0.39.0 makes `OpenCircuitVoltage` strictly the cell-level quantity, the voltage between a cell's terminals at zero current, and adds `OpenCircuitPotential` for one electrode against a reference. A scalar `ocp` claim, the half-cell potential of an electrode material, now types as `OpenCircuitPotential`. Nothing BattINFO emits holds a cell-level open-circuit voltage, so `OpenCircuitVoltage` is no longer emitted; OCP curves and expressions stay `schema:PropertyValue` nodes without an EMMO class. `entropic_coefficient` moves to `TemperatureCoefficientOfTheOpenCircuitPotential`, the electrode-level dU/dT. Its entry used to pair the cell-level label `TemperatureCoefficientOfTheOpenCircuitVoltage` with the IRI of `CoatingThickness`, so entropic coefficients were published as coating thicknesses.

  Three more parameter keys type as classes 0.39.0 adds: `solid_diffusivity` as `GuestDiffusivity` (it was the generic `Diffusivity`), `electrode_pair_count` as `NumberOfElectrodePairs` (a subclass of the `NumberOfEntities` it used before), and `transport_efficiency`, which had no class and was typed by its value basis alone, as `TransportEfficiency`; it no longer warns `semantic.property_unmapped`. The v1 records context gains these five class terms (672 to 677) and changes none. `to_bpx` output is unchanged, since only the JSON-LD typing moves.

  The version bump changes no unit IRI (the Celsius fix under Fixed is separate). From domain-electrochemistry 0.38.0 on, the closure imports EMMO's SI-accepted units, so `AmpereHour`, `MilliAmpereHour`, `Watthour`, `KiloWatthour`, `MilliLitre`, `MolePerLitre`, `WattHourPerKilogram` and `WattHourPerLitre`, which the unit map already used, are now declared inside the pinned closure. `.tools/quality/emmo_closure_terms.py` writes the closure's deprecated terms and measurement-unit classes to a test fixture, and the mapping governance tests fail when an emitted IRI is deprecated, when a unit IRI BattINFO writes is not a unit, or when a curated class label names a different IRI from the one it is mapped to.

### Fixed

- **Celsius temperatures are typed as degree Celsius, not as the programming language C.** Every temperature given in `°C` or `degC` was published with `hasMeasurementUnit` `https://w3id.org/emmo#EMMO_36a9bf69_483b_42fd_8a0c_7ac9206320bc`, which is EMMO's class for the programming language C (a CompiledLanguage). The curated unit map had the right class, `https://w3id.org/emmo#DegreeCelsius`, but a hand-kept table and the candidate map overrode it, and the records contexts bound the `degC` term to the same wrong IRI. The emitter now takes the curated map first, then the hand-kept aliases, then the candidates, and all of them say `DegreeCelsius`. `ws.import_()` still reads the old IRI back as `°C`.

- **The v1 records context term for the open-circuit voltage temperature coefficient names that quantity.** `TemperatureCoefficientOfTheOpenCircuitVoltage` expanded to `electrochemistry_3b938708_…`, the IRI of `CoatingThickness`, so entropic coefficients published through it read as coating thicknesses. It now expands to `electrochemistry_3bb5ae23_…`, the class with that label in domain-electrochemistry 0.39.0. No emitter uses the term since `entropic_coefficient` moved to `TemperatureCoefficientOfTheOpenCircuitPotential`, but the hosted context still defines it.

  Both are corrected in place in `records.context.v1.json` (the `degC` term and this one), under the same pre-release ruling that corrected eight v1 terms before (`PRE_RELEASE_CORRECTIONS` in `scripts/gen_context.py`); no release has shipped v1, and after 0.8.0 a change of meaning needs a v2 context. Records published before these fixes carry the wrong IRIs until the registry re-renders them.

- **PyYAML is a core dependency.** `battinfo push`, `battinfo batch init` and `battinfo dataset init` failed on a core install with `No module named 'yaml'`, and `battinfo config set` did too, while a `~/.battinfo/config.yaml` was silently ignored. The package now requires `pyyaml>=6.0.1`.

- **`force=True` and `--force` delete only folders BattINFO created.** `battinfo.publish(..., force=True)`, `battinfo publish cell-spec --force`, `battinfo ingest build --force` and `ingest publish --force`, `battinfo dataset process --force`, `battinfo demo setup --force` and `demo verify --force`, `LocalWorkspace.clone()` and `new_version()` with `force=True`, and `Workspace.build_submission_package(force=True)` deleted the target folder with everything in it. A root pointed at a project folder took its data files and notebooks with it, an ingest build into the evidence folder deleted the evidence, and `clone()` into the workspace's own folder deleted the workspace before copying it. Every recursive delete now goes through one guard, `battinfo._fs_guard`. It refuses the root of a drive, the home folder, the current folder and any folder that holds one of them; a folder that holds a file or folder the command reads, or lies inside one (an ingest build's evidence files, type record and manifest, the workspace a clone copies, a dataset's data file, the `--input` file of `publish cell-spec`); a folder named in a manifest or a record that is not inside its workspace, such as a `dist_dir` of `../x`; and a folder that is not empty and that BattINFO did not create. BattINFO now writes a `.battinfo-generated` file into each output folder it creates. A folder built by 0.7 or 0.8 has no such file. It is recognised by its layout instead (`battinfo-workspace.json`, `battinfo-authoring-workspace.json`, or `index.json` next to `examples/`), and only when everything in it is what BattINFO writes there, so `--force` still rebuilds it after the upgrade. A folder with a common name has to hold what BattINFO puts in it: `inputs/` only the demo's `cycle-life.csv`, `release/` a release workspace, `publication/` a folder with a JSON-LD record for each dataset, and record and report folders such as `examples/`, `library/`, `ontology/` and `dist/` only files under the names BattINFO gives them, such as `examples/cell-spec/cell-spec-<uid>.json` and `dist/validation-report.json`. Any other file in them, JSON or not, stops the delete. `artifacts/` and a dataset's folder in `publication/` hold copies of the datasets' files, and the rest of what they hold is not checked. A project folder that a publish without `--force` once wrote `index.json` and `examples/` into therefore keeps its own `inputs/`, `ontology/` or `dist/`. The `.battinfo` folder where `battinfo.workspace()` keeps a project's records is never deleted, and neither is its `records/` folder or a folder that holds a `.battinfo`, marker file or not. The error names the folder and each file or folder in it that is in the way, and nothing is deleted. `clone()` and `new_version()` also refuse a target that holds the workspace or lies inside it, with or without `force`. The `--force` help texts say what is deleted: `demo setup --force` and `demo verify --force` delete `ROOT/workspace` and `ROOT/release`, not the demo root. Temporary folders go through the same module, and a test fails if another module in `src/battinfo` calls `shutil.rmtree`.

- **`battinfo.publish()` names its parameters.** It took `**kwargs`, so `root`, `force`, `validation_policy` and the registry settings did not appear in `help(battinfo.publish)`, and a misspelt keyword failed with an error about an internal function. They are now keyword-only parameters, and an unknown keyword raises a `TypeError` that names it. The deprecated publication-package form, `publish(cell_spec=..., cell_instance=..., test=..., dataset=...)`, still works and warns with a `DeprecationWarning`, which now says it will be removed in 0.9.0. It accepts the keywords of `publish_publication_package()` only.

- **Equipment added with `ws.add("equipment")` reaches the registry after `ws.save()`.** `ws.add("equipment")` writes the unit, its spec and its channels when it is called, and `ws.save()` then reset the session's list of written records to the files it wrote itself. A session that added a unit, a cell and a test on one of the unit's channels, then saved and submitted, sent the cell and the test but not the unit, its spec or the channel the test points at. `ws.publish()` saves first, so it left them out too, and for a session that only added equipment it refused with "No records were saved in this session". `ws.save()` now keeps what `ws.add()` wrote in that list, so `ws.submit()` and `ws.publish()` send it with the rest. `ws.clear()` still empties the list.

- **A record IRI, a registry response or a workspace manifest can no longer name a file outside the folder it belongs in.** Record files are named after the uid that ends the record's IRI, and nothing checked that it was a uid. On Windows, `ws.load()` of a search hit and `ws.add("test", cell=...)` on a cell only the registry holds wrote the registry's copy of the record wherever an IRI ending in `..\..\victim\planted` pointed, and `save_record(..., validate=False)` did the same with a record's own id. On every system, `publish_record(..., validate=False)` of a record whose IRI ended in `../..` wrote above its target folder, and `Registry.download()` of a registry entry whose id was `../../x` wrote the data file outside the cache. Now only a dashed uid such as `pge5-wer6-2q82-v9k0` names a file: `save_entity_path()` raises `ValueError` for anything else, a lookup by such an IRI opens no file named after it, `ws.load()` and `ws.add()` refuse the registry record and write nothing, and `Registry.download()` refuses the entry before it fetches anything. The paths a workspace manifest names were not checked either. A `dist_dir` of `../outside` made `battinfo workspace validate` write its report there, a `resources.dataset` outside the workspace made `update_release()` rewrite that file, and a `dataset_artifacts` path outside it made the next save of an authoring workspace copy that folder into its artifacts. `dist_dir`, `artifacts_dir`, `paths.*`, `resources.*` and the `dataset_artifacts` paths must now be relative paths inside the workspace, with no drive, leading slash or `..`. A manifest that breaks this fails when it is read (`battinfo workspace validate` reports it), and the error names the field.

- **The page `emit_html_page=True` writes keeps record text inside its script element.** `save_publication_html()` puts the publication's JSON-LD in a `<script type="application/ld+json">` element, and a dataset description holding `</script><script>...</script>` ended that element early and ran its own script in any browser that opened the page. The JSON now writes `<`, `>` and `&` as `\u003c`, `\u003e` and `\u0026`, which a JSON-LD reader decodes to the same text.

- **Submission packages no longer send the local workspace folder to the registry.** The `workspace` block of the packages that `battinfo workspace bundle`, `battinfo ingest publish`, `battinfo dataset publish` and the demo build held `root`, the absolute path of the workspace with the user name in it, and the registry received it with every submission. The packages leave it out, and `submit_publication_package()` drops it from a package built by an earlier version before sending. The local reports still give the folder as `workspace_root`.

- **`--clean-output` deletes only the JSON-LD files the previous library build wrote.** `battinfo library build-rdf --clean-output`, `battinfo library save --build-rdf --clean-output` and `build_cell_spec_library_rdf(clean_output=True)` deleted every `.json` and `.jsonld` file in the output folder before building. With the output folder set to the input folder, that took the cell specifications the build was about to read and any other JSON file kept there, and the build then reported success with no entries. It now deletes only the JSON-LD files that the previous build listed in its manifest, and `clean_output` is refused when the output folder is, holds or lies inside the input folder.

- **NOTICE names the third-party material the package bundles and ships in the wheel.** It lists the EMMO ontology context and terms (CC BY 4.0) and the BPX example files (MIT, University of Oxford), each with its source and holder.

- **A Zenodo deposit describes the registry-only records its tests point at.** Since a cell found only in the registry counts as resolved, a test or dataset on it saves, but `ws.preview_jsonld()` and `ws.zenodo()` built the deposit graph from the workspace's own records alone. The graph had no node for the cell, so publication validation failed with `publication.reference_missing_node` (199 errors for the Empa relink, under the publisher and strict policies), the tests lost the cell part of their names (199 tests shared 15 names), and `ws.zenodo(publish=True)` created and uploaded a draft before it refused. The deposit now reads the copies the workspace keeps under `.battinfo/references/`: a cell or test spec that a test or dataset points at and the deposit does not carry gets a "defined elsewhere" stub, the kind of node an external target of a parameter set already gets, with its IRI, type, name and `rdfs:isDefinedBy`, and test and dataset names take the cell's name from the copy. Nothing else is read from a copy, no copy is uploaded, and `ws.import_()` skips a cell stub instead of reporting a cell without a spec. It skips the tests and datasets on such a cell too, as before, but now says so: the counts it returns are the records it imported (they used to count every test in the graph), and `skipped` lists each test and dataset left out with its cell and the reason. A reference with no copy (looked up offline, or never looked up) is still an error, and the preview and the refusal now say that the record was not found locally and how to fetch it.

  `ws.zenodo(publish=True)` also runs its checks before it contacts Zenodo, so a publish refused for a graph error or a missing data file leaves no draft behind. The graph is the one `ws.preview_jsonld()` builds, with placeholders for the record id and DOI. No check reads those two values, and the deposited graph is checked again before the DOI is minted.

- **A deposit made without a title names its catalog.** `ws.zenodo()` gave the Zenodo metadata an automatic title when none was passed, but built the deposit graph with an empty one, so the catalog node had no `schema:name`. Where pyshacl is installed the publication check refuses that, so every `ws.publish(zenodo=True)`, which passes no title, was refused. The title is now worked out once, by the rule the metadata used, and the deposit graph, the RO-Crate and the metadata all take it; `ws.preview_jsonld()` without a title shows the same one. The CLI batch path (`build_zenodo_package`, used by `battinfo push`) had the same gap: its graph took the cell spec's name, possibly empty, while the metadata took "<name> — BattINFO Reference Datasets". The staged graph and RO-Crate now take the metadata's title, and a title passed to `upload_zenodo_package` renames both before they are uploaded.

- **`ws.import_()` reads the deposits `ws.zenodo()` writes today.** The deposit graph states a file's media type as an IANA media-type IRI (`{"@id": "https://www.iana.org/assignments/media-types/text/csv"}`) and a cell's dates as typed literals, and gives each dataset its own files under the catalog. The importer expected plain strings and one dataset holding every file, so importing any deposit with a data file raised a pydantic error (`data_format Input should be a valid string`), and from an older deposit with several datasets only the tests whose file sat on the last dataset came back. Both shapes now import: the media type is read back from the IRI and an IRI that is not an IANA media type is left empty rather than guessed, dates come from the literal, each test finds its file on its own dataset, and the test kind comes from `schema:additionalType` when the deposit states it.

- **BPX cell and state claims no longer say they were fitted.** `to_parameter_set` marked every claim of a BPX file `provenance_class: "fitted"`, including the cell's capacity, cut-offs, geometry and temperatures and the initial state of charge, so the record and its JSON-LD stated something the file never says. The `cell` and `state` claims now carry no class (the field is optional, and nothing downstream needs it); the material, electrode, separator and electrolyte claims keep `default_provenance_class` (`"fitted"`, or `None` for no class). The new keyword `provenance_classes=` sets the class of a whole part by name, for example `{"cell": "measured"}` or `{"separator": None}`, and refuses a part name or class it does not know. The five packaged BPX examples are corrected the same way; their IRIs do not change, since a parameter file's IRI derives from its parameters.

- **A search by material collates only that material's claims.** `query_parameter_sets(material_kind=..., parameter=...)` returns whole records, so `collate_claims` on the result also returned a BPX file's cell, electrode and other-electrode claims; in the BPX re-check, 4 of 10 graphite `particle_radius` claims were the positive electrode's. `collate_claims` takes `material_kind=` (a kind key or alias) and `material_spec_id=`, keyword-only, and then keeps only the claims about that material: a claim batch with that target and the matching material part of a parameter file. Without them it behaves as before. Both docstrings and the parameter-set reference page show the pairing.

- **Zero transport values in a BPX file are marked as placeholders.** A BPX file may hold 0 for an ionic conductivity, a diffusivity or a transference number where the real model lives elsewhere (the Molicel P45B file keeps it in `User-defined`), and such a value was stored as an ordinary fitted claim without a word. The import still reads it as the file states it, so an export gives the file back unchanged, but a zero or negative scalar ionic or electronic conductivity, diffusivity, transference number or transport efficiency now gets no `provenance_class` (unless `provenance_classes=` names its part), the import warns with its BPX path and value, and record validation warns `semantic.parameter_transport_not_positive` on every check of a parameter set that holds one, claim batches included.

- **BPX parameter units resolve to EMMO units.** The curated unit map had no entry for the SI units BPX states its parameters in, so most claim quantities emitted their unit as `schema:unitText`. Version 0.5.2 of the map adds `m2`, `m3`, `mol/m3`, `m2/s`, `J/mol`, `V/K`, `S/m`, `1/m`, `mol.m-2.s-1`, `J/(kg.K)`, `W/(m.K)` and `W/(m2.K)`, mapped to their EMMO 1.0.2 unit classes, and a curve claim's node carries its y unit as `schema:unitCode` next to the text. The Schmitt and Molicel P45B files now import with no unit left as free text. The unit names are added to the records context v1 and the EMMO label file.

- **The JSON-LD of a BPX record says what it leaves out.** The record's `not_imported` paths and the names of its `annex` entries (the BPX `User-defined` block) did not reach the graph, so a linked-data reader could not tell that some values exist only in the source file or the record file. Both now ride the record node as `schema:additionalProperty` values named `not_imported` and `annex`, with existing schema.org terms only. The `not_imported` note points at the source file under `schema:distribution` only when the record carries one.

- **`to_bpx` names the fields a parameter-file export lacks.** `missing_required` listed only Cell keys, so an export with a missing electrode parameterisation reported `[]`. With the `bpx` package installed, every field and block the official parser reports missing is added. The list now has one format for both exports: `"<block>.<field>"` for a field, Cell fields included (`"Cell.Electrode area [m2]"`, where it used to say `"Electrode area [m2]"`), and `"<block>"` for a block missing whole.

- **Smaller BPX fixes.** A source, runnable or mirror URL on GitHub or GitLab that names a branch or tag instead of a commit gets a warning (`semantic.parameter_file_content_url_unpinned`); an explicit `refs/heads/` or `refs/tags/` ref counts as a branch or tag even when it looks like a commit hash. A runnable copy whose parameters equal the source's (the source is already in the v1 layout) gets a warning even when the source carries no `bpx_parse` check. `check_bpx` no longer writes a doubled period after the parser warnings. A misspelt keyword to `to_parameter_set` raises a `TypeError` that names it with a did-you-mean and lists the accepted keywords, instead of naming a private function.

- **BPX docs and docstrings.** The how-to [Publish a BPX parameter file](docs/howto/publish-a-bpx-parameter-file.md) shows the code for a cell that is not in the genome yet: write an identity-only cell-spec draft, `ws.load` it and `ws.save()` it, since a draft has no IRI until it is saved. The `from_bpx` docstring no longer points at `ws.cell_spec(...)`, which the workspace does not have, and says what `extra_warnings` does. The `battinfo.interop` docstrings are plain ASCII, so `pydoc.render_doc(battinfo.interop)` works on a cp1252 console. The Python API page now covers `battinfo.interop`.

- **The entry pages and how-tos match a real run.** The getting-started CLI quick reference now works after an install: it validates the cell spec the page just published, says that `battinfo template cell-instance` writes `draft.json`, saves the cell where its spec is, and shows where the packaged examples are. Its CR2032 example, and the one in the Python API page, use `li-mno2` instead of the superseded `Li-primary`, and its Validation card links to the validation contract. QUICKSTART step 3 says what the resolver document holds (the cell's EMMO types and its `hasProperty` nodes are on the `isDescriptionFor` node), and step 4 shows the output of a real run on a core install, with the pyshacl warning. The README, the reading-a-record page and the docs index name `hasNumberValue`, the predicate the JSON-LD uses, instead of `hasNumericalValue`. The README describes `battinfo push` as the Zenodo batch path it is and moves the verification gate to Contributing, since it needs a checkout. The collection how-to no longer claims that the registry's served RDF carries the membership edges; workspace-authoring no longer says test-spec templates fail `ws.load()`. Reading registry data now covers the sign of the current, where cycle numbering starts, capacity columns that do not follow the BDF definitions and how to count charge instead, what `links()` returns and what `nominal_capacity_source` holds.

- **`ws.convert()` does not call a row counter data loss.** Converting the tutorial's own Neware sample printed a DATA-LOSS WARNING for `Record`, a column that only numbers the rows (1, 2, 3, ...). In a file of at least 10 rows, a source column left out of the BDF file whose values are 0, 1, 2, ... or 1, 2, 3, ..., one per converted row, is now reported as a row counter the row order already holds, and is not recorded as lost in `.battinfo/conversions.json`. A column with any other values, or any column of a shorter file (where a single 1 or a 0/1 flag looks like a counter by chance), is still reported as data loss.

- **Help text, messages and docstrings say what the package does.** The batch path still said cell type where it means cell spec: in `battinfo push --help` and `battinfo batch init --help`, the `battinfo query cell-spec` and `battinfo publish` help and output, and the errors for a `--cell-spec` value that matches no spec or several. Saving a cell whose spec was not in the source root said "Register the type first". All of them now say cell spec, and the `--cell-spec` help says it takes the spec's IRI as well as its manufacturer and model. An unknown keyword to `ws.add(...)` used to fail deep inside: as Python's `TypeError` naming a private method (test, cell, equipment), as a pydantic error (material and electrode records), or as a complaint about a missing `name=` (`ws.add("parameter_set", reocrd=...)`). Every record type now refuses it up front, naming `ws.add`, suggesting the closest keyword and listing the accepted ones, and `help(ws.add)` lists the keywords a test takes, `protocol=`, `description=`, `status=` and `license=` among them. The `ws.zenodo()` docstring gave `battinfo-reference` as the default community; the default is `battery-knowledge-base`. `battinfo.save_dataset` documents `mode`, `duplicate_policy`, `resolve_references` and what it returns for each status, and `validate_record_report`, `validate_publication_report`, `TestSpec`, `Test` and `Dataset` have docstrings.

- **Renaming a cell with a serial number keeps its IRI.** A cell's IRI was seeded from its name when it had one, so a new display name minted a new cell, and every test and dataset seeded from that cell moved with it. The seed now takes the serial first, then the name, then the batch, as the `ws.add("cell")` documentation already stated. `create_cell_instance()` ignored the name while `ws.add("cell")` and `save_cell_instance()` used it, so one physical cell could get two IRIs depending on which function created it; all three now agree. Cells without a serial keep their IRIs. A cell that has both a name and a different serial gets a new IRI compared with earlier development versions; to keep a published one, pin it with `ws.add("cell", ..., iris=[...])`.

- **`ws.submit()` sends a cell spec's own title.** Every cell-spec submission was titled "<manufacturer> <model>", so a cell spec retitled with `battinfo.naming` ("Flores 2026 graphite AQ-1 cell spec") kept its old title in the registry. The record's `name` now wins; manufacturer and model are the fallback.

- **A property without an EMMO class no longer gets an invented one.** When a property or parameter key had no mapping, the JSON-LD emitter generated a class name such as `battinfo:solidDiffusivity`, declared nowhere, so the IRI resolved to nothing. Such a quantity node now carries only its value-basis class (`ConventionalProperty`, `MeasuredProperty`, ...) with the record key as `skos:prefLabel`, and validation warns `semantic.property_unmapped`, now for parameter-set claims as well. Five keys that hit the old fallback in the examples map to published classes: `particle_d50` to `D50ParticleSize`, `compaction_density` to `CalenderedDensity`, `initial_concentration` to `InitialChargeCarrierConcentrationInElectrolyte`, `solid_diffusivity` to `GuestDiffusivity`, and `entropic_coefficient` to `TemperatureCoefficientOfTheOpenCircuitPotential`; `transport_efficiency` types as `TransportEfficiency`. The last three are classes from domain-electrochemistry 0.39.0 (see the EMMO pins entry). The records context gains the three new class terms (append-only, 647 to 650), and `scripts/gen_battinfo_vocab.py` now fails if code generates a `battinfo:` name. IDENTIFIER_POLICY.md section 14 is amended to describe this.

- **Dataset IRIs no longer depend on where the workspace folder sits.** A dataset's identity seed included its access URL, which for a local data file is the absolute `file:///` URI, so the same workspace built in another folder (by a colleague, by a CI job, or after moving the project) minted new dataset IRIs, and publishing again created duplicates of the same data. The seed now takes a locator that does not depend on the folder: an explicit https access or download URL as before, otherwise the data file's path relative to the workspace root in POSIX form, otherwise its folder and file name (`run1/data.csv`), so two files of one name in different folders outside the workspace stay two datasets. A relative path is read against the workspace root, not the current directory, so a notebook in a subfolder mints the same IRIs. `ws.add("test", data=...)` and `save_dataset()` into a workspace's records folder use one shared helper, `battinfo.entities.dataset_locator_seed()`, and so does the re-mint that keeps two colliding records of one workspace apart, which used to hash the absolute path. The older publication-package path, `publish_publication_package()` and `Workspace.build_publication_package()`, seeded on the dataset folder's absolute URI; it now uses the same helper, with the dataset folder and its parent (`project/run-1`) as the location when there is no remote URL, and the same seed as the other two (cell, test, location, name), so a dataset with a remote access URL gets one IRI whichever of them mints it. The record's local `access_url` is unchanged. Datasets authored from local files therefore mint different IRIs than in earlier development versions; to keep one that is already published, pin it with `ws.add("test", ..., dataset_iris=[...])`.

- **Registry submission refuses local file paths.** Publishing a workspace to the registry sent each dataset's local `file:///C:/Users/<name>/...` paths as its access and download URLs, so the registry published the submitter's user name and folder layout as the only links, and nobody else could follow them. `ws.submit()`, the registry half of `ws.publish()`, `battinfo.api.submit_publication_package()` and the paths built on it (`publish_ingest_workspace()`, `run_demo_pipeline()`, `publish()` to a registry) now refuse any record whose `access_url`, `content_url`, `download_url`, `provenance.source_url` or `record_url` is a `file:` URI or a local path, or whose `source_file` or artifact `locator` is an absolute path or a `file:` URI (a file name or a relative path there is fine). The protocol importers behind `battinfo import-protocol` stored the absolute path of the imported file in both; they now store it relative to the current directory, or by its name when it lies outside it. The error lists each record and field and says what to do: deposit the files first, for example with `ws.zenodo()`, so the records carry https URLs. `ws.submit()` checks every record before it sends anything, and with `allow_partial=True` it sends the others and reports the refused ones. `allow_local_files=True` (`--allow-local-files` on `battinfo demo verify` and `battinfo ingest publish`) lifts the check for a local test registry. `ws.zenodo()` and `ws.upload()` now also point a dataset's local `provenance.source_url` at the deposited copy of its file, so a deposited workspace passes. The ingest builder behind `battinfo ingest publish` no longer writes the ingest folder or a file path into any URL field: the cell names its folder in its notes, each test names its file in `source_file` and gets the uploaded artifact's URL as `source_url` when there is one, and each file a dataset's record names follows its own uploaded copy, so a publish with an artifact base URL or an uploader passes without the override. (Every upload used to rewrite the record's first file, so a dataset of several files kept local paths for the others.) The deposit preview is unchanged. Known limitation: a Zenodo deposit of more than 90 data files is zipped by test kind, and the registry cannot yet point a record at a file inside an archive, so those records keep their local paths. `ws.publish(zenodo=True)` without R2 storage therefore refuses such a workspace before it deposits anything, instead of failing at the registry half after the DOI exists; publish it to Zenodo alone with `ws.zenodo(publish=True)`, or split it into workspaces of at most 90 data files.

- **`ws.add("test", data=...)` refuses a data file that does not exist.** Run in a folder without the file, the getting-started workspace snippet saved a dataset record for `bdf/S1.bdf.csv` with no error; only the deposit preview objected later, with a message about URLs that sent the reader after the wrong problem. A missing `data=` or `raw=` file, or a missing entry in a `datasets=[...]` list, now raises `FileNotFoundError` naming the path it resolved to, before any record is created. The `ws.add()` and `ws.load()` docstrings now say that a relative path resolves against the workspace root, not the current directory.

- **`ws.load()` no longer drops draft keys it does not read.** The MN2400 cell-spec draft supplied for the evaluation kept its five datasheet values under `specs`, the key drafts used until June, and `ws.load()` loaded none of them; a test-spec draft lost its `termination_criteria` cutoff the same way, and so did typos and unknown keys, while both records passed strict validation. Cell-spec drafts now read `specs` as an alias of `properties`, merged the way `CellSpec(specs=...)` merges it. A draft reads every key that has a home in the record it becomes: the fields of `CellSpec` or `TestSpec` (such as `datasheet_revision`, `product_type`, the electrode, electrolyte, separator and housing structure and their `*_spec_id` links, `version`, `protocol_url`, `comment`, and an `id` or `uid` that pins the IRI), the arguments of `create_equipment_spec()` for an equipment spec, the flat provenance keys (`source_url`, `retrieved_at`, `curated_by` and the rest) and the spellings the model constructors also take (`model_name`, `notes`, `test_kind`, a flat property name). So the drafts that `battinfo template cell-spec-draft` and `template_test_spec_draft()` write load with their `comment`, `datasheet_revision`, `version` and `protocol_url`. A test-spec draft's `protocol` name, which the test-spec record has no field for, is kept in its notes like `instrument` and `atmosphere`. Only a key with no home raises a `ValueError` that names the file and the key, with a did-you-mean and the keys that draft type accepts; keys starting with `_` stay comments, and a value given two ways that disagree (`model` and `model_name`, `source_url` and `source.url`) raises too. A test-spec draft's `termination_criteria` raises with the current way to state a cutoff: in the step that ends at it (`"Discharge at C/5 until 0.9 V"`) or as a structured `termination` on a `method` step. A property given as a range or as text (`min_value`, `max_value`, `typical_value`, `value_text`) is no longer dropped along with the unfilled template placeholders, and a property value that is not a quantity object, such as a bare `1.5`, raises instead of being dropped.

- **Templates no longer write a placeholder IRI.** `battinfo template cell-instance` carried `"id": "https://w3id.org/battinfo/cell/0000-0000-0000-0000"`, which `battinfo save cell-instance` saved as a real record and every validation policy accepted, so everyone who followed the getting-started steps claimed the same IRI. The other templates did the same for their record types. No template, on the command line or in Python, now writes an `id`, `short_id` or derived `identifier` unless `--uid` or `uid=` is given, and a linked IRI that was not given (`--cell-spec-id`, `--cell-id`, `--related-cell-id`, a component's spec) is left out rather than pointing at an all-zero record. Saving the filled-in record mints its IRI from its natural key, the way the matching builder (`CellSpec`, `TestSpec`, `create_material_spec()`, `create_organization()`, `create_channel()` and the rest) mints it from the same fields; `save_record()`, the `save_*` functions, `battinfo save` and `save_library_cell_spec()` all do this. A saved dataset template gets the IRI the builder gives the template's inputs, since the cells and tests it lists are related ones and stay out of the seed. A record with no natural key to mint from is refused, with an error that says to give it a uid: a component such as a separator, an equipment record, or a cell with no serial number, batch or name. A random IRI there would turn every re-run of the save into a duplicate record. Validation still rejects any record whose own IRI has the all-zero uid `0000-0000-0000-0000`, under every policy, with an `identity.placeholder_iri` error that says it is a template placeholder, so a draft made from an older template cannot be saved by mistake; `save_library_cell_spec()` refuses one too.

- **A new version of a published dataset saves under the strict policy.** A dataset with `published_at` and no `created_at`, which is what `Dataset.from_record()` gives for a published record, got `created_at` set to the time of saving. That is after the publication date, so strict validation refused the save with an error about `published_at`, a field the user never touched, and every new version of such a dataset failed this way. `save_dataset()` and the workspace engine now default `created_at` to `published_at` in that case; without either date it is still the save time. Such a save is a modification of the published dataset, so its `modified_at`, when not given, is the save time; falling back to `created_at` would report the old publication time as the new version's last change. The validator's rule that `published_at` is not earlier than `created_at` is unchanged.

- **`ws.save()` reports the records that failed validation.** A record the save-time index rejected, such as a test whose cell or protocol IRI does not resolve, was listed as `[created]`, and the save ended with "Next: ... ws.publish() to publish"; the error was only in the returned dict under `index.failures`. Such a record is now listed as `[failed]` with its error, even past the first ten of its kind, and its item in the returned summary carries `failed` and `error`. The closing line counts the failures and says to fix them and run `ws.save()` again before publishing.

- **A published record referenced by IRI or search hit counts as resolved.** `help(ws.add)` says a cell given by IRI is resolved in the registry, but the workspace never asked: a test added with `cell="https://w3id.org/battinfo/cell/..."`, or on a cell brought in with `ws.load(<search hit>)`, failed the strict save-time reference check with "Referenced cell not found in source_root", and `save_dataset()` refused a dataset about that cell the same way. With a registry configured the workspace now looks such a record up and keeps a read-only copy of the published canonical record under `.battinfo/references/<kind>/`. Reference validation against a workspace's `.battinfo/records` folder also reads that folder, and `ws.submit()` never sends the copies. This covers cells referenced by IRI, serial or search hit, cell specs from `ws.search()` hits, and test specs given to `ws.add("test", spec=...)` by IRI. Each record is looked up at most once per session, with a 10 second timeout: a failed lookup is remembered rather than repeated by every `ws.add()` that references the record, and a cell already found by its serial number is reused when it is referenced by IRI. With `registry_url=None` an unresolved reference stays an error, and `ws.save()` says it could not be checked offline.

- **A cell-spec draft keeps its title.** `ws.load()` of a cell-spec draft copied its `handle` but ignored its `name`, so the record was always titled "<manufacturer> <model>" and a build that set titles from `battinfo.naming` lost them silently. The draft's `name` now wins; without one the default is unchanged, and the IRI never depends on it.

- **BattINFO is cited by its existing Zenodo concept DOI.** The README carried a placeholder badge and said 0.8 would be the first archived release, but releases have been archived on Zenodo since v0.2.0 under the concept DOI 10.5281/zenodo.6304782. The README badge and citation, `CITATION.cff` and battinfo.org now use it, and RELEASING.md says how a published GitHub Release reaches Zenodo. battinfo.org also showed outdated ontology pins (domain-battery 0.18.7, domain-electrochemistry 0.33.0); it now shows the pinned 0.20.2 and 0.37.2, and a test keeps the two in step with `battinfo.ttl`.

- **The registry reader checks MD5 checksums, not only SHA-256.** `Registry.download()` and `Registry.read()` checked a file only when its record stated a SHA-256. Files whose record states MD5, the checksum Zenodo provides (all 95 Flores half-cell datasets among them), were downloaded and read with no check and no warning, and a cached file replaced by another dataset's file was read back as if it were the right one. The reader now checks any algorithm Python's `hashlib` provides and fetches a cached copy again when it no longer matches, as it already did for SHA-256. A file whose record states no checksum it can check is still used, with a `UserWarning` the first time. `RegistryFile` gains `checksum_algorithm` and `checksum_value`, and the catalog gains columns of the same names. `sha256` stays, filled only for SHA-256, and a catalog cached with the old columns is rebuilt.

- **The submit journal records which registry a record went to.** `ws.submit()` skips a record whose identical payload already succeeded, but its journal kept only the record and a payload hash. A workspace rehearsed against a local registry and then pointed at production skipped every record as "already submitted" and sent nothing. Each journal entry now stores the registry's base URL, normalized (lower-case scheme and host, no default port, credentials or trailing slash), and a success counts only for the same registry. Host names are not resolved, so `localhost` and `127.0.0.1` count as two registries. Entries written before this change name no registry and match none, so their records are sent once more, which is safe because the registry deduplicates identical payloads.

- **Validation warns about a `schema_version` this release did not write.** The JSON Schema checks only the form of `schema_version`, so any value passed, 9.9.9 under `--policy strict` included. A record stamped `0.1.0` or `1.0.0`, the versions earlier releases wrote, now gets the warning `semantic.schema_version_superseded`. Any other version except the current `0.2.0` gets `semantic.schema_version_unknown`. Both are warnings under every policy, so nothing that validated before fails now. Published records stamped `1.0.0` or `0.1.0` will show the superseded warning when validated. `battinfo.bundle.SUPERSEDED_SCHEMA_VERSIONS` lists the earlier versions. Some code still wrote `1.0.0` into records it had just built, which would have drawn the warning for no reason. A cell spec built from a datasheet library file (`CellSpec.from_library_record`, behind `CellSpec.from_path`, `derive_cell_spec` and the `battinfo push` batch path) took the library file's version. The library record builders defaulted to `1.0.0`, and `from_record` used `1.0.0` for a record stating no version. All of these now write `0.2.0`. A record read back with `from_record` and saved again still keeps the version it states.

- **Writing a workspace's record folders on Windows waits out a briefly held file.** The workspace engine's `save_workspace()`, `check_workspace()` and `bundle_workspace()` replace each record folder by renaming a freshly written copy into place, and Windows refuses that rename while any file inside the folder is open. A virus scanner or search indexer opening a new file for a moment was enough to fail the write with `PermissionError: [WinError 5] Access is denied`. Each rename now retries with a short backoff for up to about two seconds, and a swap that still fails restores the original folder as before.

- **Handles keep letters such as ø and æ.** `battinfo.naming` dropped letters that Unicode does not decompose, so "Topsøe" became `topse`. They now take their usual ASCII spelling (ø to o, æ to ae, ß to ss, ł to l).

- **A BPX Validation section is named on import.** Top-level sections other than Header, Parameterisation and State were skipped without a warning, so the five measured discharge curves in the Schmitt et al. 2026 file disappeared silently, against the importer's own rule. The warning now lists every Validation series and says the curves stay in the source file; any other unknown top-level section is named too.

- **A test-spec draft keeps its explicit `id`.** `ws.load()` ignored the `"id"` of a `.test-spec.json` draft and minted a new IRI from the name, so a corrected name moved a published test spec. The draft's `"id"` (or `"uid"`) is now used and checked as a `spec/` IRI.

- **Test-spec JSON-LD keeps current densities.** Coin-cell protocols state their currents per electrode area, for example a constant-current step with `setpoints={"current_density": {"value": 0.1, "unit": "mA/cm2"}}` and a constant-voltage hold that ends at `{"quantity": "current", "value": 0.05, "unit": "mA/cm2"}`. Both JSON-LD emitters, `record_to_jsonld(record, "test-protocol")` and the deposit graph from `ws.preview_jsonld()`, dropped the setpoint and wrote the cutoff as a `TerminationQuantity` with no unit, and the gold-standard check still passed. The setpoint now emits as an `ElectricCurrentDensity` control parameter and a current cutoff stated per area as a `LowerCurrentDensityLimit` or `UpperCurrentDensityLimit`, each with its unit; a setpoint under the `current` key in an areal unit is typed the same way. The curated unit map gains `mA/cm2`, `A/cm2` and `A/m2` (EMMO 1.0.2 unit IRIs), product spellings such as `mA cm-2` resolve to them, and a setpoint or cutoff whose unit has no IRI keeps its symbol as `schema:unitText` instead of losing it. The records context gains six terms (append-only, 650 to 656).

- **`TestSpec.experiment` renders what the record says.** The property, documented as the method rendered back to PyBaMM-style strings, forced a unit on each quantity, read every duration as seconds and printed a loop as the word "group": a constant-voltage hold ending at 0.05 mA/cm2 came out as "Hold at 4.2 V until 0.05 A", a 6 h rest as "Rest for 6 seconds", and a loop around the whole method lost its repeat count. Values now render in the unit they are stated in and durations in their own unit ("Rest for 6 hours"). Every loop is unrolled, its steps repeated `count` times, which is the list `pybamm.Experiment` takes; `render_method()` still returns a single top-level loop as `(steps, cycles)`, and the new `battinfo.testmethod.render_experiment()` gives the unrolled list. A step the grammar cannot write faithfully, such as a constant-current step with no direction, renders as its description instead of a guess, a loop with no count stays one "Repeat (count not stated)" line, and numbers keep up to 12 significant digits without exponent notation.

- **Step strings take a current density, and a current cutoff's unit is checked.** `parse_step("Charge at 0.1 mA/cm2 until 2.5 V")` raised `ExperimentSyntaxError`, so a protocol stated per area could only be written as structured steps, while `ws.template("test-spec")` offers only strings. The grammar now reads a current per area (`mA/cm2`, `A/m2`, `A/cm2`, `µA/cm2`, and spellings such as `mA cm-2`) as a `current_density` setpoint normalised to mA/cm2, and `until 0.05 mA/cm2` as a `current` cutoff in mA/cm2, the form the Empa specs on the registry use; the comparison shorthand takes `"Current < 0.05 mA/cm2"` and `"Current density < 0.05"`. PyBaMM's own grammar has no current per area, so such strings are a BattINFO extension. Unit prefixes in step strings are read case-sensitively, as SI writes them (`M` mega, `k` kilo, `m` milli, `u` and `µ` micro, `n` nano): the grammar used to fold case, so `1 MA` was read as 1 mA and `1 MW` as 1 mW. `1 MA/m2` is now 100000 mA/cm2, plain currents take the same prefixes, and a prefix the grammar does not read (`KA`, `pA/cm2`, `mA/Mm2`, `1 MW`) or an upper-case prefix on a lower-case unit letter (`Ma`) raises instead of being guessed. A `current` cutoff in a unit of another quantity (`V`, `Ah`, `C`, `s`, `%`, `W`) is refused when it is authored as a string, as in `"Current < 0.05 C"`. A step built from a stored record or a dict keeps such a cutoff and raises a `UserWarning` that names the step, the unit and the quantity to use, so specs published or imported with one still load through `TestSpec.from_record`. Current units, areal units and units the check does not know (a specific current such as `mA/g`) pass silently. Current density is not added to the termination vocabulary, so the save-time schema is unchanged.

- **`pip install "battinfo[processing]"` installs the converter from PyPI.** The extra required `batterydf>=0.2`, but the only 0.2 build on PyPI is the release candidate 0.2.0rc2, which sorts below 0.2, so pip found no matching version and the docs sent readers to a pinned batterydf commit on GitHub. The extra now requires `batterydf[nda,excel,mat]>=0.2.0rc2,<0.3` and installs the release candidate; the docs and the converter error messages give that one line. CI had been testing the GitHub commit, 30 commits newer than the release candidate. It now tests 0.2.0rc2 from PyPI, the install smoke job converts a file with the extra installed from the built wheel, and a weekly job runs the converter tests against the newest batterydf on PyPI.

- **The records context names the EMMO classes it should.** `records.context.v1.json`, the context every emitter uses and the file served at `https://w3id.org/battinfo/context/records/v1.json`, was frozen before domain-electrochemistry 0.37.1 and domain-battery 0.20.2 were adopted. Six properties (`power_capability`, `maximum_power`, `power_energy_ratio`, `round_trip_energy_efficiency`, `capacity_threshold_exhaustion`, `charging_time`) still expanded to private `battinfo:` terms although the curated property map gives them EMMO classes, `capacity_fade` still pointed at the CapacityFade phenomenon instead of CapacityFadeRate, and `PrismaticBattery` used an IRI the battery ontology deprecated. No release has shipped v1, so it is corrected in place. The six `battinfo:` placeholders leave the published vocabulary, documents no longer need a local PrismaticBattery patch, and a new test fails if v1 and the curated maps disagree again. After 0.8.0 a change of meaning needs a v2 context.

- **A housing spec in a format with no case class of its own converts to JSON-LD.** A housing whose `cell_format` is `other` or `unknown` types its case as the generic `Case`. The records context defines that class, but the JSON-LD validator built its allowed `@type` set from the mapping tables alone and rejected it, so `record_to_jsonld()` raised instead of returning a document. The validator now also accepts every class term of the bundled v1 records context, which puts what the emitters write and what the validator accepts on one source. Unit terms are the exception: the context also binds units such as `V`, `Ah` and `MWh`, and a unit is the value of `hasMeasurementUnit`, never a node's type, so `{"@type": "V"}` is still rejected. Which terms are units is read from the curated and candidate unit maps and from the unit symbols the context defines, a table that moved from `scripts/assemble_context.py` to `battinfo.jsonld.CONTEXT_UNIT_SYMBOLS` so the validator can use it. A bare `@type` that is defined nowhere is still rejected. The packaged-example sweep in the tests no longer skips an example whose JSON-LD fails validation, and it checks every emitted `@type` against the validator.

- **Licences are stated as working SPDX links everywhere.** The deposit graph copied a dataset record's licence into its member node as given, so `license: "cc-by-4.0"` came out as the bare string `"schema:license": "cc-by-4.0"`. The catalog node and the RO-Crate root did state an IRI, but built it from the lower-case id, and `https://spdx.org/licenses/cc-by-4.0.html` is a 404: SPDX paths are case-sensitive. The catalog, every member node and the RO-Crate root now state the licence the way `record_to_jsonld()` already did: a URL as it is, a known id as its SPDX page spelled the way SPDX spells it (`https://spdx.org/licenses/CC-BY-4.0.html`), under both `schema:license` and `dcterms:license`, and any other text as a plain literal rather than a guessed link. The table of SPDX pages now covers all 26 ids `ws.license()` accepts. Reading a publication bundle back (`load_publication()`, `LocalWorkspace.import_publication()`) accepts the IRI form and keeps the IRI as the dataset's licence; before, it failed on any member licence given as a URL. The dead links earlier versions wrote are repaired on the way through: an spdx.org page that matches a table entry apart from case, or is named by one of the table's lower-case ids (`gpl-3.0.html` becomes `GPL-3.0-only.html`), is read back from a bundle and emitted by `license_node()` in SPDX's spelling, so a record that stored `https://spdx.org/licenses/cc-by-4.0.html` now states `https://spdx.org/licenses/CC-BY-4.0.html`. An spdx.org page the table does not know is kept as given.

- **The Zenodo deposit graph reads a dataset's own `about` and understands collections.** The deposit builder took a member dataset's `schema:about` and its generated-by test only from the tests' `dataset_ids`. A corpus that links each dataset to its cell and test through the dataset's `about` list, and leaves `dataset_ids` empty, got no `schema:about` on any member, so `preview_jsonld()` reported `publication.dataset_about_missing` for every dataset and publishing was refused (95 errors on the Flores half-cell corpus). The dataset's `about` is now the primary source, unioned with what `dataset_ids` gives, and a test lists every dataset that names it as `hasOutput`/`prov:generated`. A collection (`additional_type = "DatasetSeries"`) is now typed `dcat:DatasetSeries` in the deposit and carries no empty distribution arrays, and its members carry `dcat:inSeries` and `schema:isPartOf` pointing at it, as the record and resolver emitters already did. The publication validator and its SHACL shapes exempt a series from the about and distribution rules. A `dcat:inSeries` target inside the package must be typed `dcat:DatasetSeries` (`publication.series_target_not_series`); a target outside it only warns (`publication.series_not_in_package`), since a collection may be published before its members. On the Flores corpus the gold-standard check goes from 98 errors and 96 warnings to a clean pass.

- **Pre-release fixes from the close-out review.** Three defects that would
  have frozen into 0.8.0:
  - *A collection could not be submitted.* `ws.submit()` sent
    `"distributions": []` for a dataset with no file of its own, which is
    what a `DatasetSeries` collection is, and the schema requires at least
    one entry when the key is present. The key is now left out.
  - *Two property keys emitted class names that do not exist.*
    `nominal_continuous_charging_current` and
    `nominal_continuous_discharging_current` carried candidate class IRIs
    the ontology never minted, so their `@type` resolved against the
    document base. They now emit the published `ChargingCurrent` and
    `DischargingCurrent` (context 645 to 647 terms, append-only). Both
    keys stay deferred in the curated map; their schema slots still point
    at the maximum-current classes, which is a separate correction that
    needs a context v2.
  - *The graph-equivalence sweep skipped subfolders*, which is where that
    record lives. It is now recursive, checks that every kind and every
    file is reached, and a new test fails on any class or predicate that
    falls back to the document base.

- **`ws.convert()` works against batterydf 0.2, the version the
  `processing` extra requires.** CI had been testing against a July
  snapshot that predates 0.2, and three things had drifted. The reader
  plugin name moved from `meta["source"]` to `meta.bdf.source`, so the
  unmapped-column report (the DATA-LOSS WARNING) silently stopped
  printing while columns were still being dropped. `bdf.io.save` no
  longer converts labels by default, so converted files came out with
  human-readable headers (`Voltage / V`) where every earlier file has
  machine names (`voltage_volt`); convert now asks for machine names.
  And the NEWARE binary, Excel and MATLAB readers became optional in
  batterydf, so `pip install battinfo[processing]` could no longer
  convert the `.ndax`, `.xlsx` and `.mat` files that `ws.convert()`
  auto-detects; the extra is now `batterydf[nda,excel,mat]`. A source
  with no mappable test-time column now fails with a named error and
  writes nothing (previously a BDF file with no time axis). The CI pin
  moves to the batterydf 0.2.0 release candidate, and
  `ws.bdf_columns()` lists `step_id` in place of `step_index`, which is
  no longer a BDF term.

- **Release-review fixes (independent 0.8.0 pre-release review, F1-F6 +
  onboarding).** An external review of the release candidate reproduced
  real defects; all confirmed items are fixed with regression tests:
  - *Release workflow (F1):* the CI workflow's distribution artifact is
    renamed `ci-dist` — release.yml runs CI as its gate and then uploads
    its own `dist` in the same run, and the duplicate name would have
    failed every release run at the second upload.
  - *BPX temperature masking (F2):* `to_bpx` no longer overwrites an
    imported `Reference temperature [K]` with the 298.15 K convention.
    The new default `"auto"` keeps the value carried by cell extras and
    applies the convention only when nothing provides the field; an
    explicit float still forces, `None` still omits.
  - *BPX v1 State import (F3):* a top-level `State` block is read, not
    discarded: `from_bpx` folds the initial and ambient temperatures into
    its Cell extras, and `from_bpx_parameters` reads the block as the
    record's `state` part, so v1 → record → v1 round-trips with state
    values intact. Unrecognized State entries are skipped by NAME, never
    silently.
  - *Inline JSON-LD context (F4):* inline emission now embeds the
    versioned hosted context (`records.context.v1.json`) instead of the
    stale flat assembled context, which had missing equipment terms
    (Description, BatteryCycler, ...), the deprecated hyphen-named
    PrismaticBattery IRI, retired power-key IRIs, and the pre-0.37.1
    CapacityFade class.
    Inline and URL modes now expand identically by construction. A new
    corpus-wide sweep asserts every emitted bare `@type` resolves in the
    context — it caught five more unresolved classes (Manufacturing,
    Negative/PositiveElectrode, MolarMass, SpecificSurfaceArea), now
    appended to the context.
  - *Reference validation (F6):* strict reference checking now validates
    `reference_electrode_spec_id` (cell specs) and `equipment_id` /
    `channel_id` (tests) against their expected record kinds — missing
    hardware links used to pass silently.
  - *Onboarding (F8, F7 docs):* the Quickstart validates the record the
    reader just created instead of a repository checkout file, states the
    full emitted `@type` stack, and the getting-started CLI examples use
    `--include-packaged-examples` so they work outside a checkout.
  - *Small fixes:* the BDC export docstring now states it is a partial
    inverse (measurement-availability flags are not reconstituted, F9);
    the docs navbar no longer loses the version/theme switchers to a
    duplicated `navbar_end` key (F11); the Neware tutorial sample's
    DateTime column agrees with its elapsed-time axis (F15).

### Added

- **Chemical substances get pinned, machine-verifiable identity (0.8.0
  core-features ruling; PR #371 un-parked).** A shipped vocabulary
  (`tools/substances/seed.csv` -> `build_vocab.py` ->
  `data/vocab/substances.json`) maps the symbols battery people write
  ("EC", "LiPF6", "TTE") to InChIKey (canonical), PubChem CID, CAS,
  SMILES, and the chemical-substance EMMO class; `battinfo.substances`
  resolves and stamps identity at authoring time (exact-match only,
  record slot breaks symbol collisions, did-you-mean on typos);
  components and salts gain five optional identity fields; the JSON-LD
  emits `schema:inChIKey` / `schema:smiles` and the PubChem page as
  `schema:sameAs` on the physical substance nodes - placement checked
  against the description-pattern rulings (chemistry literals ride
  physical individuals; a compound page is a reference page, not a
  class or a SKOS concept). Save gates warn (never error) on
  unresolvable names. The seed gains a hand-verified `preferred_cas`
  override - PubChem's ionic-form LiTFSI entry lists 2043073-41-0
  while the literature cites the neutral-salt 90076-65-6, so the
  reviewed number wins over the first synonym.

- **Equipment, equipment specs, and channels emit JSON-LD (0.8.0
  core-features ruling).** The last "no JSON-LD emitter" gaps close. An
  equipment spec follows the description pattern like every other
  product: catalogue facts on the `[Description, schema:ProductModel,
  schema:CreativeWork]` node, the described unit (instrument class +
  `schema:Product`) under `isDescriptionFor` as `<spec-IRI>#described`,
  and quantities as named `schema:PropertyValue`s - lab hardware sits
  outside the battery vocabulary and battinfo mints no domain classes
  for it. A standalone equipment record emits the SAME node shape the
  deposit graph builds for `hasTestEquipment` targets (instrument class
  + `prov:Entity`, serial number, location, the spec seam as
  `hasDescription`/`dcterms:conformsTo`/`schema:isVariantOf`), so both
  doors agree about a unit; channels carry `schema:isPartOf` +
  `schema:position`.

- **Organizations become first-class records (0.8.0 core-features
  ruling).** The documented triple gap closes: `create_organization` /
  `save_organization` / `query_organizations` (new IRIs mint
  deterministically from the normalized name, so re-creating "A123
  Systems" collates instead of duplicating; existing random-minted IRIs
  stay valid), a JSON-LD emitter (pure schema.org - `schema:Organization`
  with `Corporation`/`ResearchOrganization`/... stacked when the type IS
  a schema.org class, `same_as` as the Wikidata/ROR identity anchors,
  hosted records context), and an entities-registry kind, which puts
  organization records on the same validation path as every other
  family. The family's keys go snake_case (`legal_name`,
  `founding_date`, `parent_organization`, `address_country`, ...); the
  original camelCase spellings stay accepted forever as deprecated
  aliases - as kwargs and in stored records - and normalize on
  round-trip. Packaged examples rewritten to the canonical keys.

- **Cell geometry gets a home (BPX Cell-block ruling).** `electrode_area`
  and `external_surface_area` join the curated property vocabulary
  (EMMO `Area`), beside the existing `volume` - as-designed engineering
  facts of the cell. `from_bpx` maps the BPX Cell fields onto them and
  `to_bpx` fills the BPX-required `Electrode area [m2]` from the spec;
  Cell fields with no spec home (temperatures - stated conventions -
  and the electrode-pair count) are carried verbatim in
  `BpxImportResult.extras` and re-emitted by `to_bpx(cell_extras=...)`,
  so the whole Cell block round-trips. The two Cell-import warnings now
  name every key instead of truncating at eight.

### Changed

- **Nineteen quantity keys stop emitting minted `battinfo:` fallbacks and
  type as their published EMMO classes.** An audit of the parameter-claims
  corpus found the curated property map had never been wired for the
  parameter vocabulary, so every claim quantity except thickness emitted a
  `battinfo:` camelCase term with no ontology entity behind it. The
  keys with existing upstream classes now resolve: density,
  porosity, ocp (OpenCircuitPotential, for a scalar OCP only: an OCP table or expression, the form BPX always uses, is a schema:PropertyValue with no EMMO class), particle_radius,
  reaction_rate_constant, specific_capacity, stoichiometry_min/max
  (Minimum/MaximumStoichiometricCoefficient), surface_area_per_volume
  (VolumetricSurfaceArea), max_concentration, ionic_conductivity,
  electronic_conductivity, transference_number
  (ChargeCarrierTransportNumber), electrolyte_diffusivity
  (ChargeCarrierDiffusivityInElectrolyte), conductivity_activation_energy
  (ActivationEnergyOfElectrolyteConductivity), series_resistance
  (InternalResistance), and areal_mass (AreaDensity). Per the ratified
  depth rule (domain ontology carries base quantities plus at most one
  axiomatized facet; pre-coordinated parameter classes belong to
  application ontologies with bridge axioms; polarity/species/model
  context rides the graph, never the class name),
  diffusivity_activation_energy and reaction_rate_activation_energy type
  as the generic ActivationEnergy with the of-what carried by key, label,
  and claim structure. A key with no published class gets no invented
  one; see the entry on unmapped properties under Fixed above.

- `ws.status()` and `ws.pending()` now send the publisher API key from `ws.login()` (or `BATTINFO_ADMIN_TOKEN` when set). The registry's workspace views became credentialed because they list staged, not-yet-public submissions; without a key these two calls now print a hint and return an empty list instead of listing the queue.

- **BPX import drops nothing silently (parameter-plan Phase 0).** The
  `User-defined` block — BPX's extension point, previously ignored without
  a word - is now reported key-by-key, and unrecognised Parameterisation
  blocks are named. Header lineage rides the parameter-set record:
  `Description` as the record description and `References` as the
  provenance citation (verbatim as a note when it is not a URL/DOI),
  beside the model context the importer already stamped. A synthetic
  full-DFN golden fixture (structural twin of a published BattMo export,
  fabricated values - the original is GPL-3.0) pins the contract: every
  value in the file becomes a claim, the record's annex, or a named
  warning.

- **Parameter-set records emit against the records context.** The
  parameter-set JSON-LD - the payload the BPX "Metadata" seam embeds -
  now carries the hosted versioned records context
  (`context/records/v1.json`) instead of the live EMMO context, and every
  vocabulary parameter's terms resolve in it. License slugs
  (`cc-by-sa-4.0`) map to their absolute SPDX page IRI instead of
  emitting as relative IRIs; unknown values emit as literals, never
  broken links (applies to dataset records too).

- **The described individual gets a name: `<spec-IRI>#described` (JSON-LD
  dialect change, red-team ruling).** Every spec family's `isDescriptionFor`
  individual is now skolemized with the hash form of the spec's own IRI -
  dereferencing it fetches the spec document, repeated ingest merges instead
  of duplicating the physics, and the design becomes addressable from tests
  and BOMs. Nothing changes logically: no identity with any instance is
  asserted, and the existential-witness reading survives verbatim.
  `*_spec_id` reference edges now resolve to the target's described
  component (`hasElectrolyte -> <electrolyte-spec>#described`) - a physical
  relation lands on a physical individual, never on the Description
  document the range axioms would otherwise mistype.

- **Declared-value semantics tightened (red-team ruling).** `value_basis:
  "Nominal"` co-types as `ConventionalProperty` (EMMO's `NominalProperty`
  is VIM's no-magnitude property - colour, blood type - so it was a false
  claim on a numeric rating; upstream ask filed on `NominalBatteryProperty`
  too). Conditions on a declared value emit as named
  `schema:valueReference` qualifiers - the `isOutputOf ->
  BatteryMeasurement` subtree now appears only on `Measured` values, since
  it asserts a real process occurred. `voltage_reference` rides
  `schema:valueReference` everywhere (never `hasMetrologicalReference`,
  whose exactly-one slot the unit already fills - a second filler entailed
  `owl:sameAs` between the volt and the reference electrode). Material
  identity anchors (`schema:sameAs`, `skos:exactMatch`) move from the
  described substance to the spec node: `exactMatch` is symmetric and
  transitive, so on the witness it conflated every supplier's grade
  through the shared Wikidata IRI.

- **Format/IEC disjointness guard.** `cell_format: cylindrical` +
  `iec_code: cr2032` used to stack owl:disjointWith classes on one
  individual, making any merged graph OWL-inconsistent from one typo. The
  IEC code (the more specific claim) now wins with a warning; each
  `iec_code` entry in `entity_type_map.json` declares its format family.

- **ProductModel persona rounded out.** The described cell carries the
  ontology's own `hasIECCode` datatype slot beside `schema:productID` on
  the spec, and the spec node mirrors `schema:weight`/`height`/`width`/
  `depth` from the EMMO quantities so a schema.org-only consumer sees the
  product's dimensions (the EMMO encoding stays authoritative).

- **`electrode_spec.kind` becomes `active_material_kind`.** The field names
  the electrode's active material, so it now says so - a bare `kind` on an
  electrode reads as the electrode's form (porous, foil, rotating-disc), not
  its chemistry. The old spelling stays accepted as a deprecated alias (the
  `kind=` kwarg included) and normalizes to `active_material_kind` on
  round-trip; the packaged examples are rewritten to the canonical key.

- **The description pattern is complete: cell and material specs emit as
  descriptions (JSON-LD dialect change).** The last two spec families
  carried their physical payload on the specification node - a reasoner
  would classify the document as an electrochemical cell. Every
  EMMO-axiomatized physical fact (hasProperty quantities, electrode /
  electrolyte / separator / housing composition, construction, role
  holders, reference merges) now rides the described battery under
  `isDescriptionFor`; a material spec types `[Description,
  schema:ProductModel, schema:CreativeWork]` with the substance node
  (chemsub class, identity anchors, formula, properties) on the described
  individual. Spec nodes carry three personas by design: the EMMO
  information artifact, `schema:ProductModel` (newly stacked on every spec
  family) carrying the catalogue facts - name, manufacturer, brand, codes
  - in their documented schema.org home, and `schema:CreativeWork` for the
  record, with instances linking by `hasDescription` and
  `schema:isVariantOf`. The described individual is an existential
  witness: satisfied by at least one conforming unit, no identity asserted
  with any instance, epistemic status carried by the property-nature
  classes (documented in the cells design notes). The package importer reads the
  new location with old-shape fallback; published records stay valid
  forever - the old shape simply stops being produced, and the Flores v5
  corpus rebuild republishes in this final shape.

- **A housing is the enclosure assembly; all its parts ride
  `hasConstituent`.** EMMO's own definitions separate the case (the
  container) from the lid that closes it and the terminals, seals, and
  hardware beside it - the housing record describes that assembly, not a
  Case. Its described individual now types `ElectrochemicalComponent` (no
  `CellHousing` class is published; it joined the upstream ask list with
  `hasHousing` and `hasLid`) instead of the semantically empty
  `schema:Product` alone, and every part - the case (typed
  `CoinCase`/...), the cap (`CellLid`), terminals, seals, springs, spacers
  - lists uniformly under `hasConstituent`. This also retires the
  emission of `hasTerminal`, a relation with no term in the context. Cells
  keep the published `hasCase` pattern for their case.

- **Every component spec emits as a description, not the component.**
  Separator, current-collector, housing, and electrolyte specs had the same
  category error the electrode spec did: the JSON-LD node was typed as the
  physical thing. All spec records in these families now emit
  `[Description, schema:CreativeWork]`, and the ENTIRE physical node moves
  to the anonymous individual under `isDescriptionFor` - the class stack
  (`Separator`, `[CurrentCollector, Aluminium, Foil]`, `CoinCase`,
  `OrganicElectrolyte`, ...) and the physical relations and quantities
  (`hasCase`, `hasSolvent`, `hasCoating`, `hasConstituent`,
  `hasProperty`, the electrode's active-material seam and manufacturing
  route). The spec node keeps only artifact facts: id, name, manufacturer,
  citation. Instances keep their physical typing.

- **An electrode spec emits as a description, not an electrode.** Its
  JSON-LD node was typed with the physical electrode class
  (`GraphiteElectrode`, ...); a spec is an information artifact, so it now
  types `[Description, schema:CreativeWork]` - EMMO's `Description` being
  the parent class `BatterySpecification` itself subclasses - with the
  physical class stack on the anonymous individual under `isDescriptionFor`,
  the cell-spec pattern. When an `ElectrodeSpecification` class is published
  upstream (it is on the ontology-additions ask list) it replaces the
  generic `Description`. Electrode instances are physical objects and keep
  their typing.

### Changed

- **Electrolyte solvents lose their wrapper: `solvent` takes one or many.**
  A pure solvent is a single component object, a mixture is a list - no
  `solvent_mixture: {component: [...]}` level. The old spelling stays
  accepted as a deprecated alias and normalizes to `solvent` on round-trip
  (a wrapper carrying facts of its own is kept verbatim rather than
  silently flattened). Emission under `hasSolvent` is unchanged.

### Deprecated

- **`salt.cation` / `salt.anion` on electrolyte specs.** The salt's ions
  follow from its material identity - the kind resolves to the
  chemical-substance class, and `material_spec_id` cites the powder record
  - so they are never retyped in the formulation. The keys stay accepted so
  existing records keep validating; the emitter never read them.

### Fixed

- **Electrolyte composition fields are plain kwargs.** The generic
  component creators' first parameter was named `family`, colliding with
  the electrolyte's own `family` field (organic/aqueous) and forcing
  composition through `body=`. The parameter is now `component_family`
  (positional use, the only use in the wild, is unaffected), so
  `create_electrolyte_spec(family="organic", salt=..., solvent=...)` works
  as it reads.

### Added

- **Termination shorthand + the one-liner import (protocol usability).**
  Structured steps accept comparison-string cutoffs - `termination:
  ["Voltage > 4.2", "C-rate < C/50", "SOC < 0.05", "Time > 30 min"]` - the
  spelling engineers and UCP's `ends` use, normalized to the structured
  form at construction (stored records never carry the string; bad
  quantities and unit/quantity mismatches fail with a pointed message).
  And `battinfo import-protocol <file>` makes the whole import path one
  command: sniffs the format (UCP YAML, aurora-unicycler JSON, PyBaMM
  text/config, bmgen JSON-LD; `--format` overrides), emits the canonical
  record to stdout or `--out`, links the source file as the
  source_protocol artifact with its sha256, surfaces the lossy-import
  notes, and mints a deterministic IRI from the file hash so re-running
  the import is a no-op, not a duplicate. The pybamm and bmgen importers
  gained the `source_sha256` parameter the others already had.

- **`import_ucp`: ionworks Universal Cycler Protocol importer.** The
  fourth member of `battinfo.interop.protocols` (beside aurora-unicycler,
  PyBaMM, and bmgen): parses a UCP document (dict, YAML/JSON string, or
  path) into a structured `method[]` TestSpec. Charge/Discharge/Rest/EIS
  steps map by mode (C-rate/Voltage/Current/Power), `ends` comparisons
  become any-of terminations (voltage, C-rate, current, capacity, SOC,
  time), named repeat blocks become nested groups, and the `global` block
  lands on the blessed conventions (`initial_state_of_charge`,
  `ambient_temperature`, `resolution` -> `record`). Computational content
  (Control, set_variable, goto actions, expression-valued fields) stays
  with the linked `source_protocol` artifact and is recorded as notes,
  never silently dropped. PyYAML is an optional dependency (dict/JSON
  input works without it).

- **SOC-based termination and the initial-state convention (protocol
  interop).** `soc` joins the termination quantities (schema enum, vocab,
  emission as `StateOfCharge`), so SOC-stepped procedures state their
  levels directly - the HPPC example now encodes its nine levels as
  explicit `soc`-terminated discharges instead of time-at-C/3
  approximations - and UCP-style state cutoffs have a landing place. A
  protocol that assumes a starting state declares
  `conditions.initial_state_of_charge` (unit "1"), the blessed key
  importers map initial-state settings onto; the EIS-at-50%-SOC example
  demonstrates it.

- **A test execution inherits its identity from the linked protocol.**
  `Test(protocol=...)` accepts the `TestSpec` object itself: kind, protocol
  name, and `protocol_id` all derive from the spec instead of being retyped
  on the execution (an explicitly authored `kind=` still wins). The tests
  exemplar teaches the linked form. The GITT, HPPC, and rate-capability
  protocol examples gain full structured `method[]` step definitions
  matching their own descriptions, so their EMMO process graphs
  (`hasTask` chains with control and termination parameters) are no longer
  empty.

- **`spec_id=` is the uniform authoring shorthand.** Every instance creator
  (material, electrode, cell, equipment, and the generic component families)
  accepts `spec_id=` for its spec reference; the prefixed spelling
  (`material_spec_id=`, ...) stays accepted, and disagreeing spellings raise
  instead of silently picking one. Records are unchanged: they keep the
  self-describing `<type>_spec_id` key, so a fragment seen without its
  wrapper still says what kind of spec it points at.

- **Electrode genealogy: `parent_id` + `piece_id`.** A coating run
  makes one big source (a factory roll, a lab strip) and the electrodes that
  reach cells are cut from it. A cut piece now states which electrode record
  it was cut from (`parent_id`) and its label within that parent
  (`piece_id`, e.g. "disc-07", which joins the identity seed so siblings
  mint distinct IRIs; existing record IRIs are unchanged). Chains compose
  (roll -> sheet -> disc), each hop emits as `prov:wasDerivedFrom`, and the
  full lineage cell -> disc -> roll -> electrode-spec -> material-spec is
  walkable in the graph. The registry's reference-field machinery turns the
  new `*_id` field into forward links and a reverse cut-pieces panel on the
  parent once re-vendored.

- **Three-electrode cells are fully expressible.** The configuration
  existed in the `cell_configuration` enum but its distinguishing physics
  did not: `reference_electrode` was a bare string. It now accepts a full
  inline electrode holder (a lithium ring or wire is a monolithic
  `material=`) beside the legacy string, with a new
  `reference_electrode_spec_id` sibling; the `reference` role joins the
  role-typing rule; the holder emits as `hasReferenceElectrode` with
  `@type ReferenceElectrode` (a legacy string becomes a labeled typed node
  instead of staying record-only); and a latent bug is fixed where the
  enum value never reached the entity map, so `ThreeElectrodeCellDevice`
  now actually types the described device. Kept as a configuration of the
  cell record - the half-cell precedent - never a separate record type;
  the cell states its physical electrode arrangement, while the "vs what"
  of a measured voltage stays the quantity's `voltage_reference` datum.

- **Monolithic electrodes: `material` on the electrode holders.** A lithium
  counter is pure metal foil, not a coated electrode - there is no
  collector-plus-layer structure to describe. The inline electrode holder
  and the standalone electrode-spec gain `material` (a material-component:
  name / kind / material_spec_id / property) for uncoated electrodes;
  emission is the electrode's `hasActiveMaterial`, class-typed through the
  material map (which gains lithium metal -> `Lithium` and zinc ->
  `Zinc`). The half-cell exemplar's counter drops its coating wrapper for
  `{"material": {"name": "Lithium metal"}}`.

- **`coating.double_sided`.** A boolean on the electrode-coating block (the
  standalone electrode spec and the inline cell-spec holders share it)
  stating whether the current collector is coated on both sides or one. No
  EMMO class for coating sidedness exists, so it emits as a named
  `schema:PropertyValue` on the coating node until one is published.

### Changed

- **Measurement conditions ride the measurement, not the quantity (JSON-LD
  dialect change).** A quantity's `conditions` used to hang
  `hasMeasurementParameter` directly on the property node - a CHAMEO domain
  violation (a reasoner would classify the property as a process). They now
  emit on an anonymous measurement node the quantity `isOutputOf`, typed
  `BatteryMeasurement`, with each parameter carrying its condition key as
  `skos:prefLabel` and qualitative values as `hasStringValue` (never a fake
  quantity with unit "n/a"; `value_text` on a quantity likewise now emits as
  `hasStringValue` instead of `schema:value`). The test emitter gains the
  same shape: as-run conditions become typed `hasMeasurementParameter` nodes
  on the test node itself - the test is the measurement activity - beside
  the existing `schema:PropertyValue` copy. Already-published documents stay
  valid; the old flat shape is simply no longer produced. The hosted records
  context gains the new terms (append-only v1): re-vendor the registry
  context before publishing new-dialect records.

- **`voltage_reference` is a metrological datum.** "vs Li/Li+" qualifies the
  quantity itself, not the measurement: the `voltage_reference` conditions
  key (on quantities and on tests) now emits as EMMO's
  `hasMetrologicalReference` - the relation family `hasMeasurementUnit`
  belongs to; a potential carries two references, the volt as its scale and
  the reference electrode as its zero. Recognized couples (Li/Li+, Na/Na+,
  SHE, NHE, RHE, SCE, Ag/AgCl, Zn/Zn2+) resolve to class-typed
  reference-electrode nodes (`[ReferenceElectrode, LithiumElectrode]`);
  unrecognized notations keep an honest `MetrologicalReference` node
  carrying the text. Stating a counter electrode inside `conditions` is
  retired in the packaged examples: the datum is the reference couple, and
  the setup fact belongs to the test cell's own record.

- **A qualitative quantity needs no unit (the conditions ruling from #363).**
  The quantity schema required a unit even when the only value was
  `value_text`, which made honest qualitative conditions (`atmosphere:
  argon`, `voltage_reference: Li/Li+`) unrepresentable without a `"n/a"`
  unit hack. The unit requirement now exempts quantities carrying
  `value_text` alone; any numeric field still demands a unit. Applied across
  the quantity module, the cell-canonical `SpecItem`, the base-schema
  `Quantity`, and the cell-spec profile fragment.

- **`co_type` becomes `value_basis`; process condition keys take -ing names.**
  The basis on which a value is stated (Measured / Nominal / Rated /
  Conventional) is now authored as `value_basis` - `co_type` said nothing to
  a reader. And the advertised condition keys for processes follow the -ing
  convention that the direction-qualified capacity keys already use:
  `discharging_c_rate` / `charging_c_rate` (disambiguating the process
  "charging" from the noun "charge"). Both old spellings stay accepted:
  `co_type` as a deprecated schema alias that normalizes to `value_basis` on
  round-trip, the -e condition keys as tolerated inputs resolving to the
  same EMMO classes.

### Deprecated

- **`material_spec.electrode_polarity` and `material_spec.material_class`.**
  Polarity is an electrode property, never a material's, so
  `electrode_polarity` loses its authoring path entirely: the API kwarg is
  removed, the embedded-to-standalone bridge and `extract_material_specs`
  stop stamping it, and the packaged examples drop it — the schema accepts
  the key only so existing records keep validating. `material_class` is
  deprecated in favor of the kind's `roles` (strictly better information,
  multi-valued, curated); it stays accepted and importers still write it,
  slated for removal at the next record-shape version. The parameter-set
  claim scope named `electrode_polarity` is unrelated (it describes the
  electrode context of a measurement) and is retained.

### Changed

- **Material kinds carry `roles` (a list), replacing the single-valued
  `family`.** The old axis forced one role onto substances that legitimately
  play several and took sides on active materials (`active_anode` /
  `active_cathode`) — but roles are system-relative: graphite is the positive
  electrode of every lithium-counter half cell, FEC is both co-solvent and
  additive, CMC both binder and thickener. `roles` lists the use-site slots a
  substance is known to fill (coating roles, electrolyte constituents,
  component films/foils/coatings); it is informative, never normative — no
  validator rejects a use outside the listed roles. `active_material` is the
  one load-bearing role: it gates `electrode_spec.kind` and anchors reference
  properties. VC is refiled from solvent to additive; NMP carries an empty
  list (a processing solvent fills no composition slot). With the sides gone,
  the polarity-derivation chain retires: `create_electrode_spec` stamps
  `polarity` only when authored, the emitted `@type` carries a polarity class
  only for authored polarity, `semantic.electrode_polarity_conflict` is
  removed, and `electrode_polarity_for_kind` (never exported from the package
  root) is gone. Vocabulary 0.2.0 → 0.3.0. The registry re-vendors
  `material_kinds.json` after this merge.

### Fixed

- **The `modes` facet recurses into step groups.** A cycling protocol wrapped
  in a repeat group faceted as `modes: ["group"]`, so any consumer filtering
  on `modes` missed every cycling protocol; `control_modes`, `directions`,
  and the `has_*` flags already recursed. `modes` now lists leaf-step modes
  in first-encounter order and never contains `group` — group nesting stays
  visible in the method graph itself. Facets are stamped at publish time, so
  already-published records carry the old shape until re-emitted (#361).

- **Registry listings paginate; lookups no longer miss older records.** A
  single GET of `/resources` is capped by the server at one page (100 rows,
  newest first), and both the cell-spec search cache and the cell/serial
  lookup treated that first page as the whole catalog. Once the corpus
  outgrew a page, `ws.search` reported registered specs as missing and the
  cell lookup silently re-minted IRIs for serials that already had canonical
  ones (#340, #341). The client now pages with `limit`/`offset` until the
  listing is exhausted, and stops safely against a registry that predates
  pagination support.

### Added

- **`Step` gains an optional `step_id`.** A test-protocol method step can now
  carry the identifier assigned to it in the test program or schedule. The
  field name and semantics align with BDF `step_id`, but BattINFO does not
  depend on the BDF ontology; the field is not zero-based, contiguous,
  monotonic, or unique. `step_id` is unset by default and omitted when not
  given.

- **`theoretical_specific_capacity` joins the parameter vocabulary.** The curated
  material-kind reference anchors (graphite 372 mAh/g, silicon 3579, lithium
  metal 3862, LFP 170) are theoretical stoichiometric capacities, while
  `specific_capacity` is defined as the practical reversible value a design
  tool may trust. They get their own key so the anchors can be published as
  claims without a theoretical value ever satisfying a model tier's
  practical-capacity requirement. No tier contract changes.

- **Parameter sets emit JSON-LD and reach the deposit graph.** The exemption #347
  recorded is repaid: a parameter-set record now emits as one `schema:Dataset`
  node whose claims hang off the claim batch, not the target — asserting Chen
  2020's diffusivity directly onto graphite would collapse "this source claims
  X" into "X", which is the epistemic distinction the claim model exists to
  keep. The target rides `schema:about` (a `material_kind` types itself from the
  curated vocabulary and identifies as its chemical-substance class IRI, exactly
  like a material node; spec targets stay plain references so the described node
  lives in its own record). Scalar claims go through the same EMMO quantity
  emitter every component uses (`hasProperty` with real units and the labeled
  fallback for terms EMMO lacks); curve and expression claims ride
  `schema:variableMeasured` as PropertyValues — the expression string is carried
  verbatim, a curve is described (points, x-quantity, hysteresis branch) without
  restating the table the record file beside it already ships. Per-claim
  provenance class, method, and citation overrides survive onto each claim node;
  the record-level citation rides the dataset node. `record_to_jsonld` accepts
  `"parameter-set"`, and the kind moved from `DEPOSIT_COVERAGE_EXEMPT` to
  `DEPOSIT_STANDALONE_KINDS`, so published parameter sets are described nodes in
  every deposit rather than files a reader must open blind.

- **Parameter claims: the `parameter-set` record type.** Simulation parameters now have a home as *claims*: one record = one source (paper, BPX file, lab fit) making claims about one target — a curated `material_kind` ("graphite", "nmc811"), a specific `material_spec_id`, or a `cell_spec_id` for fitted sets and build parameters. Many records may claim values for the same parameter of the same material; the spread across sources is the point, and `battinfo.parameters.collate_claims` folds any number of records into `{parameter: [claim, ...]}` with per-claim source context. Each claim carries exactly one of `quantity` (scalar with unit/conditions), `curve` (tabulated y(x), e.g. an OCP with a hysteresis `branch`), or `expression` (a BPX-style function string kept verbatim), plus its own `provenance_class` (measured/fitted/literature/assumed/derived); the record-level provenance block carries the source citation. IRIs mint under `dataset/` with a uid derived from (target, scope, name), so re-importing the same source is idempotent. Parameter sets minted under `spec/` before 2026-10-11 are superseded by `dataset/` records; see "Changed (breaking — identifiers)" above.

  The shipped parameter vocabulary (`data/vocab/parameters.json`) defines the canonical keys, their physical scopes and units, and the model-tier completeness contract: `battinfo.parameters.completeness()` answers "which of bote/spm/spme/p2d can this material's claims support, and what is missing" — the same machine-readable contract downstream surfaces vendor so every consumer applies identical rules. Unknown keys are tolerated (tolerant-import policy) but never count toward a tier.

  Surface: `create_parameter_set` / `save_parameter_set` / `query_parameter_sets` / `template_parameter_set` on `battinfo.api`; `ws.add("parameter_set", name=..., material=..., claims=[...])` queues through the same stamp path as materials, so contributor/license/funding reach the records. `from_bpx_parameters` / `import_bpx_parameters` read the physics blocks `from_bpx` skips into one parameter-file record (see "A BPX file is one parameter-set record" above). Parameter sets have a JSON-LD emitter and go into deposits as nodes of their own (`DEPOSIT_STANDALONE_KINDS`).

- **A cell instance can cite the electrodes built into it.** `cell_instance` gains
  optional `working_electrode_id` and `counter_electrode_id`, pointing at `electrode`
  records — the coated batch or punched disc, not the `electrode-spec` design the cell
  spec already links. #342 deferred this as "no natural slot", having looked at the
  fourteen fields the record then had; the genome review asked for it directly ("the
  electrode should be linked to material and cell", "the same number of electrode
  instances as cell instances"), and #345 had by then decided what such a link is
  called. So the slot is not missing, it is named, and named the same way the cell
  spec's role holders are: role is assigned by the cell, because the same disc is a
  working electrode in one build and a counter electrode in another.

  Emission is a linked node — the `@id` is the electrode record's own IRI, and the only
  thing the cell contributes is the role class, so the electrode's chemistry, design
  link and as-built values stay on the electrode record and merge onto one node instead
  of being restated where they can drift. The half-cell rule follows #345 exactly: under
  `cell_configuration: half_cell` the counter electrode also carries `ReferenceElectrode`,
  a second `@type` on the one node rather than a second relation. An instance states no
  configuration of its own, so it reads its spec — the same inheritance that already
  gives it its physical type. Where the spec is not resolvable (`record_to_jsonld`
  transforms one record; so does the w3id resolver) the counter electrode types as
  `CounterElectrode` alone, because silence about the configuration is not evidence of a
  half cell. The counter-is-reference rule now has one implementation,
  `electrodes.electrode_role_types`, which the cell-spec holder emitter also calls, so a
  half cell cannot say one thing on its spec and another on its cell.

  Authoring: `ws.add("cell", …, working_electrode_id=…, counter_electrode_id=…)` takes
  one IRI for a batch of cells punched from one web, or a list assigning one electrode
  per cell — the shape the corpus actually has. A list of the wrong length is refused
  rather than zipped short. The reference resolves like every other `*_id`
  (`reference.missing` / `reference.type_mismatch`), and the schema pattern is scoped to
  the `electrode/` segment, so aiming the field at a spec fails instead of silently
  duplicating the design link. The IRI is deliberately not in the cell's identity seed:
  folding it in would re-mint every published cell the day a lab filled the field in.

- **A quantity can state the spread of the sample it summarises (gap E7).** `value` and
  `unit` gain optional `standard_deviation` and `sample_count` on the same quantity —
  the component `property` map and the cell-spec/cell-instance spec set both. The Flores
  corpus had per-batch statistics and published them as prose ("`3.6472 +/- 0.3017
  mg/cm2` … n = 8 cells") in a `notes` string, because the model had a slot for the mean
  and none for the spread: a structured key would have been dropped by the emitter, and
  a second property key mapping to `ActiveMassLoading` would have collided with the
  first. The number describing how much a batch varied was therefore unqueryable, and
  invisible to the EES crosswalk that asks for exactly it.

  Emission attaches both to the property node they qualify, through
  `schema:valueReference` — the `qualifier_relation` the cell-spec profile has declared
  since it was written and nothing used — as named `schema:PropertyValue` nodes, the
  deviation carrying the quantity's unit and the count carrying none. Not an EMMO class,
  because there is not one: the pinned closure publishes no `StandardDeviation`,
  `Variance` or `SampleCount`. It does publish `MetrologicalUncertainty`, which is
  deliberately not used — a sample standard deviation over eight discs describes a
  population of distinct objects, not the uncertainty attributed to one measurand, and
  typing it as uncertainty would be a category claim of the same kind as the
  `CapacityFade` mapping fixed in 0.37.1. The gap and the flip-when-published wiring are
  in `docs/internal/ontology-additions-needed.md`. A zero deviation is published rather
  than suppressed (three of the corpus's twelve batches repeat one declared number on
  every row, so 0 is the finding); a spread stated in `%` rescales with the value into
  the `[0, 1]` fraction encoding; and the prose form stays valid, so the records already
  on Zenodo keep validating — they simply no longer have to say it that way.

  No context change for either addition: the electrode role terms were appended to the
  frozen v1 context by #345, and the statistics use the already-declared `schema:`
  prefix rather than minting a term.

### Changed

- **EMMO pins: domain-battery 0.20.1 → 0.20.2, domain-electrochemistry 0.36.0 →
  0.37.2** (chemical-substance 0.15.0 and EMMO 1.0.2 unchanged). The bundled
  domain-battery context is refreshed to the 0.20.2 release, and every EMMO IRI
  in the curated mappings, static label tables, contexts and generated vocab was
  re-verified against the new closure: no dangling or drifted reference outside
  the frozen v1 context.

- **`PrismaticBattery` points at the underscore-named twin.** domain-battery
  0.20.2 minted `battery_86c9ca80_de6f_417f_afdc_a7e52fa6322d` and deprecated the
  hyphenated original with `dcterms:isReplacedBy` (upstream issue #73). New records
  carry the twin; the validator still accepts the hyphenated IRI, and the frozen
  v1 context still serves it, so records published before the flip keep validating.

- **Seven quantity slots leave the `battinfo:` namespace** for classes published in
  domain-electrochemistry 0.37.1: `capacity_fade` → `CapacityFadeRate`,
  `charging_time` → `ChargingTime`, `maximum_power` and `power_capability` →
  `MaximumPower` (`PowerCapability` is its altLabel, so both keys share one class),
  `power_energy_ratio` → `PowerToEnergyRatio`, `round_trip_energy_efficiency` →
  `RoundTripEnergyEfficiency`, `capacity_threshold_exhaustion` →
  `EndOfLifeCapacityThreshold`. `capacity_fade` also stops being a category error:
  it used to point at `CapacityFade`, an `ElectrochemicalDegradationPhenomenon` on
  the Process branch, so a unit-bearing datasheet value was typed as a process.

- **The `battinfo:` vocabulary honesty check sees the whole source tree.** It
  matched only double-quoted CURIEs, so `bundle_generated.py` — where LinkML
  renders `slot_uri` metadata with single quotes — was invisible to it, along with
  46 terms it never had to account for. The inventory is now sourced from the
  schema and from every published context as well as the working one, because
  retiring a term from the working context must not un-publish its IRI: documents
  minted against v1 still expand to it. `assets/vocab/battinfo-records.ttl` grows
  from 8 to 46 declared terms, all of which now dereference.

### Fixed

- **The descriptor emitter read every canonical cell-spec as a full cell.**
  `to_jsonld(record, target="domain-battery")` normalises a cell-spec record into
  the descriptor shape, and that adapter copied identity, format, chemistry and the
  electrode bases but not `cell_configuration` or `reference_electrode`. A half cell
  published through the canonical node builder therefore typed as `BatteryHalfCell`
  + `HalfCellDevice` while the same record exported through the descriptor path
  typed as a plain cell — the two emitters disagreed on the one field whose whole
  job is to say what kind of cell this is. Both fields are carried across now, and
  the single reading of them (explicit configuration wins, `reference_electrode` is
  the fallback marker) lives in one helper the descriptor path, the canonical node
  builder and the new role-holder typing all share, so they cannot drift apart
  again.

- **The deposit graph dropped the whole electrode layer (readiness finding E2).**
  `_assemble_zenodo_jsonld` promoted standalone `material-spec` and `material`
  records to first-class deposit nodes and nothing else, so `electrode-spec` and
  `electrode` records were read off disk, never used, and absent from
  `deposit.jsonld`: 301 nodes for the Flores corpus's 323 records, with the
  processing routes, compositions and design values missing from the published
  artifact. Both types are now promoted with their full emission. The set is
  named in `ws.DEPOSIT_STANDALONE_KINDS`, and `tests/test_deposit_coverage.py`
  sweeps every registered entity kind against `ws.DEPOSIT_COVERAGE_EXEMPT`, so a
  record type that cannot reach a deposit is a test failure rather than a report
  footnote.

- **The inline electrode-spec seam was not authorable (readiness finding E1).**
  `positive_electrode.electrode_spec_id` was in the JSON schema, read by the
  JSON-LD emitter and vendored by the registry, but the pydantic `Electrode`
  holder is `extra="forbid"` and had no such field, so the seam
  `docs/electrodes-model.md` recommends could only be written by hand-editing
  the record. Added to the model, along with `CurrentCollector.material_spec_id`
  (the same schema-only seam on the foil material, now also emitted as
  `schema:isVariantOf`), which the extended parity guard found alongside it. The
  doc now says which of the two spec seams to prefer and why they state
  different things.

- **The semantic validator warned about electrode design values it maps
  (readiness finding E5).** `_component_property_terms()` listed the emitter's
  holder term tables one by one and was never extended with the electrode table
  added in #342, so a correct `areal_capacity` on an electrode spec warned
  `semantic.property_unmapped` — three warnings for zero defects in the Flores
  corpus, breaking the invariant the helper's own docstring claims.
  `_MATERIAL_PROPERTY_TERMS` had drifted the same way for eight more keys
  (`bet_surface_area`, `specific_capacity`, `particle_size_d50` and friends). The
  emitter now exports one registry, `COMPONENT_PROPERTY_TERM_TABLES`, the
  validator derives its key set from it, and a guard test fails if any
  `_<holder>_PROPERTY_TERMS` table is missing from the registry.

- **`RoundTripEfficiencyValueShape` and `CapacityFadeValueShape`** targeted only the
  pre-0.37.1 classes, so the plausibility ranges silently stopped applying to
  records typed with the new ones. Both now target the new and the published IRI.

### Security

- **Dependabot backlog (web/)**: `postcss` bumped 8.4.39 → 8.5.16 and pinned
  via an npm `overrides` entry so Next.js's bundled copy (8.4.31) is forced to
  the same patched version — closes GHSA-qx2v-qp2m-jg93 (XSS via unescaped
  `</style>` in stringified CSS output) for both lockfile nodes. The Python
  lockfile audits clean (`pip-audit` over `uv export`, no known
  vulnerabilities). **Known remaining**: 14 advisories against `next@14.2.35`
  (DoS, cache-poisoning, XSS, SSRF, middleware-bypass families; e.g.
  GHSA-c4j6-fc7j-m34r, GHSA-36qx-fr4f-26g5, GHSA-q4gf-8mx6-v5v3) are only
  patched in Next >= 15.5.16 — the 14.x line is EOL with no backports, so the
  fix is a major upgrade (Next 15 + React 19 for App Router apps like this
  one), deliberately deferred to its own change rather than smuggled into a
  dependency sweep.

### Added

- **Role-based electrode holders — `working_electrode` / `counter_electrode`.**
  Maintainer ruling: do not use polarity in a half cell; use reference, working and
  counter electrode instead. Positive and negative describe the two sides of a
  *full* cell, and a half cell or a three-electrode cell has no such sides, so a
  cell-spec now carries a second electrode holder family selected by
  `cell_configuration`. The role holders are the same shape as the polarity ones —
  the inline `Electrode` (coating, current collector, tab, `property`, the
  `electrode_spec_id` seam) plus top-level `working_electrode_spec_id` /
  `counter_electrode_spec_id` siblings — so nothing about authoring an electrode
  changes except where it goes.

  They emit `hasWorkingElectrode` / `hasCounterElectrode`, typed `WorkingElectrode`
  and `CounterElectrode`. Under `half_cell` the counter electrode also carries
  `ReferenceElectrode`: a half cell has no third electrode, so its counter IS its
  reference (the `HalfCellDevice` axiom, and why the three role classes are
  non-disjoint upstream). It is stated as a second `@type` on the one node, never as
  a second relation to a second electrode. Under `three_electrode_cell` the record's
  separate `reference_electrode` field carries the reference and the counter
  electrode is typed `CounterElectrode` alone. Cell typing is untouched —
  `BatteryHalfCell` + `HalfCellDevice` and `ThreeElectrodeCellDevice` still come
  from `cell_configuration` — and so is composition typing: one shared builder emits
  the holder body for both families, because what an electrode is made of does not
  depend on the role it is given. `electrode_spec.polarity` also stays as it is:
  that is the *design's* intended full-cell side, derived from the kind, while roles
  are assigned at the cell level by the holder an electrode sits in.

  Mismatches are a save-time **warning**, never an error — the funnel stays
  tolerant and both families round-trip. Polarity holders on a stated half or
  three-electrode cell raise `semantic.electrode_role_expected`; role holders on a
  full cell (or an unstated configuration, which reads as one) raise
  `semantic.electrode_polarity_expected`; populating both families raises
  `semantic.electrode_holders_mixed`, which names the pair that fits the
  configuration. The six role terms are appended to the frozen v1 records context.

- **Test-protocol JSON-LD (readiness finding M5)**: `record_to_jsonld` now emits
  test-protocol records — the last record type it could not. The node is a
  `prov:Plan` / `schema:HowTo` that additionally types itself with the published
  characterisation-method class where the protocol's kind names one (GITT,
  pseudo-OCV, EIS, HPPC, cycling, rate capability, capacity check, formation),
  carries the descriptive method as a `hasTask` chain of typed EMMO process nodes,
  and stamps contributor/license/funding like every other record. The publication
  graph builder in `ws.py` had the only implementation; both callers now share one
  emitter in `battinfo.jsonld`, so a protocol published in a deposit and one
  exported standalone are the same graph. `ws.export()` writes protocols too.

- **`cell_spec.cell_configuration`**: optional `full_cell` | `half_cell` |
  `three_electrode_cell`, with no default. Absent still means unstated, which the
  emitter reads through the existing `reference_electrode` heuristic; a stated value
  wins in both directions, so `full_cell` suppresses the heuristic for a
  three-electrode full cell or a commercial cell under potential monitoring.
  `half_cell` types as `BatteryHalfCell` + `HalfCellDevice`, `three_electrode_cell`
  as `ThreeElectrodeCellDevice`. `reference_electrode` — permitted by the schema but
  previously unmodelled, so unauthorable and dropped on save — joins the model at the
  same time.

- **Material kind vocabulary top-up (0.2.0)**: six kinds added (`lto`, `lmo`,
  `hard_carbon`, `litfsi`, `lifsi`, `nmp`), taking the vocabulary to 38, and every
  kind now anchors to a `domain-chemical-substance` class — `silicon_graphite` and
  the four NMC ratios repoint onto the stoichiometric classes published in 0.15.0
  instead of sharing the generic `LithiumNickelManganeseCobaltOxide`.

- **External identity anchors on material kinds**: optional `wikidata_qid`,
  `inchikey`, `pubchem_cid`, `mp_id` and `cas_rn`. The three with a dereferenceable
  form emit as `skos:exactMatch` (Wikidata, PubChem, Materials Project), so a
  material joins those systems without a lookup table. Anchors are populated only
  where verified — an absent one means unverified, never guessed — and no InChIKeys
  are populated yet. `mp_id` denotes a representative ordered structure, so the
  solid-solution families carry none by design.

- **`Test.conditions`**: the `Test` model now carries the open, snake_case
  per-execution conditions map (temperature, voltage window, C-rate, frequency
  range, ...) that the test JSON Schema already defined but the model could not
  express, so conditions can be authored through the model and
  `Workspace.test(conditions=...)`. Values may be scalars, strings, or
  `{value, unit}` quantities; they round-trip through `to_record`/`from_record`
  and export to JSON-LD as `schema:PropertyValue` nodes under
  `schema:additionalProperty`.

- **EMMO label companion (`assets/vocab/emmo-labels.ttl`)**: a generated
  `skos:prefLabel` triple for every EMMO-family term the record emitters use
  (curated property classes, units, entity-map battery classes, quantity-node
  structure terms), produced by `scripts/gen_emmo_labels.py` from the same
  table the publication emitters use for inline contexts; drift-guarded by
  `tests/test_generated_reference.py`. Emitted quantity nodes and the
  `isDescriptionFor` physical individual now also carry an inline
  `skos:prefLabel` (the label already in hand), so exported RDF reads without
  dereferencing EMMO.

### Changed

- **The LinkML schema is the source of truth for the records context again.**
  `scripts/assemble_context.py --check` had been failing on ten keys, unnoticed,
  because its CI step ran `continue-on-error`. Every disputed key resolved in
  favour of the shipped context, so no published IRI changed; what changed is the
  `slot_uri:` declarations that produce them. Administrative provenance now
  declares the standard terms it has emitted since the vocabulary-policy pass
  (`source_type` -> `dcterms:type`, `source_url` -> `prov:hadPrimarySource`,
  `citation_doi` -> `bibo:doi`, `retrieved_at` -> `prov:generatedAtTime`,
  `workflow_version` -> `pav:version`); `source_file` drops its `slot_uri`
  entirely, because no standard vocabulary names the concept and the emitter never
  published it. `capacity_fade`, `power_density` and `specific_power` point at the
  `domain-electrochemistry` 0.36.0 classes rather than `battinfo:` mints. The
  generator learned three things the file already knew: the `bibo`/`pav`/`skos`
  prefixes (`skos` backs directly-emitted `skos:prefLabel` keys, so pruning it
  would silently delete every human label), `dcterms:created`/`modified` as
  `xsd:dateTime` (the emitter converts epochs to ISO-8601 before they become RDF),
  and no `"C"` unit symbol (in records `C` is only ever a C-rate, and a Coulomb
  term here shadows the correct mapping).

- **`records.context.v1.json` is append-only by construction.** `gen_context.py`
  merges every source with `setdefault` on top of what is already published, so
  regenerating can add a term but can never rewrite one. Bumping to a v2 file is
  the only way to change what a published term means.

- **The records-context freshness check is a hard CI gate**, alongside a new one
  for the hosted v1 context.

- **Emitter convergence step 4 — `record_to_jsonld` adopts the canonical
  cell-spec shape**: `cell_spec_to_jsonld` now delegates to the shared
  canonical builder (`battinfo.transform.cell_spec_node.build_cell_spec_node`),
  so all three emitters (resolver artifact, Zenodo/local publication graph,
  `record_to_jsonld`) produce the identical spec node:
  `@type ["BatteryCellSpecification", "schema:CreativeWork"]`, the physical
  EMMO class stack under `isDescriptionFor` (chemistry/format/electrode bases
  via @type stacking, not literal predicates), quantities as an EMMO
  `hasProperty` array, and a dcterms/PROV provenance node. The SHACL
  plausibility shapes were retargeted from the old EMMO-IRI-predicate
  flattening (`sh:targetObjectsOf`) to the typed canonical quantity nodes
  (`sh:targetClass`); web gallery/showcase JSON-LD and all guide outputs are
  regenerated in the new shape.

- **Emitter convergence step 5 — the `battinfo:` purge (IDENTIFIER_POLICY
  section 14)**: `battinfo:` never carries domain semantics; every EMMO
  duplicate and administrative term is deleted or re-homed to standard
  vocabularies. Highlights: cell instances are `BatteryCell` +
  `schema:IndividualProduct` with `hasDescription`/`schema:isVariantOf` spec
  links, `schema:identifier` PropertyValue batch ids, `schema:expires`,
  `schema:workExample` datasets; tests use `schema:additionalType` /
  `schema:instrument` / `schema:measurementTechnique` / `schema:actionStatus`
  / `hasTestObject` / `dcterms:conformsTo` / `schema:result`; provenance is
  the same dcterms/PROV node everywhere; the legacy metadata-record path emits
  EMMO battery classes, EMMO `hasProperty` quantities, `schema:Dataset` and
  `dcterms:conformsTo` (its `hasMeasurement`/`hasBattery` keys are now
  human-layer context aliases for EMMO `hasProperty`/`isDescriptionFor`);
  conformance deviations use `dcterms:type` + `schema:object`; the records
  context re-homes provenance aliases to `dcterms:type` /
  `prov:hadPrimarySource` / `bibo:doi` / `prov:generatedAtTime` /
  `pav:version`. Back-compat: the package importer still reads the legacy
  `battinfo:` keys from previously published packages, and the legacy
  dataframe `battinfo:columns` attrs key is still read (preferred spelling is
  now `csvw:column`). The generated record-layer vocabulary
  (`assets/vocab/battinfo-records.ttl`) shrinks from 40 to 10 terms — exactly
  the placeholder terms awaiting upstream EMMO releases (step 6, gated), with
  zero local residue — and `scripts/gen_battinfo_vocab.py` is now an honest
  closed inventory that fails the build on any unaccounted `battinfo:` mint
  (including f-string mints, its previous blind spot). `battinfo.ttl` is
  annotated as the EMMO import/pin manifest pointing at the record-layer
  companions.

- **Equipment workspace UX + SkyRC MC3000 canonical example (Phase A)**:
  registering the machine your tests ran on is now a workspace one-liner.
  `ws.add("equipment", spec=..., serial_number=..., name=..., location=...,
  channels=N)` saves the equipment-spec into the workspace if it is new
  (`spec` accepts a canonical record dict, a path to one, or its IRI), then
  creates the physical-unit record and N channel records (N defaults to the
  spec's `channel_count`) through the same canonical `save_record` path the
  api uses. The call is idempotent: the equipment uid is minted
  deterministically from (spec uid, serial number), channel uids from
  (equipment uid, index). `ws.add("test", ..., channel=...)` attaches a test
  to a channel — by channel IRI, channel label, or `"unit/CHn"` — resolving
  among channels registered this session and channel records already saved
  on disk, and stamps `equipment_id` + `channel_id` into the saved test
  record; an unknown reference lists the channels it knows.
  `ws.template("equipment-spec", ...)` writes a fillable draft that
  `ws.load()` lifts to a strict-valid canonical record with a
  natural-key-deterministic IRI. The equipment-spec schema gains optional
  `supported_chemistries` (unique non-empty strings), and the placeholder
  Neware BTS-4000 examples are replaced by a real, purchasable device: the
  SkyRC MC3000 4-channel charger-analyzer, with its full datasheet as a
  quantitative property set. New how-to: `docs/howto/register-equipment.md`;
  new website showcase entry "Equipment + channels". NOTE: the registry
  needs a schema re-vendor after this merge (equipment-spec schema changed).

- **Equipment + channel entity families (IDENTIFIER_POLICY 6.1)**: three new
  record types describe where a test physically ran. `equipment-spec` (the
  model, e.g. "Neware BTS-4000 series") mints under the shared `spec/`
  namespace like every reusable description; `equipment` (the physical unit,
  "Cycler 1") mints under `equipment/`; `channel` (one channel of one unit)
  under `channel/`. Channels are instance-only — no channel-spec kind — with
  FLAT IRIs: containment is never encoded in the address (channel boards get
  re-homed), the parent link `equipment_id` lives in the record body, and
  channel uids are minted deterministically from (equipment uid, index) so
  registration is idempotent. Equipment category (cycler, glovebox, ...) is
  data (`equipment_class`), never a namespace segment, and battinfo mints no
  domain classes for it. New builders `create_equipment_spec` /
  `create_equipment` / `create_channel` on `battinfo.api`; `Test` records
  gain optional `equipment_id` / `channel_id` links (`instrument` untouched);
  schemas, canonical examples, and the web validator all learn the three
  kinds.

### Changed

- **Namespace consolidation (IDENTIFIER_POLICY 6.1)**: every reusable
  description now mints under the shared `spec/` namespace — material,
  electrode, separator, electrolyte, current-collector, and housing specs
  join cell and test specs there. The namespace segment encodes exactly one
  distinction (description vs concrete thing); type lives in `@type`, and
  the generic segment has already survived three type renames that per-type
  segments would not have. Instance kinds keep their nouns (`cell/`,
  `material/`, `electrode/`, ...). Superseded `*-spec/` IRIs remain accepted
  everywhere as input (builders, references, schemas) and become permanent
  resolver aliases — nothing ever minted breaks. New import-time guard:
  reserved segments (`id`, `ontology`, `vocab`, `doc`, `context`,
  `resolver`, `twin`, `w3id`) can never become entity namespaces.


### Fixed

- **Bare string assigned to a `str | list[str]` field no longer explodes into
  characters (M2)**: `spec.specification_comment = "R2032"` used to serialise as
  `["R","2","0","3","2"]` and pass strict validation; `dataset.same_as =
  "https://doi.org/..."` produced one `not a 'uri'` error per character. A
  shared `_StrList` coercion (BeforeValidator + a `BundleJsonModel.__setattr__`
  guard) now wraps a bare string as `[value]` at construction and on assignment
  across every such field (CellSpec, Cell, TestSpec, Test, Dataset, Artifact).
- **Model enums now fail at construction, not late at `ws.save()` (M1)**: the
  `Step`, `Termination`, `Test`, conformance (`Conformance`/`Deviation`) and
  `Artifact` models validate their controlled vocabularies where a value is
  authored, with an error naming the valid values, and are drift-guarded against
  the save-time JSON Schemas. Previously `Step(mode="discharge")`,
  `Conformance(status="non_conformant")`, and others constructed fine but were
  rejected only at save. Affected fields: `Step.mode`, `Step.direction`,
  `Termination.quantity`, `Termination.direction`, `Test.status`,
  `Conformance.status`, `Deviation.category`, `Artifact.role`.
- **The site's own /docs quickstart crashed verbatim** (`cell_format=`, which
  `CellSpec` rejects) — fixed, and the snippet drift suite now EXECUTES every
  self-contained Python snippet on the site, so a non-running example fails CI.
- **battinfo.org's /docs page** links the six tutorial notebooks one by one
  (with current titles) instead of one folder listing; the dead
  web-validator-plan link and the "live converter" over-claim are gone.


### Fixed

- **The brand wordmark is now outlined vector paths.** The lockups are loaded
  via `<img>` tags (docs navbar, web navbar, README), and SVGs inside `<img>`
  cannot load webfonts — so "BattINFO" rendered in whatever fallback font the
  viewer's OS provided. The wordmark glyphs are now real Plus Jakarta Sans
  ExtraBold outlines (generated by `brand/tools/outline_wordmark.py`; the
  OFL-licensed font ships in `brand/assets/fonts/`). The README now uses the
  SVGs directly; the stale PNG renders are gone.


### Changed

- **Reference and Concepts sections restructured** (pass-2 review): Reference
  is now facts-only (Python API overview → generated API / property & unit /
  CLI / schema references → validation contract); Concepts tells a story
  (big picture → the spec-and-instance record model from materials up → the
  contracts). "Workspace authoring" and "How to read a published record"
  moved to How-to guides, where they belong.
- New **Identifiers & PURLs** concepts page: the IRI anatomy, the three
  promises (opaque / stable / deterministic-from-identity), the Crockford
  Base32 UID, the namespace map, and why w3id.org.
- New generated **Property & unit reference** (every curated property key
  and unit symbol, each linked to its EMMO/QUDT IRI) — produced from the curated
  mapping tables and drift-checked like the other generated references.
- Terminology: the five record types are "record classes" everywhere (the
  word "models" appeared only in docs); the homepage Python example used
  `cell_format=`, which `CellSpec` rejects — now `format=`, matching what the
  class accepts (the JSON record key stays `cell_format`; data contract
  unchanged).


### Changed

- **battinfo.org/examples is now "Describe your thing"**: nine entries —
  material, electrode, electrolyte, separator, cell spec, cell, test spec,
  test, dataset — each showing real authoring code next to the record it
  produces. The snippets live in `scripts/gen_web_examples.py`, are executed
  at generation time (so every example on the site is guaranteed to run), and
  are drift-checked in CI. The record → JSON-LD pairs remain as an "under the
  hood" section with their Playground links.
- **battinfo.org/properties is now a pointer** to the documentation's
  generated property & unit reference (reference material belongs in the
  docs); the in-browser explorer, its vendored data, and its CI sync step are
  removed. `battinfo properties show` remains the terminal equivalent.
- **New battinfo.org/about page**: mission, history (ontology → implementation
  layer), and the ecosystem (EMMO domain-battery, Battery Genome,
  battinfo-records, BIG-MAP, Battery Data Alliance). Nav gains About.


### Changed

- **The tutorials tell one story on the modern API.** Tutorial 3 (linked
  records) is rewritten on `battinfo.workspace()` — cells, a draft-file test
  spec with PyBaMM steps, a test with data, save, validation, a publication
  preview, and guarded publishing; the deprecated engine no longer appears in
  any notebook. Tutorial 2 sheds the material-level walkthrough that
  duplicated Tutorial 5 step-for-step and instead teaches the
  spec-and-instance model for materials (salts as `material(...)`, lifting
  components to standalone material specs). Tutorial 5 gains that lifting as
  a step of its own and now publishes the descriptor record directly.
- **Notebook bootstrap is two lines.** Notebooks run from their own folder
  (as nbmake/nbconvert always did) and write to a gitignored
  `docs/guides/_scratch/` directory — the cwd-detection/chdir preamble and
  `.battinfo/notebooks/` are gone.
- **Docs follow Diátaxis.** "Guides" are now *Tutorials* (learning-oriented,
  ordered, with a what-you-learn/time table); *How-to guides* state that they
  are task recipes; the landing page links the four quadrants explicitly.
  `getting-started` and `python-api` are rewritten around `workspace()` and
  the models (the engine appears only as an "advanced: internal" note), and
  the test-protocol semantic-depth essay moved from Tutorial 3 into the
  `test-specs` explanation page.
- `ws.convert()` without the BDF converter now points at
  `pip install "battinfo[processing]"`; README/QUICKSTART/getting-started
  document the extras.

### Fixed

- **`ws.preview_jsonld()` crashed on any workspace whose cells carry a
  production date**: records store `manufactured_at` as a Unix timestamp, but
  the publication assembler assumed a string (`AttributeError: 'int' object
  has no attribute 'strip'`). Timestamps now become UTC `xsd:date` values.
- **The gold-standard JSON-LD check rejected the library's own test-spec
  method graphs** (8 errors for `IterativeWorkflow`, `VoltageHold`,
  `Duration`, ...): the validator's allowed term set now includes the
  test-method vocabulary the emitter draws from the bundled context, with a
  can't-drift regression test.
- Two self-contradicting docstrings: `ws.add`'s example used
  `production_date="2026-01"` (a value it rejects — full dates required) and
  `construction()` suggested `layering="jelly-roll"` (not in the schema enum).


### Fixed

- **Unit mappings corrected at the source** (`unit_map.curated.json` + packaged copy):
  `°C`/`degC` now map to the unit `emmo:DegreeCelsius` (they pointed at the *quantity*
  `CelsiusTemperature`), and `W/kg` to `emmo:WattPerKilogram` (was a QUDT fallback).
  `W/L` and the percent symbols are unchanged pending ontology confirmation —
  `WattPerLitre` and a bare `Percent` unit do not exist in the bundled EMMO context.
- **The brand wordmark renders at its intended size**: the logo lockups' `<text>` carried
  a `.wm` class that was never defined anywhere, so "BattINFO" fell back to browser-default
  16 px inside a 470×112 canvas. The lockups now carry explicit type attributes; docs and
  website copies updated.


### Changed (installation — heavy dependencies became extras)

- **`pip install battinfo` is lean now**: core depends only on pydantic, typer, rich,
  jsonschema, rdflib, and pyld. Tabular file reading (pandas/pyarrow/openpyxl) moved to
  the **`[tabular]`** extra and RO-Crate output (rocrate) to **`[publish]`** —
  `pip install battinfo[tabular,publish]` restores everything. Features that need a
  missing extra raise a teaching error naming the exact install command; graceful
  optional uses (metadata enrichment) keep degrading gracefully.
- Cold import is ~0.5 s (from ~2.9 s pre-split): pyld/requests, rdflib, and jsonschema
  now load on first use, not at import.
- `battinfo.ws` is fully type-checked — the long-standing mypy exclusion (146 errors,
  mostly the `list` method shadowing the builtin in annotations) is burned down and
  removed.


### Changed (internal structure — no API change)

- **`battinfo.api` is now a package** split along its natural seams (templates,
  staging/submission, registry client, record store, resolver, components, index)
  behind a facade that re-exports the entire previous surface — every
  `from battinfo.api import X` that worked before still works. Shared helpers that
  had been copy-pasted across up to 8 modules (`_as_path`, `_now_iso`, `_sha256`,
  citation/DOI parsing) now live in `battinfo._util`, and the EMMO instrument map
  duplicated between api and publication has one home (`battinfo._emmo_instruments`).
  Cold import dropped from ~2.8 s to ~0.9 s as a side effect.


### Changed (curated namespace — one workspace)

- **The top level is now a curated ~34-name surface** (`battinfo.__all__`): the record
  models, `workspace()`, publish/save/query/validate, and `record_to_jsonld`. The other
  ~160 names remain importable from the top level for one release with a
  `DeprecationWarning` pointing at their home module (`battinfo.api`,
  `battinfo.interop`, `battinfo.metadata`, …); a guard test keeps the curated list from
  growing by accident.
- **There is one workspace.** `battinfo.workspace()` is the workspace; the object-graph
  engine is an internal (`battinfo._workspace`) and the top-level `Workspace` name is
  deprecated with a pointer. Legacy aliases (`TestProtocol`, `BatteryCell`,
  `BatteryCellSpecification`) moved to warning shims.


### Changed (breaking-with-shims — naming)

- **The record classes use one consistent short scheme:** `CellSpec`, `Cell`,
  `TestSpec`, `Test`, `Dataset`. `CellSpecification` and `CellInstance` remain
  importable everywhere they worked before — as silent aliases from `battinfo.bundle`
  and as one-release `DeprecationWarning` shims at the package level. The JSON record
  keys (`cell_spec`, `cell_instance`), IRIs, and schemas are unchanged: this renames
  the Python surface, not the data contract.
- `properties=` is the taught keyword for spec properties everywhere (docs, guides,
  workspace engine); `specs=` stays accepted as a quiet alias.
- CLI: `test-spec` is the command name (`battinfo query|save|template test-spec`);
  `test-protocol` still works as a hidden alias for one release.
- Committed guide-notebook outputs are scrubbed of machine-local paths
  (`scripts/execute_guides.py` executes + scrubs; a hygiene test keeps it that way).

### Added

- **Generated reference documentation** that cannot rot: the full CLI reference is
  generated from the typer app (`docs/pages/cli-reference.md`), the schema reference
  from the canonical JSON Schemas, and a curated API reference renders the pydantic
  models' field descriptions via autodoc-pydantic — each with a freshness test that
  fails when the committed page drifts from the code. Plus a new
  [infrastructure contract](docs/pages/contract.md) page for downstream builders.
- **Versioned documentation deploys**: pushes to main publish to `dev/`, release tags
  to `vX.Y.Z/` + `stable/` on GitHub Pages, with a version switcher in the theme and
  a root redirect (enable Pages from the gh-pages branch to activate).

- **Guide 06 — "Publish your first dataset"**: the end-to-end tutorial from a raw
  Neware CSV (a truncated sample now ships in `docs/guides/data/`) to validated,
  linked records and the guarded publish step — every cell executes in CI. Plus a
  new how-to gallery (`docs/howto/`): bulk ingest, fixing the five classic
  validation errors, resuming an interrupted submission, funding/ORCID tagging;
  the runnable pages execute under the doc-snippet CI harness.

### Fixed

- **A new `CellSpecification` passed to `ws.add("cell", spec=...)` now joins the
  save set** — previously it was left as an orphan: the instances referenced a spec
  that never got saved, and `ws.save()` failed with an obscure cell_spec_id error.
  Its IRI is minted at save like any authored spec.

- **Organization schema field `sameAs` renamed to `same_as`** — the one property the
  snake_case migration missed. The alias layer and the JSON-LD emitter already treated
  `same_as` as canonical; the schema (and two camelCase example records) now agree.
  Downstream note: the registry's vendored schemas need a re-vendor + pin bump.
- **The `ws.quickstart()` recipe runs again end to end.** `ws.add("cell", spec=<search
  hit>)` crashed with "Unknown field(s): _canonical_id=, type=" — a search hit carries
  index metadata, not authoring fields, and the stricter unknown-kwarg check (correctly)
  refused it. Hits are now resolved through the referenced-spec path, reusing the
  existing IRI; a plain-string `spec=` gets a one-line fix-it error
  (`spec = ws.search(...)[0]`). A new offline test executes the whole taught sequence
  (convert → search → add cell → add test → save) in CI so this seam cannot rot.
- **`ws` no longer crashes legacy Windows consoles.** User-facing prints carried `→` and
  `⚠️`, which raise `UnicodeEncodeError` on cp1252/cp437 stdout — `ws.convert()` died
  *after* a successful conversion. All printed strings are ASCII now, and a test forbids
  non-ASCII in ws.py print calls.

### Changed

- **`save_*` minting is now idempotent** (beta-hardening 3.3): a record saved without an
  `id`/`uid` mints its IRI deterministically from its natural identity key, using the same
  seeds as the workspace finalizers — so the api and workspace paths mint identical IRIs
  for identical identities, and re-running an identical ingest is a no-op
  (`status: exists`/`updated` with `content_changed: False`) instead of a duplicate corpus.
  Natural keys: cell-spec = manufacturer::model::format::chemistry::size_code;
  cell = cell_spec_id::serial::batch::name; test-spec = kind::name::version;
  test = cell::kind::protocol::name; dataset = cell::test::locator::name. A record with no
  distinguishing identity (e.g. a cell instance with no serial/batch/name) still mints a
  random IRI, so distinct anonymous records never silently dedup.

### Deprecated

- The retired `*Input` names import again as **deprecation shims** for one release:
  `CellSpecificationInput`, `CellInstanceInput`, `TestInput`, `DatasetInput`,
  `TestSpecInput`, `TestProtocolInput` resolve to their models with a
  `DeprecationWarning` naming the replacement (PEP 562), so downstream pinners get a
  migration message instead of an `ImportError`. The legacy keyword form
  `publish(cell_spec=..., ...)` also warns — call `publish_publication_package(...)`
  explicitly. The deprecation policy is now written down in CONTRIBUTING.md, and
  RELEASING.md gains a "sweep expiring deprecations" step.
- The `battinfo.publish` **submodule** moved to `battinfo._publish`, ending the
  function/module shadowing where importing the submodule silently rebound the
  `battinfo.publish` attribute from the function to the module. The documented
  surface (`from battinfo import publish`, `PublishResult`) is unchanged.

### Added

- **`ws.submit()` is resumable** (beta-hardening 3.5): every outcome is journaled to
  `.battinfo/submit-journal.jsonl` as it happens, and a record whose identical payload
  already succeeded in a previous run is skipped (`status: skipped_journal`) instead of
  re-POSTed — resuming an interrupted bulk submission re-sends only what is missing.
  Failed records are journaled but retried on resume; changed content re-submits.
  `ws.submit(resume=False)` bypasses the journal. (Transient-failure retry with
  exponential backoff already ships in `submit_publication_package`; HTTP connection
  pooling is deliberately deferred — stdlib-only HTTP, and the planned registry bulk
  endpoint is the right fix for per-request overhead.)
- **`battinfo.bulk_save_session(source_root)`** — a context manager that makes bulk
  ingests fast: the id→path map is scanned once per entity type instead of per save,
  every save keeps it current (so records saved in the batch resolve as references for
  later records), and the per-file fsync is skipped because a bulk batch is re-runnable.
  Measured on the 400-record benchmark (`scripts/bench_bulk_save.py`): 18 → 385
  records/s (21×); a 10k-record ingest completes in under half a minute.
  `Workspace.save()` and `save_batch` (Python + CLI) use it automatically.
- **Every emitted record's provenance block now carries `battinfo_version`** — the version
  of the battinfo library that wrote the record — so records are forensically attributable
  to a build. The stamp is applied at emission (model `to_record()` and the direct api.py
  record builders); an explicitly set value is preserved, so re-serialising another build's
  record does not falsify its origin. All record schemas (packaged and `assets/` sources,
  plus the cell-spec profile fragment) allow the new optional field. Downstream note: the
  registry's vendored schemas need a re-vendor + pin bump when this ships.
- `battinfo.AuthoringWorkspace` is exported by name (previously reachable only via the
  `battinfo.workspace(...)` factory); its docstring now points at the correct engine class.
  A new [Workspace authoring](docs/workspace-authoring.md) doc page mirrors
  `ws.quickstart()`, and QUICKSTART/README carry a "Which surface do I use?" table mapping
  the three entry points (authoring workspace, models + `publish`, `battinfo.Workspace`
  object-graph engine). The internal `WorkspaceManifest` in `workspace_state.py` is renamed
  `WorkspaceStateManifest`, ending the name clash with `local_workspace.WorkspaceManifest`.
- Every field of the five authoring models (`CellSpecification`, `CellInstance`, `Test`,
  `TestSpec`, `Dataset`) and `ProvenanceInfo` now carries a `Field(description=...)`,
  surfacing in `help()`, IDE hover, and `.model_json_schema()`. Descriptions note the flat
  authoring aliases (e.g. `title=` for `Dataset.name`, `kind=` for `test_type`). A test
  gate keeps new fields from shipping undocumented.

### Changed (interop sharp edges)

- `import_discovery_eln` accepts real `.eln` exports (ZIP archives wrapping the crate),
  not just an unpacked crate directory or a bare `ro-crate-metadata.json`.
- Importer JSON parse/read errors now name the offending file (shared
  `load_json_source` across the BDC, BPX, converter, discovery, and protocol importers).
- The aurora-unicycler importer surfaces a present-but-unparseable numeric field as a
  warning on the imported test spec instead of silently ignoring it.
- Batch imports that produce zero records from a real source say so in the package
  warnings instead of returning an empty result silently.

### Changed (validation errors aggregate and teach)

- Save/publish validation failures now report **every** error in one message instead of
  only the first, so a record with three problems is fixed in one pass, not three.
- Canonical record paths in error messages translate back to the authoring vocabulary
  (`cell_spec.cell_format` → `format=`, missing `provenance.source_type` → `source_type=`).
- Quantity-shape errors include a copy-pasteable example
  (`{"nominal_capacity": {"value": 0.0, "unit": "ah"}}`) and point at
  `battinfo properties show <name>` for the accepted units.
- A misspelled keyword argument on any of the five record models now raises a `TypeError`
  with a did-you-mean (`manufacture=` → "did you mean `manufacturer=`?") covering fields,
  aliases, and all spec property names, instead of a bare pydantic extra-field error.

### Changed (nothing accepted is silently dropped)

- `specs=` must be a mapping of property name → value; a list or scalar now raises a
  `TypeError` showing the expected shape (it used to be discarded without a word).
- Provenance kwargs accepted at construction (`source_name=`, `file_hash=`, `curated_by=`,
  `workflow_version=`, provenance `comment`) are now emitted by every record type's
  serializer and read back by `from_record` — previously four of the five serializers
  silently omitted them. All record schemas (assets + packaged copies) accept the full
  provenance field set; each schema's `required` list is unchanged. **Registry note:** the
  vendored schemas in battinfo-registry must be re-synced before records carrying the new
  optional fields will pass its gate.
- Passing a cell/cell-spec object positionally together with a conflicting `cell_id=`/
  `cell_spec_id=` kwarg now raises naming both ids; with a matching id the object is kept
  (it used to be silently discarded whenever the id kwarg was present).

### Changed (record format)

- Every emitted record now carries `schema_version: "0.2.0"`, stamped from a single
  `battinfo.bundle.SCHEMA_VERSION` constant used by the pydantic models, the dict-path
  record builders, and the interop importers. This deliberately supersedes **both** prior
  values: the original `"0.1.0"` (dict-path cell spec/material/component records) and the
  `"1.0.0"` that model-path records had silently picked up during the input-model
  consolidation. Reading a record preserves its stored version; only newly emitted records
  get the new stamp. Downstream consumers should accept `0.1.0`, `1.0.0`, and `0.2.0`.

### Changed (stop fabricating provenance and URLs)

- Records no longer invent `source_file: "manual.json"`: the optional provenance
  `source_file` is now absent unless you (or a real source path) provided it. The CLI
  `--source-file` options default to unset accordingly.
- Serializing a dataset without any URL now raises an actionable error naming
  `access_url` instead of emitting a fabricated `https://example.org/dataset/...`
  placeholder (the schema requires `dcat:accessURL`; a provenance `source_url` also
  satisfies it, and workspace/publication flows still derive it from the dataset path).
  Synthesized distributions likewise reuse real URLs only. Flow-specific handling:
  - the Zenodo package flow stamps the documented `https://zenodo.org/records/ZENODO_RECORD_ID`
    placeholder that `patch_zenodo_urls()` rewrites after upload (the old example.org
    fallback was never patched, publishing fake URLs in harvested bundles);
  - the tolerant BDC importer falls back source_urls → download_urls → a truthful
    `urn:battery-data-commons:record:{id}` catalog URN (with a warning);
  - the Discovery .eln importer uses the dataset's real archive URL;
  - `template_dataset()` exposes `access_url` as a visible replace-me example parameter.
- `source_type` remains schema-required, so save paths still apply the documented
  category defaults (cell spec: `datasheet`, instance/test/ws-dataset: `measurement`,
  dataset dict-path: `other`, test spec: `manual`) when unset — these are deliberate,
  documented defaults, no longer accompanied by a fake source file.

### Changed (breaking — authoring API)

- The per-record-type input classes are retired: the pydantic models are now both the
  canonical source of truth **and** the authoring input. Construct the model directly with the
  same field names you passed before and hand it to the matching `save_*` function.
  - `CellSpecificationInput` → `CellSpecification`
  - `CellInstanceInput` → `CellInstance`
  - `TestInput` → `Test`
  - `DatasetInput` → `Dataset`
  - `TestSpecInput` (and the `TestProtocolInput` alias) → `TestSpec`
- Each model accepts the flat authoring shape directly (e.g. `model_name`, `notes`,
  `source_type`, PyBaMM-style `experiment=[...]`) and normalizes it internally, so most call
  sites change only the class name.

### Added

- A dataset can now relate to multiple cells and tests via `related_cell_ids` /
  `related_test_ids` (previously a single cell/test reference silently dropped the extras).
- Test-spec artifacts are validated as structured `Artifact` objects on save (previously passed
  through unchecked), so a malformed artifact fails fast.

### Fixed

- Dataset `creators`/`funders`/`publisher` entries now preserve `orcid` and classify agents
  carrying an ORCID or given/family name as `Person` (the retired hand-builder passed these
  dicts through verbatim; the model's canonicalizer was silently dropping the ORCID and
  defaulting people to `Organization`).
- `CellInstance.expires_at` is converted to a Unix timestamp at save time, exactly like
  `manufactured_at` (ISO strings previously reached stored records unconverted).
- Provenance `retrieved_at` now accepts ISO datetime strings on every record builder (only the
  test-spec builder converted them before), preserves epoch zero, and raises on an unparseable
  value instead of silently substituting the current time.
- A flat string `citation=` kwarg on `Dataset` is routed to provenance even when an explicit
  `source=` is also given (it previously leaked into the bibliographic `citations` list); an
  already-set `source.citation` wins. List/dict citation values remain bibliographic.
- Timezone-naive timestamps (a bare ISO date such as `"2022-01-15"`, or a time with no offset)
  are now anchored to UTC before conversion. Saved record timestamps
  (`manufactured_at` / `started_at` / `ended_at` / `created_at`) were previously interpreted in
  the authoring machine's local timezone, making the same input non-reproducible across machines;
  an explicit offset is still respected.
- Datasets always emit the schema-required `access_url` (falling back to the provenance URL, then
  a stable id-derived value), so a dataset built directly from the model can no longer serialize
  into a schema-invalid record.

### Fixed

- **Schema/model parity is now swept, not discovered.** `Test.conditions` (#329)
  and `reference_electrode` (#334) were the same bug found twice: a property the
  JSON schema defines that the model cannot express, or accepts and drops on save.
  `tests/test_schema_model_parity.py` walks all 362 properties of all 21 record
  types and fails on either shape, with an allowlist that carries a reason per
  entry and a companion test that fails when a listed gap is quietly closed. The
  sweep found no new silent-loss bugs, and 22 further schema properties with no
  authoring path: the EU Battery Regulation passport fields
  (`hazardous_substances`, `battery_status`, `dpp_status`, `service_start_date`,
  ...), a few schema.org descriptive slots, and `TestSpec.conditions`, which is
  typed `dict[str, Quantity]` and so cannot hold the textual conditions the schema
  permits (readiness finding M4, still open).

## [0.7.0] — 2026-06-19

This version was never tagged or uploaded to PyPI; 0.8.0 is the first PyPI release.

First publication of the `battinfo` **Python package** (library + CLI) to PyPI.
The package, CLI, and OWL application ontology now share a single version line,
continued from the prior ontology releases (… 0.5.0, 0.6.0 → **0.7.0**).

### Packaging & release

- First PyPI release of `battinfo` (`pip install battinfo`); requires Python 3.11+.
- Unified the package and ontology on one version; `battinfo.ttl` `owl:versionIRI`/`owl:versionInfo` bumped to 0.7.0.
- Single-sourced the version from `battinfo.__version__` (pyproject `dynamic`), so it can no longer drift across files.
- Added a PyPI trusted-publishing (OIDC) release workflow, `RELEASING.md`, and a `twine check` step in CI.
- Redesigned CI into a publication-grade suite (lint/type, matrix tests, packaging, security/pip-audit + CodeQL, docs build) with the test suite as a pre-publish gate.

### Reliability

- JSON-LD validation, URDNA2015 normalization, and RDF materialization now run **fully offline**. The EMMO domain-battery and battinfo records contexts are resolved from bundled copies for **both** rdflib and PyLD (previously only PyLD/URDNA2015 used the local EMMO copy, and rdflib still fetched contexts over the network). Publishing or validating a record no longer requires a live network connection.
- The test suite is socket-blocked (`pytest-socket`) to enforce offline operation; this also cut test wall-clock roughly 6× by removing context-fetch timeouts.

### Ontology

- Upgraded EMMO dependency pins: domain-battery 0.18.8 → **0.19.0** (introduces `BatterySpecification` class hierarchy)
- Bundled EMMO context patched with 6 new 0.19.0 terms: `BatterySpecification`, `BatteryCellSpecification`, `BatteryModuleSpecification`, `BatteryPackSpecification`, `BatterySystemSpecification`, `BatterySystem`

### Semantic type migration (breaking change for downstream JSON-LD consumers)

- **Cell-type records** (`@type`): replaced EMMO physical stacking + `schema:ProductModel` with `BatteryCellSpecification` (domain-battery 0.19.0 term; subclass of `emmo:Description`)
  - EMMO physical type stacking (format + chemistry + electrode basis) moved to an `isDescriptionFor` anonymous node on the specification
  - `schema:category` and `schema:material` removed (semantically incorrect on an information entity)
- **Cell-instance records**: removed `schema:IndividualProduct`; added `hasDescription` (EMMO) alongside retained `schema:isVariantOf` (schema.org) for backward compatibility
- `bundle.py` bundle loader updated to detect both old (`schema:CreativeWork`) and new (`BatteryCellSpecification` with `schema:about`) cell-specification node formats, and to read `hasDescription` or `schema:isVariantOf` for the cell-type back-reference

### Previous entries (domain-battery 0.18.7 → 0.18.8 cycle)

- Upgraded EMMO dependency pins: domain-battery 0.18.7 → **0.18.8**, domain-electrochemistry 0.33.0 → **0.34.0**
- Bundled EMMO domain-battery context refreshed (4,900+ terms; enables offline JSON-LD processing)
- Added `.tools/quality/check_emmo_versions.py` — reports whether `owl:imports` IRIs in `battinfo.ttl` match the latest upstream releases

### Semantic mapping

- `property_map.curated.json` expanded from 38 → 47 curated entries; version bumped to 0.3.0
  - New: `NominalEnergy`, `typical_energy` (legacy alias → NominalEnergy), `CalendarLife`, `InitialCoulombicEfficiency`, `DCInternalResistance`, `ACInternalResistance`, `SelfDischargeRate`, `StateOfHealth`
  - All IRIs verified against domain-battery 0.18.8 and domain-electrochemistry 0.34.0
- `entity_type_map.json` updated; version bumped to 0.2.0
  - Added chemistry: `na-ion` → `SodiumIonBattery`
  - Added negative electrode: `silicon-graphite` → `SiliconGraphiteElectrode`, `hard-carbon` → `HardCarbonElectrode`
  - Fixed `lco` battery class: was `LithiumIonBattery` (generic), now `LithiumIonCobaltOxideBattery`
  - Fixed `nca`: dropped unresolvable `node_type` reference to non-existent `LithiumNickelCobaltAluminiumOxideElectrode`

### JSON-LD / RDF correctness

- **Resolver JSON-LD** (`_resolver_jsonld`): removed all undefined `battinfo:` terms
  - Cell-type `@type` now uses full EMMO stacking (format + chemistry + electrode basis) plus `schema:ProductModel`
  - Replaced `battinfo:chemistry` / `battinfo:format` with EMMO `@type` stacking; information is now in the type graph, not as bare string predicates
  - Replaced `battinfo:sizeCode` → `schema:size`
  - Cell instance: `battinfo:BatteryCellInstance` → `["BatteryCell", "schema:IndividualProduct"]`; `battinfo:typeId` → `schema:isVariantOf`; `battinfo:serialNumber` → `schema:serialNumber`; `battinfo:hasDataset` → `schema:workExample`
  - Test protocol: `battinfo:BatteryTestProtocol` → `["BatteryTest", "schema:HowTo"]`; `battinfo:testKind` → `schema:category`
  - Test: `battinfo:BatteryCellTest` → `BatteryTest`; `battinfo:aboutCell` → `schema:object`; `battinfo:usesTestProtocol` → `schema:instrument`; `battinfo:hasDataset` → `schema:result`
  - Dataset: `battinfo:aboutCell` / `battinfo:aboutTest` → `schema:about`
- **Descriptor JSON-LD**: removed `schema:valueReference` misuse; each ConventionalProperty node now follows the canonical EMMO single-value pattern
- **Descriptor JSON-LD**: fixed null `@id` bug — when a specification dict has no `id` field, `@id` was silently set to `null`, causing URDNA2015 normalization failures; `@id` is now only emitted when the value is non-null
- **Cell instance `@type`**: now always carries both `BatteryCell` (EMMO scientific type) and `schema:IndividualProduct` (schema.org product type)
- **URDNA2015**: offline EMMO context fallback wired — JSON-LD normalization no longer requires a live network connection
- **rdflib DeprecationWarning**: internal rdflib 7.x warnings no longer surface as false JSON-LD parse errors under `-W error`
- **`publication.py` `PROPERTY_TYPE_MAP`**: `battinfo:RatedEnergy` corrected to `RatedEnergy` (EMMO term); `battinfo:TypicalEnergy` replaced by `NominalEnergy`; added `nominal_energy` entry

### Schemas

- `cell-canonical.schema.json` SpecSet: added `calendar_life`, `nominal_energy`, `dc_internal_resistance`, `ac_internal_resistance`, `self_discharge_rate`, `initial_coulombic_efficiency`, `state_of_health`

### Python API

- `authoring.py`: full rewrite with docstrings on all 8 exported functions (`properties`, `construction`, `source`, `material`, `bom`, `electrode`, `electrolyte_recipe`, `separator_spec`, `cell_description`)
- Dead code removed: `CORE_PROPERTY_PREDICATES` dict and `_property_predicate()` function in `json_to_jsonld.py` (never called)
- `publish()` high-level API: `destination="local"`, `destination="registry"`, `destination="battery-genome"` paths implemented and tested
- `publish_record()` / `save_record()` low-level API: dry-run, upsert, and duplicate-policy modes tested
- Added `py.typed` marker (PEP 561)

### Validation

- Publication validation: `schema:about` reference check now correctly scoped to `@graph` publication packages only; standalone resolver documents may carry cross-document references without triggering a false `reference_missing_node` error

### Tests

- Added `tests/test_authoring.py`: 50 tests covering all `battinfo.authoring` exported functions
- Added entity type mapping tests in `test_mapping_governance.py`: na-ion, LCO, NCA (no node_type), silicon-graphite, hard-carbon
- `test_publish.py` expanded: resolver JSON-LD correctness, `schema:valueReference` absence, cell instance dual `@type`, `publish()` local/registry/battery-genome destinations, `save_record()` lifecycle
- Suite total at release: 938 tests, all passing on Python 3.11/3.12 (Linux + Windows)

---

## [0.1.0-alpha] — 2026-03-01

Initial internal pre-release. Core cell-descriptor validation, mapping, and publication workflows.
