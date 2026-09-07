#!/usr/bin/env python3
"""T456 - a read-only board showing when each ledger task became terminal.

Contract
--------
Reads   : every ``<root>/.keel/plans/keel-plan-*.md`` for its own working-copy
          content (current status and title), and this repository's git
          history for the SAME files only - ``git log --follow`` on each
          ledger path, then ``git show <hash>:<path>`` on each commit that
          history names, to find the moment a task's line first read
          ``[x]``, ``[!]`` or ``[?]``. Nothing else is opened: no other
          ledger's history, no ``.keel/audit/``, no ``.keel/decisions/``.
Emits   : one self-contained HTML page (``--out``) or a pipe-table on stdout
          (``--markdown``) - never both in one run.
Writes  : exactly the file named by ``--out``, and only when ``--markdown``
          is absent. A markdown run writes nothing at all. No ledger is
          rewritten, no git state is changed (every git call here is a
          read - ``log`` and ``show``).
Argv    : ``[--root DIR] [--out PATH] [--markdown] [--session SESS8]``.

Deriving "finished-at"
-----------------------
A task's CURRENT status (the working copy, read once per ledger) decides
whether it has a finished-at at all: ``[ ]`` (open) and ``[~]`` (in flight)
never do, whatever their history says - a task that is open right now is
open, even if it was briefly marked done and reopened. A task whose current
status is terminal (``[x]``, ``[!]`` or ``[?]``) gets the author time of the
FIRST commit, oldest to newest, whose copy of the ledger already shows that
task's line as terminal (:func:`first_terminal_commit`). Terminal-now but
never-terminal-in-any-commit (a working copy edit not yet committed) reads
``"uncommitted"`` and carries no commit hash. Times are rendered twice -
UTC and this machine's local zone via ``datetime.astimezone()`` - because
the owner reading the page and the git author time recorded in it are not
always the same clock.

Failure policy
--------------
FAIL-CLOSED. A root with no ``.git`` (git cannot answer ``log``/``show`` on
anything) is refused before any output is produced; a ledger whose per-task
status line cannot be parsed on a given historical commit is treated as "not
yet terminal on that commit" rather than crashing the whole run - one
malformed old revision does not blind the board to every other task.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every subprocess call is an
argument list, never a shell string built from ledger content (R5). Every
file read names its encoding, with ``errors="replace"`` so a non-UTF-8
byte in an old ledger degrades a character rather than the whole run.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

#: One task line, first line of its block only. The separator between the
#: id and the title is an em dash in current ledgers; some old ledgers use a
#: plain hyphen instead, and both are accepted (T456's own wording).
TASK_LINE_RE = re.compile(r"^- \[([ x!?~])\] (T\d+) (?:—|-) (.*)$")

#: A ledger filename: ``keel-plan-<session>.md``.
LEDGER_NAME_RE = re.compile(r"^keel-plan-(.+)\.md$")

#: Statuses that mean "this task is finished" - the ONLY three the module
#: contract, and T456's spec, name as terminal.
TERMINAL_CHARS = ("x", "!", "?")

STATUS_WORDS = {
    " ": "open",
    "~": "in flight",
    "x": "done",
    "!": "blocked",
    "?": "needs decision",
}

TITLE_MAX_CHARS = 120


class ScratchBoardError(RuntimeError):
    """The board cannot run at all; the caller prints this and exits 2."""


@dataclass
class Task:
    session: str
    task_id: str
    title: str
    status_char: str


@dataclass
class Row:
    """One rendered table row - the shared model both renderers consume."""

    session: str
    task_id: str
    title: str
    status_char: str
    status_word: str
    finished_local: str
    finished_utc: str
    commit_short: str
    sort_dt: datetime | None


# --------------------------------------------------------------------------
# git, read-only
# --------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """One git call, argument list only (R5). Raises on a missing binary."""
    try:
        return subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, check=False,
        )
    except OSError as exc:
        raise ScratchBoardError(f"cannot run git: {exc}") from exc


def assert_git_repo(root: Path) -> None:
    """Fail closed up front rather than mid-scan on the first ledger."""
    proc = _run_git(["rev-parse", "--is-inside-work-tree"], root)
    if proc.returncode != 0 or proc.stdout.decode("utf-8", "replace").strip() != "true":
        raise ScratchBoardError(f"{root} is not inside a git work tree")


def git_log_follow(root: Path, rel_path: str) -> list[tuple[str, str]]:
    """``[(commit hash, author time ISO-8601)]`` for one path, oldest first.

    Empty means the file has no commits touching it (a brand new, uncommitted
    ledger) - not an error, since ``git log`` on a real repository answers 0
    for that case; only an unreadable repository raises, and that is caught
    once in :func:`assert_git_repo` before any ledger is scanned.
    """
    proc = _run_git(
        ["log", "--follow", "--format=%H%x09%aI", "--reverse", "--", rel_path], root,
    )
    if proc.returncode != 0:
        return []
    text = proc.stdout.decode("utf-8", "replace")
    commits: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 2:
            commits.append((parts[0], parts[1]))
    return commits


def git_show(root: Path, commit_hash: str, rel_path: str) -> str | None:
    """One historical revision of one ledger, or ``None`` if git cannot show it."""
    proc = _run_git(["show", f"{commit_hash}:{rel_path}"], root)
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


# --------------------------------------------------------------------------
# ledger parsing
# --------------------------------------------------------------------------


def parse_task_statuses(content: str) -> dict[str, str]:
    """``{task id: status char}`` for every task line in one ledger revision.

    First occurrence wins for a duplicate id, which should never happen in a
    well-formed ledger; this function does not enforce that, only survives it.
    """
    statuses: dict[str, str] = {}
    for line in content.splitlines():
        match = TASK_LINE_RE.match(line)
        if match is None:
            continue
        status_char, task_id, _title = match.groups()
        statuses.setdefault(task_id, status_char)
    return statuses


def parse_tasks(session: str, content: str) -> list[Task]:
    """Every task in one ledger's CURRENT (working-copy) content, in order."""
    tasks: list[Task] = []
    seen: set[str] = set()
    for line in content.splitlines():
        match = TASK_LINE_RE.match(line)
        if match is None:
            continue
        status_char, task_id, title = match.groups()
        if task_id in seen:
            continue
        seen.add(task_id)
        tasks.append(Task(session, task_id, title, status_char))
    return tasks


