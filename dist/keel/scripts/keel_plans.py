#!/usr/bin/env python3
"""keel-plan-contract checker for session ledgers.

Contract
--------
Reads   : one or more ledger markdown files given on argv, or - when none are
          given - every ``*.md`` directly under ``<project>/.keel/plans/``
          (overridable with ``--project``). A ledger not existing there is
          not an error: a project that has written no ledgers yet has none to
          check.
Emits   : one ``path:line: [rule] detail`` line per finding, then a summary;
          ``--json`` emits the same report as a document.
Writes  : nothing. Fixing a ledger is the author's decision; this tool's job
          stops at telling the truth about one.
Argv    : ``<ledger.md> ...`` (repeatable, positional), ``--project DIR``,
          ``--strict``, ``--json``, ``--quiet``.

ADVISORY AS A CLI, LOAD-BEARING AT THE GATE
--------------------------------------------
THIS MODULE DECIDES NOTHING ABOUT SEVERITY FOR ITS CALLERS. Run as a command
it is advisory: its default mode never fails a build, because older ledgers -
including some already in this repository - predate this contract and are not
retroactively broken by it, and ``--strict`` is the opt-in that makes one rule
(see below) load-bearing.

``hooks/keel_gate.py`` IMPORTS it, and applies its own ruling: a write to a
session ledger (``.keel/plans/keel-plan-*.md``) is REFUSED when any of the
four rules below fires, severity notwithstanding (see that file's rule 3 and
its ``BLOCKING_PLAN_RULES``). The regexes and the parse live here and only
here; the blocking set lives there and only there. Nothing in this file needs
to know which caller it is serving.

The contract this checks
-------------------------
The full prose lives in ``templates/keel-plan-contract.md``; this is the
subset a machine can decide:

  - every task line (``- [ ] Tn <title>``) carries an identifier immediately
    after its checkbox;
  - every task carries a ``Route:`` line and an ``Accept:`` line somewhere in
    its block;
  - no task's block contains the banned placeholder vocabulary: ``TBD``,
    ``etc.``, ``handle appropriately``, ``as needed``, ``similar to the
    above``.

What this checker does NOT assert: that global constraints are stated once at
the top, that a consuming task names the task it consumes, or anything about
status marks - those are read by a person, or are the gate's law, not this
tool's.

Severities
----------
THIS TABLE DESCRIBES THIS CHECKER'S OWN ADVISORY EXIT CODE ONLY. All four
rules below BLOCK a session-ledger write at the calling gate regardless of
the severity shown here - see ADVISORY AS A CLI, LOAD-BEARING AT THE GATE
above: severity is not read there at all. A warning in this table is not a
lesser finding to that caller.
    missing_route        (warn: no 'Route:' line in the task's block)
    missing_accept        (warn: no 'Accept:' line in the task's block)
    placeholder_phrase    (warn: names the exact banned phrase found)
    missing_identifier    (warn by default; ERROR only under --strict - older
                          ledgers predate the contract, so a bare task line
                          is not by itself a failure until a project opts in)

Exit codes
----------
0  clean, or - without ``--strict`` - always: this checker is advisory by
   design and every rule above is a warning until the caller opts in.
1  at least one ERROR (only reachable with ``--strict``, and only from
   ``missing_identifier``).
2  the checker itself could not run: an explicitly named ledger path does not
   exist or cannot be read, or ``--project`` names an unreadable directory.

Failure policy
--------------
FAIL-CLOSED for the checker's own operation (an unreadable explicit path is a
hard error, not a skip - convention 12); FAIL-OPEN for content by explicit
design (see ADVISORY BY DESIGN above) - the one place those two conventions
point in different directions, and the split is deliberate rather than an
oversight.

Parsing
-------
A TARGETED LINE READER, NOT A MARKDOWN PARSER: it recognises exactly the
ledger shape this project's own plans use - ``- [<mark>] <rest>`` opens a
task, and every following line that is blank or starts with whitespace is
that task's continuation, ending at the next column-0 line (a new task, a
heading, or prose). Nothing else is parsed. ``Route:``/``Accept:`` are looked
for ANYWHERE in the task's block text, not only at the start of a line - many
existing ledger entries carry them as the tail of a sentence, not their own
line - and matched CASE-SENSITIVELY: this is the one contract literal a
machine reads, mirroring the ``Confidence floor:`` line in
``scripts/keel_checks.py`` - the casing is part of the contract, not
incidental style. Placeholder phrases are matched case-insensitively
(convention 3): banned vocabulary hides a decision regardless of how it is
capitalised.

A block where the strict search finds nothing is searched a second time for
a NEAR MISS - wrong case (``accept:``), or the word separated from its
colon by other text (``Accept (restated for convenience; ...):``) - purely
to report the OFFENDING line and the text actually found there, instead of
reading identically to a field never written at all. This does not loosen
what counts as present: ``has_route``/``has_accept`` are still decided by
the strict, case-sensitive patterns alone, and a near miss still reports
under the same ``missing_route``/``missing_accept`` rule. See
``ROUTE_NEAR_MISS_RE`` / ``ACCEPT_NEAR_MISS_RE``.

Constraints
-----------
Python 3.10+, standard library only. No subprocess, no shell, no network.
Every file read names its encoding.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import NamedTuple, Sequence

ERROR = "error"
WARN = "warn"

#: Where ledgers live by default when none are named on argv.
DEFAULT_PLANS_DIR: tuple[str, ...] = (".keel", "plans")

#: A task line: ``- [ ] Tn <title>`` (also ``[x]``, ``[~]``, ``[!]``, ``[?]``
#: - the status marks themselves are the gate's law, not read here).
TASK_LINE_RE = re.compile(r"^- \[[ xX~!?]\]\s*(?P<rest>.*)$")

#: An identifier immediately after the checkbox: ``T`` followed by digits.
IDENTIFIER_RE = re.compile(r"^(T\d+)\b")

#: The two required contract fields. Matched ANYWHERE in a task's block text,
#: not only at the start of a line: real ledgers often carry ``Route:`` and
#: ``Accept:`` as the tail of a sentence rather than their own line (for
#: example ``... no other files. Route: standard (keel:executor).``). The
#: lookbehind keeps a plain word boundary so neither matches as the tail of
#: some other identifier. CASE-SENSITIVE by design - see the module
#: docstring's Parsing section.
#:
#: ``ROUTE_LINE_PATTERN`` is the SINGLE definition of what a Route line is,
#: project-wide: ``scripts/keel_attest.py`` imports this pattern text (not a
#: hand-typed copy of it) to read the route's VALUE, so the gate's contract
#: and attest's reconciliation can never disagree again about the shape of a
#: Route line - see ``attest-parser-misses-contract-ledgers`` for the defect
#: this closes. This module only ever needs PRESENCE (``has_route`` below),
#: so it keeps using ``.search(...) is not None`` and ignores the named
#: group; the added group changes nothing about which text matches, only
#: what a caller may additionally read from a match. A bulleted sub-bullet
#: (``  - Route: executor``) and a bare indented line (``  Route: executor``)
#: are the SAME field at this grain - the leading dash is punctuation, not
#: part of what a Route line means - so neither this pattern nor either of
#: its callers draws a distinction between the two.
ROUTE_LINE_PATTERN = r"(?<![A-Za-z0-9_-])Route:[ \t]*(?P<value>[^\r\n]*)"
ROUTE_RE = re.compile(ROUTE_LINE_PATTERN)
ACCEPT_RE = re.compile(r"(?<![A-Za-z0-9_-])Accept:")

#: NEAR-MISS DETECTION for Route: and Accept:, added alongside the two
#: strict patterns above without changing either of them - ROUTE_RE /
#: ROUTE_LINE_PATTERN and ACCEPT_RE stay the SOLE, authoritative,
#: case-sensitive definition of "a real field", unchanged, still what
#: ``has_route``/``has_accept`` below are decided by, still what
#: ``scripts/keel_attest.py`` imports. These near-miss patterns are never
#: consulted for presence; they run only once a strict search has already
#: come back False for the whole block, purely to find WHERE a would-be
#: field went wrong, so a finding can cite that line and quote that text
#: instead of falling back to "no such line at all". Two shapes are near
#: misses, both confirmed against this project's own ledgers: wrong case
#: (``accept:`` reads as absent today) and a gap between the word and its
#: colon (``Accept (restated for convenience; ...):``, the exact text that
#: cost this session a round trip). Both patterns are the SAME literal word
#: and lookbehind the strict patterns use, widened with IGNORECASE and a
#: bounded gap before the colon - if the strict patterns' word or lookbehind
#: ever changes, these must change with them, which is why they live here
#: rather than elsewhere.
_NEAR_MISS_GAP = 64
ROUTE_NEAR_MISS_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])Route\b[^\r\n:]{{0,{_NEAR_MISS_GAP}}}:", re.IGNORECASE
)
ACCEPT_NEAR_MISS_RE = re.compile(
    rf"(?<![A-Za-z0-9_-])Accept\b[^\r\n:]{{0,{_NEAR_MISS_GAP}}}:", re.IGNORECASE
)

#: A near-miss match is disqualified when its gap crosses a sentence break
#: (``.``, ``!`` or ``?`` followed by whitespace): that is the shape of the
#: plain English word ("...does not accept placeholders. Route: ...")
#: followed, sentences later, by some OTHER field's colon - not one
#: malformed field. See ``_first_near_miss``.
_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s")


def _first_near_miss(pattern: re.Pattern[str], block_text: str) -> re.Match[str] | None:
    """The first NEAR-MISS match in ``block_text`` not crossing a sentence break.

    NOT authoritative - see the patterns' own comment above. Only ever
    called once the matching strict pattern has already found nothing in
    the whole block.
    """
    for match in pattern.finditer(block_text):
        if _SENTENCE_BREAK_RE.search(match.group(0)[:-1]):
            continue
        return match
    return None


def _near_miss_location(block_text: str, block_start: int, match: re.Match[str]) -> tuple[int, str]:
    """The near miss's absolute 1-based line number and its stripped text."""
    offset = block_text.count("\n", 0, match.start())
    text = block_text.splitlines()[offset].strip()
    if len(text) > 100:
        text = text[:97] + "..."
    return block_start + offset + 1, text


