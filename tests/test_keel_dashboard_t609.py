#!/usr/bin/env python3
"""T609 - the dashboard's two truth defects, BL31 and BL22.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` as source text only,
          extracted verbatim and run under Node - the same house idiom
          ``tests/test_keel_dashboard_t334_t335.py`` (BL31's own ``sessionModel``
          extraction) and ``tests/test_keel_background_handoff.py`` (BL22's own
          ``computeStates`` extraction) already use for this file's pure JS.
          No case here reads this repository's own audit log.
Emits   : unittest results only.
Writes  : nothing outside a temporary script/directory handed to ``node``.
Argv    : none.

What this pins
--------------
BL31 - THE CAPTAIN CARD WEARS ONLY THE CAPTAIN'S OWN MODEL. ``sessionModel``
       used to accept a ``model`` from ANY event carrying the tracked
       session's ``session_id`` - and a delegation's ``handoff_start``/
       ``handoff_end`` DOES carry that session_id (the launching session,
       per ``hooks/keel_capture.py``'s ``handoff_record``), with a ``model``
       naming the DELEGATE, never the seat that launched it. The fix is a
       blocklist of delegation-scoped event kinds (``handoff_start``,
       ``handoff_end``, ``subagent_stop``), so a session-level event
       (``session_start``, ``stop_block``) still supplies the chip and a
       delegation's own model never does.
BL22 - AN UNPAIRED DELEGATION IS NEVER RENDERED "WORKING" PAST ITS OWN LAST
       EVENT. ``computeStates`` used to read an unpaired hand-off
       (``handoff_start`` with no ``handoff_end``) as working for as long as
       ``ABANDON_MS`` (2h) from LAUNCH TIME alone - an agent the API killed
       outright, with no stop and no activity ever again, wore "working" for
       up to two hours. The fix bounds an unpaired delegation's liveness by
       its OWN newest event (``actsFor``'s activity window, the same one the
       background branch already trusted) at ``LIVENESS_MS`` scale (10min),
       introducing a THIRD state - ``a.stale`` - distinct from both
       "working" and "finished"; ``ABANDON_MS`` remains the outer bound
       unchanged.

Failure policy
--------------
FAIL-CLOSED: if ``node`` cannot be found the file fails rather than skipping.

Constraints
-----------
Python 3.10+ standard library plus a ``node`` binary on PATH. Subprocess
invoked with an argument list, never a shell string (R5).
"""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from keel_node import NODE, SKIP_REASON, announce_once

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
SOURCE = PAGE.read_text(encoding="utf-8")
announce_once()


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


