#!/usr/bin/env python3
"""keel neutral event model - the harness-independent kernel contract.

Contract
--------
Reads   : nothing from the environment directly. Its own two functions read
          only the filesystem, where the caller points them. Importing this
          module DOES pull in ``keel_redact`` (see Writes below), which at
          ITS OWN import resolves this user's home directory from the
          environment and reads ``scripts/keel-denied-names.json`` once -
          the same one-time reads that module declares under its own
          contract; nothing here re-reads either per call.
Emits   : values, never text. ``KeelEvent`` is what every gate consumes;
          ``KeelVerdict`` is what every gate returns. Harness payloads are
          translated into these by an adapter (``keel_adapter_claude.py``);
          no gate ever sees a raw payload, and no adapter ever decides.
Writes  : ``<project>/.keel/audit/keel-audit.jsonl`` via ``append_audit`` and
          ``<project>/.keel/queue/keel-observations.jsonl`` via
          ``append_queue`` - append-only JSONL, one event per line, each line
          carrying ``"v"``. The two logs are different contracts with
          different readers: the audit log is what the stop gate and
          ``keel attest`` reconcile, the queue is what distillation drains
          into records. Neither is ever rewritten in place. EVERY line either
          writer produces passes through ``keel_redact.redact_mapping`` first,
          inside ``_append_jsonl`` - the one function both writers call and
          the single place a line becomes bytes on disk. This is the
          write-time screen's chokepoint, not a convention a caller must
          remember: a caller that already redacted (``keel_capture.py``,
          ``keel_session.py``) gets the same bytes back, because ``redact``
          is idempotent on already-substituted text; a caller that did not
          (``keel_gate.py``'s ``_audit``/``_audit_bypass``,
          ``keel_stop.py``'s ``_audit``/``_nag_override``, before this
          module closed the gap) is now covered regardless. The cost: every
          audit and queue line is now tokenised against the home pattern and
          the denied-names register, where before only the callers that
          remembered to redact paid that cost - see the Performance note in
          ``keel_redact.py`` for what the walk itself costs.
Argv    : none. Library module; it is never executed as a hook.

Exit codes
----------
None of its own. This module defines the single output contract every keel
guard obeys (R6): ``KeelVerdict.to_exit_code()`` maps allow -> 0, ask -> 2,
deny -> 2, so a blocking exit code can never disagree with the emitted
decision. That mapping is the whole point of the type, and a contract test
asserts it against every fixture.

Failure policy
--------------
FAIL-CLOSED. This is a model, not a guard: an invalid event kind, an unknown
decision, or a blocking verdict with no reason raises ``ValueError`` instead
of being silently normalised (convention 7 - no component returns empty on
failure). Callers that must not break a session catch the error and apply
their own declared policy; nothing is swallowed here.

THE WRITE-TIME SCREEN INSIDE ``_append_jsonl`` KEEPS THAT POLICY RATHER THAN
EXCEPTING ITSELF FROM IT, and the distinction is worth stating exactly,
because "the redactor is fail-open" is true of the wrong thing here. Per
VALUE, ``keel_redact.redact`` is fail-open: a field it cannot process - a
type it does not expect, a machine where no home directory resolves, an
absent or malformed denied-names register - yields that field unchanged and
prints at most its own one-time stderr line, so a degraded register can never
turn an audit line into an exception. This module adds no second warning on
top of that one. Per LINE, this module stays fail-closed and does NOT wrap
the screen in a ``try``: if ``redact_mapping`` itself were to raise, the
append raises with it and NO line is written, rather than an unscreened line
being written instead. That is the same direction ``keel_redact`` takes for
the private marker - "fail open" applied to an exclusion would publish
exactly what the exclusion exists to withhold - and it costs nothing here,
every path to ``append_audit`` already catches and reports on stderr rather
than letting a hook die: ``keel_gate._audit``/``_audit_bypass``,
``keel_stop._audit``/``_nag_override``, ``keel_capture.run`` and
``keel_session.run`` each wrap their own call, and ``keel_hook.main`` wraps
every subcommand besides. A lost audit line is reported, never silent - and
never an unscreened one.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No shell, no network, no
subprocess. ``raw`` is stored read-only and is never interpolated into a
command, a message, or a path (R5).
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_redact import redact_mapping  # noqa: E402  (path must be set first)

#: The six normalised event kinds. A harness that cannot produce one of these
#: for a given native event simply produces no event at all.
EVENT_KINDS: tuple[str, ...] = (
    "pre_write",
    "pre_exec",
    "post_tool",
    "stop",
    "session_start",
    "session_end",
)

#: The three decisions. "ask" is a block that invites the user to decide; it
#: carries the same exit code as "deny" because both stop the tool call.
DECISIONS: tuple[str, ...] = ("allow", "ask", "deny")

#: R6: the exit code IS the decision. One table, one source of truth.
DECISION_EXIT_CODES: Mapping[str, int] = MappingProxyType(
    {"allow": 0, "ask": 2, "deny": 2}
)

#: Schema version stamped on every audit line. Bumping it is a contract change.
AUDIT_SCHEMA_VERSION = 1

#: Schema version stamped on every queue line. Versioned separately from the
#: audit log because they are separate contracts with separate readers: a
#: change to one must not force a re-read of the other.
QUEUE_SCHEMA_VERSION = 1

#: Project-relative locations of the keel state directory and its two logs.
KEEL_DIRNAME = ".keel"
AUDIT_SUBPATH = ("audit", "keel-audit.jsonl")
QUEUE_SUBPATH = ("queue", "keel-observations.jsonl")


def utc_now() -> str:
    """Current UTC instant, ISO 8601, second precision, explicit Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class KeelEvent:
    """One normalised harness event. Immutable by construction.

    ``raw`` keeps the untranslated payload for audit and for adapters that
    need a field the model has not normalised yet. It is stored read-only and
    is data, never code: nothing in keel interpolates it into a shell string,
    a path, or a message (R5).
    """

    kind: str
    cwd: Path
    session_id: str | None = None
    tool_name: str | None = None
    file_paths: tuple[str, ...] = ()
    command: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)
    ts: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {self.kind!r}; expected one of {EVENT_KINDS}")
        object.__setattr__(self, "cwd", Path(self.cwd))
        object.__setattr__(self, "file_paths", tuple(str(p) for p in self.file_paths))
        object.__setattr__(self, "raw", MappingProxyType(dict(self.raw)))
        if not self.ts:
            object.__setattr__(self, "ts", utc_now())

    @property
    def sess8(self) -> str:
        """First 8 characters of the session id - the ledger file's suffix."""
        return (self.session_id or "")[:8]


