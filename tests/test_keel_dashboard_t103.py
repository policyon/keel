#!/usr/bin/env python3
"""T103 - a worker card tells BACKGROUNDED, AWAITED and FINISHED apart.

Contract
--------
Reads   : temporary directories this file creates, and nothing else - no
          fixture here touches this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
A delegation's pill on the canvas now reads one of three honest states
(``compute_open_and_groups``/``compute_graph`` in ``scripts/keel_dashboard.py``):

* BACKGROUND - a closed pair whose ``handoff_end`` landed within
  ``keel_stop.BG_LAUNCH_MS`` of its own ``handoff_start`` - a launch
  acknowledgment, not a completion (see
  [[a-recorded-end-is-not-a-finish]]). The card's elapsed figure ticks from
  the START against wall clock, never from the near-instant end, and the
  card states in words that the record cannot yet say it ended.
* AWAITED - a closed pair whose gap meets or exceeds that threshold: the
  session was genuinely blocked on it, so the return already marks a real
  end and the elapsed figure is the fixed span between the two timestamps.
* FINISHED - a ``subagent_stop`` (T101) is matched to the hand-off
  (``_match_finish_events``), overriding either of the above with a
  DIFFERENT pill (a checkmark class, never a dimmed copy of the running
  pill) and a fixed elapsed figure computed from the real end.

Also covered: the threshold is read from ``hooks/keel_stop.BG_LAUNCH_MS``
rather than restated, the last-action line reuses the collapsed group's own
attribution rather than a second computation, and the honesty rules already
proven for this page (no model, no tier, never stalled/hung/stuck) still
hold on every one of the new fields.

Values, not substrings
-----------------------
Every one of the three states is asserted as a VALUE read off
``compute_open_and_groups``/``compute_graph`` directly - the same discipline
``test_keel_dashboard_t28_31.py`` documents in its own module docstring.
The handful of page-source checks below are for structural claims a value
cannot express (which CSS class differs, which fields the canvas card's own
renderer escapes) and say so in their own docstrings.

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
from pathlib import Path
from typing import Any
import unittest
import unittest.mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402  (path must be set first)
import keel_stop  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    _functions,
    _graph_fixture,
    _handoff,
    _page,
    _project,
    _script,
    _style,
)


def _state(lines: list[dict[str, Any]]) -> dict[str, Any]:
    # T109: this file's fixtures build BACKGROUND, AWAITED and FINISHED pairs
    # from fixed 2026-08-01 timestamps to test the STATE distinction itself,
    # never how long a real end lingers on the canvas before it leaves - that
    # boundary is this task's own and is asserted directly against
    # ``compute_graph``, with an explicit ``now``, in
    # ``test_keel_dashboard_t109.py``. Patched out here, at the one place
    # every test in this file reads state through, so an AWAITED or FINISHED
    # card built a decade before "now" keeps being drawn.
    with unittest.mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 10**9):
        with tempfile.TemporaryDirectory() as tmp:
            return keel_dashboard.read_state(_project(Path(tmp), lines))


#: The join key T102 gave these fixtures. A stop and the launch's own return
#: carry the same value; nothing else pairs them.
STOP_AGENT_ID = "a1111111111111111"


def _stop(session: str, agent: str, ts: str, agent_id: str | None = STOP_AGENT_ID) -> dict[str, Any]:
    """One ``subagent_stop`` line, T101's shape plus T102's key."""
    return {
        "v": 1, "ts": ts, "event": "subagent_stop", "session": session,
        "agent_id": agent_id, "agent_type": agent,
    }


def _activity(session: str, agent: str, ts: str, detail: str) -> dict[str, Any]:
    return {
        "v": 1, "ts": ts, "event": "activity", "session": session,
        "agent_type": agent, "tool": "Edit", "detail": detail,
    }


# ---------------------------------------------------------- the threshold


class TestTheThresholdIsImportedNotRestated(unittest.TestCase):
    def test_the_dashboard_reads_the_gates_own_constant(self) -> None:
        """A second copy of ``BG_LAUNCH_MS`` is exactly the drift T101's SF1
        finding was about - this must be the SAME object, not a coincidence
        of two literals agreeing today."""
        self.assertIs(keel_dashboard.BG_LAUNCH_MS, keel_stop.BG_LAUNCH_MS)
        self.assertEqual(keel_dashboard.BG_LAUNCH_MS, 5000)

    def test_the_dashboard_reuses_the_gates_own_matcher(self) -> None:
        """T102's collapse, pinned as OBJECT IDENTITY rather than behaviour.

        This used to pin ``same_agent_type``, the one comparison inside a
        matching loop this module carried its own copy of. There is no local
        loop left to hold a predicate: ``_match_finish_events`` calls the
        gate's own matcher, so what has to be the same object is the
        algorithm, not one line of it. A module that reimported the predicate
        and grew a loop back would fail here by not having these names.
        """
        self.assertIs(
            keel_dashboard.match_stops_to_launches, keel_stop.match_stops_to_launches
        )
        self.assertIs(keel_dashboard.launch_agent_id, keel_stop.launch_agent_id)
        self.assertFalse(
            hasattr(keel_dashboard, "same_agent_type"),
            "the viewer no longer matches on agent type; an import of the "
            "type predicate means a local matching loop has regrown",
        )


# ------------------------------------------------------- _delegation_state


class TestDelegationStateFunction(unittest.TestCase):
    """Direct value tests of the one function the whole distinction runs
    through - breaking any branch here breaks a card's pill."""

    def test_a_finish_event_wins_over_everything_else(self) -> None:
        self.assertEqual(keel_dashboard._delegation_state(True, 100.0, True), "finished")
        self.assertEqual(keel_dashboard._delegation_state(False, None, True), "finished")

    def test_no_end_at_all_is_the_pre_existing_open_case(self) -> None:
        self.assertEqual(keel_dashboard._delegation_state(False, None, False), "open")

    def test_a_quick_return_is_background_not_done(self) -> None:
        self.assertEqual(keel_dashboard._delegation_state(True, 0.0, False), "background")
        self.assertEqual(
            keel_dashboard._delegation_state(True, keel_dashboard.BG_LAUNCH_MS - 1, False),
            "background",
        )

    def test_a_return_at_or_past_the_threshold_is_awaited(self) -> None:
        self.assertEqual(
            keel_dashboard._delegation_state(True, keel_dashboard.BG_LAUNCH_MS, False),
            "awaited",
        )
        self.assertEqual(keel_dashboard._delegation_state(True, 600000.0, False), "awaited")

    def test_an_unparseable_gap_fails_toward_background_not_awaited(self) -> None:
        """The same direction ``hooks/keel_stop.py`` already fails in for an
        unparseable pair - AWAITED is the stronger claim (a confirmed real
        end) and must never be asserted from a gap this module could not
        actually read."""
        self.assertEqual(keel_dashboard._delegation_state(True, None, False), "background")


