#!/usr/bin/env python3
"""T507 - a MUTATING COMMAND at an installation's kernel is refused too.

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module, and the T506 module beside this
          one for the fixture vocabulary the two tasks share (``home_at``,
          ``installation``, ``checkout``, ``armed``, ``exec_event``,
          ``write_event``, ``KERNEL_RELPATHS``). Only NAMED helpers are
          imported: a star import would make unittest discovery run T506's
          own cases a second time under this module's name.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
          NOTHING IS EVALUATED AGAINST A TARGET INSIDE THIS REPOSITORY, the
          rule ``tests/test_keel_target_arming_t178.py`` states and for its
          reason: evaluating a workshop target APPENDS a real audit line to
          this repository's own log, which is evidence. Criterion 4 ("keel's
          own repository is not an installation") is pinned here against a
          keel CHECKOUT built in a temporary directory instead - the same
          fixture T506 uses, and the stronger test, because it differs from
          an installation in nothing but its location.
Argv    : none.

The defect, as the silent-failure review of T506 stated it (85%)
----------------------------------------------------------------
T506 restored the refusal of a WRITE into an installed copy's own kernel,
and guarded ``pre_write`` ONLY. For a ``pre_exec`` event the installed tree
is demoted to ABSENT by ``_not_an_installation`` and never enters
``governance``'s project list, so a session with no governing project of its
own reaches ``if not projects: return allow(UNARMED_REASON)`` - and

    sed -i 's/return "deny"/return "allow"/' <install>/hooks/keel_gate.py

rewrote the verdict of the gate that was judging it, with no deny, no bypass
line and no audit row. That is BL57's shape reopened through commands, in
exactly the unarmed fresh-adopter state T506 exists for; before T506 the
install's own tier-2 arming file judged it (and, having no ledger, refused
it), so it is a regression T506 introduced rather than a pre-existing gap.

What this covers, clause by clause
----------------------------------
1. THE REPRODUCTION (accept 1). ``TestTheReviewersReproduction``: the exact
   command above, from a session that governs nothing, is refused under
   ``gate='installed_kernel'`` - and one case neutralises the new classifier
   at the production seam, so the class can never go vacuous and the
   pre-fix behaviour stays pinned as the thing that changed.
2. THE OWNER'S CASE IS UNTOUCHED (accept 2). ``TestTheOwnersCaseIsUntouched``:
   BL57's documented first step still clears, and no ledger inside the plugin
   cache is asked for. POLICY AUTHORITY STAYS DEMOTED - the install's arming
   file, tier, lock and ledger are read by nothing in this rule.
3. WHAT THE RULE DOES NOT REACH (accept 3, accept 4).
   ``TestWhatThisRuleDoesNotReach``: a mutating command at an ORDINARY file
   inside the installation, a mutating command at a keel checkout OUTSIDE the
   cache, and a plainly read-only command at the kernel itself.
4. THE MUTATION NOTION IS THIS FILE'S OWN (the constraint).
   ``TestTheMutationNotionIsThisFilesOwn``: the command half is
   ``_shell_hits`` in its CLOSED mode - the same body, the same allowlist and
   the same ``cd`` taint the policy lock and THE GLOBAL RULE already run -
   and not a second notion of "mutating" invented beside it.
5. THE OVERRIDE COMPOSES (the boundary the write half holds).
   ``TestTheOverrideComposes``: the user's switch carries the command, one
   ``gate_bypass`` line is written under THIS rule's name, and the event
   falls through to the plan gate.
6. THE WRITE HALF IS UNCHANGED (accept 5). ``TestTheWriteHalfIsUnchanged``:
   every kernel path is still refused as a write, and
   ``installed_kernel_write`` still answers "" for a command - it remains the
   write half, with the command half its own function beside it.
7. THE DECLARATION MATCHES THE BEHAVIOUR (R3).
   ``TestTheDeclarationMatchesTheBehaviour``: the module prose no longer
   claims the rule is write-only, and the new classifier is on the preflight
   path, so a half-applied edit that deletes it fails loudly.

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
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import keel_gate  # noqa: E402

from test_keel_installation_not_a_project_t506 import (  # noqa: E402
    KERNEL_RELPATHS,
    armed,
    checkout,
    exec_event,
    home_at,
    installation,
    write_event,
)

#: The reviewer's command, verbatim in shape: it rewrites the gate's own
#: verdict. Anything weaker would prove less than the finding claimed.
REPRO = "sed -i 's/return \"deny\"/return \"allow\"/' {target}"


class _Fixture(unittest.TestCase):
    """A home with an installed copy of keel in the harness's cache, an
    UNADOPTED directory to run from, and an armed project for the one case
    that needs an audit log to inspect.

    The unadopted directory is the whole point: it is the state the finding
    was reported in, and the state in which ``evaluate`` returns early at
    ``if not projects`` - so a rule that only fires inside a project's
    evaluation cannot possibly be doing the refusing here.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        self.home = root / "userhome"
        self.unadopted = root / "laying-keel"
        self.adopter = root / "adopter"
        self.home.mkdir()
        self.unadopted.mkdir()
        self.adopter.mkdir()
        with home_at(self.home):
            self.install = installation(self.home)
        (self.install / "notes.txt").write_text("just a file\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def kernel(self, relpath: str = "hooks/keel_gate.py") -> str:
        return str(self.install.joinpath(*relpath.split("/")))

    def verdict(self, command: str, cwd: Path | None = None, env=None):
        with home_at(self.home):
            return keel_gate.evaluate(
                exec_event(self.unadopted if cwd is None else cwd, command),
                env={} if env is None else env,
            )


class TestTheReviewersReproduction(_Fixture):
    """Accept 1: the finding, as an assertion."""

    def test_the_session_really_governs_nothing(self) -> None:
        """The premise, asserted rather than assumed: this is the early-return
        state. If some project were governing here, a refusal would prove
        nothing about the rule under test."""
        with home_at(self.home):
            decided = keel_gate.governance(exec_event(self.unadopted, REPRO.format(target=self.kernel())))
        self.assertEqual(
            [str(root) for root, _targets in decided.projects],
            [],
            "the installation must not be a governing project, and the "
            "session has none of its own",
        )

    def test_the_mutating_command_at_the_kernel_is_refused(self) -> None:
        verdict = self.verdict(REPRO.format(target=self.kernel()))
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE, verdict.reason)
        self.assertIn("KEEL INSTALLATION KERNEL", verdict.reason)
        self.assertIn("(Guardrail: installed-kernel.)", verdict.reason)
        self.assertIn("KEEL_OVERRIDE=on", verdict.reason)

    def test_every_kernel_path_is_refused_by_a_mutating_command(self) -> None:
        for relpath in KERNEL_RELPATHS:
            with self.subTest(target=relpath):
                verdict = self.verdict(REPRO.format(target=self.kernel(relpath)))
                self.assertEqual(verdict.decision, "deny", verdict.reason)
                self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_without_the_command_half_it_falls_straight_through(self) -> None:
        """THE CASE IS NOT VACUOUS, and this is the defect itself, pinned. With
        the classifier neutralised at the production seam the command is
        answered by nobody: allow, gate 'unarmed' - which is exactly what the
        reviewer measured against the shipped code."""
        original = keel_gate.installed_kernel_command
        keel_gate.installed_kernel_command = lambda event: ""
        try:
            verdict = self.verdict(REPRO.format(target=self.kernel()))
        finally:
            keel_gate.installed_kernel_command = original
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_the_record_names_the_command_and_not_a_path(self) -> None:
        """A command is recorded by its redacted, bounded head, exactly as
        every other blocked command is (convention 5, THE GLOBAL RULE)."""
        command = REPRO.format(target=self.kernel())
        verdict = self.verdict(command)
        self.assertEqual(
            verdict.detail.get("target"), keel_gate.blocked_command_detail(command)
        )

    def test_an_interpreter_one_liner_is_refused_too(self) -> None:
        """The bypass class this project has already paid for twice: no verb on
        any denylist, no redirect, and it rewrites the file anyway. The open
        world cannot answer it, so this rule uses the closed one."""
        target = self.kernel().replace("\\", "\\\\")
        verdict = self.verdict(f"python -c \"open('{target}', 'w').write('x')\"")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_redirect_into_the_kernel_is_refused(self) -> None:
        verdict = self.verdict(f"echo broken > {self.kernel()}")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_later_segment_cannot_mutate_what_an_earlier_one_named(self) -> None:
        """The closed mode's spelled taint, which is why it is the closed mode:
        a pipe hands the path on without naming it twice."""
        verdict = self.verdict(f"ls {self.install / 'hooks'} | xargs rm -f")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_chdir_into_the_kernel_then_a_mutation_is_refused(self) -> None:
        verdict = self.verdict(f"cd {self.install / 'hooks'} && rm keel_gate.py")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_chdir_into_the_installation_then_a_relative_mutation_is_refused(self) -> None:
        """The token that names the kernel is RELATIVE and the directory it is
        relative to was named by an earlier token, not by the event's cwd. A
        scan that resolved only against the event's cwd would see nothing."""
        verdict = self.verdict(f"cd {self.install} && sed -i s/a/b/ hooks/keel_gate.py")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_session_standing_inside_the_installation_is_refused_too(self) -> None:
        verdict = self.verdict("sed -i s/a/b/ hooks/keel_gate.py", cwd=self.install)
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_an_armed_session_with_a_fresh_ledger_is_refused_too(self) -> None:
        """No project decides this rule, so no project's ledger excuses it -
        the shape T506's write half was restored for, asked of a command."""
        armed(self.adopter, plan=True)
        verdict = self.verdict(REPRO.format(target=self.kernel()), cwd=self.adopter)
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)


