#!/usr/bin/env python3
"""The delegation-finish subscription: registration, production, consumption.

Contract
--------
Reads   : ``hooks/hooks.json``, the sources of ``hooks/keel_hook.py`` and
          ``hooks/keel_stop.py`` for their declared-policy assertions, every
          other ``*.py`` GIT TRACKS for the second-consumer scan - enumerated
          with ``git ls-files`` so that this machine and a CI checkout see the
          same set - plus this repository's own ``.keel/audit/keel-audit.jsonl``
          - read only, copied into a temporary project, never written.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, so a developer's own shell
          cannot change what a test observes.

What this file is for
---------------------
``hooks/keel_stop.py`` has branched on a ``subagent_stop`` audit line since
several waves before anything produced one: the consumer was written, and
nothing ever subscribed to the event that would feed it. Every case here fails
if that subscription is removed again - the ``SubagentStop`` row in
``keel_gen_hooks.ENTRIES``, the ``subagent_stop`` entry in
``keel_hook.SUBCOMMANDS``, or the handler behind it. Registration is asserted
against the generated document; production is asserted by RUNNING the launcher
as a subprocess and reading the bytes it left on disk, never by inspecting the
function that would have written them.

House style: fixtures are executed the way continuous integration will -
``python hooks/keel_hook.py <subcommand>`` as a real subprocess with JSON on
stdin - so what is asserted is what a harness would get.

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
HOOKS_DIR = REPO_ROOT / "hooks"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

#: This repository's own audit log. Long, append-only, and carrying several
#: schema generations - which is exactly why the "existing lines still parse"
#: case is asserted against it rather than against a fixture somebody wrote to
#: pass.
REAL_AUDIT = REPO_ROOT.joinpath(*AUDIT_RELPATH)

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import keel_attest  # noqa: E402
import keel_gen_hooks  # noqa: E402  (path must be set first)
import keel_hook  # noqa: E402
import keel_stop  # noqa: E402
from keel_published_cut import contradiction, is_published_cut  # noqa: E402

#: The wire value. Spelled out here rather than imported, deliberately: this
#: file is the guard against the producer and the consumer drifting apart, and
#: a guard that imports the name it is checking cannot see them drift.
STOP_EVENT = "subagent_stop"

#: A payload shaped like the one the harness actually sends. The two identity
#: fields are what a real ``SubagentStop`` carries; ``agent_type`` is often
#: blank in the field, which is why a case below pins the blank spelling.
AGENT_ID = "a8a960cff0a7d4560"
AGENT_TYPE = "keel:executor-deep"


def utc_stamp(seconds_ago: int = 0) -> str:
    """A timestamp in keel's own spelling, offset into the past."""
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment every subprocess here runs with: no keel state at all."""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


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


#: The launch acknowledgment's TEXT, in the shape the harness renders it: a
#: sentence, then the id on its own labelled line. Used for the case where a
#: hook is handed the rendered result rather than the structured one, and for
#: proving that none of this prose reaches the audit log - only the id does.
LAUNCH_ACK = (
    "Async agent launched successfully. (This tool result is internal "
    "metadata.)\nagentId: {agent_id} (internal ID - do not mention.)\n"
    "The agent is working in the background."
)


def task_payloads(
    project: Path, session: str, agent_id: str
) -> list[dict[str, Any]]:
    """The two capture payloads one backgrounded delegation produces.

    PreToolUse then PostToolUse on ``Task``, in the harness's own shape: the
    same ``tool_use_id`` on both, ``tool_input`` on both, and the launch
    tool's RESULT on the second only - which is the whole asymmetry the join
    key has to live with.
    """
    common: dict[str, Any] = {
        "tool_name": "Task",
        "tool_use_id": "toolu_launch_1",
        "tool_input": {
            "subagent_type": AGENT_TYPE,
            "description": "a delegation",
            "prompt": "TASK: do the thing",
        },
        "session_id": session,
        "cwd": str(project),
    }
    return [
        dict(common, hook_event_name="PreToolUse"),
        dict(
            common,
            hook_event_name="PostToolUse",
            tool_response={
                "isAsync": True,
                "status": "async_launched",
                "agentId": agent_id,
                "description": "a delegation",
                "prompt": "TASK: do the thing",
                "content": [{"type": "text", "text": LAUNCH_ACK.format(agent_id=agent_id)}],
            },
        ),
    ]


def run_hook(
    subcommand: str, payload: Any, project: Path, scratch: Path
) -> subprocess.CompletedProcess[bytes]:
    """Run the launcher exactly as a harness does: argv, JSON on stdin."""
    if isinstance(payload, (bytes, bytearray)):
        stdin = bytes(payload)
    else:
        stdin = json.dumps(payload).encode("utf-8")
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), subcommand],
        input=stdin,
        capture_output=True,
        env=clean_env(scratch),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def audit_lines(project: Path) -> list[str]:
    """Every non-empty raw line of a project's audit log, in order."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.is_file():
        return []
    return [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def audit_records(project: Path) -> list[dict[str, Any]]:
    """Every audit line of a project, decoded. A bad line fails the test."""
    return [json.loads(line) for line in audit_lines(project)]


def stops_in(project: Path) -> list[dict[str, Any]]:
    """Only the delegation-finish lines."""
    return [r for r in audit_records(project) if r.get("event") == STOP_EVENT]


def adopted_project(root: Path) -> Path:
    """A project keel would record in: it carries ``.keel/``, nothing more."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    return project


class TestTheEventIsRegistered(unittest.TestCase):
    """The producer half that was missing: a registration and a route to it."""

    def _document(self) -> dict[str, Any]:
        return json.loads(HOOKS_JSON.read_text(encoding="utf-8"))

    def test_the_generated_document_registers_subagentstop(self) -> None:
        self.assertIn(
            "SubagentStop",
            self._document()["hooks"],
            "hooks.json does not subscribe to the delegation-finish event",
        )

    def test_the_registration_routes_to_the_subagent_stop_subcommand(self) -> None:
        groups = self._document()["hooks"]["SubagentStop"]
        self.assertEqual(len(groups), 1, groups)
        hooks = groups[0]["hooks"]
        self.assertEqual(len(hooks), 1, hooks)
        command = hooks[0]["command"]
        self.assertIn("hooks/keel_hook.py", command)
        self.assertRegex(command, r"keel_hook\.py\"?\s+subagent_stop\b")

    def test_the_registration_carries_no_matcher(self) -> None:
        """SubagentStop names no tool, so a tool matcher would filter it out."""
        self.assertNotIn("matcher", self._document()["hooks"]["SubagentStop"][0])

    def test_the_observer_is_async_and_cannot_delay_a_returning_agent(self) -> None:
        hook = self._document()["hooks"]["SubagentStop"][0]["hooks"][0]
        self.assertTrue(hook.get("async"), hook)
        self.assertEqual(hook["shell"], "bash")
        self.assertEqual(hook["type"], "command")
        self.assertNotIn("\n", hook["command"])

    def test_the_entry_lives_in_the_generator_table(self) -> None:
        """R13: hooks.json is generated. A hand-edit would not survive."""
        rows = [e for e in keel_gen_hooks.ENTRIES if e.event == "SubagentStop"]
        self.assertEqual(len(rows), 1, keel_gen_hooks.ENTRIES)
        self.assertEqual(rows[0].subcommand, "subagent_stop")
        self.assertTrue(rows[0].is_async)
        self.assertEqual(keel_gen_hooks.verify(), [])

    def test_the_launcher_can_route_it(self) -> None:
        self.assertIn("subagent_stop", keel_hook.SUBCOMMANDS)
        self.assertTrue(callable(keel_hook.SUBCOMMANDS["subagent_stop"]))

    def test_every_registered_subcommand_has_a_handler(self) -> None:
        registered = {entry.subcommand for entry in keel_gen_hooks.ENTRIES}
        self.assertTrue(registered.issubset(set(keel_hook.SUBCOMMANDS)), registered)


class TestTheEventReachesTheAuditLog(unittest.TestCase):
    """Measured on the bytes on disk, never inferred from the registration."""

    def test_one_stop_writes_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            self.assertEqual(stops_in(project), [], "premise: the log starts empty")

            result = run_hook(
                "subagent_stop", stop_payload(project, session), project, root
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"", "an observer emits nothing")
            stops = stops_in(project)
            self.assertEqual(len(stops), 1, audit_lines(project))
            record = stops[0]
            self.assertEqual(record["event"], STOP_EVENT)
            self.assertEqual(record["session"], session)
            self.assertEqual(record["agent_id"], AGENT_ID)
            self.assertEqual(record["agent_type"], AGENT_TYPE)
            self.assertIn("v", record, "every audit line carries its schema version")
            self.assertIn("ts", record)

    def test_stops_are_not_one_per_delegation(self) -> None:
        """A backgrounded agent stops more than once; each stop is a line.

        The measurement behind this case: 48 stops against 26 launches in one
        recorded session. A handler that de-duplicated - by agent, by session,
        or by "we already saw one" - would silently drop most of the record,
        so three stops naming ONE agent must leave three lines.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            for _ in range(3):
                result = run_hook(
                    "subagent_stop", stop_payload(project, session), project, root
                )
                self.assertEqual(result.returncode, 0, result.stderr)
            stops = stops_in(project)
            self.assertEqual(len(stops), 3, audit_lines(project))
            self.assertEqual({s["agent_id"] for s in stops}, {AGENT_ID})

    def test_a_stop_for_a_delegation_never_launched_is_recorded(self) -> None:
        """Recorded, not dropped - and no launch is invented to receive it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            result = run_hook(
                "subagent_stop",
                stop_payload(project, uuid.uuid4().hex, agent_type="never-launched"),
                project,
                root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            records = audit_records(project)
            self.assertEqual(len(records), 1, records)
            self.assertEqual(records[0]["event"], STOP_EVENT)
            self.assertEqual(
                [r for r in records if str(r.get("event", "")).startswith("handoff")],
                [],
                "no hand-off may be fabricated to pair a stop with",
            )
            self.assertNotIn("tool_use_id", records[0], "no pairing key is invented")

    def test_absent_and_blank_identity_fields_are_recorded_as_null(self) -> None:
        """A blank ``agent_type`` is common in the field, and is not a type."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            payload = stop_payload(project, uuid.uuid4().hex, agent_type="")
            payload.pop("agent_id")
            result = run_hook("subagent_stop", payload, project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            record = stops_in(project)[0]
            self.assertIsNone(record["agent_type"])
            self.assertIsNone(record["agent_id"])

    def test_an_unadopted_project_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "bare"
            project.mkdir()
            result = run_hook(
                "subagent_stop", stop_payload(project, uuid.uuid4().hex), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertFalse(
                (project / ".keel").exists(), "an unadopted project gains no .keel/"
            )

    def test_garbage_on_stdin_fails_open_and_manufactures_nothing(self) -> None:
        """A broken pipe is not a finished delegation.

        Unparseable stdin reaches the subcommand as ``{}`` by the launcher's
        own declared design, so the shape that must not happen is an
        unattributable stop line appended to an append-only record.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            result = run_hook("subagent_stop", b"not json at all {{{", project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(stops_in(project), [])
            self.assertIn(b"names no session", result.stderr, "and never silently")

    def test_a_payload_with_no_session_is_refused_out_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            payload = stop_payload(project, "unused")
            payload.pop("session_id")
            result = run_hook("subagent_stop", payload, project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(audit_lines(project), [], "no unattributable line")
            self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
            self.assertIn(b"subagent_stop not recorded", result.stderr)

    def test_the_write_goes_through_the_redaction_chokepoint(self) -> None:
        """No second writer: the value is screened before it becomes bytes.

        A home-SHAPED path in a payload field is replaced at
        ``keel_events._append_jsonl``, which every keel writer passes through.
        The handler itself does nothing to this value - which is the point:
        proving the screen ran proves the line took the one guarded route
        rather than a new one (convention 5).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            payload = stop_payload(
                project,
                uuid.uuid4().hex,
                agent_type="D:\\Backup\\Users\\someone-else\\agent",
            )
            result = run_hook("subagent_stop", payload, project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            recorded = stops_in(project)[0]["agent_type"]
            self.assertNotIn("someone-else", recorded, recorded)
            self.assertIn("[home-path]", recorded, recorded)


class TestTheExistingConsumerReceivesIt(unittest.TestCase):
    """``keel_stop.py``'s branch is the consumer; nothing else may be one."""

    def _delegation(self, project: Path, session: str, agent_type: str) -> None:
        """A background launch: a start, and a return moments later.

        Under ``BG_LAUNCH_MS`` that pair is a launch acknowledgment rather than
        a completion, so the hand-off stays open - which is the state a real
        finish event is supposed to resolve, and the state the viewer has been
        misreading for want of one.

        THE RETURN CARRIES THE JOIN KEY AND THE LAUNCH DOES NOT, because that
        is the shape ``keel_capture.handoff_record`` actually writes: the id
        comes back in the launch tool's RESULT, which reaches keel at
        PostToolUse, so at PreToolUse there is nothing to record and a null is
        recorded instead. A fixture that put the id on both halves would prove
        the pairing works against a record shape no hook produces.
        """
        # Recent on purpose, and in the past on purpose. ``keel_stop`` presumes
        # a background hand-off finished once its own activity has been quiet
        # for ``LIVENESS_MS``, so a fixture dated last month reads closed
        # before any stop arrives and would prove nothing; a fixture dated in
        # the future sorts after the stop and would prove nothing either.
        start = utc_stamp(seconds_ago=120)
        end = utc_stamp(seconds_ago=119)
        for event, ts in (("handoff_start", start), ("handoff_end", end)):
            self._append(
                project,
                {
                    "v": 1,
                    "ts": ts,
                    "event": event,
                    "session": session,
                    "tool_use_id": "toolu_01",
                    "agent_id": AGENT_ID if event == "handoff_end" else None,
                    "subagent_type": agent_type,
                    "description": "a delegation",
                },
            )

    def _append(self, project: Path, record: dict[str, Any]) -> None:
        path = project.joinpath(*AUDIT_RELPATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record) + "\n")

    def test_the_produced_line_closes_an_open_background_handoff(self) -> None:
        """Reachability, not the pairing rule.

        What is asserted is that the line the SUBSCRIPTION produces arrives at
        the branch that was already waiting for it: with no stop on record the
        hand-off reads open, and after the hook runs it does not. WHICH
        delegation a stop belongs to is a separate question, answered by
        ``TestTheJoinKeyIsExact`` below; this case only needs the record shape
        that question settled on, so the stop and the launch's own return name
        the same agent id.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            self._delegation(project, session, AGENT_TYPE)
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "premise: a background launch with no finish event reads open",
            )

            result = run_hook(
                "subagent_stop", stop_payload(project, session), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "the produced line never reached keel_stop.py's subagent_stop branch",
            )

    def test_a_stop_for_another_session_leaves_this_one_open(self) -> None:
        """Recorded, never paired across sessions - and never dropped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            self._delegation(project, session, AGENT_TYPE)

            other = uuid.uuid4().hex
            result = run_hook(
                "subagent_stop", stop_payload(project, other), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(len(stops_in(project)), 1, "the stop is still recorded")
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "a stop from another session may not close this session's hand-off",
            )

    def test_the_named_consumers_are_the_only_ones_in_the_repository(self) -> None:
        """Three named implementations, and no fourth - repository-wide.

        THIS ASSERTION USED TO GLOB ``hooks/*.py`` ONLY, and that is why it
        passed while ``scripts/keel_attest.py`` - a full second reading of the
        same event, outside the glob - disagreed with ``hooks/keel_stop.py``
        about whether a blank agent type closes a hand-off. A guard that can
        only see one directory cannot see drift between two.

        T103 ADDED THE THIRD, AND IT WAS ADMITTED AS PROVISIONAL: its
        ``_match_finish_events`` was a THIRD implementation of matching one
        stop to one delegation, beside ``hooks/keel_stop.py``'s closing loop
        and ``scripts/keel_attest.py``'s ``resolve_handoffs``, and this
        docstring required it to be RE-EXAMINED once T102 landed a real join
        key rather than left standing because it once passed.

        THE RE-EXAMINATION, DONE (T102). All three matching loops are gone.
        ``hooks/keel_stop.match_stops_to_launches`` is the one implementation;
        the report and the viewer CALL it. So the claim this test makes has
        got stronger, and it is now made in two parts rather than one:

        1. THE SET IS UNCHANGED AND STILL ARGUED FOR. Three files branch on
           this event, legitimately, because the gate must decide, the report
           must describe and the canvas must render. A FOURTH has to earn this
           paragraph rather than a one-line dict edit.
        2. THE THREE MUST IMPORT THE MATCHER, NOT REIMPLEMENT IT - asserted by
           ``test_the_named_consumers_share_one_matching_implementation``
           below on OBJECT IDENTITY, which a copied algorithm cannot fake. The
           provisional entry's whole justification was that no shared join
           existed yet to call; it exists, so the concession is spent and the
           condition replaces it. A consumer that regrew its own loop fails
           that test even while passing this one.

        Scope note kept from the earlier form, because it still applies: a
        text scan is a tripwire for the copy-and-diverge that actually
        happened here, not a proof of uniqueness. A consumer spelled
        ``in (...)`` would slip past it, which is exactly why the shared-object
        assertion carries the real weight and this one only has to be cheap
        and honest.

        Scope of the scan, stated so nobody has to guess why a file is absent:
        every ``*.py`` tracked in the repository except ``tests/`` (a test
        naming the value is the point of a test), and it looks for an equality
        comparison. ``keel_dashboard.COUNTED_EVENTS`` names the string without
        branching on it - it counts every event kind alike - and is correctly
        not caught.

        THE FILE LIST COMES FROM ``git ls-files``, NOT FROM WALKING THE TREE,
        and that is the whole difference between a guard and a nuisance. A walk
        counts whatever happens to sit on disk: it missed a ``git worktree``
        under ``.claude/`` (gitignored, so absent from a CI checkout) and
        reported the SAME two implementations four times - green on CI, red on
        every developer machine that uses worktrees, which is the shape people
        learn to ignore. A walk is wrong in the other direction too: an
        untracked scratch copy would fail the scan, and a tracked file is
        invisible to CI until it is committed. The tracked set is the only
        enumeration on which this machine and the harness agree BY
        CONSTRUCTION, so the scan asks git. It follows that no ``.git`` or
        ``__pycache__`` exclusion is needed here - git tracks neither.

        The enumeration itself fails loudly. No git, a non-zero exit, an empty
        listing or a tracked path missing from the working tree all FAIL this
        test, because a scan that cannot enumerate has learned nothing and an
        empty result is not a clean bill of health.
        """
        try:
            listing = subprocess.run(
                ["git", "ls-files", "--cached", "--", "*.py"],
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        except OSError as exc:  # git absent, or not executable
            self.fail(f"cannot enumerate the tracked set - git would not run: {exc}")
        self.assertEqual(
            listing.returncode,
            0,
            "git ls-files failed, so the scan enumerated nothing: "
            + (listing.stderr or "").strip(),
        )
        tracked = [
            line.strip().replace("\\", "/")
            for line in listing.stdout.splitlines()
            if line.strip()
        ]
        self.assertTrue(
            tracked,
            "git tracks no *.py at all - the scan cannot be complete, and an "
            "empty enumeration is a failure rather than a pass",
        )
        for named in (
            "hooks/keel_stop.py", "scripts/keel_attest.py", "scripts/keel_dashboard.py",
        ):
            self.assertIn(
                named,
                tracked,
                "the enumeration did not reach a named implementation, so any "
                "verdict below would be about the wrong file set",
            )

        pattern = re.compile(r"==\s*\"" + STOP_EVENT + r"\"")
        found: dict[str, int] = {}
        for relative in sorted(tracked):
            # dist/ is the tracked distribution bundle - a GENERATED mirror of
            # the sources scanned here, pinned byte-equal to generation by the
            # distribution check (T614). Its copy of a named consumer is the
            # same consumer shipped, not a fourth reader; counting it would
            # make every legitimate consumer appear twice the moment it ships.
            if relative.split("/")[0] in ("tests", "dist"):
                continue
            path = REPO_ROOT / relative
            self.assertTrue(
                path.is_file(),
                f"git tracks {relative} but it is absent from the working "
                "tree, so the scan is incomplete",
            )
            count = len(pattern.findall(path.read_text(encoding="utf-8")))
            if count:
                found[relative] = count
        self.assertEqual(
            found,
            {
                "hooks/keel_stop.py": 1,
                "scripts/keel_attest.py": 1,
                "scripts/keel_dashboard.py": 1,
                # The VENDORED predecessor page (owner-adopted 2026-08-12,
                # .keel/decisions/2026-08-12-additive-merge-ask-before-deleting.md)
                # pairs stops to launches with its own client-side rules. It
                # is named here as what it is - adopted byte-identical UI,
                # not a matcher that grew in keel's code - and it does NOT
                # import the shared implementation, deliberately: rewriting
                # vendored logic to keel's is a deletion the standing
                # decision requires asking about first.
                "scripts/keel_orchestration_dashboard.py": 1,
            },
            "a fourth reader of the delegation-finish event appeared, or a named "
            "one stopped reading it",
        )

    def test_the_named_consumers_share_one_matching_implementation(self) -> None:
        """The condition that replaced T103's provisional entry (T102).

        Three readers may branch on this event; ONE may decide which launch a
        stop belongs to. Identity is what is asserted, not behaviour: two
        copies of an algorithm agree until the day one is edited, and that day
        is what SF1 was. A consumer that reimplemented the match - or reverted
        to matching on agent TYPE, which is what each of them used to do -
        fails here even if its answers happen to agree today.

        The scan above cannot see this: a local loop still contains exactly
        one ``== "subagent_stop"``. That is the division of labour between the
        two cases, and the reason both exist.
        """
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import keel_dashboard  # noqa: PLC0415 - imported here, not at module load

        for module in (keel_attest, keel_dashboard):
            with self.subTest(module=module.__name__):
                self.assertIs(
                    module.match_stops_to_launches,
                    keel_stop.match_stops_to_launches,
                    "this consumer does not call the shared matcher",
                )
                self.assertIs(
                    module.launch_agent_id,
                    keel_stop.launch_agent_id,
                    "this consumer resolves a delegation's id its own way",
                )
                self.assertFalse(
                    hasattr(module, "same_agent_type"),
                    "an import of the TYPE predicate means a local matching "
                    "loop has regrown: nothing matches a stop by type any more",
                )


class TestAnAbsentAgentTypeMatchesNothing(unittest.TestCase):
    """The blank-key rule, asserted on both implementations of it.

    ``None != None`` is False. The gate paired a stop to a launch with a bare
    ``!=`` on the agent type, so a stop carrying no type MATCHED a launch
    carrying no type and closed it - a delegation nothing on record spoke
    about, closed in the module that decides whether a turn may end.

    Both blanks are the SHAPE THE PRODUCERS ACTUALLY WRITE, not a shape
    invented to fail: ``keel_capture._text`` (``hooks/keel_capture.py:217``)
    records an absent ``subagent_type`` as null, and ``keel_hook._payload_text``
    does the same for ``agent_type`` on the stop side. Blank types are not
    hypothetical on that stop side - 273 of 440 real stops carry one.

    Removing the guard - restoring ``!=``, or dropping the ``bool(left)`` from
    ``keel_stop.same_agent_type`` - fails the first two cases here.
    """

    def _write(self, project: Path, records: list[dict[str, Any]]) -> None:
        path = project.joinpath(*AUDIT_RELPATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def _untyped_launch(self, project: Path, session: str) -> None:
        """A background launch that names no agent type. Recent, as above."""
        self._write(
            project,
            [
                {
                    "v": 1,
                    "ts": utc_stamp(seconds_ago=120 - offset),
                    "event": event,
                    "session": session,
                    "tool_use_id": "toolu_blank",
                    "subagent_type": None,
                    "description": "a delegation that named no type",
                }
                for offset, event in ((0, "handoff_start"), (1, "handoff_end"))
            ],
        )

    def test_a_blank_stop_does_not_close_a_blank_launch(self) -> None:
        """The false match, end to end through the real producer."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            self._untyped_launch(project, session)
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "premise: a background launch with no finish event reads open",
            )

            result = run_hook(
                "subagent_stop",
                stop_payload(project, session, agent_type=""),
                project,
                root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            stops = stops_in(project)
            self.assertEqual(len(stops), 1, "recorded, never dropped")
            self.assertIsNone(stops[0]["agent_type"], "premise: the stop is blank")

            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "a stop naming no agent closed a hand-off naming no agent: two "
                "absent values were read as one identity",
            )

    def test_the_gate_and_the_report_reach_the_same_answer(self) -> None:
        """SF1 was a disagreement, so agreement is what is asserted.

        The same records, put to the gate and to ``keel attest``: both must
        say the hand-off is still open and neither may attach the stop. They
        agree because they run the same function, which is checked here too -
        a shared idea drifts, a shared object cannot.

        The records are dated MINUTES ago, not last week, so that what is
        compared is the pairing rule alone: the gate additionally presumes a
        quiet hand-off finished after ``LIVENESS_MS`` and the report never
        does, a difference ``resolve_handoffs``' docstring declares, and an
        old fixture would measure that instead of this.
        """
        self.assertIs(
            keel_attest.match_stops_to_launches, keel_stop.match_stops_to_launches
        )

        start = {
            "v": 1, "ts": utc_stamp(seconds_ago=120), "event": "handoff_start",
            "session": "s1", "tool_use_id": "toolu_blank", "subagent_type": None,
            "description": "d",
        }
        end = dict(start, ts=utc_stamp(seconds_ago=119), event="handoff_end")
        stop = {
            "v": 1, "ts": utc_stamp(seconds_ago=60), "event": STOP_EVENT,
            "session": "s1", "agent_id": AGENT_ID, "agent_type": None,
        }

        unassigned = keel_attest.resolve_handoffs([start], [end], [stop])
        self.assertEqual(unassigned, [stop], "attest attached an unattributable stop")
        self.assertTrue(start["_open"], start["_closure"])

        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project,
                [{k: v for k, v in record.items() if not k.startswith("_")}
                 for record in (start, end, stop)],
            )
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, "s1"),
                "the gate closed what the report left open",
            )

    def test_the_predicate_says_which_pairs_are_a_match(self) -> None:
        """Blank is absent, empty, whitespace, or not a string at all.

        The three blank spellings are the same three
        ``tests/test_keel_attention.py`` already pins for main-session work,
        because this is that rule made uniform rather than a new one.
        """
        for left, right, expected in (
            (None, None, False),
            ("", "", False),
            ("   ", "", False),
            (None, "", False),
            ("keel:executor-deep", "", False),
            ("", "keel:executor-deep", False),
            (None, "keel:executor-deep", False),
            (1, 1, False),
            ("keel:executor-deep", "keel:reviewer", False),
            ("keel:executor-deep", "keel:executor-deep", True),
            (" keel:executor-deep ", "keel:executor-deep", True),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(keel_stop.same_agent_type(left, right), expected)

    def test_a_named_stop_still_closes_its_named_launch(self) -> None:
        """The guard refuses absences, not the rule the gate is here to run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            self._write(
                project,
                [
                    {
                        "v": 1,
                        "ts": utc_stamp(seconds_ago=120 - offset),
                        "event": event,
                        "session": session,
                        "tool_use_id": "toolu_01",
                        "agent_id": AGENT_ID if event == "handoff_end" else None,
                        "subagent_type": AGENT_TYPE,
                        "description": "a delegation",
                    }
                    for offset, event in ((0, "handoff_start"), (1, "handoff_end"))
                ],
            )
            result = run_hook(
                "subagent_stop", stop_payload(project, session), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "a named stop must still close the launch of that name",
            )


class TestTheJoinKeyIsExact(unittest.TestCase):
    """T102: a stop is matched to the launch it belongs to, or to nothing.

    THE QUESTION THIS FILE PREVIOUSLY LEFT OPEN. The stop payload has always
    carried ``agent_id``; launch lines carried ``tool_use_id``; the two sets
    did not overlap, so the gate attributed a stop by agent type and time
    order - a guess whenever two agents of a kind are running at once, and a
    guess between two absences whenever the type was blank.

    THE KEY WAS AVAILABLE AND IT WAS MEASURED RATHER THAN ASSUMED: every
    ``Task`` result recorded in this project carries ``agentId``, in both
    result shapes - the ``async_launched`` acknowledgment of a backgrounded
    delegation and the completed return of a foreground one. It arrives in the
    tool's RESULT, so it reaches keel at PostToolUse and lands on
    ``handoff_end``; ``handoff_start`` records a null, because at PreToolUse
    there is nothing yet to record.

    BOTH DIRECTIONS ARE ASSERTED HERE, and the second is the one that matters:
    exact pairing succeeding on equal ids proves the key works, but a pairing
    that cannot be made exact REFUSING to pair is the property the whole task
    exists for. Absent is reported as absent; it is never approximated.
    """

    def _write(self, project: Path, records: list[dict[str, Any]]) -> None:
        path = project.joinpath(*AUDIT_RELPATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def _launch(
        self,
        session: str,
        tool_use_id: str,
        agent_id: str | None,
        agent_type: str | None = AGENT_TYPE,
        seconds_ago: int = 120,
        description: str = "a delegation",
    ) -> list[dict[str, Any]]:
        """One backgrounded delegation, in the shape the capture hook writes.

        Start, then a return one second later - under ``BG_LAUNCH_MS``, so the
        pair is a launch acknowledgment and the hand-off is OPEN. The id is on
        the return only, which is where the launch tool puts it.
        """
        return [
            {
                "v": 1,
                "ts": utc_stamp(seconds_ago=seconds_ago - offset),
                "event": event,
                "session": session,
                "tool_use_id": tool_use_id,
                "agent_id": agent_id if event == "handoff_end" else None,
                "subagent_type": agent_type,
                "description": description,
            }
            for offset, event in ((0, "handoff_start"), (1, "handoff_end"))
        ]

    def _stop(
        self, session: str, agent_id: str | None, agent_type: str | None = AGENT_TYPE
    ) -> dict[str, Any]:
        return {
            "v": 1,
            "ts": utc_stamp(seconds_ago=30),
            "event": STOP_EVENT,
            "session": session,
            "agent_id": agent_id,
            "agent_type": agent_type,
        }

    # ------------------------------------------------ direction 1: it pairs

    def test_the_predicate_says_which_ids_are_a_match(self) -> None:
        """Exactly the blank rule ``same_agent_type`` carries, on the id."""
        for left, right, expected in (
            (None, None, False),
            ("", "", False),
            ("   ", "", False),
            (None, "", False),
            (AGENT_ID, "", False),
            ("", AGENT_ID, False),
            (None, AGENT_ID, False),
            (1, 1, False),
            (AGENT_ID, "a0000000000000000", False),
            (AGENT_ID, AGENT_ID, True),
            (f" {AGENT_ID} ", AGENT_ID, True),
        ):
            with self.subTest(left=left, right=right):
                self.assertIs(keel_stop.same_agent_id(left, right), expected)

    def test_the_chain_from_a_launch_to_its_id_runs_through_its_return(self) -> None:
        """The launch half names no agent; the delegation still has an id."""
        start, end = self._launch("s", "toolu_01", AGENT_ID)
        self.assertIsNone(start["agent_id"], "premise: the launch half is null")
        self.assertIsNone(keel_stop.launch_agent_id(start))
        self.assertEqual(keel_stop.launch_agent_id(start, end), AGENT_ID)
        # A harness that came to expose it at launch time is read too.
        self.assertEqual(
            keel_stop.launch_agent_id(dict(start, agent_id=AGENT_ID)), AGENT_ID
        )

    def test_two_concurrent_same_type_delegations_are_told_apart(self) -> None:
        """THE CASE A TYPE CANNOT ANSWER, asserted on the attribution itself.

        Two delegations of the SAME type are open at once. A stop naming the
        FIRST must close the first - not the most recently launched one, which
        is what time order picked and what got it wrong. ``session_has_open_
        handoff`` answers in counts, so it cannot see a misattribution here;
        the matcher is asked directly, and the count is checked beside it.
        """
        first, second = "a" + "1" * 16, "a" + "2" * 16
        matched = keel_stop.match_stops_to_launches(
            [first, second], [self._stop("s", first)]
        )
        self.assertEqual(list(matched), [0], "the stop closed the wrong delegation")
        self.assertIs(matched[0]["agent_id"], first)

        matched = keel_stop.match_stops_to_launches(
            [first, second], [self._stop("s", second)]
        )
        self.assertEqual(list(matched), [1], "the stop closed the wrong delegation")

    def test_the_gate_holds_one_of_two_same_type_delegations_open(self) -> None:
        """The same case, end to end, through the audit log and the gate."""
        first, second = "a" + "1" * 16, "a" + "2" * 16
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            session = uuid.uuid4().hex
            self._write(
                project,
                self._launch(session, "toolu_a", first, seconds_ago=120)
                + self._launch(session, "toolu_b", second, seconds_ago=100)
                + [self._stop(session, second)],
            )
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "one of two same-type delegations stopped; the other is still "
                "running and the turn may not be accounted for without it",
            )
            self._write(project, [self._stop(session, first)])
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "both delegations stopped by name; nothing is open",
            )

    def test_a_repeat_stop_for_one_agent_closes_only_that_agent(self) -> None:
        """A backgrounded agent stops more than once. Twice is not two."""
        first, second = "a" + "1" * 16, "a" + "2" * 16
        matched = keel_stop.match_stops_to_launches(
            [first, second],
            [self._stop("s", first), self._stop("s", first), self._stop("s", first)],
        )
        self.assertEqual(list(matched), [0], "a repeat stop closed a second launch")

    def test_the_produced_stop_closes_the_launch_the_capture_hook_recorded(
        self,
    ) -> None:
        """END TO END THROUGH BOTH REAL PRODUCERS, no hand-written launch line.

        The capture hook is run twice - PreToolUse then PostToolUse, with the
        launch tool's own result attached to the second - and then the stop
        hook is run with the id that result carried. Nothing here writes an
        audit line itself, so what is asserted is that the two hooks agree
        about the key without a test having arranged for them to.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            launched = task_payloads(project, session, AGENT_ID)
            for payload in launched:
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)

            records = audit_records(project)
            opened = [r for r in records if r["event"] == "handoff_start"]
            closed = [r for r in records if r["event"] == "handoff_end"]
            self.assertEqual(len(opened), 1, records)
            self.assertIsNone(opened[0]["agent_id"], "the launch half names none")
            self.assertEqual(closed[0]["agent_id"], AGENT_ID, "the return half does")

            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "premise: a background launch with no stop reads open",
            )
            result = run_hook(
                "subagent_stop", stop_payload(project, session), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "the stop named the id the launch's own return recorded, and "
                "the gate still failed to join them",
            )

    def test_the_key_survives_the_redaction_chokepoint_identically(self) -> None:
        """Both sides are screened by the same function, so the join holds.

        Every audit line - the capture hook's and the stop hook's alike -
        passes through ``keel_events._append_jsonl``'s call to
        ``redact_mapping``. Redaction is a substitution, so it is the same for
        the same input: if it ever did rewrite an id, it would rewrite BOTH
        recorded copies the same way and the join would survive. That is
        asserted rather than argued, by comparing the bytes the two
        independent hooks wrote.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            session = uuid.uuid4().hex
            for payload in task_payloads(project, session, AGENT_ID):
                run_hook("capture", payload, project, root)
            run_hook("subagent_stop", stop_payload(project, session), project, root)

            records = audit_records(project)
            from_launch = [
                r["agent_id"] for r in records if r["event"] == "handoff_end"
            ]
            from_stop = [r["agent_id"] for r in records if r["event"] == STOP_EVENT]
            self.assertEqual(from_launch, from_stop, "the two writers disagree")

            # And no part of the tool's result rode along with the id: the
            # value is extracted, never the text it was extracted from.
            written = "\n".join(audit_lines(project))
            self.assertNotIn("Async agent launched successfully", written)
            self.assertNotIn("internal ID", written)

    # ------------------------------------------- direction 2: it refuses to

    def _stays_open(self, records: list[dict[str, Any]], why: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            session = records[0]["session"]
            self._write(project, records)
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session), why
            )

    def test_a_stop_naming_no_agent_closes_nothing(self) -> None:
        """The stop side's blank. 273 of 440 real stops carry a blank type;
        an id can be blank too, and a blank names nothing."""
        session = uuid.uuid4().hex
        self._stays_open(
            self._launch(session, "toolu_01", AGENT_ID)
            + [self._stop(session, None, agent_type=None)],
            "a stop naming no agent closed a delegation it never identified",
        )

    def test_a_launch_naming_no_agent_is_not_closed_by_a_stop(self) -> None:
        """The launch side's blank - the shape every line written before this
        key existed still has, and the shape a foreground return that has not
        landed yet leaves behind."""
        session = uuid.uuid4().hex
        self._stays_open(
            self._launch(session, "toolu_01", None)
            + [self._stop(session, AGENT_ID)],
            "a stop was attributed to a launch that names no agent at all",
        )

    def test_two_blank_ids_are_not_one_identity(self) -> None:
        """``None == None`` is True, and that is exactly the false match."""
        session = uuid.uuid4().hex
        self._stays_open(
            self._launch(session, "toolu_01", None)
            + [self._stop(session, None, agent_type=None)],
            "two absent ids were read as one identity",
        )

    def test_a_stop_for_another_agent_leaves_this_launch_open(self) -> None:
        """Same type, same session, same minute - and a different agent."""
        session = uuid.uuid4().hex
        self._stays_open(
            self._launch(session, "toolu_01", "a" + "1" * 16)
            + [self._stop(session, "a" + "2" * 16)],
            "a stop closed a delegation whose id it does not name",
        )

    def test_the_type_and_time_fallback_is_gone(self) -> None:
        """The rule the criteria rule out, asserted as ABSENT rather than
        described as removed.

        Both records name the same agent TYPE and the stop is later than the
        launch, which is everything the old rule needed. Neither carries an
        id, so nothing pairs them, and the delegation stays open.
        """
        session = uuid.uuid4().hex
        records = self._launch(session, "toolu_01", None, agent_type=AGENT_TYPE)
        records.append(self._stop(session, None, agent_type=AGENT_TYPE))
        self.assertEqual(
            records[0]["subagent_type"], records[-1]["agent_type"],
            "premise: the type-and-time rule would have matched these",
        )
        self._stays_open(
            records, "a stop was paired by agent type and time order"
        )

    # ------------------- direction 2, at the second site: launch and RETURN

    def test_a_return_naming_no_tool_call_closes_no_launch(self) -> None:
        """THE FIFO BLANK-PAIR SITE, closed.

        The pairing key for a launch and its RETURN was ``tool_use_id`` where
        present and ``(subagent_type, description)`` otherwise - and that
        second key pairs two records that name NEITHER, which is the same
        false match a blank agent type makes, reached by a different road.
        Here two launches and one return all name no tool call and no type;
        the return arrives well after the launches, so under the old key it
        was a genuine foreground close and it closed the FIRST launch, chosen
        by arrival order alone. It now closes neither.
        """
        session = uuid.uuid4().hex
        blank: dict[str, Any] = {
            "session": session, "tool_use_id": None,
            "subagent_type": None, "description": None,
        }
        records = [
            dict(blank, v=1, ts=utc_stamp(seconds_ago=200), event="handoff_start"),
            dict(blank, v=1, ts=utc_stamp(seconds_ago=190), event="handoff_start"),
            dict(blank, v=1, ts=utc_stamp(seconds_ago=60), event="handoff_end"),
        ]
        self._stays_open(
            records,
            "a return naming no tool call was paired with a launch naming "
            "none either: two absences were read as one delegation",
        )

    def test_a_launch_with_no_return_is_still_closed_by_elapsed_quiet(self) -> None:
        """THE THIRD WAY, and why refusing to guess leaves nothing open forever.

        A launch this pass could not pair with a RETURN - the shape a dropped
        or unattributable ``handoff_end`` leaves behind - is not closed by any
        exact key. It is not therefore immortal: the activity-quiet timeout
        reaches every launch on the open list, which is what makes it safe for
        the two keys above to refuse a guess. That property was briefly
        carried by a per-launch flag; the flag was always True at every site
        that set it, so it recorded no choice and was removed. This case pins
        the behaviour it claimed to control, so removing it cannot go
        unnoticed.
        """
        session = uuid.uuid4().hex
        old = int(keel_stop.LIVENESS_MS / 1000) + 60
        launch = {
            "v": 1, "ts": utc_stamp(seconds_ago=old), "event": "handoff_start",
            "session": session, "tool_use_id": "toolu_lonely", "agent_id": None,
            "subagent_type": AGENT_TYPE, "description": "no return ever landed",
        }
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(project, [launch])
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "a launch with no return and no stop stayed open past the "
                "activity-quiet timeout, so nothing can ever close it",
            )
        # Recent, the same shape: quiet has not elapsed, so it IS still open.
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(project, [dict(launch, ts=utc_stamp(seconds_ago=30))])
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "the timeout closed a launch that has not been quiet for it",
            )

    def test_a_named_return_still_closes_the_launch_it_names(self) -> None:
        """The guard refuses absences, not the pairing the gate runs on."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project,
                [
                    {
                        "v": 1,
                        "ts": utc_stamp(seconds_ago=seconds),
                        "event": event,
                        "session": session,
                        "tool_use_id": "toolu_fg",
                        "agent_id": None,
                        "subagent_type": AGENT_TYPE,
                        "description": "a foreground delegation",
                    }
                    for seconds, event in ((200, "handoff_start"), (60, "handoff_end"))
                ],
            )
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "a foreground pair sharing a tool_use_id must still close",
            )


class TestTheBackgroundFieldIsReadBeforeTheClock(unittest.TestCase):
    """T348: ``handoff_end.background`` decides ack-vs-completion, not the
    elapsed-time guess alone.

    THE DEFECT, confirmed by replaying this gate's own logic against this
    repository's real audit log (2026-08-27): of 24 close halves this
    project's own log marks ``background: true``, 5 arrived 5s-19s after
    their launch - over ``BG_LAUNCH_MS`` - and the elapsed-time-only rule
    misread every one of them as a finished foreground return, closing a
    launch whose agent was demonstrably still working.

    THE FIX, pinned in both directions here: the close half's own
    ``background`` field (``keel_stop.HANDOFF_BACKGROUND_KEY``, written by
    ``hooks/keel_capture.py`` from the launch tool's own result ``status``,
    T323) is read FIRST and trusted whatever the elapsed time - ``True``
    keeps a launch open no matter how slow the acknowledgment arrived,
    ``False`` closes one no matter how fast it returned. The elapsed-time
    guess (``BG_LAUNCH_MS``) survives only as the fallback for a
    ``handoff_end`` that carries neither value - proven unchanged by
    ``TestTheExistingConsumerReceivesIt`` (a fast, field-less pair stays
    open) and ``TestTheJoinKeyIsExact.test_a_named_return_still_closes_the_launch_it_names``
    (a slow, field-less pair still closes), neither of which this task
    touches.

    THE INTEGRITY ARGUMENT, pinned last: a launch this rule now keeps open
    for longer is not open forever - ``test_the_liveness_sweep_still_reaps_it``
    proves the existing activity-quiet timeout still reaches it, which is the
    only thing standing between "a background ack keeps [~] alive" and "a
    dead agent's ack keeps [~] alive forever".
    """

    def _write(self, project: Path, records: list[dict[str, Any]]) -> None:
        path = project.joinpath(*AUDIT_RELPATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def _slow_background_ack(
        self, session: str, tool_use_id: str, agent_id: str, *, gap_seconds: int = 19,
        launch_seconds_ago: int = 300,
    ) -> list[dict[str, Any]]:
        """A REAL shape this project's own log carries: a launch, and a
        background acknowledgment that took longer than ``BG_LAUNCH_MS`` to
        arrive - measured at 6s, 7s and 19s in this repository's own log."""
        return [
            {
                "v": 1,
                "ts": utc_stamp(seconds_ago=launch_seconds_ago),
                "event": "handoff_start",
                "session": session,
                "tool_use_id": tool_use_id,
                "agent_id": None,
                "subagent_type": AGENT_TYPE,
                "description": "a delegation",
            },
            {
                "v": 1,
                "ts": utc_stamp(seconds_ago=launch_seconds_ago - gap_seconds),
                "event": "handoff_end",
                "session": session,
                "tool_use_id": tool_use_id,
                "agent_id": agent_id,
                "subagent_type": AGENT_TYPE,
                "description": "a delegation",
                "background": True,
            },
        ]

    def test_a_slow_background_ack_with_no_stop_stays_open(self) -> None:
        """THE DEFECT, reproduced: before T348 this exact pair - a 19s gap,
        over ``BG_LAUNCH_MS`` - read as a finished foreground return and this
        assertion failed."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project, self._slow_background_ack(session, "toolu_slow_1", AGENT_ID)
            )
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "a background: true close half was misread as a finished "
                "foreground return because it arrived after BG_LAUNCH_MS",
            )

    def test_the_same_pair_closes_once_a_subagent_stop_names_it(self) -> None:
        """A finished agent must never permit [~], whatever the recorded
        background field said about how the launch acknowledged."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project, self._slow_background_ack(session, "toolu_slow_2", AGENT_ID)
            )
            self._write(project, [self._stop_line(session, AGENT_ID)])
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "a subagent_stop naming the agent id must still close the "
                "launch, even though its ack was read as background",
            )

    def test_an_explicit_false_closes_regardless_of_a_fast_gap(self) -> None:
        """The guard cuts both ways: ``background: false`` (a genuine
        completed return, per the launch result's own ``status``) is not kept
        open by a fast gap either - a technicality must not override a
        recorded fact any more than elapsed time may."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project,
                [
                    {
                        "v": 1,
                        "ts": utc_stamp(seconds_ago=seconds),
                        "event": event,
                        "session": session,
                        "tool_use_id": "toolu_fg_fast",
                        "agent_id": AGENT_ID if event == "handoff_end" else None,
                        "subagent_type": AGENT_TYPE,
                        "description": "a delegation",
                        **({"background": False} if event == "handoff_end" else {}),
                    }
                    for seconds, event in ((2, "handoff_start"), (1, "handoff_end"))
                ],
            )
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "background: false must close the launch even though the "
                "launch/return gap (1s) is well under BG_LAUNCH_MS",
            )

    def test_the_liveness_sweep_still_reaps_it(self) -> None:
        """THE INTEGRITY BOUND: a background-marked launch this rule keeps
        open longer is still reached by the SAME activity-quiet timeout every
        other unattributable launch already answers to - proving the only
        hole this change could open (a dead agent whose ack was misread as
        background, and which never emits ``subagent_stop``) is already
        closed by ``LIVENESS_MS``, unchanged by this task."""
        session = uuid.uuid4().hex
        old = int(keel_stop.LIVENESS_MS / 1000) + 60
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project,
                self._slow_background_ack(
                    session, "toolu_stale_bg", AGENT_ID,
                    launch_seconds_ago=old + 19, gap_seconds=19,
                ),
            )
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "a background: true launch quiet past LIVENESS_MS with no "
                "stop must still be reaped, or a dead agent's ack keeps "
                "[~] open forever",
            )
        # Recent, the same shape: quiet has not elapsed, so it IS still open.
        session2 = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            self._write(
                project,
                self._slow_background_ack(session2, "toolu_fresh_bg", AGENT_ID),
            )
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session2),
                "the sweep reaped a launch that has not been quiet for "
                "LIVENESS_MS",
            )

    def _stop_line(self, session: str, agent_id: str) -> dict[str, Any]:
        return {
            "v": 1,
            "ts": utc_stamp(seconds_ago=60),
            "event": "subagent_stop",
            "session": session,
            "agent_type": AGENT_TYPE,
            "agent_id": agent_id,
        }


class TestTheLaunchRecordCarriesTheKey(unittest.TestCase):
    """The capture side: where the id comes from, and where it does not.

    Asserted through the launcher as a real subprocess, house style, so what
    is checked is the bytes a harness would leave on disk.
    """

    def _handoffs(self, project: Path, root: Path, payload: dict[str, Any]) -> dict[str, Any]:
        result = run_hook("capture", payload, project, root)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [
            r for r in audit_records(project)
            if r.get("event") in ("handoff_start", "handoff_end")
        ]
        self.assertEqual(len(records), 1, records)
        return records[0]

    def _post(self, project: Path, session: str, response: Any) -> dict[str, Any]:
        payload = task_payloads(project, session, AGENT_ID)[1]
        payload["tool_response"] = response
        return payload

    def test_the_structured_field_of_an_async_launch_is_read(self) -> None:
        """234 of the 240 measured results have this shape: the backgrounded
        acknowledgment, whose id is on record minutes before any stop."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root,
                self._post(project, uuid.uuid4().hex, {
                    "isAsync": True, "status": "async_launched",
                    "agentId": AGENT_ID, "description": "a delegation",
                }),
            )
            self.assertEqual(record["agent_id"], AGENT_ID)

    def test_the_structured_field_of_a_foreground_return_is_read(self) -> None:
        """The other 6: a completed return, which lands AFTER the stop it
        identifies. A log is read after both lines are in it, so the order
        costs the join nothing - but the shape must still be read."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root,
                self._post(project, uuid.uuid4().hex, {
                    "status": "completed", "agentType": AGENT_TYPE,
                    "agentId": AGENT_ID, "totalDurationMs": 61234,
                    "content": [{"type": "text", "text": "STATUS: done"}],
                }),
            )
            self.assertEqual(record["agent_id"], AGENT_ID)

    def test_the_snake_case_spelling_is_read_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root,
                self._post(project, uuid.uuid4().hex, {"agent_id": AGENT_ID}),
            )
            self.assertEqual(record["agent_id"], AGENT_ID)

    def test_the_result_text_is_read_when_no_field_carries_the_id(self) -> None:
        """A harness build that hands a hook the rendered result instead."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root,
                self._post(project, uuid.uuid4().hex, [
                    {"type": "text", "text": LAUNCH_ACK.format(agent_id=AGENT_ID)},
                ]),
            )
            self.assertEqual(record["agent_id"], AGENT_ID)

    def test_the_delegation_prompt_is_never_scanned_for_an_id(self) -> None:
        """THE FALSE KEY THIS COULD HAVE INVENTED, refused.

        The launch tool echoes the delegation's own prompt back in its result,
        and keel's briefs discuss agent ids in prose - this repository's T102
        brief quotes one verbatim. A scan that wandered into the prompt would
        lift an id out of a sentence ABOUT one and record it as this
        delegation's. A wrong id is worse than none: it is a false pairing
        wearing an exact key's clothes.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root,
                self._post(project, uuid.uuid4().hex, {
                    "status": "async_launched", "isAsync": True,
                    "prompt": (
                        "Read the finding: a launch result carried "
                        'agentId: a9999999999999999 and the stop matched it.'
                    ),
                }),
            )
            self.assertIsNone(record["agent_id"], "an id was lifted from prose")

    def test_a_result_with_no_id_records_a_null(self) -> None:
        """Absence is expressed, never faked (convention 7)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for response in ({"status": "completed"}, [], "", 17, None):
                with self.subTest(response=response):
                    audit = project.joinpath(*AUDIT_RELPATH)
                    if audit.is_file():
                        audit.unlink()
                    record = self._handoffs(
                        project, root, self._post(project, uuid.uuid4().hex, response)
                    )
                    self.assertIsNone(record["agent_id"])

    def test_the_launch_half_records_a_null_because_nothing_has_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self._handoffs(
                project, root, task_payloads(project, uuid.uuid4().hex, AGENT_ID)[0]
            )
            self.assertEqual(record["event"], "handoff_start")
            self.assertIn("agent_id", record, "the field is present on both halves")
            self.assertIsNone(record["agent_id"])


