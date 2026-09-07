#!/usr/bin/env python3
"""Phase 1 wave 1 test suite - the kernel: events, adapter, gate, stop.

Contract
--------
Reads   : tests/fixtures/gate/*.json and tests/fixtures/stop/*.json, the
          declarative both-direction fixture sets, plus the hook and script
          sources for their declared-policy assertions.
Emits   : unittest results only. Every fixture builds its own project inside
          a temporary directory that it also removes; the temporary directory
          is also the subprocess's TMP, so the stop gate's loop-safety marker
          never leaks between cases or between runs.
Writes  : nothing outside those temporary directories.

House style: each fixture is executed the way continuous integration will -
``python hooks/keel_hook.py <subcommand>`` as a real subprocess, JSON on
stdin, exit code and output asserted, with the cases themselves held as
declarative JSON fixtures.

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
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_adapter_claude as adapter  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_gen_hooks  # noqa: E402
import keel_plans  # noqa: E402  (the gate's contract checker, reused here)
import keel_stop  # noqa: E402
from keel_events import KeelEvent, KeelVerdict  # noqa: E402

#: ``$TS(-30)`` in a fixture means "thirty seconds before now", so audit
#: fixtures exercising the liveness rules cannot rot into hard-coded dates.
_TS_RE = re.compile(r"\$TS\((-?\d+)\)")

#: Which audit event each guard writes when it blocks.
BLOCK_EVENTS = {"gate": "gate_block", "stop": "stop_block"}


def _iso_utc(offset_seconds: int) -> str:
    """ISO 8601 UTC instant, offset from now, in keel's own audit format."""
    moment = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def substitute(value: Any, project: Path, session: str) -> Any:
    """Expand $PROJECT / $SESSION / $SESS8 / $TS(n) through a fixture value."""
    if isinstance(value, str):
        text = (
            value.replace("$PROJECT", str(project))
            .replace("$SESSION", session)
            .replace("$SESS8", session[:8])
        )
        return _TS_RE.sub(lambda match: _iso_utc(int(match.group(1))), text)
    if isinstance(value, dict):
        return {key: substitute(item, project, session) for key, item in value.items()}
    if isinstance(value, list):
        return [substitute(item, project, session) for item in value]
    return value


def load_fixtures(kind: str) -> list[tuple[str, dict]]:
    """Every fixture in a directory, in filename order, as (stem, document)."""
    directory = FIXTURE_ROOT / kind
    if not directory.is_dir():
        raise RuntimeError(f"missing fixture directory {directory}")
    found: list[tuple[str, dict]] = []
    for path in sorted(directory.glob("*.json")):
        found.append((path.stem, json.loads(path.read_text(encoding="utf-8"))))
    if not found:
        raise RuntimeError(f"no fixtures in {directory}")
    return found


