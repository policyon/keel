#!/usr/bin/env python3
"""The tracked distribution - ``dist/keel`` (T614, BL37's disclosure half).

Contract
--------
Reads   : ``.claude-plugin/marketplace.json``, the tracked distribution at
          ``dist/keel``, the feature registry, and this repository's own
          ``.keel/`` directory - fingerprinted only, never written. Also
          miniature synthetic projects built inside temporary directories,
          for the failure direction.
Emits   : unittest results only. Nothing is written outside temporary
          directories these tests create and remove - including nothing
          under ``dist/`` or ``build/``, which is the whole point of two of
          them.

What this file is for
---------------------
Until 2026-09-06 the marketplace entry named ``"./"`` as its plugin source,
so an install copied this repository WHOLE: session ledgers, the audit log,
knowledge, decisions, the test suite, and gitignored internal working
material - a local install does not consult ``.gitignore``, which was
measured rather than assumed (T499/T505, T612). The entry now names the
tracked ``dist/keel`` bundle. These tests hold the two directions BL37 asks
for: what the shipped tree may carry, and that generating it disturbs
nothing in this repository's own records.

Why an ALLOWLIST and not a list of absences
--------------------------------------------
"No ``docs/internal/`` in the bundle" passes trivially on a CI checkout,
where that directory is gitignored and therefore does not exist - a green
assertion proving nothing about the guard it names. So the shipped path set
is compared CLOSED, against what a fresh generation emits: a path in the
tree and not in that set fails, whatever it is called. The excluded
vocabulary is imported from :data:`keel_gen_editions.EXCLUDED_PATHS` rather
than retyped, so this file cannot drift from the list generation enforces,
and never spells out a gitignored path in tracked text
(``.keel/knowledge/keel-tracked-ledger-scan-trap.md``).

The seam: DISK, not git
-----------------------
The shipped set is read by WALKING THE FILESYSTEM under the bundle, not
through ``git ls-files`` and not through ``keel_checks._scanned_files``
(git's index UNION untracked-but-not-ignored, R45), which is what this file
used until 2026-09-06. Every git-derived set excludes gitignored paths by
construction, and the measured fact this whole task exists because of - see
the paragraph above - is that an install does NOT consult ``.gitignore``: it
copies the tree as it stands. So a gitignored file inside the bundle ships
to every installer while a git-derived guard reports clean, which is BL37's
own defect reproduced inside BL37's fix. The walk keeps what the git read
was chosen for, since an uncommitted regenerated bundle is exactly the thing
under test and a walk sees it too.
:class:`TestAGitignoredFileInsideTheBundleStillShips` pins the failure the
git read could not see, in a stand-in repository with a ``.gitignore`` of
its own.

Failure policy
--------------
FAIL-CLOSED. Every assertion here is written so that an empty or absent
distribution FAILS rather than passing by vacuum, and the staleness check's
own failing direction is exercised rather than assumed
(:class:`TestTheStalenessCheckCanActuallyFail`).

Constraints
-----------
Python 3.10+, standard library only. Every file these tests write names its
encoding explicitly (convention 6).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(TESTS_DIR))
import keel_checks  # noqa: E402  (path must be set first)
import keel_gen_editions  # noqa: E402

# One definition of "fingerprint", not two: tests/test_keel_editions.py
# already established (size, mtime_ns, sha256) per path, and states in its
# own docstring why a path-set or content-only snapshot misses an overwrite
# that rewrites identical bytes. The records direction below needs exactly
# that property, so it borrows the function instead of restating it.
from test_keel_editions import _fingerprints  # noqa: E402

MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
DIST = keel_gen_editions.DISTRIBUTION_PATH
DIST_ROOT = REPO_ROOT / DIST


def paths_on_disk(bundle_root: Path) -> list[str]:
    """Every file physically present under ``bundle_root``, bundle-relative
    POSIX. Deliberately its own walk rather than a call into
    ``keel_checks._distribution_paths_on_disk``: the production guard is one
    of the things under test here, and a test that borrowed its path
    collection would inherit whatever that collection was blind to. See "The
    seam: DISK, not git" in the module docstring."""
    if not bundle_root.is_dir():
        return []
    return sorted(
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    )


