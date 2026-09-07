#!/usr/bin/env python3
"""T129 - a review verdict is an event, and the page can already read it.

Why this file is not ``tests/test_keel_review.py``
--------------------------------------------------
That name was taken before this task existed, by the Phase 3 suite that
proves routing rule 3's ESCALATION CYCLE (a ``[~]`` attempt, a deep retry, a
terminal ``[!]``) through the stop gate and ``keel attest``. The two share a
word and nothing else: that suite is about how a review VERDICT MOVES WORK,
this one is about how a verdict is WRITTEN DOWN. Naming this file after the
subcommand it exercises keeps both, which the additive-merge law requires and
which a reader looking for either is better served by.

What is proven here, and where each claim is read from
-----------------------------------------------------
1. THE RECORD. ``keel review`` appends exactly one line, with exactly the
   fixed key set ``{v, ts, event, session, task, verdict, notes}`` and the
   values the caller supplied - asserted on the BYTES read back off disk, not
   on a return value, because "the line was written screened and complete" is
   a fact about the file (the argument
   ``tests/test_keel_audit_chokepoint_screen.py`` makes at length).
2. THE VOCABULARY. ``pass`` and ``fail``, and nothing else. Both directions:
   a valid verdict appends, an invalid one is refused with exit 2 and the log
   is byte-identical afterwards.
3. THE PAGE. The vendored orchestration viewer's data layer
   (``scripts/keel_orchestration_dashboard.read_state``) serves keel's review
   line - with its ``session`` field, which the predecessor's own review lines
   never carried - beside a predecessor-shaped one, and both keep every field
   that page's renderers read (``event``, ``verdict``, ``task``, ``notes``,
   ``ts``). ZERO page edits: this file changes nothing in that program and
   only reads what it serves.

Every premise is the test's own
------------------------------
Each test builds its project in a temporary directory: its own ``.keel/``,
its own policy file, and its own audit log written line by line, so no test
here reads or writes this repository's real records, and none of them depends
on a session having happened. The one exception is deliberate and named where
it occurs: ``TestReachableFromTheCli`` imports the shipped CLI to assert
registration, and writes nothing at all.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_attest  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402  (path must be set first)
import keel_review  # noqa: E402

#: The harness's own claim, captured at IMPORT TIME - before any fixture in
#: this file (``setUpModule`` below, or any test's own patch) can override
#: it - so ``TestTheHarnessVariableIsPinned`` asserts on what the REAL
#: harness actually exported, never on a value this file wrote itself.
_MEASURED_SESSION_ENV = os.environ.get("CLAUDE_CODE_SESSION_ID")

#: The session this file's fixtures run in. Full-length and fixed, so an
#: assertion can name it exactly; the first 8 characters are what the command
#: echoes back.
SESSION = "abc12345-6789-0000-1111-222233334444"

#: A second one, for the test that pins ``--session`` beating the log.
OTHER_SESSION = "ffff9999-0000-1111-2222-333344445555"

#: Shares SESSION's first 8 characters on purpose - the ambiguous-prefix
#: fixture for the NAMED path's own refusal (T197 escalation retry:
#: keel:reviewer-silent-failure found ``pick_session`` picking silently
#: between two such ids rather than refusing).
AMBIGUOUS_SESSION = "abc12345-9999-8888-7777-666655554444"

#: The exact schema T129 fixes. Order matters as much as membership: ``v``
#: and ``ts`` are stamped by ``keel_events._append_jsonl`` before the record
#: is merged, so a review line reads like every other line in the log.
SCHEMA: tuple[str, ...] = ("v", "ts", "event", "session", "task", "verdict", "notes")


def project_with_log(root: Path, *lines: dict) -> Path:
    """An adopted project whose audit log holds exactly ``lines``.

    The log is written HERE rather than by keel, so the premise is the test's
    own: a session_start line exists because this function wrote one, not
    because something else happened to run first.
    """
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    audit = project / ".keel" / "audit" / "keel-audit.jsonl"
    audit.parent.mkdir(parents=True)
    with open(audit, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return project


def started(session: str = SESSION, ts: str = "2026-08-13T09:00:00Z") -> dict:
    """One ``session_start`` line, in keel's own shape."""
    return {"v": 1, "ts": ts, "event": "session_start", "session": session}


def audit_lines(project: Path) -> list[dict]:
    """Every line of the project's audit log, parsed, oldest first."""
    path = keel_events.audit_path(project)
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