class TestTheOwnersCaseIsUntouched(_Fixture):
    """Accept 2: BL57, which is the reason all of this exists."""

    def test_the_documented_first_step_still_clears(self) -> None:
        command = f"python {self.install / 'scripts' / 'keel.py'} survey --project ."
        verdict = self.verdict(command)
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_no_ledger_inside_the_cache_was_asked_for(self) -> None:
        command = f"python {self.install / 'scripts' / 'keel.py'} survey --project ."
        self.verdict(command)
        self.assertEqual(
            list((self.install / ".keel" / "plans").glob("keel-plan-*.md")),
            [],
            "no ledger was written into the plugin cache to obtain that allow",
        )

    def test_this_rule_says_nothing_about_the_cli_from_inside_the_install(self) -> None:
        """Asked of the CLASSIFIER, not of ``evaluate``: a session STANDING in
        an installed tree is still judged by the walk from its own cwd (T506's
        'the session's own walk is not filtered'), so ``evaluate`` may well
        refuse this for want of a ledger. What must be true here is that THIS
        rule is not the one speaking."""
        with home_at(self.home):
            self.assertEqual(
                keel_gate.installed_kernel_command(
                    exec_event(self.install, "python scripts/keel.py survey")
                ),
                "",
            )

    def test_a_chdir_into_the_installation_then_the_cli_still_clears(self) -> None:
        """The base-relative resolution the ``cd`` case needs must not turn the
        adopter's own first step into a refusal one directory later."""
        verdict = self.verdict(f"cd {self.install} && python scripts/keel.py survey")
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_nothing_of_the_installs_policy_is_read(self) -> None:
        """POLICY AUTHORITY STAYS DEMOTED: the classifier answers the same with
        the install's arming file deleted, so it cannot be reading it."""
        command = REPRO.format(target=self.kernel())
        with home_at(self.home):
            before = keel_gate.installed_kernel_command(exec_event(self.unadopted, command))
        (self.install / ".keel" / "keel-policy.md").unlink()
        with home_at(self.home):
            after = keel_gate.installed_kernel_command(exec_event(self.unadopted, command))
        self.assertTrue(before)
        self.assertEqual(before, after)


