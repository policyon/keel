# What keel does, and what proves it

keel is a governance harness for AI-assisted work: it plans before it writes,
records what happened, accounts for what it stopped with, and refuses in the
places a model would otherwise be trusted on its word. This page is the
inventory — every capability the tree ships, and the tests that hold each one
up.

**Every number here was counted from the tree, and each one carries its own
count date and says what counted it** (the page began 2026-08-26; figures are
re-measured when touched, never carried forward). A figure nobody can
re-derive is the failure this page is most exposed to, so nothing below is
quoted from memory or from an earlier document.

---

## The capabilities, by the registry that defines them

Editions are generated along feature seams, so the seams are the honest
grouping. The source is `scripts/keel-features.json`, and
`keel_checks --closure` keeps it closed: every component path must exist,
every file under `agents/` and `skills/` must be claimed by exactly one
feature, and no page may invoke a skill its edition leaves out.

### kernel — 26 components, required by every other feature

The part that cannot be left out. It owns the event model, the gates, and the
command line.

| What it does | Where |
|---|---|
| One neutral event model, harness-independent | `hooks/keel_events.py` |
| Harness adapter: native payload in, native verdict out | `hooks/keel_adapter_claude.py` |
| One launcher for every hook (R13) | `hooks/keel_hook.py` |
| Observation: what ran, who ran it, what it touched | `hooks/keel_capture.py` |
| Plan-before-write gate, and the policy lock (R43) | `hooks/keel_gate.py` |
| Stop-with-accounting: a session may not end unaccounted | `hooks/keel_stop.py` |
| Session boundaries, and the bounded context injection (R16, R34) | `hooks/keel_session.py` |
| Redaction — the one place text becomes safe to record | `hooks/keel_redact.py` |
| What this installation actually carries | `hooks/keel_features.py` |
| The command line, ten subcommands | `scripts/keel.py` |
| The eleven repository checks | `scripts/keel_checks.py` |
| Ledger-vs-log reconciliation, and the fix-round ladder (R44) | `scripts/keel_attest.py` |
| Session-ledger contract checker | `scripts/keel_plans.py` |
| Governance-field schema for records | `scripts/keel_records.py` |
| Verdicts as events | `scripts/keel_review.py` |
| Deliberate-corner harvest | `scripts/keel_debt.py` |
| Environment and registration report (R30, R9) | `scripts/keel_survey.py` |
| Tracked-content leak scan | `scripts/keel_leak_check.py` |
| Generated hook table, never hand-written (R13) | `scripts/keel_gen_hooks.py` |

