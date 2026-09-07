#!/usr/bin/env python3
"""A message to an agent is a RESUME hand-off (T124).

Contract
--------
Reads   : ``hooks/keel_capture.py``, ``hooks/keel_stop.py`` and
          ``scripts/keel_gen_hooks.py`` (imported), and nothing else of this
          repository's state. No case here reads the real audit log, the real
          agent definitions, or any transcript: every premise is written by
          the case that stands on it.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, so a developer's own shell
          cannot change what a test observes.

What this file is for
---------------------
Resuming an agent fires no launch tool: the orchestrator sends it a message,
so the capture layer's delegation matcher never fired, no ``handoff_start``
was written, and a resumed agent was invisible for as long as it worked - the
gap recorded in ``.keel/knowledge/a-resume-is-a-launch-the-record-never-saw.md``.
T124 records that send as a hand-off. The cases below pin, in this order:

* the id resolver alone, from every source and every failure path;
* BOTH DIRECTIONS at the record level - a message to an agent writes the
  hand-off, a message to anything else writes NOTHING;
* the resume marker, which is an ADDED key and not a reused one, and the
  three fields a send genuinely does not know, which stay null;
* the join: the exact key ``keel_stop`` already pairs stops on;
* additivity: a record written before any of this parses unchanged;
* the shipped hook as a SUBPROCESS, house style, so what is asserted is the
  bytes a harness would leave on disk, redaction included.

EVERY FIXTURE HERE IS SYNTHETIC AND OWNS ITS PREMISE. No case reads
``.keel/audit/keel-audit.jsonl`` for a shape to agree with, and no case
premises on what a real agent definition currently declares - the two ways a
test in this repository has broken for an IMPROVEMENT rather than a defect
(``a-test-that-borrows-its-premise-breaks-when-the-state-improves``). The
agent ids below are invented, of the measured shape, and every one of them is
asserted to BE of that shape by a case that does not use the matcher under
test, so a fixture and the code cannot agree with each other about a shape
neither has (``fixtures-that-agree-with-themselves-hide-a-real-mismatch``).

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
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")
QUEUE_RELPATH = (".keel", "queue", "keel-observations.jsonl")

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_gen_hooks  # noqa: E402
import keel_redact  # noqa: E402
import keel_stop  # noqa: E402

#: The wire values and keys, spelled out rather than imported. This file
#: exists to notice the capture side and its readers drifting apart, and a
#: guard that imports the name it checks cannot see the name move.
OPEN_EVENT = "handoff_start"
CLOSE_EVENT = "handoff_end"
KIND_FIELD = "handoff_kind"
RESUME_KIND = "resume"
LAUNCH_KIND = "launch"
MESSAGE_TOOL = "SendMessage"

#: Invented agent ids OF THE MEASURED SHAPE - 17 hexadecimal characters, the
#: shape every measured recipient, every stop line and every launch result in
#: this project carries. Invented so that nothing here identifies a real run.
AGENT_A = "a1b2c3d4e5f60718a"
AGENT_B = "b9c8d7e6f5a40312b"

#: This file's OWN reading of the shape, deliberately not the module's, so a
#: defect in ``_AGENT_ID_RE`` cannot supply both sides of an assertion.
LOCAL_AGENT_ID_SHAPE = re.compile(r"^[0-9a-f]{17}$")

#: Recipients that are NOT agents. A message to any of them must record
#: nothing at all - the second direction this file exists to pin.
NON_AGENT_RECIPIENTS = (
    "user",
    "owner",
    "orchestrator",
    "main-session",
    "Alex Invented",  # a person's name, invented: no real name is tracked here
    "#general",
    "someone@example.com",  # keel-leak: ignore - example.com address in a fixture
    "",
    "   ",
    None,
    17,
    [],
    {},
)

#: An invented account name and the home root as a constant, so that no
#: literal home path followed by a name appears in this file's source.
FAKE = "someoneelse"
WIN_ROOT = "Users"
MARK = keel_redact.HOME_SHAPE_TOKEN


def utc_stamp(seconds_ago: int = 0) -> str:
    """A timestamp in keel's own spelling, offset into the past."""
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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


