#!/usr/bin/env python3
"""T143 - keel's own viewer stops disagreeing with the board beside it.

Contract
--------
Reads   : temporary directories this file creates - no fixture here touches
          this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
Two viewers read the same log. Since T138 the adopted board withholds the
hand-offs of launches the record itself shows never took; this viewer did
not, so the same four lines were ghosts on one page and working agents on
the other. Two claims are pinned here:

* the ghost is withheld from THIS page too, counted by its own name, and
  a real open hand-off beside it is untouched (both directions);
* the rule is the IMPORTED one - patching it upstream changes what this
  page serves, which a second local implementation could not do.

And the attribution asymmetry T133 suspected: the window side of the
comparison now goes through the same normaliser the activity side always
used, so a type differing only by whitespace claims its own lines - while an
UNNAMED type still claims nothing, which is the case that would have gone
wrong if normalisation alone had been applied.

Values, not substrings
-----------------------
Everything is asserted as a value read off ``read_state`` or off the
attribution pass itself.

Failure policy
-------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import io
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_dashboard  # noqa: E402
import keel_orchestration_dashboard as board  # noqa: E402
from test_keel_dashboard_t28_31 import _handoff, _project  # noqa: E402

SESSION = "s1"


def _state(lines: list[dict[str, Any]]) -> dict[str, Any]:
    with mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 10**9):
        with tempfile.TemporaryDirectory() as tmp:
            return keel_dashboard.read_state(_project(Path(tmp), lines))


def _ghost_and_successor() -> list[dict[str, Any]]:
    """The shape of 2026-08-13T15:15Z: a launch that never returned, and the
    same delegation dispatched again twelve minutes later - the second one
    acknowledged. The first never took; the second is real."""
    lines = _handoff(
        SESSION, "tool-ghost", "keel:executor", "build the thing",
        "2026-08-13T15:15:00Z",
    )
    lines += _handoff(
        SESSION, "tool-real", "keel:executor", "build the thing",
        "2026-08-13T15:27:00Z", end="2026-08-13T15:27:05Z", agent_id="agent-7",
    )
    return lines


class TestTheGhostIsWithheldHereToo(unittest.TestCase):
    def test_a_launch_that_never_took_is_not_an_open_hand_off(self) -> None:
        state = _state(_ghost_and_successor())
        open_ids = [row.get("description") for row in state["open"]]
        self.assertNotIn("build the thing", open_ids)
        self.assertEqual(state["counts"]["working"], 0)

    def test_the_withholding_is_counted_by_its_own_name(self) -> None:
        """Not a loss and never counted as one: the log keeps every line."""
        state = _state(_ghost_and_successor())
        self.assertEqual(state["counts"]["withheld_launches"], 1)
        self.assertEqual(state["counts"]["unreadable_lines"], 0)

    def test_a_real_open_hand_off_is_left_alone(self) -> None:
        """The other direction, and the one that matters most: withholding
        must never take a live agent off the page."""
        lines = _handoff(
            SESSION, "tool-live", "keel:executor", "still running",
            "2026-08-13T15:15:00Z",
        )
        state = _state(lines)
        self.assertEqual(state["counts"]["withheld_launches"], 0)
        self.assertEqual(
            [row.get("description") for row in state["open"]], ["still running"]
        )

    def test_the_rule_is_the_imported_one(self) -> None:
        """Patch it upstream and this page follows. A local copy could not."""
        lines = _handoff(
            SESSION, "tool-live", "keel:executor", "still running",
            "2026-08-13T15:15:00Z",
        )
        with mock.patch.object(
            board, "unacknowledged_launch_ids", return_value={"tool-live"}
        ):
            state = _state(lines)
        self.assertEqual(state["counts"]["withheld_launches"], 1)
        self.assertEqual(state["open"], [])

    def test_an_unreachable_rule_serves_the_log_as_read(self) -> None:
        """Fail-open: a viewer that cannot reach the rule shows what the log
        holds - the behaviour before T143 - rather than failing a request.
        But "the filter ran and found nothing" and "the filter could not
        run at all" must not collapse into the same ``0``: the latter is
        ``None`` here, the same absence idiom ``model_of`` uses, and the
        fault is never silent (convention 7) - one stderr line names it."""
        with mock.patch.object(
            board, "unacknowledged_launch_ids", side_effect=RuntimeError("x")
        ):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
                state = _state(_ghost_and_successor())
        self.assertIsNone(state["counts"]["withheld_launches"])
        self.assertEqual(len(state["open"]), 1)
        self.assertIn("keel:", err.getvalue())
        self.assertIn("RuntimeError", err.getvalue())


class TestBothSidesOfAttributionAreNormalised(unittest.TestCase):
    def _window(self, agent: Any, group: dict[str, Any]) -> Any:
        return keel_dashboard._Window(0.0, 10.0, 0, agent, group)

    def _activity(self, agent: Any) -> dict[str, Any]:
        return {
            "v": 1, "ts": "1970-01-01T00:00:05Z", "event": "activity",
            "session": SESSION, "agent_type": agent, "tool": "Edit",
            "detail": "x",
        }

    def test_a_padded_type_claims_its_own_lines(self) -> None:
        group: dict[str, Any] = {"events": [], "inferred": 0, "inferred_ids": set()}
        line = self._activity("keel:executor")
        result = keel_dashboard._attribute_activity(
            [line], [self._window(" keel:executor ", group)]
        )
        self.assertEqual(group["events"], [line])
        self.assertIn(id(line), result.consumed)

    def test_an_unnamed_type_claims_nothing(self) -> None:
        """The regression normalisation alone would have caused: a null-typed
        hand-off must not start owning the main session's own work."""
        group: dict[str, Any] = {"events": [], "inferred": 0, "inferred_ids": set()}
        own_line = self._activity(None)
        result = keel_dashboard._attribute_activity(
            [own_line], [self._window(None, group)]
        )
        self.assertEqual(group["events"], [])
        self.assertEqual(result.own, [own_line])
        self.assertEqual(result.consumed, set())

    def test_a_named_type_still_claims_only_its_own(self) -> None:
        group: dict[str, Any] = {"events": [], "inferred": 0, "inferred_ids": set()}
        mine = self._activity("keel:executor")
        theirs = self._activity("keel:researcher")
        keel_dashboard._attribute_activity(
            [mine, theirs], [self._window("keel:executor", group)]
        )
        self.assertEqual(group["events"], [mine])


if __name__ == "__main__":
    unittest.main()
