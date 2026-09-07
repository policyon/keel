#!/usr/bin/env python3
"""Feature registry test suite - ``keel_checks --closure``, the editions gate,
and the cross-feature touch points that must decline visibly when a feature is
not installed (T22).

Contract
--------
Reads   : the repository working tree (the real registry must be closed, and
          the full tree is the "nothing changed" direction), miniature seeded
          trees built inside temporary directories to prove every failure
          clause fires, and one real ``keel-core`` bundle generated into a
          temporary directory - the trimmed direction, generated rather than
          mocked, so what is asserted is what a user would actually install
          (convention 2: guards are proven in both directions).
Emits   : unittest results only. Nothing is written outside temporary
          directories created and removed by the tests themselves - the
          generated bundle included, and the session-hook case writes its
          audit line into a temporary project, never into this repository's
          own record.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: a missing or unparseable registry is a
violation, never a pass, and these tests assert exactly that. The declines
asserted here are fail-closed in the CLI (exit 2, one line naming the missing
feature) and fail-open in the session hook (exit 0, one injected line), which
is each component's own declared policy and is asserted as such.

Constraints
-----------
Python 3.10+, standard library only. Subprocesses are invoked with an argument
list, never a shell string (R5), and every file these tests write names its
encoding (convention 6).
"""

from __future__ import annotations

import copy
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKS = REPO_ROOT / "scripts" / "keel_checks.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel  # noqa: E402  (path must be set first)
import keel_checks  # noqa: E402
import keel_features  # noqa: E402
import keel_gen_editions  # noqa: E402
import keel_session  # noqa: E402

#: A miniature registry mirroring the real shape: a kernel with no skills,
#: two skill-bearing features that require it, and no requirement between
#: the two skill-bearing features - so a cross-invocation is an escape.
BASE_REGISTRY = {
    "v": 1,
    "features": {
        "kernel": {
            "layer": "core",
            "components": ["scripts/keel.py"],
            "requires": [],
        },
        "orchestration": {
            "layer": "core",
            "components": ["skills/moor/"],
            "requires": ["kernel"],
        },
        "knowledge": {
            "layer": "standard",
            "components": ["skills/log/"],
            "requires": ["kernel"],
        },
    },
}

#: The files that make BASE_REGISTRY's claims true on disk.
BASE_FILES = {
    "scripts/keel.py": "# stand-in\n",
    "skills/moor/SKILL.md": "---\nname: moor\n---\n\n# moor\n",
    "skills/log/SKILL.md": "---\nname: log\n---\n\n# log\n",
}


class ClosureFixtureCase(unittest.TestCase):
    """Shared seeding for the fixture-tree tests."""

    def _seed(self, tmp: str, registry: dict, files: dict[str, str]) -> Path:
        """A miniature tree: the registry, plus the files under test."""
        root = Path(tmp)
        target = root / keel_checks.FEATURES_REGISTRY
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(registry), encoding="utf-8")
        for rel, text in files.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return root

    def _registry(self) -> dict:
        """A deep copy of BASE_REGISTRY, safe for a test to mutate."""
        return copy.deepcopy(BASE_REGISTRY)


