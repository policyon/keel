#!/usr/bin/env python3
"""governance-field schema checker for keel records.

Contract
--------
Reads   : every ``*.md`` under the record directories - by default
          ``<project>/.keel/knowledge/`` and ``<project>/.keel/decisions/``,
          overridable with ``--dir`` (repeatable). For ``cites`` drift it also
          reads the manifest of each pinned source that resolves locally under
          ``--sources-base`` (default: the project's PARENT directory), and
          only ever to read a ``version`` string out of it.
Emits   : one ``path:line: [rule] detail`` line per finding, then a summary;
          ``--json`` emits the same report as a document. Every path printed
          is project-relative, so the report carries no username at all
          (convention 5).
Writes  : nothing. Not the records, not a cache, not a report file. Fixing a
          record is the caller's decision; this tool's job stops at telling
          the truth about one.
Argv    : ``--project DIR``, ``--dir PATH`` (repeatable), ``--sources-base
          PATH``, ``--today YYYY-MM-DD``, ``--json``, ``--quiet``.

Exit codes
----------
0  clean - no errors. Warnings may still have been printed, and an absent
   record directory is this outcome too: a project that has written no
   records yet has no rotten ones (the schema is enforced at tier 3, and
   adopting keel must not fail a build on day one).
1  findings - at least one ERROR; every one is listed with its path and line.
2  the checker itself could not run: an unreadable directory, or a ``--today``
   that is not a date.

Failure policy
--------------
FAIL-CLOSED. A check that cannot run returns 2 rather than printing a clean
bill (convention 12). An unreadable record is an ``unreadable`` FINDING, not
a skip: silent absence is how a checker lies (convention 7). The one thing
that is deliberately never a failure is an unresolvable ``cites`` pin - see
below, where that asymmetry is the whole design.

The schema
----------
The record contract, which this file defines: ``name``, ``description``,
``type``, ``generated``, ``verified``, ``cites``, ``stale_after``, plus
``status``.
``name`` and ``description`` are keel's two additions to the ratified
2026-07-30 governance-field set, and they are additions with a
reason: they are the fields a retrieval layer routes on, and a record nobody
can find is as lost as a record that rotted.

    no_frontmatter / unterminated_frontmatter
    missing_name / bad_name
    missing_description / bad_description
    missing_type / unknown_type
    unknown_status                 (free text fails; absent means draft,
                                    which is legal but is NOT stable)
    missing_generated / bad_generated
    missing_verified / bad_verified    (an EMPTY list is legal and
                                    meaningful - it means unverified; only a
                                    missing key is a finding)
    expired                        (stale_after in the past - the headline
                                    check, the rot detector)
    bad_stale_after
    assessment_without_stale_after / decision_with_stale_after
    ratified_unverified
    actor_prefix                   (warn: ``by:`` lacking human:/machine:)
    bad_cites                      (shape only - see below)
    assessment_without_cites       (warn)
    cites_drift                    (warn: a pinned source resolves locally
                                    and now publishes a different version)
    cites_unverifiable             (warn: the pin could not be resolved on
                                    this machine - skipped, never a failure)

cites and drift - why the severities are split
----------------------------------------------
``stale_after`` catches rot on a clock; it cannot catch a record whose SOURCE
moved. ``cites`` pins each external source as read, and a pin that nothing
ever compares is a date with extra syntax - so the comparison is the point of
the field.

  - ``version`` is FREE-FORM by design ("0.2.0", a commit sha, or "no
    releases; main @ 2026-07-24"). It is compared as an opaque stripped
    string. Nothing here parses versions; nothing here may start.
  - AN UNRESOLVABLE SOURCE SKIPS, IT NEVER FAILS. Not installed, path absent,
    JSON unreadable, id unknown -> ``cites_unverifiable`` and carry on.
    Failing there would make keel's own checks depend on a neighbour
    repository being present on the machine, which is the trap that makes a
    checker unrunnable for every adopter without our exact layout.
  - DRIFT IS A WARNING. The equality test is a heuristic over a free-form
    string: a different notation for one release ("0.2" against "0.2.0"), or
    merely an older local clone, both read as drift. Exiting 1 there would
    fail a record for the state of a directory outside the project and would
    reward bumping a pin without re-reading the source - an invented pin is
    worse than no pin. The SHAPE check stays an error, because "is this a
    list of {source, version, at}" is objective; "did the source really move"
    needs a human.

Parsing
-------
This is A TARGETED FRONTMATTER READER, NOT A YAML IMPLEMENTATION: no YAML
parser exists in the standard library (R7 forbids adding one). It understands
the keys in ``SCHEMA_KEYS``, only at indent 0, and only the value shapes that
occur in records: bare and quoted scalars, ``[]``, an inline flow mapping
``{ by: "...", at: "..." }``, a flow sequence of those, and an indented block
list of them. Every other key is ignored outright. A value that cannot be
understood is reported UNPARSEABLE and never collapsed into "absent".

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network - the drift resolver reads local files only. Matching is
case-insensitive by default (convention 3, R1). Every file read names its
encoding.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from keel_events import KEEL_DIRNAME  # noqa: E402

#: Where records live by default. Both are legitimately absent - see the
#: exit-code table.
DEFAULT_RECORD_DIRS: tuple[tuple[str, ...], ...] = (
    (KEEL_DIRNAME, "knowledge"),
    (KEEL_DIRNAME, "decisions"),
)

#: The record types keel recognises. ``knowledge`` is keel's addition to the
#: inherited vocabulary: it is what ``/keel:log`` writes.
TYPES = frozenset(
    {"decision", "assessment", "knowledge", "state", "priorities", "glossary", "log", "plan"}
)

#: Lifecycle vocabulary. Absent means ``draft``, which is legal but not stable.
STATUSES = frozenset({"draft", "ratified", "superseded", "deprecated", "parked"})

#: The frontmatter keys this reader understands. Everything else is ignored.
SCHEMA_KEYS: tuple[str, ...] = (
    "name",
    "description",
    "type",
    "status",
    "generated",
    "verified",
    "stale_after",
    "cites",
)

#: Every ``cites`` entry is exactly these three keys.
CITES_KEYS: tuple[str, ...] = ("source", "version", "at")

#: Filenames skipped before anything is read, and why each one is not a record:
#: ``SKILL.md`` is an EXTERNAL contract whose frontmatter belongs to the
#: harness's skill loader, and the two index files are GENERATED artifacts
#: (R34) - a checker that flags its own tooling's output teaches people to
#: ignore it.
EXEMPT_NAMES = frozenset({"SKILL.md", "keel-index.md", "keel-index-overflow.md"})

ERROR = "error"
WARN = "warn"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ACTOR_PREFIX_RE = re.compile(r"^(?:human|machine):", re.IGNORECASE)
_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_.-]*):(.*)$")


class RecordsError(RuntimeError):
    """The checker could not run at all. The caller returns 2 (fail-closed)."""


class Unresolvable(Exception):
    """A pinned source is known but its version cannot be read here.

    Always downgraded to a ``cites_unverifiable`` WARNING - never a failure.
    """


class Finding(NamedTuple):
    """One thing that is true of one record, at one line."""

    path: str
    line: int
    rule: str
    severity: str
    detail: str


class Field(NamedTuple):
    """One frontmatter key as read.

    ``error`` non-None means UNPARSEABLE, which is reported as such and never
    collapsed into "absent" (convention 7).
    """

    value: Any
    line: int
    error: str | None


# ------------------------------------------------------- source resolution


def _json_version(path: Path) -> str:
    """The top-level string ``version`` of a JSON manifest."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise Unresolvable(f"unreadable JSON ({exc})") from None
    if not isinstance(data, dict):
        raise Unresolvable("JSON root is not an object")
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise Unresolvable("no non-empty string 'version' key")
    return version.strip()


