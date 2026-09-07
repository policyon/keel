#!/usr/bin/env python3
"""Pins the T441 rule in both skills' prose: a mooring record can close a
dead session ledger it names, and castoff honours that closure.

Contract
--------
Reads   : ``skills/castoff/SKILL.md``, ``skills/moor/SKILL.md`` and
          ``skills/moor/references/keel-mooring-record.md`` as text. No
          castoff or moor step has runtime code of its own — both skills are
          prose an agent follows — so this suite pins the wording itself,
          in both directions named by
          ``.keel/decisions/2026-09-02-a-mooring-closes-the-dead-ledgers-it-names.md``:
          a ledger named under ``## Closed ledgers`` together with an
          accounting record is reported closed, and a ledger either unnamed
          or named without an accounting record is still reported
          unterminated.
Emits   : unittest results only.
Writes  : nothing.

Failure policy
--------------
FAIL-CLOSED: a missing file fails the read rather than being skipped.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CASTOFF_SKILL = REPO_ROOT / "skills" / "castoff" / "SKILL.md"
MOOR_SKILL = REPO_ROOT / "skills" / "moor" / "SKILL.md"
MOOR_SKELETON = REPO_ROOT / "skills" / "moor" / "references" / "keel-mooring-record.md"


def read(path: Path) -> str:
    """The file's text with every run of whitespace collapsed to one space.

    The assertions below pin MEANING, so a reflow of the skill prose that
    keeps the words and moves the line breaks must not fail them (a
    `keel:reviewer-tests` finding on 2026-09-02: exact line-wrap substrings
    are brittle for no behavioural reason). Headings still match because a
    heading is one line by construction.
    """
    return " ".join(path.read_text(encoding="utf-8").split())


class TestCastoffHonoursAClosedLedger(unittest.TestCase):
    """The "closed" direction: a ledger named under ``## Closed ledgers``
    with an accounting record is reported as closed by that mooring, not as
    unterminated."""

    def test_castoff_step_4_states_a_named_ledger_with_an_accounting_record_is_closed(
        self,
    ) -> None:
        text = read(CASTOFF_SKILL)
        self.assertIn("## Closed ledgers", text)
        self.assertIn("ANY mooring record", text)
        self.assertIn(
            "together with the record or backlog entry that accounts for "
            "every one of its unfinished items",
            text,
        )
        self.assertIn("is reported in", text)
        self.assertIn("one line as closed by that mooring, not as unterminated.", text)


class TestCastoffStillReportsAnUnaccountedOrUnnamedLedger(unittest.TestCase):
    """The other direction: naming without an accounting record does not
    count, and an unnamed ledger is unaffected — both keep being reported
    unterminated."""

    def test_castoff_step_4_states_a_name_without_an_accounting_record_does_not_count(
        self,
    ) -> None:
        text = read(CASTOFF_SKILL)
        self.assertIn(
            "A `## Closed ledgers` line that names a ledger but points at "
            "no accounting record does not count",
            text,
        )
        self.assertIn(
            "report that ledger unterminated, exactly as if no mooring had "
            "named it at all.",
            text,
        )

    def test_castoff_step_4_still_carries_its_original_unterminated_report_rule(
        self,
    ) -> None:
        """The new rule is additive: the base rule — list every ledger not
        this session's own and report the ones not all terminal — is still
        there, unweakened."""
        text = read(CASTOFF_SKILL)
        self.assertIn(
            "report any whose items are not all terminal", text
        )
        self.assertIn("Report the absence too", text)

    def test_the_four_steps_heading_is_unchanged(self) -> None:
        """The rule was added INSIDE step 4, not as a fifth step, so the
        heading that counts steps stays what it was."""
        text = read(CASTOFF_SKILL)
        self.assertIn("## The four steps", text)


class TestMoorListsAndNamesDeadLedgersBeforeWriting(unittest.TestCase):
    """The other half of the ruling: moor gains the listing-and-naming step,
    before the record is written, using file-reading tools rather than a
    command."""

    def test_moor_gains_a_step_before_the_record_is_written(self) -> None:
        text = read(MOOR_SKILL)
        self.assertIn("## The six steps", text)
        self.assertIn("List and close dead ledgers", text)
        self.assertIn("not named for THIS session", text)
        self.assertIn("## Closed ledgers", text)

    def test_moor_step_states_naming_without_an_accounting_record_is_not_closure(
        self,
    ) -> None:
        text = read(MOOR_SKILL)
        self.assertIn("Naming a ledger without an accounting record is not closure", text)

    def test_moor_step_reads_files_directly_not_a_command(self) -> None:
        text = read(MOOR_SKILL)
        self.assertIn("Read these files directly rather than", text)
        self.assertIn("scripts/keel_plans.py", text)

    def test_moor_step_precedes_the_write_the_record_step(self) -> None:
        text = read(MOOR_SKILL)
        list_idx = text.index("List and close dead ledgers")
        write_idx = text.index("Write ONE mooring record")
        self.assertLess(list_idx, write_idx)


class TestMooringSkeletonCarriesTheHeading(unittest.TestCase):
    """The skeleton under ``skills/moor/references/`` gains the heading with
    one line of guidance and an example entry in the ruled form."""

    def test_skeleton_has_the_closed_ledgers_heading_with_guidance(self) -> None:
        text = read(MOOR_SKELETON)
        self.assertIn("## Closed ledgers", text)

    def test_skeleton_example_matches_the_ruled_form(self) -> None:
        text = read(MOOR_SKELETON)
        self.assertIn("keel-plan-<id8>.md", text)
        self.assertIn("unfinished item(s), accounted for in <path or BLn>", text)


if __name__ == "__main__":
    unittest.main()
