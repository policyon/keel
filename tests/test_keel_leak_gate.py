#!/usr/bin/env python3
"""The leak gate: what check_leak refuses, what it lets through, and why.

Contract
--------
Reads   : ``scripts/keel_checks.py``'s :func:`check_leak` and the scanner it
          delegates to, plus temporary git repositories this file builds and
          removes. It also reads THIS repository once, to pin a property of its
          current state that survives the state changing.
Emits   : unittest results only.
Writes  : nothing outside a temporary directory.
Argv    : none.

Why both directions are pinned here
-----------------------------------
A gate that cannot be shown to FAIL is not evidence of anything. Every case
below therefore comes in a pair: a planted finding is reported, and the same
finding carrying the scanner's own ``keel-leak: ignore`` marker is not. The
scope exemption is pinned the same way — a finding in a record surface is not
reported, and the identical finding one directory over is.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402
import keel_leak_check  # noqa: E402

#: Built at runtime so this file does not itself carry a home-path shape that
#: its own subject would report. The scanner matches ``/home/<name>``.
PLANTED_HOME = "/" + "home" + "/planted-name/notes.txt"

#: The policy-locked directories. A finding inside one of these cannot be
#: declared by an agent, because the line that would carry the marker is in a
#: file only the owner may write (``.keel/backlog.md`` BL18 and the six
#: findings named at ``CHECKS``).
LOCKED_PREFIXES = ("hooks/", ".claude-plugin/")


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=str(root), capture_output=True, text=True, check=True
    )


def _repo(root: Path, files: dict[str, str]) -> Path:
    """A git work tree with ``files`` staged - staged is enough, because the
    scanner reads ``git ls-files``, which is the index rather than a commit."""
    _git(root, "init", "-q")
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    return root


class TestAPlantedFindingIsReported(unittest.TestCase):
    def test_a_home_path_in_a_shipped_file_fails_the_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": f"see {PLANTED_HOME}\n"})
            findings = keel_checks.check_leak(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/guide.md", findings[0])
            self.assertIn("home_path", findings[0])

    def test_the_message_says_how_to_declare_it(self) -> None:
        """A refusal that does not name its own remedy sends the reader looking
        for one - the defect BL16 was filed for elsewhere in this tree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": f"see {PLANTED_HOME}\n"})
            findings = keel_checks.check_leak(root)
            self.assertIn("keel-leak: ignore", findings[0])

    def test_the_same_line_with_the_marker_is_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                {"docs/guide.md": f"see {PLANTED_HOME}  <!-- keel-leak: ignore - example -->\n"},
            )
            self.assertEqual(keel_checks.check_leak(root), [])


class TestTheRecordSurfacesAreOutOfScope(unittest.TestCase):
    """The one exemption, pinned in both directions so its edge is real."""

    def test_a_finding_in_the_audit_log_is_not_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                {".keel/audit/keel-audit.jsonl": '{"detail": "%s"}\n' % PLANTED_HOME},
            )
            self.assertEqual(keel_checks.check_leak(root), [])

    def test_the_identical_finding_one_directory_over_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                {".keel/decisions/a.md": '{"detail": "%s"}\n' % PLANTED_HOME},
            )
            self.assertEqual(len(keel_checks.check_leak(root)), 1)

    def test_every_exempt_prefix_is_under_the_record_directory(self) -> None:
        """A scope that could grow to cover source is not a scope. Each prefix
        names a record surface, and the shipped-cut declaration is what makes
        that safe."""
        for prefix in keel_checks.LEAK_RECORD_SURFACES:
            with self.subTest(prefix=prefix):
                self.assertTrue(prefix.startswith(".keel/"), prefix)
                self.assertTrue(prefix.endswith("/"), prefix)

    def test_the_prefix_test_is_separator_agnostic(self) -> None:
        """git reports forward slashes; a Windows caller may hold backslashes.
        Both spellings of the same path are the same surface."""
        self.assertTrue(keel_checks._leak_is_record_surface(".keel/audit/x.jsonl"))
        self.assertTrue(
            keel_checks._leak_is_record_surface(".keel" + chr(92) + "audit" + chr(92) + "x.jsonl")
        )
        self.assertFalse(keel_checks._leak_is_record_surface("docs/audit/x.md"))


class TestTheCheckFailsClosed(unittest.TestCase):
    def test_a_tree_that_is_not_a_git_repository_is_a_violation(self) -> None:
        """Not a clean answer: a scan that cannot enumerate what to scan knows
        nothing, and reporting nothing would read as knowing everything."""
        with tempfile.TemporaryDirectory() as tmp:
            findings = keel_checks.check_leak(Path(tmp) / "no-repo-here")
            self.assertEqual(len(findings), 1)
            self.assertIn("could not enumerate", findings[0])

    def test_an_empty_enumeration_is_a_violation(self) -> None:
        """The harder half of the case above, and the one that shipped broken:
        a REAL repository that tracks nothing. ``git ls-files`` exits 0 with no
        output here, so the failure arrives as an empty list rather than as an
        exception - indistinguishable from a clean tree unless something
        refuses it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _git(root, "init", "-q")
            findings = keel_checks.check_leak(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("could not enumerate", findings[0])
            self.assertIn("zero files", findings[0])

    def test_the_same_repository_with_one_file_is_clean(self) -> None:
        """The other direction, so the case above pins the EMPTINESS rather
        than merely the freshly-initialised repository."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": "nothing to see\n"})
            self.assertEqual(keel_checks.check_leak(root), [])

    def test_a_tracked_file_the_scan_never_read_is_a_violation(self) -> None:
        """Staged, then deleted from the work tree: ``git ls-files`` still
        names it, so the scanner is handed a file that is not there. It
        contributes no findings - which is exactly what a clean file
        contributes - so the OUTCOME and not the finding list has to carry
        this."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": "nothing to see\n"})
            (root / "docs" / "guide.md").unlink()
            findings = keel_checks.check_leak(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/guide.md", findings[0])
            self.assertIn("never read", findings[0])

    def test_an_unread_record_surface_is_not_a_violation(self) -> None:
        """The blind-file rule keeps the same scope as the findings rule: a
        record surface is out of scope whether or not it could be read."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                {
                    ".keel/audit/keel-audit.jsonl": "{}\n",
                    "docs/guide.md": "nothing to see\n",
                },
            )
            (root / ".keel" / "audit" / "keel-audit.jsonl").unlink()
            self.assertEqual(keel_checks.check_leak(root), [])