class TestWhatThisRuleDoesNotReach(_Fixture):
    """Accept 3 and accept 4: the boundary, in all three directions."""

    def test_a_mutating_command_at_an_ordinary_file_in_the_install_clears(self) -> None:
        verdict = self.verdict(REPRO.format(target=str(self.install / "notes.txt")))
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_a_mutating_command_at_a_checkout_outside_the_cache_clears(self) -> None:
        """Accept 4, as the stronger test: a keel tree identical to the
        installed one in every respect EXCEPT its location. This repository is
        such a tree, and is deliberately not evaluated against - doing so would
        append a real audit line to its log.

        IT IS STILL REFUSED, and that is the assertion: refused by ITS OWN
        POLICY LOCK, as a governing project, exactly as this repository refuses
        the same command today. If this rule had reached it, the gate would read
        ``installed_kernel`` and keel's own development tree would be being
        treated as somebody's installation."""
        with home_at(self.home):
            elsewhere = checkout(self.root / "keel-dev")
        verdict = self.verdict(REPRO.format(target=str(elsewhere / "hooks" / "keel_gate.py")))
        self.assertEqual(verdict.gate, "policy_lock", verdict.reason)
        self.assertNotEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_a_mutating_command_naming_nothing_in_the_cache_clears(self) -> None:
        verdict = self.verdict(f"rm -rf {self.root / 'scratch'}")
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_a_plain_read_of_the_kernel_is_not_refused(self) -> None:
        for command in (
            f"cat {self.kernel()}",
            f"grep -n deny {self.kernel()}",
            f"head -n 20 {self.kernel()}",
            f"cat {self.kernel()} | grep deny",
        ):
            with self.subTest(command=command):
                verdict = self.verdict(command)
                self.assertEqual(verdict.decision, "allow", verdict.reason)

    def test_the_classifier_stands_down_when_the_cache_cannot_be_named(self) -> None:
        """"" from ``install_cache_root`` is a machine where keel cannot name a
        cache, and it must exclude nothing rather than protect everything."""
        original = keel_gate.install_cache_root
        keel_gate.install_cache_root = lambda: ""
        try:
            with home_at(self.home):
                answer = keel_gate.installed_kernel_command(
                    exec_event(self.unadopted, REPRO.format(target=self.kernel()))
                )
        finally:
            keel_gate.install_cache_root = original
        self.assertEqual(answer, "")

    def test_a_write_event_is_not_the_command_halfs_business(self) -> None:
        with home_at(self.home):
            self.assertEqual(
                keel_gate.installed_kernel_command(
                    write_event(self.unadopted, self.kernel())
                ),
                "",
            )


