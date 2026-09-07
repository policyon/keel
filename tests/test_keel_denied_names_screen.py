#!/usr/bin/env python3
"""Denied-names write-time screen - ``hooks/keel_redact.py``'s third transform.

Also covers two fixes made while closing T8's reopened findings: the walk
``redact_value``/``redact_mapping`` now does into a nested dict or list (the
shape an audit line's own ``detail`` field carries), the byte-identical
result of screening an already-screened value a second time (the property
the write-time chokepoint in ``keel_events.py`` depends on), and
``redact_path``'s explicit home-membership test, replacing the
``redact(value) != value`` proxy that the denied-names screen itself made
unsound.

Contract
--------
Reads   : nothing on disk of its own. Every register these tests exercise is
          written by the test itself, to a temporary file, and holds only the
          SHA-256 digest of an ordinary word chosen here ("pineapple",
          "orchard") - never a name this repository's real register forbids.
          One test reads the real ``scripts/keel-denied-names.json`` only to
          confirm it loads at all, and never inspects its contents.
Emits   : unittest results only.
Writes  : nothing outside a temporary directory it creates and removes.

Why a separate file rather than adding to ``tests/test_keel_wave2.py``
------------------------------------------------------------------------
This suite monkeypatches ``keel_redact._DENIED_HASHES`` and
``keel_redact._WARNED`` for the width of one test at a time (restored in
``tearDown``, even on failure), which no other suite needs to do. Keeping
that pattern in its own file means a reader of ``TestRedact`` in wave 2 never
has to wonder whether module-global state survives past a test there.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its
encoding. No plaintext denied name appears anywhere in this file, in a
comment, in a string literal or in a fixture - see the module docstring
above for why that is load-bearing here, not stylistic.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_redact  # noqa: E402  (path must be set first)


def _digest(token: str) -> str:
    """The register's own algorithm: sha256(lowercased token, utf-8)."""
    return hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()


def _write_register(directory: Path, *tokens: str) -> Path:
    """A register file naming only the ordinary ``tokens`` given, hashed."""
    path = directory / "register.json"
    path.write_text(json.dumps({"hashes": [_digest(t) for t in tokens]}), encoding="utf-8")
    return path


class _RestoresModuleState(unittest.TestCase):
    """Snapshot and restore ``keel_redact``'s two mutable globals.

    Every test in this file that swaps in a fake register or clears the
    warned-set restores both here, so no other test - in this file, in
    ``test_keel_wave2.py``, or anywhere else in the same discovery run -
    observes a fake register or a cleared warning flag left behind by one
    that ran earlier.
    """

    def setUp(self) -> None:
        self._original_hashes = keel_redact._DENIED_HASHES
        self._original_warned = set(keel_redact._WARNED)

    def tearDown(self) -> None:
        keel_redact._DENIED_HASHES = self._original_hashes
        keel_redact._WARNED.clear()
        keel_redact._WARNED.update(self._original_warned)


class TestScreenSubstitutesRegisteredNames(_RestoresModuleState):
    """The positive direction: a registered name is replaced before write."""

    def test_a_single_registered_word_is_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            result = keel_redact.redact("the pineapple report is due")
            self.assertEqual(result, f"the {keel_redact.DENIED_NAME_TOKEN} report is due")
            self.assertNotIn("pineapple", result)

    def test_matching_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            result = keel_redact.redact("PineApple was mentioned")
            self.assertNotIn("pineapple", result.casefold())
            self.assertIn(keel_redact.DENIED_NAME_TOKEN, result)

    def test_a_two_word_registered_phrase_is_substituted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple orchard")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            result = keel_redact.redact("visit the pineapple orchard today")
            expected = (
                f"visit the {keel_redact.DENIED_NAME_TOKEN} "
                f"{keel_redact.DENIED_NAME_TOKEN} today"
            )
            self.assertEqual(result, expected)

    def test_a_two_word_phrase_is_not_caught_across_a_line_break(self) -> None:
        """check_vendor_names pairs words within one line only; this matches it."""
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple orchard")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "pineapple\norchard"
            result = keel_redact.redact(value)
            self.assertEqual(result, value)

    def test_substitution_keeps_a_record_line_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            record = {"tool": "Bash", "detail": "grep -rn pineapple file.txt"}
            redacted = keel_redact.redact_mapping(record)
            line = json.dumps(redacted)
            reparsed = json.loads(line)  # raises if substitution broke JSON validity
            self.assertNotIn("pineapple", line)
            self.assertIn(keel_redact.DENIED_NAME_TOKEN, reparsed["detail"])

    def test_a_name_inside_a_private_block_never_reaches_the_screen(self) -> None:
        """strip_private runs first, so the screen never even sees it (R10)."""
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "before <keel-private>pineapple secret</keel-private> after"
            result = keel_redact.redact(value)
            self.assertNotIn("pineapple", result)
            self.assertNotIn(keel_redact.DENIED_NAME_TOKEN, result)


