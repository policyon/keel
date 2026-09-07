#!/usr/bin/env python3
"""keel derived search index - the cache the record files can always rebuild.

Contract
--------
Reads   : every ``*.md`` under ``<project>/.keel/knowledge/`` and
          ``<project>/.keel/decisions/`` - the same directories and the same
          exemptions ``scripts/keel_records.py`` uses, and the same
          frontmatter reader, so the index cannot disagree with the checker
          about what a record says.
Emits   : one report line per command on stdout; ``--json`` emits the status
          as a document. Every path printed is project-relative.
Writes  : ``<project>/.keel/cache/keel-index.db`` and nothing else. That file
          is a CACHE, not a record: it is gitignored, it has exactly one
          producer, and deleting the whole ``.keel/cache/`` directory loses
          nothing that ``keel index rebuild`` cannot derive again from the
          markdown. A test asserts that round trip rather than trusting it.
Argv    : ``keel index rebuild`` | ``keel index status``, each accepting
          ``--project DIR``; ``status`` also accepts ``--json``.

Exit codes
----------
0  the command ran. An absent index is this outcome for ``status``: a project
   that has never built one has no broken one, and the remedy is printed.
2  the command could not run - an unreadable record directory, a database
   that cannot be opened, or a rebuild that failed part way.

There is deliberately no exit code 1. This tool has no findings to report;
it either derived the cache or it could not.

The two search implementations, and why both ship
-------------------------------------------------
FTS5 is a compile-time option of SQLite, so its presence is a property of the
interpreter the adopter happens to have, not of keel. keel therefore PROBES
at open - it creates and drops a scratch FTS5 table rather than parsing a
version string - and falls back to a plain table scanned with ``LIKE`` when
the probe fails.

Both implementations answer the SAME search contract, and the contract is
enforced rather than asserted: ``Index.search`` is one shared method, and the
ONLY thing a backend supplies is ``_matching_ids``. Term parsing, ordering
and limiting are backend-independent by construction. The conformance kit in
``tests/contracts/keel_search_contract.py`` runs one set of cases against
both backends, which is what makes "the index engine is swappable" a checked
claim instead of a diagram.

Search semantics (the contract both backends implement)
-------------------------------------------------------
A query is split into ASCII alphanumeric terms; every term must match, and a
term matches at the START of a word, case-insensitively. ``index`` therefore
finds ``keel-index`` and ``INDEX``; ``dex`` finds neither. Hits are ordered
newest date first, then identifier ascending, so two backends given the same
corpus return the same list in the same order.

Identifiers
-----------
A record's identifier is its file stem: the file IS the record, so the name
on disk is the name in the index, and ``keel chart --get <id>`` can resolve
one straight back to a path with no database at all. Where two directories
carry the same stem, both identifiers are qualified with the directory name -
never silently de-duplicated, because losing a record to a name collision is
exactly the class of defect a derived cache must not introduce.

Failure policy
--------------
FAIL-CLOSED. This is a build-time and review-time tool, not a runtime guard:
a rebuild that cannot complete returns 2 and says why rather than leaving a
half-built cache behind a clean exit code (convention 12). The rebuild is
also atomic in the way that matters - the old database file is removed first,
so an interrupted rebuild leaves an absent index (which every reader handles)
rather than a stale one that lies.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network, no model calls. Matching is case-insensitive by default (convention
3, R1). Every file read names its encoding (convention 6). Values reaching
the database pass ``keel_redact`` first (convention 5), and SQL is
parameterised throughout - no query is built by string interpolation of a
value (R5 in spirit: data is data).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable, NamedTuple, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import keel_records  # noqa: E402
from keel_events import KEEL_DIRNAME  # noqa: E402
from keel_redact import redact  # noqa: E402

#: Where the derived cache lives, relative to the project. Gitignored.
CACHE_SUBPATH: tuple[str, ...] = (KEEL_DIRNAME, "cache")

#: The one file this module produces.
INDEX_FILENAME = "keel-index.db"

#: Schema version of the derived database. A bump means "rebuild", never
#: "migrate": there is nothing in here that the markdown does not carry.
SCHEMA_VERSION = 1

#: Environment switch that forces the degraded backend. It exists so the
#: fallback is exercised on a machine whose SQLite has FTS5 - a fallback that
#: only runs where it cannot be tested is a fallback nobody has tested.
FTS5_ENV = "KEEL_INDEX_FTS5"

#: Values of FTS5_ENV that mean "do not use FTS5". Matched casefolded (R1).
OFF_VALUES = frozenset({"off", "0", "no", "false"})

#: SQLite settings applied to every connection. ``busy_timeout`` is the one
#: that matters in practice: two sessions rebuilding at once should wait, not
#: fail.
BUSY_TIMEOUT_MS = 5000

#: How wide one index line may be. The line is a routing signal, not the
#: record: 120 characters is enough to recognise a record and cheap enough to
#: inject a screenful of them.
LINE_CHARS = 120

#: How many hits a search returns when the caller names no limit.
DEFAULT_LIMIT = 20

#: The two backends. The value is stored in the database so a reader knows
#: which one built it without probing again.
BACKEND_FTS5 = "fts5"
BACKEND_LIKE = "like"

#: A search term: ASCII alphanumerics only. Underscores and hyphens are
#: SEPARATORS, not term characters, because that is how the FTS5 tokenizer
#: reads them - matching the tokenizer here is what keeps the two backends
#: answering the same question.
_TERM_RE = re.compile(r"[0-9A-Za-z]+")

#: What "the start of a word" means for the degraded backend. Deliberately
#: the same boundary the tokenizer uses.
_WORD_START = r"(?<![0-9A-Za-z])"


class KeelIndexError(RuntimeError):
    """The index command could not run. The caller returns 2 (fail-closed)."""


class Record(NamedTuple):
    """One knowledge or decision record, as the index stores it."""

    id: str
    path: str
    type: str
    date: str
    title: str
    status: str
    body: str

    @property
    def search_text(self) -> str:
        """Everything a query may match, in one lowercased blob."""
        return " ".join((self.id, self.type, self.title, self.body)).casefold()


class Hit(NamedTuple):
    """One search or index result - the layer-1 view of a record."""

    id: str
    date: str
    type: str
    title: str

    def line(self, limit: int = LINE_CHARS) -> str:
        """``id date type title``, redacted, never wider than ``limit``.

        The date placeholder keeps the columns aligned for a record whose
        frontmatter carries no ``generated.at``; a missing date is shown as
        missing rather than guessed.
        """
        rendered = redact(
            f"{self.id} {self.date or '----------'} {self.type or 'record'} {self.title}".strip()
        )
        rendered = " ".join(rendered.split())
        if len(rendered) > limit:
            rendered = rendered[: max(0, limit - 3)].rstrip() + "..."
        return rendered


# ------------------------------------------------------------------- reading


def index_path(project: Path) -> Path:
    """Location of the derived database for a project."""
    return Path(project).joinpath(*CACHE_SUBPATH, INDEX_FILENAME)


def record_paths(project: Path) -> list[Path]:
    """Every record file, sorted, with the checker's exemptions applied."""
    directories = keel_records.record_dirs(Path(project), None)
    try:
        found, _absent = keel_records.collect_records(directories)
    except keel_records.RecordsError as exc:
        raise KeelIndexError(str(exc)) from exc
    return found


