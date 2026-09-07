#!/usr/bin/env python3
"""The policy-lock relaxation framework and the override reminders.

Contract
--------
Reads   : ``hooks/keel_gate.py``, ``hooks/keel_session.py`` and
          ``hooks/keel_stop.py`` as modules, plus the launcher as a
          subprocess. The declarative half of this feature ships as fixtures
          under tests/fixtures/gate/, tests/fixtures/stop/ and
          tests/fixtures/session/, executed by tests/test_keel_kernel.py and
          tests/test_keel_wave2.py; what lives here is the part a fixture
          cannot state - the parser's edge cases, the vocabulary's
          invariants, and the ABSENT direction of each reminder.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. Every
          subprocess runs with an environment stripped of ``KEEL_*`` and
          ``CLAUDE_PROJECT_DIR``, so the developer's own shell - which for
          this feature is very likely to be an overridden one - cannot change
          what a test observes.

Both directions, everywhere. A relaxation test that only proves the demotion
happens is half a test: the half that matters is the one proving it does not
happen for a diff that is not version-only, for a name keel never shipped,
for a file it cannot read, or for the anchor.

Failure policy
--------------
FAIL-CLOSED, as every build gate is: an environment that cannot run a check
fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string. Every file operation names its encoding.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "hooks" / "keel_hook.py"

sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_gate  # noqa: E402  (path must be set first)
import keel_session  # noqa: E402
import keel_stop  # noqa: E402
from keel_events import KeelEvent  # noqa: E402

MANIFEST = json.dumps(
    {"name": "fixture", "version": "0.4.0", "keywords": ["a", "b"], "nested": {"x": 1}},
    indent=2,
)


def clean_env(scratch: Path) -> dict[str, str]:
    """The environment a subprocess here runs with: no keel state at all.

    ``HOME``/``USERPROFILE`` are pointed at ``scratch`` rather than left as
    the real ones: several cases here launch a real ``session`` SessionStart
    against an adopted or armed fixture, which feeds keel's user-global fleet
    registry (T227) - a write that reads ``Path.home()`` regardless of the
    ``KEEL_*`` scrub above, so leaving them untouched would write fixture
    debris into the developer's real ``~/.claude/keel/keel-registry.json``.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KEEL_") and key != "CLAUDE_PROJECT_DIR"
    }
    env.update({"TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch)})
    env.update({"HOME": str(scratch), "USERPROFILE": str(scratch)})
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def fingerprint(root: Path) -> list[tuple[str, str]]:
    """Every file under ``root`` as (relative path, content hash), sorted.

    The instrument for "an unadopted project is left untouched": a hook that
    created, touched or changed one byte anywhere shows up as a different
    list. Same pattern as the dashboard's no-write proof in the wave-3 suite.
    """
    out: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append((path.relative_to(root).as_posix(), digest))
    return out


def build_project(root: Path, policy_body: str = "", manifest: str | None = None) -> Path:
    """An armed fixture project, optionally carrying a configuration section."""
    project = root / "project"
    policy = project / ".keel" / "keel-policy.md"
    policy.parent.mkdir(parents=True, exist_ok=True)
    policy.write_text(f"---\ntier: 2\n---\n\n# policy\n{policy_body}", encoding="utf-8")
    if manifest is not None:
        target = project / ".claude-plugin" / "plugin.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(manifest, encoding="utf-8")
    return project


def write_event(project: Path, session: str, tool_input: dict[str, Any]) -> KeelEvent:
    """One pre_write event carrying a harness-shaped payload, as the adapter makes it."""
    paths = [tool_input[key] for key in ("file_path",) if key in tool_input]
    return KeelEvent(
        kind="pre_write",
        cwd=project,
        session_id=session,
        tool_name="Edit",
        file_paths=tuple(paths),
        raw={"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": tool_input},
    )


class TestSectionParser(unittest.TestCase):
    """Line-based and forgiving, but never guessing (convention 3)."""

    def test_absent_section_is_absent(self) -> None:
        present, lock, relax = keel_gate.parse_lock_section("# policy\n\nprose only\n")
        self.assertFalse(present)
        self.assertEqual((lock, relax), ([], []))

    def test_heading_matches_in_any_case_and_at_any_depth(self) -> None:
        headings = ("## Policy lock", "### POLICY LOCK", "#### policy   lock:", "## Policy Lock")
        for heading in headings:
            with self.subTest(heading=heading):
                present, _, relax = keel_gate.parse_lock_section(
                    f"{heading}\n\nrelax:\n- release-version-bump\n"
                )
                self.assertTrue(present, heading)
                self.assertEqual(relax, ["release-version-bump"])

    def test_whitespace_and_bullets_are_forgiven_but_indentation_is_not(self) -> None:
        """Forgiving about everything EXCEPT the column the line starts in.

        This case asserted the opposite until 2026-08-19 - that a leading
        indent is forgiven too - and that assertion was itself the defect: a
        four-space Markdown code block is how a document marks an EXAMPLE, so
        forgiving the indent let documentation under '## Policy lock' parse as
        ratified law (keel_gate: A RATIFIED LIST LINE STARTS AT COLUMN ZERO).
        The forgiveness that was never in question is kept and still asserted:
        the bullet character, the space before the colon, tabs after the
        bullet, backticks around a value, and blank lines between items.
        """
        body = (
            "## Policy lock\n"
            "\n"
            "lock :\n"
            "-   src/one\n"
            "*  `src/two`\n"
            "\n"
            "relax:\n"
            "-\trelease-version-bump\n"
        )
        _, lock, relax = keel_gate.parse_lock_section(body)
        self.assertEqual(lock, ["src/one", "src/two"])
        self.assertEqual(relax, ["release-version-bump"])

    def test_an_indented_list_declares_nothing_and_is_reported(self) -> None:
        """The other direction of the same rule, in the same place the old
        contract lived, so a reader of this class cannot miss which way it
        goes. The full family is pinned in tests/test_keel_gate_t169.py."""
        body = (
            "## Policy lock\n"
            "\n"
            "Example:\n"
            "\n"
            "    lock:\n"
            "    - src/one\n"
        )
        _, lock, relax = keel_gate.parse_lock_section(body)
        self.assertEqual((lock, relax), ([], []))
        self.assertEqual(keel_gate.indented_list_lines(body), ["lock:", "- src/one"])

    def test_the_next_heading_closes_the_section(self) -> None:
        body = (
            "## Policy lock\n\nlock:\n- src/one\n\n"
            "## Holds\n\nrelax:\n- release-version-bump\n"
        )
        _, lock, relax = keel_gate.parse_lock_section(body)
        self.assertEqual(lock, ["src/one"])
        self.assertEqual(relax, [], "a list under another heading is not this section's")

    def test_prose_ends_the_list_it_follows(self) -> None:
        body = "## Policy lock\n\nlock:\n- src/one\nthis paragraph is not a list\n- src/two\n"
        _, lock, _ = keel_gate.parse_lock_section(body)
        self.assertEqual(lock, ["src/one"])

    def test_a_list_head_without_entries_yields_nothing(self) -> None:
        _, lock, relax = keel_gate.parse_lock_section("## Policy lock\n\nlock:\n\nrelax:\n")
        self.assertEqual((lock, relax), ([], []))


class TestSectionValidation(unittest.TestCase):
    """Fail closed, visibly: a section keel cannot honour honours nothing."""

    def _section(self, body: str) -> keel_gate.LockSection:
        with tempfile.TemporaryDirectory() as tmp:
            return keel_gate.policy_lock_section(build_project(Path(tmp), body))

    def test_a_valid_section_is_honoured(self) -> None:
        section = self._section(
            "\n## Policy lock\n\nlock:\n- src/one\n\nrelax:\n- release-version-bump\n"
        )
        self.assertTrue(section.valid)
        self.assertEqual(section.locked_paths, ("src/one",))
        self.assertTrue(section.relaxes("release-version-bump"))

    def test_no_section_relaxes_nothing_and_locks_nothing_extra(self) -> None:
        section = self._section("\nnothing configured here\n")
        self.assertFalse(section.present)
        self.assertTrue(section.valid)
        self.assertEqual(section.locked_paths, ())
        self.assertFalse(section.relaxes("release-version-bump"))

    def test_an_unknown_name_invalidates_the_whole_section(self) -> None:
        section = self._section(
            "\n## Policy lock\n\nlock:\n- src/one\n\nrelax:\n- release-version-bump\n- teleport\n"
        )
        self.assertFalse(section.valid)
        self.assertIn("teleport", " ".join(section.errors))
        self.assertEqual(section.locked_paths, (), "an invalid section tightens nothing either")
        self.assertFalse(section.relaxes("release-version-bump"))

    def test_a_lock_entry_over_the_ledger_directory_is_refused(self) -> None:
        for entry in (".keel/plans", ".keel/plans/", ".keel/plans/keel-plan-abcd1234.md", ".keel"):
            with self.subTest(entry=entry):
                section = self._section(f"\n## Policy lock\n\nlock:\n- {entry}\n")
                self.assertFalse(section.valid, entry)
                self.assertIn("session ledgers live", " ".join(section.errors))

    def test_the_refusal_message_carries_the_configuration_error(self) -> None:
        section = self._section("\n## Policy lock\n\nrelax:\n- teleport\n")
        line = keel_gate.config_error_line(section)
        self.assertIn("teleport", line)
        self.assertIn("full default lock applies", line)
        self.assertEqual(keel_gate.config_error_line(keel_gate.LockSection()), "")

    def test_a_project_with_no_arming_file_has_no_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bare"
            project.mkdir()
            self.assertEqual(keel_gate.policy_body(project), "")
            section = keel_gate.policy_lock_section(project)
            self.assertFalse(section.present)
            self.assertFalse(section.relaxes("release-version-bump"))

    def test_a_file_with_no_frontmatter_is_read_as_a_body(self) -> None:
        """Forgiving on shape, strict on meaning: the tier check owns validity."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "loose"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "## Policy lock\n\nrelax:\n- release-version-bump\n", encoding="utf-8"
            )
            self.assertTrue(keel_gate.policy_lock_section(project).relaxes("release-version-bump"))


class TestVocabularyInvariants(unittest.TestCase):
    """Design rule 3: the anchor is not relaxable BY CONSTRUCTION."""

    def test_v1_ships_exactly_one_entry(self) -> None:
        self.assertEqual(set(keel_gate.RELAXATIONS), {"release-version-bump"})

    def test_every_vocabulary_entry_has_a_checker_and_the_reverse(self) -> None:
        self.assertEqual(set(keel_gate.RELAXATIONS), set(keel_gate._RELAX_CHECKS))

    def test_no_vocabulary_entry_names_an_anchor_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            for name, (parts, _) in keel_gate.RELAXATIONS.items():
                with self.subTest(relaxation=name):
                    target = keel_gate.norm(project, os.path.join(*parts))
                    self.assertFalse(keel_gate.is_anchor(project, target), name)
                    self.assertTrue(
                        keel_gate.is_protected(project, target),
                        "a relaxation that targets an unlocked path relaxes nothing",
                    )

    def test_the_anchor_is_refused_even_by_a_rogue_vocabulary_entry(self) -> None:
        """The second belt: a future entry aimed at the anchor is a no-op."""
        session = uuid.uuid4().hex
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n"
            )
            event = write_event(
                project, session, {"file_path": ".keel/keel-policy.md", "content": "x"}
            )
            section = keel_gate.policy_lock_section(project)
            original = dict(keel_gate._RELAX_CHECKS)
            keel_gate._RELAX_CHECKS["release-version-bump"] = lambda *a, **k: True
            try:
                self.assertIsNone(
                    keel_gate.relaxation_for(event, project, ".keel/keel-policy.md", section)
                )
            finally:
                keel_gate._RELAX_CHECKS.clear()
                keel_gate._RELAX_CHECKS.update(original)

    def test_the_design_rules_are_declared_in_the_module(self) -> None:
        doc = keel_gate.__doc__ or ""
        self.assertIn("THE ANCHOR IS NEVER RELAXABLE BY CONSTRUCTION", doc)
        self.assertIn("A RELAXATION ONLY EVER DEMOTES DENY TO ASK", doc)
        self.assertIn("INDETERMINABLE IS DENY", doc)


class TestProtectedSetExtension(unittest.TestCase):
    """Tightening is unrestricted; the anchor set is a subset of the locked set."""

    def test_extra_entries_lock_a_file_and_a_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            extra = ("src/generated", "docs/frozen.md")
            for relative in ("src/generated", "src/generated/deep/api.py", "docs/frozen.md"):
                with self.subTest(path=relative):
                    target = keel_gate.norm(project, relative)
                    self.assertTrue(keel_gate.is_protected(project, target, extra))
                    self.assertFalse(keel_gate.is_protected(project, target))

    def test_a_sibling_with_a_longer_name_is_not_swallowed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            target = keel_gate.norm(project, "src/generated2/api.py")
            self.assertFalse(keel_gate.is_protected(project, target, ("src/generated",)))

    def test_the_anchor_and_the_merely_locked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            anchors = (".keel/keel-policy.md", "hooks/keel_gate.py", ".claude/settings.json")
            for relative in anchors:
                with self.subTest(anchor=relative):
                    self.assertTrue(
                        keel_gate.is_anchor(project, keel_gate.norm(project, relative))
                    )
            for relative in (".claude-plugin/plugin.json", "src/app.py"):
                with self.subTest(not_anchor=relative):
                    self.assertFalse(
                        keel_gate.is_anchor(project, keel_gate.norm(project, relative))
                    )


class TestVersionDiff(unittest.TestCase):
    """"Only the version value" is a comparison, never a guess about intent."""

    def _after(self, **changes: Any) -> str:
        document = json.loads(MANIFEST)
        document.update(changes)
        return json.dumps(document, indent=2)

    def test_a_version_only_change_is_recognised(self) -> None:
        self.assertTrue(keel_gate.differs_only_in_version(MANIFEST, self._after(version="9.9.9")))

    def test_reformatting_alone_is_still_version_only(self) -> None:
        compact = json.dumps(json.loads(MANIFEST), separators=(",", ":"))
        self.assertTrue(keel_gate.differs_only_in_version(MANIFEST, compact))

    def test_any_other_change_is_refused(self) -> None:
        cases = {
            "added key": self._after(version="9.9.9", surprise=True),
            "changed value": self._after(version="9.9.9", name="other"),
            "nested change": self._after(version="9.9.9", nested={"x": 2}),
            "list change": self._after(version="9.9.9", keywords=["a", "b", "c"]),
        }
        for label, after in cases.items():
            with self.subTest(case=label):
                self.assertFalse(keel_gate.differs_only_in_version(MANIFEST, after))

    def test_a_removed_key_is_refused(self) -> None:
        document = json.loads(MANIFEST)
        document.pop("keywords")
        self.assertFalse(keel_gate.differs_only_in_version(MANIFEST, json.dumps(document)))

    def test_anything_that_is_not_a_json_object_is_refused(self) -> None:
        for before, after in (
            (MANIFEST, "not json at all {{{"),
            ("not json at all {{{", MANIFEST),
            (MANIFEST, "[1, 2, 3]"),
            ('{"version": 4}', '{"version": 5}'),
            ('{"name": "x"}', '{"name": "y"}'),
        ):
            with self.subTest(after=after[:20]):
                self.assertFalse(keel_gate.differs_only_in_version(before, after))


class TestResultingContent(unittest.TestCase):
    """Indeterminable is deny: the payload shapes keel understands, and the rest."""

    def test_a_full_write_is_its_own_result(self) -> None:
        self.assertEqual(keel_gate.resulting_content("old", {"content": "new"}), "new")

    def test_a_single_edit_is_applied_in_memory(self) -> None:
        result = keel_gate.resulting_content(
            "a b c", {"old_string": "b", "new_string": "B"}
        )
        self.assertEqual(result, "a B c")

    def test_an_ambiguous_edit_is_indeterminable(self) -> None:
        self.assertIsNone(
            keel_gate.resulting_content("b b", {"old_string": "b", "new_string": "B"})
        )

    def test_replace_all_resolves_the_ambiguity(self) -> None:
        result = keel_gate.resulting_content(
            "b b", {"old_string": "b", "new_string": "B", "replace_all": True}
        )
        self.assertEqual(result, "B B")

    def test_an_absent_old_string_is_indeterminable(self) -> None:
        self.assertIsNone(
            keel_gate.resulting_content("a", {"old_string": "zzz", "new_string": "B"})
        )

    def test_a_multi_edit_chain_is_applied_in_order(self) -> None:
        result = keel_gate.resulting_content(
            "a b",
            {
                "edits": [
                    {"old_string": "a", "new_string": "x"},
                    {"old_string": "b", "new_string": "y"},
                ]
            },
        )
        self.assertEqual(result, "x y")

    def test_a_shape_with_no_content_is_indeterminable(self) -> None:
        for tool_input in ({}, {"notebook_path": "n.ipynb"}, {"edits": []}, {"edits": ["x"]},
                           {"old_string": 4, "new_string": "b"}, {"content": 17}):
            with self.subTest(tool_input=tool_input):
                self.assertIsNone(keel_gate.resulting_content("a", tool_input))


class TestRelaxationVerdicts(unittest.TestCase):
    """The demotion, and every road that does not lead to it."""

    def _verdict(self, project: Path, tool_input: dict[str, Any], **paths: str) -> Any:
        session = uuid.uuid4().hex
        plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("- [ ] T1: cut a release | AC: none\n", encoding="utf-8")
        event = write_event(project, session, tool_input)
        if paths.get("extra"):
            event = KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=session,
                tool_name="MultiEdit",
                file_paths=(tool_input["file_path"], paths["extra"]),
                raw={"tool_name": "MultiEdit", "tool_input": tool_input},
            )
        return keel_gate.evaluate(event, env={})

    def _bump(self) -> dict[str, Any]:
        return {
            "file_path": ".claude-plugin/plugin.json",
            "old_string": '"version": "0.4.0"',
            "new_string": '"version": "0.5.0"',
        }

    def test_the_demotion_is_ask_and_names_the_relaxation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n", MANIFEST
            )
            verdict = self._verdict(project, self._bump())
            self.assertEqual(verdict.decision, "ask")
            self.assertEqual(verdict.to_exit_code(), 2, "ask blocks; it never allows")
            self.assertIn("release-version-bump", verdict.reason)

    def test_a_missing_manifest_on_disk_stays_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n"
            )
            verdict = self._verdict(project, self._bump())
            self.assertEqual(verdict.decision, "deny")

    def test_a_manifest_that_is_not_json_stays_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp),
                "\n## Policy lock\n\nrelax:\n- release-version-bump\n",
                'not json {{{ "version": "0.4.0"',
            )
            verdict = self._verdict(project, self._bump())
            self.assertEqual(verdict.decision, "deny")

    def test_a_payload_with_no_content_stays_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n", MANIFEST
            )
            verdict = self._verdict(project, {"file_path": ".claude-plugin/plugin.json"})
            self.assertEqual(verdict.decision, "deny")

    def test_a_payload_naming_a_second_file_stays_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n", MANIFEST
            )
            verdict = self._verdict(project, self._bump(), extra="hooks/keel_gate.py")
            self.assertEqual(verdict.decision, "deny")

    def test_the_ask_is_audited_apart_from_a_denial(self) -> None:
        """A prompt is not a refusal: the friction count must not swallow it."""
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n", MANIFEST
            )
            verdict = self._verdict(project, self._bump())
            self.assertEqual(verdict.gate, "policy_lock_relaxed")
            self.assertNotEqual(verdict.gate, "policy_lock")


class TestUnverifiableTargets(unittest.TestCase):
    """A path keel cannot resolve is not a path keel may allow.

    ``norm`` answers "" for a target it cannot normalise, and ``is_protected``
    answers False for "" because there is nothing to compare - so the write
    path must test for it FIRST or an unresolvable target walks straight past
    the lock into the plan check and out through an allow. Both directions
    are exercised against ONE project, so the only difference between the
    deny and the allow is the path itself. The declarative half of this is
    tests/fixtures/gate/28-an-unverifiable-target-denies.json, run end to end
    by the kernel suite.
    """

    #: A path no platform can resolve: an embedded NUL byte. Written as an
    #: escape rather than a literal so the source of this file stays text.
    UNRESOLVABLE = "src/\u0000app.py"

    def _verdict(self, project: Path, file_path: str, **env: str) -> Any:
        session = uuid.uuid4().hex
        plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text("- [x] T1: edit a file | AC: none\n", encoding="utf-8")
        event = write_event(project, session, {"file_path": file_path, "content": "x = 1\n"})
        return keel_gate.evaluate(event, env=env)

    def test_norm_reports_the_failure_as_the_empty_string(self) -> None:
        """The premise, pinned: "" is 'could not resolve', not 'not protected'."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            self.assertEqual(keel_gate.norm(project, self.UNRESOLVABLE), "")
            self.assertFalse(keel_gate.is_protected(project, ""))
            self.assertFalse(keel_gate.is_plan_target(project, ""))

    def test_a_target_that_cannot_be_normalised_is_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            verdict = self._verdict(project, self.UNRESOLVABLE)
            self.assertEqual(verdict.decision, "deny")
            self.assertEqual(verdict.to_exit_code(), 2)
            self.assertEqual(verdict.gate, "unverifiable_target")
            self.assertIn("could not be verified against the policy lock", verdict.reason)

    def test_the_same_write_with_a_resolvable_path_still_allows(self) -> None:
        """The other direction: nothing else about this call changed."""
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            verdict = self._verdict(project, "src/app.py")
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.to_exit_code(), 0)
            self.assertEqual(verdict.gate, "plan")

    def test_the_override_does_not_unblock_what_keel_cannot_read(self) -> None:
        """The override suspends a lock; it cannot decide about an unknown."""
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            verdict = self._verdict(project, self.UNRESOLVABLE, KEEL_OVERRIDE="on")
            self.assertEqual(verdict.decision, "deny")

    def test_an_unresolvable_second_path_denies_a_multi_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            session = uuid.uuid4().hex
            plan = project / ".keel" / "plans" / f"keel-plan-{session[:8]}.md"
            plan.parent.mkdir(parents=True, exist_ok=True)
            plan.write_text("- [x] T1: edit files | AC: none\n", encoding="utf-8")
            event = KeelEvent(
                kind="pre_write",
                cwd=project,
                session_id=session,
                tool_name="MultiEdit",
                file_paths=("src/app.py", self.UNRESOLVABLE),
                raw={"tool_name": "MultiEdit", "tool_input": {"file_path": "src/app.py"}},
            )
            self.assertEqual(keel_gate.evaluate(event, env={}).decision, "deny")

    def test_the_refusal_echoes_no_control_character_back(self) -> None:
        """A path keel could not read is rendered, never repeated verbatim."""
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            verdict = self._verdict(project, self.UNRESOLVABLE)
            self.assertNotIn("\u0000", verdict.reason)
            self.assertNotIn("\\u0000", json.dumps(dict(verdict.detail)))
            self.assertIn("src/?app.py", verdict.reason)
            self.assertEqual(verdict.detail["target"], "src/?app.py")

    def test_a_refusal_nobody_can_act_on_still_names_a_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp))
            reason = self._verdict(project, self.UNRESOLVABLE).reason
            self.assertIn("NEXT STEP:", reason)
            self.assertLessEqual(len(reason.splitlines()), 3, "one to three lines")

    def test_the_rule_is_declared_in_the_module(self) -> None:
        self.assertIn("UNVERIFIABLE IS DENY", keel_gate.__doc__ or "")


