---
name: keel-observations-are-summaries
description: The observation queue carries one summary line per state change, never a payload body.
type: knowledge
status: ratified
generated: { by: "machine:executor-deep", at: "2026-08-01" }
verified: []
cites: []
---

Capture appends one line to `.keel/queue/keel-observations.jsonl` for each
completed state change and each returned hand-off. The line names the session,
the tool, one action summary and the redacted paths touched. File contents,
command output and delegation prompts are deliberately absent: distillation
reads the files themselves, which are on disk already.

Related: `keel-index-is-derived`.
