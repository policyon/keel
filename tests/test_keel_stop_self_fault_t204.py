#!/usr/bin/env python3
"""T204 - the stop gate no longer blames the innocent arming file either.

Contract
--------
Reads   : ``hooks/keel_stop.py`` and ``hooks/keel_gate.py`` as modules. Every
          fixture is built under a temporary directory, so no assertion here
          depends on the tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

The defect
----------
``hooks/keel_stop.py`` carried the same sentence T179 removed from
``hooks/keel_gate.py``: "this project is armed ... Fix .keel/keel-policy.md
or set KEEL_GATE=off deliberately", said unconditionally whenever the stop
gate's OWN ``evaluate`` raised - even when that raise came from keel's own
half-applied edit and the arming file parsed cleanly. A session whose stop
gate cannot account for it was sent to fix a file that was never broken, at
the exact moment it was trying to end and account for itself.

THE FIX REUSES T179'S CLASSIFIERS RATHER THAN RE-DERIVING THEM:
``keel_gate.gate_self_fault`` and ``keel_gate.policy_parse_fault`` are
imported into ``hooks/keel_stop.py`` and called directly, so the two gates
cannot classify the identical exception two different ways -
``TestTheClassifiersAreReusedNotReimplemented`` pins the identity.

THE FIXTURE FOR AN UNEVALUABLE STOP GATE, modelled on
``tests/test_keel_gate_self_preflight_t179.py``: a symbol ``evaluate``
reaches on every ordinary armed, resolved, ledger-bearing stop -
``read_ledger`` - is deleted from the live module and restored afterwards, so
the fault is a genuine call-time ``NameError`` raised from inside
``hooks/keel_stop.py``, not a simulated one.

What this covers, clause by clause
-----------------------------------
1. THE TWO FAULTS ARE TOLD APART (accept 1). ``TestTheInnocentFileIsNotBlamed``.
2. THE WORDING MATCHES T179's (accept 2). Same three-shape structure, same
   classifiers, same lead sentence ("FAILED CLOSED"), pinned by
   ``TestTheClassifiersAreReusedNotReimplemented`` and by the shared shape
   strings asserted in ``TestTheInnocentFileIsNotBlamed``.
3. THE FIXTURE DRIVES AN UNEVALUABLE MODULE AND ASSERTS THE REAL FAULT SITE
   (accept 3). ``TestTheFixtureReallyBreaksEvaluation`` and
   ``test_a_call_time_nameerror_names_the_real_site``.
4. SUITE AND CHECKS (accept 4) are verified outside this file.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails the check rather
than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names
its encoding.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
import uuid
from contextlib import contextmanager, redirect_stderr
from pathlib import Path
from typing import Iterator

import sys

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_stop  # noqa: E402

#: The arming file spelling, as the refusal message would name it.
POLICY_RELPATH = ".keel/keel-policy.md"

#: THE SYMBOL THE CALL-TIME FIXTURE REMOVES. ``evaluate`` reaches it on every
#: ordinary armed, resolved, enforcing-tier stop that has passed the
#: kill-switch and loop checks - reading the ledger is not conditional on
#: anything the fixture itself sets up differently, so deleting it reproduces
#: a genuine call-time fault rather than a preflight-only one.
CALL_SITE_SYMBOL = "read_ledger"


def fresh_session() -> tuple[str, str]:
    """A (session_id, sess8) pair no other case has used."""
    session = uuid.uuid4().hex
    return session, session[:8]


def armed(project: Path, *, tier: int = 2) -> Path:
    """A fixture project whose arming file declares ``tier`` and parses."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )
    return project


def unparseable(project: Path) -> Path:
    """A fixture project whose arming file is PRESENT and does not parse."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        "---\nname: broken-fixture\n---\n\n# frontmatter without a tier\n",
        encoding="utf-8",
    )
    return project


def write_ledger(project: Path, sess8: str, body: str) -> Path:
    """This session's ledger, at the one path the stop gate consults."""
    plans = project / ".keel" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    path = plans / f"keel-plan-{sess8}.md"
    path.write_text(body, encoding="utf-8")
    return path


