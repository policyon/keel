#!/usr/bin/env python3
"""Every spelling of THIS user's home collapses to ``~``, including the two that leaked.

``tests/test_keel_home_shapes.py`` proves what happens to a home-SHAPED path
whose owner cannot be resolved: it becomes ``[home-path]``, the refusal to emit.
This file proves the other half - the spellings of the home directory that CAN
be resolved, each of which must reach the precise answer, ``~``, rather than
falling through to the coarse one.

The distinction is not cosmetic, and it is why every assertion here compares
against ``~`` rather than merely asserting that the account name is absent. The
coarse screen masks any ``…/<root>/<account>/…`` whatever its spelling, so an
"account name is gone" assertion passes even when the precise step has failed
completely - it would have passed on 2026-08-11, the day an account name reached
both tracked capture files 28 times. What tells the two apart is whether the
output says ``~``.

The shapes, and where each came from
------------------------------------
* The Windows absolute form and its forward-slash variant, in both cases.
* The DOUBLED separators a path carries after a JSON round trip, which is how
  ``scripts/keel_dashboard.py`` reads an audit line back.
* The MSYS / Git-Bash form ``/c/<root>/<account>``, with either drive case -
  the first of the two spellings that leaked on 2026-08-11, because it is what
  a ``bash`` tool call prints on Windows.
* The DOS 8.3 short form, with and without its dot-suffix continuation - the
  second one that leaked, because the session scratchpad an agent is handed is
  already spelled that way, so no care taken by the author of a command can
  avoid it. Derived here from the account name by ``eight_three_names``, which
  is what covers the machine whose volume will not generate one.
* A value embedded MID-COMMAND, which is the shape a leak actually takes: an
  assignment or a flag naming a path, never a bare path on its own.

Contract
--------
Reads   : the installation's own ``hooks/`` modules, and - in the last class
          only - this machine's real home directory, at run time, to prove the
          fix against the live environment rather than against a fixture.
Emits   : unittest results only.
Writes  : nothing at all.

NO REAL ACCOUNT NAME APPEARS IN THIS FILE, in any spelling, and the fixtures are
assembled from fragments so that no invented one is greppable as a single token
either. The last class necessarily handles the real one; it never asserts with
``assertEqual`` or ``assertIn`` on a value derived from it, because those report
their arguments when they fail and a failing test that prints the account name
would publish exactly what this module exists to withhold. It uses
``assertTrue`` with a message that names no value instead.

Failure policy
--------------
FAIL-CLOSED. Nothing here is skipped: every spelling is derivable on every
platform, because ``eight_three_names`` derives the 8.3 form from the name
rather than from the filesystem. The one Windows-only call (``short_form``) is
exercised in ``tests/test_keel_home_shapes.py`` and not repeated here.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_redact  # noqa: E402  (path must be set first)

#: The backslash, built rather than written. A literal one survives this file
#: perfectly well; it does NOT survive being retyped into a shell heredoc on the
#: way to a throwaway reproduction, which is how an earlier repair of this same
#: leak silently matched only the forward-slash half of every path it was given.
#: Building it here means a fragment copied out of this file behaves the same
#: wherever it is pasted.
BS = chr(92)

#: An invented account name, assembled from fragments. Two of them: one with a
#: period in it, because that is what makes an 8.3 short form carry a dot-suffix
#: continuation, and one without, because that is what makes it carry none.
ACCOUNT = "wex" + "ford" + "." + "quill" + "wick"
PLAIN_ACCOUNT = "wex" + "fordshire"

#: The 8.3 spellings those two names shorten to, written out so the test states
#: the expected answer rather than recomputing it with the code under test.
ACCOUNT_83 = "WEXFOR~1.QUI"
ACCOUNT_83_BARE = "WEXFOR~1"
PLAIN_83 = "WEXFOR~1"

#: The home root, as a constant for the reason ``tests/test_keel_home_shapes.py``
#: gives at its own ``WIN_ROOT``: no literal root followed by an account name
#: appears in this file's source, so ``scripts/keel_leak_check.py`` has nothing
#: invented to report.
WIN_ROOT = "Users"

#: The invented home directory, in the spelling an environment hands over.
HOME = "C:" + BS + WIN_ROOT + BS + ACCOUNT

#: A tail long enough to prove that only the prefix was replaced. This is the
#: real one: the session scratchpad, which is where both leaked spellings came
#: from, minus anything identifying.
TAIL = "/AppData/Local/Temp/claude/project/session/scratchpad/notes.txt"


def home_pattern(home: str) -> re.Pattern[str] | None:
    """``build_pattern`` for an invented home, through the production path.

    Built by ``build_pattern`` rather than by hand so ``home_candidates``,
    ``eight_three_names``, ``msys_form`` and ``_alternation`` are all inside
    the tested path instead of reimplemented here. ``home_candidates`` adds this
    machine's REAL home as well, from the live process rather than from the
    mapping handed in; that is harmless, because every fixture below is an
    invented path no real home can match.
    """
    return keel_redact.build_pattern({"USERPROFILE": home})


class _WithAnInventedHome(unittest.TestCase):
    """``_PATTERN`` built from ``HOME``, restored afterwards."""

    home = HOME

    def setUp(self) -> None:
        self._original = keel_redact._PATTERN
        keel_redact._PATTERN = home_pattern(self.home)

    def tearDown(self) -> None:
        keel_redact._PATTERN = self._original

    def assertCollapses(self, value: str, tail: str = TAIL) -> None:
        """``value + tail`` redacts to ``~ + tail`` - the precise answer.

        Deliberately not "the account name is absent": the coarse screen would
        satisfy that on its own, which is what makes it useless as a test of
        this step.
        """
        self.assertEqual(keel_redact.redact(value + tail), "~" + tail)


class TestTheSpellingsOfADriveLetterPath(_WithAnInventedHome):
    """The four ways the same absolute path is written down."""

    def test_the_windows_absolute_form(self) -> None:
        self.assertCollapses(HOME)

    def test_the_forward_slash_variant(self) -> None:
        self.assertCollapses(HOME.replace(BS, "/"))

    def test_either_case_of_the_whole_path(self) -> None:
        for value in (HOME.lower(), HOME.upper(), HOME.swapcase()):
            with self.subTest(spelling=len(value)):
                self.assertCollapses(value)

    def test_the_doubled_separators_of_a_path_stored_in_jsonl(self) -> None:
        """``scripts/keel_dashboard.py`` re-screens audit lines read back as
        TEXT, where JSON escaping has doubled every separator. Before the
        pattern tolerated the doubling this fell through to the coarse screen:
        the account name was masked, but as ``[home-path]``, which throws away
        the one fact redaction is meant to keep."""
        self.assertEqual(
            keel_redact.redact('{"cwd": "' + HOME.replace(BS, BS + BS) + '"}'),
            '{"cwd": "~"}',
        )


class TestTheMsysSpellingThatLeaked(_WithAnInventedHome):
    """``/c/<root>/<account>`` - what a ``bash`` tool call prints on Windows."""

    def test_the_msys_form(self) -> None:
        self.assertCollapses(f"/c/{WIN_ROOT}/{ACCOUNT}")

    def test_the_msys_form_with_an_upper_case_drive(self) -> None:
        """``msys_form`` lower-cases the drive letter, so the upper-case
        spelling is covered by the pattern's own case-insensitivity rather than
        by a second candidate. Asserted because that is an implicit dependency
        between two decisions made in different functions."""
        self.assertCollapses(f"/C/{WIN_ROOT}/{ACCOUNT}")

    def test_the_msys_form_is_a_candidate_spelling(self) -> None:
        candidates = keel_redact.home_candidates({"USERPROFILE": HOME})
        self.assertIn(f"/c/{WIN_ROOT}/{ACCOUNT}", candidates)

    def test_every_candidate_collapses_to_a_tilde(self) -> None:
        """The property the whole pattern rests on, asserted over the list
        rather than over the handful of spellings named above: a spelling worth
        putting in ``home_candidates`` is a spelling the compiled pattern
        matches. A candidate that does not is dead weight in the alternation
        and a false sense of coverage."""
        for candidate in keel_redact.home_candidates({"USERPROFILE": HOME}):
            with self.subTest(length=len(candidate)):
                self.assertEqual(keel_redact.redact(candidate + "/x"), "~/x")


class TestTheEightThreeSpellingDerivedFromTheNameAlone(_WithAnInventedHome):
    """The 8.3 form, derived rather than asked for.

    ``short_form`` asks Windows and is the better answer when Windows answers.
    These are the cases where it does not: short-name generation switched off on
    the volume, a home directory that does not exist, or a platform with no such
    call - and the case where it answers about the on-disk spelling only, while
    a captured command line carries the other one.
    """

    def test_the_dot_suffix_continuation(self) -> None:
        self.assertCollapses("C:" + BS + WIN_ROOT + BS + ACCOUNT_83)

    def test_the_bare_tilde_digit_form(self) -> None:
        self.assertCollapses("C:" + BS + WIN_ROOT + BS + ACCOUNT_83_BARE)

    def test_the_msys_spelling_of_the_short_form(self) -> None:
        """Both leaked spellings at once, which is the combination the session
        scratchpad actually produces: a ``bash`` command naming a path the
        harness handed over already shortened."""
        self.assertCollapses(f"/c/{WIN_ROOT}/{ACCOUNT_83}")

    def test_either_case_of_the_short_form(self) -> None:
        for value in (ACCOUNT_83.lower(), ACCOUNT_83.title()):
            with self.subTest(spelling=len(value)):
                self.assertCollapses("C:" + BS + WIN_ROOT + BS + value)

    def test_every_collision_ordinal_windows_would_number(self) -> None:
        """Windows numbers the first four colliding names ``~1``..``~4``. The
        ordinal cannot be known from the name, so all four are covered."""
        for ordinal in (1, 2, 3, 4):
            with self.subTest(ordinal=ordinal):
                spelling = ACCOUNT_83.replace("~1", f"~{ordinal}")
                self.assertCollapses("C:" + BS + WIN_ROOT + BS + spelling)

    def test_the_longer_form_wins_against_its_own_prefix(self) -> None:
        """The ordering guarantee, as a value rather than as an argument.

        ``WEXFOR~1`` is a prefix of ``WEXFOR~1.QUI``, so an alternation that
        offered the short one first would match it, replace it with ``~`` and
        leave ``.QUI`` behind - a fragment of the account name, which is still
        the leak. ``home_candidates`` sorts longest-first and ``_emit`` puts a
        terminal branch last at every node to keep that true after the shared
        prefix is factored out; this asserts the result of both.
        """
        redacted = keel_redact.redact("C:" + BS + WIN_ROOT + BS + ACCOUNT_83 + TAIL)
        self.assertEqual(redacted, "~" + TAIL)
        self.assertNotIn("QUI", redacted)

    def test_a_name_with_no_period_shortens_without_an_extension(self) -> None:
        keel_redact._PATTERN = home_pattern("C:" + BS + WIN_ROOT + BS + PLAIN_ACCOUNT)
        self.assertCollapses("C:" + BS + WIN_ROOT + BS + PLAIN_83)

    def test_what_the_derivation_returns(self) -> None:
        """``eight_three_names`` on its own, so a change to it is visible here
        rather than only through a pattern that might mask it."""
        derived = keel_redact.eight_three_names(ACCOUNT)
        self.assertEqual(derived[:2], [ACCOUNT_83, ACCOUNT_83_BARE])
        self.assertEqual(len(derived), 8, "four ordinals, each with and without the suffix")
        self.assertEqual(
            keel_redact.eight_three_names(PLAIN_ACCOUNT),
            [f"WEXFOR~{n}" for n in (1, 2, 3, 4)],
        )

    def test_the_cases_that_correctly_derive_nothing(self) -> None:
        """An empty list is an answer, not a failure: a name Windows would not
        shorten has no short form to add, and a name that already carries a
        ``~`` IS one - deriving from it would invent spellings the platform
        never generates."""
        for name in ("", "sam", "eightchr", ACCOUNT_83, "OTHER~2"):
            with self.subTest(length=len(name)):
                self.assertEqual(keel_redact.eight_three_names(name), [])

    def test_spaces_and_periods_are_dropped_not_substituted(self) -> None:
        """Windows removes the characters 8.3 has no room for, which is why a
        spaced name and a dotted one can shorten to the same six letters."""
        self.assertIn("FAKEPE~1", keel_redact.eight_three_names("Fake Person"))


class TestTheShapeALeakActuallyTakes(_WithAnInventedHome):
    """Not a bare path: an assignment or a flag inside a captured command line.

    Every one of the 28 occurrences on 2026-08-11 arrived this way, through
    ``hooks/keel_capture.py`` handing ``redact`` raw shell-command text. A test
    that only ever redacts a bare path proves the pattern and not the chokepoint.
    """

    def test_a_shell_assignment_naming_the_scratchpad(self) -> None:
        value = f'SP="/c/{WIN_ROOT}/{ACCOUNT_83}{TAIL}" && cd "$SP" && ls'
        self.assertEqual(keel_redact.redact(value), f'SP="~{TAIL}" && cd "$SP" && ls')

    def test_a_flag_naming_a_path_under_the_home_directory(self) -> None:
        value = f"pytest --basetemp=/c/{WIN_ROOT}/{ACCOUNT}/tmp -q"
        self.assertEqual(keel_redact.redact(value), "pytest --basetemp=~/tmp -q")

    def test_a_copy_between_the_project_and_the_scratchpad(self) -> None:
        value = "cp hooks/keel_redact.py " + '"C:' + BS + WIN_ROOT + BS + ACCOUNT_83 + BS + 'x"'
        self.assertEqual(keel_redact.redact(value), 'cp hooks/keel_redact.py "~' + BS + 'x"')

    def test_two_spellings_on_one_line_are_both_taken(self) -> None:
        value = f"cp C:{BS}{WIN_ROOT}{BS}{ACCOUNT}{BS}a /c/{WIN_ROOT}/{ACCOUNT_83}/b"
        self.assertEqual(keel_redact.redact(value), f"cp ~{BS}a ~/b")

    def test_ordinary_text_is_returned_as_the_same_object(self) -> None:
        """The guarantee the whole module rests on, re-asserted with the larger
        alternation in place: a line carrying no home path is not reshaped."""
        value = "git commit -m 'the gate learned to name what it permits'"
        self.assertIs(keel_redact.redact(value), value)


class TestTheFactoredAlternationIsTheFlatOne(_WithAnInventedHome):
    """The optimisation changes cost, not meaning.

    ``_alternation`` factors the shared leading text of every spelling into a
    trie so the branch count stops being a per-line cost. That is a rewrite of
    the pattern's structure, and a rewrite of a guard's pattern is exactly the
    kind of change that looks equivalent and is not - so equivalence is asserted
    against the flat alternation it replaced, over every spelling this machine
    actually produces, rather than argued in a comment.
    """

    def flat(self, homes: list[str]) -> re.Pattern[str]:
        """The alternation as it was written before the trie: one branch per
        spelling, longest first. Built from ``_atoms`` so this is the flat SHAPE
        of the production atoms and not a second guess at the separator rule."""
        branches = ["".join(keel_redact._atoms(home)) for home in homes]
        return re.compile(
            "(?:" + "|".join(branches) + ")" + keel_redact._BOUNDARY, re.IGNORECASE
        )

    def test_the_two_forms_agree_on_every_spelling(self) -> None:
        for source in (HOME, "C:" + BS + WIN_ROOT + BS + PLAIN_ACCOUNT):
            homes = keel_redact.home_candidates({"USERPROFILE": source})
            factored, flat = home_pattern(source), self.flat(homes)
            for candidate in homes:
                for tail in ("/x", BS + "x", "", " and prose"):
                    value = candidate + tail
                    with self.subTest(length=len(candidate), tail=len(tail)):
                        self.assertEqual(factored.sub("~", value), flat.sub("~", value))

    def test_the_two_forms_agree_that_ordinary_text_is_untouched(self) -> None:
        homes = keel_redact.home_candidates({"USERPROFILE": HOME})
        factored, flat = home_pattern(HOME), self.flat(homes)
        for value in ("git status", f"C:{BS}Windows{BS}System32", f"/c/{WIN_ROOT}", "~/x"):
            with self.subTest(value=value):
                self.assertEqual(factored.sub("~", value), flat.sub("~", value))
                self.assertEqual(factored.sub("~", value), value)


class TestWhatIsLeftToTheCoarseScreenOnPurpose(_WithAnInventedHome):
    """The reviewer's question - what OTHER spelling exists - answered as tests.

    Each of these is a spelling the precise step does NOT claim. None of them
    leaks: every one still carries a home root, so ``screen_home_shapes`` masks
    the account name. What is lost is the ``~``, which is information about a
    path, not information about a person - the trade this module makes
    everywhere, argued at ``_HOME_SHAPE_RE``.
    """

    def masked_not_named(self, value: str, name: str) -> None:
        redacted = keel_redact.redact(value)
        self.assertIn(keel_redact.HOME_SHAPE_TOKEN, redacted)
        self.assertNotIn(name, redacted)

    def test_the_hashed_8_3_base_after_five_collisions(self) -> None:
        """Windows stops numbering after ``~4`` and puts a hash of the long name
        into the base. It cannot be derived from the name - only ``short_form``
        can see it, on a machine whose volume answers."""
        self.masked_not_named("C:" + BS + WIN_ROOT + BS + "WE1A2B~1" + BS + "x", "WE1A2B")

    def test_a_shortened_parent_segment(self) -> None:
        """Only the final segment is derived, because only the final segment
        carries the account name."""
        self.masked_not_named("C:" + BS + "DOCUME~1" + BS + WIN_ROOT + BS + ACCOUNT, ACCOUNT)

    def test_a_percent_encoded_separator_is_below_the_floor(self) -> None:
        """Stated rather than fixed, and stated as a FAILING shape so nobody
        mistakes it for covered: no keel component and no captured tool call
        produces an encoded path, so it is left to the scan."""
        value = "C:%5C" + WIN_ROOT + "%5C" + ACCOUNT
        self.assertIn(ACCOUNT, keel_redact.redact(value))


class TestTheTranslationsNobodyAddedAndNobodyNeedsTo(_WithAnInventedHome):
    """Cygwin and WSL spell a Windows drive their own way, and both are covered.

    Neither is a candidate, and neither should be: ``msys_form``'s own rule is
    that a translation nothing on this platform emits is one more alternative
    every captured line pays for, and nothing keel runs prints either of them.
    They are covered anyway, and by accident rather than by design - both
    embed the MSYS spelling as a SUBSTRING (``/cygdrive`` + ``/c/<root>/…``),
    so the candidate matches inside them.

    Recorded as tests because "covered by accident" is worth knowing precisely:
    what comes out is not a usable path (``/cygdrive~/x``), only a safe one. If
    a future change makes either of these spellings matter as a path rather than
    as a leak, the fix is a candidate in ``home_candidates``, not a second
    pattern - and these tests will fail and say so.
    """

    def collapsed_but_mangled(self, prefix: str) -> None:
        redacted = keel_redact.redact(f"{prefix}/c/{WIN_ROOT}/{ACCOUNT}/x")
        self.assertEqual(redacted, f"{prefix}~/x")
        self.assertNotIn(ACCOUNT, redacted)

    def test_the_cygwin_translation(self) -> None:
        self.collapsed_but_mangled("/cygdrive")

    def test_the_wsl_translation(self) -> None:
        self.collapsed_but_mangled("/mnt")


class TestThisMachinesOwnHomeAtRunTime(unittest.TestCase):
    """The live environment, not a fixture - and the only class that touches it.

    Every value here is derived at run time from ``Path.home()``. Nothing is
    compared with ``assertEqual``, ``assertIn`` or ``assertNotIn``, because all
    three report their arguments when they fail, and a failing assertion that
    prints this machine's account name would put it in a build log - the exact
    outcome the module exists to prevent. ``assertTrue`` with a message naming
    no value is the whole reason this class reads differently from the rest.
    """

    def setUp(self) -> None:
        self.home = str(Path.home())
        self.account = os.path.basename(self.home)

    def spellings(self) -> list[str]:
        """This machine's home in every spelling under test, at run time."""
        found = [self.home, self.home.replace(BS, "/"), self.home.upper(), self.home.lower()]
        translated = keel_redact.msys_form(self.home)
        if translated:
            found.append(translated)
        parent, name = keel_redact._split_last_segment(self.home)
        for form in keel_redact.eight_three_names(name):
            found.append(parent + form)
            shortened = keel_redact.msys_form(parent + form)
            if shortened:
                found.append(shortened)
        return found

    def test_the_account_name_survives_no_spelling(self) -> None:
        for index, spelling in enumerate(self.spellings()):
            with self.subTest(spelling=index):
                redacted = keel_redact.redact(spelling + TAIL)
                self.assertTrue(
                    redacted == "~" + TAIL,
                    "a spelling of this machine's home did not collapse to ~ "
                    f"(spelling {index}); the value is withheld on purpose",
                )
                self.assertTrue(
                    self.account.casefold() not in redacted.casefold(),
                    f"the account name survived redaction (spelling {index})",
                )
                self.assertTrue(
                    self.home.casefold() not in redacted.casefold(),
                    f"the home path survived redaction (spelling {index})",
                )

    def test_the_account_name_survives_no_spelling_inside_a_command(self) -> None:
        """The same values in the shape they actually arrive in."""
        for index, spelling in enumerate(self.spellings()):
            with self.subTest(spelling=index):
                redacted = keel_redact.redact(f'SP="{spelling}{TAIL}" && cd "$SP"')
                self.assertTrue(
                    redacted == f'SP="~{TAIL}" && cd "$SP"',
                    f"a home spelling inside a command was not collapsed ({index})",
                )
                self.assertTrue(
                    self.account.casefold() not in redacted.casefold(),
                    f"the account name survived redaction ({index})",
                )

    def test_every_candidate_this_machine_offers_is_matched(self) -> None:
        """The live equivalent of the invented-home property above: whatever
        ``home_candidates`` resolved on THIS machine, the compiled pattern
        matches it. This is the assertion that would have failed on 2026-08-11."""
        candidates = keel_redact.home_candidates()
        self.assertTrue(candidates, "no home directory resolved on this machine")
        for index, candidate in enumerate(candidates):
            with self.subTest(candidate=index):
                self.assertTrue(
                    keel_redact.redact(candidate + "/x") == "~/x",
                    f"a resolved home spelling is not matched by the pattern ({index})",
                )


if __name__ == "__main__":
    unittest.main()
