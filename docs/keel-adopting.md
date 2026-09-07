# Adopting keel

This page answers one question: which tier do you start at, and why. It
does not repeat what keel is built of — README.md and docs/keel-capabilities.md
already list that — and it does not repeat docs/keel-trust.md's tier table
or its honest limits; it cites both instead. Every claim below names the
code or the record that holds it, the same rule docs/keel-trust.md holds
itself to.

## What keel does for you

An agent working in your repository can write files before you have agreed
what it is doing, report a task "done" with nothing you can check, forget
every fact it learned the moment the session ends or gets compacted, and —
if the harness lets it — edit the very file that is supposed to constrain
it. keel removes those specific failures, one gate at a time: it can
require a written plan before the first write of a session, hold that
session open until every item on the plan carries a real, terminal status,
lock the file that defines its own rules so the model cannot rewrite them,
and turn what a session learned into small dated files instead of a fading
context window. None of that changes what a model can think of. It changes
what a project can hold the model to, and how much of that survives past
the session that produced it.

## Try it first: the zero-token tour

Before arming anything, run:

```
python scripts/keel_demo.py --tour --serve
```

This plays a scripted, eight-beat tour into a fresh throwaway project
under a temp directory, about 40 seconds a round (`scripts/keel_demo.py`,
`TOUR_SECONDS`), and keeps replaying — each round a new session with its
own ledger, so the board's round selector fills up behind you — until you
stop it with Ctrl-C. `--seconds N` sets the round length and `--once`
plays a single pass. `--serve` also opens the orchestration board at
`http://127.0.0.1:8771` so you can watch it live, and leaves it serving
after you stop; without `--serve` the same beats print to the terminal.

What the eight beats show, in order: a session opens with the Captain alone
and the ledger empty; a write with no plan on file is refused by the PLAN
GATE; the plan lands and twelve tasks open on the ledger; three agents launch
at three different routing tiers at once, their hubs and satellite task
cards lighting up with model-and-effort pills; a POLICY LOCK refusal on the
demo project's own arming file — a second, different refusal class; a
reviewer fails one task, the retry escalates to the deep tier, and the
retry passes; a resumed session inherits the routing tier it sailed out
with; and a stop with one item still open is refused by STOP-WITH-
ACCOUNTING before the last item closes and the session ends clean
(`scripts/keel_demo.py`, the `TOUR` beat list).

Every session id, task name ("caulk the hull seams", "chart the shoal
water", and so on) and review verdict in the tour is invented for the
purpose of exercising the board — none of it names real work. It cannot
touch a real project's records: the script refuses outright to run against
its own repository root, and it refuses any target directory whose audit
log already holds one session that does not carry a `demo-` prefix — the
sign of a real project's own history (`scripts/keel_demo.py`,
`_refusal_reason`). A directory the demo has never touched, or one it has
only ever run against itself, is the only kind it will write into.

## The four tiers — a choice, not a ladder

Arming is one file, `.keel/keel-policy.md`, copied from
`templates/keel-policy.md`; its `tier:` line decides how far enforcement
reaches. The table is the same one docs/keel-trust.md carries under
"Graduated adoption" — this section exists to help you pick a row, not to
repeat it.

**Tier 0 — observe.** Fits a first look at a project you are not ready to
change anything about: pure curiosity, or a week where any friction at all
is the wrong trade. What it guarantees is the absence of ENFORCEMENT, not
the absence of a record, and the difference matters: no write is ever
refused and no stop is ever held open, but the hooks still write. Any
project with a `.keel/` directory has its session boundaries, its file and
command activity and its delegations recorded to
`.keel/audit/keel-audit.jsonl` and the observation queue — `keel_capture`
gates on adoption alone and reads no tier at all
(`hooks/keel_capture.py`, `project_is_adopted`). The plan-path and
orientation lines described below print here too. Choose tier 0 to declare
that nothing may block, not to stay unobserved.

**Tier 1 — log.** The default `/keel:lay` chooses when you express no
preference (`skills/lay/SKILL.md`, step 5). Fits a working repo where you
want a memory that outlives the session but are not ready to have a write
refused. It names capture, records, a derived search index reachable with
`/keel:chart`, and that knowledge injected — bounded in bytes — at the next
session's start (templates/keel-policy.md). Still zero blocking. Be clear
about what separates it from tier 0 today: no code path switches those
layers on at 1 and off at 0 — capture runs at both, and records and the
index are produced when someone runs `/keel:log` and `keel index`, at any
tier. So the honest difference is declared intent plus whether the habit is
actually practised, and the cost is exactly that discipline: the layer
exists, nothing forces you to use it. What changes in a session:
once there is something to show, a `[keel] knowledge index: N record(s)...`
block appears at start, capped at 4096 bytes by default with a named
overflow line the moment a project's records outgrow that
(`hooks/keel_session.py`) — and still, no write is refused.

