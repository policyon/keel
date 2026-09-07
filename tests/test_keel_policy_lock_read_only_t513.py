#!/usr/bin/env python3
"""T513 - the policy lock refuses a MUTATION, not a mention (BL54).

Contract
--------
Reads   : ``hooks/keel_gate.py`` through ``shell_hits_policy_lock``,
          ``shell_policy_lock_unclassifiable`` and TWO PRIVATE NAMES touched
          on purpose - ``_segment_word_is_read_only``, the one predicate the
          narrowing reuses, and ``_MAX_CMD``, to build a command over the
          parse limit. Renaming either should fail here, which is why they
          are named.
Emits   : unittest results only.
Writes  : nothing at all. Every case is a pure predicate call on command
          TEXT; no project, no temporary directory and no file is created,
          because the scan resolves nothing against a filesystem.
Argv    : none.

What this covers, and why each half exists
------------------------------------------
BL54 measured the lock refusing commands that only NAMED a locked path: a
``grep`` whose sole mention of ``hooks/`` was its search target, and a
``sed -n`` reading the policy file. The ruling recorded with T513 in
``.keel/backlog.md`` is that the scan gains NO path resolver - scope stays
shape-based, because a resolver that can be fooled is worse than one that
over-refuses - and that the PREDICATE narrows instead, from "names a locked
path" to "names a locked path AND could mutate it".

1. THE ALLOW DIRECTION, which is the whole point of the change: a command
   whose segment word the read-only allowlist can PROVE writes nothing is no
   longer a policy-lock hit, however loudly it names a locked path - and
   including the two shapes the verb list misread as mutations, an unquoted
   mutating word inside a grep PATTERN and ``sed`` standing on
   ``_MUTATE_VERBS`` unconditionally.
2. THE REFUSE DIRECTION, every existing refusal, because a narrowing is only
   defensible if it is exactly as wide as it claims: the mutating verbs, a
   redirect into a locked path BEHIND a read-only word, a heredoc, the ``cd``
   taint, the PowerShell cmdlets, the override variable, and a mutation
   chained after a read of the same file.
3. FAIL CLOSED, which is where a narrowing of a gate goes wrong. The
   withdrawal is applied per segment, after the redirect test and after every
   fail-safe return, so a command whose SHAPE the scan could not establish -
   over-long, unterminated quote, unterminated heredoc, unresolved redirect
   target - still refuses on the raw text even when an allowlisted read word
   stands at its head. Those four are asserted with ``grep``/``cat`` at the
   front for exactly that reason.
4. THE WITHDRAWAL CERTIFIES NOTHING IT CANNOT PROVE: an unrecognised word, an
   interpreter, an editor, a command substitution and a leading assignment are
   all refused certification. What the OPEN world then does with an unknown
   verb is unchanged by T513 - it passes, as this rule's design rule has
   always said, and the gap is recorded as ``lock_unclassifiable`` (E1)
   rather than silently blessed. That is asserted here so the limit is a
   record rather than a rediscovery.
5. THE NARROWING IS MONOTONE. Structurally the new mutation test is
   ``not read_only and <the old test>``, so nothing previously ALLOWED can
   become refused. That identity is asserted directly over a corpus by
   forcing the withdrawal off, which reproduces the old answer exactly.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Commands are casefolded
before the scan sees them, the way ``_evaluate_exec`` casefolds them.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_gate  # noqa: E402


def hits(command: str) -> bool:
    """The lock's own question, asked the way the gate asks it."""
    return keel_gate.shell_hits_policy_lock(command.casefold())


def segment(command: str) -> dict:
    """The single segment of a one-segment command, as the scan builds it."""
    body, heredoc_ok = keel_gate.strip_heredocs(command.casefold())
    segs, scan_ok = keel_gate.scan_segments(body)
    assert heredoc_ok and scan_ok and len(segs) == 1, command
    return segs[0]


