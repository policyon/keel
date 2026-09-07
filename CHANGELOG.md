# Changelog

Every release is a changelog entry plus a version bump in
`.claude-plugin/plugin.json`, cut from a tag — see `docs/keel-governance.md`.

## 0.6.0 — the plan contract grows teeth, and the voyage learns to resume

The planning layer's enforcement half, the resume command, and the first
exercised relaxation: what 0.5.0 promised as vocabulary, this release makes
mechanism.

- `skills/castoff/`: the resume counterpart to `/keel:moor` — a read-only
  session boot from the newest mooring record plus a survey, reporting the
  open threads, what is actionable in this session's state, and one
  recommended track. Writes nothing; the plan still goes through the gate.
- `hooks/keel_gate.py`: the plan contract is now asserted at write time —
  a session-ledger write missing a task identifier, a `Route:`, an
  `Accept:`, or carrying placeholder vocabulary is refused with the
  findings named, on every instrument: the write tools, edits checked from
  their payload, and mutating shell commands (which cannot be
  contract-checked and are therefore denied toward the checkable path).
  Refit drafts and other non-ledger files keep the plain carve-out.
- `scripts/keel_attest.py`: attest reads contract-shaped ledgers (task ids
  and `Route:` sub-bullets), and the fix-round ladder lands as R44 —
  resume ceiling, fresh-context floor, and a hard cap of five rounds as
  constants the check reads; a task past the cap, or an id-shaped token
  that will not parse, is a discrepancy that turns the report non-clean.
- `agents/`: every agent definition pins its model class per the routing
  table (researcher fast, executors standard/deep, reviewers standard),
  and `keel_checks --agents` fails on drift between the pins and the map.
- `.keel/keel-policy.md` (this repository's own arming file, by ratified
  refit): `relax: release-version-bump` — the version bump that produced
  this very release demotes from deny to a question. Survey wording and
  the template's kill-switch row now state the accepted override values.
- `skills/moor/`: a second same-day mooring takes a numbered suffix
  instead of overwriting another session's record; and the closure check
  reads every skill's references pages, not just its `SKILL.md`.

## 0.5.0 — the free edition completed, and the lock learns to ask

Everything between the review layer and this cut: the core edition's last
skills, the editions mechanism, the trust story, and a policy lock that can
now be configured by the user — tightened freely, loosened only ever to a
question.

- `skills/moor/`, `skills/ratify/`, `skills/refit/`: end-of-voyage
  consolidation, same-turn decision records, and the governed amendment of
  the arming file — the drafted diff, the hard stop for ratification, and
  the rule that the model never applies the policy edit itself.
- `skills/lay/`: the basic form — refuse the two wrong states (already
  armed; another armed stack), copy the arming template, choose a tier with
  1 as the safe default, accept-or-edit a routing map of model classes, and
  confirm with survey. The deeper adoption flow arrives with a later
  feature and says so plainly rather than improvising.
- `scripts/keel-features.json` and `keel_checks --closure`: the feature
  registry (five features along the edition seams, every agents/ and
  skills/ file claimed exactly once) and the bundle-closure rule — every
  skill invocation written in a shipped skill body must resolve to a skill
  its feature closure actually carries.
- `keel_checks --refs` now matches a CI checkout exactly: a cited path that
  is gitignored counts as absent even when present locally, with a
  documented fail-safe when git itself is unavailable.
- `docs/keel-why.md` and `docs/keel-trust.md`, linked from the README: the
  enforcement-over-persuasion case and the trust story — what the lock
  protects, what the gates guarantee, what never happens, and the honest
  limits — each claim citing its enforcing check.
- **The policy lock's configuration section** (R43): an armed project's
  arming file may carry `## Policy lock` with `lock:` paths (added
  protection, no ceremony — though never `.keel/plans/`, which would break
  the bootstrap) and `relax:` names from a shipped vocabulary. A relaxation
  only ever demotes deny to ASK — the harness prompts and the user's answer
  is the authorization; allow is unreachable by configuration. Unknown
  names fail closed and say which name was unknown. The anchor — the
  arming file itself, `hooks/`, the settings files — is never relaxable by
  construction. Vocabulary v1 holds exactly one entry:
  `release-version-bump`, a manifest write whose resulting JSON differs
  from the file on disk only in the top-level version string.
- **Unverifiable is deny**: a write target whose path cannot be normalized
  is refused before the lock, the plan carve-out and the override are even
  consulted, with control bytes scrubbed from every echo — found by the
  review layer's security reviewer before this release, fixed in the one
  escalation retry, and pinned by fixtures in both directions.
