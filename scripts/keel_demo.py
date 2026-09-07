#!/usr/bin/env python3
"""keel demo mode — a zero-token, fully-synthetic orchestration board (T140).

THIS IS A DEMO. Every session id, agent id, task name and line of prose this
script writes is INVENTED for the purpose of exercising the live board; none
of it names real work, a real agent or a real reviewer verdict. Demo session
ids always carry a ``demo-`` prefix (Accept 3) so a copied line can never be
mistaken for a real record.

Contract
--------
Reads   : nothing outside the throwaway demo project it creates, plus — as a
          refusal check only, before any write — the target's own
          ``.keel/audit/keel-audit.jsonl`` if one already exists there.
Writes  : a FRESH demo project directory only — its own ``.keel/audit/``,
          ``.keel/plans/`` and a minimal ``.keel/keel-policy.md`` — created
          under a temp directory by default, or under ``--dir`` if given.
          The real project's ``.keel/`` is NEVER read or written: ENFORCED by
          ``_refusal_reason`` (called before ``build_demo_project`` ever
          touches the target), which refuses — nonzero exit, nothing
          written — any target that either (a) resolves to this very
          script's own repository root, or (b) already has a
          ``.keel/audit/keel-audit.jsonl`` carrying any ``session`` line
          that does NOT start with ``demo-`` (the sound discriminator: only
          a project this demo itself has written, or never touched at all,
          can have every session so prefixed). A target whose ``.keel/`` is
          absent, or whose audit log holds only ``demo-`` sessions (a prior
          run of this same script), is accepted.
Runtime : pure Python, stdlib only, no network beyond the optional localhost
          dashboard this script may spawn for viewing. Zero tokens: no model
          is ever called (Accept 5).

Usage
-----
    python scripts/keel_demo.py                  loop until Ctrl-C
    python scripts/keel_demo.py --dir <path>      use this dir instead of a
                                                    fresh temp directory
    python scripts/keel_demo.py --fast            no sleeps (for tests/CI)
    python scripts/keel_demo.py --cycles 2         stop after N cycles
    python scripts/keel_demo.py --serve            also spawn the board
    python scripts/keel_demo.py --tour --serve     the scripted tour (T341)
                                                    instead of the loop, round
                                                    after round until Ctrl-C
    python scripts/keel_demo.py --tour --once      ONE pass, then hold the
                                                    board (scripted proofs/CI)
    python scripts/keel_demo.py --tour --seconds 60   scale one round

To watch the board yourself, in a second terminal:
    python scripts/keel_orchestration_dashboard.py --dir <path> --port 8771
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NamedTuple

#: Every field this module ever writes is invented; nothing here is copied
#: from a real project's records (names/refs checks stay green by construction).
DEMO_PORT = 8771

#: This script's own repository root — a target resolving to exactly this
#: is refused outright, whatever its ``.keel/`` holds or lacks.
REPO_ROOT = Path(__file__).resolve().parent.parent

#: KEEL ADDITION (T345b, owner 2026-08-26): WHAT THE SEAT RUNS AT. The
#: orchestrator is not one of its own executors: the crew below are the ones
#: on sonnet and opus, and the seat that plans, routes and reviews them is
#: Fable. A demo that records the seat as "sonnet" teaches a viewer the one
#: thing about keel's routing that is not so, on the first card they read.
#: The bare family name, exactly like the crew's tags — never a full model
#: id, which the demo has no business inventing.
ORCHESTRATOR_MODEL = "fable"

#: The crew, by their real keel agent type — so the board's avatars, model
#: tags and resume verbs all exercise exactly as they would for real work.
CREW = (
    ("keel:executor", "sonnet", "default"),
    ("keel:executor-deep", "opus", "high"),
    ("keel:researcher", "sonnet", "low"),
    ("keel:reviewer-correctness", "sonnet", "default"),
    ("keel:reviewer-security", "sonnet", "default"),
    ("keel:reviewer-tests", "sonnet", "default"),
)

#: A rotating pool of INVENTED task names — pure demo flavour, never a real
#: task id or description. Two are drawn per cycle, by cycle index, so the
#: sequence varies run over run without any randomness (Accept 2).
#: The identifiers are ``T``-numbers, matching what a real keel ledger writes
#: — AND staying clear of the ``[RFD]<n>`` citation grammar the reference
#: check reads. An earlier pool numbered these off the decision letter, which
#: every reader saw as demo task ids and the checker saw as ten citations of
#: decisions that do not exist. It went unnoticed until this file was
#: committed, because the checks scan TRACKED files only — the same trap that
#: has now caught this project three times.
#:
#: KEEL ADDITION (T345d, owner 2026-08-26): the descriptions ARE THE DEMO'S
#: TEACHING SURFACE and used to be nautical whimsy ("caulk the hull seams"),
#: which told a stranger watching the board nothing about what keel is for.
#: They are now the kind of work an adopter recognises as their own backlog —
#: and still obviously synthetic: no repository, product, company or person
#: is named, no path here exists, and every session line that carries them
#: keeps the ``demo-`` prefix, so no line can pass as a real record. The
#: tracked-ledger trap applies to this pool too: nothing here may name an
#: ignored path or a third-party tool, because the reference checks read
#: TRACKED files and this file is one.
TASK_POOL = (
    ("T1", "track down the flaky sign-in test"),
    ("T2", "profile the slow monthly report query"),
    ("T3", "add a retry path to the upload worker"),
    ("T4", "write the migration for the members table"),
    ("T5", "correct the stale flag in the setup guide"),
    ("T6", "delete the retired beta feature flag"),
    ("T7", "cache the settings lookup on the hot path"),
    ("T8", "log the payload of a failed callback"),
    ("T9", "paginate the members list endpoint"),
    ("T10", "fix the off-by-one in the digest timezone"),
    ("T11", "raise the attachment size limit"),
    ("T12", "backfill the missing created-at timestamps"),
)

PLAN_HEADER = """# Demo plan ledger (synthetic — written by scripts/keel_demo.py)

Every task below is invented for this demo run. Nothing here names real
work; the orchestration dashboard reads this file exactly like a real plan
ledger, so the boxes below flip as the demo's synthetic reviews land.

## Tasks

"""


def _now_iso() -> str:
    """Current wall-clock time, keel's own audit timestamp shape."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _agent_id(cycle: int, role: str) -> str:
    """A 17-character lowercase-hex agent id — the real shape, deterministic
    rather than random, so two runs of the same cycle draw the same crew."""
    return hashlib.sha1(f"keel-demo:{cycle}:{role}".encode("utf-8")).hexdigest()[:17]


def _tool_use_id(cycle: int, seq: int) -> str:
    """A synthetic hand-off id, shaped like the real ``toolu_...`` but never
    resolvable to one — the leading ``demo`` marks it unmistakably invented."""
    return f"toolu_demo{cycle:04d}{seq:02d}"


def _refusal_reason(root: Path) -> str | None:
    """``None`` when ``root`` is safe to write a demo cycle into; otherwise
    the reason to refuse, checked BEFORE anything is written (Accept 1).

    Two grounds, both fail-closed:

    1. ``root`` resolves to this script's own repository root — refused
       outright, whatever its ``.keel/`` holds or lacks.
    2. ``root`` already has a ``.keel/audit/keel-audit.jsonl`` and that log
       carries at least one ``session`` line that does NOT start with
       ``demo-``. That is the sound discriminator: a project this script
       itself has ever written has every session so prefixed, so an audit
       log holding anything else is somebody's real record, never this
       demo's own. A missing ``.keel/``, a missing or empty audit log, or
       one holding only ``demo-`` sessions (a prior run of this same
       script) all pass — this is what makes reruns against the same demo
       directory idempotent.
    """
    if root == REPO_ROOT:
        return (
            f"refusing to demo into {root} — it is this script's own "
            "repository root, and the real .keel/ there is never touched"
        )
    log_path = root / ".keel" / "audit" / "keel-audit.jsonl"
    if not log_path.is_file():
        return None
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        session = event.get("session")
        if isinstance(session, str) and session and not session.startswith("demo-"):
            return (
                f"refusing to demo into {root} — {log_path} already holds a "
                f"real session ('{session}'); this demo never writes into "
                "someone's real record"
            )
    return None


