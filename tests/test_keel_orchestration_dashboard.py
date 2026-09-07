"""The adopted orchestration dashboard's keel data layer (T121/T122).

The page itself is VENDORED - byte-for-byte the owner's predecessor-harness
viewer - so nothing here asserts on its internals beyond two landmarks that
prove the adoption did not rewrite it. What this file pins is keel's OWN
half: the data layer that feeds the page, the two bring-up fixes that made
real records digestible, and the T122 rule that keel truths are imported
from keel's viewer, never reimplemented.
"""
from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_dashboard  # noqa: E402
import keel_orchestration_dashboard as adopted  # noqa: E402

SOURCE = (REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py").read_text(
    encoding="utf-8"
)


def _iso(seconds_ago: float) -> str:
    moment = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=seconds_ago
    )
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _project(lines: list[dict]) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".keel" / "audit").mkdir(parents=True)
    (root / ".keel" / "plans").mkdir(parents=True)
    payload = "".join(json.dumps(line) + "\n" for line in lines)
    (root / ".keel" / "audit" / "keel-audit.jsonl").write_text(
        payload, encoding="utf-8"
    )
    (root / ".keel" / "plans" / "keel-plan-abcd1234.md").write_text(
        "# Session plan — abcd1234\n\n- [x] T1 done\n  Route: x\n  Accept: y\n",
        encoding="utf-8",
    )
    return tmp


class TestKeelTruthsAreImportedNotReimplemented(unittest.TestCase):
    """T122's single-place rule, pinned on object identity."""

    def test_arming_is_the_viewers_own_function(self) -> None:
        self.assertIs(adopted.keel_arming, keel_dashboard.arming)

    def test_session_liveness_is_the_viewers_own_function(self) -> None:
        self.assertIs(
            adopted.keel_session_liveness, keel_dashboard.session_liveness
        )

    def test_the_page_addition_prints_and_never_rederives(self) -> None:
        """The client block renders the payload's words; the liveness window
        constant must not exist page-side, or a second opinion could grow."""
        addition = SOURCE[SOURCE.index("KEEL ADDITION (T122) ---") :]
        self.assertIn("st.keel.liveness", addition)
        self.assertIn("lv.label", addition)
        self.assertNotIn("SESSION_LIVE_SECONDS", addition)


class TestReadStateCarriesTheKeelBlock(unittest.TestCase):
    def test_liveness_is_reported_for_the_newest_session(self) -> None:
        lines = [
            {"v": 1, "ts": _iso(9000), "event": "session_start", "session": "old-1"},
            {"v": 1, "ts": _iso(30), "event": "session_start", "session": "new-2"},
            {"v": 1, "ts": _iso(5), "event": "activity", "session": "new-2",
             "tool": "Bash", "detail": "x"},
        ]
        with _project(lines) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        self.assertEqual(state["keel"]["liveness"]["session"], "new-2")
        self.assertEqual(state["keel"]["liveness"]["state"], "live")

    def test_an_unarmed_project_reports_its_arming_honestly(self) -> None:
        with _project([]) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        arming = state["keel"]["arming"]
        self.assertIn("tier", arming)
        self.assertIn("armed", arming)
        self.assertFalse(arming["armed"])

    def test_an_empty_log_reports_no_liveness_rather_than_a_guess(self) -> None:
        with _project([]) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        self.assertIsNone(state["keel"]["liveness"])


