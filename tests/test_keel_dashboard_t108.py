#!/usr/bin/env python3
"""T108 - stop a finished session from reading as a live one.

Contract
--------
Reads   : temporary directories this file creates, and its own module source
          through this file's own helpers - no fixture here touches this
          repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
The dashboard views one session at a time (``#plansel``), and until this task
a session that ended hours ago rendered with the same visual weight as one
running now. This is the sibling of the disconnect notice (T3): that notice
says the VIEWER lost its feed; this says the SESSION ITSELF is over.

``session_liveness`` decides three honest states from the raw audit log
(never from a figure a reader has to interpret), against the named freshness
window ``SESSION_LIVE_SECONDS``, plus a fourth for "no session to judge":

* ``live``  - the session's own newest line falls within the window.
* ``ended`` - a ``session_end`` line was actually recorded for the session,
  which wins outright however old or new that line is.
* ``quiet`` - the window has passed and no ``session_end`` was recorded (a
  killed session never writes one) - historical, but never claimed as
  "ended" on evidence that only says "quiet".
* ``none``  - no session is selected at all.

Covered here: the pure function's boundary and priority rules; the NAMED
constant actually gating the decision (a behavioural test, not an attribute
check); ``read_state`` wiring the field from the SAME session identity
``compute_graph`` already resolved (``graph["session"]``) rather than a
second resolution built from the selected ledger's own filename - a real
defect a live-page check caught: a plan's name carries only ``sess8`` (the
first 8 characters of the session id), but every audit line's own
``session`` field carries the FULL id, so comparing the two by equality
matched nothing and every session read a false "quiet" forever; and the
page's markup consuming that one server-decided field rather than deriving
its own opinion (pinned by source, since a value test cannot see what a
template escapes into).

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import datetime
import inspect
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
    _page,
    _project,
    _script,
    _sole_function_containing,
)

SESSION = "abcdef12"  # the identifier _project's own fixed ledger names.


def _ts(offset_seconds: float) -> str:
    """An ISO-8601 UTC timestamp ``offset_seconds`` from the real clock -
    negative for the past - in keel's own ``...Z`` shape."""
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------- the named constant


class TestTheNamedConstantGatesTheDecision(unittest.TestCase):
    """Not just an attribute that exists - a value that actually decides."""

    def test_the_constant_is_a_positive_number(self) -> None:
        self.assertGreater(keel_dashboard.SESSION_LIVE_SECONDS, 0)

    def test_moving_the_constant_moves_the_verdict(self) -> None:
        """A fixed synthetic timestamp, never the real clock: the same event
        and the same ``now`` read LIVE or QUIET purely on which window the
        constant names - proof the constant is what decides, not a fixed
        threshold baked into the function."""
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z") + 120
        with unittest.mock.patch.object(keel_dashboard, "SESSION_LIVE_SECONDS", 600):
            self.assertEqual(keel_dashboard.session_liveness(events, SESSION, now)["state"], "live")
        with unittest.mock.patch.object(keel_dashboard, "SESSION_LIVE_SECONDS", 60):
            self.assertEqual(keel_dashboard.session_liveness(events, SESSION, now)["state"], "quiet")


# ------------------------------------------------------- the pure function