- **Refusals now name the next step**: a manifest denial points at the
  release relaxation and how to enable it; an arming-file denial points at
  the refit skill; a hooks or settings denial says plainly that kernel
  changes need a user-launched override session.
- **The override is loud**: while `KEEL_OVERRIDE` is active in an armed
  project, session start carries one reminder line, survey prints it
  beside the lock state, every stop writes an `override_active_at_stop`
  audit line with a stderr note, and every denial the suspended lock
  swallows is recorded as `gate_bypass`. Reminders are scoped to armed,
  enforcing projects — a project that never adopted keel stays
  byte-for-byte untouched, proven by a tree-fingerprint test.
- `keel survey`: the lock-configuration line (defaults, or the exact
  tighten/relax deviations), the override reminder, and bypasses counted
  beside — never inside — the denial figures. `keel dashboard` counts the
  two new event kinds.
- `docs/keel-rules.md`: R43 enters the register with its check, per the
  standing rule that a rule and its enforcement land together.

## 0.4.0 — Phase 3: the review layer

Four specialist reviewers written from scratch, the house contract asserted
as parsed structure rather than substring, and the escalation ladder proven
accountable end to end. NOTICE is unchanged: nothing in this release derives
from anyone else's prompt text.

- `agents/reviewer-correctness.md`, `agents/reviewer-silent-failure.md`,
  `agents/reviewer-tests.md`, `agents/reviewer-security.md`: the review
  layer. Each holds exactly the read-only toolset — a reviewer is a verdict,
  never more work — a delegation-grade description the orchestrator can
  route on, and the four contract sections: Scope, an 80% confidence floor
  (a finding below it is dropped, not hedged), What NOT to flag (the
  countermeasure against review noise), and a terse structured Verdict whose
  `STATUS: fail` findings are precisely what the one escalation retry
  carries.
- `scripts/keel_checks.py --agents`: the contract, enforced structurally
  (R28). Frontmatter is parsed, headings and tool lists are compared as
  values, and the floor is read as a value inside its own section — never a
  substring hunt, which passes on a line number or the year 1980. Every
  agent must declare an explicit `tools:` list (R22): an agent with no tools
  field inherits everything, including Write, which turns a reviewer into an
  editor on the one machine nobody checked. Wired into CI beside the other
  checks.
- `docs/keel-rules.md`: R22 and R28 move from reserved gaps to entries.
- `templates/keel-policy.md`: a Review subsection under Routing — reviewer
  findings feed the one `deep` retry of rule 3; a verdict never widens a
  task's scope; the second failure lands `[!]` with the blocker named in the
  line itself, so the stop gate and `keel attest` can account for how the
  cycle ended.
- `tests/test_keel_review.py`: routing rule 3's cycle exercised end to end
  in a fixture project against the real stop gate and `keel attest` — the
  verified `[~]`, the recorded deep retry, the terminal `[!]`, and both
  blocking directions; plus attest's documented discrepancy, an `[x]` with
  no delegation on record.
- `tests/fixtures/agents/` and `tests/test_keel_agents.py`: nine declarative
  fixtures in both directions — a compliant reviewer and a write-tooled
  executor pass; a write-tooled reviewer, a missing section, a missing,
  doubled or malformed floor line, an absent tools key and out-of-order
  headings are each flagged with the clause named.

## 0.3.0 — Phase 2: the knowledge layer

Capture, distillation, a derived index, retrieval and budgeted injection. The
design law is now what the code enforces: **files are the record, and the index
is a cache anyone may delete.**

- `hooks/keel_capture.py`: observation-worthy events also append one line to
  `.keel/queue/keel-observations.jsonl` — session, tool, one action summary and
  the redacted paths touched. Never a payload body: no file content, no command
  output, no delegation prompt. A hand-off is queued once, when it returns. The
  audit log's shape is untouched, so the stop gate and `keel attest` see exactly
  what they saw before.
- `hooks/keel_events.py`: `append_queue` / `read_queue` and `QUEUE_SUBPATH` —
  the queue is a second file contract with its own schema version, written by
  the one JSONL writer both logs now share.
- `hooks/keel_redact.py`: the `<keel-private>` exclusion (R10). Case-insensitive
  in either tag, tolerant of attributes and internal whitespace, spanning lines
  and any number of blocks; an unclosed opening marker drops the remainder AND
  prints one visible warning. It runs inside `redact`, so every component that
  already followed "redact before write" excludes marked content whether or not
  it knew about it. Eight fixtures pin the behaviour.