#: The banned placeholder vocabulary, verbatim from
#: ``templates/keel-plan-contract.md``, each as a case-insensitive pattern.
PLACEHOLDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("TBD", re.compile(r"\btbd\b", re.IGNORECASE)),
    ("etc.", re.compile(r"etc\.", re.IGNORECASE)),
    ("handle appropriately", re.compile(r"handle appropriately", re.IGNORECASE)),
    ("as needed", re.compile(r"\bas needed\b", re.IGNORECASE)),
    ("similar to the above", re.compile(r"similar to the above", re.IGNORECASE)),
)


class PlansError(RuntimeError):
    """The checker could not run at all. The caller returns 2 (fail-closed)."""


class Finding(NamedTuple):
    """One thing that is true of one ledger, at one line."""

    path: str
    line: int
    rule: str
    severity: str
    detail: str


class Task(NamedTuple):
    """One parsed task line plus its continuation block."""

    line: int
    identifier: str | None
    title: str
    block_lines: tuple[str, ...]
    has_route: bool
    has_accept: bool
    #: (line, text) of the nearest Route-shaped near miss, or None - only
    #: ever set when ``has_route`` is False. See ``ROUTE_NEAR_MISS_RE``.
    route_near_miss: tuple[int, str] | None
    #: Same as ``route_near_miss``, for Accept. Only set when ``has_accept``
    #: is False. See ``ACCEPT_NEAR_MISS_RE``.
    accept_near_miss: tuple[int, str] | None


