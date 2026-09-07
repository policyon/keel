#!/usr/bin/env python3
"""scan git-tracked files for content that must never leave this machine.

Contract
--------
Reads   : every file ``git ls-files`` reports for the repository containing
          the working directory (or ``--repo-root``), line by line, plus an
          optional ``--denylist`` file. Binary-looking files are skipped by
          content sniffing rather than by name.
Emits   : one ``path:line: [rule] excerpt`` line per finding, then a summary
          by rule and by file; ``--json`` emits the same as a document. The
          matched span is ALWAYS masked, and the mask is fixed-width, so
          neither the secret nor its true length is ever printed.
Writes  : nothing. It reports; scrubbing is the caller's decision.
Argv    : ``--denylist FILE``, ``--json``, ``--quiet``, ``--repo-root PATH``.

Exit codes
----------
0  clean.
1  findings - listed on stdout.
2  the scanner itself could not run (no git, not inside a work tree, an
   unreadable denylist, a bad regex in one).

What it looks for
-----------------
Anthropic-style keys, AWS access key ids, GitHub tokens and fine-grained
PATs, ``Bearer`` tokens, keyword-guarded secret assignments, private-key
blocks, email addresses, bare high-entropy strings, and absolute home paths
naming a real user - ``C:\\Users\\<name>``, ``/home/<name>``, ``/Users/<name>``
- including the Windows 8.3 short form, which is just another string this
pattern already matches. The home-path rule is the second line of defence
behind ``hooks/keel_redact.py``: redaction stops the leak at write time, this
stops what was written before the redactor existed.

Suppressing a known false positive: put ``keel-leak: ignore`` anywhere on the
offending line, in whatever comment syntax the file uses. The whole line is
then skipped by every rule, including the denylist. There is no per-path or
per-file exclusion - only this line-level, deliberately visible escape hatch,
because an exclusion list is where a real finding goes to be forgotten.

Failure policy
--------------
FAIL-CLOSED. This is a build gate: a scan that cannot enumerate the tracked
files, or cannot compile its own denylist, returns 2 rather than reporting a
clean tree (convention 12). It is also deliberately not tunable-to-pass: it
reports the true count and leaves the decision to the caller.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). ``git`` is invoked with an
argument list, never a shell string (R5). No network. Every pattern is
case-insensitive (convention 3): a key pasted in the wrong case is still a
key, and the entropy rule keeps its own case-MIX requirement, which is a
property of the token rather than of the pattern.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple, Sequence

#: The line-level escape hatch. Everything else about this scanner is total.
SUPPRESS_RE = re.compile(r"keel-leak:\s*ignore\b", re.IGNORECASE)

#: Skipped by extension before the content sniff, purely to save the read.
BINARY_EXTENSIONS = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".pdf", ".zip", ".gz",
        ".tar", ".7z", ".exe", ".dll", ".so", ".pyc", ".pyd", ".woff", ".woff2",
        ".ttf", ".eot", ".whl",
    }
)

#: Windows and macOS pseudo-accounts: not a real person's home directory.
RESERVED_HOME_NAMES = frozenset(
    {"public", "default", "default user", "all users", "defaultuser0", "guest", "shared"}
)

#: Separators may appear doubled in tracked text (a JSONL record storing a
#: Windows path escapes each backslash), so one-or-more is the right count.
_WIN_HOME_RE = re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+([^\\/:*?"<>|\r\n]{1,80})', re.IGNORECASE)
_POSIX_HOME_RE = re.compile(r'/home/([^/:\s"\'<>|]{1,80})', re.IGNORECASE)  # keel-leak: ignore - this scanner's own home-path pattern
_MAC_HOME_RE = re.compile(r'/Users/([^/:\s"\'<>|]{1,80})', re.IGNORECASE)  # keel-leak: ignore - this scanner's own home-path pattern

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.IGNORECASE)
_ANTHROPIC_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}", re.IGNORECASE)
_AWS_KEY_RE = re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE)
_GITHUB_TOKEN_RE = re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE)
_GITHUB_PAT_RE = re.compile(r"github_pat_[A-Za-z0-9_]{22,}", re.IGNORECASE)
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9\-_.~+/]{20,}", re.IGNORECASE)

#: A keyword-guarded assignment: a name ending in password/secret/api-key/
#: token, then ``:`` or ``=``, then a literal of 8+ characters. The keyword
#: may be the suffix of a longer identifier (``WIDGET_API_KEY``).
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b[A-Za-z0-9_.\-]*(?:password|passwd|pwd|secret|api[_-]?key|token)\b"
    r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-/+.=]{8,})[\"']?",
    re.IGNORECASE,
)

#: A bare high-entropy token with no keyword nearby. The case-MIX test below
#: is what keeps this rule from drowning in lowercase hex ids and UUIDs,
#: which are high-entropy without being secret.
_ENTROPY_TOKEN_RE = re.compile(r"[A-Za-z0-9+/_\-]{32,}")
ENTROPY_MIN_BITS = 3.5
ENTROPY_MIN_LEN = 32


class Finding(NamedTuple):
    """One reported occurrence. ``excerpt`` is masked before it gets here."""

    path: str
    line: int
    rule: str
    excerpt: str


class DenyEntry(NamedTuple):
    """One denylist rule: a literal substring, or a ``/regex/``."""

    kind: str
    value: Any
    raw: str


def mask(secret: str) -> str:
    """Mask a matched span; the fixed width hides the true length too."""
    length = len(secret)
    if length <= 6:
        return "*" * length
    keep = min(4, length // 3) or 1
    return f"{secret[:keep]}{'*' * 6}{secret[-keep:]}"


def excerpt(line: str, start: int, end: int, window: int = 20) -> str:
    """A bounded, triage-useful excerpt with the match itself masked."""
    return f"{line[max(0, start - window):start]}{mask(line[start:end])}{line[end:end + window]}".strip()


def shannon_entropy(text: str) -> float:
    """Bits per character. Only ever used as a threshold, never printed."""
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    total = len(text)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def looks_like_secret_token(token: str) -> bool:
    """Case-mix AND entropy. Either alone reports half the repository."""
    if not (
        any(c.isupper() for c in token)
        and any(c.islower() for c in token)
        and any(c.isdigit() for c in token)
    ):
        return False
    return shannon_entropy(token) >= ENTROPY_MIN_BITS


def load_denylist(path: str) -> list[DenyEntry]:
    """Parse a denylist file. A bad regex is an error, never a skipped line."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError(f"cannot read denylist {path!r}: {exc}") from exc
    entries: list[DenyEntry] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if len(line) >= 2 and line.startswith("/") and line.endswith("/"):
            try:
                entries.append(DenyEntry("regex", re.compile(line[1:-1], re.IGNORECASE), line))
            except re.error as exc:
                raise ValueError(f"invalid regex in denylist {path!r}: {line!r}: {exc}") from exc
        else:
            entries.append(DenyEntry("literal", line, line))
    return entries