class FixtureRunner(unittest.TestCase):
    """Shared machinery: build the project, run the launcher, assert."""

    kind = ""

    def run_fixture(self, fixture: dict) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            scratch = root / "tmp"
            project.mkdir()
            scratch.mkdir()

            for spec in fixture.get("files", []):
                target = project / substitute(spec["path"], project, session)
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(substitute(spec["text"], project, session))
                age = spec.get("age_minutes")
                if age:
                    stamp = target.stat().st_mtime - float(age) * 60.0
                    os.utime(target, (stamp, stamp))

            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
            }
            env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
            env["PYTHONIOENCODING"] = "utf-8"
            env.update(substitute(fixture.get("env", {}), project, session))

            payload = substitute(fixture["stdin"], project, session)
            result = subprocess.run(
                [sys.executable, "-B", str(HOOK), self.kind],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=env,
                cwd=str(project),
                timeout=60,
                check=False,
            )

            detail = f"exit={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}"
            self.assertEqual(result.returncode, fixture["expect_exit"], detail)
            for needle in fixture.get("expect_stdout_contains", []):
                self.assertIn(substitute(needle, project, session), result.stdout, detail)
            for needle in fixture.get("expect_stderr_contains", []):
                self.assertIn(substitute(needle, project, session), result.stderr, detail)

            # Audit expectations are asserted in BOTH directions: an allowed
            # event can still owe the log a line - a policy-lock refusal the
            # user's override suspended, or a stop taken while it is on.
            self._assert_audit(fixture, project, session, detail)

            if fixture["direction"] == "allow":
                self.assertEqual(fixture["expect_exit"], 0, "an allow fixture must expect exit 0")
                self.assertEqual(result.stdout, "", f"allow is silence, not JSON: {detail}")
                return

            # --- block direction: the R6 contract, then the audit trail ---
            self.assertEqual(fixture["expect_exit"], 2, "a block fixture must expect exit 2")
            decoded = json.loads(result.stdout)
            block = decoded["hookSpecificOutput"]
            self.assertIn(block["hookEventName"], ("PreToolUse", "Stop"), detail)
            decision = block["permissionDecision"]
            self.assertIn(decision, ("ask", "deny"), detail)
            self.assertTrue(block["permissionDecisionReason"].strip(), detail)
            self.assertEqual(
                KeelVerdict(decision=decision, reason="x").to_exit_code(),
                result.returncode,
                f"R6: exit code must match the JSON decision. {detail}",
            )
            self.assertIn(block["permissionDecisionReason"], result.stderr, detail)

            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            self.assertTrue(audit.is_file(), f"a block must be audited. {detail}")
            raw = audit.read_bytes()
            self.assertNotIn(b"\r", raw, "the audit log must be LF-only JSONL")
            last = json.loads(raw.decode("utf-8").splitlines()[-1])
            self.assertEqual(last["event"], BLOCK_EVENTS[self.kind], last)
            self.assertEqual(last["v"], keel_events.AUDIT_SCHEMA_VERSION, last)
            self.assertNotIn(str(project), json.dumps(last), "audit lines carry no absolute path")


    def _assert_audit(self, fixture: dict, project: Path, session: str, detail: str) -> None:
        """Optional ``expect_audit_events`` / ``expect_audit_contains`` /
        ``expect_audit_events_absent`` clauses.

        THE ABSENCE CLAUSE EXISTS BECAUSE AN EMPTY LIST ASSERTED NOTHING. A
        fixture saying ``"expect_audit_events": []`` reads like "this writes no
        line" and was in fact skipped entirely by the early return below, so the
        silent half of a both-directions pair passed no matter what the gate
        wrote. That is invisible in exactly the direction it matters for a
        record-only rule: a guard that starts recording EVERY command still goes
        green. Found by the E1 silent-failure review, 2026-08-31.
        """
        events = fixture.get("expect_audit_events", [])
        needles = fixture.get("expect_audit_contains", [])
        absent = fixture.get("expect_audit_events_absent", [])
        if not events and not needles and not absent:
            return
        audit = project / ".keel" / "audit" / "keel-audit.jsonl"
        if not audit.is_file():
            # A log that was never created records nothing, which SATISFIES an
            # absence clause and fails any positive one - said this way round so
            # an absence-only fixture is not forced to assert a file into
            # existence it is claiming stayed empty.
            self.assertFalse(events or needles, f"expected an audit line at {audit}. {detail}")
            return
        raw = audit.read_bytes()
        self.assertNotIn(b"\r", raw, "the audit log must be LF-only JSONL")
        text = raw.decode("utf-8")
        recorded = [json.loads(line)["event"] for line in text.splitlines() if line.strip()]
        for name in events:
            self.assertIn(name, recorded, f"{recorded}. {detail}")
        for name in absent:
            self.assertNotIn(name, recorded, f"{recorded}. {detail}")
        for needle in needles:
            self.assertIn(substitute(needle, project, session), text, detail)
        self.assertNotIn(str(project), text, "audit lines carry no absolute path")


class TestGateFixtures(FixtureRunner):
    """Declarative pre_write / pre_exec fixtures, both directions."""

    kind = "gate"


class TestStopFixtures(FixtureRunner):
    """Declarative stop fixtures, both directions."""

    kind = "stop"


