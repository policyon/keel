#!/usr/bin/env python3
"""Conformance kit: the search contract over keel records.

Contract
--------
Reads   : nothing from the environment or the tree. The corpus is declared
          here, written into a temporary project by the kit, and thrown away.
Emits   : unittest results only, through whichever case class mixes this in.
Writes  : temporary directories it creates and removes.
Argv    : none. This file is a LIBRARY, imported by
          ``tests/test_keel_knowledge.py``; it declares no test case of its
          own so that discovery runs the cases exactly twice - once per
          implementation - rather than once here and once there.

What a conformance kit is for
-----------------------------
"The index engine is swappable" is a claim, and a claim about a boundary is
worth exactly as much as the test that both sides pass. This kit is that
test: one corpus, one list of cases, run unchanged against the FTS5 backend
and against the ``LIKE`` fallback. An implementation conforms if it passes;
nothing else about it is consulted, which is what makes the boundary a
contract instead of a diagram.

The cases pin the four things a caller may rely on:

1. **Case-insensitivity** - the same query in any case returns the same hits
   (convention 3, R1).
2. **Word-start matching** - ``index`` finds ``keel-index``; ``dex`` finds
   nothing. A substring engine and a token engine would differ here, so this
   is where "same contract" is won or lost.
3. **Conjunction** - every term must match, so adding a term never widens a
   result set.
4. **Order and emptiness** - newest date first, then identifier ascending;
   an empty or unusable query is no matches rather than everything.

Failure policy
--------------
FAIL-CLOSED. A kit that cannot build its corpus fails; it never reports a
conforming implementation it did not exercise.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every file write names its
encoding (convention 6).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, NamedTuple

#: The corpus every implementation is measured on. Dates are deliberately
#: out of filename order so that "newest first" cannot pass by accident.
CORPUS: tuple[tuple[str, str, str, str, str], ...] = (
    # (directory, stem, type, generated-at, body)
    (
        "knowledge",
        "keel-index-rebuild",
        "knowledge",
        "2026-08-01",
        "Rebuilding the derived cache is idempotent and lossless.",
    ),
    (
        "knowledge",
        "keel-capture-queue",
        "knowledge",
        "2026-07-28",
        "Capture appends one observation line per state change.",
    ),
    (
        "decisions",
        "keel-cache-is-deletable",
        "decision",
        "2026-07-30",
        "The index is a cache; deleting it loses nothing at all.",
    ),
)


class Case(NamedTuple):
    """One contract case: a query, and the identifiers it must return."""

    query: str
    expect: tuple[str, ...]
    why: str


#: The cases. Every implementation answers all of them identically, including
#: the order of the hits.
CASES: tuple[Case, ...] = (
    Case("rebuilding", ("keel-index-rebuild",), "a plain word matches its record"),
    Case("REBUILDING", ("keel-index-rebuild",), "the same query shouted is the same query"),
    Case("ReBuIlDiNg", ("keel-index-rebuild",), "case is never part of the question"),
    Case(
        "index",
        ("keel-index-rebuild", "keel-cache-is-deletable"),
        "a term matches at a word start, hyphens included, newest first",
    ),
    Case("dex", (), "a mid-word substring is not a match in either implementation"),
    Case(
        "cache deleting",
        ("keel-cache-is-deletable",),
        "every term must match: two terms narrow, never widen",
    ),
    Case("cache rebuilding deleting", (), "an unsatisfiable conjunction is no matches"),
    Case("keel", ("keel-index-rebuild", "keel-cache-is-deletable", "keel-capture-queue"),
         "a term in the identifier matches, and the order is by date then identifier"),
    Case("", (), "an empty query is no matches, never the whole corpus"),
    Case("!!!", (), "a query with no usable term in it is no matches"),
    Case("observation", ("keel-capture-queue",), "the body is searched, not only the title"),
    Case("decision", ("keel-cache-is-deletable",), "the record type is searchable"),
)


def write_corpus(project: Path) -> None:
    """Write the corpus into ``project`` as real record files."""
    for directory, stem, record_type, generated, body in CORPUS:
        target = project / ".keel" / directory / f"{stem}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        # A ratified DECISION must name who ratified it; a knowledge record
        # need not. The kit writes records the schema checker would accept, so
        # the corpus is never a shape only this file believes in.
        verified = (
            f'verified:\n  - {{ by: "human:operator", at: "{generated}" }}\n'
            if record_type == "decision"
            else "verified: []\n"
        )
        text = (
            "---\n"
            f"name: {stem}\n"
            f"description: {body}\n"
            f"type: {record_type}\n"
            "status: ratified\n"
            f'generated: {{ by: "machine:executor-deep", at: "{generated}" }}\n'
            f"{verified}"
            "cites: []\n"
            "---\n\n"
            f"{body}\n"
        )
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)


class SearchContract:
    """Mix into a ``unittest.TestCase`` that supplies ``build_index``.

    The subclass provides one method - ``build_index(project)`` returning an
    open index - and inherits every case. That is the whole conformance
    surface: an implementation is exercised through the same calls a caller
    would make.
    """

    #: Set by the subclass so a failure names the implementation under test.
    implementation = ""

    def build_index(self, project: Path) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError("a conformance case must supply build_index")

    def _run_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_corpus(project)
            index = self.build_index(project)
            try:
                self.assertEqual(  # type: ignore[attr-defined]
                    index.count(), len(CORPUS), "the kit's corpus was not fully indexed"
                )
                for case in CASES:
                    with self.subTest(  # type: ignore[attr-defined]
                        implementation=self.implementation, query=case.query
                    ):
                        found = tuple(hit.id for hit in index.search(case.query))
                        self.assertEqual(found, case.expect, case.why)  # type: ignore[attr-defined]
            finally:
                index.close()

    def test_the_search_contract_holds(self) -> None:
        """Every case in the kit, against this implementation."""
        self._run_cases()

    def test_the_limit_is_honoured(self) -> None:
        """A limit truncates the ordered list; it never reorders it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            write_corpus(project)
            index = self.build_index(project)
            try:
                full = [hit.id for hit in index.search("keel", limit=10)]
                self.assertEqual(  # type: ignore[attr-defined]
                    [hit.id for hit in index.search("keel", limit=2)], full[:2]
                )
                self.assertEqual([hit.id for hit in index.search("keel", limit=0)], [])  # type: ignore[attr-defined]
            finally:
                index.close()
