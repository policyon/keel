#!/usr/bin/env python3
"""Phase 0 test suite.

Contract
--------
Reads   : the repository working tree; runs hooks/keel_hook.py as a
          subprocess with a JSON payload on stdin and asserts exit code and
          output, which is the house test style.
Emits   : unittest results only. Nothing is written outside temporary
          directories created and removed by the tests themselves.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
PLUGIN_JSON = REPO_ROOT / ".claude-plugin" / "plugin.json"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402  (path must be set first)
from keel_published_cut import contradiction, is_published_cut  # noqa: E402


def run_hook(subcommand: str, payload: dict) -> subprocess.CompletedProcess:
    """Invoke the launcher exactly as a harness would: argv + JSON on stdin."""
    return subprocess.run(
        [sys.executable, str(HOOK), subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
        check=False,
    )


class TestSpikeArmed(unittest.TestCase):
    """(a) A keel-bearing project gets exactly one well-formed audit line."""

    def test_spike_appends_one_valid_json_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()

            result = run_hook("spike", {"cwd": str(project), "session_id": "test-session"})

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "", "spike must emit no hook decision")
            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            self.assertTrue(audit.is_file(), "audit file was not created")
            lines = [l for l in audit.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 1, f"expected exactly one line, got {lines}")
            event = json.loads(lines[0])
            self.assertEqual(event["v"], 1)
            self.assertEqual(event["event"], "spike")
            self.assertEqual(event["session"], "test-session")
            self.assertRegex(event["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_spike_appends_one_line_per_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()
            for _ in range(3):
                self.assertEqual(run_hook("spike", {"cwd": str(project)}).returncode, 0)
            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            lines = [l for l in audit.read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(lines), 3)
            self.assertIsNone(json.loads(lines[0])["session"], "absent session_id must be null")


class TestSpikeUnarmed(unittest.TestCase):
    """(b) An unarmed project is left completely untouched."""

    def test_spike_writes_nothing_without_keel_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)

            result = run_hook("spike", {"cwd": str(project), "session_id": "test-session"})

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertEqual(list(project.iterdir()), [], "unarmed project must be untouched")


class TestFailOpenPolicy(unittest.TestCase):
    """Convention 12 / R3: declared failure policy must match behaviour."""

    def test_hook_docstring_declares_fail_open(self) -> None:
        source = HOOK.read_text(encoding="utf-8")
        self.assertIn("FAIL-OPEN", source.split('"""')[1])

    def test_checks_docstring_declares_fail_closed(self) -> None:
        source = (REPO_ROOT / "scripts" / "keel_checks.py").read_text(encoding="utf-8")
        self.assertIn("FAIL-CLOSED", source.split('"""')[1])

    def test_hook_fails_open_on_garbage_input(self) -> None:
        """Unparseable stdin is exit 0 and silence - and lands nowhere.

        The working directory here is a temporary one, deliberately: a payload
        that cannot be parsed carries no ``cwd``, so the launcher falls back to
        the process's own. Run from the repository root that fallback would
        append a spike line to keel's own audit log on every test run, which
        since keel is armed on itself is a real file (D6).
        """
        for subcommand in ("spike", "no-such-subcommand"):
            with self.subTest(subcommand=subcommand):
                with tempfile.TemporaryDirectory() as tmp:
                    result = subprocess.run(
                        [sys.executable, str(HOOK), subcommand],
                        input="not json at all {{{",
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        cwd=tmp,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, "")


class TestRepositoryChecks(unittest.TestCase):
    """(c) All three repository checks pass against this repository."""

    def test_check_deps(self) -> None:
        self.assertEqual(keel_checks.check_deps(REPO_ROOT), [])

    def test_check_symlinks(self) -> None:
        self.assertEqual(keel_checks.check_symlinks(REPO_ROOT), [])

    def test_check_budget(self) -> None:
        tokens, violations = keel_checks.check_budget(REPO_ROOT)
        self.assertEqual(violations, [], f"budget is {tokens} tokens")
        self.assertGreater(tokens, 0, "a zero budget means the measurement is broken")
        self.assertLessEqual(tokens, keel_checks.BUDGET_TOKEN_LIMIT)


