#!/usr/bin/env python3
"""keel hook-error log - one JSONL line per hook failure, user-global (T235).

Contract
--------
Reads   : this user's home directory, to locate the ONE user-global keel
          directory the ratified location decision names
          (``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md``
          -> ``~/.claude/keel/``); and, for the recency questions
          ``keel_session`` and ``keel doctor`` ask, that log file's own
          ``stat()``. Nothing else, and never a project's tree: a hook that is
          failing may be failing precisely because a project could not be
          resolved, so this log may not depend on one.
Emits   : values, never text on stdout. ``record`` answers whether a line was
          written; ``state`` answers what the log looks like now.
Writes  : ``~/.claude/keel/keel-hook-errors.jsonl`` - append-only JSONL, one
          line per hook failure, each carrying ``"v"``, ``"ts"``, the
          subcommand, the fault kind and a REDACTED one-line summary. The
          directory is created lazily, on the first line ever written, so a
          machine whose hooks never fail keeps no keel directory it did not
          ask for. THE WRITE ITSELF IS ``keel_events._append_jsonl`` - the
          same single chokepoint every audit and queue line passes through -
          so this log inherits the write-time redaction screen rather than
          introducing a second one (R15, convention 5). An exception message
          carries filesystem paths, so that screen is the reason this module
          may write exception text at all; if the screen cannot run, the
          appender raises and NO line is written, which is the direction
          ``keel_events`` documents for its own per-line policy.
Argv    : none. Library module, imported by ``keel_hook``, ``keel_capture``,
          ``keel_session`` and ``scripts/keel_doctor.py``.

Exit codes
----------
None of its own. Nothing here returns, sets or influences a hook's exit code,
and that is the property this module is built around rather than a side
effect: see the failure policy below.

Failure policy
--------------
FAIL-OPEN AND VERDICT-NEUTRAL. Under
``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md`` a crash
in an armed project is a DENY, and clause 5 of that ruling wants every crash
counted. A counter that could change the count's own verdict would be worse
than no counter: so every public function here catches everything, returns a
value in all cases, and NEVER raises - the caller's verdict and exit code are
already decided by the time it is called, and nothing here may revisit them.
A log that cannot be written is one stderr line (convention 7: reported,
never silent), never an exception and never a changed decision.

STDLIB ONLY AT MODULE SCOPE, and the two keel modules this needs
(``keel_events`` for the appender, ``keel_gate`` for the fault classifier) are
imported INSIDE the functions that use them. That is not laziness for cost: a
half-applied edit to either of those modules is the single most likely reason
a hook is failing in the first place, and a module-scope import of the broken
thing would take the error log down exactly when it is the only record left.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No shell, no network, no
subprocess. Every file operation states its encoding explicitly - here, by
delegating the only write to ``keel_events``, which does.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

#: The ratified user-global keel directory, as path segments under the home
#: directory. ONE directory, named by
#: ``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md`` clause
#: 1; nothing here writes outside it (clause 3).
USER_GLOBAL_RELPATH: tuple[str, ...] = (".claude", "keel")

#: The log's filename. Carries the keel token like every other keel file
#: (convention 8), and says what it holds: hook errors, one per line.
HOOK_ERROR_LOG_NAME = "keel-hook-errors.jsonl"

#: Schema version stamped on every line, versioned SEPARATELY from the audit
#: and queue logs because it is a separate contract with separate readers
#: (``keel_session``'s dead-man line, ``keel doctor``), exactly as
#: ``keel_events`` versions its two logs apart.
HOOK_ERROR_SCHEMA_VERSION = 1

#: The wire value in the ``event`` field. A reader keys on this.
HOOK_ERROR_EVENT = "hook_error"

#: How recent a line has to be for the session-start warning to fire.
RECENT_DAYS = 7

#: Bound on the summary text. Long enough for a type, a message and a fault
#: site; short enough that one failing hook cannot fill a user's disk with one
#: line. Mirrors ``keel_gate.scrub``'s default order of magnitude.
SUMMARY_CHARS = 200

#: The three states ``state`` can report, each its own answer. "present" is
#: never inferred from an unreadable file and "absent" is never inferred from
#: a home directory that could not be resolved (that is ``unreadable`` too):
#: a log keel cannot read is not a log that says nothing happened.
STATE_ABSENT = "absent"
STATE_PRESENT = "present"
STATE_UNREADABLE = "unreadable"


def user_global_dir(home: Path | None = None) -> Path | None:
    """``~/.claude/keel/`` for this user, or None when home cannot be resolved.

    ``home`` is the seam every home-reading module in this project offers
    (``keel_doctor.settings_sources``, ``keel_survey.survey``): a caller that
    must own the premise - a test with a fixture home - hands one down, and
    production passes nothing and reads the real one. None is a FACT here, not
    a failure to paper over: a machine where no home resolves has nowhere for
    this log to live, and the caller says so rather than inventing a location.
    """
    try:
        base = Path.home() if home is None else Path(home)
        return base.joinpath(*USER_GLOBAL_RELPATH)
    except Exception:  # noqa: BLE001 - no home is an answer, never an exception
        return None


def log_path(home: Path | None = None) -> Path | None:
    """The hook-error log's location, or None when home cannot be resolved."""
    directory = user_global_dir(home)
    return None if directory is None else directory / HOOK_ERROR_LOG_NAME