#: Source id -> (path RELATIVE TO ``--sources-base``, reader). Deliberately
#: tiny: add a line only when a source both sits beside adopting projects
#: often enough to be worth checking AND publishes its version in the same
#: notation the pins use - otherwise the comparison manufactures drift out of
#: two spellings of one release. An id that is absent here is not an error;
#: it falls through to the path resolver below, and then to a skip.
SOURCE_VERSION_TABLE: dict[str, tuple[str, Callable[[Path], str]]] = {
    "keel": ("keel/.claude-plugin/plugin.json", _json_version),
    "keel/plugin": ("keel/.claude-plugin/plugin.json", _json_version),
}


def _is_safe_relative(candidate: str) -> bool:
    """True for a plain relative path with no escape in it.

    The generic resolver below builds a path from a record's own text, so the
    shape is checked first: no drive letter, no absolute root, no ``..``.
    """
    if not candidate or candidate.startswith(("/", "\\")) or ":" in candidate:
        return False
    parts = candidate.replace("\\", "/").split("/")
    return all(part not in ("", ".", "..") for part in parts)


def resolve_source_version(
    source: str,
    base: str,
    table: dict[str, tuple[str, Callable[[Path], str]]] | None = None,
) -> tuple[str | None, str | None]:
    """Current version of ``source`` as published locally under ``base``.

    Returns ``(version, None)`` or ``(None, why_it_is_unverifiable)``. NEVER
    raises and never reports a failure: every miss is a skip. Two resolvers,
    in order - the explicit table, then a source id that is itself a relative
    path to a JSON manifest, which is how an adopter pins a neighbour keel
    knows nothing about. ``base`` is passed in rather than computed, so no
    machine-specific path is ever baked into this module.
    """
    entries = SOURCE_VERSION_TABLE if table is None else table
    key = source.strip()
    entry = entries.get(key)
    if entry is None:
        if not (_is_safe_relative(key) and key.casefold().endswith(".json")):
            return None, "no local resolver is registered for this source id"
        entry = (key, _json_version)
    relative, reader = entry
    path = Path(base) / relative
    if not path.is_file():
        return None, f"{relative} is not present under the sources base"
    try:
        return reader(path), None
    except Unresolvable as exc:
        return None, f"{relative}: {exc}"
    except OSError as exc:
        return None, f"{relative}: {exc.strerror or exc}"


