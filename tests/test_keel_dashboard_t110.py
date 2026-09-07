#!/usr/bin/env python3
"""T110 - the reference's visual language, and motion that means "running".

Contract
--------
Reads   : temporary directories this file creates, and ``keel_dashboard``'s
          own source through a real loopback fetch of the page - no fixture
          here touches this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
T119 landed the FRAME (five regions, stat tiles, legend bar). This task is
the SKIN inside it, and the one claim it lives or dies by:

    MOTION IS RESERVED FOR LIVE WORK. A delegation still open animates, by
    its card and by its wire. Everything closed is still. With nothing open
    the page has no animation at all.

That is the load-bearing claim, so it is pinned first and pinned
structurally rather than by looking at one rendering: every ``@keyframes``
block in the page is enumerated, every rule that references one is found,
and each of those rules is required to sit behind a marker that CANNOT be
on the page unless work is open. The three markers are then chased back to
the three places the script emits them, so the gate is proved at both ends -
the CSS may not move without a marker, and the marker may not exist without
an open delegation.

The rest is the reference's own vocabulary, each checked where it lives:
the dot grid, the AGENT corner tag, the avatar disc, the title over its grey
subtitle, the state pill's chip, the curved dashed wires and their circular
ports, the larger centre node with its warm halo, its latest chip and its
truncated path line. And, because a repaint is exactly where a page loses
things: nothing the page carried before this task is gone, no card lost its
control affordance or its ticker marker, and the page still fetches nothing
from anywhere.

Values, not substrings
-----------------------
Everything the page SAYS is asserted as a value read off ``read_state`` or
the label functions themselves, as ``test_keel_dashboard_t28_31.py``
documents. What is left - which selector gates which animation, which
condition emits which class, when the wire layer is recomputed - is
structure a value cannot express, and every one of those checks says so in
its own docstring.

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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
from test_keel_dashboard_t28_31 import (  # noqa: E402
    PRESERVED_MARKERS,
    _block_after,
    _calls,
    _functions,
    _graph_fixture,
    _handoff,
    _page,
    _project,
    _reachable,
    _script,
    _sole_function_containing,
    _style,
    _timer_target,
)
from test_keel_dashboard_t105 import _state  # noqa: E402

#: THE THREE MARKERS MOTION HANGS OFF, and the whole of them. A rule that
#: animates must sit behind one of these; a marker must be emitted only for
#: work that is actually open. Both halves are asserted below, because
#: either one alone would let motion loose: a gated rule whose marker is
#: painted on every card animates everything, and an honest marker with an
#: ungated rule beside it animates the page regardless.
LIVE_MARKERS: tuple[str, ...] = (".node.live", ".rootnode.live.acting", ".wire.flow")

#: The reduced-motion escape hatch, named here so the test below reads as a
#: claim rather than as a regex.
REDUCED_MOTION = "@media (prefers-reduced-motion:reduce)"

_KEYFRAMES = re.compile(r"@keyframes\s+([\w-]+)\s*\{")
_ANIMATION = re.compile(r"(?:^|;)\s*animation(?:-name)?\s*:\s*([^;}]+)")


def _css(text: str) -> str:
    """The page's style block with its comments and its opening tag gone.

    Comments are stripped for the same reason ``_script`` strips ``//``
    lines on the other half of the page: prose that MENTIONS an animation is
    not an animation, and a suite that could not tell the two apart would be
    measuring the wrong thing.
    """
    style = _style(text)
    body = style[style.index("<style>") + len("<style>") :]
    return re.sub(r"/\*.*?\*/", "", body, flags=re.S)


def _rules(css: str) -> tuple[tuple[str, str], ...]:
    """Every plain rule in a style block, as ``(selector, declarations)``.

    Braces are BALANCED rather than matched non-greedily, so an ``@media``
    block is descended into (its rules apply, and must be gated like any
    other) and a ``@keyframes`` block is not (its ``0%``/``50%`` steps are
    not selectors and cannot gate anything). Anything this cannot read
    raises rather than returning a shorter list - a rule silently skipped
    here is a rule the gate test would never see.
    """
    out: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while True:
        brace = css.find("{", i)
        if brace < 0:
            return tuple(out)
        selector = css[i:brace].strip()
        depth, j = 0, brace
        while j < n:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        assert depth == 0, f"unbalanced braces reading {selector!r}"
        body = css[brace + 1 : j]
        if selector.startswith("@keyframes"):
            pass
        elif selector.startswith("@"):
            out.extend(_rules(body))
        else:
            out.append((selector, body))
        i = j + 1


def _rule(css: str, selector: str) -> str:
    """What ONE selector declares, matched EXACTLY.

    ``_decl`` in the shared suite finds a rule by substring, which is right
    for the selectors it was written for and wrong for a class that is also
    the tail of a descendant selector: ``.avatar`` would come back as
    ``.rootnode .avatar``'s declarations, and a test could pass on a rule it
    was not asking about. Every declaration this suite reads goes through
    here instead. Where one selector is declared more than once (the page
    does that deliberately for ``.rootnode``), all of them are returned -
    that IS what the selector declares.
    """
    bodies = [body for sel, body in _rules(css) if sel == selector]
    assert bodies, f"no rule with selector {selector!r}"
    return ";".join(bodies)


def _animations(css: str) -> tuple[tuple[str, str], ...]:
    """Every rule that actually STARTS an animation, as
    ``(selector, keyframes-name)``. ``animation:none`` is a rule that stops
    one and is not counted as motion."""
    found: list[tuple[str, str]] = []
    for selector, body in _rules(css):
        for value in _ANIMATION.findall(body):
            name = value.strip().split()[0]
            if name != "none":
                found.append((selector, name))
    return tuple(found)


def _closed_only() -> list[dict[str, Any]]:
    """A session whose every hand-off has CLOSED - the state in which this
    page must be completely still."""
    lines: list[dict[str, Any]] = [
        {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s1"},
        {"v": 1, "ts": "2026-08-01T09:40:00Z", "event": "session_end", "session": "s1"},
    ]
    lines += _handoff("s1", "t1", "keel:executor", "a closed hand-off",
                      "2026-08-01T09:10:00Z", "2026-08-01T09:20:00Z")
    lines += _handoff("s1", "t2", "keel:reviewer-correctness", "a second closed hand-off",
                      "2026-08-01T09:25:00Z", "2026-08-01T09:30:00Z")
    return lines


# -------------------------------------------------- motion means "running"


class TestMotionIsReservedForLiveWork(unittest.TestCase):
    """THE load-bearing claim of this task, and the reason it is pinned
    structurally: "the page is still when nothing is running" is a statement
    about EVERY rule in the style block and every route that writes a class,
    which no single rendering could demonstrate. So the style block is
    enumerated rather than sampled, and the enumeration is required to be
    complete - a fourth animation added later fails this the moment it is
    not gated, which is exactly the regression the owner's rule exists to
    prevent."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.css = _css(cls.text)
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)

    def test_every_animation_rule_is_gated_on_a_live_marker(self) -> None:
        """No rule anywhere in the page starts an animation unless its own
        selector requires one of the three live markers. Enumerated over the
        WHOLE style block, media queries included."""
        animated = _animations(self.css)
        self.assertTrue(animated, "the page declares no animation at all")
        for selector, name in animated:
            with self.subTest(selector=selector):
                self.assertTrue(
                    any(marker in selector for marker in LIVE_MARKERS),
                    f"{selector!r} animates {name!r} without requiring a live marker",
                )

    def test_every_keyframes_block_is_used_and_only_by_a_gated_rule(self) -> None:
        """The other direction: a ``@keyframes`` block that nothing gated
        references would be motion waiting to be switched on, and one
        referenced from somewhere this suite did not enumerate would be
        motion already loose."""
        defined = set(_KEYFRAMES.findall(self.css))
        used = {name for _, name in _animations(self.css)}
        self.assertEqual(defined, used)
        self.assertEqual(
            len(defined), 3, "this page has exactly three animations, by design"
        )

    def test_the_three_gates_are_the_card_the_wire_and_the_halo(self) -> None:
        """Which marker carries which animation - stated, so a later reader
        can see at a glance that the card and the wire both move for an open
        delegation (the acceptance names both) and that the third is the
        centre node's own."""
        by_marker = {}
        for selector, name in _animations(self.css):
            for marker in LIVE_MARKERS:
                if marker in selector:
                    by_marker[marker] = name
        self.assertEqual(set(by_marker), set(LIVE_MARKERS))

    def test_a_card_is_marked_live_exactly_when_the_record_says_it_is_open(
        self,
    ) -> None:
        """The card end of the gate. ``n.open`` is the SAME reading the
        header's WORKING NOW figure counts, so the cards that move and the
        figure that counts them cannot disagree - and ``" live"`` appears in
        this renderer nowhere else, so there is no second route to the
        marker."""
        card = self.functions["nodeCard"]
        self.assertIn('const live = n.open ? " live" : "";', card)
        self.assertEqual(card.count('" live"'), 1)
        state = _state(_graph_fixture())
        nodes = state["graph"]["nodes"]
        self.assertEqual(
            sum(1 for n in nodes if n["open"]), state["counts"]["working"],
            "the animated cards and the WORKING NOW figure are one reading",
        )

    def test_the_wire_drifts_only_beside_a_card_already_marked_live(self) -> None:
        """The wire end of the gate, and a single source: the overlay path is
        emitted from the CARD's own class read back off the DOM, never from a
        second judgement of its own."""
        wires = self.functions[_sole_function_containing(self.functions,
                                                         "getBoundingClientRect")]
        self.assertIn('const live = el.classList.contains("live") ? " live" : "";', wires)
        self.assertIn('if (live) parts.push(`<path class="wire flow"', wires)
        self.assertEqual(wires.count('class="wire flow"'), 1)

    def test_the_halo_is_the_servers_own_liveness_and_nothing_derived(self) -> None:
        """The halo end of the gate. The page reads ``session_liveness`` in
        exactly one function (T108's own rule, unchanged) and HANDS DOWN the
        answer; the canvas is never given the field to interpret."""
        reader = _sole_function_containing(self.functions, "session_liveness")
        body = self.functions[reader]
        self.assertIn('const sessionLive = s.session_liveness.state === "live";', body)
        self.assertIn("drawCanvas(s.graph, s.now, sessionLive)", body)
        root = self.functions["rootCard"]
        self.assertNotIn("session_liveness", root)
        self.assertIn("const acting = live && root.open > 0;", root)
        self.assertIn('const mark = live ? (acting ? " live acting" : " live") : "";', root)

    def test_with_nothing_open_no_marker_can_be_on_the_page(self) -> None:
        """The claim itself, as a VALUE: a session whose every hand-off has
        closed reports no open node and no open count, so neither ``.live``
        (which is ``n.open``) nor ``acting`` (which additionally requires
        ``root.open``) can be written, and ``drawWires`` emits no ``.flow``
        path because no card carries ``.live``. With all three markers absent
        every rule found above is inert, and the canvas is still."""
        graph = _state(_closed_only())["graph"]
        self.assertTrue(graph["nodes"], "the fixture must actually draw cards")
        self.assertFalse([n for n in graph["nodes"] if n["open"]])
        self.assertEqual(graph["root"]["open"], 0)

    def test_no_animation_conveys_anything_the_words_do_not(self) -> None:
        """VALUES: every animated state is stated in words beside it - the
        pill prints its own state word, and the line under the session's
        name prints how many delegations are open. A reader who cannot
        perceive motion loses nothing."""
        self.assertEqual(keel_dashboard.delegation_state_label("open"), "open")
        self.assertIn("open now", keel_dashboard.graph_root_label(4, 2, 0))
        graph = _state(_graph_fixture())["graph"]
        for node in graph["nodes"]:
            with self.subTest(task=node["task_label"]):
                self.assertTrue(node["state_label"].strip())

    def test_a_reader_who_asks_for_less_motion_gets_none_of_it(self) -> None:
        """The escape hatch, and that it covers all three - it is the last
        thing in the block, so it wins, and it names every marker."""
        self.assertIn(REDUCED_MOTION, self.css)
        block = _block_after(self.css, REDUCED_MOTION)
        self.assertIn("animation:none", block)
        for marker in LIVE_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, block)


