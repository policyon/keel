"""The live view starts itself, when - and only when - the user said so.

WHAT THIS IS. The orchestration board (``scripts/keel_orchestration_dashboard.py``)
is a read-only viewer a session can watch while it works. Until now every
session had to be told about it by hand: the session hook injected one
sentence naming the URL and the command, and if nobody typed the command
there was no board. A server started by a previous session dies with its
parent, so the sentence was often pointing at nothing.

This module closes that loop, under three rules that decide its whole shape.

1. **OFF IS THE DEFAULT, AND THE SWITCH IS THE USER'S.** The opt-in lives in
   ``.keel/keel-policy.md``, which is policy-locked - so the decision to run a
   server cannot be taken by a model, only by the person whose machine it
   runs on. An absent key is OFF. A key nobody can parse is OFF, said out
   loud. ``KEEL_DASHBOARD`` in the environment overrides the file for one
   session, the same user-only escape the other switches have.

2. **RESTART IS A PROBE, NOT BOOKKEEPING.** The hook does not try to remember
   whether a server should be alive. It asks the port whether one IS alive
   and whether it is serving THIS project, and starts one only when the
   answer is no. That single rule covers every way a previous server can be
   gone - ended with its session, killed, crashed, rebooted - which is what
   "the board is never forgotten" actually requires. The recorded state file
   is a HINT that makes the common case one probe instead of ten; it is
   never evidence that anything is running.

3. **A VIEWER MAY NEVER COST A SESSION.** Every entry point here returns an
   outcome and raises nothing. Every failure - the script missing, the spawn
   refused, the port silent, the cache unwritable - ends as one honest
   sentence naming the manual command, never as a broken session start and
   never as silence (convention 7). The probe budget is bounded so a dead
   loopback cannot stall a session start.

IDENTITY, NOT MERE LIVENESS. Two projects can be open at once and the port
walk means either may hold 8770. So the probe reads ``/api/state`` and
compares the served root fingerprint with this project's own. The
fingerprint is imported from the dashboard module - one implementation,
never two - and is a hash rather than a path, so nothing here puts an
absolute path on a socket.

WHAT IT NEVER DOES. It never stops a server (a board that closes itself when
one session ends is the forgetting this module exists to fix), never binds
anything itself, never passes a string to a shell, never writes into the
tracked record, and never reads a port from anywhere but the constant 8770
and the walk the server itself performs (R19).
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

#: Where the opt-in is declared, and the values it accepts. A bare key on its
#: own line, the same whitespace-forgiving line shape the lock section uses.
_AUTOSTART_RE = re.compile(r"^[ \t]*autostart[ \t]*:[ \t]*(\S+)[ \t]*$", re.IGNORECASE | re.MULTILINE)
_TRUE = frozenset({"on", "true", "yes", "1"})
_FALSE = frozenset({"off", "false", "no", "0"})

#: The environment switch, user-only like every other one.
ENV_SWITCH = "KEEL_DASHBOARD"

#: The board's own constant port and the length of its own walk - both read
#: from the server rather than invented here. ``main`` binds 8770 and tries
#: ten ports; this is that same range, so a server that walked is still found.
BASE_PORT = 8770
PORT_SPAN = 10

#: Bounds. A session start may not be held up by a viewer.
#:
#: MEASURED (2026-08-15, this project, Windows): a freshly spawned viewer
#: answers its first probe after 0.67s, 0.67s and 0.78s on three consecutive
#: runs - and the run BEFORE those three, the one whose bytecode cache had
#: just been invalidated by an edit, took longer than the 1.5s this file
#: first budgeted and was reported as unconfirmed while in fact serving. The
#: cold-compile case is exactly the first run after an install or an edit,
#: which is the run an adopter is most likely to watch, so the wait is set
#: for it rather than for the warm case: three seconds, well inside the
#: hook's own ten-second timeout, and left at the first answer rather than
#: slept through.
#:
#: ONE CLAIM HERE WAS WRONG AND IS CORRECTED (T147, measured 2026-08-16).
#: This comment used to say that a probe against a port with nobody on it is
#: REFUSED rather than timed out, so a whole scan costs microseconds. On this
#: project's own Windows machine it does not: the firewall DROPS the packet,
#: the connection times out, and an empty range costs the probe timeout ten
#: times over. That is precisely why SCAN_BUDGET_S is a total checked before
#: each probe - the bound was doing the work the cost assumption claimed was
#: unnecessary, and only the bound was load-bearing.
#:
#: THE BUDGETS BELOW ARE TOTALS, and that word is load-bearing. The first
#: version of this file checked its deadline before starting a scan rather
#: than before each probe, so a scan begun just inside the deadline ran to
#: completion outside it - measured at 5.64s against a 3.0s budget, on a
#: path whose whole promise is that it cannot hold up a session start. A
#: bound that only holds when nothing is slow is not a bound.
PROBE_TIMEOUT_S = 0.25
#: How much of a probed server's answer is read before giving up on it. See
#: ``probe``: this is a hostile-stream guard, deliberately far above the
#: 269KB a real board actually serves.
MAX_STATE_BYTES = 8_000_000
SCAN_BUDGET_S = 1.0
SPAWN_WAIT_S = 3.0
SPAWN_POLL_S = 0.1
#: How long an explicit stop waits for the port to go quiet before saying it
#: could not confirm. Not a session-start path, so it may exceed the scan
#: budget; it still ends in a sentence rather than a hang.
STOP_WAIT_S = 5.0
#: The slower ask, used where "it did not answer in a quarter second" would
#: otherwise be read as a fact: the confirming probe before a spawn, and the
#: stop command's own questions. Four times the walk's probe, still inside a
#: session-start's ten seconds, and never spent on the common path.
CONFIRM_TIMEOUT_S = 1.0
#: The TOTAL the confirming pass before a spawn may spend, however many ports
#: are occupied - checked before each ask, not once before the pass, which is
#: the distinction SCAN_BUDGET_S was measured into existence by. Running out
#: means spawning, which is what would have happened without the pass at all.
CONFIRM_BUDGET_S = 2.0

#: Runtime state lives in the one ignored path, because it is rebuildable by
#: definition (the probe rebuilds it) and machine-local by nature.
STATE_RELPATH = (".keel", "cache", "live-view.json")
LOG_RELPATH = (".keel", "cache", "live-view.log")

_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
_DASHBOARD = Path(_SCRIPTS_DIR) / "keel_orchestration_dashboard.py"

MANUAL_COMMAND = "python scripts/keel_orchestration_dashboard.py --dir ."
#: The two commands this module answers to, written once so the sentences
#: that name them can never drift from what the parser accepts.
STATUS_COMMAND = "python hooks/keel_liveview.py --status"
STOP_COMMAND = "python hooks/keel_liveview.py --stop"


@dataclass(frozen=True)
class Autostart:
    """What the user asked for, and in which words we can say we know it."""

    on: bool
    reason: str


@dataclass(frozen=True)
class Outcome:
    """What actually happened. ``action`` is the vocabulary the record uses."""

    action: str  # off | already | started | unconfirmed | failed
    port: int | None
    detail: str
    #: Boards seen during this run's own walk that PROVED their project is
    #: gone. Never a survey of the range - the walk stops when it finds ours
    #: - and never populated by a probe nobody made.
    stale: tuple["Board", ...] = ()

    @property
    def url(self) -> str | None:
        return None if self.port is None else f"http://127.0.0.1:{self.port}"


# --------------------------------------------------------------- the switch


def parse_autostart(body: str) -> Autostart:
    """Read the opt-in out of an arming file's body. Pure; never raises.

    Fail-closed on anything but a clear yes: no key is OFF, an unreadable
    value is OFF, and TWO declarations that disagree are OFF - a viewer
    started on an ambiguous instruction is a viewer nobody asked for.
    """
    values = [m.group(1).strip().casefold() for m in _AUTOSTART_RE.finditer(body or "")]
    if not values:
        return Autostart(False, "not declared")
    unknown = [v for v in values if v not in _TRUE and v not in _FALSE]
    if unknown:
        return Autostart(False, f"unreadable value {unknown[0]!r}")
    decided = {v in _TRUE for v in values}
    if len(decided) > 1:
        return Autostart(False, "declared both on and off")
    return Autostart(values[0] in _TRUE, "declared on" if values[0] in _TRUE else "declared off")


def setting(cwd: Path, env: Mapping[str, str] | None = None) -> Autostart:
    """The effective opt-in: the environment switch first, then the file.

    NEVER RAISES - an unreadable arming file is OFF with its fault named,
    which is the same answer as "not declared" for behaviour and a different
    one for the reader, and that difference is the point.
    """
    values = os.environ if env is None else env
    raw = (values.get(ENV_SWITCH) or "").strip().casefold()
    if raw:
        if raw in _TRUE:
            return Autostart(True, f"{ENV_SWITCH}={raw}")
        if raw in _FALSE:
            return Autostart(False, f"{ENV_SWITCH}={raw}")
        return Autostart(False, f"{ENV_SWITCH}={raw!r} is not on or off")
    try:
        path = Path(cwd).joinpath(".keel", "keel-policy.md")
        if not path.is_file():
            return Autostart(False, "no arming file")
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return Autostart(False, f"arming file unreadable: {type(exc).__name__}")
    body = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                body = "\n".join(lines[index + 1 :])
                break
    return parse_autostart(body)


# ------------------------------------------------------------- the identity


def fingerprint(root: Path | str) -> str | None:
    """This project's served identity, from the dashboard's own function.

    Imported rather than reimplemented (the T122 rule): the hook and the page
    must never hold two opinions about which project a server is serving.
    Returns None when the dashboard module cannot be reached at all, which
    the caller reports as a failure rather than papering over.
    """
    try:
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)
        import keel_orchestration_dashboard as board  # noqa: PLC0415

        return board.root_fingerprint(root)
    except Exception:  # noqa: BLE001 - absence, reported by the caller
        return None


# ---------------------------------------------------------------- the probe


@dataclass(frozen=True)
class Board:
    """What one port said about itself when asked. Facts, never inferences.

    ``root_present`` and ``adopted`` are ``None`` when the board did not say -
    a server older than T147 answers without those keys, and "it did not say"
    must never be read as "the project is gone". Only an explicit False is
    evidence of a stale board.
    """

    port: int
    verdict: str  # ours | other
    pid: int | None
    root_present: bool | None
    adopted: bool | None

    @property
    def stale(self) -> bool:
        """Whether this board PROVED its project is gone. Never a guess."""
        return self.verdict == "other" and self.root_present is False


def identify(port: int, want: str, timeout: float = PROBE_TIMEOUT_S) -> Board | None:
    """Ask one port who it is. ``None`` means silence. Never raises.

    The one implementation behind :func:`probe`, which keeps the three-word
    vocabulary the walk uses. Anything listening that does not answer in our
    shape is a Board with verdict ``other`` and nothing else known: the port
    is occupied, which is all the walk needs, and nothing may be invented
    about a process that did not describe itself.
    """
    import http.client  # noqa: PLC0415 - stdlib, imported where it is used

    def occupied() -> Board:
        return Board(port, "other", None, None, None)

    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/api/state")
        response = conn.getresponse()
        if response.status != 200:
            return occupied()
        # The cap is a defence against a hostile local process streaming
        # forever, not a size estimate - so it sits far above the real
        # payload rather than near it. MEASURED 2026-08-15: this project's
        # own ``/api/state`` is 269KB with two 400-event windows in it. A cap
        # anywhere near that would turn a big project's board into an
        # unparseable answer, and an unparseable answer used to read as
        # "silent" - which would start a SECOND board for a project that
        # already had one.
        payload = json.loads(response.read(MAX_STATE_BYTES).decode("utf-8", "replace"))
        if not isinstance(payload, Mapping):
            # Valid JSON, wrong shape (e.g. an array) - not a parse failure,
            # but still not our answer. Route it through the same "other"
            # path as an unparseable body: something IS listening.
            raise ValueError("state response was not a JSON object")
        keel = payload.get("keel") or {}
        served = keel.get("root_fp")
        pid = keel.get("pid")
        return Board(
            port,
            "ours" if served and served == want else "other",
            pid if isinstance(pid, int) else None,
            keel.get("root_present") if isinstance(keel.get("root_present"), bool) else None,
            keel.get("adopted") if isinstance(keel.get("adopted"), bool) else None,
        )
    except (ValueError, UnicodeError):
        # Something IS listening and it did not answer in our shape. That is
        # "other", never "silent": the port is occupied, so the caller must
        # walk past it rather than treat it as free.
        return occupied()
    except Exception:  # noqa: BLE001 - nobody there, or nobody answering us
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - closing a dead socket
                pass


def probe(port: int, want: str, timeout: float = PROBE_TIMEOUT_S) -> str:
    """Ask one port who it is: ``ours``, ``other`` or ``silent``. Never raises.

    ``other`` is a real answer, not an error - it is how a second project's
    board on 8770 makes this one walk instead of claiming a server it does
    not own. The walk needs exactly this word and nothing else; callers that
    need the board's own facts call :func:`identify` instead.
    """
    board = identify(port, want, timeout)
    return "silent" if board is None else board.verdict


def port_is_free(port: int, timeout: float = PROBE_TIMEOUT_S) -> bool | None:
    """Whether nobody holds ``port``: True, False, or None for "cannot tell".

    THREE ANSWERS, BECAUSE THERE ARE THREE. :func:`identify` collapses every
    unhappy path into "no board answered", which is right for a walk looking
    for somewhere to serve and WRONG as proof that a process died: a board
    too slow to answer inside the probe timeout is indistinguishable there
    from one that is gone. This asks the only question with an unambiguous
    answer - did the connection get REFUSED - and reports "I could not tell"
    rather than guessing when it did not.

    TWO QUESTIONS, BECAUSE ONE IS NOT PORTABLE. MEASURED 2026-08-16 on this
    project's own Windows machine: connecting to a loopback port with nobody
    on it does NOT come back refused - it TIMES OUT, because the local
    firewall drops the packet rather than answering it. A "free means we were
    refused" test would therefore never once say free here, and an explicit
    stop would report failure after every successful kill. So:

    1. If the connection is ACCEPTED, something holds the port: False, and
       definitive. The kernel accepts from the listen backlog whether or not
       the server behind it is busy, which is exactly why this is asked at
       the TCP layer rather than by another HTTP probe - a loaded board can
       be slow to ANSWER while never being slow to ACCEPT.
    2. If it was not accepted, ask the other way round: try to BIND the port,
       without SO_REUSEADDR (the same test, and the same reasoning, as
       ``first_free_port``). A bind that succeeds where a connection was not
       accepted means nothing is serving there: True.
    3. Anything else - not accepted, and not bindable either - is None, the
       answer that must never be read as either of the other two.

    Never raises.
    """
    import socket  # noqa: PLC0415 - stdlib, imported where it is used

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", port))
        return False
    except ConnectionRefusedError:
        return True
    except OSError:
        pass  # not accepted; question two decides between free and unclear
    finally:
        try:
            sock.close()
        except OSError:
            pass
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe_socket.bind(("127.0.0.1", port))
        return True
    except OSError:
        return None
    finally:
        try:
            probe_socket.close()
        except OSError:
            pass


def find_running(
    cwd: Path,
    want: str,
    hint: int | None = None,
    deadline: float | None = None,
    sightings: list[Board] | None = None,
) -> int | None:
    """The port already serving THIS project, or None. Never raises.

    The hint (the port we last started on) is tried first so the common case -
    a board still up from the last session - costs one probe rather than ten.

    ``deadline`` is checked BEFORE EACH PROBE, not once before the walk: a
    scan that starts inside its budget must not finish outside it. Running
    out of time answers None, which is the same answer as "nobody is there"
    and is the safe one - the caller starts a server, and a duplicate is
    impossible anyway because the second one cannot bind the same port.

    ``sightings``, when given, collects every board this walk actually spoke
    to. It costs NOTHING: these are the answers the walk already received.
    What it cannot do is see past the point the walk stopped at - a hint that
    hits on the first probe means one sighting, not ten - so a caller must
    report what was seen and never present it as a survey of the range.
    """
    order: list[int] = []
    if hint is not None:
        order.append(hint)
    order.extend(p for p in range(BASE_PORT, BASE_PORT + PORT_SPAN) if p != hint)
    for port in order:
        if deadline is not None and time.monotonic() >= deadline:
            return None
        board = identify(port, want)
        if board is None:
            continue
        if sightings is not None:
            sightings.append(board)
        if board.verdict == "ours":
            return port
    return None


def survey(cwd: Path, want: str | None = None) -> list[Board]:
    """Every board answering in the range, whole walk, no deadline.

    The explicit-command path: a user who asks what is running gets all ten
    ports asked, not the early exit the session-start walk takes. Never
    raises - a fingerprint that cannot be computed still lists what is
    listening, all of it as ``other``, which is the truthful answer when this
    project's own identity is unavailable.
    """
    mine = want if want is not None else (fingerprint(cwd) or "")
    boards: list[Board] = []
    for port in range(BASE_PORT, BASE_PORT + PORT_SPAN):
        board = identify(port, mine)
        if board is not None:
            boards.append(board)
    return boards


# ---------------------------------------------------------- the state file


def _state_path(cwd: Path) -> Path:
    return Path(cwd).joinpath(*STATE_RELPATH)


def read_state(cwd: Path) -> dict:
    """The last recorded hint; ``{}`` when there is none. Never raises."""
    try:
        return json.loads(_state_path(cwd).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - a hint that cannot be read is no hint
        return {}


def write_state(cwd: Path, port: int, pid: int | None, want: str) -> None:
    """Record the hint. Never raises: a lost hint costs nine extra probes."""
    try:
        path = _state_path(cwd)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"port": port, "pid": pid, "root_fp": want, "at": int(time.time())},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - explicitly survivable
        pass


# ---------------------------------------------------------------- the spawn


def first_free_port(start: int = BASE_PORT, span: int = PORT_SPAN) -> int | None:
    """The first port from ``start`` that nothing holds, or None. Never raises.

    WHY THE CALLER PICKS THE PORT AT ALL. The viewer walks +1 when its port
    is busy, and on Linux that is enough. On Windows it is not: the server
    sets ``allow_reuse_address``, and Windows lets a SECOND process bind an
    address another socket already holds. Measured 2026-08-15 - a second
    project's board "bound" 8770 while the first project's server kept every
    connection, so the walk never happened, the new board answered nobody,
    and the autostart honestly reported a server it could not find. Choosing
    a free port before spawning is the fix that does not touch the vendored
    server.

    The test bind deliberately does NOT set ``SO_REUSEADDR``: this socket
    exists to be refused, and a socket permitted to share an address cannot
    tell whether one is free.

    R19 HOLDS. Nothing here is derived from the project's identity - no hash,
    no path, no user. This is the constant 8770 and the same +1 walk the
    server itself performs, done a moment earlier and by the process that
    needs to know the answer.
    """
    import socket  # noqa: PLC0415 - stdlib, imported where it is used

    for port in range(start, start + span):
        probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe_socket.bind(("127.0.0.1", port))
            return port
        except OSError:
            continue
        finally:
            try:
                probe_socket.close()
            except OSError:
                pass
    return None


def _occupied_ports(start: int = BASE_PORT, span: int = PORT_SPAN) -> list[int]:
    """Every port in the range something holds. Never raises.

    The cheap half of "is one of these a board of ours": a bind that fails
    answers immediately, where a connection to an empty port can cost its
    whole timeout (see ``port_is_free`` for what this machine measured). The
    expensive half - asking who is there - is then put only to these.

    Same test and same reasoning as ``first_free_port``, including the
    deliberate absence of SO_REUSEADDR.

    WHY THE OMISSION IS WHAT MAKES IT RELIABLE, measured 2026-08-16 on this
    project's Windows machine against a live board and against synthetic
    holders both with and without the option: a holder is detected either
    way. SO_REUSEADDR governs the socket attempting the SECOND bind, not the
    one already holding the address - which is exactly the T146 failure seen
    from the other side. There, the second SERVER inherited
    ``allow_reuse_address = 1`` and so bound around a live board; here the
    probe never sets it, and so cannot.
    """
    import socket  # noqa: PLC0415 - stdlib, imported where it is used

    held: list[int] = []
    for port in range(start, start + span):
        probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe_socket.bind(("127.0.0.1", port))
        except OSError:
            held.append(port)
        finally:
            try:
                probe_socket.close()
            except OSError:
                pass
    return held


def _spawn(cwd: Path) -> tuple[int | None, int | None, str]:
    """Start a detached board for ``cwd``. Returns ``(pid, port, detail)``.

    The port is a value of its own here, never smuggled inside ``detail``
    for a caller to parse back out.

    Detached on purpose and on both platforms: the whole point is a server
    that OUTLIVES the session that started it, so the next session finds it
    already up. No shell is involved - the argument list is built here and
    passed as a list, and the only strings in it are this interpreter, this
    module's sibling script, and the project directory.

    stdout goes nowhere because the server prints its project's absolute path
    there on startup, and a viewer has no business writing a home path into a
    file. stderr is kept, in the ignored cache, because when a spawn fails
    that text is the only witness.
    """
    if not _DASHBOARD.is_file():
        return None, None, "viewer script not found"
    # Both refusals are settled BEFORE anything is opened. The log handle
    # used to be opened first, so the no-free-port return leaked it - caught
    # by the test written for that return, which is the argument for writing
    # a test per refusal rather than one per success.
    port = first_free_port()
    if port is None:
        return None, None, f"no free port in {BASE_PORT}-{BASE_PORT + PORT_SPAN - 1}"
    try:
        log_path = Path(cwd).joinpath(*LOG_RELPATH)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        errors = open(log_path, "a", encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError:
        errors = subprocess.DEVNULL  # type: ignore[assignment]
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": errors,
        "cwd": str(cwd),
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    else:
        kwargs["start_new_session"] = True
    try:
        child = subprocess.Popen(  # noqa: S603 - list form, no shell, fixed argv
            [sys.executable, str(_DASHBOARD), "--dir", str(cwd), "--port", str(port)],
            **kwargs,
        )
        return child.pid, port, "started"
    except Exception as exc:  # noqa: BLE001 - reported, never raised
        return None, None, f"spawn refused: {type(exc).__name__}"
    finally:
        if errors not in (subprocess.DEVNULL,):
            try:
                errors.close()  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------- the caller


def ensure(cwd: Path, env: Mapping[str, str] | None = None) -> Outcome:
    """Make sure a board is serving this project, if the user asked for one.

    THIS FUNCTION NEVER RAISES. It is called from the session hook before the
    session's own record is written, so an exception here would cost a
    session its start line; every path below therefore ends in an Outcome,
    including the paths that mean "something is broken".
    """
    try:
        want = setting(cwd, env)
        if not want.on:
            return Outcome("off", None, want.reason)
        fp = fingerprint(cwd)
        if not fp:
            return Outcome("failed", None, "viewer identity unavailable")
        hint = read_state(cwd)
        seen: list[Board] = []
        port = find_running(
            cwd,
            fp,
            hint.get("port") if isinstance(hint, dict) else None,
            deadline=time.monotonic() + SCAN_BUDGET_S,
            sightings=seen,
        )
        # Collected from the walk that had to happen anyway - a session start
        # pays nothing for this, and a walk that stopped early reports only
        # what it actually asked.
        stale = tuple(board for board in seen if board.stale)
        if port is not None:
            write_state(cwd, port, hint.get("pid") if isinstance(hint, dict) else None, fp)
            return Outcome(
                "already", port, "a server for this project was already up", stale
            )
        # ONE MORE ASK BEFORE SPAWNING, over every port that is OCCUPIED. The
        # walk's probe timeout is a quarter second, and this project's own
        # board serves a 269KB payload to a browser once a second; a board
        # that is merely BUSY answers the walk with silence, and the walk's
        # answer to silence is to start a server. That would put a SECOND
        # board on another port for a project that already has one - the
        # accumulation this whole feature exists to reduce - and the orphan
        # is then unreachable by --stop, which acts on the recorded port.
        #
        # WHY OCCUPANCY FIRST. Asking every port again would cost ten slow
        # probes; asking only the recorded one misses a board whose hint is
        # stale, corrupt or absent. Occupancy is settled by BIND, which fails
        # instantly and never times out, so the slow identity question is put
        # only to the few ports something actually holds. Bounded as a TOTAL
        # and checked before each ask, the lesson SCAN_BUDGET_S already
        # carries: a machine with a full range must not turn this into ten
        # seconds of session start.
        hinted = hint.get("port") if isinstance(hint, dict) else None
        foreign = {board.port for board in seen if board.verdict == "other"}
        candidates = [p for p in _occupied_ports() if p not in foreign]
        candidates.sort(key=lambda p: (p != hinted, p))
        confirm_deadline = time.monotonic() + CONFIRM_BUDGET_S
        for candidate in candidates:
            if time.monotonic() >= confirm_deadline:
                break
            again = identify(candidate, fp, timeout=CONFIRM_TIMEOUT_S)
            if again is not None and again.verdict == "ours":
                write_state(cwd, candidate, again.pid, fp)
                return Outcome(
                    "already",
                    candidate,
                    "a server for this project was already up (it answered the "
                    "second, slower ask rather than the walk)",
                    stale,
                )
        pid, spawned_port, detail = _spawn(cwd)
        if pid is None:
            return Outcome("failed", None, detail, stale)
        # The spawn chose the port, so the wait knows exactly where to look
        # and asks there FIRST - the scan behind it is the fallback for the
        # case where something took the port in the moment between.
        chosen = spawned_port
        deadline = time.monotonic() + SPAWN_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(SPAWN_POLL_S)
            port = find_running(cwd, fp, hint=chosen, deadline=deadline)
            if port is not None:
                write_state(cwd, port, pid, fp)
                return Outcome("started", port, "started for this session", stale)
        return Outcome("unconfirmed", None, "started, not yet answering", stale)
    except Exception as exc:  # noqa: BLE001 - the promise this file makes
        return Outcome("failed", None, f"{type(exc).__name__}")


# ----------------------------------------------------------------- the stop


@dataclass(frozen=True)
class Stopped:
    """The result of an explicit stop. ``action`` is this command's vocabulary."""

    action: str  # stopped | none | refused | failed
    detail: str