# ---------------------------------------------------------- frontmatter read


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split on ``separator`` at nesting depth 0, honouring quoted spans."""
    out: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    depth = 0
    for char in text:
        if quote is not None:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
            buffer.append(char)
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        if char == separator and depth == 0:
            out.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    out.append("".join(buffer))
    return out


def _split_first_colon(text: str) -> tuple[str, str] | None:
    """``key: value`` split at the first depth-0, unquoted colon."""
    quote: str | None = None
    depth = 0
    for index, char in enumerate(text):
        if quote is not None:
            if char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        elif char == ":" and depth == 0:
            return text[:index], text[index + 1 :]
    return None


def _scalar(raw: str) -> str:
    """Unquote a scalar; on a bare scalar drop a trailing ``' #'`` comment."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    index = value.find(" #")
    if index != -1:
        value = value[:index]
    return value.strip()


def _parse_flow_map(raw: str) -> dict[str, str]:
    """``{ by: "...", at: "..." }`` -> a dictionary."""
    value = raw.strip()
    if not (value.startswith("{") and value.endswith("}")):
        raise ValueError("not a flow mapping")
    inner = value[1:-1].strip()
    if not inner:
        return {}
    out: dict[str, str] = {}
    for part in _split_top_level(inner):
        if not part.strip():
            continue
        pair = _split_first_colon(part)
        if pair is None:
            raise ValueError(f"no key: in {part.strip()!r}")
        out[_scalar(pair[0])] = _scalar(pair[1])
    return out


def _parse_flow_seq(raw: str) -> list[dict[str, str]]:
    """``[ {..}, {..} ]`` -> a list of dictionaries."""
    value = raw.strip()
    if not (value.startswith("[") and value.endswith("]")):
        raise ValueError("not a flow sequence")
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [_parse_flow_map(part) for part in _split_top_level(inner) if part.strip()]


def _parse_block_items(lines: Sequence[str]) -> list[dict[str, str]]:
    """An indented block list of mappings, in either accepted spelling."""
    groups: list[list[str]] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            groups.append([stripped[2:].strip()])
        elif stripped == "-":
            groups.append([])
        else:
            if not groups:
                raise ValueError(f"stray continuation line {stripped!r}")
            groups[-1].append(stripped)
    out: list[dict[str, str]] = []
    for group in groups:
        if group and group[0].startswith("{"):
            if len(group) > 1:
                raise ValueError("multi-line flow mapping is not supported")
            out.append(_parse_flow_map(group[0]))
            continue
        item: dict[str, str] = {}
        for entry in group:
            pair = _split_first_colon(entry)
            if pair is None:
                raise ValueError(f"no key: in {entry!r}")
            item[_scalar(pair[0])] = _scalar(pair[1])
        out.append(item)
    return out


