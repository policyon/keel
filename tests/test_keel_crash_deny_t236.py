#!/usr/bin/env python3
"""T236 - a crash in keel's own code is a DENY that names itself, measured.

Contract
--------
Reads   : ``hooks/`` and ``scripts/`` of this repository, which every case
          COPIES into a throwaway tree before breaking the copy. Nothing in
          this repository is ever modified, and no case imports the broken
          copy into the test process.
Emits   : unittest results only.
Writes  : nothing outside the temporary directories it creates and removes.
          Every launch runs with ``HOME``/``USERPROFILE`` and the whole temp
          family (``TMPDIR``/``TEMP``/``TMP``) pointed inside the case's own
          tree, so the user-global hook-error log and the stop-loop marker
          this launcher writes land in the fixture rather than on the machine
          running the suite.

What is asserted, and why it is a SUBPROCESS
--------------------------------------------
The ruling under test is
``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``, and its
whole subject is what happens when keel's own module raises or does not import
at all. A mocked handler cannot show that: an ``ImportError`` inside the test
process is not the thing the harness meets, and the exit code the harness reads
is produced by the launcher's own ``main`` on a real interpreter. So every case
here appends a raising ``run`` - or a half-written ``def broken(`` - to a COPY
of the module, then launches ``hooks/keel_hook.py`` by subprocess with a JSON
payload on stdin, exactly as ``hooks/hooks.json`` does.

That copy-then-break shape is also what makes the half-applied-edit trigger
itself testable, which is convention 14's subject
(``docs/keel-conventions.md``) and the freeze this task was written from
(``.keel/plans/keel-freeze-2026-08-21-3fbfa431.md``).

Failure policy
--------------
FAIL-CLOSED, as every build gate is. A case that cannot establish its premise
fails; nothing here is skipped into a pass.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every subprocess is invoked with
an argument list, never a shell string (R5). Every file operation names its
encoding (convention 6).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_doctor  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_faultlog  # noqa: E402
import keel_gate  # noqa: E402
import keel_hook  # noqa: E402
import keel_session  # noqa: E402
import keel_stop  # noqa: E402
from keel_registry_guard import no_real_fleet_registry  # noqa: E402

#: The exit code a blocking hook decision carries (R6). Read from the kernel's
#: one table rather than typed, so this file cannot disagree with the gate.
DENY = keel_hook._deny_exit_code()

#: A ``run`` that raises the way a half-applied edit's leftovers do: a name the
#: module no longer defines. Appended to a copy, never to this repository.
INJECT_RAISE = '''

def run(event, env=None):  # keel test injection
    raise NameError("keel injected: name 'evaluate' is not defined")
'''

#: A ``run`` whose fault message carries the user's home directory, so the
#: REDACTION of the hook-error log can be asserted on real text rather than on
#: the promise of a chokepoint.
INJECT_RAISE_WITH_HOME = '''

def run(event, env=None):  # keel test injection
    import os
    raise RuntimeError(
        "keel injected: cannot read " + os.path.expanduser("~") + os.sep + "secret.txt"
    )
'''

#: A file that stops parsing mid-definition - what a gate module looks like
#: between two writes of one multi-location edit. This is the trigger the whole
#: ruling exists for, so it is exercised rather than described.
INJECT_HALF_WRITTEN = "\n\ndef broken(  # keel test injection: half-written file\n"

#: An adapter that ANSWERS on the first call and says "no keel event here" on
#: every later one. Two calls is exactly what one crashed gate call makes: the
#: subcommand builds the event, the gate raises, and the crash path rebuilds it
#: to ask the gate's own failure policy about it. So this injection puts the
#: launcher in front of an adapter RETURNING ``None`` - which means "this
#: payload maps to no gated event", not "keel could not tell" - through
#: production code rather than by calling ``_crash_event`` by hand.
INJECT_ADAPTER_NONE_ON_SECOND_CALL = '''

_keel_test_original_event_from_payload = event_from_payload
_keel_test_calls = []


def event_from_payload(*args, **kwargs):  # keel test injection
    _keel_test_calls.append(1)
    if len(_keel_test_calls) == 1:
        return _keel_test_original_event_from_payload(*args, **kwargs)
    return None
'''

#: The arming file, at the enforcing tier. The minimum a project needs for the
#: ruling's clause 1 to apply to it at all.
ARMED_POLICY = "---\ntier: 2\n---\n\n# keel policy\n"

WRITE_PAYLOAD: dict[str, Any] = {
    "hook_event_name": "PreToolUse",
    "tool_name": "Write",
    "tool_input": {"file_path": "src.py", "content": "x"},
}
STOP_PAYLOAD: dict[str, Any] = {"hook_event_name": "Stop"}
LEDGER_TARGET = ".keel/plans/keel-plan-abcdef12.md"

#: A path that CARRIES the ledger segment and TARGETS a gate module. The defect
#: the freeze record's section 3 names: the inline carve-out's segment test ran
#: on the raw payload value, so this would have been let through during a crash
#: - a crash-time write to keel's own hooks, through the one carve-out a crash
#: is allowed.
TRAVERSAL_TARGET = ".keel/plans/../../hooks/keel_gate.py"


def write_payload(file_path: str) -> dict[str, Any]:
    """A ``Write`` payload aimed at one path."""
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": "x"},
    }


class Fixture:
    """One throwaway tree: a copied installation, a project, a home, a temp dir.

    The installation is copied rather than referenced so that breaking it
    cannot touch this repository, and ``scripts/`` travels with ``hooks/``
    because the hook modules read their siblings there (the feature registry,
    the plan helpers).
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.tree = root / "tree"
        self.tree.mkdir(parents=True)
        shutil.copytree(REPO_ROOT / "hooks", self.tree / "hooks")
        shutil.copytree(REPO_ROOT / "scripts", self.tree / "scripts")
        self.hook = self.tree / "hooks" / "keel_hook.py"
        self.project = root / "project"
        self.project.mkdir()
        self.home = root / "home"
        self.home.mkdir()
        self.scratch = root / "scratch"
        self.scratch.mkdir()

    # ---------------------------------------------------------- the premises

    def arm(self) -> Fixture:
        """Adopt AND arm the project at the enforcing tier."""
        (self.project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
        (self.project / ".keel" / "keel-policy.md").write_text(ARMED_POLICY, encoding="utf-8")
        return self

    def adopt_unarmed(self) -> Fixture:
        """``.keel/`` and no arming file: adopted, never opted into enforcement."""
        (self.project / ".keel").mkdir(parents=True, exist_ok=True)
        return self

    def break_module(self, module: str, source: str) -> Fixture:
        """Append text to a COPIED module. The only way anything breaks here.

        The premise is asserted rather than assumed: a case that silently broke
        nothing would pass by measuring a healthy keel (convention 7).
        """
        target = self.tree / "hooks" / f"{module}.py"
        if not target.is_file():
            raise AssertionError(f"no such module to break: {target}")
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(source)
        return self

    # ------------------------------------------------------------- the launch

    def env(self) -> dict[str, str]:
        """No ``KEEL_*`` inherited, and every home/temp path inside this tree."""
        environ = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "USERPROFILE": str(self.home),
                "TMPDIR": str(self.scratch),
                "TEMP": str(self.scratch),
                "TMP": str(self.scratch),
                "PYTHONIOENCODING": "utf-8",
            }
        )
        return environ

    def launch(
        self, subcommand: str, payload: dict[str, Any], **extra: Any
    ) -> subprocess.CompletedProcess:
        """One hook launch, exactly as the harness performs one."""
        body = dict(payload)
        body.setdefault("cwd", str(self.project))
        body.setdefault("session_id", "abcdef12-3456-7890-abcd-ef1234567890")
        body.update(extra)
        return subprocess.run(
            [sys.executable, "-B", str(self.hook), subcommand],
            input=json.dumps(body),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.env(),
            cwd=str(self.project),
            timeout=120,
            check=False,
        )

    # -------------------------------------------------------------- the record

    def hook_errors(self) -> list[dict[str, Any]]:
        """Every line of the sandboxed user-global hook-error log."""
        path = self.home.joinpath(*keel_faultlog.USER_GLOBAL_RELPATH) / (
            keel_faultlog.HOOK_ERROR_LOG_NAME
        )
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def audit(self) -> list[dict[str, Any]]:
        """Every line of the project's own audit log."""
        path = self.project / ".keel" / "audit" / "keel-audit.jsonl"
        if not path.is_file():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class CrashCase(unittest.TestCase):
    """A case that owns one throwaway tree for its whole duration."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def assert_one_fault_logged(
        self, result: subprocess.CompletedProcess, subcommand: str
    ) -> dict[str, Any]:
        """EXACTLY ONE hook-error line, naming the subcommand and a fault kind.

        One, not "at least one": clause 5 wants a count, and a launcher that
        logged the same crash from two paths would inflate it.
        """
        lines = self.fixture.hook_errors()
        self.assertEqual(len(lines), 1, f"{lines}\n{result.stderr}")
        line = lines[0]
        self.assertEqual(line["event"], keel_faultlog.HOOK_ERROR_EVENT, line)
        self.assertEqual(line["subcommand"], subcommand, line)
        self.assertIn(line["fault_kind"], ("module", "configuration", "unknown"), line)
        self.assertTrue(line["error"].strip(), line)
        return line


class TestAnArmedProjectDeniesAndNamesTheFault(CrashCase):
    """Clause 1: armed project, keel's own code raises -> DENY, fault named,
    the project's own configuration explicitly exonerated."""

    def test_a_gate_crash_denies_with_the_fault_named(self) -> None:
        self.fixture.arm().break_module("keel_gate", INJECT_RAISE)
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertIn("keel injected", result.stderr)
        self.assertIn("KEEL", result.stderr)
        # The fault is keel's, and the message says so rather than sending a
        # reader to edit their own project (the freeze's own lesson).
        self.assertIn("NOT THIS PROJECT'S", result.stderr.upper())
        self.assert_one_fault_logged(result, "gate")
        blocks = [line for line in self.fixture.audit() if line.get("gate") == "internal_error"]
        self.assertTrue(blocks, self.fixture.audit())

    def test_a_stop_crash_denies_too(self) -> None:
        self.fixture.arm().break_module("keel_stop", INJECT_RAISE)
        result = self.fixture.launch("stop", STOP_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertIn("keel injected", result.stderr)
        self.assert_one_fault_logged(result, "stop")

    def test_a_gate_that_cannot_even_import_still_denies(self) -> None:
        """The launcher's own half of the ruling: with no gate module to ask,
        the answer is still deny, because armed-ness could not be established
        and unverifiable is deny."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertIn("UNVERIFIABLE IS DENY", result.stderr)
        self.assertIn("ONE write", result.stderr)
        self.assert_one_fault_logged(result, "gate")
        crash_lines = [
            line for line in self.fixture.audit() if line.get("event") == "launcher_crash_deny"
        ]
        self.assertEqual(len(crash_lines), 1, self.fixture.audit())
        self.assertEqual(crash_lines[0]["detail"]["subcommand"], "gate")

    def test_a_broken_adapter_denies(self) -> None:
        """A RAISE inside the adapter is the "unknown" state: the event cannot
        be rebuilt, so nothing about arming can be shown, so it denies."""
        self.fixture.arm().break_module(
            "keel_adapter_claude",
            "\n\ndef event_from_payload(*a, **k):  # keel test injection\n"
            "    raise RuntimeError('keel injected: the adapter is broken')\n",
        )
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assert_one_fault_logged(result, "gate")


class TestAnUnarmedProjectStillFailsOpen(CrashCase):
    """Clause 3: enforcement follows arming. A crash in keel must not gate a
    project that never opted in - and the fault is still counted."""

    def test_an_unarmed_gate_crash_allows(self) -> None:
        self.fixture.adopt_unarmed().break_module("keel_gate", INJECT_RAISE)
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_one_fault_logged(result, "gate")

    def test_an_unarmed_stop_crash_allows(self) -> None:
        self.fixture.adopt_unarmed().break_module("keel_stop", INJECT_RAISE)
        result = self.fixture.launch("stop", STOP_PAYLOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_one_fault_logged(result, "stop")


class TestTheLedgerIsTheOneCrashTimeWrite(CrashCase):
    """Clause 2: a write whose every target is inside the plans directory lands
    - loudly - so a freeze can always be put on the record. This project's own
    freeze report was written through exactly this path."""

    def test_a_ledger_write_lands_loudly_when_the_gate_raises(self) -> None:
        self.fixture.arm().break_module("keel_gate", INJECT_RAISE)
        result = self.fixture.launch("gate", write_payload(LEDGER_TARGET))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LEDGER WRITE", result.stderr.upper())
        self.assert_one_fault_logged(result, "gate")

    def test_a_ledger_write_lands_even_when_the_gate_cannot_import(self) -> None:
        """The INLINE carve-out, which is the only one that can run when the
        module owning the real one is the thing that broke - and a crash that
        cannot even import keel is when a session most needs to record it."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        result = self.fixture.launch("gate", write_payload(LEDGER_TARGET))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LEDGER WRITE PERMITTED THROUGH A FAILED LAUNCHER", result.stderr)
        self.assert_one_fault_logged(result, "gate")

    def test_a_traversal_dressed_as_a_ledger_path_is_denied(self) -> None:
        """The defect from the freeze record's section 3: a path that CARRIES
        ``.keel/plans/`` and TARGETS a hooks file must not reach the carve-out.
        The gate module cannot import here, so the INLINE test is the one under
        assertion - the resolving one in ``keel_gate`` is unreachable."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        result = self.fixture.launch("gate", write_payload(TRAVERSAL_TARGET))
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertNotIn("LEDGER WRITE PERMITTED", result.stderr)
        self.assert_one_fault_logged(result, "gate")

    def test_a_mixed_payload_is_denied_whole(self) -> None:
        """One target outside the plans directory refuses the whole payload:
        the carve-out is "every target", never "any target"."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        result = self.fixture.launch(
            "gate",
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": LEDGER_TARGET,
                    "edits": [{"file_path": "src.py"}],
                },
            },
        )
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assert_one_fault_logged(result, "gate")