#: Restored by ``tearDownModule``, whatever it was before this module ran.
_ORIGINAL_SESSION_ENV: str | None = None


def setUpModule() -> None:
    """T197: identity is read from ``CLAUDE_CODE_SESSION_ID``, never from the
    log. Every fixture in this file defaults to acting as ``SESSION`` so that
    the many tests NOT about session resolution itself (the record's schema,
    the vocabulary, the task id, redaction, the page) do not each have to say
    so; ``TestTheSession`` overrides or clears this per test where the
    resolution rule itself is what is under test."""
    global _ORIGINAL_SESSION_ENV
    _ORIGINAL_SESSION_ENV = os.environ.get(keel_attest.SESSION_ENV_VAR)
    os.environ[keel_attest.SESSION_ENV_VAR] = SESSION


def tearDownModule() -> None:
    if _ORIGINAL_SESSION_ENV is None:
        os.environ.pop(keel_attest.SESSION_ENV_VAR, None)
    else:
        os.environ[keel_attest.SESSION_ENV_VAR] = _ORIGINAL_SESSION_ENV


class TestTheRecord(unittest.TestCase):
    """A verdict lands as one line of the fixed shape."""

    def test_a_pass_appends_one_line_with_the_fixed_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            code = keel_review.main(
                ["--project", str(project), "--task", "T42", "--verdict", "pass",
                 "--notes", "criteria met"]
            )
            self.assertEqual(code, 0)
            lines = audit_lines(project)
            self.assertEqual(len(lines), 2, "exactly one line was added")
            entry = lines[-1]
            self.assertEqual(tuple(entry), SCHEMA)
            self.assertEqual(entry["v"], keel_events.AUDIT_SCHEMA_VERSION)
            self.assertTrue(entry["ts"].endswith("Z"), entry["ts"])
            self.assertEqual(entry["event"], "review")
            self.assertEqual(entry["session"], SESSION)
            self.assertEqual(entry["task"], "T42")
            self.assertEqual(entry["verdict"], "pass")
            self.assertEqual(entry["notes"], "criteria met")

    def test_a_fail_is_recorded_as_faithfully_as_a_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            self.assertEqual(
                keel_review.main(
                    ["--project", str(project), "--task", "T7", "--verdict", "fail",
                     "--notes", "the guard is bypassable"]
                ),
                0,
            )
            entry = audit_lines(project)[-1]
            self.assertEqual(entry["verdict"], "fail")
            self.assertEqual(entry["notes"], "the guard is bypassable")

    def test_notes_are_optional_and_absence_is_an_empty_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            self.assertEqual(
                keel_review.main(
                    ["--project", str(project), "--task", "T7", "--verdict", "pass"]
                ),
                0,
            )
            entry = audit_lines(project)[-1]
            self.assertEqual(tuple(entry), SCHEMA, "the key is present even when empty")
            self.assertEqual(entry["notes"], "")

    def test_a_long_note_is_capped_rather_than_writing_a_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            keel_review.main(
                ["--project", str(project), "--task", "T7", "--verdict", "fail",
                 "--notes", "x" * (keel_review.NOTES_CHARS + 500)]
            )
            self.assertEqual(
                len(audit_lines(project)[-1]["notes"]), keel_review.NOTES_CHARS
            )


class TestTheVocabulary(unittest.TestCase):
    """Two words, enforced at the CLI - both directions."""

    def test_the_vocabulary_is_exactly_pass_and_fail(self) -> None:
        self.assertEqual(keel_review.VERDICTS, ("pass", "fail"))

    def test_each_word_of_the_vocabulary_is_accepted(self) -> None:
        for verdict in keel_review.VERDICTS:
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as tmp:
                project = project_with_log(Path(tmp), started())
                self.assertEqual(
                    keel_review.main(
                        ["--project", str(project), "--task", "T1", "--verdict", verdict]
                    ),
                    0,
                )
                self.assertEqual(audit_lines(project)[-1]["verdict"], verdict)

    def test_an_unknown_verdict_is_refused_and_nothing_is_written(self) -> None:
        for word in ("partial", "passed", "PASS-ish", "", "ok"):
            with self.subTest(word=word), tempfile.TemporaryDirectory() as tmp:
                project = project_with_log(Path(tmp), started())
                before = keel_events.audit_path(project).read_bytes()
                code = keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", word]
                )
                self.assertEqual(code, 2)
                self.assertEqual(
                    keel_events.audit_path(project).read_bytes(),
                    before,
                    "a refused verdict wrote to the log",
                )

    def test_case_is_folded_to_the_canonical_spelling(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            self.assertEqual(
                keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", " PASS "]
                ),
                0,
            )
            self.assertEqual(audit_lines(project)[-1]["verdict"], "pass")


