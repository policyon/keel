#!/usr/bin/env python3
"""The harness's OWN background runs reach the record and the board (T137).

Contract
--------
Reads   : ``hooks/keel_capture.py`` and
          ``scripts/keel_orchestration_dashboard.py`` (imported; the page is
          read as source text for the fencing cases), and nothing else of this
          repository's state. No case reads the real audit log, the real
          transcripts, or any agent definition: every premise is written by
          the case that stands on it.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, so a developer's own shell
          cannot change what a test observes.

What this file is for
---------------------
The board showed agents and only agents. The harness backgrounds SHELL
commands too - its own "Background tasks" panel lists them - and a
backgrounded run recorded exactly what a foreground one did: one ``activity``
line, no marker, no id, and no trace afterwards that anything was still
running. T137 adds ONE audit kind, ``background_task``, written BESIDE that
activity line, and ONE fenced verb on the adopted page.

The cases below pin, in this order:

* the fixtures' own premises - the invented task id really is of the measured
  shape, and the acknowledgment fixture really is the measured wording;
* the flag reader alone, over the measured shape and every way it can be
  absent, false or unexpected;
* the id reader alone, including the two ways it must answer NOTHING: an
  acknowledgment it cannot parse, and a token of id shape with no label in
  front of it;
* BOTH DIRECTIONS at the record level - a backgrounded call writes the added
  line, a foreground call writes exactly what it writes today and nothing
  more;
* THE HONEST LIMIT: no field of the record says finished, running, or
  succeeded, because no hook is told any of those;
* redaction, through the shipped hook as a SUBPROCESS, house style, so what is
  asserted is the bytes a harness would leave on disk;
* the display seat: the added verb is fenced, the page's own verbs survive
  untouched, and the served copy carries the kind into the feed.

EVERY FIXTURE HERE IS SYNTHETIC AND OWNS ITS PREMISE
(``a-test-that-borrows-its-premise-breaks-when-the-state-improves``). The task
ids are invented, of the measured shape, and asserted to BE of that shape by a
pattern this file writes rather than the module's own - so a fixture and the
code cannot agree with each other about a shape neither has
(``fixtures-that-agree-with-themselves-hide-a-real-mismatch``).

NO REAL HOME PATH APPEARS IN THIS FILE. The redaction case needs a value that
must not survive, and it is assembled from an invented account name and the
home root spelled as a constant, the way ``tests/test_keel_home_shapes.py``
does it: a test for a leak may not be the leak.

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

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")
QUEUE_RELPATH = (".keel", "queue", "keel-observations.jsonl")

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_redact  # noqa: E402

#: The wire values, spelled out rather than imported. This file exists to
#: notice the capture side and its readers drifting apart, and a guard that
#: imports the name it checks cannot see the name move.
BACKGROUND_KIND = "background_task"
ACTIVITY_KIND = "activity"
BACKGROUND_FLAG = "run_in_background"

#: Invented task ids of the MEASURED shape - 9 lowercase alphanumerics, which
#: is what all 63 measured acknowledgments carried. Invented so that nothing
#: here identifies a real run.
TASK_A = "b7q4zx2k9"
TASK_B = "bm1n0p5v3"

#: This file's OWN reading of the shape, deliberately not the module's, so a
#: defect in the module's pattern cannot supply both sides of an assertion.
LOCAL_TASK_ID_SHAPE = re.compile(r"^[a-z0-9]{9}$")

#: The acknowledgment as the harness WORDS it, measured in 63 of 63 launches:
#: a bare string, no mapping, no structured id anywhere in it.
ACK_TEMPLATE = (
    "Command running in background with ID: {task}. Output is being written "
    "to: {out}. You will be notified when it completes. To check interim "
    "output, use Read on that file path."
)

#: An invented account name and the home root as a constant, so that no
#: literal home path followed by a name appears in this file's source.
FAKE = "someoneelse"
WIN_ROOT = "Users"
MARK = keel_redact.HOME_SHAPE_TOKEN


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_hook(
    subcommand: str, payload: Any, project: Path, scratch: Path
) -> subprocess.CompletedProcess[bytes]:
    """Run the launcher exactly as a harness does: argv, JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), subcommand],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=clean_env(scratch),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def adopted_project(root: Path) -> Path:
    """A project keel would record in: it carries ``.keel/``, nothing more."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    return project


def audit_records(project: Path) -> list[dict[str, Any]]:
    """Every audit line of a project, decoded. A bad line fails the test."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def queue_records(project: Path) -> list[dict[str, Any]]:
    """Every queue line of a project, decoded."""
    path = project.joinpath(*QUEUE_RELPATH)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def shell_payload(
    project: Path,
    *,
    command: str = "python scripts/keel.py dashboard --project .",
    background: Any = True,
    task: str | None = TASK_A,
    session: str = "s-t137",
    tool: str = "Bash",
    tool_use_id: str = "toolu_bg_1",
    half: str = "PostToolUse",
    response: Any = None,
) -> dict[str, Any]:
    """One capture payload for a shell call, shaped from the MEASURED call.

    ``tool_input`` carries exactly what the 52 measured backgrounded calls
    carried - ``command``, ``description`` and the flag - and the result is a
    BARE STRING, which is what all 63 measured acknowledgments were. A case
    that needs another result shape passes ``response``.
    """
    tool_input: dict[str, Any] = {
        "command": command,
        "description": "start the live viewer",
    }
    if background is not None:
        tool_input[BACKGROUND_FLAG] = background
    payload: dict[str, Any] = {
        "hook_event_name": half,
        "tool_name": tool,
        "tool_use_id": tool_use_id,
        "tool_input": tool_input,
        "session_id": session,
        "cwd": str(project),
    }
    if half != "PreToolUse":
        if response is not None:
            payload["tool_response"] = response
        elif task is not None:
            payload["tool_response"] = ACK_TEMPLATE.format(
                task=task, out=f"/tmp/tasks/{task}.output"
            )
        else:
            payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
    return payload


