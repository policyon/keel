# Record schema crib

The authority is `scripts/keel_records.py`; this page is the short form of
what it enforces. Every field below is checked, and
`python scripts/keel.py records --dir .keel/knowledge` is the check.

## Frontmatter fields

| Field | Required | Shape | Notes |
|---|---|---|---|
| `name` | yes | non-empty string | The identifier. Match the filename stem: retrieval resolves `--get <name>` straight to the file. |
| `description` | yes | one sentence | What retrieval routes on and what the index line shows. Write it as a claim, not a title. |
| `type` | yes | one of the vocabulary | `knowledge` for a distilled fact; `decision`, `assessment`, `state`, `priorities`, `glossary`, `log`, `plan` exist for records written by other flows. |
| `status` | no | `draft`, `ratified`, `superseded`, `deprecated`, `parked` | Absent means `draft`, which is legal but not stable. |
| `generated` | yes | `{ by: "machine:<agent>", at: "YYYY-MM-DD" }` | `by:` carries a `human:` or `machine:` prefix. The date is absolute — never "today". |
| `verified` | yes (key) | list | `verified: []` is the correct value for an unverified record and is not a finding. An empty list means "nobody has checked this", which is a fact worth recording. |
| `cites` | no | list of `{ source, version, at }` | Pin an external source you read, with the version as published. An invented pin is worse than no pin. |
| `stale_after` | no | `YYYY-MM-DD` | A rot detector. Required for `type: assessment`; forbidden for `type: decision`. |

## The rules behind the shapes

- A `type: decision` with `status: ratified` must name a verifier — claiming
  ratification with `verified: []` is a contradiction the record makes about
  itself.
- A date is always absolute. A relative date in a record is a date that means
  something different every time it is read.
- The body is markdown, and it is where the reasoning goes. The frontmatter is
  what machines route on; the body is what a person reads.

## Skeleton

```markdown
---
name: keel-index-is-derived
description: The search index is derived from the record files and may be deleted at any time.
type: knowledge
status: ratified
generated: { by: "machine:executor", at: "2026-08-01" }
verified: []
cites: []
---

One fact, argued in a paragraph or two, citing paths rather than restating
them.

Related: `keel-observations-are-summaries`.
```

Two complete records in this exact shape ship as
`tests/fixtures/knowledge/keel-index-is-derived.md` and
`tests/fixtures/knowledge/keel-observations-are-summaries.md`; the suite
asserts they pass the checker, so they are a safe pattern to copy.