def _attach(case: type[FixtureRunner], kind: str) -> None:
    """Turn every fixture file into its own named test method."""
    for stem, fixture in load_fixtures(kind):
        name = "test_" + re.sub(r"[^0-9a-zA-Z]+", "_", stem)

        def method(self: FixtureRunner, fixture: dict = fixture) -> None:
            self.run_fixture(fixture)

        method.__doc__ = f"{kind} fixture {stem}: {fixture.get('description', '')}"
        setattr(case, name, method)


_attach(TestGateFixtures, "gate")
_attach(TestStopFixtures, "stop")


class TestFixtureSuiteShape(unittest.TestCase):
    """Convention 2: a guard with no allow-fixtures fails CI."""

    def test_both_directions_ship_for_every_guard(self) -> None:
        for kind in ("gate", "stop"):
            with self.subTest(kind=kind):
                directions = [fixture["direction"] for _, fixture in load_fixtures(kind)]
                self.assertGreater(directions.count("block"), 0, "no block fixtures")
                self.assertGreater(directions.count("allow"), 0, "no allow fixtures")

    def test_every_fixture_is_well_formed(self) -> None:
        required = ("name", "direction", "description", "stdin", "expect_exit")
        seen: set[str] = set()
        for kind in ("gate", "stop"):
            for stem, fixture in load_fixtures(kind):
                with self.subTest(fixture=f"{kind}/{stem}"):
                    for key in required:
                        self.assertIn(key, fixture)
                    self.assertIn(fixture["direction"], ("allow", "block"))
                    self.assertIn(fixture["expect_exit"], (0, 2))
                    self.assertTrue(stem.endswith(fixture["name"]), "filename must carry the name")
                    self.assertNotIn(f"{kind}/{fixture['name']}", seen, "duplicate fixture name")
                    seen.add(f"{kind}/{fixture['name']}")

    def test_case_sensitive_risks_ship_both_cases(self) -> None:
        """R1/convention 3: tool names and locked paths ship in both cases."""
        names = {stem for stem, _ in load_fixtures("gate")}
        self.assertTrue(any("lowercase" in name for name in names))
        self.assertTrue(any("uppercase" in name for name in names))


class TestVerdictContract(unittest.TestCase):
    """R6: the exit code is the decision, and nothing else may produce it."""

    def test_exit_code_table(self) -> None:
        self.assertEqual(KeelVerdict("allow").to_exit_code(), 0)
        self.assertEqual(KeelVerdict("ask", "why").to_exit_code(), 2)
        self.assertEqual(KeelVerdict("deny", "why").to_exit_code(), 2)

    def test_every_decision_has_exactly_one_code(self) -> None:
        self.assertEqual(set(keel_events.DECISIONS), set(keel_events.DECISION_EXIT_CODES))

    def test_unknown_decision_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            KeelVerdict("maybe", "why")

    def test_blocking_verdict_must_carry_a_reason(self) -> None:
        with self.assertRaises(ValueError):
            KeelVerdict("deny", "   ")

    def test_unknown_event_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            KeelEvent(kind="pre_delete", cwd=REPO_ROOT)

    def test_event_kinds_are_the_documented_six(self) -> None:
        self.assertEqual(
            set(keel_events.EVENT_KINDS),
            {"pre_write", "pre_exec", "post_tool", "stop", "session_start", "session_end"},
        )

    def test_raw_payload_is_read_only(self) -> None:
        event = KeelEvent(kind="stop", cwd=REPO_ROOT, raw={"a": 1})
        with self.assertRaises(TypeError):
            event.raw["a"] = 2  # type: ignore[index]


