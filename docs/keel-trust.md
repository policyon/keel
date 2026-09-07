# Trust model

This page states plainly what the policy lock protects, what the gates
guarantee, what never happens, how adoption is graduated, and where keel's
honest limits are. Every promise below names the code or the test that holds
it, because a promise this tree cannot ground is prose, and keel's own
reference gate (`keel_checks --refs`, R18) fails the build on a claim that
points at nothing.

## What the policy lock protects

While a project is armed, the model cannot rewrite the rules that bind it.
hooks/keel_gate.py refuses any edit to:

- `.keel/keel-policy.md` — the arming file: tier, roles, routing, holds.
- `hooks/` — the gate code itself.
- `.claude-plugin/` — the manifest that registers the gates.
- the settings files (`.claude/settings.json`, `.claude/settings.local.json`,
  `.keel/settings.json`).

The lock covers shell commands as well as write tools, because a gate that
guards a write tool but not a shell redirect guards nothing: a quote-aware
segment scanner blocks a pipeline segment that combines a mutation — a
mutating command word, an assignment to a `KEEL_*` variable, a file-writing
redirect — with a protected name, and anything it cannot parse confidently
is treated as hostile when the raw command mentions a protected name at all
(the fail-safe in hooks/keel_gate.py, pinned in both directions by fixtures
under tests/fixtures/gate/).

**The unlock channel does not exist inside a session.** The only way past
the lock is `KEEL_OVERRIDE=on` in the process environment — set by the user
before the session starts, never by the agent, whose attempt to set it in a
shell command is itself a policy-lock hit (`keel_override` is a protected
token in hooks/keel_gate.py). The same holds for the kill switches:
`KEEL_GATE=off` stands the gates down and `KEEL_PLAN_TTL_MIN` tunes plan
freshness, and all three are read from the environment only
(templates/keel-policy.md documents them as user-only).

Both gates declare FAIL-CLOSED WHEN ARMED, FAIL-OPEN WHEN UNARMED, and a
test asserts the declaration against the observed behaviour in both
directions (R3, tests/test_keel_kernel.py): an armed project whose gate
cannot evaluate gets a deny with the failure named, and a project that never
opted in is never broken by keel's own bug.

## What the gates guarantee

- **Plan-before-write.** No state-changing tool call — write, edit or shell
  — runs until this session's own ledger exists and is fresh at
  `.keel/plans/keel-plan-<sess8>.md`. Parallel sessions never share a
  ledger, and writing the plan file itself is always permitted, or the gate
  would forbid the act that satisfies it (hooks/keel_gate.py).
- **Stop-with-accounting.** A turn may end only when every ledger item
  carries a terminal status: done, blocked with a reason, needs the user's
  decision, or genuinely in flight. "In flight" is verified, never trusted:
  it passes only when the audit log shows an open hand-off for this session,
  so it cannot be used to dodge accounting (hooks/keel_stop.py).
- **The ledger is reconciled against the audit log.** Every delegation
  launch and return is recorded in `.keel/audit/keel-audit.jsonl`, and
  `keel attest` (scripts/keel_attest.py) reads the two files against each
  other, raising a completed task with no delegation on record and an
  in-flight claim with no open hand-off. The escalation cycle — attempt,
  review, one deep retry, terminal blocker — is exercised end to end against
  the real stop gate and attest by tests/test_keel_review.py.
- **Every block is on the record.** A blocking verdict writes one audit line
  before it returns; paths in that line are relativised first so the log
  never leaks an absolute filesystem path (hooks/keel_gate.py,
  hooks/keel_redact.py).

## What never happens

- **No network in the kernel.** The gates and observers open no socket. The
  one component in the tree that does is the read-only viewer, which binds
  `127.0.0.1` on a port the operating system assigns and refuses every
  state-changing HTTP method; a test fingerprints the whole project tree
  before and after a full round of requests to prove it wrote nothing (R19,
  scripts/keel_dashboard.py, tests/test_keel_wave3.py).
- **No third-party code.** The runtime is the Python standard library,
  version 3.10 or newer, and nothing else: `keel_checks --deps` walks every
  import in the tree against an allowlist on all three operating systems on
  every push (R7, R14, scripts/keel_checks.py,
  .github/workflows/keel-ci.yml). There is no lockfile because there is
  nothing to pin.
- **No telemetry.** Nothing reports usage, content or outcomes anywhere, and
  keel makes no network call at all. Everything it writes stays on your
  machine: a project's own `.keel/` directory, plus four files under
  `~/.claude/keel/` that "What keel writes, and where" below names one by one.
  What is recorded is redacted first — a fixture fails the suite if a real
  username reaches a log (hooks/keel_redact.py, tests/test_keel_wave2.py).
