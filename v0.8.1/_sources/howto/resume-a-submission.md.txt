# Resume an interrupted bulk submission

`ws.submit()` journals every outcome to `.battinfo/submit-journal.jsonl` as it
happens. If a 10k-record submission dies at record 7,000, just run it again:

<!-- doc-snippet: skip -->
```python
ws.submit()               # re-run after the interruption
# already-submitted records print:
#   <title>  [already submitted — skipped; pass resume=False to re-send]
```

- **Succeeded records are skipped** locally (`status: skipped_journal`) — no
  re-POST round-trips.
- **Failed records retry** automatically on the next run.
- **Changed content re-submits** — the journal keys on a content hash, so an
  edited record never hides behind an old success.
- **Each registry has its own record of successes.** The journal notes the registry every record went to, and a success counts only there. A workspace rehearsed against a local registry therefore still sends everything when you submit to production. Journals written by earlier versions name no registry, so their records are sent once more; the registry deduplicates identical payloads.
- `ws.submit(resume=False)` bypasses the journal entirely; the registry
  dedups identical re-submissions server-side anyway.

Transient registry failures (429/5xx, timeouts) are retried with exponential
backoff within each submission — resuming is for interruptions on your side.