def _is_continuation(line: str) -> bool:
    """Whether ``line`` extends the task block opened by the line before it."""
    if line.strip() == "":
        return True
    return line[:1] in (" ", "\t")


def parse_tasks(text: str) -> list[Task]:
    """Every task line in ``text``, each with its continuation block.

    Pure: no filesystem, no clock. A line not opening a task is skipped
    without affecting the tasks found around it (headings, prose, the
    preamble before ``## Tasks``).
    """
    lines = text.splitlines()
    tasks: list[Task] = []
    index = 0
    total = len(lines)
    while index < total:
        match = TASK_LINE_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        rest = match.group("rest").strip()
        id_match = IDENTIFIER_RE.match(rest)
        identifier = id_match.group(1) if id_match else None
        block_start = index
        cursor = index + 1
        while cursor < total and _is_continuation(lines[cursor]):
            cursor += 1
        block = tuple(lines[block_start:cursor])
        block_text = "\n".join(block)
        has_route = ROUTE_RE.search(block_text) is not None
        has_accept = ACCEPT_RE.search(block_text) is not None
        route_near_miss = None
        if not has_route:
            near = _first_near_miss(ROUTE_NEAR_MISS_RE, block_text)
            if near is not None:
                route_near_miss = _near_miss_location(block_text, block_start, near)
        accept_near_miss = None
        if not has_accept:
            near = _first_near_miss(ACCEPT_NEAR_MISS_RE, block_text)
            if near is not None:
                accept_near_miss = _near_miss_location(block_text, block_start, near)
        tasks.append(
            Task(
                line=block_start + 1,
                identifier=identifier,
                title=rest,
                block_lines=block,
                has_route=has_route,
                has_accept=has_accept,
                route_near_miss=route_near_miss,
                accept_near_miss=accept_near_miss,
            )
        )
        index = cursor
    return tasks