def build_demo_project(root: Path, *, with_plan: bool = True) -> tuple[Path, Path]:
    """Create the throwaway demo project's own ``.keel/`` tree; idempotent.

    Returns the audit log path and the plan ledger path. Never touches
    anything outside ``root`` (Accept 1).

    KEEL ADDITION (T341): ``with_plan=False`` creates the tree WITHOUT the
    loop's pre-filled ledger. The tour's first beat has to show an empty
    ledger and its second beat has to show a plan-gate refusal, and both of
    those are facts about the demo project's own state: a plan file sitting
    on disk before the tour writes one would make beat 1 read "five tasks
    already open" and beat 2's refusal a lie. The returned plan path is the
    file the tour will write at beat 3; nothing is created for it here.
    """
    audit_dir = root / ".keel" / "audit"
    plans_dir = root / ".keel" / "plans"
    audit_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)
    log_path = audit_dir / "keel-audit.jsonl"
    if not log_path.exists():
        log_path.write_text("", encoding="utf-8")
    plan_path = plans_dir / "keel-plan-demo0000.md"
    if with_plan and not plan_path.exists():
        lines = [PLAN_HEADER]
        for task_id, desc in TASK_POOL:
            lines.append(f"- [ ] {task_id} — {desc}\n")
        plan_path.write_text("".join(lines), encoding="utf-8")
    policy_path = root / ".keel" / "keel-policy.md"
    if not policy_path.exists():
        policy_path.write_text(
            "---\n"
            "tier: 2\n"
            "---\n"
            "# Demo policy (synthetic — scripts/keel_demo.py; never enforced)\n",
            encoding="utf-8",
        )
    return log_path, plan_path


def _append(log_path: Path, event: dict) -> None:
    """Append one JSON line, keel's own audit shape — flushed immediately so
    a dashboard tailing the file sees it without waiting for this process to
    exit."""
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


_CHECKBOX_RE_TEMPLATE = r"^- \[[ x]\] {task_id} — .*$"


def set_task_checked(plan_path: Path, task_id: str, checked: bool) -> None:
    """Flip one ledger line's checkbox, by task id, leaving everything else
    in the file untouched — the "ledger boxes flipping" of Accept 2."""
    text = plan_path.read_text(encoding="utf-8")
    box = "[x]" if checked else "[ ]"
    pattern = re.compile(_CHECKBOX_RE_TEMPLATE.format(task_id=re.escape(task_id)), re.MULTILINE)

    def _replace(match: re.Match) -> str:
        line = match.group(0)
        return re.sub(r"\[[ x]\]", box, line, count=1)

    new_text = pattern.sub(_replace, text)
    if new_text != text:
        plan_path.write_text(new_text, encoding="utf-8")


def _sleep(seconds: float, fast: bool) -> None:
    if not fast:
        time.sleep(seconds)


def run_cycle(log_path: Path, plan_path: Path, cycle: int, *, fast: bool, beat: float = 2.3) -> str:
    """Play one full ~30-second (real time) demo cycle: session start,
    Captain planning, a Shipwright launch with activity beats, a Chief
    launch, a RESUME hand-off, reviewer launches, one review pass and one
    review fail, stops pairing on agent ids, ledger boxes flipping, session
    end. Returns the demo session id used.

    Every field is synthetic (Accept 2/3); ``fast=True`` skips every sleep
    so a test can run a whole cycle instantly (T140's own accept gate).
    """
    sid = f"demo-{cycle:04d}"
    task_a = TASK_POOL[(2 * cycle) % len(TASK_POOL)]
    task_b = TASK_POOL[(2 * cycle + 1) % len(TASK_POOL)]
    set_task_checked(plan_path, task_a[0], False)
    set_task_checked(plan_path, task_b[0], False)

    shipwright_id = _agent_id(cycle, "keel:executor")
    chief_id = _agent_id(cycle, "keel:executor-deep")
    surveyor_id = _agent_id(cycle, "keel:reviewer-correctness")
    gunner_id = _agent_id(cycle, "keel:reviewer-tests")

    # 1. session start — the ORCHESTRATOR'S seat, which is not a crew tier
    #    (KEEL ADDITION T345b): this line recorded "sonnet" and so drew the
    #    Captain's own pill on the same tier as the executors she dispatches,
    #    which misreads keel's routing on the one card a viewer reads first.
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "session_start",
        "session": sid, "source": "startup", "model": ORCHESTRATOR_MODEL,
    })
    _sleep(beat, fast)

    # 2. Captain planning
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "activity", "session": sid,
        "agent_type": None, "tool": "TodoWrite",
        "detail": f"demo cycle {cycle}: {task_a[0]} {task_a[1]}; {task_b[0]} {task_b[1]}",
    })
    _sleep(beat, fast)

    # 3. Shipwright launch (keel:executor)
    uid_a = _tool_use_id(cycle, 1)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_start", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_a, "agent_id": None, "launch_ack": None,
        "subagent_type": "keel:executor", "model": "sonnet", "effort": "default",
        "description": f"{task_a[0]}: {task_a[1]}",
        "prompt_head": f"Demo task {task_a[0]} — {task_a[1]} (synthetic, no real work).",
    })
    _sleep(beat, fast)

    # 4. Shipwright activity beat
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "activity", "session": sid,
        "agent_type": "keel:executor", "tool": "Edit",
        "detail": f"demo/{task_a[0].lower()}.py",
    })
    _sleep(beat, fast)

    # 5. Shipwright hand-off closes (background ack)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_end", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_a, "agent_id": shipwright_id, "launch_ack": True,
        "subagent_type": "keel:executor", "model": "sonnet", "effort": "default",
        "description": f"{task_a[0]}: {task_a[1]}",
        "prompt_head": f"Demo task {task_a[0]} — {task_a[1]} (synthetic, no real work).",
    })
    _sleep(beat, fast)

    # 6. Chief launch (keel:executor-deep)
    uid_b = _tool_use_id(cycle, 2)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_start", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_b, "agent_id": None, "launch_ack": None,
        "subagent_type": "keel:executor-deep", "model": "opus", "effort": "high",
        "description": f"{task_b[0]}: {task_b[1]}",
        "prompt_head": f"Demo task {task_b[0]} — {task_b[1]} (synthetic, no real work).",
    })
    _sleep(beat, fast)

    # 7. Chief hand-off closes (background ack)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_end", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_b, "agent_id": chief_id, "launch_ack": True,
        "subagent_type": "keel:executor-deep", "model": "opus", "effort": "high",
        "description": f"{task_b[0]}: {task_b[1]}",
        "prompt_head": f"Demo task {task_b[0]} — {task_b[1]} (synthetic, no real work).",
    })
    _sleep(beat, fast)

    # 8/9. a RESUME hand-off on the Shipwright, opened then closed
    uid_r = _tool_use_id(cycle, 3)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_start", "handoff_kind": "resume",
        "session": sid, "tool_use_id": uid_r, "agent_id": shipwright_id,
        "subagent_type": None, "model": None, "effort": None,
        "description": f"{task_a[0]} wave review follow-up",
        "prompt_head": "Demo resume: one more pass on the same demo agent (synthetic).",
    })
    _sleep(beat, fast)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_end", "handoff_kind": "resume",
        "session": sid, "tool_use_id": uid_r, "agent_id": shipwright_id,
        "subagent_type": None, "model": None, "effort": None,
        "description": f"{task_a[0]} wave review follow-up",
        "prompt_head": "Demo resume: one more pass on the same demo agent (synthetic).",
    })
    _sleep(beat, fast)

    # 10. Surveyor launch, reviews task_a and PASSES
    uid_c = _tool_use_id(cycle, 4)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_start", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_c, "agent_id": None, "launch_ack": None,
        "subagent_type": "keel:reviewer-correctness", "model": "sonnet", "effort": "default",
        "description": f"Review {task_a[0]} correctness",
        "prompt_head": f"Demo review of {task_a[0]} (synthetic, no real diff).",
    })
    _sleep(beat, fast)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_end", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_c, "agent_id": surveyor_id, "launch_ack": True,
        "subagent_type": "keel:reviewer-correctness", "model": "sonnet", "effort": "default",
        "description": f"Review {task_a[0]} correctness",
        "prompt_head": f"Demo review of {task_a[0]} (synthetic, no real diff).",
    })
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "review", "session": sid,
        "task": task_a[0], "verdict": "pass",
        "notes": f"Demo review: {task_a[1]} looks synthetic-clean.",
    })
    set_task_checked(plan_path, task_a[0], True)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "subagent_stop", "session": sid,
        "agent_id": shipwright_id, "agent_type": "keel:executor",
    })
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "subagent_stop", "session": sid,
        "agent_id": surveyor_id, "agent_type": "keel:reviewer-correctness",
    })
    _sleep(beat, fast)

    # 11. Gunner launch, reviews task_b and FAILS
    uid_d = _tool_use_id(cycle, 5)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_start", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_d, "agent_id": None, "launch_ack": None,
        "subagent_type": "keel:reviewer-tests", "model": "sonnet", "effort": "default",
        "description": f"Review {task_b[0]} tests",
        "prompt_head": f"Demo review of {task_b[0]} (synthetic, no real diff).",
    })
    _sleep(beat, fast)
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "handoff_end", "handoff_kind": "launch",
        "session": sid, "tool_use_id": uid_d, "agent_id": gunner_id, "launch_ack": True,
        "subagent_type": "keel:reviewer-tests", "model": "sonnet", "effort": "default",
        "description": f"Review {task_b[0]} tests",
        "prompt_head": f"Demo review of {task_b[0]} (synthetic, no real diff).",
    })
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "review", "session": sid,
        "task": task_b[0], "verdict": "fail",
        "notes": f"Demo review: {task_b[1]} needs a synthetic retry.",
    })
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "subagent_stop", "session": sid,
        "agent_id": chief_id, "agent_type": "keel:executor-deep",
    })
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "subagent_stop", "session": sid,
        "agent_id": gunner_id, "agent_type": "keel:reviewer-tests",
    })
    _sleep(beat, fast)

    # 12. session end
    _append(log_path, {
        "v": 1, "ts": _now_iso(), "event": "session_end", "session": sid,
        "reason": "demo_cycle_complete",
    })
    return sid