class TestSessionLivenessPureFunction(unittest.TestCase):
    def test_a_recent_line_reads_live(self) -> None:
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z") + 5
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_LIVE)
        self.assertEqual(result["label"], "live")

    def test_the_window_boundary_is_inclusive(self) -> None:
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        base = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        at_boundary = base + keel_dashboard.SESSION_LIVE_SECONDS
        past_boundary = base + keel_dashboard.SESSION_LIVE_SECONDS + 1
        self.assertEqual(
            keel_dashboard.session_liveness(events, SESSION, at_boundary)["state"],
            keel_dashboard.SESSION_STATE_LIVE,
        )
        self.assertEqual(
            keel_dashboard.session_liveness(events, SESSION, past_boundary)["state"],
            keel_dashboard.SESSION_STATE_QUIET,
        )

    def test_only_old_lines_and_no_end_reads_quiet_not_ended(self) -> None:
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z") + 100000
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)
        self.assertNotEqual(result["label"], "live")
        self.assertIn("no session_end was recorded", result["note"])

    def test_no_line_at_all_for_the_session_also_reads_quiet(self) -> None:
        events: list[dict[str, Any]] = []
        result = keel_dashboard.session_liveness(events, SESSION, 1_000_000.0)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)

    def test_a_session_end_line_reads_ended_however_recent(self) -> None:
        events = [
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", "session": SESSION},
            {"v": 1, "ts": "2026-01-01T00:00:05Z", "event": "session_end", "session": SESSION},
        ]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:05Z") + 1
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_ENDED)
        self.assertEqual(result["label"], "ended")

    def test_a_session_end_line_reads_ended_even_when_the_last_line_is_old(self) -> None:
        """ENDED wins outright, however old the record now is - the whole
        point of distinguishing it from a merely QUIET, killed session."""
        events = [
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", "session": SESSION},
            {"v": 1, "ts": "2026-01-01T00:00:05Z", "event": "session_end", "session": SESSION},
        ]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:05Z") + 1_000_000
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_ENDED)

    def test_another_sessions_lines_never_decide_this_one(self) -> None:
        events = [
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": "someone-else"},
            {"v": 1, "ts": "2020-01-01T00:00:00Z", "event": "activity", "session": SESSION},
        ]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)

    def test_no_session_selected_is_its_own_state_not_a_fallthrough_to_quiet(self) -> None:
        result = keel_dashboard.session_liveness([], "", 1_000_000.0)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_NONE)
        self.assertEqual(result["label"], "no session")

    def test_every_state_carries_a_non_empty_positive_label(self) -> None:
        """Historical must never render as a missing badge: every state -
        including the two historical ones - has its own non-blank word."""
        for state in (
            keel_dashboard.SESSION_STATE_LIVE,
            keel_dashboard.SESSION_STATE_ENDED,
            keel_dashboard.SESSION_STATE_QUIET,
            keel_dashboard.SESSION_STATE_NONE,
        ):
            label = keel_dashboard.SESSION_STATE_LABELS[state]
            note = keel_dashboard.SESSION_STATE_NOTES[state]
            self.assertTrue(label.strip())
            self.assertTrue(note.strip())


# ------------------------------------------- review finding 1: future-dated ts


class TestAFutureDatedNewestLineIsSuspectNotFresh(unittest.TestCase):
    """``max(0.0, now - epoch)`` alone let ANY future timestamp clamp to age
    zero and read LIVE forever - clock skew or a corrupted line alike. A
    small named tolerance keeps ordinary jitter reading LIVE and everything
    beyond it reads QUIET with its own note."""

    def test_jitter_within_the_tolerance_still_reads_live(self) -> None:
        base = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        # `now` a couple of seconds BEHIND the line's own ts - ordinary
        # clock skew between two clocks, well inside the tolerance.
        now = base - (keel_dashboard.SESSION_CLOCK_SKEW_TOLERANCE_SECONDS - 2)
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_LIVE)

    def test_a_far_future_line_does_not_read_live(self) -> None:
        base = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = base - (keel_dashboard.SESSION_CLOCK_SKEW_TOLERANCE_SECONDS + 3600)
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)
        self.assertIn("future", result["note"])

    def test_exactly_at_the_tolerance_boundary_still_reads_live(self) -> None:
        base = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = base - keel_dashboard.SESSION_CLOCK_SKEW_TOLERANCE_SECONDS
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_LIVE)

    def test_the_session_can_still_age_into_quiet_normally(self) -> None:
        """The regression the review named: before this fix a future-dated
        line could never age out of LIVE at all."""
        base = keel_dashboard._epoch_seconds("2026-01-01T00:00:00Z")
        events = [{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "activity", "session": SESSION}]
        now = base + keel_dashboard.SESSION_LIVE_SECONDS + 1
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)


# ---------------------------------------- review finding 2: resumed sessions


class TestASessionEndOnlyWinsWhenItIsTheNewestEvidence(unittest.TestCase):
    """This project resumes a session under the SAME id
    (``hooks/keel_stop.py``'s own "a resumed agent"). An earlier
    ``session_end`` must not go on winning outright once something newer has
    been recorded for the same session - that would hide live work behind
    the calmest label this function has."""

    def _resumed_events(self) -> list[dict[str, Any]]:
        return [
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", "session": SESSION},
            {"v": 1, "ts": "2026-01-01T00:05:00Z", "event": "session_end", "session": SESSION},
            {"v": 1, "ts": "2026-01-01T01:00:00Z", "event": "activity", "session": SESSION},
        ]

    def test_fresh_activity_after_the_recorded_end_reads_live(self) -> None:
        events = self._resumed_events()
        now = keel_dashboard._epoch_seconds("2026-01-01T01:00:00Z") + 5
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_LIVE)

    def test_old_activity_after_the_recorded_end_reads_quiet_not_ended(self) -> None:
        events = self._resumed_events()
        now = (
            keel_dashboard._epoch_seconds("2026-01-01T01:00:00Z")
            + keel_dashboard.SESSION_LIVE_SECONDS
            + 3600
        )
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_QUIET)
        self.assertIn("resumed", result["note"])

    def test_a_session_whose_end_is_genuinely_the_newest_line_still_reads_ended(self) -> None:
        """The honest case (no later line at all) is unaffected."""
        events = [
            {"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", "session": SESSION},
            {"v": 1, "ts": "2026-01-01T00:05:00Z", "event": "session_end", "session": SESSION},
        ]
        now = keel_dashboard._epoch_seconds("2026-01-01T00:05:00Z") + 5
        result = keel_dashboard.session_liveness(events, SESSION, now)
        self.assertEqual(result["state"], keel_dashboard.SESSION_STATE_ENDED)


