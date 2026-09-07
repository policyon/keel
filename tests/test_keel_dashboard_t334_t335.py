#!/usr/bin/env python3
"""T334 (header typography) and T335 (the agent drawer, and the orchestrator's
own model) on the live orchestration view.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` - as source text for the
          CSS/markup pins, and by IMPORT for the served data layer's own
          bound. The two client functions T335 adds (``runModel`` and
          ``runDuration``) are pure and DOM-free, so they are extracted
          verbatim and run under ``node`` against synthetic runs shaped
          exactly as ``pairEvents``/``computeStates`` shape them (BL1: no
          case here reads this repository's audit log, and every duration
          case is closed - never the wall clock).
Emits   : unittest results only.
Writes  : nothing outside a temporary script handed to ``node``.
Argv    : none.

What this pins
--------------
T334 - THE HEADER'S TYPE, and the rule that it costs nothing to fetch: the
       restyle exists, it speaks the cards' own hierarchy (a name weight over
       a small-caps label), and the page declares NO font of its own - no
       @font-face, no @import, no remote stylesheet, no URL that is not the
       inline data: favicon or an XML namespace. A loopback board must never
       reach the network to draw itself.
T335 - THE DRAWER TELLS THE TRUTH ABOUT A RUN:
       * model comes from the whole run (the close half's resolved model
         first), and where no half recorded one the drawer says "unrecorded"
         - never the generic "agent" the persona map falls through to;
       * the duration says WHAT IT MEASURED (launch to report-back, launch to
         background acknowledgment, resume round-trip, since launch), because
         the same number means four different things;
       * a bench pill opens the run the board is showing (the working one),
         not whichever line happened to be last;
       * the whole task brief is readable: the header keeps its one-line
         preview, the body prints the full served string, and the served
         bound itself moved to 2000 (pinned in both directions next door, in
         ``test_keel_dashboard_t311_t312.py``).
       * THE ORCHESTRATOR: the Captain's card wears the session's own
         recorded model, or the honest "model unrecorded". Effort is NOT
         shown for a session and that is deliberate - see the test below,
         which pins the absence as a decision rather than an oversight.

Failure policy
--------------
FAIL-CLOSED: if ``node`` cannot be found the file fails rather than skipping.

Constraints
-----------
Python 3.10+ standard library plus a ``node`` binary on PATH. Subprocess
invoked with an argument list, never a shell string (R5).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from keel_node import NODE, SKIP_REASON, announce_once

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_orchestration_dashboard as adopted  # noqa: E402

PAGE = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
SOURCE = PAGE.read_text(encoding="utf-8")
announce_once()


def _extract_block(pattern: str, label: str) -> str:
    m = re.search(pattern, SOURCE, re.S)
    if not m:
        raise AssertionError(f"could not extract {label!r} from the served page")
    return m.group(0)


def _extract_line(prefix: str, label: str) -> str:
    for line in SOURCE.splitlines():
        if line.strip().startswith(prefix):
            return line.strip()
    raise AssertionError(f"could not extract {label!r} from the served page")


_TS = _extract_line("const ts=", "ts")
_FMTDUR = _extract_line("const fmtDur=", "fmtDur")
#: The run-facts block, verbatim as one contiguous run: ``ownField`` and
#: ``inheritedField`` (the T337-extension route join), ``runRoute``,
#: ``routeLabel``, ``runModel`` and ``runDuration``.
_RUN_BLOCK = _extract_block(
    r"function ownField\(a,key\)\{.*?\nfunction runDuration\(a\)\{.*?\n\}\n",
    "the T335/T337 run-facts block",
)
PRELUDE = "\n".join([_TS, _FMTDUR, _RUN_BLOCK])


def run_node(call_js: str) -> Any:
    if NODE is None:
        raise AssertionError("node was not found on PATH - failing closed")
    script = PRELUDE + "\nprocess.stdout.write(JSON.stringify(" + call_js + "));\n"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run([NODE, path], capture_output=True, timeout=30, check=False)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError("node harness failed: " + result.stderr.decode("utf-8", "replace"))
    return json.loads(result.stdout.decode("utf-8"))


#: T475/BL25: ``sessionModel`` itself, extracted the same way as the run-facts
#: block above. It closes over ``lastState`` (a module-level global on the
#: served page, not an argument), so the harness below assigns ``lastState``
#: before the extracted body ever runs.
_SESSION_MODEL_BLOCK = _extract_block(
    r"function sessionModel\(sessId\)\{.*?\n\}\n",
    "the T475 sessionModel scan",
)


def run_session_model(sess_id: str, events: list[dict]) -> Any:
    if NODE is None:
        raise AssertionError("node was not found on PATH - failing closed")
    script = (
        "let lastState=" + json.dumps({"events": events}) + ";\n"
        + _SESSION_MODEL_BLOCK
        + "\nprocess.stdout.write(JSON.stringify(sessionModel("
        + json.dumps(sess_id) + ")));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = fh.name
    try:
        result = subprocess.run([NODE, path], capture_output=True, timeout=30, check=False)
    finally:
        Path(path).unlink(missing_ok=True)
    if result.returncode != 0:
        raise AssertionError("node harness failed: " + result.stderr.decode("utf-8", "replace"))
    return json.loads(result.stdout.decode("utf-8"))


T0 = "2026-08-26T10:00:00Z"
T1 = "2026-08-26T10:00:03Z"
T2 = "2026-08-26T10:00:31Z"


def run(start: dict | None = None, end: dict | None = None, stop: dict | None = None,
        background: bool = False, working: bool = False) -> dict[str, Any]:
    """A paired run exactly as the page's own pipeline shapes it."""
    return {"start": start, "end": end, "stop": stop,
            "background": background, "working": working}


