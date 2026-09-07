#!/usr/bin/env python3
"""T322 - task chips branch from their owner on the live orchestration view.
Made TRANSIENT by T324 (owner design correction, 2026-08-25) and RE-DRAWN by
T332 (owner-confirmed concept, 2026-08-25): the branch rail that hung under a
card became orbit mini-cards around it. T322's subject - ATTRIBUTION (whose
task is this, how many are live, when does a chip die) - is unchanged and is
what this file still pins; the presentation assertions below were moved onto
the markup the page actually renders now (``.tnode`` satellites), because an
assertion pinning markup the page no longer emits cannot fail on a
regression. The orbit geometry and the viewport fit are pinned next door, in
``tests/test_keel_dashboard_t332.py``.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` as source text only -
          the chip-builder functions it adds are pure, DOM-free JavaScript
          (``eventsForOwner`` / ``chipRailFor`` / ``orbitCardsFor`` /
          ``orbitCardHtml`` / ``chipState`` / ``chipLive``), so this file
          extracts them verbatim
          and runs them under Node, fed entirely synthetic event lists
          (BL1: no case here reads this repository's own audit log). Every
          call that can matter for a chip's LIFETIME passes an explicit
          ``now`` - nothing here relies on the real wall clock, so a fresh
          fixture never goes stale between the moment it is written and the
          moment the assertion runs.
          Also extracts the T324 ring-position solver (``ringPos`` plus the
          layout constants it closes over) from the same source and runs it
          under Node - it too is pure (index, count, stage W/H -> [x,y]),
          with no DOM and no clock, so its geometry guarantees can be pinned
          numerically on synthetic viewport sizes alone (BL1).
Emits   : unittest results only.
Writes  : nothing outside a temporary script handed to ``node``.
Argv    : none.

What this pins
---------------
* GROUPING: a tracked-session event (no ``agent_type``) attributes to the
  Captain (owner ``null``); a delegate-paired event (matching hand-off's
  session + subagent_type + start..end window, the same test ``actsFor``
  already uses) attributes to that agent and nowhere else.
* THE CAP: at most 3 chips shown, newest first - no overflow line (T324
  deleted it: a transient rail shows what is happening now, not a log).
* THE HONESTY MAP: a ``background_task`` event renders a "background ·
  started <age>" state (never a bare "running" claim); ``activity`` and
  ``gate_block`` (both completion-only) render their own event kind
  ("just ran" / "just blocked") and NEVER "running".
* TRANSIENCE (T324): a fresh ``activity``/``gate_block`` chip is present; the
  same event once ``now`` has moved past ``CHIP_FRESH_MS`` is absent. A
  ``background_task`` chip owned by a still-working delegate is present
  regardless of its age; once that delegate has closed (``end``/``stop``)
  its background chip is absent. A node with nothing live in scope shows no
  chip at all - the T322 "rail hidden when a node has nothing in scope" pin,
  now also the T324 "quiet board looks exactly as before T322" pin and
  (T332) the "an idle hub is given no satellite and no wire" pin.
* THE ORBIT MARKUP (T332, replacing T322's rail markup): a scoped-in, live
  node produces one mini-card descriptor per live chip and a ``.tnode``
  body for each; a node with nothing live in scope produces NO descriptors
  at all, so the page draws it no satellite and no wire.
* THE CAPTAIN'S CLEARANCE (T324 retry, review finding 2026-08-25): the ring
  solver keeps every card (1) inside the viewport and (2) OUT of the
  Captain's 2D clearance box - the box is cleared by x-distance OR
  y-distance, so a card pinned to the viewport's top edge is fine when it is
  pushed far enough aside. Pinned at the review's exact failing case
  (W=1200, H=700, top of ring: the old math clamped y to 116, only 195px
  from cy=311 where 228 is required), at a pathologically short stage
  (H=560, every index of an 8-card ring across several widths), and as a
  REGRESSION pin at comfortable heights (H>=900), where the solver must
  still return the pre-fix positions to the pixel.

Failure policy
--------------
FAIL-CLOSED: if ``node`` cannot be found, the whole file fails rather than
skipping (an environment that cannot run the check does not get to claim
the check passed).

Constraints
-----------
Python 3.10+ standard library, plus a ``node`` binary on PATH (already
depended on elsewhere in this suite's Node-shaped fixtures). Subprocess
invoked with an argument list, never a shell string (R5).
"""
from __future__ import annotations

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
PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
SOURCE = PAGE.read_text(encoding="utf-8")
announce_once()


