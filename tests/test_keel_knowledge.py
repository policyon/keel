#!/usr/bin/env python3
"""Phase 2 test suite - capture queue, exclusion, index, retrieval, injection.

Contract
--------
Reads   : ``tests/fixtures/private/*.json`` (the eight marker cases),
          ``tests/fixtures/knowledge/*.md`` (example records that the record
          checker must pass), the conformance kit in ``tests/contracts/``,
          and the sources of the Phase 2 files for their declared-policy
          assertions.
Emits   : unittest results only. One test prints the injected block so the
          cap can be read in the log rather than taken on trust.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with an environment carrying no ``KEEL_*`` variable
          except the one the case is about, so a developer's own shell cannot
          change what a test observes.

House style: the pipeline is exercised end to end the way it runs - the hook
as a real subprocess with JSON on stdin, the command line as
``python scripts/keel.py <command>`` - so the exit codes asserted here are
the exit codes a caller gets.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it. The FTS5 case is the deliberate
exception in shape only - where FTS5 is genuinely absent the fallback is what
ships, so the case asserts the PROBE's verdict rather than assuming one.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Subprocess is invoked with an
argument list, never a shell string (R5). Every file operation names its
encoding (convention 6).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
KEEL_CLI = REPO_ROOT / "scripts" / "keel.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
QUEUE_RELPATH = (".keel", "queue", "keel-observations.jsonl")
CACHE_RELPATH = (".keel", "cache")

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "tests" / "contracts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_chart  # noqa: E402
import keel_index  # noqa: E402
import keel_records  # noqa: E402
import keel_redact  # noqa: E402
import keel_search_contract  # noqa: E402
import keel_session  # noqa: E402
from keel_registry_guard import (  # noqa: E402
    no_real_fleet_registry,
    no_real_hook_error_log,
)

#: A record, as the distillation skill is instructed to write one. The schema
#: is not restated here: this is the shape, and keel_records is the authority.
RECORD_TEMPLATE = """---
name: {stem}
description: {description}
type: {record_type}
status: ratified
generated: {{ by: "machine:executor-deep", at: "{generated}" }}
{verified}cites: []
---