# =====================================================================
# KEEL ADDITION (T341): THE FORTY-SECOND TOUR
# =====================================================================
# The loop above shows that the board reads keel's schema. It does not tell
# a STORY: a viewer sees hand-offs and verdicts in a rotation and has to be
# told what to look for. The tour is the same synthetic writer driving a
# CHOREOGRAPHED timeline instead - eight beats, in an order chosen so each
# one shows something the previous beat set up.
#
# THE TIMELINE IS DATA (``TOUR``), not sleeps scattered through imperative
# code. Every beat carries its offset as a FRACTION of the total duration,
# so ``--seconds N`` scales the whole tour without touching a single
# number below, and a test can import ``TOUR`` and assert its order and
# completeness without running a second of it. ``run_tour`` is the only
# thing here that knows about the clock.
#
# TIMING HONESTY. The board polls its own ``/api/state`` every 1500 ms
# (``setInterval(tick,1500)`` in scripts/keel_orchestration_dashboard.py),
# so anything shorter than about 3 s - two polls - can be overwritten
# before a viewer's eye lands on it. Every beat here is therefore at least
# 0.10 of the total apart (4 s at the 40 s default), and the sub-offsets
# INSIDE a beat (``Cue.dt``) are only ever used where the point of the
# beat is a sequence rather than a moment - the earned-fail ladder in beat
# 6, the refuse-then-close pair in beat 8 - and never to squeeze a ninth
# beat into the gap. Eight legible beats, not twelve blurred ones.
#
# EVERY EVENT CLASS AND FIELD BELOW IS ONE KEEL REALLY WRITES. The shapes
# are taken from the hooks that write them, field for field:
#   session_start / session_end   hooks/keel_session.py start_record/end_record
#   activity                      hooks/keel_capture.py action_record
#   handoff_start / handoff_end   hooks/keel_capture.py handoff_record
#                                 (launch: launch_ack + background) and
#                                 resume_record (resume: three nulls BY
#                                 CONSTRUCTION - a send knows no type, no
#                                 model, no effort)
#   subagent_stop                 hooks/keel_hook.py cmd_subagent_stop
#   gate_block                    hooks/keel_gate.py _audit
#   stop_block                    hooks/keel_stop.py _audit
#   review                        scripts/keel_review.py (the orchestrator's
#                                 own writer; a verdict is not a hook event)
# Nothing is invented for the sake of a beat: a tour that fakes a field to
# tell a better story is a demo of a product that does not exist.
TOUR_SECONDS = 40.0

# =====================================================================
# KEEL ADDITION (T346): A ROUND IS A SESSION - the board says so
# =====================================================================
# The tour now replays until Ctrl-C, and each replay has to open a NEW ROUND
# on the board rather than pile onto the last one. So: what IS a round?
#
# IT IS DERIVED, NOT RECORDED. No hook writes a "round" and no audit line
# carries one. scripts/keel_orchestration_dashboard.py builds the round list
# itself, in ``tick()``: "rounds = every session OBSERVED in the log, by
# first appearance" - one entry per distinct ``session_id``, ordered by its
# first event, numbered "Round <index+1>" in the selector
# (``sessLines``/``liveLines``). The per-round ledger comes from the same
# key: "per-session plans: each round's ledger is its own plan file", looked
# up as ``plan-<first 8 chars of the session id>.md``.
#
# THEREFORE a new round is A NEW SESSION ID, and nothing else. Two things
# follow, and both are why this is done the honest way rather than the easy
# one:
#   * A SECOND ``session_start`` FOR THE SAME ID WOULD NOT OPEN A ROUND. The
#     real hooks do write repeat starts for one session (this project's own
#     log, 2026-08-26: 269 ``session_start`` lines over 157 sessions, one id
#     carrying 33 of them - resumes and compactions). The board counts none
#     of them as a round, so faking a round that way would be a line that
#     changes nothing on screen.
#   * THE SESS8 HAS TO DIFFER TOO, not merely the full id. Rounds are keyed
#     by the whole session id, but LEDGERS are keyed by its first eight
#     characters, so two rounds sharing a sess8 would share one ledger file
#     - round 2 resetting it would rewrite round 1's finished rail under the
#     viewer paging back. ``demo-`` eats five of those eight characters, so
#     the round tag gets the remaining three (base 36: 46 656 rounds, 21
#     days at the 40 s default, before it wraps and reuses an id).
#
# What a real multi-round board shows is therefore exactly what this writes:
# one session per round, each with its own ``session_start``, its own ledger
# file named by keel's real ``keel-plan-<sess8>.md`` rule, and its own agent
# and hand-off ids. Every id keeps the ``demo-`` prefix ``_refusal_reason``
# depends on (Accept 3).
_ROUND_TAG_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
_ROUND_TAG_WIDTH = 3
_ROUND_TAG_SPAN = len(_ROUND_TAG_ALPHABET) ** _ROUND_TAG_WIDTH


