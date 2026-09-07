#!/usr/bin/env python3
"""T176 - the ``workshop:`` declaration stops being enforced in silence.

Contract
--------
Reads   : ``hooks/keel_gate.py``, ``hooks/keel_session.py`` and
          ``scripts/keel_survey.py`` as modules, plus this repository's own
          arming file in the ONE case whose subject is what keel actually
          ships. Every other case builds its own fixture arming file, so no
          verdict here depends on the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers, and why each half exists
------------------------------------------
``workshop:`` shipped ENFORCED AND UNREPORTED. Since T169 each declared prefix
turns a policy-lock deny into an ALLOW plus a ``workshop_write`` audit line,
and no reader named the field at all: ``lock_config_report`` did not carry it,
so neither the castoff orientation line nor survey's ``lock`` line could print
it. In this repository the declaration is ``hooks/``, ``scripts/``, ``tests/`` -
the loosest clause in the lock, the one that lets a model edit keel's own
source - and a session could not see what it was permitted to rewrite. A
REFUSED entry was worse off still: announced once, on stderr, at gate-event
time, and nowhere a reader looks before starting work.

That is T168's absent-vs-none rule one field along, so the shape of the fix is
T175's shape for ``## Holds``, deliberately and not coincidentally (R15's
one-parser rule, applied one level above the parse):

1. TWO FACTS, TWO FIELDS (accept 1). ``lock_config_report`` carries the entries
   IN FORCE (``workshop``, taken from ``workshop_prefixes`` so it can never
   name one the gate would refuse) and the entries REFUSED
   (``workshop_refusals``) separately, plus ``workshop_state`` - the ONE
   decision every surface renders from. REFUSED is not NONE.
2. SURFACED TWICE (accept 2). Survey's ``lock`` line and the castoff
   orientation line, both from that state, with an empty declaration printed as
   an explicit ``(none)`` exactly as ``tighten``/``relax`` already are.
3. AN INVALID SECTION NAMES THE LOSS (accept 3). It carries no workshop -
   ``LockSection.workshop_prefixes`` guarantees that at the enforcement end -
   and both lines say so instead of printing entries nothing would honour,
   because over-stating a LOOSENING misleads a reader in the unsafe direction.
4. BOTH DIRECTIONS SHIP (accept 4). Declared-and-surfaced and nothing-declared
   are pinned here per state, and end to end through the real hook by
   ``tests/fixtures/session/09-*`` and ``10-*``.

SURFACING ONLY, asserted rather than promised: ``TestTheScopeBoundary`` pins
that the reported set is exactly the set ``workshop_prefix_for`` honours, for
targets in and out of the workshop and on the hard-denied governance surface.
A change that widened a permission while making it visible would fail there.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_gate  # noqa: E402
import keel_session  # noqa: E402
import keel_survey  # noqa: E402

#: A workshop entry that STANDS: source, no governance file at or beneath it.
A_REAL_WORKSHOP = "hooks/"

#: A workshop entry keel REFUSES, because the arming file that carries the list
#: lives beneath it - the rule that stops a model widening its own workshop.
A_REFUSED_WORKSHOP = ".keel/"

#: A workshop entry used only where the test asserts it is NOT printed. Spelled
#: to appear nowhere else in a survey report, so "absent from the line" is a
#: statement about this change rather than a coincidence of the fixture tree.
AN_UNHONOURED_WORKSHOP = "distinctive-shed-t176/"

#: An arming section shape per state, so every case names which fact it pins.
BODIES: dict[str, str] = {
    "active": f"## Policy lock\n\nworkshop:\n- {A_REAL_WORKSHOP}\n",
    "refused": f"## Policy lock\n\nworkshop:\n- {A_REFUSED_WORKSHOP}\n",
    "none": "## Policy lock\n\nrelax:\n- release-version-bump\n",
    # INVALID for a reason that has nothing to do with the workshop: an
    # unknown relaxation name. The workshop entry is well formed and still
    # carried by nothing, which is the whole of accept 3.
    "invalid": (
        f"## Policy lock\n\nrelax:\n- not-a-real-name\n\nworkshop:\n"
        f"- {AN_UNHONOURED_WORKSHOP}\n"
    ),
    "absent": "# an arming file with no configuration section at all\n",
}


#: One arming body per HOLDS state, so the closure walk below can cross T175's
#: states against their two renderers exactly as it crosses the workshop's.
HOLDS_BODIES: dict[str, str] = {
    "active": "## Holds\n\n- no push until I review the migration\n",
    "none": "## Holds\n\n- *(none active)*\n",
    "absent": "# an arming file with no holds section at all\n",
    # UNREADABLE with NO injected fault: a heading keel cannot classify.
    # Holds have a portable producer for that state; the workshop's UNKNOWN
    # does not, which is why the seam helper above exists and says so.
    "malformed": "## Holds\n\nprose only, no bullet and no marker\n",
}


def armed(project: Path, body: str = "", tier: int = 2) -> Path:
    """An armed fixture project whose arming file carries ``body`` verbatim."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    text = f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n\n{body}"
    (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")
    return project


def lock_line(project: Path) -> str:
    """The ONE ``lock`` line of a rendered survey for this project.

    Asserted to be exactly one line, because "the survey names the workshop" is
    not satisfied by a report that prints the field twice or not at all.
    """
    out = keel_survey.render(keel_survey.survey(project))
    lines = [line for line in out.splitlines() if line.startswith("lock ")]
    if len(lines) != 1:
        raise AssertionError(f"expected exactly one lock line, got {lines!r}")
    return lines[0]


def refused_lines(project: Path) -> list[str]:
    """The ``REFUSED`` continuation lines of a rendered survey."""
    out = keel_survey.render(keel_survey.survey(project))
    return [line for line in out.splitlines() if line.strip().startswith("REFUSED ")]


class _Boom:
    """``keel_survey``, except ``lock_config_report`` raises outright."""

    def lock_config_report(self, _cwd: Path) -> dict[str, object]:
        raise RuntimeError("deliberate fault")

    def __getattr__(self, name: str) -> object:
        return getattr(keel_survey, name)


class _NoKeys:
    """``keel_survey``, except ``lock_config_report`` returns a bad SHAPE - the
    fault class that raises nothing and would otherwise render as a fact."""

    def lock_config_report(self, _cwd: Path) -> dict[str, object]:
        return {}

    def __getattr__(self, name: str) -> object:
        return getattr(keel_survey, name)


class _StatePresentButUnknown:
    """A report whose section is PRESENT while the state is UNKNOWN.

    The parser cannot produce this pair - an unreadable arming file reports
    ``present`` false - so this is a DOUBLE, and saying so is the point: it is
    kept as a unit-level probe of the renderers' last branch under a shape the
    real world does not supply.

    IT IS NO LONGER THE ONLY THING THAT REACHES THAT BRANCH, and that was a
    review finding, not a preference. While the segment was nested inside
    ``if present`` this double was the sole reacher, which is precisely how a
    branch that production can never enter passes for covered.
    ``TestTheRealErrorPath`` now reaches the same branch through
    ``unreadable_arming_file`` - a genuine ``OSError`` at the real read - and
    this class stays only as the second, narrower probe.
    """

    def lock_config_report(self, _cwd: Path) -> dict[str, object]:
        return {
            "present": True,
            "valid": True,
            "tightened": (),
            "relaxed": (),
            "errors": (),
            "holds_state": keel_gate.HOLDS_ABSENT,
            "holds": (),
            "hold_errors": (),
            "workshop_state": keel_gate.WORKSHOP_UNKNOWN,
            "workshop": (),
            "workshop_refusals": (),
            "note": "",
        }

    def __getattr__(self, name: str) -> object:
        return getattr(keel_survey, name)


@contextmanager
def unreadable_arming_file(project: Path):
    """``<project>/.keel/keel-policy.md`` UNREADABLE at the real read, briefly.

    WHY THE FAULT IS INJECTED, disclosed rather than buried - the same
    disclosure ``tests/test_keel_derived_facts_t168.py`` makes for the same
    reason (see its ``TestUnreadableIsNeverReadAsAbsent`` docstring): a genuine
    permission-denied fixture is not constructible on all three operating
    systems this suite runs on. A POSIX ``chmod`` to 0 is a no-op for root, and
    CI often runs as root, so the case would pass for the wrong reason; Windows
    ACLs need a tool outside the standard library, and this project ships no
    third-party code (R7). The ``is_file`` guard in ``keel_gate.policy_body``
    also rules out the phantom-path trick that gives T168 its one
    injection-free case.

    WHAT IS THEREFORE PROVEN, exactly: the ``PermissionError`` is raised BY THE
    REAL READ CALL, inside ``policy_body``, and every line after it is
    production code - ``policy_body``'s ``except OSError`` translating it to
    ``GateError``, ``lock_config_report``'s ``except GateError`` building the
    report, and both renderers rendering it. Nothing about the report, the
    state or the sentence is fabricated, which is what separates this from the
    ``_StatePresentButUnknown`` double. WHAT IS NOT PROVEN is the operating
    system's own behaviour on the way in.

    Every other path is delegated to the real reader, so a survey that reads
    dozens of files during this window sees the truth about all of them.
    """
    target = (project / ".keel" / "keel-policy.md").resolve()
    real_read_text = Path.read_text

    def refusing_read_text(self: Path, *args: object, **kwargs: object) -> str:
        try:
            same = self.resolve() == target
        except OSError:  # pragma: no cover - resolve() failing is not the fault
            same = False
        if same:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    Path.read_text = refusing_read_text  # type: ignore[method-assign]
    try:
        yield project
    finally:
        Path.read_text = real_read_text  # type: ignore[method-assign]


class TestTwoFactsTwoFields(unittest.TestCase):
    """Accept 1: in force and refused are carried apart, and neither is
    inferred from the other."""

    def test_the_report_carries_the_entries_in_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            report = keel_survey.lock_config_report(project)
            self.assertEqual(report["workshop"], (A_REAL_WORKSHOP,))
            self.assertEqual(report["workshop_refusals"], ())
            self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_ACTIVE)
            # R15: the report forms no second opinion of its own. The state and
            # the entries both come from the parser the GATE consults.
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(report["workshop_state"], keel_gate.workshop_state(section))
            self.assertEqual(report["workshop"], section.workshop_prefixes)

    def test_a_refused_entry_is_carried_as_refused_never_as_absent(self) -> None:
        """The T168 rule, one field along: an entry the owner wrote and keel
        threw away is not an entry nobody wrote."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["refused"])
            report = keel_survey.lock_config_report(project)
            self.assertEqual(report["workshop"], (), "a refused entry is never in force")
            self.assertEqual(len(report["workshop_refusals"]), 1)
            self.assertIn(A_REFUSED_WORKSHOP, report["workshop_refusals"][0])
            self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_REFUSED)
            # ...and the state is NOT the one an undeclared workshop produces.
            other = armed(Path(tmp) / "q", BODIES["none"])
            self.assertEqual(
                keel_survey.lock_config_report(other)["workshop_state"],
                keel_gate.WORKSHOP_NONE,
            )

    def test_nothing_declared_is_its_own_state_with_both_fields_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = keel_survey.lock_config_report(armed(Path(tmp) / "p", BODIES["none"]))
            self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_NONE)
            self.assertEqual(report["workshop"], ())
            self.assertEqual(report["workshop_refusals"], ())

    def test_an_invalid_section_carries_no_workshop_but_keeps_the_reason(self) -> None:
        """Accept 3 at the report level: the entries are gone because the gate
        would not honour them, and ``errors`` still says why."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["invalid"])
            report = keel_survey.lock_config_report(project)
            self.assertFalse(report["valid"])
            self.assertEqual(report["workshop"], ())
            self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_INVALID)
            self.assertTrue(report["errors"])

    def test_an_invalid_section_that_declared_nothing_reports_no_loss(self) -> None:
        """``workshop_state`` answers "nothing declared" BEFORE validity: an
        invalid section that never asked for a workshop has lost nothing, and a
        reader must not be sent hunting for a declaration nobody wrote."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Policy lock\n\nrelax:\n- not-a-real-name\n")
            report = keel_survey.lock_config_report(project)
            self.assertFalse(report["valid"])
            self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_NONE)

    def test_an_unreadable_arming_file_reports_unknown_not_none(self) -> None:
        """The file cannot be read, so what was declared is UNKNOWN. Nothing is
        in force either way - the gate could not parse it either - but "none
        declared" is a claim about the owner's intent keel has not earned."""

        def boom(_project: Path) -> keel_gate.LockSection:
            raise keel_gate.GateError("deliberate fault")

        original = keel_survey.policy_lock_section
        keel_survey.policy_lock_section = boom
        try:
            report = keel_survey.lock_config_report(Path("."))
        finally:
            keel_survey.policy_lock_section = original
        self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_UNKNOWN)
        self.assertEqual(report["workshop"], ())
        self.assertEqual(report["workshop_refusals"], ())
        self.assertTrue(report["note"])

    def test_the_five_states_are_distinct_names(self) -> None:
        """A closed set every reader branches over. Two states sharing a value
        would collapse two different facts into one sentence."""
        states = (
            keel_gate.WORKSHOP_NONE,
            keel_gate.WORKSHOP_ACTIVE,
            keel_gate.WORKSHOP_REFUSED,
            keel_gate.WORKSHOP_INVALID,
            keel_gate.WORKSHOP_UNKNOWN,
        )
        self.assertEqual(len(set(states)), 5, states)

    def test_the_shipped_arming_file_is_reported_with_a_workshop_field(self) -> None:
        """The defect's own scenario: THIS repository declares a workshop and no
        reader named it. The CONTENT of that declaration is the owner's to
        change, so what is pinned is that the field is carried and agrees with
        the gate - not which prefixes it happens to hold today."""
        report = keel_survey.lock_config_report(REPO_ROOT)
        section = keel_gate.policy_lock_section(REPO_ROOT)
        self.assertIn(report["workshop_state"], (
            keel_gate.WORKSHOP_NONE,
            keel_gate.WORKSHOP_ACTIVE,
            keel_gate.WORKSHOP_REFUSED,
            keel_gate.WORKSHOP_INVALID,
        ))
        self.assertEqual(report["workshop"], section.workshop_prefixes)
        self.assertEqual(report["workshop_refusals"], section.workshop_refusals)