class TestAdapterMapping(unittest.TestCase):
    """The adapter translates names; it decides nothing."""

    def test_write_tools_map_to_pre_write(self) -> None:
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            with self.subTest(tool=tool):
                event = adapter.event_from_payload(
                    {"tool_name": tool, "tool_input": {"file_path": "a.py"}, "cwd": str(REPO_ROOT)},
                    env={},
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.kind, "pre_write")
                self.assertEqual(event.file_paths, ("a.py",))

    def test_shell_tools_map_to_pre_exec_in_any_case(self) -> None:
        for tool in ("Bash", "bash", "PowerShell", "POWERSHELL"):
            with self.subTest(tool=tool):
                event = adapter.event_from_payload(
                    {"tool_name": tool, "tool_input": {"command": "ls"}, "cwd": str(REPO_ROOT)},
                    env={},
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.kind, "pre_exec")
                self.assertEqual(event.command, "ls")

    def test_hook_event_names_map(self) -> None:
        for name, kind in (
            ("Stop", "stop"),
            ("SessionStart", "session_start"),
            ("SessionEnd", "session_end"),
            ("PostToolUse", "post_tool"),
        ):
            with self.subTest(hook_event=name):
                event = adapter.event_from_payload(
                    {"hook_event_name": name, "cwd": str(REPO_ROOT)}, env={}
                )
                self.assertIsNotNone(event)
                self.assertEqual(event.kind, kind)

    def test_unmappable_payload_yields_no_event(self) -> None:
        """Declared FAIL-OPEN: nothing to gate means nothing is said."""
        self.assertIn("FAIL-OPEN", adapter.__doc__ or "")
        self.assertIsNone(adapter.event_from_payload({"tool_name": "Read"}, env={}))
        self.assertIsNone(adapter.event_from_payload({}, env={}))
        self.assertIsNone(adapter.event_from_payload({"tool_name": 17}, env={}))

    def test_assume_kind_covers_a_payload_without_a_hook_event_name(self) -> None:
        event = adapter.event_from_payload({"cwd": str(REPO_ROOT)}, env={}, assume_kind="stop")
        self.assertIsNotNone(event)
        self.assertEqual(event.kind, "stop")

    def test_project_dir_env_beats_payload_cwd(self) -> None:
        event = adapter.event_from_payload(
            {"tool_name": "Write", "cwd": str(REPO_ROOT / "hooks")},
            env={"CLAUDE_PROJECT_DIR": str(REPO_ROOT)},
        )
        self.assertEqual(event.cwd, REPO_ROOT)

    def test_multiedit_collects_every_path_once(self) -> None:
        event = adapter.event_from_payload(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "file_path": "a.py",
                    "edits": [{"file_path": "a.py"}, {"file_path": "b.py"}],
                },
                "cwd": str(REPO_ROOT),
            },
            env={},
        )
        self.assertEqual(event.file_paths, ("a.py", "b.py"))

    def test_allow_emits_nothing(self) -> None:
        event = KeelEvent(kind="pre_write", cwd=REPO_ROOT)
        self.assertIsNone(adapter.verdict_to_output(keel_events.allow("fine"), event))

    def test_deny_emits_the_hook_contract(self) -> None:
        event = KeelEvent(kind="pre_write", cwd=REPO_ROOT, raw={"hook_event_name": "PreToolUse"})
        output = adapter.verdict_to_output(keel_events.deny("because", "plan"), event)
        self.assertEqual(
            output,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "because",
                }
            },
        )