class TestTheMutationNotionIsThisFilesOwn(_Fixture):
    """The constraint: one notion of "mutating", not two."""

    def test_the_command_half_delegates_to_the_shared_segment_scan(self) -> None:
        """``_shell_hits`` is the body; this rule supplies only the "does this
        text name it" predicate, exactly as the policy lock and THE GLOBAL RULE
        do. Proved at the seam rather than by reading the source."""
        seen: list[bool] = []
        original = keel_gate._shell_hits

        def spy(cmd, names, closed=False):
            seen.append(closed)
            return original(cmd, names, closed)

        keel_gate._shell_hits = spy
        try:
            with home_at(self.home):
                answer = keel_gate.installed_kernel_command(
                    exec_event(self.unadopted, REPRO.format(target=self.kernel()))
                )
        finally:
            keel_gate._shell_hits = original
        self.assertTrue(answer)
        self.assertIn(True, seen, "the command half runs the scan in its CLOSED mode")

    def test_the_predicate_answers_about_resolved_paths_not_bare_names(self) -> None:
        """A command naming ``hooks/keel_gate.py`` relative to a directory that
        is not an installation names no installation's kernel - this rule is
        not the policy lock's text test wearing a new name."""
        with home_at(self.home):
            self.assertFalse(
                keel_gate.names_installed_kernel(
                    "sed -i s/a/b/ hooks/keel_gate.py",
                    self.unadopted,
                    keel_gate.install_cache_root(),
                )
            )
            self.assertTrue(
                keel_gate.names_installed_kernel(
                    f"sed -i s/a/b/ {self.kernel()}",
                    self.unadopted,
                    keel_gate.install_cache_root(),
                )
            )

    def test_what_the_closed_mode_costs_is_pinned_rather_than_implied(self) -> None:
        """SAID OUT LOUD, because it is what this rule refuses BEYOND the open
        world's mutating-verb list: a READ of a kernel path through a word the
        allowlist does not name is refused too, since no matcher can tell a
        read from a write inside an interpreter one-liner or an unlisted tool.
        The refusal names the override, and under the harness's cache nobody is
        developing anything - which is why the cost is affordable here and not
        for the policy lock over a development tree."""
        for command in (
            f"python {self.kernel()}",
            f"jq . {self.kernel()}",
            f"git diff {self.install / 'hooks'}",
        ):
            with self.subTest(command=command):
                verdict = self.verdict(command)
                self.assertEqual(verdict.decision, "deny", verdict.reason)
                self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)
                self.assertIn("KEEL_OVERRIDE=on", verdict.reason)
                self.assertIn("read", verdict.reason.lower())

    def test_a_proven_print_sed_over_the_kernel_is_a_read(self) -> None:
        """The one allowlist, shared: ``sed`` clears only in the form this file
        can prove prints, and that proof is not re-implemented here."""
        verdict = self.verdict(f"sed -n 1,20p {self.kernel()}")
        self.assertEqual(verdict.decision, "allow", verdict.reason)

    def test_a_command_that_never_spells_the_path_is_the_stated_residual(self) -> None:
        """ACCEPTED, NOT CLOSED, and pinned so nobody believes otherwise: this
        is a TEXT scan over resolved tokens, so a path assembled from a variable
        names nothing for the predicate to resolve. The same residual
        ``_shell_hits`` records for both of its existing callers."""
        verdict = self.verdict('T=$(cat p.txt) && sed -i s/a/b/ "$T"')
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_an_unparsable_command_fails_safe_rather_than_open(self) -> None:
        """An unterminated quote abandons the scan, and ``_shell_hits`` then
        answers through the same predicate on the whole text."""
        verdict = self.verdict(f"sed -i 's/a/b/ {self.kernel()}")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)