def _read_value(rest: str, continuation: Sequence[str], line_no: int) -> Field:
    """One key's value, in whichever of the supported shapes it is written."""
    body = rest.strip()
    try:
        if body.startswith("{"):
            return Field(_parse_flow_map(body), line_no, None)
        if body.startswith("["):
            return Field(_parse_flow_seq(body), line_no, None)
        if body:
            return Field(_scalar(body), line_no, None)
        items = [line for line in continuation if line.strip() and not line.strip().startswith("#")]
        if not items:
            # `key:` with nothing under it is YAML null. Read as "present and
            # empty", which for `verified` is exactly "unverified".
            return Field([], line_no, None)
        if items[0].strip().startswith("-"):
            return Field(_parse_block_items(items), line_no, None)
        mapping: dict[str, str] = {}
        for entry in items:
            pair = _split_first_colon(entry.strip())
            if pair is None:
                raise ValueError(f"no key: in {entry.strip()!r}")
            mapping[_scalar(pair[0])] = _scalar(pair[1])
        return Field(mapping, line_no, None)
    except ValueError as exc:
        return Field(None, line_no, str(exc))


def parse_frontmatter(text: str) -> tuple[dict[str, Field] | None, str | None]:
    """Read the schema keys out of a leading ``---`` block.

    Returns ``(fields, None)`` or ``(None, structural_error)``. Only keys at
    indent 0 are considered; every non-schema key is ignored outright.
    """
    lines = text.splitlines()
    if not lines or lines[0].lstrip("﻿").strip() != "---":
        return None, "no frontmatter block (file does not start with '---')"
    end = None
    for index in range(1, len(lines)):
        if lines[index].strip() in ("---", "..."):
            end = index
            break
    if end is None:
        return None, "frontmatter block is never terminated by '---'"

    fields: dict[str, Field] = {}
    index = 1
    while index < end:
        line = lines[index]
        if not line.strip() or line[:1] in (" ", "\t") or line.lstrip().startswith("#"):
            index += 1
            continue
        match = _KEY_RE.match(line)
        if match is None:
            index += 1
            continue
        key, rest = match.group(1), match.group(2)
        # Gather indented continuation lines regardless of key, so the cursor
        # always lands on the next top-level key.
        lookahead = index + 1
        continuation: list[str] = []
        while lookahead < end and (
            not lines[lookahead].strip() or lines[lookahead][:1] in (" ", "\t")
        ):
            continuation.append(lines[lookahead])
            lookahead += 1
        if key in SCHEMA_KEYS:
            fields[key] = _read_value(rest, continuation, index + 1)
        index = lookahead
    return fields, None


# -------------------------------------------------------------------- checks


def _concise(value: Any, limit: int = 60) -> str:
    """A value, short enough for one report line."""
    text = value if isinstance(value, str) else repr(value)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _parse_date(value: str) -> dt.date | None:
    """``YYYY-MM-DD`` -> a date; None for anything else, including relatives."""
    if not _DATE_RE.match(value):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _required_text(
    path: str, fields: dict[str, Field], key: str
) -> list[Finding]:
    """``name``/``description``: a present, parseable, non-empty scalar."""
    field = fields.get(key)
    if field is None:
        return [Finding(path, 1, f"missing_{key}", ERROR, f"no '{key}' key")]
    if field.error:
        return [
            Finding(path, field.line, f"bad_{key}", ERROR, f"unparseable {key}: {field.error}")
        ]
    if not isinstance(field.value, str) or not field.value.strip():
        return [
            Finding(
                path,
                field.line,
                f"bad_{key}",
                ERROR,
                f"{key} is not a non-empty string: {_concise(field.value)!r}",
            )
        ]
    return []


def _actor_findings(path: str, line: int, where: str, actor: Any) -> list[Finding]:
    """The ``by:`` half of an actor mapping. The prefix rule is a WARN."""
    rule = "bad_generated" if where == "generated" else "bad_verified"
    if not isinstance(actor, str) or not actor.strip():
        return [Finding(path, line, rule, ERROR, f"{where}.by is missing or empty")]
    if not _ACTOR_PREFIX_RE.match(actor.strip()):
        return [
            Finding(
                path,
                line,
                "actor_prefix",
                WARN,
                f"{where}.by lacks a human:/machine: prefix: {_concise(actor)!r}",
            )
        ]
    return []