class TestDeclaredFailurePolicy(unittest.TestCase):
    """R3 / convention 12: the declaration in the docstring is the behaviour."""

    def _project(self, tmp: str, armed: bool) -> Path:
        project = Path(tmp)
        if armed:
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text("---\ntier: 2\n---\n", encoding="utf-8")
        return project

    def _boom(self, *args: Any, **kwargs: Any) -> KeelVerdict:
        raise RuntimeError("deliberate fault")

    def _run_with_broken_evaluate(self, module: Any, event: KeelEvent) -> KeelVerdict:
        original = module.evaluate
        module.evaluate = self._boom
        try:
            return module.run(event, env={})
        finally:
            module.evaluate = original

    def test_gate_declares_both_directions(self) -> None:
        doc = keel_gate.__doc__ or ""
        self.assertIn("FAIL-CLOSED WHEN ARMED", doc)
        self.assertIn("FAIL-OPEN WHEN UNARMED", doc)

    def test_stop_declares_both_directions(self) -> None:
        doc = keel_stop.__doc__ or ""
        self.assertIn("FAIL-CLOSED WHEN ARMED", doc)
        self.assertIn("FAIL-OPEN WHEN UNARMED", doc)

    def test_gate_fails_closed_when_armed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, armed=True)
            event = KeelEvent(
                kind="pre_write", cwd=project, session_id=uuid.uuid4().hex,
                tool_name="Write", file_paths=("src/app.py",),
            )
            verdict = self._run_with_broken_evaluate(keel_gate, event)
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.to_exit_code(), 2)
            self.assertIn("FAILED CLOSED", verdict.reason)

    def test_gate_fails_open_when_unarmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, armed=False)
            event = KeelEvent(
                kind="pre_write", cwd=project, session_id=uuid.uuid4().hex,
                tool_name="Write", file_paths=("src/app.py",),
            )
            verdict = self._run_with_broken_evaluate(keel_gate, event)
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.to_exit_code(), 0)

    def test_stop_fails_closed_when_armed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, armed=True)
            event = KeelEvent(kind="stop", cwd=project, session_id=uuid.uuid4().hex)
            verdict = self._run_with_broken_evaluate(keel_stop, event)
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.to_exit_code(), 2)

    def test_stop_fails_open_when_unarmed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(tmp, armed=False)
            event = KeelEvent(kind="stop", cwd=project, session_id=uuid.uuid4().hex)
            verdict = self._run_with_broken_evaluate(keel_stop, event)
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.to_exit_code(), 0)

    def test_event_model_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_events.__doc__ or "")

    def test_gen_hooks_declares_fail_closed_and_is(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_gen_hooks.__doc__ or "")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                keel_gen_hooks.verify(Path(tmp) / "absent.json")


