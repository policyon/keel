#!/usr/bin/env python3
"""read-only local viewer over the audit log and the ledgers.

Contract
--------
Reads   : exactly two things under the surveyed project, both read-only -
          ``<project>/.keel/audit/keel-audit.jsonl``  the append-only record
          ``<project>/.keel/plans/keel-plan-<sess8>.md``  the session ledgers
          plus ``<project>/.keel/keel-policy.md`` for the arming tier, through
          ``keel_gate.policy_tier``. No HTTP route opens anything else, and
          nothing outside the project is reachable from any route. The one
          other reader here is ``read_hints``, which a LAUNCHER may call to
          find a running viewer: it opens this module's own hint files under
          ``<project>/.keel/cache/`` and nothing else, and neither the
          server nor ``main`` ever calls it.
Emits   : one line on stdout naming the URL it bound, then HTTP responses on
          the loopback interface. Every filesystem path in every response -
          including the ledger text - passes ``keel_redact`` first, so a
          screenshot or a shared tab carries no username (convention 5).
Writes  : NOTHING over HTTP - that is the security posture and it is
          enforced structurally: the four state-changing HTTP methods are
          bound to one refusal handler with no filesystem code in it at all,
          and the three read routes call two reader functions that only ever
          open files for reading. Running this module as a PROGRAM (``main``
          - never ``build_server`` alone, which stays pure) additionally
          writes ONE best-effort port-hint file of its own into
          ``<project>/.keel/cache/``, named for its own process id and port,
          and deletes that one file on a clean exit - see "Ports and the
          port hint" below. As a program it writes, reads and deletes no
          other file in that directory - not the directory listing, not
          another viewer's file - and nothing outside the project is ever
          written.
Argv    : ``--project DIR`` (else ``CLAUDE_PROJECT_DIR``, else the current
          directory).

Routes
------
``GET /``            the single page
``GET /api/state``   the whole state as JSON: counts, an open-work list, the
                     grouped/flat feed, ledger, plans
``GET /api/plan?name=keel-plan-<sess8>.md``  one ledger as plain text
Anything else is 404. ``POST``/``PUT``/``PATCH``/``DELETE`` are 405 with the
read-only contract stated in the body - a viewer that quietly ignored a write
would be indistinguishable from one that accepted it. Every response, read or
refused, carries a Content-Security-Policy, ``X-Content-Type-Options``,
``X-Frame-Options`` and ``Referrer-Policy`` header - a page with no write
route is not a reason to skip the headers that say so to the browser too.
Before any of this - even 404 - a ``GET``/``HEAD`` request's ``Host`` header
is checked against the interface and port actually bound (T38; see "Host
validation" below) and refused if it names anything else.

Host validation, against DNS rebinding (T38)
-----------------------------------------------
Loopback binding and the security headers above both lean on the browser's
own SAME-ORIGIN policy, and DNS rebinding defeats that assumption without
touching either of them: a page served from an attacker's domain, once the
attacker points that name at ``127.0.0.1``, is SAME-ORIGIN to the browser the
instant it resolves - so the Content-Security-Policy, ``X-Frame-Options`` and
``Referrer-Policy`` headers never apply to it, and it can ``fetch`` this
server's own routes like any other same-origin script. The loopback bind does
not stop this: the socket only ever ANSWERS on loopback, it never asks who is
calling. What is left to check is what the request itself CLAIMS to be
talking to - its ``Host`` header - against what is actually bound.

``do_GET``/``do_HEAD`` (``_host_ok``, backed by ``_host_allowed``) check it
before looking at the route, even before 404 - checking after routing would
mean the routing itself already trusted the request. Two spellings of the
ONE interface this server ever binds are ACCEPTED, both at the port actually
bound (read fresh from the live socket on every call, never cached, so a
value from one running instance can never be checked against another's): the
numeric ``HOST`` and the name ``localhost`` - they name the same interface,
and a reader who typed the name instead of the number has done nothing wrong.
A request carrying NO ``Host`` header at all is accepted too - a browser
always sends one, so its absence cannot be the rebinding attack this guards
against, and refusing it would break a launcher probing this server with a
client that omits one (see "Ports and the port hint", below). Both rulings
are the owner's, not this module's invention. Everything else - another
name, another port, a ``Host`` that merely resolves to loopback - is refused
with ``HOST_REFUSED_STATUS`` before either route is looked at, carrying the
same four security headers every other response does. A write method
(``POST``/``PUT``/``PATCH``/``DELETE``) is unaffected: it is refused by
``_refuse_write`` before any of this runs, exactly as it was before this
task, so a write's own 405 is never shadowed by a host mismatch it never
needed to check.

The feed (T27)
---------------
The audit log is overwhelmingly plain ``activity``; the landing view hides it
behind a toggle and defaults to everything else, PLUS work still open -
``compute_open_and_groups`` pairs ``handoff_start``/``handoff_end`` and
``session_start``/``session_end`` by their own identifier (never by counting
kind against kind), scoped to one session at a time. A start with no matching
end renders as OPEN with elapsed time computed against wall clock at render,
never called stalled or hung - a log reader cannot know that. A start WITH a
matching end folds the ``activity`` lines ATTRIBUTABLE to it into one
collapsed block per delegation; every other kind stays in the flat feed
whether or not it happened during a hand-off.

What "attributable" can mean here (T27d)
-----------------------------------------
An ``activity`` line carries no ``tool_use_id``, and a subagent's work is
recorded under the PARENT session id, so there is no identity on the line
that names one delegation. What it does carry is ``agent_type`` - written by
``hooks/keel_capture.py``, naming the subagent type that ran the tool, and
empty for the main session's own work. That is a TYPE, not an identity, so
the record supports exactly two certain statements and no third:

* an ``activity`` line with an EMPTY ``agent_type`` was the main session's
  own work and belongs to NO delegation - it stays in the flat feed however
  many hand-offs were in flight around it (``keel_capture`` calls this "a
  fact rather than a gap"; ``keel_attest`` refuses to attribute it too);
* an ``activity`` line whose ``agent_type`` differs from a hand-off's
  ``subagent_type`` did not come from that hand-off.

Everything else is inference. Time containment cannot settle which of two
CONCURRENT hand-offs of the SAME type produced a line, and that is not
hypothetical: in this repository's own audit log, 14 activity lines fall
inside three simultaneous ``general-purpose`` delegations at once. So
``_attribute_activity`` uses ``agent_type`` as the rule and containment only
to bound the candidates; where more than one candidate survives, it picks the
most recently started enclosing hand-off - the same tie-break
``hooks/keel_stop.py`` already uses - and REPORTS that it did, as
``group["inferred"]`` and a per-line ``inferred`` flag. The page renders such
a group differently and says so in words. A viewer may present an inference;
it may not present one as a reading of the record.

Whatever the rule decides, the accounting is exact: every audit line reaches
the page exactly once - inside one group, in the open list, or in the flat
feed - never twice and never nowhere. ``_attribute_activity`` makes that
structural by walking the lines and choosing one owner each, rather than
walking the hand-offs and letting two of them claim the same line.

Ports and the port hint (T28)
-------------------------------
The port is EPHEMERAL, never derived: ``build_server`` binds ``HOST`` on
port 0 and lets the operating system assign whatever is free - exactly as
before this task existed. A derived scheme (hashing the project's own
resolved path into a fixed window, with a bounded fallback when that port
was taken) was built and then reverted once it was caught contradicting R19
in ``docs/keel-rules.md`` - "a port derived from a user id or a project path
is undefined on some platforms and collides on all of them" - a rule cited
in ``docs/keel-why.md``, ``docs/keel-trust.md``, ``CHANGELOG.md``,
``agents/reviewer-security.md`` and ``scripts/keel.py``. Nothing in this
module computes a port from a path, a user id or anything else; a test in
this file's own test module pins that absence structurally, not just by
behaviour.

``_KeelHTTPServer`` still disables ``allow_reuse_address`` (see its own
docstring, below) - a genuine bug found while the reverted scheme was being
built, and independent of it: without the fix, a SECOND process can bind an
ephemeral port a FIRST one is still listening on, silently, with no
``OSError`` raised to report it. That fix is kept and pinned by a test.

An ephemeral port cannot be bookmarked, so ``main`` - never ``build_server``
alone - records the bound port, the process id and the instant it started
under ``<project>/.keel/cache/`` (see ``HINT_SUBPATH``): the one path this
project's own amendment already declares ignored and regenerable, so a
launcher can find a running viewer without guessing one. What it writes is
a HINT, not a contract, and says so in its own body: nothing deletes the
file if the process is killed rather than stopped, so a reader must PROBE
the URL it names before trusting it, and its ``started_at`` lets a reader
judge it stale by age even without probing. Full ruling:
``.keel/decisions/2026-08-10-r19-upheld-port-hint-instead.md``.

ONE FILE PER VIEWER (T35), never one shared file holding a list. The path
is a function of the PROJECT and two viewers of one project are ordinary -
``keel dashboard`` twice in two terminals - so each process owns exactly
one file named for its own process id and port (``hint_path``), writes it
ONCE at startup and deletes exactly that file on a clean exit. Three
defects go by CONSTRUCTION rather than by handling, which is why the shared
list was replaced rather than patched:

* nothing is read on the WRITE path - not the directory, not another
  viewer's file - so registering cannot erase anyone. The earlier shape
  read the shared file, treated an unparseable read as "no other viewers",
  and rewrote the file from that;
* nothing is read on the REMOVE path either, and no viewer ever computes a
  remainder or decides the directory is empty. Removal is one ``unlink`` of
  one path this process wrote, so a corrupt file can hide only its own
  viewer and never another that is still serving;
* there is no merge, so there is nothing to race: two viewers starting or
  stopping in the same instant touch two different paths.

``read_hints`` is the reader's whole side. It collects the directory and
returns a ``HintScan``: the viewers it could parse, a COUNT of candidate
files it could not, and whether listing the directory itself failed. "One
file is rubbish" and "no viewers are running" are therefore different
answers a reader can tell apart - an empty ``viewers`` list with a non-zero
``unreadable`` says a viewer may be running and its file is unreadable,
which is not what an empty cache says. A file is a viewer only if it parses
as a mapping carrying a well-typed ``url``, ``port``, ``pid`` and
``started_at``, the url is exactly this module's own loopback url for that
port, and the FILENAME is the one that pid and port would have written;
anything else is counted, never silently dropped and never allowed to make
the directory look empty. Every guard is broad enough that no parse failure
escapes: ``json.loads`` raises ``RecursionError`` - not an ``OSError`` - on
deeply nested input, so a file full of ``[[[[`` must not be able to stop a
viewer starting, serving or stopping.

Writing and removing are both best-effort: either failing is reported on
stderr, never raised, and the server starts, serves and returns its
existing exit codes exactly as it would with no hint at all. ``main``
closes the server in a ``finally`` NESTED INSIDE the removal's own, so
nothing that could come out of removal skips ``server_close`` or turns
exit 0 into an exit code the module does not document.

A viewer that is KILLED leaves its file behind, and nothing prunes another
process's file - a directory-wide decision is exactly what this shape
removed. That is a deliberate trade: the leftovers are one small file per
killed viewer in an ignored directory that is safe to delete wholesale,
each is self-describing enough for a reader to judge and probe, and the
alternative is a viewer deleting a file it does not own on evidence
(a pid) the note already says not to trust.

The delegation graph (T4), and the page's shape (T6)
------------------------------------------------------
The canvas is the page's PRIMARY region: it fills the window beside two
collapsible sections - the ledger and the audit feed. It draws ONE session as
a node at its centre with a node for every hand-off it made arranged around
it, joined by curved wires. Nothing moved into a section is lost: a section
keeps every row, chip, task and figure it held while collapsed and gives them
back on the next click, and the header, the roster and the footer are
unchanged.

WHAT COLLAPSING GIVES BACK CHANGED WITH THE FRAME (T119), and this paragraph
used to state the older rule as though it still held. T6 put the two sections
SIDE BY SIDE at the left, so collapsing either one handed its width straight
to the canvas. T119 stacks them in ONE sidebar column at the right, which is
the reference's own frame, and in a single column a shut section has no width
of its own to give while its sibling still holds the column open. So the rule
is now two rules, and both give back something real: collapsing ONE section
shrinks its row to the rail itself and hands the freed HEIGHT to the open
section beside it, which is the room a reader collapsing one of two stacked
lists actually wants; collapsing BOTH leaves no full-width section in the
column at all, so the column becomes the rail's own width and the canvas
takes the rest. There is no arrangement in which a collapse buys nothing -
that state (a rail beside dead space) is exactly what the grid rules in the
style block exist to prevent, and this module's own tests pin each of the
three shapes.
Which half of the canvas a card falls in is presentation only - the page says
so in standing text beside it, and every card prints its own start time.
``compute_graph`` builds it,
and it builds it from the SAME two lists the open rows and the collapsed
group rows are rendered from - the rendered open list and the rendered group
rows, after redaction - so the canvas and the rows below it cannot disagree.
There is no second pairing pass and no second reading of the log here: a
hand-off is on the canvas exactly because ``compute_open_and_groups`` already
produced it.

WHICH session. The one whose newest entry is newest - the session a reader
opening this page is almost always in. Every other session's hand-offs are
NOT drawn, and the count of them is stated in ``graph["note"]`` rather than
left to be discovered; so is the number of older CLOSED hand-offs of the
drawn session itself that ``GRAPH_NODE_TAIL`` left out. Open hand-offs are
never left out: they are the whole reason the canvas exists.

WHAT A NODE MAY SAY. The agent TYPE, because that is what the record holds -
never a model, and never a tier, since the log records who was asked and
never which model answered. The task it was handed (``description``, already
redacted), the clock time it started, how long it has been open (measured at
render against the reader's own wall clock, like every other elapsed figure
here), and whether it is still open. A closed node carries the duration the
record's own two timestamps give and how many activity lines were attributed
to it, saying in words how many of those were placed by inference rather
than read. Nothing says stalled or hung; the quiet-time wording (T30) is
carried onto an open node unchanged, and it already states that it is
inferred.

WHERE TWO OF ONE TYPE ARE OPEN AT ONCE the node says exactly what the
grouping already says - that the record names the KIND, not the instance
(``graph_type_note``) - rather than picking one and looking certain.

WHAT THE LAYOUT MAY NOT SAY. Every edge runs from the session to one
hand-off. No edge ever joins two hand-offs, because the record carries no
ordering between them and a chain would assert one; the page says so in
standing text beside the canvas, and a node's position carries no meaning
that its own printed start time does not already carry.

``counts.working`` is the header figure that joins this: how many hand-offs
are open right now, across the whole log, counted from the same open list.

The document title (T29)
-------------------------
The tab title carries ``counts.attention`` - a count of OPEN items (T27b),
the one number on the page that always means "a human still has to look at
this" - so it stays legible while the tab sits in the background. No
permission is requested, nothing calls the Notifications interface, and no
service worker is registered: a title string is the entire mechanism. The
string itself is built by ``document_title`` HERE, and the page only assigns
it, so what the tab says is a value a test can read rather than a template a
test can only find by substring (see "What the server decides", below).

Quiet-time (T30)
-----------------
An OPEN item's own ``ts`` is when it started; ``last_seen_ts`` is the latest
timestamp this module can still attribute to it - the same "activity-quiet"
reasoning ``hooks/keel_stop.py`` already applies to judge a background
hand-off's liveness, read here rather than decided (any NEW attributable
event moves ``last_seen_ts`` forward, which is what "resets the clock"
means). When ``last_seen_ts`` equals ``ts``, nothing has been recorded since
the item opened - often because whatever it is currently running has not
finished - and ``phase`` is ``"tool_running"``: the LONG threshold applies,
because a slow command is not a stall. Once at least one more event is
attributable, ``phase`` becomes ``"between_calls"`` and the SHORT threshold
applies, because keel's own subagents chain tool calls back-to-back and a
long gap between two of them is worth a label. Both thresholds are named
constants carrying their own reasoning (``QUIET_BETWEEN_CALLS_SECONDS``,
``QUIET_TOOL_RUNNING_SECONDS``), and the phase, the threshold and the worded
reason are all chosen HERE - the page receives them and only formats the
wall-clock part, so there is exactly one copy of each and a test can assert
its value. The page states once, in standing text, that the whole signal is
INFERRED, never measured: a log of completed actions cannot see a tool that
has not finished yet.

Delegation state: BACKGROUNDED, AWAITED, FINISHED (T103)
------------------------------------------------------------
A worker card's pill answers one question the raw pair cannot answer on its
own: is this delegation still going, and does the record even know it ended?
See [[a-recorded-end-is-not-a-finish]] - a ``handoff_end`` marks when the
LAUNCHING TOOL returned, not when the work did, so a card that read a quick
``handoff_end`` as "done" was reporting the wrong interval for exactly the
delegations this project runs most.

Three states, decided in ``_delegation_state`` and carried by every hand-off
row (open or closed) as ``delegation_state``:

* **background** - a CLOSED pair (a ``handoff_end`` exists) whose gap against
  its own ``handoff_start`` is under ``BG_LAUNCH_MS`` (see its import above
  for what was measured). The return was a launch acknowledgment, not a
  completion, so the card's elapsed figure ticks from the START against wall
  clock at render - never from the near-instant end - and the card states in
  words that the record cannot yet say it ended (``BACKGROUND_STATE_NOTE``),
  in the same place a reader would otherwise wrongly read "done in 5s".
* **awaited** - a CLOSED pair whose gap meets or exceeds ``BG_LAUNCH_MS``: the
  session was genuinely blocked on it, so the return already marks a real
  end and the elapsed figure is the fixed span between the two timestamps,
  never re-measured against the clock.
* **finished** - a ``subagent_stop`` (T101) is matched to this hand-off by
  ``_match_finish_events``, which since T102 CALLS the closing algorithm
  ``hooks/keel_stop.py`` and ``scripts/keel_attest.py`` use rather than
  mirroring it: ``keel_stop.match_stops_to_launches``, joining stop to launch
  on the ``agent_id`` both now carry. It does so without mutating either side
  - a private key on a raw audit entry would be one JSON response away from
  leaking into the flat feed. FINISHED overrides
  background or awaited outright and renders as a DIFFERENT pill, never a
  dimmed copy of the running one, because the reference does the same and
  because a reader must be able to tell finished from merely-not-yet-ended
  without reading either word. The elapsed figure becomes the fixed span from
  start to the stop's own timestamp - the one honest total the record can
  finally state.
* a hand-off with no ``handoff_end`` at all is the pre-existing OPEN case
  (T4/T30) and keeps its own wording and ticking elapsed unless a
  ``subagent_stop`` matches it, in which case it too reads FINISHED.

WHAT T102 FIXED, and this paragraph used to concede: two OPEN delegations of
one agent TYPE could not be told apart by a ``subagent_stop`` that only named
the type, so with two open at once a stop could finish the wrong card. The
stop names the AGENT, and the launch's own return now records that name, so
the two are told apart. The cost of exactness is stated rather than hidden: a
stop naming a launch this page has no record of, and a launch whose return has
not landed yet, match NOTHING - such a card stays as it was instead of being
finished by a resemblance.

The small last-action line under a card's pill (``last_action``) is the SAME
attribution the collapsed group's own ``events`` list already carries - the
last attributed line's own ``detail`` field (a path or a command head,
already redacted by ``hooks/keel_capture.py``) - so a card and its group can
never name a different last action. Absent or blank attribution omits the
line rather than guessing one (``_action_detail_text``).

A finished card lingers, then leaves (T109)
----------------------------------------------
FINISHED and AWAITED both mark a REAL end, unlike BACKGROUND's launch
acknowledgment, so ``compute_graph`` keeps drawing either one as its own node
only for ``GRAPH_FINISH_LINGER_SECONDS`` past that real finish moment
(``_real_finish_ts``) - measured against ``now``, which every production
caller reads as the real wall clock and every test can fix to a value. Past
that window the card is simply not among the nodes returned; it never
disappears mid-render and it is never duplicated into a second "lingering"
shape - the SAME node either is or is not still within its window. What is
still true of it lives on in the roster (``compute_roster``, unaffected by
this bound: it reads the raw open items and closed groups, never the
canvas's own node list) and in the flat feed's collapsed group row, neither
of which this task touches.

The header's own ``working`` count and the plain-text OPEN feed row
(``openRow``) used to both call an ``open_handoff`` row OPEN and count it as
working even after a ``subagent_stop`` had already matched it and the canvas
already called it FINISHED - two disagreements T103's own review found and
carried forward rather than fixing outside its own scope. Both are fixed
here, off the SAME ``delegation_state`` field the pill already reads: the
header's count excludes a FINISHED ``open_handoff`` the same way the canvas's
own ``open`` figure already does, and the feed row states FINISHED with the
real fixed span (start to ``finished_ts``) rather than a count still ticking
against ``now``.

The centre node's own panel (T105)
------------------------------------
Clicking the session at the centre of the canvas opens a drawer beside it
listing what that session did OUTSIDE any delegation - the reference's second
frame. Those lines are not searched for a second time. They are exactly the
lines rule (1) of ``_attribute_activity`` DECLINES to fold into a group (an
``activity`` line with an empty ``agent_type`` is the main session's own
work), collected by that same single pass over the lines and handed back
beside ``consumed`` as ``compute_open_and_groups``'s fourth value. One walk,
one decision, two outputs: the panel and the collapsed groups cannot disagree
about who ran a line, because neither is computed without the other.

Reading is not owning. The panel does NOT consume anything: a main-session
line stays in the flat feed exactly as it does today (T27's ``activity``
toggle shows it there), the same way T103's small last-action line reads a
group's own attributed lines without taking them out of the group. The
exactly-once law is about which row OWNS a line; a drawer on a node is a view
of lines the feed still owns, and it is bounded (``OWN_ACTIVITY_TAIL``) with
whatever it left out stated in words (``own_activity_note``) rather than
trimmed silently.

Everything the drawer says is decided here: the row's KIND (``action_kind`` -
a write or a command, read off the tool families
``hooks/keel_adapter_claude.py`` already declares rather than a second list
of tool names), the row's content (``_action_detail_text``, the same reader
of ``detail`` the card's last-action line uses), the summary counts
(``root_summary_label``) and the note (``own_activity_note``). The page maps
a kind to a glyph and nothing else. The panel's ``state:`` line is the root
node's OWN ``label`` string, re-shown rather than re-worded, so the chip on
the node and the line in the drawer are one value.

``agent_type`` is a TYPE here too (see "What 'attributable' can mean here")
-----------------------------------------------------------------------------
Quiet-time obeys the SAME limit grouping does, and for the same reason. An
open hand-off may claim an ``activity`` line only when the record can say it
was that hand-off's: the line must carry the item's own ``agent_type``, must
fall at or after the item's own start (nothing before a hand-off opened was
produced by it), and must have been produced while NO other open hand-off of
that same type was already running. Two ``executor`` hand-offs open at once
cannot be told apart by a field that names the type, so neither claims the
line: each falls back to its OWN start, which reads as ``"tool_running"``
and the long threshold - the honest answer, because borrowing a sibling's
evidence would report an item as freshly active on the strength of work it
may never have done. The decline is REPORTED rather than hidden: the item
carries ``ambiguous: true`` and its ``quiet_note`` says in words that more
than one hand-off of that type was open and the record names the type, not
which one ran the line - the same thing ``group["inferred"]`` says about the
same ambiguity on the grouping side.

What the server decides, and what the page decides (T29-T31)
--------------------------------------------------------------
Anything that can be decided from the record is decided HERE, where a test
can assert the VALUE: the attention count and the title string
(``document_title``), the roster's run count, working state and its own label
(``compute_roster``), the quiet-time phase, threshold and worded reason
(``_quiet_facts``, ``quiet_threshold_seconds``, ``quiet_note``), a feed row's
detail line (``detail_text``), the ledger's outcome and the sentence shown
for it (``read_ledger``), the wording of whatever could not be read
(``loss_note``), which session the canvas draws and every label on it
(``compute_graph``, ``graph_note``, ``graph_root_label``,
``graph_count_label``, ``graph_type_note``), the centre node's drawer - its
rows, their kinds, its summary line and its note (``root_panel``,
``action_kind``, ``root_summary_label``, ``own_activity_note``), whether the
session the CANVAS draws reads as live, ended, quiet or none, and the word
and sentence its header pill shows for it (``session_liveness``, T108 - the
sibling of the disconnect notice: that notice says the VIEWER lost its feed,
this says the SESSION ITSELF is over - fed ``graph["session"]``, the SAME
full session id ``compute_graph`` already resolved, never a second
resolution built from the selected ledger's own filename, which carries
only ``sess8`` and can never equal a raw audit line's full id) - and the
fingerprint the redraw gate compares (``content_digest``). The page keeps
only what a server cannot
do: writing to the DOM, formatting a wall-clock elapsed time at render,
measuring where a card landed so an edge can be drawn to it, the one-second
ticker, and the fetch loop. That division is the point - a page that decided
these things could only be tested by looking for its source text, and a
substring survives any change to what the code computes.

Motion means "this is running" (T110)
--------------------------------------
The page has exactly THREE animations and each is gated on a marker that
cannot exist unless work is actually open, so a canvas with nothing open is
completely still - not slowed, not faded: still.

* ``@keyframes livedot`` - the dot in a card's state pill, under
  ``.node.live .pdot``. ``.live`` is ``node["open"]``, the same reading the
  header's WORKING NOW figure counts, so the cards that move and the figure
  that counts them can never disagree.
* ``@keyframes livewire`` - a dashed overlay drifting along the wire, under
  ``.wire.flow``. ``drawWires`` emits that path only for a card already
  carrying ``.live``, read back off the DOM rather than re-derived.
* ``@keyframes livehalo`` - the centre node's warm halo breathing, under
  ``.rootnode.live.acting``. ``live`` is ``session_liveness``'s own state
  (T108); ``acting`` additionally requires ``root["open"] > 0``. A live
  session with nothing delegated therefore glows without moving.

No animation carries information found nowhere else: the pill prints its own
state word, the elapsed figure beside it advances in digits, and the line
under the session's name says "N open now". A reader who cannot perceive
motion, or who asks their system for less of it (the page honours
``prefers-reduced-motion``), loses nothing at all.

The ledger tasks and roster (T31)
-----------------------------------
``parse_ledger_tasks`` is the one place a ledger's checkbox lines and their
``Accept:`` clauses are read - reused for the page's per-task acceptance list
and for ``ledger_progress``'s terminal-against-total figure, so there is
exactly one parse to keep correct rather than two that could quietly
disagree. "Terminal" matches ``hooks/keel_stop.py``'s own vocabulary: ``x``,
``!`` and ``?`` need no further proof; ``" "`` and ``~`` do not count, because
``~`` needs the audit log itself to show a genuinely open hand-off before
anything would call it settled. ``compute_roster`` counts every hand-off by
its agent type - closed ones from ``groups``, open ones from ``open`` - and
marks a type "working" exactly when one of its hand-offs is open right now; a
session's own OPEN entry carries no agent type and is not a run of anything.

``read_ledger`` is the one place the selected ledger is turned into what the
page shows, and it reports WHICH of five outcomes the read had rather than
collapsing them: ``none`` (this project has no ledger), ``unreadable`` (one
is listed but the read failed), ``listing_failed`` (the ledger DIRECTORY
itself could not be listed - T36; see "Failure policy"), ``empty`` (read
fine, no task lines) and ``tasks``. See "Failure policy" for why none of the
last four may look like the first.

Exit codes
----------
0  the viewer ran and was stopped by the user (Ctrl-C is a normal exit).
2  it could not run at all: the project has no ``.keel/``, or the loopback
   socket could not be bound.

There is deliberately no 1. This is a viewer, not a gate: it has no findings
to report and nothing it observes can fail a build.

Failure policy
--------------
FAIL-CLOSED. A viewer that cannot read what it is meant to show says so and
returns 2 rather than serving an empty page that looks like a quiet project
(convention 7, convention 12). Once serving, a single unreadable or corrupt
audit LINE costs exactly that line - the JSONL guarantee - and the loss is
counted into ``counts.unreadable_lines`` rather than hidden.

A LEDGER is counted the same way and for the same reason. A ledger listed by
``list_plans`` can still fail to open a moment later - deleted, locked,
replaced - and reading that failure as empty text would render it as "no
ledger for this session yet", which is what a genuinely empty project looks
like: a loss dressed as a fact. ``counts.unreadable_plans`` counts it (0 or
1: the page reads exactly ONE ledger per request, the selected one) and
``plan.state``/``plan.note`` say which outcome it was, in words the page
shows instead of the empty-project sentence.

LISTING itself can also fail (T36), and that is a DIFFERENT truth from
"this project has no ledger". Nothing in production creates
``.keel/plans/`` and the shipped templates ship none either, so an armed,
never-planned-in project genuinely lacking the directory
(``FileNotFoundError``) is an ordinary "none" - no loss, the existing
wording. Every OTHER failure listing that directory - a permissions
failure, a sharing violation, a transient I/O error, or a plans path that
exists as a FILE and so raises ``NotADirectoryError`` - means something is
actually wrong where ledgers should be, and ``list_plans`` reports it back
rather than folding it into the same empty list a quiet project returns.
``read_ledger``'s ``listing_failed`` state carries it into ``plan.state``/
``plan.note`` and ``counts.unreadable_plans`` the same way an unreadable
ledger already is, so the ordinary "none" sentence never reaches a project
whose listing actually failed.

The page's five regions (T119)
--------------------------------
The owner's pinned reference is a frame, not a skin, and this is that frame:
a HEADER BAR (the identity badges at the left, four stat tiles right-aligned),
the CANVAS as the dominant area, the ROSTER ROW along its foot, a SIDEBAR of
two stacked sections at the right (the ledger above, the audit feed below),
and the LEGEND BAR at the very foot. It is CSS over the markup that was
already there - the panes were re-seated, not rewritten - which is why every
pane's own behaviour (T3, T4, T5, T27, T30, T31, T103-T109) reads exactly as
it did before this task.

ONE BEHAVIOUR DID CHANGE, and it is named rather than left for a reader to
discover: what COLLAPSING a sidebar section gives back. T6's two sections sat
side by side and each handed its width to the canvas; stacked in one column
they cannot, so a single collapse now frees HEIGHT to the open section beside
it and only collapsing BOTH frees the column's width to the canvas. The rule
is written out in full under "The delegation graph (T4), and the page's shape
(T6)" above, where the older promise used to stand. Nothing else about a
collapse moved: it is still one class on one section, still loses no row,
chip, task or figure, and still comes back with the same control that closed
it.

NOTHING IS LOST, the owner's standing sentence. The reference has four tiles
and the header carried five figures, so ``events`` and ``sessions`` keep a
seat in the header's own left cluster rather than being dropped to make the
picture match; every other surface - the filter chips and their counts, the
per-task accept clauses, the arming chip, the read-only notice, the liveness
pill, the roster, the node drawer, the disconnect notice, the losses line and
all three footer sentences - keeps the seat it had.

THE FOUR TILES read the payload and compute nothing: WORKING NOW is
``counts.working`` (T109's own figure), HAND-OFFS is ``counts.handoff_start``,
GATE BLOCKS is ``counts.gate_block + counts.stop_block`` - both of keel's own
gates, counted together as they always were here, which the tile's own note
states rather than letting the shorter word imply the narrower count - and
TASKS DONE is the ledger panel's OWN terminal-against-total figure
(``ledger_progress``, worded for a box by ``progress_tile``), never a second
count of the same task lines.

THE LEGEND BAR names keel's real agents and no invented persona, each with a
colour dot and its own one-line purpose (``AGENT_ROLES``, ``legend_entries``).
Those purposes are a HARDCODED, DISPLAY-ONLY copy of what ``agents/*.md``
frontmatter says, because nothing here may read those files at runtime - this
viewer opens exactly two things under the surveyed project, and an installed
keel's agents live outside it. An agent type the log carries that the table
has no line for is still given a row, worded as what it is, rather than
silently missing from the key to the page's own colours.

The event feed's voice (T120)
--------------------------------
A flat feed row now states a SENTENCE where one can be built truthfully,
rather than only the raw event name (``feed_sentence`` and ``EVENT_VERBS``),
built here from the SAME already-redacted fields ``detail_text`` reads - no
second event read, no second decision about what a kind means; the page's
own script renders whatever this returns, or falls back to the raw name
where it returns ``""``. The verb is the record's own KIND and nothing else:
``handoff_start`` LAUNCHED,
``handoff_end`` REPORTED BACK - an end record is the LAUNCHING TOOL's own
return, an acknowledgment, never a completion (see
[[a-recorded-end-is-not-a-finish]]) - ``subagent_stop`` FINISHED, the only
verb this page ever attaches to a delegation's real end, and
``gate_block``/``stop_block`` BLOCKED. ``session_start``/``session_end`` are
plain statements, because no agent ran a session. Every other counted kind
(``activity``, ``gate_bypass``, ``override_active_at_stop``) keeps the
raw-name-plus-detail-line rendering this page already had - this task
invents no sentence for a kind the acceptance list never named. The actor
named is the record's own agent type where it carries one and the generic
word "Agent" where it does not; the task is the record's own ``description``
where it carries one and is left off, never invented, where it does not - a
``subagent_stop`` never carries one at all. The raw event name is never
hidden behind its sentence: it moved into the row's own ``title`` attribute,
beside the wall-clock time that used to sit in the row itself, and the
filter buttons and their counts are unchanged.

THE ORCHESTRATOR RULED THE ICON AND THE RELATIVE TIME IN SCOPE (the owner's
pinned-reference rule governs this dispatch), addending the above. The icon
is ``FEED_GLYPH[e.feed_verb]`` in the page's script - keyed by ``feed_verb``,
the SAME verb family ``feed_sentence`` already named for that row (never a
second decision from the raw kind), and reusing the page's OWN existing
glyphs rather than inventing new ones: "finished" is ``MARK.x``'s own DONE
mark and "blocked" is ``MARK["!"]``'s own BLOCKED mark, the identical
characters the ledger panel already draws for those two words. It states
nothing the sentence beside it does not (T110's own law: a glyph may add no
information found nowhere else). The relative time is the page's own
``elapsedSince``/``fmtDur`` pair, rendered against ``now`` at draw time into
a span carrying ``data-role="feed-ago"``/``data-ts`` - the SAME two-attribute
shape ``roster`` already marks its own last-seen span with (T118) - and
``tickFeed`` (new, run from the existing one-second ``ticker`` beside
``tickRoster``) advances its ``textContent`` alone on every later tick, by
querying ``#feed``, so a quiet feed's "N ago" figure can never freeze the
way a resting roster chip's once did before T118. The walk is bounded by
construction: ``#feed`` never holds more than ``EVENT_TAIL`` rows, groups
included.

TWO ITEMS FROM THE REFERENCE ARE DECLINED here, not missed. The reference's
"alerts off" toggle is NOT implemented: keel ships no alert machinery, and a
control that switches nothing off would be a control that lies. Renaming
agents to personas, the reference's own flavour of naming, is NOT
implemented: keel's real agent types stand, exactly as the legend bar above
already insists on.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
outbound network: the only socket is a loopback listener, and the page makes
no request to any origin but its own. Ledger names are validated by shape
before any path is built from them, so no request can escape ``.keel/plans/``.
Every file read names its encoding.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlparse

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

# T105: which tool names are WRITES and which are COMMANDS is not restated
# here either - the centre node's drawer names the KIND of each action, and
# the two families are exactly the ones the adapter declares and
# ``hooks/keel_capture.py`` itself imports to decide what an activity line
# records. A private list here would be a second answer to "is this a write?"
# that could drift the first time a tool is added to the adapter.
from keel_adapter_claude import SHELL_TOOLS, WRITE_TOOLS  # noqa: E402
from keel_events import KEEL_DIRNAME, audit_path, utc_now  # noqa: E402
from keel_gate import PLANS_RELPATH, GateError, policy_tier  # noqa: E402
from keel_redact import redact, redact_mapping  # noqa: E402

# T103: BACKGROUNDED-versus-AWAITED is read off exactly the value
# ``hooks/keel_stop.py`` already computes for its own gate decision, and
# FINISHED off the same MATCH that module makes for a ``subagent_stop``
# (T101). ``BG_LAUNCH_MS`` and the two halves of the join key are IMPORTED
# rather than restated - the same choice ``scripts/keel_attest.py`` already
# made (see its own import of the same names) and for the same reason: two
# copies of "what counts as background" or "which delegation this stop
# finished" is exactly the drift that produced T101's SF1 finding.
# T102 FINISHED THE JOB THIS COMMENT COULD ONLY PROMISE. ``same_agent_type``
# was imported here because this module used to have a matching loop of its
# own that needed a predicate; it no longer has one. ``match_stops_to_launches``
# IS that loop, in ``hooks/keel_stop.py``, called by the gate, the report and
# this viewer alike, so the name this file imports is now the whole algorithm
# rather than one comparison inside a local copy of it.
# MEASURED against THIS project's own audit log (2026-08-11): of 185
# ``handoff_start`` lines, all 185 are paired with a ``handoff_end``, and 150
# of those pairs (81%) closed within 5000ms - bunched tightly between 2s and
# 5s, a background-launch acknowledgment landing rather than real work
# finishing. The other 35 spread from 5s to just under 14m30s with no
# cluster anywhere near the boundary, so 5000ms sits cleanly in the gap
# between the two populations rather than cutting through either one.
# Because the split is measured rather than guessed, a card states it
# plainly - "background" or "awaited" - rather than marking it inferred.
from keel_stop import (  # noqa: E402
    BG_LAUNCH_MS,
    launch_agent_id,
    match_stops_to_launches,
)

#: The loopback address, hardcoded. A dashboard reachable from the network is
#: a different product with a different threat model.
HOST = "127.0.0.1"

#: Where the port hints live, relative to the project - the SAME ignored,
#: regenerable directory ``scripts/keel_index.py`` already uses for its own
#: derived cache. Declared ignored in this project's own amendment (see the
#: ``.gitignore`` assertion in ``tests/test_keel_wave3.py``).
HINT_SUBPATH: tuple[str, ...] = (KEEL_DIRNAME, "cache")

#: The name shape of ONE viewer's own hint file: ``<prefix><pid>-<port>.json``
#: (``hint_filename``). Named for the process and the port that own it, so
#: two viewers of one project can never write the same path and no viewer
#: needs to read anybody else's file to write its own - see "Ports and the
#: port hint" in the module docstring. The prefix also keeps the reader off
#: everything else the shared cache holds (``keel-index.db``, and the single
#: ``keel-dashboard-hint.json`` an older version of this module wrote, which
#: does not match this shape and is never parsed as a viewer).
HINT_PREFIX = "keel-dashboard-hint-"
HINT_SUFFIX = ".json"

#: Each hint file's own body, in its own words. It is the contract a reader
#: gets: a file may be stale, so PROBE before trusting it, and the only
#: process that ever writes or deletes this file is the viewer it describes.
HINT_NOTE = (
    "HINT, not a contract. This file describes ONE viewer and is written and "
    "deleted only by that viewer's own process; a server that was killed "
    "rather than stopped leaves its file behind - so probe the url (e.g. GET "
    "it) before trusting it, or judge it stale by comparing started_at against "
    "how long a keel dashboard is expected to run. No other process writes or "
    "deletes this file, so one viewer stopping never hides another that is "
    "still serving, and a corrupt file here can hide only its own viewer."
)

#: How many audit lines reach the page. The newest are the interesting ones,
#: and an unbounded feed makes the response grow with the project's history.
EVENT_TAIL = 400

#: Ledger filenames keel writes, as a shape: ``keel-plan-<sess8>.md``. A name
#: that does not match is refused before any path is built from it.
PLAN_PREFIX = "keel-plan-"
PLAN_SUFFIX = ".md"

#: The boilerplate every one of this project's own ledgers opens its heading
#: with (T107): ``# Session plan — <session>...``. Not itself a subject - the
#: same words on every single ledger - so it is trimmed before what follows
#: is offered as one.
PLAN_HEADING_PREFIX = "Session plan —"

#: How long a derived subject may run before the selector's own narrow width
#: would have to wrap it rather than show it whole (T107). Cut, never
#: wrapped, matching the note above.
PLAN_SUBJECT_MAX = 48

#: Punctuation trimmed from either end of a derived subject once the
#: boilerplate prefix and the ledger's own identifier are gone (T107): in
#: every ledger this project has written, what is left is introduced by an
#: em dash, a comma, or a parenthesis - none of them part of the subject
#: itself.
PLAN_SUBJECT_STRIP = " \t—-,:()"

#: A residue that is NOTHING BUT an ISO date (T107 review fix): some
#: ledgers' headings carry only their own identifier and the day they were
#: opened (``# Session plan — <session>, 2026-08-11``), and once the
#: identifier is stripped away a bare date is all that is left. That is not
#: a subject - a reader gains nothing a date did not already tell them from
#: the ledger's own mtime - so it is matched here and treated the same as no
#: heading at all. Anchored full-string (``fullmatch``): a subject that
#: merely CONTAINS a date among real words (``"0.4.0 release, 2026-08-01
#: audit"``) does not match this and is left untouched.
PLAN_SUBJECT_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

#: The HTTP methods that may change state. All four are refused (see below).
WRITE_METHODS: tuple[str, ...] = ("POST", "PUT", "PATCH", "DELETE")

#: The two spellings of THIS server's own loopback interface a ``Host``
#: header may name (T38): the numeric address it always binds, and the name
#: a reader may type instead of it - they name the same interface, and
#: neither is more correct than the other. Matched case-insensitively (a
#: Host header's hostname is itself case-insensitive, RFC 7230 S:2.7.3).
_HOST_NAMES: tuple[str, ...] = (HOST, "localhost")

#: The status a request with any OTHER ``Host`` gets (T38): understood and
#: DELIBERATELY refused, so neither 404 ("no such thing here") nor 405
#: (already reserved for a write method, refused before this check ever
#: runs - see ``_refuse_write``) would be honest. RFC 7230 S:5.4 already
#: assigns this same status to a Host header a server judges invalid.
HOST_REFUSED_STATUS = 400

#: The body sent with ``HOST_REFUSED_STATUS``. Never echoes the request's own
#: Host header back: that value came from whoever sent the request, and
#: reflecting it into a response body this module controls buys nothing a
#: fixed sentence does not already say.
HOST_REFUSED_BODY = (
    b"keel dashboard only answers requests whose Host header names the "
    b"loopback interface and port it actually bound; this request named "
    b"something else and was refused before routing.\n"
)

#: How much of a request body is read off the socket before it is discarded.
#: A refused request still has to be DRAINED or the connection is reset before
#: the client can read the refusal - which on Windows surfaces as a dropped
#: connection rather than the 405 that was actually sent. Bounded, because
#: "read whatever the client sends" is how a viewer becomes a memory bug; a
#: body larger than this is discarded by closing the connection instead.
MAX_DRAIN_BYTES = 1 << 20

#: Every route this server answers, and what each one reads. There is no
#: fourth entry and no route in this table writes anything.
READ_ROUTES: dict[str, str] = {
    "/": "the page itself (a constant string; no file is opened)",
    "/api/state": "the audit log, the ledgers, and the arming tier",
    "/api/plan": "one ledger named by a shape-validated basename",
}

#: Audit events counted out separately on the page.
COUNTED_EVENTS: tuple[str, ...] = (
    "session_start",
    "session_end",
    "handoff_start",
    "handoff_end",
    "subagent_stop",
    "activity",
    "gate_block",
    "stop_block",
    "gate_bypass",
    "override_active_at_stop",
)

#: The one audit kind common enough to need a landing-page toggle (T27a).
#: Every other kind either bounds a pair or is something a human should see
#: without asking for it.
ROUTINE_EVENT = "activity"

#: Ledger checkbox marks a task needs no further proof to carry (T31),
#: matching ``hooks/keel_stop.py``'s own vocabulary exactly: ``[x]`` done,
#: ``[!]`` blocked with a reason, ``[?]`` needs the user's decision. ``[ ]``
#: and ``[~]`` are deliberately absent - ``keel_stop.py``'s own comment calls
#: ``[~]`` the one mark that "needs proof" (an open hand-off on record), and
#: this read-only page has no business asserting that proof itself.
TERMINAL_MARKS = frozenset({"x", "!", "?"})

#: The tab's title with nothing needing a human. ``document_title`` prefixes
#: the attention count to it (T29); the page's own ``<title>`` carries the
#: same string so the tab reads the same before the first fetch returns.
PAGE_TITLE = "keel — read-only"

#: QUIET-TIME THRESHOLDS (T30). Two, not one, because "nothing new since
#: ``last_seen_ts``" means two different things depending on what already
#: happened - and both live HERE, in one copy, chosen by
#: ``quiet_threshold_seconds`` and worded by ``quiet_note``, so the page has
#: no constant of its own to drift out of sync with either.
#:
#: BETWEEN CALLS - something has already run under this open item and the
#: next thing has not started. keel's own subagents chain tool calls
#: back-to-back with no human in the loop, so a gap this long between two of
#: them, with nothing running, is worth a label.
QUIET_BETWEEN_CALLS_SECONDS = 60

#: TOOL RUNNING - nothing at all is attributable since the open item's own
#: start line, which most often means whatever kicked it off has not finished
#: yet. A slow command is not a stall, so this threshold is deliberately much
#: longer - ten minutes, the same figure ``hooks/keel_stop.py``'s own
#: LIVENESS_MS already uses to judge a background hand-off's liveness before
#: this page borrows that reasoning for a label.
QUIET_TOOL_RUNNING_SECONDS = 10 * 60

#: SESSION FRESHNESS WINDOW (T108). How recently the CANVAS's own drawn
#: session (``graph["session"]``) must have its newest audit line fall,
#: against wall-clock ``now``, to read as LIVE rather than historical - the
#: sibling of the disconnect notice: that notice says the VIEWER lost its
#: feed, this says the SESSION ITSELF is over. Ten
#: minutes: the same figure ``QUIET_TOOL_RUNNING_SECONDS`` above already
#: borrows from ``hooks/keel_stop.py``'s own ``LIVENESS_MS`` - a slow command
#: running right now is not "the session ended", so the window is generous
#: rather than twitchy. This answers a DIFFERENT question than either
#: quiet-time threshold above: those judge one OPEN hand-off's own last
#: attributable activity; this judges the whole SESSION's newest line, of
#: any kind, open or closed, against the clock - which is why it is its own
#: named constant rather than a reuse of theirs.
SESSION_LIVE_SECONDS = 10 * 60

#: The three honest states ``session_liveness`` may report, and the fourth
#: for "no session to judge" - never a missing field, per T108's own
#: acceptance: historical must be its own positive statement, not silence.
SESSION_STATE_LIVE = "live"
SESSION_STATE_ENDED = "ended"
SESSION_STATE_QUIET = "quiet"
SESSION_STATE_NONE = "none"

#: The header pill's own word for each state (T108) - decided HERE, in one
#: copy, the same shape ``DELEGATION_STATE_LABELS`` already gives one
#: hand-off's pill (T103), so the word on screen and the state a test reads
#: can never drift apart.
SESSION_STATE_LABELS: dict[str, str] = {
    SESSION_STATE_LIVE: "live",
    SESSION_STATE_ENDED: "ended",
    SESSION_STATE_QUIET: "quiet",
    SESSION_STATE_NONE: "no session",
}

#: The sentence under the pill naming exactly what evidence produced it -
#: never left for a reader to infer from the word alone (convention 7).
SESSION_STATE_NOTES: dict[str, str] = {
    SESSION_STATE_LIVE: "a line for this session was recorded within the last "
    f"{SESSION_LIVE_SECONDS}s",
    SESSION_STATE_ENDED: "a session_end line was recorded for this session",
    SESSION_STATE_QUIET: "no line for this session in over "
    f"{SESSION_LIVE_SECONDS}s, and no session_end was recorded - this is NOT "
    "the same as ended: a killed session never writes one",
    SESSION_STATE_NONE: "no session is selected",
}

#: CLOCK SKEW TOLERANCE (T108 review fix, finding 1). How far into the
#: FUTURE the session's own newest line may fall before it stops being
#: ordinary jitter and becomes suspect evidence. Five seconds - an order of
#: magnitude below ``SESSION_LIVE_SECONDS`` so it can never be mistaken for
#: the window that decides genuine freshness, but enough to absorb ordinary
#: rounding or NTP drift between whatever wrote the line and the clock this
#: viewer reads ``now`` from. Without this, ``max(0.0, now - epoch)`` used to
#: clamp ANY future timestamp - clock skew or a corrupted line alike - to age
#: zero, which reads LIVE forever and can never age into ``quiet``. Beyond
#: this tolerance a future-dated newest line is no longer read as fresh: it
#: is read as evidence this function cannot trust for the live/quiet call,
#: and ``SESSION_STATE_FUTURE_NOTE`` says so rather than the ordinary
#: quiet-time wording, which would claim an absence of activity this record
#: does not actually show.
SESSION_CLOCK_SKEW_TOLERANCE_SECONDS = 5

#: What ``quiet`` says when the newest line for the session is dated in the
#: FUTURE beyond the tolerance above (T108 review finding 1) - a different
#: sentence from the ordinary quiet wording, because the honest complaint
#: here is a suspect timestamp, not an absence of session_end.
SESSION_STATE_FUTURE_NOTE = (
    "the newest line for this session is dated in the future, beyond "
    f"ordinary clock jitter ({SESSION_CLOCK_SKEW_TOLERANCE_SECONDS}s) - "
    "treating it as not-live rather than trusting a suspect timestamp"
)

#: What ``quiet`` says when an EARLIER ``session_end`` exists but a later
#: line supersedes it (T108 review finding 2) - this project resumes a
#: session under the SAME id (see ``hooks/keel_stop.py``'s own "a resumed
#: agent"), so an old end must not be allowed to read as the current state
#: once something newer has been recorded against the same identifier.
SESSION_STATE_QUIET_RESUMED_NOTE = (
    "no line for this session in over "
    f"{SESSION_LIVE_SECONDS}s; an earlier session_end is on record but a "
    "later line supersedes it, so this reads as a session that resumed "
    "under the same id and then went quiet - not as still being ended"
)

#: The fields a feed row shows, in this order, when ``detail_text`` builds its
#: one-line summary. ``detail`` and ``prompt_head`` are in the list because
#: the log carries them already redacted and the page used to drop them (T31).
DETAIL_FIELDS: tuple[str, ...] = (
    "tool",
    "action",
    "path",
    "description",
    "subagent_type",
    "gate",
    "reason",
    "agent_type",
    "target",
    "detail",
    "prompt_head",
)

#: What reading the selected ledger produced, and the sentence the page shows
#: for it. ``unreadable`` exists so that a listed ledger which could not be
#: opened can never be shown as an empty one - see "Failure policy".
PLAN_NOTES: dict[str, str] = {
    "none": "No ledger for this session yet.",
    "unreadable": (
        "This session's ledger is listed but could not be read - it may have been "
        "removed, locked or replaced since this page listed it. This is NOT an "
        "empty ledger, and the progress figure below is not a reading of one."
    ),
    "listing_failed": (
        "This project's ledger directory could not be listed - a permissions "
        "failure, a sharing violation or a transient I/O error, not an empty "
        "project. This is NOT the same as a project that has never been planned "
        "in, and the progress figure below is not a reading of any ledger."
    ),
    "empty": "This ledger carries no task lines yet.",
    "tasks": "",
}

#: One checkbox task line, anywhere in a ledger's Markdown. Matches the same
#: shape the client's own (pre-T31) parser used, so a ledger that rendered
#: correctly before still parses the same set of lines now.
_TASK_LINE_RE = re.compile(r"^\s*[-*]\s\[(.)\]\s*(.*)$")

#: The marker keel's own plan-contract treats as unambiguous (see T32 in
#: this repository's own ledger). Once a continuation line starts with this,
#: exactly, everything from there to the end of the task's block is its
#: acceptance criteria - which is where every ledger already places it,
#: after ``Route:`` and any ``Result:``.
_ACCEPT_MARKER = "Accept:"

#: WIRE NAMES a hand-off's two halves carry - see "WIRE NAMES" in
#: hooks/keel_capture.py. ``tool_use_id`` is the identifier a pair matches
#: on; the fallback fields are used only for a line old enough, or odd
#: enough, to carry none.
_HANDOFF_ID_FIELD = "tool_use_id"
_HANDOFF_FALLBACK_FIELDS: tuple[str, ...] = ("subagent_type", "description")

#: The ONE field on an ``activity`` line that says anything about who ran the
#: tool: ``hooks/keel_capture.py``'s ``action_record`` writes the subagent
#: type there, and leaves it empty for the main session's own work. There is
#: no ``tool_use_id`` on an activity line and no per-subagent session id, so
#: this is the whole of the record's evidence - and it is a type, never an
#: identity. See "What 'attributable' can mean here" in the module docstring.
_ACTIVITY_AGENT_FIELD = "agent_type"

#: Bound on how many hand-off nodes the delegation canvas draws (T4). One
#: session's whole history can run to dozens of closed hand-offs, and a
#: canvas that draws all of them stops being readable long before it stops
#: being honest. OPEN hand-offs are never dropped by this bound - they are
#: the point of the canvas - so it only ever trims the OLDEST CLOSED ones,
#: and whatever it trimmed is stated in ``graph["note"]`` rather than left
#: for a reader to notice, the same way ``EVENT_TAIL`` is a scroll limit
#: that changes nothing about who owns a line.
GRAPH_NODE_TAIL = 40

#: Bound on how many of the session's OWN lines the centre node's drawer
#: carries (T105). The main session is the busiest actor in any log - this
#: repository's own holds thousands of its lines - and a drawer is a recent
#: history, not an archive. Whatever this leaves out is COUNTED and stated in
#: words (``own_activity_note``), never trimmed silently, exactly as
#: ``GRAPH_NODE_TAIL`` and ``EVENT_TAIL`` already are.
OWN_ACTIVITY_TAIL = 50

#: The KINDs the drawer's rows name (T105), one per tool family the adapter
#: declares. ``action`` is the total case: a tool keel captured that is in
#: neither family cannot be called a write or a command, so it is called
#: neither. The page maps these three to a glyph and adds no fourth.
ACTION_KIND_WRITE = "write"
ACTION_KIND_COMMAND = "command"
ACTION_KIND_OTHER = "action"

#: What a drawer row says when the record holds the action but no target for
#: it - a write whose path the capture layer could not read, say. Absence is
#: expressed rather than shown as a blank row (convention 7).
NO_ACTION_TARGET_NOTE = "no target recorded on this line"

#: What the centre node IS, in one word, used by the node's own pill and by
#: the drawer's header (T105) so both name it the same thing. It is the
#: session the hand-offs on this canvas were made from - never a model, never
#: a tier, and never a claim about who or what answered.
ROOT_ROLE_LABEL = "session"

#: An agent type this page reads as a REVIEW hand-off, for the drawer's
#: summary line (T105). See ``is_review_handoff`` for the rule and for what
#: the count may therefore be called.
REVIEW_AGENT_PREFIX = "reviewer"

#: THE LEGEND BAR's role text (T119): what each of keel's OWN agents is for,
#: in one line each, keyed by the agent type the audit log actually records.
#:
#: SOURCE: the ``description:`` field of each ``agents/<name>.md`` frontmatter
#: in this repository, shortened to the agent's purpose. Those files are NOT
#: readable at runtime and nothing here tries to read them: this viewer opens
#: exactly two things under the surveyed project (see the contract at the top
#: of this file), and an INSTALLED keel's agent files live wherever the host
#: tool put them, outside the project entirely. So this is a hardcoded copy,
#: and it is DISPLAY-ONLY: no count, no filter, no match and no state on this
#: page is decided by it - it is a key to the legend's colours and nothing
#: else, which is why a line drifting out of date can mislead a reader but
#: can never make the page state a wrong figure. Real names only, exactly as
#: the record spells them; the page invents no persona for any of them.
AGENT_ROLES: dict[str, str] = {
    "keel:executor": "implements one scoped task at the standard tier",
    "keel:executor-deep": "the escalation tier - complex work, or one retry after review",
    "keel:researcher": "read-only scout: inventories files, answers with paths",
    "keel:reviewer-correctness": "checks a change against its own acceptance criteria",
    "keel:reviewer-security": "checks secrets, redaction, shell and dependencies",
    "keel:reviewer-silent-failure": "finds failure paths that would stay green when wrong",
    "keel:reviewer-tests": "checks that assertions pin the behaviour claimed",
    "keel:reviewer-altitude": "challenges the size of the solution",
}

#: What a legend row says for an agent type the ROSTER carries that
#: ``AGENT_ROLES`` has no line for - a host tool's own built-in
#: (``general-purpose``), a plugin's agent, or one added since. Never dropped
#: and never guessed at: the roster already shows the type, so the key to the
#: page's colours has to explain it, and the honest explanation is that keel
#: does not ship a purpose line for it.
LEGEND_UNKNOWN_ROLE = "not one of keel's own agents - no purpose line ships for it"

#: The colour families the legend's dots use, as TOKENS the page turns into
#: one css class each - decided here, like every other word and state on this
#: page, so a test reads a value rather than hunting a class name in markup.
#: Five: the two executor TIERS are told apart (they are different tiers and
#: the canvas is unreadable if they look alike), the reviewer FAMILY shares
#: one (one role at four angles), the scout has its own, and anything else is
#: neutral rather than borrowing a family it is not in.
AGENT_TONE_EXECUTOR = "exec"
AGENT_TONE_DEEP = "deep"
AGENT_TONE_RESEARCH = "scout"
AGENT_TONE_REVIEW = "review"
AGENT_TONE_OTHER = "other"

#: Bound on how many still-open items reach the page. In practice this is
#: never close to hit - a healthy project has a handful of open items at
#: most - but "no matching end" must not be able to grow the response
#: without bound if a log ever turns out to have many.
OPEN_TAIL = 200

#: Sent with EVERY response, read or refused (T27c). The page has exactly one
#: origin (itself), one inline ``<style>`` and one inline ``<script>``, and
#: loads nothing else - no CDN, no external font, no image, no frame - so
#: ``default-src 'none'`` can refuse everything BUT those two, named
#: explicitly, plus same-origin ``fetch`` for ``/api/state``/``/api/plan``.
SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    (
        "Content-Security-Policy",
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    ),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
)


class DashboardError(RuntimeError):
    """The viewer cannot run. The caller returns 2 (fail-closed)."""


# ------------------------------------------------------------------- readers


def plans_dir(project: Path) -> Path:
    """Where session ledgers live for a project."""
    return Path(project).joinpath(*PLANS_RELPATH)


def is_plan_name(name: str) -> bool:
    """True for a ledger basename of keel's own shape, and nothing else.

    Validated by SHAPE rather than by rejecting bad characters: a name must
    be exactly its own basename, carry the keel prefix and the ``.md``
    suffix, and have a non-empty middle with no path separator, no drive
    letter and no ``..`` in it. Anything else never reaches a path join.
    """
    if not name or name != os.path.basename(name):
        return False
    if not (name.startswith(PLAN_PREFIX) and name.endswith(PLAN_SUFFIX)):
        return False
    middle = name[len(PLAN_PREFIX) : -len(PLAN_SUFFIX)]
    if not middle or ".." in name or "/" in name or "\\" in name or ":" in name:
        return False
    return all(ch.isalnum() or ch in "-_" for ch in middle)


def read_plan(project: Path, name: str) -> str | None:
    """One ledger's text, redacted; ``None`` when the name or file is not ours.

    The name is validated before the join, so this function cannot be made to
    open a file outside ``.keel/plans/`` however the query string is spelled.
    """
    if not is_plan_name(name):
        return None
    path = plans_dir(project) / name
    try:
        return str(redact(path.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        return None


def plan_subject(text: str | None, session: str) -> str:
    """The selector's own label for one ledger (T107): the SUBJECT its
    heading already carries, or ``session`` itself when there is nothing
    truthful to say beyond the identifier.

    A ledger's heading is its FIRST line, by this project's own convention -
    every ``.keel/plans/keel-plan-*.md`` opens with one. ``text`` that is
    ``None`` or empty (the file could not be read, or listed but is empty)
    and text whose first line is not a markdown heading both mean there is
    no heading here to read, so ``session`` comes back unchanged rather than
    a guess built from a line that was never the heading.

    Once a heading is found, the parts of it that are the same on every
    ledger are trimmed away: the leading ``#``, the boilerplate
    ``PLAN_HEADING_PREFIX`` every plan opens with, and the ledger's own
    identifier - bare, or ``keel-plan-`` prefixed, exactly as an older
    ledger's heading spells it. What remains, once the punctuation that
    joined those parts together is trimmed from both ends too
    (``PLAN_SUBJECT_STRIP``), is the subject. A heading that reduces to
    nothing once its own boilerplate is gone - or that reduces to NOTHING
    BUT a bare date (``PLAN_SUBJECT_DATE_RE``; some ledgers carry only an
    identifier and the day they were opened) - is exactly as uninformative
    as no heading at all, and falls back to ``session`` the same way. A
    subject that merely CONTAINS a date among real words is untouched: only
    a residue that IS one, wholly, triggers the fallback.

    A subject longer than ``PLAN_SUBJECT_MAX`` is CUT, never wrapped: a
    ``<select>`` does not wrap an option, and a truncated subject still
    reads as what it is - nothing here invents a word the heading never
    carried.
    """
    first_line = text.splitlines()[0] if text else ""
    stripped = first_line.strip()
    if not stripped.startswith("#"):
        return session
    heading = stripped.lstrip("#").strip()
    if not heading:
        return session
    subject = heading
    if subject.startswith(PLAN_HEADING_PREFIX):
        subject = subject[len(PLAN_HEADING_PREFIX) :].strip()
    for identifier in (f"{PLAN_PREFIX}{session}", session):
        if identifier and subject.startswith(identifier):
            subject = subject[len(identifier) :]
            break
    subject = subject.strip(PLAN_SUBJECT_STRIP)
    if not subject or PLAN_SUBJECT_DATE_RE.fullmatch(subject):
        return session
    if len(subject) > PLAN_SUBJECT_MAX:
        subject = subject[: PLAN_SUBJECT_MAX - 1].rstrip() + "…"
    return subject


def list_plans(project: Path) -> tuple[list[dict[str, Any]], bool]:
    """``(found, listing_failed)`` (T36): every ledger in the project, newest
    first, name, subject and mtime, and whether LISTING the directory itself
    was a loss rather than the ordinary "no ledgers yet".

    ``FileNotFoundError`` is the one outcome this project's own law makes
    ordinary: a project is armed by its policy file alone
    (``keel_gate.policy_tier``), nothing in production creates
    ``.keel/plans/``, and the shipped templates ship none either - so an
    armed, never-planned-in project genuinely has no plans directory, and
    that is a fact, not a loss. Every OTHER ``OSError`` - a permissions
    failure, a sharing violation, a transient I/O error, or a plans path
    that exists as a FILE rather than a directory (which raises
    ``NotADirectoryError``, reachable on every platform and how this is
    tested) - means something is actually wrong where ledgers should be, so
    ``listing_failed`` comes back ``True`` and the caller must not render
    the ordinary "none" wording over it. A per-entry ``stat`` failure below
    is a smaller, already-handled loss: that entry degrades (``mtime`` is
    ``None``) without dropping its name from ``found``.

    ``subject`` (T107) is read through ``read_plan`` - the SAME function the
    ledger panel already reads a selected plan's text with, never a second
    file-reading path - and derived by ``plan_subject``. A ledger ``read_plan``
    cannot open degrades the same way a per-entry ``stat`` failure does: it
    keeps its name and falls back to it as its own subject too, rather than
    dropping out of ``found`` or being counted as a listing loss it is not.
    """
    found: list[dict[str, Any]] = []
    try:
        entries = sorted(plans_dir(project).iterdir())
    except FileNotFoundError:
        return found, False
    except OSError:
        return found, True
    for entry in entries:
        if not entry.is_file() or not is_plan_name(entry.name):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            mtime = None
        session = entry.name[len(PLAN_PREFIX) : -len(PLAN_SUFFIX)]
        found.append(
            {
                "name": entry.name,
                "session": session,
                "subject": plan_subject(read_plan(project, entry.name), session),
                "mtime": mtime,
            }
        )
    found.sort(key=lambda item: (item["mtime"] is not None, item["mtime"] or 0), reverse=True)
    return found, False


def parse_ledger_tasks(text: str) -> list[dict[str, Any]]:
    """Every checkbox task in a ledger, its title, and its ``Accept:`` text
    (T31) - the one parse the page's per-task acceptance list and its
    terminal-against-total progress figure (``ledger_progress``) both read,
    so there is one thing to keep correct rather than two that could drift.

    A task's block is its bullet line plus every line after it up to the
    next blank line or the next bullet, whichever comes first - matching how
    every ledger in this repository is actually written: one blank line
    between tasks, never one inside a task. ``Accept:`` is a marker keel's
    own plan-contract already treats as unambiguous; once a continuation
    line starts with it, that line and every line after it, to the end of
    the block, is the accept text - which is where every ledger already
    places it, after ``Route:`` and any ``Result:``. A ledger with no
    matching marker anywhere in a block yields an empty accept string for
    that task rather than raising - this is a read-only render, not a
    second copy of the plan-contract gate.
    """
    tasks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    accept_lines: list[str] = []
    in_accept = False

    def _flush() -> None:
        if current is not None:
            current["accept"] = " ".join(accept_lines).strip()
            tasks.append(current)

    for raw_line in text.splitlines():
        match = _TASK_LINE_RE.match(raw_line)
        if match:
            _flush()
            current = {"mark": match.group(1), "title": match.group(2).strip()}
            accept_lines = []
            in_accept = False
            continue
        stripped = raw_line.strip()
        if current is None:
            continue
        if not stripped:
            _flush()
            current = None
            accept_lines = []
            in_accept = False
            continue
        if in_accept:
            accept_lines.append(stripped)
            continue
        if stripped.startswith(_ACCEPT_MARKER):
            in_accept = True
            accept_lines.append(stripped[len(_ACCEPT_MARKER) :].strip())
        # else: a Route:/Result:/other continuation line before Accept: -
        # not the title, and not yet the acceptance criteria.
    _flush()
    return tasks


def fmt_duration(seconds: float | None) -> str:
    """A whole-second duration in the page's own vocabulary - ``"45s"``,
    ``"1m 0s"``, ``"2h 5m"`` - or ``"?"`` for one that is not known.

    Used for every duration THIS module decides (a quiet-time threshold, for
    instance). The page has a formatter of the same shape for the one kind of
    duration a server cannot decide - elapsed time at render against the
    reader's own wall clock - and nothing else.
    """
    if seconds is None:
        return "?"
    total = max(0, round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def document_title(counts: Mapping[str, Any]) -> str:
    """The exact string the tab carries (T29): the attention count in front
    of the page's own name, or just the name when nothing is open.

    Built here rather than in the page so that what a reader's tab SAYS is a
    value this module's tests can read directly.
    """
    attention = counts.get("attention") or 0
    return f"({attention}) {PAGE_TITLE}" if attention else PAGE_TITLE


def detail_text(row: Mapping[str, Any]) -> str:
    """One feed row's detail line, from the fields that row actually carries.

    Called with an ALREADY-REDACTED row (see ``read_state``), because this
    builds a string the page renders and every rendered value passes
    ``keel_redact`` first. A field that is absent or empty contributes
    nothing rather than an empty ``key=`` pair.
    """
    bits = [f"{field}={row[field]}" for field in DETAIL_FIELDS if row.get(field)]
    return "  ".join(bits)


#: T120: THE VERB per event KIND, and only these five. ``session_start``/
#: ``session_end`` are worded as plain statements by ``feed_sentence`` below,
#: not through this table, because no agent ran a session. A ``handoff_end``
#: is the LAUNCHING TOOL's own return - an acknowledgment, never a completion
#: (see [[a-recorded-end-is-not-a-finish]]) - so its verb never says
#: "finished"; only a matched ``subagent_stop`` may. Every other counted kind
#: (``activity``, ``gate_bypass``, ``override_active_at_stop``) has no entry
#: here and keeps the raw-name-plus-detail-line rendering the page already
#: had - this task invents no sentence for a kind the acceptance list never
#: named.
EVENT_VERBS: dict[str, str] = {
    "handoff_start": "launched",
    "handoff_end": "reported back",
    "subagent_stop": "finished",
    "gate_block": "blocked",
    "stop_block": "blocked",
}

#: Plain statements for the two kinds ``EVENT_VERBS`` does not cover: no
#: agent ran a session, so these never take the "Agent <verb>" shape.
SESSION_SENTENCES: dict[str, str] = {
    "session_start": "Session started",
    "session_end": "Session ended",
}


def feed_sentence(row: Mapping[str, Any]) -> str:
    """One flat feed row's SENTENCE, from the SAME already-redacted fields
    ``detail_text`` reads - no second event read, no second decision about
    what a kind means (T120).

    The actor is the record's OWN agent type - ``subagent_type`` on a
    hand-off record, ``agent_type`` on a stop (T31's own naming split,
    unchanged here) - where the record carries one, and the generic word
    "Agent" where it does not; the task is the record's own ``description``
    where it carries one and is left off, never invented, where it does not
    - a ``subagent_stop`` never carries one at all
    (``hooks/keel_hook.py``'s own ``cmd_subagent_stop`` contract), so it
    reads as "Agent finished" alone, the short sentence a task-less record
    earns. A kind neither table names returns ``""``, so the page falls back
    to the raw name it always showed (see ``evRow`` in the page's script).
    """
    kind = row.get("event")
    if kind in SESSION_SENTENCES:
        return SESSION_SENTENCES[kind]
    verb = EVENT_VERBS.get(kind) if isinstance(kind, str) else None
    if not verb:
        return ""
    agent = row.get("subagent_type") or row.get("agent_type")
    actor = f"{agent} agent" if agent else "Agent"
    task = row.get("description")
    return f"{actor} {verb} — {task}" if task else f"{actor} {verb}"


def feed_verb(row: Mapping[str, Any]) -> str:
    """Which VERB FAMILY a row's own kind belongs to (T120 addendum) - the
    one value the page's icon lookup keys off, read off the SAME ``event``
    field ``feed_sentence`` already reads, so the icon can never name a
    family the sentence beside it did not already state. ``"session"`` for
    the two session kinds, the verb string itself for a kind ``EVENT_VERBS``
    names, and ``""`` for every other kind - the identical three cases
    ``feed_sentence`` decides, never a second reading of what a kind means.
    """
    kind = row.get("event")
    if kind in SESSION_SENTENCES:
        return "session"
    return EVENT_VERBS.get(kind, "") if isinstance(kind, str) else ""


def ledger_progress(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """Terminal-against-total (T31): how many of ``tasks`` carry a mark
    ``hooks/keel_stop.py`` treats as needing no further proof, against how
    many tasks there are. An empty ledger reports ``0/0`` rather than
    dividing anywhere - the page decides how to word that, not this
    function.
    """
    terminal = sum(1 for task in tasks if task.get("mark") in TERMINAL_MARKS)
    return {"terminal": terminal, "total": len(tasks)}


def progress_label(progress: Mapping[str, Any]) -> str:
    """``"(1/2 terminal)"`` - or ``""`` where there is nothing to divide.

    The page shows this string and decides nothing about it: a ledger with no
    tasks, and a ledger that could not be read at all, must not be able to
    render as ``0/0`` merely because the page is where the wording lives.
    """
    total = progress.get("total") or 0
    if not total:
        return ""
    return f"({progress.get('terminal', 0)}/{total} terminal)"


def progress_tile(progress: Mapping[str, Any]) -> str:
    """``"3/5"`` - the header's TASKS DONE tile, from the ledger panel's OWN
    figure (T119).

    It is handed the SAME ``progress`` mapping ``ledger_progress`` already
    built for the panel, and it CANNOT count: there is no task list here, no
    second reading of ``TERMINAL_MARKS`` and no second walk of a ledger - it
    formats what it was given, which is what keeps the tile and the panel
    from ever stating different numbers (the same single-place rule T104 and
    T109 already hold this module to).

    It differs from ``progress_label`` above in exactly one way, and
    deliberately: where there is nothing to divide, that one returns ``""``
    so the panel's heading says nothing, and this one returns ``0/0``. A
    tile that vanished would leave the header with three of the reference's
    four boxes and no statement at all, and ``0/0`` is not itself a claim
    that a ledger was read - WHY it reads 0/0 (no ledger, an empty one, one
    that could not be read, a listing that failed) is the tile's own note,
    ``read_ledger``'s ``progress_tile_note``, which is the ledger state's
    own sentence rather than a second wording invented for the header.
    """
    return f"{progress.get('terminal', 0)}/{progress.get('total') or 0}"


def loss_note(counts: Mapping[str, Any]) -> str:
    """What the page says about what it could NOT read, or ``""``.

    Both losses are worded here, together, because they are the same
    statement: the record has a hole in it and the page must say so rather
    than render around it (convention 7). A corrupt audit line and a ledger
    that could not be opened are counted separately - they are different
    losses - and neither is allowed to look like an ordinary quiet project.
    ``counts.unreadable_plans`` carries EITHER of two distinct ledger losses
    (one listed ledger that could not be read, or the listing itself failing
    - T36's ``listing_failed``): different states with different sentences
    in ``plan.note``, folded into the one figure this coarser note counts.
    """
    bits = []
    lines = counts.get("unreadable_lines") or 0
    plans = counts.get("unreadable_plans") or 0
    if lines:
        bits.append(f"{lines} unreadable line(s)")
    if plans:
        bits.append(f"{plans} unreadable ledger(s)")
    return " · ".join(bits)


def withheld_note(counts: Mapping[str, Any]) -> str:
    """What the page says about hand-offs withheld as never-took, or ``""``.

    Kept OUT of ``loss_note`` on purpose: a withheld launch is not a loss -
    the log still holds every line, nothing here could not be read. It is a
    launch the record itself shows never took, held back from the canvas so
    it cannot be mistaken for a live agent. ``None`` is a THIRD, distinct
    fact from zero: the withholding rule could not run at all, so a ghost
    launch may still be showing as though it were live.
    """
    withheld = counts.get("withheld_launches")
    if withheld is None:
        return "withholding rule did not run - a ghost may still be showing"
    if withheld:
        return f"{withheld} launch(es) withheld as never-took"
    return ""


def read_ledger(project: Path, name: str, listing_failed: bool = False) -> dict[str, Any]:
    """The selected ledger as the page needs it, and WHICH outcome the read
    had - never a loss dressed as a fact (T31; see "Failure policy").

    ``read_plan`` answers ``None`` both for "not a ledger name of ours" and
    for an ``OSError`` - a file listed a moment ago and gone, locked or
    unreadable now. Collapsing that into ``""`` gave ``parse_ledger_tasks``
    an empty string, ``ledger_progress`` a ``0/0``, and the page the exact
    words it shows a project that simply has no ledger yet. So the outcome is
    named here (``state``), counted by the caller into
    ``counts.unreadable_plans`` the way a corrupt audit line is counted into
    ``counts.unreadable_lines``, and worded by ``PLAN_NOTES`` for the page:

    ``none``            this project lists no ledger at all;
    ``unreadable``      one is listed and the read FAILED - not an empty
                         ledger;
    ``listing_failed``  ``list_plans`` (T36) could not even list the ledger
                         DIRECTORY - a different loss again, and never the
                         ordinary "none" wording, even though ``name`` is
                         necessarily empty too;
    ``empty``           read fine, and it carries no task lines;
    ``tasks``           read fine, and here they are.

    ``listing_failed`` is the caller's own finding (``list_plans``'s second
    return value) and takes precedence over the ordinary empty-``name``
    "none" outcome below - a listing that failed can never have produced a
    name to select, so the two can never both be false at once here, but the
    words they lead to must not be interchangeable.
    """
    if listing_failed:
        text, state = "", "listing_failed"
    elif not name:
        text, state = "", "none"
    else:
        raw = read_plan(project, name)
        if raw is None:
            text, state = "", "unreadable"
        else:
            text, state = raw, ""
    tasks = parse_ledger_tasks(text)
    if not state:
        state = "tasks" if tasks else "empty"
    progress = ledger_progress(tasks)
    return {
        "name": name,
        "text": text,
        "state": state,
        "note": PLAN_NOTES[state],
        "tasks": [
            {"mark": task["mark"], "title": redact(task["title"]), "accept": redact(task["accept"])}
            for task in tasks
        ],
        "progress": progress,
        "progress_label": progress_label(progress),
        # T119: the header's TASKS DONE tile reads the SAME ``progress``
        # mapping the line above words for the panel - one count, two
        # renderings - and carries the ledger state's own sentence beside it
        # so a ``0/0`` tile is never mistaken for a ledger that was read and
        # found empty. ``PLAN_NOTES[state]`` is empty exactly when there ARE
        # tasks, which is the one case the panel's own label already words.
        "progress_tile": progress_tile(progress),
        "progress_tile_note": PLAN_NOTES[state] or progress_label(progress),
    }


def compute_roster(
    open_items: list[dict[str, Any]], groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Every agent type keel has delegated to: how many runs, and whether
    one is open right now (T31).

    A "run" is one hand-off, closed or open - ``groups`` holds the closed
    ones (one entry per matched pair; T27d already de-duplicates these) and
    ``open_items`` the ones still waiting on their ``handoff_end``. A
    session's own OPEN entry carries no agent type (T27's "empty means no
    delegation") and is not a run of anything, so it never reaches the
    roster. Sorted busiest-first, then by name, so the roster does not
    reorder itself between two reads of an unchanged log.

    Each entry also carries the ``label`` the page shows beside the agent's
    name, so working-or-idle is settled once, HERE, as a value a test can
    read - rather than by a template in the page that a test could only find
    by substring. This remains the ONE place that reading is settled: every
    chip's own ``working`` reads off THIS function alone, never a second
    working/idle judgement of its own - T109 taught this same function that a
    FINISHED ``open_handoff`` (T103's own ``delegation_state``: a
    ``subagent_stop`` matched it before its own ``handoff_end`` ever landed)
    is not working either, rather than adding a second rule beside this one
    that could drift from it.

    ``last_seen_ts`` and ``last_seen_kind`` (T104) - the most recent moment a
    RESTING agent type's record can honestly point to, and what that moment
    actually IS, because the two disagree for most of this project's own
    hand-offs (see the module docstring's BACKGROUND/AWAITED/FINISHED
    section and [[a-recorded-end-is-not-a-finish]]). A closed group's
    ``finished_ts`` (T101/T103's ``subagent_stop`` match, via
    ``_match_finish_events``) is a genuine end, so when it is set that group
    contributes it with kind ``"finished"``. Absent that, all a group has is
    ``end_ts`` - ``handoff_end``, the LAUNCHING TOOL's own return, not the
    work's - so it contributes that instead with kind ``"launched"``, never
    ``"finished"``: a card that called a launch acknowledgment a finish would
    be wrong for exactly the delegations this project runs most (the same
    honesty rule T103's pill already keeps). A FINISHED ``open_handoff``
    (T109) contributes its own ``finished_ts`` the same way a closed group's
    does - it is exactly as genuine an end, the record simply never got a
    ``handoff_end`` acknowledgment for it - through the SAME comparison
    (``_consider_last_seen``), never a second one. Across a type's
    contributions the NEWEST timestamp wins (ISO-8601 UTC strings sort
    lexicographically), and whichever kind travelled with it is what the page
    states beside it - so the word on screen and the record it names can
    never point at different events. A page renders this only for a RESTING
    entry; a working one has no honest "last" to state while a hand-off of
    its type is genuinely still open.
    """
    roster: dict[str, dict[str, Any]] = {}

    def _bucket(agent: Any) -> dict[str, Any] | None:
        text = agent.strip() if isinstance(agent, str) else ""
        if not text:
            return None
        return roster.setdefault(
            text,
            {
                "agent_type": text,
                "runs": 0,
                "working": False,
                "last_seen_ts": None,
                "last_seen_kind": None,
            },
        )

    def _consider_last_seen(entry: dict[str, Any], candidate_ts: Any, candidate_kind: str) -> None:
        if candidate_ts and (
            entry["last_seen_ts"] is None or candidate_ts > entry["last_seen_ts"]
        ):
            entry["last_seen_ts"] = candidate_ts
            entry["last_seen_kind"] = candidate_kind

    for group in groups:
        entry = _bucket(group.get("subagent_type"))
        if entry is None:
            continue
        entry["runs"] += 1
        finished_ts = group.get("finished_ts")
        if finished_ts:
            _consider_last_seen(entry, finished_ts, "finished")
        else:
            _consider_last_seen(entry, group.get("end_ts"), "launched")
    for item in open_items:
        if item.get("row_kind") != "open_handoff":
            continue
        entry = _bucket(item.get("agent_type"))
        if entry is None:
            continue
        entry["runs"] += 1
        # T109: a `subagent_stop` matched this hand-off before its own
        # `handoff_end` ever did (T103's `delegation_state == "finished"`) -
        # the same real end a closed group's own FINISHED state already
        # means, so it is RESTING with a real last-seen, never WORKING. Any
        # other open_handoff state (OPEN, or the near-instant BACKGROUND gap
        # this field never carries) has no real end on record, so it is the
        # one thing that still sets `working`.
        if item.get("delegation_state") == "finished":
            _consider_last_seen(entry, item.get("finished_ts"), "finished")
        else:
            entry["working"] = True

    ordered = sorted(roster.values(), key=lambda entry: (-entry["runs"], entry["agent_type"]))
    for entry in ordered:
        entry["state"] = "working" if entry["working"] else "resting"
        entry["label"] = f"{entry['state']} · {entry['runs']} run(s)"
    return ordered


def read_events(project: Path) -> tuple[list[dict[str, Any]], int]:
    """``(events, unreadable_lines)`` from the append-only audit log.

    ``keel_events.read_audit`` drops a corrupt line silently, which is right
    for a gate and wrong for a viewer: here the loss is counted so the page
    can say the log has a hole in it (convention 7).
    """
    events: list[dict[str, Any]] = []
    lost = 0
    try:
        with open(audit_path(project), encoding="utf-8", errors="replace") as handle:
            raw_lines = handle.readlines()
    except OSError:
        return events, lost
    for line in raw_lines:
        line = line.strip()
        if not line:
            continue
        try:
            decoded = json.loads(line)
        except ValueError:
            lost += 1
            continue
        if isinstance(decoded, dict):
            events.append(decoded)
        else:
            lost += 1
    return events, lost


#: The two hand-off halves this viewer withholds by the T138 rule. Named
#: here because the filter below drops whole lines, and a filter that could
#: silently start matching a third kind is not a filter anyone can check.
_WITHHOLDABLE_EVENTS = ("handoff_start", "handoff_end")


def _withhold_never_took(
    events: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], int | None]:
    """``(served events, how many lines were withheld)`` - T143.

    THE RULE LIVES IN ONE PLACE, and that place is the adopted board's
    ``unacknowledged_launch_ids`` (T138), which cost a retry to get right and
    is pinned by its own tests. This function imports it rather than
    restating it: the sibling module already imports THIS one for ``arming``
    and ``session_liveness``, so the import here is deliberately LAZY - done
    inside the call, when both modules are certainly loaded, whichever of the
    two an outside caller imported first.

    (The alternative - moving the rule into this module and importing it the
    other way - was weighed and declined: it would relocate a fail-sensitive
    rule for no behavioural gain, and the ordering hazard it avoids is the
    one a local import already answers.)

    NEVER RAISES. A viewer that cannot reach the rule serves the log exactly
    as it reads it - four ghosts and all, the state of affairs before this
    function existed - rather than failing a request; that fail-open
    behaviour does not change here. What changes is the second element of
    the tuple: a run that reached the rule and withheld nothing returns
    ``0``, but a run that never reached the rule - the import failed, the
    upstream call raised - returns ``None``, the same idiom ``model_of``
    uses in ``hooks/keel_session.py`` for "the harness said nothing" versus
    "keel never looked". ``0`` and ``None`` must stay two different values
    here: a counter that reads ``0`` for both "the filter ran and found no
    ghosts" and "the filter could not run at all" would let a broken import
    serve phantom launches as live agents while claiming, confidently, that
    nothing was withheld. The fault is also never silent (convention 7): one
    stderr line names it, in the same shape this project's other fail-open
    paths already use (see ``hooks/keel_liveview.py`` and
    ``hooks/keel_session.py``).
    """
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        from keel_orchestration_dashboard import (  # noqa: PLC0415
            unacknowledged_launch_ids,
        )

        handoffs = [e for e in events if e.get("event") in _WITHHOLDABLE_EVENTS]
        withheld = unacknowledged_launch_ids(handoffs)
    except Exception as exc:  # noqa: BLE001 - fail-open, but never silent
        print(
            f"keel: never-took filter unavailable, showing the log as read: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return events, None
    if not withheld:
        return events, 0
    served = [
        e
        for e in events
        if not (
            e.get("event") in _WITHHOLDABLE_EVENTS
            and e.get("tool_use_id") in withheld
        )
    ]
    return served, len(events) - len(served)


def arming(project: Path) -> dict[str, Any]:
    """Tier and armed state, or the reason neither could be read."""
    try:
        tier = policy_tier(Path(project))
    except GateError as exc:
        return {"tier": None, "armed": False, "note": str(exc)}
    return {"tier": tier, "armed": tier is not None and tier >= 2, "note": ""}


def _session_of(entry: Mapping[str, Any]) -> Any:
    """Session identifier of an audit line, under either accepted key."""
    return entry.get("session", entry.get("session_id"))


def _epoch_seconds(ts: Any) -> float | None:
    """An audit line's ISO-8601 ``ts`` as epoch seconds, or ``None``.

    keel writes UTC with a trailing ``Z``, which ``fromisoformat`` only
    accepts from Python 3.11; the suffix is normalised so 3.10 parses it
    too. Anything that fails to parse is absence, never an invented time -
    a malformed line must never be able to open or close a pair by accident.
    """
    if not isinstance(ts, str) or not ts.strip():
        return None
    text = ts.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.timestamp()


def _session_liveness_note(state: str, future_dated: bool, resumed_past_an_end: bool) -> str:
    """The sentence under the pill (T108), naming the ONE thing beyond the
    plain wording that could otherwise mislead a reader about ``quiet``:
    that the newest evidence is future-dated (finding 1) rather than absent,
    or that an earlier ``session_end`` on record has been superseded by a
    resumed session's own later activity (finding 2) rather than simply
    never having existed. Neither ever fires for ``live``, ``ended`` or
    ``none`` - those three already say everything the record supports in
    their own plain wording."""
    if state == SESSION_STATE_QUIET:
        if future_dated:
            return SESSION_STATE_FUTURE_NOTE
        if resumed_past_an_end:
            return SESSION_STATE_QUIET_RESUMED_NOTE
    return SESSION_STATE_NOTES[state]


def session_liveness(
    events: list[Mapping[str, Any]], session: str, now: float
) -> dict[str, Any]:
    """Whether ``session`` reads as LIVE or historical (T108), decided here
    so a test can read the VALUE rather than a template the page assembles.

    ``session`` is expected to be the SAME full session id ``compute_graph``
    already resolved as ``graph["session"]`` - never re-derived from a
    ledger's own filename, which carries only ``sess8`` (the first 8
    characters of the id, see ``KeelEvent.sess8`` in
    ``hooks/keel_events.py``) and can never equal a raw audit line's own
    ``session`` field by plain string equality.

    ``ended`` wins outright, however old or new that line is, but ONLY when
    the ``session_end`` line is itself the NEWEST evidence this module can
    find for ``session`` (T108 review finding 2). This project resumes a
    session under the SAME id (see ``hooks/keel_stop.py``'s own "a resumed
    agent"), so ``session_start(S)`` -> ``session_end(S)`` -> resume ->
    fresh ``activity(S)`` is a real sequence this record can hold, and an
    end that a later line supersedes must not go on winning outright - that
    would hide live work behind the calmest label this function has. Once a
    later line supersedes it, the verdict falls through to the age rule
    below exactly as if no end had been recorded, and the note says the
    earlier end was superseded rather than pretending it never happened.

    Short of an undisputed end, the newest ``ts`` this module can find for
    ``session`` is compared against ``now`` and ``SESSION_LIVE_SECONDS``:
    within the window is ``live``; past it, or no line at all for
    ``session``, is ``quiet`` - never ``ended``, because a KILLED session
    never writes ``session_end`` and this function must not claim proof the
    record does not carry.

    A newest line dated in the FUTURE beyond
    ``SESSION_CLOCK_SKEW_TOLERANCE_SECONDS`` is never read as live (T108
    review finding 1): ordinary jitter within that tolerance still clamps to
    age zero exactly as before, but clock skew or a corrupted timestamp
    beyond it is suspect evidence, not proof of freshness, and reads
    ``quiet`` with its own note naming why.

    An empty ``session`` (nothing selected, or nothing to select) is its own
    fourth state, ``none``, rather than falling through to ``quiet``'s
    wording, which would claim a session existed and went silent.
    """
    future_dated = False
    resumed_past_an_end = False
    if not session:
        state = SESSION_STATE_NONE
    else:
        newest_ts: str | None = None
        newest_end_ts: str | None = None
        for entry in events:
            if _session_of(entry) != session:
                continue
            ts = entry.get("ts")
            if not isinstance(ts, str):
                continue
            if newest_ts is None or ts > newest_ts:
                newest_ts = ts
            if entry.get("event") == "session_end" and (
                newest_end_ts is None or ts > newest_end_ts
            ):
                newest_end_ts = ts
        # FINDING 2: an end only wins when nothing newer than it was
        # recorded for this session - equal to the overall newest line, not
        # merely present somewhere in its history.
        ended = newest_end_ts is not None and newest_end_ts == newest_ts
        resumed_past_an_end = newest_end_ts is not None and not ended
        if ended:
            state = SESSION_STATE_ENDED
        else:
            epoch = _epoch_seconds(newest_ts) if newest_ts else None
            if epoch is None:
                state = SESSION_STATE_QUIET
            else:
                raw_age = now - epoch
                # FINDING 1: a future-dated newest line beyond ordinary
                # clock jitter is suspect evidence, never proof of
                # liveness - `max(0.0, raw_age)` alone let ANY future
                # timestamp clamp to age zero and read live forever.
                future_dated = raw_age < -SESSION_CLOCK_SKEW_TOLERANCE_SECONDS
                age = max(0.0, raw_age)
                state = (
                    SESSION_STATE_QUIET
                    if future_dated or age > SESSION_LIVE_SECONDS
                    else SESSION_STATE_LIVE
                )
    return {
        "session": session,
        "state": state,
        "label": SESSION_STATE_LABELS[state],
        "note": _session_liveness_note(state, future_dated, resumed_past_an_end),
    }


def _pair_starts_ends(
    starts: list[dict[str, Any]],
    ends: list[dict[str, Any]],
    id_field: str | None,
    fallback_fields: tuple[str, ...],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]]]:
    """Match ``starts`` to ``ends`` by IDENTITY, never by counting kind
    against kind (T27b) - a session that started twice and ended once must
    not read as "50% open".

    A start with a truthy ``id_field`` value matches the end carrying the
    SAME value; a start with none, or whose value matches no end, falls
    back to FIFO order within its ``fallback_fields`` key. This is the same
    two-step match ``hooks/keel_stop.py`` uses to pair a hand-off's
    ``tool_use_id`` (or, absent one, its ``subagent_type``/``description``).
    Session/session pairing calls this with an empty ``fallback_fields``, so
    every entry shares one FIFO bucket - correct because the caller has
    already scoped both lists to a single session.

    Both lists are expected in their original (chronological) order.
    Returns ``(pairs, open_starts)`` - every start left unmatched.
    """
    ends_by_id: dict[Any, list[dict[str, Any]]] = {}
    ends_fifo: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for end in ends:
        value = end.get(id_field) if id_field else None
        if value:
            ends_by_id.setdefault(value, []).append(end)
        else:
            key = tuple(end.get(field) for field in fallback_fields)
            ends_fifo.setdefault(key, []).append(end)

    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    open_starts: list[dict[str, Any]] = []
    for start in starts:
        value = start.get(id_field) if id_field else None
        bucket = ends_by_id.get(value) if value else None
        if bucket:
            pairs.append((start, bucket.pop(0)))
            continue
        key = tuple(start.get(field) for field in fallback_fields)
        fifo_bucket = ends_fifo.get(key)
        if fifo_bucket:
            pairs.append((start, fifo_bucket.pop(0)))
            continue
        open_starts.append(start)
    return pairs, open_starts


