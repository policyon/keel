#!/usr/bin/env python3
"""keel capture - the observation layer.

Contract
--------
Reads   : one ``KeelEvent`` carrying a post-tool payload - never a raw
          harness payload for its decisions, only for the fields the neutral
          model does not normalise, each read from ``event.raw`` as data and
          never interpolated anywhere (R5). They are, in full:

          * ``hook_event_name``, which says which half of a pair this is;
          * ``tool_use_id``, the key the two halves share;
          * the DELEGATION half of ``tool_input`` (``subagent_type``,
            ``description``, ``prompt``, and a ``model`` override), and the
            launch tool's own ``tool_response``, from which only an agent id,
            the model it says it resolved (``resolvedModel``, T128), ONE
            FACT ABOUT THE RESULT'S OWN SHAPE - whether it is a mapping at
            all (T138) - and its ``status`` token (T323, whether the result
            was a background acknowledgment) are taken: three tokens and a
            yes/no about the container, never a body;
          * the MESSAGE-SEND half of ``tool_input`` (``to``/``recipient``,
            ``summary``, ``message``/``content``) and the message-send tool's
            own ``tool_response`` (``resumedAgentId``/``resumed_agent_id``
            and ``pin.id``, plus its text as a fallback), from which only an
            agent id is taken. ``SendMessage`` launches nothing and is not a
            delegation tool (see ``MESSAGE_TOOLS``), so it is named here
            separately rather than folded into the line above;
          * the BACKGROUND flag of a shell tool's ``tool_input`` -
            ``run_in_background``, one boolean (T137) - and, ONLY when it is
            set, the shell tool's own ``tool_response``, from which only the
            harness's own background-task id is taken: ONE token, read out of
            the acknowledgment's labelled TEXT because no structured field
            carries it (see "THE HARNESS'S OWN BACKGROUND RUNS" below). Never
            a body, and never the run's output - which a hook could not read
            anyway, since the run has not produced any yet.

          AND NOTHING ELSE of any payload: no other key of a tool result is
          read, and no result BODY is written anywhere by this module.
Emits   : nothing on stdout, ever. An observer that speaks is a gate that
          forgot it was an observer (convention 11). Diagnostics go to
          stderr only.
Writes  : one append-only line per recorded event to
          ``<cwd>/.keel/audit/keel-audit.jsonl`` via ``keel_events``, and -
          for the observation-worthy subset - one further line to
          ``<cwd>/.keel/queue/keel-observations.jsonl``. Both only in a
          project that already carries ``.keel/``: an unadopted project is
          left untouched, exactly as the Phase 0 spike is. Every string in
          either line passes ``keel_redact`` first, which is also what drops
          ``<keel-private>`` content before it can be written (convention 5,
          R10).
Argv    : none. Imported by ``keel_hook.py`` and dispatched as ``capture``.

Exit codes
----------
0, always. This subcommand has no verdict to express, so it has no other
code to return (convention 11: capture may not emit a decision).

What is recorded
----------------
Four families, from the SAME three registrations in ``hooks/hooks.json`` (the
resume family shares the two hand-off registrations rather than adding one -
see ``scripts/keel_gen_hooks.HANDOFF_MATCHER`` - and the background family
rides the action registration, which already covers both shell tools, so T137
widened no subscription and added no ``command`` string to the always-loaded
document):

* **Action records** - PostToolUse on a state-changing tool
  (``Write``/``Edit``/``MultiEdit``/``NotebookEdit``/``Bash``/``PowerShell``).
  One line naming the tool and a redacted, project-relative target: the file
  path for a write tool, the head of the command for a shell tool.
  Read/Grep/Glob are deliberately not registered - chatty and low value.
* **Hand-off records** - PreToolUse and PostToolUse on ``Task``/``Agent``:
  the launch of a subagent and its return. The two are the ``handoff_open``
  and ``handoff_close`` halves of one delegation.
* **Resume hand-off records** - PreToolUse and PostToolUse on the
  message-send tool (``SendMessage``), when the message is addressed to an
  agent. Same two halves, same wire values, plus ``handoff_kind: "resume"``.
  See "A RESUME IS A HAND-OFF THE RECORD NEVER SAW" below.
* **Background-run records** - PostToolUse on a shell tool whose call asked
  for ``run_in_background`` (T137). ONE line, beside the action record the
  same call already wrote and never instead of it, naming the launch and the
  harness's own task id. There is no second half and there never will be
  until a harness gives a hook one - see "THE HARNESS'S OWN BACKGROUND RUNS"
  below.

THE JOIN KEY (T102). A ``subagent_stop`` line names the delegation that ended
by ``agent_id``, and until this module was taught to read it, nothing on the
launch side carried that name: launch lines carried ``tool_use_id``, stop
lines carried ``agent_id``, and the two sets did not overlap, so a stop could
only be attributed to a launch by guessing from agent type and time order. The
launching tool DOES return the id - measured, not assumed: 240 of 240 ``Task``
results recorded in this project's transcripts carry ``agentId``, in both
result shapes (234 ``async_launched`` acknowledgments and 6 completed
foreground returns). It is in the tool's RESULT, so it reaches keel at
PostToolUse and lands on the CLOSE half, ``handoff_end``; the OPEN half records
``agent_id: null``, because at PreToolUse the tool has not returned and no id
exists yet. The two halves share ``tool_use_id``, so the close half's id is the
delegation's id - that is the chain a reader follows, and
``keel_stop.launch_agent_id`` is the one function that follows it.

WHAT THIS BUYS AND WHAT IT DOES NOT. For a BACKGROUNDED delegation the close
half is the launch acknowledgment, seconds after the launch and minutes before
any stop, so the id is on record long before the event it has to be matched
to. For a FOREGROUND delegation the tool returns only when the agent has
already finished, so the close half lands AFTER the stop it identifies -
measured in this session's own log at 2 and 3 seconds after. Neither case is
a problem for a reader of an append-only log, which sees both lines whenever
it runs, and the foreground case never needed a stop to close it anyway (its
own pair closes it). What it does mean is that a reader running inside that
short window sees a stop it cannot attribute, and the rule for that is the
rule for every unattributable stop: it is reported as unmatched, never
approximated.

THE THIRD MEMBER OF THE DELEGATION FAMILY IS NOT HERE, and a reader tracing
how a delegation ends should be sent to it rather than left looking: the
``subagent_stop`` line is written by ``keel_hook.cmd_subagent_stop``, from the
``SubagentStop`` registration. It is not a tool call at all - it names no
tool, no path and no command - so it normalises to none of the six event
kinds this module dispatches on, and it is produced from the payload in the
launcher instead. It is also NOT one line per delegation: a backgrounded
agent stops each time it has no live child and may be resumed afterwards, so
nothing may pair it 1:1 with a hand-off record. See that function's docstring.

THE ROUTE A DELEGATION RAN AT (T123, absorbing T111; source 2 added by T128).
Both halves of a hand-off also carry ``model`` and ``effort`` - what the
delegation was actually launched at, so a reader can tell a standard-tier
attempt from a deep-tier one without inferring it from the agent's name.
Three sources, in one fixed order:

1. THE CALL ITSELF. ``tool_input`` may carry an explicit ``model`` override,
   and when it does that is what ran, whatever the definition says. There is
   no ``effort`` override read here, and the omission is deliberate: the
   launch tool has no effort parameter today, so a key nothing supplies would
   be a guess dressed as a source. If one appears, this is where it goes.
2. THE LAUNCH TOOL'S OWN RESULT - ``resolvedModel``, the model the harness
   says it actually resolved the call to. It exists only in the RESULT, so
   only the CLOSE half can carry it (see "THE RESULT ANSWERS THE MODEL"
   below), and it answers the model alone: no result field names an effort.
3. THE LAUNCHED AGENT'S OWN DEFINITION - ``agents/<name>.md``, resolved
   beside this file (the installed plugin IS this tree), read for the
   ``model:`` and ``effort:`` lines of its frontmatter.

AND NOTHING ELSE. Where no source answers, the field is ``null``, and
that null is the point of the field rather than a hole in it: an attempt
whose effort is unknown cannot be escalated from, and a default invented at
capture time would make every such attempt look deliberate. keel never writes
a routing tier it was not told.

THE LEVEL NAMES ARE RECORDED AS THE DEFINITION SPELLS THEM (``default``,
``high``, ...), never translated into a provider's own scale, so a line
written today still reads when a provider renames its scale tomorrow. The
only handling applied is the frontmatter reader's own trimming.

OLDER LINES CARRY NEITHER KEY, and no reader may read that as a fact about
the delegation: absent means "written before the field existed", exactly as
for ``agent_id`` above. A reader treats an absent key and a null the same
way - unknown - and never as "ran at the default".

THE RESULT ANSWERS THE MODEL, AND ONLY THE CLOSE HALF CAN HEAR IT (T128).
MEASURED, NOT ASSUMED, the way the join key and the resume matcher above
were: every ``Task``/``Agent`` result this project's transcripts hold was
read before this source was added - 22 transcripts scanned, 11 of them
holding launches, 272 results in all. 268 of the 272 are STRUCTURED results,
and 268 of those 268 carry ``resolvedModel``; the remaining 4 are the bare
string ``User rejected tool use``, a launch that never ran and so resolved
nothing - which is why a result that is not a mapping costs this source and
falls through rather than being treated as a defect. It is a non-empty string
naming one model in 268 of 268 (``claude-sonnet-5`` 154, ``claude-fable-5`` 49,
``claude-opus-5`` 23, ``claude-haiku-4-5-20251001`` 22,
``claude-opus-5[1m]`` 20), and it is present in BOTH result shapes - 249
``async_launched`` acknowledgments and 19 completed foreground returns - so
a backgrounded delegation records it as readily as a foreground one. The
camelCase spelling is the only one measured; ``resolved_model`` is accepted
beside it for the same reason ``agent_id`` is accepted beside ``agentId``.

IT IS IN THE RESULT, so it reaches keel at PostToolUse and lands on the
CLOSE half, ``handoff_end``. The OPEN half keeps the definition's answer or
a null, and reads no result even if a payload carries one: at PreToolUse the
tool has resolved nothing, and a model recorded there would be a fact
backdated to a moment that did not hold it. The two halves of one delegation
may therefore carry DIFFERENT ``model`` spellings, and that difference is
honest rather than a defect - each half records what its own moment knew,
and the pair is joined on ``tool_use_id`` by any reader that wants both.

THE OVERRIDE STILL WINS, AND IT DISAGREES WITH THE RESULT WHENEVER BOTH
EXIST. Measured: 68 of the 268 launches passed an explicit ``model``, and in
68 of 68 the two spell the same routing differently - the call says
``sonnet``/``opus``/``fable``/``haiku``, the result says
``claude-sonnet-5``/``claude-opus-5[1m]``/``claude-fable-5``/
``claude-haiku-4-5-20251001``. That is an ALIAS beside its RESOLUTION, not
two answers to one question, and keel resolves neither into the other: it
records the higher-precedence source exactly as that source spelled it, the
same rule as "THE LEVEL NAMES ARE RECORDED AS THE DEFINITION SPELLS THEM"
applied to models. A reader that wants the resolved id reads the close half
of a launch whose call passed no override; a reader that wants to know what
the caller ASKED FOR reads a launch whose call did. Translating an alias
into an id at capture time would be a mapping invented in a hook and written
as an observation - the failure the route fields exist to prevent.

STRUCTURE ONLY, WITH NO TEXT FALLBACK, and the omission is deliberate rather
than an oversight of the idiom beside it (``launch_agent_id`` reads a
labelled id out of a result's text as a last resort). Three reasons: the
field is structurally present in 268 of 268 measured results, so no measured
case needs the fallback; a model name has no shape that distinguishes it
from any other word, so a text read could not check what it found the way an
id shape can; and the text of a COMPLETED result is the agent's own report -
keel's own briefs and this very docstring discuss ``resolvedModel`` in prose,
so a labelled-text scan would happily lift a model name out of a sentence
ABOUT one and record it as the model this delegation ran at. A wrong model
is worse than none, exactly as a wrong id is.

A LAUNCH THAT NEVER TOOK IS SAID SO, NOT LEFT OPEN (T138). The census above
measured its own four exceptions, and they are the discriminator: 268 of the
272 results are mappings, all 268 of them carrying BOTH an agent id AND a
``resolvedModel``, while the other 4 are the bare string ``User rejected tool
use``. What tells them apart is therefore NOT a missing model - a harness may
one day stop resolving one for a launch that ran perfectly - but the RESULT'S
OWN SHAPE: a result that is neither a mapping nor names an agent is not a
launch acknowledgment at all. ``launch_ack`` records exactly that and nothing
further about it.

THREE VALUES, AND THE NULL IS THE POINT OF THE THIRD. ``true`` where the
result was a mapping or named an agent; ``false`` ONLY where a readable
result was actually looked at and was neither; ``null`` on the open half,
which has no result to judge, and on a close half handed no readable result
at all. "There was nothing to look at" is not "the launch did not take", and
collapsing the two would be the expensive mistake here: a harness build that
stopped passing ``tool_response`` to PostToolUse would mark every launch in
the project dead at once, and a reader acting on that would empty a page full
of working agents. Absence stays absence (convention 7).

IT SAYS WHAT THE RESULT WAS, NOT WHAT THE AGENT DID. keel cannot see whether
an agent ran; ``launch_ack: false`` says the launching tool handed this hook
no acknowledgment. That is a fact about the record, and what to conclude from
it belongs to the reader.

AND IN THIS HARNESS A REJECTED LAUNCH FIRES NO PostToolUse AT ALL - measured
in this project's own audit log, not assumed: the four rejected launches of
2026-08-13T15:15Z left an open half each and NO close half, four
``handoff_start`` lines whose ``tool_use_id`` appears nowhere else in ~6000
lines. So this field is written for the harness build that DOES deliver such
a result to a hook, and it is deliberately not what rescues those four: a
reader with no close half to read cannot read one. They are closed at READ
time instead, by ``scripts/keel_orchestration_dashboard.py``, on evidence the
log does hold - and that rule is stated where it lives, not here.

A RESUME IS A HAND-OFF THE RECORD NEVER SAW (T124). Resuming an agent does
not call the launch tool at all: the orchestrator sends it a MESSAGE, and
until this module was taught to read that call, the delegation tools above
matched nothing, no ``handoff_start`` was written, and a resumed agent was
invisible for as long as it worked - the ring and WORKING NOW honestly showed
zero while it ran, and only its ``subagent_stop`` landed, usually with a null
``agent_type``. See [[a-resume-is-a-launch-the-record-never-saw]].

MEASURED, NOT ASSUMED, exactly as the join key above was. Every ``SendMessage``
call this project's transcripts hold was read before a matcher was written -
12 of 12, all of them agent resumes, and they agree on every field:

* ``tool_input`` carries six keys in all 12: ``to`` and ``recipient`` (the
  SAME id in 12 of 12), ``message`` and ``content`` (the full text and a
  truncated preview - they differ in 12 of 12, so the full one is read
  first), ``summary`` (present in 12 of 12) and ``type`` (``"message"`` in
  12 of 12, and NOT gated on: a type is not the fact this matcher needs).
* The target id is 17 hexadecimal characters in 12 of 12, the same shape the
  79 ``subagent_stop`` lines in this project's own log carry (79 of 79) and
  the same shape the launch tool returns. ``_AGENT_ID_RE`` is that measured
  shape, widened at both ends rather than pinned at 17, and it is the ONE
  place to widen if a harness restyles its ids.
* The RESULT (the ``tool_response`` a hook receives, measured as the
  transcripts' ``toolUseResult``) is a mapping of exactly
  ``{success, message, resumedAgentId, pin}`` in 12 of 12, where
  ``resumedAgentId`` equals the recipient in 12 of 12 and ``pin.id`` equals
  it in 12 of 12. Two acknowledgment wordings appear (10 "had no active
  task; resumed from transcript", 2 "was stopped (completed); resumed it");
  both carry the structured id, which is why no wording is parsed.

STRUCTURE FIRST, TEXT ONLY AS A FALLBACK, and the INPUT is what makes the
open half possible: ``resume_agent_id`` reads the result's ``resumedAgentId``,
then ``pin.id``, then a labelled id in the result's text, and finally the
recipient named in ``tool_input`` - which is the only source that exists at
PreToolUse, and therefore the reason a resume can be recorded WHILE the agent
works rather than after it stops. Every candidate must match the measured id
shape; a message to anything else - a person, a name, a channel - resolves to
None and writes NOTHING, in either half. That asymmetry is deliberate: a
missed resume costs what today already costs (an invisible agent), while an
invented one would put a phantom worker on the page, which is the failure
this task exists to end wearing the opposite mask.

WHAT A RESUME RECORD SAYS, AND WHAT IT REFUSES TO SAY:

* ``handoff_kind`` - ``"resume"`` here, ``"launch"`` on the delegation
  records above. AN ADDED FIELD, never a repurposed one, and never a new
  ``event`` value: the wire values stay ``handoff_start``/``handoff_end`` so
  that every existing reader - the stop gate's pairing, ``keel attest``, both
  viewers - counts a resumed agent as the working delegation it is, with no
  reader change at all, while a reader that cares which it was reads one key.
  An ABSENT ``handoff_kind`` means a line written before the key existed, and
  every such line is a launch by construction, because nothing else could
  write a hand-off then.
* ``agent_id`` ON BOTH HALVES, and it is the target's own id - the exact
  key ``keel_stop.same_agent_id`` joins on, so the ``subagent_stop`` that
  ends the resumed run pairs with this record and with no other. This is the
  one place a hand-off's open half CAN carry the id, because a message names
  its recipient before it is sent; a launch's open half cannot, and records
  null (see THE JOIN KEY above).
* ``subagent_type``, ``model`` and ``effort`` are ``null``, always. THE SEND
  KNOWS NONE OF THEM: it names an id, not a type, and it carries no model
  and no effort parameter. Copying them from the earlier launch would be an
  inference made at capture time and recorded as a fact - the one thing the
  route fields exist to prevent - so they are recorded as unknown and left
  for a reader to join on the id if it wants them. See
  [[a-type-is-not-an-identity]].
* ``description`` is the send's own ``summary`` and ``prompt_head`` the head
  of its ``message``, both redacted like every other captured value; nothing
  reaches either log by a path that skips ``keel_redact``.

A SEND THAT FAILED IS STILL RECORDED AS A PAIR, and the choice is deliberate
rather than overlooked. The open half is written before the tool has returned
anything, so it cannot know; the close half falls back to the recipient the
call named when the result carries no id, and the two halves therefore pair
and then wait exactly as a background launch does - closed by the stop that
names the agent, or by the liveness timeout when no agent ever ran. The
alternative, dropping the close half, would leave the open half unpaired and
the delegation open in the stop gate for no reason a reader could see. keel
records what was ATTEMPTED here; whether the agent then worked is what its
``subagent_stop`` and its activity answer.

THE HARNESS'S OWN BACKGROUND RUNS (T137). A delegation is not the only thing
that runs while the orchestrator keeps working: the harness backgrounds SHELL
commands too, and its own "Background tasks" panel lists them beside the
agents. keel's board listed only agents, because a backgrounded run recorded
exactly what a foreground one did - one ``activity`` line, no marker, no id -
and the fact that it was still running afterwards was nowhere on record.

MEASURED FIRST, as the join key and the resume matcher were, and the census
is the whole reason this family's shape is what it is. 257 transcript files
of this project were read (11,010 tool calls, 3,079 of them ``Bash``):

* 52 of the 3,079 shell calls passed ``run_in_background: true`` - a JSON
  boolean, in 52 of 52, and the ONLY background-related key in
  ``tool_input``, which otherwise carries just ``command`` and
  ``description``. That flag is therefore the whole test, and it is read
  from the CALL, where it is available at both hook halves.
* Their acknowledgments (63 results, counting the 9 replayed into sidechain
  copies) are a BARE STRING in 63 of 63 - not a mapping, not a content list -
  reading "Command running in background with ID: <id>. Output is being
  written to: <path>. ..." So there is NO structured field to read the id
  from, and the labelled-text read that ``launch_agent_id`` keeps as a last
  resort is here the ONLY source; the structured branch is kept beside it
  only so a harness build that grows one is understood without a change.
* The id is 9 lowercase alphanumerics in 63 of 63 (``b7mmo7bmb``,
  ``bdak8rc9j``, ...). ``_BACKGROUND_TASK_ID_IN_TEXT_RE`` is that measured
  shape, widened at both ends rather than pinned at 9 - the same rule
  ``_AGENT_ID_RE`` follows - and the label is what makes the read safe: a
  token of that shape is unremarkable, a token behind that sentence is not.
* IT IS THE SAME ID THE HARNESS'S PANEL SHOWS. The completion notice for a
  backgrounded run names ``<task-id>bdak8rc9j</task-id>`` - the ack's id
  exactly - so what keel records is the identity the owner is reading on the
  other screen, not a private handle of keel's own.

NO HOOK FIRES WHEN A BACKGROUND RUN ENDS, and that was PROVEN rather than
assumed, because the honest-limits rule below stands or falls on it. Two
measurements agree:

* In the transcripts, a finished background run announces itself as a
  ``<task-notification>`` block in a USER-role message (267 of them, 26 for
  backgrounded shell runs), carrying ``task-id``, ``tool-use-id``,
  ``status``, ``summary`` and an ``output-file``. It is not a tool call: it
  has no ``tool_use``, no tool name, and no result, so it normalises to none
  of the kinds this module dispatches on and matches no PreToolUse or
  PostToolUse registration - the only registrations that carry a
  ``tool_use_id`` to join on.
* Live, on 2026-08-13: a backgrounded command was launched from a session
  with keel installed, and this project's own audit log was read on both
  sides of its completion. The launch wrote its lines; the completion, 50
  seconds later, wrote NOTHING - the next line in the log is the next tool
  call the session made, 21 seconds after the run had ended.

SO THE RECORD SAYS "LAUNCHED", AND NEVER "DONE". A background-run line has
no closing half and claims none: it carries the launch's own moment, the
tool, the redacted command head, the ``tool_use_id`` and the harness's task
id, and nothing that would let a reader conclude the run has finished, is
still running, or succeeded. A "done" keel never heard is exactly the
invented worker [[a-recorded-end-is-not-a-finish]] and the resume matcher's
asymmetry above both exist to refuse, and it is worse here than a silence:
the owner's other screen shows the truth, so an invented one would be caught
by the very comparison that asked for this family.

WHAT STAYS INVISIBLE, HONESTLY. A background process the harness starts
WITHOUT a shell tool traverses no registration keel holds - the preview
server started through the browser tool (``mcp__...preview_start``, 10 calls
measured) is one, and keel's own registrations match no MCP tool name. It is
therefore absent from the board, and absent it stays: keel does not draw a
box for something it never observed. When a dashboard is started the ordinary
way - ``python scripts/keel.py dashboard`` backgrounded from the shell, which
is how both of this project's measured dashboard launches were started - it
IS a shell call, and it records like any other background run.

WIRE NAMES: the audit values written are ``activity``, ``handoff_start``,
``handoff_end`` and ``background_task``. The first three are what
``keel_stop.py`` pairs on when it verifies a ``[~]`` ledger item against the
audit log, and what ``scripts/keel_attest.py`` reconciles; the stop gate is
not modified in this wave, so renaming the wire values would silently disable
``[~]`` verification - the one property the stop gate exists for. The fourth
pairs with NOTHING, deliberately: it is an ADDED kind, which every reader
that never heard of it skips exactly as it skips any kind it does not know
(``scripts/keel_dashboard.feed_sentence`` returns "" for it and the page
falls back to the raw name; the orchestration page's own feed does the same),
so no reader had to change to keep working. The constants below carry the
open/close naming; the values carry the contract.

The observation queue
---------------------
The audit log answers "what happened, and can the ledger be trusted"; the
queue answers "what is worth remembering". They are separate files because
they are separate contracts: the audit log is reconciled by ``keel_stop.py``
and ``keel attest`` and must not move, while the queue is drained by
``/keel:log`` into knowledge records and is allowed to be lossy.

One queue line is written per observation-worthy event - a completed state
change, or the RETURN half of a delegation. The launch half writes no queue
line: a hand-off is one observation, and queueing both halves would make
every delegation look like two facts. The line carries ``v``, ``ts``,
``session``, ``tool``, one ``action`` summary and the redacted ``paths``
touched, and NEVER a payload body: no file content, no command output, no
delegation prompt. Distillation is the session's job, and it is done from
summaries plus the files themselves, which are on disk already.

For a background launch the harness returns a task id immediately, so
``handoff_end`` fires moments after ``handoff_start``. That is a launch
acknowledgment, not a completion, and ``keel_stop.py`` already treats it as
one (``BG_LAUNCH_MS``).

Failure policy
--------------
FAIL-OPEN. keel observing a session must never be able to break it, so every
internal failure - an unwritable audit directory, an unexpected payload
shape, a redactor that cannot resolve a home - is reported as one line on
stderr and the subcommand returns 0. Nothing is ever swallowed silently
(convention 7). ``tests/test_keel_wave2.py`` asserts this declaration.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network. Tool and hook-event names are matched casefolded (convention 3,
R1); both-case fixtures ship in tests/fixtures/capture/.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_adapter_claude import SHELL_TOOLS, WRITE_TOOLS  # noqa: E402
from keel_events import (  # noqa: E402
    KeelEvent,
    append_audit,
    append_queue,
    record_root_as_spelled,
    record_root_present,
)
from keel_redact import redact, redact_path  # noqa: E402

#: Tools whose completion is a state change worth one audit line.
ACTION_TOOLS: tuple[str, ...] = WRITE_TOOLS + SHELL_TOOLS

#: Tools that launch a subagent. Claude Code names it ``Task``; ``Agent`` is
#: the older spelling and still arrives from some builds.
DELEGATION_TOOLS: tuple[str, ...] = ("Task", "Agent")

#: Tools that send a message to an agent that already exists - which is how a
#: resume happens, and why this module has to read them (T124). Not a
#: delegation tool: it launches nothing, and a message addressed to anything
#: but an agent records nothing at all.
MESSAGE_TOOLS: tuple[str, ...] = ("SendMessage",)

#: The audit value for an action record. Named ``activity`` because
#: ``keel_stop.py``'s liveness rule reads exactly that key.
ACTION_EVENT = "activity"

#: The two halves of a delegation. See "WIRE NAMES" in the module contract:
#: the concept is open/close, the value is what the stop gate pairs on.
HANDOFF_OPEN_EVENT = "handoff_start"
HANDOFF_CLOSE_EVENT = "handoff_end"

#: WHICH KIND OF HAND-OFF a record describes - the added field that tells a
#: resume from a fresh launch without repurposing anything (T124). The wire
#: EVENT values above are deliberately unchanged, so a reader that never
#: heard of this key still counts a resumed agent as a hand-off.
HANDOFF_KIND_KEY = "handoff_kind"
HANDOFF_KIND_LAUNCH = "launch"
HANDOFF_KIND_RESUME = "resume"

#: THE HARNESS'S OWN BACKGROUND RUNS (T137). One ADDED audit kind, written
#: BESIDE the action record a backgrounded shell call already writes and never
#: instead of it, so every existing reader of ``activity`` sees exactly what it
#: saw before. The name says what the line IS - a background task was launched
#: - and no closing kind exists to go with it, because no hook hears one end.
BACKGROUND_EVENT = "background_task"

#: The one key in ``tool_input`` that says a shell call was backgrounded. A
#: JSON boolean in all 52 measured calls; the string spellings are accepted
#: beside it for the same reason ``agent_id`` is accepted beside ``agentId``,
#: and ANYTHING else - absent, null, 0, false, an unexpected type - reads as
#: "not backgrounded", which records exactly what today records.
BACKGROUND_INPUT_KEY = "run_in_background"
_BACKGROUND_TRUE_SPELLINGS = frozenset({"true", "1", "yes"})

#: Where the record carries the harness's own task id for the run, and it is
#: nullable BY DESIGN: an acknowledgment keel cannot parse costs the id, never
#: the line, because "a background run started here" is worth recording with
#: or without the harness's handle for it.
BACKGROUND_TASK_ID_KEY = "task_id"

#: The task id as the acknowledgment SPELLS it, which is the only place it is
#: spelled: the result is a bare string in 63 of 63 measured launches and no
#: structured field carries the id at all. Narrow on purpose - the harness's
#: own sentence, then a token of the measured shape - so it can fail to find
#: an id (yielding null) but cannot invent one out of ordinary output.
_BACKGROUND_TASK_ID_IN_TEXT_RE = re.compile(
    r"running in background with id\b\s*[:=]?\s*[\"']?([A-Za-z0-9][A-Za-z0-9_-]{2,63})",
    re.IGNORECASE,
)

#: Where a shell result MIGHT carry its acknowledgment as structure, tried
#: before the text read for the sake of a harness build that grows one. None
#: of these carried the id in any measured launch - the measured result is a
#: bare string - so this tuple is a courtesy to the future, not a source keel
#: has ever read.
BACKGROUND_RESULT_TEXT_KEYS: tuple[str, ...] = ("stdout", "output", "result")

#: How much of a shell command reaches the audit line. Long enough to
#: recognise the action, short enough that the log is not a transcript.
COMMAND_DETAIL_CHARS = 80

#: How much of a delegation prompt reaches the audit line.
PROMPT_HEAD_CHARS = 200

#: How long one queue ``action`` summary may be. A summary, not a transcript:
#: what distillation needs is the shape of the work, and the files it names
#: are readable in full at distillation time.
ACTION_SUMMARY_CHARS = 200

#: The native hook-event name that means "this is the launch half". Read
#: casefolded, per convention 3.
PRE_TOOL_EVENT = "pretooluse"

#: Where the launching tool returns the identity a ``SubagentStop`` payload
#: calls ``agent_id``. ``agentId`` is the spelling every ``Task`` result in
#: this project's transcripts uses; ``agent_id`` is accepted beside it because
#: the stop side already spells it that way and a harness that unified the two
#: must not silently stop being read.
RESULT_AGENT_ID_KEYS: tuple[str, ...] = ("agentId", "agent_id")

#: How much of a tool result's TEXT is scanned for the id when no structured
#: field carries it. The launch acknowledgment names the id in its first line,
#: so this is generous rather than a limit anything real approaches - and it is
#: a limit, so a long result can never turn one hook into a scan of a
#: transcript.
RESULT_TEXT_SCAN_CHARS = 2000

#: The id as the launch acknowledgment SPELLS it in prose, for the harness
#: build that hands a hook the result's text rather than its structure. Narrow
#: on purpose: a label, a separator, then a token of id shape. It can fail to
#: find an id, which yields null; it cannot invent one.
_AGENT_ID_IN_TEXT_RE = re.compile(
    r"\bagent[ _]?id\b\s*[:=]\s*[\"']?([A-Za-z0-9][A-Za-z0-9_-]{3,63})",
    re.IGNORECASE,
)

#: Where a message-send names the agent it is addressed to. Both spellings
#: carried the SAME id in all 12 measured calls; both are read so that a
#: harness which keeps only one of them is still understood.
MESSAGE_RECIPIENT_KEYS: tuple[str, ...] = ("to", "recipient")

#: Where the send's RESULT names the agent it actually resumed, in the order
#: measured: a top-level field, then the pinned agent's own id.
RESUME_RESULT_AGENT_ID_KEYS: tuple[str, ...] = ("resumedAgentId", "resumed_agent_id")
RESUME_RESULT_PIN_KEY = "pin"
RESUME_RESULT_PIN_ID_KEY = "id"

#: What a message-send carries as its body and its caller's own recap. The
#: full ``message`` is read before ``content``, which is a truncated preview
#: of the same text (they differed in all 12 measured calls).
MESSAGE_BODY_KEYS: tuple[str, ...] = ("message", "content")
MESSAGE_SUMMARY_KEY = "summary"

#: THE ONE PLACE THE AGENT-ID SHAPE IS DECIDED. Measured, not assumed: the
#: recipient of all 12 measured sends, the ``agent_id`` of all 79
#: ``subagent_stop`` lines in this project's log, and the id the launch tool
#: returns are each 17 hexadecimal characters. The bound is widened at both
#: ends rather than pinned at 17, because a length is a harness detail and a
#: SHAPE is what distinguishes an agent from a person; it is deliberately
#: narrow enough that ``user``, ``owner`` or a channel name can never pass.
#: A harness that restyles its ids stops recording resumes - the safe
#: failure, identical to today - and this constant is where it is widened.
_AGENT_ID_RE = re.compile(r"\A[0-9a-fA-F]{12,64}\Z")

#: The id as a message-send's RESULT spells it, for a harness build that
#: hands a hook the result's rendered text rather than its structure. Narrow
#: on purpose, the way ``_AGENT_ID_IN_TEXT_RE`` is: the measured label, a
#: separator, then a token of the measured id shape. It can fail, which
#: yields the input's recipient or nothing; it cannot invent an id.
_RESUMED_AGENT_ID_IN_TEXT_RE = re.compile(
    r"\bresumed[ _]?agent[ _]?id\b[\"']?\s*[:=]\s*[\"']?([0-9a-fA-F]{12,64})",
    re.IGNORECASE,
)

#: Where the launch tool carries an explicit model override, when the caller
#: passed one. Only the model: the tool has no effort parameter (see "THE
#: ROUTE A DELEGATION RAN AT" in the module contract).
LAUNCH_MODEL_KEY = "model"

#: Where the launch tool's RESULT names the model it actually resolved the
#: call to (T128). ``resolvedModel`` is the spelling all 268 measured results
#: use; ``resolved_model`` is accepted beside it for the reason ``agent_id`` is
#: accepted beside ``agentId`` - a harness that restyles its keys must not
#: silently stop being read. Only the model: no result field measured names an
#: effort, so no effort is read here (see "THE RESULT ANSWERS THE MODEL" in the
#: module contract).
RESULT_MODEL_KEYS: tuple[str, ...] = ("resolvedModel", "resolved_model")

#: WHETHER THE LAUNCH TOOL'S RESULT WAS AN ACKNOWLEDGMENT AT ALL (T138). An
#: ADDED key on both halves of a launch, never a repurposed one and never a new
#: ``event`` value, so no existing reader changes to keep counting hand-offs.
#: See "A LAUNCH THAT NEVER TOOK IS SAID SO" in the module contract for the
#: three values and why the third is a null rather than a ``false``.
LAUNCH_ACK_KEY = "launch_ack"

#: WHETHER THE LAUNCH TOOL'S RESULT IS A BACKGROUND ACKNOWLEDGMENT (T323). The
#: launch RESULT's OWN ``status`` field, the same one ``launch_acknowledged``
#: already treats as a mapping and nothing more - read here for what it names
#: rather than only whether it exists. ``async_launched`` in every background
#: acknowledgment this module's own census measured (234 of 234, then 249 of
#: 249 in the later T128 count - see "THE JOIN KEY" in the module contract);
#: ``completed`` in every foreground return measured (6, then 19). No third
#: value has been measured, so no third is named here - an unmeasured status
#: answers False, exactly as an unmeasured shape does for ``launch_acknowledged``.
#: Single spelling only: unlike ``agentId``/``resolvedModel``, no snake_case
#: variant has ever been measured paired with it, so none is read.
RESULT_STATUS_KEY = "status"
RESULT_STATUS_BACKGROUND = "async_launched"

#: WHETHER THE CLOSE HALF IS A BACKGROUND HAND-OFF (T323). An ADDED key on
#: both halves of a launch, the same idiom as ``launch_ack`` above: never a
#: repurposed key, never a new ``event`` value, so no existing reader changes
#: to keep counting hand-offs, and a reader that has never heard of it still
#: sees the same ``handoff_start``/``handoff_end`` pair it always did.
#:
#: CHOSEN OVER THE LAUNCH/RETURN GAP (the timing rule
#: ``hooks/keel_stop.py``'s ``BG_LAUNCH_MS`` and this repo's dashboard's
#: mirrored ``BG_MS`` both use) BECAUSE THAT GAP IS A LATENCY ASSUMPTION
#: ALREADY DOCUMENTED TO FAIL: T182
#: (``.keel/plans/keel-plan-ad91166c.md:1362``) measured a background
#: acknowledgment arriving eight seconds after its launch - over the 5s
#: threshold - and the defect this field exists to fix is the same shape from
#: the read side: a background dispatch's ``handoff_end`` is written seconds
#: after ``handoff_start`` regardless of how long the agent then runs, so a
#: reader that infers "background" from a SHORT gap is reading the wrong
#: half of the fact. ``status`` is a field the harness states about the
#: RESULT'S OWN SHAPE, not an inference from how long the result took to
#: arrive, so it does not share that failure mode.
HANDOFF_BACKGROUND_KEY = "background"

#: THE SHAPE A RESOLVED MODEL MAY HAVE, and the only screen applied to it: one
#: line, no control characters, and bounded. A model name is a TOKEN, not a
#: body - the longest measured is 25 characters - and this value arrives in a
#: payload and is written to the audit log, so a value that is not token-shaped
#: is refused rather than trimmed into looking like one. Refusing costs the
#: result as a source and falls through to the definition, which is the honest
#: outcome: keel could not believe what it was handed. Deliberately NOT a
#: whitelist of known model names - a provider names its own models, and a
#: capture layer that only records the models it has heard of would drop every
#: new one (see "THE LEVEL NAMES ARE RECORDED AS THE DEFINITION SPELLS THEM").
RESULT_MODEL_MAX_CHARS = 200
_RESULT_MODEL_RE = re.compile(r"\A[^\x00-\x1f\x7f]{1,%d}\Z" % RESULT_MODEL_MAX_CHARS)

#: The frontmatter keys an agent definition declares its route with. The same
#: two ``scripts/keel_checks.py --agents`` validates, read here rather than
#: re-derived, so the value recorded is the value the build gate checks.
DEFINITION_MODEL_KEY = "model"
DEFINITION_EFFORT_KEY = "effort"

#: The agent definitions, resolved BESIDE THIS FILE rather than under the
#: session's cwd: the hook that runs is the installed plugin's own copy, and
#: the definitions that launched the agent are its siblings. A project keel is
#: merely observing has no ``agents/`` of its own, and would answer with
#: somebody else's routing if the cwd were trusted here.
AGENTS_DIRNAME = "agents"
AGENTS_DIR = Path(__file__).resolve().parent.parent / AGENTS_DIRNAME

#: How much of a definition is read looking for its frontmatter. The block is
#: the head of the file by definition, so this is generous rather than a limit
#: a real definition approaches - and it is a limit, so a hook can never be
#: turned into a reader of an arbitrarily large file by the name in a payload.
DEFINITION_SCAN_CHARS = 8192

#: The shape a subagent type may name a FILE with. The type arrives in the
#: payload, and this value reaches the filesystem, so it is validated against
#: a whitelist rather than sanitised: no separator, no drive, no leading dot,
#: and therefore no traversal out of ``agents/`` (R5 - payload data is never
#: interpolated into a path). A type that does not match resolves to nothing,
#: which records two nulls.
_DEFINITION_STEM_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")

_ACTION_TOOLS_FOLDED = frozenset(name.casefold() for name in ACTION_TOOLS)
_DELEGATION_TOOLS_FOLDED = frozenset(name.casefold() for name in DELEGATION_TOOLS)
_MESSAGE_TOOLS_FOLDED = frozenset(name.casefold() for name in MESSAGE_TOOLS)
_SHELL_TOOLS_FOLDED = frozenset(name.casefold() for name in SHELL_TOOLS)


def project_is_adopted(cwd: Path) -> bool:
    """True when THIS EXACT DIRECTORY carries ``.keel/`` - never raises.

    KEPT, AND NO LONGER WHAT ``run`` ASKS (T515). Two other modules imported it
    (``keel_registry.write``, ``keel_session.run``) and it is the honest name
    for the question it answers, so it stayed; what changed is that "may keel
    record here" is no longer THIS question. See ``recording_root``.

    FLAT-ADOPTION EXEMPT (T602), AND IT NOW HAS NO PRODUCTION CALLER AT ALL -
    both modules named above were swept onto the walk, which is what BL8's
    residue was. It survives as the one NAMED spelling of the flat question,
    for tests and for a reader who genuinely needs "does THIS EXACT DIRECTORY
    carry keel" (adoption itself, not a record's destination), rather than
    having each of them re-spell the join. That is not an honour system:
    ``tests/test_keel_flat_adoption_sweep_t602.py`` asserts the caller count is
    still zero, so routing a new site through this function turns the sweep
    red exactly as writing a fresh inline ``.is_dir()`` does.

    Delegates to ``keel_events.record_root_present`` rather than spelling the
    join a second time: the walk and the flat test must agree about what
    "adopted" means or a directory could be adopted for one and not the other.
    """
    return record_root_present(cwd)


def recording_root(cwd: Path) -> Path | None:
    """The project this session's records belong in, or None. Never raises.

    THE DEFECT THIS CLOSES (BL8/T515), and it is a SILENCE rather than a wrong
    line: ``run`` used to ask ``project_is_adopted(event.cwd)`` - does THIS
    EXACT DIRECTORY carry ``.keel/`` - and return 0 when it did not. A session
    started in a SUBDIRECTORY of an adopted project therefore recorded NOTHING
    AT ALL: no ``activity``, no ``handoff_start``, no ``handoff_end``, no queue
    line, for the whole session. Nothing failed, nothing was reported, and the
    stop gate's accounting then had no evidence to reconcile - a guardrail that
    passes because it examined nothing. Resolving the project by WALKING UP,
    exactly as ``keel_gate.resolve_project`` resolves arming, is the same
    correction T178 made for the gate and T186 made for the stop gate.

    IT CANNOT WIDEN WHERE KEEL WRITES. The walk only ever returns a directory
    that ALREADY carries ``.keel/``, is bounded at the home directory and the
    filesystem root, and answers None for everything else - so no ``.keel/`` is
    ever created in a directory nobody adopted (R25). What it changes is that
    records that used to be dropped are now filed, one level or more up.

    WHY THE WRITE TARGET IS NOT CONSULTED HERE, and this is a deliberate limit
    rather than an oversight. These records - ``activity``, ``handoff_start``,
    ``handoff_end`` - are facts about WHAT THIS SESSION DID, not judgements
    about a project's rules, and ``keel_stop.session_has_open_handoff`` reads
    them back from the session's own directory to decide whether a delegation is
    still open. Re-pointing them at a foreign write target's project would take
    them out of the only log that read consults and make real delegations
    unfindable - the self-inflicted hole that read's own docstring refuses.
    The direction that costs is worth naming exactly, because it is the
    opposite of the obvious guess and it was measured, not reasoned: an OPEN
    hand-off is a reason to ALLOW a stop, so a change that HIDES hand-offs
    makes the stop gate STRICTER and a change that reveals more makes it more
    PERMISSIVE. Making the stop gate's read climb to match this one was tried
    under T515 and reverted for exactly that reason - see
    ``keel_stop.session_has_open_handoff``.

    A REFUSAL IS A DIFFERENT KIND OF RECORD and IS filed with the project whose
    rule produced it, which is where BL8's ten stray lines actually came from:
    ``keel_gate._named_project`` and ``keel_gate.audit_destination``.

    IT DOES NOT RESPELL A PATH THE WALK DID NOT MOVE (T602), which is why this
    goes through ``record_root_as_spelled`` and not through the bare walk. The
    walk climbs ``os.path.realpath``, so ``resolve_record_root(cwd).root``
    hands back the CANONICAL spelling even when the answer IS ``cwd`` - and on
    Windows the harness routinely supplies the 8.3 SHORT form. Every WRITE
    lands correctly either way, so the cost is not a misfiled record: it is
    that ``keel_redact`` collapses the home directory BY STRING, so a root
    respelled out of the spelling the home was resolved to stops matching and
    the raw path reaches stderr in a fault message - a redaction leak
    (convention 5). That leak was MEASURED, at the launcher's prompt hook,
    by ``tests/test_keel_compaction_t228.py``; this function is the sibling
    site with the same shape, and ``keel_hook._recording_project`` is the
    other. Only a walk that actually CLIMBED returns a canonical ancestor -
    a path this caller never held a spelling of anyway - so the ordinary
    session at its own root is byte-identical to what it was before.
    """
    return record_root_as_spelled(cwd)


def _is_same_directory(root: Path, cwd: Path) -> bool:
    """True when two spellings name the SAME directory. Never raises.

    RESOLVED AND CASEFOLDED, and this is not tidiness - it is the trap
    ``keel_gate.governance`` documents at length and this function was added
    for after walking into it. ``root`` comes back CANONICAL from the walk while
    ``cwd`` arrives as the harness spelled it, and on Windows those are
    routinely different strings for one directory: a temporary path under
    ``C:\\Users\\SOMEUS~1`` against the same path under the long account name.  [keel-leak: ignore - the 8.3 short-name shape this comment explains]
    Compared raw, a session standing in its OWN project root read as standing
    somewhere else, and every ``activity`` line's target was rewritten from
    ``src/app.py`` to a ``../../..``-and-home-path spelling of the same file.
    """
    try:
        return os.path.realpath(str(root)).casefold() == os.path.realpath(str(cwd)).casefold()
    except (OSError, ValueError):
        return str(root) == str(cwd)


def _absolute(cwd: Path, value: str) -> str:
    """A payload path made absolute against the directory it was spelled in.

    Never raises: a path that will not join is returned as it arrived, because
    a record naming the payload's own spelling is worse than nothing only if it
    is wrong, and this fallback cannot make it wronger than the payload was.
    """
    try:
        # REALPATH, not ``abspath``: the root this will be relativised against
        # came back canonical from the walk, and a target still spelled through
        # an 8.3 short name would read as OUTSIDE it and be logged as a
        # ``../..`` climb out of the project and back in.
        return os.path.realpath(os.path.join(str(cwd), value))
    except (OSError, ValueError):
        return value


def _mapping(value: Any) -> Mapping[str, Any]:
    """A mapping, or an empty one. Payload shape is never trusted."""
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str | None:
    """A non-empty string, or None. Any other type is absence, not an error."""
    if isinstance(value, str) and value.strip():
        return value
    return None


def native_event_name(event: KeelEvent) -> str:
    """The harness's own hook-event name, casefolded; "" when it named none.

    A hand-off is a launch or a return depending on which registration fired,
    and the neutral model has no ``pre_tool`` kind to carry that distinction
    (adding a seventh kind is a contract change, not a wave-2 change), so
    this one fact is read from the raw payload.
    """
    return (_text(event.raw.get("hook_event_name")) or "").casefold()


def _result_text(value: Any) -> str:
    """The TEXT a tool result carries, and deliberately nothing else it carries.

    Only two shapes are read: a result that IS a string, and the ``text`` parts
    of a result's ``content`` list. THE ``prompt`` FIELD IS NOT READ, and that
    exclusion is the whole reason this function is narrow rather than a walk of
    the result: the launch tool echoes the delegation prompt back in its own
    result, keel's briefs discuss agent ids in prose, and a scan that wandered
    into the prompt would happily lift an id out of a sentence ABOUT one and
    record it as the id of this delegation. A wrong id is worse than none: it
    is a false pairing wearing an exact key's clothes.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, Mapping) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def launch_agent_id(event: KeelEvent) -> str | None:
    """The agent id the LAUNCH TOOL RETURNED, or None when it returned none.

    THE JOIN KEY, read at its only available source. It is the tool's RESULT
    that names the agent, so this answers None for the launch half (PreToolUse
    carries no ``tool_response``) and answers the id for the return half - see
    "THE JOIN KEY" in the module contract for what that ordering does and does
    not buy.

    STRUCTURE FIRST, TEXT ONLY AS A FALLBACK. Every ``Task`` result measured in
    this project carries ``agentId`` as a field of the result object, so the
    structured read is the one that fires in practice; the text read exists for
    a harness build that hands a hook the result's rendered content instead,
    where the same id is spelled out in the acknowledgment's first line. Both
    yield a token, never a body: no part of a tool result is written anywhere
    by this function, so nothing here can carry raw tool text past the
    redaction chokepoint in ``keel_events._append_jsonl``.

    ABSENCE IS EXPRESSED, NEVER FAKED (convention 7): a result with no id, a
    result of an unexpected type, and no result at all all answer None, so the
    record carries a null that a reader must refuse to pair on rather than a
    value nobody supplied.
    """
    response = event.raw.get("tool_response")
    if isinstance(response, Mapping):
        for key in RESULT_AGENT_ID_KEYS:
            found = _text(response.get(key))
            if found:
                return found.strip()
        text = _result_text(response.get("content"))
    else:
        text = _result_text(response)
    match = _AGENT_ID_IN_TEXT_RE.search(text[:RESULT_TEXT_SCAN_CHARS])
    return match.group(1) if match else None


