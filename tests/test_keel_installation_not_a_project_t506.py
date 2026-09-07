#!/usr/bin/env python3
"""T506 - a keel INSTALLATION is never a governing project (BL57).

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module, ``scripts/keel_survey.py`` for
          the one existing spelling of the harness's plugin cache, and this
          repository's own arming file in the three read-only cases that pin
          the regression this task must never cause. Every other case builds
          its own fixture home and fixture projects under a temporary
          directory.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED AGAINST A TARGET INSIDE THIS REPOSITORY - the
          rule ``tests/test_keel_target_arming_t178.py`` states and for its
          reason: evaluating a workshop target APPENDS a real
          ``workshop_write`` line to this repository's audit log, which is
          evidence. The repository cases here call ``governance`` and
          ``policy_tier``, which read the filesystem and write nothing.
Argv    : none.

The defect, as the owner measured it on 2026-09-05
---------------------------------------------------
Laying keel into another project refused with ``PLAN GATE (Bash): no fresh
plan for THIS session``, and the refusal named the governing project as the
PLUGIN CACHE, instructing the adopter to write a ledger inside it. The cause
was not the gate's two-source governance (T178, deliberate and correct) but
that an INSTALLED COPY of keel was allowed to be one of those sources: the
marketplace source was ``"./"`` at the time, so an install copied this
repository whole, ``.keel/keel-policy.md`` at ``tier: 2`` included, and every
target inside the cache was judged by keel's own development policy against a
ledger no adopter can have.

The packaging half of that has since changed - T614 (2026-09-06) repointed
the source at the tracked ``dist/keel`` bundle, which carries no ``.keel/``
at all - and none of what this file tests changed with it. The guard is not
about how the arming file got there; it is about a tree in the harness's
cache never being a governing project, whoever armed it and whenever. What
follows is therefore still live behaviour, not a historical record.

What this covers, clause by clause
----------------------------------
1. THE OWNER'S CASE (accept 4). ``TestTheOwnersCase``: a command naming a
   script inside an armed installation is no longer refused on the shipped
   policy - and, so the case is not vacuous, the SAME event still refuses
   when the guard cannot name the cache.
2. NOTHING IS LOOSENED FOR THE SESSION'S OWN WORK (accept 2).
   ``TestTheSessionsOwnProjectStillJudges``: the session's own armed project
   judges the very same command and the very same install target, and its own
   in-project writes are refused exactly as before.
3. KEEL'S OWN REPOSITORY REMAINS GOVERNED (accept 3), which is the regression
   that must never happen. ``TestKeelsOwnRepositoryRemainsGoverned`` pins it
   twice: against this repository itself, and against a fixture that is a
   keel checkout in every respect EXCEPT its location - the test that fails
   the moment the predicate is re-keyed on "the plugin root" or on "looks
   like keel".
4. THE PREDICATE (the shape of the guard). ``TestThePredicate``: what it
   matches, the four things it deliberately does not, and its agreement with
   the one existing spelling of the cache in this project.
5. NO WIDENING. ``TestTheUnattributableStillRefuses``: ``PROJECT_UNKNOWN`` is
   untouched, so a path keel cannot attribute still refuses, inside the cache
   as anywhere else.
6. THE TWO POWERS ARE NOT ONE (the retry, review 2026-09-05).
   ``TestAnInstallationsOwnKernelIsStillRefused`` and
   ``TestTheInstalledKernelPredicate``: what an installation loses is POLICY
   AUTHORITY - its shipped arming file arms nobody - and what it keeps is the
   protection of its OWN KERNEL. The first version demoted both at once, and a
   session in its own armed project with a fresh ledger could rewrite
   ``<install>/hooks/keel_gate.py`` under the generic plan allow; every case in
   clause 6 uses exactly that shape, and one of them neutralises the new rule
   at the production seam so the class can never go vacuous.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names
its encoding.
"""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import is_published_cut  # noqa: E402
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_survey  # noqa: E402

#: A session id of this test's own, so a fixture ledger can never be confused
#: with a real one and no real ledger can ever satisfy a fixture.
SESS8 = "cafe1506"
SESSION = SESS8 + "-0000-0000-0000-000000000000"

#: A contract-clean ledger, so a case that means to exercise arming is never
#: answered by the plan contract instead.
LEDGER_TEXT = (
    "# Plan\n\n- [ ] T1 the thing\n      Route: standard (keel:executor).\n"
    "      Accept: it works.\n"
)

#: The cache path the owner's refusal named, in its parts: the harness's
#: plugin directory, then its cache, a marketplace, the plugin and a version.
#: Spelled as the measurement found it so this fixture is the owner's case
#: rather than a sketch of it.
INSTALL_RELPARTS = (".claude", "plugins", "cache", "policyon", "keel", "0.6.0")


