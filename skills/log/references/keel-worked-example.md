# Worked example: three queue lines, one record

## What the queue held

```json
{"v": 1, "ts": "2026-08-01T14:02:11Z", "session": "9f31...", "tool": "Bash", "action": "ran python scripts/keel.py index rebuild", "paths": []}
{"v": 1, "ts": "2026-08-01T14:02:40Z", "session": "9f31...", "tool": "Write", "action": "changed scripts/keel_index.py", "paths": ["scripts/keel_index.py"]}
{"v": 1, "ts": "2026-08-01T14:06:02Z", "session": "9f31...", "tool": "Task", "action": "handoff to executor: probe FTS5 before choosing a backend", "paths": []}
```

## The reading

Three lines, one fact. The two edits are routine — the files are on disk and
`git` remembers them better than a record could. What a future session cannot
recover is *why* the backend is chosen at open rather than configured: that
came out of the hand-off, and nothing on disk states it.

So: one record, not three. The queue is evidence, not an outline.

## The record

```markdown
---
name: keel-fts5-is-probed-not-configured
description: The index probes for FTS5 at open and falls back to LIKE, because availability is a property of the interpreter.
type: knowledge
status: ratified
generated: { by: "machine:executor-deep", at: "2026-08-01" }
verified: []
cites: []
---

FTS5 is a compile-time option of SQLite, so whether it exists is a property of
the Python the adopter happens to have, not of keel or of any setting. The
index therefore creates and drops a scratch FTS5 table at open and believes
the answer; when it fails, search runs over a plain table with `LIKE` plus a
word-start check, answering the same contract more slowly.

Configuring this instead would be a setting that is wrong on some machines and
silently right on ours.

Related: `keel-index-is-derived`.
```

## Then

```
python scripts/keel.py records --dir .keel/knowledge
python scripts/keel.py index rebuild
```

Write `2026-08-01T14:06:02Z` — the `ts` of the last line read — into
`.keel/queue/keel-log-watermark.txt`, and report: 3 observations read, 1
record written, N records indexed.

## Two failure shapes to recognise

- **A record per queue line.** Produces a corpus that is a diff log with
  frontmatter, and retrieval that returns twelve near-identical hits.
- **A record that says "we improved the index".** Unfalsifiable and
  unsearchable. State the claim and the reason, or write nothing.
