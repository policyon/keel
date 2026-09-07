#!/usr/bin/env python3
"""Phase 3 review test suite - routing rule 3's escalation cycle, end to end.

Contract
--------
Reads   : hooks/keel_hook.py (the stop gate, invoked exactly as continuous
          integration invokes it) and scripts/keel.py (the ``attest`` CLI),
          run against fixture projects this module builds itself.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. The
          temporary directory is also the subprocess's TMP, so the stop
          gate's loop-safety marker never leaks between cases or between
          runs, and every subprocess runs with an environment holding no
          ``KEEL_*`` variable and no ``CLAUDE_PROJECT_DIR``.

What this proves
----------------
Routing rule 3 - "escalation is one retry, not a ladder without a top" - is
accountable at every station of its cycle. The standard attempt is a ``[~]``
ledger item backed by an OPEN hand-off on the audit record, and the stop gate
allows it; the review-fail deep retry is a second recorded hand-off, written
by the orchestrator as bookkeeping; the second failure is a ``[!]`` line with
a named blocker, which is terminal, and the stop gate allows the turn to end.
Both directions ship (convention 2): a ``[ ]`` item and an unverified ``[~]``
(no delegation on record) still block. Finally ``keel attest`` reconciles the
two recorded hand-offs against the ledger and exits clean, and its documented
discrepancy - an ``[x]`` completion with no delegation on record - is flagged
in a second fixture variant.

House style: fixtures are executed the way continuous integration will -
``python hooks/keel_hook.py stop`` as a real subprocess with JSON on stdin,
exit codes and output asserted - and the attest tool is executed as
``python scripts/keel.py attest``, so the exit codes asserted here are the
exit codes a caller gets. Audit lines copy the event shapes ``keel_capture``
writes and ``keel_stop``/``keel_attest`` read: a launch is a
``handoff_start`` plus a ``handoff_end`` moments later (a background-launch
acknowledgment inside ``BG_LAUNCH_MS``, which keeps the hand-off open), and a
close is a ``subagent_stop``. Only allow-direction stops share a session; a
block writes the loop-safety marker, so each blocking case runs in its own
session and its own TMP, which is what keeps this suite unflaky.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it. (Test module - it enforces nothing
at runtime; the failure policy under test is the stop gate's own.)

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
KEEL_CLI = REPO_ROOT / "scripts" / "keel.py"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

#: The armed policy every fixture project here carries: tier 2, the gate tier.
POLICY_TEXT = "---\ntier: 2\n---\n\n# keel policy - fixture project\n"


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def iso(offset_seconds: int) -> str:
    """A keel-format UTC timestamp, offset from now."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class ReviewCaseBase(unittest.TestCase):
    """Shared machinery: build a tier-2 fixture project, run the tools."""

    def make_project(self, root: Path, session: str, ledger: str) -> Path:
        """A fixture project armed at tier 2 with this session's ledger."""
        project = root / "project"
        policy = project / ".keel" / "keel-policy.md"
        policy.parent.mkdir(parents=True)
        with open(policy, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(POLICY_TEXT)
        self.write_ledger(project, session, ledger)
        return project

    def write_ledger(self, project: Path, session: str, ledger: str) -> None:
        """(Re)write this session's ledger, as the orchestrator would."""
        plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        with open(plan, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(ledger)

    def append_audit(self, project: Path, lines: list[dict[str, Any]]) -> None:
        """Append audit lines in keel's own shape: LF-only, UTF-8 JSONL."""
        audit = project.joinpath(*AUDIT_RELPATH)
        audit.parent.mkdir(parents=True, exist_ok=True)
        with open(audit, "a", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def invoke_stop(
        self, project: Path, scratch: Path, session: str
    ) -> subprocess.CompletedProcess:
        """Run the stop gate exactly as the harness does: JSON on stdin."""
        payload = {"session_id": session, "cwd": str(project), "hook_event_name": "Stop"}
        return subprocess.run(
            [sys.executable, "-B", str(HOOK), "stop"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=clean_env(scratch),
            cwd=str(project),
            timeout=60,
            check=False,
        )

    def run_attest(
        self, project: Path, scratch: Path, session: str, as_json: bool = False
    ) -> subprocess.CompletedProcess:
        """Run scripts/keel.py attest exactly as a caller would.

        T197: identity is read, never inferred from the log - ``--session``
        is now required here rather than left to the log's own
        ``session_start`` default, which this suite's subprocess would
        otherwise resolve from whatever ``CLAUDE_CODE_SESSION_ID`` happens to
        carry in the parent process, not this fixture's own session.
        """
        args = ["attest", "--project", str(project), "--session", session[:8]]
        if as_json:
            args.append("--json")
        return subprocess.run(
            [sys.executable, "-B", str(KEEL_CLI), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=clean_env(scratch),
            cwd=str(scratch),
            timeout=120,
            check=False,
        )

    def fixture_dirs(self, tmp: str) -> tuple[Path, Path]:
        """(project root parent, scratch TMP) inside one temporary directory."""
        root = Path(tmp)
        scratch = root / "tmp"
        scratch.mkdir()
        return root, scratch


class TestEscalationCycle(ReviewCaseBase):
    """Rule 3's cycle: standard -> review fail -> one deep retry -> [!]."""

    def test_cycle_is_accountable_end_to_end(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root, scratch = self.fixture_dirs(tmp)
            project = self.make_project(
                root,
                session,
                "# Plan\n\n- [~] T1: fix the parser | route: executor | AC: tests pass\n",
            )

            # (b) The standard attempt: a delegation is on the record. The
            # handoff_end lands moments after handoff_start - a background
            # launch acknowledgment inside BG_LAUNCH_MS, so the hand-off is
            # OPEN and the verified [~] must allow the turn to end.
            self.append_audit(
                project,
                [
                    {"v": 1, "ts": iso(-600), "event": "session_start", "session": session},
                    # T102: the launch tool names the agent in its RESULT, so
                    # the id lands on the RETURN half and the launch half
                    # records a null. The stop below names the same id, which
                    # is the only thing that attaches the two.
                    {
                        "v": 1,
                        "ts": iso(-120),
                        "event": "handoff_start",
                        "session": session,
                        "tool_use_id": "tu_std_1",
                        "agent_id": None,
                        "subagent_type": "executor",
                        "description": "T1: fix the parser",
                        "prompt_head": "TASK T1 - fix the parser",
                    },
                    {
                        "v": 1,
                        "ts": iso(-119),
                        "event": "handoff_end",
                        "session": session,
                        "tool_use_id": "tu_std_1",
                        "agent_id": "ag_std_1",
                        "subagent_type": "executor",
                        "description": "T1: fix the parser",
                        "prompt_head": "TASK T1 - fix the parser",
                    },
                ],
            )
            result = self.invoke_stop(project, scratch, session)
            detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            self.assertEqual(result.returncode, 0, detail)
            self.assertEqual(result.stdout, "", f"allow is silence, not JSON: {detail}")

            # (c) The executor returned and review found STATUS: fail, so the
            # orchestrator closes the first hand-off and launches the one
            # deep retry with the review findings attached - bookkeeping the
            # test writes exactly as the capture hook would have recorded it.
            self.append_audit(
                project,
                [
                    {
                        "v": 1,
                        "ts": iso(-60),
                        "event": "subagent_stop",
                        "session": session,
                        "agent_type": "executor",
                        "agent_id": "ag_std_1",
                    },
                    {
                        "v": 1,
                        "ts": iso(-50),
                        "event": "handoff_start",
                        "session": session,
                        "tool_use_id": "tu_deep_1",
                        "agent_id": None,
                        "subagent_type": "executor-deep",
                        "description": "T1: deep retry, review findings attached",
                        "prompt_head": "TASK T1 - retry; reviewer STATUS: fail findings attached",
                    },
                    {
                        "v": 1,
                        "ts": iso(-49),
                        "event": "handoff_end",
                        "session": session,
                        "tool_use_id": "tu_deep_1",
                        "agent_id": "ag_deep_1",
                        "subagent_type": "executor-deep",
                        "description": "T1: deep retry, review findings attached",
                        "prompt_head": "TASK T1 - retry; reviewer STATUS: fail findings attached",
                    },
                    {
                        "v": 1,
                        "ts": iso(-10),
                        "event": "subagent_stop",
                        "session": session,
                        "agent_type": "executor-deep",
                        "agent_id": "ag_deep_1",
                    },
                ],
            )

            # (d) The second failure: the ladder has a top. The ledger line
            # becomes [!] with the blocker named in the line, which is
            # terminal, so the stop gate must allow the turn to end.
            self.write_ledger(
                project,
                session,
                "# Plan\n\n- [!] T1: fix the parser | route: executor | AC: tests pass "
                "| blocker: review failed twice - parser still rejects a UTF-8 BOM\n",
            )
            result = self.invoke_stop(project, scratch, session)
            detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            self.assertEqual(result.returncode, 0, detail)
            self.assertEqual(result.stdout, "", f"allow is silence, not JSON: {detail}")

            # (f) Attestation: both recorded hand-offs reconcile against the
            # ledger - the [!] line has its delegation evidence and nothing
            # is a discrepancy, so the CLI exits 0.
            result = self.run_attest(project, scratch, session, as_json=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertTrue(report["clean"], report["discrepancies"])
            self.assertEqual(report["counts"]["handoff_start"], 2, report["counts"])
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T1", task)
            self.assertEqual(task["marker"], "!", task)
            self.assertEqual(task["verdict"], "ATTESTED", task)
            self.assertEqual(len(task["evidence"]), 2, task["evidence"])
            self.assertEqual(
                [item["agent"] for item in task["evidence"]],
                ["executor", "executor-deep"],
                "the cycle's two attempts, in order",
            )


class TestBothDirections(ReviewCaseBase):
    """Convention 2: the accountable cycle blocks where it must, too.

    Each blocking case runs in its own session AND its own TMP: a block
    writes the loop-safety marker, and a marker fresher than
    MARKER_TTL_SECONDS suppresses the next block for that session, so the
    two directions must never share either.
    """

    def assert_blocks(self, ledger: str, audit: list[dict[str, Any]], needle: str) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root, scratch = self.fixture_dirs(tmp)
            project = self.make_project(root, session, ledger)
            if audit:
                self.append_audit(project, audit)
            result = self.invoke_stop(project, scratch, session)
            detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            self.assertEqual(result.returncode, 2, detail)
            decoded = json.loads(result.stdout)
            block = decoded["hookSpecificOutput"]
            self.assertIn(block["permissionDecision"], ("ask", "deny"), detail)
            self.assertIn("STOP BLOCKED", block["permissionDecisionReason"], detail)
            self.assertIn(needle, block["permissionDecisionReason"], detail)
            last = json.loads(
                project.joinpath(*AUDIT_RELPATH)
                .read_text(encoding="utf-8")
                .splitlines()[-1]
            )
            self.assertEqual(last["event"], "stop_block", last)

    def test_open_item_still_blocks(self) -> None:
        """A [ ] item is not terminal; the cycle cannot end around it."""
        self.assert_blocks(
            "# Plan\n\n- [ ] T1: fix the parser | route: executor | AC: tests pass\n",
            [],
            "still open",
        )

    def test_unverified_inflight_still_blocks(self) -> None:
        """[~] is verified, never trusted: no delegation on record blocks."""
        session_start = {"v": 1, "ts": iso(-600), "event": "session_start", "session": "$other"}
        self.assert_blocks(
            "# Plan\n\n- [~] T1: fix the parser | route: executor | AC: tests pass\n",
            [session_start],
            "no active delegation",
        )


class TestAttestDiscrepancy(ReviewCaseBase):
    """attest's documented discrepancy: [x] with no delegation on record."""

    def test_completed_task_with_no_handoff_is_flagged(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root, scratch = self.fixture_dirs(tmp)
            project = self.make_project(
                root,
                session,
                "# Plan\n\n- [x] T9: claimed done | route: executor | AC: tests pass\n",
            )
            self.append_audit(
                project,
                [{"v": 1, "ts": iso(-600), "event": "session_start", "session": session}],
            )
            result = self.run_attest(project, scratch, session)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("UNATTESTED", result.stdout)


if __name__ == "__main__":
    unittest.main()
