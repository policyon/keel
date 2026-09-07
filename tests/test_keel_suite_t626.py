"""T626/BL59: the suite-gating instrument requires the summary, not only exit 0.

Drives :func:`scripts.keel_suite.suite_verdict` — the real verdict seam the
wrapper's ``main`` calls — against fixtures in both directions, plus one
cheap end-to-end run of the wrapper itself against a tiny targeted module
(never full discovery, so this file stays fast).
"""

from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import keel_suite  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures: unittest's own summary shapes, verbatim as the runner prints them.
# ---------------------------------------------------------------------------

COMPLETE_OK = textwrap.dedent(
    """\
    test_a (tests.test_a.Case) ... ok
    test_b (tests.test_b.Case) ... ok

    ----------------------------------------------------------------------
    Ran 2 tests in 0.003s

    OK
    """
)

COMPLETE_OK_SKIPPED = textwrap.dedent(
    """\
    test_a (tests.test_a.Case) ... ok
    test_b (tests.test_b.Case) ... skipped 'not applicable'

    ----------------------------------------------------------------------
    Ran 2 tests in 0.003s

    OK (skipped=1)
    """
)

COMPLETE_FAILED = textwrap.dedent(
    """\
    test_a (tests.test_a.Case) ... ok
    test_b (tests.test_b.Case) ... FAIL

    ======================================================================
    FAIL: test_b (tests.test_b.Case)
    ----------------------------------------------------------------------
    AssertionError: boom

    ----------------------------------------------------------------------
    Ran 2 tests in 0.003s

    FAILED (failures=1)
    """
)

# The exact BL59 shape: real per-test progress lines, then nothing — the run
# died mid-discovery with no "Ran N tests" line at all, yet the child that
# produced this text still exited 0.
TRUNCATED_BEFORE_SUMMARY = textwrap.dedent(
    """\
    test_a (tests.test_a.Case) ... ok
    test_b (tests.test_b.Case) ... ok
    test_c (tests.test_c.Case) ...
    """
)

# The count line printed, then truncated before any status word followed.
TRUNCATED_AFTER_COUNT = textwrap.dedent(
    """\
    test_a (tests.test_a.Case) ... ok

    ----------------------------------------------------------------------
    Ran 1 tests in 0.001s
    """
)


class SuiteVerdictTests(unittest.TestCase):
    """Direction 1: complete OK output with exit 0 is green."""

    def test_complete_ok_exit_zero_is_green(self):
        passed, message = keel_suite.suite_verdict(0, COMPLETE_OK)
        self.assertTrue(passed, message)
        self.assertIn("PASS", message)

    def test_ok_with_skipped_paren_is_still_green(self):
        passed, message = keel_suite.suite_verdict(0, COMPLETE_OK_SKIPPED)
        self.assertTrue(passed, message)

    def test_truncated_before_summary_with_exit_zero_is_red(self):
        """The exact BL59 shape: exit 0, no 'Ran N tests' line anywhere."""
        passed, message = keel_suite.suite_verdict(0, TRUNCATED_BEFORE_SUMMARY)
        self.assertFalse(passed)
        self.assertIn("BL59", message)
        self.assertIn("summary went unverified", message)

    def test_truncated_after_count_is_red(self):
        passed, message = keel_suite.suite_verdict(0, TRUNCATED_AFTER_COUNT)
        self.assertFalse(passed)
        self.assertIn("unverified", message)

    def test_complete_failed_exit_one_is_red(self):
        passed, message = keel_suite.suite_verdict(1, COMPLETE_FAILED)
        self.assertFalse(passed)
        self.assertIn("FAILED", message)

    def test_complete_failed_even_if_exit_code_were_zero(self):
        """A FAILED status line is red regardless of the child's exit code —
        fail-closed on the summary's own word, not only the process code."""
        passed, message = keel_suite.suite_verdict(0, COMPLETE_FAILED)
        self.assertFalse(passed)
        self.assertIn("FAILED", message)

    def test_empty_output_is_red_with_unverified_wording(self):
        passed, message = keel_suite.suite_verdict(0, "")
        self.assertFalse(passed)
        self.assertIn("no output was captured", message)

    def test_none_output_is_red(self):
        passed, message = keel_suite.suite_verdict(0, None)
        self.assertFalse(passed)
        self.assertIn("unverified", message)

    def test_ok_summary_but_nonzero_exit_is_red(self):
        """Belt and braces: a summary saying OK does not override a nonzero
        exit code — the two must agree."""
        passed, message = keel_suite.suite_verdict(1, COMPLETE_OK)
        self.assertFalse(passed)
        self.assertIn("exit code was 1", message)


class SuiteWrapperEndToEndTest(unittest.TestCase):
    """One cheap end-to-end run of the wrapper against a tiny fixture module,
    not full discovery — proves ``main`` wires the child, the log and the
    verdict together, without paying for the whole suite."""

    def test_wrapper_runs_a_tiny_module_and_reports_green(self):
        import subprocess

        repo_root = Path(__file__).resolve().parent.parent
        # A top-level file directly under tests/ (not a subpackage), so
        # ``discover -p`` finds it without depending on namespace-package
        # semantics for a fixtures/ directory that carries no __init__.py.
        fixture = repo_root / "tests" / "keel_suite_t626_tiny_pass.py"
        fixture.write_text(
            textwrap.dedent(
                """\
                import unittest

                class Tiny(unittest.TestCase):
                    def test_ok(self):
                        self.assertTrue(True)
                """
            ),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(repo_root / "scripts" / "keel_suite.py"),
                    "--",
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "keel_suite_t626_tiny_pass.py",
                    "-v",
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        finally:
            fixture.unlink(missing_ok=True)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("PASS", proc.stdout)


if __name__ == "__main__":
    unittest.main()