class TestTheOverrideComposes(_Fixture):
    """It is carried, it is recorded under THIS rule's name, and the event
    still faces the plan gate - the treatment the lock, THE GLOBAL RULE and
    the write half all give the user's switch."""

    def test_the_users_override_carries_it_and_is_recorded(self) -> None:
        armed(self.adopter, plan=True)
        verdict = self.verdict(
            REPRO.format(target=self.kernel()),
            cwd=self.adopter,
            env={"KEEL_OVERRIDE": "on"},
        )
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "plan", "it falls through to the plan gate")
        log = (self.adopter / ".keel" / "audit" / "keel-audit.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertIn("gate_bypass", log)
        self.assertIn(keel_gate.INSTALL_KERNEL_GATE, log)

    def test_the_kill_switch_still_answers_first(self) -> None:
        verdict = self.verdict(REPRO.format(target=self.kernel()), env={"KEEL_GATE": "off"})
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "kill_switch")


class TestTheWriteHalfIsUnchanged(_Fixture):
    """Accept 5: nothing the T506 review confirmed sound is disturbed."""

    def test_every_kernel_path_is_still_refused_as_a_write(self) -> None:
        armed(self.adopter, plan=True)
        for relpath in KERNEL_RELPATHS:
            with self.subTest(target=relpath):
                with home_at(self.home):
                    verdict = keel_gate.evaluate(
                        write_event(self.adopter, self.kernel(relpath)), env={}
                    )
                self.assertEqual(verdict.decision, "deny", verdict.reason)
                self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE)

    def test_the_write_half_still_answers_only_about_writes(self) -> None:
        """The two halves stay two functions: the write half is exact because a
        write declares its target, and the command half is a heuristic. A
        single function answering both would hide which one spoke."""
        with home_at(self.home):
            self.assertEqual(
                keel_gate.installed_kernel_write(
                    exec_event(self.unadopted, REPRO.format(target=self.kernel()))
                ),
                "",
            )

    def test_an_ordinary_write_into_the_installation_still_clears(self) -> None:
        with home_at(self.home):
            verdict = keel_gate.evaluate(
                write_event(self.unadopted, str(self.install / "notes.txt")), env={}
            )
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)


