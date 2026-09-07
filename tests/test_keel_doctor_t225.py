#!/usr/bin/env python3
"""T225 - doctor-grade self-diagnosis, the diagnostics half.

Contract
--------
Reads   : ``scripts/keel_doctor.py`` as a module, and this repository's own
          ``hooks/hooks.json`` for the "real registration" fixtures below -
          reading it is not a violation of the isolation every other fixture
          test in this suite insists on, because ``keel_doctor`` never
          EVALUATES anything against this project: every synthetic launch
          points its payload's ``cwd`` and the child process's
          ``CLAUDE_PROJECT_DIR`` at a throwaway temporary directory instead
          (see ``TestSyntheticLaunchNeverTouchesTheRealProject`` below, which
          is the test that makes that claim rather than trusting it).
Emits   : unittest results only.
Writes  : nothing outside temporary directories created and removed by
          ``keel_doctor`` itself or by this file's own fixtures.
Argv    : none.

What this covers, clause by clause
-----------------------------------
1. A DEAD HOOK LAYER IS DETECTED, a healthy one reports healthy (accept 1).
   ``TestAHealthyRegistrationReportsHealthy``,
   ``TestABrokenRegistrationIsDetected``.
2. EVERY STATE THE CHECK CANNOT ESTABLISH IS ITS OWN STATE (accept 2).
   ``TestUnestablishedStatesAreNeverHealthy``.
3. THE PROBE IS ZERO-TRACE, on this project's own real, ARMED audit log -
   not only on the throwaway one (T185's own lesson).
   ``TestSyntheticLaunchNeverTouchesTheRealProject``.
4. THE KNOWN-BROKEN-PATTERN SCAN flags each documented pattern and leaves a
   clean entry alone. ``TestKnownBrokenPatternScan``.
5. EXIT CODES follow the 0/1/2 convention. ``TestExitCodes``.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails the check rather
than skipping it - including the real-``bash`` launches, since every hook
this project ships already requires ``bash`` to run at all (``hooks.json``
registers ``"shell": "bash"`` on every entry), so an environment missing it
could not run keel's own hooks either.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation states
its encoding.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))

import keel_doctor  # noqa: E402


def audit_lines(project: Path) -> list[dict]:
    """Every parsed audit line of a project, oldest first; [] if there is none."""
    path = project / ".keel" / "audit" / "keel-audit.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolved_bash() -> str:
    """This suite's own harness bash, resolved the same way ``keel_doctor``
    itself resolves it (T465/BL29) - NOT the first ``bash`` on ``PATH``,
    which on a machine with a broken WSL launcher ahead of Git-for-Windows's
    is a different, unusable interpreter. Fails the test with a clear
    message if nothing resolves at all, exactly as the old
    ``shutil.which("bash")`` call this replaces did.
    """
    bash, note = keel_doctor.harness_bash()
    assert bash is not None, f"no usable bash resolved by keel_doctor.harness_bash() ({note})"
    return bash


def real_registrations() -> list[keel_doctor.HookRegistration]:
    """This repository's OWN committed registrations - the correct fixture."""
    registrations, error = keel_doctor.read_hook_registrations(REPO_ROOT)
    assert error is None, f"hooks/hooks.json could not be read: {error}"
    assert registrations, "hooks/hooks.json carries no registrations to test against"
    return registrations


class TestAHealthyRegistrationReportsHealthy(unittest.TestCase):
    """Accept 1, the healthy direction: every one of keel's own committed
    registrations, probed against its own real plugin root, reports
    ``STATE_HEALTHY`` - launched, returned exit 0, left no trace."""

    def test_every_committed_registration_probes_healthy(self) -> None:
        for registration in real_registrations():
            with self.subTest(event=registration.event, matcher=registration.matcher):
                result = keel_doctor.probe_registration(
                    registration, plugin_root=REPO_ROOT, bash=self._bash()
                )
                self.assertEqual(result.state, keel_doctor.STATE_HEALTHY, result.detail)
                self.assertEqual(result.returncode, 0)

    def _bash(self) -> str:
        return resolved_bash()


class TestABrokenRegistrationIsDetected(unittest.TestCase):
    """Accept 1, the broken direction: the SAME committed command, launched
    against a plugin root whose ``hooks/keel_hook.py`` does not exist,
    reports broken rather than healthy - the nonexistent-script-path fixture
    this task's clause 5 asks for."""

    def test_a_nonexistent_script_path_is_not_reported_healthy(self) -> None:
        bash = resolved_bash()
        registration = real_registrations()[0]
        with tempfile.TemporaryDirectory() as tmp:
            empty_plugin_root = Path(tmp)  # no hooks/keel_hook.py under here
            result = keel_doctor.probe_registration(
                registration, plugin_root=empty_plugin_root, bash=bash
            )
        self.assertNotEqual(result.state, keel_doctor.STATE_HEALTHY, result.detail)
        self.assertIn(result.state, (keel_doctor.STATE_BROKEN, keel_doctor.STATE_DEGRADED))


