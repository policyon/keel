#!/usr/bin/env python3
"""T135 - a reconstructed verdict is a record that says it is reconstructed.

What is proven here, and where each claim is read from
-----------------------------------------------------
1. THE LINE. ``keel_backfill_reviews`` appends T129's review shape plus
   exactly two fields - ``backfilled: true`` and ``backfilled_at`` - with the
   LEDGER's date in ``ts`` and the full session id resolved from the log's own
   ``session_start`` lines. Asserted on the bytes read back off disk.
2. IDEMPOTENCE, both rules. A second run writes nothing (identical bytes), a
   row whose fact is already recorded LIVE is skipped rather than duplicated,
   and two rows that honestly carry the same verdict on the same task (T108
   failed twice) both land and neither is written twice.
3. FAIL-CLOSED. A session prefix that resolves to zero or to two
   ``session_start`` lines writes NOTHING AT ALL - not the rows that would
   have resolved, either.
4. THE CHOKEPOINT. A note carrying a home-shaped path reaches the log
   screened, because this writer goes through ``keel_events.append_audit``
   like every other keel writer.
5. THE SHIPPED TABLE. ``ROWS`` is checked for the properties its own contract
   claims - every verdict in the fixed vocabulary, every task id recordable,
   every ``ts`` a bare ISO date, every row citing a source file and line, and
   NO row naming session 53967e1a, whose verdicts were written live.

Every premise is the test's own
------------------------------
Each test builds a project in a temporary directory and writes its audit log
line by line, and every behavioural test passes its OWN synthetic table of
rows with its own invented session prefixes. No test here reads or writes this
repository's real audit log, and no test depends on the shipped ``ROWS`` table
holding any particular row - claim 5 is a property test over that table, not a
transcription of it, so adding a verdict to the table cannot make this file
fail for the wrong reason.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_backfill_reviews as backfill  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_redact  # noqa: E402
import keel_review  # noqa: E402

#: The two sessions this file's fixtures invent, and the 8-character prefixes
#: a row cites. Full-length and fixed, so an assertion can name them exactly.
SESSION_A = "aaaa1111-2222-3333-4444-555566667777"
SESSION_B = "bbbb8888-9999-0000-1111-222233334444"
PREFIX_A = SESSION_A[:8]
PREFIX_B = SESSION_B[:8]

#: The exact shape a backfilled line has: T129's seven, then the two markers.
#: Order matters as much as membership - ``v``/``ts`` are stamped first, so a
#: backfilled line reads like every other line until its final two fields.
SCHEMA: tuple[str, ...] = (
    "v", "ts", "event", "session", "task", "verdict", "notes",
    "backfilled", "backfilled_at",
)

#: A bare ISO date - the precision a ledger's prose actually carries.
DATE_RE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

#: A citation: some file name, a colon, and a line or line range.
CITATION_RE = re.compile(r"[\w.-]+\.md:\d+(-\d+)?\Z")

#: The session excluded by rule: its verdicts are already live events.
LIVE_SESSION_PREFIX = "53967e1a"


def rows_fixture() -> tuple[backfill.Row, ...]:
    """This file's own verdict table - two sessions, and a repeated verdict.

    The repeat is the point: two ``fail`` rows on the same task differing only
    in their notes, which is the shape T108 left in the real ledger and the
    reason the never-twice rule identifies a row by its notes as well.
    """
    return (
        backfill.Row(PREFIX_A, "T900", "pass", "2026-08-11", "ledger-a.md:10",
                     "the reviewer passed it"),
        backfill.Row(PREFIX_A, "T901", "fail", "2026-08-11", "ledger-a.md:20-21",
                     "first wrong-but-green shape"),
        backfill.Row(PREFIX_A, "T901", "fail", "2026-08-11", "ledger-a.md:20-21",
                     "second wrong-but-green shape"),
        backfill.Row(PREFIX_A, "T901", "pass", "2026-08-11", "ledger-a.md:20-21",
                     "closed after two retries"),
        backfill.Row(PREFIX_B, "T902", "pass", "2026-08-12", "ledger-b.md:30",
                     "security pass"),
    )


def project_with_log(root: Path, *lines: dict) -> Path:
    """An adopted project whose audit log holds exactly ``lines``.

    The log is written HERE rather than by keel, so the premise is the test's
    own: a ``session_start`` line exists because this function wrote one.
    """
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    audit = project / ".keel" / "audit" / "keel-audit.jsonl"
    audit.parent.mkdir(parents=True)
    with open(audit, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return project


def started(session: str, ts: str = "2026-08-11T09:00:00Z") -> dict:
    """One ``session_start`` line, in keel's own shape."""
    return {"v": 1, "ts": ts, "event": "session_start", "session": session}