class TestAPayloadTheSubcommandDoesNotGateIsUntouched(CrashCase):
    """A crash over a ``Read`` may not refuse the ``Read``, and the adapter
    RETURNING nothing is the adapter's own way of saying so."""

    def test_an_adapter_returning_none_on_the_crash_path_allows(self) -> None:
        """The freeze record's second latent defect, driven through production
        code: the first adapter call builds the gated event (so the gate is
        entered and raises), the second returns ``None``. ``None`` is
        "ungated", not "undeterminable", so the answer is 0 - which is what
        ``cmd_gate`` itself would have answered for that payload."""
        self.fixture.arm().break_module("keel_gate", INJECT_RAISE)
        self.fixture.break_module(
            "keel_adapter_claude", INJECT_ADAPTER_NONE_ON_SECOND_CALL
        )
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("does not gate", result.stderr)
        self.assert_one_fault_logged(result, "gate")

    def test_the_classifier_itself_answers_ungated_for_a_returned_none(self) -> None:
        """The same distinction at the unit, in this process, so the three
        states are pinned apart: a returned ``None`` is ``ungated``, a RAISE is
        ``unknown``, and only the second one denies."""
        read_payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
        }
        self.assertEqual(keel_hook._crash_event("gate", read_payload), (None, "ungated"))
        broken: dict[str, Any] = {"hook_event_name": "PreToolUse", "tool_name": "Write"}
        original = keel_hook.adapter.event_from_payload

        def boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the adapter is broken")

        keel_hook.adapter.event_from_payload = boom
        try:
            self.assertEqual(keel_hook._crash_event("gate", broken), (None, "unknown"))
        finally:
            keel_hook.adapter.event_from_payload = original


