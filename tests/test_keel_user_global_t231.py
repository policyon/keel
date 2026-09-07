#!/usr/bin/env python3
"""T231: keel's own user-global files are refused to every project.

Contract
--------
Reads   : ``hooks/keel_gate.py`` through its public surface - the classifier
          (``user_global_write``), the two predicates it is built from,
          ``evaluate`` and ``run``. TWO PRIVATE NAMES ARE TOUCHED ON PURPOSE
          and nothing else is: ``_MAX_CMD``, to build a command over the parse
          limit, and ``_shell_hits`` with its ``closed`` flag, which is the
          only place the open mode and the closed one can be asked the SAME
          question and shown to answer differently. Renaming either should
          fail here, which is the point of naming them.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. THE
          REAL ``~/.claude/keel/`` IS NEVER TOUCHED, read or written: every
          case runs inside ``keel_registry_guard.sandboxed_user_global_home``,
          the same guard T227 and T238 shipped, so ``Path.home()`` - the one
          resolver the production code uses - answers with a throwaway
          directory for the duration of the block. ``test_the_sandbox_is_the_
          resolver_production_uses`` proves the substitution actually reaches
          the gate rather than being decoration.
Argv    : none.

What this covers, and why each half exists
-------------------------------------------
The fixtures under ``tests/fixtures/gate/85-*`` through ``94-*`` pin the
end-to-end verdicts of this rule - refused, overridden, the neighbour that is
not keel's, the shell redirect, the read that stays allowed, the three the
first 2026-08-22 review added (the interpreter one-liner that used to pass
silently, the same one-liner carried by the override and recorded, and the
interpreter READ that is refused with it) and the two the second one forced:
``find <dir> -type f | xargs rm -f``, which passed silently while each segment
was judged alone, and the all-read-only pipeline that must still run. This file
pins what a fixture cannot reach:

1. FROM ANY PROJECT, WHICH MEANS AN UNADOPTED ONE TOO. Every gate fixture
   builds an armed project, because every other rule in the gate needs one.
   This rule needs none - that is its whole point - so the unarmed direction
   can only be asserted here.
2. AND WITHOUT LEAVING A ``.keel/`` BEHIND. A refusal in a directory nobody
   adopted must not create an audit log there; the notice on stderr is the
   record instead.
3. THE SCOPE, IN BOTH DIRECTIONS. Everything under the ratified directory is
   covered, including a file in a subdirectory that does not exist yet; the
   harness's own settings beside it and a sibling sharing its first letters
   are NOT covered, which is clause 3 of the ruling read as a limit rather
   than as a licence.
4. THE CRASH CARVE-OUT IS NOT REGRESSED, AND THE ORDER IS WHY. The rule is
   asked before the project resolution, so a resolution that raises still
   refuses a write to keel's own state - and the same broken resolution still
   lets a ``.keel/plans/`` write through, which is T179/T236's carve-out and
   is the one loosening this task was told not to touch.
5. THE SWITCHES. ``KEEL_GATE=off`` stands the rule down with the rest of the
   gate; ``KEEL_OVERRIDE=on`` carries the write and is recorded.
6. THE CLOSED ALLOWLIST THE 2026-08-22 REVIEWS FORCED, in every one of its
   directions at once, which is the only honest way to pin a trade-off: the
   interpreter write that is now refused, the mutation a PIPE hid behind an
   allowlisted read of the same directory, the plain read that still runs -
   down a pipe as well - the unproven READ and the later segment aimed
   elsewhere that are refused with the writes (the two costs), the forward
   direction of the taint, and the path assembled at runtime that is still
   missed (the residual, accepted).

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding. A backslash is built with ``chr(92)`` rather than typed, because a
class like ``[\\/]`` collapses through a heredoc into one that matches no
Windows path at all - a defect this repository has already paid for once.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "tests"))
import keel_faultlog  # noqa: E402
import keel_gate  # noqa: E402
from keel_events import KeelEvent  # noqa: E402
from keel_registry_guard import sandboxed_user_global_home  # noqa: E402

#: The backslash, built rather than typed - see the module docstring.
BACKSLASH = chr(92)

#: A contract-clean session ledger, so a case that means to exercise this rule
#: is never answered by the plan gate instead.
LEDGER = (
    "# Plan\n\n- [ ] T1 the thing\n      Route: standard (keel:executor).\n"
    "      Accept: it works.\n"
)

#: A tier-2 arming file, for the cases that need one.
POLICY = "---\ntier: 2\n---\n\n# keel policy - fixture project\n"


def armed_project(root: Path, sess8: str = "") -> Path:
    """A tier-2 project at ``root``, with a fresh ledger when ``sess8`` is given."""
    keel = root / ".keel"
    keel.mkdir(parents=True, exist_ok=True)
    with open(keel / "keel-policy.md", "w", encoding="utf-8", newline="\n") as handle:
        handle.write(POLICY)
    if sess8:
        plans = keel / "plans"
        plans.mkdir(parents=True, exist_ok=True)
        with open(plans / f"keel-plan-{sess8}.md", "w", encoding="utf-8", newline="\n") as handle:
            handle.write(LEDGER)
    return root


def write_event(cwd: Path, *paths: Path | str, session: str = "") -> KeelEvent:
    """A ``Write`` of one or more absolute paths, from ``cwd``."""
    return KeelEvent(
        kind="pre_write",
        cwd=cwd,
        session_id=session or None,
        tool_name="Write",
        file_paths=tuple(str(p) for p in paths),
    )


def exec_event(cwd: Path, command: str, session: str = "") -> KeelEvent:
    """A ``Bash`` command from ``cwd``."""
    return KeelEvent(
        kind="pre_exec",
        cwd=cwd,
        session_id=session or None,
        tool_name="Bash",
        command=command,
    )


class UserGlobalCase(unittest.TestCase):
    """One throwaway home and one throwaway project per case."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self._home = sandboxed_user_global_home()
        self.home = self._home.__enter__()
        self.addCleanup(lambda: self._home.__exit__(None, None, None))

    @property
    def user_global(self) -> Path:
        """keel's user-global directory inside this case's throwaway home."""
        return self.home.joinpath(*keel_faultlog.USER_GLOBAL_RELPATH)

    @property
    def registry(self) -> Path:
        """The fleet registry inside it - a file keel really does deploy."""
        return self.user_global / "keel-registry.json"

    def evaluate(self, event: KeelEvent, env: dict[str, str] | None = None):
        """``evaluate`` with stderr captured, since this rule talks on it."""
        with redirect_stderr(io.StringIO()):
            return keel_gate.evaluate(event, env or {})