def live_review(session: str, task: str, verdict: str, notes: str = "live") -> dict:
    """One review line as ``keel review`` writes it - no backfill markers."""
    return {
        "v": 1, "ts": "2026-08-11T10:00:00Z", "event": "review",
        "session": session, "task": task, "verdict": verdict, "notes": notes,
    }


def audit_lines(project: Path) -> list[dict]:
    """Every line of the project's audit log, parsed, oldest first."""
    path = keel_events.audit_path(project)
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def reviews(project: Path) -> list[dict]:
    """Just the review lines, in file order."""
    return [e for e in audit_lines(project) if e.get("event") == "review"]


class TestTheReconstructedLine(unittest.TestCase):
    """A backfilled verdict says what it is, and where it came from."""

    def test_every_row_lands_with_the_markers_and_the_ledgers_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            rows = rows_fixture()
            outcome = backfill.run(project, rows)
            self.assertEqual(len(outcome.written), len(rows))
            self.assertEqual(outcome.skipped, [])
            written = reviews(project)
            self.assertEqual(len(written), len(rows))
            for entry, row in zip(written, rows):
                self.assertEqual(tuple(entry), SCHEMA, entry)
                self.assertEqual(entry["v"], keel_events.AUDIT_SCHEMA_VERSION)
                self.assertEqual(entry["ts"], row.ts)
                self.assertRegex(entry["ts"], DATE_RE)
                self.assertEqual(entry["event"], "review")
                self.assertEqual(entry["task"], row.task)
                self.assertEqual(entry["verdict"], row.verdict)
                self.assertIs(entry["backfilled"], True)
                self.assertTrue(
                    entry["backfilled_at"].endswith("Z"), entry["backfilled_at"]
                )
                self.assertIn(row.source, entry["notes"])

    def test_the_session_is_the_full_id_resolved_from_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            backfill.run(project, rows_fixture())
            by_task = {e["task"]: e["session"] for e in reviews(project)}
            self.assertEqual(by_task["T900"], SESSION_A)
            self.assertEqual(by_task["T902"], SESSION_B)

    def test_a_generated_at_stamp_is_not_the_ledgers_date(self) -> None:
        """The two timestamps answer different questions and must not merge."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started(SESSION_A))
            row = rows_fixture()[0]
            backfill.run(project, (row,))
            entry = reviews(project)[0]
            self.assertNotEqual(entry["ts"], entry["backfilled_at"])
            self.assertTrue(entry["backfilled_at"].startswith(("20", "21")))

    def test_the_live_command_still_writes_no_markers(self) -> None:
        """The backfill did not bend ``keel review``'s own defaults.

        T197: identity is read, never inferred from the log, so ``keel
        review``'s own session is named explicitly here rather than left to
        default - its default is now ``CLAUDE_CODE_SESSION_ID``, not this
        fixture's ``session_start`` line, and this test is about the markers
        ``keel review`` writes, not about which session resolution rule it
        uses."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started(SESSION_A))
            self.assertEqual(
                keel_review.main(
                    ["--project", str(project), "--task", "T42",
                     "--verdict", "pass", "--notes", "criteria met",
                     "--session", PREFIX_A]
                ),
                0,
            )
            entry = reviews(project)[0]
            self.assertNotIn("backfilled", entry)
            self.assertNotIn("backfilled_at", entry)
            self.assertTrue(entry["ts"].endswith("Z"))


