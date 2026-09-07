"""Orchestration dashboard, adapted for keel - optional live viewer (read-only).

ADAPTED 2026-08-12 from the owner's own predecessor-harness dashboard (its
home is the sibling workspace project's skills tree; the path is not spelled
here by keel's own naming rule, convention 3). NOTHING VENDORED IS DELETED OR
REWORDED: the original's whole look and every client-side rule it shipped are
still here, and what keel has added to the HTML is fenced, every block of it,
by a ``KEEL ADDITION`` comment naming its task. Besides those fences, this
Python data layer is what changed:

1. It reads keel's records instead of the predecessor's:
   ``.keel/audit/keel-audit.jsonl`` for events (each event gains a
   ``session_id`` alias for its ``session`` field - the one rename the page
   expects; every other field already matches, because keel's schema is
   this page's descendant) and ``.keel/plans/keel-plan-*.md`` for ledgers
   (the newest by mtime is "the plan"; the rest are the archives).
2. ``read_siblings`` now reads keel's own user-global fleet registry (T227,
   ``hooks/keel_registry.py``) rather than returning nothing: each sibling
   carries a ``path``, never a ``port`` - the original's crc32-from-path port
   formula is the derived-port shape keel's R19 forbids repo-wide, so it was
   not carried, and no analogous mechanism replaces it (see the
   ``keel:deferred`` marker on ``read_siblings`` itself). ``main``'s derived
   default port is fixed at 8770 for the same reason - chosen, never
   computed - with the same +1 retry walk.
3. It WITHHOLDS, from the served copy only, both halves of a launch the
   record itself shows never took (T138) - the append-only log is never
   rewritten, and the count of what was withheld rides in the keel block so
   the omission is auditable. See ``unacknowledged_launch_ids``.
4. It serves the fingerprint of the CODE it is running - the registry-derived
   component digest the survey prints, and this page source's own digest -
   beside the same two values taken from disk at request time, so a reader can
   see that a long-running board has gone stale without restarting it (T168,
   closing T162's stale-board half). See ``served_code``.
5. Nothing else. ``scripts/keel_dashboard.py`` (keel's own viewer) is a
   separate program and is not touched by this one.

Usage:  python scripts/keel_orchestration_dashboard.py            (from the project root)
        python scripts/keel_orchestration_dashboard.py --dir <project> [--port 8770]

Security: binds 127.0.0.1 only; serves exactly three endpoints ("/",
"/api/state", "/api/plan"); reads only keel's own records; never writes
anything. Token cost: zero - it never calls any model.
"""
import argparse
import glob
import hmac
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# KEEL ADDITION (T122): keel's own truths come from keel's own code - the
# arming tier and the honest session pill are IMPORTED from the sibling
# viewer, never reimplemented, so there is exactly one place each is
# settled. A broken import crashes startup loudly rather than degrading to
# a page that quietly shows neither.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from keel_dashboard import arming as keel_arming  # noqa: E402
from keel_dashboard import session_liveness as keel_session_liveness  # noqa: E402

# KEEL ADDITION (T168, closing T162's stale-board half): the same rule as the
# import above - the fingerprint is keel's own single implementation, imported
# from the kernel module that owns it, never a second hash written here.
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hooks"
    ),
)
from keel_features import component_fingerprint as keel_component_fingerprint  # noqa: E402
from keel_features import path_digest as keel_path_digest  # noqa: E402

ROOT = None  # project dir, set in main()

# ---- KEEL ADDITION (T168): the board says which CODE it is serving --------
# MEASURED 2026-08-17 (T162): the board answering on 8770 was a process
# started the day before, serving a page baked into it at import - so page
# changes that had shipped were invisible to the only board the owner was
# looking at, and autostart behaved correctly by leaving that board alone.
# Nothing about a running server tells a reader its age, and the server must
# not be trusted to know it either.
#
# So both fingerprints below are captured HERE, at import, which is the moment
# the served page and the served data layer were fixed; the same two values are
# recomputed from disk on every request. Equal means this board is serving what
# the tree holds; different means it is stale and a reader can see so without
# restarting anything. Either fingerprint missing means UNKNOWN, which is
# reported as unknown rather than as either answer (T162's fourth clause).
#
# Two values, because they answer two halves of one question and neither
# covers the other: COMPONENTS is the registry-derived digest the survey prints
# (so a board and a survey can be compared), and the page source is not a
# registry component, so a change to this very file moves only PAGE. Nothing
# here restarts, kills or reclaims anything - reporting staleness is not
# licence to end another session's server.
PAGE_SOURCE = os.path.abspath(__file__)
SERVED_COMPONENTS_FP = keel_component_fingerprint().digest
SERVED_PAGE_FP = keel_path_digest(PAGE_SOURCE)


def served_code():
    """What this process is serving, against what is on disk right now.

    Read at REQUEST time for the disk half; the served half is the import-time
    constant above. ``stale`` is only ever True on positive evidence - two
    digests that both exist and differ - and ``unknown`` carries the case where
    a digest could not be taken at all, so no reader is told a board is current
    because something failed quietly.
    """
    components_disk = keel_component_fingerprint().digest
    page_disk = keel_path_digest(PAGE_SOURCE)
    known = bool(SERVED_COMPONENTS_FP and components_disk and SERVED_PAGE_FP and page_disk)
    stale = bool(
        (SERVED_COMPONENTS_FP and components_disk and components_disk != SERVED_COMPONENTS_FP)
        or (SERVED_PAGE_FP and page_disk and page_disk != SERVED_PAGE_FP)
    )
    # KEEL ADDITION (T338, owner review 2026-08-26): WHEN, beside WHICH. The
    # verdict above is untouched - the same two digests, the same positive-
    # evidence ``stale``, the same fail-honest ``unknown``; this adds one
    # field and derives nothing from it. The page used to print the page
    # digest as its chip, which answers a machine's question ("which bytes?")
    # where the reader's question is human ("is this current, and since
    # when?"). ``page_mtime`` is the page source's modification time ON DISK
    # at this request, which is the moment the served code last changed in
    # both states that can name one: equal digests mean the served bytes ARE
    # these bytes, so the mtime is when the running board's own code was last
    # written; different digests mean the file changed after this process
    # started, and the mtime is when that change landed. A time is not a path
    # - no directory, user or filename rides on the socket with it - and an
    # unreadable mtime is None, which the page draws as no time rather than
    # as "now".
    try:
        page_mtime = os.path.getmtime(PAGE_SOURCE)
    except OSError:
        page_mtime = None
    return {
        "components_fp": SERVED_COMPONENTS_FP,
        "components_fp_disk": components_disk,
        "page_fp": SERVED_PAGE_FP,
        "page_fp_disk": page_disk,
        "page_mtime": page_mtime,
        "stale": stale,
        "unknown": not known and not stale,
    }


# ---- KEEL ADDITION (T340): the viewer's FIRST WRITE VERB -------------------
# Every endpoint above only reads keel's own records; POST /api/restart is
# the one action this board can take, and it is exactly one action: replace
# this process with the same interpreter, on the same file, with the same
# argv it was started with. Nothing about WHAT gets restarted comes from the
# request - there is no request-controlled input to this endpoint at all,
# only a yes/no gate in front of a fixed, request-independent effect.
#
# The gate exists because a loopback bind is not, by itself, a credential a
# browser respects: a page open in another tab (any origin) can still have
# JavaScript issue a request to 127.0.0.1 from the browser sitting on this
# machine. So:
#   - a per-process token, drawn fresh at import with ``secrets.token_hex``
#     and never derived from anything a page could guess or read, must come
#     back in a CUSTOM request header (``X-Keel-Restart``, not a cookie and
#     not a query string, both of which a cross-origin request can send
#     without asking). A cross-origin page cannot read this token out of
#     THIS page's DOM - the same-origin policy forbids it - and cannot even
#     get the header onto the wire without the browser first sending a CORS
#     preflight (``OPTIONS``) that this server never answers (no
#     ``OPTIONS`` handler and no ``Access-Control-Allow-*`` header exists
#     anywhere in this file), so a forged request never reaches the compare
#     below;
#   - POST-only, closing the plain cross-site vectors that need no preflight
#     at all (an ``<img>`` tag, a bare ``<form>``) - those can only issue
#     GET or a handful of simple-request POSTs, none of which can attach the
#     custom header above;
#   - the ``Host`` header is checked against loopback, so a request that
#     reached this process through some other binding still answers refused;
#   - and the token compare is constant-time (``hmac.compare_digest``), so a
#     wrong guess cannot be timed into a right one.
# Any failure is 403 (or 405 for a non-POST method) and changes nothing; the
# refusal is also printed to stderr, once, so a reader watching the process
# sees every attempt this board declined.
#
# What this endpoint does NOT add: new authority over the machine. The
# re-exec runs whatever is ALREADY on disk at ``PAGE_SOURCE`` - an attacker
# able to rewrite that file has already won the machine outright, and this
# endpoint is then a shortcut to a restart that attacker could already
# script by hand. The guards above are about who may ask this loopback
# process to restart ITSELF, not about defending the file it re-execs.
RESTART_TOKEN = secrets.token_hex(32)  # keel-leak: ignore - generated per process, never stored or shipped
RESTART_HEADER = "X-Keel-Restart"
#: Captured at import, long before any request exists - never re-read from a
#: request, an environment variable a request could have raced, or anything
#: else that could make "the same argv" mean something a request chose.
_ORIGINAL_ARGV = list(sys.argv)
#: Set by ``main()`` once ``bind_walk`` hands back the live server, so the
#: restart can close the listening socket it is actually holding. ``None``
#: until then (e.g. under test, where no server is ever bound).
_SERVER = None
#: KEEL ADDITION (T443 follow-up): set by the daemon timer, read by ``main()``
#: on its OWN thread after ``serve_forever`` returns - see the block comment
#: above ``schedule_restart`` for the race this flag exists to avoid. Never
#: read or written from a request handler thread; the timer thread only ever
#: sets it, ``main()`` only ever reads and clears it.
_RESTART_REQUESTED = False
#: A test seam, not a config knob: the ONE call that ends the process, bound
#: here so a test can replace ``keel_orchestration_dashboard._EXECV`` alone
#: rather than the shared ``os`` module every other test in this suite (and
#: outside it) also imports.
_EXECV = os.execv
# ---- KEEL ADDITION (T443): the Windows half of the same restart ----------
# MEASURED 2026-09-02: on Windows, ``os.execv`` is not a real exec - CPython
# emulates it (spawn a replacement with DEFAULT creation flags, then exit the
# caller). A replacement spawned with default flags by a console-less parent
# (the ordinary case: the board is autostarted DETACHED by
# ``hooks/keel_liveview.py``) is handed a BRAND NEW console by Windows
# itself - that console is the bug: a visible ``python.exe`` window pops on
# every click of the restart button. POSIX's ``os.execv`` has no such
# problem - it replaces the process image in place, same PID, same console
# (or lack of one) - and stays exactly as it was, untouched, byte for byte.
#
# So on Windows this module performs the same two-step by hand: spawn the
# replacement DETACHED, with the SAME creation flags the autostart itself
# already uses (``DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`` - see
# ``hooks/keel_liveview.py``'s own spawn), so the replacement is exactly as
# console-less as the parent it replaces; then end this process with
# ``os._exit`` rather than a plain return or ``sys.exit`` - no atexit
# handler runs and reaches for the socket ``_close_server_socket`` already
# closed, and nothing after the spawn can turn a restart into a stack trace
# on stderr.
#
# Two seams, not one call, for the same reason ``_EXECV`` is a seam: a test
# must be able to pin the exact argv and creation flags this builds WITHOUT
# spawning a real process or ending the test's own. ``_SPAWN`` stands in for
# ``subprocess.Popen`` and ``_EXIT`` for ``os._exit`` - both real and
# unpatched outside a test.
_SPAWN = subprocess.Popen
_EXIT = os._exit


def _is_windows():
    """``os.name == "nt"`` behind a seam, so a test can pin the Windows
    branch of ``_reexec_same_process`` on any platform without patching the
    shared ``os`` module's own ``name`` attribute for every other test in
    this process."""
    return os.name == "nt"


def _loopback_host(host_header):
    """True when ``host_header`` (the request's raw ``Host:`` value) names
    loopback - ``127.0.0.1`` or ``localhost``, with or without a ``:port``
    suffix. Empty, missing or any other name is False; nothing is assumed."""
    if not host_header:
        return False
    name = host_header.strip().rsplit(":", 1)[0].strip().lower()
    return name in ("127.0.0.1", "localhost")


def restart_authorized(method, header_token, host_header):
    """The pure guard behind ``POST /api/restart`` - every check named in the
    block comment above, none of the side effects. This is the seam the test
    suite exercises directly: a live socket and a real re-exec are not
    needed to prove the gate opens and closes on the right inputs.

    Returns ``(True, "")`` when the request is authorized, or
    ``(False, reason)`` naming the first failed check - method before token
    before host, so a GET is always "method not allowed" regardless of what
    else it carries.
    """
    if method != "POST":
        return False, "method not allowed"
    if not header_token or not hmac.compare_digest(header_token, RESTART_TOKEN):
        return False, "restart token missing or wrong"
    if not _loopback_host(host_header):
        return False, "host is not loopback"
    return True, ""


def _close_server_socket():
    """Best-effort release of the listening port before the re-exec.

    Windows note (the same hazard ``bind_walk``'s own comment documents for
    socket inheritance): ``os.execv`` replaces this process's image but a
    listening socket can outlive the call unless it is shut down first, which
    would leave the re-exec'd process unable to rebind the port it just
    vacated. So this always runs BEFORE the re-exec, never left to it.

    KEEL ADDITION (T443 follow-up): this is now ONLY ever called from the
    main thread, after ``serve_forever`` has already returned (see
    ``main()`` and ``schedule_restart``'s block comment for why). Nobody is
    ever ``select()``-ing on this socket when it closes, which is exactly
    the property the previous, timer-thread-closes-it design lacked.
    """
    if _SERVER is not None:
        try:
            _SERVER.socket.close()
        except OSError:
            pass


