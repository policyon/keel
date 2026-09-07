#!/usr/bin/env python3
"""tests for ``keel scratch-board`` (T456) - finished-at derivation and parity.

Contract
--------
Reads   : nothing outside temporary git fixture repositories this file builds
          and removes.
Emits   : unittest results only.
Writes  : nothing outside the temporary directories it creates.

Failure policy
--------------
FAIL-CLOSED, as every build-gate test here is: an environment that cannot run
a check fails the check rather than skipping it.

Constraints
-----------
Python 3.10+, standard library only. ``git`` is invoked with an argument list,
never a shell string (R5). Every file operation names its encoding.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import keel_scratch_board as board  # noqa: E402  (path must be set first)


def _git(args: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> str:
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout


class ScratchBoardFixture(unittest.TestCase):
    """A small git repo with two commits flipping one task, built once."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "repo"
        self.root.mkdir()
        _git(["init", "-q"], self.root)
        _git(["config", "user.email", "test@example.com"], self.root)  # keel-leak: ignore - a fixture identity for a throwaway repository, not a real address
        _git(["config", "user.name", "Test"], self.root)

        self.plans = self.root / ".keel" / "plans"
        self.plans.mkdir(parents=True)
        self.ledger = self.plans / "keel-plan-aaaaaaaa.md"

        # commit 1: T100 open, T101 open, T102 open
        self.ledger.write_text(
            "# session aaaaaaaa\n\n"
            "- [ ] T100 — Task A title\n"
            "- [ ] T101 — Task B title\n"
            "- [ ] T102 — Task C stays open\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], self.root)
        self.author_1 = "2026-01-01T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit 1"],
            self.root,
            extra_env={
                "GIT_AUTHOR_DATE": self.author_1,
                "GIT_COMMITTER_DATE": self.author_1,
            },
        )

        # commit 2: T100 flips to done
        self.ledger.write_text(
            "# session aaaaaaaa\n\n"
            "- [x] T100 — Task A title\n"
            "- [ ] T101 — Task B title\n"
            "- [ ] T102 — Task C stays open\n",
            encoding="utf-8",
        )
        _git(["add", "-A"], self.root)
        self.author_2 = "2026-01-02T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit 2"],
            self.root,
            extra_env={
                "GIT_AUTHOR_DATE": self.author_2,
                "GIT_COMMITTER_DATE": self.author_2,
            },
        )
        self.commit_2_hash = _git(["rev-parse", "HEAD"], self.root).strip()

        # working copy only: T101 becomes terminal, never committed
        self.ledger.write_text(
            "# session aaaaaaaa\n\n"
            "- [x] T100 — Task A title\n"
            "- [!] T101 — Task B title\n"
            "- [ ] T102 — Task C stays open\n",
            encoding="utf-8",
        )

        # a second ledger using the plain-hyphen separator, one committed
        # terminal task, to prove the alternate separator parses.
        self.ledger2 = self.plans / "keel-plan-bbbbbbbb.md"
        self.ledger2.write_text(
            "# session bbbbbbbb\n\n- [x] T200 - Hyphen separated title\n",
            encoding="utf-8",
        )
        # add ONLY the new ledger - the uncommitted T101 edit above must stay
        # unstaged and uncommitted, which is exactly what this fixture tests.
        _git(["add", str(self.ledger2)], self.root)
        self.author_3 = "2026-01-03T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit 3"],
            self.root,
            extra_env={
                "GIT_AUTHOR_DATE": self.author_3,
                "GIT_COMMITTER_DATE": self.author_3,
            },
        )
        self.commit_3_hash = _git(["rev-parse", "HEAD"], self.root).strip()

        # a third ledger whose one task is terminal, reopened, then terminal
        # again - the ONLY fixture that can distinguish "first terminal
        # commit" from "last terminal commit": T300 goes
        # [ ] (commit a) -> [x] (commit b, the answer) -> [ ] (commit c,
        # reopened) -> [!] (commit d, its CURRENT status). A detector that
        # returns the last match instead of the first would report commit d,
        # not commit b.
        self.ledger3 = self.plans / "keel-plan-cccccccc.md"

        self.ledger3.write_text(
            "# session cccccccc\n\n- [ ] T300 — Reopened task\n", encoding="utf-8"
        )
        _git(["add", str(self.ledger3)], self.root)
        author_a = "2026-01-04T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit a: T300 open"],
            self.root,
            extra_env={"GIT_AUTHOR_DATE": author_a, "GIT_COMMITTER_DATE": author_a},
        )

        self.ledger3.write_text(
            "# session cccccccc\n\n- [x] T300 — Reopened task\n", encoding="utf-8"
        )
        _git(["add", str(self.ledger3)], self.root)
        self.author_b = "2026-01-05T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit b: T300 first terminal"],
            self.root,
            extra_env={
                "GIT_AUTHOR_DATE": self.author_b,
                "GIT_COMMITTER_DATE": self.author_b,
            },
        )
        self.commit_b_hash = _git(["rev-parse", "HEAD"], self.root).strip()

        self.ledger3.write_text(
            "# session cccccccc\n\n- [ ] T300 — Reopened task\n", encoding="utf-8"
        )
        _git(["add", str(self.ledger3)], self.root)
        author_c = "2026-01-06T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit c: T300 reopened"],
            self.root,
            extra_env={"GIT_AUTHOR_DATE": author_c, "GIT_COMMITTER_DATE": author_c},
        )

        self.ledger3.write_text(
            "# session cccccccc\n\n- [!] T300 — Reopened task\n", encoding="utf-8"
        )
        _git(["add", str(self.ledger3)], self.root)
        author_d = "2026-01-07T00:00:00+00:00"
        _git(
            ["commit", "-q", "-m", "commit d: T300 terminal again"],
            self.root,
            extra_env={"GIT_AUTHOR_DATE": author_d, "GIT_COMMITTER_DATE": author_d},
        )
        self.commit_d_hash = _git(["rev-parse", "HEAD"], self.root).strip()