def _scalar(fields: dict[str, Any], key: str) -> str:
    """A frontmatter scalar as a stripped string; "" when absent or unusable."""
    field = fields.get(key)
    if field is None or field.error or not isinstance(field.value, str):
        return ""
    return field.value.strip()


def _generated_at(fields: dict[str, Any]) -> str:
    """The ``generated.at`` date, or "" when the record does not carry one."""
    field = fields.get("generated")
    if field is None or field.error or not isinstance(field.value, dict):
        return ""
    value = field.value.get("at")
    return str(value).strip() if value is not None else ""


def body_of(text: str) -> str:
    """Everything after the frontmatter block; the whole file when there is none.

    The frontmatter FIELDS are parsed by ``keel_records`` and never re-parsed
    here - only the block boundary is found, because two frontmatter readers
    in one repository is one reader too many.
    """
    lines = text.splitlines()
    if not lines or lines[0].lstrip("﻿").strip() != "---":
        return text
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            return "\n".join(lines[index + 1 :]).strip()
    return ""


def read_record(path: Path, identifier: str, project: Path) -> Record:
    """One record file, read and redacted, ready to be indexed."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise KeelIndexError(f"cannot read {path.name}: {exc}") from exc
    fields, structural = keel_records.parse_frontmatter(text)
    fields = {} if structural is not None or fields is None else fields
    return Record(
        id=identifier,
        path=keel_records.display_path(path, Path(project)),
        type=_scalar(fields, "type"),
        date=_generated_at(fields),
        title=redact(_scalar(fields, "description") or _scalar(fields, "name") or identifier),
        status=_scalar(fields, "status"),
        body=redact(body_of(text)),
    )


def identifiers_for(paths: Sequence[Path]) -> list[str]:
    """One identifier per path, qualified where two stems collide.

    A collision is rare and a silent loss is not acceptable, so BOTH sides of
    a collision are qualified with their directory name - the identifiers
    stay stable for everything else in the tree.
    """
    stems = [path.stem for path in paths]
    duplicated = {stem for stem in stems if stems.count(stem) > 1}
    return [
        f"{path.parent.name}/{path.stem}" if path.stem in duplicated else path.stem
        for path in paths
    ]


def read_records(project: Path) -> list[Record]:
    """Every record of a project, read from the files - no database involved."""
    paths = record_paths(project)
    identifiers = identifiers_for(paths)
    return [
        read_record(path, identifier, project)
        for path, identifier in zip(paths, identifiers)
    ]


# ---------------------------------------------------------------- the backend


def fts5_forced_off(env: dict[str, str] | None = None) -> bool:
    """True when the environment asks for the degraded backend explicitly."""
    source = os.environ if env is None else env
    return (source.get(FTS5_ENV) or "").strip().casefold() in OFF_VALUES


def probe_fts5(conn: sqlite3.Connection, env: dict[str, str] | None = None) -> bool:
    """Is FTS5 usable on THIS interpreter? Create a scratch table and drop it.

    A probe, not a version comparison: FTS5 is a compile-time option, so the
    only honest question is whether this SQLite will accept the statement.
    The scratch table is created in ``temp`` so a failed probe cannot leave a
    trace in the derived database.
    """
    if fts5_forced_off(env):
        return False
    try:
        conn.execute("CREATE VIRTUAL TABLE temp.keel_fts5_probe USING fts5(probe)")
        conn.execute("DROP TABLE temp.keel_fts5_probe")
    except sqlite3.Error:
        return False
    return True


def connect(db_path: Path) -> sqlite3.Connection:
    """An open connection with keel's SQLite settings applied.

    ``conn`` is closed before ``KeelIndexError`` is raised on any failure
    path: an unclosed ``sqlite3.Connection`` keeps the underlying file
    handle open, and the raised exception's traceback (chained via
    ``from exc``) keeps ``conn`` reachable for as long as the traceback
    is - which on some interpreters outlives this function's return. A
    caller cleaning up the containing directory right after (as the
    fail-closed fixtures do) can then find the file still held open.
    """
    conn: sqlite3.Connection | None = None
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys=ON")
    except (OSError, sqlite3.Error) as exc:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        raise KeelIndexError(f"cannot open the index: {exc}") from exc
    return conn


class Index:
    """An open derived index. One search contract, two backends beneath it."""

    def __init__(self, conn: sqlite3.Connection, backend: str) -> None:
        self.conn = conn
        self.backend = backend

    # -- lifecycle ------------------------------------------------------
    def close(self) -> None:
        """Close the connection. Safe to call twice."""
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "Index":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- the one backend-specific step ----------------------------------
    def _matching_ids(self, terms: Sequence[str]) -> set[str]:
        """Identifiers whose text matches every term. THE swappable method.

        Everything else about a search - what a term is, how hits are
        ordered, how many are returned - is shared, so a second backend is
        this method and nothing else.
        """
        if self.backend == BACKEND_FTS5:
            expression = " ".join(f'"{term}"*' for term in terms)
            rows = self.conn.execute(
                "SELECT id FROM keel_search WHERE keel_search MATCH ?", (expression,)
            ).fetchall()
            return {row["id"] for row in rows}
        clauses = " AND ".join("search_text LIKE ?" for _ in terms)
        rows = self.conn.execute(
            f"SELECT id, search_text FROM keel_records WHERE {clauses}",
            tuple(f"%{term}%" for term in terms),
        ).fetchall()
        # LIKE narrows; ``re`` decides. Substring matching alone would make
        # the degraded backend ANSWER A DIFFERENT QUESTION - "dex" would find
        # "index" here and nothing under FTS5 - so the word-start rule is
        # applied explicitly, with the same boundary the tokenizer uses.
        patterns = [re.compile(_WORD_START + re.escape(term), re.IGNORECASE) for term in terms]
        return {
            row["id"]
            for row in rows
            if all(pattern.search(row["search_text"]) for pattern in patterns)
        }

    # -- the shared contract --------------------------------------------
    def search(self, query: str, limit: int = DEFAULT_LIMIT) -> list[Hit]:
        """Hits for ``query``, newest first. Identical across both backends.

        An empty query, or one with no usable term in it, is no matches -
        never every record. A report that answers a meaningless question with
        the whole corpus is a report that cannot be trusted with a real one.
        """
        terms = [match.group(0).casefold() for match in _TERM_RE.finditer(query or "")]
        if not terms:
            return []
        identifiers = self._matching_ids(terms)
        if not identifiers:
            return []
        return self._hits(identifiers)[: max(0, limit)]

    def _hits(self, identifiers: Iterable[str] | None = None) -> list[Hit]:
        """Hits for a set of identifiers (or all of them), newest first."""
        rows = self.conn.execute(
            "SELECT id, date, type, title FROM keel_records"
        ).fetchall()
        wanted = None if identifiers is None else set(identifiers)
        hits = [
            Hit(id=row["id"], date=row["date"], type=row["type"], title=row["title"])
            for row in rows
            if wanted is None or row["id"] in wanted
        ]
        return sort_hits(hits)

    def summaries(self, limit: int | None = None) -> list[Hit]:
        """Every record, newest first - the injection and status view."""
        hits = self._hits()
        return hits if limit is None else hits[: max(0, limit)]

    def resolve(self, identifier: str) -> str | None:
        """The project-relative path of a record identifier, or None."""
        row = self.conn.execute(
            "SELECT path FROM keel_records WHERE id = ?", (identifier,)
        ).fetchone()
        return None if row is None else str(row["path"])

    def meta(self) -> dict[str, str]:
        """The database's own record of how and when it was built."""
        try:
            rows = self.conn.execute("SELECT key, value FROM keel_meta").fetchall()
        except sqlite3.Error:
            return {}
        return {str(row["key"]): str(row["value"]) for row in rows}

    def count(self) -> int:
        """How many records the index holds."""
        row = self.conn.execute("SELECT COUNT(*) AS n FROM keel_records").fetchone()
        return int(row["n"]) if row is not None else 0