class TestLauncherDispatch(unittest.TestCase):
    """The launcher stays the single entry point (R13)."""

    def _run(self, subcommand: str, payload: bytes, cwd: Path) -> subprocess.CompletedProcess:
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
        }
        return subprocess.run(
            [sys.executable, "-B", str(HOOK), subcommand],
            input=payload,
            capture_output=True,
            env=env,
            cwd=str(cwd),
            timeout=60,
            check=False,
        )

    def test_every_registered_subcommand_exists(self) -> None:
        import keel_hook  # noqa: PLC0415 - imported here so the path insert above applies

        registered = {entry.subcommand for entry in keel_gen_hooks.ENTRIES}
        self.assertTrue(registered.issubset(set(keel_hook.SUBCOMMANDS)), registered)

    def test_gate_blocks_despite_a_utf8_bom_on_stdin(self) -> None:
        """A Windows pipe prepends a BOM; a BOM must not disarm the gate."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True)
            policy.write_text("---\ntier: 2\n---\n", encoding="utf-8")
            payload = json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Write",
                    "tool_input": {"file_path": "src/app.py"},
                    "session_id": uuid.uuid4().hex,
                    "cwd": str(project),
                }
            ).encode("utf-8")
            result = self._run("gate", b"\xef\xbb\xbf" + payload, project)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn(b"PLAN GATE", result.stdout)

    def test_garbage_stdin_fails_open_on_every_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for subcommand in (
                "spike", "gate", "stop", "capture", "session", "no-such-subcommand"
            ):
                with self.subTest(subcommand=subcommand):
                    result = self._run(subcommand, b"not json at all {{{", Path(tmp))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, b"")


class TestGeneratedHooksJson(unittest.TestCase):
    """R13: hooks.json is generated, and the committed copy may not drift."""

    def test_committed_matches_the_generator(self) -> None:
        self.assertEqual(keel_gen_hooks.verify(), [])

    def test_verify_mode_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "keel_gen_hooks.py"), "--verify"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_one_bootstrap_string_serves_every_entry(self) -> None:
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        commands = [
            hook["command"]
            for entries in data["hooks"].values()
            for entry in entries
            for hook in entry["hooks"]
        ]
        self.assertEqual(len(commands), len(keel_gen_hooks.ENTRIES))
        skeletons = {
            command.replace(entry.subcommand, "@")
            for command, entry in zip(commands, keel_gen_hooks.ENTRIES)
        }
        self.assertEqual(len(skeletons), 1, "the bootstrap must be one string, not many")

    def test_entries_are_one_liners_declaring_bash(self) -> None:
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        for event, entries in data["hooks"].items():
            for entry in entries:
                for hook in entry["hooks"]:
                    with self.subTest(event=event):
                        self.assertNotIn("\n", hook["command"])
                        self.assertEqual(hook["shell"], "bash")
                        self.assertEqual(hook["type"], "command")

    def test_pretooluse_matcher_covers_every_gated_tool(self) -> None:
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        matcher = data["hooks"]["PreToolUse"][0]["matcher"]
        for tool in adapter.WRITE_TOOLS + adapter.SHELL_TOOLS:
            self.assertIn(tool, matcher.split("|"))

    def test_the_gate_events_are_registered(self) -> None:
        """The two synchronous gates keep their own registrations (wave 1).

        The observer registrations added in wave 2 are asserted by
        tests/test_keel_wave2.py; this case guards only the gates.
        """
        data = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertIn("PreToolUse", data["hooks"])
        self.assertIn("Stop", data["hooks"])
        gate_matchers = [group.get("matcher") for group in data["hooks"]["PreToolUse"]]
        self.assertIn("Write|Edit|MultiEdit|NotebookEdit|Bash|PowerShell", gate_matchers)


class TestPolicyLockSurface(unittest.TestCase):
    """The locked set is exactly the files that carry keel's own policy."""

    def test_locked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for relative in (
                ".keel/keel-policy.md",
                "hooks/keel_gate.py",
                "hooks/hooks.json",
                ".claude-plugin/plugin.json",
                ".claude/settings.json",
                ".claude/settings.local.json",
            ):
                with self.subTest(path=relative):
                    self.assertTrue(
                        keel_gate.is_protected(project, keel_gate.norm(project, relative)),
                        relative,
                    )

    def test_unlocked_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for relative in (
                "src/app.py",
                "docs/keel-rules.md",
                ".keel/plans/keel-plan-abcd1234.md",
                "tests/test_keel_kernel.py",
            ):
                with self.subTest(path=relative):
                    self.assertFalse(
                        keel_gate.is_protected(project, keel_gate.norm(project, relative)),
                        relative,
                    )

    def test_plan_targets_are_always_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = keel_gate.norm(project, ".keel/plans/keel-plan-abcd1234.md")
            self.assertTrue(keel_gate.is_plan_target(project, target))

    def test_shell_heuristic_both_directions(self) -> None:
        blocked = (
            "rm hooks/keel_gate.py",
            "copy evil.py hooks\\keel_stop.py",
            "echo x > .claude/settings.json",
            "sed -i 's/x/y/' .keel/keel-policy.md",
            "setx KEEL_OVERRIDE on",
            'grep -n "keel-policy.md hooks/keel_gate.py',  # unterminated quote: fail safe
        )
        allowed = (
            "git log --oneline -- .keel/keel-policy.md",
            "cat .keel/keel-policy.md > /dev/null",
            "git diff -- hooks/keel_gate.py | head -40",
            "python -m unittest discover -s tests 2>&1 | tail -3",
            "grep -i model .claude/settings.json",
        )
        for command in blocked:
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_hits_policy_lock(command.casefold()))
        for command in allowed:
            with self.subTest(command=command):
                self.assertFalse(keel_gate.shell_hits_policy_lock(command.casefold()))


class TestArming(unittest.TestCase):
    """Enforcement exists only where the adopter asked for it (R25)."""

    def _policy(self, project: Path, text: str) -> None:
        path = project / ".keel" / "keel-policy.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_tier_ladder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertIsNone(keel_gate.policy_tier(project))
            for tier, armed in ((0, False), (1, False), (2, True), (3, True)):
                with self.subTest(tier=tier):
                    self._policy(project, f"---\ntier: {tier}\n---\n")
                    self.assertEqual(keel_gate.policy_tier(project), tier)
                    self.assertEqual(keel_gate.is_armed(project), armed)

    def test_tier_is_read_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self._policy(project, "---\nTier: 2\n---\n")
            self.assertEqual(keel_gate.policy_tier(project), 2)

    def test_unreadable_tier_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for text in ("no frontmatter here\n", "---\nname: x\n---\n", "---\ntier: 2\n"):
                with self.subTest(text=text):
                    self._policy(project, text)
                    with self.assertRaises(keel_gate.GateError):
                        keel_gate.policy_tier(project)

    def test_non_numeric_ttl_raises(self) -> None:
        with self.assertRaises(keel_gate.GateError):
            keel_gate.plan_ttl_minutes({"KEEL_PLAN_TTL_MIN": "soon"})
        self.assertEqual(keel_gate.plan_ttl_minutes({}), keel_gate.DEFAULT_PLAN_TTL_MIN)


