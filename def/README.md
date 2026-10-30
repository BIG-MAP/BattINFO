# Publisher vocabularies

This folder holds the vocabularies that publishers define under `https://w3id.org/battinfo/def/{prefix}`, where `{prefix}` is the publisher's number in the [prefix register](../src/battinfo/data/namespace/prefixes.json). A vocabulary is an OWL ontology written in Turtle, and each of its releases is one file.

## Adding a vocabulary or a release

Open a pull request that adds `def/{prefix}/{X.Y.Z}/vocab.ttl` for a prefix you hold. A first release starts the vocabulary; each later release goes in a folder of its own beside the earlier ones. Before you push, check the files against the rules below:

```bash
uv run python scripts/check_def_vocabularies.py
```

CI runs the same checks on the pull request, and also fails it when it changes a release that is already merged.

A prefix whose holder has no terms to release yet gets an empty release 0.1.0, so its address answers from the start; the first terms then go in a release of their own, such as 1.0.0.

A release goes live on the next deploy of the documentation from `main`, a few minutes after the merge. Vocabulary releases are not tied to BattINFO releases.

## Rules

- The file declares one `owl:Ontology`, `https://w3id.org/battinfo/def/{prefix}`, with no trailing slash. It gives `owl:versionIRI <https://w3id.org/battinfo/def/{prefix}/{X.Y.Z}>`, `owl:versionInfo "X.Y.Z"`, a `dcterms:title` and a `dcterms:license`.
- A version is `X.Y.Z`, or a pre-release such as `1.3.0-beta.1`, which comes before `1.3.0`.
- A merged release never changes. Fix a mistake in a new release.
- A release may name an earlier release of the same vocabulary with `owl:priorVersion`, usually the one before it.
- A term is `https://w3id.org/battinfo/def/{prefix}/{term}`. Its name starts with a letter and holds only letters, digits and underscores. A term has no version, is never removed and never takes another meaning.
- When a meaning changes, add a new term and mark the old one `owl:deprecated true`, with `dcterms:isReplacedBy` naming the new term if there is one, defined in the same release. The old term stays, deprecated, in every later release.
- Every IRI that a release describes under `def/{prefix}/` is in each later release, so a backport (such as 1.2.1 after 1.3.0) adds only terms that the later releases already have.
- Each class, property, individual, concept and concept scheme has an English label (`rdfs:label` or `skos:prefLabel` with `@en`) and a definition (`skos:definition` or `rdfs:comment`). A concept scheme may use `dcterms:title` and `dcterms:description` instead.
- A vocabulary defines terms only under its own `https://w3id.org/battinfo/def/{prefix}/`.

## Licence

Each vocabulary states its own licence with at least one `dcterms:license` that is an IRI, such as `<https://creativecommons.org/licenses/by/4.0/>`. That licence applies to the vocabulary instead of the Apache-2.0 licence of this repository.

## Maintainers

A change to a publisher's folder is approved in the pull request by one of the publisher's maintainers before a BattINFO maintainer merges it.

## The release page

Each release gets a page, built from its file, so a vocabulary documents itself by what it states. The page is in the BattINFO style ([brand/](../brand/BRAND.md)), light or dark as the reader has set the docs site or their system, and stands alone, with no files from the rest of the site. Next to the title, version and licence, the page shows the ontology's `dcterms:description`, its `dcterms:publisher` (a `foaf:name` and a `foaf:homepage`) and its `dcterms:issued` date, and links to the publisher's own documentation of the vocabulary when the ontology names it with `rdfs:seeAlso` or `foaf:page`. Each concept scheme is outlined with its top concepts and their narrower concepts. Each term shows its label and definition, and also its `skos:scopeNote`, its English `skos:altLabel` values, its broader and narrower terms and its SKOS matches, with a matched EMMO term shown by its name.

## Where it is served

The pages and files are published on GitHub Pages under `https://big-map.github.io/BattINFO/def/`, and w3id redirects to them:

| IRI | Serves |
|---|---|
| `https://w3id.org/battinfo/def/{prefix}` | the newest release: its `vocab.ttl`, or a page for a browser |
| `https://w3id.org/battinfo/def/{prefix}/{X.Y.Z}` | that release |
| `https://w3id.org/battinfo/def/{prefix}/{term}` | the newest release, open at the term for a browser |

The newest release is the highest final version. A pre-release is served there only while the vocabulary has no final release; after that, a term added in a pre-release resolves once a final release includes it.