def _round_tag(round_n: int) -> str:
    """Round number -> the three characters that fit inside a sess8.

    Base 36, so the first nine rounds still read as the plain digits a
    viewer expects (``001``, ``002``) and the space runs to 46 655 before
    wrapping. The tag is not the round NUMBER a viewer reads anyway - the
    board computes "Round N" from the session's position in the log - it is
    only what keeps one round's ledger file out of another's.

    The wrap is deliberate and documented rather than an overflow: a demo
    that has played 46 656 rounds has been up three weeks, and reusing an id
    then merges that round with a predecessor long scrolled out of the
    board's own served window, instead of inventing a wider field the sess8
    has no room for.
    """
    n = round_n % _ROUND_TAG_SPAN
    tag = ""
    for _ in range(_ROUND_TAG_WIDTH):
        tag = _ROUND_TAG_ALPHABET[n % len(_ROUND_TAG_ALPHABET)] + tag
        n //= len(_ROUND_TAG_ALPHABET)
    return tag


def tour_session_id(round_n: int) -> str:
    """This round's own demo session id - the ONE thing that makes the board
    draw a new round. ``demo-`` prefixed like every other session this
    script writes (Accept 3), with the round tag inside the first eight
    characters so the round's ledger name is its own too."""
    return f"demo-{_round_tag(round_n)}-tour"


#: The session the ``TOUR`` timeline below is WRITTEN AGAINST, and the real
#: id of round 1: every template event carries this, and ``stamp_round``
#: rewrites it to the playing round's id on the way to the log.
TOUR_SESSION = tour_session_id(1)

#: keel names a session's ledger ``keel-plan-<sess8>.md`` where sess8 is the
#: first eight characters of the session id (``KeelEvent.sess8``). The tour
#: applies that real rule to its own synthetic id rather than picking a
#: prettier name, so the board's per-round ledger lookup resolves exactly
#: as it does for a real session.
TOUR_SESS8 = TOUR_SESSION[:8]

#: KEEL ADDITION (T346): the placeholder a beat's prose uses where it needs
#: to name the round it is playing. Substituted by ``beat_label`` (for what
#: is printed) and by ``stamp_round`` (for what is written), so no label and
#: no ``detail`` can say "round 1" during round 4.
TOUR_ROUND_TOKEN = "{round}"

#: The ledger the tour fills, drawn from the same invented pool the loop
#: uses. KEEL ADDITION (T345c, owner 2026-08-26): TWELVE, not five — five
#: items read thin in the right-hand rail where a real session shows a
#: dozen, and a rail that never moves teaches nothing about progress.
TOUR_TASKS = TASK_POOL

#: KEEL ADDITION (T345c): WHERE THE LEDGER MOVES, and the single source for
#: both the ``check`` cues below and the beat prose that counts them. Beat
#: number -> the items that close in it. Nothing is dumped at the end: the
#: rail reads 0, 0, 0, 2, 4, 6, 11, 12 of twelve across the eight beats, so
#: a viewer sees the ledger FILLING rather than flipping in one frame. The
#: last item is deliberately still open when beat 8 attempts its stop —
#: that is the item stop-with-accounting refuses to let go of.
#: A test pins this map against the cues actually written in ``TOUR``, so a
#: close that moves cannot leave a stale number in a label (the whole point
#: of computing the prose from here instead of typing counts into it).
TOUR_CLOSES: dict[int, tuple[str, ...]] = {
    4: ("T5", "T6"),
    5: ("T7", "T8"),
    6: ("T1", "T9"),
    7: ("T2", "T3", "T4", "T10", "T11"),
    8: ("T12",),
}


def _closed_through(beat_n: int) -> int:
    """How many ledger items are checked once beat ``beat_n`` has played."""
    return sum(len(v) for k, v in TOUR_CLOSES.items() if k <= beat_n)


def _progress(beat_n: int) -> str:
    """The ledger's own reading after this beat — computed, never typed."""
    return f"{_closed_through(beat_n)} of {len(TOUR_TASKS)}"

#: The tour's own cycle number for ``_agent_id``/``_tool_use_id``, so a tour
#: never collides with a loop cycle's synthetic ids.
TOUR_CYCLE = 341

TOUR_PLAN_HEADER = """# Demo plan ledger — the forty-second tour (synthetic)

Written by scripts/keel_demo.py --tour. Every task below is invented for
this demo run; nothing here names real work. The orchestration dashboard
reads this file exactly like a real per-session ledger, so the boxes flip
as the tour's synthetic reviews land.

## Tasks

"""

#: KEEL ADDITION (T346): the six synthetic agents of ONE round, by the role
#: each stands for. Named here rather than inline because a round gets its
#: OWN six ids - a real record never reuses an agent id across sessions, and
#: a board paging back to round 1 must not find round 4's hands on it.
_TOUR_ROLES = (
    "keel:executor",
    "keel:researcher",
    "keel:executor-deep",
    "keel:executor-deep/retry",
    "keel:reviewer-tests",
    "keel:reviewer-correctness",
)

_TOUR_EXECUTOR = _agent_id(TOUR_CYCLE, "keel:executor")
_TOUR_RESEARCHER = _agent_id(TOUR_CYCLE, "keel:researcher")
_TOUR_DEEP = _agent_id(TOUR_CYCLE, "keel:executor-deep")
_TOUR_DEEP_RETRY = _agent_id(TOUR_CYCLE, "keel:executor-deep/retry")
_TOUR_TESTS = _agent_id(TOUR_CYCLE, "keel:reviewer-tests")
_TOUR_CORRECTNESS = _agent_id(TOUR_CYCLE, "keel:reviewer-correctness")


def _ev_session_start() -> dict:
    """The session's own start line. ``model`` is the ORCHESTRATOR'S seat —
    the board draws the Captain's pill from exactly this field
    (``sessionModel(latestSession)``), so recording a crew tier here would
    put the wrong tier on the first card a viewer reads (T345b)."""
    return {
        "event": "session_start", "session": TOUR_SESSION,
        "source": "startup", "model": ORCHESTRATOR_MODEL,
    }


def _ev_session_end(reason: str) -> dict:
    return {"event": "session_end", "session": TOUR_SESSION, "reason": reason}


def _ev_activity(tool: str, detail: str, agent_type=None, agent_id=None) -> dict:
    """One ``activity`` line. ``agent_type`` absent (null) means main-session
    work — a fact, not a gap (``action_record``'s own comment), and the field
    the board attributes a satellite by."""
    return {
        "event": "activity", "session": TOUR_SESSION,
        "agent_type": agent_type, "agent_id": agent_id,
        "tool": tool, "detail": detail,
    }


def _ev_launch(
    uid: str, subagent_type: str, model: str, effort: str,
    description: str, prompt_head: str, *, agent_id: str | None = None,
    opening: bool,
) -> dict:
    """One half of a LAUNCH hand-off. The open half cannot know the launch's
    id, its acknowledgment or whether it backgrounded — those are nulls by
    construction there and answers on the close half."""
    return {
        "event": "handoff_start" if opening else "handoff_end",
        "handoff_kind": "launch", "session": TOUR_SESSION, "tool_use_id": uid,
        "agent_id": None if opening else agent_id,
        "launch_ack": None if opening else True,
        "background": None if opening else True,
        "subagent_type": subagent_type, "model": model, "effort": effort,
        "description": description, "prompt_head": prompt_head,
    }


def _ev_resume(
    uid: str, agent_id: str, description: str, prompt_head: str, *, opening: bool
) -> dict:
    """One half of a RESUME hand-off: an id, and three nulls the send could
    not know (``resume_record``). The board joins the route back on the read
    side (T337) — which is exactly what beat 7 exercises."""
    return {
        "event": "handoff_start" if opening else "handoff_end",
        "handoff_kind": "resume", "session": TOUR_SESSION, "tool_use_id": uid,
        "agent_id": agent_id,
        "subagent_type": None, "model": None, "effort": None,
        "description": description, "prompt_head": prompt_head,
    }