Eight harness events are subscribed: `SessionStart`, `SessionEnd`,
`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `PreCompact`, `Stop`,
`SubagentStop`. Gates run synchronously and observation runs asynchronously,
so watching never makes a session wait (F11).

### orchestration — 3 agents, 7 skills

Delegation with a route and a record. Agents: `agents/researcher.md`,
`agents/executor.md`, `agents/executor-deep.md`. Skills: `castoff` (orient at
session start), `lay` (lay out a plan), `moor` (close a session into a state
record), `ratify` (record a ruling), `refit`, `sound`, `wave-review` (batch a
dispatched wave's open questions into one numbered walkthrough).

### knowledge — 2 skills, 2 scripts

`log` distils a session's observations into records; `chart` retrieves them.
`scripts/keel_index.py` maintains a derived index the records can always
rebuild, and `scripts/keel_chart.py` reads it in two layers rather than
loading the whole corpus. The maintainer's development corpus is 238 records
today, 2026-09-07, counted by listing its `.keel/knowledge/` directory (a
published cut ships that directory empty — the corpus is the development
tree's, and every adopter grows their own).

### review — 5 reviewer agents

`agents/reviewer-correctness.md`, `agents/reviewer-security.md`,
`agents/reviewer-silent-failure.md`, `agents/reviewer-tests.md`,
`agents/reviewer-altitude.md`. Each holds exactly the read-only toolset and
the four contract headings, asserted structurally rather than by substring
(R22, R28).

### viewer — 1 script

`scripts/keel_dashboard.py`, a read-only local viewer over the audit log and
the ledgers. It binds loopback only, serves read-only, and costs zero tokens.

### Shipped, but claimed by no feature

Six modules are in the tree and tested, but no feature claims them, so they
ship in **no edition bundle**. That is a real gap in the registry rather than
a comment about their quality:

`scripts/keel_orchestration_dashboard.py` (the adopted orchestration board —
task orbits grouped under their executing agent, model·effort provenance on
cards and in the drawer, and a plain-language code-freshness chip),
`hooks/keel_liveview.py` (its opt-in autostart, stop and status),
`hooks/keel_registry.py` (the user-global fleet registry of adopted
projects), `scripts/keel_demo.py` (a zero-token synthetic board),
`scripts/keel_gen_editions.py` (the edition generator itself), and
`scripts/keel_backfill_reviews.py`.

---

## The enforcement surface

**Eleven repository checks** (nine → eleven across 2026-09-06: `--plugin`
added for BL56, `--distribution` for the tracked install bundle),
all in `scripts/keel_checks.py`, fail-closed — a check that cannot run is a
failure, never a pass, with one declared exception: `--plugin` visibly SKIPS
(not a pass) when the external `claude` binary is absent, since this
repository does not install it and CI's runners do not carry it:

| Check | What it refuses |
|---|---|
| `--deps` | anything outside the standard library (R7, R14) |
| `--symlinks` | a tracked symlink, which degrades to a text stub on some checkouts (R2) |
| `--budget` | an always-loaded context estimate over its limit (R9, R32) |
| `--names` | a denied name printed in any scanned text file |
| `--refs` | a citation with no register entry, or a path that will not exist on a checkout (R18, R15) |
| `--agents` | an agent without an explicit tool list, or a reviewer off contract (R22, R28) |
| `--closure` | a feature registry that is not closed, or a page invoking a skill its edition drops |
| `--policy` | a staged policy-file change that did not move its version (T230/T320) |
| `--leak` | the shipped payload naming a home path, key or address (excluding declared record surfaces) |
| `--plugin` | `claude plugin validate` reporting a component that fails to load, against a generated edition bundle (BL56) |
| `--distribution` | a committed `dist/keel` bundle that drifted from what a fresh generation would write, or carries files one would not emit |

Both scanning checks read **the tree the next commit can ship** — the index
union the untracked-but-not-ignored files — so a file is checked while it is
being written rather than after the commit that ships it (R45).

**The register** carries 30 entries (28 rules, 1 feature note, 1 decision)
in `docs/keel-rules.md`, and a rule enters it only together with the check
that enforces it.

**Continuous integration** runs on three operating systems (R27, R33) from
the workflow in this repository, covering the checks, the CLI entry point,
the generated hook table, the unit suite, edition-bundle validation, and a
hook-execution spike.

**The command line** exposes ten subcommands: `survey`, `doctor`, `attest`,
`leak-check`, `records`, `index`, `chart`, `dashboard`, `debt`, `review`.

---

## Test coverage

**3,088 tests across 91 modules** — the count the gated suite wrapper
(`scripts/keel_suite.py`) reported on 2026-09-07, not a carried-forward
figure. Alongside them sit **195 fixture files** under `tests/fixtures/`, in
eight kinds: `gate` (119), `records` (18), `stop` (18), `agents` (12),
`session` (12), `private` (8), `capture` (6), `knowledge` (2).

Fixtures ship **in both directions** by convention: a rule is proven by a
case it must catch and a case it must not.

### Where the weight sits

| Tests | Module | Guards |
|---|---|---|
| 178 | `tests/test_keel_kernel.py` | events, adapter, gate, stop |
| 140 | `tests/test_keel_dashboard_t28_31.py` | the viewer's attention pass |
| 82 | `tests/test_keel_wave2.py` | redaction, capture, session, CLI |
| 77 | `tests/test_keel_target_arming_t178.py` | enforcement keyed on the target project, not the session's cwd |
| 69 | `tests/test_keel_derived_facts_t168.py` | fingerprint, edition and friction figures derived from the tree, never asserted |
| 64 | `tests/test_keel_relaxation.py` | the policy lock and its relaxations |
| 61 | `tests/test_keel_gate_t169.py` | the gate refuses to manufacture its own bypasses |
| 61 | `tests/test_keel_knowledge.py` | capture queue, index, retrieval, injection |
| 60 | `tests/test_keel_wave3.py` | dashboard, record checker, budget |
| 59 | `tests/test_keel_liveview.py` | the autostart, and that it can never cost a session |
| 57 | `tests/test_keel_features.py` | the registry and the editions gate |
| 54 | `tests/test_keel_session_seat_and_live_view.py` | who took the seat, and where to watch |
| 52 | `tests/test_keel_demo.py` | the zero-token demo cycle, and the scripted tour timeline |
| 50 | `tests/test_keel_handoff_route.py` | the model and effort a delegation ran at |
| 49 | `tests/test_keel_dashboard_t322.py` | task-chip attribution to the owning agent |

The remaining 76 modules carry the rest between them, most of them named
for the task that paid for them (the per-module counts above were taken
2026-09-06 and rank the weight; the suite total above is newer).

### Coverage of the shipped modules

**Every one of the 35 modules under `hooks/` and `scripts/` is named by at
least one test module** — verified by scanning the test tree for each module's
name. The most heavily surrounded are `scripts/keel.py` (71 modules name it),
`hooks/keel_events.py` (34) and `hooks/keel_gate.py` (23); the most thinly
covered are `scripts/keel_backfill_reviews.py`, `hooks/keel_compaction.py`,
`scripts/keel_debt.py`, `scripts/keel_demo.py`, `hooks/keel_liveview.py`,
`hooks/keel_registry.py` and `scripts/keel_statusline.py`, each with a single
dedicated module.

---

## What this page does not claim

Three limits, stated because a coverage summary that hides them is worth
less than none.

**There is no line-coverage figure, and there will not be one.** keel carries
zero third-party runtime dependencies (R7, R14), so no coverage tool runs
here. "Covered" on this page means *exercised by a named test*, never a
percentage of lines.

**Browser behaviour is pinned by shape, not by execution.** The orchestration
board's client-side code runs in a browser; the suite is Python and cannot
run it. What the suite asserts is structure — that a join reads only the
fields it is allowed to read, that a guard precedes every write, that a
derived value is marked as derived. Behaviour is confirmed by hand against a
live board and recorded in the session ledger. Nothing in the automated gates
opens the page, and a change that satisfies the shape while breaking the
behaviour would pass.

**Not every module reaches an edition.** The six unclaimed modules above are
tested but ship in no bundle, so an adopter installing an edition gets no
board, no fleet registry, no autostart, and no demo.
