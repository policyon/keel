---
# keel arming file. Copy to <project>/.keel/keel-policy.md.
# Its presence is what arms keel in a project; its absence is what disarms it.
# This file is policy-locked: the model cannot edit it, only the user can.
#
# Enforcement in code is ONE threshold, not four steps: hooks/keel_gate.py
# sets ENFORCING_TIER = 2. Below it nothing is refused; at it and above,
# plan-before-write, stop-with-accounting and the policy lock all apply.
# The rows below are what a project DECLARES against that one threshold,
# not four enforcement steps.
#
# tier: 0  observe  - declares nothing may block; capture still records
#                     regardless, because it gates on adoption, not tier.
# tier: 1  log      - declares the knowledge habit: records, index,
#                     budgeted injection, /keel:chart. Default for
#                     /keel:lay - enforcement-identical to tier 0.
# tier: 2  gate     - IS the threshold: plan-before-write, stop-with-
#                     accounting, policy lock - chosen, never sprung.
# tier: 3  govern   - declares review-escalation and attestation
#                     discipline, on top of the same gates as tier 2.
tier: 1
---

# keel policy — <project name>

Moving up or down a tier is one `/keel:refit`. Emergencies use the kill
switches below, which are user-only.

## Roles

Law binds roles, never named products. A role is a job description; which model
fills it is a routing decision, not a policy decision.

| Role | Job | May write |
|---|---|---|
| `orchestrator` | Plans, routes, reviews, records. Does not implement substantive work directly. | ledgers, decisions, records |
| `executor` | Implements exactly one scoped task, verifies it, reports. | source, tests, docs in scope |
| `executor-deep` | Same contract, escalation tier: tasks flagged COMPLEX, or one retry with review findings attached. | same as `executor` |
| `researcher` | Reads and reports. Never edits. | nothing |
| `reviewer-*` | Read-only specialist review against a house contract. | nothing |

## Routing

Tiers are abstract so that any provider can serve them. An unmapped tier falls
back to `standard`. Law binds tiers, never model names: changing which model
serves a tier is a routing decision made here, and no agent may make it.

| Tier | Used for | Agent | Maps to (this project) |
|---|---|---|---|
| `fast` | Read-only scoping, inventory, locating code | `researcher` | <unset — falls back to standard> |
| `standard` | Every task not flagged COMPLEX — the default | `executor` | <unset> |
| `deep` | Work flagged COMPLEX, and the one escalation retry | `executor-deep` | <unset> |

Routing rules:

1. **`standard` is the default.** A task goes to `deep` only because it was
   flagged COMPLEX at planning time, or because it is the one escalation retry.
2. **`fast` is read-only.** Scoping before planning routes to `researcher`,
   which holds no write tools; a tier is not a licence, the tool list is.
3. **Escalation is one retry, not a ladder without a top.** `standard` attempt
   → review → on failure, one `deep` retry with the review findings attached →
   on second failure, surface to the user as `[!]` (blocked, with a named
   blocker) or `[?]` (needs your decision). Never a silent third attempt.
4. **Parallel executors only for disjoint files.** Two executors may run at once
   only when their file sets do not intersect. Overlapping writes are sequenced,
   because the second writer silently loses the first one's work.
5. **Every delegation is on the record.** Launches and returns are audited to
   `.keel/audit/keel-audit.jsonl`; `[~]` in the ledger is verified against that
   log by the stop gate and by `keel attest`, never taken on trust.

### Review

After an executor reports done, the orchestrator routes the change set to the
relevant `reviewer-*` agent(s). Reviewers are read-only: a review is a verdict
on the work, never more work, and a reviewer's `STATUS: fail` findings are
exactly what gets attached to the one `deep` retry of rule 3. A reviewer
verdict never widens a task's scope — a finding outside the task's stated
scope becomes a new planned task, not a bigger retry. On the second failure
the ledger line becomes `[!]` with the blocker named in the line itself, so
the stop gate and `keel attest` can account for how the cycle ended.

Every verdict is written to the record the same turn it is reached:
`python scripts/keel.py review --task <id> --verdict pass|fail --notes "<one
line on why>"` appends one `review` event to `.keel/audit/keel-audit.jsonl`.
The vocabulary is exactly `pass` and `fail`, enforced by that command. Ledger
prose still says what a verdict meant; the event says that it happened, on
which task, in which session — a verdict living only in prose is invisible to
every reader keel has.

## Features

keel's components are grouped into named features — `kernel`,
`orchestration`, `knowledge`, `review`, `viewer` — declared in the registry
at `scripts/keel-features.json` in the plugin tree. A future, optional
`features:` list in this file's frontmatter will let a project enable a
subset by name. The default is all features enabled; an absent list changes
nothing. A disabled feature's components decline visibly — a named refusal
that says which feature is off, never a silent no-op — and a feature is
never disabled underneath another feature that requires it.

## Kill switches

User-only. keel refuses to act on any of these when the value was set by an
agent rather than by the user, and every use is written to the audit log.

| Switch | Values | Effect |
|---|---|---|
| `KEEL_OVERRIDE` | `on` / unset (`1`/`true`/`yes` also accepted) | Suspends the policy lock for one session. The escape hatch of last resort. |
| `KEEL_GATE` | `on` / `off` | `off` disarms plan-before-write and stop-with-accounting without changing the tier. |
| `KEEL_PLAN_TTL_MIN` | integer minutes | How long an approved plan stays valid before a new one is required. |
| `KEEL_DASHBOARD` | `on` / `off` | Overrides the live-view opt-in below for one session, in either direction. |