def stop_event(cwd: Path, session: str) -> keel_events.KeelEvent:
    """One Stop event in the shape the adapter hands the gate."""
    return keel_events.KeelEvent(
        kind="stop",
        cwd=cwd,
        session_id=session,
        raw={"hook_event_name": "Stop", "session_id": session, "stop_hook_active": False},
    )


@contextmanager
def missing_symbol(name: str) -> Iterator[None]:
    """The fixture: a stop gate whose module state is inconsistent, then
    restored. Put back in ``finally`` even when the assertion fails, or every
    later test in the suite would run against a broken gate."""
    original = getattr(keel_stop, name)
    delattr(keel_stop, name)
    try:
        yield
    finally:
        setattr(keel_stop, name, original)


def run_quietly(event: keel_events.KeelEvent) -> tuple[keel_events.KeelVerdict, str]:
    """``run`` with stderr captured. ``env={}``: no kill switch may colour a
    result here."""
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        verdict = keel_stop.run(event, env={})
    return verdict, buffer.getvalue()


class TestTheClassifiersAreReusedNotReimplemented(unittest.TestCase):
    """REUSE BEFORE REBUILDING: the stop gate must not carry its own opinion
    about what counts as keel's own defect or a broken arming file - it asks
    the same functions ``keel_gate.py`` already carries (R15), so the two
    gates cannot disagree about the identical exception."""

    def test_gate_self_fault_is_the_same_function(self) -> None:
        self.assertIs(keel_stop.gate_self_fault, keel_gate.gate_self_fault)

    def test_policy_parse_fault_is_the_same_function(self) -> None:
        self.assertIs(keel_stop.policy_parse_fault, keel_gate.policy_parse_fault)