# --------------------------------------------------- the three card states


class TestTheThreeCardStates(unittest.TestCase):
    """Each state end to end, through ``read_state`` - a real fixture, not
    just the helper function above."""

    def test_a_quick_return_reads_background_and_ticks_from_its_own_start(self) -> None:
        """THE defect this task exists to fix: a backgrounded launch whose
        ``handoff_end`` landed seconds after its ``handoff_start`` must never
        read as finished, and its elapsed figure must be computed from the
        START (so it keeps growing), never frozen at the tiny gap."""
        lines = _handoff(
            "s1", "A", "keel:executor", "a background launch",
            "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z",
        )
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "background")
        self.assertEqual(node["state_label"], "background")
        self.assertTrue(node["ticking"])
        self.assertEqual(node["ts"], "2026-08-01T10:00:00Z", "elapsed must tick from START")
        self.assertEqual(node["duration_label"], "", "not a fixed figure while it ticks")
        self.assertIn("cannot yet say it ended", node["state_note"])

    def test_a_genuinely_awaited_call_reads_awaited_with_a_fixed_span(self) -> None:
        lines = _handoff(
            "s1", "A", "keel:executor", "a synchronous call",
            "2026-08-01T10:00:00Z", "2026-08-01T10:09:00Z",
        )
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "awaited")
        self.assertEqual(node["state_label"], "awaited")
        self.assertFalse(node["ticking"])
        self.assertEqual(node["duration_label"], "9m 0s")
        self.assertEqual(node["state_note"], "", "only BACKGROUND adds the extra sentence")

    def test_a_matched_stop_reads_finished_with_the_real_total(self) -> None:
        """A background launch that later gets a T101 finish event is
        promoted to FINISHED - a different pill, with the one honest total
        the record can finally state (start to the stop's own timestamp)."""
        lines = _handoff(
            "s1", "A", "keel:executor", "a background launch that finished",
            "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z", agent_id=STOP_AGENT_ID,
        )
        lines.append(_stop("s1", "keel:executor", "2026-08-01T10:05:32Z"))
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "finished")
        self.assertEqual(node["state_label"], "✓ finished")
        self.assertFalse(node["ticking"])
        self.assertEqual(node["duration_label"], "5m 32s")
        self.assertEqual(node["state_note"], "")

    def test_a_stop_arriving_before_the_return_finishes_nothing_yet(self) -> None:
        """WHAT T102 TRADED, stated as a test rather than left to be noticed.

        This case used to assert that a ``subagent_stop`` arriving before any
        ``handoff_end`` still read FINISHED. It cannot, and the reason is the
        join key itself: a delegation is NAMED by its launch tool's result, so
        until that result lands the page holds no id for this hand-off and no
        stop can be shown to be its. That window is real and it is short - a
        foreground return lands two or three seconds after the stop, measured
        in this repository's own log - and the honest reading inside it is the
        pre-existing OPEN one, not a card finished by resemblance.

        BOTH HALVES ARE ASSERTED, so this is a trade and not a loss: without
        the return the card stays OPEN and keeps ticking; the moment the
        return lands and names the agent, the same stop finishes it with the
        real total.
        """
        lines = _handoff("s1", "A", "keel:executor", "still open, then stopped",
                         "2026-08-01T10:00:00Z")
        lines.append(_stop("s1", "keel:executor", "2026-08-01T10:03:00Z"))
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "open")
        self.assertTrue(node["ticking"])

        with_return = _handoff(
            "s1", "A", "keel:executor", "still open, then stopped",
            "2026-08-01T10:00:00Z", "2026-08-01T10:03:02Z", agent_id=STOP_AGENT_ID,
        )
        with_return.append(_stop("s1", "keel:executor", "2026-08-01T10:03:00Z"))
        node = _state(with_return)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "finished")
        self.assertFalse(node["ticking"])
        self.assertEqual(node["duration_label"], "3m 0s")

    def test_the_pre_existing_open_card_is_unaffected_by_this_task(self) -> None:
        """A hand-off with no end and no stop keeps EXACTLY its pre-existing
        OPEN reading - this task adds states, it does not rename this one."""
        lines = _handoff("s1", "A", "keel:executor", "still open",
                         "2026-08-01T10:00:00Z")
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["delegation_state"], "open")
        self.assertEqual(node["state_label"], "open")
        self.assertTrue(node["ticking"])
        self.assertTrue(node["open"])
        self.assertEqual(node["state_note"], "")

    def test_finished_is_a_different_pill_never_a_dimmed_running_one(self) -> None:
        """The reference's own distinction: FINISHED gets its own CSS class,
        never shared with the ``.pill.live`` treatment BACKGROUND/OPEN use."""
        style = _style(_page(_project(Path(tempfile.mkdtemp()), [])))
        self.assertIn(".pill.st-finished", style)
        finished_rule = style.split(".pill.st-finished{")[1].split("}")[0]
        live_rule = style.split(".pill.live{")[1].split("}")[0]
        self.assertNotEqual(finished_rule, live_rule)


