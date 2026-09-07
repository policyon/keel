"""T340 - the board's first write verb: a one-click restart from the stale chip.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` as an imported module
          (the pure guard, the argv-building seam, the socket-close seam)
          and as TEXT (the page-side markup and JavaScript the T168/T322/T334
          suites already extract in this style). A live loopback HTTP server
          is bound with ``bind_walk`` for the handler-level cases - the
          endpoint's contract is that a request either changes nothing or
          performs ONE fixed, request-independent action, and that action
          (``os.execv``) is patched out through the module's own test seam
          (``_EXECV``) before any success case runs, so no case here can
          ever end the test process.
Emits   : unittest results only.
Writes  : nothing outside a temporary Node script and temporary sockets it
          creates and removes/closes.
Argv    : none.

What a Python suite cannot do here
-----------------------------------
The click, the in-progress button state and the reload-after-poll all run in
the BROWSER; this file pins that the markup and script exist, are wired to
the right elements, and (via a real Node process, ``node --check``-equivalent
execution of the extracted block) parse and run as JavaScript - never that a
browser drew or clicked anything. See the sibling T168/T322/T334 suites for
the same boundary stated about their own client-side markers.

Failure policy
---------------
An environment missing ``node`` SKIPS the page-side execution cases and says
so — one line on stderr from ``keel_node.announce_once`` plus the reason on
every skipped case. It used to fail them closed; ruled 2026-09-01 (BL17) so a
clone on a machine without node reaches green, with audibility kept rather
than traded away.
"""

from __future__ import annotations

import http.client
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from keel_node import NODE, SKIP_REASON, announce_once

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_orchestration_dashboard as board  # noqa: E402

announce_once()

BOARD_SOURCE = (REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py").read_text(
    encoding="utf-8"
)


# ---- KEEL ADDITION (T627, BL59): the standing instrument ----
# WHAT THIS IS FOR. This file schedules real ``threading.Timer`` objects in
# the TEST RUNNER's own process (``schedule_restart`` directly, and the live
# handler indirectly on every authorized POST). A timer that outlives the
# test that caused it fires LATER, into a module whose seams the fixture has
# already restored - ``_request_restart`` reads the module global ``_SERVER``
# when it FIRES, not when it was scheduled. BL59 records the (still
# unproven) suspicion that exactly such a stray is what ends a full-discovery
# run mid-suite, exit 0, no "Ran N tests" line: the real ``_EXIT`` is
# ``os._exit(0)``, and a process ended that way prints no summary and reports
# success.
#
# WHY IT IS A PER-TEST CLEANUP AND NOT AN ``atexit`` HOOK. An atexit report
# arrives after every test has already passed, names no test, and - if the
# stray has already called ``os._exit`` - never runs at all, because
# ``os._exit`` skips atexit. A snapshot taken in ``setUp`` and compared in an
# ``addCleanup`` fails THE CASE THAT LEAKED, by id, in the runner's own
# output, while the timer is still pending and therefore still harmless.
# ``addCleanup`` (not ``tearDown``) so it runs on the error and failure paths
# too, and because it is registered FIRST it runs LAST - after the fixture
# cleanups a case registered later, which is where the cancelling belongs.
#
# WHAT IT CANNOT SEE: a timer scheduled by a module OTHER than this file's
# subject (the snapshot is per-test, so anything already running when a case
# starts is somebody else's), and a timer created after this cleanup runs.
def _timer_ids_now() -> set:
    return {
        id(t) for t in threading.enumerate() if isinstance(t, threading.Timer)
    }


def _describe_timer(timer: threading.Timer) -> str:
    function = getattr(timer, "function", None)
    name = getattr(function, "__name__", None) or repr(function)
    return f"{timer.name}(function={name}, still-pending={not timer.finished.is_set()})"


def stop_timer(timer: threading.Timer, timeout: float = 5.0) -> None:
    """Cancel ``timer`` and wait for its thread to actually end.

    ``cancel`` alone is not enough for a timer whose delay has already
    elapsed - the callback may be running right now - so the join is what
    makes "this test left nothing behind" a fact rather than a hope. An
    unstarted timer is cancelled but never joined; joining one raises.
    """
    timer.cancel()
    if timer.is_alive():
        timer.join(timeout)