def send_payloads(
    project: Path,
    session: str,
    recipient: Any,
    *,
    tool_use_id: str = "toolu_resume_1",
    summary: Any = "T124 retry: address the finding",
    message: Any = "Review finding on your change - this is your one retry.",
    resumed: Any = None,
    both_spellings: bool = True,
) -> list[dict[str, Any]]:
    """The two capture payloads one message-send produces, open then close.

    Shaped from the MEASURED payload: six ``tool_input`` keys, and a result
    that is a mapping carrying ``success``, ``message``, ``resumedAgentId``
    and ``pin``. ``resumed`` defaults to the recipient, which is what all
    twelve measured sends did; a case that needs them to disagree passes it.
    """
    tool_input: dict[str, Any] = {
        "to": recipient,
        "summary": summary,
        "message": message,
        "content": "Review finding on your change - this is your\u2026",
        "type": "message",
    }
    if both_spellings:
        tool_input["recipient"] = recipient
    common: dict[str, Any] = {
        "tool_name": MESSAGE_TOOL,
        "tool_use_id": tool_use_id,
        "tool_input": tool_input,
        "session_id": session,
        "cwd": str(project),
    }
    confirmed = recipient if resumed is None else resumed
    return [
        dict(common, hook_event_name="PreToolUse"),
        dict(
            common,
            hook_event_name="PostToolUse",
            tool_response={
                "success": True,
                "message": f'Agent "{confirmed}" had no active task; resumed it.',
                "resumedAgentId": confirmed,
                "pin": {"id": confirmed, "name": confirmed, "ref": "f3c778"},
            },
        ),
    ]


def event_for(payload: dict[str, Any], project: Path) -> keel_events.KeelEvent:
    """The neutral event the launcher builds for a capture payload.

    ``post_tool`` is what ``keel_hook.cmd_capture`` assumes for every capture
    payload; the launch/return distinction is read from ``hook_event_name``,
    which is why both halves are the same kind here.
    """
    return keel_events.KeelEvent(
        kind="post_tool",
        cwd=project,
        session_id=payload.get("session_id"),
        tool_name=payload.get("tool_name"),
        raw=payload,
    )


class TestTheFixturesOwnTheirPremise(unittest.TestCase):
    """The invented ids really are of the measured shape - checked here, once.

    Read with THIS FILE's own pattern rather than the module's. Without these
    two cases every "an agent id is recognised" case below could pass on a
    fixture that was never id-shaped, agreeing with a matcher that was never
    right.
    """

    def test_the_invented_ids_have_the_measured_shape(self) -> None:
        for value in (AGENT_A, AGENT_B):
            with self.subTest(value=value):
                self.assertRegex(value, LOCAL_AGENT_ID_SHAPE)
        self.assertNotEqual(AGENT_A, AGENT_B, "two ids that must be told apart")

    def test_the_non_agent_recipients_have_no_id_shape(self) -> None:
        for value in NON_AGENT_RECIPIENTS:
            with self.subTest(value=value):
                self.assertFalse(
                    isinstance(value, str) and LOCAL_AGENT_ID_SHAPE.match(value.strip()),
                    "a 'not an agent' fixture that is id-shaped proves nothing",
                )


