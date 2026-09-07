---
name: castoff
description: Use at the start of a session that resumes prior work — reads the newest mooring record, surveys the session's state, and reports the open threads and a recommended track. Writes nothing.
disable-model-invocation: true
---

# castoff — take in the lines and get under way

Casting off is orientation, not action: the session starts by reading what
the last one moored, reading what this one's state actually permits, and
reporting the difference. Nothing here writes — the session plan still goes
through the normal gate, exactly as it would without this skill.

## The four steps

1. **Find the newest mooring record.** Mooring records live in
   `.keel/knowledge/`: type `state`, name starting `mooring-`. Newest means
   the latest date in the name, and a suffixed record (`mooring-<date>-2`,
   then `-3`) counts as later than the unsuffixed record of the same date.
   If no mooring record exists, say so and stop — there is nothing to resume
   from, and inventing a prior state is worse than starting fresh.
2. **Read this session's own orientation facts.** SessionStart already put
   five lines in this session's context, each tagged `[keel] castoff:` —
   the arming state, the policy-lock state (which also names the workshop
   declaration in force), the conflict scan, the three kill switches
   (`KEEL_OVERRIDE`, `KEEL_GATE`, `KEEL_PLAN_TTL_MIN`) as this session's own
   environment actually holds them, and any standing hold. Read those instead of
   running a command: at tier 2 the plan gate denies ALL Bash until this
   session's own ledger exists, so `python scripts/keel.py survey` cannot
   run here — casting off is orientation BEFORE a plan exists. If the
   conflicts line reports a count, that count is real; if it says the scan
   could not run, treat that as unresolved, never as zero. An "ARMED" tier
   on the arming line is NOT the same fact as live gates: `KEEL_GATE=off`
   disarms plan-before-write and stop-with-accounting without changing the
   arming line, so read the switches line before concluding this session's
   guardrails are actually enforcing anything.
3. **Report three things, plus the backlog.** (Step 4 adds a fourth
   surface; these three are what the mooring record and this session's own
   orientation answer between them.) First, the record's open
   threads, citing the record's path rather than restating what it already
   says. Second, which of those threads are actionable in THIS session's
   state — a thread that needs `KEEL_OVERRIDE` is actionable only while this
   session's own orientation reports the lock SUSPENDED, and a thread blocked
   on the lock stays blocked while that orientation reports the lock in force.
   Those are one question asked of one fact: the POLICY LOCK SUSPENDED line and
   the policy-lock line's `SUSPENDED by KEEL_OVERRIDE` state come from the same
   predicate over the same environment, so they cannot disagree. Read that
   line's STATE, not its parenthetical — under an override it reads
   `SUSPENDED by KEEL_OVERRIDE (declared: in force)`, where the parenthetical,
   like the `tighten:`, `relax:` and `workshop:` values beside it, describes the
   declaration the arming file still makes and that comes back the moment the
   switch is cleared. The lock is in force only when nothing precedes those
   words. Third, ONE recommended track, chosen from the
   actionable threads. Alongside these, read `.keel/backlog.md` if it exists
   and report its open (`[ ]`) entries as candidate threads — work filed by
   an earlier session and never silently dropped — citing the entry's own
   id rather than restating it. Then state plainly that nothing was written
   and the session plan still goes through the normal gate.
4. **Report any UNTERMINATED LEDGER that is not this session's.** A mooring
   record is written by a session that finished deliberately; a session that
   crashed, was killed, or simply stopped wrote no mooring record at all — but
   plan-before-write guarantees it left a ledger, because a gate refused its
   first write otherwise. So its work IS on disk, readable and structured, and
   until this step nothing pointed the next session at it: the successor cast
   off from an older mooring and could never learn the dead session ran.
   List `.keel/plans/keel-plan-*.md`, skip the one named for THIS session, and
   report any whose items are not all terminal — naming the file, the count of
   unfinished items, and their ids. Terminal is `[x]` done, `[!]` blocked,
   `[?]` needs a decision. Two markers count as unfinished here: `[ ]`, which
   is plainly open, and `[~]`, which claims a delegation is still running —
   true only of a live session, so in a ledger that is not this one's it means
   a hand-off that cannot still be in flight. Read the ledger's own prose for
   what the item was; do not guess from its id.
   A ledger named under a `## Closed ledgers` heading in ANY mooring record
   (`.keel/knowledge/mooring-*.md`) — together with the record or backlog
   entry that accounts for every one of its unfinished items — is reported in
   one line as closed by that mooring, not as unterminated. A `## Closed
   ledgers` line that names a ledger but points at no accounting record does
   not count: report that ledger unterminated, exactly as if no mooring had
   named it at all.
   Do this with the file-reading tools, NOT with a command: at tier 2 the plan
   gate denies ALL Bash until this session's own ledger exists, and casting off
   happens before that. `scripts/keel_plans.py` reports the same item states
   and is the right instrument LATER, once a plan is in place.
   Report the absence too — "no unterminated ledger from another session" is a
   fact the next session wants, and silence reads as "not checked".

## What not to do

Do not write anything — no record, no ledger entry, no plan; casting off
reports, it never commits the session to a course. Do not edit the mooring
record you booted from — a record belongs to the session that wrote it
(`skills/moor/SKILL.md` owns that rule). Do not recommend a track this
session's orientation facts show it cannot act on. Do not run
`python scripts/keel.py survey` to re-derive what step 2 already read from
context — the plan gate will not be open yet, and the command will only
deny. Do not improvise a boot procedure when no mooring record exists —
report the absence and let the user set the track. Do not ADOPT another
session's unterminated ledger as this session's plan, and do not edit it: it
belongs to the session that wrote it, the plan gate wants a ledger under THIS
session's id, and a resumed session inheriting a predecessor's file is the
confusion `.keel/knowledge/a-compacted-session-splits-its-record-into-two-ids.md`
records. Step 4 reports that a ledger exists and what is unfinished in it;
whether to pick that work up is the user's call, made on a new ledger.