# ------------------------------------------------------- read_state wiring


class TestReadStateCarriesLivenessForTheSessionTheCanvasDraws(unittest.TestCase):
    """``read_state`` must feed ``session_liveness`` the SAME session
    identity ``compute_graph`` already resolved (``graph["session"]``), never
    a second one built from the selected ledger's own filename - see the
    fixture-gap class below for the real defect this replaces."""

    def test_a_freshly_active_session_reads_live(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = [
                {"v": 1, "ts": _ts(-5), "event": "session_start", "session": SESSION},
                {"v": 1, "ts": _ts(-2), "event": "activity", "session": SESSION, "tool": "Read"},
            ]
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "live")
        self.assertEqual(state["session_liveness"]["session"], SESSION)

    def test_a_session_quiet_past_the_window_reads_historical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = -(keel_dashboard.SESSION_LIVE_SECONDS + 3600)
            audit = [{"v": 1, "ts": _ts(old), "event": "session_start", "session": SESSION}]
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "quiet")

    def test_a_session_with_a_recorded_end_reads_ended(self) -> None:
        """A closed SESSION pair with no hand-off at all never reaches
        ``compute_graph`` (``compute_open_and_groups`` tracks only OPEN
        sessions and CLOSED hand-off pairs - see its own docstring), so this
        fixture carries one hand-off too, keeping the session visible on the
        canvas exactly as any real session with delegated work would be."""
        with tempfile.TemporaryDirectory() as tmp:
            audit = [
                {"v": 1, "ts": _ts(-30), "event": "session_start", "session": SESSION},
                {
                    "v": 1,
                    "ts": _ts(-25),
                    "event": "handoff_start",
                    "session": SESSION,
                    "tool_use_id": "t1",
                    "subagent_type": "executor",
                    "description": "do the work",
                },
                {
                    "v": 1,
                    "ts": _ts(-24),
                    "event": "handoff_end",
                    "session": SESSION,
                    "tool_use_id": "t1",
                },
                {"v": 1, "ts": _ts(-10), "event": "session_end", "session": SESSION},
            ]
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "ended")

    def test_the_liveness_field_participates_in_the_redraw_digest(self) -> None:
        """A session crossing live -> historical between two polls with no
        new event at all must still redraw - the digest must not exclude
        this field the way it excludes `now` itself."""
        with tempfile.TemporaryDirectory() as tmp:
            audit = [{"v": 1, "ts": _ts(-5), "event": "session_start", "session": SESSION}]
            project = _project(Path(tmp), audit)
            live_state = keel_dashboard.read_state(project)
            quiet_material = {
                key: value
                for key, value in live_state.items()
                if key not in ("now", "content_digest")
            }
            quiet_material["session_liveness"] = dict(live_state["session_liveness"], state="quiet")
        self.assertNotEqual(
            keel_dashboard.content_digest(live_state),
            keel_dashboard.content_digest(quiet_material),
        )


# --------------------------------- the real defect: sess8 vs. the full uuid


