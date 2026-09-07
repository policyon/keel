#!/usr/bin/env python3
"""A home directory is redacted in EVERY spelling, not only the literal prefix.

``tests/test_keel_wave2.py`` proves the absolute prefix collapses to ``~``.
This file proves the shapes that prefix cannot match, each of which was found
in this repository's own tracked logs on 2026-08-10 by
``python scripts/keel.py leak-check``:

* the Windows absolute form, and the forward-slash variant of it;
* the Windows 8.3 short form - and, separately, a TRUNCATED 8.3 path, which is
  what a captured command line cut off mid-segment leaves behind;
* the MSYS / Git-Bash form ``/c/<root>/<account>/…``, which is what a ``bash``
  tool call prints on Windows;
* a path that reaches a home directory by RELATIVE ESCAPE,
  ``../../<root>/<account>/x``, which is what ``os.path.relpath`` makes of an
  absolute home path - ``hooks/keel_gate.py``'s ``relativise`` produces exactly
  this, upstream of the write-time chokepoint, for any write outside the project
  while no fresh plan is on file;
* and the shape that defeated the first four passes over the redactor: a home
  root NESTED below something, ``<drive>:\<subfolder>\<root>\<account>``, which is
  an ordinary backup or mirrored-drive layout. It is unresolvable from the
  environment, so the precise pattern cannot see it, and no enumerated lead
  stood beside it, so the shape screen could not either. It reaches the tracked
  log through RAW CAPTURED COMMAND TEXT - ``hooks/keel_capture.py`` hands
  ``redact`` whatever a shell tool call contained - which is the writer this
  repository's real 2026-08-10 leak actually came through.

Three kinds of test, and the last two are the ones that matter
--------------------------------------------------------------
The function tests below drive ``keel_redact`` directly.
``TestTheChosenOverMatchAndWhatItCosts`` states the trade the screen makes, in
BOTH directions, so the next reader finds a decision rather than an accident.
And the last two classes drive real entry points -``keel_gate.run`` and
``keel_capture.run`` - then read the audit log and the observation queue back
off DISK, because the finding this file answers was about what reaches a
git-tracked file, and only the file can answer that. A test that calls the
redactor cannot see a value that never reached it, which is precisely how the
capture writer stayed unproven while three fixes were made to the module it
calls.

Parity with the second line of defence is asserted rather than assumed:
``scripts/keel_leak_check.py``'s own ``home_path_findings`` is run over
``redact``'s output for every shape here. That is the property the fix stands
on - anything the scanner would report later, the redactor removes first - and
it is stated as a test so a future pattern change cannot quietly break it.

Contract
--------
Reads   : the installation's own ``hooks/`` and ``scripts/`` modules. Nothing
          else on disk.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes; the
          gate is always pointed at a throwaway project, never at this
          repository's own ``.keel/``.

NO REAL USERNAME APPEARS ANYWHERE IN THIS FILE. Every fixture uses the invented
account names below, and the one test that must exercise a spelling only
Windows can generate asks Windows for the short form of a directory this test
created, rather than naming a real one. The two tests that assert a value is
NOT redacted use a path on an invented drive for the same reason: asserting
"unchanged" about a real home path would mean printing one.

NO LITERAL HOME ROOT APPEARS EITHER, and that is a separate decision from the
one above - see ``WIN_ROOT`` for why the fixtures are assembled from parts.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails it rather than
skipping it. The one exception is the 8.3 short-form test, which is skipped off
Windows because 8.3 names do not exist there - the shape is unreachable rather
than unchecked.

Constraints
----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import io
import json
import ntpath
import os
import sys
import tempfile
import unittest
import uuid
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_leak_check  # noqa: E402
import keel_redact  # noqa: E402

#: An invented account name. Not a person, and not this machine's user: the
#: whole point of the fixtures is that they carry no personal data.
FAKE = "fakeuser"

#: A second one, for the shapes that are somebody else's home rather than this
#: machine's own.
OTHER = "someoneelse"

#: An invented 8.3 short form, spelled the way Windows spells one, and the
#: truncation of it that a cut-off command line leaves behind. Every part is
#: synthetic, INCLUDING the dot-suffix: an 8.3 extension derives from the
#: account name, so a real suffix on a fake account is still a fragment of a
#: real identity - a security review found exactly that here on 2026-08-11.
FAKE_SHORT = "FAKEUS~1.XYZ"
FAKE_CUT = "FAKEUS~1."

#: An invented account name with spaces, which Windows permits.
FAKE_SPACED = "Fake Person"

#: The Windows/macOS home root, and the POSIX one, spelled through constants so
#: that no LITERAL home root followed by a name appears in this file's source.
#: The fixtures are invented, but ``scripts/keel_leak_check.py`` cannot know
#: that - it would report every one of them, and forty invented findings in a
#: build gate is how a real one goes unnoticed. The gate does offer a
#: line-level escape hatch (``keel-leak: ignore``) and this file could have
#: used it forty times; assembling the fixtures from parts keeps the gate's
#: output honest without putting a suppression comment on half the file. Every
#: fixture is still readable as the path it stands for.
WIN_ROOT = "Users"
NIX_ROOT = "home"

#: An invented home directory, in the spelling the environment hands over.
FAKE_HOME = f"C:\\{WIN_ROOT}\\{FAKE}"

#: A path on a drive nothing here uses, for the "left alone" assertions.
UNTOUCHED = "Q:\\projects\\thing\\module.py"

#: The marker a shape that cannot be expressed safely becomes.
MARK = keel_redact.HOME_SHAPE_TOKEN


def leak_findings(value: str) -> list[str]:
    """``scripts/keel_leak_check.py``'s home-path verdict on one value.

    The SECOND line of defence, asked directly. A value that passes this has
    nothing for the pre-push scan to find later, whatever this module's own
    pattern happens to look like.
    """
    return [finding.excerpt for finding in keel_leak_check.home_path_findings("x", 1, value)]


class _WithAFakeHome(unittest.TestCase):
    """``_PATTERN`` built from an invented home, restored afterwards.

    Built through ``build_pattern`` rather than by hand, so ``home_candidates``
    and ``msys_form`` are inside the tested path rather than reimplemented
    here. ``home_candidates`` always adds this machine's REAL home as well
    (``os.path.expanduser("~")``, read from the live process, never from the
    env handed in); that is harmless, because every fixture below is an
    invented path the real home cannot match, and it is preferable to
    duplicating the pattern construction in a test.

    BOTH patterns are rebuilt, not just ``_PATTERN``. ``_HOME_SHAPE_RE`` is
    now derived from the running home too (``build_home_shape_pattern``), so a
    fixture that replaced only the first would leave the screen answering
    about the REAL machine's home shape while the prefix pattern answered
    about the invented one. For this particular invented home - a Windows
    ``Users`` home - the derived pattern is identical to the undecorated one,
    which is itself the point of ``test_an_ordinary_home_derives_no_extra_root``
    below; rebuilding it here is what makes that a measurement rather than an
    assumption.
    """

    def setUp(self) -> None:
        self._original = keel_redact._PATTERN
        self._original_shape = keel_redact._HOME_SHAPE_RE
        keel_redact._PATTERN = keel_redact.build_pattern({"USERPROFILE": FAKE_HOME})
        keel_redact._HOME_SHAPE_RE = keel_redact.build_home_shape_pattern(
            {"USERPROFILE": FAKE_HOME}
        )

    def tearDown(self) -> None:
        keel_redact._PATTERN = self._original
        keel_redact._HOME_SHAPE_RE = self._original_shape


class TestTheSpellingsThatCollapseToATilde(_WithAFakeHome):
    """Shapes of THIS user's own home: precise, so they still get ``~``.

    A marker would be a loss of information here. ``~`` is only correct when
    the value really is this user's home directory, which is what
    ``home_candidates`` decides from the environment.
    """

    def test_the_windows_absolute_form(self) -> None:
        self.assertEqual(keel_redact.redact(FAKE_HOME + "\\notes.txt"), "~\\notes.txt")

    def test_the_forward_slash_variant(self) -> None:
        self.assertEqual(
            keel_redact.redact(f"C:/{WIN_ROOT}/{FAKE}/notes.txt"), "~/notes.txt"
        )

    def test_the_msys_git_bash_form(self) -> None:
        """The shape a ``bash`` tool call prints on Windows, and the reason
        ``msys_form`` exists: the literal ``USERPROFILE`` prefix is nowhere in
        it, so no amount of separator tolerance would have found it."""
        self.assertEqual(
            keel_redact.redact(f"/c/{WIN_ROOT}/{FAKE}/.claude/hooks"), "~/.claude/hooks"
        )

    def test_the_msys_translation_itself(self) -> None:
        self.assertEqual(keel_redact.msys_form(FAKE_HOME), f"/c/{WIN_ROOT}/{FAKE}")
        self.assertEqual(keel_redact.msys_form("d:/data/x"), "/d/data/x")
        for value in ("", "relative/path", "C:", "/already/posix"):
            with self.subTest(value=value):
                self.assertIsNone(keel_redact.msys_form(value))

    def test_the_msys_form_is_among_the_candidates(self) -> None:
        candidates = keel_redact.home_candidates({"USERPROFILE": FAKE_HOME})
        self.assertIn(f"/c/{WIN_ROOT}/{FAKE}", candidates)
        self.assertEqual(
            candidates, sorted(candidates, key=len, reverse=True), "longest first is the contract"
        )

    def test_the_8_3_short_form_as_a_candidate_spelling(self) -> None:
        """The 8.3 form is just another spelling once the environment offers
        it; this asserts the pattern honours it without needing Windows to
        generate one."""
        keel_redact._PATTERN = keel_redact.build_pattern(
            {"USERPROFILE": f"C:\\{WIN_ROOT}\\{FAKE_SHORT}"}
        )
        self.assertEqual(keel_redact.redact(f"C:\\{WIN_ROOT}\\{FAKE_SHORT}\\x"), "~\\x")

    @unittest.skipUnless(os.name == "nt", "8.3 short names exist on Windows only")
    def test_windows_own_short_form_of_a_real_directory(self) -> None:
        """The claim in the module docstring, asked of Windows rather than of a
        fixture: a directory this test creates, its short form obtained from
        ``GetShortPathNameW``, redacted through a pattern built from the LONG
        form alone. No real home directory is named."""
        with tempfile.TemporaryDirectory() as tmp:
            long_form = str(Path(tmp) / "a directory with spaces")
            os.mkdir(long_form)
            short = keel_redact.short_form(long_form)
            if not short or short.casefold() == long_form.casefold():
                self.skipTest("this volume does not generate 8.3 short names")
            keel_redact._PATTERN = keel_redact.build_pattern({"USERPROFILE": long_form})
            self.assertEqual(keel_redact.redact(short + "\\x"), "~\\x")


class TestTheSpellingsThatCannotBeExpressedSafely(_WithAFakeHome):
    """Shapes from which no prefix pattern can recover a home directory.

    Each of these is answered with ``HOME_SHAPE_TOKEN`` - the refusal to emit -
    rather than with ``~``, which would be a claim this module cannot support,
    or with the text itself, which is the leak.
    """

    def test_the_relative_escape_relpath_produces(self) -> None:
        """THE REVIEWER'S FINDING, as a value. ``os.path.relpath`` spells an
        absolute home path this way, and the literal prefix is gone from it."""
        value = f"../../{WIN_ROOT}/{FAKE}/x"
        self.assertEqual(keel_redact.redact(value), f"../../{MARK}/x")
        self.assertNotIn(FAKE, keel_redact.redact(value))

    def test_relpath_always_puts_the_chain_next_to_the_home_root(self) -> None:
        """Why the ``../`` context is sufficient rather than a lucky guess.

        ``relpath`` climbs to the common ancestor and descends again, so an
        absolute home path comes back with the ``../`` chain IMMEDIATELY before
        the home root however deep the starting directory is. Demonstrated
        rather than asserted about the pattern, because it is a property of
        ``os.path``, and it is what lets the screen require a context at all.
        ``ntpath`` explicitly, so the demonstration is the same on any platform
        the suite runs on.
        """
        for start in ("C:\\W", "C:\\W\\P", "C:\\W\\P\\Keel\\deeper"):
            with self.subTest(start=start):
                relative = ntpath.relpath(FAKE_HOME + "\\x", start).replace("\\", "/")
                self.assertRegex(relative, r"^(?:\.\./)+" + WIN_ROOT + "/")
                self.assertNotIn(FAKE, keel_redact.redact(relative))
                self.assertIn(MARK, keel_redact.redact(relative))

    def test_a_truncated_8_3_path(self) -> None:
        """The shape that actually reached this repository's audit log: a
        captured command line cut off mid-segment, leaving a genuine PREFIX of
        a home directory, which is a complete spelling of nothing."""
        value = f'git status --porcelain > "C:\\{WIN_ROOT}\\{FAKE_CUT}'
        redacted = keel_redact.redact(value)
        self.assertEqual(redacted, f'git status --porcelain > "C:\\{MARK}')
        self.assertNotIn("FAKEUS", redacted)

    def test_another_account_in_the_windows_absolute_form(self) -> None:
        self.assertEqual(
            keel_redact.redact(f"C:\\{WIN_ROOT}\\{OTHER}\\x"), f"C:\\{MARK}\\x"
        )

    def test_another_account_in_the_msys_form(self) -> None:
        self.assertEqual(keel_redact.redact(f"/c/{WIN_ROOT}/{OTHER}/x"), f"/c/{MARK}/x")

    def test_the_posix_home_form(self) -> None:
        self.assertEqual(keel_redact.redact(f"/{NIX_ROOT}/{OTHER}/x"), f"/{MARK}/x")

    def test_the_macos_users_form(self) -> None:
        self.assertEqual(keel_redact.redact(f"/{WIN_ROOT}/{OTHER}/x"), f"/{MARK}/x")

    def test_a_username_with_spaces_in_it(self) -> None:
        """Windows permits it, so the name branch allows spaces - but only
        where a separator follows, so the match cannot run off the end of the
        segment and swallow the prose around it."""
        self.assertEqual(
            keel_redact.redact(f"C:\\{WIN_ROOT}\\{FAKE_SPACED}\\notes.txt"),
            f"C:\\{MARK}\\notes.txt",
        )

    def test_prose_after_a_path_is_not_swallowed(self) -> None:
        """The other half of the same bargain: with no separator to stop at,
        only the single token is taken."""
        self.assertEqual(
            keel_redact.redact(f"see C:\\{WIN_ROOT}\\{OTHER} for the rest"),
            f"see C:\\{MARK} for the rest",
        )

    def test_the_doubled_separators_of_a_path_stored_in_jsonl(self) -> None:
        """``keel_dashboard.py`` re-screens lines read back off disk as TEXT,
        where every separator is doubled by JSON escaping."""
        self.assertEqual(
            keel_redact.redact('{"p": "C:\\\\' + WIN_ROOT + "\\\\" + OTHER + '\\\\x"}'),
            '{"p": "C:\\\\' + MARK + '\\\\x"}',
        )

    def test_the_case_of_the_spelling_does_not_matter(self) -> None:
        for value in (
            f"C:\\{WIN_ROOT.upper()}\\{OTHER}\\x",
            f"/{NIX_ROOT.upper()}/{OTHER}/x",
        ):
            with self.subTest(value=value):
                self.assertIn(MARK, keel_redact.redact(value))

    def test_a_network_profile_root(self) -> None:
        """One shape where the redactor is BROADER than the scanner, which is
        the direction to be broad in: an all-backslash UNC path matches neither
        of the scanner's Windows patterns, so this one is stopped at write time
        or not at all. Kept out of the parity list below for that reason."""
        value = f"\\\\server\\{WIN_ROOT}\\{OTHER}\\x"
        self.assertEqual(keel_redact.redact(value), f"\\\\server\\{MARK}\\x")
        self.assertEqual(leak_findings(value), [], "the scan does not see this shape")

    def test_a_rooted_path_inside_a_captured_command_line(self) -> None:
        """The lead may be a separator at a TOKEN start, which is how a home
        path appears in a command keel captured rather than authored."""
        nix = f"/{NIX_ROOT}/{OTHER}"
        for value, expected in (
            (f"find {nix} -name x", f"find /{MARK} -name x"),
            (f"--out={nix}/x", f"--out=/{MARK}/x"),
            ('{"p": "' + nix + '/x"}', '{"p": "/' + MARK + '/x"}'),
            (f"cd ({nix}/x)", f"cd (/{MARK}/x)"),
            (f"a;{nix}/x", f"a;/{MARK}/x"),
            (f"cat <ledger {nix}/x", f"cat <ledger /{MARK}/x"),
            (f"one\n{nix}/x", f"one\n/{MARK}/x"),
        ):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.redact(value), expected)

    def test_a_pseudo_account_is_left_alone(self) -> None:
        """A pseudo-account names nobody, and the scanner passes over it too -
        the two lines of defence agree by sharing the list."""
        for name in ("Public", "Default", "All Users"):
            with self.subTest(name=name):
                value = f"C:\\{WIN_ROOT}\\{name}\\x"
                self.assertEqual(keel_redact.redact(value), value)
                self.assertEqual(leak_findings(value), [])


class TestOrdinaryTextIsReturnedUnchanged(_WithAFakeHome):
    """The guarantee the whole module rests on: a value carrying none of the
    four exclusions comes back as the SAME string object, not a copy that
    happens to be equal. A screen that quietly reshaped ordinary text would
    corrupt every record in the project."""

    def test_a_path_with_no_home_shape_is_the_same_object(self) -> None:
        for value in (
            UNTOUCHED,
            "src/app.py",
            "hooks/keel_redact.py:258",
            "the user's home directory",
            f"{WIN_ROOT} of this project should read the policy",
        ):
            with self.subTest(value=value):
                self.assertIs(keel_redact.redact(value), value)

    def test_the_screen_alone_fails_open_on_a_non_string(self) -> None:
        for value in (None, 17, {"a": 1}, ["b"], 3.5):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.screen_home_shapes(value), value)


class TestAHomeRootNestedBelowAnythingAtAll(_WithAFakeHome):
    """THE SHAPE THAT DEFEATED FOUR PASSES OVER THIS MODULE, now closed.

    Each earlier version required a RECOGNISED lead before the home root - a
    drive letter, a UNC server, ``/c/``, a ``../`` chain, a separator at a token
    start - and each closed the spelling it had been shown and left the property
    reachable by the next one. The one below is not exotic: a mirrored or backup
    drive puts an ordinary subfolder between the drive and ``<root>``, the
    account is not this machine's own so nothing can resolve it from the
    environment, and the text arrives as RAW CAPTURED COMMAND LINE - so neither
    ``_PATTERN`` nor an enumerated lead could see it and a real account name
    reached a git-tracked file verbatim.

    The rule is now a property of the text rather than a catalogue: a home root
    is a home root wherever it begins a path segment. These cases are therefore
    a sample of an infinite class, not the new list - what makes them pass is
    that nothing about what precedes the root is consulted at all.
    """

    NESTED = (
        f"D:\\Backup\\{WIN_ROOT}\\{FAKE}\\x",
        f"D:/Data/{WIN_ROOT}/{FAKE}/x",
        f"../elsewhere/{WIN_ROOT}/{FAKE}/x",
        f"ls -la D:\\mirror\\c\\{WIN_ROOT}\\{OTHER}\\Documents",
        f"grep -rn thing /mnt/backup/{NIX_ROOT}/{OTHER}/src",
        f"{WIN_ROOT}/{OTHER}/x",
        '{"p": "' + f"{WIN_ROOT}/{OTHER}" + '/x"}',
        f"tar -cf out.tar volume1/data/{NIX_ROOT}/{OTHER}",
    )

    def test_the_account_name_never_survives_however_deep_the_root_sits(self) -> None:
        for value in self.NESTED:
            with self.subTest(value=value):
                redacted = keel_redact.redact(value)
                self.assertIn(MARK, redacted)
                self.assertNotIn(FAKE, redacted)
                self.assertNotIn(OTHER, redacted)

    def test_the_tail_of_the_path_is_kept_and_only_the_name_goes(self) -> None:
        """The screen is a refusal to emit ONE segment, not a truncation: what
        makes the line worth reading survives, because it carries no name."""
        for value, expected in (
            (f"D:\\Backup\\{WIN_ROOT}\\{FAKE}\\x", f"D:\\Backup\\{MARK}\\x"),
            (f"D:/Data/{WIN_ROOT}/{FAKE}/x", f"D:/Data/{MARK}/x"),
            (f"../elsewhere/{WIN_ROOT}/{FAKE}/x", f"../elsewhere/{MARK}/x"),
            (f"{WIN_ROOT}/{OTHER}/x", f"{MARK}/x"),
        ):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.redact(value), expected)

    def test_the_nested_shape_was_a_real_leak_and_not_all_of_it_is_scannable(self) -> None:
        """Why closing it at write time mattered rather than leaving it to the
        scan: the all-backslash nested spelling is invisible to the second line
        of defence, whose Windows pattern demands the drive-adjacency this class
        is about not demanding. Pinned so nobody argues the scan had it."""
        seen_by_the_scan = {
            f"D:/Data/{WIN_ROOT}/{FAKE}/x": True,
            f"../elsewhere/{WIN_ROOT}/{FAKE}/x": True,
            f"D:\\Backup\\{WIN_ROOT}\\{FAKE}\\x": False,
        }
        for value, scannable in seen_by_the_scan.items():
            with self.subTest(value=value):
                self.assertNotIn(FAKE, keel_redact.redact(value))
                self.assertEqual(bool(leak_findings(value)), scannable)


class TestTheChosenOverMatchAndWhatItCosts(_WithAFakeHome):
    """THE TRADE, STATED AS A TEST, because it is a decision and not an accident.

    Believing a ``<root>`` segment wherever it appears means believing it in
    text that is no home directory at all. ``docs/<root>/README`` becomes
    ``docs/[home-path]``; a captured ``cat $HOME/notes.txt`` becomes
    ``cat $[home-path]``. That is information lost from a log line.

    The direction was chosen rather than stumbled into: the other direction -
    asking for more context before believing the root - is the rule that failed
    four times, and its failure writes a real person's account name into a
    git-tracked, pushed file. A mangled path is recoverable; the command, the
    tool and the session that produced it sit in the same record, and the scan
    still reports the shape for triage. A leaked name cannot be un-leaked. So
    the screen mangles, on purpose, and the cost is pinned here so the next
    reader who trips over ``docs/[home-path]`` in a log finds the reasoning
    instead of filing a bug.
    """

    def test_an_innocent_path_with_a_root_segment_is_mangled_deliberately(self) -> None:
        for value, expected in (
            (f"docs/{WIN_ROOT}/README", f"docs/{MARK}"),
            (f"src/{NIX_ROOT}/index.tsx", f"src/{MARK}"),
            (f"app/{WIN_ROOT}/list.tsx", f"app/{MARK}"),
            ("cat $HOME/notes.txt", f"cat ${MARK}"),
            (f"C:\\projects\\app\\{NIX_ROOT}\\index.tsx", f"C:\\projects\\app\\{MARK}"),
        ):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.redact(value), expected)

    def test_what_is_lost_is_a_path_and_never_the_event_around_it(self) -> None:
        """The bound on the cost: the mangling is confined to the root segment
        and the one after it. The verb, the flags and the rest of the line - the
        part that lets a reader re-derive the path - are untouched, which is the
        whole reason this direction is the cheap one."""
        redacted = keel_redact.redact(f"npm run build -- --out app/{WIN_ROOT}/dist/main.js")
        self.assertEqual(redacted, f"npm run build -- --out app/{MARK}/main.js")

    def test_the_two_lines_of_defence_now_agree_on_a_mid_path_root(self) -> None:
        """This USED to be the one place the redactor was narrower than the
        scanner, and the asymmetry was the hole. The forward-slash spellings the
        scanner reports are now all rewritten before the write, so nothing
        ``redact`` emits carries a finding - asserted with the scanner's own
        function rather than by reading its source."""
        for value in (f"docs/{WIN_ROOT}/README", f"src/{NIX_ROOT}/index.tsx"):
            with self.subTest(value=value):
                self.assertNotEqual(leak_findings(value), [], "fixture proves nothing")
                self.assertEqual(leak_findings(keel_redact.redact(value)), [])

    def test_a_root_that_is_the_tail_of_a_longer_word_is_the_bounded_residual(self) -> None:
        """THE ONE THING THAT STILL DISQUALIFIES A ROOT, and the honest account
        of what it costs.

        A word character immediately before ``<root>`` means the text is not a
        segment but the end of a longer name - ``superusers/list.txt``,
        ``my<root>/config`` - and there is no home root in it to screen. The
        price is that a directory literally NAMED ``Old<root>`` keeps the
        account beneath it, and the scan does not see that either.

        It is named here rather than buried because it is the residual of a rule
        that FAILS CLOSED: to get past the screen the character before the root
        must be one of a fixed, tiny set, so every spelling nobody thought of is
        screened. The enumeration this replaced failed the other way - anything
        not on its list passed - which is why each of four passes over it closed
        one spelling and left the property open to the next, and why this rule
        cannot leak on a shape merely because the shape is new.
        """
        for value in (
            "superusers/list.txt",
            f"my{NIX_ROOT}/config.json",
            f"C:\\Old{WIN_ROOT}\\{FAKE}\\x",
        ):
            with self.subTest(value=value):
                self.assertIs(keel_redact.redact(value), value)
        self.assertEqual(
            leak_findings(f"C:\\Old{WIN_ROOT}\\{FAKE}\\x"),
            [],
            "and the scan does not cover the residual either - say so, do not imply otherwise",
        )


class TestTheScreenNeedsNoEnvironmentAtAll(unittest.TestCase):
    """A machine where no home directory resolves used to mean every username
    passed through untouched. It no longer does: the shape screen reads nothing
    and still keeps the name out. The warning is still printed, because the
    ``~`` collapse really is lost."""

    def setUp(self) -> None:
        self._original = keel_redact._PATTERN
        self._warned = set(keel_redact._WARNED)
        keel_redact._PATTERN = None
        keel_redact._WARNED.clear()

    def tearDown(self) -> None:
        keel_redact._PATTERN = self._original
        keel_redact._WARNED.clear()
        keel_redact._WARNED.update(self._warned)

    def test_a_username_is_still_marked_with_no_pattern_at_all(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            redacted = keel_redact.redact(FAKE_HOME + "\\notes.txt")
        self.assertEqual(redacted, f"C:\\{MARK}\\notes.txt")
        self.assertIn("no home directory could be resolved", stderr.getvalue())


class TestParityWithTheSecondLineOfDefence(_WithAFakeHome):
    """Nothing ``redact`` emits can carry a ``home_path`` finding.

    Asserted with the scanner's own function, over every shape in this file, so
    that "the redactor stops what the scan would have found" is a measurement
    rather than a claim. The fixtures are checked to be findings BEFORE
    redaction as well: a shape the scanner does not flag in the first place
    would make the assertion vacuous, which is how a pin like this rots.
    """

    SHAPES = (
        FAKE_HOME + "\\notes.txt",
        f"C:/{WIN_ROOT}/{FAKE}/notes.txt",
        f"/c/{WIN_ROOT}/{FAKE}/.claude/hooks",
        f"C:\\{WIN_ROOT}\\{FAKE_SHORT}\\x",
        f"../../{WIN_ROOT}/{FAKE}/x",
        f'git status --porcelain > "C:\\{WIN_ROOT}\\{FAKE_CUT}',
        f"C:\\{WIN_ROOT}\\{OTHER}\\x",
        f"/c/{WIN_ROOT}/{OTHER}/x",
        f"/{NIX_ROOT}/{OTHER}/x",
        f"/{WIN_ROOT}/{OTHER}/x",
        f"C:\\{WIN_ROOT}\\{FAKE_SPACED}\\notes.txt",
        '{"p": "C:\\\\' + WIN_ROOT + "\\\\" + OTHER + '\\\\x"}',
        f"D:/Data/{WIN_ROOT}/{FAKE}/x",
        f"../elsewhere/{WIN_ROOT}/{FAKE}/x",
        f"grep -rn thing /mnt/backup/{NIX_ROOT}/{OTHER}/src",
    )

    def test_every_shape_here_is_a_finding_before_redaction(self) -> None:
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                self.assertNotEqual(leak_findings(shape), [], "fixture proves nothing")

    def test_and_none_of_them_is_a_finding_after_redaction(self) -> None:
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                self.assertEqual(leak_findings(keel_redact.redact(shape)), [])

    def test_redacting_twice_changes_nothing(self) -> None:
        """The chokepoint re-screens lines a caller may already have screened,
        so the fixed point has to be reached on the first pass."""
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                once = keel_redact.redact(shape)
                self.assertEqual(keel_redact.redact(once), once)
                self.assertIs(keel_redact.redact(once), once)


def armed_project(root: Path) -> Path:
    """A project keel enforces in: tier 2, and no plan on file for any session."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    return project


