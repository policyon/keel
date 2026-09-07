#!/usr/bin/env python3
"""keel plan-before-write gate and policy lock.

Contract
--------
Reads   : one ``KeelEvent`` of kind ``pre_write`` or ``pre_exec`` - never a
          harness payload. From EACH GOVERNING PROJECT - the session's own and
          every project a named target belongs to, resolved by ``governance``,
          never assumed to be ``event.cwd`` - it reads:
            ``<project>/.keel/keel-policy.md``      arming file, ``tier:``,
                                                    and the optional
                                                    ``## Policy lock`` section
                                                    with its ``lock:``,
                                                    ``relax:`` and
                                                    ``workshop:`` lists
            ``<project>/.keel/plans/keel-plan-<sess8>.md``  this session's
                                                    ledger, in THAT project -
                                                    a session writing into an
                                                    armed project is held to
                                                    that project's ledger
            ``<project>/.keel/audit/keel-audit.jsonl``  read by
                                                    ``override_age_note``
                                                    only, to date the
                                                    override for the
                                                    session-start line
            ``<project>/.claude-plugin/plugin.json``  only to compare a write
                                                    against, for the one
                                                    shipped relaxation
          And this user's home directory, for exactly two LOCATIONS and no
          file: for THE GLOBAL RULE below, where keel's own cross-project
          state lives - through ``keel_faultlog.user_global_dir``, the one
          resolver every user-global keel file already uses (R15); and for
          ``is_installed_tree``, where the HARNESS keeps the trees it
          installed, so a copy of keel that arrived with an install is never
          accepted as a governing project, while a write - or a MUTATING
          COMMAND - at such a copy's own kernel is refused (THE
          INSTALLED-KERNEL RULE, the same one location). A command's
          path-like tokens are RESOLVED against that location, which is a
          path comparison, never a read of anything the copy ships.
          Neither directory is opened here;
          only its location is asked for.
          From the environment, the three user-only kill switches:
            ``KEEL_GATE=off``        the whole gate stands down
            ``KEEL_OVERRIDE=on``     policy-locked files may be changed
            ``KEEL_PLAN_TTL_MIN``    plan freshness window, default 240
          For a write INTO ``.keel/plans/keel-plan-*.md`` it also reads the
          ledger's resulting content (from the payload, or from the file on
          disk when the payload does not determine it) and hands it to
          ``scripts/keel_plans.py`` - imported, never executed as a process.
Emits   : a ``KeelVerdict``. Nothing is printed here: turning a verdict into
          harness-shaped output is the adapter's job, so the exit code and the
          JSON decision are produced by one table (R6).
Writes  : one ``gate_block`` line to
          ``<project>/.keel/audit/keel-audit.jsonl`` per blocking verdict -
          the project whose rule produced it (``audit_destination``), which is
          the session's own directory in every ordinary case and is never a
          directory that carries no arming file - one ``gate_bypass`` line per policy-lock
          refusal the user's override suspended, one ``workshop_write`` line
          per policy-locked write a declared ``workshop:`` prefix permitted
          (the LOUD half of allow-plus-loud-audit - see THE WORKSHOP RULE
          below), and nothing at all
          otherwise. Paths in those lines are relativised to the project root
          before they are written, so the log carries no absolute filesystem
          path (convention 5). A blocked COMMAND is recorded as a redacted,
          length-bounded head of itself - see ``blocked_command_detail``,
          which falls back to the opaque ``<command>`` and never to raw text
          if redaction cannot run. A ``gate_block`` or ``gate_bypass`` line is
          written only where an arming file is present, because THE GLOBAL
          RULE below can refuse in a directory that never adopted keel and
          filing that refusal would mean creating a ``.keel/`` tree there;
          those two cases say so on stderr instead, and that notice is then
          the whole record. NOTHING IS EVER WRITTEN INTO KEEL'S USER-GLOBAL
          DIRECTORY BY THIS MODULE - it guards that directory, it does not use
          it.
Argv    : none. Imported by ``keel_hook.py`` and dispatched as ``gate``.

Exit codes
----------
Via ``KeelVerdict.to_exit_code()`` only: allow -> 0, ask -> 2, deny -> 2 (R6).

Arming
------
keel enforces ONLY where ``<project>/.keel/keel-policy.md`` exists AND its
frontmatter says ``tier: 2`` or higher (R25). Tier 0 and tier 1 are
observation tiers: this gate allows everything in them. Absent the file the
gate is unarmed, which is what makes global registration safe - every project
gets the launcher, only opted-in projects get enforcement (R25).

ARMING IS RESOLVED FROM THE TARGET'S PROJECT, NEVER FROM THE SESSION'S
DIRECTORY, and the difference is a fail-open that shipped. Until T178 both
readers asked about ``event.cwd``: ``evaluate`` took ``policy_tier(event.cwd)``
and allowed on None, and ``run`` chose fail-closed versus fail-open on
``policy_present(event.cwd)``. Measured on three events differing only in
``cwd``, each naming the same protected file of the same tier-2 project by
absolute path, the project's own directory gave a block and BOTH the parent
directory and the drive root gave ``gate='unarmed'`` - the same verdict an
unadopted project gets. A session started one directory up, which is an
ordinary way to start one, wrote into an armed project with no gate at all.

So ``resolve_project`` walks UPWARD FROM EACH TARGET to the nearest directory
carrying an arming file, ``governance`` collects the answers and accounts for
every target against them, and ``run``'s failure policy is decided on the same
resolution - a crash while judging a foreign project's target must not pick its
failure direction from the directory the session happens to be standing in.
Five consequences, each stated because each is a decision and not a detail:

1. THE LEDGER MOVES WITH THE ARMING DECISION. If a target's project supplies
   the tier, that project's ``.keel/plans/`` supplies rule 2's ledger and
   rule 3's contract. A session whose cwd is elsewhere is held to THAT
   project's plan requirement, and when no ledger is there the write is
   REFUSED - naming the project and the file the session is expected to
   write, because a refusal that cannot be acted on is a dead end.
2. THE SESSION'S OWN PROJECT KEEPS EVERYTHING IT HAD. Its arming file judges
   every target of the event exactly as before, including targets outside it,
   so nothing this change touches can loosen. A target no project owns is
   the session's project's business, as it always was.
3. THE STRICTEST VERDICT WINS. ``file_paths`` is a tuple and two targets can
   land in two projects; each project judges what it owns, the strictest
   answer decides, and a blocking one names which project produced it (in
   the message and in ``detail['project']``, which is also where that
   project's audit log gets the line - a refusal is filed with the project
   whose rule made it, not in whatever directory the session started in).
4. NO WIDENING, AND THE WALK IS BOUNDED. A target genuinely outside every
   armed project still reads unarmed and still fails open. The upward walk
   stops after ``PROJECT_WALK_MAX_LEVELS`` parents and never adopts a
   filesystem root or the home directory as a project (``is_walk_ceiling``),
   so an arming file high in a tree cannot silently arm the world.
5. NEITHER BOUND MAY READ AS A PERMISSION, and the two are told apart because
   they mean different things. Reaching a CEILING is a complete answer -
   ``PROJECT_ABSENT``, keel is unarmed here. Running out of LEVELS is not -
   ``PROJECT_UNKNOWN``, and an arming file the walk never reached could refuse
   this write - but WHO gets to say so differs by kind, ratified in
   .keel/decisions/2026-08-20-the-ladder-binds-what-keel-cannot-attribute.md
   (T189, narrowing T187 on re-review). PRE_EXEC keeps T187's rule as it
   shipped: a command is atomic, every governing project already judges the
   whole command text, so this refuses when ANY governing project has reached
   the enforcing tier. PRE_WRITE is narrower, because ``governance`` partitions
   write TARGETS strictly by ownership: an unattributable target refuses only
   when an ENFORCING governing project's root is an ANCESTOR of it
   (``_enforcing_ancestor`` - a path-prefix test against roots ``governance``
   already collected, no new walk), which is exactly the shape exhaustion
   exists to catch - a path many levels inside an enforcing project that the
   walk gave up on rather than failed to find. Short of that, the SESSION's
   own governing project's tier decides, the same legitimate judgment
   ``governance``'s consequence 2 already gives it over every other target.
   Counting a foreign project's tier merely because it owns a DIFFERENT target
   in the same payload was the over-tightening T189 corrected (security
   review, 80%).
   Below whichever test applies, the tier check already allows a write into
   a path it CAN attribute to a protected file, because ``_project_verdict``'s
   tier gate precedes the lock entirely; denying a path it merely could not
   attribute while permitting that would be a single arbitrary trapdoor, not
   safety. So below the enforcing tier the event is announced and audited
   instead (``announce_unresolved_targets``, never silent - T168's rule again),
   and at the enforcing tier and above it is refused as before
   (``gate='unresolved_project'``).
   ``Governance`` then accounts for every entry of ``file_paths`` against the
   projects it found: judged, refused-or-announced, provably outside every
   armed project (announced, since it is decided by nobody), or wholly
   ungated - and it proves that partition at construction rather than trusting
   it. A target that no one judges must never read as permitted SILENTLY; that
   is the class both T178 review findings belonged to, and it is enforced by
   the type rather than by a check downstream of it.

AND ONE PROJECT THAT IS NEVER A TARGET'S PROJECT: A KEEL INSTALLATION (T506).
A tree the harness installed under its own plugin cache is a copy of a
package, not a project, and the ``.keel/`` it carries is whatever the package
shipped - for keel, an arming file at tier 2. Until this guard, a command
naming a script inside that cache was judged by KEEL'S OWN DEVELOPMENT POLICY
and refused for want of a ledger inside the plugin cache, which is how keel's
own entry point came to refuse the documented first step of adopting it
(BL57). ``is_installed_tree`` names such a tree by its LOCATION under the
harness's cache and by nothing else - never by "the plugin root", which in
this self-hosted repository IS the working tree, so excluding that would
disarm keel in the project where it is developed.
WHAT IT LOSES IS POLICY AUTHORITY, NOT PROTECTION. An installed copy arms
nothing and judges nobody; it is still the case that no session may rewrite
the hooks it is running under, so a WRITE - or a MUTATING COMMAND - aimed at an
installed tree's own kernel - its ``hooks/``, its arming file, its settings,
its manifest - is refused outside every project by THE INSTALLED-KERNEL RULE
below. The two are separate on purpose: collapsing them into one demotion is
how the first version of this guard left the running gates editable, and
guarding only the WRITE half left the same tree editable by ``sed -i`` from any
session that had not adopted keel.

The two rules, in order
-----------------------
1. POLICY LOCK - the model may not edit the rules that bind it:
   ``.keel/keel-policy.md``, anything under ``hooks/`` or ``.claude-plugin/``,
   and the settings files. Shell commands are covered by the same lock
   through the segment heuristic below, because a gate that guards ``Write``
   but not ``Set-Content`` guards nothing.
2. PLAN GATE - no state-changing tool runs until THIS session's ledger exists
   and is fresh: ``.keel/plans/keel-plan-<sess8>.md``, ``sess8`` being the
   first 8 characters of the session id. Parallel sessions never share a
   ledger. Writing a plan file is always allowed, or the gate would forbid
   the very act that satisfies it (bootstrap).
   STATE-CHANGING IS DECIDED, NOT ASSUMED. A write declares a path, so the
   payload settles whether this rule reaches it; a command declares nothing,
   so ``shell_is_read_only`` below decides it from the command text, by a
   read-only ALLOWLIST rather than a mutation denylist: every pipeline
   segment must name a command word on a list of words that neither write
   under any documented flag NOR let a configuration file choose a program
   for them to run, or one of the two words admitted only in a form PROVEN
   read-only from the command text (``sed`` with a quiet flag and a bare
   print script, ``find`` with none of its action flags), and carry no
   redirect that writes a file, no command substitution, no heredoc and no
   leading ``NAME=value`` assignment. A command that clears every segment -
   ``grep``, ``cat``, ``ls``, ``diff``, ``sed -n '1,5p'`` - needs no ledger
   to justify it, and EVERYTHING ELSE still does: an unlisted command word
   (``git`` and ``rg`` among them, for the reason the DESIGN RULE beside
   ``shell_is_read_only`` gives), a mutating verb, a redirect into a file, a
   command substitution, a line the scanner cannot parse, or an exec event
   handed to it with no command text at all.
3. PLAN CONTRACT - the bootstrap write is permitted, but not unread: a write
   whose target is a SESSION LEDGER (``.keel/plans/keel-plan-*.md``) is
   refused when the content it would leave behind violates the
   machine-checkable half of the plan contract. The four finding kinds all
   block - ``missing_identifier``, ``missing_route``, ``missing_accept``,
   ``placeholder_phrase`` - and the rules themselves are read from
   ``scripts/keel_plans.py``, which stays the single definition of the
   contract subset a machine can decide. Nothing else under ``.keel/plans/``
   is asserted against (a refit draft is not a ledger), and a ledger with no
   task lines at all is not refused here: existence and freshness are rule 2's
   question, already asked.
   SHELL COMMANDS ARE COVERED TOO, for the same reason the policy lock covers
   them: an assertion that guards ``Write`` but not ``Set-Content`` guards
   nothing. A command's resulting file content cannot be known before the
   command runs, so it is not parsed and not guessed at - a command that
   MUTATES a session-ledger path (a redirect, ``Set-Content``, ``mv``) is
   refused outright and told to use the tools whose payload the gate can
   read, while read-only references to a ledger (``cat``, ``grep``, ``git
   add``, ``sed -n '510,545p'``) stay allowed. UNVERIFIABLE IS DENY, applied
   to the write's content - and a PRINT leaves no content, which is why the
   one print-only ``sed`` shape is exempt here as well as under rule 2 (see
   that exemption's own note beside ``shell_writes_session_ledger``).

And two rules that are not a project's
--------------------------------------
THE GLOBAL RULE (T231): keel's own user-global directory - ``~/.claude/keel/``,
the ONE cross-project home the owner ratified on 2026-08-21 - may not be
written by any project, armed or unarmed, adopted or not. It holds the fleet
registry every project reads, the hook-error log and the compaction layer's
files; it belongs to keel rather than to any repository, so no arming file
grants a write to it and none is needed to refuse one. The refusal carries its
own name (``gate='user_global'``), the user's ``KEEL_OVERRIDE`` carries it
exactly as it carries the lock, and a PLAIN read is untouched - ``cat``,
``grep``, ``ls`` and the rest of rule 2's read-only allowlist, which is the
list the command half judges by, since no matcher can tell a read from a write
inside ``python3 -c "..."``. The whole rule, its scope, its two halves, that
allowlist's cost and the residual it does not close are stated at THE GLOBAL
RULE, beside the code. Nothing outside that one directory is claimed by it -
the harness's own settings beside it stay the owner's, per clause 3 of the same
ruling.

THE INSTALLED-KERNEL RULE (T506, extended to commands by T507): a WRITE, or a
MUTATING COMMAND, aimed at the kernel of a tree the harness installed under its
own plugin cache - ``<install>/hooks/``, its arming file, its settings files,
its ``.claude-plugin/`` manifest - is refused under its own name
(``gate='installed_kernel'``), by no project and for none. It is the other half
of the paragraph above: the installed copy's shipped policy governs nobody, so
nothing was left to refuse a session rewriting the gates it is running under,
and this is that refusal restored without any of the authority that caused BL57
- no arming file, tier, lock or ledger of the install is read. An installation
is replaced by installing or updating the plugin, never edited in place, so the
rule costs an adopter nothing, and ``KEEL_OVERRIDE`` carries it exactly as it
carries the lock.

THE LINE THE COMMAND HALF DRAWS IS MUTATION, NOT LOCATION, because BL57 is a
command: ``python <install>/scripts/keel.py survey`` names a path inside the
cache and must run, so naming the cache can never be the test. A command is
refused only when the segment scan this file already uses (``_shell_hits``,
in its CLOSED mode - see ``shell_hits_installed_kernel``) finds it changing
something at a token that RESOLVES to one of those kernel paths. Guarding the
write half alone left a session with no project of its own free to run ``sed
-i`` at the running gate, because ``evaluate`` answers such a session before
any evaluator is reached.

The policy-lock configuration section - DESIGN RULES
----------------------------------------------------
The ARMED project's arming file may carry an optional ``## Policy lock``
section, parsed by ``policy_lock_section``. It holds three list forms:

    ## Policy lock

    lock:
    - src/generated/

    relax:
    - release-version-bump

    workshop:
    - hooks/

``lock:`` TIGHTENS - each project-relative path joins the protected set, for
itself and for everything beneath it. ``relax:`` LOOSENS - each name is
resolved against ``RELAXATIONS``, a vocabulary that lives in this file and
nowhere else, so a project can only ever enable a relaxation keel already
shipped and reviewed. ``workshop:`` LOOSENS FURTHER, and only for a
self-hosted repository - see THE WORKSHOP RULE below.

THE WORKSHOP RULE - DESIGN RULES (fixtures pin both directions)
---------------------------------------------------------------
Ratified by the owner on 2026-08-18
(``.keel/decisions/2026-08-18-workshop-paths-ratified.md``): in a repository
that develops the guard it runs under, source lives inside the lock only
because of self-hosting, and the real guard for source is the suite, the seven
checks and the review ladder. Each ``workshop:`` prefix therefore turns the
POLICY-LOCK DENY into ALLOW-PLUS-LOUD-AUDIT for writes at or beneath it.

1. THE GOVERNANCE SURFACE IS NEVER A WORKSHOP. An entry that IS or CONTAINS
   the arming file or any settings file - ``.keel/keel-policy.md``,
   ``.claude/settings.json``, ``.claude/settings.local.json``,
   ``.keel/settings.json``, and so every entry covering ``.keel/``, ``.`` or
   the empty string - is REFUSED: ignored exactly as if it had not been
   declared, with one line on stderr naming the entry and the reason
   (``workshop_entry_refusal``, ``announce_workshop_refusals``). Because the
   list lives inside the arming file, refusing the arming file also refuses
   any entry that could rewrite the list - the model can never widen its own
   workshop. ``workshop_forbidden`` re-refuses those targets at the point of
   use, belt and braces, so a future parser bug cannot become a hole.
2. A REFUSED ENTRY IS DROPPED, NOT THE WHOLE SECTION - the opposite direction
   from ``lock:``/``relax:``, and for the reason design rule 4 gives: dropping
   one LOOSENING entry can only ever tighten, so it is the fail-closed answer
   here, whereas dropping half a tighten/loosen configuration could widen.
   An INVALID section (any ``errors``) still carries no workshop at all, by
   ``LockSection.workshop_prefixes``: a configuration keel cannot understand
   widens nothing.
3. THE WORKSHOP DEMOTES RULE 1 ONLY. A workshop write still faces the plan
   gate (rule 2) and, for a ledger, the plan contract (rule 3): the write
   falls through to them exactly as an overridden write already does. The
   workshop answers "may the model edit its own source", not "may it edit
   without a plan".
4. IT REACHES THE WRITE PATH AND NOTHING ELSE. A write payload names a path
   that ``norm`` resolves and ``_under`` compares against a prefix; a shell
   command names no target the gate can resolve with the confidence an ALLOW
   needs (``shell_hits_policy_lock`` reasons about tokens, not paths). So
   ``_evaluate_exec`` never consults ``workshop:`` and commands keep the full
   lock - the safe direction, and the only one the ratified decision's
   evidence (308 bypasses that were TOOL WRITES to ``hooks/``) supports.
5. LOUD MEANS RECORDED, AT THE SAME CHOKEPOINT. Every workshop write appends
   one ``workshop_write`` event through ``_audit_lock_event``, the same helper
   ``_audit_bypass`` uses, so redaction happens where it already happens
   (``keel_events._append_jsonl``) and a bypass and a workshop write can never
   drift into two different shapes. Counted apart from ``gate_bypass`` on
   purpose: developing the product stops being indistinguishable from evading
   its law.
6. THE OVERRIDE COMPOSES, IT DOES NOT ABSORB. While ``KEEL_OVERRIDE`` is on
   the lock is already suspended, so nothing is refused either way - but a
   workshop-listed target is still recorded as ``workshop_write`` and a target
   outside the workshop is still recorded as ``gate_bypass``. The honest
   reading of the log survives the switch being on.
7. THE DECLARATION IS SURFACED BEFORE IT IS SPENT. Whatever this list says is
   reported by ``keel survey``'s ``lock`` line and by the castoff orientation
   line, from the one ``workshop_state`` below, so a session can see what its
   own model may rewrite instead of inferring it from an audit event after the
   fact. An entry IN FORCE, an entry REFUSED and no declaration at all are
   three different sentences, and an invalid section names the loss rather
   than listing entries nothing would honour - see THE DECLARATION IS
   SURFACED, at ``workshop_state``.

1. THE SECTION IS USER-ONLY BY CONSTRUCTION. It lives inside the arming file,
   which is itself policy-locked, so writing it takes the user's own hand or
   a session the user launched with the override. No new trust boundary is
   invented here; the existing one is reused.
2. A RELAXATION ONLY EVER DEMOTES DENY TO ASK. The harness then prompts and
   the user's click - out of band from the model - is the authorization. No
   configuration can turn a locked write into an allow, so the model alone
   can never complete one.
3. THE ANCHOR IS NEVER RELAXABLE BY CONSTRUCTION. ``RELAXATIONS`` contains no
   entry whose target could be ``.keel/keel-policy.md``, anything under
   ``hooks/``, or the settings files; ``ANCHOR_FILES``/``ANCHOR_DIRS`` name
   that set and ``relaxation_for`` refuses on it a second time, belt and
   braces. A vocabulary entry aimed at the anchor is a build error, and the
   kernel suite asserts it.
4. FAIL CLOSED, VISIBLY. An unknown relaxation name, or a ``lock:`` entry
   covering the session-ledger directory (which would break the bootstrap),
   makes the whole section INVALID: the gate keeps full default lock
   behaviour and every refusal message names the offending entry. A
   configuration keel cannot understand never widens anything.
5. INDETERMINABLE IS DENY. The one shipped relaxation compares the write's
   resulting content against the file on disk; an unreadable current file, a
   result that is not JSON, or a payload shape carrying no content is a deny,
   never a demotion.

Failure policy
--------------
UNVERIFIABLE IS DENY. A write whose target path cannot be normalised at all -
an embedded NUL byte, a name the platform refuses to resolve - is refused
before either rule is applied, because a path that will not resolve cannot be
compared against the locked set, and "not comparable" must never read as "not
protected". This is the same rule the shell scanner declares below (what
cannot be resolved is blocked), applied to the write path. It reaches
state-changing events only: this gate is never asked about a read.

FAIL-CLOSED WHEN ARMED, FAIL-OPEN WHEN UNARMED. If evaluation raises - an
unreadable policy file, a ``tier:`` that is not a number, a
``KEEL_PLAN_TTL_MIN`` that is not a number, an unexpected OSError - then an
event ANY of whose governing projects carries ``.keel/keel-policy.md`` gets a
deny with the failure named, and an event no armed project governs gets an
allow and a line on stderr. "Governing" is ``governance``, the same resolution
``evaluate`` uses, so the two can never answer differently about what is armed -
and a path keel could not ATTRIBUTE counts as armed there too, since an arming
file the walk never reached could govern it. If that resolution is itself what
failed, the question falls back to ``policy_present(event.cwd)`` - the pre-T178
reading, which is wrong about foreign targets but is never worse than silence. A guard that
cannot evaluate must not pretend it approved (R3); a tool keel was never
armed in must not be broken by keel's own bug. ``tests/test_keel_kernel.py``
asserts the declared policy against the observed one in both directions.

THE GATE'S OWN STATE IS CHECKED BEFORE THE PROJECT'S IS BLAMED. Three freezes
on 2026-08-19 came from a half-applied edit to THIS file: the gate could not
evaluate, failed closed correctly - and then told the session to fix
``.keel/keel-policy.md``, a file that had parsed cleanly. A refusal that names
the wrong file is worse than a bare one, because it sends the only agent who
could help at the one thing that was not broken. So ``run`` asks two questions
before it words a refusal. ``module_preflight`` runs BEFORE ``evaluate`` is
trusted and checks that every symbol on the evaluation path is still bound and
still callable; ``gate_self_fault`` then classifies a fault that got through.
A ``GateError`` is the PROJECT's configuration, because the gate raises it
deliberately when it cannot read the arming file. A ``NameError``,
``AttributeError``, ``TypeError``, ``ImportError``, ``SyntaxError``,
``RecursionError`` or an unpacking ``ValueError`` raised inside keel's own
source is KEEL'S OWN DEFECT: it is reported as one, with the file and line
that raised it and the repair that actually applies. The arming file is named
only when ``policy_parse_fault`` shows it genuinely will not parse, and when it
parsed cleanly the message says THAT out loud instead of staying silent about
which file is meant.

AND THE RECORD SURVIVES THE FREEZE - FOR EXACTLY ONE DIRECTORY. A write whose
every target is inside ``.keel/plans/`` is ALLOWED on the fail-closed path,
loudly and on the audit record as ``crash_ledger_write``, because the ledger is
the only place a session can write the freeze down, and stop-with-accounting
then demands accounting that the same fault forbids. The bootstrap reasoning is
already in ``templates/keel-policy.md`` - the session ledger can never be
locked, or adoption could not proceed - and a crash simply bypassed it.
THIS LOOSENS A FAIL-CLOSED PATH, SO ITS LIMITS ARE PART OF IT AND ARE NOT TO BE
WIDENED BY IMPLICATION: ``.keel/plans/`` and nothing else (not ``.keel/``, not
the audit log, not source); ``pre_write`` only, never a command, because keel
cannot tell what else a shell line does; EVERY target of the write or none, so
a ledger path cannot carry a neighbour past the gate; and a target that will
not resolve at all stays refused (UNVERIFIABLE IS DENY, unchanged). Source
stays refused; the ledger does not. The allow is not a statement that rule 3's
plan contract was met - it says the contract could not be asserted, and the
message and the audit line both say so.

The plan-contract assertion inherits that split unchanged, and adds one case
of its own: if ``scripts/keel_plans.py`` cannot be imported at all, an armed
project's ledger write is DENIED with the import failure named
(UNVERIFIABLE IS DENY - a contract keel cannot read is not a contract keel
may assume was met). An unarmed project never reaches the assertion, so it
cannot be broken by it.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network: the command heuristic *parses* command text and never executes it,
and no payload value is interpolated anywhere (R5). The plan-contract checker
is reached by IMPORT for exactly that reason - ``scripts/keel_plans.py`` is
stdlib-only and pure, so calling it costs no process and breaks no constraint
(precedent: ``hooks/keel_session.py`` reads the knowledge index the same way).
Matching is casefolded throughout (convention 3, R1). Every file read names
its encoding.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_events import (  # noqa: E402
    KEEL_DIRNAME,
    RECORD_WALK_MAX_LEVELS,
    KeelEvent,
    KeelVerdict,
    allow,
    append_audit,
    ask,
    audit_path,
    deny,
)
from keel_faultlog import (  # noqa: E402  (path must be set first)
    USER_GLOBAL_RELPATH,
    user_global_dir,
)
from keel_redact import redact  # noqa: E402  (path must be set first)

#: The arming file, project-relative. Its presence arms keel; its ``tier:``
#: decides how far enforcement reaches.
POLICY_RELPATH = (KEEL_DIRNAME, "keel-policy.md")

#: Enforcement begins at tier 2 (0 observe, 1 log, 2 gate, 3 govern - the
#: ladder is documented in ``templates/keel-policy.md``).
ENFORCING_TIER = 2

#: Session ledgers live here; every write below this directory is a bootstrap
#: write and is always permitted - subject to the plan-contract assertion for
#: the ledgers themselves (rule 3 above).
PLANS_RELPATH = (KEEL_DIRNAME, "plans")

#: Where the contract checker lives, relative to this file. Resolved the way
#: ``hooks/keel_session.py`` resolves the knowledge layer, and imported for the
#: same reason: the module is stdlib-only and pure, so the gate reuses its
#: regexes instead of restating them - one definition of the contract subset.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")

#: A SESSION LEDGER's filename: ``keel-plan-<sess8>.md``. Matched against a
#: casefolded basename, because ``norm`` casefolds. THE SCOPE LINE FOR RULE 3:
#: only these files are asserted against. Any other file under ``.keel/plans/``
#: - a refit draft, a scratch note - keeps the plain bootstrap allow, because
#: the plan contract is a ledger's contract and a draft is not a ledger.
_LEDGER_NAME_RE = re.compile(r"^keel-plan-.+\.md$")

#: The finding kinds that REFUSE a ledger write. The owner's ruling for this
#: wave: all four machine-checkable kinds ``keel_plans`` emits block, none of
#: them is advisory here. Severity is deliberately not read - ``keel_plans``
#: grades findings for its own advisory CLI, and the gate's blocking set is the
#: gate's law (which is why ``strict`` is passed as False below: the flag only
#: moves a severity this code never consults).
BLOCKING_PLAN_RULES: tuple[str, ...] = (
    "missing_identifier",
    "missing_route",
    "missing_accept",
    "placeholder_phrase",
)

#: Default plan freshness window in minutes; KEEL_PLAN_TTL_MIN overrides it.
DEFAULT_PLAN_TTL_MIN = 240.0

#: What a blocked command's audit detail says when the real command cannot be
#: recorded safely. This was the detail for EVERY blocked command until
#: ``.keel/decisions/2026-08-13-gate-block-detail-middle-path.md``; it is now
#: the fallback ``blocked_command_detail`` returns whenever redaction cannot
#: run - never raw text, and never an empty string, which would read as "the
#: gate recorded nothing" rather than "the gate refused to say".
OPAQUE_COMMAND = "<command>"

#: How much of a blocked command reaches its audit line, measured on the
#: REDACTED text. The same bargain ``keel_capture.COMMAND_DETAIL_CHARS``
#: strikes for an ordinary action record, and the same number: long enough to
#: recognise the action, short enough that the log is not a transcript. Stated
#: here rather than imported from the capture module because the gate's import
#: surface is part of its safety story - a guard that pulls in a recorder to
#: learn a number has bought a failure mode for nothing.
BLOCKED_COMMAND_HEAD_CHARS = 80

#: How much of a blocked command redaction is asked to look at at all. A COST
#: bound, not a privacy bound: a hook may not become a scan of a megabyte
#: heredoc. It is safe to cut here precisely because the cut is far beyond the
#: head - a home path or a name broken in half at this offset can never appear
#: in the first ``BLOCKED_COMMAND_HEAD_CHARS`` characters of the result, which
#: is the whole reason the head bound is applied AFTER redaction and this one
#: before it.
BLOCKED_COMMAND_SCAN_CHARS = 4000

#: Exact files under the policy lock, project-relative.
PROTECTED_FILES: tuple[tuple[str, ...], ...] = (
    POLICY_RELPATH,
    (".claude", "settings.json"),
    (".claude", "settings.local.json"),
    (KEEL_DIRNAME, "settings.json"),
)

#: Directories under the policy lock, project-relative. ``hooks/`` holds the
#: gates themselves and ``.claude-plugin/`` the manifest that registers them.
PROTECTED_DIRS: tuple[tuple[str, ...], ...] = (("hooks",), (".claude-plugin",))

#: THE ANCHOR: the part of the locked set no configuration may loosen, ever.
#: The arming file states the rules, the settings files register the gates,
#: and ``hooks/`` is the gates themselves - a relaxation reaching any of them
#: would let the guarded thing rewrite its own guard. Design rule 3.
ANCHOR_FILES: tuple[tuple[str, ...], ...] = PROTECTED_FILES
ANCHOR_DIRS: tuple[tuple[str, ...], ...] = (("hooks",),)

#: The plugin manifest - protected, but NOT anchor: it carries the release
#: version, which is the one recurring friction the vocabulary below answers.
MANIFEST_RELPATH = (".claude-plugin", "plugin.json")

#: THE RELAXATION VOCABULARY, v1. Name -> (target path, what it permits).
#: Exactly one entry ships. A name a project asks for that is not in here is
#: a configuration error, never a silent no-op (design rule 4), and no entry
#: may name an anchor path (design rule 3, asserted by the kernel suite).
RELAXATIONS: Mapping[str, tuple[tuple[str, ...], str]] = {
    "release-version-bump": (
        MANIFEST_RELPATH,
        'a write to the plugin manifest that changes only the "version" value',
    ),
}

#: Heading that opens the configuration section. Case-insensitive, any depth,
#: trailing punctuation tolerated (convention 3).
_LOCK_HEADING_RE = re.compile(r"^\s*#{1,6}\s*policy\s+lock\s*:?\s*$", re.IGNORECASE)

#: Any other heading, which closes the section.
_ANY_HEADING_RE = re.compile(r"^\s*#{1,6}\s+\S")

#: ``lock:`` / ``relax:`` / ``workshop:`` - the three list forms, AT COLUMN
#: ZERO. One regex for all three so a project cannot spell one of them in a way
#: the parser reads and another in a way it silently drops. The column-zero
#: anchor is load-bearing: see A RATIFIED LIST LINE STARTS AT COLUMN ZERO below.
_LOCK_LIST_RE = re.compile(r"^(lock|relax|workshop)[ \t]*:[ \t]*$", re.IGNORECASE)

#: The list names ``parse_lock_lists`` returns, so a caller reading one that
#: was never spelled in the file gets an empty list rather than a KeyError.
_LOCK_LIST_NAMES: tuple[str, ...] = ("lock", "relax", "workshop")

#: One list entry: ``- <value>``, also at column zero. Bullet character is not
#: load-bearing; the indentation is.
_LOCK_ITEM_RE = re.compile(r"^[-*][ \t]+(.+?)[ \t]*$")

# ======================================================================
# A RATIFIED LIST LINE STARTS AT COLUMN ZERO - DESIGN RULE
#
# The arming file is a DOCUMENT, and a document teaches by example. Two
# Markdown conventions turn text into an example, and the parser has to
# refuse BOTH or it refuses neither in effect:
#
#   the FENCED block (``` ... ```), removed by ``strip_fenced_regions``;
#   the INDENTED block (four spaces), refused HERE, by anchoring the two
#   list regexes above at column zero.
#
# The first shipped fix covered only fences, and the second half of the
# same convention was still law: an "Example:" followed by an indented
# ``workshop:`` and an indented ``- everything/`` parsed as a ratified
# declaration, because both regexes opened with ``^\s*`` and absorbed the
# indent. Reviewer finding, 2026-08-19.
#
# TWO SHAPES WERE AVAILABLE, AND THIS IS WHY THIS ONE WAS CHOSEN.
# (a) Extend the stripper to indented code blocks, faithfully to
#     CommonMark. Rejected: faithfulness here is genuinely subtle - an
#     indented block needs a preceding blank line, cannot interrupt a
#     paragraph, and interacts with list-item continuation indentation, so
#     a four-space rule alone would eat the continuation lines of an
#     ordinary Markdown list and leave the paragraph case wrong. A
#     HALF-FAITHFUL IMPLEMENTATION OF A SPEC IS EXACTLY HOW THIS FINDING
#     HAPPENED, and repeating the shape that failed would be the third
#     version of one defect.
# (b) Anchor the list lines at column zero. Chosen: it is one character of
#     regex per line form, it refuses the WHOLE indentation family in one
#     stroke - indented code block, blockquoted example, nested list,
#     table cell, anything a document does to say "this is illustration" -
#     and it needs no model of Markdown at all. It also matches how the
#     law is actually written: every list line in this repository's own
#     arming file and in ``templates/keel-policy.md`` sits at column zero,
#     so nothing ratified changes meaning.
#
# THE FAILURE DIRECTION IS SAFE AND LOUD. An owner who indents a real list
# gets a section that declares nothing from those lines - the safe
# direction, since every list here either tightens (dropping it is
# tighter) or loosens (dropping it is tighter still) - and, because a
# silently absorbed intention is the defect this rule exists to prevent,
# every indented line that LOOKED like a list line is reported:
# ``_scan_lock_section`` collects it and ``announce_ignored_indented_lines``
# says so on stderr. Ignored is never silent.
#
# NOISE IS BOUNDED ON PURPOSE: an indented bullet is only reported while a
# list is open (a list head was seen, at either indentation), so ordinary
# indented prose bullets elsewhere in the section report nothing. Both
# shipped policy documents were scanned for this before the rule landed
# and neither produces a single note.
# ======================================================================

#: An indented list HEAD - the shape that must never be law, and must always
#: be reported when it appears inside the section.
_INDENTED_LIST_RE = re.compile(r"^[ \t]+(lock|relax|workshop)[ \t]*:[ \t]*$", re.IGNORECASE)

#: An indented list ENTRY. Reported only while a list is open (see the design
#: rule above), so prose bullets are not mistaken for a misindented law.
_INDENTED_ITEM_RE = re.compile(r"^[ \t]+[-*][ \t]+\S")

#: How much of an ignored line is quoted back. A bound, not a privacy measure:
#: the value comes from a policy-locked file the user wrote, and the note goes
#: to stderr rather than to the audit log.
IGNORED_LINE_CHARS = 80

# ======================================================================
# A HOLD IS READ, NOT ENFORCED - DESIGN RULE
#
# ``## Holds`` carries the user's standing constraints: "no push until I
# review", "do not touch the migration until Thursday". It shipped as a
# HEADING WITH NO READER - prose in a policy-locked file that no instrument
# in this repository parsed, surfaced or counted - which is documentation
# shaped like mechanism, and the exact shape a user trusts by mistake.
#
# WHAT THIS SECTION NOW DOES: it is parsed here, by the scanner that already
# owns ``## Policy lock`` (R15 - one parser, so the two readings of one file
# cannot drift), and it is SURFACED twice, at castoff and in the survey.
#
# WHAT IT STILL DOES NOT DO, stated in the code so nobody has to infer it:
# it decides nothing. No hold reaches ``_evaluate_write`` or
# ``_evaluate_exec``; no hold turns an allow into a deny or an ask; no hold
# is a path pattern. A hold is prose about intent, and a gate that claimed
# to enforce prose would be the same defect one field along. Making holds
# GATE requires a vocabulary that does not exist yet, and inventing one is
# a design question, not a parsing one.
#
# THE SAFE DIRECTION IS THE OPPOSITE OF THE LOCK LISTS, and that inversion
# is the whole reason this rule is written down. For ``lock:``/``relax:``/
# ``workshop:`` the safe failure is to DROP an entry keel is unsure of -
# dropping tightens. For a hold, dropping is the unsafe direction: an
# invisible constraint is one a session breaks while every check stays
# green. So an ambiguous Holds section is never read as empty. It is read as
# UNREADABLE and said out loud, and a bullet keel cannot recognise as an
# explicit "none" is read as A HOLD rather than as noise.
#
# FOUR STATES, NEVER THREE (T168: absent and none are different facts):
#   ABSENT      no ``## Holds`` heading at all - the section was never written
#   NONE        the heading, plus an explicit none-marker bullet
#   ACTIVE      the heading, plus one or more hold bullets
#   UNREADABLE  the heading, but keel cannot tell which of the above it is
# ``holds_state`` below is the ONE function that decides between them, so the
# castoff line and the survey line cannot come to disagree about a file they
# both read through the same parse.
#
# COLUMN ZERO AGAIN, for the heading as well as the bullets. The ratified
# form of this section starts at column 0 in both shipped policy documents,
# and anchoring the heading there refuses the whole indented-example family
# in one stroke - see A RATIFIED LIST LINE STARTS AT COLUMN ZERO above,
# whose two review findings are what this anchor is paying for in advance.
# ``_LOCK_HEADING_RE`` is deliberately NOT changed to match: that regex is
# ratified law with fixtures behind it, and tightening it is not this
# change's business.
# ======================================================================

#: The heading that opens the holds section, AT COLUMN ZERO. Trailing
#: punctuation tolerated, any depth, case-insensitive (convention 3).
_HOLDS_HEADING_RE = re.compile(r"^#{1,6}[ \t]*holds[ \t]*:?[ \t]*$", re.IGNORECASE)

#: The spellings that mean "this list is deliberately empty". Deliberately a
#: SHORT closed set: every bullet outside it is read as a hold, because
#: guessing that a sentence means "nothing" is how a live constraint goes
#: quiet. Compared after ``_hold_marker_text`` strips the emphasis, backticks
#: and parentheses a human writes around such a marker.
_HOLD_NONE_MARKERS: frozenset[str] = frozenset(
    ("none", "none active", "no holds", "no holds active", "no active holds")
)

#: How much of one hold is carried. A bound on a user-authored line so a
#: pathological arming file cannot spend the whole session-injection budget
#: (R16); truncation is MARKED, never silent, and the COUNT is always exact.
HOLD_CHARS = 200

#: The ASCII marker a truncated hold ends with. Plain dots on purpose - this
#: string reaches three platforms' consoles, and a typographic ellipsis that
#: cannot be encoded would turn a visible truncation into a traceback (R34,
#: the same reasoning as ``keel_session.OVERFLOW_MARKER``).
HOLD_TRUNCATED_MARKER = "..."

#: The four states of the holds section. Names, not sentences: each reader
#: renders its own wording, but no reader decides the state for itself.
HOLDS_ABSENT = "absent"
HOLDS_NONE = "none"
HOLDS_ACTIVE = "active"
HOLDS_UNREADABLE = "unreadable"

#: The whole set, for the reason ``WORKSHOP_STATES`` carries one: a state no
#: reader can REACH is as invisible as a field no reader carries, and the only
#: way to keep that true is to enumerate the states in one place and walk them.
#: Added with T176 rather than T175; the holds renderers already reached all
#: four, and this makes that a checked property instead of a lucky one.
HOLDS_STATES: tuple[str, ...] = (
    HOLDS_ABSENT,
    HOLDS_NONE,
    HOLDS_ACTIVE,
    HOLDS_UNREADABLE,
)

#: A fenced code region's delimiter, CommonMark's rule: three or more
#: backticks or tildes, indented at most three spaces, with an optional info
#: string. A closing fence must use the same character, be at least as long,
#: and carry no info string - so a ```` ``` ```` inside a ```` ```` ```` block
#: does not close it.
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*(.*?)\s*$")

#: Frontmatter ``tier:`` line. Case-insensitive by default (convention 3).
_TIER_RE = re.compile(r"^\s*tier\s*:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE)

#: Truthy / falsey spellings accepted from a kill switch.
_ON_VALUES = frozenset(("on", "1", "true", "yes"))
_OFF_VALUES = frozenset(("off", "0", "false", "no"))

#: The one reminder every surface repeats while the override is active. An
#: override is a temporary state, never a resting state, so the session says
#: so at its start and at every stop until a session runs without it. Kept
#: here, beside the lock it suspends, so the session and stop hooks cannot
#: drift into two different sentences.
OVERRIDE_REMINDER = (
    "[keel] POLICY LOCK SUSPENDED: KEEL_OVERRIDE is on for this session, so "
    ".keel/keel-policy.md, hooks/ and the settings files are writable. Restore "
    "the lock by clearing KEEL_OVERRIDE - unset it, or remove the user-level "
    "value - and starting a new session."
)

#: The three shapes of the AGE CLAUSE the session-start surface appends to the
#: reminder above. One line each, no path in any of them, and one of the three
#: is always returned: an override whose age keel cannot state must say so
#: rather than fall silent.
OVERRIDE_AGE_UNKNOWN = (
    "OVERRIDE AGE: unknown - {reason}, and keel does not guess how long a kill "
    "switch has been on."
)
OVERRIDE_AGE_NONE = (
    "OVERRIDE AGE: no earlier use of it is on the audit record, so this may be "
    "the first session it has been on for."
)
OVERRIDE_AGE_TEMPLATE = (
    "OVERRIDE AGE: {count} gate_bypass line(s) are on the audit record, the "
    "earliest {first} ({days} day(s) ago) and the latest {last} - read off the "
    "record, so a value inherited into this session is dated by what it has "
    "already done rather than by when it was exported."
)

#: Audit timestamp spelling, as ``keel_events.utc_now`` writes it.
_AUDIT_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


class GateError(RuntimeError):
    """Evaluation could not be completed. The caller applies the fail policy."""


# ---------------------------------------------------------------- environment


def env_on(name: str, env: Mapping[str, str]) -> bool:
    """True when a kill switch is explicitly turned on by the user."""
    return env.get(name, "").strip().casefold() in _ON_VALUES


def env_off(name: str, env: Mapping[str, str]) -> bool:
    """True when a kill switch is explicitly turned off by the user."""
    return env.get(name, "").strip().casefold() in _OFF_VALUES


def plan_ttl_minutes(env: Mapping[str, str]) -> float:
    """Plan freshness window. A non-numeric override is an error, not a default.

    Silently falling back would let a typo disable freshness checking, which
    is exactly the "guard fails open where its siblings fail closed" defect
    (R3): armed projects fail closed on it instead.
    """
    raw = env.get("KEEL_PLAN_TTL_MIN", "").strip()
    if not raw:
        return DEFAULT_PLAN_TTL_MIN
    try:
        return float(raw)
    except ValueError as exc:
        raise GateError(f"KEEL_PLAN_TTL_MIN is not a number: {raw!r}") from exc


# ------------------------------------------------------- the override's age


def _audit_ts(value: Any) -> datetime | None:
    """One audit line's ``ts`` as an aware UTC datetime, or None if unreadable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), _AUDIT_TS_FORMAT).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def override_age_note(cwd: Path, now: datetime | None = None) -> str:
    """One line dating the override from the RECORD, for the session surface.

    WHY THE RECORD AND NOT THE ENVIRONMENT. ``KEEL_OVERRIDE=on`` looks
    identical whether the user exported it a minute ago or a fortnight ago and
    every session since has inherited it, so the environment cannot answer "how
    long has this been on" at all. The audit log can, because a suspended lock
    leaves ``gate_bypass`` lines behind.

    WHICH DERIVATION, AND WHY THIS ONE. The intended reading was "the span
    since the earliest ``gate_bypass`` in the current unbroken stretch, a
    stretch being broken by a session that ran without the override". That
    derivation is not sound against this log: ``session_start`` lines carry no
    override field (see ``hooks/keel_session.py``'s ``start_record``), so a
    stretch could only be inferred from the ABSENCE of evidence, and a session
    that ended without a stop event - a crash, a killed process, a session that
    wrote nothing locked - would break the stretch spuriously and UNDERSTATE
    the age. Understating is the wrong direction for a line whose whole job is
    to make a stale kill switch conspicuous. So the documented fallback is what
    ships: the first ``gate_bypass`` on record, how long ago that was, the total
    count, and the latest one. Only ``gate_bypass`` is counted -
    ``override_active_at_stop`` also evidences the switch, but mixing two kinds
    into one figure would make the number unattributable to either.

    THREE ANSWERS, NEVER SILENCE AND NEVER A GUESS: the dated line above; "no
    earlier use on record" when the log holds no bypass (which is a fact about
    the record, stated as such, not a claim that the switch is new); and
    "unknown" naming the reason when the log exists and cannot be read or
    parsed. It never raises and it never returns an empty string, because the
    caller appends it to a line that must always say something, and it never
    refuses or expires the switch itself - kill switches are the user's law.
    """
    try:
        path = audit_path(Path(cwd))
        if not path.is_file():
            return OVERRIDE_AGE_NONE
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                raw_lines = handle.readlines()
        except OSError as exc:
            return OVERRIDE_AGE_UNKNOWN.format(
                reason=f"the audit log could not be read ({type(exc).__name__})"
            )
        stamps: list[datetime] = []
        count = 0
        for line in raw_lines:
            line = line.strip()
            if not line or "gate_bypass" not in line:
                continue  # cheap pre-filter; the parse below is the decision
            try:
                decoded = json.loads(line)
            except ValueError:
                continue
            if not isinstance(decoded, dict) or decoded.get("event") != "gate_bypass":
                continue
            count += 1
            moment = _audit_ts(decoded.get("ts"))
            if moment is not None:
                stamps.append(moment)
        if count == 0:
            return OVERRIDE_AGE_NONE
        if not stamps:
            return OVERRIDE_AGE_UNKNOWN.format(
                reason=(
                    f"{count} gate_bypass line(s) are on record and none carries a "
                    f"timestamp keel can read"
                )
            )
        moment_now = datetime.now(timezone.utc) if now is None else now
        first, last = min(stamps), max(stamps)
        days = max(0, (moment_now - first).days)
        return OVERRIDE_AGE_TEMPLATE.format(
            count=count,
            first=first.strftime("%Y-%m-%d"),
            days=days,
            last=last.strftime("%Y-%m-%d"),
        )
    except Exception as exc:  # noqa: BLE001 - a footnote may never fail a session
        return OVERRIDE_AGE_UNKNOWN.format(
            reason=f"keel could not date it ({type(exc).__name__})"
        )


# --------------------------------------------------------------------- arming


def policy_file(cwd: Path) -> Path:
    """Absolute path of the arming file for a project."""
    return Path(cwd).joinpath(*POLICY_RELPATH)


def policy_present(cwd: Path) -> bool:
    """Presence test only - never raises, so the fail policy can use it."""
    try:
        return policy_file(cwd).is_file()
    except OSError:
        return False


def policy_tier(cwd: Path) -> int | None:
    """Tier from the arming file's frontmatter; None when the file is absent.

    A present file whose frontmatter carries no readable ``tier:`` raises:
    keel will not guess how far an adopter asked to be enforced against.
    """
    path = policy_file(cwd)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read {path.name}: {exc}") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise GateError("keel-policy.md has no frontmatter block")
    block: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        block.append(line)
    else:
        raise GateError("keel-policy.md frontmatter block is never closed")
    match = _TIER_RE.search("\n".join(block))
    if match is None:
        raise GateError("keel-policy.md frontmatter declares no tier")
    return int(match.group(1))


def is_armed(cwd: Path) -> bool:
    """True when this project opted into enforcement (tier 2 or higher)."""
    tier = policy_tier(cwd)
    return tier is not None and tier >= ENFORCING_TIER


# ------------------------------------------------- which project governs a path

#: How many PARENTS above a path the arming walk may climb. A project root is
#: nearly always within a handful of levels of a file it owns, so this is a
#: bound on cost rather than a limit anyone should meet: it keeps resolution
#: constant-time per target instead of proportional to how deep the target sits.
#:
#: IMPORTED RATHER THAN SPELLED (T515): ``keel_events`` climbs the same
#: filesystem to answer WHICH PROJECT A RECORD BELONGS TO, and two bounds that
#: could drift apart would mean a path keel can ARM but cannot FILE, or the
#: reverse. One number, one place, two walks.
PROJECT_WALK_MAX_LEVELS = RECORD_WALK_MAX_LEVELS


#: Memo for ``_walk_home``: ``(computed, value)``. A hook process lives for one
#: tool call and a user's home directory does not move inside one, while
#: resolving it costs a real syscall per component - and the walk asks for it on
#: every level of every target. A caller that needs a DIFFERENT ceiling passes
#: ``home=`` explicitly and never touches this.
_WALK_HOME_MEMO: list[tuple[bool, Path | None]] = [(False, None)]


def _walk_home() -> Path | None:
    """This user's home directory, canonicalised, or None if it cannot be read."""
    computed, value = _WALK_HOME_MEMO[0]
    if computed:
        return value
    try:
        value = Path(os.path.realpath(str(Path.home())))
    except (OSError, ValueError, RuntimeError):
        value = None
    _WALK_HOME_MEMO[0] = (True, value)
    return value


def is_walk_ceiling(directory: Path, home: Path | None = None) -> bool:
    """True for a directory the upward arming walk may not ADOPT as a project.

    THE BOUND, and why it is here rather than nowhere: resolving arming from
    the target upward closes a fail-open, and the way a fix of that shape fails
    is by arming the world. Two kinds of directory are therefore never a
    project when the WALK arrives at them:

    1. A FILESYSTEM ROOT - the directory whose parent is itself (``C:\\``,
       ``/``, a share root). An arming file there would arm every path on the
       volume, every other project on it included.
    2. THE HOME DIRECTORY. A per-user arming file is a plausible thing to find
       - an adopter's template, a half-finished experiment, an installer's
       leftovers - and it sits above every project this user owns.

    IT REACHES ANCESTORS ONLY, which is the whole of its scope. The first
    directory of a walk is exempt: a session whose own cwd IS the home
    directory reads the arming file there exactly as it did before this
    function existed, and a target sitting directly in such a directory is
    governed by it. That is an adopter pointing keel at one directory
    deliberately, which is a different act from keel guessing upward.

    Never raises: a directory keel cannot compare is treated as a ceiling, so
    the failure direction of the BOUND is "adopt nothing".

    THE PUBLIC, DEFENSIVE FORM: it resolves both sides before comparing, so a
    caller may hand it any spelling. The walk itself uses ``_is_ceiling``, which
    skips that work because every candidate it tests is an ancestor of a path
    already resolved - and resolving each level again turned out to cost more
    than the whole rest of the gate (see the cost note in ``governance``).
    """
    try:
        candidate = Path(os.path.realpath(str(directory)))
        base = _walk_home() if home is None else Path(os.path.realpath(str(home)))
    except (OSError, ValueError, RuntimeError):
        return True
    return _is_ceiling(candidate, base)


def _is_ceiling(candidate: Path, home: Path | None) -> bool:
    """``is_walk_ceiling`` for two already-resolved paths. Never raises."""
    try:
        if candidate.parent == candidate:
            return True
        return home is not None and candidate == home
    except (OSError, ValueError):
        return True


#: THE THREE ANSWERS AN ARMING WALK CAN GIVE, as a vocabulary rather than
#: None-with-a-story. T168's rule, one field along: ABSENT and UNKNOWN are
#: different facts and a reader that cannot tell them apart will treat the
#: second as the first - which is how a fail-open survives a fix for one.
#:
#: ``found``   a project's arming file is at or above the path.
#: ``absent``  the walk reached a CEILING (a filesystem root, the home
#:             directory) without finding one. A COMPLETE answer: above a
#:             ceiling keel refuses to look, deliberately, so there is nothing
#:             more to know - see ``is_walk_ceiling``.
#: ``unknown`` the walk ran out of levels first (``PROJECT_WALK_MAX_LEVELS``).
#:             An INCOMPLETE answer: an arming file the walk never reached could
#:             govern this path, so keel cannot vouch for it. The bound is a
#:             cost decision and this state is what keeps that decision from
#:             becoming a permission - the difference between "there is no rule
#:             here" and "I stopped looking".
PROJECT_FOUND = "found"
PROJECT_ABSENT = "absent"
PROJECT_UNKNOWN = "unknown"

#: Every state above, for the enumeration the suite walks (R15: a state no
#: reader can reach through production code is a state that is not tested).
PROJECT_STATES: tuple[str, ...] = (PROJECT_FOUND, PROJECT_ABSENT, PROJECT_UNKNOWN)


@dataclass(frozen=True)
class ProjectResolution:
    """Which project owns a path, with EXHAUSTED told apart from ABSENT.

    ``root`` is set only for ``PROJECT_FOUND``; the other two states carry None
    and are not interchangeable with each other. There is deliberately no
    ``__bool__`` and no "root or None" convenience: a caller has to name the
    state it means, because the whole defect this type exists for was a caller
    reading None as "nothing governs this".
    """

    state: str
    root: Path | None = None

    @property
    def found(self) -> bool:
        """True when a project owns this path."""
        return self.state == PROJECT_FOUND

    @property
    def unknown(self) -> bool:
        """True when the walk gave up before it could answer."""
        return self.state == PROJECT_UNKNOWN


#: The two answers that carry no root, built once because they carry no data.
ABSENT_PROJECT = ProjectResolution(PROJECT_ABSENT)
UNKNOWN_PROJECT = ProjectResolution(PROJECT_UNKNOWN)


def resolve_project(
    path: str | Path,
    home: Path | None = None,
    cache: dict[str, ProjectResolution] | None = None,
) -> ProjectResolution:
    """The nearest project AT OR ABOVE ``path``, or why there is no answer.

    THIS IS WHERE ARMING COMES FROM (R25), and it is keyed on the PATH - a
    write's target, a command's named file, or a session's own directory - and
    never on where a session happens to be standing. Callers pass an absolute
    path; a relative one is resolved against the process's own directory, which
    is a convenience for a reader at a prompt and not something the gate relies
    on.

    NEAREST WINS. A project nested inside another is governed by its own arming
    file, because the walk stops at the first one it finds. THE TARGET NEED NOT
    EXIST: a write's target usually does not exist yet, so only directories are
    ever read, and only for the arming file's presence.

    BOUNDED TWO WAYS, AND THE TWO BOUNDS MEAN DIFFERENT THINGS - which is the
    whole point of the return type. ``is_walk_ceiling`` is a DECISION: above a
    filesystem root or the home directory keel will not look, so stopping there
    is a complete answer and reads ``PROJECT_ABSENT``.
    ``PROJECT_WALK_MAX_LEVELS`` is a COST LIMIT: stopping there means keel ran
    out of budget, not that it found nothing, so it reads ``PROJECT_UNKNOWN``
    and every caller must treat it as "cannot vouch" rather than "not
    protected" (the failure policy at the top of this file).

    Never raises. ``cache`` is an optional per-event memo, so an event naming
    several files in one project pays for one walk.
    """
    try:
        start = Path(os.path.realpath(str(path)))
    except (OSError, ValueError):
        # A path that will not resolve has no ancestors to walk. It is not
        # "unknown project" - it is an unverifiable PATH, which the write rule
        # refuses on its own terms; here it is simply absent of a project.
        return ABSENT_PROJECT
    return _resolve_resolved(start, home, cache)


def _resolve_resolved(
    start: Path, home: Path | None, cache: dict[str, ProjectResolution] | None
) -> ProjectResolution:
    """``resolve_project`` for a path that is ALREADY resolved. Never raises.

    Split out for one measured reason: ``os.path.realpath`` costs a syscall per
    component (0.2-0.4ms per call on the machine this was written on, which is
    more than the whole pre-T178 arming read), and ``governance`` already
    resolves every target before it asks who owns it. Resolving twice doubled
    the added cost of this task for no answer that changed.
    """
    key = str(start).casefold() if cache is not None else ""
    if cache is not None and key in cache:
        return cache[key]
    try:
        ceiling_home = _walk_home() if home is None else Path(os.path.realpath(str(home)))
    except (OSError, ValueError, RuntimeError):
        ceiling_home = None
    answer = UNKNOWN_PROJECT  # the walk ran out of levels unless it says otherwise
    candidate = start
    for step in range(PROJECT_WALK_MAX_LEVELS + 1):
        if step and _is_ceiling(candidate, ceiling_home):
            answer = ABSENT_PROJECT
            break
        if policy_present(candidate):
            answer = ProjectResolution(PROJECT_FOUND, candidate)
            break
        parent = candidate.parent
        if parent == candidate:
            answer = ABSENT_PROJECT  # the top of the tree, reached and read
            break
        candidate = parent
    if cache is not None:
        cache[key] = answer
    return answer


# ------------------------------- a keel INSTALLATION is never a project (T506)


#: THE HARNESS'S PLUGIN CACHE, as path segments under this user's home
#: directory. It is not keel's directory and keel never writes in it: it is
#: where the HARNESS puts the trees it installs, and these are the same two
#: segments the rest of this project already uses to find it -
#: ``scripts/keel_survey.py`` joins them in ``plugin_manifests`` and opens the
#: harness's own install record inside them (``INSTALL_RECORD_RELPATH``).
#: Restated here rather than imported for the reason
#: ``BLOCKED_COMMAND_HEAD_CHARS`` gives: the gate's import surface is part of
#: its safety story, and a guard that pulls in a reporting module to learn two
#: path segments has bought a failure mode for nothing. The suite pins this
#: spelling against the survey's so the two cannot drift apart.
INSTALL_CACHE_RELPATH: tuple[str, ...] = (".claude", "plugins")


def install_cache_root() -> str:
    """The harness's plugin cache for this user, RESOLVED and casefolded, or "".

    Resolved rather than merely joined, for the reason ``user_global_root``
    gives about its own directory: the roots it is compared against arrive from
    a walk that resolved them, and on Windows a home directory reached through
    an 8.3 short name is a different string for the same directory. Comparing
    an unresolved base against a resolved root would read an installation as an
    ordinary project - which is the defect this exists to close.

    NOT MEMOISED, deliberately and for the same reason ``user_global_root`` is
    not: a memo would freeze the answer for a process whose ``HOME`` changes
    under it, which is exactly what the suite does to keep its fixtures off the
    real cache. ``governance`` asks once per event, not once per target.

    "" MEANS "KEEL CANNOT NAME A PLUGIN CACHE ON THIS MACHINE", and it is a
    fact rather than a failure to paper over. It makes ``is_installed_tree``
    answer False for everything, so the failure direction is "govern as
    before": a guard that cannot locate the cache must not start excusing
    projects on a guess.
    """
    try:
        return os.path.realpath(
            str(Path.home().joinpath(*INSTALL_CACHE_RELPATH))
        ).casefold()
    except (OSError, ValueError, RuntimeError):
        return ""


def is_installed_tree(directory: Path, cache_root: str | None = None) -> bool:
    """True when a directory is an INSTALLED COPY - a tree the harness put in
    its own plugin cache - and so may never be a governing project (BL57).

    WHAT WENT WRONG WITHOUT THIS, measured by the owner on 2026-09-05 while
    laying keel into another project. keel's marketplace entry named ``"./"``
    as its source at the time, so an install copied this repository WHOLE,
    ``.keel/`` included, and the installed copy therefore carried an arming
    file at ``tier: 2``. (That source now names the tracked ``dist/keel``
    bundle instead - T614, 2026-09-06 - so an install from THIS repository's
    manifest no longer copies an arming file in. This guard is not thereby
    redundant: it holds for any installed tree, however it came to carry one,
    including one installed before that change or from a manifest elsewhere.)
    The cache directory resolved as a project like any other, so
    the FIRST DOCUMENTED STEP OF ADOPTION - running keel's own CLI out of the
    installed tree - was judged by keel's own development policy and refused
    for want of a session ledger INSIDE THE PLUGIN CACHE, which no adopter can
    write and none should. The class is wider than the packaging that caused
    it: a directory keel ships can arm a governing project, and packaging will
    not be the last way that happens.

    WHY THE PREDICATE IS THE HARNESS'S CACHE AND NOT "THE PLUGIN ROOT", which
    is the obvious spelling and would be a disaster here. keel is developed in
    the tree it ships: on the machine this was written on the plugin
    registration IS the working repository (``keel survey`` resolves the plugin
    hook manifest to ``<repo>/hooks/hooks.json``), and ``CLAUDE_PLUGIN_ROOT``
    for a session governed by that registration points at the repository
    itself. A guard keyed on the plugin root would therefore stop keel
    governing its own development repository - the gates off in the project
    that most needs them, silently, with every test still green. An
    INSTALLATION is a different fact from a plugin root: it is a tree the
    harness COPIED into a directory the harness owns, and its LOCATION is the
    only thing that says so.

    WHAT THIS DELIBERATELY DOES NOT MATCH, each named so a later reader does
    not "extend" the guard into one of them:

    * A PLUGIN ROOT IN GENERAL, and ``CLAUDE_PLUGIN_ROOT`` in particular -
      neither is read here, by this function or by its caller.
    * A CHECKOUT OF KEEL ANYWHERE ELSE ON DISK, this repository included. Only
      a path under the cache answers True, and a development tree is not one.
    * ``<home>/.claude/plugins`` ITSELF, which is why the test is STRICTLY
      beneath rather than ``_under``'s at-or-beneath. The cache directory is
      not something the harness installed; an arming file lying directly in it
      is not an installed tree, and demoting it would be this guard deciding
      about a directory nobody has shown it anything about.
    * A PROJECT'S OWN ``.claude/plugins`` DIRECTORY. The comparison is against
      ONE absolute resolved path under this user's home - not a scan for those
      two segments wherever they appear - so a project carrying that directory
      is untouched, wherever the project lives.
    * THE SESSION'S OWN PROJECT, which this is never asked about at all. See
      ``governance``.

    Compared through ``_under`` rather than a bare prefix test, the same fix
    ``_enforcing_ancestor`` and ``is_user_global_target`` already needed: a
    sibling that merely shares the spelling (``.../plugins-old``) is not inside
    the cache.

    Never raises. A directory that will not resolve answers False - keep
    governing it - because this guard's wrong answer is not an error but
    SILENCE: a project that quietly stops being judged.
    """
    base = install_cache_root() if cache_root is None else cache_root
    if not base:
        return False
    try:
        resolved = os.path.realpath(str(directory)).casefold()
    except (OSError, ValueError):
        return False
    return resolved != base and _under(resolved, base)


def _not_an_installation(answer: ProjectResolution, cache_root: str) -> ProjectResolution:
    """A TARGET's resolution, with an installed tree demoted to ABSENT.

    ABSENT AND NOT UNKNOWN, which is the whole of the care in this function.
    UNKNOWN means "keel stopped looking" and REFUSES the event (consequence 5
    at the top of this file); what happened here is the opposite - keel looked,
    found something, and will not accept it as a project. ABSENT is the answer
    a target outside every armed project already gets, and it leaves this
    target exactly where consequence 2 leaves every unowned path: with the
    SESSION's own project, which still judges it.

    A resolution with no root passes through untouched, so nothing about an
    unattributable path changes here.

    WHAT THIS DEMOTION DOES NOT DO, and the first version of it wrongly did
    (review, 2026-09-05). It removes the installed copy's POLICY AUTHORITY -
    its arming file, its tier, its lock, its ledger, all of which came from a
    file a package shipped rather than a rule anybody adopted. It does NOT
    leave the installed tree's own kernel writable: dropping the root from the
    project list also stopped ``is_protected`` ever being asked about the
    install's ``hooks/``, its arming file and its manifest, so a session in its
    own armed project with a fresh ledger could rewrite the very gates binding
    it under the generic plan allow. That half is restored SEPARATELY and
    outside every project, at THE INSTALLED-KERNEL RULE
    (``installed_kernel_root`` / ``installed_kernel_write`` /
    ``installed_kernel_command``), which reads nothing the install shipped and
    so cannot bring BL57 back with it. The command half is there for a sharper
    version of the same reason: for a ``pre_exec`` event this demotion is the
    ONLY thing that happens to the installed tree, so a session with no project
    of its own reached no evaluator at all until T507 (silent-failure review,
    85%).
    """
    if answer.found and answer.root is not None and is_installed_tree(answer.root, cache_root):
        return ABSENT_PROJECT
    return answer


# THERE IS DELIBERATELY NO "root or None" HELPER HERE. Two shims briefly stood
# in this space during T178's retry - ``project_root_for`` and
# ``_project_root_of`` - each returning ``ProjectResolution.root`` and so
# spelling ABSENT and UNKNOWN with the same word. That collapse IS the review
# finding this file's resolution vocabulary answers, and a convenience that
# reintroduces it is not a convenience. Every caller reads the state.


# ----------------------------------------------------------- path normalising


def _resolved(cwd: Path, path: str) -> str:
    """Absolute, symlink-resolved form of a payload path - NOT casefolded.

    Split out of ``norm`` because two callers need the same resolution for
    different purposes: the lock compares paths and needs the casefold (R1),
    while ``project_root_for`` walks the filesystem and must not have the case
    of a path destroyed under it on a case-sensitive system. One resolution,
    two readings; the empty string means "could not be resolved" in both.

    An embedded NUL byte is rejected explicitly, before ``os.path.realpath``
    ever sees it: on Windows, ``realpath``'s reliance on ``_getfinalpathname``
    to raise ``ValueError`` for a NUL byte is a CPython implementation detail
    that changed in 3.12 (the rewritten ``ntpath.realpath`` no longer calls
    that WinAPI path for a non-existent target, so it silently returns a
    joined-but-unresolved string containing the NUL instead of raising). The
    UNVERIFIABLE-IS-DENY contract above must not depend on that detail.
    """
    if "\0" in path:
        return ""
    try:
        return os.path.realpath(os.path.join(str(cwd), path))
    except (OSError, ValueError):
        return ""


def norm(cwd: Path, path: str) -> str:
    """Absolute, symlink-resolved, casefolded form of a payload path.

    Casefolding is deliberate and not a case-sensitivity bug: the lock must
    hold on Windows and macOS, where ``HOOKS/`` and ``hooks/`` are the same
    directory. Both-case fixtures ship for it (R1).

    THE EMPTY STRING MEANS "COULD NOT BE RESOLVED", NEVER "NOT PROTECTED".
    ``is_protected`` answers False for it because there is nothing to compare,
    so every caller that decides something must test for it FIRST -
    ``_evaluate_write`` does, and denies (see the failure policy above).
    """
    return _resolved(cwd, path).casefold()


def _under(target_norm: str, base: str) -> bool:
    """True when a normalised path IS a normalised base or sits beneath it."""
    return bool(base) and (
        target_norm == base or target_norm.startswith(base + os.sep.casefold())
    )


def is_protected(cwd: Path, target_norm: str, extra: Sequence[str] = ()) -> bool:
    """True when a normalised path is under the policy lock.

    ``extra`` carries the project's own ``lock:`` entries, already validated.
    Each is treated as a prefix, so one line locks a file or a whole tree
    without the adopter having to say which it meant.
    """
    if not target_norm:
        return False
    for parts in PROTECTED_FILES:
        if target_norm == norm(cwd, os.path.join(*parts)):
            return True
    for parts in PROTECTED_DIRS:
        if _under(target_norm, norm(cwd, os.path.join(*parts))):
            return True
    return any(_under(target_norm, norm(cwd, entry)) for entry in extra)


def is_anchor(cwd: Path, target_norm: str) -> bool:
    """True for the part of the locked set no configuration may loosen."""
    if not target_norm:
        return False
    if any(target_norm == norm(cwd, os.path.join(*parts)) for parts in ANCHOR_FILES):
        return True
    return any(_under(target_norm, norm(cwd, os.path.join(*parts))) for parts in ANCHOR_DIRS)


def is_plan_target(cwd: Path, target_norm: str) -> bool:
    """True for anything inside ``.keel/plans/`` - always writable (bootstrap)."""
    if not target_norm:
        return False
    return _under(target_norm, norm(cwd, os.path.join(*PLANS_RELPATH)))


def relativise(cwd: Path, value: str) -> str:
    """Project-relative form of a path, for audit lines and refusal messages.

    A path outside the project is expressed relative to it (``../..``) rather
    than absolutely; where even that is impossible - a different Windows
    drive - only the basename survives. This function does not itself call
    ``keel_redact``, and does not need to for the audit log's sake: every
    value this module hands to ``append_audit`` (via ``_audit``/
    ``_audit_bypass``'s ``detail`` dict, ``relativise``'s own output among
    it) passes through ``keel_redact.redact_mapping`` unconditionally at
    ``keel_events._append_jsonl``, the write-time chokepoint every audit and
    queue line goes through before it becomes bytes on disk - see that
    function's docstring. A DENIED NAME surviving this function's output is
    therefore screened before the write, and so is any absolute home-directory
    prefix still spelled out in it; nothing here needs to duplicate that work.

    THE ONE SHAPE THAT USED TO SURVIVE THE CHOKEPOINT, and how it is closed:
    this function runs BEFORE the chokepoint, and ``os.path.relpath`` can turn
    an absolute path under a user's home into ``../../Users/<name>/x`` - a
    spelling from which the literal home prefix is gone, so a pattern anchored
    on that prefix cannot recognise it and the username segment used to reach
    the log intact. The freshness deny below is the ordinary trigger: any write
    outside the project while no fresh plan is on file. It is closed in
    ``keel_redact`` rather than here, at the door every writer passes through
    rather than in one caller: ``screen_home_shapes`` is anchored on the home
    ROOT instead of on the prefix, so ``../../Users/<name>/x`` reaches the log
    as ``../../[home-path]/x`` whoever built it and however it was spelled.
    ``tests/test_keel_home_shapes.py`` drives this function's own output
    through ``run`` and asserts it on the bytes in the file.

    That is deliberately not the same fix as ``keel_redact.redact_path``, which
    tests home membership FIRST and only then relativises, and so keeps the
    more useful ``~/x``. This function stays as it is because its output also
    feeds refusal messages whose exact text is pinned by fixtures, and because
    a caller-side fix would leave every other producer of that shape open.

    A value this function returns that is instead placed in a refusal's
    ``reason`` - shown to the model, never logged - is not covered by the
    chokepoint at all, because the audit log, not the live refusal message,
    is the leak T8 closes.
    """
    if not value:
        return ""
    try:
        return os.path.relpath(os.path.join(str(cwd), value), str(cwd)).replace(os.sep, "/")
    except (OSError, ValueError):
        return os.path.basename(value)


# ------------------------------------------- the policy-lock configuration


@dataclass(frozen=True)
class HoldsScan:
    """What one pass over the arming file saw of ``## Holds``.

    The RAW reading, before ``policy_lock_section`` judges it: whether the
    heading was there at all, the bullets as the user wrote them, whether an
    explicit none-marker was among them, and the indented bullets that were
    refused as illustration. Kept separate from ``LockSection`` so the scanner
    can return one shape and the validator can own every verdict about it.
    """

    present: bool = False
    entries: tuple[str, ...] = ()
    none_declared: bool = False
    ignored: tuple[str, ...] = ()


@dataclass(frozen=True)
class LockSection:
    """The parsed ``## Policy lock`` section of an armed project's arming file,
    and - since the same scan reads the same file - its ``## Holds`` section.

    ``errors`` is the whole safety story: a section that carries any error is
    INVALID, and an invalid section tightens nothing and loosens nothing -
    the gate falls back to the shipped default set (design rule 4). The
    errors themselves are carried into every refusal message, so a
    misconfiguration is visible at the moment it costs somebody something
    rather than filed silently.

    ``hold_errors`` IS DELIBERATELY NOT PART OF ``errors``, and the reason is
    the safety story above read backwards. ``errors`` decides what the gate
    enforces: a section carrying one drops this project's ``lock:`` entries
    and falls back to the shipped default set. So folding a typo in a PROSE
    section into ``errors`` would let a mistyped hold silently UNLOCK a path
    the owner had tightened - a loosening, caused by a sentence that gates
    nothing. The two failures stay separate, and each is reported in full
    (see A HOLD IS READ, NOT ENFORCED).
    """

    present: bool = False
    lock: tuple[str, ...] = ()
    relax: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    workshop: tuple[str, ...] = ()
    workshop_refusals: tuple[str, ...] = ()
    ignored_indented: tuple[str, ...] = ()
    holds_present: bool = False
    holds: tuple[str, ...] = ()
    holds_none_declared: bool = False
    hold_errors: tuple[str, ...] = ()
    holds_ignored_indented: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        """True when the section can be honoured as written."""
        return not self.errors

    @property
    def holds_valid(self) -> bool:
        """True when the holds section says plainly which state it is in.

        Named apart from ``valid`` on purpose: a project can have a perfectly
        valid lock and an unreadable holds section, or the reverse, and a
        single flag covering both would hide one behind the other.
        """
        return not self.hold_errors

    @property
    def locked_paths(self) -> tuple[str, ...]:
        """The tighten entries actually in force."""
        return self.lock if self.valid else ()

    def relaxes(self, name: str) -> bool:
        """True when this project enabled a named relaxation, validly."""
        return self.valid and name in self.relax

    @property
    def workshop_prefixes(self) -> tuple[str, ...]:
        """The workshop entries actually in force - the loosening ones only.

        ``workshop`` already holds only the entries that survived
        ``workshop_entry_refusal`` (workshop design rule 1); this property adds
        the second condition design rule 2 states: an INVALID section carries
        no workshop at all, because a configuration keel cannot understand may
        not widen anything (design rule 4 of the section above).
        """
        return self.workshop if self.valid else ()


def policy_body(cwd: Path) -> str:
    """The arming file's body - everything after the frontmatter block.

    An absent file is an empty body rather than an error: whether the project
    is armed at all is ``policy_tier``'s question, asked first.
    """
    path = policy_file(cwd)
    if not path.is_file():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GateError(f"cannot read {path.name}: {exc}") from exc
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                return "\n".join(lines[index + 1 :])
    return text


def _lock_entry_covers_plans(cwd: Path, entry: str) -> bool:
    """True when a tighten entry would put the session ledgers under the lock.

    Either direction counts - the entry inside ``.keel/plans/`` or the ledger
    directory inside the entry - because the plan gate's bootstrap carve-out
    is evaluated AFTER the lock, so a lock covering the ledgers would forbid
    the very write that satisfies the other rule.
    """
    base = norm(cwd, entry)
    plans = norm(cwd, os.path.join(*PLANS_RELPATH))
    if not base or not plans:
        return False
    return _under(base, plans) or _under(plans, base)


def strip_fenced_regions(body: str) -> tuple[str, bool]:
    """Blank every fenced code region, so DOCUMENTATION cannot parse as LAW.

    THE DEFECT THIS CLOSES, and it was live in the shipped template: the
    arming file is a DOCUMENT, and ``templates/keel-policy.md`` teaches the
    configuration section by showing it - a fenced example under
    ``## Policy lock`` spelling ``lock:``/``relax:`` lists. The parser below is
    line-based, so it read that EXAMPLE as a declaration: an adopter who copied
    the template got ``src/generated/`` locked and ``release-version-bump``
    relaxed without ever deciding either, and a ``workshop:`` example would
    have opened allow-plus-loud-audit on a prefix nobody ratified - silently,
    with no refusal and no error, because nothing was malformed.

    THE CLASS, stated as the rule: a policy parser may not read documentation
    as law. So fences are removed BEFORE any list is read, for all three lists
    at once - they come from one parse, and a fix that covered only
    ``workshop:`` would leave the same hole under two other names.

    THIS FUNCTION IS ONLY HALF OF THAT RULE, deliberately. Markdown has a
    second way to mark an example - the four-space INDENTED code block - and
    this stripper does not implement it, because a half-faithful CommonMark
    implementation is what produced the second finding. The indented family is
    refused instead by anchoring the list regexes at column zero (see A
    RATIFIED LIST LINE STARTS AT COLUMN ZERO), which needs no model of
    Markdown at all. Between them the two halves cover both conventions.

    Lines inside a fence are BLANKED rather than deleted, so a line number in
    an error message still means what it says. The rule is CommonMark's: an
    opening fence is three or more backticks or tildes indented at most three
    spaces; the closing fence uses the same character, is at least as long, and
    carries no info string.

    Returns ``(stripped body, closed)``. ``closed`` is False when a fence is
    never closed - which ``policy_lock_section`` turns into a section ERROR
    rather than silently swallowing the rest of the file, because "everything
    after this line is an example" is a claim the file failed to finish making,
    and an unfinished claim must not decide whether a path is locked (design
    rule 4: fail closed, visibly). Idempotent: a stripped body has no fence
    left to find, so stripping twice is stripping once.
    """
    out: list[str] = []
    char = ""
    length = 0
    for line in body.splitlines():
        match = _FENCE_RE.match(line)
        if not char:
            if match:
                char, length = match.group(1)[0], len(match.group(1))
                out.append("")
                continue
            out.append(line)
            continue
        out.append("")
        if (
            match
            and match.group(1)[0] == char
            and len(match.group(1)) >= length
            and not match.group(2).strip()
        ):
            char, length = "", 0
    return "\n".join(out), not char


def _hold_marker_text(value: str) -> str:
    """One hold bullet reduced to the words in it, for the none-marker test.

    Strips the punctuation a human puts AROUND such a marker - emphasis
    (``*``/``_``), backticks, parentheses, brackets and a trailing period -
    then folds case and collapses inner whitespace, so ``*(none active)*``,
    ``(NONE)`` and ``` `none` ``` all reduce to the same words. It strips
    nothing from the MIDDLE of the value: reducing a sentence until it happens
    to look like a marker is exactly the guess this function refuses to make.
    """
    text = value.strip().strip("*_`").strip()
    text = text.strip("()[]").strip().rstrip(".").strip()
    return " ".join(text.casefold().split())


def _scan_lock_section(
    body: str,
) -> tuple[bool, dict[str, list[str]], list[str], HoldsScan]:
    """The ONE scan of the arming file's two governance sections. Pure: no
    filesystem, no env.

    Returns ``(present, lists, ignored, holds)``:

    ``lists``    the three list forms, every name always present so a caller
                 cannot fail on a list the file never spelled. Only COLUMN-ZERO
                 lines contribute - see A RATIFIED LIST LINE STARTS AT COLUMN
                 ZERO above for why that anchor is the refusal of every
                 indentation convention at once.
    ``ignored``  the indented lines that LOOKED like list lines, quoted for the
                 stderr notice. Ignored is never silent.
    ``holds``    the ``## Holds`` reading as a ``HoldsScan`` - see A HOLD IS
                 READ, NOT ENFORCED. Read HERE, in the same pass over the same
                 stripped body, rather than by a second function that could
                 come to disagree with this one about where a section ends
                 (R15). ``_ANY_HEADING_RE`` closes both sections identically,
                 so the two cannot overlap by construction.

    FENCED REGIONS ARE STRIPPED FIRST, unconditionally, so this function reads
    the same law whether its caller remembered to strip or not - see
    ``strip_fenced_regions`` for the defect that requires it. A caller that
    needs to know whether a fence was ever CLOSED strips again for itself,
    which is a validity question rather than a parsing one.

    ONE SCANNER, THREE VIEWS (``parse_lock_lists``, ``indented_list_lines``,
    ``parse_holds``): a second scan over the same section is how two readings
    of one file start to disagree, and "what was ignored" must be answered by
    exactly the code that ignored it.
    """
    body, _closed = strip_fenced_regions(body)
    present = False
    lists: dict[str, list[str]] = {name: [] for name in _LOCK_LIST_NAMES}
    ignored: list[str] = []
    holds_present = False
    holds: list[str] = []
    holds_none = False
    holds_ignored: list[str] = []
    section: str | None = None  # "lock", "holds", or outside both
    mode: str | None = None
    open_list = False  # a list head was seen, at either indentation
    for line in body.splitlines():
        if _LOCK_HEADING_RE.match(line):
            present, section, mode, open_list = True, "lock", None, False
            continue
        if _HOLDS_HEADING_RE.match(line):
            holds_present, section, mode, open_list = True, "holds", None, False
            continue
        if section is None:
            continue
        if _ANY_HEADING_RE.match(line):
            section = None
            continue
        if section == "holds":
            # THE HEADING IS THE LIST HEAD here - there is no ``holds:`` line -
            # so a column-zero bullet is a hold and an indented one is
            # illustration, reported rather than absorbed.
            hold_item = _LOCK_ITEM_RE.match(line)
            if hold_item:
                value = hold_item.group(1).strip()
                if _hold_marker_text(value) in _HOLD_NONE_MARKERS:
                    holds_none = True
                elif value:
                    holds.append(
                        value
                        if len(value) <= HOLD_CHARS
                        else value[:HOLD_CHARS] + HOLD_TRUNCATED_MARKER
                    )
                continue
            if _INDENTED_ITEM_RE.match(line):
                holds_ignored.append(line.strip()[:IGNORED_LINE_CHARS])
            continue
        if not line.strip():
            continue  # a blank line separates, it does not close a list
        list_head = _LOCK_LIST_RE.match(line)
        if list_head:
            mode = list_head.group(1).casefold()
            open_list = True
            continue
        item = _LOCK_ITEM_RE.match(line)
        if item and mode:
            value = item.group(1).strip().strip("`").strip()
            if value:
                lists[mode].append(value)
            continue
        # NOT LAW, BY INDENTATION - and reported rather than absorbed. A head
        # is always worth a note; an entry only while a list is open, which is
        # what keeps ordinary indented prose bullets quiet.
        if _INDENTED_LIST_RE.match(line):
            ignored.append(line.strip()[:IGNORED_LINE_CHARS])
            open_list = True
            mode = None
            continue
        if open_list and _INDENTED_ITEM_RE.match(line):
            ignored.append(line.strip()[:IGNORED_LINE_CHARS])
            mode = None
            continue
        mode = None  # prose ends the list it followed
        open_list = False
    return (
        present,
        lists,
        ignored,
        HoldsScan(
            present=holds_present,
            entries=tuple(holds),
            none_declared=holds_none,
            ignored=tuple(holds_ignored),
        ),
    )


def parse_lock_lists(body: str) -> tuple[bool, dict[str, list[str]]]:
    """``(present, lists)`` - the law the section declares. A view of the scan."""
    present, lists, _ignored, _holds = _scan_lock_section(body)
    return present, lists


def indented_list_lines(body: str) -> list[str]:
    """The indented list-shaped lines the scan refused. The other view."""
    _present, _lists, ignored, _holds = _scan_lock_section(body)
    return ignored


def parse_holds(body: str) -> HoldsScan:
    """What ``## Holds`` says, as written. The third view of the same scan.

    Raw on purpose: whether a given reading is USABLE is
    ``policy_lock_section``'s judgement, in one place, so the four states of
    A HOLD IS READ, NOT ENFORCED are decided once rather than per caller.
    """
    _present, _lists, _ignored, holds = _scan_lock_section(body)
    return holds


def parse_lock_section(body: str) -> tuple[bool, list[str], list[str]]:
    """``(present, lock entries, relax entries)`` - the two original lists.

    Kept as it was for every caller that predates ``workshop:``; the parse
    itself now lives in ``_scan_lock_section``, which this function is a view of.
    """
    present, lists = parse_lock_lists(body)
    return present, lists["lock"], lists["relax"]


#: The paths the workshop rule may never reach, whatever a ``workshop:`` list
#: says: the arming file (which CARRIES the workshop list, so refusing it is
#: what stops the model widening its own workshop) and the settings files that
#: register the gates. Exactly ``PROTECTED_FILES``, named separately so a
#: future addition to either set is a deliberate act rather than a side effect.
#: ``hooks/`` and ``.claude-plugin/`` are deliberately NOT here: they are the
#: self-hosted source the ratified decision is about.
WORKSHOP_NEVER: tuple[tuple[str, ...], ...] = PROTECTED_FILES


def workshop_entry_refusal(cwd: Path, entry: str) -> str:
    """Why this ``workshop:`` entry is refused, or ``""`` when it stands.

    Workshop design rule 1. The test is CONTAINMENT IN EITHER DIRECTION
    against ``WORKSHOP_NEVER``: an entry that names one of those files is
    refused, and so is any entry a governance file sits beneath - which is what
    disposes of ``.keel/``, ``.``, ``./``, ``..`` and the empty string without
    enumerating them. An entry keel cannot resolve at all is refused too
    (UNVERIFIABLE IS DENY, applied to configuration).
    """
    text = entry.strip()
    if not text:
        return "the empty string covers the whole project, governance included"
    base = norm(cwd, text)
    if not base:
        return "keel cannot resolve it to a location, so it cannot be compared"
    for parts in WORKSHOP_NEVER:
        governance = norm(cwd, os.path.join(*parts))
        if not governance:
            continue
        if base == governance or _under(governance, base):
            return (
                f"it is or contains {'/'.join(parts)}, which the policy lock "
                f"keeps for the user's own hand"
            )
    return ""


def workshop_forbidden(cwd: Path, target_norm: str) -> bool:
    """True for a target no workshop may ever cover - checked at the point of use.

    The second half of workshop design rule 1, and the reason it exists twice:
    ``workshop_entry_refusal`` screens the CONFIGURATION, this screens the
    TARGET, so a parser that ever mis-read a list cannot turn into a write on
    the governance surface. The same belt-and-braces shape ``relaxation_for``
    already uses for the anchor.
    """
    if not target_norm:
        return False
    return any(
        target_norm == norm(cwd, os.path.join(*parts)) for parts in WORKSHOP_NEVER
    )


def workshop_prefix_for(cwd: Path, target_norm: str, section: LockSection) -> str:
    """The declared workshop prefix this target falls under, or ``""``.

    Returns the ENTRY AS WRITTEN, because that is what the audit line and the
    stderr notice quote back: a reader of the log can see which declaration
    permitted the write. Empty for an unresolvable target, for a target on the
    governance surface (``workshop_forbidden``), and for a section carrying no
    workshop in force.
    """
    if not target_norm or workshop_forbidden(cwd, target_norm):
        return ""
    for entry in section.workshop_prefixes:
        base = norm(cwd, entry)
        if base and _under(target_norm, base):
            return entry
    return ""


# ======================================================================
# THE DECLARATION IS SURFACED - DESIGN RULE (workshop design rule 7)
#
# ``workshop:`` shipped ENFORCED AND UNREPORTED. The gate honoured every
# prefix, audited every write one permitted (``workshop_write``), and no
# reader anywhere named the field: neither the castoff orientation line nor
# ``keel survey``'s ``lock`` line carried it at all, so a session could not
# see which of its own source trees its model was permitted to rewrite. A
# REFUSED entry was worse off still - announced once, on stderr, at
# gate-event time (``announce_workshop_refusals``), and nowhere a reader
# looks BEFORE starting work.
#
# That is T168's absent-vs-none rule one field along, and the facts it keeps
# apart here are:
#   IN FORCE    the gate turns a policy-lock deny into an audited allow here
#   REFUSED     declared, and dropped as if it had never been written
#   NONE        nothing was ever declared, so nothing was lost
#   INVALID     declared, and carried by nothing, because the section errored
#   UNKNOWN     the arming file could not be read, so keel cannot say
# A reader that rendered REFUSED as NONE would tell a project it has no
# workshop when its owner wrote one and keel threw it away.
#
# ``workshop_state`` is THE one decision between them, exactly as
# ``holds_state`` is for ``## Holds``: R15 applied one level above the parse,
# because two readers agreeing about the bytes can still disagree about what
# they mean. Every surface renders its own wording FROM this string and none
# of them recomputes the state from an adjacent fact like ``valid``.
#
# AN INVALID SECTION IS RENDERED AS A LOSS, NOT AS A LIST, and this is the one
# place the workshop deliberately does NOT behave like the ``tighten`` and
# ``relax`` values printed beside it. Those two are reported AS PARSED even
# when the section is invalid, because over-stating a TIGHTENING misleads a
# reader in the safe direction. A workshop is a LOOSENING: printing entries an
# invalid section does not carry would tell a session it may rewrite source
# the gate is about to refuse it, and the reader would believe the wrong half.
# So the invalid state names the loss and prints no entry - which is what
# ``LockSection.workshop_prefixes`` already guarantees at the enforcement end,
# said out loud at the reporting end. The asymmetry is the same shape as
# ``hold_errors`` being kept out of ``errors``: mirror-imaging two fields
# whose failure directions differ is how one of them ends up unsafe.
#
# SURFACING ONLY. Nothing here decides anything. No reader may widen, narrow
# or re-derive what the workshop permits; ``workshop_entry_refusal``,
# ``workshop_forbidden`` and ``workshop_prefix_for`` remain the only answers
# to that question, and this rule exists so that their answer is legible
# before a write rather than only after one.
# ======================================================================

#: The five states of the ``workshop:`` declaration. Names, not sentences: the
#: castoff line and the survey line each choose their own wording, and neither
#: decides the state for itself.
WORKSHOP_NONE = "none"
WORKSHOP_ACTIVE = "active"
WORKSHOP_REFUSED = "refused"
WORKSHOP_INVALID = "invalid"
WORKSHOP_UNKNOWN = "unknown"

#: The whole set, so "every state has a reader" is a CHECKABLE claim rather
#: than a comment. The suite walks this tuple against both surfaces and demands
#: a real input for each and a distinct sentence from each, so a sixth state
#: added here without a reader fails the build instead of rendering silently as
#: whichever branch happens to catch it.
WORKSHOP_STATES: tuple[str, ...] = (
    WORKSHOP_NONE,
    WORKSHOP_ACTIVE,
    WORKSHOP_REFUSED,
    WORKSHOP_INVALID,
    WORKSHOP_UNKNOWN,
)


def workshop_state(section: LockSection) -> str:
    """Which state the ``workshop:`` declaration is in. THE one decision.

    ``WORKSHOP_UNKNOWN`` is never returned from here, and that is not an
    oversight: it belongs to a caller holding no section to ask about at all,
    because the arming file could not be read (``keel_survey``'s ``GateError``
    path). It is named with the other four so every reader branches over ONE
    closed set instead of inventing a fifth answer of its own.

    THE SET IS CLOSED AT BOTH ENDS, and it has to be checked at both. A state
    a report can produce that no reader can REACH is exactly as invisible as a
    field no reader carries - the defect this whole rule exists to close, one
    layer up - and the first cut of T176 shipped it: the renderers nested the
    workshop segment inside ``if present``, while the only producer of
    ``UNKNOWN`` pairs it with ``present`` FALSE, so an unreadable arming file
    printed the sentence a project declaring nothing gets. Both renderers now
    branch on the state and nothing else, and
    ``tests/test_keel_workshop_surface_t176.py`` walks all five against both
    surfaces from real input, so a state added here without a reader - or a
    reader that stops reaching one - fails the suite instead of going quiet.

    NOTHING DECLARED IS ANSWERED FIRST, before validity, and the order is
    deliberate: an invalid section that never declared a workshop has lost
    nothing, and reporting a loss there would send a reader hunting for a
    declaration nobody wrote. The safety property does not rest on the order -
    ``ACTIVE`` is reachable only through ``workshop_prefixes``, which is empty
    for an invalid section by construction - so the precision is free.
    """
    if not (section.workshop or section.workshop_refusals):
        return WORKSHOP_NONE
    if not section.valid:
        return WORKSHOP_INVALID
    if section.workshop_prefixes:
        return WORKSHOP_ACTIVE
    return WORKSHOP_REFUSED


def _hold_errors(holds: HoldsScan, fences_closed: bool) -> tuple[str, ...]:
    """Why this holds reading cannot be trusted, or ``()``.

    THREE WAYS A HOLDS SECTION FAILS, and each ends in the same place: the
    section is UNREADABLE, never empty. "keel could not tell" and "the user is
    holding nothing" are the two facts T168 exists to keep apart, and here they
    are the difference between a session that stops and a session that pushes.

    The unclosed fence is checked EVEN WHEN NO HEADING WAS FOUND: a fence the
    file never closes swallows every line after it, so "there is no ``## Holds``
    section" is precisely what keel is not entitled to conclude from that body.
    """
    errors: list[str] = []
    if not fences_closed:
        errors.append(
            f"a fenced code block in {'/'.join(POLICY_RELPATH)} is never closed, "
            f"so every line after it is unreadable - keel cannot tell whether a "
            f"'## Holds' section was declared at all, or where it ends; holds are "
            f"reported as UNKNOWN rather than as none until the fence is closed"
        )
    if not holds.present:
        return tuple(errors)
    if holds.none_declared and holds.entries:
        errors.append(
            f"the '## Holds' section declares BOTH an explicit none-marker and "
            f"{len(holds.entries)} hold(s); keel cannot tell which was meant, so "
            f"it settles neither - remove the marker, or remove the hold(s)"
        )
    if not holds.none_declared and not holds.entries:
        errors.append(
            "the '## Holds' section states nothing keel can read: no hold bullet "
            "at column 0, and no explicit none-marker either. A hold written as "
            "prose is invisible to every instrument keel has, so this is reported "
            "rather than read as an empty list - write each hold as '- <hold>' at "
            "column 0, or '- *(none active)*' when there are none"
        )
    return tuple(errors)


def holds_state(section: LockSection) -> str:
    """Which of the four states the holds section is in. THE one decision.

    Every reader - the castoff line, the survey line, a test - renders its own
    wording FROM this string and none of them decides the state for itself,
    which is R15 applied one level above the parse: two readers agreeing about
    the bytes can still disagree about what they mean.

    THE ORDER IS THE SAFETY PROPERTY. Errors are answered FIRST, so a section
    keel could not read can never be rendered as an explicit "none" by a reader
    that happened to check emptiness before validity.
    """
    if section.hold_errors:
        return HOLDS_UNREADABLE
    if not section.holds_present:
        return HOLDS_ABSENT
    if section.holds:
        return HOLDS_ACTIVE
    return HOLDS_NONE


def policy_lock_section(cwd: Path) -> LockSection:
    """The project's configuration section, validated. Never widens on doubt.

    Fenced regions are stripped before anything is read (documentation is not
    law - ``strip_fenced_regions``), and a fence the file never closed is a
    section ERROR rather than a silent truncation: an invalid section tightens
    nothing and loosens nothing, and the reason is carried into every refusal
    message (design rule 4).

    ``## Holds`` RIDES ALONG, from the same scan of the same body - see A HOLD
    IS READ, NOT ENFORCED. The holds fields are built BEFORE the early return
    below, because a project can hold something without configuring the lock at
    all, and that early return is the one path down which a whole Holds section
    could otherwise disappear.
    """
    stripped, fences_closed = strip_fenced_regions(policy_body(cwd))
    present, lists, ignored, holds_scan = _scan_lock_section(stripped)
    lock, relax, workshop = lists["lock"], lists["relax"], lists["workshop"]
    hold_fields: dict[str, Any] = {
        "holds_present": holds_scan.present,
        "holds": holds_scan.entries,
        "holds_none_declared": holds_scan.none_declared,
        "hold_errors": _hold_errors(holds_scan, fences_closed),
        "holds_ignored_indented": holds_scan.ignored,
    }
    if not present:
        return LockSection(**hold_fields)
    kept_workshop: list[str] = []
    refusals: list[str] = []
    for entry in workshop:
        reason = workshop_entry_refusal(cwd, entry)
        if reason:
            refusals.append(
                f"workshop entry {entry!r} is IGNORED as if it had not been "
                f"declared: {reason}"
            )
        else:
            kept_workshop.append(entry)
    errors: list[str] = []
    if not fences_closed:
        errors.append(
            "a fenced code block in .keel/keel-policy.md is never closed, so "
            "keel cannot tell which lines of this section are law and which are "
            "an example; the whole section is ignored until the fence is closed"
        )
    for entry in lock:
        if _lock_entry_covers_plans(cwd, entry):
            errors.append(
                f"lock entry {entry!r} covers {'/'.join(PLANS_RELPATH)}, where "
                f"session ledgers live; locking it would forbid the plan write "
                f"the plan gate demands"
            )
    for name in relax:
        if name.casefold() not in RELAXATIONS:
            errors.append(
                f"unknown relaxation name {name!r}; this keel ships "
                f"{', '.join(sorted(RELAXATIONS))}"
            )
    return LockSection(
        present=True,
        lock=tuple(lock),
        relax=tuple(name.casefold() for name in relax),
        errors=tuple(errors),
        workshop=tuple(kept_workshop),
        workshop_refusals=tuple(refusals),
        ignored_indented=tuple(ignored),
        **hold_fields,
    )


def announce_ignored_indented_lines(section: LockSection) -> None:
    """Say out loud which indented lines were refused as examples, not law.

    The loud half of A RATIFIED LIST LINE STARTS AT COLUMN ZERO. An owner who
    means a list and indents it must not have that intention silently absorbed
    - the whole family of defects here is a document being read as law and a
    declaration being read as documentation, and both directions are only safe
    if the parser says which reading it took. stderr, and never raising: a
    notice may not fail the gate it annotates.

    BOTH SECTIONS ARE ANNOUNCED HERE, each naming ITS OWN heading, because the
    scan that refused a line is the only thing that knows which section the
    line was in - and a note that named the wrong section would be a false
    fact printed by the mechanism whose whole job is not printing false facts.
    """
    for heading, lines in (
        ("## Policy lock", section.ignored_indented),
        ("## Holds", section.holds_ignored_indented),
    ):
        for line in lines:
            try:
                print(
                    f"keel: an INDENTED list line in the '{heading}' section of "
                    f"{'/'.join(POLICY_RELPATH)} was IGNORED - a ratified list line "
                    f"starts at column 0, so anything indented is an example or "
                    f"prose: {line!r}",
                    file=sys.stderr,
                )
            except Exception:  # noqa: BLE001 - a notice may never fail the gate
                return


def announce_workshop_refusals(section: LockSection) -> None:
    """Say out loud, once per event, which workshop entries were refused.

    "Fail closed, VISIBLY" (design rule 4) for the entry-level refusal: the
    entry is dropped, and the drop is never silent - a project that believes it
    declared a workshop and did not must be able to see why at the moment it
    costs something. stderr, because stdout on a PreToolUse hook is the
    harness's own decision channel (convention 7). Never raises: a notice may
    not fail the gate it annotates.
    """
    for line in section.workshop_refusals:
        try:
            print(f"keel: {line}", file=sys.stderr)
        except Exception:  # noqa: BLE001 - a notice may never fail the gate
            return


# ------------------------------------------------- the shipped relaxation


def tool_input_of(event: KeelEvent) -> Mapping[str, Any]:
    """The payload's ``tool_input`` mapping, or an empty one. Data, never code."""
    value = event.raw.get("tool_input")
    return value if isinstance(value, Mapping) else {}


def _apply_edit(current: str, old: Any, new: Any, replace_all: Any) -> str | None:
    """One edit applied in memory, or None when the result is indeterminable."""
    if not isinstance(old, str) or not isinstance(new, str) or not old:
        return None
    occurrences = current.count(old)
    if occurrences == 0:
        return None
    if replace_all is True:
        return current.replace(old, new)
    if occurrences != 1:
        return None  # the harness would refuse this too; keel does not guess
    return current.replace(old, new, 1)


def payload_carries_whole_content(tool_input: Mapping[str, Any]) -> str | None:
    """The complete new content a full-write payload carries, or None.

    ONE definition, TWO readers, which is the whole reason it is a function:
    ``resulting_content`` returns it as the result, and
    ``ledger_text_for_write`` asks it whether this write's verdict needs the
    file's current text AT ALL. A shape that answers here is decidable without
    reading the disk, so a disk that cannot be read does not have to stop it.
    """
    content = tool_input.get("content")
    return content if isinstance(content, str) else None


def resulting_content(current: str, tool_input: Mapping[str, Any]) -> str | None:
    """What the file would hold after this write, or None when unknowable.

    Three payload shapes are understood: a full write (``content``), a single
    edit (``old_string``/``new_string``) and a multi-edit (``edits``). Any
    other shape - a notebook cell, a payload with no content at all - returns
    None, which the caller reads as "stay denied" (design rule 5).
    """
    content = payload_carries_whole_content(tool_input)
    if content is not None:
        return content
    if "old_string" in tool_input:
        return _apply_edit(
            current,
            tool_input.get("old_string"),
            tool_input.get("new_string"),
            tool_input.get("replace_all"),
        )
    edits = tool_input.get("edits")
    if isinstance(edits, list) and edits:
        text = current
        for edit in edits:
            if not isinstance(edit, Mapping):
                return None
            text = _apply_edit(
                text,
                edit.get("old_string"),
                edit.get("new_string"),
                edit.get("replace_all"),
            )
            if text is None:
                return None
        return text
    return None


def differs_only_in_version(before: str, after: str) -> bool:
    """True when two JSON documents agree everywhere except ``version``.

    Both sides must parse as JSON objects and both must carry a string
    ``version``; everything else - key set, nesting, values - must be equal.
    Anything else is False, which keeps the verdict where it was.
    """
    try:
        left = json.loads(before)
        right = json.loads(after)
    except ValueError:
        return False
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    if not isinstance(left.get("version"), str) or not isinstance(right.get("version"), str):
        return False
    if set(left) != set(right):
        return False
    return {k: v for k, v in left.items() if k != "version"} == {
        k: v for k, v in right.items() if k != "version"
    }


def release_version_bump_applies(cwd: Path, raw_path: str, tool_input: Mapping[str, Any]) -> bool:
    """True when this write changes the manifest's version value and nothing else."""
    target_norm = norm(cwd, raw_path)
    if target_norm != norm(cwd, os.path.join(*MANIFEST_RELPATH)):
        return False
    path = Path(cwd).joinpath(*MANIFEST_RELPATH)
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False  # unreadable current file: indeterminable, so denied
    after = resulting_content(current, tool_input)
    if after is None:
        return False
    return differs_only_in_version(current, after)


#: Name -> the predicate that decides whether a write is that relaxation.
_RELAX_CHECKS = {"release-version-bump": release_version_bump_applies}


def relaxation_for(
    event: KeelEvent, cwd: Path, raw_path: str, section: LockSection
) -> str | None:
    """The enabled relaxation this write satisfies, or None.

    The anchor is refused here a second time (design rule 3): the vocabulary
    already contains no entry that could reach it, and this line makes a
    future entry that did a no-op rather than a hole.
    """
    if is_anchor(cwd, norm(cwd, raw_path)):
        return None
    tool_input = tool_input_of(event)
    for name, check in _RELAX_CHECKS.items():
        if section.relaxes(name) and check(cwd, raw_path, tool_input):
            return name
    return None


# ------------------------------------------------------------- plan freshness


def session_plan_relpath(sess8: str) -> str:
    """Ledger path for a session, project-relative, POSIX separators."""
    return "/".join((*PLANS_RELPATH, f"keel-plan-{sess8}.md"))


def plan_is_fresh(cwd: Path, sess8: str, env: Mapping[str, str]) -> bool:
    """True when this session's ledger exists and is younger than the TTL."""
    if not sess8:
        return False
    ttl_seconds = plan_ttl_minutes(env) * 60.0
    path = Path(cwd).joinpath(*PLANS_RELPATH, f"keel-plan-{sess8}.md")
    try:
        return (time.time() - path.stat().st_mtime) < ttl_seconds
    except OSError:
        return False


# -------------------------------------------------------- the plan contract


def is_session_ledger(cwd: Path, target_norm: str) -> bool:
    """True for ``.keel/plans/keel-plan-*.md`` - and for nothing else.

    Deliberately narrower than ``is_plan_target``: the bootstrap carve-out
    covers the whole directory, the contract assertion covers only the session
    ledgers inside it (see ``_LEDGER_NAME_RE``).
    """
    if not is_plan_target(cwd, target_norm):
        return False
    return _LEDGER_NAME_RE.match(os.path.basename(target_norm)) is not None


def load_plans_checker() -> Any:
    """The contract checker module. Raises on any import failure - never None.

    Imported, not executed: ``scripts/keel_plans.py`` is stdlib-only and pure,
    so the no-subprocess constraint is kept rather than bent.
    """
    if _SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, _SCRIPTS_DIR)
    import keel_plans  # noqa: PLC0415 - the path insert above must run first

    return keel_plans


class LedgerUnestablished(Exception):
    """No TRUE text for a ledger write could be had, so no verdict can be.

    RAISED RATHER THAN RETURNED, on ``load_plans_checker``'s model two
    definitions above: the unverifiable case leaves this module as an exception
    the one caller turns into a refusal, never as a value that reads like
    content. ``""`` is a LEGITIMATE ledger text - the absent file a bootstrap
    write is about to create - and so it cannot also mean "unknown". That one
    conflation was the whole defect (T201): an empty ledger yields no findings
    from ``check_ledger``, so every transient file fault became a silent hole in
    the rule, and the more broken the situation the more freely writes passed.

    Carries its own next step because the two faults that raise it have
    different doors; see ``plan_contract_unestablished_message``.
    """

    def __init__(self, detail: str, next_step: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.next_step = next_step


def ledger_text_for_write(
    cwd: Path, raw_path: str, tool_input: Mapping[str, Any], payload_describes_target: bool
) -> str:
    """The ledger text this write would leave behind, as far as it is knowable.

    Raises ``LedgerUnestablished`` when it is not knowable at all - never a
    substitute for it.

    THE ASSERTION IS ABOUT THE CONTENT BEING WRITTEN, not about what is on
    disk. A ``Write`` payload carries the whole new content, so that is what is
    read; an ``Edit``/``MultiEdit`` payload carries a substitution, which is
    applied IN MEMORY to the current file (``resulting_content``, the same
    helper the shipped relaxation uses - one definition of "what this write
    produces").

    WHEN NEITHER IS DETERMINABLE the ON-DISK text is checked instead, and never
    a guess: an ambiguous edit, a notebook cell, a payload with no content at
    all. That fallback is stated rather than silent because it is the honest
    half of the two - it asserts something true (the ledger as it stands)
    rather than something invented, and it cannot manufacture a refusal for a
    file that is clean today. ``payload_describes_target`` is False for a
    multi-file payload, where the single ``tool_input`` cannot be attributed to
    one of several targets.

    ABSENT IS NOT UNREADABLE, and that distinction is this function's failure
    policy. ``FileNotFoundError`` is a NORMAL state with a meaning of its own -
    the ledger a bootstrap write is about to create, whose text is entirely the
    payload's - so it reads as an empty current file exactly as it always did.
    Any OTHER read fault (a Windows lock, a denied permission, a directory
    standing where the file should be, a path the platform will not resolve)
    means keel does not know what the file holds, and that is raised rather
    than flattened into ``""``.

    THE READ FAULT IS ONLY FATAL WHERE THE READ MATTERS. A payload carrying the
    whole content decides the verdict by itself - see
    ``payload_carries_whole_content`` - so it is answered BEFORE any fault is
    raised, because refusing there would be over-refusal - and worse, it would
    shut the one door that keeps the record writable while the file is in a bad
    state, which is T179's clause 3 in this function's own terms.

    THE EDIT PATH IS COVERED BY WHERE THE RAISE SITS: it is above
    ``resulting_content``, so a substitution can no longer fail to find its
    ``old_string`` in invented emptiness and then fall back to that same
    emptiness - which is precisely the two-step the defect took. The shape left
    over is a substitution with NO TEXT to apply to, whether the file is absent
    or genuinely empty: the fallback to on-disk text asserts something true only
    where there IS on-disk text, and an empty verdict is the one verdict that
    checks nothing. So that too is refused - distinguished from the bootstrap
    write (fixture 07) by the payload, which declares no substitution at all,
    and leaving the on-disk fallback for an ambiguous edit against a real ledger
    exactly as it was.
    """
    fault: Exception | None = None
    current = ""
    try:
        current = Path(os.path.join(str(cwd), raw_path)).read_text(
            encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        pass  # absent: a normal state, and the one the bootstrap write needs
    except (OSError, ValueError) as exc:
        fault = exc
    whole = payload_carries_whole_content(tool_input) if payload_describes_target else None
    if whole is not None:
        return whole
    if fault is not None:
        # ``strerror`` in preference to ``str(exc)``: the platform's own words
        # name the FAULT ("Permission denied", "Is a directory") while ``str``
        # appends the absolute filename, which has no business in a message
        # keel echoes back (convention 5's spirit, one layer early).
        detail = getattr(fault, "strerror", None) or str(fault)
        raise LedgerUnestablished(
            f"read failed - {type(fault).__name__}: {scrub(detail)}",
            NEXT_STEP_LEDGER_UNREADABLE,
        ) from fault
    if not payload_describes_target:
        return current
    after = resulting_content(current, tool_input)
    if after is not None:
        return after
    if not current and ("old_string" in tool_input or tool_input.get("edits")):
        raise LedgerUnestablished(
            "the payload describes a substitution and the ledger holds no text "
            "it could be applied to",
            NEXT_STEP_LEDGER_ABSENT_EDIT,
        )
    return current


def plan_contract_verdict(
    event: KeelEvent, targets: Sequence[tuple[str, str]]
) -> KeelVerdict | None:
    """A deny for a contract-violating ledger write, or None to allow.

    None means "this assertion has nothing to say": the write names no session
    ledger, or every ledger it names satisfies the machine-checkable contract.
    A ledger carrying NO TASK LINES yields no findings from
    ``keel_plans.check_ledger`` and so is allowed here by construction - plan
    freshness governs emptiness, this rule governs content that exists.

    THREE REFUSALS AND ONLY ONE OF THEM IS ABOUT THE LEDGER'S CONTENT. The
    checker may not load, and the ledger's own text may not be establishable
    (``LedgerUnestablished``); both deny, because a rule that cannot reach a
    verdict must not report the verdict "fine". Unverifiable is deny, applied to
    the tool, the subject and the payload alike.
    """
    ledgers = [raw for raw, target in targets if is_session_ledger(event.cwd, target)]
    if not ledgers:
        return None
    try:
        plans = load_plans_checker()
    except Exception as exc:  # noqa: BLE001 - unverifiable is deny, and named
        return deny(
            plan_contract_unreadable_message(event, f"{type(exc).__name__}: {exc}"),
            gate="plan_contract",
            target=relativise(event.cwd, ledgers[0]),
        )
    tool_input = tool_input_of(event)
    # The PAYLOAD's target count, for the reason ``_project_verdict`` gives for
    # leaving ``file_paths`` whole: one payload describing one target is what
    # makes its content attributable, and ``targets`` may be one project's
    # share of a wider payload.
    single = len(event.file_paths) == 1
    for raw in ledgers:
        shown = relativise(event.cwd, raw)
        try:
            text = ledger_text_for_write(event.cwd, raw, tool_input, single)
        except LedgerUnestablished as exc:
            # CAUGHT HERE AND NOWHERE ELSE, and the placement is the point: were
            # this to escape ``evaluate`` it would reach the crash path, whose
            # carve-out PERMITS writes under .keel/plans/ (T179) - so a refusal
            # left uncaught would arrive as an allow. Fail-closed means caught.
            return deny(
                plan_contract_unestablished_message(event, shown, exc.detail, exc.next_step),
                gate="plan_contract",
                target=shown,
                unestablished=True,
            )
        findings = [
            finding
            for finding in plans.check_ledger(shown, text, False)
            if finding.rule in BLOCKING_PLAN_RULES
        ]
        if findings:
            return deny(
                plan_contract_message(event, shown, findings),
                gate="plan_contract",
                target=shown,
                findings=len(findings),
                rules=sorted({finding.rule for finding in findings}),
            )
    return None


# ======================================================================
# SHELL POLICY LOCK - DESIGN RULE (fixtures pin both directions)
#
# A shell command is a policy-lock violation only when ONE pipeline
# segment carries BOTH a mutation - a mutating command word, an
# assignment to a KEEL_* variable, or a redirect whose target is a real
# file rather than an fd duplicate (2>&1, >&2) or a null sink
# (/dev/null, NUL) - AND a protected name that the same segment could be
# acting on (for a redirect, that means the redirect's own target).
# Mutations are read only from a segment's UNQUOTED text, because text
# inside quotes or a heredoc body is data - a grep pattern, a commit
# message - and cannot execute; protected NAMES, by contrast, count
# quoted or not, since a mutator's path argument is routinely quoted.
#
# FAIL SAFE: anything this parser cannot resolve - an unterminated quote
# or heredoc, a redirect with no target, an over-long command, any
# exception - abandons the analysis and blocks if the raw command
# mentions a protected name at all.
#
# Rejected: a read-only leading-verb allowlist (grep/cat/git log/...) AS
# THE RULE. It is the same growing special-case list this rule replaces,
# and the mutator list already states the inverse; an unknown verb such
# as `py` or `node` is not evidence of mutation and must not be treated
# as one. `cd` is the one exception: chdir-ing INTO a protected directory
# taints every later segment, so `cd hooks && rm *.py` still blocks even
# though the second segment names nothing protected.
#
# AMENDED 2026-09-06 (T513, BL54), AND THE REJECTION ABOVE STANDS AS
# WRITTEN: the allowlist is not the rule and does not decide a refusal -
# it can only WITHDRAW one. A segment is a mutation when the verb list
# says so AND the read-only allowlist cannot prove the word writes
# nothing; an unknown verb still passes, so the sentence about `py` and
# `node` is untouched. WHY IT WAS NEEDED: the verb list is matched over
# the segment's whole unquoted code, so it fired on words that were
# ARGUMENTS rather than commands - `grep -n set hooks/keel_gate.py` was
# refused for the `set` in its pattern, and `sed -n '1,5p'
# hooks/keel_gate.py` because `sed` is on the list unconditionally. Both
# only NAME a locked path. The measured cost of leaving that alone was
# not nuisance: every false refusal trains the user toward
# KEEL_OVERRIDE, so the lock was manufacturing the bypass pressure it
# exists to remove - the same argument rule 2 recorded on 2026-08-18.
#
# THE RULING IT IMPLEMENTS, so a later reader does not reopen it as a
# bug: the scan does NOT gain a path resolver and the scope stays
# SHAPE-based, because a resolver that can be fooled is worse than one
# that over-refuses. Only the predicate narrows - from "names a locked
# path" to "names a locked path AND could mutate it".
#
# NO SECOND PREDICATE AND NO SECOND LIST: the withdrawal asks
# ``_segment_word_is_read_only``, rule 2's, under its own DESIGN RULE
# further down - two-part membership test, `sed` and `find` admitted only
# in forms proven read-only from the command text, command substitution
# and leading assignments refused. Everything that list refuses to
# certify keeps its refusal here, which is the fail-closed direction.
# FAIL SAFE IS UNCHANGED AND UNREACHABLE FROM HERE: the withdrawal is
# applied per segment, after the redirect test and after every fail-safe
# return, so an over-long, unparsable or unresolvable command still
# blocks on the raw text whatever word stands at its head.
#
# SCOPE OF THIS REJECTION: it holds HERE, for the policy-lock rule, and
# nowhere else. What makes a denylist sufficient for THIS rule is the
# protected-NAME test sitting beside it: a segment is only ever asked
# about its verb AFTER it has already been shown to name something
# protected, so the verb list only ever has to state the inverse of a
# mutation - never the inverse of "every command that exists". An earlier
# reading of this rejection as binding on rule 2 (the plan gate's shell
# scope) as well was an error, not a consequence of anything argued above:
# rule 2 has no name test to narrow it, nothing comes before the verb
# question, so a denylist there would have to enumerate every command
# that is NOT read-only, which is exactly the unclosable set this project
# tried and rejected. Rule 2 carries its own design rule, beside
# ``shell_is_read_only`` below, arguing why an allowlist is the correct
# shape there.
# ======================================================================

#: Names of protected FILES, matched as a path COMPONENT or a filename STEM -
#: never as a bare substring. Any absolute prefix in front of them still
#: matches, on either separator: "c:\p\hooks\keel_gate.py" and
#: "~/p/hooks/keel_gate.py" both carry "keel_gate".
#:
#: WHY NOT A SUBSTRING, which is what this was until 2026-09-03. A bare
#: substring test blamed any longer name that happened to contain one of these
#: for a file it has nothing to do with: `sed -n 1,20p
#: tests/test_keel_gate_t169.py` was refused as a policy-lock write because the
#: TEST's name contains "keel_gate", and read-only greps naming
#: ".claude-plugin/" were refused on 2026-09-01 and three more times on
#: 2026-09-02. It fails CLOSED, so it cost friction rather than safety - but an
#: adopter meets it in the first hour and reads it as keel refusing to let them
#: look at their own tests. `_PROT_DIR_RE` below already made exactly this
#: distinction for directory names and states the same reasoning ("a bare
#: 'hooks' substring would blame 'my_hooks/' and 'hooks.txt' for nothing");
#: this is that treatment applied to the file names too.
PROT_FILE_TOKENS: tuple[str, ...] = (
    "keel-policy.md",
    "keel_gate",
    "keel_stop",
    "keel_hook",
    "keel_events",
    "keel_adapter",
    "settings.json",
)

#: Protected ENVIRONMENT VARIABLE names, which are not files and must not be
#: matched as if they were. `KEEL_OVERRIDE` appears in text as an assignment or
#: a shell variable reference - `KEEL_OVERRIDE=on`, `$env:KEEL_OVERRIDE`,
#: `setx KEEL_OVERRIDE on` - never as a path component with a separator in
#: front of it, so the path-segment test would MISS every real spelling. They
#: keep a case-insensitive WORD-boundary test instead, which accepts all three
#: spellings above and still declines to match inside a longer identifier.
PROT_ENV_TOKENS: tuple[str, ...] = (
    "keel_override",
    "keel_plan_ttl_min",
)

#: Both sets, in the order they were one tuple, for any reader that wants the
#: whole protected vocabulary in one place. Nothing matches against this: the
#: two halves are matched by different rules, which is the point.
PROT_TOKENS: tuple[str, ...] = PROT_FILE_TOKENS + PROT_ENV_TOKENS

#: A protected file name standing as its own path segment or filename stem.
#:
#: The left edge is the same class `_PROT_DIR_RE` uses - start, whitespace, a
#: quote, `=`, `(`, `:`, `;` or either separator - so a word character in front
#: of the token means the text is not a segment at all but the tail of a longer
#: name (`test_keel_gate_t169.py`, `my_keel_gate_notes.txt`), which names no
#: protected file.
#:
#: The right edge accepts what `_PROT_DIR_RE` accepts AND, unlike it, a dot
#: followed by an extension - because these are FILE names and `hooks/
#: keel_gate.py` is their ordinary spelling, where `hooks.txt` was precisely
#: the thing the directory rule had to refuse. A trailing `_t169` is still not
#: an extension, so the test file stays unmatched from both ends.
_PROT_FILE_RE = re.compile(
    r"(?:^|[\s\"'=(:;/\\])(?:" + "|".join(re.escape(t) for t in PROT_FILE_TOKENS) + r")"
    r"(?=$|[\s\"')/\\:;&|,]|\.[A-Za-z0-9]+)",
    re.IGNORECASE,
)

#: A protected environment variable named anywhere as its own word.
_PROT_ENV_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(t) for t in PROT_ENV_TOKENS) + r")\b",
    re.IGNORECASE,
)

#: Protected DIRECTORY names, matched as whole path components rather than as
#: substrings. keel's locked directories sit at the repository root, so `cd
#: hooks` is a plausible command in a way `cd .claude/hooks` never is - and a
#: bare "hooks" substring would blame "my_hooks/" and "hooks.txt" for nothing.
#: Case-insensitive by default (convention 3).
_PROT_DIR_RE = re.compile(
    r"(?:^|[\s\"'=(:;/\\])(?:hooks|\.claude-plugin)(?=$|[\s\"')/\\:;&|,])",
    re.IGNORECASE,
)

_MAX_CMD = 20000
_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([a-z_][a-z0-9_]*)\1")
# Word-anchored so "del" never matches inside "model" and "set" never
# matches inside "reset"/"offset"/"settings".
_MUTATE_VERB_RE = re.compile(
    r"(?:^|[\s;&|(`])"
    r"(?:rm|rmdir|rd|del|erase|mv|move|ren|cp|copy|tee|truncate|unlink"
    r"|chmod|attrib|icacls|setx|set|export)(?=$|[\s.])"
    r"|\bsed\s+-\w*i"
    r"|\b(?:set-content|out-file|add-content|clear-content|new-item"
    r"|remove-item|move-item|copy-item|rename-item)\b"
)
_ENV_ASSIGN_RE = re.compile(r"\$\{?env:\w+\}?\s*[+]?=")
# A quoted command word still executes ("rm" x), so a segment's first token
# is matched against the bare verb names as well. `sed` is in this set
# unconditionally: its mutation is flag-dependent, so as a command word it
# is assumed to mutate. THAT ASSUMPTION IS NOW WITHDRAWN FOR ONE PROVEN
# SHAPE AND NO OTHER (T513): `_shell_hits` asks `_segment_word_is_read_only`,
# which asks `sed_is_print_only`, before it believes this list - so
# `sed -n '1,5p' <locked>` is a read and `sed -i`, `sed -e`, a regex address
# and every other spelling still land here as a mutation.
_MUTATE_VERBS = frozenset(
    "rm rmdir rd del erase mv move ren cp copy tee truncate unlink chmod "
    "attrib icacls setx set export sed set-content out-file add-content "
    "clear-content new-item remove-item move-item copy-item rename-item".split()
)
_CHDIR_VERBS = frozenset(("cd", "chdir", "pushd", "set-location", "sl"))
_NULL_SINKS = frozenset(("/dev/null", "nul", "nul:", "$null", "\\\\.\\nul"))


def has_prot(text: str) -> bool:
    """True when text names anything the policy lock protects.

    THREE TESTS, one per kind of name, because the kinds appear in command
    text in different shapes: a protected FILE as a path component or filename
    stem (`_PROT_FILE_RE`), a protected DIRECTORY as a whole path component
    (`_PROT_DIR_RE`), and a protected ENVIRONMENT VARIABLE as a bare word
    (`_PROT_ENV_RE`). Each declines to match inside a longer identifier, which
    is the whole difference from the substring test this replaced.

    STILL A TEXT TEST, and still FAIL-CLOSED, both deliberately. It reads the
    command as text rather than resolving paths, so any prefix in front of a
    name still counts and a name reached by a variable or built by
    concatenation still is not seen - the residual `_shell_hits` records under
    its own docstring, unchanged by this. And every fail-safe in `_shell_hits`
    answers through this predicate on the WHOLE command text, so tightening it
    tightens those too: an over-long or unparsable command is now refused only
    when it names a protected file as a segment rather than as any substring.
    That is intended - a fail-safe that blames the wrong file is the same
    defect as a rule that does, one refusal further along - and the fixtures
    that pin those paths name real protected paths, so they still see one.
    """
    return bool(
        _PROT_FILE_RE.search(text)
        or _PROT_DIR_RE.search(text)
        or _PROT_ENV_RE.search(text)
    )


def strip_heredocs(text: str) -> tuple[str, bool]:
    """Drop heredoc bodies: they are stdin DATA, never command text.

    Returns ``(text, ok)``; ``ok`` is False if a heredoc is never terminated.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        for match in _HEREDOC_RE.finditer(line):
            word = match.group(2)
            while i < len(lines) and lines[i].strip() != word:
                i += 1
            if i >= len(lines):
                return "\n".join(out), False
            i += 1  # drop the terminator line too
    return "\n".join(out), True


def scan_segments(text: str) -> tuple[list[dict], bool]:
    """Quote-aware split into pipeline segments (``; && || | & newline``).

    Per segment: ``text`` = every token with quotes stripped (data + code);
    ``code`` = only the characters that were OUTSIDE quotes; ``redirs`` =
    ``[(operator, target)]`` for each ``> >> n> n>> &> >&``.
    Returns ``(segments, ok)``; ok=False means "could not parse confidently".
    """
    segs: list[dict] = []
    ok = True
    seg: dict = {"text": [], "code": [], "redirs": []}
    tok_t: list[str] = []
    tok_c: list[str] = []
    pending: str | None = None

    def end_token() -> None:
        nonlocal pending, tok_t, tok_c
        if tok_t or tok_c:
            word = "".join(tok_t)
            if pending is not None:
                seg["redirs"].append((pending, word))
                pending = None
            seg["text"].append(word)
            seg["code"].append("".join(tok_c))
            tok_t, tok_c = [], []

    def end_segment() -> None:
        nonlocal seg, pending, ok
        end_token()
        if pending is not None:  # redirect with no target - unresolvable
            seg["redirs"].append((pending, ""))
            pending = None
            ok = False
        segs.append(seg)
        seg = {"text": [], "code": [], "redirs": []}

    i, n = 0, len(text)
    while i < n:
        char = text[i]
        if char in "'\"":
            j = text.find(char, i + 1)
            if j < 0:  # unterminated quote
                tok_t.append(text[i + 1:])
                ok = False
                i = n
            else:
                tok_t.append(text[i + 1:j])  # content is data, not code
                i = j + 1
        elif char in " \t":
            end_token()
            i += 1
        elif char in "\n\r;":
            end_segment()
            i += 1
        elif char == "|":
            end_segment()
            i += 2 if text[i:i + 2] == "||" else 1
        elif char == "&":
            if text[i:i + 2] == "&&":
                end_segment()
                i += 2
            elif text[i:i + 2] == "&>":  # bash: both streams to a file
                end_token()
                i += 2
                if text[i:i + 1] == ">":
                    i += 1
                pending = "&>"
            else:
                end_segment()
                i += 1
        elif char == ">":
            if "".join(tok_t).isdigit():  # fd prefix of "2>", "1>>"
                tok_t, tok_c = [], []
            end_token()
            op = ">"
            i += 1
            if text[i:i + 1] == ">":
                op = ">>"
                i += 1
            if text[i:i + 1] == "&":  # fd duplication: 2>&1, >&2
                op += "&"
                i += 1
            pending = op
        else:
            tok_t.append(char)
            tok_c.append(char)
            i += 1
    end_segment()
    return segs, ok


def redirect_writes_file(op: str, target: str) -> bool:
    """A ">" is a mutation only when it aims at a real file."""
    if op.endswith("&"):
        return False  # fd duplication writes no file
    stripped = target.strip().casefold()
    if not stripped:
        return True  # unresolved target - assume it is a real file
    return stripped not in _NULL_SINKS


def shell_hits_policy_lock(cmd: str) -> bool:
    """Apply the DESIGN RULE above to a casefolded shell command."""
    return _shell_hits(cmd, has_prot)


def shell_policy_lock_unclassifiable(cmd: str) -> bool:
    """True when the lock's OPEN world lets a command past that its CLOSED world
    would have stopped - the gap between the two modes, and nothing else (E1).

    THE ONE THAT MATTERS, measured by 28 synthetic probes on 2026-08-27 (BL11):
    ``python -c "open('.keel/keel-policy.md','w').write('x')"`` is ALLOWED,
    silently, against the arming file whose protection is this product's
    headline claim. It names no verb on ``_MUTATE_VERBS``, carries no redirect,
    and the open mode has nothing left to judge it by. Nine of the ten known
    bypasses are of that shape: an interpreter one-liner, a ``bash -c`` or
    ``eval`` carrying the refused text one level down, or a verb the list does
    not happen to name.

    WHY THIS IS A COMPARISON AND NOT A NEW PARSER: ``_shell_hits`` already
    implements both worlds, and ``shell_hits_user_global`` already runs the
    closed one over keel's user-global state. So the gap is exactly the
    difference between the two answers over the SAME command and the SAME
    protected set. Nothing new can be wrong here that is not already wrong in
    one of the two modes this file has shipped and tested for months.

    WHY IT ONLY RECORDS. Switching the policy lock to the closed world would
    close the gap and REFUSE ``git diff hooks/``, ``jq . hooks/x``, and every
    other read reaching a locked path through a word the allowlist does not
    name - the cost ``_shell_hits`` states plainly for the mode that accepts it.
    That is a trade the owner has not made. So the refuse predicate is untouched
    and this one only says, on the record, THAT THE LOCK COULD NOT CLASSIFY WHAT
    IT ALLOWED. Blast radius is therefore zero BY CONSTRUCTION rather than by
    measurement: ``_shell_hits(cmd, has_prot)`` decides refusals exactly as it
    did, and nothing currently allowed can become refused.

    THE NOISE IS REAL AND WAS MEASURED, not estimated: over 6,611 shell commands
    in this repository's own audit log, 214 would newly record a line (3.24%),
    against 188 refused today and unchanged. That is the WORST CASE anywhere -
    this is the one project on earth that routinely runs ``git diff hooks/``.

    THE HONEST LIMIT, recorded rather than papered over: ``tar -xf payload.tar``
    names no protected path, so neither mode can judge it and this predicate is
    correctly silent. No path scanner closes that one.

    ON EVERY FAIL-SAFE PATH THIS PREDICATE IS FALSE, and that is right rather
    than a hole - said here because a difference of two answers hides it, and a
    reader checking whether an oversize command can evade the record deserves
    the answer in one place. ``_shell_hits`` answers an oversize command, an
    unterminated heredoc or a scan that could not run with ``names(cmd)`` in
    BOTH modes, so the two collapse to ``X and not X``. The reason nothing is
    lost: that same fail-safe makes the OPEN mode return True for any such
    command that names a protected path, so the lock REFUSES it outright. There
    is no allow to annotate. A command that names nothing protected is allowed
    and unremarkable in both modes. So the silence here is never the silence of
    a bypass going unrecorded - it is the silence of a refusal having already
    happened, which is the stronger outcome. Raised by the E1 silent-failure
    review, 2026-08-31, and answered by ``_MAX_CMD`` case in the tests below it.
    """
    return _shell_hits(cmd, has_prot, closed=True) and not _shell_hits(cmd, has_prot)


def _shell_hits(cmd: str, names: Callable[[str], bool], closed: bool = False) -> bool:
    """The DESIGN RULE's segment scan, over ANY "does this text name it" test.

    ``names`` is the only thing that varies between the two protected sets this
    scan serves - the policy lock's own (``has_prot``) and keel's user-global
    state (``names_user_global``, THE GLOBAL RULE further down). The scan
    itself - heredoc stripping, quote-aware segmentation, the redirect test,
    the ``cd`` taint and the fail-safes - is one body rather than two copies,
    because two copies of a shell scanner drift and the drift is invisible:
    the weaker copy simply stops refusing something.

    ``closed`` PICKS WHICH WAY A SEGMENT IS JUDGED ONCE IT NAMES THE PROTECTED
    SET, and the two answers are the open world and the closed one:

      False (the policy lock) - OPEN WORLD: the segment is a hit only if it
      looks mutating, by the verb list and the env-assignment test, AND its
      command word is not one the read-only allowlist can PROVE writes
      nothing. Anything the verb list does not name still passes, exactly as
      before - an unknown word is not evidence of mutation, which is the
      rejection this rule's DESIGN RULE has always carried.

      THE SECOND CLAUSE IS T513 (BL54), AND IT ONLY EVER SHRINKS THE REFUSAL
      SET: ``mutating_new = not read_only and mutating_old`` implies
      ``mutating_old``, so no command that was allowed can become refused,
      and no refusal survives except through a word the allowlist could not
      clear. What it removes is the ARGUMENT-level false positive the verb
      list cannot avoid: the verbs are matched against the whole segment's
      unquoted code, so ``grep -n set hooks/keel_gate.py`` was refused for
      the word `set` in its PATTERN, and ``sed -n '1,5p' hooks/keel_gate.py``
      for `sed` standing in ``_MUTATE_VERBS`` unconditionally. Both merely
      NAME a locked path; neither can reach it. The predicate is the same
      ``_segment_word_is_read_only`` rule 2 has shipped since 2026-08-18,
      with its own DESIGN RULE, its two-part membership test and its
      argument-dependent ``sed``/``find`` forms - reused, not re-derived.

      WHAT THE NARROWING DOES NOT TOUCH, because it sits below them in the
      loop: the redirect test (``cat notes.md > hooks/keel_gate.py`` is the
      redirect's hit, not the word's), the ``cd`` taint, and every fail-safe
      return above - an over-long command, an unterminated quote or heredoc,
      an unresolved redirect target, any exception - which still answer
      ``names(cmd)`` on the raw text. So a command whose SHAPE could not be
      established is still refused when it names a locked path, however
      read-only the word at its head looks.

      True (keel's user-global state) - CLOSED WORLD: the segment is a hit
      UNLESS its command word is on the read-only allowlist
      (``_segment_word_is_read_only``). A ``cd`` into the set still only
      taints, since it changes no file - and so does merely NAMING the set,
      which taints the REST of the command in this mode: once the name has
      been spelled, every later segment is judged as though it named the set
      itself, so only an all-read-only command survives past that point. A
      per-segment test alone was not enough, because a pipeline hands the set
      to the next segment without spelling it twice: ``find <set> -type f |
      xargs rm -f`` and ``ls <set> | xargs rm`` were read as an allowlisted
      find or ls followed by an ``xargs`` naming nothing, and deleted the
      directory's contents with no deny and no record (second isolated
      review, 2026-08-22, 85%). THE OPEN MODE DELIBERATELY DOES NOT TAKE
      THIS TAINT: it would change what the policy lock refuses, which is that
      rule's question to answer (T202), not a side effect of this one.

    WHY THE SECOND MODE EXISTS, stated where the next reader meets it: a verb
    list cannot bound what an interpreter does. ``python3 -c "open(<path>,
    'w').write(x)"`` names no verb on any list, carries no redirect, and
    rewrote keel's registry through this scan with no refusal and no record
    (isolated review, 2026-08-22; the same defect family as
    .keel/knowledge/a-shell-rewrite-is-atomic-on-disk-and-invisible-to-the-gate.md
    and the open question in T202). No enumeration of mutating words closes
    that, because the mutation is inside a string the gate cannot execute; the
    only closable direction is to enumerate what provably cannot write, which
    ``_READ_ONLY_COMMANDS`` already does under its own DESIGN RULE.

    WHAT THE CLOSED MODE COSTS, said plainly: a READ that names the set
    through an unlisted word - ``python -c "print(open(<path>).read())"``,
    ``jq . <path>``, ``git diff <path>`` - is refused too, because no matcher
    can tell a read from a write inside an interpreter one-liner. The spelled
    taint adds a second cost of the same kind: after the set is named, an
    unlisted segment is refused even when it aims somewhere else entirely -
    ``ls <set> && rm -rf /tmp/x`` is one refusal, not two commands. Both are
    one refusal with the override named in its message, against a silent
    rewrite of state every project on the machine shares. WHAT IT STILL DOES NOT
    CATCH, equally plainly: a command that never spells the path - built by
    concatenation, read from a variable, or reached after a ``cd`` this scan
    did not see - names nothing for ``names`` to match, and this is a TEXT
    test. That residual is accepted, not closed.

    Every fail-safe answers through ``names`` as well, so a command too large
    to parse, an unterminated heredoc or a scan that could not run is judged by
    the same test on the whole command text. FAIL SAFE, NEVER FAIL OPEN, for
    both callers.
    """
    if len(cmd) > _MAX_CMD:
        return names(cmd)  # fail safe: too big to parse
    try:
        body, heredoc_ok = strip_heredocs(cmd)
        segs, scan_ok = scan_segments(body)
    except Exception:  # noqa: BLE001 - fail safe, never fail open
        return names(cmd)
    if not (heredoc_ok and scan_ok):
        return names(cmd)  # fail safe

    tainted = False  # a preceding `cd` moved us into a protected directory
    spelled = False  # closed mode: an earlier segment already NAMED the set
    for seg in segs:
        text = " ".join(seg["text"])
        code = " ".join(seg["code"])
        for op, target in seg["redirs"]:
            if redirect_writes_file(op, target) and (tainted or names(target)):
                return True
        first = seg["text"][0] if seg["text"] else ""
        # ONE read-only predicate, asked once, serving BOTH modes (T513/BL54).
        # Its contract is exactly the question both need answered here - "is
        # this segment's command WORD incapable of writing anything" - and a
        # second predicate beside it would drift the way a second scanner
        # would. It is deliberately asked AFTER the redirect test above and
        # AFTER every fail-safe return, so neither can be exempted by it.
        read_only = _segment_word_is_read_only(seg)
        # A chdir is excused in the closed mode - it is not on the read-only
        # allowlist and would otherwise be read as a mutation of the directory
        # it merely stands in - and then taints below, exactly as in the open
        # mode. Everything else the allowlist does not name IS the mutation.
        mutating = (
            not (first in _CHDIR_VERBS or read_only)
            if closed
            else (
                not read_only
                and (
                    first in _MUTATE_VERBS
                    or bool(_MUTATE_VERB_RE.search(code))
                    or bool(_ENV_ASSIGN_RE.search(code))
                )
            )
        )
        if mutating and (tainted or spelled or names(text)):
            return True
        if first in _CHDIR_VERBS and names(text):
            tainted = True
        if closed and names(text):
            # THE SPELLED TAINT (closed mode only). Naming the set HANDS IT to
            # the rest of the command - down a pipe as data, after a `&&` as a
            # fact the next segment already knows - so every later segment is
            # judged as if it named the set too. Without this, an allowlisted
            # read that names it set nothing, and the mutation one segment
            # later named nothing left to match: `find <set> -type f | xargs
            # rm -f` and `ls <set> | xargs rm` both passed silently.
            spelled = True
    return False


# ======================================================================
# SHELL PLAN CONTRACT - DESIGN RULE (fixtures pin both directions)
#
# Rule 3 asserts a session ledger's CONTENT, and content is exactly what
# a shell command does not carry: the bytes only exist once the command
# has run, which is after the only moment the gate gets. So no attempt is
# made to reconstruct them. The mutation half of the shell heuristic
# above is reused verbatim - same segmentation, same mutating-verb and
# redirect tests, same fail-safe - with the protected-name test swapped
# for "this token names a session ledger". A mutating segment that names
# one is DENIED unread; a read-only one (cat, grep, git add) is not
# touched, because reading a ledger asserts nothing about it.
#
# The `cd` taint of the policy-lock rule is deliberately NOT carried
# over: a ledger is identified by its FILENAME, which any command that
# writes it must still name, whatever directory it stands in - so
# `cd .keel/plans && echo x > keel-plan-abcd1234.md` is caught by the
# redirect target alone and the taint would only add false positives.
#
# THE ONE EXEMPTION, added 2026-08-18 with the read-only allowlist below:
# a segment whose `sed` is PROVABLY a print (``sed_is_print_only``, whose
# rules are stated with rule 2's design rule) is not a mutation of
# anything, so it cannot be a mutation of a ledger. `sed` sits in
# ``_MUTATE_VERBS`` unconditionally because its behaviour is
# flag-dependent, and that assumption refused a measured read of a ledger
# (`sed -n '510,545p' .keel/plans/keel-plan-<sess8>.md`) with a message
# telling the reader to use the Write tool instead - a refusal of a READ,
# which rule 3 never meant to make: it asserts CONTENT a write would
# leave behind, and a print leaves none. The exemption reaches only that
# one provable shape, is applied AFTER the redirect test (so
# `sed -n '1,5p' x > keel-plan-abcd1234.md` still denies on its redirect),
# and `sed -i` - the shape that does rewrite a ledger - still denies
# through both the verb set and ``_MUTATE_VERB_RE``. Fixtures pin all
# three directions.
# ======================================================================

#: Where a command's text is cut into path-like tokens for the ledger test:
#: whitespace, quotes, and the shell punctuation that can abut a path. The
#: basename of each piece is then matched against ``_LEDGER_NAME_RE``, the same
#: one definition of "a session ledger's name" that ``is_session_ledger`` uses -
#: so a bare ``keel-plan-abcd1234.md`` and a full
#: ``.keel\plans\keel-plan-abcd1234.md`` both count, on either separator.
_TOKEN_SPLIT_RE = re.compile(r"[\s\"'`|&;<>()=,]+")


def names_session_ledger(text: str) -> bool:
    """True when any path-like token in text names a session ledger.

    Filename-based on purpose, and therefore WIDER than
    ``is_session_ledger``: no directory is required, because a command may
    reach the ledger from anywhere and a shell path cannot be normalised the
    way a tool's ``file_path`` can. The cost is that a ``keel-plan-*.md`` kept
    somewhere else is treated as a ledger by a mutating command; the house
    doctrine prefers that to a rewrite the gate never saw.
    """
    for token in _TOKEN_SPLIT_RE.split(text):
        if not token:
            continue
        base = token.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        if _LEDGER_NAME_RE.match(base):
            return True
    return False


def shell_writes_session_ledger(cmd: str) -> bool:
    """Apply the DESIGN RULE above: does this command MUTATE a session ledger?

    The mirror of ``shell_hits_policy_lock``, differing in the name test and in
    the one print-only ``sed`` exemption the DESIGN RULE above states.
    """
    if len(cmd) > _MAX_CMD:
        return names_session_ledger(cmd)  # fail safe: too big to parse
    try:
        body, heredoc_ok = strip_heredocs(cmd)
        segs, scan_ok = scan_segments(body)
    except Exception:  # noqa: BLE001 - fail safe, never fail open
        return names_session_ledger(cmd)
    if not (heredoc_ok and scan_ok):
        return names_session_ledger(cmd)  # fail safe

    for seg in segs:
        text = " ".join(seg["text"])
        code = " ".join(seg["code"])
        for op, target in seg["redirs"]:
            if redirect_writes_file(op, target) and names_session_ledger(target):
                return True
        first = seg["text"][0] if seg["text"] else ""
        if first == "sed" and sed_is_print_only(seg["text"]):
            continue  # provably a print: no content to assert (see DESIGN RULE)
        mutating = first in _MUTATE_VERBS or bool(_MUTATE_VERB_RE.search(code))
        if mutating and names_session_ledger(text):
            return True
    return False


# ======================================================================
# GIT WITH RESTORE SEMANTICS AGAINST .keel/ - DESIGN RULE (BL2, T318)
# (fixtures pin every direction named below)
#
# ``git checkout -- .keel/audit/keel-audit.jsonl .keel/queue/keel-observations.jsonl
# .keel/plans/keel-plan-c62332f5.md`` ran through this gate as a plain read: it
# carries no mutating verb and no redirect, so the OPEN-mode scan the policy
# lock and the session-ledger rule both use (``_MUTATE_VERBS``,
# ``_MUTATE_VERB_RE``) saw nothing to match, and it discarded every
# uncommitted append to keel's own audit log, observation queue and session
# ledger with no deny, no bypass line and no audit row (filed 2026-08-25 by
# session c62332f5, ``.keel/backlog.md`` BL2). It IS a write, whatever the verb
# looks like: ``checkout``, ``restore``, ``reset`` and ``clean`` REPLACE or
# REMOVE working-tree content from the index, a commit, or nothing at all -
# the same act ``rm`` or a truncating redirect already denies under the rules
# above, spelled with a different verb this file never taught either of them.
#
# NARROWED BY SUBCOMMAND, the same discipline that removed `git` from
# ``_READ_ONLY_COMMANDS`` entirely (see the DESIGN RULE beside it, and its own
# note on ``_READ_ONLY_COMMANDS``): no verb list can speak for `git` as a
# whole - `git status`, `git diff` and `git log -p` can run an external pager
# or diff driver, `git add`, `git commit` and `git fetch` touch nothing under
# .keel/ at all. So this rule enumerates the FOUR subcommands whose ORDINARY
# effect writes the working tree from elsewhere - ``checkout``, ``restore``,
# ``reset``, ``clean`` (``_GIT_RESTORE_SUBCOMMANDS``) - and asks nothing about
# any other subcommand. ``git status``, ``git log``, ``git diff``, ``git
# show``, ``git ls-files``, ``git grep`` and ``git stash list`` are none of
# the four; this rule never reaches them, and they still face rule 2's plan
# gate exactly as before - unchanged, and pinned by the existing fixtures for
# it (``56-git-status-still-needs-a-plan.json``, ``78-git-ls-files-still-
# needs-a-plan.json`` among them).
#
# NAMED, NOT MERELY SHAPED: one of the four subcommands is refused only when
# its OWN argument names a path under .keel/ - ``names_dot_keel_path``, the
# same boundary-anchored substring test ``has_prot``/``names_user_global``
# already use, so ".keel" only matches as a path component (".keel/x",
# "./.keel/x", an absolute path ending in it) and never a sibling that merely
# shares the spelling (".keel-notes/", the same over-match ``_PROT_DIR_RE``'s
# own comment already refuses for "hooks"). ``git checkout main`` and
# ``git checkout -- src/somefile.py`` name nothing under .keel/ and pass this
# rule untouched (rule 2 still asks for a plan; `git checkout` is not on the
# read-only allowlist either way). ``git checkout -- .keel/plans/keel-plan-
# *.md`` and a bare ``git checkout .keel/audit/keel-audit.jsonl`` (no ``--``,
# but the operand still spells a path under .keel/) are both refused: a
# `--` is not required for the write shape, only an operand that resolves
# path-like into .keel/ is - present whether or not `--` introduced it.
#
# ``reset`` IS THE ONE SHAPE-NARROWED SUBCOMMAND OF THE FOUR
# (``_git_restore_is_write_shape``), because ``--soft`` moves HEAD only and
# touches neither the index nor the working tree - provably nothing changes on
# disk, the same direction rule 3 already takes for a provable ``sed`` print
# ("a PRINT leaves no content", beside ``shell_writes_session_ledger``). So a
# reset carrying ``--soft`` is excluded before the .keel/ name test ever runs.
# Every other reset shape still qualifies: ``--hard``, ``--mixed``, ``--keep``,
# or a bare pathspec with no mode flag at all - because ``--mixed`` is reset's
# own default, and a bare ``git reset .keel/x`` demands the same accounting a
# spelled-out ``--mixed`` would.
#
# PER-SEGMENT, OPEN WORLD, NO ``cd`` TAINT - the SAME scope
# ``shell_writes_session_ledger`` already uses for the session ledger, and
# deliberately NOT the closed, whole-command taint THE GLOBAL RULE uses for
# keel's user-global directory. The two rules differ for the reason
# ``_shell_hits``'s own docstring states it: THE GLOBAL RULE'S closed mode
# exists because a verb list cannot bound an interpreter one-liner, so once
# the directory is NAMED at all, everything after it is judged read-only or
# refused. This rule has no such gap to close - it is narrowed by a NAME TEST
# the way rule 1 and rule 3 already are (a segment is only ever asked about
# .keel/ after its OWN git invocation has already been shown to be one of the
# four restore-semantics subcommands, in a shape that provably writes), the
# same structure that lets rule 1 and rule 3 use a closed enumeration safely
# where rule 2 cannot (see the REJECTED entry beside ``_MUTATE_VERB_RE``: "a
# segment is only ever asked about its verb AFTER it has already been shown to
# name something protected"). ONE CAUTION STATED SO IT IS NOT WIDENED BY
# IMPLICATION, THE SAME ONE THE GLOBAL RULE NAMES FOR ITSELF: a command that
# reaches .keel/ only through a preceding ``cd`` this scan does not carry
# forward (``cd .keel/audit && git checkout -- keel-audit.jsonl``) spells
# nothing under .keel/ IN THIS SEGMENT'S OWN TEXT and is not caught by this
# rule - rule 2's plan gate still reaches it, as an unlisted git subcommand,
# and this is the same residual ``has_prot``/``names_session_ledger`` already
# accept for a path named only by an earlier ``cd``.
# ======================================================================

#: A path under THIS project's own .keel/ directory, matched as a whole path
#: COMPONENT the way ``_PROT_DIR_RE``/``_USER_GLOBAL_RE`` already match theirs,
#: so any prefix in front of ``.keel`` still counts and a sibling that merely
#: shares the spelling does not. The backslash is built with ``chr(92)``
#: rather than typed, the same defect class this repository has already paid
#: for once (see ``_USER_GLOBAL_RE``). Case-insensitive by default
#: (convention 3).
_DOT_KEEL_PATH_RE = re.compile(
    r"(?:^|[\s\"'=(:;/" + re.escape(chr(92)) + r"])\.keel"
    r"(?=$|[\s\"')/" + re.escape(chr(92)) + r":;&|,])",
    re.IGNORECASE,
)

#: Git subcommands whose ORDINARY effect replaces or removes working-tree
#: content from the index, a commit, or nothing at all - never one that merely
#: reads it. Enumerated by name for the reason stated in the DESIGN RULE
#: above: no verb LIST can speak for `git` as a whole, only a subcommand can.
_GIT_RESTORE_SUBCOMMANDS = frozenset(("checkout", "restore", "reset", "clean"))

#: The one `git reset` flag that is provably NOT this rule's business: it
#: moves HEAD only, touching neither the index nor the working tree, so a
#: reset carrying it is excluded before the .keel/ name test ever runs.
_GIT_RESET_SOFT_FLAG = "--soft"

#: git's OWN global options - the ones accepted BEFORE the subcommand - that
#: consume a SEPARATE following token as their value. Read out of git's
#: ``handle_options`` in ``git.c``, which is the only authority on this list:
#: each of these names is compared whole there and then advances argv twice.
#: THIS SET EXISTS BECAUSE OF A REAL BYPASS. The first cut of this rule skipped
#: pre-subcommand options by looking past every token that starts with ``-``,
#: which is correct for a flag and WRONG for one of these: the value token
#: (``/tmp`` in ``git -C /tmp checkout -- .keel/audit/keel-audit.jsonl``, or
#: ``a=b`` in ``git -c a=b restore .keel/...``) does not start with ``-``, so
#: it was returned AS THE SUBCOMMAND, matched none of the four restore verbs,
#: and the whole command fell through to a silent allow with no audit row -
#: exactly the failure this rule was written to end, reachable by typing five
#: more characters. Two shapes are deliberately NOT here because git does not
#: consume a separate token for them: ``--opt=value`` in one token (handled by
#: the ``=`` test below, which also covers the glued ``-cfoo=bar``), and
#: ``--exec-path`` with no ``=``, which prints git's exec path and EXITS rather
#: than taking the next token - so treating it as valueless is what git does.
_GIT_VALUE_GLOBALS = frozenset((
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--super-prefix",
    "--shallow-file",
    "--config-env",
    "--attr-source",
))

#: git's global options that consume NOTHING beyond themselves, from the same
#: reading of ``handle_options``. This set is not used to skip anything - a
#: token starting with ``-`` is skipped either way - it is used to tell a
#: RECOGNISED option from an UNRECOGNISED one, which is the only thing that
#: decides whether the token after it can be trusted to be the subcommand or
#: has to be treated as possibly some unknown option's value. See
#: ``_git_restore_subcommand`` for what that distinction buys.
_GIT_FLAG_GLOBALS = frozenset((
    "-p",
    "--paginate",
    "-P",
    "--no-pager",
    "--bare",
    "--no-replace-objects",
    "--no-lazy-fetch",
    "--no-optional-locks",
    "--no-advice",
    "--literal-pathspecs",
    "--no-literal-pathspecs",
    "--glob-pathspecs",
    "--noglob-pathspecs",
    "--icase-pathspecs",
    "--no-icase-pathspecs",
    "--exec-path",
    "--html-path",
    "--man-path",
    "--info-path",
    "--version",
    "--help",
))


def names_dot_keel_path(text: str) -> bool:
    """True when TEXT names a path under THIS project's own .keel/ directory.

    Same shape as ``has_prot``/``names_user_global``: a boundary-anchored
    substring test over raw command text, so any prefix in front of ``.keel``
    still matches, and a sibling that merely shares the spelling
    (``.keel-notes/``) does not. It answers only "does this text spell a
    .keel/ path", never "is the command carrying it a write" - that is
    ``_git_restore_is_write_shape``'s question, asked first by the caller.
    """
    return bool(_DOT_KEEL_PATH_RE.search(text))


def _git_restore_subcommand(tokens: Sequence[str]) -> str:
    """The git subcommand a ``git ...`` segment's tokens name, or "".

    ``tokens[0]`` is already known to be ``git``. Everything between it and
    the subcommand is one of git's own global options, and THE VALUE OF AN
    OPTION IS NOT ALWAYS ATTACHED TO IT: ``git -C /tmp checkout`` and
    ``git -c a=b restore`` spell their values as separate tokens that do not
    start with ``-``. Skipping "every token that starts with ``-``" therefore
    does NOT reach the subcommand in those shapes - it returns the VALUE, and
    a value matches none of the four restore verbs, so the rule silently
    allowed a real destructive command (see ``_GIT_VALUE_GLOBALS``). This
    walker exists to be right about that, in three rules:

    1. A token in ``_GIT_VALUE_GLOBALS`` is skipped WITH the token after it.
       This is exact: those are the options git itself advances argv twice for.
    2. Any other token starting with ``-`` is skipped alone. When it is a
       recognised valueless global, or carries its value inline as
       ``--opt=value`` (the ``=`` test, which also covers ``-cfoo=bar``), that
       is exact too, and the next non-dash token IS the subcommand.
    3. Otherwise the option is one this reading of git does not know - a
       version newer than this file, or a typo - and it MIGHT consume the next
       token. That token can no longer be trusted to be the subcommand, so
       rather than return it and fall through to a silent allow (the defect
       above, in its general form), this FAILS CLOSED: if any later token in
       the segment is one of the four restore verbs, that verb is returned and
       the caller goes on to ask its ``.keel/`` name test.

    HONEST RESIDUAL of rule 3, stated rather than hidden. The look-ahead is
    reached ONLY after an unrecognised ``-``-prefixed token, and it only ever
    upgrades the classification - never the name test, which still has to find
    a ``.keel/`` path in the same segment. Its cost is a possible false DENY:
    an unknown-option command whose operand happens to be spelled exactly
    ``checkout``, ``restore``, ``reset`` or ``clean`` (a branch or tag so
    named) AND that also spells a ``.keel/`` path is refused though it may
    only read. That is the direction this gate is allowed to be wrong in, and
    the door is the same one every other refusal here uses: the user's own
    ``KEEL_OVERRIDE=on``. A command with no unrecognised option in front of
    its subcommand never reaches rule 3 at all, so ``git status``,
    ``git diff``, ``git log`` and ``git -C <dir> status`` are classified by
    their real subcommand and are untouched by it.

    Two residuals are NOT closed here, because they are not this function's to
    close: a subcommand reached through an alias or a shell function spells no
    restore verb in the segment's text, and neither does one reached through a
    preceding ``cd`` this scan does not carry forward - both are the same
    open-world residual the DESIGN RULE above already states, and rule 2's
    plan gate is what still stands in front of them.
    """
    index = 1
    unresolved = False
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            break
        index += 1
        if token in _GIT_VALUE_GLOBALS:
            index += 1  # rule 1: the option's own value, dash-prefixed or not
        elif "=" not in token and token not in _GIT_FLAG_GLOBALS:
            unresolved = True  # rule 3: this one might have eaten the next token
    if index >= len(tokens):
        return ""
    candidate = tokens[index]
    if not unresolved or candidate in _GIT_RESTORE_SUBCOMMANDS:
        return candidate
    for token in tokens[index + 1:]:
        if token in _GIT_RESTORE_SUBCOMMANDS:
            return token
    return candidate


def _git_restore_is_write_shape(sub: str, tokens: Sequence[str]) -> bool:
    """Does THIS invocation of a restore-semantics subcommand touch disk?

    True for every ``checkout``/``restore``/``clean`` invocation - the DESIGN
    RULE above narrows those three by NAME, not by shape, because every
    ordinary invocation replaces or removes something. ``reset`` is the one
    exception: ``--soft`` moves HEAD only, so it is excluded here; every other
    reset shape - ``--hard``, ``--mixed``, ``--keep``, or a bare pathspec with
    no mode flag at all (``--mixed`` is reset's own default) - still
    qualifies.
    """
    if sub == "reset":
        return _GIT_RESET_SOFT_FLAG not in tokens
    return True


def shell_hits_dot_keel_restore(cmd: str) -> bool:
    """True when a git command with RESTORE SEMANTICS names a .keel/ path.

    See the DESIGN RULE above (BL2, T318): PER-SEGMENT, OPEN WORLD, no ``cd``
    taint - the shape ``shell_writes_session_ledger`` already uses, not the
    closed whole-command taint THE GLOBAL RULE uses for keel's user-global
    directory. A segment is a hit only when its OWN first token is ``git``,
    its OWN subcommand is one of the four restore-semantics ones, that
    invocation's OWN shape provably touches disk
    (``_git_restore_is_write_shape``), and its OWN text spells a path under
    .keel/ (``names_dot_keel_path``).

    Every fail-safe answers through ``names_dot_keel_path`` on the raw text
    instead, the same fail-safe every scanner in this file already uses: a
    command too large to parse, an unterminated heredoc, or a scan that could
    not run is judged by the plain text test rather than allowed through
    unread.
    """
    if len(cmd) > _MAX_CMD:
        return names_dot_keel_path(cmd)  # fail safe: too big to parse
    try:
        body, heredoc_ok = strip_heredocs(cmd)
        segs, scan_ok = scan_segments(body)
    except Exception:  # noqa: BLE001 - fail safe, never fail open
        return names_dot_keel_path(cmd)
    if not (heredoc_ok and scan_ok):
        return names_dot_keel_path(cmd)  # fail safe

    for seg in segs:
        tokens = seg["text"]
        if not tokens or tokens[0] != "git":
            continue
        sub = _git_restore_subcommand(tokens)
        if sub not in _GIT_RESTORE_SUBCOMMANDS:
            continue
        if not _git_restore_is_write_shape(sub, tokens):
            continue
        if names_dot_keel_path(" ".join(tokens)):
            return True
    return False


#: The name this refusal carries in the verdict, in the audit line, and in the
#: ``gate_bypass`` line when the override suspends it - its OWN name, the same
#: reason THE GLOBAL RULE carries ``user_global`` rather than ``policy_lock``:
#: a reader of the record must be able to count destructive git commands
#: against keel's own record surfaces apart from every other kind of refusal.
DOT_KEEL_RESTORE_GATE = "keel_restore"

#: The event name for a command the policy lock allowed WITHOUT being able to
#: classify it (E1) - a sibling of ``gate_bypass`` and ``workshop_write``, and
#: counted apart from both because it records the absence of a judgement rather
#: than the exercise of a permission. It keeps ``gate: policy_lock``: the rule
#: that could not judge is the rule that would have refused.
#:
#: SPELLED ONCE AND IMPORTED BY ITS TESTS, never matched as a literal - a guard
#: whose test spells its own marker by hand is disarmed by a rename with the
#: suite still green, which is what
#: .keel/knowledge/a-marker-matched-by-literal-disarms-on-rename.md records.
LOCK_UNCLASSIFIABLE_EVENT = "lock_unclassifiable"

#: The next step for a refused restore-semantics command. The door is the
#: override, exactly as it is for the policy lock: no configuration loosens
#: this, only the user's own hand.
NEXT_STEP_DOT_KEEL_RESTORE = (
    "NEXT STEP: never restore, reset or clean keel's own record paths on a "
    "delegate's own initiative - if a file under .keel/ genuinely needs to go "
    "back to its last committed content, that is the USER's call, made with a "
    "session the USER launched with KEEL_OVERRIDE=on. Reading it first (git "
    "status, git diff, git log, git show) is never refused; only the commands "
    "that would REPLACE or REMOVE its content are."
)


def dot_keel_restore_message(event: KeelEvent) -> str:
    """The block message for a git command with restore semantics naming .keel/."""
    head = (
        f"KEEL RECORD RESTORE ({event.tool_name or event.kind}): this command "
        "carries git RESTORE SEMANTICS (checkout / restore / reset --hard, "
        "--mixed or --keep / clean) against a path under .keel/ - the audit "
        "log, the observation queue, a session ledger, or anything else keel "
        "keeps there. That REPLACES OR REMOVES the file's working-tree content "
        "from the index, a commit, or nothing at all, exactly as rm or a "
        "truncating redirect would - it is a write, never a read, whatever the "
        "verb looks like. Only the user may run it (KEEL_OVERRIDE=on)."
    )
    return _joined(head, NEXT_STEP_DOT_KEEL_RESTORE, "(Guardrail: keel-restore.)")


# ======================================================================
# PLAN FRESHNESS ON THE SHELL - DESIGN RULE (fixtures pin both directions)
#
# Rule 2 governs STATE-CHANGING tools, as the contract at the top of this
# file says. On the write path that scope costs nothing to decide: the
# payload names a path, and a path is either written or it is not. A
# command names nothing, so the scope has to be read out of the command
# text - and here, unlike rules 1 and 3, NO NAME TEST NARROWS THE
# QUESTION. Rule 1 only ever asks about a segment that already names
# something protected; rule 3 only ever asks about a segment that already
# names a ledger. Rule 2 has nothing beside it to narrow the field first,
# so a denylist here has to enumerate every command that is NOT
# read-only - and that set has no edge: an interpreter can be decorated
# (`python3.11`), renamed (`cp /usr/bin/python x`) or invented next
# release, and each is a fresh way to be wrong about "not a mutation".
# Two attempts at exactly that denylist are recorded in this project's
# ledger, and both were defeated the same way.
#
# THE CLOSED-WORLD ANSWER IS THE OTHER DIRECTION: enumerate what IS safe,
# on a read-only ALLOWLIST, and require a fresh plan for everything the
# list does not name. Nothing can talk its way past a list it was never
# added to - no decoration, no rename, no interpreter invented after this
# file was last reviewed - because the list does not reason about a
# command word at all, it only recognises the ones it was given.
# ``shell_is_read_only`` below is a command runs without a ledger ONLY
# WHEN EVERY ONE of its pipeline segments clears it:
#
#   1. the segment's command word is on ``_READ_ONLY_COMMANDS``, or it is
#      one of the two words admitted only in a form PROVEN read-only from
#      the command text itself (``sed`` and ``find``, below);
#   2. the segment carries no redirect that writes a real file (the same
#      test rules 1 and 3 use: an fd duplication or a null sink is not a
#      write, anything else is);
#   3. the segment carries no command substitution - ``$(...)``,
#      backticks, ``<(...)`` - because that runs text this gate is never
#      shown, and "cannot be concluded" is deny, per the failure policy;
#   4. the segment carries no leading ``NAME=value`` assignment, because
#      `KEEL_OVERRIDE=on ls` names a harmless verb while doing something
#      the verb never discloses.
#
# A heredoc is covered upstream, by the same ``strip_heredocs`` rules 1
# and 3 call before segmenting: its body is stdin data, and an
# unterminated one already fails the parse (see FAIL SAFE below).
#
# THE MEMBERSHIP TEST, IN TWO PARTS - and the second part is why `git` and
# `rg` are NOT on this list, though both were on it when this allowlist
# first shipped:
#
#   (a) NO DOCUMENTED INVOCATION WRITES. No flag of the word may write,
#       delete or move a file. GNU `diff`'s own `-o`/`--output` lives on
#       `patch`, never on `diff` itself, which is why bare `diff` needs no
#       disqualifier; interactive pagers fail this part outright, since
#       `less` can spawn a shell from its own prompt.
#
#   (b) NO CONFIGURATION MAY CHOOSE A PROGRAM FOR IT TO RUN. A word whose
#       binary consults repository, user or environment CONFIG to decide
#       which subprocess to execute is not read-only, however read-only its
#       own arguments look, because the decisive input is a file the gate
#       never reads and this project does not protect. Reviewer finding,
#       2026-08-19, and it is the reason `git` left this list entirely:
#         - `git diff`, `git show` and `git log -p` run an EXTERNAL DIFF or
#           TEXTCONV driver named by `.gitattributes` plus `diff.<d>.command`
#           / `diff.<d>.textconv` (or `GIT_EXTERNAL_DIFF`) WITH NO FLAG
#           ASKED FOR - the attribute alone is enough - so an allowlisted
#           `git diff` can be arbitrary execution the gate just blessed;
#           `log`/`show` additionally run `gpg.program` when
#           `log.showSignature` is set.
#         - `git status`, which looks like the safest word in git, runs
#           `core.fsmonitor`'s program and the `filter.<d>.clean` driver of
#           any path whose attributes name one - it must, to decide whether
#           such a path is modified.
#         - `git ls-files` is the closest to defensible and still leaves,
#           because "I could not think of a driver for this subcommand" is
#           not the same claim as part (b), and the list may only carry
#           words that satisfy the claim.
#       THE MIDDLE PATH WAS CONSIDERED AND REJECTED: admitting `git diff`
#       when the invocation itself carries `--no-ext-diff --no-textconv`
#       (detected, never rewritten - the gate does not touch commands) would
#       hold only as long as nobody adds a NEW config-chosen program to
#       these subcommands, and `log.showSignature` already shows they come
#       in families. Enumerating "every way git can be configured to run
#       something" is the same unclosable set the denylist above was
#       rejected for; the closed-world direction says a word whose safety
#       depends on such an enumeration does not belong on the list.
#       THE PAGER, for the same reason, is not relied on either way: git
#       invokes `core.pager` only when its stdout is a terminal, and a hook
#       runs while the harness captures the tool's output through a pipe -
#       but that is a property of the CALLER's stdio, which this gate cannot
#       observe from the command text. An allowlist may not rest on a fact
#       it cannot check.
#         - `rg` leaves for the same class, on a smaller surface:
#           `RIPGREP_CONFIG_PATH` points at a file of flags ripgrep applies
#           to every invocation, and `--pre <program>` in that file runs a
#           program per searched file. `grep` stays: the deprecated
#           `GREP_OPTIONS` could only ever add FLAGS, and no grep flag runs
#           a program.
#
# WHAT THIS COSTS, said plainly rather than hidden: `git status` needs a
# ledger again. That was a measured false block (castoff, 2026-08-18), and
# closing it this way is the correct trade because the orientation castoff
# needs is already injected at session start by ``hooks/keel_session.py``
# (arming, lock state, the conflict scan, the switches) without a shell at
# all, while `ls`, `cat`, `grep`, `head`, `tail`, `wc`, `diff`, `find` and
# `sed -n '1,5p'` still run with no ledger. A gate that blesses config-chosen
# execution to save a `git status` has stopped being a gate.
#
# THE TWO ARGUMENT-DEPENDENT WORDS, and why each earns its own predicate
# rather than a place on the bare list (measured false blocks, 2026-08-18:
# `git status` at castoff, `diff`/`grep` after a plan-TTL expiry, and a
# read-only `sed -n '510,545p'` on a ledger - every false block trains the
# user toward KEEL_OVERRIDE, so the gate was manufacturing the very bypass
# pressure the friction line reports):
#
#   `find` is read-only under every flag EXCEPT the action family that
#   deletes or executes, so it is admitted through
#   ``_FIND_WRITE_FLAG_PREFIXES``: `-delete`, `-exec`/`-execdir`,
#   `-ok`/`-okdir`, `-fprint`/`-fprint0`/`-fprintf` and `-fls` disqualify
#   the segment, tested as PREFIXES over every later token so a bare
#   `find . -name x` orients and `find . -delete` still asks for a plan.
#
#   `sed` mutates or prints depending on its FLAGS, which is exactly the
#   distinction the mutation heuristic could not draw - it assumed `sed`
#   mutates, and refused a read of a ledger. ``sed_is_print_only`` draws it
#   in the conservative direction: the segment clears only when a quiet flag
#   is present (`-n`, `--quiet`, `--silent`), NO OTHER FLAG appears at all
#   (so `-i`, `-i.bak`, `--in-place`, `-e`, `-f`, `-E`, `--` and anything
#   invented later all disqualify), and the single script operand is a bare
#   print address - `p`, `5p`, `510,545p`, `1,$p`, `$p` and nothing else, so
#   no `w` command, no `/regex/` address and no `;`-joined second command
#   can hide inside it. Everything sed can do that is not provably that
#   shape still asks for a plan.
#
# ONLY THE COMMAND WORD IS TESTED, never a segment's arguments - the same
# restraint rule 1's rejected allowlist would have needed and rule 2 keeps
# on purpose: testing arguments for exec-looking suffixes would deny `grep
# pattern foo.py` and `cat setup.py`, read-only commands that merely
# MENTION a script, which is the scope mismatch this rule exists to
# remove (fixture: reading a script is not running one).
#
# FAIL SAFE, the same structure ``shell_writes_session_ledger`` uses, with
# the per-segment loop kept INSIDE the try as ``shell_mutates_anything``
# (now removed) improved on it: an over-long command, an unterminated
# quote or heredoc, an unresolved redirect, any exception, and an exec
# event carrying no command text at all all count as NOT READ-ONLY, so
# freshness is asked and a missing ledger still blocks. THERE IS NO BRANCH
# HERE THAT ANSWERS TRUE ON A FAILURE: an unresolved case must default to
# "needs a plan", the same direction every other failure in this file
# defaults to.
# ======================================================================

#: Command words that satisfy BOTH parts of the membership test above: no
#: documented invocation writes, and no configuration can name a program for
#: them to run. Kept deliberately small: a command missing from it is one more
#: request for a ledger, never a hole, so the list only grows when a word is
#: checked against every flag it has AND against every config file its binary
#: reads. ``git`` and ``rg`` were removed on 2026-08-19 under part (b) - the
#: DESIGN RULE above names the drivers, subcommand by subcommand.
_READ_ONLY_COMMANDS = frozenset(
    "cat grep egrep fgrep head tail wc ls pwd echo diff".split()
)

#: ``find``'s action family - the flags that make it delete, execute or write
#: a file. Tested as PREFIXES over every later token in the segment: ``-exec``
#: covers ``-execdir``, ``-ok`` covers ``-okdir``, ``-fprint`` covers
#: ``-fprint0`` and ``-fprintf``. Over-blocking a harmless token that merely
#: starts with one of these is the safe direction and costs a plan, not a hole.
_FIND_WRITE_FLAG_PREFIXES = ("-delete", "-exec", "-ok", "-fprint", "-fls")

#: The only ``sed`` flags a print-only invocation may carry. Anything else -
#: including ``-e``/``-f``, which could add a second script keel would then
#: have to parse - disqualifies the segment.
_SED_QUIET_FLAGS = frozenset(("-n", "--quiet", "--silent"))

#: A ``sed`` script that provably only prints: an optional line/``$`` address,
#: an optional second one after a comma, and the single command ``p``. No
#: regex address, no ``w`` (which writes a file), no ``;`` (which joins a
#: second command), no braces, no substitution. Anchored at both ends.
_SED_PRINT_SCRIPT_RE = re.compile(r"^(?:\d+|\$)?(?:,(?:\d+|\$))?p$")


def sed_is_print_only(tokens: Sequence[str]) -> bool:
    """True when a segment's ``sed`` is provably a print, not an edit.

    Reads the segment's TOKENS (quotes already stripped by ``scan_segments``,
    text already casefolded by the caller), and answers True only for the shape
    the DESIGN RULE above enumerates: command word ``sed``, at least one quiet
    flag, no other flag of any kind, exactly one script operand matching
    ``_SED_PRINT_SCRIPT_RE``, and any number of file operands after it.

    EVERY OTHER SHAPE IS FALSE, including several that happen to be read-only
    (``sed -n -e '1p' f``, ``sed '1,5p' f`` without ``-n``, ``sed -n '/x/p'
    f``): this predicate exists to open one named door - the measured
    ``sed -n '510,545p'`` - not to model sed. False costs a plan; True on a
    wrong guess would cost a file.
    """
    if not tokens or tokens[0] != "sed":
        return False
    quiet = False
    script: str | None = None
    for token in tokens[1:]:
        if token.startswith("-") and token != "-":
            if token in _SED_QUIET_FLAGS:
                quiet = True
                continue
            return False  # any other flag: unproven, so it keeps its gate
        if script is None:
            if not _SED_PRINT_SCRIPT_RE.match(token):
                return False
            script = token
            continue
        # Later operands are files sed READS. They are not inspected: a
        # read-only sed that merely NAMES something is still read-only, the
        # same restraint the DESIGN RULE states for every other word.
    return quiet and script is not None


#: A leading ``NAME=value`` on a segment is a shell assignment, not the
#: command: `FOO=bar python x` runs python, and the verb tests must agree
#: with the shell about that.
_ASSIGN_PREFIX_RE = re.compile(r"^[a-z_][a-z0-9_]*=")

#: Command substitution in the three forms that matter here. The substituted
#: command is text this gate was never handed, so nothing can be concluded
#: about it - and "cannot be concluded" is deny, per the failure policy.
_CMD_SUBST_RE = re.compile(r"\$\(|`|<\(")


def _segment_word_is_read_only(seg: dict) -> bool:
    """Does ONE segment's command WORD clear the read-only allowlist?

    Parts 1, 3 and 4 of the DESIGN RULE's membership test - the allowlisted
    word (with ``sed`` and ``find`` admitted only in their proven-read-only
    forms), no command substitution, no leading assignment. Part 2, the
    redirect test, is deliberately NOT here: a redirect is about WHERE the
    output lands, which each caller judges against its own protected set,
    while this answers only "is this word incapable of writing anything".

    ONE BODY, THREE CALLERS, because a second copy of an allowlist is a second
    thing to forget to update: ``shell_is_read_only`` asks it of every segment
    (adding the redirect test) to decide whether rule 2 can be skipped;
    ``_shell_hits`` in its CLOSED mode asks it of the segment that names keel's
    user-global directory or an installed kernel, where the redirect test
    already ran against that name; and ``_shell_hits`` in its OPEN mode - the
    policy lock, since T513 - asks it to WITHDRAW a refusal the mutating-verb
    list would otherwise make on an argument rather than a command word. The
    third caller consumes the same answer as the other two and adds nothing:
    everything this predicate declines to certify stays refused there.

    A segment with no tokens names no command and clears - it is a stray
    separator, not an invocation. Every other unproven shape answers False,
    the same direction the DESIGN RULE states.
    """
    tokens = seg["text"]
    if not tokens:
        return True  # a stray separator names no command at all
    if _ASSIGN_PREFIX_RE.match(tokens[0]):
        return False  # a leading assignment can act while naming nothing
    if _CMD_SUBST_RE.search(" ".join(tokens)):
        return False  # $(...), `...`, <(...): text this gate never sees
    word = tokens[0]
    if word == "sed":
        return sed_is_print_only(tokens)  # anything but a bare print keeps its gate
    if word == "find":
        return not any(  # -delete / -exec / -ok / -fprint / -fls
            token.startswith(prefix)
            for token in tokens[1:]
            for prefix in _FIND_WRITE_FLAG_PREFIXES
        )
    return word in _READ_ONLY_COMMANDS


def shell_is_read_only(cmd: str) -> bool:
    """Apply the DESIGN RULE above: does EVERY segment name a safe command?

    The caller asks this to decide whether rule 2 can be skipped
    altogether, so every unresolved case - an empty command, an over-long
    one, a parse failure, any exception - answers False, the same as an
    unrecognised or unlisted command word already would. There is no
    branch here that answers True on a failure.
    """
    if not cmd.strip():
        return False  # an exec event with no command text names nothing safe
    if len(cmd) > _MAX_CMD:
        return False  # fail safe: too big to parse
    try:
        body, heredoc_ok = strip_heredocs(cmd)
        segs, scan_ok = scan_segments(body)
        if not (heredoc_ok and scan_ok) or not segs:
            return False  # fail safe
        for seg in segs:
            for op, target in seg["redirs"]:
                if redirect_writes_file(op, target):
                    return False  # a redirect that lands on a real file
            if not _segment_word_is_read_only(seg):
                return False
    except Exception:  # noqa: BLE001 - fail safe, never fail open
        return False
    return True


# ------------------------------------------------------------------- messages


def plan_message(event: KeelEvent) -> str:
    """The block message for a missing or stale ledger."""
    target = (
        session_plan_relpath(event.sess8) if event.sess8 else "/".join(PLANS_RELPATH)
    )
    return (
        f"PLAN GATE ({event.tool_name or event.kind}): no fresh plan for THIS "
        f"session. Write your plan to {target} "
        "('- [ ]' tasks with acceptance criteria and routes, per "
        ".keel/keel-policy.md), then retry. Each session has its own plan "
        "file. (Guardrail: plan-before-write.)"
    )


#: The next step for a ledger that does not meet the contract. Same shape as
#: every other next step: name the door, and it is a door the model can open
#: itself - this refusal needs no user, only a better ledger.
NEXT_STEP_PLAN_CONTRACT = (
    "NEXT STEP: fix the ledger and write it again - every task line carries a "
    "'Tn' identifier straight after its checkbox, a 'Route:' and an 'Accept:' "
    "somewhere in its block, and no banned placeholder vocabulary (TBD, etc., "
    "handle appropriately, as needed, similar to the above). Replace the "
    "placeholder with the decision it hides; the full contract is "
    "templates/keel-plan-contract.md."
)


def plan_contract_message(event: KeelEvent, target: str, findings: Sequence[Any]) -> str:
    """The block message for a ledger write that violates the contract.

    Every finding is named - kind, line and detail - because a refusal the
    author has to guess at costs more than the write it prevented. The
    findings are data from ``keel_plans``: printed, never interpolated into
    anything that runs (R5). ``finding.line`` is trusted as-is: for a
    ``missing_route``/``missing_accept`` finding this is the OFFENDING line
    when ``keel_plans`` found a near miss (wrong case, or the field's word
    separated from its colon) and only the task's opening checkbox line for
    a genuine absence - this function draws no distinction between the two
    itself, and needs none, because the line and the wording already differ
    upstream (T203).
    """
    head = (
        f"PLAN CONTRACT ({event.tool_name or event.kind} -> {target}): this "
        f"ledger does not meet the machine-checkable plan contract, so the "
        f"write is refused rather than filed. "
        f"{len(findings)} finding(s):"
    )
    lines = [
        f"  - {finding.rule} (line {finding.line}): {finding.detail}" for finding in findings
    ]
    return _joined(head, *lines, NEXT_STEP_PLAN_CONTRACT, "(Guardrail: plan-contract.)")


#: The next step for a shell command that would rewrite a session ledger. The
#: door is a different TOOL rather than a different permission: the model can
#: open it itself, and doing so is what makes the contract checkable at all.
NEXT_STEP_PLAN_CONTRACT_SHELL = (
    "NEXT STEP: write the ledger with the Write or Edit tool instead - their "
    "payload carries the content, so keel can assert the plan contract against "
    "it before the file changes. A shell command leaves nothing to check."
)


def shell_plan_contract_message(event: KeelEvent) -> str:
    """The block message for a shell command that would rewrite a ledger.

    No path is echoed back: the command names its own target and the gate did
    not resolve one, so the message names the SHAPE it recognised (the ledger
    glob) and lets the next step carry the way forward.
    """
    head = (
        f"PLAN CONTRACT ({event.tool_name or event.kind}): this "
        "command appears to modify a session ledger (.keel/plans/keel-plan-*.md) "
        "from the shell. The content such a command would leave behind does not "
        "exist until it has run, so keel cannot check it against the plan "
        "contract - and what cannot be verified is refused, not filed."
    )
    return _joined(head, NEXT_STEP_PLAN_CONTRACT_SHELL, "(Guardrail: plan-contract.)")


def plan_contract_unreadable_message(event: KeelEvent, detail: str) -> str:
    """The block message for a contract checker that could not be loaded."""
    return _joined(
        f"PLAN CONTRACT ({event.tool_name or event.kind}): keel could not load "
        f"the contract checker scripts/keel_plans.py ({detail}), so it cannot "
        "tell whether this ledger meets the contract. What cannot be verified "
        "is refused.",
        "NEXT STEP: restore scripts/keel_plans.py (it ships with keel), or set "
        "KEEL_GATE=off deliberately for this session. (Guardrail: "
        "plan-contract.)",
    )


#: The next step for a ledger keel could not READ. The door is neither a
#: permission nor a better ledger: something else holds the file, and the model
#: can find that out itself. The last sentence is load-bearing - this refusal
#: says nothing against the payload, which may well be perfect.
NEXT_STEP_LEDGER_UNREADABLE = (
    "NEXT STEP: find what holds the file - an editor, a scanner, another agent, "
    "a lock left behind by a killed process - release it and write again; or "
    "read the ledger yourself and meet the same fault keel met. If the path is "
    "not a readable file at all, that is the repair. This needs no user, and it "
    "is not a judgement on the content offered."
)

#: The next step for a substitution aimed at a ledger that is not there. A
#: DIFFERENT door from the one above, which is why the two are separate
#: constants: nothing holds this file and nothing needs releasing - the payload
#: is simply the wrong shape for a file that has to be created first.
NEXT_STEP_LEDGER_ABSENT_EDIT = (
    "NEXT STEP: write the ledger with a Write payload carrying its whole "
    "content. An edit describes a change to text that already exists, so it has "
    "nothing to apply to here and would have failed after this gate as surely "
    "as at it."
)


def plan_contract_unestablished_message(
    event: KeelEvent, target: str, detail: str, next_step: str
) -> str:
    """The block message for a ledger text keel could not ESTABLISH.

    Deliberately distinct from ``plan_contract_unreadable_message``, which is
    about the CHECKER: there the tool is missing, here the subject is. Their
    repairs are unrelated, and one message serving both would send an author to
    reinstall keel over a locked file.

    Two faults share this shape - a read that failed, and a substitution with no
    file to apply to - because the refusal is one refusal: keel does not know
    what the ledger would say. They do NOT share a next step, so that is a
    parameter; ``detail`` names the fault as keel met it. The middle sentence is
    the reasoning, said where the reader is rather than only in the ledger: the
    tempting shortcut of reading unknown as empty is the defect this replaces
    (T201).
    """
    return _joined(
        f"PLAN CONTRACT ({event.tool_name or event.kind} -> {target}): keel "
        f"could not establish the text this write would leave in the ledger "
        f"({detail}), so it cannot tell whether the result meets the plan "
        f"contract. Text keel could not establish is NOT empty text: reading it "
        f"as empty would check nothing and allow everything, so what cannot be "
        f"verified is refused.",
        next_step,
        "(Guardrail: plan-contract.)",
    )


#: The next step for each kind of locked target. A refusal that names no way
#: forward reads as a dead end and gets the guard uninstalled; every one of
#: these names the exact door, and every door needs the user.
NEXT_STEP_ARMING = (
    "NEXT STEP: policy changes go through the refit skill (/keel:refit), which "
    "puts the user's hand on this file."
)
NEXT_STEP_KERNEL = (
    "NEXT STEP: kernel and settings changes need a session the USER launched "
    "with KEEL_OVERRIDE=on. Ask for one; there is no in-session unlock."
)
NEXT_STEP_MANIFEST_AVAILABLE = (
    "NEXT STEP: a version-only manifest write can be demoted to a prompt - the "
    "user adds a '## Policy lock' section to .keel/keel-policy.md listing "
    "'release-version-bump' under 'relax:'. Everything wider stays locked."
)
NEXT_STEP_MANIFEST_NOT_VERSION_ONLY = (
    "NEXT STEP: 'release-version-bump' is enabled here, but this write changes "
    "more than the manifest's \"version\" value, so the relaxation does not "
    "apply. Split the release bump out, or ask the user."
)
NEXT_STEP_TIGHTENED = (
    "NEXT STEP: this path was added to the lock by the '## Policy lock' section "
    "of .keel/keel-policy.md. Only the user can take it back out."
)
NEXT_STEP_UNVERIFIABLE = (
    "NEXT STEP: re-issue the write with a plain project-relative path. A path "
    "keel cannot resolve is a malformed tool call rather than a permission "
    "problem, so there is no door to knock on and nothing to override."
)


def next_step_for(cwd: Path, raw_path: str, section: LockSection) -> str:
    """The one line that turns a refusal into a redirect, chosen by target."""
    target_norm = norm(cwd, raw_path)
    if target_norm == norm(cwd, os.path.join(*POLICY_RELPATH)):
        return NEXT_STEP_ARMING
    if is_anchor(cwd, target_norm):
        return NEXT_STEP_KERNEL
    if target_norm == norm(cwd, os.path.join(*MANIFEST_RELPATH)):
        if section.relaxes("release-version-bump"):
            return NEXT_STEP_MANIFEST_NOT_VERSION_ONLY
        return NEXT_STEP_MANIFEST_AVAILABLE
    if is_protected(cwd, target_norm):
        return NEXT_STEP_KERNEL
    return NEXT_STEP_TIGHTENED


def config_error_line(section: LockSection) -> str:
    """The visible half of "fail closed, visibly" - or nothing to say."""
    if section.valid:
        return ""
    return (
        "CONFIG: the '## Policy lock' section of .keel/keel-policy.md is being "
        "ignored and the full default lock applies - " + "; ".join(section.errors)
    )


def _joined(*lines: str) -> str:
    """One message from its lines, dropping the ones that had nothing to say."""
    return "\n".join(line for line in lines if line)


def policy_lock_message(
    event: KeelEvent, target: str, cwd: Path | None = None, section: LockSection | None = None
) -> str:
    """The block message for a policy-locked target, naming the next step."""
    section = LockSection() if section is None else section
    head = (
        f"POLICY LOCK ({event.tool_name or event.kind} -> {target}): "
        ".keel/keel-policy.md, the hooks/ and .claude-plugin/ directories and "
        "the settings files may only be changed when the USER sets "
        "KEEL_OVERRIDE=on. Ask the user; do not work around this."
    )
    step = next_step_for(event.cwd if cwd is None else cwd, target, section)
    return _joined(head, step, config_error_line(section))


def scrub(value: str, limit: int = 120) -> str:
    """A path made safe to echo back: unprintable characters become ``?``.

    The unverifiable-target refusal is the one place keel repeats a path it
    could NOT resolve, so the value may carry anything - a NUL byte, a control
    sequence, a kilobyte of noise. It is rendered for a human, never trusted,
    and never at length.
    """
    cleaned = "".join(char if char.isprintable() else "?" for char in value)
    return cleaned if len(cleaned) <= limit else cleaned[:limit] + "..."


def unverifiable_target_message(event: KeelEvent, target: str) -> str:
    """The block message for a target that could not be normalised at all."""
    head = (
        f"UNVERIFIABLE TARGET ({event.tool_name or event.kind} -> "
        f"{scrub(target)}): this path could not be verified against the policy "
        "lock, because keel could not resolve it to a location at all - so it "
        "cannot tell whether the write lands on a locked file. What cannot be "
        "resolved is blocked."
    )
    return _joined(head, NEXT_STEP_UNVERIFIABLE)


def policy_lock_ask_message(event: KeelEvent, target: str, relaxation: str) -> str:
    """The ASK message: a named relaxation applies, so the USER decides."""
    _, what = RELAXATIONS[relaxation]
    return (
        f"POLICY LOCK RELAXED ({event.tool_name or event.kind} -> {target}): "
        f"this project enables the '{relaxation}' relaxation, which covers "
        f"{what}, so this write is your decision rather than a refusal. "
        "Approve it only if a release is what you meant."
    )


def shell_next_step(command: str) -> str:
    """The next step for a command, read from what the command names.

    A shell write is never a relaxation candidate - the relaxation compares a
    write payload against a file, and a command carries neither - so the
    manifest is not a case here: every road leads to the user.
    """
    return NEXT_STEP_ARMING if "keel-policy.md" in command else NEXT_STEP_KERNEL


def shell_policy_lock_message(event: KeelEvent, section: LockSection | None = None) -> str:
    """The block message for a shell command that hits the policy lock."""
    section = LockSection() if section is None else section
    head = (
        f"POLICY LOCK ({event.tool_name or event.kind}): this command appears "
        "to modify policy-locked files or override variables "
        "(keel-policy.md / hooks/ / .claude-plugin/ / settings.json / KEEL_* "
        "env). Only the user may change them (KEEL_OVERRIDE=on). Do not work "
        "around this; ask the user."
    )
    step = shell_next_step((event.command or "").casefold())
    return _joined(head, step, config_error_line(section))


# --------------------------------------------------- which projects govern one event

#: How many distinct path-like tokens of ONE command are resolved upward. A
#: command naming more paths than this is a script rather than a write, and the
#: cost of resolution stays bounded instead of growing with the command's
#: length. The same fail-safe the shell scanner uses applies to what falls off
#: the end: the session's own project still judges the whole command.
COMMAND_TARGET_CANDIDATES = 24

#: A bare Windows drive prefix, so ``C:build`` counts as a path-like token even
#: though it carries no separator.
_DRIVE_PREFIX_RE = re.compile(r"^[a-z]:", re.IGNORECASE)

#: Strictness, for combining one verdict per governing project. Ask and deny
#: are both blocking, and a deny outranks an ask because it is the one no prompt
#: can carry. READ THROUGH ``_strictness``, never subscripted: a decision kind
#: this table has not heard of must not raise inside the gate - that is the class
#: of fault that froze the harness on 2026-08-19 - so it ranks as the strictest
#: instead. Every member of ``keel_events.DECISIONS`` is here today.
_STRICTNESS: Mapping[str, int] = {"allow": 0, "ask": 1, "deny": 2}


def _strictness(verdict: KeelVerdict) -> int:
    """How strict one verdict is, with an unknown decision ranked strictest."""
    return _STRICTNESS.get(verdict.decision, max(_STRICTNESS.values()))

#: What ``evaluate`` says when no project governs the event at all. NO WIDENING,
#: said out loud: this is the answer for a target genuinely outside every armed
#: project, and it names both halves of the question that was asked.
UNARMED_REASON = (
    "unarmed: no .keel/keel-policy.md at or above this session's directory, and "
    "none at or above any target this event names"
)


def command_target_dirs(command: str, cwd: Path) -> tuple[Path, ...]:
    """The paths a command's path-like tokens name, resolved against ``cwd``.

    WHY A COMMAND NEEDS THIS AT ALL: a write declares its target and a command
    does not, so the project a command would act on has to be read out of its
    text. The lock's own shell heuristic reasons about TOKENS rather than paths
    and is deliberately cwd-independent (``shell_hits_policy_lock`` takes no
    cwd); what it cannot answer is WHICH project's lock is being applied, and
    that is the question this exists to answer.

    ONLY A TOKEN THAT LOOKS LIKE A PATH COUNTS - it carries a separator or a
    drive prefix. A bare word (``rm``, ``-rf``, ``build``) names no project, and
    inferring one from it would pull in directories the command never mentioned.
    Results are deduplicated and capped at ``COMMAND_TARGET_CANDIDATES``, and
    nothing here raises: an unresolvable token is simply not a project, which is
    safe because the lock still applies the FULL default set to every project
    this does find, and the session's own project still judges the command
    whatever this returns.
    """
    if not command:
        return ()
    found: list[Path] = []
    seen: set[str] = set()
    for token in _TOKEN_SPLIT_RE.split(command[:_MAX_CMD]):
        piece = token.strip().strip("'\"")
        if not piece or piece.startswith("-"):
            continue
        if "/" not in piece and "\\" not in piece and not _DRIVE_PREFIX_RE.match(piece):
            continue
        absolute = _resolved(cwd, piece)
        if not absolute:
            continue
        key = absolute.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(Path(absolute))
        if len(found) >= COMMAND_TARGET_CANDIDATES:
            break
    return tuple(found)


#: The next step for a path keel cannot attribute to any project. It names a
#: door, as every refusal here must - and the door is NOT the override, because
#: this is not a policy refusal: keel does not know whose policy applies.
NEXT_STEP_UNRESOLVED_PROJECT = (
    "NEXT STEP: name the target by a path keel can attribute - one whose "
    "project's .keel/keel-policy.md is within reach of it - or ask the user "
    "which project this path belongs to. There is nothing to override here and "
    "no permission to raise: keel is not refusing on policy grounds, it cannot "
    "tell WHOSE policy applies."
)


def unresolved_project_message(event: KeelEvent, target: str) -> str:
    """The block message for a path whose project the walk could not reach."""
    return _joined(
        f"PROJECT UNRESOLVED ({event.tool_name or event.kind} -> {scrub(target)}): "
        f"keel climbed {PROJECT_WALK_MAX_LEVELS} parent directories above this "
        f"path without reaching either a project's arming file or the top of "
        f"the walk, so it cannot say which project's rules apply. An arming "
        f"file it never reached could refuse this - and what keel cannot vouch "
        f"for it does not permit, which is the same rule an unresolvable path "
        f"already gets (UNVERIFIABLE IS DENY).",
        NEXT_STEP_UNRESOLVED_PROJECT,
        "(Guardrail: policy-lock.)",
    )


def announce_ungoverned_targets(event: KeelEvent, outside: Sequence[str]) -> None:
    """One stderr line for payload entries NO armed project governs.

    Criterion 4 said out loud rather than in silence. These entries are allowed
    - they are provably outside every armed project, which is the unarmed answer
    and the one this task must not change - but they reach that answer inside an
    event some OTHER project is judging, so a reader who saw only the verdict
    would not know they had been decided at all. That is the shape of defect
    this whole task is about, so it is announced.

    EACH ENTRY IS RELATIVISED THEN REDACTED before it is printed (T187, a
    security finding at 82%). ``outside`` is, by definition, outside every armed
    project - and just as often outside ``event.cwd`` too - so a raw payload
    entry is normally the ABSOLUTE path the harness handed over, home directory
    and account name included. ``relativise`` alone is not enough: exactly as
    its own docstring warns, ``os.path.relpath`` can turn a path under this
    user's home into ``../../Users/<name>/x``, a spelling from which the
    literal home prefix is gone but the username is not. ``redact`` is what
    closes that shape (its home-SHAPE step is anchored on the word ``Users``/
    ``home`` rather than on this machine's own prefix), and it is the same pair
    every OTHER stderr notice and the audit line for this same bucket already
    apply - this one now matches them instead of being the one place that did
    not.

    Convention 7: stderr is where this gate says everything that is not a
    verdict. A notice may never fail the gate - so a value neither helper can
    make safe is not printed at all; the whole line is skipped rather than
    risking the leak this exists to close.
    """
    if not outside:
        return
    try:
        shown = ", ".join(
            scrub(redact(relativise(event.cwd, entry)), 80) for entry in outside[:3]
        )
        more = f" (+{len(outside) - 3} more)" if len(outside) > 3 else ""
        print(
            f"keel: NO ARMED PROJECT GOVERNS {len(outside)} target(s) of this "
            f"write - {shown}{more}: no .keel/keel-policy.md at or above them, so "
            f"keel is unarmed for those and permits them, while the rest of this "
            f"event is still judged by the project(s) that own it.",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 - a notice may never fail the gate
        return


def announce_unresolved_targets(event: KeelEvent, targets: Sequence[str]) -> None:
    """One stderr line AND one audit line for targets keel could not attribute,
    permitted only because nothing that could refuse them did (T189, narrowing
    T187's accept 1 for pre_write - see .keel/decisions/2026-08-20-the-ladder-
    binds-what-keel-cannot-attribute.md, the yardstick).

    WHAT "NOTHING THAT COULD REFUSE THEM DID" MEANS DIFFERS BY KIND, and the
    printed sentence says so rather than repeating one claim for both, because
    THE NOTICE MUST STILL BE TRUE WHENEVER IT PRINTS (T189, accept 4). For
    pre_exec it is still T187's original fact: nothing governing this EVENT has
    reached the enforcing tier, because a command is atomic and every
    governing project already judges the whole of it - unchanged, and still
    true. For pre_write the old sentence would be FALSE to print after the
    narrowing: a different governing project may well enforce elsewhere in the
    same payload. What is actually true there is narrower and named as such -
    no ENFORCING project's root could be shown to be an ancestor of THIS
    target, and the session's own project does not enforce either.

    BELOW THE ENFORCING TIER THE LOCK ITSELF NEVER RUNS - ``_project_verdict``'s
    own tier gate returns allow before the lock is even consulted - so denying
    a path keel merely could not attribute, while permitting one it CAN
    attribute to a protected file, was a single arbitrary trapdoor rather than
    a safety margin. At the enforcing tier and above (or, for pre_write, at an
    ancestor project's enforcement, or the session's own) this still refuses
    (``unresolved_project_message``, via ``evaluate``'s deny); this function is
    reached only when it does not, so it never fires alongside that deny.

    ZERO IS NOT SILENCE (accept 2): this is never called with an empty
    ``targets``, so its firing - on stderr AND in the audit log as
    ``unresolved_project_allowed`` - is itself the fact that something was
    unattributable here, distinct from a project where nothing was. The
    ordinary ``gate_block`` write only ever records a DENY, so this bucket
    needed its own event kind rather than borrowing that one silently.

    Each target is relativised then redacted before either line is built, the
    same pair ``announce_ungoverned_targets`` now applies for the same reason
    (T187, accept 3); the audit write additionally passes through
    ``keel_events``'s own chokepoint, which redacts every field again on the
    way to disk (idempotent - see ``_append_jsonl``), so the field is safe
    twice over rather than relying on either alone. Auditing may never fail the
    gate; a failure to audit is reported, not swallowed - the same discipline
    ``_audit_lock_event`` keeps for the two lock-adjacent event kinds.
    """
    if not targets:
        return
    safe = [scrub(redact(relativise(event.cwd, t)), 80) for t in targets]
    try:
        shown = ", ".join(safe[:3])
        more = f" (+{len(targets) - 3} more)" if len(targets) > 3 else ""
        if event.kind == "pre_write":
            situation = (
                "keel could not attribute these to any project; no ENFORCING "
                "governing project's root is an ancestor of them, and the "
                "session's own project does not enforce either, so nothing "
                "here blocks them - even if a different governing project "
                "enforces elsewhere in this same write, it has no structural "
                "claim on these targets"
            )
        else:
            situation = (
                f"keel could not attribute these to any project, and nothing "
                f"governing this event has reached tier {ENFORCING_TIER}, so "
                f"nothing here would have blocked them anyway"
            )
        print(
            f"keel: PROJECT UNRESOLVED FOR {len(targets)} target(s), PERMITTED "
            f"BELOW THE ENFORCING TIER - {shown}{more}: {situation}. At tier "
            f"{ENFORCING_TIER} and above this refuses instead.",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 - a notice may never fail the gate
        pass
    try:
        append_audit(
            event.cwd,
            {
                "event": "unresolved_project_allowed",
                "gate": "unresolved_project",
                "kind": event.kind,
                "tool": event.tool_name,
                "session": event.session_id,
                "detail": {"targets": safe},
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: unresolved_project_allowed audit failed: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )


@dataclass(frozen=True)
class Governance:
    """Who judges this event - and the PROOF that no target fell between them.

    THE INVARIANT, and it is checked at construction rather than trusted:
    every entry of ``payload`` (which is ``event.file_paths`` verbatim) lands in
    exactly one of four buckets, and the four are disjoint and cover it:

    * ``covered``    - judged by at least one project below. An entry keel could
      not normalise is put here too, deliberately: it is handed to EVERY project
      so that ``_evaluate_write``'s unverifiable refusal sees the whole payload
      instead of one project's filtered share of it. That filtering is how a
      malformed target used to disappear out of a governed event.
    * ``outside``    - provably outside every armed project: a COMPLETE
      ``PROJECT_ABSENT`` answer, and only reachable when the session's own
      directory is unarmed too (otherwise its project judges everything).
      Allowed, and announced by ``announce_ungoverned_targets``.
    * ``unresolved`` - the walk could not answer (``PROJECT_UNKNOWN``), for a
      pre_write TARGET. REFUSES the event when an ENFORCING project's root
      (among ``projects``) is an ANCESTOR of it (``_enforcing_ancestor``);
      short of that, the SESSION's own project's tier decides
      (``session_root``); short of THAT, ``evaluate`` announces and audits it
      instead of denying. T189, narrowing T187's retry on re-review
      (.keel/decisions/2026-08-20-the-ladder-binds-what-keel-cannot-attribute.md):
      the retry asked "is ANY governing project enforcing", which missed that
      a foreign project owning a DIFFERENT target in the same payload has no
      structural claim on THIS one (security review, 80%). This bucket does
      not decide which; it only guarantees the entry is never silently
      dropped. This is the bucket finding 1 of T178's review existed for:
      before it, exhaustion returned the same None as absence and read as
      "nothing governs this", which is the pre-T178 fail-open one directory
      below the ceiling.
    * ``ungated``    - no project governs this event AT ALL, so nothing judges
      anything and keel is unarmed here. Non-empty only when ``projects`` is
      empty, which the check below enforces.

    So the class the review named - A TARGET THAT NOBODY JUDGES MUST NEVER READ
    AS PERMITTED - is not a test somewhere downstream. An entry is judged, or it
    refuses the event, or it is one of two named states in which keel is
    honestly unarmed and says so. There is no fifth way to be neither.

    ``unresolved_named`` carries the same failure for paths a COMMAND named,
    which are not payload entries and so are not part of the partition; they
    refuse the event through the same door - and, unlike ``unresolved``, this
    bucket keeps T187's rule exactly as it shipped: ANY governing project
    enforcing refuses, because a command is atomic and every governing
    project already judges the whole of it. The narrower ancestry test is a
    pre_write-only correction (T189); pre_exec never needed one.

    TWO FIELDS EXIST PURELY FOR T189's pre_write NARROWING, and carry no new
    resolution of their own - each is a value ``governance`` already computed
    while building the buckets above, exposed rather than recomputed.
    ``session_root`` is the SESSION's own resolved root (None when it does not
    resolve), named explicitly because ``projects[0]`` is the session's root
    ONLY when it resolves - a caller that assumed the position would silently
    read a foreign project's root as the session's own whenever it did not.
    ``unresolved_norms`` pairs 1:1 with ``unresolved`` (checked below) and
    carries each target's ALREADY-RESOLVED, casefolded absolute form, so the
    ancestry test in ``evaluate`` is a bare path-prefix comparison against a
    root already on hand - no second walk, no second call to
    ``os.path.realpath``.

    The check raises ``GateError``, which ``run`` turns into a fail-closed deny
    for an armed project: an accounting bug in this file must not become a
    permission either.
    """

    payload: tuple[str, ...] = ()
    projects: tuple[tuple[Path, tuple[tuple[str, str], ...]], ...] = ()
    session_root: Path | None = None
    covered: frozenset[str] = frozenset()
    outside: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()
    unresolved_norms: tuple[str, ...] = ()
    unresolved_named: tuple[str, ...] = ()
    ungated: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        entries = set(self.payload)
        buckets = (
            self.covered,
            frozenset(self.outside),
            frozenset(self.unresolved),
            frozenset(self.ungated),
        )
        union: set[str] = set().union(*buckets)
        if union != entries:
            raise GateError(
                f"governance accounts for {sorted(union)} but the payload is "
                f"{sorted(entries)}: every target must be judged, refused or "
                f"named unarmed"
            )
        if sum(len(bucket) for bucket in buckets) != len(union):
            raise GateError(
                f"governance puts a target in two buckets at once: {sorted(entries)}"
            )
        if self.ungated and self.projects:
            raise GateError("a target cannot be ungated while a project governs the event")
        if (self.covered or self.outside) and not self.projects:
            raise GateError("a target cannot be judged by no project at all")
        if len(self.unresolved_norms) != len(self.unresolved):
            raise GateError(
                f"governance recorded {len(self.unresolved_norms)} norm(s) for "
                f"{len(self.unresolved)} unresolved target(s): the ancestry test "
                f"needs one resolved form per target, paired 1:1"
            )

    @property
    def refuses(self) -> tuple[str, ...]:
        """Every path that refuses this event because keel could not attribute it."""
        return self.unresolved + self.unresolved_named


def governance(event: KeelEvent) -> Governance:
    """Who governs this event, what each project judges, and the accounting.

    THE ACCOUNTING IS WHY THIS RETURNS A TYPE rather than a list of projects. An
    earlier cut of T178 returned the projects alone and so had nowhere to put a
    target that belonged to none of them - which is how a malformed path
    disappeared out of a governed event and how an unattributable one read as
    unarmed. Both were review findings; both are answered by ``Governance``. See
    ``Governance`` for the invariant and ARMING at the top of this file for why
    there can be more than one project.

    THE TWO SOURCES OF GOVERNANCE, and both are needed:

    * THE SESSION'S OWN PROJECT judges EVERY target, exactly as
      ``policy_tier(event.cwd)`` made it judge every target before T178. Keeping
      it is what makes this change incapable of loosening anything: a write
      outside the project still needs the session's plan, and a target no
      project owns is still that project's business. It also CLIMBS, so a
      session started in a subdirectory of a project - which read as unarmed for
      the same reason the hole existed - is governed by the project above it.
    * EACH TARGET'S OWN PROJECT judges that target. This is the fix: a target
      inside an armed project is judged by that project's arming file, its lock
      and its ledger, whoever is writing it and from wherever.

    AN INSTALLATION IS NEVER ONE OF THOSE PROJECTS (T506, BL57). A tree the
    harness installed under its own plugin cache carries whatever ``.keel/``
    the package happened to ship - for keel, an arming file at tier 2 - and
    judging a target by the record that ARRIVED WITH AN INSTALL refused the
    adopter's first act under rules they never adopted, naming a ledger inside
    the plugin cache that they must not write. So a TARGET's own project is
    dropped when its root is an installed tree (``_not_an_installation``,
    ``is_installed_tree``, which says at length what it does and does not
    match). The target then belongs to no project - a state this function
    already has and already accounts for - and the session's own project judges
    it, as it judges every path no project owns.

    THE INSTALLATION'S OWN KERNEL IS STILL REFUSED, and by nobody in this list.
    What is dropped here is a JUDGE, not a protection: a write - or a mutating
    command - aimed at an installed tree's ``hooks/``, arming file or manifest
    is refused before this function is ever called, outside every project (THE
    INSTALLED-KERNEL RULE in ``evaluate``). Without that, this demotion would
    have let a session rewrite the gates it runs under, since the only project
    that used to refuse it was the install itself - and for a COMMAND that is
    doubly so, because a demoted tree contributes no entry to ``projects`` at
    all, so an unadopted session is answered by the ``if not projects`` allow
    with nothing having judged the command (T507).

    THE SESSION'S OWN WALK IS NOT FILTERED, deliberately. Nothing here loosens
    anything for the session's own work: this removes a JUDGE whose authority
    came from a file keel itself shipped, never a rule the session was already
    under. A session STANDING INSIDE an installed tree is a shape nobody has
    measured, and for a guard whose wrong answer is silence rather than an
    error the safe direction is to exclude less, so it is left governed.

    THE SESSION'S OWN WALK IS THE ONE PLACE ``PROJECT_UNKNOWN`` DOES NOT REFUSE,
    and the reason is that a refusal there would break tools keel was never
    armed in. A cwd too deep to walk falls back to reading the arming file AT
    ``event.cwd`` itself - which is precisely what shipped before T178, so it
    cannot be a regression, and it cannot be an escape either: every TARGET
    still gets the strict answer, and a target inside that same deep tree
    exhausts its own walk and refuses.

    A COMMAND IS NOT PARTITIONED, because a command is atomic: every governing
    project judges the whole of it, and its empty target tuple says so. The
    projects come from the paths its text names (``command_target_dirs``), and a
    named path the walk could not attribute refuses the event.

    THE PAYLOAD PATH IS REWRITTEN FOR A FOREIGN PROJECT, and only then. A
    relative payload path means "relative to the SESSION's directory", so
    handing it to a project the session is not standing in would name the wrong
    file; each foreign project receives the resolved absolute path instead,
    which every downstream join reproduces unchanged. A project that IS the
    session's directory receives the payload exactly as the tool spelled it, so
    every refusal message and audit line in the ordinary case is byte-identical
    to what it was before. An unresolvable path is never rewritten: the
    unverifiable refusal must name what the payload said.

    Never raises except the accounting check in ``Governance``. Resolution
    failure is a STATE, not an exception.
    """
    # EVERY COMPARISON BELOW IS BETWEEN RESOLVED SPELLINGS, and that is not
    # tidiness: a root arrives canonical from the walk while ``event.cwd``
    # arrives as the harness spelled it, which on Windows can be an 8.3 short
    # name for the very same directory (``C:\\Users\\SOMEUS~1`` against  [keel-leak: ignore - example of the Windows short-name shape this comment explains]
    # ``C:\\Users\\someuser``). Comparing those two as strings reads a  [keel-leak: ignore - second half of the same example]
    # session standing in its OWN project as standing outside it - which put a
    # cross-project note on an ordinary refusal until a fixture caught it.
    cache: dict[str, ProjectResolution] = {}
    here = _resolved(event.cwd, "").casefold()
    # Read ONCE per event for the same cost reason ``here`` is: it costs a
    # ``realpath``, no tool call outlives a change of home directory, and every
    # target would otherwise ask for it again. "" is a machine where keel
    # cannot name the cache, and it excludes nothing (``install_cache_root``).
    installs = install_cache_root()
    session = resolve_project(event.cwd, cache=cache)
    session_root = session.root
    if session.unknown:
        # See THE SESSION'S OWN WALK above: the pre-T178 reading, no wider.
        at_cwd = _resolved(event.cwd, "")
        session_root = (
            Path(at_cwd) if at_cwd and policy_present(Path(at_cwd)) else None
        )
    session_key = str(session_root).casefold() if session_root is not None else ""

    # (payload as spelled, absolute resolution, casefolded resolution, owner)
    entries: list[tuple[str, str, str, ProjectResolution]] = []
    if event.kind == "pre_write":
        for raw in event.file_paths:
            absolute = _resolved(event.cwd, raw)
            owner = (
                _resolve_resolved(Path(absolute), None, cache) if absolute else ABSENT_PROJECT
            )
            entries.append(
                (raw, absolute, absolute.casefold(), _not_an_installation(owner, installs))
            )

    roots: list[Path] = []
    keys: list[str] = []

    def _remember(root: Path | None) -> None:
        if root is None:
            return
        key = str(root).casefold()
        if key not in keys:
            keys.append(key)
            roots.append(root)

    _remember(session_root)
    for _raw, _absolute, _target_norm, owner in entries:
        _remember(owner.root)

    unresolved_named: list[str] = []
    if event.kind == "pre_exec":
        for named in command_target_dirs(event.command or "", event.cwd):
            answer = _not_an_installation(_resolve_resolved(named, None, cache), installs)
            if answer.unknown:
                unresolved_named.append(str(named))
            else:
                _remember(answer.root)

    out: list[tuple[Path, tuple[tuple[str, str], ...]]] = []
    covered: set[str] = set()
    for root, key in zip(roots, keys):
        if event.kind != "pre_write":
            out.append((root, ()))
            continue
        session_owns = bool(session_key) and key == session_key
        as_spelled = key == here
        judged: list[tuple[str, str]] = []
        for raw, absolute, target_norm, owner in entries:
            if owner.unknown:
                continue  # refused below; never handed to a project as a fact
            if not absolute:
                pass  # unverifiable: every project sees it (see ``Governance``)
            elif not (session_owns or (owner.found and str(owner.root).casefold() == key)):
                continue
            judged.append((raw if as_spelled or not absolute else absolute, target_norm))
            covered.add(raw)
        out.append((root, tuple(judged)))

    unresolved = tuple(raw for raw, _a, _n, owner in entries if owner.unknown)
    unresolved_norms = tuple(_n for _r, _a, _n, owner in entries if owner.unknown)
    accounted = covered | set(unresolved)
    residue = tuple(raw for raw, _a, _n, _o in entries if raw not in accounted)
    return Governance(
        payload=tuple(event.file_paths),
        projects=tuple(out),
        session_root=session_root,
        covered=frozenset(covered),
        outside=residue if out else (),
        unresolved=unresolved,
        unresolved_norms=unresolved_norms,
        unresolved_named=tuple(unresolved_named),
        ungated=() if out else residue,
    )


# ======================================================================
# THE GLOBAL RULE - KEEL'S OWN USER-GLOBAL FILES (T231)
#
# Every other rule in this file is a PROJECT's rule: it comes from an arming
# file, it reaches what that project owns, and where no arming file governs a
# target keel is honestly unarmed and says so. This one is not. It is keel's
# own rule about keel's own state, and it holds in every project, adopted or
# not - because the thing it guards is not in any project.
#
# WHAT IT GUARDS, and the scope is a ratified decision rather than a judgement
# made here: ``~/.claude/keel/`` and everything beneath it - ONE directory,
# named by
# ``.keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md`` clause
# 1, holding the fleet registry, the hook-error log and the compaction layer's
# files. Clause 3 of the same ruling is the other half of the scope and is
# just as binding: nothing OUTSIDE that directory is keel's, so the harness's
# own settings beside it are NOT guarded here. They are the owner's, and a
# guard that quietly annexed them would be keel deciding it owns more than the
# owner granted it.
#
# WHY IT HAS TO BE GLOBAL. keel deploys real files there now, and until this
# rule shipped a Write, an Edit or a shell redirect from ANY project - most of
# them projects keel is not even armed in - could rewrite the registry every
# other project reads, or truncate the fault log that is the only record of a
# failing hook, and nothing in this file would have refused it. The project
# the session happens to be standing in has no claim on that directory in
# either direction: it cannot permit the write, so its tier is not asked, and
# it cannot be harmed by the refusal, because nothing in its own tree moves.
#
# THE ASYMMETRY BETWEEN A WRITE AND A COMMAND IS THE ONE THIS FILE ALREADY
# DECLARES. A write DECLARES its target, so the write half resolves the path
# and compares it - exactly, through ``_under``, so ``~/.claude/keel-notes``
# beside the directory is not inside it. A command declares nothing, so the
# command half reasons about TOKENS through the same segment scan the policy
# lock uses (``_shell_hits``) - but in its CLOSED mode, which is the whole
# difference between this rule and the lock's.
#
# WHY CLOSED, decided on a measured failure rather than in the abstract. This
# rule first shipped in the lock's OPEN mode: a segment naming the directory
# was refused when it also showed a redirect or a mutating verb. An isolated
# review (2026-08-22, 85%) then wrote the registry straight through it with
# ``python3 -c "open(<path>, 'w').write(x)"`` - no redirect, no verb on any
# list, so the path matcher was never even consulted and the write passed with
# no deny, no bypass line and no audit row. A denylist of mutating words cannot
# be completed against interpreters, which this project has already recorded
# once (.keel/knowledge/a-shell-rewrite-is-atomic-on-disk-and-invisible-to-the-
# gate.md; T202 asks the same question for the ledger path). So the direction
# inverts, exactly as the read-only allowlist above inverted it for rule 2 -
# and it inverts over the WHOLE COMMAND, not over one segment:
# ONCE THIS DIRECTORY IS NAMED ANYWHERE IN A COMMAND, ONLY AN ALL-READ-ONLY
# COMMAND SURVIVES. The segment that names it, and every segment after it, must
# have its command word on that same closed allowlist
# (``_segment_word_is_read_only`` - ``cat``, ``grep``, ``head``, ``tail``,
# ``ls``, ``wc``, ``diff``, ``echo``, ``pwd``, plus a proven-print ``sed`` and a
# non-acting ``find``); anything else is refused. A ``cd`` into the directory
# taints the rest of the command as before, and so now does merely spelling it.
# One allowlist serves both rules; there is no second list to keep in step with
# this one.
#
# WHY OVER THE WHOLE COMMAND, measured rather than reasoned, like the rest of
# this rule. It first shipped judging each segment against its OWN text, and a
# second isolated review (2026-08-22, 85%) emptied the directory through it with
# ``find <dir> -type f | xargs rm -f`` and ``ls <dir> | xargs rm``: segment one
# is an allowlisted read, segment two spells nothing the matcher can see, and
# both ran with no deny, no bypass line and no audit row. A pipe HANDS the
# directory to the next segment without naming it twice, so nothing judged one
# segment at a time can be right about a command.
#
# WHAT THAT COSTS AND WHAT IT STILL MISSES, both stated rather than implied.
# COST: a READ through an unlisted word - ``python -c "print(open(<path>).
# read())"``, ``jq . <path>``, ``git show`` of it - is refused too, because no
# matcher can tell a read from a write inside an interpreter one-liner. SECOND
# COST, from the whole-command form: after the directory is named, an unlisted
# segment is refused even when it aims elsewhere - ``ls <dir> && rm -rf /tmp/x``
# is one refusal, and the way through is to run the two commands separately.
# Plain reads, which is what ``keel doctor`` and the board actually run, stay
# allowed through the allowlist - including down a pipe, as long as every
# segment is on it (``cat <dir>/keel-registry.json | grep x``) - and every
# refusal names the override. RESIDUAL, accepted rather than closed, and now
# exactly this and nothing beside it: this is a TEXT test, so a command that
# never spells the path ANYWHERE IN ITS TEXT - assembled by concatenation, read
# out of a variable or an environment lookup - names nothing to match and is not
# refused. Spelling it once is now enough to be caught; spelling it never is
# still enough to be missed. The write
# half, which is handed a real path, has no such gap; the command half is a
# heuristic here for the same reason it is one for the policy lock.
#
# THREE LIMITS, STATED SO THAT NOTHING IS WIDENED BY IMPLICATION:
# 1. THE OVERRIDE IS HONOURED EXACTLY AS THE LOCK HONOURS IT - the user's
#    switch carries the write, one ``gate_bypass`` line records it under this
#    rule's own name, and the write still faces the plan gate afterwards. The
#    switch is the user's law here as everywhere else in this file.
# 2. IT IS NOT REACHABLE FROM THE CRASH CARVE-OUT AND DOES NOT TOUCH IT.
#    ``crash_ledger_carve_out`` keeps ``.keel/plans/`` writable through a gate
#    that cannot evaluate; this rule runs inside ``evaluate``, returns a
#    verdict rather than raising, and names a directory no ``.keel/plans/``
#    can be inside. The freeze can still be written down.
# 3. THE KILL SWITCH STILL ANSWERS FIRST. ``KEEL_GATE=off`` stands the whole
#    gate down, this rule included, because a kill switch that a new rule
#    could outlive would be a narrower switch than the one the user was
#    promised.
# ======================================================================

#: KEEL'S USER-GLOBAL DIRECTORY AS A COMMAND NAMES IT: its path segments, on
#: either separator, matched as WHOLE PATH COMPONENTS the way ``_PROT_DIR_RE``
#: matches the locked directory names - so ``~/.claude/keel`` and
#: ``~/.claude/keel/keel-registry.json`` are hits while ``~/.claude/keel-notes``
#: beside the directory is not. A plain substring test would have swept the
#: sibling in, which is the same over-match ``_PROT_DIR_RE``'s own comment
#: refuses for ``hooks``.
#:
#: Derived from the ONE constant that names the directory (R15:
#: ``keel_faultlog.USER_GLOBAL_RELPATH``, the same segments ``user_global_dir``
#: joins), never typed, so the guard cannot drift from the thing it guards.
#: The backslash is built with ``chr(92)`` rather than typed - a class of
#: defect this repository has already paid for once. Case-insensitive by
#: default (convention 3).
_USER_GLOBAL_RE = re.compile(
    r"(?:^|[\s\"'=(:;/" + re.escape(chr(92)) + r"])"
    + ("[/" + re.escape(chr(92)) + "]").join(
        re.escape(segment) for segment in USER_GLOBAL_RELPATH
    )
    + r"(?=$|[\s\"')/" + re.escape(chr(92)) + r":;&|,])",
    re.IGNORECASE,
)

#: The name this refusal carries in the verdict, in the audit line, and in the
#: ``gate_bypass`` line when the override suspends it. Its OWN name, not
#: ``policy_lock``: a reader of the record must be able to count writes aimed
#: at keel's cross-project state apart from writes aimed at a project's own
#: locked files, because the two say completely different things about what a
#: session was doing.
USER_GLOBAL_GATE = "user_global"


def user_global_root() -> str:
    """keel's user-global directory, RESOLVED and casefolded, or "".

    Resolved rather than merely joined, because the targets it is compared
    against arrive from ``norm``, which resolves - and on Windows a home
    directory reached through an 8.3 short name is a different string for the
    same directory. Comparing an unresolved root against a resolved target
    reads a write into that directory as a write somewhere else, which is the
    fail-open shape this rule exists to close.

    NOT MEMOISED, deliberately, unlike ``_walk_home``: this is asked once or
    twice per event, the cost is one ``realpath`` beside the several ``norm``
    already spends per target, and a memo would freeze the answer for a
    process whose ``HOME`` changes under it - which is exactly what the suite
    does to keep its fixtures off the real directory.

    "" MEANS "keel HAS NO USER-GLOBAL DIRECTORY HERE", which is a fact and not
    a failure to paper over: ``user_global_dir`` returns None only when no home
    directory resolves at all, and on such a machine keel has written no
    user-global file for anyone to protect.
    """
    try:
        directory = user_global_dir()
        if directory is None:
            return ""
        return os.path.realpath(str(directory)).casefold()
    except (OSError, ValueError, RuntimeError):
        return ""


def is_user_global_target(target_norm: str) -> bool:
    """True when a RESOLVED, casefolded path is inside keel's user-global directory.

    Through ``_under``, so the directory itself and everything beneath it
    answer True while a sibling that merely shares its spelling - a
    ``keel-notes.txt`` next to the ``keel/`` directory - answers False. An
    empty ``target_norm`` is a path that would not resolve, and it is NOT this
    rule's business: ``_evaluate_write``'s UNVERIFIABLE IS DENY already refuses
    it for every project, and answering True here would refuse it under the
    wrong name.
    """
    if not target_norm:
        return False
    root = user_global_root()
    return bool(root) and _under(target_norm, root)


def names_user_global(text: str) -> bool:
    """True when command TEXT names keel's user-global directory.

    A TEXT TEST, the same shape and for the same reason as ``has_prot``: a
    command names paths as text, so any prefix in front of the directory's own
    segments still matches - ``~/.claude/keel/x``, ``$HOME/.claude/keel/x`` and
    a fully spelled absolute path all carry them, and no resolution against a
    working directory is needed or possible for the ``~`` and ``$HOME`` forms,
    which a shell expands only when the command actually runs.

    IT CAN OVER-MATCH, and that direction is chosen: a project holding its own
    ``.claude/keel/`` subdirectory would see a MUTATING command naming it
    refused under this rule. That is one refusal with a door in it (the
    override, named in the message) against a silent write into every
    project's shared state, and it is the same bargain ``has_prot`` already
    strikes for ``settings.json``. The write path, which has a real path to
    resolve, is exact and never guesses.
    """
    return bool(_USER_GLOBAL_RE.search(text))


def shell_hits_user_global(cmd: str) -> bool:
    """Apply the segment scan to a casefolded command, for keel's own state.

    IN THE CLOSED MODE (``closed=True``, argued in full at ``_shell_hits``):
    once this directory is named anywhere in the command, only an all-read-only
    command survives - the naming segment and every segment after it must have
    its word on the read-only allowlist. Per-segment was not enough twice over:
    the mutating-verb heuristic the policy lock uses cannot see inside
    ``python3 -c "..."``, and judging each segment on its own text let
    ``find <dir> -type f | xargs rm -f`` delete the directory unrecorded. The
    cost, and it is real, is that an UNLISTED word is refused once the
    directory has been named, even when it was only reading and even when it
    aims elsewhere - with the override named in the refusal.
    """
    return _shell_hits(cmd, names_user_global, closed=True)


def user_global_write(event: KeelEvent) -> str:
    """What this event would change inside keel's user-global directory, or "".

    ONE CLASSIFIER FOR THE ONE CONDITION, both kinds: the payload path that
    lands inside the directory (the first, when several do), or the command
    text whose scan hits it. The caller decides what to do about it and how to
    say it; this decides only whether it is so.

    NEVER RAISES, and the two failure directions are different on purpose. A
    fault while judging ONE TARGET refuses that target - UNVERIFIABLE IS DENY,
    the failure policy this file already declares, applied to the one question
    asked here. A fault before any target is judged leaves the rule standing
    down and says so on stderr: the only work done there is resolving keel's
    own directory, and a directory keel cannot locate holds no file of keel's
    to guard.
    """
    try:
        if event.kind == "pre_write":
            for raw in event.file_paths or ():
                try:
                    if is_user_global_target(norm(event.cwd, raw)):
                        return raw
                except Exception as exc:  # noqa: BLE001 - unverifiable is deny
                    print(
                        f"keel: this target could not be compared against keel's "
                        f"user-global directory, so it is refused: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    return raw
            return ""
        if event.kind == "pre_exec":
            command = (event.command or "").casefold()
            return event.command or "" if command and shell_hits_user_global(command) else ""
        return ""
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: keel's own user-global directory could not be located, so "
            f"the rule protecting it stood down for this event: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return ""


#: The door this refusal names, as every refusal in this file must. It is the
#: OVERRIDE, because unlike an unattributable path this IS a policy refusal -
#: keel knows exactly whose file it is - and the user is the one person whose
#: files these are.
NEXT_STEP_USER_GLOBAL = (
    "NEXT STEP: let keel maintain its own user-global state - the session "
    "hooks keep the fleet registry, and each user-global file has the one "
    "writer that owns it. If changing it by hand is genuinely what the user "
    "wants, that needs a session the USER launched with KEEL_OVERRIDE=on; "
    "there is no in-session unlock. Nothing in this project's own tree is "
    "affected by this refusal."
)


#: THE COMMAND HALF SAYS WHAT IT ACTUALLY DID, which is not the same sentence
#: the write half can say. A write declares its target, so "reading is not
#: refused" is exactly true there. A command is judged by the CLOSED allowlist
#: (THE GLOBAL RULE above), so a read keel cannot recognise is refused with the
#: writes - and a refusal that claimed otherwise would send the reader looking
#: for a write that is not in their command.
_READ_IS_ALLOWED_WRITE = "Reading those files is not refused; changing them is."
_READ_IS_ALLOWED_EXEC = (
    "Reading those files is not refused when the command is plainly a read - "
    "cat, grep, head, tail, ls, wc, diff and the rest of keel's read-only "
    "allowlist. This command is not one of those, and keel cannot tell a read "
    "from a write inside an interpreter one-liner or an unlisted tool, so it "
    "is refused either way."
)


def user_global_write_message(event: KeelEvent, target: str) -> str:
    """The block message for a write aimed at keel's own user-global state."""
    reads = _READ_IS_ALLOWED_EXEC if event.kind == "pre_exec" else _READ_IS_ALLOWED_WRITE
    return _joined(
        f"KEEL USER-GLOBAL STATE ({event.tool_name or event.kind} -> "
        f"{scrub(target)}): this names keel's own user-global directory, which "
        f"is machine-local state shared by every project on this machine - the "
        f"fleet registry, the hook-error log, the compaction layer's files. It "
        f"belongs to keel rather than to any repository (ratified 2026-08-21, "
        f".keel/decisions/2026-08-21-keel-owns-one-user-global-directory.md), "
        f"so no project's policy can permit a write to it and this refusal "
        f"stands whether or not keel is armed where this session started. "
        f"{reads}",
        NEXT_STEP_USER_GLOBAL,
        "(Guardrail: user-global.)",
    )


# ------------------------- THE INSTALLED-KERNEL RULE: an installation's own
# ------------------------- guard is still refused, though it governs nobody


#: The name this refusal carries in the verdict and on the record. Its OWN
#: name, like ``USER_GLOBAL_GATE`` and for the same reason: this is not a
#: project's policy lock speaking - no project decided it, and an install has
#: no policy authority left to speak with (``_not_an_installation``) - so a
#: reader who counted these as ``policy_lock`` would be counting writes at an
#: installed copy's kernel as writes at some project's own locked files.
INSTALL_KERNEL_GATE = "installed_kernel"

#: The kernel of an installed tree, as path segments relative to it: exactly
#: the project-relative locked set (``PROTECTED_FILES``, ``PROTECTED_DIRS``),
#: casefolded once here because the targets it is compared against arrive from
#: ``norm``. DERIVED, never re-typed (R15): the paths keel refuses to let a
#: project rewrite in itself are the paths it refuses to let a session rewrite
#: in an installation, and a second spelling would let the two drift.
#:
#: THE MANIFEST IS IN, and the relaxation that reaches it in a PROJECT
#: (``release-version-bump``) is not: a relaxation is read out of an arming
#: file, and the only arming file in sight here is the one the install shipped,
#: whose authority is precisely what T506 removed. Nothing an installed copy
#: carries may loosen what an installed copy is protected by.
_INSTALL_KERNEL_FILES: tuple[tuple[str, ...], ...] = tuple(
    tuple(segment.casefold() for segment in parts) for parts in PROTECTED_FILES
)
_INSTALL_KERNEL_DIRS: tuple[tuple[str, ...], ...] = tuple(
    tuple(segment.casefold() for segment in parts) for parts in PROTECTED_DIRS
)


def installed_kernel_root(target_norm: str, cache_root: str | None = None) -> str:
    """The installed tree whose KERNEL this resolved target names, or "".

    THE TWO POWERS AN INSTALLATION HAS, AND KEEL TAKES EXACTLY ONE AWAY. T506
    removed an installed copy's POLICY AUTHORITY: the ``.keel/`` a package
    happened to ship may not arm a project, demand a ledger inside the plugin
    cache or apply its lock to anyone (``is_installed_tree``,
    ``_not_an_installation``, BL57 - keel's own entry point refusing the person
    laying it). It did NOT, and must not, remove keel's refusal to let a
    session edit an installation's OWN KERNEL. That refusal is not the install
    governing anybody; it is the ANCHOR principle beside ``ANCHOR_DIRS`` -
    "a relaxation reaching any of them would let the guarded thing rewrite its
    own guard" - applied to the copy that is actually running. Dropping the
    installed tree out of ``governance``'s project list took both powers at
    once, which left a session in its own armed project, ledger fresh, free to
    rewrite ``<install>/hooks/keel_gate.py`` under the generic plan allow. This
    function is the half that had to come back, and it comes back WITHOUT the
    half that caused BL57: nothing here reads the install's arming file, its
    tier, its lock section or its ledger, so an installation still governs
    nothing and still demands nothing of an adopter.

    LOCATION DECIDES, EXACTLY AS IT DOES FOR THE DEMOTION. A target is an
    installation's kernel when it sits under the harness's plugin cache
    (``install_cache_root``) and its tail beneath SOME directory inside that
    cache is one of the locked relative paths. The candidate roots are the
    ancestors between the target and the cache, tried from the shallowest, so
    no assumption is made about how deeply the harness nests what it installs -
    ``<cache>/<marketplace>/<plugin>/<version>/hooks/x.py`` and
    ``<cache>/<plugin>/hooks/x.py`` are both hits, and neither depth is
    hard-coded. STRICTLY beneath, for ``is_installed_tree``'s reason: the cache
    directory itself is not a tree the harness installed.

    IT DOES NOT ASK WHETHER THE TREE LOOKS LIKE A PLUGIN, and that direction is
    chosen. Reading the candidate root for a manifest before refusing would put
    the answer back inside a file the copy ships - and would answer "not
    protected" for exactly the tree whose manifest a write is aiming at. Under
    the harness's own cache there is no legitimate session write to any of
    these paths: an installation is replaced by installing or updating the
    plugin, never edited in place. Refusing is therefore the safe direction and
    costs an adopter nothing.

    Returns the install root as a resolved, casefolded string - a value for the
    message and the record to name, and "" for "this is not one". Never raises;
    an empty ``target_norm`` (a path that would not resolve) is not this rule's
    business, exactly as ``is_user_global_target`` says of its own.
    """
    base = install_cache_root() if cache_root is None else cache_root
    if not target_norm or not base:
        return ""
    if target_norm == base or not _under(target_norm, base):
        return ""
    rest = target_norm[len(base) + len(os.sep) :]
    if os.altsep:
        rest = rest.replace(os.altsep.casefold(), os.sep.casefold())
    segments = [segment for segment in rest.split(os.sep.casefold()) if segment]
    for split in range(1, len(segments)):
        tail = tuple(segments[split:])
        hit = any(tail == parts for parts in _INSTALL_KERNEL_FILES) or any(
            tail[: len(parts)] == parts for parts in _INSTALL_KERNEL_DIRS
        )
        if hit:
            return base + os.sep + os.sep.join(segments[:split])
    return ""


#: HOW MANY INSTALLED DIRECTORIES ONE COMMAND MAY HAND TO ITS LATER TOKENS.
#: A command that names more trees inside the cache than this is a script
#: rather than an edit, and the cost of re-rooting stays bounded instead of
#: growing with the command's length. Small on purpose: the shape this exists
#: for is ``cd <install> && ...``, which names one.
_INSTALL_BASE_CANDIDATES = 8


class _UnresolvablePath(ValueError):
    """A token that IS a path and could not be resolved to compare.

    ITS OWN TYPE rather than a bare ``ValueError``, so the fault this rule
    raises FOR ITSELF is not read on the way out as a ``ValueError`` some
    library raised about data. IT CARRIES NO PATH TEXT: its message reaches
    stderr, and the very thing that makes a token unresolvable - an embedded
    NUL - is not something to echo into a terminal or a log.
    """


def _resolved_or_refuse(cwd: Path, path: str) -> str:
    """``_resolved``, with resolution FAILURE told apart from ABSENCE by raising.

    THE DEFECT THIS EXISTS FOR (silent-failure review of T507's first attempt,
    82%). ``_resolved`` answers "" for two states the installed-kernel rule
    must not confuse: it catches an embedded NUL and ``(OSError, ValueError)``
    ITSELF and returns "" rather than raising, and ``installed_kernel_root``
    then reads that "" exactly as it reads "no cache" and "not this location".
    So a token that could not be resolved AT ALL stood for "does not name the
    kernel", and ``names_installed_kernel``'s per-token ``except`` - the code
    whose whole job is to make an unverifiable token deny - was never reached
    for that input class. The contract was declared and not kept.

    WHY THE SAME SHAPE IS SAFE FOR ``is_user_global_target`` AND FATAL HERE,
    which is the reason this wrapper earns its existence rather than being
    ceremony. That rule's docstring says an unresolvable path is not its
    business because ``_evaluate_write``'s UNVERIFIABLE IS DENY refuses it
    afterwards, for every governing project - and that is true there. The
    installed-kernel rule is asked in PRECISELY THE STATE WHERE IT IS NOT:
    ``evaluate`` asks it one line before ``if not projects: return allow``,
    because an installed tree is demoted to ABSENT and a fresh adopter has no
    project of their own. For that session NO later per-project check runs at
    all. An unresolvable token here is answered by nobody unless it is
    answered here.

    ABSENCE NEVER REACHES THIS FUNCTION, which is what makes raising safe.
    "There is no path in this token" is settled by the caller BEFORE any
    resolution is attempted - a token carrying neither separator nor drive
    prefix is skipped, ``command_target_dirs``'s test for its reason - so
    every call that arrives here already holds a path. And ``_resolved`` has
    no third route to "": it returns "" from its NUL guard or from its
    ``except``, never from a successful ``os.path.realpath``, which answers a
    non-empty string for every input it does not raise on, INCLUDING paths
    that do not exist. "" here therefore means resolution FAILED, and nothing
    else.

    ``_resolved``'S OWN CONTRACT IS DELIBERATELY UNTOUCHED. It is shared with
    ``norm``, ``project_root_for``, ``is_user_global_target``'s callers and
    ``_evaluate_write``'s target resolution, and each of those reads "" as a
    value it handles ITSELF - ``_evaluate_write`` refuses it under
    ``gate='unverifiable_target'``, which is the right name there. Moving the
    raise into the shared helper would re-name every one of those refusals
    under this rule; a wrapper only this rule calls moves nothing.
    """
    resolved = _resolved(cwd, path)
    if not resolved:
        raise _UnresolvablePath(
            "a token naming a path could not be resolved against the filesystem"
        )
    return resolved


def names_installed_kernel(
    text: str,
    cwd: Path,
    cache_root: str,
    bases: list[str] | None = None,
    memo: dict[tuple[str, str], bool] | None = None,
) -> bool:
    """True when command TEXT names a path inside an installation's KERNEL.

    NOT A TEXT TEST, unlike ``has_prot`` and ``names_user_global``, and the
    difference is forced by what this rule is about. Those two match NAMES that
    are protected wherever they appear, because a project's ``hooks/`` is
    protected wherever the project is. An installation's kernel is protected by
    its LOCATION - the harness's plugin cache - exactly as ``is_installed_tree``
    decides everything else here, so a token has to be RESOLVED before this
    question can be asked of it at all. Matching ``hooks/`` as text would refuse
    every project's own ``hooks/`` under this rule's name, which is both the
    wrong name and a rule the adopter never agreed to.

    ONLY A TOKEN THAT LOOKS LIKE A PATH COUNTS - it carries a separator or a
    drive prefix - and that is ``command_target_dirs``'s test, for its reason: a
    bare word names no location, and inferring one from it would refuse commands
    that mention nothing.

    ``bases`` IS THE ``cd`` CASE, AND IT IS NOT OPTIONAL POLISH. The scan's own
    taint answers ``cd <install>/hooks && rm keel_gate.py``, because the chdir
    segment NAMES the kernel. It cannot answer ``cd <install> && sed -i x
    hooks/keel_gate.py``: the chdir names only the tree, and the token that
    names the kernel is RELATIVE to a directory the event's ``cwd`` is not. So
    every token that resolves INTO the cache is remembered here, and a later
    RELATIVE token is resolved against those too. The direction is chosen the
    way the rest of this rule is: it can over-match (a session whose own
    ``hooks/keel_gate.py`` is named in the same command as an installed tree is
    refused under this name rather than its own project's lock), and that is one
    refusal with the override in its message against a silent rewrite of the
    running gate.

    ``memo`` IS THE COST BOUND. ``_shell_hits`` asks this of every segment and of
    every redirect target, and the fail-safe asks it of the whole command again,
    so a token would otherwise be resolved several times per event; the cache is
    keyed on (base, token) because the same token answers differently under two
    bases. The command length is already bounded by ``_MAX_CMD``.

    UNVERIFIABLE IS DENY, PER TOKEN - AND THE CODE NOW DOES WHAT THAT SENTENCE
    SAYS. A fault while judging ONE token answers True for it and says so on
    stderr, rather than letting an unanswerable token stand for "names
    nothing", which is the exact shape of the silence this whole rule exists to
    end. One class of fault had to be MADE into a fault before the sentence was
    true: RESOLUTION FAILURE. ``_resolved`` catches an embedded NUL and
    ``(OSError, ValueError)`` itself and answers "", which
    ``installed_kernel_root`` reads exactly as it reads "not this location" -
    so for that class the ``except`` below was never reached and the token was
    silently read as not naming the kernel (silent-failure review of T507's
    first attempt, 82%). ``_resolved_or_refuse`` raises instead, and it argues
    there why the fix is not made in ``_resolved`` itself.

    FAILURE AND ABSENCE ARE DIFFERENT ANSWERS AND ARE NOW SPELLED DIFFERENTLY,
    which is the whole of the difficulty. ABSENCE is "there is no path in this
    token": it is settled ABOVE, by the separator-or-drive-prefix test, before
    anything is resolved, and it still clears - a rule that refused every bare
    word would refuse nearly every command anyone runs, and that would be a
    blanket denial wearing this rule's name. FAILURE is "there is a path here
    and it would not resolve": keel cannot establish that it is NOT the
    installation's kernel, and because this rule is asked in the
    no-governing-project state, nothing later ever will. So it is refused, out
    loud, with the override named in the message.
    """
    if not cache_root:
        return False
    for token in _TOKEN_SPLIT_RE.split(text):
        piece = token.strip().strip("'\"")
        if not piece or piece.startswith("-"):
            continue
        if "/" not in piece and "\\" not in piece and not _DRIVE_PREFIX_RE.match(piece):
            continue
        try:
            roots = [str(cwd)]
            if bases is not None and not os.path.isabs(piece):
                roots.extend(bases)
            for root in roots:
                key = (root, piece)
                if memo is not None and key in memo:
                    answer = memo[key]
                else:
                    answer = bool(
                        installed_kernel_root(
                            _resolved_or_refuse(Path(root), piece).casefold(),
                            cache_root,
                        )
                    )
                    if memo is not None:
                        memo[key] = answer
                if answer:
                    return True
            if bases is not None and len(bases) < _INSTALL_BASE_CANDIDATES:
                # THE SAME RESOLVER, and the ``absolute and`` guard the earlier
                # version carried here is gone with it: this call cannot answer
                # "" any more, and a guard against a value that can no longer
                # arrive is a guard that teaches a later reader the wrong thing
                # about what "" would have meant.
                absolute = _resolved_or_refuse(cwd, piece)
                if absolute not in bases and is_installed_tree(Path(absolute), cache_root):
                    bases.append(absolute)
        except Exception as exc:  # noqa: BLE001 - unverifiable is deny
            print(
                f"keel: this command token could not be compared against the "
                f"harness's plugin cache, so the command is refused: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return True
    return False


def shell_hits_installed_kernel(command: str, cwd: Path, cache_root: str) -> bool:
    """Apply the segment scan to a command, for an installation's own kernel.

    IN THE CLOSED MODE (``closed=True``, argued in full at ``_shell_hits``),
    the same mode ``shell_hits_user_global`` runs and for a stronger version of
    its reason. The open world - a denylist of mutating verbs - cannot answer
    ``python -c "open('<install>/hooks/keel_gate.py','w').write(x)"``, which is
    the measured bypass class this file has already recorded twice (BL11, and
    the two isolated reviews of 2026-08-22); refusing ``sed -i`` while allowing
    that one is a rule that looks present and never fires. The instruction this
    rule is written under is the file's own: what the heuristic cannot classify
    is refused, not allowed.

    WHAT THE CLOSED MODE COSTS HERE IS NEARLY NOTHING, which is why it is
    affordable here and not for the policy lock. Its cost is a READ through a
    word the allowlist does not name - ``git diff hooks/``, ``jq . hooks/x`` -
    and the reason the lock does not pay it is that this repository runs those
    against a DEVELOPMENT tree all day. Under the harness's plugin cache nobody
    develops anything: an installation is replaced by installing or updating the
    plugin, never edited in place, and plain reads (``cat``, ``grep``, ``head``,
    ``tail``, ``ls``, ``diff``, a proven-print ``sed``) stay allowed through the
    same allowlist. Every refusal names the override.

    THE COMMAND IS NOT CASEFOLDED FIRST, and that is the one place this caller
    differs from the other two. They match names by IGNORECASE regex, so a
    casefolded command costs them nothing; this one RESOLVES tokens against the
    filesystem, and on a case-sensitive system a casefolded path resolves to a
    directory that does not exist - which would answer "names nothing" for every
    installation on Linux and macOS. The verb tests then see the command as
    typed: an uppercase ``CAT`` is not on the read-only allowlist and is treated
    as mutating, which is the fail-safe direction in this mode.

    ``cache_root`` IS PASSED IN rather than looked up per token: it costs a
    ``realpath``, the caller already has it, and a value that changed under one
    command would judge two halves of it against two different caches.
    """
    bases: list[str] = []
    memo: dict[tuple[str, str], bool] = {}
    return _shell_hits(
        command,
        lambda text: names_installed_kernel(text, cwd, cache_root, bases, memo),
        closed=True,
    )


def installed_kernel_write(event: KeelEvent) -> str:
    """What this event would WRITE inside an installation's kernel, or "".

    THE WRITE HALF, and it stays its own function beside
    ``installed_kernel_command`` rather than merging with it, because the two
    are not the same KIND of answer. A write DECLARES its target, so this half
    is exact and never guesses; a command declares nothing, so that half is a
    heuristic over tokens. One function answering both would hide which of the
    two spoke, and the file already keeps ``user_global_write``'s two halves
    apart in the same way.

    WHAT THIS DOCSTRING USED TO SAY, corrected here because a stale
    justification is a false claim: it argued that the command side needed no
    rule of its own, since the policy lock's segment scan already refuses a
    mutating command naming ``hooks/``. That holds only WHERE A PROJECT IS
    ARMED to run the lock - and the case this whole task is about is a session
    with no governing project at all, where ``evaluate`` returns early at ``if
    not projects`` and no evaluator is ever reached. A mutating command at an
    installation's kernel therefore passed with no deny, no bypass line and no
    audit row (silent-failure review of T506, 85%). ``installed_kernel_command``
    is that hole closed; BL57 is respected there by asking whether the command
    MUTATES a kernel path, never by whether it merely names the cache.

    NEVER RAISES, with the two failure directions ``user_global_write`` argues:
    a fault while judging ONE target refuses that target (UNVERIFIABLE IS
    DENY), and a fault before any target is judged stands the rule down with a
    line on stderr - the only work done there is locating a directory, and a
    cache keel cannot locate holds no installed kernel to guard.

    A TARGET THAT WILL NOT RESOLVE IS NOT REFUSED HERE, AND THAT IS THE
    DIFFERENCE FROM THE COMMAND HALF, stated because the two halves otherwise
    look like they should behave alike. ``norm`` answers "" for such a target
    and this half reads that as "not the kernel" - deliberately, because a
    write's unresolvable target IS answered downstream: ``_evaluate_write``
    refuses it first thing under ``gate='unverifiable_target'``, which is the
    accurate name for a refusal keel makes because it does not know what the
    path is. Raising here would RENAME that refusal after this rule, for every
    governing project, and the wrong name is what
    ``is_user_global_target`` declines to do for the same reason. The command
    half cannot lean on that, because it is asked for sessions that have no
    governing project at all (see ``_resolved_or_refuse``), and a command token
    has no downstream judge of any kind.
    """
    try:
        if event.kind != "pre_write":
            return ""
        cache_root = install_cache_root()
        if not cache_root:
            return ""
        for raw in event.file_paths or ():
            try:
                if installed_kernel_root(norm(event.cwd, raw), cache_root):
                    return raw
            except Exception as exc:  # noqa: BLE001 - unverifiable is deny
                print(
                    f"keel: this target could not be compared against the "
                    f"harness's plugin cache, so it is refused: "
                    f"{type(exc).__name__}: {exc}",
                    file=sys.stderr,
                )
                return raw
        return ""
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: the harness's plugin cache could not be located, so the "
            f"rule protecting an installation's own kernel stood down for this "
            f"event: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return ""


def installed_kernel_command(event: KeelEvent) -> str:
    """The command text that would CHANGE an installation's kernel, or "".

    THE COMMAND HALF, added by T507 for the hole the write half left. The write
    half guards ``pre_write`` only; for a ``pre_exec`` event ``governance``
    demotes the installed tree to ABSENT, so it never enters ``projects``, and a
    session with no governing project of its own reaches ``if not projects:
    return allow(UNARMED_REASON)`` before any evaluator runs. In that state -
    which is precisely the unarmed fresh-adopter state T506 exists for - ``sed
    -i 's/return "deny"/return "allow"/' <install>/hooks/keel_gate.py`` rewrote
    the verdict of the gate judging it, with no deny, no bypass line and no
    audit row. Before T506 the install's own arming file judged that command, so
    this is a REGRESSION T506 introduced rather than an old gap.

    IT HOLDS BL57'S BOUNDARY, WHICH IS THE WHOLE DIFFICULTY. Nothing here reads
    the install's arming file, tier, lock, ledger or manifest CONTENT: policy
    authority stays demoted, and an installation still governs nothing and
    demands nothing of an adopter. The line drawn instead is MUTATION AT A
    KERNEL PATH, not location: ``python <install>/scripts/keel.py survey`` -
    BL57 itself, the documented first step of laying keel - names a path inside
    the cache that is not kernel, so nothing in this rule ever looks at it, and
    it clears exactly as T506 made it clear.

    THE MUTATION NOTION IS THE ONE THIS FILE ALREADY HAS, not a second one
    beside it: ``_shell_hits``, the same segmentation, the same read-only
    allowlist, the same ``cd`` taint the policy lock and THE GLOBAL RULE run
    (``shell_hits_installed_kernel``, which argues the mode).

    NEVER RAISES, with the two failure directions the write half argues, and
    the per-token half of that pair lives in ``names_installed_kernel``: a fault
    while judging ONE TOKEN refuses the command, while a fault before any token
    is judged - locating the cache, or a scan that could not run at all - stands
    the rule down with a line on stderr, because a cache keel cannot locate
    holds no installed kernel to guard.
    """
    try:
        if event.kind != "pre_exec":
            return ""
        command = event.command or ""
        if not command:
            return ""
        cache_root = install_cache_root()
        if not cache_root:
            return ""
        return command if shell_hits_installed_kernel(command, event.cwd, cache_root) else ""
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: this command could not be scanned against the harness's "
            f"plugin cache, so the rule protecting an installation's own kernel "
            f"stood down for this event: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return ""


#: The door this refusal names. The OVERRIDE, because this IS a policy refusal
#: - keel knows exactly what the file is - and because the user is the one
#: person who may legitimately repair an install by hand. It composes rather
#: than absorbs, exactly as it does for the lock and for THE GLOBAL RULE, so
#: the pre-T506 reach of this protection is preserved and not quietly widened:
#: before the demotion, the install's own tier-2 arming file refused these
#: writes and the same switch carried them.
NEXT_STEP_INSTALL_KERNEL = (
    "NEXT STEP: change the plugin's SOURCE repository and install or update "
    "the plugin - an installed copy is the harness's to write, and an edit "
    "made in place is lost at the next install. If repairing this installation "
    "by hand is genuinely what the user wants, that needs a session the USER "
    "launched with KEEL_OVERRIDE=on; there is no in-session unlock. Nothing in "
    "this project's own tree is affected by this refusal."
)


def installed_kernel_message(event: KeelEvent, target: str) -> str:
    """The block message for a write or command aimed at an installation's
    own kernel.

    THE LAST SENTENCE DIFFERS BY KIND, exactly as ``user_global_write_message``
    makes it differ and for the same reason: a write declares its target, so
    "reading is not refused" is precisely true there, while a command is judged
    by the CLOSED allowlist and a read keel cannot recognise is refused with the
    writes. A refusal that claimed otherwise would send the reader looking for a
    write that is not in their command.
    """
    reads = _READ_IS_ALLOWED_EXEC if event.kind == "pre_exec" else _READ_IS_ALLOWED_WRITE
    return _joined(
        f"KEEL INSTALLATION KERNEL ({event.tool_name or event.kind} -> "
        f"{scrub(target)}): this names a file inside a tree the HARNESS "
        f"installed under its own plugin cache, and one of that tree's kernel "
        f"paths - the hooks it runs, the arming file that states its rules, "
        f"the manifest that registers them. An installed copy governs nobody "
        f"(it is not a project: T506/BL57), which is why this refusal is not "
        f"any project's policy lock and stands whether or not keel is armed "
        f"where this session started. It is the anchor principle instead: a "
        f"session may not rewrite the guard it is running under, and the "
        f"installed copy is that guard. {reads}",
        NEXT_STEP_INSTALL_KERNEL,
        "(Guardrail: installed-kernel.)",
    )


# ------------------------------------------------------------------ the gate


def _enforcing_ancestor(
    target_norm: str, projects: tuple[tuple[Path, tuple[tuple[str, str], ...]], ...]
) -> bool:
    """True when an ENFORCING governing project's root is an ANCESTOR of
    ``target_norm`` - the pre_write ancestry test T189 adds (see
    .keel/decisions/2026-08-20-the-ladder-binds-what-keel-cannot-attribute.md,
    the yardstick).

    ONLY ROOTS ``governance`` ALREADY COLLECTED are considered - the ones in
    ``decided.projects`` for THIS event - never a fresh filesystem walk: an
    arming file the walk gave up before reaching is exactly the shape this
    whole bucket exists for, so there is nothing further to look up, only a
    structural comparison against what is already known.

    Comparison goes through ``_under`` rather than a bare ``str.startswith``,
    the same fix ``command_is_own`` (T167, ``scripts/keel_survey.py``) already
    needed on a sibling check: two directories that merely share a string
    prefix (``.../keel-app/`` and ``.../keel-app-legacy/``) are not one an
    ancestor of the other, and a bare prefix test would read one as governing
    the other's target.

    An empty ``target_norm`` answers False - the defensive case, since a
    target already in ``Governance.unresolved`` always carries a non-empty
    ``unresolved_norms`` entry (checked in ``Governance.__post_init__``); a
    genuinely unresolvable path takes the separate UNVERIFIABLE IS DENY route
    this file already has, and never reaches this bucket at all. False here
    is the right answer either way: an ancestry test that cannot run is not
    evidence of ancestry, and the caller's fallback to the session's own
    project's tier is what covers it.
    """
    for root, _targets in projects:
        if is_armed(root) and _under(target_norm, str(root).casefold()):
            return True
    return False


def evaluate(event: KeelEvent, env: Mapping[str, str] | None = None) -> KeelVerdict:
    """Decide one pre_write / pre_exec event. Raises GateError when it cannot.

    Raising rather than returning an allow is deliberate: ``run`` owns the
    declared failure policy and needs to know the difference between "this is
    fine" and "I could not tell".

    ONE VERDICT PER GOVERNING PROJECT, AND THE STRICTEST WINS. See ARMING at
    the top of this file for why there can be more than one, and
    ``governance`` for who they are. A single-project event - which is every
    ordinary event - returns exactly the verdict it always did, because there is
    nothing to combine.

    A TIE GOES TO THE TARGET'S OWN PROJECT, which is the last in that order
    (the session's own is always first). Two projects can refuse the same
    write for two different reasons, and the useful one to say out loud is the
    DESTINATION's: its rules are the ones the session had no reason to have
    read, its message names which project spoke, and a session told only about
    its own missing ledger would satisfy that and come straight back into a
    lock it was never told about. Both refusals stand either way - what the tie
    decides is which one is reported, never whether the write is refused.

    THE KILL SWITCH STILL ANSWERS FIRST, before any resolution: ``KEEL_GATE=off``
    means the gate stands down, and a gate that walked the filesystem before
    reading it would have made the switch mean something narrower.

    THEN KEEL'S OWN USER-GLOBAL STATE, BEFORE ANY PROJECT IS ASKED ANYTHING -
    see THE GLOBAL RULE above. It is asked before ``governance`` for two
    reasons: no project's arming file decides it, so resolving projects first
    would only be work whose answer is not consulted; and it is the one
    refusal that must survive an accounting fault in the resolution itself,
    since the directory it guards is shared by every project on the machine.

    AND THEN AN INSTALLATION'S OWN KERNEL, for those same two reasons and one
    more - see THE INSTALLED-KERNEL RULE above. T506 took an installed copy's
    POLICY AUTHORITY away (it arms nothing, judges nobody, and demands no
    ledger inside the plugin cache); it does not follow that a session may
    rewrite the hooks it is running under, and after that demotion no project
    is left to refuse such a write. This rule is that refusal, and it is asked
    here rather than inside a project's evaluation precisely because there is
    no longer a project to ask it in. BOTH KINDS ARE ASKED (T507): a command
    reaches no evaluator at all when the session has no project of its own,
    since ``governance`` never adds the installed tree and the ``if not
    projects`` return below then allows - so the command half must be here, in
    front of that return, or it does not exist.
    """
    env = os.environ if env is None else env
    if env_off("KEEL_GATE", env):
        return allow("kill switch KEEL_GATE=off", gate="kill_switch")

    global_target = user_global_write(event)
    if global_target:
        # The command form is recorded and shown by its redacted, bounded head
        # (the same treatment every blocked command gets); the write form names
        # the path the payload spelled, and files it project-relative like every
        # other audit target (convention 5).
        shown = (
            blocked_command_detail(event.command)
            if event.kind == "pre_exec"
            else scrub(relativise(event.cwd, global_target))
        )
        if env_on("KEEL_OVERRIDE", env):
            # THE OVERRIDE COMPOSES, IT DOES NOT ABSORB, exactly as it does for
            # the policy lock: the write is carried, the bypass is on the record
            # under THIS rule's name, and the event falls through to the plan
            # gate below, which no switch here suspends.
            _audit_bypass(event, shown, gate=USER_GLOBAL_GATE)
        else:
            return deny(
                user_global_write_message(
                    event,
                    shown if event.kind == "pre_exec" else global_target,
                ),
                gate=USER_GLOBAL_GATE,
                target=shown,
            )

    kernel_target = installed_kernel_write(event) or installed_kernel_command(event)
    if kernel_target:
        # THE INSTALLED-KERNEL RULE, and it is asked HERE for the same two
        # reasons the rule above is: no project's arming file decides it - the
        # only one in sight is the copy's own, whose authority T506 removed -
        # and it must survive whatever ``governance`` concludes, since what it
        # guards is the guard currently running. The override composes exactly
        # as it does above: carried, recorded under THIS rule's name, and the
        # event falls through to the projects below.
        #
        # BOTH KINDS ARE ASKED HERE, AND THE POSITION IS THE WHOLE OF THE
        # COMMAND HALF (T507). ``governance`` demotes an installed tree named
        # by a command to ABSENT, so it never joins ``projects``, and the
        # ``if not projects`` return below then answers a session that has no
        # project of its own with an allow before any evaluator runs. A rule
        # asked one line later would be a rule that never fires for exactly the
        # unadopted session BL57 is about.
        shown_kernel = (
            blocked_command_detail(event.command)
            if event.kind == "pre_exec"
            else scrub(relativise(event.cwd, kernel_target))
        )
        if env_on("KEEL_OVERRIDE", env):
            _audit_bypass(event, shown_kernel, gate=INSTALL_KERNEL_GATE)
        else:
            return deny(
                installed_kernel_message(
                    event,
                    shown_kernel if event.kind == "pre_exec" else kernel_target,
                ),
                gate=INSTALL_KERNEL_GATE,
                target=shown_kernel,
            )

    decided = governance(event)
    if decided.refuses:
        if event.kind == "pre_write":
            # T189, NARROWING T187's RETRY (see
            # .keel/decisions/2026-08-20-the-ladder-binds-what-keel-cannot-attribute.md,
            # the yardstick). T187's retry asked "is ANYTHING GOVERNING THIS
            # EVENT enforcing" for every unattributable target - right for
            # pre_exec (a command is atomic, every governing project already
            # judges the whole of it), but OVER-WIDE here: ``governance``
            # partitions write TARGETS strictly by ownership, so counting a
            # foreign project's tier merely because it owns a DIFFERENT
            # resolved target in the SAME payload let a stranger's tier decide
            # a target it has no structural claim to (security review, 80%).
            # THE NARROWER RULE: an unattributable target is answered by
            # WHOEVER COULD OWN IT - deny when an ENFORCING governing
            # project's root is an ANCESTOR of it (``_enforcing_ancestor``, a
            # path-prefix test against roots ``governance`` already collected
            # - no new walk). This is exactly the shape exhaustion exists to
            # catch: a path many levels inside an enforcing project that the
            # walk gave up on rather than failed to find.
            denying_target: str | None = None
            for raw, target_norm in zip(decided.unresolved, decided.unresolved_norms):
                if _enforcing_ancestor(target_norm, decided.projects):
                    denying_target = raw
                    break
            if denying_target is None:
                # NO enforcing project could be shown to OWN any unattributable
                # target. What is left is the SESSION's own project's tier -
                # not the coupling T178 closed, because the session's own
                # project already judges EVERY target of this event by design
                # (``governance``'s consequence 2: "THE SESSION'S OWN PROJECT
                # KEEPS EVERYTHING IT HAD"); this is that same judgment
                # reaching the one bucket that otherwise has no judge. A path
                # that will not resolve AT ALL never reaches this bucket in
                # the first place - it is caught earlier, at the enforcing
                # tier, by the existing unverifiable-target rule
                # (UNVERIFIABLE IS DENY) - so there is no separate case to
                # fall back on for it here.
                if decided.session_root is not None and is_armed(decided.session_root):
                    denying_target = decided.refuses[0]
            if denying_target is not None:
                return deny(
                    unresolved_project_message(event, denying_target),
                    gate="unresolved_project",
                    # The record needs to name WHICH path could not be
                    # attributed, or a reader of the log sees a refusal with
                    # no subject. Relativised and bounded like every other
                    # target field (convention 5).
                    target=scrub(relativise(event.cwd, denying_target)),
                )
        elif any(is_armed(root) for root, _targets in decided.projects):
            # pre_exec, T187 UNCHANGED and reconfirmed at T189: a command is
            # atomic, so every governing project already judges the whole
            # command text - there is no per-target ownership here to narrow.
            # Kept apart from pre_write deliberately (the suite pins the
            # divergence) so a later reader does not "simplify" the two rules
            # back into one.
            unattributable = decided.refuses[0]
            return deny(
                unresolved_project_message(event, unattributable),
                gate="unresolved_project",
                # The record needs to name WHICH path could not be attributed, or
                # a reader of the log sees a refusal with no subject. Relativised
                # and bounded like every other target field (convention 5).
                target=scrub(relativise(event.cwd, unattributable)),
            )
        # ZERO IS NOT SILENCE (T187 accept 2): ``announce_unresolved_targets``
        # never fires on an empty list, so its presence on stderr AND in the
        # audit log is itself the fact that something here was unattributable
        # - a project where nothing was stays free of both. Reached for
        # pre_write only when NEITHER the ancestry test NOR the session's own
        # tier denied, and for pre_exec only when no governing project
        # enforces - the exact negation of the deny above in both cases, so
        # this call can never fire alongside it. The event is NOT returned
        # here: the rest of the payload (if any) is still judged normally
        # below, exactly as an ``outside`` target never short-circuits the
        # rest of the event either.
        announce_unresolved_targets(event, decided.refuses)
    announce_ungoverned_targets(event, decided.outside)
    projects = decided.projects
    if not projects:
        return allow(UNARMED_REASON, gate="unarmed")

    # The session's own directory, resolved ONCE for every project below - see
    # the cost note in ``governance``.
    here = _resolved(event.cwd, "").casefold()
    verdicts = [
        _project_verdict(event, env, root, targets, here) for root, targets in projects
    ]
    # REVERSED so that ``max`` - which returns the FIRST maximal element - hands
    # the tie to the LAST project instead of the first: see A TIE GOES TO THE
    # TARGET'S OWN PROJECT above. ``projects`` is non-empty, tested above, so
    # this always has something to rank.
    return max(reversed(verdicts), key=_strictness)


def _project_verdict(
    event: KeelEvent,
    env: Mapping[str, str],
    root: Path,
    targets: tuple[tuple[str, str], ...],
    here: str,
) -> KeelVerdict:
    """This event, judged by ONE project's arming file.

    The event is re-pointed at that project (``cwd``) before either rule runs,
    so every reader below this line - the lock's prefixes, the workshop's, the
    ledger's path, the audit destination, every message - answers about the
    project that armed the target rather than about the directory the session
    started in. What that project JUDGES arrives separately, in ``targets``.
    When the project IS that directory the event is passed through untouched,
    which is what keeps the ordinary case byte-identical. ``here`` is that
    directory ALREADY RESOLVED, for the two reasons ``governance``
    states: an unresolved comparison reads a session standing in its own project
    as standing outside it, and resolving it once per event instead of once per
    project is most of the cost this task added.

    ``file_paths`` IS DELIBERATELY NOT NARROWED to the judged subset. It is a
    fact about the PAYLOAD - how many files this one tool call names - and two
    rules read it as exactly that: a relaxation is never applied to a
    multi-file payload, and a ledger's resulting content can only be taken from
    a payload that describes one target. Narrowing it would let a project that
    judges one file of a two-file payload believe the payload described that
    file.
    """
    tier = policy_tier(root)
    if tier is None:
        return allow(UNARMED_REASON, gate="unarmed")
    if tier < ENFORCING_TIER:
        return allow(f"tier {tier} is below the enforcing tier {ENFORCING_TIER}", gate="tier")

    scoped = event
    if str(root).casefold() != here:
        scoped = replace(event, cwd=root)

    if event.kind == "pre_write":
        verdict = _evaluate_write(scoped, env, targets)
    elif event.kind == "pre_exec":
        verdict = _evaluate_exec(scoped, env)
    else:
        verdict = allow(f"kind {event.kind} is not gated here", gate="kind")

    if verdict.blocking and scoped is not event:
        return _named_project(verdict, root, event.sess8)
    return verdict


def _named_project(verdict: KeelVerdict, root: Path, sess8: str) -> KeelVerdict:
    """A blocking verdict, told which project made it and where to file it.

    Two readers need this and neither can infer it: the MODEL, which is being
    refused by rules that live in a directory it is not standing in and would
    otherwise read a project-relative plan path as relative to its own cwd; and
    ``_audit``, which files the block with the project whose rule produced it
    instead of creating a stray ``.keel/`` wherever the session began.

    A PLAN REFUSAL NAMES THE FILE IN FULL, absolutely. ``plan_message`` names it
    project-relative, which is exactly right for a session standing in that
    project and useless for one that is not: the model would write the ledger
    beside itself and be refused again for the same reason. Naming the whole
    path is the difference between a refusal and a dead end.

    The absolute path is in the REASON, which is shown to the model and never
    logged (see ``relativise``); ``_audit`` spends ``detail['project']`` on the
    destination and writes a project-relative ``session_cwd`` in its place, so
    convention 5 holds on the record.
    """
    note = (
        f"GOVERNING PROJECT: this refusal comes from the project at {root}, not "
        f"from the directory this session is standing in. That project's "
        f".keel/keel-policy.md armed the target, so its policy lock and its "
        f".keel/plans/ ledger are the ones that apply - a ledger beside the "
        f"session satisfies nothing here."
    )
    if verdict.gate == "plan" and sess8:
        note += (
            f" The ledger this write needs is "
            f"{Path(root).joinpath(*PLANS_RELPATH, f'keel-plan-{sess8}.md')}."
        )
    return KeelVerdict(
        decision=verdict.decision,
        reason=_joined(verdict.reason, note),
        gate=verdict.gate,
        detail={**dict(verdict.detail), "project": str(root)},
    )


def _evaluate_write(
    event: KeelEvent, env: Mapping[str, str], targets: Sequence[tuple[str, str]]
) -> KeelVerdict:
    """Unverifiable, the policy lock, the bootstrap carve-out and its contract, the plan.

    The unverifiable test comes before everything, INCLUDING the override:
    the override suspends a lock the user knows about, and this refusal is
    not that - keel does not know what the target is, so there is nothing for
    an override to have decided about (see the failure policy at the top).

    ``targets`` ARRIVES RESOLVED, as ``(payload path, normalised path)`` pairs,
    rather than being computed from ``event.cwd`` here. That is the T178 split:
    what a relative payload path MEANS is settled by the session's directory,
    while which rules apply to it is settled by the project that armed it - and
    this function is called once per governing project (``_project_verdict``),
    so recomputing the resolution from its own ``event.cwd`` would resolve the
    payload against the wrong directory the moment those two differ.
    """
    override = env_on("KEEL_OVERRIDE", env)
    section = policy_lock_section(event.cwd)
    announce_workshop_refusals(section)
    announce_ignored_indented_lines(section)
    targets = list(targets)
    unverifiable = [raw for raw, target in targets if not target]
    if unverifiable:
        return deny(
            unverifiable_target_message(event, unverifiable[0]),
            gate="unverifiable_target",
            target=scrub(relativise(event.cwd, unverifiable[0])),
        )
    locked = [
        (raw, target)
        for raw, target in targets
        if is_protected(event.cwd, target, section.locked_paths)
    ]
    if locked:
        # THE WORKSHOP SPLIT (workshop design rules 3, 4 and 6). Each locked
        # target is either inside a declared workshop prefix - where the deny is
        # an allow the log records - or outside it, where the lock is what it
        # always was. A payload naming several files is judged per file and the
        # OUTSIDE ones decide the verdict, so one workshop path in a multi-file
        # write can never carry a governance path in with it.
        inside: list[tuple[str, str]] = []
        outside: list[str] = []
        for raw, target in locked:
            prefix = workshop_prefix_for(event.cwd, target, section)
            if prefix:
                inside.append((raw, prefix))
            else:
                outside.append(raw)
        if outside and not override:
            raw_path = outside[0]
            # A relaxation is a single-target affair: one write, one file, one
            # comparison against what is on disk. A payload naming several
            # files is never demoted, because only one of them was examined.
            # THE PAYLOAD's target count, not this project's share of it: a
            # relaxation compares one write against one file on disk, and a
            # payload naming two files describes neither of them well enough.
            relaxation = (
                relaxation_for(event, event.cwd, raw_path, section)
                if len(event.file_paths) == 1
                else None
            )
            if relaxation is not None:
                return ask(
                    policy_lock_ask_message(event, raw_path, relaxation),
                    gate="policy_lock_relaxed",
                    target=relativise(event.cwd, raw_path),
                    relaxation=relaxation,
                )
            return deny(
                policy_lock_message(event, raw_path, cwd=event.cwd, section=section),
                gate="policy_lock",
                target=relativise(event.cwd, raw_path),
            )
        # Nothing refusable is left: every locked target is workshop-listed, or
        # the user's override is carrying the ones that are not. Record each
        # under the kind that actually applies to it - the composition stays
        # honest with the switch on - and FALL THROUGH to the plan gate, which
        # neither mechanism suspends.
        for raw, prefix in inside:
            _audit_workshop_write(event, relativise(event.cwd, raw), prefix)
        if outside:
            _audit_bypass(event, relativise(event.cwd, outside[0]))
    if targets and all(is_plan_target(event.cwd, n) for _, n in targets):
        # THE BOOTSTRAP CARVE-OUT, and the one assertion it carries (rule 3):
        # a write to a session ledger is still permitted unconditionally as an
        # ACT, but not as CONTENT - a ledger that violates the contract is
        # refused here. Everything else under .keel/plans/ passes straight
        # through, and this check reaches plan writes ONLY: the freshness path
        # below is untouched by it.
        refusal = plan_contract_verdict(event, targets)
        if refusal is not None:
            return refusal
        return allow("plan file write is always permitted (bootstrap)", gate="plan_bootstrap")
    if not plan_is_fresh(event.cwd, event.sess8, env):
        return deny(
            plan_message(event),
            gate="plan",
            target=relativise(event.cwd, targets[0][0]) if targets else "",
        )
    return allow("fresh plan on file for this session", gate="plan")


def blocked_command_detail(command: Any) -> str:
    """The audit detail for a blocked command: a redacted, bounded head of it.

    THE MIDDLE PATH, per
    ``.keel/decisions/2026-08-13-gate-block-detail-middle-path.md``. Until that
    ruling every blocked command was logged as ``<command>``, which is
    unleakable and unreadable: a reader of the log could see that the gate
    fired and never what it fired on. The predecessor board prints the command
    raw, which is legible and is a leak. What is recorded here is the command
    itself, passed through the full redaction chokepoint and cut to a head.

    Order, and the order is the whole security argument:

    1. Cut to ``BLOCKED_COMMAND_SCAN_CHARS`` first, so redaction's cost is
       bounded by a constant however large the payload was.
    2. ``redact`` SECOND, over that whole span - the same function
       ``keel_events._append_jsonl`` applies at the write, so the private
       blocks, home spellings and denied names in the command are gone by the
       same rules that govern every other value keel writes. ``strip_private``
       runs inside it, first and unconditionally.
    3. Cut to ``BLOCKED_COMMAND_HEAD_CHARS`` LAST, on the redacted text.

    Step 3 is deliberately after step 2, which is the opposite of
    ``keel_capture.action_detail``'s order, and the difference is not
    cosmetic. WHAT THE ORDER DEFENDS, precisely, because "a fragment matches
    no pattern" is true of only one of the three screens: the denied-names
    register matches WHOLE tokens by hash, so a registered name the cut sliced
    in half hashes to nothing and would pass the screen intact. (A home-shaped
    path cut in half is caught either way - ``keel_redact._HOME_SHAPE_RE``
    matches a truncated account segment on purpose - so there the wrong order
    costs legibility rather than privacy; and a ``<keel-private>`` region
    survives no order, since ``strip_private`` runs before either.) Cutting
    after redaction can only ever truncate a token redaction already produced
    (``[home-p``), which is a cosmetic loss and not a leak. The head carries
    no truncation marker, matching the capture module's idiom for the same
    field. Both directions are pinned in
    ``tests/test_keel_blocked_command_detail.py``, the wrong order included.

    FAIL-CLOSED, which is the reason this function exists at all rather than
    the expression being inlined at four call sites: if redaction cannot run -
    it raises, or ``redact`` is not callable in a degraded process - the
    detail falls back to ``OPAQUE_COMMAND``. Never to the raw text, and never
    to silence: each fallback prints its own line on stderr (convention 7),
    naming the exception and never the command it refused to record. A
    redactor that returns something unusable - a non-string, or blank text -
    falls back the same way, as does an empty or non-string command, so the
    field is a non-empty string on every path.
    """
    text = command if isinstance(command, str) else ""
    if not text.strip():
        return OPAQUE_COMMAND
    try:
        head = redact(text[:BLOCKED_COMMAND_SCAN_CHARS])
    except Exception as exc:  # noqa: BLE001 - fail-closed, and reported
        print(
            f"keel: blocked-command detail fell back to {OPAQUE_COMMAND}: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return OPAQUE_COMMAND
    if not isinstance(head, str) or not head.strip():
        return OPAQUE_COMMAND
    return head[:BLOCKED_COMMAND_HEAD_CHARS]


def _evaluate_exec(event: KeelEvent, env: Mapping[str, str]) -> KeelVerdict:
    """The same three rules, applied to command text instead of a path.

    Rule 3 is asked BEFORE freshness, the way the write path asks it before
    freshness: a command that rewrites a ledger must hear that the shell is the
    wrong instrument, not that its plan is stale - the second answer would send
    it back to the same command.

    Rule 2 is asked LAST and only of commands that change something, which is
    the scope the contract at the top of this file states for it. Rules 1 and 3
    are unaffected by that scoping: both are asked of every command, mutating
    or not, and both still answer before freshness does.

    ONE BRANCH HERE DECIDES NOTHING (E1): when rule 3 does NOT hit, the command
    is asked whether the lock's closed world would have stopped what its open
    world just allowed, and a yes writes one ``lock_unclassifiable`` line and
    falls straight through. It is an ``elif`` on purpose - a command the lock
    refused, or carried on the override, is already accounted for by the branch
    above and must not be counted twice under a name meaning "unjudged".
    """
    command = (event.command or "").casefold()
    if command and shell_hits_policy_lock(command):
        if env_on("KEEL_OVERRIDE", env):
            _audit_bypass(event, blocked_command_detail(event.command))
        else:
            return deny(
                shell_policy_lock_message(event, policy_lock_section(event.cwd)),
                gate="policy_lock",
                target=blocked_command_detail(event.command),
            )
    elif command and shell_policy_lock_unclassifiable(command):
        # E1: THE OPEN WORLD HAD NOTHING TO JUDGE THIS BY, and its closed world
        # would have stopped the same text. Reached only when the branch above
        # did NOT hit, so this can never touch a command the lock refuses or a
        # bypass it already recorded. One line, then the ordinary path continues
        # - the allow is unchanged, and the record is the whole of the change.
        _audit_lock_unclassifiable(event, blocked_command_detail(event.command))
    if command and shell_hits_dot_keel_restore(command):
        # BL2/T318: a git command with restore semantics naming a .keel/ path
        # is a WRITE, exactly as rm against the same path already is, and this
        # rule carries the override the same way the policy lock does - the
        # user's switch, recorded, never an in-session unlock.
        if env_on("KEEL_OVERRIDE", env):
            _audit_bypass(
                event, blocked_command_detail(event.command), gate=DOT_KEEL_RESTORE_GATE
            )
        else:
            return deny(
                dot_keel_restore_message(event),
                gate=DOT_KEEL_RESTORE_GATE,
                target=blocked_command_detail(event.command),
            )
    if command and shell_writes_session_ledger(command):
        # THE CONTENT OF A SHELL WRITE CANNOT BE CONTRACT-CHECKED, so it is
        # refused rather than assumed clean. No override is consulted: this is
        # not a lock the user suspends, it is an assertion keel cannot make -
        # and the way past it (the Write tool) needs nobody's permission.
        return deny(
            shell_plan_contract_message(event),
            gate="plan_contract_shell",
            target=blocked_command_detail(event.command),
        )
    if command and shell_is_read_only(command):
        # RULE 2 IS SCOPED TO STATE-CHANGING TOOLS, and a command every one of
        # whose segments names a word on the read-only allowlist is not one:
        # requiring a ledger before `git status` denied the model the
        # orientation the ledger is supposed to be written FROM. The scope is
        # decided by ENUMERATING WHAT IS SAFE, never by chasing what is not,
        # and every case the allowlist cannot clear still needs a plan - so
        # this branch is only ever reached by a command the gate parsed and
        # recognised in full.
        return allow("every segment names a read-only command: rule 2 does not reach it", gate="plan_scope")
    if not plan_is_fresh(event.cwd, event.sess8, env):
        return deny(plan_message(event), gate="plan", target=blocked_command_detail(event.command))
    return allow("fresh plan on file for this session", gate="plan")


def _audit_lock_event(
    event: KeelEvent, name: str, detail: Mapping[str, Any], gate: str = "policy_lock"
) -> None:
    """Record one line about a refusal that did not happen.

    ONE writer for the two kinds - ``gate_bypass`` (the user's override carried
    it) and ``workshop_write`` (a declared workshop prefix carried it) - so the
    two can never drift into different shapes, and so both reach
    ``keel_events._append_jsonl``, the single chokepoint where every value is
    redacted before it becomes bytes. Auditing may never fail the gate, and a
    failure to audit is reported rather than swallowed.

    ``gate`` NAMES THE RULE THAT WOULD HAVE REFUSED, and defaults to the lock
    because for most of this file's life the lock was the only rule an override
    could carry. THE GLOBAL RULE (keel's user-global files) is the second, and
    it passes its own name: a reader counting bypasses must be able to tell a
    session editing its own project's locked source from one reaching into the
    state every project on the machine shares.

    IT IS FILED ONLY WHERE KEEL WAS ADOPTED, for the reason
    ``_permit_crash_ledger_write`` states about its own line: a session
    standing in a directory that never adopted keel has no log to file this
    in, and creating one would mean keel scattering ``.keel/`` trees through
    directories nobody opted in. That case is reachable only through the
    global rule, which is the one rule that does not need an arming file - and
    it is never silent: the stderr line is then the whole record.

    WHERE "ADOPTED" IS ASKED HAS MOVED (T515): the session's PROJECT, resolved
    by the same walk as everything else, rather than the session's DIRECTORY.
    Inside ``_project_verdict`` the event has already been re-pointed at the
    governing project and the walk finds that same directory, so those lines are
    unchanged; what this reaches is the two call sites that run BEFORE
    ``governance`` - the global rule and the installed-kernel rule - whose
    bypass line was dropped entirely for a session standing in a subdirectory.
    ``audit_destination`` says at length why that is more record and never a new
    ``.keel/``.
    """
    try:
        destination = session_audit_root(event.cwd)
        if not policy_present(destination):
            print(
                f"keel: no {name} audit line was written - this session's own "
                f"directory carries no arming file, so there is no log to file "
                f"it in. This notice is the whole record.",
                file=sys.stderr,
            )
            return
        append_audit(
            destination,
            {
                "event": name,
                "gate": gate,
                "kind": event.kind,
                "tool": event.tool_name,
                "session": event.session_id,
                "detail": dict(detail),
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(f"keel: {name} audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def _audit_bypass(event: KeelEvent, target: str, gate: str = "policy_lock") -> None:
    """Record one refusal the user's override suspended.

    The override is the single sanctioned hole in the lock, so each use of it
    is a line on the log: the reminders make the state visible forward, this
    keeps it accountable backward. ``gate`` says WHICH rule was suspended - see
    ``_audit_lock_event``.
    """
    _audit_lock_event(
        event, "gate_bypass", {"target": target, "switch": "KEEL_OVERRIDE"}, gate=gate
    )


def _audit_lock_unclassifiable(event: KeelEvent, target: str) -> None:
    """Record one command the policy lock ALLOWED WITHOUT BEING ABLE TO JUDGE IT.

    THE THIRD KIND OF LINE ABOUT A REFUSAL THAT DID NOT HAPPEN, and the only one
    of the three that claims no authority for it: ``gate_bypass`` says the user's
    switch carried it, ``workshop_write`` says a declaration carried it, and this
    says NOTHING CARRIED IT - the lock's open world simply had no verb, redirect
    or assignment to match, and its closed world would have stopped the same
    text. It is written through ``_audit_lock_event`` with the other two so all
    three reach ``keel_events._append_jsonl``, the single chokepoint where every
    value is redacted before it becomes bytes. That matters more here than for
    either sibling: this line carries SHELL COMMAND TEXT, which routinely holds
    home paths, and this repository's audit log is TRACKED - an unredacted detail
    field would make the guard itself the leak. ``target`` arrives from
    ``blocked_command_detail``, which redacts and truncates before this is
    reached, so the text is screened twice by two independent doors.

    IT CANNOT CHANGE A VERDICT AND IT CANNOT RAISE - the same contract
    ``_audit_launcher_deny`` holds, and for the same reason: a record ABOUT a
    weakness may never become a second weakness. ``_audit_lock_event`` swallows
    and reports every fault, the call site ignores the return, and the allow it
    annotates is returned whether this line was written or not.

    NO STDERR NOTICE, deliberately, and this is where it differs from
    ``_audit_workshop_write``. A workshop write is a rare, targeted event a human
    should see in the transcript; this fires on a measured 3.24% of all shell
    commands, most of them ordinary reads like ``git diff hooks/``. A notice
    printed that often is not loud, it is weather - and it would be read past
    exactly when it mattered. The record is the loudness; the log is where a
    reader counts these.
    """
    _audit_lock_event(event, LOCK_UNCLASSIFIABLE_EVENT, {"target": target})


def _audit_workshop_write(event: KeelEvent, target: str, prefix: str) -> None:
    """Record one policy-locked write a declared workshop prefix permitted.

    THE LOUD HALF of allow-plus-loud-audit (workshop design rule 5): its own
    event kind, counted apart from ``gate_bypass``, carrying the prefix that
    permitted it so a reader of the log can see which declaration was
    exercised. One line on stderr goes with it, because "loud" is meant to
    reach the human reading the transcript as well as the reader of the log,
    and stderr is where this gate says everything that is not a verdict.

    The line says a REFUSAL WAS NOT MADE, exactly as ``gate_bypass`` does: the
    plan gate can still refuse this write afterwards, and neither event claims
    the write happened.
    """
    _audit_lock_event(event, "workshop_write", {"target": target, "workshop": prefix})
    try:
        print(
            f"keel: WORKSHOP WRITE ({target} under '{prefix}'): the policy lock's "
            f"deny is an allow here, on the audit record as workshop_write.",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 - a notice may never fail the gate
        return


def audit_destination(event: KeelEvent, verdict: KeelVerdict) -> Path:
    """Which project's audit log a verdict belongs in.

    THE PROJECT WHOSE RULE PRODUCED IT, when that is not the session's own
    directory: ``_named_project`` puts it in ``detail['project']`` and this
    reads it back. Two things go wrong otherwise. The refusal is filed where the
    project that made it cannot read it - and the gate CREATES a ``.keel/``
    directory in whatever directory the session happened to start in, which for
    a workspace-root session means keel scattering audit logs over directories
    nobody adopted.

    THE FALLBACK IS THE SESSION'S PROJECT, NOT THE SESSION'S DIRECTORY (T515),
    and the difference is a refusal that used to go unrecorded. Three gates
    answer BEFORE ``governance`` runs and so carry no ``detail['project']`` at
    all - THE GLOBAL RULE, THE INSTALLED-KERNEL RULE, and ``unresolved_project``
    - and this used to hand ``_audit`` the raw ``event.cwd``. For a session
    standing in a SUBDIRECTORY of an armed project that directory holds no
    arming file, so ``_audit``'s own ``policy_present`` test failed and the
    block was refused with NO AUDIT LINE, on the reasoning that there was no
    log to file it in. There was: one or more levels up, the same project whose
    ledger the plan gate would have demanded. Resolving it with
    ``resolve_project`` - the walk every other arming question already uses -
    files the line where the project can read it.

    IT CANNOT CREATE A LOG ANYWHERE NEW. The walk returns only a directory that
    already carries an arming file, and ``PROJECT_UNKNOWN`` or
    ``PROJECT_ABSENT`` leave the old answer standing, which ``_audit`` then
    declines to write into. The direction is strictly MORE record, never a new
    ``.keel/`` in a directory nobody adopted (R25).

    Never raises: a destination keel cannot read is the session's own.
    """
    value = verdict.detail.get("project")
    if isinstance(value, str) and value:
        try:
            return Path(value)
        except (OSError, ValueError):
            return event.cwd
    return session_audit_root(event.cwd)


def session_audit_root(cwd: Path) -> Path:
    """The armed project a session's own line belongs in - ``cwd`` if none.

    ONE ANSWER FOR THE TWO WRITERS that have no governing project to spend
    (``audit_destination`` for a block, ``_audit_lock_event`` for a line about
    a refusal that did not happen), so the two cannot come to disagree about
    where a session's own record goes. Never raises: a walk that faults leaves
    the pre-T515 answer standing, which is wrong about a subdirectory in
    exactly the way this closes and is still better than no destination at all.
    """
    try:
        session = resolve_project(cwd)
    except Exception:  # noqa: BLE001 - a destination may never fail the gate
        return cwd
    if session.found and session.root is not None:
        return session.root
    return cwd


def _audit(event: KeelEvent, verdict: KeelVerdict) -> None:
    """Record a block. Auditing must never be able to fail the gate itself.

    THE GOVERNING PROJECT IS SPENT HERE, NOT WRITTEN HERE. ``detail['project']``
    is an absolute path - it has to be, since it is the directory this line is
    filed in - and convention 5 says the log carries no absolute path. So it
    chooses the destination and is then replaced by ``session_cwd``: where the
    session was standing, expressed relative to the project that refused it
    (``..`` for the workspace-root case this task exists for). That is the fact
    a reader of the project's log actually needs, and it is project-relative
    like every other path keel logs.

    THE GUARD STARTS AT THE FIRST STATEMENT (T208, clause 2 - what is done to
    one gate is done to both). The lines below used to sit OUTSIDE the ``try``,
    so ``_resolved`` and ``relativise`` - OS calls on a path that already
    resolved upstream in the same call - could raise past this function, past
    ``run``'s tail (where this is called after the verdict is final) and into
    ``keel_hook``. Under the ratified crash ruling that escape is now a deny
    rather than an allow, but it would be a deny with NO audit line and the
    wrong fault named, so the fault is kept here: a failure to record a block
    costs the record only, never the block.
    """
    try:
        detail = {k: v for k, v in verdict.detail.items()}
        destination = audit_destination(event, verdict)
        if not policy_present(destination):
            # UNADOPTED DESTINATIONS GET THE NOTICE, NOT A NEW ``.keel/``. Every
            # refusal but one comes from a project's own arming file, so this
            # cannot fire for them; THE GLOBAL RULE is the exception, since
            # keel's user-global files are refused from any directory at all,
            # adopted or not. Filing that refusal would mean creating an audit
            # log in a directory nobody opted in - the same trade
            # ``_permit_crash_ledger_write`` already refuses to make - so the
            # stderr line is the whole record instead. Never silent.
            print(
                f"keel: no gate_block audit line was written for a "
                f"{verdict.gate} refusal - this session's own directory carries "
                f"no arming file, so there is no log to file it in. This notice "
                f"is the whole record.",
                file=sys.stderr,
            )
            return
        if detail.pop("project", None):
            # THE RESOLVED cwd, not the spelling the harness handed over. Both
            # sides of a relpath must be spelled the same way or the result
            # climbs out of the tree and back down again - and on Windows that
            # dragged an 8.3 ACCOUNT SEGMENT into the line, which the home
            # screen cannot recognise because it is anchored on the real
            # spelling.
            detail["session_cwd"] = relativise(destination, _resolved(event.cwd, ""))
        append_audit(
            destination,
            {
                "event": "gate_block",
                "gate": verdict.gate,
                "kind": event.kind,
                "tool": event.tool_name,
                "session": event.session_id,
                "detail": detail,
            },
        )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(f"keel: gate audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)


def failure_policy_roots(event: KeelEvent) -> tuple[Path, ...]:
    """The armed projects ``run`` weighs when evaluation itself failed.

    THE SAME RESOLUTION ``evaluate`` USES, and that is the point: before T178
    this question was ``policy_present(event.cwd)``, so a crash while judging a
    target inside an armed project chose its failure direction from the
    directory the session was standing in and failed OPEN on an armed
    project's file.

    A PATH KEEL COULD NOT ATTRIBUTE COUNTS AS ARMED HERE, even when no project
    was found: an arming file the walk never reached could govern it, so this is
    not the unarmed case and must not fail open. The destination for the line is
    then the session's own directory, because there is no project to file it
    with. THE MESSAGE NO LONGER OVERSTATES THAT CASE: ``run`` used to say "this
    project is armed" for every root this function returns, which is false for
    the double-fault path - a crash AND an unattributable path, where nothing
    was shown to be armed at all. ``cannot_evaluate_message`` now asks
    ``policy_present`` about the root it is about to name and says which of the
    two situations it is in.

    FAIL-SAFE ON ITS OWN FAILURE: if the resolution is what raised, the answer
    falls back to the pre-T178 reading of ``event.cwd``. That is wrong about
    foreign targets in exactly the way this task fixed, and it is still better
    than a failure policy that cannot answer at all.
    """
    try:
        decided = governance(event)
        if decided.projects:
            return tuple(root for root, _targets in decided.projects)
        if decided.refuses:
            return (Path(_resolved(event.cwd, "") or event.cwd),)
        return ()
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: arming resolution failed, falling back to the session's own "
            f"directory: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return (event.cwd,) if policy_present(event.cwd) else ()


# ------------------------------- what the gate does when it CANNOT evaluate
#
# A guard that cannot evaluate must not pretend it approved (R3) - that half was
# already written and already worked. What was missing is the check: the gate
# never asked whether IT was the broken thing, so it blamed the adopter's arming
# file for its own half-applied edit, and it froze the one directory in which the
# freeze could have been recorded. The model for the first half is
# ``_lock_orientation`` in ``hooks/keel_session.py``, which reported the true
# ``ValueError`` at castoff while this file's ``run`` was still blaming an
# innocent file for the same fault.


#: KEEL'S OWN SOURCE, as absolute casefolded directory prefixes, separator
#: included so ``.../hooks`` cannot match ``.../hooks-backup``. A fault whose
#: innermost frame sits under one of these is keel's own defect rather than the
#: adopter's configuration, and that is the distinction everything below turns
#: on. Both directories are already resolved above for the import path, so no
#: new filesystem question is asked here, and the tuple is built ONCE at import:
#: a hook process serves one tool call, and a directory does not move inside one.
_KEEL_SOURCE_DIRS: tuple[str, ...] = (
    (_HOOKS_DIR + os.sep).casefold(),
    (_SCRIPTS_DIR + os.sep).casefold(),
)

#: THE FAULT TYPES A HALF-APPLIED EDIT PRODUCES, each named for the edit that
#: produces it. All three of the 2026-08-19 freezes are in this list. They are
#: recognised only TOGETHER WITH a keel source site (see ``gate_self_fault``),
#: because every one of them can also be raised by the standard library on an
#: adopter's data, and misreading that direction is how a gate blames the wrong
#: file. Subclasses ride along: ``UnboundLocalError`` under ``NameError``,
#: ``ModuleNotFoundError`` under ``ImportError``, ``IndentationError`` under
#: ``SyntaxError``.
_SELF_FAULT_TYPES: tuple[type[BaseException], ...] = (
    NameError,  # a symbol deleted while a call site still named it
    AttributeError,  # a renamed attribute, or a module written only halfway
    TypeError,  # a parameter added in one edit, its call site in the next
    ImportError,  # a sibling module that no longer imports
    SyntaxError,  # a partially written file, compiled when it is first reached
    RecursionError,  # a call graph edited into a cycle
)

#: The one ``ValueError`` shape that is structural rather than about data: a
#: return value added without updating an unpacking site. Matched on the MESSAGE
#: because the type alone cannot tell it apart from ``int('abc')`` on a
#: malformed ``tier:`` - which is the adopter's file and must stay theirs.
_UNPACK_MARKERS: tuple[str, ...] = ("unpack", "unpacking")

#: THE EVALUATION PATH, by name, for ``module_preflight``. Spelled as literals
#: and pinned by ``tests/test_keel_gate_self_preflight_t179.py``, so a rename
#: fails the suite instead of quietly emptying the preflight - the same
#: discipline the workshop state names keep in ``hooks/keel_session.py``.
EVALUATION_PATH_SYMBOLS: tuple[str, ...] = (
    "evaluate",
    "governance",
    "_project_verdict",
    "_evaluate_write",
    "_evaluate_exec",
    "failure_policy_roots",
    "user_global_write",
    "installed_kernel_write",
    "installed_kernel_command",
)

#: The kernel this module cannot produce a verdict without. Imported at module
#: scope, so an absent one means an edit removed the import while call sites
#: kept using it - which imports perfectly and fails on the first call.
KERNEL_SYMBOLS: tuple[str, ...] = ("allow", "ask", "deny", "append_audit", "redact")

#: ``.keel/plans`` as ONE path segment run, separators on both sides, for
#: ``is_ledger_path``. Built from ``PLANS_RELPATH`` so the crash carve-out and
#: the ordinary bootstrap allow can never mean two different directories.
_PLANS_SEGMENTS = (os.sep + os.sep.join(PLANS_RELPATH) + os.sep).casefold()


def module_preflight() -> tuple[str, ...]:
    """The gate's OWN module state, checked before it is trusted to evaluate.

    WHAT THIS CAN SEE, and the narrowness is deliberate: every symbol on the
    evaluation path is still BOUND in this module and still CALLABLE. That is
    the one class of half-applied edit a check can be CERTAIN about, and
    certainty is required here rather than merely nice - the verdict this feeds
    is a DENY, so a false positive would freeze the project exactly as the
    defect does. A preflight that guessed would be worse than none.

    WHAT THIS CANNOT SEE, said plainly because a check whose limits are
    unstated gets trusted past them: arity, an unpacking site left behind by a
    changed return value, a signature that gained a parameter. Those bind fine
    and fail when the line RUNS - the whole point of
    ``a-module-that-imports-is-not-a-gate-that-evaluates`` - and no rule about
    names catches them. They are caught after the fact instead, by
    ``gate_self_fault``, which is why both halves exist.

    NEVER RAISES, INCLUDING ON ITSELF. A preflight that threw would be caught
    by the very handler it exists to inform, and the fault would be reported as
    an evaluation crash rather than as what it is.
    """
    faults: list[str] = []
    try:
        scope = globals()
        for group, names in (
            ("the evaluation path", EVALUATION_PATH_SYMBOLS),
            ("the verdict kernel", KERNEL_SYMBOLS),
        ):
            for name in names:
                if name not in scope:
                    faults.append(f"{group}: {name} is no longer defined in this module")
                elif not callable(scope[name]):
                    faults.append(
                        f"{group}: {name} is a {type(scope[name]).__name__}, "
                        f"not something that can be called"
                    )
    except Exception as exc:  # noqa: BLE001 - a check that cannot run says so
        return (f"the preflight itself could not run: {type(exc).__name__}: {exc}",)
    return tuple(faults)


def fault_site(exc: BaseException) -> str:
    """``keel_gate.py:1234`` for the INNERMOST frame inside keel's own source.

    Innermost rather than outermost, because that is the line that actually
    raised: a fault in a called helper must name the helper, not the caller
    that happened to be in keel too. "" when no frame of the traceback is
    keel's own, which is the right answer for a fault raised by a test's stub
    or by the standard library on an adopter's file - and "" reads as "not
    keel's own defect" in ``gate_self_fault``, never as "no fault".

    BASENAME AND LINE ONLY (convention 5): no absolute filesystem path reaches
    a refusal message or the audit log through this function. Never raises - a
    traceback that cannot be walked is simply no evidence.
    """
    site = ""
    try:
        frame = exc.__traceback__
        while frame is not None:
            filename = frame.tb_frame.f_code.co_filename or ""
            if filename.casefold().startswith(_KEEL_SOURCE_DIRS):
                site = f"{os.path.basename(filename)}:{frame.tb_lineno}"
            frame = frame.tb_next
    except Exception:  # noqa: BLE001 - evidence, not a decision
        return ""
    return site


def gate_self_fault(exc: BaseException) -> str:
    """KEEL'S OWN inconsistency in its own words, or "" when this is not one.

    THE DISCRIMINATOR IS IN TWO PARTS, and both are needed, because getting it
    wrong is the whole defect: a fault blamed on ``.keel/keel-policy.md`` sends
    the reader to a file that parsed cleanly, and a fault blamed on keel when
    the adopter's file really is malformed hides the one thing they can fix.

    1. A ``GateError`` IS NEVER THIS MODULE'S STATE. It is the gate's
       deliberate way of saying it could not read the project's configuration -
       an unreadable arming file, frontmatter declaring no tier, a
       ``KEEL_PLAN_TTL_MIN`` that is not a number. The project is the right
       subject for those, so this returns "" and lets
       ``policy_parse_fault`` name the file.
    2. ANYTHING ELSE IS JUDGED ON TYPE AND SITE TOGETHER. Type alone would be
       wrong: ``int()`` on a tier of ``abc`` raises ``ValueError`` about the
       adopter's file. Site alone would be wrong too: virtually every fault
       passes through this module somewhere. Only a structural type
       (``_SELF_FAULT_TYPES``, plus the unpacking ``ValueError``) raised at a
       line inside keel's own source is reported as keel's defect.

    The returned sentence is redacted and length-bounded like every other value
    this module echoes back, because an exception message can carry a path.
    """
    try:
        if isinstance(exc, GateError):
            return ""
        site = fault_site(exc)
        if not site:
            return ""
        structural = isinstance(exc, _SELF_FAULT_TYPES) or (
            isinstance(exc, ValueError)
            and any(marker in str(exc).casefold() for marker in _UNPACK_MARKERS)
        )
        if not structural:
            return ""
        return scrub(redact(f"{type(exc).__name__}: {exc} (raised at {site})"), 200)
    except Exception as inner:  # noqa: BLE001 - a classification may never fail the gate
        # NOT SILENT, even though the refusal below covers it in prose: "" from
        # here makes the message say keel could not attribute the fault to its
        # own source, which is true but says nothing about WHY. The reason is
        # said here so a reader of the transcript is not left inferring it.
        print(
            f"keel: the fault classifier failed, so this fault is reported as "
            f"unattributed: {type(inner).__name__}: {inner}",
            file=sys.stderr,
        )
        return ""


def policy_parse_fault(root: Path) -> str:
    """Why the arming file cannot be read, or "" when it reads cleanly.

    THE CHECK THAT STOPS THE GATE BLAMING AN INNOCENT FILE (T179 accept 2).
    Both readers are exercised, because either can be the one that failed: the
    frontmatter tier and the optional ``## Policy lock`` section. An INVALID
    lock section counts as a fault to report even though the gate carries on
    without it, since a section being ignored is exactly the kind of thing the
    owner wants told; an absent section is not a fault at all.

    Never raises: a fault raised here IS the answer, and one that cannot even
    be described is reported as that rather than as silence.
    """
    try:
        if not policy_present(root):
            return "that project has no .keel/keel-policy.md at all"
        policy_tier(root)
        section = policy_lock_section(root)
        if section.present and not section.valid:
            return "its '## Policy lock' section is invalid - " + "; ".join(section.errors)
    except GateError as exc:
        return scrub(redact(str(exc)), 200)
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        return scrub(redact(f"{type(exc).__name__}: {exc}"), 200)
    return ""


def plan_ttl_fault(env: Mapping[str, str]) -> str:
    """Why ``KEEL_PLAN_TTL_MIN`` cannot be used, or "" when it is fine or unset.

    THE SAME PATTERN AS ``policy_parse_fault`` (T206), asked of this session's
    environment instead of the arming file: the escaped exception is never
    trusted directly, so this and ``plan_ttl_minutes``'s own read of the
    variable can never disagree about what "broken" means. A ``GateError``
    from ``plan_ttl_minutes`` is always this operator's environment, never
    keel's own module - the same guarantee ``gate_self_fault`` documents for
    ``policy_tier`` - so the message this returns names the variable and the
    shape its value must take, never keel's source.

    Never raises: a fault raised here IS the answer, per ``policy_parse_fault``.
    """
    try:
        plan_ttl_minutes(env)
    except GateError as exc:
        return scrub(redact(str(exc)), 200)
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        return scrub(redact(f"{type(exc).__name__}: {exc}"), 200)
    return ""


def is_ledger_path(target_norm: str) -> bool:
    """True when a RESOLVED, casefolded path is inside SOME ``.keel/plans/``.

    A SEGMENT TEST, NOT A PROJECT RESOLUTION, and that is the point: this is
    reached only once the gate has already failed, so it may not depend on the
    walk that may be what failed. Any ``.keel/plans/`` directory is by
    construction the ledger directory of some keel project, and the bootstrap
    reasoning that a session ledger can never be locked holds for every one of
    them.

    NOT A PREFIX TEST EITHER: the separators on both sides of
    ``_PLANS_SEGMENTS`` mean ``.keel/plansomething`` is not a ledger path, and
    a file merely NAMED like a ledger somewhere else is not one either.
    ``is_plan_target`` stays the reader for the ordinary path, where a project
    root is known; the two agree on every path both are asked about, and
    ``tests/test_keel_gate_self_preflight_t179.py`` pins that.
    """
    if not target_norm:
        return False
    return _PLANS_SEGMENTS in target_norm + os.sep


def crash_ledger_carve_out(event: KeelEvent) -> str:
    """The ONE directory a gate that cannot evaluate still lets through:
    ``.keel/plans/``. Returns the targets it covers, or "". Never raises.

    WHY IT EXISTS. The ledger is itself a write, so a gate that fails closed on
    everything leaves the session unable to record that it is stuck - and
    stop-with-accounting then demands accounting that the same fault forbids.
    That happened three times on 2026-08-19 and each time the owner had to
    intervene from outside the session. The bootstrap carve-out in
    ``templates/keel-policy.md`` already reasons that the session ledger can
    never be locked; a crash simply bypassed the reasoning.

    THE LIMIT IS PART OF THE CHANGE, because this is a fail-closed path being
    loosened, and every clause below is a refusal that stands:

    - ``.keel/plans/`` AND NOTHING ELSE. Not ``.keel/``, not the audit log, not
      the arming file, not source. Nothing here reads as permission for any
      other path, and nothing here may be widened by implication.
    - ``pre_write`` ONLY, never a command. keel cannot tell what else a shell
      line does, and the half it cannot verify stays refused. A session writes
      its ledger with Write or Edit anyway - which is already what the plan
      contract requires (``NEXT_STEP_PLAN_CONTRACT_SHELL``).
    - EVERY TARGET OR NONE. One source file in the same payload refuses the
      whole write, so a ledger path can never carry a neighbour past the gate.
    - UNVERIFIABLE IS STILL DENY. A target that will not resolve is not a
      ledger path, so the failure policy keeps it.
    - IT PROVES NOTHING ABOUT THE CONTRACT. Rule 3's assertion could not run.
      The write is permitted, not blessed, and both the message and the audit
      line say so.

    A fault while deciding this means the carve-out does NOT apply - the
    loosening is the thing that has to be certain, so doubt fails closed here,
    the opposite direction to the one the gate as a whole is failing in.
    """
    try:
        if event.kind != "pre_write":
            return ""
        raw_paths = tuple(event.file_paths or ())
        if not raw_paths:
            return ""
        for raw in raw_paths:
            if not is_ledger_path(norm(event.cwd, raw)):
                return ""
        shown = ", ".join(
            scrub(redact(relativise(event.cwd, raw)), 80) for raw in raw_paths[:3]
        )
        more = f" (+{len(raw_paths) - 3} more)" if len(raw_paths) > 3 else ""
        return (shown + more) or "the session ledger"
    except Exception as exc:  # noqa: BLE001 - reported, and NOT a carve-out
        print(
            f"keel: the ledger carve-out could not be decided, so it does not "
            f"apply: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return ""


def _permit_crash_ledger_write(
    event: KeelEvent, env: Mapping[str, str], targets: str, detail: str, self_fault: str
) -> KeelVerdict:
    """Allow one ``.keel/plans/`` write past a gate that could not evaluate,
    and make sure the exception is impossible to miss.

    LOUD ON BOTH CHANNELS, the same allow-plus-loud-audit shape
    ``_audit_workshop_write`` keeps for the other place this project turns a
    refusal into an allow: one line on stderr for the human reading the
    transcript, one ``crash_ledger_write`` line on the record for afterwards.
    A loosening nobody can count is a loosening nobody will notice.

    THE PERMISSION IS UNCHANGED BY T206 - this still allows unconditionally,
    whatever the fault. What T206 adds is the DIAGNOSIS: ``_crash_fault_label``
    is the same classifier ``cannot_evaluate_message`` calls, so a crash that
    lands here because of a genuinely broken arming file is NAMED as one, on
    both channels, instead of the fault vanishing behind the generic sentence
    below - the defect the audit that justified this task described as "a
    genuinely broken arming file reaches the CRASH path instead of the
    honest-remediation path". The classifier never raises, so this stays as
    safe to call as it always was.

    THE LINE IS FILED WITH THE SESSION'S OWN DIRECTORY, and only when that
    directory carries an arming file. The project resolution is exactly what
    may have failed, so this cannot ask it; and rather than create a stray
    ``.keel/`` in a directory that never adopted keel, an unadopted cwd gets
    the stderr line alone and is TOLD that the audit line was not written.
    Neither the notice nor the audit may fail the write it is describing.
    """
    try:
        fault_kind, _source, named = _crash_fault_label(event.cwd, env, self_fault)
    except Exception as exc:  # noqa: BLE001 - a classification may never fail the allow
        print(
            f"keel: the crash carve-out's fault classifier failed, so this "
            f"fault is reported as unattributed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        fault_kind, named = "unknown", ""
    named_note = f" {named}" if named else ""
    try:
        print(
            f"keel: LEDGER WRITE PERMITTED THROUGH A FAILED GATE ({targets}): the "
            f"gate could not evaluate ({detail}), and .keel/plans/ is the one "
            f"directory a crash may not freeze - the session has to be able to "
            f"record this. Source stays refused. The plan contract was NOT "
            f"asserted on this write.{named_note}",
            file=sys.stderr,
        )
    except Exception:  # noqa: BLE001 - a notice may never fail the gate
        pass
    try:
        if policy_present(event.cwd):
            append_audit(
                event.cwd,
                {
                    "event": "crash_ledger_write",
                    "gate": "internal_error_ledger",
                    "kind": event.kind,
                    "tool": event.tool_name,
                    "session": event.session_id,
                    "detail": {
                        "targets": targets,
                        "fault": detail,
                        # T206 accept 4: a module defect and a configuration or
                        # file-state fault owe two different repairs, so the
                        # record says which - "unknown" when neither classifier
                        # could name it, never a guess.
                        "fault_kind": fault_kind,
                    },
                },
            )
        else:
            print(
                "keel: no crash_ledger_write audit line was written - the "
                "session's own directory carries no arming file, so there is no "
                "log to file it in. This notice is the whole record.",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: crash_ledger_write audit failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    return allow(
        "gate could not evaluate; .keel/plans/ stays writable so the freeze can "
        "be recorded (plan contract NOT asserted)",
        gate="internal_error_ledger",
    )


#: THE SENTENCES BOTH GATES SAY, DEFINED ONCE (T204 accept 2). ``keel_stop``
#: IMPORTS these instead of restating them, so the two gates cannot describe
#: one condition two ways: drift is structurally impossible here rather than
#: merely detectable by a test that someone has to remember to write. The two
#: ``{fault}`` templates are filled with ``str.format``, never with ``%`` or an
#: f-string over the template, so a brace inside a fault text is data.
#:
#: WHAT IS DELIBERATELY NOT SHARED, named rather than left out silently:
#: - the HEAD sentence, because each gate says what IT could not do ("could not
#:   evaluate this request" against "could not account for the session"),
#: - the ARMED note, because one is about a path's project and the other about
#:   a session's governing project,
#: - ``ledger_note`` below, because the crash carve-out it describes is this
#:   gate's and a Stop writes nothing.
SELF_FAULT_ATTRIBUTION = (
    "THE FAULT IS KEEL'S OWN, NOT THIS PROJECT'S CONFIGURATION: {fault}. "
    "keel's own source raised it, so either its module state is inconsistent "
    "or it mishandled this payload; either way the repair is in keel's own "
    "source and this project's configuration is not involved."
)
NEXT_STEP_SELF_FAULT = (
    "NEXT STEP: keel's hooks must be restored from git, and the policy lock "
    "refuses a shell command naming that directory - so this needs the user's "
    "hand from outside the session, exactly as it did three times on "
    "2026-08-19. Land the replacement as ONE write of the complete file: a "
    "multi-location edit applied across two tool calls is what leaves this "
    "state. Do not patch on top of it."
)
ARMING_FILE_IS_THE_FAULT = "THE ARMING FILE IS THE FAULT: {fault}."
NEXT_STEP_ARMING_FILE = (
    "NEXT STEP: fix .keel/keel-policy.md as named above - the refit skill "
    "(/keel:refit) puts the user's hand on it - or have the USER set "
    "KEEL_GATE=off to stand the gate down deliberately."
)
ARMING_FILE_IS_NOT_THE_FAULT = (
    "THE ARMING FILE IS NOT THE FAULT: it read and parsed cleanly, so do not "
    "edit this project's configuration on the strength of this message. keel "
    "could not attribute the fault to its own source either; report it as "
    "quoted above."
)
NEXT_STEP_FAULT_UNATTRIBUTED = (
    "NEXT STEP: quote the fault verbatim to the user. Only the USER can set "
    "KEEL_GATE=off to stand the gate down deliberately."
)

#: THE FOURTH SHAPE (T206): a ``GateError`` whose cause is not the arming file
#: at all but this session's own ENVIRONMENT - today, only
#: ``KEEL_PLAN_TTL_MIN``. Deliberately NOT one of the six sentences above and
#: NOT imported by ``hooks/keel_stop.py``: the stop gate never reads this
#: variable, so it has no shape here to misreport and nothing to import.
#: Naming the variable, never the arming file, is the whole point - before
#: T206 this fault fell through to ``ARMING_FILE_IS_NOT_THE_FAULT`` and left an
#: operator's typo looking like an unattributable mystery.
ENV_CONFIG_IS_THE_FAULT = (
    "THIS SESSION'S ENVIRONMENT IS THE FAULT: {fault}. That is an operator "
    "configuration error - not keel's own defect, and the arming file is not "
    "involved either."
)
NEXT_STEP_ENV_CONFIG = (
    "NEXT STEP: correct the environment variable named above to the shape "
    "keel expects, or unset it to use keel's default, or have the USER set "
    "KEEL_GATE=off to stand the gate down deliberately."
)

#: Which NEXT STEP applies for each source ``_crash_fault_label`` can name.
_NEXT_STEP_BY_SOURCE: dict[str, str] = {
    "self": NEXT_STEP_SELF_FAULT,
    "policy": NEXT_STEP_ARMING_FILE,
    "env": NEXT_STEP_ENV_CONFIG,
}


def _crash_fault_label(
    root: Path, env: Mapping[str, str], self_fault: str
) -> tuple[str, str, str]:
    """(fault_kind, source, named_sentence) for one crashed evaluation - the
    ONE place the three classifiers are asked, in this order, so a deny
    (``cannot_evaluate_message``) and an allow past the ledger carve-out
    (``_permit_crash_ledger_write``, T206) can never describe the same fault
    two different ways.

    ``fault_kind`` is the coarse split T206 accept 4 asks the audit line for:
    ``"module"`` (keel's own source; the repair is a git restore),
    ``"configuration"`` (the project's arming file or this session's
    environment; the repair is the adopter's), or ``"unknown"`` (neither
    classifier could name it). ``source`` selects the NEXT STEP that applies -
    ``"self"``, ``"policy"``, ``"env"``, or ``""`` for unknown.
    ``named_sentence`` is the fully worded, already-formatted attribution -
    ``""`` for unknown, where ``cannot_evaluate_message``'s own fourth shape
    takes over. Never raises: every classifier it calls is documented not to.
    """
    if self_fault:
        return "module", "self", SELF_FAULT_ATTRIBUTION.format(fault=self_fault)
    config_fault = policy_parse_fault(root)
    if config_fault:
        return "configuration", "policy", ARMING_FILE_IS_THE_FAULT.format(fault=config_fault)
    env_fault = plan_ttl_fault(env)
    if env_fault:
        return "configuration", "env", ENV_CONFIG_IS_THE_FAULT.format(fault=env_fault)
    return "unknown", "", ""


def cannot_evaluate_message(
    event: KeelEvent, root: Path, detail: str, self_fault: str, env: Mapping[str, str]
) -> str:
    """The fail-closed refusal, blaming what is actually broken.

    FOUR SHAPES, chosen by evidence rather than by assumption - three from
    T179 accept 2, the fourth added by T206:

    1. KEEL'S OWN DEFECT. ``gate_self_fault`` recognised this module's state
       as the fault, so the message says so, names the file and line that
       raised it, and gives the repair that applies. ``.keel/keel-policy.md``
       is not mentioned at all, because it is not the subject.
    2. THE PROJECT'S CONFIGURATION. ``policy_parse_fault`` shows the arming
       file genuinely does not read, so it is named WITH the reason - which the
       old single message never carried, so the session was told to fix a file
       without being told what was wrong with it.
    3. THE SESSION'S ENVIRONMENT (T206). ``plan_ttl_fault`` shows
       ``KEEL_PLAN_TTL_MIN`` genuinely does not parse. Asked only once the
       arming file has been cleared, so a project whose file AND whose
       environment are both broken still gets the file named first - the
       file is what an adopter is more likely to be able to fix, and shape 2's
       test for "no keel-policy.md string when it read cleanly" must stay true
       here too.
    4. NEITHER, SAID PLAINLY. Something else failed, the arming file read
       cleanly, and the environment parsed too. The fault is reported verbatim
       and the message states that the arming file is NOT the cause - silence
       there is what let a reader assume the old sentence still applied.

    "KEEL GATE FAILED CLOSED" leads every shape: the direction is a promise of
    its own, pinned by the kernel suite and by
    ``tests/fixtures/gate/20-unreadable-tier-fails-closed.json``, and it is
    about what the gate DID, never about whose fault it was.
    """
    armed_note = (
        "This project is armed, so the request is refused rather than waved "
        "through (R3)."
        if policy_present(root)
        else "keel could not attribute this path to any project, which counts as "
        "armed here - an arming file the walk never reached could govern it - so "
        "the request is refused rather than waved through (R3)."
    )
    head = f"KEEL GATE FAILED CLOSED: the gate could not evaluate this request ({detail})."
    ledger_note = (
        "NOTE: .keel/plans/ is still writable, so this can be recorded in the "
        "session ledger. Nothing else is."
    )
    # THE ARMING FILE IS NOT NAMED UNLESS IT IS GENUINELY THE FAULT, and that
    # is a testable rule rather than a matter of tone: shapes 1, 3 and 4 below
    # do not contain the string at all, so ``tests/test_keel_gate_self_
    # preflight_t179.py`` can assert its absence. Exonerating it BY NAME would
    # read as naming it to a reader skimming for a filename to open, which is
    # the failure mode - so shape 4 says "the arming file" in prose instead.
    _kind, source, named = _crash_fault_label(root, env, self_fault)
    if source:
        return _joined(head, armed_note, named, _NEXT_STEP_BY_SOURCE[source], ledger_note)
    return _joined(
        head,
        armed_note,
        ARMING_FILE_IS_NOT_THE_FAULT,
        NEXT_STEP_FAULT_UNATTRIBUTED,
        ledger_note,
    )


def _cannot_evaluate(
    event: KeelEvent, env: Mapping[str, str], detail: str, self_fault: str
) -> KeelVerdict:
    """The whole failure policy in one place, and the ORDER IS the policy.

    1. THE KILL SWITCH STILL ANSWERS. Every refusal below tells the user they
       may set ``KEEL_GATE=off`` deliberately; a preflight fault that ignored
       the switch would make that sentence a lie, and the switch is the only
       door left when the gate's own module is the broken thing. On the crash
       path ``evaluate`` has already answered this - asking twice costs a dict
       lookup and cannot disagree, because it is the same reader.
    2. THE LEDGER SURVIVES, BEFORE THE RESOLUTION IS ASKED ANYTHING. Deliberate
       ordering: the carve-out then depends on ``norm`` and a segment test
       only, not on the project walk that may itself be what failed. It is
       also the same answer either way - an unarmed event would be allowed
       below in any case. See ``crash_ledger_carve_out`` for the whole limit.
    3. FAIL CLOSED WHEN ARMED, OPEN WHEN UNARMED, on ``failure_policy_roots``.
    """
    try:
        if env_off("KEEL_GATE", env):
            print(
                f"keel: gate stood down by KEEL_GATE=off while it could not "
                f"evaluate: {detail}",
                file=sys.stderr,
            )
            return allow("kill switch KEEL_GATE=off", gate="kill_switch")
    except Exception as exc:  # noqa: BLE001 - reported, never silent
        print(
            f"keel: the KEEL_GATE switch could not be read either: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    if self_fault:
        print(f"keel: THE FAULT IS KEEL'S OWN: {self_fault}", file=sys.stderr)
    targets = crash_ledger_carve_out(event)
    if targets:
        return _permit_crash_ledger_write(event, env, targets, detail, self_fault)
    roots = failure_policy_roots(event)
    if not roots:
        print(f"keel: gate failed open (unarmed project): {detail}", file=sys.stderr)
        return allow("unarmed project; gate error ignored", gate="internal_error")
    # The project named is the one the refusal is filed with, so the crash lands
    # on the record of a project that is armed rather than in a directory that
    # never adopted keel.
    return deny(
        cannot_evaluate_message(event, roots[0], detail, self_fault, env),
        gate="internal_error",
        project=str(roots[0]),
    )


def run(event: KeelEvent, env: Mapping[str, str] | None = None) -> KeelVerdict:
    """Preflight, evaluate, apply the declared failure policy, audit blocks.

    THE PREFLIGHT RUNS FIRST, BEFORE ``evaluate`` IS TRUSTED. It is the check
    the principle at the top of this file was missing: R3 already said a guard
    that cannot evaluate must not pretend it approved, and the gate duly
    refused - but it never asked whether IT was the broken thing, so it named
    the adopter's arming file for its own half-applied edit.

    AND THE HANDLER HAS ITS OWN HANDLER. The double fault - the gate cannot
    evaluate AND cannot word the refusal - is the shape that reaches the
    session as an unhandled traceback, which is the one outcome worse than a
    bad message. It fails closed with a bare sentence, said in the fewest
    moving parts left.
    """
    env = os.environ if env is None else env
    try:
        faults = module_preflight()
        if faults:
            report = "; ".join(faults)
            verdict = _cannot_evaluate(
                event,
                env,
                f"the gate's own module state is inconsistent: {report}",
                f"module preflight: {report}",
            )
        else:
            try:
                verdict = evaluate(event, env)
            except Exception as exc:  # noqa: BLE001 - the failure policy lives here
                verdict = _cannot_evaluate(
                    event, env, f"{type(exc).__name__}: {exc}", gate_self_fault(exc)
                )
    except Exception as exc:  # noqa: BLE001 - the failure policy's OWN failure
        print(
            f"keel: the gate's failure policy failed too, so the refusal is the "
            f"bare one: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        verdict = KeelVerdict(
            decision="deny",
            reason=(
                f"KEEL GATE FAILED CLOSED: the gate could not evaluate this "
                f"request AND could not word the refusal "
                f"({type(exc).__name__}: {exc}). That is keel's own defect, not "
                f"this project's configuration. NEXT STEP: keel's hooks must be "
                f"restored from git by the USER, from outside this session."
            ),
            gate="internal_error",
        )
    if verdict.blocking:
        _audit(event, verdict)
    return verdict