def shipped_paths() -> list[str]:
    """Every path an install would copy out of this repository's own
    distribution, relative to the bundle root."""
    return paths_on_disk(DIST_ROOT)


def generated_paths(out: Path, root: Path = REPO_ROOT) -> list[str]:
    """Every path a fresh generation of ``root``'s distribution emits,
    relative to the bundle root. ``root`` is a parameter because the fixture
    classes below generate from a stand-in project, and comparing a fixture
    bundle against THIS repository's generation would be comparing two
    different trees."""
    features = keel_gen_editions.load_registry(root)
    bundle, _count = keel_gen_editions.generate_distribution(root, out, features)
    return sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
    )


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """One git invocation, as an argument list (R5), with its output kept."""
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )


def seed_full_project(root: Path) -> None:
    """A miniature project whose registry defines EVERY feature the
    distribution's closure names, so ``generate_distribution`` runs against
    it exactly as it runs here.

    Deliberately its own seed rather than an extension of
    ``test_keel_editions.seed_project``, which defines kernel and
    orchestration only: the distribution is the FULL closure, and a seed
    that could not express that would be testing a different shape than the
    one that ships.
    """
    for shared in keel_gen_editions.SHARED_PAYLOAD:
        path = root / shared
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stand-in\n", encoding="utf-8")
    manifest = root / keel_gen_editions.PLUGIN_MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "name": keel_gen_editions.DISTRIBUTION_DIRNAME,
                "version": "0.0.0",
                "description": "stand-in",
            }
        ),
        encoding="utf-8",
    )
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "keel.py").write_text("# stand-in\n", encoding="utf-8")
    for feature in ("knowledge", "review", "viewer"):
        page = root / "skills" / feature / "SKILL.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f"---\nname: {feature}\n---\n\n# {feature}\n", encoding="utf-8")
    (root / "skills" / "moor").mkdir(parents=True, exist_ok=True)
    (root / "skills" / "moor" / "SKILL.md").write_text(
        "---\nname: moor\n---\n\n# moor\n", encoding="utf-8"
    )
    registry = {
        "v": 1,
        "features": {
            "kernel": {
                "layer": "core",
                "components": [
                    "scripts/keel.py",
                    keel_gen_editions.FEATURES_REGISTRY,
                ],
                "requires": [],
            },
            "orchestration": {
                "layer": "core",
                "components": ["skills/moor/"],
                "requires": ["kernel"],
            },
            "knowledge": {
                "layer": "knowledge",
                "components": ["skills/knowledge/"],
                "requires": ["kernel"],
            },
            "review": {
                "layer": "review",
                "components": ["skills/review/"],
                "requires": ["kernel"],
            },
            "viewer": {
                "layer": "viewer",
                "components": ["skills/viewer/"],
                "requires": ["kernel"],
            },
        },
    }
    registry_path = root / keel_gen_editions.FEATURES_REGISTRY
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")


def stand_in_project(tmp: Path) -> Path:
    """A seeded miniature project with a freshly generated distribution, all
    of it staged. Never this checkout: the check under test would otherwise
    be asked to judge a tree a test was mutating."""
    project = tmp / "project"
    project.mkdir()
    git("init", cwd=project)
    seed_full_project(project)
    features = keel_gen_editions.load_registry(project)
    keel_gen_editions.generate_distribution(
        project, project / keel_gen_editions.DISTRIBUTION_OUT, features
    )
    git("add", "-A", cwd=project)
    return project


