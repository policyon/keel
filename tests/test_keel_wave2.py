#!/usr/bin/env python3
"""Phase 1 wave 2 test suite - redaction, capture, session, and the CLI.

Contract
--------
Reads   : tests/fixtures/capture/*.json and tests/fixtures/session/*.json -
          the declarative observer fixtures, in both directions ("record" and
          "silent") - plus the sources of every wave-2 file for their
          declared-policy assertions.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. The
          temporary directory is also the subprocess's TMP, and every
          subprocess runs with a copy of the environment that has no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR`` in it, so a developer's own
          shell cannot change what a test observes.

House style: fixtures are executed the way continuous integration will -
``python hooks/keel_hook.py <subcommand>`` as a real subprocess with JSON on
stdin - and the command-line tools are executed as
``python scripts/keel.py <command>``, so the exit codes asserted here are the
exit codes a caller gets.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
KEEL_CLI = REPO_ROOT / "scripts" / "keel.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_attest  # noqa: E402  (path must be set first)
import keel_capture  # noqa: E402
import keel_gen_hooks  # noqa: E402
import keel_leak_check  # noqa: E402
import keel_redact  # noqa: E402
import keel_gate  # noqa: E402
import keel_session  # noqa: E402
import keel_survey  # noqa: E402
from keel_registry_guard import (  # noqa: E402
    no_real_fleet_registry,
    no_real_hook_error_log,
)

#: The observer fixture kinds, and the subcommand each exercises.
OBSERVER_KINDS: tuple[str, ...] = ("capture", "session")

HOME = str(Path.home())
USERNAME = Path.home().name


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    Deliberately does NOT touch ``HOME``/``USERPROFILE`` here: the capture
    fixture ``02-bash-records-a-redacted-command`` embeds this machine's real
    home path in its fixture text and asserts the launcher redacts THAT path,
    so the child process must see the same home the test process resolved.
    ``run_fixture`` below overrides ``HOME``/``USERPROFILE`` on top of this,
    but only for the ``session`` kind, whose fixtures feed keel's
    user-global fleet registry (T227) and must not reach the real one.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def substitute(value: Any, project: Path, session: str) -> Any:
    """Expand $PROJECT / $SESSION / $SESS8 / $HOME / $USERNAME in a fixture."""
    if isinstance(value, str):
        return (
            value.replace("$PROJECT", str(project))
            .replace("$SESSION", session)
            .replace("$SESS8", session[:8])
            .replace("$HOME", HOME)
            .replace("$USERNAME", USERNAME)
        )
    if isinstance(value, dict):
        return {key: substitute(item, project, session) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, project, session) for item in value]
    return value


def load_fixtures(kind: str) -> list[tuple[str, dict]]:
    """Every fixture in a directory, in filename order, as (stem, document)."""
    directory = FIXTURE_ROOT / kind
    if not directory.is_dir():
        raise RuntimeError(f"missing fixture directory {directory}")
    found = [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
    if not found:
        raise RuntimeError(f"no fixtures in {directory}")
    return found


class ObserverFixtureRunner(unittest.TestCase):
    """Shared machinery for the two observer hooks: build, run, assert."""

    kind = ""

    def run_fixture(self, fixture: dict) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            scratch = root / "tmp"
            project.mkdir()
            scratch.mkdir()

            for spec in fixture.get("files", []):
                target = project / substitute(spec["path"], project, session)
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(substitute(spec["text"], project, session))

            env = clean_env(scratch)
            if self.kind == "session":
                # T227: a real SessionStart on an adopted fixture feeds keel's
                # user-global fleet registry, which reads Path.home() no
                # matter what clean_env() did to KEEL_*. Sandboxed here,
                # never for "capture" fixtures - one of which (02) embeds
                # this machine's REAL home in its own text and needs the
                # child to see that same real home to redact it.
                fleet_home = root / "fleet-home"
                fleet_home.mkdir()
                env.update({"HOME": str(fleet_home), "USERPROFILE": str(fleet_home)})
            env.update(substitute(fixture.get("env", {}), project, session))

            stdout_seen: list[str] = []
            for invocation in fixture["invocations"]:
                payload = substitute(invocation["stdin"], project, session)
                result = subprocess.run(
                    [sys.executable, "-B", str(HOOK), invocation["sub"]],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=env,
                    cwd=str(project),
                    timeout=60,
                    check=False,
                )
                detail = (
                    f"exit={result.returncode} stdout={result.stdout!r} "
                    f"stderr={result.stderr!r}"
                )
                self.assertEqual(result.returncode, fixture["expect_exit"], detail)
                stdout_seen.append(result.stdout)

            stdout = "".join(stdout_seen)
            if fixture.get("expect_stdout_empty"):
                self.assertEqual(stdout, "", "an observer that speaks is not an observer")
            for needle in fixture.get("expect_stdout_contains", []):
                self.assertIn(substitute(needle, project, session), stdout)

            audit = project.joinpath(*AUDIT_RELPATH)
            if fixture["direction"] == "silent":
                self.assertTrue(fixture.get("expect_no_audit"), "a silent fixture writes nothing")
                self.assertFalse(audit.is_file(), "nothing may be recorded here")
                if fixture.get("expect_empty_project"):
                    self.assertEqual(list(project.iterdir()), [], "project must be untouched")
                return

            self.assertTrue(audit.is_file(), f"expected an audit line at {audit}")
            raw = audit.read_bytes()
            self.assertNotIn(b"\r", raw, "the audit log must be LF-only JSONL")
            text = raw.decode("utf-8")
            lines = [json.loads(line) for line in text.splitlines() if line.strip()]
            expected = fixture["expect_events"]
            self.assertEqual([line["event"] for line in lines], expected, lines)
            for line in lines:
                self.assertEqual(line["v"], 1, line)
                self.assertRegex(line["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
                self.assertEqual(line["session"], session, line)

            # A JSON-encoded Windows path doubles its separators, so absence is
            # asserted against both spellings or it is not asserted at all.
            haystack = text + "\n" + text.replace("\\\\", "\\")
            for needle in fixture.get("expect_audit_contains", []):
                self.assertIn(substitute(needle, project, session), haystack)
            for needle in fixture.get("expect_audit_absent", []):
                resolved = substitute(needle, project, session)
                if not resolved:
                    continue
                self.assertNotIn(resolved, haystack, "a redacted log leaked a real path")


class TestCaptureFixtures(ObserverFixtureRunner):
    """Declarative capture fixtures, both directions."""

    kind = "capture"


class TestSessionFixtures(ObserverFixtureRunner):
    """Declarative session fixtures, both directions."""

    kind = "session"


def _attach(case: type[ObserverFixtureRunner], kind: str) -> None:
    """Turn every fixture file into its own named test method."""
    for stem, fixture in load_fixtures(kind):
        name = "test_" + re.sub(r"[^0-9a-zA-Z]+", "_", stem)

        def method(self: ObserverFixtureRunner, fixture: dict = fixture) -> None:
            self.run_fixture(fixture)

        method.__doc__ = f"{kind} fixture {stem}: {fixture.get('description', '')}"
        setattr(case, name, method)


_attach(TestCaptureFixtures, "capture")
_attach(TestSessionFixtures, "session")


class TestObserverFixtureShape(unittest.TestCase):
    """Convention 2, applied to observers: both directions or it does not ship."""

    def test_both_directions_ship_for_every_observer(self) -> None:
        for kind in OBSERVER_KINDS:
            with self.subTest(kind=kind):
                directions = [fixture["direction"] for _, fixture in load_fixtures(kind)]
                self.assertGreater(directions.count("record"), 0, "no record fixtures")
                self.assertGreater(directions.count("silent"), 0, "no silent fixtures")

    def test_every_fixture_is_well_formed(self) -> None:
        required = ("name", "direction", "description", "invocations", "expect_exit")
        seen: set[str] = set()
        for kind in OBSERVER_KINDS:
            for stem, fixture in load_fixtures(kind):
                with self.subTest(fixture=f"{kind}/{stem}"):
                    for key in required:
                        self.assertIn(key, fixture)
                    self.assertIn(fixture["direction"], ("record", "silent"))
                    self.assertEqual(fixture["expect_exit"], 0, "an observer never blocks")
                    self.assertTrue(stem.endswith(fixture["name"]))
                    self.assertNotIn(f"{kind}/{fixture['name']}", seen, "duplicate name")
                    seen.add(f"{kind}/{fixture['name']}")

    def test_case_sensitive_risk_ships_both_cases(self) -> None:
        """R1/convention 3: a lowercase tool name is exercised too."""
        names = {stem for stem, _ in load_fixtures("capture")}
        self.assertTrue(any("lowercase" in name for name in names))


class TestRedact(unittest.TestCase):
    """The username never reaches a log (convention 5)."""

    def test_home_prefix_becomes_a_tilde(self) -> None:
        value = os.path.join(HOME, "notes.txt")
        redacted = keel_redact.redact(value)
        self.assertTrue(redacted.startswith("~"), redacted)
        if USERNAME:
            self.assertNotIn(USERNAME, redacted)

    def test_either_separator_matches(self) -> None:
        for spelling in (HOME.replace("\\", "/"), HOME.replace("/", "\\")):
            with self.subTest(spelling=spelling):
                self.assertTrue(keel_redact.redact(spelling + "/x").startswith("~"))

    def test_matching_is_case_insensitive(self) -> None:
        self.assertTrue(keel_redact.redact(HOME.upper() + "/x").startswith("~"))

    def test_a_longer_sibling_name_is_not_swallowed(self) -> None:
        """'…/name2/x' must not be redacted as '~2/x' - a path that never was.

        WHAT THIS ASSERTED BEFORE, and why it no longer can: the original pin
        was byte-identity, on the reasoning that a sibling directory is not this
        home directory and so is nothing to do with the redactor. That reading
        was too narrow. ``…/Users/<name>2/x`` is still SOMEBODY's home-shaped
        path, and byte-identity there means emitting an account name verbatim -
        which is the leak ``screen_home_shapes`` was added to stop, so the
        expectation moved rather than the behaviour being wrong. What the test
        was actually guarding - that the boundary stops ``_PATTERN`` inventing
        ``~2/x`` out of a path that never existed - is asserted directly here
        instead, and is the assertion that would fail if ``_BOUNDARY`` were
        removed. Byte-identity for text carrying no account name at all is
        pinned in ``tests/test_keel_home_shapes.py``.
        """
        value = HOME + "2" + os.sep + "x"
        redacted = keel_redact.redact(value)
        self.assertFalse(redacted.startswith(keel_redact.HOME_TOKEN), redacted)
        self.assertNotIn(keel_redact.HOME_TOKEN, redacted)
        if USERNAME:
            self.assertNotIn(USERNAME, redacted)

    def test_non_strings_pass_through(self) -> None:
        for value in (None, 17, {"a": 1}, ["b"]):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.redact(value), value)

    def test_redact_mapping_covers_every_field(self) -> None:
        record = keel_redact.redact_mapping({"a": HOME + os.sep + "x", "b": 3})
        self.assertTrue(str(record["a"]).startswith("~"))
        self.assertEqual(record["b"], 3)

    def test_redact_path_prefers_the_project_relative_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            inside = str(project / "src" / "app.py")
            self.assertEqual(keel_redact.redact_path(project, inside), "src/app.py")

    def test_redact_path_falls_back_to_the_home_form(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outside = os.path.join(HOME, "notes.txt")
            result = keel_redact.redact_path(Path(tmp) / "elsewhere" / "project", outside)
            self.assertTrue(str(result).startswith("~/"), result)
            if USERNAME:
                self.assertNotIn(USERNAME, str(result))

    def test_declares_fail_open(self) -> None:
        self.assertIn("FAIL-OPEN", keel_redact.__doc__ or "")


class TestSurvey(unittest.TestCase):
    """R30: reporting is total, refusal is narrow, exit is always 0."""

    def _fake_home(self, root: Path) -> Path:
        home = root / "home"
        settings = home / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write|Edit|Bash",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"python {HOME}/.claude/hooks/other_gate.py",
                                    }
                                ],
                            }
                        ],
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"python {HOME}/.claude/hooks/other_stop.py",
                                    }
                                ]
                            }
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        return home

    def _quiet_home(self, root: Path) -> Path:
        """A home that registers nothing at all.

        ``_fake_home`` above registers a foreign write gate and a foreign stop
        gate, which since T167 is itself the armed-overlap CONFLICT - so a case
        whose subject is NOT that overlap has to own a quieter premise than the
        machine or the other fixture would give it.
        """
        home = root / "quiet-home"
        (home / ".claude").mkdir(parents=True)
        return home

    def test_conflict_is_flagged_with_its_migration_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".claude").mkdir(parents=True)
            (project / ".claude" / "POLICY.md").write_text("# other gate stack\n", encoding="utf-8")
            report = keel_survey.survey(project, home=self._quiet_home(root))
            self.assertEqual(len(report["conflicts"]), 1, report["conflicts"])
            conflict = report["conflicts"][0]
            self.assertEqual(conflict["kind"], "armed-overlap")
            self.assertIn("another gate stack is ARMED", conflict["detail"])
            self.assertIn(".claude/POLICY.md", conflict["detail"])
            self.assertIn("/keel:refit", conflict["migration"])
            rendered = keel_survey.render(report)
            self.assertIn("CONFLICT", rendered)
            self.assertIn("MIGRATION", rendered)

    def test_clean_tree_flags_nothing(self) -> None:
        """No foreign arming file, and no foreign registration anywhere the
        scan looks. Both halves are the premise now (T167): the fixture home
        registers nothing, so "none" is a fact this test owns end to end."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            report = keel_survey.survey(project, home=self._quiet_home(root))
            self.assertEqual(report["conflicts"], [])
            self.assertEqual(report["notes"], [], "a clean scan leaves no note")
            self.assertIn("none", keel_survey.render(report))

    def test_registration_scan_lists_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            report = keel_survey.survey(project, home=self._fake_home(root))
            events = {entry["event"] for entry in report["registrations"]}
            self.assertIn("PreToolUse", events)
            self.assertIn("Stop", events)
            scopes = {entry["scope"] for entry in report["registrations"]}
            self.assertIn("global", scopes)
            self.assertIn("plugin", scopes, "keel's own manifest must be reported too")
            lines = "\n".join(report["registration_lines"])
            self.assertIn("~", lines, "a home path in a command must be redacted")
            if USERNAME:
                self.assertNotIn(USERNAME, lines)

    def test_friction_counts_lock_denials_and_windows_them(self) -> None:
        """Only policy_lock gate_blocks count; the 7-day window uses ts;
        a malformed line is skipped, never fatal."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            fresh_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            lines = [
                json.dumps({"v": 1, "ts": old_ts, "event": "gate_block", "gate": "policy_lock"}),
                json.dumps({"v": 1, "ts": fresh_ts, "event": "gate_block", "gate": "policy_lock"}),
                json.dumps({"v": 1, "ts": fresh_ts, "event": "gate_block", "gate": "plan"}),
                json.dumps({"v": 1, "ts": fresh_ts, "event": "session_start"}),
                "{this line is not JSON and must cost exactly itself",
            ]
            audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = keel_survey.survey(project, home=self._fake_home(root))
            self.assertEqual(report["friction"]["lock_denials_total"], 2)
            self.assertEqual(report["friction"]["lock_denials_recent"], 1)
            rendered = keel_survey.render(report)
            self.assertIn("2 policy-lock denial(s) on record", rendered)
            self.assertIn("1 in the last 7 days", rendered)

    def test_friction_zero_is_an_explicit_line_not_silence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            report = keel_survey.survey(project, home=self._fake_home(root))
            self.assertEqual(report["friction"]["lock_denials_total"], 0)
            self.assertEqual(report["friction"]["lock_denials_recent"], 0)
            self.assertIn(
                "0 policy-lock denial(s) on record", keel_survey.render(report)
            )

    def test_lock_config_reports_defaults_when_the_section_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
            )
            report = keel_survey.survey(project, home=self._fake_home(root))
            self.assertFalse(report["lock_config"]["present"])
            self.assertIn("defaults", keel_survey.render(report))

    def test_lock_config_reports_the_tighten_and_relax_deviations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "---\ntier: 2\n---\n\n# policy\n\n"
                "## Policy lock\n\nlock:\n- src/generated\n\n"
                "relax:\n- release-version-bump\n",
                encoding="utf-8",
            )
            report = keel_survey.survey(project, home=self._fake_home(root))
            lock = report["lock_config"]
            self.assertTrue(lock["present"])
            self.assertTrue(lock["valid"])
            self.assertEqual(lock["tightened"], ("src/generated",))
            self.assertEqual(lock["relaxed"], ("release-version-bump",))
            rendered = keel_survey.render(report)
            self.assertIn("src/generated", rendered)
            self.assertIn("release-version-bump", rendered)

    def test_lock_config_reports_an_invalid_section_and_names_why(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "---\ntier: 2\n---\n\n## Policy lock\n\nrelax:\n- teleport\n",
                encoding="utf-8",
            )
            report = keel_survey.survey(project, home=self._fake_home(root))
            lock = report["lock_config"]
            self.assertTrue(lock["present"])
            self.assertFalse(lock["valid"])
            self.assertIn("teleport", " ".join(lock["errors"]))
            rendered = keel_survey.render(report)
            self.assertIn("INVALID", rendered)
            self.assertIn("teleport", rendered)

    def test_the_override_nag_names_the_restore_step_whenever_the_switch_is_on(self) -> None:
        """The switch decides, and only the switch (T167 accept 4).

        Every assertion about the ARMED direction is kept exactly as it was.
        The unarmed one is inverted on purpose: it used to pin "no lock, no
        nag", and that was the state the survey was blind in - ``/keel:lay``
        runs its survey on a project that is unarmed BY DEFINITION, so a switch
        already set on a tree about to be armed a minute later was the one case
        the old condition swallowed.
        """
        self.assertEqual(
            keel_survey.override_report(True, {"KEEL_OVERRIDE": "on"}),
            keel_gate.OVERRIDE_REMINDER,
        )
        self.assertIn("Restore the lock", keel_survey.override_report(True, {"KEEL_OVERRIDE": "on"}))
        self.assertEqual(keel_survey.override_report(True, {"KEEL_OVERRIDE": "off"}), "")
        self.assertEqual(keel_survey.override_report(True, {}), "")
        self.assertEqual(
            keel_survey.override_report(False, {"KEEL_OVERRIDE": "on"}),
            keel_gate.OVERRIDE_REMINDER,
            "a switch set before arming is exactly the state that matters",
        )
        self.assertEqual(keel_survey.override_report(False, {"KEEL_OVERRIDE": "off"}), "")
        self.assertEqual(keel_survey.override_report(False, {}), "")

    def test_friction_counts_bypasses_apart_from_denials(self) -> None:
        """A bypass is not a denial: it must be reported under its own label."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            old_ts = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            fresh_ts = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            lines = [
                json.dumps({"v": 1, "ts": old_ts, "event": "gate_bypass", "gate": "policy_lock"}),
                json.dumps({"v": 1, "ts": fresh_ts, "event": "gate_bypass", "gate": "policy_lock"}),
                json.dumps({"v": 1, "ts": fresh_ts, "event": "gate_block", "gate": "policy_lock"}),
            ]
            audit.write_text("\n".join(lines) + "\n", encoding="utf-8")
            report = keel_survey.survey(project, home=self._fake_home(root))
            self.assertEqual(report["friction"]["lock_bypasses_total"], 2)
            self.assertEqual(report["friction"]["lock_bypasses_recent"], 1)
            self.assertEqual(report["friction"]["lock_denials_total"], 1)
            rendered = keel_survey.render(report)
            self.assertIn("2 policy-lock bypass(es) via KEEL_OVERRIDE on record", rendered)
            self.assertIn("a bypass is not a denial", rendered)

    def test_budget_is_remeasured_not_quoted(self) -> None:
        report = keel_survey.survey(REPO_ROOT)
        self.assertIsInstance(report["budget"]["tokens"], int)
        self.assertGreater(report["budget"]["tokens"], 0)
        self.assertEqual(report["budget"]["violations"], [])

    def test_versions_agree(self) -> None:
        version = keel_survey.version_report()
        self.assertTrue(version["agrees"], version)
        self.assertIn("claude-code", version["built_against"])

    def test_this_repo_reports_the_manifests_edition_and_the_trees(self) -> None:
        """This repository's own plugin.json name is 'keel' - the standard
        edition - and the tree carries every layer, reviewers and viewer
        included, so it IS a fleet tree calling itself standard.

        Until T168 this test asserted ``edition : standard`` and passed, which
        is the whole defect it now guards against: the label came from the
        manifest's ``name`` and no part of it was derived from the tree, so a
        source repository carrying all five features reported the edition of
        the bundle it happens to be named after. Both halves are asserted here
        - the manifest's own claim keeps its key and its wording, and the
        rendered line names the derived edition with the manifest's claim
        beside it, because a disagreement that is not printed is not reported.
        """
        version = keel_survey.version_report()
        self.assertEqual(version["edition"], "standard")
        self.assertEqual(version["edition_derived"], "fleet")
        report = keel_survey.survey(REPO_ROOT)
        rendered = keel_survey.render(report)
        self.assertIn("edition : fleet", rendered)
        self.assertIn("manifest says: standard", rendered)

    def test_edition_label_recognizes_all_four_edition_names(self) -> None:
        self.assertEqual(keel_survey.edition_label("keel-core"), "core")
        self.assertEqual(keel_survey.edition_label("keel"), "standard")
        self.assertEqual(keel_survey.edition_label("keel-govern"), "govern")
        self.assertEqual(keel_survey.edition_label("keel-fleet"), "fleet")

    def test_edition_label_reports_an_unknown_name_verbatim_not_an_error(self) -> None:
        """An unrecognized plugin.json name is news, not a crash (R30)."""
        self.assertEqual(
            keel_survey.edition_label("some-fork"), "some-fork (unrecognized)"
        )
        self.assertEqual(keel_survey.edition_label(""), "(none)")

    def test_cli_always_exits_zero_even_with_a_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".claude").mkdir(parents=True)
            (project / ".claude" / "POLICY.md").write_text("# other gate stack\n", encoding="utf-8")
            result = run_cli(["survey", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CONFLICT", result.stdout)

    def test_startup_mode_prints_at_most_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(["survey", "--project", str(REPO_ROOT), "--startup"], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.strip().splitlines()), 1, result.stdout)

    def test_declares_fail_open(self) -> None:
        self.assertIn("FAIL-OPEN", keel_survey.__doc__ or "")


def run_cli(args: list[str], scratch: Path) -> subprocess.CompletedProcess:
    """Run scripts/keel.py exactly as a caller would, and return the result."""
    return subprocess.run(
        [sys.executable, "-B", str(KEEL_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch),
        cwd=str(scratch),
        timeout=120,
        check=False,
    )


def iso(offset_seconds: int) -> str:
    """A keel-format UTC timestamp, offset from now."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class TestAttest(unittest.TestCase):
    """[~] is verified against the audit log here exactly as at stop time."""

    def _project(self, tmp: Path, ledger: str, extra: list[dict] | None = None) -> tuple[Path, str]:
        project = tmp / "project"
        session = uuid.uuid4().hex
        plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(ledger, encoding="utf-8")
        lines: list[dict] = [
            {"v": 1, "ts": iso(-600), "event": "session_start", "session": session},
            {
                "v": 1,
                "ts": iso(-500),
                "event": "handoff_start",
                "session": session,
                "tool_use_id": "u1",
                "subagent_type": "executor",
                "description": "T1: build the thing",
                "prompt_head": "TASK T1 - build the thing",
            },
            {
                "v": 1,
                "ts": iso(-400),
                "event": "handoff_end",
                "session": session,
                "tool_use_id": "u1",
                "subagent_type": "executor",
                "description": "T1: build the thing",
                "prompt_head": "TASK T1 - build the thing",
            },
        ]
        lines.extend(extra or [])
        audit = project.joinpath(*AUDIT_RELPATH)
        audit.parent.mkdir(parents=True)
        with open(audit, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        return project, session

    def test_clean_ledger_reconciles_and_exits_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp), "- [x] T1: build the thing | route: executor | AC: tests pass\n"
            )
            report = keel_attest.attest(project, session)
            self.assertTrue(report["clean"], report["discrepancies"])
            self.assertEqual(report["tasks"][0]["verdict"], "ATTESTED")
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_fabricated_inflight_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1: build the thing | route: executor | AC: tests pass\n"
                "- [~] T2: still running | route: executor | AC: none\n",
            )
            report = keel_attest.attest(project, session)
            self.assertFalse(report["clean"])
            verdicts = {task["id"]: task["verdict"] for task in report["tasks"]}
            self.assertEqual(verdicts["T2"], "UNVERIFIED-INFLIGHT")
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("UNVERIFIED-INFLIGHT", result.stdout)

    def test_completed_task_with_no_handoff_is_unattested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1: build the thing | route: executor | AC: tests pass\n"
                "- [x] T9: claimed done | route: executor | AC: none\n",
            )
            report = keel_attest.attest(project, session)
            verdicts = {task["id"]: task["verdict"] for task in report["tasks"]}
            self.assertEqual(verdicts["T9"], "UNATTESTED")
            self.assertFalse(report["clean"])

    def test_an_open_handoff_verifies_an_inflight_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [~] T5: running now | route: executor | AC: none\n",
            )
            audit = project.joinpath(*AUDIT_RELPATH)
            with open(audit, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        {
                            "v": 1,
                            "ts": iso(-30),
                            "event": "handoff_start",
                            "session": session,
                            "tool_use_id": "u2",
                            "subagent_type": "executor",
                            "description": "T5: running now",
                            "prompt_head": "TASK T5",
                        }
                    )
                    + "\n"
                )
            report = keel_attest.attest(project, session)
            self.assertEqual(report["tasks"][0]["verdict"], "IN-FLIGHT")
            self.assertTrue(report["clean"])

    def test_self_routed_task_is_not_a_discrepancy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp), "- [x] T4: record the decision | route: orchestrator | AC: file\n"
            )
            report = keel_attest.attest(project, session)
            self.assertTrue(report["tasks"][0]["verdict"].startswith("SELF"))
            self.assertTrue(report["clean"])

    def test_contract_shaped_ledger_parses_ids_and_routes(self) -> None:
        """A ``templates/keel-plan-contract.md`` ledger: ``Tn`` id after the
        checkbox, no punctuation; route on an indented ``- Route:`` sub-bullet
        that also carries a trailing ``; files: ...`` clause. Both must
        resolve, not fall back to ``(unnamed)``/``UNROUTED``."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1 build the thing\n"
                "  - Route: standard (executor); files: some/path.py\n"
                "  - Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T1")
            self.assertEqual(task["route"], "standard (executor)")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("UNROUTED", result.stdout)
            self.assertNotIn("unnamed", result.stdout)

    def test_contract_shaped_self_route_is_not_a_discrepancy(self) -> None:
        """A bare ``- Route: orchestrator`` sub-bullet (no parens, no ``;``)."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T9 record the decision\n"
                "  - Route: orchestrator\n"
                "  - Accept: file written\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T9")
            self.assertEqual(task["route"], "orchestrator")
            self.assertTrue(task["verdict"].startswith("SELF"))
            self.assertTrue(report["clean"])

    def test_contract_shaped_route_bullet_is_case_insensitive(self) -> None:
        """A lowercase ``- route:`` sub-bullet resolves exactly as the
        capitalized form does (convention 3). Without case-insensitive
        matching the route stays empty and a ``[x]`` task is quietly
        reclassified UNROUTED instead of reaching the attestation check."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1 build the thing\n"
                "  - route: standard (executor); files: some/path.py\n"
                "  - Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T1")
            self.assertEqual(task["route"], "standard (executor)")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])

    def test_legacy_pipe_route_wins_over_sub_bullet(self) -> None:
        """Both shapes on one task: the legacy pipe is tried first and the
        sub-bullet is only a fallback, so the pipe value is the one reported."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1 build the thing | route: executor | AC: tests pass\n"
                "  - Route: orchestrator\n"
                "  - Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T1")
            self.assertEqual(task["route"], "executor")
            self.assertEqual(task["verdict"], "ATTESTED")

    def test_legacy_pipe_route_still_parses(self) -> None:
        """The pre-existing inline shape (``| route: ... |``) keeps working -
        widening the contract-shape parser must never narrow this one."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp), "- [x] T1: build the thing | route: executor | AC: tests pass\n"
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["id"], "T1")
            self.assertEqual(task["route"], "executor")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"])

    def test_ladder_at_hard_cap_stays_clean(self) -> None:
        """R32: a base task whose escalation series reaches exactly round
        FIX_ROUND_HARD_CAP (the bare id plus 5 suffixed retries, ``T9`` ..
        ``T9e``) is within the ladder - no ladder finding, clean report."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = "".join(
                f"- [ ] T9{suffix} fix attempt\n" for suffix in ("", "a", "b", "c", "d", "e")
            )
            project, session = self._project(Path(tmp), ledger)
            report = keel_attest.attest(project, session)
            self.assertTrue(report["clean"], report["discrepancies"])
            plan_path = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
            self.assertEqual(
                keel_attest.ladder_rounds(keel_attest.parse_plan(plan_path))["T9"],
                keel_attest.FIX_ROUND_HARD_CAP,
            )
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ladder_past_hard_cap_is_a_discrepancy(self) -> None:
        """One more round than the cap (``T9f``, round 6) - a finding, and a
        non-clean, non-zero exit."""
        with tempfile.TemporaryDirectory() as tmp:
            ledger = "".join(
                f"- [ ] T9{suffix} fix attempt\n"
                for suffix in ("", "a", "b", "c", "d", "e", "f")
            )
            project, session = self._project(Path(tmp), ledger)
            report = keel_attest.attest(project, session)
            self.assertFalse(report["clean"])
            verdicts = [item["verdict"] for item in report["discrepancies"]]
            self.assertTrue(
                any(v.startswith(keel_attest.LADDER_CAP_VERDICT_PREFIX) for v in verdicts),
                verdicts,
            )
            self.assertIn(
                f"(6 rounds, cap {keel_attest.FIX_ROUND_HARD_CAP})",
                "".join(verdicts),
            )
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(keel_attest.LADDER_CAP_VERDICT_PREFIX, result.stdout)

    def test_fix_round_of_defines_bare_id_as_round_zero(self) -> None:
        """The round accounting itself, in isolation from the ledger."""
        self.assertEqual(keel_attest.fix_round_of("T9"), 0)
        self.assertEqual(keel_attest.fix_round_of("T9A"), 1)
        self.assertEqual(keel_attest.fix_round_of("T9E"), 5)
        self.assertEqual(keel_attest.fix_round_of("T9F"), 6)

    def test_fix_round_of_maps_a_doubled_suffix_spreadsheet_style(self) -> None:
        """``aa`` is 27, not 1 and not 0: a doubled suffix is counted, so it
        cannot present itself as an early round or as no round at all."""
        self.assertEqual(keel_attest.fix_round_of("T9AA"), 27)
        self.assertEqual(keel_attest.fix_round_of("T9AB"), 28)
        self.assertEqual(keel_attest.fix_round_of("T9ZZ"), 702)

    def test_uppercase_suffix_counts_as_its_round_and_trips_the_cap(self) -> None:
        """An uppercase escalation suffix is the same round as its lowercase
        spelling (convention 3). ``T9F`` is round 6, one past the cap - before
        the widening it failed the id shape, parsed as ``(unnamed)``, and left
        the ladder unaccounted with a clean report."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [ ] T9 fix attempt\n- [ ] T9F fix attempt\n",
            )
            report = keel_attest.attest(project, session)
            self.assertEqual(report["tasks"][1]["id"], "T9F")
            self.assertFalse(report["clean"])
            verdicts = "".join(item["verdict"] for item in report["discrepancies"])
            self.assertIn(keel_attest.LADDER_CAP_VERDICT_PREFIX, verdicts)
            self.assertIn(f"(6 rounds, cap {keel_attest.FIX_ROUND_HARD_CAP})", verdicts)
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_doubled_suffix_is_flagged_not_dropped(self) -> None:
        """``T9aa`` parses as round 27 and therefore trips the cap. The point
        is that a malformed-looking suffix cannot escape ladder accounting."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [ ] T9 fix attempt\n- [ ] T9aa fix attempt\n",
            )
            report = keel_attest.attest(project, session)
            self.assertEqual(report["tasks"][1]["id"], "T9AA")
            self.assertEqual(keel_attest.fix_round_of(report["tasks"][1]["id"]), 27)
            self.assertFalse(report["clean"])
            verdicts = "".join(item["verdict"] for item in report["discrepancies"])
            self.assertIn(keel_attest.LADDER_CAP_VERDICT_PREFIX, verdicts)
            self.assertIn("(27 rounds", verdicts)
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_idlike_token_that_cannot_parse_is_its_own_discrepancy(self) -> None:
        """A token shaped like a suffixed id that no id rule accepts (three
        suffix letters) is reported as UNPARSEABLE TASK ID rather than
        vanishing into ``(unnamed)`` where nothing accounts for it."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T9 fix attempt\n- [x] T9aaa fix attempt\n",
            )
            report = keel_attest.attest(project, session)
            row = report["tasks"][1]
            self.assertFalse(row["id"].startswith("T9AAA"))
            self.assertEqual(
                row["verdict"], f"{keel_attest.UNPARSEABLE_ID_VERDICT_PREFIX} (T9aaa)"
            )
            self.assertTrue(keel_attest.is_discrepancy_verdict(row["verdict"]))
            self.assertFalse(report["clean"])
            self.assertIn(row, report["discrepancies"])
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn(keel_attest.UNPARSEABLE_ID_VERDICT_PREFIX, result.stdout)

    def test_prose_task_line_without_an_id_stays_merely_unnamed(self) -> None:
        """The other direction: a task line carrying no id-shaped token at all
        keeps its long-standing ``(unnamed)`` label and raises nothing - that
        path is visible in the ledger table and is not a parse failure."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = self._project(
                Path(tmp),
                "- [x] T1: build the thing | route: executor | AC: tests pass\n"
                "- [x] Time spent auditing the log | route: orchestrator\n",
            )
            report = keel_attest.attest(project, session)
            row = report["tasks"][1]
            self.assertTrue(row["id"].startswith("(unnamed"))
            self.assertNotIn(
                keel_attest.UNPARSEABLE_ID_VERDICT_PREFIX, row["verdict"]
            )
            self.assertTrue(report["clean"], report["discrepancies"])
            result = run_cli(
                ["attest", "--project", str(project), "--session", session[:8]],
                Path(tmp),
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True)
            audit.write_text(
                json.dumps({"v": 1, "ts": iso(0), "event": "session_start", "session": "abc"})
                + "\n",
                encoding="utf-8",
            )
            result = run_cli(["attest", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 2, result.stdout)

    def test_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_attest.__doc__ or "")


class TestLeakCheck(unittest.TestCase):
    """Both directions: a seeded key is caught, a clean tree passes."""

    def _repo(self, tmp: Path, files: dict[str, str]) -> Path:
        root = tmp / "repo"
        root.mkdir()
        for name, text in files.items():
            (root / name).write_text(text, encoding="utf-8")
        for args in (["git", "init"], ["git", "add", "-A"]):
            result = subprocess.run(
                args, cwd=str(root), capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
        return root

    def test_clean_tree_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"notes.md": "# notes\nnothing to see here\n"})
            result = run_cli(["leak-check", "--repo-root", str(root)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("clean", result.stdout)

    def test_seeded_key_is_caught_and_masked(self) -> None:
        secret = "sk-ant-" + "api03-AAAAbbbbCCCCddddEEEE1111"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"config.py": f'KEY = "{secret}"\n'})
            result = run_cli(["leak-check", "--repo-root", str(root)], Path(tmp))
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("anthropic_key", result.stdout)
            self.assertNotIn(secret, result.stdout, "a scanner may never print the secret")

    def test_home_path_is_caught(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"log.jsonl": '{"p": "C:\\\\Users\\\\someone\\\\x"}\n'})  # keel-leak: ignore - fixture home path, input to the redactor's own test
            result = run_cli(["leak-check", "--repo-root", str(root)], Path(tmp))
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("home_path", result.stdout)

    def test_suppression_comment_is_honoured(self) -> None:
        secret = "sk-ant-" + "api03-AAAAbbbbCCCCddddEEEE1111"
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(Path(tmp), {"doc.md": f"example: {secret}  <!-- keel-leak: ignore -->\n"})
            result = run_cli(["leak-check", "--repo-root", str(root)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_masking_never_returns_the_input(self) -> None:
        for secret in ("abcdefghijklmnop", "sk-ant-0123456789"):  # keel-leak: ignore - synthetic key that is an INPUT to this detector's test
            with self.subTest(secret=secret):
                self.assertNotEqual(keel_leak_check.mask(secret), secret)

    def test_scanner_error_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "not-a-repo"
            plain.mkdir()
            result = run_cli(["leak-check", "--repo-root", str(plain)], plain)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_leak_check.__doc__ or "")


class TestDeclaredFailurePolicy(unittest.TestCase):
    """R3 / convention 12: every wave-2 file declares its policy, and keeps it."""

    def test_every_new_file_declares_a_policy(self) -> None:
        expected = {
            "hooks/keel_redact.py": "FAIL-OPEN",
            "hooks/keel_capture.py": "FAIL-OPEN",
            "hooks/keel_session.py": "FAIL-OPEN",
            "scripts/keel.py": "FAIL-CLOSED",
            "scripts/keel_survey.py": "FAIL-OPEN",
            "scripts/keel_attest.py": "FAIL-CLOSED",
            "scripts/keel_leak_check.py": "FAIL-CLOSED",
        }
        for relative, policy in expected.items():
            with self.subTest(file=relative):
                source = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(policy, source.split('"""')[1], relative)

    def test_capture_fails_open_on_an_unwritable_audit(self) -> None:
        """The declaration, observed: a broken append is stderr plus exit 0."""
        from keel_events import KeelEvent  # noqa: PLC0415 - path set at import time

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()
            event = KeelEvent(
                kind="post_tool",
                cwd=project,
                session_id="s",
                tool_name="Write",
                file_paths=("a.py",),
                raw={"hook_event_name": "PostToolUse"},
            )
            original = keel_capture.append_audit

            def boom(*args: Any, **kwargs: Any) -> None:
                raise OSError("deliberate fault")

            keel_capture.append_audit = boom
            try:
                with no_real_hook_error_log():
                    self.assertEqual(keel_capture.run(event), 0)
            finally:
                keel_capture.append_audit = original

    def test_session_fails_open_on_an_unwritable_audit(self) -> None:
        from keel_events import KeelEvent  # noqa: PLC0415

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()
            event = KeelEvent(kind="session_start", cwd=project, session_id="abcdef123456")
            original = keel_session.append_audit

            def boom(*args: Any, **kwargs: Any) -> None:
                raise OSError("deliberate fault")

            keel_session.append_audit = boom
            try:
                with no_real_fleet_registry(), no_real_hook_error_log():
                    self.assertEqual(keel_session.run(event), 0)
            finally:
                keel_session.append_audit = original