class TestRealRegistryIsClosed(ClosureFixtureCase):
    """The shipped registry passes its own gate."""

    def test_this_repository_is_closed(self) -> None:
        self.assertEqual(keel_checks.check_closure(REPO_ROOT), [])

    def test_cli_flag_runs_and_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(CHECKS), "--closure"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS closure", result.stdout)

    def test_registry_shape(self) -> None:
        data = json.loads(
            (REPO_ROOT / keel_checks.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )
        self.assertEqual(data["v"], 1)
        for feature, spec in data["features"].items():
            self.assertTrue(spec["layer"], f"feature '{feature}' declares no layer")
            self.assertTrue(spec["components"], f"feature '{feature}' claims nothing")
            self.assertIsInstance(spec["requires"], list)


class TestClosurePasses(ClosureFixtureCase):
    """The passing direction, on seeded trees rather than this one."""

    def test_a_clean_seeded_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), BASE_FILES)
            self.assertEqual(keel_checks.check_closure(root), [])

    def test_an_invocation_of_a_required_feature_passes(self) -> None:
        """skills/log (knowledge) may invoke /keel:moor once knowledge
        requires orchestration, which owns it."""
        registry = self._registry()
        registry["features"]["knowledge"]["requires"] = ["orchestration"]
        files = dict(BASE_FILES)
        files["skills/log/SKILL.md"] = (
            "---\nname: log\n---\n\n# log\n\nWhen done, run /keel:moor to close.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, files)
            self.assertEqual(keel_checks.check_closure(root), [])

    def test_a_transitively_required_invocation_passes(self) -> None:
        """wrap requires knowledge requires orchestration: /keel:moor from
        the wrap skill resolves through the transitive closure."""
        registry = self._registry()
        registry["features"]["knowledge"]["requires"] = ["orchestration"]
        registry["features"]["wrap"] = {
            "layer": "standard",
            "components": ["skills/wrap/"],
            "requires": ["knowledge"],
        }
        files = dict(BASE_FILES)
        files["skills/wrap/SKILL.md"] = (
            "---\nname: wrap\n---\n\n# wrap\n\nFinish with /keel:moor.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, files)
            self.assertEqual(keel_checks.check_closure(root), [])

    def test_a_references_page_invocation_within_the_bundle_passes(self) -> None:
        """A references page ships with its skill's feature, so its
        invocation of a skill that feature requires is in-bundle."""
        registry = self._registry()
        registry["features"]["knowledge"]["requires"] = ["orchestration"]
        files = dict(BASE_FILES)
        files["skills/log/references/log-syntax.md"] = (
            "# log syntax\n\nWhen the log is full, run /keel:moor.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, files)
            self.assertEqual(keel_checks.check_closure(root), [])

    def test_an_invocation_within_ones_own_feature_passes(self) -> None:
        registry = self._registry()
        registry["features"]["knowledge"]["components"].append("skills/chart/")
        files = dict(BASE_FILES)
        files["skills/chart/SKILL.md"] = "---\nname: chart\n---\n\n# chart\n"
        files["skills/log/SKILL.md"] = (
            "---\nname: log\n---\n\n# log\n\nQuery it back with /keel:chart.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, files)
            self.assertEqual(keel_checks.check_closure(root), [])


class TestClosureFailsClosed(ClosureFixtureCase):
    """The registry itself, absent or malformed, is a violation."""

    def test_a_missing_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("missing_registry", findings[0])

    def test_an_unparseable_registry_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / keel_checks.FEATURES_REGISTRY
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("not json {{{", encoding="utf-8")
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("malformed_registry", findings[0])

    def test_an_empty_features_table_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, {"v": 1, "features": {}}, {})
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("empty_registry", findings[0])


class TestClosureCatchesClauseA(ClosureFixtureCase):
    """Clause (a): dead component paths, orphans and double-claims."""

    def test_a_missing_component_path_is_caught(self) -> None:
        registry = self._registry()
        registry["features"]["kernel"]["components"].append("scripts/keel_ghost.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, BASE_FILES)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("missing_component", findings[0])
            self.assertIn("scripts/keel_ghost.py", findings[0])
            self.assertIn("'kernel'", findings[0])

    def test_an_orphan_file_is_caught(self) -> None:
        files = dict(BASE_FILES)
        files["skills/extra/SKILL.md"] = "---\nname: extra\n---\n\n# extra\n"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), files)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/extra/SKILL.md", findings[0])
            self.assertIn("orphan_component", findings[0])

    def test_a_double_claim_is_caught(self) -> None:
        registry = self._registry()
        registry["features"]["orchestration"]["components"].append("skills/log/")
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, BASE_FILES)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/log/SKILL.md", findings[0])
            self.assertIn("double_claim", findings[0])
            self.assertIn("knowledge", findings[0])
            self.assertIn("orchestration", findings[0])


class TestClosureCatchesClauseB(ClosureFixtureCase):
    """Clause (b): unknown requirements and cycles."""

    def test_an_unknown_requires_is_caught(self) -> None:
        registry = self._registry()
        registry["features"]["knowledge"]["requires"] = ["kernel", "phantom"]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, BASE_FILES)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("unknown_requires", findings[0])
            self.assertIn("'phantom'", findings[0])

    def test_a_requires_cycle_is_caught(self) -> None:
        registry = self._registry()
        registry["features"]["orchestration"]["requires"] = ["kernel", "knowledge"]
        registry["features"]["knowledge"]["requires"] = ["kernel", "orchestration"]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, BASE_FILES)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("requires_cycle", findings[0])
            self.assertIn("orchestration", findings[0])
            self.assertIn("knowledge", findings[0])

    def test_a_self_cycle_is_caught(self) -> None:
        registry = self._registry()
        registry["features"]["kernel"]["requires"] = ["kernel"]
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, registry, BASE_FILES)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("requires_cycle", findings[0])
            self.assertIn("kernel -> kernel", findings[0])