class TestACrashedStopRefusesOnceAndNotInALoop(CrashCase):
    """The third defect, measured by the freeze itself: the stop crash path
    honoured neither ``stop_hook_active`` nor any never-block-twice marker,
    because both live inside the function that raised. A deny that fires
    forever traps the session it is meant to guard - and clause 4's human
    unfreeze cannot be typed into a session whose every turn-end is refused."""

    def test_the_second_stop_in_the_window_passes(self) -> None:
        self.fixture.arm().break_module("keel_stop", INJECT_RAISE)
        first = self.fixture.launch("stop", STOP_PAYLOAD)
        self.assertEqual(first.returncode, DENY, first.stderr)
        second = self.fixture.launch("stop", STOP_PAYLOAD)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("NOT refusing this turn-end again", second.stderr)
        # Still counted, both times: standing aside is not forgetting.
        self.assertEqual(len(self.fixture.hook_errors()), 2, self.fixture.hook_errors())

    def test_the_marker_is_the_launchers_own_file_not_the_stop_gates(self) -> None:
        """Two different facts, two different files. Sharing one would let a
        healthy block suppress the crash path's single refusal, or the reverse."""
        self.fixture.arm().break_module("keel_stop", INJECT_RAISE)
        self.assertEqual(self.fixture.launch("stop", STOP_PAYLOAD).returncode, DENY)
        written = sorted(path.name for path in self.fixture.scratch.iterdir())
        self.assertTrue(
            any(name.startswith(keel_hook._CRASH_MARKER_PREFIX) for name in written), written
        )
        self.assertNotEqual(
            keel_hook._CRASH_MARKER_PREFIX, "keel_stop_", "the two markers share a name"
        )
        self.assertEqual(keel_hook.CRASH_MARKER_TTL_SECONDS, keel_stop.MARKER_TTL_SECONDS)

    def test_stop_hook_active_alone_stands_the_crash_deny_down(self) -> None:
        """The harness's own re-entry flag, honoured on the crash path exactly
        as ``keel_stop.evaluate`` honours it on the ordinary one."""
        self.fixture.arm().break_module("keel_stop", INJECT_RAISE)
        result = self.fixture.launch("stop", STOP_PAYLOAD, stop_hook_active=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("stop_hook_active", result.stderr)


class TestTheKillSwitchStillAnswersDuringACrash(CrashCase):
    """Clause 4: ``KEEL_GATE=off`` is the human unfreeze, so it has to work in
    the one state it exists for - including when the module that reads it is
    the module that failed to import."""

    def test_keel_gate_off_allows_even_with_an_unimportable_gate(self) -> None:
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        environ = self.fixture.env()
        environ["KEEL_GATE"] = "off"
        result = subprocess.run(
            [sys.executable, "-B", str(self.fixture.hook), "gate"],
            input=json.dumps({**WRITE_PAYLOAD, "cwd": str(self.fixture.project)}),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environ,
            cwd=str(self.fixture.project),
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("KEEL_GATE=off", result.stderr)


class TestEveryCrashLeavesOneRedactedLine(CrashCase):
    """Clause 5 plus convention 5: the fault is counted, and the count is
    written through the same redaction chokepoint every other keel log uses,
    so a message carrying a home path cannot leak one."""

    def test_the_hook_error_line_carries_a_screened_path(self) -> None:
        self.fixture.arm().break_module("keel_gate", INJECT_RAISE_WITH_HOME)
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        line = self.assert_one_fault_logged(result, "gate")
        self.assertIn("secret.txt", line["error"])
        self.assertIn("~", line["error"])
        self.assertNotIn(str(self.fixture.home), line["error"])
        self.assertNotIn(self.fixture.home.name, line["error"])

    def test_a_healthy_launch_writes_no_log_and_creates_no_directory(self) -> None:
        """The other direction of the same claim (convention 2): a keel that is
        working leaves the user's home byte-for-byte alone."""
        self.fixture.arm()
        result = self.fixture.launch("gate", write_payload(LEDGER_TARGET))
        self.assertIn(result.returncode, (0, DENY), result.stderr)
        self.assertEqual(self.fixture.hook_errors(), [])
        self.assertFalse(
            self.fixture.home.joinpath(*keel_faultlog.USER_GLOBAL_RELPATH).exists(),
            "a healthy launch must create no user-global keel directory",
        )


class TestObserversStillFailOpenWhenTheyCrash(CrashCase):
    """The ruling covers the two GATES. An observer's crash decides nothing, so
    it keeps the fail-open the launcher has always declared - and the freeze
    proves why that has to be true of the IMPORT too: a broken observer must
    cost its own subcommand, never the gate's verdict."""

    def test_a_broken_capture_observer_exits_zero(self) -> None:
        self.fixture.arm().break_module("keel_capture", INJECT_RAISE)
        result = self.fixture.launch(
            "capture",
            {
                "hook_event_name": "PostToolUse",
                "tool_name": "Write",
                "tool_input": {"file_path": "src.py", "content": "x"},
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_one_fault_logged(result, "capture")

    def test_a_session_observer_that_cannot_import_does_not_freeze_the_gate(self) -> None:
        """THE FREEZE OF 2026-08-21, as a fixture. A half-written
        ``keel_session`` - an observer, which decides nothing - left
        ``keel_gate`` unbound in one shared ``try``, so the launcher could not
        establish arming and denied every write in the project. With one guard
        per import the same break costs the ``session`` subcommand alone."""
        self.fixture.arm().break_module("keel_session", INJECT_HALF_WRITTEN)
        # THE GATE STILL EVALUATES, and "evaluates" is the claim - not "allows".
        # This payload has no plan on file, so the ordinary plan gate refuses
        # it, which is exactly the verdict a healthy keel gives: the deny names
        # the PLAN CONTRACT, not keel's own fault, and no crash is recorded.
        refused = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertIn("PLAN GATE", refused.stderr)
        for crash_phrase in ("UNVERIFIABLE IS DENY", "FAILED CLOSED", "LEDGER WRITE PERMITTED"):
            self.assertNotIn(crash_phrase, refused.stderr)
        # And a write the gate ALLOWS is still allowed: the session's own plan
        # file, through the gate's ordinary reasoning rather than any carve-out.
        allowed = self.fixture.launch("gate", write_payload(LEDGER_TARGET))
        self.assertEqual(
            allowed.returncode,
            0,
            "a broken OBSERVER may not cost the gate its verdict:\n" + allowed.stderr,
        )
        self.assertNotIn("LEDGER WRITE PERMITTED", allowed.stderr)
        self.assertEqual(self.fixture.hook_errors(), [], "no gate fault to report")
        session = self.fixture.launch(
            "session", {"hook_event_name": "SessionStart"}
        )
        self.assertEqual(session.returncode, 0, session.stderr)
        self.assertIn("keel_session", session.stderr)

    def test_a_broken_session_module_now_denies_the_stop_gate_closed(self) -> None:
        """Tests-review finding 3 (BL25/T475): ``keel_stop`` began importing
        ``keel_session`` at module scope to reuse ``model_from_transcript``
        (R15). UNLIKE the ``gate`` and ``session`` subcommands exercised above
        by the SAME break, ``stop`` is one of the two GATED subcommands
        (``keel_hook.GATED_SUBCOMMANDS``), so this is not the fail-open story
        the rest of this class tells: ``stop``'s own module cannot even be
        imported when ``keel_session`` is half-written, because
        ``from keel_session import model_from_transcript`` sits at
        ``keel_stop``'s own module scope. That is exactly the shape
        ``keel_hook.gate_crash_exit``'s ``_deny_without_a_gate`` branch exists
        for - no event-specific failure policy to ask (``keel_stop`` itself
        never bound), so the launcher's OWN ruling
        (``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``)
        answers instead: DENY, closed, the fault named - never a silent exit 0
        with no accounting, which is what an unguarded new import coupling
        could otherwise have produced."""
        self.fixture.arm().break_module("keel_session", INJECT_HALF_WRITTEN)
        result = self.fixture.launch("stop", STOP_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertIn("KEEL STOP FAILED CLOSED", result.stderr)
        self.assertIn("UNVERIFIABLE IS DENY", result.stderr)
        self.assert_one_fault_logged(result, "stop")
        crash_lines = [
            line for line in self.fixture.audit() if line.get("event") == "launcher_crash_deny"
        ]
        self.assertEqual(len(crash_lines), 1, self.fixture.audit())
        self.assertEqual(crash_lines[0]["detail"]["subcommand"], "stop")

    def test_a_broken_gate_still_leaves_the_fault_log_importable(self) -> None:
        """The ordering claim in one assertion: the fault log is imported in its
        own guard, so the record of a crash survives the crash - including a
        gate that never parsed."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        result = self.fixture.launch("gate", WRITE_PAYLOAD)
        self.assertEqual(result.returncode, DENY, result.stderr)
        self.assertEqual(len(self.fixture.hook_errors()), 1, self.fixture.hook_errors())


class TestTheDoctorReportsTheCountsTheRulingRequires(CrashCase):
    """Clause 5's second half: "the doctor surface reports the count, so
    repeated crashes are a visible number". A crash that leaves no number
    cannot be said to be eliminated."""

    def test_a_crash_deny_becomes_a_number_in_the_doctor_report(self) -> None:
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        self.assertEqual(self.fixture.launch("gate", WRITE_PAYLOAD).returncode, DENY)
        doctor = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO_ROOT / "scripts" / "keel_doctor.py"),
                "--project",
                str(self.fixture.project),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.fixture.env(),
            cwd=str(self.fixture.project),
            timeout=180,
            check=False,
        )
        report = json.loads(doctor.stdout)
        crashes = report["crash_denies"]
        self.assertEqual(crashes["total"], 1, crashes)
        self.assertEqual(crashes["by_kind"]["launcher_crash_deny"], 1, crashes)
        sessions = crashes["by_session"]
        self.assertEqual(len(sessions), 1, sessions)
        self.assertEqual(next(iter(sessions.values()))["launcher_crash_deny"], 1, sessions)
        # And the hook-error log's own three states are reported, never
        # collapsed into a boolean.
        self.assertEqual(report["hook_errors"]["state"], keel_faultlog.STATE_PRESENT, report)
        self.assertIn(
            keel_faultlog.STATE_PRESENT.upper(),
            report["hook_errors"]["state"].upper(),
        )

    def test_the_synthetic_launch_catches_a_gate_that_no_longer_compiles(self) -> None:
        """T236's third elimination condition: the trigger itself is attacked,
        and the doctor's synthetic launch has to CATCH a gate that no longer
        compiles rather than report the installation healthy. Run from inside
        the BROKEN copy, so the doctor probes that installation's own
        registrations, exactly as it would on a machine mid-freeze."""
        self.fixture.arm().break_module("keel_gate", INJECT_HALF_WRITTEN)
        doctor = subprocess.run(
            [
                sys.executable,
                "-B",
                str(self.fixture.tree / "scripts" / "keel_doctor.py"),
                "--project",
                str(self.fixture.project),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.fixture.env(),
            cwd=str(self.fixture.project),
            timeout=300,
            check=False,
        )
        report = json.loads(doctor.stdout)
        gate_probes = [
            probe for probe in report["probes"] if probe["event"] == "PreToolUse"
        ]
        self.assertTrue(gate_probes, report["probes"])
        unhealthy = [probe for probe in gate_probes if probe["state"] != "healthy"]
        self.assertTrue(
            unhealthy,
            "a gate that cannot be compiled must never probe healthy: "
            + json.dumps(gate_probes, indent=1),
        )
        self.assertNotEqual(
            keel_doctor.exit_code(report), 0, "the doctor must not exit healthy"
        )

    def test_a_clean_project_reports_zero_rather_than_silence(self) -> None:
        """An absent log and an unreadable one are different facts, and neither
        is "no crashes" said quietly (convention 7)."""
        self.fixture.arm()
        doctor = subprocess.run(
            [
                sys.executable,
                "-B",
                str(REPO_ROOT / "scripts" / "keel_doctor.py"),
                "--project",
                str(self.fixture.project),
                "--json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=self.fixture.env(),
            cwd=str(self.fixture.project),
            timeout=180,
            check=False,
        )
        report = json.loads(doctor.stdout)
        self.assertEqual(report["crash_denies"]["total"], 0, report["crash_denies"])
        self.assertTrue(report["crash_denies"]["note"], report["crash_denies"])
        self.assertEqual(report["hook_errors"]["state"], keel_faultlog.STATE_ABSENT, report)


class TestTheLastTwoCrashToAllowPathsAreClosed(unittest.TestCase):
    """T208, carried by this dispatch: the two calls that sat OUTSIDE their own
    guards. Both run after a verdict is already final, so an escape there could
    not change the decision - it could only destroy it, by reaching the launcher
    in place of the deny the gate had already reached. Under the ratified ruling
    that escape is now a deny rather than an allow, but it would be a deny with
    no audit line and the wrong fault named, so the guards still matter and each
    gets its fixture (condition 4 of T236's own acceptance)."""

    def test_a_gate_audit_whose_very_first_statement_raises_is_contained(self) -> None:
        """``keel_gate._audit``'s first statements - reading the verdict's
        detail, resolving the destination, relativising the cwd - used to sit
        above the ``try``."""

        class Exploding:
            gate = "plan"
            decision = "deny"
            blocking = True

            @property
            def detail(self) -> Any:
                raise RuntimeError("deliberate fault: the verdict's detail is unreadable")

        with tempfile.TemporaryDirectory() as tmp:
            event = keel_events.KeelEvent(
                kind="pre_write", cwd=Path(tmp), session_id="abcdef123456"
            )
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertIsNone(keel_gate._audit(event, Exploding()))  # must not raise
            self.assertIn("gate audit failed", err.getvalue())

    def test_locating_the_stop_marker_can_fail_without_escaping(self) -> None:
        """``keel_stop.marker_path`` reaches ``tempfile.gettempdir()``, which is
        a filesystem question with no guard of its own, and both callers used to
        build the path outside their own ``try``."""
        original = keel_stop.tempfile.gettempdir

        def boom() -> str:
            raise OSError("deliberate fault: no temp directory resolves")

        keel_stop.tempfile.gettempdir = boom
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                # "No fresh marker" is this function's own fail-safe answer, and
                # a fault while merely LOCATING one must read as that rather
                # than escape into ``evaluate``.
                self.assertFalse(keel_stop.marker_is_fresh("abcdef123456"))
                self.assertIsNone(keel_stop.touch_marker("abcdef123456"))
        finally:
            keel_stop.tempfile.gettempdir = original
        self.assertIn("stop marker not written", err.getvalue())

    def test_the_launchers_own_marker_guards_the_same_call(self) -> None:
        """The crash path's marker reaches the same unguarded function, so it
        carries the same guarantee: reported, never fatal, never a verdict."""
        original = keel_hook.tempfile.gettempdir

        def boom() -> str:
            raise OSError("deliberate fault: no temp directory resolves")

        keel_hook.tempfile.gettempdir = boom
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                self.assertEqual(keel_hook._stop_loop_guard({"session_id": "abcdef12"}), "")
                self.assertIsNone(keel_hook._touch_crash_marker({"session_id": "abcdef12"}))
        finally:
            keel_hook.tempfile.gettempdir = original
        self.assertIn("crashed-stop marker could not be written", err.getvalue())


class TestTheSessionStartWarningSaysWhatTheLogSays(unittest.TestCase):
    """T235's dead-man line, in all four of its answers. keel's observers
    fail-open, so a keel that has quietly stopped recording looks exactly like
    a keel with nothing to record; this line is what tells them apart, and its
    SILENCE on a clean machine is as load-bearing as its warning on a dirty
    one - a warning printed every session would be ignored by the third."""

    def _log(self, home: Path, age_days: float) -> Path:
        path = home.joinpath(*keel_faultlog.USER_GLOBAL_RELPATH) / (
            keel_faultlog.HOOK_ERROR_LOG_NAME
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"v": 1, "event": "hook_error"}\n', encoding="utf-8")
        stamp = time.time() - age_days * 86400.0
        os.utime(path, (stamp, stamp))
        return path

    def test_a_machine_that_has_never_failed_says_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(keel_session.hook_fault_line(Path(tmp)))

    def test_a_recent_log_warns_and_names_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._log(home, age_days=0.0)
            line = keel_session.hook_fault_line(home)
            self.assertIsNotNone(line)
            assert line is not None
            self.assertTrue(line.startswith(keel_session.HOOK_FAULT_TAG), line)
            self.assertIn(keel_faultlog.HOOK_ERROR_LOG_NAME, line)
            self.assertEqual(len(line.splitlines()), 1, "ONE line, not a paragraph")

    def test_an_old_log_is_history_not_news(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._log(home, age_days=keel_faultlog.RECENT_DAYS + 2)
            self.assertIsNone(keel_session.hook_fault_line(home))

    def test_an_unreadable_log_gets_its_own_sentence_never_silence(self) -> None:
        """The third state, kept apart from the first: reporting a log keel
        could not read as "no errors" is the swallowed error this project has a
        knowledge record about."""
        original = keel_faultlog.log_path

        def boom(home: Any = None) -> Any:
            raise OSError("deliberate fault: the log's location cannot be read")

        keel_faultlog.log_path = boom
        try:
            line = keel_session.hook_fault_line()
        finally:
            keel_faultlog.log_path = original
        self.assertIsNotNone(line)
        assert line is not None
        self.assertIn("could NOT be read", line)
        self.assertIn("not the same as no errors", line)

    def test_the_line_is_printed_and_charged_against_the_injection_cap(self) -> None:
        """It is injected context, so it costs the index its bytes (R16, R32).
        The seam is the function itself, spied the way this suite already spies
        ``index_block``, because ``run`` reads the real home."""
        sentence = f"{keel_session.HOOK_FAULT_TAG} - deliberate fixture sentence"
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel" / "plans").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(ARMED_POLICY, encoding="utf-8")
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id="abcdef123456"
            )
            caps: list[int] = []
            original_line = keel_session.hook_fault_line
            original_index = keel_session.index_block

            def line_spy(home: Any = None) -> str:
                return sentence

            def index_spy(lines: Any, cap: int) -> str:
                caps.append(cap)
                return original_index(lines, cap)

            keel_session.hook_fault_line = line_spy
            keel_session.index_block = index_spy
            stream = io.StringIO()
            try:
                with no_real_fleet_registry():
                    self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
            finally:
                keel_session.hook_fault_line = original_line
                keel_session.index_block = original_index

            self.assertIn(sentence, stream.getvalue())
            self.assertEqual(len(caps), 1)
            orientation = keel_session.orientation_lines(project, {})
            spent = (
                keel_session.orientation_bytes(orientation)
                + keel_session.orientation_bytes([keel_session.live_view_line()])
                + keel_session.orientation_bytes([sentence])
            )
            self.assertEqual(caps[0], keel_session.DEFAULT_INJECT_CAP_BYTES - spent)

    def test_a_faultlog_that_cannot_be_imported_costs_only_this_line(self) -> None:
        """The import is local and guarded because a half-applied edit to the
        log module is exactly the fault this line reports: it may cost the
        sentence, never the session's plan line or its context."""
        original = sys.modules.get("keel_faultlog")
        sys.modules["keel_faultlog"] = None  # type: ignore[assignment]
        err = io.StringIO()
        try:
            with contextlib.redirect_stderr(err):
                self.assertIsNone(keel_session.hook_fault_line())
            # Silence is the one answer convention 7 forbids: the line is lost,
            # and the reason is said.
            self.assertIn("hook-error log not consulted", err.getvalue())
        finally:
            if original is None:
                sys.modules.pop("keel_faultlog", None)
            else:
                sys.modules["keel_faultlog"] = original


class TestTheInlineCarveOutIsNarrowByUnit(unittest.TestCase):
    """The inline carve-out at the unit, because it is a LOOSENING and every
    boundary of a loosening is worth its own case (convention 2). The
    subprocess cases above prove it is reachable; these prove its shape."""

    def _count(self, file_path: str, subcommand: str = "gate") -> int:
        return keel_hook._inline_ledger_carve_out(
            subcommand, {"tool_input": {"file_path": file_path}}
        )

    def test_a_plain_relative_ledger_path_carves_out(self) -> None:
        self.assertEqual(self._count(LEDGER_TARGET), 1)

    def test_an_absolute_ledger_path_carves_out(self) -> None:
        self.assertEqual(self._count("C:/w/keel/.keel/plans/a.md"), 1)
        self.assertEqual(self._count("/home/w/keel/.keel/plans/a.md"), 1)  # keel-leak: ignore - fixture path inside an assertion

    def test_a_backslash_ledger_path_carves_out(self) -> None:
        self.assertEqual(self._count(r".keel\plans\a.md"), 1)

    def test_dot_dot_traversal_out_of_the_ledger_does_not(self) -> None:
        self.assertEqual(self._count(TRAVERSAL_TARGET), 0)
        self.assertEqual(self._count(r".keel\plans\..\..\hooks\keel_gate.py"), 0)

    def test_dot_dot_traversal_INTO_the_ledger_still_does(self) -> None:
        """The normalisation must not become a ban on ``..``: a path that
        resolves INTO the plans directory is a ledger write however it is
        spelled."""
        self.assertEqual(self._count("hooks/../.keel/plans/a.md"), 1)

    def test_a_lookalike_directory_does_not(self) -> None:
        self.assertEqual(self._count("notes.keel/plans/a.md"), 0)
        self.assertEqual(self._count(".keel/plansomething/a.md"), 0)

    def test_a_source_file_does_not(self) -> None:
        self.assertEqual(self._count("src.py"), 0)

    def test_no_target_is_not_a_carve_out(self) -> None:
        self.assertEqual(keel_hook._inline_ledger_carve_out("gate", {}), 0)
        self.assertEqual(
            keel_hook._inline_ledger_carve_out("gate", {"tool_input": {}}), 0
        )

    def test_stop_never_carves_out(self) -> None:
        """A Stop writes nothing, so it has no target to carve out."""
        self.assertEqual(self._count(LEDGER_TARGET, subcommand="stop"), 0)


if __name__ == "__main__":
    unittest.main()
