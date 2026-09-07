# Decision record crib

The schema authority is `scripts/keel_records.py`; the check is
`python scripts/keel.py records --dir .keel/decisions`. The general field
table is `skills/log/references/keel-record-schema.md`, which ships with the
knowledge feature — where that feature is not installed, the checker above is
still the authority and the field table is simply not on disk. This page is
the shape of a ratified decision specifically.

## Skeleton

```markdown
---
name: editions-are-generated
description: Editions are generated artifacts from one source tree, never maintained forks.
type: decision
status: ratified
generated: { by: "machine:orchestrator", at: "2026-08-02" }
verified:
  - { by: "human: owner, in chat", at: "2026-08-02" }
cites: []
---

# The decision, as a heading a person can act on

**What is decided.** The claim, in the user's terms, with enough context
that a cold reader knows what it binds.

**Why.** The context that made the user state it — cited by path where a
file holds it, never restated.

**Consequences.** What this permits, forbids, or changes from here on.

**Open.** Anything the user left undecided, named as open. Absent section
means nothing is open.
```

## The rules that bite

- `status: ratified` with `verified: []` fails the check: ratification is an
  authority claim, and the record must name whose authority.
- `stale_after` on a `type: decision` fails the check: a decision is
  superseded by another decision, not expired by a date.
- Both dates are absolute `YYYY-MM-DD`. A relative date means something
  different every time it is read.
- `name` matches the filename slug's subject; the file adds the date prefix,
  the record's `name` is what retrieval resolves.