class _Window(NamedTuple):
    """One closed hand-off as the attribution pass sees it.

    ``agent`` is the ``subagent_type`` the pair was opened with, matched
    against an activity line's ``agent_type``; ``order`` is the pair's index
    within its session, used only to break a tie deterministically.
    """

    lo: float
    hi: float
    order: int
    agent: Any
    group: dict[str, Any]


class _Attribution(NamedTuple):
    """What one pass over a session's lines decided (T105).

    ``consumed`` is the ``id()`` of every line folded into some group.
    ``own`` is the other half of the SAME decision: the lines rule (1)
    declined because their ``agent_type`` was empty - the main session's own
    work, in log order. Two names for one walk, so the centre node's drawer
    and the collapsed groups cannot be built from two different readings of
    who ran a line (see "The centre node's own panel" in the module
    docstring).
    """

    consumed: set[int]
    own: list[dict[str, Any]]


def _attribute_activity(
    session_events: list[dict[str, Any]],
    windows: list[_Window],
) -> _Attribution:
    """Give each ``activity`` line AT MOST ONE owning delegation.

    The loop is over LINES, not over hand-offs, and that is the point: each
    line picks one owner, so no second hand-off can claim a line a first one
    already took. Two overlapping delegations cannot duplicate a line into
    both of their blocks, because no line is ever offered twice.

    The rule, in the order the record can support it (see the module
    docstring):

    1. An empty ``agent_type`` is the MAIN SESSION's own work. It belongs to
       no delegation and is never folded into one, however many hand-offs
       were open around it - burying the orchestrator's own edit inside a
       subagent's block would be the viewer inventing an author.
    2. Otherwise only hand-offs whose ``subagent_type`` EQUALS that
       ``agent_type`` are candidates: a ``keel:researcher`` line did not come
       from the ``keel:executor`` running beside it. This is a fact.
    3. Containment then narrows the candidates to those actually in flight
       at that instant. This is also a fact, but on its own it is not an
       answer.
    4. If exactly one candidate survives, attribution is KNOWN. If more than
       one does - concurrent hand-offs OF THE SAME TYPE - the record cannot
       say which, so the most recently started enclosing hand-off is chosen
       (``hooks/keel_stop.py`` bounds a launch's activity by the next start
       of its own type the same way, and a nested delegation is the more
       likely author of a line than the one that spawned it), the choice is
       counted into ``group["inferred"]`` and the line is remembered in
       ``group["inferred_ids"]``. The page marks both. Nothing here decides
       an inference is a reading of the log.

    Returns both halves of that decision (``_Attribution``): the ``id()`` of
    every line folded into some group, and the lines rule (1) declined. The
    early return this used to take when a session had no closed hand-off at
    all is gone deliberately - it would have skipped rule (1) as well, and a
    session that delegated nothing is exactly the one whose own work there is
    most of. With no windows the loop still reaches every line and simply
    finds no candidate for any of them, which is the same answer.
    """
    consumed: set[int] = set()
    own: list[dict[str, Any]] = []
    for entry in session_events:
        if entry.get("event") != ROUTINE_EVENT:
            continue
        raw_agent = entry.get(_ACTIVITY_AGENT_FIELD)
        agent = raw_agent.strip() if isinstance(raw_agent, str) else ""
        if not agent:
            # (1) main-session work: no delegation ran it. Collected, never
            # consumed - the flat feed still owns this line (T105).
            own.append(entry)
            continue
        when = _epoch_seconds(entry.get("ts"))
        if when is None:
            continue  # an unparseable time cannot be placed inside anything
        # T143: both sides of this comparison go through ``_agent_text``.
        # They did not before: the activity side was normalised and the
        # window side held whatever the record wrote, so a type that differed
        # only in surrounding whitespace could never claim its own lines.
        # MEASURED before changing (253 hand-off starts in this project's
        # log): 247 clean strings, 6 null, zero padded and zero non-string -
        # so the asymmetry was latent rather than active, and this closes it
        # before a record with a stray space makes it real.
        #
        # AND AN UNNAMED TYPE STILL CLAIMS NOTHING - now by rule, where it
        # used to be by accident. Normalising both sides makes a null window
        # and a blank activity line compare EQUAL, and the six null-typed
        # hand-offs would have started claiming the main session's own 1246
        # unattributed lines. Rule (1) above happens to filter those lines
        # first; this guard means the outcome no longer depends on that
        # happening to stay true.
        candidates = [
            window
            for window in windows
            if _agent_text(window.agent)
            and _agent_text(window.agent) == agent
            and window.lo <= when <= window.hi  # (2), (3)
        ]
        if not candidates:
            continue
        chosen = max(candidates, key=lambda window: (window.lo, window.order))  # (4)
        chosen.group["events"].append(entry)
        if len(candidates) > 1:
            chosen.group["inferred"] += 1
            chosen.group["inferred_ids"].add(id(entry))
        consumed.add(id(entry))
    return _Attribution(consumed, own)


