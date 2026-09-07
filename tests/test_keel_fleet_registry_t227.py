#!/usr/bin/env python3
"""T227 - the fleet registry feeds the board's own sibling selector.

Contract
--------
Reads   : ``hooks/keel_registry.py`` (write/read/seed), ``hooks/keel_session.py``
          (``registry_write``, and ``run`` end to end via the real subprocess
          launcher for the never-affects-outcome guarantee), and
          ``scripts/keel_orchestration_dashboard.py`` (``read_siblings``).
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          registry write in this file is pointed at a fixture ``home``
          directory via the ``home=`` seam ``keel_registry`` and
          ``keel_faultlog`` already offer - the SAME sandboxing principle
          ``tests/test_keel_crash_deny_t236.py`` uses via environment
          variables, applied here through the parameter seam instead, since
          every function under test already accepts one. The one case that
          needs the real launcher (the never-affects-outcome proof) sandboxes
          ``HOME``/``USERPROFILE`` for that subprocess exactly as T236 does.

Failure policy
--------------
FAIL-CLOSED, as every test module is: a case that cannot establish its
premise fails.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every file operation names its
encoding (convention 6).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import keel_orchestration_dashboard as board  # noqa: E402
import keel_registry  # noqa: E402
import keel_session  # noqa: E402


def _arm(project: Path) -> None:
    """Give ``project`` the arming file that makes it keel-adopted."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\nname: keel-policy\n---\n", encoding="utf-8"
    )


class TestRegistryWriteAdoptionGate(unittest.TestCase):
    """T227 accept 1: written only for adopted projects, never for unadopted."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)

    def test_write_for_adopted_project_creates_registry_with_its_path(self) -> None:
        project = self.root / "adopted"
        _arm(project)
        stats = keel_registry.write(project, home=self.home)
        self.assertTrue(stats["written"])
        self.assertEqual(stats["total"], 1)
        registry_file = keel_registry.registry_path(home=self.home)
        self.assertTrue(registry_file.is_file())
        entries = keel_registry.read(home=self.home)
        self.assertEqual([p.resolve() for p in entries], [project.resolve()])

    def test_write_for_unadopted_project_writes_nothing(self) -> None:
        project = self.root / "not-adopted"
        project.mkdir()
        stats = keel_registry.write(project, home=self.home)
        self.assertFalse(stats["written"])
        registry_file = keel_registry.registry_path(home=self.home)
        self.assertFalse(registry_file.is_file())

    def test_write_for_unadopted_project_does_not_disturb_an_existing_registry(self) -> None:
        adopted = self.root / "adopted"
        _arm(adopted)
        keel_registry.write(adopted, home=self.home)
        before = keel_registry.registry_path(home=self.home).read_text(encoding="utf-8")

        unadopted = self.root / "not-adopted"
        unadopted.mkdir()
        keel_registry.write(unadopted, home=self.home)

        after = keel_registry.registry_path(home=self.home).read_text(encoding="utf-8")
        self.assertEqual(before, after)


class TestRegistryPruning(unittest.TestCase):
    """T227 accept 1: prunes entries whose paths no longer exist, saying so."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)

    def test_a_vanished_entry_is_pruned_and_reported_on_stderr(self) -> None:
        gone = self.root / "gone"
        _arm(gone)
        keel_registry.write(gone, home=self.home)
        shutil.rmtree(gone)

        survivor = self.root / "survivor"
        _arm(survivor)
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            stats = keel_registry.write(survivor, home=self.home)

        self.assertEqual(stats["pruned"], 1)
        self.assertIn("pruned 1", buffer.getvalue())
        self.assertIn("no longer on disk", buffer.getvalue())
        entries = [p.resolve() for p in keel_registry.read(home=self.home)]
        self.assertEqual(entries, [survivor.resolve()])
        self.assertNotIn(gone.resolve(), entries)

    def test_a_clean_write_reports_nothing_on_stderr(self) -> None:
        project = self.root / "adopted"
        _arm(project)
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            keel_registry.write(project, home=self.home)
        self.assertEqual(buffer.getvalue(), "")


