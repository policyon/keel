#!/usr/bin/env python3
"""A rejected launch must not work forever (T138).

Contract
--------
Reads   : ``hooks/keel_capture.py`` and
          ``scripts/keel_orchestration_dashboard.py``, imported. NOTHING
          ELSE - and emphatically not this project's own
          ``.keel/audit/keel-audit.jsonl``, whose four real ghosts are what
          this feature was built for and are therefore exactly what a test
          for it may not premise on. Every line asserted about below was
          written by this file, into a temporary directory it removes.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

What this file is for
---------------------
The page has one reading of an unpaired ``handoff_start``: the agent is
WORKING, until two hours of ABANDON_MS say otherwise. That is right for a
live background agent and wrong for a launch that was rejected or killed,
which never returns and never stops - the owner watched four such cards read
"working - stalled?" beside the real ones on 2026-08-13.

TWO HALVES, MEASURED SEPARATELY, because the harness gave them different
evidence:

* CAPTURE, for the future: ``launch_ack`` says whether the launch tool's
  result was an acknowledgment AT ALL. The discriminator is the result's
  SHAPE, not a missing model - 268 of 268 real acknowledgments are mappings
  carrying both an agent id and a ``resolvedModel``, the 4 rejections are the
  bare string ``User rejected tool use``.
* READ TIME, for the four that already exist: a rejected call fires no
  PostToolUse in this harness, so those four have NO close half at all and no
  marker can reach them. What the log does hold is that the same session
  dispatched the same task to the same agent again minutes later, and a
  delegation that was re-dispatched is not still working.

BOTH DIRECTIONS ARE PINNED, and the second direction is the one that matters:
a rule that withheld a REAL agent would take a working delegation off the
page, which is worse than the ghost it was written to remove. So every case
that closes something is answered by a case that must not close - a real
background acknowledgment, a resume, a live unpaired launch with no successor,
TWO CONCURRENT LAUNCHES OF THE SAME DELEGATION (this project dispatches
identical work in parallel, and mere repetition may never supersede), a
launch whose identity has a blank in it, and a close half whose ``launch_ack``
is null rather than false.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import datetime
import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_orchestration_dashboard as adopted  # noqa: E402

#: The added key's wire name, spelled out rather than imported: this file
#: exists to notice the capture side and its reader drifting apart, and a
#: guard that imports the name it checks cannot see that name move.
ACK_FIELD = "launch_ack"

#: The result a REJECTED launch carries, verbatim as the census measured it
#: in all 4 of 4 - the one string this feature turns on.
REJECTION = "User rejected tool use"

#: A structured acknowledgment in the measured shape: a mapping carrying an
#: agent id and a resolved model, as all 268 of 268 real results do.
ACK_AGENT_ID = "a8a960cff0a7d45"
ACKNOWLEDGMENT = {
    "status": "async_launched",
    "agentId": ACK_AGENT_ID,
    "resolvedModel": "invented-t138-model",
}


def iso(seconds_ago: float) -> str:
    """A timestamp in keel's own spelling, offset into the past."""
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def project(lines: list[dict[str, Any]]) -> tempfile.TemporaryDirectory:
    """An adopted project whose audit log holds exactly these lines."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".keel" / "audit").mkdir(parents=True)
    (root / ".keel" / "plans").mkdir(parents=True)
    (root / ".keel" / "audit" / "keel-audit.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    (root / ".keel" / "plans" / "keel-plan-abcd1234.md").write_text(
        "# Session plan — abcd1234\n\n- [x] T1 done\n  Route: x\n  Accept: y\n",
        encoding="utf-8",
    )
    return tmp


def served(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """What the data layer would serve for a log holding exactly these lines."""
    with project(lines) as root:
        adopted.ROOT = root
        return adopted.read_state()


def launch_half(
    event: str,
    uid: str,
    *,
    seconds_ago: float,
    description: str,
    session: str = "s-1",
    subagent_type: str = "keel:invented-t138-agent",
    **extra: Any,
) -> dict[str, Any]:
    """One half of a LAUNCH hand-off, in the shape capture writes today."""
    return dict(
        {
            "v": 1,
            "ts": iso(seconds_ago),
            "event": event,
            "handoff_kind": "launch",
            "session": session,
            "tool_use_id": uid,
            "agent_id": None,
            "subagent_type": subagent_type,
            "description": description,
        },
        **extra,
    )


def resume_half(
    event: str, uid: str, *, seconds_ago: float, agent_id: str
) -> dict[str, Any]:
    """One half of a RESUME hand-off: the target's id on BOTH halves (T124)."""
    return {
        "v": 1,
        "ts": iso(seconds_ago),
        "event": event,
        "handoff_kind": "resume",
        "session": "s-1",
        "tool_use_id": uid,
        "agent_id": agent_id,
        "subagent_type": None,
        "description": "a resumed delegation",
    }


