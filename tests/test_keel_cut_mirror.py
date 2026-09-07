#!/usr/bin/env python3
"""BL7: the mirror cut script's guards, its record exclusion, and its ordering.

Contract
--------
Reads   : synthetic git repositories built under ``tempfile`` — the same
          "seed a miniature repo, prove the checker against it" pattern
          ``tests/test_keel_policy_version_t320.py`` uses. NEVER this
          repository's own tree as a cut TARGET, and never the real mirror:
          every destructive assertion runs against a temporary directory.
          The development-repository side is a synthetic repo too, so these
          tests do not depend on this project's own history.
Emits   : unittest results only. Nothing is staged in the real repository.

Why this module exists
----------------------
The first rehearsal of ``scripts/keel_cut_mirror.py`` copied a whole
development record directory into the tree it was assembling, because a path
normalisation stripped the leading dot from the exclusion prefix
(``".keel/x".lstrip("./")`` is ``"keel/x"``). That is the single worst thing
this script can do — a published cut exists precisely to ship WITHOUT those
records — and it exited 0 while doing it. The record-exclusion tests below
pin the fix at three independent layers, and the staging tests pin the other
silent-publication path: ``git add -A`` staging a local audit line or a
session ledger.

Failure policy
--------------
FAIL-CLOSED, matching the script's own: a guard that cannot decide refuses.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_cut_mirror as cut_mirror  # noqa: E402  (path must be set first)


def _git(root: Path, args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, ["init", "-q"])
    _git(root, ["config", "user.email", "t@example.invalid"])  # keel-leak: ignore - example.invalid identity for a throwaway repo
    _git(root, ["config", "user.name", "test"])


def _commit_all(root: Path, message: str = "seed") -> str:
    _git(root, ["add", "-A"])
    _git(root, ["commit", "-q", "-m", message])
    return _git(root, ["rev-parse", "HEAD"]).stdout.strip()


def _write(root: Path, rel: str, body: str) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _seed_private(root: Path) -> str:
    """A miniature development repository: real tree plus record directory."""
    _init_repo(root)
    _write(root, "README.md", "# project\n")
    _write(root, "docs/guide.md", "guide\n")
    _write(root, ".keel/keel-policy.md", "---\ntier: 2\nversion: 9.9.9\n---\n\n# policy\n")
    # Ships INSTEAD of the arming file: a disarmed cut that also shipped no
    # template would leave an adopter nothing to arm with.
    _write(root, "templates/keel-policy.md", "---\ntier: 1\n---\n\n# template\n")
    _write(root, ".keel/knowledge/a-lesson.md", "private lesson\n")
    _write(root, ".keel/plans/keel-plan-deadbeef.md", "private ledger\n")
    _write(root, ".keel/backlog.md", "private backlog\n")
    _write(root, ".keel/audit/keel-audit.jsonl", '{"private":"event"}\n')
    _write(
        root,
        ".keel/decisions/2026-01-01-a-cited-decision.md",
        "cited decision, current\n",
    )
    return _commit_all(root, "private seed")


def _seed_mirror(root: Path) -> None:
    """A miniature published cut: marker, empty surfaces, cited decision."""
    _init_repo(root)
    _write(root, ".keel/published-cut.md", "# published cut\n")
    _write(root, ".keel/keel-policy.md", "STALE ARMING FILE\n")
    _write(root, ".keel/audit/keel-audit.jsonl", "")
    _write(root, ".keel/queue/keel-observations.jsonl", "")
    _write(
        root,
        ".keel/decisions/2026-01-01-a-cited-decision.md",
        "cited decision, STALE\n",
    )
    _write(root, "OLDFILE.txt", "must be deleted by the cut\n")
    _write(root, "olddir/gone.txt", "must be deleted by the cut\n")
    _commit_all(root, "mirror seed")


class TestPathNormalisation(unittest.TestCase):
    """The bug that leaked the records, pinned in both directions."""

    def test_leading_dot_survives_normalisation(self) -> None:
        # The regression itself: lstrip("./") would return "keel/audit/x".
        self.assertEqual(
            cut_mirror._archive_member_name(".keel/audit/x"), ".keel/audit/x"
        )

    def test_dot_slash_prefix_is_stripped_but_the_dotfile_is_not(self) -> None:
        self.assertEqual(
            cut_mirror._archive_member_name("./.keel/audit/x"), ".keel/audit/x"
        )
        self.assertEqual(cut_mirror._archive_member_name("./docs/a.md"), "docs/a.md")

    def test_backslashes_are_normalised(self) -> None:
        self.assertEqual(
            cut_mirror._archive_member_name(r".keel\audit\x"), ".keel/audit/x"
        )

    def test_record_paths_are_recognised(self) -> None:
        for name in (".keel", ".keel/audit/x", ".keel/knowledge/y.md"):
            self.assertTrue(cut_mirror._is_record_path(name), name)

    def test_non_record_paths_are_not_recognised(self) -> None:
        # ".github" must NOT match: a prefix test loose enough to catch it
        # would delete the workflows out of every cut.
        for name in ("docs/a.md", ".github/w.yml", "keel/audit/x", ".keelish/x"):
            self.assertFalse(cut_mirror._is_record_path(name), name)


class TestRecordExportAssertion(unittest.TestCase):
    """The fail-closed backstop behind the filter and the sweep."""

    def test_assertion_refuses_a_tree_carrying_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _write(tree, ".keel/knowledge/leak.md", "leaked\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.assert_no_records_exported(tree)
            self.assertIn(".keel", str(caught.exception))

    def test_assertion_passes_a_clean_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _write(tree, "README.md", "# ok\n")
            cut_mirror.assert_no_records_exported(tree)  # must not raise

    def test_export_drops_the_record_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            work = base / "work"
            work.mkdir()
            tree = cut_mirror.export_tip(private, tip, work)
            self.assertTrue((tree / "README.md").is_file())
            self.assertTrue((tree / "docs/guide.md").is_file())
            self.assertFalse(
                (tree / ".keel").exists(),
                "the development record directory reached the exported tree",
            )


class TestGuards(unittest.TestCase):
    """Every refusal, before anything is destroyed."""

    def test_refuses_when_mirror_is_the_development_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            private = Path(tmp) / "private"
            tip = _seed_private(private)
            _write(private, ".keel/published-cut.md", "# marker\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, private, tip)
            self.assertIn("same tree", str(caught.exception))

    def test_refuses_a_tree_without_the_cut_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            (mirror / cut_mirror.CUT_MARKER).unlink()
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, tip)
            self.assertIn(cut_mirror.CUT_MARKER, str(caught.exception))

    def test_refuses_a_mirror_with_a_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _git(mirror, ["remote", "add", "origin", "https://example.invalid/x.git"])
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, tip)
            self.assertIn("remote", str(caught.exception))

    def test_refuses_a_tip_that_does_not_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, "no-such-rev")
            self.assertIn("does not resolve", str(caught.exception))

    def test_refuses_a_non_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            plain = base / "plain"
            plain.mkdir()
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, plain, tip)
            self.assertIn("not a git repository", str(caught.exception))

    def test_guards_pass_a_well_formed_mirror(self) -> None:
        # The passing control: without it the refusals above could all be
        # firing for the wrong reason.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            self.assertEqual(cut_mirror.guard(private, mirror, tip), tip)


class TestUntrackedStrays(unittest.TestCase):
    """A file the clear cannot delete must stop the cut, not ride into it."""

    def test_refuses_an_untracked_non_record_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, "STRAY.txt", "a file nobody tracked\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, tip)
            self.assertIn("STRAY.txt", str(caught.exception))

    def test_an_ignored_stray_is_not_a_stray(self) -> None:
        # The passing control that keeps the guard usable: build output a
        # mirror's .gitignore covers must not block a cut.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, ".gitignore", "build/\n")
            _commit_all(mirror, "ignore build output")
            _write(mirror, "build/artifact.bin", "ignored\n")
            self.assertEqual(cut_mirror.untracked_non_record(mirror), [])
            self.assertEqual(cut_mirror.guard(private, mirror, tip), tip)

    def test_a_session_ledger_is_not_counted_as_a_STRAY(self) -> None:
        # The two guards must not double-report the same file. A ledger lives
        # under the record prefix, so the stray guard ignores it entirely and
        # the dedicated session-ledger refusal is what speaks — otherwise the
        # owner would be told to delete it by a message that also claims a cut
        # "cannot honestly replace" it, which is not the reason.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, ".keel/plans/keel-plan-bc9349b1.md", "scaffolding\n")
            self.assertEqual(cut_mirror.untracked_non_record(mirror), [])
            self.assertEqual(
                cut_mirror.session_ledgers(mirror),
                [".keel/plans/keel-plan-bc9349b1.md"],
            )


class TestDisarming(unittest.TestCase):
    """A published cut ships UNARMED, and ships a template to arm FROM.

    Ratified 2026-08-31
    (`.keel/decisions/2026-08-31-the-shipped-product-is-not-armed.md`). This
    class REPLACES the previous `TestArmingFileRefusals`, which pinned
    `write_arming_file`/`verify_arming_file` — functions the decision retired
    along with the whole write-it-last ordering and its backup/restore path.
    Those tests are gone because their subject is gone, not because they were
    weakened; the properties that mattered are re-pinned below against the new
    contract.
    """

    def test_the_cut_removes_a_pre_existing_arming_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)  # seeds an arming file
            self.assertTrue((mirror / cut_mirror.ARMING_FILE).is_file())
            work = base / "work"
            work.mkdir()
            report = cut_mirror.cut(private, mirror, tip, work)
            self.assertTrue(report["disarmed"])
            self.assertFalse(
                (mirror / cut_mirror.ARMING_FILE).exists(),
                "the cut shipped an arming file, arming the adopter's tree for them",
            )

    def test_the_cut_refuses_a_tree_carrying_a_session_ledger(self) -> None:
        # REFUSES, does not delete. Ratified 2026-08-31 after the owner caught
        # an earlier version deleting a file this session had said was theirs.
        # Removing a record is the owner's call — the same call keel's own
        # plan-contract guard reserves to them — and `guard()` already refuses
        # rather than deleting untracked strays for the same reason.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, ".keel/plans/keel-plan-bc9349b1.md", "scaffolding\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, tip)
            self.assertIn("keel-plan-bc9349b1.md", str(caught.exception))
            self.assertIn("will NOT delete", str(caught.exception))
            # And it is still there: a refusal destroys nothing.
            self.assertTrue((mirror / ".keel/plans/keel-plan-bc9349b1.md").is_file())

    def test_a_freeze_record_is_not_a_session_ledger(self) -> None:
        # The passing control, and it still passes for its own reason: a freeze
        # record is not a ledger, so `session_ledgers` ignores it and `guard`
        # lets the cut proceed. What CHANGED on 2026-09-01 is what happens next
        # — the cut now removes it, because a cut ships no records at all. The
        # two facts are independent and both are asserted here: a check keyed
        # too loosely would block the cut, and the records ruling removes the
        # file without any check being involved.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            freeze = ".keel/plans/keel-freeze-2026-08-21-abcdef12.md"
            _write(mirror, freeze, "freeze\n")
            # THE ORIGINAL PROPERTY, unchanged: a freeze record is not a session
            # ledger, so the ledger check does not claim it.
            self.assertEqual(cut_mirror.session_ledgers(mirror), [])
            # WHAT CHANGED: it is now an untracked RECORD, and a cut ships none.
            # The guard refuses before the first destructive step and does not
            # delete it — the same posture the ledger refusal takes.
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.guard(private, mirror, tip)
            self.assertIn("keel-freeze-2026-08-21-abcdef12.md", str(caught.exception))
            self.assertIn("will NOT", str(caught.exception))
            self.assertTrue((mirror / freeze).is_file(), "a refusal destroyed a record")
            # And a TRACKED freeze record is removed by the strip step instead,
            # which is the other half of the same ruling.
            _commit_all(mirror, "track the freeze record")
            self.assertEqual(cut_mirror.untracked_records(mirror), [])
            removed, _rewritten = cut_mirror.strip_records_and_declare(mirror)
            self.assertIn(freeze, removed)
            self.assertFalse((mirror / freeze).exists())

    def test_disarming_is_idempotent(self) -> None:
        # A cut of an already-disarmed tree is not an error, so re-cutting works.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            work = base / "work"
            work.mkdir()
            cut_mirror.cut(private, mirror, tip, work)
            work2 = base / "work2"
            work2.mkdir()
            report = cut_mirror.cut(private, mirror, tip, work2)
            self.assertFalse(report["disarmed"], "nothing was there to remove")
            self.assertFalse((mirror / cut_mirror.ARMING_FILE).exists())

    def test_refuses_when_an_arming_file_survives(self) -> None:
        # The backstop for the property itself: if anything ever re-created the
        # file after `disarm`, the cut must refuse rather than ship it.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, cut_mirror.POLICY_TEMPLATE, "---\ntier: 1\n---\n\n# template\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.verify_disarmed(private, mirror, tip)
            self.assertIn("still present", str(caught.exception))

    def test_refuses_when_the_template_is_absent_from_the_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            cut_mirror.disarm(mirror)
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.verify_disarmed(private, mirror, tip)
            self.assertIn("missing", str(caught.exception))

    def test_refuses_when_the_template_is_absent_at_the_tip(self) -> None:
        # A disarmed cut with no template anywhere leaves an adopter nothing to
        # arm with, so this fails closed rather than shipping a dead end.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            _init_repo(private)
            _write(private, "README.md", "# project\n")
            tip = _commit_all(private, "no template")
            mirror = base / "mirror"
            _seed_mirror(mirror)
            cut_mirror.disarm(mirror)
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.verify_disarmed(private, mirror, tip)
            self.assertIn("does not exist", str(caught.exception))

    def test_refuses_a_stale_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            cut_mirror.disarm(mirror)
            _write(mirror, cut_mirror.POLICY_TEMPLATE, "an older template\n")
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.verify_disarmed(private, mirror, tip)
            self.assertIn("stale template", str(caught.exception))


class TestOtherRefusals(unittest.TestCase):
    """Refusals the first round of tests left uncovered."""

    def test_a_mirror_tracking_no_decision_records_is_now_the_correct_state(
        self,
    ) -> None:
        """THE INVERSE OF A REFUSAL THAT WAS DELETED, kept as a test so the
        reversal is pinned rather than merely absent.

        Until 2026-09-01 an empty decisions directory was a CutError: the cut
        shipped five records and refused a mirror that tracked none. The owner
        ruled that a cut ships no records, so the state that used to be refused
        is now the only correct one. A deleted refusal leaves no evidence it was
        ever reversed; this does.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _init_repo(mirror)
            _write(mirror, ".keel/published-cut.md", "# published cut\n")
            _commit_all(mirror, "no decisions")
            removed, rewritten = cut_mirror.strip_records_and_declare(mirror)
            self.assertEqual(removed, [])
            self.assertTrue(rewritten, "the declaration was left as the stub")
            self.assertFalse(hasattr(cut_mirror, "refresh_cited_decisions"))

    def test_the_staging_backstop_catches_a_glob_match(self) -> None:
        # The GLOB branch, which the exact-match test never reaches. Uses a
        # two-wildcard pattern so a hand-rolled prefix/suffix split would
        # under-match and this test would go red.
        staged_like = ".keel/plans/keel-plan-abc12345.md"
        self.assertTrue(
            fnmatch_ok(staged_like, ".keel/plans/keel-plan-*.md"),
            "the shipped pattern does not match a real ledger name",
        )
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            work = base / "work"
            work.mkdir()
            cut_mirror.cut(private, mirror, tip, work)
            # Written AFTER the cut on purpose: the cut now removes session
            # ledgers from the tree, so a ledger seeded beforehand would be
            # gone and this test would pass vacuously. The backstop exists for
            # exactly this residual case — something puts a ledger in the index
            # after the exclusions have run.
            _write(mirror, ".keel/plans/keel-plan-abc12345.md", "ledger\n")
            _git(mirror, ["add", "-f", "--", ".keel/plans/keel-plan-abc12345.md"])
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.assert_nothing_forbidden_staged(mirror)
            self.assertIn("keel-plan-abc12345.md", str(caught.exception))

    def test_the_glob_backstop_survives_a_second_wildcard(self) -> None:
        # Pins the fnmatch implementation against a regression to
        # partition("*"), which handles exactly one wildcard.
        self.assertTrue(fnmatch_ok(".keel/plans/keel-plan-abc.md", ".keel/*/keel-plan-*.md"))

    def test_refuses_an_archive_member_escaping_the_export(self) -> None:
        # The unsafe-member refusal, exercised directly: git archive will not
        # produce such a member, so the guard is only reachable by calling it.
        for unsafe in ("/etc/passwd", "../outside.txt", "docs/../../outside.txt"):
            name = cut_mirror._archive_member_name(unsafe)
            escapes = name.startswith("/") or ".." in Path(name).parts
            self.assertTrue(escapes, f"{unsafe} was not recognised as unsafe")


