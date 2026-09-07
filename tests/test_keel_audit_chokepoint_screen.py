#!/usr/bin/env python3
"""The write-time screen's CHOKEPOINT - proven on the bytes in the file.

``tests/test_keel_denied_names_screen.py`` proves the screen as a function.
This file proves the thing that function could not: that a line reaches the
audit log screened NO MATTER WHICH MODULE WROTE IT. Every test here drives a
real writer - the gate's own ``run``, the stop gate's own ``run``, the queue
appender, and the hook launcher in a separate process - and then reads the
file back off disk and asserts on its bytes. Nothing here asserts the screen
by calling the screen.

Why the file and not the return value
------------------------------------
The finding this file answers was not "the screen is wrong", it was "the
screen is not reached": ``hooks/keel_gate.py`` and ``hooks/keel_stop.py``
append to the audit log and neither imports ``keel_redact``, so redaction was
applied by CONVENTION at each caller and two callers did not follow it. A test
that calls ``keel_redact.redact`` cannot see that class of defect at all, and
a test that inspects a verdict cannot either - the verdict is what the gate
returns, not what it writes. Only the file can tell, so the file is what is
read. Correspondingly, the pin is on the CHOKEPOINT
(``keel_events._append_jsonl``) and not on either caller: a per-caller import
would be the instance fix, and would reopen the moment a writer is added.

Contract
--------
Reads   : nothing of its own on disk except the installation's own
          ``hooks/`` modules. Every register these tests exercise is written
          by the test itself, to a temporary directory, and holds only the
          SHA-256 digest of an ordinary word chosen here ("pineapple",
          "orchard", "denied-name" as the reserved sentinel's own text) -
          never a name this repository's real register forbids. The one test
          that uses the real register never inspects it, and asserts on this
          machine's home directory instead, which needs no register at all.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. In
          particular it never appends to this repository's own
          ``.keel/audit/keel-audit.jsonl`` - every writer is pointed at a
          throwaway project.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
No plaintext denied name appears anywhere in this file, in a comment, in a
string literal or in a fixture.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402  (path must be set first)
import keel_gate  # noqa: E402
import keel_redact  # noqa: E402
import keel_stop  # noqa: E402

HOOK = REPO_ROOT / "hooks" / "keel_hook.py"

#: An ordinary word standing in for a registered name. Chosen for being a
#: single token under ``check_vendor_names``'s tokenisation and for having
#: nothing to do with anything this repository forbids.
WORD = "pineapple"

#: A second one, for the two-word register entry.
OTHER = "orchard"

#: A fixed timestamp, so two files written by two different appends can be
#: compared as BYTES. ``_append_jsonl`` stamps ``ts`` itself from
#: ``keel_events.utc_now``, which would otherwise differ across a second
#: boundary and make a byte comparison prove nothing about redaction.
FROZEN_TS = "2026-08-10T00:00:00Z"


def digest(token: str) -> str:
    """The register's own algorithm: sha256(lowercased token, utf-8)."""
    return hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()


def register(*tokens: str) -> frozenset[str]:
    """A ``_DENIED_HASHES``-shaped set naming only the ordinary ``tokens``."""
    return frozenset(digest(token) for token in tokens)


