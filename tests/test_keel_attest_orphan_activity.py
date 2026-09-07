#!/usr/bin/env python3
"""T233 step 3: ``keel attest`` reports ORPHAN ACTIVITY and UNATTRIBUTABLE
ACTIVITY, both by agent id alone - never by agent type.

Contract
--------
Reads   : nothing outside temporary directories it creates and removes.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

Six fixtures, one project, pinning all six cells the accept clause names:

  - an activity line whose ``agent_id`` falls OUTSIDE every delegation window
    recorded for that exact id -> ORPHAN ACTIVITY, reported as a discrepancy;
  - the SAME agent id's activity, timestamped INSIDE its own window -> not
    reported at all;
  - an activity line whose ``agent_type`` is set but whose ``agent_id`` is
    null - the shape every line carried before T233 - -> UNATTRIBUTABLE
    ACTIVITY, counted and shown, never guessed into a window by its type, and
    never itself a discrepancy;
  - a main-session line (both null) -> silent, appears in neither list;
  - an activity line with a non-null ``agent_id`` and a MISSING ``ts`` -> a
    genuine orphan candidate that cannot be placed in time, so it is neither
    cleared nor condemned as an orphan; it is reported as its own
    UNPARSEABLE ACTIVITY TIMESTAMP discrepancy instead of being dropped;
  - the same shape with a GARBAGE (unparseable) ``ts`` string -> the same
    UNPARSEABLE ACTIVITY TIMESTAMP discrepancy.

The delegation window itself is built from ``keel_stop``'s own matcher
(imported by ``keel_attest``, not restated - R15): a ``handoff_start``/
``handoff_end`` pair naming ``agent-1`` on its return, closed by the
``subagent_stop`` that names the same id.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_attest  # noqa: E402  (path must be set first)


def iso(offset_seconds: int) -> str:
    """A keel-format UTC timestamp, offset from now."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def make_project() -> tuple[Path, Path, str]:
    """A project with one closed delegation (agent id ``agent-1``) and four
    activity lines - one inside its window, one outside, one pre-T233
    shaped, one main-session. Returns ``(tmp, project, session)``; the
    caller owns the temporary directory's lifetime."""
    tmp = Path(tempfile.mkdtemp())
    project = tmp / "project"
    session = uuid.uuid4().hex
    plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(
        "- [x] T1 build the thing\n  Route: executor\n  Accept: tests pass\n",
        encoding="utf-8",
    )

    lines = [
        {"v": 1, "ts": iso(-700), "event": "session_start", "session": session},
        {
            "v": 1, "ts": iso(-600), "event": "handoff_start", "session": session,
            "tool_use_id": "u1", "subagent_type": "executor",
            "description": "T1: build the thing", "prompt_head": "TASK T1",
        },
        {
            "v": 1, "ts": iso(-595), "event": "handoff_end", "session": session,
            "tool_use_id": "u1", "subagent_type": "executor",
            "description": "T1: build the thing", "prompt_head": "TASK T1",
            "agent_id": "agent-1",
        },
        {
            "v": 1, "ts": iso(-590), "event": "subagent_stop", "session": session,
            "agent_id": "agent-1",
        },
        # Inside the window [-600, -590]: must NOT be reported.
        {
            "v": 1, "ts": iso(-597), "event": "activity", "session": session,
            "agent_id": "agent-1", "agent_type": "executor",
            "tool": "Write", "detail": "in-window.py",
        },
        # Outside every window naming agent-1 (window closed at -590): the
        # ORPHAN.
        {
            "v": 1, "ts": iso(-100), "event": "activity", "session": session,
            "agent_id": "agent-1", "agent_type": "executor",
            "tool": "Write", "detail": "orphan.py",
        },
        # agent_type set, agent_id null: the pre-T233 shape. UNATTRIBUTABLE,
        # never guessed into a window.
        {
            "v": 1, "ts": iso(-594), "event": "activity", "session": session,
            "agent_type": "executor", "tool": "Edit", "detail": "unattributable.py",
        },
        # Both null: main-session work. Silent.
        {
            "v": 1, "ts": iso(-593), "event": "activity", "session": session,
            "agent_type": None, "tool": "Read", "detail": "main-session.py",
        },
        # agent_id non-null (a genuine orphan candidate), ts missing entirely:
        # can be neither cleared nor condemned as an orphan -> its own
        # UNPARSEABLE ACTIVITY TIMESTAMP discrepancy, never dropped.
        {
            "v": 1, "event": "activity", "session": session,
            "agent_id": "agent-1", "agent_type": "executor",
            "tool": "Bash", "detail": "missing-ts.py",
        },
        # Same shape, ts present but garbage (does not parse) -> the same
        # UNPARSEABLE ACTIVITY TIMESTAMP discrepancy.
        {
            "v": 1, "ts": "not-a-timestamp", "event": "activity", "session": session,
            "agent_id": "agent-2", "agent_type": "executor",
            "tool": "Edit", "detail": "garbage-ts.py",
        },
    ]
    audit = project.joinpath(*AUDIT_RELPATH)
    audit.parent.mkdir(parents=True)
    with open(audit, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return tmp, project, session


class OrphanActivityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp, self.project, self.session = make_project()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.report = keel_attest.attest(self.project, self.session)

    def test_the_orphan_is_reported_as_a_discrepancy(self) -> None:
        orphans = [
            row for row in self.report["discrepancies"]
            if row["verdict"].startswith(keel_attest.ORPHAN_ACTIVITY_VERDICT_PREFIX)
        ]
        self.assertEqual(len(orphans), 1, self.report["discrepancies"])
        self.assertIn("agent-1", orphans[0]["verdict"])
        self.assertFalse(self.report["clean"])

    def test_activity_inside_its_own_window_is_not_reported(self) -> None:
        orphan_titles = " ".join(
            row["title"] for row in self.report["discrepancies"]
            if row["verdict"].startswith(keel_attest.ORPHAN_ACTIVITY_VERDICT_PREFIX)
        )
        self.assertNotIn("in-window.py", orphan_titles)
        self.assertIn("orphan.py", orphan_titles)

    def test_a_null_id_agent_typed_record_is_unattributable_not_orphaned(self) -> None:
        unattributable = self.report["unattributable_activity"]
        self.assertEqual(len(unattributable), 1, unattributable)
        self.assertEqual(unattributable[0]["detail"], "unattributable.py")
        # Never counted as a discrepancy of its own.
        for row in self.report["discrepancies"]:
            self.assertNotIn("unattributable.py", row["title"])

    def test_a_main_session_record_is_silent(self) -> None:
        haystack = json.dumps(self.report, default=str)
        self.assertNotIn("main-session.py", haystack)

    def test_a_named_agent_with_missing_ts_is_its_own_discrepancy(self) -> None:
        unparseable = [
            row for row in self.report["discrepancies"]
            if row["verdict"].startswith(keel_attest.UNPARSEABLE_ACTIVITY_TS_VERDICT_PREFIX)
        ]
        titles = " ".join(row["title"] for row in unparseable)
        self.assertIn("missing-ts.py", titles, self.report["discrepancies"])
        # Never bucketed as ORPHAN ACTIVITY - a missing ts proves nothing.
        orphans = [
            row for row in self.report["discrepancies"]
            if row["verdict"].startswith(keel_attest.ORPHAN_ACTIVITY_VERDICT_PREFIX)
        ]
        self.assertNotIn("missing-ts.py", " ".join(row["title"] for row in orphans))

    def test_a_named_agent_with_garbage_ts_is_its_own_discrepancy(self) -> None:
        unparseable = [
            row for row in self.report["discrepancies"]
            if row["verdict"].startswith(keel_attest.UNPARSEABLE_ACTIVITY_TS_VERDICT_PREFIX)
        ]
        self.assertEqual(len(unparseable), 2, self.report["discrepancies"])
        titles = " ".join(row["title"] for row in unparseable)
        self.assertIn("garbage-ts.py", titles, self.report["discrepancies"])
        # Named clearly enough to find in the log: agent id and tool appear
        # in the verdict text itself.
        verdicts = " ".join(row["verdict"] for row in unparseable)
        self.assertIn("agent-1", verdicts)
        self.assertIn("agent-2", verdicts)
        self.assertIn("Bash", verdicts)
        self.assertIn("Edit", verdicts)

    def test_unparseable_activity_timestamp_moves_the_exit_code(self) -> None:
        # Same bucket, same exit-code effect as UNPARSEABLE TASK ID: this is
        # malformed data on a genuine orphan candidate, not the benign
        # pre-T233 UNATTRIBUTABLE shape, so it makes the run unclean.
        self.assertFalse(self.report["clean"])


if __name__ == "__main__":
    unittest.main()
