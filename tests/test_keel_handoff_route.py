#!/usr/bin/env python3
"""The route a delegation ran at: model and effort on the hand-off record.

Contract
--------
Reads   : ``hooks/keel_capture.py`` (imported), this repository's own
          ``agents/*.md`` definitions - read only, as the values to compare
          against, never rewritten - and its own
          ``.keel/audit/keel-audit.jsonl``, read only, for the
          older-lines-still-parse case. Definitions it invents are written
          into temporary directories only.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with a copy of the environment carrying no ``KEEL_*``
          variable and no ``CLAUDE_PROJECT_DIR``, so a developer's own shell
          cannot change what a test observes.

What this file is for
---------------------
T123 (absorbing the predecessor ledger's T111) gave every new hand-off record
two fields: ``model`` and ``effort``, resolved from the launch's own
``tool_input`` override first and from the launched agent's definition second,
and recorded as ``null`` when neither answers. The law behind the fields is
that an attempt whose effort is unknown cannot be escalated from - so a
GUESSED default would defeat the field, and the cases below are as much about
what is never invented as about what is resolved.

T128 added the SECOND source and the classes at the end of this file: the
launch tool's own result carries ``resolvedModel``, so a delegation that
overrode nothing can still be recorded at the model the harness actually
resolved instead of at the definition's preference. It is in the RESULT, so
only the CLOSE half can carry it, and the order it takes its place in is
override, then result, then definition, then null.

EVERY T128 CASE OWNS ITS PREMISES TWICE OVER. The unit cases write their own
definitions and repoint ``AGENTS_DIR``, as the order cases do; the subprocess
cases cannot repoint it, so they launch a subagent type NO definition can
answer for - which makes the definition source empty whatever this repository
currently ships, and leaves the result as the only source that could have
supplied the value asserted. No T128 case reads the real audit log or a real
agent definition, and none of the model names below is a real one.

Three levels, on purpose:

* the resolver alone, against definitions this file writes into a temporary
  directory - the only way to drive the failure paths (no directory, no file,
  no fence, no keys) without damaging the repository's own agents;
* the resolution ORDER - override, then definition, then null - against
  definitions this file writes too, for the reason below;
* the shipped hook as a SUBPROCESS, house style, so what is asserted is the
  bytes a harness would leave on disk, redaction included.

EVERY ROUTE THIS FILE ASSERTS A VALUE FOR IS ONE THIS FILE WROTE, and that is
the T117 lesson paid for a second time. The first form of the order cases
used the real ``agents/executor.md`` as its "declares no effort" fixture,
which was true on the day they were written and false the day after: the
missing key was a gap, somebody closed it by declaring ``effort: default``,
and six tests failed for the improvement. A definition's route is EDITABLE
STATE, so no case here premises on what a real definition currently declares
- neither the presence of an optional key nor its absence.

The subprocess cases still run against the real ``agents/`` directory,
because ``AGENTS_DIR`` is resolved beside the hook and a subprocess has no
seam to point elsewhere. What they assert is therefore only what the contract
guarantees whatever the definitions say: that the record AGREES with the
definition on disk, read with this file's own parser via ``get`` - a key that
is not there yields ``None`` on both sides and the case still means something.

NO REAL HOME PATH APPEARS IN THIS FILE. The redaction case needs a value that
must not survive, and it is assembled from an invented account name and the
home root spelled as a constant, the way ``tests/test_keel_home_shapes.py``
does it: a test for a leak may not be the leak.

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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"
AGENTS_DIR = REPO_ROOT / "agents"
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")
REAL_AUDIT = REPO_ROOT.joinpath(*AUDIT_RELPATH)

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_capture  # noqa: E402  (path must be set first)
import keel_events  # noqa: E402
import keel_redact  # noqa: E402
import keel_stop  # noqa: E402
from keel_published_cut import contradiction, is_published_cut  # noqa: E402

#: The two wire names, spelled out rather than imported: this file exists to
#: notice the capture side and its readers drifting apart, and a guard that
#: imports the name it checks cannot see it move.
MODEL_FIELD = "model"
EFFORT_FIELD = "effort"

#: An agent this repository really ships, used ONLY by the subprocess cases,
#: which cannot point the hook at a temporary directory. What it declares is
#: read from the file at assertion time and never assumed: the cases compare
#: the record against the definition, not against a value written down here.
REAL_AGENT = "executor-deep"

#: The plugin namespace a subagent type arrives with in the payload.
NAMESPACE = "keel"

#: An invented account name and the home root as a constant, so that no
#: literal home path followed by a name appears in this file's source. The
#: marker is what a shape that cannot be expressed safely becomes.
FAKE = "someoneelse"
WIN_ROOT = "Users"
MARK = keel_redact.HOME_SHAPE_TOKEN


def utc_stamp(seconds_ago: int = 0) -> str:
    """A timestamp in keel's own spelling, offset into the past."""
    moment = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def frontmatter_of(path: Path) -> dict[str, str]:
    """This file's OWN frontmatter reader - deliberately not the one under test.

    The expected values are parsed out of the real definitions with an
    independent reader, so a defect in the capture-side parser cannot supply
    both sides of an assertion.
    """
    fields: dict[str, str] = {}
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].strip() != "---":
        return fields
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return fields


