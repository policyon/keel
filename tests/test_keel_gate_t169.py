#!/usr/bin/env python3
"""T169 - the gate stops manufacturing bypasses, and the workshop is enforced.

Contract
--------
Reads   : ``hooks/keel_gate.py`` and ``hooks/keel_session.py`` as modules, and
          this repository's own ``.keel/keel-policy.md`` in exactly one case -
          the one whose subject IS the ratified declaration. Every other case
          builds its own fixture project, so no verdict here depends on the
          tree the suite happens to run in.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.
Argv    : none.

What this covers, and why each half exists
------------------------------------------
Three measured problems, one ratified decision, and the fixtures under
``tests/fixtures/gate/56-*`` through ``74-*`` pin the end-to-end verdicts. This
file pins what a fixture cannot see: the predicates themselves, in both
directions, and the two places the ALLOW direction has to be provably closed.

1. THE READ-ONLY ALLOWLIST (rule 2). ``sed_is_print_only`` and the ``find``
   disqualifier open two named doors in a list that is otherwise closed-world.
   The cases below assert the doors AND the walls: a redirect, a substitution,
   a chained mutation, a second sed flag, a ``w`` command inside a sed script,
   an unlisted word, a leading assignment, an unterminated quote and an empty
   command are all still NOT read-only. The direction of every failure is
   "needs a plan", never "runs".
2. THE WORKSHOP RULE (design rules 1-6 in the gate). The governance surface is
   screened TWICE - once on the configuration (``workshop_entry_refusal``) and
   once on the target (``workshop_forbidden``) - so the second case here
   constructs a ``LockSection`` the parser would never produce and proves the
   target screen still refuses it. A workshop write still faces the plan gate,
   the workshop never reaches a shell command, and an invalid section carries
   no workshop at all.
3. THE OVERRIDE'S AGE (item 3). Derived from the audit record, because the
   environment cannot tell an inherited value from a fresh one. All four
   answers are asserted, including the two failure shapes: an unreadable log
   and lines carrying no timestamp both say UNKNOWN, and neither falls silent.
   The switch is never refused or expired - a kill switch is the user's law.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. No pytest. Every file operation names its
encoding. A backslash is built with ``chr(92)`` rather than typed, because a
``[\\/]`` class collapses through a heredoc into one that matches no Windows
path at all - a defect this repository has already paid for once.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from keel_published_cut import (  # noqa: E402
    is_published_cut,
    shipped_policy_documents,
)
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_session  # noqa: E402

#: The backslash, built rather than typed - see the module docstring.
BACKSLASH = chr(92)

#: A contract-clean session ledger, so a case that means to exercise the policy
#: lock is never answered by the plan gate instead.
LEDGER_TEXT = (
    "# Plan\n\n- [ ] T1 the thing\n      Route: standard (keel:executor).\n"
    "      Accept: it works.\n"
)

SESS8 = "abcd1234"
SESSION = SESS8 + "-0000-0000-0000-000000000000"


def armed_project(root: Path, *workshop: str, extra: str = "", plan: bool = True) -> Path:
    """A tier-2 project, optionally declaring a workshop and a fresh ledger."""
    project = root / "project"
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    body = "---\ntier: 2\n---\n\n# keel policy - fixture project\n"
    if workshop or extra:
        body += "\n## Policy lock\n\n"
        if extra:
            body += extra
        if workshop:
            body += "workshop:\n" + "".join(f"- {entry}\n" for entry in workshop)
    (project / ".keel" / "keel-policy.md").write_text(body, encoding="utf-8")
    if plan:
        (project / ".keel" / "plans" / f"keel-plan-{SESS8}.md").write_text(
            LEDGER_TEXT, encoding="utf-8"
        )
    return project


def write_event(project: Path, *paths: str) -> keel_events.KeelEvent:
    """One ``pre_write`` event naming one or more targets."""
    return keel_events.KeelEvent(
        kind="pre_write",
        cwd=project,
        session_id=SESSION,
        tool_name="Write",
        raw={"tool_input": {"file_path": paths[0], "content": "x = 1\n"}},
        file_paths=tuple(paths),
    )


def exec_event(project: Path, command: str) -> keel_events.KeelEvent:
    """One ``pre_exec`` event carrying command text."""
    return keel_events.KeelEvent(
        kind="pre_exec",
        cwd=project,
        session_id=SESSION,
        tool_name="Bash",
        raw={"tool_input": {"command": command}},
        command=command,
    )


def audit_lines(project: Path) -> list[dict]:
    """Every parsed audit line for a fixture project, oldest first."""
    path = project / ".keel" / "audit" / "keel-audit.jsonl"
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_quiet(event: keel_events.KeelEvent, env: dict[str, str]) -> keel_events.KeelVerdict:
    """``keel_gate.run`` with its stderr notices captured, not printed."""
    with redirect_stderr(io.StringIO()):
        return keel_gate.run(event, env)


# ------------------------------------------------- 1. the read-only allowlist


class TestPrintOnlySed(unittest.TestCase):
    """``sed_is_print_only`` opens ONE shape and refuses every other."""

    PRINTS = (
        ["sed", "-n", "p"],
        ["sed", "-n", "5p"],
        ["sed", "-n", "510,545p"],
        ["sed", "-n", "1,$p"],
        ["sed", "-n", "$p"],
        ["sed", "--quiet", "1,5p", "notes.md"],
        ["sed", "--silent", "1,5p", "a.md", "b.md"],
        ["sed", "-n", "1,5p", "-"],
    )

    EDITS = (
        ["sed"],
        ["sed", "-n"],
        ["sed", "1,5p"],  # no quiet flag: unproven, so it keeps its gate
        ["sed", "-i", "s/a/b/", "f"],
        ["sed", "-i.bak", "s/a/b/", "f"],
        ["sed", "--in-place", "s/a/b/", "f"],
        ["sed", "-ni", "1,5p", "f"],
        ["sed", "-n", "-e", "1p", "f"],
        ["sed", "-n", "-f", "script.sed", "f"],
        ["sed", "-n", "/secret/w leak.txt", "f"],
        ["sed", "-n", "1,5p;w out.txt", "f"],
        ["sed", "-n", "s/a/b/w out.txt", "f"],
        ["sed", "-n", "--", "1,5p", "f"],
        ["grep", "-n", "1,5p"],
    )

    def test_the_print_shape_clears(self) -> None:
        for tokens in self.PRINTS:
            with self.subTest(tokens=tokens):
                self.assertTrue(keel_gate.sed_is_print_only(tokens))

    def test_every_other_shape_does_not(self) -> None:
        for tokens in self.EDITS:
            with self.subTest(tokens=tokens):
                self.assertFalse(keel_gate.sed_is_print_only(tokens))


class TestTheReadOnlyAllowlist(unittest.TestCase):
    """Rule 2's scope, in both directions, on the command text itself."""

    READS = (
        "grep -n tier .keel/keel-policy.md | head -5",
        "grep -rn workshop . | wc -l",
        "diff a.md b.md",
        "ls -la",
        "pwd",
        "cat notes.md | tail -3",
        "find . -name '*.md'",
        "find . -type f -printf '%p\\n'",
        "sed -n '510,545p' .keel/plans/keel-plan-abcd1234.md",
        "sed -n '1,5p' a.md && cat b.md",
    )

    GATES = (
        "",
        "   ",
        "sed -i 's/a/b/' notes.md",
        "sed -n '/x/w leak.txt' notes.md",
        "find . -name '*.md' -delete",
        "find . -name '*.md' -exec rm {} ;",
        "find . -name '*.md' -execdir rm {} ;",
        "find . -name '*.md' -ok rm {} ;",
        "find . -name '*.md' -fprint out.txt",
        "find . -name '*.md' -fls out.txt",
        "grep -rn x . > out.txt",
        "grep -rn x . >> out.txt",
        "diff a.md b.md; rm a.md",
        # PIPED siblings of the chained case above: a regression in
        # per-segment checking across "|" specifically would otherwise pass
        # every case in this file (reviewer finding, 2026-08-19).
        "cat notes.md | rm x",
        "ls | xargs rm",
        "grep -n x f | tee out.txt",
        "cat a.md | python -",
        "head -5 f | sed -i s/a/b/ g",
        "find . -name '*.md' | xargs sed -i s/a/b/",
        "ls -la | head -3 | rm -f x",
        "echo `cat notes.md`",
        "cat $(echo notes.md)",
        "cat <(echo hi)",
        "keel_override=on git status",
        "python -c 'print(1)'",
        "node script.js",
        "git commit -m x",
        "git diff --output=x",
        "cp a b",
        'grep -n "unterminated',
        "x" * (keel_gate._MAX_CMD + 1),
    )

    def test_a_read_only_command_needs_no_ledger(self) -> None:
        for command in self.READS:
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_is_read_only(command.casefold()))

    def test_everything_else_still_asks_for_one(self) -> None:
        for command in self.GATES:
            with self.subTest(command=command[:40]):
                self.assertFalse(keel_gate.shell_is_read_only(command.casefold()))

    def test_the_allowlist_words_are_the_documented_set(self) -> None:
        """A word joins this list by review, not by accident: the set is pinned
        so a future addition has to change a test that says what it is."""
        self.assertEqual(
            set(keel_gate._READ_ONLY_COMMANDS),
            {
                "cat", "grep", "egrep", "fgrep", "head", "tail", "wc",
                "ls", "pwd", "echo", "diff",
            },
        )
        for word in ("git", "rg", "python", "less", "xargs", "tee"):
            self.assertNotIn(word, keel_gate._READ_ONLY_COMMANDS)

    def test_the_git_subcommand_machinery_is_gone_not_merely_unused(self) -> None:
        """A dormant allowlist is a re-admission waiting to happen: the
        subcommand set and its write-flag disqualifier were DELETED, so nothing
        remains for a future edit to switch back on by accident."""
        self.assertFalse(hasattr(keel_gate, "_READ_ONLY_GIT_SUBCOMMANDS"))
        self.assertFalse(hasattr(keel_gate, "_GIT_WRITE_FLAG_PREFIXES"))


