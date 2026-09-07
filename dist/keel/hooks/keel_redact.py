#!/usr/bin/env python3
"""keel shared redaction - the one place text becomes safe to record.

Four transformations, one gate. ``redact`` replaces this user's home
directory with ``~``; ``strip_private`` drops everything the author marked
``<keel-private>``; ``screen_home_shapes`` replaces any REMAINING home-shaped
path - another account's, or a spelling this user's own prefix cannot be
recovered from - with ``HOME_SHAPE_TOKEN``; ``screen_denied_names`` replaces
every name matching ``scripts/keel-denied-names.json`` with
``DENIED_NAME_TOKEN``. All four run on the way to any log, message or record,
and ``redact`` applies them in a fixed order - ``strip_private``, then the
home pattern, then the home-shape screen, then the denied-names screen; see
``redact``'s own docstring for why that order is the contract, not an
accident. A caller that follows convention 5 gets every exclusion whether or
not it knew about it: marked content, a home directory in any spelling, and a
registered name therefore cannot reach the audit log, the observation queue, a
knowledge record or an injected line - each is removed or replaced before the
write, not scrubbed afterwards.

Contract
--------
Reads   : the environment, and only to resolve THIS user's home directory:
          ``USERPROFILE``, ``HOME``, ``os.path.expanduser("~")``, plus the
          Windows 8.3 short form of each - obtained from the same Win32 call
          Windows itself uses to generate one (``GetShortPathNameW``), and,
          where the platform declines to answer, DERIVED from the account
          segment that call was asked about (``eight_three_names``) - plus the
          MSYS / Git-Bash translation of each of those
          (``/c/Users/<account>``), which is the spelling a ``bash`` tool call
          prints on Windows and the one no absolute-prefix pattern would
          otherwise see. Every one of those spellings is computed FROM the
          resolved home directory at run time; no account name is hardcoded,
          guessed, or written into this file. No other environment value is
          read. Also reads ``scripts/keel-denied-names.json`` once, at
          import: the SHA-256 register a candidate name is checked against.
          This module never comes to hold a denied name itself, only hashes
          of them, computed from the text it is asked to screen.
Emits   : values, never text. ``redact`` returns its argument with every
          ``<keel-private>`` block removed, every home-directory prefix
          replaced by ``~``, every remaining home-SHAPED path's account-name
          segment replaced by ``HOME_SHAPE_TOKEN``, and every token or
          adjacent word-pair matching
          the denied-names register replaced by ``DENIED_NAME_TOKEN``; a
          non-string argument is returned unchanged, and a value carrying
          none of the three is returned as the same string, unchanged, so
          the function can be applied to a whole record indiscriminately.
          ``redact_path`` additionally expresses a path relative to the
          project root.
Writes  : nothing. One stderr line is printed at most once per process if no
          home directory can be resolved at all, one more at most once per
          process if the denied-names register cannot be read, and one
          stderr line per value carrying an unclosed ``<keel-private>``
          marker (convention 7: never silent; R10).
Argv    : none. Library module, imported by every keel component that puts a
          path into a log, an audit line, a message or a record - which is
          what convention 5 ("redact before write") means in practice.

Exit codes
----------
None of its own.

Why this exists
---------------
An audit log tracked in git grows every session; a 2026-07-28 scrub found
real-username absolute paths through one in both the long form and the
Windows 8.3 short form. Redaction happens at write time,
here, rather than as a pre-push scan: a scan finds the leak after it is
already committed. ``scripts/keel_leak_check.py`` is the second line, not
the first.

THE PREFIX WAS NOT ENOUGH, and a 2026-08-10 scan of this repository's own
tracked logs is the evidence: ten ``home_path`` findings, in three shapes that
an absolute-prefix pattern is STRUCTURALLY unable to match, whoever calls it.
A truncated 8.3 path (a captured command line cut off mid-segment, leaving a
genuine prefix of the home directory and a complete spelling of nothing); the
MSYS form ``/c/Users/<name>/…`` that a ``bash`` tool call prints on Windows;
and ``../../Users/<name>/x``, what ``os.path.relpath`` makes of an absolute
home path before this module ever sees it - ``hooks/keel_gate.py``'s
``relativise`` produces exactly that, upstream of the write-time chokepoint.
Two of the three are answered precisely, by teaching ``home_candidates`` the
spellings (``msys_form`` alongside ``short_form``); the third cannot be
answered precisely by anything, because the prefix is gone from the text, so
it is answered honestly instead - ``screen_home_shapes`` refuses to emit an
account name it cannot express, and says so with ``HOME_SHAPE_TOKEN``.

AND THE PLATFORM DOES NOT ALWAYS HAND OVER THE SHORT FORM, which is the
2026-08-11 lesson and the reason ``eight_three_names`` exists. On 2026-08-11 an
account name reached both tracked capture files 28 times, in the MSYS spelling
and in the 8.3 spelling, through captured shell commands naming a session
scratchpad - a path the harness itself hands an agent already spelled 8.3, so no
amount of care by the author of the command could have avoided it. Both
spellings are matched here now; what the incident showed beyond them is that
``short_form`` is the only source of the 8.3 spelling and it is a source that can
FAIL - short-name generation is switchable per volume (``fsutil 8dot3name``), the
call answers nothing for a directory that does not exist, and it answers nothing
at all off Windows even when the text being screened came from Windows. A
redactor whose coverage of a whole spelling depends on an optional filesystem
feature is a redactor that leaks on the machine where the feature is off. So the
spelling is DERIVED from the account name as well as asked for: same rule
Windows applies, applied to a name this module reads at run time and never
holds. What that derivation cannot reach, and what is deliberately left to the
coarse screen instead, is enumerated at ``eight_three_names`` rather than left
for a reviewer to ask about.

AND THE LIST OF LEADS WAS NOT ENOUGH EITHER, which is the harder lesson and the
reason ``_HOME_SHAPE_ROOT_START`` is written as a complement rather than as an
enumeration. ``screen_home_shapes`` first shipped requiring a RECOGNISED
context before a home root - a drive letter, a UNC server, ``/c/``, a ``../``
chain - and each pass over this file closed the context that had been named and
left the property reachable by the next one. The shape that broke it was
``<drive>:\\<subfolder>\\Users\\<account>``: an ordinary backup or mirrored
drive, where the ``Users`` segment is preceded by a subfolder instead of the
drive. It arrives through ``hooks/keel_capture.py``, which hands ``redact`` RAW
captured shell-command text - unconstrained by anything keel built - and then
appends the result to both git-tracked records. That is the writer THIS
repository's real leak came through, so the rule is now a property of the text
rather than a catalogue of the paths anyone thought of: a home root is a home
root wherever it begins a path segment. What that costs, and why the cost is
the right way round, is argued at ``_HOME_SHAPE_RE``.

A second gap closed the same way: ``scripts/keel-denied-names.json`` records
names this repository does not print, hashed so the register itself carries
none of them. Until ``screen_denied_names`` existed, that register was
consulted only by ``scripts/keel_checks.py --names``, a scan that runs after
a write. ``.keel/knowledge/denied-names-are-guarded-only-by-the-scan.md``
records a session that broke the rule three times by SEARCHING for a name -
never authoring one - because the capture layer recorded the search term
itself, and a second contamination came from an executor grepping the first
one to investigate it. ``screen_denied_names`` closes that gap at the same
place the home directory is closed: here, before the write, not in a second
scan.

Performance
-----------
This runs on every captured line, so nothing here is rebuilt per call: the
token pattern is compiled once at import (``_TOKEN_RE``, alongside
``_PATTERN``), and the register is read and hashed once at import
(``_DENIED_HASHES``), never re-read from disk per invocation. Each line is
tokenised exactly once; ``_screen_segment`` reuses that single pass for both
the per-word and the per-adjacent-pair hash test rather than scanning the line
twice, and ``_screen_line`` adds one substring test (``DENIED_NAME_TOKEN in
line``) ahead of it, which is a C-level scan and the only cost a line with no
sentinel in it pays for the idempotence guarantee. A value carrying no denied
name still costs one regular-expression pass per line - proving an absence
takes a full scan wherever the scan runs; this only moves that cost earlier,
from once over the whole tracked tree in ``keel_checks --names`` to once per
captured line here.

THE HOME PATTERN GREW BRANCHES AND DID NOT GROW COST, which is the one thing to
know before adding a spelling to ``home_candidates``. Every spelling is one more
alternative the engine would try at every position of every line, so teaching it
the derived 8.3 forms took the branch count from four to eighteen on this
machine and the per-line cost from 2.2 to 12.7 microseconds - a regression paid
by every captured line, to catch a shape that appears in a few of them.
``_alternation`` gives it back by factoring the shared leading text of the
spellings into a trie (2.0 microseconds, measured the same way, on this
repository's own captured command lines), so the count of spellings is now a
construction-time cost paid once per process rather than a per-line one. A
future spelling should be added the same way: to ``home_candidates``, never as a
second pattern.

``screen_home_shapes`` adds exactly one more pass of that kind, over the whole
value rather than line by line: one compiled ``re.sub`` (``_HOME_SHAPE_RE``,
compiled at import beside the other two), which returns its ARGUMENT
unchanged - the same object, not a copy - when nothing matched, so a value
carrying no home-shaped path pays one scan and allocates nothing. The
alternative considered and rejected was a cheap substring gate
(``"users" in value.casefold()``) ahead of the regex: casefolding allocates a
copy of every line to save a scan that is already a C-level scan, which is the
wrong trade at this volume.

WHAT THAT COSTS NOW THAT THE CHOKEPOINT IS UNCONDITIONAL: every audit line
and every queue line is tokenised, where before only the lines whose caller
remembered to redact were. The count of lines did not change and neither did
the number of times any one string is screened - a caller that already
redacted is not screened twice over, it is screened once more over text that
no longer matches anything - but the two writers that never redacted at all
(``keel_gate.py``, ``keel_stop.py``, and ``keel_hook.py``'s spike line) now
pay the same per-line cost the others always did. That cost is one regex pass
plus one substring test per line of each string field, on a line already fully
built in memory, with no I/O and no re-read of the register.

``redact_value``/``redact_mapping`` add one more cost, paid once more now
that ``keel_events._append_jsonl`` calls them on every audit and queue line
rather than leaving it to caller convention: a walk over the entry's own
shape (its dict keys and any nested dict or list), not a second text scan -
each string it finds still only ever passes through ``redact`` the one time
this module already costs. The line was already fully built in memory before
this call; the walk adds no I/O and no additional read of the register or
the environment.

The private marker (R10)
------------------------
``<keel-private>…</keel-private>`` marks content that must never be recorded.
The parser is deliberately generous about the tag and strict about the
content: the marker matches case-insensitively in either tag, tolerates
attributes and internal whitespace, spans newlines, and handles any number of
blocks. An opening marker with NO close is not a syntax error to shrug at -
it drops the whole remainder of the value AND prints one visible stderr line,
because the failure mode being designed against is a typo that quietly
publishes a secret while looking like it worked. The eight cases that pin
this behaviour ship as ``tests/fixtures/private/*.json``.

Failure policy
--------------
FAIL-OPEN. Redaction is a transformation on the way to a log, and a log that
cannot be written is worse than a log with a path in it: an unresolvable
home directory, a Win32 call that does not answer, or a value of an
unexpected type all yield the value unchanged rather than an exception. The
one thing that never happens silently is a completely unresolvable home -
that prints a single stderr line, because a redactor that is quietly doing
nothing is the leak. WHAT THAT DEGRADED STATE COSTS IS NOW SMALLER THAN THE
WARNING SUGGESTS, and the warning is kept anyway: ``screen_home_shapes`` needs
no environment at all, so a machine where no home resolves still marks every
``…/Users/<name>/…`` it is asked to record. It loses the ``~`` and keeps the
username out, which is the half worth keeping. The private marker fails the
other way on purpose: when
the marker is malformed the content is DROPPED, not passed through, because
"fail open" applied to an exclusion would publish exactly what the author
asked keel to withhold. ``tests/test_keel_wave2.py`` asserts this
declaration.

The denied-names screen fails open the identical way, deliberately, for the
identical reason: a project may ship no register at all, or one that is
malformed, and a redactor that raises on that is a redactor a hook cannot
call. ``load_denied_hashes`` returns ``None`` on an absent file, unreadable
JSON, or a document that is not ``{"hashes": [...strings...]}``, and
``screen_denied_names`` treats ``None`` as "screen nothing" - but never
silently: the one condition that never happens without a word said about it
is the register being unreadable, which prints the fixed sentence
``DENIED_NAMES_UNREADABLE_WARNING`` on stderr, once per process, matching the
home-directory guarantee above rather than inventing a second failure
vocabulary. Silently screening nothing is the shape this project has already
found and rejected once in the audit log itself; this module does not repeat
it.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network. Matching is case-insensitive by default (convention 3, R1): Windows
paths are case-insensitive, and a case-sensitive redactor would miss
``c:\\users\\...`` written by any tool that lowercased it.  [keel-leak: ignore - example of the lowercased spelling this module must match]
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

#: What a home-directory prefix is replaced with.
HOME_TOKEN = "~"

#: Characters that may not immediately follow a home match. Without this
#: boundary "…/<account>2/x" would be redacted as "~2/x", inventing a
#: path that never existed. Written as a placeholder rather than as the
#: account name this comment used to carry: a module about not recording
#: usernames may not record one in its own source (see the note in
#: ``short_form``, repaired the same way and for the same reason).
_BOUNDARY = r"(?![A-Za-z0-9_])"

#: The marker keel recognises for content that must never be recorded.
PRIVATE_TAG = "keel-private"

#: A complete block. Non-greedy, so two blocks in one value are two blocks and
#: not one block swallowing the text between them; DOTALL, so a marked region
#: may span lines; IGNORECASE, because convention 3 is the default and a
#: case-sensitive exclusion is an exclusion that fails on <KEEL-PRIVATE> (R10).
_PRIVATE_BLOCK_RE = re.compile(
    r"<\s*" + PRIVATE_TAG + r"\b[^>]*>.*?<\s*/\s*" + PRIVATE_TAG + r"\s*>",
    re.IGNORECASE | re.DOTALL,
)

#: An opening marker. Whatever this matches AFTER the complete blocks are gone
#: is an unclosed marker: the remainder of the value is dropped and said so.
_PRIVATE_OPEN_RE = re.compile(r"<\s*" + PRIVATE_TAG + r"\b[^>]*>", re.IGNORECASE)

#: What the unclosed-marker warning says. A constant so the test asserts the
#: same string the user sees.
UNCLOSED_PRIVATE_WARNING = (
    f"unclosed <{PRIVATE_TAG}> marker: everything after it was dropped, not recorded"
)

#: Messages already printed by ``_warn_once``, this process. A set rather
#: than a single flag: the home directory and the denied-names register are
#: two independent degradations, and the first one to fire must not silence
#: the second - each distinct message earns its own one-time line.
_WARNED: set[str] = set()


def _warn_once(message: str) -> None:
    """Report a degraded redactor exactly once per process per message."""
    if message not in _WARNED:
        _WARNED.add(message)
        print(f"keel: {message}", file=sys.stderr)


def strip_private(value: Any) -> Any:
    """Remove every ``<keel-private>`` region from ``value`` (R10).

    Non-strings pass through unchanged, like every function here. A value with
    no marker at all is returned untouched after one casefolded substring
    test, so the common case costs no regular expression at all.

    An unclosed opening marker truncates the value at the marker and prints
    one line on stderr - once per value, not once per process: two different
    malformed values are two different mistakes, and collapsing them would
    hide the second one.
    """
    if not isinstance(value, str) or PRIVATE_TAG not in value.casefold():
        return value
    cleaned = _PRIVATE_BLOCK_RE.sub("", value)
    unclosed = _PRIVATE_OPEN_RE.search(cleaned)
    if unclosed is not None:
        cleaned = cleaned[: unclosed.start()]
        print(f"keel: {UNCLOSED_PRIVATE_WARNING}", file=sys.stderr)
    return cleaned


#: The token every screened denied name becomes. Matches the style already
#: used when this rule was last enforced by hand - see
#: ``.keel/knowledge/denied-names-are-guarded-only-by-the-scan.md``, which
#: records six lines repaired with this exact marker - rather than inventing
#: a new one.
DENIED_NAME_TOKEN = "[denied-name]"

#: Where the denied-names register ships, relative to the installation root
#: (the directory holding this file's own parent, ``hooks/``) - never the
#: caller's cwd or a project directory. The register is a keel component,
#: like ``scripts/keel-features.json``, not project data.
_DENIED_NAMES_RELPATH: tuple[str, ...] = ("scripts", "keel-denied-names.json")

#: A denied-name candidate: one run of letters, digits and internal hyphens.
#: Matches ``check_vendor_names``'s own tokenisation in
#: ``scripts/keel_checks.py`` exactly, so a name that would flag that scan is
#: the same name this screen catches before the scan ever runs. Compiled once
#: at import, alongside ``_PATTERN`` - see "Performance" above.
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")

#: What the degraded-register warning says. A constant, like
#: ``UNCLOSED_PRIVATE_WARNING`` above, so a test can assert the exact
#: sentence rather than a message that varies with the underlying exception.
DENIED_NAMES_UNREADABLE_WARNING = (
    "denied-names register could not be read: names are not screened"
)


def _install_root() -> Path:
    """The directory holding ``hooks/`` and ``scripts/``.

    Derived from this file's own location, never a caller's cwd - the same
    reasoning ``hooks/keel_features.py:install_root`` uses, not imported here
    so this module keeps its own standard-library-only dependency graph.
    """
    return Path(__file__).resolve().parent.parent


def load_denied_hashes(path: Path | str | None = None) -> frozenset[str] | None:
    """The denied-names register as a set of lowercase-token digests, or None.

    ``path`` defaults to this installation's own
    ``scripts/keel-denied-names.json``; a caller may pass another path, which
    is how the tests prove this function without the register ever holding a
    name this repository forbids - they hash an ordinary word into a register
    of their own instead.

    An absent file, unreadable JSON, or a document that is not
    ``{"hashes": [...strings...]}`` all resolve to ``None`` - UNDECIDABLE,
    not "no names registered" - because treating "the register vanished" the
    same as "the register lists nothing" is a screen silently doing nothing,
    the shape this project has already found and rejected once (see the
    module docstring's Failure policy). ``None`` tells ``screen_denied_names``
    to fail open exactly the way a missing home directory does: nothing is
    screened, and ``DENIED_NAMES_UNREADABLE_WARNING`` is printed on stderr
    once per process, never silently.
    """
    target = _install_root().joinpath(*_DENIED_NAMES_RELPATH) if path is None else Path(path)
    try:
        document = json.loads(target.read_text(encoding="utf-8"))
        hashes = document["hashes"]
        if not isinstance(hashes, list) or not all(isinstance(h, str) for h in hashes):
            raise TypeError("'hashes' must be a list of strings")
        return frozenset(hashes)
    except (OSError, ValueError, KeyError, TypeError):
        _warn_once(DENIED_NAMES_UNREADABLE_WARNING)
        return None


#: The register, read and hashed once at import - never re-read from disk on
#: a call to ``redact``. See "Performance" in the module docstring.
_DENIED_HASHES = load_denied_hashes()


def _digest(token: str) -> str:
    """sha256 hex digest of a casefolded token - the register's own algorithm."""
    return hashlib.sha256(token.casefold().encode("utf-8")).hexdigest()


def _screen_segment(segment: str, hashes: frozenset[str]) -> str:
    """One stretch of a line, denied tokens replaced, everything else untouched.

    Tokenised exactly once; that single pass is reused for both the per-word
    and the per-adjacent-pair hash test, so nothing here scans the segment
    twice. A segment with no hit is returned as the SAME string object, so a
    caller can tell "nothing changed" without a second comparison.
    """
    matches = list(_TOKEN_RE.finditer(segment))
    if not matches:
        return segment
    hit = [False] * len(matches)
    for i, match in enumerate(matches):
        if _digest(match.group()) in hashes:
            hit[i] = True
        if i + 1 < len(matches):
            pair = f"{match.group().casefold()} {matches[i + 1].group().casefold()}"
            if _digest(pair) in hashes:
                hit[i] = True
                hit[i + 1] = True
    if not any(hit):
        return segment
    pieces: list[str] = []
    cursor = 0
    for i, match in enumerate(matches):
        if hit[i]:
            pieces.append(segment[cursor : match.start()])
            pieces.append(DENIED_NAME_TOKEN)
            cursor = match.end()
    pieces.append(segment[cursor:])
    return "".join(pieces)


def _screen_line(line: str, hashes: frozenset[str]) -> str:
    """One line of a value, screened AROUND any sentinel already in it.

    THE SENTINEL IS RESERVED, and that is what makes double screening
    idempotent BY CONSTRUCTION rather than by luck. ``DENIED_NAME_TOKEN``
    contains a word (``denied-name``) that ``_TOKEN_RE`` recognises exactly as
    it recognises any other, so a screen that simply re-tokenised its own
    output would substitute inside its own substitution the moment a register
    happened to hold that word's digest, or the digest of a pair ending in it:
    one pass yields ``[denied-name]``, the next ``[[denied-name]]``, and the
    line grows on every pass. The write-time chokepoint in
    ``keel_events._append_jsonl`` re-screens lines that a caller may already
    have screened, so "idempotent unless the register says otherwise" is not
    good enough there - the register is data, and a guarantee that depends on
    which digests it happens to carry is not a guarantee.

    So the line is split on the sentinel, each stretch BETWEEN sentinels is
    screened on its own, and the sentinels are put back untouched. Text
    already occupied by one is never a candidate again, and a sentinel also
    breaks adjacency, so no pair can form across it. The adjacency half costs
    nothing at all: ``denied-name`` sat between the two halves of any such
    pair already, so a pair could never span a sentinel even before this. The
    candidate half gives up exactly one thing - screening the sentinel's own
    text, wherever it appears, including where a human typed it rather than
    this function - and only a register forbidding ``denied-name`` itself
    would ask for that. Such a register cannot be honoured by a substitution
    spelled with the very word it forbids, so termination is the better answer
    there than an unbounded rewrite.

    The common case pays one substring test (``in``) per line and nothing
    else: a line with no sentinel goes straight to ``_screen_segment``, and a
    line where nothing matched is returned as the SAME string object.
    """
    if DENIED_NAME_TOKEN not in line:
        return _screen_segment(line, hashes)
    parts = line.split(DENIED_NAME_TOKEN)
    screened = [_screen_segment(part, hashes) for part in parts]
    if screened == parts:
        return line
    return DENIED_NAME_TOKEN.join(screened)


def screen_denied_names(value: Any) -> Any:
    """Replace every registered name in ``value`` with ``DENIED_NAME_TOKEN``.

    A non-string is returned unchanged, like every other public function in
    this module: this one is named in the module contract, so a caller may
    reach it directly, and a redactor that raises ``AttributeError`` on a
    ``None`` field would be a redactor a hook cannot call - the fail-open
    policy at the top applies to the screen's own entry point too, not only
    to ``redact``'s.

    A value carrying no registered name is returned as the SAME string
    object it was given - the byte-identical guarantee this screen exists to
    keep; a screen that quietly reshaped ordinary text would corrupt every
    record in the project. Screening an already-screened value is a no-op for
    the same reason and by construction, not by coincidence: see
    ``_screen_line`` on why the sentinel is reserved.

    Processed one line at a time (``str.splitlines(keepends=True)``, rejoined
    with nothing added or dropped), so a two-word name is only caught when
    both words share a line - exactly how ``check_vendor_names`` reads the
    tracked tree it scans, so a name that reaches that scan is a name this
    screen already would have caught. A name glued to other characters by a
    hyphen is one token to both, and so out of scope for both.

    Fails open when the register did not load: ``hashes`` falsy means
    nothing is screened, and that condition already printed its one stderr
    line from ``load_denied_hashes`` - this function stays silent about it a
    second time on purpose, so a caller does not see the same warning once
    per captured line.
    """
    hashes = _DENIED_HASHES
    if not isinstance(value, str) or not hashes:
        return value
    lines = value.splitlines(keepends=True)
    screened = [_screen_line(line, hashes) for line in lines]
    if screened == lines:
        return value
    return "".join(screened)


def short_form(path: str) -> str | None:
    """Windows 8.3 short form of ``path``, or None when there is not one.

    Derived from the Win32 API that generates these names in the first
    place, so ``C:\\Users\\<ACCOUNT>~1.<SFX>`` is discovered rather than
    guessed. Returns None on every other platform and on any failure at all.

    The example is a PLACEHOLDER, and deliberately so: this docstring used to
    spell out this machine's own 8.3 home directory, which is the exact thing
    the module exists to keep out of a tracked file. It was repaired here
    rather than reported and left, because it sits in this module's own source
    and the repair costs one word. THE FIRST REPAIR WAS PARTIAL: it masked the
    account portion and kept the real dot-suffix, the same defect one segment
    over - an 8.3 extension is derived from the account name too. A security
    review caught the leftover on 2026-08-11, and the suffix is now synthetic
    as well.
    """
    if os.name != "nt" or not path:
        return None
    try:
        import ctypes  # noqa: PLC0415 - Windows-only, imported where used

        buffer = ctypes.create_unicode_buffer(260)
        length = ctypes.windll.kernel32.GetShortPathNameW(path, buffer, 260)
        if 0 < length <= 260:
            return buffer.value
        if length > 260:
            buffer = ctypes.create_unicode_buffer(length)
            if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, length):
                return buffer.value
    except Exception:  # noqa: BLE001 - fail open; a missing short form is not an error
        return None
    return None