def _ev_subagent_stop(agent_id: str, agent_type: str) -> dict:
    return {
        "event": "subagent_stop", "session": TOUR_SESSION,
        "agent_id": agent_id, "agent_type": agent_type,
        # The payload names no transcript for a synthetic agent, and a null
        # says so; a path here would be a file that does not exist.
        "session_transcript": None,
    }


def _ev_review(task: str, verdict: str, notes: str) -> dict:
    return {
        "event": "review", "session": TOUR_SESSION,
        "task": task, "verdict": verdict, "notes": notes,
    }


def _ev_gate_block(gate: str, tool: str, target: str, kind: str = "pre_write") -> dict:
    """One write-gate refusal. ``detail`` is a MAPPING, as the real gate
    writes it (``deny(..., target=...)`` — the board stringifies it server
    side); ``gate`` names the rule that fired, and the two the tour shows,
    ``plan`` and ``policy_lock``, are two different rules rather than one
    trick twice."""
    return {
        "event": "gate_block", "gate": gate, "kind": kind, "tool": tool,
        "session": TOUR_SESSION, "detail": {"target": target},
    }


def _ev_stop_block(open_item_ids: tuple[str, ...]) -> dict:
    """One stop-with-accounting refusal, carrying the six fields the real
    gate computes before it denies (hooks/keel_stop.py's own list)."""
    return {
        "event": "stop_block", "gate": "stop", "session": TOUR_SESSION,
        "detail": {
            "open_items": len(open_item_ids),
            "stale_inflight_items": 0,
            "unverified_filed_items": 0,
            "open_item_ids": list(open_item_ids),
            "stale_inflight_item_ids": [],
            "unverified_filed_item_ids": [],
        },
    }


class Cue(NamedTuple):
    """One thing that happens inside a beat, at ``dt`` (a fraction of the
    tour's total duration) after that beat's own offset.

    Exactly one of ``event`` (an audit line to append) and ``ledger`` (a
    ledger edit) is set: the ledger is a file on disk, not an event class,
    and pretending otherwise would put a fake line in the log.
    """

    dt: float
    event: dict | None = None
    ledger: tuple[str, str] | None = None


class Beat(NamedTuple):
    """One beat of the tour: its number, its offset as a fraction of the
    total duration, what a viewer is meant to see, and its cues."""

    n: int
    at: float
    label: str
    cues: tuple[Cue, ...]

    @property
    def events(self) -> tuple[dict, ...]:
        """The audit lines this beat emits, in order."""
        return tuple(c.event for c in self.cues if c.event is not None)

    @property
    def span(self) -> float:
        """How far past ``at`` this beat's last cue lands, as a fraction."""
        return max((c.dt for c in self.cues), default=0.0)


(_T1, _T2, _T3, _T4, _T5, _T6,
 _T7, _T8, _T9, _T10, _T11, _T12) = TOUR_TASKS


def _ev_review_pass(task: tuple[str, str], note: str) -> dict:
    """A passing verdict on one ledger item, in the orchestrator's own
    voice — the writer of a ``review`` line is the orchestrator, not a hook,
    so an item the Captain did herself is filed exactly like a delegated
    one (scripts/keel_review.py)."""
    return _ev_review(task[0], "pass", f"Demo review: {task[1]} — {note}.")

