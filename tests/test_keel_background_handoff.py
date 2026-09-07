#!/usr/bin/env python3
"""T323 - a background delegation stays open until its stop arrives.

Contract
--------
Reads   : ``hooks/keel_capture.py`` (imported) for the CAPTURE side, and
          ``scripts/keel_orchestration_dashboard.py`` as source text only for
          the READ side - ``pairEvents``/``computeStates`` and everything
          they close over (``ts``, ``actsFor``, ``reviewFor``, ``winIdx``, the
          state ``let``s) are extracted verbatim and run under Node, fed
          entirely synthetic event lists, the same house idiom
          ``tests/test_keel_dashboard_t322.py`` uses for this file's pure
          JS. No case here reads this repository's own audit log.
Emits   : unittest results only.
Writes  : nothing outside temporary directories/scripts it creates and
          removes.

What this pins
---------------
THE DEFECT (owner watched it live, 2026-08-25): a BACKGROUND dispatch's
``handoff_end`` is written at launch-return, seconds after ``handoff_start``,
whatever the agent's real runtime later turns out to be - the board's old
read inferred "background" from that GAP being short (``BG_MS``/
``BG_LAUNCH_MS`` = 5000ms), so a background acknowledgment that took longer
than 5s to arrive (T182 measured 8s once already) was read as a FOREGROUND
pair that closed the instant it opened, and the agent vanished from "working
now" for its entire real runtime.

THE FIX, pinned both sides:

* CAPTURE (``hooks/keel_capture.py``): the close half's own ``background``
  field (``HANDOFF_BACKGROUND_KEY``) answers from the launch RESULT's own
  ``status`` - ``async_launched`` in every background acknowledgment
  measured, ``completed`` in every foreground return measured - a
  STRUCTURAL fact about the result's shape, not a timing guess. Three
  values, the same idiom as ``launch_ack`` (T138): ``null`` on the open half
  and wherever nothing readable exists, ``true``/``false`` only where a
  readable status was actually looked at.
* READ (``scripts/keel_orchestration_dashboard.py``'s ``computeStates``):
  a handoff whose close half carries ``background: true`` reads as
  BACKGROUND regardless of how long the launch/return gap was, so a slow
  acknowledgment is never misread as a finished foreground return; a close
  half whose ``background`` is not a boolean (older records, written before
  the field existed) still falls back to the timing gap, so nothing already
  on disk stops pairing. THE GUARD: the field, when boolean, is trusted
  EITHER WAY - a ``background: false`` (foreground return) is not overridden
  by a short gap either, though no real payload is expected to produce that
  combination.

BOTH DIRECTIONS, PER THE TASK:

* a background-marked end (``background: true``) with NO ``subagent_stop``
  yet -> the agent renders WORKING (``a.working`` true, ``a.background``
  true), counted in "working now" (``computeStates``'s ``anyWorking``/the
  per-agent ``a.working`` the page sums as ``s-active``) - even when the
  launch/return gap was minutes, not milliseconds (the exact shape T182
  measured and this fix targets).
* the SAME pair, with a later ``subagent_stop`` naming the launched agent
  id -> the delegation closes (``a.stop`` set, ``a.working`` false) exactly
  as a background pair always closed once its stop existed - the fix touches
  ONLY how "background" is decided, never the stop-matching phase already
  in ``computeStates``.
* a FOREGROUND ``handoff_end`` (no background mark, i.e. ``background``
  either ``false`` or absent as pre-T323 records are) -> finished
  immediately, no regression: this is the untouched path every existing
  hand-off test already covers, pinned again here for completeness beside
  the new field.

GUARDS: this task does not touch ``hooks/keel_stop.py`` (T182's stop gate,
whose in-flight race is documented in
``.keel/knowledge/the-inflight-check-races-the-async-capture.md``) - the
capture and read changes here leave the stop gate's own matcher and
``BG_LAUNCH_MS`` untouched, and this file asserts nothing about it.

Failure policy
--------------
FAIL-CLOSED: if ``node`` cannot be found, the Node-backed cases fail rather
than skip.

Constraints
-----------
Python 3.10+ standard library, plus a ``node`` binary on PATH.
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402

PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
SOURCE = PAGE.read_text(encoding="utf-8")
NODE = shutil.which("node")

BG_FIELD = "background"


def iso(seconds_ago: float) -> str:
    """A timestamp in keel's own spelling, offset into the past - the real
    clock, the same idiom ``tests/test_keel_rejected_launch.py`` uses, since
    ``computeStates`` reads ``Date.now()`` directly rather than taking an
    explicit ``now`` the way the T322/T324 chip functions do."""
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CAPTURE SIDE: hooks/keel_capture.py, imported directly.
# ---------------------------------------------------------------------------

#: The real shape a BACKGROUND launch acknowledgment carries, per the module
#: contract's own census (234 of 234, then 249 of 249): a mapping naming an
#: agent id and this ``status``.
BACKGROUND_RESULT = {
    "status": "async_launched",
    "agentId": "a8a960cff0a7d45",
    "resolvedModel": "invented-t323-model",
}

#: The real shape a FOREGROUND (completed) launch return carries, per the
#: same census (6, then 19).
FOREGROUND_RESULT = {
    "status": "completed",
    "agentId": "a8a960cff0a7d45",
    "resolvedModel": "invented-t323-model",
}


def _capture_event(half: str, response: Any = None, *, carried: bool = True) -> Any:
    raw: dict[str, Any] = {
        "hook_event_name": half,
        "tool_input": {"subagent_type": "keel:invented-t323-agent"},
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


class TestTheCaptureSideDetectsTheRealPayloadShape(unittest.TestCase):
    """``launch_backgrounded``: the structural signal, on the measured shapes."""

    def test_a_background_acknowledgment_answers_true(self) -> None:
        self.assertIs(
            keel_capture.launch_backgrounded(
                _capture_event("PostToolUse", BACKGROUND_RESULT)
            ),
            True,
        )

    def test_a_completed_foreground_return_answers_false(self) -> None:
        """THE CASE THIS FEATURE MUST NOT TRIGGER ON: a foreground return is
        a mapping too, and carries the same keys otherwise - only its
        ``status`` differs."""
        self.assertIs(
            keel_capture.launch_backgrounded(
                _capture_event("PostToolUse", FOREGROUND_RESULT)
            ),
            False,
        )

    def test_a_rejection_answers_none_not_false(self) -> None:
        """Not a mapping at all - "nothing readable" is not "foreground"."""
        self.assertIsNone(
            keel_capture.launch_backgrounded(
                _capture_event("PostToolUse", "User rejected tool use")
            )
        )

    def test_an_unrecognised_status_answers_false(self) -> None:
        """A readable status naming something other than the one measured
        background value is a foreground-shaped answer, not an unknown."""
        self.assertIs(
            keel_capture.launch_backgrounded(
                _capture_event(
                    "PostToolUse",
                    {"status": "something_unmeasured", "agentId": "x"},
                )
            ),
            False,
        )

    def test_the_open_half_answers_none_even_handed_a_result(self) -> None:
        self.assertIsNone(
            keel_capture.launch_backgrounded(
                _capture_event("PreToolUse", BACKGROUND_RESULT)
            )
        )

    def test_nothing_readable_answers_none(self) -> None:
        self.assertIsNone(
            keel_capture.launch_backgrounded(
                _capture_event("PostToolUse", carried=False)
            )
        )
        for response in (None, "", ["a", "list"], 17, True):
            with self.subTest(response=response):
                self.assertIsNone(
                    keel_capture.launch_backgrounded(
                        _capture_event("PostToolUse", response)
                    )
                )


class TestTheRecordCarriesTheFieldOnBothHalves(unittest.TestCase):
    """``handoff_record`` - additive, the same idiom ``launch_ack`` uses."""

    def record(self, half: str, response: Any = None, *, carried: bool = True) -> dict:
        raw: dict[str, Any] = {
            "hook_event_name": half,
            "tool_use_id": "toolu_t323_1",
            "tool_input": {
                "subagent_type": "keel:invented-t323-agent",
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

    def test_a_background_close_half_carries_true(self) -> None:
        self.assertIs(self.record("PostToolUse", BACKGROUND_RESULT)[BG_FIELD], True)

    def test_a_foreground_close_half_carries_false(self) -> None:
        self.assertIs(self.record("PostToolUse", FOREGROUND_RESULT)[BG_FIELD], False)

    def test_the_open_half_carries_the_key_and_a_null(self) -> None:
        opened = self.record("PreToolUse", carried=False)
        self.assertIn(BG_FIELD, opened)
        self.assertIsNone(opened[BG_FIELD])

    def test_the_field_is_additive_only(self) -> None:
        """The record a foreground return writes carries exactly the keys a
        background acknowledgment writes; the two differ only in the fields
        the RESULT itself differs on."""
        bg = self.record("PostToolUse", BACKGROUND_RESULT)
        fg = self.record("PostToolUse", FOREGROUND_RESULT)
        self.assertEqual(sorted(bg), sorted(fg))
        differing = [k for k in bg if bg[k] != fg[k]]
        self.assertEqual(sorted(differing), sorted([BG_FIELD]))

    def test_the_wire_event_and_kind_are_unchanged(self) -> None:
        """No new ``event`` value, no repurposed ``handoff_kind`` - an
        existing reader that never heard of ``background`` still counts the
        pair exactly as before (T323's own accept criterion)."""
        rec = self.record("PostToolUse", BACKGROUND_RESULT)
        self.assertEqual(rec["event"], "handoff_end")
        self.assertEqual(rec["handoff_kind"], "launch")


# ---------------------------------------------------------------------------
# READ SIDE: scripts/keel_orchestration_dashboard.py, extracted and run under
# Node - the same verbatim-extraction idiom as test_keel_dashboard_t322.py.
# ---------------------------------------------------------------------------


def _extract_line(prefix: str, label: str) -> str:
    for line in SOURCE.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"could not extract {label!r} from the served page")