def msys_form(path: str) -> str | None:
    """MSYS / Git-Bash spelling of a Windows path, or None when there is none.

    ``C:\\Users\\<account>`` -> ``/c/Users/<account>``. Not cosmetic variance: it
    is what a ``bash`` tool call PRINTS on Windows, so it is the spelling that
    actually reaches a captured command line, and the literal
    ``USERPROFILE`` prefix is nowhere in it. Recognising it here means the
    user's own home still collapses to ``~`` in that spelling rather than
    falling through to the coarser marker below.

    Drive-letter paths only, and no I/O: a value that is not ``<letter>:`` plus
    a remainder answers None, on every platform, because a translation nothing
    ever emits is one more alternative for every line to be matched against.
    """
    if len(path) < 3 or path[1] != ":" or not path[0].isalpha():
        return None
    rest = path[2:].replace("\\", "/").lstrip("/")
    return f"/{path[0].lower()}/{rest}" if rest else None


#: Characters Windows KEEPS when it generates an 8.3 short name. Everything
#: else is DROPPED rather than substituted - the space and the embedded period
#: above all, which is why ``Given Family`` and ``given.family`` shorten to the
#: same six letters. Written as the set to keep rather than the set to remove,
#: for the reason argued at ``_HOME_SHAPE_ROOT_START``: a list of what to strip
#: fails open on the character nobody thought of, and this one fails closed.
_EIGHT_THREE_KEEP_RE = re.compile(r"[^A-Za-z0-9_^$~!#%&{}@'()\-]")