class TestAReadOnlyCommandMayNameALockedPath(unittest.TestCase):
    """BL54's complaint, in the form the acceptance criterion states it."""

    ALLOWED = (
        # The two commands BL54 actually observed being refused.
        'grep -rn "policy lock" hooks/keel_gate.py',
        "sed -n '2944,3060p' hooks/keel_gate.py",
        # A mutating WORD that is an argument, never a command: the verb list
        # is matched over the segment's unquoted code, so each of these was a
        # refusal for a word in a search pattern.
        "grep -n set hooks/keel_gate.py",
        "grep -rn export hooks/",
        "grep -n rm .claude/settings.json",
        # The plain reads the criterion enumerates.
        "cat hooks/keel_gate.py",
        "head -40 .keel/keel-policy.md",
        "tail -5 .claude/settings.json",
        "ls hooks/",
        "ls -la .claude-plugin/",
        "wc -l hooks/keel_gate.py",
        "find hooks -name '*.py'",
        "diff hooks/keel_gate.py hooks/keel_stop.py",
        "egrep -n keel_override hooks/keel_gate.py",
        # Read-only pipelines and chains over locked paths.
        "cat hooks/keel_gate.py | head -20",
        "grep -c def hooks/keel_gate.py && wc -l hooks/keel_gate.py",
        # A read whose output goes to a null sink is still a read.
        "cat .keel/keel-policy.md > /dev/null",
        # A chdir into a locked directory taints, but a read is not a mutation
        # for the taint to fire on.
        "cd hooks && cat keel_gate.py",
    )

    def test_a_read_that_only_names_a_locked_path_is_allowed(self) -> None:
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertFalse(hits(command), command)

    def test_the_withdrawal_is_the_one_shared_predicate(self) -> None:
        """Not a second allowlist and not a second scanner: the same predicate
        rule 2 has shipped since 2026-08-18 answers for all three rules. If a
        future change gives the lock a private copy, this fails."""
        for command in ("grep -n set hooks/keel_gate.py", "sed -n '1,5p' hooks/keel_gate.py"):
            with self.subTest(command=command):
                self.assertTrue(keel_gate._segment_word_is_read_only(segment(command)))


class TestEveryExistingRefusalStillRefuses(unittest.TestCase):
    """The narrowing is exactly as wide as it claims and no wider."""

    REFUSED = (
        # Mutating command words.
        "rm -rf hooks/",
        "rm hooks/keel_gate.py",
        "cp evil.py hooks/keel_gate.py",
        "mv hooks/keel_gate.py /tmp/x",
        "copy evil.py hooks" + chr(92) + "keel_stop.py",
        "truncate -s 0 .keel/keel-policy.md",
        "chmod 777 hooks/keel_gate.py",
        # PowerShell cmdlets, which name no POSIX verb at all.
        "set-content hooks/keel_gate.py 'x'",
        "remove-item hooks/keel_gate.py",
        "out-file -filepath .claude/settings.json",
        # Redirects into a locked path - INCLUDING behind a read-only word,
        # which is the shape the withdrawal would break if it were applied
        # before the redirect test instead of after it.
        "echo x > hooks/keel_gate.py",
        "cat notes.md > hooks/keel_gate.py",
        "grep -n def notes.py >> hooks/keel_gate.py",
        "sed -n '1,5p' notes.md > hooks/keel_gate.py",
        "ls -la > .claude/settings.json",
        # A heredoc body is data, and the redirect in front of it is not.
        "cat > hooks/keel_gate.py <<eof\nx = 1\neof",
        # The cd taint: the second segment names nothing protected.
        "cd hooks && rm keel_gate.py",
        "cd hooks && echo x > y.py",
        # The override variable, which is not a file.
        "setx keel_override on",
        'set keel_override=on',
        '$env:keel_override="on"',
        "export keel_override=on",
        # sed that is not provably a print.
        "sed -i 's/x/y/' .keel/keel-policy.md",
        "sed -i.bak 's/x/y/' hooks/keel_gate.py",
        "sed --in-place 's/x/y/' hooks/keel_gate.py",
        # A mutation chained after a read of the same file: the read is
        # withdrawn, the mutation is not.
        "cat hooks/keel_gate.py; rm hooks/keel_gate.py",
        "grep -n def hooks/keel_gate.py && rm hooks/keel_gate.py",
        # find's executing action family is not read-only.
        "find hooks -type f -exec rm {} ;",
    )

    def test_each_mutation_of_a_locked_path_still_refuses(self) -> None:
        for command in self.REFUSED:
            with self.subTest(command=command):
                self.assertTrue(hits(command), command)


class TestFailClosedWhenTheShapeCannotBeEstablished(unittest.TestCase):
    """A command the scan could not parse is refused, whatever word heads it.

    Every case here puts an ALLOWLISTED READ at the front on purpose. If the
    withdrawal were applied before the fail-safe returns - or over the whole
    command instead of per segment - each of these would flip to allowed, and
    the fail-safe would have been opened by a change that only meant to stop
    refusing greps.
    """

    def test_an_over_long_command_still_refuses(self) -> None:
        oversize = "grep -n x hooks/keel_gate.py " + ("a" * keel_gate._MAX_CMD)
        self.assertGreater(len(oversize), keel_gate._MAX_CMD)
        self.assertTrue(hits(oversize))

    def test_an_unterminated_quote_still_refuses(self) -> None:
        self.assertTrue(hits('grep -n "keel-policy.md hooks/keel_gate.py'))

    def test_an_unterminated_heredoc_still_refuses(self) -> None:
        self.assertTrue(hits("cat hooks/keel_gate.py <<eof\nstill going"))

    def test_a_redirect_with_no_target_still_refuses(self) -> None:
        self.assertTrue(hits("cat hooks/keel_gate.py >"))

    def test_the_fail_safe_answers_on_the_raw_text_not_the_word(self) -> None:
        """The same four shapes naming NOTHING protected are still allowed, so
        the refusals above are the protected NAME being seen - not the parse
        failure refusing everything, which would prove nothing about the lock.
        """
        for command in (
            "grep -n x notes.md " + ("a" * keel_gate._MAX_CMD),
            'grep -n "notes.md readme.md',
            "cat notes.md <<eof\nstill going",
            "cat notes.md >",
        ):
            with self.subTest(command=command[:40]):
                self.assertFalse(hits(command))