def canonical(path: Path) -> str:
    """A path as the gate spells it: symlink-resolved, and on Windows with
    every 8.3 short component expanded. Temporary directories are handed out
    with a short home component and the gate resolves everything it reasons
    about, so a raw fixture path would compare two spellings of one
    directory."""
    return str(Path(os.path.realpath(str(path))))


@contextlib.contextmanager
def home_at(home: Path) -> Iterator[Path]:
    """Point this process's home directory at a fixture for one block.

    Both spellings are set, and the Windows pair that ``expanduser`` falls
    back to is removed, so ``Path.home()`` cannot reach the real home on
    either platform - the same discipline ``tests/keel_registry_guard.py``
    applies for keel's user-global directory, and for the same reason: a test
    that reads the real one is a test that can write it.
    """
    keys = ("HOME", "USERPROFILE", "HOMEDRIVE", "HOMEPATH")
    previous = {key: os.environ.get(key) for key in keys}
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ.pop("HOMEDRIVE", None)
    os.environ.pop("HOMEPATH", None)
    try:
        yield home
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def armed(project: Path, *, tier: int = 2, plan: bool = False) -> Path:
    """A fixture project whose arming file declares ``tier``."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n\n# keel policy - fixture project\n",
        encoding="utf-8",
    )
    if plan:
        path = project / ".keel" / "plans" / f"keel-plan-{SESS8}.md"
        path.write_text(LEDGER_TEXT, encoding="utf-8")
    return project


def installation(home: Path, *, plan: bool = False) -> Path:
    """An installed copy of keel in the harness's cache under ``home``.

    It carries what an install actually carries: the plugin manifest, the hook
    manifest that registers the gates, and the ``.keel/`` the marketplace
    source copies wholesale - arming file at tier 2 included.
    """
    tree = home.joinpath(*INSTALL_RELPARTS)
    (tree / "scripts").mkdir(parents=True, exist_ok=True)
    (tree / "scripts" / "keel.py").write_text("# keel CLI\n", encoding="utf-8")
    return checkout(tree, plan=plan)


def checkout(tree: Path, *, plan: bool = False) -> Path:
    """A keel tree in every respect except where it lives: manifest, hooks and
    an armed record. Used both inside the cache and outside it, because the
    difference between the two is exactly what this task's guard turns on."""
    (tree / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (tree / ".claude-plugin" / "plugin.json").write_text(
        '{"name": "keel", "version": "0.6.0"}\n', encoding="utf-8"
    )
    (tree / "hooks").mkdir(parents=True, exist_ok=True)
    (tree / "hooks" / "hooks.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    (tree / "scripts").mkdir(parents=True, exist_ok=True)
    (tree / "scripts" / "keel.py").write_text("# keel CLI\n", encoding="utf-8")
    return armed(tree, plan=plan)


def write_event(cwd: Path, *paths: str) -> keel_events.KeelEvent:
    """One ``pre_write`` event, from ``cwd``, naming one or more targets."""
    return keel_events.KeelEvent(
        kind="pre_write",
        cwd=cwd,
        session_id=SESSION,
        tool_name="Write",
        raw={"tool_input": {"file_path": paths[0], "content": "x = 1\n"}},
        file_paths=tuple(paths),
    )


def exec_event(cwd: Path, command: str) -> keel_events.KeelEvent:
    """One ``pre_exec`` event, from ``cwd``, carrying command text."""
    return keel_events.KeelEvent(
        kind="pre_exec",
        cwd=cwd,
        session_id=SESSION,
        tool_name="Bash",
        raw={"tool_input": {"command": command}},
        command=command,
    )


class TestTheOwnersCase(unittest.TestCase):
    """Accept 4: the measurement, as an assertion.

    The adopter's project has NOT adopted keel - they were in the act of
    laying it - so the only project in sight is the installed copy, and
    before this guard that copy refused them.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "userhome"
        self.project = root / "adopter"
        (self.home).mkdir()
        (self.project).mkdir()
        with home_at(self.home):
            self.install = installation(self.home)
        self.command = f"python {self.install / 'scripts' / 'keel.py'} survey"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_the_shipped_policy_is_armed_which_is_what_made_this_bite(self) -> None:
        """The fixture is the defect's premise, asserted rather than assumed:
        an install really does carry an enforcing arming file."""
        self.assertEqual(keel_gate.policy_tier(self.install), 2)
        self.assertTrue(keel_gate.is_armed(self.install))

    def test_the_survey_command_is_no_longer_refused(self) -> None:
        with home_at(self.home):
            verdict = keel_gate.evaluate(exec_event(self.project, self.command), env={})
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_the_installation_is_not_a_governing_project(self) -> None:
        with home_at(self.home):
            decided = keel_gate.governance(exec_event(self.project, self.command))
        roots = [str(root) for root, _targets in decided.projects]
        self.assertNotIn(canonical(self.install), roots)
        self.assertEqual(roots, [], "an unadopted session has no project either")

    def test_the_same_command_still_refuses_when_the_cache_cannot_be_named(self) -> None:
        """THE CASE IS NOT VACUOUS. ``install_cache_root`` answers "" on a
        machine where keel cannot locate the cache, and that answer excludes
        nothing - so this is the pre-guard behaviour, reachable through the
        production seam, and it is the refusal the owner saw: the plan gate,
        naming the plugin cache as the governing project."""
        original = keel_gate.install_cache_root
        keel_gate.install_cache_root = lambda: ""
        try:
            with home_at(self.home):
                verdict = keel_gate.evaluate(
                    exec_event(self.project, self.command), env={}
                )
        finally:
            keel_gate.install_cache_root = original
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "plan")
        self.assertEqual(verdict.detail.get("project"), canonical(self.install))
        self.assertIn("GOVERNING PROJECT", verdict.reason)

    def test_a_ledger_in_the_cache_was_never_the_way_out(self) -> None:
        """The remedy the refusal named is one an adopter must not perform, so
        the fix is not "let them write it": the command clears with NO ledger
        anywhere in the cache."""
        with home_at(self.home):
            verdict = keel_gate.evaluate(exec_event(self.project, self.command), env={})
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(
            list((self.install / ".keel" / "plans").glob("keel-plan-*.md")),
            [],
            "no ledger was written into the plugin cache to obtain that allow",
        )

    def test_an_ordinary_write_into_the_installation_is_not_judged_by_it(self) -> None:
        """The write half of accept 1, AND ONLY THE WRITES THE DEMOTION IS
        ABOUT. The shipped policy would have judged every target inside the
        cache by keel's own development rules; an installation governs nothing,
        so an ordinary file inside it is answered by the session (here,
        unadopted: nobody). The install's KERNEL is a different question, asked
        by ``TestAnInstallationsOwnKernelIsStillRefused`` below - this case was
        written against ``hooks/keel_gate.py`` and so proved the demotion by
        asserting the one write that must never be permitted (review,
        2026-09-05)."""
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(self.project, str(self.install / "notes.txt")),
                env={},
            )
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)


class TestTheSessionsOwnProjectStillJudges(unittest.TestCase):
    """Accept 2, and the direction this whole task fails in: the guard removes
    a JUDGE that came from a shipped file, and nothing else.

    Every case here runs with the same fixture home and the same armed
    installation as the owner's case - so if the guard had reached one step
    too far, these are the assertions that would go quiet.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "userhome"
        self.project = root / "adopter"
        self.home.mkdir()
        self.project.mkdir()
        with home_at(self.home):
            self.install = installation(self.home)
        self.command = f"python {self.install / 'scripts' / 'keel.py'} survey"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_an_armed_session_still_needs_its_own_ledger_for_that_command(self) -> None:
        armed(self.project, plan=False)
        with home_at(self.home):
            verdict = keel_gate.evaluate(exec_event(self.project, self.command), env={})
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "plan")
        self.assertEqual(
            verdict.detail.get("project", canonical(self.project)),
            canonical(self.project),
            "the session's OWN project is the one that refused",
        )

    def test_an_armed_session_with_a_ledger_runs_it(self) -> None:
        armed(self.project, plan=True)
        with home_at(self.home):
            verdict = keel_gate.evaluate(exec_event(self.project, self.command), env={})
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "plan")

    def test_an_armed_session_still_judges_a_write_into_the_installation(self) -> None:
        armed(self.project, plan=False)
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(self.project, str(self.install / "notes.txt")), env={}
            )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "plan")

    def test_a_write_inside_the_sessions_own_armed_project_is_refused_as_today(self) -> None:
        """Named separately from the loop below because it is the sentence the
        acceptance criterion uses: nothing is loosened for the session's own
        work."""
        armed(self.project, plan=False)
        with home_at(self.home):
            verdict = keel_gate.evaluate(write_event(self.project, "src/app.py"), env={})
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "plan")

    def test_the_lock_over_the_sessions_own_project_is_unchanged(self) -> None:
        armed(self.project, plan=True)
        for relpath in ("hooks/kernel.py", ".keel/keel-policy.md", ".claude/settings.json"):
            with self.subTest(target=relpath):
                with home_at(self.home):
                    verdict = keel_gate.evaluate(
                        write_event(self.project, relpath), env={}
                    )
                self.assertEqual(verdict.decision, "deny", verdict.reason)
                self.assertEqual(verdict.gate, "policy_lock")

    def test_a_foreign_armed_project_still_judges_its_own_target(self) -> None:
        """T178's fix, untouched: the guard drops installations, not foreign
        projects."""
        other = armed(Path(self._tmp.name) / "other", plan=False)
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(self.project, str(other / "src" / "app.py")), env={}
            )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "plan")
        self.assertEqual(verdict.detail.get("project"), canonical(other))