class TestTheLedgersShortIdNeverHasToMatchARawEvent(unittest.TestCase):
    """The real defect a live-page check caught, in the fixture shape that
    actually reproduces it: ``_project``'s ledger is always named
    ``keel-plan-abcdef12.md`` (``sess8`` - see ``KeelEvent.sess8`` in
    ``hooks/keel_events.py``), but a REAL audit line's own ``session`` field
    carries the FULL id. [[the-suite-is-green-only-under-one-runner]], in
    another costume: a fixture that spells the id the SAME short way on both
    sides never disagrees with itself the way the real log does, so 27 prior
    tests here passed while the live page read every session "quiet"."""

    FULL_UUID = "abcdef12-5d6c-4987-ac5c-71b8f2d4d33e"

    def test_fresh_activity_under_the_full_uuid_reads_live_despite_the_short_ledger_name(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = [
                {"v": 1, "ts": _ts(-5), "event": "session_start", "session": self.FULL_UUID},
                {
                    "v": 1,
                    "ts": _ts(-2),
                    "event": "activity",
                    "session": self.FULL_UUID,
                    "tool": "Read",
                },
            ]
            # `_project`'s own ledger is `keel-plan-abcdef12.md` - the SHORT
            # id - deliberately left disagreeing in length with `FULL_UUID`
            # above, exactly as the real ledger and the real audit log do.
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "live")
        self.assertEqual(state["session_liveness"]["session"], self.FULL_UUID)

    def test_old_activity_under_the_full_uuid_still_reads_historical(self) -> None:
        """The reverse direction of the same fix: an ended/quiet session
        under a full uuid must not accidentally start reading live either."""
        with tempfile.TemporaryDirectory() as tmp:
            old = -(keel_dashboard.SESSION_LIVE_SECONDS + 3600)
            audit = [
                {"v": 1, "ts": _ts(old), "event": "session_start", "session": self.FULL_UUID}
            ]
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "quiet")

    def test_short_ids_on_both_sides_still_work_the_reverse_regression(self) -> None:
        """Older fixtures (and a genuinely short session id, however
        unlikely) must keep working: this fix changes WHICH identity is fed
        to ``session_liveness``, never how the comparison itself is made."""
        with tempfile.TemporaryDirectory() as tmp:
            audit = [
                {"v": 1, "ts": _ts(-5), "event": "session_start", "session": SESSION},
                {"v": 1, "ts": _ts(-2), "event": "activity", "session": SESSION, "tool": "Read"},
            ]
            project = _project(Path(tmp), audit)
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["session_liveness"]["state"], "live")
        self.assertEqual(state["session_liveness"]["session"], SESSION)


class TestSessionLivenessIsFedTheCanvassOwnResolutionOnly(unittest.TestCase):
    """Structural, the same way T105's own single-reader test pins a field:
    ``read_state`` may resolve "which session" exactly ONCE - inside
    ``compute_graph`` - and hand that SAME value to ``session_liveness``,
    never build a second resolution from the selected ledger's own name."""

    def test_read_state_passes_graphs_own_session_key(self) -> None:
        source = inspect.getsource(keel_dashboard.read_state)
        self.assertIn('session_liveness(events, graph["session"], now)', source)

    def test_no_second_plan_derived_session_resolution_exists(self) -> None:
        source = inspect.getsource(keel_dashboard.read_state)
        for leftover in ("selected_plan", "session_for_liveness"):
            self.assertNotIn(leftover, source)


# --------------------------------------------------------- the page's markup


class TestThePageRendersTheServersFieldRatherThanItsOwnOpinion(unittest.TestCase):
    def test_the_header_carries_a_liveness_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            page = _page(_project(Path(tmp), []))
        self.assertIn('id="liveness"', page)

    def test_exactly_one_function_reads_the_liveness_field(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [])))
        functions = _functions(script)
        writer = _sole_function_containing(functions, "session_liveness")
        body = functions[writer]
        self.assertIn("s.session_liveness.label", body)
        self.assertIn("s.session_liveness.state", body)

    def test_the_client_computes_no_threshold_of_its_own(self) -> None:
        """The client renders the server's word; it must never re-derive
        live-vs-historical from a timestamp or the freshness window itself
        - that would be a second opinion, the exact drift this task's design
        forbids (matches the roster/last-seen precedent, T104)."""
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [])))
        functions = _functions(script)
        writer = _sole_function_containing(functions, "session_liveness")
        body = functions[writer]
        self.assertNotIn("SESSION_LIVE_SECONDS", body)
        self.assertNotIn("elapsedSince", body)

    def test_the_two_pill_shapes_exist_and_differ(self) -> None:
        """Live is the reference's green pill; historical is its OWN
        explicit rendering, never a bare absence of the live class."""
        with tempfile.TemporaryDirectory() as tmp:
            page = _page(_project(Path(tmp), []))
        self.assertIn(".tag.live", page)
        self.assertIn(".tag.historical", page)

    def test_the_className_assignment_never_leaves_the_tag_bare(self) -> None:
        """Whatever the server's state, the class expression always yields
        `tag live` or `tag historical` - never plain `tag` with no pill
        family at all, which would be exactly the "missing badge" this task
        forbids."""
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [])))
        functions = _functions(script)
        writer = _sole_function_containing(functions, "session_liveness")
        body = functions[writer]
        self.assertIn('" live" : " historical"', body)


if __name__ == "__main__":
    unittest.main()
