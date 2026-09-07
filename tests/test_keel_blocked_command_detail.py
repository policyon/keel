#!/usr/bin/env python3
"""The blocked-command audit detail - ``keel_gate.blocked_command_detail``.

The middle path ruled on 2026-08-13
(``.keel/decisions/2026-08-13-gate-block-detail-middle-path.md``): a blocked
command used to reach the log as the opaque ``<command>``, which leaks nothing
and says nothing; the predecessor board prints the command raw, which says
everything and leaks it. What ships instead is the command itself, passed
through the SHIPPED redaction chokepoint and cut to a head - and, when
redaction cannot run, the opaque mask again rather than raw text.

Both directions are pinned here, because only one of them can be observed in
normal operation:

* HEALTHY - the head is redacted first and cut second, and the bytes that
  reach the audit file on disk carry no account name and no registered name.
* BROKEN - ``redact`` raises, or returns something that is not usable text,
  and the detail falls back to ``keel_gate.OPAQUE_COMMAND`` while the gate
  goes on blocking and go on auditing exactly as before.

The broken direction is simulated by swapping ``keel_gate``'s own module-level
``redact`` reference for the width of one test (restored in ``finally``, even
on failure). That is the narrowest possible simulation: ``keel_redact`` itself
is untouched, so the write-time chokepoint in ``keel_events._append_jsonl``
keeps running with the real redactor - which is what makes the fallback
assertion meaningful rather than a tautology about a disabled screen.

Why a separate file rather than ``tests/test_keel_kernel.py``
--------------------------------------------------------------
Two tests here monkeypatch module state (``keel_gate.redact``,
``keel_redact._DENIED_HASHES``), which nothing in the kernel suite does; and
the end-to-end cases read the audit log back off DISK, the way
``tests/test_keel_home_shapes.py`` does, because the question the ruling
raises is what reaches a git-tracked file.

Contract
--------
Reads   : the installation's own ``hooks/`` and ``scripts/`` modules. Every
          register these tests use is written by the test itself and holds
          only the digest of an ordinary word ("pineapple") - never a name
          this repository's real register forbids.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes; the
          gate is always pointed at a throwaway project, never at this
          repository's own ``.keel/``.

NO REAL USERNAME AND NO REAL DENIED NAME APPEARS ANYWHERE IN THIS FILE. The
account names are invented, and - following ``tests/test_keel_home_shapes.py``
- no LITERAL home root followed by a name is written in this source at all:
the roots are assembled from ``WIN_ROOT``/``NIX_ROOT`` and the separators from
``chr(92)``, so ``scripts/keel_leak_check.py`` has nothing to report on this
file and its output stays honest. ``chr(92)`` rather than an escaped literal
is also the local convention for building a Windows path in a test: a
backslash written into a source file through a shell heredoc collapses on this
machine, and a constant cannot.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager, redirect_stderr
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_leak_check  # noqa: E402
import keel_redact  # noqa: E402

#: One backslash, built rather than written. See the module docstring.
BS = chr(92)

#: The two home roots, spelled apart from the account name that follows them
#: so that no home-shaped path appears literally in this file.
WIN_ROOT = "Users"
NIX_ROOT = "home"

#: Invented account names. Not people, and not this machine's user.
ACCOUNT = "tamsin-vellacott"
OTHER_ACCOUNT = "orrin-brackwell"

#: An ordinary word standing in for a registered name, hashed into a register
#: this test writes itself. The real register is never read here.
WORD = "pineapple"

#: The marker a home-shaped path becomes, and the one a registered name does.
HOME_MARK = keel_redact.HOME_SHAPE_TOKEN
NAME_MARK = keel_redact.DENIED_NAME_TOKEN

#: A home directory in each slash direction. BOTH are needed: this project has
#: twice shipped a screen that caught one spelling and missed the other.
WIN_PATH = f"C:{BS}{WIN_ROOT}{BS}{ACCOUNT}{BS}notes.txt"
POSIX_PATH = f"/{NIX_ROOT}/{OTHER_ACCOUNT}/notes.txt"
WIN_PATH_FORWARD = f"C:/{WIN_ROOT}/{ACCOUNT}/notes.txt"


def digest(token: str) -> str:
    """The register's own algorithm: sha256 of the casefolded token."""
    return hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()


def leak_findings(value: str) -> list[str]:
    """``scripts/keel_leak_check.py``'s home-path verdict on one value.

    The second line of defence, asked directly: a detail that passes this has
    nothing for the pre-push scan to find later.
    """
    return [finding.excerpt for finding in keel_leak_check.home_path_findings("x", 1, value)]


