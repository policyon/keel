# keel rules

The normative register. Every rule identifier cited anywhere in this repository
is defined here, and every entry names the file or the check that enforces it.
Identifiers are stable; gaps are reserved.

A rule is a design commitment, not a preference: it constrains what keel may
ship, and changing one is a policy change under `docs/keel-governance.md`
rather than an implementation detail.

## Rules

### R1 — Matching is Python `re`, and both cases ship

All guard logic is Python and all matching goes through `re` with explicit
flags; no text-processing shell utility carries a decision. Matching is
case-insensitive by default, and any pattern that is deliberately
case-sensitive carries a justifying comment and fixtures in both cases.

Enforced: convention 3 in `docs/keel-conventions.md`; both-case fixtures under
`tests/fixtures/gate/` and `tests/fixtures/capture/`, run by
`tests/test_keel_kernel.py` and `tests/test_keel_wave2.py`.

### R2 — No symlinks in the repository

Git tracks no symlink. A symlink becomes a text stub on any checkout that
cannot create one, so the file's content is silently wrong on a whole class of
machines.

Enforced: `keel_checks --symlinks`; independently by `tests/test_keel_phase0.py`.

### R3 — Failure policy is declared per guard class, and tested

Every hook and script states `FAIL-OPEN` or `FAIL-CLOSED` in its contract
docstring, and a test asserts the declaration against observed behaviour. One
guard failing open while its siblings fail closed disappears on the one machine
that lacks its prerequisite, and nothing says so.

Enforced: conventions 1 and 12 in `docs/keel-conventions.md`, asserted by
`tests/test_keel_phase0.py`, `tests/test_keel_kernel.py` and
`tests/test_keel_wave2.py`.

### R5 — No payload value reaches a shell

No value derived from a harness payload is interpolated into a shell string,
and every subprocess call uses the argument-list form. Payload strings are
carried as data and never as program text, so a command, a message or a path
cannot become an instruction.

Enforced: convention 4 in `docs/keel-conventions.md`; `hooks/keel_gate.py`,
`hooks/keel_stop.py`, `scripts/keel_leak_check.py` and
`scripts/keel_checks.py`, with the loop-safety cases in
`tests/test_keel_kernel.py`.

### R6 — The exit code is the decision

One table maps a verdict to an exit code — allow 0, ask 2, deny 2 — and both
the emitted JSON and the process exit come from it. A blocking exit code can
therefore never disagree with a permissive decision.

Enforced: `KeelVerdict.to_exit_code()` in `hooks/keel_events.py`, rendered by
`hooks/keel_adapter_claude.py`; the contract is asserted in both directions by
`tests/test_keel_kernel.py`.

### R7 — Zero third-party runtime dependencies

keel runs on Python 3.10+ and the standard library, on every supported
operating system, with nothing installed first. A missing runtime dependency
turns a guard into a no-op on exactly the machines nobody checked.

Enforced: `keel_checks --deps`, an import allowlist run on three operating
systems by `.github/workflows/keel-ci.yml`.

### R9 — The always-loaded budget is measured, in CI and in the adopter's project

Context that a harness loads before the user asks for anything is counted
against a fixed limit, and the same measurement is repeated where keel is
installed rather than quoted from this repository. A budget measured only over
shipped templates says nothing about the session it is meant to protect.

