#!/usr/bin/env python3
"""T473 - the context nudge: from 30 percent, once per step, moor not compact.

Contract
--------
Reads   : ``hooks/keel_compaction.py`` (the measurement, the step logic, the
          step record and the record-before-speak rule), ``hooks/keel_hook.py``
          (``cmd_prompt``, driven through the REAL launcher as a subprocess so
          what is asserted is the hook's own stdout rather than a function's
          return value), ``hooks/keel_redact.py`` (the screen the injected line
          must survive unchanged) and ``scripts/keel_gen_hooks.py`` (the
          registration that makes stdout context at all).
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes. The
          fixture home, the fixture project and the subprocess sandbox are the
          ones ``tests/test_keel_compaction_t228.py`` already established for
          this layer, IMPORTED from it rather than copied: the two modules test
          the same two files, and a second copy of that plumbing is a second
          thing to get wrong (R15). The real ``~/.claude/keel/`` is never read
          for a premise and never written.

          THE STEP STATE IS THE PROJECT's SINCE T474. The ``nudge`` lines live
          in the same per-session prompt log the prompts do, which moved into
          the adopted project's ``.keel/cache/``
          (``.keel/decisions/2026-09-03-the-bl28-window-takes-the-runbook-defaults.md``,
          Decision B), so every case below hands ``self.project`` where it used
          to hand a fixture home. Nothing about what is asserted changed: the
          same nine cases, the same counts, the same words in the same line.

          THE TRANSCRIPTS ARE FIXTURES, a few JSON lines each, written into the
          test's own temporary directory. No real transcript is read: the whole
          point of splitting the arithmetic out of the hook is that the
          acceptance cases can be pinned deterministically, and a case that
          depends on whatever this machine's own session happens to weigh is
          not pinned at all.

          THE UNWRITABLE-LOG FIXTURE is a FILE standing where the prompt-log
          DIRECTORY should be. That makes ``_append_jsonl``'s
          ``parent.mkdir()`` raise on every platform, which is the point: a
          permission bit set with ``chmod`` is a no-op for an administrator on
          Windows, and a fixture that silently succeeds proves the opposite of
          what it claims.

Failure policy
--------------
FAIL-CLOSED, as every test module is: a case that cannot establish its premise
fails rather than passing quietly.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). Every file operation names its
encoding (convention 6).
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import keel_compaction  # noqa: E402
import keel_gen_hooks  # noqa: E402
import keel_hook  # noqa: E402
from keel_redact import redact  # noqa: E402
from test_keel_compaction_t228 import SandboxCase, lines_of, run_hook  # noqa: E402

#: A model id no table will ever know, so case 7 measures the DEFAULT rather
#: than a table hit that happens to agree with it.
UNKNOWN_MODEL = "keel-test-model-nobody-ships"

#: A model id carrying the harness's own long-context marker - the one entry
#: keel's table has, measured in this project's audit log on 2026-09-03.
LONG_CONTEXT_MODEL = "claude-opus-5[1m]"

#: An ordinary id, of the shape the transcripts on this machine actually
#: carry, for every case that wants the default window.
ORDINARY_MODEL = "claude-sonnet-5"


def usage_split(tokens: int) -> dict[str, int]:
    """One usage block whose THREE counted fields sum to ``tokens``.

    Split three ways on purpose rather than dumped into one field: the
    measurement is defined as the SUM of ``input_tokens``,
    ``cache_creation_input_tokens`` and ``cache_read_input_tokens``, and a
    fixture that put the whole weight in one of them would pass just as well
    against an implementation that read only that one.
    """
    first = tokens // 10
    second = tokens // 5
    return {
        "input_tokens": first,
        "cache_creation_input_tokens": second,
        "cache_read_input_tokens": tokens - first - second,
        # Present and deliberately NOT counted: the harness charges it to the
        # next turn's input_tokens, so counting it here would count it twice.
        "output_tokens": 4096,
    }


def assistant_line(tokens: int, model: str = ORDINARY_MODEL) -> dict[str, Any]:
    """One assistant transcript line carrying a usage block of ``tokens``."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": model,
            "usage": usage_split(tokens),
        },
    }


def user_line(text: str = "a user turn") -> dict[str, Any]:
    """One transcript line that is NOT the assistant's, usage block and all.

    It carries a usage block too, which is the trap this fixture exists to
    spring: a reader that took the newest usage it could find, rather than the
    newest ASSISTANT line's, would measure this one.
    """
    return {
        "type": "user",
        "message": {"role": "user", "content": text, "usage": usage_split(999_999)},
    }