def armed_project(root: Path) -> Path:
    """A project keel enforces in: tier 2, no plan on file for any session."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\ntier: 2\n---\n\n# policy\n", encoding="utf-8"
    )
    return project


def exec_event(project: Path, command: str) -> keel_events.KeelEvent:
    """One shell tool call, shaped the way the adapter shapes it."""
    return keel_events.KeelEvent(
        kind="pre_exec",
        cwd=project,
        session_id=uuid.uuid4().hex,
        tool_name="Bash",
        command=command,
        raw={"tool_input": {"command": command}},
    )


def audit_text(project: Path) -> str:
    """The audit log exactly as it landed on disk. Fails if nothing was written."""
    path = keel_events.audit_path(project)
    if not path.is_file():
        raise AssertionError(f"no audit line was written to {path}")
    return path.read_bytes().decode("utf-8")


def audit_lines(project: Path) -> list[dict[str, Any]]:
    """Every audit line, decoded."""
    return [json.loads(line) for line in audit_text(project).splitlines() if line.strip()]


@contextmanager
def redactor_that(behaviour: Any) -> Iterator[None]:
    """Swap ``keel_gate``'s own ``redact`` reference for one test.

    ``keel_redact`` itself is left alone, so the write-time chokepoint still
    screens whatever the gate hands it - see the module docstring.
    """
    original = keel_gate.redact
    keel_gate.redact = behaviour
    try:
        yield
    finally:
        keel_gate.redact = original


@contextmanager
def register_holding(*tokens: str) -> Iterator[None]:
    """Screen ``tokens`` as registered names for the width of one test."""
    original = keel_redact._DENIED_HASHES
    keel_redact._DENIED_HASHES = frozenset(digest(token) for token in tokens)
    try:
        yield
    finally:
        keel_redact._DENIED_HASHES = original


class TestTheHeadIsRedactedFirstAndCutSecond(unittest.TestCase):
    """The healthy direction, at the function."""

    def test_an_ordinary_command_reaches_the_detail_in_full(self) -> None:
        """The whole point of the ruling: a reader sees what was refused."""
        self.assertEqual(
            keel_gate.blocked_command_detail("rm -rf build/cache"), "rm -rf build/cache"
        )

    def test_a_home_path_in_both_slash_directions_is_screened(self) -> None:
        command = f"cp {WIN_PATH} {POSIX_PATH}"
        detail = keel_gate.blocked_command_detail(command)
        self.assertNotIn(ACCOUNT, detail)
        self.assertNotIn(OTHER_ACCOUNT, detail)
        self.assertEqual(detail, f"cp C:{BS}{HOME_MARK}{BS}notes.txt /{HOME_MARK}/notes.txt")
        self.assertEqual(leak_findings(detail), [])

    def test_a_windows_home_written_with_forward_slashes_is_screened_too(self) -> None:
        """The spelling a shell on Windows accepts and a pattern anchored on
        backslashes misses - the exact way this screen has failed before."""
        detail = keel_gate.blocked_command_detail(f"type {WIN_PATH_FORWARD}")
        self.assertNotIn(ACCOUNT, detail)
        self.assertEqual(detail, f"type C:/{HOME_MARK}/notes.txt")
        self.assertEqual(leak_findings(detail), [])

    def test_a_registered_name_becomes_the_register_token(self) -> None:
        with register_holding(WORD):
            detail = keel_gate.blocked_command_detail(f"python scripts/{WORD}_report.py --now")
        self.assertNotIn(WORD, detail)
        self.assertIn(NAME_MARK, detail)

    def test_a_private_region_never_reaches_the_head(self) -> None:
        """``strip_private`` runs first and unconditionally inside ``redact``."""
        tag = keel_redact.PRIVATE_TAG
        command = f"echo <{tag}>the-quiet-part</{tag}> done"
        detail = keel_gate.blocked_command_detail(command)
        self.assertNotIn("the-quiet-part", detail)
        self.assertEqual(detail, "echo  done")

    def test_an_unclosed_private_marker_drops_the_tail_rather_than_passing_it(self) -> None:
        """The redactor's own fail-closed behaviour, reached through the gate:
        a marker nobody closed truncates the value instead of publishing it."""
        tag = keel_redact.PRIVATE_TAG
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            detail = keel_gate.blocked_command_detail(f"echo before <{tag}> after-the-marker")
        self.assertEqual(detail, "echo before ")
        self.assertNotIn("after-the-marker", detail)

    def test_the_head_is_bounded_at_the_capture_modules_number(self) -> None:
        long_command = "echo " + ("a" * 500)
        detail = keel_gate.blocked_command_detail(long_command)
        self.assertEqual(len(detail), keel_gate.BLOCKED_COMMAND_HEAD_CHARS)
        self.assertTrue(long_command.startswith(detail))
        self.assertEqual(
            keel_gate.BLOCKED_COMMAND_HEAD_CHARS,
            keel_capture.COMMAND_DETAIL_CHARS,
            "the gate's head and the recorder's head are one bargain, not two",
        )

    def test_a_payload_past_the_scan_bound_is_still_screened_in_its_head(self) -> None:
        """The cost bound is not a privacy bound: what is cut at
        ``BLOCKED_COMMAND_SCAN_CHARS`` is far beyond the head, so nothing it
        drops could have appeared in the head anyway."""
        command = f"cp {WIN_PATH} " + ("z" * (keel_gate.BLOCKED_COMMAND_SCAN_CHARS * 3))
        detail = keel_gate.blocked_command_detail(command)
        self.assertNotIn(ACCOUNT, detail)
        self.assertIn(HOME_MARK, detail)
        self.assertEqual(len(detail), keel_gate.BLOCKED_COMMAND_HEAD_CHARS)

    def test_cutting_after_redaction_is_what_keeps_a_straddling_name_whole(self) -> None:
        """The ORDER is the security argument, so the other order is pinned as
        a leak rather than left as an assertion about a shape that was never
        dangerous.

        The case that actually leaks is a REGISTERED NAME straddling the head
        boundary: the register matches whole tokens, so half a registered name
        hashes to nothing and passes the screen untouched. (A home-shaped path
        cut in half is caught anyway - ``keel_redact._HOME_SHAPE_RE`` matches a
        truncated account segment on purpose - so the cost of the wrong order
        there is cosmetic. Both are stated so the next reader knows which one
        the order is defending.)
        """
        head = keel_gate.BLOCKED_COMMAND_HEAD_CHARS
        prefix = "python scripts/report.py --profile "
        # Padded so the name starts four characters before the head boundary:
        # a cut made first would keep exactly those four and drop the rest,
        # which is what makes the fragment unmatchable.
        command = prefix + "x" * (head - len(prefix) - 5) + " " + WORD + " --now"
        self.assertTrue(command[:head].endswith(WORD[:4]), "the fixture must straddle the bound")
        with register_holding(WORD):
            naive = keel_redact.redact(command[:head])
            detail = keel_gate.blocked_command_detail(command)
        self.assertIn(WORD[:4], naive, "cut-then-redact leaves a fragment of the name")
        self.assertNotIn(WORD[:4], detail)
        self.assertEqual(len(detail), head)

    def test_the_detail_is_always_a_non_empty_string(self) -> None:
        """The field's shape is unchanged by this ruling: a string, never a
        null and never an empty one, on every path through the function."""
        for command in ("", "   ", None, 17, {"command": "ls"}):
            with self.subTest(command=command):
                detail = keel_gate.blocked_command_detail(command)
                self.assertIsInstance(detail, str)
                self.assertTrue(detail.strip())
        self.assertEqual(keel_gate.blocked_command_detail(""), keel_gate.OPAQUE_COMMAND)
        self.assertEqual(keel_gate.blocked_command_detail(None), keel_gate.OPAQUE_COMMAND)


class TestFailClosedWhenRedactionCannotRun(unittest.TestCase):
    """The broken direction: never raw, never silent, never fatal to the gate."""

    def test_a_redactor_that_raises_falls_back_to_the_opaque_mask(self) -> None:
        def boom(value: Any) -> Any:
            raise RuntimeError("register unreadable")

        stderr = io.StringIO()
        with redactor_that(boom), redirect_stderr(stderr):
            detail = keel_gate.blocked_command_detail(f"cp {WIN_PATH} /tmp/x")
        self.assertEqual(detail, keel_gate.OPAQUE_COMMAND)
        self.assertNotIn(ACCOUNT, detail)
        self.assertIn(keel_gate.OPAQUE_COMMAND, stderr.getvalue())
        self.assertIn("RuntimeError", stderr.getvalue())
        self.assertNotIn(ACCOUNT, stderr.getvalue(), "the report may not leak what it refused")

    def test_a_redactor_that_returns_a_non_string_falls_back(self) -> None:
        """A degraded process can hand back something that is not text at all;
        the field must still be a usable string."""
        for result in (None, 17, ["cp"]):
            with self.subTest(result=result), redactor_that(lambda value: result):
                self.assertEqual(
                    keel_gate.blocked_command_detail("cp a b"), keel_gate.OPAQUE_COMMAND
                )

    def test_a_redactor_that_returns_blank_text_falls_back(self) -> None:
        """An empty detail would read as "the gate recorded nothing" rather
        than "the gate refused to say"."""
        with redactor_that(lambda value: "   "):
            self.assertEqual(keel_gate.blocked_command_detail("cp a b"), keel_gate.OPAQUE_COMMAND)

    def test_the_gate_still_blocks_and_still_audits_when_redaction_raises(self) -> None:
        """End to end, through ``keel_gate.run`` - the function the hook calls.
        A refusal to name the command may not become a refusal to gate."""

        def boom(value: Any) -> Any:
            raise RuntimeError("register unreadable")

        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            event = exec_event(project, f"cp {WIN_PATH} {POSIX_PATH}")
            stderr = io.StringIO()
            with redactor_that(boom), redirect_stderr(stderr):
                verdict = keel_gate.run(event, {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            self.assertEqual(verdict.detail["target"], keel_gate.OPAQUE_COMMAND)
            text = audit_text(project)
            self.assertNotIn(ACCOUNT, text)
            self.assertNotIn(OTHER_ACCOUNT, text)
            self.assertNotIn("notes.txt", text, "the fallback is opaque, not partial")
            line = audit_lines(project)[-1]
            self.assertEqual(line["event"], "gate_block")
            self.assertEqual(line["detail"]["target"], keel_gate.OPAQUE_COMMAND)
            self.assertEqual(leak_findings(text), [])


class TestTheLineOnDiskCarriesTheRedactedHead(unittest.TestCase):
    """The healthy direction, read back off disk rather than from the verdict."""

    def test_a_blocked_command_is_logged_by_its_head_with_no_account_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            event = exec_event(project, f"cp {WIN_PATH} {POSIX_PATH}")
            verdict = keel_gate.run(event, {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            text = audit_text(project)
            self.assertNotIn(ACCOUNT, text)
            self.assertNotIn(OTHER_ACCOUNT, text)
            line = audit_lines(project)[-1]
            self.assertEqual(line["event"], "gate_block")
            self.assertEqual(
                line["detail"]["target"],
                f"cp C:{BS}{HOME_MARK}{BS}notes.txt /{HOME_MARK}/notes.txt",
            )
            self.assertEqual(leak_findings(text), [])

    def test_the_line_still_parses_exactly_as_it_did_before_the_ruling(self) -> None:
        """Additive only: ``detail`` is the same mapping with the same keys -
        only the value of ``target`` is more legible than it was."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            keel_gate.run(exec_event(project, "rm -rf build/cache"), {})
            line = audit_lines(project)[-1]
            self.assertEqual(
                set(line), {"v", "ts", "event", "gate", "kind", "tool", "session", "detail"}
            )
            self.assertEqual(set(line["detail"]), {"target"})
            self.assertEqual(line["detail"]["target"], "rm -rf build/cache")

    def test_a_bypass_line_names_the_command_the_override_let_through(self) -> None:
        """``_audit_bypass`` is the second writer the ruling reaches: the
        override is the one sanctioned hole in the lock, so its line has to say
        what went through it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            command = f"Set-Content hooks/keel_gate.py {WIN_PATH}"
            keel_gate.run(exec_event(project, command), {"KEEL_OVERRIDE": "on"})
            bypass = [line for line in audit_lines(project) if line["event"] == "gate_bypass"]
            self.assertEqual(len(bypass), 1, audit_lines(project))
            self.assertEqual(
                bypass[0]["detail"],
                {
                    "target": f"Set-Content hooks/keel_gate.py C:{BS}{HOME_MARK}{BS}notes.txt",
                    "switch": "KEEL_OVERRIDE",
                },
            )
            self.assertNotIn(ACCOUNT, audit_text(project))
            self.assertEqual(leak_findings(audit_text(project)), [])

    def test_a_registered_name_in_a_blocked_command_never_reaches_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            with register_holding(WORD):
                keel_gate.run(exec_event(project, f"python scripts/{WORD}_report.py"), {})
            text = audit_text(project)
            self.assertNotIn(WORD, text)
            self.assertIn(NAME_MARK, text)


if __name__ == "__main__":
    unittest.main()