def write_definition(directory: Path, stem: str, body: str) -> Path:
    """One invented agent definition, written verbatim."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{stem}.md"
    path.write_text(body, encoding="utf-8")
    return path


def definition(**fields: str) -> str:
    """A definition file's text: a closed frontmatter fence, then a body."""
    lines = "\n".join(f"{key}: {value}" for key, value in fields.items())
    return f"---\n{lines}\n---\n\nYou are an invented agent.\n"


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


#: "this caller passed no result", which is NOT the same fact as "the result
#: was literally null" - a shape T128's failure paths hand the hook on purpose.
DEFAULT_RESULT = object()


def task_payloads(
    project: Path,
    session: str,
    subagent_type: Any,
    *,
    result: Any = DEFAULT_RESULT,
    **tool_input: Any,
) -> list[dict[str, Any]]:
    """The two capture payloads one delegation produces, launch then return.

    ``result`` replaces the RETURN half's ``tool_response`` wholesale (T128),
    so a case can hand the close half the shape a real launch result has -
    including a value that is not a mapping at all. Keyword-only, so it can
    never be mistaken for a ``tool_input`` key. The default is the shape the
    older cases were written against and is unchanged.
    """
    common: dict[str, Any] = {
        "tool_name": "Task",
        "tool_use_id": "toolu_route_1",
        "tool_input": dict(
            {
                "subagent_type": subagent_type,
                "description": "a delegation",
                "prompt": "TASK: do the thing",
            },
            **tool_input,
        ),
        "session_id": session,
        "cwd": str(project),
    }
    default = {"status": "async_launched", "agentId": "a8a960cff0a7d45"}
    return [
        dict(common, hook_event_name="PreToolUse"),
        dict(
            common,
            hook_event_name="PostToolUse",
            tool_response=default if result is DEFAULT_RESULT else result,
        ),
    ]


def run_hook(
    subcommand: str, payload: Any, project: Path, scratch: Path
) -> subprocess.CompletedProcess[bytes]:
    """Run the launcher exactly as a harness does: argv, JSON on stdin."""
    return subprocess.run(
        [sys.executable, "-B", str(HOOK), subcommand],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=clean_env(scratch),
        cwd=str(project),
        timeout=60,
        check=False,
    )


def adopted_project(root: Path) -> Path:
    """A project keel would record in: it carries ``.keel/``, nothing more."""
    project = root / "project"
    (project / ".keel").mkdir(parents=True)
    return project


def audit_records(project: Path) -> list[dict[str, Any]]:
    """Every audit line of a project, decoded. A bad line fails the test."""
    path = project.joinpath(*AUDIT_RELPATH)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def handoffs_in(project: Path) -> list[dict[str, Any]]:
    """Only the two hand-off halves."""
    return [
        record
        for record in audit_records(project)
        if record.get("event") in ("handoff_start", "handoff_end")
    ]


