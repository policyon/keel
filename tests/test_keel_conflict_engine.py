#!/usr/bin/env python3
"""The conflict engine reads the FIELD, not the filename (T167, R30).

Contract
--------
Reads   : ``scripts/keel_survey.py``'s ownership and conflict derivation, the
          castoff conflict line in ``hooks/keel_session.py``, and
          ``skills/lay/SKILL.md`` as text. Every case that asserts a conflict
          COUNT builds its own project AND its own fixture home, because the
          scan reads the user's settings as well as the project's: a count
          inherited from the machine running the suite would be an ambient
          fact rather than a test. This repository's own tree is read only
          where the subject IS this installation's ownership of its own hooks.
Emits   : unittest results only, plus the lay skill's measured word count so
          the number is read in the log rather than assumed.
Writes  : nothing outside temporary directories it creates and removes.

Why this file exists
--------------------
Until T167 the refusal was a FILENAME test: another stack's arming file in
the surveyed project. A survey therefore printed the other stack's write gate
and stop gate under REGISTRATIONS and said "none" under CONFLICTS in the same
breath - which is what it did on 2026-08-18, in front of a session assessing
whether to adopt keel. The two orders in which two gate stacks come to overlap
are tested here together, because only one of them was ever caught: the other
stack arriving FIRST was refused at arming time, and the other stack arriving
SECOND was never mentioned again.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding. Path separators are built with ``chr(92)`` where a backslash is the
subject, never typed into a pattern that a shell or a heredoc could eat.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

import sys  # noqa: E402  - the two paths below must be set before the imports

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_session  # noqa: E402
import keel_survey  # noqa: E402
from keel_redact import redact  # noqa: E402
from keel_registry_guard import no_real_fleet_registry  # noqa: E402

#: The backslash, built rather than typed: a ``[\\/]`` class collapses to
#: ``[\/]`` through a heredoc and then matches no Windows path at all, which
#: is a defect this repository has already paid for once.
BACKSLASH = chr(92)

#: A foreign stack's commands. Neither references any script this installation
#: ships, which is the whole of what makes them foreign - not their wording.
FOREIGN_WRITE_COMMAND = "python /elsewhere/gates/plan_gate.py"
FOREIGN_STOP_COMMAND = "python /elsewhere/gates/stop_gate.py"

#: keel's own command, in the shape its plugin manifest actually uses: the
#: installation root arrives as an environment variable the survey never
#: expands, so ownership has to be visible in the RELATIVE tail.
OWN_PLUGIN_COMMAND = 'exec python "${CLAUDE_PLUGIN_ROOT}/hooks/keel_hook.py" gate'


def hooks_document(
    pre_matcher: str | None = "Write|Edit|MultiEdit|NotebookEdit|Bash",
    pre_command: str | None = FOREIGN_WRITE_COMMAND,
    stop_command: str | None = None,
    pre_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One settings/manifest document, holding exactly what a case needs.

    ``pre_entry`` writes a raw PreToolUse entry verbatim, which is how the
    no-readable-command case states its premise without a special path
    through the helper.
    """
    hooks: dict[str, Any] = {}
    if pre_entry is not None:
        hooks["PreToolUse"] = [{"matcher": pre_matcher or "", "hooks": [pre_entry]}]
    elif pre_command is not None:
        hooks["PreToolUse"] = [
            {
                "matcher": pre_matcher or "",
                "hooks": [{"type": "command", "command": pre_command}],
            }
        ]
    if stop_command is not None:
        hooks["Stop"] = [{"hooks": [{"type": "command", "command": stop_command}]}]
    return {"hooks": hooks}


def write_json(path: Path, document: dict[str, Any]) -> Path:
    """Create the parents and write one JSON document, naming its encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def quiet_home(root: Path) -> Path:
    """A home that registers nothing: present, and holding no settings file."""
    home = root / "fixture-home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    return home


def home_settings(home: Path) -> Path:
    """Where the USER-WIDE registrations live under a fixture home."""
    return home / ".claude" / "settings.json"


def project_settings(project: Path) -> Path:
    """Where a PROJECT's own registrations live."""
    return project / ".claude" / "settings.json"


