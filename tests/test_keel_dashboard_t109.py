#!/usr/bin/env python3
"""T109 - a finished delegation lingers on the canvas before it leaves.

Contract
--------
Reads   : temporary directories this file creates, and nothing else - no
          fixture here touches this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
``compute_graph`` (T4/T103) now takes a third argument, ``now``, and uses it
against the NAMED constant ``GRAPH_FINISH_LINGER_SECONDS`` to decide whether a
row whose end is REAL - FINISHED (a matched ``subagent_stop``) or AWAITED (a
genuine blocking return) - is still drawn as its own node. Within the window
it is present, reading exactly as T103 already drew it; past the window it is
simply not among ``nodes`` at all - never duplicated into a second shape, and
never taking the underlying group or open item away from the roster
(``compute_roster``), which reads neither ``nodes`` nor ``now``.

Two pill-free surfaces carried the same disagreement T103's own review found
and parked here rather than fixing outside its own scope: the header's
``working`` count included an ``open_handoff`` row already read FINISHED, and
the plain-text OPEN feed row (``openRow``) called that same row OPEN. Both are
covered here as VALUES (the count) and as page-source claims (the word and the
ticking figure a browser is not run in this suite to observe directly - see
``test_keel_dashboard_t28_31.py``'s own "Values, not substrings").

Values, not substrings
-----------------------
The lingering boundary itself is asserted as a VALUE, directly against
``compute_graph`` with hand-built rows and an explicit ``now`` - never against
a real wall clock, and never against this project's other test files' own
fixed-2026-08-01 fixtures, which predate this task and are patched (in their
own files) to disable this window rather than be rewritten. The header/canvas
agreement and the roster's own count are asserted end to end through
``read_state``, with ``time.time`` patched to a fixed value so the whole
pipeline is deterministic. The feed row's wording is a page-source claim,
declared as such.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    _functions,
    _handoff,
    _page,
    _project,
    _script,
)

STOP_AGENT_ID = "a2222222222222222"
FINISH_TS = "2030-06-01T12:00:00Z"
FINISH_EPOCH = keel_dashboard._epoch_seconds(FINISH_TS)


def _stop(session: str, agent: str, ts: str, agent_id: str = STOP_AGENT_ID) -> dict[str, Any]:
    return {
        "v": 1, "ts": ts, "event": "subagent_stop", "session": session,
        "agent_id": agent_id, "agent_type": agent,
    }


def _finished_group_row(session: str = "s1", agent: str = "keel:executor",
                         description: str = "a finished hand-off",
                         start_ts: str = "2030-06-01T11:55:00Z",
                         finished_ts: str = FINISH_TS) -> dict[str, Any]:
    """The minimal shape ``read_state`` renders a CLOSED group row as -
    exactly the fields ``compute_graph`` reads off one, hand-built so this
    file's own boundary tests need no real audit log at all."""
    return {
        "row_kind": "group",
        "session": session,
        "agent_type": agent,
        "description": description,
        "prompt_head": None,
        "start_ts": start_ts,
        "end_ts": finished_ts,
        "count": 0,
        "inferred": 0,
        "events": [],
        "delegation_state": "finished",
        "finished_ts": finished_ts,
        "last_action": "",
    }


def _awaited_group_row(session: str = "s1", agent: str = "keel:executor",
                        description: str = "an awaited hand-off",
                        start_ts: str = "2030-06-01T11:55:00Z",
                        end_ts: str = FINISH_TS) -> dict[str, Any]:
    row = _finished_group_row(session, agent, description, start_ts, end_ts)
    row["delegation_state"] = "awaited"
    row["finished_ts"] = None
    return row


def _background_group_row(session: str = "s1", agent: str = "keel:executor",
                           description: str = "a backgrounded hand-off",
                           start_ts: str = "2030-06-01T11:55:00Z",
                           end_ts: str = "2030-06-01T11:55:02Z") -> dict[str, Any]:
    row = _finished_group_row(session, agent, description, start_ts, end_ts)
    row["delegation_state"] = "background"
    row["finished_ts"] = None
    return row


