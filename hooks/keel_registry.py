#!/usr/bin/env python3
"""keel's fleet registry - one user-global file naming every adopted project
this machine has seen (T227).

Contract
--------
Reads   : this user's home directory - through ``keel_faultlog.user_global_dir``,
          the SAME resolver every other user-global keel file uses (R15's
          one-parser rule; see
          ``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md``)
          - to find the registry itself, and, on every ``write()``, the
          predecessor system's own cross-project registry
          (``~/orchestrated-projects.txt``), read as a ONE-TIME SEED and
          folded into keel's own file rather than kept as a standing
          dependency. A seed line is kept only when it is BOTH still a
          directory on disk AND carries keel's own arming file
          (``.keel/keel-policy.md``) - the stricter test T227 clause 2 names,
          separate from the plain adoption test ``write`` applies to ``cwd``
          itself, because a predecessor entry may name a project this
          installation never armed at all.
Emits   : ``read()`` returns every registered path that still exists on disk,
          as expanded ``Path`` objects - never the collapsed text a reader
          would have to un-substitute for itself. ``write()`` returns a small
          stats mapping (``written``, ``pruned``, ``seeded``, ``total``) for a
          caller that wants to report on it; ``hooks/keel_session.py`` does
          not, by its own guarded contract.
Writes  : ``~/.claude/keel/keel-registry.json`` - a JSON snapshot, REWRITTEN
          WHOLE on every call to ``write()``, never appended to. A registry is
          the SET of what is currently adopted, and pruning a vanished project
          means removing it from the file, which an append-only log cannot do
          (unlike ``keel_faultlog``'s hook-error log, which is genuinely an
          append-only history and stays that way). Each path is passed through
          ``keel_redact.redact`` before it is serialised (convention 5) -
          collapsing THIS user's own home prefix to ``~``, which loses nothing:
          the file never leaves this machine (never tracked, never pushed, per
          the ratified location decision), so ``~`` still names the real path
          here, and ``read()`` expands it straight back with
          ``Path.expanduser()``. A path outside the home directory is stored
          literally, unchanged - it never matched the home pattern in the
          first place.
Argv    : none. Library module, imported LAZILY: by ``hooks/keel_session.py``
          (the writer, guarded there so a fault here costs one stderr line and
          nothing else) and by ``scripts/keel_orchestration_dashboard.py``
          (the reader, through its ``read_siblings``).

Exit codes
----------
None of its own; library module.

Failure policy
--------------
FAIL-OPEN AND NEVER RAISES, from either ``write()`` or ``read()``: a fleet
registry that cannot be read or written must cost the session that triggered
it, and the board that displays it, nothing. Every fault is one stderr line
(convention 7) - "the registry could not be updated", never silence - and a
partial or unreadable file degrades to "no siblings" rather than an exception.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No shell, no network, no
subprocess. Every file operation states its encoding explicitly (convention 6).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_faultlog import user_global_dir  # noqa: E402
from keel_redact import redact  # noqa: E402

#: The registry's filename, under the ratified user-global directory.
REGISTRY_FILENAME = "keel-registry.json"

#: Schema version stamped on the registry document, versioned separately from
#: the audit and queue logs and from ``keel_faultlog``'s own schema - a
#: separate contract with separate readers (R15: neither may drift from the
#: other by accident).
REGISTRY_SCHEMA_VERSION = 1

#: The predecessor's own cross-project registry file, read once per ``write``
#: call as a SEED and never held onto afterward. Named as a segment rather
#: than spelled inline so a test can point ``home`` at a fixture without ever
#: touching a real file under this account's actual home directory.
PREDECESSOR_SEED_NAME = "orchestrated-projects.txt"

#: The arming file whose presence is what makes a SEEDED entry keel-adopted -
#: the stricter test T227 clause 2 names for predecessor entries, distinct
#: from the plain ``.keel/`` record walk ``write`` applies to ``cwd`` itself
#: (``keel_events.resolve_record_root``, imported where it is used).
_ARMING_RELPATH = (".keel", "keel-policy.md")


def registry_path(home: Path | None = None) -> Path | None:
    """``~/.claude/keel/keel-registry.json``, or None when home cannot be resolved.

    ``home`` is the seam ``keel_faultlog.user_global_dir`` already offers:
    a caller that must own the premise (a test) hands one down, production
    passes nothing and reads the real one.
    """
    directory = user_global_dir(home)
    return None if directory is None else directory / REGISTRY_FILENAME


def _seed_path(home: Path | None = None) -> Path | None:
    """The predecessor's own registry file, or None when home cannot be resolved.

    Directly under home, NOT under keel's own directory - it is the
    predecessor's file, in the predecessor's own location, read but never
    moved or deleted (T227 clause 2: a one-time import, never a standing
    dependency).
    """
    try:
        base = Path.home() if home is None else Path(home)
        return base / PREDECESSOR_SEED_NAME
    except Exception:  # noqa: BLE001 - no home is an answer, never an exception
        return None


def _is_keel_adopted(path: Path) -> bool:
    """True when ``path`` is a directory carrying keel's own arming file.

    Never raises: an unreadable filesystem entry is simply not adopted,
    exactly as a missing one is not.

    FLAT-ADOPTION EXEMPT (T602). ``path`` here is a line the PREDECESSOR wrote
    into its own registry file - a project root somebody else already named,
    not a write target and not this session's cwd - so "does THIS EXACT
    DIRECTORY carry keel" is the whole question and walking up would answer a
    different one: it would import a parent nobody listed on the strength of a
    child that happens to sit under it. The test is also ARMING-keyed
    (``.keel/keel-policy.md``) rather than ``.keel/``-keyed, which is T227
    clause 2's deliberately stricter bar for a seeded entry, and the record
    walk is ``.keel/``-keyed by design - the two ask different questions.
    ``tests/test_keel_flat_adoption_sweep_t602.py`` pins this exemption.
    """
    try:
        return path.is_dir() and path.joinpath(*_ARMING_RELPATH).is_file()
    except OSError:
        return False


def _safe_is_dir(path: Path) -> bool:
    """``path.is_dir()``, never raising."""
    try:
        return path.is_dir()
    except OSError:
        return False


def _seed_candidates(home: Path | None = None) -> list[Path]:
    """Predecessor entries surviving both filters: on disk, and keel-adopted.

    Read fresh on every call rather than memoised - one write happens per
    session start, so re-reading costs one small text file and buys a seed
    that notices a project adopted (or removed) since the machine's last
    session. Never raises: an absent or unreadable predecessor file yields no
    candidates, the honest "nothing to seed" answer, never an exception a
    caller would have to guard against separately.

    FLAT-ADOPTION EXEMPT (T602), one level out: the flat test is
    ``_is_keel_adopted`` below, which carries the reason. Each line here is a
    project root the PREDECESSOR named, so walking up from one would import a
    parent nobody listed. ``tests/test_keel_flat_adoption_sweep_t602.py`` pins
    this exemption.
    """
    path = _seed_path(home)
    if path is None or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    candidates: list[Path] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            # RESOLVED, not merely expanded: a predecessor file may itself
            # carry a Windows 8.3 short-form spelling (captured off a shell
            # exactly the way ``keel_redact``'s own module contract describes
            # this machine's temp directory being spelled), which is a
            # DIFFERENT string from - but the SAME directory as - the long
            # form ``write`` derives for ``cwd`` via ``Path.resolve()``.
            # Comparing unresolved strings would file the same project twice
            # under two spellings; resolving both sides once, here and in
            # ``write``, is what keeps the union in T227 clause 2 a genuine
            # set rather than a text match.
            candidate = Path(text).expanduser().resolve()
        except Exception:  # noqa: BLE001 - an unparseable line names no project
            continue
        if _is_keel_adopted(candidate):
            candidates.append(candidate)
    return candidates


def _load(path: Path) -> list[Path]:
    """Every path the registry currently holds, expanded. Never raises.

    An absent, empty or malformed file yields an empty list - the same
    "nothing recorded yet" answer a fresh machine gets, never an exception.
    """
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(document, dict):
        return []
    entries = document.get("projects")
    if not isinstance(entries, list):
        return []
    paths: list[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("path")
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            # RESOLVED, matching ``write``'s own ``cwd_resolved`` and
            # ``_seed_candidates`` - see the comment there on why an
            # unresolved short-form spelling must not be compared against a
            # resolved long-form one.
            paths.append(Path(raw).expanduser().resolve())
        except Exception:  # noqa: BLE001 - an unparseable entry is dropped, not fatal
            continue
    return paths


def _save(path: Path, paths: list[Path]) -> None:
    """Rewrite the registry WHOLE. Each path is redacted before it is written
    (convention 5) - see the module contract for why that is lossless here.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    document: dict[str, Any] = {
        "v": REGISTRY_SCHEMA_VERSION,
        "projects": [{"path": redact(str(p))} for p in paths],
    }
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(document, ensure_ascii=False, indent=2) + "\n")