The limit is 1,400 estimated tokens. It was 1,200 from Phase 0 until
2026-08-21, when
`.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md` raised
it — ratified by the owner, sized to a measurement (154 tokens of need for the
compaction layer's two hook registrations, against 132 of headroom), and
explicitly pre-approving no further raise. The number is never quoted from
here by a check: it is read from the constant below, and this sentence is the
citation, not the authority.

Enforced: `keel_checks --budget` (`BUDGET_TOKEN_LIMIT` in
`scripts/keel_checks.py`); re-measured by `keel survey`
(`scripts/keel_survey.py`).

### R10 — Markers are case-insensitive, and an unclosed marker is visible

Any inline marker keel recognises is matched case-insensitively, and an opening
marker with no close raises a visible warning instead of swallowing the
remainder of the text. Silence on a malformed marker is indistinguishable from
absence of one.

The marker keel recognises is `<keel-private>`, and the rule is stronger than
"warn": an unclosed opening marker DROPS the remainder of the value as well as
warning. An exclusion that fails open publishes exactly what its author asked
keel to withhold, so this one guard fails closed while its siblings in the same
file fail open — stated here because R3 forbids that divergence being silent.
The exclusion runs inside `redact`, before every write, so any component that
follows convention 5 excludes marked content whether or not it knew about it.

Enforced: convention 3 in `docs/keel-conventions.md`, which binds the marker
parser as it binds every other pattern in `hooks/keel_redact.py`
(`strip_private`); the eight-case fixture set `tests/fixtures/private/*.json`,
run by `tests/test_keel_knowledge.py`, which also asserts that marked content
cannot reach the observation queue.

### R13 — One launcher, one generated hook table

Every `hooks/hooks.json` entry is a one-liner invoking `hooks/keel_hook.py`
with a subcommand, and the file itself is generated from one bootstrap string
and one entry table — never hand-edited. A shell program pasted once per hook
is a program that gets fixed in some copies and not others.

Enforced: `scripts/keel_gen_hooks.py --verify` in
`.github/workflows/keel-ci.yml`; `tests/test_keel_phase0.py` and
`tests/test_keel_kernel.py`.

### R14 — Nothing is pinned because nothing is depended on

The supply-chain surface is the Python standard library. keel ships no
lockfile, vendors no third-party source, and inlines no unpinned dependency
into a released artifact.

Enforced: `keel_checks --deps`; `NOTICE` records the one derivation that does
exist.

### R15 — Documentation may not contradict the code

No shipped document states as fact a thing the tree does not do, and counts of
hooks, agents, skills, tests or tools are generated from source rather than
typed. A number in a document that disagrees with the code is a defect of the
same severity as a code defect.

Enforced: `docs/keel-governance.md` §3; manifest-versus-changelog agreement in
`tests/test_keel_phase0.py`; reference resolution by `keel_checks --refs`.

### R16 — Injected context is bounded in bytes, and the bound is enforced at the injector

Everything keel puts into a session before the user has asked for anything is
counted in bytes and cut to fit. The limit is `KEEL_INJECT_CAP_BYTES` (default
4096), it is read by the code that writes the text, and the truncation happens
there — not in a checker that reports afterwards, and not as a count of
records, which says nothing about how much context a record costs. A budget
that is measured but never applied is a number, not a limit.

Enforced: `DEFAULT_INJECT_CAP_BYTES` and `index_block` in
`hooks/keel_session.py`, asserted against the byte count of the emitted block
by `tests/test_keel_knowledge.py` (R32: the limit is configuration a gate
reads).

### R18 — Every reference resolves

Every file named in a manifest, a configuration or a shipped document exists in
the tree, and every rule identifier cited in the tree is defined in this
register. Dead configuration is configuration that was never true or stopped
being true silently.

"Cited in the tree" means cited in AUTHORED text. The append-only record
streams are exempt from the citation half, by name and one file at a time
(`CITATION_SCAN_EXEMPT`): those files quote what a session ran, so a command
carrying a rule identifier writes it into the record verbatim - a claim nobody
made, in a file that is evidence and is therefore never edited to satisfy a
documentation gate. Authored files in the same tree - plans, decisions,
knowledge records - stay scanned, because four of the five violations this
gate was built for were found in exactly those.

Enforced: hooks.json closure in `tests/test_keel_phase0.py`; citations and
intra-repository paths by `keel_checks --refs`; the exemption pinned in both
directions by `TestRecordStreamsAreEvidence` in `tests/test_keel_phase0.py`.

### R19 — No fixed or derived network ports

Any server keel starts binds `127.0.0.1` on port 0 and prints the URL the
operating system assigned. A port derived from a user id or a project path is
undefined on some platforms and collides on all of them.

Enforced: `scripts/keel_dashboard.py`; two-viewer and ephemeral-port cases in
`tests/test_keel_wave3.py`.

### R22 — Every agent declares least-privilege tools, and reviewers are read-only

Every keel agent declares an explicit `tools:` list in its frontmatter, and
every reviewer holds read-only tools only. An agent with no tools field
inherits everything, including Write, which turns a reviewer into an editor on
the one machine nobody checked.

Enforced: `keel_checks --agents`; both-direction fixtures under
`tests/fixtures/agents/`, run by `tests/test_keel_agents.py`.

### R25 — Enforcement exists only where the project opted in

The presence of `.keel/keel-policy.md` in a project is what arms keel, and its
absence is what disarms it. A global installation observes; it never enforces,
and a project that never adopted keel is left byte-for-byte alone.

Enforced: `hooks/keel_gate.py` and `hooks/keel_session.py`; the unarmed
fixtures `tests/fixtures/gate/01-unarmed-allows.json` and
`tests/fixtures/capture/06-unadopted-project-is-untouched.json`.

### R26 — keel does not hand-count its own parts

Counts of keel's own components are rendered from source in CI, never
maintained by hand in prose. A hand-maintained count drifts on the first change
that nobody remembers touches it.

Enforced: `docs/keel-governance.md` §3; convention 9 in
`docs/keel-conventions.md`.

### R27 — The full suite runs on three operating systems

Ubuntu, macOS and Windows all run the whole test suite and every check on every
push. A single-platform build proves the code works where it was written and
nowhere else.

Enforced: the matrix in `.github/workflows/keel-ci.yml`.

### R28 — Contract conformance is asserted structurally, never by substring

Where a document carries a contract — frontmatter keys, required headings, a
tool list, a limit line — the check parses the structure and compares values;
it never passes on the accident of a substring. A grep for "80" passes on a
line number or the year 1980 and guards nothing.

Enforced: `keel_checks --agents`, wired into `.github/workflows/keel-ci.yml`;
both-direction fixtures under `tests/fixtures/agents/`, run by
`tests/test_keel_agents.py`.

### R29 — A release is a changelog entry plus a version bump, and issues are triaged

Work ships with its entry in `CHANGELOG.md` and a version bump in the same
change; issues leave each week with a label, a decision, and a stated reason
where the decision is "not now". Documentation that keeps moving while the
changelog stays silent tells a reader nothing about what they are running.

Enforced: `docs/keel-governance.md` §§1–2; version agreement asserted by
`tests/test_keel_phase0.py`.

### R30 — Registration ownership: reporting is total, refusal is narrow

`keel survey` reports every hook registration it can see across global, project
and plugin scopes, whether or not it conflicts. Arming refuses only where
another gate is *armed* over the same project, and the refusal prints the
migration step; registered-but-disarmed observers coexist.

Enforced: `scripts/keel_survey.py`; `docs/keel-governance.md` §4; conflict
scan in `tests/test_keel_wave2.py`.

### R31 — Releases are cut from tags only

Nothing is published from a branch, a working tree or a manual copy, and the
running version is compared against the manifest at startup so that
shipped-versus-source drift is one visible line rather than a later discovery.

Enforced: `docs/keel-governance.md` §1; `keel survey --startup`
(`scripts/keel_survey.py`) against `.claude-plugin/plugin.json` and
`.claude-plugin/keel-pins.json`.

### R32 — Limits are configuration a check reads, not prose

Every stated limit exists as a constant that a gate enforces. A number that
lives only in a sentence is a suggestion, and nothing fails when it is
exceeded.

A limit may still be amended — it is configuration, not scripture — but the
amendment lands in the constant and in a written decision together, never in
prose alone: the 1,200 to 1,400 raise of 2026-08-21
(`.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md`)
moved the constant, the rule text and the reason in one reviewed change.

Enforced: `BUDGET_TOKEN_LIMIT` in `scripts/keel_checks.py`, applied by
`keel_checks --budget` and re-applied by `scripts/keel_survey.py`.

### R33 — Continuous integration exists before the code it guards

The build gates were in place before the first hook was written, and every
check keel relies on runs in CI rather than on a maintainer's machine.

Enforced: `.github/workflows/keel-ci.yml`, which runs the checks, the suite,
the generated-hooks verification and the hook-execution spike.

### R34 — Nothing is dropped silently at a cap

Where a cap truncates, the truncation is visible at the point of truncation and
what was withheld is countable; no content disappears without a record that it
did.

Two places apply this, in the two forms the situation takes:

- **Session injection.** The block is cut at a record boundary — never
  mid-line, because half a record is a fact nobody can look up — and one line
  is appended naming how many records were withheld and the command that
  reaches them. The notice travels in the very context it was cut from, so the
  reader cannot miss it.
- **A generated index document.** The remainder goes to
  `keel-index-overflow.md`, a file the reader can open.

Enforced: `OVERFLOW_MARKER` and `index_block` in `hooks/keel_session.py`, whose
exactness (kept plus withheld equals total) is asserted by
`tests/test_keel_knowledge.py`; `scripts/keel_records.py`, which treats the
overflow document as a generated artifact rather than a malformed record.

### R43 — Loosening the lock only ever reaches ask

The arming file's `## Policy lock` configuration section may TIGHTEN the
locked set freely, adding any project-relative path to it. LOOSENING is
different in kind, not just in size: a `relax:` entry only ever demotes a
deny to a user-answered ASK, never to an allow - the harness prompts, and the
user's own click, out of band from the model, is the authorization. No
configuration can turn a locked write into an allow, so the model alone can
never complete one. The anchor set - the arming file itself, `hooks/`,
`.claude-plugin/` and the settings files - is never relaxable by
construction, and an unknown relaxation name invalidates the whole section:
keel falls back to the full default lock rather than guessing what was meant.

Enforced: the relaxation path in `hooks/keel_gate.py` (`RELAXATIONS`,
`policy_lock_section`, `relaxation_for`); pinned by `tests/fixtures/gate/`
fixtures 21–28 and `tests/test_keel_relaxation.py`.

### R44 — The fix-round ladder has a floor, a ceiling, and a hard cap

An escalation-retry series is not unlimited. Rounds 1 through
`FIX_ROUND_RESUME_CEILING` (3) may resume the same executor context; round
`FIX_ROUND_FRESH_FLOOR` (4) onward must open a fresh context, on the deep
tier; no task reaches round `FIX_ROUND_HARD_CAP` + 1 (6) - past the cap the
ledger must show `[!]` or `[?]`, never another attempt. The resume-vs-fresh
split names which context and tier serve a round, and the audit log records
neither, so only the hard cap is enforced by a check; the other two limits
are procedure the orchestrator follows, asserted here only as documentation.

Enforced: `FIX_ROUND_RESUME_CEILING`, `FIX_ROUND_FRESH_FLOOR` and
`FIX_ROUND_HARD_CAP` in `scripts/keel_attest.py`, applied to
escalation-suffixed task ids (`T16b` attests base task `T16`, per `base_id`);
a base task whose highest recorded round exceeds the cap raises
`LADDER CAP EXCEEDED`, one of `DISCREPANCY_VERDICTS`, matched by
`is_discrepancy_verdict`. The suffix grammar is read case-insensitively
(convention 3) and spreadsheet-style, so `T16B` is round 2 and a doubled
`T9aa` is round 27 — far past the cap, which is the point: it is flagged, not
excused. A token that looks like a suffixed id but parses as neither raises
`UNPARSEABLE TASK ID`, so no task can leave ladder accounting silently.
Asserted both directions by `tests/test_keel_wave2.py`.

### R45 — A check reads the tree the next commit can ship

A file-scanning check reads git's index UNION the untracked-but-not-ignored
files, never the tracked set alone. A tracked-only scan cannot see the file
under test until the commit that ships it, so the run that reports PASS and
the run that decides are different runs over different trees - green on the
maintainer's machine, red on the first CI run that has the file. A gitignored
file is in no commit and so in no scan set, which is the same rule read from
the other side: a cited path that is ignored is treated as absent, because a
checkout will not have it.

Content is read from the working tree rather than from the staged blob, which
is deliberately stricter than a checkout: an edit that has not been staged yet
is the very thing under test.

Enforced: `_scanned_files` in `scripts/keel_checks.py`, which `--names` and
both halves of `--refs` take their file list from, and which fails closed - a
git that cannot answer raises, because an empty file list would pass every
scan by vacuum. Proven in all four directions by `TestScanSet` in
`tests/test_keel_phase0.py`: unstaged violation fails, staged violation fails,
ignored file is not scanned, clean tree passes.

### F11 — Gates are synchronous, observation is asynchronous

A gate that does not block is not a gate: gate hooks run inline and the session
waits for the verdict. Capture, logging and index maintenance are declared
`async: true` and may not emit a decision, so observation never makes the user
wait.

Enforced: convention 11 in `docs/keel-conventions.md`; the `is_async` column in
`scripts/keel_gen_hooks.py`, rendered into `hooks/hooks.json`.

## Decisions

### D6 — keel is developed under keel

keel arms its own repository at tier 2: waves are planned in `.keel/plans/`,
gated by `hooks/keel_gate.py`, accounted by `hooks/keel_stop.py`, and
reconciled by `keel attest`. A harness its own authors do not live under is a
harness nobody has tested.

Enforced: `.keel/keel-policy.md` at `tier: 2`, asserted by
`tests/test_keel_wave3.py`.