class TestTheSurveyLine(unittest.TestCase):
    """Accept 2 and 3, survey's half: one ``lock`` line, one sentence per
    state, never a missing word."""

    def test_the_entries_in_force_are_named_on_the_lock_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line = lock_line(armed(Path(tmp) / "p", BODIES["active"]))
            self.assertIn(f"workshop: {A_REAL_WORKSHOP}", line)
            self.assertIn("in force", line)

    def test_an_empty_declaration_renders_as_an_explicit_none(self) -> None:
        """Exactly as ``tighten`` and ``relax`` already do on the same line."""
        with tempfile.TemporaryDirectory() as tmp:
            line = lock_line(armed(Path(tmp) / "p", BODIES["none"]))
            self.assertIn("workshop: (none)", line)

    def test_a_refused_entry_never_renders_as_that_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["refused"])
            line = lock_line(project)
            self.assertNotIn("workshop: (none)", line)
            self.assertIn("REFUSED", line)
            self.assertIn("none in force", line)
            # The reason is printed too, not merely counted - and no longer only
            # on stderr at the moment a gate event happens to fire.
            refusals = refused_lines(project)
            self.assertEqual(len(refusals), 1, refusals)
            self.assertIn(A_REFUSED_WORKSHOP, refusals[0])
            self.assertIn("keeps for the user's own hand", refusals[0])

    def test_an_invalid_section_says_so_and_prints_no_entry(self) -> None:
        """Accept 3: the line names the loss. Printing the declared entry would
        tell a reader it may rewrite source the gate is about to refuse."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["invalid"])
            line = lock_line(project)
            self.assertIn("INVALID", line)
            self.assertIn("no workshop is honoured", line)
            self.assertNotIn(AN_UNHONOURED_WORKSHOP, line)
            # And nowhere else in the report either: an entry nothing honours
            # must not read as a permission from any line of this surface.
            rendered = keel_survey.render(keel_survey.survey(project))
            self.assertNotIn(AN_UNHONOURED_WORKSHOP, rendered)

    def test_an_absent_section_still_names_the_workshop_as_an_explicit_none(self) -> None:
        """The ``workshop:`` list lives INSIDE ``## Policy lock``, so an absent
        section means an absent declaration - and the line SAYS SO rather than
        leaving the word out, which is the same convention-7 rule the holds line
        follows and the reason the segment is computed before the presence
        branch at all.

        THIS ASSERTION DISCRIMINATES. Before T176 this branch printed no
        ``workshop`` word in any state, so the first form of this test - "the
        absent line must NOT mention a workshop" - passed identically on old and
        new code and pinned nothing (reviewer finding 2). It now fails on
        pre-change code, and it fails again if anyone moves the segment back
        inside the ``else`` where UNKNOWN could not be reached.
        """
        with tempfile.TemporaryDirectory() as tmp:
            line = lock_line(armed(Path(tmp) / "p", BODIES["absent"]))
            self.assertIn("no '## Policy lock' section", line)
            self.assertIn("workshop: (none)", line)

    def test_an_unknown_state_is_never_rendered_as_a_permission(self) -> None:
        """The renderer's last branch, reached with a report the parser cannot
        produce, so the fallback is exercised rather than assumed."""
        report = keel_survey.survey(REPO_ROOT)
        report["lock_config"] = _StatePresentButUnknown().lock_config_report(REPO_ROOT)
        lines = [
            line
            for line in keel_survey.render(report).splitlines()
            if line.startswith("lock ")
        ]
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("UNKNOWN", lines[0])
        self.assertIn("none is in force", lines[0])
        self.assertNotIn("workshop: (none)", lines[0])


class TestTheCastoffLine(unittest.TestCase):
    """Accept 2 and 3, the castoff half: the line a session reads before it has
    run any command at all."""

    def test_the_entries_in_force_are_named_in_the_orientation_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            line = keel_session._lock_orientation(project)
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
            self.assertIn(f"workshop: {A_REAL_WORKSHOP}", line)

    def test_an_empty_declaration_renders_as_an_explicit_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line = keel_session._lock_orientation(armed(Path(tmp) / "p", BODIES["none"]))
            self.assertIn("workshop: (none)", line)

    def test_an_absent_section_still_names_the_workshop_as_an_explicit_none(self) -> None:
        """The castoff half of the same rule, discriminating for the same
        reason: pre-change this line named no workshop in this state."""
        with tempfile.TemporaryDirectory() as tmp:
            line = keel_session._lock_orientation(armed(Path(tmp) / "p", BODIES["absent"]))
            self.assertIn("no '## Policy lock' section", line)
            self.assertIn("workshop: (none)", line)

    def test_a_refused_entry_never_renders_as_that_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line = keel_session._lock_orientation(armed(Path(tmp) / "p", BODIES["refused"]))
            self.assertNotIn("workshop: (none)", line)
            self.assertIn("1 REFUSED", line)
            self.assertIn("python scripts/keel.py survey", line)

    def test_an_invalid_section_says_so_and_prints_no_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            line = keel_session._lock_orientation(armed(Path(tmp) / "p", BODIES["invalid"]))
            self.assertIn("INVALID", line)
            self.assertIn("none in force", line)
            self.assertNotIn(AN_UNHONOURED_WORKSHOP, line)

    def test_an_unknown_state_is_never_rendered_as_a_permission(self) -> None:
        original = keel_session._keel_survey
        keel_session._keel_survey = lambda: _StatePresentButUnknown()
        try:
            line = keel_session._lock_orientation(Path("."))
        finally:
            keel_session._keel_survey = original
        self.assertIn("UNKNOWN", line)
        self.assertNotIn("workshop: (none)", line)

    def test_the_state_names_match_the_gates_own_constants(self) -> None:
        """``_lock_orientation`` spells the states as LITERALS so this hook
        keeps its lazy, fail-open reach into the survey. That trade is only safe
        if a rename fails HERE rather than silently falling through to the
        UNKNOWN branch and reporting a workshop as unreadable."""
        self.assertEqual(keel_gate.WORKSHOP_ACTIVE, "active")
        self.assertEqual(keel_gate.WORKSHOP_NONE, "none")
        self.assertEqual(keel_gate.WORKSHOP_REFUSED, "refused")
        self.assertEqual(keel_gate.WORKSHOP_INVALID, "invalid")
        self.assertEqual(keel_gate.WORKSHOP_UNKNOWN, "unknown")

    def test_the_workshop_rides_the_existing_line_not_a_sixth_one(self) -> None:
        """The block stays five lines: every reader and several tests index
        those positions, and the workshop is the third list of the section this
        line already reports."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            lines = keel_session.orientation_lines(project, {})
            self.assertEqual(len(lines), 5, lines)
            lock_lines = [line for line in lines if ": policy lock -" in line]
            self.assertEqual(len(lock_lines), 1, lines)
            self.assertIn(A_REAL_WORKSHOP, lock_lines[0])

    def test_the_line_never_raises_and_never_falls_silent(self) -> None:
        """The promise every orientation helper makes, re-asserted because this
        change added key accesses inside it."""
        original = keel_session._keel_survey
        keel_session._keel_survey = lambda: _Boom()
        try:
            line = keel_session._lock_orientation(Path("."))  # must not raise
        finally:
            keel_session._keel_survey = original
        self.assertIn("could not be read", line)
        self.assertIn("RuntimeError", line)
        self.assertNotIn("workshop", line)

    def test_a_malformed_report_shape_does_not_render_a_fact(self) -> None:
        original = keel_session._keel_survey
        keel_session._keel_survey = lambda: _NoKeys()
        try:
            line = keel_session._lock_orientation(Path("."))  # must not raise
        finally:
            keel_session._keel_survey = original
        self.assertIn("could not be read", line)
        self.assertIn("KeyError", line)