- **No model calls of keel's own.** The kernel is deterministic Python;
  distillation of observations into records is the session's own model
  writing files inline (skills/log/SKILL.md). keel holds no key, calls no
  endpoint, and adds no second model to the trust boundary.
- **No unadopted project is touched.** A project without `.keel/` gets
  silence: nothing written, nothing injected, nothing gated (R25, pinned by
  tests/fixtures/capture/06-unadopted-project-is-untouched.json and
  tests/fixtures/gate/01-unarmed-allows.json).

## What keel writes, and where

Two places, both on your own machine, and nothing anywhere else. This section
exists because an earlier version of the bullet above claimed everything landed
under the project's `.keel/` directory, and that was not true: four files live
in your home directory by a ratified decision of 2026-08-21 (the decision
record stays with the maintainer's development records — a published cut
ships none), for reasons that are about diagnosis and recovery rather than
about keel's convenience.

**In the project — `.keel/`.** The session ledgers, the audit log, the
observation queue, the knowledge and decision records: the whole record, in
plain files you can read, diff and delete.

**In your home directory — `~/.claude/keel/`.** Four files, each answering a
question the project directory cannot:

| File | What it is for | Why it cannot live in the project |
|---|---|---|
| `keel-hook-errors.jsonl` | One line per hook failure, redacted, so `keel doctor` and the next session's banner can tell you what broke instead of failing quietly | A hook may be failing precisely *because* no project could be resolved. Created lazily: a machine whose hooks never fail never gets the directory (hooks/keel_faultlog.py) |
| `keel-prompts/keel-prompts-<session>.jsonl` | Your own prompts, capped and redacted, so a session whose context the harness discards can be handed back what you actually asked for | It is survival state for the event that destroys in-session context. Written only for a project that adopted keel (hooks/keel_compaction.py) |
| `keel-compaction-ledger.jsonl` | One line per compaction — the permanent index of where each session's lossless transcript went | Same reason; an index that forgets is not an index |
| `keel-registry.json` | The set of adopted projects on this machine, so a cross-project view knows what exists. Paths are collapsed to `~` before writing | It is a cross-project fact by definition (hooks/keel_registry.py) |

Every one of those writes goes through the same write-time redaction screen the
audit log uses, none is ever tracked by a repository, and none leaves the
machine. **Measured, not asserted:** the prompt-and-compaction pair was probed
end to end on 2026-09-01 — both files written, the recovery block returned
carrying the prompt verbatim, and the home prefix collapsed on the way through.
The honest limit is frequency rather than function: compaction is rare, so most
sessions never create the ledger at all.

To remove them, delete the directory. keel re-creates only what it needs, and
only when the thing it records actually happens.

## Graduated adoption

For which tier to start at and why, see docs/keel-adopting.md — this table
stays the reference.

Enforcement is chosen, never sprung. What arms keel in a project is the
presence of `.keel/keel-policy.md`, and its `tier:` decides whether
enforcement applies — ONE threshold, not four steps: `hooks/keel_gate.py`
sets `ENFORCING_TIER = 2`, below which nothing is refused, and at or above
which plan-before-write, stop-with-accounting and the policy lock all
apply (R25). The rows are what a project DECLARES against that threshold
(the ladder is documented in templates/keel-policy.md; the amendment that
made this text match the code is version 1.1.0 in the policy's own
Amendment log):

| Tier | Name | What it declares |
|---|---|---|
| 0 | observe | That nothing may block. Capture still records — it gates on adoption, not on tier. |
| 1 | log | The knowledge habit: records, index, budgeted injection. Enforcement-identical to tier 0. |
| 2 | gate | THE THRESHOLD: plan-before-write, stop-with-accounting, the policy lock. |
| 3 | govern | The review-and-attest discipline, on top of the same gates as tier 2. |

Moving up or down a tier is one `/keel:refit` — a proposed diff, explicit
ratification, a recorded decision — never a silent edit, because the arming
file is itself policy-locked. What keel injects at session start is bounded
in bytes at the injector, and overflow is visible, never silent (R16, R34,
hooks/keel_session.py, asserted by tests/test_keel_knowledge.py).

## Honest limits

- **keel binds the agent inside armed projects only.** A global installation
  observes; it never enforces. A project that never adopted keel is left
  alone by design, which also means keel offers it no protection at all
  (R25).
- **A user-set override suspends the lock.** `KEEL_OVERRIDE=on` is a
  deliberate escape hatch, and the gate trusts the process environment as
  the user's word: it can refuse an agent's attempt to set the variable in a
  gated shell command, but it cannot know who exported a variable before the
  process started.