class TestPlanContractAssertion(unittest.TestCase):
    """Gate rule 3: a session ledger's CONTENT is asserted at the write.

    The fixtures under ``tests/fixtures/gate/`` pin the end-to-end behaviour
    (29-35); these cases pin the parts a fixture cannot see - that the gate's
    blocking set is every rule the checker can emit, that the scope line is
    narrower than the bootstrap carve-out, and that a checker which cannot be
    loaded denies rather than waves the write through.
    """

    #: A ledger violating all four machine-checkable rules at once.
    DIRTY = "# plan\n\n## Tasks\n\n- [ ] A task whose scope is TBD.\n"

    def _event(self, project: Path, relative: str, **tool_input: Any) -> KeelEvent:
        return KeelEvent(
            kind="pre_write",
            cwd=project,
            session_id=uuid.uuid4().hex,
            tool_name="Write",
            file_paths=(relative,),
            raw={"tool_input": {"file_path": relative, **tool_input}},
        )

    def test_blocking_set_is_every_rule_the_checker_emits(self) -> None:
        """The owner's ruling: all four kinds block, so none may be forgotten."""
        emitted = {f.rule for f in keel_plans.check_ledger("p.md", self.DIRTY, False)}
        self.assertEqual(emitted, set(keel_gate.BLOCKING_PLAN_RULES))

    def test_scope_is_narrower_than_the_bootstrap_carve_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for relative, is_ledger in (
                (".keel/plans/keel-plan-abcd1234.md", True),
                (".keel/plans/KEEL-PLAN-ABCD1234.MD", True),
                (".keel/plans/refit-draft-abcd1234.md", False),
                (".keel/plans/notes.md", False),
            ):
                with self.subTest(path=relative):
                    target = keel_gate.norm(project, relative)
                    self.assertTrue(keel_gate.is_plan_target(project, target))
                    self.assertEqual(
                        keel_gate.is_session_ledger(project, target), is_ledger, relative
                    )

    def test_a_dirty_ledger_write_is_denied_with_every_finding_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            relative = ".keel/plans/keel-plan-abcd1234.md"
            event = self._event(project, relative, content=self.DIRTY)
            verdict = keel_gate.plan_contract_verdict(
                event, [(relative, keel_gate.norm(project, relative))]
            )
            self.assertIsNotNone(verdict)
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan_contract")
            for rule in keel_gate.BLOCKING_PLAN_RULES:
                self.assertIn(rule, verdict.reason)
            self.assertIn("NEXT STEP:", verdict.reason)

    def test_a_ledger_with_no_task_lines_says_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            relative = ".keel/plans/keel-plan-abcd1234.md"
            event = self._event(project, relative, content="# plan\n\n## Tasks\n")
            self.assertIsNone(
                keel_gate.plan_contract_verdict(
                    event, [(relative, keel_gate.norm(project, relative))]
                )
            )

    def test_an_unloadable_checker_denies_and_names_the_failure(self) -> None:
        """UNVERIFIABLE IS DENY, applied to the checker itself."""

        def boom() -> Any:
            raise ImportError("no module named keel_plans")

        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            relative = ".keel/plans/keel-plan-abcd1234.md"
            event = self._event(project, relative, content=self.DIRTY)
            original = keel_gate.load_plans_checker
            keel_gate.load_plans_checker = boom
            try:
                verdict = keel_gate.plan_contract_verdict(
                    event, [(relative, keel_gate.norm(project, relative))]
                )
            finally:
                keel_gate.load_plans_checker = original
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan_contract")
            self.assertIn("ImportError", verdict.reason)
            self.assertIn("keel_plans", verdict.reason)

    def test_shell_ledger_mutation_both_directions(self) -> None:
        """Rule 3 reaches the shell: mutation is refused, reading is not.

        The extension exists because the content a command would leave behind
        cannot be checked before it runs, so the mutation half of the shell
        heuristic decides and nothing is parsed out of the command.
        """
        blocked = (
            "echo junk > .keel/plans/keel-plan-abcd1234.md",
            "echo junk >> .keel/plans/keel-plan-abcd1234.md",
            'set-content .keel\\plans\\keel-plan-abcd1234.md "junk"',
            "out-file -filepath .keel/plans/keel-plan-abcd1234.md",
            "cp /tmp/fake.md .keel/plans/keel-plan-abcd1234.md",
            "cd .keel/plans && echo junk > keel-plan-abcd1234.md",
            # unterminated quote: the parser gives up and the fail safe blocks
            'grep -n "route .keel/plans/keel-plan-abcd1234.md',
        )
        allowed = (
            "cat .keel/plans/keel-plan-abcd1234.md",
            "git add .keel/plans/keel-plan-abcd1234.md",
            "grep -n 'Route:' .keel/plans/keel-plan-abcd1234.md",
            "cat .keel/plans/keel-plan-abcd1234.md > /dev/null",
            "echo junk > .keel/plans/refit-draft-abcd1234.md",  # not a ledger
            "python -m unittest discover -s tests",
        )
        for command in blocked:
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_writes_session_ledger(command.casefold()))
        for command in allowed:
            with self.subTest(command=command):
                self.assertFalse(keel_gate.shell_writes_session_ledger(command.casefold()))

    def test_a_shell_ledger_write_denies_and_names_the_tool_to_use(self) -> None:
        """The end of the escalation: the refusal names a door, not a wall."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text("---\ntier: 2\n---\n", encoding="utf-8")
            session = uuid.uuid4().hex
            ledger = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_text("# plan\n", encoding="utf-8")  # fresh: rule 2 satisfied
            event = KeelEvent(
                kind="pre_exec",
                cwd=project,
                session_id=session,
                tool_name="Bash",
                command=f"echo junk > .keel/plans/{ledger.name}",
            )
            verdict = keel_gate.evaluate(event, env={})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan_contract_shell")
            self.assertIn("PLAN CONTRACT", verdict.reason)
            self.assertIn("Write or Edit tool", verdict.reason)

    def test_a_clean_ledger_write_is_allowed(self) -> None:
        """The contract-clean shape this repository's own ledgers use."""
        clean = (
            "# plan\n\n## Tasks\n\n"
            "- [ ] T1 A task that names both fields.\n"
            "      Route: standard (keel:executor).\n"
            "      Accept: the kernel suite is green.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            relative = ".keel/plans/keel-plan-abcd1234.md"
            event = self._event(project, relative, content=clean)
            self.assertIsNone(
                keel_gate.plan_contract_verdict(
                    event, [(relative, keel_gate.norm(project, relative))]
                )
            )


class TestStopMarker(unittest.TestCase):
    """Loop safety, and no payload value steering a path (R5)."""

    def test_session_id_cannot_traverse(self) -> None:
        marker = keel_stop.marker_path("../../etc/passwd")
        self.assertEqual(marker.parent, Path(tempfile.gettempdir()))
        self.assertNotIn("..", marker.name)

    def test_second_block_in_a_row_is_suppressed(self) -> None:
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True)
            policy.write_text("---\ntier: 2\n---\n", encoding="utf-8")
            plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
            plan.parent.mkdir(parents=True)
            plan.write_text("- [ ] T1: open | AC: x\n", encoding="utf-8")
            event = KeelEvent(kind="stop", cwd=project, session_id=session)
            try:
                first = keel_stop.run(event, env={})
                second = keel_stop.run(event, env={})
                self.assertEqual(first.decision, "deny")
                self.assertEqual(second.decision, "allow")
            finally:
                keel_stop.marker_path(session).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
