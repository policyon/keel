#!/usr/bin/env python3
"""BL25 (T475), the stop half: the seat's model is asked for again, at STOP.

Contract
--------
Reads   : ``hooks/keel_stop.py`` as an imported module, plus the fixture
          ledgers and transcripts each case writes into its own temporary
          project. Nothing outside a temporary directory is read.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this file is for
----------------------
BL25 measured that ``session_start`` records the model in the seat when the
harness supplies one or, failing that, from the newest ASSISTANT line of the
session's own transcript (``keel_session.model_from_transcript``) - correct,
because SessionStart runs before the assistant has said anything, so a FRESH
session has no assistant line yet and the honest answer is null. Nothing
LATER ever asked again: a ``stop_block`` line carried no opinion about the
seat at all, even though the stop hook receives the identical
``transcript_path`` at a moment when the transcript almost always already
holds an assistant line.

THE FIX IS ADDITIVE AND REUSED, NOT RE-DERIVED (R15): ``keel_stop._audit`` now
calls the SAME ``keel_session.model_from_transcript`` the session hook calls,
on the SAME field (the stop payload's own ``transcript_path``, carried on
``event.raw`` exactly as every other harness field is), so the two hooks can
never come to name the seat two different ways. Every case here is one of two
directions: a transcript that names the seat, and every way one can fail to
that must still land on an honest ``null`` - never a guess, never a raise
(convention 7).

House style: fixtures are synthetic and own their premises - each case builds
the ledger and the transcript it asserts against, and states, in the
assertion, the fact that makes the case meaningful.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

import sys  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402  (path must be set first)
import keel_stop  # noqa: E402

#: The model a transcript names in the harness's own spelling.
TRANSCRIPT_MODEL = "claude-fable-5"


def fresh_session() -> str:
    """A session id no other case has used - the loop-safety marker is keyed
    on it, and a reused id would let one case's block silently allow the
    next."""
    return uuid.uuid4().hex[:16]


def arm(project: Path, *, tier: int = 2) -> None:
    """A project keel enforces against: ``.keel/`` and an enforcing tier."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )


def write_ledger(project: Path, session: str, body: str) -> Path:
    """This session's ledger, at the one path the stop gate consults."""
    plans = project / ".keel" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"keel-plan-{session[:8]}.md"
    path.write_text(body, encoding="utf-8")
    return path


def stop_event(project: Path, session: str, **raw_overrides: Any) -> keel_events.KeelEvent:
    """One Stop event in the shape the adapter hands the gate."""
    raw: dict[str, Any] = {
        "hook_event_name": "Stop",
        "session_id": session,
        "stop_hook_active": False,
    }
    raw.update(raw_overrides)
    return keel_events.KeelEvent(kind="stop", cwd=project, session_id=session, raw=raw)


def blocks(project: Path, session: str) -> list[dict[str, Any]]:
    """Every ``stop_block`` line a project's audit log holds."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.exists():
        return []
    return [
        line
        for line in (
            json.loads(raw)
            for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()
        )
        if line.get("event") == "stop_block"
    ]


def transcript_line(model: str | None = None, role: str = "assistant") -> str:
    """One transcript line in the harness's own shape - a model, or none."""
    message: dict[str, Any] = {"role": role, "content": [{"type": "text", "text": "x"}]}
    if model is not None:
        message["model"] = model
    return json.dumps({"type": role, "message": message})


def write_transcript(path: Path, lines: list[str]) -> Path:
    """A synthetic transcript on disk, newline-terminated like the real ones."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return path


def one_open_block(
    tmp: str, *, transcript_path: Path | None = None, no_transcript_key: bool = False,
) -> tuple[Path, str]:
    """Arm a project, write one open ledger item, run the stop hook, and
    return ``(project, session)`` for the caller to inspect the audit log
    with. The block is deterministic: one ``[ ]`` item always denies."""
    root = Path(tmp)
    project = root / "project"
    session = fresh_session()
    arm(project)
    write_ledger(project, session, "- [ ] T1 - open, never closed by this fixture\n")
    overrides: dict[str, Any] = {}
    if transcript_path is not None:
        overrides["transcript_path"] = str(transcript_path)
    event = stop_event(project, session, **overrides)
    verdict = keel_stop.run(event, {})
    assert verdict.blocking, "premise: one open item always blocks"
    return project, session


class TestABlockedStopNamesTheSeat(unittest.TestCase):
    """(a) A transcript naming a model in its newest assistant line."""

    def test_the_stop_block_line_carries_the_transcripts_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line(None, role="user"), transcript_line(TRANSCRIPT_MODEL)],
            )
            project, session = one_open_block(tmp, transcript_path=transcript)
            recorded = blocks(project, session)
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["model"], TRANSCRIPT_MODEL)

    def test_the_newest_model_carrying_line_wins(self) -> None:
        """Read from the END, exactly as ``session_start`` reads it: a resumed
        or re-pointed session records what is answering NOW."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line("claude-opus-4-8"), transcript_line(TRANSCRIPT_MODEL)],
            )
            project, session = one_open_block(tmp, transcript_path=transcript)
            self.assertEqual(blocks(project, session)[0]["model"], TRANSCRIPT_MODEL)