class TestRefusalMessages(unittest.TestCase):
    """Adjustment 2: a refusal is a redirect, never a dead end."""

    def _message(self, project: Path, target: str) -> str:
        event = write_event(project, uuid.uuid4().hex, {"file_path": target})
        return keel_gate.policy_lock_message(
            event, target, cwd=project, section=keel_gate.policy_lock_section(project)
        )

    def test_each_target_names_its_own_next_step(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(Path(tmp), "\n## Policy lock\n\nlock:\n- src/generated\n")
            cases = {
                ".keel/keel-policy.md": "refit skill",
                "hooks/keel_gate.py": "KEEL_OVERRIDE=on",
                ".claude/settings.json": "KEEL_OVERRIDE=on",
                ".claude-plugin/plugin.json": "release-version-bump",
                "src/generated/api.py": "added to the lock by the",
            }
            for target, expected in cases.items():
                with self.subTest(target=target):
                    message = self._message(project, target)
                    self.assertIn("NEXT STEP:", message)
                    self.assertIn(expected, message)
                    self.assertLessEqual(len(message.splitlines()), 3, "one to three lines")

    def test_the_manifest_line_changes_once_the_relaxation_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = build_project(
                Path(tmp), "\n## Policy lock\n\nrelax:\n- release-version-bump\n"
            )
            message = self._message(project, ".claude-plugin/plugin.json")
            self.assertIn("is enabled here, but this write changes", message)

    def test_a_shell_refusal_names_a_next_step_too(self) -> None:
        for command, expected in (
            ("sed -i s/x/y/ .keel/keel-policy.md", "refit skill"),
            ("rm hooks/keel_gate.py", "KEEL_OVERRIDE=on"),
        ):
            with self.subTest(command=command):
                event = KeelEvent(
                    kind="pre_exec", cwd=REPO_ROOT, tool_name="Bash", command=command
                )
                message = keel_gate.shell_policy_lock_message(event)
                self.assertIn("NEXT STEP:", message)
                self.assertIn(expected, message)
                self.assertLessEqual(len(message.splitlines()), 3)


class TestOverrideReminders(unittest.TestCase):
    """Once per event, short, never blocking - and gone the moment it is off."""

    def _run(self, subcommand: str, payload: dict, project: Path, scratch: Path,
             **extra: str) -> subprocess.CompletedProcess:
        env = clean_env(scratch)
        env.update(extra)
        return subprocess.run(
            [sys.executable, "-B", str(HOOK), subcommand],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(project),
            timeout=60,
            check=False,
        )

    def _dirs(self, tmp: str) -> tuple[Path, Path]:
        root = Path(tmp)
        project = build_project(root)
        scratch = root / "tmp"
        scratch.mkdir()
        return project, scratch

    def test_one_reminder_is_shared_by_every_surface(self) -> None:
        self.assertIn("KEEL_OVERRIDE", keel_gate.OVERRIDE_REMINDER)
        self.assertEqual(len(keel_gate.OVERRIDE_REMINDER.splitlines()), 1, "one line, always")
        self.assertIs(keel_session.OVERRIDE_REMINDER, keel_gate.OVERRIDE_REMINDER)
        self.assertIs(keel_stop.OVERRIDE_REMINDER, keel_gate.OVERRIDE_REMINDER)

    def test_session_start_is_silent_about_a_lock_that_is_not_suspended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._dirs(tmp)
            payload = {
                "hook_event_name": "SessionStart",
                "session_id": uuid.uuid4().hex,
                "cwd": str(project),
            }
            result = self._run("session", payload, project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("YOUR session plan file is", result.stdout)
            self.assertNotIn("POLICY LOCK SUSPENDED", result.stdout)

    def test_the_reminder_follows_the_plan_line_rather_than_replacing_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._dirs(tmp)
            session = uuid.uuid4().hex
            payload = {
                "hook_event_name": "SessionStart",
                "session_id": session,
                "cwd": str(project),
            }
            result = self._run("session", payload, project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            lines = result.stdout.splitlines()
            self.assertTrue(lines[0].startswith("[keel] This project runs under"), lines)
            self.assertIn("POLICY LOCK SUSPENDED", lines[1])
            self.assertEqual(
                sum("POLICY LOCK SUSPENDED" in line for line in lines), 1, "once per event"
            )

    def test_a_tier_one_project_with_override_gets_no_reminder_at_session_start(self) -> None:
        """ARMED AT THE ENFORCING TIER, not merely adopted (mirrors keel_stop's
        armed_for_reminders): a tier-1 project's lock is not suspended by
        KEEL_OVERRIDE because it never enforced one to begin with."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True)
            policy.write_text("---\ntier: 1\n---\n\n# policy\n", encoding="utf-8")
            scratch = root / "tmp"
            scratch.mkdir()
            session = uuid.uuid4().hex
            payload = {
                "hook_event_name": "SessionStart",
                "session_id": session,
                "cwd": str(project),
            }
            result = self._run("session", payload, project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("YOUR session plan file is", result.stdout)
            self.assertNotIn("POLICY LOCK SUSPENDED", result.stdout)

    def test_stop_is_silent_about_a_lock_that_is_not_suspended(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._dirs(tmp)
            session = uuid.uuid4().hex
            payload = {"hook_event_name": "Stop", "session_id": session, "cwd": str(project)}
            result = self._run("stop", payload, project, scratch)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("POLICY LOCK SUSPENDED", result.stderr)
            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            self.assertFalse(audit.is_file(), "an ordinary allowed stop writes nothing")

    def test_stop_reminds_on_stderr_and_records_it_without_deciding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._dirs(tmp)
            session = uuid.uuid4().hex
            payload = {"hook_event_name": "Stop", "session_id": session, "cwd": str(project)}
            result = self._run("stop", payload, project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "", "allow is silence: the reminder is not a decision")
            self.assertIn("POLICY LOCK SUSPENDED", result.stderr)
            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            recorded = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([entry["event"] for entry in recorded], ["override_active_at_stop"])
            self.assertEqual(recorded[0]["session"], session)

    def test_a_reminder_that_cannot_be_recorded_still_does_not_block(self) -> None:
        """Fail-open, in the surface whose whole job is to be harmless."""
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = self._dirs(tmp)
            event = KeelEvent(kind="stop", cwd=project, session_id=uuid.uuid4().hex)
            original = keel_stop.append_audit

            def boom(*args: Any, **kwargs: Any) -> None:
                raise OSError("deliberate fault")

            keel_stop.append_audit = boom
            try:
                verdict = keel_stop.run(event, env={"KEEL_OVERRIDE": "on"})
            finally:
                keel_stop.append_audit = original
            self.assertEqual(verdict.decision, "allow")
            self.assertEqual(verdict.to_exit_code(), 0)


class TestRemindersAreScopedToArmedProjects(unittest.TestCase):
    """R25 at a stop: keel says nothing about a lock a project never had.

    The stop reminder is not only stderr - it is also an
    ``override_active_at_stop`` audit line, and writing one CREATES
    ``.keel/audit/`` in whatever directory the session happens to sit in. A
    developer with ``KEEL_OVERRIDE`` set at the user level visits a project
    that never adopted keel; that project must come out of the visit
    byte-identical. Both directions ship: the armed project still hears it,
    exactly as tests/fixtures/stop/16-keel-override-allows.json asserts.
    """

    def _run_stop(self, project: Path, scratch: Path, **extra: str) -> Any:
        env = clean_env(scratch)
        env.update(extra)
        payload = {
            "hook_event_name": "Stop",
            "session_id": uuid.uuid4().hex,
            "cwd": str(project),
        }
        return subprocess.run(
            [sys.executable, "-B", str(HOOK), "stop"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=str(project),
            timeout=60,
            check=False,
        )

    def _project(self, root: Path, tier: int | None) -> tuple[Path, Path]:
        """A project with content of its own, armed at ``tier`` or not at all."""
        project = root / "project"
        (project / "src").mkdir(parents=True)
        (project / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
        if tier is not None:
            policy = project / ".keel" / "keel-policy.md"
            policy.parent.mkdir(parents=True, exist_ok=True)
            policy.write_text(f"---\ntier: {tier}\n---\n\n# policy\n", encoding="utf-8")
        scratch = root / "tmp"
        scratch.mkdir()
        return project, scratch

    def test_arming_is_decided_before_the_override_is_consulted(self) -> None:
        """The ordering itself, read off the verdict rather than its effects."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "bare"
            project.mkdir()
            event = KeelEvent(kind="stop", cwd=project, session_id=uuid.uuid4().hex)
            verdict = keel_stop.evaluate(event, env={"KEEL_OVERRIDE": "on"})
            self.assertEqual(verdict.gate, "unarmed", "the override answered before arming did")
            self.assertEqual(verdict.decision, "allow")

    def test_a_project_that_never_adopted_keel_is_left_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp), tier=None)
            before = fingerprint(project)
            result = self._run_stop(project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "", "allow is silence")
            self.assertNotIn("POLICY LOCK SUSPENDED", result.stderr)
            self.assertFalse(
                (project / ".keel").exists(), "keel created state in an unadopted project"
            )
            self.assertEqual(before, fingerprint(project), "the stop hook wrote something")

    def test_a_project_below_the_enforcing_tier_is_left_byte_identical_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp), tier=1)
            before = fingerprint(project)
            result = self._run_stop(project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("POLICY LOCK SUSPENDED", result.stderr)
            self.assertFalse(
                (project / ".keel" / "audit").exists(), "an observing tier writes no audit line"
            )
            self.assertEqual(before, fingerprint(project), "the stop hook wrote something")

    def test_the_armed_project_still_hears_it(self) -> None:
        """The other direction, in the same shape as the two above."""
        with tempfile.TemporaryDirectory() as tmp:
            project, scratch = self._project(Path(tmp), tier=2)
            result = self._run_stop(project, scratch, KEEL_OVERRIDE="on")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("POLICY LOCK SUSPENDED", result.stderr)
            audit = project / ".keel" / "audit" / "keel-audit.jsonl"
            recorded = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual([entry["event"] for entry in recorded], ["override_active_at_stop"])

    def test_the_arming_test_the_reminder_uses_never_raises(self) -> None:
        """A footnote may not fail a stop that already allowed."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "broken"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "no frontmatter at all\n", encoding="utf-8"
            )
            with self.assertRaises(keel_stop.GateError):
                keel_stop.policy_tier(project)
            self.assertFalse(keel_stop.armed_for_reminders(project))

    def test_the_session_arming_test_the_reminder_uses_never_raises_either(self) -> None:
        """The same footnote guarantee, on keel_session's mirror of the helper."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "broken"
            (project / ".keel").mkdir(parents=True)
            (project / ".keel" / "keel-policy.md").write_text(
                "no frontmatter at all\n", encoding="utf-8"
            )
            with self.assertRaises(keel_gate.GateError):
                keel_gate.policy_tier(project)
            self.assertFalse(keel_session.armed_for_reminders(project))


if __name__ == "__main__":
    unittest.main()