class TestTheBringUpFixesHoldAgainstRealShapedRecords(unittest.TestCase):
    """The two defects live data exposed on 2026-08-12, now pinned."""

    def test_a_mapping_detail_is_served_as_a_string(self) -> None:
        """keel writes ``detail`` as a mapping on gate events; the page's
        escaper throws on objects inside a catch that renders as
        'disconnected' - so the layer stringifies, never drops."""
        lines = [
            {"v": 1, "ts": _iso(10), "event": "gate_block", "session": "s-1",
             "gate": "plan", "detail": {"switch": "KEEL_OVERRIDE"}},
        ]
        with _project(lines) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        served = [e for e in state["events"] if e["event"] == "gate_block"]
        self.assertEqual(len(served), 1)
        self.assertIsInstance(served[0]["detail"], str)
        self.assertIn("KEEL_OVERRIDE", served[0]["detail"])

    def test_a_flood_of_activity_cannot_starve_the_handoffs(self) -> None:
        """One last-400 window served pure activity and the page showed an
        empty round; two merged windows keep every recent hand-off."""
        lines = [
            {"v": 1, "ts": _iso(5000), "event": "handoff_start", "session": "s-1",
             "tool_use_id": f"t{i}", "subagent_type": "keel:executor",
             "description": f"task {i}"}
            for i in range(10)
        ]
        lines += [
            {"v": 1, "ts": _iso(4000 - i), "event": "activity", "session": "s-1",
             "tool": "Bash", "detail": f"cmd {i}"}
            for i in range(500)
        ]
        with _project(lines) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        kinds = [e["event"] for e in state["events"]]
        self.assertEqual(kinds.count("handoff_start"), 10)
        self.assertEqual(kinds.count("activity"), 400)

    def test_a_recorded_model_and_effort_compose_the_pages_own_tag(self) -> None:
        """T123 display half: the page's card tag reads one ``model`` word
        and its own persona table spells the idiom 'opus · high', so the
        served copy joins the record's two fields into it. A record with
        only one of the two keeps that one untouched, and a record with
        neither serves neither - absence is never dressed as a value."""
        lines = [
            {"v": 1, "ts": _iso(30), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "t1", "subagent_type": "keel:executor",
             "description": "both", "model": "sonnet", "effort": "default"},
            {"v": 1, "ts": _iso(20), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "t2", "subagent_type": "keel:executor",
             "description": "model only", "model": "opus", "effort": None},
            {"v": 1, "ts": _iso(10), "event": "handoff_start", "session": "s-1",
             "tool_use_id": "t3", "subagent_type": "keel:executor",
             "description": "neither"},
        ]
        with _project(lines) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        served = {e["description"]: e for e in state["events"]
                  if e["event"] == "handoff_start"}
        self.assertEqual(served["both"]["model"], "sonnet · default")
        self.assertEqual(served["model only"]["model"], "opus")
        self.assertNotIn("model", served["neither"])

    def test_events_carry_the_session_id_alias_without_losing_session(self) -> None:
        lines = [
            {"v": 1, "ts": _iso(10), "event": "session_start", "session": "s-9"},
        ]
        with _project(lines) as root:
            adopted.ROOT = root
            state = adopted.read_state()
        event = state["events"][0]
        self.assertEqual(event["session_id"], "s-9")
        self.assertEqual(event["session"], "s-9")


class TestTheVendoredPageIsAugmentedNeverRewritten(unittest.TestCase):
    def test_every_addition_is_fenced(self) -> None:
        self.assertGreaterEqual(SOURCE.count("KEEL ADDITION"), 5)

    def test_the_pages_own_landmarks_survive(self) -> None:
        for landmark in (
            'id="livedot"',
            "const PERSONAS={",
            'id="sessbtn"',
            "function renderFeed",
        ):
            self.assertIn(landmark, SOURCE)

    def test_the_feed_filter_intercepts_rather_than_edits(self) -> None:
        addition = SOURCE[SOURCE.index("KEEL ADDITION (T122) ---") :]
        self.assertIn("const _renderFeed=renderFeed;", addition)
        self.assertIn("renderFeed=evs=>_renderFeed(", addition)


