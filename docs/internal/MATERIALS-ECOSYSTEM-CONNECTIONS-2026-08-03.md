# External materials-ecosystem connections — research report 2026-08-03

Status update (2026-08-26): R1 (multi-anchor identity fields on
MaterialKind: wikidata_qid, inchikey, pubchem_cid, mp_id, cas_rn) shipped
via #330. R2-R6 and the verdict table below remain the open roadmap; note
the license traps flagged under Risks (CAS BY-NC, AFLOW non-commercial,
Battery Archive unlicensed) before building any importer.

Companion to MATERIALS-MODEL-PROPOSAL-2026-08-03.md. Web-verified August
2026 (live docs/APIs fetched; blocked fetches flagged). Full per-initiative
table, risks, and phasing below are condensed from the research run; the
complete cited report lives in the session transcript.

## Top recommendations

R1 (NOW, vocabulary-curation PR): multi-anchor identity fields on
MaterialKind, all nullable, JSON-LD mapping via skos:exactMatch (never
owl:sameAs): wikidata_qid (broadest; CC0; only anchor resolving NMC
variants: NMC811 Q121086674, NMC622 Q121086348, NMC532 Q121086662; LiPF6
Q2583808, EC Q421145, LFP Q3042400, graphite Q5309), inchikey (molecular
species only; never fabricate for solids/polymers), pubchem_cid (LiPF6
23688915, EC 7303, LFP 15320824, graphite idealized 5462310; PVDF none),
mp_id (crystalline only: graphite mp-48, Si mp-149, Li mp-135, LFP
mp-19017, LCO mp-22526, LMO mp-22584, LiPF6 mp-9143; NO mp-id for
NMC811 — label "representative ordered structure"), cas_rn (from open
secondaries ONLY — CAS Common Chemistry is CC BY-NC 4.0, no bulk
derivation), emmo_iri (primary anchor).

R2 (Phase B): Materials Project computed-reference layer — the
insertion_electrodes API serves computed voltage profiles
(InsertionElectrodeDoc: stepwise voltage pairs, average_voltage,
capacities, volume change; battery_id like mp-19017_Li) directly
overlayable with measured OCP curves on kind pages as a third "computed"
distribution layer. Batch importer per linked mp_id with provenance
{mp-id, db version, CC-BY attribution}. CONFIRM MP CC-BY terms manually
first (terms pages Cloudflare-blocked to agents).

R3 (NOW, conversation not code): propose BattINFO records as BDF's
metadata layer — the Battery Data Alliance roadmap names "a parallel
format for storing metadata" as the immediate next step and their ontology
repo already extends BattINFO. Issue/PR before they invent a parallel
model. Highest strategic leverage in the report.

R4 (time to Longlist Q3-2026 revision): Battery Pass attribute mapping
table (BattINFO fields <-> BatteryPass-Ready Data Attribute Longlist v1.3
+ Catena-X io.catenax.battery.battery_pass v3.0.1 TTL). Docs artifact
only; do not build passport tooling.

R5 (manuscript): the US "Battery Data Genome" is a dormant paper-brand
(2021 Joule vision paper, arXiv:2109.07278; no program/site since; DOE
built batterydata.energy.gov + ORNL ROVI instead). Add one sentence
positioning Battery Genome as an operational realization of that vision,
citing Joule — pre-empt reviewer confusion; adjacency is an asset.

R6 (later, cheap): Wikidata write-back via P2888 exact-match statements
pointing at w3id.org kind IRIs; improve the thin NMC-variant items.

## Verdict table (condensed)

Recommend: Materials Project (id now, importer Phase B), Wikidata,
InChIKey (scoped), PubChem (scoped), EMMO chem-substance upstreaming
(missing: EC, DMC, NMC oxides, graphite, PVDF, LiFePO4, LiTFSI; add an
InChIKey annotation property), BDF metadata-layer proposal, Battery Pass
mapping (scoped), US-BDG citation, OPTIMADE one-off CONSUME script
(federation v1.3.0, 28 providers — enrich crystalline kinds), MatPortal
listing (BattINFO currently absent/404 there — half-day cheap win).
Consider: CAS RNs (open secondaries only), NOMAD nomad-battinfo plugin
pilot (computational-first, battery plugins exist but no cell/test
model), nomad-battery-database literature dataset as distribution seed
(check license), Battery Archive cross-link (NO redistribution — no
license; import from upstream originals Oxford/HNEI/ISU-ILCC), Faraday->
LEAP Imperial 40-cell NMC811 dataset importer, PMD/DigiBatMat + BatCAT
outreach, NFDI-MatWerk listing.
Skip: OPTIMADE SERVING (federation is 100% atomistic; formulated
materials would be null-geometry noise — reassess if a battery profile
emerges), Materials Cloud publishing (nothing over Zenodo), OQMD
(redundant), AFLOW (non-commercial license), MPDS (paid),
batterydesign.net, passport tooling. BatteryLifeLab/CIDEMO/GEMS do not
exist (speculative names from the brief).

## Risks

CAS BY-NC bulk-derivation trap; AFLOW non-commercial; Battery Archive
unlicensed (link, do not redistribute); MP license needs one manual
confirmation; null anchors must read as normal (no false precision for
disordered solids); BFO-based ontology world (PMDco/MWO) = relationship
plays only, no deep alignment; recurring commitments limited to BDF
participation + optional NOMAD pilot.

## Phasing

Now (vocab PR): R1 fields + curated values; manuscript sentence.
Near-term non-code: BDF proposal; MatPortal listing; chem-substance
upstreaming (rides with the user's current class-minting); MP terms check.
Phase B: MP importer; OPTIMADE consume script; evaluate NOMAD-battery +
LEAP NMC811 as distribution/OCV feeds.
Later: Battery Pass mapping; Wikidata P2888; NOMAD plugin; outreach.
