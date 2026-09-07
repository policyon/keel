#!/usr/bin/env python3
"""Two always-on session-start facts: WHO took the seat, and WHERE to watch.

Contract
--------
Reads   : ``hooks/keel_session.py`` - both as an imported module and, for the
          production cases, as the launcher a harness actually runs
          (``python hooks/keel_hook.py session``) - plus this repository's own
          ``.keel/audit/keel-audit.jsonl``, read only and copied into a
          temporary project, never written. Its own source text is read for
          the two scans below (no home-directory reach, no computed port).
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, so a developer's own shell
          cannot change what a test observes.

What this file is for
---------------------
T130 accept 1: the ``session_start`` line names the model that took the
orchestrator seat when the harness supplies one, and carries an explicit
``null`` when it does not - because "the harness said nothing" and "nobody
looked" are different facts and a MISSING KEY cannot tell them apart. That is
the defect measured before the code was written: this project's log holds 129
``session_start`` lines, 11 with a model and 118 without, and the change is
purely in how the absence is recorded.

T131: one injected line names the orchestration viewer - fixed port 8770, the
walk-to-the-next-port caveat, and the exact start command. R19 stands
(``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``): the port is a
constant, never derived from the project path, and nothing outside this
repository is read or written to produce the line - the cross-project registry
is deliberately NOT adopted.

Both accepts share one failure policy, pinned here in both directions: the
session hook is FAIL-OPEN and returns 0 whatever throws, and losing one part
of the context never costs the session another part of it.

House style: fixtures are synthetic and own their premises - each case builds
the project it asserts against and states, in the assertion, the fact that
makes the case meaningful.

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

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
SESSION_SOURCE = REPO_ROOT / "hooks" / "keel_session.py"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

#: This repository's own audit log - long, append-only, and carrying several
#: schema generations, which is why "older lines still parse" is asserted
#: against it rather than against a fixture somebody wrote to pass.
REAL_AUDIT = REPO_ROOT.joinpath(*AUDIT_RELPATH)

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_events  # noqa: E402  (path must be set first)
import keel_session  # noqa: E402
from keel_registry_guard import (  # noqa: E402
    no_real_fleet_registry,
    no_real_hook_error_log,
)
from keel_published_cut import contradiction, is_published_cut  # noqa: E402

#: A model name in the spelling the harness actually sends: a plain string,
#: brackets and all. Spelled out here rather than imported - a guard that takes
#: its expected value from the code under test cannot see that code change.
MODEL_NAME = "claude-opus-5[1m]"

#: The session id every case here uses, and the eight characters of it the
#: ledger path is built from.
SESSION = "abcdef123456789"


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    ``HOME``/``USERPROFILE`` are pointed at ``scratch`` rather than left as
    the real ones: every case here launches a real ``session`` SessionStart,
    which feeds keel's user-global fleet registry (T227) for the adopted
    fixture project, and that write reads ``Path.home()`` - not this
    environment's ``KEEL_*`` scrub - so leaving them untouched would write
    fixture debris into the developer's real
    ``~/.claude/keel/keel-registry.json`` on every suite run.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env.update({"HOME": str(scratch), "USERPROFILE": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def run_hook(payload: dict[str, Any], project: Path, scratch: Path,
             **env_extra: str) -> subprocess.CompletedProcess:
    """Run the session hook as the harness runs it: subprocess, JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), "session"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch, **env_extra),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def adopt(project: Path, *, tier: int = 2) -> None:
    """The minimum that makes a directory keel's business: ``.keel/`` and a tier."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )


def start_payload(project: Path, **overrides: Any) -> dict[str, Any]:
    """One SessionStart payload in the harness's own shape."""
    payload: dict[str, Any] = {
        "hook_event_name": "SessionStart",
        "session_id": SESSION,
        "cwd": str(project),
        "source": "startup",
    }
    payload.update(overrides)
    return payload


