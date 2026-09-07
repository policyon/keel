#!/usr/bin/env python3
"""T186 - the stop gate resolves the GOVERNING project, not the session's cwd.

Contract
--------
Reads   : ``hooks/keel_stop.py`` and ``hooks/keel_gate.py`` as modules. Every
          fixture is built under a temporary directory, so no assertion here
          depends on the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

The defect, as it shipped after T178
-------------------------------------
T178 taught ``keel_gate.py`` to resolve arming from the nearest project AT OR
ABOVE a write's target - a session can be GOVERNED BY A PROJECT IT IS NOT
SITTING IN. ``hooks/keel_stop.py`` did not move with it: it read
``policy_tier(event.cwd)``/``read_ledger(event.cwd, ...)`` directly, exactly
the shape ``keel_gate.py`` carried before T178. So a session standing in an
unadopted SUBDIRECTORY of an armed project - an ordinary way to work - had its
open ledger items silently un-accounted-for: the stop gate found no
``.keel/keel-policy.md`` exactly at its own directory and allowed, the same
verdict a project that never adopted keel gets. ``TestTheHoleTheTaskCloses``
below is that hole turned into an assertion; it fails on the code that shipped
before this task.

What this covers, clause by clause
-----------------------------------
1. THE HOLE (accept 1, 2). ``TestTheHoleTheTaskCloses`` fails on pre-T186 code:
   a session in a subdirectory of an armed project is BLOCKED on its open
   ledger items, not silently allowed.
2. THE LEDGER MOVES WITH THE GOVERNING PROJECT (accept 2). The refusal names
   the ABSOLUTE path of the ledger the governing project expects -
   ``TestTheRefusalNamesTheAbsolutePath``.
3. THE AUDIT TRAIL FOLLOWS THE GOVERNING PROJECT TOO. A ``stop_block`` line is
   filed in the governing project's OWN log, with a relative ``session_cwd``,
   never in the (possibly unadopted) directory the session stood in -
   ``TestTheBlockIsFiledAgainstTheGoverningProject``.
4. THE FAILURE POLICY FOLLOWS THE SAME RESOLUTION (accept 1, mirroring T178's
   own companion clause for ``keel_gate.py``): an internal error while judging
   a session governed by a FOREIGN armed project fails CLOSED, not open just
   because the session's own directory carries no arming file -
   ``TestTheFailurePolicyFollowsTheGoverningProject``. FAILS on pre-T186 code.
5. UNRESOLVED IS REPORTED, NEVER READ AS UNARMED (T186's own decision, argued
   in ``keel_stop.resolve_governing_project``'s docstring): a session whose own
   governing project the walk could not resolve - budget exhausted - gets its
   own gate (``unresolved_project``), its own stderr notice and its own audit
   line, never the SAME verdict an ordinary unadopted project gets -
   ``TestExhaustionIsReportedNotSwallowed``. FAILS on pre-T186 code (which
   reads ``gate == "unarmed"`` for this exact fixture).
6. NO WIDENING. The ORDINARY case - the session's own directory IS the
   governing project, which is every fixture that predates this task - stays
   byte-identical: no ``project`` key on the verdict, no addendum in the
   message - ``TestTheOrdinaryCaseIsUnchanged``.
7. THE HANDOFF READ DELIBERATELY DOES NOT FOLLOW THE LEDGER. ``[~]``
   verification stays keyed on the session's own directory, because that is
   where ``hooks/keel_capture.py`` actually files handoff evidence (a
   DIFFERENT, out-of-scope cwd-only check - see this suite's own note) - moving
   the read to the governing project would make every real hand-off
   unfindable. ``TestTheHandoffReadFollowsTheWriteNotTheLedger`` pins both
   directions.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_stop  # noqa: E402

#: A contract-clean, terminal ledger - used where a case must NOT block on
#: accounting, only on arming/resolution.
CLEAN_LEDGER = "# Plan\n\n- [x] T1 done\n- [!] T2 blocked, reason given\n"

#: A ledger with one open item - the ordinary trigger for a block.
OPEN_LEDGER = "# Plan\n\n- [ ] T9 still open\n"


def fresh_session() -> tuple[str, str]:
    """A (session_id, sess8) pair no other case has used."""
    session = uuid.uuid4().hex
    return session, session[:8]


def arm(project: Path, *, tier: int = 2) -> Path:
    """A fixture project: ``.keel/keel-policy.md`` declaring ``tier``."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )
    return project