def result_model(event: KeelEvent) -> str | None:
    """The model the LAUNCH TOOL SAID IT RESOLVED, or None when it said none.

    THE CLOSE HALF'S OWN SOURCE (T128). ``resolvedModel`` exists only in the
    tool's RESULT, so this answers None for the open half TWICE OVER: the half
    is checked explicitly, and PreToolUse carries no ``tool_response`` to read
    anyway. The explicit check is not redundant belt-and-braces - it is the
    contract stated where it can be tested: a harness build that echoed a
    result into the launch payload could otherwise backdate a resolution onto
    the moment before the call returned.

    STRUCTURE ONLY. Unlike ``launch_agent_id`` there is no text fallback here,
    and the module contract gives the three reasons; the short one is that a
    model name has no shape to check, so a scan of a completed agent's own
    report could not tell the model this delegation ran at from a model it
    wrote a sentence about.

    THE ONE SCREEN IS SHAPE, not vocabulary: a value that is not a bounded,
    single-line token is refused, and refusal is expressed as None so the
    caller falls through to the definition rather than recording something
    keel could not believe. A result of an unexpected type, a missing field, a
    field of the wrong type, an empty one and a body pasted into it all reach
    that same None (convention 7: absence is expressed, never faked). The
    value yielded is a token; no part of a result BODY is written anywhere by
    this function.
    """
    if native_event_name(event) == PRE_TOOL_EVENT:
        return None
    response = event.raw.get("tool_response")
    if not isinstance(response, Mapping):
        return None
    for key in RESULT_MODEL_KEYS:
        found = _text(response.get(key))
        if found is None:
            continue
        found = found.strip()
        if _RESULT_MODEL_RE.match(found):
            return found
    return None


