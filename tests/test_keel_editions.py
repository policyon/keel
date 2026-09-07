#!/usr/bin/env python3
"""Edition generator test suite - ``scripts/keel_gen_editions.py``.

Contract
--------
Reads   : this repository's own working tree (a correct generation must
          succeed against the real registry) and miniature synthetic project
          trees built inside temporary directories (the failure direction,
          convention 2: guards are proven in both directions).
Emits   : unittest results only. Nothing is written outside temporary
          directories created and removed by the tests themselves.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: these tests assert that a registry
naming a missing component fails the generation loudly rather than emitting
a silently partial bundle, and that a registry naming an always-excluded
path (``keel_gen_editions.EXCLUDED_PATHS``) fails the same way rather than
being quietly trimmed out of the bundle.

Constraints
-----------
Python 3.10+, standard library only. Every file these tests write names its
encoding explicitly (convention 6).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GEN = REPO_ROOT / "scripts" / "keel_gen_editions.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402  (path must be set first)
import keel_gen_editions  # noqa: E402


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _files_under(root: Path) -> set[str]:
    """Every file's path relative to ``root``, POSIX-separated, for set math."""
    return {
        str(path.relative_to(root)).replace(os.sep, "/")
        for path in root.rglob("*")
        if path.is_file()
    }