def descriptions(state: dict[str, Any], event: str) -> list[str]:
    """The descriptions of every served hand-off line of one half."""
    return [e.get("description") for e in state["events"] if e.get("event") == event]


class TestTheResultsShapeIsWhatIsRead(unittest.TestCase):
    """``launch_acknowledged``: three values, and what earns each one.

    Every payload here is written in this method - no case reads a real
    result, a real log or a real agent definition.
    """

    def event(self, half: str, response: Any = None, *, carried: bool = True) -> Any:
        raw: dict[str, Any] = {
            "hook_event_name": half,
            "tool_input": {"subagent_type": "keel:invented-t138-agent"},
        }
        if carried:
            raw["tool_response"] = response
        return keel_events.KeelEvent(
            kind="post_tool",
            cwd=REPO_ROOT,
            session_id=uuid.uuid4().hex,
            tool_name="Task",
            raw=raw,
        )

    def test_a_structured_acknowledgment_answers_true(self) -> None:
        self.assertIs(
            keel_capture.launch_acknowledged(self.event("PostToolUse", ACKNOWLEDGMENT)),
            True,
        )

    def test_the_measured_rejection_answers_false(self) -> None:
        """The one shape this feature exists for: a result that is not a
        mapping and names no agent."""
        self.assertIs(
            keel_capture.launch_acknowledged(self.event("PostToolUse", REJECTION)),
            False,
        )

    def test_a_mapping_answers_true_even_carrying_neither_id_nor_model(self) -> None:
        """The SHAPE is the discriminator, not the model: a harness that stops
        resolving a model for a launch that ran must not have it read as a
        rejection."""
        self.assertIs(
            keel_capture.launch_acknowledged(
                self.event("PostToolUse", {"status": "async_launched"})
            ),
            True,
        )

    def test_a_text_result_that_names_an_agent_answers_true(self) -> None:
        """Not a mapping, but it named an agent - so it acknowledged a
        launch, and the same text read ``launch_agent_id`` already does
        answers for it."""
        self.assertIs(
            keel_capture.launch_acknowledged(
                self.event("PostToolUse", f"launched: agent_id={ACK_AGENT_ID}")
            ),
            True,
        )

    def test_the_open_half_answers_none_even_handed_a_result(self) -> None:
        """A resolution belongs to the moment the tool returned; the half is
        checked rather than assumed empty, as ``result_model`` checks it."""
        self.assertIsNone(
            keel_capture.launch_acknowledged(self.event("PreToolUse", REJECTION))
        )

    def test_nothing_readable_answers_none_rather_than_false(self) -> None:
        """THE EXPENSIVE MISTAKE, refused: "I was shown nothing" is not "the
        launch did not take". A harness build that stopped passing a result to
        PostToolUse would otherwise mark every launch in the project dead."""
        self.assertIsNone(
            keel_capture.launch_acknowledged(self.event("PostToolUse", carried=False))
        )
        for response in (None, "", "   ", ["a", "list"], 17, True):
            with self.subTest(response=response):
                self.assertIsNone(
                    keel_capture.launch_acknowledged(
                        self.event("PostToolUse", response)
                    )
                )


