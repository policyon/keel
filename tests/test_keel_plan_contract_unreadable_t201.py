#!/usr/bin/env python3
"""T201 - the plan contract when the ledger's own text cannot be established.

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
          real line to this project's audit log, and the log is evidence.
Argv    : none.

The defect, as an isolated reviewer found it
--------------------------------------------
``ledger_text_for_write`` caught every ``OSError`` from reading the current
ledger - a Windows lock, a denied permission, a directory standing where the
file should be - and turned it into ``current = ""``. On an ``Edit`` the
substitution then could not find its ``old_string`` in that emptiness,
``resulting_content`` returned None, and the fallback was the same emptiness
once more. ``check_ledger("")`` finds no tasks, so it returns no findings, and
``plan_contract_verdict`` ALLOWED the write however badly the real file broke
the contract. The guardrail stopped guarding exactly when the file was in a bad
state, and said nothing.

WHAT MAKES THE FIXTURE REAL RATHER THAN SIMULATED, and why that matters here:
``TestTheFixtureReallyIsUnreadable`` puts a DIRECTORY where the ledger should
be, which every supported platform refuses to read as text - ``PermissionError``
on Windows, ``IsADirectoryError`` on POSIX - and asserts that the fault is a
genuine ``OSError`` that is NOT ``FileNotFoundError``. Without that assertion
this whole file could be passing against an absent file, which is a different
and entirely legal state. The lock shape is exercised separately with a raising
``read_text``, because a lock cannot be taken portably in a test.

What this covers, clause by clause
----------------------------------
1. UNREADABLE IS DISTINGUISHED FROM ABSENT (accept 1).
   ``TestAnUnreadableLedgerFailsClosed`` and
   ``TestAnAbsentLedgerStillMeansWhatItMeant``, which is the other half: the
   fix must not turn a normal state into a refusal.
2. ``""`` IS NEVER SUBSTITUTED (accept 2). ``TestNothingIsEverInvented``.
3. THE EDIT PATH (accept 3). ``TestTheEditPathCannotDegradeToEmpty``.
4. THE REFUSAL IS REACHED, NOT MERELY RAISED (accept 4).
   ``TestTheRefusalSurvivesTheCrashPath`` - the raise is caught inside
   ``plan_contract_verdict``, because if it escaped ``evaluate`` the crash
   path's own carve-out would PERMIT the write (T179), turning a refusal into
   an allow.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails the check rather
than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_events  # noqa: E402
import keel_gate  # noqa: E402

#: A session id of this file's own, so no real ledger can satisfy a fixture.
SESS8 = "cafe1201"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: A ledger that meets the contract, and the same ledger after one placeholder
#: has been substituted into it. The pair is what an Edit turns one into.
CLEAN = (
    f"# Session plan - {SESS8}\n\n## Tasks\n\n"
    "- [ ] T1 A task that names both fields.\n"
    "      Route: standard (keel:executor).\n"
    "      Accept: the kernel suite is green.\n"
)
DIRTY = CLEAN.replace("the kernel suite is green.", "TBD.")

#: The arming file spelling, as a refusal message would name it.
POLICY_RELPATH = ".keel/keel-policy.md"


def armed(project: Path) -> Path:
    """A fixture project whose arming file declares tier 2 and parses."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# keel policy - fixture project\n", encoding="utf-8"
    )
    return project


def ledger_relpath() -> str:
    """This session's ledger, project-relative, as the harness would name it."""
    return f".keel/plans/keel-plan-{SESS8}.md"


def unreadable_ledger(project: Path) -> Path:
    """A ledger path that EXISTS and cannot be read as text.

    A directory, because it is the one shape that is genuinely unreadable on
    every platform this project supports without taking a lock or editing an
    access control list from a test. What it stands in for is the Windows lock
    the reviewer named: both arrive as an ``OSError`` that is not
    ``FileNotFoundError``, which is the only distinction the gate draws.
    """
    path = project / ledger_relpath()
    (path / "held-open-by-something-else").mkdir(parents=True, exist_ok=True)
    return path