def summarise(exc: BaseException) -> str:
    """ONE LINE naming the exception type and its message, length-bounded.

    One line rather than a traceback, because this log is a count with a
    diagnosis attached, not a debugger: newlines and tabs are collapsed so a
    multi-line message can never become several JSONL lines' worth of text
    inside one field. The text is NOT redacted here - it is redacted at the
    write chokepoint (see the module contract), which is the one place that
    screen cannot be forgotten. Never raises: an exception whose ``__str__``
    is itself broken still yields its type name.
    """
    try:
        text = f"{type(exc).__name__}: {exc}"
    except Exception:  # noqa: BLE001 - a broken __str__ is still a fault to log
        try:
            text = f"{type(exc).__name__}: (its own str() raised)"
        except Exception:  # noqa: BLE001 - nothing left to name it with
            return "an exception that could not describe itself"
    text = " ".join(text.split())
    return text if len(text) <= SUMMARY_CHARS else text[: SUMMARY_CHARS - 3] + "..."


def fault_kind(exc: BaseException) -> str:
    """The coarse fault split, from the classifier that already exists.

    ``keel_gate.gate_self_fault`` is THE classifier for "is this keel's own
    module state or somebody's data", and it is imported and called rather
    than re-derived (R15) so this log and the gates' own refusals can never
    disagree about the same exception. Its two answers map onto the same
    vocabulary ``keel_gate._crash_fault_label`` writes to the audit log:
    ``"module"`` when keel's own source raised structurally, ``"unknown"``
    otherwise - never a guess at ``"configuration"``, because deciding that
    means reading the project's arming file and this module resolves no
    project. A caller that HAS the finer answer (the launcher does, from
    ``_crash_fault_label``) passes it to ``record`` instead.

    ``"unknown"`` is also the answer when ``keel_gate`` cannot be imported at
    all, which is the most likely single reason a hook is failing: the fault is
    still counted, and the summary still names the exception.
    """
    try:
        import keel_gate  # noqa: PLC0415 - guarded, and see the module contract

        return "module" if keel_gate.gate_self_fault(exc) else "unknown"
    except Exception:  # noqa: BLE001 - a classification may never fail the log
        return "unknown"


def record(
    subcommand: str,
    exc: BaseException,
    kind: str | None = None,
    home: Path | None = None,
) -> bool:
    """Write ONE line for one hook failure. Returns whether it landed.

    NEVER RAISES AND NEVER CHANGES A VERDICT (the module contract's whole
    point): the caller has already decided allow or deny by the time this runs,
    and a failure to record is reported on stderr rather than being allowed to
    disturb the decision it is recording.

    ``kind`` is the caller's own classification when it has one - the launcher
    holds ``keel_gate._crash_fault_label``'s answer, which distinguishes
    ``configuration`` from ``module`` and cost a policy read to establish - and
    ``fault_kind`` is asked only when it does not, so the finer answer is never
    thrown away and never recomputed.
    """
    try:
        path = log_path(home)
        if path is None:
            print(
                "keel: hook error not logged: no home directory resolves, so "
                "the user-global keel directory has no location",
                file=sys.stderr,
            )
            return False
        import keel_events  # noqa: PLC0415 - guarded, and see the module contract

        keel_events._append_jsonl(
            path,
            {
                "event": HOOK_ERROR_EVENT,
                "subcommand": subcommand,
                "fault_kind": kind or fault_kind(exc),
                "error": summarise(exc),
            },
            HOOK_ERROR_SCHEMA_VERSION,
        )
        return True
    except Exception as inner:  # noqa: BLE001 - reported, never silent, never fatal
        try:
            print(
                f"keel: hook error not logged: {type(inner).__name__}: {inner}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001 - nowhere left to report to
            pass
        return False


def state(home: Path | None = None) -> dict[str, Any]:
    """What the hook-error log looks like right now, as three distinct states.

    ``{"state": ..., "path": ..., "age_days": ..., "recent": ..., "detail":
    ...}``. The three states are the whole point and they are never collapsed:
    ``absent`` (the log has never been written - the state of a healthy
    machine), ``present`` (it exists, with its age in days), and
    ``unreadable`` (it exists but its own metadata could not be read, or no
    home resolved to look in). Reporting an unreadable log as absent would
    turn keel's own failure record into a claim of health, which is the exact
    shape ``a-swallowed-error-renders-as-a-fact`` names.

    ``recent`` is True only for a ``present`` log younger than
    ``RECENT_DAYS``; it is False for ``absent``, and for ``unreadable`` it is
    None - not False - because "keel could not tell" is not "nothing
    happened". Never raises.
    """
    answer: dict[str, Any] = {
        "state": STATE_UNREADABLE,
        "path": None,
        "age_days": None,
        "recent": None,
        "detail": "",
    }
    try:
        path = log_path(home)
        if path is None:
            answer["detail"] = "no home directory resolves, so there is nowhere to look"
            return answer
        answer["path"] = _shown(path)
        if not path.exists():
            answer.update(
                {
                    "state": STATE_ABSENT,
                    "recent": False,
                    "detail": "no hook has ever written an error line",
                }
            )
            return answer
        age_days = max(time.time() - path.stat().st_mtime, 0.0) / 86400.0
        answer.update(
            {
                "state": STATE_PRESENT,
                "age_days": age_days,
                "recent": age_days <= float(RECENT_DAYS),
                "detail": f"last written {age_days:.1f} day(s) ago",
            }
        )
        return answer
    except Exception as exc:  # noqa: BLE001 - unreadable is its own state
        answer["detail"] = f"{type(exc).__name__}: {exc}"
        return answer


def _shown(path: Path) -> str:
    """The log's path as a value safe to print: redacted, or its name alone.

    This path names a home directory by construction, so it never reaches a
    message unscreened. If the screen itself cannot be imported or run, the
    FILENAME is shown instead of the path - absence of the directory part is a
    smaller loss than leaking it, and it is still enough to find the file.
    """
    try:
        import keel_redact  # noqa: PLC0415 - guarded, and see the module contract

        return keel_redact.redact(str(path))
    except Exception:  # noqa: BLE001 - the screen may never be bypassed
        return os.path.basename(str(path))