class NudgeCase(SandboxCase):
    """A fixture home, a fixture project, and transcripts written by hand."""

    def transcript(self, name: str, entries: list[dict[str, Any]]) -> Path:
        """One fixture transcript file; returns its path."""
        path = self.root / f"{name}.jsonl"
        path.write_text(
            "".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8"
        )
        return path

    def at(self, name: str, tokens: int, model: str = ORDINARY_MODEL) -> Path:
        """A transcript whose newest assistant line weighs ``tokens``."""
        return self.transcript(
            name,
            [
                user_line("the first thing asked"),
                assistant_line(tokens // 2, model),
                user_line("the newest thing asked"),
                assistant_line(tokens, model),
            ],
        )

    def prompt_turn(self, session: str, transcript: Path | None) -> Any:
        """One real UserPromptSubmit launch, sandboxed home and all."""
        payload: dict[str, Any] = {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session,
            "cwd": str(self.project),
            "prompt": "carry on",
        }
        if transcript is not None:
            payload["transcript_path"] = str(transcript)
        result = run_hook(
            "prompt", payload, self.project, self.home, self.scratch
        )
        self.assertEqual(
            result.returncode, 0, result.stderr.decode("utf-8", "replace")
        )
        return result

    def injected(self, result: Any) -> list[str]:
        """Every non-empty line the hook put on stdout."""
        return [
            line
            for line in result.stdout.decode("utf-8", "replace").splitlines()
            if line.strip()
        ]

    def steps(self, session: str, project: Path | None = None) -> list[int]:
        """Every step this session's log says it was told about, oldest first.

        Read out of the PROJECT's log (T474), which is the same file the
        prompts are in - so a step recorded against the wrong project is a
        step this helper cannot find, which is what the placement cases in
        ``test_keel_compaction_t228`` pin from the other side.
        """
        path = keel_compaction.prompt_log_path(
            session, self.project if project is None else project
        )
        self.assertIsNotNone(path, "premise: the fixture project resolves")
        if not path.exists():
            return []
        return [
            entry["step"]
            for entry in lines_of(path)
            if entry.get("event") == keel_compaction.NUDGE_EVENT
        ]


# ------------------------------------------- the nine cases, in the order ruled


class TestTheStepsAreCrossedOnce(NudgeCase):
    """Cases 1 to 5: when the line is said, and when it is not."""

    def test_case_1_at_twenty_nine_percent_nothing_is_injected_or_recorded(self) -> None:
        session = "sess-nudge-0001"
        result = self.prompt_turn(session, self.at("t29", 58_000))
        self.assertEqual(self.injected(result), [], "nothing is said below 30")
        self.assertEqual(self.steps(session), [], "and nothing is recorded")

    def test_case_2_at_thirty_percent_one_line_names_the_moor_skill(self) -> None:
        session = "sess-nudge-0002"
        result = self.prompt_turn(session, self.at("t30", 60_000))
        lines = self.injected(result)
        self.assertEqual(len(lines), 1, lines)
        line = lines[0]
        self.assertIn("/keel:moor", line, "the ruled remedy is mooring")
        self.assertIn("30%", line, "the measured percentage is stated")
        self.assertIn("200,000", line, "the assumed window is stated, in tokens")
        self.assertNotIn(
            "compact",
            line.casefold(),
            "the ratified decision forbids recommending compaction, in any wording",
        )
        self.assertEqual(self.steps(session), [30])

    def test_case_3_a_higher_percentage_in_the_same_step_says_nothing_more(self) -> None:
        session = "sess-nudge-0003"
        first = self.prompt_turn(session, self.at("t30", 60_000))
        self.assertEqual(len(self.injected(first)), 1, "premise: 30 fired")
        second = self.prompt_turn(session, self.at("t31", 62_000))
        self.assertEqual(
            self.injected(second), [], "one line per step, never per turn"
        )
        self.assertEqual(
            self.steps(session), [30], "and no second step line is written"
        )

    def test_case_4_the_next_step_injects_a_second_line(self) -> None:
        session = "sess-nudge-0004"
        self.prompt_turn(session, self.at("t30", 60_000))
        result = self.prompt_turn(session, self.at("t40", 80_000))
        lines = self.injected(result)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("40%", lines[0])
        self.assertIn("/keel:moor", lines[0])
        self.assertEqual(self.steps(session), [30, 40])

    def test_case_5_a_drop_resets_the_steps_and_thirty_fires_again(self) -> None:
        """The post-compaction case, which is the reason the comparison is a
        comparison rather than a high-water mark."""
        session = "sess-nudge-0005"
        self.prompt_turn(session, self.at("t30a", 60_000))
        dropped = self.prompt_turn(session, self.at("t12", 24_000))
        self.assertEqual(
            self.injected(dropped), [], "a drop says nothing - it is not news"
        )
        self.assertEqual(
            self.steps(session), [30, 0], "but the drop IS recorded, which is the reset"
        )
        again = self.prompt_turn(session, self.at("t30b", 60_000))
        lines = self.injected(again)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("30%", lines[0])
        self.assertEqual(self.steps(session), [30, 0, 30])

    def test_the_step_state_belongs_to_the_project_it_was_measured_in(self) -> None:
        """T474 against the nudge: the same session at the same percentage in a
        SECOND project is told once there too, because the state that says
        "already announced" is that project's own log. A step state shared
        across projects would silence the second one."""
        session = "sess-nudge-0005b"
        first = self.prompt_turn(session, self.at("t30c", 60_000))
        self.assertEqual(len(self.injected(first)), 1, "premise: it fired here")
        self.assertEqual(self.steps(session), [30])

        elsewhere = self.root / "second-project"
        (elsewhere / ".keel").mkdir(parents=True)
        outcome = keel_compaction.nudge_and_record(
            session, str(self.at("t30d", 60_000)), elsewhere
        )
        self.assertEqual(outcome.reason, keel_compaction.NUDGE_FIRED)
        self.assertEqual(self.steps(session, elsewhere), [30])
        self.assertEqual(
            self.steps(session), [30], "and the first project's log is unchanged"
        )


class TestNothingIsMeasuredSilently(NudgeCase):
    """Case 6: every path that cannot measure says which one it was."""

    def outcome(self, transcript: Any) -> keel_compaction.NudgeOutcome:
        return keel_compaction.nudge_outcome(
            "sess-nudge-0006", transcript, self.project
        )

    def test_case_6_each_unmeasurable_transcript_names_its_own_reason(self) -> None:
        no_assistant = self.transcript(
            "t-none", [user_line("only the user ever spoke")]
        )
        no_integers = self.transcript(
            "t-strings",
            [
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "model": ORDINARY_MODEL,
                        "usage": {
                            "input_tokens": "lots",
                            "cache_creation_input_tokens": None,
                            "cache_read_input_tokens": True,
                        },
                    },
                }
            ],
        )
        cases = (
            ("no path at all", None, keel_compaction.NUDGE_NO_TRANSCRIPT),
            ("an empty path", "   ", keel_compaction.NUDGE_NO_TRANSCRIPT),
            (
                "a file that is not there",
                str(self.root / "gone.jsonl"),
                keel_compaction.NUDGE_UNREADABLE,
            ),
            (
                "a directory where a file should be",
                str(self.root),
                keel_compaction.NUDGE_UNREADABLE,
            ),
            (
                "no assistant line",
                str(no_assistant),
                keel_compaction.NUDGE_NO_ASSISTANT,
            ),
            (
                "a usage block with no integers",
                str(no_integers),
                keel_compaction.NUDGE_NO_USAGE,
            ),
        )
        for label, transcript, reason in cases:
            with self.subTest(case=label):
                outcome = self.outcome(transcript)
                self.assertEqual(outcome.reason, reason)
                self.assertIsNone(outcome.line, "nothing is injected")
                self.assertIsNone(outcome.step, "and nothing is recorded")
        self.assertEqual(
            self.steps("sess-nudge-0006"), [], "no log line was written by any of them"
        )

    def test_a_boolean_is_not_an_integer_and_a_true_is_not_one_token(self) -> None:
        """``True`` is an ``int`` in Python, and summing it would make a usage
        block of three booleans weigh three tokens instead of saying it could
        not be read."""
        self.assertEqual(
            self.outcome(
                str(
                    self.transcript(
                        "t-bools",
                        [
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "usage": {"input_tokens": True},
                                },
                            }
                        ],
                    )
                )
            ).reason,
            keel_compaction.NUDGE_NO_USAGE,
        )

    def test_the_newest_assistant_line_wins_even_when_its_usage_is_unusable(self) -> None:
        """An older line's usage is a smaller, earlier window; reporting it as
        the context in use now would be a wrong number wearing a right one's
        confidence."""
        path = self.transcript(
            "t-stale",
            [
                assistant_line(60_000),
                {"type": "assistant", "message": {"role": "assistant", "usage": {}}},
            ],
        )
        self.assertEqual(
            self.outcome(str(path)).reason, keel_compaction.NUDGE_NO_USAGE
        )