def audit_lines(project: Path) -> list[dict[str, Any]]:
    """Every parsed line of a project's audit log, oldest first."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def start_lines(project: Path) -> list[dict[str, Any]]:
    """Only the ``session_start`` lines."""
    return [line for line in audit_lines(project) if line.get("event") == "session_start"]


def start_record_for(raw: dict[str, Any]) -> dict[str, Any]:
    """The record ``session_start`` would write for one payload. No filesystem."""
    event = keel_events.KeelEvent(
        kind="session_start", cwd=Path("."), session_id=SESSION, raw=raw
    )
    return keel_session.start_record(event)


class TestTheSeatIsNamedOrHonestlyNull(unittest.TestCase):
    """T130 accept 1. The two directions are the whole point: supplied and not
    supplied must be DIFFERENT lines, and both must be legible."""

    def test_a_supplied_model_is_recorded_verbatim(self) -> None:
        record = start_record_for({"source": "startup", "model": MODEL_NAME})
        self.assertEqual(record["model"], MODEL_NAME)

    def test_an_unsupplied_model_is_recorded_as_an_explicit_null(self) -> None:
        record = start_record_for({"source": "startup"})
        self.assertIn(
            "model",
            record,
            "the key must be PRESENT, or absence is indistinguishable from a "
            "recorder that never looked - the defect this task fixes",
        )
        self.assertIsNone(record["model"])

    def test_the_two_directions_produce_different_lines(self) -> None:
        supplied = start_record_for({"model": MODEL_NAME})
        unsupplied = start_record_for({})
        self.assertNotEqual(supplied["model"], unsupplied["model"])
        self.assertEqual(set(supplied) - set(unsupplied), set())

    def test_a_blank_or_non_string_model_is_absence_not_an_error(self) -> None:
        for value in ("", "   ", 5, 5.5, True, [], ["a"], None):
            with self.subTest(value=value):
                self.assertIsNone(start_record_for({"model": value})["model"])

    def test_an_object_shaped_model_records_the_name_it_sent(self) -> None:
        """The defensive branch: no such payload was measured, and it exists so
        that a shape keel cannot read never reads as 'not supplied'."""
        for raw, expected in (
            ({"id": "opus-5", "display_name": "Opus 5"}, "opus-5"),
            ({"display_name": "Opus 5"}, "Opus 5"),
            ({"name": "Opus 5"}, "Opus 5"),
            ({"id": "", "name": "Opus 5"}, "Opus 5"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(start_record_for({"model": raw})["model"], expected)

    def test_an_object_naming_nothing_keel_reads_is_still_a_null(self) -> None:
        self.assertIsNone(start_record_for({"model": {"vendor": "unknown"}})["model"])

    def test_the_field_read_is_the_payloads_own_top_level_model(self) -> None:
        """MEASURED, not assumed: the harness names the seat at the payload's
        TOP LEVEL.

        A ``message`` key inside the payload is not that field and is not read.
        Narrowed for T337, which added a fallback that reads ``message.model``
        out of the session's own TRANSCRIPT when the payload names nothing -
        so this case pins the payload's shape only, and the transcript path is
        pinned by ``TestTheTranscriptFallbackNamesTheSeat`` below. The two are
        different sources and this fixture supplies neither a transcript nor a
        ``transcript_path``, which is what keeps the expected answer null.
        """
        self.assertEqual(keel_session.MODEL_FIELD, "model")
        record = start_record_for({"message": {"model": "not-the-seat"}})
        self.assertIsNone(record["model"])


class TestTheSeatReachesTheLogThroughTheLauncher(unittest.TestCase):
    """The same two directions, but asserted on BYTES a subprocess left on
    disk - what a harness would actually get - rather than on a return value."""

    def test_a_real_session_start_writes_the_model_it_was_handed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            result = run_hook(start_payload(project, model=MODEL_NAME), project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = start_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["model"], MODEL_NAME)
            self.assertEqual(lines[0]["session"], SESSION)

    def test_a_real_session_start_without_a_model_writes_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            result = run_hook(start_payload(project), project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = start_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertIn("model", lines[0])
            self.assertIsNone(lines[0]["model"])
            self.assertIn(
                '"model": null',
                project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8"),
                "the null is written as JSON null, not as the string 'None'",
            )

    def test_the_line_keeps_every_field_it_carried_before(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            self.assertEqual(
                run_hook(start_payload(project), project, scratch).returncode, 0
            )
            line = start_lines(project)[0]
            for field in ("v", "ts", "event", "session", "source"):
                self.assertIn(field, line, "additive only: nothing may be dropped")
            self.assertEqual(line["source"], "startup")

    def test_a_session_end_is_untouched_by_the_seat_field(self) -> None:
        """Only a START names a seat. An end line that grew a null ``model``
        would be a schema change nobody asked for."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            payload = start_payload(project, hook_event_name="SessionEnd", reason="clear")
            result = run_hook(payload, project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            ends = [line for line in audit_lines(project) if line["event"] == "session_end"]
            self.assertEqual(len(ends), 1)
            self.assertNotIn("model", ends[0])


class TestOlderLinesStillParse(unittest.TestCase):
    """Additive only, asserted against a log nobody wrote to pass this test."""

    def test_this_repositorys_own_session_start_lines_all_parse(self) -> None:
        self.assertTrue(REAL_AUDIT.exists(), "the repository's own audit log is the fixture")
        starts = [
            json.loads(line)
            for line in REAL_AUDIT.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip() and '"session_start"' in line
        ]
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            self.assertEqual(
                starts, [], "a published cut declares no session_start lines to check"
            )
            return
        self.assertGreater(len(starts), 50, "too few lines to be evidence of anything")
        for line in starts:
            self.assertEqual(line["event"], "session_start")
            self.assertIn("session", line)
        with_model = [line for line in starts if line.get("model")]
        self.assertTrue(
            with_model,
            "the measurement this task rests on: some historical lines DID carry "
            "a model, which is how the drying-up was noticed at all",
        )

    def test_appending_a_new_line_leaves_the_older_bytes_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True, exist_ok=True)
            # An OLD-SHAPE line: no ``model`` key at all, which is exactly what
            # 118 of this project's 129 real ones look like.
            old = '{"v": 1, "ts": "2026-08-01T00:00:00Z", "event": "session_start", '
            old += '"session": "old12345", "source": "startup"}\n'
            audit.write_text(old, encoding="utf-8")
            self.assertEqual(
                run_hook(start_payload(project, model=MODEL_NAME), project, scratch).returncode,
                0,
            )
            text = audit.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(old), "the older bytes are untouched")
            lines = start_lines(project)
            self.assertEqual(len(lines), 2)
            self.assertNotIn("model", lines[0])
            self.assertEqual(lines[1]["model"], MODEL_NAME)