- **The shell scanner raises cost; it does not prove impossibility.** It is
  a parser applying a stated design rule with a stated fail-safe, pinned by
  fixtures in both directions — not a proof that no mutation path exists.
  A genuinely novel evasion is a bug to report (see SECURITY.md), not a
  betrayed guarantee. The routes below are NOT novel, are not hypothetical,
  and are not bugs to report: they were measured, they are open, and naming
  them here is the point of this section.
- **What the scanner does not refuse, measured rather than estimated.** 28
  probes against the gate in a throwaway project: 18 refused, 10 allowed.
  Every one of the nine path-shape evasions held — dot-segment round trips,
  `./`, doubled separators, upper-case directories, backslash separators,
  quote-splitting, globs, and paths assembled from variables. These got
  through:
  - an **interpreter one-liner** writing a locked file directly, which
    includes the arming file itself;
  - a **nested shell string** — `bash -c`, `eval`, and command substitution —
    each carrying an otherwise-refused redirect through untouched, because the
    scanner does not recurse into a nested command;
  - **verbs outside its list**: `perl -pi -e`, `dd of=`, `install -m SRC DST`;
  - **`git checkout`** naming a policy-locked path outside `.keel/`;
  - an **override smuggled through a wrapper**, `env KEEL_OVERRIDE=on cmd`,
    where the same assignment written inline is refused.

  Nine of those ten now leave an audit line and are still allowed, so they are
  visible on the record rather than silent. The tenth names no protected path
  at all, so no path scanner could judge it — a limit, not a defect. Closing
  the rest means the lock adopting a closed mode that would also refuse
  `git diff hooks/` and every other read reaching a locked path through an
  unlisted word; that trade has not been made.
- **The stop gate never blocks the same session twice in a row.** A
  per-session marker makes a second consecutive block impossible, because a
  blocking stop hook that repeats is a hung session (hooks/keel_stop.py).
  Persistent under-accounting is caught by `keel attest`, not by an infinite
  gate.
- **The audit log is a plain file in the tree.** Append-only by contract,
  verified by the gates and by attest — but a hand with shell access outside
  a gated session can edit it like any other file. Real non-repudiation is a
  property of your version control and its remote, not of a local file.
- **The record has failed once, and the event is gone.** On 2026-09-02 two of
  keel's own hook processes appended to `.keel/audit/keel-audit.jsonl` at the
  same moment. A 239-byte line was written at the same file offset as a
  303-byte line already there, overwriting its first 239 bytes and leaving its
  last 64 as a fragment of their own. One event — a subagent's stop — was
  permanently lost. It was not recovered, because there was nowhere to recover
  it from; a lost-update race destroys the only copy. The cause was keel, not
  an outside hand: at least one writer was positioning by its own idea of
  end-of-file instead of relying on the operating system's append. The writer
  now takes a lock and serialises the whole line in one write, and both halves
  are pinned by tests. That closes this race. It does not make the log
  tamper-evident, and it cannot restore what was lost — which is why this
  paragraph is here rather than in a changelog. If your use of keel depends on
  the record being complete rather than merely honest about itself, hash
  chaining is designed and not yet ratified, and until it ships the
  append-only property is a convention this page is telling you failed once.
- **The gates see what the harness routes through them.** A tool call that
  never reaches keel's hook entry points is outside the gate. That boundary
  is the harness's registration mechanism, and `keel survey` reports every
  registration it can see so the boundary is at least visible (R30,
  scripts/keel_survey.py).

## The bypass rate is published

The override above is the one sanctioned hole in the lock, so its use is
measured and published rather than described. Every bypass writes a
`gate_bypass` line to `.keel/audit/keel-audit.jsonl`, and `keel survey`
(scripts/keel_survey.py) reports the counts, warns when bypasses outrun
denials inside a seven-day window, and prints WHAT was bypassed by top path
segment — because a bypass count without its composition is a number that gets
argued about instead of read.

The first data point, measured on keel's own repository on 2026-08-18: **365
bypasses on record against 4 policy-lock denials ever, and 308 of those 365
were writes into `hooks/`** — keel's own gate source. That decomposition is the
whole finding. keel is developed under keel (D6), so its own source sits inside
its own lock, and the standing override was the instrument used to work on it:
the metric could not tell governance-evasion from development, and the raw
ratio read like a broken lock.

