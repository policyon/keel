#!/usr/bin/env python3
"""T175 - ``## Holds`` stops being documentation that pretends to be mechanism.

Contract
--------
Reads   : ``hooks/keel_gate.py``, ``hooks/keel_session.py`` and
          ``scripts/keel_survey.py`` as modules, plus the two SHIPPED policy
          documents (``.keel/keel-policy.md``, ``templates/keel-policy.md``) in
          the three cases whose subject is what keel actually ships. Every
          other case builds its own fixture arming file, so no verdict here
          depends on the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers, and why each half exists
------------------------------------------
``## Holds`` shipped as a heading with NO READER: prose in a policy-locked file
that nothing parsed, surfaced or counted. A hold the user believes is binding
and that no session is ever told about is wrong-while-green - the failure is
invisible until something the user forbade has already happened.

1. ONE PARSER (accept 1). The holds section is read by ``_scan_lock_section``,
   the same scan that owns the lock lists, in the same pass over the same
   stripped body. Asserted by behaviour rather than by inspection: the two
   documentation conventions that defeated this parser TWICE - the fenced
   example and the four-space INDENTED example - must declare no hold either,
   and they do, because holds inherit that machinery instead of re-deriving it.
2. SURFACED TWICE (accept 2). The castoff orientation line and survey's own
   ``holds`` line, both rendered from ``holds_state`` as the gate derived it.
   Zero holds is an explicit sentence in both, never a missing line.
3. LOUD WHEN MALFORMED (accept 3). Three failure shapes, each reported and
   none of them read as empty; plus the property that ties this to T168 -
   ABSENT, NONE and UNKNOWN are three different sentences.
4. THE SHIPPED TEMPLATE (accept 4) states both halves: what a hold does now and
   what it still does not do.

The scope boundary is asserted, not assumed: ``test_a_hold_never_becomes_a
_gate_decision`` pins that a project holding everything it can spell still gets
the same ALLOW the same write gets with no holds at all. Holds are readable and
visible; they are not enforceable-as-gates, and a later change that quietly
made them gate would fail here.

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

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from keel_published_cut import is_published_cut, shipped_policy_documents  # noqa: E402
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_session  # noqa: E402
import keel_survey  # noqa: E402

#: A hold that reads like something a user would actually write - prose about
#: intent, not a path pattern. The whole point of the narrow scope.
A_REAL_HOLD = "no push until I review the migration"


def armed(project: Path, body: str = "", tier: int = 2) -> Path:
    """An armed fixture project whose arming file carries ``body`` verbatim."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    text = f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n\n{body}"
    (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")
    return project


def section_for(body: str) -> keel_gate.LockSection:
    """The parsed section for an arming file carrying ``body``."""
    with tempfile.TemporaryDirectory() as tmp:
        return keel_gate.policy_lock_section(armed(Path(tmp) / "p", body))


def shipped(relative: str) -> keel_gate.LockSection:
    """The parse of a document this repository actually ships, read as an
    adopter's own arming file would be read."""
    text = (REPO_ROOT / relative).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "p"
        (project / ".keel").mkdir(parents=True)
        (project / ".keel" / "keel-policy.md").write_text(text, encoding="utf-8")
        return keel_gate.policy_lock_section(project)


class TestOneParser(unittest.TestCase):
    """Accept 1: the same scan owns both sections, so neither can drift."""

    def test_the_holds_section_is_read_by_the_lock_sections_own_scan(self) -> None:
        """Both readings come out of one call, over one stripped body."""
        body = "## Policy lock\n\nrelax:\n- release-version-bump\n\n## Holds\n\n- " + A_REAL_HOLD + "\n"
        present, lists, ignored, holds = keel_gate._scan_lock_section(body)
        self.assertTrue(present)
        self.assertEqual(lists["relax"], ["release-version-bump"])
        self.assertEqual(ignored, [])
        self.assertEqual(holds.entries, (A_REAL_HOLD,))
        self.assertTrue(holds.present)
        # ...and the public view agrees with the scan it is a view of.
        self.assertEqual(keel_gate.parse_holds(body), holds)

    def test_a_fenced_example_declares_no_hold(self) -> None:
        """The defect that failed review on 2026-08-18: a fenced example read
        as a live declaration. Holds inherit the stripper rather than repeating
        the mistake one field along."""
        section = section_for(
            "## Holds\n\nFor example:\n\n```\n- " + A_REAL_HOLD + "\n```\n\n- *(none active)*\n"
        )
        self.assertEqual(section.holds, ())
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_NONE)

    def test_an_indented_example_declares_no_hold_and_is_reported(self) -> None:
        """The second failure of the same pair: a four-space INDENTED example.
        It declares nothing, and - because a silently absorbed intention is the
        whole defect - the line is quoted back rather than dropped."""
        section = section_for("## Holds\n\nFor example:\n\n    - " + A_REAL_HOLD + "\n")
        self.assertEqual(section.holds, ())
        self.assertEqual(section.holds_ignored_indented, ("- " + A_REAL_HOLD,))
        self.assertNotEqual(keel_gate.holds_state(section), keel_gate.HOLDS_NONE)

    def test_the_indented_note_names_the_holds_section_not_the_lock_section(self) -> None:
        """One announcer, two sections, each named correctly: a note that
        blamed the wrong heading would be a false fact printed by the very
        mechanism that exists to print true ones."""
        section = section_for("## Holds\n\nExample:\n\n    - " + A_REAL_HOLD + "\n")
        stream = io.StringIO()
        with redirect_stderr(stream):
            keel_gate.announce_ignored_indented_lines(section)
        said = stream.getvalue()
        self.assertIn("'## Holds'", said)
        self.assertNotIn("'## Policy lock'", said)
        self.assertIn("column 0", said)

    def test_a_holds_section_survives_a_file_with_no_policy_lock_section(self) -> None:
        """The early return in ``policy_lock_section`` used to be the one path
        a whole Holds section could vanish down: a project may hold something
        without configuring the lock at all."""
        section = section_for("## Holds\n\n- " + A_REAL_HOLD + "\n")
        self.assertFalse(section.present, "no lock section here, by construction")
        self.assertEqual(section.holds, (A_REAL_HOLD,))
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_ACTIVE)

    def test_holds_never_reach_the_lock_sections_validity(self) -> None:
        """A typo in a PROSE section must not drop a ``lock:`` entry. Folding
        hold errors into ``errors`` would make a mistyped hold LOOSEN the very
        paths the owner tightened - a widening caused by a sentence."""
        section = section_for(
            "## Policy lock\n\nlock:\n- src/generated/\n\n## Holds\n\nprose only, no bullet\n"
        )
        self.assertTrue(section.valid, section.errors)
        self.assertEqual(section.locked_paths, ("src/generated/",))
        self.assertFalse(section.holds_valid)
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_UNREADABLE)