class TestTheRecordCarriesTheAnswerOnBothHalves(unittest.TestCase):
    """The field as ``handoff_record`` writes it - additive, on both halves."""

    def record(self, half: str, response: Any = None, *, carried: bool = True) -> dict:
        raw: dict[str, Any] = {
            "hook_event_name": half,
            "tool_use_id": "toolu_t138_1",
            "tool_input": {
                "subagent_type": "keel:invented-t138-agent",
                "description": "a delegation",
                "prompt": "TASK: do the thing",
            },
        }
        if carried:
            raw["tool_response"] = response
        return keel_capture.handoff_record(
            keel_events.KeelEvent(
                kind="post_tool",
                cwd=REPO_ROOT,
                session_id="s-1",
                tool_name="Task",
                raw=raw,
            )
        )

    def test_a_rejected_launch_closes_with_a_false(self) -> None:
        self.assertIs(self.record("PostToolUse", REJECTION)[ACK_FIELD], False)

    def test_an_acknowledged_launch_closes_with_a_true(self) -> None:
        self.assertIs(self.record("PostToolUse", ACKNOWLEDGMENT)[ACK_FIELD], True)

    def test_the_open_half_carries_the_key_and_a_null(self) -> None:
        """Present, not omitted: a null says "this half's source could not
        know", an absent key says "this line predates the field"."""
        opened = self.record("PreToolUse", carried=False)
        self.assertIn(ACK_FIELD, opened)
        self.assertIsNone(opened[ACK_FIELD])

    def test_the_field_is_added_and_nothing_else_moves(self) -> None:
        """ADDITIVE ONLY: the record a rejection writes carries exactly the
        keys an acknowledgment writes, and the two differ in this key alone."""
        rejected = self.record("PostToolUse", REJECTION)
        acknowledged = self.record("PostToolUse", ACKNOWLEDGMENT)
        self.assertEqual(sorted(rejected), sorted(acknowledged))
        differing = [k for k in acknowledged if acknowledged[k] != rejected[k]]
        self.assertEqual(
            sorted(differing), sorted([ACK_FIELD, "background", "agent_id", "model"])
        )