def half(ts_iso: str, **fields: Any) -> dict[str, Any]:
    ev = {"ts": ts_iso, "session_id": "s1", "subagent_type": "keel:executor-deep"}
    ev.update(fields)
    return ev


# ---------------------------------------------------------------- T335 model
@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheDrawerNamesTheModelTheRunActuallyRanAt(unittest.TestCase):
    """The owner's screenshot: "model: agent" on a run whose own card said
    OPUS · HIGH. "agent" is ``modelOf``'s persona-map fallback, not anything
    the record said."""

    def test_the_close_halfs_resolved_model_wins(self) -> None:
        """MEASURED shape: the open half records the requested model, the
        close half the one the harness resolved - the richer answer."""
        a = run(start=half(T0, model="opus · high"), end=half(T2, model="claude-opus-5 · high"))
        self.assertEqual(run_node(f"runModel({json.dumps(a)})"), "claude-opus-5 · high")

    def test_a_model_on_the_open_half_alone_is_still_found(self) -> None:
        a = run(start=half(T0, model="sonnet · default"), end=half(T1))
        self.assertEqual(run_node(f"runModel({json.dumps(a)})"), "sonnet · default")

    def test_a_run_with_no_recorded_model_answers_null_not_agent(self) -> None:
        """The resume shape: neither half carries a model (a resume names an
        id, not a type or a model - the capture contract says so)."""
        a = run(start=half(T0, handoff_kind="resume"), end=half(T1, handoff_kind="resume"))
        self.assertIsNone(run_node(f"runModel({json.dumps(a)})"))

    def test_an_empty_string_model_counts_as_unrecorded(self) -> None:
        a = run(start=half(T0, model="   "), end=half(T1, model=""))
        self.assertIsNone(run_node(f"runModel({json.dumps(a)})"))

    def test_the_drawer_prints_unrecorded_and_never_the_word_agent(self) -> None:
        meta = re.search(r'dr\.querySelector\("\.dmeta"\)\.innerHTML=\n?\s*`model:.*?;',
                         SOURCE, re.S)
        self.assertIsNotNone(meta, "could not find the drawer's meta line")
        rule = meta.group(0)
        self.assertIn("unrecorded", rule)
        self.assertIn("runRoute(a,lastAgents)", SOURCE)
        # the persona-map fallback no longer reaches the drawer at all
        self.assertNotIn("model: <b>${esc(modelOf(e))}</b>", SOURCE)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestAResumeRunInheritsItsAgentsRoute(unittest.TestCase):
    """T337 extension (owner review of the live drawer, 2026-08-26): a resume
    hand-off records neither model nor effort - the capture contract says the
    send "knows none of them" - so the drawer read "unrecorded" for an agent
    whose own dispatch had recorded both. The join happens on the READ side,
    from the newest earlier run of the SAME AGENT, and nowhere else."""

    #: A dispatch that recorded the route, and the resume of that same agent
    #: (same ``agent_id``, per T124) which recorded nothing.
    DISPATCH = run(start=half(T0, model="opus · high", effort="high",
                              description="Implement task orbits"),
                   end=half(T1, model="claude-opus-5 · high", effort="high",
                            agent_id="a1chief"))
    RESUME = run(start=half(T2, handoff_kind="resume", agent_id="a1chief"),
                 end=half(T2, handoff_kind="resume", agent_id="a1chief"))

    def test_the_resume_run_shows_the_route_its_dispatch_recorded(self) -> None:
        agents = [self.DISPATCH, self.RESUME]
        got = run_node(f"runModel({json.dumps(self.RESUME)},{json.dumps(agents)})")
        self.assertEqual(got, "claude-opus-5 · high")

    def test_the_borrowing_is_flagged_so_the_drawer_can_say_so(self) -> None:
        agents = [self.DISPATCH, self.RESUME]
        route = run_node(f"runRoute({json.dumps(self.RESUME)},{json.dumps(agents)})")
        self.assertTrue(route["inherited"])
        own = run_node(f"runRoute({json.dumps(self.DISPATCH)},{json.dumps(agents)})")
        self.assertFalse(own["inherited"], "a run carrying its own route borrows nothing")

    def test_the_drawer_names_the_provenance(self) -> None:
        self.assertIn("· from launch", SOURCE)
        self.assertIn("(m&&route.inherited)", SOURCE)

    def test_an_agent_with_no_model_anywhere_still_reads_unrecorded(self) -> None:
        """The honest floor: inheritance is a join over the record, not a
        default. No run of this agent carried a model -> null."""
        d = run(start=half(T0, description="something"), end=half(T1, agent_id="a2gunner"))
        r = run(start=half(T2, handoff_kind="resume", agent_id="a2gunner"),
                end=half(T2, handoff_kind="resume", agent_id="a2gunner"))
        self.assertIsNone(run_node(f"runModel({json.dumps(r)},{json.dumps([d, r])})"))

    def test_another_agents_route_is_never_borrowed(self) -> None:
        other = run(start=half(T0, model="haiku · low", effort="low",
                               subagent_type="keel:researcher"),
                    end=half(T1, model="claude-haiku-5 · low", effort="low",
                             agent_id="a9lookout", subagent_type="keel:researcher"))
        self.assertIsNone(
            run_node(f"runModel({json.dumps(self.RESUME)},{json.dumps([other, self.RESUME])})")
        )

    def test_a_later_run_never_lends_to_an_earlier_one(self) -> None:
        """Only a dispatch that already happened can lend: a route recorded
        after this run started says nothing about how this run was launched."""
        later = run(start=half(T2, model="sonnet · default", effort="default",
                               agent_id="a1chief"),
                    end=half(T2, model="claude-sonnet-5 · default", agent_id="a1chief"))
        early = run(start=half(T0, handoff_kind="resume", agent_id="a1chief"),
                    end=half(T1, handoff_kind="resume", agent_id="a1chief"))
        self.assertIsNone(
            run_node(f"runModel({json.dumps(early)},{json.dumps([later, early])})")
        )

    def test_session_and_type_carry_the_join_when_no_agent_id_exists(self) -> None:
        """Older records carry no ``agent_id``; the fallback key is the very
        one the chip rail and ``actsFor`` already attribute by."""
        d = run(start=half(T0, model="opus · high", effort="high"),
                end=half(T1, model="claude-opus-5 · high", effort="high"))
        r = run(start=half(T2, handoff_kind="resume"), end=half(T2, handoff_kind="resume"))
        self.assertEqual(
            run_node(f"runModel({json.dumps(r)},{json.dumps([d, r])})"),
            "claude-opus-5 · high",
        )

    def test_effort_is_inherited_independently_of_the_model(self) -> None:
        """They travel together on a dispatch but are read separately: a run
        that recorded only a model keeps it and borrows only the effort."""
        d = run(start=half(T0, effort="high"), end=half(T1, effort="high"))
        r = run(start=half(T2, model="claude-opus-5"), end=half(T2))
        route = run_node(f"runRoute({json.dumps(r)},{json.dumps([d, r])})")
        self.assertEqual(route["model"], "claude-opus-5")
        self.assertEqual(route["effort"], "high")
        self.assertEqual(run_node(f"routeLabel({json.dumps(route)})"), "claude-opus-5 · high")

    def test_a_composed_model_never_doubles_its_effort(self) -> None:
        """The served copy already composes "model · effort" into one string
        (T123); appending it again would read "opus · high · high"."""
        route = {"model": "claude-opus-5 · high", "effort": "high", "inherited": False}
        self.assertEqual(run_node(f"routeLabel({json.dumps(route)})"), "claude-opus-5 · high")

    def test_the_card_pill_follows_the_same_route(self) -> None:
        self.assertIn('const mtag=el.querySelector(".modeltag");', SOURCE)
        self.assertIn('if(mtag){const lbl=runModel(a,lastAgents);mtag.textContent=lbl||"";}',
                      SOURCE)
        # T132's rule survives in outcome: an unknown route draws no pill
        self.assertIn(".modeltag:empty{display:none}", SOURCE)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheDurationSaysWhatItMeasured(unittest.TestCase):
    """Four spans wear the same number of seconds; the drawer now names which
    one it printed."""

    def _dur(self, a: dict) -> list:
        return run_node(f"runDuration({json.dumps(a)})")

    def test_a_finished_foreground_run_measures_launch_to_report_back(self) -> None:
        d = self._dur(run(start=half(T0), end=half(T2)))
        self.assertEqual(d[1], "launch to report-back")

    def test_a_background_launch_says_it_measured_the_acknowledgment(self) -> None:
        """The owner's 3s: end-minus-start on a background launch is the time
        the harness took to ACCEPT the delegation, not the work."""
        d = self._dur(run(start=half(T0), end=half(T1), background=True))
        self.assertEqual(d[0], "3s")
        self.assertEqual(d[1], "launch to background acknowledgment")

    def test_a_background_run_with_a_stop_measures_the_whole_run(self) -> None:
        d = self._dur(run(start=half(T0), end=half(T1), stop=half(T2), background=True))
        self.assertEqual(d[0], "31s")
        self.assertEqual(d[1], "launch to report-back")

    def test_a_resume_pair_says_it_is_a_resume(self) -> None:
        d = self._dur(run(start=half(T0, handoff_kind="resume"),
                          end=half(T1, handoff_kind="resume")))
        self.assertEqual(d[1], "resume message round-trip")

    def test_a_run_with_no_launch_half_says_so_rather_than_guessing(self) -> None:
        d = self._dur(run(end=half(T2)))
        self.assertEqual(d[0], "?")
        self.assertIn("no launch", d[1])

    def test_the_drawer_prints_the_label_beside_the_number(self) -> None:
        self.assertIn(
            "const route=runRoute(a,lastAgents),m=routeLabel(route),dur=runDuration(a);",
            SOURCE,
        )
        self.assertIn("duration: <b>${esc(dur[0])}</b>", SOURCE)
        self.assertIn("(${esc(dur[1])})", SOURCE)


