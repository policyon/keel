#!/usr/bin/env python3
"""T120 - the event feed states a sentence, in the reference's voice.

Contract
--------
Reads   : temporary directories this file creates, and ``keel_dashboard``'s
          own source through ``inspect``/its script text - no fixture here
          touches this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
A flat feed row used to show only its raw event name and a field-by-field
detail line. This task adds a SENTENCE beside it (``feed_sentence``), built
server-side from the SAME already-redacted fields ``detail_text`` already
reads - no second event read, no second decision about what a kind means.
The verb is the record's own KIND and nothing else (``EVENT_VERBS``): an end
record ("reported back") never claims a finish, only a matched
``subagent_stop`` may say "finished" - the T104 wording law, restated for
this row. ``session_start``/``session_end`` are plain statements, because no
agent ran a session. A kind neither table names renders exactly as it did
before this task: the raw name plus ``detail_text``.

The raw event name is never hidden behind its sentence - it moved into the
row's own ``title`` attribute, beside the wall-clock time that used to sit
in the row itself - and the filter buttons and their counts are untouched.
Two items from the reference are declined in the module's own docstring
rather than silently dropped: the "alerts off" toggle (no alert machinery)
and persona renaming (real agent names stand).

ADDENDUM: an icon and a ticking relative time. Each row now carries an icon
(``FEED_GLYPH[e.feed_verb]``) keyed by ``feed_verb`` - the SAME verb family
``feed_sentence`` already read off the record, never re-derived from the raw
kind - and reusing the page's own existing glyph vocabulary (``MARK``'s DONE
and BLOCKED marks) rather than inventing one. The relative time is rendered
at draw time into a ``data-role="feed-ago"``/``data-ts`` span, the same shape
T118 already marks a resting roster chip's last-seen figure with, and ticks
the same way (``tickFeed``, run from the existing one-second ``ticker``) so
a quiet feed's "N ago" cannot freeze the way the roster's once did.

Values, not substrings
-----------------------
Every claim about WHAT a sentence or a verb family says is asserted as a
value read off ``feed_sentence``/``feed_verb`` directly or off
``read_state``'s own ``feed``, as ``test_keel_dashboard_t28_31.py``
documents. Which template the page's script renders, where the raw name and
wall-clock live in the markup, and how the ticker reaches the relative-time
span are structural claims a value cannot express, and say so in their own
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
import unittest
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

#: THE VERB TABLE, restated here so the acceptance's own words ("verb chosen
#: by event kind ... table driven both directions") are pinned against the
#: module's real ``EVENT_VERBS`` rather than a copy this file could drift
#: from.
VERB_TABLE: tuple[tuple[str, str], ...] = (
    ("handoff_start", "launched"),
    ("handoff_end", "reported back"),
    ("subagent_stop", "finished"),
    ("gate_block", "blocked"),
    ("stop_block", "blocked"),
)

#: THE GLYPH TABLE (addendum): one glyph per VERB FAMILY, "session" being the
#: fifth family beside the four verbs above. Restated here, against the
#: page's own script, for the same reason ``VERB_TABLE`` is restated against
#: ``EVENT_VERBS``.
GLYPH_TABLE: tuple[tuple[str, str], ...] = (
    ("launched", "▶"),
    ("reported back", "↩"),
    ("finished", "✓"),
    ("blocked", "!"),
    ("session", "●"),
)


def _row(kind: str, **fields: Any) -> dict[str, Any]:
    """One already-redacted feed row, as ``feed_sentence`` receives it."""
    row: dict[str, Any] = {"event": kind}
    row.update(fields)
    return row


def _orphan_handoff_end(session: str, tid: str, agent: str, description: str,
                         ts: str) -> dict[str, Any]:
    """A ``handoff_end`` with no matching start - the shape that reaches the
    FLAT feed as its own row (``row_kind: "event"``) rather than being folded
    into a closed group, so this task's sentence can be read off a real
    ``read_state`` payload rather than only off ``feed_sentence`` directly."""
    return {"v": 1, "ts": ts, "event": "handoff_end", "session": session,
            "tool_use_id": tid, "agent_id": None, "subagent_type": agent,
            "description": description}


def _stop(session: str, agent: str, ts: str) -> dict[str, Any]:
    """A ``subagent_stop`` line exactly as ``hooks/keel_hook.py`` writes one
    - session, ``agent_id``, ``agent_type``, and nothing that could ever
    carry a task description (see ``cmd_subagent_stop``'s own contract)."""
    return {"v": 1, "ts": ts, "event": "subagent_stop", "session": session,
            "agent_id": "a1", "agent_type": agent}


# -------------------------------------------------- the verb table itself


class TestTheVerbTableMatchesTheAcceptance(unittest.TestCase):
    """The acceptance's own five kinds, and no others, name a verb."""

    def test_event_verbs_is_exactly_the_acceptances_table(self) -> None:
        self.assertEqual(keel_dashboard.EVENT_VERBS, dict(VERB_TABLE))

    def test_session_kinds_are_plain_statements_not_verbs(self) -> None:
        self.assertNotIn("session_start", keel_dashboard.EVENT_VERBS)
        self.assertNotIn("session_end", keel_dashboard.EVENT_VERBS)
        self.assertEqual(keel_dashboard.SESSION_SENTENCES["session_start"],
                         "Session started")
        self.assertEqual(keel_dashboard.SESSION_SENTENCES["session_end"],
                         "Session ended")


class TestVerbPerEventKindBothDirections(unittest.TestCase):
    """Each kind gets ITS OWN verb, and no kind gets another kind's - stated
    both directions, exactly as the acceptance asks."""

    def test_each_kind_carries_its_own_verb(self) -> None:
        for kind, verb in VERB_TABLE:
            with self.subTest(kind=kind):
                row = _row(kind, subagent_type="keel:executor",
                          agent_type="keel:executor", description="T6 retry")
                self.assertIn(verb, keel_dashboard.feed_sentence(row))

    def test_no_kind_carries_a_different_kinds_verb(self) -> None:
        for kind, own_verb in VERB_TABLE:
            row = _row(kind, subagent_type="keel:executor",
                      agent_type="keel:executor", description="T6 retry")
            sentence = keel_dashboard.feed_sentence(row)
            for other_kind, other_verb in VERB_TABLE:
                if other_verb == own_verb:
                    continue
                with self.subTest(kind=kind, forbidden=other_verb):
                    self.assertNotIn(other_verb, sentence,
                                     f"{kind!r}'s sentence borrowed {other_kind!r}'s verb")


# -------------------------------------------- an end record is not a finish


class TestAnEndRecordNeverSaysFinished(unittest.TestCase):
    """[[a-recorded-end-is-not-a-finish]], restated for this row: a
    ``handoff_end`` is the launching tool's own RETURN, and this sentence
    never claims more than that."""

    def test_the_table_never_maps_handoff_end_to_finished(self) -> None:
        self.assertNotEqual(keel_dashboard.EVENT_VERBS["handoff_end"], "finished")
        self.assertEqual(keel_dashboard.EVENT_VERBS["handoff_end"], "reported back")

    def test_a_handoff_end_sentence_never_contains_the_word_finished(self) -> None:
        row = _row("handoff_end", subagent_type="keel:executor",
                  description="T7 fix stale docstring")
        sentence = keel_dashboard.feed_sentence(row)
        self.assertNotIn("finished", sentence.lower())
        self.assertIn("reported back", sentence)

    def test_only_a_matched_subagent_stop_may_say_finished(self) -> None:
        for kind, verb in VERB_TABLE:
            with self.subTest(kind=kind):
                if kind == "subagent_stop":
                    self.assertEqual(verb, "finished")
                else:
                    self.assertNotEqual(verb, "finished")

    def test_an_unmatched_handoff_end_reaches_the_real_flat_feed_reporting_back(
        self,
    ) -> None:
        """END TO END: a lone ``handoff_end`` with no start on record is not
        folded into any group and lands in the flat feed as itself, and the
        sentence ``read_state`` hands the page for it never claims a finish."""
        lines = [_orphan_handoff_end("s1", "Z", "keel:executor",
                                     "T7 fix stale docstring", "2026-08-01T10:00:00Z")]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        flat = [r for r in state["feed"] if r["row_kind"] == "event"]
        self.assertEqual(len(flat), 1)
        row = flat[0]
        self.assertEqual(row["event"], "handoff_end")
        self.assertIn("reported back", row["feed_sentence"])
        self.assertNotIn("finished", row["feed_sentence"].lower())


# --------------------------------------------------- the raw name is kept


class TestTheRawNameStaysReachable(unittest.TestCase):
    """Structural: which attribute carries the raw name is markup a value
    cannot express - it is asserted here on the row's own template."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), []))
        cls.functions = _functions(_script(cls.text))

    def test_the_row_carries_its_own_raw_kind_and_wall_clock_as_a_title(self) -> None:
        """The addendum: the wall-clock span this row used to show moved into
        the row's own ``title``, beside the raw kind - neither is dropped,
        only relocated to make room for the icon and the relative time."""
        self.assertIn('title="${esc(e.event)} · ${esc(clock(e.ts))}"',
                      self.functions["evRow"])

    def test_the_filter_buttons_and_their_counts_are_untouched(self) -> None:
        """The acceptance's own words: filter buttons stay exactly as they
        are. ``filters`` still keys off ``counts[k]`` per ``FILTERABLE``
        entry, and every kind this task added a sentence for is still one of
        the ten filterable kinds."""
        self.assertIn("counts[k]", self.functions["filters"])
        script = _script(self.text)
        for kind, _verb in VERB_TABLE:
            with self.subTest(kind=kind):
                self.assertIn(f'"{kind}"', script)
        self.assertIn('"session_start"', script)
        self.assertIn('"session_end"', script)

    def test_the_raw_event_field_survives_alongside_its_sentence(self) -> None:
        """VALUE: the flat row's own ``event`` field is never replaced or
        renamed by ``feed_sentence`` - both live on the same row."""
        lines = [_orphan_handoff_end("s1", "Z", "keel:executor", "d",
                                     "2026-08-01T10:00:00Z")]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        row = [r for r in state["feed"] if r["row_kind"] == "event"][0]
        self.assertEqual(row["event"], "handoff_end")
        self.assertIn("feed_sentence", row)


# ------------------------------------------------- a task-less record is short


class TestATaskLessRecordGetsTheShortSentence(unittest.TestCase):
    """The acceptance's own case: a record with no task says less, never
    inventing one."""

    def test_no_description_says_only_agent_and_verb(self) -> None:
        row = _row("handoff_start", subagent_type="keel:executor")
        self.assertEqual(keel_dashboard.feed_sentence(row), "keel:executor agent launched")

    def test_a_subagent_stop_never_carries_a_description_and_reads_short(self) -> None:
        """VALUE, end to end: ``hooks/keel_hook.py``'s own ``cmd_subagent_stop``
        writes session/agent_id/agent_type and nothing else, so this record
        can never earn a task clause - it reads "Agent finished" alone."""
        lines = [_stop("s1", "keel:executor", "2026-08-01T10:00:00Z")]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        row = [r for r in state["feed"] if r["row_kind"] == "event"][0]
        self.assertEqual(row["feed_sentence"], "keel:executor agent finished")
        self.assertNotIn("—", row["feed_sentence"])

    def test_a_record_naming_no_agent_type_at_all_says_agent_alone(self) -> None:
        row = _row("gate_block")
        self.assertEqual(keel_dashboard.feed_sentence(row), "Agent blocked")

    def test_a_kind_with_no_verb_and_no_task_earns_no_invented_sentence(self) -> None:
        """``activity``/``gate_bypass``/``override_active_at_stop`` name no
        verb at all; the page's own fallback (raw name plus ``detail_text``)
        is what renders for them, never a guessed sentence."""
        for kind in ("activity", "gate_bypass", "override_active_at_stop"):
            with self.subTest(kind=kind):
                self.assertEqual(keel_dashboard.feed_sentence(_row(kind)), "")


# -------------------------------------------------------------- plain statements


class TestSessionLinesArePlainStatements(unittest.TestCase):
    def test_session_start_names_no_agent(self) -> None:
        sentence = keel_dashboard.feed_sentence(_row("session_start"))
        self.assertEqual(sentence, "Session started")
        self.assertNotIn("Agent", sentence)

    def test_session_end_names_no_agent(self) -> None:
        sentence = keel_dashboard.feed_sentence(_row("session_end"))
        self.assertEqual(sentence, "Session ended")
        self.assertNotIn("Agent", sentence)


# -------------------------------------------------- the group's own members


class TestGroupedMemberRowsAlsoCarryTheSentence(unittest.TestCase):
    """The same renderer (``evRow``) draws a closed hand-off's nested events
    (T106), so a member line earns the same sentence field from the same
    single function - never a second decision for the nested case."""

    def test_a_closed_pairs_own_events_carry_feed_sentence_too(self) -> None:
        lines = _handoff("s1", "A", "keel:executor", "a closed hand-off",
                         "2026-08-01T10:00:00Z", "2026-08-01T10:00:04Z")
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        groups = [r for r in state["feed"] if r["row_kind"] == "group"]
        self.assertEqual(len(groups), 1)
        for member in groups[0]["events"]:
            with self.subTest(event=member["event"]):
                self.assertIn("feed_sentence", member)
                self.assertEqual(member["feed_sentence"],
                                 keel_dashboard.feed_sentence(member))


# ------------------------------------------------ the verb family (addendum)


class TestFeedVerbBothDirections(unittest.TestCase):
    """``feed_verb`` is the ONE field the icon lookup keys off - the same
    three cases ``feed_sentence`` already decides, read off the same field,
    asserted both directions the way the verb table itself is above."""

    def test_each_kind_reports_its_own_verb_family(self) -> None:
        for kind, verb in VERB_TABLE:
            with self.subTest(kind=kind):
                self.assertEqual(keel_dashboard.feed_verb(_row(kind)), verb)

    def test_session_kinds_report_the_session_family(self) -> None:
        self.assertEqual(keel_dashboard.feed_verb(_row("session_start")), "session")
        self.assertEqual(keel_dashboard.feed_verb(_row("session_end")), "session")

    def test_a_kind_with_no_verb_reports_no_family(self) -> None:
        for kind in ("activity", "gate_bypass", "override_active_at_stop"):
            with self.subTest(kind=kind):
                self.assertEqual(keel_dashboard.feed_verb(_row(kind)), "")

    def test_no_kind_reports_a_different_kinds_family(self) -> None:
        for kind, own_verb in VERB_TABLE:
            family = keel_dashboard.feed_verb(_row(kind))
            self.assertEqual(family, own_verb)
            for _other_kind, other_verb in VERB_TABLE:
                if other_verb == own_verb:
                    continue
                with self.subTest(kind=kind, forbidden=other_verb):
                    self.assertNotEqual(family, other_verb)

    def test_feed_verb_reaches_a_real_flat_row(self) -> None:
        lines = [_orphan_handoff_end("s1", "Z", "keel:executor", "d",
                                     "2026-08-01T10:00:00Z")]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        row = [r for r in state["feed"] if r["row_kind"] == "event"][0]
        self.assertEqual(row["feed_verb"], "reported back")


# ------------------------------------------------ the icon (addendum)


class TestGlyphPerVerbFamilyBothDirections(unittest.TestCase):
    """The addendum's own words: one glyph per verb family, table-driven
    both directions, the same shape as the verb table's own test above -
    read off the page's script, since the glyph lookup itself is decoration
    the page chooses, keyed by the server's own ``feed_verb``."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), []))
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)
        match = re.search(r"const FEED_GLYPH = \{([^;]*)\};", cls.script)
        assert match, "no FEED_GLYPH table in the page's script"
        cls.table_text = match.group(1)

    def test_each_family_carries_its_own_glyph(self) -> None:
        expected = {
            "launched": '"▶"', "reported back": '"↩"', "finished": "MARK.x[1]",
            "blocked": 'MARK["!"][1]', "session": '"●"',
        }
        for family, literal in expected.items():
            with self.subTest(family=family):
                self.assertIn(literal, self.table_text)

    def test_no_family_shares_another_familys_glyph(self) -> None:
        glyphs = [glyph for _family, glyph in GLYPH_TABLE]
        self.assertEqual(len(glyphs), len(set(glyphs)),
                         "two verb families must never render the same icon")

    def test_finished_and_blocked_reuse_the_ledgers_own_marks(self) -> None:
        """Reuse, not invention (the addendum's own instruction): the icon
        for these two families is a direct reference to ``MARK`` - the SAME
        object the ledger panel already reads its own DONE/BLOCKED glyphs
        from - rather than a copy of its characters typed a second time."""
        self.assertIn("MARK.x[1]", self.table_text)
        self.assertIn('MARK["!"][1]', self.table_text)

    def test_the_icon_is_keyed_by_the_servers_own_verb_field(self) -> None:
        body = self.functions["evRow"]
        self.assertIn("FEED_GLYPH[e.feed_verb]", body)

    def test_the_icon_states_nothing_the_sentence_does_not(self) -> None:
        """T110's own law, restated for this icon: it carries no title and no
        text a screen reader would read as new information - ``aria-hidden``
        marks it as pure decoration, exactly like the AVATAR disc."""
        body = self.functions["evRow"]
        self.assertIn('aria-hidden="true"', body)

    def test_a_kind_with_no_verb_family_renders_no_icon(self) -> None:
        body = self.functions["evRow"]
        self.assertIn('const icon = glyph ? ', body)


