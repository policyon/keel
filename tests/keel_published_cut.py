#!/usr/bin/env python3
"""Shared discriminator: is this tree a published-cut mirror, or the record?

Contract
--------
Reads   : ``<root>/.keel/published-cut.md`` (existence only, never its
          contents), ``<root>/.keel/plans/keel-plan-*.md``,
          ``<root>/.keel/audit/keel-audit.jsonl`` and
          ``<root>/scripts/keel-refs-waiver.json`` — all read-only.
Emits   : nothing; two functions other test modules import.
Writes  : nothing.

Why this exists
----------------
T249: the published mirror ships ``.keel/`` with an EMPTY record (ratified,
2026-08-22-keel-publishes-a-fresh-mirror-without-its-working-records.md), so
seven self-referential tests that read THIS repository's real corpus — the
audit log, the waiver register, the state-dir ``.gitkeep`` files — need a
tracked, declared discriminator between "the corpus is missing because
nobody ever recorded anything here" (fail closed, as today) and "the corpus
is missing because this is the published cut, and emptiness is exactly what
was declared" (assert the declared-empty shape, never skip).

The marker is a file, not an environment variable or a CLI flag, because it
must travel WITH the tree: whatever clones or copies the mirror gets the
marker too, and whatever clones or copies this repository does not — unless
someone commits the marker here, which is exactly the contradiction
``contradiction`` exists to catch.

Failure policy
--------------
N/A — a test-only helper, not production code. Both functions read files
defensively (a missing or unparsable JSON register is treated as no
waivers, matching ``keel_checks._load_refs_waivers``'s own fail-closed
reading) but never hide a real corpus: ``contradiction`` is checked BEFORE
any test asserts the declared-empty shape, so a leaked marker on a tree that
still carries this repository's records fails loudly instead of silently
skipping the six guards it would otherwise disarm.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

#: The tracked file the mirror assembly writes. Relative components, joined
#: with ``Path.joinpath`` at each call site the same way every other test
#: module builds ``AUDIT_RELPATH`` — one shape for "a path under .keel/".
MARKER_RELPATH = (".keel", "published-cut.md")

#: Same waiver register :mod:`keel_checks` reads, named again here rather
#: than imported from it: this helper answers a question about the TREE, not
#: about that module's own logic, and importing it would put a production
#: module's ``sys.path`` requirements on every caller of this one.
REFS_WAIVER_RELPATH = ("scripts", "keel-refs-waiver.json")


def marker_path(root: Path) -> Path:
    """Where the published-cut marker lives under ``root``."""
    return root.joinpath(*MARKER_RELPATH)


def is_published_cut(root: Path) -> bool:
    """True only if the tracked marker file is present under ``root``.

    Presence, not content: the marker's declaration lives in the ratified
    decision it cites, not in text a test would then be trusted to parse.
    """
    return marker_path(root).is_file()


def _ledger_paths(root: Path) -> list[Path]:
    plans_dir = root / ".keel" / "plans"
    if not plans_dir.is_dir():
        return []
    return sorted(plans_dir.glob("keel-plan-*.md"))


def _audit_lines(root: Path) -> list[str]:
    audit = root / ".keel" / "audit" / "keel-audit.jsonl"
    if not audit.is_file():
        return []
    text = audit.read_text(encoding="utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()]


def _waivers(root: Path) -> list[dict]:
    path = root.joinpath(*REFS_WAIVER_RELPATH)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    return [entry for entry in data.get("waivers", []) if isinstance(entry, dict)]


def shipped_policy_documents(root: Path) -> tuple[str, ...]:
    """The policy documents this tree actually carries, in reading order.

    A published cut ships NO arming file — arming is the adopter's own act,
    ratified 2026-08-31
    (`.keel/decisions/2026-08-31-the-shipped-product-is-not-armed.md`) — so a
    test that loops over "both shipped documents" must loop over what is here
    rather than over what the development repository happens to have.

    One definition, so the D6 self-hosting tests and the cut agree about what
    "shipped" means instead of each deciding for itself.
    """
    if is_published_cut(root):
        return ("templates/keel-policy.md",)
    return (".keel/keel-policy.md", "templates/keel-policy.md")


def contradiction(root: Path) -> Optional[str]:
    """``None`` if a published-cut tree's corpus is consistent with the
    declared emptiness; otherwise a string naming the first contradiction
    found, checked in a fixed order so the message is deterministic.

    A marker true of THIS repository — carrying session ledgers, a
    non-empty audit log, or a non-empty waiver register — is exactly the
    leak this guards against: without it, a marker accidentally committed
    here would silently flip six corpus tests from "verify the real record"
    to "assert it is empty", and they would pass while reading nothing.
    """
    ledgers = _ledger_paths(root)
    if ledgers:
        return (
            "published-cut marker present but a session ledger exists: "
            f"{ledgers[0]}"
        )
    audit_lines = _audit_lines(root)
    if audit_lines:
        return (
            "published-cut marker present but the audit log is non-empty: "
            f"{len(audit_lines)} line(s) at {root / '.keel' / 'audit' / 'keel-audit.jsonl'}"
        )
    waivers = _applicable_waivers(root)
    if waivers:
        return (
            "published-cut marker present but the waiver register carries "
            f"{len(waivers)} APPLICABLE entry(ies) at "
            f"{root.joinpath(*REFS_WAIVER_RELPATH)}"
        )
    return None


def _applicable_waivers(root: Path) -> list[dict]:
    """Waiver entries whose named file is actually present in ``root``.

    THE REGISTER ITSELF LEGITIMATELY SHIPS, so its mere non-emptiness cannot be
    the test. ``scripts/keel-refs-waiver.json`` is a tracked source file and a
    cut carries it like any other; what it must not carry is a LIVE waiver,
    because a live waiver means the file it waives is here — and the files this
    project waives violations in are session ledgers, which a cut ships without.

    This is the same distinction ratified for ``check_refs`` (backlog BL14):
    an entry naming a file absent from the tree is INAPPLICABLE, not stale and
    not evidence of a development corpus. One predicate, two guards, so they
    cannot drift into disagreeing about the same register.

    The guard's purpose survives intact: a marker accidentally committed in the
    development repository still contradicts, because there every entry names a
    ledger that IS present.
    """
    return [
        entry
        for entry in _waivers(root)
        if isinstance(entry.get("file"), str) and (root / entry["file"]).exists()
    ]
