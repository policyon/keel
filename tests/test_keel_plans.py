#!/usr/bin/env python3
"""keel-plan-contract test suite - ``scripts/keel_plans.py``.

Contract
--------
Reads   : nothing outside temporary directories it creates and removes, plus
          this repository's own ``.keel/plans/`` ledgers for the one test
          that pins the advisory default against the real tree.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

House style: ``check_ledger`` is driven directly against in-memory fixture
text, the precedent ``tests/test_keel_wave3.py`` sets for ``check_budget``
and ``tests/test_keel_agents.py`` sets for ``check_agents`` - every ``check_*``
function is pure and takes its input as a parameter. The repository-level and
CLI-shape assertions run ``python scripts/keel_plans.py`` in a subprocess, so
the exit code asserted there is the exit code a caller gets.

Failure policy
--------------
FAIL-CLOSED: a fixture that cannot be written fails the test rather than
being skipped.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "keel_plans.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_plans  # noqa: E402  (path must be set first)


#: A ledger with every task carrying an identifier, a Route line and an
#: Accept line, and no banned vocabulary anywhere - the contract-clean case.
CLEAN_LEDGER = """# Session plan - fixture - contract-clean ledger

## Tasks

- [x] T1 First task, done in one line.
      Route: standard (keel:executor).
      Accept: the fixture test suite is green.
- [ ] T2 Second task, whose Route and Accept trail a sentence rather than
      opening their own line, exactly like several real entries do: no
      other files touched. Route: standard (keel:executor). Accept: seven
      checks green; suite green.
"""

#: One task with no ``Accept:`` line anywhere in its block.
MISSING_ACCEPT_LEDGER = """# Session plan - fixture - missing accept

## Tasks

- [ ] T1 A task with a Route and no Accept line at all.
      Route: standard (keel:executor).
"""

#: One task with no ``Route:`` line anywhere in its block.
MISSING_ROUTE_LEDGER = """# Session plan - fixture - missing route

## Tasks

- [ ] T1 A task with an Accept and no Route line at all.
      Accept: the suite stays green.
"""

#: T203 fixture: an Accept field malformed exactly the way this project's
#: own session paid for once - the word separated from its colon by other
#: text. The strict pattern finds nothing (line 5, the opening checkbox,
#: would be the OLD, wrong citation); the near miss is on line 7.
NEAR_MISS_ACCEPT_LEDGER = """# Session plan - fixture - near-miss accept

## Tasks

- [ ] T1 A task with a malformed Accept field.
      Route: standard (keel:executor).
      Accept (restated for convenience; see clause 1):
      1. the suite stays green.
"""

#: T203 fixture: an Accept field present but wrong-cased. Clause 2: case is
#: a near miss, not an absence.
CASE_NEAR_MISS_ACCEPT_LEDGER = """# Session plan - fixture - case near-miss accept

## Tasks

- [ ] T1 A task with a lowercase accept field.
      Route: standard (keel:executor).
      accept: the suite stays green.
"""

#: T203 fixture: the Route-side mirror of ``NEAR_MISS_ACCEPT_LEDGER`` -
#: clause 3, every improvement Accept gets, Route gets too.
NEAR_MISS_ROUTE_LEDGER = """# Session plan - fixture - near-miss route

## Tasks

- [ ] T1 A task with a malformed Route field.
      Route (see the routing note below):
      standard (keel:executor).
      Accept: the suite stays green.
"""

#: T203 false-positive guard: "accept" used as a plain English word, with an
#: unrelated field's colon appearing only after a sentence break. This must
#: still read as a true ABSENCE of Accept, not a near miss naming the wrong
#: line.
PROSE_USES_THE_WORD_ACCEPT_LEDGER = """# Session plan - fixture - prose accept

## Tasks

- [ ] T1 A task that will not accept vague scope. Route: standard
      (keel:executor).
"""

#: One task whose body carries the banned placeholder vocabulary.
PLACEHOLDER_LEDGER = """# Session plan - fixture - placeholder vocabulary

## Tasks

- [ ] T1 A task whose scope is TBD and whose detail says to handle
      appropriately, once the shape is known - handle appropriately is
      the whole plan for now.
      Route: standard (keel:executor).
      Accept: the reviewer signs off.
"""

#: A task line carrying no ``Tn`` identifier at all after its checkbox.
MISSING_IDENTIFIER_LEDGER = """# Session plan - fixture - missing identifier

## Tasks

- [ ] Some task with no identifier at all.
      Route: standard (keel:executor).
      Accept: the suite stays green.