def _finished_open_row(session: str = "s1", agent: str = "keel:executor",
                        description: str = "a finished open hand-off",
                        start_ts: str = "2030-06-01T11:55:00Z",
                        finished_ts: str = FINISH_TS) -> dict[str, Any]:
    """The minimal shape ``read_state`` renders an OPEN ``open_handoff`` row
    as - the case a ``subagent_stop`` matched before its own ``handoff_end``
    ever landed, so it is still ``row_kind`` ``"open_handoff"`` while already
    reading FINISHED."""
    return {
        "row_kind": "open_handoff",
        "session": session,
        "ts": start_ts,
        "agent_type": agent,
        "description": description,
        "prompt_head": None,
        "last_seen_ts": start_ts,
        "phase": "tool_running",
        "ambiguous": False,
        "quiet_threshold_seconds": 600,
        "quiet_note": "",
        "delegation_state": "finished",
        "finished_ts": finished_ts,
        "last_action": "",
    }


def _open_row(session: str = "s1", agent: str = "keel:executor",
              description: str = "still going", start_ts: str = "2030-06-01T11:55:00Z") -> dict[str, Any]:
    row = _finished_open_row(session, agent, description, start_ts, None)
    row["delegation_state"] = "open"
    row["finished_ts"] = None
    return row


# ------------------------------------------------------- the named constant


class TestTheNamedConstantGatesTheLinger(unittest.TestCase):
    def test_the_constant_is_a_positive_number(self) -> None:
        self.assertGreater(keel_dashboard.GRAPH_FINISH_LINGER_SECONDS, 0)

    def test_moving_the_constant_moves_the_verdict(self) -> None:
        """A fixed synthetic gap, never the real clock: the same finished row
        and the same ``now`` draw a node or do not, purely on which window the
        constant names - proof the constant is what decides, not a fixed
        boundary baked into ``compute_graph``."""
        row = _finished_group_row()
        now = FINISH_EPOCH + 120
        with unittest.mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 300):
            graph = keel_dashboard.compute_graph([], [row], now)
            self.assertEqual(len(graph["nodes"]), 1)
        with unittest.mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 60):
            graph = keel_dashboard.compute_graph([], [row], now)
            self.assertEqual(graph["nodes"], [])


# --------------------------------------------------- the lingering boundary