def stop_command(pid: int) -> str:
    """The exact command a HUMAN would type to end a board keel will not.

    Named per platform because a wrong command is worse than no command: a
    reader who is told the other one silently learns that keel's advice does
    not work here.
    """
    return f"taskkill /PID {pid} /F" if os.name == "nt" else f"kill {pid}"


def stop(cwd: Path) -> Stopped:
    """End THIS project's board, and only ever this project's. Never raises.

    Four things must line up before a signal is sent, and any one of them
    missing is a refusal with its reason rather than a best guess:

    1. this project's fingerprint can be computed;
    2. a port is recorded for it, and something is listening there;
    3. that listener identifies itself as serving THIS project - the same
       identity test the autostart uses, so a board that walked onto our
       recorded port from another project is never ended by us;
    4. it reports its own pid. A board too old to say so is REPORTED with
       the command to end it by hand, never guessed at from a port table.

    The recorded pid is a hint like the rest of the state file (see
    ``write_state``); the pid the answering board states about itself is the
    fact, and a disagreement between them is named in the detail rather than
    resolved silently.
    """
    try:
        fp = fingerprint(cwd)
        if not fp:
            return Stopped("refused", "viewer identity unavailable")
        state = read_state(cwd)
        port = state.get("port") if isinstance(state, dict) else None
        if not isinstance(port, int):
            return Stopped("none", "no board is recorded for this project")
        board = identify(port, fp, timeout=CONFIRM_TIMEOUT_S)
        if board is None:
            # "It did not answer" is not "it is gone". Only a refused
            # connection proves the port is empty; anything else is unclear,
            # and this command does not act on unclear.
            free = port_is_free(port, timeout=CONFIRM_TIMEOUT_S)
            if free is True:
                return Stopped("none", f"nothing is listening on {port}")
            why = (
                f"something holds {port} but did not answer as a keel board in "
                f"time, so keel cannot tell whose it is"
                if free is False
                else f"{port} neither answered nor refused the connection, so "
                f"keel cannot tell a board that is gone from one that is "
                f"merely slow"
            )
            return Stopped(
                "refused",
                f"{why}; nothing was signalled. Try again, or look with: "
                f"{STATUS_COMMAND}",
            )
        if board.verdict != "ours":
            return Stopped(
                "refused",
                f"the board on {port} is serving another project; keel never "
                f"ends a board it cannot prove is its own",
            )
        recorded = state.get("pid")
        if board.pid is None:
            # A board older than this feature. keel will not signal a pid it
            # was only told about - the state file is a hint by construction,
            # and the process it named may since have died and been replaced.
            # The hint is handed to the human WITH ITS PROVENANCE, because
            # "end it from the window it runs in" is useless advice for a
            # board autostart spawned detached with no window at all.
            hint = (
                f"the recorded hint says pid {recorded}, which may be stale; "
                f"if it is still this board: {stop_command(recorded)}"
                if isinstance(recorded, int)
                else "nothing recorded a pid for it either"
            )
            return Stopped(
                "refused",
                f"the board on {port} does not report its pid, so keel cannot "
                f"prove which process to end - {hint}. A board started after "
                f"this feature landed reports its own pid and stops cleanly",
            )
        note = ""
        if isinstance(recorded, int) and recorded != board.pid:
            note = (
                f" (the recorded hint said pid {recorded}; the board itself "
                f"says {board.pid}, and the board is the fact)"
            )
        try:
            os.kill(board.pid, signal.SIGTERM)
        except (OSError, ValueError) as exc:
            return Stopped(
                "failed",
                f"could not end pid {board.pid}: {type(exc).__name__}; "
                f"{stop_command(board.pid)}",
            )
        deadline = time.monotonic() + STOP_WAIT_S
        while time.monotonic() < deadline:
            time.sleep(SPAWN_POLL_S)
            # Confirmed by REFUSAL, never by silence: a signalled process that
            # is slow to die and one that ignored the signal look identical to
            # a probe, and reporting "stopped" for the second is the exact
            # false success this command must not produce.
            if port_is_free(port, timeout=CONFIRM_TIMEOUT_S) is True:
                return Stopped(
                    "stopped", f"ended the board on {port} (pid {board.pid}){note}"
                )
        return Stopped(
            "failed",
            f"signalled pid {board.pid}, but {port} has not gone quiet within "
            f"{STOP_WAIT_S:.0f}s - it may still be serving. End it yourself "
            f"with: {stop_command(board.pid)}",
        )
    except Exception as exc:  # noqa: BLE001 - the promise this file makes
        return Stopped("failed", f"{type(exc).__name__}")