class TestTheDeclarationMatchesTheBehaviour(unittest.TestCase):
    """R3: a stale justification is a false claim in this codebase."""

    def test_the_command_half_is_on_the_preflight_path(self) -> None:
        self.assertIn("installed_kernel_command", keel_gate.EVALUATION_PATH_SYMBOLS)
        self.assertIn("installed_kernel_write", keel_gate.EVALUATION_PATH_SYMBOLS)

    def test_the_module_prose_no_longer_calls_the_rule_write_only(self) -> None:
        doc = (keel_gate.__doc__ or "").upper()
        self.assertIn("THE INSTALLED-KERNEL RULE", doc)
        self.assertNotIn("A COMMAND MERELY NAMING A PATH INSIDE THE CACHE IS UNTOUCHED", doc)
        self.assertIn("MUTATING COMMAND", doc)

    def test_the_write_half_points_at_the_command_half(self) -> None:
        doc = keel_gate.installed_kernel_write.__doc__ or ""
        self.assertIn("installed_kernel_command", doc)

    def test_the_command_half_states_the_boundary_it_holds(self) -> None:
        doc = (keel_gate.installed_kernel_command.__doc__ or "").upper()
        self.assertIn("BL57", doc)
        self.assertIn("MUTATION", doc)

    def test_the_mode_is_argued_where_the_mode_is_chosen(self) -> None:
        """The closed world costs something, so the cost is stated beside the
        line that picks it rather than left for a reader to discover."""
        doc = (keel_gate.shell_hits_installed_kernel.__doc__ or "").upper()
        self.assertIn("CLOSED", doc)
        self.assertIn("COST", doc)


#: A path the harness could genuinely hand keel and Python cannot resolve.
#: An embedded NUL is the reviewer's named example and the sharpest one: it is
#: legal in a JSON payload, it is rejected by ``_resolved`` BEFORE
#: ``os.path.realpath`` is ever called, and no later rule looks at this event
#: again - the installed-kernel rule is asked in the no-governing-project
#: state, one line before the unarmed allow.
UNRESOLVABLE = "\x00"


class TestAnUnresolvableTokenIsRefusedNotIgnored(_Fixture):
    """The silent-failure finding on T507's first attempt (82%), as assertions.

    ``names_installed_kernel`` declares UNVERIFIABLE IS DENY, PER TOKEN, and
    for one input class the declaration was false. ``_resolved`` catches the
    embedded NUL ITSELF and returns "" rather than raising, so the per-token
    ``except`` that is supposed to make an unverifiable token deny was never
    reached; ``installed_kernel_root`` then read that "" exactly as it reads
    "no cache" and "not kernel", and the token stood for "names nothing".

    THE TWO STATES THAT BOTH SPELLED THEMSELVES "" ARE NOW APART: a token with
    no path in it is skipped before any resolution is attempted (and must
    still clear), while a token that IS a path and will not resolve cannot be
    shown NOT to be the kernel by anybody, here or later, and is refused.
    """

    def test_the_route_that_hid_it_is_still_the_route(self) -> None:
        """THE CASE IS NOT VACUOUS. The deny below cannot be coming from the
        location test: the resolution the location test is given still answers
        "" for this token, and ``installed_kernel_root`` still reads "" as "not
        this rule's business", exactly as ``is_user_global_target`` does. The
        refusal has to come from the failure being told apart from absence."""
        token = self.kernel() + UNRESOLVABLE  # keel-leak: ignore - a shell command token, not a credential
        self.assertEqual(keel_gate._resolved(self.unadopted, token), "")
        with home_at(self.home):
            cache = keel_gate.install_cache_root()
        self.assertTrue(cache, "the fixture must give keel a cache to compare against")
        self.assertEqual(keel_gate.installed_kernel_root("", cache), "")

    def test_an_unresolvable_kernel_token_is_refused(self) -> None:
        """Accept 1: the fail-open, closed. Without the fix this is
        allow/'unarmed' - the token is silently read as naming nothing."""
        verdict = self.verdict(REPRO.format(target=self.kernel() + UNRESOLVABLE))
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE, verdict.reason)

    def test_an_unresolvable_token_naming_nothing_of_keels_is_refused_too(self) -> None:
        """AND THAT IS THE POINT, not an over-reach to apologise for: where the
        path will not resolve keel cannot establish it is NOT the kernel, so it
        refuses under the rule whose question it could not answer. The refusal
        names the override, so the user has a door."""
        verdict = self.verdict(f"sed -i s/a/b/ {self.root / 'scratch'}{UNRESOLVABLE}")
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE, verdict.reason)
        self.assertIn("KEEL_OVERRIDE=on", verdict.reason)

    def test_the_relative_token_under_a_chdir_is_refused_too(self) -> None:
        """The ``cd <install> && ...`` shape, where the token that names the
        kernel is relative to a directory the event's ``cwd`` is not. An
        unresolvable relative token is unresolvable against every candidate
        base, so it cannot be cleared by any of them."""
        verdict = self.verdict(
            f"cd {self.install} && sed -i s/a/b/ hooks/keel_gate.py{UNRESOLVABLE}"
        )
        self.assertEqual(verdict.decision, "deny", verdict.reason)
        self.assertEqual(verdict.gate, keel_gate.INSTALL_KERNEL_GATE, verdict.reason)

    def test_the_predicate_itself_answers_true_for_it(self) -> None:
        """At the predicate, where the contract is written."""
        with home_at(self.home):
            cache = keel_gate.install_cache_root()
            self.assertTrue(
                keel_gate.names_installed_kernel(
                    f"sed -i s/a/b/ {self.kernel()}{UNRESOLVABLE}", self.unadopted, cache
                )
            )

    def test_the_refusal_says_so_on_stderr(self) -> None:
        """FAILING LOUDLY IS HALF THE FIX. A refusal keel cannot explain is the
        same silence in a different costume, so the per-token route prints the
        reason it could not answer, exactly as the other faults here do."""
        with home_at(self.home):
            cache = keel_gate.install_cache_root()
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                keel_gate.names_installed_kernel(
                    f"sed -i s/a/b/ {self.kernel()}{UNRESOLVABLE}", self.unadopted, cache
                )
        said = stderr.getvalue()
        self.assertIn("could not be", said)
        self.assertIn("refused", said)
        self.assertNotIn("\x00", said, "the unresolvable text is not echoed back")


