#!/usr/bin/env python3
"""T515 (BL8) - A RECORD IS FILED BY THE PROJECT THE WORK CONCERNS, NEVER BY
WHATEVER DIRECTORY THE SHELL HAPPENED TO BE STANDING IN.

Contract
--------
Reads   : ``hooks/keel_gate.py``, ``hooks/keel_events.py``,
          ``hooks/keel_capture.py`` and ``hooks/keel_session.py`` as modules.
          Every case builds its own fixture projects under a temporary
          directory.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED OR CAPTURED AGAINST A TARGET INSIDE THIS
          REPOSITORY, and that is a rule of this file rather than an accident,
          for the reason ``tests/test_keel_target_arming_t178.py`` states about
          its own: a gate or capture call aimed at a path in this tree APPENDS
          A REAL LINE to ``.keel/audit/keel-audit.jsonl``, and this repository's
          audit log is tracked evidence. THE WHOLE SUBJECT OF THIS FILE is a
          line landing in a log it does not belong in; writing one while
          testing for it would be a joke at the expense of the record.
Argv    : none.

The defect, and why it needed a second task after T178
------------------------------------------------------
Measured 2026-08-27 (session d68e734b) and AGAIN 2026-08-31 (session bc9349b1,
the session that was cutting and verifying keel's own published mirror): ten
refusal lines sat in a sibling repository's working copy, filed there by
sessions whose work was elsewhere. T178 had already re-pointed ARMING at the
target; what T515 finishes is the RECORDING half, and it finishes it in the two
places T178 did not reach:

* ``keel_gate.audit_destination`` fell back to the RAW ``event.cwd`` for the
  three gates that answer before ``governance`` runs (the global rule, the
  installed-kernel rule, ``unresolved_project``). For a session standing in a
  SUBDIRECTORY of an armed project that directory holds no arming file, so
  ``_audit`` found no log and wrote NOTHING - a block with no record.
* ``keel_capture.run`` asked ``project_is_adopted(event.cwd)`` - does THIS
  EXACT DIRECTORY carry ``.keel/`` - and returned 0 when it did not. A session
  started one directory inside its own project recorded NOTHING AT ALL: no
  ``activity``, no ``handoff_start``, no queue line, all session long.

What this covers, clause by clause
----------------------------------
1. ``TestAWriteIntoAnotherProject`` - accept 3. A write into project A from a
   shell sitting in project B is JUDGED by A and RECORDED by A, with B's log
   asserted EMPTY rather than merely "not containing".
2. ``TestTheDestinationOfARefusal`` - accept 4, the clause without which the
   measured shape stays untested. All ten stray lines were refusals, and a
   refusal is written by ``_audit``/``_audit_lock_event``, a different code
   path from the capture hook. Both are pinned here, and both refusal SHAPES
   the mirror actually carries - ``gate_block`` and ``lock_unclassifiable``.
3. ``TestItStillFailsClosed`` - accept 5. Where the target's project cannot be
   ESTABLISHED (the walk exhausted, which is not the same fact as "there is no
   project"), the gate refuses and the recorder writes nothing at all. Neither
   falls through to a permissive answer, and neither invents a ``.keel/``.
4. ``TestTheRecorderResolvesTheSessionsProject`` - accept 2, the sweep. The
   capture hook's own half.
5. ``TestTheSweepIsWiderThanTheGate`` - accept 2's list, checked against the
   code rather than taken from the backlog's word.
6. ``TestTheLauncherFilesTheEventItPromisesNotToLose`` - accept 2 at the LAST
   flat ``.keel/`` test in a writer, and the only one still costing live lines:
   ``keel_hook.cmd_subagent_stop``, sole writer of every ``subagent_stop``.
7. ``TestTheOrdinaryCaseIsByteIdentical`` - the regression this task's own
   first cut introduced and the suite caught: comparing a canonical root
   against a raw ``cwd`` read a session standing in its OWN project as standing
   elsewhere, and rewrote every ``activity`` target from ``src/app.py`` into a
   ``../../..``-plus-home-path spelling of the same file.
"""

