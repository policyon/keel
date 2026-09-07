#!/usr/bin/env python3
"""T119 - the page recomposed into the owner's pinned frame: five regions.

Contract
--------
Reads   : temporary directories this file creates, and ``keel_dashboard``'s
          own source through ``inspect`` - no fixture here touches this
          repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
The reference is a FRAME, not a skin (a later task restyles the cards and
the wires). What this task owed was the page's REGIONS - a header bar with
right-aligned stat tiles, the canvas as the dominant area, a roster row
along its foot, a right sidebar of two stacked sections, and a legend bar at
the very foot - and the four tiles in that header.

Five claims are pinned here, in this order:

1. THE FIVE REGIONS EXIST, each by its own structural id or class, each
   holding what the reference puts in it, and the sidebar sits at the RIGHT
   of the canvas without the markup of a single pane having been moved out
   of the order it was already written in (T119 re-seats by ``order``; the
   panes themselves were not rewritten, which is why every earlier suite
   still reads them where it always did).
2. THE TILES READ THE PAYLOAD - field to tile, not pixel to position. Each
   of the four names ONE payload field, and the five figures the header
   carried before this task are still computed in exactly one place each.
3. NOTHING IS LOST. The owner's standing sentence, as an enumeration: every
   load-bearing surface the page carried - the filter chips and their
   counts, the per-task accept clauses, the arming chip, the read-only
   notice, the liveness pill, the roster, the node drawer, the disconnect
   notice, the losses line, the two figures no tile carries and all three
   footer sentences - is still in the page a browser receives.
4. THE LEGEND NAMES REAL AGENTS - every agent type the payload's own roster
   carries, plus the agents keel actually ships, and no persona invented
   anywhere on this page. What it says about each is display-only and is
   never read from disk at runtime.
5. A COLLAPSE STILL GIVES SOMETHING BACK. T6's two panels sat side by side
   and each handed its width to the canvas; stacked in one sidebar column
   they cannot, and the honest rule that replaces it is pinned here rather
   than deferred to someone opening a browser: a shut section's row is sized
   to its own rail so the OPEN section takes the freed height, and only with
   both shut does the column narrow to the rail and the canvas take the
   width. The state this forbids - a 34px rail sitting beside dead space,
   its row still holding half a 380px column - is asserted absent.
6. TASKS DONE REUSES THE LEDGER'S OWN COUNT. There is exactly ONE reading of
   ``TERMINAL_MARKS`` in this module and the tile cannot count at all - the
   same single-source discipline T104 and T109 already hold this module to,
   pinned at source level the way T108's own tests pin a single resolution.

Values, not substrings
-----------------------
Everything the page SAYS is asserted as a value read off ``read_state``, as
``test_keel_dashboard_t28_31.py`` documents. The page-source and style-block
checks below are for structural claims a value cannot express - which region
holds which pane, which declaration decides a width, which field a tile is
wired to - and each says so in its own docstring.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import ast
import inspect
import re
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Callable
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    DISCONNECT_SENTENCE,
    HEADER_FIGURES,
    _block_after,
    _decl,
    _functions,
    _graph_fixture,
    _handoff,
    _page,
    _project,
    _script,
    _sole_function_containing,
    _style,
)
from test_keel_dashboard_t105 import _state  # noqa: E402

#: A ledger with one task of every mark keel's own vocabulary knows: three
#: terminal (``x``/``!``/``?``, which need no further proof) and two that are
#: not (``  ``/``~``). Its one honest reading is therefore 3 of 5.
LEDGER_FIVE_TASKS = (
    "# Session plan — abcdef12, a ledger with every mark\n"
    "\n"
    "- [x] T1: done | route: executor\n"
    "  Accept: the suite is green\n"
    "- [!] T2: blocked | route: executor\n"
    "- [?] T3: needs a decision | route: executor\n"
    "- [ ] T4: not started | route: executor\n"
    "- [~] T5: in flight | route: executor\n"
)

#: WHAT EACH TILE IS WIRED TO. Four rows: the tile's own structural key
#: (``data-stat``), the label the page's own figure list holds the number
#: under, the word the tile prints, and the EXPRESSION that computes the
#: figure. The first three tiles are counts of audit lines; TASKS DONE is
#: asserted separately, because it is not one (see its own class below).
TILE_BINDINGS: tuple[tuple[str, str, str, str], ...] = (
    ("working", "working now", "working now", "c.working"),
    ("handoffs", "hand-offs", "hand-offs", "c.handoff_start"),
    ("blocks", "blocks", "gate blocks", "c.gate_block + c.stop_block"),
)

#: EVERY LOAD-BEARING SURFACE, by the marker that proves it is on the page,
#: named by what it IS rather than by where it sits - the point of the
#: enumeration is that a recomposition may move a surface anywhere and may
#: lose none of them. A marker removed from here is a surface removed from
#: the page, which is exactly the regression this list exists to catch.
LOAD_BEARING: dict[str, str] = {
    "the project path": 'id="project"',
    "the arming tier chip": 'id="arming"',
    "the read-only notice": "read-only · no write route",
    "the liveness pill": 'id="liveness"',
    "the events and sessions figures": 'id="corpus"',
    "the stat tiles": 'id="stats"',
    "the roster": 'id="roster"',
    "the ledger selector": 'id="plansel"',
    "the ledger progress figure": 'id="progress"',
    "the ledger task list": 'id="ledger"',
    "the feed filter buttons": 'id="filters"',
    "the audit feed": 'id="feed"',
    "the losses line": 'id="lost"',
    "the freshness line": 'id="freshness"',
    "the canvas": 'id="canvas"',
    "the canvas note": 'id="graphnote"',
    "the node panel": 'id="nodepanel" hidden',
    "the legend bar": 'id="agentlegend"',
    "what the page reads": (
        ".keel/audit/keel-audit.jsonl + .keel/plans/ · nothing is written"
    ),
    "the quiet-time caveat": "quiet-time is INFERRED from gaps in the log, never measured",
    "the canvas's own standing text": "no edge joins two hand-offs",
}

#: Surfaces that live inside the page's SCRIPT rather than its markup - a
#: chip the feed builds per kind, a task's accept clause, the disconnect
#: sentence. Same enumeration, different half of the page.
LOAD_BEARING_SCRIPT: dict[str, str] = {
    "a filter chip carries its own count": 'class="chip',
    "a task's accept clause": '<details class="accept">',
    "the disconnect notice": DISCONNECT_SENTENCE,
    "the arming chip's own words": " · ARMED",
}


#: THE THREE SHAPES A COLLAPSE MAY LEAVE THE SIDEBAR IN, plus the shape it
#: starts in, as the two rows each one declares. Row order is the document's:
#: the ledger above, the audit feed below. While ANY section is still open,
#: exactly one row is flexible - that is where the freed height goes - and a
#: shut section's row is sized to its own rail, which is what keeps a rail
#: from ever sitting beside dead space.
SIDEBAR_ROWS: dict[str, tuple[str, str]] = {
    "#side": ("minmax(0,1fr)", "minmax(0,1fr)"),
    "#side:has(#p-ledger.shut)": ("max-content", "minmax(0,1fr)"),
    "#side:has(#p-feed.shut)": ("minmax(0,1fr)", "max-content"),
    "#side:has(#p-ledger.shut):has(#p-feed.shut)": ("max-content", "max-content"),
}

#: Which row belongs to which section, for the reading above.
SECTION_ROW: dict[str, int] = {"#p-ledger": 0, "#p-feed": 1}


def _code(obj: Callable[..., Any]) -> str:
    """One function's CODE, with its docstring and every comment removed.

    The page's own suite strips ``//`` comments before reading structure off
    the script, for the reason ``_script`` states: a comment that mentions a
    name is not a call to it. The same rule has to hold on this side, or a
    docstring that MENTIONS ``TERMINAL_MARKS`` would read as a second place
    that counts terminal marks. ``ast.unparse`` drops both at once.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    body = list(tree.body[0].body)  # type: ignore[attr-defined]
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return "\n".join(ast.unparse(stmt) for stmt in body)