class TestTheDistributionCarriesOnlyWhatItMayCarry(unittest.TestCase):
    """The closed allowlist over the shipped path set (BL37, direction one)."""

    def test_the_distribution_is_present_and_not_empty(self) -> None:
        """Every other assertion in this class is quantified over the shipped
        set, so an empty set would make them all pass saying nothing. This is
        the one that fails instead."""
        shipped = shipped_paths()
        self.assertTrue(
            shipped,
            f"{DIST}/ holds no file on disk, and marketplace.json points an "
            f"install at it",
        )
        self.assertIn(".claude-plugin/plugin.json", shipped)
        self.assertIn("hooks/keel_gate.py", shipped)

    def test_every_shipped_path_is_one_the_distribution_may_carry(self) -> None:
        """THE ALLOWLIST, closed both ways over WHAT IS ON DISK: the set an
        install would copy equals what a fresh generation emits. A hand-added
        file - a record, a runbook, a stray note, a gitignored build artifact
        - is not in the generated set and fails here by being present,
        without this test having to have anticipated its name."""
        with tempfile.TemporaryDirectory() as tmp:
            permitted = set(generated_paths(Path(tmp)))
        shipped = set(shipped_paths())
        self.assertTrue(permitted, "a fresh generation emitted no files")
        self.assertEqual(
            shipped - permitted,
            set(),
            "the distribution carries paths a fresh generation does not emit",
        )
        self.assertEqual(
            permitted - shipped,
            set(),
            "a fresh generation emits paths the distribution does not carry",
        )

    def test_no_shipped_path_sits_under_an_excluded_prefix(self) -> None:
        """The same vocabulary generation enforces, applied to the artifact's
        own paths. Not a substitute for the allowlist above - it is the
        narrower claim, and it is checked against paths that DO exist here."""
        shipped = shipped_paths()
        self.assertTrue(shipped)
        offenders = [
            (rel, keel_gen_editions.excluded_reason(rel))
            for rel in shipped
            if keel_gen_editions.excluded_reason(rel) is not None
        ]
        self.assertEqual(offenders, [])

    def test_the_exclusion_vocabulary_would_reject_what_it_names(self) -> None:
        """The failing direction, without writing anything into the shipped
        tree: a probe path built from each EXCLUDED_PATHS entry is rejected
        by ``excluded_reason`` AND is absent from the shipped set. Neither
        the rules nor the probes are typed out here - a rule added to that
        tuple is covered the moment it is added."""
        self.assertTrue(keel_gen_editions.EXCLUDED_PATHS)
        shipped = set(shipped_paths())
        for rule in keel_gen_editions.EXCLUDED_PATHS:
            probe = f"{rule}probe.txt" if rule.endswith("/") else rule
            with self.subTest(rule=rule):
                self.assertIsNotNone(
                    keel_gen_editions.excluded_reason(probe),
                    f"{probe} is not rejected by the exclusion rule that names it",
                )
                self.assertNotIn(probe, shipped)