class TestTheDefinitionResolves(unittest.TestCase):
    """The resolver alone, against definitions written for each case."""

    def route(self, directory: Path, subagent_type: Any) -> tuple[Any, Any]:
        return keel_capture.definition_route(subagent_type, directory)

    def test_a_definition_supplies_both_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(
                agents, "invented", definition(name="invented", model="opus", effort="high")
            )
            self.assertEqual(self.route(agents, "invented"), ("opus", "high"))

    def test_a_namespaced_type_resolves_to_the_bare_filename(self) -> None:
        """``keel:executor-deep`` names ``agents/executor-deep.md``: the
        namespace belongs to the plugin, the file does not carry it."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(
                agents, "executor-deep", definition(model="opus", effort="high")
            )
            for spelling in ("keel:executor-deep", "executor-deep", " keel:executor-deep "):
                with self.subTest(spelling=spelling):
                    self.assertEqual(self.route(agents, spelling), ("opus", "high"))

    def test_a_definition_without_effort_yields_a_model_and_a_null(self) -> None:
        """Half known is recorded as half known - not as a default effort."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(agents, "invented", definition(name="invented", model="sonnet"))
            self.assertEqual(self.route(agents, "invented"), ("sonnet", None))

    def test_a_definition_without_either_key_yields_two_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(agents, "invented", definition(name="invented", tools="Read"))
            self.assertEqual(self.route(agents, "invented"), (None, None))

    def test_a_missing_definition_yields_two_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            agents.mkdir()
            self.assertEqual(self.route(agents, "keel:no-such-agent"), (None, None))

    def test_a_missing_agents_directory_yields_two_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.route(Path(tmp) / "absent", "invented"), (None, None))

    def test_a_definition_that_cannot_be_read_yields_two_nulls(self) -> None:
        """Two unreadable shapes: a directory wearing the name of a definition,
        and a path the reader is handed directly that is not there at all."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            (agents / "invented.md").mkdir(parents=True)
            self.assertEqual(self.route(agents, "invented"), (None, None))
            self.assertEqual(
                keel_capture._definition_frontmatter(agents / "gone.md"), {}
            )
            self.assertEqual(keel_capture._definition_frontmatter(agents), {})

    def test_a_file_with_no_frontmatter_yields_two_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(agents, "invented", "model: opus\neffort: high\n")
            self.assertEqual(self.route(agents, "invented"), (None, None))

    def test_an_unterminated_fence_yields_two_nulls(self) -> None:
        """A block that never closes may not be frontmatter at all, so it
        records "unknown" rather than half a header."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(agents, "invented", "---\nmodel: opus\neffort: high\n")
            self.assertEqual(self.route(agents, "invented"), (None, None))

    def test_a_fence_that_closes_past_the_scan_limit_yields_two_nulls(self) -> None:
        """The read is bounded, so a payload cannot turn one hook into a reader
        of an arbitrarily large file - and what it could not read is null."""
        filler = "x" * (keel_capture.DEFINITION_SCAN_CHARS + 100)
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(
                agents,
                "invented",
                f"---\ndescription: {filler}\nmodel: opus\neffort: high\n---\n",
            )
            self.assertEqual(self.route(agents, "invented"), (None, None))

    def test_indented_and_commented_keys_are_not_read(self) -> None:
        """A nested or commented ``effort:`` is not this agent's effort."""
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(
                agents,
                "invented",
                "---\nmodel: opus\nnested:\n  effort: high\n# effort: low\n---\n",
            )
            self.assertEqual(self.route(agents, "invented"), ("opus", None))

    def test_a_quoted_value_is_recorded_as_the_level_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            write_definition(agents, "invented", '---\nmodel: "opus"\neffort: \'high\'\n---\n')
            self.assertEqual(self.route(agents, "invented"), ("opus", "high"))

    def test_a_type_that_could_name_another_file_resolves_to_nothing(self) -> None:
        """The type arrives in a PAYLOAD and this value reaches the filesystem,
        so it is whitelisted rather than sanitised (R5). None of these may read
        a file, and none of them may raise."""
        outside = Path(tempfile.gettempdir()) / "keel-route-outside.md"
        try:
            outside.write_text(definition(model="stolen", effort="stolen"), encoding="utf-8")
            with tempfile.TemporaryDirectory() as tmp:
                agents = Path(tmp) / "agents"
                agents.mkdir()
                hostile = (
                    "../keel-route-outside",
                    "keel:../keel-route-outside",
                    "..\\keel-route-outside",
                    "/etc/passwd",
                    "C:\\Windows\\win",
                    "..",
                    ".hidden",
                    "",
                    "   ",
                )
                for value in hostile:
                    with self.subTest(value=value):
                        self.assertEqual(self.route(agents, value), (None, None))
        finally:
            if outside.is_file():
                outside.unlink()

    def test_a_type_of_an_unexpected_type_resolves_to_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents = Path(tmp) / "agents"
            agents.mkdir()
            for value in (None, 17, [], {}, True):
                with self.subTest(value=value):
                    self.assertEqual(self.route(agents, value), (None, None))

    def test_the_default_directory_is_beside_the_hook(self) -> None:
        """Not under the session's cwd: the definitions that launched the agent
        are the installed plugin's own, and an observed project's ``agents/``
        would answer with somebody else's routing."""
        self.assertEqual(
            keel_capture.AGENTS_DIR,
            Path(keel_capture.__file__).resolve().parent.parent / "agents",
        )


class TestTheResolutionOrder(unittest.TestCase):
    """Override first, definition second, null third - on its own fixtures.

    BOTH PREMISES ARE WRITTEN HERE rather than found in the repository: one
    definition that declares an effort and one that declares none, both
    invented. An earlier form of this class read the real ``agents/`` for
    those two shapes and broke the day the missing key was legitimately
    filled in - see the T117 note in this file's contract. A test that can be
    falsified by improving the thing it does not test is testing the wrong
    thing.

    ``AGENTS_DIR`` is repointed for the length of each case, because
    ``launch_route`` resolves the definitions beside the hook by design and
    takes no directory of its own; the redactor, the parser and the record
    builder under test are the shipped ones.
    """

    #: Invented agents, and invented routes. None of these strings is a real
    #: model or a real level name: if one were, a reader could not tell an
    #: assertion about resolution from an assertion about this repository.
    BOTH_KEYS = "invented-with-effort"
    MODEL_ONLY = "invented-without-effort"
    MODEL = "invented-model"
    EFFORT = "invented-effort"
    OTHER_MODEL = "invented-second-model"
    OVERRIDE = "invented-override"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agents = Path(self.tmp.name) / "agents"
        write_definition(
            agents,
            self.BOTH_KEYS,
            definition(name=self.BOTH_KEYS, model=self.MODEL, effort=self.EFFORT),
        )
        write_definition(
            agents,
            self.MODEL_ONLY,
            definition(name=self.MODEL_ONLY, model=self.OTHER_MODEL),
        )
        # The premises, asserted against the files this class just wrote, so
        # that a broken helper fails here rather than passing everything below.
        self.assertEqual(
            frontmatter_of(agents / f"{self.BOTH_KEYS}.md").get("effort"), self.EFFORT
        )
        self.assertNotIn("effort", frontmatter_of(agents / f"{self.MODEL_ONLY}.md"))
        original = keel_capture.AGENTS_DIR
        keel_capture.AGENTS_DIR = agents
        self.addCleanup(setattr, keel_capture, "AGENTS_DIR", original)

    def route(self, subagent_type: Any, **tool_input: Any) -> tuple[Any, Any]:
        event = keel_events.KeelEvent(
            kind="post_tool",
            cwd=REPO_ROOT,
            session_id=uuid.uuid4().hex,
            tool_name="Task",
            raw={
                "hook_event_name": "PreToolUse",
                "tool_input": dict({"subagent_type": subagent_type}, **tool_input),
            },
        )
        return keel_capture.launch_route(event)

    def test_the_definition_answers_when_the_call_carries_no_override(self) -> None:
        self.assertEqual(
            self.route(f"{NAMESPACE}:{self.BOTH_KEYS}"), (self.MODEL, self.EFFORT)
        )

    def test_an_explicit_model_beats_the_definition(self) -> None:
        """An override is what RAN, whatever the definition says - and it
        overrides the model alone: the effort still comes from the file."""
        model, effort = self.route(
            f"{NAMESPACE}:{self.BOTH_KEYS}", model=f"  {self.OVERRIDE}  "
        )
        self.assertEqual(model, self.OVERRIDE)
        self.assertNotEqual(model, self.MODEL, "the override was ignored")
        self.assertEqual(effort, self.EFFORT)

    def test_an_empty_override_is_not_an_override(self) -> None:
        for value in ("", "   ", None, 17):
            with self.subTest(value=value):
                self.assertEqual(
                    self.route(f"{NAMESPACE}:{self.BOTH_KEYS}", model=value),
                    (self.MODEL, self.EFFORT),
                )

    def test_a_definition_with_no_effort_records_the_model_and_a_null(self) -> None:
        """The half-known case, on a definition written to be half known."""
        self.assertEqual(
            self.route(f"{NAMESPACE}:{self.MODEL_ONLY}"), (self.OTHER_MODEL, None)
        )

    def test_an_unknown_agent_records_two_nulls_and_no_default(self) -> None:
        self.assertEqual(self.route(f"{NAMESPACE}:no-such-agent-here"), (None, None))
        self.assertEqual(self.route(None), (None, None))

    def test_an_override_with_no_definition_still_records_the_model(self) -> None:
        model, effort = self.route("no-such-agent-here", model=self.OVERRIDE)
        self.assertEqual(model, self.OVERRIDE)
        self.assertIsNone(effort, "an unknown effort may not be invented")