@dataclass(frozen=True)
class KeelVerdict:
    """A gate's answer. ``to_exit_code`` is the only exit table in keel (R6).

    ``gate`` names the rule that produced a block (``plan``, ``policy_lock``,
    ``stop``, ``internal_error``) and lands in the audit line. ``detail``
    carries structured counts for the audit only - never for interpolation.
    """

    decision: str
    reason: str = ""
    gate: str = ""
    detail: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.decision not in DECISIONS:
            raise ValueError(f"unknown decision {self.decision!r}; expected one of {DECISIONS}")
        if self.decision != "allow" and not self.reason.strip():
            raise ValueError("a blocking verdict must carry a reason (convention 7)")
        object.__setattr__(self, "detail", MappingProxyType(dict(self.detail)))

    @property
    def blocking(self) -> bool:
        """True when this verdict stops the tool call (ask and deny both do)."""
        return self.decision != "allow"

    def to_exit_code(self) -> int:
        """R6: allow -> 0, ask -> 2, deny -> 2. The code always matches the JSON."""
        return DECISION_EXIT_CODES[self.decision]


def allow(reason: str = "", gate: str = "") -> KeelVerdict:
    """An allow verdict. A reason is optional here and required for blocks."""
    return KeelVerdict(decision="allow", reason=reason, gate=gate)


def deny(reason: str, gate: str, **detail: Any) -> KeelVerdict:
    """A deny verdict; ``reason`` reaches the model, ``detail`` the audit log."""
    return KeelVerdict(decision="deny", reason=reason, gate=gate, detail=detail)


def ask(reason: str, gate: str, **detail: Any) -> KeelVerdict:
    """An ask verdict - blocking, but the user decides (exit code 2, R6)."""
    return KeelVerdict(decision="ask", reason=reason, gate=gate, detail=detail)


def audit_path(cwd: Path) -> Path:
    """Location of the append-only audit log for a project."""
    return Path(cwd).joinpath(KEEL_DIRNAME, *AUDIT_SUBPATH)


def queue_path(cwd: Path) -> Path:
    """Location of the append-only observation queue for a project."""
    return Path(cwd).joinpath(KEEL_DIRNAME, *QUEUE_SUBPATH)