class TestTheSandboxIsReal(UserGlobalCase):
    """Every assertion below is vacuous unless the substituted home is the one
    production resolves. This is that proof, and it is first on purpose."""

    def test_the_sandbox_is_the_resolver_production_uses(self) -> None:
        self.assertEqual(
            keel_faultlog.user_global_dir(), self.user_global,
            "the guard must move the resolver keel itself calls, not a copy",
        )
        self.assertEqual(
            keel_gate.user_global_root(),
            os.path.realpath(str(self.user_global)).casefold(),
            "the gate must protect the directory that resolver names",
        )

    def test_the_scope_is_the_ratified_directory_and_not_a_second_spelling(self) -> None:
        """R15: the gate derives the directory from ``keel_faultlog`` rather
        than restating it, so the guard and the guarded cannot drift."""
        self.assertEqual(keel_faultlog.USER_GLOBAL_RELPATH, (".claude", "keel"))
        for segment in keel_faultlog.USER_GLOBAL_RELPATH:
            self.assertIn(segment, keel_gate._USER_GLOBAL_RE.pattern)


class TestTheRuleReachesEveryProject(UserGlobalCase):
    """Accept 1: from ANY project, which is the half no fixture can build."""

    def test_an_unadopted_project_still_cannot_write_the_registry(self) -> None:
        verdict = self.evaluate(write_event(self.project, self.registry))
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "user_global")

    def test_an_armed_project_cannot_write_it_either(self) -> None:
        armed_project(self.project, "abcd1234")
        verdict = self.evaluate(
            write_event(self.project, self.registry, session="abcd1234-0000")
        )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "user_global")

    def test_the_refusal_leaves_no_keel_directory_in_an_unadopted_project(self) -> None:
        """A refusal that adopted the project on its way past would be keel
        scattering ``.keel/`` trees through directories nobody opted in."""
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            verdict = keel_gate.run(write_event(self.project, self.registry), {})
        self.assertEqual(verdict.gate, "user_global")
        self.assertFalse((self.project / ".keel").exists())
        self.assertIn("no gate_block audit line was written", stderr.getvalue())

    def test_the_refusal_is_filed_when_the_project_is_adopted(self) -> None:
        armed_project(self.project, "abcd1234")
        with redirect_stderr(io.StringIO()):
            keel_gate.run(write_event(self.project, self.registry, session="abcd1234-0000"), {})
        line = (self.project / ".keel" / "audit" / "keel-audit.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertIn('"gate": "user_global"', line)
        self.assertIn('"event": "gate_block"', line)

    def test_nothing_reaches_the_user_global_directory_itself(self) -> None:
        """The gate guards that directory; it must never write in it."""
        self.evaluate(write_event(self.project, self.registry))
        self.assertEqual(sorted(self.home.rglob("*")), [])


class TestTheScope(UserGlobalCase):
    """Accept 1's other half: what the rule does NOT claim."""

    def test_every_path_under_the_directory_is_covered(self) -> None:
        for target in (
            self.user_global,
            self.registry,
            self.user_global / "keel-hook-errors.jsonl",
            self.user_global / "keel-prompts" / "keel-prompts-abcd1234.jsonl",
            self.user_global / "not" / "created" / "yet.txt",
        ):
            with self.subTest(target=target):
                self.assertTrue(
                    keel_gate.is_user_global_target(keel_gate.norm(self.project, str(target)))
                )
                verdict = self.evaluate(write_event(self.project, target))
                self.assertEqual(verdict.gate, "user_global")

    def test_the_harness_own_files_beside_it_are_not_keels_to_refuse(self) -> None:
        """Clause 3 of the ratified decision read as a LIMIT: nothing outside
        the one directory is keel's, so nothing outside it is refused here."""
        for target in (
            self.home / ".claude" / "settings.json",
            self.home / ".claude" / "keel-notes.txt",
            self.home / ".claude" / "keeling" / "note.txt",
            self.home / "keel" / "note.txt",
            self.home / "note.txt",
        ):
            with self.subTest(target=target):
                self.assertFalse(
                    keel_gate.is_user_global_target(keel_gate.norm(self.project, str(target)))
                )
                self.assertEqual(keel_gate.user_global_write(write_event(self.project, target)), "")

    def test_a_target_inside_the_project_is_never_this_rule(self) -> None:
        armed_project(self.project, "abcd1234")
        for relative in ("src/app.py", ".keel/keel-policy.md", ".keel/plans/keel-plan-abcd1234.md"):
            with self.subTest(relative=relative):
                self.assertEqual(
                    keel_gate.user_global_write(write_event(self.project, self.project / relative)),
                    "",
                )

    def test_one_covered_target_in_a_payload_refuses_the_payload(self) -> None:
        """Payload-wide, like every other write rule here: a neighbour cannot
        be carried past the gate by the innocent file beside it."""
        event = write_event(self.project, self.project / "src" / "app.py", self.registry)
        self.assertEqual(keel_gate.user_global_write(event), str(self.registry))


class TestTheCommandHalf(UserGlobalCase):
    """A guard that stops Write but not a redirect guards nothing - and a
    guard that stops ``cat`` guards too much."""

    def test_mutations_are_refused_however_they_spell_the_path(self) -> None:
        absolute = str(self.registry)
        for command in (
            "echo {} > ~/.claude/keel/keel-registry.json",
            "echo {} >> ~/.claude/keel/keel-registry.json",
            "rm -rf ~/.claude/keel",
            "rm -rf ~/.claude/keel/",
            "cd ~/.claude/keel && rm keel-registry.json",
            f"echo {{}} > {absolute}",
            "set-content $HOME" + BACKSLASH + ".claude" + BACKSLASH + "keel"
            + BACKSLASH + "keel-registry.json v",
        ):
            with self.subTest(command=command):
                verdict = self.evaluate(exec_event(self.project, command))
                self.assertEqual(verdict.decision, "deny", command)
                self.assertEqual(verdict.gate, "user_global", command)

    def test_reads_of_the_same_files_are_not_refused_by_this_rule(self) -> None:
        for command in (
            "cat ~/.claude/keel/keel-registry.json",
            "ls ~/.claude/keel",
            "grep keel ~/.claude/keel/keel-hook-errors.jsonl",
        ):
            with self.subTest(command=command):
                self.assertEqual(keel_gate.user_global_write(exec_event(self.project, command)), "")

    def test_a_neighbour_named_by_a_command_is_not_refused(self) -> None:
        for command in (
            "rm ~/.claude/keel-notes.txt",
            "rm ~/.claude/settings.json",
            "rm -rf ~/.claude/keeling",
        ):
            with self.subTest(command=command):
                self.assertEqual(keel_gate.user_global_write(exec_event(self.project, command)), "")

    def test_a_command_too_large_to_parse_still_answers_on_the_text(self) -> None:
        """FAIL SAFE, NEVER FAIL OPEN: the oversize fallback asks the same
        question of the whole command text."""
        padding = "x" * (keel_gate._MAX_CMD + 10)
        self.assertTrue(
            keel_gate.shell_hits_user_global(f"echo {padding} > ~/.claude/keel/x".casefold())
        )
        self.assertFalse(keel_gate.shell_hits_user_global(f"echo {padding} > note.txt".casefold()))

    def test_the_policy_lock_scan_is_unchanged_by_sharing_its_body(self) -> None:
        """The two scans share one implementation now, so the lock's own
        answers are re-pinned here: sharing may not have moved them."""
        self.assertTrue(keel_gate.shell_hits_policy_lock("rm -rf hooks/"))
        self.assertTrue(keel_gate.shell_hits_policy_lock("cd hooks && rm keel_gate.py"))
        self.assertFalse(keel_gate.shell_hits_policy_lock("cat hooks/keel_gate.py"))
        self.assertFalse(keel_gate.shell_hits_policy_lock("ls -la"))

    def test_the_gap_between_the_two_modes_is_what_e1_records(self) -> None:
        """E1: the predicate is exactly the DIFFERENCE between the lock's open
        answer and its closed one, over the same protected set.

        THE BLAST-RADIUS CLAIM IS THE SECOND CLAUSE, and it is asserted here
        rather than argued: for every command the lock already refuses, the
        predicate is FALSE, so no refusal can decay into a recording. The first
        clause carries the case BL11 measured - an interpreter one-liner
        rewriting the arming file, which the open mode has nothing to match on.
        """
        # Recorded: allowed today, and the closed mode would have stopped it.
        for command in (
            "python -c \"open('.keel/keel-policy.md','w').write('x')\"",
            "bash -c 'echo x > hooks/keel_gate.py'",
            "perl -pi -e 's/a/b/' hooks/keel_gate.py",
        ):
            with self.subTest(recorded=command):
                self.assertTrue(keel_gate.shell_policy_lock_unclassifiable(command.casefold()))
                self.assertFalse(keel_gate.shell_hits_policy_lock(command.casefold()))

        # Never recorded: already refused (the predicate may not overlap a
        # refusal), silent in both modes, or naming nothing protected at all.
        for command in (
            "echo x > hooks/keel_gate.py",  # refused today, and stays refused
            "rm -rf hooks/",  # refused today
            "cat hooks/keel_gate.py",  # allowlisted read, silent in both modes
            "ls -la",  # names nothing protected
            "tar -xf payload.tar",  # THE HONEST LIMIT: names nothing to match
        ):
            with self.subTest(silent=command):
                self.assertFalse(keel_gate.shell_policy_lock_unclassifiable(command.casefold()))

    def test_a_command_too_large_to_parse_is_refused_rather_than_recorded(self) -> None:
        """THE FAIL-SAFE PATH, pinned so its silence cannot be mistaken for a
        hole. Both modes answer an unparseable command with the same whole-text
        test, so the difference between them collapses to False and nothing is
        recorded. Nothing is lost by that: the same fail-safe makes the OPEN mode
        say True, so the lock REFUSES the command outright - a stronger outcome
        than recording it. This asserts the pair together, because either half
        alone would read as the wrong story.
        """
        padding = "x" * (keel_gate._MAX_CMD + 10)
        oversize = f"python -c \"open('hooks/keel_gate.py','w').write('{padding}')\"".casefold()
        self.assertFalse(keel_gate.shell_policy_lock_unclassifiable(oversize))
        self.assertTrue(keel_gate.shell_hits_policy_lock(oversize))
        # And one naming nothing protected: silent in both, refused by neither.
        harmless = f"python -c \"open('notes.txt','w').write('{padding}')\"".casefold()
        self.assertFalse(keel_gate.shell_policy_lock_unclassifiable(harmless))
        self.assertFalse(keel_gate.shell_hits_policy_lock(harmless))

    def test_the_recorded_event_has_its_own_name_apart_from_a_bypass(self) -> None:
        """A reader counting these must be able to count them apart from the two
        permissions: a bypass says the user's switch carried a refusal, a
        workshop write says a declaration did, and this says nothing did - the
        lock could not judge what it allowed. The name is IMPORTED, never
        spelled, per a-marker-matched-by-literal-disarms-on-rename."""
        self.assertNotIn(
            keel_gate.LOCK_UNCLASSIFIABLE_EVENT, ("gate_bypass", "workshop_write", "gate_block")
        )

    def test_the_e1_fixtures_spell_the_event_the_code_emits(self) -> None:
        """THE HALF THE PYTHON TESTS CANNOT COVER BY IMPORTING: a JSON fixture
        has no way to import a constant, so its expected event name is a hand-
        spelled literal - the exact shape that a rename disarms while the suite
        stays green (a-marker-matched-by-literal-disarms-on-rename). This ties
        the literals back to the constant, so renaming the event fails HERE
        instead of quietly turning three fixtures into assertions about a name
        nothing emits any more.
        """
        root = Path(__file__).resolve().parent / "fixtures" / "gate"
        stems = (
            "107-an-interpreter-one-liner-against-the-arming-file-is-recorded",
            "109-an-allowlisted-read-of-a-locked-path-records-nothing",
            "110-a-command-naming-no-locked-path-records-nothing",
        )
        for stem in stems:
            path = root / f"{stem}.json"
            self.assertTrue(path.is_file(), f"the E1 fixture {stem} is missing")
            doc = json.loads(path.read_text(encoding="utf-8"))
            named = doc.get("expect_audit_events", []) + doc.get(
                "expect_audit_events_absent", []
            )
            self.assertIn(keel_gate.LOCK_UNCLASSIFIABLE_EVENT, named, stem)


class TestTheClosedAllowlist(UserGlobalCase):
    """THE 2026-08-22 REVIEW FINDING AND ITS FIX (85%, confirmed).

    The command half first shipped in the policy lock's OPEN mode - a segment
    naming the directory was refused only if it ALSO showed a redirect or a
    mutating verb. An interpreter one-liner shows neither, so the path matcher
    was never consulted and the registry could be rewritten with no deny, no
    bypass line and no audit row. These cases pin the closed mode that replaced
    it: refused unless the command word is on the read-only allowlist - and
    they pin its COST and its RESIDUAL just as explicitly, because a trade-off
    only stays a decision if the next reader can see both sides of it.
    """

    def test_an_interpreter_writing_the_directory_is_refused(self) -> None:
        """The exact shape the review reproduced, and its neighbours: every one
        of these writes through a string no verb list can read."""
        for command in (
            "python3 -c \"import os; "
            "open(os.path.expanduser('~/.claude/keel/keel-registry.json'), 'w').write('{}')\"",
            "python -c \"open('~/.claude/keel/keel-registry.json', 'w')\"",
            "node -e \"require('fs').writeFileSync('~/.claude/keel/keel-registry.json', '{}')\"",
            "perl -e 'open(F, \">\", \"~/.claude/keel/keel-registry.json\")'",
            f"python3 -c \"open('{self.registry}', 'w')\"",
            "awk 'BEGIN{print \"{}\" > \"~/.claude/keel/keel-registry.json\"}'",
        ):
            with self.subTest(command=command):
                verdict = self.evaluate(exec_event(self.project, command))
                self.assertEqual(verdict.decision, "deny", command)
                self.assertEqual(verdict.gate, "user_global", command)

    def test_the_taint_carries_the_closed_mode_past_a_chdir(self) -> None:
        """The second segment names nothing at all, so only the ``cd`` taint
        can refuse it - the same taint the open mode already had."""
        verdict = self.evaluate(
            exec_event(self.project, "cd ~/.claude/keel && python3 -c \"open('x', 'w')\"")
        )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "user_global")

    def test_a_read_through_the_allowlist_still_runs_after_a_chdir(self) -> None:
        self.assertEqual(
            keel_gate.user_global_write(
                exec_event(self.project, "cd ~/.claude/keel && cat keel-registry.json")
            ),
            "",
        )

    def test_the_allowlist_is_the_one_rule_2_already_argues(self) -> None:
        """No second list to keep in step: these are ``_READ_ONLY_COMMANDS``
        and its two proven-form words, asked of the segment that names the
        directory. A regression to a blanket ban shows up here."""
        for command in (
            "cat ~/.claude/keel/keel-registry.json",
            "head -n 5 ~/.claude/keel/keel-registry.json",
            "tail -n 5 ~/.claude/keel/keel-hook-errors.jsonl",
            "grep keel ~/.claude/keel/keel-hook-errors.jsonl",
            "wc -l ~/.claude/keel/keel-registry.json",
            "ls -la ~/.claude/keel",
            "diff ~/.claude/keel/keel-registry.json note.json",
            "sed -n '1,5p' ~/.claude/keel/keel-registry.json",
            "find ~/.claude/keel -name keel-registry.json",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    keel_gate.user_global_write(exec_event(self.project, command)), "", command
                )

    def test_the_allowlists_own_disqualifiers_still_apply_here(self) -> None:
        """An allowlisted word does NOT launder the segment around it: an
        in-place ``sed``, a ``find -delete``, a leading assignment and a
        command substitution are refused for the same reasons rule 2 refuses
        them."""
        for command in (
            "sed -i 's/a/b/' ~/.claude/keel/keel-registry.json",
            "find ~/.claude/keel -name '*.json' -delete",
            "keel_override=on cat ~/.claude/keel/keel-registry.json",
            "cat $(echo ~/.claude/keel/keel-registry.json)",
        ):
            with self.subTest(command=command):
                verdict = self.evaluate(exec_event(self.project, command))
                self.assertEqual(verdict.decision, "deny", command)
                self.assertEqual(verdict.gate, "user_global", command)

    def test_the_cost_an_unproven_read_is_refused_with_the_writes(self) -> None:
        """STATED, NOT HIDDEN: keel cannot tell a read from a write inside an
        interpreter one-liner or an unlisted tool, so it refuses both - and the
        refusal says exactly that and names the door out."""
        for command in (
            "python3 -c \"print(open('~/.claude/keel/keel-registry.json').read())\"",
            "jq . ~/.claude/keel/keel-registry.json",
            "git diff ~/.claude/keel/keel-registry.json",
        ):
            with self.subTest(command=command):
                verdict = self.evaluate(exec_event(self.project, command))
                self.assertEqual(verdict.decision, "deny", command)
                self.assertEqual(verdict.gate, "user_global", command)
                self.assertIn(
                    "keel cannot tell a read from a write inside an interpreter one-liner",
                    verdict.reason,
                )
                self.assertIn("KEEL_OVERRIDE=on", verdict.reason)

    def test_a_later_segment_cannot_mutate_what_an_earlier_one_named(self) -> None:
        """THE SECOND 2026-08-22 FINDING (85%, confirmed), reproduced here.

        The closed mode first judged each segment against its OWN text, so a
        pipeline whose FIRST segment named the directory through an allowlisted
        read set nothing, and the mutation one segment later named nothing left
        to match. Every command below emptied or rewrote keel's user-global
        state with no deny, no bypass line and no audit row. A pipe HANDS the
        directory to the next segment without spelling it twice, so naming it
        now taints the rest of the command exactly as a ``cd`` into it does.
        """
        for command in (
            "find ~/.claude/keel -type f | xargs rm -f",
            "ls ~/.claude/keel | xargs rm",
            "find ~/.claude/keel -name '*.json' | xargs sed -i 's/a/b/'",
            "cat ~/.claude/keel/keel-registry.json | python3 -c \"open('r.json', 'w')\"",
            "ls ~/.claude/keel && rm -rf keel-registry.json",
        ):
            with self.subTest(command=command):
                verdict = self.evaluate(exec_event(self.project, command))
                self.assertEqual(verdict.decision, "deny", command)
                self.assertEqual(verdict.gate, "user_global", command)

    def test_an_all_read_only_pipeline_over_the_directory_still_runs(self) -> None:
        """THE BOUND ON WHAT THAT TAINT MAY COST, pinned beside it: naming the
        directory does not ban the pipe. Every segment here is on the same
        allowlist, which is how the doctor, the board and a curious session
        actually read this state - a regression to "any pipeline touching the
        directory is refused" fails here rather than passing quietly."""
        for command in (
            "cat ~/.claude/keel/keel-registry.json | grep projects",
            "cat ~/.claude/keel/keel-registry.json | grep projects | wc -l",
            "ls ~/.claude/keel | head -n 5",
            "find ~/.claude/keel -type f | grep registry",
            "sed -n '1,5p' ~/.claude/keel/keel-registry.json | cat",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    keel_gate.user_global_write(exec_event(self.project, command)), "", command
                )

    def test_the_second_cost_an_unlisted_segment_aimed_somewhere_else(self) -> None:
        """STATED, NOT HIDDEN, like the first cost: once the directory has been
        named, an unlisted segment is refused even when it aims elsewhere
        entirely. Separating the two commands is the way through, and the
        refusal names the override as well."""
        verdict = self.evaluate(
            exec_event(self.project, "ls ~/.claude/keel && rm -rf build-output")
        )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "user_global")
        self.assertEqual(
            keel_gate.user_global_write(exec_event(self.project, "rm -rf build-output")), ""
        )

    def test_the_taint_runs_forward_because_a_command_runs_forward(self) -> None:
        """A mutation BEFORE any mention of the directory is not refused: in a
        pipeline the data flows left to right, and after ``&&`` or ``;`` the
        text order IS the execution order, so nothing to the left can have been
        handed a directory only named to its right. Pinned so the taint is not
        quietly widened into "the command mentions it somewhere, refuse all of
        it", which would refuse a build step for a later read."""
        self.assertEqual(
            keel_gate.user_global_write(
                exec_event(self.project, "rm -rf build-output && ls ~/.claude/keel")
            ),
            "",
        )

    def test_the_spelled_taint_is_the_closed_modes_alone(self) -> None:
        """SCOPE LINE, pinned: the policy lock keeps its open mode untouched by
        this change - the same command answers False through the shared body
        with ``closed=False``. Whether the lock should take this taint too is
        T202's question at its own surface, filed on the ledger, not decided
        here as a side effect."""
        command = "find ~/.claude/keel -type f | xargs rm -f".casefold()
        self.assertTrue(keel_gate._shell_hits(command, keel_gate.names_user_global, closed=True))
        self.assertFalse(keel_gate._shell_hits(command, keel_gate.names_user_global, closed=False))

    def test_the_write_halfs_message_keeps_its_own_plainer_sentence(self) -> None:
        """A Write DECLARES its target, so there the promise is exact and the
        command half's caveat would only confuse."""
        reason = self.evaluate(write_event(self.project, self.registry)).reason
        self.assertIn("Reading those files is not refused; changing them is.", reason)
        self.assertNotIn("interpreter one-liner", reason)

    def test_the_residual_a_command_that_never_names_the_path(self) -> None:
        """ACCEPTED, NOT CLOSED, and recorded here so it is never mistaken for
        a fix that works: this is a TEXT test, so a path assembled at runtime -
        out of the environment, a variable or a concatenation - names nothing
        for the matcher to see. The write half, handed a real path, has no such
        gap; closing this one needs a layer that sees the syscall, which is the
        question T202 holds open for the ledger path
        (.keel/knowledge/a-shell-rewrite-is-atomic-on-disk-and-invisible-to-the-gate.md).
        """
        for command in (
            "python3 -c \"import os; open(os.environ['reg'], 'w').write('{}')\"",
            "python3 -c \"import os; open(os.path.expanduser('~/.clau' + 'de/keel/x'), 'w')\"",
            "d=~/.claude; python3 -c \"open('x', 'w')\"",
        ):
            with self.subTest(command=command):
                self.assertEqual(
                    keel_gate.user_global_write(exec_event(self.project, command)), "", command
                )

    def test_an_unparseable_command_still_answers_on_the_whole_text(self) -> None:
        """FAIL SAFE, NEVER FAIL OPEN in the closed mode too: an unterminated
        quote defeats the segmentation, so the name test judges the raw text."""
        self.assertTrue(
            keel_gate.shell_hits_user_global(
                "python3 -c \"open('~/.claude/keel/keel-registry.json', 'w'".casefold()
            )
        )
        self.assertFalse(
            keel_gate.shell_hits_user_global("python3 -c \"open('note.txt', 'w'".casefold())
        )


