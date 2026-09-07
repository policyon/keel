"""T140: the zero-token demo mode never touches a real project's ``.keel/``,
writes keel's own real audit/plan schema with synthetic values only, and
runs a full cycle instantly under ``--fast``.

KEEL ADDITION (T341): and the scripted eight-beat TOUR is a timeline of
DATA, in order, complete, made of event classes keel really emits — through
the same refusal path, which still refuses.
"""
from __future__ import annotations

import io
import json
import re
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_demo  # noqa: E402

REAL_AGENT_TYPES = {
    "keel:executor",
    "keel:executor-deep",
    "keel:researcher",
    "keel:reviewer-correctness",
    "keel:reviewer-security",
    "keel:reviewer-tests",
}

AGENT_ID_RE = re.compile(r"^[0-9a-f]{17}$")


def _read_events(log_path: Path) -> list[dict]:
    text = log_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


class TestRealProjectNeverTouched(unittest.TestCase):
    """Accept 1: a demo run, even against a tmp root standing in for a real
    project, leaves that real project's own log byte-identical. The "real"
    tree here is one this test builds itself — never the actual repository
    (the tracked-ledger scan trap: never premise a test on live repo content)."""

    def test_a_sibling_real_project_is_refused_not_written(self) -> None:
        """The fake "real" tree is WIRED THROUGH ``--dir`` as the actual
        target under test — not merely built and ignored — so this pins the
        real refusal path (``_refusal_reason``), not a vacuous truth."""
        with tempfile.TemporaryDirectory() as real_root:
            real_root = Path(real_root)
            (real_root / ".keel" / "audit").mkdir(parents=True)
            (real_root / ".keel" / "plans").mkdir(parents=True)
            real_log = real_root / ".keel" / "audit" / "keel-audit.jsonl"
            real_log.write_text(
                '{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", '
                '"session": "real-not-touched", "source": "startup", "model": "sonnet"}\n',
                encoding="utf-8",
            )
            before = real_log.read_bytes()

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--dir", str(real_root), "--fast", "--cycles", "1"])

            self.assertNotEqual(rc, 0)
            self.assertEqual(real_log.read_bytes(), before)
            # Only the log file must exist under the fake real tree — the
            # demo must have created nothing else there, including no plan
            # ledger and no policy file.
            self.assertEqual(
                sorted(p.name for p in (real_root / ".keel" / "audit").iterdir()),
                ["keel-audit.jsonl"],
            )
            self.assertEqual(list((real_root / ".keel" / "plans").iterdir()), [])
            self.assertFalse((real_root / ".keel" / "keel-policy.md").exists())

    def test_own_repository_root_is_refused(self) -> None:
        """Refuses outright on identity with this script's own repo root —
        proven by pointing REPO_ROOT itself at a harmless tmp dir, never at
        the actual Keel checkout, so a guard bug here cannot touch it."""
        with tempfile.TemporaryDirectory() as fake_repo_root:
            fake_repo_root = Path(fake_repo_root).resolve()
            original = keel_demo.REPO_ROOT
            keel_demo.REPO_ROOT = fake_repo_root
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = keel_demo.main(
                        ["--dir", str(fake_repo_root), "--fast", "--cycles", "1"]
                    )
            finally:
                keel_demo.REPO_ROOT = original
            self.assertNotEqual(rc, 0)
            self.assertFalse((fake_repo_root / ".keel").exists())

    def test_a_fresh_target_is_accepted_and_written(self) -> None:
        """The complementary positive case: an empty target is accepted."""
        with tempfile.TemporaryDirectory() as target:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--dir", target, "--fast", "--cycles", "1"])
            self.assertEqual(rc, 0)
            log = Path(target, ".keel", "audit", "keel-audit.jsonl")
            self.assertTrue(log.is_file())
            self.assertIn("demo-", log.read_text(encoding="utf-8"))

    def test_a_target_whose_sessions_are_all_demo_prefixed_is_accepted(self) -> None:
        """A prior run of this same script (every session ``demo-`` prefixed)
        is a project this demo owns, so a rerun is accepted, not refused."""
        with tempfile.TemporaryDirectory() as target:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc1 = keel_demo.main(["--dir", target, "--fast", "--cycles", "1"])
                rc2 = keel_demo.main(["--dir", target, "--fast", "--cycles", "1"])
            self.assertEqual(rc1, 0)
            self.assertEqual(rc2, 0)
            events = _read_events(Path(target, ".keel", "audit", "keel-audit.jsonl"))
            sessions = {e["session"] for e in events if "session" in e}
            self.assertEqual({"demo-0000"}, sessions)


