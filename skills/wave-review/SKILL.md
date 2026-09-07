---
name: wave-review
description: Use when a dispatched wave of work completes, or the owner starts reviewing it, to batch every open question, finding, and applied default into one continuously numbered walkthrough the owner can answer in a single message.
disable-model-invocation: true
---

# wave-review — one numbered walkthrough per wave

A finding raised in one message, a question raised in the next, and a
default applied silently in a third leaves the owner reconstructing the
wave from scraps. Wave-review batches everything the wave produced that
needs a ruling into ONE list, numbered once, so the owner answers "1 yes,
2 no, 3 park it" and every accepted answer lands in one pass.

## The five steps

1. **Gather every open item for the wave.** Read every executor and
   reviewer report the wave produced — findings, open questions, defaults
   applied under ambiguity, anything a reviewer flagged. Nothing is dropped
   for being minor, and nothing is presented ahead of the rest as it
   arrives; the walkthrough waits for the wave to actually finish.
2. **Present ONE continuously numbered list.** Each item states what and
   where — file:line, or the record path — the question or the default
   that was applied, and a recommendation. Numbering runs across the whole
   wave, never restarting per report, so "1 yes, 2 no, 3 park it" answers
   the batch in one message.
3. **Wait for the batch reply.** An item not yet answered is not decided —
   silence is not agreement, and a recommendation stated is not a
   recommendation ratified.
4. **Apply every accepted item in one pass.** Batch the edits the answers
   authorize; do not apply them one at a time as replies trickle in, and do
   not act on an item the owner has not yet reached.
5. **Route what the answers produced.** A standing decision the owner
   ratified in the reply is written the same turn to
   `.keel/decisions/YYYY-MM-DD-<slug>.md` — the frontmatter carries `name`,
   `description`, `type: decision`, `status: ratified`,
   `generated: { by: "machine:<role>", at: "<absolute date>" }`, a
   `verified` list naming the owner and the date, and `cites` — then
   `python scripts/keel.py records --dir .keel/decisions` runs before the
   record is treated as settled. An item the owner parks is written on the
   session's own ledger as a `[?]` entry with the reason it was deferred —
   never left standing only in the reply that parked it.

## What not to do

Do not drip-feed items across separate messages — a finding surfaced
outside the walkthrough is exactly the drip-feed this skill exists to
close. Do not hand the decision-recording step to another user-invoked
skill — write the record directly, in the same shape, because a
user-invoked skill never calls another one. Do not treat an unanswered
item as approved, and do not fold two independent questions into one
numbered line — the owner answers one thing per number.
