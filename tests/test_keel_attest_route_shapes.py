#!/usr/bin/env python3
"""``keel attest`` reads the Route line this repository actually writes.

Contract
--------
Reads   : nothing outside temporary directories it creates and removes.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

Regresses the defect recorded in
``.keel/knowledge/attest-parser-misses-contract-ledgers.md``: ``keel attest``
and ``scripts/keel_plans.py`` (the plan-contract gate checker) each carried
their own idea of what "a Route line" looks like, and the two disagreed on
the bare indented form (``  Route: executor``, no leading bullet) that this
repository's recent ledgers actually write - attest read only the bulleted
sub-bullet form and silently reported every bare-form task ``UNROUTED``.

This file pins all four shapes attest must resolve identically, plus the
ordering fix that keeps a task marked ``[x]`` from having its missing
hand-off masked by a merely-unparsed route:

  - a bare indented ``Route:`` line (``BareRouteLineTests``)
  - a bulleted ``- Route:`` sub-bullet, the real-world shape
    ``keel-plan-6f7fdee8.md`` uses (``BulletedRouteLineTests``)
  - the legacy inline ``| route: ... |`` field (``LegacyInlineRouteTests``)
  - a genuinely routeless ``[x]`` task, which must report UNATTESTED rather
    than the weaker, non-discrepancy ``UNROUTED`` alone
    (``RoutelessTaskOrderingTests``)

``SharedRouteDefinitionTests`` pins the structural fix itself: attest's
route-field pattern is compiled from ``keel_plans.ROUTE_LINE_PATTERN`` -
imported, not a second hand-typed copy - so the two modules cannot drift
apart again on the next ledger-style change.

T197: ``make_project`` now returns the session it minted, and every call
passes it explicitly to ``keel_attest.attest`` - identity is read, never
inferred from the log
(``.keel/decisions/2026-08-20-identity-is-read-never-inferred.md``), so
``attest(project, None)`` no longer falls back to "the log's latest
session_start" and would refuse in this file's own process environment.

Failure policy
--------------
FAIL-CLOSED: a fixture that cannot be written fails the test rather than
being skipped.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT_RELPATH = (".keel", "audit", "keel-audit.jsonl")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_attest  # noqa: E402  (path must be set first)
import keel_plans  # noqa: E402


def iso(offset_seconds: int) -> str:
    """A keel-format UTC timestamp, offset from now."""
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def make_project(
    tmp: Path, ledger: str, task_description: str = "T1: build the thing"
) -> tuple[Path, str]:
    """A project with one ledger and one CLOSED hand-off for ``task_description``.

    The hand-off's ``description`` names the task by id, exactly as
    ``match_handoff`` requires, so a task whose id is ``T1`` and whose
    ``task_description`` mentions ``T1`` attests cleanly; a
    ``task_description`` naming no task id leaves every task unmatched, which
    is what the routeless-task tests need.
    """
    project = tmp / "project"
    session = uuid.uuid4().hex
    plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(ledger, encoding="utf-8")
    lines = [
        {"v": 1, "ts": iso(-600), "event": "session_start", "session": session},
        {
            "v": 1,
            "ts": iso(-500),
            "event": "handoff_start",
            "session": session,
            "tool_use_id": "u1",
            "subagent_type": "executor",
            "description": task_description,
            "prompt_head": f"TASK {task_description}",
        },
        {
            "v": 1,
            "ts": iso(-400),
            "event": "handoff_end",
            "session": session,
            "tool_use_id": "u1",
            "subagent_type": "executor",
            "description": task_description,
            "prompt_head": f"TASK {task_description}",
        },
    ]
    audit = project.joinpath(*AUDIT_RELPATH)
    audit.parent.mkdir(parents=True)
    with open(audit, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return project, session


class SharedRouteDefinitionTests(unittest.TestCase):
    """attest's route-field pattern IS keel_plans's, not a second copy of it."""

    def test_attest_field_regex_is_compiled_from_keel_plans_pattern(self) -> None:
        self.assertTrue(hasattr(keel_plans, "ROUTE_LINE_PATTERN"))
        self.assertEqual(
            keel_attest._ROUTE_FIELD_RE.pattern,
            keel_plans.ROUTE_LINE_PATTERN,
            "keel_attest must import keel_plans's pattern text, not hand-type "
            "its own second definition of a Route line",
        )

    def test_keel_plans_presence_check_is_unaffected_by_the_added_group(self) -> None:
        """The class fix must not change what keel_plans.ROUTE_RE finds -
        only what a caller may additionally read from a match."""
        tasks = keel_plans.parse_tasks(
            "- [ ] T1 a task\n"
            "      Route: standard (keel:executor).\n"
            "      Accept: the fixture stays green.\n"
        )
        self.assertTrue(tasks[0].has_route)
        self.assertTrue(tasks[0].has_accept)


class BareRouteLineTests(unittest.TestCase):
    """The bare indented ``Route:`` line this repo's recent ledgers write -
    the exact shape ``attest-parser-misses-contract-ledgers`` names as
    invisible to attest before this fix."""

    def test_bare_route_line_is_read_and_attests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [x] T1 build the thing\n"
                "  Route: executor\n"
                "  Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["route"], "executor")
            self.assertEqual(task["route_kind"], "executor")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])
            self.assertNotIn("UNROUTED", str(report["tasks"]))


class BulletedRouteLineTests(unittest.TestCase):
    """The bulleted ``- Route:`` sub-bullet - the real-world fixture is
    ``.keel/plans/keel-plan-6f7fdee8.md`` - must not regress under the
    shared definition."""

    def test_bulleted_route_line_still_attests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [x] T1 build the thing\n"
                "  - Route: standard (executor); files: some/path.py\n"
                "  - Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["route"], "standard (executor)")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])

    def test_real_world_ledger_6f7fdee8_attests_with_no_unrouted(self) -> None:
        """The actual fixture the earlier supersession was tested on. Every
        task must resolve a route; none may fall through to UNROUTED."""
        plan_path = REPO_ROOT / ".keel" / "plans" / "keel-plan-6f7fdee8.md"
        if not plan_path.is_file():
            self.skipTest("keel-plan-6f7fdee8.md is not present in this checkout")
        tasks = keel_attest.parse_plan(plan_path)
        self.assertTrue(tasks, "expected at least one task in keel-plan-6f7fdee8.md")
        unrouted = [t["id"] for t in tasks if t["route_kind"] == "none"]
        self.assertEqual(unrouted, [], f"tasks with no route resolved: {unrouted}")


class LegacyInlineRouteTests(unittest.TestCase):
    """The legacy ``| route: ... |`` inline field - unaffected by the fix,
    and still tried before the ``Route:`` line fallback."""

    def test_legacy_inline_route_still_attests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp), "- [x] T1: build the thing | route: executor | AC: tests pass\n"
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["route"], "executor")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])

    def test_legacy_shape_quoted_in_a_review_note_is_not_mistaken_for_a_route(
        self,
    ) -> None:
        """The legacy pattern is read on the task's OWN line only. A review
        note that merely QUOTES the ``| route: ... |`` shape as prose - this
        very fix's own ledger does exactly this, describing the class of bug
        it repairs - must never be read as a declared route. Before this
        fix, the flattened whole-block scan let that quoted example resolve
        the route to the literal text between the pipes (``...``)."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [x] T1 build the thing\n"
                "  Route: executor\n"
                "  Note: the legacy inline `| route: ... |` shape still works.\n"
                "  Accept: tests pass\n",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["route"], "executor")
            self.assertEqual(task["verdict"], "ATTESTED")
            self.assertTrue(report["clean"], report["discrepancies"])