{body}
"""

#: A ratified decision must name who ratified it; a knowledge record need not.
VERIFIED_EMPTY = "verified: []\n"
VERIFIED_BY_HUMAN = 'verified:\n  - {{ by: "human:operator", at: "{generated}" }}\n'


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    ``HOME``/``USERPROFILE`` default to ``scratch`` rather than the real
    ones - a ``session`` launch against an adopted project feeds keel's
    user-global fleet registry (T227), which reads ``Path.home()`` no matter
    what this scrub does to ``KEEL_*``. A caller that already hands down its
    own fixture ``HOME``/``USERPROFILE`` via ``extra`` still wins, since
    those are applied last.
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


def write_record(
    project: Path,
    stem: str,
    *,
    directory: str = "knowledge",
    description: str = "One fact, stated once.",
    record_type: str = "knowledge",
    generated: str = "2026-08-01",
    body: str = "The body of the record.",
) -> Path:
    """Write one schema-conforming record into a project, and return its path."""
    target = project / ".keel" / directory / f"{stem}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    verified = (
        VERIFIED_BY_HUMAN.format(generated=generated)
        if record_type == "decision"
        else VERIFIED_EMPTY
    )
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            RECORD_TEMPLATE.format(
                stem=stem,
                description=description,
                record_type=record_type,
                generated=generated,
                verified=verified,
                body=body,
            )
        )
    return target


def run_hook(subcommand: str, payload: dict[str, Any], project: Path, scratch: Path,
             **env_extra: str) -> subprocess.CompletedProcess:
    """Run one hook subcommand as the harness runs it: subprocess, JSON stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), subcommand],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch, **env_extra),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def run_cli(args: list[str], scratch: Path, **env_extra: str) -> subprocess.CompletedProcess:
    """Run the command line as a caller does, and return the whole result."""
    return subprocess.run(
        [sys.executable, "-B", str(KEEL_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch, **env_extra),
        cwd=str(scratch),
        timeout=120,
        check=False,
    )


# ------------------------------------------------------- the private marker


def load_private_fixtures() -> list[tuple[str, dict]]:
    """The eight marker cases, in filename order."""
    directory = FIXTURE_ROOT / "private"
    found = [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(directory.glob("*.json"))
    ]
    if not found:
        raise RuntimeError(f"no fixtures in {directory}")
    return found


class TestPrivateMarkerFixtures(unittest.TestCase):
    """R10: the marker is case-insensitive, and an unclosed one is visible."""

    def _check(self, fixture: dict) -> None:
        from contextlib import redirect_stderr  # noqa: PLC0415 - used here only
        from io import StringIO  # noqa: PLC0415

        captured = StringIO()
        with redirect_stderr(captured):
            result = keel_redact.strip_private(fixture["input"])
        self.assertEqual(result, fixture["expect_output"], fixture["description"])
        warned = keel_redact.UNCLOSED_PRIVATE_WARNING in captured.getvalue()
        self.assertEqual(warned, fixture["expect_warning"], captured.getvalue())

    def test_the_eight_cases_ship(self) -> None:
        """The set is eight; a shrinking fixture set is how a rule dies."""
        self.assertEqual(len(load_private_fixtures()), 8)

    def test_exactly_one_case_is_the_unclosed_one(self) -> None:
        warnings = [f["expect_warning"] for _, f in load_private_fixtures()]
        self.assertEqual(warnings.count(True), 1)

    def test_unmarked_text_is_returned_byte_for_byte(self) -> None:
        """The allow direction (convention 2): an unmarked value is untouched."""
        for value in ("nothing marked here", "a mention of keel-private in prose", ""):
            with self.subTest(value=value):
                self.assertEqual(keel_redact.strip_private(value), value)

    def test_non_strings_pass_through(self) -> None:
        for value in (None, 3, ["x"], {"a": 1}):
            with self.subTest(value=value):
                self.assertIs(keel_redact.strip_private(value), value)

    def test_redact_applies_the_exclusion(self) -> None:
        """Convention 5 in one call: every writer that redacts also excludes."""
        self.assertEqual(
            keel_redact.redact("keep <keel-private>drop</keel-private> keep"),
            "keep  keep",
        )


def _attach_private_cases() -> None:
    """One named test method per fixture file."""
    for stem, fixture in load_private_fixtures():
        name = "test_" + re.sub(r"[^0-9a-zA-Z]+", "_", stem)

        def method(self: TestPrivateMarkerFixtures, fixture: dict = fixture) -> None:
            self._check(fixture)

        method.__doc__ = f"private fixture {stem}: {fixture['description']}"
        setattr(TestPrivateMarkerFixtures, name, method)


_attach_private_cases()


# ------------------------------------------------------- the capture queue


class TestObservationQueue(unittest.TestCase):
    """Capture also appends to the queue - without changing what it audits."""

    def _project(self, root: Path) -> tuple[Path, Path]:
        project, scratch = root / "project", root / "tmp"
        (project / ".keel").mkdir(parents=True)
        scratch.mkdir()
        return project, scratch

    def _queue(self, project: Path) -> list[dict]:
        path = project.joinpath(*QUEUE_RELPATH)
        if not path.is_file():
            return []
        raw = path.read_bytes()
        self.assertNotIn(b"\r", raw, "the queue must be LF-only JSONL")
        return [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]

    def test_a_write_queues_one_redacted_observation(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            result = run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(project / "src" / "app.py")},
                    "session_id": session,
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "", "an observer that speaks is not an observer")
            lines = self._queue(project)
            self.assertEqual(len(lines), 1, lines)
            line = lines[0]
            self.assertEqual(line["v"], 1)
            self.assertRegex(line["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertEqual(line["session"], session)
            self.assertEqual(line["tool"], "Write")
            self.assertEqual(line["paths"], ["src/app.py"])
            self.assertIn("src/app.py", line["action"])
            self.assertNotIn(str(project), json.dumps(line), "a queue line leaked a real path")

    def test_a_shell_command_queues_its_head_and_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git status --short"},
                    "tool_response": {"stdout": "SECRET-OUTPUT-VALUE"},
                    "session_id": "s",
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            lines = self._queue(project)
            self.assertEqual(len(lines), 1, lines)
            self.assertIn("git status", lines[0]["action"])
            self.assertNotIn(
                "SECRET-OUTPUT-VALUE", json.dumps(lines[0]), "a payload body reached the queue"
            )

    def test_a_delegation_queues_once_on_return_not_on_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            payload = {
                "tool_name": "Task",
                "tool_input": {
                    "subagent_type": "executor",
                    "description": "port the index builder",
                    "prompt": "A LONG PROMPT BODY THAT MUST NOT BE QUEUED",
                },
                "session_id": "s",
                "cwd": str(project),
            }
            run_hook("capture", {**payload, "hook_event_name": "PreToolUse"}, project, scratch)
            self.assertEqual(self._queue(project), [], "the launch half is not an observation")
            run_hook("capture", {**payload, "hook_event_name": "PostToolUse"}, project, scratch)
            lines = self._queue(project)
            self.assertEqual(len(lines), 1, lines)
            self.assertIn("executor", lines[0]["action"])
            self.assertNotIn("LONG PROMPT BODY", json.dumps(lines[0]))

    def test_an_unobserved_tool_queues_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Read",
                    "tool_input": {"file_path": "src/app.py"},
                    "session_id": "s",
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            self.assertEqual(self._queue(project), [])

    def test_an_unadopted_project_is_left_alone(self) -> None:
        """R25 for the queue too: no .keel/, no writes of any kind."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            project.mkdir()
            scratch.mkdir()
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.py"},
                    "session_id": "s",
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            self.assertEqual(list(project.iterdir()), [], "project must be untouched")

    def test_marked_content_never_reaches_the_queue(self) -> None:
        """R10 where it matters: the exclusion runs before the write."""
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "deploy --token <keel-private>SECRET-TOKEN</keel-private> now"
                    },
                    "session_id": "s",
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            payload = json.dumps(self._queue(project))
            self.assertNotIn("SECRET-TOKEN", payload)
            self.assertIn("deploy --token", payload)

    def test_the_audit_line_is_unchanged_by_the_extension(self) -> None:
        """The queue is additive: the audit record keeps its wire shape."""
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp))
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.py"},
                    "session_id": "s",
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            audit = project.joinpath(".keel", "audit", "keel-audit.jsonl")
            lines = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([line["event"] for line in lines], ["activity"])
            self.assertEqual(lines[0]["detail"], "src/app.py")


# -------------------------------------------------------------- the index


class TestIndex(unittest.TestCase):
    """The derived cache: rebuild, status, and the deletable-cache promise."""

    def _seeded(self, root: Path) -> Path:
        project = root / "project"
        write_record(project, "keel-index-rebuild", description="Rebuilding is idempotent.",
                     generated="2026-08-01", body="Delete the cache and derive it again.")
        write_record(project, "keel-cache-is-deletable", directory="decisions",
                     record_type="decision", description="The index is a cache.",
                     generated="2026-07-30", body="Nothing depends on the cache surviving.")
        return project

    def test_rebuild_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            first = keel_index.rebuild(project)
            second = keel_index.rebuild(project)
            self.assertEqual(first, second)
            self.assertEqual(first["records"], 2)

    def test_deleting_the_whole_cache_directory_is_lossless(self) -> None:
        """The design law, tested: the cache may be deleted at any time."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            keel_index.rebuild(project)
            with keel_index.open_index(project) as index:
                before = [hit.line() for hit in index.search("cache")]
                summaries_before = [hit.line() for hit in index.summaries()]
            shutil.rmtree(project.joinpath(*CACHE_RELPATH))
            self.assertFalse(project.joinpath(*CACHE_RELPATH).exists())
            keel_index.rebuild(project)
            with keel_index.open_index(project) as index:
                self.assertEqual([hit.line() for hit in index.search("cache")], before)
                self.assertEqual([hit.line() for hit in index.summaries()], summaries_before)
            self.assertTrue(before, "the pre-deletion result was empty; the test proves nothing")

    def test_status_reports_an_absent_index_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            report = keel_index.status(project)
            self.assertFalse(report["present"])
            self.assertEqual(report["records_on_disk"], 2)
            self.assertIn("rebuild", keel_index.render_status(report))

    def test_status_reports_the_backend_and_the_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            keel_index.rebuild(project)
            report = keel_index.status(project)
            self.assertTrue(report["present"])
            self.assertIn(report["backend"], (keel_index.BACKEND_FTS5, keel_index.BACKEND_LIKE))
            self.assertEqual(report["records_indexed"], report["records_on_disk"])

    def test_the_probe_decides_the_backend_and_the_switch_overrides_it(self) -> None:
        """The probe is a probe: create and drop, then believe the answer."""
        conn = sqlite3.connect(":memory:")
        try:
            probed = keel_index.probe_fts5(conn, env={})
            self.assertIsInstance(probed, bool)
            self.assertFalse(keel_index.probe_fts5(conn, env={keel_index.FTS5_ENV: "off"}))
        finally:
            conn.close()
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            forced = keel_index.rebuild(project, env={keel_index.FTS5_ENV: "off"})
            self.assertEqual(forced["backend"], keel_index.BACKEND_LIKE)
            probed_result = keel_index.rebuild(project, env={})
            self.assertEqual(
                probed_result["backend"],
                keel_index.BACKEND_FTS5 if probed else keel_index.BACKEND_LIKE,
            )
            print(
                f"\nkeel index backends exercised: probe={'fts5' if probed else 'unavailable'}, "
                f"forced fallback=like"
            )

    def test_a_name_collision_qualifies_both_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            write_record(project, "keel-twin")
            write_record(project, "keel-twin", directory="decisions", record_type="decision")
            keel_index.rebuild(project)
            with keel_index.open_index(project) as index:
                identifiers = sorted(hit.id for hit in index.summaries())
            self.assertEqual(identifiers, ["decisions/keel-twin", "knowledge/keel-twin"])

    def test_an_index_line_is_never_wider_than_the_limit(self) -> None:
        hit = keel_index.Hit(id="keel-" + "x" * 60, date="2026-08-01", type="knowledge",
                             title="a description that runs on and on " * 6)
        self.assertLessEqual(len(hit.line()), keel_index.LINE_CHARS)
        self.assertTrue(hit.line().endswith("..."))

    def test_summaries_work_with_no_cache_at_all(self) -> None:
        """The injector must not depend on a derived file existing."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            self.assertFalse(keel_index.index_path(project).is_file())
            hits = keel_index.summaries(project)
            self.assertEqual([hit.id for hit in hits],
                             ["keel-index-rebuild", "keel-cache-is-deletable"])

    def test_the_cli_rebuilds_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            rebuilt = run_cli(["index", "rebuild", "--project", str(project)], Path(tmp))
            self.assertEqual(rebuilt.returncode, 0, rebuilt.stderr)
            self.assertIn("2 record(s)", rebuilt.stdout)
            status = run_cli(["index", "status", "--project", str(project)], Path(tmp))
            self.assertEqual(status.returncode, 0, status.stderr)
            self.assertIn("2 indexed / 2 on disk", status.stdout)
            self.assertNotIn(str(Path.home()), status.stdout)


class TestSearchContractOverFts5(keel_search_contract.SearchContract, unittest.TestCase):
    """The conformance kit against the probed backend (FTS5 where present)."""

    implementation = "probed"

    def build_index(self, project: Path) -> Any:
        keel_index.rebuild(project, env={})
        return keel_index.open_index(project)


class TestSearchContractOverLikeFallback(keel_search_contract.SearchContract, unittest.TestCase):
    """The same kit against the degraded backend, forced on every machine."""

    implementation = "like"

    def build_index(self, project: Path) -> Any:
        keel_index.rebuild(project, env={keel_index.FTS5_ENV: "off"})
        index = keel_index.open_index(project)
        assert index.backend == keel_index.BACKEND_LIKE
        return index


# ------------------------------------------------------------- retrieval


class TestChart(unittest.TestCase):
    """Two layers: cheap lines first, whole records only by identifier."""

    def _seeded(self, root: Path) -> Path:
        project = root / "project"
        write_record(project, "keel-injection-cap",
                     description="Injection is capped in bytes at the injector.",
                     body="The cap is enforced where the text is written, not measured later.")
        return project

    def test_layer_one_prints_one_bounded_line_per_hit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            result = run_cli(["chart", "injection", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            self.assertEqual(len(lines), 1, result.stdout)
            self.assertIn("keel-injection-cap", lines[0])
            self.assertLessEqual(len(lines[0]), keel_index.LINE_CHARS)

    def test_an_empty_result_is_words_and_exit_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            result = run_cli(["chart", "zzznothing", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(keel_chart.NO_MATCHES, result.stdout)

    def test_layer_two_prints_the_record_body(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            result = run_cli(
                ["chart", "--project", str(project), "--get", "keel-injection-cap"], Path(tmp)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("The cap is enforced where the text is written", result.stdout)
            self.assertIn(".keel/knowledge/keel-injection-cap.md", result.stdout)

    def test_an_unknown_identifier_is_reported_not_raised(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            result = run_cli(
                ["chart", "--project", str(project), "--get", "keel-nonesuch"], Path(tmp)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(keel_chart.NO_RECORD, result.stdout)

    def test_retrieval_derives_a_missing_cache_rather_than_failing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._seeded(Path(tmp))
            self.assertFalse(keel_index.index_path(project).is_file())
            result = run_cli(["chart", "injection", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("keel-injection-cap", result.stdout)
            self.assertTrue(keel_index.index_path(project).is_file())


# ------------------------------------------------------------- injection


class TestInjectionCap(unittest.TestCase):
    """R16/R34: the cap is enforced here, and overflow is never silent."""

    def test_the_cap_is_configuration_a_gate_reads(self) -> None:
        """R32: the limit is a constant with an override, not a sentence."""
        self.assertEqual(keel_session.DEFAULT_INJECT_CAP_BYTES, 4096)
        self.assertEqual(keel_session.inject_cap_bytes({}), 4096)
        self.assertEqual(keel_session.inject_cap_bytes({"KEEL_INJECT_CAP_BYTES": "512"}), 512)
        self.assertEqual(keel_session.INJECT_CAP_ENV, "KEEL_INJECT_CAP_BYTES")

    def test_an_unusable_cap_falls_back_and_says_so(self) -> None:
        from contextlib import redirect_stderr  # noqa: PLC0415
        from io import StringIO  # noqa: PLC0415

        captured = StringIO()
        with redirect_stderr(captured):
            value = keel_session.inject_cap_bytes({"KEEL_INJECT_CAP_BYTES": "lots"})
        self.assertEqual(value, keel_session.DEFAULT_INJECT_CAP_BYTES)
        self.assertIn("KEEL_INJECT_CAP_BYTES", captured.getvalue())

    def test_a_block_that_fits_carries_no_marker(self) -> None:
        lines = [f"keel-record-{n} 2026-08-01 knowledge a short title" for n in range(3)]
        block = keel_session.index_block(lines, 4096)
        self.assertNotIn("more record(s) not shown", block)
        for line in lines:
            self.assertIn(line, block)

    def test_overflow_truncates_at_a_record_boundary_and_is_visible(self) -> None:
        lines = [
            f"keel-record-{n:03d} 2026-08-01 knowledge " + "a title of some length " * 3
            for n in range(60)
        ]
        cap = 1024
        block = keel_session.index_block(lines, cap)
        encoded = block.encode("utf-8")
        self.assertLessEqual(len(encoded), cap, "the cap is hard, not advisory")
        self.assertIn("more record(s) not shown", block)
        self.assertIn("/keel:chart", block)
        kept = [line for line in block.splitlines() if line.startswith("keel-record-")]
        self.assertTrue(kept, "nothing was kept; the cap left no room at all")
        for line in kept:
            self.assertIn(line, lines, "a record line was cut in half")
        withheld = int(re.search(r"\.\.\. (\d+) more record", block).group(1))
        self.assertEqual(withheld, len(lines) - len(kept), "the overflow count must be exact")
        print(f"\ninjection at cap {cap}: {len(encoded)} bytes, "
              f"{len(kept)} of {len(lines)} records, marker present")

    def test_a_cap_too_small_for_a_single_record_still_reports_the_overflow(self) -> None:
        lines = [f"keel-record-{n} 2026-08-01 knowledge title" for n in range(5)]
        block = keel_session.index_block(lines, 90)
        self.assertLessEqual(len(block.encode("utf-8")), 90)
        self.assertIn("5 more record(s) not shown", block)

    def test_no_records_means_no_block_at_all(self) -> None:
        self.assertEqual(keel_session.index_block([], 4096), "")


class TestRoundTrip(unittest.TestCase):
    """capture -> queue -> record -> index -> retrieval -> injection."""

    def test_the_pipeline_runs_end_to_end(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            (project / ".keel").mkdir(parents=True)
            scratch.mkdir()

            # 1. capture appends one observation to the queue.
            run_hook(
                "capture",
                {
                    "hook_event_name": "PostToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(project / "scripts" / "keel_index.py")},
                    "session_id": session,
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            queue = project.joinpath(*QUEUE_RELPATH)
            self.assertTrue(queue.is_file(), "capture wrote no queue line")
            observed = json.loads(queue.read_text(encoding="utf-8").splitlines()[0])
            self.assertIn("scripts/keel_index.py", observed["paths"])

            # 2. distillation is the session's job; the record is its output.
            record = write_record(
                project,
                "keel-derived-index",
                description="The search index is derived from the record files.",
                body=f"Observed while writing {observed['paths'][0]}.",
            )
            self.assertEqual(
                keel_records.main(["--project", str(project), "--quiet"]),
                0,
                "the distilled record does not pass the schema checker",
            )

            # 3. the index derives from the files.
            result = run_cli(["index", "rebuild", "--project", str(project)], scratch)
            self.assertEqual(result.returncode, 0, result.stderr)

            # 4. retrieval finds it, at both layers.
            found = run_cli(["chart", "derived", "--project", str(project)], scratch)
            self.assertEqual(found.returncode, 0, found.stderr)
            self.assertIn("keel-derived-index", found.stdout)
            detail = run_cli(
                ["chart", "--project", str(project), "--get", "keel-derived-index"], scratch
            )
            self.assertIn(record.name, detail.stdout)

            # 5. session start injects it, under the plan line and the cap.
            started = run_hook(
                "session",
                {
                    "hook_event_name": "SessionStart",
                    "session_id": session,
                    "cwd": str(project),
                },
                project,
                scratch,
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            lines = started.stdout.splitlines()
            self.assertTrue(lines[0].startswith("[keel] This project runs under"))
            self.assertIn("knowledge index", started.stdout)
            self.assertTrue(
                any(line.startswith("keel-derived-index ") for line in lines), started.stdout
            )
            self.assertLessEqual(
                len("\n".join(lines[1:]).encode("utf-8")),
                keel_session.DEFAULT_INJECT_CAP_BYTES,
            )
            print("\ninjected at session start:\n" + "\n".join(lines[1:]))

    def test_the_injected_block_obeys_the_environment_cap(self) -> None:
        """The cap is arithmetic over the whole injected block, so every line
        in that block has to be a fact this test owns. Since T167 one of them
        is not free: the castoff conflict line counts the PreToolUse and Stop
        registrations the scan can see, INCLUDING the user's own, and a machine
        that registers another gate stack globally would make that line - and
        therefore this arithmetic - a property of the machine. The fixture home
        is handed to the subprocess the only way a subprocess takes one
        (``USERPROFILE`` on Windows, ``HOME`` elsewhere; both are set).

        THE CAP IS DERIVED, NOT TYPED, and that is a fix rather than a
        convenience. It used to be the literal 600, a number tuned to what the
        always-on lines happened to cost when this test was written; adding a
        fifth orientation line (T175's ``holds``) pushed that cost past 600 on
        its own, so the index was handed too few bytes for even its header and
        this test failed on an assertion about truncation while nothing about
        truncation had changed. Orientation is deliberately unclamped
        (``orientation_bytes``), so its cost IS a moving number and a literal
        here silently couples this test to it. The cap is now measured from the
        always-on block plus exactly enough room for a header and an overflow
        marker, which keeps the property under test - a too-small remainder
        truncates VISIBLY - true however many orientation lines exist."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project, scratch = root / "project", root / "tmp"
            (project / ".keel").mkdir(parents=True)
            scratch.mkdir()
            home = root / "fixture-home"
            (home / ".claude").mkdir(parents=True)
            # The always-on lines the injector subtracts before the index gets
            # anything, measured with this test's own project and home so the
            # premise is owned here rather than inherited from the machine.
            always_on = keel_session.orientation_bytes(
                keel_session.orientation_lines(project, {}, home=home)
            ) + keel_session.orientation_bytes([keel_session.live_view_line()])
            # Room for the index HEADER and the OVERFLOW MARKER and no more, so
            # 40 records cannot possibly fit and the marker must appear.
            index_room = (
                len(keel_session.INDEX_HEADER.format(total=40).encode("utf-8"))
                + len(keel_session.OVERFLOW_MARKER.format(more=39).encode("utf-8"))
                + 2  # the newline each of those two lines carries
            )
            cap = always_on + index_room
            for number in range(40):
                write_record(
                    project,
                    f"keel-record-{number:03d}",
                    description=f"Fact number {number} about the knowledge layer.",
                )
            started = run_hook(
                "session",
                {"hook_event_name": "SessionStart", "session_id": "abcdef123456",
                 "cwd": str(project)},
                project,
                scratch,
                KEEL_INJECT_CAP_BYTES=str(cap),
                HOME=str(home),
                USERPROFILE=str(home),
            )
            self.assertEqual(started.returncode, 0, started.stderr)
            block = "\n".join(started.stdout.splitlines()[1:])
            self.assertLessEqual(len(block.encode("utf-8")), cap)
            self.assertIn(
                "more record(s) not shown",
                block,
                f"cap={cap} (always-on {always_on} + index room {index_room}); "
                f"the remainder must still leave the marker visible",
            )


# ------------------------------------------------------------- the records


class TestGeneratedRecordExamples(unittest.TestCase):
    """What the distillation skill teaches must pass what the checker enforces."""

    def test_the_shipped_examples_pass_the_schema(self) -> None:
        directory = FIXTURE_ROOT / "knowledge"
        self.assertTrue(sorted(directory.glob("*.md")), "no example records ship")
        self.assertEqual(
            keel_records.main(["--dir", str(directory), "--project", str(REPO_ROOT), "--quiet"]),
            0,
        )

    def test_the_examples_are_indexable_and_findable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            target = project / ".keel" / "knowledge"
            target.mkdir(parents=True)
            for source in sorted((FIXTURE_ROOT / "knowledge").glob("*.md")):
                shutil.copyfile(source, target / source.name)
            keel_index.rebuild(project)
            with keel_index.open_index(project) as index:
                self.assertEqual(index.count(), len(list(target.glob("*.md"))))
                self.assertTrue(index.search("keel"))


# ------------------------------------------------------------- the skills


class TestSkills(unittest.TestCase):
    """The two skills are thin routers with delegation-grade frontmatter."""

    SKILLS = {"log": 500, "chart": 400}

    def _skill(self, name: str) -> str:
        return (REPO_ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")

    def _frontmatter(self, text: str) -> dict[str, str]:
        fields: dict[str, str] = {}
        lines = text.splitlines()
        self.assertEqual(lines[0].strip(), "---", "a skill must open with frontmatter")
        for line in lines[1:]:
            if line.strip() == "---":
                break
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip().strip("\"'")
        return fields

    def _body(self, text: str) -> str:
        parts = text.split("---", 2)
        return parts[2] if len(parts) > 2 else text

    def test_the_directory_names_are_bare(self) -> None:
        """The plugin namespace already prefixes: /keel:log, not /keel:keel-log."""
        for name in self.SKILLS:
            with self.subTest(skill=name):
                self.assertTrue((REPO_ROOT / "skills" / name / "SKILL.md").is_file())

    def test_each_router_is_within_its_word_budget(self) -> None:
        for name, limit in self.SKILLS.items():
            with self.subTest(skill=name):
                words = len(self._body(self._skill(name)).split())
                print(f"\nskill {name}: {words} words (limit {limit})")
                self.assertLessEqual(words, limit)

    def test_the_description_is_short_and_says_when_to_use_it(self) -> None:
        for name in self.SKILLS:
            with self.subTest(skill=name):
                fields = self._frontmatter(self._skill(name))
                self.assertEqual(fields.get("name"), name)
                description = fields.get("description", "")
                self.assertLessEqual(len(description.split()), 40, description)
                self.assertIn("use when", description.casefold())

    def test_the_router_points_at_reference_pages_that_exist(self) -> None:
        for name in self.SKILLS:
            with self.subTest(skill=name):
                references = REPO_ROOT / "skills" / name / "references"
                pages = sorted(references.glob("*.md"))
                self.assertTrue(pages, f"{name} ships no reference page")
                body = self._skill(name)
                for page in pages:
                    self.assertIn(page.name, body, f"{page.name} is unreachable from the router")

    def test_reference_pages_carry_no_frontmatter_and_cost_no_budget(self) -> None:
        """Progressive disclosure: a reference page is read on demand, never loaded."""
        for name in self.SKILLS:
            for page in sorted((REPO_ROOT / "skills" / name / "references").glob("*.md")):
                with self.subTest(page=page.name):
                    first = page.read_text(encoding="utf-8").splitlines()[0].strip()
                    self.assertNotEqual(first, "---", "a reference page must not be counted")


# ------------------------------------------------------------- the contracts


class TestPhase2DeclaredFailurePolicy(unittest.TestCase):
    """R3 / convention 12, extended to the Phase 2 modules."""

    def test_every_new_file_declares_a_policy(self) -> None:
        expected = {
            "scripts/keel_index.py": "FAIL-CLOSED",
            "scripts/keel_chart.py": "FAIL-CLOSED",
            "tests/test_keel_knowledge.py": "FAIL-CLOSED",
            "tests/contracts/keel_search_contract.py": "FAIL-CLOSED",
            "hooks/keel_capture.py": "FAIL-OPEN",
            "hooks/keel_session.py": "FAIL-OPEN",
            "hooks/keel_redact.py": "FAIL-OPEN",
        }
        for relative, policy in expected.items():
            with self.subTest(file=relative):
                source = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(policy, source.split('"""')[1], relative)

    def test_index_fails_closed_when_it_cannot_run(self) -> None:
        """The declaration, observed: an unopenable index is 2, not silence."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            path = keel_index.index_path(project)
            path.parent.mkdir(parents=True)
            path.write_text("this is not a database", encoding="utf-8")
            self.assertEqual(keel_index.main(["status", "--project", str(project)]), 2)

    def test_chart_fails_closed_when_it_cannot_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            path = keel_index.index_path(project)
            path.parent.mkdir(parents=True)
            path.write_text("this is not a database", encoding="utf-8")
            self.assertEqual(keel_chart.main(["query", "--project", str(project)]), 2)

    def test_capture_fails_open_on_an_unwritable_queue(self) -> None:
        """A queue that cannot be written costs a stderr line, never the session."""
        from keel_events import KeelEvent  # noqa: PLC0415 - path set at import time

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir()
            event = KeelEvent(
                kind="post_tool",
                cwd=project,
                session_id="s",
                tool_name="Write",
                file_paths=("a.py",),
                raw={"hook_event_name": "PostToolUse"},
            )
            original = keel_capture.append_queue

            def boom(*args: Any, **kwargs: Any) -> None:
                raise OSError("deliberate fault")

            keel_capture.append_queue = boom
            try:
                with no_real_hook_error_log():
                    self.assertEqual(keel_capture.run(event), 0)
            finally:
                keel_capture.append_queue = original

    def test_the_injector_fails_open_when_the_index_cannot_be_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            original = keel_session.knowledge_lines

            def boom(_cwd: Path) -> list[str]:
                raise OSError("deliberate fault")

            keel_session.knowledge_lines = boom
            try:
                from keel_events import KeelEvent  # noqa: PLC0415

                (project / ".keel").mkdir()
                event = KeelEvent(kind="session_start", cwd=project, session_id="abcdef123456")
                with no_real_fleet_registry(), no_real_hook_error_log():
                    self.assertEqual(keel_session.run(event), 0)
            finally:
                keel_session.knowledge_lines = original

    def test_every_command_is_reachable_from_the_cli(self) -> None:
        import keel  # noqa: PLC0415 - imported after the path insert above

        for name in ("index", "chart"):
            self.assertIn(name, keel.COMMANDS)
            self.assertIn(name, keel.usage())


class TestRulesRegister(unittest.TestCase):
    """R18: the identifiers this wave commits to are defined where they are cited."""

    def test_the_injection_rules_have_entries(self) -> None:
        register = (REPO_ROOT / "docs" / "keel-rules.md").read_text(encoding="utf-8")
        for identifier in ("R10", "R16", "R34"):
            with self.subTest(rule=identifier):
                self.assertRegex(register, rf"(?m)^#{{2,6}}\s+{identifier}\b")

    def test_the_register_names_what_enforces_the_cap(self) -> None:
        register = (REPO_ROOT / "docs" / "keel-rules.md").read_text(encoding="utf-8")
        entry = register.split("### R16")[1].split("### ")[0]
        self.assertIn("KEEL_INJECT_CAP_BYTES", entry)
        self.assertIn("hooks/keel_session.py", entry)


if __name__ == "__main__":
    unittest.main()
