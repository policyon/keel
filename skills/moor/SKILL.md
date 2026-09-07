---
name: moor
description: "Use at the end of significant work to consolidate the session: ledger terminal, delegations attested, observations distilled, one mooring record written."
disable-model-invocation: true
---

# moor — bring the vessel in before you leave it

Mooring is consolidation, not narration: the session ends with its ledger
closed, its delegations reconciled, its queue distilled, and one record that
tells the next session where things stand. Nothing here invents state — every
step reads what is on disk and makes it terminal or says why it is not.

## The six steps

1. **Close the ledger.** This session's ledger is
   `.keel/plans/keel-plan-<sess8>.md` (the 8-char session id). Drive every
   item to a terminal status: `[x]` done, `[!]` blocked with the reason on
   the same line, `[?]` genuinely unresolved. Never fabricate completion — an
   item you cannot point to evidence for is `[?]`, not `[x]`. Real work found
   but deliberately not started this session is neither of those: file it to
   `.keel/backlog.md` — add its entry there, then close the ledger line
   `[x]` with a `FILED: BL<n>` note naming that entry. The stop gate verifies
   the note against the backlog file itself, so an entry that is not really
   there still blocks the stop.
2. **Attest the delegations.** Run
   `python scripts/keel.py attest --project .` and reconcile what it reports
   against the ledger honestly: a discrepancy is stated and resolved in the
   ledger, never papered over.
3. **Distill the queue.** If `.keel/queue/keel-observations.jsonl` holds
   lines newer than the watermark, run the log skill's five steps — they are
   in `skills/log/SKILL.md`, and they are not restated here. An empty queue
   skips this step and you say so. That page ships with the knowledge
   feature: where it is not installed, distillation is skipped and your
   report says which feature the step needed.
4. **List and close dead ledgers.** Before the record is written, list
   `.keel/plans/keel-plan-*.md` not named for THIS session and check each one:
   terminal is `[x]` done, `[!]` blocked, `[?]` needs a decision — `[ ]` and
   `[~]` are not, the same distinction castoff's step 4 draws. For every
   ledger whose items are not all terminal, either name it in the record you
   are about to write, under a `## Closed ledgers` heading, together with the
   record or backlog entry that accounts for every one of its unfinished
   items, or leave it unnamed so the next castoff keeps reporting it. Naming a
   ledger without an accounting record is not closure — castoff treats that
   the same as not naming it at all. Read these files directly rather than
   shelling out to `scripts/keel_plans.py`: the same reason castoff's step 4
   gives for using file-reading tools, not a command, applies here too.
5. **Write ONE mooring record** into `.keel/knowledge/`: type `state`, name
   `mooring-<date>`, filename to match. If this session already wrote today's
   record, refresh it in place — a re-moor updates, it does not duplicate. If
   another session wrote it, take the next free suffix in `.keel/knowledge/`
   (`mooring-<date>-2`, then `-3`) — you never edit a mooring record you did
   not write. It summarizes the outcome, the open
   threads, and the next intended step — citing paths, never restating what
   the files already say. If step 1 filed anything, name the backlog's open
   count so the next session sees it without re-reading `.keel/backlog.md`
   itself. Skeleton: `references/keel-mooring-record.md`.
6. **Check and derive.** Run
   `python scripts/keel.py records --dir .keel/knowledge`, fix any finding in
   the record you just wrote, then `python scripts/keel.py index rebuild`.
   (Installed as a plugin, the script is
   `"$CLAUDE_PLUGIN_ROOT/scripts/keel.py"`.)

## What not to do

Do not write a session summary for the user inside records — the mooring
record addresses the next session, not this one. Do not mark unfinished work
done: an honest `[?]` costs a line, a false `[x]` costs the next session a
rediscovery. Do not edit records you did not just write.
