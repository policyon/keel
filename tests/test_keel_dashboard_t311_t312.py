"""T311 (round labels in keel's live view) and T312 (task preview
truncation in the agent detail drawer), both on
``scripts/keel_orchestration_dashboard.py``.

Scoping the event feed, agent cards and ledger panel to the selected round
was ALREADY implemented before this task (``inRound``/``evView``/``agView``
in ``tick()``, and the per-round ``spName`` ledger fetch) - this file does
not re-pin that; it pins only the gap that was actually closed: the round
LABELS the session switcher shows, and the SERVED bound on a delegated
task's description (T312).
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_orchestration_dashboard as adopted  # noqa: E402

SOURCE = (REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py").read_text(
    encoding="utf-8"
)


class TestRoundLabelStringsArePresent(unittest.TestCase):
    """T311: the label strings themselves, in the client script."""

    def test_the_live_label_names_the_total_round_count(self) -> None:
        self.assertIn('"Current · round "+Math.max(rounds.length,1)', SOURCE)

    def test_past_round_labels_carry_index_date_and_event_count(self) -> None:
        self.assertIn(
            "`Round ${idx+1} · ${roundDate(r.t)} · ${n} ev`", SOURCE
        )

    def test_the_session_short_id_stays_on_the_secondary_line(self) -> None:
        """Round labels must not push the session identity off the switcher
        - keel runs parallel sessions, unlike the single-session
        predecessor-harness viewer this concept was adopted from."""
        addition = SOURCE[SOURCE.index("KEEL ADDITION (T311)") :]
        self.assertIn("const sess8=(r.id||\"\").slice(0,8);", addition)
        self.assertIn("const sess8=(cur.id||\"\").slice(0,8);", addition)

    def test_round_index_is_taken_from_first_seen_order_not_the_split_lists(
        self,
    ) -> None:
        """The 0-based index must come from ``rounds`` (first-event order
        across the whole log), not from position within the active/ended
        arrays - else a round's number would change as it aged out."""
        addition = SOURCE[SOURCE.index("KEEL ADDITION (T311)") :]
        self.assertIn(
            "const idxById=new Map(rounds.map((r,i)=>[r.id,i]));", addition
        )


class TestRoundSwitcherLivesInTheRailAboveTheLedger(unittest.TestCase):
    """T313: the round/session switcher moved out of the top banner and into
    the right rail, directly above the plan-ledger panel - the same control,
    relocated, with an uppercase "ROUND" label matching the rail's other
    section headings."""

    def test_the_switcher_markup_sits_in_the_aside_ahead_of_the_ledger_heading(
        self,
    ) -> None:
        aside_start = SOURCE.index("<aside>")
        aside_body = SOURCE[aside_start:]
        round_pos = aside_body.index('id="roundrow"')
        ledger_pos = aside_body.index("Plan ledger")
        self.assertLess(
            round_pos,
            ledger_pos,
            "the ROUND control must appear ahead of the Plan ledger heading",
        )

    def test_the_round_label_is_present_and_uppercase_styled(self) -> None:
        self.assertIn('<span id="roundlabel">Round</span>', SOURCE)
        self.assertIn(
            "#roundlabel{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink3);flex:none}",
            SOURCE,
        )
        # T313 viewport fix: the popup must anchor to the rail's right edge and
        # the button must yield inside the flex row, or the control renders
        # past the viewport (owner-observed 2026-08-25).
        self.assertIn("#sesslist{position:absolute;top:calc(100% + 5px);right:0;left:auto", SOURCE)
        self.assertIn("#sessdd{position:relative;flex:1;min-width:0}", SOURCE)

    def test_the_tab_carries_the_project_name_and_a_favicon(self) -> None:
        # T315/T316: the static title is project-neutral, JS stamps the served
        # project's name onto it (live suffix kept), and the favicon is an
        # inline data URI (the page must stay asset-free).
        self.assertIn("<title>Orchestration — live</title>", SOURCE)
        self.assertIn(
            'const wanted=(project?project+" ":"")+"Orchestration — live";',
            SOURCE,
        )
        self.assertIn('rel="icon" href="data:image/svg+xml,', SOURCE)

    def test_the_switcher_no_longer_sits_in_the_top_banner(self) -> None:
        header_start = SOURCE.index("<header>")
        header_end = SOURCE.index("</header>")
        header_body = SOURCE[header_start:header_end]
        self.assertNotIn("sessdd", header_body)
        self.assertIn('id="projectsel"', header_body)