class RoutelessTaskOrderingTests(unittest.TestCase):
    """A genuinely routeless task: the verdict-ordering fix at ``verdict_for``.

    ``[x]`` must report UNATTESTED (a discrepancy) rather than being masked
    by the weaker, non-discrepancy UNROUTED verdict; a task that never
    claimed completion has no missing hand-off to hide, so it keeps the
    plain UNROUTED verdict.
    """

    def test_routeless_completed_task_reports_unattested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [x] T1 build the thing, with no route line anywhere in its block\n"
                "  Accept: tests pass\n",
                task_description="something entirely unrelated",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["route_kind"], "none")
            self.assertIn("UNATTESTED", task["verdict"])
            self.assertTrue(keel_attest.is_discrepancy_verdict(task["verdict"]))
            self.assertFalse(report["clean"])
            self.assertIn(task, report["discrepancies"])

    def test_routeless_open_task_is_unrouted_not_unattested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [ ] T1 not started, with no route line anywhere in its block\n"
                "  Accept: tests pass\n",
                task_description="something entirely unrelated",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertEqual(task["verdict"], "UNROUTED (no route declared)")
            self.assertFalse(keel_attest.is_discrepancy_verdict(task["verdict"]))
            self.assertTrue(report["clean"], report["discrepancies"])

    def test_self_routed_completed_task_stays_self_not_unattested(self) -> None:
        """``kind == "self"`` must keep winning ahead of the new marker=='x'
        branch: an orchestrator-routed task has nothing to attest."""
        with tempfile.TemporaryDirectory() as tmp:
            project, session = make_project(
                Path(tmp),
                "- [x] T1 record the decision\n"
                "  Route: orchestrator\n"
                "  Accept: file written\n",
                task_description="something entirely unrelated",
            )
            report = keel_attest.attest(project, session)
            task = report["tasks"][0]
            self.assertTrue(task["verdict"].startswith("SELF"))
            self.assertTrue(report["clean"], report["discrepancies"])


if __name__ == "__main__":
    unittest.main()