class TestClosureCatchesClauseC(ClosureFixtureCase):
    """Clause (c): the bundle-closure rule on skill invocations."""

    def test_an_invocation_of_a_missing_skill_is_caught(self) -> None:
        files = dict(BASE_FILES)
        files["skills/moor/SKILL.md"] = (
            "---\nname: moor\n---\n\n# moor\n\nThen run /keel:missing to finish.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), files)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/moor/SKILL.md:7", findings[0])
            self.assertIn("unresolved_invocation", findings[0])
            self.assertIn("/keel:missing", findings[0])

    def test_an_invocation_outside_the_bundle_is_caught(self) -> None:
        """orchestration does not require knowledge, so its skill may not
        lean on /keel:log - the edition that ships one without the other
        would ship a dead instruction."""
        files = dict(BASE_FILES)
        files["skills/moor/SKILL.md"] = (
            "---\nname: moor\n---\n\n# moor\n\nAfterwards, run /keel:log.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), files)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/moor/SKILL.md:7", findings[0])
            self.assertIn("bundle_escape", findings[0])
            self.assertIn("'knowledge'", findings[0])
            self.assertIn("'orchestration'", findings[0])

    def test_a_references_page_invocation_of_a_missing_skill_is_caught(self) -> None:
        files = dict(BASE_FILES)
        files["skills/moor/references/moor-notes.md"] = (
            "# moor notes\n\nThen run /keel:missing to finish.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), files)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/moor/references/moor-notes.md:3", findings[0])
            self.assertIn("unresolved_invocation", findings[0])
            self.assertIn("/keel:missing", findings[0])

    def test_a_references_page_invocation_outside_the_bundle_is_caught(self) -> None:
        """The escape rule binds references pages too: orchestration does
        not require knowledge, so its pages may not lean on /keel:log."""
        files = dict(BASE_FILES)
        files["skills/moor/references/moor-notes.md"] = (
            "# moor notes\n\nAfterwards, run /keel:log.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = self._seed(tmp, self._registry(), files)
            findings = keel_checks.check_closure(root)
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("skills/moor/references/moor-notes.md:3", findings[0])
            self.assertIn("bundle_escape", findings[0])
            self.assertIn("'knowledge'", findings[0])
            self.assertIn("'orchestration'", findings[0])


# --------------------------------------------------------------------------
# T22: every cross-feature touch point declines visibly, or does not decline
# at all. Both directions for each one.
# --------------------------------------------------------------------------


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    ``KEEL_*`` is stripped so a developer's live override cannot add a line to
    the output these tests read, and the temp variables are redirected into the
    test's own scratch directory. ``HOME``/``USERPROFILE`` are pointed at
    ``scratch`` too: a ``session`` launch feeds keel's user-global fleet
    registry (T227), which reads ``Path.home()`` regardless of the ``KEEL_*``
    scrub above, so leaving them untouched would write fixture debris into
    the developer's real ``~/.claude/keel/keel-registry.json``.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env.update({"HOME": str(scratch), "USERPROFILE": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


class TestFeaturePresenceHelper(unittest.TestCase):
    """``hooks/keel_features.py``: absence is decided, never guessed."""

    def _install(
        self,
        tmp: str,
        *,
        registry: dict | str | None = None,
        component: bool = False,
    ) -> Path:
        """A synthetic installation root.

        ``registry`` is the shipped registry - a document, raw text, or None
        for an installation that carries none at all; ``component`` writes the
        one knowledge file the session injector probes for.
        """
        root = Path(tmp)
        if registry is not None:
            path = root / keel_checks.FEATURES_REGISTRY
            path.parent.mkdir(parents=True, exist_ok=True)
            text = registry if isinstance(registry, str) else json.dumps(registry)
            path.write_text(text, encoding="utf-8")
        if component:
            probe = root / keel_session.KNOWLEDGE_COMPONENT
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("# stand-in\n", encoding="utf-8")
        return root

    def _core_registry(self) -> dict:
        """BASE_REGISTRY as a trimmed bundle would ship it: no knowledge."""
        registry = copy.deepcopy(BASE_REGISTRY)
        del registry["features"]["knowledge"]
        return registry

    def test_a_registry_naming_the_feature_reads_as_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._install(tmp, registry=BASE_REGISTRY)
            self.assertEqual(
                keel_features.registry_features(root),
                frozenset(BASE_REGISTRY["features"]),
            )
            self.assertFalse(keel_features.feature_absent("knowledge", root=root))

    def test_a_scoped_registry_omitting_the_feature_reads_as_absent(self) -> None:
        """The T21 ruling is what makes this decidable: a trimmed bundle ships
        a registry naming only its own features."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._install(tmp, registry=self._core_registry())
            self.assertTrue(keel_features.feature_absent("knowledge", root=root))
            self.assertFalse(keel_features.feature_absent("kernel", root=root))

    def test_the_registry_outranks_the_component_probe(self) -> None:
        """A registry that names the feature settles it, even where the probed
        component happens to be missing - the registry is the honest source."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._install(tmp, registry=BASE_REGISTRY, component=False)
            self.assertFalse(
                keel_features.feature_absent(
                    "knowledge",
                    component=keel_session.KNOWLEDGE_COMPONENT,
                    root=root,
                )
            )

    def test_the_component_decides_when_no_registry_can_be_read(self) -> None:
        for present in (True, False):
            with self.subTest(component_present=present):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self._install(tmp, registry=None, component=present)
                    self.assertIsNone(keel_features.registry_features(root))
                    self.assertEqual(
                        keel_features.feature_absent(
                            "knowledge",
                            component=keel_session.KNOWLEDGE_COMPONENT,
                            root=root,
                        ),
                        not present,
                    )

    def test_an_unreadable_registry_is_undecidable_never_empty(self) -> None:
        """Convention 7: "could not read the registry" must not be the same
        value as "this installation carries no features"."""
        for registry in ("not json {{{", {"v": 1, "features": {}}, {"v": 1}, "[]"):
            with self.subTest(registry=registry):
                with tempfile.TemporaryDirectory() as tmp:
                    root = self._install(tmp, registry=registry)
                    self.assertIsNone(keel_features.registry_features(root))

    def test_absence_is_never_reported_without_evidence(self) -> None:
        """No registry and no component to probe: the answer is "not decidably
        absent", so no caller declines on a guess."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._install(tmp, registry=None)
            self.assertFalse(keel_features.feature_absent("knowledge", root=root))

    def test_the_real_installation_carries_every_declared_feature(self) -> None:
        declared = keel_features.registry_features()
        source = json.loads(
            (REPO_ROOT / keel_checks.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )["features"]
        self.assertEqual(declared, frozenset(source))
        for feature in source:
            with self.subTest(feature=feature):
                self.assertFalse(keel_features.feature_absent(feature))

    def test_the_install_root_is_the_installation_not_the_cwd(self) -> None:
        self.assertEqual(keel_features.install_root(), REPO_ROOT)
        self.assertEqual(
            keel_features.registry_path(),
            REPO_ROOT / keel_checks.FEATURES_REGISTRY,
        )

    def test_the_decline_names_the_request_and_the_missing_feature(self) -> None:
        self.assertEqual(
            keel_features.decline("chart", "knowledge"),
            "chart needs the knowledge feature, which this edition does not include",
        )

    def test_a_decline_with_a_hole_in_it_raises(self) -> None:
        for what, feature in (("", "knowledge"), ("chart", "   "), ("", "")):
            with self.subTest(what=what, feature=feature):
                with self.assertRaises(ValueError):
                    keel_features.decline(what, feature)

    def test_it_declares_its_failure_policy(self) -> None:
        source = (REPO_ROOT / "hooks" / "keel_features.py").read_text(encoding="utf-8")
        self.assertIn("FAIL-CLOSED", source.split('"""')[1])


class TestOwnershipMatchesTheRegistry(unittest.TestCase):
    """The feature each touch point names is the feature the registry says
    owns it - nothing about ownership is restated by hand and left to drift."""

    def setUp(self) -> None:
        self.features = json.loads(
            (REPO_ROOT / keel_checks.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )["features"]

    def test_every_subcommand_names_the_feature_owning_its_module(self) -> None:
        for name, spec in keel.COMMANDS.items():
            with self.subTest(command=name):
                self.assertIn(spec.feature, self.features)
                self.assertIn(
                    spec.component,
                    self.features[spec.feature]["components"],
                    f"{name} claims {spec.feature}, which does not own {spec.component}",
                )
                self.assertTrue((REPO_ROOT / spec.component).is_file())

    def test_the_injector_names_the_feature_owning_its_component(self) -> None:
        self.assertIn(keel_session.KNOWLEDGE_FEATURE, self.features)
        self.assertIn(
            keel_session.KNOWLEDGE_COMPONENT,
            self.features[keel_session.KNOWLEDGE_FEATURE]["components"],
        )

    def test_the_presence_helper_itself_is_kernel_owned(self) -> None:
        """It answers the question for every edition, so it must ship in each."""
        self.assertIn("hooks/keel_features.py", self.features["kernel"]["components"])


class TestFullTreeBehaviourIsUnchanged(unittest.TestCase):
    """The other direction: with every feature installed, nothing declines."""

    def test_every_subcommand_resolves_to_a_callable(self) -> None:
        for name in keel.COMMANDS:
            with self.subTest(command=name):
                self.assertTrue(callable(keel.load(name)))

    def test_the_usage_screen_declines_nothing_and_names_everything(self) -> None:
        usage = keel.usage()
        self.assertNotIn("does not include", usage)
        for name in keel.COMMANDS:
            with self.subTest(command=name):
                self.assertIn(name, usage)

    def test_a_knowledge_subcommand_still_runs(self) -> None:
        # The report itself is captured: this asserts the exit code, and a
        # test suite's output is not the place for a search result.
        with tempfile.TemporaryDirectory() as tmp, io.StringIO() as sink:
            with redirect_stdout(sink):
                code = keel.main(["chart", "--project", tmp, "anything"])
            self.assertEqual(code, 0, sink.getvalue())

    def test_the_injector_offers_no_notice(self) -> None:
        self.assertEqual(keel_session.knowledge_notice(), "")

    def test_the_notice_is_fail_open_and_never_silent(self) -> None:
        """The hook's declared policy, observed on the new path: a registry read
        that raises costs one stderr line and no notice - never the session.

        Patched on ``keel_features`` rather than on ``keel_session``, because the
        injector imports the helper INSIDE ``knowledge_notice`` (so a broken
        ``keel_features`` cannot reach the hook launcher) and therefore reads the
        attribute at call time.
        """
        original = keel_features.feature_absent

        def boom(*args: object, **kwargs: object) -> bool:
            raise OSError("deliberate fault")

        keel_features.feature_absent = boom
        try:
            with io.StringIO() as sink:
                with redirect_stderr(sink):
                    notice = keel_session.knowledge_notice()
                self.assertEqual(notice, "")
                self.assertIn("deliberate fault", sink.getvalue())
        finally:
            keel_features.feature_absent = original


class TestTrimmedBundleDeclines(unittest.TestCase):
    """A real ``keel-core`` bundle - kernel plus orchestration, no knowledge
    and no viewer - generated once for this class because generation is the
    slow part and every assertion below only reads the bundle."""

    _scratch: tempfile.TemporaryDirectory
    bundle: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._scratch = tempfile.TemporaryDirectory()
        root = Path(cls._scratch.name)
        cls.bundle, _ = keel_gen_editions.generate_edition(
            "keel-core",
            REPO_ROOT,
            root / "editions",
            keel_gen_editions.load_registry(REPO_ROOT),
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._scratch.cleanup()

    def _project(self, tmp: str) -> Path:
        """A temporary armed project for the bundle's tools to point at."""
        project = Path(tmp) / "project"
        policy = project / ".keel" / "keel-policy.md"
        policy.parent.mkdir(parents=True)
        policy.write_text("---\ntier: 2\n---\n\n# policy\n", encoding="utf-8")
        return project

    def _cli(self, args: list[str], tmp: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-B", str(self.bundle / "scripts" / "keel.py"), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(self.bundle),
            env=clean_env(Path(tmp)),
            timeout=120,
            check=False,
        )

    def test_the_premise_the_bundle_carries_no_knowledge_or_viewer_module(self) -> None:
        for absent in ("keel_index.py", "keel_chart.py", "keel_dashboard.py"):
            with self.subTest(module=absent):
                self.assertFalse((self.bundle / "scripts" / absent).exists())
        self.assertTrue((self.bundle / "scripts" / "keel.py").is_file())
        self.assertTrue((self.bundle / "hooks" / "keel_features.py").is_file())
        shipped = json.loads(
            (self.bundle / keel_checks.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )["features"]
        self.assertEqual(sorted(shipped), ["kernel", "orchestration"])

    def test_a_subcommand_of_an_absent_feature_declines_by_name(self) -> None:
        cases = {"chart": "knowledge", "index": "knowledge", "dashboard": "viewer"}
        for command, feature in cases.items():
            with self.subTest(command=command):
                with tempfile.TemporaryDirectory() as tmp:
                    result = self._cli([command, "--help"], tmp)
                    self.assertEqual(
                        result.returncode,
                        keel.DECLINE_EXIT_CODE,
                        result.stdout + result.stderr,
                    )
                    self.assertEqual(
                        result.stderr.strip(),
                        f"keel: {keel_features.decline(command, feature)}",
                    )
                    self.assertEqual(result.stdout, "", "a decline is not a report")

    def test_the_kernel_commands_still_run(self) -> None:
        """The whole point: one absent feature costs one subcommand, never the
        CLI. ``survey`` is the report that must survive, because it is what a
        user runs to find out what they have."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            survey = self._cli(["survey", "--project", str(project)], tmp)
            self.assertEqual(survey.returncode, 0, survey.stdout + survey.stderr)
            self.assertIn("KEEL SURVEY", survey.stdout)
            records = self._cli(["records", "--project", str(project)], tmp)
            self.assertEqual(records.returncode, 0, records.stdout + records.stderr)

    def test_the_usage_screen_declines_in_place_of_a_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._cli(["--help"], tmp)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(
                keel_features.decline("chart", "knowledge"), result.stdout
            )
            self.assertIn(
                keel_features.decline("dashboard", "viewer"), result.stdout
            )
            # The kernel commands keep their own generated summaries.
            self.assertIn("survey", result.stdout)
            self.assertNotIn("survey needs", result.stdout)

    def test_session_injection_names_the_missing_feature(self) -> None:
        """The digest's own channel carries the absence: stdout of SessionStart
        is the injected context, and the exit code stays 0 (fail-open)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp)
            payload = json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": "abcdef123456",
                    "cwd": str(project),
                }
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(self.bundle / "hooks" / "keel_hook.py"),
                    "session",
                ],
                input=payload,
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(project),
                env=clean_env(Path(tmp)),
                timeout=120,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertTrue(lines[0].startswith("[keel] This project runs under"), lines)
            expected = "[keel] " + keel_features.decline(
                keel_session.KNOWLEDGE_SUBJECT, keel_session.KNOWLEDGE_FEATURE
            )
            self.assertIn(expected, lines)
            self.assertEqual(sum(line == expected for line in lines), 1, lines)
            # The index header is what the block would have opened with; the
            # decline replaces it rather than joining it.
            self.assertNotIn("knowledge index:", result.stdout)


class _FailingImporter:
    """Stands in for ``importlib`` inside ``keel``, failing every import.

    The point of the simulation is the NAME the failure carries: a module that
    is present and imports a dependency that is not there raises
    ``ModuleNotFoundError`` for the DEPENDENCY, and that name is the only
    evidence ``keel.trimmed_away`` gets to read.
    """

    def __init__(self, missing: str | None) -> None:
        self.missing = missing

    def import_module(self, name: str) -> object:
        raise ModuleNotFoundError(f"No module named {self.missing!r}", name=self.missing)


class TestABrokenModuleIsNotATrimmedEdition(unittest.TestCase):
    """A present-but-broken module must never masquerade as a trimmed edition:
    "included but broken" and "not included" are different facts, and only the
    second one is an edition boundary (scripts/keel.py ``trimmed_away``)."""

    CHART = keel.COMMANDS["chart"]

    @contextmanager
    def _import_fails_for(self, missing: str | None) -> Iterator[None]:
        """``keel``'s importer, failing with one chosen missing-module name."""
        original = keel.importlib
        keel.importlib = _FailingImporter(missing)
        try:
            yield
        finally:
            keel.importlib = original

    @contextmanager
    def _declared(self, modules: frozenset[str] | None) -> Iterator[None]:
        """What the LOCAL registry declares, as ``keel`` reads it."""
        original = keel.declared_modules
        keel.declared_modules = lambda *args, **kwargs: modules
        try:
            yield
        finally:
            keel.declared_modules = original

    def test_the_registry_declares_every_module_it_ships(self) -> None:
        declared = keel_features.declared_modules()
        source = json.loads(
            (REPO_ROOT / keel_checks.FEATURES_REGISTRY).read_text(encoding="utf-8")
        )["features"]
        expected = {
            component.rsplit("/", 1)[-1][: -len(".py")]
            for spec in source.values()
            for component in spec["components"]
            if component.endswith(".py")
        }
        self.assertEqual(declared, frozenset(expected))
        for module in ("keel", "keel_gate", "keel_index", "keel_chart", "keel_dashboard"):
            with self.subTest(module=module):
                self.assertIn(module, declared)

    def test_a_registry_that_cannot_be_read_declares_nothing_decidable(self) -> None:
        """UNDECIDABLE, never an empty set - the same contract
        ``registry_features`` keeps, because the caller's next move is the same:
        do not read a failed import as an edition boundary at all."""
        cases: tuple[dict | str, ...] = (
            "not json {{{",
            {"v": 1},
            {"v": 1, "features": {}},
            {"v": 1, "features": {"kernel": {"layer": "core", "components": []}}},
            {"v": 1, "features": {"kernel": {"layer": "core", "components": ["skills/log/"]}}},
        )
        for registry in cases:
            with self.subTest(registry=registry):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    path = root / keel_checks.FEATURES_REGISTRY
                    path.parent.mkdir(parents=True, exist_ok=True)
                    text = registry if isinstance(registry, str) else json.dumps(registry)
                    path.write_text(text, encoding="utf-8")
                    self.assertIsNone(keel_features.declared_modules(root))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(keel_features.declared_modules(Path(tmp)))

    def test_only_keels_own_module_names_can_be_edition_shaped(self) -> None:
        self.assertTrue(keel.is_keel_module("keel"))
        self.assertTrue(keel.is_keel_module("keel_index"))
        self.assertFalse(keel.is_keel_module("sqlite3"))
        self.assertFalse(keel.is_keel_module("kernel"))

    def test_a_dependency_of_a_present_module_is_a_crash_not_a_decline(self) -> None:
        """Finding 1's case: ``keel_chart.py`` IS installed, and its import chain
        fails on something else. Nothing about that says "trimmed edition", so
        the ModuleNotFoundError propagates as the crash it is - a damaged install
        the user must be told about.

        Three shapes of "something else": a standard-library name, a kernel
        module (which every edition carries, so a missing one is damage), and a
        knowledge module the LIVE registry declares - present here, therefore
        broken rather than absent. Plus an exception carrying no name at all.
        """
        for missing in ("sqlite3", "json", "keel_gate", "keel_index", None):
            with self.subTest(missing=missing):
                self.assertFalse(keel.trimmed_away(missing, self.CHART))
                with self._import_fails_for(missing):
                    with self.assertRaises(ModuleNotFoundError):
                        keel.load("chart")

    def test_the_crash_is_not_dressed_up_by_the_dispatcher_either(self) -> None:
        """``main`` catches only ``FeatureAbsent``, so the damaged install
        surfaces instead of exiting 2 with a decline nobody can act on."""
        with self._import_fails_for("sqlite3"):
            with self.assertRaises(ModuleNotFoundError):
                keel.main(["chart", "anything"])

    def test_the_commands_own_missing_module_is_the_edition_boundary(self) -> None:
        """The first trimming-shaped case: the module this edition would have
        dropped along the seam is the one that is gone."""
        self.assertTrue(keel.trimmed_away(self.CHART.module, self.CHART))
        with self._import_fails_for(self.CHART.module):
            with self.assertRaises(keel.FeatureAbsent) as caught:
                keel.load("chart")
        self.assertEqual(
            str(caught.exception), keel_features.decline("chart", "knowledge")
        )

    def test_a_module_the_local_registry_does_not_declare_is_the_boundary_too(self) -> None:
        """The second: ``keel_chart`` imports ``keel_index``, so in a genuinely
        trimmed bundle the failure arrives under a DIFFERENT name than the
        subcommand's own module. A scoped registry that does not declare that
        name is positive evidence an absent feature owns it."""
        trimmed = frozenset({"keel", "keel_survey", "keel_gate", "keel_features"})
        with self._declared(trimmed):
            self.assertTrue(keel.trimmed_away("keel_index", self.CHART))
            with self._import_fails_for("keel_index"):
                with self.assertRaises(keel.FeatureAbsent) as caught:
                    keel.load("chart")
        self.assertEqual(
            str(caught.exception), keel_features.decline("chart", "knowledge")
        )

    def test_an_undecidable_registry_never_reads_as_trimming(self) -> None:
        """No registry to read is not evidence of absence: the import failure
        propagates rather than being guessed into a decline."""
        with self._declared(None):
            self.assertFalse(keel.trimmed_away("keel_index", self.CHART))
            with self._import_fails_for("keel_index"):
                with self.assertRaises(ModuleNotFoundError):
                    keel.load("chart")

    def test_a_kernel_subcommand_is_never_declined_whatever_is_missing(self) -> None:
        """Unchanged, and pinned beside the new rule: every edition carries
        kernel, so a kernel import failure is damage by construction."""
        for missing in ("keel_survey", "sqlite3", None):
            with self.subTest(missing=missing):
                with self._import_fails_for(missing):
                    with self.assertRaises(ModuleNotFoundError):
                        keel.load("survey")


class TestABrokenFeaturesHelperCannotReachTheLauncher(unittest.TestCase):
    """Finding 2: ``hooks/keel_hook.py`` imports ``keel_session`` to reach
    ``gate`` and ``stop``, so anything ``keel_session`` imports at module scope
    is imported by the launcher too - upstream of the launcher's own fail-open
    handler. A defect in ``keel_features`` may cost the edition notice; it may
    not cost the session its gates."""

    _CHAIN = ("keel_features", "keel_session", "keel_hook")

    @contextmanager
    def _features_unimportable(self) -> Iterator[None]:
        """``keel_features`` present on disk but unimportable, the whole block.

        ``None`` in ``sys.modules`` is the interpreter's own "this import is
        halted" marker, so every fresh ``import keel_features`` raises exactly as
        a syntax error in the file would. The modules that reach for it are
        evicted from the cache first - re-imported inside the block rather than
        read from it, or the simulation would prove nothing.
        """
        saved = {name: sys.modules.get(name) for name in self._CHAIN}
        for name in ("keel_session", "keel_hook"):
            sys.modules.pop(name, None)
        sys.modules["keel_features"] = None
        try:
            yield
        finally:
            for name, module in saved.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    def test_the_premise_the_helper_is_importable_when_it_is_not_poisoned(self) -> None:
        self.assertIsNotNone(importlib.import_module("keel_features"))
        with self._features_unimportable():
            with self.assertRaises(ImportError):
                importlib.import_module("keel_features")
        self.assertIsNotNone(importlib.import_module("keel_features"))

    def test_the_launcher_still_imports_and_still_dispatches(self) -> None:
        with self._features_unimportable():
            launcher = importlib.import_module("keel_hook")
            for subcommand in ("gate", "stop", "session", "capture", "spike"):
                with self.subTest(subcommand=subcommand):
                    self.assertTrue(callable(launcher.SUBCOMMANDS[subcommand]))
            # A payload naming no write and no shell is not the gate's business,
            # and it reaches that verdict with the helper broken.
            self.assertEqual(launcher.SUBCOMMANDS["gate"]({}), 0)

    def test_the_injector_completes_fail_open_with_one_stderr_line(self) -> None:
        """The notice degrades exactly as a broken ``keel_index`` does today: no
        notice, one visible line naming the fault, exit 0, plan line intact."""
        from keel_events import KeelEvent  # noqa: PLC0415 - path set at import time

        with self._features_unimportable():
            session = importlib.import_module("keel_session")
            with tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp)
                (project / ".keel").mkdir()
                event = KeelEvent(
                    kind="session_start", cwd=project, session_id="abcdef123456"
                )
                with io.StringIO() as err:
                    with redirect_stderr(err):
                        self.assertEqual(session.knowledge_notice(), "")
                    lines = err.getvalue().splitlines()
                self.assertEqual(len(lines), 1, lines)
                self.assertIn("could not consult the feature registry", lines[0])
                self.assertIn("keel_features", lines[0])
                # None-poisoning arrives as ModuleNotFoundError; a syntax error
                # in the file would arrive as SyntaxError. Either way the type
                # and the message are on the line, which is what "never silent"
                # means here.
                self.assertRegex(lines[0], r"(ModuleNotFound|Import)Error")
                # ``session`` was just re-imported fresh (the module was
                # popped from ``sys.modules`` above), so it is NOT the same
                # object ``keel_registry_guard`` patches - stubbed directly
                # here instead, or this real ``session_start`` would feed
                # keel's user-global fleet registry (T227) for real.
                session.registry_write = lambda cwd, home=None: None
                with io.StringIO() as out, io.StringIO() as err:
                    with redirect_stderr(err):
                        code = session.run(event, stdout=out, env={})
                    diagnostics = err.getvalue()
                    self.assertEqual(code, 0, diagnostics)
                    self.assertIn(
                        "[keel] This project runs under", out.getvalue(), diagnostics
                    )
                    self.assertEqual(
                        sum(
                            "could not consult the feature registry" in line
                            for line in diagnostics.splitlines()
                        ),
                        1,
                        diagnostics,
                    )
                    self.assertNotIn("does not include", out.getvalue())


if __name__ == "__main__":
    unittest.main()