class TestFinishedAt(ScratchBoardFixture):
    def test_flipped_task_pins_first_terminal_commit(self) -> None:
        sessions = board.build_rows(self.root)
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T100"]
        self.assertEqual(row.commit_short, self.commit_2_hash[:7])
        expected_utc = "2026-01-02T00:00:00+00:00"
        self.assertEqual(row.finished_utc, expected_utc)

    def test_open_task_has_no_finished_at(self) -> None:
        sessions = board.build_rows(self.root)
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T102"]
        self.assertEqual(row.status_word, "open")
        self.assertEqual(row.finished_local, "")
        self.assertEqual(row.finished_utc, "")
        self.assertEqual(row.commit_short, "")

    def test_uncommitted_terminal_task_reads_uncommitted(self) -> None:
        sessions = board.build_rows(self.root)
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T101"]
        self.assertEqual(row.status_word, "blocked")
        self.assertEqual(row.finished_local, "uncommitted")
        self.assertEqual(row.finished_utc, "uncommitted")
        self.assertEqual(row.commit_short, "")

    def test_reopened_task_pins_the_first_terminal_commit_not_the_last(self) -> None:
        """T300: open -> done (commit b) -> reopened -> blocked (commit d,
        its current status). finished-at must be commit b, the FIRST time
        the line ever went terminal - not commit d, its most recent one."""
        sessions = board.build_rows(self.root)
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T300"]
        self.assertEqual(row.status_word, "blocked")
        self.assertEqual(row.commit_short, self.commit_b_hash[:7])
        self.assertNotEqual(row.commit_short, self.commit_d_hash[:7])
        self.assertEqual(row.finished_utc, self.author_b)

    def test_hyphen_separated_ledger_parses(self) -> None:
        sessions = board.build_rows(self.root)
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T200"]
        self.assertEqual(row.title, "Hyphen separated title")
        self.assertEqual(row.commit_short, self.commit_3_hash[:7])

    def test_z_suffixed_author_time_renders_with_offset(self) -> None:
        """BL30: some git versions emit ``%aI`` with a trailing ``Z`` for
        UTC instead of ``+00:00``. ``git_show`` still reads the real
        fixture commit (only its author-time spelling is faked), so this
        exercises :func:`board.build_rows` end to end for the ``Z`` case
        without depending on which spelling the host's git actually emits
        (on this machine, git normalises to ``+00:00`` regardless - see the
        module docstring note in the T466 report)."""
        with mock.patch.object(board, "git_log_follow") as mock_log_follow:
            mock_log_follow.return_value = [
                (self.commit_2_hash, "2026-01-02T00:00:00Z")
            ]
            sessions = board.build_rows(self.root, session_filter="aaaaaaaa")
        rows = {r.task_id: r for _s, rs, _n, _m in sessions for r in rs}
        row = rows["T100"]
        self.assertEqual(row.commit_short, self.commit_2_hash[:7])
        self.assertEqual(row.finished_utc, "2026-01-02T00:00:00+00:00")