#: The kernel paths of an installed tree, project-relative, spelled the way a
#: payload would spell them. Kept as one list because every case below asks the
#: same question of each of them, and a path that quietly stopped being asked
#: about is exactly the shape this class exists to catch.
KERNEL_RELPATHS = (
    "hooks/keel_gate.py",
    "hooks/nested/deeper.py",
    ".keel/keel-policy.md",
    ".claude-plugin/plugin.json",
    ".claude/settings.json",
    ".keel/settings.json",
)


class TestAnInstallationsOwnKernelIsStillRefused(unittest.TestCase):
    """THE TWO POWERS, SEPARATED - the finding this module's first version
    failed on (review 2026-09-05, silent failure, 85%).

    Demoting an installed tree out of ``governance`` removed BOTH the copy's
    POLICY AUTHORITY (right: its shipped arming file may not judge an adopter,
    BL57) and keel's refusal to let a session edit an installed copy's OWN
    KERNEL (wrong: with the install no longer a project, ``is_protected`` was
    never asked about its ``hooks/`` at all, and a session in its own armed
    project with a FRESH LEDGER rewrote the gates binding it under the generic
    plan allow).

    Every case here uses the shape that slipped through - armed session, fresh
    ledger, nothing else refusing - because a session that is unarmed or
    ledgerless is refused for a reason that has nothing to do with this rule
    and would prove nothing about it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.home = root / "userhome"
        self.project = root / "adopter"
        self.home.mkdir()
        self.project.mkdir()
        with home_at(self.home):
            self.install = installation(self.home)
        armed(self.project, plan=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _verdict(self, relpath: str, env: dict[str, str] | None = None):
        with home_at(self.home):
            return keel_gate.evaluate(
                write_event(self.project, str(self.install / relpath)),
                env={} if env is None else env,
            )

    def test_the_session_really_is_armed_with_a_fresh_ledger(self) -> None:
        """The premise, asserted rather than assumed: nothing else in this
        class's fixture is capable of refusing these writes."""
        self.assertEqual(keel_gate.policy_tier(self.project), 2)
        verdict = self._verdict("notes.txt")
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "plan", "the ledger is fresh for this session")

    def test_every_kernel_path_of_the_installation_is_refused(self) -> None:
        for relpath in KERNEL_RELPATHS:
            with self.subTest(target=relpath):
                verdict = self._verdict(relpath)
                self.assertEqual(verdict.decision, "deny", verdict.reason)
                self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)
                self.assertIn("KEEL INSTALLATION KERNEL", verdict.reason)

    def test_the_refusal_names_the_door_and_the_guardrail(self) -> None:
        verdict = self._verdict("hooks/keel_gate.py")
        self.assertIn("KEEL_OVERRIDE=on", verdict.reason)
        self.assertIn("(Guardrail: installed-kernel.)", verdict.reason)

    def test_without_the_rule_the_same_write_falls_straight_through(self) -> None:
        """THE CASE IS NOT VACUOUS, and this is the defect itself, pinned. With
        the rule neutralised at the production seam the write is not refused by
        anyone - it is answered by the session's own fresh ledger and permitted
        - which is exactly what shipped after T506's first attempt: a session
        rewriting ``hooks/keel_gate.py`` of the installation running it."""
        original = keel_gate.installed_kernel_write
        keel_gate.installed_kernel_write = lambda event: ""
        try:
            verdict = self._verdict("hooks/keel_gate.py")
        finally:
            keel_gate.installed_kernel_write = original
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "plan")

    def test_an_unarmed_session_is_refused_too(self) -> None:
        """No project decides this rule, so it does not need one. A session in a
        directory that never adopted keel is refused the same write."""
        other = Path(self._tmp.name) / "unadopted"
        other.mkdir()
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(other, str(self.install / "hooks" / "keel_gate.py")), env={}
            )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_session_standing_inside_the_installation_is_refused_too(self) -> None:
        """The confirmed-sound property, kept: a session that stands in an
        installed tree is not excused, and now cannot edit that tree's kernel
        from inside it either."""
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(self.install, "hooks/keel_gate.py"), env={}
            )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_the_users_override_carries_it_and_is_recorded(self) -> None:
        """It COMPOSES, it does not absorb - the treatment the lock and THE
        GLOBAL RULE both give the override, and the reach this protection had
        before the demotion (the install's own tier-2 lock, which the same
        switch carried)."""
        verdict = self._verdict("hooks/keel_gate.py", env={"KEEL_OVERRIDE": "on"})
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "plan", "it falls through to the plan gate")
        log = (self.project / ".keel" / "audit" / "keel-audit.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertIn("gate_bypass", log)
        self.assertIn(keel_gate.INSTALL_KERNEL_GATE, log)

    def test_a_command_is_not_the_write_halfs_business(self) -> None:
        """THIS CLASSIFIER IS THE WRITE HALF, and stays so.

        CORRECTED AT T507, because the claim this docstring used to carry
        ("a command naming a path inside the cache is untouched by this rule")
        stopped being true: a MUTATING command at one of those kernel paths is
        now refused by ``installed_kernel_command``, the sibling classifier,
        after the silent-failure review found that a session with no governing
        project reached no evaluator at all and could ``sed -i`` the running
        gate. What survives unchanged is the SPLIT - a write declares its
        target and is judged exactly, a command is a heuristic over tokens -
        and BL57's own case, which is pinned in both directions by
        ``test_the_owners_case_still_clears_with_this_rule_in_place`` here and
        by ``TestTheOwnersCaseIsUntouched`` in the T507 module."""
        with home_at(self.home):
            self.assertEqual(
                keel_gate.installed_kernel_write(
                    exec_event(self.project, f"python {self.install / 'hooks' / 'x.py'}")
                ),
                "",
            )

    def test_the_owners_case_still_clears_with_this_rule_in_place(self) -> None:
        """Accept 1, re-asserted against THIS fixture: the command the owner
        measured is not refused, and no ledger inside the cache is asked for."""
        unadopted = Path(self._tmp.name) / "laying-keel"
        unadopted.mkdir()
        command = f"python {self.install / 'scripts' / 'keel.py'} survey"
        with home_at(self.home):
            verdict = keel_gate.evaluate(exec_event(unadopted, command), env={})
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)


