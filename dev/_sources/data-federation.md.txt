# Data federation

```{note}
This is the developer-reference summary. The full, illustrated explanation lives
on the website — **[battinfo.org/federation](https://battinfo.org/federation)** —
which is the canonical home for conceptual "why" material. This page gives
developers the gist and points back into the reference docs.
```

Battery knowledge is scattered across datasheets, cycler exports, lab notebooks,
supplier specifications, and regulator databases. **Data federation** makes those
independent sources interoperable *without* forcing them into one database.
BattINFO is the backbone that makes it possible; **Battery Genome** is that
backbone in practice.

The idea in one line: **don't move the data — agree on how to describe and
address it.** Each dataset stays with its owner; a thin shared layer lets the
pieces link and be queried together.

BattINFO supplies exactly that shared layer, and nothing more:

1. **Shared meaning** — every property and unit maps to an EMMO domain-battery
   IRI, so a term means the same thing in every source. See
   [Ontology / profile architecture](ontology-profile-architecture.md).
2. **Shared identifiers** — cells, specs, tests, and datasets receive persistent
   `https://w3id.org/battinfo/` IRIs, so a record in one repository can reference
   a record published by another and the link still resolves. The registry mints
   these and renders resolvable public artifacts.
3. **Shared serialization** — records publish as JSON-LD aligned to one context,
   so independently authored documents merge into a single RDF graph. See the
   [Semantic layer guide](guides/04-semantic-layer.ipynb).

Because the shared core is deliberately minimal, data owners keep full control of
storage, access, and formats. **Battery Genome** is a working instance: cell
specs, instances, test protocols, and datasets contributed from many sources,
each described with BattINFO, given a persistent IRI, published as Linked Data,
and linked by IRI into one queryable graph that no single organization owns.

→ **Read the full concept on [battinfo.org/federation](https://battinfo.org/federation).**

## See also

- [Ontology / profile architecture](ontology-profile-architecture.md) — the source-of-truth hierarchy behind the shared vocabulary
- [04 — Semantic layer](guides/04-semantic-layer.ipynb) — JSON-LD, RDF, and SPARQL in depth
- [Workspace authoring](workspace-authoring.md) — the end-to-end flow for publishing linked records