def line(outcome: Outcome, tag: str) -> str | None:
    """The one sentence the session is told, or None when the option is off.

    Off is silence HERE rather than a sentence, because the caller still
    prints the standing live-view line in that case: an adopter who never
    opted in must see exactly what they saw before this module existed.
    """
    if outcome.action == "off":
        return None
    if outcome.action == "already":
        return (
            f"{tag} - {outcome.url} was already running for this project; "
            f"autostart left it alone."
        ) + stale_note(outcome.stale)
    if outcome.action == "started":
        return (
            f"{tag} - started for this session at {outcome.url} "
            f"(autostart is on in the arming file; it keeps running after "
            f"this session ends)."
        ) + stale_note(outcome.stale)
    if outcome.action == "unconfirmed":
        return (
            f"{tag} - autostart launched the viewer but it has not answered "
            f"yet; look at {BASE_PORT} upward, or start it with: {MANUAL_COMMAND}"
        ) + stale_note(outcome.stale)
    return (
        f"{tag} - autostart did not run ({outcome.detail}). "
        f"Start it with: {MANUAL_COMMAND}"
    ) + stale_note(outcome.stale)


def stale_note(stale: tuple[Board, ...]) -> str:
    """The sentence about boards outliving their projects, or nothing at all.

    REPORTED, NEVER REAPED. Each one names its port, the pid the board itself
    stated, and the exact command to end it - keel will not end a process it
    did not start and cannot prove is nobody's live board. Silence when there
    is nothing to say, because a line that appears every session saying "0
    stale" is a line people stop reading.

    THE COUNT IS NOT A TOTAL, and the sentence says so. These are the boards
    one walk happened to speak to before it found what it was looking for or
    ran out of budget; there may be more on ports nobody asked. A number
    presented bare would be read as "this machine has N", which is a claim
    this walk cannot make - so the caveat travels in the sentence rather than
    in a docstring the reader will never see (R34: what a bound left out is
    named where the bound applies).
    """
    if not stale:
        return ""
    parts = []
    for board in stale:
        where = f":{board.port}"
        parts.append(
            f"{where} (pid {board.pid}, {stop_command(board.pid)})"
            if board.pid is not None
            else f"{where} (pid not reported)"
        )
    subject = "board" if len(parts) == 1 else "boards"
    return (
        f" Also seen while looking for this project's board: {len(parts)} "
        f"{subject} still serving a project that no longer exists - "
        f"{'; '.join(parts)}. keel never ends them for you, and this is only "
        f"what that walk reached, not a count of the range - for all of it: "
        f"{STATUS_COMMAND}"
    )