class TestOneFastCycle(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.rc = keel_demo.main(["--dir", str(self.root), "--fast", "--cycles", "1"])
        self.log_path = self.root / ".keel" / "audit" / "keel-audit.jsonl"
        self.plan_path = self.root / ".keel" / "plans" / "keel-plan-demo0000.md"
        self.events = _read_events(self.log_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exit_zero(self) -> None:
        self.assertEqual(self.rc, 0)

    def test_session_ids_all_carry_demo_prefix(self) -> None:
        sessions = {e["session"] for e in self.events if "session" in e}
        self.assertTrue(sessions)
        for sid in sessions:
            self.assertTrue(sid.startswith("demo-"), sid)

    def test_full_event_shape_present(self) -> None:
        kinds = [e["event"] for e in self.events]
        for required in (
            "session_start", "activity", "handoff_start", "handoff_end",
            "review", "subagent_stop", "session_end",
        ):
            self.assertIn(required, kinds)
        self.assertGreaterEqual(len(self.events), 10)

    def test_launch_and_resume_kinds_both_appear(self) -> None:
        kinds = {e.get("handoff_kind") for e in self.events if e["event"] == "handoff_start"}
        self.assertEqual(kinds, {"launch", "resume"})

    def test_resume_carries_agent_id_on_both_halves_and_no_subagent_type(self) -> None:
        resumes = [e for e in self.events if e.get("handoff_kind") == "resume"]
        starts = [e for e in resumes if e["event"] == "handoff_start"]
        ends = [e for e in self.events if e["event"] == "handoff_end" and e.get("tool_use_id") == starts[0]["tool_use_id"]]
        self.assertEqual(len(starts), 1)
        self.assertEqual(len(ends), 1)
        self.assertIsNotNone(starts[0]["agent_id"])
        self.assertEqual(starts[0]["agent_id"], ends[0]["agent_id"])
        self.assertIsNone(starts[0]["subagent_type"])
        self.assertIsNone(starts[0]["model"])
        self.assertIsNone(starts[0]["effort"])
        self.assertEqual(ends[0]["handoff_kind"], "resume")
        self.assertIsNone(ends[0]["subagent_type"])
        self.assertIsNone(ends[0]["model"])
        self.assertIsNone(ends[0]["effort"])

    def test_launch_handoff_end_carries_the_real_schemas_fields(self) -> None:
        """Every launch close carries ``handoff_kind``, ``model``, ``effort``
        and ``launch_ack`` — the fields the real schema carries on both
        halves (``hooks/keel_capture.py`` ``handoff_record``)."""
        ends = [
            e for e in self.events
            if e["event"] == "handoff_end" and e.get("handoff_kind") == "launch"
        ]
        self.assertTrue(ends)
        for end in ends:
            self.assertEqual(end["handoff_kind"], "launch")
            self.assertTrue(end.get("model"))
            self.assertTrue(end.get("effort"))
            self.assertIs(end.get("launch_ack"), True)
            self.assertTrue(end.get("subagent_type"))

    def test_every_launch_gets_a_closing_handoff_end(self) -> None:
        """No withheld launches (T138): every launch tool_use_id closes."""
        launches = {
            e["tool_use_id"] for e in self.events
            if e["event"] == "handoff_start" and e.get("handoff_kind") == "launch"
        }
        closed = {
            e["tool_use_id"] for e in self.events
            if e["event"] == "handoff_end"
        }
        self.assertTrue(launches)
        self.assertTrue(launches <= closed)

    def test_real_agent_types_used(self) -> None:
        types_seen = {
            e["subagent_type"] for e in self.events
            if e["event"] == "handoff_start" and e.get("subagent_type")
        }
        self.assertTrue(types_seen)
        self.assertTrue(types_seen <= REAL_AGENT_TYPES)
        stop_types = {
            e["agent_type"] for e in self.events
            if e["event"] == "subagent_stop" and e.get("agent_type")
        }
        self.assertTrue(stop_types <= REAL_AGENT_TYPES)

    def test_agent_ids_are_seventeen_lowercase_hex(self) -> None:
        ids = {
            e["agent_id"] for e in self.events
            if e.get("agent_id") and e["event"] in ("handoff_end", "subagent_stop")
        }
        self.assertTrue(ids)
        for agent_id in ids:
            self.assertRegex(agent_id, AGENT_ID_RE)

    def test_review_pass_and_fail_both_present(self) -> None:
        verdicts = {e["verdict"] for e in self.events if e["event"] == "review"}
        self.assertEqual(verdicts, {"pass", "fail"})

    def test_ledger_flips_a_box_for_the_passed_task(self) -> None:
        passed_tasks = {e["task"] for e in self.events if e["event"] == "review" and e["verdict"] == "pass"}
        failed_tasks = {e["task"] for e in self.events if e["event"] == "review" and e["verdict"] == "fail"}
        plan_text = self.plan_path.read_text(encoding="utf-8")
        for task_id in passed_tasks:
            self.assertRegex(plan_text, rf"- \[x\] {re.escape(task_id)} —")
        for task_id in failed_tasks:
            self.assertRegex(plan_text, rf"- \[ \] {re.escape(task_id)} —")


class TestFastHasNoRealSleep(unittest.TestCase):
    def test_two_fast_cycles_run_in_well_under_a_second(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            started = time.monotonic()
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--dir", tmp, "--fast", "--cycles", "2"])
            elapsed = time.monotonic() - started
        self.assertEqual(rc, 0)
        self.assertLess(elapsed, 2.0)


class TestVariedTaskNamesAcrossCycles(unittest.TestCase):
    def test_second_cycle_reviews_different_tasks_than_the_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                keel_demo.main(["--dir", tmp, "--fast", "--cycles", "2"])
            events = _read_events(Path(tmp, ".keel", "audit", "keel-audit.jsonl"))
        by_session: dict[str, set[str]] = {}
        for e in events:
            if e["event"] == "review":
                by_session.setdefault(e["session"], set()).add(e["task"])
        self.assertEqual(len(by_session), 2)
        first, second = sorted(by_session)
        self.assertNotEqual(by_session[first], by_session[second])


class TestServeFlagSpawnsDisclosedSubprocess(unittest.TestCase):
    def test_serve_prints_the_dashboard_command_and_spawns_it(self) -> None:
        calls = []

        class _FakePopen:
            def __init__(self, cmd):
                calls.append(cmd)

            def terminate(self) -> None:
                pass

            def wait(self, timeout=None) -> int:
                """T346: ``main`` now REAPS the board it terminated, so a
                double without this would fail on the teardown rather than
                on what it is testing."""
                return 0

        real_popen = keel_demo.subprocess.Popen
        keel_demo.subprocess.Popen = _FakePopen
        try:
            with tempfile.TemporaryDirectory() as tmp:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = keel_demo.main(
                        ["--dir", tmp, "--fast", "--cycles", "1", "--serve", "--port", "8771"]
                    )
                output = buf.getvalue()
        finally:
            keel_demo.subprocess.Popen = real_popen
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any("keel_orchestration_dashboard.py" in part for part in calls[0]))
        self.assertIn("--port", calls[0])
        self.assertIn("Spawning dashboard subprocess", output)


# =====================================================================
# KEEL ADDITION (T341): the forty-second tour
# =====================================================================
#: Where keel's own event classes are WRITTEN. The tour may emit nothing
#: that is not written by one of these files — and the list of classes is
#: DERIVED from them below rather than hand-copied here, because a
#: hand-copied list is exactly how a demo starts claiming an event class the
#: product does not have.
_EVENT_SOURCES = tuple(sorted((REPO_ROOT / "hooks").glob("keel_*.py"))) + (
    REPO_ROOT / "scripts" / "keel_review.py",  # a verdict is not a hook event
)

_ASSIGN_RE = re.compile(
    r"^([A-Z][A-Z0-9_]*)\s*(?::[^=\n]+)?=\s*\"([a-z_]+)\"\s*$", re.MULTILINE
)
_EVENT_LINE_RE = re.compile(r"\"event\":(.*)$", re.MULTILINE)
_STRING_RE = re.compile(r"\"([a-z_]+)\"")
_NAME_RE = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def _real_event_classes() -> set[str]:
    """Every ``event`` value keel's own writers can put on an audit line,
    read out of those writers' source.

    Two shapes are resolved: a literal (``"event": "gate_block"``) and a
    module constant (``"event": ACTION_EVENT``, including the two-armed
    ``X if opening else Y`` the hand-off writer uses). A constant nobody
    assigns a literal to — a function parameter, for instance — is simply
    not derivable and is left out: this set is a floor on what keel emits,
    which is the direction that keeps the assertion honest.
    """
    consts: dict[str, str] = {}
    texts = []
    for path in _EVENT_SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace")
        texts.append(text)
        for name, value in _ASSIGN_RE.findall(text):
            consts[name] = value
    classes: set[str] = set()
    for text in texts:
        for tail in _EVENT_LINE_RE.findall(text):
            classes.update(_STRING_RE.findall(tail))
            for name in _NAME_RE.findall(tail):
                if name in consts:
                    classes.add(consts[name])
    return classes


class TestTourTimelineIsData(unittest.TestCase):
    """The timeline can be read, ordered and counted without running it."""

    def test_eight_beats_numbered_one_through_eight(self) -> None:
        self.assertEqual(
            [b.n for b in keel_demo.TOUR], [1, 2, 3, 4, 5, 6, 7, 8]
        )

    def test_offsets_are_monotonic_fractions_of_the_whole(self) -> None:
        offsets = [b.at for b in keel_demo.TOUR]
        self.assertEqual(offsets, sorted(offsets))
        self.assertEqual(len(set(offsets)), len(offsets))
        self.assertEqual(offsets[0], 0.0)
        for at in offsets:
            self.assertGreaterEqual(at, 0.0)
            self.assertLess(at, 1.0)

    def test_every_beat_carries_a_label_and_at_least_one_event(self) -> None:
        for beat in keel_demo.TOUR:
            self.assertTrue(beat.label.strip(), beat.n)
            self.assertTrue(beat.events, f"beat {beat.n} emits nothing")
            for event in beat.events:
                self.assertIn("event", event)
                self.assertEqual(event["session"], keel_demo.TOUR_SESSION)

    def test_no_beat_runs_into_the_next_one(self) -> None:
        """Every cue of a beat lands before the next beat opens, and the
        last beat lands before the tour's own end — the legibility rule
        (a beat is the unit a viewer reads)."""
        beats = keel_demo.TOUR
        for beat, nxt in zip(beats, beats[1:]):
            self.assertLess(beat.at + beat.span, nxt.at, f"beat {beat.n} overruns")
        self.assertLess(beats[-1].at + beats[-1].span, 1.0)

    def test_beats_are_at_least_three_board_polls_apart(self) -> None:
        """The board polls every 1.5s; a beat closer than ~3s to the next is
        not legible. At the 40s default every gap must clear that bar."""
        times = [b.at * keel_demo.TOUR_SECONDS for b in keel_demo.TOUR]
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, 3.0)

    def test_no_cue_carries_both_an_event_and_a_ledger_edit(self) -> None:
        for beat in keel_demo.TOUR:
            for cue in beat.cues:
                self.assertFalse(
                    cue.event is not None and cue.ledger is not None,
                    f"beat {beat.n}: a cue is both a log line and a file edit",
                )
                self.assertTrue(cue.event is not None or cue.ledger is not None)
                self.assertGreaterEqual(cue.dt, 0.0)


class TestTourEmitsOnlyRealEventClasses(unittest.TestCase):
    def test_the_derivation_finds_keels_own_classes(self) -> None:
        """Guard on the guard: a derivation that silently found nothing
        would make the assertion below vacuous (the T140 lesson)."""
        real = _real_event_classes()
        self.assertGreaterEqual(len(real), 8)
        for expected in ("gate_block", "stop_block", "activity", "review"):
            self.assertIn(expected, real)

    def test_every_event_class_in_the_timeline_is_one_keel_emits(self) -> None:
        real = _real_event_classes()
        emitted = {
            event["event"] for beat in keel_demo.TOUR for event in beat.events
        }
        self.assertTrue(emitted)
        self.assertEqual(emitted - real, set())

    def test_the_timeline_tells_the_story_with_the_expected_classes(self) -> None:
        emitted = {
            event["event"] for beat in keel_demo.TOUR for event in beat.events
        }
        self.assertEqual(
            emitted,
            {
                "session_start", "gate_block", "activity", "handoff_start",
                "handoff_end", "review", "subagent_stop", "stop_block",
                "session_end",
            },
        )


class TestTourBeatsSayWhatTheLedgerPromised(unittest.TestCase):
    """Each of the eight beats carries the specific thing it exists for."""

    def _beat(self, n: int):
        return keel_demo.TOUR[n - 1]

    def test_beat_1_opens_the_session_and_nothing_else(self) -> None:
        events = self._beat(1).events
        self.assertEqual([e["event"] for e in events], ["session_start"])

    def test_beat_2_is_a_plan_gate_refusal_inside_the_first_ten_seconds(self) -> None:
        beat = self._beat(2)
        blocks = [e for e in beat.events if e["event"] == "gate_block"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["gate"], "plan")
        self.assertEqual(blocks[0]["kind"], "pre_write")
        self.assertIn("target", blocks[0]["detail"])
        self.assertLess(
            (beat.at + beat.span) * keel_demo.TOUR_SECONDS, 10.0
        )

    def test_beat_3_writes_the_whole_ledger_open(self) -> None:
        beat = self._beat(3)
        self.assertIn(("plan", ""), [c.ledger for c in beat.cues])
        # T345c: at least ten items — five read thin in the rail
        self.assertGreaterEqual(len(keel_demo.TOUR_TASKS), 10)
        # and nothing is closed before the plan has even landed
        self.assertEqual(keel_demo._closed_through(3), 0)

    def test_beat_4_launches_three_agents_at_three_distinct_tiers(self) -> None:
        starts = [
            e for e in self._beat(4).events
            if e["event"] == "handoff_start" and e["handoff_kind"] == "launch"
        ]
        self.assertEqual(len(starts), 3)
        routes = {(e["model"], e["effort"]) for e in starts}
        self.assertEqual(len(routes), 3)
        types = {e["subagent_type"] for e in starts}
        self.assertEqual(len(types), 3)
        self.assertTrue(types <= REAL_AGENT_TYPES)
        # the satellites: activity attributed to each working agent's type
        acted = {
            e["agent_type"] for e in self._beat(4).events
            if e["event"] == "activity" and e["agent_type"]
        }
        self.assertEqual(acted, types)

    def test_beat_5_is_a_second_and_different_refusal_class(self) -> None:
        blocks = [e for e in self._beat(5).events if e["event"] == "gate_block"]
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["gate"], "policy_lock")
        earlier = [e for e in self._beat(2).events if e["event"] == "gate_block"]
        self.assertNotEqual(blocks[0]["gate"], earlier[0]["gate"])

    def test_beat_6_fails_retries_deeper_and_passes_the_same_task(self) -> None:
        events = self._beat(6).events
        # the ladder is about ONE task: the one that failed. Other items may
        # close in this beat too (T345c spreads the ledger's progress).
        failed = [
            e for e in events
            if e["event"] == "review" and e["verdict"] == "fail"
        ]
        self.assertEqual(len(failed), 1)
        task = failed[0]["task"]
        reviews = [
            e for e in events if e["event"] == "review" and e["task"] == task
        ]
        self.assertEqual([r["verdict"] for r in reviews], ["fail", "pass"])
        self.assertEqual(reviews[0]["task"], reviews[1]["task"])
        # the retry between them is a launch at the deep tier
        order = [e for e in events if e["event"] in ("review", "handoff_start")]
        fail_at = order.index(reviews[0])
        pass_at = order.index(reviews[1])
        between = [
            e for e in order[fail_at + 1:pass_at]
            if e["event"] == "handoff_start"
            and e["subagent_type"] == "keel:executor-deep"
        ]
        self.assertEqual(len(between), 1)
        self.assertEqual((between[0]["model"], between[0]["effort"]), ("opus", "high"))
        self.assertIn(
            ("check", reviews[1]["task"]), [c.ledger for c in self._beat(6).cues]
        )

    def test_beat_7_resumes_an_agent_that_already_recorded_a_route(self) -> None:
        beat = self._beat(7)
        resumes = [e for e in beat.events if e.get("handoff_kind") == "resume"]
        self.assertEqual(len(resumes), 2)
        for half in resumes:
            self.assertIsNone(half["subagent_type"])
            self.assertIsNone(half["model"])
            self.assertIsNone(half["effort"])
            self.assertTrue(half["agent_id"])
        # the id it resumes is one an EARLIER beat launched with a route on
        # the record — the join the board makes on the read side (T337)
        launched = {
            e["agent_id"]: (e["model"], e["effort"])
            for b in keel_demo.TOUR[:6] for e in b.events
            if e["event"] == "handoff_end" and e.get("handoff_kind") == "launch"
        }
        self.assertIn(resumes[0]["agent_id"], launched)
        self.assertEqual(launched[resumes[0]["agent_id"]], ("opus", "high"))

    def test_beat_8_refuses_the_stop_then_closes_the_last_item(self) -> None:
        beat = self._beat(8)
        blocks = [e for e in beat.events if e["event"] == "stop_block"]
        self.assertEqual(len(blocks), 1)
        detail = blocks[0]["detail"]
        self.assertEqual(blocks[0]["gate"], "stop")
        self.assertEqual(detail["open_items"], 1)
        self.assertEqual(len(detail["open_item_ids"]), 1)
        last = detail["open_item_ids"][0]
        self.assertIn(("check", last), [c.ledger for c in beat.cues])
        # and the block comes BEFORE the item closes and the session ends
        kinds = [e["event"] for e in beat.events]
        self.assertEqual(kinds[0], "stop_block")
        self.assertEqual(kinds[-1], "session_end")

    def test_every_ledger_item_is_closed_by_the_final_frame(self) -> None:
        checked = {
            c.ledger[1] for beat in keel_demo.TOUR for c in beat.cues
            if c.ledger and c.ledger[0] == "check"
        }
        self.assertEqual(checked, {t[0] for t in keel_demo.TOUR_TASKS})

    def test_every_launch_in_the_timeline_closes(self) -> None:
        events = [e for beat in keel_demo.TOUR for e in beat.events]
        opened = {
            e["tool_use_id"] for e in events if e["event"] == "handoff_start"
        }
        closed = {
            e["tool_use_id"] for e in events if e["event"] == "handoff_end"
        }
        self.assertTrue(opened)
        self.assertEqual(opened, closed)