def _task_label(task: Task) -> str:
    """A short label for report text: the identifier, or a line reference."""
    return task.identifier if task.identifier is not None else f"(no identifier, line {task.line})"


def _field_finding(
    path: str,
    task: Task,
    label: str,
    field: str,
    near_miss: tuple[int, str] | None,
) -> Finding:
    """One finding for a missing ``Route:``/``Accept:`` field.

    Shared by both fields so a Route improvement cannot land without the
    matching Accept improvement, or the reverse (T203 clause 3). A true
    absence still cites the task's OPENING line, unchanged from before; a
    near miss cites the OFFENDING line and quotes the text found there
    (T203 clauses 1 and 2), instead of reading identically to an absence.
    """
    rule = f"missing_{field.lower()}"
    if near_miss is not None:
        near_line, near_text = near_miss
        return Finding(
            path,
            near_line,
            rule,
            WARN,
            f"task {label} has text at line {near_line} that looks like a "
            f"'{field}:' field but does not match it: {near_text!r}",
        )
    return Finding(
        path,
        task.line,
        rule,
        WARN,
        f"task {label} has no '{field}:' line",
    )


def check_ledger(path: str, text: str, strict: bool) -> list[Finding]:
    """Every finding for one ledger's text. Pure: no filesystem, no clock."""
    out: list[Finding] = []
    for task in parse_tasks(text):
        label = _task_label(task)
        if task.identifier is None:
            out.append(
                Finding(
                    path,
                    task.line,
                    "missing_identifier",
                    ERROR if strict else WARN,
                    f"task line at {label} carries no Tn identifier after its checkbox",
                )
            )
        if not task.has_route:
            out.append(_field_finding(path, task, label, "Route", task.route_near_miss))
        if not task.has_accept:
            out.append(_field_finding(path, task, label, "Accept", task.accept_near_miss))
        for offset, line in enumerate(task.block_lines):
            for phrase, pattern in PLACEHOLDER_PATTERNS:
                if pattern.search(line):
                    out.append(
                        Finding(
                            path,
                            task.line + offset,
                            "placeholder_phrase",
                            WARN,
                            f"task {label} carries banned phrase {phrase!r}",
                        )
                    )
    return sorted(out, key=lambda finding: (finding.line, finding.rule))


# --------------------------------------------------------------- collection


def default_ledgers(project: Path) -> list[Path]:
    """Every ``*.md`` directly under the project's default plans directory.

    An absent directory is not an error - a project with no ledgers yet has
    none to check.
    """
    directory = project.joinpath(*DEFAULT_PLANS_DIR)
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.glob("*.md") if p.is_file())