class TestTheScanCensusSeesWhatTheFindingsCannot(unittest.TestCase):
    """The counts exist so that a blind scan is visible rather than green.
    Pinned directly, because the gate's message is built from them."""

    def test_the_report_separates_every_outcome(self) -> None:
        """Four files, four outcomes. The binary one carries a NUL so it is
        classified by its CONTENT: keying this test on a binary EXTENSION would
        have made it a test of ``BINARY_EXTENSIONS`` membership instead."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(
                Path(tmp),
                {
                    "docs/guide.md": "nothing to see\n",
                    "docs/gone.md": "staged, then deleted\n",
                },
            )
            (root / "art").mkdir()
            (root / "art" / "blob.dat").write_bytes(b"real\x00binary\n")
            (root / "art" / "logo.png").write_text("plaintext despite the name\n")
            _git(root, "add", "-A")
            (root / "docs" / "gone.md").unlink()
            tracked = keel_leak_check.tracked_files(str(root))
            report = keel_leak_check.scan_tree_reported(str(root), tracked, [])
            self.assertEqual(report.scanned, ["docs/guide.md"])
            self.assertEqual(
                sorted(report.skipped),
                [
                    ("art/blob.dat", keel_leak_check.BINARY),
                    ("art/logo.png", keel_leak_check.EXTENSION),
                ],
            )
            self.assertEqual(report.blind, [("docs/gone.md", keel_leak_check.ABSENT)])

    def test_an_extension_skip_is_never_reported_as_read(self) -> None:
        """The distinction that earns ``EXTENSION`` its own constant: this file
        is plain text holding a real finding, and the scanner never opens it.
        That is a known limit of the extension shortcut, and the census has to
        say so rather than counting it among the files it read."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": "nothing to see\n"})
            (root / "secrets.gz").write_text(f"see {PLANTED_HOME}\n")
            _git(root, "add", "-A")
            tracked = keel_leak_check.tracked_files(str(root))
            report = keel_leak_check.scan_tree_reported(str(root), tracked, [])
            self.assertNotIn("secrets.gz", report.scanned)
            self.assertIn(("secrets.gz", keel_leak_check.EXTENSION), report.skipped)
            self.assertEqual(report.findings, [])

    def test_an_unknown_outcome_raises_rather_than_landing_in_a_bucket(self) -> None:
        """The fail-closed half of the census. A future outcome that no branch
        claims must stop the scan, not fall into whichever bucket is last —
        that is how a new skip path would arrive already counted as clean."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": "nothing to see\n"})
            tracked = keel_leak_check.tracked_files(str(root))
            original = keel_leak_check.scan_file_reported
            keel_leak_check.scan_file_reported = lambda *a, **k: ([], "invented")
            try:
                with self.assertRaises(RuntimeError) as caught:
                    keel_leak_check.scan_tree_reported(str(root), tracked, [])
            finally:
                keel_leak_check.scan_file_reported = original
            self.assertIn("unknown scan outcome", str(caught.exception))

    def test_the_gate_refuses_exactly_the_blind_outcomes(self) -> None:
        """``BLIND_OUTCOMES`` drives the gate rather than merely describing it,
        so this exercises ``check_leak`` itself: each blind outcome becomes a
        violation, and each skipped outcome does not."""
        self.assertEqual(
            set(keel_leak_check.BLIND_OUTCOMES) | set(keel_leak_check.SKIPPED_OUTCOMES),
            {
                keel_leak_check.ABSENT,
                keel_leak_check.UNREADABLE,
                keel_leak_check.BINARY,
                keel_leak_check.EXTENSION,
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = _repo(Path(tmp), {"docs/guide.md": "nothing to see\n"})
            (root / "art").mkdir()
            (root / "art" / "blob.dat").write_bytes(b"real\x00binary\n")
            _git(root, "add", "-A")
            self.assertEqual(keel_checks.check_leak(root), [])
            (root / "docs" / "guide.md").unlink()
            self.assertEqual(len(keel_checks.check_leak(root)), 1)


class TestThisRepositoryIsWhereTheWorkLeftIt(unittest.TestCase):
    """One assertion about the real tree, written so it stays true when the
    remaining six findings are declared: whatever is left must be in a file an
    agent cannot write. The moment a finding appears anywhere else, this fails
    and names it."""

    def test_every_remaining_finding_is_in_a_policy_locked_file(self) -> None:
        tracked = keel_leak_check.tracked_files(str(REPO_ROOT))
        findings = keel_leak_check.scan_tree(str(REPO_ROOT), tracked, [])
        payload = [
            f for f in findings if not keel_checks._leak_is_record_surface(f.path)
        ]
        stray = [
            f"{f.path}:{f.line} [{f.rule}]"
            for f in payload
            if not f.path.replace(chr(92), "/").startswith(LOCKED_PREFIXES)
        ]
        self.assertEqual(
            stray,
            [],
            "undeclared leak finding(s) outside the policy-locked files: "
            + ", ".join(stray),
        )


if __name__ == "__main__":
    unittest.main()