from __future__ import annotations

import io
import json
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import keel_capture  # noqa: E402
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_hook  # noqa: E402
import keel_session  # noqa: E402

#: A session id of this file's own, so no fixture ledger can be confused with a
#: real one and no real ledger can ever satisfy a fixture.
SESS8 = "cafe0515"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: A contract-clean ledger, so a case that means to exercise the plan gate is
#: never answered by the plan CONTRACT instead.
LEDGER_TEXT = (
    "# Plan\n\n- [ ] T1 the thing\n      Route: standard (keel:executor).\n"
    "      Accept: it works.\n"
)

#: A target under the policy lock in every project (``PROTECTED_DIRS``), and an
#: ordinary one that only the plan gate can answer for.
LOCKED_RELPATH = "hooks/kernel.py"
ORDINARY_RELPATH = "src/app.py"


def canonical(path: Path) -> str:
    """A path as the gate spells it: resolved, 8.3 components expanded."""
    return str(Path(os.path.realpath(str(path))))


def armed(project: Path, *, tier: int = 2, plan: bool = False) -> Path:
    """A fixture project whose arming file declares ``tier``."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n",
        encoding="utf-8",
    )
    if plan:
        (project / ".keel" / "plans" / f"keel-plan-{SESS8}.md").write_text(
            LEDGER_TEXT, encoding="utf-8"
        )
    return project


def adopted(project: Path) -> Path:
    """A fixture project that carries ``.keel/`` and no arming file at all."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
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


def capture_event(cwd: Path, *paths: str) -> keel_events.KeelEvent:
    """One ``post_tool`` Write event - what the capture hook actually sees."""
    return keel_events.KeelEvent(
        kind="post_tool",
        cwd=cwd,
        session_id=SESSION,
        tool_name="Write",
        file_paths=tuple(paths),
        raw={
            "hook_event_name": "PostToolUse",
            "tool_input": {"file_path": paths[0], "content": "x = 1\n"},
        },
    )


def audit_lines(project: Path) -> list[dict]:
    """Every parsed audit line of a fixture project, oldest first."""
    path = keel_events.audit_path(project)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def gated(event: keel_events.KeelEvent) -> keel_events.KeelVerdict:
    """``keel_gate.run`` with the environment empty and stderr swallowed.

    ``run`` rather than ``evaluate``, and that IS the point of this file: the
    verdict is decided by ``evaluate`` and the LINE is written by ``run``'s
    tail. A test that called ``evaluate`` would pin the judgement and leave the
    destination - the whole subject here - untouched.
    """
    with redirect_stderr(io.StringIO()):
        return keel_gate.run(event, env={})


def subagent_stop_payload(cwd: Path) -> dict:
    """One SubagentStop payload as the harness sends it, spelled from ``cwd``.

    No ``CLAUDE_PROJECT_DIR`` is involved: the environment is emptied by
    ``without_project_dir`` for every case that uses this, because the variable
    being ABSENT is precisely the condition under which the launcher fell back
    to a directory that follows the shell.
    """
    return {
        "hook_event_name": "SubagentStop",
        "cwd": str(cwd),
        "session_id": SESSION,
        "agent_type": "keel:executor",
        "last_assistant_message": "done",
    }


@contextmanager
def without_project_dir():
    """Run with ``CLAUDE_PROJECT_DIR`` unset, everything else as it was.

    ``patch.dict`` restores the whole mapping on exit, so a test that unsets it
    cannot leak that into the rest of the suite - and the rest of the
    environment is left alone deliberately: clearing it outright would take
    ``USERPROFILE`` with it, and the record walk's ceiling is this user's home.
    """
    with mock.patch.dict(os.environ):
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
        yield


def deep_under(project: Path) -> Path:
    """A directory further below ``project`` than either walk will climb."""
    return project.joinpath(*["d"] * (keel_events.RECORD_WALK_MAX_LEVELS + 2))


