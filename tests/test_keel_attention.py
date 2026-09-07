#!/usr/bin/env python3
"""T27 - the attention pass on ``scripts/keel_dashboard.py``.

Contract
--------
Reads   : temporary directories this file creates, and - in exactly one test,
          ``TestExactlyOnce.test_...real_audit_log`` - this repository's own
          ``.keel/audit/keel-audit.jsonl``, read-only, asserted on only for
          an invariant that must hold for ANY log. Every other audit line
          exercised here is built in Python, so a test failure names the
          exact record that caused it.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
The four T27 clauses, each isolated from the others where that is possible:

(a) the routine ``activity`` kind starts hidden from a fresh page load, and
    the counts driving that toggle come from the state payload's own
    ``counts`` rather than being recomputed;
(b) a hand-off or a session with no matching end is OPEN, matched by its own
    identifier and never by counting kind against kind, sorted before
    everything else, with elapsed computed fresh each call rather than
    cached on the record;
(c) every response - ``/``, ``/api/state`` and a refused write alike -
    carries the four security headers, and the page still parses as HTML
    with them applied;
(d) the ``activity`` lines ATTRIBUTABLE to a matched hand-off collapse into
    one group keyed by that pair, while a ``gate_block`` in the same window
    stays in the flat feed.

Attribution and the exactly-once invariant (d)
-----------------------------------------------
``TestActivityAttribution`` pins what the record can and cannot say about
which delegation ran a tool - ``agent_type`` decides it, an empty one means
main-session work that belongs to no delegation, and two concurrent hand-offs
of the SAME type cannot be told apart at all, so that case is placed by
tie-break and MARKED as inferred rather than asserted.

``TestExactlyOnce`` pins the invariant that outranks all of it: every audit
line reaches the page exactly once - in one group, in the open list, or in
the flat feed - never twice and never nowhere. It is asserted against
overlapping same-session delegations, against an ``OPEN_TAIL`` overflow, and
against this repository's real audit log.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. The only socket opened is a loopback
listener bound to an ephemeral port (R19), driven only from 127.0.0.1.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_dashboard  # noqa: E402  (path must be set first)
from keel_published_cut import contradiction, is_published_cut  # noqa: E402

HTTP_TIMEOUT = 20


def _project(root: Path, audit_lines: list[dict[str, Any]]) -> Path:
    """A minimal adopted project carrying exactly the given audit lines."""
    project = root / "project"
    (project / ".keel" / "plans").mkdir(parents=True)
    (project / ".keel" / "audit").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    (project / ".keel" / "plans" / "keel-plan-abcdef12.md").write_text(
        "# ledger\n\n- [ ] T1: a task | route: executor\n", encoding="utf-8"
    )
    with open(
        project / ".keel" / "audit" / "keel-audit.jsonl", "w", encoding="utf-8", newline="\n"
    ) as handle:
        for line in audit_lines:
            handle.write(json.dumps(line) + "\n")
    return project


class DashboardServer:
    """A running viewer on an ephemeral loopback port, for one test's life."""

    def __init__(self, project: Path) -> None:
        self.server = keel_dashboard.build_server(project)
        self.url = keel_dashboard.server_url(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method: str, route: str) -> tuple[int, bytes, Any]:
        req = urllib.request.Request(self.url.rstrip("/") + route, method=method)
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            req.data = b"{}"
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def state(self) -> dict[str, Any]:
        status, body, _ = self.request("GET", "/api/state")
        assert status == 200, body
        return json.loads(body.decode("utf-8"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=HTTP_TIMEOUT)


# --------------------------------------------------------------- (a) landing


class TestExceptionDefaultLanding(unittest.TestCase):
    def test_activity_is_the_overwhelming_majority_but_not_the_only_kind(self) -> None:
        """Sanity check on the fixture shape this whole file relies on."""
        lines = (
            [{"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "activity", "session": "s1"}] * 20
            + [{"v": 1, "ts": "2026-08-01T10:00:01Z", "event": "gate_block", "session": "s1"}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(state["counts"]["activity"], 20)
            self.assertEqual(state["counts"]["gate_block"], 1)

    def test_counts_in_state_are_what_a_filter_control_would_use(self) -> None:
        """The per-kind counts (a)'s filter chips read - present, per-kind,
        and equal to a plain count of that kind across the whole log."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "activity", "session": "s1"},
            {"v": 1, "ts": "2026-08-01T10:00:01Z", "event": "activity", "session": "s1"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "gate_bypass", "session": "s1"},
            {"v": 1, "ts": "2026-08-01T10:00:03Z", "event": "stop_block", "session": "s1"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            for kind in keel_dashboard.COUNTED_EVENTS:
                self.assertIn(kind, state["counts"])
            self.assertEqual(state["counts"]["activity"], 2)
            self.assertEqual(state["counts"]["gate_bypass"], 1)
            self.assertEqual(state["counts"]["stop_block"], 1)

    def test_page_ships_the_toggle_hidden_by_default_never_the_landing_view(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "activity", "session": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), lines))
            try:
                status, body, _ = server.request("GET", "/")
                text = body.decode("utf-8")
                self.assertEqual(status, 200)
                self.assertIn('hiddenKinds = new Set(["activity"])', text)
                self.assertIn('id="filters"', text)
            finally:
                server.close()

    def test_non_activity_kinds_are_not_folded_into_a_group_even_inside_a_handoff(self) -> None:
        """(a) and (d) meeting point: a gate_block during a hand-off's window
        is "not a plain allow" and must stay in the flat, visible feed."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d"},
            {"v": 1, "ts": "2026-08-01T10:00:05Z", "event": "gate_block", "session": "s1",
             "gate": "plan"},
            {"v": 1, "ts": "2026-08-01T10:00:10Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            flat_kinds = [row["event"] for row in state["feed"] if row["row_kind"] == "event"]
            self.assertIn("gate_block", flat_kinds)
            groups = [row for row in state["feed"] if row["row_kind"] == "group"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["count"], 0, "a gate_block must not count as a member")


# ----------------------------------------------------------------- (b) open


class TestOpenState(unittest.TestCase):
    def test_a_handoff_with_no_matching_end_is_open(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(len(state["open"]), 1)
            item = state["open"][0]
            self.assertEqual(item["row_kind"], "open_handoff")
            self.assertEqual(item["description"], "unfinished")
            self.assertNotIn("stalled", json.dumps(state).lower())
            self.assertNotIn("hung", json.dumps(state).lower())
            self.assertNotIn("stuck", json.dumps(state).lower())

    def test_a_session_with_no_matching_end_is_open(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(len(state["open"]), 1)
            self.assertEqual(state["open"][0]["row_kind"], "open_session")
            self.assertEqual(state["open"][0]["session"], "s1")

    def test_matching_is_by_identifier_not_by_counting_kind_against_kind(self) -> None:
        """Two starts, two ends, all in one session, but the FIRST start's own
        id matches the SECOND end and vice versa is irrelevant - the point is
        a start whose own id has no counterpart is open even when totals are
        equal, and a start whose own id DOES have a counterpart is not."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T10:00:05Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t2", "subagent_type": "executor", "description": "two"},
            {"v": 1, "ts": "2026-08-01T10:00:10Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "one"},
            # t2 never gets a handoff_end: counts are 2 starts / 1 end, but
            # the OPEN one must be identified as "two", by id - not as
            # "whichever start is left over after subtracting counts".
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(len(state["open"]), 1)
            self.assertEqual(state["open"][0]["description"], "two")

    def test_matching_is_scoped_to_the_owning_session(self) -> None:
        """A hand-off's own session pairs against its own halves only - a
        start in one session must never be closed by an end recorded under
        a different one, and vice versa."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "shared", "subagent_type": "executor", "description": "s1 half"},
            {"v": 1, "ts": "2026-08-01T10:00:05Z", "event": "handoff_end", "session": "s2",
             "tool_use_id": "shared", "subagent_type": "executor", "description": "s1 half"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            # s1's start never sees an end recorded under s2, so it is open.
            self.assertEqual(len(state["open"]), 1)
            self.assertEqual(state["open"][0]["session"], "s1")

    def test_open_items_are_sorted_before_everything_else_oldest_first(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "session_start", "session": "s1"},
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual([o["session"] for o in state["open"]], ["s2", "s1"])

    def test_elapsed_is_not_a_field_the_record_carries(self) -> None:
        """(b): "not from any timestamp the record makes about itself" - the
        wire payload for an open item carries the raw start ``ts`` and
        nothing that already looks like a precomputed duration."""
        lines = [{"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "session_start", "session": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            item = state["open"][0]
            self.assertIn("ts", item)
            for stale_field in ("elapsed", "elapsed_seconds", "duration", "age"):
                self.assertNotIn(stale_field, item)


# --------------------------------------------------------------- (c) headers


class TestSecurityHeaders(unittest.TestCase):
    def _assert_security_headers(self, headers: Any) -> None:
        self.assertIn("'unsafe-inline'", headers.get("Content-Security-Policy", ""))
        self.assertNotIn("unsafe-eval", headers.get("Content-Security-Policy", ""))
        self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")

    def test_every_read_route_carries_all_four_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                for route in ("/", "/api/state", "/api/plan?name=keel-plan-abcdef12.md"):
                    with self.subTest(route=route):
                        status, _, headers = server.request("GET", route)
                        self.assertEqual(status, 200)
                        self._assert_security_headers(headers)
            finally:
                server.close()

    def test_a_refused_write_also_carries_all_four_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                for method in ("POST", "PUT", "PATCH", "DELETE"):
                    with self.subTest(method=method):
                        status, body, headers = server.request(method, "/api/state")
                        self.assertEqual(status, 405)
                        self.assertIn(b"read-only", body)
                        self._assert_security_headers(headers)
            finally:
                server.close()

    def test_the_page_still_renders_with_the_policy_applied(self) -> None:
        """A CSP that breaks the page silently is worse than none: the page
        must still be well-formed HTML carrying its one inline style block
        and one inline script block, with no external script/style/font/
        image reference the policy would have to block."""
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                status, body, _ = server.request("GET", "/")
                text = body.decode("utf-8")
                self.assertEqual(status, 200)
                self.assertIn("<style>", text)
                self.assertIn("<script>", text)
                self.assertIn("</html>", text)
                self.assertNotRegex(text, r'<script[^>]+src=')
                self.assertNotRegex(text, r'<link[^>]+rel="stylesheet"')
                self.assertNotIn("<iframe", text)
            finally:
                server.close()


# --------------------------------------------------------------- (d) groups


class TestHandoffGrouping(unittest.TestCase):
    def test_activity_between_a_matched_pair_collapses_into_one_group(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "did work"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
            {"v": 1, "ts": "2026-08-01T10:00:04Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Bash"},
            {"v": 1, "ts": "2026-08-01T10:00:06Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "did work"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            groups = [row for row in state["feed"] if row["row_kind"] == "group"]
            events = [row for row in state["feed"] if row["row_kind"] == "event"]
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["count"], 2)
            self.assertEqual(groups[0]["agent_type"], "executor")
            self.assertEqual(
                {e["tool"] for e in groups[0]["events"]}, {"Edit", "Bash"}
            )
            # Only one hand-off was ever open, so nothing here is a guess.
            self.assertEqual(groups[0]["inferred"], 0)
            self.assertEqual([e["inferred"] for e in groups[0]["events"]], [False, False])
            # The two boundary lines and both activity lines are all inside
            # the group; nothing about this hand-off remains in the flat feed.
            self.assertEqual(events, [])

    def test_activity_outside_any_handoff_window_stays_ungrouped(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Read"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "x"},
            {"v": 1, "ts": "2026-08-01T10:00:06Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "x"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            events = [row for row in state["feed"] if row["row_kind"] == "event"]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["tool"], "Read")

    def test_an_open_handoff_never_forms_a_group(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            groups = [row for row in state["feed"] if row["row_kind"] == "group"]
            self.assertEqual(groups, [])
            self.assertEqual(len(state["open"]), 1)
            # the activity after an open start is not swallowed by anything
            events = [row for row in state["feed"] if row["row_kind"] == "event"]
            self.assertEqual(len(events), 1)

    def test_the_page_renders_a_group_as_a_details_block(self) -> None:
        """The page is a static template driven by client-side JS against
        ``/api/state`` - so what a fetch can prove is that the rendering
        code the browser will run builds a ``<details>``/``<summary>`` pair
        for a group row, not a tree widget."""
        status, body, _ = None, b"", None
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                status, body, _ = server.request("GET", "/")
            finally:
                server.close()
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn('row_kind === "group"', text)
        self.assertIn("<details", text)
        self.assertIn("<summary>", text)
        self.assertNotIn("span-id", text.lower())


# ------------------------------------------------- (d) who ran an activity line


def _overlapping(agent_a: str, agent_b: str) -> list[dict[str, Any]]:
    """The reviewer's exact scenario: two hand-offs open at once in ONE
    session, with a single ``activity`` line inside BOTH of their windows.

    start A 10:00:00 · start B 10:00:01 · activity 10:00:02 ·
    end A 10:00:03 · end B 10:00:04 - so containment alone puts the activity
    line in two groups at once. The activity's ``agent_type`` is ``agent_a``;
    whether that settles the question depends on whether B is the same type.
    """
    return [
        {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
         "tool_use_id": "A", "subagent_type": agent_a, "description": "first"},
        {"v": 1, "ts": "2026-08-01T10:00:01Z", "event": "handoff_start", "session": "s1",
         "tool_use_id": "B", "subagent_type": agent_b, "description": "second"},
        {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
         "agent_type": agent_a, "tool": "Edit", "detail": "shared.py"},
        {"v": 1, "ts": "2026-08-01T10:00:03Z", "event": "handoff_end", "session": "s1",
         "tool_use_id": "A", "subagent_type": agent_a, "description": "first"},
        {"v": 1, "ts": "2026-08-01T10:00:04Z", "event": "handoff_end", "session": "s1",
         "tool_use_id": "B", "subagent_type": agent_b, "description": "second"},
    ]


class TestActivityAttribution(unittest.TestCase):
    """What the record can say about WHICH delegation ran a tool - and, where
    it cannot say, that the page does not pretend otherwise."""

    def test_agent_type_decides_it_when_the_overlapping_handoffs_differ(self) -> None:
        """Two hand-offs open at once, of DIFFERENT types: the activity line
        falls inside both time windows, but ``agent_type`` names one of them.
        It goes to that one, exactly once, and is NOT marked inferred -
        because nothing was inferred."""
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(
                _project(Path(tmp), _overlapping("keel:researcher", "keel:executor"))
            )
            groups = [row for row in state["feed"] if row["row_kind"] == "group"]
            self.assertEqual(len(groups), 2)
            by_agent = {g["agent_type"]: g for g in groups}
            self.assertEqual(by_agent["keel:researcher"]["count"], 1)
            self.assertEqual(by_agent["keel:executor"]["count"], 0)
            self.assertEqual(by_agent["keel:researcher"]["inferred"], 0)
            self.assertIs(by_agent["keel:researcher"]["events"][0]["inferred"], False)

    def test_the_same_type_overlap_is_placed_once_and_declared_inferred(self) -> None:
        """The case the record genuinely cannot answer: two ``keel:executor``
        hand-offs open at once. The line must still render exactly once, but
        the group holding it must SAY the placement is a guess - on the group
        and on the line - so the page is not asserting a fact it lacks."""
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(
                _project(Path(tmp), _overlapping("keel:executor", "keel:executor"))
            )
            groups = [row for row in state["feed"] if row["row_kind"] == "group"]
            self.assertEqual(len(groups), 2)
            holders = [g for g in groups if g["count"]]
            self.assertEqual(len(holders), 1, "the line landed in more than one group")
            self.assertEqual(holders[0]["count"], 1)
            self.assertEqual(holders[0]["inferred"], 1)
            self.assertIs(holders[0]["events"][0]["inferred"], True)
            # And it is not ALSO sitting in the flat feed.
            flat = [row for row in state["feed"] if row["row_kind"] == "event"]
            self.assertEqual(flat, [])

    def test_the_tie_break_is_deterministic_and_picks_the_latest_start(self) -> None:
        """Same input twice must give the same answer, and the answer is the
        most recently started enclosing hand-off (B, started at 10:00:01)."""
        lines = _overlapping("keel:executor", "keel:executor")
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), lines)
            first = keel_dashboard.read_state(project)
            second = keel_dashboard.read_state(project)
        picks = []
        for state in (first, second):
            holders = [
                g for g in state["feed"] if g["row_kind"] == "group" and g["count"]
            ]
            picks.append(holders[0]["description"])
        self.assertEqual(picks, ["second", "second"])

    def test_main_session_activity_is_never_folded_into_a_delegation(self) -> None:
        """An empty ``agent_type`` is main-session work - a fact the capture
        hook records deliberately (``hooks/keel_capture.py``). The
        orchestrator's own edit must not be shown as something the subagent
        did, however neatly it lands inside the hand-off's window."""
        for absent in ({}, {"agent_type": ""}, {"agent_type": "   "}):
            with self.subTest(shape=absent):
                lines = [
                    {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start",
                     "session": "s1", "tool_use_id": "t1",
                     "subagent_type": "keel:executor", "description": "d"},
                    {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity",
                     "session": "s1", "tool": "Edit", **absent},
                    {"v": 1, "ts": "2026-08-01T10:00:06Z", "event": "handoff_end",
                     "session": "s1", "tool_use_id": "t1",
                     "subagent_type": "keel:executor", "description": "d"},
                ]
                with tempfile.TemporaryDirectory() as tmp:
                    state = keel_dashboard.read_state(_project(Path(tmp), lines))
                groups = [r for r in state["feed"] if r["row_kind"] == "group"]
                flat = [r for r in state["feed"] if r["row_kind"] == "event"]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["count"], 0)
                self.assertEqual([r["event"] for r in flat], ["activity"])

    def test_an_activity_of_a_type_no_open_handoff_matches_stays_flat(self) -> None:
        """A ``keel:researcher`` line inside a ``keel:executor``'s window did
        not come from that executor, so it is not put inside it."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "keel:executor", "description": "d"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
             "agent_type": "keel:researcher", "tool": "Read"},
            {"v": 1, "ts": "2026-08-01T10:00:06Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "keel:executor", "description": "d"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        groups = [r for r in state["feed"] if r["row_kind"] == "group"]
        flat = [r for r in state["feed"] if r["row_kind"] == "event"]
        self.assertEqual(groups[0]["count"], 0)
        self.assertEqual([r["event"] for r in flat], ["activity"])

    def test_the_page_shows_an_inferred_group_as_an_inference(self) -> None:
        """A group whose membership was guessed must not look identical to
        one that is known: the page carries a distinct class, a per-line
        marker, and - the part that actually matters - the reason in words."""
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                status, body, _ = server.request("GET", "/")
            finally:
                server.close()
        text = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("g.inferred", text)
        self.assertIn('e.inferred ? " inf" : ""', text)
        self.assertIn("not something the record says", text)
        self.assertIn(".grp.inf", text)
        # The wording must not upgrade the guess into a claim.
        self.assertNotIn("certainly", text.lower())

    def test_every_rendered_value_in_a_group_is_escaped_before_innerhtml(self) -> None:
        """The inference marker added no unescaped interpolation: an audit
        line carrying markup is still inert on the page."""
        lines = _overlapping("keel:executor", "keel:executor")
        lines[2]["detail"] = '<img src=x onerror="alert(1)">'
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            server = DashboardServer(_project(Path(tmp) / "b", lines))
            try:
                _, page, _ = server.request("GET", "/")
            finally:
                server.close()
        # The server does not sanitise - it redacts; the page escapes. So the
        # payload survives into the payload, and the page must route every
        # group/event interpolation through `esc`.
        text = page.decode("utf-8")
        self.assertIn("const esc =", text)
        # ``detail_text`` is the server's own summary line since T31 moved it
        # off the page (it is built from the ALREADY-REDACTED row) - it is
        # still a value the page interpolates, so it still passes through
        # ``esc`` before it reaches innerHTML, which is what this pins.
        for interpolation in ("${esc(e.detail_text)}", "${esc(g.count)}", "${esc(n)}"):
            self.assertIn(interpolation, text)
        self.assertNotIn("${e.detail_text}", text)
        self.assertNotIn("${g.description}", text)
        self.assertIsInstance(json.dumps(state), str)
        # And the server's summary really does carry the hostile field, so
        # the escaping above is protecting something that is actually there.
        grouped = [
            member
            for row in state["feed"]
            if row["row_kind"] == "group"
            for member in row["events"]
        ]
        self.assertTrue(
            any('<img src=x onerror="alert(1)">' in m["detail_text"] for m in grouped),
            "the payload no longer carries the markup this test escapes",
        )


# ------------------------------------------------------- the exactly-once law


def _render_census(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Where each raw audit line ends up, counted per line.

    Re-derives the pairing the same way ``compute_open_and_groups`` does so
    the boundary lines can be named, then attributes every remaining line to
    the flat feed or to the open list. Returns per-line placement counts, so
    a line rendered twice and a line rendered nowhere are both visible.
    """
    # The fourth value (T105) is the main session's own lines, which this
    # census does not need: they are NEVER consumed, so they reach the flat
    # feed below exactly as they always did, and the drawer that shows them
    # takes no line away from any row counted here.
    open_items, groups, consumed, _own = keel_dashboard.compute_open_and_groups(events)
    places: dict[int, list[str]] = {id(entry): [] for entry in events}

    for group in groups:
        for member in group["events"]:
            places[id(member)].append("group-member")

    by_session: dict[Any, list[dict[str, Any]]] = {}
    for entry in events:
        by_session.setdefault(keel_dashboard._session_of(entry), []).append(entry)
    for session_events in by_session.values():
        starts = [e for e in session_events if e.get("event") == "handoff_start"]
        ends = [e for e in session_events if e.get("event") == "handoff_end"]
        pairs, _ = keel_dashboard._pair_starts_ends(
            starts,
            ends,
            keel_dashboard._HANDOFF_ID_FIELD,
            keel_dashboard._HANDOFF_FALLBACK_FIELDS,
        )
        for start, end in pairs:
            places[id(start)].append("group-boundary")
            places[id(end)].append("group-boundary")

    for entry in events:
        if id(entry) not in consumed:
            places[id(entry)].append("flat-feed")
    # Whatever is consumed with no place yet is an open item's start line.
    for entry in events:
        if id(entry) in consumed and not places[id(entry)]:
            places[id(entry)].append("open-list")

    return {
        "places": places,
        "open": open_items,
        "groups": groups,
        "twice": [p for p in places.values() if len(p) > 1],
        "nowhere": [key for key, p in places.items() if not p],
        "total": sum(len(p) for p in places.values()),
    }


class TestExactlyOnce(unittest.TestCase):
    """EVERY audit line renders exactly once: in one group, in the open list,
    or in the flat feed. Never both. Never neither."""

    def _assert_exactly_once(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        census = _render_census(events)
        self.assertEqual(census["twice"], [], "an audit line was rendered more than once")
        self.assertEqual(census["nowhere"], [], "an audit line was rendered nowhere")
        self.assertEqual(
            census["total"],
            len(events),
            "total rendered lines must equal total input lines",
        )
        return census

    def test_overlapping_same_session_delegations_render_every_line_once(self) -> None:
        """The fixture from the review finding, widened: three hand-offs of
        the SAME type open at once, with activity throughout - the shape that
        made time containment duplicate lines into every enclosing group."""
        events: list[dict[str, Any]] = [
            {"v": 1, "ts": "2026-08-01T09:59:00Z", "event": "session_start", "session": "s1"},
        ]
        for index, tid in enumerate(("A", "B", "C")):
            events.append(
                {"v": 1, "ts": f"2026-08-01T10:00:0{index}Z", "event": "handoff_start",
                 "session": "s1", "tool_use_id": tid, "subagent_type": "keel:executor",
                 "description": f"branch {tid}"}
            )
        for index in range(6):
            events.append(
                {"v": 1, "ts": f"2026-08-01T10:00:1{index}Z", "event": "activity",
                 "session": "s1", "agent_type": "keel:executor", "tool": "Edit"}
            )
        # Main-session work in the same window, and a block that must stay flat.
        events.append(
            {"v": 1, "ts": "2026-08-01T10:00:16Z", "event": "activity", "session": "s1",
             "agent_type": "", "tool": "Write"}
        )
        events.append(
            {"v": 1, "ts": "2026-08-01T10:00:17Z", "event": "gate_block", "session": "s1",
             "gate": "plan"}
        )
        for index, tid in enumerate(("A", "B", "C")):
            events.append(
                {"v": 1, "ts": f"2026-08-01T10:00:2{index}Z", "event": "handoff_end",
                 "session": "s1", "tool_use_id": tid, "subagent_type": "keel:executor",
                 "description": f"branch {tid}"}
            )
        events.append(
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "session_end", "session": "s1"}
        )

        census = self._assert_exactly_once(events)
        # Every one of the six subagent lines was placed, all under inference
        # (three same-type hand-offs were open for each of them).
        self.assertEqual(sum(g["count"] for g in census["groups"]), 6)
        self.assertEqual(sum(g["inferred"] for g in census["groups"]), 6)
        # ...and the shape really was ambiguous, i.e. the fixture is honest.
        self.assertEqual(len(census["groups"]), 3)

        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), events))
        rendered = sum(
            2 + row["count"] if row["row_kind"] == "group" else 1 for row in state["feed"]
        ) + len(state["open"])
        self.assertEqual(rendered, len(events))
        flat_kinds = [r["event"] for r in state["feed"] if r["row_kind"] == "event"]
        self.assertIn("gate_block", flat_kinds)
        self.assertEqual(flat_kinds.count("activity"), 1, "main-session line stays flat")

    def test_a_start_dropped_by_the_open_bound_falls_back_to_the_flat_feed(self) -> None:
        """``OPEN_TAIL`` bounds the open LIST, not the record: a start beyond
        the bound must still reach the page as an ordinary feed row rather
        than disappearing from both places."""
        events = [
            {"v": 1, "ts": f"2026-08-01T10:{index // 60:02d}:{index % 60:02d}Z",
             "event": "session_start", "session": f"s{index}"}
            for index in range(keel_dashboard.OPEN_TAIL + 5)
        ]
        census = self._assert_exactly_once(events)
        self.assertEqual(len(census["open"]), keel_dashboard.OPEN_TAIL)
        flat = [p for p in census["places"].values() if p == ["flat-feed"]]
        self.assertEqual(len(flat), 5)

    def test_the_invariant_holds_over_this_repositorys_real_audit_log(self) -> None:
        """Fixtures prove the rule; the real log proves the rule met reality.
        This repository's own audit log carries genuine parallel delegations
        - which is why the defect this test guards was reachable at all."""
        events, unreadable = keel_dashboard.read_events(REPO_ROOT)
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            self.assertEqual(unreadable, 0, "a published cut ships no corrupt line")
            self.assertEqual(
                events, [], "a published cut declares an empty audit log, not this many events"
            )
            return
        if not events:
            self.fail(f"no audit log to check under {REPO_ROOT} - fail closed, never skip")
        census = self._assert_exactly_once(events)
        self.assertEqual(unreadable, 0, "the repository's own audit log has a corrupt line")
        # Every group's declared count matches what it actually holds, and no
        # group claims more inferences than it has members.
        for group in census["groups"]:
            self.assertEqual(group["count"], len(group["events"]))
            self.assertLessEqual(group["inferred"], group["count"])


if __name__ == "__main__":
    unittest.main()