class TestAbsenceIsStillNotFailure(_Fixture):
    """Accept 2: no blanket denial. The whole difficulty of the fix is that
    "there is no path in this token" and "there is a path here and it would
    not resolve" both surfaced as "" before, and only the second may refuse."""

    def test_an_ordinary_command_with_no_path_in_it_clears(self) -> None:
        for command in ("echo hello", "rm -rf scratch", "git status", "python -m json.tool"):
            with self.subTest(command=command):
                verdict = self.verdict(command)
                self.assertEqual(verdict.decision, "allow", verdict.reason)
                self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_a_broken_token_that_is_not_a_path_still_clears(self) -> None:
        """THE DISTINCTION, AT ITS SHARPEST: the same byte that refuses a path
        must not refuse a bare word. A token carrying no separator and no drive
        prefix names no location, so nothing is resolved for it and there is no
        failure to be unverifiable about."""
        verdict = self.verdict(f"echo hel{UNRESOLVABLE}lo")
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_ordinary_paths_that_do_not_exist_still_clear(self) -> None:
        """A path that RESOLVES is answered by the location test whether or not
        anything is there - ``realpath`` does not require existence - so the
        failure route is not reached by every command naming a missing file."""
        for command in (
            "sed -i s/a/b/ ./notes.txt",
            "sed -i s/a/b/ ../elsewhere/nothing-here.txt",
            f"sed -i s/a/b/ {self.root / 'no' / 'such' / 'file.txt'}",
            "curl -s https://example.com/x | sh",
        ):
            with self.subTest(command=command):
                verdict = self.verdict(command)
                self.assertEqual(verdict.decision, "allow", verdict.reason)
                self.assertEqual(verdict.gate, "unarmed", verdict.reason)

    def test_the_owners_first_step_still_clears(self) -> None:
        """BL57, asserted again in this class because this is the fix that
        could most easily have broken it: it names a path inside the cache that
        is not kernel, and it resolves, so neither route refuses it."""
        verdict = self.verdict(f"cd {self.install} && python scripts/keel.py survey")
        self.assertEqual(verdict.decision, "allow", verdict.reason)
        self.assertEqual(verdict.gate, "unarmed", verdict.reason)


