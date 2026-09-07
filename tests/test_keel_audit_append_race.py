#!/usr/bin/env python3
"""Concurrent appenders cannot lose an event - proven with real processes.

The finding this file answers, measured on this repository's own audit log on
2026-09-02: two hook processes appended at the same instant and the shorter
line landed at the offset of the longer one, overwriting its first 239 bytes
and leaving the last 64 as a line of its own. One ``subagent_stop`` event was
lost. The mechanism is recorded at
``.keel/knowledge/windows-append-mode-is-seek-then-write.md``: Python's text
append mode is emulated by the Microsoft C runtime as seek-to-end THEN write,
two steps with a gap between them, so two processes that both seek before
either writes both write at the same offset. POSIX ``O_APPEND`` does not have
the fault.

Why subprocesses and not threads
--------------------------------
The race is BETWEEN PROCESSES. Threads in one interpreter cannot show it: the
GIL serialises the write call, so a threaded version of this test passes
against a writer that loses events in production. Nothing here uses threads,
and a future edit that swaps them in would turn this file into a restatement
(see ``.keel/knowledge/a-mutation-test-that-mutates-nothing-is-a-restatement.md``).

Why a release signal
--------------------
Eight processes started in sequence do not necessarily overlap: the first can
finish its two hundred appends before the eighth has finished importing. So
each child announces itself in a ready directory and then spins on a release
file that the parent creates only once ALL of them have announced. The writes
then actually contend. Without that, the test can pass by accident on a fast
machine, and a proof that cannot fail proves nothing.

What is asserted, and why each one
----------------------------------
1. exactly N*M lines, every one parseable by plain ``json.loads`` - the count
   catches a line that was overwritten whole, the parse catches the fragment
   left behind when a line was overwritten in part;
2. every ``(writer, seq)`` pair present exactly once - the count alone cannot
   tell a lost line from a duplicated one, and a lock that lets a writer
   re-write its own line would keep the count while corrupting the record;
3. no byte of the file is ``\\r`` - the writer builds bytes itself, so the LF
   guarantee that ``newline="\\n"`` used to provide in text mode is now a
   property of the encoding step and is pinned here rather than assumed.

Contract
--------
Reads   : this installation's own ``hooks/`` modules, and the log file it
          wrote itself in a temporary directory. Nothing else on disk.
Emits   : unittest results only.
Writes  : nothing outside a temporary directory it creates and removes. In
          particular it never appends to this repository's own
          ``.keel/audit/keel-audit.jsonl`` - every writer is pointed at a
          throwaway project, which is the whole reason the child takes the
          project root as an argument instead of finding one.

Failure policy
--------------
FAIL-CLOSED. A child that cannot start, cannot reach the release signal
inside its deadline, or exits non-zero fails the test; none of those is
skipped, and the child's own stderr is quoted in the failure so a diagnosis
does not need a re-run.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its encoding.
The child is written to a FILE and run by path rather than passed as ``-c``
text: a script sent through an argument or a shell here-document loses
backslashes silently
(``.keel/knowledge/a-heredoc-mangles-backslashes-write-the-script-to-a-file.md``).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
import keel_events  # noqa: E402  (path must be set first)

#: Eight writers of two hundred lines each. Enough to lose a line reliably on
#: Windows against a seek-then-write append, small enough that the whole test
#: is a few seconds. Both numbers are read by the failure messages, so raising
#: them needs no other edit.
WRITERS = 8
LINES_EACH = 200

#: The child. Takes every path as an argument so it finds nothing on its own.
CHILD_SOURCE = '''\
"""One racing appender. Announces itself, waits for the shared release, appends."""

import sys
import time
from pathlib import Path

hooks_dir, project, index, count, ready_dir, release = sys.argv[1:7]
sys.path.insert(0, hooks_dir)
import keel_events

index = int(index)
count = int(count)

Path(ready_dir, str(index)).write_text("ready", encoding="utf-8")

release_path = Path(release)
deadline = time.monotonic() + 120.0
while not release_path.exists():
    if time.monotonic() > deadline:
        raise SystemExit("release signal never arrived")
    time.sleep(0.001)

project_root = Path(project)
for seq in range(count):
    keel_events.append_audit(
        project_root,
        {"kind": "post_tool", "race_writer": index, "race_seq": seq},
    )
'''


class TestConcurrentAppendersLoseNothing(unittest.TestCase):
    """The record survives N processes appending to it at the same instant."""

    def _race(self, project: Path, tmp: Path) -> None:
        """Start every writer, release them together, and require a clean exit."""
        ready = tmp / "ready"
        ready.mkdir()
        release = tmp / "release"
        child = tmp / "race_writer.py"
        child.write_text(CHILD_SOURCE, encoding="utf-8")

        running = [
            subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    str(child),
                    str(REPO_ROOT / "hooks"),
                    str(project),
                    str(index),
                    str(LINES_EACH),
                    str(ready),
                    str(release),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(project),
            )
            for index in range(WRITERS)
        ]
        try:
            deadline = time.monotonic() + 120.0
            while len(list(ready.iterdir())) < WRITERS:
                if time.monotonic() > deadline:
                    self.fail(
                        f"only {len(list(ready.iterdir()))} of {WRITERS} writers "
                        "announced themselves; the race never started"
                    )
                time.sleep(0.005)
            # Every writer is now spinning on this file. Releasing them here,
            # and not at start-up, is what makes the writes overlap.
            release.write_text("go", encoding="utf-8")
            for index, process in enumerate(running):
                _, err = process.communicate(timeout=300)
                self.assertEqual(
                    process.returncode, 0, f"writer {index} exited {process.returncode}: {err}"
                )
        finally:
            for process in running:
                if process.poll() is None:
                    process.kill()

    def test_no_line_is_lost_when_eight_processes_append_at_once(self) -> None:
        """N*M lines, each parseable, each pair exactly once, no CR anywhere."""
        expected = LINES_EACH * WRITERS
        with tempfile.TemporaryDirectory() as name:
            tmp = Path(name)
            project = tmp / "project"
            (project / ".keel").mkdir(parents=True)

            self._race(project, tmp)

            log = keel_events.audit_path(project)
            raw = log.read_bytes()
            self.assertNotIn(
                b"\r",
                raw,
                "the log carries a CR: the writer is not building LF bytes itself",
            )

            text = raw.decode("utf-8", errors="replace")
            lines = [line for line in text.split("\n") if line != ""]
            unparseable = [line for line in lines if not _parses(line)]
            self.assertEqual(
                len(lines),
                expected,
                f"{len(lines)} lines on the record, expected {expected}: "
                f"{expected - len(lines)} lost to the race "
                f"({len(unparseable)} of what is there does not parse)",
            )
            self.assertEqual(
                unparseable,
                [],
                f"{len(unparseable)} of {len(lines)} lines are not JSON; a "
                f"partially overwritten line is what a lost-update race leaves "
                f"behind. First: {unparseable[:1]}",
            )

            seen: dict[tuple[int, int], int] = {}
            for line in lines:
                entry = json.loads(line)
                pair = (entry["race_writer"], entry["race_seq"])
                seen[pair] = seen.get(pair, 0) + 1
            wanted = {
                (writer, seq)
                for writer in range(WRITERS)
                for seq in range(LINES_EACH)
            }
            missing = sorted(wanted - set(seen))
            duplicated = sorted(pair for pair, count in seen.items() if count > 1)
            self.assertEqual(
                missing, [], f"{len(missing)} (writer, seq) pairs never reached the record"
            )
            self.assertEqual(
                duplicated, [], f"{len(duplicated)} (writer, seq) pairs landed more than once"
            )


class TestALockThatCannotBeTakenStillWritesTheLine(unittest.TestCase):
    """The documented timeout policy, proven by breaking the lock.

    ``_append_bytes`` writes WITHOUT the lock when it cannot take one - ten
    seconds of contention, or a filesystem that refuses locks, which some
    network mounts do. The reasoning is in its docstring: under that much
    contention the honest failure is the OLD one, a rare overwrite, not a NEW
    one, a dropped event. This asserts the choice rather than trusting the
    comment, because the alternative failure is silent by construction.
    """

    def test_a_failing_lock_does_not_cost_the_event(self) -> None:
        """A lock that always raises loses no line and raises nothing."""
        original = keel_events._lock_exclusive
        calls: list[int] = []

        def refuse(fd: int) -> None:
            calls.append(fd)
            raise OSError("deliberate fault: the lock cannot be taken")

        keel_events._lock_exclusive = refuse
        try:
            with tempfile.TemporaryDirectory() as name:
                project = Path(name) / "project"
                (project / ".keel").mkdir(parents=True)
                for seq in range(5):
                    keel_events.append_audit(
                        project, {"kind": "post_tool", "race_seq": seq}
                    )
                lines = [
                    line
                    for line in keel_events.audit_path(project)
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line
                ]
        finally:
            keel_events._lock_exclusive = original

        self.assertEqual(len(calls), 5, "the writer stopped trying to lock")
        self.assertEqual(
            [json.loads(line)["race_seq"] for line in lines],
            [0, 1, 2, 3, 4],
            "an unlockable file cost an event; the policy is to write anyway",
        )


def _parses(line: str) -> bool:
    """True when ``line`` is a JSON object, the shape every log line has."""
    try:
        return isinstance(json.loads(line), dict)
    except ValueError:
        return False


if __name__ == "__main__":
    unittest.main()