def _extract_line(prefix: str, label: str) -> str:
    """The one source line that starts with ``prefix`` - exact, unedited,
    verbatim from the served page (every helper below is single-line)."""
    for line in SOURCE.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"could not extract {label!r} from the served page")


def _extract_block(pattern: str, label: str) -> str:
    m = re.search(pattern, SOURCE, re.S)
    if not m:
        raise AssertionError(f"could not extract {label!r} from the served page")
    return m.group(0)


# Pure helpers the chip functions close over, extracted from the SAME
# source rather than reimplemented - a drift in any of these must fail this
# file, not be silently masked by a second, independent copy.
_TS = _extract_line("const ts=", "ts")
_ESC = _extract_line("const esc=", "esc")
_REL = _extract_block(r"const rel=t=>\{.*?\};", "rel")
_TOOLICON = _extract_line("const toolIcon=", "toolIcon")
_CHIP_BLOCK = _extract_block(
    r"const CHIP_KINDS=new Set.*?function orbitCardHtml\(item\)\{.*?\n\}\n",
    "the T322/T324 chip-builder block, through T332's orbit-card presentation",
)

HARNESS_PRELUDE = "\n".join([_TS, _ESC, _REL, _TOOLICON, _CHIP_BLOCK])

#: The T324 ring solver and the layout constants it reads - one contiguous
#: run of source, taken verbatim so a drift in either the constants or the
#: solver body must fail here rather than be masked by a private copy.
_SOLVER_BLOCK = _extract_block(
    r"const ORBIT_BAND_H=64,CENTER_HALF_H=120;.*?\nfunction ringPos\(i,count,W,H\)\{.*?\n\}\n",
    "the T324 ring-position solver block",
)

#: Test-side scaffolding only: it computes NOTHING the solver computes, it
#: just reports the solver's answer next to the constants the same extracted
#: source defines, so the assertions below never carry a second copy of the
#: geometry they are checking.
_SOLVER_PROBE = """
function probe(i,count,W,H){
  const [x,y]=ringPos(i,count,W,H);
  const cx=W/2,cy=(H-BENCH_H)/2;
  return {x,y,cx,cy,dx:Math.abs(x-cx),dy:Math.abs(y-cy),
    CLEAR_X,CLEAR_Y,CARD_W,CARD_H,BENCH_H,
    inBox:(Math.abs(x-cx)<CLEAR_X&&Math.abs(y-cy)<CLEAR_Y),
    inView:(x-CARD_W/2>=0&&x+CARD_W/2<=W&&y-CARD_H/2>=0&&y+CARD_H/2<=H-BENCH_H)};
}
function probeAll(cases){return cases.map(c=>Object.assign(probe(c[0],c[1],c[2],c[3]),
  {i:c[0],count:c[1],W:c[2],H:c[3]}));}
"""

SOLVER_PRELUDE = _SOLVER_BLOCK + _SOLVER_PROBE


class TestTheExtractionItselfFoundEveryPiece(unittest.TestCase):
    """The regex extraction is not vacuous - each pulled block is non-empty
    and the block carries every function this file is about to call."""

    def test_every_helper_was_found_and_is_nonempty(self) -> None:
        for name, text in (
            ("ts", _TS),
            ("esc", _ESC),
            ("rel", _REL),
            ("toolIcon", _TOOLICON),
            ("chip block", _CHIP_BLOCK),
        ):
            self.assertTrue(text.strip(), f"{name} extraction was empty")

    def test_the_chip_block_carries_every_function_under_test(self) -> None:
        for fn in ("eventsForOwner", "chipRailFor", "orbitCardsFor", "orbitCardHtml",
                   "chipState", "chipIcon", "chipLive"):
            self.assertIn(fn, _CHIP_BLOCK)

    def test_the_chip_fresh_ms_constant_is_named_and_present(self) -> None:
        self.assertIn("const CHIP_FRESH_MS=90*1000;", _CHIP_BLOCK)


def run_with(prelude: str, call_js: str) -> Any:
    """Run ``call_js`` (an expression whose value is JSON-serialisable)
    against ``prelude``, under a real ``node`` process."""
    if NODE is None:
        raise AssertionError("node was not found on PATH - failing closed")
    script = prelude + "\nprocess.stdout.write(JSON.stringify(" + call_js + "));\n"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".js", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run(
            [NODE, path], capture_output=True, timeout=30, check=False
        )
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError(
            "node harness failed: " + result.stderr.decode("utf-8", "replace")
        )
    return json.loads(result.stdout.decode("utf-8"))