class TestAWriteIntoAnotherProject(unittest.TestCase):
    """ACCEPT 3: judged AND recorded by the project the TARGET lives in.

    The fixture is BL8's own shape with the confounder removed: B carries a
    fresh ledger, so B has nothing to refuse and the only refusal in play is
    A's. That matters - keel deliberately lets the SESSION's project judge every
    target too (``keel_gate.governance``), and a fixture where both projects
    refuse would prove only that the strictest verdict won, not that the
    destination followed the target.
    """

    def test_the_refusal_comes_from_the_targets_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=False)
            target = str(there / ORDINARY_RELPATH)
            verdict = gated(write_event(here, target))
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertIn(
                f"GOVERNING PROJECT: this refusal comes from the project at "
                f"{canonical(there)}",
                verdict.reason,
            )

    def test_the_record_lands_in_the_targets_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=False)
            gated(write_event(here, str(there / ORDINARY_RELPATH)))
            lines = audit_lines(there)
            self.assertEqual(len(lines), 1, "exactly one line, in A")
            self.assertEqual(lines[0]["event"], "gate_block")
            self.assertEqual(lines[0]["gate"], "plan")

    def test_the_shells_own_project_gets_no_line_at_all(self) -> None:
        """THE HALF THAT MEASURES BL8. Not "does not contain a gate_block" -
        EMPTY. The mirror's log was 0 lines committed and 10 in the working
        copy; every one of those ten is this assertion failing."""
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=False)
            gated(write_event(here, str(there / ORDINARY_RELPATH)))
            self.assertEqual(audit_lines(here), [])
            self.assertFalse(
                keel_events.audit_path(here).exists(),
                "no audit log is even CREATED in the shell's own project",
            )

    def test_a_command_naming_a_foreign_target_is_recorded_there_too(self) -> None:
        """The ten stray lines are nine ``pre_exec`` and one ``pre_write``, so
        the command half is not an extra: it is the majority of the measured
        shape."""
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=False)
            command = f'python -c "pass" {there / ORDINARY_RELPATH}'
            verdict = gated(exec_event(here, command))
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(len(audit_lines(there)), 1)
            self.assertEqual(audit_lines(here), [])


class TestTheDestinationOfARefusal(unittest.TestCase):
    """ACCEPT 4: the sibling test BL8 argues for, and the reason it is separate.

    A refusal does not go through the capture hook. It is written by
    ``keel_gate._audit`` (for a block) or ``keel_gate._audit_lock_event`` (for a
    line about a refusal that did NOT happen - a bypass, a workshop write, an
    unclassifiable command). Those are two code paths, and the mirror's ten
    stray lines contain BOTH shapes: counted over all ten, four ``gate_block``
    and six ``lock_unclassifiable``. A test covering only the first leaves the
    majority of the measured lines unpinned.

    THIS AGREES WITH BL8 RATHER THAN CORRECTING IT; the two counts are over
    different sets. BL8's "one plan, one plan_contract, one plan_contract_shell
    and six policy_lock refusals" is scoped to the NINE lines of 2026-08-31 and
    excludes the original 2026-08-27 line; the counts above include it. Apply
    BL8's scope and the same ten lines fall out as nine.
    """

    def test_a_policy_lock_refusal_is_filed_with_the_locking_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=True)
            verdict = gated(write_event(here, str(there / LOCKED_RELPATH)))
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")
            lines = audit_lines(there)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["gate"], "policy_lock")
            self.assertEqual(audit_lines(here), [])

    def test_the_line_spends_the_project_and_keeps_the_session_cwd(self) -> None:
        """``detail['project']`` chooses the destination and is then REPLACED by
        ``session_cwd`` - the field BL8 quotes from the stray line, whose value
        was correct while the destination was not. It is project-relative
        (convention 5) and it points back at the shell."""
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=False)
            gated(write_event(here, str(there / ORDINARY_RELPATH)))
            detail = audit_lines(there)[0]["detail"]
            self.assertNotIn("project", detail, "spent, never written")
            self.assertEqual(detail["session_cwd"], "../b")

    def test_an_unclassifiable_command_is_filed_with_the_named_project(self) -> None:
        """The six lines of the mirror's ten that are NOT ``gate_block``: they
        come from ``_audit_lock_event``, whose destination this task also had
        to answer for."""
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=True)
            # An assignment the lock's open world has no verb for, naming a
            # LOCKED path inside the OTHER project - the shape of stray lines
            # 6-10, whose commands each named the sibling tree while the shell
            # stood in it.
            command = f'M="{there / LOCKED_RELPATH}"; printf "%s" "$M"'
            gated(exec_event(here, command))
            named = [
                line
                for line in audit_lines(there)
                if line["event"] == keel_gate.LOCK_UNCLASSIFIABLE_EVENT
            ]
            self.assertEqual(len(named), 1, "the target's project holds the line")
            self.assertEqual(named[0]["gate"], "policy_lock")