# --------------------------------------------------------- last-action line


class TestTheLastActionLine(unittest.TestCase):
    """Drawn from the SAME attribution the collapsed group already carries -
    never a second computation, and omitted where there is nothing to show."""

    def test_a_closed_groups_last_action_is_its_own_last_attributed_detail(self) -> None:
        lines = _handoff("s1", "A", "keel:executor", "wrote a file",
                         "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z")
        lines.append(_activity("s1", "keel:executor", "2026-08-01T10:00:01Z", "src/one.py"))
        lines.append(_activity("s1", "keel:executor", "2026-08-01T10:00:02Z", "src/two.py"))
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["last_action"], "src/two.py", "the LAST attributed line, not any")

    def test_no_attributable_activity_omits_the_line_rather_than_guessing(self) -> None:
        lines = _handoff("s1", "A", "keel:executor", "nothing attributed",
                         "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z")
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["last_action"], "")

    def test_an_open_hand_offs_last_action_is_its_own_quiet_time_winner(self) -> None:
        """The SAME entry ``last_seen_ts`` was already read off - not a
        second search - so a card and its own quiet-time figure can never
        name two different last actions."""
        lines = _handoff("s1", "A", "keel:executor", "still going",
                         "2026-08-01T10:00:00Z")
        lines.append(_activity("s1", "keel:executor", "2026-08-01T10:00:05Z", "src/live.py"))
        node = _state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["last_action"], "src/live.py")

    def test_the_card_omits_the_line_when_last_action_is_blank(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), _handoff(
                "s1", "A", "keel:executor", "no last action",
                "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z",
            )))
        card = _functions(_script(text))["nodeCard"]
        self.assertIn("n.last_action", card)
        self.assertIn('n.last_action ?', card, "the line is conditional, never unconditional")