def run_node(call_js: str) -> Any:
    """``call_js`` against the chip-builder helpers."""
    return run_with(HARNESS_PRELUDE, call_js)


def run_solver(call_js: str) -> Any:
    """``call_js`` against the extracted ring solver + its probe."""
    return run_with(SOLVER_PRELUDE, call_js)


# ---- synthetic fixtures (BL1: nothing here reads a real audit log) --------

def activity(session: str, ts_iso: str, agent_type: Any = None, tool: str = "Bash",
             detail: str = "ran a command") -> dict[str, Any]:
    return {
        "event": "activity", "session_id": session, "agent_type": agent_type,
        "tool": tool, "detail": detail, "ts": ts_iso,
    }


def background(session: str, ts_iso: str, agent_type: Any = None, tool: str = "Bash",
               detail: str = "long build") -> dict[str, Any]:
    return {
        "event": "background_task", "session_id": session, "agent_type": agent_type,
        "tool": tool, "detail": detail, "ts": ts_iso,
    }


def gate(session: str, ts_iso: str, agent_type: Any = None, tool: str = "Write",
          detail: str = "policy lock") -> dict[str, Any]:
    return {
        "event": "gate_block", "session_id": session, "agent_type": agent_type,
        "tool": tool, "detail": detail, "ts": ts_iso,
    }


def session_end(session: str, ts_iso: str) -> dict[str, Any]:
    return {"event": "session_end", "session_id": session, "ts": ts_iso}


def handoff_agent(session: str, subagent_type: str, start_ts: str, end_ts: str | None = None,
                   background_run: bool = False, stop_ts: str | None = None) -> dict[str, Any]:
    """A synthetic paired ``a`` object exactly as ``pairEvents``/``computeStates``
    would shape it - the fields ``eventsForOwner``/``chipLive`` actually read."""
    a: dict[str, Any] = {
        "start": {"session_id": session, "subagent_type": subagent_type, "ts": start_ts},
        "end": {"ts": end_ts} if end_ts else None,
        "background": background_run,
        "stop": {"ts": stop_ts} if stop_ts else None,
    }
    return a


#: Spaced 10s apart (not 1min, as T322 originally had them) so every one of
#: them sits inside CHIP_FRESH_MS (90s) of any other - the GROUPING and CAP
#: tests below are about attribution and ordering, not freshness, and use a
#: single ``now`` near the latest fixture timestamp so the T324 freshness
#: filter never silently empties a rail those tests never meant to probe.
#: The TRANSIENCE tests further down choose their own ``now`` explicitly,
#: on top of and beyond CHIP_FRESH_MS, to exercise that filter directly.
T0 = "2026-08-25T10:00:00Z"
T1 = "2026-08-25T10:00:10Z"
T2 = "2026-08-25T10:00:20Z"
T3 = "2026-08-25T10:00:30Z"
T4 = "2026-08-25T10:00:40Z"
T5 = "2026-08-25T10:00:50Z"


def _epoch_ms(ts_iso: str) -> int:
    from datetime import datetime, timezone

    return int(datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp() * 1000)


