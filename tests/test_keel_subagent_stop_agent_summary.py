#!/usr/bin/env python3
"""``agent_summary``: the one field ``cmd_subagent_stop`` adds beyond identity
and pointer (BL28 runbook task 3, function 5).

Contract
--------
Reads   : the sources of ``hooks/keel_hook.py`` and ``hooks/keel_compaction.py``
          for the constants this file pins against (``AGENT_SUMMARY_KEYS``,
          ``PROMPT_CHARS``, ``PROMPT_TRUNCATION_NOTE``).
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, and the one case that needs a
          fixture home points ``HOME``/``USERPROFILE`` at it (the same pattern
          ``tests/test_keel_compaction_t228.py`` uses), so what is asserted is
          this machine's redactor collapsing a home it was TOLD about, never
          this developer's own account.

What this file is for
----------------------
Sibling to ``tests/test_keel_subagent_stop.py`` rather than an addition to it
(that file is already the registration/production/consumption guard for the
whole event; this one is scoped to the one field this task adds). House
style is kept identical: fixtures are run the way a harness would - the real
launcher, as a subprocess, JSON on stdin - so what is asserted is what a
harness would get, never what the handler function would have returned in
isolation.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding.
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
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
HOOKS_DIR = REPO_ROOT / "hooks"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

sys.path.insert(0, str(HOOKS_DIR))
import keel_compaction  # noqa: E402  (path must be set first)
import keel_hook  # noqa: E402

STOP_EVENT = "subagent_stop"
AGENT_ID = "a8a960cff0a7d4560"
AGENT_TYPE = "keel:executor-deep"


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment every subprocess here runs with, absent a fixture home."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def sandbox_env(home: Path, scratch: Path) -> dict[str, str]:
    """The environment for the one case that needs the redactor sandboxed.

    ``HOME``/``USERPROFILE`` point at a fixture home, which is what makes the
    REDACTOR in that subprocess collapse the fixture home rather than this
    machine's - the same pattern ``tests/test_keel_compaction_t228.py`` uses
    to drive the same redactor through the same real writer.
    """
    env = clean_env(scratch)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    return env


def adopted_project(root: Path) -> Path:
    """A project keel would record in: it carries ``.keel/``, nothing more."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    return project


def stop_payload(project: Path, session: str, **overrides: Any) -> dict[str, Any]:
    """One SubagentStop payload in the harness's own shape."""
    payload: dict[str, Any] = {
        "hook_event_name": "SubagentStop",
        "session_id": session,
        "cwd": str(project),
        "agent_id": AGENT_ID,
        "agent_type": AGENT_TYPE,
        "stop_hook_active": False,
    }
    payload.update(overrides)
    return payload


