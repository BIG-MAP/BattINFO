# JSON-LD normalization infrastructure — plan

Goal: ingest arbitrary, messy, real-world JSON-LD battery metadata and turn
it deterministically into either (a) a canonical record with full repair
provenance, or (b) a precise, actionable gap report. No guessing, no
per-document human or agent intervention in the runtime path.

Principle: JSON-LD documents are trees; the data model is the graph. All
processing happens on the expanded graph, keyed on absolute IRIs — never on
JSON paths. Rules are versioned data files applied by one generic engine;
same document + same ruleset version = same output.

## The recovery ladder (each tier deterministic)

1. **Syntactic variance** — nesting, compaction, aliases, arrays, @graph
   wrapping. Erased by standard JSON-LD expansion (pyld). No configuration.
2. **Context damage** — missing/404/moved @context. A pinned local context
   store (schema.org, DCAT, PROV, QUDT, EMMO, ours; versioned copies in the
   repo). Never fetch remote contexts at ingest (determinism + the
   remote-context substitution attack). Context-free documents: a signature
   table mapping characteristic key-sets to a presumed vocabulary — lookup,
   not judgment.
3. **Vocabulary synonymy** — same concept under different IRIs. Curated
   alignment table in SSSOM format (TSV in-repo), applied as graph rewrites.
   Grows with the corpus; application is mechanical and diff-reviewable.
4. **Value-shape repair** — literals where nodes are expected (string
   manufacturer -> Organization node), packed value+unit strings ("3.5 Ah",
   parsed unit-aware via pint), unit-code alignment (QUDT/UCUM/EMMO symbols
   -> unit map). Per-property coercion rules keyed on the target IRI,
   carried alongside the existing curated property map.
5. **Identity repair** — missing @id, blank nodes, non-IRI ids.
   Deterministic re-minting from identity fields (existing machinery);
   original identifier preserved via prov:wasDerivedFrom.
6. **The floor: missing semantics** — unstated electrode polarity, numbers
   with no unit anywhere, unmapped intent. Quarantine with a machine-
   generated gap report. Unmapped triples are preserved verbatim in an
   extension block (no silent drops). The pipeline never infers here.

## Pipeline

expand -> tier 2..5 repairs (rule engine) -> SHACL validation on the graph
(shapes bind to targetClass, so they are shape-of-tree agnostic) -> frame to
the canonical record shape -> existing schema validation -> existing record
pipeline. Quarantine exits at tier 6 or on SHACL failure that repairs cannot
address.

## Reproducibility properties

- Rules are data: context store, signature table, SSSOM alignments,
  coercion rules — versioned files, one engine. New mess = new table row +
  PR, not new code.
- Provenance per record: a PROV normalization activity naming the ruleset
  version and the rules that fired. Auditable; re-runnable when rules
  improve.
- Regression corpus: every real messy document encountered becomes a
  fixture with its expected normalized output (extends the interop-fixtures
  policy). Resilience ratchets; no handled mess ever regresses.

## Where agents fit

Never in the runtime path. Agents mine rules at curation time: read the
quarantine queue, propose SSSOM rows and coercion rules for recurring
patterns, submit as reviewable PRs into the versioned tables. Deterministic
runtime, agent-assisted curation.

## Deliverables

- `battinfo.normalize` module: expand + rule engine + frame + report.
- `import_jsonld()` tolerant reader on top of it (importer-matrix entry).
- Rule tables beside assets/mappings/ (context store, signatures, SSSOM,
  coercions), each with a drift/coverage test.
- Quarantine report format (machine-readable + human summary).
- Corpus fixtures under the interop test-data policy.
- Later: registry submission mode accepting raw JSON-LD through the same
  funnel; the battinfo.org JSON-LD workbench (viewer/validator, separate
  handoff) shares the expand->frame core client-side.

## Sequencing and effort

Post-0.8, ordered against the existing backlog: P3 (workspace parity) ->
P4 (registry material types) -> this. The viewer can land earlier (it is
read-only and independently useful). Rough effort: engine + tiers 1/2/5 ~2
days; tiers 3/4 rule formats + first curated tables ~2 days; corpus +
quarantine reporting ~1 day. Curation is ongoing by design.

## Non-goals

Per-shape adapters; path-based migration scripts; heuristic inference at
tier 6; requiring authors to rewrite legacy documents; agent-in-the-loop
ingest.