NOW_FRESH = _epoch_ms(T1) + 1000  # 1s after T1 - well inside CHIP_FRESH_MS
CHIP_FRESH_MS = 90_000


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestGroupingByOwner(unittest.TestCase):
    """A tracked-session event with no delegate attribution -> Captain
    (owner ``null``); a delegate-paired event -> that agent, and nowhere
    else - the very split T322 asks for. Every fixture below is fresh
    relative to the ``now`` passed, so grouping is exercised independently
    of the T324 freshness window."""

    def test_untyped_events_group_under_the_captain(self) -> None:
        events = [
            activity("s1", T0, agent_type=None),
            activity("s1", T1, agent_type="keel:executor"),
        ]
        now = _epoch_ms(T1) + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 1)
        self.assertEqual(rail["shown"][0]["ts"], T0)

    def test_a_delegates_events_group_under_that_agent_only(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0, end_ts=T3)
        events = [
            activity("s1", T1, agent_type="keel:executor"),
            activity("s1", T4, agent_type="keel:executor"),  # after the window - excluded
            activity("s1", T1, agent_type=None),  # captain's own - excluded
        ]
        now = _epoch_ms(T4) + 1000
        rail = run_node(f"chipRailFor({json.dumps(a)},{json.dumps(events)},{now})")
        self.assertEqual([c["ts"] for c in rail["shown"]], [T1])

    def test_two_different_agents_never_share_an_event(self) -> None:
        a1 = handoff_agent("s1", "keel:executor", T0, end_ts=T2)
        a2 = handoff_agent("s1", "keel:executor", T3, end_ts=T5)
        events = [
            activity("s1", T1, agent_type="keel:executor"),  # inside a1's window
            activity("s1", T4, agent_type="keel:executor"),  # inside a2's window
        ]
        now = _epoch_ms(T5) + 1000
        rail1 = run_node(f"chipRailFor({json.dumps(a1)},{json.dumps(events)},{now})")
        rail2 = run_node(f"chipRailFor({json.dumps(a2)},{json.dumps(events)},{now})")
        self.assertEqual([c["ts"] for c in rail1["shown"]], [T1])
        self.assertEqual([c["ts"] for c in rail2["shown"]], [T4])

    def test_a_different_sessions_events_never_attribute_to_this_agent(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0, end_ts=T3)
        events = [activity("s2", T1, agent_type="keel:executor")]
        now = _epoch_ms(T1) + 1000
        rail = run_node(f"chipRailFor({json.dumps(a)},{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheThreeChipCapNewestFirst(unittest.TestCase):
    """T324: the cap stays at 3, newest first - no overflow line."""

    def test_three_or_fewer_fresh_events_show_all(self) -> None:
        events = [activity("s1", T0), activity("s1", T1), activity("s1", T2)]
        now = _epoch_ms(T2) + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 3)

    def test_more_than_three_fresh_events_caps_at_three_newest_first(self) -> None:
        events = [activity("s1", t) for t in (T0, T1, T2, T3, T4)]
        now = _epoch_ms(T4) + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 3)
        self.assertEqual([c["ts"] for c in rail["shown"]], [T4, T3, T2])

    def test_the_overflow_line_is_gone(self) -> None:
        events = [activity("s1", t) for t in (T0, T1, T2, T3, T4)]
        now = _epoch_ms(T4) + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        cards = run_node(f"orbitCardsFor(null,{json.dumps(events)},{now})")
        html = "".join(run_node(f"orbitCardHtml({json.dumps(c)})") for c in cards)
        self.assertNotIn("earlier this round", html)
        self.assertNotIn("overflow", rail)
        self.assertNotIn("tchip-more", SOURCE)
        # T332: the cap governs the satellites too - five live events, three
        # mini cards, and nothing anywhere saying how many were dropped.
        self.assertEqual(len(cards), 3)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheHonestyMap(unittest.TestCase):
    """A 'running' state is drawn ONLY where a start-shaped event class
    exists (background_task); completion-only classes (activity,
    gate_block) render as their own event kind, never as running."""

    def test_background_task_renders_background_started_never_running(self) -> None:
        state = run_node(f"chipState({json.dumps(background('s1', T0))})")
        self.assertEqual(state["cls"], "background")
        self.assertIn("background · started", state["label"])
        self.assertNotIn("running", state["label"])

    def test_activity_renders_its_own_kind_never_running_never_aged(self) -> None:
        state = run_node(f"chipState({json.dumps(activity('s1', T0))})")
        self.assertEqual(state["cls"], "done")
        self.assertEqual(state["label"], "just ran")
        self.assertNotIn("running", state["label"])
        self.assertNotIn("ago", state["label"])

    def test_gate_block_renders_its_own_kind_never_running_never_aged(self) -> None:
        state = run_node(f"chipState({json.dumps(gate('s1', T0))})")
        self.assertEqual(state["cls"], "done")
        self.assertEqual(state["label"], "just blocked")
        self.assertNotIn("running", state["label"])
        self.assertNotIn("ago", state["label"])

    def test_no_chip_class_the_source_defines_ever_says_running(self) -> None:
        # Read straight off the block under test, not off a case's own
        # fixture - a code change that introduces a 'running' literal must
        # fail here even if no test above happens to exercise it.
        self.assertNotIn("running", _CHIP_BLOCK.casefold())


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTransience(unittest.TestCase):
    """T324, owner design correction 2026-08-25: chips exist only while
    their task lives, then disappear - driven entirely by an injectable
    ``now``, never the real clock."""

    def test_fresh_activity_chip_is_present(self) -> None:
        events = [activity("s1", T0)]
        now = _epoch_ms(T0) + 1000  # 1s later - fresh
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 1)

    def test_same_activity_chip_beyond_chip_fresh_ms_is_absent(self) -> None:
        events = [activity("s1", T0)]
        now = _epoch_ms(T0) + CHIP_FRESH_MS + 1000  # past the window
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])
        # T332: nothing live in scope -> no satellite is built at all, which
        # is what makes the hub draw neither a mini card nor a wire.
        self.assertEqual(run_node(f"orbitCardsFor(null,{json.dumps(events)},{now})"), [])

    def test_same_gate_block_chip_beyond_chip_fresh_ms_is_absent(self) -> None:
        events = [gate("s1", T0)]
        now = _epoch_ms(T0) + CHIP_FRESH_MS + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])

    def test_running_background_task_is_present_regardless_of_age(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0)  # no end/stop - still working
        events = [background("s1", T0, agent_type="keel:executor")]
        # far beyond CHIP_FRESH_MS - a running background chip does not age out
        now = _epoch_ms(T0) + CHIP_FRESH_MS * 50
        rail = run_node(f"chipRailFor({json.dumps(a)},{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 1)

    def test_ended_background_task_is_absent(self) -> None:
        a = handoff_agent("s1", "keel:executor", T0, end_ts=T1)  # agent reported back
        events = [background("s1", T0, agent_type="keel:executor")]
        now = _epoch_ms(T1) + 1000
        rail = run_node(f"chipRailFor({json.dumps(a)},{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])

    def test_captain_background_task_vanishes_once_its_session_ends(self) -> None:
        events = [
            background("s1", T0, agent_type=None),
            session_end("s1", T1),
        ]
        now = _epoch_ms(T1) + 1000
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])

    def test_captain_background_task_still_present_before_its_session_ends(self) -> None:
        events = [background("s1", T0, agent_type=None)]
        now = _epoch_ms(T0) + CHIP_FRESH_MS * 50
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(rail["shown"]), 1)

    def test_empty_scope_builds_no_satellite(self) -> None:
        rail = run_node(f"chipRailFor(null,{json.dumps([])},{NOW_FRESH})")
        self.assertEqual(rail["shown"], [])
        self.assertEqual(run_node(f"orbitCardsFor(null,{json.dumps([])},{NOW_FRESH})"), [])

    def test_a_quiet_board_with_no_fresh_events_builds_no_satellites(self) -> None:
        """Pin: with no live tasks the board looks exactly as it did before
        T322 - no chip is shown, and (T332) no mini card orbits anything."""
        events = [activity("s1", T0), gate("s1", T0)]
        now = _epoch_ms(T0) + CHIP_FRESH_MS + 60_000  # long stale
        rail = run_node(f"chipRailFor(null,{json.dumps(events)},{now})")
        self.assertEqual(rail["shown"], [])
        self.assertEqual(run_node(f"orbitCardsFor(null,{json.dumps(events)},{now})"), [])


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheOrbitMarkup(unittest.TestCase):
    """T332: the rail's markup pins, moved onto the markup that replaced it."""

    def test_a_scoped_in_live_node_builds_a_background_mini_card(self) -> None:
        events = [background("s1", T0, detail="keel.py dashboard")]
        now = _epoch_ms(T0) + 1000
        cards = run_node(f"orbitCardsFor(null,{json.dumps(events)},{now})")
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["cls"], "background")
        # the state word is chipState's own - no second vocabulary (T322)
        self.assertNotIn("running", json.dumps(cards[0]).casefold())
        html = run_node(f"orbitCardHtml({json.dumps(cards[0])})")
        self.assertIn('class="tdot"', html)
        self.assertIn("keel.py dashboard", html)
        self.assertIn("background · started", html)

    def test_a_node_with_nothing_in_scope_builds_nothing(self) -> None:
        self.assertEqual(run_node(f"orbitCardsFor(null,{json.dumps([])},{NOW_FRESH})"), [])

    def test_the_description_is_html_escaped(self) -> None:
        events = [background("s1", T0, detail="<script>alert(1)")]
        now = _epoch_ms(T0) + 1000
        cards = run_node(f"orbitCardsFor(null,{json.dumps(events)},{now})")
        html = run_node(f"orbitCardHtml({json.dumps(cards[0])})")
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)