def plugin_manifest(home: Path) -> Path:
    """Where an installed plugin's hook manifest lives under a fixture home."""
    return home / ".claude" / "plugins" / "other-stack" / "hooks" / "hooks.json"


def arm(project: Path, *, tier: int = 2) -> None:
    """Arm keel over a scratch project: creating the file IS the arming act."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---{os.linesep}tier: {tier}{os.linesep}---{os.linesep}", encoding="utf-8"
    )


def foreign_policy(project: Path) -> Path:
    """Write the other stack's arming file into the surveyed project."""
    path = keel_survey.foreign_policy_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# another gate stack\n", encoding="utf-8")
    return path


class TestOwnershipIsStructural(unittest.TestCase):
    """"keel's own" is decided from the installation on disk, never from a
    product name appearing in a command string."""

    def test_the_manifest_shape_this_installation_actually_ships_is_ours(self) -> None:
        self.assertTrue(keel_survey.command_is_own(OWN_PLUGIN_COMMAND))

    def test_the_same_path_spelled_with_backslashes_is_ours_too(self) -> None:
        """Registrations are typed on three operating systems; a separator is
        not an ownership signal. Built with ``chr(92)`` on purpose."""
        windows = 'python "' + OWN_PLUGIN_COMMAND.replace("/", BACKSLASH) + '"'
        self.assertIn(BACKSLASH, windows)
        self.assertTrue(keel_survey.command_is_own(windows))

    def test_an_absolute_path_into_this_installations_hooks_is_ours(self) -> None:
        absolute = f'python "{REPO_ROOT / "hooks" / "keel_hook.py"}" gate'
        self.assertTrue(keel_survey.command_is_own(absolute))
        self.assertTrue(
            keel_survey.command_is_own(absolute.replace("/", BACKSLASH)),
            "the same path with the other separator is the same path",
        )

    def test_a_sibling_directory_sharing_a_prefix_is_foreign(self) -> None:
        """The boundary the first review found missing: an unbounded substring
        test answers "ours" for a rival living NEXT TO keel's hooks directory,
        and a command wrongly called ours never reaches the conflict report at
        all. Both separators, because a Windows registration is the case a
        collapsed pattern silently exempts."""
        for sibling in ("hooks-legacy", "hooksold", "hooks2", "hooks.bak"):
            native = str(REPO_ROOT / sibling / "rival_gate.py")
            for spelling in (native, native.replace("/", BACKSLASH)):
                with self.subTest(sibling=sibling, spelling=spelling):
                    self.assertFalse(
                        keel_survey.command_is_own(f'python "{spelling}"'), spelling
                    )

    def test_a_genuine_script_inside_this_installations_hooks_is_ours(self) -> None:
        """The other direction of the same boundary: the real directory, with a
        real script in it, must still read as ours."""
        for name in ("keel_hook.py", "keel_gate.py", "keel_session.py"):
            target = REPO_ROOT / "hooks" / name
            self.assertTrue(target.is_file(), f"premise: {name} ships here")
            for separator in ("/", BACKSLASH):
                spelling = str(target) if separator == "/" else str(target).replace("/", BACKSLASH)
                with self.subTest(name=name, separator=separator):
                    self.assertTrue(keel_survey.command_is_own(f'python "{spelling}"'))

    def test_a_script_name_glued_to_a_longer_segment_is_foreign(self) -> None:
        """The same defect on the other signal: ``hooks/keel_hook.py`` must not
        be satisfied by a directory that merely ENDS in ``hooks``, nor by a
        longer file name that merely STARTS with the script's."""
        for command in (
            "python /elsewhere/badhooks/keel_hook.py",
            "python /elsewhere/myhooks/keel_hook.py session",
            "python /elsewhere/hooks/keel_hook.pyc",
            "python /elsewhere/hooks/keel_hook.py.bak",
            "python /elsewhere/hooks/keel_hook.py-old",
        ):
            with self.subTest(command=command):
                self.assertFalse(keel_survey.command_is_own(command), command)

    def test_a_second_copy_of_this_installation_still_reads_as_ours(self) -> None:
        """The documented tolerance, pinned so it stays a decision rather than
        an accident of the boundary rule: the plugin manifest's own command
        carries no root, so any ``…/hooks/<shipped script>`` is this stack."""
        self.assertTrue(keel_survey.command_is_own("python /anywhere/hooks/keel_hook.py"))

    def test_every_occurrence_is_examined_not_only_the_first(self) -> None:
        """A command can name several paths; the bounded one may come second."""
        haystack = keel_survey._slashed(
            "python /x/badhooks/keel_hook.pyc || python /y/hooks/keel_hook.py"
        )
        self.assertTrue(keel_survey.mentions_path(haystack, "hooks/keel_hook.py"))
        self.assertFalse(
            keel_survey.mentions_path(
                keel_survey._slashed("python /x/badhooks/keel_hook.pyc"),
                "hooks/keel_hook.py",
            )
        )

    def test_mentions_path_treats_the_ends_of_the_command_as_boundaries(self) -> None:
        self.assertTrue(keel_survey.mentions_path("hooks/keel_hook.py", "hooks/keel_hook.py"))
        self.assertFalse(keel_survey.mentions_path("hooks/keel_hook.py", ""))

    def test_a_command_that_merely_mentions_the_product_name_is_not_ours(self) -> None:
        """The clause this test exists for: ownership is not a word search. A
        foreign stack installed in a directory that happens to carry keel's
        name still runs none of this installation's scripts."""
        self.assertFalse(keel_survey.command_is_own("python /elsewhere/keel/plan_gate.py"))
        self.assertFalse(keel_survey.command_is_own("keel"))

    def test_a_blank_or_absent_command_is_not_ours(self) -> None:
        for command in ("", "   ", keel_survey.NO_COMMAND):
            with self.subTest(command=command):
                self.assertFalse(keel_survey.command_is_own(command))

    def test_an_installation_whose_hooks_cannot_be_read_claims_nothing(self) -> None:
        """The fail-closed direction for a refusal that protects the user: an
        installation that cannot list its own hooks claims no command, so a
        stopping registration reads as foreign and the reader sees a conflict
        they can dismiss - never a silence they cannot."""
        with tempfile.TemporaryDirectory() as tmp:
            nowhere = Path(tmp) / "no-such-installation"
            self.assertEqual(keel_survey.own_hook_scripts(nowhere), ())
            self.assertFalse(keel_survey.command_is_own(OWN_PLUGIN_COMMAND, nowhere))

    def test_this_installation_lists_its_own_hook_scripts_from_disk(self) -> None:
        scripts = keel_survey.own_hook_scripts()
        self.assertTrue(scripts)
        for entry in scripts:
            with self.subTest(entry=entry):
                self.assertTrue(entry.startswith("hooks/"))
                self.assertTrue((REPO_ROOT / entry).is_file())

    def test_only_a_matcher_that_reaches_a_write_tool_can_stop_a_write(self) -> None:
        for matcher, expected in (
            ("", True),
            ("   ", True),
            ("*", True),
            (".*", True),
            ("Write|Edit|MultiEdit|NotebookEdit|Bash", True),
            ("Bash", True),
            ("NotebookEdit", True),
            ("Task|Agent|SendMessage", False),
            ("Read|Glob|Grep", False),
        ):
            with self.subTest(matcher=matcher):
                self.assertEqual(keel_survey.matcher_gates_writes(matcher), expected)