def _agent_text(value: Any) -> str:
    """An ``agent_type``/``subagent_type`` field as the one string both sides
    of an attribution comparison use. Absent, non-string or blank all mean
    the same thing here: no type was named."""
    return value.strip() if isinstance(value, str) else ""


def _unclaimed_activity(
    session_events: list[dict[str, Any]],
    consumed: set[int],
    agent_text: str,
) -> list[dict[str, Any]]:
    """Every ``activity`` line of one agent type that no CLOSED delegation
    has already taken - the only lines an OPEN hand-off of that type could
    possibly claim (T30).

    Anything folded into a closed delegation's group already belongs to that
    group, and letting an open item read it too would let one line answer for
    two hand-offs at once - the one thing T27d's exactly-once accounting
    forbids everywhere else, so it is not reintroduced here for a secondary
    signal. A line is never marked consumed for having been read this way:
    the activity a still-open hand-off produced stays in the flat feed exactly
    as it does today (T27), because nothing has closed it yet.
    """
    if not agent_text:
        return []
    return [
        entry
        for entry in session_events
        if id(entry) not in consumed
        and entry.get("event") == ROUTINE_EVENT
        and _agent_text(entry.get(_ACTIVITY_AGENT_FIELD)) == agent_text
    ]


def _quiet_facts(
    candidates: list[dict[str, Any]],
    start_ts: Any,
    rival_ts: list[Any],
) -> tuple[Any, str, bool, dict[str, Any] | None]:
    """``(last_seen_ts, phase, ambiguous, last_entry)`` for ONE open item
    (T30; ``last_entry`` added by T103).

    ``candidates`` are the lines this item could conceivably claim (for a
    hand-off, ``_unclaimed_activity`` of its own agent type; for a session,
    every line recorded under that session). ``rival_ts`` is the start ``ts``
    of every OPEN item competing for exactly those lines - including this
    one's own - which for hand-offs means every still-open hand-off of the
    SAME agent type, because that field is a TYPE and cannot tell two of them
    apart (see the module docstring).

    Two bounds, both facts, and then a refusal:

    1. a line BEFORE this item's own start was not produced by it - an item
       cannot have caused something that had already happened;
    2. a line is this item's only if, at the instant it was recorded, this
       item was the ONLY rival already open. Where two rivals were open, the
       record does not say which produced it, so NEITHER claims it: the item
       falls back to its own start, which reads as ``"tool_running"`` and the
       long threshold - honest, where borrowing a sibling's evidence would
       report an item as freshly active on work it may never have done;
    3. that refusal is REPORTED, never silent: ``ambiguous`` is ``True`` when
       at least one line had to be declined, and ``quiet_note`` says so in
       words - the same thing ``group["inferred"]`` says on the grouping side.

    ``last_seen_ts`` is the ORIGINAL ``ts`` string, never a derived value.
    An unparseable start means nothing can be bounded against it, so nothing
    is claimed at all. ``last_entry`` is the SAME winning candidate
    ``last_seen_ts`` was read off, not a second search - T103's last-action
    line reads its own ``detail`` field from it rather than re-scanning.
    """
    own = _epoch_seconds(start_ts)
    if own is None:
        return start_ts, "tool_running", False, None
    parsed = [_epoch_seconds(value) for value in rival_ts]
    rivals = [when for when in parsed if when is not None]
    # A rival whose own start cannot be read cannot be placed in time either,
    # so it can never be ruled OUT of having produced a line - it counts as
    # open throughout. One malformed start line therefore costs this signal
    # for its type rather than buying it a claim it cannot support.
    unplaceable_rivals = sum(1 for when in parsed if when is None)
    best_epoch: float | None = None
    best_ts: Any = None
    best_entry: dict[str, Any] | None = None
    ambiguous = False
    for entry in candidates:
        when = _epoch_seconds(entry.get("ts"))
        if when is None or when <= own:
            continue  # (1) before (or at) this item's own start
        if unplaceable_rivals or sum(1 for rival in rivals if rival <= when) > 1:
            ambiguous = True  # (2)/(3) more than one open item could have run it
            continue
        if best_epoch is None or when > best_epoch:
            best_epoch, best_ts, best_entry = when, entry.get("ts"), entry
    if best_ts is None:
        return start_ts, "tool_running", ambiguous, None
    return best_ts, "between_calls", ambiguous, best_entry