def fnmatch_ok(path: str, pattern: str) -> bool:
    """Thin wrapper so the tests read as intent rather than as a call."""
    import fnmatch as _fnmatch

    return _fnmatch.fnmatch(path, pattern)


class TestCutEndToEnd(unittest.TestCase):
    """The whole assembly, against throwaway repositories."""

    def _cut(self, base: Path) -> tuple[Path, Path, dict]:
        private = base / "private"
        tip = _seed_private(private)
        mirror = base / "mirror"
        _seed_mirror(mirror)
        # A local record append: the cut must not publish it. NO session ledger
        # is seeded here any more — `guard()` now refuses a tree carrying one
        # rather than deleting it, so a ledger present at cut time would make
        # every test using this helper a refusal test instead.
        _write(mirror, ".keel/audit/keel-audit.jsonl", '{"local":"stray line"}\n')
        work = base / "work"
        work.mkdir()
        report = cut_mirror.cut(private, mirror, tip, work)
        return private, mirror, report

    def test_replaces_the_tree_and_publishes_no_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _private, mirror, report = self._cut(Path(tmp))
            self.assertFalse((mirror / "OLDFILE.txt").exists())
            self.assertFalse((mirror / "olddir").exists())
            self.assertTrue((mirror / "README.md").is_file())
            self.assertTrue((mirror / "docs/guide.md").is_file())
            for leaked in (
                ".keel/knowledge/a-lesson.md",
                ".keel/backlog.md",
                ".keel/plans/keel-plan-deadbeef.md",
            ):
                self.assertFalse(
                    (mirror / leaked).exists(),
                    f"the cut published a development record: {leaked}",
                )
            # AND THE DECISION RECORD GOES TOO, which is the 2026-09-01 reversal:
            # this assertion used to read `report["refreshed"] == [that path]`,
            # because the cut shipped it and rewrote it from the tip each time.
            self.assertFalse(
                (mirror / ".keel/decisions/2026-01-01-a-cited-decision.md").exists(),
                "a cut ships no records, and a decision record is a record",
            )
            self.assertIn(
                ".keel/decisions/2026-01-01-a-cited-decision.md",
                report["records_removed"],
            )
            # What survives under .keel/ is the declaration and the two empty
            # surfaces — asserted as a SET, so a record sneaking back in fails
            # here even if every named path above is still absent.
            survivors = sorted(
                p.relative_to(mirror).as_posix()
                for p in (mirror / ".keel").rglob("*")
                if p.is_file()
            )
            self.assertEqual(
                survivors,
                [
                    ".keel/audit/keel-audit.jsonl",
                    ".keel/published-cut.md",
                    ".keel/queue/keel-observations.jsonl",
                ],
                f"unexpected .keel/ content in a published cut: {survivors}",
            )
            self.assertTrue(report["declaration_rewritten"])

    def test_the_cut_ships_no_arming_file_and_a_current_template(self) -> None:
        # REPLACES three tests the 2026-08-31 ruling retired: the write-it-last
        # ordering spy, the interrupt-restores-it test, and the arming-file
        # byte-identity test. All three pinned `write_arming_file` and the
        # backup/restore path, which no longer exist — a cut never writes an
        # arming file, so there is no ordering to observe, no window in which
        # the tree is half-armed, and nothing to restore. What replaces them is
        # the property that now matters: nothing armed ships, and the thing an
        # adopter WILL arm from is current.
        with tempfile.TemporaryDirectory() as tmp:
            private, mirror, _report = self._cut(Path(tmp))
            self.assertFalse((mirror / cut_mirror.ARMING_FILE).exists())
            # The seeded stale arming file is gone, not merely overwritten.
            self.assertFalse(
                any(
                    p.name == "keel-policy.md"
                    for p in (mirror / ".keel").rglob("*")
                ),
                "something arming-file-shaped survived under the record prefix",
            )
            # Normalised on both sides, for the reason in `_eol_normalised`:
            # the shipped file comes through `git archive` (eol-converted) and
            # the expected text from `git show` (raw blob), and this fixture
            # deliberately ships no .gitattributes so those two differ.
            expected = _git(
                private, ["show", f"HEAD:{cut_mirror.POLICY_TEMPLATE}"]
            ).stdout.encode("utf-8")
            self.assertEqual(
                cut_mirror._eol_normalised(
                    (mirror / cut_mirror.POLICY_TEMPLATE).read_bytes()
                ),
                cut_mirror._eol_normalised(expected),
                "the adopter would arm from a template that is not the tip's",
            )

    def test_the_declaration_is_the_scripts_text_not_whatever_was_there(self) -> None:
        """REPLACES ``test_the_cited_decision_is_refreshed_not_left_stale``,
        which asserted that the shipped decision record was rewritten from the
        tip. No decision record ships now, so the staleness question moved to
        the one record-shaped file that DOES ship: the declaration.

        The script owns that text, so a mirror seeded with an older or emptier
        declaration cannot publish it — the previous wording promised that "all
        but the cited decisions" stayed private, which is exactly the kind of
        sentence that survives a ruling and misdescribes it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            _private, mirror, report = self._cut(Path(tmp))
            body = (mirror / cut_mirror.CUT_MARKER).read_text(encoding="utf-8")
            self.assertEqual(body, cut_mirror.CUT_DECLARATION)
            self.assertIn("no decision records", body)
            self.assertNotIn("cited decisions", body)
            self.assertTrue(report["declaration_rewritten"])
            # Idempotent: a second cut of the same tree reports no rewrite,
            # so "rewritten" stays a signal rather than a constant.
            again, rewritten_again = cut_mirror.strip_records_and_declare(mirror)
            self.assertEqual(again, [])
            self.assertFalse(rewritten_again)

    def test_neither_record_surface_nor_a_ledger_is_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _private, mirror, _report = self._cut(Path(tmp))
            staged = [
                line.strip()
                for line in _git(
                    mirror, ["diff", "--cached", "--name-only"]
                ).stdout.splitlines()
                if line.strip()
            ]
            self.assertIn("README.md", staged)
            for forbidden in (
                ".keel/audit/keel-audit.jsonl",
                ".keel/queue/keel-observations.jsonl",
            ):
                self.assertNotIn(forbidden, staged)
            # The ledger exclusion cannot be exercised through a normal cut any
            # more — `guard()` refuses a tree carrying one — so what is pinned
            # here is that the pathspec is still DECLARED. It remains
            # defence-in-depth for a ledger appearing between guard and stage,
            # and `test_the_staging_backstop_catches_a_glob_match` exercises the
            # backstop behind it.
            self.assertIn(
                ":(exclude).keel/plans/keel-plan-*.md", _report["excludes"]
            )
            # The local append is still on disk: excluded from STAGING, never
            # reverted. Reverting it is the user's call, not this script's.
            self.assertIn(
                "stray line",
                (mirror / ".keel/audit/keel-audit.jsonl").read_text(encoding="utf-8"),
            )

    def test_nothing_is_committed_or_pushed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _private, mirror, _report = self._cut(Path(tmp))
            count = _git(mirror, ["rev-list", "--count", "HEAD"]).stdout.strip()
            self.assertEqual(count, "1", "the cut created a commit of its own")
            self.assertEqual(_git(mirror, ["remote"]).stdout.strip(), "")

    def test_the_staging_backstop_catches_a_forbidden_path(self) -> None:
        # Prove the guard's own guard: stage a forbidden path deliberately and
        # confirm the assertion refuses, so a silently-broken exclusion
        # pathspec cannot publish what it exists to withhold.
        with tempfile.TemporaryDirectory() as tmp:
            _private, mirror, _report = self._cut(Path(tmp))
            _git(mirror, ["add", "-f", "--", ".keel/audit/keel-audit.jsonl"])
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.assert_nothing_forbidden_staged(mirror)
            self.assertIn("keel-audit.jsonl", str(caught.exception))

    def test_a_record_the_tip_does_not_have_is_removed_rather_than_refused(
        self,
    ) -> None:
        """REPLACES the retired-decision refusal, and inverts it deliberately.

        The old behaviour: a mirror tracking a decision record absent from the
        tip was a CutError, because the cut shipped those records and publishing
        a retired ruling — or silently dropping a cited one — was worse than no
        cut at all. Under the 2026-09-01 ruling no record ships, so the question
        the refusal answered no longer exists: whether the tip still has it is
        irrelevant to a file that is being removed either way.

        Two earlier halves of this test are also gone, and for the record: it
        once asserted the arming file was restored after a failed cut, which the
        2026-08-31 disarm ruling retired.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, ".keel/decisions/2026-01-02-retired.md", "retired\n")
            _commit_all(mirror, "track a decision the tip does not have")
            work = base / "work"
            work.mkdir()
            report = cut_mirror.cut(private, mirror, tip, work)
            self.assertIn(
                ".keel/decisions/2026-01-02-retired.md", report["records_removed"]
            )
            self.assertFalse((mirror / ".keel/decisions/2026-01-02-retired.md").exists())

    def test_the_records_backstop_catches_one_the_strip_step_never_saw(self) -> None:
        """The backstop's own test: a record that reaches the INDEX by a route
        the assembly never took — a session writing into the mirror between
        assembly and commit — is refused at staging even though the strip step
        already ran and found nothing to remove."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            private = base / "private"
            _tip = _seed_private(private)
            mirror = base / "mirror"
            _seed_mirror(mirror)
            _write(mirror, ".keel/knowledge/slipped-in-late.md", "a lesson\n")
            _git(mirror, ["add", "-A"])
            with self.assertRaises(cut_mirror.CutError) as caught:
                cut_mirror.assert_only_declared_records_staged(mirror)
            self.assertIn("slipped-in-late.md", str(caught.exception))
            self.assertIn("ships no records", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