class TestConflictsAreDerivedFromRegistrations(unittest.TestCase):
    """T167 accept 1: the registration set is the authority, and the filename
    is only a fast path onto the same verdict."""

    def _survey(self, project: Path, home: Path) -> dict[str, Any]:
        return keel_survey.survey(project, home=home)

    def test_a_foreign_write_gate_alone_raises_the_conflict(self) -> None:
        """The whole point: no ``.claude/POLICY.md`` anywhere, and the refusal
        still fires - because a stack that never wrote an arming file into this
        project still holds the event that stops writes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            settings = write_json(home_settings(home), hooks_document())
            self.assertFalse(keel_survey.foreign_policy_path(project).exists())

            report = self._survey(project, home)
            self.assertEqual(len(report["conflicts"]), 1, report["conflicts"])
            conflict = report["conflicts"][0]
            self.assertEqual(conflict["kind"], "armed-overlap")
            self.assertEqual(conflict["scope"], "global")
            self.assertEqual(conflict["event"], "PreToolUse")
            self.assertIn(redact(str(settings)), conflict["detail"])
            rendered = keel_survey.render(report)
            self.assertIn("CONFLICT", rendered)
            self.assertIn("MIGRATION", rendered)

    def test_a_foreign_stop_registration_alone_raises_the_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            write_json(
                home_settings(home),
                hooks_document(pre_command=None, stop_command=FOREIGN_STOP_COMMAND),
            )
            conflicts = self._survey(project, home)["conflicts"]
            self.assertEqual(len(conflicts), 1, conflicts)
            self.assertEqual(conflicts[0]["event"], "Stop")

    def test_a_delegation_observer_is_reported_and_never_refused(self) -> None:
        """Refusal stays narrow (R30): a PreToolUse hook matching delegation
        tools cannot stop a write, so it is LISTED and left alone."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            write_json(
                home_settings(home),
                hooks_document(pre_matcher="Task|Agent|SendMessage"),
            )
            report = self._survey(project, home)
            self.assertEqual(report["conflicts"], [])
            self.assertTrue(report["registrations"], "reporting is still total")
            self.assertIn("none", keel_survey.render(report))

    def test_keels_own_command_in_the_users_own_settings_is_not_a_conflict(self) -> None:
        """Ownership is decided by the command, not by the scope it sits in: a
        user who registers keel globally has one stack, not two."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            write_json(
                home_settings(home),
                hooks_document(
                    pre_command=OWN_PLUGIN_COMMAND,
                    stop_command=OWN_PLUGIN_COMMAND.replace("gate", "stop"),
                ),
            )
            report = self._survey(project, home)
            self.assertEqual(report["conflicts"], [], report["conflicts"])
            # Both of the fixture home's own entries were seen and both were
            # judged ours; the rest of the list is this installation's own
            # manifest, which the ownership test above pins separately.
            from_home = [
                entry for entry in report["registrations"]
                if entry["source"] == redact(str(home_settings(home)))
            ]
            self.assertEqual(len(from_home), 2, report["registration_lines"])

    def test_both_signals_together_raise_both_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            foreign_policy(project)
            home = quiet_home(root)
            write_json(
                home_settings(home),
                hooks_document(stop_command=FOREIGN_STOP_COMMAND),
            )
            conflicts = self._survey(project, home)["conflicts"]
            self.assertEqual(len(conflicts), 3, conflicts)
            self.assertEqual({c["kind"] for c in conflicts}, {"armed-overlap"})
            self.assertEqual(
                [c["event"] for c in conflicts],
                ["arming file", "PreToolUse", "Stop"],
                "the fast path is reported first, then each stopping registration",
            )

    def test_a_registration_under_a_prefix_colliding_sibling_reaches_the_report(
        self,
    ) -> None:
        """The boundary fix at the surface that matters: a rival registered out
        of a directory sitting next to this installation's ``hooks/`` must be
        REFUSED, not silently adopted as keel's own."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            rival = str(REPO_ROOT / "hooks-legacy" / "plan_gate.py")
            write_json(
                home_settings(home), hooks_document(pre_command=f'python "{rival}"')
            )
            conflicts = self._survey(project, home)["conflicts"]
            self.assertEqual(len(conflicts), 1, conflicts)
            self.assertEqual(conflicts[0]["kind"], "armed-overlap")

    def test_an_entry_with_no_readable_command_is_a_note_not_a_silence(self) -> None:
        """Neither ours nor safely foreign: an entry keel cannot read the
        command of makes the count a FLOOR, and every surface says so."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            write_json(
                home_settings(home),
                hooks_document(pre_entry={"type": "command"}),
            )
            report = self._survey(project, home)
            self.assertEqual(report["conflicts"], [])
            self.assertTrue(report["notes"], "an unreadable command must be stated")
            self.assertIn("no readable command", " ".join(report["notes"]))
            self.assertIn("INCOMPLETE", keel_survey.render(report))
            self.assertIn("INCOMPLETE", keel_survey.startup_line(report))

    def test_an_unparseable_settings_file_is_a_note_not_a_clean_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            home_settings(home).write_text("{ this is not JSON", encoding="utf-8")
            report = self._survey(project, home)
            self.assertEqual(report["conflicts"], [])
            self.assertTrue(report["notes"])
            self.assertIn("INCOMPLETE", keel_survey.render(report))

    def test_a_nonzero_count_from_a_partial_scan_is_stated_as_a_floor(self) -> None:
        """The qualifier belongs to the FIGURE, not to one value of it: three
        conflicts found by a scan that could not read a settings file is no
        more a total than zero is, and a reader who migrates exactly the
        entries the report names would stop one short."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            foreign_policy(project)
            home = quiet_home(root)
            home_settings(home).write_text("{ not JSON", encoding="utf-8")
            report = self._survey(project, home)
            self.assertEqual(len(report["conflicts"]), 1, report["conflicts"])
            self.assertTrue(report["notes"])
            startup = keel_survey.startup_line(report)
            self.assertIn("1 CONFLICT", startup)
            self.assertIn("INCOMPLETE", startup)
            self.assertIn("floor", startup)
            rendered = keel_survey.render(report)
            self.assertIn("INCOMPLETE", rendered)
            self.assertIn("the count above is a floor", rendered)

    def test_the_survey_scans_once_and_both_sections_read_the_same_scan(self) -> None:
        """R15: the conflicts and the registration list are one body of
        evidence, so the payload cannot show a registration the refusal never
        considered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            settings = write_json(
                home_settings(home),
                hooks_document(stop_command=FOREIGN_STOP_COMMAND),
            )
            report = self._survey(project, home)
            sources = {entry["source"] for entry in report["registrations"]}
            self.assertIn(redact(str(settings)), sources)
            for conflict in report["conflicts"]:
                with self.subTest(event=conflict["event"]):
                    self.assertIn(conflict["source"], sources)


class TestTheScopeTravelsWithTheConflict(unittest.TestCase):
    """T167 accept 1, second half: a migration step aimed at the wrong file is
    worse than none - removing an entry from the user-wide settings file
    retires the other stack in every project on the machine."""

    def _one_conflict(self, project: Path, home: Path) -> dict[str, str]:
        conflicts = keel_survey.conflicts_for(project, home)
        self.assertEqual(len(conflicts), 1, conflicts)
        return conflicts[0]

    def test_each_scope_is_named_in_the_detail_and_in_the_migration(self) -> None:
        for scope, target in (
            ("global", home_settings),
            ("project", None),
            ("plugin", plugin_manifest),
        ):
            with self.subTest(scope=scope), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project = root / "project"
                project.mkdir()
                home = quiet_home(root)
                where = project_settings(project) if target is None else target(home)
                write_json(where, hooks_document())
                conflict = self._one_conflict(project, home)
                self.assertEqual(conflict["scope"], scope)
                label = keel_survey.SCOPE_LABELS[scope]
                self.assertIn(label, conflict["detail"])
                self.assertIn(label, conflict["migration"])
                self.assertIn(redact(str(where)), conflict["detail"])
                self.assertIn(redact(str(where)), conflict["migration"])
                self.assertIn(
                    keel_survey.SCOPE_MIGRATIONS[scope], conflict["migration"]
                )

    def test_a_user_wide_entry_is_never_migrated_by_sending_the_reader_elsewhere(
        self,
    ) -> None:
        """The measured defect: the old migration text named
        ``.claude/settings.json`` unconditionally, and following it literally
        on a machine whose entries live in the home would have disarmed every
        project on it. The blast radius is now stated where the reader is
        standing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            settings = write_json(home_settings(home), hooks_document())
            migration = self._one_conflict(project, home)["migration"]
            self.assertIn(redact(str(settings)), migration)
            self.assertNotIn(redact(str(project_settings(project))), migration)
            self.assertIn("every project on this machine", migration)
            self.assertIn("EVERYWHERE", migration)
            self.assertIn("/keel:refit", migration)

    def test_the_filename_fast_path_names_its_own_scope_and_does_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            path = foreign_policy(project)
            conflict = self._one_conflict(project, quiet_home(root))
            self.assertEqual(conflict["scope"], "project")
            self.assertIn(".claude/POLICY.md", conflict["detail"])
            self.assertIn(redact(str(path)), conflict["detail"])
            self.assertIn("each conflict below NAMES", conflict["migration"])
            self.assertIn("/keel:refit", conflict["migration"])