class TestDescriptionPreviewIsBoundedServerSide(unittest.TestCase):
    """T312: ``description`` is cut to a preview before it is served; the
    on-disk record is never touched, only the served copy."""

    def test_a_short_description_is_untouched(self) -> None:
        self.assertEqual(adopted._truncate_preview("short brief"), "short brief")

    def test_a_long_description_is_cut_to_the_preview_length_with_an_ellipsis(
        self,
    ) -> None:
        # T335 raised the ceiling to 2000; the fixture is written FROM the
        # constant so it can never quietly stop exceeding it again.
        long_text = "x" * (adopted.DESCRIPTION_PREVIEW_CHARS + 500)
        cut = adopted._truncate_preview(long_text)
        self.assertEqual(len(cut), adopted.DESCRIPTION_PREVIEW_CHARS + 1)  # +ellipsis
        self.assertTrue(cut.endswith("…"))
        self.assertEqual(cut[:-1], long_text[: adopted.DESCRIPTION_PREVIEW_CHARS])

    def test_the_ceiling_is_the_one_t335_raised_it_to(self) -> None:
        """KEEL ADDITION (T335): the drawer must be able to show a whole task
        brief, so the served bound is 2000 - the size of a real brief, still
        a BOUND: no unbounded string reaches the socket."""
        self.assertEqual(adopted.DESCRIPTION_PREVIEW_CHARS, 2000)

    def test_a_brief_under_the_raised_ceiling_survives_whole(self) -> None:
        """The other direction of T335: a full-length real brief - the kind
        that used to be cut at 300 - now reaches the page untouched."""
        brief = "Implement task orbits in the live board. " * 20  # ~800 chars
        self.assertLess(len(brief), adopted.DESCRIPTION_PREVIEW_CHARS)
        self.assertEqual(adopted._truncate_preview(brief), brief)
        self.assertFalse(adopted._truncate_preview(brief).endswith("…"))

    def test_non_string_description_passes_through_unchanged(self) -> None:
        self.assertIsNone(adopted._truncate_preview(None))

    def test_read_state_serves_a_bounded_description_never_the_full_prompt(
        self,
    ) -> None:
        import datetime
        import json

        def _iso(seconds_ago: float) -> str:
            moment = datetime.datetime.now(
                datetime.timezone.utc
            ) - datetime.timedelta(seconds=seconds_ago)
            return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

        long_desc = "brief " * (adopted.DESCRIPTION_PREVIEW_CHARS // 3)  # past the bound
        lines = [
            {
                "v": 1,
                "ts": _iso(10),
                "event": "handoff_start",
                "session": "s-1",
                "tool_use_id": "t1",
                "subagent_type": "keel:executor",
                "description": long_desc,
            },
        ]
        import tempfile

        tmp = tempfile.TemporaryDirectory()
        try:
            root = Path(tmp.name)
            (root / ".keel" / "audit").mkdir(parents=True)
            (root / ".keel" / "plans").mkdir(parents=True)
            (root / ".keel" / "audit" / "keel-audit.jsonl").write_text(
                "".join(json.dumps(line) + "\n" for line in lines),
                encoding="utf-8",
            )
            adopted.ROOT = root
            state = adopted.read_state()
        finally:
            tmp.cleanup()
        served = state["events"][0]["description"]
        self.assertLessEqual(len(served), adopted.DESCRIPTION_PREVIEW_CHARS + 1)
        self.assertNotEqual(served, long_desc)
        self.assertTrue(served.endswith("…"))


class TestDrawerPreviewIsBoundedClientSide(unittest.TestCase):
    """T312: the detail drawer's own tighter preview bound, on top of the
    server-side cut - so the ~200-char / few-lines behavior from the owner's
    reference screenshot holds even where the server's wider 300-char bound
    would still be too long for a header line."""

    def test_the_client_preview_helper_exists_and_is_used_in_the_drawer(
        self,
    ) -> None:
        self.assertIn("const PREVIEW_CHARS=200;", SOURCE)
        self.assertIn(
            'dr.querySelector(".who").textContent=p.name+" — "+preview(e.description||"");',
            SOURCE,
        )

    def test_prompt_head_is_not_double_bounded_client_side(self) -> None:
        """``prompt_head`` is already capped at capture time
        (``PROMPT_HEAD_CHARS`` in ``hooks/keel_capture.py``); the drawer must
        not wrap it in the client ``preview()`` helper too."""
        self.assertIn("e.prompt_head?", SOURCE)
        self.assertNotIn("preview(e.prompt_head", SOURCE)


class TestPromptHeadIsAlreadyBoundedAtCapture(unittest.TestCase):
    """The other half of T312's premise, pinned where it actually lives:
    ``prompt_head`` never needed a server-side cut in this file because
    ``hooks/keel_capture.py`` already bounds it before it ever reaches the
    log. If this constant ever grows past this file's own preview bound,
    that is a decision to revisit here, not a silent drift."""

    def test_prompt_head_chars_is_within_the_drawers_preview_bound(self) -> None:
        capture_src = (REPO_ROOT / "hooks" / "keel_capture.py").read_text(
            encoding="utf-8"
        )
        import re

        m = re.search(r"PROMPT_HEAD_CHARS\s*=\s*(\d+)", capture_src)
        self.assertIsNotNone(m, "PROMPT_HEAD_CHARS not found in keel_capture.py")
        self.assertLessEqual(int(m.group(1)), 200)


if __name__ == "__main__":
    unittest.main()