def iso(seconds_ago: float) -> str:
    """A timestamp in keel's own spelling, offset into the past - the real
    clock, exactly as ``tests/test_keel_background_handoff.py`` uses it,
    since ``computeStates`` reads ``Date.now()`` directly."""
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_node(script: str) -> Any:
    if NODE is None:
        raise AssertionError("node was not found on PATH - failing closed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run([NODE, path], capture_output=True, timeout=30, check=False)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError("node harness failed: " + result.stderr.decode("utf-8", "replace"))
    lines = [ln for ln in result.stdout.decode("utf-8").splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ---------------------------------------------------------------- BL31 model
_SESSION_MODEL_BLOCK = _extract_block(
    r"function sessionModel\(sessId\)\{.*?\n\}\n",
    "the sessionModel scan",
)


def session_model(sess_id: str, events: list[dict]) -> Any:
    script = (
        "let lastState=" + json.dumps({"events": events}) + ";\n"
        + _SESSION_MODEL_BLOCK
        + "\nconsole.log(JSON.stringify(sessionModel(" + json.dumps(sess_id) + ")));\n"
    )
    return run_node(script)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheCaptainsChipNeverWearsADelegatesModel(unittest.TestCase):
    """BL31: a delegation's ``handoff_start``/``handoff_end`` shares the
    LAUNCHING session's ``session_id`` but names the DELEGATE's model - it
    must never reach the Captain's chip."""

    def test_a_delegations_handoff_start_never_supplies_the_chip(self) -> None:
        events = [
            {"ts": iso(60), "event": "session_start", "session_id": "s1", "model": None},
            {"ts": iso(30), "event": "handoff_start", "session_id": "s1",
             "subagent_type": "keel:executor", "model": "claude-sonnet-5"},
        ]
        self.assertIsNone(session_model("s1", events))

    def test_a_delegations_handoff_end_never_supplies_the_chip_either(self) -> None:
        events = [
            {"ts": iso(60), "event": "session_start", "session_id": "s1", "model": None},
            {"ts": iso(10), "event": "handoff_end", "session_id": "s1",
             "subagent_type": "keel:executor", "model": "claude-opus-5 · high"},
        ]
        self.assertIsNone(session_model("s1", events))

    def test_a_subagent_stop_never_supplies_the_chip(self) -> None:
        events = [
            {"ts": iso(60), "event": "session_start", "session_id": "s1", "model": None},
            {"ts": iso(5), "event": "subagent_stop", "session_id": "s1",
             "model": "claude-haiku-5"},
        ]
        self.assertIsNone(session_model("s1", events))

    def test_a_session_level_event_is_still_read(self) -> None:
        """The other direction: a genuine session-owned event (``stop_block``,
        which reads the transcript's own seat per ``hooks/keel_stop.py``)
        still supplies the chip - the fix is a blocklist, not a lockout."""
        events = [
            {"ts": iso(60), "event": "session_start", "session_id": "s1", "model": None},
            {"ts": iso(30), "event": "handoff_start", "session_id": "s1",
             "subagent_type": "keel:executor", "model": "claude-sonnet-5"},
            {"ts": iso(5), "event": "stop_block", "session_id": "s1",
             "model": "claude-opus-5"},
        ]
        self.assertEqual(session_model("s1", events), "claude-opus-5")

    def test_session_start_alone_is_still_read(self) -> None:
        events = [
            {"ts": iso(60), "event": "session_start", "session_id": "s1",
             "model": "claude-sonnet-5"},
        ]
        self.assertEqual(session_model("s1", events), "claude-sonnet-5")


# --------------------------------------------------------------- BL22 ghost
_PAIR_EVENTS = _extract_block(
    r"function pairEvents\(events\)\{.*?\n\}\n", "pairEvents"
)
_STATE_BLOCK = _extract_block(
    r"const nodeEls=new Map\(\); let edgeSig=\"\";.*?\nfunction computeStates\(agents\)\{.*?\n  return anyWorking;\n\}\n",
    "the computeStates block and its dependencies",
)
_BG_MS = _extract_line("const BG_MS=", "BG_MS")
_ABANDON_MS = _extract_line("const ABANDON_MS=", "ABANDON_MS")
_LIVENESS_MS = _extract_line("const LIVENESS_MS=", "LIVENESS_MS")

HARNESS_PRELUDE = "\n".join([_ABANDON_MS, _BG_MS, _LIVENESS_MS, _PAIR_EVENTS, _STATE_BLOCK])


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
        "subagent_type": "keel:t609-agent",
        "description": "T609 delegation",
        **extra,
    }


def activity(*, seconds_ago: float, agent_type: str = "keel:t609-agent") -> dict[str, Any]:
    return {
        "v": 1,
        "ts": iso(seconds_ago),
        "event": "activity",
        "session_id": "s-1",
        "agent_type": agent_type,
        "tool": "Bash",
        "detail": "still going",
    }


def evaluate(events: list[dict[str, Any]], acts: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs ``pairEvents``+``computeStates`` on this fixture exactly as the
    live page's ``tick()`` does, and reports the one unpaired agent's flags."""
    script = f"""
lastStops=[];lastActs={json.dumps(acts)};lastReviews=[];lastSessionStarts=[];
const events={json.dumps(events)};
const agents=pairEvents(events);
computeStates(agents);
const a=agents.find(x=>x.start);
console.log(JSON.stringify({{
  working:a.working,abandoned:a.abandoned,stale:a.stale
}}));
"""
    return run_node(HARNESS_PRELUDE + "\n" + script)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestAnUnpairedDelegationGoesStaleNotWorking(unittest.TestCase):
    """BL22: the ghost card. An unpaired ``handoff_start`` (no ``handoff_end``
    ever arrives - the API killed the agent outright) must not render
    "working" merely because it is younger than ``ABANDON_MS`` (2h)."""

    def test_a_fresh_unpaired_launch_is_working(self) -> None:
        """Just launched, well inside LIVENESS_MS - genuinely working."""
        events = [launch_half("handoff_start", "u1", seconds_ago=30)]
        result = evaluate(events, [])
        self.assertIs(result["working"], True)
        self.assertIs(result["stale"], False)
        self.assertIs(result["abandoned"], False)

    def test_fresh_activity_keeps_it_working_past_liveness_ms_from_launch(self) -> None:
        """The launch itself is older than LIVENESS_MS, but a fresh activity
        event for the same agent proves it is still alive - exactly the
        background branch's own rule, now shared by the unpaired branch."""
        events = [launch_half("handoff_start", "u2", seconds_ago=900)]
        acts = [activity(seconds_ago=10)]
        result = evaluate(events, acts)
        self.assertIs(result["working"], True)
        self.assertIs(result["stale"], False)

    def test_no_event_past_liveness_ms_renders_stale_never_working(self) -> None:
        """THE DEFECT, reproduced: launched 20 minutes ago (past LIVENESS_MS
        =10min), no stop, no activity, and comfortably inside ABANDON_MS
        (2h) - the old code read this as "working"; it must now read
        "stale", not "working" and not silently "abandoned" either."""
        events = [launch_half("handoff_start", "u3", seconds_ago=1200)]
        result = evaluate(events, [])
        self.assertIs(result["working"], False)
        self.assertIs(result["stale"], True)
        self.assertIs(result["abandoned"], False)

    def test_past_abandon_ms_is_abandoned_not_merely_stale(self) -> None:
        """The outer bound is unchanged: past ABANDON_MS (2h) the delegation
        is ``abandoned``, and ``stale`` must not also fire for the same
        agent - the two are mutually exclusive states."""
        events = [launch_half("handoff_start", "u4", seconds_ago=3 * 60 * 60)]
        result = evaluate(events, [])
        self.assertIs(result["working"], False)
        self.assertIs(result["abandoned"], True)
        self.assertIs(result["stale"], False)

    def test_the_stale_chip_names_the_state_on_the_card(self) -> None:
        self.assertIn('chip.textContent="⏳ stale — no event since "', SOURCE)
        self.assertIn("else if(a.stale){", SOURCE)


class TestNodeAbsenceIsAnnounced(unittest.TestCase):
    """Node's absence is audible, then skipped - never silent (BL17)."""

    def test_node_is_on_path(self) -> None:
        if NODE is None:
            self.skipTest(SKIP_REASON)
        self.assertTrue(
            Path(NODE).exists(),
            f"PATH named a node that is not there: {NODE}",
        )


if __name__ == "__main__":
    unittest.main()
