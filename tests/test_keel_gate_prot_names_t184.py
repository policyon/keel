#!/usr/bin/env python3
"""T184 - a protected name is a path segment, not a substring of any word.

Contract
--------
Reads   : ``hooks/keel_gate.py`` as a module. Nothing on disk: every case here
          is a command STRING, and the predicate under test is a text test, so
          no fixture project and no real file is needed - which is also why
          none of these commands is ever run.
Emits   : unittest results only.
Writes  : nothing at all.
Argv    : none.

The defect
----------
``has_prot`` answered "does this text name anything the policy lock protects"
with a bare substring test over ``PROT_TOKENS``. So ``sed -n 1,20p
tests/test_keel_gate_t169.py`` was REFUSED as a policy-lock write - the test
file's own name contains ``keel_gate``, and ``sed`` is on the unconditional
mutator list. The same thing happened to read-only greps naming
``.claude-plugin/`` on 2026-09-01 and three more times on 2026-09-02, to an
executor and then twice to the orchestrator. It fails CLOSED, so it cost
friction rather than safety; the reason it still mattered is that an adopter
meets it in the first hour and reads it as keel refusing to let them look at
their own tests.

What is NOT reopened here, because the design rule settles it
------------------------------------------------------------
The block comment "SHELL POLICY LOCK - DESIGN RULE" in ``hooks/keel_gate.py``
decides two things this file must leave alone, and both are asserted below so
that a later change cannot quietly reverse them while making these cases pass:

* a segment is a violation only when it carries BOTH a mutation AND a
  protected name. Only the NAME test moved; the verb list did not, and the
  rejection of a read-only allowlist for this rule stands.
* ``sed`` stays on ``_MUTATE_VERBS`` unconditionally, because its mutation is
  flag-dependent. ``sed -n`` on a REAL locked file is still refused - that is
  ``test_sed_dash_n_on_a_really_locked_file_is_still_refused``, and it is the
  wall beside the door this task opened.

Both directions, per convention 15
----------------------------------
The ALLOW cases are the fix; the REFUSE cases are what the fix must not cost.
Restoring the substring test makes ``test_a_read_only_sed_on_a_test_file_is_allowed``
and ``test_a_longer_stem_naming_no_protected_file_is_allowed`` fail and leaves
every REFUSE case passing, which is what proves the two sets are independent.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_gate  # noqa: E402  (path must be set first)


def refused(command: str) -> bool:
    """The policy-lock rule's verdict on one command: True means refused.

    Asked through ``_shell_hits`` with ``has_prot``, which is the exact pair
    the lock uses, rather than through ``has_prot`` alone - a name test that
    answered correctly while the segment scan still refused the command would
    be a fix that fixed nothing.
    """
    return keel_gate._shell_hits(command, keel_gate.has_prot)


class TestAReadOnlyCommandIsNotRefusedForNamingAToken(unittest.TestCase):
    """The ALLOW direction - the defect itself, in the spellings that met it."""

    def test_a_read_only_sed_on_a_test_file_is_allowed(self) -> None:
        """T184's acceptance case, named in full: the test file is not the module.

        ``test_`` precedes ``keel_gate`` inside the same segment, so the text
        names a file called ``test_keel_gate_t169.py`` and no protected file at
        all. Spelled out rather than globbed: a glob is not a path and would
        fail the refs check.
        """
        command = "sed -n 1,20p tests/test_keel_gate_t169.py"
        self.assertFalse(keel_gate.has_prot(command), "the name test still matches")
        self.assertFalse(refused(command), "a read-only look at a test file was refused")

    def test_a_read_only_grep_naming_the_plugin_directory_is_allowed(self) -> None:
        """Read-only, and it DOES name a protected directory - which is fine.

        The open-world rule never refused this: naming the set is not a
        violation without a mutation in the same segment. Pinned because the
        2026-09-01 sounding reported it as refused, and a change to the name
        test must not be able to regress it.
        """
        command = "grep -n foo .claude-plugin/plugin.json | head"
        self.assertTrue(keel_gate.has_prot(command), "the directory should still be seen")
        self.assertFalse(refused(command), "a read-only grep was refused")

    def test_a_longer_stem_naming_no_protected_file_is_allowed(self) -> None:
        """The redirect target names nothing protected; the token is inside a stem."""
        command = "echo my_keel_gate_notes.txt > out.txt"
        self.assertFalse(keel_gate.has_prot(command))
        self.assertFalse(refused(command))

    def test_neither_a_longer_directory_nor_a_file_named_like_one_matches(self) -> None:
        """The same rule ``_PROT_DIR_RE`` already applied, now for file names."""
        for command in ("cat my_hooks/x", "cat hooks.txt", "cat my_settings.json.bak"):
            with self.subTest(command=command):
                self.assertFalse(keel_gate.has_prot(command), command)


class TestAProtectedNameIsStillFound(unittest.TestCase):
    """The REFUSE direction - everything the fix must not cost."""

    def test_a_mutating_sed_on_a_locked_file_is_refused(self) -> None:
        command = "sed -i s/a/b/ hooks/keel_gate.py"
        self.assertTrue(keel_gate.has_prot(command))
        self.assertTrue(refused(command))

    def test_a_sed_that_is_not_provably_a_print_is_still_refused(self) -> None:
        """The wall beside the door: ``sed`` mutates flag-dependently.

        UNTIL 2026-09-06 THIS ASSERTED THE DOOR SHUT TOO - ``sed -n 1,20p``
        on a locked file was refused, because ``sed`` sits on the unconditional
        mutator list. T513 (BL54) reversed that one case and nothing beside it:
        a PROVEN print writes nothing, so refusing it was a false refusal,
        while every spelling the proof does not cover still refuses. T184
        narrowed the NAME test and is unaffected either way, which these two
        halves are here to keep true.
        """
        self.assertFalse(refused("sed -n 1,20p hooks/keel_gate.py"))
        for command in (
            "sed -n /x/p hooks/keel_gate.py",
            "sed -n -e 1,20p hooks/keel_gate.py",
            "sed 1,20p hooks/keel_gate.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(refused(command), command)

    def test_copying_onto_and_moving_a_locked_file_are_refused(self) -> None:
        for command in ("cp x hooks/keel_gate.py", "mv hooks/keel_events.py /tmp/"):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.has_prot(command), command)
                self.assertTrue(refused(command), command)

    def test_a_locked_file_is_found_behind_any_prefix_on_either_separator(self) -> None:
        """Still a text test: an absolute prefix in front of the name counts."""
        for command in (
            "cat ~/p/hooks/keel_gate.py",
            "cat c:\\p\\hooks\\keel_gate.py",
            "cat .keel/keel-policy.md",
            "cat ~/.claude/settings.json",
            "python -m keel_events",
        ):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.has_prot(command), command)

    def test_the_protected_environment_variables_are_still_seen(self) -> None:
        """Not files, so they keep a word-boundary test - all three spellings.

        These never appear with a separator in front of them, which is why the
        path-segment rule would have missed every real one and why they are
        matched separately.
        """
        for command in (
            "KEEL_OVERRIDE=on python x.py",
            '$env:KEEL_OVERRIDE = "on"',
            "setx KEEL_PLAN_TTL_MIN 30",
            "keel_override=on git status",
        ):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.has_prot(command), command)

    def test_the_chdir_taint_still_reaches_a_later_segment(self) -> None:
        """The design rule's one exception, unaffected by the name test."""
        self.assertTrue(refused("cd hooks && rm *.py"))

    def test_the_fail_safe_paths_still_see_a_protected_name(self) -> None:
        """An unparsable and an over-long command, each naming a real locked file.

        ``_shell_hits`` answers every fail-safe through ``has_prot`` on the
        whole command text, so a tighter name test tightens those too. What
        must remain true is that a fail-safe whose text DOES name a protected
        path still refuses, which is what these two pin - the same sample text
        ``tests/test_keel_kernel.py`` uses for the unterminated quote.
        """
        unterminated = 'grep -n "keel-policy.md hooks/keel_gate.py'
        self.assertTrue(keel_gate.has_prot(unterminated))
        self.assertTrue(refused(unterminated))

        oversize = "cat hooks/keel_gate.py " + "x" * (keel_gate._MAX_CMD + 10)
        self.assertTrue(keel_gate.has_prot(oversize))
        self.assertTrue(refused(oversize))


