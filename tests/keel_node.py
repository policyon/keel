#!/usr/bin/env python3
"""Whether ``node`` is on PATH, and one audible line when it is not.

WHY THIS FILE EXISTS. Four test modules each resolved ``node`` for themselves
and each answered its absence differently: three failed a tripwire test
(``test_node_is_on_path``) and a fourth raised inside the case that needed it.
The tripwire was deliberate and its reasoning was sound — a whole class of
page-side checks skipping unnoticed is how a suite goes quietly hollow — but the
cost fell on everyone who is not this maintainer. Measured on Linux
2026-09-01: a clone on a machine without node reported **four failures**, so
"run the tests" could not reach green for an adopter at all (``.keel/backlog.md``
BL17).

WHAT THE OWNER RULED, 2026-09-01: the page-side checks SKIP. What the tripwire
was protecting is kept rather than discarded — the skip is made impossible to
miss instead of silent:

* every skipped case carries :data:`SKIP_REASON`, so a verbose run names it;
* :func:`announce_once` prints one line to stderr for a run that is not
  verbose, which is the reader the tripwire was written for.

A skip counted in unittest's own summary, named in the reason, and announced on
stderr is loud. A skip nobody could see is what was refused, and still is.

Stdlib only, like every other file in this tree.
"""

from __future__ import annotations

import shutil
import sys

#: The ``node`` executable, or ``None``. Resolved ONCE for the whole suite:
#: four modules asking the same question four times is four chances to answer
#: it differently, which is exactly what BL17 found.
NODE: str | None = shutil.which("node")

#: Why a case skipped, in the words unittest prints beside it. One sentence of
#: fact and one of remedy — a reason that does not say what to do next reads as
#: a shrug.
SKIP_REASON = (
    "node is not on PATH, so the page-side JavaScript checks cannot run. "
    "Install node and re-run to exercise them; everything else is unaffected."
)

_announced = False


def announce_once() -> bool:
    """Print node's absence to stderr, at most once per process.

    Returns whether THIS call was the one that printed — so a test can assert
    the announcement happens, and a second importer cannot double it. Silent by
    construction when node is present: there is nothing to announce.
    """
    global _announced
    if NODE is not None or _announced:
        return False
    _announced = True
    print(
        "keel tests: node not found on PATH - the page-side JavaScript checks "
        "will SKIP, not fail. Every other test still runs.",
        file=sys.stderr,
    )
    return True
