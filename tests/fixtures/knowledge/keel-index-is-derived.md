---
name: keel-index-is-derived
description: The search index is derived from the record files and may be deleted at any time.
type: knowledge
status: ratified
generated: { by: "machine:executor-deep", at: "2026-08-01" }
verified: []
cites: []
---

`keel index rebuild` reads every record under `.keel/knowledge/` and
`.keel/decisions/` and writes `.keel/cache/keel-index.db`. Nothing else writes
that file, and nothing reads it that cannot fall back to the records
themselves, so deleting the whole cache directory costs one rebuild and no
information.

Related: `keel-observations-are-summaries`.