class TestTheWindowIsAssumedOutLoud(NudgeCase):
    """Case 7: an unknown model takes the documented default and says so."""

    def test_case_7_an_unknown_model_takes_the_default_and_the_line_states_it(self) -> None:
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-0007",
            str(self.at("t-unknown", 60_000, UNKNOWN_MODEL)),
            self.project,
        )
        self.assertEqual(outcome.reason, keel_compaction.NUDGE_FIRED)
        self.assertEqual(outcome.window, keel_compaction.DEFAULT_CONTEXT_WINDOW)
        self.assertEqual(outcome.percent, 30)
        self.assertIsNotNone(outcome.line)
        self.assertIn("200,000", outcome.line)
        self.assertIn(
            "ASSUMED",
            outcome.line,
            "an assumption that is not stated is a claim nobody can check",
        )

    def test_the_one_table_entry_is_consulted_and_changes_the_answer(self) -> None:
        """The same 300,000 tokens are 30 percent of the long-context window and
        150 percent of the default, so this case cannot pass by accident."""
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-0007b",
            str(self.at("t-1m", 300_000, LONG_CONTEXT_MODEL)),
            self.project,
        )
        self.assertEqual(outcome.window, 1_000_000)
        self.assertEqual(outcome.percent, 30)
        self.assertIn("1,000,000", outcome.line)
        self.assertNotIn("ASSUMED", outcome.line, "the table knew this one")
        self.assertEqual(
            keel_compaction.step_of(300_000, keel_compaction.DEFAULT_CONTEXT_WINDOW),
            (150, 100),
            "premise: the default window would have answered differently - "
            "150 percent, not 30, and a step of 100 rather than 150 because "
            "T504/BL40 step two caps the STEP (never the reported percent) "
            "at 100 once the percentage proves the window wrong",
        )