#: How many collision ordinals to derive. Windows numbers the first four
#: colliding names ``~1``..``~4``; from the fifth it stops counting and puts a
#: four-hex-digit hash of the long name into the base instead, which no rule
#: can derive from the account name - see ``eight_three_names`` on where that
#: residual goes.
_EIGHT_THREE_ORDINALS = range(1, 5)


def eight_three_names(name: str) -> list[str]:
    """The DOS 8.3 spellings of one path SEGMENT, derived from the name itself.

    ``short_form`` asks Windows for the short spelling of a whole path and is
    the better answer whenever it answers, because it reads what is actually on
    the volume. This is the answer for when it does not: 8.3 generation is a
    per-volume setting that can be off, the call is silent about a directory
    that does not exist, and it does not exist at all on the platforms that
    nonetheless have to screen text produced on Windows. The rule applied here
    is the one Windows applies - drop the characters 8.3 has no room for,
    uppercase, keep the first six of the base, append ``~`` and the collision
    ordinal, and keep the first three characters after the LAST period as the
    extension - so ``given.family`` yields ``GIVEN~1.FAM`` and, because the
    ordinal is unknowable from the name, ``GIVEN~2.FAM`` and its two successors
    as well.

    BOTH the extended and the bare spelling are returned when the name has a
    period in it (``GIVEN~1.FAM`` and ``GIVEN~1``), because a captured command
    line carries whichever one the tool that printed it produced, and a
    truncated one carries only the shorter. Ordering within this list does not
    decide which wins - ``home_candidates`` sorts every spelling longest-first
    for exactly that reason, so the extended form is offered to the pattern
    before the bare form that is its own prefix; without that sort ``~1`` would
    match and leave ``.FAM`` behind, which is a fragment of the name and so
    still the leak.

    An empty result is the right answer, not a failure, in two cases: a name
    that is already a legal 8.3 spelling (Windows shortens nothing, and the
    unshortened candidate already matches case-insensitively), and a name that
    already carries a ``~`` (it IS a short form - deriving the short form of a
    short form invents spellings the platform never generates).

    WHAT THIS CANNOT REACH, said here rather than left for a reviewer to ask:

    * The hashed base Windows switches to after four collisions
      (``GIVE1A2B~1``). It embeds a hash of the long name and cannot be derived
      from the name - it is covered by ``short_form`` on any machine where the
      volume answers, and by ``screen_home_shapes`` where it does not.
    * A shortened PARENT segment (``C:\\DOCUME~1\\<account>``). Only the final
      segment is derived here, because only the final segment carries the
      account name; ``short_form`` shortens the whole path where it answers.
    * A locale or codepage that maps a non-ASCII name to different 8.3 letters.
      The keep-set above is ASCII, so a non-ASCII name derives an empty or
      truncated stem, and the coarse screen is what covers it.

    Each of those is a spelling of a path that still contains a ``Users`` or
    ``home`` root, which is what makes leaving them to ``screen_home_shapes``
    an answer rather than a shrug: the account name comes out either way, and
    only the ``~`` is lost.
    """
    if not name or "~" in name:
        return []
    base, _, suffix = name.rpartition(".")
    if not base:
        base, suffix = name, ""
    stem = _EIGHT_THREE_KEEP_RE.sub("", base).upper()
    extension = _EIGHT_THREE_KEEP_RE.sub("", suffix).upper()[:3]
    if not stem or (not extension and stem == name.upper() and len(stem) <= 8):
        return []
    forms: list[str] = []
    for ordinal in _EIGHT_THREE_ORDINALS:
        shortened = f"{stem[:6]}~{ordinal}"
        if extension:
            forms.append(f"{shortened}.{extension}")
        forms.append(shortened)
    return forms