def _check_actor_map(path: str, line: int, where: str, entry: dict[str, Any]) -> list[Finding]:
    """One ``{ by, at }`` mapping, in either ``generated`` or ``verified``."""
    rule = "bad_generated" if where == "generated" else "bad_verified"
    out: list[Finding] = []
    if "by" not in entry:
        out.append(Finding(path, line, rule, ERROR, f"{where} has no 'by' key"))
    else:
        out.extend(_actor_findings(path, line, where, entry["by"]))
    at = entry.get("at")
    if at is None:
        out.append(Finding(path, line, rule, ERROR, f"{where} has no 'at' key"))
    elif _parse_date(str(at)) is None:
        out.append(
            Finding(path, line, rule, ERROR, f"{where}.at is not YYYY-MM-DD: {_concise(at)!r}")
        )
    return out


def _check_cites(
    path: str, fields: dict[str, Field]
) -> tuple[list[Finding], list[tuple[int, dict[str, str]]]]:
    """Shape-check ``cites``; return the findings and the well-formed entries.

    Only the SHAPE is an error. ``version`` is never inspected beyond being a
    non-empty string: it is free-form by design.
    """
    field = fields.get("cites")
    if field is None:
        return [], []
    if field.error:
        return [
            Finding(path, field.line, "bad_cites", ERROR, f"unparseable cites: {field.error}")
        ], []
    if not isinstance(field.value, list):
        return [
            Finding(
                path,
                field.line,
                "bad_cites",
                ERROR,
                "cites is not a list of { source, version, at } mappings: "
                f"{_concise(field.value)!r}",
            )
        ], []

    out: list[Finding] = []
    good: list[tuple[int, dict[str, str]]] = []
    for index, entry in enumerate(field.value):
        if not isinstance(entry, dict):
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_cites",
                    ERROR,
                    f"cites[{index}] is not a mapping: {_concise(entry)!r}",
                )
            )
            continue
        ok = True
        for key in CITES_KEYS:
            value = entry.get(key)
            if value is None:
                out.append(
                    Finding(
                        path, field.line, "bad_cites", ERROR, f"cites[{index}] has no '{key}' key"
                    )
                )
                ok = False
            elif not str(value).strip():
                out.append(
                    Finding(
                        path, field.line, "bad_cites", ERROR, f"cites[{index}].{key} is empty"
                    )
                )
                ok = False
        at = entry.get("at")
        if at is not None and str(at).strip() and _parse_date(str(at)) is None:
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_cites",
                    ERROR,
                    f"cites[{index}].at is not YYYY-MM-DD: {_concise(at)!r}",
                )
            )
            ok = False
        if ok:
            good.append((index, {key: str(entry[key]).strip() for key in CITES_KEYS}))
    return out, good