**Tier 2 — gate.** Enforcement begins here, and it fits a working repo
where you are actually delegating substantive writes and want the plan and
the accounting to be real rather than aspirational. It buys plan-before-
write (no state-changing write, edit or shell command runs until this
session has a fresh ledger on file at
`.keel/plans/keel-plan-<sess8>.md`), stop-with-accounting (a turn cannot
end while a ledger item carries no terminal status), and the policy lock
(the model can no longer edit `.keel/keel-policy.md`, `hooks/`,
`.claude-plugin/`, or the settings files) — all three named together in
`hooks/keel_gate.py` and templates/keel-policy.md. What it costs is real
ceremony: every session opens by writing a plan before it can touch
anything else, and cannot end with loose ends. What visibly changes is
described in the walkthrough below — this is the tier that first produces
a refusal a session actually sees.

**Tier 3 — govern.** The full harness, and it fits a team, or a
regulated-or-high-stakes project, where a task marked done has to mean a
reviewer actually looked at it and that verdict sits on a record someone
can re-check later. Per templates/keel-policy.md's Routing section, it adds
a stated escalation ladder — a standard attempt, then review, then one
deep-tier retry carrying the review's findings, then a named blocker or a
question for the user, never a silent third attempt — reviewer verdicts
written to the audit log (`python scripts/keel.py review --task <id>
--verdict pass|fail ...`), and `keel attest` reconciling what a ledger
claims against what the log shows. What it costs: every task now waits on
a review verdict before it can honestly close, and a failed review is a
second, more expensive attempt rather than a quick fix. **One thing the
law now says plainly, and this page with it: the gate that blocks writes
and holds the stop open does not distinguish tier 2 from tier
3.** `hooks/keel_gate.py` defines one threshold, `ENFORCING_TIER = 2`,
and nothing in the tree branches on tier 3 specifically — the PLAN GATE,
POLICY LOCK and STOP-BLOCKED refusals at tier 3 are byte-for-byte the same
mechanism tier 2 already runs. What tier 3 actually adds is the review-and-
attest discipline the policy file's Routing section commits the project
to, which any project can choose to practice at any tier but which tier 3
names as the point of arming at all.

Read those four rows together and one thing follows that no single row
says: the code holds ONE threshold, not four steps. `ENFORCING_TIER = 2`
divides refusing from not-refusing, and nothing else in the tree branches
on a tier — so 0 and 1 behave alike, as do 2 and 3, and the rest of the
ladder is declared intent and practised discipline rather than enforced
difference. That is not a gap between the law and the code: the law was
amended to say so, ratified on 2026-08-26 and recorded in the policy's own
Amendment log as version 1.1.0
(`.keel/decisions/2026-08-26-the-ladder-is-one-threshold.md`). An adopter
choosing a tier deserves the mechanism, not the brochure.

Most adopters should not start at 3. Start at 1 for the memory, move to 2
once you are delegating writes you would actually want gated, and treat 3
as something you grow into once a review habit already exists in how the
project works — not a costume worn for the appearance of safety.

## A first session at tier 2

This is what changes, concretely, the first time a project arms at the
tier where enforcement begins.

**The boot lines.** At `SessionStart` in an adopted project, before you
have asked for anything, the session reads lines like these
(`hooks/keel_session.py`):

```
[keel] This project runs under .keel/keel-policy.md. YOUR session plan
file is .keel/plans/keel-plan-<sess8>.md - write your plan THERE, as
'- [ ]' tasks with acceptance criteria and routes; parallel sessions each
have their own. The gates enforce plan-before-write and stop-with-accounting
against that file.
[keel] castoff: arming - tier 2 (ARMED)
[keel] castoff: policy lock - defaults (no '## Policy lock' section); workshop: (none)
[keel] castoff: conflicts - 0 found
[keel] castoff: switches - KEEL_OVERRIDE=(unset) KEEL_GATE=(unset) KEEL_PLAN_TTL_MIN=(unset)
[keel] castoff: holds - none active (explicitly declared)
[keel] live view - http://127.0.0.1:8770 shows this session's delegations
live (fixed port, never derived; the server walks to the next port when
8770 is busy, so trust the URL it prints). Not running? Start it with:
python scripts/keel_orchestration_dashboard.py --dir .
```

**The first refusal.** Any write attempted before that plan file exists is
refused, not silently skipped:

```
PLAN GATE (Edit): no fresh plan for THIS session. Write your plan to
.keel/plans/keel-plan-<sess8>.md ('- [ ]' tasks with acceptance criteria
and routes, per .keel/keel-policy.md), then retry. Each session has its
own plan file. (Guardrail: plan-before-write.)
```

