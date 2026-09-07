#!/usr/bin/env python3
"""Castoff orientation lines - the SessionStart facts ``/keel:castoff`` reads
from its own session's context instead of shelling out to
``python scripts/keel.py survey``, which the plan gate refuses before this
session's own ledger exists (T1, T5, keel-plan-074ab77d).

Contract
--------
Reads   : ``hooks/keel_session.py``'s orientation functions directly, plus
          this repository's own arming file (tier 2, no lock section, no
          conflicts of its own) as one real-world case. Every other case
          builds its own scratch project and is never run against
          ``REPO_ROOT`` in a way that could write into this repository's own
          audit log. Every case that asserts a CONFLICT COUNT also hands down
          its own fixture home (``fixture_home``): since T167 the conflict
          scan derives its answer from the PreToolUse and Stop registrations
          visible to it, and the user-wide settings file is one of the places
          it looks - so a count read from the suite-runner's own machine would
          be an ambient fact, not a test.
Emits   : unittest results only. One test prints the measured byte cost of
          the orientation block against the injection cap, so the number is
          read in the log rather than assumed to be small.
Writes  : nothing outside temporary directories it creates and removes.

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

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import is_published_cut  # noqa: E402
import keel_events  # noqa: E402  (path must be set first)
import keel_session  # noqa: E402
import keel_survey  # noqa: E402
from keel_registry_guard import no_real_fleet_registry  # noqa: E402


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    ``HOME``/``USERPROFILE`` are pointed at ``scratch`` rather than left as
    the real ones: several cases here launch a real ``session`` SessionStart
    against an armed fixture, which feeds keel's user-global fleet registry
    (T227) - a write that reads ``Path.home()`` regardless of the ``KEEL_*``
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


def run_hook(subcommand: str, payload: dict[str, Any], project: Path, scratch: Path,
             **env_extra: str) -> subprocess.CompletedProcess:
    """Run one hook subcommand as the harness runs it: subprocess, JSON stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch, **env_extra),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def fixture_home(root: Path) -> Path:
    """A home directory that registers no hook at all.

    The premise every conflict COUNT here owns: the scan reads the user's own
    ``~/.claude/settings.json`` and installed-plugin manifests, so a test that
    inherited the real home would be asserting a fact about the machine the
    suite happens to run on. ``.claude/`` is created and left empty on
    purpose - absent and unreadable are different states, and this one is
    "present, registering nothing".
    """
    home = root / "fixture-home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    return home