class TestIdempotence(unittest.TestCase):
    """A second run writes nothing, and a live verdict is never doubled."""

    def test_a_second_run_writes_nothing_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            rows = rows_fixture()
            backfill.run(project, rows)
            after_first = keel_events.audit_path(project).read_bytes()
            second = backfill.run(project, rows)
            self.assertEqual(second.written, [])
            self.assertEqual(len(second.skipped), len(rows))
            self.assertEqual(
                keel_events.audit_path(project).read_bytes(),
                after_first,
                "a second run left the log byte-identical",
            )
            for _row, why in second.skipped:
                self.assertEqual(why, "already backfilled")

    def test_a_third_run_after_unrelated_lines_still_writes_nothing(self) -> None:
        """Idempotence survives the log growing underneath it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            rows = rows_fixture()
            backfill.run(project, rows)
            keel_events.append_audit(project, {"event": "activity", "session": SESSION_A})
            before = keel_events.audit_path(project).read_bytes()
            self.assertEqual(backfill.run(project, rows).written, [])
            self.assertEqual(keel_events.audit_path(project).read_bytes(), before)

    def test_a_live_verdict_is_never_duplicated_by_a_reconstruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(SESSION_A),
                started(SESSION_B),
                live_review(SESSION_A, "T900", "pass", "recorded as it happened"),
            )
            rows = rows_fixture()
            outcome = backfill.run(project, rows)
            self.assertEqual(len(outcome.written), len(rows) - 1)
            self.assertEqual(
                [(row.task, why) for row, why in outcome.skipped],
                [("T900", "a live verdict already records it")],
            )
            t900 = [e for e in reviews(project) if e["task"] == "T900"]
            self.assertEqual(len(t900), 1)
            self.assertNotIn("backfilled", t900[0], "the live line stands alone")

    def test_two_honest_rows_with_the_same_verdict_both_land_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            rows = rows_fixture()
            backfill.run(project, rows)
            fails = [
                e for e in reviews(project)
                if e["task"] == "T901" and e["verdict"] == "fail"
            ]
            self.assertEqual(len(fails), 2, "both stated failures are on the record")
            self.assertNotEqual(fails[0]["notes"], fails[1]["notes"])
            backfill.run(project, rows)
            fails_again = [
                e for e in reviews(project)
                if e["task"] == "T901" and e["verdict"] == "fail"
            ]
            self.assertEqual(len(fails_again), 2, "and neither was written twice")

    def test_dry_run_reports_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(SESSION_B)
            )
            before = keel_events.audit_path(project).read_bytes()
            outcome = backfill.run(project, rows_fixture(), dry_run=True)
            self.assertEqual(len(outcome.written), len(rows_fixture()))
            self.assertEqual(keel_events.audit_path(project).read_bytes(), before)


class TestFailClosed(unittest.TestCase):
    """A prefix nobody can resolve writes nothing at all."""

    def test_an_unknown_session_prefix_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started(SESSION_A))
            before = keel_events.audit_path(project).read_bytes()
            with self.assertRaises(backfill.BackfillError) as caught:
                backfill.run(project, rows_fixture())
            self.assertIn(PREFIX_B, str(caught.exception))
            self.assertEqual(
                keel_events.audit_path(project).read_bytes(),
                before,
                "not even the rows that WOULD have resolved were written",
            )

    def test_an_ambiguous_prefix_is_refused_rather_than_picked(self) -> None:
        twin = PREFIX_A + "-0000-0000-0000-999999999999"
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp), started(SESSION_A), started(twin), started(SESSION_B)
            )
            before = keel_events.audit_path(project).read_bytes()
            with self.assertRaises(backfill.BackfillError):
                backfill.run(project, rows_fixture())
            self.assertEqual(keel_events.audit_path(project).read_bytes(), before)

    def test_an_unadopted_project_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(backfill.main(["--project", tmp]), 2)


class TestTheChokepoint(unittest.TestCase):
    """A note reaches the log screened, like every other keel line."""

    def test_a_home_shaped_path_in_a_note_is_screened(self) -> None:
        row = backfill.Row(
            PREFIX_A, "T903", "pass", "2026-08-11", "ledger-a.md:40",
            r"reviewer read C:\Users\someone\secret-notes.md and passed it",  # keel-leak: ignore - fixture home path inside an assertion
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started(SESSION_A))
            backfill.run(project, (row,))
            raw = keel_events.audit_path(project).read_text(encoding="utf-8")
            self.assertNotIn("someone", raw)
            self.assertIn(keel_redact.HOME_SHAPE_TOKEN, reviews(project)[0]["notes"])


class TestTheShippedTable(unittest.TestCase):
    """The curated table has the properties its own contract claims."""

    def test_every_row_is_recordable_and_cited(self) -> None:
        for row in backfill.ROWS:
            with self.subTest(task=row.task, source=row.source):
                self.assertIn(row.verdict, keel_review.VERDICTS)
                self.assertEqual(keel_review.normalise_task(row.task), row.task)
                self.assertRegex(row.ts, DATE_RE)
                self.assertRegex(row.source, CITATION_RE)
                self.assertIn(row.source, row.notes())
                self.assertTrue(row.note.strip(), "a citation without a fact is not a note")
                self.assertLessEqual(len(row.notes()), keel_review.NOTES_CHARS)

    def test_no_row_reconstructs_the_session_that_recorded_live(self) -> None:
        for row in backfill.ROWS:
            self.assertNotEqual(
                row.session,
                LIVE_SESSION_PREFIX,
                "53967e1a's verdicts are live events; reconstructing them would double them",
            )

    def test_each_row_is_distinct_in_full(self) -> None:
        """Identity is (session, task, verdict, notes) - so it must be unique."""
        keys = [(r.session, r.task, r.verdict, r.notes()) for r in backfill.ROWS]
        self.assertEqual(len(keys), len(set(keys)))

    def test_the_table_names_exactly_the_sessions_it_cites(self) -> None:
        """A row's session prefix and its cited ledger file agree."""
        for row in backfill.ROWS:
            with self.subTest(task=row.task):
                self.assertIn(row.session, row.source)


if __name__ == "__main__":
    unittest.main()