def quiet_threshold_seconds(phase: str) -> int:
    """How long an item in ``phase`` may be quiet before the page says so.

    The choice between the two named constants is made HERE, once, so that
    the threshold a label claims to have crossed is a value a test can read
    rather than a constant the page keeps its own copy of.
    """
    if phase == "between_calls":
        return QUIET_BETWEEN_CALLS_SECONDS
    return QUIET_TOOL_RUNNING_SECONDS


def quiet_note(phase: str, ambiguous: bool, agent: Any = None, kind: str = "hand-off") -> str:
    """The words a crossed quiet-time threshold is stated in (T30; the
    ``between_calls``+``ambiguous`` wording is T37).

    Four cases, because the page must not word an inference as a reading,
    and must not let one true fact drown out another:

    - ``tool_running``, not ambiguous: genuinely nothing recorded since it
      started;
    - ``between_calls``, not ambiguous: attributed something, quiet since;
    - ``tool_running``, ambiguous: nothing was EVER attributed to this item
      (``_quiet_facts`` never found a claimable line before the decline), so
      "nothing this one can claim" is the whole truth;
    - ``between_calls``, ambiguous: BOTH facts are true at once and the
      sentence must say both - this item DID claim an earlier line
      (``last_seen_ts`` is later than its own start, which is exactly what
      ``between_calls`` means), and it also DECLINED at least one later line
      because more than one open item of the same type could have produced
      it. Saying only "nothing this one can claim" here would contradict the
      row's own ``last_seen_ts`` sitting right next to it.
    """
    threshold = fmt_duration(quiet_threshold_seconds(phase))
    who = f"{agent} {kind}" if agent else kind
    if ambiguous and phase == "between_calls":
        return (
            f"no new tool call for {threshold} since the line it already claimed - "
            f"later lines were declined too: more than one {who} was open when they "
            "landed, and the record names the agent type, not which one ran them"
        )
    if ambiguous:
        return (
            f"nothing this one can claim for {threshold} - more than one {who} was "
            "open when the later lines landed, and the record names the agent type, "
            "not which one ran them"
        )
    if phase == "between_calls":
        return f"no new tool call for {threshold}"
    return f"no event since it started, past {threshold} - a slow command is not a stall"


#: The pill's own word for each of T103's three new states. FINISHED carries
#: a glyph the other two never do - a reader must tell it apart without
#: reading either word (see the module docstring) - and neither glyph nor
#: word is shared with a dimmed copy of the running pill.
DELEGATION_STATE_LABELS: dict[str, str] = {
    "background": "background",
    "awaited": "awaited",
    "finished": "✓ finished",
}


def delegation_state_label(state: Any) -> str:
    """One hand-off's pill text (T103): one of the three words above, or the
    pre-existing ``"open"`` wording for a hand-off with no ``handoff_end`` at
    all and no matching ``subagent_stop`` - T4/T30's OPEN case, unrenamed."""
    return DELEGATION_STATE_LABELS.get(state, "open")


#: What a BACKGROUND card states under its pill (T103) - the honesty rule
#: [[a-recorded-end-is-not-a-finish]] names, in words on the card rather than
#: left for a reader to infer from an elapsed figure that looks like "done".
BACKGROUND_STATE_NOTE = "the record cannot yet say it ended"


def delegation_state_note(state: Any) -> str:
    """The one sentence a BACKGROUND card adds under its pill; every other
    state adds none - AWAITED and FINISHED both carry a real end, and OPEN
    already says everything the record can support via its own wording."""
    return BACKGROUND_STATE_NOTE if state == "background" else ""


def _delegation_state(has_end: bool, gap_ms: float | None, finished: bool) -> str:
    """BACKGROUND, AWAITED, FINISHED, or the pre-existing OPEN, for one
    hand-off (T103's whole distinction).

    ``finished`` wins outright: a ``subagent_stop`` is the one thing this
    project treats as a genuine end, so a delegation matched to one reads
    FINISHED whether or not it also got a quick ``handoff_end``
    acknowledgment. Short of that, a hand-off with no ``handoff_end`` at all
    is the pre-existing OPEN case, unrenamed. Only once a return has actually
    arrived, WITH A READABLE GAP, does that gap against ``BG_LAUNCH_MS``
    decide BACKGROUND (a launch acknowledgment) from AWAITED (the session was
    genuinely blocked on it, so the return already marks the end). An
    unparseable pair (``gap_ms is None``) fails toward BACKGROUND rather than
    AWAITED - the same direction ``hooks/keel_stop.py`` already fails in for
    the identical case ("background launch, or unparseable pair") - because
    AWAITED is the stronger claim (a genuine, confirmed end) and this module
    never asserts the stronger claim from a pair it could not actually read.
    """
    if finished:
        return "finished"
    if not has_end:
        return "open"
    if gap_ms is not None and gap_ms >= BG_LAUNCH_MS:
        return "awaited"
    return "background"


def _match_finish_events(
    starts: list[dict[str, Any]],
    ends: list[dict[str, Any]],
    stops: list[dict[str, Any]],
) -> dict[int, Any]:
    """``id(start) -> the finishing subagent_stop's own ts``, for every
    ``start`` a stop actually closes (T103, built on T101's subscription).

    NO LONGER AN IMPLEMENTATION - A CALL. This function was admitted on
    2026-08-11 as a PROVISIONAL third way of matching one stop to one
    delegation, beside ``hooks/keel_stop.py``'s closing loop and
    ``scripts/keel_attest.py``'s ``resolve_handoffs``, on the grounds that a
    viewer must read the event to draw it and no shared join existed yet to
    read it with. T102 built one, so the concession is spent: everything below
    is bookkeeping around ``keel_stop.match_stops_to_launches``, which is the
    same object the gate and the report call. A provisional third reader that
    survives its own justification is just drift with a docstring.

    THE ONLY WORK LEFT HERE is turning this module's shapes into that
    function's: the agent id of a delegation lives on its RETURN, because the
    launch tool only names the agent once it has returned one, so each start
    is resolved to its ``handoff_end`` by ``tool_use_id`` and the pair is
    handed to ``keel_stop.launch_agent_id``. That resolution is deliberately
    BY ID ALONE and does not reuse ``_pair_starts_ends``' FIFO fallback: a
    fallback that keys on ``(subagent_type, description)`` pairs two records
    that name neither, and an id lifted from a wrongly-paired return would be
    a false join wearing an exact key's clothes.

    Deliberately NON-MUTATING: unlike ``resolve_handoffs``, this never writes
    a private key onto a raw audit entry, because a ``start``/``stop`` dict
    here is the SAME object the flat feed and the collapsed group render - an
    extra key on it would be new information invented by this viewer rather
    than read from the record, one JSON response away from leaking into it.
    Returning ``id(start) -> ts`` rather than the shared matcher's index map
    is that rule, not a second algorithm.

    THE LIMIT THIS USED TO DISCLOSE IS GONE. Two hand-offs of one type open at
    once are now told apart, because a stop names the agent and not merely its
    kind. What replaces it is the rule every reader of this log now shares: a
    stop that names no launch on record - and a launch no return has yet named
    - matches nothing, and the card stays as it was rather than being finished
    by a guess.
    """
    ends_by_id: dict[str, dict[str, Any]] = {}
    for end in ends:
        tool_use_id = end.get(_HANDOFF_ID_FIELD)
        if isinstance(tool_use_id, str) and tool_use_id.strip():
            ends_by_id[tool_use_id.strip()] = end

    agent_ids: list[str | None] = []
    for start in starts:
        tool_use_id = start.get(_HANDOFF_ID_FIELD)
        end = (
            ends_by_id.get(tool_use_id.strip())
            if isinstance(tool_use_id, str) and tool_use_id.strip()
            else None
        )
        agent_ids.append(launch_agent_id(start, end))

    matched = match_stops_to_launches(
        agent_ids, sorted(stops, key=lambda entry: entry.get("ts") or "")
    )
    return {id(starts[index]): stop.get("ts") for index, stop in matched.items()}


def _finished_span(start_ts: Any, finished_ts: Any) -> float | None:
    """Seconds between a hand-off's own start and the ``subagent_stop`` that
    finished it (T103) - the one honest total a card may state as a fixed
    number rather than a live-ticking guess, because a real end is now on
    record."""
    start, finish = _epoch_seconds(start_ts), _epoch_seconds(finished_ts)
    if start is None or finish is None:
        return None
    return abs(finish - start)


def _action_detail_text(entry: Any) -> str:
    """One activity line's already-redacted ``detail`` field, or ``""``
    (T103) - the single place both the open-item and the closed-group
    last-action lines read this field from, so neither can drift from what
    the other calls "no action to show". ``entry`` may be ``None`` (an item
    with nothing attributable yet) or any non-mapping payload value; both
    mean the same thing here.
    """
    if not isinstance(entry, Mapping):
        return ""
    text = entry.get("detail")
    return text.strip() if isinstance(text, str) else ""


def _last_action_text(events: list[dict[str, Any]]) -> str:
    """The reference's small last-action line for a CLOSED group (T103): the
    LAST attributed line's own ``detail`` - reusing the SAME attribution the
    collapsed group's own ``events`` list already carries, never a second
    computation. An empty list, or a last line with nothing in ``detail``,
    means omit the line rather than guess one."""
    return _action_detail_text(events[-1]) if events else ""


def compute_open_and_groups(
    events: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[int], dict[Any, list[dict[str, Any]]]]:
    """Open hand-offs/sessions (T27b) and closed hand-off groups (T27d).

    Runs over the FULL log, not the tail: a pair must be found wherever its
    two halves fall, and truncating first would invent a false OPEN, or a
    false "no such pair", out of nothing but the page's own scroll limit.

    Returns ``(open_items, groups, consumed, own_by_session)``.
    ``own_by_session`` is T105's fourth value: per session, the ``activity``
    lines the attribution pass DECLINED to fold into any group because they
    carry no ``agent_type`` - the main session's own work, in log order. It
    is returned from here rather than computed by whoever wants it precisely
    so that there is one pass and one decision; a caller re-deriving it would
    be the second reading of "who ran this line" that this module has twice
    paid for. Nothing in it is in ``consumed``: the flat feed still owns
    these lines, and a drawer that shows them takes nothing away from it.
    ``open_items`` is sorted
    oldest-first ("sorted above everything else" and the longest-open items
    first within that). Every open item carries ``row_kind``
    (``"open_handoff"`` or ``"open_session"``) and ``agent_type`` - the ONE
    discriminator and ONE agent-type field name this payload now uses
    everywhere (T31; a group row uses the same two names, see
    ``read_state``) - plus ``last_seen_ts``, ``phase`` and ``ambiguous``, the
    raw facts T30's quiet-time labels are built from (see the module
    docstring, "Quiet-time" and "``agent_type`` is a TYPE here too").
    ``consumed`` is the ``id()`` of every raw event folded into a group or
    promoted into ``open_items`` - the flat feed must drop exactly these and
    nothing more, so a ``gate_block`` that happened to land during a
    hand-off still reaches the landing view unburied (a).

    The accounting is EXACT and is the reason ``consumed`` is built the way
    it is: an id enters it only once something else has undertaken to render
    that line. Open items are therefore consumed AFTER the ``OPEN_TAIL``
    slice, never before - a start dropped by that bound falls back into the
    flat feed rather than vanishing from the page entirely.
    """
    by_session: dict[Any, list[dict[str, Any]]] = {}
    for entry in events:
        by_session.setdefault(_session_of(entry), []).append(entry)

    open_pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    groups: list[dict[str, Any]] = []
    consumed: set[int] = set()
    own_by_session: dict[Any, list[dict[str, Any]]] = {}

    for session, session_events in by_session.items():
        h_starts = [e for e in session_events if e.get("event") == "handoff_start"]
        h_ends = [e for e in session_events if e.get("event") == "handoff_end"]
        # T103/T101: every ``subagent_stop`` this session recorded, matched to
        # the start it finishes by ``_match_finish_events`` - the SAME pass
        # that decides BACKGROUND/AWAITED/FINISHED for both the closed pairs
        # below and the still-open hand-offs further down.
        h_stops = [e for e in session_events if e.get("event") == "subagent_stop"]
        finish_map = _match_finish_events(h_starts, h_ends, h_stops)
        pairs, open_handoffs = _pair_starts_ends(
            h_starts, h_ends, _HANDOFF_ID_FIELD, _HANDOFF_FALLBACK_FIELDS
        )

        windows: list[_Window] = []
        for order, (start, end) in enumerate(pairs):
            consumed.add(id(start))
            consumed.add(id(end))
            t0, t1 = _epoch_seconds(start.get("ts")), _epoch_seconds(end.get("ts"))
            gap_ms = (t1 - t0) * 1000.0 if (t0 is not None and t1 is not None) else None
            finished_ts = finish_map.get(id(start))
            group: dict[str, Any] = {
                "session": session,
                "subagent_type": start.get("subagent_type"),
                "description": start.get("description"),
                "prompt_head": start.get("prompt_head"),
                "start_ts": start.get("ts"),
                "end_ts": end.get("ts"),
                "events": [],
                "inferred": 0,
                "inferred_ids": set(),
                "sort_ts": end.get("ts") or start.get("ts"),
                "delegation_state": _delegation_state(True, gap_ms, finished_ts is not None),
                "finished_ts": finished_ts,
            }
            groups.append(group)
            if t0 is None or t1 is None:
                continue  # a pair without two readable times encloses nothing
            lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
            windows.append(_Window(lo, hi, order, start.get("subagent_type"), group))

        attributed = _attribute_activity(session_events, windows)
        consumed |= attributed.consumed
        # T105: the same pass's other half, kept per session because the
        # drawer belongs to ONE node - the session the canvas draws.
        own_by_session[session] = attributed.own

        # Quiet-time's own pass (T30), AFTER attribution above: an open
        # hand-off may only claim activity CLOSED delegations have not
        # already claimed (``_unclaimed_activity``), and only where the
        # record can say it was THIS hand-off's rather than a sibling of the
        # same type's (``_quiet_facts``). The rivals for a hand-off are every
        # OTHER still-open hand-off of that same agent type in this session -
        # the ambiguity ``agent_type`` cannot resolve, here as in grouping.
        rivals_by_agent: dict[str, list[Any]] = {}
        for start in open_handoffs:
            rivals_by_agent.setdefault(_agent_text(start.get("subagent_type")), []).append(
                start.get("ts")
            )

        for start in open_handoffs:
            agent = start.get("subagent_type")
            agent_text = _agent_text(agent)
            last_seen, phase, ambiguous, last_entry = _quiet_facts(
                _unclaimed_activity(session_events, consumed, agent_text),
                start.get("ts"),
                rivals_by_agent.get(agent_text, []),
            )
            finished_ts = finish_map.get(id(start))
            open_pending.append(
                (
                    {
                        "row_kind": "open_handoff",
                        "session": session,
                        "ts": start.get("ts"),
                        "agent_type": agent,
                        "description": start.get("description"),
                        "prompt_head": start.get("prompt_head"),
                        "last_seen_ts": last_seen,
                        "phase": phase,
                        "ambiguous": ambiguous,
                        "delegation_state": _delegation_state(
                            False, None, finished_ts is not None
                        ),
                        "finished_ts": finished_ts,
                        "last_action": _action_detail_text(last_entry),
                    },
                    start,
                )
            )

        s_starts = [e for e in session_events if e.get("event") == "session_start"]
        s_ends = [e for e in session_events if e.get("event") == "session_end"]
        _, open_sessions = _pair_starts_ends(s_starts, s_ends, None, ())
        # A session's rivals are the other still-open ``session_start`` lines
        # recorded under the SAME session id: the identifier that would tell
        # them apart is the one they share, so two of them are exactly as
        # indistinguishable as two hand-offs of one type.
        session_rivals = [start.get("ts") for start in open_sessions]
        for start in open_sessions:
            last_seen, phase, ambiguous, _last_entry = _quiet_facts(
                session_events, start.get("ts"), session_rivals
            )
            open_pending.append(
                (
                    {
                        "row_kind": "open_session",
                        "session": session,
                        "ts": start.get("ts"),
                        "agent_type": None,
                        "description": None,
                        "prompt_head": None,
                        "last_seen_ts": last_seen,
                        "phase": phase,
                        "ambiguous": ambiguous,
                    },
                    start,
                )
            )

    for group in groups:
        group["count"] = len(group["events"])
        group["last_action"] = _last_action_text(group["events"])

    open_pending.sort(key=lambda pair: pair[0].get("ts") or "")
    kept = open_pending[:OPEN_TAIL]
    for _item, start in kept:
        consumed.add(id(start))
    return [item for item, _start in kept], groups, consumed, own_by_session


#: What the canvas says when the log holds no hand-off and no open session
#: for any session at all. It is a fact, not a loss, and it is worded here so
#: the page has no sentence of its own to drift from this one.
GRAPH_EMPTY_NOTE = "no hand-off and no open session is recorded yet"

#: How long a card whose end is REAL - FINISHED (a matched ``subagent_stop``)
#: or AWAITED (a genuine blocking return, which
#: [[a-recorded-end-is-not-a-finish]] already treats as an honest end, unlike
#: a BACKGROUND launch acknowledgment) - stays drawn on the canvas after its
#: own finish moment before it drops off into the roster-only past (T109).
#: BACKGROUND never lingers by this constant: its own ``handoff_end`` is a
#: launch acknowledgment, not a real end, so a card that may still be doing
#: real work must never be swept into the group that is leaving. Sixty
#: seconds is long enough for a reader polling this page (``POLL_MS`` redraws
#: it every 1.5s, so dozens of polls) to actually see what just completed,
#: short enough that the canvas does not slowly fill into a permanent museum
#: of everything that ever finished.
GRAPH_FINISH_LINGER_SECONDS = 60


def _real_finish_ts(row: Mapping[str, Any]) -> Any:
    """When a delegation's REAL end actually landed (T109): the matched
    ``subagent_stop``'s own timestamp for a FINISHED row, or the closing
    ``handoff_end`` for an AWAITED one - the two states this project already
    treats as an honest end (see the module docstring's "BACKGROUNDED,
    AWAITED, FINISHED" section). Any other state - BACKGROUND, or the
    pre-existing OPEN - has no real finish on record yet, so this reports
    ``None`` rather than inventing one from a return that only confirms the
    launching tool got its own result back.
    """
    state = row.get("delegation_state")
    if state == "finished":
        return row.get("finished_ts")
    if state == "awaited":
        return row.get("end_ts")
    return None


def graph_agent_label(agent: Any) -> str:
    """The agent TYPE a node names - the only thing about WHO ran a hand-off
    that the record actually holds (T4).

    Never a model and never a routing tier: ``hooks/keel_capture.py`` writes
    the subagent type it was asked for and nothing about which model answered,
    so a node claiming one would be the viewer inventing it. A hand-off whose
    start line carries no type says that in words rather than showing a blank
    card.
    """
    return _agent_text(agent) or "no agent type recorded"


def graph_task_label(description: Any) -> str:
    """The task a hand-off was handed, as its node shows it - the ALREADY
    REDACTED ``description`` the record carries, or the fact that it carries
    none."""
    text = description.strip() if isinstance(description, str) else ""
    return text or "no task description recorded"


#: The exact words a delegation with zero attributed lines uses everywhere on
#: this page it needs to say so - a closed card's own count
#: (``graph_count_label``) and its panel's empty state (T106, both open and
#: closed cards) share this ONE string, so a reader can never see two
#: different sentences for the same fact: nothing on record names this
#: delegation as the author of any line.
NO_ACTIVITY_ATTRIBUTED_NOTE = "no activity attributed"


def graph_count_label(count: Any, inferred: Any) -> str:
    """What a CLOSED node says about the activity attributed to it.

    An inferred member is counted out separately and named as one, because
    the group row this node is drawn from already had to say the same thing:
    where two hand-offs of one type overlapped, the record names the type and
    not which of them ran the line. A node that reported a bare total would
    quietly upgrade that tie-break into a reading of the log.
    """
    total = int(count or 0)
    guessed = int(inferred or 0)
    if not total:
        return NO_ACTIVITY_ATTRIBUTED_NOTE
    if guessed:
        return f"{total} event(s), {guessed} placed by inference"
    return f"{total} event(s)"


def graph_type_note(agent: Any, open_of_type: int) -> str:
    """What an OPEN node says when a sibling of its own type is open too
    (T4) - the same limit ``group["inferred"]`` and ``quiet_note`` already
    state, in the same terms.

    The record names the agent TYPE, never the instance, so with two of one
    type open at once nothing on this page can say which of them a given node
    is. Saying so on the node is the honest alternative to picking one and
    looking certain.
    """
    return (
        f"{open_of_type} {graph_agent_label(agent)} hand-offs are open at once - the "
        "record names the agent type, not which of them this node is"
    )


def graph_root_label(handoffs: int, open_now: int, open_sessions: int) -> str:
    """The line under the session node: how many hand-offs are drawn, how
    many of them are open, and how many of this session's own
    ``session_start`` lines are still unmatched (T4)."""
    bits = [f"{handoffs} hand-off(s) drawn", f"{open_now} open now"]
    if open_sessions:
        bits.append(f"{open_sessions} session line(s) still open")
    return " · ".join(bits)


def graph_note(session: Any, omitted: int, other_sessions: int) -> str:
    """The sentence beside the canvas heading (T4): which session is drawn,
    and everything the log holds that this canvas does NOT draw.

    Both omissions are stated rather than left to be noticed - the oldest
    closed hand-offs ``GRAPH_NODE_TAIL`` trimmed, and the other sessions in
    the log - because a canvas that silently drew a subset would be the one
    thing this page refuses everywhere else: a loss dressed as a fact.
    """
    bits = [f"session {session}, the most recently recorded"]
    if omitted:
        bits.append(f"{omitted} older closed hand-off(s) of this session are not drawn")
    if other_sessions:
        bits.append(f"{other_sessions} other session(s) with work of their own are not drawn")
    return " · ".join(bits)