class TestTheBareModelIsMeasuredToo(NudgeCase):
    """T504/BL40 step two, part 1: a ``claude-opus-5`` seat with NO ``[1m]``
    marker is measured at 1,000,000, not the 200,000 default - the exact
    defect the owner measured directly: 178.3k of 1,000,000 (18%) read as 85%
    of an assumed 200,000 in the same turn."""

    def test_a_bare_opus_5_seat_resolves_the_same_as_the_marked_one(self) -> None:
        self.assertEqual(
            keel_compaction.context_window("claude-opus-5"),
            (1_000_000, True),
            "the marker toggles on and off this one model; the family, not "
            "the marker, is what carries the window",
        )
        self.assertEqual(
            keel_compaction.context_window("claude-opus-5"),
            keel_compaction.context_window(LONG_CONTEXT_MODEL),
            "both spellings of the same model must resolve identically",
        )

    def test_the_owners_measured_seat_does_not_fire_below_thirty_percent(self) -> None:
        """178.3k of 1,000,000 is 17 percent - below the first step - so the
        session that measured this defect must NOT be nudged at all."""
        session = "sess-nudge-owner-seat"
        outcome = keel_compaction.nudge_outcome(
            session,
            str(self.at("t-owner-seat", 178_300, "claude-opus-5")),
            self.project,
        )
        self.assertEqual(outcome.window, 1_000_000)
        self.assertEqual(outcome.percent, 17)
        self.assertEqual(outcome.reason, keel_compaction.NUDGE_BELOW)
        self.assertIsNone(outcome.line, "17 percent of the real window is silence")
        self.assertEqual(self.steps(session), [])

    def test_an_unrecognised_id_still_takes_the_default_and_still_says_so(self) -> None:
        """Learning ``claude-opus-5`` must not widen the default: a model
        neither table has ever measured is exactly as unmeasured as before."""
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-still-unknown",
            str(self.at("t-still-unknown", 60_000, UNKNOWN_MODEL)),
            self.project,
        )
        self.assertEqual(outcome.window, keel_compaction.DEFAULT_CONTEXT_WINDOW)
        self.assertIn("ASSUMED", outcome.line)
        self.assertIn("200,000", outcome.line)