def _reexec_same_process():
    """Replace this process with the same interpreter, same file, same argv.

    Nothing from the request that authorized this call reaches here -
    ``_ORIGINAL_ARGV`` was frozen at import, before any request existed.

    POSIX goes through ``_EXECV`` (see its module-level comment) so a test
    can pin the exact argv this builds without ending the test process; only
    a REAL, unpatched ``_EXECV`` actually replaces anything - the process
    image changes in place, same PID.

    Windows (T443, see ``_SPAWN``'s module-level comment for why) builds the
    identical argv but spawns it by hand, DETACHED, through ``_SPAWN`` (the
    same seam discipline: a test pins argv and flags without spawning
    anything real), then ends this process through ``_EXIT``.

    stdin is DEVNULL; stdout/stderr are left UNSET, which is
    ``subprocess.Popen``'s own default - inherit the parent's handles - and
    that default is deliberate, not an oversight. A board launched with a
    piped stdout (this file's own real-restart test, and any developer
    watching a foreground run) must keep writing its SECOND startup banner
    to that SAME pipe after a restart, or the only outside proof a restart
    happened - a second banner line on the ORIGINAL child's stdout - goes
    dark. A board autostarted DETACHED by ``hooks/keel_liveview.py`` already
    has stdout at DEVNULL, and inheriting DEVNULL is still DEVNULL. Either
    way, inheriting is correct: the replacement's stdout is whatever the
    caller's already was, never redirected here.
    """
    if _is_windows():
        _SPAWN(
            [sys.executable, PAGE_SOURCE, *_ORIGINAL_ARGV[1:]],
            creationflags=(
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            ),
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        _EXIT(0)
        return
    _EXECV(sys.executable, [sys.executable, PAGE_SOURCE, *_ORIGINAL_ARGV[1:]])


def _perform_restart():
    """Close the socket, THEN re-exec - see ``_close_server_socket``'s note
    on why the order is fixed rather than left to chance.

    KEEL ADDITION (T443 follow-up): called ONLY from ``main()``, on the main
    thread, after ``serve_forever`` has returned - never from the timer
    thread ``schedule_restart`` starts. See that function's block comment
    for the race this split exists to close.
    """
    _close_server_socket()
    _reexec_same_process()


def _request_restart():
    """The daemon timer's WHOLE job (T443 follow-up) - request a restart and
    get ``serve_forever`` to return, nothing more.

    THE RACE THIS REPLACES. The previous design fired ``_perform_restart``
    (close-socket-then-re-exec) directly on the timer thread. The MAIN
    thread is, at that moment, blocked inside ``serve_forever``'s
    ``selector.select()`` on that very socket; closing a socket a select()
    is blocked on raises ``OSError: [WinError 10038]`` (Windows) in the
    thread doing the selecting - the MAIN thread - which then propagates out
    of ``main()`` as an unhandled traceback. Interpreter shutdown that
    follows can end the daemon timer thread before, or while, it reaches the
    re-exec/spawn - so a lost race left NO process answering the port at
    all (Ran-three-times evidence: OK, FAILED, OK - a lost race is
    microseconds-timed, not deterministic).
    THE FIX. Nothing that touches the socket or the process image runs on
    this thread any more. ``BaseServer.shutdown()`` (the stdlib base class
    every server here descends from) is EXPLICITLY documented as safe to
    call from another thread while ``serve_forever`` is running elsewhere -
    it sets an internal event and blocks until the running loop notices it
    and returns, never touching the listening socket itself. So this thread
    only sets the flag ``main()`` reads and asks ``serve_forever`` to stop;
    ``_perform_restart`` (the socket close, the re-exec/spawn) runs
    afterwards, on the main thread, with nobody left selecting on anything.
    """
    global _RESTART_REQUESTED
    _RESTART_REQUESTED = True
    if _SERVER is not None:
        _SERVER.shutdown()


def schedule_restart(delay=0.2):
    """Fire ``_request_restart`` on a daemon timer ``delay`` seconds out.

    The delay is so the 200 response that authorized this call finishes
    writing to ITS OWN client socket before ``serve_forever`` is asked to
    stop. This server is a ``ThreadingHTTPServer``: every request, including
    the one that authorized this restart, is handled on ITS OWN worker
    thread, already independent of the main thread's accept loop - by the
    time this handler returns 200 the response bytes are already written to
    that connection's socket, not queued behind anything ``shutdown()``
    could interrupt. The delay is still kept (rather than calling
    ``_request_restart`` from the handler thread directly) so the handler
    method has visibly returned and its connection is closing cleanly before
    the accept loop stops, and so a restart that races a slow client write
    does not appear to cut a response off. A daemon thread never blocks
    process exit on its own, so a restart that somehow never fires cannot
    hang the process either.

    KEEL ADDITION (T627, BL59): the timer is REGISTERED before it is started,
    so a caller that did not create it can still reach it - see
    ``_RESTART_TIMERS`` below for why that matters. Registration happens
    before ``start()``, never after, so there is no window in which a live
    timer exists that ``cancel_pending_restarts`` cannot see.
    """
    timer = threading.Timer(delay, _request_restart)
    timer.daemon = True
    _register_restart_timer(timer)
    timer.start()
    return timer


# ---- KEEL ADDITION (T627, BL59): a restart timer is reachable, not stray ----
# The board schedules a restart from a REQUEST thread (``_answer_restart``
# calls ``schedule_restart()`` and drops the returned timer on the floor -
# production has no use for the handle, because production restarts). A test
# that stands the handler up in-process does: the timer it caused is live in
# the TEST RUNNER's own process, and ``_request_restart`` reads the MODULE
# global ``_SERVER`` when it fires, not when it was scheduled - so a timer
# outliving the fixture that caused it acts on whatever the module looks like
# later. BL59 records the unproven suspicion that such a stray timer is what
# ends a full-discovery run mid-suite with exit 0.
#
# This registry is the smallest thing that makes the stray reachable: every
# scheduled timer is remembered, dead ones are pruned on each new schedule so
# a board running for days keeps at most a handful, and a caller (the test
# fixture in ``tests/test_keel_dashboard_t340.py``) can cancel and join what
# is still pending. Nothing here changes what a restart DOES - the timer, its
# delay, its daemon flag and its callback are exactly what they were.
_RESTART_TIMERS_LOCK = threading.Lock()
_RESTART_TIMERS = []


def _register_restart_timer(timer):
    """Remember ``timer``, forgetting any already-finished ones."""
    with _RESTART_TIMERS_LOCK:
        _RESTART_TIMERS[:] = [t for t in _RESTART_TIMERS if t.is_alive()]
        _RESTART_TIMERS.append(timer)


def pending_restart_timers():
    """The scheduled restart timers still alive right now (usually none)."""
    with _RESTART_TIMERS_LOCK:
        return [t for t in _RESTART_TIMERS if t.is_alive()]


def cancel_pending_restarts(timeout=5.0):
    """Cancel every registered restart timer and wait for its thread to end.

    Returns the timers that were STILL alive after ``timeout`` - an empty
    list is the proof a caller wants ("nothing of mine is left running"), a
    non-empty one names what refused to stop rather than hiding it.

    A registered-but-not-yet-started timer is cancelled too (``cancel`` sets
    the finished event, so a later ``start`` returns without calling
    anything) but never joined - joining an unstarted thread raises.
    """
    with _RESTART_TIMERS_LOCK:
        timers = list(_RESTART_TIMERS)
    for timer in timers:
        timer.cancel()
    for timer in timers:
        if timer.is_alive():
            timer.join(timeout)
    with _RESTART_TIMERS_LOCK:
        _RESTART_TIMERS[:] = [t for t in _RESTART_TIMERS if t.is_alive()]
    return [t for t in timers if t.is_alive()]


def _plan_files():
    """Keel ledgers, newest first by mtime; [] when the dir is missing."""
    pattern = os.path.join(ROOT, ".keel", "plans", "keel-plan-*.md")
    try:
        return sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    except OSError:
        return []


# ---- KEEL ADDITION (T142): the ledger name the page actually asks for ----
# The page looks a round's ledger up by ``plan-<sess8>.md`` - its own comment
# says why: "per-session plans: each round's ledger is its own plan file" -
# and keel names that very file ``keel-plan-<sess8>.md``. The eight characters
# already match exactly, because a keel ledger IS named for its session; the
# only thing standing between the page and the right ledger was five letters
# of prefix. So the served list carries BOTH names for every ledger: the real
# one, which is what the record calls it, and the alias, which is what the
# page asks for. Nothing is renamed on disk and no vendored line changes.
#
# Two things were dark before this and are lit by the same alias: the session
# switcher's subject line (it fetches ``plan-<sess8>.md`` to read the plan's
# title, and showed the raw eight characters when the fetch never fired) and
# the per-round ledger panel (it fetches the same name, and fell through to an
# empty panel).
#
# The page's OTHER archive path - ``stampTs``, which parses
# ``plan-YYYYmmdd-HHMMSS.md`` - stays inert, and that is a correct outcome
# rather than an unfinished one: it reads the predecessor's TIMED SNAPSHOTS,
# a convention keel does not keep. keel writes one ledger per session, which
# is exactly the case this alias serves. Feeding that fallback would mean
# inventing timestamped names for snapshots keel never took.
PLAN_PREFIX = "keel-plan-"
ALIAS_PREFIX = "plan-"


def _archive_alias(basename):
    """``keel-plan-<sess8>.md`` -> ``plan-<sess8>.md``; None when not a ledger."""
    if not (basename.startswith(PLAN_PREFIX) and basename.endswith(".md")):
        return None
    return ALIAS_PREFIX + basename[len(PLAN_PREFIX):]


# ---- KEEL ADDITION (T144): which project this server is serving ----------
# The session hook may start this viewer by itself, and to do that honestly it
# has to answer one question first: is the server already on this port MINE?
# Liveness alone cannot answer it - two projects can be open at once and the
# port walk means either may hold 8770, so a bare "something answered" would
# hand one project's session the other project's board.
#
# The answer is a fingerprint rather than the path itself. A viewer has no
# business putting an absolute home path on a socket, even a loopback one,
# and nothing needs the path back: the only question ever asked of this value
# is whether two of them are equal. ``normcase``+``realpath`` first, so the
# same directory spelled differently by a shell and by a hook still matches.
#
# This is the ONE implementation. The hook imports it from here rather than
# hashing a path of its own, so the two halves can never disagree about
# identity - the same single-place rule the arming chip and the session pill
# already follow.
def root_fingerprint(root):
    """A stable, non-reversible name for one project directory."""
    import hashlib

    resolved = os.path.normcase(os.path.realpath(str(root)))
    return hashlib.sha256(resolved.encode("utf-8", "replace")).hexdigest()[:16]


# ---- KEEL ADDITION (T138): a launch the record shows never took ----------
# The page has exactly one way to read an unpaired ``handoff_start``: the
# agent is WORKING, until ABANDON_MS (two hours) says otherwise. That is the
# right reading for a live background agent and the wrong one for a launch
# that was rejected or killed, which never returns and never stops - the
# owner watched four such cards read "working - stalled?" for hours on
# 2026-08-13. The log is APPEND-ONLY and is not rewritten; what changes is
# the SERVED copy, which withholds the hand-off lines of launches the record
# itself shows are over. Nothing is withheld silently: the count rides in the
# keel block below, and the log keeps every line forever.
#
# The wire values are spelled here rather than imported: this layer reads
# keel's records the way any outside reader does, and a rule that imported the
# names it matches could not notice them drifting.
HANDOFF_OPEN_EVENT = "handoff_start"
HANDOFF_CLOSE_EVENT = "handoff_end"
HANDOFF_KIND_KEY = "handoff_kind"
HANDOFF_KIND_RESUME = "resume"
LAUNCH_ACK_KEY = "launch_ack"


# ---- KEEL ADDITION (T312): a delegated task's brief never ships in full --
# ``prompt_head`` is already bounded at CAPTURE time
# (``hooks/keel_capture.py``'s ``PROMPT_HEAD_CHARS``, 200 chars) - this layer
# leaves it alone. ``description`` carries no such bound: it is the send's
# own summary, and the page's card renders it under a CSS two-line clamp
# (``-webkit-line-clamp:2``) that hides overflow visually while the full
# string still sits in the DOM behind it - and the detail drawer's header
# prints it with no clamp at all. A long delegation brief would therefore
# reach every open tab in full regardless of what CSS hides, so the SERVED
# copy is cut here, once, for every reader of this field: the on-disk
# record is never touched, only what this layer hands the page.
#
# KEEL ADDITION (T335, owner review of the live drawer 2026-08-26): THE
# CEILING MOVES, THE PRINCIPLE DOES NOT. The owner opened the drawer on a
# working agent and could not read the end of its own task brief: 300 chars
# cut a real delegation mid-sentence, and the drawer had no way to show the
# rest because the rest never left this process. The bound exists so that no
# UNBOUNDED string rides the socket - that is still true at 2000, which is
# the size of a full task brief in this project's own ledger (the longest
# ``description`` in this repository's log measures well under it), not the
# size of a prompt. Bypassing the cut for the drawer alone was the other
# option and is refused: it would put the unbounded string back on the wire
# for every reader of /api/state, which is exactly what T312 closed.
DESCRIPTION_PREVIEW_CHARS = 2000


def _truncate_preview(text, limit=DESCRIPTION_PREVIEW_CHARS):
    """``text`` unchanged when it already fits; else cut to ``limit`` chars
    plus a trailing ellipsis - never the full string beyond that bound."""
    if not isinstance(text, str) or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _launch_identity(ev):
    """What makes two launch lines THE SAME delegation, or None for "unknown".

    Session, agent type and description - the very key ``pairEvents`` falls
    back to when a hand-off carries no ``tool_use_id``, reused here rather
    than invented, and scoped to one session so that a new session repeating
    a task can never close an older session's still-running agent.

    ALL THREE MUST BE THERE. A line missing any of them has no identity to
    compare, and answering None says so rather than letting two blanks match
    each other: a resume records a null ``subagent_type``, an older line may
    record no ``description`` at all, and an identity built from those would
    make every such launch the same delegation as every other. An unknown
    identity is never superseded and never supersedes.
    """
    identity = (
        ev.get("session") or ev.get("session_id"),
        ev.get("subagent_type"),
        ev.get("description"),
    )
    if any(not isinstance(part, str) or not part.strip() for part in identity):
        return None
    return identity


def unacknowledged_launch_ids(handoffs):
    """``tool_use_id``s of LAUNCH hand-offs the record shows never took.

    TWO MEASURED FORMS, and each is evidence in the log rather than a guess
    about an agent:

    1. A close half saying so - ``launch_ack: false`` (T138 capture side): the
       launch tool answered, and its answer was not an acknowledgment. Only a
       literal ``false`` counts; a null means nothing could be judged.
    2. A LATER ATTEMPT AT THE SAME DELEGATION THAT ITSELF CLOSED, where this
       one never got a close half at all. That is the shape the four rejected
       launches of 2026-08-13T15:15Z left behind - a rejected call fires no
       PostToolUse in this harness, so no close half exists to carry the
       marker above, and what the record does hold is that the same session
       dispatched the same task to the same agent again 12 minutes later AND
       that the second attempt was acknowledged (measured: all four relaunches
       closed with a background acknowledgment seconds in). A superseded
       delegation whose successor took is not still working.

    THE SUCCESSOR MUST HAVE CLOSED, and that qualifier is the whole safety of
    rule 2 rather than a detail of it. Mere repetition is NOT evidence: this
    project's own log dispatches identical work in parallel (four
    ``handoff_start`` lines seconds apart at 15:15Z), and a rule that read "a
    later twin exists" would withhold the earlier of two agents that are BOTH
    running right now. A successor that has itself been acknowledged is a
    different fact - it says the delegation was taken up again after this
    attempt produced nothing.

    WHAT THIS MAY NOT CATCH IS THE POINT. A launch that really was
    acknowledged always has a close half (measured: 268 of 268 results are
    acknowledgments carrying an agent id), so rule 2 can never fire on one -
    it requires the ABSENCE of any close half on the attempt it withholds. A
    concurrent live twin cannot trigger it either, having no close half of its
    own; an identity missing any of its three parts is skipped entirely (see
    ``_launch_identity``); and a RESUME is skipped outright, because a resume
    carries its target's agent id on both halves and is not a launch at all
    (T124). The failure this leans towards is leaving a ghost on the page,
    never removing a working agent from it.
    """
    closed, withheld, opens = set(), set(), []
    for ev in handoffs:
        if ev.get(HANDOFF_KIND_KEY) == HANDOFF_KIND_RESUME:
            continue
        uid = ev.get("tool_use_id")
        if not isinstance(uid, str) or not uid:
            continue
        kind = ev.get("event")
        if kind == HANDOFF_CLOSE_EVENT:
            closed.add(uid)
            if ev.get(LAUNCH_ACK_KEY) is False:
                withheld.add(uid)
        elif kind == HANDOFF_OPEN_EVENT:
            identity = _launch_identity(ev)
            if identity is not None:
                opens.append((uid, identity))
    # Walked backwards, so that what is known at each open is what came AFTER
    # it: how many later attempts at this same delegation were acknowledged.
    closed_later = {}
    for uid, identity in reversed(opens):
        if uid not in closed and closed_later.get(identity, 0) > 0:
            withheld.add(uid)
        if uid in closed:
            closed_later[identity] = closed_later.get(identity, 0) + 1
    return withheld


def _is_withheld_handoff(ev, withheld):
    """True for either half of a withheld launch, and for nothing else."""
    return (
        ev.get("event") in (HANDOFF_OPEN_EVENT, HANDOFF_CLOSE_EVENT)
        and ev.get("tool_use_id") in withheld
    )


def read_state():
    log_path = os.path.join(ROOT, ".keel", "audit", "keel-audit.jsonl")
    # Keel's log is DOMINATED by per-tool ``activity`` lines the
    # predecessor never wrote, so a single last-400 window can be pure
    # activity and starve the page of every hand-off. Two windows instead:
    # the last 400 activity lines (drawers, stall detection, liveness all
    # read them) and the last 400 of everything else, merged back into log
    # order. Same page diet as the original, adapted to a noisier log.
    activity = []
    rest = []
    handoffs = []  # KEEL ADDITION (T138): every hand-off line, unwindowed
    log_mtime = plan_mtime = None
    try:
        log_mtime = os.path.getmtime(log_path)
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                # The one rename the page expects: keel writes ``session``,
                # the page reads ``session_id``. Alias, never move - the
                # original field stays for anything else reading this JSON.
                if "session" in ev and "session_id" not in ev:
                    ev["session_id"] = ev["session"]
                # One coercion: keel writes ``detail`` as a mapping on gate
                # events; the page's renderers expect a string and its
                # ``esc()`` throws on anything else - which kills the whole
                # tick inside a catch that renders as "disconnected".
                # KEEL ADDITION (T342): LIFT THE STOP COUNTS BEFORE THAT
                # STRINGIFY. ``hooks/keel_stop.py`` nests its three counts
                # inside ``detail``; the page's feed verb read a top-level
                # ``open_items`` that has therefore never existed, and every
                # stop_block line on every board has read "undefined plan
                # item(s)" since the verb was written. The counts are promoted
                # here, beside the other served-copy compositions below, so the
                # renderer keeps reading plain numbers - and all THREE are
                # lifted, not just the open one: this gate also blocks on stale
                # in-flight items and on filed claims the backlog does not back,
                # so a line reporting only ``open_items`` would say "0" for a
                # block that really happened.
                if isinstance(ev.get("detail"), dict):
                    for _count in (
                        "open_items",
                        "stale_inflight_items",
                        "unverified_filed_items",
                    ):
                        if _count not in ev and isinstance(ev["detail"].get(_count), int):
                            ev[_count] = ev["detail"][_count]
                # Stringify, never drop.
                if "detail" in ev and not isinstance(ev["detail"], str):
                    ev["detail"] = json.dumps(ev["detail"], ensure_ascii=False)
                # KEEL ADDITION (T123): the page's card tag reads ``model``
                # and its own idiom folds effort into it ("opus · high" in
                # its persona table), so the SERVED copy composes the
                # record's two honest fields into that one display word.
                # Absence stays absent - the page then falls back to its
                # own generic vocabulary, never to a guess made here.
                model = ev.get("model")
                effort = ev.get("effort")
                if isinstance(model, str) and model and isinstance(effort, str) and effort:
                    ev["model"] = f"{model} · {effort}"
                # KEEL ADDITION (T312): see ``_truncate_preview`` above - the
                # only field this touches is ``description``; ``prompt_head``
                # is already bounded at capture and is served as-is.
                if "description" in ev:
                    ev["description"] = _truncate_preview(ev["description"])
                # KEEL ADDITION (T138): the never-took rule is decided over
                # the WHOLE log, before either window narrows it - a ghost's
                # own evidence (the relaunch that superseded it) may sit any
                # distance away in the file.
                if ev.get("event") in (HANDOFF_OPEN_EVENT, HANDOFF_CLOSE_EVENT):
                    handoffs.append(ev)
                (activity if ev.get("event") == "activity" else rest).append(
                    (idx, ev)
                )
    except OSError:
        pass
    # KEEL ADDITION (T138): withhold both halves of every launch the record
    # shows never took, BEFORE the window - so the four ghosts give their
    # seats back to four real events rather than merely vanishing.
    withheld = unacknowledged_launch_ids(handoffs)
    if withheld:
        rest = [pair for pair in rest if not _is_withheld_handoff(pair[1], withheld)]
    merged = sorted(activity[-400:] + rest[-400:], key=lambda pair: pair[0])
    events = [ev for _, ev in merged]
    # KEEL ADDITION (T122): the newest session the page will draw, found the
    # same way the page finds it (last event carrying a session), so the
    # honest pill describes what the canvas shows - the T108 lesson.
    latest_session = None
    for ev in reversed(events):
        sid = ev.get("session") or ev.get("session_id")
        if sid:
            latest_session = sid
            break
    keel_block = {
        "arming": keel_arming(Path(ROOT)),
        # KEEL ADDITION (T144): the served identity the autostart probe reads.
        # The page itself never draws it; it is here so a hook can tell this
        # project's board from another project's on the same port.
        "root_fp": root_fingerprint(ROOT),
        # KEEL ADDITION (T147): what a board can say about itself that nobody
        # outside can find out. MEASURED 2026-08-16: a board whose project was
        # deleted underneath it keeps answering 200 with the same name and the
        # same fingerprint, so from outside it is indistinguishable from a
        # quiet project that was never armed - which is why nothing could ever
        # reclaim a seat from a project that is gone. The fingerprint is a
        # hash, so it can never be resolved back to a directory to check.
        # These three are facts only the serving process holds.
        "pid": os.getpid(),
        "root_present": os.path.isdir(ROOT),
        "adopted": os.path.isdir(os.path.join(ROOT, ".keel")),
        # KEEL ADDITION (T138): what this response withheld as never-took -
        # the count AND the ``tool_use_id`` of each, so the withholding can be
        # checked line by line against the log rather than taken on trust. The
        # page ignores keys it never heard of, and the audit log still holds
        # every one of those lines.
        "withheld_launches": len(withheld),
        "withheld_launch_ids": sorted(withheld),
        # KEEL ADDITION (T168): the component fingerprint the survey prints,
        # plus this page's own, each as SERVED and as it stands on disk at this
        # request. The page prints the comparison; it derives nothing.
        "code": served_code(),
        "liveness": (
            keel_session_liveness(events, latest_session, time.time())
            if latest_session
            else None
        ),
    }
    plan = ""
    plans = _plan_files()
    if plans:
        try:
            plan_mtime = os.path.getmtime(plans[0])
            with open(plans[0], encoding="utf-8", errors="replace") as f:
                plan = f.read()
        except OSError:
            pass
    # KEEL ADDITION (T142): real names AND the page's own alias for each.
    names = []
    for path in plans:
        base = os.path.basename(path)
        names.append(base)
        alias = _archive_alias(base)
        if alias:
            names.append(alias)
    archives = sorted(names)
    return {
        "project": os.path.basename(os.path.abspath(ROOT)),
        "keel": keel_block,  # KEEL ADDITION (T122)
        "events": events,
        "plan": plan,
        "plan_archives": archives,
        "siblings": read_siblings(ROOT),
        "log_mtime": log_mtime,
        "plan_mtime": plan_mtime,
        "now": time.time(),
    }


def read_siblings(root):
    """Every OTHER adopted project keel's own fleet registry currently names,
    excluding ``root`` itself, filtered to paths that still exist on disk
    (T227). The registry is built and pruned by ``hooks/keel_session.py`` at
    session start, over there - this reader parses nothing of its own, so it
    cannot disagree with what a session actually wrote (R15's one-parser
    rule); see
    ``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md``.

    keel:deferred(ceiling=each entry carries only a ``path``, never a
    ``port`` - the predecessor's own crc32-from-path formula that filled that
    field is exactly the derived-port shape R19 forbids, and keel's boards do
    not bind a deterministic port, so there is no analogous value to put
    there; trigger=when a sibling's board needs to be reachable FROM this
    selector, resolve its port from that sibling's own recorded live-view
    hint (``<sibling>/.keel/cache/live-view.json``, the same hint
    ``hooks/keel_liveview.py`` writes for itself) rather than reviving a
    derived-port formula.)
    """
    try:
        import keel_registry  # noqa: PLC0415 - hooks dir already on sys.path, see above

        here = os.path.normcase(os.path.abspath(str(root)))
        siblings = []
        for path in keel_registry.read():
            if os.path.normcase(str(path)) == here:
                continue
            siblings.append({"path": str(path)})
        return siblings
    except Exception:  # noqa: BLE001 - a board that cannot list siblings still serves itself
        return []


def read_archive(name):
    """Strictly-validated archived ledger fetch (basename only, keel shape).

    KEEL ADDITION (T142): the page's own ``plan-<sess8>.md`` alias resolves
    here as well as the real ``keel-plan-<sess8>.md``. Resolution is by
    LOOKUP against the ledgers keel itself listed - the requested name is
    never pasted into a path - so the only files this endpoint can open are
    files ``_plan_files`` already returned, which is a strictly tighter rule
    than the prefix test it replaces rather than a loosening of it.
    """
    if name != os.path.basename(name) or not name.endswith(".md"):
        return None
    for path in _plan_files():
        base = os.path.basename(path)
        if name == base or name == _archive_alias(base):
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    return f.read()
            except OSError:
                return None
    return None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/restart":
            # KEEL ADDITION (T340): a GET here is refused exactly like any
            # other non-POST attempt - see ``restart_authorized``.
            self._answer_restart("GET")
            return
        if self.path == "/" or self.path.startswith("/index"):
            # KEEL ADDITION (T340): the per-process restart token is baked
            # into the served page here, at request time - never written
            # into ``HTML`` itself, which stays one static string shared by
            # every request this process answers.
            body = HTML.replace("__KEEL_RESTART_TOKEN__", RESTART_TOKEN).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path.startswith("/api/state"):
            body = json.dumps(read_state()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path.startswith("/api/plan?name="):
            from urllib.parse import unquote

            content = read_archive(unquote(self.path.split("name=", 1)[1]))
            if content is None:
                body = b"not found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
            else:
                body = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
        else:
            body = b"not found"
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # KEEL ADDITION (T340): the viewer's first write verb. ``do_POST`` exists
    # for exactly one path; everything else POSTed here is answered 404,
    # same as an unknown GET.
    def do_POST(self):
        if self.path == "/api/restart":
            self._answer_restart("POST")
            return
        body = b"not found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _answer_restart(self, method):
        """Guard, then either refuse (nothing changes) or restart.

        The guard is the pure ``restart_authorized`` - this method only maps
        its answer onto an HTTP response and, on success, the two side
        effects: respond 200 FIRST (so the client learns before anything
        closes), flush, then schedule the close-then-re-exec.
        """
        header_token = self.headers.get(RESTART_HEADER, "")  # keel-leak: ignore - reads a request header; holds no secret
        host_header = self.headers.get("Host", "")
        ok, reason = restart_authorized(method, header_token, host_header)
        if not ok:
            # KEEL ADDITION (T340): a refusal is visible - one stderr line -
            # and answers an error; it changes nothing else.
            print(f"KEEL: restart refused ({reason})", file=sys.stderr)
            status = 405 if reason == "method not allowed" else 403
            body = f"refused: {reason}".encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        body = b"restarting"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()
        # The response above is already on the wire; only now does the
        # process act on the (request-independent) decision to restart.
        schedule_restart()

    def log_message(self, *a):  # silence per-request console noise
        pass


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Orchestration — live</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Ctext x='32' y='52' font-size='52' text-anchor='middle'%3E%E2%9A%93%3C/text%3E%3C/svg%3E">
<style>
/* KEEL ADDITION (T332, owner adjustment 2026-08-25): the surface palette is
   NEUTRAL GREY, not blue-navy. Only the hue is drained - every value below
   keeps the lightness relationship the vendored ramp had (bg darkest, then
   card, panel, panel2, line), so contrast and depth read exactly as before.
   The persona accents (the second :root rule below, --captain gold through
   --trimmer green) and every state colour (--good/--bad/--warn) are
   UNTOUCHED: ownership and state must still read by colour, and a grey
   accent would delete the only signal telling one crew member from another. */
:root{
  --bg:#121316; --panel:#191a1e; --panel2:#202226; --card:#1b1d21;
  --line:#33363c; --ink:#f0f1f4; --ink2:#adb0b6; --ink3:#6b6e76;
  --maestro:#eec25f; --scout:#38c2b1; --forge:#5f9dfb; --sage:#ab8bff;
  --counsel:#f0925a; --generic:#8a93a8;
  --good:#46c988; --bad:#ef6470; --warn:#e9ba3a;
}
/* KEEL ADDITION (T132): the crew's own accents - a second :root rule that
   only ADDS custom properties; the vendored :root above is byte-identical.
   Captain (keel's own orchestrator identity) and the eight keel:* roles
   each get a distinct hue, reusing the vendored palette's saturation/value
   feel rather than clashing with it. */
:root{
  --captain:#e8c34a; --lookout:#38c2b1; --shipwright:#5f9dfb;
  --chief:#ab8bff; --surveyor:#6fd1e8; --arms:#ef6470;
  --leadsman:#4fb0e0; --gunner:#e98a3a; --trimmer:#7fd48a;
}
/* KEEL ADDITION (T333, owner review 2026-08-25): ONE colour for task wiring,
   and it is nobody's persona. A hub->task wire used to inherit the hub's
   accent, which made the fractal layer speak the Captain->agent language -
   gold wire from the Captain, blue from the Shipwright - and the two kinds of
   wiring stopped being distinguishable at a glance. --taskwire is that second
   language, used by EVERY task wire including the Captain's self-run tasks:
   gold stays exclusively the Captain<->agent line.
   WHY THIS VALUE: every persona accent in the two rules above is a HIGH
   saturation hue (the least saturated, --generic #8a93a8, is 30 points of
   max-min; the rest run 100-175) and every surface is neutral grey (under 12).
   #c9b08c sits deliberately between them at 61 - a muted sand that no persona
   owns, that no state colour means, and that cannot be read as a surface: it
   is the only low-saturation chromatic on the board. It carries the same
   luminance range the accents do, so it holds up at both wire opacities the
   renderer uses (0.85 running, 0.22 faint) against --bg. */
:root{ --taskwire:#c9b08c; }
*{box-sizing:border-box;margin:0;padding:0;scrollbar-width:thin;scrollbar-color:#3a3d44 transparent}
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#3a3d44;border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:#4c5057}
html,body{height:100%}
body{background:var(--bg);color:var(--ink);font:400 13.5px/1.45 "Segoe UI",system-ui,sans-serif;display:flex;flex-direction:column;overflow:hidden}

header{display:flex;align-items:center;gap:10px;padding:8px 16px;border-bottom:1px solid var(--line);background:linear-gradient(180deg,#1a1c20,#141518)}
.logo{width:34px;height:34px;border-radius:10px;display:grid;place-items:center;font-size:18px;
  background:linear-gradient(135deg,#34373d,#202226);border:1px solid var(--line)}
header h1{font-size:15px;font-weight:650;letter-spacing:.01em}
.badge{font-size:12px;color:var(--ink2);border:1px solid var(--line);border-radius:20px;padding:3px 12px;background:var(--panel)}
/* KEEL ADDITION (T340): the restart control reuses .badge's shape (same
   border-radius, padding, font-size) and only ADDS the pointer + colour a
   button needs; it is the stale chip's own colour, so the two read as one
   unit even though only one of them can be clicked. */
#keelrestart{cursor:pointer;color:var(--bad);border-color:var(--bad);font-family:inherit}
#keelrestart:disabled{cursor:default;opacity:.6}
/* KEEL ADDITION (T122): feed kind-chips; badges above reuse .badge as-is */
#keelfilters{display:flex;flex-wrap:wrap;gap:4px;padding:0 0 8px}
.kchip{font-size:9.5px;color:var(--ink2);border:1px solid var(--line);border-radius:9px;padding:2px 8px;background:var(--panel);cursor:pointer}
.kchip b{color:var(--ink);font-weight:600}
.kchip.off{opacity:.4;text-decoration:line-through}
.kchip:hover{border-color:var(--ink3)}
#live{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--ink2);border:1px solid var(--line);border-radius:20px;padding:3px 12px;background:var(--panel)}
#livedot{width:8px;height:8px;border-radius:50%;background:var(--ink3);transition:.3s}
#livedot.on{background:var(--good);box-shadow:0 0 10px var(--good)}
#bell{font-size:12px;color:var(--ink2);border:1px solid var(--line);border-radius:20px;padding:3px 12px;background:var(--panel);cursor:pointer;user-select:none}
#bell.on{color:var(--ink);border-color:var(--warn)}
#stats{margin-left:auto;display:flex;gap:10px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:5px 12px;text-align:center;min-width:82px}
.stat b{display:block;font-size:17px;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums}
.stat span{font-size:10px;color:var(--ink3);text-transform:uppercase;letter-spacing:.09em}

/* ---- KEEL ADDITION (T334, owner review of the live board 2026-08-26): the
   top bar's TYPE, and nothing else. Every rule below is additive - it
   restates only font properties (family is never restated: the page's own
   system stack on ``body`` is inherited, and no @font-face, @import or
   remote URL exists anywhere in this page, which is a hard rule for a
   loopback board and is pinned by test) - so no information, element or
   colour token changes here.
   THE HIERARCHY IS THE CARDS' OWN, borrowed so the header stops reading as
   a different product from the stage below it. A card says a NAME in weight
   700 at ~12.5-15px with tight tracking (``.node .who``) over a ROLE in
   ~9.5px muted (``.node .role``); the stat boxes are exactly that pair - a
   number over its label - and the chips are the role voice on one line. So:
     * the title takes the name voice one size up, with negative tracking
       (a heading tightens where a label opens up);
     * chips/badges take the role voice: 11px, weight 600, faintly opened;
       the values inside them (``b``) step up to the ink colour at 700;
     * the stat number takes the name voice at 20px with tabular figures
       (already set) and -.02em, so four boxes of digits line up as a row of
       numerals rather than four separate words;
     * the stat label keeps its uppercase micro-caps but gains the weight
       and tracking that make small caps legible at 9.5px.
   Sizes are the only thing that moved; nothing here is a colour change. */
header h1{font-size:17px;font-weight:700;letter-spacing:-.015em;line-height:1.2}
header #projectsel{font-size:11.5px;font-weight:600;letter-spacing:.01em}
.badge,#live,#bell{font-size:11px;font-weight:600;letter-spacing:.015em}
.badge b,#live b,#bell b{font-weight:700;color:var(--ink)}
#livetxt{font-weight:650;letter-spacing:.04em;text-transform:uppercase;font-size:10px}
.stat{min-width:88px;padding:5px 13px}
.stat b{font-size:20px;font-weight:700;letter-spacing:-.02em;line-height:1.1}
.stat span{font-size:9.5px;font-weight:600;letter-spacing:.11em}
.logo{font-size:17px}

main{flex:1;display:grid;grid-template-columns:1fr 312px;min-height:0}
#stage{position:relative;overflow:hidden;
  background:radial-gradient(1000px 620px at 50% 46%, #1c1e23 0%, #121316 62%)}
#stage::before{content:"";position:absolute;inset:0;
  background-image:radial-gradient(#ffffff0d 1px, transparent 1.3px);
  background-size:26px 26px;pointer-events:none}
#edges{position:absolute;inset:0;width:100%;height:100%}
/* KEEL ADDITION (T332, owner adjustment 2026-08-25 - VIEWPORT FIT): the
   whole scene (centre card, ring cards, orbit mini-cards and every wire)
   lives in these TWO layers and nothing else, so one uniform transform on
   both - computed by ``sceneFit`` in the script below, over the boxes of the
   cards, the satellites AND the wires' own bowed reach (``wireBox``, added
   for the 2026-08-25 review finding: a wire leaves the straight line between
   its endpoints, so it can cross the stage edge while both its cards sit
   inside), and written to both elements from the same value - shrinks the
   entire drawing to fit the stage without any card, satellite or wire being
   clipped, and without the
   two layers ever drifting apart (a wire is drawn in the same pixel space
   as the card it lands on). ``transform-origin:0 0`` is what makes the
   translate/scale pair exact rather than centre-relative. When the scene
   already fits, ``sceneFit`` returns the identity and the transform is set
   to ``none`` - a quiet board is not scaled at all. */
#nodes{position:absolute;inset:0;z-index:2;transform-origin:0 0;
  transition:transform .5s cubic-bezier(.4,0,.2,1)}
#edges{transform-origin:0 0;transition:transform .5s cubic-bezier(.4,0,.2,1)}
#empty{position:absolute;inset:0;display:flex;align-items:flex-end;justify-content:center;color:var(--ink3);font-size:12.5px;text-align:center;padding:0 30px 110px;z-index:1}
#empty[hidden]{display:none!important}

.node{position:absolute;transform:translate(-50%,-50%);width:152px;
  transition:left .8s cubic-bezier(.4,0,.2,1),top .8s cubic-bezier(.4,0,.2,1),opacity .4s;
  animation:arrive .5s cubic-bezier(.2,.9,.3,1.2)}
/* KEEL ADDITION (T325, owner mockup review 2026-08-25): the node's visible
   surface (background/border/radius/shadow) now lives on this INNER .card
   wrapper only, not on .node itself - .node stays a bare positioned box
   (width/left/top/transform), so the rail below (a SIBLING of .card, not a
   child) sits visually OUTSIDE the card: the card's own background/border
   ends at its own bottom edge, and the rail zone paints nothing but its
   branch line + mini-cards. The wrapper's (.node's) total box-model height
   is unchanged by this split - .card carries the exact padding .node used
   to carry - so CARD_H/ringPos below still reserve the correct footprint. */
.node .card{background:linear-gradient(180deg,#212328f2,#17191df2);
  border:1px solid var(--line);border-radius:14px;padding:10px 11px 9px;
  box-shadow:0 10px 28px #00000055;transition:border-color .4s}
@keyframes arrive{from{opacity:0;transform:translate(-50%,-50%) scale(.6)}to{opacity:1;transform:translate(-50%,-50%) scale(1)}}
.node .top{display:flex;align-items:center;gap:10px}
.avatar{position:relative;width:37px;height:37px;flex:none;border-radius:50%;display:grid;place-items:center;padding:4px;
  background:color-mix(in srgb, var(--c) 14%, #16181c);
  border:2px solid color-mix(in srgb, var(--c) 55%, transparent)}
.avatar svg{width:100%;height:100%;display:block}
.emb{position:absolute;right:-4px;bottom:-4px;font-size:10px;line-height:1;padding:2px;border-radius:50%;
  background:#131417;border:1px solid color-mix(in srgb, var(--c) 50%, transparent)}
.node.center .emb{right:0;bottom:-2px;font-size:13px}
.fbot{display:inline-block;width:15px;height:15px;vertical-align:-3px}
.fbot svg{width:100%;height:100%;display:block}
.node .who{font-weight:700;font-size:12.5px;letter-spacing:.01em}
.node .role{font-size:9.5px;color:var(--ink2);line-height:1.3}
/* KEEL ADDITION (T337 extension): an empty pill is no pill - the tag is
   emptied rather than removed when a run's route is unknown (T132's rule,
   same outcome), so the same element can be filled again on a later tick.
   AND IT STAYS ON ONE LINE: the pill now shows the route the RUN actually
   ran at, which prefers the close half's resolved id ("claude-sonnet-5 ·
   default") over the open half's request ("sonnet · default") - a longer
   string than this tag was ever given before, and MEASURED on the rendered
   board it wrapped to two lines and sat over the card's own title row. The
   pill is a label, not a paragraph: one line, bounded by the card's width,
   ellipsised when the id is longer than the card can show (the drawer prints
   it in full). */
.modeltag:empty{display:none}
.modeltag{max-width:calc(100% - 22px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.modeltag{position:absolute;top:-9px;right:12px;font-size:9.5px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
  color:#131417;background:color-mix(in srgb, var(--c) 82%, white 4%);border-radius:8px;padding:2px 8px}
/* KEEL ADDITION (T335): the unrecorded variant of the pill - same shape,
   surface greys instead of a persona accent, because "unrecorded" is not a
   model and must not be dressed as one. */
.modeltag.unknown{color:var(--ink3);background:var(--panel2);border:1px solid var(--line);
  font-weight:600;text-transform:none;letter-spacing:.02em}
.node .task{font-size:10.5px;color:var(--ink2);margin-top:7px;border-top:1px solid #ffffff10;padding-top:8px;
  overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;min-height:2.5em}
.chip{font-size:9.5px;font-weight:600;border-radius:9px;padding:2.5px 9px;margin-top:8px;display:inline-flex;align-items:center;gap:5px}
.node.working .card{border-color:color-mix(in srgb, var(--c) 65%, transparent)}
.node.working .avatar{animation:ring 1.5s ease-out infinite}
@keyframes ring{0%{box-shadow:0 0 0 0 color-mix(in srgb, var(--c) 60%, transparent)}75%{box-shadow:0 0 0 13px transparent}100%{box-shadow:0 0 0 0 transparent}}
.node.working .chip{background:color-mix(in srgb, var(--c) 24%, transparent);color:var(--ink)}
.node.working .chip::before{content:"";width:7px;height:7px;border-radius:50%;background:var(--c);animation:blink 1s infinite alternate}
@keyframes blink{from{opacity:.35}to{opacity:1}}
.node.working.stall .card{border-color:var(--warn)}
.node.working.stall .chip{background:color-mix(in srgb, var(--warn) 26%, transparent)}
.node.done{opacity:.68}
.node.done .chip{background:#2c2f35;color:var(--ink2)}
.node.done .chip::before{content:"✓";color:var(--good)}
.node .act{font-size:9px;color:var(--ink3);margin-top:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-variant-numeric:tabular-nums}
.node .act:empty{display:none}
.node:not(.center){cursor:pointer}

/* KEEL ADDITION (T332, owner-confirmed concept 2026-08-25 - THE WIRING VIEW
   IS FRACTAL): the T322/T324/T325 branch rail that hung UNDER a card is
   replaced, presentation only, by ORBIT MINI-CARDS. The attribution that
   fed the rail is untouched (``chipRailFor`` in the script below still
   decides whose task a chip is, and how many are live); what changed is
   where those chips are drawn: each one is now its own small card orbiting
   the node that owns it, wired hub->task in the same quadratic-bezier
   language the Captain->agent edges use, because an agent running a task
   IS an orchestrator of that task. A hub with nothing live in scope draws
   no satellites and no wires and therefore looks exactly as it did before
   T322 - the same quiet-board guarantee the rail's ``:empty`` rule made.
   The T324 owner correction still holds and is not softened: the ring
   solver still reserves a fixed per-card band (ORBIT_BAND_H, the same 64px
   the rail used to claim) so ring cards keep their clearance from the
   Captain, and the satellites that now reach past that band are answered by
   the T332 uniform scene scale below (``sceneFit``) rather than by letting
   anything hang off the viewport.
   WIDTH/HEIGHT ARE FIXED HERE ON PURPOSE and must match ORBIT_W/ORBIT_H in
   the script below - the same lockstep-by-comment discipline ORBIT_BAND_H and
   BG_LAUNCH_MS/BG_MS already use in this file: the layout reserves a mini
   card's footprint from a constant rather than measuring the DOM. */
.tnode{position:absolute;transform:translate(-50%,-50%);width:96px;height:30px;overflow:hidden;
  display:flex;align-items:center;gap:5px;padding:3px 6px;pointer-events:none;
  background:linear-gradient(180deg,var(--panel2),var(--card));
  border:1px solid color-mix(in srgb, var(--c) 45%, var(--line));border-radius:8px;
  box-shadow:0 6px 16px #00000055;
  transition:left .6s cubic-bezier(.4,0,.2,1),top .6s cubic-bezier(.4,0,.2,1),opacity .4s;
  animation:arrive .45s cubic-bezier(.2,.9,.3,1.2)}
.tnode .tdot{flex:none;width:6px;height:6px;border-radius:50%;background:var(--c)}
.tnode .tbody{min-width:0;display:flex;flex-direction:column;line-height:1.15}
.tnode .tdesc{font-family:ui-monospace,Consolas,"SFMono-Regular",monospace;font-size:9px;color:var(--ink);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tnode .tstate{font-size:8.5px;color:var(--ink3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tnode-background{border-color:color-mix(in srgb, var(--c) 70%, transparent)}
.tnode-background .tdot{animation:blink 1s infinite alternate}
.tnode-background .tstate{color:var(--warn)}
.tnode-done{opacity:.62}

#drawer{position:absolute;top:0;right:0;bottom:0;width:360px;max-width:85%;z-index:8;
  background:#17191df5;border-left:1px solid var(--line);box-shadow:-14px 0 34px #00000066;
  display:flex;flex-direction:column;transform:translateX(105%);transition:transform .3s}
#drawer.open{transform:none}
#drawer .dhead{display:flex;align-items:center;gap:10px;padding:14px 16px;border-bottom:1px solid var(--line)}
#drawer .dhead .face{width:30px;height:30px;flex:none}
#drawer .dhead .face svg{width:100%;height:100%;display:block}
#drawer .dhead .who{font-weight:700}
#drawer .dhead .close{margin-left:auto;cursor:pointer;color:var(--ink3);font-size:18px;padding:2px 8px}
#drawer .dmeta{padding:10px 16px;font-size:12px;color:var(--ink2);border-bottom:1px solid var(--panel2)}
/* KEEL ADDITION (T335, owner review 2026-08-26): the full task brief. It
   WRAPS (the header's one-line preview is the only clamped copy of this
   string), it scrolls when a brief is long, and it never grows past 42% of
   the drawer so the action list underneath it stays reachable. The label
   uses T334's small-caps label voice, the same one the stat boxes speak. */
#drawer .dtask{padding:10px 16px;font-size:12px;line-height:1.5;color:var(--ink);
  border-bottom:1px solid var(--panel2);white-space:pre-wrap;overflow-wrap:anywhere;
  max-height:42%;overflow-y:auto}
#drawer .dtask[hidden]{display:none}
#drawer .dtask .dlabel{display:block;font-size:9.5px;font-weight:600;letter-spacing:.11em;
  text-transform:uppercase;color:var(--ink3);margin-bottom:4px}
#dracts{flex:1;overflow-y:auto;padding:6px 10px 14px}
.arow{display:flex;gap:8px;padding:6px 6px;font-size:12px;border-bottom:1px solid var(--panel2);color:var(--ink2)}
.arow .t{color:var(--ink3);flex:none;font-variant-numeric:tabular-nums}
.arow .d{overflow-wrap:anywhere}

.node.center{width:206px;text-align:center;z-index:3;animation:none;cursor:pointer}
.node.center .card{border-color:color-mix(in srgb, var(--maestro) 45%, transparent)}
.node.center .avatar{width:48px;height:48px;margin:0 auto}
.node.center .who{font-size:15px;margin-top:6px}
.node.center .chip{background:#2c2f35;color:var(--ink2);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:inline-block}
.node.center .act{text-align:center}
.node.center.judge-pass .card{animation:judgeP 2.2s ease}
.node.center.judge-fail .card{animation:judgeF 2.2s ease}
@keyframes judgeP{35%{border-color:var(--good);box-shadow:0 0 42px -4px var(--good)}}
@keyframes judgeF{35%{border-color:var(--bad);box-shadow:0 0 42px -4px var(--bad)}}
.node.center .halo{position:absolute;inset:-7px;border-radius:20px;pointer-events:none;opacity:0;transition:opacity .5s;
  background:conic-gradient(from var(--a,0deg), transparent 0 78%, var(--maestro) 92%, transparent 100%);
  -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);-webkit-mask-composite:xor;mask-composite:exclude;padding:2px}
.node.center.busy .halo{opacity:.9;animation:spin 2.6s linear infinite}
@property --a{syntax:"<angle>";initial-value:0deg;inherits:false}
@keyframes spin{to{--a:360deg}}

aside{border-left:1px solid var(--line);background:var(--panel);display:flex;flex-direction:column;min-height:0}
aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink3);padding:14px 18px 8px;display:flex;align-items:center;gap:8px}
header #projectsel{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:20px;
  padding:3px 10px;font-size:12px;font-family:inherit;max-width:160px}
header #projectsel:focus{outline:none;border-color:var(--forge)}
/* KEEL ADDITION (T313): the session/round switcher relocated from the top
   banner into the right rail, sitting directly above the plan-ledger panel */
#roundrow{display:flex;align-items:center;gap:10px;padding:14px 18px 8px;min-width:0}
#roundlabel{font-size:11px;text-transform:uppercase;letter-spacing:.1em;color:var(--ink3);flex:none}
#sessdd{position:relative;flex:1;min-width:0}
#sessbtn{background:var(--panel2);color:var(--ink);border:1px solid var(--line);border-radius:14px;
  padding:3px 12px;font-size:12px;font-family:inherit;width:100%;max-width:100%;min-width:0;text-align:left;
  cursor:pointer;display:flex;flex-direction:column;line-height:1.25;gap:1px}
#sessbtn:focus{outline:none;border-color:var(--forge)}
#sessbtn span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block;max-width:100%}
#sessbtn-line1{font-size:12px;color:var(--ink)}
#sessbtn-line2{font-size:10px;color:var(--ink3)}
#sesslist{position:absolute;top:calc(100% + 5px);right:0;left:auto;min-width:min(260px,100%);
  max-width:min(360px,calc(100vw - 24px));max-height:360px;
  overflow-y:auto;background:#1a1c20f5;border:1px solid var(--line);border-radius:10px;
  box-shadow:0 14px 34px #00000066;z-index:20;padding:4px}
#sesslist[hidden]{display:none}
.ddgrouplabel{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--ink3);padding:6px 8px 2px}
.ddopt{padding:6px 8px;border-radius:7px;cursor:pointer;display:flex;flex-direction:column;gap:1px}
.ddopt:hover{background:#232529}
.ddopt.sel{background:#2c2f35}
.ddopt .l1{font-size:12px;color:var(--ink);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ddopt .l2{font-size:10px;color:var(--ink3)}
body.history #stage{filter:saturate(.75)}
#histnote{display:none;font-size:10.5px;color:var(--warn);padding:4px 18px 0}
body.history #histnote{display:block}
#planbar{flex:none;height:5px;border-radius:4px;background:#2a2d33;margin:0 18px 4px;overflow:hidden}
#planfill{height:100%;width:0%;border-radius:4px;background:linear-gradient(90deg,var(--good),#7ee3ae);transition:width .6s}
#ledger{padding:2px 12px 10px;overflow-y:auto;flex:0 1 44%}
.task-item{display:flex;gap:9px;align-items:flex-start;padding:6px 6px;border-bottom:1px solid var(--panel2);font-size:12px}
.task-item .mark{width:1.5em;text-align:center;flex:none;font-size:13px;line-height:1.5}
.task-item .ac{display:block;font-size:11px;color:var(--ink3);margin-top:1px}
.t-done .mark{color:var(--good)} .t-open .mark{color:var(--ink3)}
.t-blocked .mark{color:var(--bad)} .t-decision .mark{color:var(--warn)}
.t-done .txt{color:var(--ink2);text-decoration:line-through;text-decoration-color:#4a4d54}
.t-blocked .txt{color:#f2aeb4}
#feed{flex:1 1 0;overflow-y:auto;padding:0 12px 12px;border-top:1px solid var(--line)}
.ev{display:flex;gap:8px;padding:6px 5px;font-size:11px;border-bottom:1px solid var(--panel2);color:var(--ink2);border-left:3px solid transparent;padding-left:9px}
.ev .t{color:var(--ink3);flex:none;font-variant-numeric:tabular-nums;min-width:52px;text-align:right}
.ev b{color:var(--ink);font-weight:650}
.ev.alert{background:#2a1c2422}

#legend{display:flex;gap:18px;flex-wrap:wrap;padding:9px 20px;border-top:1px solid var(--line);background:var(--panel);font-size:11.5px;color:var(--ink2)}
#legend .lg{display:inline-flex;align-items:center;gap:6px}
#legend .dot{width:11px;height:11px;border-radius:4px}

/* KEEL ADDITION (T155, owner-instructed 2026-08-16): the bench was laid out
   for five personas and now carries thirteen. Centred on one unwrapped row,
   the strip grew wider than the canvas and cards fell off BOTH edges - so
   "too dense" was two faults: cards too large for their number, and a row
   that could not admit it had run out of room. It now wraps, keeps a margin
   the cards cannot be clipped against, and each card is smaller. Nothing
   about what a card SAYS changed here; this is size and flow only. */
#bench{position:absolute;left:0;right:0;bottom:12px;display:flex;justify-content:center;flex-wrap:wrap;
  gap:6px 7px;padding:0 14px;z-index:4;pointer-events:none}
.bpill{pointer-events:auto;display:flex;align-items:center;gap:7px;padding:4px 10px 4px 5px;border-radius:22px;cursor:pointer;
  background:#1a1c20e8;border:1px solid var(--line);box-shadow:0 4px 12px #00000038;transition:.3s}
.bpill .bface{width:21px;height:21px;border-radius:50%;display:grid;place-items:center;padding:2px;
  background:color-mix(in srgb, var(--c) 14%, #16181c);border:1.5px solid color-mix(in srgb, var(--c) 45%, transparent)}
.bpill .bface svg{width:100%;height:100%;display:block}
.bpill b{font-size:10px;display:block;line-height:1.15}
.bpill .bstat{font-size:9px;color:var(--ink3);display:block;line-height:1.15}
.bpill.asleep{opacity:.55;filter:saturate(.4)}
.bpill.asleep:hover{opacity:.9;filter:none}
.bpill.awake{border-color:color-mix(in srgb, var(--c) 55%, transparent)}
.bpill.awake .bstat{color:var(--ink2)}
</style></head><body>
<header>
  <div class="logo">🎛️</div>
  <h1>Orchestration</h1>
  <select id="projectsel" title="Project — pick a sibling to open its dashboard"></select>
  <span id="live"><span id="livedot"></span><span id="livetxt">idle</span></span>
  <span id="bell" title="Desktop notifications for blocked / needs-decision / gate events">🔔 alerts off</span>
  <!-- KEEL ADDITION (T122): arming chip + honest session pill, both fed by
       the /api/state "keel" block; the page's own livedot is untouched -->
  <span class="badge" id="keelarming" hidden></span>
  <span class="badge" id="keelsess" hidden></span>
  <!-- KEEL ADDITION (T168): is this board serving the code on disk? Fed by
       the /api/state "keel" block's "code" field; three states, one of which
       is "unknown" - see served_code() -->
  <span class="badge" id="keelcode" hidden></span>
  <!-- KEEL ADDITION (T340): the board's own restart control. It renders
       ONLY when the chip above is in the stale state - see keelPaint()'s
       ``cd.stale`` branch, which is the sole place ``.hidden`` is cleared -
       the current and unknown states never show a button, only text. -->
  <button type="button" class="badge" id="keelrestart" hidden>restart board</button>
  <div id="stats">
    <div class="stat"><b id="s-active" style="color:var(--forge)">0</b><span>working now</span></div>
    <div class="stat"><b id="s-handoffs">0</b><span>hand-offs</span></div>
    <div class="stat"><b id="s-gates">0</b><span>gate blocks</span></div>
    <div class="stat"><b id="s-done" style="color:var(--good)">0/0</b><span>tasks done</span></div>
  </div>
</header>
<main>
  <div id="stage">
    <svg id="edges"></svg>
    <div id="nodes"></div>
    <div id="empty" hidden>No orchestration activity yet.<br>Start a Claude session in this project and hand-offs will appear here live.</div>
    <div id="bench"></div>
    <div id="drawer">
      <div class="dhead"><span class="face"></span><span class="who"></span><span class="close" title="close">✕</span></div>
      <div class="dmeta"></div>
      <!-- KEEL ADDITION (T335): the run's whole task brief, wrapped and
           scrollable - the header line above stays a one-line preview -->
      <div class="dtask" hidden></div>
      <div id="dracts"></div>
    </div>
  </div>
  <aside>
    <div id="histnote">viewing a past round — live updates continue in "Current"</div>
    <div id="roundrow">
      <span id="roundlabel">Round</span>
      <div id="sessdd">
        <button type="button" id="sessbtn" title="Session / round — active sessions first, ended rounds below" aria-haspopup="listbox" aria-expanded="false">
          <span id="sessbtn-line1">Current (auto)</span><span id="sessbtn-line2"></span>
        </button>
        <div id="sesslist" role="listbox" hidden></div>
      </div>
    </div>
    <h2>Plan ledger <span id="plancount" style="margin-left:auto;color:var(--ink2);letter-spacing:0"></span></h2>
    <div id="planbar"><div id="planfill"></div></div>
    <div id="ledger"></div>
    <h2>Event feed</h2>
    <!-- KEEL ADDITION (T122): kind-chips that hide/show feed rows -->
    <div id="keelfilters" hidden></div>
    <div id="feed"></div>
  </aside>
</main>
<div id="legend"></div>
<script>
const STALL_MS=10*60*1000;      // working this long -> amber "stalled?"
const ABANDON_MS=2*60*60*1000;  // unpaired start this old -> presumed aborted, not working
const BG_MS=5000;               // FALLBACK ONLY (T323): end within 5s of start -> background launch,
                                 // agent still running. Used only for a handoff_end that predates the
                                 // capture-side "background" field (hooks/keel_capture.py's
                                 // HANDOFF_BACKGROUND_KEY) - a fresh record answers the field directly
                                 // (computeStates below) rather than this timing guess, because the
                                 // guess is exactly the defect T323 fixes: a background acknowledgment
                                 // can arrive well past this gap (T182 measured 8s, over this 5000ms),
                                 // which would misread a still-running delegation as a finished
                                 // foreground one. MUST stay in sync with stop_gate.py's BG_LAUNCH_MS
                                 // for the records still using this fallback - do not drift
const LIVENESS_MS=10*60*1000;   // bg agent with no stop signal & no activity this long -> presumed finished
const RETIRE_MS=2*60*1000;      // finished cards linger this long in the ring, then rest on the bench
const ACTIVE_WINDOW_MS=10*60*1000; // a session with no session_end is ACTIVE while its last event is this fresh
const PERSONAS={
  orchestrator:{face:"🎩",emb:"🎼",kind:"maestro",name:"Maestro",role:"Orchestrator — plans · routes · reviews",v:"--maestro"},
  researcher:{face:"🔭",emb:"🔭",kind:"scout",name:"Scout",role:"Researcher — read-only recon",v:"--scout"},
  "executor-sonnet":{face:"🔨",emb:"🔨",kind:"forge",name:"Forge",role:"Executor — default tier",v:"--forge"},
  "executor-opus":{face:"🧠",emb:"🧠",kind:"sage",name:"Sage",role:"Executor — high-effort tier",v:"--sage"},
  advisor:{face:"⚖️",emb:"⚖️",kind:"counsel",name:"Counsel",role:"Advisor — strong second opinion",v:"--counsel"},
  _generic:{face:"🤖",emb:"🤖",kind:"generic",name:"Agent",role:"Subagent",v:"--generic"},
};
/* KEEL ADDITION (T132): the crew comes aboard - the vendored table above
   (this object literal) is untouched byte-for-byte; nothing in it is
   deleted or reworded. Keel's own identity for the orchestrator (Captain)
   is layered on by a DIRECT KEY RE-ASSIGNMENT after the literal closes -
   the vendored key stays `orchestrator`, no vendored line is edited. Every
   `keel:*` entry below is a brand-new key (T132, names ratified
   2026-08-13). `kind` values reuse the vendored eye styles from robotSVG
   below, so this block never has to touch that vendored function; each
   entry's own `v` (this file's new crew CSS vars, added above) is what
   makes the crew visually distinct. */
PERSONAS.orchestrator={face:"⚓",emb:"⚓",kind:"maestro",name:"Captain",role:"Orchestrator — plans · routes · reviews",v:"--captain"};
Object.assign(PERSONAS,{
  "keel:researcher":{face:"🔭",emb:"🔭",kind:"scout",name:"Lookout",role:"Researcher — read-only recon",v:"--lookout"},
  "keel:executor":{face:"🔨",emb:"🔨",kind:"forge",name:"Shipwright",role:"Executor — standard tier",v:"--shipwright"},
  "keel:executor-deep":{face:"⚙️",emb:"⚙️",kind:"sage",name:"Chief",role:"Executor — deep tier · one retry",v:"--chief"},
  "keel:reviewer-correctness":{face:"📐",emb:"📐",kind:"counsel",name:"Surveyor",role:"Reviewer — correctness",v:"--surveyor"},
  "keel:reviewer-security":{face:"🛡️",emb:"🛡️",kind:"counsel",name:"Master-at-Arms",role:"Reviewer — security",v:"--arms"},
  "keel:reviewer-silent-failure":{face:"🌊",emb:"🌊",kind:"counsel",name:"Leadsman",role:"Reviewer — silent failure",v:"--leadsman"},
  "keel:reviewer-tests":{face:"💥",emb:"💥",kind:"counsel",name:"Gunner",role:"Reviewer — tests",v:"--gunner"},
  "keel:reviewer-altitude":{face:"⚖️",emb:"⚖️",kind:"counsel",name:"Trimmer",role:"Reviewer — altitude",v:"--trimmer"},
});
const persona=t=>PERSONAS[t]||{...PERSONAS._generic,role:t||"Subagent"};
const $=id=>document.getElementById(id);
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();

// ---- android avatars (inline SVG, tinted per persona) ---------------------
function robotSVG(varName,kind){
  const c=`var(${varName})`;
  const eyes={
    scout:`<circle cx="32" cy="30" r="9.5" fill="${c}"/><circle cx="32" cy="30" r="4.2" fill="#131417"/><circle cx="34" cy="28" r="1.5" fill="#f0f1f4"/>`,
    forge:`<rect x="19" y="25" width="10" height="10" rx="2.5" fill="${c}"/><rect x="35" y="25" width="10" height="10" rx="2.5" fill="${c}"/><path d="M25 41h14" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>`,
    sage:`<rect x="16" y="24" width="32" height="11" rx="5.5" fill="${c}"/><rect x="20" y="27" width="7" height="5" rx="2" fill="#131417" opacity=".55"/><rect x="37" y="27" width="7" height="5" rx="2" fill="#131417" opacity=".55"/>`,
    counsel:`<circle cx="24" cy="29" r="5.2" fill="${c}"/><circle cx="40" cy="29" r="5.2" fill="${c}"/><path d="M23 40h18" stroke="${c}" stroke-width="2.5" stroke-linecap="round"/>`,
    maestro:`<circle cx="24" cy="31" r="5" fill="${c}"/><circle cx="40" cy="31" r="5" fill="${c}"/><path d="M27 42c2 2.4 8 2.4 10 0" stroke="${c}" stroke-width="2.5" fill="none" stroke-linecap="round"/>`,
    generic:`<circle cx="24" cy="29" r="5" fill="${c}"/><circle cx="40" cy="29" r="5" fill="${c}"/>`,
  }[kind]||"";
  const top=kind==="maestro"
    ?`<rect x="23" y="1" width="18" height="10" rx="2" fill="${c}"/><rect x="18" y="9" width="28" height="3.5" rx="1.75" fill="${c}"/>`
    :`<line x1="32" y1="5" x2="32" y2="12" stroke="${c}" stroke-width="2.5"/><circle cx="32" cy="4.5" r="3" fill="${c}"/>`;
  return `<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
    ${top}
    <rect x="12" y="12" width="40" height="36" rx="12" fill="#1b1d21" stroke="${c}" stroke-width="2.6"/>
    <rect x="7" y="24" width="5" height="12" rx="2.5" fill="${c}" opacity=".75"/>
    <rect x="52" y="24" width="5" height="12" rx="2.5" fill="${c}" opacity=".75"/>
    ${eyes}
    <rect x="23" y="52" width="18" height="7" rx="3.5" fill="${c}" opacity=".45"/>
  </svg>`;
}
const bot=(p,cls)=>`<span class="${cls||"fbot"}">${robotSVG(p.v,p.kind)}</span>`;

/* KEEL ADDITION (T155, owner-instructed 2026-08-16): the legend stops
   printing the two keys that name MODEL TIERS rather than roles. Their
   PERSONAS entries above are untouched, so a record still carrying those
   types renders exactly as it did - this hides two legend rows and moves no
   behaviour. keel's own crew is named for what it does, and these were the
   only rows in the legend naming a model. */
const LEGEND_HIDDEN=new Set(["executor-sonnet","executor-opus"]);
$("legend").innerHTML=Object.entries(PERSONAS).filter(([k])=>k!=="_generic"&&!LEGEND_HIDDEN.has(k))
 .map(([k,p])=>`<span class="lg"><span class="dot" style="background:var(${p.v})"></span>${bot(p)} <b style="color:var(--ink)">${p.name}</b>&nbsp;= ${k}</span>`).join("");

// ---- notifications -------------------------------------------------------
let alertsOn=false;
$("bell").onclick=async()=>{
  if(!alertsOn){
    const perm=await Notification.requestPermission();
    alertsOn=perm==="granted";
  } else alertsOn=false;
  $("bell").textContent=alertsOn?"🔔 alerts on":"🔔 alerts off";
  $("bell").classList.toggle("on",alertsOn);
};
function notify(title,body){
  if(alertsOn&&"Notification" in window&&Notification.permission==="granted")
    new Notification(title,{body:body||""});
}

function pairEvents(events){
  const agents=[],open=new Map(),byId=new Map();
  const kf=e=>(e.subagent_type||"?")+"|"+(e.description||"");
  let n=0;
  for(const e of events){
    if(e.event==="handoff_start"){
      const a={start:e,end:null,uid:e.tool_use_id||("k"+(n++))};
      agents.push(a);
      if(e.tool_use_id)byId.set(e.tool_use_id,a);
      else{const k=kf(e);if(!open.has(k))open.set(k,[]);open.get(k).push(a);}
    }else if(e.event==="handoff_end"||e.event==="handoff"){
      let a=null;
      if(e.tool_use_id&&byId.has(e.tool_use_id)){a=byId.get(e.tool_use_id);byId.delete(e.tool_use_id);}
      else{const q=open.get(kf(e));if(q&&q.length)a=q.shift();}
      if(a)a.end=e;else agents.push({start:null,end:e,uid:"e"+(n++)});
    }
  }
  return agents;
}

const nodeEls=new Map(); let edgeSig="";
let lastAgents=[], lastActs=[], lastStops=[], lastReviews=[], lastSessionStarts=[];
let lastArchives=[], selectedRound="live", lastRoundHtml="", lastRoundKey="";
let sessionEnded=new Set(), lastSeenBySession=new Map();
const planCache=new Map();
const subjectCache=new Map(); // session_id -> plan subject line (for the dropdown label)
// which session "era" a timestamp falls in (index of the latest
// session_start at or before it) - scopes review pairing per session
const winIdx=t=>{let i=-1;for(const s of lastSessionStarts){if(s<=t)i++;else break;}return i;};
const toolIcon=t=>({Write:"✏️",Edit:"✏️",MultiEdit:"✏️",NotebookEdit:"📓",Bash:"▶"})[t]||"·";
function actsFor(a){
  // activity events attributed to this hand-off: same agent_type, inside
  // its start..end time window (agent_type may be absent -> orchestrator).
  // Background runs stay open-ended: the logged "end" is just the launch
  // acknowledgment, so the window extends to the stop signal or now.
  if(!a.start)return[];
  let t1=(a.background&&!a.stop)?Infinity:(a.stop?ts(a.stop):(a.end?ts(a.end):Infinity));
  // same-type instances are indistinguishable in the activity stream, so
  // bound each agent's window at the next same-type launch (FIFO-ish)
  if(a.nextSameTypeStart)t1=Math.min(t1,a.nextSameTypeStart);
  const t0=ts(a.start), type=a.start.subagent_type, sess=a.start.session_id;
  // strict attribution: events without agent_type belong to the
  // orchestrator/main session, never to a subagent card; and never
  // across session boundaries
  return lastActs.filter(ev=>{
    const t=ts(ev);
    return t>=t0&&t<=t1&&ev.agent_type===type&&ev.session_id===sess;
  });
}
function reviewFor(a){
  // policy guarantees a review per task; a review whose task id appears in
  // this agent's description means the agent has finished and reported
  if(!a.start||!a.start.description)return null;
  const desc=a.start.description, w=winIdx(ts(a.start));
  for(const r of lastReviews){
    if(r.task&&ts(r)>=ts(a.start)&&winIdx(ts(r))===w
       &&new RegExp("\\b"+r.task+"\\b","i").test(desc))return r;
  }
  return null;
}
const ts=e=>new Date(e.ts).getTime();
const fmtDur=ms=>ms<0?"":ms<60000?Math.round(ms/1000)+"s":Math.floor(ms/60000)+"m "+Math.round(ms%60000/1000)+"s";
const esc=s=>(s||"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
// KEEL ADDITION (T312): the detail drawer's own preview bound. The card's
// task text is already cut server-side (``_truncate_preview``, 2000 chars
// since T335 so the drawer's TASK block can show the whole brief)
// so a long brief never reaches the DOM in full; this is a SECOND, tighter
// bound applied only where the drawer would otherwise print that field with
// no visual clamp at all (``.who``) - ~200 chars, matching the owner's
// reference screenshot ("first ~2-3 lines or ~200 chars, ellipsized").
// ``prompt_head`` needs no second cut: it is already bounded to 200 chars
// at capture (``hooks/keel_capture.py``'s ``PROMPT_HEAD_CHARS``).
const PREVIEW_CHARS=200;
const preview=(s,n)=>{n=n||PREVIEW_CHARS;s=s||"";return s.length>n?s.slice(0,n).trimEnd()+"…":s;};
const modelOf=(e)=>e.model||({researcher:"haiku","executor-sonnet":"sonnet","executor-opus":"opus · high",advisor:"opus"})[e.subagent_type]||"agent";

// ---- KEEL ADDITION (T322; made TRANSIENT by T324) - task chips branch ----
// from their owner. Small per-tool chips hang on a branch rail under the
// node that owns them: the tracked (orchestrator) session's own tool runs
// under the Captain card, a delegate's runs under that agent's card - same
// pairing logic ``actsFor`` already uses (session + agent_type +
// start..end window), no new record format. Pure, DOM-free functions, so
// this whole seat can be exercised with synthetic event lists in a test
// harness, ``now`` included - never a scattered ``Date.now()`` a test
// cannot control (the page's own call sites in ``layout()`` below pass the
// real one).
//
// CHIP EVENT CLASSES, and the HONESTY MAP each chip's state is drawn from
// (do not add a fourth class here without updating this comment AND
// ``chipState``/``chipLive`` together - this is the one place all three
// are read):
//   background_task - a START-shaped event (T137's own addition above): the
//     harness's own backgrounded shell runs, for which "no end signal
//     reaches keel" (T137's own words, in the feed verb table above). Its
//     chip therefore renders "background · started <age>" - never a bare
//     "running" claim keel cannot back, and never a fake spinner-forever -
//     and it EXISTS only while nothing has closed its scope (see
//     ``chipLive`` below), not for a fixed age window: a background run has
//     no natural finish time to measure staleness from.
//   activity, gate_block - COMPLETION-ONLY event classes: each line already
//     records something that finished (a tool call returned; a gate fired
//     and was resolved one way or the other). Their chips render their own
//     event kind ("just ran" / "just blocked") - a "running" state may
//     NEVER be drawn for these, because no start half exists to measure one
//     from - and they EXIST only within CHIP_FRESH_MS of their own ``ts``.
const CHIP_KINDS=new Set(["activity","background_task","gate_block"]);
// KEEL ADDITION (T324, owner design correction 2026-08-25): completion-only
// chips are FRESH, never archival - one named constant, read wherever a
// chip's lifetime is decided. 90s: long enough that a reader glancing at
// the board after a tool call still sees it, short enough that nothing
// becomes a "done · Nm ago" history row (that shape is deleted, not kept
// around with a longer clock).
const CHIP_FRESH_MS=90*1000;
function chipState(e){
  if(e.event==="background_task")return{cls:"background",label:"background · started "+rel(e.ts)};
  if(e.event==="gate_block")return{cls:"done",label:"just blocked"};
  return{cls:"done",label:"just ran"};
}
function chipIcon(e){
  if(e.event==="gate_block")return"🛡️";
  return toolIcon(e.tool);
}
// KEEL ADDITION (T324): whether a chip-eligible event is still LIVE right
// now - the transience rule, kept separate from ``eventsForOwner``'s
// grouping/windowing so neither reader has to hold both concerns at once.
//   background_task: alive exactly while nothing has closed its scope.
//     Owned by a delegate (``a`` given) - the harness itself never signals
//     a background run's own completion (see the T137 comment above), so
//     the only honest close-signal available is the OWNING AGENT'S own
//     report-back (``a.stop``/``a.end``); once that agent has closed, its
//     background chip no longer belongs on a live card. Owned by the
//     Captain (``a`` null) - the analogous close-signal is the LAUNCHING
//     SESSION'S OWN END (``session_end``): while that session is still
//     open keel cannot honestly call the run finished, so the chip stays;
//     once the session ends, so does the chip.
//   activity, gate_block: alive only within CHIP_FRESH_MS of their own ts -
//     a plain age check, exactly the freshness window named above.
function chipLive(e,a,events,now){
  if(e.event==="background_task"){
    if(a)return!(a.stop||a.end);
    return!(events||[]).some(o=>o.event==="session_end"&&o.session_id===e.session_id&&ts(o)>=ts(e));
  }
  return(now-ts(e))<CHIP_FRESH_MS;
}
// eventsForOwner(null, events, now) -> the tracked session's OWN
// chip-eligible LIVE events (no agent_type - the same test ``maestroActs``
// uses for the Captain card's own activity strip). eventsForOwner(a,
// events, now) -> the SAME windowing ``actsFor`` uses for a delegate's
// hand-off (a), narrowed to CHIP_KINDS instead of activity alone - one
// agent's chips can never bleed into another's, and never across a session
// boundary - then filtered again through ``chipLive`` (T324): grouping
// says WHOSE the event is, ``chipLive`` says whether it still belongs on
// the board at all.
function eventsForOwner(a,events,now){
  const all=events||[];
  let scoped;
  if(!a){
    scoped=all.filter(e=>CHIP_KINDS.has(e.event)&&!e.agent_type);
  }else if(!a.start){
    scoped=[];
  }else{
    let t1=(a.background&&!a.stop)?Infinity:(a.stop?ts(a.stop):(a.end?ts(a.end):Infinity));
    if(a.nextSameTypeStart)t1=Math.min(t1,a.nextSameTypeStart);
    const t0=ts(a.start),type=a.start.subagent_type,sess=a.start.session_id;
    scoped=all.filter(e=>{
      if(!CHIP_KINDS.has(e.event))return false;
      const t=ts(e);
      return t>=t0&&t<=t1&&e.agent_type===type&&e.session_id===sess;
    });
  }
  return scoped.filter(e=>chipLive(e,a,all,now));
}
// KEEL ADDITION (T324): at most 3 chips, NEWEST first - a transient rail
// shows what is happening now, not a log, so the T322 overflow count line
// is deleted outright, not renamed: anything past the cap is simply not
// shown, exactly like any other event this board declines to render.
function chipRailFor(a,events,now){
  const items=eventsForOwner(a,events,now).slice().sort((x,y)=>ts(y)-ts(x));
  return{shown:items.slice(0,3)};
}
// ---- KEEL ADDITION (T332): the same chips, drawn as ORBIT MINI-CARDS ----
// ``chipRailFor`` above is the attribution layer and is UNTOUCHED by T332:
// it still answers "whose live task is this, and which three are newest".
// These two functions are the presentation layer that replaced the branch
// rail: one descriptor per live chip (``orbitCardsFor``), one mini-card's
// markup per descriptor (``orbitCardHtml``). Both are pure and DOM-free, so
// the "N live tasks -> N satellites, idle hub -> none" rule can be
// exercised with synthetic events and an injected ``now``, exactly as T322's
// own harness already exercises the attribution below it.
//
// A satellite's STATE VOCABULARY is ``chipState``'s own ``cls`` and nothing
// else - the descriptor carries that value through untouched, and the CSS
// class is ``tnode-<cls>``. So the only satellites drawn bright, with a
// blinking dot and a live flowing wire, are the ``background`` ones (the one
// start-shaped class T322's honesty map allows to be shown as still going);
// every completion-only chip stays dim on a faint wire. No new word is
// coined here, which is deliberate: a second vocabulary is exactly how a
// mini card would end up claiming something the record never said.
const ORBIT_LABEL_CHARS=18;
function orbitLabel(e){
  // The task's own name when the record carries one (``task_id``, written by
  // the background-run capture), else what the tool actually did, else the
  // tool. Never a synthesised id - a satellite says only what the event says.
  const raw=(e.task_id||e.detail||e.tool||"task").toString();
  return raw.length>ORBIT_LABEL_CHARS?raw.slice(0,ORBIT_LABEL_CHARS-1).trimEnd()+"…":raw;
}
function orbitCardsFor(a,events,now){
  return chipRailFor(a,events,now).shown.map(e=>{
    const st=chipState(e);
    return{key:(e.ts||"")+"|"+(e.event||"")+"|"+(e.tool||""),
      icon:chipIcon(e),label:orbitLabel(e),state:st.label,cls:st.cls};
  });
}
function orbitCardHtml(item){
  return`<span class="tdot"></span><span class="tbody">`+
    `<span class="tdesc">${esc(item.icon)} ${esc(item.label)}</span>`+
    `<span class="tstate">${esc(item.state)}</span></span>`;
}

function ensureCenter(cx,cy){
  let el=nodeEls.get("__center");
  if(!el){
    const p=PERSONAS.orchestrator;
    el=document.createElement("div");
    el.className="node center";el.style.setProperty("--c",`var(${p.v})`);
    el.innerHTML=`<div class="card">
      <div class="halo"></div>
      <!-- KEEL ADDITION (T335, owner extension 2026-08-26): the orchestrator
           wears its model where every agent card wears its own - filled by
           renderMaestro from the session's OWN record, or the honest word
           "unrecorded" when the harness supplied none -->
      <span class="modeltag" id="mmodel"></span>
      <div class="avatar">${robotSVG(p.v,p.kind)}<span class="emb">${p.emb}</span></div>
      <div class="who">${p.name}</div><div class="role">${p.role}</div>
      <span class="chip" id="mstate"></span><div class="act" id="mact"></div>
      </div>`;
    /* KEEL ADDITION (T332): the Captain's own live tasks no longer hang on a
       rail under this card - they orbit it as mini cards on the Captain's own
       gold wire, drawn by layout() below (the orchestrator is a hub like any
       other). Nothing else about this card changed. */
    $("nodes").appendChild(el);nodeEls.set("__center",el);
  }
  el.style.left=cx+"px";el.style.top=cy+"px";
  return el;
}

// latest session = session of the newest event carrying one
let latestSession=null;
function maestroActs(){
  return lastActs.filter(e=>!e.agent_type&&e.session_id===latestSession);
}
/* ---- KEEL ADDITION (T335, owner extension 2026-08-26): THE ORCHESTRATOR'S
   OWN MODEL, from the record and nowhere else.
   WHERE IT COMES FROM: ``hooks/keel_session.py`` already records ``model`` on
   EVERY ``session_start`` line, "carrying null where the harness supplied
   nothing" (its own contract). So this reads that field off the tracked
   session's own start line - the newest one, since a session can be resumed
   and re-registered - and answers null when the record answers null.
   WHAT IS MISSING AND WHY IT IS NOT INVENTED: EFFORT. MEASURED on this
   project's log 2026-08-26: 260 ``session_start`` lines, 11 carrying a model
   and ZERO carrying an effort, because no harness payload names one for the
   session itself (``hooks/keel_capture.py``'s own contract says the launch
   tool has no effort parameter, and effort is only ever read from an AGENT
   definition's frontmatter - the orchestrator has no such file). An agent
   card can therefore say "opus · high" where the Captain can only say the
   model: the second half of that pill does not exist for a session, and a
   default printed here would be a routing tier nobody recorded.
   KEEL ADDITION (T475/BL25, 2026-09-03): SessionStart fires before the
   transcript holds a single assistant line, so on a FRESH session the model
   is genuinely unknowable at that instant - only a RESUMED session's
   re-registration can carry one on its start line (MEASURED: 50 of 340
   ``session_start`` events on the audit log carry a model, 290 do not, and
   ``stop_block`` for the same sessions already carries ``model: None`` too,
   though the transcript has the answer by then). The hooks half of T475
   teaches a LATER event (whichever one first sees an assistant line) to
   carry the model instead of leaving it for the transcript to answer alone.
   So this no longer requires ``event==="session_start"``: it reads the
   session's NEWEST event that carries a non-null, non-blank ``model``
   field, OF WHATEVER KIND - the field is the same one T335 already reads,
   just no longer gated to one event name - so the day that later event
   lands, this needs no matching edit; it already reads it. Newest wins
   because a session_start's null must not out-live a later event's answer.

   KEEL ADDITION (T609/BL31, 2026-09-06): "OF WHATEVER KIND" above was never
   licence to read a DELEGATION'S own event just because it shares the
   captain's ``session_id`` - and ``handoff_start``/``handoff_end`` do share
   it (``hooks/keel_capture.py``'s ``handoff_record``/``resume_record`` write
   ``"session": event.session_id`` on the LAUNCHING session, then a ``model``
   that names the DELEGATE, never the seat that did the launching), so this
   loop was letting a subagent's model wear the Captain's own chip. The fix
   is a blocklist, not a narrower allowlist, because the "of whatever kind"
   openness above is still the point for a session's OWN future event kinds
   (T475's "no matching edit" promise): only the event kinds MEASURED above
   to name someone else's seat are excluded - the two handoff halves, and
   ``subagent_stop`` for the same reason though it carries no ``model`` key
   today (``hooks/keel_hook.py``'s ``cmd_subagent_stop``) - so a future
   session-level event still needs no edit here, and a future delegation
   event needs one line added to this set, never a rewritten loop. Kept as a
   LOCAL inside the function, not a module-level const, so this whole seat -
   the blocklist included - stays one self-contained block a test can
   extract verbatim (see ``_SESSION_MODEL_BLOCK`` in
   ``tests/test_keel_dashboard_t334_t335.py``), the same reason T322's own
   attribution functions above stayed pure and DOM-free. */
function sessionModel(sessId){
  const excluded=new Set(["handoff_start","handoff_end","subagent_stop"]);
  const evs=(lastState&&lastState.events)||[];
  for(let i=evs.length-1;i>=0;i--){
    const e=evs[i];
    if(e.session_id!==sessId)continue;
    if(excluded.has(e.event))continue;
    if(typeof e.model==="string"&&e.model.trim())return e.model;
  }
  return null;
}
const MAESTRO_FRESH_MS=3*60*1000;  // a specific action counts as "now" this long
function maestroMode(){
  const evs=(lastState&&lastState.events)||[];
  const workingN=lastAgents.filter(a=>a.working).length;
  let lastTs=0;
  // tier 1: a fresh specific action wins
  for(let i=evs.length-1;i>=0;i--){
    const e=evs[i],age=Date.now()-ts(e);
    if(!lastTs)lastTs=ts(e);
    if(age>MAESTRO_FRESH_MS)break;
    switch(e.event){
      case "review":return [(e.verdict==="pass"?"✅ reviewed ":"❌ review failed — ")+(e.task||""),true];
      case "handoff_start":{const p=persona(e.subagent_type);return ["🎯 assigned "+p.name+" — "+(e.description||"").slice(0,26),true];}
      case "subagent_stop":{const p=persona(e.agent_type);return ["📥 "+p.name+" reported — reviewing",true];}
      case "stop_block":return ["✋ completing the ledger",true];
      case "gate_block":return ["🛡️ gate fired — replanning",true];
      case "session_start":return ["session started",true];
      case "handoff_end":continue;
      case "activity":
        if(!e.agent_type){
          if((e.detail||"").toLowerCase().includes("plan.md"))return ["📝 updating plan.md",true];
          return [toolIcon(e.tool)+" verifying / working",true];
        }
        return ["🕐 awaiting reports · agents working",true];
      default:continue;
    }
  }
  // tier 2: not fresh, but agents are still out working -> NOT idle
  if(workingN>0)return ["🕐 awaiting reports · "+workingN+" working",true];
  // tier 3: genuinely nothing in flight
  if(!lastTs){for(let i=evs.length-1;i>=0;i--){if(evs[i].ts){lastTs=ts(evs[i]);break;}}}
  return ["idle"+(lastTs?" — last active "+rel(new Date(lastTs).toISOString()):""),false];
}
let maestroActive=false;  // Maestro itself doing work (not just awaiting reports)
function renderMaestro(){
  const mst=$("mstate"),mact=$("mact");
  if(!mst)return;
  const [mode,busy]=maestroMode();
  mst.textContent=mode;
  const acts=maestroActs(),last=acts[acts.length-1];
  mact.textContent=last&&(Date.now()-ts(last))<MAESTRO_FRESH_MS?toolIcon(last.tool)+" "+(last.detail||last.tool):"";
  // KEEL ADDITION (T335): the Captain's pill. A recorded model wears the
  // Captain's own accent like any agent tag; an unrecorded one wears the
  // surface greys and says so, so the card never dresses a hole as a fact.
  const mm=$("mmodel");
  if(mm){
    const om=sessionModel(latestSession);
    mm.textContent=om||"model unrecorded";
    mm.classList.toggle("unknown",!om);
    mm.title=om?"the model this session registered at session_start"
      :"this session's start line recorded no model (the harness supplied none); effort is not recorded for a session at all";
  }
  const c=nodeEls.get("__center");
  if(c)c.classList.toggle("busy",busy&&mode!=="session started");
  maestroActive=busy&&mode!=="session started"&&!mode.startsWith("🕐");
  if(maestroActive)$("empty").hidden=true;  // never show the hint over a working Maestro
}

function chipText(el){
  const t=Date.now()-(+el.dataset.start);
  // stall keys off last observed activity, not launch time - long
  // background builds with a fresh activity stream are not "stalled"
  const seen=+el.dataset.lastSeen||+el.dataset.start;
  const stalled=(Date.now()-seen)>STALL_MS;
  el.classList.toggle("stall",stalled);
  const label=el.dataset.bg==="1"?"background · ":"working · ";
  return label+fmtDur(t)+(stalled?" ⚠ stalled?":"");
}

function finishTs(a){
  if(a.stop)return ts(a.stop);
  if(a.end&&!a.background)return ts(a.end);
  return a.lastSeen||(a.end?ts(a.end):(a.start?ts(a.start):0));
}

function computeStates(agents){
  // phase 0: flags + same-type ordering (session-scoped: an old session's
  // unresolved agents must never absorb a new session's signals)
  agents.forEach(a=>{
    // T323: the CLOSE half's own "background" field (written by
    // hooks/keel_capture.py's HANDOFF_BACKGROUND_KEY, structural - the
    // launch result's own status, not a timing guess) is trusted whenever
    // it is present, boolean either way. Only a record from BEFORE that
    // field existed (absent key, or present as null/non-boolean) falls
    // back to the launch/return gap - the read side must never let the
    // gap OVERRIDE a fresh record's own answer, or the exact race T323
    // exists to close (a slow background acknowledgment misread as a
    // finished foreground return) comes back for every fresh record too.
    const bgField=a.end?a.end.background:undefined;
    a.background=(typeof bgField==="boolean")?bgField
      :!!(a.start&&a.end&&(ts(a.end)-ts(a.start))<BG_MS);
    a.stop=null;a.abandoned=false;a.stale=false;
  });
  const byType=new Map();
  agents.filter(x=>x.start).forEach(x=>{
    const k=(x.start.session_id||"?")+"|"+(x.start.subagent_type||"?");
    if(!byType.has(k))byType.set(k,[]);byType.get(k).push(x);});
  byType.forEach(list=>{list.sort((x,y)=>ts(x.start)-ts(y.start));
    list.forEach((x,i)=>x.nextSameTypeStart=list[i+1]?ts(list[i+1].start):0);});

  // phase 1: assign stop signals FROM THE SIGNAL'S PERSPECTIVE - each stop
  // closes the most-recently-launched still-open same-type/session agent.
  // Robust to lost signals: a missing stop strands only its own agent
  // (liveness sweeps it up) instead of shifting every later pairing.
  lastStops.slice().sort((x,y)=>ts(x)-ts(y)).forEach(s=>{
    const sk=(s.session_id||"?")+"|"+(s.agent_type||"?");
    let best=null;
    for(const a of agents){
      if(!a.background||a.stop||!a.start)continue;
      const ak=(a.start.session_id||"?")+"|"+(a.start.subagent_type||"?");
      if(ak!==sk||ts(a.start)>ts(s))continue;
      if(!best||ts(a.start)>ts(best.start))best=a;
    }
    if(best){best.stop=s;s.__owner=best.start.subagent_type;}
  });

  // phase 2: resolve working state
  //
  // KEEL ADDITION (T609/BL22, 2026-09-06): an UNPAIRED delegation (a
  // handoff_start with no handoff_end - the ghost card) used to read
  // ``working=!a.abandoned`` with ONLY ``ABANDON_MS`` (2h) as a bound, so an
  // agent the API killed outright - no stop, no activity, ever again - still
  // wore "working" for up to two hours on nothing but its own launch time.
  // The background branch right below already had the honest shape: bound
  // liveness by the delegation's OWN newest event (its last real activity,
  // ``actsFor`` - the same window every other reader of this record uses),
  // not by launch age alone. An unpaired delegation now gets the same
  // check, at ``LIVENESS_MS`` scale (10min - "no stop signal & no activity
  // this long -> presumed finished", the constant's own comment above, and
  // exactly the bound the background branch already trusted for the same
  // question) - ``ABANDON_MS`` (2h) stays the OUTER bound unchanged, so a
  // launch old enough to clear THAT is still ``abandoned``, never merely
  // "stale". A stale delegation is neither "working" (nothing says so) nor
  // silently "finished" (nothing says that either) - a THIRD state,
  // ``a.stale``, distinct from both, so the card can say what it is: no
  // event since <when>, not a guess at which.
  let anyWorking=false;
  agents.forEach(a=>{
    const unpaired=!!(a.start&&!a.end);
    a.review=reviewFor(a);  // verdict badge (and completion fallback below)
    if(a.background&&!a.stop&&a.review)a.stop=a.review;  // reviewed => finished
    let working, lastSeen=a.start?ts(a.start):0;
    if(unpaired){
      const acts=actsFor(a);
      if(acts.length)lastSeen=ts(acts[acts.length-1]);
      a.abandoned=(Date.now()-ts(a.start))>ABANDON_MS;
      a.stale=!a.abandoned&&(Date.now()-lastSeen)>=LIVENESS_MS;
      working=!a.abandoned&&!a.stale;
    }else if(a.background&&!a.stop){
      // launched in background, no completion signal yet: alive while its
      // own activity is fresh (or just launched), else presumed finished
      const acts=actsFor(a);
      if(acts.length)lastSeen=ts(acts[acts.length-1]);
      working=(Date.now()-lastSeen)<LIVENESS_MS&&(Date.now()-ts(a.start))<ABANDON_MS;
    }else{
      working=false;
    }
    if(working)anyWorking=true;
    a.working=working;
    a.lastSeen=lastSeen;
  });
  return anyWorking;
}

// elliptical ring geometry: reserve a band at the bottom for the bench so
// cards never crowd the orchestrator or sit on the sleeping pills.
// KEEL ADDITION (T324, owner design correction 2026-08-25 - LAYOUT
// COLLISION FIX): CARD_H used to be the bare card height (152), which
// never accounted for a chip rail hanging under it - so the ring
// reserved less room than a card with a rail actually occupies, and at
// the top-of-ring position that shortfall let a rail run off the
// viewport's top edge while its downward growth (the rail is appended
// BELOW a card's own content, growing toward screen-center regardless of
// which side of the ring the card sits on) reached into the Captain
// card. CHOSEN FIX: a fixed max footprint, not DOM measurement - T324
// also caps the rail at <=3 rows with no overflow line (see chipRailFor
// above), so its tallest possible shape is now a KNOWN CONSTANT rather
// than something that has to be measured; the 64px band below reserves
// exactly that constant, so every card's reserved footprint already
// includes what hangs off it whether or not anything is hanging there
// now. CENTER_HALF_H is the Captain's OWN measured max half-height (its
// avatar/name/role/chip/act stack plus its own band, ~236px full
// height); CENTER_HALF_W is half its CSS width
// (``.node.center{width:206px}`` above, border-box) - together they are
// the Captain's clearance box, which ``ringPos`` below keeps every ring
// card out of.
// KEEL ADDITION (T332): the constant is RENAMED, never re-valued -
// RAIL_MAX_H reserved the branch rail that T332 replaced with orbit mini
// cards, so a name saying "rail" would name something the page no longer
// draws. ORBIT_BAND_H is the SAME 64px, reserved for the same reason
// (what a hub carries beyond its own card body), and every ring position
// this solver returns is therefore byte-for-byte the position it returned
// before T332 - the T324 owner correction is preserved exactly, not
// re-derived. What the satellites reach BEYOND this band is answered by
// ``sceneFit`` below, which shrinks the whole scene rather than letting a
// mini card hang off the stage.
const ORBIT_BAND_H=64,CENTER_HALF_H=120;
const BENCH_H=78,CARD_W=150,CARD_H=152+ORBIT_BAND_H;
const CENTER_HALF_W=103;
// The two half-extents a ring card must clear to be outside the Captain's
// box: it is INSIDE only when BOTH |x-cx|<CLEAR_X and |y-cy|<CLEAR_Y hold,
// so clearing EITHER axis is enough - a card pinned to the viewport's top
// edge is fine as long as it stands far enough aside.
const CLEAR_X=CENTER_HALF_W+CARD_W/2,CLEAR_Y=CENTER_HALF_H+CARD_H/2;

// KEEL ADDITION (T324 retry, 2026-08-25 - CLEARANCE THAT HOLDS AT EVERY
// VIEWPORT SIZE): the per-card ring position, PURE (index, count, stage
// W/H, plus the constants above -> [x,y]) so the guarantee it makes can be
// pinned numerically without a browser; layout() below is its only caller.
// Review finding it answers: the old code clamped y to the viewport AFTER
// deriving it from Ry's captain-clearance floor, so on a stage shorter than
// ~766px the clamp overrode that floor and pulled the top-of-ring card back
// into the Captain (H=700: cy=311, y clamped 116, 195px apart where 228 is
// required) - the guarantee the comment claimed was simply false there.
// WHAT IS GUARANTEED NOW, at every W/H:
//   (a) the card stays inside the viewport (and off the bench band) - this
//       constraint always wins, because a card nobody can see is worse than
//       a crowded one;
//   (b) the card stays out of the Captain's clearance box, which is 2D:
//       satisfied by x-distance OR y-distance, not by y alone.
// TIE-BREAK when the natural ring point cannot satisfy (b) - i.e. the stage
// is too short for the y term to clear the box: the card is pushed OUTWARD
// in x (its effective Rx widens to at least CLEAR_X) rather than accepting
// overlap, keeping the ring's own side - right for cos(ang)>=0, left
// otherwise, so the exact-top and exact-bottom cards (cos == 0) go right,
// deterministically. If that side has no room left in the viewport, the
// mirror side is taken; if NEITHER side can clear the box (a stage narrower
// than 2*(CLEAR_X+CARD_W/2+12), i.e. 530px), (a) still wins: the card takes
// the widest x the viewport allows and the y extreme furthest from the
// Captain, which is the least-overlap position that is still fully on
// screen. One honest limit: on a stage with less room than a single card
// (H-BENCH_H < CARD_H+8, or W < CARD_W+24), nothing can satisfy (a) either
// - the clamps then keep the top/left edge visible and let the card spill
// past the far edge, exactly as they did before this change.
function ringPos(i,count,W,H){
  const cx=W/2,cy=(H-BENCH_H)/2;
  // radii shrink with the viewport; positions are then hard-clamped so a
  // card (its reserved band included) can never hang off any edge or sit
  // on the bench.
  const Rx=Math.max(140,W/2-CARD_W/2-22);
  const Ry=Math.max(84,CLEAR_Y+10,(H-BENCH_H)/2-CARD_H/2-8);
  const xLo=CARD_W/2+12,xHi=Math.max(xLo,W-CARD_W/2-12);
  const yLo=CARD_H/2+8,yHi=Math.max(yLo,H-BENCH_H-CARD_H/2);
  const clampX=v=>Math.min(Math.max(v,xLo),xHi);
  const clampY=v=>Math.min(Math.max(v,yLo),yHi);
  const ang=-Math.PI/2+i*(2*Math.PI/Math.max(count,3));
  const reach=Rx*Math.cos(ang);
  let x=clampX(cx+reach),y=clampY(cy+Ry*Math.sin(ang));
  if(Math.abs(x-cx)<CLEAR_X&&Math.abs(y-cy)<CLEAR_Y){
    const dir=Math.cos(ang)>=0?1:-1,out=Math.max(CLEAR_X,Math.abs(reach));
    const own=clampX(cx+dir*out),mirror=clampX(cx-dir*out);
    x=Math.abs(mirror-cx)>Math.abs(own-cx)?mirror:own;
    if(Math.abs(x-cx)<CLEAR_X)y=(cy-yLo)>=(yHi-cy)?yLo:yHi;
  }
  return [x,y];
}

// ---- KEEL ADDITION (T332): orbit geometry + the one viewport fit --------
// PURE, like ``ringPos`` above and for the same reason: every guarantee
// below is arithmetic on constants, so it can be pinned numerically without
// a browser. ``layout()`` is the only caller of any of it.
//
// ORBIT_W/ORBIT_H MUST MATCH the CSS ``.tnode{width:96px;height:30px}``
// above - the mini card's footprint is reserved from these constants and
// never measured off the DOM, the same lockstep-by-comment rule
// ORBIT_BAND_H and BG_LAUNCH_MS/BG_MS already follow in this file.
//
// THE TWO RADII ARE NOT TASTE, they are the smallest radius at which a
// satellite's box cannot touch its hub's box at ANY angle. A satellite is
// clear when |dx| >= hubHalfW+ORBIT_W/2 OR |dy| >= hubHalfH+ORBIT_H/2, so
// the worst angle is the one where both terms are exactly met at once, and
// the radius needed there is hypot(those two sums):
//   ring hub  (152x152 card, halves 75/76): hypot(75+48, 76+15)  = 153.0 -> 156
//   Captain   (206x240 card, halves 103/120): hypot(103+48,120+15)= 202.6 -> 206
// ORBIT_STEP is derived, not chosen: the angular step whose CHORD at a given
// radius is one mini card wide plus a gap, so two satellites of the same hub
// can never overlap each other either.
const ORBIT_W=96,ORBIT_H=30;
const ORBIT_R=156,CENTER_ORBIT_R=206,ORBIT_GAP=8;
const FIT_PAD=6;
function orbitStep(r){return 2*Math.asin(Math.min(0.9,(ORBIT_W+ORBIT_GAP)/(2*r)));}
// ---- KEEL ADDITION (T333, owner review of the live board 2026-08-25): a
// hub's tasks HANG BELOW IT. The T332 fan aimed satellites outward (ring
// hubs) or into the ring's widest angular gap (the Captain), which put a
// task anywhere on the clock and read as arbitrary; the owner asked for a
// shape a reader can predict - the first satellite directly under the card,
// the next two under it to the right and to the left, and only then out to
// the sides. Nothing about the SIZES changed: the radii, the own-hub
// no-touch arithmetic above and the sibling step are exactly T332's, so
// every clearance pin still holds; this is the ORDER OF BEARINGS only.
//
// Slot j takes offset 0, -step, +step, -2*step, +2*step ... from the base
// bearing, and at the "below" base (+PI/2, y grows downward) that reads
// below, below-right, below-left, right-ish, left-ish - the owner's order.
// A one-sided base (the horizontal fallbacks) walks UPWARD only, so a fan
// pushed off the bench can never curl back into it.
function slotBearings(base,n,step){
  const oneSided=(base===0||base===Math.PI),out=[];
  for(let j=0;j<n;j++){
    let off;
    if(oneSided)off=-j*step*(base===0?1:-1);
    else{const k=Math.ceil(j/2);off=(j%2===1?-1:1)*k*step;}
    out.push(base+off);
  }
  return out;
}
function slotsAt(hx,hy,bearings,r){
  return bearings.map(a=>[hx+r*Math.cos(a),hy+r*Math.sin(a)]);
}
// How bad a fan is, in two kinds of badness that are NOT interchangeable:
//   * OFF THE STAGE - any slot over the bench strip or past the top edge.
//     That is the owner's own rule ("fan outward rather than into it") and it
//     is DISQUALIFYING: Infinity, never traded against anything.
//   * ON ANOTHER CARD - a slot overlapping one of the boxes this hub was told
//     to avoid (the Captain's card for a ring hub, the ring cards for the
//     Captain's own fan). That is a preference, COUNTED rather than fatal,
//     because a single crowded slot must not cost the whole below-anchor the
//     owner asked for: a fan with one brush against a neighbour still reads
//     better than one aimed somewhere unpredictable.
function slotsPenalty(slots,yMax,blockers){
  let hits=0;
  for(const s of slots){
    if(s[1]+ORBIT_H/2>yMax||s[1]-ORBIT_H/2<0)return Infinity;
    for(const b of(blockers||[])){
      if(s[0]+ORBIT_W/2>b[0]&&s[0]-ORBIT_W/2<b[2]
       &&s[1]+ORBIT_H/2>b[1]&&s[1]-ORBIT_H/2<b[3])hits++;
    }
  }
  return hits;
}
// The bases, in the owner's own order of preference: BELOW first, then
// outward horizontally on the hub's own side of the stage (fanning upward,
// away from the bench - the "fan outward rather than into it" rule), then
// the far side, then above. The best-scoring base wins and TIES GO TO THE
// EARLIER BASE, so "below" is kept unless something strictly better exists -
// the anchor moves only for a reason, never for a rounding difference.
// If every base is off the stage - a hub hemmed in on all four - the
// below-anchor is kept anyway and ``sceneFit`` answers for it by shrinking
// the scene, which is the one remedy that cannot hide a satellite: a scaled
// board still shows every card, where a silently re-aimed one would put a
// task somewhere the reader cannot predict.
function orbitSlots(hx,hy,n,r,yMax,side,blockers){
  if(!n)return[];
  const step=orbitStep(r);
  const out=side>=0?0:Math.PI,far=side>=0?Math.PI:0;
  const bases=[Math.PI/2,out,far,-Math.PI/2];
  let best=null,bestScore=Infinity,first=null;
  for(const b of bases){
    const slots=slotsAt(hx,hy,slotBearings(b,n,step),r);
    if(first===null)first=slots;
    const score=slotsPenalty(slots,yMax,blockers);
    if(score<bestScore){bestScore=score;best=slots;}
    if(bestScore===0)break;
  }
  return best||first;
}
// A ring card's satellites: below it first, and the horizontal fallback goes
// out towards the card's own side of the stage. The box they must dodge is
// the Captain's card - the one thing standing between a ring card and the
// middle of the board.
function ringOrbitSlots(hx,hy,n,cx,cy,yMax){
  return orbitSlots(hx,hy,n,ORBIT_R,yMax,(hx>=cx)?1:-1,
    [[cx-CENTER_HALF_W,cy-CENTER_HALF_H,cx+CENTER_HALF_W,cy+CENTER_HALF_H]]);
}
// The Captain's own satellites follow the same rule from the middle of the
// board, dodging the ring cards themselves (their visible boxes, not their
// reserved band) so a self-run task never lands on a delegate.
function centerOrbitSlots(n,points,cx,cy,yMax){
  const blockers=(points||[]).map(p=>[p[0]-CARD_W/2,p[1]-76,p[0]+CARD_W/2,p[1]+76]);
  return orbitSlots(cx,cy,n,CENTER_ORBIT_R,yMax,1,blockers);
}
// ONE UNIFORM SCALE, the owner's viewport-fit adjustment (2026-08-25).
// ``boxes`` are every drawn box in stage pixels ([x0,y0,x1,y1]: the centre
// card, each ring card at its reserved footprint, each satellite, AND each
// wire's own reach - see ``wireBox``; a bezier's bow is drawn outside the
// straight line between the two cards it joins, so a fit told only about
// cards would clip the edge layer while reporting success, which is the
// review finding this list answers). The answer is the transform
// ``layout()`` writes onto BOTH the node layer and the edge layer, so cards
// and the wires between them move as one drawing.
//   * ALREADY FITS -> the identity (s=1, no shift). A board with no
//     satellites and no bowing wire is therefore pixel-identical to the
//     pre-T332 board: the ring solver already keeps every card inside
//     (0,0)-(W,H-BENCH_H), so this branch is the one that fires there, and
//     nothing is scaled or nudged at all.
//   * DOES NOT FIT -> the largest scale that puts the whole bounding box
//     inside the stage minus FIT_PAD on every side, centred in what is
//     left. Never scales UP (s<=1): a sparse scene is not magnified.
// The bench band stays reserved exactly as ``ringPos`` reserves it, so the
// scene can never be scaled down onto the sleeping pills.
function sceneFit(boxes,W,H){
  if(!boxes||!boxes.length)return{s:1,tx:0,ty:0};
  let x0=Infinity,y0=Infinity,x1=-Infinity,y1=-Infinity;
  for(const b of boxes){
    if(b[0]<x0)x0=b[0]; if(b[1]<y0)y0=b[1];
    if(b[2]>x1)x1=b[2]; if(b[3]>y1)y1=b[3];
  }
  const stageH=H-BENCH_H;
  if(x0>=0&&y0>=0&&x1<=W&&y1<=stageH)return{s:1,tx:0,ty:0};
  const availW=Math.max(1,W-2*FIT_PAD),availH=Math.max(1,stageH-2*FIT_PAD);
  const bw=Math.max(1,x1-x0),bh=Math.max(1,y1-y0);
  const s=Math.min(1,availW/bw,availH/bh);
  return{s:s,
    tx:FIT_PAD+(availW-bw*s)/2-x0*s,
    ty:FIT_PAD+(availH-bh*s)/2-y0*s};
}

// ---- KEEL ADDITION (T332): ONE wire renderer, two scales ----------------
// The quadratic bezier below is the vendored Captain->agent edge formula,
// moved here VERBATIM (same 0.14 control-point bow, same dash pattern, same
// travelling dot) rather than copied: the ring's own edges are now drawn
// through it too, so a hub->task wire cannot drift away from the wire
// language it is meant to be speaking. Only the sizes differ at the call
// site - ring edges keep their exact 2.4/1.4 widths and r=4 dot, task wires
// run one size down (1.6/1.1, r=2.6) so a satellite reads as subordinate to
// its hub. ``live`` is the running/idle split: dashed + flowing + a dot when
// live, a faint static line when not.
function wireCtrl(ax,ay,bx,by){
  return[(ax+bx)/2+(by-ay)*0.14,(ay+by)/2-(bx-ax)*0.14];
}
function wireD(ax,ay,bx,by){
  const c=wireCtrl(ax,ay,bx,by);
  return`M${ax} ${ay} Q${c[0]} ${c[1]} ${bx} ${by}`;
}
function wireSvg(ax,ay,bx,by,col,live,wLive,wIdle,dotR,dur){
  const d=wireD(ax,ay,bx,by);
  return`<path d="${d}" fill="none"
        stroke="${col}" stroke-opacity="${live?0.85:0.22}" stroke-width="${live?wLive:wIdle}"
        ${live?'stroke-dasharray="7 7" class="flow"':""} stroke-linecap="round"/>`
    +(live?`<circle r="${dotR}" fill="${col}"><animateMotion dur="${dur}" repeatCount="indefinite" path="${d}"/></circle>`:"");
}
// KEEL ADDITION (T332, correctness review finding 2026-08-25): A WIRE HAS ITS
// OWN REACH, and the viewport fit has to be told about it. ``sceneFit`` below
// is fed boxes; before this it was fed only card boxes, so a wire whose BOW
// left the stage while both of its endpoints sat comfortably inside was
// invisible to the fit - the code promised "nothing clipped" and could only
// see the cards. The bow is not small: it is 0.14 of the endpoint distance at
// the control point, half that at the curve itself, which is tens of pixels
// on a Captain->ring wire.
//
// WHAT THIS BOX IS, and why it is the curve's extent rather than a guess.
// Writing D for the control point minus the chord's own midpoint, the
// quadratic satisfies B(t) = chord(t) + 2t(1-t)*D, and 2t(1-t) runs over
// [0, 0.5] - so every point of the curve is a point of the chord displaced
// by at most D/2, i.e. the whole curve lies in the parallelogram spanned by
// the chord and by the chord shifted by D/2. Its four corners are the two
// endpoints and those same two endpoints shifted by D/2, which is exactly
// what this bbox is taken over. The apex (t=0.5, the deepest point of the
// bow) is the midpoint of the two shifted corners and therefore already
// inside it. The CONTROL POINT itself would also bound the curve - the hull
// of P0,C,P2 contains it - but it bounds it at twice the true depth, which
// would shrink the board for clearance no wire ever uses; this one is tight.
// ``dotR`` widens it by the travelling dot's radius, since the dot rides the
// same path and is drawn as a disc on it.
function wireBox(ax,ay,bx,by,dotR){
  const c=wireCtrl(ax,ay,bx,by);
  const dx=(c[0]-(ax+bx)/2)/2,dy=(c[1]-(ay+by)/2)/2;
  const xs=[ax,bx,ax+dx,bx+dx],ys=[ay,by,ay+dy,by+dy];
  return[Math.min.apply(null,xs)-dotR,Math.min.apply(null,ys)-dotR,
         Math.max.apply(null,xs)+dotR,Math.max.apply(null,ys)+dotR];
}

function layout(agents,railEvents){
  // agents = the VIEW (round-filtered); states were already computed on
  // the full set in tick(). railEvents = the SAME round-filtered event view
  // (T322) - task chips must respect the selected round exactly like the
  // agent cards themselves.
  const stage=$("stage"),W=stage.clientWidth,H=stage.clientHeight;
  const now=Date.now();
  const cx=W/2,cy=(H-BENCH_H)/2;
  const anyWorking=agents.some(a=>a.working);
  const center=ensureCenter(cx,cy);
  const seen=new Set(["__center"]);

  // pass 2: the ring shows only active agents + just-finished ones
  const ring=agents.filter(a=>a.working||(Date.now()-finishTs(a))<RETIRE_MS).slice(-8);
  const pos={};
  ring.forEach((a,i)=>{pos[a.uid]=ringPos(i,ring.length,W,H);});
  ring.forEach(a=>{
    seen.add(a.uid);
    const e=a.start||a.end,p=persona(e.subagent_type);
    const working=a.working;
    let el=nodeEls.get(a.uid);
    if(!el){
      el=document.createElement("div");
      el.innerHTML=`<div class="card">
        <span class="modeltag">${esc(modelOf(e))}</span>
        <div class="top"><div class="avatar">${robotSVG(p.v,p.kind)}<span class="emb">${p.emb}</span></div>
        <div><div class="who">${p.name}</div><div class="role">${p.role}</div></div></div>
        <div class="task">${esc(e.description||e.prompt_head||"")}</div>
        <span class="chip"></span><div class="act"></div>
        </div>`;  /* KEEL ADDITION (T332): the rail is gone - this card's live
        tasks orbit it as mini cards, wired in the ring's own wire language */
      el.dataset.uid=a.uid;
      $("nodes").appendChild(el);nodeEls.set(a.uid,el);
      if(a.start)el.dataset.start=ts(a.start);
      // KEEL ADDITION (T132): a null model with no fallback wears no tag -
      // "agent" was a copy string the record never signed off on
      // (.keel/knowledge/model-tags-copy-strings-the-record-never-validates.md).
      // The vendored `modelOf` (its map included) stays byte-identical;
      // "agent" is the ONLY string that literal can produce, and only when
      // both `e.model` and the fallback map are absent, so re-checking that
      // one output is exactly reading the same two facts modelOf already
      // read - this just empties the span this line already created.
      // KEEL ADDITION (T337 extension): the tag is left EMPTY rather than
      // removed, and filled from the run's route on every tick below. T132's
      // rule is unchanged in outcome - an unknown model wears no tag - because
      // ``.modeltag:empty`` paints nothing; what changes is that a resume run
      // whose agent's own dispatch recorded a model can now wear it.
      if(modelOf(e)==="agent"){const mt=el.querySelector(".modeltag");if(mt)mt.textContent="";}
    }
    el.className="node "+(working?"working":"done");
    el.style.setProperty("--c",`var(${p.v})`);
    // KEEL ADDITION (T337 extension): the pill says what this run ran at,
    // inheriting the agent's own dispatch route where the run itself carries
    // none (a resume records neither model nor effort). No label -> empty
    // span -> nothing drawn, which is T132's rule kept.
    const mtag=el.querySelector(".modeltag");
    if(mtag){const lbl=runModel(a,lastAgents);mtag.textContent=lbl||"";}
    const [x,y]=pos[a.uid];el.style.left=x+"px";el.style.top=y+"px";
    el.dataset.bg=a.background?"1":"0";
    el.dataset.lastSeen=a.lastSeen||"";
    const chip=el.querySelector(".chip");
    const badge=a.review?(a.review.verdict==="pass"?" · review ✓":" · review ✗"):"";
    if(working){chip.textContent=chipText(el);}
    else if(a.abandoned){chip.textContent="⚠ no report (aborted?)";el.classList.remove("working");}
    // KEEL ADDITION (T609/BL22): a THIRD state, never folded into "working"
    // or "reported back" - see computeStates above for why this is not the
    // same thing as ``a.abandoned``.
    else if(a.stale){chip.textContent="⏳ stale — no event since "+rel(new Date(a.lastSeen).toISOString());el.classList.remove("working");}
    else if(a.background){
      chip.textContent=(a.stop?"finished · "+fmtDur(ts(a.stop)-ts(a.start)):"finished (background)")+badge;
    }
    else{const d=a.start&&a.end?" · "+fmtDur(ts(a.end)-ts(a.start)):"";chip.textContent="reported back"+d+badge;}
    // KEEL ADDITION (T132): a resume is not a launch it "reported back"
    // from - either half of a resumed hand-off carries handoff_kind:
    // "resume" (T124); this card verb reads "resumed" instead, touching
    // no vendored line above, only the chip text it already set.
    if((a.end&&a.end.handoff_kind==="resume")||(a.start&&a.start.handoff_kind==="resume"))
      chip.textContent=chip.textContent.replace(/^reported back/,"resumed");
    const actEl=el.querySelector(".act");
    if(actEl){
      const acts=working?actsFor(a):[];
      const last=acts[acts.length-1];
      actEl.textContent=last?toolIcon(last.tool)+" "+(last.detail||last.tool):"";
    }
  });

  /* ---- KEEL ADDITION (T332): the orbit pass - every hub is an orchestrator
     of its own tasks. The DATA is exactly the data the branch rail used
     (``chipRailFor``, whose attribution T332 does not touch): the tracked
     session's own untyped tool/background/gate events belong to the Captain
     - that is the orchestrator-self case, a task the session ran with no
     subagent between it and the tool - and a delegate's are scoped by the
     same session+agent_type+window rule ``actsFor`` uses. What changed is
     only where they are drawn. A hub with nothing live in scope produces no
     satellite and no wire, so an idle agent's card is exactly the card it
     was before T322. Satellites are reaped by the same ``seen`` sweep the
     ring cards use, keyed by hub+slot, and carry no click target of their
     own (``pointer-events:none`` in the CSS) - the drawer still belongs to
     the card that owns the task. */
  const orbits=[];
  const ringPts=ring.map(a=>pos[a.uid]);
  // KEEL ADDITION (T333): the bench line every fan must stay above - the same
  // band ``ringPos`` and ``sceneFit`` reserve, passed in rather than re-derived.
  const yMax=H-BENCH_H;
  const capItems=orbitCardsFor(null,railEvents,now);
  centerOrbitSlots(capItems.length,ringPts,cx,cy,yMax).forEach((q,j)=>{
    orbits.push({hub:"__center",hx:cx,hy:cy,x:q[0],y:q[1],slot:j,
                 item:capItems[j],pv:PERSONAS.orchestrator.v});
  });
  ring.forEach(a=>{
    const e=a.start||a.end,p=persona(e.subagent_type);
    const hx=pos[a.uid][0],hy=pos[a.uid][1];
    const items=orbitCardsFor(a,railEvents,now);
    ringOrbitSlots(hx,hy,items.length,cx,cy,yMax).forEach((q,j)=>{
      orbits.push({hub:a.uid,hx:hx,hy:hy,x:q[0],y:q[1],slot:j,item:items[j],pv:p.v});
    });
  });
  orbits.forEach(o=>{
    const key="__orbit|"+o.hub+"|"+o.slot;
    seen.add(key);
    let el=nodeEls.get(key);
    if(!el){el=document.createElement("div");$("nodes").appendChild(el);nodeEls.set(key,el);}
    el.className="tnode tnode-"+o.item.cls;
    el.style.setProperty("--c",`var(${o.pv})`);
    el.style.left=o.x+"px";el.style.top=o.y+"px";
    const html=orbitCardHtml(o.item);
    if(el.dataset.html!==html){el.dataset.html=html;el.innerHTML=html;}
  });

  for(const[k,el]of nodeEls){if(!seen.has(k)){el.remove();nodeEls.delete(k);}}
  center.classList.toggle("busy",anyWorking);

  /* KEEL ADDITION (T332, owner adjustment - VIEWPORT FIT): every box the
     scene draws, handed to ``sceneFit`` as one list, and the single
     transform it answers written to BOTH layers. Ring cards are reserved at
     CARD_W x CARD_H (the T324 footprint, band included) rather than at their
     visible height, so a board with no satellites and no bowing wire hits
     sceneFit's already-fits branch and is left completely untransformed.
     EVERY WIRE IS IN THIS LIST TOO (review finding 2026-08-25): a bezier
     bows away from the straight line between its endpoints, so the edge
     layer can reach past the stage while both cards it joins sit inside it -
     see ``wireBox`` above for the bound and why it is the curve's own
     extent. The dot radii here are the ones the matching ``wireSvg`` calls
     below draw with (4 on the ring, 2.6 on a task wire); a wire and its fit
     box must always be built from the same pair of endpoints. */
  const boxes=[[cx-CENTER_HALF_W,cy-CENTER_HALF_H,cx+CENTER_HALF_W,cy+CENTER_HALF_H]];
  ring.forEach(a=>{const q=pos[a.uid];
    boxes.push([q[0]-CARD_W/2,q[1]-CARD_H/2,q[0]+CARD_W/2,q[1]+CARD_H/2]);
    boxes.push(wireBox(cx,cy,q[0],q[1],4));});
  orbits.forEach(o=>{
    boxes.push([o.x-ORBIT_W/2,o.y-ORBIT_H/2,o.x+ORBIT_W/2,o.y+ORBIT_H/2]);
    boxes.push(wireBox(o.hx,o.hy,o.x,o.y,2.6));});
  const fit=sceneFit(boxes,W,H);
  const tf=(fit.s===1&&!fit.tx&&!fit.ty)?"none"
    :`translate(${fit.tx}px,${fit.ty}px) scale(${fit.s})`;
  $("nodes").style.transform=tf;$("edges").style.transform=tf;

  const orbitSig=orbits.map(o=>o.hub+"~"+o.item.key+"~"+o.item.cls
    +"@"+Math.round(o.x)+","+Math.round(o.y)).join(";");
  const sig=ring.map(a=>a.uid+(a.working?"w":"e")).join(",")+"|"+W+"x"+H+"|"+orbitSig;
  if(sig!==edgeSig){
    edgeSig=sig;
    let lines="";
    ring.forEach(a=>{
      const e=a.start||a.end,p=persona(e.subagent_type);
      const [x,y]=pos[a.uid],working=!!a.working;
      const col=css(p.v);
      lines+=wireSvg(cx,cy,x,y,col,working,2.4,1.4,4,"1.6s");
    });
    // KEEL ADDITION (T332, RECOLOURED T333): the hub->task wires, drawn by
    // the SAME renderer one size down - a running task gets the bright dashed
    // wire and its travelling dot, a completed one the faint line, exactly as
    // a working vs reported-back agent does on the ring above.
    // T333 (owner review 2026-08-25): they no longer take the hub's persona
    // colour. Persona colour on a wire is the Captain->agent language, gold
    // included, and a task wire wearing it made the two kinds of wiring one
    // kind at a glance. Every task wire - a delegate's and the Captain's own
    // self-run task alike - is --taskwire instead, so the fractal layer reads
    // as its own layer. OWNERSHIP STILL READS BY COLOUR: the satellite CARD
    // keeps the hub's accent on its border and status dot (``o.pv``, set as
    // --c on the element above), which is where the T332 rule lives.
    const taskWire=css("--taskwire");
    orbits.forEach(o=>{
      lines+=wireSvg(o.hx,o.hy,o.x,o.y,taskWire,o.item.cls==="background",1.6,1.1,2.6,"1.9s");
    });
    $("edges").innerHTML=`<style>.flow{animation:dash 1.1s linear infinite}@keyframes dash{to{stroke-dashoffset:-14}}</style>`+lines;
  }

  // pass 3: the bench - the standing team, asleep until summoned
  renderBench(agents,lastAgents);
  $("empty").hidden=agents.length>0;
  return anyWorking;
}

function renderBench(roundAgents,allAgents){
  // The roster is built from EVERY agent ever seen in the log, so a persona
  // that worked in an earlier round rests on the bench instead of vanishing.
  // Working counts come from the selected round only.
  const groups=new Map();
  (allAgents||roundAgents).forEach(a=>{
    const e=a.start||a.end;if(!e)return;
    const k=e.subagent_type||"agent";
    /* KEEL ADDITION (T155): count how many of a group's runs the record
       itself calls resumes, so the card can name what it is instead of what
       it lacks. `handoff_kind` is a FIELD, not a guess. */
    if(!groups.has(k))groups.set(k,{runs:0,working:0,last:0,resumed:0});
    const g=groups.get(k);
    g.runs++;
    if(e.handoff_kind==="resume")g.resumed++;
    const t=finishTs(a)||ts(e); if(t>g.last)g.last=t;
  });
  roundAgents.forEach(a=>{
    const e=a.start||a.end;if(!e||!a.working)return;
    const g=groups.get(e.subagent_type||"agent"); if(g)g.working++;
  });
  const order=[...Object.keys(PERSONAS).filter(k=>k!=="_generic"&&k!=="orchestrator"),
               ...[...groups.keys()].filter(k=>!(k in PERSONAS))];
  $("bench").innerHTML=order.filter(k=>groups.has(k)).map(k=>{
    const g=groups.get(k),p=persona(k);
    const awake=g.working>0;
    const runs=`${g.runs} run${g.runs>1?"s":""}`;
    const stat=awake
      ? `⚡ ${g.working} working · ${runs}`
      : `💤 resting · ${runs}${g.last?" · last "+rel(new Date(g.last).toISOString()):""}`;
    /* KEEL ADDITION (T155): a group with no persona wears its OWN key, not
       the generic persona's name. MEASURED 2026-08-16 on this project's
       record: two different groups - a real `fork` type, and every launch
       whose type the record never carried (grouped above under the sentinel
       key "agent") - both fell through to the generic persona and rendered
       as two cards labelled "Agent". One name for two unlike things is the
       board saying something it cannot back.

       The sentinel group is named from the record rather than from the hole
       in it: MEASURED 2026-08-16, every launch in this project's log with no
       type carries `handoff_kind: "resume"` - all eighteen events, nine
       pairs, five of them findings sent back to a working executor and four
       re-reviews. A resume fires the hand-off pair without a launch tool
       call to read a type from, so the type is missing for a REASON the
       record states outright. The card says "resumed" only while that holds
       for every run in it, and falls back to "untyped" the moment one run
       arrives typeless for some other reason - the display never asserts
       more than the events do. */
    const label=(k in PERSONAS)?p.name
      :(k==="agent"?(g.resumed===g.runs?"resumed":"untyped"):k);
    return `<div class="bpill ${awake?"awake":"asleep"}" data-type="${esc(k)}" style="--c:var(${p.v})">
      <span class="bface">${robotSVG(p.v,p.kind)}</span><div><b>${esc(label)}</b><span class="bstat">${stat}</span></div></div>`;
  }).join("");
}

function renderLedger(plan){
  const rows=[...plan.matchAll(/^\s*[-*] \[([ x!?])\] *(.+)$/gm)];
  const cls={" ":"t-open",x:"t-done","!":"t-blocked","?":"t-decision"};
  const mark={" ":"○",x:"●","!":"⛔","?":"❓"};
  let done=0;
  $("ledger").innerHTML=rows.map(r=>{
    if(r[1]==="x")done++;
    const [txt,ac]=r[2].split(/\s*\|\s*AC:\s*/);
    return `<div class="task-item ${cls[r[1]]}"><span class="mark">${mark[r[1]]}</span>
      <span><span class="txt">${esc(txt)}</span>${ac?`<span class="ac">AC: ${esc(ac.split("|")[0])}</span>`:""}</span></div>`;
  }).join("")||`<div class="task-item t-open"><span class="mark">○</span><span class="txt" style="color:var(--ink3)">no plan.md yet</span></div>`;
  $("s-done").textContent=done+"/"+rows.length;
  $("plancount").textContent=rows.length?`${done} of ${rows.length}`:"";
  $("planfill").style.width=(rows.length?done/rows.length*100:0)+"%";
  return rows;
}

const rel=t=>{const s=Math.max(0,(Date.now()-new Date(t).getTime())/1000);
  return s<5?"now":s<60?Math.round(s)+"s ago":s<3600?Math.round(s/60)+"m ago"
    :s<86400?Math.round(s/3600)+"h ago":Math.round(s/86400)+"d ago";};
function renderFeed(events){
  const verbs={
    /* KEEL ADDITION (T342, closing BL3): this verb read
       ``e.orchestrator_model``, a field no record has ever carried - a branch
       that could never fire. The seat's model lives in ``model`` on the
       session_start line (real since T337's capture fallback), so the branch
       now reads the field that exists and stays silent when it is null. */
    session_start:e=>[`session started${e.source?" ("+esc(e.source)+")":""}`+(e.model?` — orchestrator: <b>${esc(e.model)}</b>`:""),"--maestro",false],
    handoff_start:e=>{const p=persona(e.subagent_type);return[`${bot(p)} <b>${p.name}</b> launched — ${esc(e.description||"")}`,p.v,false]},
    handoff_end:e=>{const p=persona(e.subagent_type);return[`${bot(p)} <b>${p.name}</b> reported back — ${esc(e.description||"")}`,p.v,false]},
    handoff:e=>{const p=persona(e.subagent_type);return[`${bot(p)} <b>${p.name}</b> reported back — ${esc(e.description||"")}`,p.v,false]},
    gate_block:e=>[`🛡️ <b>${e.gate==="policy_lock"?"POLICY LOCK":"PLAN GATE"}</b> blocked ${esc(e.tool||"")} — ${esc(e.detail||"")}`,"--bad",true],
    /* KEEL ADDITION (T342): the counts are served top-level now (see the
       lift beside the detail stringify), and this verb sums all three the
       gate can block on rather than naming the open one alone. When none of
       them is a number - an older line written before the lift - it says so
       without a count instead of printing "undefined". */
    stop_block:e=>{
      const n=["open_items","stale_inflight_items","unverified_filed_items"]
        .map(k=>typeof e[k]==="number"?e[k]:null).filter(v=>v!==null);
      const total=n.reduce((a,b)=>a+b,0);
      return[`✋ <b>stop blocked</b> — ${n.length?total+" plan item(s)":"plan items"} unaccounted`,"--warn",true];
    },
    review:e=>[`${e.verdict==="pass"?"✅":"❌"} <b>review ${esc(e.verdict||"")}</b> — ${esc(e.task||"")}${e.notes?": "+esc(e.notes):""}`,e.verdict==="pass"?"--good":"--bad",e.verdict!=="pass"],
    subagent_stop:e=>{const p=persona(e.__owner||e.agent_type);return[`${bot(p)} <b>${p.name}</b> finished — background run complete`,p.v,false]},
    /* KEEL ADDITION (T137): the harness's OWN background runs, which are not
       agents and get no bench seat: one added property on this table, nothing
       above it deleted or reworded, and no new element on the page. The row
       says "launched" and stops there - keel receives no hook when a
       background command ends (measured; see hooks/keel_capture.py), so a
       word like "running" or "done" here would be a claim the record cannot
       back. The timestamp beside it is the launch's own, and "last seen" is
       exactly what it means. */
    background_task:e=>[`▶ <b>background ${esc(e.tool||"run")}</b> launched — ${esc(e.detail||"")}${e.task_id?" · task "+esc(e.task_id):""} · <span style="color:var(--ink3)">no end signal reaches keel</span>`,"--generic",false],
  };
  // sort by real timestamp: hook events are local-time, orchestrator-written
  // reviews are UTC ("...Z") - file order alone is not authoritative
  const rows=events.filter(e=>e.event!=="activity").slice().sort((a,b)=>ts(a)-ts(b));
  $("feed").innerHTML=rows.slice(-40).reverse().map(e=>{
    const [html,v,alert]=(verbs[e.event]||(x=>[esc(x.event),"--generic",false]))(e);
    return `<div class="ev${alert?" alert":""}" style="border-left-color:color-mix(in srgb, var(${v}) 70%, transparent)">
      <span class="t">${rel(e.ts)}</span><span>${html}</span></div>`;}).join("");
  // KEEL ADDITION (T132): a resume's feed line says so - re-slicing the
  // SAME already-filtered `rows` (not a re-filtered copy of `events`) keeps
  // this aligned with the DOM just rendered above even when T122's
  // kind-filter has hidden rows.
  rows.slice(-40).reverse().forEach((e,i)=>{
    if(e.handoff_kind!=="resume")return;
    const el=$("feed").children[i]; if(!el)return;
    el.innerHTML=el.innerHTML.replace(" launched — "," resumed — ").replace(" reported back — "," resumed — ");
  });
}

// ---- proactive alerts: diff state between ticks --------------------------
let prev=null;
function alertDiffs(events,rows){
  const counts={gate_block:0,stop_block:0,review_fail:0,reviews:0};
  let lastReview=null;
  for(const e of events){
    if(e.event==="gate_block")counts.gate_block++;
    else if(e.event==="stop_block")counts.stop_block++;
    else if(e.event==="review"){counts.reviews++;lastReview=e;if(e.verdict!=="pass")counts.review_fail++;}
  }
  const done=rows.filter(r=>r[1]==="x").length;
  const blocked=rows.filter(r=>r[1]==="!").length;
  const decisions=rows.filter(r=>r[1]==="?").length;
  if(prev){
    if(counts.reviews>prev.counts.reviews&&lastReview){
      // judgment flash on Maestro when a review lands
      const c=nodeEls.get("__center");
      if(c){const cls=lastReview.verdict==="pass"?"judge-pass":"judge-fail";
        c.classList.remove("judge-pass","judge-fail");void c.offsetWidth;
        c.classList.add(cls);setTimeout(()=>c.classList.remove(cls),2400);}
    }
    if(counts.gate_block>prev.counts.gate_block)notify("🛡️ Guardrail fired","A gate blocked an action — see the event feed.");
    if(counts.stop_block>prev.counts.stop_block)notify("✋ Stop blocked","Orchestrator tried to end with unaccounted plan items.");
    if(counts.review_fail>prev.counts.review_fail)notify("❌ Review failed","A task failed review — escalation should follow.");
    if(blocked>prev.blocked)notify("⛔ Task blocked","A plan item was marked blocked — your call may be needed.");
    if(decisions>prev.decisions)notify("❓ Decision needed","A plan item is waiting on your decision.");
    if(rows.length>0&&done===rows.length&&prev.done<prev.rows)notify("🏁 Plan complete","All plan items are done.");
  }
  prev={counts,done,blocked,decisions,rows:rows.length};
}

// ---- session switcher (active sessions first, ended rounds below) --------
function truncateLabel(s,n){return s.length>n?s.slice(0,n).trimEnd()+"…":s;}
function planSubject(text){
  if(!text)return "";
  let m=text.match(/^#\s+(.+)$/m);
  if(m)return truncateLabel(m[1].trim(),40);
  m=text.match(/^\s*[-*] \[[ x!?]\] *(.+)$/m);
  if(m)return truncateLabel(m[1].split(/\s*\|\s*AC:\s*/)[0].trim(),40);
  return "";
}
function fetchSubject(name){
  return fetch("/api/plan?name="+encodeURIComponent(name)).then(r=>r.ok?r.text():"")
    .then(planSubject).catch(()=>"");
}
function workingCountFor(sessId){
  return lastAgents.filter(a=>{const e=a.start||a.end;return e&&e.session_id===sessId&&a.working;}).length;
}
// KEEL ADDITION (T311): round labels, adopted from the advisor reference's
// own numbering (its "Current · round N" / "Round i · date · n ev" pair) -
// ``idx`` is the round's 0-based position in ``rounds``, which is ordered
// by FIRST-EVENT timestamp across the whole log (see ``tick()``'s
// ``firstSeen`` walk), so "Round 1" always names the earliest session this
// log has observed and the numbering cannot reorder as sessions end. ``n``
// is the same SIGNAL-event count ``tick()`` already computes for the
// "hide activity-less rounds" filter - one count, two uses. The session
// short id is KEPT on the second line rather than dropped: keel runs
// parallel sessions the advisor's single-session board never had to,  and
// a label naming only a round number could no longer tell two live
// sessions apart.
function roundDate(t){
  return new Date(t).toLocaleString(undefined,{month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"});
}
// two-line entry text for one session: [primary = round label, secondary =
// sess8 (+ subject/counts) dimmed underneath] - a native <option> cannot
// render two lines, so the list below is a custom div-based dropdown.
function sessLines(r,idx,n){
  const sess8=(r.id||"").slice(0,8);
  const subj=subjectCache.get(r.id)||"";
  const wc=workingCountFor(r.id);
  const primary=`Round ${idx+1} · ${roundDate(r.t)} · ${n} ev`;
  const secondary=sess8+(subj?" · "+subj:"")+" · "+wc+" working";
  return [primary,secondary];
}
// the live sentinel's own two lines: "Current · round N" (N = every round
// this log has observed, not merely the ones shown) with the session it is
// currently auto-tracking named underneath, so identity never vanishes
// behind the word "Current".
function liveLines(rounds){
  const primary="Current · round "+Math.max(rounds.length,1);
  const cur=rounds.find(r=>r.id===latestSession);
  if(!cur)return [primary,""];
  const sess8=(cur.id||"").slice(0,8);
  const subj=subjectCache.get(cur.id)||"";
  const wc=workingCountFor(cur.id);
  const secondary=sess8+(subj?" · "+subj:"")+" · "+wc+" working";
  return [primary,secondary];
}
function sessOptionHtml(value,line1,line2,selected){
  return `<div class="ddopt${selected?" sel":""}" data-value="${esc(value)}" role="option" aria-selected="${selected?"true":"false"}">`+
    `<span class="l1">${esc(line1)}</span><span class="l2">${esc(line2)}</span></div>`;
}
let sessOpen=false;
function closeSessDD(){sessOpen=false;$("sesslist").hidden=true;$("sessbtn").setAttribute("aria-expanded","false");}
function openSessDD(){sessOpen=true;$("sesslist").hidden=false;$("sessbtn").setAttribute("aria-expanded","true");}
$("sessbtn").onclick=()=>{sessOpen?closeSessDD():openSessDD();};
$("sesslist").addEventListener("click",ev=>{
  const opt=ev.target.closest(".ddopt");
  if(!opt)return;
  selectedRound=opt.dataset.value;
  edgeSig="";
  nodeEls.forEach((el,k)=>{if(k!=="__center"){el.remove();nodeEls.delete(k);}});
  lastRoundHtml="";  // force the list + button label to refresh selection
  closeSessDD();
  tick();
});
document.addEventListener("click",ev=>{
  if(!sessOpen)return;
  if(ev.target.closest("#sessdd"))return;
  closeSessDD();
});
document.addEventListener("keydown",ev=>{if(ev.key==="Escape"&&sessOpen)closeSessDD();});
function updateRoundSel(rounds,counts){
  const cur=selectedRound,now=Date.now();
  // KEEL ADDITION (T311): round index is this session's 0-based position in
  // ``rounds`` itself - first-seen order across the WHOLE log - not its
  // position within the active/ended split below, so a round's number
  // cannot change as it moves from "active" to "ended".
  const idxById=new Map(rounds.map((r,i)=>[r.id,i]));
  const active=[],ended=[];
  for(const r of rounds){
    const endedFlag=sessionEnded.has(r.id);
    const lastSeen=lastSeenBySession.get(r.id)||r.t;
    const rec={...r,lastSeen,endedFlag};
    (!endedFlag&&(now-lastSeen)<ACTIVE_WINDOW_MS?active:ended).push(rec);
  }
  active.sort((a,b)=>b.lastSeen-a.lastSeen);
  ended.sort((a,b)=>b.lastSeen-a.lastSeen);
  // fire-and-forget subject fetches; the label fills in over the next tick(s)
  for(const r of active){
    const name="plan-"+(r.id||"").slice(0,8)+".md";
    if(lastArchives.includes(name))fetchSubject(name).then(s=>subjectCache.set(r.id,s));
  }
  for(const r of ended){
    if(subjectCache.has(r.id))continue;
    const name="plan-"+(r.id||"").slice(0,8)+".md";
    if(lastArchives.includes(name))fetchSubject(name).then(s=>subjectCache.set(r.id,s));
  }
  const endedShown=ended.filter(r=>(counts.get(r.id)||0)>0); // hide activity-less rounds (resume duplicates)
  const [liveL1,liveL2]=liveLines(rounds);
  let html=`<div class="ddgrouplabel">Active sessions</div>`+
    sessOptionHtml("live",liveL1,liveL2,cur==="live");
  for(const r of active){
    const[l1,l2]=sessLines(r,idxById.get(r.id)||0,counts.get(r.id)||0);
    html+=sessOptionHtml(r.id,l1,l2,cur===r.id);
  }
  if(endedShown.length){
    html+=`<div class="ddgrouplabel">Ended / past rounds</div>`;
    for(const r of endedShown){
      const[l1,l2]=sessLines(r,idxById.get(r.id)||0,counts.get(r.id)||0);
      html+=sessOptionHtml(r.id,l1,l2,cur===r.id);
    }
  }
  const known=new Set(["live",...active.map(r=>r.id),...endedShown.map(r=>r.id)]);
  if(!known.has(cur)){selectedRound="live";}
  if(html!==lastRoundHtml){lastRoundHtml=html;$("sesslist").innerHTML=html;}
  const found=[...active,...endedShown].find(r=>r.id===selectedRound);
  if(selectedRound==="live"||!found){
    $("sessbtn-line1").textContent=liveL1;$("sessbtn-line2").textContent=liveL2;
  }else{
    const[l1,l2]=sessLines(found,idxById.get(found.id)||0,counts.get(found.id)||0);
    $("sessbtn-line1").textContent=l1;$("sessbtn-line2").textContent=l2;
  }
}
function renderProjectSel(project,sibs){
  // T316: the tab names the project this instance serves (siblings open
  // their own dashboards on their own ports, each stamping its own name).
  const wanted=(project?project+" ":"")+"Orchestration — live";
  if(document.title!==wanted)document.title=wanted;
  const el=$("projectsel");if(!el)return;
  let html=`<option value="" selected>${esc(project||"—")}</option>`;
  for(const s of(sibs||[])){
    html+=`<option value="${s.port}">${esc(s.path.split(/[\\/]/).pop()||s.path)}</option>`;
  }
  if(el.dataset.html!==html){el.innerHTML=html;el.dataset.html=html;el.value="";}
}
$("projectsel").onchange=e=>{
  const v=e.target.value;
  if(v)window.location.href="http://127.0.0.1:"+v+"/";
  else e.target.value="";
};

function stampTs(name){ // plan-YYYYmmdd-HHMMSS.md -> epoch ms
  const m=name.match(/^plan-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})\.md$/);
  return m?new Date(+m[1],+m[2]-1,+m[3],+m[4],+m[5],+m[6]).getTime():0;
}
function renderArchivedLedger(rIdx,rounds){
  // the archive whose snapshot stamp (= plan mtime) falls inside the round
  const t0=rounds[rIdx]?rounds[rIdx].t:0;
  const t1=rounds[rIdx+1]?rounds[rIdx+1].t:Infinity;
  let best=null;
  for(const n of lastArchives){const t=stampTs(n);if(t>=t0&&t<t1&&(!best||t>stampTs(best)))best=n;}
  if(!best){renderLedger("");return;}
  if(planCache.has(best)){renderLedger(planCache.get(best));return;}
  fetch("/api/plan?name="+encodeURIComponent(best)).then(r=>r.ok?r.text():"")
    .then(txt=>{planCache.set(best,txt);if(selectedRound!=="live")renderLedger(txt);});
}

/* KEEL ADDITION (T156, owner-ruled 2026-08-16 — unparks resume-persona
   inheritance; see .keel/decisions/2026-08-16-resume-persona-join-unparked.md).

   A resume is a message to an agent that already exists, so it fires the
   hand-off pair with NO type: there is no launch tool call to read one from.
   The id is carried though, and the original launch's `handoff_end` carries
   that same id together with the real type - so the persona is recoverable
   by a JOIN rather than by a guess.

   ONE PASS, AT INGEST, so every reader downstream - ring, bench, feed,
   drawer - sees the same answer without a change at any call site. Two rules
   it may not break:

   1. AN UNRESOLVED JOIN CHANGES NOTHING. No inference from timing, session,
      ordering or plausibility; a run whose id resolves to nothing stays
      generic, and agents launched before ids were recorded stay generic
      permanently. A card that admits it does not know is worth more than one
      that is usually right.
   2. A JOINED TYPE IS MARKED (`__joined`), because a derived type must never
      be indistinguishable from one the record actually carried. */
function joinResumePersonas(events){
  const byAgent=new Map();
  for(const e of events||[]){
    const t=e.subagent_type||e.agent_type;
    if(e.agent_id&&t&&!byAgent.has(e.agent_id))byAgent.set(e.agent_id,t);
  }
  let joined=0;
  for(const e of events||[]){
    if(!e.agent_id)continue;
    const t=byAgent.get(e.agent_id);
    if(!t)continue;
    if(!e.subagent_type&&("subagent_type" in e)){e.subagent_type=t;e.__joined=true;joined++;}
    else if(!e.agent_type&&("agent_type" in e)){e.agent_type=t;e.__joined=true;joined++;}
  }
  return joined;
}

let lastState=null;
async function tick(){
  try{
    const st=await(await fetch("/api/state")).json();
    joinResumePersonas(st.events);
    lastState=st;
    lastActs=st.events.filter(e=>e.event==="activity");
    lastStops=st.events.filter(e=>e.event==="subagent_stop");
    lastReviews=st.events.filter(e=>e.event==="review");
    lastArchives=st.plan_archives||[];
    // rounds = every session OBSERVED in the log, by first appearance.
    // A session_start is not guaranteed: resumed/compacted sessions can
    // rotate to a fresh session_id without ever firing SessionStart, and
    // their agents must still show up.
    const firstSeen=new Map();
    sessionEnded=new Set();lastSeenBySession=new Map();
    for(const e of st.events){
      if(!e.session_id)continue;
      if(!firstSeen.has(e.session_id))firstSeen.set(e.session_id,ts(e));
      if(e.event==="session_end")sessionEnded.add(e.session_id);
      const t=ts(e);
      if(!lastSeenBySession.has(e.session_id)||t>lastSeenBySession.get(e.session_id))lastSeenBySession.set(e.session_id,t);
    }
    const rounds=[...firstSeen.entries()].map(([id,t])=>({id,t})).sort((a,b)=>a.t-b.t);
    lastSessionStarts=rounds.map(r=>r.t);  // winIdx boundaries follow observed sessions
    for(let i=st.events.length-1;i>=0;i--){if(st.events[i].session_id){latestSession=st.events[i].session_id;break;}}
    const agents=pairEvents(st.events);
    lastAgents=agents;
    computeStates(agents);

    const live=selectedRound==="live";
    // "live" auto-tracks the most-recently-active session (default / single-
    // session behavior); any other value is a session_id PINNED by the user
    // and stays selected regardless of which session is newest.
    let rIdx=live?rounds.findIndex(r=>r.id===latestSession):rounds.findIndex(r=>r.id===selectedRound);
    if(rIdx<0||rIdx>=rounds.length)rIdx=Math.max(0,rounds.length-1);
    const SIGNAL=new Set(["handoff_start","handoff_end","handoff","review","gate_block","stop_block","subagent_stop"]);
    const counts=new Map();
    for(const e of st.events){
      if(!e.session_id||!SIGNAL.has(e.event))continue;
      counts.set(e.session_id,(counts.get(e.session_id)||0)+1);
    }
    updateRoundSel(rounds,counts);
    renderProjectSel(st.project,st.siblings);
    // history = the PINNED session has genuinely ended (session_end event,
    // or aged out of the active window) - not merely "not the live sentinel",
    // since a pinned ACTIVE session must keep live-updating.
    const pinnedId=live?null:selectedRound;
    const selEnded=!!pinnedId&&(sessionEnded.has(pinnedId)||(Date.now()-(lastSeenBySession.get(pinnedId)||0))>=ACTIVE_WINDOW_MS);
    const isLiveish=!selEnded;
    document.body.classList.toggle("history",selEnded);

    // a new round (or a switch) resets every number and clears stale cards
    const roundKey=(live?"live":"hist")+"|"+(rounds[rIdx]?rounds[rIdx].id:"none");
    if(roundKey!==lastRoundKey){
      lastRoundKey=roundKey;
      edgeSig="";
      nodeEls.forEach((el,k)=>{if(k!=="__center"){el.remove();nodeEls.delete(k);}});
      prev=null;              // fresh alert baseline - no burst on round change
      $("s-active").textContent="0";$("s-handoffs").textContent="0";$("s-gates").textContent="0";
    }

    // the view: this round's events and agents only. Rounds are keyed by
    // SESSION ID, not time-window - two Claude sessions running in
    // parallel interleave in time but never share a session_id. Events
    // without one (orchestrator-written reviews) fall back to the
    // time-window, which is right when sessions are sequential.
    const rid=rounds[rIdx]?rounds[rIdx].id:null;
    const inRound=e=>(rid&&e.session_id)?e.session_id===rid:winIdx(ts(e))===rIdx;
    const evView=rounds.length?st.events.filter(inRound):st.events;
    const agView=rounds.length?agents.filter(a=>{const e=a.start||a.end;return e&&inRound(e);}):agents;

    const anyWorking=layout(agView,evView);
    // per-session plans: each round's ledger is its own plan file
    const spName=rounds[rIdx]?"plan-"+(rounds[rIdx].id||"").slice(0,8)+".md":null;
    const hasSp=!!(spName&&lastArchives.includes(spName));
    let planText=null;
    if(hasSp){
      if(isLiveish||!planCache.has(spName)){
        try{const r=await fetch("/api/plan?name="+encodeURIComponent(spName));
            planText=r.ok?await r.text():"";}catch(_){planText="";}
        if(!isLiveish)planCache.set(spName,planText);
      }else planText=planCache.get(spName);
    }
    if(isLiveish){
      const rows=renderLedger(planText!==null&&planText!==""?planText:st.plan);
      alertDiffs(st.events,rows);
    }else{
      if(planText!==null&&planText!=="")renderLedger(planText);
      else renderArchivedLedger(rIdx,rounds);
    }
    renderFeed(evView);
    renderMaestro();
    // the orchestrator counts as a working agent while it works itself
    $("s-active").textContent=agView.filter(a=>a.working).length+((live&&maestroActive)?1:0);
    $("s-handoffs").textContent=agView.length;
    $("s-gates").textContent=evView.filter(e=>e.event==="gate_block"||e.event==="stop_block").length;
    const fresh=st.log_mtime&&(st.now-st.log_mtime)<20;
    $("livedot").className=(fresh||anyWorking)?"on":"";
    $("livetxt").textContent=(fresh||anyWorking)?"live":"idle";
  }catch(e){$("livetxt").textContent="disconnected";$("livedot").className="";}
}
// ---- KEEL ADDITION (T335, owner review of the live drawer 2026-08-26) ----
// WHAT THE RUN RAN AT, read from the whole run rather than from one half of
// it. MEASURED on this project's log (2026-08-26): 169 of 439 ``handoff_start``
// lines carry ``model``, and the CLOSE half carries the richer value - the
// launch tool's own ``resolvedModel`` ("claude-sonnet-5" against the open
// half's "sonnet"). The drawer read ``modelOf(a.start||a.end)``, so a run
// whose open half recorded nothing fell through that function's persona map
// to the literal "agent" - a word the record never said, printed beside a
// card whose own pill showed the real model from the other half. So: prefer
// the close half (the harness's resolved answer), then the open half, then
// the stop signal, and when NO half carries one say so. ``modelOf`` itself is
// untouched - the vendored card pill still uses it - and nothing here invents
// a model from a persona.
function ownField(a,key){
  for(const e of[a&&a.end,a&&a.start,a&&a.stop]){
    if(e&&typeof e[key]==="string"&&e[key].trim())return e[key];
  }
  return null;
}
/* ---- KEEL ADDITION (T337 extension, owner review of the live drawer
   2026-08-26): A RESUME RUN INHERITS THE ROUTE OF THE DISPATCH IT RESUMES.
   MEASURED on this project's log: a resume hand-off records ``model`` and
   ``effort`` as null on BOTH halves, and ``hooks/keel_capture.py``'s own
   contract says why - "THE SEND KNOWS NONE OF THEM: it names an id, not a
   type, and it carries no model and no effort parameter", and copying them
   at capture time would be an inference recorded as a fact. So the JOIN
   happens HERE, on the read side, where it is visibly a join: the newest
   EARLIER run of the SAME AGENT that did record the field lends its value,
   and the drawer says the value was borrowed ("from launch").
   THE SAME AGENT, by the strongest key the two runs share:
     * ``agent_id`` when both carry one - a resume carries its target's own
       id on both halves (T124), so this is the same agent INSTANCE, not
       merely the same persona;
     * else session_id + subagent_type, the very key ``actsFor`` and the chip
       rail already attribute by (and the type itself may have arrived
       through T156's ingest join, which is marked ``__joined`` there).
   NEVER LATER, never across agents, never invented: only a run that started
   at or before this one can lend, model and effort are taken
   INDEPENDENTLY (whichever is present), and when no run of this agent
   anywhere in scope recorded a field the answer stays null - which the
   drawer prints as "unrecorded", exactly as before. */
function inheritedField(a,agents,key){
  if(!a||!a.start)return null;
  const t0=ts(a.start);
  const id=a.start.agent_id||(a.end&&a.end.agent_id)||null;
  const sess=a.start.session_id,type=a.start.subagent_type;
  let best=null,bestTs=-Infinity;
  for(const c of(agents||[])){
    if(c===a||!c.start)continue;
    const ct=ts(c.start);
    if(ct>t0)continue;
    const cid=c.start.agent_id||(c.end&&c.end.agent_id)||null;
    const sameAgent=(id&&cid)?(cid===id)
      :(!!type&&c.start.session_id===sess&&c.start.subagent_type===type);
    if(!sameAgent)continue;
    const v=ownField(c,key);
    if(v&&ct>bestTs){best=v;bestTs=ct;}
  }
  return best;
}
// The route a run ran at: what its OWN halves recorded, then what the agent's
// own earlier dispatch recorded, per field. ``inherited`` is true only when a
// value really was borrowed, so the drawer can say so rather than implying
// this run carried it.
function runRoute(a,agents){
  const model=ownField(a,"model"),effort=ownField(a,"effort");
  const im=model?null:inheritedField(a,agents,"model");
  const ie=effort?null:inheritedField(a,agents,"effort");
  return{model:model||im,effort:effort||ie,inherited:!!(im||ie)};
}
// One display word for a route. The SERVED copy already composes
// "model · effort" into ``model`` where the same event carried both (T123),
// so effort is appended only when the model string is not already wearing
// it - a pill must never read "opus · high · high".
function routeLabel(r){
  if(!r)return null;
  let s=r.model||"";
  if(r.effort&&!(s&&s.toLowerCase().endsWith(" · "+r.effort.toLowerCase())))
    s=s?s+" · "+r.effort:r.effort;
  return s||null;
}
function runModel(a,agents){
  return routeLabel(runRoute(a,agents))||null;
}
// WHAT THE DURATION MEASURES, said out loud. The owner saw "3s" on a run
// whose card said 31s: for a BACKGROUND launch the close half is only the
// launch acknowledgment, so end-minus-start is the time the harness took to
// accept the delegation, not the time the agent worked - and for a RESUME
// pair (T124) it is the round-trip of one message to an agent that already
// existed. Both are honest numbers with dishonest labels, so each answer now
// carries the span it actually measured.
function runDuration(a){
  if(!a||!a.start)return["?","no launch recorded for this run"];
  const resumed=(a.start&&a.start.handoff_kind==="resume")||(a.end&&a.end.handoff_kind==="resume");
  if(resumed&&a.end)return[fmtDur(ts(a.end)-ts(a.start)),"resume message round-trip"];
  if(a.stop)return[fmtDur(ts(a.stop)-ts(a.start)),"launch to report-back"];
  if(a.working)return[fmtDur(Date.now()-ts(a.start))+" (running)","since launch"];
  if(a.end&&a.background)return[fmtDur(ts(a.end)-ts(a.start)),"launch to background acknowledgment"];
  if(a.end)return[fmtDur(ts(a.end)-ts(a.start)),"launch to report-back"];
  return[fmtDur(Date.now()-ts(a.start))+" (running)","since launch"];
}
// ---- per-agent drawer ----------------------------------------------------
function openDrawer(a){
  const e=a.start||a.end,p=persona(e.subagent_type);
  const dr=$("drawer");
  dr.querySelector(".face").innerHTML=robotSVG(p.v,p.kind);
  dr.querySelector(".who").textContent=p.name+" — "+preview(e.description||"");
  // KEEL ADDITION (T335): model from the whole run (``runModel``), and an
  // honest word where the record carries none - never the generic "agent".
  // KEEL ADDITION (T337 extension): the route, borrowed from this agent's own
  // dispatch when the shown run recorded none - and SAID to be borrowed.
  const route=runRoute(a,lastAgents),m=routeLabel(route),dur=runDuration(a);
  const from=(m&&route.inherited)?` <span style="color:var(--ink3)">· from launch</span>`:"";
  dr.querySelector(".dmeta").innerHTML=
    `model: ${m?`<b>${esc(m)}</b>${from}`:`<b style="color:var(--ink3)">unrecorded</b>`} · `+
    `duration: <b>${esc(dur[0])}</b> <span style="color:var(--ink3)">(${esc(dur[1])})</span>`+
    (e.prompt_head?`<br><span style="color:var(--ink3)">${esc(e.prompt_head)}…</span>`:"");
  /* KEEL ADDITION (T335): THE WHOLE BRIEF, READABLE. The header line above
     keeps its one-line preview (T312's client bound - a title must stay a
     title), and the task itself is printed here in full, wrapped, inside the
     drawer body that already scrolls. "In full" means the whole of what the
     server sent, which is bounded once at ``DESCRIPTION_PREVIEW_CHARS``
     (raised to 2000 by T335) - the page never reconstructs anything the
     bound removed, and an ellipsis reaching this element is the record's own
     served truth rather than a second, quieter cut made here. */
  const dtask=dr.querySelector(".dtask"),desc=(e.description||"").toString();
  if(dtask){
    dtask.innerHTML=desc?`<span class="dlabel">task</span>${esc(desc)}`:"";
    dtask.hidden=!desc;
  }
  const acts=actsFor(a);
  $("dracts").innerHTML=acts.length?acts.map(ev=>
    `<div class="arow"><span class="t">${(ev.ts||"").slice(11)}</span>
     <span class="d">${toolIcon(ev.tool)} ${esc(ev.detail||ev.tool)}</span></div>`).reverse().join("")
   :`<div class="arow"><span class="d" style="color:var(--ink3)">no recorded actions — activity logging starts with sessions launched after it was installed</span></div>`;
  dr.classList.add("open");
}
function openMaestroDrawer(){
  const p=PERSONAS.orchestrator,dr=$("drawer");
  dr.querySelector(".face").innerHTML=robotSVG(p.v,p.kind);
  // KEEL ADDITION (T155): DERIVED, not written out. This line carried the
  // vendored persona's name as a literal, so keel's rename reached the card
  // and never the flyout - a residue no name scan could catch, because the
  // string it should have matched was only ever built at render time.
  dr.querySelector(".who").textContent=`${p.name} — orchestrator`;
  // KEEL ADDITION (T335): the Captain has no delegation brief of its own -
  // the task block belongs to a run, so it is emptied rather than left
  // showing the last agent the reader opened.
  const dtask=dr.querySelector(".dtask");
  if(dtask){dtask.innerHTML="";dtask.hidden=true;}
  const evs=(lastState&&lastState.events)||[];
  const mine=e=>e.session_id===latestSession;
  const nHand=evs.filter(e=>e.event==="handoff_start"&&mine(e)).length;
  const nRev=evs.filter(e=>e.event==="review"&&winIdx(ts(e))===winIdx(Date.now())).length;
  const nGate=evs.filter(e=>(e.event==="gate_block"||e.event==="stop_block")&&mine(e)).length;
  // KEEL ADDITION (T335, owner extension 2026-08-26): the orchestrator's own
  // model, on the same honesty rule the agent drawer follows - the recorded
  // value or the word "unrecorded", never a guess and never "agent".
  const om=sessionModel(latestSession);
  dr.querySelector(".dmeta").innerHTML=
    `model: ${om?`<b>${esc(om)}</b>`:`<b style="color:var(--ink3)">unrecorded</b>`}<br>`+
    `current session: <b>${nHand}</b> hand-offs · <b>${nRev}</b> reviews · <b>${nGate}</b> gate blocks<br>`+
    `<span style="color:var(--ink3)">state: ${esc(maestroMode()[0])}</span>`;
  const acts=maestroActs();
  $("dracts").innerHTML=acts.length?acts.map(ev=>
    `<div class="arow"><span class="t">${(ev.ts||"").slice(11)}</span>
     <span class="d">${toolIcon(ev.tool)} ${esc(ev.detail||ev.tool)}</span></div>`).reverse().join("")
   :`<div class="arow"><span class="d" style="color:var(--ink3)">no orchestrator actions recorded this session</span></div>`;
  dr.classList.add("open");
}
$("nodes").addEventListener("click",ev=>{
  const el=ev.target.closest(".node");
  if(!el)return;
  if(el.classList.contains("center")){openMaestroDrawer();return;}
  const a=lastAgents.find(x=>x.uid===el.dataset.uid);
  if(a)openDrawer(a);
});
const closeDrawer=()=>$("drawer").classList.remove("open");
document.querySelector("#drawer .close").onclick=closeDrawer;
document.addEventListener("click",ev=>{
  const dr=$("drawer");
  if(!dr.classList.contains("open"))return;
  if(dr.contains(ev.target))return;                        // inside the flyout
  if(ev.target.closest(".node")||ev.target.closest(".bpill"))return; // openers
  closeDrawer();
});
document.addEventListener("keydown",ev=>{if(ev.key==="Escape")closeDrawer();});
$("bench").addEventListener("click",ev=>{
  const pill=ev.target.closest(".bpill");
  if(!pill)return;
  const type=pill.dataset.type;
  /* KEEL ADDITION (T335, owner review 2026-08-26): open the run a reader
     MEANS by that pill. The plain "newest of this type" pick handed back
     whatever line came last, which for a resumed agent is the resume pair -
     a 3-second round-trip with no model recorded on either half - while the
     agent's own card on the ring showed a 31-second run at OPUS · HIGH. Two
     different runs, one persona, and nothing on screen saying so. Preference
     now: the newest run of this type still WORKING, else the newest real
     launch (a run whose open half carries the brief it was launched with),
     else the newest line of any kind - so a bench pill opens the run the
     board is actually showing. */
  const runs=lastAgents.filter(x=>(((x.start||x.end||{}).subagent_type)||"agent")===type);
  const back=[...runs].reverse();
  const a=back.find(x=>x.working)||back.find(x=>x.start&&x.start.description)||back[0];
  if(a)openDrawer(a);
});

tick();setInterval(tick,1500);
setInterval(()=>{ // 1s elapsed ticker for working chips, no full redraw
  for(const[,el]of nodeEls){
    if(el.classList.contains("working")&&el.dataset.start){
      const chip=el.querySelector(".chip");
      if(chip)chip.textContent=chipText(el);
    }
  }
},1000);
addEventListener("resize",()=>{edgeSig="";if(lastState)tick();});
/* ---- KEEL ADDITION (T122) ---------------------------------------------
   Three additive seats, nothing of the page's own removed or rewritten:
   1. #keelarming / #keelsess render the /api/state "keel" block - the
      server computed both with keel's own single implementations, so this
      block only PRINTS; it derives nothing client-side.
   2. renderFeed is INTERCEPTED (the declaration's binding is reassigned),
      never edited: rows whose kind the reader hid are filtered before the
      page's own renderer runs. Hiding is per-page-load, deliberately - a
      filter is a reading aid, not a record.
   3. One 1.5s repaint keeps chips and badges current from lastState; it
      writes textContent/innerHTML on its own elements only. */
(function(){
  const HIDDEN=new Set();
  const _renderFeed=renderFeed;
  renderFeed=evs=>_renderFeed(evs.filter(e=>!HIDDEN.has(e.event)));
  /* KEEL ADDITION (T340): the per-process token the server embedded when it
     served this page - a JS const, never read from anywhere the page could
     be tricked into re-reading (no query string, no cookie). One page load,
     one token; a reload after a real restart gets the NEW process's token. */
  const KEEL_RESTART_TOKEN="__KEEL_RESTART_TOKEN__";  // keel-leak: ignore - placeholder substituted per process at serve time
  let restartBusy=false;
  async function doRestart(){
    const btn=$("keelrestart"),code=$("keelcode");
    restartBusy=true;
    btn.disabled=true;btn.textContent="restarting…";btn.hidden=false;
    let res;
    try{
      res=await fetch("/api/restart",{method:"POST",headers:{"X-Keel-Restart":KEEL_RESTART_TOKEN}});
    }catch(e){
      restartBusy=false;btn.disabled=false;btn.textContent="restart board";
      return;
    }
    if(!res.ok){
      restartBusy=false;btn.disabled=false;btn.textContent="restart board";
      code.textContent="restart refused ("+res.status+")";code.style.color="var(--bad)";
      return;
    }
    /* The request that authorized the restart is answered; now poll until a
       NEW process is serving fresh code (``!st.keel.code.stale``), which is
       true only once the re-exec'd process has actually taken over - the
       old, stale process would keep answering "stale" for as long as it
       lives. A sensible window, not an infinite spin: after it, say so. */
    const deadline=Date.now()+20000;
    const poll=async()=>{
      if(Date.now()>deadline){
        restartBusy=false;btn.disabled=false;btn.textContent="restart board";
        code.textContent="board did not come back — reload manually";
        code.style.color="var(--bad)";
        return;
      }
      try{
        const st=await(await fetch("/api/state",{cache:"no-store"})).json();
        if(st&&st.keel&&st.keel.code&&!st.keel.code.stale){
          location.reload();
          return;
        }
      }catch(e){/* still down between the old process closing and the new one binding */}
      setTimeout(poll,700);
    };
    setTimeout(poll,700);
  }
  $("keelrestart").addEventListener("click",doRestart);
  function keelPaint(){
    const st=lastState; if(!st||!st.keel)return;
    const arm=$("keelarming"),sp=$("keelsess");
    const a=st.keel.arming;
    if(a&&a.tier!==null&&a.tier!==undefined){
      arm.hidden=false;
      arm.textContent="tier "+a.tier+(a.armed?" · ARMED":" · observing");
      arm.title=a.note||"keel arming, read from this project's policy";
    }else if(a){arm.hidden=false;arm.textContent="arming unreadable";arm.title=a.note||"";}
    const lv=st.keel.liveness;
    if(lv){
      sp.hidden=false;
      sp.textContent="session: "+lv.label;
      sp.title=lv.note||"";
      sp.style.color=lv.state==="live"?"var(--good)":"var(--ink2)";
    }
    /* KEEL ADDITION (T168): the stale-board marker. The server compared the
       fingerprints (served_code); this only PRINTS the verdict it was handed,
       exactly as the arming chip above does. An unknown answer says unknown -
       it is never drawn as "current". */
    /* KEEL ADDITION (T338, owner review 2026-08-26): the chip answers the
       READER's question. It used to read "page current · 1d778b9ecd2a" - a
       digest, which tells a machine which bytes are running and tells a
       person nothing. Same three states, same verdict, same source (the
       server's ``cd``; nothing is compared here): what changed is that each
       state now names its own TIME, humanised by the page's own ``rel()``,
       the same relative-time voice the cards and the feed already speak.
       The digests are not lost - both of them move into the chip's title,
       where a reader who wants the machine answer can hover for it. Where no
       mtime could be taken the time is simply absent: the sentence still
       reads, and no reader is told "now" because a stat() failed. */
    const codeAge=cd=>cd&&typeof cd.page_mtime==="number"
      ?rel(new Date(cd.page_mtime*1000).toISOString()):null;
    const codeFps=cd=>"served page "+(cd.page_fp||"?")+" / components "+(cd.components_fp||"?")
      +"; on disk now page "+(cd.page_fp_disk||"?")+" / components "+(cd.components_fp_disk||"?");
    const code=$("keelcode"),cd=st.keel.code;
    /* KEEL ADDITION (T340): the restart control - shown ONLY in the stale
       branch below. ``restartBusy`` guards against the 1.5s repaint
       clobbering the in-progress button while a click is being handled. */
    const restartBtn=$("keelrestart");
    if(cd){
      code.hidden=false;
      const age=codeAge(cd);
      if(cd.stale){
        code.textContent="code changed on disk"+(age?" "+age:"")+" — restart the board";
        code.style.color="var(--bad)";
        code.title=codeFps(cd);
        if(!restartBusy)restartBtn.hidden=false;
      }else if(cd.unknown){
        code.textContent="code freshness unknown";
        code.style.color="var(--warn)";
        code.title="a fingerprint could not be taken, so this board is reported neither current nor stale";
        if(!restartBusy)restartBtn.hidden=true;
      }else{
        code.textContent="code current"+(age?" · updated "+age:"");
        code.style.color="var(--ink2)";
        code.title="this board is serving the code on disk ("+codeFps(cd)+")";
        if(!restartBusy)restartBtn.hidden=true;
      }
    }
    const counts=new Map();
    for(const e of st.events){if(e.event==="activity")continue;counts.set(e.event,(counts.get(e.event)||0)+1);}
    const bar=$("keelfilters");
    bar.hidden=counts.size===0;
    const html=[...counts.entries()].sort((x,y)=>y[1]-x[1]).map(([k,n])=>
      `<button type="button" class="kchip${HIDDEN.has(k)?" off":""}" data-kind="${k}" `+
      `title="hide or show these rows (this page only)">${k} <b>${n}</b></button>`).join("");
    if(bar.dataset.html!==html){bar.dataset.html=html;bar.innerHTML=html;}
  }
  $("keelfilters").addEventListener("click",ev=>{
    const b=ev.target.closest(".kchip"); if(!b)return;
    const k=b.dataset.kind;
    HIDDEN.has(k)?HIDDEN.delete(k):HIDDEN.add(k);
    keelPaint();
  });
  setInterval(keelPaint,1500);
})();
</script></body></html>
"""


# ---- KEEL ADDITION (T146): a port this process cannot OWN is never claimed
# The walk below has always been the plan: bind 8770, and on failure try the
# next. It silently did not work on Windows. ``ThreadingHTTPServer`` inherits
# ``allow_reuse_address = 1``, which on POSIX only permits rebinding a socket
# in TIME_WAIT - the standard, correct setting - but on Windows permits a
# SECOND process to bind an address a live listener already holds. So the
# bind never raised, the walk never walked, and the second board printed the
# first board's port.
#
# MEASURED 2026-08-15, with this project's board on 8770: a viewer started
# for a different project printed ``http://127.0.0.1:8770``, stayed on 8770,
# and every request to that URL was answered by the FIRST project's server.
# A reader following the command the session hook itself prints would have
# been watching another project's delegations, with nothing anywhere saying
# so. Printing a wrong port is worse than failing to start.
#
# The setting is therefore per-platform, because the right answer differs:
# POSIX keeps reuse ON (turning it off there would refuse a restart while a
# previous socket lingers in TIME_WAIT - a regression, not a fix), and
# Windows turns it OFF and asks for exclusive use, so a duplicate bind fails
# and the walk finally does what it always claimed to.
PORT_WALK_SPAN = 10


class _OwnedPortServer(ThreadingHTTPServer):
    """A server that fails to start rather than share someone else's port."""

    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            # Belt and braces, and not only theory: a board started BEFORE
            # this fix is still running with reuse on, and could otherwise
            # take a port from a server started after it.
            exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
            if exclusive is not None:
                try:
                    self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
                except OSError:
                    pass  # an older Windows that refuses it still gets the walk
        super().server_bind()


def bind_walk(start_port, span=PORT_WALK_SPAN, handler=None):
    """``(server, port)`` on the first port this process actually owns.

    Raises ``SystemExit`` when every port in the walk is taken - loudly, and
    without serving anything, because a viewer that cannot say where it is
    has nothing useful to say at all.
    """
    last = None
    for port in range(start_port, start_port + span):
        try:
            return _OwnedPortServer(("127.0.0.1", port), handler or Handler), port
        except OSError as exc:
            last = exc
    raise SystemExit(
        f"keel viewer: no free port in {start_port}-{start_port + span - 1} "
        f"({last}); nothing is being served"
    )


def main():
    global ROOT, _SERVER, _RESTART_REQUESTED
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=".", help="project folder containing .keel/")
    ap.add_argument("--port", type=int, default=8770,
                    help="fixed default 8770 (never derived - keel R19); "
                         "walks +1 when busy")
    args = ap.parse_args()
    ROOT = args.dir
    if not os.path.isdir(os.path.join(ROOT, ".keel")):
        # allow running as `python scripts/keel_orchestration_dashboard.py` from anywhere
        alt = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.isdir(os.path.join(alt, ".keel")):
            ROOT = alt
    # KEEL ADDITION (T146): the walk moved into ``bind_walk`` above, which
    # binds a port this process OWNS or exits saying it could not. The line
    # printed below therefore names the port that answers, which is what it
    # always claimed to do.
    srv, port = bind_walk(args.port)
    # KEEL ADDITION (T340): the restart handler needs the live server to
    # close its socket before the re-exec - see ``_close_server_socket``.
    _SERVER = srv
    print(f"Orchestration dashboard (keel): http://127.0.0.1:{port}  (project: {os.path.abspath(ROOT)})")
    _RESTART_REQUESTED = False
    srv.serve_forever()
    # KEEL ADDITION (T443 follow-up): ``serve_forever`` only ever returns
    # when something called ``srv.shutdown()`` - here, that is exclusively
    # ``_request_restart`` on the daemon timer, setting the flag below
    # BEFORE calling shutdown() (see that function's own comment for why the
    # order there is fixed too, and for the race this main-thread-only
    # design replaces). By the time control reaches this line, the accept
    # loop has genuinely stopped and nothing is selecting on the listening
    # socket any more, so it is finally safe to close it and re-exec/spawn -
    # both of which happen here, on the SAME thread that was just inside
    # ``serve_forever``, never on the timer thread that asked for the stop.
    if _RESTART_REQUESTED:
        _perform_restart()


if __name__ == "__main__":
    main()