class TestTheGhostsAreWithheldFromTheServedCopy(unittest.TestCase):
    """The read-time rule, on logs this file writes."""

    def test_a_relaunched_delegation_that_never_closed_is_withheld(self) -> None:
        """The measured shape of the four: an open half with no close half at
        all, and the same session dispatching the same task again later."""
        lines = [
            launch_half("handoff_start", "ghost", seconds_ago=900, description="T1"),
            launch_half("handoff_start", "real", seconds_ago=300, description="T1"),
            launch_half(
                "handoff_end",
                "real",
                seconds_ago=297,
                description="T1",
                agent_id=ACK_AGENT_ID,
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 1)
        self.assertEqual(descriptions(state, "handoff_start"), ["T1"])
        self.assertEqual(descriptions(state, "handoff_end"), ["T1"])
        self.assertEqual(
            [e["tool_use_id"] for e in state["events"]], ["real", "real"]
        )

    def test_a_close_half_saying_it_never_took_withholds_both_halves(self) -> None:
        """The capture-side marker, honoured by the reader: no relaunch is
        needed when the record says outright that the tool acknowledged
        nothing."""
        lines = [
            launch_half("handoff_start", "x", seconds_ago=120, description="T2"),
            launch_half(
                "handoff_end",
                "x",
                seconds_ago=119,
                description="T2",
                **{ACK_FIELD: False},
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 1)
        self.assertEqual(state["events"], [])

    def test_a_live_unpaired_launch_with_no_successor_is_served(self) -> None:
        """THE CASE THAT MUST NOT CLOSE. A background agent working right now
        looks exactly like a ghost except for the one thing that is evidence:
        nothing re-dispatched it."""
        lines = [
            launch_half("handoff_start", "live", seconds_ago=60, description="T3"),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(descriptions(state, "handoff_start"), ["T3"])

    def test_two_concurrent_identical_launches_are_both_served(self) -> None:
        """THE CASE THE FIRST FORM OF THIS RULE GOT WRONG. This project
        dispatches identical work in parallel, so an earlier open with a later
        twin is NOT evidence of anything - while neither twin has closed, both
        may be running this second. Repetition does not supersede; a successor
        that was itself acknowledged does."""
        lines = [
            launch_half("handoff_start", "first", seconds_ago=120, description="TC"),
            launch_half("handoff_start", "second", seconds_ago=110, description="TC"),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(state["keel"]["withheld_launch_ids"], [])
        self.assertEqual(
            [e["tool_use_id"] for e in state["events"]], ["first", "second"]
        )

    def test_a_ghost_beside_a_live_twin_withholds_only_the_ghost(self) -> None:
        """The three shapes at once: a superseded ghost, the relaunch that
        closed and superseded it, and a THIRD attempt still running. Only the
        ghost may go."""
        lines = [
            launch_half("handoff_start", "ghost", seconds_ago=900, description="TD"),
            launch_half("handoff_start", "done", seconds_ago=600, description="TD"),
            launch_half(
                "handoff_end",
                "done",
                seconds_ago=597,
                description="TD",
                agent_id=ACK_AGENT_ID,
            ),
            launch_half("handoff_start", "live", seconds_ago=60, description="TD"),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launch_ids"], ["ghost"])
        self.assertEqual(
            [e["tool_use_id"] for e in state["events"]], ["done", "done", "live"]
        )

    def test_launches_missing_an_identity_part_never_supersede(self) -> None:
        """Two distinct delegations whose type and description are both absent
        are not one delegation attempted twice: an identity with a blank in it
        is no identity, and blanks may not match each other."""
        lines = [
            {"v": 1, "ts": iso(900), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "n1", "subagent_type": None, "description": None},
            {"v": 1, "ts": iso(300), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "n2", "subagent_type": None, "description": None},
            {"v": 1, "ts": iso(297), "event": "handoff_end", "session": "s-1",
             "tool_use_id": "n2", "subagent_type": None, "description": None,
             "agent_id": ACK_AGENT_ID},
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual([e["tool_use_id"] for e in state["events"]], ["n1", "n2", "n2"])

    def test_a_real_background_acknowledgment_pair_is_served(self) -> None:
        """A pair whose close half carries an agent id is a launch that took -
        measured 268 of 268 - and no rule here may touch it, even when a later
        launch repeats its description."""
        lines = [
            launch_half("handoff_start", "bg", seconds_ago=600, description="T4"),
            launch_half(
                "handoff_end",
                "bg",
                seconds_ago=597,
                description="T4",
                agent_id=ACK_AGENT_ID,
                **{ACK_FIELD: True},
            ),
            launch_half("handoff_start", "bg2", seconds_ago=120, description="T4"),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(descriptions(state, "handoff_start"), ["T4", "T4"])
        self.assertEqual(descriptions(state, "handoff_end"), ["T4"])

    def test_a_resume_pair_is_served_untouched(self) -> None:
        """A resume carries its target's id on BOTH halves and is not a launch
        (T124); the rule skips the kind outright, so even a repeated resume
        keeps every line."""
        lines = [
            resume_half("handoff_start", "r1", seconds_ago=600, agent_id=ACK_AGENT_ID),
            resume_half("handoff_end", "r1", seconds_ago=598, agent_id=ACK_AGENT_ID),
            resume_half("handoff_start", "r2", seconds_ago=90, agent_id=ACK_AGENT_ID),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(len(state["events"]), 3)

    def test_an_unknown_ack_is_never_read_as_a_rejection(self) -> None:
        """``null`` means nothing could be judged, and a reader may not turn
        that into "it never took" any more than the writer may."""
        lines = [
            launch_half("handoff_start", "u", seconds_ago=120, description="T5"),
            launch_half(
                "handoff_end",
                "u",
                seconds_ago=119,
                description="T5",
                **{ACK_FIELD: None},
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(len(state["events"]), 2)

    def test_older_lines_that_never_heard_of_the_key_still_pair(self) -> None:
        """Lines written before ``launch_ack`` existed carry neither the key
        nor a rejection, and are served exactly as before."""
        lines = [
            {"v": 1, "ts": iso(400), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "old", "subagent_type": "keel:x", "description": "T6"},
            {"v": 1, "ts": iso(397), "event": "handoff_end", "session": "s-1",
             "tool_use_id": "old", "subagent_type": "keel:x", "description": "T6"},
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(len(state["events"]), 2)

    def test_a_repeat_in_another_session_closes_nothing(self) -> None:
        """Scoped to one session: a new session repeating a task says nothing
        about an agent an older session may still have running."""
        lines = [
            launch_half(
                "handoff_start", "a", seconds_ago=900, description="T7", session="s-1"
            ),
            launch_half(
                "handoff_start", "b", seconds_ago=120, description="T7", session="s-2"
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 0)
        self.assertEqual(len(state["events"]), 2)

    def test_nothing_but_hand_off_lines_is_ever_withheld(self) -> None:
        """The withholding is keyed on the hand-off halves alone: an activity
        line, a stop and a gate event are untouched whatever id they carry."""
        lines = [
            launch_half("handoff_start", "ghost", seconds_ago=900, description="T8"),
            {"v": 1, "ts": iso(880), "event": "activity", "session": "s-1",
             "agent_type": "keel:invented-t138-agent", "tool": "Bash",
             "detail": "ran something", "tool_use_id": "ghost"},
            {"v": 1, "ts": iso(870), "event": "subagent_stop", "session": "s-1",
             "agent_type": "keel:invented-t138-agent", "agent_id": ACK_AGENT_ID},
            launch_half("handoff_start", "real", seconds_ago=300, description="T8"),
            launch_half(
                "handoff_end",
                "real",
                seconds_ago=297,
                description="T8",
                agent_id=ACK_AGENT_ID,
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 1)
        self.assertEqual(
            [e["event"] for e in state["events"]],
            ["activity", "subagent_stop", "handoff_start", "handoff_end"],
        )


class TestTheRuleIsDecidedOverTheWholeLog(unittest.TestCase):
    """The evidence may sit any distance from the ghost it closes."""

    def test_a_relaunch_beyond_the_served_window_still_closes_its_ghost(self) -> None:
        """The served copy is two last-400 windows; the never-took rule runs
        over every parsed line first, so a ghost cannot survive by having its
        successor far away in the file."""
        lines = [launch_half("handoff_start", "ghost", seconds_ago=9000, description="T9")]
        lines += [
            {"v": 1, "ts": iso(8000 - i), "event": "activity", "session": "s-1",
             "tool": "Bash", "detail": f"cmd {i}"}
            for i in range(500)
        ]
        lines += [
            launch_half("handoff_start", "real", seconds_ago=300, description="T9"),
            launch_half(
                "handoff_end",
                "real",
                seconds_ago=297,
                description="T9",
                agent_id=ACK_AGENT_ID,
            ),
        ]
        state = served(lines)
        self.assertEqual(state["keel"]["withheld_launches"], 1)
        self.assertNotIn("ghost", [e.get("tool_use_id") for e in state["events"]])
        self.assertEqual(descriptions(state, "handoff_start"), ["T9"])


class TestTheLogItselfIsNeverRewritten(unittest.TestCase):
    """Append-only means append-only: withholding is a property of the
    RESPONSE, and the bytes on disk are identical before and after."""

    def test_reading_a_ghost_leaves_the_file_byte_identical(self) -> None:
        lines = [
            launch_half("handoff_start", "ghost", seconds_ago=900, description="TA"),
            launch_half("handoff_start", "real", seconds_ago=300, description="TA"),
            launch_half(
                "handoff_end",
                "real",
                seconds_ago=297,
                description="TA",
                agent_id=ACK_AGENT_ID,
            ),
        ]
        with project(lines) as root:
            log = Path(root) / ".keel" / "audit" / "keel-audit.jsonl"
            before = log.read_bytes()
            adopted.ROOT = root
            state = adopted.read_state()
            self.assertEqual(state["keel"]["withheld_launches"], 1)
            self.assertEqual(log.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