class TestTheBareFableSeatIsMeasuredToo(NudgeCase):
    """T605/BL40's remainder: a bare ``claude-fable-5`` seat is measured at
    1,000,000, not the 200,000 default - the exact defect measured live on
    2026-09-06: keel printed "about 80% of an ASSUMED 200,000-token context
    window" for this seat while the harness's own panel showed 153,800 tokens
    used of a real 1,000,000-token window (15%, not 77-80%)."""

    def test_a_bare_fable_5_seat_resolves_to_the_measured_window(self) -> None:
        self.assertEqual(
            keel_compaction.context_window("claude-fable-5"),
            (1_000_000, True),
            "a bare spelling of a measured family must not fall to the "
            "default just because it carries no [1m] marker",
        )

    def test_the_measured_percentage_is_fifteen_not_seventy_seven(self) -> None:
        """153,800 of 1,000,000 is 15 percent; 153,800 of the old 200,000
        default would have been (impossibly) 76 percent - this pins the
        actual regression measured live, not a round number."""
        self.assertEqual(
            keel_compaction.step_of(153_800, 1_000_000),
            (15, 0),
            "15 percent is below the first step, so this session would not "
            "have been nudged at all under the correct window",
        )
        self.assertEqual(
            keel_compaction.step_of(153_800, keel_compaction.DEFAULT_CONTEXT_WINDOW),
            (76, 70),
            "premise: the default window is what produced the false reading",
        )

    def test_the_owners_measured_fable_seat_does_not_fire_below_thirty_percent(
        self,
    ) -> None:
        session = "sess-nudge-fable-seat"
        outcome = keel_compaction.nudge_outcome(
            session,
            str(self.at("t-fable-seat", 153_800, "claude-fable-5")),
            self.project,
        )
        self.assertEqual(outcome.window, 1_000_000)
        self.assertEqual(outcome.percent, 15)
        self.assertEqual(outcome.reason, keel_compaction.NUDGE_BELOW)
        self.assertIsNone(outcome.line, "15 percent of the real window is silence")
        self.assertEqual(self.steps(session), [])

    def test_an_id_from_neither_family_still_takes_the_default_and_says_so(
        self,
    ) -> None:
        """Learning ``claude-fable-5`` must not widen the default: a model
        neither table has ever measured is exactly as unmeasured as before."""
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-still-unknown-fable",
            str(self.at("t-still-unknown-fable", 60_000, UNKNOWN_MODEL)),
            self.project,
        )
        self.assertEqual(outcome.window, keel_compaction.DEFAULT_CONTEXT_WINDOW)
        self.assertIn("ASSUMED", outcome.line)
        self.assertIn("200,000", outcome.line)


class TestAnImpossiblePercentageIsNeverStated(unittest.TestCase):
    """T504/BL40 step two, part 2: BL40 recorded a real injected line claiming
    "261%". A number over 100 disproves the assumed window rather than
    describing the session, and it must never reach the injected line as a
    fact."""

    def test_no_number_over_a_hundred_followed_by_a_percent_sign_is_ever_said(
        self,
    ) -> None:
        for percent, window, from_table in (
            (261, 200_000, False),
            (105, 200_000, False),
            (999, 1_000_000, True),
        ):
            with self.subTest(percent=percent, from_table=from_table):
                line = keel_compaction.nudge_text(percent, window, from_table)
                self.assertNotIn(f"{percent}%", line)
                for token in line.replace(",", " ").split():
                    if token.endswith("%"):
                        digits = token[:-1]
                        if digits.isdigit():
                            self.assertLessEqual(
                                int(digits),
                                100,
                                f"{token!r} in {line!r} asserts an impossible percentage",
                            )

    def test_the_line_says_the_window_is_wrong_rather_than_guessing_a_number(
        self,
    ) -> None:
        line = keel_compaction.nudge_text(261, 200_000, False)
        self.assertIn("window", line.casefold())
        self.assertIn("wrong", line.casefold())
        self.assertIn("does not know", line.casefold())
        self.assertIn("/keel:moor", line, "the remedy is still named")
        self.assertNotIn("compact", line.casefold())

    def test_a_percentage_at_exactly_a_hundred_is_still_stated_plainly(self) -> None:
        """The impossible-percentage branch triggers strictly ABOVE 100: a
        session genuinely full of a correctly measured window is not a
        disproof of anything."""
        line = keel_compaction.nudge_text(100, 1_000_000, True)
        self.assertIn("100%", line)
        self.assertNotIn("does not know", line.casefold())

    def test_the_step_recorded_for_an_impossible_percentage_is_capped_at_a_hundred(
        self,
    ) -> None:
        self.assertEqual(keel_compaction.step_of(522_000, 200_000), (261, 100))


