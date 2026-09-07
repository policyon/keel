#!/usr/bin/env python3
"""T135 - the review history keel reached before it could record it.

Why this is a SEPARATE program from ``keel review``
---------------------------------------------------
``scripts/keel_review.py`` records a verdict AS IT IS REACHED: it stamps the
line with the clock, attributes it to the session the log says is current, and
writes exactly the seven fields T129 fixed. Every one of those defaults is
right for a live verdict and wrong for a reconstructed one, so this file does
not bend them - it is a one-shot beside that command rather than a flag on it.
Nothing here changes what ``keel review`` writes, and a reader diffing the two
sees the difference in the LINE, not only in the program: a backfilled line
carries ``backfilled: true`` and ``backfilled_at``, which no live line ever
does. It is also why this module is not registered as a ``keel`` subcommand
and not claimed by a feature in ``scripts/keel-features.json``: the table below
is THIS repository's own history, not a capability an adopter installs.

Contract
--------
Reads   : ``<project>/.keel/audit/keel-audit.jsonl`` (via
          ``keel_events.read_audit``) twice over, for two questions and no
          others - which full session id each ``session_start`` line carries
          (so a prefix in the table below resolves to a real id rather than a
          guessed one), and which ``review`` events the log ALREADY holds (so a
          second run writes nothing). NO LEDGER IS READ: the verdicts were
          extracted from ledger prose by the orchestrator and are data here,
          each row citing the file and line it was read from.
Emits   : one summary line on stdout naming written and skipped counts, one
          line per skipped row saying why, and errors on stderr.
Writes  : zero or more append-only lines to that same audit log through
          ``keel_events.append_audit`` - the same chokepoint every keel line
          passes (``keel_redact.redact_mapping`` inside ``_append_jsonl``).
          Nothing else on disk is touched; no ledger is rewritten.
Argv    : ``[--project DIR] [--dry-run]``.

The event
---------
T129's shape, plus exactly the two fields a reconstruction owes its reader::

    {"v": 1, "ts": "2026-08-11", "event": "review", "session": ...,
     "task": ..., "verdict": "pass"|"fail", "notes": ...,
     "backfilled": true, "backfilled_at": "2026-08-13T..Z"}

``ts`` IS DATE-PRECISION ON PURPOSE. The ledger states the DAY a wave's
verdicts were reached and nothing finer; writing ``T00:00:00Z`` would invent a
clock time that no record holds, so the value carries exactly the precision
the source had (convention: absence over invention). It parses everywhere
keel reads timestamps - ``datetime.fromisoformat`` accepts a bare ISO date,
and the page's ``new Date(e.ts)`` reads it as UTC midnight - and it sorts
into the right position in the feed, which is the only thing the page uses it
for on a review line.

``backfilled_at`` is the one honest clock value in the line: the moment the
reconstruction was generated. A reader that wants only live verdicts filters
on ``backfilled``; a reader that wants to know when the reconstruction
happened reads ``backfilled_at``. Neither can be inferred from ``ts``, which
is why both fields exist.

Idempotence, and its two rules
------------------------------
A second run writes NOTHING. The log itself is the state - no marker file, no
"already ran" flag that could drift from the record it describes:

1. NEVER TWICE. A row is skipped when the log already holds a BACKFILLED
   review with the same ``(session, task, verdict, notes)``. Notes are part of
   the identity because a task can honestly carry two verdicts of the same
   word - T108 failed twice - and those rows differ in exactly their notes.
2. NEVER OVER A LIVE VERDICT. A row is skipped when the log holds a
   NON-backfilled review with the same ``(session, task, verdict)``, whatever
   its notes say. A live line is the better record of the same fact, and a
   reconstruction beside it would double every count the page draws. This is
   also why the table below carries no row for session 53967e1a: that
   session's verdicts were written live, by the command, as they happened.

Exit codes
----------
0   every row is now in the log - written by this run or already there.
2   nothing was written: an unadopted project, a session prefix that does not
    resolve to exactly one ``session_start``, or a row whose verdict or task
    id the shipped normalisers refuse.

Failure policy
--------------
FAIL-CLOSED, and BEFORE the first write. Every row is resolved and normalised
up front; if any row cannot be, the program prints what was wrong and writes
NOTHING AT ALL. A half-written backfill would be worse than none, because the
second run's idempotence rules would then treat the partial result as the
finished one.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No network, no subprocess, no
shell. Nothing read from the log is interpolated into anything (R5).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable, NamedTuple

_SCRIPTS_DIR = Path(__file__).resolve().parent
for _extra in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR.parent / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from keel_events import KEEL_DIRNAME, append_audit, read_audit, utc_now  # noqa: E402
from keel_redact import redact  # noqa: E402
from keel_review import (  # noqa: E402
    REVIEW_EVENT,
    ReviewError,
    normalise_task,
    normalise_verdict,
    review_record,
)

#: The marker that says "reconstructed", and the field carrying WHEN it was
#: reconstructed. Named here rather than spelled inline, because the
#: idempotence rules read them back off disk and a drift between writer and
#: reader would silently re-write the whole table on every run.
BACKFILLED_KEY = "backfilled"
BACKFILLED_AT_KEY = "backfilled_at"


class Row(NamedTuple):
    """One verdict a ledger's prose STATES, with the citation that proves it.

    ``session`` is a PREFIX (the 8 characters a plan filename carries), never
    a full id: the full id is resolved from the log's own ``session_start``
    lines at run time, so a row cannot attribute a verdict to a session that
    never existed. ``ts`` is the ledger's own date. ``source`` is the file and
    line the verdict was read from, and it is appended to ``notes`` so the
    citation travels with the record rather than living only here.
    """

    session: str
    task: str
    verdict: str
    ts: str
    source: str
    note: str

    def notes(self) -> str:
        """The recorded note: what the prose said, then where it said it."""
        return f"{self.note}; backfilled from {self.source}"


#: THE CURATED TABLE - the orchestrator's extraction from ledger prose, each
#: row citing the file and line it was read from (economy rule 3 of
#: ``.keel/plans/keel-plan-53967e1a.md``: the executor reads the table, never
#: the long ledgers). A verdict that prose does not STATE is not here, and the
#: exclusions are declared rather than left to be noticed:
#:
#: * T107 and T120 - ROUTED "Reviewer: none - orchestrator checks"
#:   (``keel-plan-26835f59.md:189-190`` and ``:269-270``), and their outcome
#:   prose narrates orchestrator fixes without ever reaching a verdict WORD.
#:   Both were backfilled in this task's first attempt and REMOVED on review
#:   (2026-08-13, owner-approved): "CLOSED" is not "passed", and a
#:   reconstruction that supplies the missing word invents the one thing the
#:   record exists to hold. An orchestrator check is a real check - it is just
#:   not a review event, and T129's vocabulary has no third word for it.
#: * T118, likewise orchestrator-verified with no reviewer.
#: * T112/T121/T122/T125 - no reviewer verdict stated in the cited prose.
#: * Session 53967e1a's verdicts - already live lines, written by the command
#:   as they happened.
ROWS: tuple[Row, ...] = (
    # -- session 26835f59, waves 2-5, 2026-08-11 ---------------------------
    Row(
        "26835f59", "T104", "pass", "2026-08-11", "keel-plan-26835f59.md:116-118",
        "reviewer-correctness passed it with two non-blocking notes, neither a defect",
    ),
    Row(
        "26835f59", "T117", "fail", "2026-08-11", "keel-plan-26835f59.md:122",
        "reviewer-tests refuted the executor's mutation claim",
    ),
    Row(
        "26835f59", "T117", "pass", "2026-08-11", "keel-plan-26835f59.md:122",
        "CLOSED after one retry isolating the appended bytes",
    ),
    Row(
        "26835f59", "T106", "pass", "2026-08-11", "keel-plan-26835f59.md:457",
        "CLOSED after one retry; review's blocking finding on panel elapsed fixed",
    ),
    Row(
        "26835f59", "T108", "fail", "2026-08-11", "keel-plan-26835f59.md:467-468",
        "reviewer-silent-failure confirmed a wrong-but-green shape; first of two retries",
    ),
    Row(
        "26835f59", "T108", "fail", "2026-08-11", "keel-plan-26835f59.md:467-468",
        "reviewer-silent-failure confirmed a second wrong-but-green shape; second of two retries",
    ),
    Row(
        "26835f59", "T108", "pass", "2026-08-11", "keel-plan-26835f59.md:467-468",
        "CLOSED after two retries - the honesty magnet of the wave",
    ),
    Row(
        "26835f59", "T109", "pass", "2026-08-11", "keel-plan-26835f59.md:478",
        "CLOSED after one addendum; the two carried surfaces fixed",
    ),
    Row(
        "26835f59", "T105", "pass", "2026-08-11", "keel-plan-26835f59.md:506-508",
        "reviewer-correctness: pass, no findings",
    ),
    Row(
        "26835f59", "T102", "pass", "2026-08-11", "keel-plan-26835f59.md:511",
        "CLOSED on two passes and four reviews, all passed",
    ),
    Row(
        "26835f59", "T110", "pass", "2026-08-11", "keel-plan-26835f59.md:434",
        "review pass with zero findings",
    ),
    Row(
        "26835f59", "T119", "fail", "2026-08-11", "keel-plan-26835f59.md:426-433",
        "review caught the stacked sidebar silently breaking T6's collapse promise",
    ),
    Row(
        "26835f59", "T119", "pass", "2026-08-11", "keel-plan-26835f59.md:426-433",
        "CLOSED after one retry making the new geometry real",
    ),
    # -- session 26835f59, wave 6 addenda, 2026-08-12 ----------------------
    Row(
        "26835f59", "T123", "pass", "2026-08-12", "keel-plan-26835f59.md:400-412",
        "reviewer-security passed with zero findings; CLOSED after one retry",
    ),
    # -- session 6d02243b, 2026-08-12 --------------------------------------
    Row(
        "6d02243b", "T124", "pass", "2026-08-12", "keel-plan-6d02243b.md:328-329",
        "security PASS: chokepoint order, per-part redaction, matcher strings held",
    ),
    Row(
        "6d02243b", "T124", "pass", "2026-08-12", "keel-plan-6d02243b.md:329-330",
        "tests PASS: fixture independence proved against the measured shape",
    ),
    Row(
        "6d02243b", "T124", "fail", "2026-08-12", "keel-plan-6d02243b.md:330-331",
        "correctness FAIL with one finding: the Reads contract omitted the new raw reads",
    ),
    Row(
        "6d02243b", "T124", "pass", "2026-08-12", "keel-plan-6d02243b.md:331-332",
        "fixed in the one retry; the contract now names every raw field",
    ),
)


class BackfillError(Exception):
    """A backfill that cannot run, carrying the sentence to print."""


class Outcome(NamedTuple):
    """What one run did: the lines written, and each skip with its reason."""

    written: list[dict[str, object]]
    skipped: list[tuple[Row, str]]


def resolve_sessions(events: Iterable[dict], prefixes: Iterable[str]) -> dict[str, str]:
    """``{prefix: full session id}``, or ``BackfillError`` naming the failure.

    The answer comes from the log's own ``session_start`` lines, because that
    is where a session id is a FACT rather than a filename convention. A
    prefix matching none is an error (the verdict would be attributed to a
    session nobody recorded); a prefix matching two is an error as well - two
    sessions sharing eight characters is a coincidence this program must not
    resolve by picking one (convention 7: fail closed, name the ambiguity).
    """
    starts: list[str] = []
    for ev in events:
        if ev.get("event") != "session_start":
            continue
        sid = ev.get("session") or ev.get("session_id")
        if isinstance(sid, str) and sid and sid not in starts:
            starts.append(sid)
    resolved: dict[str, str] = {}
    for prefix in sorted(set(prefixes)):
        matches = [sid for sid in starts if sid.startswith(prefix)]
        if len(matches) != 1:
            raise BackfillError(
                f"session prefix {prefix!r} matches {len(matches)} session_start "
                "lines in the audit log; a verdict is never attributed to a "
                "guessed session (nothing was written)"
            )
        resolved[prefix] = matches[0]
    return resolved


def existing_keys(events: Iterable[dict]) -> tuple[set, set]:
    """``(backfilled identities, live identities)`` already in the log.

    The first set is four-part - ``(session, task, verdict, notes)`` - and the
    second three-part, for the two reasons the module contract gives: a
    reconstruction is identified by everything it says, while a LIVE verdict
    on the same task and word makes a reconstruction of it redundant however
    it is worded.
    """
    done: set = set()
    live: set = set()
    for ev in events:
        if ev.get("event") != REVIEW_EVENT:
            continue
        session = ev.get("session") or ev.get("session_id")
        key3 = (session, ev.get("task"), ev.get("verdict"))
        if ev.get(BACKFILLED_KEY) is True:
            done.add(key3 + (ev.get("notes"),))
        else:
            live.add(key3)
    return done, live


def build_record(row: Row, session_id: str, generated_at: str) -> dict[str, object]:
    """The line for one row - the live shape, plus the two honest markers.

    ``review_record`` is the SAME builder ``keel review`` uses, so a
    backfilled line cannot drift from a live one in the five fields they
    share; this function only supplies the ledger's date in place of the
    clock and adds the two fields that say what this line is. Key order
    matters: ``keel_events._append_jsonl`` stamps ``v`` and ``ts`` first and
    then merges, so the markers land last and the line reads like every other
    line in the log until its final two fields.
    """
    verdict = normalise_verdict(row.verdict)
    task = normalise_task(row.task)
    record = review_record(session_id, task, verdict, row.notes())
    return {
        "ts": redact(row.ts),
        **record,
        BACKFILLED_KEY: True,
        BACKFILLED_AT_KEY: generated_at,
    }


def plan(root: Path, rows: Iterable[Row] = ROWS) -> Outcome:
    """What a run WOULD do, decided entirely before anything is written.

    Every row is resolved, normalised and tested against the log's existing
    lines here, so a refusal costs nothing and a half-written backfill is
    impossible: ``run`` only appends what this function already decided.
    """
    rows = tuple(rows)
    events = read_audit(root)
    sessions = resolve_sessions(events, (row.session for row in rows))
    done, live = existing_keys(events)
    generated_at = utc_now()
    written: list[dict[str, object]] = []
    skipped: list[tuple[Row, str]] = []
    for row in rows:
        session_id = sessions[row.session]
        try:
            record = build_record(row, session_id, generated_at)
        except ReviewError as exc:
            raise BackfillError(f"{row.task} ({row.source}): {exc}") from exc
        key3 = (record["session"], record["task"], record["verdict"])
        key4 = key3 + (record["notes"],)
        if key4 in done:
            skipped.append((row, "already backfilled"))
            continue
        if key3 in live:
            skipped.append((row, "a live verdict already records it"))
            continue
        done.add(key4)  # a row cannot duplicate itself within one run either
        written.append(record)
    return Outcome(written, skipped)


def run(root: Path, rows: Iterable[Row] = ROWS, dry_run: bool = False) -> Outcome:
    """Append what ``plan`` decided, in table order. Nothing when ``dry_run``."""
    outcome = plan(root, rows)
    if not dry_run:
        for record in outcome.written:
            append_audit(root, record)
    return outcome


def main(argv: list[str] | None = None) -> int:
    """backfill this repository's stated review verdicts as audit events"""
    parser = argparse.ArgumentParser(
        prog="keel-backfill-reviews",
        description="append the curated historical review verdicts to the audit log",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be written; write nothing"
    )
    args = parser.parse_args(argv)

    root = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    if not (root / KEEL_DIRNAME).is_dir():
        print(
            f"keel backfill-reviews: {redact(str(root))} has no {KEEL_DIRNAME}/",
            file=sys.stderr,
        )
        return 2
    try:
        outcome = run(root, ROWS, args.dry_run)
    except BackfillError as exc:
        print(f"keel backfill-reviews: {exc}", file=sys.stderr)
        return 2
    for row, why in outcome.skipped:
        print(f"keel backfill-reviews: skipped {row.task} {row.verdict} - {why}")
    verb = "would write" if args.dry_run else "wrote"
    print(
        f"keel backfill-reviews: {verb} {len(outcome.written)} of {len(ROWS)} "
        f"reconstructed verdicts, skipped {len(outcome.skipped)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