def _is_windows_path(path: str) -> bool:
    """True for a drive-letter or UNC path, on any platform.

    Decided from the SHAPE of the value rather than from ``os.name``, so a
    machine that is not Windows still recognises a Windows home directory it
    was handed - which is the case ``eight_three_names`` exists for.
    """
    return (len(path) > 1 and path[1] == ":" and path[0].isalpha()) or path.startswith("\\\\")


def _split_last_segment(path: str) -> tuple[str, str]:
    """``("C:\\Users\\", "<account>")`` - the parent, separator included, and the name.

    Either separator, because a home directory arrives spelled with whichever
    one the source used. An empty parent means there was no separator at all.
    """
    index = max(path.rfind("\\"), path.rfind("/"))
    if index < 0:
        return "", path
    return path[: index + 1], path[index + 1 :]


def home_candidates(env: Mapping[str, str] | None = None) -> list[str]:
    """Every home-directory spelling worth matching, longest first.

    Longest first matters: a shorter candidate that is a prefix of a longer
    one would otherwise win the regex alternation and leave the tail of the
    longer path - including a username - in the output. It is what keeps
    ``…\\<ACCOUNT>~1.FAM`` from matching as ``~`` plus a stray ``.FAM``, so it
    is load-bearing for ``eight_three_names`` and not merely tidy.

    Several spellings per source, not one, built in three passes in this order
    because each pass feeds the next:

    1. The value as the environment gives it, and its Windows 8.3 short form
       from ``short_form`` - the authoritative one, read off the volume.
    2. The 8.3 spellings DERIVED from the account segment of each Windows-shaped
       candidate (``eight_three_names``), which is what covers the machine
       where step 1 answers nothing: 8.3 generation switched off, a home
       directory that does not exist, or a platform with no such call at all.
       Both the extended and the bare form, since a command line may carry
       either.
    3. The MSYS / Git-Bash translation (``msys_form``) of everything above -
       LAST, so the translated spelling of a derived short form
       (``/c/Users/<ACCOUNT>~1.FAM``) is a candidate too. That is one of the two
       spellings that leaked on 2026-08-11, so the ordering here is the fix
       rather than an implementation detail.

    Every spelling is computed FROM the resolved home directory: the 8.3 forms
    from the same Win32 call Windows uses to generate one and from Windows' own
    shortening rule applied to the name that call was asked about, the MSYS form
    arithmetically from the drive letter. This function still learns the
    username from the environment alone and never guesses it.
    """
    env = os.environ if env is None else env
    raw: list[str] = []
    for value in (env.get("USERPROFILE"), env.get("HOME")):
        if value and value.strip():
            raw.append(value)
    try:
        expanded = os.path.expanduser("~")
        if expanded and expanded != "~":
            raw.append(expanded)
    except Exception:  # noqa: BLE001 - fail open
        pass
    for candidate in list(raw):
        short = short_form(candidate)
        if short:
            raw.append(short)
    for candidate in list(raw):
        if not _is_windows_path(candidate):
            continue
        parent, name = _split_last_segment(candidate)
        if parent:
            raw.extend(parent + form for form in eight_three_names(name))
    for candidate in list(raw):
        msys = msys_form(candidate)
        if msys:
            raw.append(msys)
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in raw:
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    unique.sort(key=len, reverse=True)
    return unique