def armed_project(root: Path) -> Path:
    """A project keel enforces in: tier 2, with content of its own."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n\n## Policy lock\n\nlock:\n- src\n",
        encoding="utf-8",
    )
    (project / "src").mkdir()
    return project


def audit_bytes(project: Path) -> bytes:
    """The audit log exactly as it landed on disk. Fails if nothing was written."""
    path = keel_events.audit_path(project)
    if not path.is_file():
        raise AssertionError(f"no audit line was written to {path}")
    return path.read_bytes()


class _ScreensWithATemporaryRegister(unittest.TestCase):
    """Swap in a register of ordinary words, and put the real one back.

    Restored in ``tearDown`` so no later test - in this file or any other in
    the same discovery run - sees a fake register left behind.
    """

    def setUp(self) -> None:
        self._original = keel_redact._DENIED_HASHES
        keel_redact._DENIED_HASHES = register(WORD, f"{WORD} {OTHER}")

    def tearDown(self) -> None:
        keel_redact._DENIED_HASHES = self._original


class TestTheGateWritesScreenedLines(_ScreensWithATemporaryRegister):
    """``hooks/keel_gate.py`` never imports ``keel_redact``. It is covered anyway."""

    def test_the_gates_block_line_is_screened_in_the_file(self) -> None:
        """A registered name in ``event.file_paths`` becomes the audit target.

        This is finding 1 exactly: ``_audit`` appends ``verdict.detail``,
        whose ``target`` is built from the payload's own path, straight to the
        log. Driven through ``keel_gate.run`` - the function ``keel_hook.py``
        calls - so nothing about the writer is simulated.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=uuid.uuid4().hex,
                tool_name="Write",
                file_paths=(str(project / "notes" / f"{WORD}.py"),),
            )
            verdict = keel_gate.run(event, {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(
                verdict.detail["target"],
                f"notes/{WORD}.py",
                "the verdict itself is unscreened - the screen is at the write, not here",
            )
            raw = audit_bytes(project)
            self.assertNotIn(WORD.encode("utf-8"), raw)
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            self.assertEqual(line["event"], "gate_block")
            self.assertEqual(
                line["detail"]["target"],
                f"notes/{keel_redact.DENIED_NAME_TOKEN}.py",
            )

    def test_the_gates_bypass_line_is_screened_in_the_file(self) -> None:
        """``_audit_bypass`` is the other writer finding 1 named, and it takes
        its ``target`` straight from ``event.file_paths`` rather than from a
        verdict."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            locked = project / "src" / f"{WORD}.py"
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=uuid.uuid4().hex,
                tool_name="Write",
                file_paths=(str(locked),),
            )
            verdict = keel_gate.run(event, {"KEEL_OVERRIDE": "on"})
            self.assertEqual(verdict.decision, "deny", "no plan on file, so rule 2 still denies")
            raw = audit_bytes(project)
            self.assertNotIn(WORD.encode("utf-8"), raw)
            events = [json.loads(line) for line in raw.decode("utf-8").splitlines()]
            bypass = [entry for entry in events if entry["event"] == "gate_bypass"]
            self.assertEqual(len(bypass), 1, events)
            self.assertEqual(
                bypass[0]["detail"]["target"],
                f"src/{keel_redact.DENIED_NAME_TOKEN}.py",
            )

    def test_a_two_word_registered_phrase_is_screened_in_the_file_too(self) -> None:
        """The pair branch of the screen, exercised through the writer rather
        than through the function, because a pair spans two tokens and the
        substitution has to leave the line valid JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            event = keel_events.KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=uuid.uuid4().hex,
                tool_name="Write",
                file_paths=(str(project / "notes" / f"{WORD} {OTHER}.md"),),
            )
            keel_gate.run(event, {})
            raw = audit_bytes(project)
            self.assertNotIn(WORD.encode("utf-8"), raw)
            self.assertNotIn(OTHER.encode("utf-8"), raw)
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            token = keel_redact.DENIED_NAME_TOKEN  # keel-leak: ignore - the redaction token constant, not a secret
            self.assertEqual(line["detail"]["target"], f"notes/{token} {token}.md")


class TestTheStopGateWritesScreenedLines(_ScreensWithATemporaryRegister):
    """Finding 2: ``hooks/keel_stop.py`` has the same structural gap.

    Its audit lines carry no path today, but they do carry the harness's own
    ``session_id`` verbatim, which is text keel never authored. The point is
    not that this particular field is dangerous - it is that the module writes
    to the log without ever consulting the redactor, and is covered anyway.
    """

    def test_the_override_reminder_line_is_screened_in_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            event = keel_events.KeelEvent(
                kind="stop",
                cwd=project,
                session_id=f"{WORD}_{uuid.uuid4().hex[:8]}",
            )
            verdict = keel_stop.run(event, {"KEEL_OVERRIDE": "on"})
            self.assertEqual(verdict.decision, "allow")
            raw = audit_bytes(project)
            self.assertNotIn(WORD.encode("utf-8"), raw)
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            self.assertEqual(line["event"], "override_active_at_stop")
            self.assertTrue(
                line["session"].startswith(keel_redact.DENIED_NAME_TOKEN),
                line["session"],
            )


class TestTheQueueIsScreenedByTheSameDoor(_ScreensWithATemporaryRegister):
    """``append_queue`` shares ``_append_jsonl``, so it shares the screen.

    The queue matters as much as the audit log here: the contamination that
    occasioned T8 landed in BOTH tracked files, six lines across the two.
    """

    def test_a_queue_line_no_caller_redacted_is_screened_in_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            keel_events.append_queue(
                project,
                {
                    "event": "observation",
                    "action": f"ran grep for {WORD}",
                    "paths": [f"src/{WORD}/a.py", "src/other/b.py"],
                    "detail": {"nested": {"deeper": f"{WORD} again"}},
                },
            )
            raw = keel_events.queue_path(project).read_bytes()
            self.assertNotIn(WORD.encode("utf-8"), raw)
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            token = keel_redact.DENIED_NAME_TOKEN  # keel-leak: ignore - the redaction token constant, not a secret
            self.assertEqual(line["action"], f"ran grep for {token}")
            self.assertEqual(line["paths"], [f"src/{token}/a.py", "src/other/b.py"])
            self.assertEqual(line["detail"]["nested"]["deeper"], f"{token} again")


class TestDoubleScreeningIsByteIdenticalOnDisk(_ScreensWithATemporaryRegister):
    """The property the chokepoint stands on, measured in bytes.

    Callers that already redact (``keel_capture.py``, ``keel_session.py``)
    still pass through the chokepoint, so screening twice has to produce
    exactly what screening once produces. ``ts`` is frozen for the width of
    each test, because a stamp that differs by a second would make a byte
    comparison prove nothing about redaction.
    """

    def setUp(self) -> None:
        super().setUp()
        self._original_now = keel_events.utc_now
        keel_events.utc_now = lambda: FROZEN_TS

    def tearDown(self) -> None:
        keel_events.utc_now = self._original_now
        super().tearDown()

    def _append_both_ways(self, entry: dict[str, object], root: Path) -> tuple[bytes, bytes]:
        """The same entry appended raw, and appended already-redacted."""
        raw_project = root / "raw"
        pre_project = root / "pre"
        raw_project.mkdir()
        pre_project.mkdir()
        keel_events.append_audit(raw_project, entry)
        keel_events.append_audit(pre_project, keel_redact.redact_mapping(entry))
        return audit_bytes(raw_project), audit_bytes(pre_project)

    def test_an_already_redacted_entry_yields_identical_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entry = {
                "event": "gate_block",
                "detail": {"target": f"src/{WORD}/file.py", "switch": "KEEL_OVERRIDE"},
            }
            once, twice = self._append_both_ways(entry, Path(tmp))
            self.assertEqual(once, twice)
            self.assertNotIn(WORD.encode("utf-8"), once)
            self.assertIn(keel_redact.DENIED_NAME_TOKEN.encode("utf-8"), once)

    def test_a_home_directory_path_is_idempotent_through_the_door_too(self) -> None:
        """The other transformation the chokepoint applies, same measurement."""
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"event": "spike", "session": str(Path.home() / "notes.txt")}
            once, twice = self._append_both_ways(entry, Path(tmp))
            self.assertEqual(once, twice)
            self.assertNotIn(str(Path.home()).encode("utf-8"), once)

    def test_screening_a_third_time_still_yields_identical_bytes(self) -> None:
        """Not just "twice is safe": the fixed point is reached at the FIRST
        pass, so a caller, a re-reader and the door together cannot drift."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "third"
            project.mkdir()
            entry = {"event": "gate_block", "detail": {"target": f"src/{WORD}/file.py"}}
            thrice = keel_redact.redact_mapping(keel_redact.redact_mapping(entry))
            keel_events.append_audit(project, thrice)
            _, twice = self._append_both_ways(entry, Path(tmp))
            self.assertEqual(audit_bytes(project), twice)

    def test_idempotence_holds_even_when_the_register_names_the_sentinel(self) -> None:
        """The register is DATA, so the guarantee may not depend on it.

        ``DENIED_NAME_TOKEN`` contains a word the tokeniser recognises like
        any other. A screen that re-tokenised its own output would substitute
        inside its own substitution here and grow the line on every pass -
        ``[[...]]``, then ``[[[...]]]``. ``_screen_line`` reserves the
        sentinel, so the second pass changes nothing at all.
        """
        sentinel_word = keel_redact.DENIED_NAME_TOKEN.strip("[]")
        keel_redact._DENIED_HASHES = register(WORD, sentinel_word)
        with tempfile.TemporaryDirectory() as tmp:
            entry = {"event": "gate_block", "detail": {"target": f"src/{WORD}/file.py"}}
            once, twice = self._append_both_ways(entry, Path(tmp))
            self.assertEqual(once, twice)
            self.assertNotIn(b"[[", once)
            self.assertIn(keel_redact.DENIED_NAME_TOKEN.encode("utf-8"), once)

    def test_a_line_already_carrying_the_sentinel_is_left_alone(self) -> None:
        """The repaired lines already in this project's tracked logs carry
        this exact marker (see the knowledge record). Re-screening one of them
        must not touch it."""
        keel_redact._DENIED_HASHES = register(
            WORD, keel_redact.DENIED_NAME_TOKEN.strip("[]")
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "repaired"
            project.mkdir()
            already = f"grep -rn {keel_redact.DENIED_NAME_TOKEN} file.txt"
            keel_events.append_audit(project, {"event": "action", "detail": already})
            line = json.loads(audit_bytes(project).decode("utf-8").splitlines()[-1])
            self.assertEqual(line["detail"], already)


class TestTheChokepointHoldsAcrossAProcessBoundary(unittest.TestCase):
    """No monkeypatching at all: the real register, the real launcher.

    ``keel_hook.py``'s ``spike`` subcommand appends the payload's own
    ``session_id`` to the audit log and, like the gate and the stop gate,
    never imports ``keel_redact``. Feeding it a path under this user's home
    directory therefore tests the chokepoint end to end - in a separate
    process, through the real hook entry point, with nothing in this test's
    memory able to influence the result. The observable is the home-directory
    collapse rather than a denied name, because the real register's contents
    are not this test's business and must not be.
    """

    def test_a_writer_that_never_redacts_still_writes_a_redacted_file(self) -> None:
        home = str(Path.home())
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel").mkdir(parents=True)
            payload = {
                "hook_event_name": "SessionStart",
                "session_id": str(Path(home) / "notes.txt"),
                "cwd": str(project),
            }
            result = subprocess.run(
                [sys.executable, "-B", str(HOOK), "spike"],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=str(project),
                timeout=60,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = audit_bytes(project)
            self.assertNotIn(home.casefold(), raw.decode("utf-8").casefold())
            line = json.loads(raw.decode("utf-8").splitlines()[-1])
            self.assertEqual(line["event"], "spike")
            self.assertTrue(
                line["session"].startswith(keel_redact.HOME_TOKEN),
                f"the launcher's own audit line was not redacted: {line['session']!r}",
            )

    def test_the_screen_is_called_from_the_door_itself(self) -> None:
        """WHERE the call sits is the whole finding, so it is pinned directly.

        The same behaviour could be obtained by calling the screen from
        ``append_audit`` and ``append_queue`` instead - and it would be the
        instance fix all over again, reopening for the next writer that reaches
        ``_append_jsonl`` by another route. This asserts the call is inside the
        single door, not in either of the two functions that pass through it.
        A first version of this test asserted the module docstring MENTIONED
        the screen; that could not be made to fail (the name appears in the
        docstring several times over), so it was replaced by something that
        can.
        """
        self.assertIn("redact_mapping", keel_events._append_jsonl.__code__.co_names)
        for name in ("append_audit", "append_queue"):
            with self.subTest(name=name):
                self.assertNotIn(
                    "redact_mapping",
                    getattr(keel_events, name).__code__.co_names,
                    "the screen belongs at the door, not at each writer",
                )


class TestTheDoorFailsOpenPerValueAndClosedPerLine(_ScreensWithATemporaryRegister):
    """The failure policy the chokepoint inherits, asserted rather than assumed."""

    def test_an_unloadable_register_still_writes_the_line(self) -> None:
        """FAIL-OPEN per value: no register means nothing screened, never a
        lost audit line. The same condition fails ``keel_checks --names``
        closed at continuous integration, which is why open is defensible
        here - the write-time screen is the first line, not the only one."""
        keel_redact._DENIED_HASHES = None
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            keel_events.append_audit(project, {"event": "action", "detail": f"{WORD} here"})
            line = json.loads(audit_bytes(project).decode("utf-8").splitlines()[-1])
            self.assertEqual(line["detail"], f"{WORD} here")

    def test_a_non_string_field_passes_through_the_door_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            keel_events.append_audit(
                project, {"event": "stop_block", "detail": {"open_items": 3, "flag": True}}
            )
            line = json.loads(audit_bytes(project).decode("utf-8").splitlines()[-1])
            self.assertEqual(line["detail"], {"open_items": 3, "flag": True})
            self.assertEqual(line["v"], keel_events.AUDIT_SCHEMA_VERSION)

    def test_the_screen_itself_fails_open_on_a_non_string(self) -> None:
        """``screen_denied_names`` is named in the module contract, so it is
        reachable directly; a redactor that raises on ``None`` is a redactor a
        hook cannot call."""
        for value in (None, 17, {"a": 1}, ["b"]):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.screen_denied_names(value), value)


class TestNoWriterCanBypassTheDoor(unittest.TestCase):
    """The structural claim, checked against the tree rather than believed.

    The fix is at the chokepoint precisely so that a new writer inherits it.
    That argument is only sound while ``_append_jsonl`` really is the only
    place either log is opened for writing, so this test asserts that instead
    of trusting it: every shipped module that appends to the audit log or the
    queue does so through ``keel_events``, and no module opens either file
    itself.
    """

    def test_only_keel_events_opens_the_logs_for_writing(self) -> None:
        offenders: list[str] = []
        for source in sorted((REPO_ROOT / "hooks").glob("*.py")) + sorted(
            (REPO_ROOT / "scripts").glob("*.py")
        ):
            text = source.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                if "open(" not in line:
                    continue
                if any(mode in line for mode in ('"a"', "'a'", '"w"', "'w'")):
                    if "audit" in line.casefold() or "queue" in line.casefold():
                        offenders.append(f"{source.name}:{lineno}")
        self.assertEqual(offenders, [], "a writer that bypasses the chokepoint")

    def test_every_appender_is_the_one_function(self) -> None:
        """``append_audit`` and ``append_queue`` both delegate to the same
        private appender - two append routines would be two screens to keep in
        step, which is the drift this module's own docstring rejects."""
        for name in ("append_audit", "append_queue"):
            with self.subTest(name=name):
                source = getattr(keel_events, name).__code__.co_names
                self.assertIn("_append_jsonl", source)


if __name__ == "__main__":
    unittest.main()