class TestScreenLeavesOrdinaryTextByteIdentical(_RestoresModuleState):
    """The negative direction, pinned harder than the positive one."""

    def test_a_value_with_no_registered_name_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "an ordinary sentence about apples and oranges, nothing more"
            self.assertEqual(keel_redact.screen_denied_names(value), value)
            self.assertIs(keel_redact.screen_denied_names(value), value)

    def test_redact_of_ordinary_text_is_unchanged_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "2026-08-10T12:00:00Z ordinary log text with punctuation: ok."
            self.assertEqual(keel_redact.redact(value), value)

    def test_a_near_miss_sibling_word_is_not_swallowed(self) -> None:
        """'pineapples' must not be caught by a rule for 'pineapple'."""
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "pineapples are a fruit"
            self.assertEqual(keel_redact.redact(value), value)

    def test_a_hyphen_glued_word_is_one_token_to_the_screen_and_to_the_scan(self) -> None:
        """Parity with ``check_vendor_names``, pinned so nobody "improves" it.

        Its tokeniser is ``[a-z0-9][a-z0-9-]*``, so a hyphen is INTERNAL to a
        token: ``<word>-9f2c`` is one candidate and hashes to something the
        register does not hold. The screen must agree, or the two disagree
        about what a name is - and the direction of that disagreement matters,
        because the alternative (substring matching) would rewrite every
        ordinary word that merely contains a registered one and corrupt the
        records this screen exists to protect. A name glued to other
        characters with a hyphen is out of scope for BOTH, which is a property
        of the rule rather than a hole in this implementation of it.
        """
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            value = "session pineapple-9f2c started"
            self.assertEqual(keel_redact.redact(value), value)
            words = re.findall(r"[a-z0-9][a-z0-9-]*", value.lower())
            self.assertIn("pineapple-9f2c", words, "the scan tokenises it the same way")
            self.assertNotIn("pineapple", words)


