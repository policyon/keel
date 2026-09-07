#!/usr/bin/env python3
"""keel stop-with-accounting gate.

Contract
--------
Reads   : one ``KeelEvent`` of kind ``stop`` - never a harness payload. The
          project that GOVERNS this session - the nearest ancestor of
          ``event.cwd`` carrying an arming file, resolved the same way
          ``keel_gate.resolve_project`` resolves one for a write or a command
          (T178), and NOT necessarily ``event.cwd`` itself (T186: a session
          can be governed by a project it is not sitting in, exactly as a
          write already can be) - supplies:
            ``<root>/.keel/keel-policy.md``               arming file + tier
            ``<root>/.keel/plans/keel-plan-<sess8>.md``   THIS session's ledger
            ``<root>/.keel/backlog.md``    session-independent backlog (T229),
                                            consulted only when the ledger
                                            carries a ``FILED`` claim to verify
          Delegation history is read at ``event.cwd`` itself, deliberately
          NOT re-pointed at ``root`` and deliberately NOT climbing with
          ``keel_capture.recording_root`` either - see
          ``session_has_open_handoff``, which records what happened when the
          climb was tried:
            ``<event.cwd>/.keel/audit/keel-audit.jsonl``  delegation history
          From the environment: ``KEEL_GATE=off`` and ``KEEL_OVERRIDE=on``
          (user-only kill switches), and the temp directory, where a
          per-session marker file makes a second consecutive block impossible.
          When this event blocks, one more file is read for the record rather
          than the verdict: the payload's own ``transcript_path``, through
          ``keel_session.model_from_transcript`` (BL25) - IMPORTED rather than
          re-derived (R15), so the two hooks find the seat's model the same
          way and can never come to disagree about it. That read is the exact
          one ``keel_session`` already makes at ``session_start``: the last
          ``TRANSCRIPT_TAIL_BYTES`` of the transcript, for the newest
          ASSISTANT-marked line's ``message.model``, bounded and best-effort -
          a transcript that is absent, unreadable, empty, malformed, or names
          no assistant line at all leaves the seat null exactly as it did
          before this read existed. Belt-and-braces: this hook also wraps the
          call in its OWN narrow guard (see ``_audit``), so even a fault
          ``model_from_transcript`` did not anticipate costs only this one
          field, never the rest of the ``stop_block`` line.
Emits   : a ``KeelVerdict``. Rendering it is the adapter's job (R6). One
          exception, and it is not a decision: while ``KEEL_OVERRIDE`` is on
          and the verdict allows, one reminder line goes to stderr, where the
          harness shows hook feedback - an allow still emits no JSON and no
          exit code of its own.
Writes  : one ``stop_block`` line to the GOVERNING project's audit log per
          block - carrying, in its ``detail``, both the COUNTS this gate
          computed (``open_items``, ``stale_inflight_items``) and the
          IDENTIFIERS behind them (``open_item_ids``, ``stale_inflight_item_ids``),
          so a block can be read back as "which items", not only "how many"
          (see "What a block records" below), and, since BL25, one top-level
          ``model`` field on that SAME line - the model named on the
          session's own transcript at the moment of the block, through the
          identical reader ``session_start`` uses, or an explicit ``null``
          when the payload named no transcript, the file could not be read,
          or the tail named no assistant line (never a guess) - one
          ``override_active_at_stop`` line per allowed stop taken with the
          override on IN AN ARMED PROJECT, one ``unresolved_project_allowed``
          line (plus a stderr notice) when this session's OWN governing
          project could not be resolved at all - the walk ran out of
          ``PROJECT_WALK_MAX_LEVELS`` parent directories (T186; see
          ``resolve_governing_project``) - plus the loop-safety marker in the
          system temp directory. Nothing at all in a project that never armed
          keel - not the reminder, and therefore not the ``.keel/`` directory
          the reminder's audit line would have created (R25). The other two
          events this gate writes - ``override_active_at_stop`` and
          ``unresolved_project_allowed`` - are UNCHANGED by BL25: only the
          block's own accounting line is the one that was measured carrying
          no answer about the seat at all.
          A GOVERNING PROJECT IS NOT ALWAYS ``event.cwd`` (T186, mirroring
          T178's fix to ``keel_gate.py`` one hook along): a session held to a
          foreign project's ledger has its ``stop_block``/
          ``override_active_at_stop`` lines filed THERE, with a
          ``session_cwd`` field recording, relative to that project, where
          the session was actually standing - the same
          ``detail['project']``-then-``session_cwd`` convention
          ``keel_gate._audit`` already uses (T178), so a reader of either
          project's log finds the same shape. The ordinary case - the
          session's own directory is the governing project, which is every
          fixture that predates this task - stays byte-identical: no
          ``project`` key is ever added there.
Argv    : none. Imported by ``keel_hook.py`` and dispatched as ``stop``.

Exit codes
----------
Via ``KeelVerdict.to_exit_code()``: allow -> 0, deny -> 2 (R6).

The rule
--------
A turn may end only when every item in THIS session's ledger carries a
terminal status: ``[x]`` done, ``[!]`` blocked with a reason, ``[?]`` needs
the user's decision, or ``[~]`` genuinely in flight.

FILING IS ITS OWN VOCABULARY, NOT A FIFTH MARK (T229, ratified by
``.keel/decisions/2026-08-22-a-backlog-is-not-a-plan.md``). Work discovered
but deliberately not started this session is neither blocked (there is no
blocker; nobody is waiting on anything) nor abandoned (nothing was begun and
dropped): it is FILED to the session-independent backlog at
``.keel/backlog.md``. A filed item closes its ledger line ``[x]`` with a
``FILED: BL<n>`` note naming its backlog entry - and THIS GATE VERIFIES THE
NOTE AGAINST THE BACKLOG FILE rather than trusting the prose: a ``[x] ...
FILED: BL<n>`` line whose id is not on record in ``.keel/backlog.md`` is not
accounted for, and blocks the stop exactly as an open item would. That is
the whole mechanism - filing is accounting only when the record backs it,
never by a mark or a sentence alone.

``[~]`` is VERIFIED, NEVER TRUSTED. It passes only when the audit log shows
an OPEN hand-off for this session. Subagents are launched as background
tasks, so ``handoff_end`` fires at LAUNCH, moments after ``handoff_start``;
such a close-together pair is a launch acknowledgment, not a close, and the
hand-off stays open. WHICH IT IS IS READ FROM THE RECORD FIRST (T348): the
close half's own ``background`` field (``HANDOFF_BACKGROUND_KEY``, written by
``hooks/keel_capture.py`` from the launch tool's result ``status``) says so
directly, and is trusted whatever the elapsed time between the two halves -
the elapsed-time guess (``BG_LAUNCH_MS``) survives only as the fallback for a
``handoff_end`` written before that field existed. A background hand-off
closes via a ``subagent_stop`` THAT NAMES IT (``same_agent_id``), or, absent
one, an activity-quiet timeout (``LIVENESS_MS``). A genuine foreground pair
(``background: false``, or - for an older record - an end well after start)
closes directly. With no open hand-off on record, ``[~]`` blocks exactly
like ``[ ]``: it cannot be used to dodge accounting.

A STOP CLOSES THE LAUNCH IT NAMES, AND NOTHING ELSE (T102). The join key is
``agent_id``: the stop payload has always carried it, and the launch tool
returns it, so ``hooks/keel_capture.py`` now records it on the return half of
each delegation and ``launch_agent_id`` follows the ``tool_use_id`` that the
two halves share to reach it. Two records pair when, and only when, they name
the SAME, NON-BLANK id. THERE IS NO FALLBACK, and its absence is the rule
rather than an omission: pairing by agent type and time order attributed a
stop to whichever same-type delegation was launched most recently, which is a
guess whenever two of a kind are running at once, and a type is not an
identity. A stop this log cannot attribute exactly closes nothing at all, and
the hand-off it might have belonged to is left to the activity-quiet timeout.
Absent is reported as absent; it is never approximated.

A LAUNCH PAIRS WITH ITS RETURN BY ``tool_use_id``, AND BY NOTHING ELSE. The
same rule, at the other site: a ``handoff_end`` naming no tool call closes no
``handoff_start``, and a ``handoff_start`` naming none is closed by no return.
That site used to fall back to ``(subagent_type, description)``, which pairs
two records that name NEITHER - the same false match an absent agent type
makes, reached by a different road.

AN ABSENT AGENT TYPE MATCHES NOTHING (``same_agent_type``). A hand-off naming
no type is closed by the activity-quiet timeout alone - never by another
agent's activity. Absence is not a shared identity, and reading it as one
closes a delegation nothing on record spoke about. The predicate remains the
one rule for comparing two recorded agent TYPES, and is still what the
liveness window attributes activity with; it no longer attributes a stop.

What a block records
--------------------
The block message names the items to the model; the audit line now names them
to every later reader too. Six fields, all of them things this gate ALREADY
computed before it denied:

    open_items                int   how many ``[ ]`` items the ledger held
    open_item_ids             list  their identifiers, ledger order
    stale_inflight_items      int   how many ``[~]`` items had no open hand-off
    stale_inflight_item_ids   list  their identifiers, ledger order
    unverified_filed_items      int   how many ``[x] ... FILED: BL<n>`` notes
                                      named a backlog id this gate could not
                                      verify (T229)
    unverified_filed_item_ids   list  their identifiers, ledger order

The names are keel's own vocabulary for keel's own computation - the two
original counts have been on this line since the gate was written, and every
list is named after the count beside it rather than after another tool's
schema. An identifier is the item's leading task id (``T130``) where it has
one and a bounded head of its text where it does not (``item_identifier``),
because a count alone cannot be looked up and an unlabelled item is precisely
the one nobody can find. Each list is capped at ``MAX_ITEM_IDS`` while the
count beside it stays the true total, so truncation is READ off the line
rather than hidden in it (convention 7).

Additive: every field that was on a ``stop_block`` line before is still on it,
unchanged, and a reader of the older lines sees exactly what it always did.

Arming
------
RESOLVED THE SAME WAY ``keel_gate.py`` RESOLVES A WRITE'S TARGET (T178), one
hook along (T186): enforcement is decided by the NEAREST PROJECT AT OR ABOVE
``event.cwd`` (``keel_gate.resolve_project``), not by whether ``event.cwd``
itself carries an arming file. A SESSION CAN BE GOVERNED BY A PROJECT IT IS
NOT SITTING IN, exactly as a write or a command already can be: a session
started one directory below its project's root is enforced by that project,
not read as unarmed the way it was before this task. See
``resolve_governing_project`` for the three answers the walk can give and
what this gate does with each.

THE ORDER IS STILL LOAD-BEARING: resolution is decided before the
``KEEL_OVERRIDE`` kill switch, so an unarmed project can never be told that a
lock it never had is suspended, and can never be given a ``.keel/`` directory
by the line that says so. What changed is WHICH directory that guarantee is
about - the GOVERNING project's, not necessarily ``event.cwd``'s.

TWO OF THE WALK'S THREE ANSWERS ARE UNCHANGED IN SPIRIT: ``PROJECT_FOUND``
enforces, at the found project's own tier; ``PROJECT_ABSENT`` is the ordinary
"never adopted keel" allow. THE THIRD, ``PROJECT_UNKNOWN`` - the walk ran out
of ``PROJECT_WALK_MAX_LEVELS`` before it could answer - is handled
DIFFERENTLY here than in ``keel_gate.governance``, deliberately: see
``resolve_governing_project``'s docstring for why.

Failure policy
--------------
FAIL-CLOSED WHEN ARMED, FAIL-OPEN WHEN UNARMED - the same declaration
``keel_gate.py`` carries, for the same reason (R3), asserted in both
directions by ``tests/test_keel_kernel.py``. "Armed" here means the SAME
governing-project resolution ``evaluate`` itself uses (T186), not a bare read
of ``event.cwd``; and when that resolution cannot tell at all
(``PROJECT_UNKNOWN``), the failure policy treats the session as armed rather
than as unarmed - what keel cannot vouch for it does not treat as a safe
default to fail open on, either. Three cases are NOT failures and allow
deliberately: ``stop_hook_active`` (the harness is re-entering this hook), a
missing ledger (this session recorded nothing, so there is nothing to
account for), and a fresh block marker (never block the same session twice in
a row - a blocking Stop hook that repeats is a hung session).

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network. The session id is sanitised before it becomes a filename, so a
payload value can never traverse a path (R5). Every file read names its
encoding.
"""

