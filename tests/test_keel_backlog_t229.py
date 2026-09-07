#!/usr/bin/env python3
"""T229: the stop gate tells FILED apart from blocked and from abandoned.

Contract
--------
Reads   : ``hooks/keel_stop.py``, sandboxed project trees this file builds and
          removes itself.
Emits   : unittest results only.
Writes  : nothing outside temporary directories.

What this file is for
----------------------
``.keel/decisions/2026-08-22-a-backlog-is-not-a-plan.md`` ratifies option (a):
newly-filed work lives in a session-independent backlog, and the stop gate
recognises filing as accounting distinct from ``[!]`` blocked and from
abandoned, WITHOUT a fifth ledger mark. The mechanism: a ledger item closes
``[x]`` with a ``FILED: BL<n>`` note, and the gate VERIFIES that note against
``.keel/backlog.md`` rather than trusting the sentence - so a genuine filing
passes the gate and a fabricated one (an id the backlog does not carry, or no
backlog at all) still blocks, exactly like an abandoned item would.

Failure policy
--------------
FAIL-CLOSED: an unverifiable FILED claim blocks the stop, same as an open
item.

Constraints
-----------
Python 3.10+, standard library only. Every file written names its encoding.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))

import keel_events  # noqa: E402
import keel_stop  # noqa: E402


def fresh_session() -> str:
    return uuid.uuid4().hex[:16]


def arm(project: Path, *, tier: int = 2) -> None:
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )


def write_ledger(project: Path, session: str, body: str) -> Path:
    plans = project / ".keel" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"keel-plan-{session[:8]}.md"
    path.write_text(body, encoding="utf-8")
    return path


def write_backlog(project: Path, body: str) -> Path:
    path = project / ".keel" / "backlog.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def stop_event(project: Path, session: str) -> keel_events.KeelEvent:
    return keel_events.KeelEvent(
        kind="stop",
        cwd=project,
        session_id=session,
        raw={"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False},
    )


class TestAGenuineFilingPassesTheGate(unittest.TestCase):
    """Direction 1: filed, verified, and the backlog carries the entry."""

    def test_a_closed_item_naming_a_real_backlog_entry_allows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_backlog(project, "- [ ] BL7 — a defect found while doing something else\n")
            write_ledger(
                project, session, "- [x] T900 — filed to the backlog. FILED: BL7\n"
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertFalse(verdict.blocking, verdict.reason)

    def test_the_backlog_entry_is_verifiably_still_on_the_record_afterward(self) -> None:
        """The entry is not consumed or altered by the gate reading it - a
        second session (a fresh read of the same file) finds it too."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            body = "- [ ] BL3 — carried across a simulated session boundary\n"
            write_backlog(project, body)
            first_read = keel_stop.read_backlog_ids(project)
            self.assertIn("BL3", first_read)
            # A second, unrelated session's own evaluation reads the same file.
            second_read = keel_stop.read_backlog_ids(project)
            self.assertEqual(first_read, second_read)
            self.assertIn("BL3", second_read)


class TestAFabricatedFilingStillBlocks(unittest.TestCase):
    """Direction 2: a [x]/FILED note the record does not back is unaccounted -
    the same shape as work abandoned mid-flight, and it still blocks."""

    def test_a_filed_note_naming_no_real_backlog_entry_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_backlog(project, "- [ ] BL1 — an unrelated real entry\n")
            write_ledger(
                project, session, "- [x] T901 — claims filing. FILED: BL99\n"
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["unverified_filed_items"], 1)
            self.assertEqual(verdict.detail["unverified_filed_item_ids"], ["T901"])
            self.assertIn("FILED", verdict.reason)

    def test_a_filed_note_with_no_backlog_file_at_all_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(
                project, session, "- [x] T902 — claims filing with nothing on record. "
                "FILED: BL1\n",
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["unverified_filed_items"], 1)

    def test_an_ordinary_blocked_item_is_unaffected(self) -> None:
        """[!] still means what it always meant; the new check only looks at
        [x] items carrying a FILED note."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [!] T903 — blocked, reason given\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertFalse(verdict.blocking)

    def test_a_filed_note_naming_a_closed_backlog_entry_blocks(self) -> None:
        """A ledger item may not close [x]/FILED against a backlog entry that
        is itself already checked off - the entry it would file against is
        not standing open to receive it (T229 finding: reviewer-silent-failure)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_backlog(project, "- [x] BL9 — already closed by an earlier session\n")
            write_ledger(
                project, session,
                "- [x] T905 — claims filing against a DONE entry. FILED: BL9\n",
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["unverified_filed_items"], 1)
            self.assertEqual(verdict.detail["unverified_filed_item_ids"], ["T905"])
            self.assertIn("FILED", verdict.reason)

    def test_one_unverified_id_among_several_filed_notes_on_one_line_blocks(self) -> None:
        """Every FILED id an item names must verify, not just the first
        (T229 below-floor note): a real entry followed by a fabricated one is
        still unaccounted."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_backlog(project, "- [ ] BL2 — a real entry the first note names\n")
            write_ledger(
                project, session,
                "- [x] T906 — claims two filings. FILED: BL2 FILED: BL77\n",
            )
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertTrue(verdict.blocking)
            self.assertEqual(verdict.detail["unverified_filed_items"], 1)
            self.assertEqual(verdict.detail["unverified_filed_item_ids"], ["T906"])

    def test_an_ordinary_closed_item_with_no_filed_note_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            session = fresh_session()
            arm(project)
            write_ledger(project, session, "- [x] T904 — done, no filing involved\n")
            verdict = keel_stop.evaluate(stop_event(project, session), {})
            self.assertFalse(verdict.blocking)
            self.assertEqual(verdict.detail, {})


class TestReadBacklogIdsIsUndecidableNeverEmpty(unittest.TestCase):
    """convention 7: an absent or unreadable backlog is None, not set()."""

    def test_a_missing_backlog_file_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(keel_stop.read_backlog_ids(Path(tmp)))

    def test_an_empty_backlog_file_is_an_empty_set_not_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_backlog(project, "# keel backlog\n\nNothing filed yet.\n")
            self.assertEqual(keel_stop.read_backlog_ids(project), set())

    def test_a_closed_backlog_entry_does_not_verify_a_new_filing(self) -> None:
        """A [x] backlog entry's id is not an OPEN id: it once existed but is
        not one a fresh FILED claim may point to (T229)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_backlog(project, "- [x] BL5 — closed by T910 on 2026-08-22\n")
            self.assertNotIn("BL5", keel_stop.read_backlog_ids(project))


if __name__ == "__main__":
    unittest.main()