def launch_acknowledged(event: KeelEvent) -> bool | None:
    """Whether the launch tool's RESULT was an acknowledgment at all (T138).

    THE SHAPE, NOT THE CONTENTS. The one question asked of the result here is
    whether it is a mapping - the container, never what it holds - and, when it
    is not, whether ``launch_agent_id`` can still find an id in it. A result
    that is neither is what a REJECTED launch returns (measured: the 4 bare
    ``User rejected tool use`` strings beside 268 structured acknowledgments,
    all 268 of which carry both an id and a ``resolvedModel``). No value from
    the result is returned by this function, and nothing it reads is written
    anywhere: the answer is a boolean about the record.

    NULL WHERE NOTHING COULD BE JUDGED, and that is the whole reason this is a
    three-valued answer. The OPEN half is checked explicitly and answers None,
    as ``result_model`` does and for the same reason - PreToolUse has resolved
    nothing, and a payload that carried a result into it would be backdating a
    fact. A close half handed no result, an empty one, or a value of a type
    that cannot be read answers None too: "I was shown nothing" is not "the
    launch did not take", and only the second may ever be claimed here
    (convention 7 - absence is expressed, never faked).
    """
    if native_event_name(event) == PRE_TOOL_EVENT:
        return None
    response = event.raw.get("tool_response")
    if isinstance(response, Mapping):
        return True
    if _text(response) is None:
        return None
    return launch_agent_id(event) is not None