class TestThreeWaysTheSeatStaysNull(unittest.TestCase):
    """(b) No guess, ever: absence, an unreadable file, and a transcript with
    no assistant line must all land on the SAME honest ``null`` - never an
    exception reaching the gate."""

    def test_no_transcript_path_at_all_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = one_open_block(tmp)
            recorded = blocks(project, session)
            self.assertEqual(len(recorded), 1)
            self.assertIn("model", recorded[0], "the key is present, absence is not a missing key")
            self.assertIsNone(recorded[0]["model"])

    def test_an_unreadable_transcript_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nowhere" / "session.jsonl"
            self.assertFalse(missing.exists(), "premise: the file is not there")
            project, session = one_open_block(tmp, transcript_path=missing)
            self.assertIsNone(blocks(project, session)[0]["model"])

    def test_a_transcript_with_no_assistant_line_is_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line(None, role="user"), transcript_line(None, role="system")],
            )
            project, session = one_open_block(tmp, transcript_path=transcript)
            self.assertIsNone(blocks(project, session)[0]["model"])

    def test_nothing_raises_across_all_three_absences(self) -> None:
        """Convention 7, stated as one assertion: every one of the three
        absences above still leaves a healthy, blocking gate - never a raise
        the launcher would have to convert into an ``internal_error`` deny."""
        with tempfile.TemporaryDirectory() as tmp:
            for kind, kwargs in (
                ("no path", {}),
                ("missing file", {"transcript_path": Path(tmp) / "gone.jsonl"}),
            ):
                with self.subTest(kind=kind):
                    with tempfile.TemporaryDirectory() as inner:
                        project, session = one_open_block(inner, **kwargs)
                        self.assertEqual(blocks(project, session)[0]["gate"], "stop")


class TestAFaultReadingTheSeatCostsOnlyThatField(unittest.TestCase):
    """Tests-review finding 1 (BL25/T475): a raise inside
    ``model_from_transcript`` must cost the seat alone, never the whole
    ``stop_block`` line - the module's own docstring promises this, and this
    is the proof.

    Before ``_audit`` wrapped the call in its own narrow ``try``, this exact
    monkeypatch made ``append_audit`` never run at all: the whole
    ``stop_block`` line was lost, not merely its ``model`` field. Quoted
    reproduction of that lost shape lives in this task's report rather than
    in a permanent dead branch here (convention 7's "no unreachable branch"
    concern) - this test pins the FIXED behaviour, and is the regression
    guard against the bug returning.
    """

    def test_a_raising_reader_still_lands_the_line_with_a_null_seat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = keel_stop.model_from_transcript

            def boom(_raw: Any) -> str:
                raise RuntimeError("deliberate fault reading the seat")

            keel_stop.model_from_transcript = boom
            try:
                project, session = one_open_block(tmp)
            finally:
                keel_stop.model_from_transcript = original
            recorded = blocks(project, session)
            self.assertEqual(
                len(recorded), 1, "the line must still land, not be lost with the field"
            )
            self.assertIsNone(recorded[0]["model"])
            self.assertEqual(
                recorded[0]["detail"]["open_items"], 1,
                "the rest of the accounting survives the same fault",
            )
            self.assertEqual(recorded[0]["detail"]["open_item_ids"], ["T1"])


class TestTheFieldIsAdditive(unittest.TestCase):
    """(c) The existing accounting fields are untouched by the new key."""

    def test_the_existing_count_and_identifier_fields_survive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = one_open_block(tmp)
            line = blocks(project, session)[0]
            self.assertIn("model", line, "additive: the new field is present")
            detail = line["detail"]
            self.assertEqual(detail["open_items"], 1)
            self.assertEqual(detail["open_item_ids"], ["T1"])


if __name__ == "__main__":
    unittest.main()