# ---------------------------------------------------------------------------
# WHICH PROJECT A RECORD BELONGS TO (T515, BL8)
#
# ``audit_path`` and ``queue_path`` answer WHERE inside a project a line goes.
# They cannot answer WHICH PROJECT, and for most of keel's life every caller
# answered that with ``event.cwd`` - the directory the SESSION happens to be
# standing in. That is the defect BL8 measured twice: a record filed against a
# project that had nothing to do with the work, in a tree whose own guards then
# fail on it. The gate closed its half at T178 by resolving ARMING from the
# target upward; this closes the RECORDING half for every other writer, and it
# lives here because ``keel_events`` is the one module every writer already
# imports (``keel_gate``, ``keel_capture``, ``keel_session``, ``keel_stop``,
# ``keel_hook``) - a second copy of this walk in each of them is exactly the
# drift the two-readers-of-one-fact rule exists to stop.
#
# IT IS KEYED ON ``.keel/``, NOT ON THE ARMING FILE, and that is the whole
# reason it is not simply ``keel_gate.resolve_project``. Those are two
# different questions with two different right answers: arming asks WHICH
# POLICY JUDGES THIS (the arming file), recording asks WHICH TREE HAS A LOG TO
# PUT THIS IN (the state directory). An adopted tier-0 project has a log and no
# policy; keying the record walk on the arming file would silently stop
# recording every observing project keel has. The BOUND is shared with the
# arming walk rather than spelled twice - see ``RECORD_WALK_MAX_LEVELS``.
# ---------------------------------------------------------------------------


#: The record walk's cost limit, and the source of ``keel_gate``'s
#: ``PROJECT_WALK_MAX_LEVELS`` - the two walks ask different questions but they
#: climb the same filesystem, and a bound that differed between them would mean
#: a path keel can ARM but cannot FILE, or the reverse.
RECORD_WALK_MAX_LEVELS = 32

#: The three answers the record walk can give. ABSENT and UNKNOWN are different
#: facts and must never collapse into each other: ABSENT is COMPLETE (the walk
#: reached a ceiling and there is no project above this path), UNKNOWN is
#: INCOMPLETE (the walk ran out of budget, so a project it never reached could
#: own this path). A writer that reads UNKNOWN as ABSENT files the line
#: somewhere else - which is the BL8 shape, one level up.
RECORD_ROOT_FOUND = "found"
RECORD_ROOT_ABSENT = "absent"
RECORD_ROOT_UNKNOWN = "unknown"

#: Every state above, for the enumeration the suite walks.
RECORD_ROOT_STATES: tuple[str, ...] = (
    RECORD_ROOT_FOUND,
    RECORD_ROOT_ABSENT,
    RECORD_ROOT_UNKNOWN,
)


@dataclass(frozen=True)
class RecordRoot:
    """Which project owns a path for RECORDING, with EXHAUSTED told apart.

    ``root`` is set only for ``RECORD_ROOT_FOUND``. There is deliberately no
    ``__bool__`` and no "root or None" convenience, for the reason
    ``keel_gate.ProjectResolution`` gives about its own: the defect this type
    exists for was a caller reading a missing root as "file it where I am".
    """

    state: str
    root: Path | None = None

    @property
    def found(self) -> bool:
        """True when a ``.keel/``-bearing project owns this path."""
        return self.state == RECORD_ROOT_FOUND

    @property
    def unknown(self) -> bool:
        """True when the walk gave up before it could answer."""
        return self.state == RECORD_ROOT_UNKNOWN


#: The two answers that carry no root, built once because they carry no data.
ABSENT_RECORD_ROOT = RecordRoot(RECORD_ROOT_ABSENT)
UNKNOWN_RECORD_ROOT = RecordRoot(RECORD_ROOT_UNKNOWN)


def record_root_present(directory: Path) -> bool:
    """True when a directory carries ``.keel/`` - never raises.

    The presence test the record walk is keyed on, named once so that every
    caller asking "is this a tree keel may write a record into" asks it in the
    same words.

    FLAT-ADOPTION EXEMPT (T602), and it is the exemption every other one is
    measured against: this is the walk's own primitive, the single place the
    join is spelled, and ``resolve_record_root`` is built by calling it at each
    level. Routing it through the walk would be the walk calling itself.
    ``tests/test_keel_flat_adoption_sweep_t602.py`` pins this exemption.
    """
    try:
        return (Path(directory) / KEEL_DIRNAME).is_dir()
    except OSError:
        return False