- `scripts/keel_index.py`: `keel index rebuild` and `keel index status`. SQLite
  with WAL and a five-second busy timeout; FTS5 is PROBED at open — a scratch
  table created and dropped — and a plain table scanned with `LIKE` plus a
  word-start check answers the same contract where the probe fails. Rebuild is
  delete-then-derive, so it is idempotent, and deleting `.keel/cache/` entirely
  loses nothing. A test asserts that round trip rather than trusting it.
- `tests/contracts/keel_search_contract.py`: the conformance kit. One corpus,
  one list of cases, run unchanged against both backends — the in-tree swap
  proof, rather than a diagram of one.
- `scripts/keel_chart.py`: `keel chart <query>` prints one `id date type title`
  line per hit, redacted and no wider than 120 characters;
  `keel chart --get <id>...` prints the full records. An empty result is
  `no matches` and exit 0 — a report tool never fails on finding nothing.
- `skills/log/` and `skills/chart/`, surfacing as `/keel:log` and `/keel:chart`:
  thin routers over `references/` pages. Distillation is the session's own model
  writing records inline, so keel still makes zero model calls of its own.
- `hooks/keel_session.py`: after the plan line, the knowledge index is injected
  newest-first under a HARD byte cap — `KEEL_INJECT_CAP_BYTES`, default 4096,
  enforced at the injector rather than measured afterwards (R16). Overflow
  truncates at a record boundary and appends one visible line naming how many
  records were withheld and how to reach them (R34): never silent, never
  mid-line.
- `docs/keel-rules.md`: R16 added; R34 extended to state the injector's form of
  visible overflow; R10 extended to state that the exclusion drops as well as
  warns, and why that one guard fails closed among fail-open siblings.
- Tests: the pipeline end to end (queue → record → index → retrieval →
  injection), the cap, the eight marker fixtures, the conformance kit against
  both backends, example records checked against the schema, and the declared
  failure policy of every new file.

## 0.2.0 — Phase 1: kernel, observers, tools, arming

This is the first published history of keel. Development prior to first
publication took place in a private working history that was reset before
publish; this tree at `v0.2.0` is the complete state of the project.

- `docs/keel-rules.md`: the rules register — every identifier this repository
  cites, stated as a design commitment with the file or check that enforces it.
  Identifiers are stable; gaps are reserved.
- `scripts/keel_checks.py`: `--refs`, the fifth gate. Every `R`/`F`/`D`
  citation in a tracked file must resolve to an entry in the register, and
  every intra-repository path named in tracked markdown must exist. Wired into
  `.github/workflows/keel-ci.yml` and proven in both directions by
  `tests/test_keel_phase0.py`.
- `docs/keel-governance.md`: §5 reference integrity — every citation resolves
  in-repo, every documented claim has an enforced or testable basis, and no
  document or changelog entry contradicts the tree.

The Phase 1 exit gate: the gates are built on a neutral
event model, observation and the command line are in place, and keel is armed
on its own repository at tier 2 (D6). Nothing here is published
to a marketplace yet; the knowledge layer and the reviewer agents are Phases 2
and 3.

Phase 1, wave 1 — kernel core.

- `hooks/keel_events.py`: the neutral event model — gates consume normalised
  events and per-harness adapters translate, so no harness payload shape ever
  reaches a gate. `KeelEvent` over six normalised kinds, and `KeelVerdict`
  whose `to_exit_code()` is the single exit table in keel — allow 0, ask 2,
  deny 2, so a blocking exit code can never disagree with the emitted
  decision (R6).
- `hooks/keel_adapter_claude.py`: the first harness translator. Payload in,
  `KeelEvent` out; verdict in, `hookSpecificOutput` JSON out. It contains no
  policy at all, which is what makes a second harness a translation exercise.
  An allow verdict emits nothing: keel narrows permissions, never widens them.
- `hooks/keel_gate.py`: plan-before-write and the policy lock — a write or a
  shell command is refused until this session has a fresh plan ledger, and the
  files that carry keel's own policy are locked against edit while armed:
  arming at tier 2, session-isolated ledgers in
  `.keel/plans/keel-plan-<sess8>.md`, `KEEL_PLAN_TTL_MIN` freshness, always-
  writable plan files, and the shell segment heuristic that stops
  `Set-Content`/`rm`/redirect attacks on the locked set without blaming
  `git log` for reading it.
- `hooks/keel_stop.py`: stop-with-accounting — a session may not end while its
  ledger still claims unfinished work. `[~]` is verified against
  `.keel/audit/keel-audit.jsonl`, never trusted, including the
  background-launch and liveness rules.