def arm(project: Path, *, tier: int = 2, lock_section: str = "") -> None:
    """Write a minimal arming file, optionally carrying a '## Policy lock' body."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    text = f"---\ntier: {tier}\n---\n"
    if lock_section:
        text += f"\n{lock_section}\n"
    (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")


class _PartialBoom:
    """``keel_survey``, except ``conflicts_for`` always raises.

    Everything else is delegated to the real module, so a test can break the
    conflict scan alone and observe that the other two orientation lines are
    unaffected (T1 accept: a fault in one may never blank the other two).
    """

    def conflicts_for(self, cwd: Path, home: Path | None = None) -> list[dict[str, str]]:
        raise RuntimeError("deliberate fault")

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


def _wholly_unreachable() -> Any:
    raise ModuleNotFoundError("no such module: keel_survey")


class _MalformedArming:
    """``keel_survey``, except ``arming_report`` returns a dict MISSING the
    keys ``_arming_orientation`` reads - no exception raised, a bad shape
    returned instead (T1 retry finding 1: the dict access sat outside the
    ``try``)."""

    def arming_report(self, cwd: Path) -> dict[str, Any]:
        return {"tier": 2}  # no "armed", no "note"

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _NonDictLock:
    """``keel_survey``, except ``lock_config_report`` returns something that
    is not a dict at all - a string, which supports no key access."""

    def lock_config_report(self, cwd: Path) -> Any:
        return "not-a-dict"

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _StringConflicts:
    """``keel_survey``, except ``conflicts_for`` returns a SIZED NON-LIST - a
    string, which ``len()`` happily accepts (T1 retry finding 3: ``len()``
    alone type-checks nothing)."""

    def conflicts_for(self, cwd: Path, home: Path | None = None) -> Any:
        return "CONFLICT"  # len() == 8; would render "8 CONFLICT(S) found"

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _AllThreeMalformed:
    """``keel_survey``, except all three calls return a bad shape rather than
    raising: a dict missing every key, a list where a dict is expected, and a
    plain int with no ``len()`` at all."""

    def arming_report(self, cwd: Path) -> dict[str, Any]:
        return {}

    def lock_config_report(self, cwd: Path) -> Any:
        return []

    def conflicts_for(self, cwd: Path, home: Path | None = None) -> Any:
        return 42

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _MissingKeySwitches:
    """``keel_survey``, except ``switches_report`` returns a dict MISSING one
    of ``KILL_SWITCHES`` - no exception, a bad shape instead (the same class
    of fault T1's retry found in ``arming_report``). A plain ``.get()``
    default would silently render this as "(unset)"; the strict presence
    check in ``_switches_orientation`` must turn it into a fault instead."""

    def switches_report(self, env: Any = None) -> dict[str, str]:
        return {"KEEL_GATE": "off", "KEEL_OVERRIDE": ""}  # KEEL_PLAN_TTL_MIN missing

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _NonDictSwitches:
    """``keel_survey``, except ``switches_report`` returns something that is
    not a dict at all - a list of pairs, which supports no key access."""

    def switches_report(self, env: Any = None) -> Any:
        return [("KEEL_GATE", "off")]

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _BoomSwitches:
    """``keel_survey``, except ``switches_report`` raises outright."""

    def switches_report(self, env: Any = None) -> dict[str, str]:
        raise RuntimeError("deliberate switches fault")

    def __getattr__(self, name: str) -> Any:
        return getattr(keel_survey, name)


class _AllFourMalformed(_AllThreeMalformed):
    """``_AllThreeMalformed``, plus a malformed ``switches_report`` too - all
    four orientation facts wrong-shaped at once."""

    def switches_report(self, env: Any = None) -> Any:
        return "not-a-dict"


class TestOrientationLinesPure(unittest.TestCase):
    """Direct unit coverage of the five functions ``run`` prints."""

    def test_unarmed_project_reports_unarmed_not_enforcing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()
            line = keel_session._arming_orientation(project)
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
            self.assertIn("unarmed", line)
            self.assertIn("not enforcing", line)

    def test_armed_tier_two_project_reports_armed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            line = keel_session._arming_orientation(project)
            self.assertIn("tier 2", line)
            self.assertIn("ARMED", line)

    def test_no_lock_section_reports_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            line = keel_session._lock_orientation(project, env={})
            self.assertIn("defaults", line)

    def test_lock_section_present_and_valid_reports_in_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(
                project,
                tier=2,
                lock_section="## Policy lock\n\nrelax:\n- release-version-bump\n",
            )
            line = keel_session._lock_orientation(project, env={})
            self.assertIn("in force", line)
            self.assertIn("release-version-bump", line)

    def test_lock_section_invalid_reports_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(
                project,
                tier=2,
                lock_section="## Policy lock\n\nrelax:\n- not-a-real-name\n",
            )
            line = keel_session._lock_orientation(project, env={})
            self.assertIn("INVALID", line)

    # --- BL12/T375: the line reports the EFFECTIVE lock, not the declared one.
    #
    # EVERY CASE HERE HANDS DOWN ITS OWN ``env``, and the three cases above were
    # changed to do the same. They used to read ``os.environ``, which made them
    # ambient: run the suite from a session holding ``KEEL_OVERRIDE=on`` - the
    # exact session that implements this item - and a test asserting "in force"
    # would flip on a fact belonging to the developer's shell rather than to the
    # fixture. That is the read-side leak BL1 closed for the audit log, in a
    # second place.

    def test_an_active_override_is_reported_on_the_lock_line(self) -> None:
        """The state segment names the suspension FIRST and the declaration after.

        Both facts, because both are true and they answer different questions:
        the suspension says what governs this session's next write, the
        declaration says what comes back when the switch is cleared - and the
        ``relax:`` value beside it, which describes the declaration, stays true
        throughout. Reporting either one alone is what made a session's two
        orientation lines read as a contradiction.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(
                project,
                tier=2,
                lock_section="## Policy lock\n\nrelax:\n- release-version-bump\n",
            )
            live = keel_session._lock_orientation(project, env={"KEEL_OVERRIDE": "on"})
            # The MARKER IS IMPORTED, never spelled: see
            # .keel/knowledge/a-marker-matched-by-literal-disarms-on-rename.md,
            # where a guard test spelling its own marker by hand was silently
            # disarmed by a rename. The full segment is pinned through the
            # renderer for the same reason.
            self.assertIn(keel_session.LOCK_SUSPENDED_STATE, live)
            self.assertIn(
                keel_session._effective_lock_state("in force", True), live
            )
            self.assertLess(
                live.index(keel_session.LOCK_SUSPENDED_STATE),
                live.index("in force"),
                f"the effective state must lead, the declaration follow: {live}",
            )
            self.assertIn("release-version-bump", live)

    def test_the_same_lock_reads_in_force_with_no_override(self) -> None:
        """The other direction, over the SAME project: one env value is the only
        difference between the two renderings, so neither can be produced by a
        line that ignores the switch."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(
                project,
                tier=2,
                lock_section="## Policy lock\n\nrelax:\n- release-version-bump\n",
            )
            quiet = keel_session._lock_orientation(project, env={})
            self.assertNotIn(keel_session.LOCK_SUSPENDED_STATE, quiet)
            self.assertIn(
                f"{keel_session.ORIENTATION_TAG}: policy lock - in force", quiet
            )

    def test_the_override_suspends_nothing_where_no_lock_exists(self) -> None:
        """A tier-1 project is adopted and has no policy lock, so the switch has
        nothing there to carry and the line may not claim a suspension. The same
        condition governs whether the reminder is printed at all."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=1)
            line = keel_session._lock_orientation(project, env={"KEEL_OVERRIDE": "on"})
            self.assertNotIn(keel_session.LOCK_SUSPENDED_STATE, line)
            self.assertFalse(
                keel_session.override_suspends_lock(project, env={"KEEL_OVERRIDE": "on"})
            )

    def test_the_reminder_and_the_lock_line_cannot_disagree(self) -> None:
        """THE PROPERTY BL12 EXISTS FOR, asserted as an equivalence rather than
        as two separate expectations.

        The banner said both "POLICY LOCK SUSPENDED" and "policy lock - in
        force" about one lock in one session, because two surfaces answered the
        same question from different inputs. They now share
        ``override_suspends_lock``, and this pins the consequence: across every
        environment tested, the reminder is printed if and only if the lock line
        reports the suspension. A future edit that gives either surface its own
        opinion fails here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(
                project,
                tier=2,
                lock_section="## Policy lock\n\nrelax:\n- release-version-bump\n",
            )
            for env in ({"KEEL_OVERRIDE": "on"}, {}, {"KEEL_OVERRIDE": "off"}):
                with self.subTest(env=env):
                    reminded = bool(keel_session.override_reminder(project, env=env))
                    reported = keel_session.LOCK_SUSPENDED_STATE in (
                        keel_session._lock_orientation(project, env=env)
                    )
                    self.assertEqual(reminded, reported, env)

    def test_no_conflict_reports_zero_found(self) -> None:
        """A true zero: nothing foreign in the project, nothing registered in
        the fixture home. Both premises are owned here, because since T167 the
        second one is part of the answer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            line = keel_session._conflict_orientation(project, home=fixture_home(root))
            self.assertEqual(line, f"{keel_session.ORIENTATION_TAG}: conflicts - 0 found")

    def test_a_conflict_is_counted_and_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".claude").mkdir()
            (project / ".claude" / "POLICY.md").write_text("# other\n", encoding="utf-8")
            line = keel_session._conflict_orientation(project, home=fixture_home(root))
            self.assertIn("1 CONFLICT", line)
            self.assertIn("python scripts/keel.py survey", line)

    def test_switches_reports_each_kill_switch_raw_value(self) -> None:
        env = {"KEEL_GATE": "off", "KEEL_OVERRIDE": "", "KEEL_PLAN_TTL_MIN": "120"}
        line = keel_session._switches_orientation(env)
        self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
        self.assertIn("KEEL_GATE=off", line)
        self.assertIn("KEEL_OVERRIDE=(unset)", line)
        self.assertIn("KEEL_PLAN_TTL_MIN=120", line)

    def test_switches_with_no_env_given_reports_unset_for_all_three(self) -> None:
        line = keel_session._switches_orientation({})
        self.assertIn("KEEL_GATE=(unset)", line)
        self.assertIn("KEEL_OVERRIDE=(unset)", line)
        self.assertIn("KEEL_PLAN_TTL_MIN=(unset)", line)

    def test_switches_values_match_keel_survey_switches_report_verbatim(self) -> None:
        """The accept clause verbatim: this line and ``keel survey``'s own
        ``switches:`` line must never disagree, because both read the exact
        same values through ``keel_survey.switches_report`` and format each
        pair with the identical ``name=value or '(unset)'`` expression."""
        env = {"KEEL_GATE": "off", "KEEL_OVERRIDE": "on", "KEEL_PLAN_TTL_MIN": ""}
        line = keel_session._switches_orientation(env)
        survey_switches = keel_survey.switches_report(env)
        self.assertEqual(set(survey_switches), set(keel_survey.KILL_SWITCHES))
        for name, value in survey_switches.items():
            self.assertIn(f"{name}={value or '(unset)'}", line)

    def test_keel_gate_off_is_visible_even_though_the_arming_line_still_reads_armed(
        self,
    ) -> None:
        """The case the ledger names as the one that matters:
        ``KEEL_GATE=off`` disarms plan-before-write and stop-with-accounting
        at ``hooks/keel_gate.py:1573`` WITHOUT changing the arming line, so a
        reader must be able to see both facts side by side rather than
        reading "tier 2 (ARMED)" alone and concluding the gates are live."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            arming_line = keel_session._arming_orientation(project)
            switches_line = keel_session._switches_orientation({"KEEL_GATE": "off"})
            self.assertIn("tier 2", arming_line)
            self.assertIn("ARMED", arming_line)
            self.assertIn("KEEL_GATE=off", switches_line)


class TestAFailedScanIsNeverAZero(unittest.TestCase):
    """The clause the ledger names verbatim: a conflict scan that raises is
    reported as a sentence, and that sentence is never the string a real
    zero produces (see ``a-swallowed-error-renders-as-a-fact``)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".keel").mkdir()
        self.original = keel_session._keel_survey

    def tearDown(self) -> None:
        keel_session._keel_survey = self.original
        self.tmp.cleanup()

    def test_a_raised_scan_never_renders_as_zero_conflicts(self) -> None:
        keel_session._keel_survey = lambda: _PartialBoom()
        line = keel_session._conflict_orientation(self.project)
        zero_line = f"{keel_session.ORIENTATION_TAG}: conflicts - 0 found"
        self.assertNotEqual(line, zero_line)
        self.assertIn("scan could not run", line)
        self.assertIn("RuntimeError", line)

    def test_a_raised_scan_does_not_blank_the_other_three_lines(self) -> None:
        keel_session._keel_survey = lambda: _PartialBoom()
        lines = keel_session.orientation_lines(self.project)
        self.assertEqual(len(lines), 5)
        self.assertIn("unarmed", lines[0])
        self.assertIn("defaults", lines[1])
        self.assertIn("scan could not run", lines[2])
        self.assertIn("switches", lines[3])

    def test_orientation_lines_never_raises_even_when_survey_is_wholly_unreachable(self) -> None:
        keel_session._keel_survey = _wholly_unreachable
        lines = keel_session.orientation_lines(self.project)
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
        self.assertIn("could not be read", lines[0])
        self.assertIn("could not be read", lines[1])
        self.assertIn("scan could not run", lines[2])
        self.assertIn("switches", lines[3])
        self.assertIn("could not be read", lines[3])

    def test_a_hook_run_never_fails_and_the_transcript_shows_no_false_zero(self) -> None:
        """R3/convention 7: the SessionStart hook returns 0 always, even when
        every orientation fact is unreadable, and its transcript never shows
        the failed scan as "0 found"."""
        keel_session._keel_survey = _wholly_unreachable
        event = keel_events.KeelEvent(
            kind="session_start", cwd=self.project, session_id="abcdef123456"
        )
        stream = io.StringIO()
        with no_real_fleet_registry():
            self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
        out = stream.getvalue()
        self.assertNotIn(f"{keel_session.ORIENTATION_TAG}: conflicts - 0 found", out)
        self.assertIn("scan could not run", out)