class TestWave2Registrations(unittest.TestCase):
    """Convention 11 in the generated document: gates block, observers do not."""

    def _hooks(self) -> dict:
        return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))

    def test_every_registered_subcommand_exists(self) -> None:
        import keel_hook  # noqa: PLC0415 - imported after the path insert above

        registered = {entry.subcommand for entry in keel_gen_hooks.ENTRIES}
        self.assertEqual(
            registered,
            {
                "session",
                "gate",
                "capture",
                "stop",
                "subagent_stop",
                # T228's two compaction-survival observers.
                "prompt",
                "precompact",
            },
        )
        self.assertTrue(registered.issubset(set(keel_hook.SUBCOMMANDS)))
        self.assertIn("spike", keel_hook.SUBCOMMANDS, "the spike stays available")

    def test_the_eight_events_are_registered(self) -> None:
        """Five since wave 2, six since the delegation-finish subscription,
        eight since the compaction-survival layer.

        ``SubagentStop`` is the sixth, and the closed set is kept closed on
        purpose: an event silently dropped from this table is exactly the
        defect that left keel's stop consumer with no producer for several
        waves. What that registration must then DO is asserted in
        tests/test_keel_subagent_stop.py, end to end against a real log.

        ``UserPromptSubmit`` and ``PreCompact`` are the seventh and eighth
        (T228). They are also the two whose ARRIVAL was gated on a decision
        rather than on code: each is another copy of the bootstrap in the
        always-loaded budget, which is why
        ``.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md``
        was ratified before this table grew. What they must DO is asserted in
        tests/test_keel_compaction_t228.py.
        """
        self.assertEqual(
            set(self._hooks()["hooks"]),
            {
                "SessionStart",
                "SessionEnd",
                "PreToolUse",
                "PostToolUse",
                "Stop",
                "SubagentStop",
                "UserPromptSubmit",
                "PreCompact",
            },
        )

    #: The two events whose registration is an OBSERVER that is nevertheless
    #: SYNCHRONOUS, because its stdout is context: ``SessionStart`` (the
    #: castoff block) and, since T473, ``UserPromptSubmit`` (the context
    #: nudge). Named once and used by both cases below, so a third one cannot
    #: be added to one list and forgotten in the other.
    CONTEXT_EVENTS = ("SessionStart", "UserPromptSubmit")

    def test_gates_are_synchronous_and_observers_are_not(self) -> None:
        for entry in keel_gen_hooks.ENTRIES:
            with self.subTest(event=entry.event, subcommand=entry.subcommand):
                if entry.subcommand in ("gate", "stop"):
                    self.assertFalse(entry.is_async, "a gate that does not block is not a gate")
                elif entry.event in self.CONTEXT_EVENTS:
                    self.assertFalse(entry.is_async, "injected context may not arrive late")
                else:
                    self.assertTrue(entry.is_async, "an observer must not make the user wait")

    def test_the_async_flag_reaches_the_generated_document(self) -> None:
        document = self._hooks()["hooks"]
        for hook in document["PostToolUse"]:
            self.assertTrue(hook["hooks"][0].get("async"), hook)
        for event in self.CONTEXT_EVENTS:
            for hook in document[event]:
                self.assertNotIn("async", hook["hooks"][0], event)
        for hook in document["Stop"]:
            self.assertNotIn("async", hook["hooks"][0])

    def test_delegation_and_state_change_matchers_are_registered(self) -> None:
        document = self._hooks()["hooks"]
        matchers = {
            (event, group.get("matcher"))
            for event, groups in document.items()
            for group in groups
        }
        self.assertIn(("PostToolUse", keel_gen_hooks.STATE_CHANGING_MATCHER), matchers)
        # The capture rows watch the delegation tools AND the message-send a
        # resume goes through (T124), so what has to be registered is the
        # wider matcher - and the delegation tools have to still be inside it.
        self.assertIn(("PostToolUse", keel_gen_hooks.HANDOFF_MATCHER), matchers)
        self.assertIn(("PreToolUse", keel_gen_hooks.HANDOFF_MATCHER), matchers)
        for tool in keel_gen_hooks.DELEGATION_MATCHER.split("|"):
            self.assertIn(tool, keel_gen_hooks.HANDOFF_MATCHER.split("|"))

    def test_committed_document_matches_the_generator(self) -> None:
        self.assertEqual(keel_gen_hooks.verify(), [])


if __name__ == "__main__":
    unittest.main()
