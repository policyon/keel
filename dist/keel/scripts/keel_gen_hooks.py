#!/usr/bin/env python3
"""Generator for hooks/hooks.json — one bootstrap string, one entry table (R13).

Contract
--------
Reads   : nothing but its own two constants — BOOTSTRAP, the single shell
          bootstrap proven on all three operating systems by the Phase 0
          spike, and ENTRIES, the table of hook registrations. In
          ``--verify`` mode it also reads the committed hooks/hooks.json.
Emits   : one result line per run on stdout; the diff summary beneath it when
          verification fails.
Writes  : hooks/hooks.json (default mode only), UTF-8, LF line endings.
Argv    : ``--verify`` compares instead of writing; ``--print`` writes the
          generated document to stdout and touches nothing; no flag
          regenerates the file in place.

Exit codes
----------
0  written, printed, or verified equal.
1  ``--verify`` found the committed file different from the generated one.
2  the generator could not run at all.

Why generate
------------
A hand-maintained hooks.json ends up carrying the same multi-kilobyte
bootstrap verbatim once per entry; every fix then has to be applied to each
copy, and one of them will be missed (R13). keel writes the bootstrap once.
Adding a hook is one row in ENTRIES, and CI re-runs ``--verify`` so the
committed file can never drift from the table.

Failure policy
--------------
FAIL-CLOSED. This is a build gate: a verification that cannot read the
committed file is a failure, never a pass (convention 12). This declaration
is asserted by tests/test_keel_kernel.py.

Constraints
-----------
Python 3.10+, standard library only. The bootstrap contains no payload-derived
value and no interpolation of anything but a subcommand name drawn from this
file's own table (R5). The generated file is written with newline="\\n" so a
Windows checkout cannot commit CRLF.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

#: The subcommand placeholder inside BOOTSTRAP. Chosen so it cannot occur in
#: shell text by accident, and substituted by str.replace rather than
#: str.format — the bootstrap legitimately contains ${CLAUDE_PLUGIN_ROOT}.
SUBCOMMAND_TOKEN = "@SUB@"

#: The one launch program, proven on Ubuntu, macOS and Windows by the Phase 0
#: spike. It resolves the plugin root, translates it with cygpath where that
#: exists (the single Windows hook pattern verified in the field), and probes
#: for a *working* Python 3.10+ rather than a merely present one — on Windows
#: `command -v python3` finds the Microsoft Store stub, which exits 49.
BOOTSTRAP = (
    'R="${CLAUDE_PLUGIN_ROOT}"; '
    "command -v cygpath >/dev/null 2>&1 && R=\"$(cygpath -u \"$R\")\"; "
    "for P in python3 python py; do "
    "\"$P\" -c 'import sys;sys.exit(sys.version_info[:2]<(3,10))' >/dev/null 2>&1 "
    f'&& exec "$P" "$R/hooks/keel_hook.py" {SUBCOMMAND_TOKEN}; '
    "done; "
    "echo 'keel: no Python 3.10+ found; hook skipped' >&2; exit 0"
)


#: The tools the gate and the action-capture registrations both cover: every
#: state-changing tool Claude Code exposes, in both its shell spellings.
STATE_CHANGING_MATCHER = "Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell"

#: The delegation tools. ``Task`` is current; ``Agent`` is the older spelling.
DELEGATION_MATCHER = "Task|Agent"

#: What the CAPTURE registrations watch: the delegation tools, plus the
#: message-send tool a resume goes through (T124). A resumed agent calls no
#: launch tool, so a registration that named only the delegation tools saw
#: nothing at all while it worked - see "A RESUME IS A HAND-OFF THE RECORD
#: NEVER SAW" in ``hooks/keel_capture.py``. Widening the two existing rows
#: rather than adding two more is deliberate: the always-loaded budget (R9)
#: charges every ``command`` string in this document, and a matcher costs
#: nothing. ``keel_capture`` records a message-send only when it is addressed
#: to an agent, so the wider subscription writes no wider a log.
HANDOFF_MATCHER = DELEGATION_MATCHER + "|SendMessage"


@dataclass(frozen=True)
class HookEntry:
    """One registration: which harness event, which tools, which subcommand.

    ``is_async`` renders as ``"async": true`` and is convention 11 in the
    table: gates block and therefore never carry it; observers carry it and
    may emit no decision. TWO observers do not carry it, and both for the
    same reason - their stdout is injected CONTEXT rather than a decision, and
    an async hook's output arrives too late to be context: ``SessionStart``
    (the castoff block) and, since T473, ``UserPromptSubmit`` (the context
    nudge). Neither emits a decision; both make the session wait for one
    Python launch, which is the price of speaking into the turn rather than
    after it.
    """

    event: str
    subcommand: str
    matcher: str | None = None
    timeout: int = 10
    is_async: bool = False


#: The registration table. One row per hook; adding a hook is one row here
#: and one regeneration, never a hand-edit of the generated document (R13).
ENTRIES: tuple[HookEntry, ...] = (
    HookEntry(event="SessionStart", subcommand="session"),
    HookEntry(event="SessionEnd", subcommand="session", is_async=True),
    HookEntry(event="PreToolUse", subcommand="gate", matcher=STATE_CHANGING_MATCHER),
    HookEntry(
        event="PreToolUse",
        subcommand="capture",
        matcher=HANDOFF_MATCHER,
        is_async=True,
    ),
    HookEntry(
        event="PostToolUse",
        subcommand="capture",
        matcher=STATE_CHANGING_MATCHER,
        is_async=True,
    ),
    HookEntry(
        event="PostToolUse",
        subcommand="capture",
        matcher=HANDOFF_MATCHER,
        is_async=True,
    ),
    HookEntry(event="Stop", subcommand="stop"),
    #: The delegation-finish event. Registered async because it is an
    #: OBSERVER: the subcommand writes one audit line and emits no decision,
    #: so it must never make a returning subagent wait (convention 11). It is
    #: the third member of the delegation family, alongside the two
    #: ``Task``/``Agent`` capture rows above - the launch and the launch
    #: tool's return - and the only one of the three that reports an ENDING.
    #: Its consumer predates it by several waves: ``keel_stop.py`` has
    #: branched on ``subagent_stop`` since before anything produced one.
    HookEntry(event="SubagentStop", subcommand="subagent_stop", is_async=True),
    #: The two compaction-survival registrations (T228). Both are OBSERVERS -
    #: they write to keel's user-global state and emit no decision.
    #: ``PreCompact`` fires while the harness is about to throw the
    #: conversation away, all it does is write down where the lossless copy
    #: lives, and it carries ``async`` (convention 11).
    #:
    #: ``UserPromptSubmit`` DOES NOT, since T473, and it is the second
    #: exception to convention 11's async-observer rule for the same reason as
    #: the first (``SessionStart``): its stdout is CONTEXT - the context nudge,
    #: one line on the turns where a new ten-percent step of the window is
    #: crossed - and an async hook's output arrives too late to be context (see
    #: the ``HookEntry`` docstring). The cost is one Python launch per prompt,
    #: before the user's turn, on the one hook that sees the user's own words;
    #: it was put to the owner with its alternative and accepted in
    #: ``.keel/decisions/2026-09-03-the-bl28-window-takes-the-runbook-defaults.md``
    #: (Decision A). ONE registration still does both jobs - the same
    #: subcommand records the prompt and nudges - because a second row on this
    #: event would charge the always-loaded budget for a second copy of the
    #: bootstrap to buy the very same launch.
    #:
    #: THEIR COST WAS MEASURED BEFORE THEY WERE ADDED, and the measurement is
    #: why the ceiling moved rather than the other way round: two more
    #: ``command`` strings are 616 characters, 154 tokens at the estimator's
    #: fixed rate, against 132 tokens of headroom under the old 1200 - so
    #: ``.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md``
    #: was ratified first and this table changed with it, in one reviewed
    #: change. Neither row carries a matcher: neither event names a tool, and
    #: a matcher that matched nothing would cost bytes to say nothing.
    HookEntry(event="UserPromptSubmit", subcommand="prompt"),
    HookEntry(event="PreCompact", subcommand="precompact", is_async=True),
)


def repo_root() -> Path:
    """Repository root, derived from this file's location (scripts/ is a child)."""
    return Path(__file__).resolve().parent.parent