class TestTheRealErrorPath(unittest.TestCase):
    """FINDING 1: ``WORKSHOP_UNKNOWN`` reached through an actually unreadable
    arming file, on both surfaces, with no fabricated report anywhere.

    The first cut of T176 nested the whole workshop segment inside
    ``if present``, while the only producer of UNKNOWN -
    ``lock_config_report``'s ``except GateError`` branch - pairs it with
    ``present`` FALSE. So an unreadable arming file printed the identical line a
    project that declared nothing gets: the word "workshop" absent, the cause
    surviving only in a generic trailing NOTE. That is the NONE/UNKNOWN collapse
    T168 closed elsewhere, rebuilt one field along.
    """

    def test_the_report_reports_unknown_from_a_real_read_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            with unreadable_arming_file(project):
                report = keel_survey.lock_config_report(project)
        self.assertEqual(report["workshop_state"], keel_gate.WORKSHOP_UNKNOWN)
        self.assertFalse(report["present"], "the pairing that hid the state")
        self.assertEqual(report["workshop"], ())
        # The declaration WAS there - ``workshop: hooks/`` - and keel must not
        # claim it was absent on the strength of a read it never completed.
        self.assertNotEqual(report["workshop_state"], keel_gate.WORKSHOP_NONE)

    def test_the_survey_line_names_the_unknown_workshop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            with unreadable_arming_file(project):
                line = lock_line(project)
            none_line = lock_line(armed(Path(tmp) / "q", BODIES["absent"]))
        self.assertIn("workshop:", line, "the word itself went missing before")
        self.assertIn("UNKNOWN", line)
        self.assertIn("cannot be read", line)
        # THE COLLAPSE, asserted directly: the sentence an unreadable file
        # produces is not the sentence an undeclared workshop produces.
        self.assertNotEqual(line, none_line)
        self.assertNotIn("workshop: (none)", line)
        # ...and it no longer claims there is no section, which keel never read.
        self.assertNotIn("defaults", line)

    def test_the_castoff_line_names_the_unknown_workshop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            with unreadable_arming_file(project):
                line = keel_session._lock_orientation(project)
            none_line = keel_session._lock_orientation(
                armed(Path(tmp) / "q", BODIES["absent"])
            )
        self.assertIn("workshop:", line)
        self.assertIn("UNKNOWN", line)
        self.assertNotEqual(line, none_line)
        self.assertNotIn("workshop: (none)", line)
        self.assertNotIn("defaults", line)

    def test_the_same_failure_still_reports_holds_as_unreadable(self) -> None:
        """T175's surface, re-checked through the same real fault rather than
        assumed: the reviewer asked for the holds states to be crossed against
        their renderers too, and this is the producer they share with the
        workshop's UNKNOWN. A regression here would be a T175 regression."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            with unreadable_arming_file(project):
                report = keel_survey.lock_config_report(project)
                rendered = keel_survey.render(keel_survey.survey(project))
                castoff = keel_session._holds_orientation(project)
        self.assertEqual(report["holds_state"], keel_gate.HOLDS_UNREADABLE)
        holds_lines = [
            line for line in rendered.splitlines() if line.startswith("holds ")
        ]
        self.assertEqual(len(holds_lines), 1, rendered)
        self.assertIn("UNKNOWN", holds_lines[0])
        self.assertIn("not 'none'", holds_lines[0])
        self.assertIn("UNKNOWN", castoff)
        self.assertNotIn("none active (explicitly declared)", castoff)

    def test_nothing_leaks_an_absolute_home_path_into_the_castoff_line(self) -> None:
        """The failure sentence travels through ``redact`` like every other line
        this hook emits (convention 5), and a home-anchored path is the one this
        fault carries."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["active"])
            with unreadable_arming_file(project):
                line = keel_session._lock_orientation(project)
        self.assertNotIn(str(Path.home()), line)