class TimerLeakGuard(unittest.TestCase):
    """Base class for every case in this file: a case that leaves a live
    ``threading.Timer`` behind FAILS, and the failure names it."""

    def setUp(self) -> None:
        super().setUp()
        self._timers_at_start = _timer_ids_now()
        self.addCleanup(self._fail_if_a_timer_survived_this_test)

    def _fail_if_a_timer_survived_this_test(self) -> None:
        survivors = [
            t
            for t in threading.enumerate()
            if isinstance(t, threading.Timer)
            and t.is_alive()
            and id(t) not in self._timers_at_start
        ]
        if not survivors:
            return
        # Describe BEFORE cancelling (cancelling clears "still pending"),
        # then stop them HERE, before reporting: the point of failing early
        # is that the stray never reaches the tests that follow (or the
        # interpreter's own exit) - a report that leaves the timer running
        # would still let it end the runner.
        described = [_describe_timer(t) for t in survivors]
        for timer in survivors:
            stop_timer(timer)
        self.fail(
            f"live threading.Timer left behind by {self.id()}: "
            + "; ".join(described)
            + " - cancel and join the timer in an addCleanup; a stray "
            "restart timer can reach os._exit(0) after its test is over"
        )


class TestTheTimerLeakGuardIsItselfProven(TimerLeakGuard):
    """An instrument nobody has seen fail proves nothing. Both directions,
    on real timers: a case that leaks goes RED and the message names THAT
    case; a case that cancels and joins stays GREEN.

    The inner cases are run through a real ``TextTestRunner`` into a string
    buffer, so this file's own result is not touched by them.
    """

    def _run_case(self, case_class: type) -> unittest.TestResult:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(case_class)
        stream = io.StringIO()
        return unittest.TextTestRunner(stream=stream, verbosity=0).run(suite)

    def test_a_leaked_timer_fails_its_own_case_and_names_it(self) -> None:
        leaked: list[threading.Timer] = []
        # Registered BEFORE the inner case runs, so even a broken guard
        # cannot let the deliberately-leaked timer escape into this suite.
        self.addCleanup(lambda: [stop_timer(t) for t in leaked])

        class _LeakyCase(TimerLeakGuard):
            def test_leaves_a_timer_running(self_inner) -> None:  # noqa: N805
                timer = threading.Timer(300, lambda: None)
                timer.daemon = True
                timer.start()
                leaked.append(timer)

        result = self._run_case(_LeakyCase)
        self.assertEqual(result.testsRun, 1)
        self.assertEqual(len(result.errors), 0, result.errors)
        self.assertEqual(len(result.failures), 1, "the leak went unnoticed")
        case, message = result.failures[0]
        self.assertIn("live threading.Timer left behind", message)
        # The failure names the LEAKER - the case id, not this file at exit.
        self.assertIn("test_leaves_a_timer_running", message)
        self.assertIn(case.id(), message)
        self.assertIn("still-pending=True", message)
        # And it stopped what it found, rather than reporting and walking on.
        self.assertFalse(leaked[0].is_alive())

    def test_a_cancelled_and_joined_timer_leaves_the_case_green(self) -> None:
        class _TidyCase(TimerLeakGuard):
            def test_stops_its_timer(self_inner) -> None:  # noqa: N805
                timer = threading.Timer(300, lambda: None)
                timer.daemon = True
                timer.start()
                self_inner.addCleanup(stop_timer, timer)

        result = self._run_case(_TidyCase)
        self.assertEqual(result.testsRun, 1)
        self.assertTrue(result.wasSuccessful(), (result.failures, result.errors))

    def test_the_boards_own_pending_restart_timer_is_what_it_catches(self) -> None:
        """Not any old timer - the real thing, scheduled by the real
        ``schedule_restart`` and left pending exactly as a stray would be."""
        self.addCleanup(board.cancel_pending_restarts)

        class _LeakyRestartCase(TimerLeakGuard):
            def test_leaves_a_restart_pending(self_inner) -> None:  # noqa: N805
                board.schedule_restart(delay=300)

        result = self._run_case(_LeakyRestartCase)
        self.assertEqual(len(result.failures), 1, "a stray restart timer passed")
        _, message = result.failures[0]
        self.assertIn("live threading.Timer left behind", message)
        self.assertIn("function=_request_restart", message)
        self.assertEqual(board.pending_restart_timers(), [])

    def test_a_case_that_starts_with_somebody_elses_timer_running_is_not_blamed(
        self,
    ) -> None:
        """The snapshot is per-case: a timer already running when a case
        begins belongs to somebody else and must not fail this one."""
        foreign = threading.Timer(300, lambda: None)
        foreign.daemon = True
        foreign.start()
        self.addCleanup(stop_timer, foreign)

        class _InnocentCase(TimerLeakGuard):
            def test_touches_no_timer(self_inner) -> None:  # noqa: N805
                self_inner.assertTrue(foreign.is_alive())

        result = self._run_case(_InnocentCase)
        self.assertTrue(result.wasSuccessful(), (result.failures, result.errors))
        self.assertTrue(foreign.is_alive(), "an innocent case stopped a live timer")