class TestItStillFailsClosed(unittest.TestCase):
    """ACCEPT 5. This defect fails CLOSED today, so a fix can only make things
    worse by opening something. Where the target's project cannot be
    ESTABLISHED - the walk ran out of budget, which is a different fact from
    "no project is there" - nothing here falls through to a permissive answer.
    """

    def test_the_gate_refuses_a_target_it_cannot_attribute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=True)
            target = str(deep_under(there) / "app.py")
            verdict = gated(write_event(here, target))
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")
            self.assertNotEqual(verdict.gate, "unarmed")

    def test_that_refusal_is_filed_with_the_session_not_invented_elsewhere(self) -> None:
        """The one case where the cwd fallback is the RIGHT answer, and the
        reason the fallback is allowed to exist at all: no target project was
        established, so the session's own project is the only one entitled to
        the line. It must not be filed against the project the walk was
        HEADING for."""
        with tempfile.TemporaryDirectory() as tmp:
            here = armed(Path(tmp) / "b", plan=True)
            there = armed(Path(tmp) / "a", plan=True)
            gated(write_event(here, str(deep_under(there) / "app.py")))
            self.assertEqual(len(audit_lines(here)), 1)
            self.assertEqual(audit_lines(here)[0]["gate"], "unresolved_project")
            self.assertEqual(audit_lines(there), [])

    def test_the_walk_tells_exhausted_apart_from_absent(self) -> None:
        """R15: all three states reachable through production code, and the
        distinction is the whole guard. A reader that collapses UNKNOWN into
        ABSENT files the line somewhere else - BL8, one level up."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted(root / "project")
            seen = {
                keel_events.resolve_record_root(project / "src" / "app.py").state,
                keel_events.resolve_record_root(root / "loose" / "note.txt").state,
                keel_events.resolve_record_root(deep_under(project) / "app.py").state,
            }
            self.assertEqual(seen, set(keel_events.RECORD_ROOT_STATES))

    def test_the_recorder_writes_nothing_where_it_cannot_place_the_line(self) -> None:
        """The capture hook's half of accept 5, in both directions it can fail:
        a session too deep for the walk to answer for, and a session in no
        project at all. Neither writes, and - the part that matters more than
        the silence - neither CREATES a ``.keel/`` in a directory nobody
        adopted (R25)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            too_deep = deep_under(project)
            too_deep.mkdir(parents=True)
            self.assertTrue(keel_events.resolve_record_root(too_deep).unknown)
            self.assertIsNone(keel_capture.recording_root(too_deep))
            self.assertEqual(keel_capture.run(capture_event(too_deep, "app.py")), 0)
            self.assertFalse((too_deep / ".keel").exists())
            self.assertEqual(audit_lines(project), [])

            nowhere = Path(tmp) / "nowhere"
            nowhere.mkdir()
            self.assertIsNone(keel_capture.recording_root(nowhere))
            self.assertEqual(keel_capture.run(capture_event(nowhere, "app.py")), 0)
            self.assertFalse((nowhere / ".keel").exists())