def event_for(payload: dict[str, Any], project: Path) -> keel_events.KeelEvent:
    """The neutral event the launcher builds for a capture payload.

    ``command`` is filled the way the adapter fills it, so a unit case sees
    the same event the shipped hook would build.
    """
    return keel_events.KeelEvent(
        kind="post_tool",
        cwd=project,
        session_id=payload.get("session_id"),
        tool_name=payload.get("tool_name"),
        command=(payload.get("tool_input") or {}).get("command"),
        raw=payload,
    )


class TestTheFixturesOwnTheirPremise(unittest.TestCase):
    """The invented ids and the fixture wording really are the measured ones.

    Read with THIS FILE's own pattern and THIS FILE's own wording rather than
    the module's, so that every case below stands on a premise the code under
    test did not supply.
    """

    def test_the_invented_task_ids_have_the_measured_shape(self) -> None:
        for task in (TASK_A, TASK_B):
            self.assertRegex(task, LOCAL_TASK_ID_SHAPE)

    def test_the_two_task_ids_differ(self) -> None:
        self.assertNotEqual(TASK_A, TASK_B)

    def test_the_acknowledgment_fixture_is_a_bare_string_carrying_no_structure(
        self,
    ) -> None:
        payload = shell_payload(Path("."), task=TASK_A)
        self.assertIsInstance(payload["tool_response"], str)
        self.assertIn("running in background with ID", payload["tool_response"])

    def test_the_fixture_flag_is_the_json_boolean_that_was_measured(self) -> None:
        payload = shell_payload(Path("."))
        self.assertIs(payload["tool_input"][BACKGROUND_FLAG], True)


