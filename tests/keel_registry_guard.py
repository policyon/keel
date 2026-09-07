#!/usr/bin/env python3
"""Shared guards: keep in-process ``keel_session.run()`` / ``keel_capture.run()``
calls - and ``keel_gate.run()`` since T231 - from reading or writing this
developer's REAL user-global keel state: the fleet registry (T227 / T185-class
review finding, 2026-08-21), the hook-error log (T238, 2026-08-21) and
everything else under the one ratified user-global directory.

Contract
--------
Reads   : ``hooks/keel_session.py`` (``registry_write``), to substitute it
          for the duration of one block.
Emits   : nothing; three context managers other test modules import (two of
          them one implementation - see ``no_real_hook_error_log``).
Writes  : nothing outside whatever the caller's own fixture already writes -
          ``no_real_fleet_registry``'s substituted ``registry_write`` is a
          pure no-op, and ``no_real_hook_error_log`` only ever writes inside
          its own throwaway ``HOME``/``USERPROFILE``.

Why this exists
----------------
``keel_session.run()`` calls ``registry_write(event.cwd)`` with no ``home``
argument whenever the event is ``session_start`` on an adopted project
(``.keel/`` present - ``keel_capture.project_is_adopted``), and
``registry_write`` in turn resolves the REAL ``Path.home()`` unless it is
stubbed: the ``env=`` mapping ``run`` otherwise threads through has no effect
on it. Any in-process test that adopts a temp project and calls ``run()``
directly must stub this, or every suite run leaves fixture debris in
``~/.claude/keel/keel-registry.json`` on the machine running the tests.

``keel_session.run()`` and ``keel_capture.run()`` share the SAME hazard for
``keel_faultlog.record``: it is called with no ``home`` argument from each
module's own catch-all, whenever a test deliberately breaks a helper so the
raise reaches that catch-all, and ``record`` resolves the REAL ``Path.home()``
unless ``HOME``/``USERPROFILE`` are overridden. Unlike ``registry_write``,
there is no module-level attribute a test can stub for this one - the import
inside each catch-all is local and guarded (T235's own contract) - so the
in-process fix is the environment-variable half of the SAME sandboxing
principle ``tests/test_keel_crash_deny_t236.py`` applies to its subprocess
launches, applied here to the test process itself for the duration of one
block, or every suite run leaves fixture debris in
``~/.claude/keel/keel-hook-errors.jsonl`` instead.

A SUBPROCESS launch of ``hooks/keel_hook.py session`` needs the other half of
the same discipline instead - ``HOME``/``USERPROFILE`` pointed at a sandbox in
the child's own environment - because there is no in-process attribute to
monkeypatch across a process boundary for ``registry_write``; every
subprocess-launching test file already owns its own ``clean_env`` for that.

Failure policy
--------------
N/A - a test-only helper, not production code.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterator

_HOOKS_DIR = str(Path(__file__).resolve().parent.parent / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

import keel_gate  # noqa: E402
import keel_session  # noqa: E402


def _forget_memoised_home() -> None:
    """Drop ``keel_gate``'s memo of this user's home directory.

    ``keel_gate._walk_home`` memoises, deliberately and for a good reason: a
    hook process serves ONE tool call and resolving a home costs a syscall per
    component. A TEST process serves thousands and moves the home under itself,
    so the memo has to be dropped on both edges of a sandbox - on the way in,
    or the sandboxed block reads the real home; on the way out, or every LATER
    case in the same process reads a temporary directory that no longer exists
    as this machine's home. The second direction is not hypothetical: it made
    ``test_keel_target_arming_t178``'s home-is-a-ceiling case pass or fail
    purely on which test file ran first.

    It pokes a private name on purpose, and that is the honest shape: the memo
    is an internal optimisation, and a test helper that faked its own way
    around it would be asserting against a different resolver than the one
    production uses.
    """
    keel_gate._WALK_HOME_MEMO[0] = (False, None)


@contextlib.contextmanager
def no_real_fleet_registry() -> Iterator[None]:
    """Substitute a no-op for ``keel_session.registry_write`` for one block.

    Restores the original on the way out, exception or not, so one test's
    stub can never leak into the next.
    """
    original = keel_session.registry_write
    keel_session.registry_write = lambda cwd, home=None: None
    try:
        yield
    finally:
        keel_session.registry_write = original


@contextlib.contextmanager
def no_real_hook_error_log() -> Iterator[Path]:
    """``sandboxed_user_global_home`` under the name its first callers know.

    Kept as its own name because that is what the hook-error-log cases read
    like at their call sites ("this block must not touch the real log"), and
    because renaming a guard in place is how a guard gets dropped from a file
    by a merge. One implementation, two honest names.
    """
    with sandboxed_user_global_home() as home:
        yield home


@contextlib.contextmanager
def sandboxed_user_global_home() -> Iterator[Path]:
    """Point ``HOME``/``USERPROFILE`` at a throwaway directory for one block.

    THE WHOLE USER-GLOBAL SURFACE, not one file of it: every keel module that
    resolves ``~/.claude/keel/`` does so through ``Path.home()``
    (``keel_faultlog.user_global_dir``, and ``keel_registry`` and
    ``keel_compaction`` through it), so this one substitution keeps the
    hook-error log, the fleet registry, the prompt logs and the compaction
    ledger of the machine running the tests out of reach at once. T231's gate
    rule reads the same resolver to decide what it protects, which is why its
    cases use this guard rather than a home of their own: a test that invented
    a second way to fake the home directory could pass while the production
    resolver looked somewhere else entirely.

    Restores both variables on the way out, exception or not - present ones to
    their previous value, absent ones to absent - and drops the memoised home
    on BOTH edges (see ``_forget_memoised_home``), so one test's sandbox can
    never leak into the next in either direction. Yields the throwaway
    directory, for a case that wants to assert on what did or did not land
    inside it.
    """
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        previous_home = os.environ.get("HOME")
        previous_userprofile = os.environ.get("USERPROFILE")
        os.environ["HOME"] = str(home)
        os.environ["USERPROFILE"] = str(home)
        _forget_memoised_home()
        try:
            yield home
        finally:
            if previous_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = previous_home
            if previous_userprofile is None:
                os.environ.pop("USERPROFILE", None)
            else:
                os.environ["USERPROFILE"] = previous_userprofile
            _forget_memoised_home()