class TestTheTaskId(unittest.TestCase):
    """An id a reader turns into a pattern is a whitelist, not free text."""

    def test_an_id_carrying_syntax_is_refused_and_nothing_is_written(self) -> None:
        for bad in ("T1 (retry)", "T1|T2", "T1*", "../T1", "T1\nT2", ""):
            with self.subTest(task=bad), tempfile.TemporaryDirectory() as tmp:
                project = project_with_log(Path(tmp), started())
                before = keel_events.audit_path(project).read_bytes()
                self.assertEqual(
                    keel_review.main(
                        ["--project", str(project), "--task", bad, "--verdict", "pass"]
                    ),
                    2,
                )
                self.assertEqual(keel_events.audit_path(project).read_bytes(), before)

    def test_the_ids_this_project_actually_uses_are_accepted(self) -> None:
        for good in ("T129", "T129-verify", "T129.1", "t9"):
            with self.subTest(task=good), tempfile.TemporaryDirectory() as tmp:
                project = project_with_log(Path(tmp), started())
                self.assertEqual(
                    keel_review.main(
                        ["--project", str(project), "--task", good, "--verdict", "pass"]
                    ),
                    0,
                )
                self.assertEqual(audit_lines(project)[-1]["task"], good)


class TestTheSession(unittest.TestCase):
    """The verdict is attributed, never guessed. T197: identity is READ from
    ``CLAUDE_CODE_SESSION_ID`` in the environment, never inferred from the
    log - see
    ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``. Every
    test here controls the environment variable explicitly (rather than
    relying on this module's own ``setUpModule`` default) because the
    resolution rule itself is what is under test.

    DROPPED from this class: ``test_the_session_defaults_to_the_logs_latest_
    session_start``, which pinned exactly the inference this record deletes
    (T174's first specification). It is replaced below by
    ``test_the_session_defaults_to_claude_code_session_id``, which proves the
    log's ``session_start`` lines are no longer consulted at all for the
    default - not merely resolved differently.
    """

    def test_the_session_defaults_to_claude_code_session_id(self) -> None:
        """``OTHER_SESSION`` is the LATER ``session_start`` in the log; under
        any of the three deleted inference specifications it would have been
        chosen. The environment variable names ``SESSION`` instead, and
        ``SESSION`` is what gets written - the log's own contents are not
        part of this decision any more."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(SESSION, "2026-08-13T08:00:00Z"),
                started(OTHER_SESSION, "2026-08-13T09:00:00Z"),  # newer, NOT chosen
            )
            with mock.patch.dict(os.environ, {keel_attest.SESSION_ENV_VAR: SESSION}):
                code = keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", "pass"]
                )
            self.assertEqual(code, 0)
            self.assertEqual(audit_lines(project)[-1]["session"], SESSION)

    def test_an_explicit_session_wins_over_the_log(self) -> None:
        """This priority predates the ratified decision (T129); pinned here
        because this class is where session resolution as a whole is
        pinned, not because the decision changed this particular rule."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(OTHER_SESSION, "2026-08-13T08:00:00Z"),
                started(SESSION, "2026-08-13T09:00:00Z"),
            )
            with mock.patch.dict(os.environ, {keel_attest.SESSION_ENV_VAR: SESSION}):
                keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", "pass",
                     "--session", OTHER_SESSION[:8]]
                )
            self.assertEqual(audit_lines(project)[-1]["session"], OTHER_SESSION)

    def test_an_explicit_session_wins_over_the_environment(self) -> None:
        """``--session`` beats ``CLAUDE_CODE_SESSION_ID`` too - a NAMED
        session is never second-guessed, not even by the harness's own claim
        of who is acting. An explicit flag outranking the default predates
        this decision; only the default it now beats (the environment, not
        the log) is new."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started(OTHER_SESSION))
            with mock.patch.dict(os.environ, {keel_attest.SESSION_ENV_VAR: SESSION}):
                code = keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", "pass",
                     "--session", OTHER_SESSION[:8]]
                )
            self.assertEqual(code, 0)
            self.assertEqual(audit_lines(project)[-1]["session"], OTHER_SESSION)

    def test_a_full_session_id_still_resolves(self) -> None:
        """The ambiguity fix below must not tighten the ordinary path: a
        FULL id, not only a short prefix, still matches exactly one session
        and resolves exactly as before."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(OTHER_SESSION, "2026-08-13T08:00:00Z"),
                started(SESSION, "2026-08-13T09:00:00Z"),
            )
            code = keel_review.main(
                ["--project", str(project), "--task", "T1", "--verdict", "pass",
                 "--session", OTHER_SESSION]
            )
            self.assertEqual(code, 0)
            self.assertEqual(audit_lines(project)[-1]["session"], OTHER_SESSION)

    def test_an_ambiguous_prefix_is_refused_and_nothing_is_written(self) -> None:
        """T197 escalation retry: ``keel:reviewer-silent-failure`` found the
        NAMED path (``--session``) resolving an ambiguous prefix by silently
        returning whichever session the scan reached first, contradicting
        its own docstring's "this is not a guess" - the only remaining route
        to a wrong attribution once the unnamed default stopped inferring
        from the log. ``SESSION`` and ``AMBIGUOUS_SESSION`` share their first
        8 characters on purpose; the flag must refuse, naming how many
        sessions matched, rather than pick one."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(SESSION, "2026-08-13T08:00:00Z"),
                started(AMBIGUOUS_SESSION, "2026-08-13T09:00:00Z"),
            )
            before = keel_events.audit_path(project).read_bytes()
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                code = keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", "pass",
                     "--session", SESSION[:8]]
                )
            self.assertEqual(code, 2)
            self.assertEqual(keel_events.audit_path(project).read_bytes(), before)
            message = buf.getvalue()
            self.assertIn("--session", message)
            self.assertIn("2", message)

    def test_no_session_anywhere_is_refused_and_nothing_is_written(self) -> None:
        """Neither ``--session`` nor the environment answers: REFUSE rather
        than fall back to the log - the log here even carries a
        ``session_start``, and it is still not consulted (convention 7)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            before = keel_events.audit_path(project).read_bytes()
            with mock.patch.dict(os.environ):
                os.environ.pop(keel_attest.SESSION_ENV_VAR, None)
                code = keel_review.main(
                    ["--project", str(project), "--task", "T1", "--verdict", "pass"]
                )
            self.assertEqual(code, 2)
            self.assertEqual(keel_events.audit_path(project).read_bytes(), before)

    def test_the_refusal_names_both_routes(self) -> None:
        """Criterion 4: legible to a human who has never read the decision -
        the one line printed names both the flag and the variable."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp))  # no session_start either
            buf = io.StringIO()
            with mock.patch.dict(os.environ):
                os.environ.pop(keel_attest.SESSION_ENV_VAR, None)
                with contextlib.redirect_stderr(buf):
                    code = keel_review.main(
                        ["--project", str(project), "--task", "T1", "--verdict", "pass"]
                    )
            self.assertEqual(code, 2)
            message = buf.getvalue()
            self.assertIn("--session", message)
            self.assertIn(keel_attest.SESSION_ENV_VAR, message)

    def test_an_unadopted_project_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                keel_review.main(
                    ["--project", tmp, "--task", "T1", "--verdict", "pass"]
                ),
                2,
            )
            self.assertFalse((Path(tmp) / ".keel").exists(), "nothing was created")


class TestTheHarnessVariableIsPinned(unittest.TestCase):
    """T197 criterion 3: the harness's own session id is a DEPENDENCY that may
    change, not a keel convention - its name and its shape are pinned HERE so
    a harness change surfaces as a red test in this file rather than as a
    silent return to inferring identity from the log (see
    ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``).

    The NAME half is a keel-side constant and runs everywhere. The PRESENCE
    half can only be true where the harness is running, so it skips elsewhere
    rather than failing a CI runner or an adopter's clone (BL17)."""

    UUID_RE = re.compile(
        r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{12}\Z"
    )

    def test_the_variable_name_is_claude_code_session_id(self) -> None:
        self.assertEqual(keel_attest.SESSION_ENV_VAR, "CLAUDE_CODE_SESSION_ID")

    def test_the_variable_is_present_and_uuid_shaped_in_this_environment(self) -> None:
        """Asserts on ``_MEASURED_SESSION_ENV`` (captured at import time,
        above ``setUpModule``'s own override) rather than on a live
        ``os.environ`` read, so this reports on what the REAL harness
        actually exported when this suite was collected - never on a value
        this file wrote for its own fixtures."""
        if _MEASURED_SESSION_ENV is None:
            self.skipTest(
                f"{keel_attest.SESSION_ENV_VAR} was not exported when this suite "
                "was collected. This case pins a HARNESS dependency, so it can "
                "only run inside the harness — it skips in CI and in an "
                "adopter's terminal rather than failing them (BL17, ruled "
                "2026-09-01). The name half of this contract, tested above, "
                "still runs everywhere."
            )
        self.assertRegex(
            _MEASURED_SESSION_ENV,
            self.UUID_RE,
            f"not UUID-shaped: {_MEASURED_SESSION_ENV!r}",
        )