class TestTheFourStates(unittest.TestCase):
    """Accept 2 and 3: absent, none, active and unreadable are four different
    facts, and ``holds_state`` is the only thing that decides between them."""

    def test_absent_is_not_none(self) -> None:
        """T168's rule, one field along: a section nobody wrote and a section
        that says "nothing" are different claims about the world."""
        absent = section_for("# just a policy file\n")
        none = section_for("## Holds\n\n- *(none active)*\n")
        self.assertEqual(keel_gate.holds_state(absent), keel_gate.HOLDS_ABSENT)
        self.assertEqual(keel_gate.holds_state(none), keel_gate.HOLDS_NONE)
        self.assertNotEqual(
            keel_gate.holds_state(absent),
            keel_gate.holds_state(none),
            "absent and none must never collapse into one state",
        )

    def test_an_active_hold_is_carried_as_written(self) -> None:
        section = section_for("## Holds\n\n- " + A_REAL_HOLD + "\n- leave vendor/ alone\n")
        self.assertEqual(section.holds, (A_REAL_HOLD, "leave vendor/ alone"))
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_ACTIVE)

    def test_the_none_marker_is_recognised_through_its_punctuation(self) -> None:
        """The spelling this repository's own arming file uses, and the plainer
        ones an adopter is likely to reach for."""
        for spelling in ("*(none active)*", "(none)", "none", "`none active`", "no holds"):
            with self.subTest(spelling=spelling):
                section = section_for(f"## Holds\n\n- {spelling}\n")
                self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_NONE)
                self.assertEqual(section.holds, ())

    def test_a_sentence_that_merely_contains_none_is_still_a_hold(self) -> None:
        """The marker set is closed on purpose. Reducing a sentence until it
        looks like a marker is how a live constraint goes quiet."""
        section = section_for("## Holds\n\n- none of the migrations may be pushed\n")
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_ACTIVE)
        self.assertEqual(section.holds, ("none of the migrations may be pushed",))

    def test_prose_without_a_bullet_is_unreadable_not_empty(self) -> None:
        """A hold written as a paragraph is invisible to every instrument keel
        has, so keel says it cannot read the section instead of reporting none.
        This is the shape the shipped template used to have."""
        section = section_for("## Holds\n\nNo push until I review the migration.\n")
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_UNREADABLE)
        self.assertTrue(section.hold_errors)
        self.assertIn("column 0", " ".join(section.hold_errors))

    def test_a_marker_beside_a_hold_is_a_contradiction_and_is_said_so(self) -> None:
        section = section_for("## Holds\n\n- *(none active)*\n- " + A_REAL_HOLD + "\n")
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_UNREADABLE)
        self.assertIn("BOTH", " ".join(section.hold_errors))

    def test_an_unclosed_fence_makes_holds_unknown_rather_than_absent(self) -> None:
        """A fence the file never closes swallows every line after it, so
        "there is no Holds section" is exactly what keel is NOT entitled to
        conclude - the same reasoning the lock section already applies to
        itself, pointed at the other direction of the same ambiguity."""
        section = section_for("## Holds\n\n```\n- " + A_REAL_HOLD + "\n")
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_UNREADABLE)
        self.assertIn("never closed", " ".join(section.hold_errors))

    def test_an_unclosed_fence_before_the_heading_is_still_unknown(self) -> None:
        """The harder half: the fence eats the heading itself, so the raw scan
        sees no section at all. Reporting ABSENT here would erase a standing
        constraint with the very failure that should have raised the alarm."""
        section = section_for("Example:\n\n```\nunterminated\n\n## Holds\n\n- " + A_REAL_HOLD + "\n")
        self.assertFalse(section.holds_present, "the fence hid the heading, by construction")
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_UNREADABLE)

    def test_a_pathological_hold_is_bounded_and_marked(self) -> None:
        """These lines are injected into every session under a byte cap (R16).
        Truncation is allowed; SILENT truncation is not."""
        section = section_for("## Holds\n\n- " + "x" * 400 + "\n")
        self.assertEqual(len(section.holds), 1)
        self.assertTrue(section.holds[0].endswith(keel_gate.HOLD_TRUNCATED_MARKER))
        self.assertLess(len(section.holds[0]), 400)


