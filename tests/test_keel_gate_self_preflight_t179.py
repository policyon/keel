#!/usr/bin/env python3
"""T179 - what the gate does when it CANNOT evaluate.

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module. Every gated case builds its own
          fixture project under a temporary directory, so no assertion here
          depends on the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED AGAINST A TARGET INSIDE THIS REPOSITORY, the
          same rule ``tests/test_keel_target_arming_t178.py`` states and for
          the same reason: evaluating the gate on a target under a declared
          ``workshop:`` prefix appends a real line to this project's own audit
          log, and the audit log is evidence.
Argv    : none.

The defect, as the freezes produced it
--------------------------------------
Three times on 2026-08-19 an edit to ``hooks/keel_gate.py`` left the gate
unable to evaluate. It failed closed, which is correct (R3), and then said:
"this project is armed and the gate could not evaluate the request. Fix
.keel/keel-policy.md or set KEEL_GATE=off deliberately." The arming file had
parsed cleanly every time. Two consequences, and this file asserts both:

* THE BLAME WAS WRONG. The only agent that could have helped was pointed at
  the one file that was not broken.
* THE RECORD FROZE. A ledger write is a write, so the session could not even
  record that it was stuck, and stop-with-accounting then demanded accounting
  the same fault forbade.

THE FIXTURE FOR AN UNEVALUABLE GATE, and why there are two of them: the
recorded freezes were call-time faults, so a check that the module still
IMPORTS proves nothing about them (the lesson recorded as
``a-module-that-imports-is-not-a-gate-that-evaluates``). Both fixtures remove
a symbol from the live module and put it back afterwards.

* ``missing_symbol("_evaluate_write")`` removes a name the PREFLIGHT knows
  about, so the fault is caught BEFORE ``evaluate`` is entered.
* ``missing_symbol(CALL_SITE_SYMBOL)`` removes one it does not, so
  ``evaluate`` raises a genuine ``NameError`` at the real call line inside
  ``hooks/keel_gate.py`` - freeze cause 2 exactly, reproduced rather than
  simulated - and ``gate_self_fault`` is what has to recognise it.
  ``test_the_fixture_really_makes_the_gate_unevaluable`` asserts that the
  fixture DOES break evaluation, because the first draft of this file deleted
  ``is_armed`` - a symbol no ordinary write event reaches - and every
  assertion built on it passed against a gate that was working perfectly.

What this covers, clause by clause
----------------------------------
1. SELF-PREFLIGHT (accept 1). ``TestThePreflightSeesItsOwnModule`` and
   ``TestTheFaultIsAttributedToKeel``.
2. HONEST REMEDIATION (accept 2). ``TestTheInnocentFileIsNotBlamed``: the
   string ``.keel/keel-policy.md`` does not appear in the refusal when that
   file parsed cleanly, and DOES appear, with the reason, when it did not.
3. THE RECORD SURVIVES (accept 3). ``TestTheLedgerStaysWritable``.
4. SCOPE AS A LIMIT (accept 4). ``TestTheCarveOutIsNotWidened`` - one
   directory, ``pre_write`` only, every target or none, unverifiable still
   denied, and the loosening declared in the module docstring.

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
import os
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
SESS8 = "cafe1179"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: An ordinary source target: nothing locks it, so only a rule can refuse it.
ORDINARY_RELPATH = "src/app.py"

#: The arming file spelling, as the refusal message would name it.
POLICY_RELPATH = ".keel/keel-policy.md"

#: THE SYMBOL THE CALL-TIME FIXTURE REMOVES. It must be one ``evaluate``
#: reaches on EVERY event and one the preflight does NOT pin, or the fixture
#: reproduces nothing: ``announce_ungoverned_targets`` is called
#: unconditionally once ``governance`` has answered, for both event kinds, and
#: nothing on the failure path or in the ledger carve-out needs it - so the
#: crash it causes is the freeze shape and not a second, unrelated fault.
CALL_SITE_SYMBOL = "announce_ungoverned_targets"


def armed(project: Path, *, tier: int = 2, body: str = "") -> Path:
    """A fixture project whose arming file declares ``tier`` and parses."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    text = f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n\n{body}"
    (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")
    return project


def unparseable(project: Path) -> Path:
    """A fixture project whose arming file is PRESENT and does not parse.

    Frontmatter with no ``tier:`` - the shape
    ``tests/fixtures/gate/20-unreadable-tier-fails-closed.json`` ships, so the
    two agree about what a genuine configuration fault looks like.
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


def exec_event(cwd: Path, command: str) -> keel_events.KeelEvent:
    """One ``pre_exec`` event, from ``cwd``, carrying command text."""
    return keel_events.KeelEvent(
        kind="pre_exec",
        cwd=cwd,
        session_id=SESSION,
        tool_name="Bash",
        raw={"tool_input": {"command": command}},
        command=command,
    )


def ledger_relpath(sess8: str = SESS8) -> str:
    """This session's ledger, project-relative, as the harness would name it."""
    return f".keel/plans/keel-plan-{sess8}.md"


@contextmanager
def missing_symbol(name: str) -> Iterator[None]:
    """The fixture: a gate whose module state is inconsistent, then restored.

    This is the half-applied edit in the only form a test can hold - a symbol
    deleted while call sites still name it. It is put back in ``finally`` even
    when the assertion fails, or every later test in the suite would run
    against a broken gate and the run would say nothing useful.
    """
    original = getattr(keel_gate, name)
    delattr(keel_gate, name)
    try:
        yield
    finally:
        setattr(keel_gate, name, original)


def run_quietly(event: keel_events.KeelEvent) -> tuple[keel_events.KeelVerdict, str]:
    """``run`` with stderr captured - the notices are asserted, not printed.

    ``env={}`` throughout: no kill switch may colour a result here, and the
    switch has its own test.
    """
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        verdict = keel_gate.run(event, env={})
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


class TestThePreflightSeesItsOwnModule(unittest.TestCase):
    """Accept 1. The gate asks whether IT is the broken thing, before it asks
    anything of the project."""

    def test_a_clean_module_passes_the_preflight(self) -> None:
        self.assertEqual(keel_gate.module_preflight(), ())

    def test_every_pinned_symbol_exists(self) -> None:
        """The preflight is a list of literal names, so a rename must fail HERE
        rather than quietly leave the check inspecting nothing."""
        for name in keel_gate.EVALUATION_PATH_SYMBOLS + keel_gate.KERNEL_SYMBOLS:
            with self.subTest(name=name):
                self.assertTrue(
                    callable(getattr(keel_gate, name, None)),
                    f"{name} is pinned by the preflight but is not a callable "
                    f"of hooks/keel_gate.py",
                )

    def test_a_deleted_symbol_is_reported_by_name(self) -> None:
        with missing_symbol("_evaluate_write"):
            faults = keel_gate.module_preflight()
        self.assertTrue(faults)
        self.assertIn("_evaluate_write", " ".join(faults))

    def test_a_symbol_that_is_not_callable_is_reported_too(self) -> None:
        """A half-applied edit can leave a name BOUND to the wrong thing, which
        binds fine and fails at the call."""
        original = keel_gate.governance
        keel_gate.governance = "not a function"  # type: ignore[assignment]
        try:
            faults = keel_gate.module_preflight()
        finally:
            keel_gate.governance = original
        self.assertTrue(faults)
        self.assertIn("governance", " ".join(faults))

    def test_the_preflight_never_raises(self) -> None:
        """Its own failure would be caught by the handler it exists to inform,
        and reported as an evaluation crash instead of as what it is."""
        original = keel_gate.EVALUATION_PATH_SYMBOLS
        keel_gate.EVALUATION_PATH_SYMBOLS = 7  # type: ignore[assignment]
        try:
            faults = keel_gate.module_preflight()
        finally:
            keel_gate.EVALUATION_PATH_SYMBOLS = original
        self.assertTrue(faults)
        self.assertIn("preflight itself", " ".join(faults))


class TestTheFaultIsAttributedToKeel(unittest.TestCase):
    """Accept 1 and 2. The message names the real defect - the classifier is
    what tells keel's own inconsistency from the adopter's file."""

    def test_the_fixture_really_makes_the_gate_unevaluable(self) -> None:
        """THE BEFORE HALF, and it is not ceremony: every assertion in this file
        is vacuous unless the fixture genuinely stops the gate deciding. It also
        shows why importability is not the check - the module imports perfectly
        and ``evaluate`` is still callable while this fault is live."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            event = write_event(project, ORDINARY_RELPATH)
            with missing_symbol(CALL_SITE_SYMBOL):
                self.assertTrue(callable(keel_gate.evaluate))
                with self.assertRaises(NameError):
                    keel_gate.evaluate(event, env={})
            self.assertEqual(keel_gate.evaluate(event, env={}).gate, "plan")

    def test_a_preflight_fault_denies_and_names_keel(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol("_evaluate_write"):
                verdict, err = run_quietly(write_event(project, ORDINARY_RELPATH))
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.to_exit_code(), 2)
        self.assertIn("FAILED CLOSED", verdict.reason)
        self.assertIn("THE FAULT IS KEEL'S OWN", verdict.reason)
        self.assertIn("_evaluate_write", verdict.reason)
        self.assertIn("KEEL'S OWN", err)

    def test_a_call_time_nameerror_is_recognised_as_keels_own(self) -> None:
        """Freeze cause 2, reproduced: a symbol deleted while a call site still
        names it, raising from inside ``hooks/keel_gate.py`` at the real line.
        Nothing about a NameError's TYPE says whose fault it is - the site does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("THE FAULT IS KEEL'S OWN", verdict.reason)
        self.assertIn("NameError", verdict.reason)
        self.assertIn("keel_gate.py:", verdict.reason)

    def test_the_repair_named_is_the_one_that_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
        self.assertIn("restored from git", verdict.reason)
        self.assertIn("ONE write of the complete file", verdict.reason)

    def test_a_gateerror_is_the_project_and_never_keel(self) -> None:
        """The gate raises ``GateError`` deliberately when it cannot read the
        project's configuration, so it may never be classified as keel's own
        state - that direction hides the one thing the adopter can fix."""
        self.assertEqual(keel_gate.gate_self_fault(keel_gate.GateError("no tier")), "")

    def test_a_data_valueerror_is_not_a_self_fault(self) -> None:
        """``int('abc')`` on a malformed tier is a ``ValueError`` about the
        adopter's file. Only the structural unpacking shape counts."""
        try:
            int("abc")
        except ValueError as exc:
            self.assertEqual(keel_gate.gate_self_fault(exc), "")
        else:  # pragma: no cover - int('abc') raises
            self.fail("int('abc') did not raise")

    def test_an_unpacking_valueerror_is_a_self_fault(self) -> None:
        """Freeze cause 1: a return value added without updating an unpacking
        site. The type is shared with data faults, so the message decides."""
        exc = ValueError("too many values to unpack (expected 2)")
        exc.__traceback__ = self._traceback_inside_keel()
        self.assertIn("unpack", keel_gate.gate_self_fault(exc))

    def test_a_fault_with_no_keel_frame_is_not_attributed_to_keel(self) -> None:
        """Site alone is not enough, and neither is type alone: a structural
        type raised nowhere near keel's source is not keel's defect."""
        self.assertEqual(keel_gate.gate_self_fault(TypeError("from elsewhere")), "")

    def _traceback_inside_keel(self):
        """A traceback whose innermost frame is inside ``hooks/keel_gate.py``.

        Raised through the gate's own module so the frame is genuine rather
        than fabricated: ``fault_site`` reads ``co_filename``, and a test that
        handed it a made-up string would prove nothing about the real read.
        """
        try:
            keel_gate.plan_ttl_minutes({"KEEL_PLAN_TTL_MIN": "not a number"})
        except Exception as exc:  # noqa: BLE001 - the traceback is the fixture
            return exc.__traceback__
        return None  # pragma: no cover - a non-numeric TTL always raises


class TestTheInnocentFileIsNotBlamed(unittest.TestCase):
    """Accept 2, as the assertion the freeze needed. The old message named
    ``.keel/keel-policy.md`` unconditionally; the new one names it only when
    that file genuinely will not parse."""

    def _refusal(self, project: Path, symbol: str = CALL_SITE_SYMBOL) -> str:
        with missing_symbol(symbol):
            verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
        return verdict.reason

    def test_a_clean_arming_file_is_never_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            reason = self._refusal(project)
        self.assertNotIn(POLICY_RELPATH, reason)

    def test_a_clean_arming_file_is_not_named_on_the_preflight_path_either(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            reason = self._refusal(project, symbol="_evaluate_write")
        self.assertNotIn(POLICY_RELPATH, reason)

    def test_a_fault_keel_cannot_attribute_says_the_file_is_not_at_fault(self) -> None:
        """The third shape: not keel's own source, and the arming file parses.
        Staying silent about it is what let the old sentence be assumed."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            original = keel_gate.evaluate

            def boom(*_a: object, **_k: object) -> keel_events.KeelVerdict:
                raise RuntimeError("deliberate fault")

            keel_gate.evaluate = boom
            try:
                verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
            finally:
                keel_gate.evaluate = original
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("FAILED CLOSED", verdict.reason)
        self.assertIn("THE ARMING FILE IS NOT THE FAULT", verdict.reason)
        self.assertNotIn(POLICY_RELPATH, verdict.reason)

    def test_a_broken_arming_file_IS_named_with_the_reason(self) -> None:
        """The other direction, which a fix of this shape breaks: when the file
        really is the fault, it must still be named - and now with the reason,
        which the old message never carried."""
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("FAILED CLOSED", verdict.reason)
        self.assertIn(POLICY_RELPATH, verdict.reason)
        self.assertIn("THE ARMING FILE IS THE FAULT", verdict.reason)
        self.assertIn("declares no tier", verdict.reason)

    def test_the_double_fault_does_not_claim_the_project_is_armed(self) -> None:
        """``failure_policy_roots`` returns the session's own directory for a
        path keel could not attribute, which is NOT a project shown to be
        armed. The old sentence said it was."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = "d/" * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2) + "app.py"
            target = root / deep
            target.parent.mkdir(parents=True, exist_ok=True)
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(write_event(root, str(target)))
        self.assertEqual(verdict.decision, "deny")
        self.assertNotIn("This project is armed", verdict.reason)
        self.assertIn("could not attribute this path", verdict.reason)


class TestTheLedgerStaysWritable(unittest.TestCase):
    """Accept 3. A crash may not freeze ``.keel/plans/``: it is the only place
    the session can write down that it is stuck, and stop-with-accounting then
    demands accounting the same fault forbids. Source stays refused."""

    def test_the_ledger_is_allowed_while_source_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                source, _e1 = run_quietly(write_event(project, ORDINARY_RELPATH))
                ledger, err = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(source.decision, "deny")
        self.assertEqual(ledger.decision, "allow")
        self.assertEqual(ledger.to_exit_code(), 0)
        self.assertEqual(ledger.gate, "internal_error_ledger")
        self.assertIn("LEDGER WRITE PERMITTED THROUGH A FAILED GATE", err)

    def test_the_allow_says_the_contract_was_not_asserted(self) -> None:
        """Rule 3's assertion could not run. The write is permitted, not
        blessed, and a reader of either channel is told which."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, err = run_quietly(write_event(project, ledger_relpath()))
        self.assertIn("NOT asserted", verdict.reason + err)

    def test_the_carve_out_is_on_the_audit_record(self) -> None:
        """A loosening nobody can count is a loosening nobody will notice, so
        it gets its own event kind rather than borrowing ``gate_block``."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                run_quietly(write_event(project, ledger_relpath()))
            lines = audit_lines(project)
        kinds = [line.get("event") for line in lines]
        self.assertIn("crash_ledger_write", kinds)

    def test_the_refusal_tells_the_session_the_ledger_is_still_open(self) -> None:
        """A refusal that cannot be acted on is a dead end. The one action that
        IS available is named in the refusal itself."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(write_event(project, ORDINARY_RELPATH))
        self.assertIn(".keel/plans/ is still writable", verdict.reason)

    def test_the_preflight_path_keeps_the_ledger_open_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            with missing_symbol("_evaluate_write"):
                verdict, _err = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "internal_error_ledger")

    def test_a_broken_arming_file_does_not_freeze_the_ledger_either(self) -> None:
        """The bootstrap reasoning does not depend on WHY evaluation failed."""
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            verdict, _err = run_quietly(write_event(project, ledger_relpath()))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "internal_error_ledger")


class TestTheCarveOutIsNotWidened(unittest.TestCase):
    """Accept 4. This LOOSENS a fail-closed path for exactly one directory, so
    every clause of the limit is an assertion. Nothing here reads as permission
    for any other path."""

    def _denied(self, event: keel_events.KeelEvent) -> None:
        with missing_symbol(CALL_SITE_SYMBOL):
            verdict, _err = run_quietly(event)
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "internal_error")

    def test_the_audit_log_is_not_carved_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(write_event(project, ".keel/audit/keel-audit.jsonl"))

    def test_the_arming_file_is_not_carved_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(write_event(project, POLICY_RELPATH))

    def test_a_lookalike_directory_is_not_carved_out(self) -> None:
        """A segment test, not a prefix one: ``.keel/plansomething`` is not the
        ledger directory and neither is ``plans/`` at the project root."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(write_event(project, ".keel/plansomething/x.md"))
            self._denied(write_event(project, "plans/x.md"))

    def test_one_source_target_refuses_the_whole_write(self) -> None:
        """Every target or none, so a ledger path cannot carry a neighbour."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(write_event(project, ledger_relpath(), ORDINARY_RELPATH)
            )

    def test_a_command_is_never_carved_out(self) -> None:
        """keel cannot tell what else a shell line does, so the half it cannot
        verify stays refused - even when the line names only the ledger."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(exec_event(project, f"echo x >> {ledger_relpath()}"))

    def test_a_target_that_will_not_resolve_is_still_denied(self) -> None:
        """UNVERIFIABLE IS DENY, unchanged: a path keel cannot resolve is not a
        ledger path, whatever it is spelled like."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            self._denied(write_event(project, ".keel/plans/\x00bad.md"))

    def test_an_empty_payload_is_not_a_carve_out(self) -> None:
        """A write naming no target at all must not fall through the hole."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=SESSION,
                tool_name="Write",
                file_paths=(),
            )
            self.assertEqual(keel_gate.crash_ledger_carve_out(event), "")

    def test_the_two_ledger_readers_agree(self) -> None:
        """``is_ledger_path`` may not depend on the project walk, since the walk
        may be what failed - so it is a second reader, and a second reader that
        DISAGREED with ``is_plan_target`` would be a hole of its own."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(os.path.realpath(str(Path(tmp) / "project")))
            (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
            for relpath in (
                ledger_relpath(),
                ".keel/plans/",
                ".keel/plans/nested/deep.md",
                ".keel/plansomething/x.md",
                ".keel/audit/keel-audit.jsonl",
                POLICY_RELPATH,
                ORDINARY_RELPATH,
                "plans/x.md",
            ):
                target = keel_gate.norm(project, relpath)
                with self.subTest(relpath=relpath):
                    self.assertEqual(
                        keel_gate.is_ledger_path(target),
                        keel_gate.is_plan_target(project, target),
                    )

    def test_the_loosening_is_declared_where_the_policy_is_declared(self) -> None:
        """Declared versus observed, the discipline ``tests/test_keel_kernel.py``
        keeps for the two directions: a fail-closed path with an exception the
        docstring does not mention is a misleading declaration."""
        doc = keel_gate.__doc__ or ""
        self.assertIn("FAIL-CLOSED WHEN ARMED", doc)
        self.assertIn("FAIL-OPEN WHEN UNARMED", doc)
        self.assertIn(".keel/plans/", doc)
        self.assertIn("NOT TO BE", doc)

    def test_the_kill_switch_still_answers_a_broken_module(self) -> None:
        """Every refusal offers ``KEEL_GATE=off``; a preflight fault that
        ignored the switch would make that sentence a lie, and the switch is
        the only door left when the gate's own module is the broken thing."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            buffer = io.StringIO()
            with missing_symbol("_evaluate_write"), redirect_stderr(buffer):
                verdict = keel_gate.run(
                    write_event(project, ORDINARY_RELPATH), env={"KEEL_GATE": "off"}
                )
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "kill_switch")

    def test_an_unarmed_project_still_fails_open(self) -> None:
        """NO WIDENING in the other direction either: a tool keel was never
        armed in must not be broken by keel's own bug."""
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            loose.mkdir(parents=True, exist_ok=True)
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(write_event(loose, "note.txt"))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.to_exit_code(), 0)


class TestTheHandlerHasItsOwnHandler(unittest.TestCase):
    """The double fault - the gate cannot evaluate AND cannot word the refusal.
    An unhandled traceback reaching the session is the one outcome worse than a
    bad message, so this fails closed with the fewest moving parts left."""

    def test_a_broken_message_builder_still_denies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            original = keel_gate.cannot_evaluate_message

            def boom(*_a: object, **_k: object) -> str:
                raise RuntimeError("the handler is broken too")

            keel_gate.cannot_evaluate_message = boom  # type: ignore[assignment]
            try:
                with missing_symbol(CALL_SITE_SYMBOL):
                    verdict, err = run_quietly(write_event(project, ORDINARY_RELPATH))
            finally:
                keel_gate.cannot_evaluate_message = original
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.to_exit_code(), 2)
        self.assertIn("FAILED CLOSED", verdict.reason)
        self.assertIn("could not word the refusal", verdict.reason)
        self.assertIn("failure policy failed too", err)


if __name__ == "__main__":  # pragma: no cover - manual runs only
    unittest.main()
