#!/usr/bin/env python3
"""Phase 1 wave 3 test suite - the dashboard, the record checker, the budget,
and keel's own arming file.

Contract
--------
Reads   : tests/fixtures/records/*.json - the declarative record fixtures, in
          both directions ("pass" and "flag") - plus this repository's arming
          file, .gitignore and the sources of the wave-3 modules for their
          declared-policy assertions.
Emits   : unittest results only, plus one line naming the measured
          always-loaded token budget, because a number nobody prints is a
          number nobody notices.
Writes  : nothing outside temporary directories it creates and removes. The
          dashboard tests assert this literally: the project tree is
          fingerprinted before and after a full round of requests, including
          the refused ones.

House style: the command-line tools are executed as
``python scripts/keel.py <command>`` in a subprocess, so the exit codes
asserted here are the exit codes a caller gets. The dashboard is the one
component that cannot be exercised that way - it serves until interrupted -
so it is started in a thread on its ephemeral port and driven over 127.0.0.1,
which is the only network any keel test is permitted to touch.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file operation names its encoding. The
only socket opened is a loopback listener bound to an ephemeral port (R19).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
KEEL_CLI = REPO_ROOT / "scripts" / "keel.py"
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "records"
POLICY = REPO_ROOT / ".keel" / "keel-policy.md"
GITIGNORE = REPO_ROOT / ".gitignore"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import is_published_cut  # noqa: E402

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_checks  # noqa: E402  (path must be set first)
import keel_dashboard  # noqa: E402
import keel_gate  # noqa: E402
import keel_hook  # noqa: E402
import keel_records  # noqa: E402
import keel_session  # noqa: E402
import keel_survey  # noqa: E402

HOME = str(Path.home())
USERNAME = Path.home().name

#: One request timeout for every loopback call. Generous, because a slow
#: Windows runner must not be reported as a broken server.
HTTP_TIMEOUT = 20


def clean_env(scratch: Path, **extra: str) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all.

    ``extra`` overrides after the scrub, which is how a caller hands a
    subprocess a fixture HOME - the one premise a CLI resolves for itself.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def run_cli(args: list[str], scratch: Path, **env_extra: str) -> subprocess.CompletedProcess:
    """Run scripts/keel.py exactly as a caller would, and return the result."""
    return subprocess.run(
        [sys.executable, "-B", str(KEEL_CLI), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=clean_env(scratch, **env_extra),
        cwd=str(scratch),
        timeout=180,
        check=False,
    )


def fingerprint(root: Path) -> list[tuple[str, str]]:
    """Every file under ``root`` as (relative path, content hash), sorted.

    The instrument for "writes nothing": a viewer that created, touched or
    changed one byte anywhere shows up as a different list.
    """
    out: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append((path.relative_to(root).as_posix(), digest))
    return out


# ------------------------------------------------------------------ dashboard


class DashboardServer:
    """A running viewer on an ephemeral loopback port, for the duration of a test."""

    def __init__(self, project: Path) -> None:
        self.server: ThreadingHTTPServer = keel_dashboard.build_server(project)
        self.url = keel_dashboard.server_url(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def get(self, route: str) -> tuple[int, str, str]:
        """``(status, body, content-type)`` for a GET, 4xx included."""
        try:
            with urllib.request.urlopen(self.url.rstrip("/") + route, timeout=HTTP_TIMEOUT) as r:
                return r.status, r.read().decode("utf-8"), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8"), exc.headers.get("Content-Type", "")

    def request(self, method: str, route: str) -> tuple[int, str]:
        """``(status, body)`` for any method, including the refused ones."""
        request = urllib.request.Request(
            self.url.rstrip("/") + route, data=b"{}", method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as r:
                return r.status, r.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8")

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=HTTP_TIMEOUT)


class TestDashboard(unittest.TestCase):
    """Read-only, loopback-only, ephemeral-port-only (R19)."""

    session = "abcdef12"

    def _project(self, root: Path) -> Path:
        """A small adopted project: an arming file, one ledger, one audit log."""
        project = root / "project"
        (project / ".keel" / "plans").mkdir(parents=True)
        (project / ".keel" / "audit").mkdir(parents=True)
        (project / ".keel" / "keel-policy.md").write_text(
            "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
        )
        (project / ".keel" / "plans" / f"keel-plan-{self.session}.md").write_text(
            "# ledger\n\n"
            "- [x] T1: port the dashboard | route: executor-deep\n"
            "- [~] T2: port the record checker | route: executor-deep\n"
            f"- [ ] T3: read {HOME}/notes.txt | route: researcher\n",
            encoding="utf-8",
        )
        with open(
            project / ".keel" / "audit" / "keel-audit.jsonl", "w", encoding="utf-8", newline="\n"
        ) as handle:
            for line in (
                {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "session_start",
                 "session": self.session},
                {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "handoff_start",
                 "session": self.session, "subagent_type": "executor-deep",
                 "description": "T1: port the dashboard"},
                {"v": 1, "ts": "2026-08-01T10:02:00Z", "event": "gate_block",
                 "session": self.session, "gate": "plan", "reason": "no ledger"},
            ):
                handle.write(json.dumps(line) + "\n")
            handle.write("{ this line is not json\n")
        return project

    def test_binds_an_ephemeral_loopback_port_and_prints_it(self) -> None:
        """R19: no fixed port, no derived port - the OS assigns and we report."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            first = DashboardServer(project)
            second = DashboardServer(project)
            try:
                for server in (first, second):
                    host, port = server.server.server_address[0], server.server.server_address[1]
                    self.assertEqual(host, "127.0.0.1", "a dashboard is loopback only")
                    self.assertNotEqual(port, 0, "an ephemeral bind still resolves to a port")
                    self.assertRegex(server.url, r"^http://127\.0\.0\.1:\d+/$")
                self.assertNotEqual(
                    first.server.server_address[1],
                    second.server.server_address[1],
                    "two viewers must never collide on one port (R19)",
                )
            finally:
                first.close()
                second.close()

    def test_index_and_state_are_served_over_loopback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(self._project(Path(tmp)))
            try:
                status, body, content_type = server.get("/")
                self.assertEqual(status, 200)
                self.assertIn("text/html", content_type)
                self.assertIn("<title>keel", body)
                self.assertIn("read-only", body)

                status, body, content_type = server.get("/api/state")
                self.assertEqual(status, 200)
                self.assertIn("application/json", content_type)
                state = json.loads(body)
                self.assertTrue(state["readonly"])
                self.assertEqual(state["arming"], {"tier": 2, "armed": True, "note": ""})
                self.assertEqual(state["counts"]["events"], 3)
                self.assertEqual(state["counts"]["gate_block"], 1)
                self.assertEqual(
                    state["counts"]["unreadable_lines"], 1, "a corrupt line is counted, not hidden"
                )
                self.assertEqual(state["plan"]["name"], f"keel-plan-{self.session}.md")
                self.assertIn("- [x] T1", state["plan"]["text"])
            finally:
                server.close()

    def test_gate_bypass_and_override_reminder_events_are_counted(self) -> None:
        """COUNTED_EVENTS gains the two events the relaxation wave introduced:
        a bypass is not a denial and neither is the stop-time reminder, but
        both are countable friction the viewer must not drop on the floor."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            with open(
                project / ".keel" / "audit" / "keel-audit.jsonl", "a", encoding="utf-8", newline="\n"
            ) as handle:
                for line in (
                    {"v": 1, "ts": "2026-08-01T10:03:00Z", "event": "gate_bypass",
                     "session": self.session, "gate": "policy_lock"},
                    {"v": 1, "ts": "2026-08-01T10:04:00Z", "event": "override_active_at_stop",
                     "session": self.session, "gate": "policy_lock"},
                ):
                    handle.write(json.dumps(line) + "\n")
            server = DashboardServer(project)
            try:
                status, body, _ = server.get("/api/state")
                self.assertEqual(status, 200)
                state = json.loads(body)
                self.assertEqual(state["counts"]["gate_bypass"], 1)
                self.assertEqual(state["counts"]["override_active_at_stop"], 1)
                self.assertEqual(state["counts"]["events"], 5)
            finally:
                server.close()

    def test_a_ledger_is_served_by_name_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(self._project(Path(tmp)))
            try:
                status, body, _ = server.get(f"/api/plan?name=keel-plan-{self.session}.md")
                self.assertEqual(status, 200)
                self.assertIn("T2: port the record checker", body)
                self.assertIn("~/notes.txt", body, "a home path must reach the page redacted")
                if USERNAME:
                    self.assertNotIn(USERNAME, body, "the viewer leaked a username")
            finally:
                server.close()

    def test_no_route_escapes_the_plans_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(self._project(Path(tmp)))
            try:
                for name in (
                    "../keel-policy.md",
                    "..%2Fkeel-policy.md",
                    "keel-plan-../../keel-policy.md",
                    "/etc/passwd",
                    "keel-policy.md",
                    "keel-plan-x.txt",
                ):
                    with self.subTest(name=name):
                        status, body, _ = server.get(f"/api/plan?name={name}")
                        self.assertEqual(status, 404, body)
                        self.assertNotIn("tier:", body)
                self.assertEqual(server.get("/nope")[0], 404)
            finally:
                server.close()

    def test_no_write_route_exists(self) -> None:
        """The security posture, asserted three ways."""
        with tempfile.TemporaryDirectory() as tmp:
            project = self._project(Path(tmp))
            before = fingerprint(project)
            server = DashboardServer(project)
            try:
                for method in keel_dashboard.WRITE_METHODS:
                    for route in ("/", "/api/state", "/api/plan?name=x", "/anything"):
                        with self.subTest(method=method, route=route):
                            status, body = server.request(method, route)
                            self.assertEqual(status, 405, f"{method} {route} was not refused")
                            self.assertIn("read-only", body)
                # Every read route is exercised too, so "nothing changed" is a
                # statement about a server that actually did its work.
                server.get("/")
                server.get("/api/state")
                server.get(f"/api/plan?name=keel-plan-{self.session}.md")
            finally:
                server.close()
            self.assertEqual(before, fingerprint(project), "the viewer wrote something")

    def test_the_handler_declares_only_read_methods(self) -> None:
        """Structural, not behavioural: the class itself has no write handler."""
        handlers = {
            name
            for name in dir(keel_dashboard.KeelDashboardHandler)
            if name.startswith("do_")
        }
        self.assertEqual(handlers, {"do_GET", "do_HEAD", "do_POST", "do_PUT", "do_PATCH",
                                    "do_DELETE"})
        for method in keel_dashboard.WRITE_METHODS:
            with self.subTest(method=method):
                self.assertIs(
                    getattr(keel_dashboard.KeelDashboardHandler, "do_" + method),
                    keel_dashboard.KeelDashboardHandler._refuse_write,
                    "a state-changing method is bound to something other than the refusal",
                )
        self.assertEqual(set(keel_dashboard.READ_ROUTES), {"/", "/api/state", "/api/plan"})

    def test_plan_name_validation_in_both_directions(self) -> None:
        good = ("keel-plan-abcdef12.md", "keel-plan-ci.md", "keel-plan-A1_b-2.md")
        bad = (
            "",
            "keel-plan-.md",
            "plan-abcdef12.md",
            "keel-plan-abcdef12.txt",
            "keel-plan-../x.md",
            "keel-plan-a/b.md",
            "keel-plan-a\\b.md",
            "C:keel-plan-a.md",
            "keel-plan-a b.md",
        )
        for name in good:
            with self.subTest(name=name):
                self.assertTrue(keel_dashboard.is_plan_name(name))
        for name in bad:
            with self.subTest(name=name):
                self.assertFalse(keel_dashboard.is_plan_name(name))

    def test_an_unadopted_project_cannot_start_a_viewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "plain"
            plain.mkdir()
            with self.assertRaises(keel_dashboard.DashboardError):
                keel_dashboard.build_server(plain)
            result = run_cli(["dashboard", "--project", str(plain)], Path(tmp))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn(".keel", result.stderr)

    def test_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_dashboard.__doc__ or "")


# -------------------------------------------------------------------- records


def load_record_fixtures() -> list[tuple[str, dict[str, Any]]]:
    """Every record fixture, in filename order, as (stem, document)."""
    if not FIXTURE_ROOT.is_dir():
        raise RuntimeError(f"missing fixture directory {FIXTURE_ROOT}")
    found = [
        (path.stem, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(FIXTURE_ROOT.glob("*.json"))
    ]
    if not found:
        raise RuntimeError(f"no fixtures in {FIXTURE_ROOT}")
    return found


class TestRecordFixtures(unittest.TestCase):
    """Declarative record fixtures, both directions, run through the CLI."""

    def run_fixture(self, fixture: dict[str, Any]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            project = base / "project"
            (project / ".keel").mkdir(parents=True)
            for relative, text in fixture["records"].items():
                target = project / ".keel" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            for relative, document in fixture.get("sources", {}).items():
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(document))

            result = run_cli(
                [
                    "records",
                    "--project",
                    str(project),
                    "--sources-base",
                    str(base),
                    "--today",
                    fixture["today"],
                    "--json",
                ],
                root,
            )
            detail = f"exit={result.returncode} stdout={result.stdout} stderr={result.stderr}"
            self.assertEqual(result.returncode, fixture["expect_exit"], detail)
            report = json.loads(result.stdout)
            rules = {finding["rule"] for finding in report["findings"]}
            for rule in fixture["expect_rules"]:
                self.assertIn(rule, rules, detail)
            for rule in fixture["expect_absent_rules"]:
                self.assertNotIn(rule, rules, detail)
            self.assertEqual(report["clean"], fixture["expect_exit"] == 0, detail)
            if "expect_checked" in fixture:
                self.assertEqual(report["summary"]["records_checked"], fixture["expect_checked"])
            for finding in report["findings"]:
                self.assertNotIn(tmp, finding["path"], "a report path must be project-relative")


def _attach_record_fixtures() -> None:
    """Turn every fixture file into its own named test method."""
    for stem, fixture in load_record_fixtures():
        name = "test_" + re.sub(r"[^0-9a-zA-Z]+", "_", stem)

        def method(self: TestRecordFixtures, fixture: dict[str, Any] = fixture) -> None:
            self.run_fixture(fixture)

        method.__doc__ = f"record fixture {stem}: {fixture.get('description', '')}"
        setattr(TestRecordFixtures, name, method)


_attach_record_fixtures()


class TestRecordFixtureShape(unittest.TestCase):
    """Convention 2 applied to the checker: both directions or it does not ship."""

    def test_both_directions_ship(self) -> None:
        directions = [fixture["direction"] for _, fixture in load_record_fixtures()]
        self.assertGreater(directions.count("pass"), 0, "no passing records")
        self.assertGreater(directions.count("flag"), 0, "no flagged records")

    def test_every_fixture_is_well_formed(self) -> None:
        required = (
            "name",
            "direction",
            "description",
            "today",
            "records",
            "expect_exit",
            "expect_rules",
            "expect_absent_rules",
        )
        seen: set[str] = set()
        for stem, fixture in load_record_fixtures():
            with self.subTest(fixture=stem):
                for key in required:
                    self.assertIn(key, fixture)
                self.assertIn(fixture["direction"], ("pass", "flag"))
                self.assertEqual(fixture["expect_exit"], 0 if fixture["direction"] == "pass" else 1)
                self.assertTrue(stem.endswith(fixture["name"]))
                self.assertNotIn(fixture["name"], seen, "duplicate fixture name")
                seen.add(fixture["name"])

    def test_every_error_rule_is_exercised_by_a_fixture(self) -> None:
        """A rule nothing exercises is a rule nobody knows still works."""
        exercised: set[str] = set()
        for _, fixture in load_record_fixtures():
            exercised.update(fixture["expect_rules"])
        for rule in (
            "missing_name",
            "missing_verified",
            "unknown_type",
            "expired",
            "bad_stale_after",
            "bad_cites",
            "decision_with_stale_after",
            "ratified_unverified",
            "no_frontmatter",
            "unterminated_frontmatter",
            "assessment_without_stale_after",
            "cites_drift",
            "cites_unverifiable",
        ):
            with self.subTest(rule=rule):
                self.assertIn(rule, exercised)


class TestRecords(unittest.TestCase):
    """Severity semantics, scope, and the two ways this checker may exit."""

    def _project(self, root: Path, records: dict[str, str]) -> Path:
        project = root / "project"
        for relative, text in records.items():
            target = project / ".keel" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        (project / ".keel").mkdir(parents=True, exist_ok=True)
        return project

    def test_absent_record_directories_are_clean_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel").mkdir(parents=True)
            result = run_cli(["records", "--project", str(project)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("clean", result.stdout)
            self.assertIn("0 record(s) checked", result.stdout)

    def test_drift_is_a_warning_and_never_a_failure(self) -> None:
        """The asymmetry that makes the pin usable: reported, not enforced."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            (base / "neighbour" / ".claude-plugin").mkdir(parents=True)
            (base / "neighbour" / ".claude-plugin" / "plugin.json").write_text(
                json.dumps({"version": "2.0.0"}), encoding="utf-8"
            )
            project = self._project(
                base,
                {
                    "knowledge/pinned.md": (
                        "---\nname: pinned\ndescription: A pinned record.\n"
                        "type: knowledge\n"
                        'generated: { by: "machine:executor", at: "2026-08-01" }\n'
                        "verified: []\nstale_after: 2027-01-01\ncites:\n"
                        '  - { source: "neighbour/.claude-plugin/plugin.json", '
                        'version: "1.0.0", at: "2026-08-01" }\n---\n\nBody.\n'
                    )
                },
            )
            result = run_cli(
                [
                    "records", "--project", str(project), "--sources-base", str(base),
                    "--today", "2026-08-01", "--json",
                ],
                root,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            drift = [f for f in report["findings"] if f["rule"] == "cites_drift"]
            self.assertEqual(len(drift), 1, report["findings"])
            self.assertEqual(drift[0]["severity"], "warn")
            self.assertIn("2.0.0", drift[0]["detail"])
            self.assertIn("1.0.0", drift[0]["detail"])
            self.assertTrue(report["clean"], "a warning must not make the run unclean")

    def test_the_actor_prefix_rule_is_a_warning(self) -> None:
        findings = keel_records.check_record(
            "r.md",
            "---\nname: r\ndescription: d\ntype: knowledge\n"
            'generated: { by: "someone", at: "2026-08-01" }\n'
            "verified: []\nstale_after: 2027-01-01\n---\n",
            __import__("datetime").date(2026, 8, 1),
        )
        prefix = [f for f in findings if f.rule == "actor_prefix"]
        self.assertEqual(len(prefix), 1, findings)
        self.assertEqual(prefix[0].severity, keel_records.WARN)

    def test_a_source_id_cannot_escape_the_sources_base(self) -> None:
        for source in ("../secrets.json", "/etc/passwd.json", "C:/secrets.json", "a/../b.json"):
            with self.subTest(source=source):
                version, why = keel_records.resolve_source_version(source, str(REPO_ROOT))
                self.assertIsNone(version)
                self.assertIsNotNone(why)

    def test_an_explicit_dir_replaces_the_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            elsewhere = root / "elsewhere"
            elsewhere.mkdir()
            (elsewhere / "r.md").write_text("# no frontmatter\n", encoding="utf-8")
            result = run_cli(
                ["records", "--project", str(root), "--dir", str(elsewhere), "--json"], root
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["summary"]["records_checked"], 1)
            self.assertEqual(report["findings"][0]["rule"], "no_frontmatter")

    def test_a_bad_today_is_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(["records", "--project", tmp, "--today", "yesterday"], Path(tmp))
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_this_repository_own_records_are_clean(self) -> None:
        """keel checks itself: today there are no records, which is exit 0."""
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(["records", "--project", str(REPO_ROOT)], Path(tmp))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_declares_fail_closed(self) -> None:
        self.assertIn("FAIL-CLOSED", keel_records.__doc__ or "")


# --------------------------------------------------------------------- budget


class TestBudgetScope(unittest.TestCase):
    """The re-scope: the budget now counts the real always-loaded surface."""

    def _tree(self, root: Path, readme_lines: int = 0) -> Path:
        project = root / "p"
        (project / "hooks").mkdir(parents=True)
        (project / "agents").mkdir()
        (project / "skills" / "chart").mkdir(parents=True)
        (project / "hooks" / "hooks.json").write_text(
            json.dumps(
                {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
                                                        "command": "x" * 40}]}]}}
            ),
            encoding="utf-8",
        )
        (project / "agents" / "executor.md").write_text(
            "---\nname: executor\ndescription: " + "d" * 30 + "\ntools: Read\n---\n\nBody.\n",
            encoding="utf-8",
        )
        (project / "skills" / "chart" / "SKILL.md").write_text(
            "---\nname: chart\ndescription: " + "e" * 20 + "\n---\n\nBody.\n",
            encoding="utf-8",
        )
        if readme_lines:
            (project / "README.md").write_text(
                "\n".join("z" * 200 for _ in range(readme_lines)) + "\n", encoding="utf-8"
            )
        return project

    def test_the_readme_is_no_longer_counted(self) -> None:
        """The dropped proxy, proven dropped: a huge README moves nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare = self._tree(root / "a")
            wordy = self._tree(root / "b", readme_lines=200)
            self.assertEqual(keel_checks.check_budget(bare)[0],
                             keel_checks.check_budget(wordy)[0])

    def test_it_counts_hook_commands_and_component_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._tree(Path(tmp))
            # 40 hook chars + (8+30) agent + (5+20) skill = 103 chars -> 26 tokens.
            chars = 40 + (len("executor") + 30) + (len("chart") + 20)
            tokens, violations = keel_checks.check_budget(project)
            self.assertEqual(tokens, -(-chars // keel_checks.CHARS_PER_TOKEN))
            self.assertEqual(violations, [])

    def test_a_reference_page_without_frontmatter_costs_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = self._tree(Path(tmp))
            before = keel_checks.check_budget(project)[0]
            references = project / "skills" / "chart" / "references"
            references.mkdir()
            (references / "detail.md").write_text("# detail\n" + "w" * 5000, encoding="utf-8")
            self.assertEqual(keel_checks.check_budget(project)[0], before)

    def test_the_limit_is_still_strict(self) -> None:
        # 1400 since the ratified amendment of 2026-08-21
        # (.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md);
        # 1200 before it. The literal is pinned rather than read from the
        # module because this test's whole job is to notice the number moving
        # without a decision behind it.
        self.assertEqual(keel_checks.BUDGET_TOKEN_LIMIT, 1400)
        with tempfile.TemporaryDirectory() as tmp:
            project = self._tree(Path(tmp))
            (project / "agents" / "bloated.md").write_text(
                "---\nname: bloated\ndescription: " + "d" * 6000 + "\n---\n", encoding="utf-8"
            )
            tokens, violations = keel_checks.check_budget(project)
            self.assertGreater(tokens, keel_checks.BUDGET_TOKEN_LIMIT)
            self.assertEqual(len(violations), 1)
            self.assertIn("exceeds limit 1400", violations[0])

    def test_the_readme_proxy_is_gone_from_the_module(self) -> None:
        self.assertFalse(hasattr(keel_checks, "README_BUDGET_LINES"))
        self.assertFalse(hasattr(keel_checks, "_readme_head_chars"))
        source = (REPO_ROOT / "scripts" / "keel_checks.py").read_text(encoding="utf-8")
        self.assertIn("proxy", keel_checks.check_budget.__doc__ or "")
        self.assertNotIn("README head", source)

    def test_this_repository_is_measured_and_the_number_is_printed(self) -> None:
        tokens, violations = keel_checks.check_budget(REPO_ROOT)
        print(f"\nkeel always-loaded budget: {tokens} / {keel_checks.BUDGET_TOKEN_LIMIT} tokens")
        self.assertEqual(violations, [], f"budget is {tokens} tokens")
        self.assertGreater(tokens, 0, "a zero budget means the measurement is broken")
        self.assertLess(tokens, keel_checks.BUDGET_TOKEN_LIMIT)

    def test_the_survey_reports_the_same_number(self) -> None:
        report = keel_survey.survey(REPO_ROOT)
        self.assertEqual(report["budget"]["tokens"], keel_checks.check_budget(REPO_ROOT)[0])
        self.assertIn("agent/skill frontmatter", report["budget"]["detail"])

    def test_session_injection_tokens_reads_the_session_hooks_cap(self) -> None:
        """T26: figure 2 is imported from the session hook, not duplicated,
        so it cannot disagree with the cap actually enforced there."""
        cap_bytes, tokens = keel_checks.session_injection_tokens()
        self.assertEqual(cap_bytes, keel_session.DEFAULT_INJECT_CAP_BYTES)
        self.assertEqual(tokens, -(-cap_bytes // keel_checks.CHARS_PER_TOKEN))
        self.assertEqual(tokens, 1024)  # 4096 bytes / 4 chars-per-token, ceiling.

        lowered_cap, lowered_tokens = keel_checks.session_injection_tokens(
            {"KEEL_INJECT_CAP_BYTES": "1000"}
        )
        self.assertEqual(lowered_cap, 1000)
        self.assertEqual(lowered_tokens, 250)
        self.assertLess(lowered_tokens, tokens)


class TestBudgetCLIThreeFigures(unittest.TestCase):
    """T26: ``--budget`` reports three figures, only the first of which gates."""

    CHECKS = REPO_ROOT / "scripts" / "keel_checks.py"

    STATIC_RE = re.compile(
        r"always-loaded static tokens \(gates this check\): (\d+) / (\d+)"
    )
    INJECTION_RE = re.compile(
        r"session injection tokens \(reported only, not gated\): (\d+) \(cap (\d+) bytes\)"
    )
    FLOOR_RE = re.compile(
        r"worst-case session floor \(reported only, not gated\): (\d+) tokens"
    )

    def _run(self, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
        env = {**os.environ, **env_overrides, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            [sys.executable, "-B", str(self.CHECKS), "--budget"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(REPO_ROOT),
            env=env,
            check=False,
        )

    def test_the_cli_reports_all_three_figures_pinned(self) -> None:
        """The exact figures, pinned against the functions that compute them,
        as this repository is measured today (1222 + 1024 = 2246).

        The static figure was 989 through T21 and moved when keel subscribed
        to ``SubagentStop``: an eighth registration is an eighth copy of the
        bootstrap in ``hooks/hooks.json``, and those command strings are half
        of what this budget measures. It moved again, 1068 -> 1222, when T228
        added the ninth and tenth (``UserPromptSubmit`` and ``PreCompact``) -
        154 tokens, exactly the figure the ceiling amendment was sized by
        (``.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md``).
        Re-pinned rather than relaxed, both times: a pinned figure that drifts
        on its own is the thing this case exists to catch, and the limit is a
        separate number that moves only by decision.
        """
        result = self._run({})
        detail = f"exit={result.returncode} stdout={result.stdout} stderr={result.stderr}"
        self.assertEqual(result.returncode, 0, detail)

        static_tokens, violations = keel_checks.check_budget(REPO_ROOT)
        self.assertEqual(violations, [], detail)
        cap_bytes, injection_tokens = keel_checks.session_injection_tokens()
        worst_case = static_tokens + injection_tokens

        static_match = self.STATIC_RE.search(result.stdout)
        injection_match = self.INJECTION_RE.search(result.stdout)
        floor_match = self.FLOOR_RE.search(result.stdout)
        self.assertIsNotNone(static_match, detail)
        self.assertIsNotNone(injection_match, detail)
        self.assertIsNotNone(floor_match, detail)

        self.assertEqual(int(static_match.group(1)), static_tokens, detail)
        self.assertEqual(int(static_match.group(2)), keel_checks.BUDGET_TOKEN_LIMIT, detail)
        self.assertEqual(int(injection_match.group(1)), injection_tokens, detail)
        self.assertEqual(int(injection_match.group(2)), cap_bytes, detail)
        self.assertEqual(int(floor_match.group(1)), worst_case, detail)

        # Pinned against this repository's own measurement (R9).
        self.assertEqual(static_tokens, 1222, detail)
        self.assertEqual(injection_tokens, 1024, detail)
        self.assertEqual(worst_case, 2246, detail)

    def test_lowering_the_cap_lowers_only_the_two_new_figures(self) -> None:
        """R16: the report moves the moment the cap does; the gated figure
        and the exit code never do."""
        default_result = self._run({})
        lowered_result = self._run({"KEEL_INJECT_CAP_BYTES": "8"})

        self.assertEqual(default_result.returncode, 0, default_result.stdout)
        self.assertEqual(lowered_result.returncode, 0, lowered_result.stdout)

        default_static = self.STATIC_RE.search(default_result.stdout)
        lowered_static = self.STATIC_RE.search(lowered_result.stdout)
        default_injection = self.INJECTION_RE.search(default_result.stdout)
        lowered_injection = self.INJECTION_RE.search(lowered_result.stdout)
        default_floor = self.FLOOR_RE.search(default_result.stdout)
        lowered_floor = self.FLOOR_RE.search(lowered_result.stdout)
        for match in (
            default_static, lowered_static, default_injection,
            lowered_injection, default_floor, lowered_floor,
        ):
            self.assertIsNotNone(match)

        # Figure 1 (static, gated) is untouched by the injection cap.
        self.assertEqual(default_static.group(1), lowered_static.group(1))
        self.assertEqual(default_static.group(2), lowered_static.group(2))

        # Figures 2 and 3 move down with a lower cap.
        self.assertEqual(lowered_injection.group(2), "8")
        self.assertLess(int(lowered_injection.group(1)), int(default_injection.group(1)))
        self.assertLess(int(lowered_floor.group(1)), int(default_floor.group(1)))

        # The exit code is unaffected either way (figure 3 gates nothing).
        self.assertEqual(default_result.returncode, lowered_result.returncode)


# --------------------------------------------------------------------- arming


class TestKeelIsArmedOnItself(unittest.TestCase):
    """D6: the Phase 1 exit gate is keel arming its own repository.

    THESE ASSERTIONS INVERT IN A PUBLISHED CUT, they are not skipped there.
    Ratified 2026-08-31
    (`.keel/decisions/2026-08-31-the-shipped-product-is-not-armed.md`): a cut
    ships NO arming file, because arming is the adopter's own act. "Unarmed" is
    therefore a shipped PROPERTY of the product, and a property worth proving
    is worth proving in the tree that ships it — so in a cut this class asserts
    the tree is NOT armed and that the template IS present, rather than
    excusing the cut from checking anything. Skipping would let a cut that
    accidentally shipped armed pass silently, which is the whole failure this
    decision exists to prevent.
    """

    def test_the_arming_file_exists_at_tier_two(self) -> None:
        if is_published_cut(REPO_ROOT):
            self.assertFalse(
                POLICY.is_file(),
                f"a published cut must ship UNARMED, but an arming file is at "
                f"{POLICY} — arming is the adopter's own act",
            )
            self.assertFalse(keel_gate.is_armed(REPO_ROOT))
            return
        self.assertTrue(POLICY.is_file(), f"no arming file at {POLICY}")
        self.assertEqual(keel_gate.policy_tier(REPO_ROOT), 2)
        self.assertTrue(keel_gate.is_armed(REPO_ROOT))

    def test_the_arming_file_carries_the_routing_defaults(self) -> None:
        # In a cut the same content requirements are checked against the
        # TEMPLATE, which is what an adopter will actually arm from — so a cut
        # shipping a gutted template fails here rather than passing vacuously.
        source = (
            REPO_ROOT / "templates" / "keel-policy.md"
            if is_published_cut(REPO_ROOT)
            else POLICY
        )
        self.assertTrue(source.is_file(), f"no policy source at {source}")
        text = source.read_text(encoding="utf-8")
        for tier in ("`fast`", "`standard`", "`deep`"):
            self.assertIn(tier, text)
        for agent in ("`researcher`", "`executor`", "`executor-deep`"):
            self.assertIn(agent, text)
        self.assertIn("## Routing", text)
        self.assertIn("## Kill switches", text)
        self.assertIn("## Holds", text)

    def test_the_state_directories_are_tracked(self) -> None:
        for relative in (".keel/audit/.gitkeep", ".keel/plans/.gitkeep"):
            with self.subTest(path=relative):
                self.assertTrue((REPO_ROOT / relative).is_file(), relative)

    def test_only_the_cache_is_ignored(self) -> None:
        """The record stays in git; the rebuildable cache does not."""
        ignored = [
            line.strip()
            for line in GITIGNORE.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        keel_rules = [rule for rule in ignored if ".keel" in rule]
        self.assertEqual(keel_rules, [".keel/cache/"], ignored)
        result = subprocess.run(
            ["git", "check-ignore", "-v", ".keel/keel-policy.md", ".keel/plans/.gitkeep",
             ".keel/audit/.gitkeep"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1, f"a record path is gitignored: {result.stdout}")

    def test_the_suite_does_not_write_into_keels_own_record(self) -> None:
        """Arming keel on keel makes .keel/audit/ a real file, not a scratch pad.

        A hook run with an unparseable payload falls back to the process's own
        working directory; run from the repository root that appended a spike
        line to this repository's audit log on every test run. The guard is
        structural: no test may leave the repository's own record different
        from how it found it.

        KEEL ADDITION (T349, fixing BL1): raw before/after byte equality
        flaked under full-suite load, because this repository is an ARMED,
        LIVE session while the suite runs - the session's own hooks keep
        appending real lines to this exact file across the ~seconds this
        subprocess call takes, and a legitimate concurrent append is not this
        test writing into the record. ``cmd_spike`` stamps every line it
        writes with ``keel_hook.SPIKE_EVENT`` (``hooks/keel_hook.py``), so
        the precise claim - "this action added no line of its own" - is
        checked by that marker rather than by raw length/bytes, and the
        append-only guarantee (nothing already written may move) is checked
        separately.

        KEEL ADDITION (T349, from the tests review): the marker is IMPORTED,
        never spelled here. A hand-copied literal would leave this test
        scanning for a string production no longer writes the moment anyone
        renamed it - finding nothing, passing, and protecting nothing.
        """
        audit = REPO_ROOT / ".keel" / "audit" / "keel-audit.jsonl"
        before_bytes = audit.read_bytes() if audit.is_file() else b""
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, "-B", str(REPO_ROOT / "hooks" / "keel_hook.py"), "spike"],
                input="not json at all {{{",
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=clean_env(Path(tmp)),
                cwd=tmp,
                timeout=60,
                check=False,
            )
        after_bytes = audit.read_bytes() if audit.is_file() else b""
        self.assertTrue(
            after_bytes.startswith(before_bytes),
            "the real audit log is append-only - earlier bytes moved",
        )
        appended = after_bytes[len(before_bytes) :].decode("utf-8")
        appended_lines = [json.loads(line) for line in appended.splitlines() if line.strip()]
        leaked = [
            line for line in appended_lines
            if line.get("event") == keel_hook.SPIKE_EVENT
        ]
        self.assertEqual(
            leaked, [], "the spike subprocess wrote a line of its own into the real audit log"
        )

    def test_the_survey_reports_tier_two_armed_and_no_conflict(self) -> None:
        """The fixture home is the premise this test owns since T167: the
        conflict set is derived from the PreToolUse/Stop registrations the scan
        can see, and the user-wide settings file is one of them - so a machine
        that registers another stack globally would answer this question about
        itself rather than about this repository. With a home that registers
        nothing, the only stopping registrations in scope are keel's own
        manifest, and they must read as keel's own."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "fixture-home"
            (home / ".claude").mkdir(parents=True)
            report = keel_survey.survey(REPO_ROOT, home=home)
        if is_published_cut(REPO_ROOT):
            # A cut ships unarmed but still ADOPTED - .keel/ is present, which
            # is what capture keys on. Both halves asserted, because "unarmed"
            # and "not adopted" are different facts and only one is true here.
            self.assertFalse(report["arming"]["armed"])
            self.assertNotEqual(report["arming"]["tier"], 2)
        else:
            self.assertEqual(report["arming"]["tier"], 2)
            self.assertTrue(report["arming"]["armed"])
            self.assertTrue(report["arming"]["adopted"])
        self.assertEqual(
            report["conflicts"], [], "no foreign gate stack is armed in this repository"
        )
        line = keel_survey.startup_line(report)
        print(f"\n{line}")
        self.assertIn("unarmed" if is_published_cut(REPO_ROOT) else "tier 2", line)
        self.assertIn("no conflicts", line)

    def test_the_startup_survey_runs_at_the_repository_root(self) -> None:
        """Run through the CLI, which resolves the user's home itself - so the
        fixture home is handed to the SUBPROCESS the only way a subprocess
        takes one, through the environment (``USERPROFILE`` on Windows,
        ``HOME`` elsewhere; both are set, so neither platform inherits the
        machine's real registrations into this assertion)."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "fixture-home"
            (home / ".claude").mkdir(parents=True)
            result = run_cli(
                ["survey", "--project", str(REPO_ROOT), "--startup"],
                REPO_ROOT,
                HOME=str(home),
                USERPROFILE=str(home),
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "unarmed" if is_published_cut(REPO_ROOT) else "tier 2", result.stdout
        )
        self.assertIn("no conflicts", result.stdout)


# ------------------------------------------------------------------ contracts


class TestWave3DeclaredFailurePolicy(unittest.TestCase):
    """R3 / convention 12, extended to the wave-3 modules."""

    def test_every_new_file_declares_a_policy(self) -> None:
        expected = {
            "scripts/keel_dashboard.py": "FAIL-CLOSED",
            "scripts/keel_records.py": "FAIL-CLOSED",
            "tests/test_keel_wave3.py": "FAIL-CLOSED",
        }
        for relative, policy in expected.items():
            with self.subTest(file=relative):
                source = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(policy, source.split('"""')[1], relative)

    def test_records_fails_closed_when_it_cannot_run(self) -> None:
        """The declaration, observed: an unusable argument is 2, not a clean bill."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keel_records.main(["--project", tmp, "--today", "31-12-2026"]), 2)

    def test_dashboard_fails_closed_when_it_cannot_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(keel_dashboard.main(["--project", tmp]), 2)

    def test_every_command_is_reachable_from_the_cli(self) -> None:
        import keel  # noqa: PLC0415 - imported after the path insert above

        self.assertEqual(
            set(keel.COMMANDS),
            {
                "survey",
                "doctor",
                "attest",
                "leak-check",
                "records",
                "index",
                "chart",
                "dashboard",
                "debt",
                "review",
            },
        )
        usage = keel.usage()
        for name in keel.COMMANDS:
            self.assertIn(name, usage)


if __name__ == "__main__":
    unittest.main()
