#!/usr/bin/env python3
"""keel doctor - synthetic hook launches and known-broken-pattern scan (T225).

Contract
--------
Reads   : ``hooks/hooks.json`` (this installation's own registrations); the
          user-global ``~/.claude/settings.json`` and the surveyed project's
          ``.claude/settings.json`` / ``.claude/settings.local.json`` (the
          known-broken-pattern scan, R30's source list, restated here rather
          than imported because ``keel_survey`` is a pure-read module and this
          one is not - see "Why a new module" below); and, through
          ``keel_survey.version_report``, the plugin manifest / changelog /
          component fingerprint this installation already knows how to read,
          and through ``keel_survey.install_report`` (T500), the harness's own
          record of which tree it installed, against the tree this runs from.
          And, for "keel's own failures as numbers" below, two logs keel
          itself writes: the user-global hook-error log through
          ``keel_faultlog.state`` (never parsed here - the module that owns the
          three states answers them) and the surveyed project's own audit log
          through ``keel_events.read_audit``.
Emits   : a human-readable report on stdout, or ``--json``. Every filesystem
          path in it passes ``keel_redact.redact`` first (convention 5).
Writes  : nothing to ``.keel/`` anywhere - see "Zero-trace synthetic launch"
          below. Each probe DOES create and destroy its own throwaway
          temporary directory (never inside this project, never inside the
          surveyed one), which is not a record of anything and is removed
          before this process exits.
Argv    : ``--project DIR`` (the settings-scan target; defaults like
          ``keel_survey``'s), ``--json``.

Why a new module, not a section of ``keel_survey.py``
------------------------------------------------------
Measured before writing anything here: ``keel_survey.py``'s own contract
declares "Writes: nothing at all. A survey that changes what it surveys is
not a survey" and "Constraints: ... No subprocess, no network" as hard,
tested invariants (T206's whole test suite, and the module docstring itself,
would start lying the moment a survey launched a process). A synthetic hook
launch is a subprocess by definition. Bolting that onto ``keel_survey``
would not be an extension, it would be the deletion of the one guarantee
that report exists to make, so this is the honest shape instead: a sibling
module wired into ``scripts/keel.py`` exactly the way ``keel_survey`` itself
is (a lazy-imported subcommand, claimed in ``scripts/keel-features.json``
under ``kernel``, the same feature that owns ``keel_survey.py``).

Zero-trace synthetic launch
----------------------------
T185 measured a probe that called ``keel_gate.evaluate`` against THIS
project three times to answer a question and appended one real
``workshop_write`` line to this project's own audit log for a write that
never happened - the exact failure this task is warned against repeating.
The fix here is structural rather than promised: every probe's payload
``cwd``, AND the ``CLAUDE_PROJECT_DIR`` environment variable handed to the
child process (``keel_adapter_claude.project_dir`` reads the environment
FIRST, so only overriding the payload would not be enough), point at a
freshly created temporary directory that carries no ``.keel/`` at all. Every
hook subcommand's own ``run`` - ``keel_session.run``, ``keel_capture.run``,
``keel_hook.cmd_subagent_stop``, ``keel_hook.cmd_prompt``,
``keel_hook.cmd_precompact``, and both gates' fail-open branch for an unarmed
project - returns before it ever calls ``append_audit`` (or, for the two
compaction observers, ``keel_compaction.record_prompt`` /
``record_compaction``) when the target directory is not keel-bearing (read
directly, in each of those seven functions, before this module was written a
line of its own logic). The probe additionally re-checks the throwaway
directory's own contents after each launch and reports a trace as its own
state (:data:`STATE_BROKEN`) rather than trusting the design never to
regress.

Known-broken-pattern scan
--------------------------
Translates the known-broken hook patterns a predecessor doctor skill
documents into keel's own
registration shape: an ``args`` array (Claude Code's settings rewriter drops
unknown fields and silently kills the hook), a ``$CLAUDE_PROJECT_DIR`` /
``%CLAUDE_PROJECT_DIR%`` variable a Windows shell will not expand, a
RELATIVE script path (resolves against the session shell's persisted cwd),
and a ``Stop``/``PreToolUse`` command with no visible failure wrapper (a
crash exiting non-zero can be misread as a block). Every one of these is a
REPORT, never a refusal - this module blocks nothing, exactly like
``keel_survey`` (R30's own convention).

Keel's own failures, as numbers (T235/T236)
--------------------------------------------
Clause 5 of ``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``
requires that repeated crashes be a VISIBLE NUMBER, so two counts sit at the
foot of the report: the hook-error log's three states (``absent`` /
``present`` / ``unreadable``, never collapsed - a log keel could not read is
not a log that says nothing happened), and the crash-denies in the surveyed
project's audit log, split into the three kinds a reader acts on differently
and GROUPED BY SESSION.

Both are REPORTED AND NOT SCORED - they are deliberately outside
``exit_code``. They are a history, not a present state: one bad edit a month
ago is still in the log, and the ruling's own unfreeze (clause 4) is a human
act, so a doctor that exited 1 forever afterwards would teach its reader to
ignore the only signal a script can read.

Exit codes
----------
0  every registration probed healthy, and the pattern scan found nothing to
   report and no source it could not read.
1  at least one probe or pattern finding says something worth a look - this
   INCLUDES a probe this doctor could not fully establish (degraded,
   skipped, unreadable), and INCLUDES a settings SOURCE the pattern scan
   could not read at all (malformed/unreadable, carried in
   ``pattern_notes``): that source is the same "cannot establish" shape as
   an unreadable probe, so it is scored the same way, never as healthy by
   omission (see "Failure vocabulary" below).
2  the check could not run at all - ``hooks/hooks.json`` itself is missing,
   unreadable, or carries no ``hooks`` table, so there is nothing to probe.
   An unreadable settings SOURCE for the pattern scan does not qualify for
   this: the registrations are still known and still probed, so that is
   scored 1 (above), never 2 - 2 is reserved for the doctor having nothing
   at all to probe.

Failure vocabulary
-------------------
Every probe answers one of exactly five states, never fewer:
``healthy`` (launched, returned the documented allow/no-op exit, left no
trace), ``degraded`` (launched and returned 0, but its own launcher could not
find a working Python 3.10+ - the harness would see "succeeded" for a hook
that never ran), ``broken`` (a non-zero exit where the documented one is
0, a timeout, or a trace left in the throwaway project), ``skipped`` (no
usable ``bash`` could be resolved, so a zero-trace launch could not be
attempted at all - this is convention 7's rule, never silently promoted to a
pass; this now covers TWO distinct causes, both reported the same way
because neither one measured anything: no ``bash`` resolves at all through
:func:`harness_bash`'s three steps, OR one resolves but
:func:`bash_is_usable` proves it cannot even run a trivial ``-c`` command -
BL29's own finding, a ``bash`` on PATH that launches but is not the
harness's interpreter and cannot run anything (WSL's launcher with no
distro installed is exactly this: it exists, ``shutil.which`` finds it, and
it still cannot run ``echo``). Either way the detail names the launcher
path and, for the second cause, its stderr, and says plainly that the
registrations were NOT MEASURED - neither healthy nor broken, because
nothing was proven either way), and ``unreadable`` (the probe itself could
not even be started, e.g. the temporary directory could not be created).
Nothing here is ever reported as healthy by omission.

Failure policy
--------------
FAIL-CLOSED for the check itself (an unreadable ``hooks.json`` is exit 2,
never a report of zero registrations); FAIL-OPEN for each individual probe,
in the sense that a hook this doctor cannot verify is reported as its own
state rather than raising and losing every other probe's result with it.

AND THE DIAGNOSTIC OUTLIVES A BROKEN KEEL, which is a stronger claim than
either: ``keel_survey`` is imported inside a guard because its own import chain
reaches ``keel_gate``, so a gate module that no longer compiles would otherwise
kill this file with a traceback in the one state a reader runs it for. That
degrades the version line - which says why - and nothing else.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every subprocess is invoked
with an argument list, never a shell string built from payload-derived text
(R5) - the JSON payload travels on stdin exactly as a harness would send it,
never interpolated into the command. Every file read states its encoding.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import keel_events  # noqa: E402
import keel_faultlog  # noqa: E402
from keel_redact import redact  # noqa: E402

#: ``keel_survey`` IS IMPORTED GUARDED, which is not the house style, and the
#: reason is the state this diagnostic exists to be useful in. That module
#: reaches ``keel_checks`` -> ``keel_session`` -> ``keel_gate`` at its own
#: module scope, so a gate module that no longer compiles - the exact fault
#: ``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md`` and
#: T236 are about - took THIS FILE down with a traceback instead of letting it
#: report the broken gate. Measured 2026-08-21 against a deliberately
#: half-written ``keel_gate.py``: exit 1, no report at all, in the one state
#: clause 4's reader is trying to diagnose. The three modules above
#: (``keel_events``, ``keel_faultlog``, ``keel_redact``) are unguarded because
#: they import no gate and cannot be broken by one.
#:
#: The two things the survey answers here both have honest fallbacks, and the
#: report SAYS which one it used - a degraded version line, never a wrong one.
_SURVEY_FAULT = ""
try:
    import keel_survey  # noqa: E402
except Exception as _survey_exc:  # noqa: BLE001 - a diagnostic must outlive a broken keel
    keel_survey = None  # type: ignore[assignment]
    _SURVEY_FAULT = f"{type(_survey_exc).__name__}: {_survey_exc}"
    print(
        f"keel doctor: the survey module could not be imported, so the version "
        f"fingerprint is unavailable and the project directory is resolved "
        f"inline: {_SURVEY_FAULT}",
        file=sys.stderr,
    )

#: Where this installation's own registrations live.
HOOKS_JSON_RELPATH: tuple[str, ...] = ("hooks", "hooks.json")

#: The audit ``gate`` values a CRASH-DENY writes, and the audit ``event`` the
#: launcher writes when it could not even reach a gate to ask. Clause 5 of
#: ``.keel/decisions/2026-08-21-a-crash-is-a-deny-that-names-itself.md``: every
#: crash-deny is audited with its fault kind and the doctor surface reports the
#: count, "so repeated crashes are a visible number". THREE KINDS, KEPT APART,
#: because they send a reader to three different repairs:
#:
#: * ``internal_error`` - a gate's own failure policy refused (or, in an unarmed
#:   project, allowed): keel's code raised while deciding.
#: * ``internal_error_ledger`` - the crash-time ``.keel/plans/`` carve-out let a
#:   ledger write through loudly. Not a refusal, and still a crash.
#: * ``launcher_crash_deny`` - the launcher could not reach a gate AT ALL, so it
#:   denied on its own. The most serious of the three: an import failed.
CRASH_DENY_GATES: tuple[str, ...] = ("internal_error", "internal_error_ledger")
CRASH_DENY_EVENT = "launcher_crash_deny"
CRASH_DENY_KINDS: tuple[str, ...] = (*CRASH_DENY_GATES, CRASH_DENY_EVENT)

#: What a crash-deny group is filed under when the line names no session. An
#: EXPLICIT bucket, never merged into a real session's count: "keel does not
#: know whose turn this was" is a fact about the record, not a missing value to
#: quietly drop (convention 7).
CRASH_DENY_NO_SESSION = "(no session named)"

#: How long a single synthetic launch may run before it is called broken.
#: Generous next to the registered ``"timeout": 10`` seconds every entry in
#: ``hooks/hooks.json`` already declares, so a slow but honest launch is not
#: mistaken for a hung one.
PROBE_TIMEOUT_SECONDS = 20.0

#: The session id every synthetic payload carries, so a reader of any log
#: this probe SHOULD never write to would recognise it instantly if the
#: zero-trace guarantee ever failed.
PROBE_SESSION_ID = "keel-doctor-probe"

#: The stderr marker ``hooks/hooks.json``'s own bootstrap prints, verbatim,
#: when no Python interpreter it tried was 3.10+. A probe that sees this has
#: proven the LAUNCHER runs, and proven that nothing behind it did.
NO_PYTHON_MARKER = "no python 3.10+ found"

WRITE_TOOLS: tuple[str, ...] = ("Write", "Edit", "MultiEdit", "NotebookEdit")
SHELL_TOOLS: tuple[str, ...] = ("Bash", "PowerShell")
DELEGATION_TOOLS: tuple[str, ...] = ("Task", "Agent", "SendMessage")

#: Events whose payload names no tool at all - the harness fires them with a
#: fixed shape regardless of matcher.
NO_TOOL_EVENTS: tuple[str, ...] = ("SessionStart", "SessionEnd", "Stop", "SubagentStop")

STATE_HEALTHY = "healthy"
STATE_DEGRADED = "degraded"
STATE_BROKEN = "broken"
STATE_SKIPPED = "skipped"
STATE_UNREADABLE = "unreadable"

#: Every state a probe may answer, in the fixed order the report walks them.
PROBE_STATES: tuple[str, ...] = (
    STATE_HEALTHY,
    STATE_DEGRADED,
    STATE_BROKEN,
    STATE_SKIPPED,
    STATE_UNREADABLE,
)

#: The environment variable Claude Code itself honours on Windows to name the
#: Git-for-Windows ``bash`` it launches hooks through - read here FIRST for
#: the same reason: this doctor's whole claim is "the HARNESS's launcher",
#: never merely "a bash", and this is the most direct statement of which one
#: that is when the harness has set it (BL29).
CLAUDE_CODE_GIT_BASH_PATH_VAR = "CLAUDE_CODE_GIT_BASH_PATH"

#: How long the trivial usability probe (:func:`bash_is_usable`) may run
#: before the interpreter is called unusable rather than merely slow. Far
#: below :data:`PROBE_TIMEOUT_SECONDS`: this is one ``echo``, not a hook.
BASH_USABLE_TIMEOUT_SECONDS = 5.0

#: The marker :func:`bash_is_usable` looks for on stdout - anything else
#: (including a truncated or garbled stdout) is read as "did not run".
BASH_USABLE_MARKER = "keel-doctor-bash-ok"


def derive_git_bash(git_exe: Path, windows: bool) -> Path | None:
    """The Git-for-Windows ``bash`` that ships beside ``git_exe``, or ``None``.

    Takes ``windows`` as a parameter rather than reading ``os.name`` itself so
    the derivation can be exercised on every platform this suite runs on
    (this repo's fail-closed test doctrine: a Windows-only code path is not
    allowed to hide behind a skip on Linux/macOS CI - it is instead made
    unconditionally callable, and the CALLER decides, once, whether the
    platform is Windows). Returns ``None`` off Windows, and off Windows only.

    ``git_exe`` is normally one of three shapes: ``<root>\\cmd\\git.exe``,
    ``<root>\\bin\\git.exe``, or ``<root>\\mingw64\\bin\\git.exe`` - the
    fixed number of parents to ``<root>`` differs by shape, so this walks
    ``git_exe``'s own parents looking for the first one that carries a
    ``bin\\bash.exe`` sibling, rather than assuming a fixed depth.
    """
    if not windows:
        return None
    for parent in (git_exe.parent, *git_exe.parents):
        candidate = parent / "bin" / "bash.exe"
        if candidate.is_file():
            return candidate
    return None


def harness_bash() -> tuple[str | None, str]:
    """The ``bash`` the harness itself would launch hooks through, and why.

    Three steps, in this fixed order, because the order is BL29's whole
    fix - a probe that measures the FIRST ``bash`` on ``PATH`` measures
    nothing the harness actually calls:

    1. ``CLAUDE_CODE_GIT_BASH_PATH`` from the environment, when set AND the
       file it names exists - this is the variable Claude Code itself
       honours on Windows, so when the harness has set it, this is not a
       guess at the harness's choice, it IS the harness's choice.
    2. On Windows (``os.name == "nt"``), the Git-for-Windows ``bash``
       derived from the ``git`` found on ``PATH`` (:func:`derive_git_bash`) -
       the harness's own documented fallback, and the one BL29 measured
       missing.
    3. ``shutil.which("bash")`` - the last resort, and the ONLY step the
       pre-fix code ever took.

    Returns ``(path, note)``. ``path`` is ``None`` when nothing resolves at
    all. ``note`` is always one line, redacted (paths may carry a home
    directory or a username): it says which step won, and - the part BL29
    asks for by name - when the chosen bash differs from what
    ``shutil.which("bash")`` alone would have picked, it names BOTH paths so
    a reader can see exactly what changed.
    """
    path_first = shutil.which("bash")
    override = os.environ.get(CLAUDE_CODE_GIT_BASH_PATH_VAR)
    if override and Path(override).is_file():
        note = f"{CLAUDE_CODE_GIT_BASH_PATH_VAR} (environment): {redact(override)}"
        if path_first and os.path.abspath(override) != os.path.abspath(path_first):
            note += f" - differs from PATH-first bash {redact(path_first)}"
        return override, note
    if os.name == "nt":
        git_exe = shutil.which("git")
        if git_exe:
            derived = derive_git_bash(Path(git_exe), windows=True)
            if derived is not None:
                derived_str = str(derived)
                note = f"derived from Git for Windows ({redact(git_exe)}): {redact(derived_str)}"
                if path_first and os.path.abspath(derived_str) != os.path.abspath(path_first):
                    note += f" - differs from PATH-first bash {redact(path_first)}"
                return derived_str, note
    if path_first:
        return path_first, f"PATH-first bash (shutil.which): {redact(path_first)}"
    return None, "no 'bash' resolved by any step (env override, Git-for-Windows, PATH)"


def bash_is_usable(bash: str) -> tuple[bool, str]:
    """Prove ``bash`` can run one trivial command before probing anything.

    Runs ``[bash, "-c", "echo " + BASH_USABLE_MARKER]`` as an argument list
    (never a shell string - R5) with a short timeout. Usable iff the process
    exits 0 AND the marker is on stdout; any other outcome (non-zero exit,
    timeout, launch failure, or a marker that never appears - a launcher
    that "succeeds" while printing nothing proves nothing) is reported False
    with the tail of whatever the launcher itself said, redacted and capped,
    so BL29's own symptom (WSL's ``getpwuid(0) failed`` /
    ``execvpe(/bin/bash) failed``) reaches the report instead of being
    swallowed as a plain "skipped".
    """
    try:
        result = subprocess.run(
            [bash, "-c", f"echo {BASH_USABLE_MARKER}"],
            capture_output=True,
            timeout=BASH_USABLE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {BASH_USABLE_TIMEOUT_SECONDS:.0f}s running a trivial command"
    except OSError as exc:
        return False, redact(f"could not launch: {type(exc).__name__}: {exc}")[:300]
    stdout = result.stdout.decode("utf-8", errors="replace")
    if result.returncode == 0 and BASH_USABLE_MARKER in stdout:
        return True, ""
    stderr = result.stderr.decode("utf-8", errors="replace")
    detail = redact(stderr.strip() or stdout.strip() or f"exit {result.returncode}, no output")
    return False, detail[:300]


@dataclass(frozen=True)
class HookRegistration:
    """One hook command, read from ``hooks/hooks.json`` exactly as it is."""

    event: str
    matcher: str
    command: str
    source: str

    def head(self, chars: int = 60) -> str:
        return self.command.replace("\n", " ")[:chars]


@dataclass(frozen=True)
class ProbeResult:
    """The verdict for one registration's synthetic launch."""

    registration: HookRegistration
    state: str
    detail: str
    returncode: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.registration.event,
            "matcher": self.registration.matcher,
            "command": redact(self.registration.head()),
            "source": self.registration.source,
            "state": self.state,
            "detail": redact(self.detail),
            "returncode": self.returncode,
        }