def sort_hits(hits: Sequence[Hit]) -> list[Hit]:
    """Newest date first, then identifier ascending. One ordering, shared.

    Sorting happens in Python rather than in SQL on purpose: two backends
    that sort in two engines are two orderings waiting to disagree, and the
    conformance kit asserts order, not just membership. Two passes over a
    stable sort express "descending, then ascending" without a key that has
    to invert a string.
    """
    by_id = sorted(hits, key=lambda hit: hit.id)
    return sorted(by_id, key=lambda hit: hit.date, reverse=True)


# ------------------------------------------------------------------ building

_SCHEMA = (
    """
    CREATE TABLE keel_records (
        id          TEXT PRIMARY KEY,
        path        TEXT NOT NULL,
        type        TEXT NOT NULL DEFAULT '',
        date        TEXT NOT NULL DEFAULT '',
        title       TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT '',
        body        TEXT NOT NULL DEFAULT '',
        search_text TEXT NOT NULL DEFAULT ''
    )
    """,
    "CREATE INDEX keel_records_date ON keel_records (date DESC)",
    "CREATE TABLE keel_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)


def remove_index(project: Path) -> None:
    """Delete the database and its journals. An absent index is not an error."""
    base = index_path(project)
    for path in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise KeelIndexError(f"cannot remove {path.name}: {exc}") from exc


def rebuild(project: Path, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Delete the index and derive it again. Idempotent by construction.

    Rebuild is the only write path there is: nothing updates a row in place,
    so the cache cannot drift from the files by half a change.
    """
    project = Path(project)
    records = read_records(project)
    remove_index(project)
    conn = connect(index_path(project))
    try:
        backend = BACKEND_FTS5 if probe_fts5(conn, env) else BACKEND_LIKE
        for statement in _SCHEMA:
            conn.execute(statement)
        if backend == BACKEND_FTS5:
            conn.execute(
                "CREATE VIRTUAL TABLE keel_search USING fts5(id UNINDEXED, text)"
            )
        for record in records:
            conn.execute(
                "INSERT INTO keel_records"
                " (id, path, type, date, title, status, body, search_text)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.id,
                    record.path,
                    record.type,
                    record.date,
                    record.title,
                    record.status,
                    record.body,
                    record.search_text,
                ),
            )
            if backend == BACKEND_FTS5:
                conn.execute(
                    "INSERT INTO keel_search (id, text) VALUES (?, ?)",
                    (record.id, record.search_text),
                )
        for key, value in (
            ("schema_version", str(SCHEMA_VERSION)),
            ("backend", backend),
            ("records", str(len(records))),
        ):
            conn.execute("INSERT INTO keel_meta (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    except sqlite3.Error as exc:
        conn.close()
        remove_index(project)
        raise KeelIndexError(f"rebuild failed: {exc}") from exc
    finally:
        try:
            conn.close()
        except sqlite3.Error:
            pass
    return {
        "backend": backend,
        "records": len(records),
        "path": relative_path(index_path(project), project),
    }


def relative_path(path: Path, project: Path) -> str:
    """A path as a report prints it: project-relative, POSIX, no username."""
    try:
        return path.resolve().relative_to(Path(project).resolve()).as_posix()
    except (OSError, ValueError):
        return redact(str(path))


def open_index(project: Path) -> Index:
    """Open an existing index. Raises when there is none - callers choose."""
    path = index_path(project)
    if not path.is_file():
        raise KeelIndexError(f"no index at {relative_path(path, project)}; run 'keel index rebuild'")
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT value FROM keel_meta WHERE key = 'backend'"
        ).fetchone()
    except sqlite3.Error as exc:
        conn.close()
        raise KeelIndexError(f"the index is unreadable ({exc}); run 'keel index rebuild'") from exc
    backend = str(row["value"]) if row is not None else BACKEND_LIKE
    return Index(conn, backend)


def open_or_rebuild(project: Path, env: dict[str, str] | None = None) -> Index:
    """The reader's entry point: open the cache, deriving it first if absent.

    A derived cache that a reader must be told to build is a cache that will
    be missing exactly when it is wanted, so a missing one is simply built.
    """
    if not index_path(project).is_file():
        rebuild(project, env)
    return open_index(project)


def summaries(project: Path, limit: int | None = None) -> list[Hit]:
    """Every record of a project, newest first, WITHOUT requiring a cache.

    Used by the session injector, which must never depend on a derived file
    or spend a rebuild on a session start: the database is read when it is
    already there, and the record files are read when it is not.
    """
    project = Path(project)
    if index_path(project).is_file():
        try:
            with open_index(project) as index:
                return index.summaries(limit)
        except (KeelIndexError, sqlite3.Error):
            pass
    hits = sort_hits(
        [
            Hit(id=record.id, date=record.date, type=record.type, title=record.title)
            for record in read_records(project)
        ]
    )
    return hits if limit is None else hits[: max(0, limit)]


def status(project: Path) -> dict[str, Any]:
    """What the cache is, what it was built from, and whether it is there."""
    project = Path(project)
    path = index_path(project)
    report: dict[str, Any] = {
        "path": relative_path(path, project),
        "present": path.is_file(),
        "records_on_disk": len(record_paths(project)),
    }
    if not report["present"]:
        report.update({"backend": None, "records_indexed": 0})
        return report
    with open_index(project) as index:
        meta = index.meta()
        report.update(
            {
                "backend": index.backend,
                "records_indexed": index.count(),
                "schema_version": meta.get("schema_version", ""),
                "fts5_available": index.backend == BACKEND_FTS5,
            }
        )
    return report


def render_status(report: dict[str, Any]) -> str:
    """The human status line, complete whether or not an index exists."""
    if not report["present"]:
        return (
            f"keel index: none at {report['path']}; "
            f"{report['records_on_disk']} record(s) on disk - run 'keel index rebuild'"
        )
    stale = (
        ""
        if report["records_indexed"] == report["records_on_disk"]
        else " - rebuild to catch up"
    )
    return (
        f"keel index: {report['path']}, backend {report['backend']}, "
        f"{report['records_indexed']} indexed / {report['records_on_disk']} on disk{stale}"
    )


# ------------------------------------------------------------------- command


def main(argv: list[str] | None = None) -> int:
    """derive and inspect the search index over this project's records"""
    parser = argparse.ArgumentParser(
        prog="keel index",
        description="derive the search index from the record files (a cache, never a record)",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    parser.add_argument(
        "command",
        nargs="?",
        default="status",
        choices=("rebuild", "status"),
        help="rebuild: delete and derive again; status: report (default)",
    )
    args = parser.parse_args(argv)

    project = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        if args.command == "rebuild":
            result = rebuild(project)
            if args.as_json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(
                    f"keel index: rebuilt {result['path']} with {result['records']} "
                    f"record(s), backend {result['backend']}"
                )
            return 0
        report = status(project)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.as_json
              else render_status(report))
    except (KeelIndexError, OSError, sqlite3.Error) as exc:
        print(f"keel index: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