def _extract_block(pattern: str, label: str) -> str:
    m = re.search(pattern, SOURCE, re.S)
    if not m:
        raise AssertionError(f"could not extract {label!r} from the served page")
    return m.group(0)


_PAIR_EVENTS = _extract_block(
    r"function pairEvents\(events\)\{.*?\n\}\n", "pairEvents"
)
#: ``computeStates`` and everything it closes over (``ts``, ``actsFor``,
#: ``reviewFor``, ``winIdx``, the state ``let``s, ``BG_MS``'s own consumer)
#: sit in ONE contiguous run of source between ``pairEvents`` and the ring
#: geometry that follows - extracted whole rather than picked apart, so a
#: drift in any dependency must fail this file rather than be silently
#: masked by a private reimplementation.
_STATE_BLOCK = _extract_block(
    r"const nodeEls=new Map\(\); let edgeSig=\"\";.*?\nfunction computeStates\(agents\)\{.*?\n  return anyWorking;\n\}\n",
    "the T323 computeStates block and its dependencies",
)
_BG_MS = _extract_line("const BG_MS=", "BG_MS")
_ABANDON_MS = _extract_line("const ABANDON_MS=", "ABANDON_MS")
_LIVENESS_MS = _extract_line("const LIVENESS_MS=", "LIVENESS_MS")