from __future__ import annotations

import datetime
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_events import KeelEvent, KeelVerdict, allow, append_audit, deny, read_audit  # noqa: E402
from keel_gate import (  # noqa: E402
    ARMING_FILE_IS_NOT_THE_FAULT,
    ARMING_FILE_IS_THE_FAULT,
    ENFORCING_TIER,
    NEXT_STEP_ARMING_FILE,
    NEXT_STEP_FAULT_UNATTRIBUTED,
    NEXT_STEP_SELF_FAULT,
    OVERRIDE_REMINDER,
    PLANS_RELPATH,
    PROJECT_WALK_MAX_LEVELS,
    SELF_FAULT_ATTRIBUTION,
    GateError,
    env_off,
    env_on,
    gate_self_fault,
    is_armed,
    policy_parse_fault,
    policy_present,
    policy_tier,
    relativise,
    resolve_project,
)
#: THE SEAT'S MODEL (BL25), READ THE SAME WAY ``keel_session`` READS IT AT
#: ``session_start`` - IMPORTED rather than re-derived (R15), so the two
#: hooks can never come to disagree about what counts as the model in the
#: seat. Safe on the import graph: ``keel_session`` imports ``keel_capture``,
#: ``keel_events``, ``keel_gate`` and ``keel_redact`` at module scope and
#: nothing that reaches back to this module, so no cycle is created. See
#: ``_audit`` for where this is called and the module contract's "Reads"
#: section for what the read can and cannot find.
from keel_session import model_from_transcript  # noqa: E402

#: A ``handoff_end`` within this long of its ``handoff_start`` is a
#: background-launch acknowledgment, not a completion. Kept as its own named
#: constant so a future dashboard must reference it rather than re-derive it.
#: KEEL ADDITION (T348): this is now the FALLBACK ONLY, read for a
#: ``handoff_end`` that carries no ``HANDOFF_BACKGROUND_KEY`` at all - see
#: that constant and ``session_has_open_handoff`` for why a recorded fact
#: is read first.
BG_LAUNCH_MS = 5000

#: WHETHER A CLOSE HALF IS A BACKGROUND ACKNOWLEDGMENT, READ FROM THE RECORD
#: RATHER THAN GUESSED FROM ELAPSED TIME (T348). ``hooks/keel_capture.py``
#: writes this key (``HANDOFF_BACKGROUND_KEY`` there, same spelling, T323)
#: on the close half of every launch from the launch tool's own result
#: ``status`` - ``true`` for ``async_launched`` (a background acknowledgment),
#: ``false`` for a genuine completed return, ``null`` where nothing readable
#: existed (including every close half written before T323). This gate used
#: to read ONLY the elapsed time between a launch and its close - a guess
#: T182 had already measured wrong once (an 8s background acknowledgment) -
#: and MEASURING THIS PROJECT'S OWN AUDIT LOG (2026-08-27, T348) found the
#: guess wrong again, live: of 24 close halves this repo's own log marks
#: ``background: true``, 5 arrived 5s-19s after their launch and were
#: misread by the elapsed-time rule as finished foreground runs, closing
#: launches whose agents were demonstrably still working - two stop_block
#: refusals in the session that found this cited it by name. This constant
#: is read FIRST in ``session_has_open_handoff``; the elapsed-time guess
#: above survives only as the fallback for a ``handoff_end`` that predates
#: this field, exactly as ``scripts/keel_orchestration_dashboard.py``'s
#: ``computeStates`` already reads the same key the same way, one hook
#: along (T323).
HANDOFF_BACKGROUND_KEY = "background"

#: A background hand-off with no activity for this long and no
#: ``subagent_stop`` is presumed finished rather than open.
LIVENESS_MS = 10 * 60 * 1000

#: Never block the same session twice in a row inside this window (seconds).
MARKER_TTL_SECONDS = 180