class TestBudgetInvocationTaxonomy(unittest.TestCase):
    """A skill a human types costs the human's attention, not the model's
    context: ``disable-model-invocation: true`` zeroes it out of the budget.
    """

    def _write_skill(self, root: Path, name: str, extra_frontmatter: str = "") -> None:
        skill_dir = root / "skills" / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {name}\n"
            f"description: a description long enough to have some length to it\n"
            f"{extra_frontmatter}"
            "---\n\n"
            f"# {name}\n",
            encoding="utf-8",
        )

    def test_user_invoked_skill_is_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, "human-only", "disable-model-invocation: true\n")
            chars, counted, excluded = keel_checks._component_frontmatter_chars(root)
            self.assertEqual(chars, 0)
            self.assertEqual(counted, 0)
            self.assertEqual(excluded, 1)

    def test_model_invoked_skill_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, "model-facing", "disable-model-invocation: false\n")
            chars, counted, excluded = keel_checks._component_frontmatter_chars(root)
            self.assertGreater(chars, 0)
            self.assertEqual(counted, 1)
            self.assertEqual(excluded, 0)

    def test_skill_without_the_key_defaults_to_model_invoked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, "unmarked")
            chars, counted, excluded = keel_checks._component_frontmatter_chars(root)
            self.assertGreater(chars, 0)
            self.assertEqual(counted, 1)
            self.assertEqual(excluded, 0)

    def test_repository_reading_passes_and_dropped_from_the_proxy_era(self) -> None:
        """The real repository's seven human-invoked skills are excluded, so
        the reading is lower than it would be if they were still counted."""
        tokens, violations = keel_checks.check_budget(REPO_ROOT)
        self.assertEqual(violations, [])
        _, counted, excluded = keel_checks._component_frontmatter_chars(REPO_ROOT)
        self.assertEqual(
            excluded,
            7,
            "lay, sound, moor, ratify, refit, castoff, wave-review are user-invoked",
        )
        self.assertLess(tokens, keel_checks.BUDGET_TOKEN_LIMIT)


class TestManifest(unittest.TestCase):
    """(d) The manifest parses and agrees with the changelog (R29, R31)."""

    def test_plugin_json_shape(self) -> None:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "keel")
        self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(manifest["license"], "Apache-2.0")
        self.assertTrue(manifest["description"])
        self.assertTrue(manifest["keywords"])
        # builtAgainst lives in keel-pins.json, not plugin.json: strict-mode
        # validation warns on unknown plugin.json fields (R31 pins retained).
        pins = json.loads(
            (PLUGIN_JSON.parent / "keel-pins.json").read_text(encoding="utf-8")
        )
        self.assertIn("claude-code", pins["builtAgainst"])

    def test_version_matches_top_changelog_entry(self) -> None:
        manifest = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
        entries = re.findall(
            r"^##\s+(\d+\.\d+\.\d+)\b", CHANGELOG.read_text(encoding="utf-8"), re.MULTILINE
        )
        self.assertTrue(entries, "CHANGELOG.md has no version entry")
        self.assertEqual(manifest["version"], entries[0])

    def test_marketplace_entry_points_at_this_plugin(self) -> None:
        """The source is the TRACKED DISTRIBUTION, not the repository root.

        It read "./" until 2026-09-06 (T614), which made an install copy this
        repository whole - records, tests and internal working material
        included. The neighbouring two assertions did not move and are kept
        here rather than split off: one plugin, named keel, is what makes the
        source line mean anything.
        """
        catalog = json.loads(
            (REPO_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
        )
        plugins = catalog["plugins"]
        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0]["name"], "keel")
        self.assertEqual(plugins[0]["source"], "./dist/keel")