class TestAPoisonedStepIsIgnoredOnRead(NudgeCase):
    """T504/BL40 step two, part 3: a prompt log already holding a step above
    100 - BL40's own recorded ``"step": 260`` - is read as though that line
    were never written, so it cannot mute the rest of the session."""

    def test_newest_nudge_step_treats_an_over_range_step_as_absent(self) -> None:
        self.assertIsNone(
            keel_compaction.newest_nudge_step(
                [{"event": keel_compaction.NUDGE_EVENT, "step": 260}]
            )
        )
        self.assertEqual(
            keel_compaction.newest_nudge_step(
                [
                    {"event": keel_compaction.NUDGE_EVENT, "step": 30},
                    {"event": keel_compaction.NUDGE_EVENT, "step": 260},
                ]
            ),
            30,
            "the poisoned line is skipped, not treated as the whole log's answer",
        )

    def test_a_poisoned_log_on_disk_still_lets_the_next_real_step_fire(self) -> None:
        """Builds the exact log BL40 describes - one ``nudge`` line with
        ``step`` 260, written the same way the real hook once wrote it
        (``record_nudge`` refuses a negative or non-integer step but not an
        out-of-range one - that refusal is this fix's read side, not its
        write side) - and proves the session is not muted for its rest."""
        session = "sess-nudge-poisoned"
        self.assertTrue(keel_compaction.record_nudge(session, 260, self.project))
        self.assertEqual(self.steps(session), [260], "premise: the poison is on disk")
        outcome = keel_compaction.nudge_outcome(
            session, str(self.at("t-poisoned", 60_000)), self.project
        )
        self.assertEqual(
            outcome.reason,
            keel_compaction.NUDGE_FIRED,
            "a legitimate 30 percent still fires despite the poisoned line",
        )
        self.assertIsNotNone(outcome.line)
        self.assertIn("30%", outcome.line)
        self.assertEqual(outcome.step, 30)


class TestTheLineIsSafeToInject(NudgeCase):
    """Case 8: the screen every injected line passes cannot change this one."""

    def test_case_8_the_screen_changes_nothing_because_the_raw_text_is_clean(self) -> None:
        """THE COMPARISON IS RAW AGAINST EMITTED, not emitted against itself.
        ``outcome.line`` has already been through ``redact``, so asserting
        ``redact(line) == line`` would only prove the screen is idempotent and
        would stay green if a path were interpolated into the wording tomorrow.
        Building the same sentence from the exposed raw builder and demanding
        equality is what fails in that case, because the screen would then have
        had something to collapse."""
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-0008", str(self.at("t-safe", 60_000)), self.project
        )
        line = outcome.line
        self.assertIsNotNone(line)
        raw = keel_compaction.nudge_text(
            outcome.percent, outcome.window, from_table=False
        )
        self.assertEqual(
            raw, line, "the screen had nothing to collapse in the raw sentence"
        )
        self.assertEqual(redact(raw), raw, "and it is stable under a second pass")
        self.assertNotIn(str(self.home), line, "it carries no path")
        self.assertNotIn("\\", line)
        self.assertEqual(len(line.splitlines()), 1, "exactly one physical line")
        line.encode("ascii")  # raises if a console-hostile character crept in

    def test_a_raw_sentence_carrying_a_home_path_would_not_survive_the_screen(self) -> None:
        """The other direction, so the case above is a measurement rather than
        a hope: ``redact`` demonstrably DOES change a sentence with a home path
        in it, which is exactly what the equality assertion would catch."""
        home = str(Path.home() / "notes" / "keel-nudge-fixture.md")
        self.assertNotEqual(
            redact(f"{keel_compaction.NUDGE_TAG} - see {home}"),
            f"{keel_compaction.NUDGE_TAG} - see {home}",
        )

    def test_the_line_is_one_line_even_at_an_absurd_percentage(self) -> None:
        outcome = keel_compaction.nudge_outcome(
            "sess-nudge-0008b", str(self.at("t-over", 900_000)), self.project
        )
        self.assertEqual(outcome.percent, 450, "measured, not clamped")
        self.assertEqual(len(outcome.line.splitlines()), 1)