TOUR: tuple[Beat, ...] = (
    Beat(
        1, 0.00,
        "session opens: the Captain alone, the ledger empty, the board calm",
        (
            Cue(0.00, _ev_session_start()),
        ),
    ),
    Beat(
        2, 0.10,
        "a write with NO plan on file: the PLAN GATE refuses it",
        (
            # No ``activity`` line goes with this, and that is the point: a
            # refused write never reaches PostToolUse, so the gate line is
            # the ONLY record of the attempt. The refusal is also true of
            # this very demo project, which has no ledger yet (beat 3
            # writes it) — the tour is not miming a block, it is showing
            # the state that earns one.
            Cue(0.00, _ev_gate_block("plan", "Edit", f"demo/{_T1[0].lower()}.py")),
        ),
    ),
    Beat(
        3, 0.22,
        f"the plan lands: {len(TOUR_TASKS)} tasks on the ledger, round "
        f"{TOUR_ROUND_TOKEN} open ({_progress(3)} done)",
        (
            Cue(0.00, ledger=("plan", "")),
            # The bootstrap carve-out in keel_gate: a write to the session's
            # own ledger is always permitted, so this one records an
            # ``activity`` line where beat 2 recorded a refusal.
            Cue(
                0.00,
                _ev_activity("Write", f".keel/plans/keel-plan-{TOUR_SESS8}.md"),
            ),
            # KEEL ADDITION (T346): the round NUMBER, substituted at emit
            # time - a round-4 line reading "round 1" would be a false
            # record of the very thing this beat is announcing.
            Cue(0.03, _ev_activity(
                "TodoWrite", f"round {TOUR_ROUND_TOKEN}: {len(TOUR_TASKS)} tasks")),
        ),
    ),
    Beat(
        4, 0.35,
        "three agents launch at three different tiers: wires light, "
        f"satellites appear, model+effort pills visible (ledger {_progress(4)})",
        (
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 1), "keel:executor", "sonnet", "default",
                f"{_T1[0]}: {_T1[1]}",
                f"Demo task {_T1[0]} — {_T1[1]} (synthetic, no real work).",
                opening=True)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 1), "keel:executor", "sonnet", "default",
                f"{_T1[0]}: {_T1[1]}",
                f"Demo task {_T1[0]} — {_T1[1]} (synthetic, no real work).",
                agent_id=_TOUR_EXECUTOR, opening=False)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 2), "keel:researcher", "sonnet", "low",
                f"{_T2[0]}: {_T2[1]}",
                f"Demo task {_T2[0]} — {_T2[1]} (synthetic, no real work).",
                opening=True)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 2), "keel:researcher", "sonnet", "low",
                f"{_T2[0]}: {_T2[1]}",
                f"Demo task {_T2[0]} — {_T2[1]} (synthetic, no real work).",
                agent_id=_TOUR_RESEARCHER, opening=False)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 3), "keel:executor-deep", "opus", "high",
                f"{_T3[0]}: {_T3[1]}",
                f"Demo task {_T3[0]} — {_T3[1]} (synthetic, no real work).",
                opening=True)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 3), "keel:executor-deep", "opus", "high",
                f"{_T3[0]}: {_T3[1]}",
                f"Demo task {_T3[0]} — {_T3[1]} (synthetic, no real work).",
                agent_id=_TOUR_DEEP, opening=False)),
            # The satellites: an ``activity`` line carrying the working
            # agent's own type is what puts a task mini-card under its hub
            # (the board attributes chips by agent_type + session inside the
            # hand-off's own window). One step behind the launches so the
            # hubs light first and the tasks hang under them second.
            Cue(0.03, _ev_activity(
                "Edit", f"demo/{_T1[0].lower()}.py",
                agent_type="keel:executor", agent_id=_TOUR_EXECUTOR)),
            Cue(0.03, _ev_activity(
                "Grep", "demo/reports/monthly_query.sql",
                agent_type="keel:researcher", agent_id=_TOUR_RESEARCHER)),
            Cue(0.03, _ev_activity(
                "Edit", f"demo/{_T3[0].lower()}.py",
                agent_type="keel:executor-deep", agent_id=_TOUR_DEEP)),
            Cue(0.06, _ev_activity(
                "Bash", "python -m unittest demo.test_upload_worker",
                agent_type="keel:executor-deep", agent_id=_TOUR_DEEP)),
            # KEEL ADDITION (T345c): the rail starts moving HERE, on the two
            # small items the Captain does herself while the crew is out —
            # her own ``activity`` (no agent_type) and her own verdicts. The
            # ledger reads 2 of 12 by the end of this beat, so a viewer sees
            # a ledger that fills rather than one that flips at the finish.
            Cue(0.06, _ev_activity("Edit", f"demo/{_T5[0].lower()}_setup_guide.md")),
            Cue(0.08, _ev_review_pass(_T5, "one-line correction, verified")),
            Cue(0.08, ledger=("check", _T5[0])),
            Cue(0.08, _ev_review_pass(_T6, "flag and its last reader removed")),
            Cue(0.08, ledger=("check", _T6[0])),
        ),
    ),
    Beat(
        5, 0.50,
        "a POLICY LOCK refusal on a guard file: a second, different "
        f"refusal class (ledger {_progress(5)})",
        (
            # The demo project's OWN policy file, which is the archetypal
            # locked target: governance here is layered (two rules, two
            # verdict lines), not one trick shown twice.
            Cue(0.00, _ev_gate_block("policy_lock", "Edit", ".keel/keel-policy.md")),
            # The rail keeps moving while the feed shows the refusal: two more
            # of the Captain's own items close here.
            Cue(0.03, _ev_activity("Edit", f"demo/{_T7[0].lower()}_settings.py")),
            Cue(0.05, _ev_review_pass(_T7, "lookup cached, hot path measured")),
            Cue(0.05, ledger=("check", _T7[0])),
            Cue(0.05, _ev_review_pass(_T8, "payload logged behind the redactor")),
            Cue(0.05, ledger=("check", _T8[0])),
        ),
    ),
    Beat(
        6, 0.62,
        f"the earned-fail ladder: a reviewer FAILS {_T1[0]}, the work retries "
        f"at the deep tier, the retry PASSES (ledger {_progress(6)})",
        (
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 4), "keel:reviewer-tests", "sonnet", "default",
                f"Review {_T1[0]} tests",
                f"Demo review of {_T1[0]} (synthetic, no real diff).",
                opening=True)),
            Cue(0.00, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 4), "keel:reviewer-tests", "sonnet", "default",
                f"Review {_T1[0]} tests",
                f"Demo review of {_T1[0]} (synthetic, no real diff).",
                agent_id=_TOUR_TESTS, opening=False)),
            Cue(0.01, _ev_review(
                _T1[0], "fail",
                f"Demo review: {_T1[1]} — the test still fails under load; "
                "the cause was not found, only hidden.")),
            Cue(0.01, _ev_subagent_stop(_TOUR_EXECUTOR, "keel:executor")),
            Cue(0.01, _ev_subagent_stop(_TOUR_TESTS, "keel:reviewer-tests")),
            # The escalation: the SAME task, re-dispatched one tier up.
            Cue(0.05, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 5), "keel:executor-deep", "opus", "high",
                f"{_T1[0]} retry (deep tier)",
                f"Demo retry of {_T1[0]} after a failed review (synthetic).",
                opening=True)),
            Cue(0.05, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 5), "keel:executor-deep", "opus", "high",
                f"{_T1[0]} retry (deep tier)",
                f"Demo retry of {_T1[0]} after a failed review (synthetic).",
                agent_id=_TOUR_DEEP_RETRY, opening=False)),
            Cue(0.05, _ev_activity(
                "Edit", f"demo/{_T1[0].lower()}.py",
                agent_type="keel:executor-deep", agent_id=_TOUR_DEEP_RETRY)),
            Cue(0.10, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 6), "keel:reviewer-correctness",
                "sonnet", "default",
                f"Review {_T1[0]} retry",
                f"Demo re-review of {_T1[0]} (synthetic, no real diff).",
                opening=True)),
            Cue(0.10, _ev_launch(
                _tool_use_id(TOUR_CYCLE, 6), "keel:reviewer-correctness",
                "sonnet", "default",
                f"Review {_T1[0]} retry",
                f"Demo re-review of {_T1[0]} (synthetic, no real diff).",
                agent_id=_TOUR_CORRECTNESS, opening=False)),
            Cue(0.11, _ev_review(
                _T1[0], "pass",
                f"Demo review: {_T1[1]} — root cause found at the deep tier "
                "and the test is stable across runs.")),
            Cue(0.11, ledger=("check", _T1[0])),
            Cue(0.11, _ev_subagent_stop(_TOUR_DEEP_RETRY, "keel:executor-deep")),
            Cue(0.11, _ev_subagent_stop(_TOUR_CORRECTNESS, "keel:reviewer-correctness")),
            # One of the Captain's own items closes beside the ladder, so the
            # rail moves in this beat too (T345c).
            Cue(0.12, _ev_review_pass(_T9, "endpoint paginated, limit capped")),
            Cue(0.12, ledger=("check", _T9[0])),
        ),
    ),
    Beat(
        7, 0.78,
        "a resume run inherits its launch route (opus+high on a record that "
        f"carries none), and the ledger closes to {_progress(7)}",
        (
            Cue(0.00, _ev_resume(
                _tool_use_id(TOUR_CYCLE, 7), _TOUR_DEEP,
                f"{_T4[0]} on the same hand",
                "Demo resume: one more pass on an agent already out "
                "(synthetic).",
                opening=True)),
            Cue(0.02, _ev_resume(
                _tool_use_id(TOUR_CYCLE, 7), _TOUR_DEEP,
                f"{_T4[0]} on the same hand",
                "Demo resume: one more pass on an agent already out "
                "(synthetic).",
                opening=False)),
            Cue(0.04, _ev_review_pass(_T2, "slow join found and indexed")),
            Cue(0.04, ledger=("check", _T2[0])),
            Cue(0.04, _ev_review_pass(_T3, "retry path bounded and tested")),
            Cue(0.04, ledger=("check", _T3[0])),
            Cue(0.05, _ev_review_pass(_T4, "migration reversible, on the resumed pass")),
            Cue(0.05, ledger=("check", _T4[0])),
            Cue(0.05, _ev_subagent_stop(_TOUR_RESEARCHER, "keel:researcher")),
            Cue(0.05, _ev_subagent_stop(_TOUR_DEEP, "keel:executor-deep")),
            # The Captain's last two, closed while the crew reports back, so
            # the rail arrives at beat 8 with exactly ONE item open — the one
            # stop-with-accounting is about to refuse to let go of (T345c).
            Cue(0.07, _ev_activity("Edit", f"demo/{_T10[0].lower()}_digest.py")),
            Cue(0.08, _ev_review_pass(_T10, "boundary case covered")),
            Cue(0.08, ledger=("check", _T10[0])),
            Cue(0.08, _ev_review_pass(_T11, "limit raised, validation updated")),
            Cue(0.08, ledger=("check", _T11[0])),
        ),
    ),
    Beat(
        8, 0.90,
        "a stop with one item still open: STOP-WITH-ACCOUNTING refuses it; "
        f"the item closes; the session stops clean (ledger {_progress(8)})",
        (
            Cue(0.00, _ev_stop_block((_T12[0],))),
            Cue(0.03, _ev_activity("Edit", f"demo/{_T12[0].lower()}_backfill.py")),
            Cue(0.04, _ev_review_pass(_T12, "the last item, accounted for")),
            Cue(0.04, ledger=("check", _T12[0])),
            Cue(0.06, _ev_session_end("demo_tour_complete")),
        ),
    ),
)


def tour_plan_path(root: Path, round_n: int = 1) -> Path:
    """This round's own ledger, named by keel's real rule for a session's
    plan file (``keel-plan-<sess8>.md``).

    KEEL ADDITION (T346): one ledger PER ROUND, because that is how the board
    reads them - "each round's ledger is its own plan file", looked up by the
    round's sess8. So round 2 does not reset round 1's file; it writes its
    own, and the rail fills from zero while round 1's finished rail stays
    exactly as it ended for a viewer paging back to it.
    """
    return root / ".keel" / "plans" / f"keel-plan-{tour_session_id(round_n)[:8]}.md"