def _fingerprints(root: Path) -> dict[str, tuple[int, int, str]]:
    """Every file under ``root`` (empty if absent), keyed by relative POSIX
    path, valued by (size, mtime_ns, sha256 of the bytes).

    A path-only snapshot cannot see the leak this guards against: a
    generator run overwrites an existing bundle at deterministic paths, so
    the path set is identical before and after. Neither can a content-only
    snapshot: the bundle a second run writes is byte-for-byte the one it
    replaced (component files are copied with ``shutil.copy2``, which
    preserves the source's own mtime, and the two generated files -
    ``plugin.json`` and the scoped ``keel-features.json`` - are rewritten
    from unchanged inputs). Only mtime moves, so the fingerprint carries
    mtime. ``test_a_leaked_bundle_would_still_be_caught`` pins all three
    facts.
    """
    if not root.exists():
        return {}
    prints: dict[str, tuple[int, int, str]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = str(path.relative_to(root)).replace(os.sep, "/")
        stat = path.stat()
        prints[relative] = (
            stat.st_size,
            stat.st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return prints


class TestGenerateFromRealRegistry(unittest.TestCase):
    """The generator against this repository's own registry."""

    def test_keel_core_carries_kernel_and_orchestration_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            bundle, count = keel_gen_editions.generate_edition(
                "keel-core",
                REPO_ROOT,
                out,
                keel_gen_editions.load_registry(REPO_ROOT),
            )
            self.assertGreater(count, 0)
            self.assertTrue((bundle / "hooks" / "keel_gate.py").is_file())
            self.assertTrue((bundle / "skills" / "moor" / "SKILL.md").is_file())
            self.assertFalse((bundle / "skills" / "chart").exists())
            self.assertFalse(
                (bundle / "agents" / "reviewer-correctness.md").exists()
            )
            self.assertFalse((bundle / "scripts" / "keel_dashboard.py").exists())
            manifest = json.loads(
                (bundle / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["name"], "keel-core")
            source_manifest = json.loads(
                (REPO_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )
            # Every field but 'name' and 'description' is copied through
            # verbatim. Compared as whole mappings, not an enumerated subset,
            # so a field added to the source manifest later is covered
            # without touching this test - and a dropped, renamed or mangled
            # field fails it. 'description' is pinned separately below: it
            # is the source description plus this edition's clause, not a
            # verbatim copy.
            self.assertEqual(
                {
                    key: value
                    for key, value in manifest.items()
                    if key not in ("name", "description")
                },
                {
                    key: value
                    for key, value in source_manifest.items()
                    if key not in ("name", "description")
                },
            )
            self.assertEqual(
                manifest["description"],
                source_manifest["description"]
                + " "
                + keel_gen_editions.EDITION_DESCRIPTIONS["keel-core"],
            )
            # Guard against the comparison above passing vacuously if the
            # source manifest is ever reduced to 'name' alone.
            self.assertGreater(len(source_manifest), 1, source_manifest)

    def test_cli_generates_all_four_editions_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            result = subprocess.run(
                [sys.executable, "-B", str(GEN), "--out", str(out)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ("keel-core", "keel", "keel-govern", "keel-fleet"):
                self.assertIn(name, result.stdout)
                self.assertTrue((out / name).is_dir())

    def test_editions_are_strict_supersets_by_file_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            file_sets: dict[str, set[str]] = {}
            for name in keel_gen_editions.EDITIONS_ORDER:
                bundle, _ = keel_gen_editions.generate_edition(
                    name, REPO_ROOT, out, registry
                )
                file_sets[name] = _files_under(bundle)
            order = keel_gen_editions.EDITIONS_ORDER
            for smaller, larger in zip(order, order[1:]):
                missing = file_sets[smaller] - file_sets[larger]
                self.assertEqual(
                    missing,
                    set(),
                    f"{smaller} carries files not in {larger}: {missing}",
                )
                self.assertLess(
                    len(file_sets[smaller]),
                    len(file_sets[larger]),
                    f"{smaller} is not a strict subset of {larger}",
                )

    def test_generated_fleet_bundle_passes_closure(self) -> None:
        """keel-fleet includes every feature, so its bundle carries the same
        agents/skills tree and the same registry as the real repo - the
        closure check's ownership and invocation logic can therefore run
        in-process against the generated root exactly as it runs against
        this repository. check_closure(root: Path) -> list[str] takes only
        a project directory (scripts/keel_checks.py ~line 718), so this is
        a genuine in-process run, not a skip."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            bundle, _ = keel_gen_editions.generate_edition(
                "keel-fleet", REPO_ROOT, out, registry
            )
            self.assertEqual(keel_checks.check_closure(bundle), [])


def seed_project(
    root: Path,
    *,
    ghost: bool = False,
    extra_kernel_components: tuple[str, ...] = (),
) -> None:
    """A minimal project satisfying every SHARED_PAYLOAD path and the
    plugin manifest, plus a kernel/orchestration registry. Kernel claims the
    registry itself, as this repository's kernel does, so a generated bundle
    carries the (edition-scoped) registry every bundle is contracted to ship.
    When ``ghost`` is True, kernel claims a component that is never written,
    which must make generation fail rather than silently drop it. Every path
    in ``extra_kernel_components`` is claimed by kernel *and* written to disk,
    so a failure over one of them can only be the exclusion guard talking,
    never the missing-path check."""
    for shared in keel_gen_editions.SHARED_PAYLOAD:
        path = root / shared
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stand-in\n", encoding="utf-8")
    manifest_path = root / keel_gen_editions.PLUGIN_MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"name": "keel", "version": "0.0.0"}), encoding="utf-8"
    )
    kernel_components = ["scripts/keel.py", keel_gen_editions.FEATURES_REGISTRY]
    if ghost:
        kernel_components.append("scripts/keel_ghost.py")
    for extra in extra_kernel_components:
        kernel_components.append(extra)
        extra_path = root / extra
        extra_path.parent.mkdir(parents=True, exist_ok=True)
        extra_path.write_text("stand-in\n", encoding="utf-8")
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "keel.py").write_text("# stand-in\n", encoding="utf-8")
    (root / "skills" / "moor").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "moor" / "SKILL.md").write_text(
        "---\nname: moor\n---\n\n# moor\n", encoding="utf-8"
    )
    registry = {
        "v": 1,
        "features": {
            "kernel": {
                "layer": "core",
                "components": kernel_components,
                "requires": [],
            },
            "orchestration": {
                "layer": "core",
                "components": ["skills/moor/"],
                "requires": ["kernel"],
            },
        },
    }
    registry_path = root / keel_gen_editions.FEATURES_REGISTRY
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")


class TestMissingComponentFailsClosed(unittest.TestCase):
    """A registry naming a file that does not exist is a loud failure."""

    def test_a_missing_component_path_fails_the_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, ghost=True)
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(project)
            with self.assertRaises(keel_gen_editions.EditionError) as ctx:
                keel_gen_editions.generate_edition(
                    "keel-core", project, out, registry
                )
            self.assertIn("scripts/keel_ghost.py", str(ctx.exception))
            self.assertIn("kernel", str(ctx.exception))
            self.assertFalse((out / "keel-core").exists())

    def test_a_missing_component_path_fails_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, ghost=True)
            out = Path(tmp) / "editions"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(GEN),
                    "--project",
                    str(project),
                    "--out",
                    str(out),
                    "--edition",
                    "keel-core",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("scripts/keel_ghost.py", result.stderr)
            self.assertIn("kernel", result.stderr)
            self.assertFalse((out / "keel-core").exists())

    def test_a_clean_seeded_project_generates_without_the_ghost(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, ghost=False)
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(project)
            bundle, count = keel_gen_editions.generate_edition(
                "keel-core", project, out, registry
            )
            self.assertGreater(count, 0)
            self.assertTrue((bundle / "skills" / "moor" / "SKILL.md").is_file())


class TestExcludedPathsAreNeverPayload(unittest.TestCase):
    """EXCLUDED_PATHS is enforced, not merely documented (convention 2: the
    guard is proven in both directions - a registry naming an excluded path
    fails loudly, and the real repository's four bundles carry none of the
    excluded prefixes)."""

    def _run_cli(self, project: Path, out: Path, tmp: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(GEN),
                "--project",
                str(project),
                "--out",
                str(out),
                "--edition",
                "keel-core",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=clean_env(tmp),
            check=False,
        )

    def test_registry_naming_marketplace_json_fails_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(
                project,
                extra_kernel_components=(".claude-plugin/marketplace.json",),
            )
            out = Path(tmp) / "editions"
            result = self._run_cli(project, out, Path(tmp))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(".claude-plugin/marketplace.json", result.stderr)
            self.assertIn("exclu", result.stderr)
            self.assertIn("kernel", result.stderr)
            self.assertFalse((out / "keel-core").exists())

    def test_registry_naming_a_tests_path_fails_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, extra_kernel_components=("tests/test_seed.py",))
            out = Path(tmp) / "editions"
            result = self._run_cli(project, out, Path(tmp))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("tests/test_seed.py", result.stderr)
            self.assertIn("tests/", result.stderr)
            self.assertFalse((out / "keel-core").exists())

    def test_registry_naming_a_tests_path_fails_the_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, extra_kernel_components=("tests/test_seed.py",))
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(project)
            with self.assertRaises(keel_gen_editions.EditionError) as ctx:
                keel_gen_editions.generate_edition("keel-core", project, out, registry)
            message = str(ctx.exception)
            self.assertIn("tests/test_seed.py", message)
            self.assertIn("exclu", message)
            self.assertFalse((out / "keel-core").exists())

    def test_a_directory_component_hiding_an_excluded_child_fails(self) -> None:
        """The claim is "regardless of registry contents", so a component
        naming a parent directory cannot carry an excluded child in either."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, extra_kernel_components=("docs/internal/plan.md",))
            registry_path = project / keel_gen_editions.FEATURES_REGISTRY
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            registry["features"]["kernel"]["components"] = ["scripts/keel.py", "docs/"]
            registry_path.write_text(json.dumps(registry), encoding="utf-8")
            out = Path(tmp) / "editions"
            with self.assertRaises(keel_gen_editions.EditionError) as ctx:
                keel_gen_editions.generate_edition(
                    "keel-core",
                    project,
                    out,
                    keel_gen_editions.load_registry(project),
                )
            message = str(ctx.exception)
            self.assertIn("docs/internal", message)
            self.assertIn("exclusion rule 'docs/internal/'", message)
            self.assertFalse((out / "keel-core").exists())

    def test_an_excluded_shared_payload_path_fails(self) -> None:
        """The guard covers SHARED_PAYLOAD too, not only registry components."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project)
            payload = keel_gen_editions.SHARED_PAYLOAD + (".github/workflows/ci.yml",)
            workflow = project / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True, exist_ok=True)
            workflow.write_text("stand-in\n", encoding="utf-8")
            out = Path(tmp) / "editions"
            with unittest.mock.patch.object(
                keel_gen_editions, "SHARED_PAYLOAD", payload
            ):
                with self.assertRaises(keel_gen_editions.EditionError) as ctx:
                    keel_gen_editions.generate_edition(
                        "keel-core",
                        project,
                        out,
                        keel_gen_editions.load_registry(project),
                    )
            message = str(ctx.exception)
            self.assertIn(".github/workflows/ci.yml", message)
            self.assertIn("shared payload", message)
            self.assertFalse((out / "keel-core").exists())

    def test_no_real_bundle_carries_an_excluded_prefix(self) -> None:
        """The passing direction: all four bundles emit, and no file in any of
        them sits under an excluded prefix."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            for name in keel_gen_editions.EDITIONS_ORDER:
                bundle, count = keel_gen_editions.generate_edition(
                    name, REPO_ROOT, out, registry
                )
                self.assertGreater(count, 0)
                offenders = {
                    relative
                    for relative in _files_under(bundle)
                    if keel_gen_editions.excluded_reason(relative) is not None
                }
                self.assertEqual(
                    offenders, set(), f"{name} carries excluded paths: {offenders}"
                )
                for rule in keel_gen_editions.EXCLUDED_PATHS:
                    self.assertFalse(
                        (bundle / rule.rstrip("/")).exists(),
                        f"{name} carries excluded path {rule}",
                    )
            self.assertEqual(
                sorted(path.name for path in out.iterdir() if path.is_dir()),
                sorted(keel_gen_editions.EDITIONS_ORDER),
            )


class TestUnreadableRegistryCannotRun(unittest.TestCase):
    """No registry at all is exit 2 - cannot run, not a generation failure."""

    def test_missing_registry_cli_exits_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "empty"
            project.mkdir()
            out = Path(tmp) / "editions"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(GEN),
                    "--project",
                    str(project),
                    "--out",
                    str(out),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


class TestValidateEditions(unittest.TestCase):
    """``--validate`` (T21): one command validates every generated edition."""

    def test_real_repo_validates_all_four_editions_green(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-B", str(GEN), "--validate"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in keel_gen_editions.EDITIONS_ORDER:
                self.assertIn(f"VALID {name} ", result.stdout)
            self.assertNotIn("INVALID", result.stdout)

    def test_validate_leaves_no_build_directory_behind(self) -> None:
        """Default --out under --validate is a scratch dir, not build/editions
        - validation must not add, remove, or rewrite so much as one file
        under build/ in the checkout. REPO_ROOT is not a clean room: a
        developer's own prior generator run (or a leftover from an
        unrelated test) may already have left a populated, gitignored
        build/ here, and that is not a validation leak - so this compares a
        before/after fingerprint of whatever build/ already holds rather
        than asserting the directory is absent. The fingerprint carries
        mtime because the regression it must catch (``--validate`` falling
        through to the default out_root at keel_gen_editions.py:687)
        rewrites a bundle in place at paths that already exist, with bytes
        that are identical to the ones it replaced. See
        test_a_leaked_bundle_would_still_be_caught below."""
        own_build = REPO_ROOT / "build"
        before = _fingerprints(own_build)
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-B", str(GEN), "--validate"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = _fingerprints(own_build)
        self.assertEqual(
            before,
            after,
            "--validate must not add, remove, or rewrite a single file under "
            "build/, whether or not build/ already existed before this test ran",
        )

    def test_a_leaked_bundle_would_still_be_caught(self) -> None:
        """Pins the failing direction of the guard above, on the exact code
        path a regression would take and in the exact condition that makes
        the leak hardest to see.

        The regression is ``--validate`` losing its scratch directory and
        falling through to ``out_root = project / "build" / "editions"``
        (keel_gen_editions.py:687), so what this runs is the same CLI in
        the same subprocess, taking that very line - against a stand-in
        project of its own, never REPO_ROOT, so the checkout the guard
        protects is not written to. It runs twice: the first run populates
        the stand-in build/, the second overwrites an ALREADY-POPULATED one,
        which is the case a weaker snapshot misses.

        The three assertions are ordered by what they rule out: the path
        set is unchanged (a path-only snapshot is blind), the bytes are
        unchanged (a content-only snapshot is blind too), and the
        fingerprint still differs."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project)
            leak = [
                sys.executable,
                "-B",
                str(GEN),
                "--project",
                str(project),
                "--edition",
                "keel-core",
            ]
            env = clean_env(Path(tmp))
            first = subprocess.run(
                leak,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            stand_in_build = project / "build"
            before = _fingerprints(stand_in_build)
            self.assertNotEqual(before, {}, "the first run wrote no bundle")
            second = subprocess.run(
                leak,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                check=False,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            after = _fingerprints(stand_in_build)
            self.assertEqual(
                set(before),
                set(after),
                "the overwrite changed the path set, so this no longer covers "
                "the case a path-only snapshot would miss",
            )
            self.assertEqual(
                {name: (size, digest) for name, (size, _, digest) in before.items()},
                {name: (size, digest) for name, (size, _, digest) in after.items()},
                "the overwrite changed the bytes, so this no longer covers the "
                "case a content-only snapshot would miss",
            )
            self.assertNotEqual(
                before,
                after,
                "a bundle overwritten in place must show up as a difference: "
                "without this, the guard above cannot fail on a real leak",
            )

    def test_validate_api_passes_for_the_real_fleet_edition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            source_version = json.loads(
                (REPO_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )["version"]
            file_count, violations = keel_gen_editions.validate_edition(
                "keel-fleet", REPO_ROOT, out, registry, source_version
            )
            self.assertEqual(violations, [])
            self.assertGreater(file_count, 0)

    def _seed_bundle_escape_project(self, tmp: Path) -> Path:
        """A synthetic project whose only skill (moor, owned by orchestration -
        included in every edition) invokes /keel:chart, but no chart feature
        or skill exists anywhere in the project. The bundle-escape clause of
        check_closure must catch this regardless of edition."""
        project = tmp / "project"
        project.mkdir()
        seed_project(project)
        skill_md = project / "skills" / "moor" / "SKILL.md"
        skill_md.write_text(
            "---\nname: moor\n---\n\n# moor\n\nSee /keel:chart for details.\n",
            encoding="utf-8",
        )
        return project

    def test_a_skill_invoking_an_absent_feature_fails_validation_api(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seed_bundle_escape_project(Path(tmp))
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(project)
            source_version = json.loads(
                (project / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )["version"]
            file_count, violations = keel_gen_editions.validate_edition(
                "keel-core", project, out, registry, source_version
            )
            self.assertGreater(file_count, 0)
            self.assertTrue(
                any("unresolved_invocation" in v for v in violations), violations
            )
            self.assertTrue(
                any(v.startswith("closure:") for v in violations), violations
            )

    def test_a_skill_invoking_an_absent_feature_fails_validation_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seed_bundle_escape_project(Path(tmp))
            out = Path(tmp) / "editions"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(GEN),
                    "--project",
                    str(project),
                    "--out",
                    str(out),
                    "--edition",
                    "keel-core",
                    "--validate",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("INVALID keel-core", result.stdout)
            self.assertIn("unresolved_invocation", result.stdout)

    def test_a_generation_failure_is_reported_as_invalid_not_a_crash(self) -> None:
        """A registry naming a missing component makes validation report that
        edition INVALID with the generation error as its failing assertion,
        never an uncaught exception or a silent skip."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            seed_project(project, ghost=True)
            out = Path(tmp) / "editions"
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(GEN),
                    "--project",
                    str(project),
                    "--out",
                    str(out),
                    "--edition",
                    "keel-core",
                    "--validate",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(REPO_ROOT),
                env=clean_env(Path(tmp)),
                check=False,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("INVALID keel-core", result.stdout)
            self.assertIn("generation:", result.stdout)
            self.assertIn("scripts/keel_ghost.py", result.stdout)

    def test_a_tampered_description_fails_the_manifest_assertion(self) -> None:
        """The manifest assertion pins 'description', not only 'name' and
        'version'. ``validate_edition`` regenerates the bundle itself, so the
        tamper is injected by faking ``write_plugin_manifest`` for the
        duration of this one generation call, standing in for a bundle whose
        description was corrupted after the fact."""

        real_write = keel_gen_editions.write_plugin_manifest

        def tampered_write(project, bundle, edition_name, **kwargs):
            # **kwargs, not a fixed signature: generate_edition passes
            # source_identity through to the real function, and a stub that
            # refused it would fail this test on a TypeError rather than on
            # the tampered description it exists to catch.
            real_write(project, bundle, edition_name, **kwargs)
            manifest_path = bundle / keel_gen_editions.PLUGIN_MANIFEST
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["description"] = "tampered"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            source_version = json.loads(
                (REPO_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )["version"]
            with unittest.mock.patch.object(
                keel_gen_editions, "write_plugin_manifest", tampered_write
            ):
                file_count, violations = keel_gen_editions.validate_edition(
                    "keel-core", REPO_ROOT, out, registry, source_version
                )
            self.assertGreater(file_count, 0)
            self.assertTrue(
                any("description" in v for v in violations), violations
            )


class TestEditionDescriptions(unittest.TestCase):
    """Each edition's plugin.json gets a per-edition description: the source
    description plus a short house-voice clause naming the edition."""

    def test_every_edition_appends_its_own_clause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            registry = keel_gen_editions.load_registry(REPO_ROOT)
            source_description = json.loads(
                (REPO_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                    encoding="utf-8"
                )
            )["description"]
            for name in keel_gen_editions.EDITIONS_ORDER:
                bundle, _ = keel_gen_editions.generate_edition(
                    name, REPO_ROOT, out, registry
                )
                manifest = json.loads(
                    (bundle / keel_gen_editions.PLUGIN_MANIFEST).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    manifest["description"],
                    source_description
                    + " "
                    + keel_gen_editions.EDITION_DESCRIPTIONS[name],
                )
                # Every clause is genuinely distinct - a copy-paste error
                # collapsing two editions to the same clause is caught here.
        clauses = list(keel_gen_editions.EDITION_DESCRIPTIONS.values())
        self.assertEqual(len(clauses), len(set(clauses)), clauses)


class TestBundleRegistryIsEditionScoped(unittest.TestCase):
    """The "Registry scoping" contract: every bundle ships a registry naming
    exactly its own features, GENERATION is what writes it, and ``--validate``
    leaves that file untouched - so ``--out X`` and ``--out X --validate``
    cannot leave materially different artifacts at the same path."""

    def _run(self, args: list[str], tmp: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(GEN), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=clean_env(tmp),
            check=False,
        )

    def _registry_bytes(self, bundle: Path) -> bytes:
        return (bundle / keel_gen_editions.FEATURES_REGISTRY).read_bytes()

    def _registry(self, root: Path) -> dict:
        return json.loads(
            (root / keel_gen_editions.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )

    def test_generation_without_validate_scopes_the_core_registry(self) -> None:
        """No --validate anywhere in this test: plain generation must already
        leave keel-core carrying a registry scoped to its own closure."""
        source_before = self._registry_bytes(REPO_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            result = self._run(
                ["--out", str(out), "--edition", "keel-core"], Path(tmp)
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = self._registry(out / "keel-core")
            self.assertEqual(sorted(data["features"]), ["kernel", "orchestration"])
            for absent in ("knowledge", "review", "viewer"):
                self.assertNotIn(absent, data["features"], sorted(data["features"]))
            # Top-level keys other than 'features' survive the rewrite.
            self.assertEqual(data["v"], self._registry(REPO_ROOT)["v"])
        # The source repository's own registry is never modified.
        self.assertEqual(self._registry_bytes(REPO_ROOT), source_before)

    def test_fleet_registry_equals_the_source_registry(self) -> None:
        """keel-fleet's closure is every feature, so its scoped registry is the
        source registry - compared as parsed structures, formatting aside."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "editions"
            result = self._run(
                ["--out", str(out), "--edition", "keel-fleet"], Path(tmp)
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            shipped = self._registry(out / "keel-fleet")
            source = self._registry(REPO_ROOT)
            self.assertEqual(shipped, source)
            # Not vacuous: the source registry names more than one feature, so
            # an all-features bundle is a real superset of keel-core's.
            self.assertGreater(len(source["features"]), 1, sorted(source["features"]))

    def test_validate_leaves_the_same_bundle_as_plain_generation(self) -> None:
        """The docstring's claim, pinned: at the same --out, adding --validate
        changes nothing about what is left behind - registry bytes included."""
        for edition in ("keel-core", "keel-fleet"):
            with self.subTest(edition=edition), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "editions"
                plain = self._run(
                    ["--out", str(out), "--edition", edition], Path(tmp)
                )
                self.assertEqual(plain.returncode, 0, plain.stdout + plain.stderr)
                bundle = out / edition
                plain_registry = self._registry_bytes(bundle)
                plain_files = _files_under(bundle)

                validated = self._run(
                    ["--out", str(out), "--edition", edition, "--validate"],
                    Path(tmp),
                )
                self.assertEqual(
                    validated.returncode, 0, validated.stdout + validated.stderr
                )
                self.assertIn(f"VALID {edition} ", validated.stdout)
                self.assertEqual(self._registry_bytes(bundle), plain_registry)
                self.assertEqual(_files_under(bundle), plain_files)


if __name__ == "__main__":
    unittest.main()