def _record_walk_home() -> Path | None:
    """This user's home directory, canonicalised, or None if it cannot be read.

    NOT MEMOISED, unlike ``keel_gate._walk_home``, and the difference is a cost
    decision rather than a disagreement: the arming walk runs once per TARGET
    inside a loop, this runs at most twice per event. A memo here would also
    freeze the ceiling for a process whose ``HOME`` moves under it, which is
    precisely what the suite does to keep its fixtures off the real home.
    """
    try:
        return Path(os.path.realpath(str(Path.home())))
    except (OSError, ValueError, RuntimeError):
        return None


def resolve_record_root(path: str | Path, home: Path | None = None) -> RecordRoot:
    """The nearest ``.keel/``-bearing project AT OR ABOVE ``path``, or why not.

    THE TARGET NEED NOT EXIST - a write's target usually does not yet - so only
    directories are ever read, and only for ``.keel/``. NEAREST WINS: a project
    nested inside another records against its own log.

    BOUNDED THE SAME TWO WAYS THE ARMING WALK IS, and the two bounds mean
    different things. A filesystem root or the home directory is a CEILING: keel
    will not adopt either as a project, so stopping there is a complete answer
    and reads ABSENT. ``RECORD_WALK_MAX_LEVELS`` is a COST LIMIT: stopping there
    means keel ran out of budget, so it reads UNKNOWN and no caller may treat it
    as "nowhere owns this".

    THE FIRST DIRECTORY IS EXEMPT FROM THE CEILING, exactly as
    ``keel_gate.is_walk_ceiling`` is: a session whose own cwd IS the home
    directory, having adopted keel there, still has a log.

    FLAT-ADOPTION EXEMPT (T602): the one call to ``record_root_present`` in the
    loop below IS this walk, asking the flat question once per level, which is
    what makes every other site able to stop asking it.
    ``tests/test_keel_flat_adoption_sweep_t602.py`` pins this exemption.

    Never raises.
    """
    try:
        start = Path(os.path.realpath(str(path)))
    except (OSError, ValueError):
        # A path that will not resolve has no ancestors to climb. That is a
        # complete answer about THIS path, not a budget failure.
        return ABSENT_RECORD_ROOT
    ceiling = _record_walk_home() if home is None else _resolved_or_none(home)
    candidate = start
    for step in range(RECORD_WALK_MAX_LEVELS + 1):
        if step and _record_is_ceiling(candidate, ceiling):
            return ABSENT_RECORD_ROOT
        if record_root_present(candidate):
            return RecordRoot(RECORD_ROOT_FOUND, candidate)
        parent = candidate.parent
        if parent == candidate:
            return ABSENT_RECORD_ROOT  # the top of the tree, reached and read
        candidate = parent
    return UNKNOWN_RECORD_ROOT


def _resolved_or_none(value: Path) -> Path | None:
    """``realpath`` of a path, or None when it will not resolve. Never raises."""
    try:
        return Path(os.path.realpath(str(value)))
    except (OSError, ValueError, RuntimeError):
        return None


def _record_is_ceiling(candidate: Path, home: Path | None) -> bool:
    """``is_walk_ceiling`` for two already-resolved paths. Never raises."""
    try:
        if candidate.parent == candidate:
            return True
        return home is not None and candidate == home
    except (OSError, ValueError):
        return True


def record_root_or_none(cwd: Path) -> Path | None:
    """The project a record from ``cwd`` belongs in, or None. Never raises.

    THE ONE-LINE FORM every recording writer uses, and the None is the whole
    reason it exists: ABSENT and UNKNOWN both mean KEEL CANNOT NAME A LOG FOR
    THIS, and both must end in the caller writing nothing at all rather than
    creating a ``.keel/`` in a directory nobody adopted (R25). A caller that
    needs to tell the two apart - to say WHY on stderr - asks
    ``resolve_record_root`` directly.
    """
    return resolve_record_root(cwd).root