- Both gates declare FAIL-CLOSED WHEN ARMED, FAIL-OPEN WHEN UNARMED, and a
  test asserts the declaration against the behaviour in both directions (R3).
- `hooks/keel_hook.py`: `gate` and `stop` subcommands added; the launcher
  stays the single entry point (R13) and now returns the verdict's exit code.
  Stdin is decoded as UTF-8-SIG, so a Windows pipe's byte-order mark cannot
  silently disarm a gate.
- `scripts/keel_gen_hooks.py`: `hooks/hooks.json` is now generated from one
  bootstrap string and one entry table, with a `--verify` mode wired into CI —
  the committed file cannot drift from the table.
- `tests/fixtures/gate/` and `tests/fixtures/stop/`: declarative fixtures in
  both directions, run through the launcher as a subprocess exactly as CI
  does, by `tests/test_keel_kernel.py`.
- `.gitattributes`: `text=auto` with explicit `eol=lf` for the source types
  and `eol=crlf` for `*.bat` (the queued Phase 1 line-ending decision).
- `NOTICE`: the ported-code declaration for the two gates.

Phase 1, wave 2 — observation, the command line, and the agents.

- `hooks/keel_redact.py`: the shared redactor — the one place a path becomes
  safe to record. Convention 5 now has an implementation: every string
  carrying a filesystem path passes through it before reaching a log, an
  audit line or a message. The home directory is resolved at runtime — never
  a hardcoded username — and its Windows 8.3 short form comes from the same
  Win32 call Windows uses to generate one. `redact_path` prefers the
  project-relative form, so a project that itself lives under the home
  directory is not logged as `~/…` file by file.
- `hooks/keel_capture.py`: the observation layer — activity and delegation
  routing on one record. State-changing tool calls become one redacted action
  line; `Task`/`Agent` calls become the open and close halves of a hand-off.
  Nothing is written in a project without `.keel/`, and nothing is ever
  written to stdout.
- `hooks/keel_session.py`: session boundaries, recorded at both ends.
  SessionStart records the boundary and injects THIS session's ledger path,
  built by `keel_gate.session_plan_relpath` so the path injected and the path
  enforced cannot drift apart; SessionEnd records the close. A project that
  never adopted keel gets silence.
- `hooks/keel_hook.py`: `capture` and `session` subcommands; `spike` stays.
- `scripts/keel_gen_hooks.py`: five harness events registered from one table,
  and an `is_async` column that renders convention 11 into the document —
  gates carry no async flag, observers do, and SessionStart does not, because
  injected context that arrives late is not context.
- `scripts/keel.py`: the command line — invoked as a script from the plugin
  root, with no global binary to collide with anything installed — dispatching
  to three read-only tools.
  - `keel survey`: version against pin against changelog, arming state and
    tier, kill-switch values, the R9 budget re-measured where it runs, and
    the R30 registration scan across global, project and plugin scopes.
    Reporting is total; the one narrow refusal is another gate stack armed
    over the same project, which prints its migration step. Exit 0 always.
  - `keel attest`: reconciles a session ledger against the audit log.
    Two discrepancies are raised — a completed task with no
    delegation on record, and a `[~]` with no open hand-off — and the scope
    limit is stated in the file: it attests the delegation record, never the
    text of a report.
  - `keel leak-check`: the pre-push scanner for secrets and unredacted paths,
    with every pattern case-insensitive (convention 3) and the matched span
    always masked at a fixed width.
- `agents/executor.md`, `agents/executor-deep.md`, `agents/researcher.md`:
  the three delegation targets. They name routing TIERS (`standard`, `deep`,
  `fast`) and never a model, because law binds tiers and any provider can serve
  one; and they carry least-privilege tool lists — the researcher holds no
  write tool at all. Their frontmatter is inside the 1,200-token always-loaded
  gate.
- `templates/keel-policy.md`: the Routing section now names the agent per
  tier and states the five routing rules, including one retry on `deep` with
  the review findings attached before `[!]`/`[?]` goes to the user, and
  parallel executors only over disjoint files.
- `tests/fixtures/capture/` and `tests/fixtures/session/`: declarative
  observer fixtures in both directions — "record" and "silent" — run through
  the launcher as subprocesses, including a redaction case that fails if a
  real username reaches the log.
- `tests/test_keel_wave2.py`: those fixtures, plus unit tests for the
  redactor, the survey conflict scan, attestation in both directions, and
  leak detection in both directions; the declared-failure-policy assertion
  now covers every wave-2 file.
- `NOTICE`: the ported-code declaration generalised to every derived file
  added this wave.

Phase 1, wave 3 — the viewer, the record checker, the budget, and arming.

