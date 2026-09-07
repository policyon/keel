#!/usr/bin/env python3
"""Claude Code adapter - native payload in, native verdict out.

Contract
--------
Reads   : one decoded Claude Code hook payload (a dict), plus the environment
          variable ``CLAUDE_PROJECT_DIR`` (the harness's stable project root;
          the payload's ``cwd`` drifts with the session shell, so the
          environment wins when both are present).
Emits   : ``KeelEvent`` for the kernel, and on the way back one line of JSON
          on stdout in Claude Code's hook contract:

              {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                      "permissionDecision": "deny",
                                      "permissionDecisionReason": "..."}}

          plus the same reason on stderr, which is where Claude Code shows a
          blocking hook's message. An ALLOW verdict emits nothing at all:
          keel refuses to auto-approve tool calls, so the harness's own
          permission flow is left untouched (see "Allow is silence" below).
Writes  : nothing. This module has no filesystem side effects.
Argv    : none. Library module, imported by ``keel_hook.py``.

Exit codes
----------
``emit`` returns ``KeelVerdict.to_exit_code()`` and nothing else: allow -> 0,
ask -> 2, deny -> 2 (R6). The adapter never invents a code, so the code and
the JSON decision cannot drift apart.

Allow is silence
----------------
Claude Code treats ``permissionDecision: "allow"`` as an auto-approval that
bypasses the user's own permission rules. A gate that answered "allow" in
JSON would therefore *widen* permissions it was installed to narrow, so an
allow verdict produces no JSON and exit 0. Deny and ask, which narrow, are
always emitted in full.

Policy
------
NONE. This file maps names to names. Every decision - arming, tiers, plan
freshness, the policy lock - lives in ``keel_gate.py`` / ``keel_stop.py``,
which is what makes a second harness a translation exercise rather than a
re-implementation: a swap is proven by an adapter passing the kernel's own
fixtures, never asserted by a diagram.

Failure policy
--------------
FAIL-OPEN. A payload this adapter cannot map to a normalised event yields
``None``, and the launcher then does nothing: an unrecognised event names no
tool and no target, so there is nothing to gate and the harness's own
permissions still apply. Mapping never raises on unexpected field types.

Constraints
-----------
Python 3.10+, standard library only. Tool and hook-event names are matched
case-insensitively (convention 3); both-case fixtures ship in
tests/fixtures/gate/. No payload value is ever interpolated into a shell
string, a path, or a format template (R5).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_events import KeelEvent, KeelVerdict, normalise_paths, utc_now  # noqa: E402

#: State-changing file tools -> pre_write. Matched casefolded (convention 3).
WRITE_TOOLS: tuple[str, ...] = ("Write", "Edit", "MultiEdit", "NotebookEdit")

#: Shell tools -> pre_exec. On Windows Claude Code names its shell tool
#: "PowerShell", not "Bash"; missing that leaves an unguarded shell surface,
#: so both names are first-class here.
SHELL_TOOLS: tuple[str, ...] = ("Bash", "PowerShell")

#: Native hook event name -> normalised kind, for events that are not tool
#: calls. PreToolUse is absent deliberately: its kind comes from the tool.
HOOK_EVENT_KINDS: Mapping[str, str] = {
    "stop": "stop",
    "sessionstart": "session_start",
    "sessionend": "session_end",
    "posttooluse": "post_tool",
}

#: Normalised kind -> the hookEventName echoed back in the JSON contract.
KIND_HOOK_EVENT_NAMES: Mapping[str, str] = {
    "pre_write": "PreToolUse",
    "pre_exec": "PreToolUse",
    "post_tool": "PostToolUse",
    "stop": "Stop",
    "session_start": "SessionStart",
    "session_end": "SessionEnd",
}

#: tool_input keys that carry a path, in the order Claude Code uses them.
PATH_KEYS: tuple[str, ...] = ("file_path", "notebook_path", "path")

_TOOL_KINDS: dict[str, str] = {name.casefold(): "pre_write" for name in WRITE_TOOLS}
_TOOL_KINDS.update({name.casefold(): "pre_exec" for name in SHELL_TOOLS})


def _text(value: Any) -> str | None:
    """A non-empty string, or None. Any other type is absence, not an error."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _mapping(value: Any) -> Mapping[str, Any]:
    """A mapping, or an empty one. Payload shape is never trusted."""
    return value if isinstance(value, Mapping) else {}