class TestAbsentOrMalformedRegisterFailsOpen(_RestoresModuleState):
    """Convention 7: degraded, never silent; never a crashed hook."""

    def test_an_absent_register_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / f"does-not-exist-{uuid.uuid4().hex}.json"
            self.assertIsNone(keel_redact.load_denied_hashes(missing))

    def test_invalid_json_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "register.json"
            broken.write_text("{not valid json", encoding="utf-8")
            self.assertIsNone(keel_redact.load_denied_hashes(broken))

    def test_a_document_missing_the_hashes_key_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wrong_shape = Path(tmp) / "register.json"
            wrong_shape.write_text(json.dumps({"other": []}), encoding="utf-8")
            self.assertIsNone(keel_redact.load_denied_hashes(wrong_shape))

    def test_hashes_of_the_wrong_type_resolves_to_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wrong_type = Path(tmp) / "register.json"
            wrong_type.write_text(json.dumps({"hashes": "not-a-list"}), encoding="utf-8")
            self.assertIsNone(keel_redact.load_denied_hashes(wrong_type))
            wrong_entries = Path(tmp) / "register2.json"
            wrong_entries.write_text(json.dumps({"hashes": [1, 2, 3]}), encoding="utf-8")
            self.assertIsNone(keel_redact.load_denied_hashes(wrong_entries))

    def test_a_missing_register_never_crashes_redact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / f"does-not-exist-{uuid.uuid4().hex}.json"
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(missing)
            self.assertEqual(keel_redact.redact("nothing forbidden here"), "nothing forbidden here")

    def test_an_unreadable_register_prints_exactly_one_stderr_line(self) -> None:
        keel_redact._WARNED.clear()
        with tempfile.TemporaryDirectory() as tmp:
            missing_a = Path(tmp) / "a-does-not-exist.json"
            missing_b = Path(tmp) / "b-does-not-exist.json"
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                keel_redact.load_denied_hashes(missing_a)
                keel_redact.load_denied_hashes(missing_b)
            printed = buffer.getvalue()
            self.assertEqual(printed.count(keel_redact.DENIED_NAMES_UNREADABLE_WARNING), 1)

    def test_the_home_warning_does_not_silence_the_denied_names_one(self) -> None:
        """``_WARNED`` is a SET, and this is the test that says why.

        As a single boolean - which is what it was before the screen existed -
        the first degradation to speak would have silenced every later one:
        a machine where no home directory resolves prints its line, and the
        denied-names register could then go unreadable for the rest of the
        process without a word said about it. Two independent guarantees need
        two independent one-time lines, so the pre-seeded home message must
        not suppress this one.
        """
        keel_redact._WARNED.clear()
        keel_redact._WARNED.add("redaction is inactive: no home directory could be resolved")
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / f"does-not-exist-{uuid.uuid4().hex}.json"
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                keel_redact.load_denied_hashes(missing)
            self.assertEqual(
                buffer.getvalue().count(keel_redact.DENIED_NAMES_UNREADABLE_WARNING),
                1,
                "the home-directory warning silenced the denied-names warning",
            )

    def test_the_real_register_loads_without_a_warning(self) -> None:
        """Sanity check on the actual installation, contents never inspected."""
        self.assertIsNotNone(keel_redact._DENIED_HASHES)
        self.assertGreater(len(keel_redact._DENIED_HASHES), 0)


class TestPriorTransformationsUnchanged(_RestoresModuleState):
    """strip_private and the home-directory rewrite behave exactly as before."""

    def test_home_prefix_still_becomes_a_tilde(self) -> None:
        home = str(Path.home())
        value = str(Path(home) / "notes.txt")
        redacted = keel_redact.redact(value)
        self.assertTrue(redacted.startswith("~"), redacted)

    def test_private_block_is_still_dropped(self) -> None:
        value = "keep <keel-private>drop this</keel-private> keep"
        result = keel_redact.redact(value)
        self.assertNotIn("drop this", result)

    def test_non_strings_still_pass_through_unchanged(self) -> None:
        for value in (None, 17, {"a": 1}, ["b"]):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.redact(value), value)

    def test_declares_fail_open_still(self) -> None:
        self.assertIn("FAIL-OPEN", keel_redact.__doc__ or "")


def _isolated_home_pattern(home: str) -> re.Pattern[str]:
    """A ``_PATTERN``-shaped regex for exactly one home spelling.

    Built the same way ``keel_redact.build_pattern`` builds one, but from a
    single string handed in directly - never through ``home_candidates``,
    which always adds THIS machine's real home directory as a fallback
    (``os.path.expanduser("~")``, read straight from the live process
    environment, never from any override passed to it). On this machine, as
    on many, the OS's own temp directory sits UNDER that real home, so a
    pattern built the normal way would match every temporary directory these
    tests create - exactly what the "outside home" tests below need to NOT
    happen.
    """
    escaped = "".join(r"[\\/]" if char in "\\/" else re.escape(char) for char in home)
    return re.compile("(?:" + escaped + ")" + keel_redact._BOUNDARY, re.IGNORECASE)