class TestTheSurveyReport(unittest.TestCase):
    """Accept 2, survey's half: one reader, four sentences, never a blank."""

    def test_the_report_carries_the_state_the_gate_derived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Holds\n\n- " + A_REAL_HOLD + "\n")
            report = keel_survey.lock_config_report(project)
            self.assertEqual(report["holds_state"], keel_gate.HOLDS_ACTIVE)
            self.assertEqual(report["holds"], (A_REAL_HOLD,))
            self.assertEqual(report["hold_errors"], ())
            # R15: the report must not form a second opinion of its own.
            self.assertEqual(
                report["holds_state"],
                keel_gate.holds_state(keel_gate.policy_lock_section(project)),
            )

    def test_an_unreadable_arming_file_reports_unknown_holds_not_none(self) -> None:
        """The most expensive shape of the T168 fault: the file cannot be read,
        so the number of standing holds is UNKNOWN. Reporting "absent" would
        erase them at exactly the moment nobody can check."""

        def boom(_project: Path) -> keel_gate.LockSection:
            raise keel_gate.GateError("deliberate fault")

        original = keel_survey.policy_lock_section
        keel_survey.policy_lock_section = boom
        try:
            report = keel_survey.lock_config_report(Path("."))
        finally:
            keel_survey.policy_lock_section = original
        self.assertEqual(report["holds_state"], keel_gate.HOLDS_UNREADABLE)
        self.assertTrue(report["hold_errors"])

    def test_the_rendered_report_always_carries_a_holds_line(self) -> None:
        """Four states, four sentences, and an absent section is a printed
        sentence rather than a missing line (convention 7)."""
        cases = (
            ("## Holds\n\n- " + A_REAL_HOLD + "\n", "1 ACTIVE", A_REAL_HOLD),
            ("## Holds\n\n- *(none active)*\n", "none active", "explicitly declared"),
            ("# nothing here\n", "no '## Holds' section", "nothing declared"),
            ("## Holds\n\nprose only\n", "UNKNOWN", "not 'none'"),
        )
        for body, needle, second in cases:
            with self.subTest(body=body):
                with tempfile.TemporaryDirectory() as tmp:
                    project = armed(Path(tmp) / "p", body)
                    out = keel_survey.render(keel_survey.survey(project))
                    holds_lines = [
                        line for line in out.splitlines() if line.startswith("holds")
                    ]
                    self.assertEqual(len(holds_lines), 1, out)
                    self.assertIn(needle, holds_lines[0])
                    self.assertIn(second, out)


