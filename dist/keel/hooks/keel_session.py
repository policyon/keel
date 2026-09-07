#!/usr/bin/env python3
"""keel session boundaries.

Contract
--------
Reads   : one ``KeelEvent`` of kind ``session_start`` or ``session_end``.
          From the project it reads whether ``<cwd>/.keel/`` exists - the
          adoption test - and, for the orientation lines below, four more
          project facts through ``scripts/keel_survey.py``: the arming
          file's declared tier (``arming_report``), its ``## Policy lock``
          section if any - including the ``workshop:`` prefixes in force and
          the ones keel refused - and its ``## Holds`` section, both from the
          one ``lock_config_report``, over one parse - and whether another gate
          stack holds an event that can stop work over this project
          (``conflicts_for`` with ``conflict_scan_notes``, which read the
          project's and the user's PreToolUse/Stop registrations as well as
          the foreign ``.claude/POLICY.md`` fast path - so this line is a
          RE-EVALUATION at every session start, not a memory of what arming
          time found). From the environment - the same module's
          ``switches_report`` - the three kill switches ``KEEL_OVERRIDE``,
          ``KEEL_GATE`` and ``KEEL_PLAN_TTL_MIN``, read from the ``env``
          mapping ``run`` is given or this process's own environment when
          none is given, exactly as ``override_reminder`` already resolves
          that same ambiguity. From its own INSTALLATION it reads the shipped
          feature registry, through ``keel_features``, to learn whether this
          edition carries the knowledge feature at all. From the payload it
          takes ``session_id``, and for the record the harness's own
          ``source``, ``model`` and ``reason`` fields where they are present;
          none of them is ever interpolated into a path or a command (R5).
          ``model`` is now recorded on EVERY ``session_start`` line, carrying
          null where neither the payload nor the transcript names one - see
          "What the harness actually sends" below. Where the payload names no
          model, ONE more file is read: the payload's own ``transcript_path``,
          and only its last ``TRANSCRIPT_TAIL_BYTES`` bytes, for the newest
          ``message.model`` in it (``model_from_transcript``). That read is
          bounded, best-effort and never required: a transcript that is
          absent, unreadable, empty or malformed leaves the seat null exactly
          as it was before this fallback existed.
Emits   : on ``session_start`` in an adopted project, the plan line on stdout;
          beneath it, while ``KEEL_OVERRIDE`` is on AND the project is armed
          at the enforcing tier (there being no lock otherwise), one line
          reminding the user that the policy lock is suspended and how to
          restore it; beneath THAT, five ORIENTATION lines - arming state,
          policy-lock state, the conflict scan, the three kill switches'
          raw values, and the user's standing holds - so a skill whose whole
          job is orientation before a
          plan exists (``/keel:castoff``) reads those facts from this
          session's own context instead of shelling out to
          ``python scripts/keel.py survey``, which the plan gate would
          refuse before a ledger exists; beneath THOSE, ONE live-view line
          naming the orchestration viewer's URL and its start command (see
          "The live-view line" below); and -
          beneath THAT, and ONLY when the payload's ``source`` says this start
          follows a COMPACTION, the recovery block (T228): where the lossless
          pre-compaction transcript is, one line telling the model to retrieve
          exact detail from it rather than reconstruct it, and the last few
          user prompts verbatim from keel's own per-session log. On every other
          source that block is empty and costs nothing, in bytes or in cap; and
          when the project holds knowledge records - the knowledge index under
          a hard byte cap, or, in an edition that does not carry the knowledge
          feature, one line saying so in its place. Claude Code adds a
          SessionStart hook's stdout to the session's context, which is the
          whole mechanism: the orchestrator learns its own plan-file path,
          whether it is running unlocked, what this project's arming and
          policy-lock state are, whether the conflict scan ran clean, what
          its kill switches are actually set to - so an armed tier is never
          mistaken for live gates when ``KEEL_GATE=off`` - and what this
          project already knows - or that this installation cannot know it.
          Nothing is emitted on ``session_end``, and nothing at all outside
          an adopted project.
Writes  : one ``session_start`` or ``session_end`` line to
          ``<cwd>/.keel/audit/keel-audit.jsonl``, and only where ``.keel/``
          already exists. A project that never adopted keel is left byte-for-
          byte untouched - the arming model in miniature (R25). On
          ``session_start`` in an adopted project it ALSO feeds this
          project's own path into keel's user-global fleet registry
          (``keel_registry.write``, T227) - never into this or any other
          project's own tree, per
          ``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md``;
          see ``registry_write`` below.
Argv    : none. Imported by ``keel_hook.py`` and dispatched as ``session``.

Exit codes
----------
0, always. A session boundary carries no verdict.

Synchronicity
-------------
The ``SessionStart`` registration is deliberately NOT async: its stdout is
context, and context that arrives after the model has started is not
context. ``SessionEnd`` is a pure observer and is registered async
(convention 11).

The injection cap (R16, R34)
----------------------------
Injected context is spent before the user has asked for anything, so the
knowledge index is bounded in BYTES and the bound is enforced HERE, at the
injector, rather than measured and reported somewhere else:
``KEEL_INJECT_CAP_BYTES`` (default 4096) is a limit a gate applies, not a
sentence in a document (R32).

When the records do not fit, the block is truncated at a RECORD BOUNDARY -
never mid-line, because half a record line is a fact nobody can look up - and
one visible line is appended naming how many records were withheld and the
command that reaches them. Overflow is therefore always visible in the very
context it was cut from (R34): the reader can see that there is more, count
it, and go and get it.

The knowledge lines themselves come from ``scripts/keel_index.py``: this hook
holds no record parser of its own, and the index reads no gate code, so the
dependency runs one way only.

That is a dependency across a feature seam, and the seam is honoured rather
than assumed: ``scripts/keel_index.py`` belongs to the knowledge feature, and
an edition without it ships no such file. ``knowledge_notice`` asks
``keel_features`` whether this installation carries the feature at all, and
where it does not, ONE line naming the missing feature is injected in the
channel the index block would have used - the injected context is where the
absence has to be visible, because that is where the reader looks for what
this project knows (convention 7). Where the feature IS installed, that
function returns nothing and the index path below is byte-for-byte what it
always was.

Both cross-module reads are LAZY, inside the function that needs them:
``keel_features`` like ``keel_index``. ``hooks/keel_hook.py`` imports this
module in order to reach ``gate`` and ``stop``, so anything imported at this
module's scope is imported by the launcher too, upstream of the launcher's own
fail-open handler. A defect in either of those files may cost one line of
injected context and one line of stderr; it may not cost the session its gates.

Why the injected path matters
-----------------------------
The plan gate demands a fresh ledger at ``.keel/plans/keel-plan-<sess8>.md``
and nowhere else, and parallel sessions never share one. Telling the model
that path at session start is what turns the gate from an obstacle into a
protocol - the single highest-value line of output. The string is
built by ``keel_gate.session_plan_relpath`` rather than re-spelled here, so
the path injected and the path enforced cannot drift apart.

What the harness actually sends (measured 2026-08-13)
-----------------------------------------------------
The field naming the model that took the orchestrator seat is the payload's
own top-level ``model``, a plain string. MEASURED, not assumed:

* this project's own audit log holds 129 ``session_start`` lines; 11 carry a
  ``model`` (``claude-opus-4-8[1m]`` twice, ``claude-opus-5[1m]`` nine times)
  and 118 do not. Every line that carries one was written on or before
  2026-08-03T05:31:55Z; every line after it carries none.
* a second, independent recorder of the same payload field on this machine -
  a hook outside this repository that writes the payload's ``model``
  unconditionally - shows the same shape and the same drying-up: 1 of the 256
  ``session_start`` lines it held when this was measured carries a model, the
  last of them on 2026-07-19. That log is live and still growing, so its total
  is a snapshot; the ratio and the date are the evidence, not the count.

WHY THE OLD LINES CARRY A MODEL KEY AND THE NEW ONES DO NOT: nothing in keel
changed. ``START_FIELDS`` has named ``model`` since 0.2.0 (2026-08-01), the
adapter has always passed the whole payload through as ``raw``, and git shows
no edit to either since. The HARNESS stopped supplying the field, and this
record's own shape - a key present only when a value was - turned that into
silence. That is the defect fixed here: an absent model is now written as an
explicit ``null``, so a reader can tell "the harness said nothing" from
"nobody looked". No value is invented to fill the gap.

THE TRANSCRIPT FALLBACK (T337), and why the paragraph above once forbade it
------------------------------------------------------------------------
That honest null was the right fix and an incomplete one. It made the silence
LEGIBLE without making it RARE: by 2026-08-26 every session_start line in this
project carried ``"model": null``, and the live board's own Captain card read
"model unrecorded" for every session ever recorded - a field whose only useful
value is a name, always reading as an absence.

This file previously stated the stronger position that nothing would be read
out of the transcript to guess a model, on the grounds that a transcript's
``message.model`` describes the messages rather than the seat. That reasoning
is sound about a general transcript and wrong about THIS one. The payload hands
this hook ``transcript_path``: the transcript OF THE SESSION BEING STARTED. The
model on its newest assistant message is not a guess about who is in the seat -
it is the record of who has been answering in it. So the fallback is not an
inference dressed as a fact; it is the same fact read from the other end.

What keeps it honest is the shape of the failure, not the confidence of the
source:

* it fires ONLY where the payload named nothing. A model the payload supplied
  is never second-guessed, and one it supplied that could not be SCREENED
  stays null rather than being quietly replaced by the transcript's answer -
  "supplied in a shape keel could not screen" and "not supplied" are the two
  facts an honest null must not blur, and a substitution would blur them.
* it reads only a line it can ATTRIBUTE. A model named on a line that does not
  mark itself as the assistant's - by the entry's ``type`` or the message's
  ``role`` - is refused rather than recorded, because a stray ``model`` key on
  somebody else's line is not evidence of who is answering. Measured: all 1106
  model-carrying lines in four real transcripts on this machine set both
  markers, and no non-assistant line carries a model at all, so the requirement
  costs nothing and closes the one path that could have written a
  wrong-but-green name (``_is_assistant_line``).
* it is BOUNDED. ``keel_compaction`` refuses to read transcripts at all
  because they "can be tens of megabytes", and that judgement stands: only the
  last ``TRANSCRIPT_TAIL_BYTES`` are ever read, from the tail, with one seek.
  A model named only beyond that ceiling is NOT found, and the seat stays
  null - a bounded reader that misses an old line is the intended behaviour,
  not a defect to widen the bound for.
* it CANNOT FAIL LOUDLY. Absent field, absent file, a directory, a permission
  error, half a line at the tail's edge, malformed JSON, a screen that raises -
  every one of them yields None, one stderr line at most, and the same
  ``null`` this record has always carried. A best-effort read of somebody
  else's file may never cost the session its context.

The record's SHAPE is unchanged - ``model`` is a plain string or null, whatever
resolved it - so every existing reader (the dashboard's ``sessionModel``, the
attestation) is unaffected and needs no change.

``model_of`` also accepts a MAPPING under that key, taking ``id``, then
``display_name``, then ``name``. That branch is defensive rather than
measured - no such payload appears in either corpus above - and it exists so
that a harness which one day sends an object rather than a string records the
name it sent instead of a silent null: "not supplied" and "supplied in a
shape keel could not read" are exactly the two facts an honest null must not
blur.

THE SYNTHETIC-LINE REFINEMENT (T482/BL39), and why the fallback above was not
yet safe to rely on for every stop
------------------------------------------------------------------------
The transcript fallback above reads the NEWEST assistant line, and until now
that was the whole rule. MEASURED 2026-09-04: the harness itself writes
assistant lines whose ``message.model`` is not a model at all but a literal
placeholder - ``<synthetic>`` in what was measured - on a line it generated
itself rather than one a model produced: an API spend-limit error, and "No
response requested." twice, none of the three marked ``isSidechain``. The
ordinary sequence "an API failure kills a delegation, the harness writes a
synthetic assistant line, the session stops, the stop hook reads the newest
assistant line" would otherwise make the newest line the placeholder, and
record the seat as ``<synthetic>`` - a name, not an absence, and a wrong one.
``model_from_transcript`` now treats a value with that SHAPE as absent and
continues walking to the assistant line before it, so a real model one line
older is still found; see that function's own docstring for the rule and
``_is_placeholder_model`` for the test.

The live-view line (R19)
------------------------
One more injected line names the orchestration viewer: its URL, the caveat
that the server walks to the next port when 8770 is busy, and the exact
command that starts it. The port is a CONSTANT here, never derived from the
project path or from the user - R19, upheld at
``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``: a derived
port is undefined on some platforms and collides on all of them. Hence a
caveat rather than a computation: the line says where to look FIRST and tells
the reader to trust the URL the server itself prints, which is the only
authority on the port actually bound.

Nothing outside this repository is read or written to produce it. The
predecessor's cross-project registry - a file under the user's home naming
every orchestrated project - is deliberately NOT adopted; the owner
re-affirmed that park on 2026-08-13.

The line is a constant, so there is nothing in it that can fail: no survey,
no filesystem, no environment. ``live_view_line`` still guards its own
redaction call, so even a fault THERE costs the sentence its redaction rather
than costing the session its context. Its bytes are subtracted from the
injection cap alongside the orientation block's, so an always-on addition
cannot silently widen what the cap bounds (R16, R32).

Failure policy
--------------
FAIL-OPEN. A session boundary must never be able to break the session it
brackets: an unwritable audit directory, a payload of an unexpected shape,
an index that cannot be read, or any other fault escaping ``run``'s own
``try`` is reported as one line on stderr and the subcommand returns 0 -
and the plan line is still emitted, because losing the knowledge index must
not cost the session its ledger path. An orientation fact (arming, lock,
conflicts, switches or holds) that cannot be computed is different: each of the
five is computed inside its own ``try`` in ``orientation_lines``, so the
fault renders as its own sentence on STDOUT - the same channel the other,
unaffected orientation lines use - and never reaches ``run``'s stderr path
at all; ``run`` still returns 0. Nothing is swallowed silently (convention
7) on either channel: a conflict scan that raises is reported as its OWN
sentence saying so, never folded into "0 conflicts" - an empty result and a
failed one are different facts and must stay different strings on the page
(see ``a-swallowed-error-renders-as-a-fact``). A scan that RAN but could not
read one of its sources is a third fact and gets a third sentence: the count
is stated as a floor, with the number of unread sources, rather than as a
clean zero.
``tests/test_keel_wave2.py`` asserts this declaration.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network. Every file operation names its encoding (convention 6).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_events import KeelEvent, append_audit, record_root_as_spelled  # noqa: E402
from keel_gate import (  # noqa: E402
    OVERRIDE_REMINDER,
    POLICY_RELPATH,
    env_on,
    is_armed,
    override_age_note,
    resolve_project,
    session_plan_relpath,
)
from keel_redact import redact  # noqa: E402

#: The arming file, as the injected line names it.
POLICY_DISPLAY = "/".join(POLICY_RELPATH)

#: Payload fields worth keeping on the session_start record. They describe
#: who took the orchestrator seat; none of them steers anything.
START_FIELDS: tuple[str, ...] = ("source", "model")

#: The one field that names the model in the seat, and the keys tried when a
#: harness sends an object under it rather than a string (defensive - see
#: "What the harness actually sends" in the module contract). Unlike the rest
#: of ``START_FIELDS`` this one is recorded even when the payload supplies
#: nothing, as ``null``: absent and unasked must not read alike.
MODEL_FIELD = "model"
MODEL_NAME_KEYS: tuple[str, ...] = ("id", "display_name", "name")

#: The payload field naming the harness's transcript for THIS session, and the
#: key inside one of its lines that names the model which produced that line.
#: The fallback below reads those two names and nothing else out of the file.
TRANSCRIPT_FIELD = "transcript_path"
TRANSCRIPT_MESSAGE_KEY = "message"

#: The two places a transcript line marks itself as the ASSISTANT's, and the
#: value that says so. EITHER marker is enough (see ``model_from_transcript``):
#: MEASURED on this machine, all 1106 model-carrying lines across four real
#: transcripts are ``type="assistant"`` AND ``role="assistant"``, and not one
#: non-assistant line carries a model at all - so requiring the mark costs
#: nothing today, and accepting either spelling keeps the fallback working if
#: the harness ever drops one of them.
TRANSCRIPT_TYPE_KEY = "type"
TRANSCRIPT_ROLE_KEY = "role"
TRANSCRIPT_ASSISTANT = "assistant"

#: THE SYNTHETIC-LINE SHAPE (T482/BL39). The harness writes a literal
#: placeholder into ``message.model`` on an assistant line IT authored - an
#: API spend-limit error, "No response requested." - rather than a model that
#: produced it, and does not mark either kind ``isSidechain``. MEASURED
#: 2026-09-04: a real transcript carried three such lines, all spelled
#: ``PLACEHOLDER_MODEL_EXAMPLE`` below. That one spelling is named here for
#: the record, not as the whole rule: ``_is_placeholder_model`` tests the
#: SHAPE a harness placeholder takes - a value wrapped in angle brackets,
#: which no real model id is ever spelled as - because the harness's exact
#: placeholder text is measured, not guaranteed, and hard-coding one string
#: would miss the next one it invents.
PLACEHOLDER_MODEL_OPEN = "<"
PLACEHOLDER_MODEL_CLOSE = ">"
PLACEHOLDER_MODEL_EXAMPLE = "<synthetic>"

#: THE CEILING ON THE FALLBACK READ, in bytes from the END of the transcript.
#: A limit a gate applies, not a sentence in a document (R32) - and the reason
#: this fallback is allowed to exist at all: ``keel_compaction`` declines to
#: read transcripts because they "can be tens of megabytes", and this one reads
#: 64 KB of any transcript, however large, in one seek. A model named only
#: further back than this is NOT found and the seat stays null; that is the
#: designed outcome of a bounded reader, not a bound to be widened.
TRANSCRIPT_TAIL_BYTES = 65536

#: The tag the live-view line opens with. Its own tag, NOT
#: ``ORIENTATION_TAG``: the five castoff lines are survey-derived facts about
#: this project, this one is a fixed pointer at a viewer, and a skill that
#: counts orientation facts must not find an extra one here.
LIVE_VIEW_TAG = "[keel] live view"

#: The viewer's address and start command. CONSTANTS - R19 forbids deriving a
#: port from the project path or the user, so 8770 is chosen and never
#: computed, and the walk-to-the-next-port caveat is stated instead of
#: modelled (``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``).
LIVE_VIEW_URL = "http://127.0.0.1:8770"
LIVE_VIEW_COMMAND = "python scripts/keel_orchestration_dashboard.py --dir ."

#: The hard cap on injected knowledge, in BYTES of UTF-8, and the environment
#: variable that overrides it. A limit a gate reads, never prose (R16, R32).
INJECT_CAP_ENV = "KEEL_INJECT_CAP_BYTES"
DEFAULT_INJECT_CAP_BYTES = 4096

#: The header the index block opens with. It names the count BEFORE the lines,
#: so a truncated block still says how large the corpus is.
INDEX_HEADER = "[keel] knowledge index: {total} record(s), newest first - /keel:chart to search"

#: The overflow line. Plain ASCII on purpose: this string is printed to a
#: harness's stdout on three operating systems, and a console encoding that
#: cannot render a typographic ellipsis would turn a visible truncation into
#: an exception (R34 - the overflow must survive to be seen).
OVERFLOW_MARKER = "[keel] ... {more} more record(s) not shown - /keel:chart to search"

#: Where the knowledge layer lives, relative to this file. The injector reads
#: the index through that module and parses no record itself.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")

#: The feature that owns the knowledge layer in ``scripts/keel-features.json``,
#: and the one component of it this hook reaches for. The component is the
#: fallback evidence when the registry itself cannot be read; a test pins both
#: against the registry, so neither can drift from what the editions are cut
#: along.
KNOWLEDGE_FEATURE = "knowledge"
KNOWLEDGE_COMPONENT = "scripts/keel_index.py"

#: What the injected line calls the block it cannot show. The sentence itself
#: comes from ``keel_features.decline``, so the CLI and this hook say the same
#: thing about the same absence.
KNOWLEDGE_SUBJECT = "the knowledge index"

#: The tag every orientation line opens with, naming the skill this exists
#: for: ``/keel:castoff`` reads its own session's context instead of running
#: ``python scripts/keel.py survey`` from a gate that will not be open yet.
ORIENTATION_TAG = "[keel] castoff"

#: What the policy-lock orientation line calls the EFFECTIVE state while the
#: override is carrying it (BL12/T375). The line used to report the DECLARATION
#: only - "in force" whenever the ``## Policy lock`` section parsed - while the
#: switches line beside it reported ``KEEL_OVERRIDE=on``, so a session's two
#: orientation lines answered different questions and read as a contradiction.
#: The declared state is still named, on the same line, because a suspension is
#: temporary and what it suspends is the thing that comes back.
#:
#: SPELLED HERE AND NOWHERE ELSE, and tests IMPORT it rather than matching a
#: literal: ``.keel/knowledge/a-marker-matched-by-literal-disarms-on-rename.md``
#: is the record of a guard that a rename silently disarmed. The castoff skill's
#: actionability rule reads this word, so it is a contract, not wording.
LOCK_SUSPENDED_STATE = "SUSPENDED by KEEL_OVERRIDE"

#: The tag the hook-error warning opens with (T235). Its OWN tag, like
#: ``LIVE_VIEW_TAG`` and for the same reason: the five castoff lines are
#: survey-derived facts about this project, this one is a fact about KEEL
#: ITSELF, and a skill that counts orientation facts must not find a sixth.
HOOK_FAULT_TAG = "[keel] hook errors"

#: What the plan-file line says of the gates AT THE ENFORCING TIER (BL51).
#: SPELLED HERE AND NOWHERE ELSE, like ``LOCK_SUSPENDED_STATE`` above and for
#: the same reason: tests import it rather than matching a literal, so a
#: rewording cannot silently drift the injected claim from the tested one.
GATES_ENFORCE_CLAIM = (
    "The gates enforce plan-before-write and stop-with-accounting against "
    "that file."
)

#: What the SAME line says BELOW the enforcing tier (0 observe, 1 log - the
#: ladder ``keel_gate.ENFORCING_TIER`` is pinned against). Before this, the
#: line said ``GATES_ENFORCE_CLAIM`` with no tier read at all, so a tier-1
#: project - ``/keel:lay``'s own default - had its first sentence claim
#: enforcement its second sentence, two lines down, already denied
#: (BL51). This names what IS true of those tiers instead of falling silent:
#: the plan file is still the right place to write, the gates simply are not
#: the reason to write there yet.
#:
#: THE WORD "log" MUST NOT APPEAR IN THIS SENTENCE, and neither must any other
#: claim that a write is watched or recorded. Below the enforcing tier
#: ``keel_gate.run`` returns ``allow(f"tier {tier} is below the enforcing
#: tier ...")`` (``keel_gate.py``, the ``tier < ENFORCING_TIER`` branch), and
#: the audit line is written under ``if verdict.blocking`` at the END of that
#: same function - ``KeelVerdict.blocking`` is ``decision != "allow"``, so an
#: allow NEVER reaches ``_audit``. An ordinary write at tier 0/1 therefore
#: leaves no audit line at all; ``keel_capture`` records ``DELEGATION_TOOLS``
#: (``Task``/``Agent``) events, not file writes. The tier NAMES in
#: ``templates/keel-policy.md`` - "observe", "log" - are what a project
#: DECLARES, and that template calls tier 1 "enforcement-identical to tier 0":
#: its "log" is the knowledge-record habit, not a per-write trail. Telling the
#: model its writes are being logged when no code path records them is BL51's
#: defect pointed the other way, so this sentence claims neither.
#:
#: "NO RULE" IS THE EXACT WORD, not "nothing". One blocking path does survive
#: below the enforcing tier: ``keel_gate.run``'s ``_cannot_evaluate`` denies -
#: and, being blocking, DOES audit - when the gate's own preflight or
#: ``evaluate`` raises, because ``failure_policy_roots`` asks ``governance``,
#: which never reads ``policy_tier``. That is keel refusing to operate, not a
#: tier-1 rule refusing a write, and the sentence is worded so it stays true
#: through it.
GATES_NOT_ENFORCED_CLAIM = (
    "No rule here enforces that: below the enforcing tier none refuses a "
    "write against that file, and none records one either."
)


def _text(value: Any) -> str | None:
    """A non-empty string, or None. Any other type is absence, not an error."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def _screened(value: str) -> str | None:
    """One payload value, screened - or None when the screen itself failed.

    ``live_view_line`` guards its own ``redact`` call and keeps the sentence
    on a fault, because that sentence is a CONSTANT this file wrote: there is
    nothing in it to leak. A payload value is the opposite case, so the
    fallback is the opposite too - the value is DROPPED, never written
    unscreened (convention 5 is applied at the emitter, and a screen that
    could not run is not a screen that passed).

    Absence, not invention: the caller records the honest "nothing here" -
    ``null`` for the seat, an omitted key for the rest - and the fault is one
    line on stderr, never silence (convention 7).

    Why this containment exists at all: ``start_record`` runs at the TOP of
    ``run``, before a single context line is printed. An exception escaping
    here would reach ``run``'s catch-all and cost the session its plan-path
    line, its orientation block, its live-view line and its knowledge index -
    the whole injection - over one field of one audit line. Losing one part
    of the context may never cost the session another part of it.
    """
    try:
        return redact(value)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: session field not screened, so not recorded: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def ledger_hint(root: Path, cwd: Path, sess8: str) -> str | None:
    """The ledger path spelled from where the SESSION stands, or None.

    T602, AND IT IS THE PRECONDITION FOR SWEEPING ``run``. The path in the
    injected line is PROJECT-relative, which was T515's stated reason for
    leaving ``run`` filing at ``event.cwd``: a session standing in a
    subdirectory would read ``.keel/plans/keel-plan-x.md`` against ITS OWN
    directory and create a stray ``.keel/`` there - a ledger the gate, which
    resolves the ledger at the governing root, would never see. Spelling it
    absolutely is not the alternative: this line goes through ``redact``, so on
    a machine whose projects live under the home directory an absolute path
    reaches the model as ``[home-path]/...`` and instructs it to write nowhere.

    THE THIRD ANSWER IS A RELATIVE PATH FROM THE SESSION'S OWN DIRECTORY -
    ``../.keel/plans/...`` - which names the right file, carries no home shape,
    and therefore survives the screen intact. When the session already stands
    at the root, ``relpath`` is ``.`` and this returns BYTE-FOR-BYTE what
    ``session_plan_relpath`` has always returned, so the ordinary session's
    injected line is unchanged.

    BOTH SIDES ARE RESOLVED BEFORE THEY ARE COMPARED, and this is not a
    tidiness point - the first cut of this function did not, and the fixture
    below caught it emitting eight ``../`` steps followed by the ACCOUNT NAME
    and a full absolute descent - ``../../../../../../../../<account>/AppData/
    Local/Temp/.../.keel/plans/...`` - into a session's context, which is both
    a wrong path and a name past the screen. The walk hands back a CANONICAL
    root while the
    harness supplies the 8.3 SHORT form of the cwd, so ``relpath`` of the two
    climbs out of one spelling and back down the other: a path that is wrong,
    enormous, and carries the account name past a screen that was looking for
    a home-SHAPED string.

    AND THE RESULT IS CHECKED, not trusted (fail-closed). ``root`` is an
    ancestor of ``cwd`` by construction, so the prefix must be a pure chain of
    ``..`` - anything else means the premise did not hold and the answer is
    None. That check is what makes the emitted line safe by CONSTRUCTION
    rather than by the caller's good luck.

    None means the two paths do not relate (separate drives on Windows, an
    unresolvable spelling, a prefix that is not a pure ascent). The caller
    withholds the line rather than emitting a path it cannot vouch for -
    convention 7: a hint keel cannot compute is said to be absent, never
    guessed.
    """
    relpath = session_plan_relpath(sess8)
    try:
        prefix = os.path.relpath(
            os.path.realpath(str(root)), os.path.realpath(str(cwd))
        )
    except (OSError, ValueError):
        return None
    if prefix in ("", "."):
        return relpath
    steps = prefix.replace("\\", "/").split("/")
    if any(step != ".." for step in steps):
        return None
    return "/".join((*steps, relpath))