- [x] T2 A properly identified task.
      Route: standard (keel:executor).
      Accept: the suite stays green.
"""


def _findings_by_rule(findings, rule: str) -> list:
    return [f for f in findings if f.rule == rule]


class ParseTasksTests(unittest.TestCase):
    """``parse_tasks`` reads the ledger shape this project's plans use."""

    def test_identifier_and_title_captured(self) -> None:
        tasks = keel_plans.parse_tasks(CLEAN_LEDGER)
        self.assertEqual([t.identifier for t in tasks], ["T1", "T2"])

    def test_route_and_accept_found_mid_sentence(self) -> None:
        # T2's Route/Accept trail a sentence rather than opening their own
        # line - the shape several real ledger entries actually use.
        tasks = keel_plans.parse_tasks(CLEAN_LEDGER)
        t2 = tasks[1]
        self.assertTrue(t2.has_route)
        self.assertTrue(t2.has_accept)

    def test_missing_identifier_is_none(self) -> None:
        tasks = keel_plans.parse_tasks(MISSING_IDENTIFIER_LEDGER)
        self.assertIsNone(tasks[0].identifier)
        self.assertEqual(tasks[1].identifier, "T2")

    def test_true_absence_carries_no_near_miss(self) -> None:
        # A genuine absence (no attempt at the field anywhere) must not
        # manufacture a near miss out of nothing.
        route_task = keel_plans.parse_tasks(MISSING_ROUTE_LEDGER)[0]
        self.assertIsNone(route_task.route_near_miss)
        accept_task = keel_plans.parse_tasks(MISSING_ACCEPT_LEDGER)[0]
        self.assertIsNone(accept_task.accept_near_miss)

    def test_malformed_accept_field_is_captured_as_a_near_miss(self) -> None:
        task = keel_plans.parse_tasks(NEAR_MISS_ACCEPT_LEDGER)[0]
        self.assertFalse(task.has_accept)
        self.assertIsNotNone(task.accept_near_miss)
        near_line, near_text = task.accept_near_miss
        self.assertEqual(near_line, 7)
        self.assertIn("Accept (restated for convenience", near_text)


