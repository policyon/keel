#!/usr/bin/env python3
"""T28-T31 - the viewer's second attention pass on ``scripts/keel_dashboard.py``.

Contract
--------
Reads   : temporary directories this file creates, and nothing else - no
          fixture here touches this repository's own ``.keel/``.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers
-----------------
T28 (superseded) the viewer's port stays EPHEMERAL - never derived from the
    project path, a user id or anything else (R19) - the same "cannot bind
    at all" exit-2 contract is unchanged, a port hint (pid, start time) is
    written into ``.keel/cache/`` and removed on a clean exit, and the
    address-reuse fix found while building the reverted derived-port scheme
    is kept independently of it. See
    ``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``;
T35 that hint is ONE FILE PER VIEWER, named for its own pid and port: written
    once with nothing read on the write path, deleted only by the process
    that wrote it and only its own file, and read back by ``read_hints``,
    which reports what it could not parse as a COUNT beside the viewers it
    could rather than as an empty directory. Rubbish in the cache - corrupt,
    wrongly shaped, or nested deeply enough to raise ``RecursionError`` out
    of ``json.loads`` - may stop no start, no serve and no clean stop, and
    may never change the documented pair of exit codes;
T29 the document title carries ``counts.attention``;
T30 an OPEN item's quiet-time is phase-aware (a short threshold between
    tool calls, a much longer one while a tool is presumed running), an open
    hand-off claims only what the record can say is ITS OWN, and the page
    states plainly that the whole signal is inferred;
T31 the payload settles on ONE discriminator name (``row_kind``) and ONE
    agent-type name (``agent_type``) across every row kind, renders the
    already-redacted ``detail``/``prompt_head`` fields, shows a task's own
    ``Accept:`` text and a terminal-against-total progress figure, and adds
    a delegation roster.

Values, not substrings
-----------------------
There is no JavaScript engine here, so a test that reads the served page can
only prove the page CONTAINS some text - never that the page computes
anything. Every decision that a server can make is therefore made in
``keel_dashboard`` (see its "What the server decides" section) and asserted
HERE as a VALUE: the title string, the roster's label, the quiet-time phase,
its threshold and its wording, a feed row's detail line, the ledger's
outcome, and the fingerprint the redraw gate compares. A handful of
assertions genuinely can only be substrings - that the page ASSIGNS the
title rather than composing one, that it calls no Notifications API, that
its two timers exist - and each of those says so in its own docstring
instead of reading as coverage of behaviour it cannot reach.

Failure policy
--------------
FAIL-CLOSED, as every build gate is.

Constraints
-----------
Python 3.10+, standard library only. The only sockets opened are loopback
listeners on an ephemeral port (R19), driven only from 127.0.0.1.
"""

from __future__ import annotations

import json
import re
import socket
import sys
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_dashboard  # noqa: E402  (path must be set first)

HTTP_TIMEOUT = 20


def _project(root: Path, audit_lines: list[dict[str, Any]], ledger_text: str | None = None) -> Path:
    """A minimal adopted project carrying the given audit lines and ledger."""
    project = root / "project"
    (project / ".keel" / "plans").mkdir(parents=True)
    (project / ".keel" / "audit").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    (project / ".keel" / "plans" / "keel-plan-abcdef12.md").write_text(
        ledger_text if ledger_text is not None else "# ledger\n\n- [ ] T1: a task | route: executor\n",
        encoding="utf-8",
    )
    with open(
        project / ".keel" / "audit" / "keel-audit.jsonl", "w", encoding="utf-8", newline="\n"
    ) as handle:
        for line in audit_lines:
            handle.write(json.dumps(line) + "\n")
    return project


class DashboardServer:
    """A running viewer on its ephemeral port, for one test's life."""

    def __init__(self, project: Path) -> None:
        self.server: ThreadingHTTPServer = keel_dashboard.build_server(project)
        self.url = keel_dashboard.server_url(self.server)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def request(self, method: str, route: str) -> tuple[int, bytes, Any]:
        req = urllib.request.Request(self.url.rstrip("/") + route, method=method)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), exc.headers

    def state(self) -> dict[str, Any]:
        status, body, _ = self.request("GET", "/api/state")
        assert status == 200, body
        return json.loads(body.decode("utf-8"))

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=HTTP_TIMEOUT)


def _page(project: Path) -> str:
    """The page as a browser would receive it, over a real loopback fetch."""
    server = DashboardServer(project)
    try:
        status, body, _ = server.request("GET", "/")
    finally:
        server.close()
    assert status == 200, status
    return body.decode("utf-8")


# ------------------------------------------------------------------- T28 port


class TestNoPortIsDerived(unittest.TestCase):
    """R19 stands: nothing here computes a port from the project path, a
    user id, or anything else. See
    ``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``."""

    def test_the_derivation_mechanism_is_actually_gone_not_just_unused(self) -> None:
        for name in (
            "derived_port",
            "PORT_RANGE_START",
            "PORT_RANGE_SIZE",
            "PORT_FALLBACK_ATTEMPTS",
        ):
            self.assertFalse(hasattr(keel_dashboard, name), f"{name} still exists")

    def test_build_server_always_asks_the_os_for_port_zero_whatever_the_project(self) -> None:
        """The one place a port could be computed - the address handed to
        the underlying server class - is always the literal ``(HOST, 0)``,
        regardless of the project's path. Deterministic, unlike "two runs
        landed on different ports", which an unlucky OS could coincide on.
        """
        seen_addresses: list[tuple[str, int]] = []
        original = keel_dashboard._KeelHTTPServer

        class _Capturing(original):  # type: ignore[misc]
            def __init__(self, address: tuple[str, int], handler: Any) -> None:
                seen_addresses.append(address)
                super().__init__(address, handler)

        with tempfile.TemporaryDirectory() as tmp:
            projects = [
                _project(Path(tmp) / "alpha", []),
                _project(Path(tmp) / "a-very-differently-named-project-xyz", []),
            ]
            with unittest.mock.patch.object(keel_dashboard, "_KeelHTTPServer", _Capturing):
                servers = [keel_dashboard.build_server(p) for p in projects]
            try:
                self.assertEqual(seen_addresses, [(keel_dashboard.HOST, 0)] * len(projects))
            finally:
                for server in servers:
                    server.server_close()

    def test_two_viewers_for_the_same_project_get_different_ephemeral_ports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            first = DashboardServer(project)
            second = DashboardServer(project)
            try:
                first_port = first.server.server_address[1]
                second_port = second.server.server_address[1]
                self.assertNotEqual(first_port, second_port, "two viewers collided on one port")
                for port in (first_port, second_port):
                    self.assertNotEqual(port, 0, "an ephemeral bind still resolves to a port")
            finally:
                first.close()
                second.close()

    def test_main_still_exits_2_when_it_cannot_bind_at_all(self) -> None:
        """The "cannot bind at all" contract is unchanged: a bind failure
        still fails closed, with no fallback window to exhaust first."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with unittest.mock.patch.object(
                keel_dashboard, "_KeelHTTPServer", side_effect=OSError("address in use")
            ):
                self.assertEqual(keel_dashboard.main(["--project", str(project)]), 2)


class TestReuseAddressDisabled(unittest.TestCase):
    """The reuse-address fix kept from the reverted work (T28): without it,
    a second process can silently bind a port a first one is still
    listening on, on Windows, with no ``OSError`` raised to report it."""

    def test_allow_reuse_address_is_off(self) -> None:
        self.assertFalse(keel_dashboard._KeelHTTPServer.allow_reuse_address)

    def test_binding_an_already_listening_port_again_raises_instead_of_silently_succeeding(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            first = DashboardServer(project)
            try:
                port = first.server.server_address[1]
                handler = type(
                    "BoundKeelDashboardHandler",
                    (keel_dashboard.KeelDashboardHandler,),
                    {"project": project},
                )
                with self.assertRaises(OSError):
                    keel_dashboard._KeelHTTPServer((keel_dashboard.HOST, port), handler)
            finally:
                first.close()


# ------------------------------------------------- T28/T35 the port hint files


DEEPLY_NESTED_JSON = "[" * 100_000 + "]" * 100_000
"""Valid JSON that ``json.loads`` cannot parse: it raises ``RecursionError``,
which is a ``RuntimeError`` and NOT an ``OSError``, so a guard written for
filesystem trouble lets it straight through."""


def _cache_file(project: Path, name: str, text: str) -> Path:
    """Drop a raw file into the hint directory, as a crashed viewer, another
    tool, or a corruption would leave it."""
    path = keel_dashboard.hint_dir(project) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _hint_text(pid: int, port: int, started_at: str = "2026-08-10T09:00:00Z") -> str:
    """A well-formed hint file's body, exactly as a viewer writes it."""
    return json.dumps(
        {
            "hint": True,
            "note": keel_dashboard.HINT_NOTE,
            "url": f"http://{keel_dashboard.HOST}:{port}/",
            "port": port,
            "pid": pid,
            "started_at": started_at,
        }
    )