# ----------------------------------------------------------------- the command


def report(cwd: Path) -> list[str]:
    """The lines ``--status`` prints: the whole range, asked one by one."""
    mine = fingerprint(cwd)
    lines = [f"keel live view: ports {BASE_PORT}-{BASE_PORT + PORT_SPAN - 1}"]
    if not mine:
        lines.append("  this project's identity is unavailable; all boards read as other")
    state = read_state(cwd)
    lines.append(
        f"  recorded for this project: {state.get('port')} (pid {state.get('pid')})"
        if isinstance(state, dict) and state.get("port")
        else "  recorded for this project: nothing"
    )
    boards = survey(cwd, mine or "")
    if not boards:
        lines.append("  nothing is listening in the range")
        return lines
    for board in boards:
        who = "THIS project" if board.verdict == "ours" else "another project"
        if board.stale:
            who = "a project that no longer exists"
        pid = board.pid if board.pid is not None else "not reported"
        lines.append(f"  :{board.port} - {who} (pid {pid})")
        if board.verdict == "ours":
            lines.append(f"      end it with: {STOP_COMMAND}")
        elif board.pid is not None:
            lines.append(f"      keel will not end it; you can: {stop_command(board.pid)}")
    return lines


def main(argv: list[str] | None = None) -> int:
    """``--status`` reports the range; ``--stop`` ends this project's board.

    Exit codes follow R6: 0 when the command did what it says, 1 when a stop
    was refused or could not be confirmed. A status report is never a gate -
    finding a stale board is information, not a failure, so it exits 0.
    """
    import argparse  # noqa: PLC0415 - stdlib, imported where it is used

    parser = argparse.ArgumentParser(
        prog="keel_liveview.py",
        description="Report the live-view boards on this machine, or stop this project's.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="report every board in the range (the default when no flag is given)",
    )
    parser.add_argument("--stop", action="store_true", help="end THIS project's board")
    parser.add_argument("--dir", default=".", help="the project directory (default: .)")
    args = parser.parse_args(argv)
    cwd = Path(args.dir)
    if args.stop:
        result = stop(cwd)
        print(f"{result.action}: {result.detail}")
        return 0 if result.action in ("stopped", "none") else 1
    for text in report(cwd):
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