def launch_backgrounded(event: KeelEvent) -> bool | None:
    """Whether the launch tool's RESULT is a BACKGROUND acknowledgment (T323).

    THE STRUCTURAL SIGNAL, not the latency one. The launch RESULT's own
    ``status`` field names ``async_launched`` in every background
    acknowledgment measured and ``completed`` in every foreground return
    measured (see ``RESULT_STATUS_KEY`` above for the counts and where they
    are cited). A reader that instead measured the GAP between a delegation's
    open and close half - the way ``keel_stop.BG_LAUNCH_MS`` and the
    dashboard's mirrored ``BG_MS`` both do - is measuring how fast the
    acknowledgment happened to arrive, which is a fact about the machine and
    the harness that moment, not about the delegation; T182 measured that gap
    exceed 5s on a genuine background acknowledgment once already. This
    answers the question directly instead.

    THREE VALUES, for the same reason ``launch_acknowledged`` has three: the
    OPEN half is checked explicitly and answers None, because PreToolUse has
    resolved nothing and a payload that carried a status into it would be
    backdating a fact to a moment that did not hold it. A close half handed
    no result, an empty one, or a value of a type that cannot be read answers
    None too - "I was shown nothing" is not "this was a foreground return",
    and only a readable ``status`` naming something other than
    ``async_launched`` may ever answer False (convention 7).
    """
    if native_event_name(event) == PRE_TOOL_EVENT:
        return None
    response = event.raw.get("tool_response")
    if not isinstance(response, Mapping):
        return None
    status = _text(response.get(RESULT_STATUS_KEY))
    if status is None:
        return None
    return status.strip() == RESULT_STATUS_BACKGROUND


