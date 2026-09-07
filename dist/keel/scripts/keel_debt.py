#!/usr/bin/env python3
"""keel debt harvest - collects deliberate corners cut inside completed work.

The convention this tool reads
-------------------------------
A deliberate simplification with a known ceiling is marked at the site where
it was cut, in whatever comment syntax the file uses, with the literal text
``keel:deferred(ceiling=<what breaks or runs out>; trigger=<the observable
event that demands the upgrade>)``. Both fields are required; free text may
follow the pair, separated the same way, for a human reader. See convention
13 in ``docs/keel-conventions.md``.

Contract
--------
Reads   : every path ``git ls-files`` reports for the repository containing
          ``--project`` (default: ``CLAUDE_PROJECT_DIR``, else the current
          directory), read as UTF-8 text; a path that will not decode as
          UTF-8 is silently treated as binary and skipped, the same as every
          other keel scanner over a tracked tree. ``.keel/audit/`` and
          ``.keel/queue/`` are excluded outright - they are mechanical logs,
          never a site where a deferral is cut. THIS FILE and
          ``tests/test_keel_debt.py`` are excluded too: the marker pattern
          appears in both as a literal string (this docstring, and the test
          fixtures), and a harvester that reports its own documentation as
          debt teaches nobody anything.
Emits   : one line per marker - ``path:line — ceiling — trigger`` -
          in path order, then a totals line. A marker missing either field
          prints ``(missing)`` in its place and is tagged
          ``[no-trigger rot risk]``:
          a ceiling with no trigger is a corner that is cut forever, because
          nothing ever fires the upgrade. ``--json`` emits the same report as
          a document. An empty result prints exactly ``no deferrals on
          record`` (a report tool never fails on finding nothing - and here,
          finding nothing is the state every project starts in).
Writes  : nothing. Harvesting debt is not paying it down.
Argv    : ``--project DIR``, ``--json``, ``--quiet``.

Exit codes
----------
0  the harvest ran - INCLUDING when it found nothing, and including when
   every marker it found is missing a field. This is a report, not a gate:
   nothing here is the caller's failure to fix on this run (compare
   ``scripts/keel_index.py`` and ``scripts/keel_chart.py``, which take the
   same position for the same reason).
2  the harvest could not run - not a git work tree, ``git ls-files`` failed,
   or ``--project`` names something unreadable.

Failure policy
--------------
FAIL-CLOSED. A harvest that cannot enumerate the tracked tree returns 2
rather than printing an empty bill (convention 12); the one exception,
stated above, is exit 0 on a *complete and clean* run that simply found no
markers, which is never confused with a run that could not look.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). ``git`` is invoked with an
argument list, never a shell string (R5). Matching is case-insensitive by
default (convention 3). Every file read names its encoding (convention 6).
Paths printed are exactly what ``git ls-files`` returns - already
project-relative and already free of any username (convention 5) - so no
further redaction pass is needed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple, Sequence

#: Mechanical logs: never a site where a corner is deliberately cut.
EXCLUDED_PREFIXES: tuple[str, ...] = (".keel/audit/", ".keel/queue/")

#: This tool's own source and its tests: the marker text appears in both as a
#: literal string (documentation and fixtures), never as a real deferral.
EXCLUDED_PATHS: frozenset[str] = frozenset({"scripts/keel_debt.py", "tests/test_keel_debt.py"})

#: ``keel:deferred(...)`` on one line; the parenthesised body excludes nested
#: parens by design - ceiling/trigger prose is not expected to carry them.
_MARKER_RE = re.compile(r"keel:deferred\(([^()]*)\)", re.IGNORECASE)

#: One ``key=value`` field inside a marker body, split on top-level ``;``.
_FIELD_RE = re.compile(r"^(ceiling|trigger)\s*=\s*(.*)$", re.IGNORECASE)


class Marker(NamedTuple):
    """One ``keel:deferred`` marker as read from the tree."""

    path: str
    line: int
    ceiling: str | None
    trigger: str | None


class DebtError(RuntimeError):
    """The harvest could not run at all. The caller returns 2 (fail-closed)."""


def find_repo_root(start: str) -> str:
    """The work tree containing ``start``. Argument list only, no shell (R5)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise DebtError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise DebtError("not inside a git work tree: " + (proc.stderr or "").strip())
    return str(Path(proc.stdout.strip()).resolve())


