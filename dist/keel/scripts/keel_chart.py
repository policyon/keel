#!/usr/bin/env python3
"""keel knowledge retrieval - two layers, never the whole corpus.

Contract
--------
Reads   : the derived index at ``<project>/.keel/cache/keel-index.db`` for
          layer 1, and the record FILES for layer 2. The database is a cache:
          when it is absent it is derived first, so retrieval never fails for
          want of a step the caller was supposed to remember.
Emits   : layer 1 - one line per hit, ``id date type title``, redacted and no
          wider than 120 characters. Layer 2 - the full text of each named
          record, redacted, under one header line naming its path.
Writes  : nothing, except that a missing cache is derived by
          ``scripts/keel_index.py`` before the first query.
Argv    : ``keel chart <query>...`` | ``keel chart --get <id>...``, plus
          ``--project DIR`` and ``--limit N``.

Exit codes
----------
0  the report ran - INCLUDING when it found nothing. "No matches" is an
   answer, and a retrieval tool that exits non-zero on an empty result trains
   its caller to stop asking.
2  the report could not run: an unreadable record directory, or a database
   that can neither be opened nor rebuilt.

Why two layers
--------------
Layer 1 is a routing signal: one short line per hit, cheap enough to read a
screenful of. Layer 2 is the record itself, fetched BY IDENTIFIER after the
caller has filtered. Loading full records to decide which full records to
load is how a knowledge layer spends a session's context on its own
bookkeeping; the skill in ``skills/chart/`` states the same rule for the
model, and this tool is what makes it cheap to obey.

Failure policy
--------------
FAIL-CLOSED. A report that cannot run says so and returns 2 rather than
printing an empty list that reads exactly like "there is nothing here"
(convention 7). The empty RESULT is the one thing that is not a failure, and
it is printed in words rather than as silence.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network, no model calls. Every file read names its encoding (convention 6).
Everything printed passes ``keel_redact`` (convention 5), which is also what
drops ``<keel-private>`` content that reached a record (R10).
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import keel_index  # noqa: E402
import keel_records  # noqa: E402
from keel_redact import redact  # noqa: E402

#: What layer 1 prints when a query matches nothing. A sentence, not silence.
NO_MATCHES = "no matches"

#: What layer 2 prints for an identifier that resolves to no record.
NO_RECORD = "no record with that identifier"


def search_lines(project: Path, query: str, limit: int) -> list[str]:
    """Layer 1: one line per hit, already redacted and width-bounded."""
    with keel_index.open_or_rebuild(project) as index:
        return [hit.line() for hit in index.search(query, limit)]


def record_text(project: Path, identifier: str) -> tuple[str, str] | None:
    """Layer 2: ``(relative path, redacted text)`` for one identifier.

    The index resolves the identifier, but the FILE is what is read: the
    database holds a copy and the file holds the record, and where the two
    could differ the record wins.
    """
    relative: str | None = None
    try:
        with keel_index.open_or_rebuild(project) as index:
            relative = index.resolve(identifier)
    except (keel_index.KeelIndexError, sqlite3.Error):
        relative = None
    candidates = [Path(project) / relative] if relative else []
    # No index, or an index built before this record landed: the identifier is
    # the file stem by construction, so the file can still be found without one.
    for parts in keel_records.DEFAULT_RECORD_DIRS:
        candidates.append(Path(project).joinpath(*parts, f"{identifier}.md"))
    for candidate in candidates:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8", errors="replace")
            return keel_index.relative_path(candidate, Path(project)), redact(text)
    return None


def main(argv: list[str] | None = None) -> int:
    """search knowledge records: one line per hit, full text by identifier"""
    parser = argparse.ArgumentParser(
        prog="keel chart",
        description="search the knowledge records (layer 1), then read them by identifier",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument(
        "--get",
        dest="identifiers",
        nargs="+",
        default=None,
        metavar="ID",
        help="layer 2: print the full record for each identifier",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=keel_index.DEFAULT_LIMIT,
        help=f"how many hits to print (default {keel_index.DEFAULT_LIMIT})",
    )
    parser.add_argument("query", nargs="*", default=None, help="search terms")
    args = parser.parse_args(argv)

    project = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        if args.identifiers:
            for identifier in args.identifiers:
                found = record_text(project, identifier)
                if found is None:
                    print(f"{identifier}: {NO_RECORD}")
                    continue
                relative, text = found
                print(f"--- {identifier} ({relative}) ---")
                print(text.rstrip())
            return 0
        lines = search_lines(project, " ".join(args.query or []), args.limit)
        print("\n".join(lines) if lines else NO_MATCHES)
    except (keel_index.KeelIndexError, OSError, sqlite3.Error) as exc:
        print(f"keel chart: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