def display_path(ledger: Path, project: Path) -> str:
    """The path as the report prints it: project-relative wherever possible."""
    try:
        return ledger.resolve().relative_to(project.resolve()).as_posix()
    except (ValueError, OSError):
        return ledger.name


def check_tree(ledgers: Sequence[Path], project: Path, strict: bool) -> list[Finding]:
    """Every finding for ``ledgers``, sorted by path, line and rule."""
    findings: list[Finding] = []
    for ledger in ledgers:
        shown = display_path(ledger, project)
        text = ledger.read_text(encoding="utf-8", errors="replace")
        findings.extend(check_ledger(shown, text, strict))
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.rule))


# ---------------------------------------------------------------- reporting


def summarize(findings: Sequence[Finding], checked: int) -> dict[str, object]:
    """Counts by rule and by file - the shape ``--json`` publishes."""
    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    errors = 0
    warnings = 0
    for finding in findings:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
        by_file[finding.path] = by_file.get(finding.path, 0) + 1
        if finding.severity == ERROR:
            errors += 1
        else:
            warnings += 1
    return {
        "ledgers_checked": checked,
        "total": len(findings),
        "errors": errors,
        "warnings": warnings,
        "by_rule": by_rule,
        "by_file": by_file,
    }


def render_text(findings: Sequence[Finding], checked: int, quiet: bool) -> str:
    """The human report. Complete whether or not it found anything."""
    summary = summarize(findings, checked)
    lines: list[str] = []
    if not quiet:
        for finding in findings:
            tag = "" if finding.severity == ERROR else " (warn)"
            lines.append(f"{finding.path}:{finding.line}: [{finding.rule}]{tag} {finding.detail}")
        if findings:
            lines.append("")
    errors = summary["errors"]
    warnings = summary["warnings"]
    head = "keel plans: clean" if not errors else f"keel plans: {errors} finding(s)"
    if warnings:
        head += f", {warnings} warning(s)"
    head += f" ({checked} ledger(s) checked)"
    lines.append(head)
    if findings and not quiet:
        lines.append("by rule:")
        for rule, count in sorted(summary["by_rule"].items()):
            lines.append(f"  {rule}: {count}")
        lines.append("by file:")
        for path, count in sorted(summary["by_file"].items()):
            lines.append(f"  {path}: {count}")
    return "\n".join(lines)


def render_json(findings: Sequence[Finding], checked: int) -> str:
    """The same report as a document."""
    summary = summarize(findings, checked)
    payload = {
        "clean": summary["errors"] == 0,
        "summary": summary,
        "findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "rule": finding.rule,
                "severity": finding.severity,
                "detail": finding.detail,
            }
            for finding in findings
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """check ledger tasks against the keel plan-document contract"""
    parser = argparse.ArgumentParser(
        prog="keel plans",
        description="keel-plan-contract checker for session ledgers (advisory by design)",
    )
    parser.add_argument(
        "ledgers",
        nargs="*",
        metavar="ledger.md",
        help="ledger file(s) to check (default: every *.md under .keel/plans/)",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="promote missing_identifier to an ERROR (exit 1 if any is found)",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    parser.add_argument("--quiet", action="store_true", help="emit only the summary")
    args = parser.parse_args(argv)

    try:
        project = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        if args.ledgers:
            ledgers: list[Path] = []
            for raw in args.ledgers:
                candidate = Path(raw)
                if not candidate.is_file():
                    raise PlansError(f"ledger not found: {raw}")
                ledgers.append(candidate)
        else:
            ledgers = default_ledgers(project)
    except OSError as exc:
        print(f"keel plans: {exc}", file=sys.stderr)
        return 2
    except PlansError as exc:
        print(f"keel plans: {exc}", file=sys.stderr)
        return 2

    try:
        findings = check_tree(ledgers, project, args.strict)
    except OSError as exc:
        print(f"keel plans: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(render_json(findings, len(ledgers)))
    else:
        print(render_text(findings, len(ledgers), args.quiet))
    return 1 if any(finding.severity == ERROR for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