class TestTheLingerBoundaryPureFunction(unittest.TestCase):
    """Direct calls against ``compute_graph``, with a controlled ``now`` -
    never a real fixture aged by the wall clock between test runs."""

    def test_a_closed_finished_node_within_the_window_is_present_with_its_finished_state(
        self,
    ) -> None:
        graph = keel_dashboard.compute_graph([], [_finished_group_row()], FINISH_EPOCH + 10)
        self.assertEqual(len(graph["nodes"]), 1)
        node = graph["nodes"][0]
        self.assertEqual(node["delegation_state"], "finished")
        self.assertEqual(node["state_label"], "✓ finished")

    def test_a_closed_finished_node_past_the_window_is_gone_from_nodes(self) -> None:
        graph = keel_dashboard.compute_graph(
            [], [_finished_group_row()], FINISH_EPOCH + keel_dashboard.GRAPH_FINISH_LINGER_SECONDS + 1
        )
        self.assertEqual(graph["nodes"], [])

    def test_the_window_boundary_is_inclusive(self) -> None:
        at_boundary = FINISH_EPOCH + keel_dashboard.GRAPH_FINISH_LINGER_SECONDS
        past_boundary = at_boundary + 1
        self.assertEqual(
            len(keel_dashboard.compute_graph([], [_finished_group_row()], at_boundary)["nodes"]), 1
        )
        self.assertEqual(
            keel_dashboard.compute_graph([], [_finished_group_row()], past_boundary)["nodes"], []
        )

    def test_an_open_handoff_already_reading_finished_lingers_the_same_way(self) -> None:
        """T103's own edge case - a ``subagent_stop`` matched before the
        launch tool's own return landed, so the row is still ``open_handoff``
        while already FINISHED. It lingers and expires exactly like a closed
        FINISHED group, off the same ``finished_ts``."""
        within = keel_dashboard.compute_graph([_finished_open_row()], [], FINISH_EPOCH + 10)
        self.assertEqual(len(within["nodes"]), 1)
        self.assertFalse(within["nodes"][0]["open"], "a FINISHED row is never OPEN on the canvas")
        past = keel_dashboard.compute_graph(
            [_finished_open_row()], [], FINISH_EPOCH + keel_dashboard.GRAPH_FINISH_LINGER_SECONDS + 1
        )
        self.assertEqual(past["nodes"], [])

    def test_an_awaited_node_lingers_and_expires_the_same_way_as_finished(self) -> None:
        """The design's other REAL end (see the module docstring's
        "BACKGROUNDED, AWAITED, FINISHED" section): AWAITED already marks an
        honest end even without a matched ``subagent_stop``, so it lingers
        off its own closing ``handoff_end`` the same way FINISHED lingers off
        its stop."""
        within = keel_dashboard.compute_graph([], [_awaited_group_row()], FINISH_EPOCH + 10)
        self.assertEqual(len(within["nodes"]), 1)
        self.assertEqual(within["nodes"][0]["delegation_state"], "awaited")
        past = keel_dashboard.compute_graph(
            [], [_awaited_group_row()], FINISH_EPOCH + keel_dashboard.GRAPH_FINISH_LINGER_SECONDS + 1
        )
        self.assertEqual(past["nodes"], [])

    def test_background_never_lingers_out_however_old_it_is(self) -> None:
        """A BACKGROUND card's ``handoff_end`` is a launch acknowledgment,
        never a real end (see [[a-recorded-end-is-not-a-finish]]) - it must
        never be swept off the canvas by a window meant for a REAL finish,
        however far ``now`` sits from it."""
        graph = keel_dashboard.compute_graph([], [_background_group_row()], FINISH_EPOCH + 10 ** 8)
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["delegation_state"], "background")

    def test_the_pre_existing_open_row_never_lingers_out_however_old_it_is(self) -> None:
        graph = keel_dashboard.compute_graph([_open_row()], [], FINISH_EPOCH + 10 ** 8)
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["delegation_state"], "open")

    def test_no_now_argument_falls_back_to_the_real_wall_clock(self) -> None:
        """The default is production's own: every caller that does not name
        a ``now`` reads the real clock, so a row finished moments ago is
        still drawn without any test needing to pass one."""
        with unittest.mock.patch.object(keel_dashboard.time, "time", return_value=FINISH_EPOCH + 5):
            graph = keel_dashboard.compute_graph([], [_finished_group_row()])
        self.assertEqual(len(graph["nodes"]), 1)


# --------------------------------------------- exactly-once, never duplicated


class TestExactlyOnceAcrossTheBoundary(unittest.TestCase):
    def test_the_lingering_node_is_the_same_node_never_a_second_shape(self) -> None:
        """Crossing the boundary changes MEMBERSHIP in ``nodes``, never the
        node's own identity: the same row drawn just inside the window is
        byte-for-byte the row T103 already drew, with no lingering-specific
        field grafted onto it."""
        row = _finished_group_row()
        graph = keel_dashboard.compute_graph([], [row], FINISH_EPOCH + 10)
        node = graph["nodes"][0]
        self.assertEqual(node["id"], "h0")
        self.assertNotIn("lingering", node)
        self.assertNotIn("linger", node)
        self.assertEqual(graph["counts"]["handoffs"], 1)
        self.assertEqual(len(graph["edges"]), 1)


# ------------------------------------------ the two parked, pill-free surfaces