class TestTheSwitches(UserGlobalCase):
    """Accept 1: the override is honoured exactly as the other rules honour it."""

    def test_the_override_carries_the_write(self) -> None:
        armed_project(self.project, "abcd1234")
        verdict = self.evaluate(
            write_event(self.project, self.registry, session="abcd1234-0000"),
            {"KEEL_OVERRIDE": "on"},
        )
        self.assertEqual(verdict.decision, "allow")
        self.assertFalse(verdict.blocking)

    def test_the_override_is_recorded_under_this_rules_own_name(self) -> None:
        armed_project(self.project, "abcd1234")
        with redirect_stderr(io.StringIO()):
            keel_gate.run(
                write_event(self.project, self.registry, session="abcd1234-0000"),
                {"KEEL_OVERRIDE": "on"},
            )
        line = (self.project / ".keel" / "audit" / "keel-audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"event": "gate_bypass"', line)
        self.assertIn('"gate": "user_global"', line)
        self.assertIn('"switch": "KEEL_OVERRIDE"', line)

    def test_the_override_does_not_absorb_the_plan_gate(self) -> None:
        """It composes, as it does for the lock: no ledger, still refused -
        by the PLAN gate, which is the honest second answer."""
        armed_project(self.project)
        verdict = self.evaluate(
            write_event(self.project, self.registry, session="abcd1234-0000"),
            {"KEEL_OVERRIDE": "on"},
        )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "plan")

    def test_the_kill_switch_stands_this_rule_down_with_the_rest(self) -> None:
        verdict = self.evaluate(write_event(self.project, self.registry), {"KEEL_GATE": "off"})
        self.assertEqual(verdict.gate, "kill_switch")