class TestTheFlagIsReadFromTheCall(unittest.TestCase):
    """``is_background_launch`` - the whole test for "was this backgrounded"."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = adopted_project(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_the_measured_boolean_says_yes(self) -> None:
        event = event_for(shell_payload(self.project, background=True), self.project)
        self.assertTrue(keel_capture.is_background_launch(event))

    def test_rendered_spellings_say_yes_too(self) -> None:
        for spelling in ("true", "TRUE", " True ", "1", "yes"):
            event = event_for(
                shell_payload(self.project, background=spelling), self.project
            )
            self.assertTrue(
                keel_capture.is_background_launch(event), f"{spelling!r} read as no"
            )

    def test_everything_else_says_no(self) -> None:
        for value in (None, False, "false", "no", "0", 0, 1, [], {}, "maybe"):
            payload = shell_payload(self.project, background=value)
            self.assertFalse(
                keel_capture.is_background_launch(event_for(payload, self.project)),
                f"{value!r} read as backgrounded",
            )

    def test_a_missing_flag_says_no(self) -> None:
        payload = shell_payload(self.project, background=None)
        self.assertNotIn(BACKGROUND_FLAG, payload["tool_input"])
        self.assertFalse(
            keel_capture.is_background_launch(event_for(payload, self.project))
        )

    def test_the_launch_half_says_no_because_it_has_heard_no_answer(self) -> None:
        payload = shell_payload(self.project, half="PreToolUse")
        self.assertFalse(
            keel_capture.is_background_launch(event_for(payload, self.project))
        )

    def test_a_write_tool_says_no_whatever_its_input_carries(self) -> None:
        payload = shell_payload(self.project, tool="Write")
        self.assertFalse(
            keel_capture.is_background_launch(event_for(payload, self.project))
        )

    def test_both_shell_spellings_say_yes(self) -> None:
        for tool in ("Bash", "bash", "PowerShell", "powershell"):
            payload = shell_payload(self.project, tool=tool)
            self.assertTrue(
                keel_capture.is_background_launch(event_for(payload, self.project)),
                f"{tool!r} read as not a shell tool",
            )


class TestTheTaskIdIsReadOrAnsweredNull(unittest.TestCase):
    """``background_task_id`` - one token, or an honest nothing."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = adopted_project(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _id_for(self, **kwargs: Any) -> str | None:
        return keel_capture.background_task_id(
            event_for(shell_payload(self.project, **kwargs), self.project)
        )

    def test_the_measured_acknowledgment_yields_its_id(self) -> None:
        self.assertEqual(self._id_for(task=TASK_A), TASK_A)

    def test_a_structured_result_carrying_the_same_sentence_is_read_too(self) -> None:
        found = self._id_for(
            response={"stdout": ACK_TEMPLATE.format(task=TASK_B, out="/tmp/x.output")}
        )
        self.assertEqual(found, TASK_B)

    def test_a_content_list_result_is_read_too(self) -> None:
        found = self._id_for(
            response={
                "content": [
                    {"type": "text", "text": ACK_TEMPLATE.format(task=TASK_B, out="x")}
                ]
            }
        )
        self.assertEqual(found, TASK_B)

    def test_an_unparsable_acknowledgment_answers_none_rather_than_a_guess(
        self,
    ) -> None:
        self.assertIsNone(self._id_for(response="started, see the tasks folder"))

    def test_an_unlabelled_token_of_id_shape_is_never_lifted(self) -> None:
        # The whole reason the read is labelled: this token IS of the measured
        # shape, and it must still record nothing, because nothing said it was
        # a task id.
        self.assertIsNone(self._id_for(response=f"done {TASK_A} done"))

    def test_a_result_of_an_unexpected_type_answers_none(self) -> None:
        for response in (17, [], {}, {"stdout": None}, True):
            self.assertIsNone(self._id_for(response=response), f"{response!r}")

    def test_a_missing_result_answers_none(self) -> None:
        payload = shell_payload(self.project)
        payload.pop("tool_response")
        self.assertIsNone(
            keel_capture.background_task_id(event_for(payload, self.project))
        )