def agent_id_shaped(value: Any) -> str | None:
    """The trimmed value when it has the shape of an agent id, else None.

    THE "IS THIS ADDRESSED TO AN AGENT" TEST, in one place. It answers on
    SHAPE rather than on a name, because a name is what a harness renames:
    the measured id is a run of hexadecimal characters (see ``_AGENT_ID_RE``
    for the measurement), which no person, role or channel name can be.

    Answering None is a normal answer and the common one: every message sent
    to anything but an agent reaches it, and records nothing.
    """
    text = _text(value)
    if text is None:
        return None
    text = text.strip()
    return text if _AGENT_ID_RE.match(text) else None


def resume_agent_id(event: KeelEvent) -> str | None:
    """The agent a message-send is addressed to, or None when it names none.

    THE JOIN KEY AGAIN, at the source a resume has. Four candidates, in the
    order measured (see "A RESUME IS A HAND-OFF THE RECORD NEVER SAW" in the
    module contract): the result's ``resumedAgentId``, the result's pinned
    agent id, a labelled id in the result's TEXT for a harness build that
    hands a hook rendered content, and last the recipient the CALL named.

    THE LAST ONE IS WHY A RESUME CAN BE RECORDED WHILE THE AGENT WORKS: at
    PreToolUse there is no result at all, and the recipient is already on
    record, so the open half carries the same id the close half will confirm.
    Where they could disagree the RESULT wins, because it names the agent the
    harness actually resumed rather than the one the caller asked for.

    Every candidate passes ``agent_id_shaped``, so an unexpected payload, a
    message to a person, and a result of an unexpected type all answer None -
    which the caller records as "no hand-off happened here", never as a
    hand-off with a null id. No part of the result is written anywhere by
    this function: it yields a token or nothing.
    """
    response = event.raw.get("tool_response")
    if isinstance(response, Mapping):
        for key in RESUME_RESULT_AGENT_ID_KEYS:
            found = agent_id_shaped(response.get(key))
            if found:
                return found
        pin = _mapping(response.get(RESUME_RESULT_PIN_KEY))
        found = agent_id_shaped(pin.get(RESUME_RESULT_PIN_ID_KEY))
        if found:
            return found
        text = _result_text(response.get("content"))
    else:
        text = _result_text(response)
    match = _RESUMED_AGENT_ID_IN_TEXT_RE.search(text[:RESULT_TEXT_SCAN_CHARS])
    if match:
        return match.group(1)
    tool_input = _mapping(event.raw.get("tool_input"))
    for key in MESSAGE_RECIPIENT_KEYS:
        found = agent_id_shaped(tool_input.get(key))
        if found:
            return found
    return None


