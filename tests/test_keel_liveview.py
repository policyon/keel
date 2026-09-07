"""The live view starts itself, and may never cost a session (T144).

Three properties are load-bearing here and each is pinned in BOTH directions:
the switch is off unless a user said otherwise, the probe tells this
project's server from another project's, and no failure on this path can
reach the session hook. The last one is the reason the file exists: a viewer
is a convenience, and a convenience that can break a session start is a
defect no matter how well it works when it works.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_liveview as live  # noqa: E402
import keel_orchestration_dashboard as board  # noqa: E402
import keel_session  # noqa: E402
from keel_registry_guard import no_real_fleet_registry  # noqa: E402


def _project(policy_body: str | None = None) -> tempfile.TemporaryDirectory:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".keel").mkdir(parents=True)
    if policy_body is not None:
        (root / ".keel" / "keel-policy.md").write_text(
            "---\ntier: 2\n---\n\n# policy\n\n" + policy_body,
            encoding="utf-8",
        )
    return tmp


class TestTheSwitchIsOffUntilAUserSaysOtherwise(unittest.TestCase):
    def test_no_key_is_off(self) -> None:
        self.assertFalse(live.parse_autostart("# nothing here").on)

    def test_declared_on_is_on(self) -> None:
        setting = live.parse_autostart("## Live view\n\nautostart: on\n")
        self.assertTrue(setting.on)
        self.assertEqual(setting.reason, "declared on")

    def test_the_accepted_spellings_of_yes_and_no(self) -> None:
        for yes in ("on", "ON", "true", "Yes", "1"):
            self.assertTrue(live.parse_autostart(f"autostart: {yes}").on, yes)
        for no in ("off", "OFF", "false", "No", "0"):
            self.assertFalse(live.parse_autostart(f"autostart: {no}").on, no)

    def test_an_unreadable_value_is_off_and_says_so(self) -> None:
        setting = live.parse_autostart("autostart: perhaps\n")
        self.assertFalse(setting.on)
        self.assertIn("perhaps", setting.reason)

    def test_two_declarations_that_disagree_are_off(self) -> None:
        """Ambiguity is not a majority vote: a server nobody clearly asked
        for is a server that does not start."""
        setting = live.parse_autostart("autostart: on\nautostart: off\n")
        self.assertFalse(setting.on)
        self.assertIn("both", setting.reason)

    def test_prose_mentioning_the_key_does_not_arm_it(self) -> None:
        self.assertFalse(live.parse_autostart("write `autostart: on` to opt in").on)

    def test_the_file_is_read_past_its_frontmatter(self) -> None:
        with _project("## Live view\n\nautostart: on\n") as name:
            self.assertTrue(live.setting(Path(name), {}).on)

    def test_a_missing_arming_file_is_off(self) -> None:
        with _project(None) as name:
            setting = live.setting(Path(name), {})
        self.assertFalse(setting.on)
        self.assertEqual(setting.reason, "no arming file")

    def test_the_environment_switch_wins_in_both_directions(self) -> None:
        with _project("autostart: on\n") as name:
            root = Path(name)
            self.assertFalse(live.setting(root, {"KEEL_DASHBOARD": "off"}).on)
            self.assertTrue(live.setting(root, {"KEEL_DASHBOARD": "on"}).on)
            self.assertFalse(live.setting(root, {"KEEL_DASHBOARD": "maybe"}).on)


class TestIdentityNotMereLiveness(unittest.TestCase):
    def test_the_fingerprint_is_the_viewers_own_function(self) -> None:
        """One implementation of identity, or the hook and the page could
        disagree about whose board is on the port."""
        with _project(None) as name:
            self.assertEqual(live.fingerprint(name), board.root_fingerprint(name))

    def test_the_fingerprint_carries_no_path(self) -> None:
        with _project(None) as name:
            fp = board.root_fingerprint(name)
        self.assertEqual(len(fp), 16)
        self.assertNotIn(Path(name).name, fp)
        self.assertTrue(all(c in "0123456789abcdef" for c in fp))

    def test_the_same_directory_spelled_differently_is_the_same_project(self) -> None:
        with _project(None) as name:
            self.assertEqual(
                board.root_fingerprint(name), board.root_fingerprint(name + "//.")
            )

    def test_the_served_state_carries_the_fingerprint(self) -> None:
        with _project(None) as name:
            root = Path(name)
            (root / ".keel" / "audit").mkdir(parents=True, exist_ok=True)
            (root / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
            (root / ".keel" / "audit" / "keel-audit.jsonl").write_text(
                "", encoding="utf-8"
            )
            board.ROOT = root
            served = board.read_state()["keel"]["root_fp"]
            self.assertEqual(served, board.root_fingerprint(root))

    def test_a_silent_port_and_a_foreign_server_are_different_answers(self) -> None:
        """A port nobody answers is ``silent``; a server that answers for
        another project is ``other`` - and neither is ever ``ours``."""
        foreign = live.Board(8770, "other", None, None, None)
        with mock.patch.object(live, "identify", return_value=foreign):
            self.assertIsNone(live.find_running(Path("."), "deadbeef"))
        with mock.patch.object(live, "identify", return_value=None):
            self.assertIsNone(live.find_running(Path("."), "deadbeef"))
        # ``probe`` still speaks the same three words over the same seam.
        with mock.patch.object(live, "identify", return_value=foreign):
            self.assertEqual(live.probe(8770, "deadbeef"), "other")
        with mock.patch.object(live, "identify", return_value=None):
            self.assertEqual(live.probe(8770, "deadbeef"), "silent")
        with mock.patch.object(
            live, "identify", return_value=live.Board(8770, "ours", 1, True, True)
        ):
            self.assertEqual(live.probe(8770, "deadbeef"), "ours")

    def test_an_answer_we_cannot_parse_is_other_not_silent(self) -> None:
        """A port that answers something unparseable is OCCUPIED. Reading it
        as silent would mean starting a second board for a project that
        already has one - the payload is 269KB today, so a cap set anywhere
        near it would make that the normal outcome on a busy project."""
        import http.client

        class _Response:
            status = 200

            def read(self, _n: int = 0) -> bytes:
                return b'{"keel": {"root_fp": "trunc'  # cut mid-JSON

        class _Conn:
            def __init__(self, *a: object, **k: object) -> None:
                pass

            def request(self, *a: object, **k: object) -> None:
                pass

            def getresponse(self) -> _Response:
                return _Response()

            def close(self) -> None:
                pass

        with mock.patch.object(http.client, "HTTPConnection", _Conn):
            self.assertEqual(live.probe(8770, "whatever"), "other")

    def test_a_json_array_body_is_other_not_silent(self) -> None:
        """A 200 response whose body is valid JSON but not a mapping (e.g. a
        bare array) is not our shape, but something IS listening - ``other``,
        never ``silent``, same as an unparseable body."""
        import http.client

        class _Response:
            status = 200

            def read(self, _n: int = 0) -> bytes:
                return b"[1, 2, 3]"

        class _Conn:
            def __init__(self, *a: object, **k: object) -> None:
                pass

            def request(self, *a: object, **k: object) -> None:
                pass

            def getresponse(self) -> _Response:
                return _Response()

            def close(self) -> None:
                pass

        with mock.patch.object(http.client, "HTTPConnection", _Conn):
            self.assertEqual(live.probe(8770, "whatever"), "other")

    def test_the_read_cap_is_far_above_a_real_payload(self) -> None:
        self.assertGreaterEqual(live.MAX_STATE_BYTES, 4_000_000)

    def test_the_recorded_hint_is_probed_first(self) -> None:
        seen: list[int] = []

        def fake(port: int, want: str, timeout: float = 0.0) -> live.Board | None:
            seen.append(port)
            return live.Board(port, "ours", 42, True, True) if port == 8775 else None

        with mock.patch.object(live, "identify", side_effect=fake):
            self.assertEqual(live.find_running(Path("."), "fp", hint=8775), 8775)
        self.assertEqual(seen, [8775])

    def test_the_scan_stops_at_its_deadline_rather_than_after_it(self) -> None:
        """The bound is a TOTAL: a scan that starts inside its budget must
        not run past it. Measured once at 5.64s against a 3.0s budget - the
        deadline was checked before the walk instead of before each probe."""
        import time as _time

        probes: list[int] = []

        def slow(port: int, want: str, timeout: float = 0.0) -> live.Board | None:
            probes.append(port)
            _time.sleep(0.05)
            return None

        with mock.patch.object(live, "identify", side_effect=slow):
            started = _time.monotonic()
            live.find_running(
                Path("."), "fp", deadline=_time.monotonic() + 0.12
            )
            elapsed = _time.monotonic() - started
        self.assertLess(elapsed, 0.5, "the walk outlived its deadline")
        self.assertLess(len(probes), 10, "every port was probed regardless")

    def test_the_scan_covers_the_servers_own_walk(self) -> None:
        seen: list[int] = []

        def fake(port: int, want: str, timeout: float = 0.0) -> live.Board | None:
            seen.append(port)
            return None

        with mock.patch.object(live, "identify", side_effect=fake):
            live.find_running(Path("."), "fp")
        self.assertEqual(seen, list(range(live.BASE_PORT, live.BASE_PORT + 10)))


class TestNoFailureOnThisPathReachesTheSession(unittest.TestCase):
    def test_off_never_spawns_anything(self) -> None:
        with _project("autostart: off\n") as name:
            with mock.patch.object(live, "_spawn") as spawn:
                outcome = live.ensure(Path(name), {})
        spawn.assert_not_called()
        self.assertEqual(outcome.action, "off")

    def test_a_refused_spawn_is_reported_not_raised(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(live, "find_running", return_value=None), \
                 mock.patch.object(
                     subprocess, "Popen", side_effect=OSError("no")
                 ):
                outcome = live.ensure(Path(name), {})
        self.assertEqual(outcome.action, "failed")
        self.assertIn("spawn refused", outcome.detail)

    def test_a_server_that_never_answers_is_unconfirmed_not_started(self) -> None:
        """Honest about what is known: the process was launched, and nothing
        has proved it is serving. It is never reported as running."""
        with _project("autostart: on\n") as name:
            with mock.patch.object(live, "find_running", return_value=None), \
                 mock.patch.object(live, "_spawn", return_value=(4321, None, "spawned")), \
                 mock.patch.object(live, "SPAWN_WAIT_S", 0.01), \
                 mock.patch.object(live, "SPAWN_POLL_S", 0.001):
                outcome = live.ensure(Path(name), {})
        self.assertEqual(outcome.action, "unconfirmed")
        self.assertIsNone(outcome.port)

    def test_an_exception_anywhere_inside_still_returns_an_outcome(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(
                live, "fingerprint", side_effect=RuntimeError("boom")
            ):
                outcome = live.ensure(Path(name), {})
        self.assertEqual(outcome.action, "failed")

    def test_an_unwritable_state_file_does_not_break_the_run(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(
                live.Path, "mkdir", side_effect=OSError("read-only")
            ):
                live.write_state(Path(name), 8770, 1, "fp")  # must not raise
        self.assertEqual(live.read_state(Path(name)), {})

    def test_an_already_running_board_is_left_alone(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(live, "find_running", return_value=8771), \
                 mock.patch.object(live, "_spawn") as spawn:
                outcome = live.ensure(Path(name), {})
        spawn.assert_not_called()
        self.assertEqual(outcome.action, "already")
        self.assertEqual(outcome.url, "http://127.0.0.1:8771")

    def test_the_spawn_chooses_a_free_port_rather_than_trusting_the_walk(
        self,
    ) -> None:
        """Windows lets a second process bind an address the first still
        holds (the server sets ``allow_reuse_address``), so the viewer's own
        +1 walk silently does not happen there: measured 2026-08-15, a second
        project's board "bound" 8770, answered nobody, and was invisible.
        The port is therefore chosen before the spawn and passed explicitly."""
        import socket

        held = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        taken = held.getsockname()[1]
        try:
            self.assertNotEqual(live.first_free_port(taken, 2), taken)
            self.assertEqual(live.first_free_port(taken, 2), taken + 1)
        finally:
            held.close()

    def test_no_free_port_is_reported_rather_than_spawned_into(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(live, "first_free_port", return_value=None), \
                 mock.patch.object(subprocess, "Popen") as popen:
                pid, port, detail = live._spawn(Path(name))
        popen.assert_not_called()
        self.assertIsNone(pid)
        self.assertIn("no free port", detail)

    def test_the_chosen_port_is_passed_to_the_viewer(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(live, "first_free_port", return_value=8773), \
                 mock.patch.object(subprocess, "Popen") as popen:
                popen.return_value.pid = 5
                pid, port, detail = live._spawn(Path(name))
        argv = popen.call_args[0][0]
        self.assertIn("--port", argv)
        self.assertEqual(argv[argv.index("--port") + 1], "8773")
        self.assertEqual(port, 8773)

    def test_the_spawn_passes_no_string_to_a_shell(self) -> None:
        with _project("autostart: on\n") as name:
            with mock.patch.object(subprocess, "Popen") as popen:
                popen.return_value.pid = 99
                live._spawn(Path(name))
        argv, kwargs = popen.call_args
        self.assertIsInstance(argv[0], list)
        self.assertEqual(argv[0][0], sys.executable)
        self.assertNotIn("shell", kwargs)


class TestTheSessionLineTellsTheTruth(unittest.TestCase):
    def test_off_yields_no_line_so_the_standing_pointer_stands(self) -> None:
        self.assertIsNone(live.line(live.Outcome("off", None, "x"), "[keel] live view"))

    def test_each_outcome_has_its_own_words(self) -> None:
        tag = "[keel] live view"
        started = live.line(live.Outcome("started", 8770, "x"), tag)
        already = live.line(live.Outcome("already", 8772, "x"), tag)
        failed = live.line(live.Outcome("failed", None, "viewer script not found"), tag)
        self.assertIn("started for this session", started)
        self.assertIn("8770", started)
        self.assertIn("already running", already)
        self.assertIn("8772", already)
        self.assertIn("viewer script not found", failed)
        self.assertIn(live.MANUAL_COMMAND, failed)

    def test_a_failed_autostart_still_names_the_manual_command(self) -> None:
        for action in ("failed", "unconfirmed"):
            text = live.line(live.Outcome(action, None, "why"), "[keel] live view")
            self.assertIn(live.MANUAL_COMMAND, text)


class TestTheRecordCarriesWhatHappened(unittest.TestCase):
    def _event(self, root: Path):
        return keel_session.KeelEvent(
            kind="session_start",
            cwd=root,
            session_id="7a73cbb8-cc4e-413a-b8f6-9ef3f02d7427",
            raw={"session_id": "7a73cbb8-cc4e-413a-b8f6-9ef3f02d7427"},
        )

    def test_a_record_without_an_outcome_is_byte_for_byte_the_old_shape(self) -> None:
        """Additive means additive: the caller that passes nothing gets the
        record every existing reader already parses."""
        with _project(None) as name:
            root = Path(name)
            self.assertNotIn("live_view", keel_session.start_record(self._event(root)))

    def test_the_outcome_is_recorded_when_there_is_one(self) -> None:
        with _project(None) as name:
            root = Path(name)
            record = keel_session.start_record(
                self._event(root), live.Outcome("started", 8770, "started for this session")
            )
        self.assertEqual(record["live_view"]["action"], "started")
        self.assertEqual(record["live_view"]["port"], 8770)
        self.assertEqual(record["event"], "session_start")

    def test_an_off_session_records_that_it_was_off(self) -> None:
        with _project(None) as name:
            record = keel_session.start_record(
                self._event(Path(name)), live.Outcome("off", None, "not declared")
            )
        self.assertEqual(record["live_view"]["action"], "off")
        self.assertNotIn("port", record["live_view"])

    def test_the_record_still_serialises(self) -> None:
        with _project(None) as name:
            record = keel_session.start_record(
                self._event(Path(name)), live.Outcome("failed", None, "spawn refused: OSError")
            )
        json.loads(json.dumps(record))


class TestOffIsByteIdenticalToTheFeatureNeverHavingExisted(unittest.TestCase):
    """T144: a user who declined the feature must see EXACTLY what they would
    have seen from an edition that never had this module at all - stdout is
    the contract that must not move, even though the audit record (a
    different reader, for a different purpose) is allowed to."""

    def _event(self, root: Path):
        return keel_session.KeelEvent(
            kind="session_start",
            cwd=root,
            session_id="7a73cbb8-cc4e-413a-b8f6-9ef3f02d7427",
            raw={"session_id": "7a73cbb8-cc4e-413a-b8f6-9ef3f02d7427"},
        )

    def test_autostart_off_matches_the_feature_being_absent_byte_for_byte(self) -> None:
        """Runs the declined-off path and the feature-unreachable path (the
        shape ``live_view_autostart`` returning None takes) through the SAME
        session entry point and asserts the two stdout strings are equal and
        non-empty - a user who said no must see the same thing as a user
        whose edition never had the option to say no to."""
        with no_real_fleet_registry():
            with _project("autostart: off\n") as off_name:
                off_stream = io.StringIO()
                keel_session.run(self._event(Path(off_name)), stdout=off_stream, env={})
                off_text = off_stream.getvalue()

            with _project("autostart: off\n") as absent_name:
                with mock.patch.object(keel_session, "live_view_autostart", return_value=None):
                    absent_stream = io.StringIO()
                    keel_session.run(
                        self._event(Path(absent_name)), stdout=absent_stream, env={}
                    )
                    absent_text = absent_stream.getvalue()

        self.assertEqual(off_text, absent_text)
        self.assertTrue(off_text)

    def test_the_two_paths_are_not_trivially_the_same_by_construction(self) -> None:
        """Proves the equality above is not vacuous: the AUDIT record - never
        read by the byte-identical assertion above - does carry the
        difference stdout is not allowed to. The declined-off run's
        ``session_start`` line names ``live_view``; the run standing in for
        the feature being unreachable does not."""
        with no_real_fleet_registry():
            with _project("autostart: off\n") as off_name:
                off_root = Path(off_name)
                keel_session.run(self._event(off_root), stdout=io.StringIO(), env={})
                off_audit = (off_root / ".keel" / "audit" / "keel-audit.jsonl").read_text(
                    encoding="utf-8"
                )

            with _project("autostart: off\n") as absent_name:
                absent_root = Path(absent_name)
                with mock.patch.object(keel_session, "live_view_autostart", return_value=None):
                    keel_session.run(self._event(absent_root), stdout=io.StringIO(), env={})
                absent_audit = (absent_root / ".keel" / "audit" / "keel-audit.jsonl").read_text(
                    encoding="utf-8"
                )

        self.assertIn("live_view", off_audit)
        self.assertNotIn("live_view", absent_audit)


class TestABoardOutlivesItsProject(unittest.TestCase):
    """T147: a board whose project is gone is REPORTED, never reaped.

    MEASURED 2026-08-16 before any of this was written: a board whose
    directory was deleted underneath it keeps answering 200 with the same
    name and the same fingerprint, and from outside it is indistinguishable
    from a quiet unarmed project. So the board must state what only it knows,
    and every refusal below exists because a wrong guess here ends somebody
    else's live window.
    """

    def test_the_served_state_says_whether_its_project_still_exists(self) -> None:
        """The three facts only the serving process holds."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".keel").mkdir()
            (root / ".keel" / "keel-audit.jsonl").write_text("", encoding="utf-8")
            board.ROOT = str(root)
            keel = board.read_state()["keel"]
            self.assertEqual(keel["pid"], __import__("os").getpid())
            self.assertTrue(keel["root_present"])
            self.assertTrue(keel["adopted"])

    def test_a_deleted_project_reports_root_present_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            gone = Path(tmp) / "was-here"
            gone.mkdir()
            board.ROOT = str(gone)
        # the temporary directory is now removed, exactly as a deleted project
        keel = board.read_state()["keel"]
        self.assertFalse(keel["root_present"])
        self.assertFalse(keel["adopted"])

    def test_only_an_explicit_false_is_stale(self) -> None:
        """A board too old to answer the question is UNKNOWN, never stale -
        the difference between reporting a fact and inventing one."""
        self.assertTrue(live.Board(8771, "other", 9, False, False).stale)
        self.assertFalse(live.Board(8771, "other", 9, None, None).stale)
        self.assertFalse(live.Board(8771, "ours", 9, False, False).stale)
        self.assertFalse(live.Board(8771, "other", 9, True, True).stale)

    def test_the_walk_reports_what_it_saw_and_the_line_names_the_command(self) -> None:
        stale = live.Board(8772, "other", 4242, False, False)

        def fake(port: int, want: str, timeout: float = 0.0) -> live.Board | None:
            if port == 8772:
                return stale
            return live.Board(port, "ours", 7, True, True) if port == 8773 else None

        seen: list[live.Board] = []
        with mock.patch.object(live, "identify", side_effect=fake):
            self.assertEqual(live.find_running(Path("."), "fp", sightings=seen), 8773)
        self.assertIn(stale, seen)
        text = live.stale_note(tuple(b for b in seen if b.stale))
        self.assertIn("8772", text)
        self.assertIn("4242", text)
        self.assertIn(live.stop_command(4242), text)
        self.assertIn("never ends them", text)

    def test_nothing_is_said_when_nothing_is_stale(self) -> None:
        """A line that says "0 stale" every session is a line nobody reads."""
        self.assertEqual(live.stale_note(()), "")

    def test_stop_refuses_a_board_serving_another_project(self) -> None:
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 111, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(
                     live, "identify",
                     return_value=live.Board(8770, "other", 222, True, True),
                 ), \
                 mock.patch.object(live.os, "kill") as killed:
                result = live.stop(root)
        self.assertEqual(result.action, "refused")
        self.assertIn("another project", result.detail)
        killed.assert_not_called()

    def test_stop_refuses_a_board_that_does_not_name_its_own_process(self) -> None:
        """The recorded pid is a HINT (see write_state); keel will not signal
        a process on the strength of a hint, and hands it to the human with
        its provenance instead."""
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 111, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(
                     live, "identify",
                     return_value=live.Board(8770, "ours", None, True, True),
                 ), \
                 mock.patch.object(live.os, "kill") as killed:
                result = live.stop(root)
        self.assertEqual(result.action, "refused")
        self.assertIn("111", result.detail)
        self.assertIn("may be stale", result.detail)
        killed.assert_not_called()

    def test_stop_does_nothing_when_nothing_is_recorded_or_listening(self) -> None:
        with _project("autostart: on\n") as name:
            root = Path(name)
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(live.os, "kill") as killed:
                nothing_recorded = live.stop(root)
                live.write_state(root, 8770, 111, "ours-fp")
                with mock.patch.object(live, "identify", return_value=None), \
                     mock.patch.object(live, "port_is_free", return_value=True):
                    nothing_listening = live.stop(root)
        self.assertEqual(nothing_recorded.action, "none")
        self.assertEqual(nothing_listening.action, "none")
        killed.assert_not_called()

    def test_stop_ends_this_projects_own_board_and_confirms_it(self) -> None:
        """Confirmed by a REFUSED connection - the only unambiguous answer."""
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 999, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(
                     live, "identify",
                     return_value=live.Board(8770, "ours", 999, True, True),
                 ), \
                 mock.patch.object(live, "port_is_free", return_value=True), \
                 mock.patch.object(live.os, "kill") as killed:
                result = live.stop(root)
        self.assertEqual(result.action, "stopped", result.detail)
        killed.assert_called_once()
        self.assertEqual(killed.call_args.args[0], 999)

    def test_a_stop_that_does_not_take_is_a_failure_not_a_success(self) -> None:
        """The port still held after the signal is the silent-failure shape
        this whole file exists to refuse."""
        alive = live.Board(8770, "ours", 999, True, True)
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 999, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(live, "identify", return_value=alive), \
                 mock.patch.object(live, "port_is_free", return_value=False), \
                 mock.patch.object(live.os, "kill"), \
                 mock.patch.object(live, "STOP_WAIT_S", 0.3):
                result = live.stop(root)
        self.assertEqual(result.action, "failed")
        self.assertIn("may still be serving", result.detail)

    def test_a_board_too_slow_to_answer_is_never_reported_as_stopped(self) -> None:
        """The finding this fixture exists for: a signalled process that is
        slow to die and one that ignored the signal look IDENTICAL to a
        probe. Only a refusal is proof, so "cannot tell" must end as failed,
        never as a success-shaped sentence and never as exit 0."""
        alive = live.Board(8770, "ours", 999, True, True)
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 999, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(live, "identify", return_value=alive), \
                 mock.patch.object(live, "port_is_free", return_value=None), \
                 mock.patch.object(live.os, "kill"), \
                 mock.patch.object(live, "STOP_WAIT_S", 0.3):
                result = live.stop(root)
        self.assertEqual(result.action, "failed")
        self.assertIn("999", result.detail)

    def test_a_port_that_neither_answers_nor_refuses_is_not_called_empty(self) -> None:
        """Before the kill, the same ambiguity: silence is not absence, so
        nothing is signalled and the reason says which question was unclear."""
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, 8770, 999, "ours-fp")
            with mock.patch.object(live, "fingerprint", return_value="ours-fp"), \
                 mock.patch.object(live, "identify", return_value=None), \
                 mock.patch.object(live, "port_is_free", return_value=None), \
                 mock.patch.object(live.os, "kill") as killed:
                result = live.stop(root)
        self.assertEqual(result.action, "refused")
        self.assertIn("nor refused", result.detail)
        killed.assert_not_called()

    def test_port_is_free_answers_three_ways_and_never_guesses(self) -> None:
        """Held, free, and cannot-tell - the first two against real sockets.

        MEASURED 2026-08-16 on this project's machine: a loopback port with
        nobody on it TIMES OUT instead of refusing, because the firewall
        drops the packet. A "free means refused" test would never say free
        here, so freedom is proven by BINDING rather than by being turned
        away - which is why the free case below is a real socket and not a
        mock that would have agreed with either design.
        """
        import socket as _socket

        held = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        try:
            held.bind(("127.0.0.1", 0))
            held.listen(1)
            taken = held.getsockname()[1]
            self.assertIs(live.port_is_free(taken), False, "a held port is not free")
        finally:
            held.close()
        self.assertIs(live.port_is_free(taken), True, "a released port is free")

        class _Unclear:
            """Not accepted, and not bindable either: the third answer."""

            def settimeout(self, _t: float) -> None:
                pass

            def connect(self, _a: object) -> None:
                raise TimeoutError("nobody answered in time")

            def bind(self, _a: object) -> None:
                raise OSError("and nobody will let us have it either")

            def close(self) -> None:
                pass

        with mock.patch.object(_socket, "socket", lambda *a, **k: _Unclear()):
            self.assertIsNone(live.port_is_free(8770))

    def _slow_board_on(self, port: int, recorded: int | None):
        """A board that only answers the patient ask, and the recorded hint."""
        def only_the_patient_ask(probed: int, want: str, timeout: float = 0.0):
            if probed == port and timeout >= live.CONFIRM_TIMEOUT_S:
                return live.Board(port, "ours", 55, True, True)
            return None

        return only_the_patient_ask, recorded

    def test_a_slow_board_of_ours_is_not_answered_with_a_second_server(self) -> None:
        """A busy board answers the quarter-second walk with silence. Taking
        that as absence starts a SECOND board for a project that already has
        one - on another port, so nothing about binding prevents it."""
        ask, recorded = self._slow_board_on(8773, 8773)
        with _project("autostart: on\n") as name:
            root = Path(name)
            live.write_state(root, recorded, 55, "fp")
            with mock.patch.object(live, "fingerprint", return_value="fp"), \
                 mock.patch.object(live, "identify", side_effect=ask), \
                 mock.patch.object(live, "_occupied_ports", return_value=[8773]), \
                 mock.patch.object(live, "_spawn") as spawned:
                outcome = live.ensure(root)
        spawned.assert_not_called()
        self.assertEqual(outcome.action, "already")
        self.assertEqual(outcome.port, 8773)

    def test_a_slow_board_on_an_UNRECORDED_port_is_found_too(self) -> None:
        """The round-2 finding: a hint that is stale, corrupt or absent must
        not turn a busy board of ours into a second board of ours. Occupancy
        is settled by bind, so the slow ask reaches ports no hint named."""
        ask, _ = self._slow_board_on(8776, None)
        with _project("autostart: on\n") as name:
            root = Path(name)  # no state file at all: nothing was recorded
            with mock.patch.object(live, "fingerprint", return_value="fp"), \
                 mock.patch.object(live, "identify", side_effect=ask), \
                 mock.patch.object(live, "_occupied_ports", return_value=[8776]), \
                 mock.patch.object(live, "_spawn") as spawned:
                outcome = live.ensure(root)
            # read INSIDE the project's lifetime: the state file goes with it
            self.assertEqual(
                live.read_state(root).get("port"), 8776, "the hint is corrected"
            )
        spawned.assert_not_called()
        self.assertEqual(outcome.action, "already")
        self.assertEqual(outcome.port, 8776)

    def test_a_port_already_known_to_be_another_projects_is_not_asked_twice(self) -> None:
        asked: list[tuple[int, float]] = []

        def record(port: int, want: str, timeout: float = 0.0):
            asked.append((port, timeout))
            return live.Board(port, "other", 1, True, True) if port == 8771 else None

        with _project("autostart: on\n") as name:
            root = Path(name)
            with mock.patch.object(live, "fingerprint", return_value="fp"), \
                 mock.patch.object(live, "identify", side_effect=record), \
                 mock.patch.object(live, "_occupied_ports", return_value=[8771]), \
                 mock.patch.object(live, "_spawn", return_value=(None, None, "no")):
                live.ensure(root)
        slow_asks = [port for port, timeout in asked if timeout >= live.CONFIRM_TIMEOUT_S]
        self.assertEqual(slow_asks, [], "it already answered, and it is not ours")

    def test_the_confirming_pass_is_bounded_as_a_total(self) -> None:
        """A full range of foreign boards must cost the confirming pass its
        BUDGET, not one slow ask per occupied port.

        WHAT IS MEASURED. Every port in the range is occupied and every ask
        answers silence, so ``ensure`` reaches the confirming pass with ten
        candidates and no reason of its own to stop early. The pass checks
        its total before EACH ask - the distinction SCAN_BUDGET_S was
        measured into existence by, where a scan begun inside its budget ran
        to completion outside it - so it must stop part-way down that list.
        Unbounded, this is ten asks at CONFIRM_TIMEOUT_S: the ten seconds of
        session start this whole path exists to prevent.

        WHY THE BOUND IS WHAT IT IS, and why it is no longer a wall-clock
        second. Until 2026-09-02 this test asserted that the WHOLE of
        ``ensure`` finished in under 1.0s. That number is SCAN_BUDGET_S
        itself - the budget of the walk that runs BEFORE the pass under test
        - so the assertion only held while the thirteen fake asks in front
        of it stayed far cheaper than the code is allowed to let them be. On
        GitHub's macOS runner a 0.05s sleep does not cost 0.05s, the walk
        alone spent the whole second, and the test failed 17 of 17 runs on a
        board that was behaving perfectly: it measured the runner.

        So the cost of one ask is MEASURED here, on the machine running the
        test - ``per_ask``, the cheapest ask this run actually made - and
        every bound below is stated as a multiple of it, over the pass alone:

          * the pass may make at most ``budget / per_ask + 1`` asks: those
            that fit inside the total, plus the one that was already in
            flight when it ran out;
          * it must make FEWER asks than there are candidates, on any
            machine - the assertion that fails if the total stops being
            checked before each ask;
          * and it may span at most ``budget + 2 * worst_ask``: the total,
            plus that in-flight ask, plus one ask of slack for a scheduler
            that suspends this process mid-loop.

        All three scale with the machine, and none of them can be satisfied
        by a pass that walks all ten candidates - which is what keeps this a
        test of the bound rather than of the clock.
        """
        ask_cost_s = 0.05
        # Two asks fit inside this; the third is the one in flight when the
        # total runs out. Expressed as a multiple of the fake ask's own cost
        # so the two numbers cannot drift apart.
        budget_s = 2.5 * ask_cost_s
        # (timeout asked for, start, end) per ask. The timeout is what tells
        # the walk's asks (PROBE_TIMEOUT_S, left at this stub's default) from
        # the confirming pass's asks (CONFIRM_TIMEOUT_S), the same
        # discriminator the test above this one uses.
        asks: list[tuple[float, float, float]] = []

        def slow(port: int, want: str, timeout: float = 0.0):
            started = time.monotonic()
            time.sleep(ask_cost_s)
            asks.append((timeout, started, time.monotonic()))
            return None

        candidates = list(range(8770, 8780))
        with _project("autostart: on\n") as name:
            root = Path(name)
            with mock.patch.object(live, "fingerprint", return_value="fp"), \
                 mock.patch.object(live, "identify", side_effect=slow), \
                 mock.patch.object(live, "_occupied_ports", return_value=candidates), \
                 mock.patch.object(live, "CONFIRM_BUDGET_S", budget_s), \
                 mock.patch.object(live, "_spawn", return_value=(None, None, "no port")):
                live.ensure(root)

        self.assertTrue(asks, "nothing was asked at all: the pass never ran")
        per_ask = min(end - start for _, start, end in asks)
        confirming = [
            (start, end)
            for timeout, start, end in asks
            if timeout >= live.CONFIRM_TIMEOUT_S
        ]
        self.assertLess(
            len(confirming),
            len(candidates),
            f"the confirming pass asked all {len(candidates)} occupied ports: its "
            f"total did nothing, so a full range costs {len(candidates)} x "
            f"CONFIRM_TIMEOUT_S ({len(candidates) * live.CONFIRM_TIMEOUT_S:.0f}s) "
            "of session start",
        )
        allowed = int(budget_s / per_ask) + 1
        self.assertLessEqual(
            len(confirming),
            allowed,
            f"{len(confirming)} confirming asks against a {budget_s:.3f}s total at a "
            f"measured {per_ask:.3f}s per ask - at most {allowed} fit (those inside "
            "the total, plus the one in flight when it ran out)",
        )
        if confirming:
            spanned = confirming[-1][1] - confirming[0][0]
            worst = max(end - start for start, end in confirming)
            ceiling = budget_s + 2 * worst
            self.assertLessEqual(
                spanned,
                ceiling,
                f"the confirming pass spanned {spanned:.3f}s against a {budget_s:.3f}s "
                f"total, with a measured worst ask of {worst:.3f}s (ceiling "
                f"{ceiling:.3f}s): the total is not being checked before each ask",
            )

    def test_occupancy_by_bind_sees_a_holder_that_set_reuse_as_well(self) -> None:
        """The risk the reviewer raised, measured instead of argued.

        If a holder's SO_REUSEADDR could make it invisible here, that port
        would drop off the candidate list and the duplicate board would come
        back. It cannot: the option governs the socket attempting the SECOND
        bind, which is the T146 failure seen from the other side - there the
        second SERVER set it and bound around a live board; this probe never
        sets it. Both holders below are seen, and a released port is not.
        """
        import socket as _socket

        for reuse in (False, True):
            held = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            try:
                if reuse:
                    held.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
                held.bind(("127.0.0.1", 0))
                held.listen(1)
                port = held.getsockname()[1]
                self.assertIn(
                    port, live._occupied_ports(port, 1), f"holder with reuse={reuse}"
                )
            finally:
                held.close()
        self.assertNotIn(port, live._occupied_ports(port, 1), "released is free")

    def test_the_stale_sentence_never_claims_to_be_a_total(self) -> None:
        text = live.stale_note((live.Board(8772, "other", 7, False, False),))
        self.assertIn("not a count of the range", text)
        self.assertIn(live.STATUS_COMMAND, text)

    def test_the_stop_command_named_is_the_one_this_platform_runs(self) -> None:
        text = live.stop_command(1234)
        self.assertIn("1234", text)
        self.assertEqual(text.startswith("taskkill"), __import__("os").name == "nt")


if __name__ == "__main__":
    unittest.main()