class TestTheCastoffLine(unittest.TestCase):
    """Accept 2, the castoff half: the line a session cannot miss."""

    def test_an_active_hold_is_named_on_its_own_orientation_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Holds\n\n- " + A_REAL_HOLD + "\n")
            line = keel_session._holds_orientation(project)
            self.assertTrue(line.startswith(keel_session.ORIENTATION_TAG))
            self.assertIn("1 ACTIVE", line)
            self.assertIn(A_REAL_HOLD, line)

    def test_zero_holds_reads_as_an_explicit_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Holds\n\n- *(none active)*\n")
            line = keel_session._holds_orientation(project)
            self.assertIn("none active", line)
            self.assertIn("explicitly declared", line)

    def test_an_absent_section_says_so_rather_than_saying_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "# no holds section\n")
            line = keel_session._holds_orientation(project)
            self.assertIn("no '## Holds' section", line)
            self.assertNotIn("none active", line)

    def test_a_malformed_section_never_renders_as_none(self) -> None:
        """Accept 3 at the surface: the sentence a session reads must not be
        the one a genuinely empty section produces."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Holds\n\nprose only, no bullet\n")
            line = keel_session._holds_orientation(project)
            self.assertIn("UNKNOWN", line)
            self.assertIn("NOT 'none'", line)
            # The none SENTENCE, not the substring: the advisory in the error
            # text legitimately quotes the marker an owner should write.
            none_line = keel_session._holds_orientation(
                armed(Path(tmp) / "none", "## Holds\n\n- *(none active)*\n")
            )
            self.assertIn("none active (explicitly declared)", none_line)
            self.assertNotIn("none active (explicitly declared)", line)

    def test_many_holds_are_bounded_but_counted_exactly(self) -> None:
        body = "## Holds\n\n" + "".join(f"- hold number {n}\n" for n in range(1, 8))
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", body)
            line = keel_session._holds_orientation(project)
            self.assertIn("7 ACTIVE", line, "the count is never bounded")
            self.assertIn("+4 more", line, "the listing is")
            self.assertIn("python scripts/keel.py survey", line)

    def test_the_state_names_match_the_gates_own_constants(self) -> None:
        """``_holds_orientation`` spells the four states as literals so this
        hook keeps its lazy, fail-open reach into the survey. That trade is
        only safe if a rename fails HERE instead of silently falling through to
        the UNKNOWN branch."""
        self.assertEqual(keel_gate.HOLDS_ACTIVE, "active")
        self.assertEqual(keel_gate.HOLDS_NONE, "none")
        self.assertEqual(keel_gate.HOLDS_ABSENT, "absent")
        self.assertEqual(keel_gate.HOLDS_UNREADABLE, "unreadable")

    def test_the_holds_line_never_raises_and_never_falls_silent(self) -> None:
        """The promise every orientation helper makes."""

        class _Boom:
            def lock_config_report(self, _cwd: Path) -> dict[str, object]:
                raise RuntimeError("deliberate fault")

            def __getattr__(self, name: str) -> object:
                return getattr(keel_survey, name)

        original = keel_session._keel_survey
        keel_session._keel_survey = lambda: _Boom()
        try:
            line = keel_session._holds_orientation(Path("."))  # must not raise
        finally:
            keel_session._keel_survey = original
        self.assertIn("could not be read", line)
        self.assertIn("RuntimeError", line)
        self.assertNotIn("none active", line)

    def test_a_malformed_report_shape_does_not_render_a_fact(self) -> None:
        """A bad SHAPE rather than a raised exception - the class T1's retry
        found in every other orientation helper."""

        class _NoKeys:
            def lock_config_report(self, _cwd: Path) -> dict[str, object]:
                return {}

            def __getattr__(self, name: str) -> object:
                return getattr(keel_survey, name)

        original = keel_session._keel_survey
        keel_session._keel_survey = lambda: _NoKeys()
        try:
            line = keel_session._holds_orientation(Path("."))  # must not raise
        finally:
            keel_session._keel_survey = original
        self.assertIn("could not be read", line)
        self.assertIn("KeyError", line)

    def test_the_holds_line_joins_the_orientation_block(self) -> None:
        """Accept 2's "cannot miss it": the line is in the block ``run`` prints,
        and a fault in it costs only itself."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "p", "## Holds\n\n- " + A_REAL_HOLD + "\n")
            lines = keel_session.orientation_lines(project, {})
            self.assertEqual(len(lines), 5)
            holds_lines = [line for line in lines if ": holds -" in line]
            self.assertEqual(len(holds_lines), 1, lines)
            self.assertIn(A_REAL_HOLD, holds_lines[0])