class TestTheLiveViewLine(unittest.TestCase):
    """T131. One line, one URL, one command, and a caveat that is load-bearing."""

    def test_the_line_names_the_url_the_caveat_and_the_command(self) -> None:
        line = keel_session.live_view_line()
        self.assertIn("http://127.0.0.1:8770", line)
        self.assertIn("8770", line)
        self.assertIn("python scripts/keel_orchestration_dashboard.py --dir .", line)
        self.assertIn("next port", line, "the walk-plus-one caveat is not optional")
        self.assertEqual(len(line.splitlines()), 1, "ONE line, not a paragraph")

    def test_the_command_it_prints_names_a_file_that_exists(self) -> None:
        script = REPO_ROOT / "scripts" / "keel_orchestration_dashboard.py"
        self.assertTrue(script.exists(), "a start command nobody can run is worse than none")
        self.assertIn(script.name, keel_session.LIVE_VIEW_COMMAND)

    def test_the_port_is_a_constant_and_never_derived(self) -> None:
        """R19, upheld: no port is computed from the project path or the user.
        Two different projects therefore get the SAME line, byte for byte."""
        self.assertEqual(keel_session.LIVE_VIEW_URL, "http://127.0.0.1:8770")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first, second = root / "alpha", root / "beta-with-a-longer-name"
            first.mkdir()
            second.mkdir()
            saved = os.getcwd()
            lines = []
            try:
                for project in (first, second):
                    os.chdir(project)
                    lines.append(keel_session.live_view_line())
            finally:
                os.chdir(saved)
            self.assertEqual(lines[0], lines[1])

    def test_the_hook_reaches_nothing_outside_the_project_to_build_it(self) -> None:
        """The cross-project registry under the user's home is NOT adopted
        (owner re-affirmed the park 2026-08-13). Asserted on the source, since
        the guarantee is 'never reaches there', not 'did not this time'."""
        source = SESSION_SOURCE.read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith("#")
        )
        for reach in ("Path.home(", "expanduser(", "USERPROFILE", "HOMEPATH"):
            self.assertNotIn(reach, code, f"{reach} would leave this repository")

    def test_the_line_is_injected_into_a_real_sessions_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            result = run_hook(start_payload(project), project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            matching = [
                line
                for line in result.stdout.splitlines()
                if keel_session.LIVE_VIEW_TAG in line
            ]
            self.assertEqual(len(matching), 1, "exactly one live-view line")
            self.assertIn(keel_session.LIVE_VIEW_URL, matching[0])
            self.assertIn(keel_session.LIVE_VIEW_COMMAND, matching[0])

    def test_it_carries_its_own_tag_and_does_not_join_the_castoff_five(self) -> None:
        """A skill that counts orientation facts must not find a sixth one."""
        self.assertNotIn(keel_session.ORIENTATION_TAG + ":", keel_session.live_view_line())
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            adopt(project)
            self.assertEqual(len(keel_session.orientation_lines(project, {})), 5)

    def test_nothing_is_written_outside_the_project(self) -> None:
        """A session start in a scratch project leaves ONE file behind: its own
        audit log. No registry, nowhere else."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            self.assertEqual(run_hook(start_payload(project), project, scratch).returncode, 0)
            written = sorted(
                str(path.relative_to(project)).replace("\\", "/")
                for path in project.rglob("*")
                if path.is_file()
            )
            self.assertEqual(
                written,
                [".keel/audit/keel-audit.jsonl", ".keel/keel-policy.md"],
            )


class TestTheFailurePolicySurvivesBothAdditions(unittest.TestCase):
    """FAIL-OPEN, in both directions: a throw anywhere still exits 0, and one
    broken part of the context never blanks another."""

    def test_a_throwing_audit_write_still_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            adopt(project)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id=SESSION,
                raw={"model": MODEL_NAME},
            )
            original = keel_session.append_audit

            def boom(*_args: Any, **_kwargs: Any) -> None:
                raise OSError("deliberate fault: the audit directory is unwritable")

            keel_session.append_audit = boom
            stream = io.StringIO()
            try:
                with no_real_fleet_registry(), no_real_hook_error_log():
                    self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
            finally:
                keel_session.append_audit = original

    def test_a_throwing_redactor_costs_the_line_its_redaction_not_the_session(self) -> None:
        original = keel_session.redact

        def boom(_value: Any) -> str:
            raise RuntimeError("deliberate fault in the screen")

        keel_session.redact = boom
        try:
            line = keel_session.live_view_line()
        finally:
            keel_session.redact = original
        self.assertIn(keel_session.LIVE_VIEW_URL, line)
        self.assertIn(keel_session.LIVE_VIEW_COMMAND, line)

    def test_a_broken_model_reader_never_reaches_the_session(self) -> None:
        """``model_of`` is called from ``start_record``, inside ``run``'s own
        fail-open handler. Even if it threw, the return code stays 0."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            adopt(project)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id=SESSION, raw={}
            )
            original = keel_session.model_of

            def boom(_raw: Any) -> str:
                raise RuntimeError("deliberate fault reading the seat")

            keel_session.model_of = boom
            try:
                with no_real_fleet_registry(), no_real_hook_error_log():
                    self.assertEqual(keel_session.run(event, stdout=io.StringIO(), env={}), 0)
            finally:
                keel_session.model_of = original

    def test_a_screen_that_fails_on_the_seat_costs_the_seat_and_nothing_else(self) -> None:
        """The whole injection survives a redact fault while the seat is being
        resolved.

        The premise this fixture owns, stated rather than implied: the screen
        raises for the PAYLOAD values ``start_record`` puts through it - the
        model and the source - and works for everything else. That is the
        fault under test, because ``start_record`` runs at the top of ``run``,
        before one context line has been printed, so an escape there would
        take the plan-path line, the orientation block, the live-view line and
        the knowledge index down with it - four losses to pay for one field.

        What must hold instead: the seat is an honest ``null`` (absence, never
        an unscreened or invented name), the ``session_start`` line is still
        written, and every injected line is still there.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            adopt(project)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id=SESSION,
                raw={"source": "startup", "model": MODEL_NAME},
            )
            original_redact = keel_session.redact
            original_index = keel_session.knowledge_lines
            payload_values = {MODEL_NAME, "startup"}

            def selective(value: Any) -> str:
                if value in payload_values:
                    raise RuntimeError("deliberate fault screening a payload value")
                return original_redact(value)

            def one_record(_cwd: Path) -> list[str]:
                return ["k1 2026-08-13 note a record this project holds"]

            keel_session.redact = selective
            keel_session.knowledge_lines = one_record
            stream = io.StringIO()
            try:
                with no_real_fleet_registry():
                    self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
            finally:
                keel_session.redact = original_redact
                keel_session.knowledge_lines = original_index

            line = start_lines(project)[0]
            self.assertIn("model", line, "the session_start line is still written")
            self.assertIsNone(line["model"], "an unscreenable seat is absence, not a name")
            self.assertNotIn(
                "source", line, "an unscreened payload value is dropped, never written raw"
            )

            printed = stream.getvalue()
            self.assertIn(".keel/plans/keel-plan-", printed, "the plan-path line survives")
            self.assertEqual(
                printed.count(keel_session.ORIENTATION_TAG),
                5,
                "all five orientation lines survive",
            )
            self.assertIn(keel_session.LIVE_VIEW_TAG, printed, "the live-view line survives")
            self.assertIn("a record this project holds", printed, "the index survives")

    def test_the_seat_is_null_when_the_screen_fails_on_it(self) -> None:
        """``model_of`` alone: never raises, and answers absence."""
        original = keel_session.redact

        def boom(_value: Any) -> str:
            raise RuntimeError("deliberate fault in the screen")

        keel_session.redact = boom
        try:
            self.assertIsNone(keel_session.model_of({"model": MODEL_NAME}))
            self.assertIsNone(keel_session.model_of({"model": {"id": "opus-5"}}))
        finally:
            keel_session.redact = original

    def test_a_broken_knowledge_index_still_leaves_the_live_view_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            adopt(project)
            event = keel_events.KeelEvent(
                kind="session_start", cwd=project, session_id=SESSION, raw={}
            )
            original = keel_session.knowledge_lines

            def boom(_cwd: Path) -> list[str]:
                raise RuntimeError("deliberate fault reading the index")

            keel_session.knowledge_lines = boom
            stream = io.StringIO()
            try:
                with no_real_fleet_registry(), no_real_hook_error_log():
                    self.assertEqual(keel_session.run(event, stdout=stream, env={}), 0)
            finally:
                keel_session.knowledge_lines = original
            self.assertIn(keel_session.LIVE_VIEW_TAG, stream.getvalue())

    def test_a_malformed_payload_still_exits_zero_through_the_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            result = run_hook(
                {"hook_event_name": "SessionStart", "session_id": SESSION,
                 "cwd": str(project), "model": {"unreadable": ["shape"]}},
                project,
                scratch,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(start_lines(project)[0]["model"])


#: A model name in the spelling a TRANSCRIPT carries it, distinct from
#: ``MODEL_NAME`` on purpose: every case below that supplies both a payload
#: model and a transcript model must be able to say WHICH one was recorded, and
#: two equal strings cannot.
TRANSCRIPT_MODEL = "claude-fable-5"


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


def padding_lines(total_bytes: int) -> list[str]:
    """Enough model-less transcript lines to push earlier ones past a bound.

    Sized in BYTES rather than in a line count, because the thing under test is
    a byte ceiling: the caller says how many bytes of tail it wants occupied and
    this returns lines that occupy at least that many.
    """
    filler = transcript_line(None)
    cost = len(filler.encode("utf-8")) + 1
    return [filler] * (total_bytes // cost + 1)


class TestTheTranscriptFallbackNamesTheSeat(unittest.TestCase):
    """T337 capture half. The harness stopped supplying ``model`` on
    SessionStart, so every start line read ``null`` and the board's Captain card
    read "model unrecorded" for every session ever recorded.

    The fallback reads the seat from the other end - the newest ``message.model``
    in the session's OWN transcript, whose path the payload hands over - and the
    two directions asserted throughout this class are the whole point: a
    transcript that names a model must produce a real string, and every way a
    transcript can fail to name one must produce exactly the ``null`` this
    record carried before the fallback existed.
    """

    def record_for(self, transcript: Path | None, **extra: Any) -> dict[str, Any]:
        """The record for a payload naming ``transcript`` and no model."""
        raw: dict[str, Any] = dict(extra)
        if transcript is not None:
            raw["transcript_path"] = str(transcript)
        return start_record_for(raw)

    # ------------------------------------------------------------------ found

    def test_a_silent_payload_takes_the_model_from_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_the_newest_model_carrying_line_wins(self) -> None:
        """Read from the END: a resumed session records what is answering now,
        not whatever opened it."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line("claude-opus-4-8"),
                    transcript_line(None, role="user"),
                    transcript_line(TRANSCRIPT_MODEL),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_a_malformed_newer_line_does_not_hide_an_older_good_one(self) -> None:
        """A bounded tail read makes half-lines ORDINARY, so one unparseable
        line may not stop the walk before a good line older than it."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    '{"type": "assistant", "message": {"model": "trunc',
                    "not json at all",
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_lines_that_name_no_model_are_skipped_not_treated_as_absence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line(None, role="user"),
                    json.dumps({"type": "summary", "summary": "no message key"}),
                    json.dumps({"type": "x", "message": "not a mapping"}),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    # ------------------------------------------------------- attribution only

    def test_a_model_on_a_line_that_is_not_the_assistants_is_refused(self) -> None:
        """A stray ``model`` key on somebody else's line is not evidence of who
        is answering, so it is refused rather than recorded.

        This is the wrong-but-green path the silent-failure review found: the
        walk once accepted ``message.model`` from ANY line. MEASURED against
        four real transcripts on this machine: no non-assistant line carries a
        model at all, so refusing them costs nothing real.
        """
        for entry in (
            {"type": "user", "message": {"role": "user", "model": "not-the-seat"}},
            {"type": "system", "message": {"role": "system", "model": "not-the-seat"}},
            {"message": {"model": "not-the-seat"}},
            {"type": "tool_result", "message": {"model": "not-the-seat"}},
        ):
            with self.subTest(entry=entry):
                with tempfile.TemporaryDirectory() as tmp:
                    transcript = write_transcript(
                        Path(tmp) / "session.jsonl", [json.dumps(entry)]
                    )
                    self.assertIsNone(
                        self.record_for(transcript)["model"],
                        "an unattributable model is a null, never a seat",
                    )

    def test_either_assistant_marker_alone_is_enough(self) -> None:
        """Real lines set BOTH ``type`` and ``role``; accepting either alone is
        what keeps this fallback working if the harness ever drops one."""
        for entry in (
            {"type": "assistant", "message": {"model": TRANSCRIPT_MODEL}},
            {"message": {"role": "assistant", "model": TRANSCRIPT_MODEL}},
            {"type": "assistant", "message": {"role": "assistant",
                                              "model": TRANSCRIPT_MODEL}},
        ):
            with self.subTest(entry=entry):
                with tempfile.TemporaryDirectory() as tmp:
                    transcript = write_transcript(
                        Path(tmp) / "session.jsonl", [json.dumps(entry)]
                    )
                    self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_an_unattributable_newer_line_does_not_shadow_the_assistants(self) -> None:
        """The refusal SKIPS rather than stops: a stray model on a newer,
        unattributable line must not hide the assistant's own older one."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    json.dumps(
                        {"type": "user", "message": {"role": "user", "model": "not-the-seat"}}
                    ),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_the_assistant_marker_values_are_the_modules_own(self) -> None:
        self.assertEqual(keel_session.TRANSCRIPT_ASSISTANT, "assistant")
        self.assertEqual(keel_session.TRANSCRIPT_TYPE_KEY, "type")
        self.assertEqual(keel_session.TRANSCRIPT_ROLE_KEY, "role")

    # ------------------------------------------------------------- the ceiling

    def test_the_tail_bound_is_the_modules_own_constant(self) -> None:
        """Spelled out here rather than imported into the arithmetic below: a
        guard that takes its expected value from the code under test cannot see
        that code change."""
        self.assertEqual(keel_session.TRANSCRIPT_TAIL_BYTES, 65536)

    def test_a_model_named_inside_the_tail_bound_is_found(self) -> None:
        """The near side of the ceiling, so the far side below is known to be
        the BOUND biting rather than the reader simply never working."""
        bound = keel_session.TRANSCRIPT_TAIL_BYTES
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                padding_lines(bound * 2)
                + [transcript_line(TRANSCRIPT_MODEL)]
                + padding_lines(bound // 2),
            )
            self.assertGreater(
                transcript.stat().st_size, bound, "premise: the file exceeds the bound"
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_a_model_named_beyond_the_tail_bound_is_not_found(self) -> None:
        """THE CEILING. The only line naming a model sits further back than
        ``TRANSCRIPT_TAIL_BYTES``, so a bounded reader must NOT find it and the
        seat must stay null. This is the case that fails if the read ever
        becomes a whole-file scan - which is the thing a session-start hook may
        not do to a file that can be tens of megabytes."""
        bound = keel_session.TRANSCRIPT_TAIL_BYTES
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line(TRANSCRIPT_MODEL)] + padding_lines(bound * 2),
            )
            self.assertGreater(
                transcript.stat().st_size,
                bound * 2,
                "premise: the naming line is far outside the tail",
            )
            record = self.record_for(transcript)
            self.assertIn("model", record)
            self.assertIsNone(record["model"], "a bounded reader misses it, and says so")

    def test_the_read_never_takes_more_than_the_bound(self) -> None:
        """The guarantee as arithmetic rather than as an outcome: whatever the
        file's size, the bytes returned fit the limit."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", padding_lines(40_000)
            )
            for limit in (0, 1, 512, 4096, keel_session.TRANSCRIPT_TAIL_BYTES):
                with self.subTest(limit=limit):
                    lines = keel_session.transcript_tail_lines(transcript, limit)
                    spent = sum(len(line.encode("utf-8")) + 1 for line in lines)
                    self.assertLessEqual(spent, limit)

    def test_a_partial_first_line_is_dropped_rather_than_parsed(self) -> None:
        """Half a JSON object is not a line. The cut lands at an arbitrary
        offset, so the first line of a truncated read is discarded - and the
        whole file's first line is NOT, when the file fitted inside the bound."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line(TRANSCRIPT_MODEL), transcript_line("second")],
            )
            whole = keel_session.transcript_tail_lines(transcript, 10 ** 6)
            self.assertEqual(len(whole), 2, "nothing is dropped when nothing was cut")
            size = transcript.stat().st_size
            cut = keel_session.transcript_tail_lines(transcript, size // 2)
            self.assertTrue(all(line.startswith("{") for line in cut), cut)
            self.assertTrue(all(json.loads(line) for line in cut), "every line parses")

    # ------------------------------------------------------------------- nulls

    def test_a_payload_with_no_transcript_path_is_still_null(self) -> None:
        record = self.record_for(None)
        self.assertIn("model", record)
        self.assertIsNone(record["model"])

    def test_a_blank_or_non_string_transcript_path_is_still_null(self) -> None:
        for value in ("", "   ", 5, True, [], {}, None):
            with self.subTest(value=value):
                self.assertIsNone(start_record_for({"transcript_path": value})["model"])

    def test_an_absent_transcript_file_is_still_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nothing" / "session.jsonl"
            self.assertFalse(missing.exists(), "premise: the file is not there")
            self.assertIsNone(self.record_for(missing)["model"])

    def test_a_directory_where_a_transcript_should_be_is_still_null(self) -> None:
        """The read raises ``IsADirectoryError``/``PermissionError`` depending
        on the platform, which is exactly why the caller catches everything."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(self.record_for(Path(tmp))["model"])

    def test_an_empty_transcript_is_still_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(Path(tmp) / "session.jsonl", [])
            self.assertEqual(transcript.stat().st_size, 0, "premise: the file is empty")
            self.assertIsNone(self.record_for(transcript)["model"])

    def test_an_all_malformed_transcript_is_still_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", ["not json", "[]", "null", "{", "12"]
            )
            self.assertIsNone(self.record_for(transcript)["model"])

    def test_a_transcript_model_of_the_wrong_type_is_still_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for value in ("", "   ", 5, True, [], {"id": "opus"}, None):
                with self.subTest(value=value):
                    transcript = write_transcript(
                        Path(tmp) / "session.jsonl",
                        [json.dumps({"message": {"model": value}})],
                    )
                    self.assertIsNone(self.record_for(transcript)["model"])

    def test_a_broken_screen_leaves_the_transcript_seat_null(self) -> None:
        """``_screened`` is where the name goes through, so a screen that
        raises yields absence - never an unscreened name."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            original = keel_session.redact

            def boom(_value: Any) -> str:
                raise RuntimeError("deliberate fault in the screen")

            keel_session.redact = boom
            try:
                self.assertIsNone(
                    keel_session.model_from_transcript({"transcript_path": str(transcript)})
                )
            finally:
                keel_session.redact = original

    # ------------------------------------------------- absence, never failure

    def test_a_supplied_payload_model_is_never_second_guessed(self) -> None:
        """The order is fixed: the payload wins where it names anything, and
        the transcript is not even read."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            record = self.record_for(transcript, model=MODEL_NAME)
            self.assertEqual(record["model"], MODEL_NAME)
            self.assertNotEqual(
                record["model"], TRANSCRIPT_MODEL, "the transcript did not override it"
            )

    def test_an_object_shaped_payload_model_still_wins_over_the_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            record = self.record_for(transcript, model={"id": "opus-5"})
            self.assertEqual(record["model"], "opus-5")

    def test_an_unscreenable_payload_model_stays_null_and_does_not_fall_through(
        self,
    ) -> None:
        """THE DISTINCTION THE FALLBACK MUST NOT BLUR. The payload named a
        model; the screen refused it. Answering from the transcript instead
        would report a name for a seat whose supplied name keel had just
        declined to write - so this stays null, exactly as it did before the
        fallback existed.

        The premise this fixture owns: the screen raises for the PAYLOAD's name
        and works for the transcript's, so a fall-through would be visible as
        the transcript's model rather than as another null.
        """
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            original = keel_session.redact

            def selective(value: Any) -> str:
                if value == MODEL_NAME:
                    raise RuntimeError("deliberate fault screening the payload's name")
                return original(value)

            keel_session.redact = selective
            try:
                seat = keel_session.model_of(
                    {"model": MODEL_NAME, "transcript_path": str(transcript)}
                )
            finally:
                keel_session.redact = original
            self.assertIsNone(seat, "a refused screen is not an absent field")

    # --------------------------------------------------- through the launcher

    def test_a_real_session_start_records_the_transcripts_model(self) -> None:
        """What a harness would actually get: bytes on disk, written by a
        subprocess, for a payload shaped exactly like the ones this machine
        sends - a transcript path and no model."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            transcript = write_transcript(
                root / "transcripts" / f"{SESSION}.jsonl",
                [transcript_line(None, role="user"), transcript_line(TRANSCRIPT_MODEL)],
            )
            result = run_hook(
                start_payload(project, transcript_path=str(transcript)), project, scratch
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = start_lines(project)
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0]["model"], TRANSCRIPT_MODEL)

    def test_an_unreadable_transcript_leaves_a_healthy_hook_and_a_null(self) -> None:
        """The fail-safe direction end to end: the hook exits 0, the start line
        is still written, and the seat is the same JSON null it always was."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            scratch.mkdir()
            adopt(project)
            result = run_hook(
                start_payload(project, transcript_path=str(root / "gone.jsonl")),
                project,
                scratch,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIsNone(start_lines(project)[0]["model"])
            self.assertIn(
                '"model": null',
                project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8"),
                "the null is written as JSON null, not as the string 'None'",
            )

    def test_the_transcript_path_itself_never_reaches_the_record(self) -> None:
        """The path is read and forgotten: it is somebody's home directory in
        production, and this record holds no field for it."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl", [transcript_line(TRANSCRIPT_MODEL)]
            )
            record = self.record_for(transcript)
            self.assertNotIn("transcript_path", record)
            self.assertNotIn(str(transcript), json.dumps(record))