class TestTheRecipientResolves(unittest.TestCase):
    """The id resolver alone: every source, and every way it may not answer."""

    def resolve(self, payload: dict[str, Any]) -> Any:
        with tempfile.TemporaryDirectory() as tmp:
            return keel_capture.resume_agent_id(event_for(payload, Path(tmp)))

    def test_the_open_half_answers_from_the_call_alone(self) -> None:
        """The half that has no result at all - and the whole point of the
        change: an id known at PreToolUse is an agent visible WHILE it works."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A)[0]
            self.assertNotIn("tool_response", payload, "premise: no result yet")
            self.assertEqual(self.resolve(payload), AGENT_A)

    def test_either_recipient_spelling_answers(self) -> None:
        for key in ("to", "recipient"):
            with self.subTest(key=key):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": MESSAGE_TOOL,
                    "tool_input": {key: AGENT_A},
                }
                self.assertEqual(self.resolve(payload), AGENT_A)

    def test_the_result_answers_on_the_close_half(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A)[1]
            self.assertEqual(self.resolve(payload), AGENT_A)

    def test_the_result_wins_when_it_disagrees_with_the_call(self) -> None:
        """The harness names the agent it ACTUALLY resumed; the caller named
        the one it asked for. A record may only carry the first."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A, resumed=AGENT_B)[1]
            self.assertEqual(self.resolve(payload), AGENT_B)

    def test_the_pinned_id_answers_when_the_field_is_missing(self) -> None:
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": MESSAGE_TOOL,
            "tool_input": {"to": AGENT_A},
            "tool_response": {"success": True, "pin": {"id": AGENT_B}},
        }
        self.assertEqual(self.resolve(payload), AGENT_B)

    def test_a_rendered_result_is_read_from_its_text(self) -> None:
        """Structure first, text only as a fallback - for a harness build that
        hands a hook the result's rendered content instead of its fields."""
        for response in (
            f'{{"success":true,"resumedAgentId":"{AGENT_B}"}}',
            {"content": [{"type": "text", "text": f"resumedAgentId: {AGENT_B}"}]},
        ):
            with self.subTest(response=type(response).__name__):
                payload = {
                    "hook_event_name": "PostToolUse",
                    "tool_name": MESSAGE_TOOL,
                    "tool_input": {},
                    "tool_response": response,
                }
                self.assertEqual(self.resolve(payload), AGENT_B)

    def test_a_recipient_that_is_not_an_agent_answers_nothing(self) -> None:
        for value in NON_AGENT_RECIPIENTS:
            with self.subTest(value=value):
                payload = {
                    "hook_event_name": "PreToolUse",
                    "tool_name": MESSAGE_TOOL,
                    "tool_input": {"to": value, "recipient": value},
                }
                self.assertIsNone(self.resolve(payload))

    def test_an_unexpected_payload_shape_answers_nothing_and_does_not_raise(self) -> None:
        for payload in (
            {"hook_event_name": "PreToolUse", "tool_name": MESSAGE_TOOL},
            {"tool_name": MESSAGE_TOOL, "tool_input": "not a mapping"},
            {"tool_name": MESSAGE_TOOL, "tool_input": [], "tool_response": []},
            {"tool_name": MESSAGE_TOOL, "tool_input": {}, "tool_response": 17},
            {"tool_name": MESSAGE_TOOL, "tool_input": {}, "tool_response": None},
            {"tool_name": MESSAGE_TOOL, "tool_input": {"to": {"id": AGENT_A}}},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(self.resolve(payload))

    def test_an_id_shaped_token_inside_prose_is_not_lifted(self) -> None:
        """The MESSAGE body is prose about the work and routinely discusses
        ids; only the labelled field is read, and never the body."""
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": MESSAGE_TOOL,
            "tool_input": {
                "to": "user",
                "message": f"the stop line for {AGENT_A} never paired",
            },
            "tool_response": {"success": False},
        }
        self.assertIsNone(self.resolve(payload))

    def test_the_scan_of_a_rendered_result_is_bounded(self) -> None:
        """A long result may never turn one hook into a scan of a transcript."""
        filler = "x" * (keel_capture.RESULT_TEXT_SCAN_CHARS + 200)
        payload = {
            "hook_event_name": "PostToolUse",
            "tool_name": MESSAGE_TOOL,
            "tool_input": {},
            "tool_response": f"{filler} resumedAgentId: {AGENT_B}",
        }
        self.assertIsNone(self.resolve(payload))


