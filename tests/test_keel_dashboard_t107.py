#!/usr/bin/env python3
"""T107 - the session selector names a ledger by its subject, not its id.

Contract
--------
Reads   : temporary directories this file creates - no fixture here touches
          this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
The dashboard's session selector (``#plansel``) used to list nothing but
plan-file identifiers - ``26835f59``, ``074ab77d`` - even though every
ledger under ``.keel/plans/`` already opens with a markdown heading naming
its own subject. This task makes the selector show that subject, with the
identifier kept alongside for a reader who needs it, and derives the
subject from the SAME text ``read_plan`` already reads for the ledger
panel - ``list_plans`` is extended to call it, never a second file-reading
path.

Covered here: ``plan_subject``'s derivation rule (boilerplate prefix,
identifier, and surrounding punctuation trimmed; long subjects cut, not
wrapped) directly; its fallback to the bare identifier for a heading that
is missing, unreadable, reduces to nothing once trimmed, or reduces to
NOTHING BUT a bare date (review fix: a residue that merely CONTAINS a date
among real words must survive untouched); ``list_plans`` carrying
``subject`` alongside ``name`` and ``session`` for every listed ledger, end
to end against the real filesystem; and that the selector's page source
reads both fields rather than inventing a new one.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
import unittest
import unittest.mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import _project, _page, _script  # noqa: E402


# --------------------------------------------------- plan_subject: derivation


class TestPlanSubjectDerivation(unittest.TestCase):
    """A subject is what is left of the heading once the boilerplate every
    ledger shares - the leading ``#``, ``"Session plan —"``, and the
    ledger's own identifier - is trimmed away, and nothing invented."""

    def test_a_dashed_subject_after_the_identifier_is_read_off_plainly(self) -> None:
        text = "# Session plan — 074ab77d — fix the gate deadlock that blocks orientation\n"
        self.assertEqual(
            keel_dashboard.plan_subject(text, "074ab77d"),
            "fix the gate deadlock that blocks orientation",
        )

    def test_the_keel_plan_prefixed_identifier_form_is_recognised_too(self) -> None:
        """The identifier is stripped in its ``keel-plan-`` form too - and
        what is left here, a bare date, is itself uninformative (see the
        date-fallback tests below), so this only pins that the IDENTIFIER
        half of the strip fires; a subject with real words survives, as the
        long-subject and no-generic-prefix tests already show."""
        text = "# Session plan — keel-plan-6f7fdee8 (2026-08-03)\n"
        self.assertEqual(keel_dashboard.plan_subject(text, "6f7fdee8"), "6f7fdee8")

    def test_a_subject_that_contains_a_date_among_real_words_survives_untouched(self) -> None:
        """The date fallback matches a residue that IS a date, wholly - not
        one that merely contains one. ``PLAN_SUBJECT_DATE_RE`` is anchored
        full-string for exactly this reason. Kept well under
        ``PLAN_SUBJECT_MAX`` so truncation cannot be confused for this."""
        text = "# Session plan — 25fb144d — 0.4.0 release, 2026-08-01 audit\n"
        self.assertEqual(
            keel_dashboard.plan_subject(text, "25fb144d"),
            "0.4.0 release, 2026-08-01 audit",
        )

    def test_a_heading_with_no_generic_prefix_is_used_whole(self) -> None:
        """A custom heading - not this project's own boilerplate - is not
        forced through a shape it does not have; it is trimmed of its ``#``
        and surrounding space only."""
        self.assertEqual(keel_dashboard.plan_subject("# ledger\n\nbody\n", "abcdef12"), "ledger")

    def test_a_long_subject_is_cut_not_wrapped(self) -> None:
        long_tail = "reach parity with the predecessor viewer, starting with the finish it cannot currently see"
        text = f"# Session plan — 4850df38 — {long_tail}\n"
        subject = keel_dashboard.plan_subject(text, "4850df38")
        self.assertLessEqual(len(subject), keel_dashboard.PLAN_SUBJECT_MAX)
        self.assertTrue(subject.endswith("…"))
        self.assertTrue(long_tail.startswith(subject[:-1].rstrip()))
        self.assertNotIn("\n", subject)


# -------------------------------------------------- plan_subject: fallback