class TestRedactValueWalksNestedStructures(_RestoresModuleState):
    """The chokepoint hands whole audit/queue lines to this walk - a real
    line's ``detail`` is a dict, and a queue line's ``paths`` is a list, so
    a one-level-deep walk would leave both unscreened."""

    def test_a_nested_mapping_is_screened_at_every_depth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            entry = {
                "event": "gate_block",
                "gate": "policy_lock",
                "detail": {"target": "src/pineapple/file.py", "switch": "KEEL_OVERRIDE"},
            }
            redacted = keel_redact.redact_mapping(entry)
            line = json.dumps(redacted)
            self.assertNotIn("pineapple", line)
            self.assertEqual(
                redacted["detail"]["target"],
                f"src/{keel_redact.DENIED_NAME_TOKEN}/file.py",
            )
            self.assertEqual(redacted["detail"]["switch"], "KEEL_OVERRIDE")

    def test_a_list_of_strings_is_screened_item_by_item(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            entry = {"paths": ["src/pineapple/a.py", "src/other/b.py"]}
            redacted = keel_redact.redact_mapping(entry)
            self.assertEqual(
                redacted["paths"],
                [f"src/{keel_redact.DENIED_NAME_TOKEN}/a.py", "src/other/b.py"],
            )

    def test_a_flat_record_behaves_exactly_as_before(self) -> None:
        """The pre-existing one-level contract is a special case of the walk,
        not a behaviour this loses."""
        record = keel_redact.redact_mapping({"a": 1, "b": "ordinary text"})
        self.assertEqual(record, {"a": 1, "b": "ordinary text"})


class TestDoubleScreeningIsANoOp(_RestoresModuleState):
    """The chokepoint runs after callers that may already have redacted
    (``keel_capture.py``, ``keel_session.py``); this is the proof that doing
    so twice reproduces the same bytes rather than mangling them further."""

    def test_redacting_a_denied_name_twice_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            once = keel_redact.redact("the pineapple report is due")
            twice = keel_redact.redact(once)
            self.assertEqual(once, twice)
            self.assertIn(keel_redact.DENIED_NAME_TOKEN, once)

    def test_redacting_a_home_path_twice_is_byte_identical(self) -> None:
        home = str(Path.home())
        value = str(Path(home) / "notes.txt")
        once = keel_redact.redact(value)
        twice = keel_redact.redact(once)
        self.assertEqual(once, twice)

    def test_redact_mapping_of_an_already_redacted_entry_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            entry = {"detail": {"target": "src/pineapple/file.py"}}
            once = keel_redact.redact_mapping(entry)
            twice = keel_redact.redact_mapping(once)
            self.assertEqual(once, twice)
            self.assertEqual(json.dumps(once), json.dumps(twice))


class TestRedactPathHomeMembershipIsExplicit(_RestoresModuleState):
    """Finding 3: ``redact(value) != value`` stopped meaning "under home" the
    moment step 3 of ``redact`` could fire on its own for any denied name,
    anywhere. ``redact_path`` now asks ``_under_home`` instead."""

    def setUp(self) -> None:
        super().setUp()
        self._original_pattern = keel_redact._PATTERN

    def tearDown(self) -> None:
        keel_redact._PATTERN = self._original_pattern
        super().tearDown()

    def test_a_path_outside_project_and_home_keeps_the_short_form(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as tmp:
            keel_redact._PATTERN = _isolated_home_pattern(home_tmp)
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            project = Path(tmp) / "project"
            outside_root = Path(tmp) / "elsewhere"
            outside = str(outside_root / "pineapple" / "notes.txt")
            result = keel_redact.redact_path(project, outside)
            self.assertFalse(os.path.isabs(result), result)
            self.assertNotIn(str(tmp).casefold(), result.casefold())
            self.assertNotIn("pineapple", result.casefold())
            self.assertIn(keel_redact.DENIED_NAME_TOKEN, result)

    def test_a_path_actually_under_the_fake_home_still_gets_the_tilde_form(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as tmp:
            keel_redact._PATTERN = _isolated_home_pattern(home_tmp)
            project = Path(tmp) / "project"
            value = str(Path(home_tmp) / "notes.txt")
            result = keel_redact.redact_path(project, value)
            self.assertTrue(result.startswith("~/"), result)

    def test_the_old_proxy_would_have_misfired_on_this_exact_case(self) -> None:
        """Pin the failure mode itself: a denied name outside both project
        and home makes ``redact(value) != value`` true even though ``value``
        was never under home, which is exactly what fooled the old proxy."""
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as tmp:
            keel_redact._PATTERN = _isolated_home_pattern(home_tmp)
            register = _write_register(Path(tmp), "pineapple")
            keel_redact._DENIED_HASHES = keel_redact.load_denied_hashes(register)
            outside_root = Path(tmp) / "elsewhere"
            outside = str(outside_root / "pineapple" / "notes.txt")
            self.assertNotEqual(keel_redact.redact(outside), outside)
            self.assertFalse(keel_redact._under_home(outside))


if __name__ == "__main__":
    unittest.main()