class TestBothDirectionsAtTheRecordLevel(unittest.TestCase):
    """A message to an agent writes the hand-off; any other message writes none."""

    def record(self, payload: dict[str, Any]) -> Any:
        with tempfile.TemporaryDirectory() as tmp:
            return keel_capture.record_for(event_for(payload, Path(tmp)))

    def test_a_message_to_an_agent_writes_both_halves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open_half, close_half = (
                self.record(payload)
                for payload in send_payloads(Path(tmp), "s", AGENT_A)
            )
        self.assertEqual(open_half["event"], OPEN_EVENT)
        self.assertEqual(close_half["event"], CLOSE_EVENT)
        for record in (open_half, close_half):
            self.assertEqual(record["agent_id"], AGENT_A)
            self.assertEqual(record[KIND_FIELD], RESUME_KIND)

    def test_a_message_to_anything_else_writes_nothing(self) -> None:
        """The other direction, and the one that keeps the log honest: keel
        observes delegations, and a message to a person is not one."""
        for value in NON_AGENT_RECIPIENTS:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                for payload in send_payloads(Path(tmp), "s", value):
                    self.assertIsNone(self.record(payload))

    def test_a_send_that_names_nobody_writes_nothing(self) -> None:
        self.assertIsNone(
            self.record(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": MESSAGE_TOOL,
                    "tool_input": {"summary": "a note", "message": "a body"},
                }
            )
        )

    def test_a_send_the_harness_refused_is_still_recorded_as_a_pair(self) -> None:
        """A decision, not an oversight: the open half cannot know the outcome,
        so dropping the close half would leave a delegation open in the stop
        gate for no reason a reader could see. What was ATTEMPTED is recorded;
        whether an agent then worked is what its stop and its activity say."""
        with tempfile.TemporaryDirectory() as tmp:
            close_half = send_payloads(Path(tmp), "s", AGENT_A)[1]
            close_half["tool_response"] = {
                "success": False,
                "message": "no agent by that id",
            }
            record = self.record(close_half)
        self.assertIsNotNone(record)
        self.assertEqual(record["event"], CLOSE_EVENT)
        self.assertEqual(record["agent_id"], AGENT_A, "the pair must still join")

    def test_the_tool_name_is_matched_casefolded(self) -> None:
        """Convention 3: a harness that restyles the name is still read."""
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A)[0]
            for spelling in (MESSAGE_TOOL.lower(), MESSAGE_TOOL.upper(), MESSAGE_TOOL):
                with self.subTest(spelling=spelling):
                    record = self.record(dict(payload, tool_name=spelling))
                    self.assertIsNotNone(record)
                    self.assertEqual(record["agent_id"], AGENT_A)


class TestTheResumeIsDistinguishable(unittest.TestCase):
    """The marker is added, not reused - and it says what the send knows."""

    def resume(self, index: int = 0, **kwargs: Any) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A, **kwargs)[index]
            return keel_capture.record_for(event_for(payload, Path(tmp)))

    def launch(self, index: int = 0) -> dict[str, Any]:
        payload = {
            "hook_event_name": "PreToolUse" if index == 0 else "PostToolUse",
            "tool_name": "Task",
            "tool_use_id": "toolu_launch_1",
            "session_id": "s",  # the same session as ``resume``: the two
            # records are compared field by field below, and a session that
            # differed would read as a difference between the two KINDS.
            "tool_input": {
                "subagent_type": "keel:no-such-agent-in-this-test",
                "description": "a delegation",
                "prompt": "TASK: do the thing",
            },
        }
        with tempfile.TemporaryDirectory() as tmp:
            return keel_capture.record_for(event_for(payload, Path(tmp)))

    def test_the_two_kinds_carry_different_markers(self) -> None:
        for index in (0, 1):
            with self.subTest(half=index):
                self.assertEqual(self.resume(index)[KIND_FIELD], RESUME_KIND)
                self.assertEqual(self.launch(index)[KIND_FIELD], LAUNCH_KIND)

    def test_no_existing_field_was_repurposed_to_say_it(self) -> None:
        """A resume is told from a launch by the ADDED key and by nothing
        else: the wire ``event`` values are the same two, deliberately, so
        every existing reader counts a resumed agent as the hand-off it is."""
        resume, launch = self.resume(0), self.launch(0)
        self.assertEqual(resume["event"], launch["event"])
        self.assertEqual(
            {key for key in resume if resume[key] != launch.get(key)} - {KIND_FIELD},
            {"agent_id", "subagent_type", "tool_use_id", "description", "prompt_head"},
            "a field changed meaning between the two kinds",
        )

    def test_the_send_records_null_for_what_it_cannot_know(self) -> None:
        """Never guessed from the earlier launch: a type, a model and an
        effort inferred at capture time are indistinguishable afterwards from
        ones that were observed."""
        for index in (0, 1):
            record = self.resume(index)
            for field in ("subagent_type", "model", "effort"):
                with self.subTest(half=index, field=field):
                    self.assertIn(field, record, "absence is expressed, never omitted")
                    self.assertIsNone(record[field])

    def test_the_summary_and_the_body_are_what_the_send_carries(self) -> None:
        record = self.resume(0, summary="T124 retry", message="the finding, in full")
        self.assertEqual(record["description"], "T124 retry")
        self.assertEqual(record["prompt_head"], "the finding, in full")

    def test_the_body_is_bounded(self) -> None:
        long_body = "z" * (keel_capture.PROMPT_HEAD_CHARS + 500)
        record = self.resume(0, message=long_body)
        self.assertEqual(len(record["prompt_head"]), keel_capture.PROMPT_HEAD_CHARS)

    def test_a_send_with_no_full_body_falls_back_to_the_preview(self) -> None:
        """``content`` is a truncated preview of ``message`` - the full one is
        read first, and the preview is what is left when it is absent."""
        record = self.resume(0, message=None)
        self.assertTrue(record["prompt_head"].startswith("Review finding"))

    def test_a_send_carrying_neither_records_a_null_and_an_empty_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = send_payloads(Path(tmp), "s", AGENT_A)[0]
            payload["tool_input"].pop("content")
            payload["tool_input"]["summary"] = None
            payload["tool_input"]["message"] = None
            record = keel_capture.record_for(event_for(payload, Path(tmp)))
        self.assertIsNone(record["description"])
        self.assertEqual(record["prompt_head"], "")