def message_body(tool_input: Mapping[str, Any]) -> str:
    """The text a message-send carries, full spelling first; "" when it has none."""
    for key in MESSAGE_BODY_KEYS:
        body = _text(tool_input.get(key))
        if body is not None:
            return body
    return ""


def resume_record(event: KeelEvent) -> dict[str, Any] | None:
    """One RESUME hand-off record, or None when the message named no agent.

    Same two halves, the same wire ``event`` values and the same field names
    as a launched hand-off - so nothing downstream needs to learn a new record
    to count a resumed agent - plus ``handoff_kind: "resume"``, which is the
    only thing that tells them apart and is an ADDED key rather than a reused
    one.

    THREE FIELDS ARE NULL BY CONSTRUCTION AND NOT BY OMISSION.
    ``subagent_type``, ``model`` and ``effort`` are what the SEND does not
    know: it names an id, not a type, and it carries neither a model nor an
    effort parameter. They are written as nulls rather than left out for the
    reason ``agent_id`` is written on both halves of a launch - a null says
    "this record's source could not know", an absent key says "this line
    predates the field" - and they are never copied from the delegation's
    earlier launch, because a value inferred at capture time and written as a
    fact is indistinguishable afterwards from one that was observed.

    ``redact`` is applied here exactly as it is in ``handoff_record``: not a
    second write path and not the screen the record depends on - the
    chokepoint in ``keel_events._append_jsonl`` screens every line whatever
    built it - but the same belt-and-braces every captured value gets.
    """
    agent_id = resume_agent_id(event)
    if agent_id is None:
        return None
    tool_input = _mapping(event.raw.get("tool_input"))
    opening = native_event_name(event) == PRE_TOOL_EVENT
    return {
        "event": HANDOFF_OPEN_EVENT if opening else HANDOFF_CLOSE_EVENT,
        HANDOFF_KIND_KEY: HANDOFF_KIND_RESUME,
        "session": event.session_id,
        "tool_use_id": _text(event.raw.get("tool_use_id")),
        "agent_id": agent_id,
        "subagent_type": None,
        "model": None,
        "effort": None,
        "description": redact(_text(tool_input.get(MESSAGE_SUMMARY_KEY))),
        "prompt_head": redact(message_body(tool_input)[:PROMPT_HEAD_CHARS]),
    }