#: One or more separators, either spelling - the atom every path separator in
#: a home spelling becomes. Argued at ``build_pattern``.
_SEPARATOR_ATOM = r"[\\/]+"


def _atoms(spelling: str) -> list[str]:
    """One home spelling as regular-expression atoms, one per character."""
    return [_SEPARATOR_ATOM if char in "\\/" else re.escape(char) for char in spelling]


def _emit(node: dict[str, Any]) -> str:
    """One trie node as a regular-expression fragment.

    Branches longest-atom-first, which puts the TERMINAL branch (the empty
    atom, length zero) last at every node that has one - so a spelling that is
    a prefix of another spelling is only matched after the longer one has been
    tried. That is the same longest-first rule ``home_candidates`` states, kept
    exactly where the shared prefix was factored out of it; without it
    ``…\\<ACCOUNT>~1`` would win against ``…\\<ACCOUNT>~1.FAM`` and leave a
    fragment of the account name in the output.

    Order among equal-length atoms is insertion order and does not matter: two
    atoms of equal length at the same node differ in their first character, so
    at most one of them can match at all.
    """
    if not node:
        return ""
    branches = [
        atom + _emit(child)
        for atom, child in sorted(node.items(), key=lambda item: len(item[0]), reverse=True)
    ]
    return branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"


def _alternation(spellings: list[str]) -> str:
    """Every spelling as ONE fragment, with common prefixes factored out.

    A flat ``a|b|c`` alternation costs the engine one attempt per branch at
    every position of every line, and this pattern runs on every captured line
    of every record. Teaching the pattern the 8.3 spellings multiplied the
    branch count, and the spellings overwhelmingly share their leading text -
    the drive, the ``Users`` segment, even the first six letters of the account
    name - so factoring the shared prefix into a trie returns a single literal
    head the engine can scan for. Measured on this repository's own captured
    command lines: 12.7 microseconds per line flat, 2.0 factored, against 2.2
    for the four-branch pattern this replaces. The cost of the new spellings is
    therefore paid in pattern-construction time, once per process, rather than
    per line.

    Semantically identical to the flat form, not merely close: the branches at
    each node are disjoint in their first character, and the terminal branch is
    ordered last (see ``_emit``), so the same alternative wins here as would
    win there. ``tests/test_keel_home_spellings.py`` asserts that equivalence
    over every spelling this machine actually produces rather than trusting the
    argument.

    Falls back to the flat form on ``RecursionError``: ``_emit`` recurses once
    per character of the longest spelling, and ``HOME`` is an environment
    variable a caller can set to anything at all. A pattern that is slower is a
    cost; an exception raised at import time in a module every hook imports is
    an outage, and this module's failure policy is to degrade rather than to
    raise.
    """
    root: dict[str, Any] = {}
    for spelling in spellings:
        node = root
        for atom in _atoms(spelling):
            node = node.setdefault(atom, {})
        node[""] = {}
    try:
        return _emit(root)
    except RecursionError:
        return "(?:" + "|".join("".join(_atoms(s)) for s in spellings) + ")"


def build_pattern(env: Mapping[str, str] | None = None) -> re.Pattern[str] | None:
    """The compiled home-prefix pattern, or None when no home resolves.

    Either separator matches wherever the recorded path used the other one,
    so a home resolved as ``C:\\Users\\x`` still matches ``C:/Users/x``.  [keel-leak: ignore - example of the separator spellings this pattern matches; this line carries two findings and one marker skips the line]

    ONE OR MORE of them, not exactly one: a path that has been through a JSON
    round trip and is being screened as TEXT carries its separators doubled
    (``C:\\\\Users\\\\x``), which is precisely the state ``keel_dashboard.py``  [keel-leak: ignore - example of the doubled-separator spelling]
    reads audit lines back in. ``_HOME_SHAPE_RE`` already tolerates the
    doubling for the same reason; before this the two disagreed, and the
    disagreement meant a doubled spelling of THIS user's own home fell past the
    precise step and was answered by the coarse one - the account name was
    still masked, but as ``[home-path]`` rather than as ``~``, losing the one
    fact redaction is meant to keep.
    """
    homes = home_candidates(env)
    if not homes:
        return None
    return re.compile(_alternation(homes) + _BOUNDARY, re.IGNORECASE)


_PATTERN = build_pattern()


#: Windows and macOS pseudo-accounts: a home-shaped path naming one of these
#: names no person. Mirrors ``scripts/keel_leak_check.py``'s own
#: ``RESERVED_HOME_NAMES`` deliberately - that scanner is the SECOND line of
#: defence behind this module, and two lines of defence that disagree about
#: what counts as a home path each pass what the other rejects.
RESERVED_HOME_NAMES = frozenset(
    {"public", "default", "default user", "all users", "defaultuser0", "guest", "shared"}
)

#: What a home-SHAPED path becomes when it is not this user's home in any
#: spelling ``_PATTERN`` can recognise. Spelled like ``DENIED_NAME_TOKEN``
#: rather than like ``HOME_TOKEN``, because it says something different: ``~``
#: is a claim ("this was YOUR home directory"), and this is an admission
#: ("a username stood here and could not be expressed safely, so it was not
#: expressed at all").
HOME_SHAPE_TOKEN = "[home-path]"

#: The account-name segment of a home-shaped path, in two branches tried in
#: order. The first allows a username with spaces in it (``John Smith``) but
#: only where a separator follows, so the match cannot run off the end of the
#: segment and eat the prose around it; the second is the single token, which
#: is what answers at the end of a TRUNCATED path - the shape that actually
#: leaked into this project's logs, where a captured command line was cut off
#: mid-path and the tail of the home directory went with it.
_HOME_SHAPE_NAME = (
    r"[^\s\\/:*?\"<>|]{1,80}(?: [^\s\\/:*?\"<>|]{1,80}){0,3}(?=[\\/])"
    r"|[^\s\\/:*?\"<>|]{1,80}"
)

