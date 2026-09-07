# keel code conventions

The house style every keel file follows. A convention is how the code is
written; the identifiers in brackets are the rules it carries out, defined in
`docs/keel-rules.md`.

## The ten

1. **PEP 8, full type hints, and a contract docstring** on every hook/module:
   what it reads, what it emits, its exit-code table, and its declared failure
   policy (fail-open or fail-closed) — the declaration a test verifies (R3).
2. **Every guard ships fixtures in both directions** — block-cases and
   allow-cases. A guard with no allow-fixtures fails CI: the false positive is
   what gets a guard uninstalled, so it is guarded first.
3. **Case-insensitive matching is the default**; any deliberately
   case-sensitive pattern carries a justifying comment and both-case fixtures
   (R1, R10).
4. **No shell string interpolation of any payload-derived value**;
   `subprocess` list-argument form only (R5).
5. **Redact before write:** any string containing a filesystem path passes
   `keel_redact` before reaching a log, message, or record.
6. **UTF-8 explicit** in every `open()`; no platform-default encodings
   (Windows lesson).
7. **No component returns empty on failure** — errors re-raise or emit
   structured failure. An empty result that means "the check could not run" is
   indistinguishable from "the check found nothing", and that ambiguity is the
   bug.
8. **Names carry the token:** files `keel_*.py` / `keel-*.md`, environment
   `KEEL_*`, commands `/keel:*`, directories `.keel/`. Platform-required names
   (`plugin.json`, `hooks.json`, `SKILL.md`, `agents/`, `skills/`) keep their
   canonical spelling.
9. **Docs never state a count by hand** — counts render from source in CI
   (R15, R26).
10. **Comments state constraints, not narration** — the standing house style.

## Plus five

*(This heading said "Plus two" while listing four, and now five. Corrected
2026-09-02 — a count in a heading is a claim like any other.)*

11. **Gates are synchronous; capture and logging are asynchronous** (F11).
    A gate that does not block is not a gate, so gate hooks run inline and the
    session waits for the verdict. Capture, logging, and index maintenance must
    never make the user wait: they are declared `async: true` in `hooks.json`
    and may not emit a decision. Two observers are a deliberate exception and
    run synchronously: `SessionStart` (the castoff block) and, since T473,
    `UserPromptSubmit` (the context nudge) — both emit their content on stdout,
    and stdout IS the context; an async hook's output arrives too late to be
    one.
12. **Failure policy is per guard class, declared in the file's docstring, and
    tested** (R3). Every hook and script states `FAIL-OPEN` or `FAIL-CLOSED`
    in its contract docstring, and a test asserts the declared policy matches
    observed behaviour. The two classes in force today:

    | Class | Policy | Rationale | Example |
    |---|---|---|---|
    | Runtime hooks | FAIL-OPEN | keel observing a session must never break it | `hooks/keel_hook.py` |
    | Build gates | FAIL-CLOSED | a check that cannot run is a failure, never a pass | `scripts/keel_checks.py`, `scripts/keel_gen_hooks.py` |
    | Enforcement gates | FAIL-CLOSED WHEN ARMED, FAIL-OPEN WHEN UNARMED | a guard that cannot evaluate must not pretend it approved — but a project that never armed keel must not be broken by keel's own bug | `hooks/keel_gate.py`, `hooks/keel_stop.py` |

    Mixing policies inside one class is the defect (R3): a guard that fails
    open while its siblings fail closed disappears silently on the one machine
    that lacks its prerequisite, and nothing says so.

13. **A deliberate corner cut inside completed work is marked at the site it
    was cut**, in whatever comment syntax the file uses, with
    `keel:deferred(ceiling=<what breaks or runs out>; trigger=<the observable
    event that demands the upgrade>)`. Both fields are required — a ceiling
    with no trigger is a corner that stays cut forever, because nothing ever
    fires the upgrade. `keel debt` harvests every marker in the tracked tree
    into one report.

14. **An edit to a gate module lands as ONE write that leaves the module
    importable, and the gate is exercised before the next edit.** The gate is
    recompiled from its source on every tool call, so a half-applied edit to
    `hooks/keel_gate.py`, `hooks/keel_stop.py`, `hooks/keel_hook.py` or any
    module they import does not fail later — it fails on the NEXT tool call,
    and under the 2026-08-21 ruling that a crash is a deny that names itself,
    an
    armed project then denies every write and every shell call, including the
    repair. So: fewest edits, each one complete in itself, and after every one
    an import check plus one live gated call before touching anything else. A
    multi-location change is one write of the whole file, never two writes with
    a broken state between them; if an edit fails, the file is restored from
    git before the next attempt. Two pending half-edits are never acceptable.

    MEASURED, not advisory: three freezes on 2026-08-19, and one on 2026-08-21
    written up from inside itself in the maintainer's own session records
    — a single f-string split
    across two edits in an observer module froze a whole project's gates. Every
    executor brief that touches a gate cites this convention, and the
    launcher's own refusal sentence
    (`hooks/keel_hook.py:LAUNCHER_CANNOT_DECIDE`) states it to whoever is
    reading the deny.

15. **A change that adds or alters a guard carries a MUTATION PROOF**: the guard
    is broken on purpose, on the real file, and observed to fail. A test that
    stays green while the thing it guards is broken is not guarding anything,
    and nothing else in a green suite will tell you which of its tests are
    hollow.

    Four properties, from the ratified 2026-09-02 ruling that a guard is
    proven by breaking it: the
    mutation is applied to the REAL artefact rather than a copy; the restore
    sits in a `finally` and is verified, because a proof that can leave the tree
    broken is a hazard dressed as diligence; the observed failure MESSAGE is
    quoted, since a guard that fails while naming the wrong thing is a finding
    of its own; and the mutation is the NARROWEST break the guard should catch,
    because deleting a whole function proves little while the interesting
    mutations leave every visible signal intact.

    Prefer the permanent form where one exists. A both-directions pair — a
    planted violation reported, the same line carrying its declared exemption
    not reported — is a mutation proof kept in the suite instead of run once by
    hand, and it re-runs forever.

    MEASURED, not advisory: three guards in this repository passed review while
    hollow between 1 and 2 September 2026 — a check that certified a tree it
    never read, a check registered and never dispatched (eight PASS lines at a
    real exit 0), and a test whose blind spot two sessions had described wrongly
    until one mutation settled it in fourteen seconds. The limit is stated in
    the record: a passing mutation proof shows a test CAN fail, never that it
    fails for the right reason.

## How these are enforced, not merely written

- Conventions 1 and 12: the docstring declaration is asserted by
  `tests/test_keel_phase0.py` and, for the enforcement gates in both
  directions, by `tests/test_keel_kernel.py`.
- Convention 2: `tests/test_keel_kernel.py` fails if either guard's fixture
  directory carries no allow-cases.
- Convention 4: no keel code passes payload values to a shell; the shell
  strings in the repository (`hooks/hooks.json`, generated by
  `scripts/keel_gen_hooks.py`) contain no payload data.
- Convention 6: every `open()` and every `read_text()` in the repository names
  its encoding.
- Convention 9 and the zero-dependency, no-symlink rules: `scripts/keel_checks.py`,
  run on all three operating systems by `.github/workflows/keel-ci.yml`.
- Convention 14: `tests/test_keel_crash_deny_t236.py` drives real crashes
  through the real launcher and asserts the ruled outcome for each, and
  `keel doctor` reports the crash-deny count per session so a violation shows
  up as a number rather than as a story.