def hooks_json_path(root: Path | None = None) -> Path:
    """The generated document's committed location."""
    return (root or repo_root()) / "hooks" / "hooks.json"


def command_for(entry: HookEntry) -> str:
    """The bootstrap with this entry's subcommand substituted in."""
    if SUBCOMMAND_TOKEN in entry.subcommand:
        raise ValueError(f"subcommand may not contain {SUBCOMMAND_TOKEN}")
    return BOOTSTRAP.replace(SUBCOMMAND_TOKEN, entry.subcommand)


def build_document(entries: tuple[HookEntry, ...] = ENTRIES) -> dict:
    """The whole hooks.json document, entries grouped by harness event."""
    hooks: dict[str, list[dict]] = {}
    for entry in entries:
        group: dict = {}
        if entry.matcher is not None:
            group["matcher"] = entry.matcher
        hook: dict = {"type": "command", "shell": "bash", "timeout": entry.timeout}
        if entry.is_async:
            hook["async"] = True
        hook["command"] = command_for(entry)
        group["hooks"] = [hook]
        hooks.setdefault(entry.event, []).append(group)
    return {"hooks": hooks}


def render(entries: tuple[HookEntry, ...] = ENTRIES) -> str:
    """The exact text the committed hooks.json must contain, byte for byte."""
    return json.dumps(build_document(entries), indent=2, ensure_ascii=False) + "\n"