def injection_line(
    sess8: str,
    ledger: str | None = None,
    *,
    cwd: Path | None = None,
) -> str:
    """The one line SessionStart puts into the session's context.

    Redacted like everything else keel emits, although the path it carries is
    relative by construction: convention 5 is applied at the emitter, not
    argued about at each call site.

    ``ledger`` OVERRIDES THE PROJECT-RELATIVE SPELLING (T602) and defaults to
    it, so every existing caller and every existing fixture gets the line they
    got before. ``run`` passes ``ledger_hint``, which differs only for a
    session standing in a subdirectory of its project - see that function for
    why an absolute path is not the alternative.

    ``cwd`` IS THE GOVERNING PROJECT (BL51), and its EFFECTIVE tier - not the
    declaration, the same distinction BL12 drew for the lock line - decides
    which claim this line ends on. ``armed_for_reminders`` is the one predicate
    already used to ask "is this project armed at the enforcing tier": it
    resolves the governing project the same way ``override_reminder`` does and
    fails to False on anything it cannot read, so an unreadable arming file
    reports the same as an absent one - no enforcement claimed either way.
    ``run`` passes its own ``root``; a caller with no ``cwd`` (the historic
    signature, kept so every existing fixture that never asked about tiers
    still gets a line) gets the tier-0/1 wording, because "cannot tell" and
    "not enforcing" must read the same way here (R25's fail-closed answered
    for a claim rather than a write).

    KEEL_GATE IS NOT READ HERE, deliberately, matching ``_effective_lock_state``:
    that switch is reported at its own raw value on the switches line, never
    folded into a tier predicate, so this line and the lock line stay
    consistent about what "effective" means.
    """
    enforcing = cwd is not None and armed_for_reminders(cwd)
    return redact(
        f"[keel] This project runs under {POLICY_DISPLAY}. YOUR session plan "
        f"file is {ledger or session_plan_relpath(sess8)} - write your plan THERE, as "
        f"'- [ ]' tasks with acceptance criteria and routes; parallel sessions "
        f"each have their own. "
        f"{GATES_ENFORCE_CLAIM if enforcing else GATES_NOT_ENFORCED_CLAIM}"
    )