class TestTheHeaderAndTheCanvasCannotDisagree(unittest.TestCase):
    """T109's own acceptance: the header's ``working`` count and the canvas's
    own ``open`` figure must never disagree about a FINISHED ``open_handoff``
    row - the exact disagreement T103's review carried forward."""

    def _lines(self) -> list[dict[str, Any]]:
        """A genuinely reachable FINISHED ``open_handoff``: T103's own note on
        ``launch_agent_id`` reads the launch's own ``agent_id`` FIRST, "for
        a harness that came to expose the id at launch time" - so a start
        that carries its own ``agent_id`` can be matched to a stop with NO
        ``handoff_end`` ever landing, and its row stays ``open_handoff``
        while reading FINISHED (T103's own ``_match_finish_events`` does
        this without any change here). ``_handoff`` alone cannot build this
        shape - it only ever puts ``agent_id`` on the END - so this hand-off
        is built directly.
        """
        lines = [{"v": 1, "ts": "2030-06-01T11:00:00Z", "event": "session_start", "session": "s1"}]
        lines += _handoff("s1", "still-open", "keel:executor", "still working",
                           "2030-06-01T11:50:00Z")
        lines.append({
            "v": 1, "ts": "2030-06-01T11:55:00Z", "event": "handoff_start", "session": "s1",
            "tool_use_id": "finished-open", "agent_id": STOP_AGENT_ID,
            "subagent_type": "keel:executor", "description": "finished before its own return",
        })
        lines.append(_stop("s1", "keel:executor", FINISH_TS))
        return lines

    def _state_at(self, now_epoch: float) -> dict[str, Any]:
        with unittest.mock.patch.object(keel_dashboard.time, "time", return_value=now_epoch):
            with tempfile.TemporaryDirectory() as tmp:
                return keel_dashboard.read_state(_project(Path(tmp), self._lines()))

    def test_a_finished_open_handoff_is_excluded_from_working_and_from_the_canvas_alike(
        self,
    ) -> None:
        state = self._state_at(FINISH_EPOCH + 5)
        self.assertEqual(state["counts"]["working"], 1, "only the genuinely OPEN one")
        finished_row = next(
            item for item in state["open"] if item["description"] == "finished before its own return"
        )
        self.assertEqual(finished_row["delegation_state"], "finished")
        node = next(
            n for n in state["graph"]["nodes"] if n["task_label"] == "finished before its own return"
        )
        self.assertFalse(node["open"])
        self.assertEqual(
            state["counts"]["working"],
            sum(1 for n in state["graph"]["nodes"] if n["open"]),
            "the header figure and the canvas's own open count must agree",
        )

    def test_past_the_linger_window_the_finished_card_leaves_but_the_roster_keeps_the_run(
        self,
    ) -> None:
        state = self._state_at(FINISH_EPOCH + keel_dashboard.GRAPH_FINISH_LINGER_SECONDS + 1)
        tasks = [n["task_label"] for n in state["graph"]["nodes"]]
        self.assertNotIn("finished before its own return", tasks)
        self.assertIn("still working", tasks, "a genuinely open hand-off never lingers out")
        roster = {row["agent_type"]: row for row in state["roster"]}
        self.assertEqual(roster["keel:executor"]["runs"], 2, "the roster still counts both runs")


class TestTheOpenFeedRowWording(unittest.TestCase):
    """``openRow`` (page-source, since no browser runs in this suite - see
    this module's "Values, not substrings")."""

    def test_the_row_says_finished_not_open_for_a_finished_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        row = _functions(_script(text))["openRow"]
        self.assertIn('o.delegation_state === "finished"', row)
        self.assertIn("FINISHED", row)
        self.assertIn('"OPEN"', row)

    def test_the_ticker_keeps_stating_finished_rather_than_resuming_a_tick(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        live = _functions(_script(text))["updateOpenRowLive"]
        self.assertIn('o.delegation_state === "finished"', live)


if __name__ == "__main__":
    unittest.main()