#: Ledger statuses. Terminal ones need no proof; ``[~]`` needs proof, and (T229)
#: a ``[x]`` claiming ``FILED`` needs proof too - just against a different
#: record.
OPEN_ITEM_RE = re.compile(r"^\s*[-*] \[ \] *(.+)$", re.MULTILINE)
INFLIGHT_ITEM_RE = re.compile(r"^\s*[-*] \[~\] *(.+)$", re.MULTILINE)
CLOSED_ITEM_RE = re.compile(r"^\s*[-*] \[x\] *(.+)$", re.MULTILINE | re.IGNORECASE)

#: A closed item's own claim that its remaining work moved to the backlog
#: (T229) - found INSIDE a ``[x]`` item's text, never anchored at its start,
#: because the id it names belongs to a different record than the one this
#: line lives in.
FILED_NOTE_RE = re.compile(r"\bFILED:\s*([A-Za-z]{1,4}[0-9]{1,4}[A-Za-z]?)\b")

#: Where the session-independent backlog lives
#: (``.keel/decisions/2026-08-22-a-backlog-is-not-a-plan.md``). Read-only from
#: this gate: filing WRITES here, this gate only VERIFIES a claim against it.
BACKLOG_RELPATH = (".keel", "backlog.md")

#: A backlog entry's own leading id, the same shape ``ITEM_ID_RE`` reads off a
#: ledger item. The checkbox mark is captured, not skipped (T229): a FILED
#: claim verifies only against an entry that is still OPEN on the backlog - a
#: ``[x]``/closed entry is a backlog id that once existed, not one a NEW claim
#: may point to, so it must not verify a fresh filing either.
BACKLOG_ID_RE = re.compile(
    r"^\s*[-*] \[(.)\] *([A-Za-z]{1,4}[0-9]{1,4}[A-Za-z]?)\b", re.MULTILINE
)

#: The identifier a ledger item leads with, where it has one: keel's task ids
#: (``T130``, ``T7b``) sit at the head of the item text, optionally emphasised.
#: Anchored at the start on purpose - an id found anywhere in the prose would
#: name the item this one CITES rather than the item itself.
ITEM_ID_RE = re.compile(r"^[*_`\s]*([A-Za-z]{1,4}[0-9]{1,4}[A-Za-z]?)\b")

#: How much of an unidentified item's own text stands in for an id, and how
#: many identifiers one ``stop_block`` line carries. Both are bounds on an
#: audit line, not on the block: the COUNT beside the list is always the true
#: total, so a truncated list is visible by comparison rather than silent.
ITEM_LABEL_CHARS = 48
MAX_ITEM_IDS = 20

#: Characters allowed in the marker filename derived from a session id. The
#: dot is deliberately NOT allowed: a session id is a payload value, and
#: "../x" must not survive into a filename in any form (R5).
_MARKER_SAFE_RE = re.compile(r"[^A-Za-z0-9_-]")


def _parse_ts_ms(value: Any) -> float | None:
    """ISO timestamp -> epoch milliseconds; None on any parse failure.

    keel writes UTC with a ``Z`` suffix, which ``fromisoformat`` only accepts
    from Python 3.11, so the suffix is normalised first. A timestamp with no
    zone is read as UTC, because that is what every keel writer emits.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp() * 1000.0


def _session_of(entry: Mapping[str, Any]) -> Any:
    """Session identifier of an audit line, under either accepted key."""
    return entry.get("session", entry.get("session_id"))


def same_agent_type(left: Any, right: Any) -> bool:
    """True only when both records name the SAME, NON-BLANK agent type.

    THE ONE RULE for matching two audit records by agent type. It is public
    and it is imported - ``scripts/keel_attest.py`` calls this function
    rather than restating the test - because the two implementations
    disagreeing about a blank key is precisely the drift this exists to end.

    An absent type is not a value that can equal another absent type. Plain
    ``!=`` said otherwise: ``None != None`` is False, so a stop carrying no
    ``agent_type`` MATCHED a launch carrying no ``subagent_type`` and closed
    it, in the module that decides whether a turn may end. 62% of real stops
    (273 of 440) carry a blank type, and a launch field that may be blank is
    one schema change away, so the false match was latent rather than
    impossible.

    The reading is already keel's elsewhere: a blank ``agent_type`` means
    the main session's own work rather than an unknown delegation
    (``hooks/keel_capture.py``; asserted in ``tests/test_keel_attention.py``
    for ``{}``, ``""`` and ``"   "`` alike). This makes it uniform. Blank
    means absent, empty, whitespace, or any non-string; two present types are
    otherwise compared exactly, because an agent type is a wire value and not
    prose.

    What this deliberately does NOT fix: two REAL, same-typed delegations
    open at once still collide, because a type is not an identity. That is
    the join-key problem, and ``same_agent_id`` below is its answer - which
    is also why nothing here attributes a stop to a launch any more. This
    predicate's remaining job is the liveness window's, where the question
    genuinely is "is this activity the same KIND of agent's".
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    left, right = left.strip(), right.strip()
    return bool(left) and left == right


def same_agent_id(left: Any, right: Any) -> bool:
    """True only when both records name the SAME, NON-BLANK agent id.

    THE JOIN KEY (T102), and the one rule for matching two audit records by
    delegation identity. It is public and it is meant to be imported, for the
    reason ``same_agent_type`` is: three readers of this log decide whether a
    stop belongs to a launch - this gate, ``scripts/keel_attest.py``'s report
    and the viewer's canvas - and three copies of the comparison is exactly the
    drift a shared object cannot have.

    An agent id is a wire value, not prose, so two present ids are compared
    exactly after trimming. Blank means absent, empty, whitespace, or any
    non-string, and blank matches NOTHING, including another blank. That is
    the same reading ``same_agent_type`` carries and it is load-bearing in the
    same way: plain ``==`` on two nulls is True, and the audit log is full of
    nulls - every ``handoff_start`` records one by construction, and so does
    every launch line written before this field existed. A blank-to-blank
    match would pair each of those with the first unattributable stop to
    arrive, which is the precise failure this key was introduced to end.

    What it deliberately does NOT do: guess. A stop whose id names no launch
    on record - a resumed agent, a delegation launched before keel was
    adopted, a foreground return that has not landed yet - matches nothing and
    closes nothing, rather than falling back to a weaker key.
    """
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    left, right = left.strip(), right.strip()
    return bool(left) and left == right


def launch_agent_id(
    start: Mapping[str, Any], end: Mapping[str, Any] | None = None
) -> str | None:
    """The agent id of one delegation, or None when nothing on record names it.

    THE CHAIN, in one place so no reader has to rebuild it: the id lives in the
    launch TOOL's result, which reaches keel at PostToolUse, which is the
    ``handoff_end`` line - so it is the RETURN half that carries it, and the
    two halves are the same delegation because they share a ``tool_use_id``.
    The launch half is still read first, and not only for symmetry: a harness
    that came to expose the id at launch time, or a fixture written that way,
    is then read without changing anything here.

    A blank in either place is absence, not a value, so an id is returned only
    when some line actually names one.
    """
    for entry in (start, end):
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("agent_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def match_stops_to_launches(
    launch_agent_ids: Sequence[str | None],
    stops: Iterable[Mapping[str, Any]],
) -> dict[int, Mapping[str, Any]]:
    """Which launch each stop belongs to. Exact, or absent.

    THE ONE IMPLEMENTATION of matching a delegation-finish to the delegation
    it finished. It is public and it returns the ATTRIBUTION rather than a
    count, because the three readers of this log need different answers from
    the same question: this gate needs "is anything still open", the report
    needs "which stop attaches to which task", and the viewer needs "is THIS
    card finished". A function that only answered the first would leave the
    other two to write their own, which is how this project came to have three
    of them.

    ``launch_agent_ids`` is the id of each launch, in launch order, with None
    where nothing on record names one; the caller resolves it with
    ``launch_agent_id`` so that the chain from a launch to its return lives in
    one place. The answer maps a launch's INDEX to the stop that closed it, so
    a caller can see WHICH delegation ended and not merely how many did.

    The rules, all three of them consequences of ``same_agent_id``:

    * A stop closes the launch whose id it names, and no other. Two
      delegations of the same type running at once are told apart, which is
      the case a type-and-time-order guess gets wrong roughly half the time.
    * A stop that names no launch on this list closes nothing. It is not
      dropped by the log and it is not attributed by this function: unmatched
      is the answer, and it is returned by simply not appearing.
    * A launch is closed once. A backgrounded agent stops each time it has no
      live child, so repeat stops naming an already-closed launch are
      idempotent - the FIRST stop to name a launch is the one recorded
      against it, which is why the caller sorts stops chronologically.
    """
    matched: dict[int, Mapping[str, Any]] = {}
    for stop in stops:
        stop_id = stop.get("agent_id")
        for index, agent_id in enumerate(launch_agent_ids):
            if index in matched or not same_agent_id(agent_id, stop_id):
                continue
            matched[index] = stop
            break
    return matched