def armed_for_reminders(cwd: Path) -> bool:
    """True when the project GOVERNING this session opted into enforcement.
    NEVER raises.

    Mirrors ``keel_stop.armed_for_reminders``: the reminder is the only thing
    keel says about a lock, so it may be said only where a lock exists to be
    suspended. Adoption (``.keel/`` present) is not enough - a tier-1
    (observing) project has no policy lock yet, even though it is adopted, so
    KEEL_OVERRIDE has nothing there to suspend. Any fault reading the arming
    file is "not armed": a footnote may not fail the session it brackets.

    IT HAD STOPPED MIRRORING (T515). T186 re-pointed the stop gate's twin at the
    GOVERNING project and left this one reading ``is_armed(cwd)`` - the arming
    file in THIS EXACT DIRECTORY - so the two functions that share a docstring
    claim gave opposite answers for the same session whenever it was started in
    a subdirectory: the stop gate held it to the project's lock while
    SessionStart told it nothing about that lock existing. The walk is the same
    one, through the same ``keel_gate.resolve_project`` T186 delegates to, so a
    later change to arming resolution reaches both.
    """
    try:
        resolution = resolve_project(cwd)
    except Exception:  # noqa: BLE001 - a footnote may not fail the session hook
        return False
    if not resolution.found or resolution.root is None:
        return False
    try:
        return is_armed(resolution.root)
    except Exception:  # noqa: BLE001 - a footnote may not fail the session hook
        return False


def override_suspends_lock(cwd: Path, env: Mapping[str, str] | None = None) -> bool:
    """True exactly when this session's policy lock is suspended by the switch.

    ONE PREDICATE, ASKED BY BOTH SURFACES THAT SPEAK ABOUT THE LOCK (BL12/T375),
    for the reason ``_lock_orientation`` and ``_holds_orientation`` share one
    parse of the arming file (R15): two readers of one fact drift, and the drift
    is invisible until a session is told both halves of a contradiction. Before
    this, the reminder read ``KEEL_OVERRIDE`` here while the policy-lock line
    read only whether the arming file parsed, so one line said SUSPENDED and the
    other said "in force" about the same lock in the same session.

    BOTH CONDITIONS ARE LOAD-BEARING, and the second is why this is not simply
    ``env_on``: the switch suspends a lock only where a lock exists to suspend.
    A tier-1 project is adopted and has no policy lock, so ``KEEL_OVERRIDE`` has
    nothing there to carry - see ``armed_for_reminders``, whose fail-safe (any
    fault reading the arming file reads as "not armed") is inherited here, so an
    unreadable arming file never renders an orientation line claiming the lock
    is off.

    NEVER RAISES, like every reader the orientation lines call.
    """
    if not armed_for_reminders(cwd):
        return False
    return bool(env_on("KEEL_OVERRIDE", os.environ if env is None else env))