class TestUnestablishedStatesAreNeverHealthy(unittest.TestCase):
    """Accept 2: a probe that cannot even be attempted (no ``bash``) is its
    own state, never folded into healthy, and never crashes the caller."""

    def test_no_bash_reports_skipped_not_healthy(self) -> None:
        registration = real_registrations()[0]
        result = keel_doctor.probe_registration(registration, plugin_root=REPO_ROOT, bash=None)
        self.assertEqual(result.state, keel_doctor.STATE_SKIPPED)

    def test_probe_states_are_the_five_declared_ones(self) -> None:
        self.assertEqual(
            set(keel_doctor.PROBE_STATES),
            {
                keel_doctor.STATE_HEALTHY,
                keel_doctor.STATE_DEGRADED,
                keel_doctor.STATE_BROKEN,
                keel_doctor.STATE_SKIPPED,
                keel_doctor.STATE_UNREADABLE,
            },
        )


class TestSyntheticLaunchNeverTouchesTheRealProject(unittest.TestCase):
    """Accept 3, restated from T185: probing every one of keel's own
    registrations against THIS project - the one this suite runs in, which
    is itself armed - appends not one line to this project's real audit log
    and creates no file in this project's real ``.keel/`` tree.

    ``CLAUDE_PROJECT_DIR`` is passed as the (real, armed) repository root
    only to prove the OVERRIDE inside ``probe_registration`` - which always
    points both the payload ``cwd`` and the child's ``CLAUDE_PROJECT_DIR`` at
    a throwaway directory - is what actually protects this project, not an
    accident of the caller never having set the variable.
    """

    def test_probing_every_registration_leaves_the_real_audit_log_untouched(self) -> None:
        # KEEL ADDITION (T349): this repo's real audit log is append-only
        # (hooks/keel_events.py._append_jsonl opens "a") and this session's
        # own hooks keep appending to it WHILE this test runs, so a raw
        # before/after length or byte-size comparison flakes under full-suite
        # load - a concurrent real append lands between the two reads and is
        # mistaken for a leak. Append-only means the "before" snapshot is
        # always a prefix of "after"; what the probe must never do is add a
        # line of ITS OWN, and every synthetic payload is stamped with
        # keel_doctor.PROBE_SESSION_ID exactly so a leaked line can be
        # recognised on sight (see keel_doctor.probe_payload). So this
        # asserts the precise claim - "doctor did not add lines of its own" -
        # rather than "the file's length is unchanged", which is untrue by
        # construction in a live, armed repo.
        bash = resolved_bash()
        before = audit_lines(REPO_ROOT)
        for registration in real_registrations():
            keel_doctor.probe_registration(registration, plugin_root=REPO_ROOT, bash=bash)
        after = audit_lines(REPO_ROOT)
        self.assertGreaterEqual(
            len(after), len(before), "the real audit log lost lines - it should only ever grow"
        )
        self.assertEqual(
            after[: len(before)],
            before,
            "an existing real audit line changed - the log is meant to be append-only",
        )
        # KEEL ADDITION (T349): every real audit writer (keel_session.py,
        # keel_capture.py, keel_gate.py, keel_stop.py, keel_hook.py) stamps
        # the session id under the key "session", not the harness payload's
        # own "session_id" spelling - checking both catches a leak no matter
        # which of the two conventions the write path used.
        leaked = [
            line
            for line in after[len(before) :]
            if keel_doctor.PROBE_SESSION_ID in (line.get("session"), line.get("session_id"))
        ]
        self.assertEqual(
            leaked, [], "a synthetic probe appended a line of its own to the real audit log"
        )


class TestKnownBrokenPatternScan(unittest.TestCase):
    """Accept 4: each documented pattern is flagged by name; a clean entry
    triggers nothing."""

    def test_args_array_is_flagged(self) -> None:
        document = {
            "hooks": {
                "Stop": [
                    {"hooks": [{"type": "command", "args": ["a"], "command": "/abs/x.py"}]}
                ]
            }
        }
        findings = keel_doctor.scan_settings_document("t", Path("settings.json"), document)
        self.assertTrue(any("args" in f for f in findings), findings)

    def test_project_dir_variable_is_flagged(self) -> None:
        findings = keel_doctor.scan_command_patterns(
            "t", "PreToolUse", 'python "$CLAUDE_PROJECT_DIR/hooks/x.py"'
        )
        self.assertTrue(any("CLAUDE_PROJECT_DIR" in f for f in findings), findings)

    def test_relative_script_path_is_flagged(self) -> None:
        findings = keel_doctor.scan_command_patterns("t", "PreToolUse", "python hooks/x.py")
        self.assertTrue(any("relative script path" in f for f in findings), findings)

    def test_absolute_script_path_is_not_flagged_as_relative(self) -> None:
        findings = keel_doctor.scan_command_patterns(
            "t", "PreToolUse", 'python "/abs/hooks/x.py" || exit 0'
        )
        self.assertFalse(any("relative script path" in f for f in findings), findings)

    def test_gate_command_with_no_failure_wrapper_is_flagged(self) -> None:
        findings = keel_doctor.scan_command_patterns("t", "Stop", '"/abs/x.py"')
        self.assertTrue(any("no visible failure wrapper" in f for f in findings), findings)

    def test_a_clean_wrapped_absolute_command_is_not_flagged(self) -> None:
        findings = keel_doctor.scan_command_patterns(
            "t", "Stop", '"/abs/x.py" || echo failed; exit 0'
        )
        self.assertEqual(findings, [])

    def test_a_non_gate_event_is_not_checked_for_a_wrapper(self) -> None:
        findings = keel_doctor.scan_command_patterns("t", "SessionStart", '"/abs/x.py"')
        self.assertEqual(findings, [])


