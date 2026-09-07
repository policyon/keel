#!/usr/bin/env python3
"""T156 - a resumed agent's card inherits the persona it resumed.

Contract
--------
Reads   : the orchestration board's own page source
          (``keel_orchestration_dashboard.HTML``), and nothing else. No
          fixture here touches this repository's ``.keel/``.
Emits   : unittest results only.
Writes  : nothing.
Argv    : none.

What this covers
-----------------
A resume is a message to an agent that already exists, so it fires the
hand-off pair with no ``subagent_type``: there is no launch tool call to read
one from. The id IS carried, and the launch's ``handoff_end`` carries that
same id together with the real type, so the persona is recoverable by a join
(owner ruling, ``.keel/decisions/2026-08-16-resume-persona-join-unparked.md``).

The join runs in the page, so what a Python suite can pin is its SHAPE - and
the shape is where the danger lives. A join that quietly resolved to the
wrong agent would relabel one agent's work as another's, which is worse than
the generic card it replaces. Four properties are asserted:

* it runs ONCE, at ingest, before anything downstream reads the state, so
  ring, bench, feed and drawer cannot disagree about who an agent was;
* it reads nothing but the id and the type - no timestamp, no session, no
  ordering, no description, which are the fields a plausible GUESS would be
  built from;
* an unresolved id leaves the event alone, the guard preceding every write;
* nothing is written without being marked derived, so no reader downstream
  can mistake a joined type for one the record carried.

Behaviour was exercised against a live board and against synthetic events -
a resolved resume, an orphan id, an event with no id at all, and an
already-typed event that must not be overwritten - and recorded in the
session ledger. This file keeps those guarantees from drifting afterwards.

Why this file carries its own extractor
---------------------------------------
``test_keel_dashboard_t28_31`` has ``_script``/``_functions`` helpers, but
they read KEEL'S OWN viewer, whose script carries no end-of-line comments and
whose ``_script`` asserts as much. This page is the adopted board: its
vendored script is full of them, so those helpers refuse it. The extractor
below balances braces the same way and makes no claim about comments - which
is safe HERE precisely because the function under test carries none inside
its body (its prose sits above the declaration), so nothing below can match
a comment and call it code.

Failure policy
-------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_orchestration_dashboard as board  # noqa: E402

JOIN = "joinResumePersonas"


def _function(name: str) -> str:
    """The body of ``function NAME(...){...}`` in the board's page script."""
    script = board.HTML[
        board.HTML.index("<script>") + len("<script>") : board.HTML.index("</script>")
    ]
    match = re.search(r"^(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", script, re.M)
    assert match, f"{name} is not defined in the page"
    open_at = script.index("{", match.end())
    depth, i = 0, open_at
    while i < len(script):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    assert depth == 0, f"unbalanced braces reading {name!r}"
    return script[open_at + 1 : i]


class TestTheJoinIsALookupNotAGuess(unittest.TestCase):
    def setUp(self) -> None:
        self.body = _function(JOIN)
        self.assertNotIn("//", self.body, "the body must stay prose-free (see module docstring)")

    def test_it_runs_at_ingest_so_every_reader_sees_one_answer(self) -> None:
        tick = _function("tick")
        self.assertIn(f"{JOIN}(st.events)", tick)
        self.assertLess(
            tick.index(f"{JOIN}(st.events)"),
            tick.index("lastState=st"),
            "the join must run before anything downstream reads the state",
        )

    def test_it_reads_only_the_id_and_the_type(self) -> None:
        """The fields a plausible guess would be built from are absent.

        Timing, session and ordering are how a join could be made to
        'usually' resolve; a lookup on an explicit id needs none of them.
        """
        for tempting in (r"\bts\b", "session", "handoff_kind", "description", "sort", "Date"):
            self.assertIsNone(
                re.search(tempting, self.body),
                f"{JOIN} reads {tempting!r}, which a lookup does not need",
            )
        self.assertIn("agent_id", self.body)

    def test_an_unresolved_id_is_left_alone(self) -> None:
        self.assertIn("if(!t)continue;", self.body)
        first_write = min(
            self.body.index("e.subagent_type=t"), self.body.index("e.agent_type=t")
        )
        self.assertLess(
            self.body.index("if(!t)continue;"),
            first_write,
            "an id that resolves to nothing must return before any assignment",
        )
        self.assertIn("if(!e.agent_id)continue;", self.body)

    def test_nothing_is_written_without_being_marked_as_derived(self) -> None:
        writes = re.findall(r"e\.(?:subagent_type|agent_type)=t;[^\n]*", self.body)
        self.assertTrue(writes, "no type assignment found - has the join moved?")
        for statement in writes:
            self.assertIn("__joined=true", statement, statement)

    def test_an_already_typed_event_is_never_overwritten(self) -> None:
        """A type the record carried outranks any join."""
        for field in ("subagent_type", "agent_type"):
            self.assertIn(f"!e.{field}&&", self.body)


if __name__ == "__main__":
    unittest.main()