def session_has_open_handoff(cwd: Path, session_id: str | None) -> bool:
    """True when the audit log shows an unresolved delegation for THIS session.

    KEYED ON ``cwd`` - THE SESSION'S OWN DIRECTORY - DELIBERATELY, EVEN AFTER
    T186 RE-POINTED THE LEDGER/TIER LOOKUP AT THE GOVERNING PROJECT. This is
    not the same cwd-keyed shape T186 exists to close: ``hooks/keel_capture.py``
    is the ONLY writer of ``handoff_start``/``handoff_end``/``activity``
    lines, and re-pointing this READ at the governing project's root, while the
    WRITER files against the SESSION's, would make every real delegation
    unfindable - trading the hole T186 closed for a different one,
    self-inflicted. So the read follows the write, not the ledger.

    IT DID NOT FOLLOW THE WRITER'S ONE MOVE, AND THAT IS MEASURED RATHER THAN
    ASSUMED (T515). ``keel_capture.run`` now resolves the session's project by
    walking UP from ``event.cwd`` instead of reading ``.keel/`` at that exact
    directory, so a session standing in a SUBDIRECTORY - which recorded nothing
    at all before - now files its lines one or more levels up. Making this read
    climb to match was tried and REVERTED: an open hand-off is a reason to
    ALLOW a stop, so finding MORE hand-offs makes this gate MORE permissive, and
    ``tests/test_keel_stop_target_arming_t186.py``'s
    ``test_handoff_evidence_filed_only_at_the_governing_project_is_not_found``
    turned from deny to allow the moment it did. The direction of a fix to a
    fail-closed defect may not be "open". So the subdirectory case is left
    exactly as it behaved before: nothing is found here, and the stop is judged
    on its ledger alone - the same answer it got when nothing was written
    either.

    Any timestamp that cannot be parsed is treated as background/open rather
    than raised: a malformed audit line must never close a hand-off, and must
    never crash the gate.

    THREE WAYS A HAND-OFF CLOSES, and no fourth. Its RETURN is a genuine
    foreground pairing (its close half's own ``background`` field says
    ``False``, or - for a record written before that field existed, T348 -
    its close arrives well after its launch); a ``subagent_stop`` NAMES it by
    agent id; or its own activity has been quiet for ``LIVENESS_MS``. Each of
    the first two is an exact key - ``tool_use_id`` for the pair, ``agent_id``
    for the stop - and a record that carries neither is not closed by a
    resemblance to another record. The third is a timeout, and it is what an
    unattributable hand-off is left to, which is why removing the guesses
    does not leave one open forever - INCLUDING a hand-off this task keeps
    open longer, on the ``background`` field's word rather than the clock's
    (see ``HANDOFF_BACKGROUND_KEY``): a background launch whose agent dies
    without ever emitting ``subagent_stop`` is still reaped here once its
    activity (or, absent any, its own launch) has been quiet for
    ``LIVENESS_MS`` - the same sweep below, untouched by this task, applies
    to every entry ``open_launches`` holds, however it got there.
    """
    starts: list[dict[str, Any]] = []
    ends_by_id: dict[str, dict[str, Any]] = {}
    stops: list[dict[str, Any]] = []
    acts: list[dict[str, Any]] = []

    for entry in read_audit(cwd):
        if _session_of(entry) != session_id:
            continue
        event = entry.get("event")
        if event == "handoff_start":
            starts.append(entry)
        elif event == "handoff_end":
            tool_use_id = entry.get("tool_use_id")
            # A RETURN THAT NAMES NO TOOL CALL IS KEPT BY NOBODY. It used to
            # go into a ``(subagent_type, description)`` bucket, which pairs
            # two records that name neither - a launch and a return that have
            # nothing in common but two absences. Dropping it here does not
            # lose a delegation: the launch it would have closed stays open,
            # which is the honest reading of a return keel cannot attribute.
            if isinstance(tool_use_id, str) and tool_use_id.strip():
                ends_by_id[tool_use_id.strip()] = entry
        elif event == "subagent_stop":
            stops.append(entry)
        elif event == "activity":
            acts.append(entry)

    # Each entry: the launch line, and the delegation's agent id - which comes
    # from its return, because only the return carries one.
    #
    # EVERY LAUNCH THAT REACHES THIS LIST IS QUIET-CLOSEABLE, and there is
    # deliberately no flag saying so. This list used to carry one, set at both
    # append sites to the same value; a field that is always True does not
    # record a choice, it only suggests a choice was available. It was not.
    # The list holds exactly the launches this pass could not pair with a
    # RETURN - a background acknowledgment, an unreadable pair of timestamps,
    # and a launch with no return on record at all - and the third way a
    # hand-off closes exists precisely for that set, which is what lets the
    # exact keys above refuse to guess without leaving anything open forever.
    open_launches: list[tuple[dict[str, Any], str | None]] = []
    for start in starts:
        tool_use_id = start.get("tool_use_id")
        end: dict[str, Any] | None = None
        if isinstance(tool_use_id, str) and tool_use_id.strip():
            end = ends_by_id.get(tool_use_id.strip())

        if end is None:
            open_launches.append((start, launch_agent_id(start)))
            continue

        # KEEL ADDITION (T348): READ THE RECORDED FACT BEFORE GUESSING FROM
        # THE CLOCK. The close half's own ``background`` field says whether
        # the launch tool's result WAS a background acknowledgment, straight
        # from its ``status`` - not inferred from how fast it happened to
        # arrive. Trusted either way, exactly as
        # ``keel_orchestration_dashboard.py``'s ``computeStates`` already
        # trusts it (T323): ``True`` keeps the launch open regardless of
        # elapsed time (a slow acknowledgment is not a finished run), and
        # ``False`` closes it regardless of elapsed time (a fast genuine
        # foreground return is not kept open on a technicality). Only a
        # close half that carries neither ``True`` nor ``False`` - a record
        # written before this field existed - falls through to the
        # elapsed-time guess below.
        background = end.get(HANDOFF_BACKGROUND_KEY)
        if isinstance(background, bool):
            if background:
                open_launches.append((start, launch_agent_id(start, end)))
            # background is False: a genuine foreground return, closed.
            continue

        t_start = _parse_ts_ms(start.get("ts"))
        t_end = _parse_ts_ms(end.get("ts"))
        if t_start is None or t_end is None or (t_end - t_start) < BG_LAUNCH_MS:
            open_launches.append((start, launch_agent_id(start, end)))
            continue
        # end well after start, and this line predates the recorded field ->
        # genuine foreground pairing, fully closed (unchanged fallback)

    if not open_launches:
        return False

    def _ts(entry: Mapping[str, Any]) -> str:
        return entry.get("ts") or ""  # ISO strings sort chronologically

    open_launches.sort(key=lambda launch: _ts(launch[0]))
    stops.sort(key=_ts)

    # A stop closes the launch it NAMES, and the attribution is computed by
    # the shared matcher rather than restated here. No time comparison is
    # involved: an id is unique, so "which of these could it be" is not a
    # question this has to answer by proximity.
    closed: set[int] = set(
        match_stops_to_launches([launch[1] for launch in open_launches], stops)
    )

    # activity-quiet liveness: a launch not closed by a stop is presumed
    # finished once its own activity - bounded by the next same-type start -
    # has been quiet for LIVENESS_MS.
    now_ms = time.time() * 1000.0
    for index, (start, _agent_id) in enumerate(open_launches):
        if index in closed:
            continue
        agent_type = start.get("subagent_type")
        t_start = _parse_ts_ms(start.get("ts"))
        next_start_ts: float | None = None
        for other, _other_id in open_launches[index + 1:]:
            if same_agent_type(other.get("subagent_type"), agent_type):
                next_start_ts = _parse_ts_ms(other.get("ts"))
                break
        last_seen = t_start
        for activity in acts:
            # A blank type on either side attributes nothing, so a hand-off
            # that names no agent has no activity of its own and its window
            # runs from its own launch: it is closed by elapsed quiet, never
            # by somebody else's tool call.
            if not same_agent_type(activity.get("agent_type"), agent_type):
                continue
            act_ts = _parse_ts_ms(activity.get("ts"))
            if act_ts is None or t_start is None or act_ts < t_start:
                continue
            if next_start_ts is not None and act_ts >= next_start_ts:
                continue
            if last_seen is None or act_ts > last_seen:
                last_seen = act_ts
        if last_seen is None:
            continue  # unparseable timestamps: fail safe, stay open
        if (now_ms - last_seen) >= LIVENESS_MS:
            closed.add(index)

    return len(closed) < len(open_launches)