class TestTheBenchPillOpensTheRunTheBoardIsShowing(unittest.TestCase):
    """The other half of the owner's finding: the drawer described a
    different run from the card, because the bench pill took whichever line
    of that persona came last - for a resumed agent, the resume pair."""

    def test_the_working_run_is_preferred_then_a_real_launch(self) -> None:
        self.assertIn(
            "const a=back.find(x=>x.working)||back.find(x=>x.start&&x.start.description)||back[0];",
            SOURCE,
        )

    def test_the_blind_newest_of_this_type_pick_is_gone(self) -> None:
        self.assertNotIn(
            "const a=[...lastAgents].reverse().find(x=>(((x.start||x.end||{}).subagent_type)"
            '||"agent")===type);',
            SOURCE,
        )


class TestTheWholeBriefIsReadableInTheDrawer(unittest.TestCase):
    """T335: the task text was cut mid-sentence with nowhere to read the
    rest. The header line keeps its preview (a title stays a title); the body
    prints the whole served string, wrapped, in a block that scrolls."""

    def test_the_drawer_has_a_task_block_fed_the_unclamped_description(self) -> None:
        self.assertIn('<div class="dtask" hidden></div>', SOURCE)
        self.assertIn('const dtask=dr.querySelector(".dtask"),desc=(e.description||"").toString();',
                      SOURCE)
        self.assertIn('dtask.innerHTML=desc?`<span class="dlabel">task</span>${esc(desc)}`:"";',
                      SOURCE)

    def test_the_task_block_wraps_and_scrolls_rather_than_clamping(self) -> None:
        rule = re.search(r"#drawer \.dtask\{[^}]*\}", SOURCE, re.S)
        self.assertIsNotNone(rule, "could not find the .dtask rule")
        css = rule.group(0)
        self.assertIn("white-space:pre-wrap", css)
        self.assertIn("overflow-y:auto", css)
        self.assertNotIn("-webkit-line-clamp", css)
        self.assertNotIn("text-overflow:ellipsis", css)

    def test_the_description_is_escaped_before_it_is_printed(self) -> None:
        self.assertIn("${esc(desc)}", SOURCE)

    def test_the_header_line_keeps_its_one_line_preview(self) -> None:
        """T312's client bound is not repealed by T335 - it just stopped
        being the only copy of the string."""
        self.assertIn("const PREVIEW_CHARS=200;", SOURCE)
        self.assertIn(
            'dr.querySelector(".who").textContent=p.name+" — "+preview(e.description||"");',
            SOURCE,
        )

    def test_the_served_bound_moved_but_still_bounds(self) -> None:
        self.assertEqual(adopted.DESCRIPTION_PREVIEW_CHARS, 2000)
        self.assertEqual(len(adopted._truncate_preview("y" * 5000)), 2001)


