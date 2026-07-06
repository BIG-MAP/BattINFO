# Tag your work with a grant and your ORCID

Set both once per workspace; every record you save carries them from then on —
so your data stays traceable to the project that funded it and the person who
made it.

<!-- doc-snippet: skip -->
```python
ws.project("101103997")      # EU grant number — resolved via OpenAIRE
ws.contributor("0000-0002-1825-0097")   # your ORCID
ws.save()                    # records now carry funding + contributor
```

- The grant is stamped into each record's `funding` block and lifted to the
  submission envelope, so the registry can answer "everything from grant X".
- The contributor ORCID flows to the registry's contribution tracker and your
  profile on Battery Genome.
- Both live in `.battinfo/workspace.json`; edit or clear them there.