def record_root_as_spelled(cwd: Path, resolution: RecordRoot | None = None) -> Path | None:
    """``record_root_or_none``, but never RESPELLING a path it did not move.

    THE WALK CANONICALISES, AND THAT CAN DEFEAT THE REDACTOR (T602). The walk
    climbs ``os.path.realpath``, so the root it hands back is the canonical
    spelling of the directory - and on Windows the harness routinely hands keel
    the 8.3 SHORT form. Measured: a caller that hands in a path whose account
    component is spelled ``<EIGHT~1.THR>`` gets back one spelled with the full
    account name instead, the two differing in that component alone. Both name
    the same directory, so every WRITE lands correctly either way - but
    ``keel_redact`` collapses the home directory BY STRING, so a path respelled
    out of the spelling the home was resolved to stops matching, and the raw
    path reaches stderr in a fault message. That is a redaction leak
    (convention 5) introduced by a destination fix, which is a poor trade.
    ``tests/test_keel_compaction_t228.py`` caught it as a real failure, not by
    review.

    SO: when the directory handed in IS the record root, the caller's own
    spelling comes back unchanged, and the ordinary session - the overwhelming
    majority, where the project root is what the harness named - is
    byte-identical to what it was before any of this. Only a walk that actually
    CLIMBED returns a canonical ancestor, which is a path the caller never held
    a spelling of anyway.

    ``resolution`` LETS A CALLER THAT ALREADY WALKED HAND ITS ANSWER IN, so a
    caller which needs to tell ABSENT from UNKNOWN (to say WHY on stderr) does
    not climb the filesystem a second time for the spelling. Passing a
    resolution that came from a different path is the caller's error and would
    be answered honestly - with that path's root.

    Never raises; None for exactly what ``record_root_or_none`` answers None
    for, and for the same fail-closed reason.
    """
    if resolution is None:
        resolution = resolve_record_root(cwd)
    if resolution.root is None:
        return None
    try:
        if os.path.realpath(str(cwd)) == str(resolution.root):
            return Path(cwd)
    except (OSError, ValueError):
        # A spelling that will not resolve is one keel cannot vouch for; the
        # walk's own canonical answer is the safe one to hand back.
        return resolution.root
    return resolution.root


# ---------------------------------------------------------------------------
# THE ATOMIC APPEND
#
# Two keel processes append to one log routinely - a subagent's stop hook and
# the orchestrator's post-tool capture are the pair that actually collided -
# so the append must be atomic ACROSS PROCESSES, not merely correct within
# one. The obvious spelling is not enough: `open(path, "a")` IS atomic on
# POSIX, where the kernel honours ``O_APPEND`` per write, and is NOT atomic on
# Windows, where the Microsoft C runtime emulates append as seek-to-end THEN
# write - two steps with a gap, so two processes that both seek before either
# writes both write at the SAME offset and the second silently overwrites the
# first.
#
# That is not a theoretical risk. It happened to this repository's own audit
# log on 2026-09-02: a 239-byte record landed at the offset of a 303-byte one,
# overwrote its first 239 bytes, and left the remaining 64 as a line of their
# own - costing one ``subagent_stop`` event, the one thing keel promises not
# to lose. The mechanism is recorded at
# ``.keel/knowledge/windows-append-mode-is-seek-then-write.md`` and the
# reproducer is ``tests/test_keel_audit_append_race.py``, which loses on the
# order of 130 of 1600 lines against the old writer and none against this one.
#
# So: one exclusive lock, one seek, one write, on every platform.
# ---------------------------------------------------------------------------

#: The byte a Windows writer locks in order to serialise appends.
#:
#: WHY NOT BYTE 0, which is the conventional choice. Windows file locks are
#: MANDATORY, not advisory: a region locked by one process cannot be READ by
#: another, and it would fail that reader's read rather than make it wait.
#: keel's readers - the stop gate, ``keel attest``, the live board - read this
#: log continuously while hooks are writing to it, so a lock over real bytes
#: would trade a rare lost line for a new class of failed read. Windows
#: permits locking a range BEYOND end-of-file, so the writers rendezvous on a
#: byte far past any end this log will ever have, where no reader will ever
#: look. One TiB of JSONL text is not a log this project will produce; if it
#: somehow were, the lock would still be correct, merely visible to a reader
#: that had read a terabyte to reach it.
#:
#: POSIX needs no such care: ``flock`` is advisory and whole-file, so a reader
#: that does not ask for the lock is never affected by it.
_WINDOWS_LOCK_OFFSET = 1 << 40

#: How long a writer waits for the append lock before giving up and writing
#: without it. Ten seconds is the budget ``msvcrt.LK_LOCK`` would have spent
#: on its own; what changed is how it is spent - see ``_lock_exclusive``.
_LOCK_TIMEOUT_SECONDS = 10.0