- `scripts/keel_dashboard.py` (`keel dashboard`): the read-only local viewer
  over the audit log and the ledgers. It reads `.keel/audit/` and
  `.keel/plans/` and writes nothing at all — the four state-changing HTTP
  methods are bound to one refusal handler, and a test fingerprints the whole
  project tree before and after a full round of requests to prove it. The port
  is EPHEMERAL: it binds `127.0.0.1:0`, the operating system assigns, and the
  URL is printed (R19 — no fixed port, and no port derived from a user id or
  a project path either). Ledger names are validated by shape before any path
  is built from them, and every path in every response, ledger text included,
  passes `keel_redact` first.
- `scripts/keel_records.py` (`keel records`): the governance-field schema
  checker, and the file that holds the record contract — `name`,
  `description`, `type`, `generated`, `verified`, `cites`, `stale_after` —
  with `name` and `description` as keel's two
  additions, because a record retrieval cannot route on is as lost as one that
  rotted. Severities: shape is an error, drift and
  unresolvable pins are warnings, and an unresolvable pin never fails a run,
  so keel's checks never depend on a neighbouring repository being installed.
  It walks directories rather than `git ls-files`, defaults to
  `.keel/knowledge/` and `.keel/decisions/`, and treats an absent record
  directory as exit 0 — adopting keel must not fail a build on day one.
- `scripts/keel_checks.py`: the `--budget` gate now counts the REAL
  always-loaded surface — the `name` and `description` frontmatter of every
  component under `agents/` and `skills/`, plus the `command` strings in
  `hooks/hooks.json` — and the README-head proxy is dropped. No harness loads
  keel's README into a session, so charging prose against the budget measured
  the wrong thing, and at 1,184 of 1,200 tokens it had left 16 tokens of
  headroom: the next agent would have broken the build over a paragraph. The
  1,200 limit is unchanged and strict; the reading is now **668**.
- `.keel/keel-policy.md`: **keel is armed on keel at tier 2** — the D6
  self-hosting bootstrap and the Phase 1 exit gate. `.keel/plans/` and
  `.keel/audit/` ship tracked, because they are the development record of the
  tool and its first knowledge corpus; `.keel/cache/` remains the only ignored
  path, since it is rebuildable by definition. Enforcement goes
  live when the plugin is installed in a session here; the file is the
  commitment.
- `.github/workflows/keel-ci.yml`: `actions/checkout` and
  `actions/setup-python` moved to their current majors, clearing the Node 20
  deprecation annotation on every job, and a `keel survey --startup` step now
  proves the command-line entry point starts on all three operating systems.
- `tests/fixtures/records/` and `tests/test_keel_wave3.py`: eighteen
  declarative record fixtures in both directions — a well-formed record
  passes; a missing field, a type outside the vocabulary, an expired
  `stale_after` and a drifted pin are each flagged with the right severity —
  plus the dashboard driven over 127.0.0.1 on its ephemeral port, the budget
  re-scope, and keel's own arming file surveyed at tier 2 with zero conflicts.

## 0.1.0 — Phase 0 foundations

- Repository initialised: Apache-2.0 licence, NOTICE, SECURITY.md, and the
  governance and conventions documents.
- Plugin manifest `.claude-plugin/plugin.json` with a `builtAgainst` pin, and a
  single-entry `.claude-plugin/marketplace.json` for local marketplace install.
- `hooks/keel_hook.py`: the single stdlib-only launcher, dispatching on a
  subcommand; `spike` implemented, declared fail-open.
- `hooks/hooks.json`: one SessionStart entry, a one-liner invoking the launcher
  (R13 — no duplicated shell programs). It probes for a *working* Python 3.10+
  rather than a merely present one: the first spike run on Windows found
  `command -v python3` resolving to the Microsoft Store stub, which exits 49.
- `scripts/keel_checks.py`: stdlib-only import check (R7, R14), tracked-symlink
  check (R2), and always-loaded token budget (R9), each with a CLI flag.
- `.github/workflows/keel-ci.yml`: three-OS matrix (Ubuntu, macOS, Windows) on
  Python 3.10, running the checks, the tests, and the hook-execution spike
  (R27, R33).
- `tests/test_keel_phase0.py`: spike behaviour armed and unarmed, all three
  checks against this repository, manifest/changelog version agreement,
  hooks.json reference closure (R18), and no tracked symlinks.
- `templates/keel-policy.md`: the arming file, tiers 0–3, roles, routing tiers
  and user-only kill switches.
- Registration-ownership rule written (R30) in `docs/keel-governance.md`.