def write(cwd: Path, home: Path | None = None) -> dict[str, Any]:
    """Feed ``cwd`` into the registry, prune the dead, fold in the seed.

    ONLY for an ADOPTED ``cwd`` (``keel_events.resolve_record_root`` - the
    SAME walk ``hooks/keel_session.py`` already applies before this is ever
    called, re-applied here so this function is correct even when called
    directly, as the tests do): for an unadopted project nothing is read and
    nothing is written, not even a prune of someone else's stale entry - "the
    registry is written ... only for adopted projects, never for unadopted
    ones" (T227 clause 1) is unconditional.

    THE PROJECT ROOT IS WHAT IS REGISTERED, NOT ``cwd`` (T602, BL8's residue).
    This used to ask the flat ``keel_capture.project_is_adopted(cwd)``, which
    cost the fleet registry two different things at once: a session started in
    a SUBDIRECTORY of an adopted project never registered that project AT ALL,
    and if the flat test had merely been loosened without moving the entry, the
    registry would have filled with subdirectories - a fleet list whose members
    are not projects. The walk answers both: the entry is the ROOT the walk
    names, so a session in ``<root>/src`` registers ``<root>``, exactly the
    entry a session started at the root would have written. Idempotence
    survives that (T227 clause 2's set union) because both spellings now
    normalise to the same resolved root, where before they were two keys.

    UNADOPTED AND UNRESOLVABLE STILL WRITE NOTHING. The walk returns a
    directory that ALREADY carries ``.keel/`` or nothing at all, so nothing
    here can create a ``.keel/`` anywhere new (R25), and an exhausted walk
    writes nothing either - a project keel cannot name is not a project keel
    registers.

    ABSENT IS SILENT, EXHAUSTED IS SAID (convention 7), the SAME rule and the
    SAME voice as ``keel_hook._recording_project``, which is why this asks
    ``resolve_record_root`` rather than the one-line ``record_root_or_none``:
    that helper collapses both refusals into one None, and this function's
    only other channel is a stats mapping whose ``written`` is False either
    way - so an exhausted walk would leave NO trace anywhere. "No project
    above this path" is a COMPLETE answer and an unadopted tree is keel's
    business to leave alone. "The walk ran out of budget" is an INCOMPLETE
    one: a project that owns this path may exist above the ceiling, so the
    fleet is missing an entry it should have had rather than declining one it
    should not, and a registry that lost a project says so.

    ONE UNION, not two writes: the surviving existing entries, the surviving
    predecessor seed, and ``cwd`` itself are all folded together before the
    single rewrite, so a reader of the file never sees a half-updated state,
    and calling this twice in the same session is a no-op the second time
    (T227 clause 2's own "idempotent - a set union").

    Returns a stats mapping; NEVER RAISES - every path is wrapped, because the
    one thing this function may not do is take a session down with it.
    """
    stats: dict[str, Any] = {"written": False, "pruned": 0, "seeded": 0, "total": 0}
    try:
        from keel_events import resolve_record_root  # noqa: PLC0415 - guarded, see contract

        resolution = resolve_record_root(cwd)
        if resolution.unknown:
            # EXHAUSTED IS SAID - see this function's docstring and the same
            # line in ``keel_hook._recording_project``. ABSENT falls through to
            # the silent return below.
            print(
                "keel: fleet registry not updated: the project this path "
                "belongs to could not be established within the walk's bound",
                file=sys.stderr,
            )
            return stats
        root = resolution.root
        if root is None:
            return stats
        path = registry_path(home)
        if path is None:
            print(
                "keel: fleet registry not updated: no home directory resolves",
                file=sys.stderr,
            )
            return stats
        current = _load(path) if path.is_file() else []
        survivors: list[Path] = []
        seen: set[str] = set()
        pruned = 0
        for candidate in current:
            if not _safe_is_dir(candidate):
                pruned += 1
                continue
            key = os.path.normcase(str(candidate))
            if key not in seen:
                seen.add(key)
                survivors.append(candidate)
        seeded = 0
        for candidate in _seed_candidates(home):
            key = os.path.normcase(str(candidate))
            if key not in seen:
                seen.add(key)
                survivors.append(candidate)
                seeded += 1
        # THE ROOT THE WALK NAMED, not ``cwd`` - see this function's docstring.
        # ``resolve`` is kept over the walk's already-canonical answer so the
        # spelling matches ``_load``'s and ``_seed_candidates``' entries exactly;
        # comparing an unresolved short-form against a resolved long-form is the
        # bug the comment in ``_load`` names.
        cwd_resolved = Path(root).resolve()
        key = os.path.normcase(str(cwd_resolved))
        if key not in seen:
            seen.add(key)
            survivors.append(cwd_resolved)
        _save(path, survivors)
        stats.update(
            {"written": True, "pruned": pruned, "seeded": seeded, "total": len(survivors)}
        )
        if pruned:
            print(
                f"keel: fleet registry pruned {pruned} "
                f"entr{'y' if pruned == 1 else 'ies'} no longer on disk",
                file=sys.stderr,
            )
        return stats
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: fleet registry not updated: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return stats


def read(home: Path | None = None) -> list[Path]:
    """Every registered path that still exists on disk, expanded. Never raises.

    Read-only: this function never prunes or rewrites the file - only
    ``write()`` mutates it, at session start. A reader (the board) that
    called between session starts sees a snapshot that may include an entry
    ``write()`` has not yet pruned; it simply filters those out here rather
    than reporting them.
    """
    try:
        path = registry_path(home)
        if path is None or not path.is_file():
            return []
        return [p for p in _load(path) if _safe_is_dir(p)]
    except Exception:  # noqa: BLE001 - a read that cannot run reports nothing
        return []