class TestExitCodes(unittest.TestCase):
    """Accept 5: 0 healthy, 1 findings (including an unestablished state), 2
    cannot run."""

    def _report(self, **overrides) -> dict:
        base = {
            "hooks_json_error": None,
            "registrations_found": 1,
            "probe_summary": {state: 0 for state in keel_doctor.PROBE_STATES},
            "pattern_findings": [],
        }
        base.update(overrides)
        return base

    def test_all_healthy_no_findings_is_zero(self) -> None:
        report = self._report(
            probe_summary={
                keel_doctor.STATE_HEALTHY: 1,
                keel_doctor.STATE_DEGRADED: 0,
                keel_doctor.STATE_BROKEN: 0,
                keel_doctor.STATE_SKIPPED: 0,
                keel_doctor.STATE_UNREADABLE: 0,
            }
        )
        self.assertEqual(keel_doctor.exit_code(report), 0)

    def test_a_pattern_finding_alone_is_one(self) -> None:
        report = self._report(
            probe_summary={
                keel_doctor.STATE_HEALTHY: 1,
                keel_doctor.STATE_DEGRADED: 0,
                keel_doctor.STATE_BROKEN: 0,
                keel_doctor.STATE_SKIPPED: 0,
                keel_doctor.STATE_UNREADABLE: 0,
            },
            pattern_findings=["something"],
        )
        self.assertEqual(keel_doctor.exit_code(report), 1)

    def test_a_skipped_probe_alone_is_one_never_zero(self) -> None:
        report = self._report(
            probe_summary={
                keel_doctor.STATE_HEALTHY: 0,
                keel_doctor.STATE_DEGRADED: 0,
                keel_doctor.STATE_BROKEN: 0,
                keel_doctor.STATE_SKIPPED: 1,
                keel_doctor.STATE_UNREADABLE: 0,
            }
        )
        self.assertEqual(keel_doctor.exit_code(report), 1)

    def test_an_unreadable_hooks_json_is_two(self) -> None:
        report = self._report(hooks_json_error="hooks/hooks.json: not found")
        self.assertEqual(keel_doctor.exit_code(report), 2)

    def test_all_healthy_no_findings_is_zero_with_pattern_notes_explicitly_empty(
        self,
    ) -> None:
        """The "no notes" spelling as an explicit ``[]`` must agree with the
        absent-key spelling already exercised above - both read as healthy."""
        report = self._report(
            probe_summary={
                keel_doctor.STATE_HEALTHY: 1,
                keel_doctor.STATE_DEGRADED: 0,
                keel_doctor.STATE_BROKEN: 0,
                keel_doctor.STATE_SKIPPED: 0,
                keel_doctor.STATE_UNREADABLE: 0,
            },
            pattern_notes=[],
        )
        self.assertEqual(keel_doctor.exit_code(report), 0)

    def test_pattern_notes_alone_is_one_never_zero(self) -> None:
        """keel:reviewer-silent-failure (T225 retry): an unreadable settings
        SOURCE (``pattern_notes`` non-empty) must not read as healthy even
        when every probe is healthy and there are no pattern findings -
        "could not check" is never "healthy"."""
        report = self._report(
            probe_summary={
                keel_doctor.STATE_HEALTHY: 1,
                keel_doctor.STATE_DEGRADED: 0,
                keel_doctor.STATE_BROKEN: 0,
                keel_doctor.STATE_SKIPPED: 0,
                keel_doctor.STATE_UNREADABLE: 0,
            },
            pattern_notes=["unreadable settings.json: JSONDecodeError: bad"],
        )
        self.assertEqual(keel_doctor.exit_code(report), 1)