def override_reminder(cwd: Path, env: Mapping[str, str] | None = None) -> str:
    """The suspended-lock reminder while the override is on AND there is a
    lock for it to suspend, else nothing.

    One line, appended after the plan line, so the very first thing a session
    reads includes the fact that its guardrail is off and the sentence that
    puts it back. It never blocks and it never repeats within an event: the
    override is a temporary state, and the reminders stop the moment a
    session runs without it - or the moment the project is not armed at the
    enforcing tier to begin with.

    THE AGE CLAUSE (T169 accept 3) EXTENDS THAT ONE LINE rather than adding a
    second: "one session" stops being every session by inheritance only if the
    reminder says how long the switch has already been on, and a second line
    would be a second thing to stop reading. The value is
    ``keel_gate.override_age_note``, derived from the audit record because the
    environment cannot tell an inherited value from a fresh one; it always says
    something (dated, "none on record", or "unknown" with the reason), and it
    never refuses or expires the switch, which is the user's law. Redaction runs
    once, over the joined line, so the clause is screened by the same door the
    sentence already went through.
    """
    if not override_suspends_lock(cwd, env):
        return ""
    note = override_age_note(cwd)
    return redact(f"{OVERRIDE_REMINDER} {note}" if note else OVERRIDE_REMINDER)


def inject_cap_bytes(env: Mapping[str, str] | None = None) -> int:
    """The byte cap in force, from the environment or the default.

    An unreadable or negative value falls back to the default and says so:
    a cap that silently became "no cap" because of a typo is the defect this
    whole mechanism exists to prevent (R16).
    """
    raw = (os.environ if env is None else env).get(INJECT_CAP_ENV)
    if raw is None or not str(raw).strip():
        return DEFAULT_INJECT_CAP_BYTES
    try:
        value = int(str(raw).strip())
    except ValueError:
        value = -1
    if value < 0:
        print(
            f"keel: {INJECT_CAP_ENV}={raw!r} is not a byte count; "
            f"using {DEFAULT_INJECT_CAP_BYTES}",
            file=sys.stderr,
        )
        return DEFAULT_INJECT_CAP_BYTES
    return value


def index_block(lines: Sequence[str], cap: int) -> str:
    """The knowledge block, never wider than ``cap`` bytes of UTF-8.

    Pure: no filesystem, no environment, no clock - so the cap can be tested
    for what it is, an arithmetic guarantee. The overflow marker's own size is
    reserved BEFORE the last line is admitted, because a marker that does not
    fit is a truncation that was not announced.
    """
    if not lines:
        return ""
    header = INDEX_HEADER.format(total=len(lines))
    kept: list[str] = []
    used = len(header.encode("utf-8"))
    for position, line in enumerate(lines):
        marker = OVERFLOW_MARKER.format(more=len(lines) - position)
        reserve = len(marker.encode("utf-8")) + 1
        cost = len(line.encode("utf-8")) + 1
        if used + cost + (reserve if position < len(lines) - 1 else 0) > cap:
            break
        used += cost
        kept.append(line)
    if len(kept) == len(lines):
        return "\n".join([header, *kept])
    marker = OVERFLOW_MARKER.format(more=len(lines) - len(kept))
    if used + len(marker.encode("utf-8")) + 1 > cap:
        # Not even the header plus one marker fits: the marker still ships,
        # alone. Reporting the overflow is the part that may not be dropped.
        return marker if len(marker.encode("utf-8")) <= cap else ""
    return "\n".join([header, *kept, marker])


def knowledge_notice() -> str:
    """The line injected INSTEAD of the index when knowledge is not installed.

    Empty string when the feature is present, which is the unchanged path: the
    caller then reads the index exactly as it always did. Takes no project
    argument on purpose - whether an INSTALLATION carries a feature has
    nothing to do with which project it is looking at, and answering it from
    the project directory is how a trimmed bundle would start blaming the
    user's tree.

    NEVER raises: like every other line this hook emits, a footnote about the
    edition may not cost the session its plan line, so any fault at all is one
    stderr line and no notice - after which the index path runs and reports its
    own fault in its own words. Nothing is swallowed silently (convention 7).

    ``keel_features`` is imported HERE, inside that guarantee, and not at module
    scope: ``hooks/keel_hook.py`` imports this module to reach ``gate`` and
    ``stop``, so a defect in ``keel_features`` at import time - a syntax error,
    a truncated file - would otherwise take the whole launcher down before
    ``main`` reaches its own fail-open handler, and the gates with it. Lazy, the
    worst such a defect can cost is this one notice and one stderr line, which
    is exactly what a broken ``keel_index`` costs the index below.
    """
    try:
        from keel_features import (  # noqa: PLC0415 - lazy on purpose, see above
            decline,
            feature_absent,
        )

        if not feature_absent(KNOWLEDGE_FEATURE, component=KNOWLEDGE_COMPONENT):
            return ""
        return redact(f"[keel] {decline(KNOWLEDGE_SUBJECT, KNOWLEDGE_FEATURE)}")
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: could not consult the feature registry: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return ""


def knowledge_lines(cwd: Path) -> list[str]:
    """One ``id date type title`` line per record, newest first.

    Reads the derived index when it exists and the record files when it does
    not, so a session start never waits on a rebuild and never depends on a
    cache. Any failure at all is one stderr line and no knowledge block: the
    plan line matters more than the index, and this hook is fail-open.

    Called only where ``knowledge_notice`` found no reason to decline, so a
    missing ``keel_index`` here is an installation contradicting its own
    registry rather than a trimmed edition - reported the same fail-open way,
    since either is one line of stderr and no index.
    """
    try:
        if _SCRIPTS_DIR not in sys.path:
            sys.path.insert(0, _SCRIPTS_DIR)
        import keel_index  # noqa: PLC0415 - path must be set first

        return [hit.line() for hit in keel_index.summaries(cwd)]
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(f"keel: knowledge index unavailable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []


def _keel_survey():
    """``scripts/keel_survey.py``, imported lazily on the scripts path.

    Follows the same coupling ``knowledge_lines`` already takes for
    ``keel_index``: the scripts directory goes on ``sys.path`` and the module
    is imported inside the function that needs it, never at module scope, so
    a defect in ``scripts/keel_survey.py`` costs this one orientation block
    and not the launcher that imports THIS module to reach ``gate`` and
    ``stop``. No new dependency direction is invented - the seam already
    exists at line ~153 (``_SCRIPTS_DIR``).
    """
    if _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)
    import keel_survey  # noqa: PLC0415 - path must be set first

    return keel_survey


def _arming_orientation(cwd: Path) -> str:
    """Arming tier and ARMED/not-enforcing, or the read fault in its own words.

    Reuses ``keel_survey.arming_report`` rather than re-deriving tier and
    armed-ness here, so this line and ``keel survey`` can never disagree
    about what "armed" means (R15). NEVER raises: any fault is reported as
    its own sentence, not silence (convention 7) - and the guarantee covers
    the WHOLE computation, not just the survey call: the ``try`` below wraps
    the dict access and formatting too, because a malformed report (a
    missing key, or something that is not a dict at all) is exactly as
    fault-prone as an exception the survey call raises directly, and must
    render the same "could not be read" sentence rather than a KeyError or
    TypeError escaping past this function's promise.
    """
    try:
        report = _keel_survey().arming_report(cwd)
        tier = "unarmed" if report["tier"] is None else f"tier {report['tier']}"
        state = "ARMED" if report["armed"] else "not enforcing"
        line = f"{ORIENTATION_TAG}: arming - {tier} ({state})"
        if report["note"]:
            line += f"; NOTE {report['note']}"
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        return redact(
            f"{ORIENTATION_TAG}: arming - could not be read: {type(exc).__name__}: {exc}"
        )
    return redact(line)


def _effective_lock_state(declared: str, suspended: bool) -> str:
    """The state segment: what is in force now, and what the file declares.

    BOTH FACTS OR NEITHER (BL12/T375). Reporting only the declaration is what
    made this line contradict the switches line beside it; reporting only the
    suspension would be a second, opposite lie, because the ``tighten:``,
    ``relax:`` and ``workshop:`` values on the REST of this line describe the
    declaration and remain true while the switch is on. So the effective state
    leads - it is what governs this session's next write - and the declaration
    follows it in parentheses, as the thing that comes back the moment the
    switch is cleared.

    THE PARENTHETICAL IS NOT DECORATION: a suspension a session cannot see the
    shape of is one it cannot restore knowingly, and the four-way declared state
    (in force / INVALID / defaults / UNKNOWN) is exactly what tells a reader
    whether clearing the switch restores a lock, a default, or a fault.
    """
    if not suspended:
        return declared
    return f"{LOCK_SUSPENDED_STATE} (declared: {declared})"


def _lock_orientation(cwd: Path, env: Mapping[str, str] | None = None) -> str:
    """The '## Policy lock' section's state, or that there is none.

    Reuses ``keel_survey.lock_config_report`` for the identical reason
    ``_arming_orientation`` reuses ``arming_report``: one parser, one
    opinion about what the lock says (R15). NEVER raises - and, as in
    ``_arming_orientation``, the ``try`` wraps the dict access, the joins and
    the formatting along with the survey call, so a malformed report renders
    the same "could not be read" sentence instead of an uncaught KeyError or
    TypeError.

    THE ``workshop:`` DECLARATION IS NAMED HERE (workshop design rule 7), on
    this line rather than on a sixth orientation line of its own: it is the
    third list of the one section this line already reports, and it belongs
    beside the two lists whose meaning it modifies. It was enforced from T169 -
    each prefix turning a policy-lock deny into an audited allow - and named by
    no reader at all, so a session could not see which of its own source trees
    its model was permitted to rewrite. In a self-hosted project it is the
    loosest clause in the lock and the one carrying most of the session's
    writes, which is precisely why it is the one a session must be told about
    rather than left to infer from an audit event after the fact. The list
    itself is quoted from the project's own arming file, never from here: what
    a given project declares is the owner's to change.

    THE STATE SEGMENT REPORTS THE EFFECTIVE LOCK, NOT ONLY THE DECLARED ONE
    (BL12/T375). It used to be derived solely from whether the section parsed,
    so it read "in force" beside a switches line reading ``KEEL_OVERRIDE=on`` -
    two orientation lines answering different questions with nothing to say
    they were different questions, which is the one failure a governance tool
    may not have: a surface reporting a state that is not the case. The
    suspension comes from ``override_suspends_lock``, the SAME predicate that
    decides whether ``OVERRIDE_REMINDER`` is printed, so the banner's two
    sentences about the lock are one fact said twice and can never disagree.
    ``env`` exists for the tests, which must be able to render both worlds
    without depending on the environment the suite happens to run in - a
    session holding the override would otherwise flip these lines under a test
    that only reads them (the read-side leak of BL1's class).
    """
    try:
        report = _keel_survey().lock_config_report(cwd)
        # THE WORKSHOP SEGMENT IS BUILT BEFORE THE PRESENCE BRANCH, so that
        # every state one can hold is reachable on this line. It first sat
        # inside the ``else`` below, where ``UNKNOWN`` could never be reached at
        # all: the only producer of that state is the survey's ``GateError``
        # path, which pairs it with ``present`` FALSE, so an unreadable arming
        # file rendered the identical sentence a project declaring nothing gets.
        # A state machine nested inside a condition that excludes one of its
        # states is the defect; see the same note in ``keel_survey.render``.
        #
        # The five state names are spelled as LITERALS for the reason
        # ``_holds_orientation`` spells its four that way: this hook reaches
        # the survey LAZILY on purpose, and a module-level import of
        # ``keel_gate`` would trade that property for a constant. They are
        # pinned against ``keel_gate.WORKSHOP_*`` by a test, so a rename
        # fails the suite instead of silently falling through to UNKNOWN.
        shop_state = report["workshop_state"]
        if shop_state == "active":
            workshop = ", ".join(report["workshop"])
        elif shop_state == "none":
            workshop = "(none)"
        elif shop_state == "refused":
            # Never "(none)": an entry keel threw away is not one nobody
            # wrote, and until now the refusal was said only on stderr at
            # gate-event time - long after orientation.
            workshop = (
                f"(none in force, {len(report['workshop_refusals'])} REFUSED - "
                f"run: python scripts/keel.py survey)"
            )
        elif shop_state == "invalid":
            workshop = "(none in force, the section is INVALID)"
        else:
            workshop = "(UNKNOWN, the arming file cannot be read)"
        # THE SWITCH IS READ ONCE, HERE, and only ever wraps the state segment
        # below: a suspension changes what governs this session, never what the
        # arming file declares, so nothing downstream of this line is touched by
        # it (BL12/T375).
        suspended = override_suspends_lock(cwd, env)
        if not report["present"]:
            if shop_state == "unknown":
                # NOT "defaults": keel never read this file, so "there is no
                # section" is a claim it has not earned. ``present`` is FALSE
                # for both worlds - no section, and no readable file - and the
                # workshop state is what lets this line tell them apart.
                declared = "UNKNOWN, the arming file cannot be read"
            else:
                # No section, no workshop: the ``workshop:`` list lives inside
                # it, so "(none)" is a statement rather than a silence.
                declared = "defaults (no '## Policy lock' section)"
            line = (
                f"{ORIENTATION_TAG}: policy lock - "
                f"{_effective_lock_state(declared, suspended)}; workshop: {workshop}"
            )
        else:
            declared = "in force" if report["valid"] else "INVALID (full default lock applies)"
            tighten = ", ".join(report["tightened"]) or "(none)"
            relax = ", ".join(report["relaxed"]) or "(none)"
            line = (
                f"{ORIENTATION_TAG}: policy lock - "
                f"{_effective_lock_state(declared, suspended)}; "
                f"tighten: {tighten}; relax: {relax}; workshop: {workshop}"
            )
        if report["note"]:
            line += f"; NOTE {report['note']}"
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        return redact(
            f"{ORIENTATION_TAG}: policy lock - could not be read: "
            f"{type(exc).__name__}: {exc}"
        )
    return redact(line)