class TestTheScopeBoundary(unittest.TestCase):
    """The narrow scope, asserted rather than promised: holds are READABLE and
    VISIBLE, never enforceable-as-gates."""

    def test_a_hold_never_becomes_a_gate_decision(self) -> None:
        """A project holding everything it can spell still gets exactly the
        verdict it would get with no holds at all. A hold is prose about intent;
        inventing a gating vocabulary for it is a separate design question, and
        a later change that quietly made holds refuse writes fails here."""
        holds = (
            "## Holds\n\n- no push until I review\n- do not touch src/\n"
            "- src/\n- /\n- .\n- deny everything\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            held = armed(root / "held", holds)
            free = armed(root / "free", "## Holds\n\n- *(none active)*\n")
            for project in (held, free):
                plans = project / ".keel" / "plans"
                plans.mkdir(parents=True, exist_ok=True)
                (plans / "keel-plan-abcdef12.md").write_text(
                    "# Plan\n\n- [ ] T1 the thing\n      Route: standard.\n"
                    "      Accept: it works.\n",
                    encoding="utf-8",
                )
            verdicts = []
            for project in (held, free):
                event = keel_events.KeelEvent(
                    kind="pre_write",
                    cwd=project,
                    session_id="abcdef123456",
                    tool_name="Write",
                    file_paths=(str(project / "src" / "thing.py"),),
                )
                verdicts.append(keel_gate.run(event, env={}))
            self.assertEqual(
                verdicts[0].blocking,
                verdicts[1].blocking,
                "a hold changed a gate decision - that is outside T175's scope",
            )
            self.assertEqual(keel_gate.holds_state(keel_gate.policy_lock_section(held)).lower(), "active")

    def test_a_hold_is_not_a_path_pattern(self) -> None:
        """The clearest statement of the boundary: a hold naming a directory
        does not lock that directory. ``lock:`` does that, and only ``lock:``."""
        section = section_for("## Holds\n\n- do not touch src/generated/\n")
        self.assertEqual(section.locked_paths, ())
        self.assertEqual(section.lock, ())


class TestWhatKeelShips(unittest.TestCase):
    """Accept 4, and the two shipped documents' own behaviour."""

    def test_this_repositorys_arming_file_reads_as_an_explicit_none(self) -> None:
        """The subject IS the ratified declaration: this project's own Holds
        section stands ``*(none active)*``, and must read as NONE - not as
        absent, and not as a hold literally named "(none active)".

        INVERTS IN A PUBLISHED CUT, which ships no arming file at all: there the
        claim has no subject, so the assertion becomes the shipped property
        itself - that nothing armed is present. Skipping would let a cut that
        accidentally shipped armed pass here in silence.
        """
        if is_published_cut(REPO_ROOT):
            self.assertFalse(
                (REPO_ROOT / ".keel" / "keel-policy.md").exists(),
                "a published cut must ship no arming file",
            )
            return
        section = shipped(".keel/keel-policy.md")
        self.assertTrue(section.holds_present)
        self.assertEqual(section.holds, ())
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_NONE)
        self.assertEqual(section.hold_errors, ())

    def test_the_shipped_template_teaches_without_declaring(self) -> None:
        """The rule that failed twice on the lock lists, pinned here for holds
        before it can fail a third time: an adopter who copies the template
        verbatim gets a readable, EMPTY holds section - not the example hold,
        and not an unreadable section either."""
        section = shipped("templates/keel-policy.md")
        self.assertEqual(section.holds, ())
        self.assertEqual(keel_gate.holds_state(section), keel_gate.HOLDS_NONE)
        self.assertEqual(section.hold_errors, (), "the shipped template must be readable")
        self.assertEqual(section.holds_ignored_indented, ())

    def test_neither_shipped_document_produces_a_holds_note(self) -> None:
        """The bounded-noise property, checked for the new section too: the law
        as actually written sits at column zero in both documents."""
        for relative in shipped_policy_documents(REPO_ROOT):
            with self.subTest(document=relative):
                self.assertEqual(shipped(relative).holds_ignored_indented, ())

    def test_the_template_states_both_halves_of_what_a_hold_does(self) -> None:
        """Accept 4: an adopter must not be misled in EITHER direction - not
        into thinking a hold is decoration, and not into thinking it gates."""
        text = (REPO_ROOT / "templates" / "keel-policy.md").read_text(encoding="utf-8")
        # Bounded by the NEXT REAL heading, named explicitly: this section
        # contains a fenced example that repeats the '## Holds' heading, and a
        # split on the next '## ' would cut the section off at its own example.
        holds_section = text.split("\n## Holds\n", 1)[1].split("\n## Local amendments", 1)[0]
        # what it DOES
        self.assertIn("castoff", holds_section)
        self.assertIn("survey", holds_section)
        # what it does NOT do
        self.assertIn("It refuses nothing.", holds_section)
        self.assertIn("not a path pattern", holds_section)
        # and the shape that makes it readable at all
        self.assertIn("COLUMN ZERO", holds_section)
        self.assertIn("*(none active)*", holds_section)


if __name__ == "__main__":
    unittest.main()