def tracked_files(root: str) -> list[str]:
    """Everything git tracks, repository-wide, whatever directory we ran in."""
    try:
        proc = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise DebtError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise DebtError("git ls-files failed: " + (proc.stderr or "").strip())
    return [line.replace("\\", "/") for line in proc.stdout.splitlines() if line]


def is_excluded(rel_path: str) -> bool:
    """True for a mechanical log or this tool's own source/tests."""
    if rel_path in EXCLUDED_PATHS:
        return True
    return any(rel_path.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def parse_marker_body(body: str) -> tuple[str | None, str | None]:
    """``ceiling``/``trigger`` out of one marker's parenthesised body.

    Fields are ``;``-separated; anything that is not a recognised
    ``key=value`` is free text and is ignored here - it exists for the human
    reading the source, not for this tool.
    """
    ceiling: str | None = None
    trigger: str | None = None
    for part in body.split(";"):
        match = _FIELD_RE.match(part.strip())
        if match is None:
            continue
        key = match.group(1).lower()
        value = match.group(2).strip()
        if not value:
            continue
        if key == "ceiling":
            ceiling = value
        elif key == "trigger":
            trigger = value
    return ceiling, trigger


def scan_file(root: str, rel_path: str) -> list[Marker]:
    """Every marker in one tracked file, or nothing at all if it is binary/gone."""
    full = Path(root) / rel_path
    try:
        text = full.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    markers: list[Marker] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _MARKER_RE.finditer(line):
            ceiling, trigger = parse_marker_body(match.group(1))
            markers.append(Marker(rel_path, line_no, ceiling, trigger))
    return markers


def collect_markers(root: str, tracked: Sequence[str]) -> list[Marker]:
    """Every marker in the tree, sorted by path then line."""
    markers: list[Marker] = []
    for rel in tracked:
        if is_excluded(rel):
            continue
        markers.extend(scan_file(root, rel))
    return sorted(markers, key=lambda marker: (marker.path, marker.line))


def is_rot_risk(marker: Marker) -> bool:
    """True when either required field is missing - the rot-risk warning."""
    return marker.ceiling is None or marker.trigger is None


def render_text(markers: Sequence[Marker]) -> str:
    """The human report. A clean tree gets exactly one sentence."""
    if not markers:
        return "no deferrals on record"
    lines: list[str] = []
    warnings = 0
    for marker in markers:
        ceiling = marker.ceiling or "(missing)"
        trigger = marker.trigger or "(missing)"
        line = f"{marker.path}:{marker.line} — {ceiling} — {trigger}"
        if is_rot_risk(marker):
            warnings += 1
            line += "  [no-trigger rot risk]"
        lines.append(line)
    lines.append("")
    lines.append(f"keel debt: {len(markers)} deferral(s) on record, {warnings} at rot risk")
    return "\n".join(lines)


def render_json(markers: Sequence[Marker]) -> str:
    """The same report as a document."""
    payload: dict[str, Any] = {
        "total": len(markers),
        "rot_risk": sum(1 for marker in markers if is_rot_risk(marker)),
        "markers": [
            {
                "path": marker.path,
                "line": marker.line,
                "ceiling": marker.ceiling,
                "trigger": marker.trigger,
                "rot_risk": is_rot_risk(marker),
            }
            for marker in markers
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """scan git-tracked text for keel:deferred markers and harvest them"""
    parser = argparse.ArgumentParser(
        prog="keel debt",
        description="collect keel:deferred markers left in completed work",
    )
    parser.add_argument("--project", default=None, help="project / repository directory")
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    parser.add_argument("--quiet", action="store_true", help="summary line only")
    args = parser.parse_args(argv)

    try:
        project = args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        root = find_repo_root(str(Path(project)))
        tracked = tracked_files(root)
    except (DebtError, OSError, ValueError) as exc:
        print(f"keel debt: {exc}", file=sys.stderr)
        return 2

    markers = collect_markers(root, tracked)
    if args.as_json:
        print(render_json(markers))
    elif args.quiet:
        warnings = sum(1 for marker in markers if is_rot_risk(marker))
        print(
            "no deferrals on record"
            if not markers
            else f"keel debt: {len(markers)} deferral(s) on record, {warnings} at rot risk"
        )
    else:
        print(render_text(markers))
    return 0


if __name__ == "__main__":
    sys.exit(main())
