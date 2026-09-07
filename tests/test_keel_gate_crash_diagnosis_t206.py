#!/usr/bin/env python3
"""T206 - a broken arming file reaches the crash path instead of the honest one.

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module. Every case builds its own fixture
          project under a temporary directory, so no assertion here depends on
          the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED AGAINST A TARGET INSIDE THIS REPOSITORY, the
          rule ``tests/test_keel_gate_self_preflight_t179.py`` states and for
          the same reason: a gate evaluated against a real target appends a
          real line to this project's own audit log, and the log is evidence.
Argv    : none.

The defect, as T205's audit found it
-------------------------------------
Five ``GateError`` raises escape ``evaluate`` uncaught: ``policy_tier`` (an
arming file that exists but will not read, or whose frontmatter is malformed)
and ``policy_body`` (the read fails after ``policy_present`` already confirmed
the file), both reached on every governed write - including one that targets
nothing but the session's own ledger, before the bootstrap carve-out in
``_evaluate_write`` ever runs; and ``plan_ttl_minutes`` (``KEEL_PLAN_TTL_MIN``
set to a non-numeric value), reached on every write that is not a pure ledger
write and on every command. All five used to land on ``_cannot_evaluate``
without the honest diagnosis T179 built for exactly this case:

* A LEDGER WRITE during a broken arming file was ALLOWED (correctly - the
  carve-out's permission is not in question) with a generic, uninformative
  message on both the stderr notice and the ``crash_ledger_write`` audit
  line - the fault that T179's ``policy_parse_fault`` could have named went
  unnamed on the one write the gate still lets through.
* A non-ledger write or command during a malformed ``KEEL_PLAN_TTL_MIN`` was
  DENIED with ``cannot_evaluate_message``'s third shape - "THE ARMING FILE IS
  NOT THE FAULT ... keel could not attribute the fault to its own source
  either" - which is true as far as it goes but never names the one thing
  that actually IS wrong: an operator's environment variable.

THE FIX reuses the classifiers T179 and T204 already built
(``policy_parse_fault``, ``gate_self_fault``) rather than inventing a new
message path, and adds exactly one same-shaped sibling, ``plan_ttl_fault``,
for the one ``GateError`` source that was not a file read. Both the deny path
(``cannot_evaluate_message``) and the ledger carve-out's allow path
(``_permit_crash_ledger_write``) now ask the same classifier,
``_crash_fault_label``, so the two can never describe one crashed evaluation
two different ways.

What this covers, clause by clause
-----------------------------------
1. THE HONEST PATH, NOT THE CRASH PATH (accept 1).
   ``TestABrokenArmingFileIsNamedEvenOnTheLedgerCarveOut``.
2. THE PERMISSION IS UNCHANGED (accept 2), verified by test rather than by
   reading, on the two scenarios this task's fix actually touches:
   ``TestTheLedgerPermissionDoesNotRegress``.
3. A MALFORMED ENVIRONMENT VARIABLE NAMES ITSELF (accept 3).
   ``TestAMalformedTTLNamesTheVariable``.
4. THE AUDIT LINE DISTINGUISHES THE REPAIR OWED (accept 4).
   ``TestTheAuditLineNamesTheKindOfRepair``.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails the check rather
than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402
import keel_gate  # noqa: E402

#: A session id of this file's own, so no real ledger can satisfy a fixture.
SESS8 = "cafe1206"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: An ordinary source target: nothing locks it, so only a rule can refuse it.
ORDINARY_RELPATH = "src/app.py"

#: The arming file spelling, as the refusal message would name it.
POLICY_RELPATH = ".keel/keel-policy.md"


def armed(project: Path, *, tier: int = 2) -> Path:
    """A fixture project whose arming file declares ``tier`` and parses."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n",
        encoding="utf-8",
    )
    return project


def unparseable(project: Path) -> Path:
    """A fixture project whose arming file is PRESENT and does not parse.

    Frontmatter with no ``tier:`` - the same shape
    ``tests/fixtures/gate/20-unreadable-tier-fails-closed.json`` ships and
    ``tests/test_keel_gate_self_preflight_t179.py`` builds, so all three agree
    about what a genuine configuration fault looks like.
    """
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\nname: broken-fixture\n---\n\n# frontmatter without a tier\n",
        encoding="utf-8",
    )
    return project


def write_event(cwd: Path, *paths: str) -> keel_events.KeelEvent:
    """One ``pre_write`` event, from ``cwd``, naming one or more targets."""
    return keel_events.KeelEvent(
        kind="pre_write",
        cwd=cwd,
        session_id=SESSION,
        tool_name="Write",
        raw={"tool_input": {"file_path": paths[0], "content": "x = 1\n"}},
        file_paths=tuple(paths),
    )


def ledger_relpath(sess8: str = SESS8) -> str:
    """This session's ledger, project-relative, as the harness would name it."""
    return f".keel/plans/keel-plan-{sess8}.md"


def run_quietly(
    event: keel_events.KeelEvent, env: dict | None = None
) -> tuple[keel_events.KeelVerdict, str]:
    """``run`` with stderr captured - the notices are asserted, not printed."""
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        verdict = keel_gate.run(event, env={} if env is None else env)
    return verdict, buffer.getvalue()


def audit_lines(project: Path) -> list[dict]:
    """Every parsed audit line of a fixture project, oldest first."""
    path = project / ".keel" / "audit" / "keel-audit.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@contextmanager
def missing_symbol(name: str) -> Iterator[None]:
    """A gate whose module state is inconsistent, then restored - the same
    fixture ``tests/test_keel_gate_self_preflight_t179.py`` uses for a
    genuine, call-time self-fault rather than a simulated one."""
    original = getattr(keel_gate, name)
    delattr(keel_gate, name)
    try:
        yield
    finally:
        setattr(keel_gate, name, original)