HARNESS_PRELUDE = "\n".join([_ABANDON_MS, _BG_MS, _LIVENESS_MS, _PAIR_EVENTS, _STATE_BLOCK])


class TestTheExtractionFoundEveryPiece(unittest.TestCase):
    def test_every_helper_is_present(self) -> None:
        for name in ("function pairEvents", "function computeStates", "function actsFor"):
            self.assertIn(name, HARNESS_PRELUDE)
        self.assertIn("BG_MS", HARNESS_PRELUDE)


def run_node(script_body: str) -> dict[str, Any]:
    """Runs ``HARNESS_PRELUDE`` plus ``script_body`` under Node, returning the
    JSON the script prints on its last line."""
    if NODE is None:
        raise unittest.SkipTest("node is not on PATH")  # pragma: no cover
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "probe.js"
        script.write_text(HARNESS_PRELUDE + "\n" + script_body, encoding="utf-8")
        proc = subprocess.run(
            [NODE, str(script)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode != 0:
            raise AssertionError(f"node failed: {proc.stderr}")
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        return json.loads(lines[-1])


def launch_half(event: str, uid: str, *, seconds_ago: float, **extra: Any) -> dict[str, Any]:
    return {
        "v": 1,
        "ts": iso(seconds_ago),
        "event": event,
        "handoff_kind": "launch",
        "session": "s-1",
        "session_id": "s-1",
        "tool_use_id": uid,
        "agent_id": extra.pop("agent_id", None),
        "subagent_type": "keel:t323-agent",
        "description": "T323 delegation",
        **extra,
    }


def stop_half(*, seconds_ago: float, agent_type: str = "keel:t323-agent",
              agent_id: str = "a8a960cff0a7d45") -> dict[str, Any]:
    return {
        "v": 1,
        "ts": iso(seconds_ago),
        "event": "subagent_stop",
        "session": "s-1",
        "session_id": "s-1",
        "agent_type": agent_type,
        "agent_id": agent_id,
    }


def evaluate(events: list[dict[str, Any]], stops: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs ``pairEvents``+``computeStates`` on this fixture exactly as the
    live page's ``tick()`` does (``lastStops`` assigned before the call,
    ``lastActs``/``lastReviews``/``lastSessionStarts`` left empty - no
    fixture here needs them), and reports the one agent's resulting flags."""
    script = f"""
lastStops={json.dumps(stops)};
lastActs=[];lastReviews=[];lastSessionStarts=[];
const events={json.dumps(events)};
const agents=pairEvents(events);
computeStates(agents);
const a=agents.find(x=>x.start);
console.log(JSON.stringify({{
  background:a.background,working:a.working,hasStop:!!a.stop,
  abandoned:a.abandoned
}}));
"""
    return run_node(script)


class TestABackgroundMarkedEndStaysOpenUntilItsStop(unittest.TestCase):
    """THE DEFECT, reproduced and fixed: a background ``handoff_end`` whose
    launch/return gap is minutes, not milliseconds - the exact shape a
    timing-only reader misreads as a finished foreground pair."""

    def test_no_stop_yet_renders_working(self) -> None:
        events = [
            launch_half("handoff_start", "bg1", seconds_ago=300),
            launch_half(
                "handoff_end", "bg1", seconds_ago=30,  # 270s gap: over BG_MS by far,
                # comfortably inside LIVENESS_MS (600s) measured from launch
                agent_id="a8a960cff0a7d45", **{BG_FIELD: True},
            ),
        ]
        result = evaluate(events, [])
        self.assertIs(result["background"], True)
        self.assertIs(result["working"], True)
        self.assertIs(result["hasStop"], False)

    def test_a_later_stop_closes_it(self) -> None:
        events = [
            launch_half("handoff_start", "bg2", seconds_ago=600),
            launch_half(
                "handoff_end", "bg2", seconds_ago=590,
                agent_id="a8a960cff0a7d45", **{BG_FIELD: True},
            ),
        ]
        stops = [stop_half(seconds_ago=5)]
        result = evaluate(events, stops)
        self.assertIs(result["background"], True)
        self.assertIs(result["hasStop"], True)
        self.assertIs(result["working"], False)

    def test_a_foreground_end_is_finished_immediately_no_regression(self) -> None:
        """The untouched path: ``background: false`` (a real foreground
        return, per T323's capture-side census) closes exactly as it always
        did, whatever the gap."""
        events = [
            launch_half("handoff_start", "fg1", seconds_ago=600),
            launch_half(
                "handoff_end", "fg1", seconds_ago=590,
                agent_id="a8a960cff0a7d45", **{BG_FIELD: False},
            ),
        ]
        result = evaluate(events, [])
        self.assertIs(result["background"], False)
        self.assertIs(result["working"], False)

    def test_an_older_record_with_no_field_falls_back_to_the_timing_gap(self) -> None:
        """Backward compatible: a close half written before T323 carries no
        ``background`` key at all, and a short gap still reads as background
        exactly as it did before this fix."""
        events = [
            launch_half("handoff_start", "old1", seconds_ago=10),
            launch_half("handoff_end", "old1", seconds_ago=8, agent_id="a8a960cff0a7d45"),
        ]
        result = evaluate(events, [])
        self.assertIs(result["background"], True)
        self.assertIs(result["working"], True)

    def test_an_older_foreground_pair_still_reads_as_finished(self) -> None:
        """Same backward-compat path, the other direction: an old record
        with a long gap and no field falls back to the timing rule and reads
        foreground, unchanged from before this fix."""
        events = [
            launch_half("handoff_start", "old2", seconds_ago=600),
            launch_half("handoff_end", "old2", seconds_ago=590, agent_id="a8a960cff0a7d45"),
        ]
        result = evaluate(events, [])
        self.assertIs(result["background"], False)
        self.assertIs(result["working"], False)


if __name__ == "__main__":
    unittest.main()