def write_tour_plan(plan_path: Path) -> None:
    """Beat 3's ledger: every tour item open, nothing checked yet."""
    lines = [TOUR_PLAN_HEADER]
    for task_id, desc in TOUR_TASKS:
        lines.append(f"- [ ] {task_id} — {desc}\n")
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text("".join(lines), encoding="utf-8")


def _apply_ledger(plan_path: Path, action: tuple[str, str]) -> None:
    """Run one ledger cue. Unknown verbs raise rather than pass silently — a
    beat whose ledger edit vanished would leave the final frame wrong."""
    verb, task_id = action
    if verb == "plan":
        write_tour_plan(plan_path)
    elif verb == "check":
        set_task_checked(plan_path, task_id, True)
    else:
        raise ValueError(f"unknown ledger action {verb!r}")


def beat_label(beat: Beat, round_n: int = 1) -> str:
    """One beat's prose with the round it is playing named in it (T346)."""
    return beat.label.replace(TOUR_ROUND_TOKEN, str(round_n))


#: KEEL ADDITION (T346): the hand-off ids the template carries, collected
#: FROM ``TOUR`` itself rather than re-listed here - a mapping typed out by
#: hand could fall behind a beat that gains a launch, and an unmapped id
#: would silently be shared between rounds.
_TOUR_TEMPLATE_UIDS = frozenset(
    event["tool_use_id"]
    for beat in TOUR for event in beat.events
    if event.get("tool_use_id")
)

#: The template's six agent ids, each pointing back at the role it stands
#: for, so a round can re-derive its own six from the same rule.
_TOUR_TEMPLATE_AGENT_IDS = {
    _agent_id(TOUR_CYCLE, role): role for role in _TOUR_ROLES
}


def round_substitutions(round_n: int) -> dict[str, str]:
    """Every template id, mapped to the id ROUND ``round_n`` uses instead.

    Round 1 maps each id to itself (the template IS round 1), so a single
    pass writes exactly the record it wrote before this addition; later
    rounds draw a fresh set from the same deterministic rules the loop's
    cycles use, which is what a real second session looks like - new agents,
    new hand-off ids, nothing carried over but the choreography.
    """
    cycle = TOUR_CYCLE + round_n - 1
    subs = {
        template: _agent_id(cycle, role)
        for template, role in _TOUR_TEMPLATE_AGENT_IDS.items()
    }
    # The sequence number is read back off the template id rather than
    # re-counted, so the mapping cannot drift from what ``TOUR`` carries.
    subs.update(
        {uid: _tool_use_id(cycle, int(uid[-2:])) for uid in _TOUR_TEMPLATE_UIDS}
    )
    return subs


def _stamped(value, sid: str, round_n: int, subs: dict[str, str]):
    """One template value, rewritten for this round. Recurses into the
    mappings and lists keel's own records carry (``gate_block``'s ``detail``,
    ``stop_block``'s id lists), so nothing nested keeps a stale id."""
    if isinstance(value, dict):
        return {
            key: (sid if key == "session" else _stamped(item, sid, round_n, subs))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_stamped(item, sid, round_n, subs) for item in value]
    if isinstance(value, str):
        if value in subs:
            return subs[value]
        return value.replace(TOUR_ROUND_TOKEN, str(round_n)).replace(
            TOUR_SESS8, sid[:8]
        )
    return value


def stamp_round(event: dict, round_n: int) -> dict:
    """One ``TOUR`` template event as ROUND ``round_n``'s own record (T346).

    Four things move and nothing else: the ``session`` (the whole reason the
    board draws a new round), the agent ids, the hand-off ids, and the two
    places a string names the round or its ledger. No field is added, none
    is dropped, and no shape changes - the timeline above stays the single
    description of what a round IS.
    """
    sid = tour_session_id(round_n)
    return _stamped(event, sid, round_n, round_substitutions(round_n))


def beat_schedule(seconds: float = TOUR_SECONDS) -> tuple[tuple[int, float, tuple[float, ...]], ...]:
    """The tour's absolute clock at this duration: one row per beat, each
    ``(beat number, beat offset in seconds, cue offsets in seconds)``.

    Pure — no clock read, nothing written. This is what makes ``--seconds``
    testable without waiting for a tour to play.
    """
    return tuple(
        (b.n, b.at * seconds, tuple((b.at + c.dt) * seconds for c in b.cues))
        for b in TOUR
    )


def run_tour(
    root: Path, *, seconds: float = TOUR_SECONDS, fast: bool = False,
    echo: bool = True, round_n: int = 1,
) -> str:
    """Play the eight-beat tour into ``root``'s demo project as ROUND
    ``round_n``. Returns the demo session id this round used.

    Real time by default — the board polls, so the events have to arrive
    while a viewer is watching. ``fast=True`` executes the SAME timeline with
    no sleeps at all, which is what the tests run: the file that comes out is
    the file a real-time tour would leave behind, minus the waiting.

    KEEL ADDITION (T346): ``round_n`` chooses the session id, the ledger file
    and this round's own agent/hand-off ids (``stamp_round``); ``seconds`` is
    the length of THIS ROUND, not of the whole demo. Rounds are otherwise
    identical — the choreography is the point of the tour, so it repeats
    exactly rather than drifting.
    """
    sid = tour_session_id(round_n)
    log_path = root / ".keel" / "audit" / "keel-audit.jsonl"
    plan_path = tour_plan_path(root, round_n)
    started = time.monotonic()

    def _hold(until: float) -> None:
        if fast:
            return
        gap = started + until - time.monotonic()
        if gap > 0:
            time.sleep(gap)

    for beat in TOUR:
        _hold(beat.at * seconds)
        if echo:
            print(
                f"  round {round_n} · beat {beat.n}/{len(TOUR)}  "
                f"{beat.at * seconds:5.1f}s  {beat_label(beat, round_n)}"
            )
        for cue in beat.cues:
            _hold((beat.at + cue.dt) * seconds)
            if cue.ledger is not None:
                _apply_ledger(plan_path, cue.ledger)
            if cue.event is not None:
                _append(
                    log_path,
                    {"v": 1, "ts": _now_iso(), **stamp_round(cue.event, round_n)},
                )
    # The final frame is part of the tour: ledger complete, board quiet.
    _hold(seconds)
    return sid


def run_tour_rounds(
    root: Path, *, seconds: float = TOUR_SECONDS, fast: bool = False,
    repeat: bool = True, echo: bool = True,
) -> int:
    """Play round after round until Ctrl-C; return how many rounds played.

    KEEL ADDITION (T346, owner 2026-08-26: "the demo should run unless I
    stopped it"). The tour used to play once and stop, so a demo left on a
    screen froze on its final frame at the moment it became worth watching.
    It now REPEATS, and each repetition is a NEW ROUND on the board — a new
    session, its own ledger filling from zero (the round comment above says
    why that, and only that, is what a round is).

    ``repeat=False`` plays exactly one round and RETURNS, which is what
    ``--once`` and ``--fast`` ask for: a scripted proof and this project's own
    test suite both need a call that ends. With ``repeat=True`` the only way
    out is ``KeyboardInterrupt``, deliberately NOT caught here — ``main``
    owns the one handler, because it is the handler that also takes the
    spawned board down.
    """
    round_n = 0
    while True:
        round_n += 1
        sid = run_tour(root, seconds=seconds, fast=fast, echo=echo, round_n=round_n)
        if echo:
            print(
                f"keel demo tour: round {round_n} complete ({sid}) — "
                "ledger closed, board quiet."
            )
        if not repeat:
            return round_n
        if echo:
            print(
                f"keel demo tour: opening round {round_n + 1} — a fresh demo "
                "session, its own ledger from zero. Ctrl-C stops."
            )