# ------------------------------------------------ the wire layer's own clock


class TestTheWireLayerRecomputesOnRenderNotOnAClock(unittest.TestCase):
    """STRUCTURAL, and declared: "the geometry is measured when it can have
    changed, and never polled" is a claim about which callers reach the
    measuring function, which no value can carry. The page still runs
    exactly two timers, and neither of them is the wires'."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)
        cls.wires = _sole_function_containing(cls.functions, "getBoundingClientRect")

    def test_the_render_recomputes_the_wires(self) -> None:
        canvas = _sole_function_containing(self.functions, '$("canvas").innerHTML')
        self.assertIn(self.wires, _calls(self.functions[canvas], set(self.functions)))
        poll = _timer_target(self.script, "POLL_MS")
        self.assertIn(self.wires, _reachable(self.functions, poll))

    def test_the_wires_have_no_timer_of_their_own(self) -> None:
        ticker = _timer_target(self.script, "TICK_MS")
        self.assertNotIn(self.wires, _reachable(self.functions, ticker) | {ticker})
        for forbidden in ("setInterval", "setTimeout", "requestAnimationFrame"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.functions[self.wires])
        self.assertNotIn("requestAnimationFrame", self.script)
        self.assertEqual(self.script.count("setInterval("), 2,
                         "the page still runs exactly the two timers it had")

    def test_the_wires_are_remeasured_whenever_the_cards_can_have_moved(self) -> None:
        """The three places geometry changes without a redraw: the window
        resizes, a sidebar section collapses, the drawer opens or closes."""
        self.assertIn('window.addEventListener("resize", ' + self.wires, self.script)
        collapse = _block_after(self.script, '$("side").addEventListener("click"')
        self.assertIn(self.wires, _calls(collapse, set(self.functions)))
        drawer = self.functions[_sole_function_containing(self.functions, "panelOpen =")]
        self.assertIn(self.wires, _calls(drawer, set(self.functions)))


# ------------------------------------------------- the reference's own skin


class TestTheReferencesVisualLanguage(unittest.TestCase):
    """STRUCTURE: a dot grid, a corner tag, a disc, a chip and a curve are
    markup and declarations, not values ``read_state`` could carry. Each is
    found by the class or declaration that draws it, never by a pixel
    position no test without a browser could read."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.css = _css(cls.text)
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)

    def test_the_ground_carries_a_dot_grid_drawn_by_a_gradient(self) -> None:
        stage = _rule(self.css, ".stage")
        self.assertIn("radial-gradient", stage)
        self.assertIn("background-size:", stage)
        self.assertNotIn("url(", self.text)

    def test_a_worker_card_carries_the_agent_tag_on_its_own_border(self) -> None:
        """The reference's corner tag - a label for the KIND of card, riding
        the top border, which is what the negative offset says."""
        self.assertIn('<span class="atag">AGENT</span>', self.functions["nodeCard"])
        tag = _rule(self.css, ".atag")
        self.assertIn("position:absolute", tag)
        self.assertRegex(tag, r"top:-\d")
        self.assertIn("position:relative", _rule(self.css, ".node"))

    def test_both_nodes_carry_one_circular_avatar_disc_drawn_inline(self) -> None:
        """One constant, used by both renderers, drawn as inline SVG - the
        content policy forbids an image and this page has no network. It is
        decoration and is hidden from a screen reader, so no word a reader
        needs is carried by a picture."""
        self.assertEqual(self.script.count("const AVATAR ="), 1)
        for name in ("nodeCard", "rootCard"):
            with self.subTest(name=name):
                self.assertIn("${AVATAR}", self.functions[name])
        self.assertIn('<span class="avatar" aria-hidden="true">', self.script)
        self.assertIn('<svg class="bot"', self.script)
        self.assertIn("border-radius:50%", _rule(self.css, ".avatar"))

    def test_a_worker_card_is_a_title_over_a_grey_subtitle(self) -> None:
        """The reference's own stack. The subtitle is the agent TYPE the
        record holds - the one thing about who ran a hand-off that the log
        actually carries - and it is grey rather than an accent, which is
        what makes the live treatment beside it read as a state."""
        card = self.functions["nodeCard"]
        self.assertIn('<span class="cname">Agent</span>', card)
        self.assertIn('<span class="role">${esc(n.agent_label)}</span>', card)
        self.assertLess(card.index('class="cname"'), card.index('class="role"'))
        self.assertIn("var(--ink)", _rule(self.css, ".cname"))
        self.assertIn("var(--ink2)", _rule(self.css, ".role"))
        self.assertIn("border-radius:999px", _rule(self.css, ".role"))

    def test_the_state_pill_is_a_rounded_chip_carrying_its_own_dot(self) -> None:
        card = self.functions["nodeCard"]
        self.assertIn('<span class="pdot"></span>${esc(n.state_label)}', card)
        self.assertIn("border-radius:999px", _rule(self.css, ".pill"))
        self.assertIn("border-radius:50%", _rule(self.css, ".pdot"))

    def test_the_wires_are_thin_curves_dashed_with_a_port_at_each_card(self) -> None:
        wires = self.functions[_sole_function_containing(self.functions,
                                                         "getBoundingClientRect")]
        self.assertIn(" C ", wires, "a bezier, not a straight line")
        self.assertIn('<path class="wire', wires)
        self.assertIn('<circle class="port', wires)
        self.assertIn('<circle class="port hub"', wires)
        wire = _rule(self.css, ".wire")
        self.assertIn("fill:none", wire)
        self.assertIn("stroke-dasharray", wire)
        port = _rule(self.css, ".port")
        self.assertIn("stroke", port)

    def test_the_centre_node_is_larger_and_carries_a_warm_halo(self) -> None:
        """Larger by declaration, not by hope: its own minimum width is wider
        than a worker card's fixed width. The halo is a shadow it carries
        only while live, and a worker card carries no shadow at all."""
        root = _rule(self.css, ".rootnode")
        node = _rule(self.css, ".node")
        self.assertGreater(int(re.search(r"min-width:(\d+)px", root).group(1)),
                           int(re.search(r"width:(\d+)px", node).group(1)))
        self.assertIn("box-shadow", root)
        self.assertNotIn("box-shadow", node)
        self.assertIn("box-shadow", _rule(self.css, ".rootnode.live"))

    def test_the_centre_node_shows_its_latest_chip_and_its_last_path(self) -> None:
        """Both come from ``own_activity`` - the SAME already-redacted rows
        the drawer lists (T105), newest first as the server built them - so
        the canvas cannot name a line the drawer does not, and neither line
        is truncated in the page: the style block clips it, so nothing the
        server sent is thrown away before a reader can open the drawer."""
        card = self.functions["rootCard"]
        self.assertIn("root.own_activity", card)
        self.assertIn('<div class="rchip"', card)
        self.assertIn('<div class="rpath"', card)
        self.assertIn("esc(latest.text)", card)
        self.assertIn("esc(wrote.text)", card)
        self.assertIn('a.action_kind === "write"', card)
        for selector in (".rootnode .rchip", ".rootnode .rpath"):
            with self.subTest(selector=selector):
                self.assertIn("text-overflow:ellipsis", _rule(self.css, selector))
        root = _state(_graph_fixture())["graph"]["root"]
        self.assertIn("own_activity", root)