def run_hook(
    payload: dict[str, Any], project: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[bytes]:
    """Run the launcher exactly as a harness does: argv, JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), "subagent_stop"],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=env,
        cwd=str(project),
        timeout=60,
        check=False,
    )


def audit_lines(project: Path) -> list[str]:
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.is_file():
        return []
    return [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def audit_records(project: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in audit_lines(project)]


def stops_in(project: Path) -> list[dict[str, Any]]:
    return [r for r in audit_records(project) if r.get("event") == STOP_EVENT]


class TestTheConstantAgrees(unittest.TestCase):
    """The precedence order this whole file pins against, named once."""

    def test_the_four_spellings_in_order(self) -> None:
        self.assertEqual(
            keel_hook.AGENT_SUMMARY_KEYS,
            ("last_assistant_message", "summary", "result", "output"),
        )


class TestABoundedSummaryIsRecorded(unittest.TestCase):
    """Case 1: a payload carrying ``last_assistant_message`` is recorded."""

    def test_a_short_summary_is_recorded_verbatim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(
                project,
                session,
                last_assistant_message="the delegation finished; three files changed.",
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertEqual(
                record["agent_summary"],
                "the delegation finished; three files changed.",
            )


class TestRedactionIsInherited(unittest.TestCase):
    """Case 2: a fixture HOME path inside the summary collapses to ``~``.

    Driven through the real writer with a fixture home, exactly as
    ``tests/test_keel_compaction_t228.py`` drives ``record_prompt`` - the
    point being that ``cmd_subagent_stop`` adds NO redaction of its own:
    the collapse happens at ``keel_events._append_jsonl``, the one
    chokepoint every audit line already passes through.
    """

    def test_the_summary_is_screened_at_the_one_chokepoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            scratch = root / "scratch"
            scratch.mkdir()
            project = adopted_project(root)
            session = uuid.uuid4().hex
            secret_path = str(home / "notes" / "private-plan.md")
            payload = stop_payload(
                project,
                session,
                last_assistant_message=f"read {secret_path} and reported back",
            )
            result = run_hook(payload, project, sandbox_env(home, scratch))
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = stops_in(project)[0]["agent_summary"]
            self.assertIn("~", recorded, "the home prefix collapses to ~")
            self.assertNotIn(str(home), recorded)
            self.assertNotIn(home.name, recorded)
            self.assertIn("private-plan.md", recorded, "the useful part survives")


class TestAMultilineSummaryIsOneLine(unittest.TestCase):
    """Case 3: newlines inside the summary do not become physical lines."""

    def test_newlines_are_collapsed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(
                project,
                session,
                last_assistant_message="line one\nline two\n\nline three",
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = audit_lines(project)
            self.assertEqual(len(lines), 1, "one record, one physical line")
            record = stops_in(project)[0]
            self.assertNotIn("\n", record["agent_summary"])
            self.assertEqual(record["agent_summary"], "line one line two line three")


class TestATruncatedSummarySaysSo(unittest.TestCase):
    """Case 4: a summary longer than ``PROMPT_CHARS`` is cut AND says so."""

    def test_the_cut_carries_the_truncation_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            long_text = "z" * (keel_compaction.PROMPT_CHARS + 100)
            payload = stop_payload(
                project, session, last_assistant_message=long_text
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = stops_in(project)[0]["agent_summary"]
            self.assertTrue(
                recorded.startswith("z" * keel_compaction.PROMPT_CHARS),
                recorded,
            )
            self.assertTrue(
                recorded.endswith(keel_compaction.PROMPT_TRUNCATION_NOTE),
                "a truncated value must say so, never cut silently (R34): "
                + recorded,
            )
            self.assertEqual(
                recorded,
                "z" * keel_compaction.PROMPT_CHARS
                + keel_compaction.PROMPT_TRUNCATION_NOTE,
            )


class TestEachCandidateSpellingIsReadAlone(unittest.TestCase):
    """Case 5, half one: each of the three fallback spellings is read when it
    is the ONLY candidate present."""

    def test_summary_alone(self) -> None:
        self._one_candidate_alone("summary", "summary carried the news")

    def test_result_alone(self) -> None:
        self._one_candidate_alone("result", "result carried the news")

    def test_output_alone(self) -> None:
        self._one_candidate_alone("output", "output carried the news")

    def _one_candidate_alone(self, key: str, text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(project, session, **{key: text})
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertEqual(record["agent_summary"], text)


class TestPrecedenceIsAsserted(unittest.TestCase):
    """Case 5, half two: when several candidates are present,
    ``last_assistant_message`` wins - asserted on the VALUE, not on presence
    alone, so a handler that picked a different one of the four would fail
    here even though ``agent_summary`` would still be non-null."""

    def test_last_assistant_message_beats_the_other_three(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(
                project,
                session,
                last_assistant_message="the winner",
                summary="not this one",
                result="nor this one",
                output="nor this one either",
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertEqual(record["agent_summary"], "the winner")

    def test_summary_beats_result_and_output_when_last_assistant_message_is_absent(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(
                project,
                session,
                summary="the winner",
                result="not this one",
                output="nor this one",
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertEqual(record["agent_summary"], "the winner")

    def test_result_beats_output_when_the_first_two_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(
                project, session, result="the winner", output="not this one"
            )
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertEqual(record["agent_summary"], "the winner")


class TestNoCandidateStillWritesTheLine(unittest.TestCase):
    """Case 6: none of the four present yields ``agent_summary: null``, and
    the line IS still written with the rest of the identity intact."""

    def test_a_plain_stop_is_still_recorded_in_full(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(project, session)
            self.assertNotIn("last_assistant_message", payload)
            self.assertNotIn("summary", payload)
            self.assertNotIn("result", payload)
            self.assertNotIn("output", payload)
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            records = stops_in(project)
            self.assertEqual(len(records), 1, audit_lines(project))
            record = records[0]
            self.assertIsNone(record["agent_summary"])
            self.assertEqual(record["session"], session)
            self.assertEqual(record["agent_id"], AGENT_ID)
            self.assertEqual(record["agent_type"], AGENT_TYPE)
            self.assertIn("session_transcript", record)


class TestABlankOrNonStringCandidateIsNull(unittest.TestCase):
    """Case 7: present but blank or non-string yields null, never "".

    Each fixture below carries the SOLE candidate blank or mistyped, so a
    handler that answered "" instead of None - or that trusted a candidate's
    mere presence over ``_payload_text``'s normalisation - fails here.
    """

    def test_an_empty_string_is_null_not_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(project, session, last_assistant_message="")
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertIsNone(record["agent_summary"])

    def test_a_whitespace_only_string_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(project, session, summary="   \t  ")
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertIsNone(record["agent_summary"])

    def test_a_non_string_candidate_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            payload = stop_payload(project, session, result=12345)
            result = run_hook(payload, project, clean_env(root))
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertIsNone(record["agent_summary"])


class TestNoSecondWriterAndNoSecondEventKind(unittest.TestCase):
    """R15/convention 5, restated for this field alone: no new registration,
    no new event kind, and the field goes through the one chokepoint."""

    def test_hooks_json_is_unchanged_by_this_field(self) -> None:
        document = json.loads((HOOKS_DIR / "hooks.json").read_text(encoding="utf-8"))
        groups = document["hooks"]["SubagentStop"]
        self.assertEqual(len(groups), 1, groups)
        self.assertEqual(len(groups[0]["hooks"]), 1, groups[0]["hooks"])

    def test_capped_is_reused_not_reimplemented(self) -> None:
        """R15: the same helper the prompt log uses, not a second cap this
        file could quietly diverge from - checked on the source, since the
        function returns a plain ``str`` and object identity has nothing to
        compare it against."""
        import inspect  # noqa: PLC0415 - used once, here only

        source = inspect.getsource(keel_hook._agent_summary)
        self.assertIn("keel_compaction.capped", source)


if __name__ == "__main__":
    unittest.main()