class TestASyntheticLineIsSkippedNotReturned(unittest.TestCase):
    """T482/BL39. MEASURED 2026-09-04: the harness writes a literal placeholder
    into ``message.model`` on an assistant line IT authored - an API
    spend-limit error, "No response requested." twice - rather than a model
    that produced the line, and none of the three measured lines was marked
    ``isSidechain``. The ordinary sequence "an API failure kills a delegation,
    the harness writes a synthetic assistant line, the session stops, the stop
    hook reads the newest assistant line" would otherwise make keel record the
    seat as ``<synthetic>`` - a name, not an absence, and a wrong one.

    ``model_from_transcript`` treats a value with that SHAPE - wrapped in
    angle brackets - as absent and continues walking to the assistant line
    before it, so a real model one line older is still found; every case here
    is one direction of that rule.
    """

    def record_for(self, transcript: Path) -> dict[str, Any]:
        return start_record_for({"transcript_path": str(transcript)})

    def test_a_synthetic_newest_line_is_skipped_and_the_real_model_beneath_it_wins(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line(keel_session.PLACEHOLDER_MODEL_EXAMPLE),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_two_stacked_synthetic_lines_still_yield_the_real_model_beneath_them(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line(keel_session.PLACEHOLDER_MODEL_EXAMPLE),
                    transcript_line(keel_session.PLACEHOLDER_MODEL_EXAMPLE),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_when_every_assistant_line_is_synthetic_the_seat_is_none_not_the_placeholder(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(keel_session.PLACEHOLDER_MODEL_EXAMPLE),
                    transcript_line(keel_session.PLACEHOLDER_MODEL_EXAMPLE),
                ],
            )
            self.assertIsNone(
                keel_session.model_from_transcript({"transcript_path": str(transcript)}),
                "a placeholder is never the seat, even when it is all there is",
            )

    def test_the_newest_of_several_different_real_models_still_wins(self) -> None:
        """Real, measured: a session carried claude-fable-5-1, claude-fable-5,
        claude-opus-5 and claude-opus-4-8 as the seat changed model mid-session.
        The walk must still return the newest of the four, synthetic lines or
        not - this case has none, to isolate NEWEST WINS from the placeholder
        rule the other cases in this class exercise."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line("claude-opus-4-8"),
                    transcript_line("claude-opus-5"),
                    transcript_line("claude-fable-5"),
                    transcript_line("claude-fable-5-1"),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], "claude-fable-5-1")

    def test_an_angle_bracketed_value_other_than_synthetic_is_skipped_too(self) -> None:
        """The SHAPE is the test, not one spelling: a placeholder the harness
        has not been measured writing yet is still refused if it has the same
        shape as the one that was."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line("<some-other-placeholder>"),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)


class TestWhitespaceDoesNotDefeatThePlaceholderShapeTest(unittest.TestCase):
    """``_text`` normalises only its OWN truthiness test (``value.strip()``)
    and returns the payload value UNSTRIPPED, so a placeholder padded with
    whitespace would reach ``_is_placeholder_model`` exactly as written and
    defeat a test anchored at the string's own ends unless that function
    strips its own local copy before testing the shape. Each case here pins
    one edge of that fix.
    """

    def record_for(self, transcript: Path) -> dict[str, Any]:
        return start_record_for({"transcript_path": str(transcript)})

    def test_a_placeholder_padded_with_leading_and_trailing_spaces_is_skipped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line(" <synthetic> "),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_a_placeholder_padded_with_a_tab_and_a_newline_is_also_skipped(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [
                    transcript_line(TRANSCRIPT_MODEL),
                    transcript_line("\t<synthetic>\n"),
                ],
            )
            self.assertEqual(self.record_for(transcript)["model"], TRANSCRIPT_MODEL)

    def test_a_legitimately_padded_real_model_is_still_returned(self) -> None:
        """Pins that this fix did not change what is RECORDED for a real
        model: ``_is_placeholder_model`` only decides whether the SHAPE is a
        placeholder, and the padded value itself still flows through
        ``_text``, ``model_from_transcript`` and ``_screened`` unchanged."""
        with tempfile.TemporaryDirectory() as tmp:
            transcript = write_transcript(
                Path(tmp) / "session.jsonl",
                [transcript_line(" claude-opus-5 ")],
            )
            self.assertEqual(self.record_for(transcript)["model"], " claude-opus-5 ")


if __name__ == "__main__":
    unittest.main()