class TestPendingRestartTimersAreReachableAndCancellable(TimerLeakGuard):
    """KEEL ADDITION (T627, BL59): the module seam the fixture needs - the
    handler drops the timer handle, so the module keeps one."""

    def setUp(self) -> None:
        super().setUp()
        self.addCleanup(board.cancel_pending_restarts)

    def test_a_scheduled_restart_is_listed_while_it_is_pending(self) -> None:
        timer = board.schedule_restart(delay=300)
        self.addCleanup(stop_timer, timer)
        self.assertIn(timer, board.pending_restart_timers())

    def test_cancelling_stops_the_timer_and_strands_nothing(self) -> None:
        timer = board.schedule_restart(delay=300)
        self.addCleanup(stop_timer, timer)
        stranded = board.cancel_pending_restarts()
        self.assertEqual(stranded, [])
        self.assertFalse(timer.is_alive())
        self.assertEqual(board.pending_restart_timers(), [])

    def test_cancelling_with_nothing_pending_is_a_quiet_no_op(self) -> None:
        self.assertEqual(board.cancel_pending_restarts(), [])

    def test_a_cancelled_timer_never_calls_request_restart(self) -> None:
        called = threading.Event()
        original = board._request_restart
        self.addCleanup(setattr, board, "_request_restart", original)
        board._request_restart = called.set
        timer = board.schedule_restart(delay=0.05)
        self.addCleanup(stop_timer, timer)
        board.cancel_pending_restarts()
        self.assertFalse(called.wait(timeout=0.5))

    def test_the_registry_does_not_grow_without_bound(self) -> None:
        """A board left running for days schedules restarts it never keeps:
        dead timers are pruned on each new schedule, so the list stays the
        size of what is actually pending."""
        # The immediate timers below would otherwise call the REAL
        # ``_request_restart`` and set the module's restart flag; patched to
        # a no-op so this case changes nothing outside the registry.
        original = board._request_restart
        self.addCleanup(setattr, board, "_request_restart", original)
        board._request_restart = lambda: None
        for _ in range(5):
            timer = board.schedule_restart(delay=0)
            stop_timer(timer)
        live = board.schedule_restart(delay=300)
        self.addCleanup(stop_timer, live)
        self.assertLessEqual(len(board._RESTART_TIMERS), 2)