class TestParseAuthorTime(unittest.TestCase):
    """``_parse_author_time`` normalises a trailing ``Z`` (BL30) without
    disturbing an already-offset-aware value or a non-UTC offset."""

    def test_z_and_explicit_utc_offset_are_equal(self) -> None:
        from_z = board._parse_author_time("2026-01-02T00:00:00Z")
        from_offset = board._parse_author_time("2026-01-02T00:00:00+00:00")
        self.assertEqual(from_z, from_offset)
        self.assertIsNotNone(from_z.tzinfo)
        self.assertEqual(from_z.utcoffset(), timedelta(0))
        self.assertIsNotNone(from_offset.tzinfo)
        self.assertEqual(from_offset.utcoffset(), timedelta(0))

    def test_lowercase_z_also_normalises(self) -> None:
        parsed = board._parse_author_time("2026-01-02T00:00:00z")
        self.assertEqual(parsed.utcoffset(), timedelta(0))

    def test_non_utc_offset_is_preserved_not_rewritten(self) -> None:
        parsed = board._parse_author_time("2026-01-02T00:00:00+02:00")
        self.assertEqual(parsed.utcoffset(), timedelta(hours=2))
        self.assertEqual(parsed.isoformat(), "2026-01-02T00:00:00+02:00")

    def test_z_parses_under_a_310_shaped_fromisoformat(self) -> None:
        """A stand-in for Python 3.10's ``datetime.fromisoformat``, which
        raises on a trailing ``Z``/``z`` and otherwise delegates to the real
        implementation, proves the fix does not depend on the HOST
        interpreter's own ``Z`` tolerance (3.11+) - the normalisation in
        :func:`board._parse_author_time` must strip the ``Z`` itself before
        ever calling ``fromisoformat``."""
        real_datetime = board.datetime

        class Python310ShapedDatetime:
            @staticmethod
            def fromisoformat(value: str):
                if value.endswith(("Z", "z")):
                    raise ValueError(f"Invalid isoformat string: {value!r}")
                return real_datetime.fromisoformat(value)

        with mock.patch.object(board, "datetime", Python310ShapedDatetime):
            parsed = board._parse_author_time("2026-01-02T00:00:00Z")

        self.assertEqual(
            parsed, real_datetime(2026, 1, 2, 0, 0, 0, tzinfo=timezone.utc)
        )


class TestMarkdownHtmlParity(ScratchBoardFixture):
    def test_markdown_and_html_agree_on_every_row(self) -> None:
        sessions = board.build_rows(self.root)
        md = board.render_markdown(sessions)
        html_out = board.render_html(sessions)

        md_rows = []
        for line in md.splitlines():
            if not line.startswith("| T"):
                continue
            cells = [c.strip() for c in line.strip("|").split("|")]
            md_rows.append(tuple(cells))

        html_rows = []
        for row_match in re.finditer(r"<tr>(.*?)</tr>", html_out, re.DOTALL):
            cells = re.findall(r"<td>(.*?)</td>", row_match.group(1), re.DOTALL)
            if cells and cells[0].startswith("T"):
                html_rows.append(tuple(cells))

        self.assertTrue(md_rows, "no markdown rows found")
        self.assertEqual(len(md_rows), len(html_rows))
        self.assertEqual(md_rows, html_rows)


class TestCLI(ScratchBoardFixture):
    def test_markdown_mode_writes_nothing_and_exits_zero(self) -> None:
        out_path = Path(self._tmp.name) / "should-not-exist.html"
        code = board.main(
            ["--root", str(self.root), "--markdown", "--session", "aaaaaaaa"]
        )
        self.assertEqual(code, 0)
        self.assertFalse(out_path.exists())

    def test_html_mode_writes_only_out_file(self) -> None:
        out_path = Path(self._tmp.name) / "board.html"
        code = board.main(["--root", str(self.root), "--out", str(out_path)])
        self.assertEqual(code, 0)
        self.assertTrue(out_path.is_file())
        text = out_path.read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme", text)
        self.assertIn("T100", text)

    def test_out_required_without_markdown(self) -> None:
        code = board.main(["--root", str(self.root)])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