class TestTheStopPairsWithTheResume(unittest.TestCase):
    """The join key: the stop that ends a resumed run closes the resume record.

    The gate is driven against an audit log this class WRITES - the shape a
    resumed run leaves behind - so nothing here depends on what the real log
    happens to contain today.
    """

    def log(self, project: Path, lines: list[dict[str, Any]]) -> None:
        audit = project.joinpath(*AUDIT_RELPATH)
        audit.parent.mkdir(parents=True, exist_ok=True)
        with open(audit, "w", encoding="utf-8", newline="\n") as handle:
            for line in lines:
                handle.write(json.dumps(line) + "\n")

    def resume_lines(self, session: str, agent_id: str) -> list[dict[str, Any]]:
        common = {
            "v": 1,
            KIND_FIELD: RESUME_KIND,
            "session": session,
            "tool_use_id": f"toolu_{agent_id}",
            "agent_id": agent_id,
            "subagent_type": None,
            "model": None,
            "effort": None,
            "description": "a resume",
            "prompt_head": "the finding",
        }
        return [
            dict(common, event=OPEN_EVENT, ts=utc_stamp(120)),
            dict(common, event=CLOSE_EVENT, ts=utc_stamp(120)),
        ]

    def test_the_shared_matcher_pairs_a_stop_to_the_resume_it_ended(self) -> None:
        start = self.resume_lines("s", AGENT_A)[0]
        stop = {"event": "subagent_stop", "agent_id": AGENT_A, "agent_type": None}
        matched = keel_stop.match_stops_to_launches(
            [keel_stop.launch_agent_id(start)], [stop]
        )
        self.assertEqual(matched, {0: stop})

    def test_the_open_half_alone_carries_the_key(self) -> None:
        """A launch's open half cannot name an id and records null; a resume's
        can, because a message names its recipient before it is sent. That is
        what lets a stop pair even when the close half never landed."""
        start = self.resume_lines("s", AGENT_A)[0]
        self.assertEqual(keel_stop.launch_agent_id(start), AGENT_A)

    def test_a_stop_naming_another_agent_closes_nothing(self) -> None:
        start = self.resume_lines("s", AGENT_A)[0]
        stop = {"event": "subagent_stop", "agent_id": AGENT_B, "agent_type": None}
        self.assertEqual(
            keel_stop.match_stops_to_launches([keel_stop.launch_agent_id(start)], [stop]),
            {},
        )

    def test_the_gate_holds_the_turn_while_a_resumed_agent_works(self) -> None:
        """The pair lands within the background window - a send returns at
        once - so the delegation is OPEN until its stop names it, which is
        exactly how a backgrounded launch already behaves."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self.log(project, self.resume_lines(session, AGENT_A))
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "a resumed agent is not visible to the stop gate",
            )
            self.log(
                project,
                self.resume_lines(session, AGENT_A)
                + [
                    {
                        "v": 1,
                        "event": "subagent_stop",
                        "session": session,
                        "ts": utc_stamp(30),
                        "agent_id": AGENT_A,
                        "agent_type": None,
                    }
                ],
            )
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "the stop naming the resumed agent did not close it",
            )

    def test_two_resumes_of_different_agents_are_told_apart(self) -> None:
        """A type is not an identity, and neither resume record has a type:
        what tells them apart is the id, which is the whole point of it."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self.log(
                project,
                self.resume_lines(session, AGENT_A)
                + self.resume_lines(session, AGENT_B)
                + [
                    {
                        "v": 1,
                        "event": "subagent_stop",
                        "session": session,
                        "ts": utc_stamp(30),
                        "agent_id": AGENT_B,
                        "agent_type": None,
                    }
                ],
            )
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "one agent's stop closed the other agent's resume",
            )