#: What may NOT stand immediately before a home ROOT - and it is a COMPLEMENT
#: rule on purpose, which is the one design decision on this line worth
#: reading. Every earlier version of this screen enumerated what MAY stand
#: there: a drive letter, a UNC server, the MSYS ``/c/``, a ``../`` chain, a
#: separator at a token start. Four successive passes over this file each closed
#: the lead that had been named and left the property reachable by the next
#: spelling - most recently ``<drive>:\\<subfolder>\\Users\\<account>``, an
#: ordinary backup or mirrored-drive layout, which no enumerated lead covered
#: because the ``Users`` segment is preceded by a subfolder rather than by the
#: drive. LEADS ARE UNBOUNDED, so no list of them can be complete, and a screen
#: whose completeness depends on such a list is a screen that leaks on the next
#: shape somebody types.
#:
#: So this states the opposite thing, and states it exhaustively: ``Users`` or
#: ``home`` is a home root wherever it BEGINS A PATH SEGMENT, whatever precedes
#: that segment - a separator, a quote, a subfolder, the start of the value, a
#: newline, anything at all. The single disqualifier is a preceding word
#: character, which means the text is not a segment at all but the tail of a
#: longer word (``myUsers/x``, ``C:\\SomeUsers\\x``), so there is no home root
#: in it to screen. Spelled with the same character class ``_BOUNDARY`` uses at
#: the other end of a match, so both edges of this module's idea of "a segment"
#: are written once each and identically.
#:
#: WHY A COMPLEMENT CANNOT BE DEFEATED BY A NEW SPELLING, which is the property
#: the enumeration never had: this rule FAILS CLOSED on anything unforeseen. To
#: get past it the character immediately before the root must be a member of one
#: fixed character class; every other character there - every one
#: nobody thought of, on every platform - screens. The enumeration failed open
#: instead: anything not on its list passed. That is the whole difference, and
#: it is why the residual here is bounded and nameable rather than open-ended -
#: a directory whose name merely ENDS in ``users`` or ``home``
#: (``C:\\OldUsers\\<account>``) is a different directory name and is left to
#: ``scripts/keel_leak_check.py``, which does not see it either; that is stated
#: in ``tests/test_keel_home_shapes.py`` rather than left for a reader to find.
_HOME_SHAPE_ROOT_START = r"(?<![A-Za-z0-9_])"

#: The two root names this screen knows without being told, and the set
#: ``scripts/keel_leak_check.py`` enumerates as well. A home whose parent is
#: one of these is an ORDINARY home and adds nothing to the pattern - which is
#: why the common Windows and Linux machine gets a screen byte-identical to the
#: one before ``home_shape_siblings`` existed.
_HOME_SHAPE_KNOWN_ROOTS = frozenset({"users", "home"})


def home_shape_siblings(env: Mapping[str, str] | None = None) -> list[str]:
    """The running home's own basename, where its PARENT is not a known root.

    THE GAP THIS CLOSES, measured 2026-09-01 in a ``python:3.10-slim``
    container running as root: the screen recognised a home ROOT only as the
    segment ``Users`` or ``home``, so a home shaped otherwise matched nothing
    and was emitted byte for byte - with the account name in it. The failing
    assertion was ``'root' unexpectedly found in '/root2/x'``: a LONGER SIBLING
    of the running home, which is still somebody's home-shaped path. ``/root``
    is the ordinary case, because it is what ``docker run`` gives you by
    default. The primary redaction was never at risk (it is prefix-based on the
    real home and collapses this user's own home whatever its shape); it is the
    shape-based BACKSTOP, the one that catches OTHER home-shaped paths
    appearing in text, that was blind.

    WHAT THIS RETURNS: the home's own BASENAME, and only where the home's
    PARENT is not already a known root. So ``/root`` yields ``root`` and
    ``/var/lib/<svc>`` yields ``<svc>``, while ``/home/<name>`` and
    ``C:\\Users\\<name>`` yield NOTHING - the segment above those is already
    recognised, and the ordinary machine must keep the pattern it had.

    WHAT IT DELIBERATELY DOES NOT RETURN, because measurement rejected it: the
    PARENT's basename as a new home root. That was this fix's first shape -
    add ``lib`` as a root for a ``/var/lib/<svc>`` home - and it reads every
    ``lib`` segment anywhere as a homes directory. The cost was not
    hypothetical. It screened ``/usr/lib/<package>/x`` in ordinary captured
    command lines, and it broke ``tests/test_keel_compaction_t228.py``'s ledger
    test, whose sandbox puts the fixture home and the fixture project side by
    side under one temporary directory: the parent-as-root rule turned the
    PROJECT's own name into ``[home-path]`` in an audit line's ``cwd`` field.
    That field is how an event is attributed to a project, so the
    generalisation cost more than the leak it closed. A directory that merely
    CONTAINS a home is not a homes directory; ``/home`` and ``C:\\Users`` are,
    which is why exactly those two are named literally rather than derived.

    THE RESIDUE, stated rather than implied: a sibling of the home that does
    NOT share its basename - ``/var/lib/<other>`` beside ``/var/lib/<svc>``, or
    ``/alice`` beside ``/root`` - is not seen, because nothing in its text says
    it is a home. That is the same "below the floor" family ``_HOME_SHAPE_RE``
    already records, and it is left to ``scripts/keel_leak_check.py``.

    Read from the same three sources ``home_candidates`` reads and in the same
    order, un-embellished: no 8.3 or MSYS spellings, because a basename is not
    a path and those transformations do not change it. Learns nothing this
    module did not already know about the machine. A drive or UNC head is
    dropped before counting segments: ``C:`` names no directory, so
    ``C:\\Users\\<name>`` is a two-segment home whose parent is ``Users``.
    """
    env = os.environ if env is None else env
    raw: list[str] = []
    for value in (env.get("USERPROFILE"), env.get("HOME")):
        if value and value.strip():
            raw.append(value)
    try:
        expanded = os.path.expanduser("~")
        if expanded and expanded != "~":
            raw.append(expanded)
    except Exception:  # noqa: BLE001 - fail open, as everywhere in this module
        pass

    siblings: list[str] = []
    for value in raw:
        segments = [segment for segment in re.split(r"[\\/]+", value.strip()) if segment]
        if segments and re.fullmatch(r"[A-Za-z]:", segments[0]):
            segments = segments[1:]
        if not segments:
            continue
        parent = segments[-2] if len(segments) >= 2 else ""
        if parent.casefold() in _HOME_SHAPE_KNOWN_ROOTS:
            continue
        name = segments[-1]
        if name not in siblings:
            siblings.append(name)
    return siblings


