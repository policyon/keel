#!/usr/bin/env python3
"""keel review - one verdict, written to the record as an event.

Contract
--------
Reads   : the project's own audit log (``.keel/audit/keel-audit.jsonl``), and
          ONLY to resolve which session this verdict belongs to - the same
          question ``keel attest`` answers, answered by the same function
          (``keel_attest.pick_session``) rather than by a second rule that
          could drift from it: the session named by ``--session``, else
          ``CLAUDE_CODE_SESSION_ID`` from the environment, else this command
          REFUSES, naming both (identity is read, never inferred from the
          log - see
          ``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``).
          The project root is ``--project``, else ``CLAUDE_PROJECT_DIR``,
          else the current directory - the resolution order ``keel attest``
          already uses.
Emits   : one line on stdout naming what was recorded, and its errors on
          stderr. It is not a gate and has no findings of its own.
Writes  : exactly ONE append-only line to
          ``<project>/.keel/audit/keel-audit.jsonl`` via
          ``keel_events.append_audit``, which stamps ``v`` and ``ts`` and
          passes the whole line through the redaction chokepoint
          (``keel_redact.redact_mapping``, inside ``_append_jsonl``). Nothing
          here opens the log itself. Nothing else on disk is touched: no
          ledger is rewritten, no queue line is written - a verdict is an
          observation about work, not work.
Argv    : ``--task Tn --verdict pass|fail [--notes TEXT] [--session ID]
          [--project DIR]``.

The event
---------
One shape, fixed::

    {"v": 1, "ts": ..., "event": "review", "session": ..., "task": ...,
     "verdict": "pass"|"fail", "notes": ...}

``v`` and ``ts`` come from ``keel_events`` (the same stamp every audit line
carries, UTC with an explicit ``Z``); the other five are this module's. The
key ORDER above is the order written, because ``_append_jsonl`` stamps
``v``/``ts`` first and then merges the record - so a review line reads like
every other line in the log rather than like a guest in it.

THE VOCABULARY IS TWO WORDS AND THE CLI IS WHERE IT IS ENFORCED (see
``VERDICTS``). A third word - "partial", "pass with notes", "mostly" - is
refused with a named error and NOTHING is written, because a verdict a reader
cannot count is not a verdict: the page counts failures to raise an alert, and
``keel attest`` will one day count them against the ledger. Case is folded on
the way in and the canonical spelling is what lands, so ``PASS`` is accepted
and recorded as ``pass`` (convention 3), while a word that is not one of the
two is not guessed at.

WHY ``--session`` IS NEVER GUESSED. A verdict belongs to the session that
reached it; attributing it to the wrong one would put it in the wrong round on
the page and reconcile it against the wrong ledger. So the session is READ -
STATED by the caller (``--session``), or else read from
``CLAUDE_CODE_SESSION_ID`` in the environment - NEVER inferred from the log's
own contents (three prior specifications tried exactly that and each printed
success while mis-attributing a verdict; see ``keel_attest.pick_session`` and
``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md`` for why).
Where neither ``--session`` nor the environment variable answers, this
command fails closed with an error naming BOTH routes rather than writing a
line with a null session (convention 7).

WHAT THE TASK ID MAY CONTAIN, AND WHY IT IS A WHITELIST. The recorded ``task``
reaches a reader that builds a REGULAR EXPRESSION from it - the vendored
orchestration page pairs a review to an agent card with
``new RegExp("\\b"+r.task+"\\b","i")`` - so an id carrying regex syntax would
at best match the wrong card and at worst throw inside the page's render tick.
``_TASK_RE`` therefore admits letters, digits and ``. _ - :`` only, every one
of which is inert in that position, and refuses anything else with a named
error instead of sanitising it into a different id (R5: data from an argument
never becomes syntax somewhere else). It is applied AFTER redaction, so a
value the screen rewrote cannot slip past the shape the writer checked.

Exit codes
----------
0   the line was written.
2   it was not: an unadopted project, an unknown verdict, an unusable task id,
    or no session to attribute the verdict to. Never 1 - recording a verdict
    is not a check and has no findings of its own to report.

Failure policy
--------------
FAIL-CLOSED. Every refusal above prints one line naming what was wrong and
writes NOTHING (convention 7, convention 12): a half-written verdict, or one
attributed to a session nobody named, would be worse than the prose it was
meant to replace, because a record is trusted in a way prose is not.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No network, no subprocess, no
shell. Nothing read from the log is interpolated into anything (R5).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
for _extra in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR.parent / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from keel_attest import AttestError, pick_session  # noqa: E402
from keel_events import KEEL_DIRNAME, append_audit, read_audit  # noqa: E402
from keel_redact import redact  # noqa: E402

#: The wire value. The vendored orchestration page already renders exactly
#: this event name, and ``review`` is what the predecessor's log carried, so
#: the value is inherited rather than invented.
REVIEW_EVENT = "review"

#: THE WHOLE VOCABULARY. Two words, in the spelling a reader counts on.
VERDICTS: tuple[str, ...] = ("pass", "fail")

#: How much of a review note reaches the audit line. A note, not a report:
#: the review itself lives in the session's prose and in the reviewer's own
#: output, and an audit log that carried whole reviews would stop being
#: readable at the line level. Same reasoning, and the same order of
#: magnitude, as ``keel_capture.PROMPT_HEAD_CHARS``.
NOTES_CHARS = 500

#: The shape a recorded task id may have - see "WHAT THE TASK ID MAY CONTAIN"
#: in the module contract. A whitelist, because the value ends up inside a
#: reader's regular expression, and because an id is a name rather than prose.
_TASK_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z")


class ReviewError(Exception):
    """A verdict that cannot be recorded, carrying the sentence to print."""


def normalise_verdict(value: str) -> str:
    """The canonical verdict, or ``ReviewError`` naming the two that exist.

    Case is folded (convention 3) and surrounding space is dropped, so the
    word a human typed is accepted in the spelling a human types it. Anything
    that is still not one of ``VERDICTS`` is refused BY NAME rather than
    coerced towards either answer: "mostly passed" is not a pass, and guessing
    which way it leans is precisely the judgment this record exists to stop
    being implicit.
    """
    folded = (value or "").strip().casefold()
    if folded not in VERDICTS:
        raise ReviewError(
            f"unknown verdict {value!r}: the vocabulary is exactly "
            f"{' and '.join(VERDICTS)} (nothing was written)"
        )
    return folded


def normalise_task(value: str) -> str:
    """The recorded, redacted task id, or ``ReviewError`` saying why not.

    Redaction runs FIRST and the shape is checked on what it returned, so the
    id written is the id checked - a value the screen rewrote (a denied name,
    a marked region) never reaches the log wearing a shape nothing verified.
    """
    task = redact((value or "").strip())
    if not _TASK_RE.match(task):
        raise ReviewError(
            f"unusable task id {value!r}: a recorded id is letters, digits, "
            "'.', '_', '-' or ':' (nothing was written)"
        )
    return task


def resolve_session(project: Path, wanted: str | None) -> tuple[str, str]:
    """``(session_id, note)`` for this verdict - never a guessed one.

    ``keel_attest.pick_session``'s answer, UNCHANGED - the one resolver both
    commands share (T193): the session ``wanted`` names, matched as a prefix
    against the log exactly as ``keel attest`` matches it, else
    ``CLAUDE_CODE_SESSION_ID`` read from the environment, else ``AttestError``
    naming both routes. That error is re-raised as this module's own
    ``ReviewError`` because the caller of ``keel review`` should be told to
    pass ``--session`` (or run where the environment variable is set) rather
    than be told about attestation.

    ``note`` is non-empty when the caller named a session the log does not
    carry. That is NOT an error - a verdict may be recorded for a session
    whose lines are elsewhere - but it is never silent: ``main`` prints it.
    """
    try:
        return pick_session(read_audit(project), wanted)
    except AttestError as exc:
        raise ReviewError(str(exc)) from exc


def review_record(session_id: str, task: str, verdict: str, notes: str) -> dict[str, str]:
    """The event, built from values that have already been normalised.

    ``notes`` is redacted here and truncated to ``NOTES_CHARS``; ``task``
    arrived redacted from ``normalise_task``. Neither call is the screen this
    line depends on - the chokepoint in ``keel_events._append_jsonl`` screens
    every line whatever built it, and ``redact`` is idempotent against that
    second pass - it is the same belt-and-braces every captured value gets in
    ``keel_capture.py``, applied here so that truncation cannot cut a
    ``<keel-private>`` region in half and leave its content behind.
    """
    return {
        "event": REVIEW_EVENT,
        "session": session_id,
        "task": task,
        "verdict": verdict,
        "notes": redact(notes or "")[:NOTES_CHARS],
    }


def main(argv: list[str] | None = None) -> int:
    """record a review verdict as an event in the audit log"""
    parser = argparse.ArgumentParser(
        prog="keel review",
        description="append one review verdict to the keel audit log",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument("--task", required=True, help="the ledger task id the verdict is on")
    parser.add_argument(
        "--verdict", required=True, help=f"one of: {', '.join(VERDICTS)}"
    )
    parser.add_argument("--notes", default="", help="one line on why (optional)")
    parser.add_argument(
        "--session", default=None,
        help="session id; default: $CLAUDE_CODE_SESSION_ID from the environment",
    )
    args = parser.parse_args(argv)

    root = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not (root / KEEL_DIRNAME).is_dir():
        print(f"keel review: {redact(str(root))} has no {KEEL_DIRNAME}/", file=sys.stderr)
        return 2
    try:
        verdict = normalise_verdict(args.verdict)
        task = normalise_task(args.task)
        session_id, note = resolve_session(root, args.session)
    except ReviewError as exc:
        print(f"keel review: {exc}", file=sys.stderr)
        return 2
    if note:
        print(f"keel review: {note}", file=sys.stderr)
    append_audit(root, review_record(session_id, task, verdict, args.notes))
    print(f"keel review: recorded {verdict} on {task} for session {session_id[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