class TestOlderLinesStayValid(unittest.TestCase):
    """Additive only: a record written before any of this parses unchanged.

    The old shapes are WRITTEN HERE rather than read out of the real log -
    the same rule the rest of this file obeys - so the case keeps meaning the
    same thing however the real log grows.
    """

    OLD_LAUNCH = {
        "v": 1,
        "event": OPEN_EVENT,
        "session": "older-session",
        "tool_use_id": "toolu_old",
        "agent_id": None,
        "subagent_type": "keel:executor",
        "description": "a delegation from before the marker",
        "prompt_head": "TASK",
    }

    def test_an_older_line_carries_no_marker_and_reads_as_a_launch(self) -> None:
        """Absent means "written before the key existed", and every such line
        is a launch by construction: nothing else could write a hand-off then."""
        line = json.loads(json.dumps(self.OLD_LAUNCH))
        self.assertNotIn(KIND_FIELD, line)
        self.assertIsNone(line.get(KIND_FIELD))
        self.assertEqual(line["event"], OPEN_EVENT)

    def test_the_stop_gate_reads_an_older_pair_exactly_as_before(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True, exist_ok=True)
            with open(audit, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(dict(self.OLD_LAUNCH, session=session, ts=utc_stamp(200)))
                    + "\n"
                )
            self.assertTrue(keel_stop.session_has_open_handoff(project, session))
            with open(audit, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        dict(
                            self.OLD_LAUNCH,
                            session=session,
                            ts=utc_stamp(60),
                            event=CLOSE_EVENT,
                        )
                    )
                    + "\n"
                )
            self.assertFalse(keel_stop.session_has_open_handoff(project, session))

    def test_the_new_key_is_an_addition_and_removes_nothing(self) -> None:
        """Every field an older hand-off line carried is still written."""
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_use_id": "toolu_now",
            "tool_input": {"subagent_type": "keel:x", "description": "d", "prompt": "p"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            record = keel_capture.record_for(event_for(payload, Path(tmp)))
        for key in self.OLD_LAUNCH:
            if key in ("v", "ts"):
                continue  # stamped by the writer, not by the record builder
            with self.subTest(key=key):
                self.assertIn(key, record)


class TestTheShippedHookWritesTheRecord(unittest.TestCase):
    """The launcher as a subprocess: the bytes a harness would leave on disk."""

    def test_a_resume_lands_as_a_pair_in_the_audit_log(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for payload in send_payloads(project, session, AGENT_A):
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, b"", "an observer that speaks")
            records = audit_records(project)
            self.assertEqual([r["event"] for r in records], [OPEN_EVENT, CLOSE_EVENT])
            for record in records:
                self.assertEqual(record[KIND_FIELD], RESUME_KIND)
                self.assertEqual(record["agent_id"], AGENT_A)
                self.assertEqual(record["session"], session)
                self.assertEqual(record["tool_use_id"], "toolu_resume_1")
                self.assertIsNone(record["subagent_type"])
            raw = project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
            self.assertIn('"model": null', raw)
            self.assertIn('"effort": null', raw)
            self.assertIn('"handoff_kind": "resume"', raw)

    def test_a_message_to_a_person_leaves_no_line_at_all(self) -> None:
        """Not an empty record, not a null-id hand-off: nothing, in either log."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for payload in send_payloads(project, session, "user"):
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(audit_records(project), [])
            self.assertEqual(queue_records(project), [])

    def test_the_return_half_queues_one_observation_and_the_launch_half_none(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            payloads = send_payloads(project, session, AGENT_A)
            run_hook("capture", payloads[0], project, root)
            self.assertEqual(queue_records(project), [], "the open half queued a line")
            run_hook("capture", payloads[1], project, root)
            queued = queue_records(project)
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["tool"], MESSAGE_TOOL)
            self.assertIn("resumed subagent", queued[0]["action"])
            self.assertIn("T124 retry", queued[0]["action"])
            self.assertNotIn(AGENT_A, json.dumps(queued[0]), "the queue is lossy")

    def test_an_unadopted_project_is_untouched(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bare"
            project.mkdir()
            for payload in send_payloads(project, session, AGENT_A):
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((project / ".keel").exists())


class TestEveryValueIsScreened(unittest.TestCase):
    """A resume's own fields pass the write-time screen, like every other value.

    The chokepoint is ``keel_events._append_jsonl`` - the one function every
    audit and queue line passes through - so these cases read the BYTES on
    disk rather than a return value: a screen that was never reached cannot
    be seen from the value that skipped it.
    """

    #: An invented home path, assembled from parts. Not this machine's, and
    #: not a person: a test for a leak may not be the leak.
    HOSTILE = f"C:\\{WIN_ROOT}\\{FAKE}\\notes\\finding.md"

    def test_the_hostile_value_really_did_carry_the_name(self) -> None:
        """The other half of the pin: without it the cases below could pass on
        a fixture that never held an account name in the first place."""
        self.assertIn(FAKE, self.HOSTILE)
        self.assertNotIn(MARK, self.HOSTILE)

    def test_a_summary_and_a_body_carrying_a_home_path_are_screened(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for payload in send_payloads(
                project,
                session,
                AGENT_A,
                summary=f"finding in {self.HOSTILE}",
                message=f"the file is {self.HOSTILE}",
            ):
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)
            for relpath in (AUDIT_RELPATH, QUEUE_RELPATH):
                raw = project.joinpath(*relpath).read_bytes()
                self.assertNotIn(FAKE.encode("utf-8"), raw, f"{relpath[-1]} carries a name")
            record = audit_records(project)[0]
            self.assertIn(MARK, record["description"])
            self.assertIn(MARK, record["prompt_head"])
            self.assertIn("finding.md", record["prompt_head"], "the field recorded nothing")

    def test_marked_private_content_never_reaches_either_log(self) -> None:
        """The private marker is dropped before a line becomes bytes (R10)."""
        secret = "kept-out-of-the-record"  # keel-leak: ignore - invented value, asserted to stay out of the record
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for payload in send_payloads(
                project,
                session,
                AGENT_A,
                message=f"before <keel-private>{secret}</keel-private> after",
            ):
                run_hook("capture", payload, project, root)
            for relpath in (AUDIT_RELPATH, QUEUE_RELPATH):
                raw = project.joinpath(*relpath).read_bytes()
                self.assertNotIn(secret.encode("utf-8"), raw)


class TestTheRegistrationReachesTheTool(unittest.TestCase):
    """A matcher nothing subscribes to is a matcher that never fires.

    The capture registrations are what decide whether any of the above ever
    runs in the field, so the subscription is pinned here beside the matcher
    it feeds - and pinned through the GENERATOR, because hooks.json is
    generated and a hand-edit would not survive (R13).
    """

    def test_the_capture_rows_watch_the_message_tool(self) -> None:
        document = keel_gen_hooks.build_document()["hooks"]
        for event in ("PreToolUse", "PostToolUse"):
            with self.subTest(event=event):
                matchers = [group.get("matcher") or "" for group in document[event]]
                self.assertTrue(
                    any(MESSAGE_TOOL in matcher.split("|") for matcher in matchers),
                    f"{event} does not subscribe to {MESSAGE_TOOL}",
                )

    def test_the_delegation_tools_are_still_watched(self) -> None:
        """The wider subscription is an ADDITION: nothing stopped being seen."""
        document = keel_gen_hooks.build_document()["hooks"]
        for event in ("PreToolUse", "PostToolUse"):
            matchers = [group.get("matcher") or "" for group in document[event]]
            for tool in keel_capture.DELEGATION_TOOLS:
                with self.subTest(event=event, tool=tool):
                    self.assertTrue(
                        any(tool in matcher.split("|") for matcher in matchers)
                    )

    def test_the_committed_document_matches_the_generator(self) -> None:
        self.assertEqual(keel_gen_hooks.verify(), [])

    def test_the_matcher_names_the_tool_the_capture_module_reads(self) -> None:
        """The one place the two sides could drift: a registration for a tool
        the module ignores records nothing, and a module reading a tool
        nothing subscribes to never runs."""
        for tool in keel_capture.MESSAGE_TOOLS:
            with self.subTest(tool=tool):
                self.assertIn(tool, keel_gen_hooks.HANDOFF_MATCHER.split("|"))


if __name__ == "__main__":
    unittest.main()
