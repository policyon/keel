#!/usr/bin/env python3
"""A blocked stop says WHICH items, not only how many.

Contract
--------
Reads   : ``hooks/keel_stop.py`` - as an imported module for the pure cases and
          as the launcher a harness actually runs
          (``python hooks/keel_hook.py stop``) for the production ones - plus
          this repository's own ``.keel/audit/keel-audit.jsonl``, read only, for
          the "older lines still parse" case.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, and with the loop-safety
          marker's temp directory redirected into the scratch tree, so a
          developer's own shell cannot change what a test observes and one case
          can never suppress the next one's block.

What this file is for
---------------------
T130 accept 2. The stop gate has always COUNTED what it denied over - the
``open_items`` and ``stale_inflight_items`` numbers have been on the
``stop_block`` line since the gate was written - and a count alone is a fact
nobody can look up. The identifiers beside those counts (``open_item_ids``,
``stale_inflight_item_ids``) are named for what keel computes, and every case
here asserts them against a ledger the case itself wrote.

Three properties are worth stating separately, because each is its own way to
get this wrong:

* the COUNT stays the true total when the LIST is capped, so a truncation is
  read off the line rather than hidden in it (convention 7);
* an item with no task id still yields an identifier, because an unlabelled
  item is precisely the one nobody can find from a number;
* the accounting is ADDITIVE - every field an older ``stop_block`` line
  carried is still on the new one, unchanged.

Both directions are exercised for each half of the accounting: a ledger that
blocks and a ledger that does not.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

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
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")
REAL_AUDIT = REPO_ROOT.joinpath(*AUDIT_RELPATH)

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402  (path must be set first)
import keel_stop  # noqa: E402
from keel_published_cut import contradiction, is_published_cut  # noqa: E402

#: The four detail fields a blocked stop now carries. Spelled out rather than
#: imported: a guard that reads its expectation out of the code under test
#: cannot see that code rename a field.
COUNT_FIELDS = ("open_items", "stale_inflight_items")
ID_FIELDS = ("open_item_ids", "stale_inflight_item_ids")


def fresh_session() -> str:
    """A session id no other case has used - the loop-safety marker is keyed on
    it, and a reused id would let one case's block silently allow the next."""
    return uuid.uuid4().hex[:16]


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def arm(project: Path, *, tier: int = 2) -> None:
    """A project keel enforces against: ``.keel/`` and an enforcing tier."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )


def write_ledger(project: Path, session: str, body: str) -> Path:
    """This session's ledger, at the one path the stop gate consults."""
    plans = project / ".keel" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"keel-plan-{session[:8]}.md"
    path.write_text(body, encoding="utf-8")
    return path


