"""T350 - KEEL ADDITION (T350): a REAL one-click restart, proven end to end.

Contract
--------
Reads   : ``scripts/keel_orchestration_dashboard.py`` run as a REAL child
          process (``subprocess.Popen``, unpatched ``_EXECV``) - not the
          module imported in-process. T340's own suite pins the guard and
          the argv-building seam through ``_EXECV`` replaced by a recorder,
          which proves the gate opens on the right inputs but proves nothing
          about the effect: nothing there ever calls a real, unpatched
          ``os.execv``. This file closes exactly that gap (backlog BL5):
          it starts the board on a spare loopback port pointed at a
          throwaway fixture project, reads the per-process restart token out
          of the served page, POSTs ``/api/restart`` with that token in the
          real header, and then proves - from OUTSIDE the process, over the
          real socket - that a NEW process is now answering the SAME port.
Emits   : unittest results only.
Writes  : nothing outside a temporary fixture project directory and the
          child process's own stdout/stderr pipes, all cleaned up in
          ``tearDown``/``finally`` regardless of outcome.
Argv    : none.

What proves "a new process", not just "a response"
----------------------------------------------------
``RESTART_TOKEN`` is drawn fresh with ``secrets.token_hex(32)`` at MODULE
IMPORT time (see the block comment above it in the board itself) - so the
only way the token served after the restart can differ from the token
served before it is for the module to have been imported again, in a fresh
interpreter, which is exactly what ``_reexec_same_process`` does and a
lingering old process could never produce on its own. That is the test's
core assertion: same port, DIFFERENT token, within a bounded deadline.

Where the platforms genuinely diverge - and why this test does not choose
between them
-------------------------------------------------------------------------
On POSIX, ``os.execv`` replaces the running process's image in place: the
OS-level PID is unchanged. On Windows, CPython's ``os.execv`` has no real
exec syscall to call, so it emulates one (spawn a new process, then exit the
caller) - the PID this test's ``subprocess.Popen`` was given is NOT the PID
now answering the port. Both are "a real restart"; neither is faked. So the
headline assertion (different token, same port, bounded wait) is written to
hold on BOTH, and the PID-level observation below is platform-conditional
by construction, never a skip: POSIX gets a same-PID-still-alive assertion
(the one thing that has never been exercised anywhere in this suite before
this file), Windows gets an exited-original-PID assertion - both are real
claims about what actually happened, checked, not assumed.

Failure policy
---------------
FAIL-CLOSED: no case here is skipped for being "the platform that matters
most". The only permitted skip is the environment-level one named at the
point it happens (no spare port could be bound at all).
"""

from __future__ import annotations

import http.client
import os
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BOARD_SCRIPT = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_orchestration_dashboard as board  # noqa: E402

TOKEN_RE = re.compile(r'const KEEL_RESTART_TOKEN="([0-9a-f]{64})"')
BANNER_RE = re.compile(r"Orchestration dashboard \(keel\): http://127\.0\.0\.1:(\d+)")

# KEEL ADDITION (T350), REVISED (T442, 2026-09-02): these are CEILINGS ON A
# HANG, not measurements of anything, and the difference is the whole reason
# they moved.
#
# Nothing this file asserts is a claim about how fast a board starts. The
# claims are: a banner is printed, the port answers, the token changes, and
# the original PID's fate matches the platform. A deadline is only here so
# that a board which never does those things ends the test in a sentence
# instead of hanging the suite forever - so it is set for the slowest
# machine anyone runs this on, not for the machine that wrote it.
#
# MEASURED 2026-09-02: at 20.0s the startup ceiling failed 17 of 17 GitHub
# macOS runs and 5 of 17 Windows runs, on a board that this machine and WSL
# Ubuntu both start in well under two seconds. A shared runner cold-starting
# an interpreter, importing this board (which fingerprints the component
# registry and this file at import time), and binding a socket is the case
# these numbers must cover, and 20s demonstrably did not cover it. 90s does,
# with room, and costs a passing run NOTHING: every wait below is a deadline
# loop that leaves at the first answer, never a fixed sleep.
#
# When a ceiling IS hit, the failure text is built by ``_diagnosis`` below,
# which says what did not happen - whether the child died, what it printed,
# whether the port answers anyway - rather than reporting a clock.
STARTUP_DEADLINE_S = 90.0
SERVE_DEADLINE_S = 60.0
RESTART_DEADLINE_S = 90.0
POLL_INTERVAL_S = 0.1