## Live view

Optional, and OFF unless you write it here. keel ships a read-only local
viewer of your own delegations; this section is where you say you want it
started for you.

```
## Live view

autostart: on
```

With `autostart: on`, every session start checks whether a viewer is already
serving THIS project and starts one if none is - so a board that died with a
previous session, or with the machine, comes back by itself rather than
waiting to be remembered. The server keeps running after the session that
started it ends, which is the whole point; nothing stops it for you.

Off is the default and every unclear case: no key, a value that is not `on`
or `off`, or two lines that disagree all mean off, said out loud rather than
guessed. The switch lives HERE, inside the policy-locked file, so the
decision to run a server on your machine is yours and cannot be taken by a
model - and `KEEL_DASHBOARD` in the environment overrides this line for one
session when you need the other answer once.

The viewer binds loopback only, serves read-only, costs zero tokens, and
records its machine-local state under `.keel/cache/`, the one ignored path.

### Stopping it, and the boards that outlive their projects

Nothing stops a board for you, so there is one command that stops THIS
project's:

```
python hooks/keel_liveview.py --stop
```

It ends a board only when that board proves it is yours: the port answers
with this project's identity AND states its own process id. Anything else is
refused with the reason, never guessed at - the port you recorded may since
have been taken by another project's viewer, and ending the wrong one closes
a window somebody is watching.

```
python hooks/keel_liveview.py --status
```

lists every board answering in the range, marking which is this project's,
which belongs to another, and which is serving a project THAT NO LONGER
EXISTS. That last kind is the reason this section exists: a board survives
the directory it serves, and the range is only ten ports wide. keel reports
those with the exact command to end them and never ends them itself - it
cannot tell a board somebody abandoned from one somebody is still watching,
and only you can.

## Policy lock

Optional. This section is itself policy-locked - it lives inside this file -
so only your own hand, or a session you launch with `KEEL_OVERRIDE=on`, can
add or change it. Absent, keel's shipped default lock applies exactly as
documented above; nothing here is required.

```
## Policy lock

lock:
- src/generated/

relax:
- release-version-bump
```

Two list forms, and nothing else. `lock:` TIGHTENS - each project-relative
path (file or directory) joins the locked set, on top of the default.
`relax:` LOOSENS - each name is resolved against keel's shipped vocabulary,
which today carries exactly one entry: `release-version-bump`, a write to
`.claude-plugin/plugin.json` that changes only its `version` value.

A relaxation only ever demotes a deny to an ASK - the harness prompts, and
your answer is the authorization. No entry in this section can turn a
locked write into an allow; the model alone can never complete one. The
anchor - this file itself, `hooks/`, `.claude-plugin/` and the settings
files - is never relaxable, by construction. An unknown relaxation name
invalidates the whole section: keel falls back to the full default lock and
says so, visibly. `.keel/plans/` (the session ledgers) can never be added to
`lock:` either, because that would block the very write the plan gate's
bootstrap depends on.

## Holds

Standing constraints that survive across sessions until you lift them. Empty
at adoption, and this section is policy-locked like the rest of this file, so
only your own hand adds one.

Write each hold as a bullet AT COLUMN ZERO, and say so explicitly when there
are none:

```
## Holds

- no push until I review the migration
- leave vendor/ alone until the upstream bump lands
```

WHAT A HOLD DOES TODAY. keel parses this section with the same parser that
reads `## Policy lock` above, and reports it in two places a session cannot
miss: the `holds` line of `/keel:castoff`'s orientation block, which lands in
every session's opening context, and the `holds` line of
`python scripts/keel.py survey`. An active hold is named there, with its own
text, so a session is told about it before it does anything.

WHAT A HOLD DOES NOT DO, stated plainly so this section is not mistaken for a
gate. It refuses nothing. No hold becomes a deny or an ask at any hook; no
write is blocked by one; a hold is not a path pattern and is never matched
against a filename. A hold is prose about intent, and it binds because the
model reads it and honours it — the same way a local amendment below binds —
not because a gate stops the work. If you need a path made unwritable, that is
`lock:` in the section above, which does refuse.

FOUR STATES, AND "NONE" IS NOT SILENCE. keel reports this section as ABSENT
(no `## Holds` heading), NONE (the heading plus an explicit none-marker),
ACTIVE (the heading plus hold bullets), or UNKNOWN. UNKNOWN is the one worth
knowing about: a section with the heading but no column-zero bullet and no
none-marker — a hold written only as prose, say, or indented as an example —
is reported as unreadable rather than as empty, out loud, because a constraint
keel cannot read is still a constraint you are relying on. Fenced and indented
examples, like the one above, are documentation and declare nothing.

- *(none active)*

## Local amendments

Project-specific rules that compose additively with the above. On a genuine
conflict, surface both sources and propose a resolution; never resolve it
silently.

1. **The record stays tracked** (shipped default, ratified 2026-08-18). The
   plans and the audit log are the durable record of this project's
   governance: `.keel/plans/` and `.keel/audit/` are versioned in git, and
   `.keel/cache/` is the one ignored path, because it is rebuildable by
   definition. A recorded verdict that is not in version control survives
   exactly until the next clean checkout. To opt out, edit this amendment in
   this file — the choice is then itself on the record.