class TestTheNamesAgreeWithoutConsultingPrecedence(unittest.TestCase):
    """Which ``name`` a harness prefers when the marketplace entry and the
    bundle manifest disagree is undocumented, and a mismatch is reported to
    hard-error on some platforms (T612 (H), T613). So they are made equal and
    pinned equal, and no precedence is consulted by anyone."""

    def setUp(self) -> None:
        self.catalog = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

    def test_the_marketplace_name_is_policyon(self) -> None:
        """Pinned by the owner's ruling, so a later edit cannot drift it
        silently: the marketplace is not renamed by this or any packaging
        change."""
        self.assertEqual(self.catalog["name"], "policyon")

    def test_the_entry_and_the_bundle_manifest_name_the_same_plugin(self) -> None:
        entries = self.catalog["plugins"]
        self.assertEqual(len(entries), 1)
        bundle_manifest = json.loads(
            (DIST_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(encoding="utf-8")
        )
        self.assertEqual(entries[0]["name"], bundle_manifest["name"])
        self.assertEqual(entries[0]["name"], keel_gen_editions.DISTRIBUTION_DIRNAME)
        self.assertEqual(bundle_manifest["name"], "keel")

    def test_the_source_resolves_to_the_bundle_that_carries_that_manifest(self) -> None:
        """The pointer is only worth as much as what it lands on: the entry's
        ``source``, resolved from the repository root, is the directory whose
        manifest the assertion above just read."""
        source = self.catalog["plugins"][0]["source"]
        resolved = (REPO_ROOT / source).resolve()
        self.assertTrue(resolved.is_dir(), f"{source} is not a directory here")
        self.assertEqual(resolved, DIST_ROOT.resolve())
        self.assertTrue((resolved / keel_gen_editions.PLUGIN_MANIFEST).is_file())

    def test_the_bundle_manifest_is_the_sources_own_identity(self) -> None:
        """Not the edition rewrite: the distribution ships the repository's
        own name and description, which is what makes the equality above true
        by construction rather than by coincidence."""
        source_manifest = json.loads(
            (REPO_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(encoding="utf-8")
        )
        bundle_manifest = json.loads(
            (DIST_ROOT / keel_gen_editions.PLUGIN_MANIFEST).read_text(encoding="utf-8")
        )
        self.assertEqual(bundle_manifest["name"], source_manifest["name"])
        self.assertEqual(
            bundle_manifest["description"], source_manifest["description"]
        )
        for clause in keel_gen_editions.EDITION_DESCRIPTIONS.values():
            self.assertNotIn(clause, bundle_manifest["description"])


class TestTheDistributionIsTheFullClosure(unittest.TestCase):
    """The regression that would otherwise ship in silence: the edition
    literally named ``keel`` is a NARROWER closure - no ``review``, no
    ``viewer`` - so shipping it would drop the reviewer agents and the
    dashboard an install carries today. The distribution takes
    ``DISTRIBUTION_EDITION``'s closure instead."""

    def test_the_shipped_set_is_a_strict_superset_of_the_keel_edition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            features = keel_gen_editions.load_registry(REPO_ROOT)
            bundle, _count = keel_gen_editions.generate_edition(
                "keel", REPO_ROOT, Path(tmp), features
            )
            narrower = {
                path.relative_to(bundle).as_posix()
                for path in bundle.rglob("*")
                if path.is_file()
            }
        shipped = set(shipped_paths())
        self.assertTrue(narrower)
        self.assertEqual(
            narrower - shipped,
            set(),
            "the narrower edition carries files the distribution does not",
        )
        self.assertLess(
            len(narrower),
            len(shipped),
            "the distribution is no wider than the edition that shares its "
            "name - the reviewer agents and the dashboard are missing",
        )

    def test_every_component_of_the_wider_features_is_shipped(self) -> None:
        """Named by the registry, not by this test: whatever ``review`` and
        ``viewer`` own is what must be present."""
        features = keel_gen_editions.load_registry(REPO_ROOT)
        wider = [
            component
            for feature in ("review", "viewer")
            for component in features[feature]["components"]
        ]
        self.assertTrue(wider)
        for component in wider:
            with self.subTest(component=component):
                self.assertTrue(
                    (DIST_ROOT / component.rstrip("/")).exists(),
                    f"{component} is owned by a feature the distribution "
                    f"includes but is absent from {DIST}/",
                )


class TestGeneratingTheDistributionTouchesNoRecords(unittest.TestCase):
    """BL37's SECOND direction: the project's own records are untouched by
    generation. ``.keel/`` is what the whole entry is about, so this is
    pinned rather than assumed."""

    def test_generating_the_distribution_moves_nothing_under_dot_keel(self) -> None:
        """Fingerprinted with mtime, not compared as a path set or as
        content: an overwrite that rewrites identical bytes at existing paths
        is invisible to either of those, and it is precisely the leak worth
        catching. ``tests/test_keel_editions.py`` pins that property of
        ``_fingerprints`` in its own failing-direction test; this borrows the
        function rather than the argument."""
        records = REPO_ROOT / ".keel"
        before = _fingerprints(records)
        self.assertNotEqual(before, {}, "no records to protect - test is vacuous")
        with tempfile.TemporaryDirectory() as tmp:
            features = keel_gen_editions.load_registry(REPO_ROOT)
            bundle, count = keel_gen_editions.generate_distribution(
                REPO_ROOT, Path(tmp), features
            )
            self.assertGreater(count, 0)
            self.assertTrue(bundle.is_dir())
        after = _fingerprints(records)
        moved = sorted(
            path
            for path in set(before) | set(after)
            if before.get(path) != after.get(path)
        )
        self.assertEqual(
            moved,
            [],
            "generating the distribution added, removed or rewrote records",
        )


class TestTheStalenessCheckCanActuallyFail(unittest.TestCase):
    """``keel_checks.check_distribution`` is the only thing between a tracked
    bundle and silent staleness, so its failing direction is exercised here
    rather than trusted. Every case runs against a stand-in git repository of
    its own - never this checkout, which the check under test would otherwise
    be asked to judge while a test mutated it."""

    def _stand_in(self, tmp: Path) -> Path:
        return stand_in_project(tmp)

    def test_a_freshly_generated_distribution_passes(self) -> None:
        """The green baseline, so the three failures below are the mutation
        talking and not the fixture."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._stand_in(Path(tmp))
            self.assertEqual(keel_checks.check_distribution(project), [])

    def test_editing_a_source_and_forgetting_to_regenerate_fails(self) -> None:
        """The regression this check exists for, in the exact shape it takes:
        someone edits a component and commits without rebuilding the bundle."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._stand_in(Path(tmp))
            (project / "scripts" / "keel.py").write_text(
                "# stand-in, edited\n", encoding="utf-8"
            )
            violations = keel_checks.check_distribution(project)
            self.assertTrue(violations)
            self.assertIn("STALE", violations[0])
            self.assertTrue(
                any(f"{DIST}/scripts/keel.py" in v for v in violations),
                violations,
            )

    def test_a_file_added_to_the_bundle_by_hand_fails(self) -> None:
        """The direction that matters most for BL37: something that is not a
        generated payload appearing inside the shipped tree."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._stand_in(Path(tmp))
            stowaway = project / DIST / "NOTES-from-somewhere.md"
            stowaway.write_text("not a payload\n", encoding="utf-8")
            git("add", "-A", cwd=project)
            violations = keel_checks.check_distribution(project)
            self.assertTrue(violations)
            self.assertTrue(
                any("NOTES-from-somewhere.md" in v for v in violations), violations
            )

    def test_a_missing_distribution_fails_rather_than_passing_empty(self) -> None:
        """Fail-closed: no bundle at all is a violation naming the remedy,
        never a check with nothing to compare and therefore nothing to say."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            git("init", cwd=project)
            seed_full_project(project)
            git("add", "-A", cwd=project)
            violations = keel_checks.check_distribution(project)
            self.assertTrue(violations)
            self.assertIn(DIST, violations[0])

    def test_the_check_is_registered_and_dispatched(self) -> None:
        """Registering in CHECKS is not wiring - that comment in
        keel_checks.py is there because a check once shipped selected and
        never invoked, which reads exactly like success. This asserts both
        halves: the name is in CHECKS, and running the script with only that
        flag reports a result line for it."""
        self.assertIn(
            "distribution", [name for name, _ in keel_checks.CHECKS]
        )
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
        }
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO_ROOT / "scripts" / "keel_checks.py"),
                "--distribution",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )
        self.assertIn("distribution", result.stdout, result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class TestAGitignoredFileInsideTheBundleStillShips(unittest.TestCase):
    """The finding that sent T614 back on 2026-09-06, pinned so it cannot
    return.

    A local plugin install copies the bundle directory AS IT STANDS ON DISK
    and does not consult ``.gitignore`` - the measured fact this whole task
    exists because of. Every git-derived path set (``git ls-files``, or
    ``keel_checks._scanned_files``) excludes gitignored paths by
    construction. So a guard built on one says "clean" about a tree that is
    shipping a file the guard cannot see: BL37's own defect, reproduced
    inside BL37's fix.

    The plant is a build artifact of the most ordinary kind - the bundle
    carries ``hooks/`` and ``scripts/`` full of Python, so anything that
    imports from the installed tree creates exactly this directory. The
    stand-in repository is given a ``.gitignore`` of its own so the plant is
    genuinely invisible to git HERE, in the fixture, rather than by appeal to
    this repository's ignore rules - which the trap in
    ``.keel/knowledge/keel-tracked-ledger-scan-trap.md`` warns are not the
    same rules a CI checkout has.

    MUTATION PROOF (2026-09-06): reverting ``check_distribution`` to the
    ``_scanned_files`` read, or ``paths_on_disk`` to the same, makes
    :meth:`test_the_allowlist_over_disk_rejects_it` and
    :meth:`test_the_check_fails_and_names_it` pass by blindness -
    :meth:`test_git_genuinely_cannot_see_it` is what says why.
    """

    #: Assembled rather than written out whole: the tracked-ledger scan trap
    #: (same knowledge card) is that naming a gitignored path in tracked text
    #: gives ``--refs`` a citation it must resolve, which fails on a checkout
    #: where the path does not exist. The fixture needs the NAME, not a path
    #: in this repository.
    CACHE_DIR = "__" + "pycache" + "__"
    STRAY = "stray.pyc"

    def _fixture(self, tmp: Path) -> tuple[Path, Path, str]:
        """A staged stand-in whose ``.gitignore`` hides the plant, the plant
        written into the generated bundle, and its bundle-relative path."""
        project = stand_in_project(tmp)
        (project / ".gitignore").write_text(
            f"{self.CACHE_DIR}/\n*.pyc\n", encoding="utf-8"
        )
        git("add", "-A", cwd=project)
        rel = f"hooks/{self.CACHE_DIR}/{self.STRAY}"
        planted = project / DIST / rel
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"not a payload, and git will not mention it\n")
        git("add", "-A", cwd=project)
        return project, planted, rel

    def test_git_genuinely_cannot_see_it(self) -> None:
        """The premise, measured in the fixture rather than asserted: after
        ``git add -A`` the plant is in no index and no status line, and no
        git-derived scan set contains it. If this ever fails the other two
        tests below prove nothing, because the plant would be visible."""
        with tempfile.TemporaryDirectory() as tmp:
            project, planted, rel = self._fixture(Path(tmp))
            self.assertTrue(planted.is_file(), "the plant was not written")
            tracked = git("ls-files", cwd=project).stdout
            self.assertNotIn(self.STRAY, tracked)
            status = git("status", "--porcelain", cwd=project).stdout
            self.assertNotIn(self.STRAY, status)
            scanned = keel_checks._scanned_files(project)
            self.assertTrue(scanned, "empty scan set - fixture is vacuous")
            self.assertEqual(
                [path for path in scanned if self.STRAY in path],
                [],
                "git can see the plant, so this fixture cannot show the hole",
            )

    def test_the_allowlist_over_disk_rejects_it(self) -> None:
        """This file's own closed allowlist, applied to the fixture bundle:
        the plant is present on disk and absent from a fresh generation, so
        it fails by being there."""
        with tempfile.TemporaryDirectory() as tmp:
            project, _planted, rel = self._fixture(Path(tmp))
            present = set(paths_on_disk(project / DIST))
            self.assertIn(rel, present)
            with tempfile.TemporaryDirectory() as out:
                permitted = set(generated_paths(Path(out), project))
            self.assertTrue(permitted, "a fresh generation emitted no files")
            self.assertIn(
                rel,
                present - permitted,
                "the allowlist is not closed over what is on disk",
            )

    def test_the_check_fails_and_names_it(self) -> None:
        """``keel_checks.check_distribution`` reports a violation naming the
        plant's path - the symmetric case to a file a generation emits and
        the bundle lacks."""
        with tempfile.TemporaryDirectory() as tmp:
            project, _planted, rel = self._fixture(Path(tmp))
            violations = keel_checks.check_distribution(project)
            self.assertTrue(
                violations,
                "a file that ships and is in no commit was reported clean",
            )
            self.assertIn("STALE", violations[0])
            self.assertTrue(
                any(f"{DIST}/{rel}" in v for v in violations), violations
            )

    def test_the_same_fixture_passes_once_the_plant_is_removed(self) -> None:
        """So the three failures above are the plant talking and not the
        ``.gitignore`` the fixture gained."""
        with tempfile.TemporaryDirectory() as tmp:
            project, planted, _rel = self._fixture(Path(tmp))
            planted.unlink()
            planted.parent.rmdir()
            self.assertEqual(keel_checks.check_distribution(project), [])


if __name__ == "__main__":
    unittest.main()