class TestTheRecordItselfBothDirections(unittest.TestCase):
    """A backgrounded call records the added line; a foreground one does not."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = adopted_project(Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_backgrounded_call_yields_a_record(self) -> None:
        record = keel_capture.background_record(
            event_for(shell_payload(self.project), self.project)
        )
        assert record is not None
        self.assertEqual(record["event"], BACKGROUND_KIND)
        self.assertEqual(record["tool"], "Bash")
        self.assertEqual(record["tool_use_id"], "toolu_bg_1")
        self.assertEqual(record["task_id"], TASK_A)
        self.assertIn("dashboard", record["detail"])

    def test_a_foreground_call_yields_no_record_at_all(self) -> None:
        self.assertIsNone(
            keel_capture.background_record(
                event_for(shell_payload(self.project, background=False), self.project)
            )
        )

    def test_an_unparsable_acknowledgment_still_records_the_launch(self) -> None:
        record = keel_capture.background_record(
            event_for(
                shell_payload(self.project, response="off it goes"), self.project
            )
        )
        assert record is not None
        self.assertIsNone(record["task_id"])
        self.assertEqual(record["event"], BACKGROUND_KIND)

    def test_the_record_claims_nothing_about_how_the_run_ENDED(self) -> None:
        # The honest limit, pinned as a field list rather than as prose: no
        # hook is told a background run finished, so no key here may imply it.
        record = keel_capture.background_record(
            event_for(shell_payload(self.project), self.project)
        )
        assert record is not None
        self.assertEqual(
            sorted(record),
            ["agent_type", "detail", "event", "session", "task_id", "tool", "tool_use_id"],
        )
        forbidden = ("status", "exit_code", "exit", "done", "finished", "running",
                     "ended", "duration", "result", "success", "output")
        for key in forbidden:
            self.assertNotIn(key, record)
        self.assertNotIn("finish", json.dumps(record).casefold())

    def test_the_detail_is_the_same_text_the_activity_line_carries(self) -> None:
        event = event_for(shell_payload(self.project), self.project)
        self.assertEqual(
            keel_capture.background_record(event)["detail"],
            keel_capture.action_record(event)["detail"],
        )

    def test_the_activity_record_is_untouched_by_the_flag(self) -> None:
        # The direction that must never change: the kind every existing reader
        # depends on records exactly what it recorded before T137.
        backgrounded = keel_capture.action_record(
            event_for(shell_payload(self.project), self.project)
        )
        foreground = keel_capture.action_record(
            event_for(shell_payload(self.project, background=None), self.project)
        )
        self.assertEqual(backgrounded, foreground)

    def test_a_subagents_own_turn_carries_its_agent_id(self) -> None:
        # T233 step 2: the top-level ``agent_id`` the census measured on a
        # PostToolUse call made during a subagent's own turn.
        payload = shell_payload(self.project)
        payload["agent_id"] = "agent-42"
        payload["agent_type"] = "keel:executor"
        record = keel_capture.action_record(event_for(payload, self.project))
        self.assertEqual(record["agent_id"], "agent-42")

    def test_main_session_work_records_agent_id_null(self) -> None:
        # The other direction: no agent_id key on the raw payload at all,
        # which is what a main-session tool call carries per the census.
        record = keel_capture.action_record(
            event_for(shell_payload(self.project), self.project)
        )
        self.assertIsNone(record["agent_id"])


class TestTheShippedHookOnDisk(unittest.TestCase):
    """The bytes a harness would leave: the launcher, as a subprocess."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.scratch = self.root / "scratch"
        self.scratch.mkdir()
        self.project = adopted_project(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_a_backgrounded_run_writes_the_activity_line_AND_one_added_line(
        self,
    ) -> None:
        result = run_hook(
            "capture", shell_payload(self.project), self.project, self.scratch
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        self.assertEqual(result.stdout, b"")
        records = audit_records(self.project)
        self.assertEqual([r["event"] for r in records], [ACTIVITY_KIND, BACKGROUND_KIND])
        self.assertEqual(records[1]["task_id"], TASK_A)
        self.assertEqual(records[1]["session"], "s-t137")

    def test_a_foreground_run_writes_exactly_what_it_writes_today(self) -> None:
        result = run_hook(
            "capture",
            shell_payload(self.project, background=None),
            self.project,
            self.scratch,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        records = audit_records(self.project)
        self.assertEqual([r["event"] for r in records], [ACTIVITY_KIND])

    def test_one_backgrounded_run_is_one_observation_not_two(self) -> None:
        run_hook("capture", shell_payload(self.project), self.project, self.scratch)
        self.assertEqual(len(queue_records(self.project)), 1)

    def test_every_line_stays_one_json_object_per_line(self) -> None:
        run_hook("capture", shell_payload(self.project), self.project, self.scratch)
        text = self.project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
        for line in text.splitlines():
            self.assertIsInstance(json.loads(line), dict)

    def test_a_home_path_in_the_command_survives_in_neither_line(self) -> None:
        home = f"C:\\{WIN_ROOT}\\{FAKE}\\notes"
        run_hook(
            "capture",
            shell_payload(self.project, command=f"python {home}/run.py --serve"),
            self.project,
            self.scratch,
        )
        text = self.project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
        self.assertNotIn(FAKE, text)
        self.assertIn(MARK, text)
        self.assertEqual(
            [r["event"] for r in audit_records(self.project)],
            [ACTIVITY_KIND, BACKGROUND_KIND],
        )

    def test_a_private_region_in_the_command_reaches_neither_line(self) -> None:
        secret = "hunter2-invented-never-a-real-value"  # keel-leak: ignore - invented value, asserted to be redacted
        run_hook(
            "capture",
            shell_payload(
                self.project,
                command=f"deploy --token <keel-private>{secret}</keel-private>",
            ),
            self.project,
            self.scratch,
        )
        text = self.project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
        self.assertNotIn(secret, text)

    def test_an_unadopted_project_is_left_untouched(self) -> None:
        bare = self.root / "bare"
        bare.mkdir()
        result = run_hook("capture", shell_payload(bare), bare, self.scratch)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(audit_records(bare), [])


class TestTheDisplaySeatIsAdditive(unittest.TestCase):
    """The adopted page gains one fenced verb and loses nothing it shipped."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PAGE.read_text(encoding="utf-8")

    def test_the_added_verb_is_fenced_and_names_its_task(self) -> None:
        self.assertIn("KEEL ADDITION (T137)", self.source)
        fence = self.source.index("KEEL ADDITION (T137)")
        self.assertIn(f"{BACKGROUND_KIND}:e=>", self.source[fence : fence + 1400])

    def test_the_pages_own_verbs_survive_untouched(self) -> None:
        for verb in (
            "session_start:e=>",
            "handoff_start:e=>",
            "handoff_end:e=>",
            "gate_block:e=>",
            "stop_block:e=>",
            "review:e=>",
            "subagent_stop:e=>",
        ):
            self.assertIn(verb, self.source)

    def test_the_row_says_launched_and_never_claims_an_ending(self) -> None:
        fence = self.source.index("KEEL ADDITION (T137)")
        block = self.source[fence : fence + 1400]
        row = block[block.index(f"{BACKGROUND_KIND}:e=>") :].split("\n", 1)[0]
        self.assertIn("launched", row)
        for word in ("finished", "done", "complete", "running", "exit"):
            self.assertNotIn(word, row.casefold())

    def test_the_served_copy_carries_the_kind_into_the_feed(self) -> None:
        # The feed drops ``activity`` and nothing else; a background line is
        # not activity, so it reaches the page with no data-layer change.
        import keel_orchestration_dashboard as page

        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text(
                json.dumps(
                    {
                        "v": 1,
                        "ts": "2026-08-13T16:27:42Z",
                        "event": BACKGROUND_KIND,
                        "session": "s-t137",
                        "agent_type": None,
                        "tool": "Bash",
                        "tool_use_id": "toolu_bg_1",
                        "task_id": TASK_A,
                        "detail": "python scripts/keel.py dashboard",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            previous = page.ROOT
            page.ROOT = str(project)
            try:
                state = page.read_state()
            finally:
                page.ROOT = previous
        kinds = [event["event"] for event in state["events"]]
        self.assertIn(BACKGROUND_KIND, kinds)
        served = next(e for e in state["events"] if e["event"] == BACKGROUND_KIND)
        self.assertEqual(served["session_id"], "s-t137")
        self.assertEqual(served["task_id"], TASK_A)
        self.assertIsInstance(served["detail"], str)


if __name__ == "__main__":
    unittest.main()
