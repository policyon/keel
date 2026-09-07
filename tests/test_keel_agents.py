#!/usr/bin/env python3
"""Agent contract test suite - ``keel_checks --agents``, the R22/R28 gate.

Contract
--------
Reads   : tests/fixtures/agents/*.json - the declarative agent fixtures, in
          both directions ("pass" and "flag") - plus this repository's own
          agents/ directory, which is checked exactly as it ships.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

House style: the repository-level assertion runs
``python scripts/keel_checks.py --agents`` in a subprocess, so the exit code
asserted here is the exit code CI gets. The fixtures drive ``check_agents``
directly against a temporary root, the same precedent
``tests/test_keel_wave3.py`` sets for ``check_budget``: every ``check_*``
function takes its root as a parameter.

Failure policy
--------------
FAIL-CLOSED: a missing fixture directory or an empty fixture set fails the
suite rather than skipping it. (An absent ``agents/`` directory in a checked
project is a PASS of the check itself - keel never fails an adopter on day
one - and that behaviour is pinned below as a test.)

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKS = REPO_ROOT / "scripts" / "keel_checks.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "agents"
AGENTS_DIR = REPO_ROOT / "agents"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402  (path must be set first)


def load_agent_fixtures() -> list[tuple[str, dict[str, Any]]]:
    """Every agent fixture, in filename order, as (stem, document)."""
    if not FIXTURE_ROOT.is_dir():
        raise RuntimeError(f"missing fixture directory {FIXTURE_ROOT}")
    found = [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(FIXTURE_ROOT.glob("*.json"))
    ]
    if not found:
        raise RuntimeError(f"no fixtures in {FIXTURE_ROOT}")
    return found


class TestAgentFixtures(unittest.TestCase):
    """Declarative agent fixtures, both directions, run through check_agents."""

    def run_fixture(self, fixture: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "agents"
            agents.mkdir()
            for relative, text in fixture["agents"].items():
                with open(agents / relative, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            violations = keel_checks.check_agents(root)
            detail = f"violations={violations}"
            self.assertEqual(
                1 if violations else 0, fixture["expect_exit"], detail
            )
            joined = "\n".join(violations)
            for clause in fixture["expect_rules"]:
                self.assertIn(clause, joined, detail)
            for clause in fixture["expect_absent_rules"]:
                self.assertNotIn(clause, joined, detail)
            for violation in violations:
                self.assertTrue(
                    violation.startswith("agents/"),
                    f"a violation must name its file: {violation}",
                )


def _attach_agent_fixtures() -> None:
    """Turn every fixture file into its own named test method."""
    for stem, fixture in load_agent_fixtures():
        name = "test_" + re.sub(r"[^0-9a-zA-Z]+", "_", stem)

        def method(self: TestAgentFixtures, fixture: dict[str, Any] = fixture) -> None:
            self.run_fixture(fixture)

        method.__doc__ = f"agent fixture {stem}: {fixture.get('description', '')}"
        setattr(TestAgentFixtures, name, method)


_attach_agent_fixtures()


class TestAgentFixtureShape(unittest.TestCase):
    """Convention 2 applied to the checker: both directions or it does not ship."""

    def test_both_directions_ship(self) -> None:
        directions = [fixture["direction"] for _, fixture in load_agent_fixtures()]
        self.assertGreater(directions.count("pass"), 0, "no passing agents")
        self.assertGreater(directions.count("flag"), 0, "no flagged agents")

    def test_every_fixture_is_well_formed(self) -> None:
        required = (
            "name",
            "direction",
            "description",
            "agents",
            "expect_exit",
            "expect_rules",
            "expect_absent_rules",
        )
        seen: set[str] = set()
        for stem, fixture in load_agent_fixtures():
            with self.subTest(fixture=stem):
                for key in required:
                    self.assertIn(key, fixture)
                self.assertIn(fixture["direction"], ("pass", "flag"))
                self.assertEqual(fixture["expect_exit"], 0 if fixture["direction"] == "pass" else 1)
                self.assertTrue(stem.endswith(fixture["name"]))
                self.assertNotIn(fixture["name"], seen, "duplicate fixture name")
                seen.add(fixture["name"])

    def test_every_contract_clause_is_exercised_by_a_fixture(self) -> None:
        """A clause nothing exercises is a clause nobody knows still works."""
        exercised: set[str] = set()
        for _, fixture in load_agent_fixtures():
            exercised.update(fixture["expect_rules"])
        for clause in (
            "missing_tools",
            "reviewer_tools",
            "heading_missing",
            "headings_out_of_order",
            "floor_line",
            "model_missing",
            "model_mismatch",
        ):
            with self.subTest(clause=clause):
                self.assertIn(clause, exercised)


class TestCheckAgentsEdges(unittest.TestCase):
    """The clauses the declarative fixtures do not need a whole file for."""

    def test_a_missing_agents_directory_is_a_pass(self) -> None:
        """keel's checks never fail an adopter on day one: no agents/, exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keel_checks.check_agents(Path(tmp)), [])

    def test_an_empty_tools_value_is_flagged(self) -> None:
        """R22 wants an explicit list, and 'tools:' with nothing after it is not one."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            agents.mkdir()
            with open(agents / "hollow.md", "w", encoding="utf-8", newline="\n") as handle:
                handle.write("---\nname: hollow\ndescription: Declares tools, lists none.\ntools:\n---\n\nBody.\n")
            joined = "\n".join(keel_checks.check_agents(Path(tmp)))
            self.assertIn("empty_tools", joined)

    def test_a_name_that_is_not_the_stem_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            agents.mkdir()
            with open(agents / "alias.md", "w", encoding="utf-8", newline="\n") as handle:
                handle.write("---\nname: somebody-else\ndescription: Routed by a name no file carries.\ntools: Read\n---\n\nBody.\n")
            joined = "\n".join(keel_checks.check_agents(Path(tmp)))
            self.assertIn("name_mismatch", joined)


class TestRepositoryAgents(unittest.TestCase):
    """keel checks itself: the shipped agents honour the contract they define."""

    def test_the_shipped_agents_pass_via_the_cli(self) -> None:
        """The exit code CI gets, not the return value a caller hopes for."""
        env = {key: value for key, value in os.environ.items()}
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "-B", str(CHECKS), "--agents"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=env,
            timeout=120,
            check=False,
        )
        detail = f"exit={result.returncode} stdout={result.stdout} stderr={result.stderr}"
        self.assertEqual(result.returncode, 0, detail)
        self.assertIn("PASS agents", result.stdout, detail)

    def test_the_reviewers_are_found_and_counted_from_the_filesystem(self) -> None:
        """R26: the count comes from glob, never from prose."""
        reviewers = sorted(path.stem for path in AGENTS_DIR.glob("reviewer-*.md"))
        self.assertGreaterEqual(len(reviewers), 4, reviewers)
        self.assertEqual(keel_checks.check_agents(REPO_ROOT), [])
        for stem in reviewers:
            with self.subTest(reviewer=stem):
                fields, _, error = keel_checks._agent_frontmatter(
                    (AGENTS_DIR / f"{stem}.md").read_text(encoding="utf-8")
                )
                self.assertIsNone(error)
                self.assertEqual(fields.get("name"), stem)


if __name__ == "__main__":
    unittest.main()