class TestTheWithdrawalCertifiesNothingItCannotProve(unittest.TestCase):
    """Doubt is never certified read-only - and what the OPEN world does with
    an unknown verb is unchanged by T513, which is stated here as a limit."""

    UNCERTIFIED = (
        "frobnicate hooks/keel_gate.py",
        "python -c \"open('hooks/keel_gate.py','w').write('x')\"",
        "node rewrite.js hooks/keel_gate.py",
        "vim hooks/keel_gate.py",
        "cat $(echo hooks/keel_gate.py)",
        "cat `echo hooks/keel_gate.py`",
        "keel_override=on cat hooks/keel_gate.py",
        "find hooks -name '*.py' -delete",
        "sed -n '/## policy lock/,/## holds/p' .keel/keel-policy.md",
    )

    def test_an_unproven_shape_is_never_certified_read_only(self) -> None:
        for command in self.UNCERTIFIED:
            with self.subTest(command=command):
                segs, _ = keel_gate.scan_segments(command.casefold())
                self.assertFalse(
                    any(keel_gate._segment_word_is_read_only(seg) for seg in segs),
                    command,
                )

    def test_an_unrecognised_word_is_recorded_rather_than_blessed(self) -> None:
        """THE LIMIT, ON THE RECORD. The open world still lets an unknown verb
        past - T513 narrowed the refusal, it did not widen it, and 'an unknown
        verb is not evidence of mutation' is this rule's own design rule. The
        gap is not silent: the lock's closed world would have stopped these,
        and the difference is written as ``lock_unclassifiable`` (E1)."""
        for command in (
            "frobnicate hooks/keel_gate.py",
            "python -c \"open('.keel/keel-policy.md','w').write('x')\"",
        ):
            with self.subTest(command=command):
                self.assertTrue(
                    keel_gate.shell_policy_lock_unclassifiable(command.casefold()),
                    command,
                )


class TestTheNarrowingIsMonotone(unittest.TestCase):
    """Nothing the lock allowed can become refused, asserted rather than argued.

    The new mutation test is ``not read_only and <the old test>``, so forcing
    ``_segment_word_is_read_only`` to False reproduces the OLD answer exactly -
    which is what makes this comparison a measurement of the change rather than
    a restatement of it. A rewrite that makes the withdrawal anything other
    than a conjunction fails here.
    """

    CORPUS = (
        TestAReadOnlyCommandMayNameALockedPath.ALLOWED
        + TestEveryExistingRefusalStillRefuses.REFUSED
        + TestTheWithdrawalCertifiesNothingItCannotProve.UNCERTIFIED
        + (
            "git diff -- hooks/keel_gate.py | head -40",
            "python -m unittest discover -s tests 2>&1 | tail -3",
            "ls hooks/ && rm -rf /tmp/x",
            "grep -rn x hooks/ | xargs rm -f",
            "echo hello",
        )
    )

    def _without_the_withdrawal(self, command: str) -> bool:
        real = keel_gate._segment_word_is_read_only
        keel_gate._segment_word_is_read_only = lambda seg: False
        try:
            return hits(command)
        finally:
            keel_gate._segment_word_is_read_only = real

    def test_the_substitution_actually_reaches_the_scan(self) -> None:
        """The comparison below is worthless if the patch does not land, so the
        one command whose answer MUST differ is asserted first."""
        command = "sed -n '1,5p' hooks/keel_gate.py"
        self.assertFalse(hits(command))
        self.assertTrue(self._without_the_withdrawal(command))

    def test_no_command_becomes_newly_refused(self) -> None:
        for command in self.CORPUS:
            with self.subTest(command=command[:60]):
                if hits(command):
                    self.assertTrue(
                        self._without_the_withdrawal(command),
                        f"newly refused, which the narrowing may never do: {command}",
                    )


if __name__ == "__main__":
    unittest.main()
