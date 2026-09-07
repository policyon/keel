---
name: chart
description: Use when you need what this project already knows - searches the knowledge records by keyword and returns full records only for the identifiers you choose.
---

# chart — navigate the knowledge, cheaply

Two layers, in order. Never read the records in bulk: that spends the
session's context on deciding what to read.

## Layer 1 — find the identifiers

```
python scripts/keel.py chart <terms>
```

One line per hit: `id date type title`, newest first, never wider than 120
characters. Terms are ANDed and match at the start of a word,
case-insensitively — `index` finds `keel-index-rebuild`, `dex` finds nothing.
`no matches` is a normal answer, and the command still exits 0.

Query syntax, narrowing, and what to do when a search returns too much or too
little: `references/keel-query-syntax.md`.

## Layer 2 — read only what you chose

```
python scripts/keel.py chart --get <id> [<id>...]
```

Prints the full text of each named record. Ask for it only after layer 1 has
told you which identifiers are worth it — one, two, rarely more.

(Installed as a plugin, the script is `"$CLAUDE_PLUGIN_ROOT/scripts/keel.py"`.)

## The rules

- **Filter, then fetch.** If you are about to `--get` more than three
  identifiers, your query was too broad — narrow it and search again.
- **Never read `.keel/knowledge/` with a glob.** That is the bulk load this
  skill exists to avoid, and it defeats the injection budget the session
  starts under.
- **The index is a cache.** If it is missing it is derived automatically; if
  results look stale, `python scripts/keel.py index rebuild` and search again.
  The record files are the truth, always.
- **Report what you used.** When knowledge changes your answer, name the
  identifiers you read, so the user can open them.
- A record found here may be wrong or out of date. It is evidence, not
  authority: check it against the tree before acting on it.