class TestTheOrchestratorWearsItsOwnModel(unittest.TestCase):
    """T335, owner extension: the Captain's card carries the session's model
    the way an agent card carries its own - from the record, or "unrecorded".
    """

    def test_the_centre_card_has_a_model_pill_fed_from_the_session_record(self) -> None:
        self.assertIn('<span class="modeltag" id="mmodel"></span>', SOURCE)
        self.assertIn("function sessionModel(sessId){", SOURCE)
        self.assertIn('if(e.session_id!==sessId)continue;', SOURCE)
        self.assertIn("const om=sessionModel(latestSession);", SOURCE)

    def test_an_absent_model_renders_the_unrecorded_word_not_a_guess(self) -> None:
        self.assertIn('mm.textContent=om||"model unrecorded";', SOURCE)
        self.assertIn('mm.classList.toggle("unknown",!om);', SOURCE)
        self.assertIn(".modeltag.unknown{", SOURCE)

    def test_the_orchestrator_model_is_read_and_never_derived(self) -> None:
        """No persona map, no default, no inference from the agent models in
        the same session - the session's own newest carrying event or
        nothing (T475/BL25: no longer gated to ``session_start`` alone, since
        that event cannot know the model on a fresh session)."""
        block = re.search(r"function sessionModel\(sessId\)\{.*?\n\}", SOURCE, re.S).group(0)
        self.assertIn("e.session_id!==sessId", block)
        self.assertNotIn("PERSONAS", block)
        self.assertNotIn("modelOf", block)
        self.assertNotIn("||\"", block.replace('||"model unrecorded"', ""))

    def test_effort_is_absent_for_a_session_deliberately(self) -> None:
        """MEASURED 2026-08-26 on this project's log: 260 session_start lines,
        11 with a model, ZERO with an effort - and the capture contract says
        why (no payload names an effort for a session; effort is only ever
        read from an agent definition's frontmatter). The comment carrying
        that reason must stay with the code, or the next reader will "fix"
        the missing half by inventing a default."""
        block = SOURCE[SOURCE.index("THE ORCHESTRATOR'S"):]
        block = block[: block.index("function sessionModel")]
        self.assertIn("EFFORT", block)
        self.assertIn("no such file", block)

    def test_the_session_start_field_this_reads_is_the_one_keel_writes(self) -> None:
        """The field is not invented here: the session hook's own contract
        says it records ``model`` on every session_start line."""
        hook = (REPO_ROOT / "hooks" / "keel_session.py").read_text(encoding="utf-8")
        self.assertIn("``model`` is now recorded on EVERY ``session_start`` line", hook)