class TestTourSecondsScalesTheWholeChoreography(unittest.TestCase):
    def test_doubling_the_duration_doubles_every_offset(self) -> None:
        base = keel_demo.beat_schedule(40.0)
        wide = keel_demo.beat_schedule(80.0)
        self.assertEqual(len(base), len(wide))
        for (n1, at1, cues1), (n2, at2, cues2) in zip(base, wide):
            self.assertEqual(n1, n2)
            self.assertAlmostEqual(at2, at1 * 2)
            self.assertEqual(len(cues1), len(cues2))
            for c1, c2 in zip(cues1, cues2):
                self.assertAlmostEqual(c2, c1 * 2)

    def test_the_last_cue_lands_inside_the_requested_duration(self) -> None:
        for seconds in (20.0, 40.0, 90.0):
            last = keel_demo.beat_schedule(seconds)[-1][2][-1]
            self.assertLess(last, seconds)

    def test_a_nonpositive_duration_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--tour", "--fast", "--seconds", "0", "--dir", tmp])
            self.assertNotEqual(rc, 0)
            self.assertFalse(Path(tmp, ".keel").exists())


class TestTourFastRun(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        started = time.monotonic()
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.rc = keel_demo.main(["--tour", "--fast", "--dir", str(self.root)])
        self.elapsed = time.monotonic() - started
        self.log_path = self.root / ".keel" / "audit" / "keel-audit.jsonl"
        self.events = _read_events(self.log_path)
        self.plan_path = keel_demo.tour_plan_path(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exit_zero_without_sleeping(self) -> None:
        self.assertEqual(self.rc, 0)
        self.assertLess(self.elapsed, 2.0)

    def test_every_session_line_is_demo_prefixed(self) -> None:
        sessions = {e["session"] for e in self.events if "session" in e}
        self.assertEqual(sessions, {keel_demo.TOUR_SESSION})
        for sid in sessions:
            self.assertTrue(sid.startswith("demo-"), sid)

    def test_the_log_holds_the_whole_timeline_in_order(self) -> None:
        expected = [
            e["event"] for beat in keel_demo.TOUR for e in beat.events
        ]
        self.assertEqual([e["event"] for e in self.events], expected)

    def test_only_real_event_classes_reach_the_log(self) -> None:
        real = _real_event_classes()
        self.assertEqual({e["event"] for e in self.events} - real, set())

    def test_both_refusal_classes_and_the_stop_refusal_are_on_the_log(self) -> None:
        gates = [e["gate"] for e in self.events if e["event"] == "gate_block"]
        self.assertEqual(gates, ["plan", "policy_lock"])
        stops = [e for e in self.events if e["event"] == "stop_block"]
        self.assertEqual(len(stops), 1)

    def test_the_ledger_starts_absent_and_ends_complete(self) -> None:
        """The loop's pre-filled ledger is NOT written in tour mode (beat 1
        shows an empty ledger), and the tour's own ledger closes."""
        plans = sorted(p.name for p in (self.root / ".keel" / "plans").iterdir())
        self.assertEqual(plans, [self.plan_path.name])
        text = self.plan_path.read_text(encoding="utf-8")
        for task_id, _ in keel_demo.TOUR_TASKS:
            self.assertRegex(text, rf"- \[x\] {re.escape(task_id)} —")
        self.assertNotIn("- [ ]", text)

    def test_the_ledger_is_named_by_keels_own_session_rule(self) -> None:
        self.assertEqual(
            self.plan_path.name, f"keel-plan-{keel_demo.TOUR_SESSION[:8]}.md"
        )

    def test_agent_ids_are_seventeen_lowercase_hex_and_types_are_real(self) -> None:
        ids = {
            e["agent_id"] for e in self.events
            if e.get("agent_id") and e["event"] in ("handoff_end", "subagent_stop")
        }
        self.assertTrue(ids)
        for agent_id in ids:
            self.assertRegex(agent_id, AGENT_ID_RE)
        types = {
            e["subagent_type"] for e in self.events if e.get("subagent_type")
        } | {e["agent_type"] for e in self.events if e.get("agent_type")}
        self.assertTrue(types <= REAL_AGENT_TYPES)

    def test_a_rerun_into_the_same_demo_directory_is_still_accepted(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = keel_demo.main(["--tour", "--fast", "--dir", str(self.root)])
        self.assertEqual(rc, 0)


class TestTourGoesThroughTheSameRefusalPath(unittest.TestCase):
    """The safety property is PINNED for the tour too: the mode is new, the
    refusal is not — a tour aimed at a real record exits non-zero having
    written nothing (see
    .keel/knowledge/a-demo-must-be-refused-the-record-it-imitates.md)."""

    def test_a_tour_at_this_scripts_own_repo_root_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as fake_repo_root:
            fake_repo_root = Path(fake_repo_root).resolve()
            original = keel_demo.REPO_ROOT
            keel_demo.REPO_ROOT = fake_repo_root
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = keel_demo.main(
                        ["--tour", "--fast", "--dir", str(fake_repo_root)]
                    )
            finally:
                keel_demo.REPO_ROOT = original
            self.assertNotEqual(rc, 0)
            self.assertFalse((fake_repo_root / ".keel").exists())

    def test_a_tour_at_a_project_holding_a_real_session_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as real_root:
            real_root = Path(real_root)
            (real_root / ".keel" / "audit").mkdir(parents=True)
            (real_root / ".keel" / "plans").mkdir(parents=True)
            real_log = real_root / ".keel" / "audit" / "keel-audit.jsonl"
            real_log.write_text(
                '{"v": 1, "ts": "2026-01-01T00:00:00Z", "event": "session_start", '
                '"session": "real-not-touched", "source": "startup", "model": "sonnet"}\n',
                encoding="utf-8",
            )
            before = real_log.read_bytes()

            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--tour", "--fast", "--dir", str(real_root)])

            self.assertNotEqual(rc, 0)
            self.assertEqual(real_log.read_bytes(), before)
            self.assertEqual(list((real_root / ".keel" / "plans").iterdir()), [])
            self.assertFalse((real_root / ".keel" / "keel-policy.md").exists())


# ---------------------------------------------------------------------
# KEEL ADDITION (T345): four fixes from watching the tour run
# ---------------------------------------------------------------------
_COUNT_RE = re.compile(r"(\d+) of (\d+)")
_TASKS_RE = re.compile(r"(\d+) tasks")

#: The whimsy T345d retired. A regression pin, not a style opinion: these
#: exact words are what taught a watching stranger nothing.
_RETIRED_WHIMSY = (
    "caulk", "mizzen", "mainbrace", "barnacle", "foresail",
    "anchorage", "ballast", "swab", "shoal", "keel for",
)


class TestTheLedgerFillsAcrossTheRun(unittest.TestCase):
    """T345c: ten or more items, closing in stages, ending complete — and no
    beat's prose naming a count the cues do not produce."""

    def test_the_ledger_holds_at_least_ten_items(self) -> None:
        self.assertGreaterEqual(len(keel_demo.TOUR_TASKS), 10)
        ids = [t[0] for t in keel_demo.TOUR_TASKS]
        self.assertEqual(len(set(ids)), len(ids))

    def test_the_close_map_matches_the_cues_actually_written(self) -> None:
        """The single-source rule: ``TOUR_CLOSES`` feeds the beat prose, so a
        close that moves in the timeline without moving here would leave a
        stale number in a label. This is the test that forbids that."""
        actual: dict[int, tuple[str, ...]] = {}
        for beat in keel_demo.TOUR:
            closed = tuple(
                c.ledger[1] for c in beat.cues
                if c.ledger and c.ledger[0] == "check"
            )
            if closed:
                actual[beat.n] = closed
        self.assertEqual(actual, keel_demo.TOUR_CLOSES)

    def test_the_closes_are_spread_and_never_dumped_at_the_end(self) -> None:
        counts = [keel_demo._closed_through(b.n) for b in keel_demo.TOUR]
        self.assertEqual(counts[-1], len(keel_demo.TOUR_TASKS))
        # at least four beats move the rail, and no single beat closes half
        moving = [b for b in keel_demo.TOUR if b.n in keel_demo.TOUR_CLOSES]
        self.assertGreaterEqual(len(moving), 4)
        for closed in keel_demo.TOUR_CLOSES.values():
            self.assertLess(len(closed), len(keel_demo.TOUR_TASKS) / 2)
        # monotonic, and strictly rising from the first beat that closes
        self.assertEqual(counts, sorted(counts))
        first = min(keel_demo.TOUR_CLOSES)
        rising = [keel_demo._closed_through(n) for n in range(first, 9)]
        self.assertEqual(len(set(rising)), len(rising))

    def test_exactly_one_item_is_open_when_the_stop_is_attempted(self) -> None:
        """The stop refusal's own count has to be the truth of the ledger at
        that instant, not a number chosen for the story."""
        stop_beat = keel_demo.TOUR[-1]
        blocks = [e for e in stop_beat.events if e["event"] == "stop_block"]
        open_before = len(keel_demo.TOUR_TASKS) - keel_demo._closed_through(7)
        self.assertEqual(blocks[0]["detail"]["open_items"], open_before)
        self.assertEqual(open_before, 1)
        self.assertEqual(
            tuple(blocks[0]["detail"]["open_item_ids"]),
            keel_demo.TOUR_CLOSES[stop_beat.n],
        )

    def test_no_beat_label_names_a_stale_count(self) -> None:
        total = len(keel_demo.TOUR_TASKS)
        for beat in keel_demo.TOUR:
            for done, of in _COUNT_RE.findall(beat.label):
                self.assertEqual(
                    (int(done), int(of)),
                    (keel_demo._closed_through(beat.n), total),
                    f"beat {beat.n} label: {beat.label}",
                )
            for named in _TASKS_RE.findall(beat.label):
                self.assertEqual(int(named), total, beat.label)

    def test_every_item_gets_a_passing_verdict_of_its_own(self) -> None:
        """A box does not flip without a verdict beside it: every close in
        the timeline is accompanied by a ``review`` pass on that task."""
        passed = {
            e["task"] for beat in keel_demo.TOUR for e in beat.events
            if e["event"] == "review" and e["verdict"] == "pass"
        }
        self.assertEqual(passed, {t[0] for t in keel_demo.TOUR_TASKS})


class TestTaskNamesReadLikeRealWork(unittest.TestCase):
    """T345d: the ledger teaches an adopter something, and the agents' task
    lines are the ledger's own items rather than a second invented list."""

    def test_no_retired_whimsy_comes_back(self) -> None:
        blob = " ".join(desc for _, desc in keel_demo.TASK_POOL).lower()
        for word in _RETIRED_WHIMSY:
            self.assertNotIn(word, blob)

    def test_every_item_reads_like_a_task_someone_would_delegate(self) -> None:
        for task_id, desc in keel_demo.TASK_POOL:
            self.assertRegex(task_id, r"^T\d+$")
            self.assertGreaterEqual(len(desc.split()), 4, desc)
            self.assertEqual(desc, desc.strip())

    def test_agent_task_lines_come_from_the_ledger(self) -> None:
        by_id = dict(keel_demo.TOUR_TASKS)
        described = [
            e["description"] for beat in keel_demo.TOUR for e in beat.events
            if e["event"] == "handoff_start"
        ]
        self.assertTrue(described)
        seen = 0
        for text in described:
            head = text.split(":")[0].split()[0]
            if head in by_id:
                seen += 1
                if ":" in text:
                    self.assertEqual(text, f"{head}: {by_id[head]}")
        self.assertGreaterEqual(seen, 3)


class TestTheCaptainsSeatIsNotACrewTier(unittest.TestCase):
    """T345b: the orchestrator's own pill is drawn from ``session_start``'s
    ``model``, so a crew tier recorded there misreads keel's routing on the
    first card a viewer looks at."""

    def test_the_tour_records_the_orchestrator_seat(self) -> None:
        starts = [
            e for beat in keel_demo.TOUR for e in beat.events
            if e["event"] == "session_start"
        ]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["model"], keel_demo.ORCHESTRATOR_MODEL)
        self.assertEqual(keel_demo.ORCHESTRATOR_MODEL, "fable")

    def test_no_delegation_is_routed_to_the_orchestrator_seat(self) -> None:
        for beat in keel_demo.TOUR:
            for event in beat.events:
                if event["event"] in ("handoff_start", "handoff_end"):
                    self.assertNotEqual(
                        event.get("model"), keel_demo.ORCHESTRATOR_MODEL
                    )

    def test_the_crew_still_wears_its_own_tiers(self) -> None:
        routes = {
            (e["model"], e["effort"]) for beat in keel_demo.TOUR
            for e in beat.events
            if e["event"] == "handoff_start" and e.get("model")
        }
        self.assertIn(("sonnet", "default"), routes)
        self.assertIn(("opus", "high"), routes)

    def test_the_loop_records_it_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                keel_demo.main(["--dir", tmp, "--fast", "--cycles", "1"])
            events = _read_events(
                Path(tmp, ".keel", "audit", "keel-audit.jsonl")
            )
        starts = [e for e in events if e["event"] == "session_start"]
        self.assertTrue(starts)
        for start in starts:
            self.assertEqual(start["model"], keel_demo.ORCHESTRATOR_MODEL)


class TestTheBoardOutlivesTheTour(unittest.TestCase):
    """T345a: after a single-pass tour the board keeps serving until Ctrl-C —
    and under ``--fast`` it must not wait at all, or this very suite hangs.

    T346 moved the single pass behind ``--once`` (repetition is the default),
    so these runs name it; the repeating default has its own class below."""

    def _run(self, argv: list[str]) -> tuple[int, list[str], str]:
        calls: list[str] = []

        class _FakePopen:
            def __init__(self, cmd):
                calls.append("spawn")

            def terminate(self) -> None:
                calls.append("terminate")

            def wait(self, timeout=None) -> int:
                calls.append("reap")
                return 0

        real_popen = keel_demo.subprocess.Popen
        real_hold = keel_demo._hold_board
        keel_demo.subprocess.Popen = _FakePopen
        keel_demo._hold_board = lambda url: calls.append(f"hold:{url}")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = keel_demo.main(argv + ["--dir", tmp])
                return rc, calls, buf.getvalue()
        finally:
            keel_demo.subprocess.Popen = real_popen
            keel_demo._hold_board = real_hold

    def test_a_real_time_tour_holds_the_board_before_tearing_it_down(self) -> None:
        rc, calls, _ = self._run(
            ["--tour", "--once", "--serve", "--seconds", "0.5", "--port", "8791"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(calls[0], "spawn")
        self.assertEqual(calls[1], "hold:http://127.0.0.1:8791/")
        self.assertEqual(calls[-2:], ["terminate", "reap"])

    def test_a_fast_tour_never_waits(self) -> None:
        started = time.monotonic()
        rc, calls, _ = self._run(["--tour", "--serve", "--fast"])
        elapsed = time.monotonic() - started
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["spawn", "terminate", "reap"])
        self.assertLess(elapsed, 2.0)

    def test_a_tour_without_serve_has_no_board_to_hold(self) -> None:
        rc, calls, out = self._run(["--tour", "--once", "--seconds", "0.5"])
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [])
        # but it still tells the viewer how to open one
        self.assertIn("keel_orchestration_dashboard.py", out)

    def test_the_hold_says_where_the_board_is(self) -> None:
        """``_hold_board`` itself blocks, so what is pinned here is its
        announcement — the URL a viewer needs — with the loop cut short."""
        printed: list[str] = []
        real_sleep = keel_demo.time.sleep

        def _boom(_seconds):
            raise KeyboardInterrupt

        keel_demo.time.sleep = _boom
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                with self.assertRaises(KeyboardInterrupt):
                    keel_demo._hold_board("http://127.0.0.1:8771/")
            printed.append(buf.getvalue())
        finally:
            keel_demo.time.sleep = real_sleep
        self.assertIn("STILL SERVING", printed[0])
        self.assertIn("http://127.0.0.1:8771/", printed[0])
        self.assertIn("Ctrl-C", printed[0])


# =====================================================================
# KEEL ADDITION (T346): THE TOUR RUNS UNTIL STOPPED
# =====================================================================
# The owner's sentence, 2026-08-26: "the demo should run unless I stopped
# it". Three things are pinned below, and the middle one is the reason this
# file can be run at all:
#   1. a ROUND is a SESSION — the board derives its round list from distinct
#      session ids (``tick()``: "rounds = every session OBSERVED in the log,
#      by first appearance") and each round's ledger from that session's own
#      sess8, so a new round means a new session id and a new ledger file,
#      never an invented field and never a second start on one id;
#   2. ``--fast`` plays EXACTLY ONE PASS, and so does ``--once`` — if either
#      ever inherited the repeating default, this suite would hang forever
#      instead of failing;
#   3. the default DOES repeat, and Ctrl-C at any point leaves nothing
#      behind: no further rounds, no held board, no unreaped subprocess.


class TestARoundIsASession(unittest.TestCase):
    """What a round boundary IS, checked against the board's own derivation."""

    def test_every_rounds_session_id_is_demo_prefixed_and_its_own(self) -> None:
        ids = [keel_demo.tour_session_id(n) for n in range(1, 60)]
        for sid in ids:
            self.assertTrue(sid.startswith("demo-"), sid)
        self.assertEqual(len(set(ids)), len(ids))

    def test_two_rounds_never_share_a_sess8(self) -> None:
        """The ledger key is the first EIGHT characters, so two rounds
        sharing those would share one ledger file — round 2 resetting it
        would rewrite round 1's finished rail under a viewer paging back."""
        sess8s = [keel_demo.tour_session_id(n)[:8] for n in range(1, 400)]
        self.assertEqual(len(set(sess8s)), len(sess8s))

    def test_round_one_is_the_session_the_timeline_is_written_against(self) -> None:
        self.assertEqual(keel_demo.tour_session_id(1), keel_demo.TOUR_SESSION)
        self.assertEqual(keel_demo.TOUR_SESS8, keel_demo.TOUR_SESSION[:8])

    def test_each_round_gets_its_own_ledger_named_by_keels_own_rule(self) -> None:
        root = Path("nowhere")
        for n in (1, 2, 7):
            sid = keel_demo.tour_session_id(n)
            self.assertEqual(
                keel_demo.tour_plan_path(root, n).name, f"keel-plan-{sid[:8]}.md"
            )

    def test_no_round_shares_an_agent_id_or_a_handoff_id_with_another(self) -> None:
        """A real record never reuses an agent id across sessions, and the
        board pairs a launch by its ``tool_use_id``. Both are re-drawn."""

        def ids(round_n: int) -> tuple[set, set]:
            events = [
                keel_demo.stamp_round(e, round_n)
                for beat in keel_demo.TOUR for e in beat.events
            ]
            return (
                {e["agent_id"] for e in events if e.get("agent_id")},
                {e["tool_use_id"] for e in events if e.get("tool_use_id")},
            )

        a1, u1 = ids(1)
        a2, u2 = ids(2)
        a3, u3 = ids(3)
        self.assertTrue(a1 and u1)
        self.assertEqual(a1 & a2, set())
        self.assertEqual(a2 & a3, set())
        self.assertEqual(u1 & u2, set())
        self.assertEqual(u2 & u3, set())
        for agent_id in a2 | a3:
            self.assertRegex(agent_id, AGENT_ID_RE)

    def test_stamping_moves_the_session_and_nothing_structural(self) -> None:
        for beat in keel_demo.TOUR:
            for event in beat.events:
                stamped = keel_demo.stamp_round(event, 4)
                self.assertEqual(list(stamped), list(event))
                self.assertEqual(stamped["session"], keel_demo.tour_session_id(4))
                self.assertEqual(stamped["event"], event["event"])

    def test_a_stamped_round_stays_internally_consistent(self) -> None:
        """Round 4's resume names an agent ROUND 4 launched — the join the
        board makes on the read side must not cross a round boundary."""
        events = [
            keel_demo.stamp_round(e, 4)
            for beat in keel_demo.TOUR for e in beat.events
        ]
        launched = {
            e["agent_id"] for e in events
            if e["event"] == "handoff_end" and e.get("handoff_kind") == "launch"
        }
        resumes = [e for e in events if e.get("handoff_kind") == "resume"]
        self.assertTrue(resumes)
        for half in resumes:
            self.assertIn(half["agent_id"], launched)
        stops = [e for e in events if e["event"] == "subagent_stop"]
        self.assertTrue(stops)
        for stop in stops:
            self.assertIn(stop["agent_id"], launched)
        opened = {e["tool_use_id"] for e in events if e["event"] == "handoff_start"}
        closed = {e["tool_use_id"] for e in events if e["event"] == "handoff_end"}
        self.assertEqual(opened, closed)

    def test_the_prose_names_the_round_that_is_playing(self) -> None:
        beat3 = keel_demo.TOUR[2]
        self.assertIn(keel_demo.TOUR_ROUND_TOKEN, beat3.label)
        self.assertIn("round 5", keel_demo.beat_label(beat3, 5))
        details = [keel_demo.stamp_round(e, 5).get("detail") for e in beat3.events]
        self.assertIn(f"round 5: {len(keel_demo.TOUR_TASKS)} tasks", details)
        self.assertIn(
            keel_demo.tour_plan_path(Path("x"), 5).name,
            " ".join(d for d in details if isinstance(d, str)),
        )

    def test_no_placeholder_survives_into_a_label_or_a_record(self) -> None:
        for beat in keel_demo.TOUR:
            self.assertNotIn(
                keel_demo.TOUR_ROUND_TOKEN, keel_demo.beat_label(beat, 9)
            )
            for event in beat.events:
                self.assertNotIn(
                    keel_demo.TOUR_ROUND_TOKEN,
                    json.dumps(keel_demo.stamp_round(event, 9)),
                )


class TestRoundsFillTheirOwnLedgerFromZero(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        keel_demo.build_demo_project(self.root, with_plan=False)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_three_rounds_write_three_sessions_and_three_ledgers(self) -> None:
        played = [
            keel_demo.run_tour(self.root, fast=True, echo=False, round_n=n)
            for n in (1, 2, 3)
        ]
        self.assertEqual(len(set(played)), 3)
        events = _read_events(self.root / ".keel" / "audit" / "keel-audit.jsonl")
        sessions = {e["session"] for e in events if "session" in e}
        self.assertEqual(sessions, set(played))
        for sid in sessions:
            self.assertTrue(sid.startswith("demo-"), sid)
        # one session_start per round and not one more: the board counts a
        # repeat start on the SAME id as no new round at all, so a second one
        # would be a line that changes nothing on screen
        starts = [e for e in events if e["event"] == "session_start"]
        self.assertEqual(len(starts), 3)
        self.assertEqual(len({e["session"] for e in starts}), 3)
        plans = sorted(p.name for p in (self.root / ".keel" / "plans").iterdir())
        self.assertEqual(
            plans,
            sorted(keel_demo.tour_plan_path(self.root, n).name for n in (1, 2, 3)),
        )
        for n in (1, 2, 3):
            text = keel_demo.tour_plan_path(self.root, n).read_text(encoding="utf-8")
            self.assertNotIn("- [ ]", text)
            self.assertEqual(text.count("- [x]"), len(keel_demo.TOUR_TASKS))

    def test_round_two_fills_from_zero_while_round_one_stays_complete(self) -> None:
        """The rail is not an accumulator: sampled at every line round 2
        writes, round 2's ledger appears with NOTHING checked and climbs from
        there, and round 1's finished ledger never moves."""
        keel_demo.run_tour(self.root, fast=True, echo=False, round_n=1)
        first = keel_demo.tour_plan_path(self.root, 1)
        second = keel_demo.tour_plan_path(self.root, 2)
        total = len(keel_demo.TOUR_TASKS)
        self.assertEqual(first.read_text(encoding="utf-8").count("- [x]"), total)

        samples: list[tuple[int | None, int]] = []
        real_append = keel_demo._append

        def _spy(log_path, event):
            real_append(log_path, event)
            samples.append((
                second.read_text(encoding="utf-8").count("- [x]")
                if second.exists() else None,
                first.read_text(encoding="utf-8").count("- [x]"),
            ))

        keel_demo._append = _spy
        try:
            keel_demo.run_tour(self.root, fast=True, echo=False, round_n=2)
        finally:
            keel_demo._append = real_append

        seen = [n for n, _ in samples]
        self.assertIsNone(seen[0])                 # no round-2 ledger yet
        filled = [n for n in seen if n is not None]
        self.assertEqual(filled[0], 0)             # it arrives EMPTY
        self.assertEqual(filled[-1], total)        # and ends complete
        self.assertEqual(filled, sorted(filled))   # monotonically, never reset
        self.assertGreater(len(set(filled)), 3)    # visibly, in stages
        self.assertEqual({n for _, n in samples}, {total})  # round 1 untouched


class TestTheTourRepeatsUntilStopped(unittest.TestCase):
    """The flag semantics, all four of them, without ever risking a hang:
    ``run_tour`` is stubbed, so no round costs a second and the stub decides
    where the Ctrl-C lands."""

    HARD_CAP = 40  # a regression that repeats when it must not FAILS, never hangs

    def _run(
        self, argv: list[str], *, stop_after: int | None = None,
        hold_raises: bool = False,
    ) -> tuple[int, list[int], list[str], str]:
        rounds: list[int] = []
        calls: list[str] = []
        seconds_seen: set[float] = set()

        class _FakePopen:
            def __init__(self, cmd):
                calls.append("spawn")

            def terminate(self) -> None:
                calls.append("terminate")

            def wait(self, timeout=None) -> int:
                calls.append("reap")
                return 0

        def _stub_tour(root, *, seconds=0.0, fast=False, echo=True, round_n=1):
            rounds.append(round_n)
            seconds_seen.add(seconds)
            if len(rounds) > self.HARD_CAP:
                raise RuntimeError("the tour repeated where it must not")
            if stop_after is not None and round_n >= stop_after:
                raise KeyboardInterrupt  # Ctrl-C, mid-beat
            return keel_demo.tour_session_id(round_n)

        def _stub_hold(url):
            calls.append(f"hold:{url}")
            if hold_raises:
                raise KeyboardInterrupt  # Ctrl-C while the board is held

        real_popen = keel_demo.subprocess.Popen
        real_tour = keel_demo.run_tour
        real_hold = keel_demo._hold_board
        keel_demo.subprocess.Popen = _FakePopen
        keel_demo.run_tour = _stub_tour
        keel_demo._hold_board = _stub_hold
        try:
            with tempfile.TemporaryDirectory() as tmp:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = keel_demo.main(argv + ["--dir", tmp])
                self.seconds_seen = seconds_seen
                return rc, rounds, calls, buf.getvalue()
        finally:
            keel_demo.subprocess.Popen = real_popen
            keel_demo.run_tour = real_tour
            keel_demo._hold_board = real_hold

    def test_repetition_is_the_default_for_tour(self) -> None:
        """No ``--once`` and no ``--fast``: round 4 plays, because rounds
        1-3 did not end the run."""
        rc, rounds, _, out = self._run(
            ["--tour", "--serve", "--seconds", "20"], stop_after=4
        )
        self.assertEqual(rc, 0)
        self.assertEqual(rounds, [1, 2, 3, 4])
        self.assertEqual(self.seconds_seen, {20.0})  # --seconds is PER ROUND
        self.assertIn("stopped", out)

    def test_a_repeating_tour_never_holds_the_board_after_the_interrupt(self) -> None:
        _, _, calls, _ = self._run(
            ["--tour", "--serve", "--seconds", "20"], stop_after=2
        )
        self.assertEqual(calls, ["spawn", "terminate", "reap"])

    def test_once_plays_exactly_one_pass_and_still_holds_the_board(self) -> None:
        rc, rounds, calls, _ = self._run(
            ["--tour", "--once", "--serve", "--seconds", "20", "--port", "8792"]
        )
        self.assertEqual(rc, 0)
        self.assertEqual(rounds, [1])
        self.assertEqual(
            calls, ["spawn", "hold:http://127.0.0.1:8792/", "terminate", "reap"]
        )

    def test_fast_plays_exactly_one_pass_whatever_the_default_is(self) -> None:
        """The pin that keeps this suite finite: ``--fast`` alone, with the
        repeating default in force, plays once and returns."""
        rc, rounds, calls, _ = self._run(["--tour", "--serve", "--fast"])
        self.assertEqual(rc, 0)
        self.assertEqual(rounds, [1])
        self.assertEqual(calls, ["spawn", "terminate", "reap"])

    def test_an_interrupt_while_the_board_is_held_still_reaps_it(self) -> None:
        rc, rounds, calls, out = self._run(
            ["--tour", "--once", "--serve", "--seconds", "20"], hold_raises=True
        )
        self.assertEqual(rc, 0)
        self.assertEqual(rounds, [1])
        self.assertEqual(calls[-2:], ["terminate", "reap"])
        self.assertIn("stopped", out)

    def test_an_interrupt_in_the_very_first_round_exits_clean(self) -> None:
        rc, rounds, calls, out = self._run(
            ["--tour", "--serve", "--seconds", "20"], stop_after=1
        )
        self.assertEqual(rc, 0)
        self.assertEqual(rounds, [1])
        self.assertEqual(calls, ["spawn", "terminate", "reap"])
        self.assertIn("stopped", out)

    def test_the_banner_says_which_shape_the_run_is(self) -> None:
        _, _, _, repeating = self._run(
            ["--tour", "--serve", "--seconds", "20"], stop_after=1
        )
        _, _, _, single = self._run(["--tour", "--once", "--serve", "--seconds", "20"])
        self.assertIn("Ctrl-C", repeating)
        self.assertIn("ROUND", repeating)
        self.assertIn("One pass only", single)

    def test_run_tour_rounds_returns_after_one_round_when_not_repeating(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keel_demo.build_demo_project(root, with_plan=False)
            played = keel_demo.run_tour_rounds(
                root, fast=True, repeat=False, echo=False
            )
        self.assertEqual(played, 1)

    def test_run_tour_rounds_keeps_going_until_interrupted(self) -> None:
        """The repeating call has no exit but the interrupt — so this pins
        that the interrupt LEAVES the loop rather than being swallowed in
        it, and that nothing else ends it."""
        rounds: list[int] = []
        real_tour = keel_demo.run_tour

        def _stub(root, *, seconds=0.0, fast=False, echo=True, round_n=1):
            rounds.append(round_n)
            if round_n == 3:
                raise KeyboardInterrupt
            return keel_demo.tour_session_id(round_n)

        keel_demo.run_tour = _stub
        try:
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(KeyboardInterrupt):
                    keel_demo.run_tour_rounds(Path(tmp), fast=True, echo=False)
        finally:
            keel_demo.run_tour = real_tour
        self.assertEqual(rounds, [1, 2, 3])


class TestTheLoopStaysAvailableUnchanged(unittest.TestCase):
    def test_without_tour_the_loop_still_writes_its_own_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = keel_demo.main(["--dir", tmp, "--fast", "--cycles", "1"])
            self.assertEqual(rc, 0)
            plans = sorted(p.name for p in Path(tmp, ".keel", "plans").iterdir())
            self.assertEqual(plans, ["keel-plan-demo0000.md"])
            sessions = {
                e["session"] for e in _read_events(
                    Path(tmp, ".keel", "audit", "keel-audit.jsonl")
                ) if "session" in e
            }
            self.assertEqual(sessions, {"demo-0000"})


if __name__ == "__main__":
    unittest.main()