class TestTheTwoSetsAreMatchedByTheRulesTheyDeclare(unittest.TestCase):
    """The vocabulary is pinned, so an addition has to change a test."""

    def test_every_token_belongs_to_exactly_one_set(self) -> None:
        self.assertEqual(
            keel_gate.PROT_TOKENS,
            keel_gate.PROT_FILE_TOKENS + keel_gate.PROT_ENV_TOKENS,
        )
        self.assertEqual(
            set(keel_gate.PROT_FILE_TOKENS) & set(keel_gate.PROT_ENV_TOKENS), set()
        )

    def test_the_environment_set_is_the_documented_pair(self) -> None:
        """Only these two are variables; anything else added here is a file."""
        self.assertEqual(
            set(keel_gate.PROT_ENV_TOKENS), {"keel_override", "keel_plan_ttl_min"}
        )

    def test_every_file_token_is_found_as_its_own_segment(self) -> None:
        """Each token, in its ordinary spelling, is seen; inside a stem it is not."""
        for token in keel_gate.PROT_FILE_TOKENS:
            with self.subTest(token=token):
                self.assertTrue(keel_gate.has_prot(f"cat some/dir/{token}"), token)
                self.assertFalse(keel_gate.has_prot(f"cat some/dir/prefix_{token}"), token)


if __name__ == "__main__":
    unittest.main()