def marker_path(session_id: str | None) -> Path:
    """Loop-safety marker for a session, inside the system temp directory.

    The session id is a payload value, so it is reduced to filename-safe
    characters before it is used as one - no payload may steer a path (R5).
    """
    safe = _MARKER_SAFE_RE.sub("_", (session_id or "unknown"))[:64] or "unknown"
    return Path(tempfile.gettempdir()) / f"keel_stop_{safe}"


def marker_is_fresh(session_id: str | None) -> bool:
    """True when this session was blocked less than MARKER_TTL_SECONDS ago.

    THE PATH IS BUILT INSIDE THE GUARD (T208), and the guard catches more than
    ``OSError``: ``marker_path`` reaches ``tempfile.gettempdir()``, which is a
    filesystem question and can fail for reasons no caller controls, and it
    has no guard of its own. A fault while merely LOCATING the marker now
    reads as "no fresh marker", which is this function's own fail-safe answer,
    instead of escaping into ``evaluate``.
    """
    try:
        path = marker_path(session_id)
        return path.is_file() and (time.time() - path.stat().st_mtime) < MARKER_TTL_SECONDS
    except Exception:  # noqa: BLE001 - a missing marker is the safe reading
        return False


def touch_marker(session_id: str | None) -> None:
    """Record that this session was just blocked. Never fails the gate.

    NEVER RAISES, for any reason (T208). This is called from ``run``'s tail,
    AFTER the verdict is final, so an escape here cannot change the decision -
    it can only destroy it, by reaching ``keel_hook`` in place of the deny this
    gate already reached. The guard therefore covers locating the marker
    (``tempfile.gettempdir()``, which has no guard of its own) as well as
    writing it, and it catches every exception rather than ``OSError`` alone.
    """
    try:
        marker_path(session_id).write_text("", encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - reported, never silent, never fatal
        print(f"keel: stop marker not written: {exc}", file=sys.stderr)


def resolve_governing_project(cwd: Path) -> tuple[Path | None, bool]:
    """The project that governs THIS session, and whether resolution ran out
    of budget rather than actually answering.

    Delegates the entire walk to ``keel_gate.resolve_project`` (T178's
    helper) rather than re-deriving it - R15's one-parser rule binds the walk
    itself, not only its name. Returns ``(root, unresolved)``:

    * ``PROJECT_FOUND``  -> ``(root, False)``. A project's arming file is at
      or above ``cwd``, and ``root`` MAY DIFFER FROM ``cwd`` - a session can
      be GOVERNED BY A PROJECT IT IS NOT SITTING IN (T178's whole point, one
      hook along), and every downstream read here - ledger, tier, audit
      destination - follows ``root``, never ``cwd``.
    * ``PROJECT_ABSENT`` -> ``(None, False)``. The walk reached a ceiling (a
      filesystem root, the home directory) without finding one. A COMPLETE
      answer: this session belongs to no project at all.
    * ``PROJECT_UNKNOWN`` -> ``(None, True)``. The walk ran out of
      ``PROJECT_WALK_MAX_LEVELS`` before it could answer.

      ``keel_gate.governance`` falls back, for exactly this state, to
      testing ``policy_present`` at the session's own directory directly (no
      further walk) - documented there as "precisely what shipped before
      T178, so it cannot be a regression". THIS FUNCTION DOES NOT COPY THAT
      FALLBACK, and the omission is deliberate rather than an oversight:
      ``resolve_project``'s own walk already tests ``policy_present`` at
      ``cwd`` itself as the FIRST thing it does (step 0 of the loop, before
      any ceiling or budget check - see ``keel_gate._resolve_resolved``), so
      ``PROJECT_UNKNOWN`` can only ever be returned when that exact test has
      already come back False. A second call to ``policy_present(cwd)`` here
      would therefore always read False too - a documented branch that
      production code can never take, which is precisely the shape this
      project's own review culture polices (T176's ``WORKSHOP_UNKNOWN``: "a
      state no reader can reach through production code is a state that is
      not tested"). Writing that dead branch here would repeat the class of
      defect T186 exists to close, not honour the precedent it comes from.

      So ``PROJECT_UNKNOWN`` reads as "cannot vouch", full stop, and the
      caller is told via the second element so it can be REPORTED rather
      than silently folded into "unarmed" - a Stop event has no second
      governance signal to fall back on the way a write's target does (a
      target's own bucket can be uncertain while the session's own project
      still judges the rest of the event); here the session's own governance
      IS the whole question, so "cannot tell" must not read the same as
      "definitely not governed". See ``announce_unresolved_session``.
    """
    resolution = resolve_project(cwd)
    if resolution.found:
        return resolution.root, False
    if resolution.unknown:
        return None, True
    return None, False  # PROJECT_ABSENT: a complete answer, no fallback needed


#: The next step for a session whose own governing project keel could not
#: resolve. Named as a constant, like ``keel_gate.NEXT_STEP_UNRESOLVED_PROJECT``,
#: so the wording is stated once rather than folded into one long sentence.
NEXT_STEP_UNRESOLVED_SESSION = (
    "NEXT STEP: run the session from within "
    f"{PROJECT_WALK_MAX_LEVELS} parent directories of its governing project's "
    ".keel/keel-policy.md, or set KEEL_GATE=off deliberately if this session "
    "genuinely answers to no project. There is nothing to override here: "
    "keel is not refusing on policy grounds, it cannot tell whether one "
    "applies."
)


def unresolved_session_message(event: KeelEvent) -> str:
    """The stderr/report text for a stop whose own governing project keel
    could not resolve - modelled on ``keel_gate.unresolved_project_message``,
    but about the SESSION's own directory rather than a write's target, since
    a stop event names no target of its own to point at."""
    return (
        f"PROJECT UNRESOLVED FOR THIS SESSION (stop): keel climbed "
        f"{PROJECT_WALK_MAX_LEVELS} parent directories above this session's "
        f"own directory without reaching either a project's arming file or "
        f"the top of the walk, so it cannot say whether any project's ledger "
        f"governs this session. What keel cannot vouch for it does not treat "
        f"as accounted-for. {NEXT_STEP_UNRESOLVED_SESSION}"
    )


def announce_unresolved_session(event: KeelEvent) -> None:
    """Stderr AND one audit line for a stop whose OWN governance keel could
    not resolve - never silent (T186).

    UNLIKE ``keel_gate.announce_unresolved_targets``, this is not one bucket
    among several a bigger event still gets judged by: a Stop event's ONLY
    governance question is which project governs the session, so an
    unresolved answer here is the WHOLE answer, not one target's share of it.
    Reading it the same as "no ledger to check" would be exactly the
    guardrail that passes because it examined nothing - the shape this task
    exists to close.

    THE AUDIT LINE IS WRITTEN EVEN THOUGH ``event.cwd`` MAY NEVER HAVE
    ADOPTED KEEL, which looks like it defies the "nothing at all in an
    unadopted project" rule this module otherwise keeps (R25, see
    ``armed_for_reminders``) - it does not, because that rule is about a
    CONFIRMED absence, and this is the opposite: keel could not confirm
    ANYTHING, including absence. ``keel_gate.announce_unresolved_targets``
    already makes the identical choice for the same fact about a write's
    target, filing ``unresolved_project_allowed`` at ``event.cwd``
    unconditionally; this reuses that event name on purpose, so a reader of
    either gate's log recognises the same vocabulary for the same fact.
    """
    try:
        print(f"keel: {unresolved_session_message(event)}", file=sys.stderr)
    except Exception:  # noqa: BLE001 - a notice may never fail the gate
        pass
    try:
        append_audit(
            event.cwd,
            {
                "event": "unresolved_project_allowed",
                "gate": "unresolved_project",
                "kind": event.kind,
                "session": event.session_id,
                "detail": {"walked_levels": PROJECT_WALK_MAX_LEVELS},
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: unresolved_project_allowed audit failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def plan_path(root: Path, sess8: str) -> Path:
    """This session's ledger, IN THE GOVERNING PROJECT. Other sessions'
    ledgers are never consulted, and ``root`` is the project
    ``resolve_governing_project`` found - not necessarily where the session
    is standing (T186)."""
    return Path(root).joinpath(*PLANS_RELPATH, f"keel-plan-{sess8}.md")


def read_ledger(root: Path, sess8: str) -> str | None:
    """Ledger text, or None when this session has no ledger on file."""
    if not sess8:
        return None
    path = plan_path(root, sess8)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read the session ledger: {exc}") from exc


def read_backlog_ids(root: Path) -> set[str] | None:
    """The ids of every entry still OPEN (``- [ ] BL<n>``) on
    ``.keel/backlog.md``, or ``None`` when the file cannot be read at all
    (T229).

    A ``[x]``/closed backlog entry's id is deliberately EXCLUDED: a FILED
    claim naming it is not accounted just because that id once existed on the
    backlog - the entry it would file against is already closed, so the claim
    is exactly as unverifiable as one naming an id the backlog never carried.

    ``None`` is UNDECIDABLE, never empty (convention 7): a ``FILED`` claim
    that names an id from a backlog keel could not read is unverifiable, and
    unverifiable must not collapse into "this backlog carries nothing" - the
    caller treats both the same way (no proof, no accounting) but the
    distinction matters to a reader of a future fault line.
    """
    path = Path(root).joinpath(*BACKLOG_RELPATH)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return {
        match.group(2)
        for match in BACKLOG_ID_RE.finditer(text)
        if match.group(1) == " "
    }


def block_message(
    plan_name: str,
    open_items: list[str],
    stale_inflight: list[str],
    unverified_filed: list[str] | None = None,
    *,
    governing_project: Path | None = None,
) -> str:
    """The STOP BLOCKED message, naming what is unaccounted for.

    ``governing_project`` is set only when the session is governed by a
    project it is NOT sitting in (T186). The ordinary case - governed by the
    directory the session is standing in, which is every fixture that
    predates this task - renders byte-identical to before: the addendum below
    is additive, the same asymmetry ``keel_gate._named_project`` keeps for a
    write's own refusal message. It names the ledger's ABSOLUTE path there,
    because a project-relative name is useless to a model that would
    otherwise write the ledger beside itself and be refused again for the
    same reason.

    ``unverified_filed`` (T229) defaults to ``None`` so every caller that
    predates filing renders byte-identical prose, exactly as the
    ``governing_project`` addendum already does.
    """
    parts: list[str] = []
    if open_items:
        preview = "; ".join(item.strip()[:60] for item in open_items[:5])
        parts.append(f"{len(open_items)} plan item(s) still open ({preview})")
    if stale_inflight:
        preview = "; ".join(item.strip()[:60] for item in stale_inflight[:5])
        parts.append(
            f"{len(stale_inflight)} item(s) marked [~] in-flight but no active "
            f"delegation is on record in .keel/audit/keel-audit.jsonl for this "
            f"session ({preview}) - review the returned report and close the "
            "item properly ([x]/[!]/[?]); [~] does not excuse accounting on "
            "its own"
        )
    if unverified_filed:
        preview = "; ".join(item.strip()[:60] for item in unverified_filed[:5])
        parts.append(
            f"{len(unverified_filed)} item(s) closed [x] with a FILED note naming "
            f"a backlog id .keel/backlog.md does not carry OPEN ({preview}) - filing "
            "is accounted only when the backlog record actually holds that entry "
            "OPEN; a closed backlog entry does not verify a new claim, so re-file "
            "it there as a fresh open entry, or account for the item some other "
            "terminal way"
        )
    message = (
        f"STOP BLOCKED: {'; and '.join(parts)} in {plan_name}. Before "
        "stopping, mark each item [x] done, [!] blocked with a concrete "
        "reason, or [?] needs the user's decision - then report the full "
        "ledger to the user. Use [~] only while a delegation is genuinely "
        "still running. A [x] item may FILE its remaining work to the backlog "
        "with a 'FILED: BL<n>' note naming an entry that is really on "
        ".keel/backlog.md. (Guardrail: stop-with-accounting.)"
    )
    if governing_project is not None:
        ledger = governing_project.joinpath(*PLANS_RELPATH, plan_name)
        message += (
            f" GOVERNING PROJECT: this session is governed by the project at "
            f"{governing_project}, not by the directory it is standing in - "
            f"the ledger this accounting needs is {ledger}."
        )
    return message


def item_identifier(item: Any) -> str:
    """One ledger item reduced to something a reader can look up.

    The item's leading task id where it has one (``T130``), and otherwise a
    bounded head of the item's own text - never nothing, because an item with
    no id is exactly the item a count alone cannot help anybody find. Newlines
    and runs of whitespace collapse to single spaces so one identifier stays
    one field of one JSONL line.

    Never raises and never returns an empty string: a non-string, or an item
    that is all whitespace, yields ``"(unnamed item)"`` rather than a blank
    that would read as a missing entry in the list.
    """
    if not isinstance(item, str):
        return "(unnamed item)"
    text = " ".join(item.split())
    if not text:
        return "(unnamed item)"
    match = ITEM_ID_RE.match(text)
    if match:
        return match.group(1)
    return text[:ITEM_LABEL_CHARS]


def item_identifiers(items: Sequence[Any]) -> list[str]:
    """The identifiers of up to ``MAX_ITEM_IDS`` items, in ledger order.

    The cap is on the AUDIT LINE, not on the accounting: the count written
    beside this list is ``len(items)`` in full, so a list shorter than the
    count is a visible truncation rather than a quiet one (convention 7). The
    order is the ledger's own, so the first identifiers are the first items a
    reader will find when they open the file.
    """
    return [item_identifier(item) for item in list(items)[:MAX_ITEM_IDS]]


def evaluate(event: KeelEvent, env: Mapping[str, str] | None = None) -> KeelVerdict:
    """Decide one stop event. Raises GateError when it cannot decide.

    ORDER IS THE CONTRACT, and it mirrors ``keel_gate.evaluate`` exactly:
    ``KEEL_GATE=off`` stands the whole guard down, then RESOLUTION decides
    whether this session is governed at all - and by whom (T186) - and only
    then does the override - the switch that suspends a lock - get a say. A
    session resolved as ungoverned must leave this function as ungoverned, so
    that ``run`` can tell the difference and say nothing about a lock the
    project never had (R25).
    """
    env = os.environ if env is None else env
    if env_off("KEEL_GATE", env):
        return allow("kill switch KEEL_GATE=off", gate="kill_switch")

    root, unresolved = resolve_governing_project(event.cwd)
    if unresolved:
        announce_unresolved_session(event)
        return allow(unresolved_session_message(event), gate="unresolved_project")
    if root is None:
        return allow(
            "unarmed: no .keel/keel-policy.md at or above this session's directory",
            gate="unarmed",
        )

    # ``root`` is PROJECT_FOUND, which guarantees policy_present(root) is
    # True - so, unlike the pre-T178 shape, there is no "tier is None" branch
    # to fall back to here: it is unreachable by construction, and this
    # project's own review culture treats an unreachable branch as a defect
    # to avoid writing, not a safety net (T176). A malformed frontmatter still
    # raises GateError, which propagates to ``run``'s declared failure policy.
    tier = policy_tier(root)
    if tier < ENFORCING_TIER:
        return allow(f"tier {tier} is below the enforcing tier {ENFORCING_TIER}", gate="tier")

    if env_on("KEEL_OVERRIDE", env):
        return allow("kill switch KEEL_OVERRIDE=on", gate="kill_switch")
    if event.raw.get("stop_hook_active"):
        return allow("stop_hook_active: the harness is re-entering this hook", gate="loop")

    if marker_is_fresh(event.session_id):
        return allow("this session was blocked moments ago; never block twice", gate="loop")

    text = read_ledger(root, event.sess8)
    if text is None:
        return allow("no ledger on file for this session; nothing to account for", gate="stop")

    open_items = OPEN_ITEM_RE.findall(text)
    inflight_items = INFLIGHT_ITEM_RE.findall(text)
    stale_inflight: list[str] = []
    if inflight_items and not session_has_open_handoff(event.cwd, event.session_id):
        stale_inflight = inflight_items

    # T229: a [x] item may claim its remaining work was FILED to the backlog.
    # The claim is only ever taken at its word if the backlog file backs it -
    # otherwise it is unaccounted, same as an open item, because a mark that
    # can be satisfied by a sentence alone is the fraud T196 named.
    # Every FILED id on one item's line must verify, not just the first
    # (T229): a line naming a real entry and then a fabricated one is exactly
    # as unaccounted as one naming only the fabricated id.
    filed_claims = [
        (item, ids)
        for item in CLOSED_ITEM_RE.findall(text)
        for ids in (FILED_NOTE_RE.findall(item),)
        if ids
    ]
    unverified_filed: list[str] = []
    if filed_claims:
        backlog_ids = read_backlog_ids(root)
        unverified_filed = [
            item
            for item, claimed_ids in filed_claims
            if backlog_ids is None or any(cid not in backlog_ids for cid in claimed_ids)
        ]

    if not open_items and not stale_inflight and not unverified_filed:
        return allow("every ledger item is terminal", gate="stop")

    here = os.path.realpath(str(event.cwd))
    foreign = str(root).casefold() != here.casefold()
    plan_name = plan_path(root, event.sess8).name
    detail: dict[str, Any] = {
        "open_items": len(open_items),
        "stale_inflight_items": len(stale_inflight),
        "unverified_filed_items": len(unverified_filed),
        # The identifiers beside the counts, named for what this gate computes
        # - the open items, the stale in-flight ones, and the filed claims the
        # backlog does not back - so a reader of the audit line can go to the
        # ledger and find them, instead of learning only how many there were.
        # The counts above stay authoritative; these lists are bounded
        # (``MAX_ITEM_IDS``).
        "open_item_ids": item_identifiers(open_items),
        "stale_inflight_item_ids": item_identifiers(stale_inflight),
        "unverified_filed_item_ids": item_identifiers(unverified_filed),
    }
    if foreign:
        # Read and popped by ``_audit`` - the same ``detail['project']``
        # convention ``keel_gate._audit`` uses (T178) - to route this line to
        # the GOVERNING project's own log rather than the session's directory.
        detail["project"] = str(root)
    return deny(
        block_message(
            plan_name, open_items, stale_inflight, unverified_filed,
            governing_project=root if foreign else None,
        ),
        gate="stop",
        **detail,
    )


def _audit(event: KeelEvent, verdict: KeelVerdict) -> None:
    """Record a block. Auditing must never be able to fail the gate itself.

    THE GOVERNING PROJECT IS SPENT HERE, NOT WRITTEN HERE (T186, mirroring
    ``keel_gate._audit``): ``detail['project']`` is only ever an ABSOLUTE
    path - it has to be, since it names the directory this line is filed in -
    and convention 5 says the persisted log carries no absolute path, so it
    is popped and replaced with a project-relative ``session_cwd``: where the
    session was standing, expressed relative to the project this block is
    filed against. In the ordinary case - the session's own directory IS the
    governing project, every fixture that predates T186 - ``project`` is
    never set, so this is a complete no-op and the line stays byte-identical.

    THE SEAT'S MODEL IS NAMED HERE TOO, ON THE SAME LINE (BL25). Until this
    task a ``stop_block`` line said nothing about which model was in the
    seat, even though the payload it is built from can carry the identical
    ``transcript_path`` ``keel_session`` already reads at ``session_start`` -
    and unlike ``session_start``, an assistant line usually already exists by
    the time a session stops, so this read is rarely the empty attempt
    ``session_start``'s can be on a fresh session. ``model_from_transcript``
    is IMPORTED from ``keel_session`` rather than re-derived (R15): one
    bounded, best-effort reader of one field, used by both hooks, so they can
    never come to name the seat two different ways.

    THE READ HAS ITS OWN, NARROWER GUARD, separate from the one that wraps
    ``append_audit`` below (tests-review finding: BL25/T475). It NEVER RAISES
    by ``model_from_transcript``'s own contract, but "never by contract" is
    not "cannot in practice" - a future edit to that function, or to
    ``keel_session`` generally, is exactly the kind of fault this project's
    own review culture assumes WILL eventually happen. Folding the call into
    the SAME ``try`` as ``append_audit`` would mean an unexpected raise there
    costs the WHOLE ``stop_block`` line - the open-item counts and
    identifiers this function already computed, lost along with the one
    field that faulted - which is a worse outcome than the null this field
    already promises on every OTHER failure mode (an absent transcript, an
    unreadable one, one with no assistant line). So the read is wrapped in
    its OWN ``try``, reported on its own stderr line, and answers ``None`` on
    any fault: a fault reading the seat costs exactly that one field, never
    the accounting the rest of this line carries.

    THE GUARD STARTS AT THE FIRST STATEMENT (T208). Until this task, the four
    lines below sat OUTSIDE the ``try``, so ``os.path.realpath`` and
    ``relativise`` - both OS calls on a path that resolved upstream in the same
    call, and therefore rare rather than impossible faults - could raise past
    this function, past ``run``'s tail (where ``_audit`` is called after the
    verdict is final), and into ``keel_hook``. That escape used to become an
    exit 0: a session permitted to stop unaccounted because keel could not
    write the line SAYING it was refused. Now a fault there costs the audit
    line and nothing else, and the deny that was already decided stands. The
    write gate's ``keel_gate._audit`` carries the identical fix at the
    identical place, per T208 clause 2.
    """
    try:
        detail = {k: v for k, v in verdict.detail.items()}
        project = detail.pop("project", None)
        destination = Path(project) if project else event.cwd
        if project:
            detail["session_cwd"] = relativise(destination, os.path.realpath(str(event.cwd)))
        try:
            model = model_from_transcript(event.raw)
        except Exception as exc:  # noqa: BLE001 - the seat may not cost the whole line
            print(
                f"keel: stop seat not read: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            model = None
        append_audit(
            destination,
            {
                "event": "stop_block",
                "gate": verdict.gate,
                "session": event.session_id,
                "model": model,
                "detail": detail,
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(f"keel: stop audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def governing_project_if_armed(cwd: Path) -> Path | None:
    """The project GOVERNING this session, if - and only if - it is armed.

    NEVER raises: an unreadable arming file, an unreadable tier, a resolution
    that could not tell (``PROJECT_UNKNOWN``) - all read as "not armed" here,
    because this feeds a footnote (the override reminder), not a decision,
    and a footnote may not fail a stop that already allowed.
    """
    try:
        root, unresolved = resolve_governing_project(cwd)
    except Exception:  # noqa: BLE001 - a footnote may not fail the gate
        return None
    if unresolved or root is None:
        return None
    try:
        return root if is_armed(root) else None
    except Exception:  # noqa: BLE001 - a footnote may not fail the gate
        return None


def armed_for_reminders(cwd: Path) -> bool:
    """True when the project GOVERNING this session (T186 - not necessarily
    ``cwd`` itself) opted into enforcement. NEVER raises.

    The reminder is the only thing keel says about a lock, so it may be said
    only where a lock exists: an unarmed project is told nothing and, because
    the reminder is also an audit line, has no ``.keel/`` created under it
    (R25). Unreadable arming file, unreadable tier, unresolved governance, any
    OS fault: not armed, because a stop that already allowed must not be
    failed by its own footnote.
    """
    return governing_project_if_armed(cwd) is not None


def _nag_override(event: KeelEvent, root: Path, verdict: KeelVerdict, stderr: Any = None) -> None:
    """One reminder per stop while the override is on. Never a decision.

    An allow verdict emits nothing at all through the adapter - that is the
    "allow is silence" contract, and it is not weakened here: the reminder
    goes to STDERR, which the harness shows as hook feedback, and to the
    audit log as ``override_active_at_stop``, FILED AGAINST ``root`` - the
    project ``governing_project_if_armed`` just confirmed is armed (T186), not
    necessarily ``event.cwd`` - so this line lands beside the ``stop_block``
    lines the same governing project's ledger produces. Nothing about the
    verdict changes, and a failure to say it can never fail the stop gate.
    """
    try:
        append_audit(
            root,
            {
                "event": "override_active_at_stop",
                "gate": "policy_lock",
                "session": event.session_id,
                "detail": {"switch": "KEEL_OVERRIDE"},
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(f"keel: stop override audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    print(OVERRIDE_REMINDER, file=stderr or sys.stderr)


#: THE REFUSAL OF LAST RESORT: what a Stop is told when the stop gate could
#: neither account for the session NOR word the refusal about it. A CONSTANT,
#: with nothing interpolated into it, because everything ``run``'s fallback
#: could use to say more - the fault's text, the project's name, this gate's
#: own message builder - belongs to the half that just failed. The counterpart
#: of ``keel_gate.run``'s bare sentence, and it differs from that one on
#: purpose: this one omits the fault, which stderr carries instead.
STOP_DOUBLE_FAULT = (
    "KEEL STOP FAILED CLOSED: the stop gate could not account for this session "
    "AND could not word the refusal. That is keel's own defect, not this "
    "project's configuration. The fault itself is on stderr rather than in "
    "this sentence, because putting it here would mean formatting it and "
    "formatting is part of what failed. NEXT STEP: keel's hooks must be "
    "restored from git by the USER, from outside this session."
)


def cannot_account_message(
    event: KeelEvent, root: Path | None, detail: str, self_fault: str
) -> str:
    """The fail-closed refusal when the stop gate itself could not run.

    THE SAME THREE SHAPES ``keel_gate.cannot_evaluate_message`` established
    (T179 accept 2), reached the same way - via ``gate_self_fault`` and
    ``policy_parse_fault``, IMPORTED rather than re-derived (R15), so the two
    gates can never classify the identical exception two different ways:

    1. KEEL'S OWN DEFECT. ``self_fault`` is non-empty, so the message says so
       by name and site and ``.keel/keel-policy.md`` is never mentioned - it
       is not the subject.
    2. THE PROJECT'S ARMING FILE. ``policy_parse_fault`` shows it genuinely
       does not read, so it is named WITH the reason.
    3. NEITHER, SAID PLAINLY. The fault is reported verbatim and the message
       states that the arming file is NOT the cause.

    AND THE WORDS THEMSELVES ARE THE WRITE GATE'S WORDS, not a copy of them:
    every sentence the two gates share is IMPORTED from ``keel_gate`` - see
    ``keel_gate.SELF_FAULT_ATTRIBUTION`` and the block that defines it, which
    also names the three sentences deliberately NOT shared. A copy would drift,
    and did: the first cut of this function omitted the self-fault next step's
    "three times on 2026-08-19" clause, and only the head and the armed note
    below are this gate's own.

    ``root`` IS A PROXY, NOT ALWAYS THE ANSWER: ``None`` means the session's
    own governing project could not be resolved either - the walk ran out of
    budget, or resolving it raised in turn - so there is no project left to
    ask, and ``event.cwd`` stands in for it, mirroring
    ``keel_gate.failure_policy_roots``'s fallback for the identical shape of
    double fault.
    """
    proxy_root = root if root is not None else event.cwd
    armed_note = (
        "This session's governing project is armed, so the stop is refused "
        "rather than allowed to end unaccounted (R3)."
        if policy_present(proxy_root)
        else "keel could not confirm which project governs this session, "
        "which counts as armed here - an arming file the walk never reached, "
        "or never finished reaching, could still govern it - so the stop is "
        "refused rather than allowed to end unaccounted (R3)."
    )
    head = (
        f"KEEL STOP FAILED CLOSED: the stop gate could not account for the "
        f"session ({detail})."
    )
    if self_fault:
        return "\n".join(
            (
                head,
                armed_note,
                SELF_FAULT_ATTRIBUTION.format(fault=self_fault),
                NEXT_STEP_SELF_FAULT,
            )
        )
    config_fault = policy_parse_fault(proxy_root)
    if config_fault:
        return "\n".join(
            (
                head,
                armed_note,
                ARMING_FILE_IS_THE_FAULT.format(fault=config_fault),
                NEXT_STEP_ARMING_FILE,
            )
        )
    return "\n".join(
        (
            head,
            armed_note,
            ARMING_FILE_IS_NOT_THE_FAULT,
            NEXT_STEP_FAULT_UNATTRIBUTED,
        )
    )


def _cannot_account(event: KeelEvent, exc: BaseException) -> KeelVerdict:
    """The failure policy in one place: fail closed when armed, open when not.

    EVERYTHING IN HERE CAN RAISE, and that is why it is its own function:
    ``run`` wraps the call in a fallback that cannot. Reading the fault
    (``str(exc)`` on an exception carrying its own broken ``__str__``),
    resolving the project, testing for the arming file, and wording the
    refusal are all ordinary work - and this is ordinary work being done
    AFTER something has already gone wrong, which is the one context where
    "that call has never raised" is worth nothing. Only the resolution is
    caught here, because the answer to a failed resolution is a decision
    (treat the session as governed); the rest have no local answer, so they
    are left to the guard in ``run``.
    """
    detail = f"{type(exc).__name__}: {exc}"
    self_fault = gate_self_fault(exc)
    try:
        root, unresolved = resolve_governing_project(event.cwd)
        governed = unresolved or (root is not None and policy_present(root))
    except Exception:  # noqa: BLE001 - the failure policy must never fail
        root = None  # the resolution itself failed too; no project to name
        governed = True  # cannot tell -> the safer default is fail-closed
    if not governed:
        print(f"keel: stop failed open (unarmed project): {detail}", file=sys.stderr)
        return allow("unarmed project; stop error ignored", gate="internal_error")
    if self_fault:
        print(f"keel: THE FAULT IS KEEL'S OWN: {self_fault}", file=sys.stderr)
    return deny(
        cannot_account_message(event, root, detail, self_fault),
        gate="internal_error",
    )


def run(event: KeelEvent, env: Mapping[str, str] | None = None) -> KeelVerdict:
    """Evaluate, apply the declared failure policy, audit blocks, return.

    AND THE HANDLER HAS ITS OWN HANDLER, the same double-fault guard
    ``keel_gate.run`` carries (T179, restored here by T204). The reason it is
    not optional is that this gate does NOT own its own exit code: an
    exception escaping this function reaches ``keel_hook.main``, whose
    declared fail-open turns ANY escape into exit 0 - an allow. So a raise
    while merely WORDING the refusal would convert this gate's fail-closed
    deny into a session permitted to stop unaccounted, which is the exact
    inversion of the contract at the top of this file.

    THE FALLBACK IS DELIBERATELY INERT: a constant sentence and a verdict
    built from it, with no path resolution, no file read and no interpolation
    of the fault - formatting is one of the things that may just have failed.
    The fault itself goes to stderr AFTER the verdict exists, inside its own
    guard, because a fallback that can raise is not a fallback.
    """
    env = os.environ if env is None else env
    try:
        try:
            verdict = evaluate(event, env)
        except Exception as exc:  # noqa: BLE001 - the failure policy lives here
            verdict = _cannot_account(event, exc)
    except Exception as exc:  # noqa: BLE001 - the failure policy's OWN failure
        verdict = KeelVerdict(
            decision="deny", reason=STOP_DOUBLE_FAULT, gate="internal_error"
        )
        try:
            print(
                f"keel: the stop gate's failure policy failed too, so the refusal "
                f"is the bare one: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001 - nowhere left to report to
            pass  # the refusal above stands; it needed none of this to be built
    if verdict.blocking:
        touch_marker(event.session_id)
        _audit(event, verdict)
    elif env_on("KEEL_OVERRIDE", env):
        root = governing_project_if_armed(event.cwd)
        if root is not None:
            _nag_override(event, root, verdict)
    return verdict