#: A home-shaped path: a home root beginning a path segment, then an account
#: name. Anchored on the ROOT rather than on this user's home PREFIX, which is
#: what lets it see the shapes ``_PATTERN`` structurally cannot - another
#: account's home in any spelling, a relativised path (``../../Users/<account>``),
#: a redirected or mirrored profile root (``D:\\Backup\\Users\\<account>``), and a
#: path TRUNCATED mid-segment (``C:\\Users\\<ACCOUNT>~1.``), where what remains is
#: a genuine prefix of a home directory and a complete spelling of nothing.
#:
#: ``[\\/]+`` rather than ``[\\/]`` after the root, because a path stored in
#: JSONL and read back as TEXT carries its separators doubled
#: (``C:\\\\Users\\\\<account>``), and ``keel_dashboard.py`` re-screens exactly
#: such lines.
#:
#: WHAT IS NOT HERE, and was: a ``lead`` group consuming the separators BEFORE
#: the root so the replacement could put them back. It is gone because the match
#: no longer starts before the root at all - the boundary above is a
#: zero-width assertion, so a drive letter, a ``../..`` chain or a UNC server
#: survives by never being consumed rather than by being carefully re-emitted.
#: A mutation that deleted the separator alternative left all 116 tests in this
#: module's two files passing, which is what dead code looks like; it was
#: removed rather than documented as covered.
#:
#: THE OVER-MATCH IS A CHOSEN COST, NOT AN OVERSIGHT, and this is it: a
#: ``Users`` or ``home`` segment followed by another segment is treated as
#: somebody's home directory even where it plainly is not, so an innocent
#: ``docs/Users/<file>`` is recorded as ``docs/[home-path]``,
#: ``src/home/<page>.tsx`` as ``src/[home-path]``, and a captured
#: ``cat $HOME/notes.txt`` as ``cat $[home-path]``. The alternative - demanding
#: more context before believing the root - is the rule that has now failed
#: four times, and its failure mode is a person's account name written into a
#: git-tracked file. The two errors are not comparable. A mangled path is
#: information lost from one log line, and it is recoverable: the command, the
#: tool and the session that produced it sit in the same record, and the second
#: line of defence (``scripts/keel_leak_check.py``) reports the shape anyway so
#: a project that really does keep a ``home/`` directory still gets it
#: triaged. A leaked account name cannot be un-leaked, because the record is
#: committed and pushed before anyone reads it - which is exactly how this
#: repository came to carry ten such findings in its own tracked logs on
#: 2026-08-10. So this screen prefers to mangle a log line, deliberately, and
#: ``tests/test_keel_home_shapes.py``'s
#: ``TestTheChosenOverMatchAndWhatItCosts`` pins the cost rather than leaving a
#: reader to discover it.
#:
#: WHAT REMAINS OUTSIDE THIS RULE, said rather than implied. The ROOT names are
#: exactly two, ``Users`` and ``home``, matched to
#: ``scripts/keel_leak_check.py``'s own set so the two lines of defence cannot
#: disagree about what a home root is; a platform with a third UNIVERSAL
#: spelling would need both changed together. A home shaped unlike either is
#: recognised by a SECOND branch instead of by a third root - see
#: ``build_home_shape_pattern``, and ``home_shape_siblings`` for why deriving a
#: new root from the running home was measured and rejected. And the ``name``
#: class above excludes glob and quoting metacharacters, so ``Users/*`` is left
#: alone - which is correct rather than a gap, since a wildcard names no
#: account. A percent- or URL-encoded separator (``C:%5CUsers%5C<account>``)
#: would defeat this line and ``_PATTERN`` alike; it is recorded as below the
#: floor because no keel component and no captured tool call produces an
#: encoded path, and it is left for the scan.
def build_home_shape_pattern(env: Mapping[str, str] | None = None) -> re.Pattern[str]:
    """``_HOME_SHAPE_RE``, with the running home's own shape folded in.

    A FUNCTION rather than a literal for two reasons. The first is the fix
    itself: one branch of the pattern is derived from the environment, so it
    cannot be a constant. The second is testability - the fake-home fixture in
    ``tests/test_keel_home_shapes.py`` rebuilds ``_PATTERN`` from an invented
    home, and it can now rebuild this pattern from the same invented home
    rather than reimplementing the construction or being unable to test the
    derived branch at all.

    TWO BRANCHES, because a home has two shapes:

    1. a home ROOT beginning a path segment, then an account name. The roots
       are exactly ``Users`` and ``home`` - the original rule, UNCHANGED and
       not widened, which is what keeps the ordinary machine's screen
       byte-identical to the one before this function existed.
    2. a directory whose name BEGINS with the running home's own basename,
       wherever it appears, for a home whose parent is not one of those two
       roots and which branch 1 therefore cannot anchor on. ``/root2/x``
       becomes ``/[home-path]/x``; so does ``/var/lib/<svc>2/x`` for a home of
       ``/var/lib/<svc>``. One or MORE trailing characters are required
       (``[^\\s\\\\/]+``, not ``*``), which excludes the exact home itself -
       ``/root`` is this user's own home and ``_PATTERN`` has already collapsed
       it to ``~`` by the time this screen runs, so matching it here could only
       overwrite a better answer with a worse one.

    Branch 2 keeps ``_HOME_SHAPE_ROOT_START``, as that comment requires, and
    asks for the leading separator with a LOOKBEHIND rather than consuming it,
    so the separator survives by never being matched - the same way branch 1
    leaves a drive letter and a ``../..`` chain alone.

    WHAT BRANCH 2 IS NOT: a new home ROOT derived from the home's parent. That
    was this fix's first shape and measurement rejected it; the whole argument,
    including the audit-line field it corrupted, is at ``home_shape_siblings``.
    Branch 2 costs nothing on a machine whose home is ordinary, because
    ``home_shape_siblings`` returns nothing there and the branch is not built.

    THE RESIDUE, stated because it is the honest half of this fix: a sibling of
    the home that does not SHARE its basename - ``/alice`` beside ``/root``, or
    ``/var/lib/<other>`` beside ``/var/lib/<svc>`` - is not seen, because
    nothing in its text says it is a home, and a rule that treated every
    directory beside a home as a home would screen ``/usr``, ``/etc`` and
    ``/tmp``. That is the same "below the floor" family ``_HOME_SHAPE_RE``'s
    comment already records for encoded separators, and it is left to
    ``scripts/keel_leak_check.py``.
    """
    branches = [
        _HOME_SHAPE_ROOT_START + r"(?:Users|home)[\\/]+"
        r"(?P<name>" + _HOME_SHAPE_NAME + r")"
    ]
    siblings = home_shape_siblings(env)
    if siblings:
        own = "|".join(re.escape(name) for name in siblings)
        branches.append(
            _HOME_SHAPE_ROOT_START + r"(?<=[\\/])"
            r"(?P<sibling>(?:" + own + r")[^\s\\/]+)(?=[\\/]|$)"
        )
    return re.compile("(?:" + "|".join(branches) + ")", re.IGNORECASE)


_HOME_SHAPE_RE = build_home_shape_pattern()


def _home_shape_replacement(match: re.Match[str]) -> str:
    """One home-shaped match: the root and the account name, replaced together.

    Everything AROUND the match is kept by not being matched in the first place
    - the drive letter, the ``../..`` chain, the UNC server, the whole tail of
    the path. Each of those carries no name and is what makes the line readable.
    The text comes back UNCHANGED for a pseudo-account
    (``C:\\Users\\Public\\x``), which names nobody and is ordinary content the
    scanner passes over too.

    TWO BRANCHES REACH HERE and only one of them has an account name to test.
    Branch 2 of ``build_home_shape_pattern`` matches a directory whose name
    begins with the running home's basename (``/root2``), where the DIRECTORY
    name is itself the account name - there is no separate ``name`` segment,
    and there is no pseudo-account question to ask, because a reserved name is
    a name INSIDE a home root and this shape has no root.
    ``groupdict().get`` rather than ``group``: the ``sibling`` group only
    exists in the pattern on a machine whose home is shaped that way, so
    asking for it by name unconditionally would raise on every other machine.
    """
    name = match.groupdict().get("name")
    if name is None:
        return HOME_SHAPE_TOKEN
    if name.strip().casefold() in RESERVED_HOME_NAMES:
        return match.group(0)
    return HOME_SHAPE_TOKEN


def screen_home_shapes(value: Any) -> Any:
    """Replace every home-SHAPED path that is not this user's home with a marker.

    Step 3 of ``redact``, between the home prefix and the denied names, and the
    answer to a question ``_PATTERN`` cannot be asked: what to do with text
    that is unmistakably somebody's home directory but is not this user's home
    directory in any spelling this machine can resolve. Leaving it is the leak;
    turning it into ``~`` would be a lie; so the account-name segment is
    replaced by ``HOME_SHAPE_TOKEN`` and everything around it - the drive, the
    ``../..`` chain, the whole tail of the path - is kept, because the tail is
    what makes an audit line worth reading and carries no name.

    That is deliberately a REFUSAL TO EMIT rather than a normalisation: a
    relativised path or a truncated one cannot be turned back into ``~/x``
    without inventing the very segment that was removed, and a redactor that
    guesses is a redactor that publishes its guess.

    WHAT "HOME-SHAPED" MEANS HERE, AND WHICH WAY IT ERRS. A ``Users`` or
    ``home`` directory segment followed by another segment, wherever it appears
    and whatever precedes it - plus, on a machine whose own home is shaped
    unlike either, a directory sharing that home's basename
    (``build_home_shape_pattern``). That deliberately catches paths that are
    not home directories at all - ``docs/Users/<file>`` becomes
    ``docs/[home-path]`` - because the rule that asked for more context than
    that has been defeated by a new spelling four times running, and its
    failure writes a real person's account name into a git-tracked file. This
    screen would rather mangle a log line than leak a name: the path is
    re-derivable from the rest of the record, the name is not un-leakable once
    pushed. The full argument, and the residuals it does NOT cover, are at
    ``_HOME_SHAPE_RE``.

    A non-string is returned unchanged, and a value with no home-shaped path in
    it is returned as the SAME string object (``re.sub`` returns its argument
    when nothing matched), so this step keeps the byte-identical guarantee the
    rest of the module makes. Runs whether or not a home directory resolved on
    this machine: it needs no environment at all, which is why the one
    condition ``redact`` warns about - no home resolvable - no longer means
    "usernames pass through untouched".
    """
    if not isinstance(value, str):
        return value
    return _HOME_SHAPE_RE.sub(_home_shape_replacement, value)