class TestConfigChosenProgramsAreNotReadOnly(unittest.TestCase):
    """THE CLASS behind the 2026-08-19 finding: an allowlisted NAME is not
    read-only when the binary consults repository, user or environment CONFIG
    to choose a subprocess. Both directions, per subcommand and per word."""

    #: Every git spelling that used to clear rule 2, plus the flag spellings
    #: that were offered as a middle path and refused.
    GIT = (
        "git status",
        "git status --short",
        "git log --oneline -5",
        "git log -p",
        "git log -p --no-ext-diff",
        "git diff",
        "git diff --no-ext-diff",
        "git diff --no-textconv",
        "git diff --no-ext-diff --no-textconv",
        "git show head",
        "git show --no-textconv head",
        "git ls-files",
        "git ls-files hooks",
        "git --no-pager diff",
        "git -c diff.external=/bin/sh diff",
        "git commit -am wip",
        "git push",
        "git add .",
        "git status --short | head -5",
        "cat notes.md && git status",
    )

    RIPGREP = (
        "rg -n tier .keel/keel-policy.md",
        "rg --files",
        "rg --pre cat -n x .",
    )

    def test_no_git_invocation_is_read_only(self) -> None:
        for command in self.GIT:
            with self.subTest(command=command):
                self.assertFalse(keel_gate.shell_is_read_only(command.casefold()))

    def test_no_ripgrep_invocation_is_read_only(self) -> None:
        for command in self.RIPGREP:
            with self.subTest(command=command):
                self.assertFalse(keel_gate.shell_is_read_only(command.casefold()))

    def test_the_words_that_stay_still_clear(self) -> None:
        """The other direction, so the fix is a scalpel and not an amputation:
        grep's only ever-configured input (the deprecated GREP_OPTIONS) could
        add FLAGS and no grep flag runs a program, and none of the remaining
        words reads a configuration file at all."""
        for command in (
            "grep -rn workshop hooks",
            "cat hooks/keel_gate.py | head -20",
            "ls -la hooks",
            "wc -l hooks/keel_gate.py",
            "diff hooks/keel_gate.py hooks/keel_stop.py",
            "find hooks -name '*.py'",
            "sed -n '1,20p' hooks/keel_gate.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_is_read_only(command.casefold()))

    def test_the_design_rule_states_the_class_and_the_rejected_middle_path(self) -> None:
        source = (REPO_ROOT / "hooks" / "keel_gate.py").read_text(encoding="utf-8")
        for phrase in (
            "NO CONFIGURATION MAY CHOOSE A PROGRAM FOR IT TO RUN",
            "THE MIDDLE PATH WAS CONSIDERED AND REJECTED",
            "core.fsmonitor",
            "RIPGREP_CONFIG_PATH",
            "THE PAGER",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, source)


class TestThePrintOnlySedExemptionOnTheLedgerScreen(unittest.TestCase):
    """Rule 3's one exemption - the measured false positive of 2026-08-18."""

    def test_a_print_of_a_ledger_is_not_a_write_of_one(self) -> None:
        self.assertFalse(
            keel_gate.shell_writes_session_ledger(
                "sed -n '510,545p' .keel/plans/keel-plan-abcd1234.md"
            )
        )

    def test_sed_in_place_on_a_ledger_still_denies(self) -> None:
        for command in (
            "sed -i 's/t1/t2/' .keel/plans/keel-plan-abcd1234.md",
            "sed -i.bak 's/t1/t2/' keel-plan-abcd1234.md",
            "sed --in-place 's/t1/t2/' keel-plan-abcd1234.md",
        ):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_writes_session_ledger(command.casefold()))

    def test_a_redirect_is_still_caught_behind_a_print_only_sed(self) -> None:
        """The exemption is applied AFTER the redirect test, so the one shape
        that writes a ledger through a print is still refused."""
        self.assertTrue(
            keel_gate.shell_writes_session_ledger(
                "sed -n '1,5p' notes.md > .keel/plans/keel-plan-abcd1234.md"
            )
        )

    def test_the_policy_lock_rule_now_takes_the_same_exemption(self) -> None:
        """SCOPE, RESTATED 2026-09-06 (T513/BL54). Until then this test asserted
        the OPPOSITE - rule 1 kept the over-block - and the reversal is the whole
        of that task: a print-only sed cannot write the file it names, so the
        lock refusing it was a false refusal, and every false refusal trains the
        user toward KEEL_OVERRIDE. The exemption now reaches all three rules
        through the ONE predicate (``_segment_word_is_read_only``)."""
        self.assertFalse(
            keel_gate.shell_hits_policy_lock("sed -n '1,5p' hooks/keel_gate.py")
        )

    def test_a_sed_that_is_not_provably_a_print_still_locks(self) -> None:
        """The other half of the same decision: the exemption is the proven
        shape and nothing near it. A regex address is NOT proven (it could hide
        a `w`), so BL54's own second observed command still refuses - stated as
        a test rather than left for a reader to rediscover as a bug."""
        for command in (
            "sed -n '/## policy lock/,/## holds/p' .keel/keel-policy.md",
            "sed -i 's/x/y/' hooks/keel_gate.py",
            "sed -n -e '1,5p' hooks/keel_gate.py",
            "sed '1,5p' hooks/keel_gate.py",
        ):
            with self.subTest(command=command):
                self.assertTrue(keel_gate.shell_hits_policy_lock(command))