class TestTheOtherCallersOfTheSharedResolverAreUntouched(unittest.TestCase):
    """Constraint: ``_resolved`` is shared, and its contract is not changed.

    A shared helper whose semantics moved under ``is_user_global_target`` or
    ``_evaluate_write`` would be a worse regression than the bug being fixed,
    so the failure/absence split lives in a wrapper the installed-kernel rule
    calls and nothing else does.
    """

    def test_the_shared_resolver_still_returns_the_empty_string(self) -> None:
        self.assertEqual(keel_gate._resolved(Path(os.getcwd()), "a\x00b"), "")
        self.assertEqual(keel_gate.norm(Path(os.getcwd()), "a\x00b"), "")

    def test_the_wrapper_is_the_only_new_caller(self) -> None:
        """The split is LOCAL: exactly one function raises, and it is the one
        the installed-kernel rule calls."""
        source = (REPO_ROOT / "hooks" / "keel_gate.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("_resolved_or_refuse("), 3)

    def test_the_write_half_still_reads_the_shared_resolver(self) -> None:
        """Accept 3: the write half is unchanged. Its unverifiable case is
        answered downstream by ``_evaluate_write`` under its own gate name, and
        refusing it here would rename that refusal."""
        source = (REPO_ROOT / "hooks" / "keel_gate.py").read_text(encoding="utf-8")
        body = source.split("def installed_kernel_write(")[1].split("\ndef ")[0]
        code = body.split('"""', 2)[2]
        self.assertIn("norm(event.cwd, raw)", code)
        self.assertNotIn("_resolved_or_refuse(", code)
        self.assertIn("_resolved_or_refuse", body, "and the docstring says WHY not")


class TestTheProseAndTheCodeAgree(_Fixture):
    """Accept 5. In this codebase a stale justification is a false claim, and
    this one was load-bearing enough to hide a fail-open for a whole review.
    Each case below drives the real function its docstring describes, so a
    docstring that drifted from the code it documents fails HERE rather than
    only in a grep of its own text - which is what a docstring merely
    existing proved before, and proved nothing about the behaviour."""

    def test_the_wrapper_raises_exactly_where_resolved_answers_failure(self) -> None:
        """"UNVERIFIABLE IS DENY" and "RESOLUTION", proved at the function the
        words are on rather than read off it: ``_resolved_or_refuse`` raises
        for precisely the input ``_resolved`` answers "" for (an unresolvable
        token IS a path), and for a resolvable input it hands back the exact
        string ``_resolved`` would - ``_resolved``'s own contract stays
        untouched, not quietly replaced by a second resolution."""
        unresolvable = self.kernel() + UNRESOLVABLE
        self.assertEqual(keel_gate._resolved(self.unadopted, unresolvable), "")
        with self.assertRaises(keel_gate._UnresolvablePath):
            keel_gate._resolved_or_refuse(self.unadopted, unresolvable)

        resolvable = self.kernel()
        self.assertEqual(
            keel_gate._resolved_or_refuse(self.unadopted, resolvable),
            keel_gate._resolved(self.unadopted, resolvable),
        )

    def test_the_per_token_contract_denies_even_when_no_token_names_the_kernel(self) -> None:
        """"PER TOKEN", asked of the predicate directly rather than of the
        whole evaluated verdict: a command that never spells the kernel's own
        path still answers True if some OTHER path-shaped token in it cannot
        be resolved, because the contract is kept for every such token, not
        only the one this rule is ultimately about."""
        with home_at(self.home):
            cache = keel_gate.install_cache_root()
        self.assertTrue(
            keel_gate.names_installed_kernel(
                f"sed -i s/a/b/ {self.root / 'scratch'}{UNRESOLVABLE}",
                self.unadopted,
                cache,
            )
        )

    def test_absence_never_reaches_the_wrapper_so_never_denies(self) -> None:
        """"ABSENCE" and "FAILURE" are told apart before either is asked
        about: a token carrying the same broken byte but no separator and no
        drive prefix names no location, so it is skipped before any
        resolution is attempted and the predicate clears it rather than
        denying - the same byte, a different shape, a different answer."""
        with home_at(self.home):
            cache = keel_gate.install_cache_root()
        self.assertFalse(
            keel_gate.names_installed_kernel(
                f"echo hel{UNRESOLVABLE}lo", self.unadopted, cache
            )
        )

if __name__ == "__main__":
    unittest.main()
