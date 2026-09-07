#!/usr/bin/env python3
"""run the full-discovery test suite and gate on its SUMMARY, not only exit 0.

Contract
--------
Reads   : nothing on disk directly; spawns
          ``python -m unittest discover -s <start-dir> -v`` (or whatever argv
          this wrapper is given after ``--``) as a child process and reads its
          captured stdout and stderr in full.
Writes  : one captured log file, always — every run, pass or fail — so the
          evidence exists whether or not anyone is watching. Default path is a
          fresh file under the platform temp directory; ``--log PATH`` pins it.
Emits   : the run's own verdict line, the log path, and — on failure — the
          tail of the captured output (the evidence), on stdout/stderr.
Argv    : ``--start-dir DIR`` (default ``tests``), ``--log PATH``,
          ``--tail-lines N`` (default 40), and ``-- ARGS...`` to replace the
          default ``discover -s <start-dir> -v`` invocation outright (used by
          this script's own end-to-end test, which targets one small module
          rather than the whole suite).

Exit codes
----------
0  the child exited 0 AND its captured output's tail carries the unittest
   summary — a ``Ran N tests ...`` line immediately followed (blank lines
   aside) by an ``OK`` line (``OK (skipped=N)`` and similar parenthetical
   forms both count).
1  either half is missing: a nonzero child exit, a ``FAILED (...)`` status,
   a summary line with no recognised status after it, or no summary line at
   all — the last of these is the exact BL59 shape this wrapper exists to
   close: the suite can end mid-run with exit code 0 and no final summary.
2  the wrapper itself could not run the child or read its output.

Failure policy
--------------
FAIL-CLOSED (BL59, ``.keel/backlog.md``). Exit 0 alone is not a green suite:
this project's own gate on itself found the ONLY gating site
(``.github/workflows/keel-ci.yml``) trusting the child's exit code alone,
while a run that died mid-discovery still reported exit 0 with no summary
line at all — green while wrong. Unreadable, empty or truncated output is
always a FAILURE that says the summary went unverified, never a pass; see
:func:`suite_verdict`, the seam this file's own tests drive directly.

A truncation trap already paid for once, on this exact suite
(``.keel/knowledge/piping-a-suite-run-through-tail-destroys-the-evidence-it-
was-run-for.md``): a shell pipe to ``tail`` reports the PIPE's exit status,
not the child's, and can silently keep the wrong end of interleaved
stdout/stderr. This wrapper never pipes the child through anything — it
captures both streams whole via :mod:`subprocess`, verifies against the
unmerged text, and only ever truncates for the human-facing tail print,
never for the verdict.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Subprocess is invoked with an
argument list, never a shell string (R5).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

#: A unittest summary's count line, e.g. ``Ran 3069 tests in 379.669s``.
RAN_RE = re.compile(r"^Ran (\d+) tests? in [\d.]+s$")

#: The status line unittest prints after the (possibly blank-separated) count
#: line on a clean run: ``OK`` alone, or with a parenthetical
#: (``OK (skipped=2)``, ``OK (expected failures=1)``, and so on).
STATUS_OK_RE = re.compile(r"^OK(\s*\(.*\))?$")

#: The status line on a run with failures/errors, e.g. ``FAILED (failures=1)``.
STATUS_FAILED_RE = re.compile(r"^FAILED\s*\(.*\)$")

#: The knowledge record this wrapper exists to satisfy, quoted in every
#: failure message so a reader lands on the finding, not just the symptom.
BL59_NOTE = (
    "BL59 (.keel/backlog.md): the full-discovery suite can end mid-run with "
    "exit code 0 and no final summary — a green-while-wrong shape this "
    "wrapper's verdict function exists to close."
)


def suite_verdict(exit_code: int, output: str | None) -> tuple[bool, str]:
    """Whether a suite run is genuinely green: exit 0 AND a summary saying so.

    ``output`` is the text stream that carries unittest's own summary —
    ``TextTestRunner`` writes both the ``Ran N tests`` line and the following
    ``OK``/``FAILED`` line to the SAME stream (stderr, by unittest's default),
    in that order, so this function needs no interleaving logic: it is never
    handed a merge of two streams, which is exactly the trap the module
    docstring names.

    FAIL-CLOSED at every branch: ``None``/empty output, a missing summary
    line, a summary with no recognised status after it, or an unrecognised
    status word are all failures whose message says the summary went
    unverified — never silently treated as a pass. Returns
    ``(passed, message)``.
    """
    if output is None or not output.strip():
        return False, (
            "FAIL: no output was captured to check — the 'Ran N tests' "
            f"summary went unverified. {BL59_NOTE}"
        )

    lines = output.splitlines()
    ran_idx: int | None = None
    for index in range(len(lines) - 1, -1, -1):
        if RAN_RE.match(lines[index].strip()):
            ran_idx = index
            break

    if ran_idx is None:
        return False, (
            "FAIL: no 'Ran N tests' summary line found anywhere in the "
            f"captured output — the summary went unverified. {BL59_NOTE}"
        )

    status_line: str | None = None
    for index in range(ran_idx + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped:
            continue
        status_line = stripped
        break

    if status_line is None:
        return False, (
            "FAIL: a 'Ran N tests' line was found but nothing recognisable "
            "followed it (the run ended right after the count) — the "
            f"summary went unverified. {BL59_NOTE}"
        )

    if STATUS_FAILED_RE.match(status_line):
        return False, f"FAIL: suite reported {status_line!r}"

    if not STATUS_OK_RE.match(status_line):
        return False, (
            f"FAIL: unrecognised status line {status_line!r} after the "
            f"summary count — the summary went unverified. {BL59_NOTE}"
        )

    if exit_code != 0:
        return False, (
            f"FAIL: suite reported {status_line!r} but the child's exit "
            f"code was {exit_code}, not 0 — the two disagree"
        )

    return True, f"PASS: {lines[ran_idx].strip()}; {status_line}"


def run_child(argv: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run the child suite, capturing stdout and stderr WHOLE, never piped.

    Returns ``(exit_code, stdout, stderr)``. Raises ``RuntimeError`` if the
    child cannot even be launched — that is a wrapper failure (exit 2), never
    a quiet pass.
    """
    try:
        proc = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run {argv!r}: {exc}") from exc
    return proc.returncode, proc.stdout, proc.stderr


def write_log(log_path: Path, argv: list[str], exit_code: int, stdout: str, stderr: str) -> None:
    """The full captured log, both streams labelled and kept in full — the
    convention this project follows for a suite run: redirect the whole run
    to a file rather than a pipe, so nothing downstream can truncate it."""
    parts = [
        f"$ {' '.join(argv)}",
        f"exit code: {exit_code}",
        "----- stdout -----",
        stdout,
        "----- stderr -----",
        stderr,
        "",
    ]
    log_path.write_text("\n".join(parts), encoding="utf-8")


def tail(text: str, n: int) -> str:
    """The last ``n`` lines of ``text`` — for the human-facing evidence print
    only; the verdict itself never truncates (see :func:`suite_verdict`)."""
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel_suite",
        description="run the full-discovery suite, gated on the summary line, not just exit 0",
    )
    parser.add_argument("--start-dir", default="tests", help="discovery start dir (default: tests)")
    parser.add_argument("--log", metavar="PATH", default=None, help="where to write the full captured log")
    parser.add_argument("--tail-lines", type=int, default=40, help="lines of evidence to print on failure")
    parser.add_argument("child_args", nargs="*", help="replace the default discover invocation, after --")
    args = parser.parse_args(argv)

    child_argv = (
        [sys.executable, *args.child_args]
        if args.child_args
        else [sys.executable, "-m", "unittest", "discover", "-s", args.start_dir, "-v"]
    )

    if args.log:
        log_path = Path(args.log)
    else:
        handle = tempfile.NamedTemporaryFile(
            prefix="keel-suite-", suffix=".log", delete=False
        )
        handle.close()
        log_path = Path(handle.name)

    repo_root = Path(__file__).resolve().parent.parent

    try:
        exit_code, stdout, stderr = run_child(child_argv, repo_root)
    except RuntimeError as exc:
        print(f"keel_suite: error: {exc}", file=sys.stderr)
        return 2

    try:
        write_log(log_path, child_argv, exit_code, stdout, stderr)
    except OSError as exc:
        print(f"keel_suite: error: cannot write log {log_path}: {exc}", file=sys.stderr)
        return 2

    passed, message = suite_verdict(exit_code, stderr)
    print(message)
    print(f"keel_suite: full captured log: {log_path}")

    if not passed:
        print("----- tail of captured output (stderr) -----", file=sys.stderr)
        print(tail(stderr, args.tail_lines), file=sys.stderr)
        if stdout.strip():
            print("----- tail of captured output (stdout) -----", file=sys.stderr)
            print(tail(stdout, args.tail_lines), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