def action_detail(event: KeelEvent) -> str:
    """The redacted target of an action record: a path, or a command head."""
    tool = (event.tool_name or "").casefold()
    if tool in _SHELL_TOOLS_FOLDED:
        return redact((event.command or "")[:COMMAND_DETAIL_CHARS])
    if event.file_paths:
        return redact_path(event.cwd, event.file_paths[0])
    return ""


def action_record(event: KeelEvent) -> dict[str, Any]:
    """One action record. Every value in it has already been redacted."""
    return {
        "event": ACTION_EVENT,
        "session": event.session_id,
        # Absent agent_type means main-session work, which is a fact rather
        # than a gap: keel_stop.py and attest both rely on that reading.
        "agent_type": _text(event.raw.get("agent_type")),
        # Mirrors the agent_type read above, exactly: same top-level key on
        # the same payload, null when absent. Present, snake_case, no
        # ``agentId`` fallback - measured 2026-08-21, key list in the T233
        # census, on a PostToolUse call made during a subagent's own turn;
        # the dual-spelling convention elsewhere in this file is for the
        # launch tool's own nested result, a different payload shape this
        # census did not measure.
        "agent_id": _text(event.raw.get("agent_id")),
        "tool": event.tool_name,
        "detail": action_detail(event),
    }


def _asked_for_background(value: Any) -> bool:
    """Whether a ``run_in_background`` value says "yes", on the measured shape.

    A JSON boolean in all 52 measured calls, so ``True`` is the answer this
    exists for; the three string spellings are accepted beside it the way
    ``agent_id`` is accepted beside ``agentId``, for a harness that renders
    its flags. EVERYTHING ELSE IS "NO" - absent, null, false, 0, a mapping, a
    word nobody measured - and "no" is not a failure: it records exactly what
    a foreground call records today, which is the direction that must never
    change.
    """
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in _BACKGROUND_TRUE_SPELLINGS
    return False


def is_background_launch(event: KeelEvent) -> bool:
    """Whether this event is a shell call the caller asked to BACKGROUND.

    Three conditions, all measured rather than inferred: the tool is one of
    the two shell tools (a write tool has nothing to background), the hook
    half is the RETURN half (PreToolUse has no acknowledgment, so it could
    carry no task id, and recording a launch keel has not yet seen return
    would put a task on the board that the harness may still refuse), and the
    call's own ``run_in_background`` says yes.

    IT READS THE CALL, NOT THE RESULT, for the fact itself. The result's
    wording is the harness's, and a wording is what a harness rewrites; the
    flag is the caller's own instruction and is present in both halves of
    every measured call. The result is read only for the id, and only after
    this has already answered True.
    """
    if (event.tool_name or "").casefold() not in _SHELL_TOOLS_FOLDED:
        return False
    if native_event_name(event) == PRE_TOOL_EVENT:
        return False
    tool_input = _mapping(event.raw.get("tool_input"))
    return _asked_for_background(tool_input.get(BACKGROUND_INPUT_KEY))


def background_task_id(event: KeelEvent) -> str | None:
    """The harness's own id for this background run, or None when it named none.

    THE ONLY SOURCE IS TEXT, and unusually so: the acknowledgment is a bare
    string in 63 of 63 measured launches, with no structured field to prefer
    (see "THE HARNESS'S OWN BACKGROUND RUNS" in the module contract). The
    structured keys are tried first anyway, so a harness build that grows one
    is understood without a change here; none of them has ever answered.

    WHAT MAKES A TEXT READ SAFE HERE is the label, not the token: 9 lowercase
    alphanumerics is a shape any word could wear, but the harness's own
    sentence in front of it is not something ordinary output produces. The
    scan is bounded by ``RESULT_TEXT_SCAN_CHARS``, so no result can turn one
    hook into a scan of a transcript, and it yields ONE token - no part of any
    result body is written anywhere by this function.

    ABSENCE IS EXPRESSED, NEVER FAKED (convention 7): a result of an
    unexpected type, an acknowledgment worded differently, and no result at
    all each answer None, and the caller records the line with a null id
    rather than dropping it or inventing a handle.
    """
    response = event.raw.get("tool_response")
    if isinstance(response, Mapping):
        parts = [_result_text(response.get(key)) for key in BACKGROUND_RESULT_TEXT_KEYS]
        parts.append(_result_text(response.get("content")))
        text = "\n".join(part for part in parts if part)
    else:
        text = _result_text(response)
    match = _BACKGROUND_TASK_ID_IN_TEXT_RE.search(text[:RESULT_TEXT_SCAN_CHARS])
    return match.group(1) if match else None


def background_record(event: KeelEvent) -> dict[str, Any] | None:
    """The background-run line this event calls for, or None for every other event.

    ONE LINE, WITH NO SECOND HALF, and every field on it is something the
    launch moment genuinely knew: the session and agent type that started it,
    the tool, the ``tool_use_id`` (the key the harness's own completion notice
    also carries, so the day a hook hears an ending it can be joined to this
    line without a migration), the harness's task id or a null, and the same
    redacted command head the action record beside it carries - composed by
    ``action_detail``, so the two lines can never disagree about what ran.

    WHAT IS NOT ON IT IS THE POINT. There is no status, no exit code, no end
    timestamp and no "running" flag, because a hook is told none of those: the
    completion arrives as a message to the model and reaches no registration
    keel holds (proven, twice, in the module contract). A reader may say
    "launched at ``ts``"; nothing here lets it say "finished", and nothing
    here lets it say "still working" either.

    ``redact`` is applied to the id for the same belt-and-braces reason
    ``handoff_record`` applies it to a model: the chokepoint in
    ``keel_events._append_jsonl`` screens every line whatever built it, and a
    second idempotent pass costs nothing.
    """
    if not is_background_launch(event):
        return None
    return {
        "event": BACKGROUND_EVENT,
        "session": event.session_id,
        # Same reading as the action record beside it: absent means the main
        # session ran it, which is a fact rather than a gap.
        "agent_type": _text(event.raw.get("agent_type")),
        "tool": event.tool_name,
        "tool_use_id": _text(event.raw.get("tool_use_id")),
        BACKGROUND_TASK_ID_KEY: redact(background_task_id(event)),
        "detail": action_detail(event),
    }


def definition_stem(subagent_type: Any) -> str | None:
    """The ``agents/`` file stem a subagent type names, or None for no file.

    The type is namespaced by the plugin that ships the agent
    (``keel:executor-deep``), and the definition on disk is not
    (``agents/executor-deep.md``), so the last segment is the stem. Answering
    None is a normal answer, not an error: a type of an unexpected type, an
    empty one, and one whose stem could name something other than a plain file
    inside ``agents/`` all reach it, and each records two nulls rather than a
    guess or a raised exception.
    """
    text = _text(subagent_type)
    if text is None:
        return None
    stem = text.strip().rsplit(":", 1)[-1].strip()
    return stem if _DEFINITION_STEM_RE.match(stem) else None