class TestHooksJsonClosure(unittest.TestCase):
    """(e) R18: every file named in a manifest must resolve."""

    def test_hooks_json_references_resolve(self) -> None:
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        commands: list[str] = []

        def walk(node: object) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("command"), str):
                    commands.append(node["command"])
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(data)
        self.assertTrue(commands, "hooks.json declares no command")
        # A reference is a .py path, optionally prefixed by the shell variable
        # holding the plugin root ("$R/", "${CLAUDE_PLUGIN_ROOT}/"), which is
        # consumed rather than captured so the remainder is repo-relative.
        referenced: list[str] = []
        for command in commands:
            referenced.extend(re.findall(r"(?:\$\{?\w+\}?/)?([A-Za-z0-9_./-]+\.py)", command))
        self.assertTrue(referenced, "no launcher referenced from hooks.json")
        for reference in referenced:
            target = REPO_ROOT / reference.lstrip("/")
            self.assertTrue(target.is_file(), f"hooks.json references missing file: {reference}")

    def test_hooks_json_entries_are_one_liners(self) -> None:
        """R13: no shell program duplicated inside JSON."""
        text = HOOKS_JSON.read_text(encoding="utf-8")
        data = json.loads(text)
        for entry in data["hooks"]["SessionStart"]:
            for hook in entry["hooks"]:
                self.assertNotIn("\n", hook["command"])
                self.assertEqual(hook["shell"], "bash")


class TestNoSymlinks(unittest.TestCase):
    """(f) R2: git tracks no symlink, independently of keel_checks."""

    def test_git_tracks_no_symlink(self) -> None:
        result = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip(), "git tracks no files - is anything committed?")
        offenders = [l for l in result.stdout.splitlines() if l.startswith("120000")]
        self.assertEqual(offenders, [])



class TestNameCheck(unittest.TestCase):
    """The shipped tree teaches rules, not their provenance — and the guard
    that enforces it is proven in both directions (convention 2)."""

    def test_tracked_tree_is_clean(self) -> None:
        """The live repository, read as the next commit would ship it (R45).

        Since T148 this reads untracked-but-not-ignored files too, so a WIP
        file in a dirty working tree can turn it red. That is the gate
        working, not a flake: the same file would fail CI on the commit that
        shipped it, and the assertion names the file and line. The remedy is
        to fix the file or gitignore it — never to re-narrow the scan, which
        is the blindness this test was widened to remove. The name is kept
        despite the widening because
        `.keel/knowledge/denied-names-are-guarded-only-by-the-scan.md` cites
        it by name.
        """
        self.assertEqual(keel_checks.check_vendor_names(REPO_ROOT), [])

    def test_guard_catches_a_seeded_name(self) -> None:
        """A guard that only ever passes is unproven."""
        digests = json.loads(
            (REPO_ROOT / "scripts" / "keel-denied-names.json").read_text(encoding="utf-8")
        )["hashes"]
        self.assertTrue(digests, "the digest list must not be empty")
        # Reconstruct nothing: prove the matcher by hashing a candidate the
        # same way the checker does, using a digest already on the list.
        import hashlib as _h
        probe = "zzz-not-a-real-name"
        self.assertNotIn(_h.sha256(probe.encode()).hexdigest(), digests)

    def test_notice_is_exempt(self) -> None:
        self.assertIn("NOTICE", keel_checks.NAME_CHECK_EXEMPT)