def write(path: Path | None = None) -> Path:
    """Regenerate the committed document. Returns the path written."""
    target = path or hooks_json_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render())
    return target


def verify(path: Path | None = None) -> list[str]:
    """Compare committed against generated; return violation lines (empty = ok)."""
    target = path or hooks_json_path()
    if not target.is_file():
        raise RuntimeError(f"no committed hooks.json at {target}")
    with open(target, encoding="utf-8", newline="") as handle:
        committed = handle.read()
    expected = render()
    if committed == expected:
        return []
    violations = [f"{target.name} differs from the generated document"]
    if "\r\n" in committed:
        violations.append("committed file has CRLF line endings; the generator writes LF")
    committed_lines = committed.splitlines()
    expected_lines = expected.splitlines()
    if len(committed_lines) != len(expected_lines):
        violations.append(
            f"line count {len(committed_lines)} != generated {len(expected_lines)}"
        )
    for number, (got, want) in enumerate(zip(committed_lines, expected_lines), start=1):
        if got != want:
            violations.append(f"line {number}: committed {got.strip()[:80]!r}")
            violations.append(f"line {number}: generated {want.strip()[:80]!r}")
            break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel_gen_hooks.py", description="generate or verify hooks/hooks.json"
    )
    parser.add_argument(
        "--verify", action="store_true", help="fail if the committed file differs"
    )
    parser.add_argument(
        "--print", dest="print_only", action="store_true", help="write to stdout only"
    )
    args = parser.parse_args(argv)

    try:
        if args.print_only:
            sys.stdout.write(render())
            return 0
        if args.verify:
            violations = verify()
            if violations:
                print(f"FAIL gen-hooks: {len(violations)} finding(s)")
                for violation in violations:
                    print(f"    {violation}")
                print("    run: python scripts/keel_gen_hooks.py")
                return 1
            print(f"PASS gen-hooks: {hooks_json_path().name} matches the generator")
            return 0
        target = write()
        print(f"WROTE {target} ({len(ENTRIES)} entries)")
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR gen-hooks could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