def _a_port_nobody_is_listening_on() -> int:
    """An ephemeral port bound and immediately released - the situation a
    KILLED viewer leaves behind: a hint file naming a port that answers
    nothing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((keel_dashboard.HOST, 0))
        return int(probe.getsockname()[1])


class TestPortHint(unittest.TestCase):
    """``.keel/cache/`` carries ONE HINT FILE PER VIEWER (T35), written by the
    process it describes and deleted by that same process - never a contract,
    never a shared list, and never anything ``build_server`` alone touches
    (the library stays pure; only ``main`` writes)."""

    def test_build_server_alone_writes_no_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            try:
                self.assertEqual(keel_dashboard.read_hints(project), ([], 0, False))
            finally:
                server.server_close()

    def test_write_hint_records_port_pid_and_start_time_and_says_it_is_a_hint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                self.assertIsNotNone(hint)
                assert hint is not None
                port = server.server_address[1]
                self.assertEqual(hint.path, keel_dashboard.hint_path(project, hint.pid, port))
                self.assertEqual(hint.path.name, f"keel-dashboard-hint-{hint.pid}-{port}.json")
                self.assertEqual(hint.port, port)
                payload = json.loads(hint.path.read_text(encoding="utf-8"))
                self.assertTrue(payload.get("hint"))
                self.assertIn("hint", payload["note"].lower())
                self.assertIn("probe", payload["note"].lower())
                self.assertEqual(payload["port"], port)
                self.assertEqual(payload["url"], keel_dashboard.server_url(server))
                self.assertIn("pid", payload)
                self.assertIn("started_at", payload)
            finally:
                keel_dashboard.remove_hint(hint)
                server.server_close()

    def test_the_payload_carries_nothing_about_the_machine_or_the_session(self) -> None:
        """Minimal by contract: a port, a pid, a start time, a loopback url
        and the note. No project path, no session id, no home directory -
        a hint that leaked those would be a worse screenshot risk than the
        page this module spends its redaction on."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                assert hint is not None
                body = hint.path.read_text(encoding="utf-8")
                payload = json.loads(body)
                self.assertEqual(
                    set(payload),
                    {"hint", "note", "url", "port", "pid", "started_at"},
                )
                for leaked in (str(project), str(Path.home()), Path.home().name):
                    self.assertNotIn(leaked, body)
            finally:
                keel_dashboard.remove_hint(hint)
                server.server_close()

    def test_remove_hint_deletes_its_own_file_and_leaves_no_viewers_behind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                assert hint is not None
                self.assertTrue(hint.path.exists())
                keel_dashboard.remove_hint(hint)
                self.assertFalse(hint.path.exists())
                self.assertEqual(keel_dashboard.read_hints(project), ([], 0, False))
            finally:
                server.server_close()

    def test_remove_hint_of_none_is_a_no_op(self) -> None:
        keel_dashboard.remove_hint(None)  # must not raise

    def test_a_second_viewer_does_not_disturb_the_first_and_leaves_it_discoverable(self) -> None:
        """The finding's exact scenario: two viewers, ONE project, and the
        SECOND one stops. Both write their own file, so registering the
        second cannot touch the first's, and stopping the second removes one
        path and reads nothing.

        Asserted end to end: while both run each has its own file; after the
        second exits, the first is still listed, its port is its own, its
        file is untouched byte for byte, and the url the hint names actually
        answers a request.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            first = DashboardServer(project)
            second = DashboardServer(project)
            first_hint = keel_dashboard.write_hint(project, first.server)
            first_bytes = first_hint.path.read_bytes() if first_hint else b""
            second_hint = keel_dashboard.write_hint(project, second.server)
            try:
                assert first_hint is not None and second_hint is not None
                self.assertNotEqual(first_hint.path, second_hint.path)
                self.assertEqual(
                    first_hint.path.read_bytes(),
                    first_bytes,
                    "registering the second viewer rewrote the first viewer's file",
                )
                scan = keel_dashboard.read_hints(project)
                self.assertEqual(
                    {entry["port"] for entry in scan.viewers},
                    {first_hint.port, second_hint.port},
                )
                self.assertEqual((scan.unreadable, scan.listing_failed), (0, False))

                keel_dashboard.remove_hint(second_hint)

                scan = keel_dashboard.read_hints(project)
                self.assertEqual(len(scan.viewers), 1, "stopping one viewer erased the other")
                self.assertEqual(scan.viewers[0]["port"], first_hint.port)
                self.assertTrue(first_hint.path.exists())
                self.assertFalse(second_hint.path.exists())
                # A reader can still FIND the live viewer, which is the whole
                # point of the file: probe the url it names.
                with urllib.request.urlopen(
                    scan.viewers[0]["url"], timeout=HTTP_TIMEOUT
                ) as response:
                    self.assertEqual(response.status, 200)
            finally:
                keel_dashboard.remove_hint(first_hint)
                first.close()
                second.close()

    def test_remove_hint_never_deletes_a_file_another_process_wrote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            foreign = _cache_file(
                project,
                keel_dashboard.hint_filename(999_999, 65_000),
                _hint_text(999_999, 65_000),
            )
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                assert hint is not None
                keel_dashboard.remove_hint(hint)
                self.assertTrue(foreign.exists(), "another process's file was deleted")
                scan = keel_dashboard.read_hints(project)
                self.assertEqual([entry["pid"] for entry in scan.viewers], [999_999])
            finally:
                server.server_close()

    def test_a_re_registration_of_one_viewer_rewrites_only_its_own_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            second = None
            try:
                first = keel_dashboard.write_hint(project, server)
                second = keel_dashboard.write_hint(project, server)
                self.assertEqual(first, second)
                scan = keel_dashboard.read_hints(project)
                self.assertEqual(len(scan.viewers), 1)
                self.assertEqual((scan.unreadable, scan.listing_failed), (0, False))
            finally:
                keel_dashboard.remove_hint(second)
                server.server_close()

    def test_files_left_by_killed_viewers_neither_hide_a_live_one_nor_stop_a_start(self) -> None:
        """Nothing prunes another process's file, deliberately (see the module
        docstring): a killed viewer's file simply stays, and a reader judges
        it by probing. What must hold is that a directory full of them costs
        a new viewer nothing and hides nobody."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            for index in range(60):
                _cache_file(
                    project,
                    keel_dashboard.hint_filename(500_000 + index, 9_000 + index),
                    _hint_text(500_000 + index, 9_000 + index),
                )
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                assert hint is not None
                scan = keel_dashboard.read_hints(project)
                self.assertEqual(len(scan.viewers), 61)
                self.assertEqual((scan.unreadable, scan.listing_failed), (0, False))
                self.assertIn(hint.port, [entry["port"] for entry in scan.viewers])
            finally:
                keel_dashboard.remove_hint(hint)
                server.server_close()

    def test_an_absent_cache_reads_as_no_viewers_and_not_as_a_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            scan = keel_dashboard.read_hints(project)
            self.assertEqual((scan.viewers, scan.unreadable, scan.listing_failed), ([], 0, False))

    def test_a_listing_failure_is_reported_as_a_loss_not_as_an_empty_directory(self) -> None:
        """"The directory cannot be read" and "no viewer is running" are
        different answers, and only one of them is safe to act on."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            keel_dashboard.hint_dir(project).mkdir(parents=True, exist_ok=True)
            with unittest.mock.patch.object(
                Path, "iterdir", side_effect=PermissionError("cache directory is not readable")
            ):
                scan = keel_dashboard.read_hints(project)
            self.assertEqual((scan.viewers, scan.unreadable), ([], 0))
            self.assertTrue(scan.listing_failed)

    def test_a_corrupt_file_beside_a_good_one_leaves_the_good_viewer_discoverable(self) -> None:
        """Defect 1, made impossible: rubbish in the directory costs exactly
        the rubbish. The live viewer is still listed, still probeable, and
        the unreadable files are COUNTED rather than folded into an empty
        list that would read as "nothing is running"."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            live = DashboardServer(project)
            hint = keel_dashboard.write_hint(project, live.server)
            try:
                assert hint is not None
                rubbish = {
                    # not JSON at all
                    keel_dashboard.hint_filename(111, 1_111): "{not json at all",
                    # JSON, but not a mapping
                    keel_dashboard.hint_filename(222, 2_222): "[1, 2, 3]",
                    # a mapping whose port is the wrong type
                    keel_dashboard.hint_filename(333, 3_333): json.dumps(
                        {"url": "http://127.0.0.1:3333/", "port": "3333", "pid": 333}
                    ),
                    # a mapping naming a host this module would never bind
                    keel_dashboard.hint_filename(444, 4_444): json.dumps(
                        {
                            "url": "http://example.invalid:4444/",
                            "port": 4_444,
                            "pid": 444,
                            "started_at": "2026-08-10T09:00:00Z",
                        }
                    ),
                    # a well-formed body under somebody else's filename
                    keel_dashboard.hint_filename(555, 5_555): _hint_text(666, 6_666),
                    # nested past what json.loads can parse without raising
                    keel_dashboard.hint_filename(777, 7_777): DEEPLY_NESTED_JSON,
                }
                for name, text in rubbish.items():
                    _cache_file(project, name, text)

                scan = keel_dashboard.read_hints(project)
                self.assertEqual(
                    [entry["port"] for entry in scan.viewers],
                    [hint.port],
                    "a corrupt file hid a viewer that was still serving",
                )
                self.assertEqual(scan.unreadable, len(rubbish))
                self.assertFalse(scan.listing_failed)
                self.assertNotEqual(
                    (scan.viewers, scan.unreadable),
                    ([], 0),
                    "rubbish must never be reportable as an empty directory",
                )
                with urllib.request.urlopen(
                    scan.viewers[0]["url"], timeout=HTTP_TIMEOUT
                ) as response:
                    self.assertEqual(response.status, 200)
            finally:
                keel_dashboard.remove_hint(hint)
                live.close()

    def test_a_stale_file_from_a_dead_process_is_distinguishable_from_a_live_one(self) -> None:
        """A killed viewer's file stays behind by design, so a reader must be
        able to tell it from a live one - by probing the url, exactly as the
        note it carries says, and by its own started_at."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            dead_port = _a_port_nobody_is_listening_on()
            _cache_file(
                project,
                keel_dashboard.hint_filename(999_999, dead_port),
                _hint_text(999_999, dead_port, started_at="2020-01-01T00:00:00Z"),
            )
            live = DashboardServer(project)
            hint = keel_dashboard.write_hint(project, live.server)
            try:
                assert hint is not None
                scan = keel_dashboard.read_hints(project)
                self.assertEqual(len(scan.viewers), 2, "both files are reported; neither is judged")
                by_port = {entry["port"]: entry for entry in scan.viewers}
                self.assertEqual(set(by_port), {dead_port, hint.port})
                # Probing tells them apart, which is the contract the file states.
                with urllib.request.urlopen(
                    by_port[hint.port]["url"], timeout=HTTP_TIMEOUT
                ) as response:
                    self.assertEqual(response.status, 200)
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(by_port[dead_port]["url"], timeout=HTTP_TIMEOUT)
                # And so does age, without probing at all.
                self.assertEqual(by_port[dead_port]["started_at"], "2020-01-01T00:00:00Z")
                self.assertGreater(
                    by_port[hint.port]["started_at"], by_port[dead_port]["started_at"]
                )
                self.assertEqual(by_port[dead_port]["pid"], 999_999)
            finally:
                keel_dashboard.remove_hint(hint)
                live.close()

    def test_the_write_path_reads_nothing_at_all(self) -> None:
        """Defect 2, made impossible rather than handled. The old shape read
        the shared file before rewriting it, so an unparseable read meant
        "no other viewers" and registering erased every one of them. With
        every read primitive booby-trapped, registration still succeeds -
        because it performs none."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            _cache_file(project, keel_dashboard.hint_filename(888, 8_888), DEEPLY_NESTED_JSON)
            server = keel_dashboard.build_server(project)
            hint = None
            try:
                with unittest.mock.patch.object(
                    Path, "read_text", side_effect=AssertionError("the write path read a file")
                ):
                    with unittest.mock.patch.object(
                        Path, "iterdir", side_effect=AssertionError("the write path listed a dir")
                    ):
                        with unittest.mock.patch.object(
                            keel_dashboard.json,
                            "loads",
                            side_effect=AssertionError("the write path parsed JSON"),
                        ):
                            hint = keel_dashboard.write_hint(project, server)
                self.assertIsNotNone(hint, "registration touched a file it does not own")
                assert hint is not None
                self.assertTrue(hint.path.exists())
            finally:
                keel_dashboard.remove_hint(hint)
                server.server_close()

    def test_the_remove_path_reads_nothing_and_touches_one_path(self) -> None:
        """The same proof for deregistration: no read, no remainder, no
        directory-wide decision - one unlink of one path this process wrote."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            other = _cache_file(
                project, keel_dashboard.hint_filename(888, 8_888), DEEPLY_NESTED_JSON
            )
            server = keel_dashboard.build_server(project)
            try:
                hint = keel_dashboard.write_hint(project, server)
                assert hint is not None
                with unittest.mock.patch.object(
                    Path, "read_text", side_effect=AssertionError("the remove path read a file")
                ):
                    with unittest.mock.patch.object(
                        Path, "iterdir", side_effect=AssertionError("the remove path listed a dir")
                    ):
                        keel_dashboard.remove_hint(hint)
                self.assertFalse(hint.path.exists())
                self.assertTrue(other.exists(), "a file this process never wrote was removed")
            finally:
                server.server_close()

    def test_main_writes_the_hint_on_start_and_removes_it_on_clean_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            seen_during_serve: dict[str, Any] = {"scan": None}
            real_write_hint = keel_dashboard.write_hint
            written: list[Path] = []

            def _spy(p: Path, server: ThreadingHTTPServer) -> Any:
                result = real_write_hint(p, server)
                if result is not None:
                    written.append(result.path)
                seen_during_serve["scan"] = keel_dashboard.read_hints(p)
                return result

            def _raise_keyboard_interrupt(self: ThreadingHTTPServer) -> None:
                raise KeyboardInterrupt()

            with unittest.mock.patch.object(keel_dashboard, "write_hint", _spy):
                with unittest.mock.patch.object(
                    ThreadingHTTPServer, "serve_forever", _raise_keyboard_interrupt
                ):
                    self.assertEqual(keel_dashboard.main(["--project", str(project)]), 0)

            self.assertEqual(len(seen_during_serve["scan"].viewers), 1, "listed while serving")
            self.assertEqual(len(written), 1)
            self.assertFalse(written[0].exists(), "the hint must be gone after a clean stop")
            self.assertEqual(keel_dashboard.read_hints(project).viewers, [])

    def test_a_cache_full_of_rubbish_stops_neither_a_start_a_serve_nor_a_clean_stop(self) -> None:
        """Defect 3, made impossible: ``json.loads`` raises ``RecursionError``
        on the nested file, which is not an ``OSError``. Here the viewer
        starts with that file in the directory, answers a REAL loopback
        request, stops on Ctrl-C, returns the documented 0 and takes its own
        file with it - leaving every rubbish file exactly where it was."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            rubbish = [
                _cache_file(project, keel_dashboard.hint_filename(1, 1), DEEPLY_NESTED_JSON),
                _cache_file(project, keel_dashboard.hint_filename(2, 2), "{not json at all"),
                _cache_file(project, keel_dashboard.hint_filename(3, 3), ""),
                _cache_file(project, "keel-dashboard-hint.json", '{"viewers": "not a list"}'),
            ]
            answered: dict[str, Any] = {}
            written: list[Path] = []
            real_write_hint = keel_dashboard.write_hint

            def _spy(p: Path, server: ThreadingHTTPServer) -> Any:
                result = real_write_hint(p, server)
                if result is not None:
                    written.append(result.path)
                return result

            def _serve_one_request_then_interrupt(server: ThreadingHTTPServer) -> None:
                url = keel_dashboard.server_url(server)

                def _fetch() -> None:
                    try:
                        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
                            answered["status"] = response.status
                    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                        answered["error"] = repr(exc)

                client = threading.Thread(target=_fetch, daemon=True)
                client.start()
                server.handle_request()
                client.join(timeout=HTTP_TIMEOUT)
                raise KeyboardInterrupt()

            with unittest.mock.patch.object(keel_dashboard, "write_hint", _spy):
                with unittest.mock.patch.object(
                    ThreadingHTTPServer, "serve_forever", _serve_one_request_then_interrupt
                ):
                    exit_code = keel_dashboard.main(["--project", str(project)])

            self.assertEqual(exit_code, 0, "a corrupt cache changed the exit code")
            self.assertEqual(answered.get("status"), 200, answered)
            self.assertEqual(len(written), 1)
            self.assertFalse(written[0].exists(), "its own file must be gone after a clean stop")
            for path in rubbish:
                self.assertTrue(path.exists(), f"{path.name} was deleted by a viewer that owns it")
            scan = keel_dashboard.read_hints(project)
            self.assertEqual(scan.viewers, [])
            self.assertEqual(scan.unreadable, 3, "the rubbish is counted, not read as an absence")

    def test_a_failure_while_removing_never_aborts_the_shutdown_or_the_exit_code(self) -> None:
        """Whatever comes out of the removal - an ``OSError`` or the
        ``RecursionError`` that used to escape the guard entirely - the
        socket is still closed and the exit code is still the documented 0."""
        for failure in (
            OSError("the cache went away"),
            RecursionError("maximum recursion depth exceeded"),
            ValueError("something else entirely"),
        ):
            with self.subTest(failure=type(failure).__name__):
                with tempfile.TemporaryDirectory() as tmp:
                    project = _project(Path(tmp), [])
                    closed: list[str] = []
                    real_close = ThreadingHTTPServer.server_close

                    def _spy_close(server: ThreadingHTTPServer) -> None:
                        closed.append("closed")
                        real_close(server)

                    def _raise_keyboard_interrupt(server: ThreadingHTTPServer) -> None:
                        raise KeyboardInterrupt()

                    with unittest.mock.patch.object(
                        ThreadingHTTPServer, "serve_forever", _raise_keyboard_interrupt
                    ):
                        with unittest.mock.patch.object(
                            ThreadingHTTPServer, "server_close", _spy_close
                        ):
                            with unittest.mock.patch.object(
                                Path, "unlink", side_effect=failure
                            ):
                                exit_code = keel_dashboard.main(["--project", str(project)])

                    self.assertEqual(exit_code, 0, "a removal failure changed the exit code")
                    self.assertEqual(closed, ["closed"], "the server was left unclosed")

    def test_an_unwritable_cache_directory_does_not_stop_the_server(self) -> None:
        """Requirement (2) of the port-hint contract: a write failure is
        reported and swallowed, never allowed to affect serving."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            server = keel_dashboard.build_server(project)
            try:
                with unittest.mock.patch.object(
                    Path, "mkdir", side_effect=OSError("read-only cache directory")
                ):
                    hint = keel_dashboard.write_hint(project, server)
                self.assertIsNone(hint)
                # The server is still alive and answering.
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    url = keel_dashboard.server_url(server)
                    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as response:
                        self.assertEqual(response.status, 200)
                finally:
                    server.shutdown()
                    thread.join(timeout=HTTP_TIMEOUT)
            finally:
                server.server_close()


# --------------------------------------------------------------- T29 title


class TestAttentionCount(unittest.TestCase):
    def test_attention_equals_the_number_of_open_items(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(state["counts"]["attention"], 2)
            self.assertEqual(state["counts"]["attention"], len(state["open"]))

    def test_attention_is_zero_with_nothing_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), []))
            self.assertEqual(state["counts"]["attention"], 0)

    def test_the_title_string_is_the_count_in_front_of_the_page_name(self) -> None:
        """The value a reader's tab would actually show, asserted directly -
        the page only assigns this string."""
        self.assertEqual(keel_dashboard.PAGE_TITLE, "keel — read-only")
        self.assertEqual(keel_dashboard.document_title({"attention": 0}), "keel — read-only")
        self.assertEqual(keel_dashboard.document_title({}), "keel — read-only")
        self.assertEqual(keel_dashboard.document_title({"attention": 3}), "(3) keel — read-only")

    def test_state_carries_the_title_a_reader_would_see(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s2"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
            self.assertEqual(state["title"], "(2) keel — read-only")
            empty = keel_dashboard.read_state(_project(Path(tmp) / "b", []))
            self.assertEqual(empty["title"], "keel — read-only")

    def test_the_page_assigns_that_title_and_calls_no_notification_api(self) -> None:
        """SUBSTRING, deliberately, and the only option here: there is no
        JavaScript engine in this suite, so what can be proven about the page
        is what it CONTAINS - that it assigns the server's title rather than
        composing one of its own, that it computes no title itself, and that
        it calls no Notifications API, requests no permission and registers
        no service worker. What the title SAYS is asserted by value above.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("document.title = s.title", text)
        self.assertNotIn("function title(", text)
        # API USAGE, not the bare word - the module's own comments name the
        # interface it does NOT call.
        self.assertNotIn("new Notification(", text)
        self.assertNotIn(".requestPermission(", text)
        self.assertNotIn("serviceWorker.register(", text)
        # The static <title> the tab shows before the first fetch returns is
        # the same string the server would send.
        self.assertIn(f"<title>{keel_dashboard.PAGE_TITLE}</title>", keel_dashboard.PAGE)


# -------------------------------------------------------------- T30 quiet-time


