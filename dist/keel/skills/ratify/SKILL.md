---
name: ratify
description: Use the moment the user states a standing decision, preference, or constraint in chat, to record it as a ratified decision the same turn.
disable-model-invocation: true
---

# ratify — spoken this turn, on file this turn

A standing decision that lives only in chat is a decision the next session
does not have. The moment the user states one, it becomes a record — same
turn, no queue, no batching. Ratify writes down what was said; it never
decides.

## The five steps

1. **Write the record** to `.keel/decisions/YYYY-MM-DD-<slug>.md`. The
   frontmatter is enforced, not suggested: `name`, `description` (the
   decision as one claim), `type: decision`, `status: ratified`,
   `generated: { by: "machine:<role>", at: "<absolute date>" }`, a `verified`
   list naming the human ratifier and the date, and `cites`. The body carries
   the decision, its context, and its consequences. Skeleton:
   `references/keel-decision-record.md`.
2. **Know what the checker enforces** before it tells you: a decision never
   carries `stale_after` — a decision does not rot on a clock, it gets
   superseded; a ratified decision must name a verifier — `verified: []`
   under `status: ratified` is a contradiction the record makes about
   itself; every date is absolute.
3. **Gate discipline — the file is tracked.** Never write a rule identifier
   (a letter-plus-number token) that does not resolve to a heading in
   `docs/keel-rules.md`; never name ignored paths; never name outside tools.
   The gates check the claim, not the intent.
4. **Check and derive.** Run
   `python scripts/keel.py records --dir .keel/decisions`, fix findings —
   a finding is a defect in the record you just wrote — then
   `python scripts/keel.py index rebuild`. (Installed as a plugin, the
   script is `"$CLAUDE_PLUGIN_ROOT/scripts/keel.py"`.)
5. **Commit and push only after the staged gates pass:** `git add -A`, then
   `python scripts/keel_checks.py --names --refs`. The gates scan the
   tracked tree, so the record must be staged before the check means
   anything.

## What not to do

Never record a decision the user did not state — inference is not
ratification, and a plausible decision put in the user's mouth is a
fabrication with a schema. When a ratified decision contains an open
question, mark it open explicitly in the body; resolving it silently turns a
record into a decision nobody made.