#: How long to sleep between attempts on Windows. One millisecond against a
#: lock measured to be held for under one (0.8ms per uncontended append).
_LOCK_POLL_SECONDS = 0.001

if sys.platform == "win32":  # pragma: no cover - platform-selected at import
    import msvcrt

    def _lock_exclusive(fd: int) -> None:
        """Wait for the exclusive append lock. Raises ``OSError`` on timeout.

        WHY THIS POLLS RATHER THAN ASKING FOR A BLOCKING LOCK. The obvious
        spelling is ``msvcrt.locking(fd, msvcrt.LK_LOCK, 1)``, and it is the
        wrong tool inside a hook: ``LK_LOCK`` retries on a ONE-SECOND timer
        and gives up after ten attempts, so a writer that loses a race stalls
        for a full second over a lock that is held for less than a
        millisecond. Two hooks appending at once is ordinary here rather than
        pathological - a subagent's stop hook and the orchestrator's post-tool
        capture do it routinely - so that stall would be an ordinary
        occurrence and it would be visible in the session as a pause.
        ``LK_NBLCK`` fails immediately instead, which lets the same
        ten-second budget be spent polling on a millisecond timer: the
        uncontended cost is unchanged, a collision costs about a millisecond
        instead of a second, and the ceiling that ends in ``OSError`` is
        still there for ``_append_bytes`` to apply its policy to.
        """
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while True:
            os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(_LOCK_POLL_SECONDS)

    def _release(fd: int) -> None:
        """Release the lock ``_lock_exclusive`` took."""
        os.lseek(fd, _WINDOWS_LOCK_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:  # pragma: no cover - platform-selected at import

    import fcntl

    def _lock_exclusive(fd: int) -> None:
        """Wait for the exclusive append lock. Raises ``OSError`` on failure."""
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: int) -> None:
        """Release the lock ``_lock_exclusive`` took."""
        fcntl.flock(fd, fcntl.LOCK_UN)


def _append_bytes(path: Path, payload: bytes) -> None:
    """Append ``payload`` to ``path`` in ONE write, serialised across processes.

    The caller hands over finished bytes: serialisation happens once, above,
    so that nothing here can split one logical line into two writes. The file
    is opened in BINARY append - no text layer, so no platform can translate
    the trailing ``\\n`` into ``\\r\\n``, which makes the LF guarantee a
    property of the encoding step rather than of an ``open`` argument that a
    later edit could drop.

    The seek to end inside the lock is what makes the Windows path correct
    rather than merely conventional: the seek and the write are two steps, and
    holding the lock across both is exactly what closes the gap between them.

    A LOCK TIMEOUT WRITES ANYWAY, DELIBERATELY. If the lock cannot be taken -
    ten seconds of contention on Windows, or a filesystem that refuses locks
    altogether, which some network mounts do - this writes without it rather
    than raising or returning. Under that much contention the honest choice is
    the OLD behaviour, a rare overwrite, and not a NEW one, a dropped event: a
    record that loses a line under pathological load is bad, and a record that
    silently declines to write one is worse, because nothing downstream can
    tell that it happened. The unlock is skipped in that case too - releasing
    a lock this process never took is not this function's to do.

    No flush and no ``fsync``: ``os.write`` is unbuffered, so the bytes are
    with the operating system when it returns. Durability across a power cut
    is not a promise this log makes, and an ``fsync`` per audit line would be
    paid on every tool call.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o644)
    try:
        try:
            _lock_exclusive(fd)
            locked = True
        except OSError:
            locked = False
        try:
            os.lseek(fd, 0, os.SEEK_END)
            written = 0
            while written < len(payload):
                written += os.write(fd, payload[written:])
        finally:
            if locked:
                _release(fd)
    finally:
        os.close(fd)


def _append_jsonl(path: Path, entry: Mapping[str, Any], version: int) -> Path:
    """Append one JSON line to ``path``, stamping ``v`` and ``ts``.

    Newline is LF by construction: the line is encoded to bytes here and
    written through ``_append_bytes`` in binary, so no text layer exists that
    could turn a log into CRLF JSONL. One writer for both logs: two append
    routines drift, and a queue line that lost its ``v`` is a line no reader
    can version.

    THE APPEND IS ATOMIC ACROSS PROCESSES, which is a correctness property of
    the record and not a performance detail - see the block comment above
    ``_append_bytes`` for the race it closes and the event it cost. The two
    steps that matter here: the line is serialised to bytes ONCE, so no
    logical line can be split across two writes, and those bytes reach the
    file in one locked write that no concurrent writer can land on top of.

    THE WRITE-TIME SCREEN'S CHOKEPOINT. ``line`` is passed through
    ``keel_redact.redact_mapping`` right here, after ``v``/``ts`` are stamped
    and every caller-supplied field is merged in, and immediately before it
    is serialised - the last point at which the line is still a value rather
    than bytes, and the one point every audit line and every queue line
    passes through no matter which caller built it. A caller upstream
    (``keel_capture.py``, ``keel_session.py``) may already have redacted its
    own fields with the same function; that is not redundant work removed
    from here, it is the other reason this call is safe to make
    unconditionally - ``redact`` cannot un-substitute a token or re-collapse
    an already-collapsed home prefix, so redacting twice reproduces the same
    bytes as redacting once (see ``tests/test_keel_audit_chokepoint_screen.py``
    for the idempotence proof). A caller that never redacted at all
    (``keel_gate.py``'s ``_audit``/``_audit_bypass``, ``keel_stop.py``'s
    ``_audit``/``_nag_override``) is covered for the first time by this line,
    without having to import ``keel_redact`` itself - the fix sits where no
    future writer can bypass it by forgetting to call it.

    WHAT "AFTER EVERY CALLER-SUPPLIED FIELD IS MERGED IN" BUYS, beyond the
    denied-names screen it was added for: a field a caller built by
    RESHAPING a path - ``keel_gate.relativise`` turns an absolute path outside
    the project into ``../../Users/<name>/x``, a spelling no home-prefix
    pattern can match - is screened here too, because ``redact``'s home-shape
    step is anchored on the home root rather than on this machine's own home
    prefix (see ``keel_redact.screen_home_shapes``). That is the reason this
    call sits after the merge rather than being left to the caller that knows
    what its own field means: the caller cannot always spell it safely, and
    this line does not need it to.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    line: dict[str, Any] = {"v": version, "ts": utc_now()}
    line.update(dict(entry))
    line = redact_mapping(line)
    _append_bytes(path, (json.dumps(line, ensure_ascii=False) + "\n").encode("utf-8"))
    return path