class TestTheRecorderResolvesTheSessionsProject(unittest.TestCase):
    """ACCEPT 2, the capture hook's half of the sweep.

    ``keel_capture.run`` used to ask whether THIS EXACT DIRECTORY carried
    ``.keel/``. A session started in a subdirectory of its own project - the
    most ordinary thing there is - therefore recorded nothing at all, silently,
    for its whole life. This is the same correction T178 made for the gate and
    T186 made for the stop gate, arriving late at the third writer.
    """

    def test_a_session_in_a_subdirectory_used_to_record_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            inside = project / "src"
            inside.mkdir()
            self.assertFalse(
                keel_capture.project_is_adopted(inside),
                "THE PRE-FIX READING: the flat test says no, and returning 0 "
                "on it is the whole defect",
            )
            self.assertEqual(
                keel_capture.recording_root(inside),
                Path(canonical(project)),
                "the walk says the project one level up owns this session",
            )

    def test_that_sessions_activity_is_now_on_the_projects_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            inside = project / "src"
            inside.mkdir()
            self.assertEqual(keel_capture.run(capture_event(inside, "app.py")), 0)
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["event"], "activity")
            self.assertEqual(
                lines[0]["detail"],
                "src/app.py",
                "anchored on the project the line is FILED in, not on the "
                "subdirectory the payload spelled it from",
            )

    def test_the_queue_line_follows_the_audit_line(self) -> None:
        """One destination for both surfaces, or a distillation pass reads a
        queue that disagrees with the log beside it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            inside = project / "src"
            inside.mkdir()
            keel_capture.run(capture_event(inside, "app.py"))
            queue = keel_events.queue_path(project)
            self.assertTrue(queue.is_file())
            self.assertFalse((inside / ".keel").exists())

    def test_the_session_hooks_reminder_asks_the_governing_project(self) -> None:
        """``keel_session.armed_for_reminders`` claims in its own docstring to
        MIRROR ``keel_stop.armed_for_reminders``. T186 re-pointed the stop
        gate's at the governing project and left this one reading the arming
        file at the exact directory, so the two gave opposite answers about the
        same session's lock."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            inside = project / "src"
            inside.mkdir()
            self.assertTrue(keel_session.armed_for_reminders(project))
            self.assertTrue(
                keel_session.armed_for_reminders(inside),
                "the lock a subdirectory session is held to is a lock it is "
                "told about",
            )

    def test_a_directory_that_never_adopted_keel_is_still_told_nothing(self) -> None:
        """R25 from the other side: the walk may not invent an answer for a
        session outside every project."""
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            loose.mkdir()
            self.assertFalse(keel_session.armed_for_reminders(loose))
            self.assertIsNone(keel_capture.recording_root(loose))


class TestTheOrdinaryCaseIsByteIdentical(unittest.TestCase):
    """THE REGRESSION THIS TASK'S OWN FIRST CUT SHIPPED, kept as a test because
    it is the trap ``keel_gate.governance`` documents and it caught this file's
    author anyway: the walk returns a CANONICAL root while ``event.cwd``
    arrives as the harness spelled it, and on Windows those are routinely
    different strings for one directory. Compared raw, a session standing in
    its OWN project root read as standing elsewhere, and four suite tests
    turned ``src/app.py`` into a ``../../..``-and-home-path spelling of the
    same file.
    """

    def test_a_session_at_the_root_logs_the_payloads_own_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            keel_capture.run(capture_event(project, ORDINARY_RELPATH))
            self.assertEqual(audit_lines(project)[0]["detail"], ORDINARY_RELPATH)

    def test_the_two_spellings_of_one_directory_are_one_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            self.assertTrue(
                keel_capture._is_same_directory(
                    Path(canonical(project)), project / "." / ""
                )
            )
            self.assertFalse(
                keel_capture._is_same_directory(
                    Path(canonical(project)), project / "src"
                )
            )