def _graph_ts(row: Mapping[str, Any]) -> str:
    """How recent a rendered row is, for choosing the session to draw: a
    closed hand-off's END, an open item's own start. Absence sorts first."""
    for field in ("end_ts", "ts", "start_ts"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def _graph_start_ts(row: Mapping[str, Any]) -> str:
    """When a rendered row's hand-off STARTED - the order nodes are laid out
    in. Ordering is presentation only: the canvas draws no edge between two
    hand-offs, and each node prints its own start time, so what a reader
    learns about sequence comes from the record and not from a position."""
    for field in ("ts", "start_ts"):
        value = row.get(field)
        if isinstance(value, str) and value:
            return value
    return ""


def compute_graph(
    open_rows: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
    now: float | None = None,
) -> dict[str, Any]:
    """The delegation canvas (T4): one session as the root node, one node per
    hand-off it made, and one edge from the root to each of them.

    Built from the rows the page ALREADY renders - ``read_state``'s rendered
    open list and its rendered group rows, both already redacted - so there
    is no second pairing pass, no second reading of the log, and no way for
    the canvas to name a hand-off the open rows and the feed do not. That is
    the whole reason this takes rendered rows rather than raw events.

    The session drawn is the one whose newest row is newest. What is left out
    - other sessions, and the oldest closed hand-offs beyond
    ``GRAPH_NODE_TAIL`` - is counted into ``note`` rather than dropped
    silently; an OPEN hand-off is never left out.

    ``now`` (T109) gates a THIRD kind of leaving, orthogonal to both of the
    above: a row whose real finish (``_real_finish_ts``) is more than
    ``GRAPH_FINISH_LINGER_SECONDS`` behind ``now`` is not drawn as a node at
    all, however much of ``GRAPH_NODE_TAIL``'s budget is still free - it has
    had its short moment on the canvas and now belongs to the roster only.
    Defaults to ``time.time()`` so every production caller reads the real
    clock; a test passes its own value so the boundary is a fixed value, not
    a race against the wall.

    Edges are root-to-node only. Two hand-offs are never joined, because the
    record carries no ordering between them (see the module docstring).
    """
    if now is None:
        now = time.time()
    latest: dict[str, str] = {}
    for row in list(open_rows) + list(group_rows):
        session = row.get("session")
        if not isinstance(session, str) or not session:
            continue
        stamp = _graph_ts(row)
        if session not in latest or stamp >= latest[session]:
            latest[session] = stamp
    if not latest:
        return {
            "session": "",
            "root": None,
            "nodes": [],
            "edges": [],
            "counts": {"handoffs": 0, "open": 0, "omitted": 0, "other_sessions": 0},
            "note": GRAPH_EMPTY_NOTE,
        }
    session = sorted(latest.items(), key=lambda item: (item[1], item[0]))[-1][0]

    open_handoffs = [
        row
        for row in open_rows
        if row.get("row_kind") == "open_handoff" and row.get("session") == session
    ]
    closed = sorted(
        (row for row in group_rows if row.get("session") == session), key=_graph_ts
    )
    budget = max(0, GRAPH_NODE_TAIL - len(open_handoffs))
    kept_closed = closed[len(closed) - budget :] if budget else []
    omitted = len(closed) - len(kept_closed)

    # Two open hand-offs of ONE type cannot be told apart by a record that
    # names the type - the same limit grouping and quiet-time both run into.
    open_of_type: dict[str, int] = {}
    for row in open_handoffs:
        agent = _agent_text(row.get("agent_type"))
        open_of_type[agent] = open_of_type.get(agent, 0) + 1

    ordered = sorted(open_handoffs + kept_closed, key=_graph_start_ts)
    nodes: list[dict[str, Any]] = []
    for index, row in enumerate(ordered):
        agent = row.get("agent_type")
        state = row.get("delegation_state") or "open"
        node: dict[str, Any] = {
            "id": f"h{index}",
            "row_kind": row.get("row_kind"),
            "session": row.get("session"),
            "agent_type": agent,
            "agent_label": graph_agent_label(agent),
            "task_label": graph_task_label(row.get("description")),
            "shares_type": False,
            "type_note": "",
            # T103: the pill's own state and word, the sentence a BACKGROUND
            # card adds under it, whether the card TICKS (BACKGROUND and the
            # pre-existing OPEN case) or shows a FIXED span (AWAITED and
            # FINISHED), and the small last-action line - all decided here so
            # a test can read each as a value (see the module docstring).
            "delegation_state": state,
            "state_note": delegation_state_note(state),
            "last_action": row.get("last_action") or "",
            # T106: the worker card's own panel reads these two fields and
            # nothing else for its list of lines. ``events`` is the CLOSED
            # group's own member list - the same one ``graph_count_label``
            # above already counts, ``_attribute_activity`` already marked
            # ``inferred`` on, and the feed's collapsed card already renders
            # (``groupRow``) - never a second attribution pass. An OPEN
            # hand-off has no such group yet (T30's own last-action line
            # above is a different, weaker signal - see ``_quiet_facts``), so
            # it carries none, which is also honest: the record cannot yet
            # say which lines are its.
            "events": list(row.get("events") or []),
            "activity_note": "" if row.get("events") else NO_ACTIVITY_ATTRIBUTED_NOTE,
        }
        if row.get("row_kind") == "open_handoff":
            same = open_of_type.get(_agent_text(agent), 0)
            finished_span = (
                _finished_span(row.get("ts"), row.get("finished_ts"))
                if state == "finished"
                else None
            )
            node.update(
                {
                    "ts": row.get("ts"),
                    "open": state != "finished",
                    "ticking": state == "open",
                    "state_label": delegation_state_label(state),
                    "duration_label": fmt_duration(finished_span) if state == "finished" else "",
                    "count_label": "",
                    # T30's own facts, carried across unchanged so the node and
                    # the open row show one wording, and so the page's own
                    # in-place ticker can update this node from the very same
                    # open item it updates the row from.
                    "last_seen_ts": row.get("last_seen_ts"),
                    "phase": row.get("phase"),
                    "ambiguous": row.get("ambiguous"),
                    "quiet_threshold_seconds": row.get("quiet_threshold_seconds"),
                    "quiet_note": row.get("quiet_note"),
                    "shares_type": same > 1,
                    "type_note": graph_type_note(agent, same) if same > 1 else "",
                }
            )
        else:
            start, end = _epoch_seconds(row.get("start_ts")), _epoch_seconds(row.get("end_ts"))
            span = abs(end - start) if (start is not None and end is not None) else None
            # T103: only AWAITED and FINISHED get a FIXED duration_label - a
            # real end is on record for both. BACKGROUND ticks instead (see
            # `ticking` below), and must not carry the near-instant gap here
            # too: that gap is exactly the figure this task exists to stop a
            # reader from mistaking for "done".
            if state == "finished":
                duration_label = fmt_duration(
                    _finished_span(row.get("start_ts"), row.get("finished_ts"))
                )
            elif state == "awaited":
                duration_label = fmt_duration(span)
            else:
                duration_label = ""
            node.update(
                {
                    "ts": row.get("start_ts"),
                    "end_ts": row.get("end_ts"),
                    "open": False,
                    "ticking": state == "background",
                    "state_label": delegation_state_label(state),
                    "duration_label": duration_label,
                    "count_label": graph_count_label(row.get("count"), row.get("inferred")),
                }
            )
        # T109: a card whose end is REAL lingers for a short, named window
        # after that finish moment and then leaves the canvas for the roster
        # - checked LAST, against the finished row/group, never the node
        # dict, so a state this task did not touch (BACKGROUND, OPEN) is
        # never a candidate: `_real_finish_ts` reports `None` for both and
        # the row is kept exactly as every prior task already drew it. An
        # unparseable finish timestamp also keeps the row rather than
        # guessing it is stale.
        finish_ts = _real_finish_ts(row)
        if finish_ts is not None:
            finish_epoch = _epoch_seconds(finish_ts)
            if finish_epoch is not None and (now - finish_epoch) > GRAPH_FINISH_LINGER_SECONDS:
                continue
        nodes.append(node)

    open_sessions = sum(
        1
        for row in open_rows
        if row.get("row_kind") == "open_session" and row.get("session") == session
    )
    open_now = sum(1 for node in nodes if node["open"])
    return {
        "session": session,
        "root": {
            "id": "root",
            "session": session,
            "handoffs": len(nodes),
            "open": open_now,
            "open_sessions": open_sessions,
            "label": graph_root_label(len(nodes), open_now, open_sessions),
        },
        "nodes": nodes,
        # One edge per node, every one of them from the root. Nothing joins
        # two hand-offs: the record does not order them, and a chain would
        # say it did.
        "edges": [
            {"from": "root", "to": node["id"], "open": node["open"]} for node in nodes
        ],
        "counts": {
            "handoffs": len(nodes),
            "open": open_now,
            "omitted": omitted,
            "other_sessions": len(latest) - 1,
        },
        "note": graph_note(session, omitted, len(latest) - 1),
    }


def _node_key(node: Mapping[str, Any]) -> str:
    """The identifier a worker card's own panel is opened by, built the SAME
    way the page's own client-side ``openRowKey`` builds it -
    ``row_kind``+``session``+``ts`` (T106). A roster chip carrying this key
    can only ever point at a card the reader could also click themselves,
    because it is read off the very node the canvas drew, not composed
    twice."""
    return f"{node.get('row_kind') or ''}|{node.get('session') or ''}|{node.get('ts') or ''}"


def latest_node_of_agent_type(
    nodes: list[Mapping[str, Any]], agent_type: Any
) -> Mapping[str, Any] | None:
    """The MOST RECENT delegation card of one agent type, among the nodes the
    canvas actually drew (T106) - "most recent" by the same start-time order
    the canvas itself lays its cards out in (``_graph_start_ts``), so a
    roster chip can never resolve to a card that is not on screen. ``None``
    when that type has no card currently drawn: the roster spans every
    session the log has ever recorded, and the canvas draws only the one
    session most recently active (see ``compute_graph``'s own docstring).
    """
    text = _agent_text(agent_type)
    candidates = [node for node in nodes if _agent_text(node.get("agent_type")) == text]
    if not candidates:
        return None
    return max(candidates, key=_graph_start_ts)


#: The two tool families, folded once at import. Membership is the adapter's
#: (see the import above); only the casefolding is done here, the same way
#: ``hooks/keel_capture.py`` folds the same two tuples for the same reason.
_WRITE_TOOLS_FOLDED = frozenset(name.casefold() for name in WRITE_TOOLS)
_SHELL_TOOLS_FOLDED = frozenset(name.casefold() for name in SHELL_TOOLS)


def action_kind(tool: Any) -> str:
    """The KIND of one ``activity`` line, for the icon the drawer shows.

    A fact about the tool the record names, not an interpretation of what the
    action achieved: a write tool wrote, a shell tool ran a command, and
    anything else is called neither (``ACTION_KIND_OTHER``). The two families
    are the adapter's own, so a tool added there is classified here without
    this module being edited - and a tool it does not know is not guessed at.
    """
    folded = tool.casefold() if isinstance(tool, str) else ""
    if folded in _WRITE_TOOLS_FOLDED:
        return ACTION_KIND_WRITE
    if folded in _SHELL_TOOLS_FOLDED:
        return ACTION_KIND_COMMAND
    return ACTION_KIND_OTHER


def is_review_handoff(agent: Any) -> bool:
    """Whether a hand-off's agent TYPE names a reviewer (T105).

    The record holds the type keel was asked for and nothing else, so this is
    a reading of that NAME - ``keel:reviewer-correctness`` and
    ``reviewer-tests`` are reviews, ``keel:executor`` and ``general-purpose``
    are not - and the figure it feeds is called "review hand-off(s)" in
    ``root_summary_label`` for exactly that reason: the label names what was
    counted (an agent type whose name says reviewer), never a claim that a
    review was performed. The namespace prefix is stripped because keel's own
    agents carry one and a project's may not.
    """
    text = _agent_text(agent)
    return text.rsplit(":", 1)[-1].startswith(REVIEW_AGENT_PREFIX)


def agent_tone(agent: Any) -> str:
    """Which colour family one agent type's legend dot belongs to (T119).

    The REVIEWER family is decided by ``is_review_handoff`` - the SAME
    reading of the same name the centre node's drawer already counts reviews
    by (T105) - never a second prefix test that could one day disagree with
    it about what a reviewer is called. The namespace prefix is stripped the
    same way and for the same reason: keel's own agents carry one and a
    project's may not.

    Anything the four families do not name is ``AGENT_TONE_OTHER`` - neutral,
    never quietly folded into a family it is not in, because the dot is the
    only thing on a legend row a reader takes in at a glance.
    """
    name = _agent_text(agent).rsplit(":", 1)[-1]
    if is_review_handoff(agent):
        return AGENT_TONE_REVIEW
    if name.startswith("executor-deep"):
        return AGENT_TONE_DEEP
    if name.startswith("executor"):
        return AGENT_TONE_EXECUTOR
    if name.startswith("researcher"):
        return AGENT_TONE_RESEARCH
    return AGENT_TONE_OTHER


def legend_entries(roster: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The legend bar's rows (T119): keel's own agents in ``AGENT_ROLES``
    order, then every OTHER agent type the roster actually carries.

    Two sources, one list, no duplicates. The shipped agents are always
    named, whether or not this project has ever run one - the bar is a KEY to
    the colours on the canvas and the roster, not a census, and a key that
    appeared only once a colour had already been used would be no key at all.
    Everything the roster carries is named too, so no chip on the page can
    show a dot the foot of the page cannot explain; a type with no shipped
    purpose line says so in its own words (``LEGEND_UNKNOWN_ROLE``) rather
    than being dropped or given a role it never claimed.

    ``roster`` entries arrive already redacted (``read_state`` redacts each
    ``agent_type`` before this sees it), and the names from ``AGENT_ROLES``
    are constants carrying no path, so nothing here re-redacts anything.
    """
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(agent_type: str, role: str) -> None:
        if agent_type in seen:
            return
        seen.add(agent_type)
        entries.append(
            {"agent_type": agent_type, "role": role, "tone": agent_tone(agent_type)}
        )

    for name, role in AGENT_ROLES.items():
        _add(name, role)
    for entry in roster:
        name = entry.get("agent_type")
        text = name.strip() if isinstance(name, str) else ""
        if text:
            _add(text, AGENT_ROLES.get(text, LEGEND_UNKNOWN_ROLE))
    return entries


def root_summary_label(handoffs: int, reviews: int, gate_blocks: int) -> str:
    """The drawer's summary line (T105), in the reference's own order: how
    much this session handed off, how much of that named a reviewer, and how
    often the gate blocked it. Scoped to the session the canvas draws, which
    is why it says so rather than borrowing the header's cross-session
    figures."""
    return (
        f"this session: {handoffs} hand-off(s) · {reviews} review hand-off(s) · "
        f"{gate_blocks} gate block(s)"
    )


def own_activity_note(total: int, shown: int) -> str:
    """What the drawer says about the lines it is NOT showing (T105).

    Three different facts, never one: nothing of this session's own is on
    record, everything on record is on screen (no note at all), or the tail
    bound left some out and says how many. An empty list with no sentence
    would read as "it did nothing", which is the reading this refuses.
    """
    if total <= 0:
        return "no action by this session outside a delegation is recorded yet"
    omitted = total - shown
    return f"{omitted} older line(s) of this session's own work are not shown" if omitted else ""


def own_activity_row(entry: Mapping[str, Any]) -> dict[str, Any]:
    """One drawer row, from one ALREADY-REDACTED main-session line (T105).

    Three values and no fourth: when it happened, what KIND of action it was,
    and the content - the same ``detail`` field (a path, or the head of a
    command) that T103's last-action line reads, through the same reader, so
    a card's last action and the drawer's newest row cannot word one line two
    ways. A line whose target the record does not carry says so.
    """
    return {
        "ts": entry.get("ts"),
        "action_kind": action_kind(entry.get("tool")),
        "text": _action_detail_text(entry) or NO_ACTION_TARGET_NOTE,
    }


def root_panel(
    own_entries: list[dict[str, Any]], counts: Mapping[str, int]
) -> dict[str, Any]:
    """Everything the centre node's drawer shows, decided here (T105).

    ``own_entries`` are the RAW main-session lines
    ``compute_open_and_groups`` handed back for the session being drawn -
    rule (1) of ``_attribute_activity``'s own output, in log order - and this
    is the only place they are redacted and turned into rows, because until
    ``compute_graph`` has chosen a session there is no way to know which
    session's lines are worth rendering at all.

    NEWEST FIRST, as the reference's frame 2 is: the log is append-ordered,
    so the newest lines are its last, and the bound is taken from that end
    before the list is reversed - the same order the flat feed puts its own
    rows in, arrived at the same way.
    """
    tail = list(own_entries)[-OWN_ACTIVITY_TAIL:]
    rows = [own_activity_row(redact_mapping(entry)) for entry in reversed(tail)]
    return {
        "role": ROOT_ROLE_LABEL,
        "summary": root_summary_label(
            counts.get("handoffs", 0),
            counts.get("reviews", 0),
            counts.get("gate_blocks", 0),
        ),
        "own_activity": rows,
        "own_total": len(own_entries),
        "own_note": own_activity_note(len(own_entries), len(rows)),
    }


#: Fields ``content_digest`` ignores. ``now`` is the wall clock, which every
#: poll changes whether or not anything was recorded; the digest cannot
#: include itself. Everything else - down to the audit file's mtime - IS
#: content: if it moved, the page has something new to draw.
_DIGEST_EXCLUDED = frozenset({"now", "content_digest"})


def content_digest(state: Mapping[str, Any]) -> str:
    """A fingerprint of everything in ``state`` a redraw depends on (T30).

    Two reads of an unchanged project give the same digest even though their
    ``now`` differs, so the page can skip a redraw by comparing two short
    strings - the "equality check that ignores the timestamp", decided here
    where its behaviour is a value rather than in the page where it could
    only be found by substring. Sorted keys, so two equal states cannot
    disagree by dictionary order; ``default=str`` for the same reason
    ``/api/state`` serialises that way.
    """
    material = {key: value for key, value in state.items() if key not in _DIGEST_EXCLUDED}
    encoded = json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_state(project: Path, selected: str | None = None) -> dict[str, Any]:
    """The whole viewer state as a plain dictionary - also ``/api/state``.

    ``feed`` mixes two row shapes, both already redacted: a plain event
    (``row_kind: "event"``) and a closed hand-off's collapsed group
    (``row_kind: "group"``, carrying its own ``events``) - T27d. Whatever a
    group swallows is removed from the flat feed entirely, not duplicated:
    ``compute_open_and_groups`` gives each line at most one owner, so the
    ``consumed`` test below removes exactly the lines some group or open item
    has undertaken to render. A group also carries ``inferred`` - how many of
    its members could NOT be attributed from the record and were placed by a
    tie-break - and marks those same members with ``inferred: true``, so the
    page can show an inferred grouping as what it is.
    ``open`` is T27b's still-open list, kept separate and never subject to
    the tail bound, because it is exactly the small set of things a human
    still needs to see.

    ``feed`` alone is tail-bounded (``EVENT_TAIL``). That is a scroll limit
    on presentation, applied after every line already has exactly one owner -
    it never changes WHICH row owns a line, only how far back the page goes.
    """
    project = Path(project)
    events, lost = read_events(project)
    # T143: the same withholding the adopted board already applies, applied
    # here too. Both viewers read the same log and, until now, only one of
    # them knew that four of its hand-offs are launches the record itself
    # shows never took - so this page went on drawing them as working agents
    # for hours after the other page had stopped. The rule is IMPORTED, not
    # copied: two implementations of "never took" could drift into two
    # different answers about whether an agent is alive, and that is the one
    # disagreement a pair of viewers must not be able to have.
    events, withheld_launches = _withhold_never_took(events)
    plans, listing_failed = list_plans(project)
    # The selected ledger must be one this project actually LISTS, not merely
    # a name of the right shape: otherwise a query string naming a ledger
    # that never existed would be reported as a ledger that could not be read
    # (``counts.unreadable_plans``), and a bad request would read as a loss.
    listed = {entry["name"] for entry in plans}
    name = selected if selected in listed else (plans[0]["name"] if plans else "")
    counts = {event: 0 for event in COUNTED_EVENTS}
    sessions: set[str] = set()
    # T105: the three figures the centre node's drawer summarises, per
    # session, counted in the pass this function ALREADY makes over every
    # line rather than in a second walk of the log. These are counts of
    # whole event kinds - nothing here attributes an activity line to
    # anything, which is settled once and elsewhere.
    per_session: dict[Any, dict[str, int]] = {}
    for entry in events:
        kind = entry.get("event")
        if isinstance(kind, str) and kind in counts:
            counts[kind] += 1
        session = _session_of(entry)
        if isinstance(session, str) and session:
            sessions.add(session)
        bucket = per_session.setdefault(
            session, {"handoffs": 0, "reviews": 0, "gate_blocks": 0}
        )
        if kind == "handoff_start":
            bucket["handoffs"] += 1
            if is_review_handoff(entry.get("subagent_type")):
                bucket["reviews"] += 1
        elif kind == "gate_block":
            bucket["gate_blocks"] += 1

    open_items, groups, consumed, own_by_session = compute_open_and_groups(events)

    rows: list[dict[str, Any]] = []
    for entry in events:
        if id(entry) in consumed:
            continue
        row = redact_mapping(entry)
        row["row_kind"] = "event"
        row["sort_ts"] = entry.get("ts")
        # T31: the row's own detail line, built from the ALREADY-REDACTED
        # fields (``detail``/``prompt_head`` among them, which the log carries
        # and the page used to drop) - built here, so what a row SAYS is a
        # value rather than a template the page assembles.
        row["detail_text"] = detail_text(row)
        # T120: the row's own SENTENCE, from these SAME already-redacted
        # fields - never a second event read. "" where no kind names one, so
        # the page falls back to the raw name and ``detail_text`` above.
        row["feed_sentence"] = feed_sentence(row)
        # T120 addendum: the row's own VERB FAMILY, the one value the page's
        # icon keys off - never a second reading of what the kind means.
        row["feed_verb"] = feed_verb(row)
        rows.append(row)
    # Built as their own list BEFORE the tail bound is applied below, because
    # the delegation canvas (T4) draws from these same rendered rows and must
    # see every closed hand-off of the session it draws - the tail is a scroll
    # limit on the FEED, and a scroll limit must not decide what the canvas
    # knows about.
    group_rows: list[dict[str, Any]] = []
    for group in groups:
        members = []
        for member in group["events"]:
            rendered = redact_mapping(member)
            # Marked on the LINE as well as counted on the group: a reader
            # opening the block has to be able to tell which rows inside it
            # are known to belong there and which were placed by tie-break.
            rendered["inferred"] = id(member) in group["inferred_ids"]
            rendered["detail_text"] = detail_text(rendered)
            rendered["feed_sentence"] = feed_sentence(rendered)
            rendered["feed_verb"] = feed_verb(rendered)
            members.append(rendered)
        group_rows.append(
            {
                "row_kind": "group",
                "session": redact(group["session"]),
                # ONE agent-type name across every row kind (T31): this used
                # to be "subagent_type" here and "agent_type" on an activity
                # line's own fields (still true inside ``events`` above,
                # which are raw records rendered as recorded) - a reader of
                # this endpoint now learns one name, not two.
                "agent_type": redact(group["subagent_type"]),
                "description": redact(group["description"]),
                "prompt_head": redact(group.get("prompt_head")),
                "start_ts": group["start_ts"],
                "end_ts": group["end_ts"],
                "count": group["count"],
                "inferred": group["inferred"],
                "events": members,
                "sort_ts": group["sort_ts"],
                # T103: carried across unchanged, same computation as above.
                "delegation_state": group.get("delegation_state"),
                "finished_ts": group.get("finished_ts"),
                "last_action": redact(group.get("last_action")),
            }
        )
    rows.extend(group_rows)
    rows.sort(key=lambda row: row.get("sort_ts") or "")
    rows = rows[-EVENT_TAIL:]

    open_rendered = []
    for item in open_items:
        agent_type = redact(item["agent_type"])
        phase = item.get("phase") or "tool_running"
        ambiguous = bool(item.get("ambiguous"))
        kind = "hand-off" if item["row_kind"] == "open_handoff" else "session"
        open_rendered.append(
            {
                # ONE discriminator name across every row kind (T31): this
                # used to be "open_of" here and "row_kind" on a feed row -
                # both lists now use "row_kind", with "open_handoff"/
                # "open_session" telling the two open shapes apart the way
                # "open_of" used to.
                "row_kind": item["row_kind"],
                "session": redact(item["session"]),
                "ts": item["ts"],
                "agent_type": agent_type,
                "description": redact(item["description"]),
                "prompt_head": redact(item.get("prompt_head")),
                # T30's raw facts - never an elapsed time, which stays a
                # render-time-only wall-clock computation on the client,
                # exactly as ``ts`` already was: the latest moment this open
                # item can still be attributed activity, which of the two
                # quiet-time phases that implies, whether a line had to be
                # DECLINED because more than one open item of the same type
                # could have produced it, and - decided here rather than in
                # the page - the threshold that phase carries and the words
                # a crossing is stated in. See the module docstring,
                # "Quiet-time" and "``agent_type`` is a TYPE here too".
                "last_seen_ts": item.get("last_seen_ts"),
                "phase": phase,
                "ambiguous": ambiguous,
                "quiet_threshold_seconds": quiet_threshold_seconds(phase),
                "quiet_note": quiet_note(phase, ambiguous, agent_type, kind),
                # T103: BACKGROUND/AWAITED/FINISHED and the small last-action
                # line are carried across from ``compute_open_and_groups``
                # unchanged, exactly as the quiet-time facts above already
                # are - one computation, read here rather than redone.
                "delegation_state": item.get("delegation_state"),
                "finished_ts": item.get("finished_ts"),
                "last_action": redact(item.get("last_action")),
            }
        )

    # T108/T109: ONE read of the wall clock for the whole request, reused by
    # every decision that needs "now" below - the canvas's own T109 linger
    # window and T108's session liveness - so two figures on the same page
    # can never disagree because they happened to be computed a heartbeat
    # apart.
    now = time.time()
    # T4: the canvas, from the rows just rendered rather than from the log a
    # second time - so a hand-off can never be on the canvas and missing from
    # the open rows below it, or the other way about.
    graph = compute_graph(open_rendered, group_rows, now)
    # T105: the centre node's drawer, attached to the root the canvas just
    # chose. It is built HERE rather than inside ``compute_graph`` for one
    # reason: which session is drawn is that function's own decision, and
    # redacting and rendering every OTHER session's main-session lines - a
    # log of any age holds thousands - would be work thrown away on every
    # poll. What it shows is still entirely the server's (``root_panel``).
    if graph["root"]:
        # ``graph["session"]`` is the session as the RENDERED rows name it,
        # which is to say after ``redact``; both lookups here are keyed by
        # the raw identifier the log carries. They are re-keyed the same way
        # the rows were rather than trusting two spellings of one identifier
        # to agree - a drawer that silently found nothing would read as a
        # session that did nothing.
        own_drawn = {redact(key): value for key, value in own_by_session.items()}
        counts_drawn = {redact(key): value for key, value in per_session.items()}
        graph["root"].update(
            root_panel(
                own_drawn.get(graph["session"], []),
                counts_drawn.get(graph["session"], {}),
            )
        )

    plan = read_ledger(project, name, listing_failed)
    audit = audit_path(project)
    try:
        audit_mtime: float | None = audit.stat().st_mtime
    except OSError:
        audit_mtime = None
    all_counts = {
        **counts,
        "events": len(events),
        "sessions": len(sessions),
        "plans": len(plans),
        "unreadable_lines": lost,
        # T143: hand-off lines this response withheld because the record
        # itself shows the launch never took. A loss would be counted; this
        # is not a loss, so it is counted separately and by its own name -
        # the log still holds every one of these lines. ``None`` here is a
        # THIRD, distinguishable fact - not zero: the filter could not be
        # reached at all (see ``_withhold_never_took``), so nothing was
        # withheld and a ghost may still be showing as a live agent above.
        # A reader must be able to tell that apart from a clean run that
        # withheld nothing, which is exactly why this is not folded into 0.
        "withheld_launches": withheld_launches,
        # Counted exactly as a corrupt audit line is (see "Failure policy"):
        # 0 or 1, because the page reads ONE ledger per request. A listed
        # ledger that could not be opened is a loss, and so - a DIFFERENT
        # loss, T36 - is a ledger DIRECTORY that could not even be listed;
        # neither is an empty ledger.
        "unreadable_plans": 1 if plan["state"] in ("unreadable", "listing_failed") else 0,
        # T29: the one figure the document title carries - every OPEN
        # item, cross-session, because that is exactly the set of things
        # on this page a log reader cannot resolve without a human.
        "attention": len(open_rendered),
        # T4: how many hand-offs are open right now - the header figure that
        # joins the other four beside the canvas. Counted from the same open
        # list the canvas and the open rows are drawn from, cross-session as
        # every other header figure is, and NOT the same number as
        # ``attention``, which also counts an open session line.
        # T109: an ``open_handoff`` row can itself already read FINISHED (a
        # ``subagent_stop`` matched it before its own ``handoff_end`` did) -
        # T103 gave the pill this word, but this figure never learned it, so
        # it counted a delegation the canvas already draws as done among
        # those still working. Excluded here the same way the canvas already
        # excludes it from its own ``open`` figure (see ``compute_graph``'s
        # ``"open": state != "finished"``), so the two can never disagree.
        "working": sum(
            1
            for item in open_rendered
            if item["row_kind"] == "open_handoff" and item.get("delegation_state") != "finished"
        ),
    }
    # T106: each roster chip carries the identifier of the MOST RECENT
    # delegation of its own agent type currently drawn on the canvas
    # (``latest_node_of_agent_type``), redacted the same way its own
    # ``agent_type`` field already is - the two are compared as the page's
    # own rendered rows spell them, not as the raw log does, for the exact
    # reason ``test_the_drawer_is_looked_up_by_the_session_the_canvas_names``
    # already pins for the centre panel.
    roster_rows = []
    for entry in compute_roster(open_items, groups):
        agent_type = redact(entry["agent_type"])
        target = latest_node_of_agent_type(graph["nodes"], agent_type)
        roster_rows.append(
            {**entry, "agent_type": agent_type, "node_key": _node_key(target) if target else None}
        )
    # T108: fed the SAME session identity the canvas already resolved
    # (``graph["session"]``) - never a second resolution built from the
    # selected LEDGER's own filename. A plan's name carries ``sess8`` (the
    # first 8 characters of the session id - see ``KeelEvent.sess8`` in
    # ``hooks/keel_events.py``), but every audit line's own ``session`` field
    # carries the FULL id, so comparing the two by equality (a real defect
    # this task's own review caught against the live log) matches nothing
    # and every session reads a false "quiet" forever. ``compute_graph``
    # already picked the one full-id session whose newest line is newest -
    # exactly what "live or historical" needs to ask about - so this reuses
    # that value rather than inventing a shorter one that can never match a
    # raw event again. Already redacted, the same way every other identifier
    # ``graph`` carries already is.
    liveness = session_liveness(events, graph["session"], now)
    state = {
        "project": str(redact(str(project.resolve()))),
        "arming": arming(project),
        "counts": all_counts,
        # T29: the exact string the tab carries, decided here (the page only
        # assigns it), so a test reads what a reader would actually see.
        "title": document_title(all_counts),
        # What could NOT be read, in words, for the same reason.
        "loss_note": loss_note(all_counts),
        "withheld_note": withheld_note(all_counts),
        "open": open_rendered,
        "feed": rows,
        # T4: the delegation canvas - one session, one node per hand-off it
        # made, one edge from the session to each of them, and every label on
        # them decided here.
        "graph": graph,
        "plans": plans,
        # T31: acceptance criteria per task, shown rather than parsed and
        # discarded, the terminal-against-total figure they are derived from
        # in the same pass, and WHICH outcome reading the ledger had.
        "plan": plan,
        # T31: the delegation roster - every agent type keel has run, its
        # run count, whether one of its hand-offs is open right now, and the
        # label saying so.
        "roster": roster_rows,
        # T119: the legend bar at the foot - keel's own agents and every
        # other type this roster carries, each with the one-line purpose and
        # the dot colour the page shows for it. Built from the roster rows
        # just rendered, so the bar can never fail to explain a chip that is
        # on screen beside it.
        "legend": legend_entries(roster_rows),
        "audit_mtime": audit_mtime,
        # T108: live/ended/quiet/none for the session the CANVAS draws, and
        # the word and sentence the header's own pill shows for it.
        "session_liveness": liveness,
        "now": now,
        "readonly": True,
    }
    # T30's redraw gate, decided HERE: the page compares two fingerprints
    # instead of two payloads, so "did anything but the clock change?" is a
    # value a test can assert rather than a comparison buried in the page.
    state["content_digest"] = content_digest(state)
    return state


# -------------------------------------------------------------------- server


def _host_allowed(host_header: str | None, port: int) -> bool:
    """True when a ``GET``/``HEAD`` request's ``Host`` header may be routed
    at all (T38): it names the loopback interface actually bound, at the
    port actually bound, under either accepted spelling - or it carries no
    ``Host`` header at all.

    Guards against DNS rebinding - a page served from an attacker's own
    domain, pointed at ``127.0.0.1``, is SAME-ORIGIN to the browser the
    instant the name resolves, so the security headers this module already
    sends never reach it; only checking what the REQUEST ITSELF claims to be
    talking to can catch that (see the module docstring, "Host validation").

    A missing header is ACCEPTED rather than refused: every real browser
    sends one, so its absence is not the attack being guarded against, and
    refusing it would break a launcher probing this server with a client
    that omits one. Matching is exact against ``<name>:<port>`` for each name
    in ``_HOST_NAMES``, case-insensitive - a bare name with no port, an IPv6
    form, or a name that merely resolves to loopback are all refused, because
    none of them is the literal string this server's own address bar would
    show.
    """
    if host_header is None or not host_header.strip():
        return True
    candidate = host_header.strip().lower()
    return any(candidate == f"{name}:{port}".lower() for name in _HOST_NAMES)


class KeelDashboardHandler(BaseHTTPRequestHandler):
    """Three read routes, four refusals, and no filesystem write anywhere.

    ``project`` is set on the subclass built by ``build_server`` rather than
    read from a module global, so two viewers in one process cannot see each
    other's project.
    """

    project: Path = Path(".")
    server_version = "keel-dashboard"
    sys_version = ""

    # ------------------------------------------------------------- plumbing

    def _drain_request_body(self) -> None:
        """Read and DISCARD any request body, so the reply can be delivered.

        Nothing is parsed and nothing is kept: the bytes go nowhere. This
        exists only because an unread body makes the operating system reset
        the connection when the handler closes it, and a refusal the client
        never receives is indistinguishable from a crash.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return
        if 0 < length <= MAX_DRAIN_BYTES:
            self.rfile.read(length)
        elif length > MAX_DRAIN_BYTES:
            self.close_connection = True

    def _send_security_headers(self) -> None:
        """``SECURITY_HEADERS`` (T27c), on every response this server sends -
        read or refused, so a browser is told the same thing either way."""
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        """One response path for every route, read or refused."""
        self._drain_request_body()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence per-request console noise; the URL line is the only output."""

    # ---------------------------------------------------------------- reads

    def _host_ok(self) -> bool:
        """This request's ``Host`` header, checked against the interface and
        port THIS process actually bound (T38) - read fresh from the live
        socket on every call, never cached, so it can never drift from what
        is actually listening. See ``_host_allowed`` for what is accepted and
        why, and "Host validation" in the module docstring for the threat."""
        return _host_allowed(self.headers.get("Host"), self.server.server_address[1])

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        """The only method that reads anything. ``Host`` is checked BEFORE
        either route or 404 (T38) - refusing after routing would mean the
        routing itself already trusted the request. Then three routes, then
        404."""
        if not self._host_ok():
            self._send(HOST_REFUSED_STATUS, HOST_REFUSED_BODY, "text/plain; charset=utf-8")
            return
        parsed = urlparse(self.path)
        route = parsed.path
        if route in ("/", "/index.html"):
            self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if route == "/api/state":
            selected = (parse_qs(parsed.query).get("plan") or [""])[0]
            body = json.dumps(read_state(self.project, selected), default=str)
            self._send(200, body.encode("utf-8"), "application/json; charset=utf-8")
            return
        if route == "/api/plan":
            name = (parse_qs(parsed.query).get("name") or [""])[0]
            text = read_plan(self.project, name)
            if text is None:
                self._send(404, b"no such ledger", "text/plain; charset=utf-8")
                return
            self._send(200, text.encode("utf-8"), "text/plain; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_HEAD(self) -> None:  # noqa: N802
        """Same routing, no body. Still a read."""
        self.do_GET()

    # ------------------------------------------------------------ refusals

    def _refuse_write(self) -> None:
        """Every state-changing method lands here. It touches no file.

        405 rather than 404: the honest answer to ``POST /api/state`` is not
        "there is no such thing" but "this server does not change anything".
        """
        body = (
            "keel dashboard is read-only: it has no write route, and this "
            "method is refused before any handler runs.\n"
        ).encode("utf-8")
        self._drain_request_body()
        self.send_response(405)
        self.send_header("Allow", "GET, HEAD")
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._send_security_headers()
        self.end_headers()
        self.wfile.write(body)

    do_POST = _refuse_write
    do_PUT = _refuse_write
    do_PATCH = _refuse_write
    do_DELETE = _refuse_write


class _KeelHTTPServer(ThreadingHTTPServer):
    """``ThreadingHTTPServer`` with address reuse turned OFF.

    ``http.server.HTTPServer`` inherits ``allow_reuse_address = 1``, which
    sets ``SO_REUSEADDR`` before every bind. On Windows that flag does not
    just survive a TIME_WAIT socket (the POSIX reason it exists) - it lets a
    SECOND process bind the SAME address and port while a first one is
    actively listening on it, silently, with no exception raised. Found
    while a since-reverted derived-port scheme was being built (a fixed port
    makes the collision trivial to trigger), the defect is independent of
    that design and is kept: with reuse OFF, a second process asking for a
    port a first one still holds gets ``OSError`` instead of an unreachable,
    silent second listener.
    """

    allow_reuse_address = False


def build_server(project: Path) -> ThreadingHTTPServer:
    """Bind ``HOST`` on an EPHEMERAL port and return the server, not yet
    serving (R19).

    Port 0 asks the operating system for whatever loopback port is free.
    Nothing here derives a port from the project path, a user id or anything
    else - see "Ports and the port hint" in the module docstring for why a
    scheme that once did was reverted. Raises ``DashboardError`` when the
    project was never adopted, or the bind itself fails - the caller turns
    either into exit 2.
    """
    project = Path(project)
    if not (project / KEEL_DIRNAME).is_dir():
        raise DashboardError(
            f"{redact(str(project))} has no {KEEL_DIRNAME}/ - there is nothing to view"
        )
    handler = type("BoundKeelDashboardHandler", (KeelDashboardHandler,), {"project": project})
    try:
        return _KeelHTTPServer((HOST, 0), handler)
    except OSError as exc:
        raise DashboardError(f"cannot bind {HOST} on an ephemeral port: {exc}") from exc


def server_url(server: ThreadingHTTPServer) -> str:
    """``http://127.0.0.1:<bound port>/`` - the ephemeral port the operating
    system assigned (R19); never derived from the project or anything else."""
    return f"http://{HOST}:{server.server_address[1]}/"


def hint_dir(project: Path) -> Path:
    """The directory this project's viewer files live in, written or not."""
    return Path(project).joinpath(*HINT_SUBPATH)


def hint_filename(pid: int, port: int) -> str:
    """The ONE filename the viewer running as ``pid`` on ``port`` may write.

    Both numbers come from the operating system - ``os.getpid`` and the
    bound socket - and both are forced through ``int`` here, so the name is
    digits and dashes whatever was passed and no path can be built out of a
    caller's string.
    """
    return f"{HINT_PREFIX}{int(pid)}-{int(port)}{HINT_SUFFIX}"


def is_hint_name(name: str) -> bool:
    """Whether ``name`` is a per-viewer hint file this module would write.

    A shape test, so the reader parses only its own files and leaves
    everything else the shared cache holds alone - including the single
    ``keel-dashboard-hint.json`` an older version of this module wrote,
    which carries no dash after ``hint`` and so is not a candidate.
    """
    return (
        name.startswith(HINT_PREFIX)
        and name.endswith(HINT_SUFFIX)
        and len(name) > len(HINT_PREFIX) + len(HINT_SUFFIX)
    )


def hint_path(project: Path, pid: int, port: int) -> Path:
    """Where the viewer ``(pid, port)`` writes its own hint file, and the
    only path in that directory it is ever allowed to write or delete."""
    return hint_dir(project) / hint_filename(pid, port)


class Hint(NamedTuple):
    """One viewer's own hint file: the path it wrote, and the ``(pid, port)``
    that names it.

    ``remove_hint`` deletes exactly ``path`` and consults nothing else, so
    this is the whole of what a viewer needs to take back its own record
    without touching a file anyone else wrote.
    """

    path: Path
    pid: int
    port: int


class HintScan(NamedTuple):
    """What a reader found in the hint directory, with the losses SEPARATE
    from the finding (T35).

    ``viewers``     every file that parsed as a viewer, oldest first.
    ``unreadable``  how many candidate files did NOT - unparseable, wrongly
                    shaped, wrongly typed, or named for a different pid and
                    port than they carry.
    ``listing_failed``  the directory itself could not be listed.

    Three values rather than one list, because "no viewer is running", "one
    file here is rubbish and a viewer may well be running" and "this
    directory cannot be read at all" are three different answers and a
    reader that cannot tell them apart will report a loss as an absence.
    """

    viewers: list[dict[str, Any]]
    unreadable: int
    listing_failed: bool


def _read_hint_file(path: Path) -> dict[str, Any] | None:
    """One viewer's four documented fields, or ``None`` if this file is not
    a viewer's hint.

    Returns a NEW mapping carrying only ``url``, ``port``, ``pid`` and
    ``started_at``: whatever else a stale or hand-written file holds is left
    behind rather than handed to a launcher. ``url`` must be exactly this
    module's own loopback url for that port - a hint file naming any other
    host is rubbish, not a viewer, and a reader must never be pointed at it.
    The filename must be the one that pid and port would have written, so a
    file's name and its contents cannot disagree.

    The guard is deliberately ``Exception``, not ``OSError``: ``json.loads``
    raises ``RecursionError`` on deeply nested input, and a decoding failure
    raises ``UnicodeDecodeError``. Neither may reach a caller that is
    starting or stopping a server.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            return None
        port, pid = payload.get("port"), payload.get("pid")
        url, started_at = payload.get("url"), payload.get("started_at")
        if isinstance(port, bool) or not isinstance(port, int):
            return None
        if isinstance(pid, bool) or not isinstance(pid, int):
            return None
        if not isinstance(url, str) or not isinstance(started_at, str):
            return None
        if url != f"http://{HOST}:{port}/":
            return None
        if path.name != hint_filename(pid, port):
            return None
        return {"url": url, "port": port, "pid": pid, "started_at": started_at}
    except Exception:
        return None


def read_hints(project: Path) -> HintScan:
    """The reader's whole side of the hint (T35): every viewer of this
    project that could be read, how many files could not be, and whether the
    directory itself could be listed.

    Several viewers are ordinary - the directory is a function of the
    project, and ``keel dashboard`` twice in two terminals is a normal day.
    Every entry is a HINT: probe its url before trusting it, exactly as each
    file's own ``note`` says, because a viewer that was killed rather than
    stopped left its file behind. ``started_at`` lets a reader judge age
    without probing.

    A MISSING directory is an ordinary "no viewers", not a loss: nothing
    creates the cache until a viewer runs. Every other listing failure comes
    back as ``listing_failed`` rather than as an empty list, for the same
    reason ``list_plans`` refuses to report a failed listing as "no
    ledgers": a loss dressed as a fact is the one answer a reader cannot
    recover from.
    """
    viewers: list[dict[str, Any]] = []
    unreadable = 0
    try:
        entries = sorted(hint_dir(project).iterdir())
    except FileNotFoundError:
        return HintScan(viewers, 0, False)
    except OSError:
        return HintScan(viewers, 0, True)
    for entry in entries:
        if not is_hint_name(entry.name):
            continue
        parsed = _read_hint_file(entry)
        if parsed is None:
            unreadable += 1
        else:
            viewers.append(parsed)
    viewers.sort(key=lambda viewer: (viewer["started_at"], viewer["port"]))
    return HintScan(viewers, unreadable, False)


def write_hint(project: Path, server: ThreadingHTTPServer) -> Hint | None:
    """Best-effort: write THIS viewer's own hint file - its bound port,
    process id and start time - so a launcher can find a running viewer
    without guessing.

    One file, written ONCE, named for this process and this port. Nothing is
    read here: not the directory, not another viewer's file, not this
    process's own. That is what makes registering unable to erase anybody -
    the shape this replaced read a shared file, treated an unparseable read
    as "no other viewers", and rewrote the file from that, so one corrupt
    file cost every other viewer its record at the next start.

    Returns the registration to hand back to ``remove_hint``, or ``None``
    when the write failed. NEVER raises, and the guard is ``Exception``
    rather than ``OSError``: a cache directory that cannot be created or
    written, or anything else at all, is reported on stderr and the server
    starts, serves and exits exactly as it would with no hint at all.
    """
    try:
        pid, port = os.getpid(), int(server.server_address[1])
        path = hint_path(project, pid, port)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "hint": True,
            "note": HINT_NOTE,
            "url": server_url(server),
            "port": port,
            "pid": pid,
            "started_at": utc_now(),
        }
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return Hint(path, pid, port)
    except Exception as exc:
        print(
            f"keel dashboard: could not write the port hint ({exc}); continuing without one.",
            file=sys.stderr,
        )
        return None


def remove_hint(hint: Hint | None) -> None:
    """Delete exactly this viewer's own hint file on a clean exit.

    One ``unlink`` of one path this process wrote. Nothing is read, no
    remainder is computed, and no judgement is ever made about the directory
    as a whole - so a corrupt file cannot lead this viewer to delete a
    record of another that is still serving, which is precisely what the
    shared list allowed. A file already gone is not an error.

    NEVER raises: the guard is ``Exception``, because this runs in ``main``'s
    ``finally`` on the way out and nothing that happens here may abort the
    shutdown path, skip ``server_close`` or change the exit code.
    """
    if hint is None:
        return
    try:
        hint.path.unlink(missing_ok=True)
    except Exception as exc:
        print(f"keel dashboard: could not remove the port hint ({exc}).", file=sys.stderr)


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>keel — read-only</title>
<style>
/* T6: the palette and the shape of the two pinned references - a near-black,
   faintly navy ground carrying a dot grid, card surfaces a shade lighter,
   thin light borders, curved connector wires and small coloured pills. Every
   colour, shape and font is declared HERE: the content policy permits one
   inline style block and forbids every external stylesheet, font and image,
   so there is nothing on this page to fetch and no network to fetch it over.
   The dot grid is a CSS gradient rather than an image for the same reason. */
:root{--bg:#070a11;--grid:rgba(133,150,186,.13);--panel:#0d121c;--head:#101724;
--card:#161d2a;--card2:#1c2434;--line:#2a3243;--line2:#3a4457;--edge:#414c61;
--ink:#e9eef8;--ink2:#9daac2;--ink3:#5e6b85;--good:#46c988;--bad:#ef6470;
--warn:#e9ba3a;--info:#5f9dfb;--root:#8b93ff}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--ink);display:flex;flex-direction:column;
font:400 13.5px/1.45 "Segoe UI",system-ui,sans-serif;overflow:hidden}
header{display:flex;align-items:center;gap:12px;padding:9px 16px;flex:none;
border-bottom:1px solid var(--line);background:var(--head);flex-wrap:wrap}
/* T119: the header bar's LEFT CLUSTER - the page's identity in the
   reference's own order (title, project, arming, read-only, liveness) plus
   the two figures the reference has no tile for (`#corpus`: events and
   sessions). It takes the room the tiles do not, and wraps rather than
   pushing them off the bar. */
.hleft{display:flex;align-items:center;gap:10px;flex-wrap:wrap;min-width:0;
flex:1 1 auto}
h1{font-size:15px;font-weight:650;letter-spacing:.04em}
.tag{font-size:11.5px;color:var(--ink2);border:1px solid var(--line);
border-radius:20px;padding:3px 11px;overflow-wrap:break-word;min-width:0}
.tag.armed{color:var(--good);border-color:var(--good)}
.tag.ro{color:var(--warn);border-color:var(--warn)}
/* T108: the session pill's two shapes. LIVE is the reference's green pill,
   unmistakable next to the amber "read-only" tag beside it. HISTORICAL is
   its own explicit rendering - dashed, never green, never blank - so its
   absence of the live pill can never be read as a missing badge; ended and
   quiet share this one shape and differ only in the word printed inside it,
   because the acceptance this task carries asks for the SHAPE to be binary
   (live vs historical), not a third colour for a distinction the record
   itself already states in words. */
.tag.live{color:var(--good);border-color:var(--good)}
.tag.historical{color:var(--ink2);border-color:var(--line2);border-style:dashed}
#stats{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:4px 11px;text-align:center;min-width:74px}
.stat b{display:block;font-size:16px;font-variant-numeric:tabular-nums}
.stat span{font-size:9.5px;color:var(--ink3);text-transform:uppercase;
letter-spacing:.08em}
/* T6: the canvas is the PRIMARY region - `.stage` is the only flexible child
   of the canvas area, and that area is the only flexible child of `main`, so
   every pixel the sidebar gives up when a reader collapses it goes to the
   canvas and nothing else.
   T119 RE-SEATED THE REGIONS AND MOVED NO PANE'S MARKUP. `main` is still one
   flex row; what changed is `order`, so the sidebar renders at the RIGHT
   while staying first in the document - the panes are still written where
   they always were, which is why nothing about how they behave had to be
   touched to move them. Source order: sidebar, canvas area, drawer. Painted
   order: canvas area (1), drawer (2), sidebar (3). */
main{flex:1;display:flex;min-height:0;min-width:0}
/* T119: the canvas AREA - the canvas itself with the roster row along its
   foot. It is the one flexible child of `main` and it never scrolls
   horizontally: `min-width:0` lets it be narrower than its own content, and
   `.stage` inside it takes the scrolling. */
#canvasarea{order:1;flex:1 1 auto;min-width:0;min-height:0;display:flex;
flex-direction:column}
/* T119: the SIDEBAR - two stacked sections sharing its height, the ledger
   above and the audit feed below, exactly as the reference stacks them. A
   GRID rather than a flex column on purpose: each section keeps `flex:none`
   (it is not a flex item here at all) and the two rows are `minmax(0,1fr)`,
   which is what lets each section scroll its OWN list instead of the
   sidebar growing to the taller of the two. It declares no width of its
   own: the column is as wide as its widest section, which is what lets
   collapsing BOTH sections hand the width to the canvas. */
#side{display:grid;grid-template-rows:minmax(0,1fr) minmax(0,1fr);order:3;
flex:none;min-height:0;border-left:1px solid var(--line);
background:var(--panel)}
/* T119: WHAT A COLLAPSE GIVES BACK, in three shapes and no fourth. T6's two
   panels sat side by side and each handed its width to the canvas; stacked
   in one column they cannot, and a shut section beside a 380px sibling with
   an equal row would be a 34px rail against dead space - a collapse that
   bought the reader nothing. So a SHUT row sizes to the rail itself
   (`max-content`) and the OPEN section keeps the only flexible row, taking
   the height that frees; with both shut there is no full-width section left
   holding the column open, so the column is the rail's own width and the
   canvas takes the rest. Written with `:has()` because the collapse handler
   toggles ONE class on ONE section and reads nothing (T6), and that must
   stay true: the sidebar answers the class, the handler is not given a
   second thing to write. Where `:has()` is not supported these three rules
   simply do not apply and the two rows stay equal - the shape this sidebar
   had before them, never a broken one. */
#side:has(#p-ledger.shut){grid-template-rows:max-content minmax(0,1fr)}
#side:has(#p-feed.shut){grid-template-rows:minmax(0,1fr) max-content}
#side:has(#p-ledger.shut):has(#p-feed.shut){grid-template-rows:max-content max-content}
.panel{width:380px;flex:none;display:flex;flex-direction:column;min-height:0;
background:var(--panel);border-bottom:1px solid var(--line)}
/* The rail a shut section becomes: its own width, and - because its row is
   sized to it rather than to a share of the column - its own height too. */
.panel.shut{width:34px}
.panel.shut>:not(.phead){display:none}
.panel.shut .xtra{display:none}
.panel.shut .phead{flex-direction:column;align-items:center;height:100%;
padding:9px 0;gap:12px}
.panel.shut .ttl{writing-mode:vertical-rl;text-orientation:mixed}
.phead{font-size:11px;text-transform:uppercase;letter-spacing:.1em;flex:none;
color:var(--ink3);padding:10px 12px 7px;display:flex;gap:9px;
align-items:center;flex-wrap:wrap;font-weight:600}
.ttl{color:var(--ink2)}
.tog{background:var(--card);color:var(--ink2);border:1px solid var(--line2);
border-radius:7px;width:21px;height:21px;line-height:1;font:inherit;
font-size:13px;cursor:pointer;flex:none;padding:0}
.tog:hover{border-color:var(--info);color:var(--info)}
select{background:var(--card);color:var(--ink);border:1px solid var(--line);
border-radius:14px;padding:2px 9px;font:inherit;font-size:11.5px;
flex:1 1 110px;min-width:0;max-width:100%}
#ledger,#feed{flex:1;overflow-y:auto;padding:0 12px 14px;min-height:0}
.task{display:flex;gap:9px;padding:6px 5px;font-size:12.5px;
border-bottom:1px solid var(--card)}
.task .mark{width:1.6em;text-align:center;flex:none}
.t-done .mark{color:var(--good)}.t-open .mark{color:var(--ink3)}
.t-blocked .mark{color:var(--bad)}.t-decision .mark{color:var(--warn)}
.t-inflight .mark{color:var(--info)}
.t-done .txt{color:var(--ink2)}
/* T5: a feed row is a WRAPPING flex row, and its text column may shrink no
   further than its own longest word. `overflow-wrap:anywhere` (what this was)
   also shrinks a flex item's min-content size to a single CHARACTER, so a
   long note beside it could squeeze the column until a session identifier
   rendered one character per line and the row stood hundreds of pixels tall.
   `break-word` still breaks a word too long for its own line and leaves
   min-content alone, which is exactly the difference wanted here. */
.ev{display:flex;flex-wrap:wrap;gap:9px;padding:5px 5px;font-size:11.5px;
color:var(--ink2);border-bottom:1px solid var(--card);
border-left:3px solid transparent;padding-left:8px}
.ev .t{color:var(--ink3);flex:none;font-variant-numeric:tabular-nums}
.ev b{color:var(--ink);font-weight:650}
.ev.block{border-left-color:var(--bad)}
.ev.hand{border-left-color:var(--info)}
.ev.sess{border-left-color:var(--warn)}
/* T120 addendum: the per-row icon, the same shape `.arow .ic` already draws
   for the drawer's own rows (T105) - one character wide, muted, centred. */
.ev .ic{flex:none;color:var(--ink3);width:1em;text-align:center}
.ev .d{flex:1 1 240px;min-width:0;overflow-wrap:break-word}
.ev.openrow{border-left-color:var(--warn);background:rgba(233,186,58,.08)}
.ev.openrow b{color:var(--warn)}
.meta{color:var(--ink3);margin-left:auto;flex:none;padding-left:8px}
.filters{display:flex;gap:6px;flex-wrap:wrap;padding:0 12px 8px;flex:none}
.chip{background:var(--card);color:var(--ink2);border:1px solid var(--line);
border-radius:12px;padding:2px 9px;font:inherit;font-size:10.5px;cursor:pointer}
.chip span{color:var(--ink3);margin-left:4px}
.chip.off{opacity:.4}
.grp{border-bottom:1px solid var(--card);padding:4px 5px 4px 8px;font-size:11.5px}
.grp summary{cursor:pointer;color:var(--ink2);display:flex;flex-wrap:wrap;
gap:9px;align-items:baseline;list-style:none}
.grp summary::-webkit-details-marker{display:none}
.grp summary .t{color:var(--ink3);flex:none;font-variant-numeric:tabular-nums}
.grp summary b{color:var(--info)}
.grp .body{margin:6px 0 2px 20px;border-left:2px solid var(--line);padding-left:10px}
/* An inferred grouping must not look like a known one (d): dashed, not
   solid, and it says why in words rather than relying on the styling. */
.grp.inf summary b{color:var(--warn)}
.grp.inf .body{border-left:2px dashed var(--warn)}
.grp .why{color:var(--warn);font-size:10.5px;padding:2px 0 5px;
overflow-wrap:anywhere}
.ev.inf{border-left-color:var(--warn);border-left-style:dashed}
.ev .inf-tag{color:var(--warn);flex:none;font-size:10px;
text-transform:uppercase;letter-spacing:.06em}
/* T119: the LEGEND BAR at the very foot - the reference's last region. One
   row mapping every agent on the roster to its dot and its own one-line
   purpose, and under it the three sentences the footer already carried,
   which lost nothing to make room. */
footer{border-top:1px solid var(--line);background:var(--head);flex:none;
padding:7px 16px;font-size:11px;color:var(--ink3);display:flex;
flex-direction:column;gap:5px}
#agentlegend{display:flex;gap:14px;flex-wrap:wrap;align-items:center}
.footnotes{display:flex;gap:16px;flex-wrap:wrap}
.lg{display:flex;gap:6px;align-items:center;color:var(--ink3);font-size:10.5px}
.lg b{color:var(--ink2);font-weight:600}
/* One dot per colour FAMILY the server named (`agent_tone`). The page maps a
   token to a colour and decides nothing else - which family a type is in was
   decided from its own name, server-side, like every other reading here. */
.lgdot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--ink3)}
.lgdot.tone-exec{background:var(--info)}
.lgdot.tone-deep{background:var(--root)}
.lgdot.tone-scout{background:var(--good)}
.lgdot.tone-review{background:var(--warn)}
.empty{color:var(--ink3);font-size:12px;padding:14px 6px}
/* T31: acceptance criteria, shown rather than parsed and discarded. */
.task{padding:6px 5px;font-size:12.5px;border-bottom:1px solid var(--card)}
.task-line{display:flex;gap:9px}
.accept{margin:4px 0 2px 1.6em}
.accept summary{cursor:pointer;color:var(--ink3);font-size:10.5px;
text-transform:uppercase;letter-spacing:.06em;list-style:none}
.accept summary::-webkit-details-marker{display:none}
.accepttxt{color:var(--ink2);font-size:11.5px;padding:4px 2px 2px;overflow-wrap:anywhere}
#progress{color:var(--ink3);font-weight:400;text-transform:none;letter-spacing:0;
font-size:10.5px}
/* T31: the delegation roster - one strip, always visible.
   T119 re-seats it where the reference puts it: along the FOOT of the canvas
   area rather than under the header, still one full-width strip, still every
   chip it carried. It never scrolls with the canvas (`flex:none`, outside
   `.stage`), so a session with many cards cannot push it off screen. */
.roster{display:flex;gap:8px;flex-wrap:wrap;padding:6px 16px;flex:none;
background:var(--head);border-top:1px solid var(--line)}
.roster .a{background:var(--card);border:1px solid var(--line);border-radius:12px;
padding:3px 10px;font-size:11px;color:var(--ink2);display:flex;gap:6px;align-items:center}
.roster .a b{color:var(--ink)}
.roster .a.working{border-color:var(--info);color:var(--info)}
.roster .a.working b{color:var(--info)}
.roster .dot{width:6px;height:6px;border-radius:50%;background:var(--ink3);flex:none}
.roster .a.working .dot{background:var(--info)}
/* T106: a chip naming a delegation currently on the canvas opens that
   delegation's own panel - the same affordance the canvas cards themselves
   carry (`.rootnode`/`.node` below). A chip with no card drawn right now
   (`node_key` is null) gets no pointer cursor: there is nothing behind it
   to open. */
.roster .a[data-node-key]{cursor:pointer}
/* T4/T6: the delegation canvas - the session as one node at the centre, a
   card per hand-off it made arranged around it, and a curved wire drawn from
   the session to each card. Every card hangs off the session and never off
   another card, because the record carries no ordering between two hand-offs.
   T6 makes this the page's PRIMARY region: it fills the ground the two left
   panels do not take, and it takes theirs as well when they are collapsed. */
.stage{flex:1 1 auto;min-width:0;min-height:0;display:flex;flex-direction:column;
overflow:auto;background-color:var(--bg);
background-image:radial-gradient(circle at 1px 1px,var(--grid) 1px,transparent 0);
background-size:22px 22px}
.stagehead{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;flex:none;
padding:11px 18px 2px;font-size:11px;text-transform:uppercase;
letter-spacing:.1em;color:var(--ink3);font-weight:600}
#graphnote{color:var(--ink3);font-weight:400;text-transform:none;
letter-spacing:0;font-size:10.5px;overflow-wrap:break-word;min-width:0}
/* `flex:1 0 auto`: the canvas may GROW into the room the stage has and may
   never be shrunk below the cards it is holding, so a session with many
   hand-offs scrolls the stage instead of having its top row clipped by a
   centred line that is taller than its own box. */
#canvas{position:relative;flex:1 0 auto;display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:30px;padding:22px 18px}
#wires{position:absolute;left:0;top:0;width:100%;height:100%;
pointer-events:none;overflow:visible}
.wire{fill:none;stroke:var(--edge);stroke-width:1.2;stroke-dasharray:4 5}
.wire.live{stroke:var(--warn);stroke-dasharray:none;stroke-width:1.7}
.port{fill:var(--bg);stroke:var(--edge);stroke-width:1.2}
.port.live{stroke:var(--warn)}
.port.hub{fill:var(--panel);stroke:var(--root);stroke-width:1.4}
/* T110: THE ONE MOVING WIRE. A second path laid over the live wire only -
   `drawWires` emits it for a card carrying `.live` and for no other, so the
   marker `.wire.flow` cannot exist on the canvas unless a delegation is
   open. The drift travels centre-to-card at the dash period (2+10), which
   is why the offset lands exactly on -12 and the loop has no seam. The
   solid base wire underneath is untouched: this adds motion to the live
   wire, it does not restyle it. */
.wire.flow{stroke:var(--warn);stroke-width:1.7;stroke-dasharray:2 10;
stroke-linecap:round;animation:livewire 1.4s linear infinite}
@keyframes livewire{to{stroke-dashoffset:-12}}
.ring{position:relative;z-index:1;display:flex;flex-wrap:wrap;gap:16px;
justify-content:center;width:100%}
/* T110: the CENTRE node, larger than a worker card and treated as the
   reference treats it - a disc, a bold name, a grey line under it, the chip
   naming what this session last did and the path line under that. Its role
   tag rides the top border, the way a worker card's AGENT tag does. */
.rootnode{position:relative;z-index:2;background:var(--card2);
border:1px solid var(--root);border-radius:18px;padding:15px 26px 12px;
min-width:286px;max-width:380px;text-align:center;overflow-wrap:break-word;
box-shadow:0 0 0 7px rgba(139,147,255,.06)}
/* T110: THE WARM HALO, and the one rule that decides when it is there: the
   session is LIVE by the server's own reading (T108's pill - the page reads
   that field and derives nothing of its own). It is a STILL glow, because a
   live session with nothing delegated right now is not work in flight, and
   the page must be motionless in that state. */
.rootnode.live{border-color:rgba(233,186,58,.6);
box-shadow:0 0 0 7px rgba(233,186,58,.09),0 0 30px 5px rgba(233,186,58,.17)}
/* ACTING = live AND at least one delegation open (`root.open`). Only then
   does the halo breathe. What the breathing says is printed under the name
   in words by `graph_root_label` ("N open now"), so a reader who cannot
   perceive motion is told the same thing. */
.rootnode.live.acting{animation:livehalo 2.8s ease-in-out infinite}
@keyframes livehalo{
0%,100%{box-shadow:0 0 0 7px rgba(233,186,58,.09),0 0 30px 5px rgba(233,186,58,.17)}
50%{box-shadow:0 0 0 12px rgba(233,186,58,.13),0 0 46px 11px rgba(233,186,58,.3)}}
.rootnode .rpill{position:absolute;top:-9px;left:50%;transform:translateX(-50%);
background:var(--card2);white-space:nowrap;
color:var(--root);border:1px solid rgba(139,147,255,.5);border-radius:999px;
padding:1px 10px;font-size:9.5px;text-transform:uppercase;letter-spacing:.1em}
.rootnode.live .rpill{border-color:rgba(233,186,58,.5)}
.rootnode .avatar{width:34px;height:34px;margin:0 auto}
.rootnode .avatar .bot{width:19px;height:19px}
.rootnode.live .avatar{border-color:rgba(233,186,58,.55);color:var(--warn)}
.rootnode .who{color:var(--ink);font-size:14px;padding-top:5px;
overflow-wrap:break-word}
.rootnode .sub{color:var(--ink3);font-size:10.5px}
/* The chip naming what this session last did, and the line naming the file
   it last wrote - both the server's own already-redacted `own_activity`
   rows (T105), truncated by the STYLE BLOCK with an ellipsis rather than by
   the page, so nothing sent is thrown away before the drawer can show it in
   full. */
.rootnode .rchip{display:block;max-width:100%;margin:7px auto 0;
background:var(--card);border:1px solid var(--line2);border-radius:999px;
padding:2px 11px;font-size:10.5px;color:var(--ink2);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.rootnode .rpath{color:var(--ink3);font-size:10px;padding-top:4px;
white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.node{width:230px;background:var(--card);border:1px solid var(--line2);
border-radius:14px;padding:11px 11px 9px;font-size:11px;color:var(--ink2);
overflow-wrap:break-word;cursor:pointer;position:relative}
.node.live{border-color:rgba(233,186,58,.55);background:var(--card2)}
/* T110: the AGENT tag riding the top border, as both references draw it. It
   is a label for the KIND of card, never a claim about who ran it - what
   the record actually holds is the agent type in the line below it. */
.atag{position:absolute;top:-7px;right:11px;background:var(--bg);
border:1px solid var(--line2);border-radius:6px;padding:0 6px;
font-size:8.5px;line-height:14px;letter-spacing:.14em;color:var(--ink3)}
.node.live .atag{border-color:rgba(233,186,58,.55);color:var(--warn)}
/* T110: the circular avatar disc. The glyph inside it is drawn HERE as
   inline SVG - the content policy forbids an image and there is no network
   to fetch one over - and it is decorative, so it is hidden from a screen
   reader and every word on the card is left to say what the card is. */
.avatar{width:26px;height:26px;flex:none;border-radius:50%;
background:var(--card2);border:1px solid var(--line2);color:var(--ink2);
display:flex;align-items:center;justify-content:center}
.node.live .avatar{border-color:rgba(233,186,58,.55);color:var(--warn)}
.bot{width:15px;height:15px;fill:none;stroke:currentColor;stroke-width:1.6;
stroke-linecap:round;stroke-linejoin:round}
.bot .eye{fill:currentColor;stroke:none}
.ident{min-width:0;flex:1 1 90px;display:flex;flex-direction:column;
gap:3px;align-items:flex-start}
.cname{color:var(--ink);font-size:12px;font-weight:650}
.node .hd{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
/* The grey subtitle under the title: the agent TYPE the record holds. */
.role{background:transparent;color:var(--ink2);min-width:0;
border:1px solid var(--line);border-radius:999px;padding:1px 8px;
font-size:10px;letter-spacing:.04em;overflow-wrap:break-word}
.node.live .role{background:rgba(233,186,58,.14);color:var(--warn);
border-color:rgba(233,186,58,.45)}
.pillrow{padding:6px 0 1px}
.pill{margin-left:auto;flex:none;border:1px solid var(--line2);
border-radius:999px;padding:2px 9px;font-size:9.5px;text-transform:uppercase;
letter-spacing:.06em;color:var(--ink3)}
.pill.live{border-color:rgba(233,186,58,.55);color:var(--warn);
background:rgba(233,186,58,.1)}
/* T110: the dot in the state pill - muted on a closed card, warm on a live
   one, green behind the finished check. It PULSES on a live card and on no
   other, and it says nothing the pill's own word does not already say
   beside it. */
.pdot{display:inline-block;width:6px;height:6px;border-radius:50%;
background:var(--ink3);margin-right:6px;vertical-align:middle}
.pill.live .pdot{background:var(--warn)}
.pill.st-finished .pdot{background:var(--good)}
.node.live .pdot{animation:livedot 1.6s ease-in-out infinite}
@keyframes livedot{0%,100%{opacity:1;transform:scale(1)}
50%{opacity:.35;transform:scale(.68)}}
/* T103: FINISHED is a DIFFERENT pill, never a dimmed copy of the running
   one - a green check against the muted dot BACKGROUND and AWAITED both
   keep (the plain `.pill` rule above already reads as "still uncertain",
   so neither of those two needs a rule of its own). A reader tells finished
   apart by colour and glyph alone, without reading either word. */
.pill.st-finished{border-color:rgba(70,201,136,.55);color:var(--good);
background:rgba(70,201,136,.12)}
.node .job{color:var(--ink);padding:5px 0 3px;font-size:11.5px}
.node .foot{color:var(--ink3);display:flex;flex-wrap:wrap;gap:8px}
.node .t{font-variant-numeric:tabular-nums}
.node .why2{color:var(--warn);font-size:10px;line-height:1.35;padding-top:4px}
/* T103: the BACKGROUND note ("the record cannot yet say it ended") and the
   small last-action line under the pill - both dim, both a sentence rather
   than a value competing for the row's width, same treatment as `.why2`. */
.node .statenote{color:var(--ink3);font-size:10px;line-height:1.35;
padding-top:4px}
.node .lastact{color:var(--ink3);font-size:10px;line-height:1.35;
padding-top:3px;overflow-wrap:break-word}
.node .quiet{display:block;flex:none;font-size:10px;line-height:1.35;
padding:4px 0 0}
.legend{color:var(--ink3);font-size:10.5px;padding:4px 22px 14px;flex:none;
text-align:center;overflow-wrap:break-word}
/* T105: the centre node's drawer, the reference's frame 2. It sits BESIDE
   the canvas and takes width of its own, so the canvas narrows and keeps
   every card it was holding rather than being covered by an overlay - the
   whole point of the frame is that the cards are still there, still ticking,
   while the drawer is open. `flex:none` keeps `.stage` the only flexible
   child of `main` (T6), so nothing else on the page moves. */
.npanel{width:288px;flex:none;display:flex;flex-direction:column;min-height:0;
background:var(--panel);border-left:1px solid var(--line);overflow-y:auto;
order:2}
.npanel[hidden]{display:none}
.nphead{display:flex;gap:9px;align-items:center;flex-wrap:wrap;flex:none;
padding:10px 12px 8px;border-bottom:1px solid var(--line)}
.nphead .who{color:var(--ink);font-size:12.5px;min-width:0;
overflow-wrap:break-word;flex:1 1 120px}
.nphead .who span{color:var(--ink3)}
.npx{background:var(--card);color:var(--ink2);border:1px solid var(--line2);
border-radius:7px;width:21px;height:21px;line-height:1;font:inherit;
font-size:13px;cursor:pointer;flex:none;padding:0}
.npx:hover{border-color:var(--info);color:var(--info)}
.npsum{color:var(--ink2);font-size:11px;padding:8px 12px 0;
overflow-wrap:break-word}
.npstate{color:var(--ink3);font-size:11px;padding:3px 12px 8px;
overflow-wrap:break-word}
.npnote{color:var(--ink3);font-size:10.5px;padding:6px 12px;
overflow-wrap:break-word}
.nplist{padding:0 12px 14px}
/* One drawer row: a wall-clock time, the glyph naming the KIND, and the
   content clamped to two lines - a path or a command head is often long, and
   the reference's rows never grow past two. */
.arow{display:flex;gap:8px;padding:5px 2px;font-size:11.5px;color:var(--ink2);
border-bottom:1px solid var(--card)}
.arow .t{color:var(--ink3);flex:none;font-variant-numeric:tabular-nums}
.arow .ic{flex:none;color:var(--ink3);width:1em;text-align:center}
.arow .d{flex:1 1 auto;min-width:0;overflow-wrap:break-word;overflow:hidden;
max-height:2.9em;display:-webkit-box;-webkit-box-orient:vertical;
-webkit-line-clamp:2}
.rootnode{cursor:pointer}
.rootnode:hover{border-color:var(--info)}
/* T106: a worker card opens its own panel the same way the session node
   does - the pointer affordance is the one thing CSS decides here, never
   what the click actually does. */
.node:hover{border-color:var(--info)}
/* T31: the already-redacted detail/prompt_head fields, rendered rather than
   dropped - a dim, quoted aside next to the row that carries them. */
.d2{color:var(--ink3);font-style:italic;overflow-wrap:break-word}
/* T30: quiet-time - a label naming the threshold it crossed, never a colour
   alone, and always marked as inferred rather than measured.
   T5: the note is a full SENTENCE, so it takes a line of its own under the
   row rather than competing with the row's own text for width - it used to
   be `white-space:nowrap`, which is what made it push everything beside it
   down to nothing. */
.quiet{color:var(--warn);flex:1 1 100%;font-size:10.5px;padding-left:8px;
overflow-wrap:break-word}
/* T6: a narrow window keeps everything and rearranges it - the canvas stays
   first and stays the largest region, the two panels fall below it at full
   width, and a collapsed panel is a plain horizontal bar rather than a rail
   too narrow to read. Nothing is hidden at any width that a reader cannot
   bring back with the same control they closed it with.
   T119: the same rearrangement, one region wider - the canvas AREA (canvas
   plus roster strip) is what stays first and largest now, and the sidebar
   stops being a grid of two shared rows and becomes two full-width sections
   stacked under it, each bounded by its own `max-height` as before. This
   breakpoint is deliberately well below the 1280px width the frame is drawn
   for: at 1280 the sidebar sits BESIDE the canvas, taking 380px of it, and
   nothing on the page scrolls sideways. */
@media (max-width:1100px){
main{flex-direction:column;overflow-y:auto}
#canvasarea{order:1;flex:1 0 auto}
.stage{order:1;min-height:56vh;flex:1 0 auto}
/* T105: the drawer keeps its place BESIDE the canvas by falling directly
   under it - same order as the stage, later in the document - so a narrow
   window rearranges it exactly as it rearranges everything else, and the
   two left panels keep the order they already had. */
.npanel{order:1;width:auto;max-height:42vh;border-left:none;
border-top:1px solid var(--line)}
#side{order:2;display:block;width:auto;flex:none;border-left:none}
.panel{width:auto;max-height:42vh;border-right:none;
border-top:1px solid var(--line)}
.panel.shut{width:auto;max-height:none}
.panel.shut .phead{flex-direction:row;align-items:center;height:auto;
padding:10px 12px}
.panel.shut .ttl{writing-mode:horizontal-tb}
#stats{margin-left:0}
}
/* T110: a reader who has asked their system for less motion gets none, and
   loses nothing by it - every one of the three animations above states its
   fact in words as well (the pill's own word, the elapsed figure beside it,
   and the "N open now" line under the session's name). This is LAST in the
   block so it wins over the three rules it names, and it names exactly
   those three: there is nothing else on this page that moves. */
@media (prefers-reduced-motion:reduce){
.node.live .pdot,.rootnode.live.acting,.wire.flow{animation:none}
}
</style></head><body>
<header id="topbar">
  <div class="hleft">
    <h1>keel</h1>
    <span class="tag" id="project">…</span>
    <span class="tag" id="arming">…</span>
    <span class="tag ro">read-only · no write route</span>
    <span class="tag" id="liveness" title="…">…</span>
    <span class="tag" id="corpus" title="the whole log this page is reading">…</span>
  </div>
  <div id="stats"></div>
</header>
<main>
  <div id="side">
    <section class="panel" id="p-ledger">
      <h2 class="phead"><button type="button" class="tog" data-panel="p-ledger"
        aria-expanded="true" title="collapse or expand the ledger panel">−</button>
        <span class="ttl">Plan ledger</span>
        <span class="xtra" id="progress"></span>
        <select class="xtra" id="plansel"></select></h2>
      <div id="ledger"></div>
    </section>
    <section class="panel" id="p-feed">
      <h2 class="phead"><button type="button" class="tog" data-panel="p-feed"
        aria-expanded="true" title="collapse or expand the audit feed panel">−</button>
        <span class="ttl">Event feed</span>
        <span class="xtra" id="lost" style="color:var(--bad)"></span>
        <span class="xtra" id="withheld" title="hand-offs the record itself shows never took - withheld, not lost"></span></h2>
      <div class="filters" id="filters"></div>
      <div id="feed"></div>
    </section>
  </div>
  <div id="canvasarea">
    <div class="stage">
      <div class="stagehead"><span class="ttl">Delegations</span>
        <span id="graphnote"></span></div>
      <div id="canvas"></div>
      <div class="legend">every edge runs from this session to one hand-off it
         made; no edge joins two hand-offs, because the record carries no
         ordering between them - a card's position on this canvas says nothing
         its own start time does not already say. A card names the agent TYPE
         the record holds, never a model: the log records who was asked, never
         which model answered.</div>
    </div>
    <div class="roster" id="roster"></div>
  </div>
  <aside class="npanel" id="nodepanel" hidden></aside>
</main>
<footer id="legendbar">
  <div id="agentlegend"></div>
  <div class="footnotes">
    <span id="freshness">…</span>
    <span>.keel/audit/keel-audit.jsonl + .keel/plans/ · nothing is written</span>
    <span>quiet-time is INFERRED from gaps in the log, never measured - a log
          of completed actions cannot see a tool that has not finished yet, and
          where two hand-offs of one agent type are open at once it does not
          say which of them produced a line</span>
  </div>
</footer>
<script>
const $ = id => document.getElementById(id);
const MARK = {" ":["open","○"], "x":["done","✓"], "!":["blocked","!"],
              "?":["decision","?"], "~":["inflight","~"]};
const KIND = {gate_block:"block", stop_block:"block", handoff_start:"hand",
              handoff_end:"hand", subagent_stop:"hand", session_start:"sess",
              session_end:"sess"};
// Same kinds `COUNTED_EVENTS` computes server-side (T27a): the filter row is
// built FROM those counts, never by re-scanning events in this page.
const FILTERABLE = ["activity", "gate_block", "gate_bypass", "stop_block",
                     "override_active_at_stop", "handoff_start", "handoff_end",
                     "session_start", "session_end", "subagent_stop"];
// Routine `activity` starts hidden - the "exception" landing (T27a). Every
// other kind starts visible; toggling never touches a hand-off's collapsed
// group, only the flat feed.
const hiddenKinds = new Set(["activity"]);
// T105: one glyph per KIND the server named (`action_kind`) - a pencil for a
// write, a play mark for a command, a neutral dot for a tool in neither
// family. The page chooses the glyph and nothing else: which kind a line IS
// was decided from the record, and the glyph carries that word as its own
// title so the icon is never the only thing saying it.
const ACTION_GLYPH = {write: "✎", command: "▶", action: "·"};
// T120 addendum: one glyph per VERB FAMILY, keyed by `e.feed_verb` - the
// server's own reading of which family a row's kind belongs to
// (`feed_verb`), never a second decision made here from `e.event` itself.
// The glyph conveys nothing the sentence beside it does not already say
// (T110's own law), and it reuses the page's OWN existing vocabulary rather
// than inventing one: "finished" is `MARK.x`'s own DONE glyph and "blocked"
// is `MARK["!"]`'s own BLOCKED glyph - the very marks the ledger panel
// already draws for the same two words. A kind naming no family at all
// (`feed_verb` returns `""`) gets no icon, matched by the lookup below.
const FEED_GLYPH = {launched: "▶", "reported back": "↩", finished: MARK.x[1],
                     blocked: MARK["!"][1], session: "●"};
// T119: the two header figures the reference has no tile for. They are not
// dropped to make the picture match - they keep a seat in the header's own
// left cluster, named here so there is one list saying which figures are
// seated there rather than a second copy of the words inside a template.
const CORPUS = ["events", "sessions"];
// T110: the avatar disc both references put on every node, drawn as inline
// SVG because the content policy forbids an image and this page has no
// network to fetch one over. It is DECORATION and says so - `aria-hidden`,
// no title, no text - so nothing a reader needs is carried by a picture; the
// card's own words are the whole of what it states. One constant, so the
// centre node and a worker card cannot end up with two different discs.
const AVATAR = '<span class="avatar" aria-hidden="true">' +
  '<svg class="bot" viewBox="0 0 24 24">' +
  '<path d="M12 3.6V6.8"></path>' +
  '<circle class="eye" cx="12" cy="2.7" r="1.3"></circle>' +
  '<rect x="4.2" y="7" width="15.6" height="12" rx="4.4"></rect>' +
  '<circle class="eye" cx="9.4" cy="12.8" r="1.5"></circle>' +
  '<circle class="eye" cx="14.6" cy="12.8" r="1.5"></circle>' +
  '<path d="M9.7 16.4h4.6"></path></svg></span>';
let selected = "";
let lastState = null;
// T105: whether the centre node's drawer is open. It is the whole of the
// drawer's state - what it SHOWS is read from `lastState` every time it is
// drawn, so a poll that brings new lines updates an open drawer without the
// reader touching anything, and closing it costs nothing but this flag.
let panelOpen = false;
// T106: WHICH card the drawer shows while it is open - `null` for the
// centre session (T105's own root), or one worker card's own `openRowKey`
// (below) otherwise. Reset to `null` every time the drawer closes, so the
// next open call always states plainly which of the two it means rather
// than a stale key surviving between two unrelated openings.
let panelNodeKey = null;

const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function clock(ts){
  const m = /T(\d{2}:\d{2}:\d{2})Z/.exec(String(ts || ""));
  return m ? m[1] : "--:--:--";
}

// Whole seconds since some ISO-8601 instant, against ``now`` (also epoch
// seconds) - both supplied by the caller so this never reads the system
// clock itself; every open item's elapsed time is computed at render
// against THIS wall clock, not any timestamp the record makes about itself.
function elapsedSince(ts, now){
  const t = Date.parse(String(ts || ""));
  return Number.isNaN(t) ? null : Math.max(0, now - t / 1000);
}

function fmtDur(seconds){
  if (seconds == null) return "?";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), s = total % 60;
  if (h) return h + "h " + m + "m";
  if (m) return m + "m " + s + "s";
  return s + "s";
}

// Quiet-time (T30). The phase, the threshold that phase carries, and the
// words a crossing is stated in are ALL decided by the server
// (`_quiet_facts`, `quiet_threshold_seconds`, `quiet_note`) - including the
// case where the record cannot say which of two open hand-offs of one type
// produced a line, which is declined rather than guessed and says so in its
// own note. Nothing about that judgement lives here, so there is nothing
// here to drift out of sync with it and nothing a test could only find by
// reading this file's source text.
//
// What is left is the one thing a server cannot do: measure the gap against
// the reader's own wall clock, at render, and word the elapsed part of the
// label - shown only once the server's own threshold is actually crossed,
// because "OPEN" and its elapsed time already say enough below that.
function quietLabel(o, now){
  if (!o.last_seen_ts || !o.quiet_note) return "";
  const quietSecs = elapsedSince(o.last_seen_ts, now);
  if (quietSecs == null || quietSecs < o.quiet_threshold_seconds) return "";
  return "quiet " + fmtDur(quietSecs) + " (" + o.quiet_note + ")";
}

// T119: the header's four stat tiles, in the reference's own order, and the
// two figures it has no tile for.
// The FIVE figures below are UNCHANGED - the same five rows, the same five
// expressions, each still computed in exactly one place. What this task adds
// is a SEATING table: which of them each of the reference's boxes carries,
// the word that box prints, and the note it carries where that word is
// shorter than the count behind it (GATE BLOCKS is `gate_block` AND
// `stop_block` here, both of keel's own gates, exactly as this figure always
// was - the tile says so rather than letting the shorter word imply the
// narrower count).
// TASKS DONE is the one tile no row here holds, because it is not a count of
// audit lines at all: it is the ledger panel's OWN terminal-against-total
// figure, formatted for a box by the server (`progress_tile`) off the very
// mapping the panel's own heading already words - never a second count of
// the same task lines.
// `events` and `sessions` keep a seat in the header's left cluster
// (`#corpus`); nothing the header showed before this task is gone.
function stats(c, plan){
  const rows = [["events", c.events], ["sessions", c.sessions],
                ["hand-offs", c.handoff_start],
                ["blocks", c.gate_block + c.stop_block],
                ["working now", c.working]];
  const figure = new Map(rows);
  const tiles = [
    ["working", "working now", figure.get("working now"),
     "hand-offs open right now, across the whole log"],
    ["handoffs", "hand-offs", figure.get("hand-offs"),
     "handoff_start lines in the log"],
    ["blocks", "gate blocks", figure.get("blocks"),
     "gate_block and stop_block lines - both of keel's own gates, counted together"],
    ["tasks", "tasks done", plan.progress_tile, plan.progress_tile_note],
  ];
  $("stats").innerHTML = tiles.map(
    t => `<div class="stat" data-stat="${esc(t[0])}" title="${esc(t[3])}">` +
         `<b>${esc(t[2])}</b><span>${esc(t[1])}</span></div>`
  ).join("");
  $("corpus").textContent = CORPUS.map(k => figure.get(k) + " " + k).join(" · ");
}

// T119: the legend bar at the very foot - one row per agent, its coloured
// dot and its own one-line purpose, in the reference's own shape. Every word
// on it and the colour FAMILY each dot belongs to are the server's
// (`legend_entries`, `AGENT_ROLES`, `agent_tone`); this maps a family token
// to one class and puts the rows in the DOM, which is the same division
// every other pane on this page already keeps. The names are the record's
// own and the agents keel actually ships - there is no persona here that
// nothing else on the page could name.
function agentLegend(entries){
  const items = entries || [];
  $("agentlegend").innerHTML = items.map(
    e => `<span class="lg"><span class="lgdot tone-${esc(e.tone)}"></span>` +
         `<b>${esc(e.agent_type)}</b> = ${esc(e.role)}</span>`
  ).join("");
}

// T31: driven by the server's own parse (`parse_ledger_tasks`) rather than
// re-parsing the raw text here - one parse to keep correct, not two that
// could disagree - so the Accept clause the server already extracted is
// shown per task instead of being read and thrown away. The sentence shown
// when there are no task lines is the server's too (`plan.note`): "this
// project has no ledger" and "this ledger is listed but could not be read"
// are different facts, and this page must not be the thing that decides
// they look alike.
function ledger(plan){
  const tasks = plan.tasks || [];
  const out = [];
  for (const t of tasks) {
    const info = MARK[t.mark] || ["open", t.mark];
    const accept = t.accept
      ? `<details class="accept"><summary>accept</summary>` +
        `<div class="accepttxt">${esc(t.accept)}</div></details>`
      : "";
    out.push(`<div class="task t-${info[0]}"><div class="task-line">` +
             `<span class="mark">${esc(info[1])}</span>` +
             `<span class="txt">${esc(t.title)}</span></div>${accept}</div>`);
  }
  $("ledger").innerHTML = out.length ? out.join("")
    : `<div class="empty">${esc(plan.note)}</div>`;
  $("progress").textContent = plan.progress_label || "";
}

// T31: the delegation roster - every agent type keel has run, its run
// count, and whether one of its hand-offs is open right now. The count, the
// working/resting reading and its label are all the server's
// (`compute_roster`); this puts them in the DOM and nothing else. T104 adds
// a RESTING chip's last-seen figure: the server names WHICH moment it is
// (`r.last_seen_kind`, "launched" or "finished" - see `compute_roster`'s own
// docstring for why those two are never interchangeable) and the raw
// timestamp; only the elapsed-against-now figure is computed here, at
// render, the same division every other elapsed figure on this page already
// keeps. A WORKING chip states none - there is no honest "last" to give
// while one of its hand-offs is still open - and is marked out visually by
// the same `.working` class the pill elsewhere on this page already uses,
// not by wording alone.
// T118: the elapsed figure inside a RESTING chip's last-seen text is wrapped
// in its own `[data-role="last-seen"]` span, carrying the raw `data-ts` the
// tick below re-reads, so a quiet project's "last finished Ns ago" advances
// every second instead of standing still between content-digest rebuilds.
// The verb (`last_seen_kind`) stays OUTSIDE that span as plain text written
// once, here, from the server's own field - the tick never rewrites it, so
// T104's label-source agreement cannot drift client-side.
// T106: `r.node_key` is the server's own resolution of "the most recent
// delegation of this type" (`latest_node_of_agent_type`) - never re-derived
// here by scanning the canvas's own nodes a second time. `null` when that
// type has no card currently drawn (the roster spans every session the log
// ever saw; the canvas draws only one), in which case the chip carries no
// key at all and a click on it opens nothing.
function roster(entries, now){
  const items = entries || [];
  $("roster").innerHTML = items.length
    ? items.map(r => {
        const seen = !r.working && r.last_seen_ts && r.last_seen_kind
          ? ` · last ${esc(r.last_seen_kind)} ` +
            `<span data-role="last-seen" data-ts="${esc(r.last_seen_ts)}">` +
            `${esc(fmtDur(elapsedSince(r.last_seen_ts, now)))}</span> ago`
          : "";
        const key = r.node_key ? ` data-node-key="${esc(r.node_key)}"` : "";
        // T106 (review note): a chip with no `node_key` is otherwise told
        // apart only by cursor - a `title` says why in words.
        const title = r.node_key ? "" : ' title="no delegation drawn for this session"';
        return `<span class="a${r.working ? " working" : ""}"${key}${title}>` +
          `<span class="dot"></span><b>${esc(r.agent_type)}</b>` +
          `${esc(r.label)}${seen}</span>`;
      }).join("")
    : '<span class="empty">no delegations recorded yet</span>';
}

function filters(counts){
  $("filters").innerHTML = FILTERABLE.map(k => {
    const off = hiddenKinds.has(k);
    return `<button type="button" class="chip${off ? " off" : ""}" data-kind="${esc(k)}">` +
           `${esc(k)}<span>${esc(counts[k] ?? 0)}</span></button>`;
  }).join("");
}

// One flat-feed row - reused for both the top-level feed and the events
// nested inside a collapsed hand-off group (d), so there is exactly one
// place that knows how to render an event. ``e.inferred`` is set only on a
// grouped member the server could not attribute from the record; a flat-feed
// row never carries it. Every interpolation goes through ``esc`` because
// this string is assigned to innerHTML.
// `e.detail_text` is the server's own one-line summary of the fields this
// row carries, built from the already-redacted record (T31) - the page does
// not decide which fields a row shows. T120: `e.feed_sentence` is that same
// server's SENTENCE for this row (`feed_sentence`, from the identical
// already-redacted fields `detail_text` reads) - "" where no kind names one,
// which is when this falls back to the raw name it always showed. The raw
// event NAME is never lost even where a sentence replaces it as the visible
// text - it moved into this row's own `title` attribute, beside the
// wall-clock time it used to show in its own span, one hover away.
// T120 addendum: the icon is `FEED_GLYPH[e.feed_verb]` - the server's own
// verb family, never re-derived from `e.event` here. The relative-time span
// is the SAME `data-role`/`data-ts` shape `tickRoster` already ticks by
// (T118) - `now` is the render-time reading, and `tickFeed` (below) advances
// `textContent` alone on every later tick, so a quiet feed's "5m ago" cannot
// freeze the way a resting roster chip's once did.
function evRow(e, now){
  const cls = (KIND[e.event] || "") + (e.inferred ? " inf" : "");
  const tag = e.inferred
    ? `<span class="inf-tag" title="which hand-off ran this is not in the record">inferred</span>`
    : "";
  const body = e.feed_sentence
    ? esc(e.feed_sentence) : `<b>${esc(e.event)}</b> ${esc(e.detail_text)}`;
  const glyph = FEED_GLYPH[e.feed_verb] || "";
  const icon = glyph ? `<span class="ic" aria-hidden="true">${esc(glyph)}</span>` : "";
  const ago = `<span class="meta" data-role="feed-ago" data-ts="${esc(e.ts)}">` +
    `${esc(fmtDur(elapsedSince(e.ts, now)))} ago</span>`;
  return `<div class="ev ${cls}" title="${esc(e.event)} · ${esc(clock(e.ts))}">` +
         `${icon}<span class="d">${body}</span>${tag}${ago}</div>`;
}

// T3: the one stable identity an open item's own row carries between two
// renders of the pane. Nothing in the payload names one - `row_kind` plus
// `session` plus its own start `ts` is unique in practice (two items with
// all three the same would already be one item) - and the ticker (below)
// reads this same key back off the DOM to find the node it may update
// without rebuilding it.
function openRowKey(o){
  return (o.row_kind || "") + "|" + (o.session || "") + "|" + (o.ts || "");
}

// One still-open item (b): OPEN, never "stalled" or "hung" - a log reader
// cannot know that a start with no matching end is anything more than that.
// `row_kind`/`agent_type` are the ONE discriminator and ONE agent-type name
// this payload now uses on every row kind (T31, was `open_of`/`subagent_type`
// here); `prompt_head` is the already-redacted opening prompt the log
// carries and the page used to drop (T31); the trailing `.quiet` label is
// T30's own signal, shown only once the applicable threshold is crossed.
// `data-key` and the two `data-role` markers (T3) are what let the ticker
// update THIS row's elapsed time and quiet label in place later, without
// ever reassigning the feed pane's markup - see `tickOpenRows`.
// T5: the quiet note is LAST in the row, after the elapsed figure, because
// it is a full sentence and takes a line of its own (see `.quiet` in the
// style block). Nothing about the note's own wording changed to make it fit:
// the row's layout gave way instead, which is the right way round.
// T109: a hand-off row can already read FINISHED here - a `subagent_stop`
// matched it before its own `handoff_end` ever landed (T103's own
// `delegation_state`, carried onto this row unchanged) - and this plain-text
// row used to say OPEN regardless, the same disagreement the header's
// `working` figure carried (see `read_state`'s own `"working"` count). The
// word and the elapsed figure both flip together: FINISHED gets the fixed
// span from its own start to the real finish `o.finished_ts` names, never a
// count still climbing against `now`, because a live-ticking number beside
// the word FINISHED would be exactly the dishonesty this project's pills
// already refuse.
function openRow(o, now){
  const finished = o.delegation_state === "finished";
  const finishEpoch = finished && o.finished_ts ? Date.parse(o.finished_ts) / 1000 : null;
  const secs = elapsedSince(o.ts, finishEpoch == null ? now : finishEpoch);
  const label = o.row_kind === "open_handoff"
    ? "hand-off to " + esc(o.agent_type || "subagent") +
      (o.description ? ": " + esc(o.description) : "")
    : "session " + esc(o.session || "");
  const promptBit = o.prompt_head ? ` <span class="d2">"${esc(o.prompt_head)}"</span>` : "";
  const quiet = quietLabel(o, now);
  const quietHidden = quiet ? "" : ' style="display:none"';
  const quietBit = `<span class="quiet" data-role="quiet" title="inferred from a gap in ` +
    `the log, not measured"${quietHidden}>${esc(quiet)}</span>`;
  return `<div class="ev openrow" data-key="${esc(openRowKey(o))}">` +
         `<span class="t">${esc(clock(o.ts))}</span>` +
         `<span class="d"><b>${finished ? "FINISHED" : "OPEN"}</b> ${label}${promptBit}</span>` +
         `<span class="meta" data-role="elapsed">` +
         `${finished ? "finished " : "open "}${esc(fmtDur(secs))}</span>` +
         `${quietBit}</div>`;
}

// T4: one hand-off as a card on the delegation canvas. Everything it SAYS is
// the server's own (`compute_graph`): the agent TYPE the record holds - never
// a model, which the log does not record - the task it was handed, the state,
// what a closed one's activity count means, and, where the record cannot tell
// this hand-off from a sibling of the same type, the sentence saying exactly
// that. The two things computed here are the two a server cannot compute:
// elapsed time against the reader's own wall clock and the elapsed part of
// the quiet-time label. A TICKING card (T103: the pre-existing OPEN case, and
// now BACKGROUND too) carries `openRowKey`'s own `data-key` marker, so the
// ONE in-place writer (`updateOpenRowLive`) can advance it without rebuilding
// the canvas - see `tickOpenRows`.
// T103: FINISHED gets its own pill class (`st-finished`) rather than a
// dimmed copy of the running one, matching the reference's green check
// against its muted dot; BACKGROUND adds the one sentence the honesty rule
// in [[a-recorded-end-is-not-a-finish]] requires, under the pill rather than
// left for the elapsed figure alone to imply; the small last-action line is
// the server's own `last_action` (the collapsed group's own attribution),
// shown only when the record actually carries one.
// T106: `key` (`openRowKey`) is now on EVERY card, ticking or not - it is
// how a click resolves WHICH delegation to open the drawer on
// (`$("canvas").addEventListener("click"`, below), not only how the ticker
// finds a live one. A closed card's key simply matches nothing in the
// ticker's own map (`tickOpenRows`), so this adds no card to what that walk
// touches. `role`/`tabindex` make the card a control by keyboard too, the
// same way T105 already made the session node one.
// T110 RESKINS THIS CARD AND MOVES NOTHING IT SAYS. Added: the AGENT tag on
// the top border, the avatar disc, a title over the grey subtitle the agent
// TYPE already was, and a dot inside the state pill. Every string is the
// same server string it was, in the same order, escaped the same way.
// `live` - `n.open`, the SAME reading the header's WORKING NOW figure counts
// (`read_state`'s own `"working"`) - is the one marker the whole of this
// page's motion hangs off: it puts `.live` on the card (which pulses the
// pill's dot), on the pill, and, read straight back off the DOM by
// `drawWires`, on the wire that drifts. A card that is not open carries the
// marker nowhere, so nothing on or around it can move.
function nodeCard(n, now){
  const live = n.open ? " live" : "";
  const key = ` data-key="${esc(openRowKey(n))}"`;
  const quiet = n.open ? quietLabel(n, now) : "";
  const quietBit = n.open
    ? `<span class="quiet" data-role="quiet" title="inferred from a gap in ` +
      `the log, not measured"${quiet ? "" : ' style="display:none"'}>${esc(quiet)}</span>`
    : "";
  const finishedClass = n.delegation_state === "finished" ? " st-finished" : "";
  const openPrefix = n.delegation_state === "open" ? "open " : "";
  const age = n.ticking
    ? `<span class="t" data-role="elapsed">${openPrefix}${esc(fmtDur(elapsedSince(n.ts, now)))}</span>`
    : `<span class="t">${esc(n.duration_label)}</span>`;
  const count = n.count_label ? `<span>${esc(n.count_label)}</span>` : "";
  const why = n.type_note ? `<div class="why2">${esc(n.type_note)}</div>` : "";
  const stateNote = n.state_note ? `<div class="statenote">${esc(n.state_note)}</div>` : "";
  const lastAct = n.last_action ? `<div class="lastact">✎ ${esc(n.last_action)}</div>` : "";
  return `<div class="node${live}" role="button" tabindex="0"${key}>` +
         `<span class="atag">AGENT</span>` +
         `<div class="hd">${AVATAR}<span class="ident">` +
         `<span class="cname">Agent</span>` +
         `<span class="role">${esc(n.agent_label)}</span></span></div>` +
         `<div class="job">${esc(n.task_label)}</div>` +
         `<div class="pillrow"><span class="pill${live}${finishedClass}">` +
         `<span class="pdot"></span>${esc(n.state_label)}</span></div>` +
         `<div class="foot"><span class="t">${esc(clock(n.ts))}</span>${age}${count}</div>` +
         `${quietBit}${why}${stateNote}${lastAct}</div>`;
}

// T4: the session at the root of the canvas - the identifier the record
// carries, and the server's own count of what hangs off it. T6 gives it a
// visibly different treatment from a worker card, as both references do: its
// own accent border and ring, a wider body, and a pill naming what it is.
// T105: the card is the drawer's own control, so it says so to a pointer
// (`cursor`, in the style block), to a screen reader (`role`) and to the
// keyboard (`tabindex`) rather than only to a reader who happens to click
// it. The word in its pill is the server's `role` - the SAME string the
// drawer's header names it by, so the node and its drawer cannot call it two
// different things.
// T110: the centre node gets the reference's own treatment - the avatar
// disc, its role tag riding the top border, the chip naming what this
// session last did and, under it, the file it last wrote. Both of those come
// from `root.own_activity`, the SAME already-redacted rows T105's drawer
// lists, newest first as the server built them: there is no second reading
// of the log here and no field on the payload that this task invented.
// Neither line truncates in JS - the style block clips them with an ellipsis
// - so opening the drawer still shows every character the server sent.
// THE HALO AND ITS ONE GATE. `live` is the server's own liveness state
// (T108), handed down by `drawCanvas`; the page derives no threshold of its
// own. Live alone is a STILL glow. `acting` - live AND at least one
// delegation open, which is `root.open`, the very figure the line under the
// name prints in words - is what makes it breathe, and it is the only route
// by which the centre of this canvas can move at all.
function rootCard(root, live){
  const acting = live && root.open > 0;
  const mark = live ? (acting ? " live acting" : " live") : "";
  const rows = root.own_activity || [];
  const latest = rows[0];
  const wrote = rows.find(a => a.action_kind === "write");
  const chip = latest
    ? `<div class="rchip" title="${esc(latest.action_kind)}">${esc(latest.text)}</div>`
    : "";
  const path = wrote
    ? `<div class="rpath">${ACTION_GLYPH.write} ${esc(wrote.text)}</div>` : "";
  return `<div class="rootnode${mark}" role="button" tabindex="0" ` +
         `title="open what this session did outside any delegation">` +
         `<span class="rpill">${esc(root.role)}</span>${AVATAR}` +
         `<div class="who">${esc(root.session)}</div>` +
         `<div class="sub">${esc(root.label)}</div>${chip}${path}</div>`;
}

// T105: one line of the session's own work, the reference's frame-2 row: a
// wall-clock time, the glyph naming the KIND, and the content - clamped to
// two lines by the style block, never truncated here, so nothing the server
// sent is thrown away before a reader can widen the pane and read it.
// `a.text` and `a.action_kind` are both the server's (`own_activity_row`).
function ownRow(a){
  const glyph = ACTION_GLYPH[a.action_kind] || ACTION_GLYPH.action;
  return `<div class="arow"><span class="t">${esc(clock(a.ts))}</span>` +
         `<span class="ic" title="${esc(a.action_kind)}">${esc(glyph)}</span>` +
         `<span class="d">${esc(a.text)}</span></div>`;
}

// T105: the drawer itself - header, summary, state, rows, in the reference's
// order. Every string in it is the server's: the node's name and role, the
// summary counts (`root_summary_label`), the state line, which is the root
// node's OWN label re-shown rather than re-worded, and the note saying what
// the tail bound left out or that there is nothing to show
// (`own_activity_note`). The rows are newest first because the server built
// them that way.
function nodePanel(root){
  const rows = (root.own_activity || []).map(ownRow).join("");
  const note = root.own_note
    ? `<div class="npnote">${esc(root.own_note)}</div>` : "";
  return `<div class="nphead"><span class="who">${esc(root.session)} ` +
         `<span>— ${esc(root.role)}</span></span>` +
         `<button type="button" class="npx" data-role="closepanel" ` +
         `title="close this panel">×</button></div>` +
         `<div class="npsum">${esc(root.summary)}</div>` +
         `<div class="npstate">state: ${esc(root.label)}</div>` +
         `${note}<div class="nplist">${rows}</div>`;
}

// T106: a WORKER card's own drawer - the SAME `#nodepanel` aside T105's
// centre panel already uses, fed one delegation's own node (`compute_graph`)
// instead of the root. The header states exactly what the card itself
// states - agent type, task, elapsed and whether it is still open - because
// both are built from the SAME fields, never a second reading of one. Its
// rows are `n.events`, the closed group's own attributed lines - the very
// list `graph_count_label` already counted and the feed's collapsed card
// already renders (`groupRow`) - drawn through the SAME `evRow` that draws
// them there, so an inferred line carries the same marker and the same word
// in both places (never a re-attribution: an open hand-off's `n.events` is
// always empty, because no group has closed around it yet to attribute one).
// A delegation with none says so with the server's own sentence
// (`n.activity_note`, `NO_ACTIVITY_ATTRIBUTED_NOTE`'s own words) rather than
// an empty list that would read as "it did nothing".
// T106 (review fix): the elapsed figure ticks exactly when the CARD's own
// does - `n.ticking` is true only for a plain OPEN hand-off or a BACKGROUND
// pair, never AWAITED or FINISHED (see `compute_graph`; `updateOpenRowLive`
// and `nodeCard` gate the identical way). A ticking figure is wrapped in the
// SAME two-element shape those two already use - an outer `data-key`
// (`openRowKey(n)`) around an inner `data-role="elapsed"` - so `tickOpenRows`
// (extended below to also walk `#nodepanel`) finds it through the very same
// map it already built for the card and the open row, and advances it by
// `textContent` alone through `updateOpenRowLive`: no new writer, and no
// markup rebuild that would reset the panel's own scroll position. A
// non-ticking figure (AWAITED/FINISHED) is `n.duration_label`, a fixed span,
// carrying no `data-key` at all - there is nothing for the ticker to find,
// which is the point: it must never move.
function delegationPanel(n, now){
  const prefix = n.delegation_state === "open" ? "open " : "";
  const elapsed = n.ticking
    ? `<span data-key="${esc(openRowKey(n))}"><span data-role="elapsed">` +
      `${esc(prefix + fmtDur(elapsedSince(n.ts, now)))}</span></span>`
    : esc(n.duration_label || "?");
  const openWord = n.open ? "open" : "closed";
  const rows = (n.events || []).map(e => evRow(e, now)).join("") ||
    `<div class="empty">${esc(n.activity_note)}</div>`;
  return `<div class="nphead"><span class="who">${esc(n.agent_label)} ` +
         `<span>— ${esc(n.task_label)}</span></span>` +
         `<button type="button" class="npx" data-role="closepanel" ` +
         `title="close this panel">×</button></div>` +
         `<div class="npsum">elapsed ${elapsed} · ${esc(openWord)}</div>` +
         `<div class="npstate">state: ${esc(n.state_label)}</div>` +
         `<div class="nplist">${rows}</div>`;
}

// T105: the drawer's one writer. It touches its own node and nothing else -
// no pane's markup, no freshness line, no card - so opening or closing it
// cannot cost the reader an expanded delegation, a scroll position, the
// disconnect notice or a ticking elapsed figure. With no root node to
// describe (an empty log) there is nothing to open, and the drawer stays
// shut rather than showing a frame around nothing.
// T106: `panelNodeKey` chooses WHICH of the two the drawer builds - a worker
// card's own node, matched by its `openRowKey` off the very list the canvas
// just drew (`s.graph.nodes`), or, when it names none, T105's own root. A
// key that no longer matches any drawn node (the card aged out of
// `GRAPH_NODE_TAIL`, say) shows nothing rather than a stale panel, exactly
// as a missing root already does.
function renderNodePanel(s){
  const el = $("nodepanel");
  const graph = s && s.graph ? s.graph : null;
  let html = "";
  if (panelOpen && graph) {
    if (panelNodeKey) {
      const node = (graph.nodes || []).find(n => openRowKey(n) === panelNodeKey);
      if (node) html = delegationPanel(node, s.now);
    } else if (graph.root) {
      html = nodePanel(graph.root);
    }
  }
  el.innerHTML = html;
  el.hidden = !html;
}

// T4: the canvas itself. WHICH session is drawn, which hand-offs hang off it
// and every word on them is `compute_graph`'s, built from the very rows the
// open list and the feed below are built from - so this pane cannot name a
// hand-off those do not. With nothing to draw the pane is left empty and the
// heading carries the server's sentence, rather than this page inventing a
// second wording for an empty log.
// T6: the session sits at the CENTRE of the canvas with its cards arranged
// around it - half the cards above, the rest below - rather than in a band
// beneath it. Which half a card falls in is presentation and nothing else:
// the legend beside the canvas says so, and every card still prints its own
// start time, which is the only ordering the record carries.
// T110: `live` is the server's own session-liveness state, passed straight
// through to the centre node - this function makes no judgement about it and
// no other pane is given a second one (see `renderAll`, the page's sole
// reader of that field).
function drawCanvas(graph, now, live){
  const g = graph || {};
  $("graphnote").textContent = g.note || "";
  const cards = g.nodes || [];
  const above = cards.length > 1 ? cards.slice(0, Math.ceil(cards.length / 2)) : [];
  const below = cards.slice(above.length);
  const ring = items => items.length
    ? '<div class="ring">' + items.map(n => nodeCard(n, now)).join("") + '</div>'
    : "";
  $("canvas").innerHTML = g.root
    ? '<svg id="wires"></svg>' + ring(above) + rootCard(g.root, live) + ring(below)
    : "";
  drawWires();
}

// T4: the edges. WHERE a card landed is the one thing the server cannot know
// - the cards wrap to the reader's own window - so each wire is measured off
// the DOM once the cards are in it, and measured again on a resize or when a
// panel is collapsed. Every path starts at the session node and ends at one
// card: there is no code here that could join two cards, whatever order they
// happen to sit in. Nothing interpolated below comes from the payload; these
// are numbers this function measured itself.
// T6: the wires are thin CURVED beziers in the references' muted grey, dashed
// for a closed hand-off and solid for an open one, each ending in the small
// circular port the workflow reference draws. Drawn as inline SVG, because
// the content policy forbids an image and there is no network to load one.
function drawWires(){
  const host = $("canvas"), svg = $("wires");
  const root = host.querySelector(".rootnode");
  if (!svg || !root) return;
  const box = host.getBoundingClientRect(), rb = root.getBoundingClientRect();
  const at = v => Math.round(v * 10) / 10;
  const x0 = at(rb.left - box.left + rb.width / 2);
  const top = at(rb.top - box.top), bottom = at(rb.bottom - box.top);
  const parts = [];
  host.querySelectorAll(".node").forEach(el => {
    const b = el.getBoundingClientRect();
    const up = b.top - box.top < top;
    const y0 = up ? top : bottom;
    const x1 = at(b.left - box.left + b.width / 2);
    const y1 = up ? at(b.bottom - box.top) : at(b.top - box.top);
    const mid = at((y0 + y1) / 2);
    const live = el.classList.contains("live") ? " live" : "";
    const d = `M ${x0} ${y0} C ${x0} ${mid}, ${x1} ${mid}, ${x1} ${y1}`;
    parts.push(`<path class="wire${live}" d="${d}"></path>`);
    // T110: the drifting overlay, emitted for a LIVE card and for no other.
    // The condition is the card's own `.live` class, read off the DOM above
    // rather than re-derived here, so a wire cannot move beside a card that
    // is not open - and with nothing open the canvas holds no `.flow` path
    // at all, which is what makes the whole page still.
    if (live) parts.push(`<path class="wire flow" d="${d}"></path>`);
    parts.push(`<circle class="port${live}" cx="${x1}" cy="${y1}" r="3.4"></circle>`);
  });
  parts.push(`<circle class="port hub" cx="${x0}" cy="${top}" r="4.2"></circle>`);
  parts.push(`<circle class="port hub" cx="${x0}" cy="${bottom}" r="4.2"></circle>`);
  svg.setAttribute("viewBox", `0 0 ${at(box.width)} ${at(box.height)}`);
  svg.innerHTML = parts.join("");
}

// One collapsed delegation (d): a closed hand-off's own boundary lines are
// never shown - this block IS their feed row - and its contained ``events``
// are the ``activity`` lines the server attributed to it by ``agent_type``.
// Where it could not attribute one - concurrent hand-offs of the SAME type,
// which the record cannot tell apart - the group carries a non-zero
// ``inferred`` and is drawn as an inference, in words, not only in colour.
// `g.agent_type` was `g.subagent_type` before T31 settled on one name for
// every row kind; `g.prompt_head` is the delegation's own already-redacted
// opening prompt, rendered here rather than dropped (T31).
function groupRow(g, now){
  const elapsed = (g.start_ts && g.end_ts)
    ? fmtDur(Math.max(0, (Date.parse(g.end_ts) - Date.parse(g.start_ts)) / 1000))
    : "?";
  const agent = esc(g.agent_type || "subagent");
  const desc = g.description ? " — " + esc(g.description) : "";
  const promptBit = g.prompt_head ? ` <span class="d2">"${esc(g.prompt_head)}"</span>` : "";
  const n = Number(g.inferred) || 0;
  const why = n
    ? `<div class="why">${esc(n)} of these line(s) ran while more than one ` +
      `${agent} hand-off was open. The log records the agent type, not which ` +
      `hand-off, so they are shown under the most recent one that was open — ` +
      `a presentation choice, not something the record says.</div>`
    : "";
  const inner = g.events.map(e => evRow(e, now)).join("") ||
    '<div class="empty">no activity attributed to this hand-off</div>';
  return `<details class="grp${n ? " inf" : ""}"><summary><span class="t">` +
         `${esc(clock(g.end_ts || g.start_ts))}</span>` +
         `<b>${agent}</b>${desc}${promptBit}` +
         `<span class="meta">${esc(g.count)} event(s)` +
         `${n ? " · " + esc(n) + " inferred" : ""} · ${esc(elapsed)}</span>` +
         `</summary><div class="body">${why}${inner}</div></details>`;
}

function feed(rows, open, now){
  const out = (open || []).map(o => openRow(o, now));
  for (const row of rows.slice().reverse()) {
    if (row.row_kind === "group") { out.push(groupRow(row, now)); continue; }
    if (hiddenKinds.has(row.event)) continue;
    out.push(evRow(row, now));
  }
  $("feed").innerHTML = out.length ? out.join("")
    : '<div class="empty">Nothing recorded yet.</div>';
}

function renderAll(s){
  $("project").textContent = s.project;
  const a = $("arming");
  a.textContent = s.arming.tier === null ? "unarmed"
    : "tier " + s.arming.tier + (s.arming.armed ? " · ARMED" : " · observing");
  a.className = "tag" + (s.arming.armed ? " armed" : "");
  // T108: the header states plainly whether the session the CANVAS draws is
  // live or historical - the word and the sentence are BOTH the server's own
  // (`session_liveness`); this reads them and derives no opinion of its own,
  // the same discipline the roster's own last-seen figure already keeps
  // (T104: label and source agree). Historical is never a missing badge -
  // `ended` and `quiet` both render the same explicit `historical` pill,
  // distinguished only by the word the server chose for them.
  // T110: the SAME reading feeds the centre node's halo, taken here so this
  // stays the page's one and only reader of that field - the canvas is
  // handed the answer, never the field.
  const lv = $("liveness");
  lv.textContent = s.session_liveness.label;
  lv.title = s.session_liveness.note;
  const sessionLive = s.session_liveness.state === "live";
  lv.className = "tag" + (sessionLive ? " live" : " historical");
  // T119: the four tiles read `s.counts` and the ledger's own progress
  // mapping - two payload fields, no arithmetic of the page's own.
  stats(s.counts, s.plan);
  // T119: the legend bar, from the server's own list.
  agentLegend(s.legend);
  // T29: the tab carries the attention count. The STRING is the server's
  // (`document_title`) - no permission prompt, no Notifications interface,
  // no service worker: assigning a title is the whole mechanism.
  document.title = s.title;
  // What the log and the ledgers would not give up, worded by the server
  // (`loss_note`) - a corrupt audit line and a ledger that could not be
  // opened are different losses and neither is rendered around.
  $("lost").textContent = s.loss_note;
  const wh = $("withheld");
  wh.textContent = s.withheld_note;
  wh.style.color = s.counts.withheld_launches == null ? "var(--bad)" : "";
  // T107: the option TEXT is the ledger's own subject (`p.subject` - a
  // heading's own words, or the identifier itself when a ledger has no
  // readable heading to take one from, decided once by the server's own
  // `plan_subject` rather than guessed at here); the identifier stays
  // reachable for a reader who needs it, as the option's `title` attribute,
  // never dropped even where it is also the visible text.
  const sel = $("plansel");
  const names = s.plans.map(p => p.name + " " + p.subject).join("|");
  if (sel.dataset.names !== names) {
    sel.dataset.names = names;
    sel.innerHTML = s.plans.map(
      p => `<option value="${esc(p.name)}" title="${esc(p.session)}">${esc(p.subject)}</option>`
    ).join("");
  }
  if (s.plan.name) sel.value = s.plan.name;
  ledger(s.plan);
  roster(s.roster, s.now);
  // T105: the drawer is refreshed BEFORE the canvas, so the wires the canvas
  // measures are measured at the width the drawer has actually left it.
  renderNodePanel(s);
  drawCanvas(s.graph, s.now, sessionLive);
  filters(s.counts);
  feed(s.feed, s.open, s.now);
  updateFreshness(s, s.now);
}

// T3: contact with the server, in one flag - true from the instant a poll's
// own `fetch` rejects or fails to parse, until one actually succeeds again.
// It is set and cleared ONLY inside `tick`, never guessed at from anything a
// between-poll tick observes. It is declared HERE, immediately above the
// freshness writer, because that writer is what reads it: the guard belongs
// beside the code it guards, not beside the caller that happens to trip it.
let disconnected = false;

// The exact sentence a reader sees while contact is lost. One constant, so
// there is no second wording anywhere that could drift away from this one,
// and no caller holding a private copy of it.
const DISCONNECTED_NOTE = "viewer disconnected — the server was stopped";

// T3: the footer's freshness sentence, in one place - a full poll
// (`renderAll`) and the between-poll tick (`ticker`) both word it the same
// way, against different clocks (the server's own `now` right after a
// fetch; the reader's local clock in between, same reasoning as
// `elapsedSince`), so there is one sentence to keep correct rather than two
// that could drift apart.
function freshnessText(auditMtime, now){
  const age = auditMtime ? Math.max(0, Math.round(now - auditMtime)) : null;
  return age === null ? "no audit log yet" : "last audit line " + age + "s ago";
}

// T3: the SOLE writer of the footer's freshness node, and the structural
// home of the disconnect guard. Every route that could put an age there runs
// through here - a full render (`renderAll`), a poll that found nothing new
// (`tick`), the per-second `ticker`, the filter chips' own re-render from
// `lastState`, and any caller written after these - so the property holds
// for all of them at once and for callers not yet written: WHILE
// DISCONNECTED, NO CALLER RENDERS A FRESHNESS FIGURE. The guard is part of
// the same expression as the write rather than an early return above it, so
// there is no room above it for a later edit to slip in an unguarded
// assignment; and because a conditional short-circuits, `state` is not even
// read while disconnected, which is why `tick`'s failure path can call this
// with no arguments at all. The ticker's own early return (below) is then
// belt-and-braces rather than the only defence, which is what it was when a
// filter chip could still re-render a stale age straight over the notice.
function updateFreshness(state, now){
  $("freshness").textContent = disconnected ? DISCONNECTED_NOTE
    : freshnessText(state.audit_mtime, now);
}

// T30: the poll that fetches new state, dropped from 3000ms to roughly
// 1500ms so quiet-time crossings are noticed sooner.
const POLL_MS = 1500;
// T3 (was T30): a 1-second client-side ticker that advances elapsed/
// quiet-time labels BETWEEN polls, so neither ever lags its own threshold
// by more than a second. It no longer re-draws the feed pane at all - see
// `ticker`, below - only the text of nodes the last real render already
// built, using the local clock (this is a loopback server on the SAME
// machine, so there is no clock to reconcile), and never re-fetches anything.
const TICK_MS = 1000;

// T30: the redraw gate. `content_digest` is the server's fingerprint of
// everything a redraw depends on, computed with `now` - the one field every
// poll changes trivially - deliberately left out of it, so a poll that
// brings nothing new does not redraw the page. The comparison is two short
// strings here; what "nothing new" MEANS is decided (and tested) server-side.
// T3 restores what this gate is FOR: the pane it protects (`#feed`'s own
// markup) is no longer rebuilt by the ticker regardless of what this
// decided, so a poll that brings nothing new now genuinely leaves it alone.
function sameContent(a, b){
  if (!a || !b) return false;
  return a.content_digest === b.content_digest;
}

async function tick(){
  let newState;
  try {
    const r = await fetch("/api/state" + (selected ? "?plan=" + encodeURIComponent(selected) : ""));
    newState = await r.json();
  } catch (err) {
    // T3: the sticky disconnect notice. `lastState` is left exactly as it
    // was - not cleared, not replaced - and the notice is put on screen
    // through the one writer above rather than by assigning that node here,
    // so this path keeps no private copy of the sentence and no private
    // route to the node (the arguments it would pass are the stale ones, and
    // the writer ignores them while the flag stands). Setting the flag is
    // therefore the whole of the fix: from this instant NOTHING renders an
    // age - not the ticker, not a filter chip's re-render, not a caller
    // added later - until a later call to this same function whose own
    // `fetch` succeeds clears it again.
    disconnected = true;
    updateFreshness();
    return;
  }
  disconnected = false;
  const changed = !sameContent(newState, lastState);
  lastState = newState;
  if (changed) renderAll(lastState);
  // Freshness still needs a fresh figure even when nothing else changed -
  // `now` is excluded from the digest on purpose (see `sameContent`), so an
  // unchanged poll would otherwise leave a growing age unshown - and this
  // is also what clears a disconnect notice the moment contact returns,
  // whether or not the state itself is any different from before the drop.
  updateFreshness(lastState, lastState.now);
}

// T3: the one-second tick itself. It writes ONLY elapsed time and the
// quiet-time label into nodes `openRow` already built (`tickOpenRows`,
// below), and the freshness sentence - it never calls `feed`, never
// assigns `#feed`'s markup, and never rebuilds a row, so a delegation the
// reader opened by clicking stays open and the pane's scroll position is
// untouched. While disconnected it does nothing at all: neither the elapsed
// times nor the freshness line advance, so the notice `tick` wrote stands
// exactly as written until a fetch actually succeeds again. This early
// return is now a second line of defence rather than the only one - both
// things it calls refuse for themselves while disconnected - and it is kept
// because doing nothing is still cheaper than calling two functions that
// will each decide to do nothing. `Date.now()` below is the ONLY reading of
// the reader's own clock anywhere in this page: every other figure is
// computed against a `now` the server sent, which cannot move while the
// server is not answering, so no elapsed value can advance during an outage
// by any route at all.
function ticker(){
  if (disconnected || !lastState) return;
  const now = Date.now() / 1000;
  tickOpenRows(now);
  tickRoster(now);
  tickFeed(now);
  updateFreshness(lastState, now);
}

// T3: update one already-rendered open row's elapsed time and quiet label
// in place, by `textContent` on the two nodes `openRow` marked with
// `data-role`, never by touching the row's own markup.
// T103: a BACKGROUND canvas card ticks the same way an OPEN one always has -
// elapsed against THIS wall clock, never the near-instant `handoff_end` - but
// its pill already says "background", so the figure drops the "open " prefix
// a plain open row still carries. `o.delegation_state` tells the two apart:
// a plain open item's own is "open"; only a BACKGROUND graph node's is
// "background" - AWAITED never reaches here, because it never has a row in
// this pane at all (see `tickOpenRows`'s own T103 note).
// T109 CORRECTED WHAT THIS COMMENT USED TO CLAIM: an ``open_handoff`` row CAN
// already read FINISHED - a `subagent_stop` matched it before its own
// `handoff_end` ever landed - and it keeps its OWN row in `lastState.open`
// the whole time, so it DOES reach here, ticking exactly like a plain OPEN
// row until this task. It no longer ticks: `openRow` freezes it at its own
// real finish the moment it is first drawn, and this in-place writer must
// keep stating that same frozen figure, never resume advancing it against
// `now`, or the two renderers of one row would disagree within seconds.
function updateOpenRowLive(el, o, now){
  const metaEl = el.querySelector('[data-role="elapsed"]');
  if (metaEl) {
    const finished = o.delegation_state === "finished";
    const finishEpoch = finished && o.finished_ts ? Date.parse(o.finished_ts) / 1000 : now;
    const elapsed = fmtDur(elapsedSince(o.ts, finishEpoch));
    metaEl.textContent = finished ? "finished " + elapsed
      : o.delegation_state === "background" ? elapsed : "open " + elapsed;
  }
  const quietEl = el.querySelector('[data-role="quiet"]');
  if (quietEl) {
    const quiet = quietLabel(o, now);
    quietEl.textContent = quiet;
    quietEl.style.display = quiet ? "" : "none";
  }
}

// T3: find every open row currently in the pane (`openRow`'s own
// `data-key`, read back off the DOM rather than re-derived) and update it
// from the LAST STATE a real render already drew from - this reads the
// DOM, it never writes `#feed`'s markup, and an item with no matching row
// (closed, or not yet rendered) is simply skipped rather than inserted.
// It refuses while disconnected for the same structural reason the freshness
// writer does: this is the only place an elapsed or quiet figure is advanced
// against a moving clock, so the guard sits here where no caller can miss
// it, rather than only in the one caller that exists today.
// T4: an OPEN hand-off is on screen TWICE - as a row here and as a card on
// the canvas - and both are updated from the ONE open item, through the one
// writer, in this one guarded walk. Neither pane is rebuilt and neither can
// show an age the other does not.
// T103: a BACKGROUND card exists ONLY on the canvas - it is a CLOSED pair, so
// it never has a row in the open feed pane - and it is keyed by its own
// `openRowKey`, read off `lastState.graph.nodes` rather than `lastState.open`,
// so this adds no card the feed selector below could ever match and takes
// nothing away from the plain open items the first loop already covers.
// T106: a WORKER card's open panel (`delegationPanel`) is on screen at the
// SAME time as its card whenever a reader has it open - a THIRD place the
// one open item or BACKGROUND node above can appear - so it walks through
// the very same `byKey` map and the very same guarded writer, never a
// dedicated one: a panel that duplicated this walk could tick a figure the
// card's own value had already moved past.
function tickOpenRows(now){
  if (disconnected || !lastState) return;
  const byKey = new Map();
  for (const o of lastState.open || []) byKey.set(openRowKey(o), o);
  for (const n of (lastState.graph && lastState.graph.nodes) || []) {
    if (n.delegation_state === "background") byKey.set(openRowKey(n), n);
  }
  const live = el => {
    const o = byKey.get(el.dataset.key);
    if (o) updateOpenRowLive(el, o, now);
  };
  document.querySelectorAll("#feed .ev.openrow[data-key]").forEach(live);
  document.querySelectorAll("#canvas .node[data-key]").forEach(live);
  document.querySelectorAll("#nodepanel [data-key]").forEach(live);
}

// T118: a RESTING roster chip's last-seen figure ticks the same way an open
// row's elapsed figure already does (`updateOpenRowLive` above) - by
// `textContent` alone, on the ONE span `roster` marked, read back by its own
// `data-ts` rather than re-derived from `lastState`. There is nothing to key
// against a state item here (the chip's timestamp does not change between
// polls the way an open item's identity must), so this walks the DOM
// directly; it still refuses while disconnected, for the same reason every
// other live-clock writer on this page does.
function tickRoster(now){
  if (disconnected || !lastState) return;
  document.querySelectorAll('#roster [data-role="last-seen"]').forEach(el => {
    el.textContent = fmtDur(elapsedSince(el.dataset.ts, now));
  });
}

// T120 addendum: a flat feed row's relative time ticks the SAME way a
// resting roster chip's already does (T118, directly above) - `textContent`
// alone, on the span `evRow` marked with `data-role="feed-ago"`, read back
// by its own `data-ts` rather than re-derived from `lastState`. Without
// this, a quiet feed would freeze its "N ago" text at whatever a poll last
// rendered - the exact defect T118 fixed on the roster, in a new place. The
// selector reaches every row `#feed` currently holds, open groups included
// (`querySelectorAll` descends into an open `<details>`), and the feed is
// already bounded by `EVENT_TAIL` server-side, so this walk is bounded too.
function tickFeed(now){
  if (disconnected || !lastState) return;
  document.querySelectorAll('#feed [data-role="feed-ago"]').forEach(el => {
    el.textContent = fmtDur(elapsedSince(el.dataset.ts, now)) + " ago";
  });
}

$("plansel").addEventListener("change", e => { selected = e.target.value; tick(); });
// Hiding or showing a kind is a pure presentation change, so it re-renders
// from the state already in hand rather than fetching - correct even while
// disconnected, because the freshness writer refuses on its own while the
// flag stands and every other figure this redraw computes comes from the
// server's frozen `now`. There is deliberately NO connection check here: a
// guard on this caller would have covered this caller only, and the next
// one written would have had to rediscover the same defect.
$("filters").addEventListener("click", e => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  const kind = chip.dataset.kind;
  if (hiddenKinds.has(kind)) hiddenKinds.delete(kind); else hiddenKinds.add(kind);
  if (lastState) renderAll(lastState);
});
// T6: the two left panels, each collapsing and expanding on its own. The
// handler toggles ONE class on ONE panel and nothing else: no pane is
// re-rendered, no state is read and no fetch is made, so a collapsed panel
// keeps every row, chip and task it held and gives them all back on the next
// click - a panel a reader can open still carries everything it carried. The
// canvas takes the freed width by construction rather than by measurement,
// because it is the only flexible child of `main` (see `.stage` in the style
// block); the wires are then re-measured, because the cards have moved.
$("side").addEventListener("click", e => {
  const tog = e.target.closest(".tog");
  if (!tog) return;
  const panel = document.getElementById(tog.dataset.panel);
  if (!panel) return;
  const shut = panel.classList.toggle("shut");
  tog.textContent = shut ? "+" : "−";
  tog.setAttribute("aria-expanded", shut ? "false" : "true");
  drawWires();
});
// T105: opening and closing the centre node's drawer, in ONE function so
// both directions do exactly the same three things - set the flag, redraw
// the drawer, re-measure the wires because the canvas just changed width.
// It re-renders no pane, reads no clock, fetches nothing and touches no
// state, so a reader who had a delegation expanded, a panel collapsed or a
// disconnect notice on screen still has all three afterwards; and because
// the cards themselves are never rebuilt, every elapsed figure on them goes
// on advancing while the drawer stands open.
// T106: `nodeKey` (a worker card's own `openRowKey`) picks which of the two
// panels this opens; omitted, or on close, it names the root instead - the
// SAME single writer both cases go through, so a worker's panel closes and
// re-measures exactly the way the root's already did.
function setNodePanel(open, nodeKey){
  panelOpen = open;
  panelNodeKey = open ? (nodeKey || null) : null;
  renderNodePanel(lastState);
  drawWires();
}
// The centre node and a worker card are both the drawer's control, by
// pointer and by keyboard (T106 adds the worker card; T105 built the root).
// A click on neither - bare canvas ground - is left alone.
$("canvas").addEventListener("click", e => {
  if (e.target.closest(".rootnode")) { setNodePanel(true); return; }
  const card = e.target.closest(".node");
  if (card) setNodePanel(true, card.dataset.key);
});
$("canvas").addEventListener("keydown", e => {
  if (e.key !== "Enter" && e.key !== " ") return;
  if (e.target.closest(".rootnode")) { e.preventDefault(); setNodePanel(true); return; }
  const card = e.target.closest(".node");
  if (card) { e.preventDefault(); setNodePanel(true, card.dataset.key); }
});
$("nodepanel").addEventListener("click", e => {
  if (e.target.closest('[data-role="closepanel"]')) setNodePanel(false);
});
// T106: a roster chip opens the panel for the MOST RECENT delegation of its
// own agent type - the server's own resolution (`r.node_key`), read back off
// the chip exactly as a worker card's own key is read off it above. A chip
// naming no card (`node_key` was null) does nothing, the same way a click on
// bare canvas ground does.
$("roster").addEventListener("click", e => {
  const chip = e.target.closest("[data-node-key]");
  if (chip) setNodePanel(true, chip.dataset.nodeKey);
});
// T4: the cards wrap to the window, so a resize moves them and the wires
// must be measured again. Only the wires: nothing here re-renders a pane, so
// resizing costs the reader no expanded row and no scroll position, and it
// reads no clock and no state - a wire is drawn between two boxes that are
// already on screen.
window.addEventListener("resize", drawWires);
tick();
setInterval(tick, POLL_MS);
setInterval(ticker, TICK_MS);
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    """read-only local viewer on an ephemeral loopback port"""
    parser = argparse.ArgumentParser(
        prog="keel dashboard",
        description="read-only viewer over .keel/audit and .keel/plans",
    )
    parser.add_argument("--project", default=None, help="project directory to view")
    args = parser.parse_args(argv)

    root = args.project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    try:
        server = build_server(Path(root))
    except DashboardError as exc:
        print(f"keel dashboard: {exc}", file=sys.stderr)
        return 2

    hint = write_hint(Path(root), server)
    print(
        f"keel dashboard: {server_url(server)}  "
        f"(project: {redact(str(Path(root).resolve()))}; read-only, no write route; "
        f"Ctrl-C to stop)"
    )
    sys.stdout.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("keel dashboard: stopped.")
    finally:
        # ``remove_hint`` swallows its own failures; the NESTED ``finally``
        # is the structural half of the same promise - whatever came out of
        # the removal, the socket is still closed and the exit code is still
        # one of the two this module documents.
        try:
            remove_hint(hint)
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
