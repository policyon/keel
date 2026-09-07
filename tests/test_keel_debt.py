#!/usr/bin/env python3
"""tests for ``keel debt`` - the keel:deferred marker harvest.

Contract
--------
Reads   : nothing outside temporary git fixture repositories this file builds
          and removes.
Emits   : unittest results only.
Writes  : nothing outside the temporary directories it creates.

Failure policy
--------------
FAIL-CLOSED, as every build-gate test here is: an environment that cannot run
a check fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. ``git`` is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KEEL_CLI = REPO_ROOT / "scripts" / "keel.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_debt  # noqa: E402  (path must be set first)


def run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run ``scripts/keel.py`` exactly as a caller would."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-B", str(KEEL_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
        env=env,
        timeout=120,
        check=False,
    )


class TestDebt(unittest.TestCase):
    """Both directions: a well-formed marker is caught, a clean tree passes."""

    def _repo(self, tmp: Path, tracked: dict[str, str]) -> Path:
        """A throwaway git repo with ``tracked`` files staged (not committed)."""
        root = tmp / "repo"
        root.mkdir()
        for name, text in tracked.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        for args in (["git", "init"], ["git", "add", "-A"]):
            result = subprocess.run(
                args, cwd=str(root), capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        return root

    def test_well_formed_marker_is_reported_with_its_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(
                Path(tmp),
                {
                    "app.py": (
                        "# keel:deferred(ceiling=only handles one locale; "
                        "trigger=a second locale is requested)\n"
                        "def render():\n    pass\n"
                    )
                },
            )
            result = run_cli(["debt", "--project", str(root)], root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("app.py:1", result.stdout)
            self.assertIn("only handles one locale", result.stdout)
            self.assertIn("a second locale is requested", result.stdout)
            self.assertNotIn("no-trigger rot risk", result.stdout)
            self.assertIn("1 deferral(s) on record", result.stdout)

    def test_missing_trigger_is_flagged_rot_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(
                Path(tmp),
                {"app.py": "# keel:deferred(ceiling=only handles one locale)\n"},
            )
            result = run_cli(["debt", "--project", str(root)], root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("no-trigger rot risk", result.stdout)
            self.assertIn("(missing)", result.stdout)

    def test_clean_repo_prints_the_empty_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"app.py": "def render():\n    pass\n"})
            result = run_cli(["debt", "--project", str(root)], root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "no deferrals on record")

    def test_untracked_files_marker_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"tracked.py": "def render():\n    pass\n"})
            (root / "untracked.py").write_text(
                "# keel:deferred(ceiling=leaks memory; trigger=process runs past a day)\n",
                encoding="utf-8",
            )
            result = run_cli(["debt", "--project", str(root)], root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.strip(), "no deferrals on record")
            self.assertNotIn("leaks memory", result.stdout)

    def test_scanner_error_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "not-a-repo"
            plain.mkdir()
            result = run_cli(["debt", "--project", str(plain)], plain)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_debt.__doc__ or "")

    def test_own_source_and_tests_are_excluded_from_findings(self) -> None:
        self.assertTrue(keel_debt.is_excluded("scripts/keel_debt.py"))
        self.assertTrue(keel_debt.is_excluded("tests/test_keel_debt.py"))
        self.assertTrue(keel_debt.is_excluded(".keel/audit/keel-audit.jsonl"))
        self.assertTrue(keel_debt.is_excluded(".keel/queue/keel-observations.jsonl"))
        self.assertFalse(keel_debt.is_excluded("scripts/keel_records.py"))


if __name__ == "__main__":
    unittest.main()