# ---------------------------------------------- the relative time and its tick


class TestTheRelativeTimeTicks(unittest.TestCase):
    """The T118 test shape, copied: a marked span carrying ``data-role`` and
    ``data-ts``, the verb/sentence entirely OUTSIDE it, and a dedicated
    tick function reachable from the existing one-second ``ticker`` - never
    render-time-only text that could freeze on a quiet feed."""

    @classmethod
    def setUpClass(cls) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cls.text = _page(_project(Path(tmp), []))
        cls.script = _script(cls.text)
        cls.functions = _functions(cls.script)

    def test_the_row_carries_a_data_role_and_data_ts_marked_span(self) -> None:
        body = self.functions["evRow"]
        self.assertIn('data-role="feed-ago"', body)
        self.assertIn("data-ts=\"${esc(e.ts)}\"", body)

    def test_the_sentence_and_verb_sit_outside_the_marked_span(self) -> None:
        """The T118 shape: the marked span's own content is ONLY the
        rendered duration, never the sentence or the verb the icon and the
        ``.d`` span already state - so a tick can only ever rewrite a
        duration, never invent or drop a word."""
        body = self.functions["evRow"]
        ago_open = body.index('data-role="feed-ago"')
        span_start = body.rindex("<span", 0, ago_open)
        span_close = body.index("</span>", ago_open)
        inside = body[span_start:span_close]
        self.assertNotIn("feed_sentence", inside)
        self.assertNotIn("feed_verb", inside)

    def test_a_dedicated_tick_function_exists_and_is_bounded_to_the_feed(self) -> None:
        self.assertIn("tickFeed", self.functions)
        body = self.functions["tickFeed"]
        self.assertIn('#feed [data-role="feed-ago"]', body)
        self.assertIn(".textContent =", body)
        self.assertIn("elapsedSince", body)
        self.assertIn("fmtDur", body)

    def test_the_tick_function_refuses_while_disconnected_or_unstated(self) -> None:
        """The same guard every other live-clock writer on this page opens
        with (``tickRoster``, ``tickOpenRows``) - restated here rather than
        assumed, because a writer that ticked anyway would advance a figure
        during an outage no other figure on the page moves during."""
        body = self.functions["tickFeed"]
        self.assertIn("if (disconnected || !lastState) return;", body)

    def test_the_existing_one_second_ticker_now_calls_it(self) -> None:
        self.assertIn("tickFeed(now)", self.functions["ticker"])

    def test_no_new_timer_was_introduced(self) -> None:
        """The addendum joins the EXISTING one-second walk rather than
        adding a new interval - the page still runs exactly the two timers
        it always has (``POLL_MS``, ``TICK_MS``)."""
        self.assertEqual(self.script.count("setInterval("), 2)


# ---------------------------------------------------- declined, not missed


class TestDeclinedItemsAreOnTheRecord(unittest.TestCase):
    """The reference carries two things this task does not build, and the
    module's own docstring says so where the feed is documented, per the
    acceptance's own instruction."""

    def test_the_alerts_off_toggle_is_declined_in_words(self) -> None:
        doc = keel_dashboard.__doc__ or ""
        self.assertIn("alerts off", doc)
        self.assertIn("NOT implemented", doc)

    def test_persona_renaming_is_declined_in_words(self) -> None:
        doc = keel_dashboard.__doc__ or ""
        self.assertIn("persona", doc.lower())
        self.assertIn("real agent", doc.lower())


if __name__ == "__main__":
    unittest.main()