class TestTheInstalledKernelPredicate(unittest.TestCase):
    """``installed_kernel_root``: what it names as an installation's kernel,
    and the places it must stay silent - each one a direction in which this
    rule would either disarm keel or re-create BL57."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "userhome"
        self.home.mkdir()
        self.cache = self.home / ".claude" / "plugins"
        self.cache.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _root_of(self, path: Path) -> str:
        with home_at(self.home):
            return keel_gate.installed_kernel_root(keel_gate.norm(self.root, str(path)))

    def test_it_names_the_installation_the_kernel_path_belongs_to(self) -> None:
        install = self.home.joinpath(*INSTALL_RELPARTS)
        self.assertEqual(
            self._root_of(install / "hooks" / "keel_gate.py"),
            canonical(install).casefold(),
        )

    def test_the_nesting_depth_of_the_cache_is_not_assumed(self) -> None:
        """The harness's layout is its own business, so the candidate roots are
        every directory between the target and the cache."""
        for parts in ((".claude", "plugins", "plug"), INSTALL_RELPARTS):
            with self.subTest(depth=len(parts)):
                install = self.home.joinpath(*parts)
                self.assertEqual(
                    self._root_of(install / "hooks" / "x.py"),
                    canonical(install).casefold(),
                )

    def test_the_spelling_of_the_directory_is_casefolded(self) -> None:
        install = self.home.joinpath(*INSTALL_RELPARTS)
        self.assertTrue(self._root_of(install / "HOOKS" / "Keel_Gate.py"))

    def test_an_ordinary_file_inside_an_installation_is_not_kernel(self) -> None:
        install = self.home.joinpath(*INSTALL_RELPARTS)
        for relpath in ("notes.txt", "src/app.py", "scripts/keel.py", ".keel/plans/p.md"):
            with self.subTest(target=relpath):
                self.assertEqual(self._root_of(install / relpath), "")

    def test_a_kernel_shaped_path_directly_in_the_cache_is_not_one(self) -> None:
        """STRICTLY beneath, ``is_installed_tree``'s rule kept: the cache
        directory is not a tree the harness installed, so there is no install
        whose kernel ``<cache>/hooks/x.py`` could be."""
        self.assertEqual(self._root_of(self.cache / "hooks" / "x.py"), "")
        self.assertEqual(self._root_of(self.cache), "")

    def test_nothing_outside_the_cache_is_touched(self) -> None:
        """The direction that would disarm keel: a development checkout's
        ``hooks/`` is a PROJECT's locked path, judged by that project, and this
        rule must have no opinion about it at all."""
        development = checkout(self.root / "dev" / "keel")
        self.assertEqual(self._root_of(development / "hooks" / "keel_gate.py"), "")
        project = self.root / "work" / "app"
        (project / ".claude" / "plugins" / "thing").mkdir(parents=True)
        self.assertEqual(
            self._root_of(project / ".claude" / "plugins" / "thing" / "hooks" / "x.py"),
            "",
            "a project's own .claude/plugins directory is not the harness's cache",
        )

    def test_this_repository_is_not_an_installations_kernel(self) -> None:
        """Accept 3, in this rule's own terms and against the REAL home: keel's
        own ``hooks/`` is protected by keel's own arming file, not by this."""
        self.assertEqual(
            keel_gate.installed_kernel_root(
                keel_gate.norm(REPO_ROOT, str(REPO_ROOT / "hooks" / "keel_gate.py"))
            ),
            "",
        )

    def test_no_cache_root_protects_nothing_and_governs_as_before(self) -> None:
        """The failure direction, stated: a machine where keel cannot name the
        cache has no installation to protect, and every project keeps the lock
        it always had."""
        install = self.home.joinpath(*INSTALL_RELPARTS)
        with home_at(self.home):
            target = keel_gate.norm(self.root, str(install / "hooks" / "x.py"))
        self.assertEqual(keel_gate.installed_kernel_root(target, cache_root=""), "")

    def test_an_unresolvable_target_is_not_this_rules_business(self) -> None:
        """"" is a path that would not resolve - refused by UNVERIFIABLE IS DENY
        under its own name, never by this one."""
        with home_at(self.home):
            self.assertEqual(keel_gate.installed_kernel_root(""), "")

    def test_the_kernel_set_is_the_locked_set_and_is_not_re_typed(self) -> None:
        """R15: the paths keel refuses to let a project rewrite in itself are
        the paths it refuses to let a session rewrite in an installation."""
        self.assertEqual(
            keel_gate._INSTALL_KERNEL_FILES,
            tuple(
                tuple(segment.casefold() for segment in parts)
                for parts in keel_gate.PROTECTED_FILES
            ),
        )
        self.assertEqual(
            keel_gate._INSTALL_KERNEL_DIRS,
            tuple(
                tuple(segment.casefold() for segment in parts)
                for parts in keel_gate.PROTECTED_DIRS
            ),
        )