def session_id_for(ledger: Path) -> str:
    """The session id a ledger filename carries, or its stem as a fallback."""
    match = LEDGER_NAME_RE.match(ledger.name)
    return match.group(1) if match else ledger.stem


def list_ledgers(root: Path) -> list[Path]:
    """Every ``keel-plan-*.md`` under ``.keel/plans/``, sorted by name."""
    plans_dir = root / ".keel" / "plans"
    if not plans_dir.is_dir():
        return []
    return sorted(plans_dir.glob("keel-plan-*.md"))


# --------------------------------------------------------------------------
# finished-at
# --------------------------------------------------------------------------


def first_terminal_commit(
    commits: list[tuple[str, str]], root: Path, rel_path: str, task_id: str
) -> tuple[str, str] | None:
    """The FIRST commit, oldest to newest, whose ledger shows ``task_id``
    terminal - ``(hash, author time)``, or ``None`` if none ever did.

    ``commits`` is already oldest-first (:func:`git_log_follow`'s own
    contract); this function walks it in the order given and returns on the
    first match, which is what makes it "first" rather than "last" - the
    exact clause convention 15's mutation drill targets.
    """
    for commit_hash, author_time in commits:
        content = git_show(root, commit_hash, rel_path)
        if content is None:
            continue
        status = parse_task_statuses(content).get(task_id)
        if status in TERMINAL_CHARS:
            return commit_hash, author_time
    return None


def resolve_finished_at(
    root: Path, ledger: Path, tasks: list[Task]
) -> dict[str, tuple[str | None, str | None]]:
    """``{task id: (commit hash or None, author time ISO or None)}``.

    Only for tasks whose CURRENT status is terminal - callers must not ask
    for an open or in-flight task, and this function does not filter for
    them; :func:`build_rows` is the one place that decides who is asked.
    """
    rel_path = ledger.relative_to(root).as_posix()
    terminal_ids = [t.task_id for t in tasks if t.status_char in TERMINAL_CHARS]
    result: dict[str, tuple[str | None, str | None]] = {}
    if not terminal_ids:
        return result
    commits = git_log_follow(root, rel_path)
    for task_id in terminal_ids:
        found = first_terminal_commit(commits, root, rel_path, task_id)
        result[task_id] = found if found else (None, None)
    return result