def _read_json(path: Path) -> tuple[Any, str | None]:
    """``(document, error)``. An absent file is absence, not an error."""
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace")), None
    except (OSError, ValueError) as exc:
        return None, f"unreadable {redact(str(path))}: {type(exc).__name__}: {exc}"


def read_hook_registrations(root: Path | None = None) -> tuple[list[HookRegistration], str | None]:
    """Every hook command in ``hooks/hooks.json``, or the one reason there are none.

    Returns ``(registrations, fatal_error)``. ``fatal_error`` is set only when
    the file itself could not be read or carries no ``hooks`` table at all -
    the condition this module's own CLI answers exit 2 for, because a doctor
    that cannot see what is registered has nothing to diagnose.
    """
    root = _REPO_ROOT if root is None else Path(root)
    path = root.joinpath(*HOOKS_JSON_RELPATH)
    source = "/".join(HOOKS_JSON_RELPATH)
    document, error = _read_json(path)
    if error:
        return [], error
    if document is None:
        return [], f"{redact(str(path))}: not found"
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return [], f"{redact(str(path))}: carries no 'hooks' table"
    found: list[HookRegistration] = []
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher") if isinstance(group.get("matcher"), str) else ""
            entries = group.get("hooks")
            entries = entries if isinstance(entries, list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                command = entry.get("command")
                if not isinstance(command, str) or not command.strip():
                    continue
                found.append(
                    HookRegistration(event=str(event), matcher=matcher, command=command, source=source)
                )
    return found, None


def representative_tool(matcher: str) -> str | None:
    """One real tool name this matcher would actually fire on, or None.

    Picks the first write tool, else the first shell tool, else the first
    delegation tool named in the matcher - whichever the registration's own
    intent is, a harmless call on that tool is the payload that resolves to
    the documented allow/no-op this task asks for, rather than to a decision
    the registration was never meant to make.
    """
    tokens = [token.strip() for token in (matcher or "").split("|") if token.strip()]
    for tool in WRITE_TOOLS:
        if tool in tokens:
            return tool
    for tool in SHELL_TOOLS:
        if tool in tokens:
            return tool
    for tool in DELEGATION_TOOLS:
        if tool in tokens:
            return tool
    return None


def probe_payload(registration: HookRegistration, temp_project: Path) -> dict[str, Any]:
    """One harmless, well-formed payload for this registration.

    Shaped from ``hooks/keel_adapter_claude.py``'s own contract: ``cwd`` and
    ``session_id`` are read by every subcommand, ``hook_event_name`` decides
    the kind for everything but a tool call, and ``tool_name``/``tool_input``
    decide a tool call's kind. Every field here resolves to allow or no-op in
    an UNADOPTED project - never to a write, a command execution, or a real
    delegation - because nothing this payload names is ever actually carried
    out; the hooks it reaches only ever decide whether the harness's own
    permission flow may proceed.
    """
    payload: dict[str, Any] = {
        "session_id": PROBE_SESSION_ID,
        "cwd": str(temp_project),
        "hook_event_name": registration.event,
    }
    if registration.event in NO_TOOL_EVENTS:
        if registration.event == "SubagentStop":
            payload["agent_id"] = "keel-doctor-probe-agent"
            payload["agent_type"] = "keel-doctor-probe"
        elif registration.event == "SessionEnd":
            payload["reason"] = "other"
        return payload
    tool = representative_tool(registration.matcher)
    if tool is None:
        return payload
    payload["tool_name"] = tool
    if tool in WRITE_TOOLS:
        payload["tool_input"] = {
            "file_path": str(temp_project / "keel-doctor-probe.txt"),
            "content": "keel doctor probe\n",
        }
    elif tool in SHELL_TOOLS:
        payload["tool_input"] = {"command": "echo keel-doctor-probe"}
    else:
        payload["tool_input"] = {"subagent_type": "keel-doctor-probe", "prompt": "keel doctor probe"}
    return payload


def probe_registration(
    registration: HookRegistration,
    plugin_root: Path,
    bash: str | None,
) -> ProbeResult:
    """Launch one registration synthetically; never touches a real project.

    ``bash`` is the resolved interpreter path (:func:`harness_bash`, passed
    in rather than re-resolved so every probe in one run agrees on it) -
    absent, this returns :data:`STATE_SKIPPED` rather than guessing at a
    launch that never happened (convention 7; the T185 rule restated: a
    probe that cannot be zero-trace is skipped, never faked healthy).
    """
    if not bash:
        return ProbeResult(
            registration,
            STATE_SKIPPED,
            "no 'bash' found on PATH - a zero-trace synthetic launch could "
            "not be attempted for this hook, so it is reported skipped "
            "rather than assumed healthy",
        )
    try:
        temp_dir = tempfile.mkdtemp(prefix="keel-doctor-")
    except OSError as exc:
        return ProbeResult(
            registration, STATE_UNREADABLE, f"could not create a throwaway project: {exc}"
        )
    try:
        temp_project = Path(temp_dir)
        payload = probe_payload(registration, temp_project)
        env = dict(os.environ)
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
        env["CLAUDE_PROJECT_DIR"] = str(temp_project)
        try:
            result = subprocess.run(
                [bash, "-c", registration.command],
                input=json.dumps(payload).encode("utf-8"),
                capture_output=True,
                cwd=str(temp_project),
                env=env,
                timeout=PROBE_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProbeResult(
                registration, STATE_BROKEN, f"timed out after {PROBE_TIMEOUT_SECONDS:.0f}s"
            )
        except OSError as exc:
            return ProbeResult(
                registration, STATE_UNREADABLE, f"could not launch: {type(exc).__name__}: {exc}"
            )
        trace = [entry.name for entry in temp_project.iterdir()]
        if trace:
            return ProbeResult(
                registration,
                STATE_BROKEN,
                "the probe left a trace in its own throwaway project "
                f"({', '.join(sorted(trace)[:5])}) - a synthetic launch must be "
                "zero-trace, so this hook is reported broken rather than healthy",
                result.returncode,
            )
        stderr = result.stderr.decode("utf-8", errors="replace")
        stdout = result.stdout.decode("utf-8", errors="replace")
        if NO_PYTHON_MARKER in stderr.casefold():
            return ProbeResult(
                registration,
                STATE_DEGRADED,
                "the hook's own launcher found no working Python 3.10+: "
                f"{stderr.strip()[:300]}",
                result.returncode,
            )
        if result.returncode == 0:
            return ProbeResult(
                registration,
                STATE_HEALTHY,
                "launched and returned the documented allow/no-op exit (0)",
                0,
            )
        return ProbeResult(
            registration,
            STATE_BROKEN,
            f"exit {result.returncode} (documented allow/no-op is 0) - "
            f"stdout={stdout.strip()[:200]!r} stderr={stderr.strip()[:200]!r}",
            result.returncode,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def probe_all(
    registrations: list[HookRegistration],
    plugin_root: Path | None = None,
    bash: str | None = None,
) -> list[ProbeResult]:
    """Every registration, probed once. ``bash`` resolved once for all of them.

    When the caller does not name a ``bash``, it is resolved through
    :func:`harness_bash` - the harness's own launcher, not the first ``bash``
    on ``PATH`` (BL29) - and, before any registration is probed, proven
    usable with :func:`bash_is_usable`. An interpreter that resolves but
    cannot even run ``echo`` (BL29's own symptom: WSL's launcher exists, is
    found, and still cannot run anything) answers EVERY probe with the
    existing :data:`STATE_SKIPPED` state, never a sixth state and never
    ``broken`` - a probe cannot call a registration broken by launching an
    interpreter that never ran the registration's command at all. The
    detail names the launcher path and its stderr and says plainly that the
    registrations were NOT MEASURED.
    """
    plugin_root = _REPO_ROOT if plugin_root is None else Path(plugin_root)
    bash_note = ""
    if bash is None:
        bash, bash_note = harness_bash()
    if bash is not None:
        usable, usable_detail = bash_is_usable(bash)
        if not usable:
            detail = (
                f"the resolved bash ({redact(bash)}) could not run a trivial command, so "
                "these registrations were NOT MEASURED - neither healthy nor broken: "
                f"{usable_detail}"
            )
            return [ProbeResult(r, STATE_SKIPPED, detail) for r in registrations]
    return [probe_registration(r, plugin_root, bash) for r in registrations]


# --------------------------------------------- known-broken-pattern scan

#: A script-like path token: anything not whitespace or a quote character,  # keel-leak: ignore - prose describing a token shape, not a token
#: ending in one of these extensions.
_SCRIPT_TOKEN_RE = re.compile(r"""([^\s"']+\.(?:py|ps1|sh|bash|js|cjs|mjs))""", re.IGNORECASE)

#: A Windows drive-letter absolute path: ``C:\`` or ``C:/``.
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:[\\/]")

#: ``$CLAUDE_PROJECT_DIR`` or ``%CLAUDE_PROJECT_DIR%``, either shell's spelling.
_PROJECT_DIR_VAR_RE = re.compile(r"\$\{?CLAUDE_PROJECT_DIR\}?|%CLAUDE_PROJECT_DIR%", re.IGNORECASE)

#: Substrings whose presence in a command is read as SOME failure handling
#: around the launched program, however crude - never a proof of correctness,
#: only a reason not to flag it. Deliberately permissive: this scan reports,
#: it does not block, and a false negative here costs a missed finding while
#: a false positive costs a false alarm the reader can dismiss on sight.
_FAILURE_WRAPPER_MARKERS: tuple[str, ...] = ("||", "trap ", "try:", "try{", "except")

#: Events this scan treats as gates - the two R30 already calls out as able
#: to stop work, which is exactly why a crash impersonating their verdict is
#: worth flagging.
_GATE_EVENTS: frozenset[str] = frozenset({"Stop", "PreToolUse"})


def _is_rooted_path(token: str) -> bool:
    """True when ``token`` is absolute or resolved through a shell variable.

    A leading ``$`` covers both ``$VAR/...`` and ``${VAR}/...`` - either
    shape is resolved by the shell before the path is ever a relative
    lookup against the session's cwd, which is the failure mode this check
    exists to catch (a predecessor doctor's "RELATIVE paths" pattern).
    """
    return (
        token.startswith("/")
        or token.startswith("~")
        or token.startswith("$")
        or bool(_DRIVE_LETTER_RE.match(token))
    )


def scan_command_patterns(where: str, event: str, command: str) -> list[str]:
    """Known-broken patterns in one hook command string. Reports, never blocks."""
    findings: list[str] = []
    if _PROJECT_DIR_VAR_RE.search(command):
        findings.append(
            f"{where}: command references a project-dir variable "
            f"($CLAUDE_PROJECT_DIR / %CLAUDE_PROJECT_DIR%) that a Windows shell "
            f"will not expand: {redact(command[:120])}"
        )
    for token in _SCRIPT_TOKEN_RE.findall(command):
        if not _is_rooted_path(token):
            findings.append(
                f"{where}: relative script path {token!r} - resolves against the "
                f"session shell's PERSISTED cwd, which moves with every 'cd'; use "
                f"an absolute path or a shell-variable-rooted one"
            )
    if event in _GATE_EVENTS and not any(marker in command for marker in _FAILURE_WRAPPER_MARKERS):
        findings.append(
            f"{where}: a {event} gate command with no visible failure wrapper "
            f"(none of {', '.join(repr(m) for m in _FAILURE_WRAPPER_MARKERS)} present) "
            f"- a crash exiting non-zero here can be read by the harness as a "
            f"block/continue decision rather than as a launch failure"
        )
    return findings


def scan_settings_document(label: str, path: Path, document: Any) -> list[str]:
    """Every known-broken pattern in one settings document's hook entries."""
    findings: list[str] = []
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return findings
    for event, groups in hooks.items():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            entries = group.get("hooks")
            entries = entries if isinstance(entries, list) else []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                where = f"{label} ({redact(str(path))}), {event} entry"
                if "args" in entry:
                    findings.append(
                        f"{where}: uses an 'args' array - Claude Code's settings "
                        f"rewriter drops unknown fields and silently kills this "
                        f"hook (observed pattern); fold the arguments into one "
                        f"'command' string"
                    )
                command = entry.get("command")
                if isinstance(command, str) and command.strip():
                    findings.extend(scan_command_patterns(where, str(event), command))
    return findings


def settings_sources(project: Path, home: Path | None = None) -> list[tuple[str, Path]]:
    """The settings files R30's own source list names, labelled for the reader."""
    home = Path.home() if home is None else Path(home)
    return [
        ("user-global settings", home / ".claude" / "settings.json"),
        ("project settings", Path(project) / ".claude" / "settings.json"),
        ("project local settings", Path(project) / ".claude" / "settings.local.json"),
    ]


def known_broken_pattern_scan(
    project: Path, home: Path | None = None
) -> tuple[list[str], list[str]]:
    """Every known-broken-pattern finding across the settings files keel can
    see, plus a note per source it could not read.

    Returns ``(findings, notes)``. FAIL-OPEN per source: a settings file that
    is absent (the ordinary state on most machines) or unreadable adds a note
    rather than aborting the scan of the sources that ARE readable.
    """
    findings: list[str] = []
    notes: list[str] = []
    for label, path in settings_sources(project, home):
        document, error = _read_json(path)
        if error:
            notes.append(error)
            continue
        if document is None:
            continue
        findings.extend(scan_settings_document(label, path, document))
    return findings, notes


# ------------------------------------------- keel's own failures, as numbers


def surveyed_project(argument: str | None) -> Path:
    """The project to scan: the survey's own answer, or the same rule inline.

    THE FALLBACK IS A DUPLICATE ON PURPOSE, and on the same terms as
    ``keel_hook._KEEL_GATE_OFF_VALUES``: ``keel_survey.project_root`` is the
    authority and is asked first, but this module has to be able to run when
    that module is the thing that did not import (see the guard above), and a
    diagnostic that cannot resolve a directory reports nothing at all. The rule
    is three lines and is kept identical to the one it mirrors.
    """
    if keel_survey is not None:
        try:
            return keel_survey.project_root(argument)
        except Exception:  # noqa: BLE001 - fall through to the inline rule
            pass
    if argument and argument.strip():
        return Path(argument)
    env = os.environ.get("CLAUDE_PROJECT_DIR", "")
    return Path(env) if env.strip() else Path(os.getcwd())


def version_fingerprint() -> dict[str, Any]:
    """The installation's version fingerprint, or an honest absence.

    ``note`` is empty when the survey answered. When it is not, every other
    field reads as unknown rather than as a clean zero: a version line that
    said "(none)" without saying why would report a broken installation as an
    unversioned one (convention 7).
    """
    if keel_survey is None:
        return {
            "plugin": None,
            "changelog_top": None,
            "agrees": False,
            "components": None,
            "note": f"the survey module could not be imported: {_SURVEY_FAULT}",
        }
    try:
        report = keel_survey.version_report()
        return {
            "plugin": report["plugin"],
            "changelog_top": report["changelog_top"],
            "agrees": report["agrees"],
            "components": report["components"],
            "note": "",
        }
    except Exception as exc:  # noqa: BLE001 - unreadable is its own answer
        return {
            "plugin": None,
            "changelog_top": None,
            "agrees": False,
            "components": None,
            "note": f"the version fingerprint could not be read: {type(exc).__name__}: {exc}",
        }


# Every state ``keel_survey.install_report`` can return - enumerated from that
# function's own ``report["state"] = ...`` assignments rather than from memory
# - and what each one means to the single question this doctor asks: does the
# harness's record of which tree it installed agree with the tree this process
# is actually running from?
#
# READ AS AN ALLOWLIST, and that is the whole point of the table. The first
# version of this check named the one divergent state it happened to have in
# hand ("unreadable") and let every other state fall through to agreement, so
# "unrecorded-root" - the record naming this installation at a tree that is
# NOT this one, the exact defect this check exists to catch - scored green.
# A table consulted default-deny (:data:`INSTALL_UNESTABLISHED` for anything
# absent from it) inverts that failure direction: a state added to
# ``install_report`` tomorrow and forgotten here scores 1 and says it was not
# recognised, instead of scoring 0 and saying nothing at all.
INSTALL_AGREES = "agrees"
INSTALL_DIVERGES = "diverges"
INSTALL_UNESTABLISHED = "unestablished"
INSTALL_STATE_VERDICTS: dict[str, str] = {
    # The record names this installation, at this tree, and the tree is there.
    "agree": INSTALL_AGREES,
    # No record file exists at all. THE ADOPTER CASE, and ``install_report``'s
    # own line calls it "the normal state of a checkout": a machine whose
    # harness keeps no install record has made no claim about this tree, so
    # there is no claim for this tree to contradict. Scoring it 1 would light
    # this line red on every adopter's clone and teach them to ignore it,
    # which is the same silence by another route.
    "not-found": INSTALL_AGREES,
    # A record that reads and parses, and names no installation matching this
    # manifest among the plugins it does hold. The adopter case one layer in -
    # a checkout the harness never installed, or one installed under another
    # name - and again the record makes no claim about THIS tree.
    "no-entry": INSTALL_AGREES,
    # The record holds entries for this manifest and none of them is this
    # tree: a claim about this installation that this tree contradicts. The
    # divergence this check was built for, and the one it used to miss,
    # because ``install_report`` states it in ``state`` plus ``notes`` and
    # leaves ``findings`` empty - nothing but this table stops it reading as
    # agreement.
    "unrecorded-root": INSTALL_DIVERGES,
    # The record names this tree and something about it is wrong: a recorded
    # installPath that is not on disk, an orphaned tree, two trees claiming
    # one version. Those ``install_report`` does state in ``findings``.
    "disagree": INSTALL_DIVERGES,
    # A record EXISTS and keel could not read it (I/O or JSON error). Not the
    # adopter case: absence is "not-found" above, and this is presence plus
    # failure. Could-not-be-established scores exactly like a divergence,
    # because "could not check" is never read as "healthy".
    "unreadable": INSTALL_UNESTABLISHED,
    # A record exists, parses as JSON, and carries no 'plugins' table.
    # Deliberately the same class as "unreadable" and NOT the same class as
    # "not-found", which is the one judgement call in this table: the file is
    # there, so a claim about this tree may well be in it, and keel cannot see
    # the shape well enough to check. An adopter with no record hits
    # "not-found"; reaching here means the harness's own file is in a shape
    # this keel does not know, which is a thing to say out loud.
    "malformed": INSTALL_UNESTABLISHED,
}


def classify_install_report(report: dict[str, Any]) -> dict[str, Any]:
    """One ``keel_survey.install_report`` result, scored against
    :data:`INSTALL_STATE_VERDICTS` into the two-key shape ``exit_code`` and
    ``render`` already read: ``findings`` for a divergence that WAS read,
    ``note`` for one that could not be established. Both score 1; only an
    empty pair scores 0.

    Split out of ``install_divergence_report`` so the mapping can be pinned
    state by state against a hand-built report, with no second tree on disk
    and no harness record to stage - the states that most need pinning are
    exactly the ones that are awkward to produce for real.

    FINDINGS FIRST, whatever the state says: ``install_report`` reads the
    running tree's ``.orphaned_at``/``.in_use`` markers BEFORE it reads the
    record, and returns early on the quiet states, so an orphaned tree on a
    machine with no record at all arrives here as "not-found" CARRYING a
    finding. A stated finding is the stronger evidence in any such pair, so it
    decides, and an agreeing state can never swallow one.
    """
    findings = [str(finding) for finding in (report.get("findings") or [])]
    if findings:
        return {"findings": findings, "note": ""}
    state = str(report.get("state") or "")
    verdict = INSTALL_STATE_VERDICTS.get(state, INSTALL_UNESTABLISHED)
    if verdict == INSTALL_AGREES:
        return {"findings": [], "note": ""}
    detail = " - ".join(
        part
        for part in [str(report.get("line") or "").strip()]
        + [str(note).strip() for note in (report.get("notes") or [])]
        if part
    )
    if verdict == INSTALL_DIVERGES:
        return {
            "findings": [
                f"the harness's install record does not agree with the tree "
                f"this doctor runs from (state '{state}'): "
                f"{detail or 'no detail given'}"
            ],
            "note": "",
        }
    if state in INSTALL_STATE_VERDICTS:
        return {
            "findings": [],
            "note": (
                f"the harness's install record could not be read, so its "
                f"agreement with this tree could not be established "
                f"(state '{state}'): {detail or 'no detail given'}"
            ),
        }
    return {
        "findings": [],
        "note": (
            f"keel_survey reported install state '{state}', which this doctor "
            f"does not recognise, so its agreement with this tree could not be "
            f"established"
            + (f": {detail}" if detail else "")
            + " - scored as unchecked rather than as healthy, which is the only "
            "thing an unknown state can safely mean"
        ),
    }


def install_divergence_report(home: Path | None = None) -> dict[str, Any]:
    """The tree the harness has recorded as installed, against the tree this
    doctor runs from - ``keel_survey.install_report`` (T168), read the other
    half of the same fingerprint ``version_fingerprint`` above already reads.

    Measured on this machine: a real divergence had been scoring green for a
    month, because nothing between ``install_report`` and ``exit_code`` ever
    carried its finding. This function is that missing carry, modeled on
    ``version_fingerprint`` line for line and for the same reason -
    THE PROPERTY AT RISK IS SILENCE, NOT CORRECTNESS.

    The carry is a CLASSIFICATION rather than a forward: ``install_report``
    states some of its divergences in ``findings`` and others in ``state``
    alone, so passing ``findings`` through loses precisely the divergences
    whose findings list is empty. ``classify_install_report`` above holds that
    mapping, default-deny; this function is the I/O around it, wearing the
    exception guard every other diagnostic in this file wears, so that a crash
    in one check cannot take the rest of the report down with it - and, like
    every one of them, turning its own failure into a stated ``note`` rather
    than a quiet ``findings: []``.
    """
    if keel_survey is None:
        return {
            "findings": [],
            "note": f"the survey module could not be imported: {_SURVEY_FAULT}",
        }
    try:
        version = keel_survey.version_report()
        report = keel_survey.install_report(
            home=home,
            manifest_name=version.get("manifest_name", ""),
            version=version.get("plugin", ""),
        )
        return classify_install_report(report)
    except Exception as exc:  # noqa: BLE001 - unreadable is its own answer
        return {
            "findings": [],
            "note": f"the install divergence report could not be read: {type(exc).__name__}: {exc}",
        }


def hook_error_report(home: Path | None = None) -> dict[str, Any]:
    """The user-global hook-error log's state, from the module that owns it.

    A THIN PASS-THROUGH of ``keel_faultlog.state`` (R15): that function already
    answers the three states this surface has to report - ``absent``,
    ``present``, ``unreadable`` - and re-deriving them here from a ``stat()``
    would let the doctor and the session-start warning disagree about the same
    file. ``home`` is the seam ``build_report`` already threads for the
    settings scan, so a test owns the premise and production reads the real
    home. Never raises: ``state`` does not, by its own contract.
    """
    return keel_faultlog.state(home)


def crash_deny_report(project: Path) -> dict[str, Any]:
    """Crash-denies in this project's audit log, counted BY SESSION.

    Clause 5 of the crash ruling in one number, or rather in three: a crash
    class is only eliminated if repeated crashes are VISIBLE, and one crash
    line looks the same as forty until somebody counts them. Grouped by session
    because that is the unit a reader acts on - forty crash-denies spread over
    forty sessions is a chronic defect, and forty in one session is one bad
    edit that froze one turn.

    THE THREE KINDS ARE NOT SUMMED AWAY (see :data:`CRASH_DENY_KINDS`); the
    total is reported beside them, never instead of them.

    ``log`` is the redacted audit path, and ``note`` says why a count is zero
    when the reason is not "no crashes": an absent log and an unreadable one
    are different facts, and reporting the second as zero crashes would be the
    swallowed error this project has a knowledge record about. Never raises -
    a diagnostic that dies on a corrupt log is worse than the log.
    """
    answer: dict[str, Any] = {
        "log": None,
        "note": "",
        "total": 0,
        "by_kind": {kind: 0 for kind in CRASH_DENY_KINDS},
        "by_session": {},
    }
    try:
        path = keel_events.audit_path(Path(project))
        answer["log"] = redact(str(path))
        if not path.is_file():
            answer["note"] = "this project has no audit log, so nothing has been recorded yet"
            return answer
        lines = keel_events.read_audit(Path(project))
    except Exception as exc:  # noqa: BLE001 - unreadable is its own answer
        answer["note"] = f"the audit log could not be read: {type(exc).__name__}: {exc}"
        return answer
    for line in lines:
        try:
            if line.get("event") == CRASH_DENY_EVENT:
                kind = CRASH_DENY_EVENT
            elif line.get("gate") in CRASH_DENY_GATES:
                kind = str(line.get("gate"))
            else:
                continue
            session = line.get("session") or CRASH_DENY_NO_SESSION
            group = answer["by_session"].setdefault(
                str(session), {name: 0 for name in CRASH_DENY_KINDS}
            )
            group[kind] += 1
            answer["by_kind"][kind] += 1
            answer["total"] += 1
        except Exception:  # noqa: BLE001 - one unreadable line costs that line only
            continue
    if not answer["total"] and not answer["note"]:
        answer["note"] = "no crash-deny has ever been recorded in this project"
    return answer


# --------------------------------------------------------------- the report


def build_report(project: Path, home: Path | None = None) -> dict[str, Any]:
    """The whole doctor report as a plain dictionary; also the ``--json`` payload."""
    registrations, fatal = read_hook_registrations(_REPO_ROOT)
    # Resolved ONCE here, rather than left to ``probe_all``'s own default, so
    # the report can say which bash it chose and why (BL29) without
    # resolving it a second time.
    bash, bash_note = harness_bash()
    probes = [] if fatal else probe_all(registrations, bash=bash)
    findings, notes = known_broken_pattern_scan(project, home)
    version = version_fingerprint()
    summary = {state: 0 for state in PROBE_STATES}
    for probe in probes:
        summary[probe.state] += 1
    return {
        "project": redact(str(Path(project).resolve())),
        "hooks_json_error": fatal,
        "registrations_found": len(registrations),
        "probes": [p.to_dict() for p in probes],
        "probe_summary": summary,
        "bash": {"path": redact(bash) if bash else None, "note": bash_note},
        "pattern_findings": findings,
        "pattern_notes": notes,
        # T235/T236, clause 5 of the crash ruling: keel's own failures as
        # numbers. REPORTED, NOT SCORED - deliberately absent from
        # ``exit_code``: these are a HISTORY (a crash last month is still in the
        # log, and the repair is a human act under clause 4), while every other
        # thing this report scores is a state of the installation right now. A
        # doctor that exited 1 forever after one crash would train its reader to
        # ignore the exit code, which is the only thing here a script reads.
        "hook_errors": hook_error_report(home),
        "crash_denies": crash_deny_report(project),
        "version": {
            "plugin": version["plugin"],
            "changelog_top": version["changelog_top"],
            "agrees": version["agrees"],
            "components": version["components"],
            # Empty when the fingerprint was read. When it is not, it says why,
            # so a broken installation never reads as an unversioned one.
            "note": version["note"],
        },
        # T168's other half, finally reaching this report: the tree the
        # harness recorded, against the tree this doctor runs from. Same
        # ``home`` seam as the settings scan above, so a test owns the same
        # premise for both.
        "install": install_divergence_report(home),
    }


def render(report: dict[str, Any]) -> str:
    """The full human-readable report."""
    out: list[str] = []
    write = out.append
    write("=" * 72)
    write(f"KEEL DOCTOR - {report['project']}")
    write("=" * 72)
    version = report["version"]
    agreement = "agree" if version["agrees"] else "DISAGREE"
    write(
        f"version : plugin {version['plugin'] or '(none)'} | changelog top "
        f"{version['changelog_top'] or '(none)'} ({agreement}) | components "
        f"{version['components']}"
    )
    # ``.get`` for the same reason every new key below uses it: a report built
    # by an older keel, or by a caller's own fixture, is still a report.
    if version.get("note"):
        write(f"          NOT READ: {version['note']}")
    # ``.get`` for the reason every key below it uses the same call: a report
    # from an older keel, or a test's hand-built fixture, has no "install" key
    # at all, and that must print nothing rather than raise.
    install = report.get("install")
    if install:
        if install.get("findings"):
            write("install : DISAGREE - the installed tree differs from this one")
            for finding in install["findings"]:
                write(f"          FINDING {finding}")
        elif install.get("note"):
            # NOT a divergence: "note" is what `classify_install_report` fills
            # for "unreadable", "malformed", and any state it does not
            # recognise - none of which ever compared this tree to the
            # record. Saying DISAGREE here would assert a divergence nobody
            # established; say only what is true, and let the NOT READ line
            # below carry why.
            write("install : UNKNOWN - the installed tree's agreement with this one could not be established")
            write(f"          NOT READ: {install['note']}")
        else:
            write("install : agrees - the installed tree is this one")
    bash_info = report.get("bash")
    if bash_info:
        write(f"bash    : {bash_info.get('path') or '(none resolved)'} - {bash_info.get('note', '')}")
    write("")
    if report["hooks_json_error"]:
        write(f"REGISTRATIONS: could not be read - {report['hooks_json_error']}")
        write("(nothing could be probed; see exit code 2)")
        return "\n".join(out)
    write(f"SYNTHETIC LAUNCHES (zero-trace) - {report['registrations_found']} registration(s)")
    for probe in report["probes"]:
        write(
            f"  {probe['state']:<11} {probe['event']:<12} {probe['matcher'] or '(any tool)'} "
            f"-> {probe['command']}"
        )
        write(f"              {probe['detail']}")
    summary = report["probe_summary"]
    write(
        "  summary: "
        + ", ".join(f"{summary[state]} {state}" for state in PROBE_STATES)
    )
    write("")
    write("KNOWN-BROKEN-PATTERN SCAN (reports, never blocks)")
    if report["pattern_findings"]:
        for finding in report["pattern_findings"]:
            write(f"  FINDING {finding}")
    elif not report["pattern_notes"]:
        write("  none found across the settings files this scan can see")
    else:
        write("  no findings from the sources that could be read")
    for note in report["pattern_notes"]:
        write(f"  UNREADABLE SOURCE (not scanned; counted against the exit code) {note}")
    # EVERY KEY BELOW IS READ WITH ``.get``, and that is a contract with the
    # callers this function already has: ``exit_code``'s own fixtures build
    # minimal report dictionaries by hand, and a report shape from an older
    # keel is still a report. A section whose key is absent prints nothing at
    # all rather than raising - the one thing a diagnostic may never do.
    errors = report.get("hook_errors")
    if errors:
        write("")
        write("KEEL'S OWN HOOK ERRORS (user-global log; reported, not scored)")
        write(f"  {str(errors.get('state', 'unknown')):<11} {errors.get('detail', '')}")
        write(f"              log: {errors.get('path') or '(no location resolves)'}")
    crashes = report.get("crash_denies")
    if crashes:
        write("")
        write("CRASH-DENIES IN THIS PROJECT'S AUDIT LOG (reported, not scored)")
        by_kind = crashes.get("by_kind") or {}
        write(
            f"  total {crashes.get('total', 0)}: "
            + ", ".join(f"{by_kind.get(kind, 0)} {kind}" for kind in CRASH_DENY_KINDS)
        )
        for session, counts in (crashes.get("by_session") or {}).items():
            write(
                f"    {session}: "
                + ", ".join(
                    f"{(counts or {}).get(kind, 0)} {kind}"
                    for kind in CRASH_DENY_KINDS
                    if (counts or {}).get(kind, 0)
                )
            )
        if crashes.get("note"):
            write(f"  {crashes['note']}")
        write(f"  log: {crashes.get('log') or '(no location resolves)'}")
    write("")
    write("(read-only report; no probe wrote to any project's .keel/.)")
    return "\n".join(out)


def exit_code(report: dict[str, Any]) -> int:
    """0 healthy, 1 findings (including any state that is not proven healthy,
    and including a settings source ``pattern_notes`` records as unreadable,
    and including the installed tree disagreeing with this one), 2 could not
    run.

    A non-empty ``pattern_notes`` counts exactly like an unestablished probe
    state (:data:`STATE_UNREADABLE`, :data:`STATE_DEGRADED`,
    :data:`STATE_SKIPPED`): "could not check" is never read as "healthy". It
    is read via ``.get`` because older report shapes (and this module's own
    ``TestExitCodes`` fixtures) may omit the key entirely rather than set it
    to ``[]``; both spellings of "no notes" must agree.

    ``install`` follows the identical rule (T500): a non-empty ``findings``
    is a real divergence, and a non-empty ``note`` is an install report that
    could not be read - and an unread report scores exactly like a
    divergence it DID read, never like agreement. Read via ``.get`` for the
    same reason as ``pattern_notes``: a report with no "install" key at all
    (an older keel's, or a hand-built fixture) must not raise, and must not be
    scored as a divergence it never checked for - it agrees by omission, the
    same way ``pattern_findings``/``pattern_notes`` already do above.
    """
    if report["hooks_json_error"]:
        return 2
    summary = report["probe_summary"]
    all_healthy = summary[STATE_HEALTHY] == report["registrations_found"]
    install = report.get("install") or {}
    install_agrees = not install.get("findings") and not install.get("note")
    if (
        all_healthy
        and not report["pattern_findings"]
        and not report.get("pattern_notes")
        and install_agrees
    ):
        return 0
    return 1


def main(argv: list[str] | None = None) -> int:
    """synthetic hook launches and known-broken-pattern scan (T225)"""
    parser = argparse.ArgumentParser(
        prog="keel doctor", description="synthetic hook launches and known-broken-pattern scan"
    )
    parser.add_argument("--project", default=None, help="project directory to scan settings for")
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    try:
        report = build_report(surveyed_project(args.project))
    except Exception as exc:  # noqa: BLE001 - a diagnostic must never crash unreported
        print(f"keel doctor: could not complete the report: {type(exc).__name__}: {exc}")
        return 2
    if args.as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
    else:
        print(render(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