def written_ledger(project: Path, text: str) -> Path:
    """A ledger that exists, holds ``text``, and reads back normally."""
    path = project / ledger_relpath()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_event(project: Path, tool: str, **payload: Any) -> keel_events.KeelEvent:
    """One ``pre_write`` event naming this session's ledger, with a payload."""
    relative = ledger_relpath()
    return keel_events.KeelEvent(
        kind="pre_write",
        cwd=project,
        session_id=SESSION,
        tool_name=tool,
        raw={"tool_input": {"file_path": relative, **payload}},
        file_paths=(relative,),
    )


def verdict_for(project: Path, event: keel_events.KeelEvent) -> Any:
    """``plan_contract_verdict`` for an event naming this session's ledger."""
    relative = ledger_relpath()
    return keel_gate.plan_contract_verdict(
        event, [(relative, keel_gate.norm(project, relative))]
    )


def text_for(project: Path, event: keel_events.KeelEvent, single: bool = True) -> str:
    """``ledger_text_for_write`` for one event, with its own payload."""
    return keel_gate.ledger_text_for_write(
        project, ledger_relpath(), keel_gate.tool_input_of(event), single
    )


@contextmanager
def read_raises(error: OSError) -> Iterator[None]:
    """The lock shape: every text read fails the way a held file fails.

    Patched rather than staged, and only for the duration of one call: a real
    Windows lock cannot be taken portably, and the point being pinned is the
    gate's handling of the error, not the operating system's production of it.
    """
    with mock.patch.object(Path, "read_text", side_effect=error):
        yield


def run_quietly(event: keel_events.KeelEvent) -> tuple[keel_events.KeelVerdict, str]:
    """``run`` with stderr captured, and ``env={}`` so no switch colours it."""
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        verdict = keel_gate.run(event, env={})
    return verdict, buffer.getvalue()