class TestQuietTimePhase(unittest.TestCase):
    def test_an_open_handoff_with_no_activity_is_tool_running_from_its_own_start(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        item = state["open"][0]
        self.assertEqual(item["phase"], "tool_running")
        self.assertEqual(item["last_seen_ts"], item["ts"])
        self.assertFalse(item["ambiguous"])
        self.assertEqual(
            item["quiet_threshold_seconds"], keel_dashboard.QUIET_TOOL_RUNNING_SECONDS
        )

    def test_an_open_handoff_with_activity_after_start_is_between_calls(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "unfinished"},
            {"v": 1, "ts": "2026-08-01T10:05:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
            {"v": 1, "ts": "2026-08-01T10:02:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Read"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        item = state["open"][0]
        self.assertEqual(item["phase"], "between_calls")
        self.assertEqual(item["last_seen_ts"], "2026-08-01T10:05:00Z", "the LATEST, not the first")
        self.assertFalse(item["ambiguous"], "one open hand-off of this type: nothing was guessed")
        self.assertEqual(
            item["quiet_threshold_seconds"], keel_dashboard.QUIET_BETWEEN_CALLS_SECONDS
        )

    def test_two_open_handoffs_of_one_type_claim_nothing_and_say_why(self) -> None:
        """The review finding, exactly as it was written: session s1 has two
        unmatched ``handoff_start`` lines, both ``executor`` - A at 10:00:00Z
        and B at 10:05:00Z - plus ONE activity line at 10:06:00Z.

        ``agent_type`` is a TYPE, not an identity, so the record cannot say
        which of them produced that line. A must therefore read from its OWN
        start: ``tool_running``, ``last_seen_ts == ts``, the long threshold -
        never 10:06:00Z borrowed from a sibling that may have produced it.
        The refusal is reported rather than hidden, the way an ambiguous
        grouping is reported: ``ambiguous`` is true and the note says in
        words that the record names the type, not which hand-off.
        """
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "first"},
            {"v": 1, "ts": "2026-08-01T10:05:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "second"},
            {"v": 1, "ts": "2026-08-01T10:06:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        by_description = {item["description"]: item for item in state["open"]}
        self.assertEqual(set(by_description), {"first", "second"})

        first = by_description["first"]
        self.assertEqual(first["last_seen_ts"], "2026-08-01T10:00:00Z")
        self.assertEqual(first["last_seen_ts"], first["ts"])
        self.assertEqual(first["phase"], "tool_running")
        self.assertEqual(
            first["quiet_threshold_seconds"], keel_dashboard.QUIET_TOOL_RUNNING_SECONDS
        )
        self.assertTrue(first["ambiguous"])
        self.assertIn("more than one", first["quiet_note"])
        self.assertIn("not which one ran them", first["quiet_note"])

        second = by_description["second"]
        self.assertEqual(second["last_seen_ts"], second["ts"], "B may not claim it either")
        self.assertEqual(second["phase"], "tool_running")
        self.assertTrue(second["ambiguous"])

        # The line itself is not lost - nothing consumed it, so it is still in
        # the flat feed exactly as T27 leaves an open hand-off's activity.
        flat = [row for row in state["feed"] if row["row_kind"] == "event"]
        self.assertEqual([row["event"] for row in flat], ["activity"])

    def test_the_second_of_two_same_type_handoffs_does_not_darken_the_first_s_own_evidence(
        self,
    ) -> None:
        """Ambiguity begins when the sibling OPENS, not before it. A line
        recorded while A was the only ``executor`` hand-off open IS A's, and
        stays A's when B opens afterwards - declining a line that the record
        can attribute would be as wrong as claiming one it cannot.
        """
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "first"},
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Read"},
            {"v": 1, "ts": "2026-08-01T10:05:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "second"},
            {"v": 1, "ts": "2026-08-01T10:06:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        by_description = {item["description"]: item for item in state["open"]}
        first = by_description["first"]
        self.assertEqual(first["last_seen_ts"], "2026-08-01T10:01:00Z", "its own, unambiguously")
        self.assertEqual(first["phase"], "between_calls")
        self.assertTrue(first["ambiguous"], "and it says the 10:06 line was NOT attributed")
        # T37: the rendered sentence, end to end - it must state BOTH facts
        # this row's own fields already show (a claimed earlier line AND a
        # later one declined), never the "nothing this one can claim"
        # wording that belongs to an item with no claimed line at all.
        self.assertEqual(
            first["quiet_note"],
            "no new tool call for 1m 0s since the line it already claimed - later "
            "lines were declined too: more than one executor hand-off was open when "
            "they landed, and the record names the agent type, not which one ran them",
        )
        second = by_description["second"]
        self.assertEqual(second["last_seen_ts"], second["ts"])
        self.assertEqual(second["phase"], "tool_running")

    def test_a_sibling_with_an_unreadable_start_time_cannot_be_ruled_out(self) -> None:
        """A second ``executor`` hand-off whose own ``ts`` will not parse
        cannot be placed in time, so it can never be shown NOT to have been
        open when a line landed. The first hand-off therefore claims nothing
        and says so, rather than treating "we cannot read its clock" as
        "it was not there"."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "readable"},
            {"v": 1, "ts": "not a timestamp", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "unreadable clock"},
            {"v": 1, "ts": "2026-08-01T10:06:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        first = {item["description"]: item for item in state["open"]}["readable"]
        self.assertEqual(first["last_seen_ts"], first["ts"])
        self.assertEqual(first["phase"], "tool_running")
        self.assertTrue(first["ambiguous"])

    def test_activity_recorded_before_an_open_handoff_started_is_never_its_own(self) -> None:
        """A hand-off cannot have produced something that had already
        happened - even where it is the only one of its type in the log."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Read"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "later"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        item = state["open"][0]
        self.assertEqual(item["last_seen_ts"], "2026-08-01T10:00:00Z")
        self.assertEqual(item["phase"], "tool_running")
        self.assertFalse(item["ambiguous"], "nothing was declined: nothing was a candidate")

    def test_last_seen_never_claims_activity_already_owned_by_a_closed_group(self) -> None:
        """Two `executor` hand-offs: A closes normally and takes its own
        activity with it; B stays open. B's quiet-time must not read A's
        (already-grouped) activity as though it were its own."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "first"},
            {"v": 1, "ts": "2026-08-01T09:01:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
            {"v": 1, "ts": "2026-08-01T09:02:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "first"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "second"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        self.assertEqual(len(state["open"]), 1)
        item = state["open"][0]
        self.assertEqual(item["phase"], "tool_running")
        self.assertEqual(item["last_seen_ts"], item["ts"], "A's activity must not leak into B")
        groups = [r for r in state["feed"] if r["row_kind"] == "group"]
        self.assertEqual(groups[0]["count"], 1, "A still keeps its own activity")

    def test_an_activity_line_of_another_type_is_never_this_handoffs(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "open"},
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "activity", "session": "s1",
             "agent_type": "researcher", "tool": "Read"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        item = state["open"][0]
        self.assertEqual(item["last_seen_ts"], item["ts"])
        self.assertEqual(item["phase"], "tool_running")
        self.assertFalse(item["ambiguous"])

    def test_an_open_session_reads_the_latest_event_in_the_session(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s1"},
            {"v": 1, "ts": "2026-08-01T09:10:00Z", "event": "activity", "session": "s1",
             "agent_type": "", "tool": "Write"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        item = state["open"][0]
        self.assertEqual(item["row_kind"], "open_session")
        self.assertEqual(item["phase"], "between_calls")
        self.assertEqual(item["last_seen_ts"], "2026-08-01T09:10:00Z")
        self.assertFalse(item["ambiguous"])


class TestQuietTimeThresholdsAndWording(unittest.TestCase):
    """The two thresholds and the words a crossing is stated in are chosen
    server-side, so both are values rather than page text."""

    def test_the_two_thresholds_are_named_constants_with_the_stated_figures(self) -> None:
        self.assertEqual(keel_dashboard.QUIET_BETWEEN_CALLS_SECONDS, 60)
        self.assertEqual(keel_dashboard.QUIET_TOOL_RUNNING_SECONDS, 10 * 60)
        self.assertGreater(
            keel_dashboard.QUIET_TOOL_RUNNING_SECONDS,
            keel_dashboard.QUIET_BETWEEN_CALLS_SECONDS,
            "a slow command must get the LONGER of the two",
        )

    def test_the_phase_selects_the_threshold(self) -> None:
        self.assertEqual(
            keel_dashboard.quiet_threshold_seconds("between_calls"),
            keel_dashboard.QUIET_BETWEEN_CALLS_SECONDS,
        )
        self.assertEqual(
            keel_dashboard.quiet_threshold_seconds("tool_running"),
            keel_dashboard.QUIET_TOOL_RUNNING_SECONDS,
        )

    def test_each_note_states_the_threshold_it_crossed_in_words(self) -> None:
        """EXACT strings, for all four combinations of phase and ambiguity
        (T37) - not fragments, because the sentence IS the deliverable and a
        wrong sentence must fail this test rather than merely lack one of
        several substrings."""
        self.assertEqual(
            keel_dashboard.quiet_note("tool_running", False),
            "no event since it started, past 10m 0s - a slow command is not a stall",
        )
        self.assertEqual(
            keel_dashboard.quiet_note("between_calls", False),
            "no new tool call for 1m 0s",
        )
        self.assertEqual(
            keel_dashboard.quiet_note("tool_running", True, "executor"),
            "nothing this one can claim for 10m 0s - more than one executor hand-off "
            "was open when the later lines landed, and the record names the agent "
            "type, not which one ran them",
        )
        self.assertEqual(
            keel_dashboard.quiet_note("between_calls", True, "executor"),
            "no new tool call for 1m 0s since the line it already claimed - later "
            "lines were declined too: more than one executor hand-off was open when "
            "they landed, and the record names the agent type, not which one ran them",
        )

    def test_no_note_ever_calls_an_open_item_stalled_hung_or_stuck(self) -> None:
        for phase in ("between_calls", "tool_running"):
            for ambiguous in (False, True):
                note = keel_dashboard.quiet_note(phase, ambiguous, "executor").lower()
                for word in ("stalled", "hung", "stuck"):
                    self.assertNotIn(word, note)

    def test_fmt_duration_words_a_threshold_the_way_the_page_words_elapsed(self) -> None:
        self.assertEqual(keel_dashboard.fmt_duration(45), "45s")
        self.assertEqual(keel_dashboard.fmt_duration(60), "1m 0s")
        self.assertEqual(keel_dashboard.fmt_duration(600), "10m 0s")
        self.assertEqual(keel_dashboard.fmt_duration(7500), "2h 5m")
        self.assertEqual(keel_dashboard.fmt_duration(None), "?")

    def test_the_page_states_that_the_signal_is_inferred_and_keeps_no_threshold(self) -> None:
        """SUBSTRING, deliberately: standing text on the page, and the
        ABSENCE of any second copy of a threshold there. Neither is a value
        this suite can obtain any other way - the wording is what a reader
        sees, and "the page keeps no constant of its own" is a claim about
        the page's source by definition.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("quiet-time is INFERRED from gaps in the log, never measured", text)
        self.assertIn("where two hand-offs of one agent type are open at once it does not", text)
        self.assertNotIn("QUIET_BETWEEN_CALLS_MS", text)
        self.assertNotIn("QUIET_TOOL_RUNNING_MS", text)
        self.assertIn("o.quiet_threshold_seconds", text)
        self.assertIn("o.quiet_note", text)


class TestRedrawGate(unittest.TestCase):
    """The equality check that ignores the timestamp (T30), decided here as
    a fingerprint rather than in the page as a comparison."""

    def test_two_reads_of_an_unchanged_project_agree_though_now_moved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            first = keel_dashboard.read_state(project)
            second = keel_dashboard.read_state(project)
        self.assertEqual(first["content_digest"], second["content_digest"])
        self.assertGreaterEqual(second["now"], first["now"])

    def test_now_alone_can_never_change_the_digest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), []))
        moved = {**state, "now": state["now"] + 3600}
        self.assertEqual(keel_dashboard.content_digest(moved), state["content_digest"])

    def test_a_new_audit_line_changes_the_digest(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "activity", "session": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), lines)
            before = keel_dashboard.read_state(project)
            with open(
                project / ".keel" / "audit" / "keel-audit.jsonl",
                "a",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                handle.write(
                    json.dumps(
                        {"v": 1, "ts": "2026-08-01T10:00:01Z", "event": "gate_block",
                         "session": "s1", "gate": "plan"}
                    )
                    + "\n"
                )
            after = keel_dashboard.read_state(project)
        self.assertNotEqual(before["content_digest"], after["content_digest"])

    def test_the_page_gates_its_redraw_on_that_digest(self) -> None:
        """SUBSTRING, deliberately and unavoidably: the poll loop and the
        redraw it guards run in a browser, not here. What the gate MEANS -
        that the wall clock alone never counts as a change - is asserted by
        value above; this only pins that the page compares the server's
        fingerprint rather than re-deciding the question itself.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("a.content_digest === b.content_digest", text)
        self.assertIn("if (changed) renderAll(lastState)", text)

    def test_the_page_polls_faster_and_ticks_every_second(self) -> None:
        """SUBSTRING, deliberately: two timer intervals that only exist in a
        browser. The figures are the acceptance criteria's own (a ~1.5s poll
        and a 1s ticker); nothing about them is computable here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("POLL_MS = 1500", text)
        self.assertIn("TICK_MS = 1000", text)
        self.assertIn("setInterval(tick, POLL_MS)", text)
        self.assertIn("setInterval(ticker, TICK_MS)", text)


# ------------------------------------------------------- T3 the tick, in place


def _script(text: str) -> str:
    """The page's script with its full-line ``//`` comments removed.

    Everything below that reads the page's source reads THIS. A comment that
    mentions a function is not a call to it and a comment that mentions a
    guard is not a guard, so the prose is stripped before any structure is
    read off it. If an inline (end-of-line) comment ever appears the strip
    would be incomplete, and this refuses rather than quietly measuring the
    wrong thing.
    """
    start = text.index("<script>") + len("<script>")
    body = text[start : text.index("</script>", start)]
    code = "\n".join(ln for ln in body.splitlines() if not ln.strip().startswith("//"))
    assert "//" not in code, "an inline comment would defeat this stripping"
    return code


_FUNCTION = re.compile(r"^(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.M)


def _functions(script: str) -> dict[str, str]:
    """Every ``function NAME(...){...}`` in the page's script, by name.

    Bodies are found by BALANCING braces, not by a non-greedy match, so a
    function with nested blocks comes back whole instead of truncated at its
    first inner ``}`` - the earlier helper here could only read functions
    with no nested braces at all, which quietly limited what could be
    asserted. The closing brace of a top-level function is at column zero in
    this page; checking that is how this knows the balance found the real
    end rather than running off into a string literal.
    """
    out: dict[str, str] = {}
    for match in _FUNCTION.finditer(script):
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
        assert depth == 0, f"unbalanced braces reading {match.group(1)!r}"
        assert script[i - 1] == "\n", f"{match.group(1)!r} did not end at column zero"
        out[match.group(1)] = script[open_at + 1 : i]
    return out


def _block_after(script: str, marker: str) -> str:
    """The brace-balanced block that opens after ``marker`` - used for the
    parts of the page that are not named functions (an event handler, a
    ``catch``), so they can be read as precisely as a function body is.
    """
    start = script.index(marker)
    open_at = script.index("{", start)
    depth, i = 0, open_at
    while i < len(script):
        if script[i] == "{":
            depth += 1
        elif script[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    assert depth == 0, f"unbalanced braces reading the block after {marker!r}"
    return script[open_at + 1 : i]


def _calls(body: str, names: set[str]) -> set[str]:
    """Which of ``names`` this body calls, by ``name(`` with a word boundary
    - so ``tick`` is not read out of ``tickOpenRows(`` and ``feed`` is not
    read out of ``$("feed")``.
    """
    return {n for n in names if re.search(r"\b" + re.escape(n) + r"\s*\(", body)}


def _reachable(functions: dict[str, str], start: str) -> set[str]:
    """Every function reachable from ``start`` through calls, transitively -
    the whole of what running ``start`` can touch, rather than only what its
    own body names directly.
    """
    seen: set[str] = set()
    todo = [start]
    while todo:
        name = todo.pop()
        for called in _calls(functions[name], set(functions)):
            if called not in seen:
                seen.add(called)
                todo.append(called)
    return seen


def _sole_function_containing(functions: dict[str, str], needle: str) -> str:
    """The ONE function whose body contains ``needle``, asserting there is
    exactly one. Every role below is found this way - by the thing the code
    does (writes this node, assigns this markup, reads the clock) rather
    than by the name it happens to carry - so renaming a function cannot
    make any of these checks pass by accident.
    """
    named = [n for n, body in functions.items() if needle in body]
    assert len(named) == 1, f"expected exactly one function containing {needle!r}, got {named}"
    return named[0]


def _timer_target(script: str, interval: str) -> str:
    """The function a ``setInterval(..., <interval>)`` actually drives."""
    match = re.search(
        r"setInterval\(\s*([A-Za-z_$][\w$]*)\s*,\s*" + re.escape(interval) + r"\s*\)", script
    )
    assert match, f"no setInterval on {interval}"
    return match.group(1)


FRESHNESS_NODE = '$("freshness")'
PANE_MARKUP = '$("feed").innerHTML'
DISCONNECT_SENTENCE = "viewer disconnected — the server was stopped"

#: Everything the page must still carry, whatever it looks like (T4, restated
#: and extended by T6). The owner has now twice said that a rebuild may not
#: cost the page anything it already showed, so the list lives in ONE place
#: and both the canvas suite and the T6 layout suite read it: the project
#: path, the arming and read-only badges, the header figures, the roster, the
#: ledger's selector and progress, the feed with its filter chips, the open
#: rows' pane, the losses line, the canvas and its note, and all three
#: sentences in the footer. A marker removed from here is a pane removed from
#: the page, and that is exactly the regression this is written to catch.
PRESERVED_MARKERS: tuple[str, ...] = (
    'id="project"', 'id="arming"', 'read-only · no write route', 'id="stats"',
    'id="roster"', 'id="plansel"', 'id="progress"', 'id="ledger"',
    'id="filters"', 'id="feed"', 'id="lost"', 'id="freshness"',
    'id="canvas"', 'id="graphnote"',
    ".keel/audit/keel-audit.jsonl + .keel/plans/ · nothing is written",
    "quiet-time is INFERRED from gaps in the log, never measured",
)

#: The five figures the header carries (four from T27b/T31 plus T4's own
#: "working now"), as the page's own rows compute them.
HEADER_FIGURES: tuple[str, ...] = (
    '["events", c.events]', '["sessions", c.sessions]',
    '["hand-offs", c.handoff_start]',
    '["blocks", c.gate_block + c.stop_block]',
    '["working now", c.working]',
)


def _style(text: str) -> str:
    """The page's one inline style block."""
    return text[text.index("<style>") : text.index("</style>")]


def _decl(style: str, selector: str) -> str:
    """The declarations of ONE css rule, found by its selector.

    Used instead of quoting a whole rule back at the page, so a declaration
    added or reordered inside a rule this suite has an opinion about does not
    fail a test that was never about ordering.
    """
    opened = style.index(selector + "{") + len(selector) + 1
    return style[opened : style.index("}", opened)]


class TestTickInPlaceAndTheDisconnectNotice(unittest.TestCase):
    """T3 (carried from the prior ledger's T33): the one-second tick updates
    elapsed, quiet-time and freshness text IN PLACE and never assigns the
    feed pane's markup wholesale, so a delegation opened by a click stays
    open and scroll position survives; and once a poll's own fetch fails,
    the disconnect notice stands until a fetch actually succeeds again - not
    only against the next tick, but against EVERY route that could put an
    age on screen, including a filter chip's re-render and any caller
    written after this class was.

    There is no JavaScript engine in this suite (see the module docstring's
    "Values, not substrings"), so none of this can be run here. What these
    tests do instead of quoting the page's source back at it is read its
    STRUCTURE: which function writes a given node, which functions can reach
    it, and where the guard sits relative to the write. Each role is
    discovered by what the code does - the function that writes the
    freshness node, the function the one-second timer drives, the function
    that assigns the pane's markup - and never by name, so renaming any of
    them changes nothing here while reintroducing the defect fails these
    tests. Where a plain substring is still the only honest option the
    docstring says so, following this suite's convention.

    The behaviour itself - that an expanded group truly stays open across
    real ticks, and that a stopped server truly leaves the notice standing
    while every filter chip is clicked - is reported to the orchestrator
    from a hand-driven browser run rather than claimed here.
    """

    def _page_parts(self) -> tuple[str, dict[str, str]]:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        script = _script(text)
        return script, _functions(script)

    def _flag(self, script: str, functions: dict[str, str]) -> str:
        """The name of the lost-contact flag, read off the failure path that
        SETS it rather than assumed - the poll's ``catch`` assigns exactly
        one identifier ``true``, and that identifier is the flag.
        """
        poll = _timer_target(script, "POLL_MS")
        catch = _block_after(functions[poll], "catch")
        match = re.search(r"\b([A-Za-z_$][\w$]*)\s*=\s*true\s*;", catch)
        self.assertIsNotNone(match, catch)
        assert match
        return match.group(1)

    def test_the_brace_scanner_reads_whole_functions_not_fragments(self) -> None:
        """Guards the METHOD every test below depends on: a helper that
        stopped at a function's first inner ``}`` would return a fragment,
        and assertions about what is absent from a fragment prove nothing.
        The function that assigns the pane's markup has a loop and a
        conditional of its own, so its body is only whole if the balance
        worked - checked here by its opening and its closing statement both
        being present in the one extracted body.
        """
        script, functions = self._page_parts()
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        body = functions[renderer]
        self.assertIn("for (", body)
        self.assertIn(PANE_MARKUP, body.split("for (")[-1])
        self.assertEqual(body.count("{"), body.count("}"), body)
        # And the scan found every function the page declares, not a prefix.
        self.assertEqual(len(functions), len(_FUNCTION.findall(script)))

    def test_the_freshness_line_has_exactly_one_writer_in_the_whole_page(self) -> None:
        """The structural half of the fix. The footer node that carries the
        age is touched from ONE function - not from the poll's failure path,
        not from a handler, not from top-level code - so a guard placed in
        that function is a guard on every route there is, present and
        future. Keyed on the node itself (the ``freshness`` id the footer
        declares), which is what a reader actually sees, rather than on any
        function's name.
        """
        script, functions = self._page_parts()
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        inside = functions[writer].count(FRESHNESS_NODE)
        self.assertEqual(
            script.count(FRESHNESS_NODE),
            inside,
            "every reference to the freshness node must live in its one writer",
        )
        self.assertEqual(inside, 1, "and that writer must write it exactly once")

    def test_that_one_writer_refuses_to_compose_an_age_while_disconnected(self) -> None:
        """THE property, pinned where it cannot be bypassed: the writer's
        single assignment is itself conditional on the lost-contact flag,
        and the flag is consulted BEFORE any field of the state it was
        handed is read. Because the guard is part of the same expression as
        the write - not an early return with room above it - no later edit
        can put an unguarded assignment ahead of it without deleting this
        one. The flag's own name is discovered from the failure path that
        sets it, so renaming it changes nothing here.
        """
        script, functions = self._page_parts()
        flag = self._flag(script, functions)
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        body = functions[writer]
        self.assertEqual(body.count("textContent"), 1, body)
        start = body.index("textContent")
        statement = body[start : body.index(";", start)]
        self.assertIn(flag, statement)
        self.assertLess(
            statement.index(flag),
            statement.index("audit_mtime"),
            "the flag must be consulted before the stale state is read",
        )

    def test_the_notice_is_one_constant_only_the_guarded_writer_puts_on_screen(self) -> None:
        """SUBSTRING for the sentence itself, unavoidably - the exact words
        a reader sees are text and nothing else can stand in for them. What
        is structural here is where they live: one constant, referenced from
        the guarded branch of the one writer, so no other path holds a copy
        of the sentence and no path can show it without going through the
        guard that decides it is true.
        """
        script, functions = self._page_parts()
        self.assertEqual(script.count(DISCONNECT_SENTENCE), 1, "one wording, one place")
        match = re.search(
            r"const\s+([A-Za-z_$][\w$]*)\s*=\s*\"" + re.escape(DISCONNECT_SENTENCE) + r"\"", script
        )
        self.assertIsNotNone(match, "the sentence must be a named constant")
        assert match
        note = match.group(1)
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        users = [n for n, body in functions.items() if re.search(r"\b" + note + r"\b", body)]
        self.assertEqual(users, [writer], "only the guarded writer may show the notice")
        flag = self._flag(script, functions)
        statement = functions[writer]
        self.assertLess(statement.index(flag), statement.index(note))

    def test_losing_contact_sets_the_flag_and_writes_no_node_of_its_own(self) -> None:
        """The failure path keeps no private route to the footer: it sets
        the flag, calls the one writer, and returns. It does not name the
        node, does not carry the sentence, and does not touch ``textContent``
        - so the notice a reader sees while the server is down is produced
        by exactly the same guarded code as every other state of that line.
        """
        script, functions = self._page_parts()
        poll = _timer_target(script, "POLL_MS")
        catch = _block_after(functions[poll], "catch")
        flag = self._flag(script, functions)
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        self.assertIn(flag + " = true;", catch)
        self.assertNotIn("textContent", catch)
        self.assertNotIn(FRESHNESS_NODE, catch)
        self.assertNotIn(DISCONNECT_SENTENCE, catch)
        self.assertIn(writer, _calls(catch, set(functions)))
        self.assertIn("return;", catch)

    def test_a_successful_poll_clears_the_flag_and_always_refreshes_the_figure(self) -> None:
        """Both halves of "sticky until contact returns": the flag is
        cleared on the success path BEFORE anything renders, and the writer
        is called from that path as a bare statement - not inside the
        ``changed`` branch - because ``now`` is deliberately outside the
        redraw digest (T30) and an unchanged poll must still retire the
        notice and show a live age. Read against the SUCCESS PATH alone -
        everything after the failure block ends - so the failure path's own
        call cannot stand in for the one being asserted here.
        """
        script, functions = self._page_parts()
        poll = _timer_target(script, "POLL_MS")
        body = functions[poll]
        success = body.split(_block_after(body, "catch"), 1)[1]
        flag = self._flag(script, functions)
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        full = _sole_function_containing(functions, renderer + "(")
        self.assertEqual(body.count(flag + " = false;"), 1, body)
        cleared = success.index(flag + " = false;")
        first_render = min(
            i for i in (success.find(writer + "("), success.find(full + "(")) if i != -1
        )
        self.assertLess(cleared, first_render, "contact is restored before anything is drawn")
        bare = [ln.strip() for ln in success.splitlines() if ln.strip().startswith(writer + "(")]
        self.assertEqual(len(bare), 1, "exactly one unconditional refresh on the success path")

    def test_the_filter_chips_re_render_with_no_route_of_their_own_to_the_age(self) -> None:
        """The defect this task was escalated over: clicking a chip while
        disconnected re-rendered from the state held before the outage and
        overwrote the notice with a stale-but-plausible age. The handler is
        unchanged in shape - it still re-renders from held state, which is
        right for a presentation-only toggle - and what makes it safe is
        structural rather than local: it has no route to the footer node
        except the one writer, which refuses while the flag stands. A guard
        in this handler would cover this handler alone, which is exactly the
        fix this test is written to make unnecessary.
        """
        script, functions = self._page_parts()
        handler = _block_after(script, '$("filters").addEventListener')
        self.assertNotIn("textContent", handler)
        self.assertNotIn(FRESHNESS_NODE, handler)
        self.assertNotIn("audit_mtime", handler)
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        full = _sole_function_containing(functions, renderer + "(")
        self.assertIn(full, _calls(handler, set(functions)))
        writer = _sole_function_containing(functions, FRESHNESS_NODE)
        self.assertIn(
            writer, _reachable(functions, full), "its only age route is the guarded writer"
        )

    def test_only_one_place_in_the_page_reads_the_readers_own_clock(self) -> None:
        """Why no elapsed or quiet-time figure can advance during an outage,
        stated once rather than per caller: every other figure is computed
        against a ``now`` the SERVER sent, which cannot move while the server
        is not answering. The single live-clock read sits in the function the
        one-second timer drives, after that function's own guard.
        """
        script, functions = self._page_parts()
        self.assertEqual(script.count("Date.now()"), 1, "one live clock read in the whole page")
        ticker = _timer_target(script, "TICK_MS")
        body = functions[ticker]
        self.assertIn("Date.now()", body)
        flag = self._flag(script, functions)
        self.assertLess(body.index(flag), body.index("Date.now()"))
        self.assertIn("return;", body[: body.index("Date.now()")])

    def test_the_in_place_elapsed_writer_is_reached_only_through_a_guarded_caller(self) -> None:
        """The elapsed and quiet-time half of the same property. The one
        function that rewrites those two nodes in place is called from one
        place, and that caller refuses on the flag in its FIRST statement -
        so the guard is in the walker every caller must go through, not only
        in the timer that happens to drive it today.
        """
        script, functions = self._page_parts()
        live = _sole_function_containing(functions, '[data-role="elapsed"]')
        callers = [n for n, body in functions.items() if live + "(" in body]
        self.assertTrue(callers, "the in-place writer must be called from somewhere")
        flag = self._flag(script, functions)
        for caller in callers:
            first = functions[caller].strip().splitlines()[0].strip()
            self.assertIn(flag, first, f"{caller} must refuse while disconnected")
            self.assertIn("return;", first)

    def test_the_one_second_timer_cannot_reach_the_panes_markup_renderer(self) -> None:
        """The scroll-and-expansion half of the task, as reachability rather
        than as the absence of one call at one site: nothing the timer can
        reach, transitively, assigns markup at all. A rename cannot pass
        this and neither can moving the rebuild one call deeper.
        """
        script, functions = self._page_parts()
        ticker = _timer_target(script, "TICK_MS")
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        reach = _reachable(functions, ticker)
        self.assertNotIn(renderer, reach)
        for name in reach | {ticker}:
            self.assertNotIn("innerHTML", functions[name], name)
            self.assertNotIn("outerHTML", functions[name], name)

    def test_the_panes_markup_is_assigned_in_exactly_one_place(self) -> None:
        """One assignment of the pane's markup in the whole page, made from
        one call site, inside the full render a changed poll gates. Before
        this task there were two - the second ran every second regardless of
        what the redraw gate decided, which is what made the gate pointless
        and threw away the reader's expanded rows.
        """
        script, functions = self._page_parts()
        self.assertEqual(script.count(PANE_MARKUP), 1, script.count(PANE_MARKUP))
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        call_sites = re.findall(r"(?<!function )\b" + renderer + r"\s*\(", script)
        self.assertEqual(len(call_sites), 1, call_sites)
        full = _sole_function_containing(functions, renderer + "(")
        self.assertIn(renderer, _calls(functions[full], set(functions)))

    def test_open_rows_carry_the_key_and_role_markers_the_ticker_reads_back(self) -> None:
        """SUBSTRING, and honestly so: these are the marker names written
        into markup on one side and read back off the DOM on the other, and
        a string is all either side is. What makes the pairing meaningful is
        that both sides are asserted together - the render's ``data-key`` and
        the walker's selector for it - so a change to one that forgot the
        other fails here rather than silently updating no rows at all.
        """
        script, functions = self._page_parts()
        self.assertIn('data-key="${esc(openRowKey(o))}"', script)
        self.assertIn('data-role="elapsed"', script)
        self.assertIn('data-role="quiet"', script)
        self.assertIn('document.querySelectorAll("#feed .ev.openrow[data-key]")', script)
        live = _sole_function_containing(functions, '[data-role="elapsed"]')
        self.assertIn('el.querySelector(\'[data-role="quiet"]\')', functions[live])

    def test_server_computed_open_item_fields_the_ticker_depends_on_are_real_values(
        self,
    ) -> None:
        """VALUE, not substring: ``openRowKey``'s three ingredients
        (``row_kind``, ``session``, ``ts``) and the quiet-time fields
        ``updateOpenRowLive`` re-reads (``last_seen_ts``, ``quiet_note``,
        ``quiet_threshold_seconds``) are exactly what ``read_state`` already
        computes server-side, UNCHANGED by this task - the ticker has
        genuine server-computed values to key on and format, never anything
        invented client-side. Two independent reads of the same log agree on
        the key material, which is the whole of how the ticker finds the
        right row again between polls.
        """
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "unfinished"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            first = keel_dashboard.read_state(_project(Path(tmp), lines))
            second = keel_dashboard.read_state(_project(Path(tmp) / "again", lines))
        for state in (first, second):
            item = state["open"][0]
            for field in (
                "row_kind", "session", "ts", "last_seen_ts",
                "quiet_note", "quiet_threshold_seconds", "agent_type",
            ):
                self.assertIn(field, item)
        self.assertEqual(
            (first["open"][0]["row_kind"], first["open"][0]["session"], first["open"][0]["ts"]),
            (second["open"][0]["row_kind"], second["open"][0]["session"], second["open"][0]["ts"]),
        )

    def test_the_roster_ticker_rewrites_only_the_elapsed_figure_in_place(self) -> None:
        """T118: a resting chip's last-seen figure must tick the same way an
        open row's elapsed figure already does - by ``textContent`` on the
        ONE span marked for it, never by touching the chip's own markup. The
        walker is found by the thing it does (queries
        ``[data-role="last-seen"]``, the marker `roster` wrote) rather than
        by name, so a rename cannot make this pass by accident. What it
        rewrites must be readable as an elapsed figure alone - the verb
        (``last_seen_kind``), the run count and the working/resting state
        word must never appear in what this function assigns, because a
        write scoped to the marked span structurally cannot reach them.
        """
        script, functions = self._page_parts()
        live = _sole_function_containing(functions, '[data-role="last-seen"]')
        body = functions[live]
        # refuses on the same flag every other live-clock writer refuses on
        flag = self._flag(script, functions)
        first = body.strip().splitlines()[0].strip()
        self.assertIn(flag, first)
        self.assertIn("return;", first)
        # rewrites by textContent alone, never innerHTML/outerHTML, and
        # never assigns the pane's own markup
        self.assertIn("textContent", body)
        self.assertNotIn("innerHTML", body)
        self.assertNotIn("outerHTML", body)
        renderer = _sole_function_containing(functions, PANE_MARKUP)
        self.assertNotEqual(live, renderer)
        # the ticker actually reaches this writer
        ticker = _timer_target(script, "TICK_MS")
        self.assertIn(live, _reachable(functions, ticker))
        # what it assigns is composed from `fmtDur`/`elapsedSince` alone -
        # never the verb, the run count or the state word a chip also shows
        assignment = body[body.index("textContent"):]
        for absent in ("last_seen_kind", "r.label", "working", "resting", "run(s)"):
            self.assertNotIn(absent, assignment)

# ---------------------------------------------------------------- T31 rename


class TestOneNameEachRowKind(unittest.TestCase):
    def test_open_and_group_and_event_rows_all_use_row_kind_and_agent_type(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "closed"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
            {"v": 1, "ts": "2026-08-01T10:00:04Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "closed"},
            {"v": 1, "ts": "2026-08-01T11:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t2", "subagent_type": "researcher", "description": "open"},
            {"v": 1, "ts": "2026-08-01T11:00:01Z", "event": "gate_block", "session": "s1",
             "gate": "plan"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        self.assertNotIn("open_of", json.dumps(state))
        for row in state["feed"]:
            self.assertIn("row_kind", row)
            if row["row_kind"] == "group":
                self.assertIn("agent_type", row)
                self.assertNotIn("subagent_type", row)
        for item in state["open"]:
            self.assertEqual(item["row_kind"], "open_handoff")
            self.assertIn("agent_type", item)
            self.assertNotIn("subagent_type", item)
            self.assertNotIn("open_of", item)


class TestPromptHeadAndDetail(unittest.TestCase):
    def test_prompt_head_reaches_a_closed_groups_own_row(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d",
             "prompt_head": "do the thing"},
            {"v": 1, "ts": "2026-08-01T10:00:04Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d",
             "prompt_head": "do the thing"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        groups = [r for r in state["feed"] if r["row_kind"] == "group"]
        self.assertEqual(groups[0]["prompt_head"], "do the thing")

    def test_prompt_head_reaches_an_open_handoffs_own_row(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d",
             "prompt_head": "do the other thing"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        self.assertEqual(state["open"][0]["prompt_head"], "do the other thing")

    def test_detail_text_names_every_field_the_row_carries_in_order(self) -> None:
        row = {
            "event": "activity",
            "tool": "Edit",
            "path": "scripts/keel_dashboard.py",
            "detail": "one line",
            "prompt_head": "do the thing",
            "ignored_field": "not shown",
        }
        self.assertEqual(
            keel_dashboard.detail_text(row),
            "tool=Edit  path=scripts/keel_dashboard.py  detail=one line  "
            "prompt_head=do the thing",
        )

    def test_detail_text_of_a_row_with_nothing_to_say_is_empty(self) -> None:
        self.assertEqual(keel_dashboard.detail_text({"event": "session_end", "tool": ""}), "")

    def test_the_detail_line_reaches_a_flat_row_and_a_grouped_member(self) -> None:
        """``detail`` and ``prompt_head`` are fields the log carries and the
        page used to drop on the floor - now built into the row itself, so
        what a reader would see is a value rather than page source."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d"},
            {"v": 1, "ts": "2026-08-01T10:00:02Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit", "detail": "shared.py"},
            {"v": 1, "ts": "2026-08-01T10:00:04Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "t1", "subagent_type": "executor", "description": "d"},
            {"v": 1, "ts": "2026-08-01T11:00:00Z", "event": "gate_block", "session": "s1",
             "gate": "plan", "reason": "no ledger"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        flat = [r for r in state["feed"] if r["row_kind"] == "event"]
        self.assertEqual(flat[0]["detail_text"], "gate=plan  reason=no ledger")
        group = [r for r in state["feed"] if r["row_kind"] == "group"][0]
        self.assertEqual(
            group["events"][0]["detail_text"], "tool=Edit  agent_type=executor  detail=shared.py"
        )


# ------------------------------------------------------------ T31 tasks/roster


class TestParseLedgerTasks(unittest.TestCase):
    def test_a_multiline_accept_clause_is_captured_in_full(self) -> None:
        text = (
            "# ledger\n\n"
            "- [x] T27 The attention pass — four changes.\n"
            "  Route: executor.\n"
            "  Accept: all four clauses below hold.\n"
            "  (a) first clause.\n"
            "  (b) second clause.\n\n"
            "- [ ] T28 Next task.\n"
            "  Route: executor.\n"
            "  Accept: a short one.\n"
        )
        tasks = keel_dashboard.parse_ledger_tasks(text)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(tasks[0]["mark"], "x")
        self.assertIn("T27 The attention pass", tasks[0]["title"])
        self.assertEqual(
            tasks[0]["accept"], "all four clauses below hold. (a) first clause. (b) second clause."
        )
        self.assertEqual(tasks[1]["accept"], "a short one.")

    def test_result_and_route_lines_are_not_mistaken_for_accept_text(self) -> None:
        text = (
            "- [x] T2 Verify something.\n"
            "  Result: records clean.\n"
            "  Route: orchestrator.\n"
            "  Accept: the thing is verified.\n"
        )
        tasks = keel_dashboard.parse_ledger_tasks(text)
        self.assertEqual(tasks[0]["accept"], "the thing is verified.")
        self.assertNotIn("Result", tasks[0]["accept"])
        self.assertNotIn("Route", tasks[0]["accept"])

    def test_a_task_with_no_accept_marker_yields_an_empty_string_not_a_crash(self) -> None:
        text = "- [ ] T9 Nothing to see here.\n  just a continuation line.\n"
        tasks = keel_dashboard.parse_ledger_tasks(text)
        self.assertEqual(tasks[0]["accept"], "")

    def test_every_terminal_mark_is_recognised_and_others_are_not(self) -> None:
        text = (
            "- [x] Ta done\n  Accept: a\n\n"
            "- [!] Tb blocked\n  Accept: b\n\n"
            "- [?] Tc decision\n  Accept: c\n\n"
            "- [ ] Td open\n  Accept: d\n\n"
            "- [~] Te inflight\n  Accept: e\n"
        )
        tasks = keel_dashboard.parse_ledger_tasks(text)
        progress = keel_dashboard.ledger_progress(tasks)
        self.assertEqual(progress, {"terminal": 3, "total": 5})
        self.assertEqual(keel_dashboard.progress_label(progress), "(3/5 terminal)")

    def test_an_empty_ledger_reports_zero_over_zero_and_says_nothing(self) -> None:
        self.assertEqual(keel_dashboard.ledger_progress([]), {"terminal": 0, "total": 0})
        self.assertEqual(keel_dashboard.progress_label({"terminal": 0, "total": 0}), "")


class TestUnreadableLedgerIsNotAnEmptyOne(unittest.TestCase):
    """A ledger listed and then unreadable is a LOSS, and the page may not
    show a loss with the words it shows an empty project (see the module's
    "Failure policy"). Counted like a corrupt audit line, and named."""

    def test_a_listed_ledger_that_cannot_be_read_is_reported_as_unreadable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            plan = keel_dashboard.read_ledger(project, "keel-plan-deadbeef.md")
        self.assertEqual(plan["state"], "unreadable")
        self.assertEqual(plan["tasks"], [])
        self.assertIn("could not be read", plan["note"])
        self.assertIn("NOT an empty ledger", plan["note"])

    def test_a_ledger_with_no_tasks_is_reported_as_empty_and_reads_differently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [], "# ledger\n\nprose, no checkboxes.\n")
            plan = keel_dashboard.read_ledger(project, "keel-plan-abcdef12.md")
        self.assertEqual(plan["state"], "empty")
        self.assertEqual(plan["tasks"], [])
        self.assertNotEqual(plan["note"], keel_dashboard.PLAN_NOTES["unreadable"])
        self.assertNotEqual(plan["note"], keel_dashboard.PLAN_NOTES["none"])

    def test_a_project_with_no_ledger_at_all_is_reported_as_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            (project / ".keel" / "plans" / "keel-plan-abcdef12.md").unlink()
            state = keel_dashboard.read_state(project)
        self.assertEqual(state["plan"]["state"], "none")
        self.assertEqual(state["counts"]["unreadable_plans"], 0)
        self.assertIn("No ledger", state["plan"]["note"])

    def test_the_race_between_listing_and_reading_is_counted_not_swallowed(self) -> None:
        """``list_plans`` said the ledger was there; ``read_plan`` could not
        open it a moment later - deleted, locked, replaced. That is the exact
        input the finding named, and it may not render as "no ledger yet"."""
        phantom = [{"name": "keel-plan-deadbeef.md", "session": "deadbeef", "mtime": 1.0}]
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with unittest.mock.patch.object(
                keel_dashboard, "list_plans", return_value=(phantom, False)
            ):
                lost = keel_dashboard.read_state(project)
            intact = keel_dashboard.read_state(project)

        self.assertEqual(lost["plan"]["state"], "unreadable")
        self.assertEqual(lost["counts"]["unreadable_plans"], 1)
        self.assertEqual(lost["plan"]["progress"], {"terminal": 0, "total": 0})
        self.assertEqual(lost["plan"]["progress_label"], "", "0/0 is not a reading of a ledger")
        # ...and it is DISTINGUISHABLE from a project whose ledger is fine.
        self.assertEqual(intact["counts"]["unreadable_plans"], 0)
        self.assertNotEqual(intact["plan"]["state"], lost["plan"]["state"])
        self.assertNotEqual(intact["plan"]["note"], lost["plan"]["note"])

    def test_a_query_naming_a_ledger_this_project_never_had_is_not_a_loss(self) -> None:
        """The counter means "a ledger this project LISTS could not be read".
        A request naming something that never existed is a bad request, not a
        hole in the record, and must not inflate the loss."""
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), []), "keel-plan-99999999.md")
        self.assertEqual(state["counts"]["unreadable_plans"], 0)
        self.assertEqual(state["plan"]["name"], "keel-plan-abcdef12.md")
        self.assertEqual(state["plan"]["state"], "tasks")

    def test_both_losses_are_worded_together_and_neither_is_worded_when_absent(self) -> None:
        self.assertEqual(keel_dashboard.loss_note({}), "")
        self.assertEqual(
            keel_dashboard.loss_note({"unreadable_lines": 0, "unreadable_plans": 0}), ""
        )
        self.assertEqual(
            keel_dashboard.loss_note({"unreadable_lines": 2, "unreadable_plans": 0}),
            "2 unreadable line(s)",
        )
        self.assertEqual(
            keel_dashboard.loss_note({"unreadable_lines": 0, "unreadable_plans": 1}),
            "1 unreadable ledger(s)",
        )
        self.assertEqual(
            keel_dashboard.loss_note({"unreadable_lines": 2, "unreadable_plans": 1}),
            "2 unreadable line(s) · 1 unreadable ledger(s)",
        )

    def test_an_unreadable_ledger_reaches_the_payloads_own_loss_note(self) -> None:
        phantom = [{"name": "keel-plan-deadbeef.md", "session": "deadbeef", "mtime": 1.0}]
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with unittest.mock.patch.object(
                keel_dashboard, "list_plans", return_value=(phantom, False)
            ):
                lost = keel_dashboard.read_state(project)
            intact = keel_dashboard.read_state(project)
        self.assertEqual(lost["loss_note"], "1 unreadable ledger(s)")
        self.assertEqual(intact["loss_note"], "")

    def test_the_page_shows_the_servers_sentence_rather_than_one_of_its_own(self) -> None:
        """SUBSTRING, deliberately: which sentence is shown is a value
        (asserted above); that the page renders the server's sentence at all,
        instead of hard-coding "No ledger for this session yet", can only be
        read off the page's source here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("esc(plan.note)", text)
        self.assertNotIn("No ledger for this session yet", text)


class TestListingFailureIsALoss(unittest.TestCase):
    """T36: an absent plans directory is the ordinary "none" - no loss - a
    project this project's own law never made exist. Any OTHER failure
    listing that directory is a LOSS with its own state, its own sentence,
    and a counted, non-empty loss note - never the "no ledger yet" wording
    an absent directory gets."""

    def test_an_absent_plans_directory_is_reported_with_no_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            found, listing_failed = keel_dashboard.list_plans(Path(tmp) / "never-planned-in")
        self.assertEqual(found, [])
        self.assertFalse(listing_failed)

    def test_a_plans_path_that_is_a_file_not_a_directory_is_reported_as_a_loss(self) -> None:
        """Reachable on every platform: a plans path that exists as a FILE
        raises an ``OSError`` subclass (``NotADirectoryError``) when listed,
        and that is a genuine anomaly, not the ordinary "never planned in".
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            plans_path = project / ".keel" / "plans"
            (plans_path / "keel-plan-abcdef12.md").unlink()
            plans_path.rmdir()
            plans_path.write_text("not a directory", encoding="utf-8")
            found, listing_failed = keel_dashboard.list_plans(project)
        self.assertEqual(found, [])
        self.assertTrue(listing_failed)

    def test_a_per_entry_stat_failure_degrades_that_entry_without_dropping_its_name(
        self,
    ) -> None:
        """A smaller loss than the whole directory failing to list: the
        entry stays in ``found``, named, just without an ``mtime``."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            with unittest.mock.patch.object(Path, "is_file", return_value=True):
                with unittest.mock.patch.object(
                    Path, "stat", side_effect=OSError("simulated per-entry stat failure")
                ):
                    found, listing_failed = keel_dashboard.list_plans(project)
        self.assertFalse(listing_failed)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["name"], "keel-plan-abcdef12.md")
        self.assertIsNone(found[0]["mtime"])

    def test_a_real_listing_failure_reaches_read_state_as_a_distinct_loss(self) -> None:
        """End to end, against the real filesystem rather than a mock: the
        payload names a state and a sentence neither "none" nor
        "unreadable" carry, counts the loss, and never says "no ledger
        yet" over it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = _project(Path(tmp), [])
            plans_path = project / ".keel" / "plans"
            (plans_path / "keel-plan-abcdef12.md").unlink()
            plans_path.rmdir()
            plans_path.write_text("not a directory", encoding="utf-8")
            state = keel_dashboard.read_state(project)

        self.assertEqual(state["plan"]["state"], "listing_failed")
        self.assertNotEqual(state["plan"]["state"], "none")
        self.assertNotEqual(state["plan"]["state"], "unreadable")
        self.assertEqual(state["plan"]["note"], keel_dashboard.PLAN_NOTES["listing_failed"])
        self.assertNotEqual(state["plan"]["note"], keel_dashboard.PLAN_NOTES["none"])
        self.assertNotIn("No ledger", state["plan"]["note"])
        self.assertEqual(state["counts"]["unreadable_plans"], 1)
        self.assertNotEqual(state["loss_note"], "")
        self.assertEqual(state["plans"], [])


class TestComputeRoster(unittest.TestCase):
    def test_closed_and_open_runs_of_the_same_type_are_counted_together(self) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T09:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "two"},
            {"v": 1, "ts": "2026-08-01T10:00:30Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        roster = {r["agent_type"]: r for r in state["roster"]}
        self.assertEqual(roster["executor"]["runs"], 2)
        self.assertTrue(roster["executor"]["working"])
        self.assertEqual(roster["researcher"]["runs"], 1)
        self.assertFalse(roster["researcher"]["working"])

    def test_the_roster_says_working_or_resting_in_its_own_words(self) -> None:
        """The working/resting reading is the whole point of the roster, so
        it is settled server-side and asserted as the string a reader sees
        (T104: "idle" renamed to the reference's "resting")."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T09:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "two"},
            {"v": 1, "ts": "2026-08-01T10:00:30Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        labels = {r["agent_type"]: r["label"] for r in state["roster"]}
        states = {r["agent_type"]: r["state"] for r in state["roster"]}
        self.assertEqual(labels["executor"], "working · 2 run(s)")
        self.assertEqual(labels["researcher"], "resting · 1 run(s)")
        self.assertEqual(states["executor"], "working")
        self.assertEqual(states["researcher"], "resting")

    def test_a_resting_entrys_last_seen_names_its_own_source_truthfully(self) -> None:
        """T104's wording trap: a RESTING chip's last-seen figure must name
        what it actually measures. ``researcher`` here is closed only by a
        ``handoff_end`` - the LAUNCHING TOOL's own return, never the work's
        (see the module's [[a-recorded-end-is-not-a-finish]] discussion) - so
        it must read "launched", never "finished". ``executor`` is ALSO
        matched by a real ``subagent_stop`` (T101), a genuine end, so it must
        read "finished" and its last-seen timestamp must be the stop's own
        ``ts``, not the handoff_end's."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "agent_id": None, "subagent_type": "executor",
             "description": "one"},
            {"v": 1, "ts": "2026-08-01T09:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "A", "agent_id": "a1111111111111111",
             "subagent_type": "executor", "description": "one"},
            # T102: the stop NAMES the agent its launch's own return recorded.
            {"v": 1, "ts": "2026-08-01T09:05:00Z", "event": "subagent_stop", "session": "s1",
             "agent_id": "a1111111111111111", "agent_type": "executor"},
            {"v": 1, "ts": "2026-08-01T10:00:30Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
            {"v": 1, "ts": "2026-08-01T10:01:00Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "C", "subagent_type": "researcher", "description": "three"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        by_type = {r["agent_type"]: r for r in state["roster"]}

        researcher = by_type["researcher"]
        self.assertEqual(researcher["last_seen_kind"], "launched")
        self.assertEqual(researcher["last_seen_ts"], "2026-08-01T10:01:00Z")

        executor = by_type["executor"]
        self.assertEqual(executor["last_seen_kind"], "finished")
        self.assertEqual(executor["last_seen_ts"], "2026-08-01T09:05:00Z")

    def test_a_background_only_close_never_claims_finished(self) -> None:
        """A closed pair with NO matching ``subagent_stop`` at all must never
        be labelled "finished" - the acknowledgment ``handoff_end`` carries is
        the launching tool's return, not the work's own end."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
            {"v": 1, "ts": "2026-08-01T09:00:02Z", "event": "handoff_end", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "one"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        executor = {r["agent_type"]: r for r in state["roster"]}["executor"]
        self.assertEqual(executor["last_seen_kind"], "launched")
        self.assertNotEqual(executor["last_seen_kind"], "finished")

    def test_a_finished_open_handoff_reads_resting_not_working(self) -> None:
        """T109: a ``subagent_stop`` can match a hand-off before its own
        ``handoff_end`` ever lands - ``hooks/keel_stop.launch_agent_id``
        reads the launch's own ``agent_id`` FIRST, for a harness that names
        it at launch time - so the row stays ``open_handoff`` while already
        reading FINISHED (T103's own ``delegation_state``). That is a REAL
        end, not open work: a roster chip saying "working" while the canvas
        already draws that same delegation lingering as finished would be
        exactly the disagreement T109's acceptance forbids. Its run is still
        counted, and its own real finish is what ``last_seen`` names (T104) -
        never the near-instant ``launched`` a ``handoff_end`` alone would
        mean. A genuinely open hand-off of another type is unaffected and
        still reads working."""
        lines = [
            {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "agent_id": "a1111111111111111", "subagent_type": "executor",
             "description": "finished before its own return"},
            {"v": 1, "ts": "2026-08-01T09:05:00Z", "event": "subagent_stop", "session": "s1",
             "agent_id": "a1111111111111111", "agent_type": "executor"},
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "researcher", "description": "still going"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        by_type = {r["agent_type"]: r for r in state["roster"]}

        executor = by_type["executor"]
        self.assertEqual(executor["runs"], 1)
        self.assertFalse(executor["working"])
        self.assertEqual(executor["state"], "resting")
        self.assertEqual(executor["last_seen_kind"], "finished")
        self.assertEqual(executor["last_seen_ts"], "2026-08-01T09:05:00Z")

        researcher = by_type["researcher"]
        self.assertEqual(researcher["runs"], 1)
        self.assertTrue(researcher["working"])
        self.assertEqual(researcher["state"], "working")

    def test_an_open_session_is_not_a_run_of_anything(self) -> None:
        lines = [{"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s1"}]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        self.assertEqual(state["roster"], [])

    def test_the_page_renders_the_roster_the_server_computed(self) -> None:
        """SUBSTRING, deliberately: the strip is a DOM element and its
        contents are drawn in a browser. What each entry SAYS is asserted by
        value above; this pins only that the page shows the server's own
        label instead of composing a second one.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn('id="roster"', text)
        self.assertIn("esc(r.label)", text)
        self.assertNotIn('esc(r.runs)} run(s)', text)

    def test_the_page_renders_last_seen_from_the_servers_own_kind_field(self) -> None:
        """T104's wording trap, pinned at the render layer too: the page must
        read the VERB it prints beside a last-seen figure off the server's
        own ``r.last_seen_kind`` - never a hardcoded "finished" or "launched"
        the page invented itself, which could read true for one source and
        false for the other."""
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn("r.last_seen_kind", text)
        self.assertIn("r.last_seen_ts", text)
        self.assertNotIn('"last finished"', text)
        self.assertNotIn('"last launched"', text)

    def test_a_resting_chips_last_seen_figure_is_marked_for_the_ticker(self) -> None:
        """T118: a resting chip's elapsed figure must be a live node the
        one-second ticker can find and rewrite, not static text baked in at
        render - otherwise it only ever advances when a poll's content
        digest changes, which on a quiet project can be hours. The VERB
        (``last_seen_kind``) must sit OUTSIDE the marked span, as plain text,
        so the tick (pinned below) has no way to touch it and no way to
        drift from what T104 already fixed.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        self.assertIn('data-role="last-seen"', text)
        self.assertIn('data-ts="${esc(r.last_seen_ts)}"', text)
        span_open = text.index('<span data-role="last-seen"')
        span_close = text.index("</span>", span_open)
        before_span = text[: span_open]
        inside_span = text[span_open:span_close]
        # the verb is composed BEFORE the span opens, and never appears
        # inside it - the tick (pinned below) can only ever rewrite what is
        # between these two tags
        self.assertIn("last ${esc(r.last_seen_kind)}", before_span[-120:])
        self.assertNotIn("last_seen_kind", inside_span)


class TestStateIntegration(unittest.TestCase):
    def test_plan_carries_tasks_and_a_progress_figure(self) -> None:
        ledger_text = (
            "# ledger\n\n"
            "- [x] T1 done task.\n  Route: executor.\n  Accept: it works.\n\n"
            "- [ ] T2 open task.\n  Route: executor.\n  Accept: it will work.\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), [], ledger_text))
        self.assertEqual(len(state["plan"]["tasks"]), 2)
        self.assertEqual(state["plan"]["tasks"][0]["accept"], "it works.")
        self.assertEqual(state["plan"]["progress"], {"terminal": 1, "total": 2})
        self.assertEqual(state["plan"]["progress_label"], "(1/2 terminal)")
        self.assertEqual(state["plan"]["state"], "tasks")

    def test_every_security_header_still_applies_after_all_four_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = DashboardServer(_project(Path(tmp), []))
            try:
                for route in ("/", "/api/state", "/api/plan?name=keel-plan-abcdef12.md"):
                    status, _, headers = server.request("GET", route)
                    self.assertEqual(status, 200)
                    self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                    self.assertEqual(headers.get("X-Frame-Options"), "DENY")
                    self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
                    self.assertIn("default-src 'none'", headers.get("Content-Security-Policy", ""))
                status, body, headers = server.request("GET", "/no-such-route")
                self.assertEqual(status, 404)
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("X-Frame-Options"), "DENY")
                self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
                self.assertIn("default-src 'none'", headers.get("Content-Security-Policy", ""))
                status, body, headers = server.request("POST", "/api/state")
                self.assertEqual(status, 405)
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
            finally:
                server.close()

    def test_nothing_in_the_payload_calls_an_open_item_stalled_hung_or_stuck(self) -> None:
        """Every worded field this pass added ships inside ``/api/state``,
        so the vocabulary rule is re-checked against the whole payload -
        including a quiet-time note for an ambiguous open hand-off."""
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A", "subagent_type": "executor", "description": "first"},
            {"v": 1, "ts": "2026-08-01T10:05:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "B", "subagent_type": "executor", "description": "second"},
            {"v": 1, "ts": "2026-08-01T10:06:00Z", "event": "activity", "session": "s1",
             "agent_type": "executor", "tool": "Edit"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            state = keel_dashboard.read_state(_project(Path(tmp), lines))
        text = json.dumps(state).lower()
        for word in ("stalled", "hung", "stuck"):
            self.assertNotIn(word, text)


# --------------------------------------------------------------- T38 Host


def _raw_request(
    address: tuple[str, int],
    request_line: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, str], bytes]:
    """One request sent by hand over a REAL socket (T38).

    ``DashboardServer.request`` goes through ``urllib.request``, which
    ALWAYS injects a ``Host`` header of its own when none was given - so it
    cannot drive "no Host header at all", one of the seven cases T38 must
    prove. This talks the wire directly instead: ``request_line`` (e.g.
    ``"GET / HTTP/1.1"``) plus whatever ``headers`` are given - none of them
    implied - terminated by ``Connection: close`` so the socket's own EOF
    marks the end of the response and every byte can be read without racing
    a timeout.
    """
    with socket.create_connection(address, timeout=HTTP_TIMEOUT) as sock:
        sock.settimeout(HTTP_TIMEOUT)
        lines = [request_line]
        for name, value in (headers or {}).items():
            lines.append(f"{name}: {value}")
        lines.append("Connection: close")
        sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("ascii"))
        chunks: list[bytes] = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    raw = b"".join(chunks)
    head, _, body = raw.partition(b"\r\n\r\n")
    status_line, *header_lines = head.decode("iso-8859-1").split("\r\n")
    status = int(status_line.split(None, 2)[1])
    resp_headers: dict[str, str] = {}
    for line in header_lines:
        if ":" in line:
            key, _, value = line.partition(":")
            resp_headers[key.strip()] = value.strip()
    return status, resp_headers, body


class TestHostValidation(unittest.TestCase):
    """T38 - a request whose ``Host`` header does not name the loopback
    interface and port actually bound is refused BEFORE routing, carrying
    the same four security headers as every other response; both accepted
    spellings of that one interface, and a request with no ``Host`` header
    at all, are served. Every case is driven over a real socket
    (``_raw_request``), never by asserting on page text."""

    def _server(self, tmp: str) -> DashboardServer:
        return DashboardServer(_project(Path(tmp), []))

    def test_numeric_loopback_with_bound_port_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, _, _ = _raw_request(
                    server.server.server_address,
                    "GET / HTTP/1.1",
                    {"Host": f"127.0.0.1:{port}"},
                )
                self.assertEqual(status, 200)
            finally:
                server.close()

    def test_localhost_with_bound_port_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, _, _ = _raw_request(
                    server.server.server_address,
                    "GET / HTTP/1.1",
                    {"Host": f"localhost:{port}"},
                )
                self.assertEqual(status, 200)
            finally:
                server.close()

    def test_no_host_header_at_all_is_served(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                status, _, _ = _raw_request(
                    server.server.server_address, "GET / HTTP/1.1", {}
                )
                self.assertEqual(status, 200)
            finally:
                server.close()

    def test_foreign_name_with_bound_port_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, _, _ = _raw_request(
                    server.server.server_address,
                    "GET / HTTP/1.1",
                    {"Host": f"attacker.example:{port}"},
                )
                self.assertEqual(status, keel_dashboard.HOST_REFUSED_STATUS)
                self.assertNotIn(status, (404, 405))
            finally:
                server.close()

    def test_right_interface_wrong_port_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, _, _ = _raw_request(
                    server.server.server_address,
                    "GET / HTTP/1.1",
                    {"Host": f"127.0.0.1:{port + 1}"},
                )
                self.assertEqual(status, keel_dashboard.HOST_REFUSED_STATUS)
            finally:
                server.close()

    def test_refusal_carries_all_four_security_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, headers, _ = _raw_request(
                    server.server.server_address,
                    "GET / HTTP/1.1",
                    {"Host": f"attacker.example:{port}"},
                )
                self.assertEqual(status, keel_dashboard.HOST_REFUSED_STATUS)
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("X-Frame-Options"), "DENY")
                self.assertEqual(headers.get("Referrer-Policy"), "no-referrer")
                self.assertIn(
                    "default-src 'none'", headers.get("Content-Security-Policy", "")
                )
            finally:
                server.close()

    def test_write_method_still_returns_its_existing_refusal(self) -> None:
        """A write method's OWN refusal (405) is not shadowed by T38's - the
        Host check lives only in the read path (``do_GET``/``do_HEAD``)."""
        with tempfile.TemporaryDirectory() as tmp:
            server = self._server(tmp)
            try:
                port = server.server.server_address[1]
                status, _, body = _raw_request(
                    server.server.server_address,
                    "POST /api/state HTTP/1.1",
                    {"Host": f"attacker.example:{port}"},
                )
                self.assertEqual(status, 405)
                self.assertNotEqual(status, keel_dashboard.HOST_REFUSED_STATUS)
                self.assertIn(b"read-only", body)
            finally:
                server.close()


# ------------------------------------------------------- T4 the delegation graph


def _handoff(session: str, tid: str, agent: str, description: str, start: str,
             end: str | None = None, agent_id: str | None = None) -> list[dict[str, Any]]:
    """One hand-off as the log records it: a start, and an end when it closed.

    ``agent_id`` (T102's join key) lands on the END only, because that is
    where the producer puts it: the launch tool names the agent in its RESULT,
    which reaches keel at PostToolUse, so the start records a null.
    """
    lines = [
        {"v": 1, "ts": start, "event": "handoff_start", "session": session,
         "tool_use_id": tid, "agent_id": None, "subagent_type": agent,
         "description": description},
    ]
    if end:
        lines.append(
            {"v": 1, "ts": end, "event": "handoff_end", "session": session,
             "tool_use_id": tid, "agent_id": agent_id, "subagent_type": agent,
             "description": description}
        )
    return lines


def _graph_fixture() -> list[dict[str, Any]]:
    """One session with one CLOSED hand-off, two OPEN hand-offs of the SAME
    type, and one open hand-off of another - the shape every honesty rule on
    the canvas has to survive at once."""
    lines: list[dict[str, Any]] = [
        {"v": 1, "ts": "2026-08-01T09:00:00Z", "event": "session_start", "session": "s1"},
    ]
    lines += _handoff("s1", "t1", "keel:executor", "a closed hand-off",
                      "2026-08-01T09:10:00Z", "2026-08-01T09:12:00Z")
    lines.append({"v": 1, "ts": "2026-08-01T09:11:00Z", "event": "activity", "session": "s1",
                  "agent_type": "keel:executor", "tool": "Edit"})
    lines += _handoff("s1", "A", "keel:executor", "first of two open executors",
                      "2026-08-01T10:00:00Z")
    lines += _handoff("s1", "B", "keel:executor", "second of two open executors",
                      "2026-08-01T10:05:00Z")
    lines += _handoff("s1", "C", "keel:reviewer-correctness", "review the canvas",
                      "2026-08-01T10:30:00Z")
    return lines


class TestDelegationGraph(unittest.TestCase):
    """T4: the session as one node, a node per hand-off it made, and edges
    taken from the record.

    Every assertion here is a VALUE (see this module's "Values, not
    substrings"): the canvas is a payload ``compute_graph`` builds from the
    rows the page already renders, so what a reader sees can be read here
    without a browser. The handful of page-source checks below say so in
    their own docstrings.
    """

    def _state(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        # T109: every fixture in this class predates the finish-linger window
        # and uses fixed 2026-08-01 timestamps nowhere near the real wall
        # clock ``compute_graph`` now checks a FINISHED/AWAITED row's own
        # finish against. Patched here, at the one place every test in this
        # class reads state through, so a closed pair built to test the
        # STATE distinctions T4 already drew keeps being drawn rather than
        # aging out of every one of them at once - T109's own lingering
        # boundary is asserted directly against ``compute_graph``, not
        # through this class's decade-old fixtures.
        with unittest.mock.patch.object(keel_dashboard, "GRAPH_FINISH_LINGER_SECONDS", 10**9):
            with tempfile.TemporaryDirectory() as tmp:
                return keel_dashboard.read_state(_project(Path(tmp), lines))

    def test_the_canvas_draws_exactly_the_pairs_the_open_and_group_pass_produced(self) -> None:
        """THE structural claim of this task: nodes come from the hand-off
        pairs ``compute_open_and_groups`` already produced, so the canvas and
        the open rows cannot disagree. Asserted as set equality both ways -
        a node with no row behind it fails, and a row with no node fails."""
        state = self._state(_graph_fixture())
        nodes = state["graph"]["nodes"]
        drawn = {(n["row_kind"], n["agent_type"], n["task_label"]) for n in nodes}
        rows = {
            (item["row_kind"], item["agent_type"], item["description"])
            for item in state["open"]
            if item["row_kind"] == "open_handoff"
        }
        groups = {
            ("group", row["agent_type"], row["description"])
            for row in state["feed"]
            if row["row_kind"] == "group"
        }
        self.assertEqual(drawn, rows | groups)
        self.assertEqual(len(nodes), 4)

    def test_nothing_on_the_canvas_that_the_log_did_not_record(self) -> None:
        """Every agent type and every task on a card is a value some
        ``handoff_start`` line in the log actually carries."""
        lines = _graph_fixture()
        state = self._state(lines)
        recorded = {
            (line["subagent_type"], line["description"])
            for line in lines
            if line["event"] == "handoff_start"
        }
        for node in state["graph"]["nodes"]:
            with self.subTest(node=node["id"]):
                self.assertIn((node["agent_type"], node["task_label"]), recorded)

    def test_every_edge_runs_from_the_session_and_none_joins_two_handoffs(self) -> None:
        """Layout may not imply sequence. There is one edge per node, every
        one of them rooted at the session, and no edge whose two ends are
        both hand-offs - which is what a left-to-right chain would be."""
        graph = self._state(_graph_fixture())["graph"]
        ids = {node["id"] for node in graph["nodes"]}
        self.assertEqual(len(graph["edges"]), len(graph["nodes"]))
        self.assertEqual({edge["from"] for edge in graph["edges"]}, {"root"})
        self.assertEqual({edge["to"] for edge in graph["edges"]}, ids)
        self.assertNotIn("root", ids)
        for edge in graph["edges"]:
            self.assertNotIn(edge["from"], ids, "no edge may join two hand-offs")

    def test_a_card_names_the_agent_type_and_never_a_model_or_a_tier(self) -> None:
        """The log records who was ASKED, never which model answered, so the
        canvas carries the agent type and nothing that could be read as a
        model or a routing tier."""
        graph = self._state(_graph_fixture())["graph"]
        by_task = {node["task_label"]: node for node in graph["nodes"]}
        self.assertEqual(by_task["review the canvas"]["agent_label"], "keel:reviewer-correctness")
        self.assertEqual(by_task["a closed hand-off"]["agent_label"], "keel:executor")
        text = json.dumps(graph).lower()
        for word in ("opus", "sonnet", "haiku", "model", "tier"):
            self.assertNotIn(word, text)

    def test_a_start_line_with_no_type_or_no_task_says_so_rather_than_showing_a_blank(
        self,
    ) -> None:
        lines = [
            {"v": 1, "ts": "2026-08-01T10:00:00Z", "event": "handoff_start", "session": "s1",
             "tool_use_id": "A"},
        ]
        node = self._state(lines)["graph"]["nodes"][0]
        self.assertEqual(node["agent_label"], "no agent type recorded")
        self.assertEqual(node["task_label"], "no task description recorded")
        self.assertEqual(keel_dashboard.graph_agent_label("  "), "no agent type recorded")
        self.assertEqual(keel_dashboard.graph_task_label(None), "no task description recorded")

    def test_two_open_handoffs_of_one_type_say_the_record_names_the_kind(self) -> None:
        """The honesty rule this project has already paid for, on the canvas:
        with two of one type open at once the card says the record names the
        TYPE and not which of them it is, rather than picking one."""
        graph = self._state(_graph_fixture())["graph"]
        by_task = {node["task_label"]: node for node in graph["nodes"]}
        for task in ("first of two open executors", "second of two open executors"):
            node = by_task[task]
            with self.subTest(task=task):
                self.assertTrue(node["shares_type"])
                self.assertIn("the record names the agent type", node["type_note"])
                self.assertIn("not which of them this node is", node["type_note"])
        alone = by_task["review the canvas"]
        self.assertFalse(alone["shares_type"])
        self.assertEqual(alone["type_note"], "")
        self.assertFalse(by_task["a closed hand-off"]["shares_type"])

    def test_an_open_card_carries_the_quiet_time_wording_already_agreed(self) -> None:
        """No card invents a liveness vocabulary. An open node carries the
        SAME ``quiet_note``, threshold and ``last_seen_ts`` its own open row
        carries - one wording, one place, and it already says it is
        inferred."""
        state = self._state(_graph_fixture())
        rows = {item["ts"]: item for item in state["open"]}
        for node in state["graph"]["nodes"]:
            if not node["open"]:
                continue
            row = rows[node["ts"]]
            with self.subTest(node=node["id"]):
                self.assertEqual(node["quiet_note"], row["quiet_note"])
                self.assertEqual(
                    node["quiet_threshold_seconds"], row["quiet_threshold_seconds"]
                )
                self.assertEqual(node["last_seen_ts"], row["last_seen_ts"])
        text = json.dumps(state["graph"]).lower()
        for word in ("stalled", "hung", "stuck"):
            self.assertNotIn(word, text)

    def test_a_closed_card_reports_an_inferred_member_as_inferred(self) -> None:
        """A closed card's count is not a bare total where the record could
        not say which of two same-type hand-offs ran a line."""
        self.assertEqual(keel_dashboard.graph_count_label(0, 0), "no activity attributed")
        self.assertEqual(keel_dashboard.graph_count_label(3, 0), "3 event(s)")
        self.assertEqual(
            keel_dashboard.graph_count_label(3, 2), "3 event(s), 2 placed by inference"
        )
        lines: list[dict[str, Any]] = []
        for tid, start, end in (("A", "10:00:00", "10:10:00"), ("B", "10:01:00", "10:09:00")):
            lines += _handoff("s1", tid, "keel:executor", f"pair {tid}",
                              f"2026-08-01T{start}Z", f"2026-08-01T{end}Z")
        lines.append({"v": 1, "ts": "2026-08-01T10:05:00Z", "event": "activity",
                      "session": "s1", "agent_type": "keel:executor", "tool": "Edit"})
        nodes = self._state(lines)["graph"]["nodes"]
        labels = {node["count_label"] for node in nodes}
        self.assertIn("1 event(s), 1 placed by inference", labels)

    def test_the_session_drawn_is_the_most_recent_and_the_rest_are_counted(self) -> None:
        """One session is drawn; the others are stated rather than dropped
        without a word."""
        lines = _handoff("older", "o1", "keel:executor", "older work",
                         "2026-07-01T10:00:00Z", "2026-07-01T10:01:00Z")
        lines += _handoff("newer", "n1", "keel:researcher", "newer work",
                          "2026-08-01T10:00:00Z", "2026-08-01T10:01:00Z")
        graph = self._state(lines)["graph"]
        self.assertEqual(graph["session"], "newer")
        self.assertEqual(graph["counts"]["other_sessions"], 1)
        self.assertIn("session newer, the most recently recorded", graph["note"])
        self.assertIn("1 other session(s) with work of their own are not drawn", graph["note"])
        self.assertEqual([node["task_label"] for node in graph["nodes"]], ["newer work"])

    def test_the_node_bound_trims_only_closed_work_and_says_how_much(self) -> None:
        """``GRAPH_NODE_TAIL`` is a readability limit, not a silent one: it
        drops the OLDEST CLOSED hand-offs, never an open one, and the count
        it dropped is in the canvas's own sentence."""
        extra = 5
        lines: list[dict[str, Any]] = []
        for index in range(keel_dashboard.GRAPH_NODE_TAIL + extra):
            stamp = f"2026-08-01T{index // 60:02d}:{index % 60:02d}:00Z"
            done = f"2026-08-01T{index // 60:02d}:{index % 60:02d}:30Z"
            lines += _handoff("s1", f"c{index}", "keel:executor", f"closed {index}", stamp, done)
        lines += _handoff("s1", "OPEN1", "keel:researcher", "still open",
                          "2026-08-01T23:00:00Z")
        graph = self._state(lines)["graph"]
        tasks = [node["task_label"] for node in graph["nodes"]]
        self.assertEqual(len(tasks), keel_dashboard.GRAPH_NODE_TAIL)
        self.assertIn("still open", tasks)
        self.assertNotIn("closed 0", tasks, "the OLDEST closed work is what gives way")
        self.assertIn(f"closed {keel_dashboard.GRAPH_NODE_TAIL + extra - 1}", tasks)
        self.assertEqual(graph["counts"]["omitted"], extra + 1)
        self.assertIn(
            f"{extra + 1} older closed hand-off(s) of this session are not drawn",
            graph["note"],
        )

    def test_the_root_counts_what_hangs_off_it_in_its_own_words(self) -> None:
        graph = self._state(_graph_fixture())["graph"]
        self.assertEqual(graph["root"]["session"], "s1")
        self.assertEqual(graph["root"]["handoffs"], 4)
        self.assertEqual(graph["root"]["open"], 3)
        self.assertEqual(graph["root"]["open_sessions"], 1)
        self.assertEqual(
            graph["root"]["label"],
            "4 hand-off(s) drawn · 3 open now · 1 session line(s) still open",
        )
        self.assertEqual(
            keel_dashboard.graph_root_label(2, 0, 0), "2 hand-off(s) drawn · 0 open now"
        )

    def test_a_log_with_nothing_to_draw_says_that_rather_than_drawing_a_root(self) -> None:
        state = self._state([])
        self.assertIsNone(state["graph"]["root"])
        self.assertEqual(state["graph"]["nodes"], [])
        self.assertEqual(state["graph"]["edges"], [])
        self.assertEqual(state["graph"]["note"], keel_dashboard.GRAPH_EMPTY_NOTE)

    def test_working_now_counts_open_handoffs_and_is_not_the_attention_count(self) -> None:
        """The header figure this task adds. It counts open HAND-OFFS across
        the log; ``attention`` also counts an open session line, so the two
        are deliberately different numbers."""
        state = self._state(_graph_fixture())
        self.assertEqual(state["counts"]["working"], 3)
        self.assertEqual(state["counts"]["attention"], 4)
        self.assertEqual(
            state["counts"]["working"],
            sum(1 for item in state["open"] if item["row_kind"] == "open_handoff"),
        )

    def test_an_open_card_keys_on_exactly_what_its_open_row_keys_on(self) -> None:
        """How the one in-place writer can update a card and a row together:
        the three fields the page's ``openRowKey`` is built from are on both,
        with the same values."""
        state = self._state(_graph_fixture())
        keyed = {
            (item["row_kind"], item["session"], item["ts"])
            for item in state["open"]
            if item["row_kind"] == "open_handoff"
        }
        for node in state["graph"]["nodes"]:
            if node["open"]:
                self.assertIn((node["row_kind"], node["session"], node["ts"]), keyed)

    def test_the_canvas_keeps_every_pane_and_every_figure_that_was_there(
        self,
    ) -> None:
        """SUBSTRING, and declared: this is markup, not behaviour. A prettier
        page that showed LESS than the one before it would be a regression,
        so every pane and every figure the page carried before this task is
        named here.

        WHERE the canvas sits was a claim of T4's own ("above the audit
        feed") and T6 deliberately changed it: the canvas is now the primary
        region and the feed is a panel beside it. That arrangement is
        asserted in ``TestTheCanvasIsThePage`` below, against T6's own
        acceptance clause; what survives here unchanged is the list of things
        that may never disappear whatever the arrangement is, and it is
        LONGER than it was, not shorter.
        """
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), _graph_fixture()))
        for marker in PRESERVED_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        for figure in HEADER_FIGURES:
            with self.subTest(figure=figure):
                self.assertIn(figure, text)

    def test_the_page_states_that_a_cards_position_is_not_an_order(self) -> None:
        """SUBSTRING for the sentence itself - the words a reader sees are
        text and nothing else can stand in for them."""
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), _graph_fixture()))
        # The sentence is wrapped in the source; a reader sees it as one line.
        flat = " ".join(text.split())
        self.assertIn("no edge joins two hand-offs", flat)
        self.assertIn("the record carries no ordering between them", flat)
        self.assertIn("names the agent TYPE the record holds, never a model", flat)

    def test_every_value_a_card_shows_is_escaped_before_it_reaches_innerhtml(self) -> None:
        """A hostile ``description`` really does reach the canvas payload, so
        the escaping asserted here is protecting something that is there."""
        lines = _handoff("s1", "A", "keel:executor", '<img src=x onerror="alert(1)">',
                         "2026-08-01T10:00:00Z")
        state = self._state(lines)
        self.assertEqual(
            state["graph"]["nodes"][0]["task_label"], '<img src=x onerror="alert(1)">'
        )
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), lines))
        for interpolation in (
            "${esc(n.agent_label)}", "${esc(n.state_label)}", "${esc(n.task_label)}",
            "${esc(n.duration_label)}", "${esc(n.count_label)}", "${esc(n.type_note)}",
            "${esc(clock(n.ts))}", "${esc(openRowKey(n))}",
            "${esc(root.session)}", "${esc(root.label)}",
        ):
            with self.subTest(interpolation=interpolation):
                self.assertIn(interpolation, text)
        for raw in ("${n.agent_label}", "${n.task_label}", "${n.type_note}",
                    "${n.count_label}", "${root.session}", "${root.label}"):
            with self.subTest(raw=raw):
                self.assertNotIn(raw, text)

    def test_the_ticker_updates_a_card_in_place_and_can_never_redraw_the_canvas(
        self,
    ) -> None:
        """The canvas obeys the same law the feed does (T3): the one-second
        tick may rewrite a card's elapsed and quiet text through the one
        guarded in-place writer, and may not reach the function that builds
        the canvas's markup - so a poll that brings nothing new leaves both
        panes exactly as the reader left them.
        """
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), _graph_fixture())))
        functions = _functions(script)
        walker = _sole_function_containing(functions, '#canvas .node[data-key]')
        live = _sole_function_containing(functions, '[data-role="elapsed"]')
        self.assertIn(live, _calls(functions[walker], set(functions)))
        self.assertIn('#feed .ev.openrow[data-key]', functions[walker])
        ticker = _timer_target(script, "TICK_MS")
        canvas = _sole_function_containing(functions, '$("canvas").innerHTML')
        self.assertNotIn(canvas, _reachable(functions, ticker))
        self.assertIn(walker, _reachable(functions, ticker))
        full = _sole_function_containing(functions, canvas + "(")
        self.assertEqual(full, _sole_function_containing(functions, "feed("))