class TestABrokenArmingFileIsNamedEvenOnTheLedgerCarveOut(unittest.TestCase):
    """Accept 1. A malformed arming file is reached on ``policy_tier`` before
    ``_evaluate_write``'s bootstrap carve-out ever runs, even for a write that
    names nothing but the session's own ledger - so the crash carve-out's
    ALLOW is what T206 must make honest. FAILS against the code before this
    task: the old message named neither the file nor its reason."""

    def test_the_stderr_notice_names_the_file_and_the_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            _verdict, err = run_quietly(write_event(project, ledger_relpath()))
        self.assertIn("THE ARMING FILE IS THE FAULT", err)
        self.assertIn("frontmatter declares no tier", err)

    def test_the_decision_is_still_allow(self) -> None:
        """The diagnosis changed; the permission did not (accept 2, restated
        here because it is the fact that makes the notice above safe to add)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            verdict, _err = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "internal_error_ledger")

    def test_an_unreadable_frontmatter_is_named_too(self) -> None:
        """The second raise site (T205's audit): the frontmatter block is
        opened but never closed, a different ``GateError`` than "no tier"."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "---\ntier: 2\n\n# the closing --- is missing\n", encoding="utf-8"
            )
            _verdict, err = run_quietly(write_event(project, ledger_relpath()))
        self.assertIn("THE ARMING FILE IS THE FAULT", err)
        self.assertIn("never closed", err)


class TestTheLedgerPermissionDoesNotRegress(unittest.TestCase):
    """Accept 2, verified by test rather than by reading, on both fault shapes
    this task's fix touches. Reinstating the freeze this project suffered
    three times on 2026-08-19 is the one outcome this task must not produce."""

    def test_a_broken_arming_file_still_leaves_the_ledger_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            source, _e1 = run_quietly(write_event(project, ORDINARY_RELPATH))
            ledger, _e2 = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(source.decision, "deny")
        self.assertEqual(ledger.decision, "allow")
        self.assertEqual(ledger.to_exit_code(), 0)
        self.assertEqual(ledger.gate, "internal_error_ledger")

    def test_keels_own_module_fault_still_leaves_the_ledger_writable(self) -> None:
        """The OTHER fault kind ``_crash_fault_label`` can name - keel's own
        module state - must reach the identical carve-out, unaffected by the
        classifier this task added alongside it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol("announce_ungoverned_targets"):
                verdict, err = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "internal_error_ledger")
        self.assertIn("LEDGER WRITE PERMITTED THROUGH A FAILED GATE", err)


class TestAMalformedTTLNamesTheVariable(unittest.TestCase):
    """Accept 3. FAILS against the code before this task: the old third shape
    said "THE ARMING FILE IS NOT THE FAULT ... keel could not attribute the
    fault to its own source either", never naming ``KEEL_PLAN_TTL_MIN`` as the
    operator configuration error it is."""

    def test_the_denial_names_the_variable_and_its_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, _err = run_quietly(
                write_event(project, ORDINARY_RELPATH),
                env={"KEEL_PLAN_TTL_MIN": "not-a-number"},
            )
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("FAILED CLOSED", verdict.reason)
        self.assertIn("KEEL_PLAN_TTL_MIN", verdict.reason)
        self.assertIn("THIS SESSION'S ENVIRONMENT IS THE FAULT", verdict.reason)

    def test_it_is_never_reported_as_the_arming_file_or_as_keel_breaking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, _err = run_quietly(
                write_event(project, ORDINARY_RELPATH),
                env={"KEEL_PLAN_TTL_MIN": "not-a-number"},
            )
        self.assertNotIn(POLICY_RELPATH, verdict.reason)
        self.assertNotIn("THE ARMING FILE IS NOT THE FAULT", verdict.reason)
        self.assertNotIn("could not attribute the fault to its own source", verdict.reason)
        self.assertNotIn("THE FAULT IS KEEL'S OWN", verdict.reason)

    def test_a_broken_arming_file_is_still_named_ahead_of_the_environment(self) -> None:
        """When both are broken, the file - the more fixable of the two for
        most adopters - is named first; shape 2 stays intact."""
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            verdict, _err = run_quietly(
                write_event(project, ORDINARY_RELPATH),
                env={"KEEL_PLAN_TTL_MIN": "not-a-number"},
            )
        self.assertIn("THE ARMING FILE IS THE FAULT", verdict.reason)
        self.assertNotIn("THIS SESSION'S ENVIRONMENT IS THE FAULT", verdict.reason)


class TestTheAuditLineNamesTheKindOfRepair(unittest.TestCase):
    """Accept 4. The record says which kind of repair is owed: keel's own
    source (a module defect) or the adopter's project (configuration or file
    state) - never a guess when neither could be shown."""

    def test_a_broken_arming_file_is_a_configuration_fault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            run_quietly(write_event(project, ledger_relpath()))
            lines = audit_lines(project)
        crash_lines = [line for line in lines if line.get("event") == "crash_ledger_write"]
        self.assertEqual(len(crash_lines), 1)
        self.assertEqual(crash_lines[0]["detail"]["fault_kind"], "configuration")

    def test_keels_own_module_fault_is_a_module_fault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol("announce_ungoverned_targets"):
                run_quietly(write_event(project, ledger_relpath()))
            lines = audit_lines(project)
        crash_lines = [line for line in lines if line.get("event") == "crash_ledger_write"]
        self.assertEqual(len(crash_lines), 1)
        self.assertEqual(crash_lines[0]["detail"]["fault_kind"], "module")


if __name__ == "__main__":  # pragma: no cover - manual runs only
    unittest.main()
