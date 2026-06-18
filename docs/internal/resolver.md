# Resolver Deployment

Deployment infrastructure has been split out of this repository.

The main BattINFO repository can still generate local resolver artifacts for review,
but the deployed resolver, static hosting layout, and `w3id.org` rules belong in
the dedicated `battinfo-registry` repository.

## Artifact Build

Generate local resolver artifacts from canonical examples:

```powershell
python .tools/build/build_resolver_artifacts.py
```

Output root:

```text
.battinfo/resolver-site/
```

Generated structure:

- `.battinfo/resolver-site/cell/{uid}/index.html`
- `.battinfo/resolver-site/cell/{uid}/index.json`
- `.battinfo/resolver-site/cell/{uid}/index.jsonld`
- `.battinfo/resolver-site/cell-type/{uid}/index.html`
- `.battinfo/resolver-site/cell-type/{uid}/index.json`
- `.battinfo/resolver-site/cell-type/{uid}/index.jsonld`
- `.battinfo/resolver-site/dataset/{uid}/index.html`
- `.battinfo/resolver-site/dataset/{uid}/index.json`
- `.battinfo/resolver-site/dataset/{uid}/index.jsonld`

## Deployment Ownership

Items that no longer belong in this repository:

- deployed resolver site contents
- `w3id.org` redirect templates/rules
- static-hosting-specific deployment configuration

Those should live in `battinfo-registry`.

## Deployment Notes

- Publish reviewed local artifacts from `.battinfo/resolver-site/` into `battinfo-registry` as needed.
- Keep canonical UID format dashed-lowercase (`xxxx-xxxx-xxxx-xxxx`).
- Ensure deployed paths match generated folder layout exactly.

