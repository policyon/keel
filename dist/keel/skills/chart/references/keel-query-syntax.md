# Query syntax and narrowing

## What a query is

A query is a list of terms. Terms are split on everything that is not an
ASCII letter or digit, so `keel_index`, `keel-index` and `keel index` are the
same two-term query.

- **Every term must match** (AND). Adding a term always narrows.
- **A term matches at the start of a word**, case-insensitively. `inject`
  finds `injection` and `INJECTED`; `jection` finds neither.
- **Punctuation is not searchable.** A query of punctuation alone is no
  matches, never everything.
- **What is searched:** the record's identifier, type, description and body.

The same rules hold whether the index is running on FTS5 or on the `LIKE`
fallback — that equivalence is what `tests/contracts/keel_search_contract.py`
exists to prove, so a search never has to ask which backend answered.

## Options

| Flag | Effect |
|---|---|
| `--limit N` | How many hits to print (default 20). Hits are ordered newest first, so a limit truncates the tail, never the middle. |
| `--get <id>...` | Layer 2: print the full record for each identifier. |
| `--project DIR` | Search another project's records. Defaults to the current one. |

## When a search returns too much

- Add a term. Two terms are usually enough; three is a precise query.
- Prefer a term from the *fact* over a term from the domain: `probe` beats
  `index`, `watermark` beats `queue`.
- Search the type when you know it: `decision`, `knowledge`.

## When a search returns nothing

- Try the shorter root: `inject` rather than `injection`.
- Try the identifier convention: records are named `keel-<subject>-<claim>`,
  so `keel` plus one subject word often lands.
- Then accept the answer. `no matches` means this project has not written that
  down, which is worth saying out loud — and is exactly when `/keel:log` is
  the next move.

## Reading the line

```
keel-fts5-is-probed 2026-08-01 knowledge FTS5 availability is a property of the interpreter.
```

`id date type title`: the identifier is what `--get` takes, the date is when
the record was generated, the type tells you what kind of claim it is, and the
title is the record's own one-sentence description.