class TestTheRestartGuardIsAPureFunction(TimerLeakGuard):
    """``restart_authorized`` - every check, no side effect, no socket."""

    def test_a_correct_request_is_authorized(self) -> None:
        ok, reason = board.restart_authorized(
            "POST", board.RESTART_TOKEN, "127.0.0.1:8770"
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "")

    def test_localhost_without_a_port_is_also_loopback(self) -> None:
        ok, _ = board.restart_authorized("POST", board.RESTART_TOKEN, "localhost")
        self.assertTrue(ok)

    def test_get_is_refused_regardless_of_token_or_host(self) -> None:
        ok, reason = board.restart_authorized(
            "GET", board.RESTART_TOKEN, "127.0.0.1:8770"
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "method not allowed")

    def test_a_missing_token_is_refused(self) -> None:
        ok, reason = board.restart_authorized("POST", "", "127.0.0.1:8770")
        self.assertFalse(ok)
        self.assertIn("token", reason)

    def test_a_wrong_token_is_refused(self) -> None:
        ok, reason = board.restart_authorized(
            "POST", "0" * len(board.RESTART_TOKEN), "127.0.0.1:8770"
        )
        self.assertFalse(ok)
        self.assertIn("token", reason)

    def test_a_non_loopback_host_is_refused(self) -> None:
        for host in ("evil.example.com", "evil.example.com:8770", "", "0.0.0.0:8770"):
            with self.subTest(host=host):
                ok, reason = board.restart_authorized(
                    "POST", board.RESTART_TOKEN, host
                )
                self.assertFalse(ok)
                self.assertEqual(reason, "host is not loopback")

    def test_method_is_checked_before_token_or_host(self) -> None:
        """A GET with everything else wrong too still reports the METHOD
        failure - the order named in the module's own docstring."""
        ok, reason = board.restart_authorized("GET", "", "evil.example.com")
        self.assertFalse(ok)
        self.assertEqual(reason, "method not allowed")


class TestTheTokenIsAPerProcessSecretNotAConfigValue(TimerLeakGuard):
    def test_the_token_is_nonempty_hex_of_the_expected_length(self) -> None:
        token = board.RESTART_TOKEN  # keel-leak: ignore - reads the board's per-process token; holds no secret
        self.assertTrue(token)
        self.assertEqual(len(token), 64)  # secrets.token_hex(32)
        int(token, 16)  # raises if it is not hex

    def test_the_token_is_embedded_in_the_served_page_exactly_once(self) -> None:
        served = board.HTML.replace("__KEEL_RESTART_TOKEN__", board.RESTART_TOKEN)
        self.assertEqual(served.count(board.RESTART_TOKEN), 1)

    def test_the_placeholder_appears_exactly_once_in_the_static_html(self) -> None:
        self.assertEqual(board.HTML.count("__KEEL_RESTART_TOKEN__"), 1)


class TestTheReexecSeamBuildsTheFixedArgvOnly(TimerLeakGuard):
    """The one line no test may actually execute - patched through the
    module's own seam (``_EXECV``) rather than the shared ``os`` module, so
    every other test in this process keeps a real ``os.execv``."""

    def test_reexec_calls_the_same_interpreter_same_file_same_argv(self) -> None:
        # KEEL ADDITION (T443): this case pins the POSIX branch specifically
        # (``_EXECV``, never ``_SPAWN``) - ``_is_windows`` is forced False so
        # the assertion holds on a Windows development machine too, exactly
        # as it held before T443 split the two platforms apart.
        calls = []
        original = board._EXECV
        original_argv = board._ORIGINAL_ARGV
        original_is_windows = board._is_windows
        try:
            board._EXECV = lambda *a: calls.append(a)
            board._is_windows = lambda: False
            board._ORIGINAL_ARGV = ["keel_orchestration_dashboard.py", "--port", "8770"]
            board._reexec_same_process()
        finally:
            board._EXECV = original
            board._ORIGINAL_ARGV = original_argv
            board._is_windows = original_is_windows
        self.assertEqual(len(calls), 1)
        executable, argv = calls[0]
        self.assertEqual(executable, sys.executable)
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], board.PAGE_SOURCE)
        self.assertEqual(argv[2:], ["--port", "8770"])

    def test_reexec_takes_nothing_from_a_request(self) -> None:
        """The argv built is a function of ``_ORIGINAL_ARGV`` alone - calling
        it twice with the same seed produces the same call, whatever a
        handler thinks it is answering."""
        # KEEL ADDITION (T443): same reason as the case above - forced to
        # the POSIX branch so this holds on Windows too.
        calls = []
        original = board._EXECV
        original_is_windows = board._is_windows
        try:
            board._EXECV = lambda *a: calls.append(a)
            board._is_windows = lambda: False
            board._reexec_same_process()
            board._reexec_same_process()
        finally:
            board._EXECV = original
            board._is_windows = original_is_windows
        self.assertEqual(calls[0], calls[1])