# ---------------------------------------------------------- nothing is lost


class TestTheRepaintCostThePageNothing(unittest.TestCase):
    """The owner's standing sentence, as an enumeration - a repaint is
    exactly where a page quietly loses a control, a marker or a word."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), _graph_fixture()))
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)

    def test_every_preserved_surface_is_still_on_the_page(self) -> None:
        for marker in PRESERVED_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, self.text)

    def test_a_card_is_still_a_control_and_still_carries_its_ticker_marker(
        self,
    ) -> None:
        """T106's affordance and T3's in-place ticker both hang off markup
        this task restyled around: the card is still a button by pointer and
        by keyboard, and still carries the ``data-key`` the one-second walk
        finds it by."""
        card = self.functions["nodeCard"]
        for marker in ('role="button"', 'tabindex="0"', "data-key=", 'data-role="quiet"',
                       'data-role="elapsed"'):
            with self.subTest(marker=marker):
                self.assertIn(marker, card)
        self.assertIn('role="button"', self.functions["rootCard"])
        self.assertIn('tabindex="0"', self.functions["rootCard"])

    def test_the_pills_still_say_exactly_what_they_said(self) -> None:
        """VALUES: the four state words and the finished pill's own class are
        untouched by the repaint."""
        for state, word in (("open", "open"), ("background", "background"),
                            ("awaited", "awaited"), ("finished", "finished")):
            with self.subTest(state=state):
                self.assertIn(word, keel_dashboard.delegation_state_label(state))
        self.assertIn("st-finished", self.functions["nodeCard"])
        self.assertIn(keel_dashboard.BACKGROUND_STATE_NOTE,
                      keel_dashboard.delegation_state_note("background"))

    def test_the_card_still_names_no_model_and_no_tier(self) -> None:
        """The honesty rule, re-checked over the markup this task rewrote."""
        for name in ("nodeCard", "rootCard"):
            body = self.functions[name].lower()
            for word in ("opus", "sonnet", "haiku", "model", "tier", "stalled",
                         "hung", "stuck"):
                with self.subTest(name=name, word=word):
                    self.assertNotIn(word, body)

    def test_the_page_still_fetches_nothing_from_anywhere(self) -> None:
        """The skin added a glyph and a grid, and both are drawn in the page:
        no image, no font, no stylesheet, nothing to fetch."""
        self.assertEqual(self.text.count("<style>"), 1)
        self.assertEqual(self.text.count("<script>"), 1)
        for forbidden in ("http://", "https://", "@import", "url(", "<link",
                          "<img", "<iframe", "<object", "@font-face", " src="):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.text)


if __name__ == "__main__":
    unittest.main()