class TestTheRefusalSaysEnough(UserGlobalCase):
    """A refusal that cannot be acted on is a dead end."""

    def test_the_message_names_the_rule_the_ruling_and_the_door(self) -> None:
        verdict = self.evaluate(write_event(self.project, self.registry))
        for phrase in (
            "KEEL USER-GLOBAL STATE",
            "keel's own user-global directory",
            ".keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md",
            "KEEL_OVERRIDE=on",
            "Reading those files is not refused",
            "(Guardrail: user-global.)",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, verdict.reason)

    def test_the_audit_target_is_relative_and_the_command_is_a_head(self) -> None:
        write = self.evaluate(write_event(self.project, self.registry))
        self.assertNotIn(str(self.project), write.detail["target"])
        command = self.evaluate(exec_event(self.project, "rm -rf ~/.claude/keel"))
        self.assertIn("~/.claude/keel", command.detail["target"])


class TestTheCrashCarveOutIsUntouched(UserGlobalCase):
    """The one loosening this task was told not to regress - and the ordering
    that lets both stand at once."""

    def setUp(self) -> None:
        super().setUp()
        armed_project(self.project, "abcd1234")
        self._governance = keel_gate.governance

        def broken(event):  # noqa: ANN001 - a stub, deliberately shaped wrong
            raise RuntimeError("deliberate resolution fault")

        keel_gate.governance = broken
        self.addCleanup(lambda: setattr(keel_gate, "governance", self._governance))

    def test_a_ledger_write_still_passes_a_gate_that_cannot_evaluate(self) -> None:
        ledger = self.project / ".keel" / "plans" / "keel-plan-abcd1234.md"
        with redirect_stderr(io.StringIO()) as stderr:
            verdict = keel_gate.run(write_event(self.project, ledger, session="abcd1234-0000"), {})
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(verdict.gate, "internal_error_ledger")
        self.assertIn("LEDGER WRITE PERMITTED THROUGH A FAILED GATE", stderr.getvalue())

    def test_and_the_user_global_refusal_survives_the_same_fault(self) -> None:
        """Asked before the resolution, so a resolution that cannot answer
        does not become a way into keel's own state."""
        with redirect_stderr(io.StringIO()):
            verdict = keel_gate.run(
                write_event(self.project, self.registry, session="abcd1234-0000"), {}
            )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.gate, "user_global")

    def test_the_carve_out_never_covers_keels_own_directory(self) -> None:
        """``.keel/plans/`` is the carve-out's whole scope, and no path inside
        the user-global directory is one."""
        self.assertEqual(
            keel_gate.crash_ledger_carve_out(write_event(self.project, self.registry)), ""
        )


class TestTheGuardLeavesNothingBehind(unittest.TestCase):
    """The sandbox is shared machinery now, so its own residue is pinned here.

    ``keel_gate._walk_home`` memoises this user's home, which is right for a
    hook process and wrong for a test process that moves the home under
    itself: a sandbox that did not drop the memo on both edges would leave
    every LATER case in the same interpreter reading a temporary directory
    that no longer exists as this machine's home. That is exactly how
    ``tests/test_keel_target_arming_t178.py``'s home-is-a-ceiling case came to
    pass or fail on nothing but file order, so it is asserted rather than
    remembered.
    """

    def test_the_memoised_home_does_not_survive_the_sandbox(self) -> None:
        real = keel_gate._walk_home()
        with sandboxed_user_global_home() as home:
            self.assertEqual(keel_gate._walk_home(), Path(os.path.realpath(str(home))))
        self.assertEqual(keel_gate._walk_home(), real)
        self.assertTrue(keel_gate.is_walk_ceiling(Path.home()))


if __name__ == "__main__":
    unittest.main()