class TestTheRedactionChokepoint(unittest.TestCase):
    """``notes`` and ``task`` reach the log through the one screen."""

    def test_a_marked_private_region_never_reaches_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            keel_review.main(
                ["--project", str(project), "--task", "T1", "--verdict", "fail",
                 "--notes", "seen <keel-private>pineapple</keel-private> gone"]
            )
            notes = audit_lines(project)[-1]["notes"]
            self.assertNotIn("pineapple", notes)
            self.assertNotIn("keel-private", notes)
            self.assertIn("seen", notes)

    def test_truncation_cannot_leave_marked_content_behind(self) -> None:
        """The cap is applied AFTER the screen, so a region straddling the cut
        is dropped rather than sliced open by it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(Path(tmp), started())
            filler = "y" * (keel_review.NOTES_CHARS - 10)
            keel_review.main(
                ["--project", str(project), "--task", "T1", "--verdict", "fail",
                 "--notes", f"{filler}<keel-private>pineapple</keel-private>tail"]
            )
            self.assertNotIn("pineapple", audit_lines(project)[-1]["notes"])


class TestThePageStillReadsIt(unittest.TestCase):
    """Accept 2, mechanically: the vendored viewer's data layer serves both
    shapes of review line - keel's (with ``session``) and the predecessor's
    (without) - and keeps every field that page's renderers read. Nothing in
    that program is modified by this test; it is imported and read."""

    RENDERED = ("event", "ts", "task", "verdict", "notes")

    def _served(self, project: Path) -> list[dict]:
        import keel_orchestration_dashboard as page  # noqa: PLC0415 - path set above

        original = page.ROOT
        page.ROOT = str(project)
        try:
            return page.read_state()["events"]
        finally:
            page.ROOT = original

    def test_both_shapes_survive_the_data_layer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = project_with_log(
                Path(tmp),
                started(),
                # The predecessor's own shape: no ``session`` field at all.
                {"ts": "2026-08-13T09:30:00Z", "event": "review", "task": "T00",
                 "verdict": "pass", "notes": "the older shape"},
            )
            keel_review.main(
                ["--project", str(project), "--task", "T129", "--verdict", "pass",
                 "--notes", "keel's own shape"]
            )
            reviews = [e for e in self._served(project) if e.get("event") == "review"]
            self.assertEqual(len(reviews), 2)
            old, new = reviews
            for entry in (old, new):
                for key in self.RENDERED:
                    self.assertIn(key, entry)
            self.assertNotIn("session", old, "the predecessor's line is served unchanged")
            self.assertEqual(new["session"], SESSION)
            self.assertEqual(
                new["session_id"], SESSION, "the page reads session_id; the alias is added"
            )
            self.assertEqual(new["task"], "T129")
            self.assertEqual(new["verdict"], "pass")
            self.assertEqual(new["notes"], "keel's own shape")


class TestReachableFromTheCli(unittest.TestCase):
    """Registration, and the declaration every keel module carries."""

    def test_the_subcommand_resolves_to_a_callable(self) -> None:
        import keel  # noqa: PLC0415 - path set above

        self.assertIn("review", keel.COMMANDS)
        self.assertTrue(callable(keel.load("review")))
        self.assertIn("review", keel.usage())

    def test_it_declares_its_failure_policy(self) -> None:
        source = (REPO_ROOT / "scripts" / "keel_review.py").read_text(encoding="utf-8")
        self.assertIn("FAIL-CLOSED", source.split('"""')[1])


if __name__ == "__main__":
    unittest.main()