def _definition_frontmatter(path: Path) -> dict[str, str]:
    """The scalar frontmatter of one agent definition; ``{}`` when it has none.

    A LINE SCAN, deliberately, not a YAML parse: keel ships no third-party
    dependency (R7/R14) and the definitions are ``key: value`` lines. The
    scan matches ``scripts/keel_checks._agent_frontmatter`` - open on
    ``---``, stop on the closing ``---``, skip indented and commented lines
    (so a nested key can never be mistaken for a top-level one), split on the
    first colon, trim, and drop surrounding quotes - so the value keel RECORDS
    is the value keel's own build gate VALIDATES.

    Every failure answers ``{}``: an unreadable or absent file, a file that
    does not open with a fence, and a fence that does not close inside
    ``DEFINITION_SCAN_CHARS``. The last of those is why the fields collected
    are not returned early - a block that never closed may not be frontmatter
    at all, and "I could not read it" must record a null rather than half a
    header.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(DEFINITION_SCAN_CHARS)
    except OSError:
        return {}
    lines = head.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    return {}


def definition_route(
    subagent_type: Any, agents_dir: Any = None
) -> tuple[str | None, str | None]:
    """``(model, effort)`` as the launched agent's DEFINITION declares them.

    FAILS HONESTLY, EVERY WAY IT CAN FAIL: no ``agents/`` directory, no file
    for this type, a file that cannot be read, frontmatter without the keys -
    each yields None for what it could not answer, and one of the two may be
    known while the other is not (a definition with ``model:`` and no
    ``effort:`` records the model and a null effort). The broad guard is the
    module's FAIL-OPEN policy applied where it matters: an unexpected failure
    here costs the two fields, never the audit line they ride on, and it is
    reported on stderr rather than swallowed (convention 7).

    ``agents_dir`` exists so a test can point the resolver at a definition it
    wrote; nothing in production passes it, and the default is resolved beside
    this file rather than under the session's cwd (see ``AGENTS_DIR``).
    """
    try:
        stem = definition_stem(subagent_type)
        if stem is None:
            return None, None
        directory = AGENTS_DIR if agents_dir is None else Path(agents_dir)
        path = directory / f"{stem}.md"
        if not path.is_file():
            return None, None
        fields = _definition_frontmatter(path)
        return (
            _text(fields.get(DEFINITION_MODEL_KEY)),
            _text(fields.get(DEFINITION_EFFORT_KEY)),
        )
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: capture could not read an agent definition: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return None, None


def launch_route(event: KeelEvent) -> tuple[str | None, str | None]:
    """``(model, effort)`` this delegation actually ran at, or nulls.

    The order is the contract: an explicit ``model`` in ``tool_input`` beats
    everything, because an override is what the caller made run; the RESULT'S
    ``resolvedModel`` answers next, because the harness saying what it resolved
    the call to beats a file saying what it would prefer; the definition
    answers what neither of those did; and nothing answers after that - see
    "THE ROUTE A DELEGATION RAN AT" in the module contract for why a default
    is never supplied here.

    THE MIDDLE SOURCE IS AVAILABLE TO THE CLOSE HALF ONLY, which is a property
    of ``result_model`` rather than a branch here: the open half is written
    before the tool resolved anything. The EFFORT is untouched by the addition
    - no result field names one - so it still comes from the definition or
    from nowhere.
    """
    tool_input = _mapping(event.raw.get("tool_input"))
    override = _text(tool_input.get(LAUNCH_MODEL_KEY))
    resolved = result_model(event)
    model, effort = definition_route(tool_input.get("subagent_type"))
    if override is not None:
        return override.strip(), effort
    if resolved is not None:
        return resolved, effort
    return model, effort


def handoff_record(event: KeelEvent) -> dict[str, Any]:
    """One hand-off record - the open half or the close half of a delegation.

    BOTH HALVES CARRY THE ``agent_id`` FIELD, and only one of them can carry a
    value: the open half is written before the tool returned anything, so its
    id is null by construction rather than by omission. The field is present on
    both so that a reader never has to decide whether a missing key means "this
    launch had no id" or "this line predates the key" - a null says the first,
    an absent key says the second, and the audit log holds both generations.

    ``handoff_kind`` IS ``"launch"`` HERE, and it is on both halves for the
    same reason again: it says what this record IS, so that a reader telling a
    fresh launch from a resume (``resume_record``) never has to read the
    absence of a key as a fact about the delegation.

    ``launch_ack`` IS ON BOTH HALVES FOR THAT SAME REASON (T138), and only the
    close half can answer it: it says whether the launching tool's RESULT was
    an acknowledgment at all, so the open half records the null it honestly
    has. A ``false`` there is the one shape measured for a launch the tool
    refused - see "A LAUNCH THAT NEVER TOOK IS SAID SO" in the module contract,
    including why the four such launches in this project's own log carry no
    close half at all and are therefore closed by a READER instead.

    ``model`` AND ``effort`` ARE ON BOTH HALVES FOR THE SAME REASON, and it
    costs nothing to keep them there: both are resolved from ``tool_input``
    and the launched agent's definition, which the close half carries exactly
    as the open half does, so a KEY present on one and absent from the other
    would be a distinction with no fact behind it - and a ``handoff_end``
    missing the key would be indistinguishable from a line predating it.

    THE VALUES MAY DIFFER BETWEEN THE HALVES, AND THAT IS NOT A DEFECT (T128).
    The close half has one source the open half cannot have - the result's
    ``resolvedModel`` - so an un-overridden launch records the definition's
    model when it opens and the harness's resolved model when it closes. Each
    half records what its own moment knew; neither is corrected afterwards,
    because an append-only log has no afterwards, and the two are joined on
    ``tool_use_id`` by any reader that wants both.

    ``background`` (``HANDOFF_BACKGROUND_KEY``) IS ON BOTH HALVES FOR THE SAME
    REASON AS ``launch_ack`` (T323), and only the close half can answer it, for
    the same reason: at PreToolUse the launch has resolved nothing, so the
    open half is honestly null. It says whether the launch RESULT was a
    BACKGROUND acknowledgment rather than a foreground return - see
    ``launch_backgrounded`` for the structural signal and why it is preferred
    over a launch/return timing gap. A hand-off marked ``true`` here is OPEN
    in a reader's eyes until the matching ``subagent_stop`` arrives, never
    finished merely because this close half exists; see
    ``scripts/keel_orchestration_dashboard.py`` for the read side.
    ``redact`` is applied here the way it is to ``description``: not a second
    write path, and not the screen the record depends on - the chokepoint in
    ``keel_events._append_jsonl`` screens every line whatever built it - but
    the same belt-and-braces every other captured value gets, and idempotent
    against the chokepoint's own pass.
    """
    tool_input = _mapping(event.raw.get("tool_input"))
    opening = native_event_name(event) == PRE_TOOL_EVENT
    model, effort = launch_route(event)
    return {
        "event": HANDOFF_OPEN_EVENT if opening else HANDOFF_CLOSE_EVENT,
        HANDOFF_KIND_KEY: HANDOFF_KIND_LAUNCH,
        "session": event.session_id,
        "tool_use_id": _text(event.raw.get("tool_use_id")),
        "agent_id": launch_agent_id(event),
        LAUNCH_ACK_KEY: launch_acknowledged(event),
        HANDOFF_BACKGROUND_KEY: launch_backgrounded(event),
        "subagent_type": _text(tool_input.get("subagent_type")),
        "model": redact(model),
        "effort": redact(effort),
        "description": redact(tool_input.get("description")),
        "prompt_head": redact((_text(tool_input.get("prompt")) or "")[:PROMPT_HEAD_CHARS]),
    }


def observation_action(event: KeelEvent) -> str:
    """The one-line summary of what happened, already redacted.

    Three shapes, one per family, and none of them is a payload body: a shell
    tool contributes the head of its command, a write tool the file it
    changed, a delegation the subagent and the caller's own description of the
    task. ``redact`` is applied per part rather than to the joined string so
    that a marked ``<keel-private>`` region cannot survive by straddling the
    join (R10).
    """
    tool = (event.tool_name or "").casefold()
    if tool in _DELEGATION_TOOLS_FOLDED:
        tool_input = _mapping(event.raw.get("tool_input"))
        subagent = redact(_text(tool_input.get("subagent_type")) or "subagent")
        description = redact(_text(tool_input.get("description")) or "")
        summary = f"handoff to {subagent}" + (f": {description}" if description else "")
    elif tool in _MESSAGE_TOOLS_FOLDED:
        # A resume, in the queue's own lossy idiom. The agent's ID is not
        # spelled here and its type is not known here: what distillation
        # needs from a resume is that one happened and what it was about,
        # and the audit line beside it carries the identity in full.
        tool_input = _mapping(event.raw.get("tool_input"))
        description = redact(_text(tool_input.get(MESSAGE_SUMMARY_KEY)) or "")
        summary = "resumed subagent" + (f": {description}" if description else "")
    elif tool in _SHELL_TOOLS_FOLDED:
        summary = "ran " + redact((event.command or "")[:COMMAND_DETAIL_CHARS])
    else:
        target = redact_path(event.cwd, event.file_paths[0]) if event.file_paths else ""
        summary = f"changed {target}".strip()
    return summary[:ACTION_SUMMARY_CHARS]


def record_for(event: KeelEvent) -> dict[str, Any] | None:
    """The audit record this event calls for, or None when it calls for none.

    Deliberately total: a tool keel did not register for, a payload with no
    tool name at all, and a Read call all return None rather than an empty
    record (convention 7 - absence is expressed, never faked). A message-send
    reaches that same None whenever it names no agent - the ONE case here
    where a registered tool records nothing, and the reason it is a case at
    all: keel observes delegations, and a message to a person is not one.
    """
    tool = (event.tool_name or "").casefold()
    if tool in _DELEGATION_TOOLS_FOLDED:
        return handoff_record(event)
    if tool in _MESSAGE_TOOLS_FOLDED:
        return resume_record(event)
    if tool in _ACTION_TOOLS_FOLDED:
        return action_record(event)
    return None


def observation(event: KeelEvent) -> dict[str, Any] | None:
    """The queue line this event calls for, or None when it calls for none.

    None for anything the audit log does not record either - the queue never
    observes something the audit log did not see - and None for the LAUNCH
    half of a delegation: a hand-off is one observation, recorded when it
    returns.
    """
    if record_for(event) is None:
        return None
    if native_event_name(event) == PRE_TOOL_EVENT:
        return None
    return {
        "session": event.session_id,
        "tool": event.tool_name,
        "action": observation_action(event),
        "paths": [redact_path(event.cwd, path) for path in event.file_paths],
    }


def run(event: KeelEvent) -> int:
    """Record what this event is worth recording. Returns 0 unconditionally.

    THE BACKGROUND LINE IS WRITTEN BESIDE THE ACTION LINE, NEVER INSTEAD OF IT
    (T137), and the ordering is the contract: the action record goes first, so
    a reader replaying the log sees the same ``activity`` line at the same
    position it has always been at, and the added kind arrives after it. A
    foreground call reaches ``background_record`` too and gets None from it,
    which is why this addition changes nothing at all for the 3,027 of 3,079
    measured shell calls that were never backgrounded.

    NO QUEUE LINE FOR IT. The observation queue records what is worth
    REMEMBERING, and the run's own action summary already says what was run;
    a second queue line naming the same command would make one command look
    like two pieces of work at distillation time.
    """
    try:
        root = recording_root(event.cwd)
        if root is None:
            return 0
        if not _is_same_directory(root, event.cwd):
            # THE LINE IS ANCHORED ON THE PROJECT IT IS FILED IN (convention 5).
            # Reached ONLY when the session stands in a SUBDIRECTORY of its
            # project - the case that recorded nothing at all before T515 - so
            # the ordinary case does not enter this branch and every existing
            # record is byte-identical. The payload paths are made absolute
            # FIRST, against the directory the payload was spelled relative to:
            # re-anchoring ``x.py`` on the root without that would rename the
            # file, turning a missing record into a wrong one.
            event = replace(
                event,
                cwd=root,
                file_paths=tuple(_absolute(event.cwd, path) for path in event.file_paths),
            )
        record = record_for(event)
        if record is None:
            return 0
        append_audit(root, record)
        background = background_record(event)
        if background is not None:
            append_audit(root, background)
        queued = observation(event)
        if queued is not None:
            append_queue(root, queued)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(f"keel: capture failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        # T235: one line in the user-global hook-error log, so a capture hook
        # that has been failing silently for a week is a NUMBER somebody can
        # see rather than a stderr line nobody kept. The import is local and
        # guarded on purpose - this runs while something is already broken, so
        # a missing or half-applied log module must cost the log line and
        # nothing else - and ``record`` cannot raise or change this return.
        try:
            import keel_faultlog  # noqa: PLC0415 - guarded, cost-contained

            keel_faultlog.record("capture", exc)
        except Exception:  # noqa: BLE001 - a counter may never fail the observer
            pass
    return 0