class TestTheUnadoptedProjectIsUntouched(NudgeCase):
    """Case 9: no ``.keel/``, no measurement, no line, no log."""

    def test_case_9_an_unadopted_project_is_neither_measured_nor_spoken_to(self) -> None:
        unadopted = self.root / "not-adopted"
        unadopted.mkdir()
        session = "sess-nudge-0009"
        transcript = self.at("t-unadopted", 80_000)
        result = run_hook(
            "prompt",
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session,
                "cwd": str(unadopted),
                "prompt": "carry on",
                "transcript_path": str(transcript),
            },
            unadopted,
            self.home,
            self.scratch,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode("utf-8", "replace").strip(), "")
        self.assertEqual(self.steps(session, unadopted), [])
        self.assertEqual(self.steps(session), [], "nor in the adopted one beside it")
        self.assertFalse(keel_compaction.prompt_dir(unadopted).exists())
        self.assertFalse((unadopted / ".keel").exists(), "not one directory was made")


# ------------------------------ a step that cannot be recorded is not spoken


class TestAnUnrecordableStepIsWithheld(NudgeCase):
    """The silent-failure review of 2026-09-03, in both directions.

    Discarding ``record_nudge``'s answer and printing anyway would put the same
    line on stdout at EVERY following prompt, because the step state that makes
    "once per step" true never reached disk - the one behaviour the ratified
    specification forbids, and the opposite of what the line itself promises.
    So the writer speaks only after the write, and the two tests below are the
    two halves of that: the write blocked (nothing said, and the outcome says
    why), then the block removed (the line arrives, exactly once, because
    nothing was ever falsely claimed).
    """

    def block_the_log(self) -> Path:
        """Put a FILE where the prompt-log directory has to be.

        ``_append_jsonl`` starts with ``path.parent.mkdir(parents=True,
        exist_ok=True)``, which raises ``FileExistsError``/``NotADirectoryError``
        against a file - on every platform, unlike a permission bit, which an
        administrator on Windows simply ignores.
        """
        directory = keel_compaction.prompt_dir(self.project)
        self.assertIsNotNone(directory, "premise: the fixture project resolves")
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.write_text("not a directory\n", encoding="utf-8")
        self.assertTrue(directory.is_file(), "premise: the log path is blocked")
        return directory

    def test_a_step_that_could_not_be_recorded_is_never_injected(self) -> None:
        session = "sess-nudge-0010"
        self.block_the_log()
        transcript = self.at("t30", 60_000)

        outcome = keel_compaction.nudge_and_record(
            session, str(transcript), self.project
        )
        self.assertEqual(
            outcome.reason,
            keel_compaction.NUDGE_WITHHELD,
            "the outcome names the state rather than looking like an ordinary quiet turn",
        )
        self.assertIsNone(outcome.line, "nothing may be injected")
        self.assertEqual(outcome.step, 30, "and it still says which step was lost")

        result = self.prompt_turn(session, transcript)
        self.assertEqual(
            self.injected(result),
            [],
            "through the real launcher too: an unrecordable nudge is not spoken",
        )

    def test_and_the_next_prompt_still_gets_its_one_line_once_the_log_works(self) -> None:
        """The state was never CLAIMED, so nothing was lost but the one nudge:
        the very next prompt at the same percentage says it, once."""
        session = "sess-nudge-0011"
        blocked = self.block_the_log()
        transcript = self.at("t30", 60_000)
        self.assertEqual(self.injected(self.prompt_turn(session, transcript)), [])

        blocked.unlink()
        result = self.prompt_turn(session, transcript)
        lines = self.injected(result)
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("/keel:moor", lines[0])
        self.assertEqual(self.steps(session), [30], "recorded exactly once")

        quiet = self.prompt_turn(session, transcript)
        self.assertEqual(
            self.injected(quiet), [], "and never again inside the same step"
        )


# ----------------------------------------------------- the arithmetic, directly