def find_repo_root(start: str | None = None) -> str:
    """The work tree containing ``start``. Argument list only, no shell (R5)."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=start or os.getcwd(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError("not inside a git work tree: " + (proc.stderr or "").strip())
    return str(Path(proc.stdout.strip()).resolve())


def tracked_files(root: str) -> list[str]:
    """Everything git tracks, repository-wide, whatever directory we ran in.

    EMPTY IS A FAILURE, NOT A CLEAN TREE. ``git ls-files`` exits 0 with no
    output whenever it was asked about somewhere it tracks nothing — a fresh
    repository, an ignored subdirectory of an enclosing work tree, a root that
    is not the repository the caller meant — so the empty list arrives looking
    exactly like a clean answer. A scan of zero files knows nothing, and
    reporting that as clean would read as knowing everything, which is the one
    answer this scanner must never give. It raises instead and lets both
    callers fail closed: the gate turns the raise into a violation, the CLI
    into its exit code 2. ``keel_checks._tracked_text_files`` refuses the same
    state for the same reason.
    """
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
        raise RuntimeError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError("git ls-files failed: " + (proc.stderr or "").strip())
    tracked = [line for line in proc.stdout.splitlines() if line]
    if not tracked:
        raise RuntimeError(
            f"git tracks no files under {root} - a scan of zero files knows "
            "nothing, and reporting it as clean would read as knowing everything"
        )
    return tracked


def _sniff(path: Path) -> bytes | None:
    """The first 8 KiB, or None when the file cannot be read at all.

    The None is the whole point: a file that reads as empty and a file that
    would not open are opposite states, and this is the last place that can
    still tell them apart. Every caller above collapses them one way or the
    other, so each one has to choose deliberately.
    """
    try:
        with path.open("rb") as handle:
            return handle.read(8192)
    except OSError:
        return None


def _chunk_is_binary(chunk: bytes) -> bool:
    """NUL byte, then UTF-8 decodability - in that order."""
    if b"\x00" in chunk:
        return True
    try:
        chunk.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False



#: Rules whose whole match is the secret.
SIMPLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("anthropic_key", _ANTHROPIC_KEY_RE),
    ("aws_access_key", _AWS_KEY_RE),
    ("github_token", _GITHUB_TOKEN_RE),
    ("github_token", _GITHUB_PAT_RE),
    ("bearer_token", _BEARER_RE),
    ("private_key_block", _PRIVATE_KEY_RE),
    ("email", _EMAIL_RE),
)


def home_path_findings(rel_path: str, line_no: int, line: str) -> list[Finding]:
    """The three home-path shapes, deduped by overlapping span.

    ``C:/Users/bob/`` satisfies the macOS pattern too, one character later; (keel-leak: ignore - documents the pattern with an example path)
    reporting it twice under the same rule would inflate the count without
    adding a fact.
    """
    found: list[Finding] = []
    occupied: list[tuple[int, int]] = []
    for pattern in (_WIN_HOME_RE, _POSIX_HOME_RE, _MAC_HOME_RE):
        for match in pattern.finditer(line):
            span = (match.start(), match.end())
            if any(a < span[1] and span[0] < b for a, b in occupied):
                continue
            if match.group(1).strip().casefold() in RESERVED_HOME_NAMES:
                continue
            occupied.append(span)
            found.append(Finding(rel_path, line_no, "home_path", excerpt(line, *span)))
    return found


def scan_line(
    rel_path: str, line_no: int, line: str, denylist: Sequence[DenyEntry]
) -> list[Finding]:
    """Every rule, over one line. The suppression comment short-circuits all."""
    if SUPPRESS_RE.search(line):
        return []
    findings: list[Finding] = []
    occupied: list[tuple[int, int]] = []

    for rule, pattern in SIMPLE_RULES:
        for match in pattern.finditer(line):
            occupied.append((match.start(), match.end()))
            findings.append(Finding(rel_path, line_no, rule, excerpt(line, match.start(), match.end())))

    for match in _SECRET_ASSIGNMENT_RE.finditer(line):
        span = (match.start(1), match.end(1))
        if any(a < span[1] and span[0] < b for a, b in occupied):
            continue  # a specific rule already owns this span
        occupied.append(span)
        findings.append(Finding(rel_path, line_no, "secret_assignment", excerpt(line, *span)))

    findings.extend(home_path_findings(rel_path, line_no, line))

    for match in _ENTROPY_TOKEN_RE.finditer(line):
        span = (match.start(), match.end())
        if len(match.group(0)) < ENTROPY_MIN_LEN:
            continue
        if any(a < span[1] and span[0] < b for a, b in occupied):
            continue
        if looks_like_secret_token(match.group(0)):
            findings.append(Finding(rel_path, line_no, "high_entropy_token", excerpt(line, *span)))

    for entry in denylist:
        if entry.kind == "literal":
            index = line.find(entry.value)
            if index != -1:
                findings.append(
                    Finding(
                        rel_path,
                        line_no,
                        "denylist",
                        excerpt(line, index, index + len(entry.value)),
                    )
                )
        else:
            for match in entry.value.finditer(line):
                findings.append(
                    Finding(rel_path, line_no, "denylist", excerpt(line, match.start(), match.end()))
                )
    return findings


#: What one file's scan actually did. EXACTLY ONE of these is honest about
#: having seen the contents: ``SCANNED``. The other three are all "no lines were
#: examined", and they differ only in why, which is why they are four constants
#: and not a boolean.
SCANNED = "scanned"
BINARY = "binary"
EXTENSION = "extension"
ABSENT = "absent"
UNREADABLE = "unreadable"

#: Not read, and legitimately so: ``BINARY`` was opened and sniffed as non-text,
#: ``EXTENSION`` was never opened at all because its suffix said not to bother.
#: THE SECOND ONE IS A TRUST DECISION, NOT A MEASUREMENT - a tracked
#: ``secrets.gz`` holding plaintext is skipped on its name, and this scanner
#: will not see it. Counted and printed separately from ``BINARY`` for exactly
#: that reason: an unopened file must never be reported as one that was read.
SKIPPED_OUTCOMES = (BINARY, EXTENSION)

#: The outcomes that read nothing AND had no business failing to. A caller
#: gating on this scanner treats these as failures rather than as clean files -
#: see :class:`ScanReport` and ``keel_checks.check_leak``.
BLIND_OUTCOMES = (ABSENT, UNREADABLE)


class ScanReport(NamedTuple):
    """A tree scan's findings AND which files produced them.

    ``findings`` alone cannot distinguish a tree that is clean from a tree that
    was never opened: both are the empty list. This carries the PATHS rather
    than bare counts so a caller can apply its own scope before counting —
    a gate that exempts some directories must be able to say how many files it
    read *in the part it gates*, not across the whole tree. Same reason
    ``keel_checks`` prints its scan set before the checks that read it: a run
    must never be green about a file it never opened (R45).
    """

    findings: list[Finding]
    scanned: list[str]
    skipped: list[tuple[str, str]]
    blind: list[tuple[str, str]]


def scan_file_reported(
    root: str, rel_path: str, denylist: Sequence[DenyEntry]
) -> tuple[list[Finding], str]:
    """One tracked file, with WHAT HAPPENED beside the findings.

    An empty finding list means one of two opposite things - read and clean, or
    never read - and only the outcome tells them apart.
    """
    full = Path(root) / rel_path
    if not full.is_file():
        return [], ABSENT
    if full.suffix.lower() in BINARY_EXTENSIONS:
        return [], EXTENSION
    chunk = _sniff(full)
    if chunk is None:
        return [], UNREADABLE
    if _chunk_is_binary(chunk):
        return [], BINARY
    try:
        text = full.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], UNREADABLE
    findings: list[Finding] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        findings.extend(scan_line(rel_path, line_no, line, denylist))
    return findings, SCANNED


def scan_file(root: str, rel_path: str, denylist: Sequence[DenyEntry]) -> list[Finding]:
    """One tracked file, or nothing at all when it is binary or gone."""
    return scan_file_reported(root, rel_path, denylist)[0]


def scan_tree_reported(
    root: str, tracked: Sequence[str], denylist: Sequence[DenyEntry]
) -> ScanReport:
    """Every tracked file, in git's own order, with the census beside it."""
    findings: list[Finding] = []
    scanned: list[str] = []
    skipped: list[tuple[str, str]] = []
    blind: list[tuple[str, str]] = []
    for rel in tracked:
        normalised = rel.replace("\\", "/")
        found, outcome = scan_file_reported(root, normalised, denylist)
        findings.extend(found)
        if outcome == SCANNED:
            scanned.append(normalised)
        elif outcome in SKIPPED_OUTCOMES:
            skipped.append((normalised, outcome))
        elif outcome in BLIND_OUTCOMES:
            blind.append((normalised, outcome))
        else:
            # An outcome this loop was never taught about must not land in
            # whichever bucket happens to be last: that is how a new skip path
            # would arrive already counted as clean.
            raise RuntimeError(f"unknown scan outcome {outcome!r} for {normalised}")
    return ScanReport(findings, scanned, skipped, blind)