class TestTheSweepIsWiderThanTheGate(unittest.TestCase):
    """ACCEPT 2's LIST, CHECKED AGAINST THE CODE rather than taken from the
    backlog's word. BL8 names two further sites; both were confirmed present,
    and the sweep found a third the entry does not name - the gate's OWN
    fallback, which is where a refusal went unrecorded entirely.
    """

    def test_one_bound_serves_both_walks(self) -> None:
        """Two numbers that could drift apart would mean a path keel can ARM
        but cannot FILE, or the reverse."""
        self.assertIs(
            keel_gate.PROJECT_WALK_MAX_LEVELS, keel_events.RECORD_WALK_MAX_LEVELS
        )

    def test_the_gates_own_fallback_is_a_project_not_a_directory(self) -> None:
        """THE THIRD SITE, and it is a MISSING record rather than a misfiled
        one: a refusal from one of the three gates that answer before
        ``governance`` - here the ``unresolved_project`` gate - used to be
        handed the raw ``event.cwd``, which for a subdirectory session carries
        no arming file, so ``_audit`` wrote nothing and said so on stderr."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            inside = project / "src"
            inside.mkdir()
            self.assertFalse(
                keel_gate.policy_present(inside),
                "THE PRE-FIX READING: no arming file here, so no log was found",
            )
            self.assertEqual(
                keel_gate.session_audit_root(inside), Path(canonical(project))
            )
            gated(write_event(inside, str(deep_under(project) / "app.py")))
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["gate"], "unresolved_project")
            self.assertFalse((inside / ".keel").exists())

    def test_the_recorders_predicate_is_the_state_directory_not_the_arming_file(
        self,
    ) -> None:
        """The two walks ask DIFFERENT questions and must not be merged. An
        adopted tier-0 project has a LOG and no POLICY; keying the record walk
        on the arming file would silently stop recording every observing
        project keel has."""
        with tempfile.TemporaryDirectory() as tmp:
            observing = adopted(Path(tmp) / "observing")
            self.assertFalse(keel_gate.policy_present(observing))
            answer = keel_capture.recording_root(observing)
            self.assertIsNotNone(
                answer, "an adopted tier-0 project has a LOG and must be recordable"
            )
            # THE ANSWER IS THIS DIRECTORY - compared as a DIRECTORY, not as a
            # string. T602 later made ``recording_root`` keep the caller's own
            # spelling when the walk did not climb (see
            # ``keel_events.record_root_as_spelled``: a respelled root defeats
            # the redactor), so the canonical form is no longer what comes
            # back here. Which directory it names, which is this test's actual
            # subject, is unchanged.
            self.assertEqual(canonical(answer), canonical(observing))


class TestTheLauncherFilesTheEventItPromisesNotToLose(unittest.TestCase):
    """ACCEPT 2 AT THE LAUNCHER, and the site of the sweep that cost live lines.

    ``keel_hook.cmd_subagent_stop`` is the ONLY writer of ``subagent_stop``, and
    it asked the flat question every other writer has now stopped asking: does
    THIS EXACT DIRECTORY carry ``.keel/``, ``return 0`` if not. Its directory
    comes from ``keel_adapter_claude.project_dir``, which answers
    ``CLAUDE_PROJECT_DIR`` FIRST and the payload's ``cwd`` second - and only the
    first of those is a project root. With the variable absent, a session
    standing in a subdirectory dropped every delegation-finish it produced, with
    nothing on stderr and nothing on disk. ``cmd_spike`` carried the same
    spelling and is swept with it; see
    ``test_the_spike_sweep_is_consistency_not_a_live_hole``.
    """

    def test_a_subdirectory_sessions_stop_lands_in_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            inside = project / "src"
            inside.mkdir()
            self.assertFalse(
                (inside / keel_events.KEEL_DIRNAME).is_dir(),
                "THE PRE-FIX READING: the flat test says no, and returning 0 "
                "on it drops the event outright",
            )
            with without_project_dir(), redirect_stderr(io.StringIO()) as err:
                code = keel_hook.cmd_subagent_stop(subagent_stop_payload(inside))
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "", "nothing to report - it wrote")
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1, "the line is in the project, not gone")
            self.assertEqual(lines[0]["event"], keel_hook.SUBAGENT_STOP_EVENT)
            self.assertEqual(lines[0]["session"], SESSION)
            self.assertEqual(lines[0]["agent_type"], "keel:executor")
            self.assertFalse(
                (inside / keel_events.KEEL_DIRNAME).exists(),
                "and no ``.keel/`` is invented in the subdirectory (R25)",
            )

    def test_the_session_at_its_own_root_is_unchanged(self) -> None:
        """The ordinary case, which must be byte-identical: the walk's first
        candidate is the starting directory, so a session already standing in
        its project files exactly where it always did."""
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            with without_project_dir(), redirect_stderr(io.StringIO()):
                keel_hook.cmd_subagent_stop(subagent_stop_payload(project))
            self.assertEqual(len(audit_lines(project)), 1)

    def test_a_directory_in_no_project_is_still_left_alone(self) -> None:
        """R25 unchanged in the other direction: ABSENT is a COMPLETE answer,
        so it writes nothing, creates nothing, and says nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            loose = Path(tmp) / "loose"
            loose.mkdir()
            with without_project_dir(), redirect_stderr(io.StringIO()) as err:
                code = keel_hook.cmd_subagent_stop(subagent_stop_payload(loose))
            self.assertEqual(code, 0)
            self.assertEqual(err.getvalue(), "")
            self.assertFalse((loose / keel_events.KEEL_DIRNAME).exists())

    def test_a_stop_the_walk_cannot_place_is_said_rather_than_dropped(self) -> None:
        """EXHAUSTED IS NOT ABSENT, and this is the assertion that makes the
        new guard capable of failing: where the walk runs out of budget a line
        IS being lost, and an observer that loses one says so on stderr instead
        of returning 0 in silence."""
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            too_deep = deep_under(project)
            too_deep.mkdir(parents=True)
            self.assertTrue(keel_events.resolve_record_root(too_deep).unknown)
            with without_project_dir(), redirect_stderr(io.StringIO()) as err:
                code = keel_hook.cmd_subagent_stop(subagent_stop_payload(too_deep))
            self.assertEqual(code, 0, "an observer never fails the session")
            self.assertIn("subagent_stop not recorded", err.getvalue())
            self.assertEqual(audit_lines(project), [])
            self.assertFalse((too_deep / keel_events.KEEL_DIRNAME).exists())

    def test_the_spike_sweep_is_consistency_not_a_live_hole(self) -> None:
        """``cmd_spike`` carried the same flat test and is swept with it, but
        the claim about it is narrower and is checked here rather than
        asserted: nothing in this repository REGISTERS ``spike``, so it is
        reachable only through the launcher's own dispatch table and no live
        session was losing a line there. The sweep is so that one spelling of
        the rule does not sit beside another and drift."""
        manifest = (REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
        # The manifest is JSON, so the closing quote of the interpolated path
        # arrives as ``\"`` between the script name and its subcommand.
        registered = set(re.findall(r'keel_hook\.py[\\"]*\s+([a-z_]+)', manifest))
        self.assertIn(
            "subagent_stop", registered, "the manifest this reads is the live one"
        )
        self.assertNotIn(keel_hook.SPIKE_EVENT, registered)
        self.assertIs(keel_hook.SUBCOMMANDS[keel_hook.SPIKE_EVENT], keel_hook.cmd_spike)
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted(Path(tmp) / "project")
            inside = project / "src"
            inside.mkdir()
            with redirect_stderr(io.StringIO()):
                keel_hook.cmd_spike({"cwd": str(inside), "session_id": SESSION})
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["event"], keel_hook.SPIKE_EVENT)
            self.assertFalse((inside / keel_events.KEEL_DIRNAME).exists())


if __name__ == "__main__":
    unittest.main()