class TestMalformedSurveyResultsNeverEscapeOrRenderAsFacts(unittest.TestCase):
    """T1 retry findings 1 and 3: a MALFORMED return - not a raised exception,
    a bad SHAPE returned instead - must still (a) never raise past each
    helper's "NEVER raises" promise and (b) never render as a plausible-
    looking fact when the shape cannot support one."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".keel").mkdir()
        self.original = keel_session._keel_survey

    def tearDown(self) -> None:
        keel_session._keel_survey = self.original
        self.tmp.cleanup()

    def test_arming_report_missing_keys_renders_as_could_not_be_read(self) -> None:
        keel_session._keel_survey = lambda: _MalformedArming()
        line = keel_session._arming_orientation(self.project)  # must not raise
        self.assertIn("could not be read", line)
        self.assertIn("KeyError", line)

    def test_lock_config_report_non_dict_renders_as_could_not_be_read(self) -> None:
        keel_session._keel_survey = lambda: _NonDictLock()
        line = keel_session._lock_orientation(self.project)  # must not raise
        self.assertIn("could not be read", line)
        self.assertIn("TypeError", line)

    def test_conflicts_for_sized_non_list_never_renders_as_a_count(self) -> None:
        keel_session._keel_survey = lambda: _StringConflicts()
        line = keel_session._conflict_orientation(self.project)  # must not raise
        self.assertNotIn("CONFLICT(S) found", line)
        self.assertNotIn("8", line)
        self.assertIn("scan could not run", line)

    def test_conflicts_for_non_sized_return_also_fails_as_a_sentence(self) -> None:
        keel_session._keel_survey = lambda: _AllThreeMalformed()
        line = keel_session._conflict_orientation(self.project)  # must not raise
        self.assertIn("scan could not run", line)

    def test_switches_report_missing_a_key_renders_as_could_not_be_read_not_unset(
        self,
    ) -> None:
        """The property T5 exists for: a missing key must not silently
        default to "(unset)" the way a plain ``.get()`` would - that string
        means "keel read this and it is off", not "keel could not tell"."""
        keel_session._keel_survey = lambda: _MissingKeySwitches()
        line = keel_session._switches_orientation({})  # must not raise
        self.assertIn("could not be read", line)
        self.assertIn("KeyError", line)
        self.assertNotIn("KEEL_PLAN_TTL_MIN=(unset)", line)

    def test_switches_report_non_dict_renders_as_could_not_be_read(self) -> None:
        keel_session._keel_survey = lambda: _NonDictSwitches()
        line = keel_session._switches_orientation({})  # must not raise
        self.assertIn("could not be read", line)
        self.assertIn("TypeError", line)

    def test_switches_report_raising_renders_as_could_not_be_read(self) -> None:
        keel_session._keel_survey = lambda: _BoomSwitches()
        line = keel_session._switches_orientation({})  # must not raise
        self.assertIn("could not be read", line)
        self.assertIn("RuntimeError", line)

    def test_orientation_lines_survives_all_three_malformed_at_once(self) -> None:
        keel_session._keel_survey = lambda: _AllThreeMalformed()
        lines = keel_session.orientation_lines(self.project)
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))

    def test_orientation_lines_survives_all_four_malformed_at_once(self) -> None:
        keel_session._keel_survey = lambda: _AllFourMalformed()
        lines = keel_session.orientation_lines(self.project, {})
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
        self.assertIn("could not be read", lines[3])


class TestFindingTwoEachOrientationLineFailsIndependentlyOnStdout(unittest.TestCase):
    """T1 retry finding 2: even a helper's OWN internal guarantee being
    defeated - not merely a malformed survey return, which the helpers now
    already absorb - must cost only that one line, and every failure sentence
    must land on the SAME channel (stdout) the successful lines use, never
    diverted to ``run``'s stderr catch-all, and never at the cost of the
    knowledge-index print that follows in ``run``'s body."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".keel").mkdir()
        self.original_conflict = keel_session._conflict_orientation
        self.original_switches = keel_session._switches_orientation
        self.original_registry_write = keel_session.registry_write

    def tearDown(self) -> None:
        keel_session._conflict_orientation = self.original_conflict
        keel_session._switches_orientation = self.original_switches
        keel_session.registry_write = self.original_registry_write
        self.tmp.cleanup()

    def test_a_helpers_own_escape_still_leaves_the_other_three_lines_intact(self) -> None:
        def _boom(cwd: Path, home: Path | None = None) -> str:
            raise RuntimeError("a helper's own guard was defeated")

        keel_session._conflict_orientation = _boom
        lines = keel_session.orientation_lines(self.project, {})
        self.assertEqual(len(lines), 5)
        self.assertIn("unarmed", lines[0])
        self.assertIn("defaults", lines[1])
        self.assertIn("could not be computed", lines[2])
        self.assertIn("RuntimeError", lines[2])
        self.assertIn("switches", lines[3])

    def test_the_switches_helpers_own_escape_still_leaves_the_other_three_lines_intact(
        self,
    ) -> None:
        def _boom(env: Any = None) -> str:
            raise RuntimeError("the switches helper's own guard was defeated")

        keel_session._switches_orientation = _boom
        # The fixture home is what makes "0 found" a fact about this project
        # rather than about the machine running the suite (T167).
        lines = keel_session.orientation_lines(
            self.project, {}, home=fixture_home(Path(self.tmp.name))
        )
        self.assertEqual(len(lines), 5)
        self.assertIn("unarmed", lines[0])
        self.assertIn("defaults", lines[1])
        self.assertIn("0 found", lines[2])
        self.assertIn("could not be computed", lines[3])
        self.assertIn("RuntimeError", lines[3])

    def test_run_prints_every_orientation_line_on_stdout_and_never_diverts_to_stderr(self) -> None:
        def _boom(cwd: Path, home: Path | None = None) -> str:
            raise RuntimeError("a helper's own guard was defeated")

        keel_session._conflict_orientation = _boom
        # T227: ``run`` also feeds the fleet registry, which lives on THIS
        # machine's real user-global directory when no fixture home is
        # threaded through (``run`` takes none). That write is unrelated to
        # what this test is about - one helper's own guard being defeated -
        # and its own "pruned" stderr line (earned whenever an earlier test's
        # now-torn-down temp project is still on file) would otherwise be
        # mistaken for exactly the leak this test exists to catch. No-op it,
        # the same way this test already substitutes the helper under test.
        keel_session.registry_write = lambda cwd, home=None: None
        event = keel_events.KeelEvent(
            kind="session_start", cwd=self.project, session_id="abcdef123456"
        )
        stream = io.StringIO()
        stderr_capture = io.StringIO()
        with contextlib.redirect_stderr(stderr_capture):
            result = keel_session.run(event, stdout=stream, env={})
        self.assertEqual(result, 0)
        out = stream.getvalue()
        # the two lines that never faulted are still present -
        self.assertIn("unarmed", out)
        self.assertIn("defaults", out)
        # - and the fault renders its own sentence on the SAME stream -
        self.assertIn("could not be computed", out)
        # - rather than the whole orientation block being lost to the
        # catch-all in ``run`` that would otherwise write to stderr and abort
        # before the plan line / knowledge index print that follows.
        self.assertIn("YOUR session plan file", out)
        self.assertEqual(stderr_capture.getvalue(), "")