class TestTheSocketIsClosedBeforeTheReexec(TimerLeakGuard):
    def test_the_live_servers_socket_is_closed(self) -> None:
        class _Fake:
            def __init__(self) -> None:
                self.closed = False
                self.socket = self

            def close(self) -> None:
                self.closed = True

        fake = _Fake()
        original = board._SERVER
        try:
            board._SERVER = fake
            board._close_server_socket()
        finally:
            board._SERVER = original
        self.assertTrue(fake.closed)

    def test_no_server_bound_is_a_quiet_no_op(self) -> None:
        original = board._SERVER
        try:
            board._SERVER = None
            board._close_server_socket()  # must not raise
        finally:
            board._SERVER = original

    def test_perform_restart_closes_before_it_reexecs(self) -> None:
        order = []
        original_close = board._close_server_socket
        original_exec = board._reexec_same_process
        try:
            board._close_server_socket = lambda: order.append("close")
            board._reexec_same_process = lambda: order.append("exec")
            board._perform_restart()
        finally:
            board._close_server_socket = original_close
            board._reexec_same_process = original_exec
        self.assertEqual(order, ["close", "exec"])


class TestScheduleRestartFiresOnADaemonTimer(TimerLeakGuard):
    """KEEL ADDITION (T443 follow-up): the timer's job changed - it now
    REQUESTS a restart (set the flag, call ``shutdown()``) rather than
    PERFORMING one (close the socket, re-exec/spawn) - see
    ``_request_restart``'s own comment for the race this split closes."""

    def test_it_calls_request_restart_after_the_delay(self) -> None:
        # KEEL ADDITION (T627, BL59): the timer this case creates is stopped
        # through addCleanup, registered the instant the timer exists, so it
        # is cancelled AND JOINED on the failure and error paths too - a tail
        # line after the last assertion would be skipped by exactly the run
        # that most needs it. The subject is unchanged: the timer is still a
        # daemon and still calls ``_request_restart`` after the delay.
        called = threading.Event()
        original = board._request_restart
        self.addCleanup(setattr, board, "_request_restart", original)
        board._request_restart = called.set
        timer = board.schedule_restart(delay=0)
        self.addCleanup(stop_timer, timer)
        self.assertTrue(timer.daemon)
        self.assertTrue(called.wait(timeout=5))

    def test_request_restart_sets_the_flag_and_shuts_down_but_never_closes_or_reexecs(
        self,
    ) -> None:
        """The timer thread must never touch the socket or the process
        image - only ``main()``, after ``serve_forever`` returns, may."""

        class _FakeServer:
            def __init__(self) -> None:
                self.shutdown_calls = 0

            def shutdown(self) -> None:
                self.shutdown_calls += 1

        fake = _FakeServer()
        original_server = board._SERVER
        original_flag = board._RESTART_REQUESTED
        original_close = board._close_server_socket
        original_exec = board._reexec_same_process
        close_calls: list[None] = []
        exec_calls: list[None] = []
        try:
            board._SERVER = fake
            board._RESTART_REQUESTED = False
            board._close_server_socket = lambda: close_calls.append(None)
            board._reexec_same_process = lambda: exec_calls.append(None)
            board._request_restart()
            self.assertTrue(board._RESTART_REQUESTED)
            self.assertEqual(fake.shutdown_calls, 1)
            self.assertEqual(close_calls, [])
            self.assertEqual(exec_calls, [])
        finally:
            board._SERVER = original_server
            board._RESTART_REQUESTED = original_flag
            board._close_server_socket = original_close
            board._reexec_same_process = original_exec

    def test_request_restart_with_no_server_bound_is_a_quiet_no_op_on_the_socket(
        self,
    ) -> None:
        original_server = board._SERVER
        original_flag = board._RESTART_REQUESTED
        try:
            board._SERVER = None
            board._RESTART_REQUESTED = False
            board._request_restart()  # must not raise
            self.assertTrue(board._RESTART_REQUESTED)
        finally:
            board._SERVER = original_server
            board._RESTART_REQUESTED = original_flag