def stop_event(project: Path, session: str) -> keel_events.KeelEvent:
    """One Stop event in the shape the adapter hands the gate."""
    return keel_events.KeelEvent(
        kind="stop",
        cwd=project,
        session_id=session,
        raw={"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False},
    )


def run_stop(project: Path, session: str, scratch: Path) -> subprocess.CompletedProcess:
    """Run the stop hook as the harness runs it: subprocess, JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), "stop"],
        input=json.dumps(
            {"hook_event_name": "Stop", "session_id": session, "cwd": str(project),
             "stop_hook_active": False}
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def blocks(project: Path, session: str) -> list[dict[str, Any]]:
    """Every ``stop_block`` line a project's audit log holds."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.exists():
        return []
    return [
        line
        for line in (
            json.loads(raw)
            for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        )
        if line.get("event") == "stop_block"
    ]


class TestTheIdentifierOfOneItem(unittest.TestCase):
    """``item_identifier`` alone: pure, and never allowed to return nothing."""

    def test_a_leading_task_id_is_the_identifier(self) -> None:
        for text, expected in (
            ("T130 - session records name the model", "T130"),
            ("T7b — a lettered id still reads", "T7b"),
            ("**T131** emphasised at the head", "T131"),
            ("`T99` in code marks", "T99"),
            ("  T42 leading whitespace", "T42"),
        ):
            with self.subTest(text=text):
                self.assertEqual(keel_stop.item_identifier(text), expected)

    def test_an_id_mentioned_mid_sentence_never_names_the_item(self) -> None:
        """An id found in the prose names the item this one CITES. Taking it
        would file the block under somebody else's task."""
        identifier = keel_stop.item_identifier("finish what T130 started")
        self.assertNotEqual(identifier, "T130")
        self.assertTrue(identifier.startswith("finish what"))

    def test_an_unlabelled_item_falls_back_to_a_bounded_head_of_its_text(self) -> None:
        long_item = "write the thing " * 20
        identifier = keel_stop.item_identifier(long_item)
        self.assertTrue(identifier)
        self.assertLessEqual(len(identifier), keel_stop.ITEM_LABEL_CHARS)
        self.assertTrue(long_item.startswith(identifier))

    def test_newlines_collapse_so_one_identifier_stays_one_field(self) -> None:
        identifier = keel_stop.item_identifier("wrapped item\n  continued here")
        self.assertNotIn("\n", identifier)
        self.assertIn("wrapped item continued", identifier)

    def test_nothing_at_all_still_yields_a_name_never_a_blank(self) -> None:
        for value in ("", "   ", "\n", None, 5, {"a": 1}, ["a"]):
            with self.subTest(value=value):
                identifier = keel_stop.item_identifier(value)
                self.assertTrue(identifier.strip(), "a blank would read as a missing entry")

    def test_the_identifier_function_never_raises(self) -> None:
        """It runs inside ``evaluate``: a throw there would turn a clean stop
        block into an internal_error, which is a worse message for the same
        decision."""

        class Hostile:
            def __str__(self) -> str:
                raise RuntimeError("deliberate fault")

        self.assertTrue(keel_stop.item_identifier(Hostile()))

    def test_the_list_is_capped_while_the_count_beside_it_is_not(self) -> None:
        items = [f"T{n} an item" for n in range(1, keel_stop.MAX_ITEM_IDS + 6)]
        identifiers = keel_stop.item_identifiers(items)
        self.assertEqual(len(identifiers), keel_stop.MAX_ITEM_IDS)
        self.assertLess(len(identifiers), len(items), "the truncation must be visible")
        self.assertEqual(identifiers[0], "T1", "ledger order, first item first")


class TestABlockedStopNamesItsItems(unittest.TestCase):
    """The verdict's own detail, computed from a ledger this case wrote."""

    def test_open_items_are_counted_and_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(
                project,
                session,
                "# ledger\n\n- [x] T1 - done\n- [ ] T2 - still open\n"
                "- [ ] T3 - also open\n",
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["open_items"], 2)
            self.assertEqual(verdict.detail["open_item_ids"], ["T2", "T3"])
            self.assertEqual(
                verdict.detail["stale_inflight_items"], 0, "no [~] item in this ledger"
            )
            self.assertEqual(verdict.detail["stale_inflight_item_ids"], [])

    def test_stale_inflight_items_are_counted_and_named_separately(self) -> None:
        """A ``[~]`` with no open hand-off on record is the OTHER half of the
        accounting, and it is kept in its own field rather than merged: which
        list an item is on is the difference between 'never started' and
        'started and nothing came back'."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "# ledger\n\n- [~] T9 - dispatched, nothing back\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["open_items"], 0)
            self.assertEqual(verdict.detail["open_item_ids"], [])
            self.assertEqual(verdict.detail["stale_inflight_items"], 1)
            self.assertEqual(verdict.detail["stale_inflight_item_ids"], ["T9"])

    def test_a_mixed_ledger_keeps_the_two_lists_apart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(
                project,
                session,
                "- [ ] T20 - open\n- [~] T21 - in flight\n- [!] T22 - blocked\n",
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertEqual(verdict.detail["open_item_ids"], ["T20"])
            self.assertEqual(verdict.detail["stale_inflight_item_ids"], ["T21"])

    def test_an_unlabelled_open_item_is_still_findable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] rename the survey module and retest\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertEqual(verdict.detail["open_items"], 1)
            self.assertEqual(len(verdict.detail["open_item_ids"]), 1)
            self.assertIn("rename the survey module", verdict.detail["open_item_ids"][0])

    def test_a_long_ledger_caps_the_list_and_keeps_the_count_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            total = keel_stop.MAX_ITEM_IDS + 7
            write_ledger(
                project,
                session,
                "".join(f"- [ ] T{n} - open\n" for n in range(1, total + 1)),
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertEqual(verdict.detail["open_items"], total)
            self.assertEqual(len(verdict.detail["open_item_ids"]), keel_stop.MAX_ITEM_IDS)
            self.assertLess(
                len(verdict.detail["open_item_ids"]),
                verdict.detail["open_items"],
                "count and list disagree ON PURPOSE, so the truncation is readable",
            )

    def test_a_terminal_ledger_allows_and_records_no_accounting_at_all(self) -> None:
        """The other direction. An allow writes no ``stop_block`` line, so
        there is nothing for these fields to be wrong about."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [x] T1 - done\n- [!] T2 - blocked, reason given\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertFalse(verdict.blocking)
            for field in COUNT_FIELDS + ID_FIELDS:
                self.assertNotIn(field, verdict.detail)


class TestTheBlockReachesTheLogThroughTheLauncher(unittest.TestCase):
    """Asserted on bytes a subprocess left on disk, not on a return value."""

    def test_a_real_block_writes_the_counts_and_the_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] T130 - open\n- [ ] T131 - open\n")
            result = run_stop(project, session, scratch)
            self.assertEqual(result.returncode, 2, result.stderr)
            recorded = blocks(project, session)
            self.assertEqual(len(recorded), 1)
            detail = recorded[0]["detail"]
            self.assertEqual(detail["open_items"], 2)
            self.assertEqual(detail["open_item_ids"], ["T130", "T131"])
            self.assertEqual(detail["stale_inflight_items"], 0)
            self.assertEqual(detail["stale_inflight_item_ids"], [])

    def test_the_line_keeps_every_field_it_carried_before(self) -> None:
        """Additive only: the older shape is a subset of the newer one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] T5 - open\n")
            self.assertEqual(run_stop(project, session, scratch).returncode, 2)
            line = blocks(project, session)[0]
            for field in ("v", "ts", "event", "gate", "session", "detail"):
                self.assertIn(field, line)
            self.assertEqual(line["gate"], "stop")
            self.assertEqual(line["session"], session)
            for field in COUNT_FIELDS:
                self.assertIn(field, line["detail"], "a count that was there must stay")

    def test_an_allowed_stop_still_writes_no_block_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [x] T5 - done\n")
            result = run_stop(project, session, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(blocks(project, session), [])


class TestOlderBlockLinesStillParse(unittest.TestCase):
    """The additive claim, against a log nobody wrote to pass this test."""

    def test_this_repositorys_own_stop_block_lines_all_parse(self) -> None:
        self.assertTrue(REAL_AUDIT.exists(), "the repository's own audit log is the fixture")
        recorded = [
            json.loads(raw)
            for raw in REAL_AUDIT.read_text(encoding="utf-8", errors="replace").splitlines()
            if raw.strip() and '"stop_block"' in raw
        ]
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            self.assertEqual(
                recorded, [], "a published cut declares no stop_block lines to check"
            )
            return
        self.assertTrue(recorded, "no historical block lines to check against")
        for line in recorded:
            self.assertEqual(line["event"], "stop_block")
            self.assertIn("session", line)
            self.assertIsInstance(line.get("detail", {}), dict)

    def test_a_reader_of_the_old_shape_reads_the_new_one_the_same_way(self) -> None:
        """The old shape's question - 'how many items were unaccounted for?' -
        is answered by the new line with the same keys and the same meaning."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] T1 - open\n- [ ] T2 - open\n")
            detail = keel_stop.evaluate(stop_event(project, session), {}).detail
            self.assertEqual(
                {field: detail[field] for field in COUNT_FIELDS},
                {"open_items": 2, "stale_inflight_items": 0},
            )