def scan_tree(root: str, tracked: Sequence[str], denylist: Sequence[DenyEntry]) -> list[Finding]:
    """Every tracked file, in git's own order."""
    return scan_tree_reported(root, tracked, denylist).findings


def summarize(findings: Sequence[Finding]) -> dict[str, Any]:
    """Counts by rule and by file - the shape a reviewer triages from."""
    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    for finding in findings:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
        by_file[finding.path] = by_file.get(finding.path, 0) + 1
    return {"total": len(findings), "by_rule": by_rule, "by_file": by_file}


def render_text(findings: Sequence[Finding], quiet: bool) -> str:
    lines: list[str] = []
    if not quiet:
        for finding in findings:
            lines.append(f"{finding.path}:{finding.line}: [{finding.rule}] {finding.excerpt}")
        if findings:
            lines.append("")
    summary = summarize(findings)
    if not findings:
        lines.append("keel leak-check: clean")
        return "\n".join(lines)
    lines.append(f"keel leak-check: {summary['total']} finding(s)")
    if not quiet:
        lines.append("by rule:")
        for rule, count in sorted(summary["by_rule"].items()):
            lines.append(f"  {rule}: {count}")
        lines.append("by file:")
        for path, count in sorted(summary["by_file"].items()):
            lines.append(f"  {path}: {count}")
    return "\n".join(lines)


def render_json(findings: Sequence[Finding]) -> str:
    return json.dumps(
        {
            "clean": not findings,
            "summary": summarize(findings),
            "findings": [finding._asdict() for finding in findings],
        },
        indent=2,
        ensure_ascii=False,
    )


def main(argv: list[str] | None = None) -> int:
    """scan git-tracked files for content that must not leave this machine"""
    parser = argparse.ArgumentParser(
        prog="keel leak-check",
        description="blocking scanner for content that must not leave this machine",
    )
    parser.add_argument("--denylist", metavar="FILE", default=None, help="extra literals/regexes")
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    parser.add_argument("--quiet", action="store_true", help="summary line only")
    parser.add_argument("--repo-root", metavar="PATH", default=None, help="override the work tree")
    args = parser.parse_args(argv)

    try:
        root = args.repo_root or find_repo_root()
        tracked = tracked_files(root)
        denylist = load_denylist(args.denylist) if args.denylist else []
    except (RuntimeError, OSError, ValueError) as exc:
        print(f"keel leak-check: error: {exc}", file=sys.stderr)
        return 2

    findings = scan_tree(root, tracked, denylist)
    print(render_json(findings) if args.as_json else render_text(findings, args.quiet))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
