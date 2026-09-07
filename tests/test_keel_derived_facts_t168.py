#!/usr/bin/env python3
"""T168 - the four facts keel used to ASSERT are now derived from the tree.

Contract
--------
Reads   : ``hooks/keel_features.py`` (the fingerprint and the edition
          derivation), ``scripts/keel_survey.py`` (the install-record
          resolution, the friction band and the report it renders) and
          ``scripts/keel_orchestration_dashboard.py`` - the last as a module
          for its Python half and as TEXT for its page half. Every case that
          asserts a digest, an edition, an install state or a friction figure
          builds its own fixture tree, its own fixture home and its own
          fixture project: a value inherited from the machine running the
          suite would be an ambient fact rather than a test. This
          repository's own tree is read only where the subject IS this
          installation.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers, and why each half exists
------------------------------------------
An external assessment on 2026-08-18 found four places keel stated a fact it
could have measured. Each was verified against this tree before the fix, and
each is pinned here in BOTH directions:

1. VERSION. Two materially different trees - an installed cache snapshot and a
   working tree differing in 43 files - both reported
   ``plugin 0.6.0 | changelog top 0.6.0 (agree)``, because that line compares
   two strings to each other. ``component_fingerprint`` digests the CONTENTS of
   the files the feature registry names, so two identical trees agree and one
   changed file disagrees. The missing-component case matters most: a trimmed
   tree must not fingerprint as a whole one.
2. EDITION. ``edition_label`` derives the edition from ``plugin.json``'s
   ``name`` alone, and its own docstring admitted it - the tree carried all
   five reviewer agents (feature ``review``, layer ``govern``) and reported
   ``standard``. ``derived_edition`` reads the layers actually present, and the
   manifest's claim is still printed, separately, when it disagrees.
3. INSTALL RECORD. The harness's record named an ``installPath`` that did not
   exist while the tree actually loaded carried ``.orphaned_at`` and
   ``.in_use``, and the survey checked neither. All four states are fixtured
   here - agree, missing path, orphaned, no record - plus the two faults that
   must not crash a report running on an adopter's machine: an unreadable
   record and a record whose shape keel does not recognise.
4. FRICTION. 365 bypasses against 4 denials ever printed as two neutral lines,
   with nothing saying that 308 of them were writes into ``hooks/`` under
   self-hosting. The WARN band is asserted in both directions, and the
   composition is asserted to name its head AND count its tail.

What a Python suite cannot do here
----------------------------------
The board's stale-page marker RUNS IN THE PAGE, so what this file pins is that
the page source carries the marker logic and that the Python half hands it a
correct verdict - the same honest boundary
``tests/test_keel_dashboard_t156.py`` states for the resume-persona join: this
suite cannot execute the page's JavaScript, and no assertion here should be
read as evidence that a browser drew anything. The comparison itself is
Python (``served_code``) and IS executed, in all three of its states, which is
where a wrong answer would come from.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding, except where bytes are the subject. A backslash is built with
``chr(92)`` rather than typed, because a ``[\\/]`` class collapses through a
heredoc into one that matches no Windows path at all - a defect this
repository has already paid for once.
"""

from __future__ import annotations

import copy
import datetime
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_features  # noqa: E402
import keel_orchestration_dashboard as board  # noqa: E402
import keel_survey  # noqa: E402

BOARD_SOURCE = (REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py").read_text(
    encoding="utf-8"
)

#: The module's pristine seams, captured at import before any case swaps one
#: in. Restoring from these rather than from a value read inside a test means a
#: case that fails half way cannot leave a fake stat behind for the next one.
_REAL_STAT = keel_features._stat
_REAL_WALK = keel_features._walk_tree

#: The backslash, built rather than typed - see the module docstring.
BACKSLASH = chr(92)

#: A fixture registry shaped like the real one: five features across the four
#: layers of the edition ladder, each owning components this file creates. The
#: registry names itself, exactly as the shipped one does, so the digest covers
#: the document that decides what the digest is over.
FIXTURE_FEATURES: dict[str, dict] = {
    "kernel": {
        "layer": "core",
        "components": ["hooks/gate.py", "scripts/keel-features.json"],
        "requires": [],
    },
    "orchestration": {
        "layer": "core",
        "components": ["agents/executor.md", "skills/lay/"],
        "requires": ["kernel"],
    },
    "knowledge": {
        "layer": "standard",
        "components": ["scripts/index.py"],
        "requires": ["kernel"],
    },
    "review": {
        "layer": "govern",
        "components": ["agents/reviewer-correctness.md"],
        "requires": ["orchestration"],
    },
    "viewer": {
        "layer": "fleet",
        "components": ["scripts/viewer.py"],
        "requires": ["kernel"],
    },
}

#: Which features each fixture edition carries, so a case states the tree it
#: means rather than a list of paths.
FIXTURE_EDITIONS: dict[str, tuple[str, ...]] = {
    "core": ("kernel", "orchestration"),
    "standard": ("kernel", "orchestration", "knowledge"),
    "govern": ("kernel", "orchestration", "knowledge", "review"),
    "fleet": ("kernel", "orchestration", "knowledge", "review", "viewer"),
}


def _iso(seconds_ago: float) -> str:
    """A UTC stamp in the shape keel writes, that many seconds in the past."""
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_tree(
    root: Path,
    features: dict[str, dict] | None = None,
    carried: tuple[str, ...] | None = None,
    contents: dict[str, str] | None = None,
) -> Path:
    """A synthetic installation root that OWNS its premises.

    ``features`` is the registry document's feature table (defaults to
    :data:`FIXTURE_FEATURES`); ``carried`` names the features whose component
    files are actually created, so "the registry declares it and the disk does
    not carry it" is a state a case can state directly; ``contents`` overrides
    the text written into a named component path.
    """
    features = FIXTURE_FEATURES if features is None else features
    carried = tuple(features) if carried is None else carried
    contents = contents or {}
    registry = root / "scripts" / "keel-features.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps({"v": 1, "features": features}, indent=2), encoding="utf-8"
    )
    for name in carried:
        for component in features[name].get("components", []):
            relative = component.replace(BACKSLASH, "/").strip("/")
            if relative == "scripts/keel-features.json":
                continue  # written above; it is its own component
            target = root / relative
            if component.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                (target / "SKILL.md").write_text(
                    contents.get(component, f"# {relative}\n"), encoding="utf-8"
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                contents.get(component, f"# {relative}\n"), encoding="utf-8"
            )
    return root