def _free_port() -> int:
    """A port nothing is listening on right now - not derived, just probed."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]
    finally:
        probe.close()


def _pump_stdout(pipe, out_queue: "queue.Queue[str | None]") -> None:
    """KEEL ADDITION (T350): drain the child's combined stdout/stderr on its
    own thread so a full pipe buffer can never stall the child, and so this
    test can wait on specific lines (the startup banner, printed once per
    process) with a deadline instead of guessing how long a restart takes."""
    try:
        for line in iter(pipe.readline, ""):
            out_queue.put(line)
    finally:
        out_queue.put(None)
        try:
            pipe.close()
        except OSError:
            pass


def _http_get(port: int, path: str, timeout: float = 5.0) -> tuple[int, str]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", "replace")
        return resp.status, body
    finally:
        conn.close()


def _http_post_restart(port: int, token: str, timeout: float = 5.0) -> int:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request(
            "POST",
            "/api/restart",
            body=b"",
            headers={"X-Keel-Restart": token, "Content-Length": "0"},
        )
        resp = conn.getresponse()
        resp.read()
        return resp.status
    finally:
        conn.close()


def _windows_best_effort_kill_port_owner(port: int) -> None:
    """KEEL ADDITION (T350): on Windows the re-exec's replacement process is
    NOT the child ``subprocess.Popen`` tracked - it is a new, untracked PID
    (see the module docstring). ``taskkill`` here is best-effort cleanup
    only, never load-bearing for the test's assertions, so any failure is
    swallowed: a leaked process on a CI runner's throwaway VM is not this
    test's correctness concern, but a local developer re-running this file
    should not accumulate stray listeners either."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=5, check=False
        ).stdout
    except Exception:
        return
    for line in out.splitlines():
        if f":{port} " in line and "LISTENING" in line:
            parts = line.split()
            pid = parts[-1] if parts else ""
            if pid.isdigit():
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", pid],
                        capture_output=True,
                        timeout=5,
                        check=False,
                    )
                except Exception:
                    pass