def _under_home(value: str) -> bool:
    """True when ``value`` itself begins with one of this user's home spellings.

    An EXPLICIT membership test, anchored at the start of the string via
    ``_PATTERN.match`` rather than ``.search`` - deliberately not inferred
    from whether ``redact(value) != value``. That comparison stopped meaning
    "under home" the moment ``screen_denied_names`` became step 3 of
    ``redact``: a path outside both the project and the home directory can
    still change under redaction if it happens to carry a registered name
    anywhere in it, and a proxy that cannot tell "changed because of home"
    from "changed because of a denied name" is not a home test at all. See
    ``redact_path``'s own docstring for what this decides between; no home
    resolving on this machine (``_PATTERN is None``) answers False here the
    same way it answers "nothing to substitute" in ``redact``.
    """
    return _PATTERN is not None and _PATTERN.match(value) is not None


def redact(value: Any) -> Any:
    """Drop marked content, collapse the home directory, mark home shapes, screen names.

    Non-strings pass through unchanged: this is meant to be applied to every
    field of a record without first proving the field is a string. A string
    that triggers none of the three transformations is returned unchanged too
    (see ``screen_denied_names`` and ``_PATTERN.sub`` for that guarantee on
    their own steps) - a screen that quietly reshaped ordinary text would
    corrupt every record in the project, which matters more than catching any
    one positive case.

    Fixed order, and the order is the contract:

    1. ``strip_private`` FIRST and unconditionally - before the home pattern,
       and before the degraded-redactor branch below - so that a machine
       where no home directory resolves still honours the exclusion. A
       denied name inside a ``<keel-private>`` block is already gone by the
       time step 3 would see it, so private content needs no separate
       handling from the denied-names screen either.
    2. The home-directory pattern SECOND (or the one-time stderr line, on a
       machine where none resolves). This is the PRECISE step: it knows this
       user's home in every spelling the machine can hand over, and it collapses
       each of them to ``~``.
    3. The home-SHAPE screen THIRD, and only third, because it is the COARSE
       step and must never answer a question step 2 can answer better. Once
       step 2 has run, every remaining ``…/Users/<name>/…`` is either another
       account or a spelling from which this user's own prefix has been
       destroyed - relativised, truncated - and in both cases the honest answer
       is the marker, not ``~``. Running it before step 2 would spell this
       user's own home ``C:\\[home-path]\\AppData`` and throw away the one fact
       redaction is supposed to keep.
    4. The denied-names screen LAST, deliberately after steps 2 and 3 rather
       than before them: the home pattern matches this user's actual
       home-directory spelling literally. If a denied word happened to be a
       substring of that spelling, screening it away first would corrupt
       the exact text the home pattern needs to see, and a home-directory
       leak could survive intact in the gap the screen left behind. Running
       the screen after the home collapse cannot have that failure - the
       home text is already gone by the time step 4 runs, so there is
       nothing left of it to mismatch.
    """
    if not isinstance(value, str):
        return value
    value = strip_private(value)
    if _PATTERN is None:
        _warn_once("redaction is inactive: no home directory could be resolved")
    else:
        value = _PATTERN.sub(HOME_TOKEN, value)
    return screen_denied_names(screen_home_shapes(value))


def redact_value(value: Any) -> Any:
    """``redact`` applied to ``value``, recursing into mappings and sequences.

    A mapping's values, and a list's or tuple's items, are each walked in
    turn - however deeply nested - so a structured field such as an audit
    line's ``detail`` (itself a dict of the verdict's own keyword detail) is
    screened exactly as thoroughly as a flat string field is. Every other
    type, a string included, is handed to ``redact`` itself, which already
    returns a non-string unchanged - so this function adds recursion, not a
    second redaction algorithm. This is the one walk ``redact_mapping`` and
    the write-time chokepoint in ``keel_events.py`` both stand on.
    """
    if isinstance(value, Mapping):
        return {key: redact_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        walked = [redact_value(item) for item in value]
        return tuple(walked) if isinstance(value, tuple) else walked
    return redact(value)


def redact_mapping(entry: Mapping[str, Any]) -> dict[str, Any]:
    """``redact`` applied to every value of a record, however deeply nested.

    Used both by callers that redact ahead of a write (``keel_dashboard.py``,
    re-screening a line already read back off disk) and by the write-time
    chokepoint itself (``keel_events._append_jsonl``, the one function every
    audit and queue line passes through). A caller that already redacted its
    fields, then hits the chokepoint, gets the same bytes back: ``redact`` is
    idempotent on already-substituted text for all three of its steps - a
    removed private block leaves no marker to remove again, a collapsed home
    prefix is spelled ``~`` and no longer matches the pattern, and the
    denied-names sentinel is reserved from the screen that produces it (see
    ``_screen_line``). ``tests/test_keel_audit_chokepoint_screen.py`` proves
    it on the bytes on disk rather than asserting it here, including the case
    where the register itself holds the sentinel's own word.
    """
    return {key: redact_value(value) for key, value in entry.items()}


def project_relative(cwd: Any, value: str) -> str:
    """Project-relative, POSIX-separated form of a path (convention 5).

    A path outside the project is expressed relative to it (``../..``); where
    even that is impossible - a different Windows drive - only the basename
    survives, because an audit line must never become the leak.
    """
    if not value:
        return ""
    try:
        return os.path.relpath(os.path.join(str(cwd), value), str(cwd)).replace(os.sep, "/")
    except (OSError, ValueError):
        return os.path.basename(value)


def redact_path(cwd: Any, value: Any) -> Any:
    """The one call every keel component makes before logging a path.

    Three cases, in this order, because the order is the whole correctness
    argument:

    1. Inside the project - the shortest safe form, ``src/app.py``. This is
       tried FIRST so that a project which itself lives under the home
       directory does not have every one of its files logged as ``~/...``.
    2. Outside the project but under this user's home - ``~/notes.txt``.
       Redaction has to happen on the ABSOLUTE value here: ``relpath`` would
       have spelled the username out as ``../../Users/<name>/notes.txt``,
       where the home pattern can no longer see it. Membership is decided by
       ``_under_home``, an explicit test of ``value`` itself - NOT by
       comparing ``redact(value)`` against ``value`` and treating any change
       as proof of home membership. Since ``redact`` also screens denied
       names, a path that is under NEITHER the project NOR the home
       directory, but happens to carry a registered name, would change under
       redaction too; the old proxy could not tell the two apart and
       answered with the fuller absolute form case 3 promises never to give -
       disclosing more path structure (potentially another real username
       segment) than this function's contract allows.
    3. Anywhere else - relative (``../../other/x``), or, when even that is
       impossible, the basename alone. Reached both on its own merits and as
       the fallback for a path ``_under_home`` correctly says no to.

    Case 2's argument about ``relpath`` is why this function exists, and it is
    now BELT AND BRACES rather than the only defence: should case 2 ever be
    reached wrongly - or should a caller relativise a home path itself, which
    ``hooks/keel_gate.py``'s ``relativise`` does - ``redact``'s home-shape
    screen still marks the ``../../Users/<name>`` that comes out. Choosing the
    right case here yields ``~/notes.txt``, which is better; failing to yields
    ``../../[home-path]/notes.txt``, which is not a leak.
    """
    if not isinstance(value, str) or not value:
        return value
    relative = project_relative(cwd, value)
    if relative and not relative.startswith("..") and not os.path.isabs(relative):
        return redact(relative)
    if _under_home(value):
        return redact(value).replace("\\", "/")
    return redact(relative)
