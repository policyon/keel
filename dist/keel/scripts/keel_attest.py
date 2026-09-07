#!/usr/bin/env python3
"""reconcile a session ledger against the audit log.

Contract
--------
Reads   : exactly two things, both read-only -
          ``<project>/.keel/plans/keel-plan-<sess8>.md``  the ledger
          ``<project>/.keel/audit/keel-audit.jsonl``      the record
          The project is ``--project``, else ``CLAUDE_PROJECT_DIR``, else the
          current directory; the session is ``--session`` - refused if the
          prefix is ambiguous, naming the count (never picked) - else
          ``SESSION_ENV_VAR`` (``CLAUDE_CODE_SESSION_ID``) from the
          environment, else this REFUSES, naming both - identity is read,
          never inferred from the log's own contents, and never guessed
          between two candidates either (see
          ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``).
Emits   : per task - its status marker, its declared route, the hand-off(s)
          that are evidence for it, and a verdict; then the discrepancy
          summary. ``--json`` emits the same report as a document. Every path
          it prints passes ``keel_redact`` (convention 5).
Writes  : nothing. Not the log, not the plan, not a cache. Strictly
          read-only, which is what makes it safe to run mid-session.
Argv    : ``--project DIR``, ``--session SESS8``, ``--json``.

Exit codes
----------
0  reconciled clean - every completed task has evidence, and every ``[~]``
   is backed by a hand-off that is genuinely open.
1  discrepancies found (they are listed; the report is still complete).
2  the report could not be produced at all.

What this does NOT do - the limit, stated plainly
-------------------------------------------------
An executor's report is returned to the orchestrator inside the harness's own
process. No hook observes that text and no channel exists on which the
subagent could sign it, so this tool cannot authenticate a report and must
never be described as doing so. What it attests is everything AROUND the
report: that a delegation carrying that task really was issued in this
session, to that agent type; that it closed, or did not; and what the
session recorded while it ran. That is provenance of the delegation, not
authenticity of the report. The residual risk it leaves untouched is a
report whose text was never produced by the agent it claims to come from.

The six discrepancies it raises
--------------------------------
1. UNATTESTED - a task marked ``[x]`` whose declared route is a subagent,
   with no ``handoff_start`` anywhere in the session. Recorded as
   delegated-and-done with no evidence any delegation happened. A task
   marked ``[x]`` whose route line did not parse at all (or was never
   written) is reported this way too, never as the weaker ``UNROUTED`` alone
   - the missing hand-off is the stronger fact and must not be masked by the
   missing route (see ``verdict_for``).
2. UNVERIFIED-INFLIGHT - a task marked ``[~]`` with no open hand-off on
   record. ``[~]`` is verified, never trusted; this is the same rule
   ``hooks/keel_stop.py`` enforces at stop time, applied here per task.
3. LADDER CAP EXCEEDED (R32) - a base task whose escalation-suffix series
   (``T9``, ``T9a``, ``T9b``, ...) reaches a round past ``FIX_ROUND_HARD_CAP``.
   Accounted from the ledger only: the fix-round ladder's other two limits
   (the resume ceiling and the fresh-context floor) name WHICH context and
   tier serve a round, and the audit log records neither, so only the cap -
   how many rounds happened at all - is checkable here; see the constants'
   comments for the honest boundary.
4. UNPARSEABLE TASK ID - a task line carrying a token shaped like a suffixed
   task id (a letter run, digits, trailing letters) that no id rule could
   parse. Such a task is invisible to hand-off matching AND to the ladder
   accounting above, so a malformed suffix would otherwise let a base task
   take unlimited further rounds without ever tripping the cap. It is named
   here instead. A task line with no id-shaped token at all is not this: it
   keeps its ``(unnamed #N)`` label and stays visible in the ledger table.
5. ORPHAN ACTIVITY (T233) - an ``activity`` line whose ``agent_id`` is
   non-null and falls OUTSIDE every delegation window recorded for that exact
   agent id in this session. A window runs from the ``handoff_start`` whose
   own return or ``subagent_stop`` names this agent id (``keel_stop``'s own
   matcher, imported rather than restated - R15) to that ``subagent_stop``,
   or to the end of the log when none closed it. Matching is by id alone,
   never by type - two same-typed delegations open at once are told apart
   the same way the stop gate tells them apart. An activity line whose
   ``agent_type`` is set but whose ``agent_id`` is null - the shape every
   line recorded before this field existed - is never guessed into a window
   by its type; it is counted and reported separately, as UNATTRIBUTABLE
   ACTIVITY, which is expected on any log with history predating the field
   and is not itself a discrepancy.
6. UNPARSEABLE ACTIVITY TIMESTAMP (T233) - an ``activity`` line whose
   ``agent_id`` IS non-null (unlike UNATTRIBUTABLE ACTIVITY above, this is a
   genuine orphan candidate) but whose ``ts`` is missing or does not parse.
   Such a record can be neither cleared as in-window nor condemned as
   ORPHAN ACTIVITY - both require a placeable timestamp - so per the
   failure policy below it is reported under its own verdict rather than
   dropped. Named a discrepancy, the same way UNPARSEABLE TASK ID is above.

Task <-> hand-off matching is heuristic, and deliberately so: the audit line
carries no task id, so a hand-off is evidence for a task when the task's id
appears in the hand-off's ``description``, else when it is the primary id of
its ``prompt_head``. An escalation id (``T16b``) attests its base task
(``T16``). This is why attest reports rather than blocks: a heuristic must
never become a stop condition, because the cost of its false positives is paid
by a user who cannot end the session.

Failure policy
--------------
FAIL-CLOSED. A reconciliation that cannot read what it must reconcile
returns 2 rather than printing a clean bill: a missing plan or an unreadable
log is a finding, not a pass (convention 12). Malformed audit LINES are the
one tolerated loss - JSONL's own guarantee is that one corrupt line costs
exactly one line - and they are counted and reported, never silently
dropped.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no network.
Matching is case-insensitive by default (convention 3). Every file read
names its encoding.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import keel_plans  # noqa: E402
from keel_events import KEEL_DIRNAME, audit_path, read_audit  # noqa: E402
from keel_gate import PLANS_RELPATH  # noqa: E402
from keel_redact import redact  # noqa: E402
from keel_stop import (  # noqa: E402
    BG_LAUNCH_MS,
    launch_agent_id,
    match_stops_to_launches,
    same_agent_id,
)

#: Ledger statuses, in the spelling the stop gate accounts for.
MARKERS: dict[str, str] = {
    "x": "done",
    " ": "open",
    "!": "blocked",
    "?": "needs-decision",
    "~": "in-flight",
}

#: Verdicts that make the run non-clean. Everything else is information.
#: Membership is by PREFIX (``is_discrepancy_verdict``), not exact string,
#: because ``LADDER_CAP_VERDICT_PREFIX`` below carries a dynamic round count
#: and cap - the other two entries are exact verdicts already, and a prefix
#: match on an exact string is the same as equality, so this widening changes
#: nothing about them.
LADDER_CAP_VERDICT_PREFIX = "LADDER CAP EXCEEDED"
#: A token shaped like an escalation-suffixed id that no id rule could parse.
#: It carries the offending token, so it is a prefix match too. This exists so
#: that a malformed suffix cannot buy a task silence: ladder accounting only
#: sees tasks whose id parsed, so an id that fails to parse must raise its own
#: finding rather than sliding past the cap check as an unnamed task.
UNPARSEABLE_ID_VERDICT_PREFIX = "UNPARSEABLE TASK ID"
#: T233 - an activity line whose agent_id names no window on record. A prefix
#: match (see ``is_discrepancy_verdict``) because the reported string carries
#: the offending agent id, the way the ladder-cap verdict carries its round
#: count.
ORPHAN_ACTIVITY_VERDICT_PREFIX = "ORPHAN ACTIVITY"
#: T233 - an activity line that names an agent (``agent_id`` non-null, a
#: genuine orphan candidate) but whose ``ts`` is missing or unparseable. It
#: can be neither cleared as in-window nor condemned as ``ORPHAN_ACTIVITY_
#: VERDICT_PREFIX`` - both require a placeable timestamp - so it gets its own
#: verdict rather than being silently skipped (fail-closed, :96-99). A prefix
#: match for the same reason as its siblings above: the reported string
#: carries the offending agent id and tool.
UNPARSEABLE_ACTIVITY_TS_VERDICT_PREFIX = "UNPARSEABLE ACTIVITY TIMESTAMP"
DISCREPANCY_VERDICTS: tuple[str, ...] = (
    "UNATTESTED",
    "UNVERIFIED-INFLIGHT",
    LADDER_CAP_VERDICT_PREFIX,
    UNPARSEABLE_ID_VERDICT_PREFIX,
    ORPHAN_ACTIVITY_VERDICT_PREFIX,
    UNPARSEABLE_ACTIVITY_TS_VERDICT_PREFIX,
)
#: UNATTRIBUTABLE ACTIVITY (T233) is deliberately NOT a discrepancy verdict:
#: an agent-typed line with no agent_id is the shape every activity line
#: carried before this field existed, and reporting history as a finding
#: would make every pre-T233 log permanently unclean. It is counted and
#: shown in its own report section instead (see ``attest``'s
#: ``unattributable_activity``).
UNATTRIBUTABLE_ACTIVITY_LABEL = "UNATTRIBUTABLE ACTIVITY"

#: R32 - the fix-round ladder (roadmap planning layer) as constants a check
#: reads (docs/keel-rules.md R32), applied to escalation-suffixed task ids
#: (``T16b`` attests base task ``T16``, per ``base_id`` above). ROUND is
#: defined precisely for accounting purposes: the bare id (``T9``) is round
#: 0, the original attempt; each escalation suffix is one further round in
#: series order (``T9a``=1, ``T9b``=2, ``T9c``=3, ...). These three constants
#: are the whole ladder as the owner ruled it (ATTEST-SIDE ACCOUNTING, no
#: gate-side state):
FIX_ROUND_RESUME_CEILING = 3
#: Rounds 1-3 MAY resume the same executor context; this is a procedural
#: permission, not a fact the audit log records, so it is asserted here only
#: as documentation - never checked (the log carries no context identity).
FIX_ROUND_FRESH_FLOOR = 4
#: Round 4 onward MUST be a fresh context, on the deep tier. Same limit as
#: above: documented, not verified, for the same reason.
FIX_ROUND_HARD_CAP = 5
#: No task gets a sixth round. THIS bound alone is checkable from the ledger
#: alone (a round either happened or did not); past it the ledger must carry
#: ``[!]`` or ``[?]``, never another attempt - and a base task whose highest
#: recorded round exceeds this cap is the one ladder finding this module
#: raises (see ``ladder_rounds`` and ``LADDER_CAP_VERDICT_PREFIX``).

_TASK_LINE_RE = re.compile(r"^\s*[-*] \[(.)\]\s*(.*)$")
#: A task identifier right after the checkbox. Two alternatives, tried in
#: order: (1) a letter-led id (``T9``, ``T16b``) followed by a WIDE
#: terminator that includes plain whitespace - this is what
#: ``templates/keel-plan-contract.md`` uses (``- [x] T9 <title>``, no
#: punctuation after the id); (2) the original letters-optional id followed
#: by a NARROW (punctuation-only) terminator, kept as-is so a bare numeral
#: id such as ``5) do the thing`` still resolves exactly as it did before -
#: widening (1) must never make a plain number in running prose look like an
#: id, so the whitespace terminator is only granted where a letter prefix
#: makes the token unambiguous.
#:
#: In alternative (1) ONLY, the escalation suffix is ``[A-Za-z]{0,2}`` rather
#: than ``[a-z]?``: matching is case-insensitive by default (convention 3), so
#: ``T16B`` must read as round 2 rather than failing the id shape, and a
#: doubled suffix (``T9aa``) must read as the round its mapping gives (27, see
#: ``fix_round_of``) rather than escaping the ladder as an unnamed task. Both
#: terminators are unchanged, which is what keeps ordinary words after an id
#: from false-positiving. Alternative (2) keeps its original ``[a-z]?`` on
#: purpose: keel writes escalation suffixes only on letter-led ids, which (1)
#: already covers under every terminator, so widening the digit-led legacy
#: shape would buy nothing and would start reading tokens like ``2FA:`` as
#: ids. Three suffix letters or more still fails here - by design, so the
#: token lands on ``_IDLIKE_TOKEN_RE`` below and is reported, never dropped.
_TASK_ID_RE = re.compile(
    r"^\**\s*("
    r"[A-Za-z]{1,4}\d{1,4}[A-Za-z]{0,2}(?=[:.)\]\s-]|$)"
    r"|[A-Za-z]{0,4}\d{1,4}[a-z]?(?=[:.)\]-])"
    r")"
)
#: The SHAPE of an escalation-suffixed task id - a letter run, digits, then a
#: trailing letter run - used only when ``_TASK_ID_RE`` did NOT match, to tell
#: a token that looks like a task id (``T9aaa``, ``T16b/c``) apart from a task
#: line that simply has no id (``- [x] Time spent auditing the log``). The
#: first is a parse failure and is reported as one (``UNPARSEABLE_ID_VERDICT_
#: PREFIX``); the second keeps its long-standing ``(unnamed #N)`` label, which
#: is visible in the ledger table. Deliberately NOT anchored to a terminator:
#: its whole job is to catch the tokens the terminators reject.
_IDLIKE_TOKEN_RE = re.compile(r"^\**\s*([A-Za-z]{1,4}\d{1,4}[A-Za-z]+)")
#: The legacy inline shape: ``| route: executor | ...`` on the task's own line.
_ROUTE_RE = re.compile(r"\|\s*route\s*:\s*([^|]*)", re.IGNORECASE)
#: The plan-contract shape: a ``Route:`` line - bulleted (``  - Route: ...``,
#: ``templates/keel-plan-contract.md``) or bare (``  Route: ...``, the shape
#: this repository's own recent ledgers write; see
#: ``attest-parser-misses-contract-ledgers`` for why the two must never be
#: read as different shapes again). Compiled from ``keel_plans.
#: ROUTE_LINE_PATTERN`` - the SAME pattern text the plan-contract gate checks
#: for presence at ``scripts/keel_plans.py:129`` - imported rather than
#: copied, so "a Route line" has exactly one definition project-wide and the
#: two can never drift apart on the next style change. Matched per physical
#: line - not on the flattened block blob - because the value must stop at
#: the end of ITS OWN line, not run into the next sub-bullet's text. The
#: value is cut at the first ``;`` so a trailing ``; files: ...`` clause does
#: not become part of the reported route. Case-insensitive
#: (convention 3, widening keel_plans's own case-sensitive presence check):
#: a ledger writing ``- route:`` or ``route:`` must resolve, not fall through
#: to an empty route and a spurious UNROUTED verdict.
_ROUTE_FIELD_RE = re.compile(keel_plans.ROUTE_LINE_PATTERN, re.IGNORECASE)
_TASK_KW_RE = re.compile(r"\bTASK\s+([A-Za-z]{0,4}\d{1,4}[a-z]?)\b", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s")


class AttestError(RuntimeError):
    """The report could not be produced. The caller returns 2 (fail-closed)."""


def base_id(task_id: str) -> str:
    """``T16b`` -> ``T16``: an escalation attests its base task. Uppercased."""
    match = re.match(r"^([A-Za-z]*\d+)", task_id or "")
    return match.group(1).upper() if match else (task_id or "").upper()


def is_discrepancy_verdict(verdict: str) -> bool:
    """Whether a verdict counts against ``clean`` - by prefix (see the
    comment on ``DISCREPANCY_VERDICTS``), so the dynamic ladder-cap verdict
    matches alongside the two fixed-string verdicts."""
    return any(verdict.startswith(entry) for entry in DISCREPANCY_VERDICTS)


def fix_round_of(task_id: str) -> int:
    """The escalation round a task id names: 0 for the bare id (the original
    attempt), else the 1-based position of its trailing letter run in the
    escalation series. This is pure string accounting on the id itself - it
    says nothing about which tier served the round or whether it resumed a
    context, because nothing in the audit log says that either (R32's
    resume/fresh split is not checked here).

    The suffix is read case-insensitively (convention 3), so ``T9b`` and
    ``T9B`` are both round 2, and a multi-letter suffix is read spreadsheet-
    column style, base-26 with no zero digit: ``a``..``z`` are 1..26, ``aa``
    is 27, ``ab`` 28, ``ba`` 53, ``zz`` 702. Nothing in keel's convention
    writes a doubled suffix on purpose - the mapping exists so that a doubled
    one is COUNTED (as a round far past ``FIX_ROUND_HARD_CAP``, hence flagged)
    instead of failing the id shape and slipping out of ladder accounting
    entirely. A non-letter suffix is not a round and reads as 0.
    """
    base = base_id(task_id)
    suffix = (task_id or "")[len(base):].lower()
    if not suffix or not suffix.isalpha() or not suffix.isascii():
        return 0
    value = 0
    for letter in suffix:
        value = value * 26 + (ord(letter) - ord("a") + 1)
    return value


def ladder_rounds(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """Highest escalation round recorded for each base task id in a ledger.

    The highest round reached, not merely how many suffixed entries exist -
    so a gap in the series (``a``, then ``c`` with no ``b`` ever written) is
    still read at its true depth, per the round definition on ``fix_round_of``.

    Tasks whose id did not parse are skipped here - they cannot be attributed
    to a base task - but they are NOT lost: ``verdict_for`` raises
    ``UNPARSEABLE_ID_VERDICT_PREFIX`` for any of them that looks like a
    suffixed id, so a malformed suffix is reported rather than buying its base
    task an unaccounted round.
    """
    rounds: dict[str, int] = {}
    for task in tasks:
        if not task["has_id"]:
            continue
        base = base_id(task["id"])
        rounds[base] = max(rounds.get(base, 0), fix_round_of(task["id"]))
    return rounds


def id_pattern(task_id: str) -> re.Pattern[str]:
    """Match a task id in free text, allowing a trailing escalation suffix.

    ``T16`` matches ``T16b`` and never ``T160`` or ``T1``: an id boundary is
    not a word boundary, because the suffix is part of the identifier.
    """
    return re.compile(
        r"(?<![A-Za-z0-9])" + re.escape(task_id) + r"[a-z]?(?![A-Za-z0-9])",
        re.IGNORECASE,
    )


def parse_ts_ms(value: Any) -> float | None:
    """ISO timestamp -> epoch milliseconds; None on any parse failure.

    keel stamps UTC with a ``Z``, which ``fromisoformat`` only accepts from
    Python 3.11, so the suffix is normalised first (the same normalisation
    ``keel_stop.py`` performs, for the same reason).
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