class TestTheSolverExtractionItselfFoundEveryPiece(unittest.TestCase):
    """The solver extraction is not vacuous, and layout() really delegates to
    it - a copy of the old inline math left behind in layout() would make
    every geometry pin below decorative."""

    def test_the_solver_block_is_nonempty_and_carries_the_function(self) -> None:
        self.assertTrue(_SOLVER_BLOCK.strip())
        self.assertIn("function ringPos(i,count,W,H){", _SOLVER_BLOCK)

    def test_the_clearance_box_is_named_on_both_axes(self) -> None:
        self.assertIn("const CENTER_HALF_W=103;", _SOLVER_BLOCK)
        self.assertIn(
            "const CLEAR_X=CENTER_HALF_W+CARD_W/2,CLEAR_Y=CENTER_HALF_H+CARD_H/2;",
            _SOLVER_BLOCK,
        )

    def test_layout_positions_cards_only_through_the_solver(self) -> None:
        self.assertIn("pos[a.uid]=ringPos(i,ring.length,W,H);", SOURCE)
        # exactly one definition, exactly one caller shape - no second copy
        self.assertEqual(SOURCE.count("function ringPos("), 1)
        self.assertEqual(SOURCE.count("ringPos(i,ring.length,W,H)"), 1)

    def test_no_inline_clamp_survives_in_layout(self) -> None:
        """The old clampX/clampY pair lived in layout() and was the bug: it
        must exist only inside the solver, where the clearance rule can see
        it."""
        self.assertEqual(SOURCE.count("const clampX=v=>"), 1)
        self.assertEqual(SOURCE.count("const clampY=v=>"), 1)
        self.assertIn("const clampX=v=>", _SOLVER_BLOCK)
        self.assertIn("const clampY=v=>", _SOLVER_BLOCK)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheCaptainsClearanceBox(unittest.TestCase):
    """T324 retry (review finding, 2026-08-25): the clearance the layout
    comment promises must hold at EVERY viewport size, not only at ones tall
    enough for the y term alone to carry it."""

    #: Viewport widths a real browser window can plausibly hand the stage,
    #: paired below with heights from painfully short to comfortable.
    WIDTHS = (900, 1024, 1200, 1400, 1920)

    def _assert_both_properties(self, cases: list[tuple[int, int, int, int]]) -> None:
        """One node run for the whole sweep (a process per card would make
        this file the slowest in the suite), then one subTest per card so a
        failure names the exact index and viewport."""
        for p in run_solver(f"probeAll({json.dumps([list(c) for c in cases])})"):
            with self.subTest(W=p["W"], H=p["H"], count=p["count"], i=p["i"]):
                self.assertFalse(
                    p["inBox"],
                    f"card {p['i']}/{p['count']} at {p['W']}x{p['H']} sits in the "
                    f"Captain's clearance box: |dx|={p['dx']:.1f} (needs >= "
                    f"{p['CLEAR_X']}) and |dy|={p['dy']:.1f} (needs >= {p['CLEAR_Y']})",
                )
                self.assertTrue(
                    p["inView"],
                    f"card {p['i']}/{p['count']} at {p['W']}x{p['H']} hangs off the "
                    f"stage: x={p['x']:.1f} y={p['y']:.1f}",
                )

    def test_the_review_case_h700_top_of_ring_clears_the_captain(self) -> None:
        """The exact case the review measured. BEFORE this fix the old math
        returned (600, 116) with cy=311: |dy|=195 against a required 228 and
        |dx|=0, i.e. squarely inside the box. The card may still be clamped
        to y=116 (the viewport bound wins), but it must then stand aside."""
        p = run_solver("probe(0,3,1200,700)")
        self.assertEqual(p["cy"], 311)
        self.assertEqual(p["y"], 116)  # the viewport clamp still governs y
        self.assertLess(p["dy"], p["CLEAR_Y"])  # so y alone cannot clear the box
        self.assertGreaterEqual(p["dx"], p["CLEAR_X"])  # x is what clears it
        self.assertEqual(p["x"], 778)  # cx + CLEAR_X, pushed outward, right side
        self.assertFalse(p["inBox"])
        self.assertTrue(p["inView"])

    def test_the_review_case_bottom_of_ring_clears_the_captain_too(self) -> None:
        """The same clamp bit the bottom of the ring at H=700 (old math:
        (600, 514), |dy|=203 < 228) - the mirror of the reported case."""
        p = run_solver("probe(3,6,1200,700)")
        self.assertEqual(p["y"], 514)
        self.assertGreaterEqual(p["dx"], p["CLEAR_X"])
        self.assertFalse(p["inBox"])
        self.assertTrue(p["inView"])

    def test_every_index_of_every_ring_size_at_h700(self) -> None:
        self._assert_both_properties(
            [(i, count, W, 700)
             for W in self.WIDTHS for count in range(1, 9) for i in range(count)]
        )

    def test_a_pathologically_short_stage_still_holds_both_properties(self) -> None:
        """H=560: the stage is barely taller than two card footprints, so the
        y term can never clear the box - every card that needs it is pushed
        outward in x instead."""
        self._assert_both_properties(
            [(i, count, W, 560)
             for W in self.WIDTHS for count in range(1, 9) for i in range(count)]
        )

    def test_the_threshold_height_and_the_heights_around_it(self) -> None:
        """~766px is where Ry's clearance floor and the viewport clamp meet;
        the property must hold on both sides of that seam."""
        self._assert_both_properties(
            [(i, 6, 1200, H)
             for H in (600, 650, 700, 740, 766, 780, 800, 900, 1080)
             for i in range(6)]
        )


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestComfortableViewportsAreUntouched(unittest.TestCase):
    """REGRESSION pin: at heights where the pre-fix math was already correct
    the solver must return exactly the positions it always did. The numbers
    below were computed from the PRE-FIX formula (clampX/clampY over the
    ellipse) and are pinned as literals - if the fix moved a card on a
    comfortable stage, that is a behaviour change this task did not license.
    """

    EXPECTED = {
        (1200, 900, 3): [(600.0, 116.0), (1035.61, 558.5), (164.39, 558.5)],
        (1400, 900, 8): [
            (700.0, 116.0), (1126.39, 202.4), (1303.0, 411.0), (1126.39, 619.6),
            (700.0, 706.0), (273.61, 619.6), (97.0, 411.0), (273.61, 202.4),
        ],
        (1200, 1080, 5): [
            (600.0, 116.0), (1078.38, 382.03), (895.66, 812.47),
            (304.34, 812.47), (121.62, 382.03),
        ],
    }

    def test_the_pre_fix_positions_survive_to_the_pixel(self) -> None:
        cases = [[i, count, W, H]
                 for (W, H, count), points in self.EXPECTED.items()
                 for i in range(len(points))]
        for p in run_solver(f"probeAll({json.dumps(cases)})"):
            ex, ey = self.EXPECTED[(p["W"], p["H"], p["count"])][p["i"]]
            with self.subTest(W=p["W"], H=p["H"], count=p["count"], i=p["i"]):
                self.assertAlmostEqual(p["x"], ex, delta=1.0)
                self.assertAlmostEqual(p["y"], ey, delta=1.0)
                self.assertFalse(p["inBox"])
                self.assertTrue(p["inView"])

    def test_the_top_of_ring_card_is_still_centred_when_there_is_room(self) -> None:
        """The sideways push is a SHORT-STAGE remedy only: given height, the
        top card sits dead centre above the Captain exactly as before."""
        p = run_solver("probe(0,3,1200,900)")
        self.assertEqual(p["x"], p["cx"])
        self.assertEqual(p["dx"], 0)
        self.assertGreaterEqual(p["dy"], p["CLEAR_Y"])