# --------------------------------------------------------------------------
# rows
# --------------------------------------------------------------------------


def _parse_author_time(value: str) -> datetime:
    """``%aI`` (strict ISO-8601, always offset-aware) as a ``datetime``.

    Some git versions render UTC as a trailing ``Z`` instead of ``+00:00``;
    ``datetime.fromisoformat`` only accepts ``Z`` from Python 3.11, and this
    project's floor is 3.10 (R7), so the suffix is normalised first. ``%aI``
    is documented as always offset-aware, but if some git build ever answers
    a naive string anyway, it is read as UTC rather than raising - the same
    choice :func:`hooks.keel_stop._parse_ts_ms` makes for keel's own
    timestamps.
    """
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def build_rows(
    root: Path, session_filter: str | None = None
) -> list[tuple[str, list[Row], datetime | None, float]]:
    """``[(session, rows, newest finished-at, ledger mtime)]``, one entry per
    session, sessions ordered newest-first by (newest finished-at, mtime).
    """
    sessions: list[tuple[str, list[Row], datetime | None, float]] = []
    for ledger in list_ledgers(root):
        session = session_id_for(ledger)
        if session_filter and session != session_filter:
            continue
        try:
            content = ledger.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ScratchBoardError(f"cannot read {ledger}: {exc}") from exc
        tasks = parse_tasks(session, content)
        finished = resolve_finished_at(root, ledger, tasks)
        rows: list[Row] = []
        newest: datetime | None = None
        for task in tasks:
            commit_hash: str | None = None
            author_time: str | None = None
            finished_local = ""
            finished_utc = ""
            sort_dt: datetime | None = None
            if task.status_char in TERMINAL_CHARS:
                commit_hash, author_time = finished.get(task.task_id, (None, None))
                if author_time:
                    sort_dt = _parse_author_time(author_time)
                    finished_local = sort_dt.astimezone().isoformat(timespec="seconds")
                    finished_utc = sort_dt.astimezone(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    if newest is None or sort_dt > newest:
                        newest = sort_dt
                else:
                    finished_local = "uncommitted"
                    finished_utc = "uncommitted"
            rows.append(
                Row(
                    session=session,
                    task_id=task.task_id,
                    title=task.title.strip()[:TITLE_MAX_CHARS],
                    status_char=task.status_char,
                    status_word=STATUS_WORDS.get(task.status_char, task.status_char),
                    finished_local=finished_local,
                    finished_utc=finished_utc,
                    commit_short=(commit_hash[:7] if commit_hash else ""),
                    sort_dt=sort_dt,
                )
            )
        mtime = ledger.stat().st_mtime if ledger.exists() else 0.0
        sessions.append((session, rows, newest, mtime))

    def sort_key(entry: tuple[str, list[Row], datetime | None, float]):
        _session, _rows, newest, mtime = entry
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        return (newest or epoch, mtime)

    sessions.sort(key=sort_key, reverse=True)
    return sessions


def counts_for(sessions: list[tuple[str, list[Row], datetime | None, float]]) -> dict[str, int]:
    """Global counts across every rendered row, keyed by status word."""
    totals = {word: 0 for word in STATUS_WORDS.values()}
    for _session, rows, _newest, _mtime in sessions:
        for row in rows:
            totals[row.status_word] = totals.get(row.status_word, 0) + 1
    return totals


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def render_markdown(sessions: list[tuple[str, list[Row], datetime | None, float]]) -> str:
    totals = counts_for(sessions)
    lines = [
        "counts: open={open}, in flight={inflight}, done={done}, "
        "blocked={blocked}, needs decision={needs_decision}".format(
            open=totals.get("open", 0),
            inflight=totals.get("in flight", 0),
            done=totals.get("done", 0),
            blocked=totals.get("blocked", 0),
            needs_decision=totals.get("needs decision", 0),
        ),
        "",
    ]
    for session, rows, _newest, _mtime in sessions:
        lines.append(f"## session {session}")
        lines.append("")
        lines.append("| id | title | status | finished local | finished UTC | commit |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for row in rows:
            cells = [
                row.task_id,
                row.title.replace("|", "\\|"),
                row.status_word,
                row.finished_local,
                row.finished_utc,
                row.commit_short,
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_HTML_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>keel scratch board</title>
<style>
:root { color-scheme: light dark; }
body {
  font-family: -apple-system, "Segoe UI", sans-serif;
  margin: 2rem;
  background: #ffffff;
  color: #111111;
}
h1 { font-size: 1.3rem; }
h2 { font-size: 1.05rem; margin-top: 2rem; }
.counts { margin-bottom: 1.5rem; }
table { border-collapse: collapse; width: 100%; margin-bottom: 1.5rem; }
th, td {
  border: 1px solid #cccccc;
  padding: 0.35rem 0.6rem;
  text-align: left;
  font-size: 0.9rem;
}
th { background: #f2f2f2; }
@media (prefers-color-scheme: dark) {
  body { background: #1b1b1b; color: #e6e6e6; }
  th { background: #2a2a2a; }
  th, td { border-color: #444444; }
}
</style>
</head>
<body>
"""

_HTML_TAIL = """</body>
</html>
"""


def render_html(sessions: list[tuple[str, list[Row], datetime | None, float]]) -> str:
    totals = counts_for(sessions)
    parts = [_HTML_HEAD]
    parts.append("<h1>keel scratch board</h1>\n")
    parts.append(
        "<p class=\"counts\">open={open}, in flight={inflight}, done={done}, "
        "blocked={blocked}, needs decision={needs_decision}</p>\n".format(
            open=totals.get("open", 0),
            inflight=totals.get("in flight", 0),
            done=totals.get("done", 0),
            blocked=totals.get("blocked", 0),
            needs_decision=totals.get("needs decision", 0),
        )
    )
    for session, rows, _newest, _mtime in sessions:
        parts.append(f"<h2>session {html.escape(session)}</h2>\n")
        parts.append("<table>\n<thead><tr>")
        for header in ("id", "title", "status", "finished local", "finished UTC", "commit"):
            parts.append(f"<th>{header}</th>")
        parts.append("</tr></thead>\n<tbody>\n")
        for row in rows:
            cells = [
                row.task_id,
                row.title,
                row.status_word,
                row.finished_local,
                row.finished_utc,
                row.commit_short,
            ]
            parts.append("<tr>")
            for cell in cells:
                parts.append(f"<td>{html.escape(cell)}</td>")
            parts.append("</tr>\n")
        parts.append("</tbody>\n</table>\n")
    parts.append(_HTML_TAIL)
    return "".join(parts)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """a read-only scratch board naming when each ledger task went terminal"""
    parser = argparse.ArgumentParser(
        prog="keel-scratch-board",
        description="render, per ledger, when each task became terminal",
    )
    parser.add_argument("--root", default=None, help="project directory (default: cwd)")
    parser.add_argument("--out", default=None, help="HTML output path (required unless --markdown)")
    parser.add_argument(
        "--markdown", action="store_true", help="print the table to stdout instead of writing HTML"
    )
    parser.add_argument("--session", default=None, help="show only this session id")
    args = parser.parse_args(argv)

    root = Path(args.root or os.getcwd()).resolve()

    try:
        assert_git_repo(root)
        sessions = build_rows(root, args.session)
    except ScratchBoardError as exc:
        print(f"keel scratch-board: {exc}", file=sys.stderr)
        return 2

    if args.markdown:
        sys.stdout.write(render_markdown(sessions))
        return 0

    if not args.out:
        print("keel scratch-board: --out is required unless --markdown is given", file=sys.stderr)
        return 2

    try:
        Path(args.out).write_text(render_html(sessions), encoding="utf-8")
    except OSError as exc:
        print(f"keel scratch-board: cannot write {args.out}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
