#!/usr/bin/env python3
"""T178 - enforcement is keyed on the TARGET's project, not the session's cwd.

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module, and this repository's own
          directory layout in exactly one read-only case (the walk is asked
          which project owns a file of keel's own source; no verdict is
          evaluated there). Every gated case builds its own fixture project
          under a temporary directory, so no assertion here depends on the
          tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED AGAINST A TARGET INSIDE THIS REPOSITORY, and
          that is a rule of this file rather than an accident: evaluating the
          gate on a target under a declared ``workshop:`` prefix APPENDS a
          real ``workshop_write`` line to ``.keel/audit/keel-audit.jsonl``,
          and the audit log is evidence here. A probe did exactly that while
          this defect was being measured and the false line is permanently on
          the record.
Argv    : none.

The defect, as measured before a line of the fix was written
------------------------------------------------------------
``evaluate`` read ``policy_tier(event.cwd)`` and allowed when it was None;
``run`` chose fail-closed versus fail-open on ``policy_present(event.cwd)``.
Both asked about the SESSION'S DIRECTORY when the question is about the
TARGET'S PROJECT. Three events differing only in ``cwd``, each naming the same
protected target of the same armed project by absolute path, with an empty
environment so no kill switch could colour the result::

    cwd = the armed project   -> blocking=True,  gate='plan'
    cwd = the drive root      -> blocking=False, gate='unarmed'
    cwd = the parent directory -> blocking=False, gate='unarmed'

The parent-directory case is the one that matters and it needs no cleverness:
a session started one directory up - a workspace-root session, the most
ordinary thing there is - wrote into a tier-2 armed project with NO GATE AT
ALL. Not a weaker gate; ``gate='unarmed'``, the same verdict an unadopted
project gets. That is a fail-OPEN, and ``TestTheHoleTheProbeMeasured`` below
is that probe turned into an assertion.

What this covers, clause by clause
----------------------------------
1. THE HOLE (accept 1). ``TestTheHoleTheProbeMeasured`` fails on the code that
   shipped before this task, for the parent-directory case specifically.
2. RESOLVED FROM THE TARGET UPWARD (accept 2), and ``run``'s fail-closed
   choice made on the same resolution - ``TestTheFailurePolicyFollowsTheSame
   Resolution``, both directions.
3. THE LEDGER MOVES WITH THE PROJECT. A session held to a plan requirement is
   held to the plan requirement OF THE PROJECT IT IS WRITING INTO, and the
   refusal names the file it is expected to write. ``TestTheLedgerMovesWith
   TheProject``.
4. SEVERAL TARGETS, SEVERAL PROJECTS (accept 2's tuple). ``file_paths`` is a
   tuple and two targets can land in two different projects, or one in an
   armed project and one nowhere. THE STRICTEST VERDICT WINS and the refusal
   names which target and which project produced it.
   ``TestSeveralTargetsSeveralProjects``.
5. COMMANDS TOO (accept 3). ``TestACommandIsJudgedByItsTargetsProject``: a
   command whose cwd is elsewhere and whose named target is inside an armed
   project. Commands keep the FULL lock and never consult ``workshop:``
   (design rule 4), which stays true - what changes is WHICH project's lock
   applies.
6. NO WIDENING (accept 4), which is the direction a fix of this shape fails
   in. ``TestNoWidening`` pins that a target genuinely outside every armed
   project still reads unarmed and still fails open, and that the upward walk
   is BOUNDED: it never treats a filesystem root or the home directory as a
   project, and it gives up after ``PROJECT_WALK_MAX_LEVELS`` levels. An
   arming file high in a tree may not silently arm the world.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding. R1: matching is casefolded in the gate, so the fixtures that care
ship both cases.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import is_published_cut  # noqa: E402
import keel_events  # noqa: E402
import keel_gate  # noqa: E402

#: A session id of this test's own, so a fixture ledger can never be confused
#: with a real one and no real ledger can ever satisfy a fixture.
SESS8 = "cafe1178"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: A contract-clean ledger, so a case that means to exercise arming or the
#: lock is never answered by the plan contract instead.
LEDGER_TEXT = (
    "# Plan\n\n- [ ] T1 the thing\n      Route: standard (keel:executor).\n"
    "      Accept: it works.\n"
)

#: A protected target inside a fixture project: ``hooks/`` is under the lock
#: for every project, by ``PROTECTED_DIRS``.
PROTECTED_RELPATH = "hooks/kernel.py"

#: An ordinary target inside a fixture project: nothing locks it, so the plan
#: gate is the only rule that can answer for it.
ORDINARY_RELPATH = "src/app.py"


def canonical(path: Path) -> str:
    """A path as the gate spells it: symlink-resolved and, on Windows, with
    every 8.3 short component expanded. The temporary directories this file
    builds are handed out with a short home component, and the gate resolves
    every path it reasons about, so a comparison against a raw fixture path
    would be a comparison of two spellings of the same directory."""
    return str(Path(os.path.realpath(str(path))))


def armed(project: Path, *, tier: int = 2, plan: bool = False, body: str = "") -> Path:
    """A fixture project whose arming file declares ``tier`` and ``body``."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    text = f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n\n{body}"
    (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")
    if plan:
        ledger(project)
    return project


def ledger(project: Path, sess8: str = SESS8) -> Path:
    """A fresh session ledger for a fixture project."""
    path = project / ".keel" / "plans" / f"keel-plan-{sess8}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(LEDGER_TEXT, encoding="utf-8")
    return path


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


def _boom(*_args: object, **_kwargs: object) -> keel_events.KeelVerdict:
    """An ``evaluate`` that cannot evaluate - the failure policy's input."""
    raise RuntimeError("deliberate fault")


def run_with_broken_evaluate(event: keel_events.KeelEvent) -> keel_events.KeelVerdict:
    """``run`` over an evaluation that raises, so the fail policy is what answers."""
    original = keel_gate.evaluate
    keel_gate.evaluate = _boom
    try:
        return keel_gate.run(event, env={})
    finally:
        keel_gate.evaluate = original


class TestTheHoleTheProbeMeasured(unittest.TestCase):
    """Accept 1: the measurement, as an assertion. FAILS on pre-T178 code.

    Three cwds, ONE target, one verdict. The parent-directory case is named as
    its own test as well as inside the loop, because it is the case an ordinary
    session hits by accident and a loop that fails on the first cwd would never
    reach it.
    """

    def test_the_same_protected_target_is_refused_from_every_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            target = str(project / PROTECTED_RELPATH)
            for label, cwd in (
                ("the armed project", project),
                ("the parent directory", root),
                ("the drive root", Path(root.anchor)),
            ):
                with self.subTest(cwd=label):
                    verdict = keel_gate.evaluate(write_event(cwd, target), env={})
                    self.assertEqual(verdict.decision, "deny", label)
                    self.assertEqual(verdict.gate, "policy_lock", label)

    def test_a_session_one_directory_up_writes_under_the_full_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / PROTECTED_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")
            self.assertNotEqual(
                verdict.gate, "unarmed", "an armed project's file read as unadopted"
            )

    def test_the_case_survives_a_casefolded_spelling(self) -> None:
        """R1: the lock is casefolded, so the hole must close on either case."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            target = str(project / "HOOKS" / "Kernel.py")
            verdict = keel_gate.evaluate(write_event(root, target), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")

    def test_a_target_in_a_subdirectory_of_the_project_resolves_upward(self) -> None:
        """The walk climbs from the target, not from the project it guesses."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            deep = str(project / "src" / "a" / "b" / "c" / "app.py")
            allowed = keel_gate.evaluate(write_event(root, deep), env={})
            self.assertEqual(allowed.decision, "allow", "a fresh plan is on file")
            self.assertEqual(allowed.gate, "plan")


class TestTheSessionsOwnProjectStillDecides(unittest.TestCase):
    """The other half of accept 2, and the regression guard for every existing
    case: a session INSIDE its project keeps exactly the verdicts it had, and a
    session in a SUBDIRECTORY of one - which read as unarmed for the same
    reason the hole existed - is now gated by the project above it."""

    def test_an_ordinary_in_project_write_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            verdict = keel_gate.evaluate(
                write_event(project, ORDINARY_RELPATH), env={}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan")

    def test_an_ordinary_in_project_write_with_no_ledger_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=False)
            verdict = keel_gate.evaluate(
                write_event(project, ORDINARY_RELPATH), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")

    def test_a_session_in_a_subdirectory_is_gated_by_the_project_above_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=False)
            inside = project / "src"
            inside.mkdir(parents=True, exist_ok=True)
            verdict = keel_gate.evaluate(write_event(inside, "app.py"), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")

    def test_a_relative_path_still_resolves_against_the_sessions_own_cwd(self) -> None:
        """The project decides the RULES; the session's cwd still decides what a
        relative payload path MEANS. Confusing the two would judge the wrong
        file - here, ``app.py`` beside the session rather than at the root."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            inside = project / "hooks"
            inside.mkdir(parents=True, exist_ok=True)
            verdict = keel_gate.evaluate(write_event(inside, "kernel.py"), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(
                verdict.gate, "policy_lock", "hooks/kernel.py is under the lock"
            )


class TestTheLedgerMovesWithTheProject(unittest.TestCase):
    """If a target's project supplies the arming decision, that project's
    ``.keel/plans/`` supplies the plan requirement too. Refusing is the honest
    answer when no ledger is there, and the refusal names the file the session
    is expected to write."""

    def test_a_write_into_an_armed_project_needs_that_projects_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertIn(f".keel/plans/keel-plan-{SESS8}.md", verdict.reason)

    def test_the_refusal_names_the_project_the_ledger_belongs_to(self) -> None:
        """The plan path alone is ambiguous when the cwd is somewhere else: it
        is project-relative, and the session is not standing in that project."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertIn(project.name, verdict.reason)
            self.assertIn(
                str(Path(canonical(project)) / ".keel" / "plans" / f"keel-plan-{SESS8}.md"),
                verdict.reason,
                "a project-relative ledger path is a dead end for a session "
                "standing somewhere else",
            )
            self.assertEqual(verdict.detail.get("project"), canonical(project))

    def test_a_ledger_beside_the_session_does_not_satisfy_the_target(self) -> None:
        """The whole of the hole, stated as a positive: a plan in the directory
        the session happens to be sitting in decides nothing about a write into
        another project."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            elsewhere = armed(root / "elsewhere", plan=True)
            project = armed(root / "project", plan=False)
            verdict = keel_gate.evaluate(
                write_event(elsewhere, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(verdict.detail.get("project"), canonical(project))

    def test_that_projects_own_ledger_does_satisfy_it(self) -> None:
        """The other direction, or the clause above would be satisfied by a gate
        that simply refuses everything cross-project."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan")

    def test_the_bootstrap_carve_out_travels_too(self) -> None:
        """A write to the target project's own ledger is still the one write
        that needs no ledger - or a cross-project session could never bootstrap
        the plan the clause above demands of it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            target = str(project / ".keel" / "plans" / f"keel-plan-{SESS8}.md")
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=root,
                session_id=SESSION,
                tool_name="Write",
                raw={"tool_input": {"file_path": target, "content": LEDGER_TEXT}},
                file_paths=(target,),
            )
            verdict = keel_gate.evaluate(event, env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan_bootstrap")


class TestSeveralTargetsSeveralProjects(unittest.TestCase):
    """``file_paths`` is a tuple, and a single event can reach two projects.
    THE STRICTEST VERDICT WINS, and the refusal says which target and which
    project produced it."""

    def test_one_armed_target_among_unarmed_ones_decides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            loose = root / "loose" / "note.txt"
            loose.parent.mkdir(parents=True, exist_ok=True)
            verdict = keel_gate.evaluate(
                write_event(root, str(loose), str(project / ORDINARY_RELPATH)),
                env={},
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(verdict.detail.get("project"), canonical(project))

    def test_two_projects_and_the_stricter_one_answers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relaxed = armed(root / "relaxed", plan=True)
            strict = armed(root / "strict", plan=False)
            verdict = keel_gate.evaluate(
                write_event(
                    root,
                    str(relaxed / ORDINARY_RELPATH),
                    str(strict / ORDINARY_RELPATH),
                ),
                env={},
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.detail.get("project"), canonical(strict))

    def test_the_lock_of_one_project_does_not_reach_into_another(self) -> None:
        """Each project's protected set is ITS OWN, resolved from ITS OWN root:
        a file called ``hooks/kernel.py`` in project A is not locked by project
        B's copy of the same rule."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            armed(root / "watcher", plan=True)
            other = armed(root / "other", plan=True)
            verdict = keel_gate.evaluate(
                write_event(root / "watcher", str(other / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "allow")

    def test_both_projects_refuse_and_the_named_one_owns_the_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = armed(root / "here", plan=False)
            there = armed(root / "there", plan=False)
            verdict = keel_gate.evaluate(
                write_event(here, str(there / PROTECTED_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")
            self.assertEqual(verdict.detail.get("project"), canonical(there))


class TestACommandIsJudgedByItsTargetsProject(unittest.TestCase):
    """Accept 3. A command's cwd is elsewhere and its named target is inside an
    armed project. Commands keep the FULL lock and never consult ``workshop:``
    (design rule 4); what changes is which project's lock applies."""

    def test_a_mutating_command_naming_a_locked_path_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            command = f"rm -rf {project / 'hooks'}"
            verdict = keel_gate.evaluate(exec_event(root, command), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")

    def test_a_command_needs_the_target_projects_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            command = f"python {project / 'src' / 'build.py'}"
            verdict = keel_gate.evaluate(exec_event(root, command), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(verdict.detail.get("project"), canonical(project))

    def test_that_projects_ledger_clears_the_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            command = f"python {project / 'src' / 'build.py'}"
            verdict = keel_gate.evaluate(exec_event(root, command), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan")

    def test_a_read_only_command_is_still_no_ones_business(self) -> None:
        """Rule 2 is scoped to state-changing commands and this change does not
        widen that scope: a read of a file in an armed project from outside it
        needs no ledger, exactly as a read inside it does not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            command = f"cat {project / 'src' / 'app.py'}"
            verdict = keel_gate.evaluate(exec_event(root, command), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan_scope")

    def test_a_command_touching_nothing_of_any_project_is_ungated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            armed(root / "project", plan=False)
            command = f"rm -rf {root / 'loose' / 'note.txt'}"
            verdict = keel_gate.evaluate(exec_event(root, command), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "unarmed")


class TestTheFailurePolicyFollowsTheSameResolution(unittest.TestCase):
    """Accept 2's second half. ``run`` decides fail-closed versus fail-open on
    the SAME resolution ``evaluate`` uses, or a crash while evaluating a foreign
    project's target picks the wrong failure policy."""

    def test_a_crash_on_an_armed_projects_target_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = run_with_broken_evaluate(
                write_event(root, str(project / ORDINARY_RELPATH))
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("FAILED CLOSED", verdict.reason)

    def test_a_crash_on_nobodys_target_still_fails_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            armed(root / "project", plan=True)
            loose = root / "loose" / "note.txt"
            loose.parent.mkdir(parents=True, exist_ok=True)
            verdict = run_with_broken_evaluate(write_event(root, str(loose)))
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.to_exit_code(), 0)

    def test_a_crash_inside_the_project_still_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            verdict = run_with_broken_evaluate(write_event(project, ORDINARY_RELPATH))
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("FAILED CLOSED", verdict.reason)


class TestTheRecordLandsInTheProjectThatRefused(unittest.TestCase):
    """A block is evidence, and it belongs to the project whose rule produced
    it. A gate that audited into the session's cwd would create a stray
    ``.keel/`` in whatever directory the session happened to start in - and
    would file the project's own refusal somewhere the project cannot read."""

    def test_the_block_is_recorded_in_the_target_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            verdict = keel_gate.run(
                write_event(root, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1, lines)
            self.assertEqual(lines[0]["event"], "gate_block")
            self.assertEqual(lines[0]["gate"], "plan")

    def test_the_line_says_where_the_session_stood_and_names_no_absolute_path(self) -> None:
        """Convention 5: the governing project chooses the destination and is
        then spent - what the log keeps is the session's directory relative to
        the project that refused, which for this case is one level up."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            keel_gate.run(write_event(root, str(project / ORDINARY_RELPATH)), env={})
            line = audit_lines(project)[-1]
            self.assertEqual(line["detail"].get("session_cwd"), "..")
            self.assertNotIn("project", line["detail"])
            self.assertNotIn(canonical(project), json.dumps(line))

    def test_no_keel_directory_appears_beside_the_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            keel_gate.run(write_event(root, str(project / ORDINARY_RELPATH)), env={})
            self.assertFalse(
                (root / ".keel").exists(),
                "the gate created a .keel/ in a directory that is not a project",
            )


class TestNoWidening(unittest.TestCase):
    """Accept 4, and the failure mode a fix of this shape is expected to have.
    A target genuinely outside every armed project reads UNARMED and fails
    OPEN, said out loud; and the upward walk is bounded so that an arming file
    high in a tree cannot silently arm the world."""

    def test_a_target_outside_every_project_reads_unarmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            loose = root / "loose" / "note.txt"
            loose.parent.mkdir(parents=True, exist_ok=True)
            verdict = keel_gate.evaluate(write_event(root, str(loose)), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "unarmed")

    def test_the_unarmed_reason_says_why_out_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verdict = keel_gate.evaluate(
                write_event(root, str(root / "note.txt")), env={}
            )
            self.assertEqual(verdict.gate, "unarmed")
            self.assertIn("keel-policy.md", verdict.reason)
            self.assertIn("target", verdict.reason)

    def test_a_tier_below_enforcing_is_still_below_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", tier=1, plan=False)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / PROTECTED_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "tier")

    def test_the_walk_never_treats_a_filesystem_root_as_a_project(self) -> None:
        anchor = Path(Path(tempfile.gettempdir()).anchor)
        self.assertTrue(keel_gate.is_walk_ceiling(anchor))

    def test_the_walk_never_treats_the_home_directory_as_a_project(self) -> None:
        self.assertTrue(keel_gate.is_walk_ceiling(Path.home()))

    def test_an_arming_file_at_the_ceiling_arms_nothing_below_it(self) -> None:
        """The whole of "must not silently arm the world", as a fixture: a home
        directory carrying an arming file does not arm the projects under it."""
        with tempfile.TemporaryDirectory() as tmp:
            home = armed(Path(tmp) / "home", plan=False)
            target = home / "work" / "app.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            stopped = keel_gate.resolve_project(target, home=home)
            self.assertEqual(stopped.state, keel_gate.PROJECT_ABSENT)
            self.assertIsNone(stopped.root)
            found = keel_gate.resolve_project(target, home=Path(tmp) / "somewhere-else")
            self.assertEqual(found.state, keel_gate.PROJECT_FOUND)
            self.assertEqual(
                found.root,
                Path(canonical(home)),
                "the same tree DOES arm when it is not the ceiling - or the "
                "assertion above would pass for the wrong reason",
            )

    def test_the_walk_gives_up_after_a_bounded_number_of_levels(self) -> None:
        """The bound still bounds - and says WHICH bound stopped it.

        This assertion used to read the walk's answer as a bare root and
        called None-for-a-deep-path intended. It was the review's first
        finding: the cost limit
        answered in the same word absence answers in, so a target one level
        below the ceiling read as "no project owns this" and was allowed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            top = armed(Path(tmp) / "top", plan=False)
            levels = keel_gate.PROJECT_WALK_MAX_LEVELS
            at_the_limit = top.joinpath(*["d"] * (levels - 1)) / "app.py"
            beyond_it = top.joinpath(*["d"] * (levels + 2)) / "app.py"
            reached = keel_gate.resolve_project(at_the_limit)
            self.assertEqual(reached.state, keel_gate.PROJECT_FOUND)
            self.assertEqual(reached.root, Path(canonical(top)))
            exhausted = keel_gate.resolve_project(beyond_it)
            self.assertEqual(exhausted.state, keel_gate.PROJECT_UNKNOWN)
            self.assertIsNone(exhausted.root, "unknown carries no root")
            self.assertNotEqual(
                exhausted.state,
                keel_gate.PROJECT_ABSENT,
                "the cost limit is not a statement that no project exists",
            )

    def test_the_walk_needs_no_file_on_disk(self) -> None:
        """A write's target usually does not exist yet - that is the point of a
        write - so resolution may never depend on the target being there."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=False)
            absent = project / "src" / "not" / "created" / "yet.py"
            self.assertFalse(absent.exists())
            self.assertEqual(keel_gate.resolve_project(absent).root, Path(canonical(project)))

    def test_an_unresolvable_target_is_nobodys_business_when_nobody_is_armed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            verdict = keel_gate.evaluate(write_event(root, "no\x00thing"), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "unarmed")

    def test_an_unresolvable_target_is_still_refused_by_an_armed_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            verdict = keel_gate.evaluate(write_event(project, "no\x00thing"), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unverifiable_target")


class TestTheKillSwitchStillAnswersFirst(unittest.TestCase):
    """``KEEL_GATE=off`` stands the whole gate down before arming is resolved,
    which is what the switch means. Pinned because the resolution added here
    runs at the same point the old tier read did, and a fix that resolved
    arming BEFORE the switch would change what the switch does."""

    def test_the_switch_answers_before_any_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / PROTECTED_RELPATH)),
                env={"KEEL_GATE": "off"},
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "kill_switch")


class TestTheWalkOnKeelsOwnTree(unittest.TestCase):
    """One read-only case against the real repository, because a resolution
    that only works on fixtures has not been shown to work. NOTHING IS
    EVALUATED here: the walk is a filesystem read and appends nothing."""

    def test_this_repositorys_own_source_resolves_to_this_repository(self) -> None:
        """INVERTS IN A PUBLISHED CUT. Resolution keys on the arming file, and a
        cut ships none, so there is no project to find - which is the shipped
        property, asserted rather than skipped."""
        found = keel_gate.resolve_project(REPO_ROOT / "hooks" / "keel_gate.py")
        if is_published_cut(REPO_ROOT):
            self.assertNotEqual(found.state, keel_gate.PROJECT_FOUND)
            self.assertIsNone(found.root)
            return
        self.assertEqual(found.state, keel_gate.PROJECT_FOUND)
        self.assertEqual(found.root, REPO_ROOT)

    def test_a_nested_path_of_this_repository_resolves_the_same_way(self) -> None:
        found = keel_gate.resolve_project(Path(__file__).resolve())
        if is_published_cut(REPO_ROOT):
            self.assertIsNone(found.root)
            return
        self.assertEqual(found.root, REPO_ROOT)


class TestTheDeclarationMatchesTheBehaviour(unittest.TestCase):
    """R3/R15: what the module says about arming is what the module does."""

    def test_the_module_declares_target_keyed_arming(self) -> None:
        doc = keel_gate.__doc__ or ""
        self.assertIn("THE TARGET'S PROJECT", doc.upper())

    def test_the_module_declares_the_bound(self) -> None:
        doc = (keel_gate.resolve_project.__doc__ or "") + (keel_gate.__doc__ or "")
        self.assertIn("PROJECT_WALK_MAX_LEVELS", doc)

    def test_the_gate_still_declares_both_failure_directions(self) -> None:
        doc = keel_gate.__doc__ or ""
        self.assertIn("FAIL-CLOSED WHEN ARMED", doc)
        self.assertIn("FAIL-OPEN WHEN UNARMED", doc)


class TestExhaustionIsNotAbsence(unittest.TestCase):
    """The T178 review's FIRST finding (security, 82%): the walk's cost limit
    must not answer in the same word absence answers in.

    ``is_walk_ceiling`` is a DECISION - above a drive root or the home directory
    keel will not look, so stopping there is a complete answer and reads
    ``PROJECT_ABSENT``. ``PROJECT_WALK_MAX_LEVELS`` is a BUDGET - stopping there
    means keel ran out of levels, so it reads ``PROJECT_UNKNOWN`` and must fail
    TOWARD the gate. While both answers were a bare None, a target one directory
    below the bound read as "no project owns this" and was ALLOWED: the pre-T178
    fail-open, moved downward. Where a test can, it states the pre-fix reading
    IN ITSELF, so the discrimination needs no second tree to run against.
    """

    def deep_under(self, project: Path) -> Path:
        """A directory further above ``project`` than the walk will climb."""
        return project.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2))

    def test_all_three_states_are_reachable_through_production_code(self) -> None:
        """R15, and T176's rule: a state no real input reaches is not tested."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            seen = {
                keel_gate.resolve_project(project / "src" / "app.py").state,
                keel_gate.resolve_project(root / "loose" / "note.txt").state,
                keel_gate.resolve_project(self.deep_under(project) / "app.py").state,
            }
            self.assertEqual(seen, set(keel_gate.PROJECT_STATES))

    def test_a_target_beyond_the_bound_is_refused_when_the_session_enforces(self) -> None:
        """The finding itself, from OUTSIDE the armed project (T187: the deny
        here now depends on the SESSION's own tier - ``root`` is unarmed, so
        see the companion test below for what T187 makes of exactly this
        fixture from a session that does not enforce)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            target = str(self.deep_under(project) / "app.py")
            self.assertIsNone(
                keel_gate.resolve_project(target).root,
                "THE PRE-FIX READING: a caller that reads only the root sees "
                "None here, which is what 'nothing governs this' looked like",
            )
            # cwd is the ARMED project itself now, not the unarmed root above
            # it - T187 made the session's OWN tier the deciding fact, and
            # ``test_it_is_refused_from_inside_that_project_too`` already
            # covers "from inside"; this one is kept to prove the DENY still
            # happens for an outside-but-enforced session too (project2 sits
            # beside project, both armed, session standing in project2).
            project2 = armed(root / "project2", plan=True)
            verdict = keel_gate.evaluate(write_event(project2, target), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")
            self.assertNotEqual(verdict.gate, "unarmed")

    def test_the_same_fixture_from_an_unarmed_session_is_announced_not_denied(self) -> None:
        """T187 accept 1, ripple: the ORIGINAL form of the test above stood in
        ``root``, which this fixture never arms - so under the new ruling the
        session itself is below the enforcing tier (there is no tier at all)
        and the unattributable path is announced and allowed, never denied."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            target = str(self.deep_under(project) / "app.py")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.evaluate(write_event(root, target), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertNotEqual(verdict.gate, "unresolved_project")
            self.assertIn("PROJECT UNRESOLVED", stderr.getvalue())
            self.assertIn(
                "PERMITTED BELOW THE ENFORCING TIER", stderr.getvalue()
            )

    def test_it_is_refused_from_inside_that_project_too(self) -> None:
        """Not only from outside: the hole is the PATH, not the session."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            target = str(self.deep_under(project) / "app.py")
            verdict = keel_gate.evaluate(write_event(project, target), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")

    def test_it_is_refused_even_where_no_project_was_found_at_all(self) -> None:
        """Stopping early is not a statement that nothing is there, so a
        target the walk gave up on is still PROJECT_UNKNOWN, never
        PROJECT_ABSENT, with no arming file anywhere above the path either -
        the state distinction holds regardless of what ``evaluate`` does with
        it. T187 ripple: this session (``root``) is unarmed too, so the
        WRITE ITSELF is now announced and allowed rather than denied - see
        ``test_a_tier_below_enforcing_...`` below for the deliberate case."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = str(self.deep_under(root) / "app.py")
            self.assertTrue(
                keel_gate.resolve_project(target).unknown,
                "the state itself is unaffected by T187 - only evaluate()'s "
                "use of it changed",
            )
            verdict = keel_gate.evaluate(write_event(root, target), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertNotEqual(verdict.gate, "unresolved_project")

    def test_a_tier_below_enforcing_is_announced_and_allowed_not_denied(self) -> None:
        """INVERTS the old ``test_a_tier_below_enforcing_does_not_rescue_it``
        (T187 accept 1, the ruling itself): a tier-1 project ALREADY allows a
        write into ITS OWN protected/locked path, because the tier check in
        ``_project_verdict`` precedes the lock entirely - so denying a path it
        merely could not attribute, while permitting one it CAN attribute to a
        protected file, was a single arbitrary trapdoor rather than safety.
        Below the enforcing tier the unattributable path is announced and
        audited instead, never denied; at tier 2 and above it still is
        (``test_it_is_refused_from_inside_that_project_too``, unchanged)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", tier=1, plan=False)
            target = str(self.deep_under(project) / "app.py")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.run(write_event(project, target), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "tier")
            self.assertNotEqual(verdict.gate, "unresolved_project")
            printed = stderr.getvalue()
            self.assertIn("PROJECT UNRESOLVED", printed)
            self.assertIn("PERMITTED BELOW THE ENFORCING TIER", printed)
            lines = audit_lines(project)
            self.assertTrue(lines, "below-tier is announced AND audited, never silent")
            self.assertEqual(lines[-1]["event"], "unresolved_project_allowed")
            self.assertEqual(lines[-1]["gate"], "unresolved_project")

    def test_zero_unattributable_targets_leaves_no_marker(self) -> None:
        """T187 accept 2: zero is not silence in the OTHER direction too - an
        ordinary write with nothing unattributable must never carry the
        ``unresolved_project_allowed`` line, or its presence would stop
        meaning anything."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", tier=1, plan=False)
            verdict = keel_gate.run(write_event(project, ORDINARY_RELPATH), env={})
            self.assertEqual(verdict.decision, "allow")
            lines = audit_lines(project)
            self.assertFalse(
                any(line.get("event") == "unresolved_project_allowed" for line in lines),
                "nothing here was unattributable; the marker must not appear",
            )

    def test_one_level_inside_the_bound_still_resolves(self) -> None:
        """The bound is what does the work above, not the fixture's depth."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            inside = project.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS - 2))
            verdict = keel_gate.evaluate(
                write_event(root, str(inside / "app.py")), env={}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan")

    def test_the_refusal_names_the_bound_and_points_at_no_override(self) -> None:
        """T187 ripple: the session must ENFORCE for this to still deny, so
        the cwd moved from the unarmed ``root`` to the armed project itself -
        the message this pins is unchanged, only the fixture needed to keep
        reaching it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=False)
            target = str(self.deep_under(project) / "app.py")
            verdict = keel_gate.evaluate(write_event(project, target), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertIn("PROJECT UNRESOLVED", verdict.reason)
            self.assertIn(str(keel_gate.PROJECT_WALK_MAX_LEVELS), verdict.reason)
            self.assertIn("NEXT STEP:", verdict.reason)
            self.assertNotIn(
                "KEEL_OVERRIDE=on",
                verdict.reason,
                "not a policy refusal, so it must not send anyone to the override",
            )

    def test_the_refusal_reaches_the_record_with_its_own_gate(self) -> None:
        """T187 ripple: same fixture-only fix as above - cwd is now the armed
        project so the session enforces and this remains a DENY on the record."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project", plan=True)
            target = str(self.deep_under(project) / "app.py")
            verdict = keel_gate.run(write_event(project, target), env={})
            self.assertEqual(verdict.decision, "deny")
            lines = audit_lines(project)
            self.assertTrue(lines, "a block must be audited")
            self.assertEqual(lines[-1]["gate"], "unresolved_project")

    def test_a_command_naming_an_unattributable_path_is_refused(self) -> None:
        """Accept 3's half of the finding: the same rule for command text.
        T187 ripple: cwd moved from the unarmed ``root`` to the armed project
        itself, so the session still enforces and this remains a DENY."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            named = str(self.deep_under(project) / "build.py")
            verdict = keel_gate.evaluate(exec_event(project, "python " + named), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")

    def test_a_command_naming_an_unattributable_path_is_announced_below_tier(self) -> None:
        """T187 accept 1, the command-text half: the same shape as the write
        case above - an unresolvable NAMED target is announced and allowed,
        never denied, while the session itself does not enforce."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            named = str(self.deep_under(root) / "build.py")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.run(exec_event(root, "python " + named), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertIn("PROJECT UNRESOLVED", stderr.getvalue())
            lines = audit_lines(root)
            self.assertTrue(
                any(line.get("event") == "unresolved_project_allowed" for line in lines)
            )

    def test_a_deep_session_directory_does_not_refuse_the_event_by_itself(self) -> None:
        """The documented asymmetry, pinned in both directions. A cwd too deep to
        walk falls back to reading the arming file AT the cwd - which is exactly
        what shipped before T178, so it cannot be a regression - while every
        TARGET still gets the strict answer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=False)
            deep_cwd = self.deep_under(root)
            deep_cwd.mkdir(parents=True, exist_ok=True)
            self.assertTrue(keel_gate.resolve_project(deep_cwd).unknown)
            verdict = keel_gate.evaluate(
                write_event(deep_cwd, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.gate, "plan", "the target's project decided")
            self.assertEqual(verdict.detail.get("project"), canonical(project))

    def test_a_target_inside_that_deep_tree_is_announced_not_refused(self) -> None:
        """T187 ripple: this session's OWN walk also exhausts here (nothing is
        armed anywhere in this fixture, so ``policy_present`` at the deep cwd
        itself is False too) - below the enforcing tier (there is none), so
        the target inside it is announced and allowed rather than denied."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep_cwd = self.deep_under(root)
            deep_cwd.mkdir(parents=True, exist_ok=True)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.evaluate(write_event(deep_cwd, "app.py"), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertNotEqual(verdict.gate, "unresolved_project")
            self.assertIn("PROJECT UNRESOLVED", stderr.getvalue())

#: A payload path that will not normalise, spelled without a literal NUL in the
#: source: an embedded NUL is what makes ``os.path.realpath`` refuse, and the
#: existing single-target fixtures use the same shape.
UNVERIFIABLE_RELPATH = "no" + chr(0) + "thing"


class TestEveryTargetIsAccountedFor(unittest.TestCase):
    """The T178 review's SECOND finding (silent failure, 87%), verbatim: when the
    session's own cwd is governed by no armed project and a ``pre_write`` names
    two or more targets, an unresolvable target's owner fell back to a None
    session root, was remembered by nobody, and was excluded from every project's
    judged tuple - while ``_evaluate_write``'s unverifiable check inspects only
    the subset it is passed and never ``event.file_paths``. The event was decided
    on the resolvable target alone and the malformed one was never evaluated.

    THE ANSWER IS THE CLASS, NOT THE SITE. ``Governance`` accounts for every
    entry of ``event.file_paths`` in exactly one of four buckets and PROVES it at
    construction, so a target nobody judges cannot read as permitted without the
    accounting raising first. An unresolvable entry is handed to EVERY governing
    project, which is what puts the whole payload back in front of the
    unverifiable check rather than one project's share of it.
    """

    def mixed(self, root: Path, project: Path, reverse: bool = False) -> object:
        """One event naming a resolvable target of ``project`` and a bad path."""
        paths = [str(project / ORDINARY_RELPATH), UNVERIFIABLE_RELPATH]
        if reverse:
            paths.reverse()
        return write_event(root, *paths)

    def test_an_unverifiable_target_beside_an_armed_one_refuses_the_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = keel_gate.evaluate(self.mixed(root, project), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unverifiable_target")
            self.assertIn("thing", str(verdict.detail.get("target")))

    def test_the_control_that_makes_the_case_above_attributable(self) -> None:
        """THE PRE-FIX READING, executed: the resolvable target ALONE is allowed
        by this same fixture, so the refusal above can only come from the entry
        that used to be dropped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = keel_gate.evaluate(
                write_event(root, str(project / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "plan")

    def test_the_order_of_the_two_targets_does_not_matter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            verdict = keel_gate.evaluate(self.mixed(root, project, reverse=True), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unverifiable_target")

    def test_every_governing_project_is_handed_the_unverifiable_entry(self) -> None:
        """The mechanism rather than the verdict: it is in ``covered`` and in
        every project's judged tuple, which is what lets the existing check see
        the whole payload."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            decided = keel_gate.governance(self.mixed(root, project))
            self.assertIn(UNVERIFIABLE_RELPATH, decided.covered)
            self.assertTrue(decided.projects)
            for _root, judged in decided.projects:
                self.assertIn(UNVERIFIABLE_RELPATH, [raw for raw, _norm in judged])

    def test_every_payload_entry_is_accounted_for_exactly_once(self) -> None:
        """The invariant itself, over every shape this task introduced."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            other = armed(root / "other", plan=False)
            deep = project.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2))
            loose = str(root / "loose" / "note.txt")
            shapes = {
                "in project": write_event(project, ORDINARY_RELPATH),
                "foreign": write_event(root, str(project / ORDINARY_RELPATH)),
                "two projects": write_event(
                    root, str(project / ORDINARY_RELPATH), str(other / ORDINARY_RELPATH)
                ),
                "armed and loose": write_event(
                    root, str(project / ORDINARY_RELPATH), loose
                ),
                "armed and unverifiable": self.mixed(root, project),
                "armed and unattributable": write_event(
                    root, str(project / ORDINARY_RELPATH), str(deep / "app.py")
                ),
                "nothing armed": write_event(root / "elsewhere", "note.txt", loose),
                "unverifiable alone, nothing armed": write_event(
                    root / "elsewhere", UNVERIFIABLE_RELPATH
                ),
            }
            for label, event in shapes.items():
                with self.subTest(shape=label):
                    decided = keel_gate.governance(event)
                    buckets = (
                        set(decided.covered),
                        set(decided.outside),
                        set(decided.unresolved),
                        set(decided.ungated),
                    )
                    union = set().union(*buckets)
                    self.assertEqual(union, set(event.file_paths))
                    self.assertEqual(
                        sum(len(bucket) for bucket in buckets),
                        len(union),
                        "a target may not sit in two buckets at once",
                    )

    def test_an_unattributable_target_beside_an_armed_one_still_denies(self) -> None:
        """T187 RETRY - ``keel:reviewer-silent-failure``'s finding at 85% on
        the first cut: it checked only the SESSION's own tier and missed
        exactly this shape, which is the "armed and unattributable" fixture
        of ``test_every_payload_entry_is_accounted_for_exactly_once`` above -
        that test only ever asked ``governance`` for its partition; this one
        asks ``evaluate`` for its VERDICT, which the first cut never checked.

        ``root`` (the session) is UNARMED, so a check of the session's tier
        alone would announce-and-allow. But ``project`` - which genuinely
        governs the FIRST target of this same payload - is tier 2 and
        enforcing, so the corrected rule (ANY governing project enforcing
        denies, not just the session's own) must deny the SECOND, walk-
        exhausted target instead of waving the whole event through."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            deep = project.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2))
            verdict = keel_gate.evaluate(
                write_event(
                    root, str(project / ORDINARY_RELPATH), str(deep / "app.py")
                ),
                env={},
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")

    def test_the_accounting_guard_refuses_to_be_built_wrong(self) -> None:
        """The proof that the invariant is structural rather than decorative:
        each way of losing a target raises at construction."""
        with self.assertRaises(keel_gate.GateError):
            keel_gate.Governance(payload=("a.py",))
        with self.assertRaises(keel_gate.GateError):
            keel_gate.Governance(
                payload=("a.py",),
                projects=((Path("p"), (("a.py", "a"),)),),
                covered=frozenset({"a.py"}),
                outside=("a.py",),
            )
        with self.assertRaises(keel_gate.GateError):
            keel_gate.Governance(
                payload=("a.py",),
                projects=((Path("p"), (("a.py", "a"),)),),
                ungated=("a.py",),
            )
        with self.assertRaises(keel_gate.GateError):
            keel_gate.Governance(payload=("a.py",), covered=frozenset({"a.py"}))

    def test_a_target_no_armed_project_governs_is_announced_not_silent(self) -> None:
        """Criterion 4 kept, and said out loud: the loose target is still
        permitted, and a reader is told it was decided by nobody."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            loose = root / "loose" / "note.txt"
            loose.parent.mkdir(parents=True, exist_ok=True)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.evaluate(
                    write_event(root, str(project / ORDINARY_RELPATH), str(loose)),
                    env={},
                )
            self.assertEqual(verdict.decision, "allow")
            self.assertIn("NO ARMED PROJECT GOVERNS", stderr.getvalue())
            self.assertIn("note.txt", stderr.getvalue())

    def test_the_notice_relativises_and_redacts_the_target(self) -> None:
        """T187 item 2 (accept 3), the security reviewer's actual finding at
        82%: the raw absolute path - home directory and account name
        included - must never reach stderr, only a relativised-then-redacted
        form, matching every sibling notice in this file and the audit field
        for this same refusal. Pinned on CONTENT, not merely that it fires."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            # "Somewhere" keeps the "Users" segment OUT of the common prefix
            # ``relativise`` shares with ``root`` (itself under this
            # machine's own ``Users\<realname>`` tree) - otherwise relpath's
            # climb consumes "Users" into the shared ancestor and the
            # home-shape screen never sees the word at all.
            outside = str(
                Path(root.anchor) / "Somewhere" / "Users" / "someone-else" / "secret.py"
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.evaluate(
                    write_event(root, str(project / ORDINARY_RELPATH), outside),
                    env={},
                )
            printed = stderr.getvalue()
            self.assertEqual(verdict.decision, "allow")
            self.assertIn("NO ARMED PROJECT GOVERNS", printed)
            self.assertNotIn(outside, printed, "the raw absolute path leaked")
            self.assertNotIn("someone-else", printed, "the account name leaked")
            self.assertIn(
                "[home-path]", printed, "the home-shape marker must replace it"
            )
            self.assertIn("secret.py", printed, "the basename itself may survive")

    def test_nothing_armed_anywhere_stays_ungated_and_quiet(self) -> None:
        """The other side of the announcement: when NO project governs the event
        there is nothing to announce and nothing to refuse - the unarmed answer,
        unchanged, a malformed path included."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event = write_event(root, "note.txt", UNVERIFIABLE_RELPATH)
            decided = keel_gate.governance(event)
            self.assertEqual(set(decided.ungated), set(event.file_paths))
            self.assertEqual(decided.projects, ())
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_gate.evaluate(event, env={})
            self.assertEqual(verdict.gate, "unarmed")
            self.assertNotIn("NO ARMED PROJECT GOVERNS", stderr.getvalue())


class TestTheSessionsProjectStillJudgesEveryTarget(unittest.TestCase):
    """The property the security reviewer verified against the PREVIOUS shape,
    re-pinned against this one: the walk only ADDS judges. The session's own
    project keeps judging every target, so no foreign or nested project's weaker
    verdict can override a stricter one."""

    def test_the_session_project_is_first_and_judges_the_whole_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = armed(root / "here", plan=True)
            there = armed(root / "there", plan=True)
            event = write_event(
                here,
                ORDINARY_RELPATH,
                str(there / ORDINARY_RELPATH),
                str(root / "loose.txt"),
            )
            decided = keel_gate.governance(event)
            self.assertEqual(decided.projects[0][0], Path(canonical(here)))
            self.assertEqual(
                [raw for raw, _norm in decided.projects[0][1]],
                list(event.file_paths),
                "the session's project judges every target, as it always did",
            )
            self.assertEqual(decided.outside, ())

    def test_a_foreign_allow_never_overrides_the_sessions_deny(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = armed(root / "here", plan=False)
            there = armed(root / "there", plan=True)
            verdict = keel_gate.evaluate(
                write_event(here, str(there / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")

    def test_a_foreign_deny_beats_the_sessions_allow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            here = armed(root / "here", plan=True)
            there = armed(root / "there", plan=False)
            verdict = keel_gate.evaluate(
                write_event(here, str(there / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.detail.get("project"), canonical(there))

    def test_a_nested_project_cannot_weaken_the_one_above_it(self) -> None:
        """NEAREST WINS for arming, and the session's project still judges: a
        nested project with a fresh ledger cannot carry a write past the outer
        project that has none."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outer = armed(root / "outer", plan=False)
            inner = armed(outer / "vendor" / "inner", plan=True)
            self.assertEqual(
                keel_gate.resolve_project(inner / ORDINARY_RELPATH).root,
                Path(canonical(inner)),
                "the nearest arming file owns the target",
            )
            verdict = keel_gate.evaluate(
                write_event(outer, str(inner / ORDINARY_RELPATH)), env={}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")


class TestT189AncestryNarrowsPreWriteOnly(unittest.TestCase):  # keel-leak: ignore - CamelCase class name caught by the entropy heuristic
    """T189: the security reviewer's 80% finding on T187's retry, and the
    ruling that answers it
    (.keel/decisions/2026-08-20-the-ladder-binds-what-keel-cannot-attribute.md).

    T187's retry denied an unattributable pre_write TARGET whenever ANY
    governing project of the EVENT enforced - which let a project owning a
    DIFFERENT, unrelated target in the same payload decide the fate of one it
    had no structural claim to. T189 narrows this to an ANCESTRY test: deny
    only when an enforcing project's root is an ancestor of the unattributable
    target itself; short of that, the SESSION's own project's tier decides;
    short of that, announce and allow. pre_exec is UNCHANGED on purpose - a
    command is atomic, so every governing project already judges the whole of
    it - and this class pins the two kinds apart so a later reader does not
    "simplify" them back together.
    """

    def deep_under(self, base: Path) -> Path:
        """A directory further above ``base`` than the walk will climb."""
        return base.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2))

    def test_an_unrelated_enforcing_owner_does_not_deny_a_sibling_exhausted_target(
        self,
    ) -> None:
        """The security reviewer's exact scenario (T187 retry, 80%): an
        unarmed or tier-1 session writes one payload naming a file inside an
        UNRELATED tier-2 project and a walk-exhausted path that sits NOWHERE
        NEAR it. Today's (pre-T189) rule denies the whole event solely
        because the stranger enforces; the ancestry test must not."""
        for tier, label in ((None, "unarmed"), (1, "tier 1")):
            with self.subTest(session=label):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    if tier is not None:
                        armed(root, tier=tier, plan=True)
                    stranger = armed(root / "stranger", plan=True)
                    exhausted = str(
                        self.deep_under(root / "elsewhere") / "app.py"
                    )
                    owned = str(stranger / ORDINARY_RELPATH)
                    stderr = io.StringIO()
                    with redirect_stderr(stderr):
                        verdict = keel_gate.evaluate(
                            write_event(root, owned, exhausted), env={}
                        )
                    self.assertEqual(verdict.decision, "allow", label)
                    self.assertNotEqual(verdict.gate, "unresolved_project", label)
                    printed = stderr.getvalue()
                    self.assertIn("PROJECT UNRESOLVED", printed, label)
                    self.assertIn(
                        "PERMITTED BELOW THE ENFORCING TIER", printed, label
                    )

    def test_the_mirror_the_exhausted_path_under_the_enforcing_project_still_denies(
        self,
    ) -> None:
        """Same shape, one change: the unattributable path now sits INSIDE
        the enforcing project's own tree - the case exhaustion exists to
        catch - so the ancestry test must still deny it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = armed(root / "project", plan=True)
            owned = str(project / ORDINARY_RELPATH)
            exhausted = str(self.deep_under(project) / "app.py")
            verdict = keel_gate.evaluate(write_event(root, owned, exhausted), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")

    def test_pre_write_and_pre_exec_diverge_on_the_identical_shape(self) -> None:
        """The divergence, pinned directly: one unarmed session, one
        unrelated tier-2 owner, one sibling walk-exhausted path NOT under it.
        pre_write narrows (announce-and-allow); pre_exec keeps T187's wider
        rule (deny), because a command is atomic and every governing project
        already judges the whole of it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stranger = armed(root / "stranger", plan=True)
            exhausted = str(self.deep_under(root / "elsewhere") / "app.py")
            owned = str(stranger / ORDINARY_RELPATH)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                write_verdict = keel_gate.evaluate(
                    write_event(root, owned, exhausted), env={}
                )
            self.assertEqual(write_verdict.decision, "allow")
            self.assertIn("PROJECT UNRESOLVED", stderr.getvalue())

            exec_verdict = keel_gate.evaluate(
                exec_event(root, f"python {owned} {exhausted}"), env={}
            )
            self.assertEqual(exec_verdict.decision, "deny")
            self.assertEqual(exec_verdict.gate, "unresolved_project")

    def test_the_sessions_own_tier_denies_when_no_ancestor_can(self) -> None:
        """The FALLBACK, isolated from the ancestry test: the session stands
        INSIDE an enforcing project and the unattributable target sits
        somewhere else entirely - no project owns it, ancestor or not - so
        the session's own tier is what denies it, not ``_enforcing_ancestor``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = armed(root / "home", plan=True)
            elsewhere_exhausted = str(self.deep_under(root / "elsewhere") / "app.py")
            verdict = keel_gate.evaluate(write_event(home, elsewhere_exhausted), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "unresolved_project")

    def test_the_notice_names_the_pre_write_situation_truthfully(self) -> None:
        """T189 accept 4: the printed claim must stay TRUE even though a
        stranger project enforces elsewhere in the same payload - so it may
        no longer say "nothing governing this event has reached tier N",
        which would be false here, and must instead name THIS target's own
        situation (no ancestor enforces, and neither does the session)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stranger = armed(root / "stranger", plan=True)
            exhausted = str(self.deep_under(root / "elsewhere") / "app.py")
            owned = str(stranger / ORDINARY_RELPATH)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                keel_gate.evaluate(write_event(root, owned, exhausted), env={})
            printed = stderr.getvalue()
            self.assertIn("no ENFORCING", printed)
            self.assertIn("ancestor", printed)
            self.assertNotIn(
                "nothing governing this event has reached tier",
                printed,
                "false below T189: a stranger project DOES enforce elsewhere "
                "in this same payload",
            )


if __name__ == "__main__":  # pragma: no cover - parity with the other suites
    unittest.main(verbosity=int(os.environ.get("KEEL_TEST_VERBOSITY", "1")))
