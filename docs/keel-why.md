# Why keel

## The problem

An AI coding agent does what its context suggests, weighted against
everything else in that context. Written instructions — a project standards
file, a "never touch X" paragraph, a carefully worded system prompt — are
persuasion: they compete with the rest of the session for attention, they
degrade under context compression, and they lose exactly when the stakes are
highest, deep into a long session when the early rules have scrolled far
behind the current problem.

Two failures recur in practice:

1. **Writes before agreement.** The session starts modifying files before
   anyone has agreed what it is going to do. There is no plan on record, so
   afterwards there is nothing to check the work against — intent was never
   written down, and the diff is the only artifact.
2. **Claims instead of accounting.** The session ends on "all done" with
   items quietly dropped, delegated work never confirmed returned, and no way
   to tell a finished task from an asserted one.

And beneath both sits the structural failure: in an instruction-only setup
the agent can edit the very files that carry its rules. Discipline that the
disciplined party can amend is voluntary, whatever the prose says.

## The founding commitments

keel's answer is to move the rules that matter out of prose and into
processes with exit codes. Four commitments follow, and each one names the
code that enforces it — because a claim this document cannot ground in the
tree does not belong in it (R15).

- **Gates decide; prose advises.** Every gate verdict passes through one
  table that maps a decision to an exit code — allow 0, block 2 — and both
  the emitted JSON and the process exit come from that table, so a blocking
  exit code can never disagree with a permissive decision (R6:
  `KeelVerdict.to_exit_code()` in hooks/keel_events.py, asserted in both
  directions by tests/test_keel_kernel.py). The field's tools tell the model
  what it should do; a keel gate returns 2 and the write does not happen.
- **Files are the record.** The plan ledger, the audit log, the decisions
  and the knowledge records are plain text inside the project tree, readable
  and diffable without keel installed. The search index is a cache: deleting
  `.keel/cache/` loses nothing, rebuild is delete-then-derive, and a test
  asserts that round trip rather than trusting it (scripts/keel_index.py,
  tests/test_keel_knowledge.py).
- **The rules that bind the model sit outside its reach.** While a project
  is armed, hooks/keel_gate.py refuses any edit — through a write tool or
  through a shell command — to the arming policy, the hook code, the plugin
  manifest and the settings files. The only way past the lock is an
  environment variable the user sets before the session starts; no unlock
  channel exists inside one. docs/keel-trust.md states exactly what the lock
  covers and where it stops.
- **Every claim resolves against the tree.** Every rule identifier cited
  anywhere in this repository must have an entry in docs/keel-rules.md, and
  every intra-repository path named in tracked markdown must exist on a CI
  checkout — `keel_checks --refs` fails the build otherwise (R18, R15,
  scripts/keel_checks.py). Every stated limit exists as a constant a gate
  reads, never as a number living only in a sentence (R32).

## Enforcement, not persuasion — the working set

- **Plan-before-write.** No state-changing tool runs until this session's
  own ledger exists and is fresh at `.keel/plans/keel-plan-<sess8>.md`;
  parallel sessions never share one, and writing the plan file itself is
  always allowed, or the gate would forbid the act that satisfies it
  (hooks/keel_gate.py; both-direction fixtures under tests/fixtures/gate/,
  run by tests/test_keel_kernel.py).
- **Stop-with-accounting.** A turn may end only when every ledger item
  carries a terminal status, and "in flight" is verified against the audit
  log — an open hand-off must actually be on record — never taken on trust
  (hooks/keel_stop.py, fixtures under tests/fixtures/stop/).
- **Attestation.** `keel attest` reconciles a session's ledger against
  `.keel/audit/keel-audit.jsonl` after the fact and raises the two
  discrepancies that matter: a task marked done with no delegation on
  record, and an in-flight claim with no open hand-off
  (scripts/keel_attest.py, exercised end to end by
  tests/test_keel_review.py).

## Zero, verified

- **Zero third-party code.** keel runs on Python 3.10+ and the standard
  library, with nothing installed first. This is not a packaging preference;
  it is a gate — `keel_checks --deps` walks every import in the tree against
  an allowlist, on Ubuntu, macOS and Windows, on every push (R7, R14, R27,
  .github/workflows/keel-ci.yml).
- **Zero telemetry.** Everything keel writes lands under the project's own
  `.keel/` directory; nothing reports usage, content or outcomes anywhere.
  Paths are redacted before they are recorded (hooks/keel_redact.py), and a
  fixture fails the suite if a real username ever reaches a log
  (tests/test_keel_wave2.py). A project that never adopted keel is left
  byte-for-byte untouched
  (tests/fixtures/capture/06-unadopted-project-is-untouched.json).
- **Zero network in the kernel.** The gates and observers open no socket.
  The one component in the tree that does is the read-only viewer, and it
  binds `127.0.0.1` on an ephemeral port the operating system assigns —
  never a fixed or derived one (R19, scripts/keel_dashboard.py, proven by
  tests/test_keel_wave3.py, which also fingerprints the project tree to show
  the viewer wrote nothing).
- **Zero model calls of keel's own.** The kernel is deterministic Python.
  Distillation of observations into knowledge records is done by the
  session's own model, inline, following skills/log/SKILL.md — keel never
  calls a model, so there is no key to configure, no bill to arm, and no
  second model to trust.

## keel runs under keel

keel is developed armed on its own repository at tier 2 (D6): waves are
planned in `.keel/plans/`, gated by hooks/keel_gate.py, accounted by
hooks/keel_stop.py and reconciled by `keel attest`. The arming file's tier is
asserted by tests/test_keel_wave3.py. A harness its own authors do not live
under is a harness nobody has tested.

## Where to go next

- docs/keel-trust.md — the trust story: what the policy lock protects, what
  the gates guarantee, what never happens, and the honest limits.
- docs/keel-rules.md — the normative register: every design commitment and
  the check that enforces it.