# ------------------------------------------------------ _match_finish_events


class TestMatchFinishEvents(unittest.TestCase):
    """T102's collapse, at the viewer's own call site.

    These cases were written for the type-and-time rule this function used to
    carry a copy of - "the stop closes the most recently launched start of the
    same type". That rule is gone from all three readers, so the cases assert
    the one that replaced it: the stop closes the launch whose ``agent_id`` it
    NAMES, and matches nothing when no launch is named. The signature grew an
    ``ends`` argument for the same reason - a launch's id lives on its return.
    """

    A_ID = "a" + "1" * 16
    B_ID = "a" + "2" * 16

    def _launch(self, tool_use_id: str, ts: str, agent_id: str | None) -> tuple[
        dict[str, Any], dict[str, Any]
    ]:
        """A start and the return that names its agent, as capture writes them."""
        start = {
            "ts": ts, "event": "handoff_start", "tool_use_id": tool_use_id,
            "agent_id": None, "subagent_type": "keel:executor",
        }
        end = dict(start, event="handoff_end", agent_id=agent_id)
        return start, end

    def test_a_blank_agent_id_on_either_side_matches_nothing(self) -> None:
        """``None == None`` is True, and that is the false match."""
        start, end = self._launch("tu_1", "2026-08-01T10:00:00Z", None)
        stops = [{"ts": "2026-08-01T10:01:00Z", "agent_id": None}]
        self.assertEqual(keel_dashboard._match_finish_events([start], [end], stops), {})

        start2, end2 = self._launch("tu_2", "2026-08-01T10:00:00Z", self.A_ID)
        self.assertEqual(
            keel_dashboard._match_finish_events([start2], [end2], stops), {}
        )
        blank_stop = [{"ts": "2026-08-01T10:01:00Z", "agent_id": self.A_ID}]
        self.assertEqual(
            keel_dashboard._match_finish_events([start], [end], blank_stop), {}
        )

    def test_a_stop_naming_another_agent_finishes_nothing_here(self) -> None:
        start, end = self._launch("tu_1", "2026-08-01T10:00:00Z", self.A_ID)
        stops = [{"ts": "2026-08-01T10:05:00Z", "agent_id": self.B_ID}]
        self.assertEqual(keel_dashboard._match_finish_events([start], [end], stops), {})

    def test_two_open_of_one_type_are_told_apart_by_the_id(self) -> None:
        """THE CASE THE OLD RULE GOT WRONG, asserted in the direction it got
        wrong: the stop names the OLDER of two same-type delegations, and the
        old tie-break would have finished the newer one's card."""
        older, older_end = self._launch("tu_a", "2026-08-01T10:00:00Z", self.A_ID)
        newer, newer_end = self._launch("tu_b", "2026-08-01T10:02:00Z", self.B_ID)
        stops = [{"ts": "2026-08-01T10:05:00Z", "agent_id": self.A_ID}]
        finished = keel_dashboard._match_finish_events(
            [older, newer], [older_end, newer_end], stops
        )
        self.assertEqual(set(finished), {id(older)}, "the wrong card read finished")

    def test_the_id_is_read_from_the_return_not_the_launch(self) -> None:
        """The launch half records a null by construction, so a page given no
        returns can finish nothing - and the same page given them can."""
        start, end = self._launch("tu_1", "2026-08-01T10:00:00Z", self.A_ID)
        stops = [{"ts": "2026-08-01T10:05:00Z", "agent_id": self.A_ID}]
        self.assertEqual(keel_dashboard._match_finish_events([start], [], stops), {})
        self.assertEqual(
            set(keel_dashboard._match_finish_events([start], [end], stops)),
            {id(start)},
        )

    def test_a_return_naming_another_tool_call_lends_no_id(self) -> None:
        """The return is resolved by ``tool_use_id`` alone - no FIFO fallback,
        so an id can never be lifted from somebody else's return."""
        start, _ = self._launch("tu_1", "2026-08-01T10:00:00Z", self.A_ID)
        _, other_end = self._launch("tu_9", "2026-08-01T10:00:00Z", self.A_ID)
        stops = [{"ts": "2026-08-01T10:05:00Z", "agent_id": self.A_ID}]
        self.assertEqual(
            keel_dashboard._match_finish_events([start], [other_end], stops), {}
        )

    def test_each_start_is_finished_at_most_once_by_the_earliest_eligible_stop(self) -> None:
        """A backgrounded agent stops each time it has no live child."""
        start, end = self._launch("tu_1", "2026-08-01T10:00:00Z", self.A_ID)
        first_stop = {"ts": "2026-08-01T10:01:00Z", "agent_id": self.A_ID}
        second_stop = {"ts": "2026-08-01T10:02:00Z", "agent_id": self.A_ID}
        finished = keel_dashboard._match_finish_events(
            [start], [end], [second_stop, first_stop]
        )
        self.assertEqual(finished[id(start)], "2026-08-01T10:01:00Z")

    def test_never_mutates_any_input(self) -> None:
        start, end = self._launch("tu_1", "2026-08-01T10:00:00Z", self.A_ID)
        stop = {"ts": "2026-08-01T10:01:00Z", "agent_id": self.A_ID}
        before = (dict(start), dict(end), dict(stop))
        keel_dashboard._match_finish_events([start], [end], [stop])
        self.assertEqual((start, end, stop), before)


