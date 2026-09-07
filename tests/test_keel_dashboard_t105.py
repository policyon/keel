#!/usr/bin/env python3
"""T105 - the centre node opens a panel on what the session did itself.

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
Clicking the session at the centre of the delegation canvas opens a drawer
beside it - the reference's frame 2 - listing what that session did outside
any delegation, newest first.

THE load-bearing claim is where those lines come from. A panel showing one
actor's lines is a claim about which lines were its, and this project has
twice paid for getting that claim wrong, so the drawer does not look for
them: they are the lines rule (1) of ``_attribute_activity`` DECLINES to
fold into a group, handed back by that same single pass as
``compute_open_and_groups``'s fourth value. Three tests below would fail if
a second computation of that appeared anywhere -

* the drawer's rows are exactly the lines no group claimed, and never a
  delegation's own lines (a value test, both directions);
* the drawer's rows follow the attribution pass's output when that output is
  changed underneath it - so a caller re-deriving the set would be caught;
* the ONE field on an activity line that says who ran it is read in exactly
  two functions of this module, and neither of them is the drawer's.

Also covered: the reference's row shape (a wall-clock time, a glyph naming
the KIND, content clamped to two lines), the summary and state lines, the
tail bound stating what it left out, and the structural half of "opening it
disturbs nothing" - the drawer's one writer reaches no pane's markup, no
freshness node and no card, so an expanded delegation, a scroll position,
the disconnect notice and every ticking elapsed figure survive it.

Values, not substrings
-----------------------
Everything the drawer SAYS is asserted as a value read off ``read_state``,
the discipline ``test_keel_dashboard_t28_31.py`` documents. The page-source
checks below are for structural claims a value cannot express - which
function may reach which, what the row's markup escapes - and say so in
their own docstrings.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import inspect
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_adapter_claude  # noqa: E402
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    FRESHNESS_NODE,
    PANE_MARKUP,
    _block_after,
    _calls,
    _decl,
    _functions,
    _graph_fixture,
    _handoff,
    _page,
    _project,
    _reachable,
    _script,
    _sole_function_containing,
    _style,
)

SESSION = "s1"


def _state(lines: list[dict[str, Any]]) -> dict[str, Any]:
    # T109: this module's fixtures predate the finish-linger window and use
    # fixed historical timestamps nowhere near the real wall clock
    # ``compute_graph`` now checks a FINISHED/AWAITED row's own finish
    # against. Patched here, at the one place every test in this file (and
    # every test in ``test_keel_dashboard_t106.py`` that imports this same
    # function) reads state through, so a closed pair built to test the
    # drawer or the panel keeps being drawn rather than aging out of all of
    # them at once.
    with mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 10**9):
        with tempfile.TemporaryDirectory() as tmp:
            return keel_dashboard.read_state(_project(Path(tmp), lines))


def _root(lines: list[dict[str, Any]]) -> dict[str, Any]:
    return _state(lines)["graph"]["root"]


def _own(session: str, ts: str, tool: str, detail: str) -> dict[str, Any]:
    """One line of the MAIN SESSION's own work: an ``activity`` line with no
    ``agent_type``, which is how ``hooks/keel_capture.py`` records work no
    subagent ran (see ``action_record``'s own comment)."""
    return {
        "v": 1, "ts": ts, "event": "activity", "session": session,
        "agent_type": None, "tool": tool, "detail": detail,
    }


def _delegated(session: str, agent: str, ts: str, detail: str) -> dict[str, Any]:
    """One line a DELEGATION produced - the same shape, carrying a type."""
    return {
        "v": 1, "ts": ts, "event": "activity", "session": session,
        "agent_type": agent, "tool": "Edit", "detail": detail,
    }


def _mixed_fixture() -> list[dict[str, Any]]:
    """One session that delegated once and also worked itself: a closed
    hand-off with two lines of its own inside its window, and three
    main-session lines around it."""
    lines: list[dict[str, Any]] = [
        {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": SESSION},
        _own(SESSION, "2026-08-01T09:05:00Z", "Write", "docs/first.md"),
    ]
    lines += _handoff(SESSION, "t1", "keel:executor", "a closed hand-off",
                      "2026-08-01T09:10:00Z", "2026-08-01T09:20:00Z")
    lines += [
        _delegated(SESSION, "keel:executor", "2026-08-01T09:11:00Z", "src/worker-one.py"),
        _own(SESSION, "2026-08-01T09:12:00Z", "Bash", "git status --short"),
        _delegated(SESSION, "keel:executor", "2026-08-01T09:13:00Z", "src/worker-two.py"),
        _own(SESSION, "2026-08-01T09:30:00Z", "Edit", "docs/last.md"),
    ]
    return lines


#: The three main-session lines of ``_mixed_fixture``, newest first.
MIXED_OWN_NEWEST_FIRST = ["docs/last.md", "git status --short", "docs/first.md"]


# ------------------------------------------- where the drawer's lines come from


class TestTheDrawerReadsTheAttributionItselfAndNothingElse(unittest.TestCase):
    """THE claim of this task. The drawer's lines are the attribution pass's
    own declined half - not a second search, not "whatever the feed still
    holds", and not a rule restated beside the first one."""

    def test_the_drawer_holds_exactly_the_lines_no_delegation_claimed(self) -> None:
        """Both directions at once: every main-session line is in the drawer,
        every delegated line is in its group, and neither set has a member of
        the other. A drawer that over-claimed or under-claimed by one line
        fails here."""
        state = _state(_mixed_fixture())
        root = state["graph"]["root"]
        self.assertEqual([row["text"] for row in root["own_activity"]],
                         MIXED_OWN_NEWEST_FIRST)
        groups = [row for row in state["feed"] if row["row_kind"] == "group"]
        self.assertEqual(len(groups), 1)
        grouped = {member["detail"] for member in groups[0]["events"]}
        self.assertEqual(grouped, {"src/worker-one.py", "src/worker-two.py"})
        self.assertFalse(grouped & set(MIXED_OWN_NEWEST_FIRST),
                         "no line may be in both a group and the drawer")

    def test_the_drawer_follows_the_attribution_pass_rather_than_re_deriving_it(
        self,
    ) -> None:
        """The test that would fail if a SECOND computation appeared. The one
        pass is replaced with a wrapper that drops a line from the half it
        declined; the drawer must lose exactly that line. Anything that
        re-derived "the main session's own lines" from the events, the feed
        or the consumed set would still show it - and would fail here - which
        is the whole point of returning it from that pass instead."""
        real = keel_dashboard._attribute_activity

        def dropping(session_events: list[dict[str, Any]], windows: list[Any]) -> Any:
            attributed = real(session_events, windows)
            return keel_dashboard._Attribution(attributed.consumed, attributed.own[1:])

        with mock.patch.object(keel_dashboard, "_attribute_activity", dropping):
            root = _root(_mixed_fixture())
        self.assertEqual([row["text"] for row in root["own_activity"]],
                         MIXED_OWN_NEWEST_FIRST[:-1])
        self.assertEqual(root["own_total"], 2)

    def test_the_field_that_says_who_ran_a_line_has_no_new_reader(self) -> None:
        """Structural, and the reason a third computation cannot be added
        quietly: the ONE field an activity line carries about who ran it is
        read in exactly two functions of this module - the attribution pass
        and quiet-time's own unclaimed filter, both of which predate this
        task. The drawer's builders are not among them, because they never
        decide the question; they are handed the answer."""
        readers = {
            name
            for name, obj in vars(keel_dashboard).items()
            if inspect.isfunction(obj)
            and obj.__module__ == "keel_dashboard"
            and "_ACTIVITY_AGENT_FIELD" in inspect.getsource(obj)
        }
        self.assertEqual(readers, {"_attribute_activity", "_unclaimed_activity"})
        for builder in ("root_panel", "own_activity_row", "read_state"):
            with self.subTest(builder=builder):
                self.assertNotIn(builder, readers)

    def test_an_open_delegations_lines_are_not_the_sessions_own(self) -> None:
        """"Unconsumed" is NOT the rule, and this is the fixture that tells
        the two apart: a still-open hand-off's activity is claimed by no
        group either, yet it carries an agent type and so was not the
        session's own work. A drawer built from the leftovers of the feed
        would show it."""
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "t1", "keel:executor", "still open",
                          "2026-08-01T10:00:00Z")
        lines.append(_delegated(SESSION, "keel:executor", "2026-08-01T10:01:00Z",
                                "src/still-running.py"))
        lines.append(_own(SESSION, "2026-08-01T10:02:00Z", "Edit", "docs/mine.md"))
        root = _root(lines)
        self.assertEqual([row["text"] for row in root["own_activity"]], ["docs/mine.md"])

    def test_the_drawer_takes_no_line_away_from_the_flat_feed(self) -> None:
        """Reading is not owning: the exactly-once law is about which row
        OWNS a line, and a main-session line is still owned by the flat feed
        exactly as it was before this task. A drawer that consumed what it
        showed would delete those rows from the feed."""
        state = _state(_mixed_fixture())
        flat = {row.get("detail") for row in state["feed"] if row["row_kind"] == "event"}
        for text in MIXED_OWN_NEWEST_FIRST:
            with self.subTest(text=text):
                self.assertIn(text, flat)

    def test_the_drawer_is_looked_up_by_the_session_the_canvas_names(self) -> None:
        """The canvas names its session as the RENDERED rows do - after
        redaction - while the attribution pass keys its lines by the raw
        identifier the log carries. Pinned with a redaction that actually
        changes a string, because with one that does not the two spellings
        agree by accident: a lookup on the wrong one comes back empty, and
        the drawer would report a busy session as an idle one."""
        with mock.patch.object(
            keel_dashboard,
            "redact",
            lambda value: value.upper() if isinstance(value, str) else value,
        ):
            root = _root(_mixed_fixture())
        self.assertEqual(root["session"], SESSION.upper())
        self.assertEqual([row["text"] for row in root["own_activity"]],
                         MIXED_OWN_NEWEST_FIRST)
        self.assertIn("1 hand-off(s)", root["summary"])

    def test_the_pass_returns_the_sessions_own_lines_beside_what_it_consumed(
        self,
    ) -> None:
        """The shape the whole property rests on, asserted directly: one
        call, both halves, and nothing in the second half is in the first."""
        events = _mixed_fixture()
        _open_items, _groups, consumed, own = keel_dashboard.compute_open_and_groups(events)
        self.assertEqual([entry["detail"] for entry in own[SESSION]],
                         list(reversed(MIXED_OWN_NEWEST_FIRST)))
        for entry in own[SESSION]:
            with self.subTest(detail=entry["detail"]):
                self.assertNotIn(id(entry), consumed)


# ------------------------------------------------------- the reference's shape


class TestTheDrawerMatchesTheReferencesSecondFrame(unittest.TestCase):
    """Header, summary, state line, then timestamped rows - each row a
    wall-clock time, a glyph naming the KIND, and content of one or two
    lines, newest first."""

    def test_every_row_carries_a_time_a_kind_and_its_content(self) -> None:
        rows = _root(_mixed_fixture())["own_activity"]
        self.assertEqual([sorted(row) for row in rows],
                         [["action_kind", "text", "ts"]] * len(rows))
        self.assertEqual([row["ts"] for row in rows],
                         sorted((row["ts"] for row in rows), reverse=True),
                         "newest first, as the reference's frame 2 is")

    def test_a_write_and_a_command_are_different_kinds(self) -> None:
        rows = {row["text"]: row["action_kind"] for row in _root(_mixed_fixture())["own_activity"]}
        self.assertEqual(rows["docs/last.md"], keel_dashboard.ACTION_KIND_WRITE)
        self.assertEqual(rows["git status --short"], keel_dashboard.ACTION_KIND_COMMAND)
        self.assertEqual(keel_dashboard.action_kind("NotebookEdit"),
                         keel_dashboard.ACTION_KIND_WRITE)
        self.assertEqual(keel_dashboard.action_kind("PowerShell"),
                         keel_dashboard.ACTION_KIND_COMMAND)

    def test_a_tool_in_neither_family_is_called_neither(self) -> None:
        """Total, and never guessed: a tool name the adapter does not know,
        an absent one and a non-string all mean the same thing here."""
        for value in ("Grep", "", None, 17, {"tool": "Write"}):
            with self.subTest(value=value):
                self.assertEqual(keel_dashboard.action_kind(value),
                                 keel_dashboard.ACTION_KIND_OTHER)

    def test_the_tool_families_are_the_adapters_own_not_a_second_list(self) -> None:
        """The same discipline T103 used for ``BG_LAUNCH_MS``: these must be
        the SAME objects, not two literals that happen to agree today."""
        self.assertIs(keel_dashboard.WRITE_TOOLS, keel_adapter_claude.WRITE_TOOLS)
        self.assertIs(keel_dashboard.SHELL_TOOLS, keel_adapter_claude.SHELL_TOOLS)

    def test_the_summary_line_carries_this_sessions_three_counts(self) -> None:
        lines = _mixed_fixture()
        lines += _handoff(SESSION, "t2", "keel:reviewer-correctness", "a review",
                          "2026-08-01T09:40:00Z", "2026-08-01T09:50:00Z")
        lines.append({"v": 1, "ts": "2026-08-01T09:41:00Z", "event": "gate_block",
                      "session": SESSION, "gate": "pre_write", "reason": "denied"})
        root = _root(lines)
        self.assertEqual(
            root["summary"],
            "this session: 2 hand-off(s) · 1 review hand-off(s) · 1 gate block(s)",
        )

    def test_the_summary_counts_this_session_and_not_the_log(self) -> None:
        """The drawer is on ONE node, so its figures are that session's - a
        block recorded under another session is not this one's."""
        lines = _mixed_fixture()
        lines.append({"v": 1, "ts": "2026-08-01T09:42:00Z", "event": "gate_block",
                      "session": "s2", "gate": "pre_write", "reason": "elsewhere"})
        self.assertIn("0 gate block(s)", _root(lines)["summary"])

    def test_a_reviewer_is_read_off_the_agent_types_own_name(self) -> None:
        """The rule the "review hand-off(s)" figure names, stated as values:
        an agent type whose name says reviewer, with or without a namespace,
        and nothing else."""
        for agent in ("keel:reviewer-correctness", "reviewer-tests",
                      "keel:reviewer-silent-failure"):
            with self.subTest(agent=agent):
                self.assertTrue(keel_dashboard.is_review_handoff(agent))
        for agent in ("keel:executor", "general-purpose", "keel:researcher", "", None):
            with self.subTest(agent=agent):
                self.assertFalse(keel_dashboard.is_review_handoff(agent))

    def test_the_state_line_repeats_the_nodes_own_chip(self) -> None:
        """One value, shown twice - the root node's own label. A second
        wording here is exactly how a panel and its node start disagreeing."""
        root = _root(_graph_fixture())
        self.assertEqual(root["label"],
                         keel_dashboard.graph_root_label(root["handoffs"], root["open"],
                                                         root["open_sessions"]))
        panel = _functions(self._script())["nodePanel"]
        self.assertIn("root.label", panel)
        self.assertNotIn("hand-off(s) drawn", panel)

    def test_the_node_and_its_drawer_name_the_role_with_one_string(self) -> None:
        self.assertEqual(_root(_graph_fixture())["role"], keel_dashboard.ROOT_ROLE_LABEL)
        functions = _functions(self._script())
        self.assertIn("root.role", functions["rootCard"])
        self.assertIn("root.role", functions["nodePanel"])

    def test_the_header_names_the_node_and_carries_a_close_control(self) -> None:
        """A page-source check, because a control is markup rather than a
        value: the header carries the node's name, its role and a real button
        a reader can press."""
        panel = _functions(self._script())["nodePanel"]
        self.assertIn("root.session", panel)
        self.assertIn('type="button"', panel)
        self.assertIn('data-role="closepanel"', panel)

    def test_the_rows_content_is_clamped_to_two_lines_not_truncated_early(self) -> None:
        """The reference's rows are one or two lines. The clamp is the style
        block's, so nothing the server sent is thrown away before a reader
        can widen the pane."""
        style = _style(self._page_text())
        self.assertIn("-webkit-line-clamp:2", _decl(style, ".arow .d"))
        row = _functions(self._script())["ownRow"]
        self.assertNotIn("slice(", row)
        self.assertNotIn("substring(", row)

    def test_the_glyph_carries_the_kind_as_a_word_too(self) -> None:
        """An icon alone is not a name: the row's glyph carries the server's
        own kind word as its title, and the page adds no fourth kind."""
        script = self._script()
        row = _functions(script)["ownRow"]
        self.assertIn('title="${esc(a.action_kind)}"', row)
        glyphs = script[script.index("const ACTION_GLYPH"):]
        glyphs = glyphs[: glyphs.index("\n")]
        for kind in (keel_dashboard.ACTION_KIND_WRITE, keel_dashboard.ACTION_KIND_COMMAND,
                     keel_dashboard.ACTION_KIND_OTHER):
            with self.subTest(kind=kind):
                self.assertIn(kind + ":", glyphs)

    def _page_text(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return _page(_project(Path(tmp), _mixed_fixture()))

    def _script(self) -> str:
        return _script(self._page_text())


# ------------------------------------------------- what the drawer leaves out


class TestTheDrawerSaysWhatItIsNotShowing(unittest.TestCase):
    def test_the_tail_bound_counts_what_it_left_out_rather_than_dropping_it(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z",
                  "event": "session_start", "session": SESSION}]
        lines += _handoff(SESSION, "t1", "keel:executor", "one hand-off",
                          "2026-08-01T09:10:00Z", "2026-08-01T09:20:00Z")
        total = keel_dashboard.OWN_ACTIVITY_TAIL + 7
        for index in range(total):
            lines.append(_own(SESSION, f"2026-08-01T10:{index // 60:02d}:{index % 60:02d}Z",
                              "Edit", f"docs/line-{index:03d}.md"))
        root = _root(lines)
        self.assertEqual(len(root["own_activity"]), keel_dashboard.OWN_ACTIVITY_TAIL)
        self.assertEqual(root["own_total"], total)
        self.assertEqual(root["own_note"],
                         "7 older line(s) of this session's own work are not shown")
        self.assertEqual(root["own_activity"][0]["text"], f"docs/line-{total - 1:03d}.md",
                         "the bound is taken from the NEWEST end")

    def test_a_session_with_nothing_of_its_own_says_so_rather_than_showing_a_blank(
        self,
    ) -> None:
        """An empty list with no sentence reads as "it did nothing", which is
        not what an empty list means."""
        root = _root(_graph_fixture())
        self.assertEqual(root["own_activity"], [])
        self.assertEqual(root["own_total"], 0)
        self.assertEqual(root["own_note"],
                         "no action by this session outside a delegation is recorded yet")

    def test_nothing_is_said_when_everything_is_shown(self) -> None:
        self.assertEqual(_root(_mixed_fixture())["own_note"], "")

    def test_a_line_with_no_target_on_record_says_so(self) -> None:
        """Absence expressed, never a blank row: the record holds the action
        but not what it acted on."""
        lines = _mixed_fixture()
        lines.append(_own(SESSION, "2026-08-01T09:31:00Z", "Write", ""))
        row = _root(lines)["own_activity"][0]
        self.assertEqual(row["text"], keel_dashboard.NO_ACTION_TARGET_NOTE)
        self.assertEqual(row["action_kind"], keel_dashboard.ACTION_KIND_WRITE)


# --------------------------------------------- opening it disturbs nothing


class TestOpeningTheDrawerDisturbsNothing(unittest.TestCase):
    """The structural half of the acceptance clause. There is no browser in
    this suite (see this module's "Values, not substrings"), so what is
    asserted is what the drawer's one writer is ABLE to touch - which is what
    decides whether an expanded delegation, a scroll position, the disconnect
    notice or a ticking card can survive it."""

    def setUp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.text = _page(_project(Path(tmp), _graph_fixture()))
        self.script = _script(self.text)
        self.functions = _functions(self.script)

    def _writer(self) -> str:
        return _sole_function_containing(self.functions, "panelOpen =")

    def test_the_drawer_has_exactly_one_writer_and_both_directions_use_it(self) -> None:
        """Open and close are the same three steps in one function, so a
        reader cannot end up in a state only one of them cleans up."""
        writer = self._writer()
        for marker in ('$("canvas").addEventListener("click"',
                       '$("canvas").addEventListener("keydown"',
                       '$("nodepanel").addEventListener'):
            with self.subTest(marker=marker):
                handler = _block_after(self.script, marker)
                self.assertIn(writer, _calls(handler, set(self.functions)))
                self.assertNotIn("innerHTML", handler)

    def test_that_writer_re_renders_no_pane_and_writes_no_age(self) -> None:
        """Reachability, not the absence of one call at one site: nothing the
        drawer's writer can reach, transitively, assigns the feed pane's
        markup, rebuilds the canvas, or puts an age in the footer. So the
        panels the reader had expanded, the rows they had opened and the
        disconnect notice are all still there afterwards."""
        writer = self._writer()
        reach = _reachable(self.functions, writer) | {writer}
        for forbidden in (
            _sole_function_containing(self.functions, PANE_MARKUP),
            _sole_function_containing(self.functions, FRESHNESS_NODE),
            _sole_function_containing(self.functions, '$("canvas").innerHTML'),
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, reach)
        for name in reach:
            with self.subTest(name=name):
                self.assertNotIn("fetch(", self.functions[name])
                self.assertNotIn("Date.now()", self.functions[name])

    def test_the_cards_keep_ticking_because_the_drawer_holds_no_ticking_row(
        self,
    ) -> None:
        """The elapsed figures on the cards advance from the DOM the ticker
        walks (``data-key`` nodes inside the canvas). The drawer adds no such
        node and rebuilds no card, so the walk finds exactly what it found
        before the drawer opened."""
        for name in ("nodePanel", "ownRow", "renderNodePanel"):
            with self.subTest(name=name):
                self.assertNotIn("data-key", self.functions[name])
        walker = _sole_function_containing(self.functions, "#canvas .node[data-key]")
        self.assertNotIn(self._writer(), _reachable(self.functions, walker) | {walker})

    def test_the_drawer_re_measures_the_wires_because_the_canvas_narrowed(self) -> None:
        """The one thing it MUST do besides drawing itself: the cards are
        still on screen and have moved, so the edges are measured again -
        without rebuilding a single card."""
        wires = _sole_function_containing(self.functions, "getBoundingClientRect")
        self.assertIn(wires, _calls(self.functions[self._writer()], set(self.functions)))

    def test_the_drawer_is_shut_until_the_reader_opens_it(self) -> None:
        self.assertIn('id="nodepanel" hidden', self.text)
        self.assertIn("let panelOpen = false;", self.script)
        self.assertIn("display:none", _decl(_style(self.text), ".npanel[hidden]"))

    def test_the_drawer_takes_width_beside_the_canvas_rather_than_covering_it(
        self,
    ) -> None:
        """The reference's frame 2 narrows the canvas and keeps its cards.
        A drawer that floated over them would hide the very thing the frame
        shows still running."""
        panel = _decl(_style(self.text), ".npanel")
        self.assertIn("flex:none", panel)
        self.assertRegex(panel, r"width:\d+px")
        self.assertNotIn("position:absolute", panel)
        self.assertNotIn("position:fixed", panel)

    def test_a_click_on_bare_canvas_ground_opens_nothing(self) -> None:
        """This task opens the drawer on the ROOT node only; T106 gives a
        worker card (`.node`) the same control, so what is pinned here now is
        that a click reaching neither still does nothing."""
        handler = _block_after(self.script, '$("canvas").addEventListener("click"')
        self.assertIn('closest(".rootnode")', handler)
        self.assertIn('closest(".node")', handler)

    def test_the_full_render_refreshes_an_open_drawer(self) -> None:
        """A poll that brings new lines must reach an open drawer, or it
        would freeze at whatever it held when it was opened - and it is
        refreshed BEFORE the canvas, so the wires are measured at the width
        the drawer actually leaves."""
        full = _sole_function_containing(self.functions, "feed(")
        body = self.functions[full]
        renderer = _sole_function_containing(self.functions, '$("nodepanel")')
        canvas = _sole_function_containing(self.functions, '$("canvas").innerHTML')
        self.assertIn("innerHTML", self.functions[renderer],
                      "the drawer's markup is assigned in its own one writer")
        self.assertIn(renderer, _calls(body, set(self.functions)))
        self.assertLess(body.index(renderer + "("), body.index(canvas + "("))


# ------------------------------------------------------------ honesty holds


class TestHonestyRulesHoldInTheDrawer(unittest.TestCase):
    def test_the_drawers_payload_names_no_model_no_tier_and_no_stall(self) -> None:
        text = json.dumps(_root(_mixed_fixture())).lower()
        for word in ("opus", "sonnet", "haiku", "model", "tier", "stalled", "hung", "stuck"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)

    def test_every_value_the_drawer_renders_is_escaped(self) -> None:
        """The drawer's markup is assigned to ``innerHTML``, and its rows
        carry paths and command heads out of the audit log."""
        with tempfile.TemporaryDirectory() as tmp:
            functions = _functions(_script(_page(_project(Path(tmp), _mixed_fixture()))))
        for expression in ("esc(clock(a.ts))", "esc(a.action_kind)", "esc(a.text)"):
            with self.subTest(expression=expression):
                self.assertIn(expression, functions["ownRow"])
        for field in ("root.session", "root.role", "root.summary", "root.label",
                      "root.own_note"):
            with self.subTest(field=field):
                self.assertIn("esc(" + field + ")", functions["nodePanel"])

    def test_the_drawer_carries_no_figure_the_record_cannot_support(self) -> None:
        """Every field on it is either a count of lines the record holds or a
        string this module worded - there is no elapsed figure, no rate and
        no judgement of progress."""
        root = _root(_mixed_fixture())
        self.assertEqual(root["own_total"], len(root["own_activity"]))
        self.assertEqual(
            sorted(set(root) - {"id", "session", "handoffs", "open", "open_sessions",
                                "label"}),
            ["own_activity", "own_note", "own_total", "role", "summary"],
        )


if __name__ == "__main__":
    unittest.main()