class TestMainPerformsTheRestartOnlyAfterServeForeverReturns(TimerLeakGuard):
    """KEEL ADDITION (T443 follow-up): ``main()``'s post-loop branch - the
    other half of the split. A fake server whose ``serve_forever`` returns
    immediately stands in for the real accept loop, so this pins the branch
    without binding a socket or spawning/exec'ing anything real."""

    def _run_main_with(self, fake_server, restart_requested_after_serve: bool):
        """Runs the same shape ``main()`` runs, on THIS thread, against a
        fake server - the smallest slice that proves the ordering without
        parsing argv or binding a real port."""
        fake_server.serve_forever()
        board._RESTART_REQUESTED = restart_requested_after_serve
        if board._RESTART_REQUESTED:
            board._perform_restart()

    def test_a_requested_restart_performs_close_then_reexec_after_serve_returns(
        self,
    ) -> None:
        order: list[str] = []

        class _FakeServer:
            def serve_forever(self) -> None:
                order.append("serve")

        original_close = board._close_server_socket
        original_exec = board._reexec_same_process
        original_flag = board._RESTART_REQUESTED
        try:
            board._close_server_socket = lambda: order.append("close")
            board._reexec_same_process = lambda: order.append("exec")
            self._run_main_with(_FakeServer(), restart_requested_after_serve=True)
        finally:
            board._close_server_socket = original_close
            board._reexec_same_process = original_exec
            board._RESTART_REQUESTED = original_flag
        self.assertEqual(order, ["serve", "close", "exec"])

    def test_no_restart_requested_means_serve_forever_returning_does_nothing_else(
        self,
    ) -> None:
        order: list[str] = []

        class _FakeServer:
            def serve_forever(self) -> None:
                order.append("serve")

        original_close = board._close_server_socket
        original_exec = board._reexec_same_process
        original_flag = board._RESTART_REQUESTED
        try:
            board._close_server_socket = lambda: order.append("close")
            board._reexec_same_process = lambda: order.append("exec")
            self._run_main_with(_FakeServer(), restart_requested_after_serve=False)
        finally:
            board._close_server_socket = original_close
            board._reexec_same_process = original_exec
            board._RESTART_REQUESTED = original_flag
        self.assertEqual(order, ["serve"])


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class _LiveBoard:
    """A real bound-and-serving ``Handler`` on loopback, for exactly the
    handler-level cases the pure guard cannot cover by itself - the
    connection actually carries the ``Host`` and custom-header semantics
    ``restart_authorized`` is fed from ``BaseHTTPRequestHandler.headers``.

    ``os.execv`` is patched to a recorder for the LIFETIME of every instance,
    so a case that authorizes a restart cannot end this test process even on
    a mistake elsewhere in the file.
    """

    def __init__(self) -> None:
        self.execv_calls: list[tuple] = []
        # Restart timers still alive after ``close`` asked them to stop -
        # empty on every healthy run; see ``close``.
        self.stranded_timers: list = []
        self._original_execv = board._EXECV
        board._EXECV = lambda *a: self.execv_calls.append(a)
        # KEEL ADDITION (T443): this fixture's whole point is proving a
        # restart happens EXACTLY ONCE through the patched ``_EXECV`` - on
        # a real Windows machine ``_reexec_same_process`` would otherwise
        # take the Windows branch instead (``_SPAWN`` then a REAL,
        # unpatched ``os._exit(0)`` - which would kill this very test
        # process). Forced to the POSIX branch so the fixture's patched
        # seam is the one actually exercised, on every platform.
        self._original_is_windows = board._is_windows
        board._is_windows = lambda: False
        # A minimal project so a follow-up GET /api/state (the "did a
        # refusal change anything" probe) has something to read rather than
        # crashing on ``board.ROOT`` being ``None``.
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / ".keel" / "audit").mkdir(parents=True)
        (root / ".keel" / "plans").mkdir(parents=True)
        (root / ".keel" / "audit" / "keel-audit.jsonl").write_text("", encoding="utf-8")
        self._original_root = board.ROOT
        board.ROOT = str(root)
        port = _free_port()
        self.server, _ = board.bind_walk(port, span=1)
        self.port = self.server.server_address[1]
        self._original_server = board._SERVER
        board._SERVER = self.server
        # KEEL ADDITION (T443 follow-up): the request/perform split moved
        # "close the socket, re-exec" out of the timer thread and into
        # whatever thread called ``serve_forever`` - in production that is
        # ``main()``, on this thread that is the same shape, by hand, so the
        # fixture's patched ``_EXECV`` is still the one actually exercised
        # once a restart is requested and ``serve_forever`` returns.
        self._original_flag = board._RESTART_REQUESTED
        board._RESTART_REQUESTED = False

        def _serve_then_restart_if_requested() -> None:
            self.server.serve_forever()
            if board._RESTART_REQUESTED:
                board._perform_restart()

        self.thread = threading.Thread(
            target=_serve_then_restart_if_requested, daemon=True
        )
        self.thread.start()

    def request(self, method: str, path: str, headers: dict | None = None) -> http.client.HTTPResponse:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            host_header = (headers or {}).pop("Host", None) if headers else None
            headers = dict(headers or {})
            conn.putrequest(method, path, skip_host=host_header is not None)
            if host_header is not None:
                conn.putheader("Host", host_header)
            for key, value in headers.items():
                conn.putheader(key, value)
            conn.putheader("Content-Length", "0")
            conn.endheaders()
            resp = conn.getresponse()
            resp.read()
            return resp
        finally:
            conn.close()

    def close(self) -> None:
        # KEEL ADDITION (T627, BL59): FIRST, before anything else, stop the
        # restart timers this fixture caused. Nobody here ever held them -
        # the handler calls ``schedule_restart()`` on a REQUEST thread and
        # drops the handle - so they are reached through the module's own
        # registry (``cancel_pending_restarts``, added for this). It has to
        # happen before the seams are restored at the bottom of this method:
        # a timer firing after that restoration acts on the REAL
        # ``_is_windows``/``_EXECV``, which on Windows is a real
        # ``os._exit(0)`` in this very test process. Cancelling first also
        # keeps the timer from setting ``_RESTART_REQUESTED`` behind the
        # serve thread's back while it is winding down.
        self.stranded_timers = board.cancel_pending_restarts()
        try:
            self.server.shutdown()
        except Exception:
            pass
        # KEEL ADDITION (T443 follow-up): the serve thread may still be
        # inside ``_perform_restart`` (calling the patched ``_EXECV``) right
        # after ``shutdown()`` returns - join before restoring any patched
        # seam below, so nothing swaps ``_EXECV``/``_is_windows`` back to
        # the real thing out from under a thread still using them.
        self.thread.join(timeout=5)
        try:
            self.server.server_close()
        except Exception:
            pass
        board._EXECV = self._original_execv
        board._is_windows = self._original_is_windows
        board._SERVER = self._original_server
        board._RESTART_REQUESTED = self._original_flag
        board.ROOT = self._original_root
        self._tmp.cleanup()