#: How many holds the castoff line names before it stops listing and counts.
#: The COUNT is always exact; the listing is what is bounded, because these
#: lines are injected into every session's context under a byte cap (R16) and a
#: user may write a dozen holds. The survey prints all of them.
HOLDS_SHOWN = 3


def _holds_orientation(cwd: Path) -> str:
    """The user's standing constraints, or the fact that there are none.

    Reuses ``keel_survey.lock_config_report`` - the SAME reader
    ``_lock_orientation`` uses, over the same parse of the same file - so the
    two lines can never disagree about one arming file (R15). The four-way
    state is taken from the report as the gate derived it and is never
    recomputed here: this function chooses wording, nothing else.

    WHY THIS LINE EXISTS AT ALL: ``## Holds`` shipped as prose no instrument
    read. A hold the user believes is binding and that no session is ever told
    about is wrong-while-green - the failure is invisible until something the
    user forbade has already happened. NEVER raises, like every other
    orientation helper, and the ``try`` wraps the dict access and the joins as
    well as the survey call.
    """
    try:
        report = _keel_survey().lock_config_report(cwd)
        # The four state names are spelled as LITERALS, not imported from
        # ``keel_gate``, because this hook reaches the survey lazily on purpose
        # (a defect down there must cost one orientation line, never the whole
        # block - see ``_keel_survey``). A module-level import would trade that
        # property away for a constant. The literals are pinned against
        # ``keel_gate.HOLDS_*`` by a test instead, so a rename fails the suite
        # rather than silently falling through to the UNKNOWN branch.
        state = report["holds_state"]
        if state == "active":
            holds = list(report["holds"])
            shown = "; ".join(holds[:HOLDS_SHOWN])
            more = len(holds) - HOLDS_SHOWN
            tail = f" (+{more} more, run: python scripts/keel.py survey)" if more > 0 else ""
            line = (
                f"{ORIENTATION_TAG}: holds - {len(holds)} ACTIVE, honour them: "
                f"{shown}{tail}"
            )
        elif state == "none":
            line = f"{ORIENTATION_TAG}: holds - none active (explicitly declared)"
        elif state == "absent":
            line = f"{ORIENTATION_TAG}: holds - no '## Holds' section (nothing declared)"
        else:
            # UNREADABLE, and said as such. "none" is the one thing this must
            # never render: a hold keel could not read is a hold that is
            # still in force for the user who wrote it.
            errors = "; ".join(report["hold_errors"]) or "reason unavailable"
            line = (
                f"{ORIENTATION_TAG}: holds - UNKNOWN, the section cannot be read "
                f"(this is NOT 'none'): {errors}"
            )
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        return redact(
            f"{ORIENTATION_TAG}: holds - could not be read: "
            f"{type(exc).__name__}: {exc}"
        )
    return redact(line)


def _conflict_orientation(cwd: Path, home: Path | None = None) -> str:
    """How many conflicts the scan found, or that it could not run.

    The scan is RE-RUN here, at every session start, and that is the point of
    the line: the conflict set is derived from the PreToolUse and Stop
    registrations visible right now (``keel_survey.conflict_scan``), so a
    foreign gate stack that appeared AFTER this project was armed - a
    registration added to a settings file, or the other stack's arming file
    written into the tree an hour later - is found on the next session start
    instead of never. Arming-time refusal alone can only ever catch one of the
    two orders in which two stacks come to overlap.

    A failed scan is reported as a SENTENCE, never as the digit 0: collapsing
    "the scan could not run" into "0 conflicts" is exactly the swallowed-
    error shape ``a-swallowed-error-renders-as-a-fact`` records, and this is
    the one fact on this line a reader would otherwise act on with false
    confidence. A clean scan that genuinely finds nothing still says "0" -
    that is a true negative, not a swallowed failure, and the two must read
    as different sentences. A scan that ran but could not read one of its
    sources is a THIRD fact, and it qualifies EVERY count rather than only the
    zero: a settings file keel could not parse is the very place a foreign gate
    would hide, so "3 found" from a partial scan is a floor exactly as "0
    found" is, and both say so in the same breath as the number.

    ``home`` is the seam the scan's own scope needs: registrations live in the
    user's home as well as in the project, so a caller that must own that
    premise - a test with a fixture home - hands one down, exactly as
    ``keel_survey.survey`` already takes one. Production passes nothing and
    reads the real home.

    The ``try`` wraps the shape check and ``len()`` along with the survey
    call itself (mirroring ``_arming_orientation`` and ``_lock_orientation``),
    and the shape check is explicit rather than implicit: ``len()`` alone
    type-checks nothing, so a sized-but-wrong return (a string, say, which
    ``len()`` happily accepts) would otherwise render as a plausible-looking
    "N CONFLICT(S) found" built from the wrong kind of length - precisely the
    swallowed-error-as-a-fact shape this function exists to prevent,
    reproduced inside its own guard. Only a genuine ``list`` is trusted to
    report a count; anything else is a fault, not a number.
    """
    try:
        survey = _keel_survey()
        conflicts = survey.conflicts_for(cwd, home)
        if not isinstance(conflicts, list):
            raise TypeError(
                f"conflicts_for returned {type(conflicts).__name__}, not a list"
            )
        count = len(conflicts)
        notes = survey.conflict_scan_notes(cwd, home)
        if not isinstance(notes, list):
            raise TypeError(
                f"conflict_scan_notes returned {type(notes).__name__}, not a list"
            )
    except Exception as exc:  # noqa: BLE001 - fail-open, and never a false zero
        return redact(
            f"{ORIENTATION_TAG}: conflicts - scan could not run: "
            f"{type(exc).__name__}: {exc}"
        )
    # The floor qualifier attaches to the NUMBER, whichever number it is. A
    # count of 3 from a scan that could not read one of its sources is no more
    # a total than a count of 0 is: "N found" would be read as "N exist", and
    # the reader would act on it - stop looking, or migrate exactly N entries.
    # One sentence, both branches, same breath as the figure it qualifies.
    floor = (
        f", and the scan was INCOMPLETE ({len(notes)} source(s) unread), so "
        f"that is a FLOOR rather than a total"
        if notes
        else ""
    )
    if count:
        return redact(
            f"{ORIENTATION_TAG}: conflicts - {count} CONFLICT(S) found{floor}, "
            f"run: python scripts/keel.py survey"
        )
    if floor:
        return redact(
            f"{ORIENTATION_TAG}: conflicts - 0 found{floor}, run: "
            f"python scripts/keel.py survey"
        )
    return redact(f"{ORIENTATION_TAG}: conflicts - 0 found")


def _switches_orientation(env: Mapping[str, str] | None = None) -> str:
    """The three kill switches' raw values, or the read fault in its own words.

    Reuses ``keel_survey.switches_report`` - the very values ``keel survey``'s
    own ``switches:`` line renders - and that line's own formatting
    expression (``name=value or '(unset)'``) verbatim, so this line and that
    one can never disagree about what a switch's value is (R15). Unlike the
    other four orientation helpers this one takes no ``cwd``: a kill switch
    is an environment fact, not a project one.

    ``env`` resolves the same ambiguity ``override_reminder`` resolves at
    ``:251`` (``os.environ if env is None else env``) - a caller may hand
    down a specific mapping (tests do; production never does, so ``run``'s
    own ``env`` parameter reaches here exactly as it reaches
    ``override_reminder``). This is a DELIBERATE choice against the
    alternative already living in this file: ``inject_cap_bytes`` reads
    ``os.environ`` unconditionally and ignores whatever ``env`` its caller
    was given, which is a landmine for a test that sets a switch in ``env``
    and expects this line - or the cap - to see it. Threading ``env``
    through here keeps the switches line on the same, testable side of that
    split as ``override_reminder``, not on ``inject_cap_bytes``'s side.

    NEVER raises. The property worth stating plainly, because it is the one
    this function exists to keep true: an UNREADABLE switch state may never
    print as "(unset)". Those are different facts - "keel could not tell"
    and "keel asked and it is off" - and a reader deciding whether a gate is
    actually live would act on them differently (see
    ``a-swallowed-error-renders-as-a-fact``). So the shape check below is
    strict: every name in ``keel_survey.KILL_SWITCHES`` must come back as a
    key, or the whole line renders as a fault sentence rather than quietly
    reporting whichever switches happened to survive a malformed return (a
    plain ``.get()`` default would silently turn "missing key" into
    "(unset)") and omitting the rest - the same "malformed shape, not a
    raised exception" class T1's retry found in the other three helpers.
    """
    try:
        survey = _keel_survey()
        switches = survey.switches_report(env)
        if not isinstance(switches, dict):
            raise TypeError(
                f"switches_report returned {type(switches).__name__}, not a dict"
            )
        missing = [name for name in survey.KILL_SWITCHES if name not in switches]
        if missing:
            raise KeyError(f"switches_report is missing {missing!r}")
        rendered = " ".join(
            f"{name}={switches[name] or '(unset)'}" for name in survey.KILL_SWITCHES
        )
        line = f"{ORIENTATION_TAG}: switches - {rendered}"
    except Exception as exc:  # noqa: BLE001 - fail-open, and never a false "(unset)"
        return redact(
            f"{ORIENTATION_TAG}: switches - could not be read: {type(exc).__name__}: {exc}"
        )
    return redact(line)