class CheckLedgerTests(unittest.TestCase):
    """``check_ledger`` - both directions, at the right severity."""

    def test_contract_clean_ledger_has_no_findings(self) -> None:
        findings = keel_plans.check_ledger("fixture.md", CLEAN_LEDGER, strict=True)
        self.assertEqual(findings, [], f"expected no findings, got {findings!r}")

    def test_missing_accept_is_a_warning(self) -> None:
        findings = keel_plans.check_ledger("fixture.md", MISSING_ACCEPT_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "missing_accept")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, keel_plans.WARN)
        # Never promoted to an error, even under --strict.
        self.assertFalse(any(f.severity == keel_plans.ERROR for f in findings))

    def test_missing_route_is_a_warning(self) -> None:
        findings = keel_plans.check_ledger("fixture.md", MISSING_ROUTE_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "missing_route")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, keel_plans.WARN)

    def test_true_absence_still_cites_the_tasks_opening_line(self) -> None:
        # Regression guard: unchanged behaviour for a genuine absence with
        # no near miss anywhere in the block.
        findings = keel_plans.check_ledger("fixture.md", MISSING_ACCEPT_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "missing_accept")
        self.assertEqual(matches[0].line, 5)
        self.assertEqual(matches[0].detail, "task T1 has no 'Accept:' line")

    def test_malformed_accept_field_is_reported_at_its_own_line(self) -> None:
        # T203 clause 1: a near-miss is reported AS a near miss, citing the
        # OFFENDING line (7) rather than the task's opening checkbox line
        # (5, the wrong line the old code cited), and showing the text
        # found beside the token required.
        findings = keel_plans.check_ledger("fixture.md", NEAR_MISS_ACCEPT_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "missing_accept")
        self.assertEqual(len(matches), 1)
        finding = matches[0]
        opening_line = keel_plans.parse_tasks(NEAR_MISS_ACCEPT_LEDGER)[0].line
        self.assertEqual(finding.line, 7)
        self.assertNotEqual(finding.line, opening_line)
        self.assertIn("Accept (restated for convenience", finding.detail)
        self.assertEqual(finding.severity, keel_plans.WARN)

    def test_case_mismatched_accept_is_a_near_miss_not_an_absence(self) -> None:
        # T203 clause 2: case is handled as a near miss rather than an
        # absence - the wording must differ from the true-absence message.
        findings = keel_plans.check_ledger(
            "fixture.md", CASE_NEAR_MISS_ACCEPT_LEDGER, strict=True
        )
        matches = _findings_by_rule(findings, "missing_accept")
        self.assertEqual(len(matches), 1)
        finding = matches[0]
        self.assertEqual(finding.line, 7)
        self.assertNotEqual(finding.detail, "task T1 has no 'Accept:' line")
        self.assertIn("accept: the suite stays green.", finding.detail)

    def test_malformed_route_field_gets_the_same_treatment_as_accept(self) -> None:
        # T203 clause 3: Route gets every improvement Accept gets, in the
        # same change.
        findings = keel_plans.check_ledger("fixture.md", NEAR_MISS_ROUTE_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "missing_route")
        self.assertEqual(len(matches), 1)
        finding = matches[0]
        self.assertEqual(finding.line, 6)
        self.assertIn("Route (see the routing note below):", finding.detail)

    def test_prose_use_of_the_word_accept_is_not_mistaken_for_a_near_miss(self) -> None:
        # False-positive guard: a sentence break between the word and an
        # unrelated field's colon must not manufacture a near miss.
        findings = keel_plans.check_ledger(
            "fixture.md", PROSE_USES_THE_WORD_ACCEPT_LEDGER, strict=True
        )
        matches = _findings_by_rule(findings, "missing_accept")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].line, 5)
        self.assertEqual(matches[0].detail, "task T1 has no 'Accept:' line")

    def test_placeholder_phrase_named_and_warned(self) -> None:
        findings = keel_plans.check_ledger("fixture.md", PLACEHOLDER_LEDGER, strict=True)
        matches = _findings_by_rule(findings, "placeholder_phrase")
        phrases = {f.detail for f in matches}
        self.assertTrue(any("TBD" in d for d in phrases))
        self.assertTrue(any("handle appropriately" in d for d in phrases))
        self.assertTrue(all(f.severity == keel_plans.WARN for f in matches))

    def test_missing_identifier_is_warning_by_default(self) -> None:
        findings = keel_plans.check_ledger(
            "fixture.md", MISSING_IDENTIFIER_LEDGER, strict=False
        )
        matches = _findings_by_rule(findings, "missing_identifier")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, keel_plans.WARN)

    def test_missing_identifier_is_error_under_strict(self) -> None:
        findings = keel_plans.check_ledger(
            "fixture.md", MISSING_IDENTIFIER_LEDGER, strict=True
        )
        matches = _findings_by_rule(findings, "missing_identifier")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].severity, keel_plans.ERROR)


class MainExitCodeTests(unittest.TestCase):
    """``main`` - the CLI's exit codes, both directions."""

    def _write(self, tmp: Path, name: str, text: str) -> Path:
        path = tmp / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_clean_ledger_exits_zero_under_strict(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ledger = self._write(tmp, "clean.md", CLEAN_LEDGER)
            self.assertEqual(keel_plans.main([str(ledger), "--strict", "--quiet"]), 0)

    def test_missing_identifier_exits_one_under_strict_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ledger = self._write(tmp, "bad.md", MISSING_IDENTIFIER_LEDGER)
            self.assertEqual(keel_plans.main([str(ledger), "--quiet"]), 0)
            self.assertEqual(keel_plans.main([str(ledger), "--strict", "--quiet"]), 1)

    def test_advisory_default_never_fails_on_warnings_alone(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ledger = self._write(tmp, "placeholder.md", PLACEHOLDER_LEDGER)
            self.assertEqual(keel_plans.main([str(ledger), "--quiet"]), 0)
            # Placeholder vocabulary is never promoted to an error, even
            # under --strict - only missing_identifier is strict-sensitive.
            self.assertEqual(keel_plans.main([str(ledger), "--strict", "--quiet"]), 0)

    def test_nonexistent_explicit_ledger_exits_two(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = str(Path(raw) / "nowhere.md")
            self.assertEqual(keel_plans.main([missing, "--quiet"]), 2)

    def test_absent_default_plans_directory_is_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(keel_plans.main(["--project", raw, "--quiet"]), 0)


class RepoLedgersAdvisoryTests(unittest.TestCase):
    """This repository's CURRENT session ledgers pass the default run."""

    def test_default_run_over_project_plans_is_clean_exit(self) -> None:
        self.assertEqual(keel_plans.main(["--project", str(REPO_ROOT), "--quiet"]), 0)

    def test_cli_subprocess_default_run_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CHECKER)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            result.returncode, 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


if __name__ == "__main__":
    unittest.main()