# ---------------------------------------------------------- honesty holds


class TestHonestyRulesStillHoldOnTheNewFields(unittest.TestCase):
    def test_no_state_carries_a_model_a_tier_or_a_stall_word(self) -> None:
        """Scoped to the CANVAS payload, not the whole state - ``arming``
        legitimately carries the word "tier" for the arming badge, a
        pre-existing feature this task does not touch."""
        lines = _handoff("s1", "A", "keel:executor", "a background launch",
                         "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z",
                         agent_id=STOP_AGENT_ID)
        lines.append(_stop("s1", "keel:executor", "2026-08-01T10:05:00Z"))
        graph = _state(lines)["graph"]
        import json
        text = json.dumps(graph).lower()
        for word in ("opus", "sonnet", "haiku", "model", "tier", "stalled", "hung", "stuck"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)

    def test_the_reference_fixture_still_reads_honestly_across_all_states(self) -> None:
        """``_graph_fixture`` (T4/T6's own shape: one closed pair, two open
        siblings of one type, one open of another) carries a two-minute
        closed gap - AWAITED under this task - and must not silently drift
        to BACKGROUND or FINISHED."""
        graph = _state(_graph_fixture())["graph"]
        by_task = {node["task_label"]: node for node in graph["nodes"]}
        closed = by_task["a closed hand-off"]
        self.assertEqual(closed["delegation_state"], "awaited")
        for task in ("first of two open executors", "second of two open executors",
                     "review the canvas"):
            self.assertEqual(by_task[task]["delegation_state"], "open")

    def test_the_card_renderer_escapes_the_two_new_text_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), _handoff(
                "s1", "A", "keel:executor", "x", "2026-08-01T10:00:00Z", "2026-08-01T10:00:03Z",
            )))
        card = _functions(_script(text))["nodeCard"]
        for field in ("n.state_note", "n.last_action"):
            with self.subTest(field=field):
                self.assertIn("esc(" + field + ")", card)


if __name__ == "__main__":
    unittest.main()
