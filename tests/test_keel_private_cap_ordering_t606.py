#!/usr/bin/env python3
"""BL34/T606 - fixtures pinning the CAP-BEFORE-REDACTION ordering, at every
interesting ``<keel-private>`` boundary, for BOTH writers that share it.

THE ORDERING THIS FILE PINS: every recorded free text is capped at
``keel_compaction.PROMPT_CHARS`` (300) BEFORE the write-time screen runs -
``keel_events._append_jsonl`` calls ``keel_redact.redact_mapping``, whose
``strip_private`` drops everything after an UNCLOSED ``<keel-private>``
opening marker. Two writers share it: ``keel_compaction.record_prompt`` and
``keel_hook._agent_summary`` (feeding ``keel_hook.cmd_subagent_stop``). This
file was raised by ``keel:reviewer-security`` reviewing T477 and filed as
BL34 because the ordering is OLDER than T477 (it has governed the prompt log
since T228) and WIDER (both writers now share it) - see
``.keel/backlog.md`` BL34 for the reviewer's own analysis, which this file
turns from an argument into a pinned fixture set.

Contract
--------
Reads   : ``hooks/keel_compaction.py`` (``capped``, ``PROMPT_CHARS``,
          ``PROMPT_TRUNCATION_NOTE``, ``record_prompt``), ``hooks/keel_hook.py``
          (``cmd_subagent_stop``/``_agent_summary``, run as the real launcher),
          ``hooks/keel_redact.py`` (``strip_private``, read directly only for
          the convention-15 mutation demonstration below - never reimplemented).
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          ``record_prompt`` is driven IN PROCESS against a fixture project (the
          same pattern ``tests/test_keel_compaction_t228.py`` uses - the prompt
          log lives in the project since T474, so no home sandbox is needed for
          it). ``cmd_subagent_stop`` is driven as a SUBPROCESS through the real
          launcher, JSON on stdin, the same pattern
          ``tests/test_keel_subagent_stop_agent_summary.py`` uses - no home
          path is involved in any fixture here, so the plain (non-sandboxed)
          environment that module calls ``clean_env`` is enough.

What this file is for
----------------------
Four boundaries, at the point ``keel_compaction.capped`` cuts the text, where
a ``<keel-private>``/``</keel-private>`` region can sit relative to that cut:

  1. the cap lands BEFORE the opening marker - the whole region is beyond the
     cut and is dropped by the cap alone, with no marker ever visible to the
     screen;
  2. the cap lands INSIDE the opening marker itself - the marker text arriving
     at the screen is a fragment ("<keel") that never spells the tag, so the
     screen finds nothing to remove, which is safe only because nothing after
     the fragment was ever included in the cut;
  3. the cap lands BETWEEN the markers - the open tag survives whole, the
     close tag does not, so the screen must read it as UNCLOSED and drop the
     remainder (this is the case the reviewer's argument leans hardest on: the
     region ends up MORE aggressively removed than the region itself,
     including trailing non-secret text);
  4. the cap lands AFTER the closing marker - the whole marked region is
     intact when the screen runs, so it is removed as a normal closed block,
     with ordinary truncation applying to whatever follows.

Each of the four is driven against BOTH writers (cases 1-4 for
``record_prompt``, cases 5-8 for ``_agent_summary``), and every case asserts
on the file written to disk, not on a function's return value in isolation -
Case 3 additionally carries the convention-15 mutation: the same raw text
run through the two screening functions in the OPPOSITE order (screen the
full text, then cap the result) - both real functions, only their sequence
changed, entirely inside this test - which changes what survives (case 3's
"between the markers" trailing text, dropped under the real ordering,
resurfaces under the reversed one), proving the fixture is sensitive to the
ordering rather than passing regardless of it.

Failure policy
--------------
FAIL-CLOSED, as every test module is: a case that cannot establish its
premise fails rather than passing quietly.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every file operation names its
encoding (convention 6). No shell, no network, no subprocess argument built
from a shell string (R5).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / "hooks"
HOOK = HOOKS_DIR / "keel_hook.py"

sys.path.insert(0, str(HOOKS_DIR))
import keel_compaction  # noqa: E402
import keel_events  # noqa: E402
import keel_hook  # noqa: E402
import keel_redact  # noqa: E402

CAP = keel_compaction.PROMPT_CHARS
NOTE = keel_compaction.PROMPT_TRUNCATION_NOTE
OPEN_TAG = "<keel-private>"
CLOSE_TAG = "</keel-private>"
SECRET = "SHIBBOLETH-NEVER-RECORDED"  # keel-leak: ignore - invented, asserted never recorded


def arm(project: Path) -> Path:
    """Give ``project`` the ``.keel/`` directory that makes it adopted."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    return project


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment ``cmd_subagent_stop`` runs with. No home path is
    involved in any fixture below, so no home sandbox is needed here - the
    same premise ``tests/test_keel_subagent_stop_agent_summary.py`` states for
    its own ``clean_env``."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_subagent_stop(payload: dict[str, Any], project: Path, scratch: Path):
    """One real launcher run of the SubagentStop subcommand."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), "subagent_stop"],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=clean_env(scratch),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def audit_records(project: Path) -> list[dict[str, Any]]:
    path = project / ".keel" / "audit" / "keel-audit.jsonl"
    if not path.is_file():
        return []
    return keel_events._read_jsonl(path)


# --------------------------------------------------------------- the fixtures
#
# Built once and shared by both writers, so a difference between how
# ``record_prompt`` and ``_agent_summary`` handle the SAME text is a
# difference in the writers, never in the fixture.


def case_1_before_opening_marker() -> tuple[str, str]:
    """Boundary 1: the cap lands entirely before the opening marker.

    The first ``CAP`` characters are plain text; the marker, the secret and
    the close tag are ALL beyond the cut, so the cap alone removes the whole
    region and the screen never sees a marker at all.
    """
    prefix = "a" * (CAP + 50)
    text = prefix + OPEN_TAG + SECRET + CLOSE_TAG + " tail"
    expected = prefix[:CAP] + NOTE
    return text, expected


def case_2_inside_opening_marker() -> tuple[str, str]:
    """Boundary 2: the cap lands INSIDE the opening marker itself.

    The cut falls 5 characters into ``OPEN_TAG`` ("<keel"), which never
    spells ``keel-private`` on its own - the screen's own casefolded
    substring test finds nothing, so it returns the fragment unchanged. Safe
    only because nothing past the fragment - the secret, the close tag - was
    ever part of the cut to begin with (the reviewer's second branch, BL34).
    """
    split = 5
    prefix = "a" * (CAP - split)
    text = prefix + OPEN_TAG + SECRET + CLOSE_TAG + " tail beyond the cap too"
    expected = prefix + OPEN_TAG[:split] + NOTE
    return text, expected


def case_3_between_the_markers() -> tuple[str, str]:
    """Boundary 3: the cap lands BETWEEN the markers - deep in the secret
    body, well past the whole opening tag and well short of the closing one.

    The FULL raw text is in fact a CLOSED block (the close tag exists further
    down) - but the cap runs first, so the text the screen ever sees carries
    only the open tag and a fragment of the secret, no close tag anywhere in
    it. That reads as UNCLOSED, and the screen drops everything from the open
    tag onward - including the truncation note that was appended after it,
    and the harmless "tail" text that follows the close tag in the full raw
    text. The prefix alone survives.
    """
    prefix = "b" * 100
    secret_body = SECRET * 10  # long enough that CAP lands inside it
    text = prefix + OPEN_TAG + secret_body + CLOSE_TAG + " tail beyond cap"
    assert len(prefix) + len(OPEN_TAG) < CAP < len(prefix) + len(OPEN_TAG) + len(
        secret_body
    ), "premise: the cap lands inside the secret body, not at either tag"
    expected = prefix
    return text, expected


def case_4_after_the_closing_marker() -> tuple[str, str]:
    """Boundary 4: the cap lands AFTER the closing marker - the whole marked
    region is intact when the screen runs, and is removed as an ordinary
    closed block; text on both sides of it, and the normal truncation note,
    are unaffected by the marker's presence."""
    prefix = "c" * 50
    marker = OPEN_TAG + SECRET + CLOSE_TAG
    tail_within_cap = "d" * 30
    tail_beyond_cap = "e" * 300
    assert len(prefix) + len(marker) + len(tail_within_cap) < CAP
    text = prefix + marker + tail_within_cap + tail_beyond_cap
    expected = prefix + tail_within_cap + "e" * (CAP - len(prefix) - len(marker) - len(tail_within_cap)) + NOTE
    return text, expected


CASES = {
    "before_opening_marker": case_1_before_opening_marker,
    "inside_opening_marker": case_2_inside_opening_marker,
    "between_the_markers": case_3_between_the_markers,
    "after_the_closing_marker": case_4_after_the_closing_marker,
}


# ------------------------------------------------------- writer 1: record_prompt


class TestRecordPromptBoundaries(unittest.TestCase):
    """Cases 1-4, driven through the real ``record_prompt`` writer."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = arm(Path(self.tmp.name) / "project")

    def _recorded(self, session: str, text: str) -> str:
        self.assertTrue(keel_compaction.record_prompt(session, text, self.project))
        path = keel_compaction.prompt_log_path(session, self.project)
        entries = keel_events._read_jsonl(path)
        self.assertEqual(len(entries), 1, entries)
        # Asserted off the raw bytes too, not merely the parsed field.
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, raw, "the secret must not reach the bytes on disk")
        return entries[0]["prompt"]

    def test_case_1_before_opening_marker(self) -> None:
        text, expected = case_1_before_opening_marker()
        recorded = self._recorded("case1-prompt", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())

    def test_case_2_inside_opening_marker(self) -> None:
        text, expected = case_2_inside_opening_marker()
        recorded = self._recorded("case2-prompt", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())

    def test_case_3_between_the_markers(self) -> None:
        text, expected = case_3_between_the_markers()
        recorded = self._recorded("case3-prompt", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())
        self.assertNotIn(NOTE.strip(), recorded)

    def test_case_4_after_the_closing_marker(self) -> None:
        text, expected = case_4_after_the_closing_marker()
        recorded = self._recorded("case4-prompt", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())
        self.assertTrue(recorded.endswith(NOTE))


# ------------------------------------------------------ writer 2: _agent_summary


class TestAgentSummaryBoundaries(unittest.TestCase):
    """Cases 5-8: the same four fixtures, driven through the real
    ``cmd_subagent_stop`` launcher subcommand rather than reimplemented."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = arm(self.root / "project")

    def _recorded(self, session: str, text: str) -> str:
        payload = {
            "hook_event_name": "SubagentStop",
            "session_id": session,
            "cwd": str(self.project),
            "agent_id": uuid.uuid4().hex,
            "agent_type": "keel:executor",
            "stop_hook_active": False,
            "last_assistant_message": text,
        }
        result = run_subagent_stop(payload, self.project, self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [
            r for r in audit_records(self.project) if r.get("event") == "subagent_stop"
        ]
        self.assertEqual(len(records), 1, records)
        path = self.project / ".keel" / "audit" / "keel-audit.jsonl"
        raw = path.read_text(encoding="utf-8")
        self.assertNotIn(SECRET, raw, "the secret must not reach the bytes on disk")
        return records[0]["agent_summary"]

    def test_case_5_before_opening_marker(self) -> None:
        text, expected = case_1_before_opening_marker()
        recorded = self._recorded("case5-stop", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())

    def test_case_6_inside_opening_marker(self) -> None:
        text, expected = case_2_inside_opening_marker()
        recorded = self._recorded("case6-stop", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())

    def test_case_7_between_the_markers(self) -> None:
        text, expected = case_3_between_the_markers()
        recorded = self._recorded("case7-stop", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())
        self.assertNotIn(NOTE.strip(), recorded)

    def test_case_8_after_the_closing_marker(self) -> None:
        text, expected = case_4_after_the_closing_marker()
        recorded = self._recorded("case8-stop", text)
        self.assertEqual(recorded, expected)
        self.assertNotIn("keel-private", recorded.casefold())
        self.assertTrue(recorded.endswith(NOTE))


# --------------------------------------------- convention 15: the mutation proof


class TestTheOrderingIsWhatMakesItSafe(unittest.TestCase):
    """Move the cap to AFTER the screen (in the test only, real functions,
    reversed sequence) and show which fixture changes.

    ``case_3_between_the_markers`` is the one built for this: its FULL raw
    text is a CLOSED block (the close tag exists, just past where the real
    cap-first ordering ever looks), so reversing the two calls - screen the
    whole raw text first, THEN cap the result - recognises it as closed
    rather than unclosed, strips only the marked span, and lets the
    "tail beyond cap" text survive into the capped output. Under the real
    ordering that same text is gone (see
    ``TestRecordPromptBoundaries.test_case_3_between_the_markers`` and
    ``TestAgentSummaryBoundaries.test_case_7_between_the_markers`` above,
    both asserting the recorded value equals ``prefix`` alone). No production
    code is touched: both calls below are the real ``keel_redact.strip_private``
    and the real ``keel_compaction.capped``, only their order is swapped, and
    only inside this test.
    """

    def test_reversing_cap_and_screen_changes_case_3(self) -> None:
        text, real_order_expected = case_3_between_the_markers()

        # The real ordering, exactly as ``record_prompt`` and ``_agent_summary``
        # apply it: cap first, screen second.
        real_order = keel_redact.strip_private(keel_compaction.capped(text))
        self.assertEqual(real_order, real_order_expected)

        # The mutated ordering BL34 asks to be tried: screen the full raw
        # text first, cap what is left second.
        mutated_order = keel_compaction.capped(keel_redact.strip_private(text))

        self.assertNotEqual(
            mutated_order, real_order,
            "case 3 must be order-sensitive, or this fixture proves nothing "
            "about which ordering is in force",
        )
        # And say exactly HOW it changed: the trailing, non-secret text that
        # the real ordering drops (having read the region as unclosed)
        # resurfaces once the screen runs on the full, genuinely-closed text.
        self.assertNotIn("tail beyond cap", real_order)
        self.assertIn("tail beyond cap", mutated_order)
        # Both orderings still keep the SECRET itself off the result - this
        # fixture demonstrates a behavioural change, not the leak the
        # reviewer's analysis already argued does not exist for this shape.
        self.assertNotIn(SECRET, mutated_order)
        self.assertNotIn(SECRET, real_order)


if __name__ == "__main__":
    unittest.main()
