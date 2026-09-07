#!/usr/bin/env python3
"""T320: the arming file's law names its own version.

Contract
--------
Reads   : synthetic git repositories built under ``tempfile``, never this
          repository's own ``.keel/keel-policy.md`` — the same "seed a
          miniature repo, prove the checker against it" pattern
          ``TestScanSet`` in ``tests/test_keel_phase0.py`` uses for
          ``check_refs``/``check_vendor_names``. Nothing is staged in the
          real repository as part of these tests. Also reads, as text,
          ``scripts/keel_checks.py``, ``.github/workflows/keel-ci.yml`` and
          ``skills/refit/SKILL.md`` — the wiring assertions: a check that is
          defined but invoked nowhere gates nothing.
Emits   : unittest results only.

Failure policy
--------------
FAIL-CLOSED, matching ``scripts/keel_checks.py``'s own stated policy: a
check that cannot run is a failure, never a pass.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402  (path must be set first)


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _commit(root: Path, message: str) -> None:
    result = _git(
        root,
        ["-c", "user.email=t320@example.com", "-c", "user.name=t320", "commit", "-q", "-m", message],  # keel-leak: ignore - example.com identity for a throwaway repo
    )
    assert result.returncode == 0, result.stderr


def _policy_text(version: str | None, amendment_versions: list[str], body_extra: str = "") -> str:
    """A minimal but structurally real arming-file text: frontmatter with (or
    without) a ``version:`` line, and an Amendment log table carrying one row
    per version in ``amendment_versions``."""
    version_line = f"version: {version}\n" if version is not None else ""
    rows = "".join(
        f"| {v} | 2026-08-25 | owner, in chat | fixture row |\n" for v in amendment_versions
    )
    return (
        "---\n"
        "tier: 2\n"
        f"{version_line}"
        "---\n\n"
        "# keel policy — fixture\n\n"
        f"{body_extra}"
        "## Amendment log\n\n"
        "| Version | Date | Ratified by | Change |\n"
        "|---|---|---|---|\n"
        f"{rows}"
    )


class TestPolicyVersionCheck(unittest.TestCase):
    """Fixture-based, both directions (convention 2)."""

    def _repo(self, tmp: str) -> Path:
        root = Path(tmp)
        result = _git(root, ["init", "-q"])
        self.assertEqual(result.returncode, 0, result.stderr)
        return root

    def _write_policy(self, root: Path, text: str) -> None:
        path = root / keel_checks.POLICY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _stage(self, root: Path) -> None:
        result = _git(root, ["add", "--", keel_checks.POLICY_FILE])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_absent_policy_file_in_a_bare_directory_passes(self) -> None:
        """No git repository at all — a tier-0 tree or a plain export."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse((root / ".git").exists())
            self.assertEqual(keel_checks.check_policy_version(root), [])

    def test_absent_policy_file_in_a_fresh_repo_passes(self) -> None:
        """A real git repository, but no commits and nothing staged: a
        project mid-``/keel:lay`` that has not adopted the arming file yet."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self.assertEqual(keel_checks.check_policy_version(root), [])

    def test_committed_unchanged_policy_passes(self) -> None:
        """The common case this repository's own tree is in: committed,
        nothing staged that touches it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._write_policy(root, _policy_text("1.0.0", ["1.0.0"]))
            self._stage(root)
            _commit(root, "seed policy")
            self.assertEqual(keel_checks.check_policy_version(root), [])

    def test_unrelated_staged_change_with_no_policy_history_passes(self) -> None:
        """A repo with commits, but none of them ever touched the policy
        file, and nothing staged touches it either — still legitimately
        absent, not a regression."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            _git(root, ["add", "--", "README.md"])
            _commit(root, "seed")
            self.assertEqual(keel_checks.check_policy_version(root), [])

    def test_staged_text_change_without_version_move_fails(self) -> None:
        """The core rule: text moved, version did not."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._write_policy(root, _policy_text("1.0.0", ["1.0.0"]))
            self._stage(root)
            _commit(root, "seed policy")

            self._write_policy(
                root, _policy_text("1.0.0", ["1.0.0"], body_extra="A new sentence.\n\n")
            )
            self._stage(root)

            findings = keel_checks.check_policy_version(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn(keel_checks.POLICY_FILE, findings[0])
            self.assertIn("did not move", findings[0])
            self.assertIn(keel_checks.POLICY_VERSION_DECISION, findings[0])

    def test_staged_text_change_with_version_move_and_log_row_passes(self) -> None:
        """The fix: text moved, version moved, and the Amendment log carries
        the new version's row."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._write_policy(root, _policy_text("1.0.0", ["1.0.0"]))
            self._stage(root)
            _commit(root, "seed policy")

            self._write_policy(
                root,
                _policy_text(
                    "1.0.1", ["1.0.0", "1.0.1"], body_extra="A new sentence.\n\n"
                ),
            )
            self._stage(root)

            self.assertEqual(keel_checks.check_policy_version(root), [])

    def test_version_moved_without_a_log_row_fails(self) -> None:
        """Clause (b): the version bumped, but no Amendment log row names it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._write_policy(root, _policy_text("1.0.0", ["1.0.0"]))
            self._stage(root)
            _commit(root, "seed policy")

            self._write_policy(
                root, _policy_text("1.0.1", ["1.0.0"], body_extra="A new sentence.\n\n")
            )
            self._stage(root)

            findings = keel_checks.check_policy_version(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("no row for it", findings[0])
            self.assertIn(keel_checks.POLICY_VERSION_DECISION, findings[0])

    def test_missing_version_line_after_baseline_fails(self) -> None:
        """The baseline now exists, so an absent ``version:`` line is a
        regression, not a legitimate absence."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            self._write_policy(root, _policy_text("1.0.0", ["1.0.0"]))
            self._stage(root)
            _commit(root, "seed policy")

            self._write_policy(
                root, _policy_text(None, ["1.0.0"], body_extra="A new sentence.\n\n")
            )
            self._stage(root)

            findings = keel_checks.check_policy_version(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("no 'version:' frontmatter", findings[0])
            self.assertIn(keel_checks.POLICY_VERSION_DECISION, findings[0])

    def test_this_repository_passes(self) -> None:
        """The live repository: policy is committed and unchanged, so the
        check must be quiet."""
        self.assertEqual(keel_checks.check_policy_version(REPO_ROOT), [])


class TestAbsenceIsNotFailure(unittest.TestCase):
    """``_git_show_path`` keeps "not there" and "git cannot answer" apart.

    Both directions, because the first version of this helper collapsed them:
    every nonzero ``git show`` became ``None``, and ``None`` means pass.
    """

    def _repo_with_policy(self, root: Path) -> None:
        result = _git(root, ["init", "-q"])
        self.assertEqual(result.returncode, 0, result.stderr)
        path = root / keel_checks.POLICY_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_policy_text("1.0.0", ["1.0.0"]), encoding="utf-8")
        result = _git(root, ["add", "--", keel_checks.POLICY_FILE])
        self.assertEqual(result.returncode, 0, result.stderr)
        _commit(root, "seed policy")

    def _break_head(self, root: Path) -> None:
        """Point the checked-out branch at an object that does not exist —
        a corrupt ref, the shape a damaged repository actually takes."""
        branch = _git(root, ["symbolic-ref", "--short", "HEAD"]).stdout.strip()
        self.assertTrue(branch, "fixture repo has no checked-out branch")
        ref = root / ".git" / "refs" / "heads" / branch
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text("0" * 40 + "\n", encoding="utf-8")

    def test_absent_path_at_both_surfaces_is_none(self) -> None:
        """The pass direction, at the helper level: a real repository with
        commits where nothing ever named the policy file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_git(root, ["init", "-q"]).returncode, 0)
            (root / "README.md").write_text("hello\n", encoding="utf-8")
            _git(root, ["add", "--", "README.md"])
            _commit(root, "seed")
            self.assertIsNone(
                keel_checks._git_show_path(root, "HEAD", keel_checks.POLICY_FILE)
            )
            self.assertIsNone(
                keel_checks._git_show_path(root, "", keel_checks.POLICY_FILE)
            )

    def test_present_path_returns_its_text(self) -> None:
        """The other half of the pass direction: present at both surfaces
        returns the text, not ``None``."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_policy(root)
            head = keel_checks._git_show_path(root, "HEAD", keel_checks.POLICY_FILE)
            index = keel_checks._git_show_path(root, "", keel_checks.POLICY_FILE)
            self.assertIsNotNone(head)
            self.assertEqual(head, index)
            self.assertIn("version: 1.0.0", head or "")

    def test_unborn_head_is_absence_not_failure(self) -> None:
        """A repository with no commits: ``HEAD`` legitimately does not
        resolve, and that stays a pass."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(_git(root, ["init", "-q"]).returncode, 0)
            self.assertFalse(keel_checks._git_head_exists(root))
            self.assertIsNone(
                keel_checks._git_show_path(root, "HEAD", keel_checks.POLICY_FILE)
            )

    def test_a_damaged_ref_is_not_read_as_an_unborn_head(self) -> None:
        """The two states the old helper could not tell apart, asserted side by
        side: no commit yet is False, a ref git cannot read raises."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_policy(root)
            self.assertTrue(keel_checks._git_head_exists(root))
            self._break_head(root)
            with self.assertRaises(RuntimeError):
                keel_checks._git_head_exists(root)

    def test_corrupt_head_ref_raises_instead_of_returning_none(self) -> None:
        """The fail direction: git exits nonzero for a reason that is NOT
        absence. The helper must raise, not answer ``None``."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_policy(root)
            self._break_head(root)
            with self.assertRaises(RuntimeError):
                keel_checks._git_show_path(root, "HEAD", keel_checks.POLICY_FILE)

    def test_corrupt_head_ref_makes_the_check_report_an_error(self) -> None:
        """The same failure at the check level: ``check_policy_version``
        surfaces it rather than passing quietly on a broken repository."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_policy(root)
            self._break_head(root)
            with self.assertRaises(RuntimeError):
                keel_checks.check_policy_version(root)

    def test_unclassifiable_rev_is_refused_not_answered(self) -> None:
        """A rev git cannot parse returned ``None`` — a pass — before this fix.
        It now raises: this helper reads two named surfaces and refuses to
        answer for anything whose absence it could not verify."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._repo_with_policy(root)
            with self.assertRaises(ValueError):
                keel_checks._git_show_path(
                    root, "HEAD^{bogus}", keel_checks.POLICY_FILE
                )

    def test_broken_git_directory_raises_but_no_repository_is_absence(self) -> None:
        """``.git`` present but unusable is a broken repository (raises);
        no ``.git`` at all is a bare export (absent, passes)."""
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken"
            broken.mkdir()
            (broken / ".git").write_text(
                "gitdir: " + str(Path(tmp) / "nowhere") + "\n", encoding="utf-8"
            )
            with self.assertRaises(RuntimeError):
                keel_checks._git_show_path(broken, "HEAD", keel_checks.POLICY_FILE)

            bare = Path(tmp) / "bare"
            bare.mkdir()
            self.assertIsNone(
                keel_checks._git_show_path(bare, "HEAD", keel_checks.POLICY_FILE)
            )


class TestEveryCheckIsWiredIn(unittest.TestCase):
    """The drift that made this retry necessary, closed by construction: a
    check that exists but runs nowhere that gates a push."""

    WORKFLOW = REPO_ROOT / ".github" / "workflows" / "keel-ci.yml"

    def _checks_step_command(self) -> str:
        text = self.WORKFLOW.read_text(encoding="utf-8")
        lines = [
            line.strip()
            for line in text.splitlines()
            if "keel_checks.py" in line and line.strip().startswith("run:")
        ]
        self.assertEqual(len(lines), 1, f"expected one keel_checks step, got {lines}")
        return lines[0]

    def test_ci_invokes_the_checker_with_no_flags(self) -> None:
        """CI must not enumerate checks: the enumeration is what went stale."""
        command = self._checks_step_command()
        self.assertEqual(command, "run: python scripts/keel_checks.py", command)

    def test_the_registry_is_the_only_check_list(self) -> None:
        """Every check ``main`` runs is registered in ``CHECKS``, and every
        registered check is run by ``main`` — so registering a check is the
        whole of wiring it in, and CI's no-flag run cannot miss one."""
        source = (REPO_ROOT / "scripts" / "keel_checks.py").read_text(encoding="utf-8")
        dispatched = set(re.findall(r'"([a-z]+)" in selected', source))
        registered = {name for name, _ in keel_checks.CHECKS}
        self.assertEqual(dispatched, registered)
        self.assertIn("policy", registered)

    def test_main_reports_every_registered_check(self) -> None:
        """BL20: the BEHAVIOURAL half of the test above, and the half that was
        missing when it mattered.

        WHAT THE SOURCE-PARSING TEST CANNOT SEE. It asserts that the string
        ``"<name>" in selected`` appears, which catches a DELETED dispatch block
        and nothing else. An ``if`` whose body never calls ``_report`` satisfies
        it perfectly — and so does a body that reports a different check twice.

        WHY THIS EXISTS. On 2026-09-01 the leak check was registered in
        ``CHECKS`` and given no dispatch line. ``keel_checks.py`` printed EIGHT
        PASS lines and returned a real exit 0, because ``passed`` was never
        touched by the check that never ran. It read exactly like success, and it
        was caught only because a human-written acceptance criterion said NINE.
        The next check added has no such criterion waiting for it; this test is
        that criterion, permanently.

        WHAT IS ASSERTED IS DISPATCH, NOT OUTCOME. Every registered name must
        appear in a PASS or FAIL line — pass and fail are equally fine. Asserting
        this repository's own checks pass would make every unrelated violation
        anywhere in the tree fail this test too, which is a different claim and a
        flakier one.
        """
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            keel_checks.main([])
        printed = buffer.getvalue()
        silent = [
            name
            for name, _ in keel_checks.CHECKS
            if not re.search(rf"^(?:PASS|FAIL) {re.escape(name)}\b", printed, re.M)
        ]
        self.assertEqual(
            silent,
            [],
            "registered but never reported by main - selected, skipped, and "
            f"green: {silent}",
        )

    def test_no_flags_selects_every_registered_check(self) -> None:
        """The default itself, asserted rather than assumed: parsing an empty
        argv selects all of ``CHECKS``; one flag selects exactly that one."""
        parser = argparse.ArgumentParser()
        for name, help_text in keel_checks.CHECKS:
            parser.add_argument(f"--{name}", action="store_true", help=help_text)
        empty = parser.parse_args([])
        self.assertEqual(
            [name for name, _ in keel_checks.CHECKS if getattr(empty, name)], []
        )
        one = parser.parse_args(["--policy"])
        self.assertEqual(
            [name for name, _ in keel_checks.CHECKS if getattr(one, name)], ["policy"]
        )

    def test_the_policy_check_runs_as_its_own_flag(self) -> None:
        """End to end through the real entry point: ``--policy`` alone reports
        PASS on this repository and exits 0."""
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "keel_checks.py"), "--policy"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS policy", result.stdout)

    def test_the_refit_skill_claim_matches_the_wiring(self) -> None:
        """The skill promises the checker catches a skipped bump. That promise
        is only true while CI runs the check, so the two are asserted
        together."""
        skill = (REPO_ROOT / "skills" / "refit" / "SKILL.md").read_text(encoding="utf-8")
        prose = " ".join(skill.split())  # line wrapping is not the claim
        self.assertIn("check_policy_version", prose)
        self.assertIn(
            "keel's own CI runs `scripts/keel_checks.py` with no flags", prose,
            "the skill's promise rests on the no-flag CI invocation",
        )
        self.assertEqual(
            "run: python scripts/keel_checks.py",
            self._checks_step_command(),
            "and that invocation is what the workflow actually does",
        )


if __name__ == "__main__":
    unittest.main()