@unittest.skipIf(NODE is None, SKIP_REASON)
class TestTheOrchestratorReadsTheNewestModelCarryingEvent(unittest.TestCase):
    """T475/BL25 dashboard half: SessionStart runs before the transcript has
    an assistant line, so a fresh session's own start line carries a null
    model by construction (only a resumed session's re-registration can
    answer there). ``sessionModel`` must not stop at ``session_start`` - it
    scans the session's own events, newest first, for the first one that
    carries a non-null, non-blank ``model``, of WHATEVER KIND, so a later
    event the hooks half of T475 teaches to carry one needs no dashboard
    edit to be picked up."""

    def test_a_later_event_of_any_kind_supplies_what_session_start_could_not(self) -> None:
        """The fresh-session shape this exists for: session_start recorded
        null (the harness had nothing to say yet), and a later event - here
        a plausible stand-in for the hooks half's own addition - carries the
        model once the transcript makes it knowable."""
        events = [
            {"ts": T0, "event": "session_start", "session_id": "s1", "model": None},
            {"ts": T1, "event": "stop_block", "session_id": "s1", "model": "claude-x"},
        ]
        self.assertEqual(run_session_model("s1", events), "claude-x")

    def test_no_event_carrying_a_model_still_reads_unrecorded_never_a_guess(self) -> None:
        events = [
            {"ts": T0, "event": "session_start", "session_id": "s1", "model": None},
            {"ts": T1, "event": "activity", "session_id": "s1"},
        ]
        self.assertIsNone(run_session_model("s1", events))

    def test_another_sessions_model_is_never_borrowed(self) -> None:
        """Two sessions in the same log must not leak into each other - the
        second session's model answers for the second session only."""
        events = [
            {"ts": T0, "event": "session_start", "session_id": "s1", "model": None},
            {"ts": T1, "event": "stop_block", "session_id": "s2", "model": "claude-other"},
        ]
        self.assertIsNone(run_session_model("s1", events))
        self.assertEqual(run_session_model("s2", events), "claude-other")

    def test_the_newest_carrying_event_wins_over_an_older_one(self) -> None:
        """Two events of the same session both carry a model (a resume can
        re-register with a different one); the newest is the truth, not the
        first one found."""
        events = [
            {"ts": T0, "event": "session_start", "session_id": "s1", "model": "claude-old"},
            {"ts": T1, "event": "stop_block", "session_id": "s1", "model": "claude-new"},
        ]
        self.assertEqual(run_session_model("s1", events), "claude-new")

    def test_the_scan_continues_past_newer_events_that_carry_no_model(self) -> None:
        """T475 review finding: the scan must keep walking BACKWARD past a
        same-session event whose ``model`` is null, absent, or blank, until
        it finds one that actually carries a value. A mutation that returns
        at the first same-session event regardless of that check - the
        newest here holds a blank string, the next a missing key, the next
        an explicit null - would answer null/blank and fail this test, while
        passing all four above (none of which stacks a carrying event under
        newer non-carrying ones of the same session)."""
        events = [
            {"ts": T0, "event": "session_start", "session_id": "s1", "model": "claude-x"},
            {"ts": T1, "event": "stop_block", "session_id": "s1", "model": None},
            {"ts": T1, "event": "activity", "session_id": "s1"},
            {"ts": T2, "event": "spike", "session_id": "s1", "model": "  "},
        ]
        self.assertEqual(run_session_model("s1", events), "claude-x")