def project_dir(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> Path:
    """The project root: CLAUDE_PROJECT_DIR, else payload cwd, else process cwd.

    The payload's cwd follows the session shell into subdirectories; the
    environment variable is the stable root, so a `cd` mid-session cannot
    disarm a gate or hide a ledger.
    """
    env = os.environ if env is None else env
    return Path(
        _text(env.get("CLAUDE_PROJECT_DIR"))
        or _text(payload.get("cwd"))
        or os.getcwd()
    )


def file_paths_of(tool_input: Mapping[str, Any]) -> tuple[str, ...]:
    """Every path a write-class tool call targets, in payload order.

    MultiEdit carries one ``file_path`` plus an ``edits`` list; some harness
    versions repeat the path inside each edit, so both places are read and
    duplicates are collapsed.
    """
    candidates: list[Any] = [tool_input.get(key) for key in PATH_KEYS]
    edits = tool_input.get("edits")
    if isinstance(edits, list):
        for edit in edits:
            edit_map = _mapping(edit)
            candidates.extend(edit_map.get(key) for key in PATH_KEYS)
    seen: list[str] = []
    for path in normalise_paths(candidates):
        if path not in seen:
            seen.append(path)
    return tuple(seen)


def event_kind(payload: Mapping[str, Any]) -> str | None:
    """Normalised kind for a payload, or None when nothing maps.

    A tool call decides by tool name; every other event decides by
    ``hook_event_name``. Both are matched casefolded (convention 3, R1).
    """
    hook_event = (_text(payload.get("hook_event_name")) or "").casefold()
    tool = (_text(payload.get("tool_name")) or "").casefold()
    if hook_event and hook_event != "pretooluse":
        return HOOK_EVENT_KINDS.get(hook_event)
    return _TOOL_KINDS.get(tool)


def event_from_payload(
    payload: Mapping[str, Any],
    env: Mapping[str, str] | None = None,
    assume_kind: str | None = None,
) -> KeelEvent | None:
    """Translate a Claude Code payload into a KeelEvent, or None if unmappable.

    ``assume_kind`` is used by a subcommand that already knows which event it
    was registered for (the Stop hook fires with no tool name at all, and
    older harness builds omit ``hook_event_name`` entirely).
    """
    payload = _mapping(payload)
    kind = event_kind(payload) or assume_kind
    if kind is None:
        return None
    tool_input = _mapping(payload.get("tool_input"))
    return KeelEvent(
        kind=kind,
        cwd=project_dir(payload, env),
        session_id=_text(payload.get("session_id")),
        tool_name=_text(payload.get("tool_name")),
        file_paths=file_paths_of(tool_input),
        command=_text(tool_input.get("command")),
        raw=payload,
        ts=utc_now(),
    )


def hook_event_name(event: KeelEvent) -> str:
    """The hookEventName to echo back: the payload's own, else the kind's."""
    return _text(event.raw.get("hook_event_name")) or KIND_HOOK_EVENT_NAMES[event.kind]


def verdict_to_output(verdict: KeelVerdict, event: KeelEvent) -> dict[str, Any] | None:
    """The hookSpecificOutput object for a blocking verdict, else None.

    None means "say nothing": see "Allow is silence" in the module contract.
    """
    if not verdict.blocking:
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name(event),
            "permissionDecision": verdict.decision,
            "permissionDecisionReason": verdict.reason,
        }
    }


def emit(
    verdict: KeelVerdict,
    event: KeelEvent,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Write the verdict in Claude Code's contract; return its exit code (R6)."""
    output = verdict_to_output(verdict, event)
    if output is not None:
        print(json.dumps(output, ensure_ascii=False), file=stdout or sys.stdout)
        print(verdict.reason, file=stderr or sys.stderr)
    return verdict.to_exit_code()