class TestNodeAbsenceIsAnnounced(unittest.TestCase):
    """Node's absence is audible, then skipped — never silent.

    This class used to FAIL when node was missing, so the page-side checks
    above could not skip unnoticed. Ruled 2026-09-01 (BL17): they skip, so a
    clone on a machine without node still reaches green, and audibility is
    kept rather than traded away — ``keel_node.announce_once`` prints one line
    to stderr and every skipped case above carries the same reason.
    """

    def test_node_is_on_path(self) -> None:
        if NODE is None:
            self.skipTest(SKIP_REASON)
        self.assertTrue(
            Path(NODE).exists(),
            f"PATH named a node that is not there: {NODE}",
        )


class TestTheChipsAreWiredIntoTheRenderedPage(unittest.TestCase):
    """Static presence pins, moved by T332 from the rail onto the orbit
    satellites that replaced it: the page builds ``.tnode`` mini cards from
    the chip builder, layout() is still round-scoped via the same evView the
    rest of the round-filtered view uses, and the rail markup is gone from
    the source rather than left behind as dead furniture."""

    def test_the_page_builds_orbit_satellites_from_the_chip_builder(self) -> None:
        self.assertIn("const capItems=orbitCardsFor(null,railEvents,now);", SOURCE)
        self.assertIn("const items=orbitCardsFor(a,railEvents,now);", SOURCE)
        self.assertIn('el.className="tnode tnode-"+o.item.cls;', SOURCE)

    def test_layout_is_called_with_the_round_scoped_event_view(self) -> None:
        self.assertIn("const anyWorking=layout(agView,evView);", SOURCE)

    def test_the_replaced_rail_markup_is_gone_not_merely_unused(self) -> None:
        """A pin that would fail on dead furniture: T332 replaced the rail,
        so no rail container, class or builder may survive in the page."""
        for dead in ('class="rail"', "data-rail", "captainRail", "chipRailHtml", "tchip"):
            self.assertNotIn(dead, SOURCE, f"{dead!r} survives the T332 replacement")

    def test_the_three_chip_cap_is_the_literal_the_builder_uses(self) -> None:
        self.assertIn("items.slice(0,3)", SOURCE)

    def test_no_overflow_line_literal_survives_in_source(self) -> None:
        self.assertNotIn("earlier this round", SOURCE)

    def test_the_mini_card_has_a_fixed_footprint_in_css(self) -> None:
        """T332's lockstep pair, successor to T324's rail ceiling: the CSS box
        and the constant the layout reserves it by must agree."""
        self.assertIn(
            ".tnode{position:absolute;transform:translate(-50%,-50%);"
            "width:96px;height:30px;overflow:hidden;",
            SOURCE,
        )
        self.assertIn("const ORBIT_W=96,ORBIT_H=30;", SOURCE)

    def test_the_js_layout_still_reserves_the_same_per_card_band(self) -> None:
        self.assertIn("const ORBIT_BAND_H=64,CENTER_HALF_H=120;", SOURCE)
        self.assertIn("const BENCH_H=78,CARD_W=150,CARD_H=152+ORBIT_BAND_H;", SOURCE)