class TestOrientationLinesViaTheRealHook(unittest.TestCase):
    """The full subprocess path: SessionStart on stdin, the five tagged
    lines on stdout, measured against the injection cap rather than assumed
    to be small (T1 accept, T5 accept)."""

    def test_session_start_emits_all_five_orientation_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            arm(project, tier=2)
            result = run_hook(
                "session",
                {"hook_event_name": "SessionStart", "session_id": "abcdef123456",
                 "cwd": str(project)},
                project,
                scratch,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            tagged = [line for line in lines if line.startswith(keel_session.ORIENTATION_TAG)]
            self.assertEqual(len(tagged), 5, result.stdout)
            self.assertTrue(any("arming" in line for line in tagged), tagged)
            self.assertTrue(any("policy lock" in line for line in tagged), tagged)
            self.assertTrue(any("conflicts" in line for line in tagged), tagged)
            self.assertTrue(any("switches" in line for line in tagged), tagged)
            self.assertTrue(any("holds" in line for line in tagged), tagged)

    def test_keel_gate_off_appears_in_context_without_changing_the_arming_line(self) -> None:
        """The case the ledger names as the one that matters:
        ``KEEL_GATE=off`` disarms plan-before-write and stop-with-accounting
        at ``hooks/keel_gate.py:1573``, before the tier check, WITHOUT
        changing the arming line - so a session reading "tier 2 (ARMED)"
        alone would wrongly conclude its gates are live. Both lines must be
        readable from the same context so that conclusion is never the only
        one available."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            arm(project, tier=2)
            result = run_hook(
                "session",
                {"hook_event_name": "SessionStart", "session_id": "abcdef123456",
                 "cwd": str(project)},
                project,
                scratch,
                KEEL_GATE="off",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            tagged = [
                line for line in result.stdout.splitlines()
                if line.startswith(keel_session.ORIENTATION_TAG)
            ]
            self.assertEqual(len(tagged), 5, result.stdout)
            arming_line = next(line for line in tagged if "arming" in line)
            switches_line = next(line for line in tagged if "switches" in line)
            # the arming line alone still reads ARMED - KEEL_GATE never touches it -
            self.assertIn("tier 2", arming_line)
            self.assertIn("ARMED", arming_line)
            # - but the switches line names the disarmed gate explicitly, so a
            # reader of the FULL context cannot conclude the gates are live.
            self.assertIn("KEEL_GATE=off", switches_line)

    def test_the_orientation_block_costs_a_small_fraction_of_the_injection_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            lines = keel_session.orientation_lines(project, {})
            cost = keel_session.orientation_bytes(lines)
            cap = keel_session.inject_cap_bytes()
            print(f"\ncastoff orientation block: {cost} of {cap} bytes ({cost / cap:.2%} of the cap)")
            self.assertLess(cost, cap)

    def test_this_repository_reports_tier_two_armed_and_no_conflicts(self) -> None:
        """This repo is armed at tier 2 and registers no foreign gate stack of
        its own - the same real-world fact ``test_keel_wave3``'s
        ``startup_line`` test pins, read here through the hook's own
        orientation lines. A pure read: it writes nothing, so it is safe to
        point at ``REPO_ROOT`` directly.

        The fixture home is handed down for the conflict line alone. Since
        T167 that line also counts the USER's own registrations, and what a
        given machine registers globally is not this repository's property:
        with a home that registers nothing, "0 found" is the statement this
        test means - keel's own plugin manifest, the only PreToolUse/Stop
        registration in this tree, is recognised as keel's own rather than as
        a rival stack.

        The switches line is checked for FORMAT only (every switch name
        present), never for a specific value, because this repository's own
        ambient environment when the suite runs is not this test's to pin."""
        with tempfile.TemporaryDirectory() as tmp:
            lines = keel_session.orientation_lines(REPO_ROOT, home=fixture_home(Path(tmp)))
        self.assertEqual(len(lines), 5)
        if is_published_cut(REPO_ROOT):
            # INVERTS IN A PUBLISHED CUT, which ships no arming file: the
            # orientation must SAY so rather than claim a tier it does not have.
            self.assertIn("unarmed", lines[0])
            self.assertNotIn("tier 2", lines[0])
        else:
            self.assertIn("tier 2", lines[0])
            self.assertIn("ARMED", lines[0])
        self.assertIn("0 found", lines[2])
        for name in keel_survey.KILL_SWITCHES:
            self.assertIn(f"{name}=", lines[3])

    def test_the_repositorys_own_plugin_manifest_is_never_a_conflict(self) -> None:
        """The ownership half of the line above, stated on its own so a
        regression in ``command_is_own`` cannot hide behind a passing count:
        this repository's ``hooks/hooks.json`` DOES register a PreToolUse hook
        on write tools and a Stop hook, and both must read as keel's own."""
        registrations, _notes = keel_survey.scan_registrations(REPO_ROOT, Path(REPO_ROOT) / "no-such-home")
        stopping = [r for r in registrations if keel_survey.registration_can_stop_work(r)]
        self.assertTrue(stopping, "keel's own manifest must register a stopping event")
        for registration in stopping:
            with self.subTest(event=registration.event, source=registration.source):
                self.assertTrue(
                    keel_survey.command_is_own(registration.command),
                    registration.command,
                )


class TestOrientationSharesTheInjectionCapWithTheIndex(unittest.TestCase):
    """The knowledge index and the orientation block share ONE injector cap
    (R16, R32), so an always-on addition can never silently double-spend the
    budget the cap exists to bound."""

    def test_index_block_receives_the_cap_minus_orientation_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id="abcdef123456"
            )
            seen_caps: list[int] = []
            original_index_block = keel_session.index_block

            def spy(lines: Any, cap: int) -> str:
                seen_caps.append(cap)
                return original_index_block(lines, cap)

            keel_session.index_block = spy
            try:
                with no_real_fleet_registry():
                    self.assertEqual(keel_session.run(event, stdout=io.StringIO(), env={}), 0)
            finally:
                keel_session.index_block = original_index_block

            self.assertEqual(len(seen_caps), 1)
            orientation = keel_session.orientation_lines(project, {})
            # THREE injections are subtracted, not one: the five orientation
            # lines, the single live-view line (T131), and the hook-error
            # warning when there IS one (T235/T236 - it is conditional, so its
            # term is zero on a machine whose hooks have never failed, which is
            # every clean checkout and CI). All three are measured by the SAME
            # byte counter the hook uses, so this expectation cannot drift from
            # the arithmetic it checks - and each term is written out rather
            # than folded in, because the defect they guard against is exactly
            # an always-on line that silently widens what the cap bounds
            # (R16, R32).
            fault_line = keel_session.hook_fault_line()
            spent = (
                keel_session.orientation_bytes(orientation)
                + keel_session.orientation_bytes([keel_session.live_view_line()])
                + keel_session.orientation_bytes([fault_line] if fault_line else [])
            )
            expected = keel_session.DEFAULT_INJECT_CAP_BYTES - spent
            self.assertEqual(seen_caps[0], expected)
            self.assertLess(
                expected,
                keel_session.DEFAULT_INJECT_CAP_BYTES
                - keel_session.orientation_bytes(orientation),
                "the live-view line must cost the index bytes, not ride free",
            )