def classify_route(route: str) -> tuple[str, str]:
    """``(kind, display)`` for a declared route. Kinds decide the verdict."""
    text = (route or "").strip()
    low = text.casefold()
    if not low:
        return "none", "(none declared)"
    if low.startswith("executor"):
        return "executor", text
    if low.startswith("researcher"):
        return "researcher", text
    if low.startswith(("orchestrator", "self", "user")):
        return "self", text
    return "subagent", text


def session_of(entry: dict[str, Any]) -> Any:
    """Session identifier of an audit line, under either accepted key."""
    return entry.get("session", entry.get("session_id"))


def parse_plan(path: Path) -> list[dict[str, Any]]:
    """Every ledger task. A task owns its lines until the next task or heading.

    Ledgers wrap a task over several lines and interleave review notes, so a
    task's block is everything up to the next ``- [`` line or the next
    markdown heading - that block is where a route is looked for, in either
    of two shapes: the legacy inline ``| route: ...`` on the task's own line,
    or a ``Route:`` line - bulleted or bare, see ``_ROUTE_FIELD_RE`` - read
    from ``keel_plans``'s single shared definition of that shape. The legacy
    shape is tried first (it is unambiguous, being pipe-delimited); the
    ``Route:`` line is the fallback, read line-by-line so its value cannot
    swallow the next line's text.
    """
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise AttestError(f"cannot read the ledger {redact(str(path))}: {exc}") from exc

    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        match = _TASK_LINE_RE.match(line)
        if match:
            marker, rest = match.group(1), match.group(2)
            id_match = _TASK_ID_RE.match(rest)
            task_id = id_match.group(1).upper() if id_match else ""
            idlike_match = None if task_id else _IDLIKE_TOKEN_RE.match(rest)
            current = {
                "id": task_id or f"(unnamed #{len(tasks) + 1})",
                "has_id": bool(task_id),
                #: The raw token when the line CARRIES an id-shaped thing that
                #: no id rule could parse; "" when the line simply has no id.
                "idlike": idlike_match.group(1) if idlike_match else "",
                "marker": marker,
                "marker_name": MARKERS.get(marker, f"unknown '{marker}'"),
                "text": rest,
                "block": [rest],
            }
            tasks.append(current)
            continue
        if current is not None:
            if _HEADING_RE.match(line):
                current = None
                continue
            current["block"].append(line)

    for task in tasks:
        block_lines = task.pop("block")
        # The legacy shape is searched on the task's OWN line only (block_
        # lines[0], its opening line) - never the flattened block, which
        # would also scan review notes and the Accept clause's own prose.
        # This repository's ledger for this very fix quotes the shape
        # verbatim as an example (`` the legacy inline `| route: ... |`
        # shape``); scanning the whole block let that quoted example itself
        # satisfy the pattern and report a route of "...", which is exactly
        # the kind of false attestation this task exists to remove.
        route_match = _ROUTE_RE.search(block_lines[0]) if block_lines else None
        if route_match:
            route = route_match.group(1).strip()
        else:
            route = ""
            for line in block_lines:
                field_match = _ROUTE_FIELD_RE.search(line)
                if field_match:
                    route = field_match.group("value").split(";", 1)[0].strip()
                    break
        task["route"] = route
        task["route_kind"], task["route_display"] = classify_route(task["route"])
        task["title"] = re.sub(r"\s*\|.*$", "", task["text"]).strip()
    return tasks


