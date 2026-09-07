#!/usr/bin/env python3
"""T106 - a worker card opens the SAME panel T105 built, on its own lines.

Contract
--------
Reads   : temporary directories this file creates, and its own module source
          through ``inspect`` - no fixture here touches this repository's own
          ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
T105 gave the centre session node a drawer that shows the session's OWN
lines. This task extends that SAME drawer to a worker card: clicking a
delegation on the canvas, or a roster chip naming one, opens it on that
delegation's own header and its own attributed lines instead.

THE load-bearing claim, as it was for T105: the lines a worker's panel shows
are the group's own ``events`` - the SAME list ``_attribute_activity`` built
and ``graph_count_label``/the feed's collapsed card already read - never a
second attribution pass. An OPEN hand-off has no such group yet, so its
panel carries none, worded with the SAME string a closed card with zero
lines already uses (``NO_ACTIVITY_ATTRIBUTED_NOTE``).

Values, not substrings
-----------------------
Everything the panel SAYS is asserted as a value read off ``read_state``, as
``test_keel_dashboard_t28_31.py`` documents. The page-source checks below are
for structural claims a value cannot express - which function may reach
which, what markup a click handler carries - and say so in their own
docstrings.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from typing import Any
import unittest
import unittest.mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    FRESHNESS_NODE,
    PANE_MARKUP,
    _block_after,
    _functions,
    _graph_fixture,
    _handoff,
    _page,
    _project,
    _reachable,
    _script,
    _sole_function_containing,
)
from test_keel_dashboard_t105 import SESSION, _mixed_fixture, _state  # noqa: E402


def _group_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in state["graph"]["nodes"] if n["row_kind"] == "group"]


# ---------------------------------------------- the panel reads no second copy


class TestTheWorkerPanelPayloadIsTheGroupsOwnLines(unittest.TestCase):
    """THE claim of this task, restated for a worker card: its lines are the
    SAME ``events`` the closed group already carries - not a second search."""

    def test_the_panel_payload_is_exactly_the_groups_own_lines(self) -> None:
        state = _state(_mixed_fixture())
        feed_groups = [row for row in state["feed"] if row["row_kind"] == "group"]
        self.assertEqual(len(feed_groups), 1)
        nodes = _group_nodes(state)
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["events"], feed_groups[0]["events"])
        self.assertEqual(
            {member["detail"] for member in nodes[0]["events"]},
            {"src/worker-one.py", "src/worker-two.py"},
        )

    def test_a_delegations_lines_are_not_duplicated_in_the_flat_feed(self) -> None:
        """The exactly-once law, read from the worker card's own side: a line
        its panel lists is owned by the group, never also by a flat feed row."""
        state = _state(_mixed_fixture())
        flat_details = {row.get("detail") for row in state["feed"] if row["row_kind"] == "event"}
        for member in _group_nodes(state)[0]["events"]:
            with self.subTest(detail=member["detail"]):
                self.assertNotIn(member["detail"], flat_details)

    def test_an_open_hand_offs_panel_carries_no_group_it_does_not_have(self) -> None:
        """An open hand-off has no closed group to read lines from yet - its
        panel says so rather than borrowing a candidate list T30 built for a
        different, weaker signal (``_unclaimed_activity``/``_quiet_facts``)."""
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "t1", "keel:executor", "still open",
                          "2026-08-01T10:00:00Z")
        lines.append({"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "activity",
                      "session": SESSION, "agent_type": "keel:executor", "tool": "Edit",
                      "detail": "src/still-running.py"})
        state = _state(lines)
        node = next(n for n in state["graph"]["nodes"] if n["row_kind"] == "open_handoff")
        self.assertEqual(node["events"], [])
        self.assertEqual(node["activity_note"], keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE)


# ------------------------------------------------- the existing vocabulary


class TestANodeWithNoLinesReusesTheExistingWords(unittest.TestCase):
    def test_the_note_is_the_same_string_the_cards_own_count_label_uses(self) -> None:
        """Reused, not reinvented: one constant, read by both."""
        self.assertEqual(keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE, "no activity attributed")
        self.assertEqual(keel_dashboard.graph_count_label(0, 0),
                         keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE)

    def test_a_closed_group_with_zero_events_says_so_plainly(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "t1", "keel:executor", "nothing happened inside it",
                          "2026-08-01T09:10:00Z", "2026-08-01T09:11:00Z")
        state = _state(lines)
        node = _group_nodes(state)[0]
        self.assertEqual(node["events"], [])
        self.assertEqual(node["activity_note"], keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE)
        self.assertEqual(node["count_label"], keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE)


# ------------------------------------------------ inferred marking passes through


class TestInferredMarkingPassesThroughToThePanel(unittest.TestCase):
    def test_a_member_the_group_could_not_attribute_stays_marked_in_the_panel(self) -> None:
        """The SAME tie-break ``_attribute_activity`` already made - a nested
        hand-off of the same type wins an ambiguous line - reaches the panel
        with the SAME marker the collapsed card already carries, never a
        second reading of which hand-off ran it."""
        lines = [{"v": 1, "ts": "2026-08-01T08:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "outer", "keel:executor", "outer",
                          "2026-08-01T09:00:00Z", "2026-08-01T09:30:00Z")
        lines += _handoff(SESSION, "inner", "keel:executor", "inner",
                          "2026-08-01T09:10:00Z", "2026-08-01T09:20:00Z")
        lines.append({"v": 1, "ts": "2026-08-01T09:15:00Z", "event": "activity",
                      "session": SESSION, "agent_type": "keel:executor", "tool": "Edit",
                      "detail": "src/ambiguous.py"})
        state = _state(lines)
        by_task = {n["task_label"]: n for n in _group_nodes(state)}
        inner, outer = by_task["inner"], by_task["outer"]
        self.assertEqual(len(inner["events"]), 1)
        self.assertEqual(inner["events"][0]["detail"], "src/ambiguous.py")
        self.assertTrue(inner["events"][0]["inferred"])
        self.assertEqual(outer["events"], [])
        self.assertEqual(outer["activity_note"], keel_dashboard.NO_ACTIVITY_ATTRIBUTED_NOTE)


# ------------------------------------------------- the roster chip's own route


class TestARosterChipResolvesToTheMostRecentDelegation(unittest.TestCase):
    def test_the_roster_entry_carries_the_most_recent_cards_own_key(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "first", "keel:executor", "first",
                          "2026-08-01T09:00:00Z", "2026-08-01T09:05:00Z")
        lines += _handoff(SESSION, "second", "keel:executor", "second",
                          "2026-08-01T10:00:00Z", "2026-08-01T10:05:00Z")
        state = _state(lines)
        by_task = {n["task_label"]: n for n in _group_nodes(state)}
        newest = keel_dashboard.latest_node_of_agent_type(
            state["graph"]["nodes"], "keel:executor"
        )
        self.assertEqual(newest["task_label"], "second")
        roster = {r["agent_type"]: r for r in state["roster"]}
        self.assertEqual(
            roster["keel:executor"]["node_key"],
            keel_dashboard._node_key(by_task["second"]),
        )
        self.assertNotEqual(
            roster["keel:executor"]["node_key"],
            keel_dashboard._node_key(by_task["first"]),
        )

    def test_a_type_with_no_card_currently_drawn_carries_no_key(self) -> None:
        """The roster spans every session the log ever saw; the canvas draws
        only the one most recently active. A chip naming a type that lives
        only in a session the canvas is not drawing has nothing to open."""
        lines = [{"v": 1, "ts": "2026-08-01T08:00:00Z",
                  "event": "session_start", "session": "s2"}]
        lines += _handoff("s2", "old", "keel:auditor", "an older session's own work",
                          "2026-08-01T08:00:00Z", "2026-08-01T08:05:00Z")
        lines.append({"v": 1, "ts": "2026-08-01T09:00:00Z",
                      "event": "session_start", "session": "s1"})
        lines += _handoff("s1", "new", "keel:researcher", "the session the canvas draws",
                          "2026-08-01T09:00:00Z", "2026-08-01T09:05:00Z")
        state = _state(lines)
        self.assertEqual(state["graph"]["session"], "s1")
        roster = {r["agent_type"]: r for r in state["roster"]}
        self.assertIsNone(roster["keel:auditor"]["node_key"])
        self.assertIsNotNone(roster["keel:researcher"]["node_key"])

    def test_the_key_is_absent_when_the_agent_type_has_no_node_at_all(self) -> None:
        self.assertIsNone(keel_dashboard.latest_node_of_agent_type([], "keel:executor"))


# --------------------------------------------- the panel is the SAME panel


class TestTheWorkerPanelIsTheSamePanelT105Built(unittest.TestCase):  # keel-leak: ignore - CamelCase class name caught by the entropy heuristic
    """No second aside, no second open/close mechanism: a worker card and a
    roster chip both drive the ONE writer T105 already built
    (``setNodePanel``), which still touches its own node and nothing else."""

    def _script(self, lines: list[dict[str, Any]]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return _script(_page(_project(Path(tmp), lines)))

    def test_a_worker_card_opens_the_drawer_through_the_one_writer(self) -> None:
        script = self._script(_graph_fixture())
        handler = _block_after(script, '$("canvas").addEventListener("click"')
        self.assertIn('closest(".node")', handler)
        self.assertIn("setNodePanel(", handler)
        self.assertIn("card.dataset.key", handler)

    def test_a_roster_chip_opens_the_drawer_through_the_one_writer(self) -> None:
        script = self._script(_graph_fixture())
        handler = _block_after(script, '$("roster").addEventListener("click"')
        self.assertIn("setNodePanel(", handler)
        self.assertIn("chip.dataset.nodeKey", handler)
        functions = _functions(script)
        self.assertIn("data-node-key", functions["roster"])

    def test_the_writer_reaches_the_delegation_panel_and_nothing_forbidden(self) -> None:
        """Reachability, not one call site: the writer both a worker card and
        a roster chip drive must be able to build the delegation panel, and
        must still reach none of the feed pane, the freshness node or a
        canvas rebuild - the exact property T105 pinned for the root panel,
        now re-checked with the worker branch present too."""
        script = self._script(_graph_fixture())
        functions = _functions(script)
        writer = _sole_function_containing(functions, "panelOpen =")
        reach = _reachable(functions, writer) | {writer}
        self.assertIn("delegationPanel", reach)
        for forbidden in (
            _sole_function_containing(functions, PANE_MARKUP),
            _sole_function_containing(functions, FRESHNESS_NODE),
            _sole_function_containing(functions, '$("canvas").innerHTML'),
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, reach)
        for name in reach:
            with self.subTest(name=name):
                self.assertNotIn("fetch(", functions[name])
                self.assertNotIn("Date.now()", functions[name])

    def test_the_header_carries_agent_type_task_elapsed_and_open_state(self) -> None:
        panel = _functions(self._script(_graph_fixture()))["delegationPanel"]
        for field in ("n.agent_label", "n.task_label", "n.state_label", "n.open"):
            with self.subTest(field=field):
                self.assertIn(field, panel)
        self.assertIn('type="button"', panel)
        self.assertIn('data-role="closepanel"', panel)

    def test_the_lines_are_rendered_through_the_same_evrow_as_the_collapsed_card(
        self,
    ) -> None:
        """Same marker, same vocabulary (criterion 2): the panel does not own
        a second renderer for an inferred line - it reuses ``evRow``, the
        very function the feed's own collapsed group already draws its
        members with (``groupRow``). T120 addendum: both call sites now pass
        ``now`` through for the row's own ticking relative time - ``evRow``
        is still the one function either place calls, never a duplicate."""
        script = self._script(_graph_fixture())
        functions = _functions(script)
        self.assertIn("n.events || []", functions["delegationPanel"])
        self.assertIn(".map(e => evRow(e, now))", functions["delegationPanel"])
        self.assertIn(".map(e => evRow(e, now))", functions["groupRow"])
        self.assertIn("n.activity_note", functions["delegationPanel"])

    def test_closing_resets_which_panel_the_drawer_shows(self) -> None:
        script = self._script(_graph_fixture())
        writer = _sole_function_containing(_functions(script), "panelOpen =")
        body = _functions(script)[writer]
        self.assertIn("panelNodeKey = open ? (nodeKey || null) : null;", body)

    def test_a_click_on_bare_canvas_ground_still_opens_neither_panel(self) -> None:
        script = self._script(_graph_fixture())
        handler = _block_after(script, '$("canvas").addEventListener("click"')
        self.assertIn('closest(".rootnode")', handler)
        self.assertIn('closest(".node")', handler)
        self.assertNotIn("innerHTML", handler)


# --------------------------------- review fix: the header's elapsed ticks too


class TestThePanelsElapsedTicksExactlyWhenTheCardsDoes(unittest.TestCase):
    """Review finding on the first pass: the panel's elapsed text was
    computed once at render and never advanced again, so an OPEN or
    BACKGROUND delegation's card kept ticking while its own open panel froze.
    Fixed the way the page already fixes this twice - ``updateOpenRowLive``
    for an open row and a card, ``tickRoster`` for a resting chip - by
    marking the SAME span shape and extending the SAME guarded walk, never a
    second writer."""

    def _script(self, lines: list[dict[str, Any]]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return _script(_page(_project(Path(tmp), lines)))

    def test_the_elapsed_figure_is_marked_for_the_ticker_exactly_when_ticking(
        self,
    ) -> None:
        """The SAME gate the card itself uses (``n.ticking`` - true only for
        an OPEN hand-off or a BACKGROUND pair, per ``compute_graph``): when
        it holds, the elapsed figure is wrapped in the outer ``data-key`` /
        inner ``data-role="elapsed"`` shape a card already carries; when it
        does not, the figure is the plain fixed ``duration_label`` with no
        ``data-key`` at all, so the ticker can never find it."""
        panel = _functions(self._script(_graph_fixture()))["delegationPanel"]
        match = re.search(
            r"const elapsed = n\.ticking\s*\?\s*(.+?)\s*:\s*(.+?);\n", panel, re.S
        )
        self.assertIsNotNone(match, "no `n.ticking` ternary building `elapsed` was found")
        ticking_branch, fixed_branch = match.group(1), match.group(2)
        self.assertIn('data-key="${esc(openRowKey(n))}"', ticking_branch)
        self.assertIn('data-role="elapsed"', ticking_branch)
        self.assertNotIn("data-key", fixed_branch)
        self.assertIn("n.duration_label", fixed_branch)

    def test_the_ticker_walks_the_panel_through_the_same_map_and_writer(self) -> None:
        """No dedicated writer for the panel: the same ``tickOpenRows`` that
        already updates a feed row and a canvas card now also walks
        ``#nodepanel``, through the very same ``byKey`` lookup and the very
        same ``updateOpenRowLive`` - so the panel can never show an age the
        card it mirrors does not."""
        script = self._script(_graph_fixture())
        functions = _functions(script)
        walker = _sole_function_containing(functions, "#canvas .node[data-key]")
        self.assertEqual(walker, "tickOpenRows")
        body = functions[walker]
        self.assertIn("#nodepanel [data-key]", body)
        # exactly one map, one call to the shared writer, one `live` walker
        # used by three selectors - the panel's own walk was added to the
        # EXISTING loop, not given a second map or a second writer.
        self.assertEqual(body.count("new Map()"), 1)
        self.assertEqual(body.count("updateOpenRowLive"), 1)
        self.assertEqual(body.count(".forEach(live)"), 3)

    def test_the_ticker_can_rewrite_only_the_elapsed_and_quiet_text(self) -> None:
        """``updateOpenRowLive`` is the ONE writer both the card's walk and
        the panel's now share, and it touches exactly two ``textContent``s,
        both found by ``data-role`` - never the panel's agent type, task or
        state words, which carry no ``data-role`` a ticker could find them
        by at all."""
        script = self._script(_graph_fixture())
        functions = _functions(script)
        writer = _sole_function_containing(functions, '[data-role="elapsed"]')
        self.assertEqual(writer, "updateOpenRowLive")
        body = functions[writer]
        self.assertEqual(body.count("textContent"), 2)
        self.assertIn('data-role="quiet"', body)
        self.assertNotIn("innerHTML", body)
        panel = functions["delegationPanel"]
        for forbidden in ('data-role="agent"', 'data-role="task"', 'data-role="state"'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, panel)

    def test_an_open_and_a_background_node_both_tick_awaited_and_finished_never_do(
        self,
    ) -> None:
        """The data-level half of the same claim, against real fixtures: the
        four states ``compute_graph`` can hand the panel, and which of them
        ``n.ticking`` says should move."""
        # T109: the AWAITED pair below is a real end, fixed to a 2026-08-01
        # timestamp far outside the real-clock finish-linger window
        # ``compute_graph`` now checks it against - patched out here so this
        # test keeps asserting what it always asserted (ticking, by state),
        # not whether the pair is still young enough to be drawn at all.
        with unittest.mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 10**9):
            with tempfile.TemporaryDirectory() as tmp:
                state = keel_dashboard.read_state(_project(Path(tmp), [
                    {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start",
                     "session": "s1"},
                    # OPEN: no end at all.
                    *_handoff("s1", "open1", "keel:executor", "still running",
                              "2026-08-01T09:00:00Z"),
                    # BACKGROUND: a quick handoff_end acknowledgment, no subagent_stop.
                    *_handoff("s1", "bg1", "keel:executor", "backgrounded",
                              "2026-08-01T09:05:00Z", "2026-08-01T09:05:00Z"),
                    # AWAITED: a genuinely slow return, well past the background
                    # threshold, no subagent_stop either.
                    *_handoff("s1", "await1", "keel:executor", "awaited",
                              "2026-08-01T09:10:00Z", "2026-08-01T09:20:00Z"),
                ]))
        by_task = {n["task_label"]: n for n in state["graph"]["nodes"]}
        self.assertTrue(by_task["still running"]["ticking"])
        self.assertTrue(by_task["backgrounded"]["ticking"])
        self.assertFalse(by_task["awaited"]["ticking"])


if __name__ == "__main__":
    unittest.main()