class TestTheViewerNeverClaimsAPortItDoesNotOwn(unittest.TestCase):
    """T146: the walk has to actually walk.

    On Windows a second bind to a live listener SUCCEEDS while reuse is on,
    so the viewer printed a port whose answers came from another project's
    server. These run on every OS: after the fix the outcome is the same
    everywhere, which is the point - before it, this first test passed on
    POSIX and failed on Windows.
    """

    def test_it_walks_past_a_port_another_process_is_listening_on(self) -> None:
        import socket

        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # The holder sets reuse ON deliberately: that is exactly the shape of
        # a board started before this fix, and the case that must not shadow.
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        server = None
        try:
            server, port = adopted.bind_walk(taken, span=3)
            self.assertNotEqual(port, taken, "the viewer shadowed a live listener")
            self.assertIn(port, (taken + 1, taken + 2))
        finally:
            if server is not None:
                server.server_close()
            held.close()

    def test_it_takes_the_port_it_asked_for_when_that_port_is_free(self) -> None:
        import socket

        scout = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        scout.bind(("127.0.0.1", 0))
        free = scout.getsockname()[1]
        scout.close()
        server, port = adopted.bind_walk(free, span=3)
        try:
            self.assertEqual(port, free)
        finally:
            server.server_close()

    def test_a_walk_with_nowhere_to_go_exits_rather_than_serving(self) -> None:
        import socket

        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        try:
            with self.assertRaises(SystemExit) as caught:
                adopted.bind_walk(taken, span=1)
            self.assertIn("nothing is being served", str(caught.exception))
        finally:
            held.close()

    def test_reuse_is_off_only_where_it_is_the_hazard(self) -> None:
        """POSIX keeps reuse on - turning it off there would refuse a restart
        while a previous socket sits in TIME_WAIT, which is a regression
        rather than a fix."""
        expected = os.name != "nt"
        self.assertEqual(adopted._OwnedPortServer.allow_reuse_address, expected)


class TestTheLedgerNameThePageAsksFor(unittest.TestCase):
    """T142: the page asks for ``plan-<sess8>.md``; keel's file is
    ``keel-plan-<sess8>.md``. Two features were dark for five letters."""

    def test_the_page_still_builds_the_name_this_alias_serves(self) -> None:
        """The premise, owned rather than borrowed: this bridge is only
        correct while the VENDORED page constructs that exact name. If the
        page's convention ever changes, this fails before the board does."""
        self.assertIn('"plan-"+(r.id||"").slice(0,8)+".md"', SOURCE)
        self.assertIn('"plan-"+(rounds[rIdx].id||"").slice(0,8)+".md"', SOURCE)

    def test_the_served_list_carries_both_names(self) -> None:
        with _project([]) as name:
            root = Path(name)
            adopted.ROOT = root
            archives = adopted.read_state()["plan_archives"]
        self.assertIn("keel-plan-abcd1234.md", archives)
        self.assertIn("plan-abcd1234.md", archives)

    def test_the_alias_resolves_to_the_real_ledger(self) -> None:
        with _project([]) as name:
            root = Path(name)
            adopted.ROOT = root
            by_alias = adopted.read_archive("plan-abcd1234.md")
            by_real = adopted.read_archive("keel-plan-abcd1234.md")
        self.assertIsNotNone(by_alias)
        self.assertIn("T1 done", by_alias)
        self.assertEqual(by_alias, by_real)

    def test_a_name_no_ledger_owns_is_refused(self) -> None:
        """The other direction: the endpoint answers for listed ledgers and
        for nothing else - traversal, absolute paths, a plausible-looking
        name with no file behind it."""
        with _project([]) as name:
            root = Path(name)
            adopted.ROOT = root
            for hostile in (
                "plan-99999999.md",
                "keel-plan-99999999.md",
                "../keel-policy.md",
                "..\\keel-policy.md",
                "/etc/passwd",
                "plan-abcd1234.txt",
                "",
            ):
                self.assertIsNone(
                    adopted.read_archive(hostile), f"served {hostile!r}"
                )

    def test_a_file_that_is_not_a_ledger_gets_no_alias(self) -> None:
        self.assertIsNone(adopted._archive_alias("keel-policy.md"))
        self.assertIsNone(adopted._archive_alias("keel-plan-abcd1234.txt"))
        self.assertEqual(
            adopted._archive_alias("keel-plan-abcd1234.md"), "plan-abcd1234.md"
        )


if __name__ == "__main__":
    unittest.main()