class TestInstallDivergenceIsScoredAndRendered(unittest.TestCase):
    """T500: ``keel_survey.install_report``'s own finding (T168) was already
    computed on every run and never reached this report, so a real divergence
    on this machine had been scoring green for a month. Fixture-built report
    dictionaries only, in ``TestExitCodes``'s own style - no test here needs a
    real second installed tree on disk.
    """

    def _report(self, **overrides) -> dict:
        base = {
            "project": "/some/project",
            "hooks_json_error": None,
            "registrations_found": 0,
            "probes": [],
            "probe_summary": {state: 0 for state in keel_doctor.PROBE_STATES},
            "pattern_findings": [],
            "pattern_notes": [],
            "version": {
                "plugin": "1.2.3",
                "changelog_top": "1.2.3",
                "agrees": True,
                "components": "abc123",
                "note": "",
            },
        }
        base.update(overrides)
        return base

    def test_a_real_divergence_renders_a_line_and_exits_one(self) -> None:
        report = self._report(
            install={
                "findings": [
                    "two trees claim version 1.2.3: this one fingerprints "
                    "X and the recorded tree at Y fingerprints Z"
                ],
                "note": "",
            }
        )
        rendered = keel_doctor.render(report)
        self.assertIn("install : DISAGREE - the installed tree differs from this one", rendered)
        self.assertIn("two trees claim version 1.2.3", rendered)
        self.assertNotIn("could not be established", rendered)
        self.assertEqual(keel_doctor.exit_code(report), 1)

    def test_record_and_reality_agreeing_still_exits_zero(self) -> None:
        """The agreement wording is its own claim, not just the absence of
        the divergence one - a reader who only checked "no DISAGREE" would
        not notice the headline going silent."""
        report = self._report(install={"findings": [], "note": ""})
        rendered = keel_doctor.render(report)
        self.assertIn("install : agrees - the installed tree is this one", rendered)
        self.assertNotIn("differs from this one", rendered)
        self.assertEqual(keel_doctor.exit_code(report), 0)

    def test_an_unreadable_install_report_scores_like_a_divergence_but_is_not_rendered_as_one(
        self,
    ) -> None:
        """keel:reviewer-silent-failure (T500 retry): an install report that
        could not be read scores exactly like a divergence (the same contract
        ``version.note`` already keeps), but "unreadable" is not "differs" -
        nobody ever compared the two trees, so the headline must not claim
        they were found to disagree. Only the NOT READ line may say why."""
        report = self._report(
            install={
                "findings": [],
                "note": "the install record could not be read: JSONDecodeError: bad",
            }
        )
        rendered = keel_doctor.render(report)
        self.assertNotIn("DISAGREE", rendered)
        self.assertNotIn("differs from this one", rendered)
        self.assertIn(
            "install : UNKNOWN - the installed tree's agreement with this "
            "one could not be established",
            rendered,
        )
        self.assertIn("NOT READ: the install record could not be read", rendered)
        self.assertEqual(keel_doctor.exit_code(report), 1)

    def test_a_report_with_no_install_key_at_all_is_backward_compatible(self) -> None:
        """A report shape from an older keel, or a fixture that never sets
        "install", must not raise and must not be scored as a divergence it
        never checked for (the same "no notes" contract ``pattern_notes``
        already keeps)."""
        report = self._report()
        self.assertNotIn("install", report)
        rendered = keel_doctor.render(report)
        self.assertNotIn("differs from this one", rendered)
        self.assertEqual(keel_doctor.exit_code(report), 0)


class TestInstallDivergenceReport(unittest.TestCase):
    """Unit tests for ``install_divergence_report`` itself: the function
    ``build_report`` calls, modeled defensively on ``version_fingerprint``
    (T500)."""

    def test_survey_module_absent_is_a_note_not_a_crash(self) -> None:
        with mock.patch.object(keel_doctor, "keel_survey", None):
            report = keel_doctor.install_divergence_report()
        self.assertEqual(report["findings"], [])
        self.assertTrue(report["note"])

    def test_install_report_raising_is_caught_and_named(self) -> None:
        fake_survey = mock.Mock()
        fake_survey.version_report.return_value = {"manifest_name": "x", "plugin": "1.0.0"}
        fake_survey.install_report.side_effect = RuntimeError("boom")
        with mock.patch.object(keel_doctor, "keel_survey", fake_survey):
            report = keel_doctor.install_divergence_report()
        self.assertEqual(report["findings"], [])
        self.assertIn("RuntimeError", report["note"])
        self.assertIn("boom", report["note"])

    def test_an_unreadable_install_record_becomes_a_note_not_a_quiet_pass(self) -> None:
        """``install_report``'s own "unreadable" state (the record exists but
        could not be parsed) is a real failure, unlike "no record" - it must
        fold into ``note`` here, the same shape ``version.note`` uses."""
        fake_survey = mock.Mock()
        fake_survey.version_report.return_value = {"manifest_name": "x", "plugin": "1.0.0"}
        fake_survey.install_report.return_value = {
            "state": "unreadable",
            "line": "record unreadable - JSONDecodeError: bad",
            "findings": [],
        }
        with mock.patch.object(keel_doctor, "keel_survey", fake_survey):
            report = keel_doctor.install_divergence_report()
        self.assertEqual(report["findings"], [])
        self.assertIn("record unreadable", report["note"])

    def test_build_report_threads_home_and_the_version_half_through(self) -> None:
        """``build_report`` must pass ``install_report`` the ``manifest_name``
        and ``version`` the version half already read (T500 accept 1), and
        the same ``home`` seam it already threads for the settings scan."""
        fake_survey = mock.Mock()
        fake_survey.version_report.return_value = {
            "plugin": "9.9.9",
            "changelog_top": "9.9.9",
            "agrees": True,
            "components": "digest",
            "manifest_name": "the-manifest",
        }
        fake_survey.install_report.return_value = {"findings": [], "state": "agree"}
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as home_dir:
            project = Path(project_dir)
            home = Path(home_dir)
            with mock.patch.object(keel_doctor, "keel_survey", fake_survey):
                keel_doctor.build_report(project, home=home)
        fake_survey.install_report.assert_called_once()
        _, kwargs = fake_survey.install_report.call_args
        self.assertEqual(kwargs.get("home"), home)
        self.assertEqual(kwargs.get("manifest_name"), "the-manifest")
        self.assertEqual(kwargs.get("version"), "9.9.9")