# ----------------------------------------------------------- 2. the workshop


class TestWorkshopEntryRefusals(unittest.TestCase):
    """Workshop design rule 1, on the CONFIGURATION."""

    REFUSED = (
        "",
        "   ",
        ".",
        "./",
        "..",
        ".keel",
        ".keel/",
        ".keel/keel-policy.md",
        ".keel/settings.json",
        ".claude",
        ".claude/settings.json",
        ".claude/settings.local.json",
    )

    KEPT = ("hooks/", "scripts/", "tests/", "src/generated/", "docs")

    def test_the_governance_surface_is_refused_by_name_or_by_containment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            for entry in self.REFUSED:
                with self.subTest(entry=entry):
                    self.assertTrue(keel_gate.workshop_entry_refusal(project, entry))

    def test_a_source_prefix_is_kept(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            for entry in self.KEPT:
                with self.subTest(entry=entry):
                    self.assertEqual(keel_gate.workshop_entry_refusal(project, entry), "")

    def test_a_refused_entry_is_dropped_and_said_out_loud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/", ".keel/", ".claude/settings.json")
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(section.workshop_prefixes, ("hooks/",))
            self.assertEqual(len(section.workshop_refusals), 2)
            stream = io.StringIO()
            with redirect_stderr(stream):
                keel_gate.announce_workshop_refusals(section)
            said = stream.getvalue()
            self.assertIn(".keel/", said)
            self.assertIn(".claude/settings.json", said)
            self.assertIn("IGNORED as if it had not been declared", said)

    def test_an_invalid_section_carries_no_workshop_at_all(self) -> None:
        """Design rule 4 reaches the workshop: a configuration keel cannot
        understand widens nothing, so one unknown relaxation name empties the
        workshop as well as the lock."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(
                Path(tmp), "hooks/", extra="relax:\n- teleport\n\n"
            )
            section = keel_gate.policy_lock_section(project)
            self.assertFalse(section.valid)
            self.assertEqual(section.workshop, ("hooks/",))
            self.assertEqual(section.workshop_prefixes, ())
            self.assertEqual(section.locked_paths, ())

    def test_no_section_is_no_workshop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            section = keel_gate.policy_lock_section(project)
            self.assertFalse(section.present)
            self.assertEqual(section.workshop_prefixes, ())

    def test_a_fenced_example_declares_nothing_and_a_live_list_still_does(self) -> None:
        """THE CLASS behind the second 2026-08-19 finding: the policy parser
        may not read DOCUMENTATION as law. All three lists come from one parse,
        so all three are covered by one strip."""
        fenced_only = (
            "## Policy lock\n\nExample, for documentation only:\n\n"
            "```\nworkshop:\n- everything/\n\nlock:\n- src/one\n\nrelax:\n"
            "- teleport\n```\n\nProse after the fence.\n"
        )
        present, lists = keel_gate.parse_lock_lists(fenced_only)
        self.assertTrue(present, "the heading outside the fence is still a heading")
        self.assertEqual(lists["workshop"], [])
        self.assertEqual(lists["lock"], [])
        self.assertEqual(lists["relax"], [])

        both = fenced_only + "\nworkshop:\n- hooks/\n\nlock:\n- src/real\n"
        _present, live = keel_gate.parse_lock_lists(both)
        self.assertEqual(live["workshop"], ["hooks/"])
        self.assertEqual(live["lock"], ["src/real"])
        self.assertEqual(live["relax"], [])

    def test_a_fenced_example_cannot_open_a_workshop_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(
                Path(tmp),
                extra="An example:\n\n```\nworkshop:\n- hooks/\n```\n\n",
            )
            section = keel_gate.policy_lock_section(project)
            self.assertTrue(section.present)
            self.assertTrue(section.valid, "an example is not a malformation")
            self.assertEqual(section.workshop, ())
            self.assertEqual(section.workshop_prefixes, ())
            verdict = run_quiet(write_event(project, "hooks/keel_gate.py"), {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")

    def test_a_tilde_fence_and_a_longer_fence_close_by_the_same_rule(self) -> None:
        for body in (
            "## Policy lock\n\n~~~\nworkshop:\n- everything/\n~~~\n",
            "## Policy lock\n\n````text\nworkshop:\n- everything/\n````\n",
            "## Policy lock\n\n  ```\n  workshop:\n  - everything/\n  ```\n",
        ):
            with self.subTest(body=body.splitlines()[2]):
                _present, lists = keel_gate.parse_lock_lists(body)
                self.assertEqual(lists["workshop"], [])

    def test_an_inner_fence_does_not_close_a_longer_outer_one(self) -> None:
        body = (
            "## Policy lock\n\n````\n```\nworkshop:\n- everything/\n```\n````\n"
            "\nworkshop:\n- hooks/\n"
        )
        _present, lists = keel_gate.parse_lock_lists(body)
        self.assertEqual(lists["workshop"], ["hooks/"])

    def test_an_unclosed_fence_invalidates_the_section_visibly(self) -> None:
        """Dropping the rest of the file silently would LOOSEN a lock, so an
        unfinished claim about what is an example is an error instead: nothing
        tightens, nothing loosens, and the refusal message says why."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(
                Path(tmp), extra="```\nworkshop:\n- hooks/\n\nlock:\n- src/one\n"
            )
            section = keel_gate.policy_lock_section(project)
            self.assertFalse(section.valid)
            self.assertEqual(section.workshop_prefixes, ())
            self.assertEqual(section.locked_paths, ())
            self.assertIn("never closed", " ".join(section.errors))
            self.assertIn("never closed", keel_gate.config_error_line(section))

    def test_the_shipped_template_teaches_without_declaring(self) -> None:
        """The defect was LIVE in what keel ships: templates/keel-policy.md
        documents the section with a fenced example, and an adopter copying it
        verbatim used to get 'src/generated/' locked and 'release-version-bump'
        relaxed without having decided either."""
        template = (REPO_ROOT / "templates" / "keel-policy.md").read_text(encoding="utf-8")
        self.assertIn("lock:", template, "the premise: the template shows the lists")
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(template, encoding="utf-8")
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(section.lock, ())
            self.assertEqual(section.relax, ())
            self.assertEqual(section.workshop_prefixes, ())
            self.assertTrue(section.valid, section.errors)

    def test_an_indented_example_declares_nothing(self) -> None:
        """The other half of the same Markdown convention (finding, 2026-08-19):
        an example marked by INDENTATION rather than by a fence must be read as
        documentation too. Both the list head and its entries are indented here,
        which is how a four-space code block is actually written."""
        body = (
            "## Policy lock\n\nExample:\n\n"
            "    workshop:\n    - everything/\n\n"
            "    lock:\n    - /\n\n"
            "    relax:\n    - teleport\n\nProse after.\n"
        )
        present, lists = keel_gate.parse_lock_lists(body)
        self.assertTrue(present)
        self.assertEqual(lists["workshop"], [])
        self.assertEqual(lists["lock"], [])
        self.assertEqual(lists["relax"], [])

    def test_an_indented_list_is_reported_rather_than_absorbed(self) -> None:
        """Ignored is never silent: the owner who meant a list and indented it
        sees exactly which lines were refused and why."""
        body = "## Policy lock\n\nExample:\n\n    workshop:\n    - everything/\n"
        self.assertEqual(
            keel_gate.indented_list_lines(body), ["workshop:", "- everything/"]
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(
                Path(tmp), extra="Example:\n\n    workshop:\n    - everything/\n\n"
            )
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(section.workshop_prefixes, ())
            self.assertEqual(section.ignored_indented, ("workshop:", "- everything/"))
            stream = io.StringIO()
            with redirect_stderr(stream):
                keel_gate.announce_ignored_indented_lines(section)
            said = stream.getvalue()
            self.assertIn("INDENTED list line", said)
            self.assertIn("column 0", said)
            self.assertIn("everything/", said)
            self.assertEqual(len(said.strip().splitlines()), 2, "one note per line")

    def test_a_misindented_entry_under_a_live_head_is_reported_too(self) -> None:
        """The likeliest honest mistake - a real head with indented entries -
        declares nothing and says so."""
        body = "## Policy lock\n\nworkshop:\n  - hooks/\n"
        _present, lists = keel_gate.parse_lock_lists(body)
        self.assertEqual(lists["workshop"], [])
        self.assertEqual(keel_gate.indented_list_lines(body), ["- hooks/"])

    def test_a_column_zero_list_beside_an_indented_example_parses_exactly_itself(self) -> None:
        body = (
            "## Policy lock\n\nworkshop:\n- hooks/\n\nlock:\n- src/real\n\n"
            "Example, indented:\n\n    workshop:\n    - everything/\n"
        )
        _present, lists = keel_gate.parse_lock_lists(body)
        self.assertEqual(lists["workshop"], ["hooks/"])
        self.assertEqual(lists["lock"], ["src/real"])
        self.assertEqual(keel_gate.indented_list_lines(body), ["workshop:", "- everything/"])

    def test_ordinary_indented_prose_bullets_are_not_reported(self) -> None:
        """The note is bounded on purpose: an indented bullet only counts while
        a list is open, so prose keeps its sub-bullets without a false alarm."""
        body = (
            "## Policy lock\n\nNotes:\n\n- a bullet at column zero\n"
            "  - an indented prose bullet\n"
        )
        self.assertEqual(keel_gate.indented_list_lines(body), [])

    def test_neither_shipped_policy_document_produces_a_note(self) -> None:
        """Scanned before the rule landed, and pinned so it stays true: the law
        as actually written sits at column zero in both documents."""
        for relative in shipped_policy_documents(REPO_ROOT):
            with self.subTest(document=relative):
                body = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(keel_gate.indented_list_lines(body), [])

    def test_the_live_workshop_fixture_declares_at_column_zero(self) -> None:
        """Fixture 81's premise is the column-zero form - asserted here rather
        than assumed, since the whole rule now turns on that column."""
        fixture = json.loads(
            (
                REPO_ROOT
                / "tests"
                / "fixtures"
                / "gate"
                / "81-a-live-list-outside-a-fence-is-still-law.json"
            ).read_text(encoding="utf-8")
        )
        text = fixture["files"][0]["text"]
        self.assertIn("\nworkshop:\n- hooks/\n", text)

    def test_the_design_rule_states_the_choice_and_the_rejected_shape(self) -> None:
        source = (REPO_ROOT / "hooks" / "keel_gate.py").read_text(encoding="utf-8")
        for phrase in (
            "A RATIFIED LIST LINE STARTS AT COLUMN ZERO",
            "HALF-FAITHFUL IMPLEMENTATION OF A SPEC",
            "THE FAILURE DIRECTION IS SAFE AND LOUD",
            "NOISE IS BOUNDED ON PURPOSE",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, source)

    def test_the_three_lists_are_parsed_by_one_parser(self) -> None:
        body = (
            "## Policy lock\n\nlock:\n- src/one\n\nrelax:\n"
            "- release-version-bump\n\nworkshop:\n- hooks/\n- tests/\n"
        )
        present, lists = keel_gate.parse_lock_lists(body)
        self.assertTrue(present)
        self.assertEqual(lists["lock"], ["src/one"])
        self.assertEqual(lists["relax"], ["release-version-bump"])
        self.assertEqual(lists["workshop"], ["hooks/", "tests/"])
        # The older two-list view stays exactly as its callers know it.
        self.assertEqual(
            keel_gate.parse_lock_section(body),
            (True, ["src/one"], ["release-version-bump"]),
        )


class TestWorkshopTargetScreen(unittest.TestCase):
    """Workshop design rule 1, on the TARGET - the screen a parser bug cannot
    bypass, because it does not consult the parser."""

    def test_a_forged_section_still_cannot_reach_the_governance_surface(self) -> None:
        forged = keel_gate.LockSection(
            present=True, workshop=(".", ".keel/", ".keel/keel-policy.md", "hooks/")
        )
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            for relative in (
                ".keel/keel-policy.md",
                ".keel/settings.json",
                ".claude/settings.json",
                ".claude/settings.local.json",
            ):
                with self.subTest(relative=relative):
                    target = keel_gate.norm(project, relative)
                    self.assertTrue(keel_gate.workshop_forbidden(project, target))
                    self.assertEqual(
                        keel_gate.workshop_prefix_for(project, target, forged), ""
                    )

    def test_a_workshop_path_reports_the_entry_that_covered_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/", "scripts/")
            section = keel_gate.policy_lock_section(project)
            # A BACKSLASH IS A SEPARATOR ONLY WHERE THE PLATFORM SAYS SO. On
            # Windows ``hooks\\keel_gate.py`` names a file inside the workshop
            # entry; on POSIX the backslash is an ordinary filename character,
            # so that string names ONE file at the project root and no workshop
            # entry covers it. The empty answer there is the fail-closed one —
            # an uncovered path is refused rather than allowed-plus-audited —
            # so both expectations assert safety, not a platform quirk.
            # Measured on Linux 2026-09-01: this tuple was the suite's only
            # genuine platform failure (BL17 cause (c)).
            backslash_is_a_separator = BACKSLASH in (os.sep, os.altsep)
            for relative, expected in (
                ("hooks/keel_gate.py", "hooks/"),
                ("hooks/nested/deep.py", "hooks/"),
                (
                    f"hooks{BACKSLASH}keel_gate.py",
                    "hooks/" if backslash_is_a_separator else "",
                ),
                ("scripts/keel_checks.py", "scripts/"),
                ("docs/keel-rules.md", ""),
            ):
                with self.subTest(relative=relative):
                    target = keel_gate.norm(project, relative)
                    self.assertEqual(
                        keel_gate.workshop_prefix_for(project, target, section), expected
                    )

    def test_an_unresolvable_target_is_never_a_workshop_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            section = keel_gate.policy_lock_section(project)
            self.assertEqual(keel_gate.workshop_prefix_for(project, "", section), "")


class TestWorkshopVerdicts(unittest.TestCase):
    """The write path end to end, with the audit line each verdict owes."""

    def test_a_workshop_write_is_allowed_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(write_event(project, "hooks/keel_gate.py"), {})
            self.assertEqual(verdict.decision, "allow")
            lines = audit_lines(project)
            self.assertEqual([line["event"] for line in lines], ["workshop_write"])
            self.assertEqual(lines[0]["detail"]["target"], "hooks/keel_gate.py")
            self.assertEqual(lines[0]["detail"]["workshop"], "hooks/")
            self.assertEqual(lines[0]["session"], SESSION)
            self.assertRegex(lines[0]["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_the_governance_surface_still_denies_under_a_workshop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            for relative in (".keel/keel-policy.md", ".claude/settings.json"):
                with self.subTest(relative=relative):
                    verdict = run_quiet(write_event(project, relative), {})
                    self.assertEqual(verdict.decision, "deny")
                    self.assertEqual(verdict.gate, "policy_lock")

    def test_a_multi_target_write_is_decided_by_its_worst_target(self) -> None:
        """One workshop path may not carry a governance path in with it, and no
        workshop_write is recorded for a write that was refused."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(
                write_event(project, "hooks/keel_gate.py", ".keel/keel-policy.md"), {}
            )
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(
                [line["event"] for line in audit_lines(project)], ["gate_block"]
            )

    def test_a_workshop_write_still_faces_the_plan_gate(self) -> None:
        """Design rule 3: the workshop demotes rule 1 only."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/", plan=False)
            verdict = run_quiet(write_event(project, "hooks/keel_gate.py"), {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "plan")
            events = [line["event"] for line in audit_lines(project)]
            self.assertEqual(events, ["workshop_write", "gate_block"])

    def test_the_workshop_never_reaches_a_shell_command(self) -> None:
        """Design rule 4: a command names no target the gate can resolve, so
        the lock stands over commands whatever the workshop says. Asserted over
        a family of spellings, not one - and fixture 76 asserts the same thing
        through the subprocess path, because an in-process check cannot see the
        launcher, the adapter or the exit code (reviewer finding, 2026-08-19)."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            for command in (
                "rm hooks/keel_gate.py",
                "mv hooks/keel_gate.py /tmp/x",
                "Set-Content hooks/keel_gate.py 'x'",
                "sed -i 's/deny/allow/' hooks/keel_gate.py",
                "cp x hooks/keel_events.py",
                "cd hooks && rm keel_gate.py",
                "echo x > hooks/keel_gate.py",
            ):
                with self.subTest(command=command):
                    verdict = run_quiet(exec_event(project, command.casefold()), {})
                    self.assertEqual(verdict.decision, "deny", command)
                    self.assertEqual(verdict.gate, "policy_lock", command)

    def test_a_read_of_a_workshop_path_is_still_a_read(self) -> None:
        """The other direction of the same scope line: refusing COMMANDS the
        workshop does not cover is not the same as refusing reads, which never
        hit the lock in the first place.

        THE FIRST CASE CHANGED ANSWER ON 2026-09-06 (T513/BL54) and the scope
        line did not: it used to deny, because ``sed`` was read as a mutation
        whatever its flags, and it now allows because a proven print writes
        nothing. The workshop is still not what decides it - the command is -
        which the mutating spelling beside it keeps pinned end to end.
        """
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(
                exec_event(project, "sed -n '1,20p' hooks/keel_gate.py".casefold()), {}
            )
            self.assertEqual(verdict.decision, "allow", "a proven print is a read")
            verdict = run_quiet(
                exec_event(project, "sed -i 's/a/b/' hooks/keel_gate.py".casefold()), {}
            )
            self.assertEqual(verdict.decision, "deny", "rule 1 is unchanged here")
            self.assertEqual(verdict.gate, "policy_lock")
            verdict = run_quiet(
                exec_event(project, "grep -n workshop docs".casefold()), {}
            )
            self.assertEqual(verdict.decision, "allow")

    def test_an_undeclared_project_behaves_exactly_as_before(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            verdict = run_quiet(write_event(project, "hooks/keel_gate.py"), {})
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.gate, "policy_lock")
            self.assertEqual(
                [line["event"] for line in audit_lines(project)], ["gate_block"]
            )


class TestWorkshopComposesWithTheOverride(unittest.TestCase):
    """Design rule 6: the switch does not absorb the workshop's accounting."""

    def test_a_workshop_target_under_the_override_is_a_workshop_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(
                write_event(project, "hooks/keel_gate.py"), {"KEEL_OVERRIDE": "on"}
            )
            self.assertEqual(verdict.decision, "allow")
            events = [line["event"] for line in audit_lines(project)]
            self.assertEqual(events, ["workshop_write"])
            self.assertNotIn("gate_bypass", events)

    def test_a_target_outside_it_is_still_a_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(
                write_event(project, ".keel/keel-policy.md"), {"KEEL_OVERRIDE": "on"}
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(
                [line["event"] for line in audit_lines(project)], ["gate_bypass"]
            )

    def test_a_mixed_payload_under_the_override_records_both_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            verdict = run_quiet(
                write_event(project, "hooks/keel_gate.py", ".keel/keel-policy.md"),
                {"KEEL_OVERRIDE": "on"},
            )
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(
                [line["event"] for line in audit_lines(project)],
                ["workshop_write", "gate_bypass"],
            )

    def test_both_kinds_are_written_by_one_helper(self) -> None:
        """One writer, one chokepoint: the two kinds cannot drift into two
        shapes, and neither reaches the log without passing redaction."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp), "hooks/")
            event = write_event(project, "hooks/keel_gate.py")
            keel_gate._audit_lock_event(event, "workshop_write", {"target": "x"})
            keel_gate._audit_lock_event(event, "gate_bypass", {"target": "x"})
            first, second = audit_lines(project)
            self.assertEqual(set(first) - {"event"}, set(second) - {"event"})
            self.assertEqual(first["gate"], "policy_lock")


class TestThisRepositorysOwnDeclarationIsEnforced(unittest.TestCase):
    """The one case whose subject IS this tree: the ratified declaration of
    2026-08-18 is law, and this asserts the gate now reads it rather than
    leaving the standing override as the bridge."""

    def test_the_ratified_prefixes_are_in_force_here(self) -> None:
        """INVERTS IN A PUBLISHED CUT: the workshop declaration is a section OF
        THE ARMING FILE, and a cut ships none, so no prefix is in force there -
        which is correct, since a cut has no development to license."""
        section = keel_gate.policy_lock_section(REPO_ROOT)
        if is_published_cut(REPO_ROOT):
            self.assertEqual(section.workshop_prefixes, ())
            self.assertEqual(section.relax, ())
            return
        self.assertEqual(section.workshop_prefixes, ("hooks/", "scripts/", "tests/"))
        self.assertEqual(section.workshop_refusals, ())
        # The fence strip must not have swallowed this file's own live lists.
        self.assertEqual(section.relax, ("release-version-bump",))
        self.assertTrue(section.valid, section.errors)
        for relative, expected in (
            ("hooks/keel_gate.py", "hooks/"),
            ("scripts/keel_checks.py", "scripts/"),
            ("tests/test_keel_gate_t169.py", "tests/"),
            (".keel/keel-policy.md", ""),
            (".claude/settings.json", ""),
            ("docs/keel-rules.md", ""),
        ):
            with self.subTest(relative=relative):
                target = keel_gate.norm(REPO_ROOT, relative)
                self.assertEqual(
                    keel_gate.workshop_prefix_for(REPO_ROOT, target, section), expected
                )

    def test_the_gate_declares_the_rule_it_now_enforces(self) -> None:
        doc = keel_gate.__doc__ or ""
        self.assertIn("THE WORKSHOP RULE", doc)
        self.assertIn("workshop_write", doc)
        self.assertIn("ALLOW-PLUS-LOUD-AUDIT", doc)


# ------------------------------------------------------ 3. the override's age


def _stamp(days_ago: float) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_audit(project: Path, *lines: dict) -> Path:
    path = project / ".keel" / "audit" / "keel-audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for line in lines:
            handle.write(json.dumps(line) + "\n")
    return path


class TestTheOverrideAgeIsDerivedFromTheRecord(unittest.TestCase):
    """Item 3: the line names an age it can prove, or says it cannot."""

    def test_a_dated_answer_names_the_first_bypass_and_the_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(
                project,
                {"v": 1, "ts": _stamp(9), "event": "gate_bypass"},
                {"v": 1, "ts": _stamp(5), "event": "session_start"},
                {"v": 1, "ts": _stamp(2), "event": "gate_bypass"},
            )
            note = keel_gate.override_age_note(project)
            self.assertIn("2 gate_bypass line(s)", note)
            self.assertIn("9 day(s) ago", note)
            self.assertEqual(len(note.splitlines()), 1, "one line, always")

    def test_an_empty_record_says_so_rather_than_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            self.assertEqual(keel_gate.override_age_note(project), keel_gate.OVERRIDE_AGE_NONE)
            seed_audit(project, {"v": 1, "ts": _stamp(1), "event": "session_start"})
            self.assertEqual(keel_gate.override_age_note(project), keel_gate.OVERRIDE_AGE_NONE)

    def test_a_corrupt_line_costs_that_line_and_nothing_else(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            path = seed_audit(project, {"v": 1, "ts": _stamp(3), "event": "gate_bypass"})
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write("{ not json at all\n")
                handle.write("\n")
            note = keel_gate.override_age_note(project)
            self.assertIn("1 gate_bypass line(s)", note)

    def test_a_bypass_with_no_timestamp_is_unknown_never_a_guess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(project, {"v": 1, "event": "gate_bypass"})
            note = keel_gate.override_age_note(project)
            self.assertIn("OVERRIDE AGE: unknown", note)
            self.assertIn("timestamp", note)

    def test_an_unreadable_log_is_unknown_and_names_the_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(project, {"v": 1, "ts": _stamp(3), "event": "gate_bypass"})
            real_open = builtins.open

            def refuse(*args, **kwargs):
                if str(args[0]).endswith("keel-audit.jsonl"):
                    raise OSError("device is busy")
                return real_open(*args, **kwargs)

            builtins.open = refuse
            try:
                note = keel_gate.override_age_note(project)
            finally:
                builtins.open = real_open
            self.assertIn("OVERRIDE AGE: unknown", note)
            self.assertIn("could not be read", note)
            self.assertEqual(len(note.splitlines()), 1)

    def test_every_answer_is_one_non_empty_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            for label, seeder in (
                ("none", lambda: None),
                ("dated", lambda: seed_audit(
                    project, {"v": 1, "ts": _stamp(4), "event": "gate_bypass"})),
                ("no-ts", lambda: seed_audit(project, {"v": 1, "event": "gate_bypass"})),
            ):
                with self.subTest(case=label):
                    seeder()
                    note = keel_gate.override_age_note(project)
                    self.assertTrue(note.strip())
                    self.assertEqual(len(note.splitlines()), 1)


class TestTheSessionLineCarriesTheAge(unittest.TestCase):
    """The surface, not the helper: one line, extended - never a second one."""

    def test_the_reminder_and_the_age_are_one_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(project, {"v": 1, "ts": _stamp(6), "event": "gate_bypass"})
            line = keel_session.override_reminder(project, {"KEEL_OVERRIDE": "on"})
            self.assertEqual(len(line.splitlines()), 1, "one line, always")
            self.assertIn("POLICY LOCK SUSPENDED", line)
            self.assertIn("OVERRIDE AGE:", line)
            self.assertIn("6 day(s) ago", line)

    def test_the_switch_off_says_nothing_at_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(project, {"v": 1, "ts": _stamp(6), "event": "gate_bypass"})
            self.assertEqual(keel_session.override_reminder(project, {}), "")
            self.assertEqual(
                keel_session.override_reminder(project, {"KEEL_OVERRIDE": "off"}), ""
            )

    def test_an_unarmed_project_still_has_no_lock_to_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "---\ntier: 1\n---\n", encoding="utf-8"
            )
            self.assertEqual(
                keel_session.override_reminder(project, {"KEEL_OVERRIDE": "on"}), ""
            )

    def test_the_age_never_refuses_or_expires_the_switch(self) -> None:
        """A kill switch is the user's law: however old the record says the
        override is, the verdict for a locked write is still an allow."""
        with tempfile.TemporaryDirectory() as tmp:
            project = armed_project(Path(tmp))
            seed_audit(project, {"v": 1, "ts": _stamp(400), "event": "gate_bypass"})
            verdict = run_quiet(
                write_event(project, ".keel/keel-policy.md"), {"KEEL_OVERRIDE": "on"}
            )
            self.assertEqual(verdict.decision, "allow")

    def test_the_gate_owns_the_sentence_and_the_clause(self) -> None:
        self.assertIs(keel_session.OVERRIDE_REMINDER, keel_gate.OVERRIDE_REMINDER)
        self.assertIs(keel_session.override_age_note, keel_gate.override_age_note)


if __name__ == "__main__":
    unittest.main()