def check_record(path: str, text: str, today: dt.date) -> list[Finding]:
    """Every check for one record. Pure: no filesystem, no clock, no network."""
    fields, structural = parse_frontmatter(text)
    if structural is not None or fields is None:
        rule = (
            "no_frontmatter"
            if (structural or "").startswith("no frontmatter")
            else "unterminated_frontmatter"
        )
        return [Finding(path, 1, rule, ERROR, structural or "unreadable frontmatter")]
    out: list[Finding] = []

    # -- name and description: what retrieval routes on -------------------
    out.extend(_required_text(path, fields, "name"))
    out.extend(_required_text(path, fields, "description"))

    # -- type -------------------------------------------------------------
    record_type: str | None = None
    field = fields.get("type")
    if field is None:
        out.append(Finding(path, 1, "missing_type", ERROR, "no 'type' key"))
    elif field.error:
        out.append(
            Finding(path, field.line, "unknown_type", ERROR, f"unparseable type: {field.error}")
        )
    elif not isinstance(field.value, str) or field.value not in TYPES:
        out.append(
            Finding(
                path,
                field.line,
                "unknown_type",
                ERROR,
                f"type not in vocabulary: {_concise(field.value)!r}",
            )
        )
    else:
        record_type = field.value

    # -- status (absent => draft, which is legal but is NOT stable) --------
    status: str | None = "draft"
    field = fields.get("status")
    if field is not None:
        if field.error:
            out.append(
                Finding(
                    path,
                    field.line,
                    "unknown_status",
                    ERROR,
                    f"unparseable status: {field.error}",
                )
            )
            status = None
        elif not isinstance(field.value, str) or field.value not in STATUSES:
            out.append(
                Finding(
                    path,
                    field.line,
                    "unknown_status",
                    ERROR,
                    f"status not in vocabulary: {_concise(field.value)!r}",
                )
            )
            status = None
        else:
            status = field.value

    # -- generated --------------------------------------------------------
    field = fields.get("generated")
    if field is None:
        out.append(Finding(path, 1, "missing_generated", ERROR, "no 'generated' key"))
    elif field.error:
        out.append(
            Finding(
                path, field.line, "bad_generated", ERROR, f"unparseable generated: {field.error}"
            )
        )
    elif isinstance(field.value, dict):
        out.extend(_check_actor_map(path, field.line, "generated", field.value))
    else:
        out.append(
            Finding(
                path,
                field.line,
                "bad_generated",
                ERROR,
                f"generated is not a {{ by, at }} mapping: {_concise(field.value)!r}",
            )
        )

    # -- verified (key required; [] is legal AND meaningful) ---------------
    verified_count: int | None = None
    verified_line = 1
    field = fields.get("verified")
    if field is None:
        out.append(
            Finding(
                path,
                1,
                "missing_verified",
                ERROR,
                "no 'verified' key (an empty list is the way to say unverified)",
            )
        )
    else:
        verified_line = field.line
        if field.error:
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_verified",
                    ERROR,
                    f"unparseable verified: {field.error}",
                )
            )
        elif isinstance(field.value, list):
            verified_count = len(field.value)
            for entry in field.value:
                if not isinstance(entry, dict):
                    out.append(
                        Finding(
                            path,
                            field.line,
                            "bad_verified",
                            ERROR,
                            f"verified entry is not a mapping: {_concise(entry)!r}",
                        )
                    )
                    continue
                out.extend(_check_actor_map(path, field.line, "verified", entry))
        else:
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_verified",
                    ERROR,
                    f"verified is not a list: {_concise(field.value)!r}",
                )
            )

    # -- stale_after: the rot detector ------------------------------------
    field = fields.get("stale_after")
    has_stale = field is not None
    stale_line = field.line if field is not None else 1
    if field is not None:
        if field.error:
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_stale_after",
                    ERROR,
                    f"unparseable stale_after: {field.error}",
                )
            )
        elif not isinstance(field.value, str) or _parse_date(field.value) is None:
            out.append(
                Finding(
                    path,
                    field.line,
                    "bad_stale_after",
                    ERROR,
                    "stale_after is not an absolute YYYY-MM-DD date: "
                    f"{_concise(field.value)!r}",
                )
            )
        else:
            when = _parse_date(field.value)
            assert when is not None
            if when < today:
                out.append(
                    Finding(
                        path,
                        field.line,
                        "expired",
                        ERROR,
                        f"stale_after {field.value} passed {(today - when).days} day(s) ago "
                        f"(today {today.isoformat()})",
                    )
                )
    if record_type == "assessment" and not has_stale:
        out.append(
            Finding(
                path,
                1,
                "assessment_without_stale_after",
                ERROR,
                "type: assessment requires stale_after",
            )
        )
    if record_type == "decision" and has_stale:
        out.append(
            Finding(
                path,
                stale_line,
                "decision_with_stale_after",
                ERROR,
                "type: decision must not carry stale_after - a ratified decision is a "
                "historical fact; it retires via status: superseded",
            )
        )

    # -- cites ------------------------------------------------------------
    #
    # Shape is an ERROR; presence is only a WARN, and only on assessments.
    # "cites an external catalog" is not machine-detectable, so demanding the
    # field would force authors to invent pins, and an invented pin is worse
    # than none. An explicit `cites: []` is an answer and is not nudged.
    cite_findings, _ = _check_cites(path, fields)
    out.extend(cite_findings)
    if record_type == "assessment" and "cites" not in fields:
        out.append(
            Finding(
                path,
                1,
                "assessment_without_cites",
                WARN,
                "type: assessment with no cites - if this record leans on an external "
                "source, pin the version it was read at",
            )
        )

    # -- ratified with nobody having verified it --------------------------
    #
    # DELIBERATE, REASONED EXEMPTION - do not generalise it. This fires ONLY
    # for type: decision. Nobody signs off each STATE.md edit, so applying it
    # to state/priorities/log would flag them on every run, and a checker that
    # always cries wolf is a checker everyone learns to ignore. A decision is
    # different: `ratified` is an authority claim, and claiming ratification
    # with an empty `verified` list is a contradiction the record asserts
    # about itself.
    if record_type == "decision" and status == "ratified" and verified_count == 0:
        out.append(
            Finding(
                path,
                verified_line,
                "ratified_unverified",
                ERROR,
                "status: ratified but verified: [] - a ratified decision must name "
                "who ratified it",
            )
        )

    return out