#: The harness's own identifier for the session that is actually running -
#: not a keel convention, a DEPENDENCY on the harness, and therefore pinned
#: (``tests/test_keel_review_command.py`` asserts it by name and by shape)
#: rather than left as a literal repeated at each call site. Measured
#: present, and matching the acting session exactly, in every tool
#: invocation of this project's own harness; see
#: ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``.
SESSION_ENV_VAR = "CLAUDE_CODE_SESSION_ID"


def pick_session(records: list[dict[str, Any]], wanted: str | None) -> tuple[str, str]:
    """``(session_id, note)`` - identity is READ here, never inferred.

    A NAMED session (``wanted``, i.e. ``--session``) is matched as a PREFIX
    against every DISTINCT session id the log carries. This is not a guess:
    the caller supplied the id directly, and an 8-char prefix is a
    convenience for typing it - but a convenience is not license to pick
    between candidates when it is a convenience for MORE THAN ONE id, so a
    prefix matching more than one distinct session is REFUSED, naming how
    many matched, rather than resolved by taking whichever the scan reached
    first. A prefix matching exactly one id resolves exactly as before,
    whether the prefix is short or the caller passed the full id.

    Absent ``wanted``, the ONLY other source is ``SESSION_ENV_VAR`` in the
    environment - never the log. Three specifications tried inferring the
    acting session from the log's own contents instead (newest
    ``session_start``; newest start that has not ended; newest event of any
    kind) and each one printed success while attributing a report or a
    verdict to a session that had not reached it - see
    ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md`` for why
    each failed. None of that reasoning survives here: when neither
    ``wanted`` nor the environment variable answers, this function REFUSES,
    naming both routes, rather than falling back to a guess between them.
    """
    if wanted and wanted.strip():
        want = wanted.strip().casefold()
        matches: list[str] = []
        for entry in records:
            value = session_of(entry)
            if (
                isinstance(value, str)
                and value.casefold().startswith(want)
                and value not in matches
            ):
                matches.append(value)
        if len(matches) > 1:
            raise AttestError(
                f"--session {wanted.strip()!r} matches {len(matches)} distinct "
                "session ids in the audit log - a verdict is never attributed "
                "to a guessed session (nothing was written); pass a longer, "
                "unambiguous prefix"
            )
        if matches:
            return matches[0], ""
        return wanted.strip(), f"no audit line carries session '{wanted.strip()}'"

    from_env = os.environ.get(SESSION_ENV_VAR)
    if isinstance(from_env, str) and from_env.strip():
        return from_env.strip(), ""

    raise AttestError(
        f"no session to attribute this to: pass --session <sess8>, or set "
        f"{SESSION_ENV_VAR} in the environment - neither was found (identity "
        "is read, never inferred from the log)"
    )