class TestPlanSubjectFallsBackToTheIdentifier(unittest.TestCase):
    """"No readable heading" covers three different shapes, and none of
    them may say anything false about the identifier they fall back to."""

    def test_no_text_at_all_falls_back(self) -> None:
        self.assertEqual(keel_dashboard.plan_subject(None, "abcdef12"), "abcdef12")
        self.assertEqual(keel_dashboard.plan_subject("", "abcdef12"), "abcdef12")

    def test_a_first_line_that_is_not_a_heading_falls_back(self) -> None:
        self.assertEqual(
            keel_dashboard.plan_subject("Track: dashboard parity\n\n# a later heading\n", "abcdef12"),
            "abcdef12",
        )

    def test_a_bare_hash_with_nothing_after_it_falls_back(self) -> None:
        self.assertEqual(keel_dashboard.plan_subject("#\n", "abcdef12"), "abcdef12")

    def test_a_heading_with_only_the_identifier_falls_back(self) -> None:
        text = "# Session plan — 26835f59\n"
        self.assertEqual(keel_dashboard.plan_subject(text, "26835f59"), "26835f59")

    def test_a_heading_with_only_the_identifier_and_a_date_falls_back(self) -> None:
        """Review fix: ``26835f59, 2026-08-11`` reduces to nothing but a bare
        date once the identifier is trimmed - as uninformative as no subject
        at all, so this falls back the same way rather than showing a date
        the ledger's own mtime already carries."""
        text = "# Session plan — 26835f59, 2026-08-11\n"
        self.assertEqual(keel_dashboard.plan_subject(text, "26835f59"), "26835f59")

    def test_a_keel_plan_prefixed_identifier_with_only_a_date_falls_back(self) -> None:
        text = "# Session plan — keel-plan-6f7fdee8 (2026-08-03)\n"
        self.assertEqual(keel_dashboard.plan_subject(text, "6f7fdee8"), "6f7fdee8")


# --------------------------------------------- plan_subject: whitespace/prefix


class TestPlanSubjectWhitespaceAndPrefixHandling(unittest.TestCase):
    def test_surrounding_whitespace_on_the_heading_line_is_ignored(self) -> None:
        text = "   #   Session plan — 074ab77d — fix the leak   \n"
        self.assertEqual(keel_dashboard.plan_subject(text, "074ab77d"), "fix the leak")

    def test_only_the_first_line_is_ever_read_as_the_heading(self) -> None:
        """A heading later in the file is not this ledger's heading (T107's
        own convention: the FIRST line, and no other)."""
        text = "not a heading line\n# Session plan — abcdef12 — a real subject\n"
        self.assertEqual(keel_dashboard.plan_subject(text, "abcdef12"), "abcdef12")


# --------------------------------------------------------- list_plans payload


class TestListPlansCarriesBothSubjectAndIdentifier(unittest.TestCase):
    def test_each_listed_ledger_carries_its_own_subject_alongside_its_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(
                Path(tmp), [], "# Session plan — abcdef12 — a real subject\n\nbody\n"
            )
            found, listing_failed = keel_dashboard.list_plans(project)
        self.assertFalse(listing_failed)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["session"], "abcdef12")
        self.assertEqual(found[0]["subject"], "a real subject")
        self.assertEqual(found[0]["name"], "keel-plan-abcdef12.md")

    def test_a_ledger_read_plan_cannot_open_falls_back_without_dropping_out(self) -> None:
        """The same degrade-without-dropping shape T36 already gives a
        per-entry ``stat`` failure: a ledger that could not be READ still
        keeps its name and its ``mtime``, and its subject is the identifier
        - never an empty string, and never a listing loss it is not."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with unittest.mock.patch.object(
                keel_dashboard, "read_plan", return_value=None
            ):
                found, listing_failed = keel_dashboard.list_plans(project)
        self.assertFalse(listing_failed)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "keel-plan-abcdef12.md")
        self.assertEqual(found[0]["subject"], "abcdef12")

    def test_read_state_carries_the_subject_through_to_the_plans_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(
                Path(tmp), [], "# Session plan — abcdef12 — reach the far dock\n"
            )
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["plans"][0]["subject"], "reach the far dock")
        self.assertEqual(state["plans"][0]["session"], "abcdef12")


# ------------------------------------------------------- the selector's markup


class TestTheSelectorPageSourceReadsBothFields(unittest.TestCase):
    """A value test cannot see what the option markup ESCAPES its label and
    its identifier into, so this pins the source itself: the visible text
    is the subject, and the identifier still travels with the option
    rather than being dropped once a subject exists."""

    def test_the_option_builder_reads_subject_for_text_and_session_for_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [])))
        self.assertIn("p.subject", script)
        self.assertIn("p.session", script)
        self.assertIn('title="${esc(p.session)}"', script)
        self.assertIn(">${esc(p.subject)}<", script)


if __name__ == "__main__":
    unittest.main()