def orientation_lines(
    cwd: Path, env: Mapping[str, str] | None = None, home: Path | None = None
) -> list[str]:
    """The five lines ``/keel:castoff`` step 2 reads instead of a command:
    arming, policy lock, conflicts, the three kill switches, and the user's
    standing holds - each computed and reported independently, so a fault in
    one never blanks the others, and each is redacted like every other line
    this hook emits (convention 5).

    HOLDS COME LAST, and the position is a choice rather than an accident. The
    block's existing four positions stay where every reader (and several tests)
    already index them, and a standing constraint is the last thing a session
    reads before it starts working - the closest an injected line gets to being
    unmissable.

    The independence is enforced HERE, not merely assumed from each helper's
    own ``try``: each of the five calls below sits inside its OWN
    ``except``, so even if a helper's internal guarantee were ever defeated -
    a bug in a future edit, a ``redact`` call that itself raises - the escape
    costs only that one line, never the other four, and never propagates to
    ``run``'s catch-all, which would divert the failure sentence to stderr
    (this file's own contract says stdout is what becomes session context,
    ``:27``) and would also abort ``run`` before the knowledge index block
    beneath the orientation lines gets a chance to print. Every fallback
    sentence built here lands in the same returned list the successful lines
    do, so it reaches the SAME channel (``run`` prints every line in this
    list to the same stream) rather than a different one.

    ``env`` is threaded through to ``_switches_orientation`` AND to
    ``_lock_orientation`` - the other three helpers read only ``cwd`` - exactly
    as ``run`` threads its own ``env`` parameter to ``override_reminder`` and
    nowhere else but there and here. The lock line took it at BL12/T375, when
    its state segment stopped reporting the declaration alone: the switch that
    suspends the lock and the switch the switches line names must be READ FROM
    THE SAME MAPPING, or a caller owning its own environment would be told two
    different things about one session by two adjacent lines - which is the
    defect that item exists to close. ``home`` is threaded through to ``_conflict_orientation``
    alone, for the same reason and on the same terms: the conflict scan reads
    registrations out of the user's home as well as the project's own tree, so
    a caller that must own that premise can name it, and production names
    nothing and reads the real home.
    """
    lines: list[str] = []
    for label, compute in (
        ("arming", lambda: _arming_orientation(cwd)),
        ("policy lock", lambda: _lock_orientation(cwd, env)),
        ("conflicts", lambda: _conflict_orientation(cwd, home)),
        ("switches", lambda: _switches_orientation(env)),
        ("holds", lambda: _holds_orientation(cwd)),
    ):
        try:
            lines.append(compute())
        except Exception as exc:  # noqa: BLE001 - belt-and-braces: one line, not five
            lines.append(
                redact(
                    f"{ORIENTATION_TAG}: {label} - could not be computed: "
                    f"{type(exc).__name__}: {exc}"
                )
            )
    return lines


def orientation_bytes(lines: Sequence[str]) -> int:
    """UTF-8 bytes ``orientation_lines`` spends, INCLUDING the newline that
    separates it from whatever prints next.

    What is actually guaranteed, stated plainly rather than overstated: this
    number is what ``run`` SUBTRACTS from ``inject_cap_bytes`` before handing
    the remainder to the knowledge index (R16, R32) - twice now, once for the
    orientation block and once for the single live-view line, which is
    measured by this same function rather than by a second byte counter that
    could come to disagree with it - so the INDEX never
    silently grows the total past the cap - its floor is zero, never
    negative, and an oversized orientation block simply leaves it nothing.
    That is the invariant this function actually enforces.

    Orientation itself is deliberately NOT clamped against the cap, so a cap
    set below what orientation alone costs can still push the total over it.
    That choice was made, not overlooked: the five orientation lines are the
    facts ``/keel:castoff`` cannot orient without (arming, policy lock,
    conflicts, switches, holds), each one already a single short, atomic sentence
    with no record boundary to truncate at the way the index's per-record
    lines have one (see ``index_block``'s overflow marker). Cutting one to
    fit a byte count would hide exactly the safety fact a reader depends on -
    a worse failure than a session that runs slightly wide under a cap
    configured well below the ~360 bytes these five lines cost in practice
    (see ``test_the_orientation_block_costs_a_small_fraction_of_the_injection_cap``).
    And the failure mode is never silence either way: unlike a dropped index
    record, an over-cap orientation block still prints in full, so the
    reader sees the very lines that explain why the total ran wide, rather
    than a gap with nothing said about it.
    """
    return sum(len(line.encode("utf-8")) + 1 for line in lines)


def live_view_line() -> str:
    """The one line naming the orchestration viewer. NEVER raises.

    A constant sentence: no port is derived, no path is hashed, no file is
    read (R19 - see "The live-view line" in the module contract). The
    ``--dir .`` in the command is what makes it copy-pasteable from the
    session it was injected into without naming anybody's home directory.

    The caveat is load-bearing rather than decorative. The server binds 8770
    by default and walks to the next free port when it is busy, so this URL
    is where to look FIRST, not a promise about the port in use; the running
    server prints the address it actually bound, and that is the authority
    this line points at instead of pretending to compute it.

    ``redact`` cannot change this string - it holds no home path and no
    registered name - and is applied anyway, because every line this hook
    emits goes through the same screen at the emitter (convention 5) and an
    exception in the screen must not cost the session the sentence. A fault
    there is one stderr line and the unredacted constant, which is the same
    text: fail-open, and never silent (convention 7).
    """
    line = (
        f"{LIVE_VIEW_TAG} - {LIVE_VIEW_URL} shows this session's delegations "
        f"live (fixed port, never derived; the server walks to the next port "
        f"when 8770 is busy, so trust the URL it prints). Not running? Start "
        f"it with: {LIVE_VIEW_COMMAND}"
    )
    try:
        return redact(line)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: live-view line not redacted: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return line


def transcript_tail_lines(path: Path, limit: int = TRANSCRIPT_TAIL_BYTES) -> list[str]:
    """The last ``limit`` bytes of a transcript, as whole lines, oldest first.

    ONE SEEK, NEVER A SCAN. The file is opened in binary, seeked to
    ``size - limit``, and read to the end: a 40 MB transcript costs exactly the
    same as a 40 KB one. This is the property that makes reading somebody
    else's file acceptable inside a session-start hook at all, so it is
    expressed as a seek rather than as a read-and-discard that would have the
    same result and none of the guarantee.

    THE FIRST LINE IS DROPPED whenever the read began past byte zero, because a
    cut at an arbitrary offset lands in the middle of one - and half a JSON
    object is not a line, it is a parse error waiting for a caller who trusted
    the list. Where the whole file fitted inside the bound nothing is dropped.

    Decoded with ``errors="replace"``: the same arbitrary cut can also land
    mid-character, and a ``UnicodeDecodeError`` from a best-effort read of a
    foreign file would be an exception raised over a byte nobody needed. The
    replacement character can only ever appear in the dropped first line or in
    a value, and a value that came back mangled fails ``_text`` or ``json``
    like any other malformed input.

    Raises whatever the filesystem raises - an absent file, a directory, a
    permission error. The guarantee lives in ``model_from_transcript``, which
    is the only caller and which turns every one of those into an honest null;
    keeping this function honest about its own failures is what lets that one
    report them in a single place instead of guessing at them.
    """
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        start = max(0, size - max(limit, 0))
        handle.seek(start)
        blob = handle.read()
    lines = blob.decode("utf-8", errors="replace").splitlines()
    if start > 0 and lines:
        return lines[1:]
    return lines


def _is_assistant_line(entry: Mapping[str, Any], message: Mapping[str, Any]) -> bool:
    """True when this transcript line marks itself as the ASSISTANT's own.

    EITHER marker satisfies it - the entry's ``type`` or the message's ``role`` -
    and the asymmetry is deliberate in both directions:

    * requiring the mark AT ALL is what keeps a stray ``model`` on somebody
      else's line from being recorded as the seat. A user, system or synthetic
      line that happens to carry that key is not evidence of who is answering,
      and recording it would be a wrong-but-green value where this function
      promises an honest null.
    * accepting EITHER spelling is what keeps the fallback alive if the harness
      renames or drops one of them. Measured, not assumed: every model-carrying
      line in four real transcripts on this machine (1106 of them) sets both,
      and no non-assistant line carries a model at all.

    A line with NEITHER marker is refused even when it names a model, which is
    the safe direction: the seat stays null rather than being filled from a line
    keel cannot attribute.
    """
    if _text(entry.get(TRANSCRIPT_TYPE_KEY)) == TRANSCRIPT_ASSISTANT:
        return True
    return _text(message.get(TRANSCRIPT_ROLE_KEY)) == TRANSCRIPT_ASSISTANT


def _is_placeholder_model(name: str) -> bool:
    """True when ``name`` has the SHAPE of a harness placeholder, not a model id.

    MEASURED 2026-09-04 (T482/BL39): the harness writes a literal marker into
    ``message.model`` on an assistant line it authored itself - an API
    spend-limit error, "No response requested." - rather than a model that
    produced the line, and does not mark either kind ``isSidechain``. The
    test here is the SHAPE that marker takes, not the one spelling measured
    (``PLACEHOLDER_MODEL_EXAMPLE``, ``<synthetic>``): a value wrapped in angle
    brackets, because no real model id is ever spelled that way, and the
    harness's exact placeholder text is not a guarantee - see
    ``model_from_transcript``.

    STRIPPED BEFORE THE SHAPE TEST, and only in this local copy: ``name``
    arrives here exactly as ``_text`` returned it, and ``_text`` normalises
    only its OWN truthiness test (``value.strip()``) while returning the
    ORIGINAL, unstripped value - so a placeholder padded with whitespace,
    ``" <synthetic> "``, would reach this function unchanged and then defeat a
    test anchored at the string's own ends, no longer starting with ``<`` or
    ending with ``>`` once the padding is counted. Stripping here closes that
    gap without reaching back into ``_text``: what ``model_from_transcript``
    and ``_screened`` go on to return for a legitimately padded REAL model is
    untouched, because this function only answers whether the SHAPE is a
    placeholder, never what string is recorded.
    """
    stripped = name.strip()
    return stripped.startswith(PLACEHOLDER_MODEL_OPEN) and stripped.endswith(
        PLACEHOLDER_MODEL_CLOSE
    )