def write_ledger(project: Path, sess8: str, body: str) -> Path:
    """This session's ledger, at the one path the stop gate consults."""
    plans = project / ".keel" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"keel-plan-{sess8}.md"
    path.write_text(body, encoding="utf-8")
    return path


def stop_event(cwd: Path, session: str) -> keel_events.KeelEvent:
    """One Stop event in the shape the adapter hands the gate."""
    return keel_events.KeelEvent(
        kind="stop",
        cwd=cwd,
        session_id=session,
        raw={"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False},
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


def canonical(path: Path) -> str:
    """A path as the gate spells it: symlink-resolved (and, on Windows, with
    every 8.3 short component expanded, via realpath)."""
    return str(Path(os.path.realpath(str(path))))


def deep_under(base: Path) -> Path:
    """A directory further above ``base`` than the walk will climb - the same
    fixture shape ``tests/test_keel_target_arming_t178.py`` uses for
    ``PROJECT_UNKNOWN``."""
    return base.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2))


class TestTheHoleTheTaskCloses(unittest.TestCase):
    """Accept 1/2: FAILS on the code that shipped before T186.

    A session standing in an unadopted subdirectory of an armed project must
    be held to that project's ledger, not read as unarmed.
    """

    def test_a_session_in_a_subdirectory_is_blocked_by_the_project_above_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            verdict = keel_stop.evaluate(stop_event(subdir, session), env={})
            self.assertEqual(verdict.decision, "deny", verdict.reason)
            self.assertEqual(verdict.gate, "stop")
            self.assertNotEqual(
                verdict.gate, "unarmed",
                "an armed project's ledger read as though nothing governs this session",
            )
            self.assertEqual(verdict.detail.get("open_items"), 1)

    def test_the_same_session_from_inside_the_project_is_unaffected(self) -> None:
        """The regression guard: the ordinary case must still block too."""
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            verdict = keel_stop.evaluate(stop_event(project, session), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "stop")

    def test_a_clean_ledger_in_the_foreign_project_allows(self) -> None:
        """The other direction: nothing open, nothing blocks - even governed
        from a subdirectory."""
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, CLEAN_LEDGER)
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            verdict = keel_stop.evaluate(stop_event(subdir, session), env={})
            self.assertEqual(verdict.decision, "allow")


class TestTheRefusalNamesTheAbsolutePath(unittest.TestCase):
    """Accept 2: a refusal that cannot be acted on is a dead end - the model
    would write the ledger beside itself and be refused again for the same
    reason, exactly the problem ``keel_gate._named_project`` solves for a
    write."""

    def test_the_message_names_the_governing_project_and_the_absolute_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            verdict = keel_stop.evaluate(stop_event(subdir, session), env={})
            self.assertIn("GOVERNING PROJECT", verdict.reason)
            expected_ledger = Path(canonical(project)).joinpath(
                ".keel", "plans", f"keel-plan-{sess8}.md"
            )
            self.assertIn(str(expected_ledger), verdict.reason)
            self.assertIn(canonical(project), verdict.reason)