def match_handoff(handoff: dict[str, Any], task_ids: list[str]) -> tuple[list[str], str]:
    """Which tasks a hand-off is evidence for, and how it was matched.

    ``description`` first, because a description that names the task is the
    strong signal; ``prompt_head`` second, restricted to its PRIMARY id, so a
    prompt that merely cross-references another task does not attest it.
    """
    description = handoff.get("description") or ""
    hits = [tid for tid in task_ids if id_pattern(tid).search(description)]
    if hits:
        return hits, "description"
    head = handoff.get("prompt_head") or ""
    if not head:
        return [], ""
    keyword = _TASK_KW_RE.search(head)
    if keyword:
        primary = base_id(keyword.group(1))
        return ([primary], "prompt_head") if primary in task_ids else ([], "")
    best, best_at = "", None
    for task_id in task_ids:
        found = id_pattern(task_id).search(head)
        if found and (best_at is None or found.start() < best_at):
            best, best_at = task_id, found.start()
    return ([best], "prompt_head") if best else ([], "")


def resolve_handoffs(
    starts: list[dict[str, Any]],
    ends: list[dict[str, Any]],
    stops: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Pair each launch with its return by ``keel_stop.py``'s own rules.

    Not "in the same spirit as": ``BG_LAUNCH_MS``, ``launch_agent_id`` and
    ``match_stops_to_launches`` are IMPORTED from that module rather than
    restated here. This sentence once read "exactly as ``keel_stop.py`` does"
    and was false - the gate matched a blank stop against a blank launch and
    this module refused to, so one of them was silently closing hand-offs the
    other reported as open.

    TWO EXACT KEYS, AND NO THIRD ROUTE (T102). A launch pairs with its RETURN
    by ``tool_use_id``, and a stop attaches to the launch whose ``agent_id`` it
    NAMES. Both rules used to have a fallback and both fallbacks were the same
    mistake: the return side keyed on ``(subagent_type, description)``, which
    pairs two records that name neither, and the stop side took the
    most-recently-launched still-open start of the same agent TYPE, which is a
    guess whenever two agents of a kind are running at once. A type is not an
    identity. What replaces them is nothing: a return this module cannot
    attribute closes no launch, and a stop it cannot attribute is returned as
    an unattributable gap, which is what this function's answer has always
    been for.

    A return that lands within ``BG_LAUNCH_MS`` of its launch is a
    background-launch acknowledgment, not a completion, and leaves the
    hand-off open.

    ONE DIFFERENCE IS DELIBERATE and is not drift: the gate additionally
    presumes a quiet background hand-off finished after ``LIVENESS_MS``, and
    this module never does. A gate must decide; a report must not invent a
    closure no record shows. So a hand-off open here may read closed at the
    gate, and the reason is stated rather than reconciled away.

    Returns the stop signals that could not be attached to any hand-off.
    """
    ends_by_id: dict[str, dict[str, Any]] = {}
    for end in ends:
        tool_use_id = end.get("tool_use_id")
        if isinstance(tool_use_id, str) and tool_use_id.strip():
            ends_by_id[tool_use_id.strip()] = end

    for start in starts:
        tool_use_id = start.get("tool_use_id")
        end: dict[str, Any] | None = None
        if isinstance(tool_use_id, str) and tool_use_id.strip():
            end = ends_by_id.get(tool_use_id.strip())
        start_ms = parse_ts_ms(start.get("ts"))
        end_ms = parse_ts_ms(end.get("ts")) if end else None
        start["_end"] = end
        start["_stop"] = None
        start["_agent_id"] = launch_agent_id(start, end)
        start["_start_ms"] = start_ms
        start["_foreground_close"] = bool(
            end is not None
            and start_ms is not None
            and end_ms is not None
            and (end_ms - start_ms) >= BG_LAUNCH_MS
        )

    # The shared matcher decides which launch each stop belongs to; the only
    # work left here is turning its index answer back into this module's
    # private keys, and reporting everything it did NOT match as a gap.
    ordered_stops = sorted(stops, key=lambda record: record.get("ts") or "")
    matched = match_stops_to_launches(
        [start["_agent_id"] for start in starts], ordered_stops
    )
    for index, stop in matched.items():
        starts[index]["_stop"] = stop
    attached = {id(stop) for stop in matched.values()}
    unassigned: list[dict[str, Any]] = [
        stop for stop in ordered_stops if id(stop) not in attached
    ]

    for start in starts:
        if start["_stop"] is not None:
            start["_closure"] = "handoff_end+subagent_stop" if start["_end"] else "subagent_stop"
        elif start["_foreground_close"]:
            start["_closure"] = "handoff_end"
        elif start["_end"] is not None:
            start["_closure"] = "handoff_end(bg-ack only, no stop)"
        else:
            start["_closure"] = "NONE"
        start["_open"] = start["_closure"] in ("NONE", "handoff_end(bg-ack only, no stop)")
    return unassigned


def delegation_windows(
    starts: list[dict[str, Any]], log_end_ms: float | None
) -> list[tuple[str, float, float]]:
    """Every delegation window this session recorded, as ``(agent_id, begin, end)``.

    Built from exactly the attribution ``resolve_handoffs`` already computed
    onto each ``start`` (``_agent_id``, ``_start_ms``, ``_stop``) - not a
    second pass over agent TYPE, and not a second matcher: the join key is
    ``keel_stop.same_agent_id``'s, imported rather than restated (R15). A
    start naming no agent id opens no window at all, because a blank id is
    not a value ``same_agent_id`` ever matches.

    ANYTHING UNPARSEABLE WIDENS THE WINDOW, never narrows it: an orphan
    verdict must never rest on a timestamp keel could not itself read. A
    launch whose own timestamp is unparseable opens its window from the
    beginning of time; a delegation with no ``subagent_stop`` on record - or
    whose stop's own timestamp is unparseable - closes at ``log_end_ms``, the
    session's own last recorded timestamp (its "end of log"), or at the end
    of time when even that could not be established.
    """
    windows: list[tuple[str, float, float]] = []
    for start in starts:
        agent_id = start.get("_agent_id")
        if not isinstance(agent_id, str) or not agent_id.strip():
            continue
        begin = start.get("_start_ms")
        if begin is None:
            begin = float("-inf")
        stop = start.get("_stop")
        end = parse_ts_ms(stop.get("ts")) if stop else None
        if end is None:
            end = log_end_ms if log_end_ms is not None else float("inf")
        windows.append((agent_id, begin, end))
    return windows


def activity_is_orphan(
    agent_id: str, ts_ms: float, windows: list[tuple[str, float, float]]
) -> bool:
    """True when no recorded window for THIS EXACT agent id contains ``ts_ms``."""
    return not any(
        same_agent_id(window_id, agent_id) and begin <= ts_ms <= end
        for window_id, begin, end in windows
    )


def handoff_view(start: dict[str, Any]) -> dict[str, Any]:
    """One hand-off as the report shows it - redacted, never raw."""
    return {
        "ts": start.get("ts"),
        "agent": start.get("subagent_type") or "(none)",
        "description": redact(start.get("description") or ""),
        "tool_use_id": start.get("tool_use_id"),
        "matched_via": start.get("_how") or "(unmatched)",
        "closure": start["_closure"],
        "open": start["_open"],
    }


def verdict_for(task: dict[str, Any], mine: list[dict[str, Any]], session_open: bool) -> str:
    """The verdict rules, in priority order. Three of them are discrepancies.

    The unparseable-id rule comes first because it is the one verdict about
    the task LINE rather than about its evidence: a task whose id could not be
    parsed cannot be matched to a hand-off (it is not in ``task_ids``) and
    cannot be counted into the fix-round ladder, so the parse failure is the
    finding, and reporting it is what keeps it out of the silent path.

    ``marker == "x"`` is checked BEFORE the generic ``kind == "none"``
    fallback, not after it: a completed task with an unparseable (missing)
    route is a STRONGER finding than a merely undeclared route on a task with
    no completion claim, and the weaker verdict must never be allowed to
    mask the stronger one - see ``attest-parser-misses-contract-ledgers``'s
    second entry for the fail-open this ordering used to produce. Both facts
    are carried in one verdict string (still an ``UNATTESTED``-prefixed
    discrepancy, per ``DISCREPANCY_VERDICTS``) rather than picking one and
    discarding the other. A task that never claimed completion (``[ ]``,
    ``[!]``, ``[?]``) has no hand-off to miss, so it keeps the plain
    ``UNROUTED`` verdict below - that case is information, not a discrepancy.
    """
    marker, kind = task["marker"], task["route_kind"]
    if task.get("idlike"):
        return f"{UNPARSEABLE_ID_VERDICT_PREFIX} ({task['idlike']})"
    if mine:
        if any(start["_open"] for start in mine):
            return "ATTESTED (a hand-off never closed)" if marker == "x" else "IN-FLIGHT"
        return "ATTESTED"
    if marker == "~":
        return "IN-FLIGHT (unmatched hand-off open)" if session_open else "UNVERIFIED-INFLIGHT"
    if kind == "self":
        return "SELF (no delegation declared - nothing to attest)"
    if marker == "x":
        if kind == "none":
            return "UNATTESTED (route did not parse - no route declared, no hand-off on record)"
        return "UNATTESTED"
    if kind == "none":
        return "UNROUTED (no route declared)"
    if marker == " ":
        return "PENDING (not started - no hand-off yet)"
    return f"NO-HANDOFF ({kind} route, marker '{marker}')"


def attest(project: Path, wanted_session: str | None) -> dict[str, Any]:
    """The whole reconciliation as a plain dictionary; also ``--json``."""
    project = Path(project)
    log_path = audit_path(project)
    if not log_path.is_file():
        raise AttestError(
            f"no audit log at {redact(str(log_path))} - this project has recorded "
            f"nothing to reconcile against"
        )
    records = read_audit(project)
    if not records:
        raise AttestError(f"the audit log {redact(str(log_path))} holds no readable line")

    session_id, note = pick_session(records, wanted_session)
    sess8 = session_id[:8]
    plan_path = project.joinpath(*PLANS_RELPATH, f"keel-plan-{sess8}.md")
    if not plan_path.is_file():
        raise AttestError(f"no ledger for this session at {redact(str(plan_path))}")
    tasks = parse_plan(plan_path)

    session_records = [entry for entry in records if session_of(entry) == session_id]
    starts = sorted(
        [entry for entry in session_records if entry.get("event") == "handoff_start"],
        key=lambda record: record.get("ts") or "",
    )
    ends = [entry for entry in session_records if entry.get("event") == "handoff_end"]
    stops = [entry for entry in session_records if entry.get("event") == "subagent_stop"]
    actions = [entry for entry in session_records if entry.get("event") == "activity"]
    blocks = [
        entry for entry in session_records if entry.get("event") in ("gate_block", "stop_block")
    ]

    unassigned_stops = resolve_handoffs(starts, ends, stops)
    task_ids = [task["id"] for task in tasks if task["has_id"]]
    for start in starts:
        hits, how = match_handoff(start, task_ids)
        start["_tasks"], start["_how"] = hits, how
    session_open = any(start["_open"] for start in starts)

    report: dict[str, Any] = {
        "project": redact(str(project.resolve())),
        "log": redact(str(log_path)),
        "plan": redact(str(plan_path)),
        "session": sess8,
        "session_id": session_id,
        "notes": [note] if note else [],
        "counts": {
            "tasks": len(tasks),
            "handoff_start": len(starts),
            "handoff_end": len(ends),
            "subagent_stop": len(stops),
            "activity": len(actions),
            "gate_and_stop_blocks": len(blocks),
            "session_records": len(session_records),
        },
        "tasks": [],
        "discrepancies": [],
        "unclosed": [],
        "unmatched_handoffs": [],
        "unattributable_activity": [],
        "gaps": [],
    }

    for task in tasks:
        mine = [start for start in starts if task["id"] in start["_tasks"]]
        verdict = verdict_for(task, mine, session_open)
        evidence = [handoff_view(start) for start in mine]
        row = {
            "id": task["id"],
            "marker": task["marker"],
            "status": task["marker_name"],
            "route": task["route_display"],
            "route_kind": task["route_kind"],
            "title": task["title"][:70],
            "evidence": evidence,
            "activity_by_agent": dict(
                Counter(
                    action.get("agent_type") or "(main session)"
                    for action in actions
                )
            )
            if evidence
            else {},
            "verdict": verdict,
        }
        report["tasks"].append(row)
        if is_discrepancy_verdict(verdict):
            report["discrepancies"].append(row)

    # R32 ladder cap: checkable from the ledger alone (see the constants'
    # comments above for why the resume-ceiling and fresh-context-floor
    # limits are documentation only, not asserted here). A base task at or
    # under FIX_ROUND_HARD_CAP stays clean; only exceeding it is a finding.
    for base, rounds in sorted(ladder_rounds(tasks).items()):
        if rounds > FIX_ROUND_HARD_CAP:
            verdict = f"{LADDER_CAP_VERDICT_PREFIX} ({rounds} rounds, cap {FIX_ROUND_HARD_CAP})"
            row = {
                "id": base,
                "marker": "",
                "status": "ladder",
                "route": "",
                "route_kind": "",
                "title": f"fix-round ladder: {rounds} round(s) recorded for {base}"[:70],
                "evidence": [],
                "activity_by_agent": {},
                "verdict": verdict,
            }
            report["discrepancies"].append(row)

    # T233 - ORPHAN ACTIVITY and UNATTRIBUTABLE ACTIVITY, containment by
    # agent id alone (never by type; R15, the shared matcher is imported,
    # not restated - see ``delegation_windows`` and ``activity_is_orphan``).
    log_end_ms = None
    for entry in session_records:
        ts_ms = parse_ts_ms(entry.get("ts"))
        if ts_ms is not None and (log_end_ms is None or ts_ms > log_end_ms):
            log_end_ms = ts_ms
    windows = delegation_windows(starts, log_end_ms)
    for action in actions:
        agent_id = action.get("agent_id")
        agent_type = action.get("agent_type")
        if isinstance(agent_id, str) and agent_id.strip():
            act_ts = parse_ts_ms(action.get("ts"))
            # An unparseable or missing timestamp cannot prove containment OR
            # its absence, so this record can be neither cleared as
            # in-window nor condemned as an orphan. It names an agent (a
            # genuine orphan candidate), so fail-safe here means reported
            # under its own verdict - never silently skipped, and never
            # claimed as ORPHAN ACTIVITY, which would assert a containment
            # fact this record cannot support (see :96-99).
            if act_ts is None:
                verdict = (
                    f"{UNPARSEABLE_ACTIVITY_TS_VERDICT_PREFIX} "
                    f"(agent {agent_id}, tool {action.get('tool')}, "
                    f"ts {action.get('ts')!r})"
                )
                row = {
                    "id": "(unplaceable)",
                    "marker": "",
                    "status": "unparseable-activity-ts",
                    "route": "",
                    "route_kind": "",
                    "title": f"{action.get('tool')} {action.get('detail') or ''}".strip()[:70],
                    "evidence": [],
                    "activity_by_agent": {},
                    "verdict": verdict,
                }
                report["discrepancies"].append(row)
                continue
            if not activity_is_orphan(agent_id, act_ts, windows):
                continue
            verdict = f"{ORPHAN_ACTIVITY_VERDICT_PREFIX} (agent {agent_id})"
            row = {
                "id": "(orphan)",
                "marker": "",
                "status": "orphan-activity",
                "route": "",
                "route_kind": "",
                "title": f"{action.get('tool')} {action.get('detail') or ''}".strip()[:70],
                "evidence": [],
                "activity_by_agent": {},
                "verdict": verdict,
            }
            report["discrepancies"].append(row)
        elif isinstance(agent_type, str) and agent_type.strip():
            # agent_type set, agent_id null: the shape recorded before this
            # field existed. Never guessed into a window by its type - just
            # counted and shown, its own state, not a discrepancy.
            report["unattributable_activity"].append(
                {
                    "ts": action.get("ts"),
                    "agent_type": agent_type,
                    "tool": action.get("tool"),
                    "detail": action.get("detail"),
                }
            )
        # else: both null - main-session work, never an orphan candidate.

    if report["unattributable_activity"]:
        report["gaps"].append(
            f"{len(report['unattributable_activity'])} activity line(s) carry an "
            "agent_type but no agent_id - expected on any log with history from "
            "before T233 added the field; not attributed by type, not reported as "
            "an orphan"
        )

    report["unclosed"] = [handoff_view(s) for s in starts if s["_closure"] == "NONE"]
    report["unmatched_handoffs"] = [handoff_view(s) for s in starts if not s["_tasks"]]
    if unassigned_stops:
        report["gaps"].append(
            f"{len(unassigned_stops)} subagent_stop line(s) could not be attached to a "
            f"hand-off (an empty agent_type cannot be attributed)"
        )
    if not starts and tasks:
        report["gaps"].append(
            "this session recorded no hand-off at all: either nothing was delegated, "
            "or the capture hook was not registered while it ran"
        )
    report["clean"] = not report["discrepancies"]
    return report


def render(report: dict[str, Any]) -> str:
    """The human report. Complete whether or not it found anything."""
    out: list[str] = []
    write = out.append
    counts = report["counts"]
    write("=" * 72)
    write(f"KEEL ATTESTATION - session {report['session']}")
    write("=" * 72)
    write(f"project : {report['project']}")
    write(f"ledger  : {report['plan']}")
    write(f"log     : {report['log']}")
    write(
        "counts  : {tasks} task(s) | {handoff_start} handoff_start, {handoff_end} "
        "handoff_end, {subagent_stop} subagent_stop, {activity} activity, "
        "{gate_and_stop_blocks} block(s)".format(**counts)
    )
    write("")
    write("SCOPE: this attests the DELEGATION RECORD around each report - that it")
    write("happened, to whom, and whether it closed. It does NOT authenticate any")
    write("report's text; no channel exists on which a subagent could sign it.")
    for note in report["notes"]:
        write(f"NOTE: {note}")
    write("")

    write(f"TASK LEDGER ({len(report['tasks'])} task(s))")
    write("-" * 72)
    for task in report["tasks"]:
        write(
            f"{task['id']:<8} [{task['marker']}] {task['route'][:30]:<30} {task['verdict']}"
        )
        for item in task["evidence"]:
            write(
                f"      -> {item['ts']} {item['agent']:<16} closed={item['closure']} "
                f"(matched via {item['matched_via']})"
            )
    write("")

    write(f"DISCREPANCIES ... {len(report['discrepancies'])}")
    for task in report["discrepancies"]:
        write(f"  {task['verdict']:<22} {task['id']:<8} [{task['marker']}] {task['title']}")
    if not report["discrepancies"]:
        write("  none: every completion has evidence and every [~] has an open hand-off")
    write("")

    write(f"UNCLOSED HAND-OFFS (no return, no stop signal) ... {len(report['unclosed'])}")
    for item in report["unclosed"]:
        write(f"  {item['ts']} {item['agent']:<16} {item['description'][:44]}")
    if report["unmatched_handoffs"]:
        write(f"HAND-OFFS MATCHING NO TASK ... {len(report['unmatched_handoffs'])}")
        for item in report["unmatched_handoffs"]:
            write(f"  {item['ts']} {item['agent']:<16} {item['description'][:44]}")
    if report["unattributable_activity"]:
        write(
            f"{UNATTRIBUTABLE_ACTIVITY_LABEL} (agent_type set, no agent_id - "
            f"expected on history from before T233) ... "
            f"{len(report['unattributable_activity'])}"
        )
        for item in report["unattributable_activity"]:
            write(f"  {item['ts']} {item['agent_type']:<16} {item['tool']} {item['detail']}")
    for gap in report["gaps"]:
        write(f"  GAP {gap}")
    write("")
    write("(read-only report; nothing was written.)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """reconcile a session's ledger against the audit log"""
    parser = argparse.ArgumentParser(
        prog="keel attest",
        description="reconcile a session's ledger against the keel audit log",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument(
        "--session", default=None,
        help=f"8-char session id; default: ${SESSION_ENV_VAR} from the environment",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    root = args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    if not (Path(root) / KEEL_DIRNAME).is_dir():
        print(f"keel attest: {redact(str(Path(root)))} has no {KEEL_DIRNAME}/", file=sys.stderr)
        return 2
    try:
        report = attest(Path(root), args.session)
    except AttestError as exc:
        print(f"keel attest: {exc}", file=sys.stderr)
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(render(report))
    return 0 if report["clean"] else 1


if __name__ == "__main__":
    sys.exit(main())