class TestARealRestartAnswersTheSamePortWithANewToken(unittest.TestCase):
    """KEEL ADDITION (T350): the integration case backlog BL5 named - a real
    child process, a real ``POST /api/restart``, a real ``os.execv`` (never
    patched anywhere in this file), asserted from outside the process over
    the real socket."""

    def setUp(self) -> None:
        try:
            self.port = _free_port()
        except OSError:
            self.skipTest("no spare loopback port could be bound for the restart test")
            return

        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / ".keel" / "audit").mkdir(parents=True)
        (root / ".keel" / "plans").mkdir(parents=True)
        (root / ".keel" / "audit" / "keel-audit.jsonl").write_text("", encoding="utf-8")
        self.root = root

        # KEEL ADDITION (T350): unbuffered stdout is load-bearing, not
        # cosmetic - a child whose stdout is a pipe (not a tty) is fully
        # buffered by default, so the startup banner this test waits on
        # would sit in the child's internal buffer, unflushed, until the
        # pipe filled or the process exited. This is set via the
        # PYTHONUNBUFFERED env var rather than the "-u" flag deliberately:
        # ``_reexec_same_process`` rebuilds argv from ``_ORIGINAL_ARGV``
        # (``sys.argv``, which never contains an interpreter flag like
        # "-u" - the interpreter consumes and strips it before ``sys.argv``
        # is even populated) but ``os.execv`` inherits the CURRENT process
        # environment as-is (it calls the C ``execv``, which forwards
        # ``environ`` unchanged), so an env var - unlike an argv flag -
        # survives the restart into the replacement process too.
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(BOARD_SCRIPT),
                "--dir",
                str(root),
                "--port",
                str(self.port),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self.lines: "queue.Queue[str | None]" = queue.Queue()
        # KEEL ADDITION (T442): every line the child prints is KEPT, not just
        # the one that matches the banner. When a deadline is hit, the child's
        # own words are the only witness to what a platform actually did, and
        # the old failure text threw them away.
        self.transcript: list[str] = []
        self._output_ended = False
        self.reader = threading.Thread(
            target=_pump_stdout, args=(self.proc.stdout, self.lines), daemon=True
        )
        self.reader.start()

    def tearDown(self) -> None:
        # KEEL ADDITION (T350): tear down even when an assertion above
        # failed - never leave a listener behind, on either platform.
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    try:
                        self.proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception:
            pass
        if os.name == "nt":
            _windows_best_effort_kill_port_owner(self.port)
        self.reader.join(timeout=5)
        self._tmp.cleanup()

    def _wait_for_banner(self, deadline: float) -> int | None:
        """Block on the queue (never a fixed sleep) until the startup banner
        line arrives or the deadline passes; returns the port it names.

        KEEL ADDITION (T442): every line pulled off the queue is kept in
        ``self.transcript`` on the way past, and the end of the child's
        output (``None``, the pump's sentinel) is remembered rather than
        merely returned - both feed ``_diagnosis``.
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            try:
                line = self.lines.get(timeout=min(remaining, 1.0))
            except queue.Empty:
                continue
            if line is None:
                self._output_ended = True
                return None
            self.transcript.append(line)
            match = BANNER_RE.search(line)
            if match:
                return int(match.group(1))

    def _drain_output(self) -> None:
        """Everything the child has printed but nobody has read yet, without
        blocking. Called only when something is already being reported."""
        while True:
            try:
                line = self.lines.get_nowait()
            except queue.Empty:
                return
            if line is None:
                self._output_ended = True
                return
            self.transcript.append(line)

    def _diagnosis(self, what_did_not_happen: str, waited: float) -> str:
        """KEEL ADDITION (T442): the failure text for a hit ceiling.

        The point of this file is a real restart, so when it fails the report
        has to name the platform behaviour, not the clock it was measured
        against. Four facts, all read at the moment of failure: whether the
        child is alive and with what exit code, whether its output stream
        ended, whether the port answers anyway (a port that serves while no
        banner ever arrived is a stdout problem, not a startup problem), and
        the last words the child said - which, when the board dies at import
        on some platform, is its traceback.
        """
        self._drain_output()
        code = self.proc.poll()
        child = (
            f"the child (pid {self.proc.pid}) is still running"
            if code is None
            else f"the child (pid {self.proc.pid}) had already exited with code {code}"
        )
        if self._output_ended:
            child += " and its stdout/stderr stream has ended"
        try:
            status, body = _http_get(self.port, "/", timeout=5.0)
            served = "with" if TOKEN_RE.search(body) else "without"
            port_state = (
                f"port {self.port} DID answer GET / with HTTP {status} "
                f"({served} a restart token in the page)"
            )
        except Exception as exc:  # noqa: BLE001 - a diagnosis never raises
            port_state = (
                f"nothing answered GET / on port {self.port} "
                f"({type(exc).__name__}: {exc})"
            )
        tail = " || ".join(line.rstrip() for line in self.transcript[-20:])
        said = tail if tail else "<the child printed nothing at all>"
        return (
            f"{what_did_not_happen} within the {waited:.0f}s ceiling: "
            f"{child}; {port_state}. The child's own output: {said}"
        )

    def _wait_for_serving_with_token(self, deadline: float) -> str | None:
        """Poll GET / with a bounded deadline (never a fixed sleep) - the
        listening socket can legitimately refuse connections for a moment
        while the old socket is closing and the new one is re-binding."""
        while time.monotonic() < deadline:
            try:
                status, body = _http_get(self.port, "/", timeout=2.0)
            except (ConnectionRefusedError, OSError):
                time.sleep(POLL_INTERVAL_S)
                continue
            if status != 200:
                time.sleep(POLL_INTERVAL_S)
                continue
            match = TOKEN_RE.search(body)
            if match:
                return match.group(1)
            time.sleep(POLL_INTERVAL_S)
        return None

    def test_the_port_answers_with_a_new_token_after_a_real_restart(self) -> None:
        """A real ``POST /api/restart`` leaves a DIFFERENT process answering
        the SAME port - proven from outside, over the socket.

        WHAT IS MEASURED (T442 restated it, because it was being read as a
        speed test): four facts about what happened, none of them a duration.
        A startup banner is printed and names a port; that port serves a
        64-hex restart token; after an authorized restart a SECOND banner is
        printed for the same port and the token served there is a different
        one - which only a fresh module import can produce, since the token
        is drawn at import time; and the original PID's fate matches how the
        platform implements ``os.execv`` (alive on POSIX, exited on Windows).

        WHY THE DEADLINES ARE WHAT THEY ARE. They are not part of the claim.
        Every wait is a ceiling on a HANG - a board that never prints, never
        answers or never comes back must end this test with a sentence rather
        than block the suite - so each is set generously for the slowest
        shared runner (see the constants block: 20s was measured wrong, 17 of
        17 macOS failures on a board that works) and is polled, so a healthy
        board pays none of it. A hung board still fails, at the ceiling, with
        ``_diagnosis`` naming which of the four facts did not happen and what
        the child process was actually doing instead.
        """
        original_pid = self.proc.pid

        startup_deadline = time.monotonic() + STARTUP_DEADLINE_S
        banner_port = self._wait_for_banner(startup_deadline)
        if banner_port is None:
            self.fail(
                self._diagnosis(
                    "the board never printed its startup banner",
                    STARTUP_DEADLINE_S,
                )
            )
        # bind_walk can, in principle, step past a port lost to a race; the
        # test follows whatever the process actually reports rather than
        # assuming its own probe still holds.
        self.port = banner_port

        # KEEL ADDITION (T442): a deadline of its own, taken from NOW. It
        # used to be the startup deadline plus five seconds, so a banner
        # that arrived late left the token wait almost no time at all - a
        # second-order way for a slow machine to fail a healthy board.
        token_before = self._wait_for_serving_with_token(
            time.monotonic() + SERVE_DEADLINE_S
        )
        if token_before is None:
            self.fail(
                self._diagnosis(
                    "the board printed its banner but never served a restart token",
                    SERVE_DEADLINE_S,
                )
            )

        status = _http_post_restart(self.port, token_before)
        self.assertEqual(status, 200, "a correctly-authorized restart was refused")

        restart_deadline = time.monotonic() + RESTART_DEADLINE_S

        # A second banner line is a second call to main() - real evidence a
        # process (new or image-replaced) actually started again, not just
        # that some socket somewhere kept answering.
        second_banner_port = self._wait_for_banner(restart_deadline)
        if second_banner_port is None:
            self.fail(
                self._diagnosis(
                    "no second startup banner - the restart never ran a new main()",
                    RESTART_DEADLINE_S,
                )
            )
        self.assertEqual(
            second_banner_port, self.port, "the restarted board bound a different port"
        )

        token_after = self._wait_for_serving_with_token(
            time.monotonic() + SERVE_DEADLINE_S
        )
        if token_after is None:
            self.fail(
                self._diagnosis(
                    "the board restarted but never served a token again",
                    SERVE_DEADLINE_S,
                )
            )

        # THE core assertion: a fresh module import draws a fresh token: a
        # lingering old process could never produce a different one.
        self.assertNotEqual(
            token_before, token_after, "the restart token did not change - same process"
        )
        self.assertEqual(len(token_after), 64)

        # KEEL ADDITION (T350): the platform-specific PID claim, checked
        # honestly rather than assumed - see the module docstring.
        #
        # KEEL ADDITION (T442): the two platforms need opposite waits, and
        # one shared five-second sleep was serving both badly. Windows waits
        # for an EVENT (the original process exiting), so its wait is a
        # ceiling, polled, generous, and paid only when something is wrong.
        # POSIX asserts an ABSENCE (the process never exited), so its wait is
        # a settle window that is genuinely spent - and is therefore kept
        # short, because a longer one buys no extra confidence.
        if os.name == "nt":
            exit_deadline = time.monotonic() + RESTART_DEADLINE_S
            while self.proc.poll() is None and time.monotonic() < exit_deadline:
                time.sleep(POLL_INTERVAL_S)
            if self.proc.poll() is None:
                self.fail(
                    self._diagnosis(
                        f"on Windows the original PID ({original_pid}) never exited, "
                        "and execv there is emulated by spawning a replacement and "
                        "exiting the caller",
                        RESTART_DEADLINE_S,
                    )
                )
        else:
            settle_deadline = time.monotonic() + 5.0
            while self.proc.poll() is None and time.monotonic() < settle_deadline:
                time.sleep(POLL_INTERVAL_S)
            self.assertIsNone(
                self.proc.poll(),
                "on POSIX os.execv replaces the image in place - the original PID "
                f"({original_pid}) must still be the live process",
            )
            self.assertEqual(self.proc.pid, original_pid)


class TestTheWindowsRestartSpawnsDetachedInsteadOfExeccing(unittest.TestCase):
    """T443 - the console-window bug and its fix, pinned through the module's
    own seams (``_SPAWN``, ``_EXIT``, ``_is_windows``) rather than a real
    spawn or a real process exit on either platform.

    DIAGNOSIS (T443): ``os.execv`` on Windows is not a real exec - CPython
    spawns a replacement with DEFAULT creation flags and exits the caller,
    and a replacement spawned with default flags by a console-less parent
    (the board is autostarted DETACHED by ``hooks/keel_liveview.py``) is
    handed a BRAND NEW console by Windows - the visible ``python.exe``
    window the owner reported. This class proves both directions: Windows
    takes the detached-spawn path with the exact flags and argv the exec
    path would have used, and POSIX takes the untouched ``os.execv`` path
    with no spawn at all.
    """

    def setUp(self) -> None:
        self._original_execv = board._EXECV
        self._original_spawn = board._SPAWN
        self._original_exit = board._EXIT
        self._original_is_windows = board._is_windows
        self._original_argv = board._ORIGINAL_ARGV
        board._ORIGINAL_ARGV = ["keel_orchestration_dashboard.py", "--port", "8770"]

    def tearDown(self) -> None:
        board._EXECV = self._original_execv
        board._SPAWN = self._original_spawn
        board._EXIT = self._original_exit
        board._is_windows = self._original_is_windows
        board._ORIGINAL_ARGV = self._original_argv

    def test_windows_spawns_detached_with_the_exact_flags_and_argv_then_exits(
        self,
    ) -> None:
        spawn_calls: list[tuple] = []
        exit_calls: list[int] = []
        execv_calls: list[tuple] = []
        board._SPAWN = lambda *a, **kw: spawn_calls.append((a, kw))
        board._EXIT = lambda code=0: exit_calls.append(code)
        board._EXECV = lambda *a: execv_calls.append(a)
        board._is_windows = lambda: True

        board._reexec_same_process()

        self.assertEqual(execv_calls, [], "POSIX exec must not run on Windows")
        self.assertEqual(len(spawn_calls), 1)
        args, kwargs = spawn_calls[0]
        self.assertEqual(len(args), 1)
        argv = args[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], board.PAGE_SOURCE)
        self.assertEqual(argv[2:], ["--port", "8770"])
        expected_flags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
        self.assertEqual(kwargs["creationflags"], expected_flags)
        self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["close_fds"])
        # stdout/stderr are deliberately absent from the call - inherited,
        # never redirected. See ``_reexec_same_process``'s own comment.
        self.assertNotIn("stdout", kwargs)
        self.assertNotIn("stderr", kwargs)
        self.assertEqual(exit_calls, [0], "the old process must end after the spawn")

    # Convention 15 is satisfied by BREAKING the module, not by a test that
    # re-derives the flags and compares them with a number it invented: the
    # real mutation (creationflags forced to 0; then the whole Windows branch
    # emptied) and the failures it produced are recorded on ledger item T443,
    # `.keel/plans/keel-plan-0d6cb6e8.md`. A test that "proves" a mutation
    # without mutating anything was removed on a silent-failure review.

    def test_posix_takes_the_execv_path_with_no_spawn_at_all(self) -> None:
        spawn_calls: list[tuple] = []
        exit_calls: list[int] = []
        execv_calls: list[tuple] = []
        board._SPAWN = lambda *a, **kw: spawn_calls.append((a, kw))
        board._EXIT = lambda code=0: exit_calls.append(code)
        board._EXECV = lambda *a: execv_calls.append(a)
        board._is_windows = lambda: False

        board._reexec_same_process()

        self.assertEqual(spawn_calls, [], "Windows spawn must not run on POSIX")
        self.assertEqual(exit_calls, [], "os._exit must not run on POSIX")
        self.assertEqual(len(execv_calls), 1)
        executable, argv = execv_calls[0]
        self.assertEqual(executable, sys.executable)
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], board.PAGE_SOURCE)
        self.assertEqual(argv[2:], ["--port", "8770"])


if __name__ == "__main__":
    unittest.main()