def fixture_home(base: Path, record: object | str | None) -> Path:
    """A home directory holding exactly the install record a case needs.

    ``record`` is a document, raw text (for the unreadable case), or ``None``
    for a machine whose harness keeps no record at all - which is the normal
    state of an adopter's checkout and must never be an error.
    """
    home = base / "fixture-home"
    (home / ".claude" / "plugins").mkdir(parents=True, exist_ok=True)
    if record is not None:
        text = record if isinstance(record, str) else json.dumps(record, indent=2)
        keel_survey.install_record_path(home).write_text(text, encoding="utf-8")
    return home


def install_document(
    key: str, install_path: Path | str, version: str = "0.6.0"
) -> dict:
    """One harness install record, in the shape version 2 of that file uses."""
    return {
        "version": 2,
        "plugins": {
            key: [
                {
                    "scope": "user",
                    "installPath": str(install_path),
                    "version": version,
                    "installedAt": "2026-08-10T22:45:51.928Z",
                }
            ]
        },
    }


def fixture_project(base: Path, lines: list[dict]) -> Path:
    """An adopted project carrying exactly the audit lines a case needs."""
    project = base / "fixture-project"
    (project / ".keel" / "audit").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "audit" / "keel-audit.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    return project


def bypass(target: object, seconds_ago: float = 60.0) -> dict:
    """One ``gate_bypass`` audit line aimed at ``target``."""
    return {
        "v": 1,
        "ts": _iso(seconds_ago),
        "event": "gate_bypass",
        "gate": "policy_lock",
        "session": "s-1",
        "detail": {"target": target, "switch": "KEEL_OVERRIDE"},
    }


def denial(target: str = "hooks/keel_gate.py", seconds_ago: float = 60.0) -> dict:
    """One policy-lock ``gate_block`` audit line."""
    return {
        "v": 1,
        "ts": _iso(seconds_ago),
        "event": "gate_block",
        "gate": "policy_lock",
        "session": "s-1",
        "detail": {"target": target},
    }