class TestBothOrdersEndLoud(unittest.TestCase):
    """T167 accept 3. Two stacks can come to overlap in two orders, and only
    one of them was ever caught."""

    def test_adopt_then_lay_refuses_at_survey_time(self) -> None:
        """The order that already worked: the other stack is there first, and
        the survey ``/keel:lay`` step 1 reads refuses before anything is
        armed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            foreign_policy(project)
            write_json(project_settings(project), hooks_document())
            home = quiet_home(root)

            report = keel_survey.survey(project, home=home)
            self.assertIsNone(report["arming"]["tier"], "keel is not armed yet")
            self.assertTrue(report["conflicts"], "lay must have something to refuse")
            rendered = keel_survey.render(report)
            self.assertIn("CONFLICT [armed-overlap]", rendered)
            self.assertIn("MIGRATION", rendered)

    def test_lay_then_adopt_surfaces_the_conflict_at_the_next_session_start(self) -> None:
        """The order that was silent forever: keel is armed FIRST, the other
        stack's arming file appears afterwards, and nothing ever ran the scan
        again. The castoff line is where it now surfaces."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            arm(project, tier=2)

            before = keel_session._conflict_orientation(project, home=home)
            self.assertEqual(
                before, f"{keel_session.ORIENTATION_TAG}: conflicts - 0 found"
            )

            foreign_policy(project)

            after = keel_session._conflict_orientation(project, home=home)
            self.assertIn("1 CONFLICT(S) found", after)
            self.assertIn("python scripts/keel.py survey", after)

            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id="abcdef123456"
            )
            stream = io.StringIO()
            with no_real_fleet_registry():
                self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
            conflict_lines = [
                line
                for line in stream.getvalue().splitlines()
                if line.startswith(f"{keel_session.ORIENTATION_TAG}: conflicts")
            ]
            self.assertEqual(len(conflict_lines), 1, stream.getvalue())
            self.assertIn("CONFLICT(S) found", conflict_lines[0])

    def test_a_registration_added_after_arming_is_found_at_the_next_session_start(
        self,
    ) -> None:
        """The same order, without the filename: the other stack registers its
        write gate an hour after keel was armed and writes no arming file at
        all. This is the case the filename check could never see."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            arm(project, tier=2)
            self.assertIn("0 found", keel_session._conflict_orientation(project, home=home))

            write_json(
                home_settings(home),
                hooks_document(stop_command=FOREIGN_STOP_COMMAND),
            )

            line = keel_session._conflict_orientation(project, home=home)
            self.assertFalse(keel_survey.foreign_policy_path(project).exists())
            self.assertIn("2 CONFLICT(S) found", line)

    def test_a_partial_scan_qualifies_a_nonzero_castoff_count_too(self) -> None:
        """The castoff line's number is a floor whenever a source went unread,
        whatever the number is: an armed project told "1 CONFLICT(S) found"
        would otherwise read that as the total and migrate exactly one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            arm(project, tier=2)
            foreign_policy(project)
            home_settings(home).write_text("{ not JSON at all", encoding="utf-8")
            line = keel_session._conflict_orientation(project, home=home)
            self.assertIn("1 CONFLICT(S) found", line)
            self.assertIn("INCOMPLETE", line)
            self.assertIn("FLOOR", line)
            self.assertIn("1 source(s) unread", line)

    def test_a_partial_scan_at_session_start_never_reports_a_bare_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            arm(project, tier=2)
            home_settings(home).write_text("{ not JSON at all", encoding="utf-8")
            line = keel_session._conflict_orientation(project, home=home)
            self.assertNotEqual(
                line, f"{keel_session.ORIENTATION_TAG}: conflicts - 0 found"
            )
            self.assertIn("INCOMPLETE", line)
            self.assertIn("1 source(s) unread", line)