def check_record_sources(
    path: str,
    text: str,
    base: str,
    table: dict[str, tuple[str, Callable[[Path], str]]] | None = None,
) -> list[Finding]:
    """Compare each well-formed pin against the source AS IT STANDS LOCALLY.

    Kept out of ``check_record`` so that function stays pure - this one
    touches the filesystem. Shape findings are re-derived and discarded here;
    ``check_record`` already reports them. Every outcome is a WARNING.
    """
    fields, structural = parse_frontmatter(text)
    if structural is not None or fields is None:
        return []
    field = fields.get("cites")
    if field is None:
        return []
    _, entries = _check_cites(path, fields)
    out: list[Finding] = []
    for index, entry in entries:
        source, pinned = entry["source"], entry["version"]
        current, why = resolve_source_version(source, base, table)
        if current is None:
            out.append(
                Finding(
                    path,
                    field.line,
                    "cites_unverifiable",
                    WARN,
                    f"cites[{index}] {source!r}: not checked - {why}",
                )
            )
        elif current != pinned:
            out.append(
                Finding(
                    path,
                    field.line,
                    "cites_drift",
                    WARN,
                    f"cites[{index}] {source!r}: pinned {pinned!r} as read on "
                    f"{entry['at']}, but it now publishes {current!r} - re-read the "
                    "source, then correct the record or repin",
                )
            )
    return out


# --------------------------------------------------------------- collection


def record_dirs(project: Path, requested: Sequence[str] | None) -> list[Path]:
    """The directories to check: ``--dir`` if given, else the two defaults."""
    if requested:
        return [Path(item) for item in requested]
    return [Path(project).joinpath(*parts) for parts in DEFAULT_RECORD_DIRS]