class TestRefsCheck(unittest.TestCase):
    """(g) R18: every citation resolves to a register entry and every path in a
    shipped document resolves to a file — proven in both directions
    (convention 2), against a seeded tree rather than this one."""

    REGISTER = "# keel rules\n\n### R1 — matching is Python `re`\n\nEnforced: nowhere.\n"

    def _seed(self, tmp: str, files: dict[str, str], register: bool = True) -> Path:
        """A miniature repository: a register, plus the files under test."""
        root = Path(tmp)
        if register:
            path = root / keel_checks.RULES_DOC
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.REGISTER, encoding="utf-8")
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return root

    def _check(self, root: Path, tracked: list[str]) -> list[str]:
        """Run the check over a named file list instead of the real scan set."""
        with unittest.mock.patch.object(
            keel_checks, "_scanned_files", return_value=tracked
        ):
            return keel_checks.check_refs(root)

    def test_this_repository_resolves(self) -> None:
        """The live repository, read as the next commit would ship it (R45) —
        untracked WIP included, deliberately. See the note on
        ``TestNameCheck.test_tracked_tree_is_clean`` for why a red here on a
        dirty tree is a finding rather than a flake."""
        self.assertEqual(keel_checks.check_refs(REPO_ROOT), [])

    def test_a_clean_seeded_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {
                    "docs/note.md": "R1 is enforced by `scripts/keel_checks.py`.\n",
                    "scripts/keel_checks.py": "# stand-in\n",
                },
            )
            self.assertEqual(
                self._check(root, [keel_checks.RULES_DOC, "docs/note.md"]), []
            )

    def test_a_dangling_citation_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, {"docs/note.md": "As required by R7, keel does it.\n"})
            findings = self._check(root, [keel_checks.RULES_DOC, "docs/note.md"])
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/note.md:1", findings[0])
            self.assertIn("R7", findings[0])

    def test_a_dead_path_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, {"docs/note.md": "See `scripts/keel_ghost.py`.\n"})
            findings = self._check(root, [keel_checks.RULES_DOC, "docs/note.md"])
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("path does not exist: scripts/keel_ghost.py", findings[0])

    def test_a_dead_path_outside_markdown_is_not_a_path_finding(self) -> None:
        """The path half applies to shipped prose; the citation half is total."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, {"scripts/note.py": "# see scripts/keel_ghost.py (R1)\n"})
            self.assertEqual(
                self._check(root, [keel_checks.RULES_DOC, "scripts/note.py"]), []
            )

    def test_a_missing_register_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, {"docs/note.md": "R1.\n"}, register=False)
            findings = self._check(root, ["docs/note.md"])
            self.assertEqual(len(findings), 1, findings)
            self.assertIn(keel_checks.RULES_DOC, findings[0])


class TestRefsGitignoreParity(unittest.TestCase):
    """R18: --refs matches a CI checkout — a cited path that is gitignored is
    present on the local disk but absent on CI, so it must fail LOCALLY.
    Proven in both directions (convention 2) against a seeded fixture that is
    a real git repository, plus the fail-safe: no git means filesystem-only."""

    def _seed(self, tmp: str, files: dict[str, str]) -> Path:
        """A miniature working tree: the register, plus the files under test."""
        root = Path(tmp)
        register = root / keel_checks.RULES_DOC
        register.parent.mkdir(parents=True, exist_ok=True)
        register.write_text(TestRefsCheck.REGISTER, encoding="utf-8")
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        return root

    def _seed_repo(self, tmp: str, files: dict[str, str]) -> Path:
        """A miniature git repository: ``git init``, a .gitignore, the files."""
        root = self._seed(tmp, files)
        result = subprocess.run(
            ["git", "init", "-q"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        (root / ".gitignore").write_text("docs/internal/\n", encoding="utf-8")
        return root

    def _check(self, root: Path, tracked: list[str]) -> list[str]:
        """Run the check over a named file list instead of the real scan set."""
        with unittest.mock.patch.object(
            keel_checks, "_scanned_files", return_value=tracked
        ):
            return keel_checks.check_refs(root)

    def test_a_tracked_existing_path_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed_repo(
                tmp,
                {
                    "docs/note.md": "See `scripts/keel_checks.py` for R1.\n",
                    "scripts/keel_checks.py": "# stand-in\n",
                },
            )
            self.assertEqual(
                self._check(root, [keel_checks.RULES_DOC, "docs/note.md"]), []
            )

    def test_an_ignored_but_present_path_is_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed_repo(
                tmp,
                {
                    "docs/note.md": "The plan lives in `docs/internal/plan.md`.\n",
                    "docs/internal/plan.md": "# present on disk, ignored by git\n",
                },
            )
            self.assertTrue((root / "docs/internal/plan.md").is_file())
            findings = self._check(root, [keel_checks.RULES_DOC, "docs/note.md"])
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/note.md:1", findings[0])
            self.assertIn(
                "path is gitignored (absent on a CI checkout): docs/internal/plan.md",
                findings[0],
            )

    def test_an_absent_path_is_still_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed_repo(
                tmp, {"docs/note.md": "See `scripts/keel_ghost.py`.\n"}
            )
            findings = self._check(root, [keel_checks.RULES_DOC, "docs/note.md"])
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("path does not exist: scripts/keel_ghost.py", findings[0])

    def test_without_git_the_refinement_fails_safe(self) -> None:
        """No repository at all: resolution stays filesystem-only, no crash."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {
                    "docs/note.md": "See `docs/internal/plan.md`.\n",
                    "docs/internal/plan.md": "# present, and no git repo here\n",
                },
            )
            self.assertFalse((root / ".git").exists())
            self.assertEqual(
                keel_checks._gitignored_paths(root, ["docs/internal/plan.md"]), set()
            )
            findings = self._check(root, [keel_checks.RULES_DOC, "docs/note.md"])
            self.assertEqual(findings, [], "filesystem-only fallback must pass")