The ratified answer is *workshop paths*: a self-hosted repository may declare,
in its policy-locked arming file, path prefixes where the lock's deny becomes
allow-plus-loud-audit — each such write recorded as its own audit event and
counted separately from bypasses, while the arming file, the settings files and
the workshop list itself stay hard-locked, so the model can never widen its own
workshop (ratified 2026-08-18 in keel's own project records; a published cut
ships none of them). Nothing shipped
changes for adopters: no template carries a workshop list, and a project that
does not host the gate it is governed by has no use for one.

## The gates fired on their own publication

This repository was published under keel's own gates, and the release that
put this page in front of you was itself refused, repeatedly, until it was
right. Every incident below is from the publication sitting of 2026-09-07 or
the sitting before it, happened to the session doing the publishing, and is
the designed behaviour observed against the instrument's own maker — which
is the strongest evidence this page can offer that the gates do what the
sections above claim.

- **The publication plan was refused before the first command ran.** The
  session's first ledger draft failed the machine-checkable plan contract
  with twelve findings (tasks without parseable acceptance criteria and
  routes), and plan-before-write held every state-changing call until a
  compliant ledger existed (hooks/keel_gate.py).
- **keel refused its own release script.** The first attempt to run the
  mirror cut was denied by the plan gate, because the mirror still carried
  an armed policy from the previous cut and the gate resolves one verdict
  per governing project — the target's law bound the writer, exactly as it
  would for any adopter's tree. The refusal itself was audit-logged into the
  target's own log.
- **One stray line failed seven guards.** That logged refusal left a single
  audit line in the mirror, and the published-cut declaration inverts the
  self-assertions — so seven independent tests failed the mirror's suite,
  each naming the one non-empty record surface, until a human cleared the
  line. A cut cannot go out carrying even one line of session residue
  without the suite saying so (tests/keel_published_cut.py).
- **The suite gate caught a real red run in its first hour.** The wrapper
  that refuses to call a suite green without the final summary line
  (scripts/keel_suite.py) reported `FAILED (failures=4)` on its first real
  use the sitting before publication, then passed the clean rerun — both on
  the record.
- **The version check refused even a sanctioned deletion.** The cut removes
  the arming file by ratified design, and `keel_checks --policy` still
  failed the staged deletion until the commit made it real — the check
  would not take the cut script's word for it. (That the failure message
  misnames the case is filed as a defect in the maintainer's queue; the
  refusal standing is the point.)
- **The tree-staleness check caught keel soiling its own distribution.**
  `keel_checks --distribution` failed the publishing session's tree because
  keel's own hooks had compiled bytecode into the shipped bundle — measured
  twice, once within fourteen seconds of a hand deletion — and stayed red
  until a regeneration made the committed bundle byte-identical to its
  sources again.
- **The cut script refuses to stand next to a remote.** Re-cutting the
  mirror after it had gained its GitHub remote was refused by the script's
  own guard: publishing is the owner's act, so the assembler will not run
  where a push is reachable (scripts/keel_cut_mirror.py).
- **The lock refused the publisher a read it could not classify.** The
  session's attempt to read keel's user-global error log through an
  interpreter one-liner was denied — the gate cannot tell a read from a
  write inside an interpreter, so it refuses either way — and the same
  information was read a moment later through a plain allowlisted command.
- **The stop gate blocked the publishing session three times.** Each time a
  turn tried to end with the ledger not accounting for every item — open
  tasks after castoff, an in-flight claim with no delegation on the audit
  record, a task added and left open — the stop was refused with the items
  named, and the turn ended only after the ledger told the truth
  (hooks/keel_stop.py).

None of this was staged for this page: the refusals are ordinary audit lines
in the maintainer's development records, of exactly the kind every armed
project accumulates. The release you are reading cleared eleven repository
checks and a 3088-test suite run inside the published tree itself, through
the same wrapper that had refused the red run days earlier.

## Who trusts what

- **Individuals** get enforcement without ceremony: one file arms a project
  at a tier they chose, every record is plain text they can read, diff or
  delete, and there is no account, no key and no network dependency in the
  path.
- **Teams** get an accounting trail that survives the session: plans,
  delegations and blocks land in `.keel/audit/keel-audit.jsonl`, "done"
  carries evidence that `keel attest` re-checks after the fact, and the
  session close is consolidated on file (skills/moor/SKILL.md) rather than
  in a chat scrollback nobody rereads.
- **Enterprises** get determinism and no egress: a standard-library-only
  runtime verified by a build gate on three operating systems, no telemetry,
  no third-party code in the trust boundary, and a policy file whose changes
  go through a ratification procedure (skills/refit/SKILL.md) instead of an
  agent's discretion. Everything keel does is reviewable as plain text in
  the repository it governs.