class TestTheLiveHandlerRefusesEveryBadRequest(TimerLeakGuard):
    """Every refusal must change nothing: no execv call, and the board keeps
    answering afterwards exactly as it did before."""

    def setUp(self) -> None:
        # super() FIRST (T627): the guard's own cleanup is registered before
        # this fixture's, so - cleanups running last-registered-first - the
        # board is closed and its timers cancelled BEFORE the leak check
        # looks, and the check sees the state the next test would inherit.
        super().setUp()
        self.live = _LiveBoard()
        self.addCleanup(self.live.close)

    def _still_serving(self) -> None:
        resp = self.live.request("GET", "/api/state")
        self.assertEqual(resp.status, 200)

    def test_get_is_refused_with_405(self) -> None:
        resp = self.live.request(
            "GET", "/api/restart", {"X-Keel-Restart": board.RESTART_TOKEN}
        )
        self.assertEqual(resp.status, 405)
        self.assertEqual(self.live.execv_calls, [])
        self._still_serving()

    def test_post_without_a_token_is_refused_with_403(self) -> None:
        resp = self.live.request("POST", "/api/restart")
        self.assertEqual(resp.status, 403)
        self.assertEqual(self.live.execv_calls, [])
        self._still_serving()

    def test_post_with_the_wrong_token_is_refused_with_403(self) -> None:
        resp = self.live.request(
            "POST", "/api/restart", {"X-Keel-Restart": "0" * 64}
        )
        self.assertEqual(resp.status, 403)
        self.assertEqual(self.live.execv_calls, [])
        self._still_serving()

    def test_a_non_loopback_host_header_is_refused_with_403(self) -> None:
        resp = self.live.request(
            "POST",
            "/api/restart",
            {"X-Keel-Restart": board.RESTART_TOKEN, "Host": "evil.example.com"},
        )
        self.assertEqual(resp.status, 403)
        self.assertEqual(self.live.execv_calls, [])
        self._still_serving()

    def test_a_valid_request_is_authorized_and_restarts_exactly_once(self) -> None:
        resp = self.live.request(
            "POST", "/api/restart", {"X-Keel-Restart": board.RESTART_TOKEN}
        )
        self.assertEqual(resp.status, 200)
        # schedule_restart's own delay - give the daemon timer a moment to
        # fire the (patched) execv this test's fixture installed.
        for _ in range(50):
            if self.live.execv_calls:
                break
            threading.Event().wait(0.05)
        self.assertEqual(len(self.live.execv_calls), 1)