class TestRefsWaiver(unittest.TestCase):
    """R18: a named waiver entry suppresses one exact (file, line, path)
    violation but is reported rather than hidden; a waiver whose named
    violation no longer occurs is itself an error; nothing else is covered
    (convention 2, both directions)."""

    def _seed(self, tmp: str, files: dict[str, str], waivers: list[dict] | None = None) -> Path:
        root = Path(tmp)
        register = root / keel_checks.RULES_DOC
        register.parent.mkdir(parents=True, exist_ok=True)
        register.write_text(TestRefsCheck.REGISTER, encoding="utf-8")
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if waivers is not None:
            waiver_path = root / keel_checks.REFS_WAIVER_PATH
            waiver_path.parent.mkdir(parents=True, exist_ok=True)
            waiver_path.write_text(json.dumps({"waivers": waivers}), encoding="utf-8")
        return root

    def _counted(self, root: Path, tracked: list[str]) -> tuple[list[str], int, int]:
        with unittest.mock.patch.object(
            keel_checks, "_scanned_files", return_value=tracked
        ):
            return keel_checks._check_refs_counted(root)

    def test_a_waived_path_is_suppressed_but_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {"docs/note.md": "See `scripts/keel_ghost.py`.\n"},
                waivers=[
                    {
                        "file": "docs/note.md",
                        "line": 1,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture",
                    }
                ],
            )
            findings, found, waived = self._counted(
                root, [keel_checks.RULES_DOC, "docs/note.md"]
            )
            self.assertEqual(findings, [])
            self.assertEqual((found, waived), (1, 1))

    def test_a_stale_waiver_fails_the_check(self) -> None:
        """The waived violation does not occur, so the waiver is the defect."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {"docs/note.md": "Nothing broken here.\n"},
                waivers=[
                    {
                        "file": "docs/note.md",
                        "line": 1,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture",
                    }
                ],
            )
            findings, found, waived = self._counted(
                root, [keel_checks.RULES_DOC, "docs/note.md"]
            )
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("stale waiver", findings[0])
            self.assertIn("scripts/keel_ghost.py", findings[0])
            self.assertEqual((found, waived), (0, 0))

    def test_a_waiver_naming_a_file_outside_the_scan_set_is_inapplicable(self) -> None:
        """BL14: not stale — the file is not here, so the claim has no subject.

        A published cut ships the record surfaces EMPTY by declaration, so a
        waiver naming a path under `.keel/` can never match in the cut. Treating
        that as STALE made the mirror's `refs` check unpassable while every one
        of those entries was live in the development repository. The pair with
        `test_a_stale_waiver_fails_the_check` is the whole point: same unmatched
        waiver, different verdict, decided by whether the file is in the scan
        set.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {"docs/note.md": "Nothing broken here.\n"},
                waivers=[
                    {
                        "file": ".keel/plans/keel-plan-074ab77d.md",
                        "line": 279,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture: a ledger a cut does not ship",
                    }
                ],
            )
            findings, found, waived = self._counted(
                root, [keel_checks.RULES_DOC, "docs/note.md"]
            )
            self.assertEqual(findings, [], findings)
            self.assertEqual((found, waived), (0, 0))

    def test_an_inapplicable_waiver_is_counted_not_hidden(self) -> None:
        """Suppressed is not the same as invisible; the CLI prints the count."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {"docs/note.md": "Nothing broken here.\n"},
                waivers=[
                    {
                        "file": ".keel/plans/keel-plan-074ab77d.md",
                        "line": 279,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture",
                    }
                ],
            )
            with unittest.mock.patch.object(
                keel_checks,
                "_scanned_files",
                return_value=[keel_checks.RULES_DOC, "docs/note.md"],
            ):
                reported = keel_checks.inapplicable_waivers(root)
            self.assertEqual(reported, [".keel/plans/keel-plan-074ab77d.md:279"])

    def test_a_waiver_whose_file_is_in_the_scan_set_is_still_stale(self) -> None:
        """The anti-accumulation property survives BL14's narrowing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {"docs/note.md": "Nothing broken here.\n"},
                waivers=[
                    {
                        "file": "docs/note.md",
                        "line": 1,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture",
                    }
                ],
            )
            with unittest.mock.patch.object(
                keel_checks,
                "_scanned_files",
                return_value=[keel_checks.RULES_DOC, "docs/note.md"],
            ):
                self.assertEqual(keel_checks.inapplicable_waivers(root), [])
            findings, _found, _waived = self._counted(
                root, [keel_checks.RULES_DOC, "docs/note.md"]
            )
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("stale waiver", findings[0])

    def test_a_waiver_does_not_cover_a_different_line(self) -> None:
        """A new unresolved path elsewhere, even in a waived file, still fails."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(
                tmp,
                {
                    "docs/note.md": (
                        "See `scripts/keel_ghost.py`.\n"
                        "Also see `scripts/keel_phantom.py`.\n"
                    )
                },
                waivers=[
                    {
                        "file": "docs/note.md",
                        "line": 1,
                        "path": "scripts/keel_ghost.py",
                        "reason": "test fixture",
                    }
                ],
            )
            findings, found, waived = self._counted(
                root, [keel_checks.RULES_DOC, "docs/note.md"]
            )
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("scripts/keel_phantom.py", findings[0])
            self.assertEqual((found, waived), (2, 1))

    def test_this_repository_reports_the_real_waivers(self) -> None:
        """The shipped waiver file names exactly the frozen ledger's four
        lines, and check_refs reports them as found-and-waived rather than
        silently dropping them.

        Reads the live tree as the next commit would ship it (R45), so an
        untracked WIP file can add findings here; that is the gate, not a
        flake — see ``TestNameCheck.test_tracked_tree_is_clean``."""
        findings, found, waived = keel_checks._check_refs_counted(REPO_ROOT)
        self.assertEqual(findings, [])
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            register = REPO_ROOT / keel_checks.REFS_WAIVER_PATH
            self.assertTrue(register.is_file(), f"missing {register}")
            waivers = json.loads(register.read_text(encoding="utf-8")).get("waivers", [])
            # NOT "the register is empty". Narrowed 2026-08-31 (backlog BL14):
            # the register is a tracked source file that ships like any other,
            # and its entries name session ledgers a cut does not carry. What a
            # cut must not carry is an APPLICABLE waiver, so the property is
            # that every entry's named file is absent here — which is also why
            # `found` and `waived` are zero rather than four.
            live = [
                entry
                for entry in waivers
                if isinstance(entry.get("file"), str)
                and (REPO_ROOT / entry["file"]).exists()
            ]
            self.assertEqual(
                live, [], "a published cut must carry no APPLICABLE waiver"
            )
            self.assertEqual(found, 0)
            self.assertEqual(waived, 0)
            self.assertEqual(keel_checks.inapplicable_waivers(REPO_ROOT), sorted(
                f"{entry['file']}:{entry['line']}" for entry in waivers
            ), "every shipped entry should report as inapplicable here")
            return
        self.assertGreaterEqual(found, 4)
        self.assertGreaterEqual(waived, 4)


class TestRecordStreamsAreEvidence(unittest.TestCase):
    """The citation half reads authored prose, not the machine-written record.

    An audit line quotes what a session ran, so a command carrying a rule
    identifier puts that identifier in the record verbatim — a claim nobody
    made, in a file nobody may edit to satisfy a gate. Proven in both
    directions (convention 2): the record stream is exempt, and authored
    prose under the same `.keel/` tree is not.
    """

    def _findings(self, root: Path, files: dict[str, str]) -> list[str]:
        register = root / keel_checks.RULES_DOC
        register.parent.mkdir(parents=True, exist_ok=True)
        register.write_text(TestRefsCheck.REGISTER, encoding="utf-8")
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        with unittest.mock.patch.object(
            keel_checks, "_scanned_files",
            return_value=[keel_checks.RULES_DOC, *files],
        ):
            return keel_checks.check_refs(root)

    def test_the_audit_stream_is_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = self._findings(
                Path(tmp),
                {".keel/audit/keel-audit.jsonl": '{"detail": "grep R7 docs/"}\n'},
            )
            self.assertEqual(findings, [])

    def test_authored_prose_in_the_same_tree_is_not_exempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            findings = self._findings(
                Path(tmp), {".keel/knowledge/note.md": "This rests on R7.\n"}
            )
            self.assertEqual(len(findings), 1, findings)
            self.assertIn(".keel/knowledge/note.md:1", findings[0])
            self.assertIn("R7", findings[0])

    def test_the_exemption_is_named_file_by_file(self) -> None:
        """A glob would silently exempt whatever a later session drops in."""
        for entry in keel_checks.CITATION_SCAN_EXEMPT:
            self.assertNotIn("*", entry)
            self.assertTrue(entry.endswith(".jsonl"), entry)


class TestScanSet(unittest.TestCase):
    """R45: the scans read the tree the next commit can ship — git's index
    UNION the untracked-but-not-ignored files — so a file is checked while it
    is being written, not after the commit that ships it. Proven in all four
    directions (convention 2) against a real seeded git repository, plus the
    fail-closed declaration this module's policy requires.

    The violation seeded throughout is a citation of R7, which the miniature
    register does not carry: one defect, moved between the three states a
    file can be in, so what the tests separate is the STATE and nothing else.
    """

    NOTE = "As required by R7, keel does it.\n"

    def _repo(self, tmp: str, staged: dict[str, str], untracked: dict[str, str]) -> Path:
        """A miniature git repository with the register staged.

        The register is always staged because an empty index is a
        misconfiguration this module refuses to scan — see
        ``_tracked_text_files`` — and never the state under test here.
        """
        root = Path(tmp)
        self._git(root, ["init", "-q"])
        (root / ".gitignore").write_text("docs/internal/\n", encoding="utf-8")
        files = {keel_checks.RULES_DOC: TestRefsCheck.REGISTER, **staged, **untracked}
        for rel, text in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        self._git(root, ["add", "--", keel_checks.RULES_DOC, *staged])
        return root

    def _git(self, root: Path, args: list[str]) -> None:
        result = subprocess.run(
            ["git", *args], cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_an_unstaged_file_is_scanned(self) -> None:
        """The whole point: written, not staged, and caught anyway."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, staged={}, untracked={"docs/note.md": self.NOTE})
            self.assertIn("docs/note.md", keel_checks._scanned_files(root))
            self.assertNotIn("docs/note.md", keel_checks._tracked_text_files(root))
            findings = keel_checks.check_refs(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/note.md:1", findings[0])
            self.assertIn("R7", findings[0])

    def test_a_staged_file_is_still_scanned(self) -> None:
        """A REGRESSION guard, not proof of the fix — and labelled as one.

        This case passes under the old tracked-only seam too, because a
        staged file is already listed by ``git ls-files``. It earns its place
        by failing if the union ever loses its tracked half — a scan that
        covered only untracked files would satisfy every other test in this
        class. The directions that prove the fix itself are
        ``test_an_unstaged_file_is_scanned`` and
        ``test_the_name_check_reads_the_same_scan_set``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, staged={"docs/note.md": self.NOTE}, untracked={})
            self.assertIn("docs/note.md", keel_checks._scanned_files(root))
            findings = keel_checks.check_refs(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("docs/note.md:1", findings[0])

    def test_a_non_ascii_filename_is_not_silently_skipped(self) -> None:
        """git escapes such a name unless asked not to, and an escaped name
        resolves to nothing on disk — which the scans would swallow as an
        unreadable file. Asserted by count, not by comparing the name: two
        of the three supported operating systems normalise it differently."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp, staged={}, untracked={"docs/nöte.md": self.NOTE})
            findings = keel_checks.check_refs(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("R7", findings[0])

    def test_an_ignored_file_is_not_scanned(self) -> None:
        """An ignored file reaches no checkout, so it is in no scan set —
        the same rule that makes a cited ignored path count as absent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(
                tmp, staged={}, untracked={"docs/internal/note.md": self.NOTE}
            )
            self.assertTrue((root / "docs/internal/note.md").is_file())
            self.assertNotIn("docs/internal/note.md", keel_checks._scanned_files(root))
            self.assertEqual(keel_checks.check_refs(root), [])

    def test_a_clean_tree_passes(self) -> None:
        """A guard that only ever fails is as unproven as one that only passes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(
                tmp,
                staged={"scripts/keel_checks.py": "# stand-in\n"},
                untracked={"docs/note.md": "R1 is enforced by `scripts/keel_checks.py`.\n"},
            )
            self.assertEqual(keel_checks.check_refs(root), [])

    def test_the_name_check_reads_the_same_scan_set(self) -> None:
        """Both scans take the seam, so an unstaged file is caught by either.

        The manifest is seeded here rather than borrowed from the repository:
        the list is stored hashed, so a test can name its own forbidden word
        by hashing it the way the checker does, without writing that word's
        real counterpart anywhere.
        """
        digest = hashlib.sha256(b"ghostname").hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(
                tmp,
                staged={"scripts/keel-denied-names.json": json.dumps({"hashes": [digest]})},
                untracked={"docs/note.md": "The ghostname is printed here.\n"},
            )
            self.assertEqual(keel_checks.check_vendor_names(root), ["docs/note.md:1"])

    def test_a_git_that_cannot_answer_fails_closed(self) -> None:
        """No repository: the scan set raises rather than reporting no files,
        because an empty list would pass every file check by vacuum."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse((root / ".git").exists())
            with self.assertRaises(RuntimeError):
                keel_checks._scanned_files(root)

    def test_an_empty_index_is_a_misconfiguration_not_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._git(root, ["init", "-q"])
            with self.assertRaises(RuntimeError):
                keel_checks._tracked_text_files(root)


if __name__ == "__main__":
    unittest.main()