class TestKeelsOwnRepositoryRemainsGoverned(unittest.TestCase):
    """Accept 3 - the regression that must never happen, pinned two ways.

    keel is developed in the tree it ships: this repository's own plugin
    registration resolves to ``<repo>/hooks/hooks.json``, and
    ``CLAUDE_PLUGIN_ROOT`` for a session governed by it points here. A guard
    keyed on "the plugin root" would therefore disarm keel exactly where it is
    developed - silently, with every other test still green. These are the
    assertions that would fail if the guard ever caught this tree.
    """

    def test_this_repository_is_still_armed_at_tier_2(self) -> None:
        """INVERTS IN A PUBLISHED CUT, which ships no arming file - the shipped
        property, asserted rather than skipped."""
        if is_published_cut(REPO_ROOT):
            self.assertIsNone(keel_gate.policy_tier(REPO_ROOT))
            return
        self.assertEqual(keel_gate.policy_tier(REPO_ROOT), 2)
        self.assertTrue(keel_gate.is_armed(REPO_ROOT))

    def test_this_repository_is_not_an_installation(self) -> None:
        """Asked against the REAL home directory, because that is the premise:
        a development checkout does not live in the harness's cache."""
        self.assertFalse(keel_gate.is_installed_tree(REPO_ROOT))
        self.assertFalse(keel_gate.is_installed_tree(REPO_ROOT / "hooks"))

    def test_a_target_in_this_repository_is_still_governed_by_it(self) -> None:
        """The load-bearing one. A session standing ELSEWHERE names a file of
        this repository: the repository must still be a governing project.
        ``governance`` reads the filesystem and writes nothing, so no verdict
        is evaluated and no audit line is appended."""
        if is_published_cut(REPO_ROOT):
            self.skipTest("no arming file in a published cut; covered by the case above")
        with tempfile.TemporaryDirectory() as tmp:
            event = write_event(Path(tmp), str(REPO_ROOT / "hooks" / "keel_gate.py"))
            decided = keel_gate.governance(event)
        roots = [str(root) for root, _targets in decided.projects]
        self.assertIn(str(REPO_ROOT), roots, "keel stopped governing its own repository")

    def test_the_plugin_root_variable_changes_nothing(self) -> None:
        """``CLAUDE_PLUGIN_ROOT`` is the value the obvious wrong guard would
        have used. Setting it to this repository must change no answer, and
        the way to prove that is to set it."""
        if is_published_cut(REPO_ROOT):
            self.skipTest("no arming file in a published cut")
        previous = os.environ.get("CLAUDE_PLUGIN_ROOT")
        os.environ["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                event = write_event(Path(tmp), str(REPO_ROOT / "hooks" / "keel_gate.py"))
                decided = keel_gate.governance(event)
        finally:
            if previous is None:
                os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
            else:
                os.environ["CLAUDE_PLUGIN_ROOT"] = previous
        roots = [str(root) for root, _targets in decided.projects]
        self.assertIn(str(REPO_ROOT), roots)
        self.assertFalse(keel_gate.is_installed_tree(REPO_ROOT))

    def test_a_development_checkout_governs_and_the_same_tree_in_the_cache_does_not(self) -> None:
        """ONE PAIR, IDENTICAL CONTENT, TWO LOCATIONS - the test that fails the
        moment someone re-keys the predicate on "it is a plugin root" or "it
        looks like keel". Both trees carry a plugin manifest, a hook manifest
        and an arming file at tier 2; only their addresses differ.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "userhome"
            home.mkdir()
            session = root / "elsewhere"
            session.mkdir()
            development = checkout(root / "dev" / "keel")
            with home_at(home):
                installed = installation(home)
                governing = keel_gate.evaluate(
                    write_event(session, str(development / "src" / "app.py")), env={}
                )
                excused = keel_gate.evaluate(
                    write_event(session, str(installed / "src" / "app.py")), env={}
                )
        self.assertEqual(governing.decision, "deny", governing.reason)
        self.assertEqual(governing.gate, "plan")
        self.assertEqual(governing.detail.get("project"), canonical(development))
        self.assertEqual(excused.decision, "allow", excused.reason)
        self.assertEqual(excused.gate, "unarmed")


class TestThePredicate(unittest.TestCase):
    """What ``is_installed_tree`` matches, and the four things it deliberately
    does not. Each non-match is a place a wider guard would have gone silent.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.home = self.root / "userhome"
        self.home.mkdir()
        self.cache = self.home / ".claude" / "plugins"
        self.cache.mkdir(parents=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_an_installed_tree_and_everything_under_it_match(self) -> None:
        with home_at(self.home):
            tree = self.home.joinpath(*INSTALL_RELPARTS)
            tree.mkdir(parents=True, exist_ok=True)
            self.assertTrue(keel_gate.is_installed_tree(tree))
            self.assertTrue(keel_gate.is_installed_tree(tree / "scripts"))
            self.assertTrue(keel_gate.is_installed_tree(self.cache / "cache"))

    def test_the_cache_directory_itself_is_not_an_installation(self) -> None:
        """STRICTLY beneath: the harness's plugin directory is not a tree the
        harness installed, and demoting it would be this guard deciding about
        a directory nobody has shown it anything about."""
        with home_at(self.home):
            self.assertFalse(keel_gate.is_installed_tree(self.cache))

    def test_a_sibling_that_merely_shares_the_spelling_does_not_match(self) -> None:
        neighbour = self.home / ".claude" / "plugins-old" / "keel"
        neighbour.mkdir(parents=True)
        with home_at(self.home):
            self.assertFalse(keel_gate.is_installed_tree(neighbour))

    def test_keels_user_global_directory_does_not_match(self) -> None:
        """The other ``.claude/`` directory keel knows about is not this one."""
        user_global = self.home / ".claude" / "keel"
        user_global.mkdir(parents=True)
        with home_at(self.home):
            self.assertFalse(keel_gate.is_installed_tree(user_global))

    def test_a_projects_own_claude_plugins_directory_does_not_match(self) -> None:
        """The comparison is ONE absolute path under this user's home, never a
        scan for those two segments wherever they appear - so a project that
        carries the same directory name is untouched."""
        project = self.root / "work" / "app"
        (project / ".claude" / "plugins" / "thing").mkdir(parents=True)
        with home_at(self.home):
            self.assertFalse(keel_gate.is_installed_tree(project / ".claude" / "plugins"))
            self.assertFalse(
                keel_gate.is_installed_tree(project / ".claude" / "plugins" / "thing")
            )

    def test_a_project_elsewhere_under_the_home_directory_does_not_match(self) -> None:
        project = self.home / "Projects" / "app"
        project.mkdir(parents=True)
        with home_at(self.home):
            self.assertFalse(keel_gate.is_installed_tree(project))

    def test_no_cache_root_excludes_nothing(self) -> None:
        """The failure direction, stated as a test: a machine where keel cannot
        name the cache keeps governing everything it governed before."""
        tree = self.home.joinpath(*INSTALL_RELPARTS)
        tree.mkdir(parents=True, exist_ok=True)
        self.assertFalse(keel_gate.is_installed_tree(tree, cache_root=""))

    def test_the_cache_root_is_resolved_and_casefolded(self) -> None:
        with home_at(self.home):
            root = keel_gate.install_cache_root()
        self.assertEqual(root, canonical(self.cache).casefold())

    def test_the_spelling_agrees_with_the_one_this_project_already_had(self) -> None:
        """R15: the cache is named ONCE. ``scripts/keel_survey.py`` finds
        installed plugins under these same two segments and opens the
        harness's install record inside them; a drift between the two would be
        a guard pointed at a directory nothing else uses."""
        self.assertEqual(
            keel_gate.INSTALL_CACHE_RELPATH,
            keel_survey.INSTALL_RECORD_RELPATH[:2],
        )
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            base = home.joinpath(*keel_gate.INSTALL_CACHE_RELPATH)
            base.mkdir(parents=True)
            (base / "plug" / "hooks").mkdir(parents=True)
            (base / "plug" / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
            found = keel_survey.plugin_manifests(home)
        self.assertEqual(
            [str(path) for path in found],
            [str(base / "plug" / "hooks" / "hooks.json")],
            "the survey looks for installs somewhere this guard does not",
        )


class TestTheUnattributableStillRefuses(unittest.TestCase):
    """The constraint: ``PROJECT_UNKNOWN`` is not weakened. A path keel cannot
    attribute is not a path keel has excused, and that holds inside the cache
    as anywhere else - the demotion only ever touches a resolution that FOUND
    a root."""

    def test_an_unknown_resolution_passes_through_untouched(self) -> None:
        self.assertEqual(
            keel_gate._not_an_installation(keel_gate.UNKNOWN_PROJECT, "").state,
            keel_gate.PROJECT_UNKNOWN,
        )
        self.assertEqual(
            keel_gate._not_an_installation(keel_gate.ABSENT_PROJECT, "").state,
            keel_gate.PROJECT_ABSENT,
        )

    def test_a_target_too_deep_in_the_cache_to_attribute_still_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "userhome"
            home.mkdir()
            project = armed(root / "adopter", plan=True)
            with home_at(home):
                install = installation(home)
                deep = install.joinpath(
                    *[f"d{level}" for level in range(keel_gate.PROJECT_WALK_MAX_LEVELS + 2)]
                )
                verdict = keel_gate.evaluate(
                    write_event(project, str(deep / "app.py")), env={}
                )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, "unresolved_project")


class TestTheDeclarationMatchesTheBehaviour(unittest.TestCase):
    """R3/R15: what the module says about installations is what it does."""

    def test_the_module_declares_the_rule(self) -> None:
        doc = (keel_gate.__doc__ or "").upper()
        self.assertIn("A KEEL INSTALLATION", doc)

    def test_the_predicate_states_what_it_does_not_match(self) -> None:
        doc = keel_gate.is_installed_tree.__doc__ or ""
        self.assertIn("CLAUDE_PLUGIN_ROOT", doc)
        self.assertIn("DOES NOT MATCH", doc.upper())

    def test_the_governance_docstring_states_the_session_is_not_filtered(self) -> None:
        doc = (keel_gate.governance.__doc__ or "").upper()
        self.assertIn("THE SESSION'S OWN WALK IS NOT FILTERED", doc)

    def test_the_module_declares_the_installed_kernel_rule(self) -> None:
        """The rule that is not a project's is declared where the other one is,
        because a refusal no reader of the module can find is a surprise."""
        doc = (keel_gate.__doc__ or "").upper()
        self.assertIn("THE INSTALLED-KERNEL RULE", doc)

    def test_the_demotion_says_what_it_does_not_take_away(self) -> None:
        """R3: the comment that justified the demotion must not still claim the
        installation is left with nothing - it is left without POLICY
        AUTHORITY, and keeps the protection of its own kernel."""
        doc = (keel_gate._not_an_installation.__doc__ or "").upper()
        self.assertIn("POLICY AUTHORITY", doc)
        self.assertIn("INSTALLED-KERNEL RULE", doc)

    def test_the_predicate_states_the_two_powers(self) -> None:
        doc = (keel_gate.installed_kernel_root.__doc__ or "").upper()
        self.assertIn("POLICY AUTHORITY", doc)
        self.assertIn("OWN KERNEL", doc)

    def test_the_rule_is_on_the_preflight_path(self) -> None:
        """A half-applied edit that deletes the classifier must fail the
        preflight rather than silently unprotect every installation."""
        self.assertIn("installed_kernel_write", keel_gate.EVALUATION_PATH_SYMBOLS)


if __name__ == "__main__":
    unittest.main()