class TestTheHandlerSaysWhatItWillNotAssume(unittest.TestCase):
    """Declared policy is asserted, house style, not left to a reader."""

    def _doc(self) -> str:
        return keel_hook.cmd_subagent_stop.__doc__ or ""

    def test_non_uniqueness_is_stated_in_the_docstring(self) -> None:
        doc = self._doc().casefold()
        self.assertIn("not a delegation", doc)
        self.assertIn("de-duplicate", doc)
        # Whitespace-tolerant: the sentence is allowed to reflow, the claim is not.
        self.assertRegex(doc, r"48\s+stops\s+against\s+26\s+launches")

    def test_the_absence_of_pairing_is_stated(self) -> None:
        doc = self._doc().casefold()
        self.assertIn("no pairing is attempted", doc)
        self.assertIn("recorded rather than dropped", doc)

    def test_both_directions_of_the_failure_policy_are_declared(self) -> None:
        doc = self._doc().casefold()
        self.assertIn("fail-open", doc)
        self.assertIn("fail-closed", doc)


class TestTheRealAuditLogStillParses(unittest.TestCase):
    """Against this repository's own log, not a fixture written to pass."""

    def test_appending_to_the_real_log_disturbs_nothing_before_it(self) -> None:
        """What is already written stays written, byte for byte and in order.

        The property asserted is PREFIX-UNCHANGED, and it is deliberately
        blind to what the record already holds. An earlier form of this case
        opened by asserting the log contained no ``subagent_stop`` line at
        all - true only while the subscription was dead, and permanently
        false since the harness began firing it: the real log gains stop
        lines every session, including from the agent running this suite. So
        the lines present BEFORE the append are snapshotted and compared
        against themselves afterwards, and the count of pre-existing stops is
        measured rather than pinned - one more line than there were, whatever
        there were. The bytes the append itself contributed are then held to
        the write-side contract separately: one complete line, terminated.

        The real log is READ, copied into a temporary project, and never
        written: the append under test lands on the copy, which the enclosing
        ``TemporaryDirectory`` removes. Nothing needs restoring because
        nothing in this repository is modified.
        """
        self.assertTrue(REAL_AUDIT.is_file(), f"missing {REAL_AUDIT}")
        original = REAL_AUDIT.read_text(encoding="utf-8")
        before = [line for line in original.splitlines() if line.strip()]
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            self.assertEqual(before, [], "a published cut declares an empty audit log")
        else:
            self.assertGreater(
                len(before), 1000, "premise: a long log holding several generations"
            )
        for line in before:
            json.loads(line)  # every existing line parses, unchanged

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            target = project.joinpath(*AUDIT_RELPATH)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(original)

            # Measured, not pinned: however many finish lines the record has
            # already accumulated, the append must add exactly one more.
            stops_before = len(stops_in(project))

            result = run_hook(
                "subagent_stop", stop_payload(project, uuid.uuid4().hex), project, root
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            after = target.read_text(encoding="utf-8")
            self.assertTrue(
                after.startswith(original),
                "the log is append-only: earlier bytes may not move",
            )

            # The appended bytes ALONE, held to the write-side contract that
            # every record carries its own terminator (``keel_events`` writes
            # ``json.dumps(...) + "\n"``). Asserted here because no other
            # check in this case can see that terminator go missing: the
            # copied log already ends with a newline from the record before
            # it, so a dropped "\n" is masked by the old bytes - the prefix
            # still matches, ``splitlines`` forgives an unterminated final
            # line, and it still parses. The corruption would surface only
            # when a SECOND append merged two records into one line, in some
            # later session, against a log nothing rewrites.
            appended = after[len(original) :]
            self.assertTrue(
                appended.endswith("\n"),
                "an append must terminate its own line, not lean on the one before it",
            )
            self.assertEqual(
                appended.count("\n"), 1, f"one append, one line: {appended!r}"
            )
            json.loads(appended)

            lines = [line for line in after.splitlines() if line.strip()]
            # Line by line, so a corrupted or reordered record names the place
            # it moved rather than dumping a thousand lines of diff.
            for index, (kept, prior) in enumerate(zip(lines, before), start=1):
                self.assertEqual(
                    kept, prior, f"line {index} of the record changed or moved"
                )
            # Catches the truncating append the loop above cannot see: zip
            # stops at the shorter side.
            self.assertEqual(len(lines), len(before) + 1)
            for line in lines:
                json.loads(line)  # and every line still parses afterwards
            self.assertEqual(len(stops_in(project)), stops_before + 1)


if __name__ == "__main__":
    unittest.main()