def collect_records(directories: Sequence[Path]) -> tuple[list[Path], list[str]]:
    """``(records, absent_directories)``. An absent directory is not an error.

    Sorted, de-duplicated, and exempt names removed before anything is read.
    """
    found: list[Path] = []
    absent: list[str] = []
    seen: set[str] = set()
    for directory in directories:
        try:
            present = directory.is_dir()
        except OSError as exc:
            raise RecordsError(f"cannot read {directory}: {exc}") from exc
        if not present:
            absent.append(str(directory))
            continue
        try:
            candidates = sorted(directory.rglob("*.md"))
        except OSError as exc:
            raise RecordsError(f"cannot walk {directory}: {exc}") from exc
        for candidate in candidates:
            if candidate.name in EXEMPT_NAMES or not candidate.is_file():
                continue
            key = str(candidate.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            found.append(candidate)
    return found, absent


def display_path(record: Path, project: Path) -> str:
    """The path as the report prints it: project-relative wherever possible.

    A relative path carries no username, which is convention 5 satisfied by
    construction rather than by a redaction pass over the output.
    """
    try:
        return record.resolve().relative_to(Path(project).resolve()).as_posix()
    except (ValueError, OSError):
        return record.name


def check_tree(
    records: Sequence[Path],
    project: Path,
    today: dt.date,
    base: str | None = None,
) -> list[Finding]:
    """Every finding for ``records``, sorted by path, line and rule.

    When ``base`` is given, pinned sources are resolved under it and compared;
    when it is None nothing outside the project is touched at all.
    """
    findings: list[Finding] = []
    for record in records:
        shown = display_path(record, project)
        try:
            text = record.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(Finding(shown, 1, "unreadable", ERROR, str(exc)))
            continue
        findings.extend(check_record(shown, text, today))
        if base is not None:
            findings.extend(check_record_sources(shown, text, base))
    return sorted(findings, key=lambda finding: (finding.path, finding.line, finding.rule))


# ---------------------------------------------------------------- reporting


def summarize(findings: Sequence[Finding], checked: int) -> dict[str, Any]:
    """Counts by rule and by file - the shape ``--json`` publishes."""
    by_rule: dict[str, int] = {}
    by_file: dict[str, int] = {}
    errors = 0
    warnings = 0
    for finding in findings:
        by_rule[finding.rule] = by_rule.get(finding.rule, 0) + 1
        by_file[finding.path] = by_file.get(finding.path, 0) + 1
        if finding.severity == ERROR:
            errors += 1
        else:
            warnings += 1
    return {
        "records_checked": checked,
        "total": len(findings),
        "errors": errors,
        "warnings": warnings,
        "by_rule": by_rule,
        "by_file": by_file,
    }


def render_text(
    findings: Sequence[Finding], checked: int, absent: Sequence[str], quiet: bool
) -> str:
    """The human report. Complete whether or not it found anything."""
    summary = summarize(findings, checked)
    lines: list[str] = []
    if not quiet:
        for finding in findings:
            tag = "" if finding.severity == ERROR else " (warn)"
            lines.append(f"{finding.path}:{finding.line}: [{finding.rule}]{tag} {finding.detail}")
        if findings:
            lines.append("")
    errors = summary["errors"]
    warnings = summary["warnings"]
    head = "keel records: clean" if not errors else f"keel records: {errors} finding(s)"
    if warnings:
        head += f", {warnings} warning(s)"
    head += f" ({checked} record(s) checked)"
    lines.append(head)
    if absent and not quiet:
        for directory in absent:
            lines.append(f"  (no record directory at {Path(directory).name}/ - nothing to check)")
    if findings and not quiet:
        lines.append("by rule:")
        for rule, count in sorted(summary["by_rule"].items()):
            lines.append(f"  {rule}: {count}")
        lines.append("by file:")
        for path, count in sorted(summary["by_file"].items()):
            lines.append(f"  {path}: {count}")
    return "\n".join(lines)


def render_json(findings: Sequence[Finding], checked: int, absent: Sequence[str]) -> str:
    """The same report as a document."""
    summary = summarize(findings, checked)
    payload = {
        "clean": summary["errors"] == 0,
        "summary": summary,
        "absent_directories": [Path(item).name for item in absent],
        "findings": [
            {
                "path": finding.path,
                "line": finding.line,
                "rule": finding.rule,
                "severity": finding.severity,
                "detail": finding.detail,
            }
            for finding in findings
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """check knowledge and decision records against the governance schema"""
    parser = argparse.ArgumentParser(
        prog="keel records",
        description="governance-field schema checker for keel knowledge and decision records",
    )
    parser.add_argument("--project", default=None, help="project directory")
    parser.add_argument(
        "--dir",
        dest="dirs",
        action="append",
        default=None,
        metavar="PATH",
        help="record directory to check (repeatable; replaces the defaults)",
    )
    parser.add_argument(
        "--sources-base",
        default=None,
        metavar="PATH",
        help="where pinned sources are looked for (default: the project's parent)",
    )
    parser.add_argument(
        "--today",
        default=None,
        metavar="YYYY-MM-DD",
        help="reference date for stale_after (default: today; fixed in tests)",
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    parser.add_argument("--quiet", action="store_true", help="emit only the summary")
    args = parser.parse_args(argv)

    try:
        if args.today and not _DATE_RE.match(args.today):
            raise RecordsError(f"--today must be YYYY-MM-DD: {args.today!r}")
        today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
        project = Path(args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        base = args.sources_base or str(project.resolve().parent)
        records, absent = collect_records(record_dirs(project, args.dirs))
    except (RecordsError, OSError, ValueError) as exc:
        print(f"keel records: {exc}", file=sys.stderr)
        return 2

    findings = check_tree(records, project, today, base=base)
    if args.as_json:
        print(render_json(findings, len(records), absent))
    else:
        print(render_text(findings, len(records), absent, args.quiet))
    return 1 if any(finding.severity == ERROR for finding in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
