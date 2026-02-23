# Resolver Deployment (First Draft)

This document describes the first-draft BattINFO resource resolution setup.

## Artifact Build

Generate resolver artifacts from canonical examples:

```powershell
python scripts/build_resolver_artifacts.py
```

Output root:

```text
registry/site/
```

Generated structure:

- `registry/site/cell/{uid}/index.html`
- `registry/site/cell/{uid}/index.json`
- `registry/site/cell/{uid}/index.jsonld`
- `registry/site/cell-type/{uid}/index.html`
- `registry/site/cell-type/{uid}/index.json`
- `registry/site/cell-type/{uid}/index.jsonld`
- `registry/site/dataset/{uid}/index.html`
- `registry/site/dataset/{uid}/index.json`
- `registry/site/dataset/{uid}/index.jsonld`

## w3id Template

Use `registry/w3id-template.htaccess` as the starting point for `w3id.org` rules.

The template implements:

- 303 redirects for non-information resources
- Content negotiation for JSON-LD (`application/ld+json`) vs HTML
- Patterns for:
  - `/battinfo/cell/{uid}`
  - `/battinfo/cell-type/{uid}`
  - `/battinfo/dataset/{uid}`

## Deployment Notes

- Replace placeholder host `https://your-org.github.io/battinfo-registry/site` with your actual deployed static site root.
- Keep canonical UID format dashed-lowercase (`xxxx-xxxx-xxxx-xxxx`).
- Ensure deployed paths match generated folder layout exactly.