class TestFindingFiveOrientationAtTheSmallCapBoundary(unittest.TestCase):
    """T1 retry finding 5: ``orientation_bytes``'s docstring now states the
    guarantee it actually enforces - the INDEX floors at zero, orientation
    itself is not clamped - exercised at the boundary the finding named: a
    cap set below what orientation alone costs."""

    def test_a_cap_below_orientations_own_cost_still_emits_all_five_lines_in_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            arm(project, tier=2)
            cost = keel_session.orientation_bytes(keel_session.orientation_lines(project, {}))
            small_cap = 10
            self.assertLess(
                small_cap, cost, "meaningless unless the cap is below orientation's own cost"
            )
            result = run_hook(
                "session",
                {"hook_event_name": "SessionStart", "session_id": "abcdef123456",
                 "cwd": str(project)},
                project,
                scratch,
                KEEL_INJECT_CAP_BYTES=str(small_cap),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            tagged = [
                line for line in result.stdout.splitlines()
                if line.startswith(keel_session.ORIENTATION_TAG)
            ]
            self.assertEqual(len(tagged), 5, result.stdout)
            self.assertTrue(any("arming" in line for line in tagged), tagged)
            self.assertTrue(any("policy lock" in line for line in tagged), tagged)
            self.assertTrue(any("conflicts" in line for line in tagged), tagged)
            self.assertTrue(any("switches" in line for line in tagged), tagged)
            self.assertTrue(any("holds" in line for line in tagged), tagged)

    def test_index_cap_floors_at_zero_rather_than_going_negative(self) -> None:
        """Spies on the real ``index_block`` call inside ``run()`` (same
        technique as ``TestOrientationSharesTheInjectionCapWithTheIndex``)
        so the value asserted is the cap the floor at
        ``hooks/keel_session.py`` actually hands to its caller, not a
        recomputation of ``max`` in the test. Deleting or inverting that
        floor sends ``index_block`` a negative cap here (~-135) instead of 0,
        which fails this assertion."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id="abcdef123456"
            )
            cost = keel_session.orientation_bytes(keel_session.orientation_lines(project, {}))
            small_cap = 10
            self.assertLess(
                small_cap, cost, "meaningless unless the cap is below orientation's own cost"
            )

            seen_caps: list[int] = []
            original_index_block = keel_session.index_block

            def spy(lines: Any, cap: int) -> str:
                seen_caps.append(cap)
                return original_index_block(lines, cap)

            # ``run()``'s own cap lookup reads ``os.environ`` directly (it
            # calls ``inject_cap_bytes()`` with no argument), so the small
            # cap has to land there, not in the ``env`` mapping ``run()``
            # only threads through to ``override_reminder``.
            had_env_cap = keel_session.INJECT_CAP_ENV in os.environ
            previous_env_cap = os.environ.get(keel_session.INJECT_CAP_ENV)
            os.environ[keel_session.INJECT_CAP_ENV] = str(small_cap)
            keel_session.index_block = spy
            try:
                with no_real_fleet_registry():
                    self.assertEqual(
                        keel_session.run(event, stdout=io.StringIO(), env={}),
                        0,
                    )
            finally:
                keel_session.index_block = original_index_block
                if had_env_cap:
                    os.environ[keel_session.INJECT_CAP_ENV] = previous_env_cap  # type: ignore[assignment]
                else:
                    os.environ.pop(keel_session.INJECT_CAP_ENV, None)

            self.assertEqual(len(seen_caps), 1)
            self.assertGreaterEqual(
                seen_caps[0], 0, "index_block must never be handed a negative cap"
            )
            self.assertEqual(seen_caps[0], 0)


class TestOrientationBytes(unittest.TestCase):
    """``orientation_bytes`` is arithmetic, not a guess."""

    def test_matches_the_lines_plus_one_newline_each(self) -> None:
        lines = ["ab", "cdef"]
        expected = len("ab".encode("utf-8")) + 1 + len("cdef".encode("utf-8")) + 1
        self.assertEqual(keel_session.orientation_bytes(lines), expected)

    def test_empty_list_costs_nothing(self) -> None:
        self.assertEqual(keel_session.orientation_bytes([]), 0)


if __name__ == "__main__":
    unittest.main()
