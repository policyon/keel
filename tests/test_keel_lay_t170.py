#!/usr/bin/env python3
"""Greenfield lay and the tracked-record default (T170), pinned as skill TEXT.

Two owner-ratified decisions change what ``/keel:lay`` says:
``.keel/decisions/2026-08-18-greenfield-lay-ratified.md`` (an empty or
near-empty tree defaults to tier 1 and says so, importing the planning
documents it finds as knowledge records with foreign citations pinned to a
SHA at import) and
``.keel/decisions/2026-08-18-tracked-record-becomes-the-default.md`` (the
record is tracked by default; the opt-out lives in the shipped policy
template's ``## Local amendments``, ``templates/keel-policy.md:235``).
Both are mechanisms made of prose, so the prose is what is pinned here,
following the shape of ``TestLayWarnsBeforeArmingBlind`` in
``tests/test_keel_conflict_engine.py``.

Contract
--------
Reads   : ``skills/lay/SKILL.md`` as text only. No subprocess, no scratch
          project, no ``.keel/`` of its own.
Emits   : unittest results only.
Writes  : nothing.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its
encoding.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = REPO_ROOT / "skills" / "lay" / "SKILL.md"


def _skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def _body() -> str:
    """The text after the YAML frontmatter, same split the precedent uses."""
    parts = _skill().split("---", 2)
    return parts[2] if len(parts) > 2 else _skill()


def _flat() -> str:
    """``_body()`` with runs of whitespace collapsed to one space.

    A phrase that wraps across a hard line-break in the shipped markdown is
    still one phrase to a reader; a pin that breaks the moment prose
    reflows would be testing the wrap, not the content.
    """
    return re.sub(r"\s+", " ", _body())


class TestGreenfieldLayDefaultsToTierOneAndImportsThePlan(unittest.TestCase):
    """Ratified decision: greenfield-lay-ratified.md.

    An empty or near-empty tree is not "nothing to capture yet" — lay
    defaults to tier 1 out loud and imports the planning documents it finds
    as knowledge records, pinning any foreign-repository citation to a SHA
    at import.
    """

    def test_the_tier_step_names_the_greenfield_case(self) -> None:
        """T226 renumbered lay's steps (backup and legacy-import survey were
        inserted before it), so the tier step is now step 5, not step 3."""
        body = _body()
        step_five = body.split("5. **Choose a tier.**", 1)
        self.assertEqual(len(step_five), 2, "the tier step must still be there to check")
        self.assertIn("empty or near-empty tree", step_five[1])

    def test_greenfield_defaults_to_tier_one_without_asking_and_says_so(self) -> None:
        self.assertIn("without asking and say so", _body())

    def test_greenfield_imports_the_plan_as_knowledge_records(self) -> None:
        body = _body()
        self.assertIn("imports the planning documents it finds", body)
        self.assertIn("knowledge records", body)

    def test_greenfield_names_the_record_kinds_the_decision_names(self) -> None:
        """All FOUR kinds the decision names — decisions, kill-gates,
        subordination constraints AND measured claims — not a three-item
        stand-in for them (greenfield-lay-ratified.md line 24: "decisions,
        kill-gates, subordination constraints and measured claims are
        imported as knowledge records"). Matched whitespace-flat since the
        shipped list wraps across a line."""
        self.assertIn(
            "decisions, kill-gates, subordination constraints and measured claims",
            _flat(),
        )

    def test_greenfield_pins_foreign_citations_to_a_sha_at_import(self) -> None:
        """Path-only anchors into a foreign repository break the moment the
        source tree moves — the decision's own reasoning for the pin.
        Matched whitespace-flat, same reason as the record-kinds test."""
        self.assertIn(
            "pins any citation into a foreign repository to a SHA at import",
            _flat(),
        )


class TestTheRecordIsTrackedByDefault(unittest.TestCase):
    """Ratified decision: tracked-record-becomes-the-default.md.

    ``.keel/plans/`` and ``.keel/audit/`` are versioned by the shipped
    template; ``.keel/cache/`` is the one ignored path. This corrects step
    5's old sentence rather than adding beside it — the old sentence said
    the choice was the user's, not this skill's, which contradicted the
    ratified default.
    """

    def test_the_confirm_step_states_tracked_by_default(self) -> None:
        """T226 renumbered lay's steps; Confirm is now step 7, not step 5."""
        body = _body()
        step_seven = body.split("7. **Confirm.**", 1)
        self.assertEqual(len(step_seven), 2, "the confirm step must still be there to check")
        self.assertIn("TRACKED BY DEFAULT", step_seven[1])

    def test_the_cache_path_is_named_as_the_one_ignored_path(self) -> None:
        self.assertIn("`.keel/cache/` the one ignored path", _body())

    def test_the_opt_out_names_the_shipped_amendment_location(self) -> None:
        """T170 accept 2: lay states where the opt-out lives — the shipped
        amendment, already landed, at ``templates/keel-policy.md:235``."""
        self.assertIn("templates/keel-policy.md:235", _body())

    def test_the_opt_out_says_how_to_opt_out(self) -> None:
        body = _body()
        self.assertIn("to opt out, edit that", body)
        self.assertIn("so the choice is itself recorded", body)

    def test_the_old_contradiction_is_gone(self) -> None:
        """Step 5 used to say the record was the user's choice to track or
        not — that sentence is a correction target, not a survivor."""
        self.assertNotIn("the project's record to track or not", _body())
        self.assertNotIn("that choice is the user's, not this skill's", _body())


if __name__ == "__main__":
    unittest.main()
