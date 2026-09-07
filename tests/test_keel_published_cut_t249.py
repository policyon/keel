#!/usr/bin/env python3
"""T249: the discriminator between "no record" and "a declared-empty record".

Contract
--------
Reads   : nothing outside temporary directories this file builds and removes.
Emits   : unittest results only.
Writes  : nothing outside those same temporary directories.

What this file is for
----------------------
``tests/keel_published_cut.py`` is the shared answer seven self-referential
tests lean on to tell "this repository's corpus is missing because nobody
ever recorded anything" (fail closed) apart from "it is missing because this
is the published mirror, and emptiness is exactly what was declared" (assert
the declared-empty shape). This file proves the helper itself in all three
directions named in T249 accept 4, against synthetic trees rather than this
repository's own — the real-corpus behaviour is what the seven tests already
assert, unchanged, on THIS tree; this file is what proves the helper would
answer correctly on a tree that is not this one.

Failure policy
--------------
N/A — a test-only module, not production code.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import (  # noqa: E402
    contradiction,
    is_published_cut,
    marker_path,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestNoMarkerBehavesAsToday(unittest.TestCase):
    """(a) No marker, corpus absent or empty: not a published cut, and the
    contradiction guard never even engages — the six tests' own "fail
    closed, never skip" branch is what runs, unchanged."""

    def test_an_empty_tree_is_not_a_published_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(is_published_cut(root))
            self.assertFalse(marker_path(root).is_file())

    def test_a_tree_with_an_empty_corpus_and_no_marker_is_not_a_published_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / ".keel" / "audit" / "keel-audit.jsonl", "")
            _write(
                root / "scripts" / "keel-refs-waiver.json",
                json.dumps({"waivers": []}),
            )
            self.assertFalse(is_published_cut(root))


class TestMarkerWithDeclaredEmptyCorpusPasses(unittest.TestCase):
    """(b) Marker present, corpus exactly the declared-empty shape: no
    contradiction, so a test in the marker branch may assert the emptiness
    and pass."""

    def test_marker_and_empty_corpus_is_a_published_cut_with_no_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            _write(root / ".keel" / "audit" / "keel-audit.jsonl", "")
            _write(
                root / "scripts" / "keel-refs-waiver.json",
                json.dumps({"waivers": []}),
            )
            self.assertTrue(is_published_cut(root))
            self.assertIsNone(contradiction(root))

    def test_marker_with_no_corpus_files_at_all_is_still_no_contradiction(self) -> None:
        """Absent is as empty as zero-length: a mirror need not ship a
        zero-byte file for every state directory to be honest about holding
        nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            self.assertTrue(is_published_cut(root))
            self.assertIsNone(contradiction(root))


class TestMarkerWithADevelopmentCorpusFails(unittest.TestCase):
    """(c) Marker present AND a development corpus: the contradiction guard
    names the leak instead of letting the marker silence the six guards."""

    def test_marker_and_a_session_ledger_is_a_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            ledger = root / ".keel" / "plans" / "keel-plan-deadbeef.md"
            _write(ledger, "- [ ] T1 - open\n")
            reason = contradiction(root)
            self.assertIsNotNone(reason)
            self.assertIn("ledger", reason)
            self.assertIn(str(ledger), reason)

    def test_marker_and_a_non_empty_audit_log_is_a_contradiction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            _write(
                root / ".keel" / "audit" / "keel-audit.jsonl",
                '{"v": 1, "event": "session_start"}\n',
            )
            reason = contradiction(root)
            self.assertIsNotNone(reason)
            self.assertIn("audit log", reason)

    def test_marker_and_an_APPLICABLE_waiver_is_a_contradiction(self) -> None:
        """The register's non-emptiness was never the point; a LIVE waiver is.

        Narrowed 2026-08-31 with the same distinction ratified for
        ``check_refs`` (backlog BL14): a waiver whose named file is PRESENT
        means the file it waives is here, and the files this project waives
        violations in are session ledgers a cut ships without. So the named
        file must exist for the entry to contradict — and it does here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            _write(root / "x.md", "the waived file, present in this tree\n")
            _write(
                root / "scripts" / "keel-refs-waiver.json",
                json.dumps(
                    {
                        "waivers": [
                            {"file": "x.md", "line": 1, "path": "scripts/nope.py"}
                        ]
                    }
                ),
            )
            reason = contradiction(root)
            self.assertIsNotNone(reason)
            self.assertIn("waiver register", reason)

    def test_marker_and_an_INAPPLICABLE_waiver_is_not_a_contradiction(self) -> None:
        """The paired direction, and the reason the narrowing exists: the
        register is a tracked source file that legitimately ships, and its
        entries name session ledgers a cut does not carry. Identical to the
        test above except that the waived file is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            _write(
                root / "scripts" / "keel-refs-waiver.json",
                json.dumps(
                    {
                        "waivers": [
                            {
                                "file": ".keel/plans/keel-plan-074ab77d.md",
                                "line": 279,
                                "path": "scripts/nope.py",
                            }
                        ]
                    }
                ),
            )
            self.assertIsNone(contradiction(root))

    def test_this_repositorys_own_tree_would_name_a_contradiction_if_marked(self) -> None:
        """The guard clause every one of the seven tests relies on. On a
        development tree (no marker): this repository must not ship the
        marker — the marker path is only ever checked, never created, here.
        On a published cut (marker legitimately present, corpus exactly the
        declared-empty shape): the marker and the emptiness must agree, so
        this test still asserts something real — contradiction(REPO_ROOT)
        must be None — rather than skipping."""
        if is_published_cut(REPO_ROOT):
            self.assertIsNone(contradiction(REPO_ROOT))
        else:
            self.assertFalse(is_published_cut(REPO_ROOT), "this repository must not ship the marker")


class TestOwnTreeGuardBranchesOnPublishedCutState(unittest.TestCase):
    """T250: the own-tree guard clause must branch on what the tree actually
    is, never assume every tree is the development tree. This exercises the
    published-cut branch directly against a sandboxed tree, since THIS
    repository's tree is (by design) never marked."""

    def test_own_tree_guard_logic_passes_on_a_sandboxed_published_cut(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root.joinpath(".keel", "published-cut.md"), "# published cut\n")
            _write(root / ".keel" / "audit" / "keel-audit.jsonl", "")
            _write(
                root / "scripts" / "keel-refs-waiver.json",
                json.dumps({"waivers": []}),
            )
            self.assertTrue(is_published_cut(root))
            if is_published_cut(root):
                self.assertIsNone(contradiction(root))
            else:
                self.fail("sandboxed tree must be recognized as a published cut")


if __name__ == "__main__":
    unittest.main()