class TestThePageRendersTheControlOnlyInTheStaleBranch(TimerLeakGuard):
    """The extraction style ``test_keel_derived_facts_t168.py`` already uses
    for this exact chip: pull the addition, assert on ITS text."""

    def setUp(self) -> None:
        super().setUp()
        # From the doRestart addition through the end of keelPaint - covers
        # both the poll/reload logic and the chip's three render branches.
        start = BOARD_SOURCE.index(
            "KEEL ADDITION (T340): the per-process token the server embedded"
        )
        end = BOARD_SOURCE.index('$("keelfilters").addEventListener')
        self.chip_block = BOARD_SOURCE[start:end]

    def test_the_badge_button_starts_hidden_in_the_markup(self) -> None:
        self.assertIn(
            '<button type="button" class="badge" id="keelrestart" hidden>'
            "restart board</button>",
            BOARD_SOURCE,
        )

    def test_the_button_is_shown_only_in_the_stale_branch(self) -> None:
        stale_start = self.chip_block.index("if(cd.stale){")
        unknown_start = self.chip_block.index("}else if(cd.unknown){")
        current_start = self.chip_block.index("}else{", unknown_start)
        block_end = self.chip_block.index("\n    }\n", current_start)
        stale_body = self.chip_block[stale_start:unknown_start]
        unknown_body = self.chip_block[unknown_start:current_start]
        current_body = self.chip_block[current_start:block_end]
        self.assertIn("restartBtn.hidden=false", stale_body)
        self.assertNotIn("restartBtn.hidden=false", unknown_body)
        self.assertNotIn("restartBtn.hidden=false", current_body)
        self.assertIn("restartBtn.hidden=true", unknown_body)
        self.assertIn("restartBtn.hidden=true", current_body)

    def test_the_click_handler_posts_with_the_token_header(self) -> None:
        self.assertIn('$("keelrestart").addEventListener("click",doRestart)', BOARD_SOURCE)
        self.assertIn('method:"POST"', BOARD_SOURCE)
        self.assertIn('"X-Keel-Restart":KEEL_RESTART_TOKEN', BOARD_SOURCE)

    def test_the_poll_checks_the_served_verdict_not_a_timer_alone(self) -> None:
        self.assertIn('"/api/state"', self.chip_block)
        self.assertIn("!st.keel.code.stale", self.chip_block)
        self.assertIn("location.reload()", self.chip_block)

    def test_a_stalled_restart_says_so_rather_than_spinning_forever(self) -> None:
        self.assertIn("Date.now()>deadline", self.chip_block)
        self.assertIn("board did not come back", self.chip_block)


class TestTheExtractedScriptIsValidJavaScript(TimerLeakGuard):
    """Skips, audibly, where no ``node`` exists — see the module docstring."""

    def test_the_whole_served_script_parses_under_node(self) -> None:
        import re
        import subprocess

        if NODE is None:
            self.skipTest(SKIP_REASON)
        node = NODE
        match = re.search(r"<script>(.*?)</script>", BOARD_SOURCE, re.S)
        self.assertIsNotNone(match, "could not extract the page's <script> block")
        with tempfile.NamedTemporaryFile(
            "w", suffix=".js", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(match.group(1))
            path = fh.name
        try:
            result = subprocess.run(
                [node, "--check", path], capture_output=True, timeout=30, check=False
            )
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", "replace")
        )


if __name__ == "__main__":
    unittest.main()