class TestEveryStateHasAReaderOnBothSurfaces(unittest.TestCase):
    """FINDING 1's CLASS, closed and machine-checked: a state the report can
    PRODUCE that no renderer can REACH is exactly as invisible as a field no
    renderer carries - the defect this task exists to fix, one layer up.

    The guard is the enumeration itself. Every member of
    ``keel_gate.WORKSHOP_STATES`` and ``keel_gate.HOLDS_STATES`` must have a
    REAL input that produces it and a DISTINCT sentence on each surface, so a
    sixth state added without a reader, or a renderer that stops reaching one,
    fails here rather than rendering as whichever branch happens to catch it.
    """

    #: state -> (arming body, make the file unreadable, survey needle, castoff
    #: needle). Real inputs only; no report is fabricated in this class.
    WORKSHOP_CASES: dict[str, tuple[str, bool, str, str]] = {
        keel_gate.WORKSHOP_ACTIVE: (BODIES["active"], False, "hooks/", "hooks/"),
        keel_gate.WORKSHOP_REFUSED: (BODIES["refused"], False, "REFUSED", "REFUSED"),
        keel_gate.WORKSHOP_NONE: (BODIES["none"], False, "(none)", "(none)"),
        keel_gate.WORKSHOP_INVALID: (BODIES["invalid"], False, "INVALID", "INVALID"),
        keel_gate.WORKSHOP_UNKNOWN: (BODIES["active"], True, "UNKNOWN", "UNKNOWN"),
    }

    #: state -> (arming body, make the file unreadable, needle). The malformed
    #: section gives UNREADABLE a producer needing no injection at all.
    HOLDS_CASES: dict[str, tuple[str, bool, str]] = {
        keel_gate.HOLDS_ACTIVE: (HOLDS_BODIES["active"], False, "ACTIVE"),
        keel_gate.HOLDS_NONE: (HOLDS_BODIES["none"], False, "none active"),
        keel_gate.HOLDS_ABSENT: (HOLDS_BODIES["absent"], False, "no '## Holds' section"),
        keel_gate.HOLDS_UNREADABLE: (HOLDS_BODIES["malformed"], False, "UNKNOWN"),
    }

    def _rendered(self, body: str, unreadable: bool) -> tuple[str, str, str, str, str]:
        """One real fixture, read four ways: the two workshop sentences, the two
        holds sentences, and the pair of states the report derived."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", body)
            if unreadable:
                with unreadable_arming_file(project):
                    return self._read(project)
            return self._read(project)

    def _read(self, project: Path) -> tuple[str, str, str, str, str]:
        report = keel_survey.lock_config_report(project)
        rendered = keel_survey.render(keel_survey.survey(project))
        survey_lock = next(
            line for line in rendered.splitlines() if line.startswith("lock ")
        )
        survey_holds = next(
            line for line in rendered.splitlines() if line.startswith("holds ")
        )
        return (
            survey_lock,
            keel_session._lock_orientation(project),
            survey_holds,
            keel_session._holds_orientation(project),
            f"{report['workshop_state']}|{report['holds_state']}",
        )

    def test_every_workshop_state_is_produced_and_rendered_on_both_surfaces(self) -> None:
        seen_survey: dict[str, str] = {}
        seen_castoff: dict[str, str] = {}
        for state, (body, blocked, s_needle, c_needle) in self.WORKSHOP_CASES.items():
            with self.subTest(state=state):
                survey_lock, castoff, _h, _hc, states = self._rendered(body, blocked)
                self.assertEqual(
                    states.split("|")[0], state,
                    "the fixture does not produce the state it claims",
                )
                self.assertIn("workshop:", survey_lock)
                self.assertIn("workshop:", castoff)
                self.assertIn(s_needle, survey_lock)
                self.assertIn(c_needle, castoff)
                seen_survey[state] = survey_lock
                seen_castoff[state] = castoff
        # (a) every declared state has a fixture: a sixth one cannot be added to
        #     the gate and left unread.
        self.assertEqual(
            sorted(seen_survey), sorted(keel_gate.WORKSHOP_STATES),
            "a declared state has no real input and no reader",
        )
        # (b) no two states render the same sentence on either surface - the
        #     collapse itself, asserted rather than reasoned about.
        for surface, seen in (("survey", seen_survey), ("castoff", seen_castoff)):
            with self.subTest(surface=surface):
                self.assertEqual(
                    len(set(seen.values())), len(keel_gate.WORKSHOP_STATES),
                    f"two workshop states render identically on the {surface} "
                    f"surface: {seen}",
                )

    def test_every_holds_state_is_produced_and_rendered_on_both_surfaces(self) -> None:
        """The same walk over T175's states, because the reviewer's class is a
        property of the pattern and not of this field. No divergence found: the
        holds line always rendered outside the presence branch, which is why
        UNREADABLE was reachable there and was not here."""
        seen_survey: dict[str, str] = {}
        seen_castoff: dict[str, str] = {}
        for state, (body, blocked, needle) in self.HOLDS_CASES.items():
            with self.subTest(state=state):
                _l, _c, survey_holds, castoff, states = self._rendered(body, blocked)
                self.assertEqual(states.split("|")[1], state)
                self.assertIn(needle, survey_holds)
                self.assertIn(needle, castoff)
                seen_survey[state] = survey_holds
                seen_castoff[state] = castoff
        self.assertEqual(sorted(seen_survey), sorted(keel_gate.HOLDS_STATES))
        for surface, seen in (("survey", seen_survey), ("castoff", seen_castoff)):
            with self.subTest(surface=surface):
                self.assertEqual(
                    len(set(seen.values())), len(keel_gate.HOLDS_STATES),
                    f"two holds states render identically on the {surface} "
                    f"surface: {seen}",
                )

    def test_the_holds_unreadable_state_is_also_reached_through_the_real_fault(self) -> None:
        """Two producers, one state: the malformed section above needs no
        injection, and the unreadable file reaches the same sentence. Both are
        pinned so neither producer can be lost without notice."""
        _l, _c, survey_holds, castoff, states = self._rendered(BODIES["active"], True)
        self.assertEqual(states.split("|")[1], keel_gate.HOLDS_UNREADABLE)
        self.assertIn("UNKNOWN", survey_holds)
        self.assertIn("UNKNOWN", castoff)

    def test_the_state_tuples_hold_exactly_the_declared_constants(self) -> None:
        """The enumeration is only a guard if it is complete: a constant added
        beside the tuple rather than inside it would defeat every test above."""
        self.assertEqual(
            set(keel_gate.WORKSHOP_STATES),
            {
                keel_gate.WORKSHOP_NONE,
                keel_gate.WORKSHOP_ACTIVE,
                keel_gate.WORKSHOP_REFUSED,
                keel_gate.WORKSHOP_INVALID,
                keel_gate.WORKSHOP_UNKNOWN,
            },
        )
        self.assertEqual(len(keel_gate.WORKSHOP_STATES), 5)
        self.assertEqual(
            set(keel_gate.HOLDS_STATES),
            {
                keel_gate.HOLDS_ABSENT,
                keel_gate.HOLDS_NONE,
                keel_gate.HOLDS_ACTIVE,
                keel_gate.HOLDS_UNREADABLE,
            },
        )
        self.assertEqual(len(keel_gate.HOLDS_STATES), 4)

    def test_the_workshop_segment_is_reached_without_regard_to_presence(self) -> None:
        """The structural property in one sentence: for EVERY state, both
        surfaces print the word. The nesting defect is exactly the case where
        one state printed no ``workshop`` word at all, so this assertion fails
        on the pre-fix code."""
        for state, (body, blocked, _s, _c) in self.WORKSHOP_CASES.items():
            with self.subTest(state=state):
                survey_lock, castoff, _h, _hc, _states = self._rendered(body, blocked)
                self.assertIn("workshop:", survey_lock)
                self.assertIn("workshop:", castoff)
        # and the absent-section fixture, whose ``present`` is FALSE like the
        # unreadable one - the pairing that made the branch unreachable.
        survey_lock, castoff, _h, _hc, _states = self._rendered(BODIES["absent"], False)
        self.assertIn("workshop: (none)", survey_lock)
        self.assertIn("workshop: (none)", castoff)


class TestTheScopeBoundary(unittest.TestCase):
    """Surfacing only, asserted rather than promised: nothing here changed what
    the workshop PERMITS."""

    def test_the_reported_set_is_exactly_the_enforced_set(self) -> None:
        """The property that makes the new field safe to read: for every target,
        the surface agrees with ``workshop_prefix_for`` - the function the gate
        itself calls - so a session cannot read a permission it does not have.
        Both directions per state, including the hard-denied governance file."""
        targets = (
            "hooks/keel_gate.py",
            "hooks/nested/deeper.py",
            "scripts/keel_checks.py",
            "docs/keel-rules.md",
            ".keel/keel-policy.md",
            ".claude/settings.json",
        )
        for state, body in BODIES.items():
            with self.subTest(state=state):
                with tempfile.TemporaryDirectory() as tmp:
                    project = armed(Path(tmp) / "p", body)
                    section = keel_gate.policy_lock_section(project)
                    reported = keel_survey.lock_config_report(project)["workshop"]
                    for relative in targets:
                        target = keel_gate.norm(project, relative)
                        prefix = keel_gate.workshop_prefix_for(project, target, section)
                        if prefix:
                            self.assertIn(
                                prefix, reported,
                                "the gate honours a prefix the surface never named",
                            )
                        else:
                            covered = [
                                entry for entry in reported
                                if keel_gate._under(target, keel_gate.norm(project, entry))
                            ]
                            self.assertEqual(
                                covered, [],
                                f"{relative} is reported as workshop-covered while the "
                                f"gate refuses it",
                            )

    def test_the_governance_surface_is_still_refused_after_being_surfaced(self) -> None:
        """The hard-denied set is untouched: the arming file, the settings files
        and the workshop list itself. Declaring them, and now seeing them
        reported, grants nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", BODIES["refused"])
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(section.workshop_prefixes, ())
            for relative in (".keel/keel-policy.md", ".claude/settings.json"):
                with self.subTest(relative=relative):
                    target = keel_gate.norm(project, relative)
                    self.assertTrue(keel_gate.workshop_forbidden(project, target))
                    self.assertEqual(
                        keel_gate.workshop_prefix_for(project, target, section), ""
                    )

    def test_workshop_state_decides_nothing_and_mutates_nothing(self) -> None:
        """A reporter, not a rule: the section it is handed is unchanged by the
        asking, and the answer depends on no environment of its own."""
        with tempfile.TemporaryDirectory() as tmp:
            section = keel_gate.policy_lock_section(armed(Path(tmp) / "p", BODIES["active"]))
            before = (section.workshop, section.workshop_refusals, section.errors)
            first = keel_gate.workshop_state(section)
            second = keel_gate.workshop_state(section)
            self.assertEqual(first, second)
            self.assertEqual(
                (section.workshop, section.workshop_refusals, section.errors), before
            )

    def test_the_gate_declares_the_rule_it_now_reports(self) -> None:
        """The design rule is written where the code is, not only in a ledger."""
        doc = keel_gate.__doc__ or ""
        self.assertIn("THE DECLARATION IS SURFACED", doc)
        self.assertIn("THE WORKSHOP RULE", doc)


if __name__ == "__main__":  # pragma: no cover - parity with the other suites
    unittest.main()