class TestTheRecordCarriesTheRoute(unittest.TestCase):
    """The shipped hook as a subprocess: the bytes a harness would leave.

    THE ONLY CASES THAT TOUCH THE REAL ``agents/``, because ``AGENTS_DIR`` is
    resolved beside the hook and a subprocess offers no seam to point it
    elsewhere. What they assert is AGREEMENT, not a value: the record must say
    what the definition on disk says, read here with this file's own parser
    through ``get`` - so a definition that declares no effort makes both sides
    ``None`` and the case still holds. Nothing here breaks when an agent is
    legitimately re-routed, which is exactly what these cases exist to notice
    if the capture layer ever stops following.
    """

    def expected_route(self) -> tuple[Any, Any]:
        """What the real definition declares right now, whatever that is."""
        path = AGENTS_DIR / f"{REAL_AGENT}.md"
        self.assertTrue(path.is_file(), f"missing {path}")
        fields = frontmatter_of(path)
        return fields.get("model"), fields.get("effort")

    def capture(
        self, project: Path, root: Path, payload: dict[str, Any]
    ) -> dict[str, Any]:
        result = run_hook("capture", payload, project, root)
        self.assertEqual(result.returncode, 0, result.stderr)
        records = handoffs_in(project)
        self.assertEqual(len(records), 1, records)
        return records[0]

    def test_the_launch_half_agrees_with_the_definition_on_disk(self) -> None:
        model, effort = self.expected_route()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self.capture(
                project,
                root,
                task_payloads(project, uuid.uuid4().hex, f"{NAMESPACE}:{REAL_AGENT}")[0],
            )
            self.assertEqual(record["event"], "handoff_start")
            self.assertEqual(record[MODEL_FIELD], model)
            self.assertEqual(record[EFFORT_FIELD], effort)

    def test_both_halves_carry_the_fields(self) -> None:
        """Present on both, for the reason ``agent_id`` is: a key missing from
        one half would be indistinguishable from a line predating the key."""
        model, effort = self.expected_route()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            for payload in task_payloads(
                project, uuid.uuid4().hex, f"{NAMESPACE}:{REAL_AGENT}"
            ):
                result = run_hook("capture", payload, project, root)
                self.assertEqual(result.returncode, 0, result.stderr)
            records = handoffs_in(project)
            self.assertEqual([r["event"] for r in records], ["handoff_start", "handoff_end"])
            for record in records:
                self.assertIn(MODEL_FIELD, record, "absence is expressed, never omitted")
                self.assertIn(EFFORT_FIELD, record, "absence is expressed, never omitted")
                self.assertEqual(record[MODEL_FIELD], model)
                self.assertEqual(record[EFFORT_FIELD], effort)

    def test_an_override_reaches_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self.capture(
                project,
                root,
                task_payloads(
                    project,
                    uuid.uuid4().hex,
                    f"{NAMESPACE}:{REAL_AGENT}",
                    model="invented-override",
                )[0],
            )
            self.assertEqual(record[MODEL_FIELD], "invented-override")

    def test_an_unknown_agent_records_json_nulls_the_keys_are_still_there(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self.capture(
                project,
                root,
                task_payloads(project, uuid.uuid4().hex, f"{NAMESPACE}:no-such-agent")[0],
            )
            for field in (MODEL_FIELD, EFFORT_FIELD):
                self.assertIn(field, record, "absence is expressed, never omitted")
                self.assertIsNone(record[field])
            raw = project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
            self.assertIn('"model": null', raw)
            self.assertIn('"effort": null', raw)

    def test_the_observed_projects_own_agents_directory_is_not_read(self) -> None:
        """The session's cwd is not a source of routing. A project keel is
        merely observing may carry an ``agents/`` of its own, and the agent
        that ran was the installed plugin's - so the definition beside the
        HOOK is the one that answers."""
        model, effort = self.expected_route()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            write_definition(
                project / "agents",
                REAL_AGENT,
                definition(model="impostor-model", effort="impostor-effort"),
            )
            record = self.capture(
                project,
                root,
                task_payloads(project, uuid.uuid4().hex, f"{NAMESPACE}:{REAL_AGENT}")[0],
            )
            self.assertEqual(record[MODEL_FIELD], model)
            self.assertEqual(record[EFFORT_FIELD], effort)
            self.assertNotIn("impostor", json.dumps(record))

    def test_a_hostile_type_costs_the_fields_and_nothing_else(self) -> None:
        """The record is still written, the hook still exits 0, and the two
        fields it could not resolve are null - the fail-open policy applied to
        the smallest unit that can fail."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            record = self.capture(
                project,
                root,
                task_payloads(project, uuid.uuid4().hex, "keel:../../etc/passwd")[0],
            )
            self.assertIsNone(record[MODEL_FIELD])
            self.assertIsNone(record[EFFORT_FIELD])
            self.assertEqual(record["subagent_type"], "keel:../../etc/passwd")


class TestTheNewFieldsAreScreened(unittest.TestCase):
    """Both fields pass the write-time screen, from both of their sources.

    The chokepoint is ``keel_events._append_jsonl`` - the one function every
    audit line passes through - and these cases read the BYTES on disk rather
    than a return value, because a screen that was never reached cannot be
    seen from the value that skipped it.
    """

    #: An invented home path, assembled from parts. Not this machine's, and
    #: not a person: a test for a leak may not be the leak.
    HOSTILE = f"C:\\{WIN_ROOT}\\{FAKE}\\models\\local-build"

    def test_an_override_carrying_a_home_path_is_screened(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            payload = task_payloads(
                project, uuid.uuid4().hex, f"{NAMESPACE}:{REAL_AGENT}", model=self.HOSTILE
            )[0]
            result = run_hook("capture", payload, project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            raw = project.joinpath(*AUDIT_RELPATH).read_bytes()
            self.assertNotIn(FAKE.encode("utf-8"), raw, "the audit log carries a name")
            record = handoffs_in(project)[0]
            self.assertIn(MARK, record[MODEL_FIELD])
            self.assertIn("local-build", record[MODEL_FIELD], "the field recorded nothing")

    def test_a_definition_value_carrying_a_home_path_is_screened(self) -> None:
        """The other source. ``AGENTS_DIR`` is repointed for the length of this
        case - the only way to make a DEFINITION supply a value that must not
        survive without writing one into this repository's own ``agents/``.
        The redactor, the chokepoint and the writer are the shipped ones.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            agents = root / "agents"
            write_definition(
                agents,
                "invented",
                definition(model=self.HOSTILE, effort=f"{self.HOSTILE}-effort"),
            )
            event = keel_events.KeelEvent(
                kind="post_tool",
                cwd=project,
                session_id=uuid.uuid4().hex,
                tool_name="Task",
                raw={
                    "hook_event_name": "PreToolUse",
                    "tool_use_id": "toolu_screen",
                    "tool_input": {"subagent_type": "keel:invented"},
                },
            )
            original = keel_capture.AGENTS_DIR
            keel_capture.AGENTS_DIR = agents
            try:
                self.assertEqual(keel_capture.run(event), 0, "capture is fail-open")
            finally:
                keel_capture.AGENTS_DIR = original
            raw = keel_events.audit_path(project).read_bytes()
            self.assertNotIn(FAKE.encode("utf-8"), raw, "the audit log carries a name")
            record = handoffs_in(project)[0]
            self.assertIn(MARK, record[MODEL_FIELD])
            self.assertIn(MARK, record[EFFORT_FIELD])

    def test_the_hostile_value_really_did_carry_the_name(self) -> None:
        """The other half of the pin: without it, the two cases above could
        pass on a fixture that never held an account name in the first place."""
        self.assertIn(FAKE, self.HOSTILE)
        self.assertNotIn(MARK, self.HOSTILE)


class TestOlderLinesStayReadable(unittest.TestCase):
    """Every line written before the fields existed parses, and reads as unknown."""

    def test_the_real_audit_logs_handoff_lines_all_parse(self) -> None:
        self.assertTrue(REAL_AUDIT.is_file(), f"missing {REAL_AUDIT}")
        lines = [
            json.loads(line)
            for line in REAL_AUDIT.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if is_published_cut(REPO_ROOT):
            reason = contradiction(REPO_ROOT)
            if reason:
                self.fail(reason)
            self.assertEqual(lines, [], "a published cut declares an empty audit log")
            return
        self.assertGreater(len(lines), 1000, "premise: a long log, several generations")
        handoffs = [
            line for line in lines if line.get("event") in ("handoff_start", "handoff_end")
        ]
        self.assertGreater(len(handoffs), 100, "premise: the log holds hand-offs")
        older = [line for line in handoffs if MODEL_FIELD not in line]
        self.assertGreater(
            len(older), 100, "premise: most of the record predates the fields"
        )
        for line in older:
            # The reader's rule for an older line: absent is unknown, and
            # ``get`` answers exactly what a null would - never a default.
            self.assertIsNone(line.get(MODEL_FIELD))
            self.assertIsNone(line.get(EFFORT_FIELD))
            self.assertIn("subagent_type", line, "an older line is otherwise intact")

    def test_the_stop_gate_still_pairs_lines_that_have_no_route(self) -> None:
        """The consumer that pairs hand-offs reads neither field, so an old
        line opens and closes exactly as it did before.

        The two stamps are spaced past ``BG_LAUNCH_MS`` deliberately: a return
        landing within that of its launch is a background ACKNOWLEDGMENT and
        leaves the delegation open, which is the gate's own rule and not
        something this case is testing.
        """
        session = uuid.uuid4().hex
        old_shape = {
            "v": 1,
            "event": "handoff_start",
            "session": session,
            "tool_use_id": "toolu_old",
            "agent_id": None,
            "subagent_type": "keel:executor",
            "description": "a delegation from before the fields",
        }
        with tempfile.TemporaryDirectory() as tmp:
            project = adopted_project(Path(tmp))
            audit = project.joinpath(*AUDIT_RELPATH)
            audit.parent.mkdir(parents=True, exist_ok=True)
            with open(audit, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(dict(old_shape, ts=utc_stamp(200))) + "\n")
            self.assertTrue(
                keel_stop.session_has_open_handoff(project, session),
                "an old-shape launch stopped being read as an open hand-off",
            )
            with open(audit, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(
                        dict(old_shape, ts=utc_stamp(60), event="handoff_end")
                    )
                    + "\n"
                )
            self.assertFalse(
                keel_stop.session_has_open_handoff(project, session),
                "an old-shape pair stopped closing",
            )


class TestTheResultAnswersTheModel(unittest.TestCase):
    """T128: the launch RESULT's ``resolvedModel``, its place, and its failures.

    ONE INVENTED DEFINITION AND ONE NAME THAT HAS NONE, both written or
    checked here, for the reason the order cases give: a case premised on what
    a real definition currently declares is falsified by improving that
    definition. Every model name below is invented, so an assertion about
    resolution can never be confused with an assertion about this repository.

    The half is what makes this source available: a result exists only after
    the tool returned, so the OPEN half must answer without it even when a
    payload hands it one.
    """

    AGENT = "invented-t128-agent"
    UNKNOWN = "invented-t128-agent-with-no-file"
    DEFINITION_MODEL = "invented-definition-model"
    EFFORT = "invented-effort"
    RESOLVED = "invented-resolved-model"
    OTHER_RESOLVED = "invented-second-resolved-model"
    OVERRIDE = "invented-override-model"
    STOLEN = "invented-stolen-model"

    #: "this case passed no result at all", distinct from "the result was
    #: literally null" - which is one of the malformed shapes tested below.
    NO_RESULT = object()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        agents = Path(self.tmp.name) / "agents"
        write_definition(
            agents,
            self.AGENT,
            definition(name=self.AGENT, model=self.DEFINITION_MODEL, effort=self.EFFORT),
        )
        # The premises, read back with this file's own parser: the definition
        # really declares both keys, the other name really has no file, and the
        # three model spellings really are three.
        fields = frontmatter_of(agents / f"{self.AGENT}.md")
        self.assertEqual(fields.get(MODEL_FIELD), self.DEFINITION_MODEL)
        self.assertEqual(fields.get(EFFORT_FIELD), self.EFFORT)
        self.assertFalse((agents / f"{self.UNKNOWN}.md").exists())
        self.assertEqual(
            len({self.DEFINITION_MODEL, self.RESOLVED, self.OVERRIDE}), 3
        )
        original = keel_capture.AGENTS_DIR
        keel_capture.AGENTS_DIR = agents
        self.addCleanup(setattr, keel_capture, "AGENTS_DIR", original)

    def event(
        self,
        half: str,
        subagent_type: Any = None,
        response: Any = NO_RESULT,
        **tool_input: Any,
    ) -> Any:
        raw: dict[str, Any] = {
            "hook_event_name": half,
            "tool_input": dict(
                {"subagent_type": self.AGENT if subagent_type is None else subagent_type},
                **tool_input,
            ),
        }
        if response is not self.NO_RESULT:
            raw["tool_response"] = response
        return keel_events.KeelEvent(
            kind="post_tool",
            cwd=REPO_ROOT,
            session_id=uuid.uuid4().hex,
            tool_name="Task",
            raw=raw,
        )

    def route(self, half: str, **kwargs: Any) -> tuple[Any, Any]:
        return keel_capture.launch_route(self.event(half, **kwargs))

    def result(self, model: Any, key: str = "resolvedModel") -> dict[str, Any]:
        """A launch result in the measured shape, carrying one model."""
        return {"status": "async_launched", "agentId": "a8a960cff0a7d45", key: model}

    def test_the_close_half_takes_the_model_the_result_resolved(self) -> None:
        self.assertEqual(
            self.route("PostToolUse", response=self.result(self.RESOLVED)),
            (self.RESOLVED, self.EFFORT),
            "the result did not beat the definition",
        )

    def test_the_open_half_keeps_the_definitions_answer(self) -> None:
        self.assertEqual(
            self.route("PreToolUse"), (self.DEFINITION_MODEL, self.EFFORT)
        )

    def test_the_open_half_refuses_a_result_it_was_handed_anyway(self) -> None:
        """A resolution belongs to the moment the tool returned. A payload that
        carried one into PreToolUse would be backdating a fact, so the half is
        checked rather than merely assumed to be empty."""
        event = self.event("PreToolUse", response=self.result(self.RESOLVED))
        self.assertIsNone(keel_capture.result_model(event))
        self.assertEqual(
            keel_capture.launch_route(event), (self.DEFINITION_MODEL, self.EFFORT)
        )

    def test_an_explicit_override_beats_the_resolved_model(self) -> None:
        model, effort = self.route(
            "PostToolUse",
            response=self.result(self.RESOLVED),
            model=f"  {self.OVERRIDE}  ",
        )
        self.assertEqual(model, self.OVERRIDE)
        self.assertNotEqual(model, self.RESOLVED, "the override was ignored")
        self.assertEqual(effort, self.EFFORT)

    def test_an_empty_override_is_not_an_override_and_the_result_answers(self) -> None:
        for value in ("", "   ", None, 17, True, []):
            with self.subTest(value=value):
                self.assertEqual(
                    self.route(
                        "PostToolUse", response=self.result(self.RESOLVED), model=value
                    ),
                    (self.RESOLVED, self.EFFORT),
                )

    def test_the_result_answers_when_no_definition_can(self) -> None:
        """And the effort stays null: no result field names one, and an unknown
        effort may not be invented from a known model."""
        self.assertEqual(
            self.route("PostToolUse", subagent_type=self.UNKNOWN, response=self.result(self.RESOLVED)),
            (self.RESOLVED, None),
        )

    def test_a_result_that_names_no_model_falls_back_to_the_definition(self) -> None:
        self.assertEqual(
            self.route(
                "PostToolUse",
                response={"status": "async_launched", "agentId": "a8a960cff0a7d45"},
            ),
            (self.DEFINITION_MODEL, self.EFFORT),
        )

    def test_both_spellings_are_read_and_the_measured_one_is_preferred(self) -> None:
        self.assertEqual(
            self.route(
                "PostToolUse", response=self.result(self.RESOLVED, key="resolved_model")
            ),
            (self.RESOLVED, self.EFFORT),
        )
        both = self.result(self.RESOLVED)
        both["resolved_model"] = self.OTHER_RESOLVED
        model, _ = self.route("PostToolUse", response=both)
        self.assertEqual(model, self.RESOLVED, "the measured spelling lost")

    def test_the_value_is_trimmed_and_recorded_as_it_is_spelled(self) -> None:
        model, _ = self.route(
            "PostToolUse", response=self.result(f"  {self.RESOLVED}  ")
        )
        self.assertEqual(model, self.RESOLVED)

    def test_a_malformed_result_costs_the_source_and_nothing_else(self) -> None:
        """Every failure path answers "the result told me nothing", which falls
        through to the definition - never an exception, never a partial value."""
        malformed: tuple[Any, ...] = (
            None,
            17,
            True,
            "a result that is a bare string",
            # The one non-mapping shape the measurement actually found: a
            # launch the user rejected never ran, so it resolved nothing.
            "User rejected tool use",
            ["a", "list"],
            {},
            {"status": "async_launched"},
            self.result(None),
            self.result(17),
            self.result(True),
            self.result(""),
            self.result("   "),
            self.result([]),
            self.result({"name": "invented"}),
            self.result("first\nsecond"),
            self.result("has a \x00 in it"),
            self.result("x" * (keel_capture.RESULT_MODEL_MAX_CHARS + 1)),
        )
        for response in malformed:
            with self.subTest(response=response):
                self.assertEqual(
                    self.route("PostToolUse", response=response),
                    (self.DEFINITION_MODEL, self.EFFORT),
                )

    def test_a_token_at_the_bound_is_still_a_token(self) -> None:
        """The bound refuses a body, not a long name: the value one character
        under the limit is recorded, the one over it was refused above."""
        longest = "m" * keel_capture.RESULT_MODEL_MAX_CHARS
        model, _ = self.route("PostToolUse", response=self.result(longest))
        self.assertEqual(model, longest)

    def test_no_model_is_lifted_out_of_a_results_text(self) -> None:
        """STRUCTURE ONLY. A completed agent's result carries the agent's own
        report, and a report may discuss ``resolvedModel`` in prose - this
        file's own subject matter does. A scan that read it would record a
        model the delegation never ran at."""
        prose = f"the resolvedModel: {self.STOLEN} was discussed, not used"
        for response in (
            prose,
            [{"type": "text", "text": prose}],
            {"status": "completed", "content": [{"type": "text", "text": prose}]},
            {"status": "completed", "content": prose, "prompt": prose},
        ):
            with self.subTest(response=response):
                model, effort = self.route("PostToolUse", response=response)
                self.assertEqual((model, effort), (self.DEFINITION_MODEL, self.EFFORT))
                self.assertNotIn(self.STOLEN, str(model))

    def test_nothing_anywhere_still_records_two_nulls(self) -> None:
        self.assertEqual(
            self.route("PostToolUse", subagent_type=self.UNKNOWN), (None, None)
        )
        self.assertEqual(
            self.route(
                "PostToolUse",
                subagent_type=self.UNKNOWN,
                response={"status": "async_launched"},
            ),
            (None, None),
        )


class TestTheRecordCarriesTheResolvedModel(unittest.TestCase):
    """T128 through the shipped hook: the bytes a harness would leave on disk.

    THE SUBAGENT TYPE NAMES NO DEFINITION, on purpose. These cases run the hook
    as a subprocess, which offers no seam to repoint ``AGENTS_DIR``, so the
    definition source is emptied instead - by launching an invented type this
    repository ships no file for and cannot plausibly ship one for. The
    premise is asserted below rather than trusted, and it is an absence that
    improving a real definition cannot turn into a presence.
    """

    TYPE = f"{NAMESPACE}:invented-t128-agent-with-no-file"
    RESOLVED = "invented-resolved-model"
    OVERRIDE = "invented-override-model"

    #: An invented home path, assembled from parts, as the screen cases above
    #: do it: a test for a leak may not be the leak.
    HOSTILE = f"C:\\{WIN_ROOT}\\{FAKE}\\models\\local-build"

    def setUp(self) -> None:
        stem = self.TYPE.split(":")[-1]
        self.assertFalse(
            (AGENTS_DIR / f"{stem}.md").exists(),
            "premise: no definition answers for this type",
        )

    def capture_pair(
        self, project: Path, root: Path, payloads: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        for payload in payloads:
            result = run_hook("capture", payload, project, root)
            self.assertEqual(result.returncode, 0, result.stderr)
        records = handoffs_in(project)
        self.assertEqual([r["event"] for r in records], ["handoff_start", "handoff_end"])
        return records

    def payloads(self, project: Path, **kwargs: Any) -> list[dict[str, Any]]:
        return task_payloads(project, uuid.uuid4().hex, self.TYPE, **kwargs)

    def launch_result(self, model: Any) -> dict[str, Any]:
        return {
            "status": "async_launched",
            "agentId": "a8a960cff0a7d45",
            "resolvedModel": model,
        }

    def test_the_close_half_records_it_and_the_open_half_records_a_null(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            opened, closed = self.capture_pair(
                project,
                root,
                self.payloads(project, result=self.launch_result(self.RESOLVED)),
            )
            self.assertIsNone(opened[MODEL_FIELD], "the launch half knew no model")
            self.assertEqual(closed[MODEL_FIELD], self.RESOLVED)
            for record in (opened, closed):
                self.assertIsNone(record[EFFORT_FIELD], "no result names an effort")

    def test_an_override_wins_on_the_wire_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            records = self.capture_pair(
                project,
                root,
                self.payloads(
                    project,
                    result=self.launch_result(self.RESOLVED),
                    model=self.OVERRIDE,
                ),
            )
            for record in records:
                self.assertEqual(record[MODEL_FIELD], self.OVERRIDE)
            raw = project.joinpath(*AUDIT_RELPATH).read_text(encoding="utf-8")
            self.assertNotIn(self.RESOLVED, raw, "the override did not win")

    def test_the_record_gains_no_key_and_loses_none(self) -> None:
        """ADDITIVE ONLY: the resolved model reaches an existing field. A
        hand-off written with one carries exactly the keys a hand-off written
        without one carries, so every reader of the older shape still reads
        this line."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            with_model = self.capture_pair(
                project, root, self.payloads(project, result=self.launch_result(self.RESOLVED))
            )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            without = self.capture_pair(project, root, self.payloads(project))
        for new, old in zip(with_model, without):
            self.assertEqual(sorted(new), sorted(old))
        self.assertIsNone(without[1][MODEL_FIELD], "premise: the old shape is null")

    def test_a_hostile_resolved_model_is_screened_on_the_way_to_disk(self) -> None:
        """The new source passes the same write-time chokepoint as the other
        two: a result is payload, and payload does not reach the log unscreened.
        The bytes are read, not the return value - a screen that was never
        reached cannot be seen from the value that skipped it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = adopted_project(root)
            records = self.capture_pair(
                project, root, self.payloads(project, result=self.launch_result(self.HOSTILE))
            )
            raw = project.joinpath(*AUDIT_RELPATH).read_bytes()
            self.assertNotIn(FAKE.encode("utf-8"), raw, "the audit log carries a name")
            self.assertIn(MARK, records[1][MODEL_FIELD])
            self.assertIn("local-build", records[1][MODEL_FIELD], "the field recorded nothing")

    def test_a_malformed_result_still_leaves_a_pair_and_a_null(self) -> None:
        """Fail-open at the smallest unit that can fail: the hook exits 0, both
        halves are written, and the field it could not believe is null."""
        for response in (None, "a bare string", ["a", "list"], self.launch_result(17)):
            with self.subTest(response=response), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project = adopted_project(root)
                records = self.capture_pair(
                    project, root, self.payloads(project, result=response)
                )
                for record in records:
                    self.assertIn(MODEL_FIELD, record, "absence is expressed, never omitted")
                    self.assertIsNone(record[MODEL_FIELD])


if __name__ == "__main__":
    unittest.main()