class TestPredecessorSeed(unittest.TestCase):
    """T227 accept: the seed imports only keel-adopted survivors, idempotently."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)

    def test_seed_keeps_only_existing_keel_adopted_entries(self) -> None:
        keel_adopted = self.root / "keel-adopted"
        _arm(keel_adopted)

        exists_not_adopted = self.root / "exists-not-adopted"
        exists_not_adopted.mkdir()

        missing = self.root / "does-not-exist-at-all"

        (self.home / keel_registry.PREDECESSOR_SEED_NAME).write_text(
            f"{keel_adopted}\n{exists_not_adopted}\n{missing}\n\n",
            encoding="utf-8",
        )

        project = self.root / "this-session"
        _arm(project)
        stats = keel_registry.write(project, home=self.home)

        self.assertEqual(stats["seeded"], 1)
        entries = {p.resolve() for p in keel_registry.read(home=self.home)}
        self.assertIn(keel_adopted.resolve(), entries)
        self.assertIn(project.resolve(), entries)
        self.assertNotIn(exists_not_adopted.resolve(), entries)
        self.assertNotIn(missing.resolve(), entries)

    def test_seeding_twice_is_an_idempotent_union(self) -> None:
        keel_adopted = self.root / "keel-adopted"
        _arm(keel_adopted)
        (self.home / keel_registry.PREDECESSOR_SEED_NAME).write_text(
            f"{keel_adopted}\n", encoding="utf-8"
        )
        project = self.root / "this-session"
        _arm(project)

        first = keel_registry.write(project, home=self.home)
        second = keel_registry.write(project, home=self.home)

        self.assertEqual(first["total"], 2)
        self.assertEqual(second["total"], 2)
        self.assertEqual(second["seeded"], 0)  # already folded in; not re-counted


class TestBoardReadSiblings(unittest.TestCase):
    """T227 accept 2: the board selector lists the registered siblings."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_read_siblings_excludes_self_and_lists_the_others(self) -> None:
        me = self.root / "me"
        me.mkdir()
        other = self.root / "other"
        other.mkdir()
        with mock.patch.object(keel_registry, "read", return_value=[me, other]):
            siblings = board.read_siblings(me)
        self.assertEqual(len(siblings), 1)
        self.assertEqual(Path(siblings[0]["path"]).resolve(), other.resolve())

    def test_read_siblings_is_empty_when_the_registry_has_only_self(self) -> None:
        me = self.root / "me"
        me.mkdir()
        with mock.patch.object(keel_registry, "read", return_value=[me]):
            siblings = board.read_siblings(me)
        self.assertEqual(siblings, [])

    def test_read_siblings_never_raises_when_the_registry_read_fails(self) -> None:
        me = self.root / "me"
        me.mkdir()
        with mock.patch.object(keel_registry, "read", side_effect=RuntimeError("boom")):
            siblings = board.read_siblings(me)
        self.assertEqual(siblings, [])


class TestRegistryLivesOutsideAnyProjectTree(unittest.TestCase):
    """T227's own constraint: the registry file never lands inside a project."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)

    def test_registry_path_is_never_under_the_written_project(self) -> None:
        project = self.root / "adopted"
        _arm(project)
        keel_registry.write(project, home=self.home)
        registry_file = keel_registry.registry_path(home=self.home).resolve()
        self.assertFalse(
            str(registry_file).startswith(str(project.resolve()) + os.sep)
        )
        self.assertTrue(
            str(registry_file).startswith(str(self.home.resolve()))
        )


class TestSessionRegistryNeverAffectsOutcome(unittest.TestCase):
    """The write is wrapped: it can never affect session start's outcome."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_raising_keel_registry_write_is_swallowed_by_registry_write(self) -> None:
        buffer = io.StringIO()
        with mock.patch.object(keel_registry, "write", side_effect=RuntimeError("boom")):
            with contextlib.redirect_stderr(buffer):
                keel_session.registry_write(self.root)  # must not raise
        self.assertIn("fleet registry not updated", buffer.getvalue())

    def test_live_session_start_still_exits_zero_and_injects_the_plan_line(self) -> None:
        """End-to-end through the real launcher (mirrors T236's own shape)."""
        project = self.root / "proj"
        _arm(project)
        home = self.root / "home"
        (home / ".claude").mkdir(parents=True)
        payload = {
            "hook_event_name": "SessionStart",
            "session_id": "abcdef1234567890",
            "cwd": str(project),
            "source": "startup",
        }
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["USERPROFILE"] = str(home)
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / "hooks" / "keel_hook.py"), "session"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=str(project),
            env=env,
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("YOUR session plan file is", proc.stdout)
        registry_file = home / ".claude" / "keel" / "keel-registry.json"
        self.assertTrue(registry_file.is_file())


if __name__ == "__main__":
    unittest.main()