class TestTheAccountingNeverCostsTheGateItsVerdict(unittest.TestCase):
    """The stop hook's declared policy, now covering the added fields: the
    AUDIT may never fail the gate, and an unarmed project is never blocked by
    a fault in keel's own accounting."""

    def test_a_throwing_audit_write_leaves_the_verdict_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] T1 - open\n")
            original = keel_stop.append_audit

            def boom(*_args: Any, **_kwargs: Any) -> None:
                raise OSError("deliberate fault: the audit directory is unwritable")

            keel_stop.append_audit = boom
            try:
                verdict = keel_stop.run(stop_event(project, session), {})
            finally:
                keel_stop.append_audit = original
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.gate, "stop", "the block is the gate's, not an error's")

    def test_a_throwing_identifier_in_an_unarmed_project_never_blocks(self) -> None:
        """Fail-open where keel was never armed: the session belongs to the
        user, not to a gate that could not compute its own accounting."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
            original = keel_stop.policy_tier

            def boom(_cwd: Path) -> int:
                raise RuntimeError("deliberate fault reading the tier")

            keel_stop.policy_tier = boom
            try:
                verdict = keel_stop.run(stop_event(project, session), {})
            finally:
                keel_stop.policy_tier = original
            self.assertFalse(verdict.blocking)

    def test_the_kill_switch_still_stands_the_whole_gate_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [ ] T1 - open\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {"KEEL_GATE": "off"})
            self.assertFalse(verdict.blocking)
            self.assertEqual(verdict.detail, {})


if __name__ == "__main__":
    unittest.main()