class TestTheGatesRelativisedTargetReachesTheLogSafely(unittest.TestCase):
    """The finding end to end, on the bytes in the file.

    ``hooks/keel_gate.py``'s freshness deny records
    ``relativise(event.cwd, targets[0][0])``, and ``relativise`` runs BEFORE
    the write-time chokepoint - so the value that reaches
    ``keel_events._append_jsonl`` is already relativised, already stripped of
    the literal home prefix, and still carrying an account name. That the
    chokepoint sees it AFTER the reshaping, and screens it anyway, is the thing
    this fix depends on, so it is verified here rather than assumed: the gate is
    driven through ``run``, and the audit log is read back off disk.

    Nothing is monkeypatched. The register, the redactor and the writer are the
    shipped ones; only the project and the target are invented.
    """

    def test_a_write_outside_the_project_logs_no_account_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            outside = str(Path(tmp) / WIN_ROOT / FAKE / "x.py")
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=uuid.uuid4().hex,
                tool_name="Write",
                file_paths=(outside,),
            )
            verdict = keel_gate.run(event, {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(
                verdict.detail["target"],
                f"../{WIN_ROOT}/{FAKE}/x.py",
                "the verdict itself is unscreened - the screen is at the write, not here",
            )
            raw = keel_events.audit_path(project).read_bytes()
            self.assertNotIn(FAKE.encode("utf-8"), raw)
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            self.assertEqual(line["event"], "gate_block")
            self.assertEqual(line["detail"]["target"], f"../{MARK}/x.py")
            self.assertEqual(leak_findings(raw.decode("utf-8")), [])

    def test_the_same_line_before_the_screen_would_have_been_a_finding(self) -> None:
        """Pin the leak itself, not only its absence: the value the gate hands
        the chokepoint IS what the scanner reports, so the assertion above is
        about the screen rather than about a shape that was never dangerous."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            outside = str(Path(tmp) / WIN_ROOT / FAKE / "x.py")
            self.assertNotEqual(leak_findings(keel_gate.relativise(project, outside)), [])


class TestCapturedCommandTextReachesBothRecordsSafely(unittest.TestCase):
    """THE WRITER THE REAL LEAK CAME THROUGH, driven end to end on file bytes.

    ``hooks/keel_capture.py`` is the one writer that puts RAW, UNCONSTRAINED
    text into a git-tracked file: ``action_detail`` and ``observation_action``
    hand ``redact`` the head of whatever a shell tool call contained, and
    ``run`` appends the result to the audit log AND to the observation queue.
    Nothing keel built shaped that text, so no argument about what keel's own
    path handling produces says anything about it - which is how a nested home
    root reached this repository's two tracked records on 2026-08-10, in a
    session that only ever RAN ``ls`` and ``grep``.

    Every other test of this module drives ``keel_redact`` directly or
    ``keel_gate.run``. That gap was half of the review finding this class
    answers, so this drives ``keel_capture.run`` itself and reads the BYTES of
    both files, because a redactor test cannot see a value that never reached
    the redactor, and an assertion about a return value cannot see what was
    serialised.

    Nothing is monkeypatched: the redactor, the chokepoint and both writers are
    the shipped ones. Only the project is invented, and the account names are
    the invented ones at the top of this file - a test for a leak may not be the
    leak.
    """

    #: Commands a session really does run, each naming a home directory nested
    #: below something, in the two separator spellings. The account is not this
    #: machine's, so nothing can resolve it from the environment.
    COMMANDS = (
        f"ls -la D:\\mirror\\c\\{WIN_ROOT}\\{OTHER}\\Documents",
        f"grep -rn thing /mnt/backup/{NIX_ROOT}/{OTHER}/src",
        f"cat ../elsewhere/{WIN_ROOT}/{FAKE}/notes.txt",
    )

    def _run_capture(self, project: Path, command: str) -> None:
        """One Bash PostToolUse event through the real entry point."""
        event = keel_events.KeelEvent(
            kind="post_tool",
            cwd=project,
            session_id=uuid.uuid4().hex,
            tool_name="Bash",
            command=command,
            raw={"hook_event_name": "PostToolUse", "tool_input": {"command": command}},
        )
        self.assertEqual(keel_capture.run(event), 0, "capture is fail-open and returns 0")

    def test_no_account_name_reaches_the_audit_log_or_the_queue(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as tmp:
                project = Path(tmp) / "project"
                (project / ".keel").mkdir(parents=True)
                self._run_capture(project, command)
                for path in (keel_events.audit_path(project), keel_events.queue_path(project)):
                    raw = path.read_bytes()
                    self.assertNotIn(FAKE.encode("utf-8"), raw, f"{path.name} carries a name")
                    self.assertNotIn(OTHER.encode("utf-8"), raw, f"{path.name} carries a name")
                    text = raw.decode("utf-8")
                    self.assertIn(MARK, text, f"{path.name} recorded nothing about the path")
                    self.assertEqual(leak_findings(text), [])
                    json.loads(text.splitlines()[-1])

    def test_the_command_that_was_captured_really_did_carry_the_name(self) -> None:
        """The other half of the pin. Without this the test above could pass on
        a fixture that never held an account name in the first place, which is
        how an assertion about absence rots into an assertion about nothing."""
        for command in self.COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(
                    OTHER in command or FAKE in command, "fixture proves nothing"
                )
                self.assertLess(
                    len(command),
                    keel_capture.COMMAND_DETAIL_CHARS,
                    "and it is short enough that the audit line is not truncated first",
                )

    def test_the_exact_bytes_of_both_records_for_one_command(self) -> None:
        """Not only "the name is gone" but what is there instead, so a screen
        that started writing empty details would fail rather than pass."""
        command = f"ls -la D:\\mirror\\c\\{WIN_ROOT}\\{OTHER}\\Documents"
        expected = f"ls -la D:\\mirror\\c\\{MARK}\\Documents"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel").mkdir(parents=True)
            self._run_capture(project, command)
            audit = json.loads(
                keel_events.audit_path(project).read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertEqual(audit["event"], "activity")
            self.assertEqual(audit["detail"], expected)
            queued = json.loads(
                keel_events.queue_path(project).read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertEqual(queued["action"], f"ran {expected}")

    def test_an_ordinary_command_is_recorded_word_for_word(self) -> None:
        """The screen may not pay for itself by mangling everything: a command
        with no home root in it reaches both records exactly as it was run."""
        command = "git status --porcelain && python -m unittest discover -s tests"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel").mkdir(parents=True)
            self._run_capture(project, command)
            audit = json.loads(
                keel_events.audit_path(project).read_text(encoding="utf-8").splitlines()[-1]
            )
            self.assertEqual(audit["detail"], command[: keel_capture.COMMAND_DETAIL_CHARS])


class TestAHomeShapedUnlikeUsersOrHome(unittest.TestCase):
    """The backstop sees a home that is not under ``Users`` or ``home``.

    The gap, measured 2026-09-01 in a ``python:3.10-slim`` container running
    as root: the screen recognised a home ROOT only as ``Users`` or ``home``,
    so ``/root2/x`` - still somebody's home-shaped path - was emitted byte for
    byte with the account name in it, and
    ``test_a_longer_sibling_name_is_not_swallowed`` in
    ``tests/test_keel_wave2.py`` failed for every adopter running the suite
    under ``docker run``, which runs as root by default.

    Both directions, per class: a home shaped otherwise is now screened, AND
    the ordinary Windows or Linux machine derives nothing and behaves exactly
    as it did before. The second half is the one that keeps this fix from
    costing anything where the gap never existed, so it is asserted rather
    than argued.
    """

    #: A home directly under the filesystem root - the Docker default, and the
    #: shape with no root segment for the original rule to anchor on.
    ROOT_HOME = "/root"

    #: A home whose parent is a named directory - the service-account shape a
    #: CI runner actually uses. Assembled so no literal home root appears.
    SERVICE_HOME = "/var/lib/svc"

    def _install(self, home: str) -> None:
        """Both patterns rebuilt from ``home``, restored by ``addCleanup``."""
        original_pattern = keel_redact._PATTERN
        original_shape = keel_redact._HOME_SHAPE_RE

        def restore() -> None:
            keel_redact._PATTERN = original_pattern
            keel_redact._HOME_SHAPE_RE = original_shape

        self.addCleanup(restore)
        env = {"USERPROFILE": home, "HOME": home}
        keel_redact._PATTERN = keel_redact.build_pattern(env)
        keel_redact._HOME_SHAPE_RE = keel_redact.build_home_shape_pattern(env)

    def test_a_sibling_of_a_root_home_does_not_keep_the_account_name(self) -> None:
        """``/root2/x`` loses ``root``; this is the container failure itself."""
        self._install(self.ROOT_HOME)
        redacted = keel_redact.redact("/root2/x")
        self.assertNotIn("root", redacted, redacted)
        self.assertIn(MARK, redacted)
        self.assertTrue(redacted.endswith("/x"), f"the tail was lost: {redacted}")

    def test_a_root_home_itself_still_collapses_to_a_tilde(self) -> None:
        """The primary pattern still wins on the home itself - ``~`` beats a mark.

        The marker would be a loss of information here, and branch 2 requires
        at least one character after the basename precisely so that it cannot
        overwrite this better answer.
        """
        self._install(self.ROOT_HOME)
        self.assertEqual(keel_redact.redact("/root/x"), "~/x")

    def test_a_service_home_screens_a_sibling_sharing_its_name_and_keeps_the_tail(
        self,
    ) -> None:
        """``/var/lib/<svc>2/x`` loses the account name and keeps ``x``.

        The same shape as the ``/root2`` case one class up, at a depth branch 1
        cannot anchor on, which is the point: the rule is the home's own
        basename and not its position in the tree.
        """
        self._install(self.SERVICE_HOME)
        redacted = keel_redact.redact("/var/lib/svc2/x")
        self.assertNotIn("svc", redacted, redacted)
        self.assertEqual(redacted, f"/var/lib/{MARK}/x")

    def test_a_service_homes_unrelated_neighbour_is_the_recorded_residue(self) -> None:
        """``/var/lib/<other>/x`` is NOT screened, and that is the honest half.

        The first shape of this fix DID screen it, by adding the home's parent
        (``lib``) as a new home root - and that was measured and rejected: it
        reads every ``lib`` segment anywhere as a homes directory, so it
        screened ``/usr/lib/<package>`` too, and it turned the PROJECT's own
        name into a marker in an audit line's ``cwd`` field in
        ``tests/test_keel_compaction_t228.py``'s sandbox, where the fixture
        home and the fixture project are siblings. A directory that merely
        contains a home is not a homes directory. Pinned so the residue is a
        measured property rather than a sentence in a docstring; if a later
        change closes it, this test is the one to rewrite deliberately.
        """
        self._install(self.SERVICE_HOME)
        self.assertEqual(keel_redact.redact("/var/lib/other/x"), "/var/lib/other/x")
        self.assertEqual(keel_redact.redact("/usr/lib/pkg/x"), "/usr/lib/pkg/x")

    def test_a_service_home_itself_still_collapses_to_a_tilde(self) -> None:
        self._install(self.SERVICE_HOME)
        self.assertEqual(keel_redact.redact("/var/lib/svc/x"), "~/x")

    def test_the_word_root_in_prose_is_untouched(self) -> None:
        """No separator after it, so there is no path and nothing to screen.

        ``_HOME_SHAPE_ROOT_START``'s complement rule is what makes this hold,
        and branch 2 obeys it rather than reopening it.
        """
        self._install(self.ROOT_HOME)
        for prose in ("the root of the tree", "root cause", "chroot2 jail"):
            with self.subTest(prose=prose):
                self.assertEqual(keel_redact.redact(prose), prose)

    def _contribution(self, home: str) -> set[str]:
        """What ``home`` adds to the derivation, over what this machine adds.

        MEASURED AS A DIFFERENCE, not as an absolute, and the reason is a real
        failure rather than caution: ``home_shape_siblings`` reads
        ``os.path.expanduser("~")`` from the LIVE process as well as the env it
        is handed - deliberately, because in production it must see every
        spelling of the real home. So on a machine whose own home is shaped
        unusually the result carries that machine's contribution too, and an
        equality assertion here passed on Windows and FAILED in a
        ``python:3.10-slim`` container running as root, where the live home is
        ``/root`` and contributes ``root`` whatever env is passed in. The claim
        these tests actually make is about the CONTRIBUTION of a given home,
        so that is what is measured; it holds on every platform.
        """
        base = set(keel_redact.home_shape_siblings({}))
        derived = set(
            keel_redact.home_shape_siblings({"USERPROFILE": home, "HOME": home})
        )
        return derived - base

    def test_an_ordinary_home_derives_nothing_at_all(self) -> None:
        """The common machines add nothing, so their screen cannot have moved.

        Asserted on the DERIVATION rather than on a redaction, because "adds
        nothing" is the claim that makes every other test in this file still
        valid on an ordinary machine: no second branch is built, so the pattern
        is the one that shipped before this fix.
        """
        for home in (
            f"/{NIX_ROOT}/{FAKE}",
            f"C:\\{WIN_ROOT}\\{FAKE}",
            f"C:/{WIN_ROOT}/{FAKE}",
        ):
            with self.subTest(home=home):
                self.assertEqual(self._contribution(home), set())

    def test_a_home_outside_a_known_root_derives_its_own_basename(self) -> None:
        """Both unusual shapes yield the home's BASENAME - not its parent.

        CONTAINMENT rather than the difference used above, and for the mirror
        of the same reason: on a machine whose own home is ``/root`` - the
        container this fix was found in - ``root`` is already in the baseline,
        so its contribution is empty while the claim "the derivation knows
        about it" is still exactly true. A positive claim asks what the result
        CONTAINS; only the negative claim needs the difference.

        That it is the basename and NOT the parent is the whole correction
        this design carries: ``lib`` must never appear here, or every
        ``/usr/lib/...`` in the record would be screened. Asserted, not
        assumed.
        """
        service = keel_redact.home_shape_siblings(
            {"USERPROFILE": self.SERVICE_HOME, "HOME": self.SERVICE_HOME}
        )
        self.assertIn("svc", service)
        self.assertNotIn("lib", service)
        self.assertIn(
            "root",
            keel_redact.home_shape_siblings(
                {"USERPROFILE": self.ROOT_HOME, "HOME": self.ROOT_HOME}
            ),
        )

    def test_a_sibling_not_sharing_the_basename_is_the_recorded_residue(self) -> None:
        """``/alice`` beside ``/root`` is NOT seen, and that is documented.

        Pinned so the residue is a measured property rather than a sentence in
        a docstring: nothing in ``/alice/x`` says it is a home, and a rule that
        treated every top-level directory as one would screen ``/usr`` and
        ``/tmp``. If a later change closes this, this test is the one that
        should be rewritten deliberately.
        """
        self._install(self.ROOT_HOME)
        self.assertEqual(keel_redact.redact("/alice/x"), "/alice/x")

    def test_text_with_no_home_shape_is_still_the_same_object(self) -> None:
        """The byte-identity guarantee survives the second branch."""
        self._install(self.ROOT_HOME)
        value = "git status --porcelain"
        self.assertIs(keel_redact.screen_home_shapes(value), value)


if __name__ == "__main__":
    unittest.main()