# ------------------------------------------- T6 the canvas becomes the page


class TestTheCanvasIsThePage(unittest.TestCase):
    """T6: the canvas is the page's primary region, the ledger and the audit
    feed are panels at the left that collapse and expand independently, and
    the palette is the two pinned references' - a near-black ground with a
    faint grid, card surfaces a shade lighter, thin light borders, curved
    wires and small coloured pills.

    There is no layout engine and no browser in this suite (see this module's
    "Values, not substrings"), so what is asserted here is the RULES a
    browser would apply and the STRUCTURE of the code that changes them -
    which region can grow, how wide each panel is open and collapsed, which
    element the collapse control names, and what the handler is able to
    touch. Two of those are genuine numbers rather than substrings: the
    panels' width against the width at which the side-by-side layout stops
    applying, and the ground's own colour against the card's. That the
    finished page LOOKS like the references, and that a collapse really does
    widen the canvas, is reported to the orchestrator from a hand-driven
    browser run at a wide and a narrow window, as this file's other layout
    claims are.
    """

    def _page_text(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            return _page(_project(Path(tmp), _graph_fixture()))

    def test_the_canvas_is_the_only_region_that_can_take_the_freed_width(self) -> None:
        """The acceptance clause's structural half. ``main`` is a row of
        three things - two fixed-width panels and the canvas - and the canvas
        is the ONLY flexible one, so every pixel a collapsed panel gives up
        can go nowhere else. This is why nothing in the collapse handler has
        to compute a width: the rule already decides it.
        """
        style = _style(self._page_text())
        self.assertIn("display:flex", _decl(style, "main"))
        side = _decl(style, "#side")
        self.assertIn("flex:none", side)
        panel = _decl(style, ".panel")
        self.assertIn("flex:none", panel)
        self.assertRegex(panel, r"width:\d+px")
        stage = _decl(style, ".stage")
        self.assertIn("flex:1 1 auto", stage)
        self.assertIn("min-width:0", stage)

    def test_the_canvas_takes_the_majority_at_every_width_this_layout_applies_at(
        self,
    ) -> None:
        """A NUMBER, not a claim: the panels open are less than half of the
        narrowest window at which they sit beside the canvas at all, so above
        that width the canvas always has the majority of it - and below it
        the layout changes shape (asserted separately) rather than squeezing
        the canvas into a strip.

        THE ARITHMETIC, NOT THE PROPERTY, IS WHAT T119 CHANGED. T6 put the
        two panels SIDE BY SIDE, so both open cost the window two panel
        widths and this read ``2 * panel``. T119 stacks them in ONE column -
        the reference's right sidebar, the ledger above the audit feed - so
        both open now cost exactly one panel width, and multiplying by two
        would be asserting against a layout the page no longer has. What is
        pinned is the same property it always was, against the width the
        sidebar actually takes.
        """
        style = _style(self._page_text())
        panel = int(re.search(r"width:(\d+)px", _decl(style, ".panel")).group(1))
        match = re.search(r"@media \(max-width:(\d+)px\)", style)
        self.assertIsNotNone(match, "the narrow layout must declare its own breakpoint")
        assert match
        narrow = int(match.group(1))
        self.assertLess(
            panel,
            narrow / 2,
            "the sidebar open must leave the canvas the majority of the window",
        )

    def test_each_panel_carries_its_own_control_and_collapses_on_its_own(self) -> None:
        """Two panels, two controls, two independent targets. Each control is
        a real button a reader can see and press (not a bare styled span),
        names the panel it belongs to, and states whether that panel is open.
        """
        text = self._page_text()
        for panel in ("p-ledger", "p-feed"):
            with self.subTest(panel=panel):
                self.assertIn(f'id="{panel}"', text)
                self.assertIn(f'data-panel="{panel}"', text)
        self.assertEqual(text.count('class="tog"'), 2)
        self.assertEqual(text.count('type="button" class="tog"'), 2)
        self.assertEqual(text.count('aria-expanded="true"'), 2)
        style = _style(text)
        shut = int(re.search(r"width:(\d+)px", _decl(style, ".panel.shut")).group(1))
        opened = int(re.search(r"width:(\d+)px", _decl(style, ".panel")).group(1))
        self.assertLess(shut, opened, "a collapsed panel must give width back")
        self.assertNotIn("display:none", _decl(style, ".panel.shut"))
        self.assertIn("display:none", _decl(style, ".panel.shut>:not(.phead)"))

    def test_collapsing_hides_a_panel_and_deletes_nothing(self) -> None:
        """Collapsed is not gone. The handler toggles ONE class on ONE panel:
        it assigns no markup, removes no node, and re-renders no pane - so
        every row, chip, task and figure the panel held is still in the
        document and comes back with the same control that closed it. It also
        has no route to the freshness node or to either pane's renderer,
        which is what keeps T3's disconnect notice safe from a new caller.
        """
        text = self._page_text()
        script = _script(text)
        functions = _functions(script)
        handler = _block_after(script, '$("side").addEventListener')
        self.assertIn('classList.toggle("shut")', handler)
        self.assertNotIn("innerHTML", handler)
        self.assertNotIn("outerHTML", handler)
        self.assertNotIn(".remove(", handler)
        self.assertNotIn(FRESHNESS_NODE, handler)
        reach = set()
        for name in _calls(handler, set(functions)):
            reach |= {name} | _reachable(functions, name)
        for forbidden in (
            _sole_function_containing(functions, PANE_MARKUP),
            _sole_function_containing(functions, FRESHNESS_NODE),
            _sole_function_containing(functions, '$("canvas").innerHTML'),
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, reach)

    def test_both_panels_still_hold_everything_they_held_before(self) -> None:
        """The panes that MOVED, checked where they moved TO: the ledger's
        selector, progress figure, task list, the filter chips, the feed and
        its losses line are all inside the left panels, and the rest of the
        preserved list is still on the page around them.
        """
        text = self._page_text()
        start, end = text.index('<div id="side">'), text.index('<div class="stage">')
        for marker in ('id="plansel"', 'id="progress"', 'id="ledger"',
                       'id="filters"', 'id="feed"', 'id="lost"'):
            with self.subTest(marker=marker):
                self.assertLess(start, text.index(marker))
                self.assertLess(text.index(marker), end)
        for marker in PRESERVED_MARKERS:
            with self.subTest(marker=marker):
                self.assertIn(marker, text)
        for figure in HEADER_FIGURES:
            with self.subTest(figure=figure):
                self.assertIn(figure, text)

    def test_the_ground_is_near_black_and_carries_a_faint_grid(self) -> None:
        """VALUES: the ground is darker than the panel, which is darker than
        a card, which is darker than the border it carries - the reference's
        own ordering, read as numbers rather than as colour names - and the
        grid is drawn by a gradient rather than by an image.
        """
        style = _style(self._page_text())
        shades = {}
        for name in ("bg", "panel", "card", "line2"):
            match = re.search(r"--" + name + r":#([0-9a-f]{6})", style)
            self.assertIsNotNone(match, name)
            assert match
            shades[name] = int(match.group(1), 16)
        self.assertLess(shades["bg"], shades["panel"])
        self.assertLess(shades["panel"], shades["card"])
        self.assertLess(shades["card"], shades["line2"])
        self.assertLess(shades["bg"], 0x151515, "the ground is near-black")
        stage = _decl(style, ".stage")
        self.assertIn("radial-gradient", stage)
        self.assertIn("background-size:22px 22px", stage)

    def test_the_root_node_is_treated_differently_from_a_worker_card(self) -> None:
        """Both references give the centre node its own treatment, so the
        page does too: its own accent border, its own pill, and a rule a
        worker card does not share.
        """
        text = self._page_text()
        style = _style(text)
        root, node = _decl(style, ".rootnode"), _decl(style, ".node")
        self.assertIn("var(--root)", root)
        self.assertNotIn("var(--root)", node)
        self.assertIn("box-shadow", root)
        self.assertNotIn("box-shadow", node)
        functions = _functions(_script(text))
        self.assertIn('class="rpill"', functions["rootCard"])
        self.assertNotIn('class="rpill"', functions["nodeCard"])
        self.assertIn('class="role"', functions["nodeCard"])
        self.assertIn('class="pill', functions["nodeCard"])
        for pill in (".role", ".pill"):
            with self.subTest(pill=pill):
                self.assertIn("border-radius:999px", _decl(style, pill))

    def test_the_wires_are_curves_this_page_draws_itself(self) -> None:
        """Curved, and drawn - a cubic bezier and a circular port per card,
        emitted as inline SVG from numbers the page measured off the DOM. No
        image is fetched, because the content policy forbids one and there is
        no network to fetch it over.
        """
        text = self._page_text()
        functions = _functions(_script(text))
        wires = _sole_function_containing(functions, "getBoundingClientRect")
        body = functions[wires]
        self.assertIn(' C ', body, "a curve, not a straight line")
        self.assertIn('<path class="wire', body)
        self.assertIn('<circle class="port', body)
        self.assertIn("getBoundingClientRect", body)
        style = _style(text)
        self.assertIn("fill:none", _decl(style, ".wire"))
        self.assertIn("stroke-dasharray", _decl(style, ".wire"))
        self.assertIn("stroke-dasharray:none", _decl(style, ".wire.live"))

    def test_the_page_still_fetches_nothing_from_anywhere(self) -> None:
        """The content policy's own claim, checked against the page rather
        than trusted: one inline style block, one inline script, and no
        external stylesheet, font, script, image or frame anywhere in it.
        """
        text = self._page_text()
        self.assertEqual(text.count("<style>"), 1)
        self.assertEqual(text.count("<script>"), 1)
        for forbidden in ("http://", "https://", "@import", "url(", "<link",
                          "<img", "<iframe", "<object", "@font-face", " src="):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        policy = dict(keel_dashboard.SECURITY_HEADERS)["Content-Security-Policy"]
        self.assertIn("default-src 'none'", policy)
        self.assertIn("connect-src 'self'", policy)

    def test_a_narrow_window_keeps_every_region_and_keeps_the_canvas_first(self) -> None:
        """The page must be readable narrow as well as wide. Below the
        breakpoint the row becomes a column, the canvas comes FIRST and keeps
        the majority of the height, the panels fall below it at full width,
        and a collapsed panel becomes a horizontal bar rather than a rail too
        narrow to read - nothing is dropped at any width.
        """
        style = _style(self._page_text())
        narrow = style[style.index("@media (max-width:") :]
        self.assertIn("flex-direction:column", _decl(narrow, "main"))
        stage = _decl(narrow, ".stage")
        self.assertIn("order:1", stage)
        self.assertIn("order:2", _decl(narrow, "#side"))
        height = int(re.search(r"min-height:(\d+)vh", stage).group(1))
        self.assertGreater(height, 50, "the canvas keeps the majority of a narrow window")
        self.assertIn("width:auto", _decl(narrow, ".panel"))
        self.assertIn("writing-mode:horizontal-tb", _decl(narrow, ".panel.shut .ttl"))
        self.assertNotIn("display:none", narrow)

    def test_the_rebuilt_card_still_says_only_what_the_record_holds(self) -> None:
        """The honesty rules are unchanged by a repaint. The card renderer
        shows the server's own labels and carries no vocabulary of its own -
        no model, no routing tier, and nothing that calls an open hand-off
        stalled, hung or stuck. What those labels SAY is asserted by value in
        ``TestDelegationGraph``; this pins that the rebuilt markup adds no
        second wording beside them.
        """
        functions = _functions(_script(self._page_text()))
        card = functions["nodeCard"].lower()
        for word in ("opus", "sonnet", "haiku", "model", "tier", "stalled",
                     "hung", "stuck"):
            with self.subTest(word=word):
                self.assertNotIn(word, card)
        for field in ("n.agent_label", "n.state_label", "n.task_label",
                      "n.count_label", "n.duration_label", "n.type_note"):
            with self.subTest(field=field):
                self.assertIn("esc(" + field + ")", functions["nodeCard"])


# ---------------------------------------------------- T5 the long OPEN row


class TestALongOpenRowStaysOnItsLine(unittest.TestCase):
    """T5: an OPEN row whose quiet-time note runs to a full sentence used to
    render its session identifier one character per line, standing hundreds
    of pixels tall and pushing every later row off the screen.

    There is no layout engine in this suite, so what is asserted here is the
    two things that CAUSED it and the one thing that could hide it: the row's
    text column no longer declares a break rule that shrinks its minimum
    width to a single character, the note no longer sits beside that column
    as an unwrappable block, and the note's own wording is untouched - the
    fix had to be the row's layout, because shortening an honest sentence to
    make it fit is the trade this project already refused. The behaviour
    itself is reported from a hand-driven browser run, as this file's other
    layout claims are.
    """

    def _style(self) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            text = _page(_project(Path(tmp), []))
        return text[text.index("<style>") : text.index("</style>")]

    def test_the_rows_text_column_may_not_shrink_below_its_longest_word(self) -> None:
        style = self._style()
        self.assertIn(".ev .d{flex:1 1 240px;min-width:0;overflow-wrap:break-word}", style)
        self.assertNotIn("overflow-wrap:anywhere", style.split(".ev .d")[1].split("}")[0])
        self.assertIn("flex-wrap:wrap", style.split(".ev{")[1].split("}")[0])

    def test_the_quiet_note_takes_its_own_line_instead_of_the_rows_width(self) -> None:
        # The base rule, not the canvas card's override of it.
        quiet = self._style().split("\n.quiet{")[1].split("}")[0]
        self.assertIn("flex:1 1 100%", quiet)
        self.assertNotIn("white-space:nowrap", quiet)
        self.assertIn("overflow-wrap:break-word", quiet)

    def test_no_class_the_open_row_uses_can_break_between_characters(self) -> None:
        """The rule that caused it is gone from every class an OPEN row
        actually renders with - the text column and the dim prompt aside -
        not merely from one of them."""
        style = self._style()
        for selector in (".ev .d{", ".d2{"):
            block = style.split(selector)[1].split("}")[0]
            with self.subTest(selector=selector):
                self.assertIn("overflow-wrap:break-word", block)
                self.assertNotIn("anywhere", block)

    def test_the_note_itself_was_not_shortened_to_make_it_fit(self) -> None:
        """The wording is the one T30 and T37 settled on, unchanged by this
        layout fix - asserted as a VALUE, from the function that words it."""
        self.assertEqual(
            keel_dashboard.quiet_note("tool_running", False),
            "no event since it started, past 10m 0s - a slow command is not a stall",
        )
        self.assertIn(
            "the record names the agent type, not which one ran them",
            keel_dashboard.quiet_note("between_calls", True, "keel:executor"),
        )

    def test_the_row_still_carries_the_markers_the_in_place_writer_reads(self) -> None:
        """Moving the note after the elapsed figure changed the ORDER of a
        row's parts, so the two markers the ticker finds them by are checked
        again here rather than assumed."""
        with tempfile.TemporaryDirectory() as tmp:
            script = _script(_page(_project(Path(tmp), [])))
        row = _functions(script)["openRow"]
        self.assertIn('data-role="elapsed"', row)
        self.assertIn('data-role="quiet"', row)
        self.assertLess(row.index('data-role="elapsed"'), row.index("${quietBit}"))


if __name__ == "__main__":
    unittest.main()
