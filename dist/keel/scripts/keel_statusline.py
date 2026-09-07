#!/usr/bin/env python3
"""keel status line - one line of context, cost and place, from stdin (T228).

Contract
--------
Reads   : one JSON object on stdin, the status-line payload the harness hands
          a status-line command on every render. Three fields are read and
          nothing else: ``context_window.used_percentage`` (a number, or null
          before the first API call and again immediately after a compaction),
          ``cost.total_cost_usd`` (a number), and the working directory, taken
          from ``workspace.current_dir`` and falling back to ``cwd``. Every
          other field the payload carries is ignored, never interpolated.
Emits   : exactly one line on stdout - the status line itself. Nothing on
          stderr in any circumstance: a status-line command's stderr competes
          with the very line it is trying to draw, and a diagnostic that
          corrupts the display it diagnoses is worse than silence. The line
          is drawn on EVERY path, including the broken ones, because a status
          line that vanishes tells the user nothing about why.
Writes  : NOTHING. No file, no directory, no telemetry, no state of any kind -
          see "Why this writes nothing" below. It is the only keel component
          that runs on every assistant message, and the only safe amount of
          work for such a thing to do is none.
Argv    : none.

Exit codes
----------
0, always and unconditionally. A status line carries no verdict, and a
non-zero exit from one is a harness-level error report about a cosmetic
component.

Registration
------------
BY THE USER, BY HAND, and never by keel. Nothing in keel writes to the
harness's settings files - they are the owner's, per
``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md`` clause 3
- so this script ships and waits. To use it, add a ``statusLine`` entry of
type ``command`` running::

    python <keel>/scripts/keel_statusline.py

Why this writes nothing
-----------------------
A status-line command runs on every assistant message, which makes it the
highest-frequency process in the whole system and therefore the worst place
in keel to put a side effect. The temptation is specific and worth naming so
that a later reader does not rediscover it as an idea: a status line is the
only component that can see the context percentage, so it is the natural
place to record that number for something else to act on. keel does not do
that today.

The marker below is on ONE line because that is what harvests it
(``scripts/keel_debt.py`` matches within a line), and it is deliberately the
only deferral this file carries.

keel:deferred(ceiling=the context percentage is visible only here and is recorded nowhere, so nothing in keel can warn a session it is about to be compacted - only help it survive one; trigger=an owner decision to add a context nudge, at which point this script gains one small per-session write and the prompt hook gains the matching read)

Failure policy
--------------
FAIL-OPEN, TOTAL, AND SILENT ON STDERR - the one place in keel where "never
silent" (convention 7) yields, and it yields to the same reasoning that
produced the rule: an error message here does not reach a log or a reader, it
lands in the middle of a one-line display. So every field is read inside its
own guard, an unreadable field renders as ``--`` rather than as an absence
the reader has to interpret, and an unparseable payload still produces the
line with every field ``--``. That is the honest rendering: "keel could not
read this" and "this is zero" are different, and ``--`` is the first of them.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No shell, no network, no
subprocess, no imports from keel's own tree - a status line must start fast
and must not be able to fail because some other keel module is mid-edit.
NO PATH IS EVER RENDERED: only the last segment of the working directory
reaches the line, which is why this file needs no redactor to satisfy
convention 5 - there is nothing path-shaped in its output to screen.
"""

from __future__ import annotations

import json
import sys
from typing import Any

#: What an unreadable or unsupplied value renders as. Never "0", never blank:
#: the payload sends null for the context percentage before the first API call
#: and again right after a compaction, and a zero there would be a lie about
#: the session's state at exactly the two moments it matters most.
UNKNOWN = "--"

#: The tag the line opens with, so a combined status line built from several
#: commands says which segment is keel's (convention 8).
TAG = "keel"

#: The separator between segments. Plain ASCII on purpose: this string is
#: printed to a console on three operating systems, and an encoding that
#: cannot render a typographic character would turn a status line into a
#: traceback (the same reasoning ``keel_session.OVERFLOW_MARKER`` gives).
SEPARATOR = " | "