def append_audit(cwd: Path, entry: Mapping[str, Any]) -> Path:
    """Append one JSON line to ``<cwd>/.keel/audit/keel-audit.jsonl``.

    Stamps ``v`` and ``ts`` when the caller has not.
    """
    return _append_jsonl(audit_path(cwd), entry, AUDIT_SCHEMA_VERSION)


def append_queue(cwd: Path, entry: Mapping[str, Any]) -> Path:
    """Append one JSON line to ``<cwd>/.keel/queue/keel-observations.jsonl``.

    The queue is the distillation input: mechanical, model-free, and drained
    by ``/keel:log`` into records. Nothing here decides anything, and no
    payload body reaches it - the caller writes summaries (see
    ``keel_capture.observation``).
    """
    return _append_jsonl(queue_path(cwd), entry, QUEUE_SCHEMA_VERSION)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Every parseable object in a JSONL log, oldest first."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            raw_lines = handle.readlines()
    except OSError:
        return []
    events: list[dict[str, Any]] = []
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
        except ValueError:
            continue
        if isinstance(decoded, dict):
            events.append(decoded)
    return events


def read_audit(cwd: Path) -> list[dict[str, Any]]:
    """Every parseable object in the audit log, oldest first.

    A corrupt line loses exactly that line - the JSONL guarantee, and why the
    audit log is append-only lines rather than one document;
    a missing log is an empty history, which is a fact rather than a failure.
    """
    return _read_jsonl(audit_path(cwd))


def read_queue(cwd: Path) -> list[dict[str, Any]]:
    """Every parseable object in the observation queue, oldest first.

    Same one-line-loss guarantee as the audit log, and the same reading of an
    absent file: a project that has observed nothing yet has an empty queue,
    which is a fact rather than a failure.
    """
    return _read_jsonl(queue_path(cwd))


def normalise_paths(values: Iterable[Any]) -> tuple[str, ...]:
    """Keep the non-empty strings from a payload's path-ish fields, in order."""
    kept: list[str] = []
    for value in values:
        if isinstance(value, str) and value.strip():
            kept.append(value)
    return tuple(kept)