class TestTheStepArithmetic(unittest.TestCase):
    """The pure functions, driven from values rather than files."""

    def test_the_step_is_the_percentage_rounded_down_from_thirty(self) -> None:
        window = keel_compaction.DEFAULT_CONTEXT_WINDOW
        for percent, step in (
            (0, 0),
            (29, 0),
            (30, 30),
            (31, 30),
            (39, 30),
            (40, 40),
            (99, 90),
            (100, 100),
        ):
            with self.subTest(percent=percent):
                self.assertEqual(
                    keel_compaction.step_of(window * percent // 100, window),
                    (percent, step),
                )

    def test_a_window_of_zero_measures_nothing_rather_than_dividing_by_it(self) -> None:
        self.assertEqual(keel_compaction.step_of(1, 0), (0, 0))
        self.assertEqual(keel_compaction.step_of(-1, 100), (0, 0))

    def test_the_newest_step_is_read_from_the_log_and_nothing_else_is(self) -> None:
        entries = [
            {"event": keel_compaction.PROMPT_EVENT, "prompt": "step 90 is not a step"},
            {"event": keel_compaction.NUDGE_EVENT, "step": 30},
            {"event": keel_compaction.NUDGE_EVENT, "step": 40},
            {"event": keel_compaction.NUDGE_EVENT, "step": "fifty"},
            {"event": keel_compaction.NUDGE_EVENT},
        ]
        self.assertEqual(keel_compaction.newest_nudge_step(entries), 40)
        self.assertIsNone(keel_compaction.newest_nudge_step([]))
        self.assertEqual(
            keel_compaction.newest_nudge_step(
                [{"event": keel_compaction.NUDGE_EVENT, "step": 0}]
            ),
            0,
            "a recorded zero is the reset, not an absence",
        )

    def test_an_unknown_model_and_a_marked_one_answer_differently(self) -> None:
        self.assertEqual(
            keel_compaction.context_window(None),
            (keel_compaction.DEFAULT_CONTEXT_WINDOW, False),
        )
        self.assertEqual(
            keel_compaction.context_window(UNKNOWN_MODEL),
            (keel_compaction.DEFAULT_CONTEXT_WINDOW, False),
        )
        self.assertEqual(
            keel_compaction.context_window(LONG_CONTEXT_MODEL.upper()),
            (1_000_000, True),
            "the marker is matched case-insensitively",
        )

    def test_a_session_with_no_id_is_not_measured(self) -> None:
        self.assertEqual(
            keel_compaction.nudge_outcome(None, "anything", None).reason,
            keel_compaction.NUDGE_NO_SESSION,
        )
        self.assertEqual(
            keel_compaction.nudge_and_record(None, "anything", None).reason,
            keel_compaction.NUDGE_NO_SESSION,
        )

    def test_a_step_with_no_project_is_refused_out_loud(self) -> None:
        """T474: the step state is a line in the project's log, so no project
        is no record - and a nudge whose step cannot be recorded is withheld,
        never spoken twice."""
        self.assertFalse(keel_compaction.record_nudge("s", 30, None))


# ------------------------------------------------------------------- contracts


class TestDeclarations(unittest.TestCase):
    """Convention 1/12: what the code promises is what a test reads."""

    def test_the_prompt_registration_is_synchronous_in_the_generated_document(self) -> None:
        """The artefact the HARNESS reads, not just the table it came from: an
        ``"async": true`` here would make the nudge arrive after the turn it
        was meant to shape."""
        document = json.loads(
            (REPO_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8")
        )
        groups = document["hooks"]["UserPromptSubmit"]
        self.assertEqual(len(groups), 1, "one registration, not two (Decision A)")
        self.assertNotIn("async", groups[0]["hooks"][0])
        rows = [
            entry
            for entry in keel_gen_hooks.ENTRIES
            if entry.event == "UserPromptSubmit"
        ]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0].is_async)

    def test_the_launcher_no_longer_claims_the_prompt_hook_emits_no_context(self) -> None:
        module_doc = keel_hook.__doc__ or ""
        prompt_doc = keel_hook.cmd_prompt.__doc__ or ""
        self.assertNotIn("emits no context", module_doc.casefold())
        self.assertNotIn("no context", prompt_doc.casefold())
        self.assertIn("/keel:moor", prompt_doc)

    def test_the_state_module_declares_what_the_nudge_may_not_do(self) -> None:
        doc = keel_compaction.__doc__ or ""
        self.assertIn("FAIL-OPEN AND NEVER RAISES", doc)
        self.assertIn("NO MODEL CALL", doc)
        self.assertIn("RECORDS FIRST", doc.upper())


if __name__ == "__main__":
    unittest.main()
