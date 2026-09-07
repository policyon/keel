#!/usr/bin/env python3
"""keel hook launcher — the single entry point for every keel hook (R13).

Contract
--------
Reads   : one JSON object on stdin (the harness hook payload). Recognised
          fields: ``cwd`` (project directory; falls back to ``os.getcwd()``),
          ``session_id``, and - for the three subcommands that need them -
          ``agent_id``/``agent_type``/``transcript_path`` (``subagent_stop``),
          ``prompt``/``transcript_path`` (``prompt``) and ``transcript_path``
          (``precompact``).
          Unknown fields are ignored, never interpolated.
Emits   : nothing on stdout unless a subcommand produces a hook decision or
          context. ``spike``, ``capture``, ``subagent_stop`` and ``precompact``
          produce neither, so they print nothing at all; ``gate`` and ``stop``
          emit one line of ``hookSpecificOutput`` JSON when — and only when —
          they block;
          ``session`` emits one plain line at SessionStart in an adopted
          project, which the harness adds to the session's context; and
          ``prompt`` emits ONE plain line - the context nudge (T473) - on the
          turns where a new ten-percent step of the context window is crossed
          AND the step behind it reached disk, and nothing at all on every
          other turn.
          Diagnostics go to stderr only (convention 7: no silent failure).
Writes  : ``<cwd>/.keel/audit/keel-audit.jsonl`` — append-only JSONL, one
          event per line, each line carrying ``"v"`` (R-schema field). And,
          from every failure path only, one line in the user-global hook-error
          log through ``keel_faultlog`` (``~/.claude/keel/keel-hook-errors.jsonl``,
          T235): timestamp, subcommand, fault kind, redacted one-line summary.
          A healthy session writes nothing there and creates no directory.
          And, from ``prompt`` and ``precompact`` in an ADOPTED project only,
          the two compaction-survival files, through ``keel_compaction``
          (T228): one line per user prompt in a per-session prompt log - plus
          one ``nudge`` line per context step that log's session has been told
          about (T473) - under ``<cwd>/.keel/cache/`` since T474, and one line
          per compaction in the permanent compaction ledger, which stays under
          the user-global keel directory
          (``.keel/decisions/2026-09-03-the-bl28-window-takes-the-runbook-defaults.md``,
          Decision B). All go through the same write-time redaction chokepoint
          every audit line does; the prompt log is a project file in the ONE
          gitignored, regenerable directory a project declares, and an
          unadopted project produces none of them.
          And, when a crashed ``stop`` actually refuses a turn-end, one empty
          marker file in the system temp directory
          (``keel_hook_crash_stop_<session>``), which is how that refusal is
          kept to ONE - see ``_stop_loop_guard``. Nothing else, ever.
Deletes : ONE thing, from ONE place, and only from ``session`` on SessionEnd
          in an adopted project: per-session prompt logs older than
          ``keel_compaction.PROMPT_LOG_KEEP_DAYS`` in that project's own
          ``.keel/cache/keel-prompts/`` (T474). The guard that keeps it there
          lives in ``keel_compaction.prune_prompt_logs``; this file's part is
          to call it once and to PRINT what it deleted, so a file keel removed
          is always a file the session's stderr can be asked about.
Argv    : ``keel_hook.py <subcommand>``; dispatch table is SUBCOMMANDS.
          An unknown or missing subcommand is a no-op.

Exit codes
----------
0  the subcommand reached no blocking decision (always, for ``spike``).
2  ``gate`` or ``stop`` returned ask or deny. The code is produced by
   ``KeelVerdict.to_exit_code()``, never by this file, so it can never
   disagree with the emitted JSON decision (R6).

Synchronicity
-------------
``gate`` and ``stop`` are synchronous by design: a gate that does not block
is not a gate (convention 11). ``spike``, ``capture``, ``subagent_stop`` and
``precompact``
are observers, registered async, and must never make the user wait -
``subagent_stop`` least of all, since what waits on it is a subagent trying
to finish. ``session`` and ``prompt`` are the two observers that are NOT
async: their stdout is context, and context that arrives after the model has
started is not context. ``prompt`` was async until T473 and is not any more;
the cost of that - one Python launch per prompt, before the turn - was put to
the owner with its alternative and accepted in
``.keel/decisions/2026-09-03-the-bl28-window-takes-the-runbook-defaults.md``
(Decision A), which also keeps it ONE registration: the same subcommand
records the prompt and, when a step is crossed, nudges.

Failure policy
--------------
TWO POLICIES, BY SUBCOMMAND CLASS, and which one applies is not this file's
choice: it is
``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``, ratified
2026-08-21, which overruled the single fail-open this section used to declare.

OBSERVERS FAIL-OPEN — ``spike``, ``capture``, ``session``, ``subagent_stop``,
``prompt``, ``precompact``.
keel watching a session must never be able to break it, and an observer's
crash decides nothing, so an exception escaping one is reported on stderr and
the launcher exits 0.

GATES (``gate``, ``stop``) FAIL CLOSED WHEN ARMED, OPEN WHEN UNARMED — the
same policy the gates themselves declare, applied by the launcher when the
exception escapes them instead of being handled inside them. An escaping
exception is handed to ``gate_crash_exit``, which asks the gate's own failure
policy (``keel_gate._cannot_evaluate`` / ``keel_stop._cannot_account``) rather
than deciding anything itself, so the verdict is what the gate would have
returned had the fault happened one frame earlier: armed → deny (exit code and
JSON from ``KeelVerdict.to_exit_code``, rendered by the adapter, with the fault
classified as keel's own module, the arming file, or the environment);
unarmed → allow; a write whose every target is inside ``.keel/plans/`` →
allowed loudly, the one crash-time write, so a freeze can always be recorded;
``KEEL_GATE=off`` → allow, the user's own documented unfreeze. When arming
itself cannot be established — the gate module or the adapter did not import,
or the event cannot be rebuilt — the answer is DENY: unverifiable is deny, and
fail-open follows a project PROVEN unarmed, never one keel could not ask
about. A payload the subcommand does not gate is passed untouched: a crash
over a ``Read`` may not refuse the ``Read`` - and the adapter RETURNING nothing
is that same answer, given by the adapter itself, not an undeterminable one.
A crashed ``stop`` refuses a given turn-end ONCE and then stands aside
(``_stop_loop_guard``): the ruling asks for a deny, not for a session that can
never end and therefore can never be repaired from inside itself.

BOTH classes write one line to the user-global hook-error log first (see
Writes), and that write can never change a verdict or an exit code.

This declaration is asserted by tests/test_keel_phase0.py,
tests/test_keel_kernel.py and tests/test_keel_crash_deny_t236.py (R3).

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No shell string interpolation
of payload-derived values — nothing here reaches a shell at all (R5).
Every file operation states its encoding explicitly (convention 6).
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

#: Why the imports below are GUARDED, which is not the ordinary house style:
#: a half-applied edit to a gate module makes it fail to IMPORT (a
#: ``SyntaxError`` while the file is half-written, an ``ImportError`` from a
#: sibling), and a module-scope import failure here killed the launcher itself
#: with a traceback and a non-blocking exit code - keel's own crash deciding a
#: tool call by accident. Under
#: ``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md`` the
#: launcher has to be the thing that survives long enough to deny, so the
#: fault is RECORDED and every consumer below asks ``globals().get`` for the
#: module it needs. ``Exception``, not ``ImportError``: a partially written
#: module raises ``SyntaxError``, which is not one.
#:
#: ONE GUARD PER IMPORT, AND GATES BEFORE OBSERVERS. Both halves of that are
#: repairs of a MEASURED freeze, not taste - see
#: ``.keel/plans/keel-freeze-2026-08-21-3fbfa431.md``, written from inside the
#: freeze it describes.
#:
#: What happened: these imports were ONE ``try`` with the observers first, and a
#: half-applied edit to ``keel_session`` (an observer, which decides nothing)
#: raised ``SyntaxError``. An import that raises aborts the REST of its block,
#: so ``keel_gate`` was never bound, the launcher could not establish whether
#: the project was armed, and - correctly, under the ratified ruling - it denied
#: every write and every shell call in the project. A broken OBSERVER froze the
#: GATE. The comment that used to stand here argued the opposite order on the
#: grounds that the kernel and the fault log serve the most paths; the freeze
#: settled it. A broken module must cost its own subcommand and nothing else.
#:
#: So each import stands in its OWN guard: no module's failure can abort
#: another's binding, which is the only way to make that property true rather
#: than merely likely. The ORDER is then a statement of priority rather than a
#: dependency: the kernel, the adapter and the two GATES first, because the
#: decision the launcher must still reach depends on exactly those; the fault
#: log and the two observers after, because nothing that decides a tool call
#: depends on them. ``keel_faultlog`` imports no keel module at its own scope,
#: so it survives a broken gate and the error log still gets its line.
#:
#: A cascade is still recorded honestly rather than hidden: ``keel_session`` and
#: ``keel_stop`` import ``keel_gate`` themselves, so a broken gate module fails
#: their imports too, and every failure is named in ONE stderr line instead of
#: one line each. ``Exception``, not ``ImportError``: a partially written module
#: raises ``SyntaxError``, which is not one.
_IMPORT_FAULTS: list[str] = []

try:
    from keel_events import (  # noqa: E402
        AUDIT_SCHEMA_VERSION,
        DECISION_EXIT_CODES,
        KEEL_DIRNAME,
        append_audit,
        record_root_as_spelled,
        resolve_record_root,
        utc_now,
    )
except Exception as _exc:  # noqa: BLE001 - a launcher that cannot import must still decide
    _IMPORT_FAULTS.append(f"keel_events: {type(_exc).__name__}: {_exc}")

try:
    import keel_adapter_claude as adapter  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_adapter_claude: {type(_exc).__name__}: {_exc}")

try:
    import keel_gate  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_gate: {type(_exc).__name__}: {_exc}")

try:
    import keel_stop  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_stop: {type(_exc).__name__}: {_exc}")

try:
    import keel_faultlog  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_faultlog: {type(_exc).__name__}: {_exc}")

try:
    import keel_capture  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_capture: {type(_exc).__name__}: {_exc}")

try:
    import keel_session  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_session: {type(_exc).__name__}: {_exc}")

try:
    import keel_compaction  # noqa: E402
except Exception as _exc:  # noqa: BLE001
    _IMPORT_FAULTS.append(f"keel_compaction: {type(_exc).__name__}: {_exc}")

#: The joined summary every failure path below quotes. Truthy exactly when at
#: least one module is missing, which is the one question the crash path asks.
_IMPORT_FAULT = "; ".join(_IMPORT_FAULTS)
if _IMPORT_FAULT:
    print(f"keel: hook module(s) could not be imported: {_IMPORT_FAULT}", file=sys.stderr)


def _read_payload(stream: Any) -> dict[str, Any]:
    """Decode the stdin payload as UTF-8 JSON; return {} for anything else.

    A malformed payload is not an error worth failing a session over: the
    subcommand simply sees no fields and falls back to its defaults.
    """
    try:
        if stream is None or stream.isatty():
            return {}
        raw = stream.buffer.read()
    except (AttributeError, OSError, ValueError):
        return {}
    if not raw:
        return {}
    try:
        # utf-8-sig, not utf-8: a Windows PowerShell pipe prepends a BOM, and
        # a BOM that fails the JSON parse would silently disarm every gate on
        # that platform; this is regression-tested.
        decoded = raw.decode("utf-8-sig", errors="replace")
    except (AttributeError, UnicodeError):
        return {}
    if not decoded.strip():
        return {}
    try:
        payload = json.loads(decoded)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_cwd(payload: dict[str, Any]) -> Path:
    """Project directory from the payload, falling back to the process cwd."""
    value = payload.get("cwd")
    if isinstance(value, str) and value.strip():
        return Path(value)
    return Path(os.getcwd())


def _payload_text(payload: dict[str, Any], key: str) -> str | None:
    """A non-empty string field of the payload, or None.

    ABSENCE IS EXPRESSED, NEVER FAKED (convention 7): a field the harness
    omitted, sent as a non-string, or sent as the empty string all answer
    None, so a record built from this carries a null rather than a value
    nobody supplied. That distinction is load-bearing for the delegation
    fields ``cmd_subagent_stop`` records - a blank ``agent_type`` is common
    and is a fact about the payload, not a default to invent around.
    """
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _payload_session(payload: dict[str, Any]) -> str | None:
    """Session identifier from the payload, or None when absent/unusable."""
    return _payload_text(payload, "session_id")


def _recording_project(directory: Path, name: str, verb: str = "recorded") -> Path | None:
    """The project an observer's line belongs in, or None. Never raises.

    THE LAUNCHER'S SHARE OF THE T515 SWEEP, and it is the SAME WALK the other
    writers use rather than a fourth copy of it: ``keel_events``' record walk,
    keyed on ``.keel/`` (the state directory), bounded at the home directory
    and the filesystem root, and telling EXHAUSTED apart from ABSENT.

    WHAT IT REPLACED, AND WHY THAT MATTERED MOST HERE. Both callers used to ask
    ``(project / KEEL_DIRNAME).is_dir()`` - does THIS EXACT DIRECTORY carry
    ``.keel/`` - and ``return 0`` when it did not. For ``cmd_subagent_stop``,
    the live writer of every ``subagent_stop`` line, that is a DROPPED EVENT
    with no record anywhere: a session whose harness supplied no
    ``CLAUDE_PROJECT_DIR`` falls back to the payload's ``cwd``, which follows
    the shell into subdirectories, and every delegation that finished from one
    vanished silently. The stop gate then reconciled a log that was missing
    them - a guardrail passing because it examined nothing.

    IT CANNOT WIDEN WHERE KEEL WRITES (R25). The walk only ever returns a
    directory that ALREADY carries ``.keel/``; a project that never adopted
    keel answers None here exactly as the flat test answered False, and no
    ``.keel/`` is created anywhere new. The direction is strictly more record.

    ABSENT IS SILENT, EXHAUSTED IS SAID (convention 7). "No project above this
    path" is a COMPLETE answer and an unadopted tree is keel's business to
    leave alone. "The walk ran out of budget" is an INCOMPLETE one: a project
    that owns this path may exist above the ceiling, so a line is being lost
    rather than declined, and an observer that lost a line says so.

    ``verb`` EXISTS BECAUSE T602 GAVE THIS FUNCTION A CALLER THAT WRITES
    NOTHING. Four of the five callers file a line and say "not recorded"; the
    SessionEnd prompt-log prune DELETES files and says "not run". One helper
    with an honest verb beats a second copy of the walk for the sake of one
    word - the drift the shared walk exists to stop.
    """
    resolution = resolve_record_root(directory)
    if resolution.found and resolution.root is not None:
        # THE CALLER'S OWN SPELLING WHEN THE WALK DID NOT CLIMB (T602) - see
        # ``keel_events.record_root_as_spelled`` for the measured reason: the
        # walk canonicalises, and a path respelled out of the home's own
        # spelling stops being redactable.
        return record_root_as_spelled(directory, resolution)
    if resolution.unknown:
        print(
            f"keel: {name} not {verb}: the project this path belongs to "
            f"could not be established within the walk's bound",
            file=sys.stderr,
        )
    return None


#: The event name ``cmd_spike`` writes, named here rather than spelled
#: inline. KEEL ADDITION (T349, from the tests review): a test proves the
#: suite never writes into keel's own record by scanning the log for lines
#: carrying THIS name. Spelled as a literal in both places, a rename here
#: would leave that test scanning for a string nothing writes any more - it
#: would find nothing, pass, and stop protecting without ever failing. One
#: constant, imported by the test, makes the rename break loudly instead.
SPIKE_EVENT = "spike"


def cmd_spike(payload: dict[str, Any]) -> int:
    """Phase 0 hook-execution spike: prove the launcher fires on all 3 OS.

    Appends exactly one audit line when a keel-bearing project owns the
    payload's directory. Does nothing at all otherwise — an unadopted project
    is untouched, which is the arming model in miniature.

    SWEPT WITH THE REST FOR CONSISTENCY, NOT FOR A CONSEQUENCE (T515). This
    subcommand answers to no registration: nothing in this repository's
    settings or plugin manifests names ``spike``, so it is reachable only
    through ``SUBCOMMANDS`` and a hand-run launcher, and no live session is
    losing a line here. What the flat ``.keel/`` test WAS is the same
    silent-drop shape ``cmd_subagent_stop`` had for real, and leaving one
    spelling of a rule beside another is how the two come to disagree - see
    ``_recording_project``.
    """
    project = _recording_project(_payload_cwd(payload), SPIKE_EVENT)
    if project is None:
        return 0
    append_audit(
        project,
        {
            "v": AUDIT_SCHEMA_VERSION,
            "event": SPIKE_EVENT,
            "ts": utc_now(),
            "session": _payload_session(payload),
        },
    )
    return 0


def cmd_gate(payload: dict[str, Any]) -> int:
    """PreToolUse: plan-before-write and the policy lock (synchronous).

    The adapter normalises the payload; ``keel_gate`` decides; the adapter
    renders. A payload that maps to no pre_write/pre_exec event is not this
    gate's business and passes untouched.
    """
    event = adapter.event_from_payload(payload)
    if event is None or event.kind not in ("pre_write", "pre_exec"):
        return 0
    return adapter.emit(keel_gate.run(event), event)


def cmd_stop(payload: dict[str, Any]) -> int:
    """Stop: accounting for this session's ledger (synchronous).

    ``assume_kind`` is set because a Stop payload names no tool, and older
    harness builds omit ``hook_event_name`` altogether — the subcommand this
    hook was registered as is the authority on which event fired.
    """
    event = adapter.event_from_payload(payload, assume_kind="stop")
    if event is None or event.kind != "stop":
        return 0
    return adapter.emit(keel_stop.run(event), event)


def cmd_capture(payload: dict[str, Any]) -> int:
    """PostToolUse / PreToolUse observation: action and hand-off records.

    ``assume_kind`` is ``post_tool`` because one of this subcommand's three
    registrations is a PreToolUse on ``Task``, which the adapter maps to no
    kind at all - ``Task`` is not a write tool and not a shell tool. The
    launch/return distinction is not lost: ``keel_capture`` reads the native
    hook-event name from the payload it was built from.
    """
    event = adapter.event_from_payload(payload, assume_kind="post_tool")
    if event is None:
        return 0
    return keel_capture.run(event)


def _prune_prompt_logs(project: Path) -> None:
    """The SessionEnd half of T474's hygiene: one prune, reported. Never raises.

    WHY HERE AND NOT IN ``keel_session``: SessionEnd is an observer keel
    already subscribes to, so the prune costs no new registration and no new
    always-loaded bytes (the runbook's constraint for task 2), and a session
    that is ending is the one moment when deleting its neighbours' stale logs
    can inconvenience nobody.

    WHAT IT MAY DELETE IS NOT DECIDED HERE. ``keel_compaction`` owns the
    directory, the name pattern, the age bound and the ``.keel/cache/`` guard;
    this function calls it once and PRINTS the count, because a deletion keel
    performed and never mentioned is exactly the silent failure convention 7
    exists to forbid.

    WHAT IS PRINTED, and why not always: one stderr line whenever files were
    deleted, whenever the prune was REFUSED or faulted, or whenever a file it
    matched could not be removed. A pass that walked a directory and found
    nothing old enough - the ordinary end of an ordinary session - prints
    nothing, because a line per session end on every machine would be noise
    with no reader, and the count is still in the returned outcome for a caller
    or a test that wants it.
    """
    try:
        outcome = keel_compaction.prune_prompt_logs(project)
        if (
            outcome.pruned
            or outcome.failed
            or outcome.reason
            in (
                keel_compaction.PRUNE_REFUSED,
                keel_compaction.PRUNE_FAULT,
                keel_compaction.PRUNE_BAD_BOUND,
            )
        ):
            print(
                f"keel: prompt-log prune: {outcome.pruned} file(s) deleted, "
                f"{outcome.kept} kept, {outcome.failed} could not be deleted "
                f"({outcome.reason})",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 - hygiene may never cost a session its end
        print(f"keel: prompt logs not pruned: {_fault_text(exc)}", file=sys.stderr)


def cmd_session(payload: dict[str, Any]) -> int:
    """SessionStart / SessionEnd: the audit line, the injection, the prune.

    ``assume_kind`` covers a harness build that omits ``hook_event_name``;
    a SessionEnd payload names itself and maps on its own.

    THE PRUNE RUNS AFTER THE RECORD, on SessionEnd only and in an adopted
    project only (T474). After, because the audit line is the thing that must
    survive: hygiene that could cost a session its last record would be a poor
    trade for a few deleted files. In an adopted project only, for R25's
    reason - keel touches nothing in a project that never adopted it - and
    because ``prompt_dir`` of an unadopted project names a directory that does
    not exist, which the prune reports rather than creates.

    THE PROJECT IS WALKED UP, NOT READ OFF THE CWD (T602, BL8's residue). This
    line used to ask ``(event.cwd / KEEL_DIRNAME).is_dir()``, which made the
    prune AGREE WITH NOTHING ELSE once T515 landed: ``cmd_prompt`` writes the
    log into the project ``_recording_project`` names, so a session standing in
    a SUBDIRECTORY wrote its prompts to the root and then pruned a directory
    under the subdirectory that had never existed - files accumulating with no
    reaper, which is the shape T474 exists to prevent. Writer and reaper now
    resolve the same directory the same way.
    """
    event = adapter.event_from_payload(payload, assume_kind="session_start")
    if event is None or event.kind not in ("session_start", "session_end"):
        return 0
    code = keel_session.run(event)
    if event.kind == "session_end":
        project = _recording_project(event.cwd, "prompt-log prune", verb="run")
        if project is not None:
            _prune_prompt_logs(project)
    return code


def cmd_prompt(payload: dict[str, Any]) -> int:
    """UserPromptSubmit: preserve one user prompt (T228), and nudge (T473).

    AN OBSERVER, AND THE MOST SENSITIVE ONE KEEL HAS. It emits no decision.
    It DOES emit CONTEXT, on the few turns where a new ten-percent step of the
    context window has just been crossed: ONE plain line recommending
    ``/keel:moor``, which the harness adds to this turn's context for this
    event. That is a change from T228, where this subcommand deliberately
    emitted nothing at all and was registered async - a hook's stdout can only
    become context if the session waits for it, so under Decision A of
    ``.keel/decisions/2026-09-03-the-bl28-window-takes-the-runbook-defaults.md``
    the registration lost its ``async`` flag and every prompt now waits for one
    Python launch. ONE registration does both jobs on purpose: a second
    registration on the same event would charge the always-loaded budget for a
    second copy of the bootstrap to buy the very same launch.

    THE TEXT NEVER TOUCHES DISK UNSCREENED. It is capped at
    ``keel_compaction.PROMPT_CHARS`` and then written through
    ``keel_events._append_jsonl``, the same single chokepoint every audit and
    queue line passes through, which strips ``<keel-private>`` regions,
    collapses this user's home directory to ``~``, screens denied names, and -
    per LINE - refuses to write at all rather than write a line it could not
    screen (R10, convention 5). No second writer, no second screen.

    AN UNADOPTED PROJECT IS UNTOUCHED, which is not a formality here and is
    stricter since T474 than it was before it. The log now lives IN THE PROJECT
    (``<cwd>/.keel/cache/``, Decision B), so this test is what keeps keel from
    creating a ``.keel/`` in a directory that never adopted it - the arming
    model itself (R25) - as well as what keeps one project's prompts out of
    another's. The project is resolved through the ADAPTER, exactly as
    ``cmd_subagent_stop`` resolves it, so a prompt is filed under the same
    project the rest of the session is, and it is handed to BOTH calls below:
    the log they write and the log the nudge reads its step state from are one
    file. The nudge stands inside the same test: a project that never adopted
    keel is not measured and is not spoken to.

    THE ORDER IS DELIBERATE, TWICE OVER. The prompt is recorded FIRST, because
    the record is the thing that has to survive a compaction. Then
    ``keel_compaction.nudge_and_record`` measures, WRITES THE STEP, and only
    then hands back a line to print: this function prints what it is given and
    never decides to speak on its own, because the decision depends on whether
    the step reached disk and only the writer knows that. A nudge keel cannot
    remember having given would be repeated on every following turn - the one
    thing the ratified specification forbids - so a step that could not be
    written costs its nudge, loudly, on stderr (``NUDGE_WITHHELD``).

    THE GUARD around it is the second line of defence, not the first:
    ``nudge_and_record`` never raises by contract, and measuring still means
    reading somebody else's file (the transcript the payload names) on the one
    hook that stands between the user and their own turn.

    Fail-open in every direction: an unwritable log, a payload with no session,
    a project directory that cannot be written, a transcript that cannot be
    read - each is one stderr line from ``keel_compaction`` and exit 0.

    AND THE PROJECT IS WALKED UP (T602, BL8's residue). The adapter answers
    ``CLAUDE_PROJECT_DIR``, else the payload's ``cwd``, else the process cwd,
    and only the first of those three is a project root - so the flat
    ``(project / KEEL_DIRNAME).is_dir()`` this line used to carry meant a
    session standing in a SUBDIRECTORY preserved NO prompt at all and was never
    nudged, for its whole life. That is the same silence T515 measured in
    ``cmd_subagent_stop``, and it costs the most on the one hook whose record
    exists to survive a compaction. The walk cannot widen where keel writes: it
    only ever returns a directory that ALREADY carries ``.keel/``, so an
    unadopted tree still answers None and no ``.keel/`` is created (R25).
    """
    project = _recording_project(adapter.project_dir(payload), "the user prompt")
    if project is None:
        return 0
    session = _payload_session(payload)
    keel_compaction.record_prompt(session, payload.get("prompt"), project)
    try:
        outcome = keel_compaction.nudge_and_record(
            session, _payload_text(payload, "transcript_path"), project
        )
        if outcome.line:
            print(outcome.line)
    except Exception as exc:  # noqa: BLE001 - the nudge may never cost the turn
        print(f"keel: context nudge skipped: {_fault_text(exc)}", file=sys.stderr)
    return 0


def cmd_precompact(payload: dict[str, Any]) -> int:
    """PreCompact: record WHERE this session's ground truth is, before it goes.

    One line in the permanent compaction ledger - the timestamp, the session,
    the project and the transcript path the harness named - and nothing else.
    The transcript itself is neither read nor copied: it is the harness's file,
    it can be tens of megabytes, and the recovery a compacted session needs is
    a POINTER to it, not a second copy of it.

    THE PROJECT IS RECORDED FOR TWO REASONS NOW. It was always the join that
    survives a session-id rotation; since T474 it is also the only thing that
    tells the recovery block WHICH project's prompt log to re-supply from, the
    log having moved out of the user-global directory and into the project.

    The ledger is never pruned, which is a deliberate asymmetry with the
    per-session prompt logs: a prompt log is worth exactly as much as the
    session it belongs to and is pruned at SessionEnd after
    ``keel_compaction.PROMPT_LOG_KEEP_DAYS`` days, while the ledger is the
    index that says where every session's lossless record went, and an index
    that forgets is not one.

    An observer: no decision, nothing on stdout, exit 0 whatever happens, and
    an unadopted project untouched - the same three properties ``cmd_prompt``
    has, except that ``cmd_prompt`` now has one line of stdout to say (T473).

    THE PROJECT IS WALKED UP (T602, BL8's residue), for the reason
    ``cmd_prompt`` gives and one more that is particular to this hook: the
    ledger line this writes is the ONLY pointer a compacted session has back to
    its own lossless transcript, and it is also what tells the recovery block
    WHICH project's prompt log to re-supply from. A subdirectory session that
    silently filed no ledger line lost both at once - and lost them at exactly
    the moment the context that would have revealed the loss was thrown away.
    """
    project = _recording_project(adapter.project_dir(payload), "the compaction pointer")
    if project is None:
        return 0
    keel_compaction.record_compaction(
        _payload_session(payload),
        project,
        _payload_text(payload, "transcript_path"),
    )
    return 0


#: The audit wire value for a delegation that STOPPED. Not this file's to
#: rename: the CONSUMER predates the producer below by several waves -
#: ``keel_stop.session_has_open_handoff`` branches on exactly this string, and
#: ``scripts/keel_attest.py`` reconciles on it - so the value is a contract
#: with them. Its two siblings in the delegation family are
#: ``keel_capture.HANDOFF_OPEN_EVENT`` and ``HANDOFF_CLOSE_EVENT``; this is
#: the third, and the only one of the three that reports an ending rather
#: than a launch or a launch tool's return.
SUBAGENT_STOP_EVENT = "subagent_stop"


#: THE FOUR SPELLINGS A SUBAGENT'S OWN FINAL TEXT MAY ARRIVE UNDER, IN
#: PRECEDENCE ORDER. ``last_assistant_message`` is what the harness's own
#: hooks reference names for a ``SubagentStop`` payload; the three behind it
#: are what the predecessor hook (see ``session_transcript`` below) fell back
#: to, with a comment that the schema "varies across versions". That same
#: documentation is demonstrably wrong about ``transcript_path`` - see the
#: measurement in ``cmd_subagent_stop`` - so this order is read DEFENSIVELY
#: rather than trusted because a reference document names one field: the
#: first present, non-blank candidate wins, and a version that ships none of
#: the four is read as carrying no summary at all rather than as a schema
#: this subcommand does not understand.
AGENT_SUMMARY_KEYS: tuple[str, ...] = (
    "last_assistant_message",
    "summary",
    "result",
    "output",
)


def _agent_summary(payload: dict[str, Any]) -> str | None:
    """The subagent's own final text, bounded and one line, or None.

    THE FIRST PRESENT, NON-BLANK CANDIDATE WINS (``AGENT_SUMMARY_KEYS``).
    ``_payload_text`` already answers None for a key that is absent, blank,
    or not a string - the same normalisation ``agent_type`` gets - so a
    candidate this loop skips is a candidate the payload did not usably
    supply, never a value this function invents around.

    NO TRANSCRIPT IS EVER READ TO BUILD ONE. The measurement in this
    function's caller - 48 stops against 26 launches in one session, 440 to
    176 over this project's whole history - is exactly why: a summary
    manufactured by reading the transcript this subcommand already points at
    (``session_transcript``) would pay that cost on every stop, and most
    stops are not delegation finishes at all. This function reads only the
    payload the harness already handed the hook.

    BOUNDED THE SAME WAY A PROMPT IS, through the SAME helper rather than a
    second cap (R15): ``keel_compaction.capped`` collapses the text to one
    line (``keel_compaction.one_line``) and cuts it at
    ``keel_compaction.PROMPT_CHARS`` - 300 characters, applied here before the
    write-time screen for the same reason ``PROMPT_CHARS`` is applied before
    that screen for a prompt: the screen can only shorten a value further, so
    capping first keeps the result within the cap afterwards. A cut value
    never reads as the whole answer - ``capped`` appends
    ``keel_compaction.PROMPT_TRUNCATION_NOTE`` when it truncates, exactly the
    note a truncated prompt carries (R34: nothing is dropped silently at a
    cap).

    Not wrapped in its own ``try``: a broken ``keel_compaction`` costs this
    subcommand's whole line rather than a silently unbounded field, through
    the ``try`` that already wraps every write ``cmd_subagent_stop`` makes -
    the same fail-open-per-session, never-per-field policy that function
    already declares.
    """
    for key in AGENT_SUMMARY_KEYS:
        value = _payload_text(payload, key)
        if value is not None:
            # PROVEN BY BREAKING IT (convention 15, 2026-09-04): with this
            # line reading ``return keel_compaction.one_line(value)`` instead
            # - the collapse without the cap - the case-4 fixture in
            # tests/test_keel_subagent_stop_agent_summary.py
            # (``TestATruncatedSummarySaysSo.test_the_cut_carries_the_
            # truncation_note``) FAILED with ``AssertionError: False is not
            # true : a truncated value must say so, never cut silently (R34):
            # zzz...zzz`` (400 raw "z" characters, no truncation note - the
            # long fixture was written WHOLE rather than cut at
            # ``PROMPT_CHARS``). Restored to ``keel_compaction.capped(value)``
            # and re-run green in the same session.
            return keel_compaction.capped(value)
    return None


def cmd_subagent_stop(payload: dict[str, Any]) -> int:
    """SubagentStop: record that a delegation stopped. One line, no pairing.

    A STOP IS NOT A DELEGATION, and nothing here may come to assume it is.
    A backgrounded agent stops every time it has no live child, and it can be
    resumed afterwards, so one delegation yields one stop, or three, or none
    at all. The measurement in
    ``.keel/knowledge/keel-never-subscribes-to-subagent-stop.md`` found 48
    stops against 26 launches in a single session; over this project's whole
    history the ratio is 440 to 176. So this subcommand does not count stops
    as delegations, does not de-duplicate them, and does not treat a second
    stop naming the same agent as a mistake to suppress: every stop the
    harness reports becomes one line, in arrival order. A reader who
    reintroduces a uniqueness assumption here will silently lose most of the
    record.

    NO PAIRING IS ATTEMPTED, deliberately. This is the PRODUCER; the consumer
    is ``keel_stop.session_has_open_handoff``, which has branched on
    ``subagent_stop`` since long before anything emitted one. A stop that
    arrives for a delegation this session never launched - a resumed agent, a
    harness that reports one keel never saw start, a session whose launch
    lines predate keel's adoption - is therefore RECORDED rather than dropped:
    the audit log is what happened, not what this hook could explain. No
    launch is looked up, matched, or invented to receive it, and whether the
    launch side can be made to carry a key this payload also carries is a
    separate question with a separate answer.

    WHAT IS RECORDED, and nothing beyond it: the session, the two identity
    fields the payload itself carries (``agent_id``, ``agent_type``), the
    transcript path it also carries, and now ``agent_summary`` - each
    normalised by ``_payload_text`` (and, for the last, also bounded - see
    ``_agent_summary``) so an omitted or blank value is recorded as null
    rather than as an invented one - ``agent_type`` arrives blank often
    enough that treating "" as a type would poison every reader. ``v`` and
    ``ts`` are stamped by ``keel_events``.

    THE TRANSCRIPT FIELD IS NAMED ``session_transcript``, NOT AFTER THE
    PAYLOAD KEY IT COMES FROM, and the rename is the measurement (T228). The
    payload's own key is ``transcript_path``, and a second recorder of this
    same event on this machine - a hook outside this repository, which archives
    it under a comment claiming it is "the subagent's own transcript path" -
    holds 2,680 stop records across 114 sessions in which EVERY path's file
    name is the PARENT SESSION's id, never the agent's. So the field is the
    session transcript, one per session and shared by every stop in it, and
    recording it under the payload's name would have shipped that same false
    claim into keel's log. What it is good for is exactly what the compaction
    layer needs it for: a delegation's audit line now says where the lossless
    text of the turn that launched it lives, which survives a compaction that
    the turn itself does not. It is a home path by construction and reaches
    disk collapsed to ``~``, like every other value, through the write-time
    screen in ``keel_events._append_jsonl``.

    ``agent_summary`` IS THE ONE FIELD THIS SUBCOMMAND ADDS BEYOND IDENTITY
    AND POINTER (BL28 runbook task 3, function 5), and it is read exactly as
    defensively as the caution above about ``session_transcript`` demands:
    the harness's own hooks reference names ``last_assistant_message`` as the
    agent's final assistant text, but that same document is demonstrably
    wrong about a sibling field, so no name here is trusted merely because a
    reference document gives it. ``_agent_summary`` therefore tries FOUR
    spellings in order - ``last_assistant_message``, then ``summary``, then
    ``result``, then ``output`` (``AGENT_SUMMARY_KEYS``), the same fallback
    order and the same "schema varies across versions" caution the
    predecessor hook carried - and records the first one the payload actually
    supplies, non-blank, as a string. NO TRANSCRIPT IS EVER READ TO BUILD ONE:
    the measurement two paragraphs up is exactly why keel does not pay that
    cost on every stop. THE VALUE IS BOUNDED AT ``keel_compaction.PROMPT_CHARS``
    (300), not the predecessor's 1000: this field is a POINTER for the audit
    reader, not the record itself - the lossless text is what
    ``session_transcript`` already names - so it does not need the
    predecessor's budget, and a cut value says so through the same
    ``PROMPT_TRUNCATION_NOTE`` a truncated prompt carries (R34, R15; see
    ``_agent_summary``).

    A PAYLOAD NAMING NO SESSION IS NOT RECORDED, and this is the one thing
    this subcommand refuses to write rather than a hole in "record, never
    drop". Every reader of this log keys on the session first - the stop gate
    filters by it, ``keel attest`` groups by it, the viewer scopes by it - so
    a stop with a null session is a line no reader can use and no later pass
    can repair, appended forever to a record that is never rewritten. It is
    also what an EMPTY payload looks like: ``_read_payload`` answers ``{}``
    for unparseable stdin by design, and an observer that treated that as an
    event would manufacture a delegation-finish out of a broken pipe. The
    condition is reported on stderr rather than passed over in silence
    (convention 7), and the project is left exactly as it was.

    WHY THERE IS NO ``KeelEvent`` HERE. A SubagentStop payload normalises to
    none of the six kinds in ``keel_events.EVENT_KINDS``: it names no tool, no
    path and no command, and it is not the ``Stop`` this session's gate
    accounts for. Adding a seventh kind is a kernel-contract change, which
    subscribing to an event does not need, so this subcommand builds its own
    record from the payload exactly as ``cmd_spike`` does - and, like every
    other writer, hands it to ``append_audit``, which redacts at the single
    write-time chokepoint in ``keel_events._append_jsonl``. No second writer
    and no second redaction path is introduced here (convention 5). No new
    event KIND is introduced for ``agent_summary`` either, for the same
    reason: it is one more field on the same record, not a new subscription.

    The project is resolved through the ADAPTER rather than ``_payload_cwd``:
    ``keel_capture`` writes the launch lines through the same resolution, and
    a stop that landed in a different project's log from the launch it belongs
    to would be worse than no stop at all.

    AND THEN WALKED UP, WHICH IS THE HOLE T515 FOUND LAST AND THE ONLY ONE OF
    ITS SITES THAT WAS COSTING LIVE EVENTS. The adapter answers
    ``CLAUDE_PROJECT_DIR``, else the payload's ``cwd``, else the process cwd -
    and only the FIRST of those three is a project root. The other two follow
    the shell. Asking ``(project / KEEL_DIRNAME).is_dir()`` of that answer and
    returning 0 meant that a session whose harness supplied no
    ``CLAUDE_PROJECT_DIR``, standing in a SUBDIRECTORY, dropped every
    ``subagent_stop`` line it produced - the one event this file's own header
    calls the thing keel promises not to lose, and the same event the
    2026-09-02 append race cost one of. ``_recording_project`` answers the
    project instead, through the record walk every other writer now uses, and
    says so on stderr when it cannot.

    Failure policy, in both directions. Per SESSION, fail-open: an unwritable
    log, an unexpected payload shape, a redactor that cannot resolve a home -
    each is one stderr line and exit 0, because keel observing a delegation
    must never be able to stop one from ending (convention 7: reported, never
    silent). Per LINE, fail-closed, and that half is inherited rather than
    re-implemented: ``_append_jsonl`` does not wrap its own screen, so a line
    that cannot be redacted is not written at all instead of being written
    unscreened. An unadopted project is left untouched, ``.keel/`` and all.
    """
    try:
        project = _recording_project(
            adapter.project_dir(payload), SUBAGENT_STOP_EVENT
        )
        if project is None:
            return 0
        session = _payload_session(payload)
        if session is None:
            print(
                "keel: subagent_stop not recorded: the payload names no session",
                file=sys.stderr,
            )
            return 0
        append_audit(
            project,
            {
                "event": SUBAGENT_STOP_EVENT,
                "session": session,
                "agent_id": _payload_text(payload, "agent_id"),
                "agent_type": _payload_text(payload, "agent_type"),
                "session_transcript": _payload_text(payload, "transcript_path"),
                "agent_summary": _agent_summary(payload),
            },
        )
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: subagent_stop not recorded: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return 0


# ------------------- what the LAUNCHER does when a gate's own code raises
#
# The ruling this section implements:
# ``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``. Until
# it was ratified, an exception escaping ANY subcommand exited 0 - an allow -
# and that contract could not both be true and let ``keel_stop`` declare
# FAIL-CLOSED WHEN ARMED, because the stop gate does not own its own exit code.
# The stop gate's declaration won. Everything below is the launcher's half:
# armed -> the gate's own deny, unarmed -> the allow it always was, the session
# ledger the one crash-time write, and "keel cannot tell" -> deny.

#: The two subcommands the ruling covers. Everything else here is an OBSERVER
#: (``spike``, ``capture``, ``session``, ``subagent_stop``, ``prompt``,
#: ``precompact``): an observer's
#: crash decides nothing, so it keeps the fail-open this file has always
#: declared - keel watching a session must never be able to break it.
GATED_SUBCOMMANDS: tuple[str, ...] = ("gate", "stop")

#: The event kinds each gated subcommand actually decides, mirroring
#: ``cmd_gate`` and ``cmd_stop``'s own guards. THE CRASH PATH RE-CHECKS THIS:
#: a fault raised over a payload the subcommand would have passed untouched
#: (a ``Read``, a ``Task``) may not become a refusal of that payload.
_GATED_KINDS: dict[str, tuple[str, ...]] = {
    "gate": ("pre_write", "pre_exec"),
    "stop": ("stop",),
}

#: ``KEEL_GATE`` values that stand the gate down. ``keel_gate.env_off`` is the
#: reader everywhere in keel and is PREFERRED here too (see
#: ``_kill_switch_off``); this set is the fallback for the one case where that
#: module is the thing that failed to import. Clause 4 of the ruling makes
#: ``KEEL_GATE=off`` the human unfreeze, so it has to answer even then - an
#: escape hatch that stops working during the crash it exists for is not one.
_KEEL_GATE_OFF_VALUES = frozenset(("off", "0", "false", "no"))

#: ``.keel/plans/`` as one path-segment run, forward slashes, for the inline
#: carve-out below. Separators on both sides so ``.keel/plansomething`` is not
#: a ledger path - the same reasoning as ``keel_gate._PLANS_SEGMENTS``, which
#: is the authority whenever it can be reached.
_INLINE_PLANS_SEGMENT = "/.keel/plans/"

#: NEVER REFUSE THE SAME SESSION'S TURN-END TWICE INSIDE THIS WINDOW (seconds),
#: when it is a CRASH doing the refusing. Deliberately the same 180 as
#: ``keel_stop.MARKER_TTL_SECONDS`` - one behaviour, one duration - but its own
#: constant rather than a read of that one, because the module holding it is
#: exactly what may have failed to import, and a loop brake that needs the
#: broken module is not a brake.
CRASH_MARKER_TTL_SECONDS = 180

#: The crash marker's filename prefix. ITS OWN FILE, never ``keel_stop``'s
#: ``keel_stop_<session>``, because the two record different facts - "this gate
#: blocked" and "this gate CRASHED" - and one file for both would let either
#: one suppress the other's first and only refusal.
_CRASH_MARKER_PREFIX = "keel_hook_crash_stop_"

#: Characters allowed in a marker filename derived from a session id, mirroring
#: ``keel_stop._MARKER_SAFE_RE``. The dot is deliberately NOT allowed: a session
#: id is a payload value, and ``../x`` may not survive into a filename (R5).
_CRASH_MARKER_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]")

#: THE DENY OF LAST RESORT: the gate crashed AND armed-ness itself could not be
#: established, because the module that answers that question is the module
#: that broke. UNVERIFIABLE IS DENY (R3, and clause 1 of the ruling read
#: together with clause 3: fail-open follows a project PROVEN unarmed, never a
#: project keel could not ask about). ``keel_stop.STOP_DOUBLE_FAULT`` is this
#: sentence's sibling and is deliberately NOT reused: it lives in a module that
#: may be exactly what is missing, and when it IS importable this path is not
#: reached at all - the gates' own ``_cannot_evaluate`` / ``_cannot_account``
#: handle an undeterminable project themselves, and they are called first.
LAUNCHER_CANNOT_DECIDE = (
    "KEEL {gate} FAILED CLOSED: keel's own launcher could not run this "
    "{subcommand} hook AND could not establish whether this project is armed "
    "({fault}). UNVERIFIABLE IS DENY: the module that answers 'is this project "
    "armed' is the module that failed, and an armed project must not be waved "
    "through because keel broke. THE FAULT IS KEEL'S OWN, NOT THIS PROJECT'S "
    "CONFIGURATION - do not edit this project's files on the strength of this "
    "message. NEXT STEP: keel's hooks must be restored from git by the USER, "
    "from outside this session; landing the replacement as ONE write of the "
    "complete file, because a multi-location edit applied across two tool calls "
    "is what leaves this state. Or the USER may set KEEL_GATE=off to stand the "
    "gate down deliberately. NOTE: .keel/plans/ stays writable, so this can be "
    "recorded in the session ledger. Nothing else is."
)

#: The head word each gated subcommand uses in that sentence, so the launcher
#: says "KEEL GATE" / "KEEL STOP" exactly as the gate itself would.
_CRASH_HEAD: dict[str, str] = {"gate": "GATE", "stop": "STOP"}


def _module(name: str) -> Any:
    """A keel module that imported cleanly, or None. Never raises.

    ``globals().get`` rather than a re-import: the guarded block at the top of
    this file has already tried, and a module that failed there fails the same
    way again - re-parsing a broken file during a crash buys nothing and can
    only add a second fault to explain.
    """
    return globals().get(name)


def _fault_text(exc: BaseException) -> str:
    """One bounded line naming a fault, whatever the exception does.

    ``keel_faultlog.summarise`` when it is available, because the error log and
    the refusal must quote the same text; the plain interpolation when it is
    not; and a fixed sentence when even ``str(exc)`` raises. Never raises: this
    is called on the path that exists because something already did.
    """
    log = _module("keel_faultlog")
    if log is not None:
        try:
            return log.summarise(exc)
        except Exception:  # noqa: BLE001 - fall through to the plainest reading
            pass
    try:
        return f"{type(exc).__name__}: {exc}"
    except Exception:  # noqa: BLE001 - nothing left to name it with
        return "an exception that could not describe itself"


def _log_hook_error(subcommand: str, exc: BaseException, kind: str | None = None) -> None:
    """One line in the user-global hook-error log (T235). Never decides.

    THE WRITE MAY NOT REACH THE VERDICT, in either direction: it happens after
    the exit code is already determined, it is wrapped here as well as inside
    ``keel_faultlog.record`` (which never raises by contract), and its return
    value is discarded. A log that cannot be written costs a stderr line, never
    a decision.
    """
    log = _module("keel_faultlog")
    if log is None:
        return
    try:
        log.record(subcommand, exc, kind)
    except Exception:  # noqa: BLE001 - a counter may never change what it counts
        pass


def _deny_exit_code() -> int:
    """Exit 2, from keel's ONE exit table (R6) whenever it can be read.

    The literal is the fallback for a ``keel_events`` that did not import - the
    same reasoning as ``_KEEL_GATE_OFF_VALUES``, and the reason the constant is
    consulted first: two spellings of the deny code must never be able to
    disagree while the table exists to be read.
    """
    try:
        return DECISION_EXIT_CODES["deny"]
    except Exception:  # noqa: BLE001 - the table itself is missing
        return 2


def _kill_switch_off(env: dict[str, str] | None = None) -> bool:
    """True when the user stood the gate down with ``KEEL_GATE=off``.

    ``keel_gate.env_off`` first, so the switch means exactly what it means
    everywhere else; the inline reading only when that module is unavailable.
    Never raises: an unreadable environment is not an unfreeze.
    """
    environ = os.environ if env is None else env
    gate = _module("keel_gate")
    if gate is not None:
        try:
            return bool(gate.env_off("KEEL_GATE", environ))
        except Exception:  # noqa: BLE001 - fall through to the inline reading
            pass
    try:
        return (environ.get("KEEL_GATE") or "").strip().casefold() in _KEEL_GATE_OFF_VALUES
    except Exception:  # noqa: BLE001 - no readable switch is not a stood-down gate
        return False


def _crash_event(subcommand: str, payload: dict[str, Any]) -> tuple[Any, str]:
    """``(event, state)`` for a crashed gate call, without trusting anything.

    ``state`` is one of three answers, kept apart because they take three
    different outcomes:

    * ``"event"`` - the payload rebuilt into the event the gate was judging,
      so the gate's own failure policy can be asked about it.
    * ``"ungated"`` - the payload maps to a kind this subcommand does not
      decide, so nothing about it is refused: the crash happened over a tool
      call keel was never going to gate. TWO WAYS TO REACH THIS, and they are
      the same fact: the adapter returned an event of an ungated kind, or it
      returned ``None``, which is how the adapter SAYS "this payload is no
      keel event at all" (a ``Read``, a ``Task``, a ``WebFetch``). A ``None``
      used to be answered ``"unknown"`` here - a deny - which read the
      adapter's clearest answer as its absence; the mistake was latent only
      because the gate's own tool matcher screens those payloads out upstream
      (freeze record section 3).
    * ``"unknown"`` - the event could not be rebuilt AT ALL, which is a
      different sentence: the adapter module never imported, or it RAISED, so
      keel holds no opinion about this payload rather than the opinion "not
      mine". ARMED-NESS IS THEN UNDETERMINABLE, which the ruling answers with
      a deny.
    """
    adapter_mod = _module("adapter")
    if adapter_mod is None:
        return None, "unknown"
    try:
        event = adapter_mod.event_from_payload(
            payload, assume_kind="stop" if subcommand == "stop" else None
        )
    except Exception:  # noqa: BLE001 - an unrebuildable event is its own state
        return None, "unknown"
    if event is None:
        # A RETURN, not a raise: the adapter ran and reported that this payload
        # maps to no gated event. ``cmd_gate`` and ``cmd_stop`` pass exactly
        # this case through untouched, and the crash path may not be stricter
        # than the path it stands in for.
        return None, "ungated"
    try:
        kind = event.kind
    except Exception:  # noqa: BLE001 - an event that cannot say what it is
        return None, "unknown"
    if kind not in _GATED_KINDS.get(subcommand, ()):
        return None, "ungated"
    return event, "event"


def _crash_fault_kind(event: Any, exc: BaseException) -> str:
    """``module`` / ``configuration`` / ``unknown`` for the error log.

    ``keel_gate._crash_fault_label`` is THE classifier - the same one the audit
    line and both gates' refusals use - so it is called rather than re-derived
    (R15) and this log can never name a different kind from the record beside
    it. It needs a project to ask about the arming file, so when there is no
    event to take one from, the COARSER classifier answers instead
    (``keel_faultlog.fault_kind``, which asks ``gate_self_fault`` alone and can
    therefore say ``module`` but never ``configuration``). ``unknown`` when
    neither is available, which is honest: the fault is still counted and still
    quoted, and a guessed kind would send a reader to the wrong repair.
    """
    gate = _module("keel_gate")
    if gate is not None and event is not None:
        try:
            kind, _source, _named = gate._crash_fault_label(
                event.cwd, os.environ, gate.gate_self_fault(exc)
            )
            return str(kind)
        except Exception:  # noqa: BLE001 - fall through to the coarser answer
            pass
    log = _module("keel_faultlog")
    if log is not None:
        try:
            return str(log.fault_kind(exc))
        except Exception:  # noqa: BLE001 - a classification may never fail the verdict
            pass
    return "unknown"


def _inline_ledger_carve_out(subcommand: str, payload: dict[str, Any]) -> int:
    """How many ``.keel/plans/`` targets this payload has, or 0 - the ONE
    crash-time allow, spelled out here because the module that owns it is gone.

    THE ONE PERMITTED DUPLICATION IN THIS FILE, and the justification is the
    condition itself: ``keel_gate.crash_ledger_carve_out`` is the authority and
    IS called whenever it can be - ``_cannot_evaluate`` asks it before anything
    else, and the crash path above reaches that function first. This inline
    equivalent runs only when ``keel_gate`` (or the adapter that builds the
    ``KeelEvent`` it takes) is the thing that failed to import, so there is no
    function to call and no event to pass it. Clause 2 of the ruling keeps the
    ledger writable while the gate cannot evaluate, and a crash that cannot
    even import keel is precisely when a session most needs to record that it
    is stuck; a carve-out that depended on the broken module would be no
    carve-out at all.

    NARROWER THAN THE ORIGINAL, deliberately, because it has none of that
    module's resolution machinery: ``gate`` only (a Stop writes nothing, and a
    shell command's targets cannot be established without the scanner), a
    write tool's own payload keys only, EVERY target must carry the
    ``.keel/plans/`` segment, one that does not refuses the whole payload, and
    an empty target list is not a carve-out. A COUNT is returned rather than
    the paths: this function has no redactor to hand and a target is a
    filesystem path, so it never reaches a message (convention 5). Never
    raises - doubt here fails closed, the opposite direction to the gate as a
    whole, exactly as ``crash_ledger_carve_out`` documents.
    """
    if subcommand != "gate":
        return 0
    try:
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict):
            return 0
        candidates: list[str] = []
        sources: list[dict[str, Any]] = [tool_input]
        edits = tool_input.get("edits")
        if isinstance(edits, list):
            sources.extend(edit for edit in edits if isinstance(edit, dict))
        for source in sources:
            for key in ("file_path", "notebook_path", "path"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value)
        if not candidates:
            return 0
        for value in candidates:
            # TRAVERSAL IS COLLAPSED BEFORE THE SEGMENT TEST, and this order is
            # the whole safety of the function. Without it
            # ``.keel/plans/../../hooks/keel_gate.py`` CARRIES the ledger
            # segment while TARGETING a gate module, so a crash-time write
            # could have edited keel's own hooks through the one carve-out a
            # crash is allowed - the defect found while frozen and recorded in
            # ``.keel/plans/keel-freeze-2026-08-21-3fbfa431.md`` section 3.
            # ``keel_gate.crash_ledger_carve_out`` is immune because it calls
            # ``norm()`` first; this inline equivalent has no resolver, so
            # ``normpath`` is the lexical equivalent - it needs no filesystem
            # and cannot raise on a path that does not exist.
            #
            # Separators on BOTH ends, and both spellings folded to ``/`` on
            # both sides of ``normpath`` (which re-spells them as ``\`` on
            # Windows): the payload's path may be relative
            # (``.keel/plans/x.md`` - what a session actually writes) or
            # absolute, and there is no resolver here to tell them apart. The
            # bracketing slashes are what make this a SEGMENT test rather than
            # a substring one, so ``notes.keel/plans/`` is not a ledger path
            # and neither is a file merely named like one.
            folded = os.path.normpath(value.replace("\\", "/")).replace("\\", "/")
            probe = "/" + folded.casefold().strip("/") + "/"
            if _INLINE_PLANS_SEGMENT not in probe:
                return 0
        return len(candidates)
    except Exception:  # noqa: BLE001 - doubt about a loosening fails closed
        return 0


def _crash_marker_path(session: str | None) -> Path:
    """Where the crashed-stop marker for one session lives. Never trusted.

    The session id is a payload value, so it is reduced to filename-safe
    characters before it becomes one, exactly as ``keel_stop.marker_path``
    does - no payload may steer a path (R5). May raise (``gettempdir`` is a
    filesystem question); every caller guards it.
    """
    safe = _CRASH_MARKER_SAFE_RE.sub("_", (session or "unknown"))[:64] or "unknown"
    return Path(tempfile.gettempdir()) / f"{_CRASH_MARKER_PREFIX}{safe}"


def _stop_loop_guard(payload: dict[str, Any]) -> str:
    """Why a crashed ``stop`` may NOT refuse this turn-end, or "" when it may.

    THE STOP GATE'S TWO LOOP BRAKES, RE-STATED FOR THE CRASH PATH, and the
    duplication is forced rather than chosen: both of them live inside
    ``keel_stop.evaluate`` (``stop_hook_active``, then ``marker_is_fresh``),
    which is the function that just raised or the module that never imported.
    So on the crash path neither ran, and the freeze of 2026-08-21 MEASURED
    what that costs: a stop that denies without a brake refuses the turn-end,
    the harness re-runs the hook, the same broken module raises again, and the
    session cannot end at all. Clause 4's human unfreeze is not an answer to
    that, because the human is trying to type into a session whose every turn
    is being refused by a loop.

    A DENY THAT FIRES ONCE IS THE RULING; a deny that fires forever is a trap.
    The first crashed stop in a window refuses and says so (the record is
    written, the fault is named, the session is stopped from ending
    unaccounted); a second one inside ``CRASH_MARKER_TTL_SECONDS`` passes. The
    asymmetry the ruling rests on still holds: the cost is one unaccounted
    turn-end, visible in the audit log and in the hook-error log, against a
    session that could otherwise never be repaired from inside itself.

    Two independent reasons, each in its own guard so a fault in one cannot
    hide the other, and BOTH failing means the loop guard simply does not fire
    (doubt here fails CLOSED - back to the deny the ruling asks for):

    * ``stop_hook_active`` in the payload - the harness itself saying it is
      re-entering this hook. Authoritative, and free.
    * a fresh marker file of this launcher's own, written by
      ``_touch_crash_marker`` after any crashed stop that actually blocked.
    """
    try:
        if payload.get("stop_hook_active"):
            return "stop_hook_active: the harness says it is re-entering this hook"
    except Exception:  # noqa: BLE001 - an unreadable payload is not a loop
        pass
    try:
        path = _crash_marker_path(_payload_session(payload))
        if path.is_file() and (time.time() - path.stat().st_mtime) < CRASH_MARKER_TTL_SECONDS:
            return (
                f"a crashed stop hook already refused this session's turn-end "
                f"less than {CRASH_MARKER_TTL_SECONDS}s ago; never twice in a row"
            )
    except Exception:  # noqa: BLE001 - no readable marker is not a loop
        pass
    return ""


def _touch_crash_marker(payload: dict[str, Any]) -> None:
    """Record that a crashed ``stop`` just refused this session. Never raises.

    Called AFTER the exit code is final, like ``keel_stop.touch_marker``, so an
    escape here could only destroy a verdict that is already correct. A marker
    that cannot be written costs one stderr line and the guarantee above - the
    next crashed stop would refuse again - which is worth saying out loud
    rather than swallowing (convention 7).
    """
    try:
        _crash_marker_path(_payload_session(payload)).write_text("", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - reported, never silent, never fatal
        print(
            f"keel: the crashed-stop marker could not be written, so a second "
            f"refusal of this turn-end is possible: {_fault_text(exc)}",
            file=sys.stderr,
        )


def _stop_marked(subcommand: str, payload: dict[str, Any], code: int) -> int:
    """Pass a crash exit code through, marking a BLOCKING stop on the way out.

    One place, so the marker cannot be forgotten on one of the two deny paths
    (``_emit_crash_verdict`` and ``_deny_without_a_gate``) and thereby leave
    half a loop guard. Only a blocking code marks: an allow starts no loop.
    """
    if code and subcommand == "stop":
        _touch_crash_marker(payload)
    return code


def _audit_launcher_deny(
    subcommand: str, payload: dict[str, Any], exc: BaseException, fault: str
) -> None:
    """One ``launcher_crash_deny`` line, when there is a log to put it in.

    Clause 5 of the ruling - every crash-deny is audited with its fault kind,
    so repeated crashes are a visible number. This path has no gate module to
    file the line the way ``_audit`` would, so it writes the plainest line it
    can and files it with the session's own directory, ONLY when that directory
    is already keel-bearing: a single ``.is_dir()`` test, never the project
    walk (which is exactly what may have failed), and never a ``.keel/``
    created under a directory that never adopted keel (R25). When there is no
    log, the user-global hook-error log is the whole record - which is what
    T235 exists for. Never raises, and never changes the verdict.

    FLAT-ADOPTION EXEMPT (T602). This is the ONE flat ``.keel/`` test in the
    launcher that the record walk must not replace, and the paragraph above is
    the reason rather than an excuse: this function runs only after a
    subcommand has ALREADY crashed, and ``keel_events`` - the module the walk
    lives in - is one of the things that may have crashed. A handler of last
    resort that called into the suspect code to decide where to file the
    suspicion could take the crash-deny down with it, and the crash-deny is the
    only in-project trace the ruling's clause 5 demands. The cost is bounded
    and known: a crash in a session standing in a SUBDIRECTORY files no
    in-project line, and the user-global hook-error log still has it.
    ``tests/test_keel_flat_adoption_sweep_t602.py`` pins this exemption.
    """
    if _module("append_audit") is None or _module("KEEL_DIRNAME") is None:
        # The kernel writer itself never imported, so there is nothing to write
        # with and nothing to say about it that the hook-error log has not
        # already said. Reported by the import guard at the top of this file.
        return
    try:
        cwd = _payload_cwd(payload)
        if not (cwd / KEEL_DIRNAME).is_dir():
            return
        append_audit(
            cwd,
            {
                "event": "launcher_crash_deny",
                "gate": "internal_error",
                "session": _payload_session(payload),
                "detail": {
                    "subcommand": subcommand,
                    "fault": fault,
                    "fault_kind": _crash_fault_kind(None, exc),
                },
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent, never fatal
        print(
            f"keel: launcher_crash_deny audit failed: {_fault_text(exc)}",
            file=sys.stderr,
        )


def _emit_crash_verdict(
    subcommand: str, event: Any, verdict: Any, module: Any, exc: BaseException
) -> int:
    """Record and render a verdict the gate's own failure policy produced.

    THE RECORD FIRST, because clause 5 of the ruling wants every crash-deny
    counted with its fault kind, and this path bypassed ``run``'s own tail (the
    exception escaped it). ``_audit`` and ``touch_marker`` are total functions
    after T208 - neither can raise - and are guarded here anyway: this is the
    handler of last resort and it may not need its own.

    THE RENDERING IS THE ADAPTER'S, not a second one: ``adapter.emit`` is the
    same call ``cmd_gate`` and ``cmd_stop`` make, so the JSON shape and the
    exit code come from ``KeelVerdict.to_exit_code`` exactly as they do on the
    ordinary path (R6). If even that raises, the reason still reaches stderr -
    which is where the harness shows a blocking hook's message - and the exit
    code still says block.
    """
    try:
        if verdict.blocking:
            if subcommand == "stop":
                module.touch_marker(event.session_id)
            module._audit(event, verdict)
    except Exception as inner:  # noqa: BLE001 - the record may not cost the verdict
        print(
            f"keel: the crash verdict could not be audited: {_fault_text(inner)}",
            file=sys.stderr,
        )
    _log_hook_error(subcommand, exc, _crash_fault_kind(event, exc))
    adapter_mod = _module("adapter")
    if adapter_mod is not None:
        try:
            return int(adapter_mod.emit(verdict, event))
        except Exception as inner:  # noqa: BLE001 - reported, never silent
            print(
                f"keel: the crash verdict could not be rendered: {_fault_text(inner)}",
                file=sys.stderr,
            )
    try:
        if verdict.blocking:
            print(verdict.reason, file=sys.stderr)
        return int(verdict.to_exit_code())
    except Exception:  # noqa: BLE001 - a verdict that cannot even be read is a deny
        return _deny_exit_code()


def _deny_without_a_gate(
    subcommand: str, payload: dict[str, Any], exc: BaseException, fault: str
) -> int:
    """The outcome when the gate module itself cannot be asked anything.

    THE ORDER IS THE POLICY, and it is ``keel_gate._cannot_evaluate``'s order,
    kept the same on purpose so the two paths cannot answer one situation two
    ways:

    1. THE KILL SWITCH STILL ANSWERS (clause 4). Every sentence below tells the
       user they may set ``KEEL_GATE=off``; a handler that ignored it would make
       that sentence a lie in the one case where it is the only door left.
    2. THE LEDGER SURVIVES (clause 2), decided from the payload alone.
    3. OTHERWISE DENY (clause 1 with clause 3): unarmed fails open, but this
       branch is reached precisely because nothing could be shown about arming.
    """
    if _kill_switch_off():
        print(
            f"keel: {subcommand} stood down by KEEL_GATE=off while keel's own "
            f"launcher could not decide: {fault}",
            file=sys.stderr,
        )
        _log_hook_error(subcommand, exc)
        return 0
    targets = _inline_ledger_carve_out(subcommand, payload)
    if targets:
        print(
            f"keel: LEDGER WRITE PERMITTED THROUGH A FAILED LAUNCHER "
            f"({targets} target(s), all inside .keel/plans/): keel's own hooks "
            f"could not run ({fault}), and .keel/plans/ is the one directory a "
            f"crash may not freeze - the session has to be able to record this. "
            f"Everything else is refused. The plan contract was NOT asserted on "
            f"this write.",
            file=sys.stderr,
        )
        _log_hook_error(subcommand, exc)
        return 0
    print(
        LAUNCHER_CANNOT_DECIDE.format(
            gate=_CRASH_HEAD.get(subcommand, "GATE"),
            subcommand=subcommand,
            fault=fault,
        ),
        file=sys.stderr,
    )
    _log_hook_error(subcommand, exc)
    _audit_launcher_deny(subcommand, payload, exc, fault)
    return _deny_exit_code()


def gate_crash_exit(subcommand: str, payload: dict[str, Any], exc: BaseException) -> int:
    """The RULED outcome for an exception escaping ``gate`` or ``stop``.

    Five outcomes, in this order, and every one of them is the ruling rather
    than this file's own reading of it:

    (a) THE FAULT IS ALWAYS REPORTED on stderr and always written to the
        user-global hook-error log (T235), whichever way the verdict goes.
    (b) A PAYLOAD THIS SUBCOMMAND DOES NOT GATE is passed untouched. keel
        crashing over a ``Read`` may not refuse the ``Read``.
    (b2) A CRASHED ``stop`` REFUSES A GIVEN TURN-END ONCE, never in a loop -
        ``_stop_loop_guard``, which re-states the two brakes that live inside
        the function that just raised. Measured, not hypothesised: the freeze
        of 2026-08-21 trapped a real session's turn-end.
    (c) THE GATE'S OWN FAILURE POLICY DECIDES whenever it can be asked -
        ``keel_gate._cannot_evaluate`` / ``keel_stop._cannot_account``, called
        rather than re-implemented (R15). Those functions already are the
        ruling: kill switch, then the ``.keel/plans/`` carve-out, then armed ->
        deny with the fault classified, unarmed -> allow. The launcher adds no
        second opinion, and the deny it returns is byte-identical to the one
        the gate would have returned had the exception happened one frame
        earlier.
    (d) A DOUBLE FAULT - the failure policy itself raises - falls through to
        (e) rather than escaping, because an escape is what this whole handler
        exists to stop.
    (e) NO MODULE, NO EVENT, NO ANSWER: ``_deny_without_a_gate``, which keeps
        the kill switch and the ledger carve-out and otherwise denies.
    """
    fault = _fault_text(exc)
    print(f"keel: {subcommand} failed: {fault}", file=sys.stderr)
    if _IMPORT_FAULT:
        print(
            f"keel: and a hook module never imported in this process: {_IMPORT_FAULT}",
            file=sys.stderr,
        )
    event, state = _crash_event(subcommand, payload)
    if state == "ungated":
        print(
            f"keel: {subcommand} failed over a payload it does not gate, so "
            f"nothing is refused",
            file=sys.stderr,
        )
        _log_hook_error(subcommand, exc)
        return 0
    if subcommand == "stop":
        loop = _stop_loop_guard(payload)
        if loop:
            print(
                f"keel: stop failed AND is NOT refusing this turn-end again "
                f"({loop}). The fault stands and is logged; a crashed gate that "
                f"blocked once has made its point, and blocking every retry "
                f"would trap this session instead of guarding it. THIS TURN-END "
                f"IS UNACCOUNTED - keel's hooks need restoring from git by the "
                f"user, from outside this session.",
                file=sys.stderr,
            )
            _log_hook_error(subcommand, exc)
            return 0
    module = _module("keel_gate" if subcommand == "gate" else "keel_stop")
    if event is not None and module is not None:
        verdict = None
        try:
            if subcommand == "gate":
                verdict = module._cannot_evaluate(
                    event, os.environ, fault, module.gate_self_fault(exc)
                )
            else:
                verdict = module._cannot_account(event, exc)
        except Exception as inner:  # noqa: BLE001 - the double fault, handled below
            print(
                f"keel: the gate's own failure policy could not be reached "
                f"either, so the launcher decides: {_fault_text(inner)}",
                file=sys.stderr,
            )
        if verdict is not None:
            return _stop_marked(
                subcommand,
                payload,
                _emit_crash_verdict(subcommand, event, verdict, module, exc),
            )
    return _stop_marked(
        subcommand, payload, _deny_without_a_gate(subcommand, payload, exc, fault)
    )


#: Dispatch table. One entry per hook behaviour; hooks.json passes the key.
SUBCOMMANDS: dict[str, Callable[[dict[str, Any]], int]] = {
    "spike": cmd_spike,
    "gate": cmd_gate,
    "stop": cmd_stop,
    "capture": cmd_capture,
    "session": cmd_session,
    "subagent_stop": cmd_subagent_stop,
    "prompt": cmd_prompt,
    "precompact": cmd_precompact,
}


def main(argv: list[str] | None = None) -> int:
    """Dispatch on argv[1]; return the subcommand's exit code, else 0.

    THE EXCEPTION HANDLER IS NOW PER SUBCOMMAND CLASS (the ratified crash
    ruling): a gate or stop crash goes to ``gate_crash_exit``, which applies
    the gate's own failure policy; an observer's crash is reported and exits 0,
    which is what this file has always done and what it still declares.
    Either way one line lands in the user-global hook-error log (T235), and
    that write can never change the code returned here.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    handler = SUBCOMMANDS.get(args[0]) if args else None
    payload = _read_payload(sys.stdin)
    if handler is None:
        return 0
    try:
        code = handler(payload)
    except Exception as exc:  # noqa: BLE001 - ruled per subcommand, never silent
        if args[0] in GATED_SUBCOMMANDS:
            return gate_crash_exit(args[0], payload, exc)
        print(f"keel: {args[0]} failed: {_fault_text(exc)}", file=sys.stderr)
        _log_hook_error(args[0], exc)
        return 0
    return code if isinstance(code, int) else 0


if __name__ == "__main__":
    sys.exit(main())