class TestEveryInstallStateIsClassified(unittest.TestCase):
    """T500 retry: the state-by-state mapping ``classify_install_report``
    applies, one case per state ``keel_survey.install_report`` can return.

    Why per state rather than one happy and one sad case: the defect this
    retry answers was not a wrong branch, it was a MISSING one. The first
    version special-cased "unreadable" and let "unrecorded-root" - a record
    naming this installation at a tree that is not this one - fall through to
    agreement, and no test noticed because no test ever built that state. So
    each state below is pinned in both directions: what it classifies as, and
    what ``exit_code`` therefore returns. Flip any single row of
    ``INSTALL_STATE_VERDICTS`` and one of these fails.

    Hand-built report fixtures throughout, in the shape ``install_report``
    really returns (its own early-return paths leave ``entries``/``notes``
    exactly as staged here) - none of this needs a second installed tree on
    disk or a harness record to stage, which is precisely why the awkward
    states went untested the first time.
    """

    AGREEING = ("agree", "not-found", "no-entry")
    DIVERGING = ("unrecorded-root", "disagree")
    UNESTABLISHED = ("unreadable", "malformed")

    def _scored(self, install: dict) -> int:
        """``install`` scored the way a whole doctor run would score it."""
        return keel_doctor.exit_code(
            {
                "project": "/some/project",
                "hooks_json_error": None,
                "registrations_found": 0,
                "probes": [],
                "probe_summary": {state: 0 for state in keel_doctor.PROBE_STATES},
                "pattern_findings": [],
                "pattern_notes": [],
                "install": install,
            }
        )

    def test_the_table_names_every_state_keel_survey_can_actually_return(self) -> None:
        """The enumeration is taken FROM THE SOURCE, not from memory: every
        string ``keel_survey.install_report`` ever assigns to ``state`` must
        have a verdict here. Add a state there and forget it here and this
        test says so - which is the failure the default-deny lookup makes
        safe rather than silent, and this test makes visible rather than
        merely safe."""
        source = (REPO_ROOT / "scripts" / "keel_survey.py").read_text(encoding="utf-8")
        assigned: set[str] = set()
        for expression in re.findall(r'report\["state"\] = ([^\n]+)', source):
            assigned.update(re.findall(r'"([a-z-]+)"', expression))
        self.assertEqual(
            assigned,
            {"agree", "disagree", "unrecorded-root", "unreadable", "not-found", "malformed", "no-entry"},
            "keel_survey.install_report's state set changed - classify it below",
        )
        for state in sorted(assigned):
            with self.subTest(state=state):
                self.assertIn(state, keel_doctor.INSTALL_STATE_VERDICTS)

    def test_the_table_holds_exactly_the_verdicts_this_module_scores(self) -> None:
        """A verdict outside the three ``classify_install_report`` branches
        would fall through its ``AGREES`` check and land in the note branch
        by accident rather than by decision."""
        self.assertEqual(
            set(keel_doctor.INSTALL_STATE_VERDICTS.values()),
            {
                keel_doctor.INSTALL_AGREES,
                keel_doctor.INSTALL_DIVERGES,
                keel_doctor.INSTALL_UNESTABLISHED,
            },
        )
        agreeing = {
            state
            for state, verdict in keel_doctor.INSTALL_STATE_VERDICTS.items()
            if verdict == keel_doctor.INSTALL_AGREES
        }
        self.assertEqual(
            agreeing,
            set(self.AGREEING),
            "only 'the record makes no claim this tree contradicts' scores 0",
        )

    def test_the_states_that_mean_agreement_score_zero_and_print_nothing(self) -> None:
        """The state "agree" is the record and the tree matching. "not-found" and
        "no-entry" are THE ADOPTER CASES - no record at all, or a record
        holding other people's plugins and nothing named like this one. A
        record that makes no claim about this tree cannot be contradicted by
        it, and alarming here would fire on every adopter's clone."""
        lines = {
            "agree": "record names keel v1.2.3 at /trees/keel - record and reality agree",
            "not-found": (
                "record not found at /[home-path]/.claude/plugins/config.json - nothing "
                "to check (this tree was not installed by a harness that keeps "
                "one, which is the normal state of a checkout)"
            ),
            "no-entry": (
                "record /[home-path]/.claude/plugins/config.json names no installation "
                "matching 'keel' among 4 recorded plugin(s)"
            ),
        }
        for state in self.AGREEING:
            with self.subTest(state=state):
                install = keel_doctor.classify_install_report(
                    {"state": state, "line": lines[state], "findings": [], "notes": []}
                )
                self.assertEqual(install, {"findings": [], "note": ""})
                self.assertEqual(self._scored(install), 0)

    def test_an_unrecorded_root_is_a_divergence_though_its_findings_are_empty(
        self,
    ) -> None:
        """THE REGRESSION THIS RETRY EXISTS FOR. ``install_report`` reports
        this one - the record holds entries keyed to this manifest and NONE
        of them is the tree running - in ``state`` and ``notes`` only, with
        ``findings`` left empty. Forwarding findings alone therefore scored a
        genuinely orphaned installation as agreement. The fixture is that
        exact shape."""
        install = keel_doctor.classify_install_report(
            {
                "state": "unrecorded-root",
                "line": "record names keel v1.2.3 at /trees/other-keel",
                "findings": [],
                "notes": [
                    "this survey runs from /trees/this-keel, which the record "
                    "does not name: the tree being surveyed is not the tree the "
                    "harness installed"
                ],
                "entries": [{"key": "keel", "install_path": "/trees/other-keel"}],
            }
        )
        self.assertEqual(install["note"], "")
        self.assertEqual(len(install["findings"]), 1)
        self.assertIn("unrecorded-root", install["findings"][0])
        self.assertIn("/trees/other-keel", install["findings"][0])
        self.assertIn("is not the tree the harness installed", install["findings"][0])
        self.assertEqual(self._scored(install), 1)

    def test_a_disagreeing_record_scores_one_even_if_it_states_no_finding(self) -> None:
        """``install_report`` reaches "disagree" only alongside a finding
        today, so this pins the state itself rather than the finding that
        usually accompanies it: the classification must not depend on
        another function continuing to populate a list."""
        install = keel_doctor.classify_install_report(
            {
                "state": "disagree",
                "line": "record names keel v1.2.3 at /trees/gone",
                "findings": [],
                "notes": [],
            }
        )
        self.assertEqual(install["note"], "")
        self.assertTrue(install["findings"])
        self.assertEqual(self._scored(install), 1)

    def test_a_record_that_exists_and_cannot_be_read_is_never_agreement(self) -> None:
        """The states "unreadable" (present, unparseable) and "malformed" (parses, but
        carries no 'plugins' table) are one class: the file IS there, so a
        claim about this tree may well be in it, and keel cannot see it. That
        is could-not-be-established, which scores exactly like a divergence -
        deliberately NOT grouped with "not-found", where the absence of the
        file is itself the answer."""
        lines = {
            "unreadable": "record unreadable - JSONDecodeError: line 1 column 1",
            "malformed": (
                "record /[home-path]/.claude/plugins/config.json carries no 'plugins' "
                "table - the harness's record is in a shape keel does not "
                "recognise"
            ),
        }
        for state in self.UNESTABLISHED:
            with self.subTest(state=state):
                install = keel_doctor.classify_install_report(
                    {"state": state, "line": lines[state], "findings": [], "notes": []}
                )
                self.assertEqual(install["findings"], [])
                self.assertIn("could not be established", install["note"])
                self.assertIn(state, install["note"])
                self.assertIn(lines[state], install["note"])
                self.assertEqual(self._scored(install), 1)

    def test_a_state_this_doctor_has_never_heard_of_scores_one_and_says_so(self) -> None:
        """The default-deny half, and the reason the table is an allowlist of
        agreement rather than a denylist of divergence: a state added to
        ``install_report`` later, and never classified here, must arrive as
        "not checked" rather than as "healthy". A missing row can then only
        cost a false alarm that names itself, never a silent pass."""
        install = keel_doctor.classify_install_report(
            {"state": "invented-next-month", "line": "something new", "findings": []}
        )
        self.assertEqual(install["findings"], [])
        self.assertIn("invented-next-month", install["note"])
        self.assertIn("does not recognise", install["note"])
        self.assertEqual(self._scored(install), 1)

    def test_an_empty_state_is_not_agreement_either(self) -> None:
        """The field's own initial value, and what a caller's partial fixture
        carries. Nothing about "" says the record agrees."""
        install = keel_doctor.classify_install_report({"state": "", "findings": []})
        self.assertEqual(install["findings"], [])
        self.assertTrue(install["note"])
        self.assertEqual(self._scored(install), 1)

    def test_a_finding_is_carried_even_under_a_state_that_agrees(self) -> None:
        """``install_report`` reads the running tree's ``.orphaned_at`` marker
        BEFORE it reads the record, and its quiet states return early, so an
        orphaned tree on a machine with no record at all arrives as
        "not-found" CARRYING a finding. The finding is the stronger evidence,
        so an agreeing state must never swallow it."""
        orphan = (
            "the tree this survey runs from carries .orphaned_at "
            "(2026-08-18T09:12:44) and .in_use, so the orphaned tree is the one "
            "loaded"
        )
        install = keel_doctor.classify_install_report(
            {"state": "not-found", "line": "record not found", "findings": [orphan]}
        )
        self.assertEqual(install["findings"], [orphan])
        self.assertEqual(install["note"], "")
        self.assertEqual(self._scored(install), 1)

    def test_the_divergence_survives_the_whole_run_end_to_end(self) -> None:
        """The classification is only worth anything if it survives
        ``install_divergence_report`` -> ``build_report`` -> ``exit_code`` and
        ``render``. Mocked at the survey seam only, so every layer between is
        the real one; this is the test that would fail if the carry were
        dropped anywhere along it, as it was."""
        fake_survey = mock.Mock()
        fake_survey.version_report.return_value = {
            "plugin": "1.2.3",
            "changelog_top": "1.2.3",
            "agrees": True,
            "components": "digest",
            "manifest_name": "keel",
        }
        fake_survey.install_report.return_value = {
            "state": "unrecorded-root",
            "line": "record names keel v1.2.3 at /trees/other-keel",
            "findings": [],
            "notes": ["the tree being surveyed is not the tree the harness installed"],
        }
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as home_dir:
            with mock.patch.object(keel_doctor, "keel_survey", fake_survey):
                report = keel_doctor.build_report(Path(project_dir), home=Path(home_dir))
        self.assertTrue(report["install"]["findings"])
        rendered = keel_doctor.render(report)
        self.assertIn("the installed tree differs from this one", rendered)
        self.assertIn("/trees/other-keel", rendered)
        self.assertEqual(keel_doctor.exit_code(report), 1)