def model_from_transcript(
    raw: Mapping[str, Any], limit: int = TRANSCRIPT_TAIL_BYTES
) -> str | None:
    """The model on the newest assistant line of THIS session's transcript, or
    None. NEVER RAISES - see "The transcript fallback" in the module contract.

    NEWEST WINS, and it is read from the END: the lines are walked in reverse
    so the first ``message.model`` found is the most recent one, which is the
    model actually answering in the seat now rather than whichever one opened
    the session. A resumed or re-pointed session therefore records what it is,
    not what it was.

    EVERY failure is the same answer - None - and the list of them is the point
    rather than an afterthought: no ``transcript_path`` in the payload, a path
    that is blank or not a string, a file that does not exist, a directory, a
    permission error, an empty file, a tail whose every line is malformed, a
    line whose ``message`` is not a mapping, a line that names a model without
    marking itself as the ASSISTANT's (``_is_assistant_line``), a model that is
    not a non-empty string, a model that is a PLACEHOLDER rather than an id
    (see below), or a ``redact`` that raises on the name. None of them is an
    error here: this is a fallback for a field the harness was already allowed
    to leave silent, so its own silence has to be an ordinary outcome.

    A MALFORMED LINE IS SKIPPED, NOT FATAL. ``json.loads`` runs per line inside
    its own guard, so one truncated or non-JSON line - which a bounded tail
    read makes ordinary rather than exceptional - does not stop the walk from
    reaching a good line older than it.

    A SYNTHETIC LINE IS SKIPPED THE SAME WAY (T482/BL39), and the walk
    CONTINUES to the assistant line before it rather than stopping there. The
    harness writes a literal placeholder into ``message.model`` on an
    assistant line it generated itself - an API spend-limit error, "No
    response requested." - not a model that produced it, and MEASURED
    2026-09-04, none of those lines was marked ``isSidechain``, so that marker
    could not be used to tell them apart instead. ``_is_placeholder_model``
    tests the SHAPE the harness uses for that - a value wrapped in angle
    brackets, spelled ``<synthetic>`` in what was measured - because a
    harness's exact placeholder spelling is measured, not guaranteed, and
    hard-coding one string would miss the next one. A placeholder is treated
    exactly like a line naming no model at all: if every assistant line in the
    tail is one, this function returns None, never the placeholder - a value
    that is not an answer is not recorded, the same rule every other entry in
    the failure list above already embodies.

    The name goes through ``_screened`` like every other payload-derived value
    (convention 5, applied at the emitter): a name that cannot be screened is
    dropped, never recorded raw. The path itself is never printed, never
    interpolated into a command, and never used for anything but this read
    (R5).
    """
    path_text = _text(raw.get(TRANSCRIPT_FIELD))
    if path_text is None:
        return None
    try:
        lines = transcript_tail_lines(Path(path_text), limit)
    except Exception as exc:  # noqa: BLE001 - a best-effort read, but never silent
        print(
            f"keel: session transcript not read for the seat: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:  # noqa: BLE001 - a partial tail line is ordinary here
            continue
        if not isinstance(entry, Mapping):
            continue
        message = entry.get(TRANSCRIPT_MESSAGE_KEY)
        if not isinstance(message, Mapping):
            continue
        if not _is_assistant_line(entry, message):
            continue
        name = _text(message.get(MODEL_FIELD))
        if name is None:
            continue
        if _is_placeholder_model(name):
            continue
        return _screened(name)
    return None


def model_of(raw: Mapping[str, Any]) -> str | None:
    """The model named by a SessionStart payload, or None when it names none.

    THE ONE AUTHORITY ON THIS FIELD, over two sources in a fixed order: the
    payload's own ``model`` first, and only where that names nothing, the
    session's transcript through ``model_from_transcript``. ``start_record``
    calls this and nothing else, so there is one place where the seat is
    decided and one order in which it is decided (R15).

    None is a FACT here, not a failure: measurement says the harness supplies
    ``model`` on a minority of session starts (11 of 129 in this project's own
    log, none since 2026-08-03), and the caller writes that None to the record
    as an explicit ``null`` so the two cases stay legible - "nobody could name
    the seat" and "keel never looked" are different, and a missing key cannot
    tell them apart.

    A string is taken as the name. A MAPPING is read for ``id``, then
    ``display_name``, then ``name`` - the defensive branch described in the
    module contract, so a future object-shaped payload records what it sent
    instead of reading as absence. Anything else is absence, exactly as
    ``_text`` treats it everywhere else in this file.

    THE FALLBACK IS REACHED ON ABSENCE, NOT ON FAILURE, and the difference is
    load-bearing. It runs where the payload NAMED nothing keel could read. It
    does NOT run where the payload named something that failed the screen:
    ``_screened`` returning None is a screening fault, and answering it from a
    different source would report a name for a seat whose supplied name keel
    had just refused to write - two different facts collapsed into one string.
    That case stays an honest null, exactly as it did before this fallback
    existed, and a test pins it.

    NEVER RAISES. The screen runs through ``_screened`` and the transcript read
    through ``model_from_transcript``, whose own contract is that every failure
    is None; so a fault in ``redact``, or an unreadable transcript, yields an
    honest null seat - absence, not an unscreened name and not an invented one -
    rather than an exception that would abort ``start_record`` at the top of
    ``run`` and take the entire injected context down with it.
    """
    value = raw.get(MODEL_FIELD)
    name = _text(value)
    if name is None and isinstance(value, Mapping):
        for key in MODEL_NAME_KEYS:
            name = _text(value.get(key))
            if name is not None:
                break
    if name is not None:
        return _screened(name)
    return model_from_transcript(raw)


def live_view_autostart(cwd: Path, env: Mapping[str, str] | None = None):
    """The autostart outcome for this session. NEVER raises, by contract.

    Delegated whole to ``keel_liveview``, whose own promise is that every
    path - including the broken ones - ends in an Outcome. The import is
    local and guarded anyway: this function runs BEFORE the session's own
    audit line is written, so a module that failed to import must cost the
    live view and nothing else. An unavailable module reads as "failed",
    never as "off", because those are different facts and only one of them
    is something the user chose.
    """
    try:
        import keel_liveview  # noqa: PLC0415 - guarded, cost-contained

        return keel_liveview.ensure(cwd, env)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: live-view autostart unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def autostart_line(outcome) -> str | None:
    """The autostart sentence, screened at the emitter like every other line.

    Returns None when the option is off, which is what keeps an adopter who
    never opted in seeing exactly the page they saw before: the caller then
    prints the standing constant line instead.
    """
    if outcome is None:
        return None
    try:
        import keel_liveview  # noqa: PLC0415

        raw = keel_liveview.line(outcome, LIVE_VIEW_TAG)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: live-view line not built: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    if raw is None:
        return None
    try:
        return redact(raw)
    except Exception as exc:  # noqa: BLE001 - the screen may not cost the line
        print(
            f"keel: live-view autostart line not redacted: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return raw


def hook_fault_line(home: Path | None = None) -> str | None:
    """The DEAD-MAN LINE: one sentence when keel's own hooks have been failing
    recently, and None when they have not (T235).

    Why a session start says this at all. keel's observers fail-open by
    contract - a capture hook that cannot write is one line of stderr nobody
    keeps - so a keel that has quietly stopped recording looks exactly like a
    keel with nothing to record. The user-global hook-error log
    (``keel_faultlog``) is the count that tells them apart, and a session start
    is the one moment a reader is looking at keel's own state before trusting
    it. So the log is READ here and reported in the same channel as every
    other fact this hook injects.

    THREE STATES, THREE ANSWERS, which is why this returns ``str | None``
    rather than a bool:

    * ``absent`` - no hook has ever failed on this machine. NOTHING is said.
      Silence is the reward for a clean log, and a line saying "no errors"
      every single session start would spend injected context on nothing.
    * ``present`` and recent (within ``keel_faultlog.RECENT_DAYS``) - the
      warning, naming the log and the command that reads it. A ``present`` log
      OLDER than that is silence too: an error from last month is history, not
      news, and doctor still reports it on demand.
    * ``unreadable`` - its OWN sentence, and the reason this function does not
      collapse the states. A log keel could not read is not a log that says
      nothing happened; reporting it as health is exactly the shape
      ``.keel/knowledge/keel-a-swallowed-error-renders-as-a-fact.md`` names.

    ``home`` is the seam ``keel_faultlog`` itself offers and is threaded
    straight through, so a caller that must own the premise - a test with a
    fixture home - names one, and production names nothing and reads the real
    one.

    NEVER RAISES, on the terms this file's other emitters use. The import is
    LOCAL and guarded: a half-applied edit to ``keel_faultlog`` is exactly the
    kind of fault this line exists to report, and it must cost this sentence
    only - never the plan line, the orientation block or the index (and never
    the launcher's gates, which import this module). The screen is guarded
    separately and DROPS the line on failure rather than emitting it: the text
    carries a fault message and a log path, which are values, not a constant
    this file wrote, so an unscreenable one is withheld (convention 5 applied
    at the emitter).
    """
    try:
        import keel_faultlog  # noqa: PLC0415 - guarded, cost-contained

        report = keel_faultlog.state(home)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: hook-error log not consulted: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None
    state = report.get("state")
    if state == keel_faultlog.STATE_ABSENT:
        return None
    if state == keel_faultlog.STATE_PRESENT:
        if not report.get("recent"):
            return None
        where = report.get("path") or keel_faultlog.HOOK_ERROR_LOG_NAME
        detail = report.get("detail") or "no detail available"
        line = (
            f"{HOOK_FAULT_TAG} - KEEL'S OWN HOOKS HAVE FAILED on this machine "
            f"({detail}): the log is {where}. Run python scripts/keel.py doctor "
            f"before reading a quiet gate as a working one."
        )
    else:
        detail = report.get("detail") or "reason unavailable"
        line = (
            f"{HOOK_FAULT_TAG} - keel's hook-error log could NOT be read, which "
            f"is not the same as no errors: {detail}"
        )
    try:
        return redact(line)
    except Exception as exc:  # noqa: BLE001 - the screen may never be bypassed
        print(
            f"keel: hook-error warning not screened, so not shown: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None


def compaction_recovery_lines(
    event: KeelEvent, home: Path | None = None, project: Path | None = None
) -> list[str]:
    """The post-compaction recovery block, and NOTHING on any other start (T228).

    ``project`` IS WHERE THE PROMPT LOG IS READ FROM (T602) and defaults to
    ``event.cwd``, which is what every caller before ``run`` passed and still
    gets. It exists because the WRITER moved: ``keel_hook.cmd_prompt`` now
    resolves the project by walking up, so a subdirectory session's prompts are
    preserved at the ROOT, and a reader still keyed on ``event.cwd`` would find
    an empty directory and rebuild the session from nothing on the one start
    where nothing is exactly what it must not do.

    ZERO ADDED BYTES ON A NORMAL START, and that is the property this function
    exists to keep rather than a happy consequence of it. The first thing it
    asks is ``keel_compaction.is_compact_start``, which reads the payload's own
    ``source`` field; every other value - ``startup``, ``resume``, ``clear``,
    ``fork``, a source the harness has not invented yet, or none at all -
    returns the empty list here, before the module that would build a block is
    even imported. An empty list prints nothing and costs nothing against the
    injection cap, and a fixture asserts a non-compact start emits byte-for-byte
    what it emitted before this mechanism existed.

    WHY A COMPACTED SESSION NEEDS THIS AT ALL: compaction throws away the early
    turns first, which is where the user's own instructions live, and it leaves
    the model with a summary it cannot check. The block says where the lossless
    transcript is, tells the model to read it rather than reconstruct from the
    summary, and re-supplies the last few prompts verbatim from keel's own
    per-session log. Every line of it was screened when it was RECORDED and is
    screened again here at the emitter (convention 5, applied twice because
    ``redact`` is idempotent and the emitter may not assume its source).

    ``keel_compaction`` is imported LOCALLY and guarded, on exactly the terms
    ``hook_fault_line`` and ``registry_write`` use: this module is imported by
    the launcher to reach ``gate`` and ``stop``, so a half-applied edit to the
    compaction module must cost this one block and never the session's gates.

    NEVER RAISES; any fault is one stderr line and no block, because losing the
    recovery lines may not also cost the session its plan line.
    """
    try:
        import keel_compaction  # noqa: PLC0415 - guarded, cost-contained

        if not keel_compaction.is_compact_start(event.raw):
            return []
        lines = keel_compaction.recovery_lines(
            event.session_id, event.cwd if project is None else project, home
        )
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: compaction recovery unavailable: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return []
    screened: list[str] = []
    for line in lines:
        try:
            screened.append(redact(line))
        except Exception as exc:  # noqa: BLE001 - the screen may never be bypassed
            # DROPPED, not emitted raw: these lines carry a transcript path and
            # the user's own words, so an unscreenable one is withheld while the
            # rest of the block still ships.
            print(
                f"keel: a compaction recovery line was not screened, so not "
                f"shown: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
    return screened


def registry_write(cwd: Path, home: Path | None = None) -> None:
    """Feed this project's path into keel's user-global fleet registry (T227).

    Delegated whole to ``keel_registry``, on the SAME lazy-import terms as
    ``hook_fault_line`` and ``live_view_autostart`` above: the import sits
    inside this function's own guarded ``try``, so a half-applied edit to
    ``keel_registry`` costs this one registration and nothing else - never the
    plan line, the orientation block, the live view, or the gates the
    launcher reaches through THIS module. ``keel_registry.write`` re-applies
    the adoption test itself before touching its file, so this call stays
    correct even if a future caller reaches it directly; it is placed only
    where ``run`` has already confirmed adoption so an unadopted project's
    session never pays even the cost of this one import.

    NEVER RAISES: a registry that could not be updated is one stderr line
    from ``keel_registry`` itself (its own fail-open contract, which is also
    where the pruning count is reported), never an exception reaching ``run``.
    """
    try:
        import keel_registry  # noqa: PLC0415 - guarded, cost-contained

        keel_registry.write(cwd, home=home)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: fleet registry not updated: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


def start_record(event: KeelEvent, live_view=None) -> dict[str, Any]:
    """The ``session_start`` audit line - which session, and whose seat.

    ``model`` is written on EVERY line, null included; every other field is
    written only when the payload carried it. The asymmetry is the point: the
    model in the seat is the fact this record exists to hold, so its absence
    has to be recorded as an absence rather than left to be inferred from a
    key that is not there (see the module contract's measurement note).

    Every value goes through ``_screened``, which is where this function's
    own never-raises guarantee comes from: it runs before ``run`` has printed
    anything, so a screening fault must cost the field it screens and nothing
    else - never the session's whole injected context.
    """
    record: dict[str, Any] = {"event": "session_start", "session": event.session_id}
    for field in START_FIELDS:
        value = _text(event.raw.get(field))
        if value is not None:
            screened = _screened(value)
            if screened is not None:
                record[field] = screened
    # After the loop, and deliberately: for a plain string payload this writes
    # the same value the loop just did, and for every other shape - absent,
    # blank, an object, a number - it writes the honest answer the loop had no
    # way to express. One authority for this field, not two.
    record[MODEL_FIELD] = model_of(event.raw)
    # T144: what the live view did at this session's start, when anything did.
    # Additive and optional - a caller that passes nothing writes exactly the
    # line this function has always written, so every existing record and
    # every existing reader is unaffected. ``off`` is written too: "the user
    # has not opted in" is a fact about this session worth being able to read
    # back, and it is the one that explains an absent board.
    if live_view is not None:
        entry: dict[str, Any] = {"action": getattr(live_view, "action", "failed")}
        port = getattr(live_view, "port", None)
        if isinstance(port, int):
            entry["port"] = port
        detail = _text(getattr(live_view, "detail", None))
        if detail is not None:
            screened = _screened(detail)
            if screened is not None:
                entry["detail"] = screened
        record["live_view"] = entry
    return record


def end_record(event: KeelEvent) -> dict[str, Any]:
    """The ``session_end`` audit line, carrying the harness's reason if any."""
    record: dict[str, Any] = {"event": "session_end", "session": event.session_id}
    reason = _text(event.raw.get("reason"))
    if reason is not None:
        record["reason"] = redact(reason)
    return record


def run(event: KeelEvent, stdout: Any = None, env: Mapping[str, str] | None = None) -> int:
    """Record the boundary, inject the plan path at start. Returns 0 always.

    THE DESTINATION IS WALKED UP FROM ``event.cwd``, NOT READ OFF IT (T602,
    BL8's residue). This asked the flat ``project_is_adopted(event.cwd)`` and
    returned 0 when the answer was no, so a session started in a SUBDIRECTORY
    of an adopted project got NO ``session_start`` line, NO ``session_end``
    line, NO orientation, NO plan-file instruction and NO fleet-registry entry,
    for its whole life - the boundary records the stop gate's accounting and
    the dashboard both read back. T515 left this site alone for one stated
    reason, the project-relative ledger path in the injected line; ``ledger_hint``
    is that reason answered, so the record can follow the walk like every other.

    EVERY DOWNSTREAM READ FOLLOWS THE ROOT, not ``event.cwd``, and that is the
    half a partial sweep would get wrong: the arming file, the backlog, the
    knowledge index, the prompt log and the registry entry are all facts about
    the PROJECT, and reading them at a subdirectory answers "unarmed, empty,
    nothing" about a project that is none of those things. ``event`` itself is
    left alone - ``sess8`` and the payload fields are what the records carry.

    FAILS CLOSED, unchanged in direction: a path no project owns, and a walk
    that ran out of budget, both answer None here and both write nothing at all
    rather than creating a ``.keel/`` somewhere nobody adopted (R25).
    """
    try:
        root = record_root_as_spelled(event.cwd)
        if root is None:
            return 0
        if event.kind == "session_end":
            append_audit(root, end_record(event))
            return 0
        if event.kind != "session_start":
            return 0
        # The live view is settled BEFORE the record is written, so the record
        # can carry what happened. It cannot raise and it is bounded, which is
        # what makes it safe to put ahead of the audit line.
        live_view_outcome = live_view_autostart(root, env)
        append_audit(root, start_record(event, live_view_outcome))
        # T227: this project's own path joins keel's user-global fleet
        # registry, only ever here (adoption already confirmed above) and
        # never inside this project's own tree - see ``registry_write``.
        registry_write(root)
        stream = stdout or sys.stdout
        if event.sess8:
            # WITHHELD RATHER THAN GUESSED when the ledger path cannot be
            # spelled from where this session stands (convention 7). A wrong
            # path here is worse than none: it would have the model create a
            # second ``.keel/`` the gate never looks in.
            ledger = ledger_hint(root, event.cwd, event.sess8)
            if ledger is None:
                print(
                    "keel: the session plan path was not injected: it cannot be "
                    "spelled relative to this session's own directory",
                    file=sys.stderr,
                )
            else:
                print(injection_line(event.sess8, ledger, cwd=root), file=stream)
        reminder = override_reminder(root, env)
        if reminder:
            print(reminder, file=stream)
        orientation = orientation_lines(root, env)
        for line in orientation:
            print(line, file=stream)
        # The live view is injected after the orientation facts and before the
        # index: it is a pointer, not a fact about this project, so it carries
        # its own tag and is counted separately against the same cap.
        # T144: when autostart is ON, the pointer is replaced by what actually
        # happened - one line either way, so the cap arithmetic below is
        # unchanged and no session pays twice for the same subject.
        live_view = autostart_line(live_view_outcome) or live_view_line()
        print(live_view, file=stream)
        # T235: the dead-man line, and it is CONDITIONAL - on a machine whose
        # hooks have never failed ``hook_fault_line`` returns None and nothing
        # is printed or charged. It sits here, after the pointers and before
        # the index, because it is a fact about keel rather than about this
        # project: a reader who is about to trust the orientation block above
        # needs to know first whether the hook that wrote it has been failing.
        fault_line = hook_fault_line()
        if fault_line:
            print(fault_line, file=stream)
        # T228: the compaction recovery block, and it is CONDITIONAL on the
        # payload's own ``source`` - on any start that is not a compaction
        # ``compaction_recovery_lines`` returns [] and nothing at all is printed
        # or charged. It sits last of the keel-facts lines and immediately
        # before the index because it is the most urgent thing a just-compacted
        # session can read, and because what it re-supplies (the user's own
        # recent requests) belongs closest to the work the model is about to do.
        recovery = compaction_recovery_lines(event, project=root)
        for line in recovery:
            print(line, file=stream)
        # One channel, two possible occupants: the index, or the one line
        # saying which feature this edition would need to have one. Never both,
        # and never neither in silence.
        notice = knowledge_notice()
        if notice:
            print(notice, file=stream)
        else:
            # FOUR always-counted terms now, and the fourth is written out
            # rather than folded in for the same reason the second and third
            # were (R16, R32): every line this hook injects has to cost the
            # index its bytes, or an addition silently widens what the cap
            # bounds. A session with no fault line charges nothing for it, and
            # a session that was not compacted charges nothing for recovery -
            # ``orientation_bytes([])`` is 0, which is the arithmetic half of
            # the zero-cost guarantee ``compaction_recovery_lines`` makes.
            #
            # A COMPACTED session's recovery block can be large - twelve
            # prompts of up to ``keel_compaction.PROMPT_CHARS`` each - and it
            # is charged in full rather than clamped, exactly as the
            # orientation block is and for the reason ``orientation_bytes``
            # states: the invariant this arithmetic keeps is that the INDEX
            # never silently grows the total past the cap. So on the one start
            # in a session's life where the recovery block appears, the index
            # yields its bytes to it and may print nothing at all - which is
            # the right trade, since the index is a searchable corpus the model
            # can reach on demand (``/keel:chart``) while the block is the only
            # copy of what the session was just asked to do.
            spent = (
                orientation_bytes(orientation)
                + orientation_bytes([live_view])
                + orientation_bytes([fault_line] if fault_line else [])
                + orientation_bytes(recovery)
            )
            cap = max(inject_cap_bytes() - spent, 0)
            records = knowledge_lines(root)
            block = index_block(records, cap)
            if block:
                print(block, file=stream)
            elif records:
                # R34, AT THE ONE BOUNDARY THAT PREVIOUSLY HAD NO ANNOUNCEMENT.
                # ``index_block`` ships its overflow marker alone when the cap
                # is too small for the header, but returns "" when the cap is
                # too small even for the marker - which, before the recovery
                # block existed, only a deliberately tiny KEEL_INJECT_CAP_BYTES
                # could reach. A large recovery block reaches it in ordinary
                # use: it can consume the whole cap and leave the index a cap
                # of zero, and an index that vanishes without a word is the
                # silent drop R34 forbids. So the count and the command that
                # reaches the records are printed even when nothing else can
                # be: the reader can see there is more, count it, and go and
                # get it.
                print(redact(OVERFLOW_MARKER.format(more=len(records))), file=stream)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(f"keel: session failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # T235: and the failure of the hook that REPORTS hook failures is
        # itself one line in that log, or the dead-man line above could never
        # name the fault that silenced it. Local, guarded, and unable to change
        # this return: ``record`` never raises by contract, and is wrapped here
        # anyway because this runs while something is already broken.
        try:
            import keel_faultlog  # noqa: PLC0415 - guarded, cost-contained

            keel_faultlog.record("session", exc)
        except Exception:  # noqa: BLE001 - a counter may never fail the observer
            pass
    return 0