def _module_functions_containing(needle: str) -> set[str]:
    """Every function in ``keel_dashboard`` whose CODE names ``needle``."""
    found: set[str] = set()
    for name, obj in vars(keel_dashboard).items():
        if not inspect.isfunction(obj) or obj.__module__ != keel_dashboard.__name__:
            continue
        if needle in _code(obj):
            found.add(name)
    return found


def _between(text: str, opening: str, closing: str) -> str:
    """The slice of the page between two markers, both asserted present."""
    assert opening in text, opening
    start = text.index(opening)
    assert closing in text[start:], closing
    return text[start : text.index(closing, start)]


def _rows(style: str, selector: str) -> tuple[str, ...]:
    """The row track list one sidebar rule declares, as its own tracks."""
    match = re.search(r"grid-template-rows:([^;}]+)", _decl(style, selector))
    assert match, f"{selector} declares no rows"
    return tuple(re.findall(r"minmax\([^)]*\)|[\w-]+", match.group(1)))


def _order(style: str, selector: str) -> int:
    """The painted ``order`` one region declares."""
    match = re.search(r"order:(\d+)", _decl(style, selector))
    assert match, f"{selector} declares no order"
    return int(match.group(1))


# ------------------------------------------------------------- the regions


class TestTheFiveRegions(unittest.TestCase):
    """STRUCTURE, and declared: which region holds which pane is markup and
    a style block, not a value ``read_state`` could carry. Each region is
    found by its own id or class - never by a pixel position, which no test
    without a browser could read and no reader would recognise anyway."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.style = _style(cls.text)

    def test_region_one_is_a_header_bar_carrying_the_pages_identity(self) -> None:
        header = _between(self.text, '<header id="topbar">', "</header>")
        self.assertIn("<h1>keel</h1>", header)
        for marker in ('id="project"', 'id="arming"', "read-only · no write route",
                       'id="liveness"', 'id="corpus"', 'id="stats"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, header)

    def test_the_stat_tiles_sit_at_the_right_of_that_bar(self) -> None:
        """The reference right-aligns them, and the header is a flex row, so
        ``margin-left:auto`` is the whole of it - the tiles take the room the
        left cluster does not."""
        self.assertIn("display:flex", _decl(self.style, "header"))
        self.assertIn("margin-left:auto", _decl(self.style, "#stats"))
        self.assertIn("flex:1 1 auto", _decl(self.style, ".hleft"))

    def test_a_tile_is_a_boxed_number_over_its_own_label(self) -> None:
        """The reference's tile shape: a bordered box, the figure above, the
        label under it in small uppercase."""
        self.assertIn("border", _decl(self.style, ".stat"))
        self.assertIn("display:block", _decl(self.style, ".stat b"))
        self.assertIn("text-transform:uppercase", _decl(self.style, ".stat span"))

    def test_region_two_is_the_canvas_and_it_is_the_dominant_area(self) -> None:
        """The canvas AREA is the only flexible child of ``main``; the
        sidebar and the drawer both declare ``flex:none``, so every pixel
        neither of them takes is the canvas's."""
        area = _decl(self.style, "#canvasarea")
        self.assertIn("flex:1 1 auto", area)
        self.assertIn("min-width:0", area)
        self.assertIn("flex:none", _decl(self.style, "#side"))
        self.assertIn("flex:none", _decl(self.style, ".npanel"))
        self.assertIn('id="canvas"', _between(self.text, '<div id="canvasarea">', "</main>"))

    def test_region_three_is_a_right_sidebar_of_two_stacked_sections(self) -> None:
        """Two sections, stacked, sharing the sidebar's height - a grid of
        two ``minmax(0,1fr)`` rows, which is what lets each section scroll
        its own list rather than the taller one pushing the other out."""
        side = _decl(self.style, "#side")
        self.assertIn("grid-template-rows:minmax(0,1fr) minmax(0,1fr)", side)
        markup = _between(self.text, '<div id="side">', '<div id="canvasarea">')
        self.assertLess(markup.index('id="p-ledger"'), markup.index('id="p-feed"'),
                        "the ledger sits above the feed, as the reference stacks them")
        for marker in ('id="plansel"', 'id="progress"', 'id="ledger"',
                       'id="filters"', 'id="feed"', 'id="lost"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, markup)

    def test_each_sidebar_section_carries_a_small_uppercase_heading(self) -> None:
        markup = _between(self.text, '<div id="side">', '<div id="canvasarea">')
        self.assertIn('<span class="ttl">Plan ledger</span>', markup)
        self.assertIn('<span class="ttl">Event feed</span>', markup)
        # Leading newline: ``.panel.shut .phead`` also ends in ``.phead{``,
        # and the rule wanted here is the one that opens its own line.
        self.assertIn("text-transform:uppercase", _decl(self.style, "\n.phead"))

    def test_the_sidebar_is_painted_at_the_right_without_moving_a_pane(self) -> None:
        """T119 re-seats by ``order`` alone: the sidebar is still FIRST in
        the document - which is why every earlier suite still finds its panes
        exactly where they were written - and paints last, at the right of
        the canvas and the drawer."""
        self.assertLess(self.text.index('<div id="side">'),
                        self.text.index('<div id="canvasarea">'))
        self.assertLess(_order(self.style, "#canvasarea"), _order(self.style, ".npanel"))
        self.assertLess(_order(self.style, ".npanel"), _order(self.style, "#side"))

    def test_the_sidebar_is_about_the_references_width(self) -> None:
        width = int(re.search(r"width:(\d+)px", _decl(self.style, ".panel")).group(1))
        self.assertGreaterEqual(width, 340)
        self.assertLessEqual(width, 420)

    def test_region_four_is_the_roster_along_the_foot_of_the_canvas(self) -> None:
        """Inside the canvas area and AFTER the canvas, but outside the
        scrolling stage - a session with many cards must not be able to push
        the roster off the screen."""
        area = _between(self.text, '<div id="canvasarea">', "</main>")
        self.assertIn('id="roster"', area)
        stage = _between(area, '<div class="stage">', '<div class="roster"')
        self.assertIn('id="canvas"', stage)
        self.assertNotIn('id="roster"', stage)
        self.assertIn("overflow:auto", _decl(self.style, ".stage"))
        self.assertIn("flex:none", _decl(self.style, ".roster"))

    def test_region_five_is_the_legend_bar_at_the_very_foot(self) -> None:
        self.assertLess(self.text.index("</main>"), self.text.index('<footer id="legendbar">'))
        footer = _between(self.text, '<footer id="legendbar">', "</footer>")
        self.assertIn('<div id="agentlegend">', footer)
        self.assertIn('id="freshness"', footer)

    def test_the_page_does_not_scroll_sideways_at_the_width_it_is_drawn_for(
        self,
    ) -> None:
        """NUMBERS, not a claim. At 1280px the sidebar sits beside the canvas
        (the narrow layout's own breakpoint is below that), it takes less
        than half the window, and every region between it and the window
        edge may be narrower than its own content (``min-width:0``) - which
        is what keeps a long path or a wide card from widening the page
        instead of scrolling inside its own region."""
        narrow = int(re.search(r"@media \(max-width:(\d+)px\)", self.style).group(1))
        self.assertLess(narrow, 1280, "at 1280 the sidebar sits beside the canvas")
        width = int(re.search(r"width:(\d+)px", _decl(self.style, ".panel")).group(1))
        self.assertLess(width, 1280 / 2)
        # Leading newline again: ``html,body`` shares the ``body{`` ending.
        self.assertIn("overflow:hidden", _decl(self.style, "\nbody"))
        self.assertIn("min-width:0", _decl(self.style, "#canvasarea"))
        self.assertIn("min-width:0", _decl(self.style, ".stage"))

    def test_each_sidebar_section_scrolls_its_own_list(self) -> None:
        lists = _decl(self.style, "#ledger,#feed")
        self.assertIn("overflow-y:auto", lists)
        self.assertIn("min-height:0", lists)
        self.assertIn("min-height:0", _decl(self.style, "#side"))


# ------------------------------------------------ what a collapse gives back


class TestACollapsedSectionGivesItsRoomBack(unittest.TestCase):
    """STYLE BLOCK, and declared: which track a row takes is CSS, and CSS is
    where this rule lives - the collapse handler still toggles one class and
    reads nothing. T6's own suite left "a collapse really does widen the
    canvas" to a manual browser run; the rule that replaces it is written as
    three declarations, so it is asserted here instead of deferred."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.style = _style(cls.text)

    def test_each_collapse_shape_declares_its_own_rows(self) -> None:
        for selector, tracks in SIDEBAR_ROWS.items():
            with self.subTest(selector=selector):
                self.assertEqual(_rows(self.style, selector), tracks)

    def test_a_shut_section_never_keeps_a_share_of_the_column(self) -> None:
        """THE DEAD-SPACE CASE, asserted absent. A rail whose row still held
        half a 380px column would be a collapse that bought the reader
        nothing: the rail sits at the left of its row and the rest of the row
        is empty. So a shut section's row is sized to the rail itself, and
        the sibling that is still open holds the only flexible row."""
        for section, index in SECTION_ROW.items():
            selector = f"#side:has({section}.shut)"
            sibling = 1 - index
            with self.subTest(shut=section):
                tracks = _rows(self.style, selector)
                self.assertEqual(tracks[index], "max-content")
                self.assertNotIn("fr", tracks[index])
                self.assertEqual(tracks[sibling], "minmax(0,1fr)")

    def test_both_shut_leaves_no_flexible_row_at_all(self) -> None:
        tracks = _rows(self.style, "#side:has(#p-ledger.shut):has(#p-feed.shut)")
        for track in tracks:
            with self.subTest(track=track):
                self.assertNotIn("fr", track)

    def test_the_both_shut_rule_is_read_after_the_single_ones(self) -> None:
        """Equal-specificity rules are decided by order, so the shape for two
        shut sections has to be declared last or one of the single rules
        would still be describing the column."""
        both = self.style.index("#side:has(#p-ledger.shut):has(#p-feed.shut){")
        for section in SECTION_ROW:
            with self.subTest(shut=section):
                self.assertLess(self.style.index(f"#side:has({section}.shut){{"), both)

    def test_collapsing_both_hands_the_width_to_the_canvas(self) -> None:
        """The sidebar declares NO width of its own - the column is as wide
        as its widest section - so once both sections are their own rail the
        column is the rail's width and everything it gave up goes to the one
        flexible region beside it, the canvas area."""
        side = _decl(self.style, "#side")
        self.assertNotRegex(side, r"(^|;)\s*width:")
        rail = int(re.search(r"width:(\d+)px", _decl(self.style, ".panel.shut")).group(1))
        opened = int(re.search(r"width:(\d+)px", _decl(self.style, ".panel")).group(1))
        self.assertLess(rail, opened, "a collapsed section must narrow the column")
        self.assertIn("flex:1 1 auto", _decl(self.style, "#canvasarea"))

    def test_the_geometry_is_the_style_blocks_and_not_the_handlers(self) -> None:
        """The handler still toggles ONE class on ONE section and writes
        nothing else - no width, no track, no inline style - which is what
        keeps T6's own "collapsing deletes nothing" property true of the
        stacked sidebar too."""
        handler = _block_after(_script(self.text), '$("side").addEventListener')
        self.assertIn('classList.toggle("shut")', handler)
        for forbidden in ("grid", "style", "width", "height"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, handler)


# ------------------------------------------------------- the header's tiles


class TestTheHeadersStatTiles(unittest.TestCase):
    """FIELD TO TILE, never pixel to position: each tile names one payload
    field, and the figures behind them are still computed in one place each.
    """

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.functions = _functions(_script(cls.text))
        cls.state = _state(_graph_fixture())

    def test_there_are_exactly_four_tiles_and_one_writer_of_them(self) -> None:
        writer = _sole_function_containing(self.functions, '$("stats").innerHTML')
        body = self.functions[writer]
        self.assertEqual(body.count('<div class="stat"'), 1,
                         "one template, one writer - the tiles are a list, not four copies")
        self.assertEqual(len(re.findall(r'\["\w[^"]*", "[^"]+",', body)), 4,
                         "the reference's header carries four tiles")

    def test_each_tile_names_one_payload_field(self) -> None:
        """The BINDING, read off the page's own source: the figure list still
        computes each figure exactly once, and the tile list seats one of
        those figures - by the same label - in a box of its own."""
        body = self.functions[
            _sole_function_containing(self.functions, '$("stats").innerHTML')
        ]
        for key, row, word, expression in TILE_BINDINGS:
            with self.subTest(tile=key):
                self.assertIn(f'["{row}", {expression}]', body)
                self.assertIn(f'["{key}", "{word}", figure.get("{row}")', body)

    def test_the_tasks_tile_reads_the_ledgers_own_progress(self) -> None:
        body = self.functions[
            _sole_function_containing(self.functions, '$("stats").innerHTML')
        ]
        self.assertIn('["tasks", "tasks done", plan.progress_tile, plan.progress_tile_note]',
                      body)

    def test_the_renderer_hands_the_tiles_the_two_payload_fields(self) -> None:
        full = _sole_function_containing(self.functions, "session_liveness")
        self.assertIn("stats(s.counts, s.plan)", self.functions[full])

    def test_the_figures_the_tiles_read_are_the_payloads_own(self) -> None:
        """VALUES: the fixture is one session with four hand-offs, three of
        them still open and none blocked, so the three counting tiles read 3,
        4 and 0 - numbers this test states rather than recomputes."""
        counts = self.state["counts"]
        self.assertEqual(counts["working"], 3)
        self.assertEqual(counts["handoff_start"], 4)
        self.assertEqual(counts["gate_block"] + counts["stop_block"], 0)

    def test_a_tile_says_in_words_what_it_counted(self) -> None:
        """GATE BLOCKS is the reference's word and this figure counts both of
        keel's own gates, so the tile states that rather than letting the
        shorter word imply the narrower count."""
        body = self.functions[
            _sole_function_containing(self.functions, '$("stats").innerHTML')
        ]
        self.assertIn("gate_block and stop_block lines", body)
        self.assertIn('title="${esc(t[3])}"', body)


# ---------------------------------------------------------- nothing is lost


class TestNothingIsLost(unittest.TestCase):
    """The owner's standing sentence, as an enumeration. A recomposition may
    move any surface anywhere and may lose none of them."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.script = _script(cls.text)

    def test_every_load_bearing_surface_is_still_in_the_page(self) -> None:
        for surface, marker in LOAD_BEARING.items():
            with self.subTest(surface=surface):
                self.assertIn(marker, self.text)

    def test_every_load_bearing_surface_the_script_builds_is_still_built(self) -> None:
        for surface, marker in LOAD_BEARING_SCRIPT.items():
            with self.subTest(surface=surface):
                self.assertIn(marker, self.script)

    def test_the_five_header_figures_are_still_computed_once_each(self) -> None:
        """The reference has four tiles and the header carried five figures.
        Neither of the two without a tile was dropped to make the picture
        match: both are still computed by the same expression they always
        were, and both are seated in the header's left cluster."""
        for figure in HEADER_FIGURES:
            with self.subTest(figure=figure):
                self.assertIn(figure, self.text)
        self.assertIn('const CORPUS = ["events", "sessions"];', self.script)
        self.assertIn('$("corpus").textContent', self.script)

    def test_the_filter_chips_still_carry_their_counts(self) -> None:
        functions = _functions(self.script)
        self.assertIn("counts[k]", functions["filters"])


# -------------------------------------------------------------- the legend


class TestTheLegendBar(unittest.TestCase):
    """Real names only, every roster type covered, and nothing about it read
    from disk while the viewer is running."""

    def test_it_names_every_agent_type_the_roster_carries(self) -> None:
        lines = _graph_fixture()
        lines += _handoff("s1", "D", "general-purpose", "a host tool's own agent",
                          "2026-08-01T10:40:00Z", "2026-08-01T10:41:00Z")
        state = _state(lines)
        legend = {row["agent_type"]: row for row in state["legend"]}
        for entry in state["roster"]:
            with self.subTest(agent_type=entry["agent_type"]):
                self.assertIn(entry["agent_type"], legend)
                self.assertTrue(legend[entry["agent_type"]]["role"])

    def test_a_type_keel_does_not_ship_says_so_rather_than_being_dropped(self) -> None:
        lines = _handoff("s1", "D", "general-purpose", "a host tool's own agent",
                         "2026-08-01T10:40:00Z", "2026-08-01T10:41:00Z")
        state = _state(lines)
        legend = {row["agent_type"]: row for row in state["legend"]}
        self.assertEqual(legend["general-purpose"]["role"], keel_dashboard.LEGEND_UNKNOWN_ROLE)
        self.assertEqual(legend["general-purpose"]["tone"], keel_dashboard.AGENT_TONE_OTHER)

    def test_keels_own_agents_are_named_even_before_one_has_ever_run(self) -> None:
        state = _state([])
        self.assertEqual(state["roster"], [])
        named = [row["agent_type"] for row in state["legend"]]
        self.assertEqual(named, list(keel_dashboard.AGENT_ROLES))

    def test_it_invents_no_persona_and_repeats_no_name(self) -> None:
        state = _state(_graph_fixture())
        named = [row["agent_type"] for row in state["legend"]]
        self.assertEqual(len(named), len(set(named)))
        known = set(keel_dashboard.AGENT_ROLES) | {r["agent_type"] for r in state["roster"]}
        for name in named:
            with self.subTest(agent_type=name):
                self.assertIn(name, known)

    def test_the_roles_are_the_agents_own_one_line_purposes(self) -> None:
        """VALUES: every shipped agent has a role line, none is empty, and
        each is one line - the frontmatter's own ``description``, shortened.
        """
        for name, role in keel_dashboard.AGENT_ROLES.items():
            with self.subTest(agent_type=name):
                self.assertTrue(role.strip())
                self.assertNotIn("\n", role)
                self.assertTrue(name.startswith("keel:"))

    def test_the_families_the_dots_stand_for(self) -> None:
        """VALUES: the two executor TIERS are told apart, the reviewer family
        shares one colour, and the reviewer reading is the same one the
        drawer's own review count already uses."""
        cases = {
            "keel:executor": keel_dashboard.AGENT_TONE_EXECUTOR,
            "keel:executor-deep": keel_dashboard.AGENT_TONE_DEEP,
            "keel:researcher": keel_dashboard.AGENT_TONE_RESEARCH,
            "keel:reviewer-correctness": keel_dashboard.AGENT_TONE_REVIEW,
            "reviewer-tests": keel_dashboard.AGENT_TONE_REVIEW,
            "general-purpose": keel_dashboard.AGENT_TONE_OTHER,
            "": keel_dashboard.AGENT_TONE_OTHER,
        }
        for agent, tone in cases.items():
            with self.subTest(agent=agent):
                self.assertEqual(keel_dashboard.agent_tone(agent), tone)
        self.assertIn("is_review_handoff", _code(keel_dashboard.agent_tone))

    def test_the_page_renders_a_dot_and_a_role_for_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), _graph_fixture()))
        functions = _functions(_script(text))
        body = functions[_sole_function_containing(functions, '$("agentlegend").innerHTML')]
        self.assertIn("lgdot tone-${esc(e.tone)}", body)
        self.assertIn("esc(e.agent_type)", body)
        self.assertIn("esc(e.role)", body)
        style = _style(text)
        self.assertIn("border-radius:50%", _decl(style, ".lgdot"))
        for tone in (keel_dashboard.AGENT_TONE_EXECUTOR, keel_dashboard.AGENT_TONE_DEEP,
                     keel_dashboard.AGENT_TONE_RESEARCH, keel_dashboard.AGENT_TONE_REVIEW):
            with self.subTest(tone=tone):
                self.assertIn(f".lgdot.tone-{tone}{{", style)

    def test_the_role_table_is_display_only_and_never_read_from_disk(self) -> None:
        """The purposes are a hardcoded copy of what ``agents/*.md``
        frontmatter says, because this viewer may not read those files: its
        contract opens exactly two things under the surveyed project. So
        nothing here opens a file, and nothing on the page is COUNTED,
        filtered or matched by the table - only shown."""
        readers = _module_functions_containing("AGENT_ROLES")
        self.assertEqual(readers, {"legend_entries"})
        source = _code(keel_dashboard.legend_entries) + _code(keel_dashboard.agent_tone)
        for forbidden in ("open(", "read_text", "Path(", "glob", "iterdir", "agents/"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertEqual(set(keel_dashboard.READ_ROUTES), {"/", "/api/state", "/api/plan"})


# -------------------------------------------- tasks done is not a second count


class TestTasksDoneReusesTheLedgersOwnCount(unittest.TestCase):
    """SOURCE-LEVEL, and declared: "there is only one of these" is a claim
    about the whole module, which no single value can carry - the same way
    T108 pins that ``read_state`` resolves a session exactly once."""

    def test_exactly_one_function_reads_the_terminal_marks(self) -> None:
        self.assertEqual(_module_functions_containing("TERMINAL_MARKS"), {"ledger_progress"})

    def test_the_tile_cannot_count_at_all(self) -> None:
        """It is handed the mapping ``ledger_progress`` built and formats it.
        There is no task list in it, no loop and no total of its own, so it
        cannot state a figure the panel's own heading disagrees with."""
        code = _code(keel_dashboard.progress_tile)
        for forbidden in ("TERMINAL_MARKS", "sum(", "for ", "len(", "tasks"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code)

    def test_the_ledger_is_counted_once_and_both_renderings_read_that_count(
        self,
    ) -> None:
        code = _code(keel_dashboard.read_ledger)
        self.assertEqual(code.count("ledger_progress("), 1)
        self.assertIn("progress_tile(progress)", code)
        self.assertIn("progress_label(progress)", code)

    def test_the_tile_and_the_panel_state_the_same_figure(self) -> None:
        """VALUES: five tasks, three of them terminal - the tile reads 3/5
        and the panel's own heading words the very same pair."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [], ledger_text=LEDGER_FIVE_TASKS)
            state = keel_dashboard.read_state(project)
        plan = state["plan"]
        self.assertEqual(plan["progress"], {"terminal": 3, "total": 5})
        self.assertEqual(plan["progress_tile"], "3/5")
        self.assertEqual(plan["progress_label"], "(3/5 terminal)")
        self.assertEqual(plan["progress_tile_note"], "(3/5 terminal)")

    def test_a_ledger_with_nothing_to_divide_reads_zero_of_zero_and_says_why(
        self,
    ) -> None:
        """The tile never vanishes - the reference's header has four boxes -
        and ``0/0`` is never left to be mistaken for a ledger that was read
        and found empty: the note beside it is the ledger STATE's own
        sentence, the one the panel already shows."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [], ledger_text="# a ledger with no tasks\n")
            state = keel_dashboard.read_state(project)
        plan = state["plan"]
        self.assertEqual(plan["state"], "empty")
        self.assertEqual(plan["progress_tile"], "0/0")
        self.assertEqual(plan["progress_label"], "")
        self.assertEqual(plan["progress_tile_note"], keel_dashboard.PLAN_NOTES["empty"])

    def test_the_page_computes_no_terminal_figure_of_its_own(self) -> None:
        """The client renders the server's pair; it must never re-derive one
        from the task marks it is also given - that would be a second answer
        to the same question, the drift T104's own label rule forbids."""
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [], ledger_text=LEDGER_FIVE_TASKS)))
        self.assertNotIn("terminal", script)
        self.assertIn("plan.progress_tile", script)


if __name__ == "__main__":
    unittest.main()