class TestTheOverrideNagIsDecoupledFromArming(unittest.TestCase):
    """T167 accept 4: a kill switch set while unarmed is exactly the state that
    matters, because arming can follow one minute later - and the survey a
    ``/keel:lay`` runs is BY DEFINITION run on an unarmed project."""

    def test_an_unarmed_project_with_the_switch_on_is_nagged_verbatim(self) -> None:
        self.assertEqual(
            keel_survey.override_report(False, {"KEEL_OVERRIDE": "on"}),
            keel_gate.OVERRIDE_REMINDER,
        )

    def test_the_armed_direction_is_unchanged(self) -> None:
        self.assertEqual(
            keel_survey.override_report(True, {"KEEL_OVERRIDE": "on"}),
            keel_gate.OVERRIDE_REMINDER,
        )

    def test_the_switch_off_is_silent_in_both_arming_states(self) -> None:
        for armed in (True, False):
            for env in ({"KEEL_OVERRIDE": "off"}, {}):
                with self.subTest(armed=armed, env=env):
                    self.assertEqual(keel_survey.override_report(armed, env), "")

    def test_the_sentence_is_the_gates_own_constant_and_is_never_re_spelled(self) -> None:
        self.assertIs(
            keel_survey.OVERRIDE_REMINDER,
            keel_gate.OVERRIDE_REMINDER,
            "the reminder is imported from the gate, not copied",
        )

    def test_an_unarmed_survey_prints_the_active_override(self) -> None:
        """End to end through the payload a lay reads, not just the helper:
        the switch is set in this process's environment, which is where
        ``survey`` looks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            home = quiet_home(root)
            had = "KEEL_OVERRIDE" in os.environ
            previous = os.environ.get("KEEL_OVERRIDE")
            os.environ["KEEL_OVERRIDE"] = "on"
            try:
                report = keel_survey.survey(project, home=home)
            finally:
                if had:
                    os.environ["KEEL_OVERRIDE"] = previous  # type: ignore[assignment]
                else:
                    os.environ.pop("KEEL_OVERRIDE", None)
            self.assertFalse(report["arming"]["armed"], "the premise: not armed")
            self.assertEqual(report["override"], keel_gate.OVERRIDE_REMINDER)
            self.assertIn("OVERRIDE ACTIVE", keel_survey.render(report))
            self.assertIn("KEEL_OVERRIDE=on", keel_survey.render(report))


class TestLayWarnsBeforeArmingBlind(unittest.TestCase):
    """T167 accept 5: the arming skill reports the switches and refuses to arm
    blind. Skill TEXT is the mechanism here, so the text is what is pinned."""

    def _skill(self) -> str:
        return (REPO_ROOT / "skills" / "lay" / "SKILL.md").read_text(encoding="utf-8")

    def _body(self) -> str:
        parts = self._skill().split("---", 2)
        return parts[2] if len(parts) > 2 else self._skill()

    def test_the_confirmation_step_reports_the_switches_line(self) -> None:
        """T226 renumbered lay's steps (backup and legacy-import survey were
        inserted before it), so Confirm is now step 7, not step 5."""
        body = self._body()
        step_seven = body.split("7. **Confirm.**", 1)
        self.assertEqual(len(step_seven), 2, "the confirm step must still be there to check")
        self.assertIn("switches:", step_seven[1].split("The deeper adoption flow")[0])

    def test_a_set_switch_requires_explicit_confirmation_before_arming(self) -> None:
        body = self._body()
        self.assertIn("kill switch", body)
        self.assertIn("explicitly confirms", body)
        self.assertIn("Never arm blind", body)

    def test_the_refusal_step_quotes_the_scope_the_report_names(self) -> None:
        """The migration step now names a file per scope, so the skill must
        send the user to THAT file rather than to a fixed one."""
        self.assertIn("it names the scope and file to edit", self._body())

    def test_the_skill_stays_within_its_word_budget(self) -> None:
        """The voice discipline this edit had to keep: an arming skill is read
        by a human under time pressure. T226 added two mandatory disciplines
        (backup-before-adoption, legacy import) that raised the floor of what
        must be said; the budget moved with them rather than being dropped.
        Printed, so the number is read."""
        words = len(self._body().split())
        print(f"\nskill lay: {words} words (limit 950)")
        self.assertLessEqual(words, 950)


if __name__ == "__main__":
    unittest.main()