class TestTheFixtureReallyIsUnreadable(unittest.TestCase):
    """Non-vacuity, first: a fixture that is merely ABSENT proves nothing here.

    The lesson is this project's own - a fixture asserted against sixteen
    passing assertions once turned out not to break the thing it claimed to
    break (``a-module-that-imports-is-not-a-gate-that-evaluates``).
    """

    def test_the_path_exists_and_reading_it_raises_a_non_absent_oserror(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = unreadable_ledger(armed(Path(tmp)))
            self.assertTrue(path.exists(), "the fixture must EXIST, or it is absent")
            with self.assertRaises(OSError) as caught:
                path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIsInstance(
                caught.exception,
                FileNotFoundError,
                "an absent file is a legal state; this fixture must not be one",
            )

    def test_the_lock_shape_is_also_a_non_absent_oserror(self) -> None:
        error = PermissionError(13, "Permission denied")
        self.assertIsInstance(error, OSError)
        self.assertNotIsInstance(error, FileNotFoundError)


class TestAnUnreadableLedgerFailsClosed(unittest.TestCase):
    """Accept 1 and 2: the read fault is named, and the write is refused."""

    def test_the_reader_raises_rather_than_returning_empty_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            with self.assertRaises(keel_gate.LedgerUnestablished) as caught:
                text_for(project, event)
            self.assertIn("read failed", caught.exception.detail)

    def test_an_edit_against_an_unreadable_ledger_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            verdict = verdict_for(project, event)
            self.assertIsNotNone(verdict, "an unreadable ledger must not be allowed")
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan_contract")

    def test_the_message_names_the_read_fault_and_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            reason = verdict_for(project, event).reason
            self.assertIn("read failed", reason)
            self.assertIn("Error", reason, "the exception class is named")
            self.assertIn(ledger_relpath(), reason)
            self.assertIn("NEXT STEP:", reason)

    def test_a_locked_ledger_is_refused_and_the_lock_is_named(self) -> None:
        """The reviewer's own shape: a file keel may not read, not one missing."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, CLEAN)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            with read_raises(PermissionError(13, "Permission denied")):
                verdict = verdict_for(project, event)
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("PermissionError", verdict.reason)
            self.assertIn("Permission denied", verdict.reason)

    def test_the_refusal_does_not_blame_the_arming_file(self) -> None:
        """T179's clause 2, applied to this refusal: the innocent file is not
        named when it parsed cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            self.assertNotIn(POLICY_RELPATH, verdict_for(project, event).reason)

    def test_no_absolute_path_reaches_the_message_or_the_verdict_detail(self) -> None:
        """The fault is named by class and platform words, never by filename:
        the detail dict becomes an audit line."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            verdict = verdict_for(project, event)
            self.assertNotIn(str(project), verdict.reason)
            self.assertNotIn(str(project), repr(verdict.detail))


class TestAnAbsentLedgerStillMeansWhatItMeant(unittest.TestCase):
    """Accept 1's other half. An absent ledger is a NORMAL state with an
    existing meaning - the file a bootstrap write is about to create - and a fix
    that refused it would have broken the only way to satisfy the gate."""

    def test_a_clean_first_write_of_an_absent_ledger_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            event = write_event(project, "Write", content=CLEAN)
            self.assertIsNone(verdict_for(project, event))

    def test_a_dirty_first_write_of_an_absent_ledger_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            event = write_event(project, "Write", content=DIRTY)
            verdict = verdict_for(project, event)
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("placeholder_phrase", verdict.reason)

    def test_a_payload_with_no_content_at_all_is_allowed_as_before(self) -> None:
        """The bootstrap shape fixture 07 ships (plan-write-always-allowed):
        no content key, absent file, and so nothing to assert."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            self.assertEqual(text_for(project, write_event(project, "Write")), "")
            self.assertIsNone(verdict_for(project, write_event(project, "Write")))

    def test_the_absent_read_is_not_reported_as_a_fault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            event = write_event(project, "Write", content=CLEAN)
            self.assertEqual(text_for(project, event), CLEAN)


class TestNothingIsEverInvented(unittest.TestCase):
    """Accept 2, as a rule rather than a case: across every payload shape, a
    read that FAILED never yields text - it yields a refusal."""

    SHAPES: tuple[dict[str, Any], ...] = (
        {},
        {"old_string": "a", "new_string": "b"},
        {"old_string": "a", "new_string": "b", "replace_all": True},
        {"edits": [{"old_string": "a", "new_string": "b"}]},
        {"new_source": "cell"},
    )

    def test_no_payload_shape_gets_text_out_of_a_failed_read(self) -> None:
        for payload in self.SHAPES:
            with self.subTest(payload=sorted(payload)), tempfile.TemporaryDirectory() as tmp:
                project = armed(Path(tmp))
                unreadable_ledger(project)
                event = write_event(project, "Edit", **payload)
                with self.assertRaises(keel_gate.LedgerUnestablished):
                    text_for(project, event)

    def test_a_multi_file_payload_over_an_unreadable_ledger_is_refused(self) -> None:
        """``payload_describes_target`` False took the on-disk fallback, which
        is exactly the path that had no disk to fall back to."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "MultiEdit", content=CLEAN)
            with self.assertRaises(keel_gate.LedgerUnestablished):
                text_for(project, event, single=False)

    def test_a_whole_content_payload_still_decides_by_itself(self) -> None:
        """THE LIMIT ON THIS FIX, stated as a test. A full write's result is the
        payload, so the unreadable file is beside the point - and keeping this
        door open is what keeps the record writable while the file is in a bad
        state (T179's clause 3). The contract is still asserted on the content:
        clean passes, dirty is refused on its findings and not on the read."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            self.assertIsNone(verdict_for(project, write_event(project, "Write", content=CLEAN)))
            verdict = verdict_for(project, write_event(project, "Write", content=DIRTY))
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("placeholder_phrase", verdict.reason)
            self.assertNotIn("read failed", verdict.reason)


class TestTheEditPathCannotDegradeToEmpty(unittest.TestCase):
    """Accept 3. A substitution that cannot be applied must not become a
    verdict about empty content - which is the verdict that checks nothing."""

    def test_an_edit_against_an_absent_ledger_is_refused_with_its_own_door(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            event = write_event(project, "Edit", old_string="a", new_string="b")
            verdict = verdict_for(project, event)
            self.assertIsNotNone(verdict, "an unappliable edit must not read as clean")
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("substitution", verdict.reason)
            self.assertIn("Write payload", verdict.reason)
            self.assertNotIn("read failed", verdict.reason)

    def test_a_multi_edit_against_an_absent_ledger_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            event = write_event(
                project, "MultiEdit", edits=[{"old_string": "a", "new_string": "b"}]
            )
            self.assertEqual(verdict_for(project, event).decision, "deny")

    def test_an_edit_against_an_existing_but_empty_ledger_is_refused(self) -> None:
        """The same emptiness reached the other way: the file is real and holds
        nothing, so there is still no text the substitution could act on."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, "")
            event = write_event(project, "Edit", old_string="a", new_string="b")
            self.assertEqual(verdict_for(project, event).decision, "deny")

    def test_an_edit_that_lands_is_asserted_on_its_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, CLEAN)
            event = write_event(
                project,
                "Edit",
                old_string="      Accept: the kernel suite is green.\n",
                new_string="      Accept: TBD.\n",
            )
            verdict = verdict_for(project, event)
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("placeholder_phrase", verdict.reason)

    def test_an_ambiguous_edit_against_a_real_ledger_still_falls_back_to_disk(self) -> None:
        """THE FALLBACK THIS TASK DID NOT TOUCH, pinned so a later reader does
        not widen the refusal by accident: where there IS on-disk text, checking
        it asserts something TRUE. Clean on disk passes, dirty on disk is
        caught - and neither answer was invented."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, CLEAN)
            event = write_event(project, "Edit", old_string="nowhere", new_string="b")
            self.assertEqual(text_for(project, event), CLEAN)
            self.assertIsNone(verdict_for(project, event))
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, DIRTY)
            event = write_event(project, "Edit", old_string="nowhere", new_string="b")
            self.assertEqual(verdict_for(project, event).decision, "deny")


class TestTheRefusalSurvivesTheCrashPath(unittest.TestCase):
    """Accept 4, and the trap this fix had to avoid: ``.keel/plans/`` is carved
    OUT of the crash path (T179), so a refusal that escaped ``evaluate`` as an
    exception would come back as an ALLOW. It is caught where it is raised."""

    def test_the_gate_denies_end_to_end_and_not_through_the_crash_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            event = write_event(project, "Edit", old_string="a", new_string="b")
            verdict, stderr = run_quietly(event)
            self.assertEqual(verdict.decision, "deny", stderr)
            self.assertEqual(verdict.gate, "plan_contract", stderr)
            self.assertNotIn("FAILED CLOSED", verdict.reason)

    def test_the_two_faults_offer_two_different_doors(self) -> None:
        """One refusal, two repairs: releasing a held file, and using a payload
        that carries content. A single next step would be wrong for one of
        them, which is why the exception carries its own."""
        self.assertNotEqual(
            keel_gate.NEXT_STEP_LEDGER_UNREADABLE, keel_gate.NEXT_STEP_LEDGER_ABSENT_EDIT
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            unreadable_ledger(project)
            held = verdict_for(
                project, write_event(project, "Edit", old_string="a", new_string="b")
            ).reason
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            absent = verdict_for(
                project, write_event(project, "Edit", old_string="a", new_string="b")
            ).reason
        self.assertIn(keel_gate.NEXT_STEP_LEDGER_UNREADABLE, held)
        self.assertIn(keel_gate.NEXT_STEP_LEDGER_ABSENT_EDIT, absent)

    def test_an_ordinary_write_is_untouched_by_any_of_this(self) -> None:
        """Scope, as a limit: nothing here reaches a target that is not a
        session ledger."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp))
            written_ledger(project, CLEAN)
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=SESSION,
                tool_name="Edit",
                raw={"tool_input": {"file_path": "src/app.py", "old_string": "a", "new_string": "b"}},
                file_paths=("src/app.py",),
            )
            self.assertIsNone(
                keel_gate.plan_contract_verdict(
                    event, [("src/app.py", keel_gate.norm(project, "src/app.py"))]
                )
            )


if __name__ == "__main__":
    unittest.main()