That message names the exact file to write and the shape it must take;
writing that one file is always permitted, "or the gate would forbid the
act that satisfies it" (docs/keel-trust.md). Once the ledger exists,
ordinary writes proceed. An edit aimed at a locked target — the policy
file, `hooks/`, the settings files — is refused the same way, on a
different guardrail:

```
POLICY LOCK (Edit -> .keel/keel-policy.md): .keel/keel-policy.md, the
hooks/ and .claude-plugin/ directories and the settings files may only be
changed when the USER sets KEEL_OVERRIDE=on. Ask the user; do not work
around this.
```

**What the ledger asks for at stop.** Ending the turn with any item still
open is refused too, naming exactly which items and what would close them:

```
STOP BLOCKED: 2 plan item(s) still open (T4 - ...; T5 - ...) in
keel-plan-<sess8>.md. Before stopping, mark each item [x] done, [!]
blocked with a concrete reason, or [?] needs the user's decision - then
report the full ledger to the user. Use [~] only while a delegation is
genuinely still running. (Guardrail: stop-with-accounting.)
```

`[~]` is checked, not trusted: the stop gate looks for an open hand-off on
this session in `.keel/audit/keel-audit.jsonl` before it accepts an
in-flight claim (docs/keel-trust.md).

**What the board shows.** The URL in the boot lines opens a read-only,
loopback-only view of this session's own delegations as they happen — the
same view `scripts/keel_demo.py --tour --serve` plays a scripted version
of: a hub per working agent, satellite task cards attributed to it by
agent type and session, and the model-and-effort pill each launch actually
ran at. It costs no tokens, writes nothing back into the project, and
shows only what this project's own audit log already recorded
(`hooks/keel_session.py`, docs/keel-trust.md).

## Moving tiers

Moving up or down is always one `/keel:refit`, never a silent edit — the
arming file is itself policy-locked, so the model has no other path
(skills/refit/SKILL.md). The skill drafts the full amended policy text to
`.keel/plans/refit-draft-<sess8>.md`, presents it as a plain diff — what
changes, what it means in operation, what it does not change — and then
stops: only your own hand, editing the file from the draft, or a session
you relaunch with `KEEL_OVERRIDE=on` and direct yourself, can apply it.
After it lands, the amendment is recorded as a ratified decision and the
draft is deleted. Every ratified change moves the policy file's own
`version:` line and gains a row in its Amendment log — the law names its
own version (skills/refit/SKILL.md).

Moving down is the identical procedure, not a lesser one. If you armed at
3 and found only friction, going back to 1 through `/keel:refit` is the
ratification working exactly as it would going the other way — an adopter
who over-armed is not stuck; they draft, they are shown the diff, they
ratify it.

## What you get for the ceremony

Each tier's cost buys a record that would not otherwise exist: a plan that
outlives the session it was written in, versioned in git rather than
living only in a chat scrollback (`.keel/plans/`, the shipped Local
amendment in templates/keel-policy.md); an audit trail that `keel attest`
reconciles against the ledger after the fact rather than trusting a
status word (docs/keel-trust.md); knowledge that survives compaction,
injected at the next session's start instead of depending on a context
window that resets (`hooks/keel_session.py`); delegations that are
attested rather than taken on trust — every launch and return on record, so
an in-flight claim with no open hand-off is caught (docs/keel-trust.md);
and refusals that are visible on the record rather than a silent
workaround — every blocking verdict writes one audit line, with the path
redacted first, before it returns anything to the model
(`hooks/keel_gate.py`, `hooks/keel_redact.py`).

## Honest limits on day one

- **Claude Code only, for now.** keel's gates travel through this
  harness's own hook registration; governing a session on a different
  harness waits on an adapter, which is planned and not yet built
  (`.keel/decisions/2026-08-25-portability-goes-through-adapters.md`).
- **Proven on Windows; not yet watched end-to-end elsewhere.** The
  dashboard's one-click restart is written with no platform branching, but
  POSIX replaces the running process image where Windows starts a new one
  — a real difference no test exercises, because none of the suite execs
  for real. It has been watched work on Windows and not yet watched on
  macOS or Linux (`.keel/backlog.md`, BL5).
- **The demo tour is entirely synthetic.** Every session id, task name and
  review verdict `scripts/keel_demo.py --tour` plays back is invented; it
  proves the mechanics work, not that any real work happened.
- **Nothing here is a security boundary against a determined operator.**
  The lock raises the cost of a mutation reaching the tree unrefused; it
  is not a proof that no such path exists, and a local file can be edited
  by any hand with shell access outside a gated session. See
  docs/keel-trust.md's own "Honest limits" and "The bypass rate is
  published" for exactly what is and is not guaranteed.