class TestTheBlockIsFiledAgainstTheGoverningProject(unittest.TestCase):
    """Accept 2/3: the audit trail follows the governing project, never the
    (possibly unadopted) directory the session stood in."""

    def test_the_stop_block_line_lands_in_the_projects_own_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            verdict = keel_stop.run(stop_event(subdir, session), env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertFalse(
                (subdir / ".keel").exists(),
                "no state was created in the directory the session stood in",
            )
            lines = audit_lines(project)
            self.assertTrue(lines, "the block must be audited against the project")
            last = lines[-1]
            self.assertEqual(last["event"], "stop_block")
            self.assertEqual(last["session"], session)
            self.assertNotIn(
                "project", last["detail"],
                "the absolute path must not survive into the persisted log (convention 5)",
            )
            self.assertIn("session_cwd", last["detail"])
            self.assertEqual(last["detail"]["session_cwd"], "src/sub")

    def test_the_ordinary_case_never_carries_a_session_cwd_field(self) -> None:
        """The ordinary case is a complete no-op for the new field (accept 4)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            verdict = keel_stop.run(stop_event(project, session), env={})
            self.assertEqual(verdict.decision, "deny")
            lines = audit_lines(project)
            self.assertNotIn("session_cwd", lines[-1]["detail"])
            self.assertNotIn("project", verdict.detail)


class TestTheFailurePolicyFollowsTheGoverningProject(unittest.TestCase):
    """Accept 1, mirroring T178's own companion clause: FAILS on pre-T186
    code, which chose fail-open/fail-closed on ``policy_present(event.cwd)`` -
    the session's own (here, unadopted) directory - rather than on the
    project that actually governs it."""

    def _boom(self, *_args: object, **_kwargs: object) -> keel_events.KeelVerdict:
        raise RuntimeError("deliberate fault")

    def test_a_crash_judging_a_session_governed_by_a_foreign_armed_project_fails_closed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, _sess8 = fresh_session()
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            original = keel_stop.evaluate
            keel_stop.evaluate = self._boom
            try:
                verdict = keel_stop.run(stop_event(subdir, session), env={})
            finally:
                keel_stop.evaluate = original
            self.assertEqual(verdict.decision, "deny", verdict.reason)
            self.assertIn("FAILED CLOSED", verdict.reason)

    def test_a_crash_judging_a_genuinely_unarmed_session_still_fails_open(self) -> None:
        """The other direction, unaffected: nothing governs this session at
        all, so the same crash still fails open."""
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare"
            bare.mkdir(parents=True)
            session, _sess8 = fresh_session()
            original = keel_stop.evaluate
            keel_stop.evaluate = self._boom
            try:
                verdict = keel_stop.run(stop_event(bare, session), env={})
            finally:
                keel_stop.evaluate = original
            self.assertEqual(verdict.decision, "allow")


class TestExhaustionIsReportedNotSwallowed(unittest.TestCase):
    """Accept 1 (via T186's own decision record in
    ``resolve_governing_project``): FAILS on pre-T186 code, which reads
    ``gate == "unarmed"`` for this exact fixture - the same verdict an
    ordinary unadopted project gets, with no signal that resolution merely
    ran out of budget."""

    def test_a_deep_session_directory_is_its_own_gate_not_unarmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep_cwd = deep_under(root)
            deep_cwd.mkdir(parents=True, exist_ok=True)
            self.assertTrue(
                keel_gate.resolve_project(deep_cwd).unknown,
                "the fixture must actually exhaust the walk's budget",
            )
            session, _sess8 = fresh_session()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_stop.evaluate(stop_event(deep_cwd, session), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "unresolved_project")
            self.assertNotEqual(
                verdict.gate, "unarmed",
                "budget exhaustion must not read as the same fact as no project at all",
            )
            printed = stderr.getvalue()
            self.assertIn("PROJECT UNRESOLVED", printed)
            self.assertIn(str(keel_gate.PROJECT_WALK_MAX_LEVELS), printed)

    def test_the_unresolved_case_is_also_on_the_audit_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep_cwd = deep_under(root)
            deep_cwd.mkdir(parents=True, exist_ok=True)
            session, _sess8 = fresh_session()
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                verdict = keel_stop.run(stop_event(deep_cwd, session), env={})
            self.assertEqual(verdict.decision, "allow")
            lines = audit_lines(deep_cwd)
            self.assertTrue(lines, "zero is not silence: something was unresolved here")
            self.assertEqual(lines[-1]["event"], "unresolved_project_allowed")
            self.assertEqual(lines[-1]["gate"], "unresolved_project")

    def test_one_level_inside_the_bound_still_resolves_the_governing_project(self) -> None:
        """The bound is what does the work above, not the fixture's depth: a
        session many directories below its project, but still within
        ``PROJECT_WALK_MAX_LEVELS`` of it, resolves the project - not the
        uncertain ``unresolved_project`` answer - exactly the same shape
        ``tests/test_keel_target_arming_t178.py`` pins for a write's target."""
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, CLEAN_LEDGER)
            inside = project.joinpath(*["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS - 2))
            inside.mkdir(parents=True, exist_ok=True)
            verdict = keel_stop.evaluate(stop_event(inside, session), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "stop", "resolved and read the (clean) ledger")


class TestTheOrdinaryCaseIsUnchanged(unittest.TestCase):
    """Accept 4: no widening. A genuinely unarmed project, and a project
    armed below the enforcing tier, both keep their pre-T186 verdicts."""

    def test_a_project_that_never_adopted_keel_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / "src").mkdir(parents=True)
            session, _sess8 = fresh_session()
            verdict = keel_stop.evaluate(stop_event(project, session), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "unarmed")

    def test_a_project_below_the_enforcing_tier_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project", tier=1)
            session, sess8 = fresh_session()
            write_ledger(project, sess8, OPEN_LEDGER)
            verdict = keel_stop.evaluate(stop_event(project, session), env={})
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.gate, "tier")