class TestTheFixtureReallyBreaksEvaluation(unittest.TestCase):
    """THE BEFORE HALF, and it is not ceremony: every assertion in this file
    is vacuous unless the fixture genuinely stops ``evaluate`` deciding. The
    module still imports and ``evaluate`` is still callable while this fault
    is live - proving the point
    ``a-module-that-imports-is-not-a-gate-that-evaluates`` makes."""

    def test_the_fixture_really_makes_evaluate_raise(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [ ] T9 open\n")
            event = stop_event(project, session)
            with missing_symbol(CALL_SITE_SYMBOL):
                self.assertTrue(callable(keel_stop.evaluate))
                with self.assertRaises(NameError):
                    keel_stop.evaluate(event, env={})
            # Restored: the identical event now evaluates cleanly.
            self.assertEqual(keel_stop.evaluate(event, env={}).gate, "stop")


class TestTheInnocentFileIsNotBlamed(unittest.TestCase):
    """Accept 1, 2 and 3. The old message named ``.keel/keel-policy.md``
    unconditionally; the new one names it only when that file genuinely will
    not parse, and names keel's own source, with its real site, otherwise."""

    def test_a_clean_arming_file_is_never_named_and_the_real_site_is(self) -> None:
        """Accept 3: the fixture drives an unevaluable module and the message
        names the REAL fault site - a line inside ``hooks/keel_stop.py``, not
        the arming file that parsed cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [ ] T9 open\n")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, err = run_quietly(stop_event(project, session))
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.to_exit_code(), 2)
        self.assertIn("KEEL STOP FAILED CLOSED", verdict.reason)
        self.assertIn("THE FAULT IS KEEL'S OWN", verdict.reason)
        self.assertIn("keel_stop.py:", verdict.reason)
        self.assertNotIn(POLICY_RELPATH, verdict.reason)
        self.assertIn("KEEL'S OWN", err)

    def test_a_call_time_nameerror_names_the_real_site(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [ ] T9 open\n")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(stop_event(project, session))
        self.assertIn("NameError", verdict.reason)
        self.assertIn(CALL_SITE_SYMBOL, verdict.reason)

    def test_the_repair_named_is_the_one_that_applies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            session, sess8 = fresh_session()
            write_ledger(project, sess8, "# Plan\n\n- [ ] T9 open\n")
            with missing_symbol(CALL_SITE_SYMBOL):
                verdict, _err = run_quietly(stop_event(project, session))
        self.assertIn("restored from git", verdict.reason)
        self.assertIn("ONE write of the complete file", verdict.reason)

    def test_a_broken_arming_file_IS_named_with_the_reason(self) -> None:
        """The other direction, which a fix of this shape breaks: when the
        file really is the fault, it must still be named, with the reason."""
        with tempfile.TemporaryDirectory() as tmp:
            project = unparseable(Path(tmp) / "project")
            session, _sess8 = fresh_session()
            verdict, _err = run_quietly(stop_event(project, session))
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("KEEL STOP FAILED CLOSED", verdict.reason)
        self.assertIn(POLICY_RELPATH, verdict.reason)
        self.assertIn("THE ARMING FILE IS THE FAULT", verdict.reason)
        self.assertIn("declares no tier", verdict.reason)

    def test_a_fault_keel_cannot_attribute_says_the_file_is_not_at_fault(self) -> None:
        """The third shape: not keel's own source, and the arming file
        parses. Staying silent about it is what let the old sentence be
        assumed to still apply."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            session, _sess8 = fresh_session()
            original = keel_stop.evaluate

            def boom(*_a: object, **_k: object) -> keel_events.KeelVerdict:
                raise RuntimeError("deliberate fault, not keel-shaped")

            keel_stop.evaluate = boom
            try:
                verdict, _err = run_quietly(stop_event(project, session))
            finally:
                keel_stop.evaluate = original
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("KEEL STOP FAILED CLOSED", verdict.reason)
        self.assertIn("THE ARMING FILE IS NOT THE FAULT", verdict.reason)
        self.assertNotIn(POLICY_RELPATH, verdict.reason)

    def test_an_unresolved_session_does_not_claim_the_project_is_armed(self) -> None:
        """The double-fault shape T179 named for the write gate has the same
        answer here: a session keel could not even resolve is not a project
        shown to be armed, and the message must not say it is."""
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp).joinpath(*(["d"] * (keel_gate.PROJECT_WALK_MAX_LEVELS + 2)))
            deep.mkdir(parents=True, exist_ok=True)
            session, _sess8 = fresh_session()
            original = keel_stop.evaluate

            def boom(*_a: object, **_k: object) -> keel_events.KeelVerdict:
                raise RuntimeError("deliberate fault, unresolved session")

            keel_stop.evaluate = boom
            try:
                verdict, _err = run_quietly(stop_event(deep, session))
            finally:
                keel_stop.evaluate = original
        self.assertEqual(verdict.decision, "deny")
        self.assertNotIn("This session's governing project is armed", verdict.reason)
        self.assertIn("could not confirm which project governs", verdict.reason)


#: EVERY SENTENCE THE TWO GATES CLAIM TO SHARE, by the name it is defined
#: under in the write gate. Membership is the contract: a sentence added to
#: one gate's message and not the other is either in this tuple and imported,
#: or it is one of the three exclusions the write gate's own comment names.
SHARED_SENTENCES = (
    "SELF_FAULT_ATTRIBUTION",
    "NEXT_STEP_SELF_FAULT",
    "ARMING_FILE_IS_THE_FAULT",
    "NEXT_STEP_ARMING_FILE",
    "ARMING_FILE_IS_NOT_THE_FAULT",
    "NEXT_STEP_FAULT_UNATTRIBUTED",
)

#: The clause the first cut of this fix dropped. Named on its own because it
#: is the specific drift the review caught, and a regression here would be
#: invisible to a substring test of the sentence's opening words.
DRIFTED_CLAUSE = "exactly as it did three times on 2026-08-19"

#: A self-fault sentence in the shape the classifier really returns.
SELF_FAULT_TEXT = "NameError: name 'read_ledger' is not defined (raised at keel_stop.py:1)"