def _print_tour_banner(root: Path, seconds: float, *, repeat: bool) -> None:
    print("=" * 72)
    print(f"keel demo — THE {seconds:.0f}-SECOND TOUR (T341). Synthetic events only.")
    print(f"Demo project directory: {root}")
    # KEEL ADDITION (T346): the banner says WHICH of the two shapes this run
    # is, because "it stopped" and "it is between rounds" look identical for
    # the second or two the final frame is up.
    if repeat:
        print(
            f"Repeating: one ROUND every {seconds:.0f}s, each a fresh demo "
            "session with its own ledger, until Ctrl-C (--once for one pass)."
        )
    else:
        print("One pass only (--once/--fast), then the board is held for reading.")
    print("Eight beats:")
    for beat in TOUR:
        print(f"  {beat.n}. {beat.at * seconds:5.1f}s  {beat_label(beat, 1)}")
    print("Watch it live (in another terminal, if --serve was not used):")
    print(
        f"    python scripts/keel_orchestration_dashboard.py --dir "
        f"\"{root}\" --port {DEMO_PORT}"
    )
    print("=" * 72)


def _hold_board(url: str) -> None:
    """Keep serving after the tour has played. Returns only on Ctrl-C.

    KEEL ADDITION (T345a, owner 2026-08-26): the tour used to end by
    terminating the board it had just spawned, so the FINAL FRAME — ledger
    complete, board quiet, the one frame a viewer wants to sit and read —
    vanished at the instant it became worth reading, twice in front of the
    owner. The tour's last act is now to stand still.

    THE INTERRUPT IS NOT CAUGHT HERE. ``main`` already has one handler for
    Ctrl-C, and it is the handler that terminates the spawned board in its
    ``finally``; a second one here would either duplicate that or swallow
    the signal before it reached the teardown.

    NEVER REACHED UNDER ``--fast``: the caller decides, because the test
    suite runs the tour with ``--fast`` and a blocking wait there would hang
    CI rather than fail it.
    """
    print("")
    print(f"keel demo: the board is STILL SERVING at {url}")
    print("The final frame stays up. Press Ctrl-C to stop the board and exit.")
    while True:
        time.sleep(0.5)


def _print_banner(root: Path) -> None:
    print("=" * 72)
    print("keel demo mode — SYNTHETIC EVENTS ONLY, nothing here is real work.")
    print(f"Demo project directory: {root}")
    print("Watch it live (in another terminal):")
    print(
        f"    python scripts/keel_orchestration_dashboard.py --dir "
        f"\"{root}\" --port {DEMO_PORT}"
    )
    print("Ctrl-C stops the cycle here.")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel_demo.py",
        description="Zero-token synthetic orchestration-board demo (T140).",
    )
    parser.add_argument(
        "--dir", default=None,
        help="throwaway demo project directory (default: a fresh temp dir; "
             "NEVER the real project's .keel/)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="skip every sleep — a full cycle runs instantly (tests/CI)",
    )
    parser.add_argument(
        "--cycles", type=int, default=None,
        help="stop after N cycles instead of looping until Ctrl-C",
    )
    parser.add_argument(
        "--serve", action="store_true",
        help="also spawn the orchestration dashboard as a subprocess, bound "
             "to 127.0.0.1 only, on --port",
    )
    parser.add_argument("--port", type=int, default=DEMO_PORT, help="dashboard port for --serve")
    # KEEL ADDITION (T341): the tour is a DISTINCT MODE, not a replacement —
    # the loop above stays exactly as it was and is still the default.
    parser.add_argument(
        "--tour", action="store_true",
        help="play the scripted eight-beat tour instead of the loop (T341), "
             "round after round until Ctrl-C (T346); --cycles does not apply",
    )
    # KEEL ADDITION (T346): REPETITION IS THE DEFAULT, because the owner's
    # expectation of a demo is that it runs until stopped. ``--once`` is the
    # opt-out for the two callers that need a run which ENDS: a scripted
    # proof, and this project's own suite.
    parser.add_argument(
        "--once", action="store_true",
        help="with --tour: play ONE pass instead of repeating, then hold the "
             "board (T346; --fast implies it)",
    )
    parser.add_argument(
        "--seconds", type=float, default=TOUR_SECONDS,
        help=f"length of ONE --tour round in seconds (default "
             f"{TOUR_SECONDS:.0f}); every beat's offset is a fraction of "
             "this, so the whole choreography scales",
    )
    args = parser.parse_args(argv)

    if args.tour and args.seconds <= 0:
        print("keel demo: --seconds must be greater than zero", file=sys.stderr)
        return 2

    if args.dir:
        root = Path(args.dir).resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="keel-demo-")).resolve()

    # ENFORCE the never-touch-a-real-.keel/ claim in code, before anything is
    # written (Accept 1) — see ``_refusal_reason``.
    reason = _refusal_reason(root)
    if reason is not None:
        print(f"keel demo: {reason}", file=sys.stderr)
        return 2

    if args.dir:
        root.mkdir(parents=True, exist_ok=True)

    # KEEL ADDITION (T341): the tour's first beat is an EMPTY ledger and its
    # second is a plan-gate refusal, so the loop's pre-filled plan file is
    # not written in tour mode — see ``build_demo_project``.
    log_path, plan_path = build_demo_project(root, with_plan=not args.tour)
    # KEEL ADDITION (T346): ONE place decides how many passes the tour plays.
    # ``--fast`` forces a single pass whatever else was asked for: it is the
    # suite's own path, and a repeating tour there would not fail CI, it
    # would HANG it. ``--once`` is the human-facing opt-out; everything else
    # repeats, which is the owner's stated expectation of a demo.
    repeat_tour = args.tour and not args.once and not args.fast
    if args.once and not args.tour:
        print("keel demo: --once applies to --tour; the loop uses --cycles.")
    if args.tour:
        _print_tour_banner(root, args.seconds, repeat=repeat_tour)
    else:
        _print_banner(root)

    server = None
    if args.serve:
        dashboard = Path(__file__).resolve().parent / "keel_orchestration_dashboard.py"
        cmd = [sys.executable, str(dashboard), "--dir", str(root), "--port", str(args.port)]
        print(f"Spawning dashboard subprocess (disclosed): {' '.join(cmd)}")
        server = subprocess.Popen(cmd)  # noqa: S603 - argument list, no shell (R5)

    try:
        if args.tour:
            if args.cycles is not None:
                print("keel demo: --cycles does not apply to --tour; ignoring it.")
            run_tour_rounds(
                root, seconds=args.seconds, fast=args.fast, repeat=repeat_tour
            )
            # KEEL ADDITION (T345a): the board OUTLIVES the tour. Three
            # conditions now, all necessary: there has to BE a board (this
            # process spawned one), the run has to be a real-time one a human
            # is watching (``--fast`` is the suite's own path and must return
            # immediately — a blocking wait there hangs CI instead of failing
            # it), and the tour has to have STOPPED PLAYING. A repeating tour
            # never gets here at all: it leaves ``run_tour_rounds`` only by
            # Ctrl-C, which belongs to the handler below and its teardown —
            # holding a board after the interrupt that asked for everything
            # to stop is exactly what T346 must not do.
            if not repeat_tour and server is not None and not args.fast:
                _hold_board(f"http://127.0.0.1:{args.port}/")
        else:
            cycle = 0
            while args.cycles is None or cycle < args.cycles:
                run_cycle(log_path, plan_path, cycle, fast=args.fast)
                cycle += 1
    except KeyboardInterrupt:
        print("\nkeel demo mode: stopped.")
    finally:
        if server is not None:
            # KEEL ADDITION (T346): and WAITED FOR. ``terminate`` only asks;
            # returning while the child is still dying leaves its listening
            # socket on the port for the next run to trip over, which is the
            # one way a clean Ctrl-C can still leave a mess behind. ``kill``
            # is the fallback for a board that will not go.
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
    return 0


if __name__ == "__main__":
    sys.exit(main())