class TestTheHandoffReadFollowsTheWriteNotTheLedger(unittest.TestCase):
    """Clause 7: ``session_has_open_handoff`` stays keyed on the session's own
    directory even when the ledger/tier lookup follows the governing project
    - because ``hooks/keel_capture.py`` (a separate, out-of-scope cwd-only
    check, reported rather than fixed here per this task's own scope) still
    files hand-off evidence at the session's own directory. Both directions
    are pinned so a future reader cannot "simplify" this back to ``root``
    without noticing every real hand-off would then go unfound.
    """

    def _handoff_start(self, session: str) -> dict:
        # A CURRENT timestamp, deliberately - not a fixed date: a launch older
        # than LIVENESS_MS reads as activity-quiet-closed regardless of where
        # it is filed, which would make this fixture prove nothing about
        # WHICH directory the read follows.
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "event": "handoff_start",
            "session": session,
            "tool_use_id": "tool-1",
            "subagent_type": "keel:executor",
            "ts": now,
        }

    def test_handoff_evidence_at_the_sessions_own_directory_is_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [~] T9 dispatched\n")
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            keel_events.append_audit(subdir, self._handoff_start(session))
            verdict = keel_stop.evaluate(stop_event(subdir, session), env={})
            self.assertEqual(
                verdict.decision, "allow",
                "an open hand-off recorded at the session's own directory must be found",
            )

    def test_handoff_evidence_filed_only_at_the_governing_project_is_not_found(self) -> None:
        """The discriminating twin: the SAME line, but filed at ``root``
        instead of at the session's own directory, must NOT be picked up -
        proving the read follows ``event.cwd``, not the ledger's project."""
        with tempfile.TemporaryDirectory() as tmp:
            project = arm(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [~] T9 dispatched\n")
            subdir = project / "src" / "sub"
            subdir.mkdir(parents=True)
            keel_events.append_audit(project, self._handoff_start(session))
            verdict = keel_stop.evaluate(stop_event(subdir, session), env={})
            self.assertEqual(verdict.decision, "deny", "no hand-off visible at cwd: stale")
            self.assertEqual(verdict.detail.get("stale_inflight_items"), 1)


if __name__ == "__main__":
    unittest.main()