class TestTheSharedSentencesAreOneDefinition(unittest.TestCase):
    """Accept 2, structurally rather than by inspection. Two gates describing
    one condition two ways is not prevented by a test that notices it after
    the fact: the sentences are DEFINED ONCE in the write gate and IMPORTED
    here, so ``assertIs`` on the object is the whole assertion - a copy would
    be an equal string at another address, and an edited copy not even equal.
    """

    def test_every_shared_sentence_is_the_same_object_in_both_gates(self) -> None:
        for name in SHARED_SENTENCES:
            with self.subTest(sentence=name):
                self.assertIs(getattr(keel_stop, name), getattr(keel_gate, name))

    def test_the_dropped_clause_is_back_and_in_both_gates(self) -> None:
        self.assertIn(DRIFTED_CLAUSE, keel_gate.NEXT_STEP_SELF_FAULT)
        self.assertIn(DRIFTED_CLAUSE, keel_stop.NEXT_STEP_SELF_FAULT)


class TestTheTwoGatesSayTheSameThing(unittest.TestCase):
    """The same three shapes, rendered side by side and compared as WHOLE
    sentences rather than as substrings. What may differ is named here rather
    than left to inference: the head sentence, the armed note, and the write
    gate's ledger note."""

    def _rendered(self, root: Path, self_fault: str) -> tuple[list[str], list[str]]:
        detail = "RuntimeError: deliberate fault"
        write_event = keel_events.KeelEvent(
            kind="pre_write", cwd=root, session_id="abcdef12", raw={}
        )
        stop = keel_stop.cannot_account_message(
            stop_event(root, "abcdef12"), root, detail, self_fault
        )
        gate = keel_gate.cannot_evaluate_message(write_event, root, detail, self_fault, {})
        return stop.split("\n"), gate.split("\n")

    def test_the_shared_sentences_are_identical_in_all_three_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            clean = armed(Path(tmp) / "clean")
            broken = unparseable(Path(tmp) / "broken")
            cases = (
                ("keel's own defect", clean, SELF_FAULT_TEXT),
                ("a broken arming file", broken, ""),
                ("neither", clean, ""),
            )
            for label, root, self_fault in cases:
                stop_lines, gate_lines = self._rendered(root, self_fault)
                with self.subTest(shape=label):
                    # Lines 3 and 4 are the attribution and its next step: the
                    # shared pair. The write gate carries one line more, its
                    # ledger note, which is a Stop-irrelevant exclusion.
                    self.assertEqual(stop_lines[2:4], gate_lines[2:4])
                    self.assertEqual(len(stop_lines), 4)
                    self.assertEqual(len(gate_lines), 5)

    def test_only_the_named_exclusions_differ(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = armed(Path(tmp) / "clean")
            stop_lines, gate_lines = self._rendered(root, SELF_FAULT_TEXT)
        self.assertNotEqual(stop_lines[0], gate_lines[0])  # what each gate DID
        self.assertNotEqual(stop_lines[1], gate_lines[1])  # armed, but about what
        self.assertIn("could not account for the session", stop_lines[0])
        self.assertIn("could not evaluate this request", gate_lines[0])
        self.assertIn("is still writable", gate_lines[4])
        self.assertNotIn("is still writable", "\n".join(stop_lines))


class TestTheHandlerHasItsOwnHandler(unittest.TestCase):
    """THE FAIL-OPEN THIS FIX CLOSES, and it is not hypothetical: the stop
    gate does not own its own exit code. An exception escaping ``run`` reaches
    the launcher, whose declared fail-open returns 0 - an ALLOW - so a raise
    while merely WORDING the refusal inverted a fail-closed deny into a
    session permitted to stop unaccounted. Before the outer guard every case
    below raised out of ``run``; after it, each returns a deny."""

    @contextmanager
    def _raising(self, name: str, exc: BaseException) -> Iterator[None]:
        """Replace a symbol the failure path calls with one that raises."""
        original = getattr(keel_stop, name)

        def boom(*_a: object, **_k: object) -> object:
            raise exc

        setattr(keel_stop, name, boom)
        try:
            yield
        finally:
            setattr(keel_stop, name, original)

    def _double_fault(
        self, project: Path, name: str, exc: BaseException
    ) -> tuple[keel_events.KeelVerdict, str]:
        """A stop whose ``evaluate`` fails AND whose failure path fails too."""
        session, sess8 = fresh_session()
        write_ledger(project, sess8, "# Plan\n\n- [ ] T9 open\n")
        with missing_symbol(CALL_SITE_SYMBOL), self._raising(name, exc):
            return run_quietly(stop_event(project, session))

    def test_a_message_builder_that_raises_still_denies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, err = self._double_fault(
                project, "cannot_account_message", ValueError("embedded null byte")
            )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.to_exit_code(), 2)
        self.assertEqual(verdict.reason, keel_stop.STOP_DOUBLE_FAULT)
        self.assertIn("could not word the refusal", verdict.reason)
        self.assertIn("failure policy failed too", err)
        self.assertIn("embedded null byte", err)

    def test_an_arming_file_test_that_raises_still_denies(self) -> None:
        """The arming-file test is called while deciding whom to blame, so a
        raise from it lands in the middle of wording the refusal.

        THE REVIEW NAMED A CONCRETE TRIGGER FOR THIS AND IT DOES NOT HOLD, so
        the raise here is injected rather than provoked: a null byte in the
        path was expected to reach ``policy_present`` as a ``ValueError`` it
        does not catch, but CPython 3.10's own ``Path.is_file`` catches
        ``ValueError`` ("non-encodable path") and returns False. What the
        guard is for is the class, not that one route."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, _err = self._double_fault(
                project, "policy_present", ValueError("embedded null byte")
            )
        self.assertEqual(verdict.decision, "deny")
        self.assertEqual(verdict.reason, keel_stop.STOP_DOUBLE_FAULT)

    def test_a_project_resolution_that_raises_still_denies(self) -> None:
        """Resolution is already caught inside the failure path, so this one
        must land on the ORDINARY refusal, not the bare one - the guard added
        for the double fault may not swallow a fault that was handled."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, _err = self._double_fault(
                project, "resolve_governing_project", ValueError("embedded null byte")
            )
        self.assertEqual(verdict.decision, "deny")
        self.assertIn("KEEL STOP FAILED CLOSED", verdict.reason)
        self.assertNotEqual(verdict.reason, keel_stop.STOP_DOUBLE_FAULT)

    def test_the_fallback_quotes_no_fault_text_at_all(self) -> None:
        """A fallback that formats untrusted input can fail the way the thing
        it covers for just did, so this one formats nothing: the fault goes to
        stderr and the reason is a constant with no placeholder in it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, err = self._double_fault(
                project,
                "cannot_account_message",
                ValueError("a very {distinctive} fault"),
            )
        self.assertNotIn("distinctive", verdict.reason)
        self.assertIn("distinctive", err)
        self.assertNotIn("{", keel_stop.STOP_DOUBLE_FAULT)
        self.assertNotIn(POLICY_RELPATH, verdict.reason)

    def test_the_bare_refusal_is_still_recorded(self) -> None:
        """The fallback drops the wording, not the record: a block that cannot
        be worded is still audited and still marks the session."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed(Path(tmp) / "project")
            verdict, _err = self._double_fault(
                project, "cannot_account_message", RuntimeError("no words left")
            )
            log = project / ".keel" / "audit" / "keel-audit.jsonl"
            self.assertTrue(log.is_file())
            lines = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        self.assertTrue(verdict.blocking)
        self.assertEqual([entry["event"] for entry in lines], ["stop_block"])
        self.assertEqual(lines[0]["gate"], "internal_error")

if __name__ == "__main__":  # pragma: no cover - manual runs only
    unittest.main()