def _number(payload: Any, *path: str) -> float | None:
    """A number at ``path`` inside nested mappings, or None. Never raises.

    None is the answer for every non-numeric outcome there is - a missing key,
    a null, a string, a mapping where a number was expected, a payload that is
    not a mapping at all - because the renderer treats them all the same way
    and inventing a distinction the display cannot show would only be a lie
    with more steps. Booleans are rejected explicitly: ``True`` is an
    ``int`` in Python and would render as "1%".
    """
    try:
        node: Any = payload
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        if isinstance(node, bool) or not isinstance(node, (int, float)):
            return None
        return float(node)
    except Exception:  # noqa: BLE001 - a status line may never raise
        return None


def context_segment(payload: Any) -> str:
    """``<n>% ctx`` from the context window, or ``-- ctx``.

    Clamped to 0-100 rather than trusted: the value is a payload number, and a
    status line that renders "-3% ctx" or "412% ctx" costs its reader the
    trust of every other figure on the line.
    """
    value = _number(payload, "context_window", "used_percentage")
    if value is None:
        return f"{UNKNOWN} ctx"
    return f"{max(0, min(100, int(round(value))))}% ctx"


def cost_segment(payload: Any) -> str:
    """``$<n.nn>`` for this session's cost, or ``$--``.

    The number the harness reports, rendered to two decimals and never
    recomputed, estimated or converted: keel reports what it is told and
    models nobody's pricing, so there is no price table here to drift out of
    date and no "saving" claimed against a number nobody measured.
    """
    value = _number(payload, "cost", "total_cost_usd")
    if value is None:
        return f"${UNKNOWN}"
    return f"${value:.2f}"


def place_segment(payload: Any) -> str:
    """The LAST SEGMENT of the working directory, or ``--``. Never a path.

    Both separators are folded before the split, so a Windows payload and a
    POSIX one yield the same answer, and empty segments are discarded so a
    trailing slash does not render as nothing. A path is never rendered whole
    - see the module contract: this is what keeps the line free of anything a
    redactor would have to screen.
    """
    try:
        raw = None
        if isinstance(payload, dict):
            workspace = payload.get("workspace")
            if isinstance(workspace, dict):
                raw = workspace.get("current_dir")
            if not isinstance(raw, str) or not raw.strip():
                raw = payload.get("cwd")
        if not isinstance(raw, str) or not raw.strip():
            return UNKNOWN
        parts = [part for part in raw.replace("\\", "/").split("/") if part]
        return parts[-1] if parts else UNKNOWN
    except Exception:  # noqa: BLE001 - a status line may never raise
        return UNKNOWN


def render(payload: Any) -> str:
    """The whole line. Total: every input, including nonsense, yields a line."""
    return SEPARATOR.join(
        (
            f"{TAG} {context_segment(payload)}",
            cost_segment(payload),
            place_segment(payload),
        )
    )


def read_payload(stream: Any = None) -> Any:
    """The decoded payload, or ``{}`` for anything that is not a JSON object.

    ``utf-8-sig``, not ``utf-8``: a Windows shell pipe prepends a byte-order
    mark, and a mark that fails the parse would blank every field on that
    platform - the same defect ``keel_hook._read_payload`` documents and
    guards, re-stated here because this file imports nothing from keel.
    """
    try:
        handle = sys.stdin if stream is None else stream
        raw = handle.buffer.read() if hasattr(handle, "buffer") else handle.read()
        if isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw).decode("utf-8-sig", errors="replace")
        decoded = json.loads(str(raw).strip() or "{}")
        return decoded if isinstance(decoded, dict) else {}
    except Exception:  # noqa: BLE001 - an unreadable payload still gets a line
        return {}


def main(stream: Any = None, stdout: Any = None) -> int:
    """Draw the line; return 0 whatever happened."""
    try:
        print(render(read_payload(stream)), file=stdout or sys.stdout)
    except Exception:  # noqa: BLE001 - the line is drawn on every path
        try:
            print(f"{TAG} {UNKNOWN} ctx{SEPARATOR}${UNKNOWN}{SEPARATOR}{UNKNOWN}")
        except Exception:  # noqa: BLE001 - nowhere left to draw to
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