class TestTheChipsAreDetachedMiniCards(unittest.TestCase):
    """T325 (owner screenshot review, 2026-08-25), carried forward by T332:
    the node's visible surface (background/border) is its own inner .card
    wrapper, and each chip is its own mini-card with a background+border
    distinct from the node card's own - now a free-standing satellite rather
    than a rail row. Pins the CSS declarations and the markup structure that
    together produce that detachment."""

    def test_the_mini_card_rule_declares_its_own_background_and_border(self) -> None:
        m = re.search(r"\.tnode\{[^}]*\}", SOURCE, re.S)
        self.assertIsNotNone(m, "could not find the .tnode CSS rule")
        rule = m.group(0)
        self.assertIn("background:", rule)
        self.assertIn("border:", rule)
        self.assertIn("border-radius:", rule)
        self.assertIn("position:absolute", rule)  # placed by the layout, not by flow

    def test_the_node_visible_box_lives_on_an_inner_card_wrapper(self) -> None:
        # the painted surface (background/border/box-shadow) lives on
        # .node .card, not on .node itself - .node stays a bare positioned box.
        # The literal is the T332 GREY gradient: the owner's palette
        # adjustment drained the hue, so a navy value here would now be the
        # regression rather than the pin.
        self.assertIn(
            ".node .card{background:linear-gradient(180deg,#212328f2,#17191df2);",
            SOURCE,
        )
        self.assertNotIn(
            ".node{position:absolute;transform:translate(-50%,-50%);width:152px;\n"
            "  background:",
            SOURCE,
        )

    def test_a_satellite_is_never_a_child_of_the_card_it_orbits(self) -> None:
        # the delegate card template ends at its own .card wrapper ...
        self.assertIn('el.innerHTML=`<div class="card">', SOURCE)
        self.assertIn(
            '<span class="chip"></span><div class="act"></div>\n        </div>`;',
            SOURCE,
        )
        # ... and every satellite is appended to the node LAYER instead
        self.assertIn(
            'if(!el){el=document.createElement("div");$("nodes").appendChild(el);'
            "nodeEls.set(key,el);}",
            SOURCE,
        )

    def test_the_captain_card_also_ends_at_its_own_wrapper(self) -> None:
        self.assertIn(
            '<span class="chip" id="mstate"></span><div class="act" id="mact"></div>\n'
            "      </div>`;",
            SOURCE,
        )


if __name__ == "__main__":
    unittest.main()