class TestComponentFingerprintIdentifiesTheTree(unittest.TestCase):
    """Finding 3: one version string, two different trees, nothing said so."""

    def test_two_identical_trees_fingerprint_the_same(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            left = build_tree(base / "left")
            right = build_tree(base / "right")
            first = keel_features.component_fingerprint(left)
            second = keel_features.component_fingerprint(right)
        self.assertTrue(first.known)
        self.assertEqual(first.digest, second.digest)
        self.assertEqual(first.files, second.files)
        self.assertEqual(len(first.digest), keel_features.FINGERPRINT_HEX_CHARS)

    def test_one_changed_component_changes_the_fingerprint(self) -> None:
        """The whole point: the digest is over CONTENT, so a tree that edited
        one gate file is no longer the tree that did not."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            left = build_tree(base / "left")
            right = build_tree(
                base / "right", contents={"hooks/gate.py": "# changed\n"}
            )
            first = keel_features.component_fingerprint(left)
            second = keel_features.component_fingerprint(right)
        self.assertNotEqual(first.digest, second.digest)

    def test_a_file_inside_a_directory_component_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            left = build_tree(base / "left")
            right = build_tree(base / "right", contents={"skills/lay/": "# other\n"})
            self.assertNotEqual(
                keel_features.component_fingerprint(left).digest,
                keel_features.component_fingerprint(right).digest,
            )

    def test_a_trimmed_tree_never_fingerprints_as_a_whole_one(self) -> None:
        """A missing component is folded into the digest AND listed, so a
        report cannot print a digest that looks like health."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            whole = keel_features.component_fingerprint(build_tree(base / "whole"))
            trimmed = keel_features.component_fingerprint(
                build_tree(base / "trimmed", carried=FIXTURE_EDITIONS["standard"])
            )
        self.assertNotEqual(whole.digest, trimmed.digest)
        self.assertEqual(whole.missing, ())
        self.assertIn("agents/reviewer-correctness.md", trimmed.missing)
        self.assertIn("scripts/viewer.py", trimmed.missing)
        self.assertIn("MISSING", trimmed.summary())
        self.assertNotIn("MISSING", whole.summary())

    def test_an_unreadable_registry_is_undecidable_never_a_digest(self) -> None:
        """Convention 7: "could not read the registry" must not be printable as
        a fingerprint, because a fingerprint is read as evidence."""
        for text in ("not json {{{", '{"v": 1}', '{"v": 1, "features": {}}'):
            with self.subTest(registry=text):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    registry = root / "scripts" / "keel-features.json"
                    registry.parent.mkdir(parents=True)
                    registry.write_text(text, encoding="utf-8")
                    fingerprint = keel_features.component_fingerprint(root)
                self.assertEqual(fingerprint.digest, "")
                self.assertFalse(fingerprint.known)
                self.assertIn("no readable feature registry", fingerprint.note)
                self.assertIn("unavailable", fingerprint.summary())

    def test_an_absent_tree_is_undecidable_rather_than_a_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fingerprint = keel_features.component_fingerprint(Path(tmp) / "nowhere")
        self.assertFalse(fingerprint.known)

    def test_line_endings_are_not_a_difference_in_content(self) -> None:
        """A checkout policy is not a different tree; the docstring says so and
        this is what makes that claim true."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            left = build_tree(base / "left")
            right = build_tree(base / "right")
            (right / "hooks" / "gate.py").write_bytes(b"# hooks/gate.py\r\n")
            self.assertEqual(
                keel_features.component_fingerprint(left).digest,
                keel_features.component_fingerprint(right).digest,
            )

    def test_bytecode_and_caches_are_not_part_of_the_tree(self) -> None:
        """A digest that moved the first time something was imported would
        report two identical trees as different."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            left = build_tree(base / "left")
            right = build_tree(base / "right")
            cache = right / "skills" / "lay" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "x.cpython-310.pyc").write_bytes(b"\x00\x01")
            (right / "skills" / "lay" / "stray.pyc").write_bytes(b"\x00\x02")
            self.assertEqual(
                keel_features.component_fingerprint(left).digest,
                keel_features.component_fingerprint(right).digest,
            )

    def test_this_installation_can_be_fingerprinted(self) -> None:
        fingerprint = keel_features.component_fingerprint()
        self.assertTrue(fingerprint.known)
        self.assertEqual(fingerprint.missing, ())
        self.assertEqual(fingerprint.unreadable, ())
        self.assertGreater(fingerprint.files, 30)

    def test_one_files_digest_answers_for_that_file_alone(self) -> None:
        """``path_digest`` covers what the component set cannot: a file that is
        not a registry component but whose staleness matters (the board)."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "a.py"
            second = base / "b.py"
            first.write_text("# same\n", encoding="utf-8")
            second.write_text("# same\n", encoding="utf-8")
            self.assertEqual(
                keel_features.path_digest(first), keel_features.path_digest(second)
            )
            second.write_text("# different\n", encoding="utf-8")
            self.assertNotEqual(
                keel_features.path_digest(first), keel_features.path_digest(second)
            )
            self.assertEqual(keel_features.path_digest(base / "gone.py"), "")


class TestEditionIsDerivedFromTheTree(unittest.TestCase):
    """Finding 6: the edition was ``plugin.json``'s ``name``, and nothing else."""

    def _derive(self, tmp: str, edition: str) -> keel_features.DerivedEdition:
        root = build_tree(Path(tmp), carried=FIXTURE_EDITIONS[edition])
        return keel_features.derived_edition(root)

    def test_each_edition_on_the_ladder_derives_to_its_own_layer(self) -> None:
        for edition in FIXTURE_EDITIONS:
            with self.subTest(edition=edition):
                with tempfile.TemporaryDirectory() as tmp:
                    derived = self._derive(tmp, edition)
                self.assertEqual(derived.layer, edition)
                self.assertTrue(derived.known)
                self.assertEqual(derived.note, "")

    def test_the_govern_components_are_what_makes_it_govern(self) -> None:
        """The measured case: a tree carrying the reviewer agents reported
        ``standard`` because only the manifest was ever consulted."""
        with tempfile.TemporaryDirectory() as tmp:
            without = self._derive(tmp, "standard")
        with tempfile.TemporaryDirectory() as tmp:
            with_review = self._derive(tmp, "govern")
        self.assertEqual(without.layer, "standard")
        self.assertEqual(with_review.layer, "govern")

    def test_a_gap_in_the_ladder_is_an_unrecognized_mix(self) -> None:
        """govern present over a missing standard is no edition at all, and is
        reported as what was found rather than rounded to one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(
                Path(tmp), carried=("kernel", "orchestration", "review")
            )
            derived = keel_features.derived_edition(root)
        self.assertEqual(derived.layer, "")
        self.assertFalse(derived.known)
        self.assertIn("core", derived.note)
        found = derived.found_summary()
        self.assertIn("present: kernel, orchestration, review", found)
        self.assertIn("absent: knowledge", found)

    def test_a_half_copied_feature_is_partial_and_never_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp), carried=FIXTURE_EDITIONS["fleet"])
            (root / "agents" / "executor.md").unlink()
            derived = keel_features.derived_edition(root)
        self.assertEqual(derived.layer, "")
        self.assertIn("orchestration (1 of 2)", derived.found_summary())

    def test_a_layer_outside_the_ladder_is_reported_not_guessed(self) -> None:
        features = copy.deepcopy(FIXTURE_FEATURES)
        features["fork"] = {
            "layer": "bespoke",
            "components": ["scripts/fork.py"],
            "requires": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp), features=features)
            derived = keel_features.derived_edition(root)
        self.assertEqual(derived.layer, "")
        self.assertIn("bespoke", derived.note)

    def test_an_unreadable_registry_derives_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            derived = keel_features.derived_edition(Path(tmp))
        self.assertEqual(derived.layer, "")
        self.assertIn("no readable feature registry", derived.note)

    def test_the_manifest_half_keeps_its_own_behaviour(self) -> None:
        """The manifest's claim is still reported, with the unrecognized-name
        wording ``edition_label`` already had - it is the other half of the
        disagreement, not a value to be replaced."""
        self.assertEqual(keel_survey.edition_label("keel"), "standard")
        self.assertEqual(keel_survey.edition_label("keel-govern"), "govern")
        self.assertEqual(keel_survey.edition_label(""), "(none)")
        self.assertEqual(
            keel_survey.edition_label("something-else"), "something-else (unrecognized)"
        )

    def test_this_installation_reports_both_halves(self) -> None:
        version = keel_survey.version_report()
        self.assertEqual(version["edition"], "standard")  # the manifest's claim
        self.assertEqual(version["edition_derived"], "fleet")  # what is on disk
        self.assertTrue(version["components_digest"])
        self.assertEqual(version["components_missing"], [])


class TestTheRenderShowsWhatWasDerived(unittest.TestCase):
    """The report a human reads, over a fixture project and a fixture home."""

    def _render(self, lines: list[dict], record: object | None = None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = keel_survey.survey(
                fixture_project(base, lines), fixture_home(base, record)
            )
        return keel_survey.render(report)

    def test_the_version_line_carries_the_component_fingerprint(self) -> None:
        # KEEL ADDITION (T349): this used to read the real REPO_ROOT tree
        # TWICE - once inside ``_render`` (``survey`` calls ``version_report``,
        # which fingerprints ``keel_survey._REPO_ROOT``) and once again here -
        # and this armed session's own concurrent edits under hooks/,
        # scripts/, skills/, agents/ can move the tree between the two reads,
        # so the two digests could legitimately disagree without either
        # derivation being wrong. Pointing both reads at one static fixture
        # tree removes the race; what is asserted - the rendered line quotes
        # the SAME digest ``component_fingerprint`` derives - is unchanged.
        with tempfile.TemporaryDirectory() as tmp:
            fixture_root = build_tree(Path(tmp))
            original_repo_root = keel_survey._REPO_ROOT
            keel_survey._REPO_ROOT = fixture_root
            try:
                text = self._render([])
                digest = keel_features.component_fingerprint(fixture_root).digest
            finally:
                keel_survey._REPO_ROOT = original_repo_root
        line = [row for row in text.splitlines() if row.startswith("version :")][0]
        self.assertIn(f"components {digest}", line)

    def test_the_edition_line_names_the_manifest_when_they_disagree(self) -> None:
        text = self._render([])
        line = [row for row in text.splitlines() if row.startswith("edition :")][0]
        self.assertIn("fleet", line)
        self.assertIn("manifest says: standard", line)

    def test_a_home_with_no_install_record_says_so_in_one_line(self) -> None:
        text = self._render([])
        line = [row for row in text.splitlines() if row.startswith("install :")][0]
        self.assertIn("record not found", line)

    def test_the_friction_band_fires_when_bypasses_outrun_denials(self) -> None:
        text = self._render([bypass("hooks/keel_gate.py") for _ in range(3)])
        self.assertIn("WARN bypasses OUTRUN denials", text)
        self.assertIn("hooks/ 3", text)

    def test_the_band_is_silent_when_the_lock_is_doing_the_work(self) -> None:
        text = self._render([denial(), denial(), bypass("hooks/keel_gate.py")])
        self.assertNotIn("WARN bypasses OUTRUN", text)
        self.assertIn("composition of all 1 bypass(es)", text)

    def test_the_report_still_exits_zero_and_writes_nothing(self) -> None:
        """The survey's own contract, re-checked over the added sections: a
        report that changes what it surveys is not a report, and exit is 0
        whatever it found."""
        buffer = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = fixture_project(base, [bypass("hooks/x.py")])
            before = sorted(p.name for p in project.rglob("*"))
            with redirect_stdout(buffer):
                exit_code = keel_survey.main(["--project", str(project)])
            after = sorted(p.name for p in project.rglob("*"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(before, after)
        self.assertIn("KEEL SURVEY", buffer.getvalue())
        self.assertNotIn("could not complete the report", buffer.getvalue())


class TestTheSurveyChecksItsOwnInstallation(unittest.TestCase):
    """Finding 4: the record named a tree that was gone, and nothing looked."""

    def test_a_record_that_matches_reality_is_one_quiet_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "installed")
            home = fixture_home(base, install_document("keel@yard", root))
            report = keel_survey.install_report(
                home=home, root=root, manifest_name="keel", version="0.6.0"
            )
        self.assertEqual(report["state"], "agree")
        self.assertEqual(report["findings"], [])
        self.assertIn("record and reality agree", report["line"])

    def test_a_recorded_path_that_is_not_there_is_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "loaded")
            home = fixture_home(
                base, install_document("keel@yard", base / "renamed-away")
            )
            report = keel_survey.install_report(
                home=home, root=root, manifest_name="keel", version="0.6.0"
            )
        self.assertEqual(report["state"], "unrecorded-root")
        self.assertEqual(len(report["findings"]), 1)
        self.assertIn("DOES NOT EXIST", report["findings"][0])
        self.assertTrue(
            any("does not name" in note for note in report["notes"]), report["notes"]
        )

    def test_an_orphaned_tree_is_a_finding_that_names_the_timestamp(self) -> None:
        """The state measured 2026-08-18: keel running out of a directory its
        own harness had written off, with ``.in_use`` beside the marker."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "orphaned")
            (root / keel_survey.ORPHAN_MARKER).write_text(
                "1786433966251", encoding="utf-8"
            )
            (root / keel_survey.IN_USE_MARKER).write_text("", encoding="utf-8")
            home = fixture_home(base, install_document("keel@yard", root))
            report = keel_survey.install_report(
                home=home, root=root, manifest_name="keel", version="0.6.0"
            )
        self.assertTrue(report["orphaned_at"])
        self.assertIn("1786433966251", report["orphaned_at"])
        self.assertIn("2026-", report["orphaned_at"])
        self.assertTrue(report["in_use"])
        self.assertEqual(len(report["findings"]), 1)
        self.assertIn(".orphaned_at", report["findings"][0])
        self.assertIn("1786433966251", report["findings"][0])
        self.assertIn(".in_use", report["findings"][0])
        self.assertEqual(report["state"], "disagree")

    def test_a_marker_with_no_timestamp_still_names_the_orphaning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "orphaned")
            (root / keel_survey.ORPHAN_MARKER).write_text("", encoding="utf-8")
            report = keel_survey.install_report(
                home=fixture_home(base, None), root=root, manifest_name="keel"
            )
        self.assertIn("no timestamp in the marker", report["orphaned_at"])
        self.assertEqual(len(report["findings"]), 1)

    def test_no_install_record_at_all_is_one_stated_line(self) -> None:
        """The adopter's normal case: this must never be a crash, and never a
        silence either."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "checkout")
            report = keel_survey.install_report(
                home=fixture_home(base, None), root=root, manifest_name="keel"
            )
        self.assertEqual(report["state"], "not-found")
        self.assertIn("record not found", report["line"])
        self.assertEqual(report["findings"], [])

    def test_an_unreadable_record_says_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "checkout")
            report = keel_survey.install_report(
                home=fixture_home(base, "{not json"), root=root, manifest_name="keel"
            )
        self.assertEqual(report["state"], "unreadable")
        self.assertIn("record unreadable", report["line"])

    def test_a_record_shaped_differently_is_reported_not_assumed(self) -> None:
        for document in ({"version": 2}, {"plugins": []}, [1, 2, 3]):
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as tmp:
                    base = Path(tmp)
                    root = build_tree(base / "checkout")
                    report = keel_survey.install_report(
                        home=fixture_home(base, document),
                        root=root,
                        manifest_name="keel",
                    )
                self.assertEqual(report["state"], "malformed")
                self.assertIn("no 'plugins' table", report["line"])

    def test_a_record_naming_no_installation_of_ours_says_which_it_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "checkout")
            report = keel_survey.install_report(
                home=fixture_home(base, install_document("other@market", base / "x")),
                root=root,
                manifest_name="keel",
            )
        self.assertEqual(report["state"], "no-entry")
        self.assertIn("names no installation matching 'keel'", report["line"])
        self.assertEqual(report["findings"], [])

    def test_two_trees_claiming_one_version_is_a_finding(self) -> None:
        """The whole reason the fingerprint exists, stated as a fixture: the
        record names a tree that EXISTS, is not this one, and claims the same
        version - and its components differ."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            here = build_tree(base / "working")
            there = build_tree(
                base / "installed", contents={"hooks/gate.py": "# older\n"}
            )
            report = keel_survey.install_report(
                home=fixture_home(base, install_document("keel@yard", there)),
                root=here,
                manifest_name="keel",
                version="0.6.0",
            )
        self.assertTrue(
            any("two trees claim version 0.6.0" in f for f in report["findings"]),
            report["findings"],
        )

    def test_two_identical_trees_are_a_note_rather_than_a_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            here = build_tree(base / "working")
            there = build_tree(base / "installed")
            report = keel_survey.install_report(
                home=fixture_home(base, install_document("keel@yard", there)),
                root=here,
                manifest_name="keel",
                version="0.6.0",
            )
        self.assertEqual(report["findings"], [])
        self.assertTrue(
            any("same components" in note for note in report["notes"]), report["notes"]
        )

    def test_every_state_answers_with_a_line_and_a_documented_state(self) -> None:
        """Fail-soft, stated as a property rather than case by case: whatever
        it is handed, it returns a report with a state and a line."""
        documented = {
            "agree",
            "disagree",
            "unrecorded-root",
            "no-entry",
            "not-found",
            "unreadable",
            "malformed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = build_tree(base / "root")
            for record in (
                None,
                "{not json",
                {"version": 2},
                install_document("keel@yard", root),
                install_document("keel@yard", base / "gone"),
                {"version": 2, "plugins": {"keel@yard": "not a list"}},
                {"version": 2, "plugins": {"keel@yard": [{"installPath": None}]}},
            ):
                with self.subTest(record=record):
                    report = keel_survey.install_report(
                        home=fixture_home(base, record),
                        root=root,
                        manifest_name="keel",
                        version="0.6.0",
                    )
                    self.assertIn(report["state"], documented)
                    self.assertTrue(report["line"].strip())

    def test_the_real_machine_is_surveyed_without_raising(self) -> None:
        report = keel_survey.install_report(manifest_name="keel", version="0.6.0")
        self.assertTrue(report["line"].strip())
        self.assertIn("install", keel_survey.survey(REPO_ROOT))


class TestFrictionCarriesItsComposition(unittest.TestCase):
    """Finding 1: 365 bypasses printed neutrally, 308 of them into ``hooks/``."""

    def _friction(self, lines: list[dict]) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            return keel_survey.friction_report(fixture_project(Path(tmp), lines))

    def test_the_band_fires_only_when_bypasses_outrun_denials(self) -> None:
        cases = (
            ([bypass("hooks/a.py")], True),
            ([bypass("hooks/a.py"), denial()], False),
            ([bypass("hooks/a.py"), bypass("hooks/b.py"), denial()], True),
            ([denial(), denial()], False),
            ([], False),
        )
        for lines, expected in cases:
            with self.subTest(lines=len(lines), expected=expected):
                self.assertEqual(
                    self._friction(lines)["bypasses_outrun_denials"], expected
                )

    def test_the_window_decides_the_band_not_the_whole_record(self) -> None:
        """Denials from last month cannot excuse this week's bypasses, and
        bypasses from last month cannot raise this week's band."""
        old_bypasses = [bypass("hooks/a.py", seconds_ago=40 * 86400) for _ in range(9)]
        friction = self._friction(old_bypasses + [denial()])
        self.assertEqual(friction["lock_bypasses_total"], 9)
        self.assertEqual(friction["lock_bypasses_recent"], 0)
        self.assertFalse(friction["bypasses_outrun_denials"])

    def test_the_composition_names_its_head_and_counts_its_tail(self) -> None:
        lines = (
            [bypass("hooks/keel_gate.py") for _ in range(8)]
            + [bypass("<command>") for _ in range(3)]
            + [bypass(".keel/keel-policy.md") for _ in range(2)]
            + [bypass("scripts/keel_survey.py")]
            + [bypass("docs/keel-trust.md")]
        )
        friction = self._friction(lines)
        self.assertEqual(
            friction["bypass_segments"][:3],
            [
                {"segment": "hooks/", "count": 8},
                {"segment": "<command>", "count": 3},
                {"segment": ".keel/", "count": 2},
            ],
        )
        line = keel_survey.bypass_composition_line(friction)
        self.assertIn("composition of all 15 bypass(es)", line)
        self.assertIn("hooks/ 8", line)
        self.assertIn("2 more across 2 other segment(s)", line)

    def test_a_population_of_nothing_says_nothing_was_bypassed(self) -> None:
        line = keel_survey.bypass_composition_line(self._friction([denial()]))
        self.assertIn("nothing bypassed on record", line)

    def test_every_bypass_is_counted_somewhere_visible(self) -> None:
        """A target keel cannot read is still a bypass; dropping it would make
        the composition disagree with the total it is composed of."""
        lines = [
            bypass("hooks/a.py"),
            bypass(f"hooks{BACKSLASH}b.py"),
            bypass("<command>"),
            bypass(None),
            bypass(""),
            bypass({"nested": "shape"}),
            {"v": 1, "ts": _iso(30), "event": "gate_bypass", "gate": "policy_lock"},
        ]
        friction = self._friction(lines)
        counted = sum(item["count"] for item in friction["bypass_segments"])
        self.assertEqual(counted, friction["lock_bypasses_total"])
        self.assertEqual(counted, 7)
        segments = {item["segment"]: item["count"] for item in friction["bypass_segments"]}
        self.assertEqual(segments["hooks/"], 2)  # both separators, one segment
        self.assertEqual(segments[keel_survey.NO_SEGMENT], 4)

    def test_a_string_detail_is_read_as_the_target_it_is(self) -> None:
        self.assertEqual(keel_survey.bypass_segment("hooks/keel_gate.py"), "hooks/")
        self.assertEqual(
            keel_survey.bypass_segment({"target": f"hooks{BACKSLASH}keel_gate.py"}),
            "hooks/",
        )
        self.assertEqual(keel_survey.bypass_segment({"target": "<command>"}), "<command>")
        self.assertEqual(keel_survey.bypass_segment(None), keel_survey.NO_SEGMENT)


class TestTheBoardSaysWhichCodeItIsServing(unittest.TestCase):
    """T162's stale-board half: a board serving last week's page said nothing.

    The marker itself is drawn by the page, and this suite cannot execute the
    page's JavaScript - see "What a Python suite cannot do here" above. What is
    executed is the comparison the page is handed, in all three of its states.

    KEEL ADDITION (T349, fixing BL1): every case below used to fingerprint
    REPO_ROOT live - this repository's own tracked tree - which this armed
    session's own concurrent activity (other in-flight edits under hooks/,
    scripts/, skills/, agents/, from parallel work elsewhere in the same
    session) can move mid full-suite run. "Not stale" asserts nothing moved
    BETWEEN two reads, and a live, shared, actively-edited tree cannot
    promise that, so the assertion flaked exactly when something legitimately
    had - not a defect in ``served_code`` itself. ``setUp`` points
    ``board.served_code`` and ``keel_survey.version_report`` at ONE synthetic
    fixture tree this test builds with the existing ``build_tree`` helper and
    that nothing else in the process ever touches, so the same staleness
    logic is exercised deterministically. What each case asserts is
    unchanged; only what it measures moved from a shared live tree to an
    owned static one.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        fixture_root = build_tree(Path(tmp.name))
        page_copy = fixture_root / "keel_orchestration_dashboard.py"
        page_copy.write_text(BOARD_SOURCE, encoding="utf-8")

        original_fingerprint_fn = board.keel_component_fingerprint
        original_components_fp = board.SERVED_COMPONENTS_FP
        original_page_fp = board.SERVED_PAGE_FP
        original_page_source = board.PAGE_SOURCE
        original_survey_repo_root = keel_survey._REPO_ROOT

        def _cleanup() -> None:
            board.keel_component_fingerprint = original_fingerprint_fn
            board.SERVED_COMPONENTS_FP = original_components_fp
            board.SERVED_PAGE_FP = original_page_fp
            board.PAGE_SOURCE = original_page_source
            keel_survey._REPO_ROOT = original_survey_repo_root

        self.addCleanup(_cleanup)

        board.keel_component_fingerprint = lambda: keel_features.component_fingerprint(
            fixture_root
        )
        board.SERVED_COMPONENTS_FP = keel_features.component_fingerprint(fixture_root).digest
        board.PAGE_SOURCE = str(page_copy)
        board.SERVED_PAGE_FP = keel_features.path_digest(page_copy)
        # Same tree, so a board and a survey stay comparable exactly as they
        # are wired in production (both point at one installation root).
        keel_survey._REPO_ROOT = fixture_root
        self.fixture_root = fixture_root

    def test_the_served_block_carries_both_fingerprints(self) -> None:
        code = board.served_code()
        for key in (
            "components_fp",
            "components_fp_disk",
            "page_fp",
            "page_fp_disk",
            "stale",
            "unknown",
        ):
            self.assertIn(key, code)
        self.assertFalse(code["stale"])
        self.assertFalse(code["unknown"])

    def test_the_served_component_fingerprint_is_the_surveys_own(self) -> None:
        """One derivation, two surfaces: a board and a survey must be
        comparable, or the fingerprint answers nothing across them."""
        self.assertEqual(
            board.served_code()["components_fp"],
            keel_survey.version_report()["components_digest"],
        )

    def test_a_board_running_older_code_reports_itself_stale(self) -> None:
        original = board.SERVED_PAGE_FP
        try:
            board.SERVED_PAGE_FP = "0" * keel_features.FINGERPRINT_HEX_CHARS
            code = board.served_code()
        finally:
            board.SERVED_PAGE_FP = original
        self.assertTrue(code["stale"])
        self.assertFalse(code["unknown"])
        self.assertNotEqual(code["page_fp"], code["page_fp_disk"])

    def test_a_board_whose_components_moved_reports_itself_stale(self) -> None:
        original = board.SERVED_COMPONENTS_FP
        try:
            board.SERVED_COMPONENTS_FP = "1" * keel_features.FINGERPRINT_HEX_CHARS
            code = board.served_code()
        finally:
            board.SERVED_COMPONENTS_FP = original
        self.assertTrue(code["stale"])

    def test_an_unknown_answer_says_unknown_and_not_current(self) -> None:
        """T162's fourth clause: a board that cannot answer is not reported as
        current, and never as stale either."""
        original_fp, original_source = board.SERVED_PAGE_FP, board.PAGE_SOURCE
        try:
            board.SERVED_PAGE_FP = ""
            board.PAGE_SOURCE = str(REPO_ROOT / "scripts" / "no-such-page.py")
            code = board.served_code()
        finally:
            board.SERVED_PAGE_FP, board.PAGE_SOURCE = original_fp, original_source
        self.assertTrue(code["unknown"])
        self.assertFalse(code["stale"])

    def test_the_state_endpoint_serves_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            project = fixture_project(base, [])
            (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
            previous = board.ROOT
            try:
                board.ROOT = str(project)
                state = board.read_state()
            finally:
                board.ROOT = previous
        self.assertIn("code", state["keel"])
        self.assertEqual(
            state["keel"]["code"]["components_fp"], board.SERVED_COMPONENTS_FP
        )

    def test_the_page_carries_the_marker_and_derives_nothing_itself(self) -> None:
        """Pinned as SOURCE, for the reason this class's docstring gives. The
        page must print the server's verdict and must not compute one of its
        own - a second opinion drawn client-side is how two surfaces start
        disagreeing about whether a board is current."""
        addition = BOARD_SOURCE[BOARD_SOURCE.index("KEEL ADDITION (T168): the stale-board") :]
        self.assertIn('$("keelcode")', addition)
        self.assertIn("st.keel.code", addition)
        self.assertIn("cd.stale", addition)
        self.assertIn("cd.unknown", addition)
        # T338 (owner review 2026-08-26) reworded all three states from a
        # digest to a human answer; the pins follow the wording the page
        # actually ships, or they stop being able to fail.
        self.assertIn('code.textContent="code changed on disk"', addition)
        self.assertIn('code.textContent="code freshness unknown"', addition)
        self.assertIn('code.textContent="code current"', addition)
        self.assertIn("restart the board", addition)
        marker_block = addition[: addition.index("const counts=new Map();")]
        self.assertNotIn("cd.page_fp!==cd.page_fp_disk", marker_block)
        self.assertNotIn("cd.components_fp!==cd.components_fp_disk", marker_block)

    def test_the_served_block_carries_the_mtime_the_chip_humanises(self) -> None:
        """T338: one field added beside the fingerprints - a TIME, not a path -
        and the verdict keys are untouched."""
        code = board.served_code()
        self.assertIn("page_mtime", code)
        self.assertIsInstance(code["page_mtime"], float)
        self.assertGreater(code["page_mtime"], 0)
        # the comparison itself is unchanged: same keys, same verdict
        self.assertFalse(code["stale"])
        self.assertFalse(code["unknown"])

    def test_an_unreadable_page_source_reports_no_mtime_rather_than_now(self) -> None:
        original = board.PAGE_SOURCE
        try:
            board.PAGE_SOURCE = str(REPO_ROOT / "scripts" / "no-such-page.py")
            code = board.served_code()
        finally:
            board.PAGE_SOURCE = original
        self.assertIsNone(code["page_mtime"])

    def test_the_chip_humanises_that_time_with_the_pages_own_rel(self) -> None:
        """The relative-time voice is the page's existing one (``rel``), so the
        chip speaks like the cards and the feed rather than inventing a
        second time format."""
        self.assertIn('const codeAge=cd=>cd&&typeof cd.page_mtime==="number"', BOARD_SOURCE)
        self.assertIn("?rel(new Date(cd.page_mtime*1000).toISOString()):null;", BOARD_SOURCE)
        self.assertIn("const age=codeAge(cd);", BOARD_SOURCE)

    def test_the_digests_moved_into_the_chips_title(self) -> None:
        """The machine answer is not lost - it is one hover away, in both the
        stale and the current state."""
        self.assertIn("code.title=codeFps(cd);", BOARD_SOURCE)
        self.assertIn(
            'code.title="this board is serving the code on disk ("+codeFps(cd)+")";',
            BOARD_SOURCE,
        )
        self.assertNotIn('code.textContent="page current · "+cd.page_fp;', BOARD_SOURCE)

    def test_the_badge_exists_in_the_page_and_starts_hidden(self) -> None:
        self.assertIn('<span class="badge" id="keelcode" hidden></span>', BOARD_SOURCE)

    def test_the_addition_is_fenced_and_nothing_vendored_is_lost(self) -> None:
        self.assertIn("KEEL ADDITION (T168", BOARD_SOURCE)
        for landmark in (
            'id="livedot"',
            "const PERSONAS={",
            'id="sessbtn"',
            "function renderFeed",
            '<span class="badge" id="keelarming" hidden></span>',
        ):
            self.assertIn(landmark, BOARD_SOURCE)


class TestUnreadableIsNeverReadAsAbsent(unittest.TestCase):
    """The escalation's class: a path keel was REFUSED is not a path that is
    GONE, at every point where a filesystem answer becomes a presence verdict.

    Why these cases inject the fault
    --------------------------------
    A genuine permission-denied fixture is not constructible on all three
    operating systems this suite runs on: a POSIX ``chmod 000`` is a no-op for
    root (CI often runs as root, so the case would silently pass for the wrong
    reason), and Windows has no portable equivalent - its ACLs need a tool
    outside the standard library, and this project ships no third-party code.
    So the ``EACCES`` is injected at the two seams the module declares for it,
    ``keel_features._stat`` and ``keel_features._walk_tree``, and this docstring
    is the disclosure: what is proven here is that the code paths a real
    permission fault takes report UNREADABLE rather than ABSENT, and what is
    NOT proven is the operating system's behaviour on the way in. The
    read-failure case below needs no injected exception at all - it produces a
    real ``OSError`` from a real read.
    """

    #: The component every case in this class makes unreadable.
    BLOCKED = "hooks/gate.py"

    def _blocking_stat(self, blocked: Path):
        """A ``_stat`` that refuses one path and answers honestly for the rest."""
        real = keel_features._stat

        def fake(path: Path):
            if Path(path) == Path(blocked):
                raise PermissionError(13, "Permission denied", str(path))
            return real(path)

        return fake

    def test_component_state_tells_the_three_answers_apart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp))
            self.assertEqual(
                keel_features.component_state(self.BLOCKED, root), "present"
            )
            self.assertEqual(
                keel_features.component_state("hooks/never-shipped.py", root), "absent"
            )
            keel_features._stat = self._blocking_stat(root / self.BLOCKED)
            try:
                self.assertEqual(
                    keel_features.component_state(self.BLOCKED, root), "unreadable"
                )
                # The bool question keeps its own narrow contract: present, or
                # not positively present.
                self.assertFalse(keel_features.component_present(self.BLOCKED, root))
            finally:
                keel_features._stat = _REAL_STAT

    def test_the_legacy_component_probe_never_declines_on_a_refusal(self) -> None:
        """``feature_absent``'s no-registry path NEGATES a presence answer, so
        it is the third place a refusal could have become an absence - and the
        one whose output is a sentence telling a user to buy a bigger edition."""
        with tempfile.TemporaryDirectory() as tmp:
            bare = Path(tmp) / "bare"  # a tree carrying no registry at all
            (bare / "hooks").mkdir(parents=True)
            (bare / self.BLOCKED).write_text("# gate\n", encoding="utf-8")
            self.assertIsNone(keel_features.registry_features(bare))
            self.assertFalse(
                keel_features.feature_absent("kernel", component=self.BLOCKED, root=bare)
            )
            self.assertTrue(
                keel_features.feature_absent(
                    "kernel", component="hooks/never-shipped.py", root=bare
                )
            )
            keel_features._stat = self._blocking_stat(bare / self.BLOCKED)
            try:
                self.assertFalse(
                    keel_features.feature_absent(
                        "kernel", component=self.BLOCKED, root=bare
                    )
                )
            finally:
                keel_features._stat = _REAL_STAT

    def test_an_unreadable_component_is_not_counted_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            whole = build_tree(base / "whole")
            refused = build_tree(base / "refused")
            deleted = build_tree(base / "deleted")
            (deleted / self.BLOCKED).unlink()
            whole_fp = keel_features.component_fingerprint(whole)
            deleted_fp = keel_features.component_fingerprint(deleted)
            keel_features._stat = self._blocking_stat(refused / self.BLOCKED)
            try:
                refused_fp = keel_features.component_fingerprint(refused)
            finally:
                keel_features._stat = _REAL_STAT
        self.assertEqual(refused_fp.unreadable, (self.BLOCKED,))
        self.assertEqual(refused_fp.missing, ())
        self.assertEqual(deleted_fp.missing, (self.BLOCKED,))
        self.assertEqual(deleted_fp.unreadable, ())
        # Three distinct trees, three distinct digests: refused is neither the
        # whole tree nor the trimmed one.
        self.assertNotEqual(refused_fp.digest, whole_fp.digest)
        self.assertNotEqual(refused_fp.digest, deleted_fp.digest)
        self.assertIn("UNREADABLE", refused_fp.summary())
        self.assertNotIn("MISSING", refused_fp.summary())

    def test_the_same_refusal_digests_the_same_way_twice(self) -> None:
        """Deterministic: the unreadable marker is part of the input, so the
        value is still a fingerprint and not a coin toss."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp))
            keel_features._stat = self._blocking_stat(root / self.BLOCKED)
            try:
                first = keel_features.component_fingerprint(root)
                second = keel_features.component_fingerprint(root)
            finally:
                keel_features._stat = _REAL_STAT
        self.assertEqual(first.digest, second.digest)

    def test_a_subdirectory_that_cannot_be_listed_is_recorded(self) -> None:
        """The reviewed defect precisely: an OSError raised while LISTING a
        directory component used to fold into the absent marker. The walk seam
        reports it and the component's other files are still digested."""
        real_walk = keel_features._walk_tree

        def refusing_walk(base, onerror):
            for dirpath, dirnames, filenames in real_walk(base, onerror):
                yield dirpath, dirnames, filenames
            onerror(
                PermissionError(13, "Permission denied", str(Path(base) / "locked"))
            )

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            clean = build_tree(base / "clean")
            refused = build_tree(base / "refused")
            clean_fp = keel_features.component_fingerprint(clean)
            keel_features._walk_tree = refusing_walk
            try:
                refused_fp = keel_features.component_fingerprint(refused)
            finally:
                keel_features._walk_tree = real_walk
        self.assertEqual(refused_fp.missing, ())
        self.assertIn("skills/lay/locked", refused_fp.unreadable)
        self.assertEqual(refused_fp.files, clean_fp.files)  # the rest still counted
        self.assertNotEqual(refused_fp.digest, clean_fp.digest)

    def test_a_member_that_cannot_be_read_is_unreadable_not_missing(self) -> None:
        """No injected exception here: the walk names a file that is not there,
        so the read raises a REAL OSError, which is the fault a file deleted
        mid-scan or a locked file produces."""
        real_walk = keel_features._walk_tree

        def phantom_walk(base, onerror):
            for dirpath, dirnames, filenames in real_walk(base, onerror):
                yield dirpath, dirnames, list(filenames) + ["vanished.md"]

        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp))
            keel_features._walk_tree = phantom_walk
            try:
                fingerprint = keel_features.component_fingerprint(root)
            finally:
                keel_features._walk_tree = real_walk
        self.assertEqual(fingerprint.missing, ())
        self.assertIn("skills/lay/vanished.md", fingerprint.unreadable)

    def test_a_feature_with_an_unreadable_component_is_undecided(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp))
            keel_features._stat = self._blocking_stat(root / self.BLOCKED)
            try:
                presence = {p.name: p for p in keel_features.feature_presence(root)}
            finally:
                keel_features._stat = _REAL_STAT
        self.assertEqual(presence["kernel"].state, "unreadable")
        self.assertEqual(presence["kernel"].unreadable, 1)
        self.assertEqual(presence["knowledge"].state, "present")

    def test_the_edition_refuses_to_derive_rather_than_deriving_a_wrong_one(self) -> None:
        """Without the refusal this tree derives ``fleet``; with it, the answer
        is "cannot derive" - never a smaller edition inferred from an absence
        that was never established."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_tree(Path(tmp))
            clean = keel_features.derived_edition(root)
            keel_features._stat = self._blocking_stat(root / self.BLOCKED)
            try:
                refused = keel_features.derived_edition(root)
            finally:
                keel_features._stat = _REAL_STAT
        self.assertEqual(clean.layer, "fleet")
        self.assertTrue(clean.decidable)
        self.assertEqual(refused.layer, "")
        self.assertFalse(refused.decidable)
        self.assertTrue(refused.note.startswith("cannot derive"), refused.note)
        self.assertIn(self.BLOCKED, refused.note)
        self.assertIn(self.BLOCKED, refused.unreadable)
        self.assertIn("unreadable: kernel (1 of 2)", refused.found_summary())

    def test_the_survey_says_cannot_be_derived_in_its_own_register(self) -> None:
        """End to end over this repository's own tree, with one of its real
        components refused: the survey must not print an edition, must not call
        it an unrecognized mix (that is a claim about the tree), and must name
        the unreadable component under its own word."""
        blocked = REPO_ROOT / "hooks" / "keel_gate.py"
        keel_features._stat = self._blocking_stat(blocked)
        try:
            version = keel_survey.version_report()
            with tempfile.TemporaryDirectory() as tmp:
                base = Path(tmp)
                report = keel_survey.survey(
                    fixture_project(base, []), fixture_home(base, None)
                )
            rendered = keel_survey.render(report)
        finally:
            keel_features._stat = _REAL_STAT
        self.assertEqual(version["edition_derived"], "")
        self.assertEqual(version["edition_unreadable"], ["hooks/keel_gate.py"])
        self.assertIn("hooks/keel_gate.py", version["components_unreadable"])
        self.assertEqual(version["components_missing"], [])
        self.assertIn("edition : CANNOT BE DERIVED", rendered)
        self.assertNotIn("unrecognized component mix", rendered)
        self.assertIn("UNREADABLE component(s)", rendered)
        self.assertIn("1 UNREADABLE", rendered)
        self.assertNotIn("MISSING component(s)", rendered)


class TestTheStartupLineNamesAnInstallFinding(unittest.TestCase):
    """Finding 3: the one-liner stayed clean over an orphaned or missing tree."""

    def _startup(self, record: object | None) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            report = keel_survey.survey(
                fixture_project(base, []), fixture_home(base, record)
            )
            return keel_survey.startup_line(report)

    def test_a_record_pointing_at_nothing_reaches_the_one_liner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = install_document("keel@yard", Path(tmp) / "gone")
        line = self._startup(record)
        self.assertIn("install FINDING(s)", line)
        self.assertEqual(len(line.splitlines()), 1)

    def test_the_quiet_states_stay_quiet(self) -> None:
        """No record at all (an adopter's checkout) and a record that agrees
        both add nothing: a line that always mentions the install is a line
        nobody reads."""
        self.assertNotIn("install FINDING", self._startup(None))
        agreeing = install_document("keel@yard", REPO_ROOT)
        line = self._startup(agreeing)
        self.assertNotIn("install FINDING", line)
        self.assertEqual(len(line.splitlines()), 1)

    def test_the_line_still_carries_everything_it_did_before(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = install_document("keel@yard", Path(tmp) / "gone")
        line = self._startup(record)
        for fragment in ("keel survey:", "registration(s)", "tokens", "conflicts"):
            self.assertIn(fragment, line)


class TestTheTrustPagePublishesTheRate(unittest.TestCase):
    """The published rate, with the decomposition as its first data point."""

    def setUp(self) -> None:
        self.text = (REPO_ROOT / "docs" / "keel-trust.md").read_text(encoding="utf-8")

    def test_the_rate_is_published_with_its_composition(self) -> None:
        self.assertIn("bypass rate is published", self.text)
        for figure in ("365", "308", "4 policy-lock denials"):
            self.assertIn(figure, self.text)
        self.assertIn("2026-08-18", self.text)

    def test_the_ratified_answer_is_named(self) -> None:
        self.assertIn("workshop", self.text)
        self.assertIn("2026-08-18-workshop-paths-ratified.md", self.text)


if __name__ == "__main__":
    unittest.main()