class TestUnreadableSettingsSourceIsNeverSilentlyHealthy(unittest.TestCase):
    """keel:reviewer-silent-failure (T225 retry, end-to-end): a project whose
    settings.json is malformed cannot be pattern-scanned for that source -
    the report must say so as its own labeled state (not a NOTE aside), and
    the exit code must not read the run as healthy just because every probe
    that COULD run was fine and no pattern findings turned up."""

    def test_a_malformed_settings_json_is_reported_unscannable_and_exits_nonzero(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as project_dir, tempfile.TemporaryDirectory() as home_dir:
            project = Path(project_dir)
            home = Path(home_dir)
            claude_dir = project / ".claude"
            claude_dir.mkdir(parents=True, exist_ok=True)
            (claude_dir / "settings.json").write_text("{not valid json", encoding="utf-8")

            report = keel_doctor.build_report(project, home=home)

            self.assertIsNone(report["hooks_json_error"])
            self.assertTrue(report["pattern_notes"], report)
            self.assertTrue(
                any("settings.json" in note for note in report["pattern_notes"]),
                report["pattern_notes"],
            )
            rendered = keel_doctor.render(report)
            self.assertIn("UNREADABLE SOURCE", rendered)
            self.assertFalse(
                any(line.strip().startswith("NOTE ") for line in rendered.splitlines()),
                "must be its own labeled state, not a NOTE aside",
            )

            code = keel_doctor.exit_code(report)
            self.assertNotEqual(code, 0, "an unscannable source must not exit healthy")
            self.assertEqual(code, 1, "an unscannable source is a 'cannot establish' state, same as a probe that could not be run - scored 1, not 2 (2 is reserved for having nothing at all to probe)")


class TestReadHookRegistrations(unittest.TestCase):
    """The fatal-error path a caller's exit-2 branch depends on."""

    def test_a_missing_hooks_json_is_a_fatal_error_not_an_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registrations, error = keel_doctor.read_hook_registrations(Path(tmp))
        self.assertEqual(registrations, [])
        self.assertIsNotNone(error)

    def test_the_real_hooks_json_parses_into_registrations(self) -> None:
        registrations, error = keel_doctor.read_hook_registrations(REPO_ROOT)
        self.assertIsNone(error)
        self.assertTrue(registrations)
        events = {r.event for r in registrations}
        self.assertIn("Stop", events)
        self.assertIn("SubagentStop", events)


class TestHarnessBashResolver(unittest.TestCase):
    """T465/BL29: the probe must ask the bash the HARNESS uses, not the
    first ``bash`` on ``PATH``. Both directions, entirely through fixtures -
    never the real machine's own PATH or environment - so these pass
    identically whether or not this machine's own WSL launcher happens to
    shadow Git-for-Windows's bash today.
    """

    def test_env_override_wins_when_set_to_an_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_bash = Path(tmp) / "fake-bash.exe"
            fake_bash.write_text("", encoding="utf-8")
            with mock.patch.dict(
                os.environ, {keel_doctor.CLAUDE_CODE_GIT_BASH_PATH_VAR: str(fake_bash)}
            ), mock.patch("keel_doctor.shutil.which", return_value=r"C:\Windows\system32\bash.EXE"):
                bash, note = keel_doctor.harness_bash()
        self.assertEqual(bash, str(fake_bash))
        self.assertIn("environment", note)

    def test_env_override_pointing_at_a_missing_file_is_not_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does-not-exist.exe"
            with mock.patch.dict(
                os.environ, {keel_doctor.CLAUDE_CODE_GIT_BASH_PATH_VAR: str(missing)}
            ), mock.patch("keel_doctor.shutil.which", return_value=None), mock.patch.object(
                keel_doctor, "_running_on_windows", lambda: True
            ):
                bash, note = keel_doctor.harness_bash()
        self.assertIsNone(bash)
        self.assertNotIn(str(missing), note)

    def test_git_derived_bash_wins_over_path_first_bash_on_windows(self) -> None:
        # A fake Git-for-Windows layout: git.exe under cmd/, bash.exe under
        # bin/ - the exact shape ``derive_git_bash`` walks parents to find.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_exe = root / "cmd" / "git.exe"
            git_exe.parent.mkdir(parents=True)
            git_exe.write_text("", encoding="utf-8")
            derived_bash = root / "bin" / "bash.exe"
            derived_bash.parent.mkdir(parents=True)
            derived_bash.write_text("", encoding="utf-8")
            path_first_bash = r"C:\Windows\system32\bash.EXE"  # the WSL shadow, never chosen

            def fake_which(name: str) -> str | None:
                return str(git_exe) if name == "git" else path_first_bash

            with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
                "keel_doctor.shutil.which", side_effect=fake_which
            ), mock.patch.object(keel_doctor, "_running_on_windows", lambda: True):
                os.environ.pop(keel_doctor.CLAUDE_CODE_GIT_BASH_PATH_VAR, None)
                bash, note = keel_doctor.harness_bash()
        self.assertEqual(bash, str(derived_bash))
        self.assertIn("Git for Windows", note)
        self.assertIn("differs from PATH-first bash", note)

    def test_derive_git_bash_finds_bin_bash_beside_cmd_git(self) -> None:
        """``derive_git_bash`` itself, exercised on EVERY platform this suite
        runs on (fail-closed doctrine: the Windows branch is not allowed to
        hide behind a skip on non-Windows CI) - the ``windows`` parameter
        stands in for the platform check the caller (``harness_bash``)
        otherwise makes with ``os.name``.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_exe = root / "mingw64" / "bin" / "git.exe"
            git_exe.parent.mkdir(parents=True)
            git_exe.write_text("", encoding="utf-8")
            bash_exe = root / "bin" / "bash.exe"
            bash_exe.parent.mkdir(parents=True)
            bash_exe.write_text("", encoding="utf-8")
            found = keel_doctor.derive_git_bash(git_exe, windows=True)
        self.assertEqual(found, bash_exe)

    def test_derive_git_bash_returns_none_off_windows_even_if_the_files_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_exe = root / "cmd" / "git.exe"
            git_exe.parent.mkdir(parents=True)
            git_exe.write_text("", encoding="utf-8")
            (root / "bin").mkdir()
            (root / "bin" / "bash.exe").write_text("", encoding="utf-8")
            found = keel_doctor.derive_git_bash(git_exe, windows=False)
        self.assertIsNone(found)

    def test_derive_git_bash_returns_none_when_no_bash_sits_beside_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            git_exe = Path(tmp) / "cmd" / "git.exe"
            git_exe.parent.mkdir(parents=True)
            git_exe.write_text("", encoding="utf-8")
            found = keel_doctor.derive_git_bash(git_exe, windows=True)
        self.assertIsNone(found)

    def test_falls_back_to_path_bash_when_no_override_and_no_git(self) -> None:
        path_bash = r"C:\somewhere\bash.exe"

        def fake_which(name: str) -> str | None:
            return path_bash if name == "bash" else None

        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "keel_doctor.shutil.which", side_effect=fake_which
        ), mock.patch.object(keel_doctor, "_running_on_windows", lambda: True):
            os.environ.pop(keel_doctor.CLAUDE_CODE_GIT_BASH_PATH_VAR, None)
            bash, note = keel_doctor.harness_bash()
        self.assertEqual(bash, path_bash)
        self.assertIn("PATH-first bash", note)

    def test_nothing_resolves_at_all(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False), mock.patch(
            "keel_doctor.shutil.which", return_value=None
        ), mock.patch.object(keel_doctor, "_running_on_windows", lambda: True):
            os.environ.pop(keel_doctor.CLAUDE_CODE_GIT_BASH_PATH_VAR, None)
            bash, note = keel_doctor.harness_bash()
        self.assertIsNone(bash)
        self.assertTrue(note)


class TestBashIsUsable(unittest.TestCase):
    """The trivial-command usability check standing between resolution and
    a real synthetic launch (BL29's own symptom: a ``bash`` that resolves
    and even launches, but cannot run anything)."""

    def test_the_real_resolved_bash_is_usable(self) -> None:
        usable, detail = keel_doctor.bash_is_usable(resolved_bash())
        self.assertTrue(usable, detail)
        self.assertEqual(detail, "")

    def test_an_interpreter_that_cannot_run_the_trivial_command_is_unusable(self) -> None:
        # A fixture "bash" that resolves and launches but cannot run the
        # trivial command: a real Python interpreter invoked exactly the way
        # ``bash_is_usable`` invokes bash (``[interpreter, "-c", "echo ..."]``)
        # - Python has no ``echo`` builtin, so this raises a SyntaxError to
        # stderr and exits non-zero, precisely the "launches, but cannot run
        # the trivial command" shape BL29's WSL launcher has (there it is
        # ``getpwuid``/``execvpe`` failing instead; the shape this check
        # cares about - non-zero exit, no marker on stdout - is identical).
        usable, detail = keel_doctor.bash_is_usable(sys.executable)
        self.assertFalse(usable)
        self.assertTrue(detail)
        self.assertIn("SyntaxError", detail)


class TestProbeAllSkipsRatherThanMeasuresAnUnusableBash(unittest.TestCase):
    """T465 clause 3: when the resolved bash cannot even run a trivial
    command, EVERY probe answers the existing SKIPPED state, naming the
    launcher and its stderr, and saying the registrations were NOT
    measured - never a sixth state, and never ``broken`` (broken asserts a
    registration's own command failed, which was never even attempted
    here)."""

    def test_an_unusable_bash_yields_all_skipped_not_broken(self) -> None:
        registrations = real_registrations()
        results = keel_doctor.probe_all(registrations, plugin_root=REPO_ROOT, bash=sys.executable)
        self.assertEqual(len(results), len(registrations))
        for result in results:
            self.assertEqual(result.state, keel_doctor.STATE_SKIPPED, result.detail)
            self.assertIn(sys.executable, result.detail)
            self.assertIn("NOT MEASURED", result.detail)
            self.assertNotEqual(result.state, keel_doctor.STATE_BROKEN)

    def test_a_usable_bash_still_probes_normally(self) -> None:
        # Convention 15's other half, restated as a fixture rather than a
        # manual before/after: with a bash proven usable, ``probe_all``
        # reaches the real synthetic launches - this repository's own
        # committed registrations report healthy exactly as
        # ``TestAHealthyRegistrationReportsHealthy`` already proves one at a
        # time.
        registrations = real_registrations()
        results = keel_doctor.probe_all(registrations, plugin_root=REPO_ROOT, bash=resolved_bash())
        for result in results:
            self.assertEqual(result.state, keel_doctor.STATE_HEALTHY, result.detail)


if __name__ == "__main__":
    unittest.main()