class TestTheHeaderTypeIsRestyledAndCostsNoNetwork(unittest.TestCase):
    """T334: style only, and no font may be fetched."""

    def test_the_restyle_exists_and_is_fenced_as_an_addition(self) -> None:
        self.assertIn("KEEL ADDITION (T334", SOURCE)
        for rule in (
            "header h1{font-size:17px;font-weight:700;letter-spacing:-.015em;line-height:1.2}",
            ".badge,#live,#bell{font-size:11px;font-weight:600;letter-spacing:.015em}",
            ".stat b{font-size:20px;font-weight:700;letter-spacing:-.02em;line-height:1.1}",
            ".stat span{font-size:9.5px;font-weight:600;letter-spacing:.11em}",
        ):
            self.assertIn(rule, SOURCE)

    def test_the_header_speaks_the_cards_own_hierarchy(self) -> None:
        """The card pairs a 700-weight name with a small, wide-tracked label;
        the header's title/stat pair must do the same, or the restyle is just
        different rather than consistent. The EFFECTIVE declaration is the
        LAST one of equal specificity - T334 restyles by adding rules after
        the vendored ones, never by editing them - so each assertion reads
        the last rule the cascade would apply."""
        self.assertIn(".node .who{font-weight:700;", SOURCE)  # the card's name voice
        title = re.findall(r"header h1\{([^}]*)\}", SOURCE)[-1]
        self.assertIn("font-weight:700", title)
        self.assertIn("letter-spacing:-", title)          # a heading tightens
        number = re.findall(r"\.stat b\{([^}]*)\}", SOURCE)[-1]
        self.assertIn("font-weight:700", number)
        label = re.findall(r"\.stat span\{([^}]*)\}", SOURCE)[-1]
        self.assertIn("letter-spacing:.11em", label)       # ... a label opens up
        vendored_label = re.findall(r"\.stat span\{([^}]*)\}", SOURCE)[0]
        self.assertIn("text-transform:uppercase", vendored_label)

    @staticmethod
    def _page_without_comments() -> str:
        """The served page with its own commentary removed - a comment that
        NAMES ``@font-face`` (this file's T334 block explains why there is
        none) must not be mistaken for one."""
        page = SOURCE[SOURCE.index("HTML = r"):]
        page = re.sub(r"/\*.*?\*/", "", page, flags=re.S)      # CSS comments
        page = re.sub(r"<!--.*?-->", "", page, flags=re.S)     # HTML comments
        return re.sub(r"(?m)^\s*//.*$", "", page)              # JS line comments

    def test_no_font_is_ever_fetched(self) -> None:
        page = self._page_without_comments()
        for forbidden in ("@font-face", "@import", "fonts.googleapis", "fonts.gstatic",
                          'rel="stylesheet"', "preconnect"):
            self.assertNotIn(forbidden, page, f"{forbidden!r} would make the board fetch")

    def test_the_only_urls_in_the_page_are_local_or_namespaces(self) -> None:
        """Every http(s) string in the served page must be an XML namespace or
        the loopback address - a board that draws itself from the network is
        not a loopback board."""
        page = SOURCE[SOURCE.index("HTML = r"):]
        for url in re.findall(r"https?://[^\s\"'`)]+", page):
            with self.subTest(url=url):
                self.assertTrue(
                    url.startswith("http://www.w3.org/")
                    or url.startswith("http://127.0.0.1"),
                    f"unexpected outbound URL in the page: {url}",
                )

    def test_the_font_family_is_still_the_pages_own_system_stack(self) -> None:
        self.assertIn('font:400 13.5px/1.45 "Segoe UI",system-ui,sans-serif', SOURCE)
        # the T334 block restates sizes/weights only - never a family
        block = SOURCE[SOURCE.index("KEEL ADDITION (T334"):]
        block = block[: block.index("main{flex:1")]
        self.assertNotIn("font-family", block)


class TestNodeAbsenceIsAnnounced(unittest.TestCase):
    """Node's absence is audible, then skipped — never silent (BL17, ruled
    2026-09-01). The run-facts checks above skip so a clone without node
    reaches green; ``keel_node.announce_once`` is what keeps that visible."""

    def test_node_is_on_path(self) -> None:
        if NODE is None:
            self.skipTest(SKIP_REASON)
        self.assertTrue(
            Path(NODE).exists(),
            f"PATH named a node that is not there: {NODE}",
        )


if __name__ == "__main__":
    unittest.main()
