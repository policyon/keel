# Mooring record crib

One record per mooring, type `state`, into `.keel/knowledge/`. The schema
authority is `scripts/keel_records.py` and the check is
`python scripts/keel.py records --dir .keel/knowledge`; the full field table
lives in `skills/log/references/keel-record-schema.md`, which ships with the
knowledge feature — where that feature is not installed, the checker above is
still the authority and the field table is simply not on disk. This page is
only the shape of this one record.

## Skeleton

```markdown
---
name: mooring-2026-08-02  # or mooring-2026-08-02-2 — see the suffix rule below
description: Session moored with the review layer shipped and two threads open.
type: state
generated: { by: "machine:orchestrator", at: "2026-08-02" }
verified: []
cites: []
---

## Outcome

What reached a terminal state this session, as claims with paths — the
ledger is `.keel/plans/keel-plan-<sess8>.md`; cite it, do not replay it.

## Open threads

Each `[!]` and `[?]` item, one line each: what it is and why it stopped.

## Closed ledgers

One line per dead ledger this record closes, in the form
`- keel-plan-<id8>.md — <n> unfinished item(s), accounted for in <path or BLn>`.
Omit the heading entirely when this record closes none.

## Next intended step

One step, concrete enough that a cold session could take it.
```

## The rules that bite

- One date, maybe many sessions: the session that wrote today's record
  refreshes it in place; any other session takes the next free suffix
  (`mooring-<date>-2`, `-3`, counting up from what exists in
  `.keel/knowledge/`) and never edits a record it did not write.
- `name` matches the filename stem, suffix included — retrieval resolves by
  it.
- The date in `generated.at` is absolute; "today" means a different day every
  time the record is read.
- `verified: []` is correct here: a mooring is a machine's account, and
  claiming a human checked it would be false.
- Cite, never restate. A mooring that copies file contents goes stale the
  first time the file changes; a path does not.
