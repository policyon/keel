"""THE COMPLETENESS CHECK FOR BL8's SWEEP (T602).

WHY THIS FILE EXISTS, and it is not "one more test for the same bug". BL8 -
"the gate resolves the governing project from a stale shell cwd, not from the
write target" - was worked four times. Each pass found more sites than the
one before it: the entry named two, the first pass touched five modules, review
found two more, T515 named three further ones as out of scope. The finding
under the finding, recorded as
``.keel/knowledge/a-sweep-with-no-completeness-check-is-rediscovered-by-grep-every-pass.md``:
NOTHING ENUMERATED THE FLAT CHECKS. Every reader had to rediscover the residue
by grepping ``hooks/*.py`` for ``KEEL_DIRNAME).is_dir()``, and a grep is not a
gate - it runs when somebody remembers to run it and it is silent when they do
not.

So this file does the grep MECHANICALLY, in the suite, and pins the answer.
Every flat adoption test in ``hooks/`` is either absent (the site was routed
through the shared record walk in ``hooks/keel_events.py``) or present and
PINNED HERE with a reason that is also written in the code beside it. A new
unswept flat check turns this red on the pass that introduces it, which is the
whole point: residue must never again be discoverable only by grep.

WHAT COUNTS AS A FLAT ADOPTION TEST, stated exactly, because a detector whose
scope is vague is a detector nobody can trust:

* a DIRECTORY presence test (``.is_dir()``, ``.exists()``,
  ``os.path.isdir/exists``) applied to an expression that mentions ``.keel`` -
  literally, through ``KEEL_DIRNAME``, through a module constant whose value
  contains ``.keel``, or through a local assigned from any of those; and
* a call to one of the NAMED adoption predicates
  (``project_is_adopted``, ``record_root_present``, ``_is_keel_adopted``).

WHAT IT DOES NOT COVER, said plainly rather than left for a reader to assume.
This detector is about ADOPTION - "does this directory carry ``.keel/``" - and
therefore about a RECORD's destination. It is NOT about ARMING - "which policy
judges this write" - which is ``keel_gate.resolve_project``'s question, has its
own walk, and is deliberately keyed on the arming file instead. It also reads
SOURCE, not behaviour: it can prove that no site asks the flat question, and it
cannot prove that the answer a swept site gets is then used correctly. The
behaviour is pinned separately, by
``tests/test_keel_record_destination_t515.py`` and by the fixtures below it.

THE DETECTOR IS ITSELF TESTED (``TestTheDetectorItself``), because a safeguard
that cannot fail verifies nothing: four freshly planted flat checks, in four
different spellings, must each be seen.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

HOOKS_DIR = Path(__file__).resolve().parent.parent / "hooks"

#: The attribute and function names that ask the filesystem whether a
#: DIRECTORY is there. ``is_file`` is deliberately NOT in the set, and the
#: boundary is the one the module docstring draws: a presence test on a FILE
#: inside ``.keel/`` is an arming, ledger or backlog READ - a different
#: question, with a different owner and a different walk. Measured before it
#: was decided: including ``is_file`` pulled in
#: ``keel_liveview.setting`` (the autostart declaration),
#: ``keel_registry._is_keel_adopted`` (the arming-keyed seed filter) and
#: ``keel_stop.read_backlog_ids`` (the backlog), while still MISSING
#: ``keel_gate.policy_present``, which spells the same read through a helper.
#: Coverage that inconsistent is worse than a boundary stated plainly.
PRESENCE_NAMES = frozenset({"is_dir", "isdir", "exists", "lexists"})

#: The named predicates that answer the flat question. A call to one of these
#: IS a flat adoption test at the call site - which is what makes routing a new
#: site through ``project_is_adopted`` fail here exactly as writing a fresh
#: inline ``.is_dir()`` does.
ADOPTION_PREDICATES = frozenset(
    {"project_is_adopted", "record_root_present", "_is_keel_adopted"}
)

#: How ``.keel`` is spelled in source. Every other token is DERIVED from these
#: per module (constants and locals), never listed by hand, so a rename that
#: goes through ``KEEL_DIRNAME`` cannot slip past this file.
KEEL_LITERALS = ("KEEL_DIRNAME", '".keel"', "'.keel'")

#: THE WALK'S ENTRY POINTS, SPLIT BY WHAT THEY DO TO THE CALLER'S SPELLING.
#:
#: An undifferentiated list of entry points was the hole in the first cut of
#: this file, and it is worth stating exactly because it is the failure mode a
#: completeness check is MOST prone to: a set that answers "swept: yes" for
#: both a safe entry and a leaky one cannot turn red when a writer moves from
#: the first to the second. ``keel_capture.recording_root`` did exactly that -
#: it returned ``resolve_record_root(cwd).root``, the canonicalised root, and
#: every pin in this file was green.
#:
#: CANONICALISING entries climb ``os.path.realpath`` and hand back the
#: canonical spelling of the root even when the root IS the directory handed
#: in. That is correct for a caller that only WRITES through the answer, or
#: that resolves it again itself.
CANONICALISING_ENTRY_POINTS = frozenset(
    {
        "resolve_record_root",
        "record_root_or_none",
    }
)

#: SPELLING-PRESERVING entries hand back the caller's own spelling when the
#: walk did not climb. Required of any writer whose root reaches a REDACTED
#: record or a stderr line: ``keel_redact`` collapses the home directory BY
#: STRING, so a path respelled out of the spelling the home was resolved to
#: stops matching and the raw path leaks (convention 5). See
#: ``keel_events.record_root_as_spelled``'s docstring for the measurement.
#:
#: MEMBERSHIP HERE IS A BEHAVIOURAL CLAIM, NOT A LABEL, and
#: ``TestTheSpellingPreservingEntryPointsActuallyPreserveSpelling`` below makes
#: each name in this set prove it - otherwise a future site could be waved
#: through by adding its canonicalising helper to this list.
SPELLING_PRESERVING_ENTRY_POINTS = frozenset(
    {
        "record_root_as_spelled",
        "recording_root",
        "_recording_project",
    }
)

#: The shared record walk's entry points - ``hooks/keel_events.py``'s own
#: three, and the two thin per-module wrappers. NOT ``record_root_present``:
#: that is the flat primitive the walk is BUILT from, and counting it as a walk
#: call would let a swept site regress into the exact shape this file exists to
#: catch.
WALK_ENTRY_POINTS = CANONICALISING_ENTRY_POINTS | SPELLING_PRESERVING_ENTRY_POINTS

#: The token every exempt site must carry in the code, so the reason lives
#: BESIDE the exemption and not only in this file.
EXEMPTION_MARKER = "FLAT-ADOPTION EXEMPT (T602)"

#: THE PINNED EXEMPT LIST: ``(module, function) -> (how many, why)``.
#:
#: The count is pinned as well as the site, and that is deliberate: adding a
#: SECOND flat test to a function that already has a blessed one is exactly how
#: residue grew last time, and a pin on the site alone would wave it through.
EXEMPT_SITES: dict[tuple[str, str], tuple[int, str]] = {
    ("keel_events", "record_root_present"): (
        1,
        "the walk's own primitive - the single place the join is spelled, and "
        "what resolve_record_root calls at each level. Routing it through the "
        "walk would be the walk calling itself.",
    ),
    ("keel_events", "resolve_record_root"): (
        1,
        "the walk itself, calling its own primitive once per level.",
    ),
    ("keel_capture", "project_is_adopted"): (
        1,
        "the one NAMED spelling of the flat question, kept for tests and for a "
        "reader who genuinely asks about a directory's own adoption. It has no "
        "production caller left, and the count is asserted below.",
    ),
    ("keel_hook", "_audit_launcher_deny"): (
        1,
        "the handler of last resort: it runs only after a subcommand has "
        "already crashed, and keel_events - where the walk lives - is one of "
        "the things that may have crashed. Calling the suspect code to decide "
        "where to file the suspicion could take the crash-deny down with it.",
    ),
    ("keel_registry", "_seed_candidates"): (
        1,
        "it screens the PREDECESSOR's own registry file: each line is a project "
        "root somebody else already named, not a write target, so 'does THIS "
        "EXACT DIRECTORY carry keel' is the whole question and walking up would "
        "import a parent nobody listed. The reasoning is at _is_keel_adopted, "
        "which this calls.",
    ),
}

#: THE PINNED SWEPT LIST: writers whose record destination MUST come from the
#: shared walk. Each must hold NO flat adoption test and at least one call to a
#: walk entry point. This is the other direction of the same assertion - the
#: exempt list alone would be satisfied by deleting a writer's destination
#: logic entirely.
#:
#: ``spelling`` IS THE SECOND HALF OF "SWEPT", and it is not decoration: a
#: writer marked SPELLING must reach the walk through
#: ``SPELLING_PRESERVING_ENTRY_POINTS``, because its root reaches a redacted
#: record or a stderr line and a canonicalised root defeats the redactor
#: (convention 5). A writer marked CANONICAL may use either, and the entry
#: says WHY the canonical spelling is safe there - a blanket exemption with no
#: reason is how the first cut of this file let ``recording_root`` regress.
SPELLING = "spelling-preserving"
CANONICAL = "canonical-is-safe"

SWEPT_WRITERS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("keel_capture", "run"): (
        "activity, background and queue lines",
        SPELLING,
        "it re-anchors the event on the root and every path in the line is "
        "redacted on the way out; it reaches the walk through recording_root.",
    ),
    ("keel_capture", "recording_root"): (
        "the wrapper capture and session share",
        SPELLING,
        "THE SITE THIS PIN WAS ADDED FOR. Its answer is what run() files and "
        "what keel_stop reads back, and it used to return the canonical root.",
    ),
    ("keel_session", "run"): (
        "session_start, session_end, orientation, registry",
        SPELLING,
        "the injected orientation line is built from this root and is read by "
        "a human; ledger_hint already mixed a canonical root with a "
        "short-form cwd once and walked the account name into the injection.",
    ),
    ("keel_registry", "write"): (
        "the fleet registry entry",
        CANONICAL,
        "the ONE writer that must canonicalise: the entry is a KEY compared "
        "against _load's and _seed_candidates' already-resolved entries, so "
        "write() calls Path(root).resolve() on the answer regardless of how "
        "it is spelled - two spellings of one project would be two entries. "
        "It is redacted at _save, after that resolve, against the same "
        "resolved home.",
    ),
    ("keel_hook", "_recording_project"): (
        "the launcher's wrapper",
        SPELLING,
        "the wrapper every launcher subcommand routes through, and the "
        "sibling whose shape the other spelling-preserving sites copy.",
    ),
    ("keel_hook", "cmd_session"): (
        "the SessionEnd prompt-log prune",
        SPELLING,
        "reaches the walk through _recording_project.",
    ),
    ("keel_hook", "cmd_prompt"): (
        "the preserved user prompt and the nudge",
        SPELLING,
        "the measured leak: tests/test_keel_compaction_t228.py caught the "
        "canonical root reaching stderr from exactly this subcommand.",
    ),
    ("keel_hook", "cmd_precompact"): (
        "the compaction ledger pointer",
        SPELLING,
        "reaches the walk through _recording_project.",
    ),
    ("keel_hook", "cmd_subagent_stop"): (
        "subagent_stop lines",
        SPELLING,
        "reaches the walk through _recording_project.",
    ),
    ("keel_hook", "cmd_spike"): (
        "spike lines",
        SPELLING,
        "reaches the walk through _recording_project.",
    ),
}


# --------------------------------------------------------------- the detector


class FlatSite:
    """One flat adoption test: where it is and how it is spelled."""

    def __init__(self, module: str, function: str, lineno: int, source: str) -> None:
        self.module = module
        self.function = function
        self.lineno = lineno
        self.source = " ".join(source.split())[:90]

    @property
    def key(self) -> tuple[str, str]:
        return (self.module, self.function)

    def __repr__(self) -> str:  # pragma: no cover - failure messages only
        return f"hooks/{self.module}.py:{self.lineno} in {self.function}(): {self.source}"


def _segment(lines: list[str], node: ast.AST) -> str:
    """The source text of a node, sliced from a line list already in hand.

    ``ast.get_source_segment`` re-splits the whole file on every call, which on
    a 7,000-line module inside a walk is minutes rather than milliseconds. This
    is the same slice against a list split once.
    """
    start = getattr(node, "lineno", None)
    end = getattr(node, "end_lineno", None)
    if start is None or end is None:
        return ""
    if start == end:
        return lines[start - 1][node.col_offset : node.end_col_offset]
    chunk = [lines[start - 1][node.col_offset :]]
    chunk.extend(lines[start : end - 1])
    chunk.append(lines[end - 1][: node.end_col_offset])
    return "\n".join(chunk)


def _module_tokens(tree: ast.Module) -> set[str]:
    """Module-level names whose literal value carries ``.keel``, derived not listed.

    ``KEEL_DIRNAME``, ``_ARMING_RELPATH``, ``BACKLOG_RELPATH`` and their kin are
    found by reading their values, never by being listed here, so a rename that
    goes through the constant cannot slip past this file.
    """
    tokens = set(KEEL_LITERALS)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if node.value is None:
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, SyntaxError, TypeError):
            continue
        if ".keel" in repr(value):
            tokens.update(t.id for t in targets if isinstance(t, ast.Name))
    return tokens


def _local_tokens(scope: ast.AST, lines: list[str], seed: set[str]) -> set[str]:
    """Names assigned INSIDE one scope from an expression carrying ``.keel``.

    SCOPED PER FUNCTION, and that is not a detail. A first draft tainted names
    across the whole module, so a single ``path = <something>/.keel/...``
    anywhere in ``keel_gate`` made every ``path.is_file()`` in the file look
    like an adoption test - seven false hits, every one of them an arming,
    ledger or backlog READ. A detector that cries wolf gets its exempt list
    padded with entries nobody reads, which is the failure mode this whole file
    exists to avoid.

    Two hops, bounded on purpose: a third buys nothing a reviewer can follow.
    """
    tokens = set(seed)
    for _ in range(2):
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            else:
                continue
            if any(token in _segment(lines, value) for token in tokens):
                tokens.update(t.id for t in targets if isinstance(t, ast.Name))
    return tokens


def _enclosing(tree: ast.Module) -> dict[int, str]:
    """Node id -> the dotted name of the function or class holding it."""
    owner: dict[int, str] = {}

    def descend(parent: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(parent):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                for inner in ast.walk(child):
                    owner.setdefault(id(inner), name)
                descend(child, name)

    descend(tree, "")
    return owner


def _called_name(node: ast.Call) -> str | None:
    """The bare name being called, however it is qualified."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def scan_module(path: Path) -> tuple[list[FlatSite], dict[str, set[str]], list[str]]:
    """Every flat adoption site in one module, plus which functions call what.

    Returns (sites, calls-by-function, source lines).
    """
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    module = path.stem
    module_tokens = _module_tokens(tree)
    owner = _enclosing(tree)
    scope_tokens: dict[str, set[str]] = {"<module>": module_tokens}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = owner.get(id(node))
            if name is not None:
                scope_tokens[name] = _local_tokens(node, lines, module_tokens)
    sites: list[FlatSite] = []
    calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _called_name(node)
        function = owner.get(id(node), "<module>")
        if name is not None:
            calls.setdefault(function, set()).add(name)
        text = _segment(lines, node)
        tokens = scope_tokens.get(function, module_tokens)
        flat = False
        if name in PRESENCE_NAMES and any(token in text for token in tokens):
            flat = True
        if name in ADOPTION_PREDICATES:
            flat = True
        if flat:
            sites.append(FlatSite(module, function, node.lineno, text))
    return sites, calls, lines


def scan_hooks() -> tuple[list[FlatSite], dict[str, dict[str, set[str]]]]:
    """The whole ``hooks/`` tree, in one pass."""
    sites: list[FlatSite] = []
    calls: dict[str, dict[str, set[str]]] = {}
    for path in sorted(HOOKS_DIR.glob("*.py")):
        module_sites, module_calls, _ = scan_module(path)
        sites.extend(module_sites)
        calls[path.stem] = module_calls
    return sites, calls


def function_source(module: str, function: str) -> str:
    """The source text of one function, for the marker assertion."""
    path = HOOKS_DIR / f"{module}.py"
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source)
    owner = _enclosing(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if owner.get(id(node)) == function:
                return _segment(lines, node)
    return ""


# ------------------------------------------------------------------ the pins


class TestTheFlatAdoptionSweepIsComplete(unittest.TestCase):
    """The residue is enumerated by the suite, not by whoever remembers to grep."""

    def setUp(self) -> None:
        self.sites, self.calls = scan_hooks()

    def test_every_flat_adoption_site_in_hooks_is_pinned_exempt(self) -> None:
        unpinned = [site for site in self.sites if site.key not in EXEMPT_SITES]
        self.assertEqual(
            unpinned,
            [],
            "a flat .keel/ adoption test appeared in hooks/ that is neither "
            "routed through the shared record walk (hooks/keel_events.py: "
            "resolve_record_root / record_root_or_none) nor pinned in "
            "EXEMPT_SITES with the reason written beside it in the code. "
            "This is BL8's residue growing back. Sites: "
            + "; ".join(repr(site) for site in unpinned),
        )

    def test_each_exempt_site_still_exists_and_holds_exactly_its_pinned_count(
        self,
    ) -> None:
        counted: dict[tuple[str, str], int] = {}
        for site in self.sites:
            counted[site.key] = counted.get(site.key, 0) + 1
        expected = {key: pin[0] for key, pin in EXEMPT_SITES.items()}
        self.assertEqual(
            counted,
            expected,
            "the exempt list no longer matches the code. A count that GREW "
            "means a second flat test was added to a function that already "
            "held a blessed one; a count that FELL or a key that vanished "
            "means the exemption is stale and its entry should go.",
        )

    def test_each_exemption_states_its_reason_in_the_code_beside_it(self) -> None:
        for (module, function), (_, reason) in sorted(EXEMPT_SITES.items()):
            with self.subTest(site=f"{module}.{function}"):
                self.assertTrue(
                    reason.strip(),
                    "an exemption with no reason is an exemption nobody can review",
                )
                body = function_source(module, function)
                self.assertNotEqual(
                    body, "", f"hooks/{module}.py has no {function}() to be exempt"
                )
                self.assertIn(
                    EXEMPTION_MARKER,
                    body,
                    f"hooks/{module}.py::{function} is pinned exempt here but "
                    f"says nothing about it in the code. The reason has to live "
                    f"where the next reader of that function will see it, or "
                    f"they will sweep it and break something on purpose.",
                )

    def test_every_swept_writer_resolves_its_destination_through_the_walk(self) -> None:
        for (module, function), (what, _, _) in sorted(SWEPT_WRITERS.items()):
            with self.subTest(writer=f"{module}.{function}"):
                flat = [
                    site
                    for site in self.sites
                    if site.module == module and site.function == function
                ]
                self.assertEqual(
                    flat,
                    [],
                    f"{module}.{function} writes {what} and has gone back to "
                    f"asking the flat question: {flat}",
                )
                called = self.calls.get(module, {}).get(function, set())
                self.assertTrue(
                    called & WALK_ENTRY_POINTS,
                    f"{module}.{function} writes {what} but calls no entry point "
                    f"of the shared record walk ({sorted(WALK_ENTRY_POINTS)}). A "
                    f"writer that resolves its own destination is how the two "
                    f"walks came to disagree in the first place.",
                )

    def test_a_writer_whose_root_is_redacted_reaches_the_walk_spelling_first(
        self,
    ) -> None:
        """"Swept" is not one question. THIS is the half the first cut missed.

        A writer pinned SPELLING must call a SPELLING-PRESERVING entry point.
        Reaching the walk through ``resolve_record_root`` or
        ``record_root_or_none`` alone is the regression
        ``keel_capture.recording_root`` shipped with: routed through the walk,
        green on every other pin in this file, and handing back a canonical
        root that ``keel_redact`` can no longer collapse.
        """
        for (module, function), (what, mode, why) in sorted(SWEPT_WRITERS.items()):
            if mode != SPELLING:
                continue
            with self.subTest(writer=f"{module}.{function}"):
                called = self.calls.get(module, {}).get(function, set())
                self.assertTrue(
                    called & SPELLING_PRESERVING_ENTRY_POINTS,
                    f"{module}.{function} writes {what} ({why}) and its root "
                    f"reaches a redacted record or a stderr line, but it "
                    f"calls only "
                    f"{sorted(called & CANONICALISING_ENTRY_POINTS) or 'no'} "
                    f"walk entry point(s). A canonicalising entry hands back "
                    f"the realpath spelling even when the walk never climbed, "
                    f"and keel_redact collapses the home BY STRING - so the "
                    f"raw path leaks (convention 5). Reach the walk through "
                    f"one of {sorted(SPELLING_PRESERVING_ENTRY_POINTS)}.",
                )

    def test_every_swept_writer_declares_which_spelling_it_needs_and_why(self) -> None:
        for (module, function), (_, mode, why) in sorted(SWEPT_WRITERS.items()):
            with self.subTest(writer=f"{module}.{function}"):
                self.assertIn(mode, (SPELLING, CANONICAL))
                self.assertTrue(
                    why.strip(),
                    "a writer excused from spelling preservation with no "
                    "reason is the undifferentiated list all over again",
                )

    def test_the_two_kinds_of_entry_point_are_disjoint(self) -> None:
        self.assertEqual(
            CANONICALISING_ENTRY_POINTS & SPELLING_PRESERVING_ENTRY_POINTS,
            frozenset(),
            "an entry point cannot be both, and one listed in both would make "
            "the spelling pin above unfalsifiable",
        )

    def test_the_named_flat_predicate_has_no_production_caller(self) -> None:
        callers = [
            f"{module}.{function}"
            for module, functions in self.calls.items()
            for function, names in functions.items()
            if "project_is_adopted" in names and function != "project_is_adopted"
        ]
        self.assertEqual(
            callers,
            [],
            "keel_capture.project_is_adopted answers 'does THIS EXACT "
            "DIRECTORY carry .keel/', which is not the question a record's "
            "destination asks. Every production caller was swept onto the walk "
            "by T602; a new one is the residue coming back through the front "
            f"door. Callers: {callers}",
        )


class TestTheDetectorItself(unittest.TestCase):
    """A safeguard that cannot fail verifies nothing.

    Each case plants a flat check in a throwaway module in one of the spellings
    a future site might plausibly use, and asserts the scanner sees it. Without
    these, an over-narrow detector would report a clean sweep forever.
    """

    def _scan(self, source: str) -> list[FlatSite]:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "keel_planted.py"
            path.write_text(source, encoding="utf-8")
            sites, _, _ = scan_module(path)
            return sites

    def test_it_sees_the_constant_spelling(self) -> None:
        sites = self._scan(
            "from keel_events import KEEL_DIRNAME\n"
            "def record(cwd):\n"
            "    if not (cwd / KEEL_DIRNAME).is_dir():\n"
            "        return 0\n"
            "    return 1\n"
        )
        self.assertEqual([site.function for site in sites], ["record"])

    def test_it_sees_the_string_literal_spelling(self) -> None:
        sites = self._scan(
            "def record(cwd):\n"
            '    if not (cwd / ".keel").exists():\n'
            "        return 0\n"
            "    return 1\n"
        )
        self.assertEqual([site.function for site in sites], ["record"])

    def test_it_sees_the_os_path_spelling_through_a_local(self) -> None:
        sites = self._scan(
            "import os\n"
            "def record(cwd):\n"
            '    state = os.path.join(cwd, ".keel")\n'
            "    if not os.path.isdir(state):\n"
            "        return 0\n"
            "    return 1\n"
        )
        self.assertEqual([site.function for site in sites], ["record"])

    def test_it_sees_a_call_to_a_named_adoption_predicate(self) -> None:
        sites = self._scan(
            "from keel_capture import project_is_adopted\n"
            "def record(cwd):\n"
            "    if not project_is_adopted(cwd):\n"
            "        return 0\n"
            "    return 1\n"
        )
        self.assertEqual([site.function for site in sites], ["record"])

    def test_it_does_not_fire_on_a_site_that_uses_the_walk(self) -> None:
        sites = self._scan(
            "from keel_events import record_root_or_none\n"
            "def record(cwd):\n"
            "    root = record_root_or_none(cwd)\n"
            "    if root is None:\n"
            "        return 0\n"
            "    return 1\n"
        )
        self.assertEqual(sites, [])


# ------------------------------------------------- what the sweep actually did
#
# The pins above are about SOURCE. These are about BEHAVIOUR, at the three
# sites T602 swept that had no fixture of their own, and they are here rather
# than in ``tests/test_keel_record_destination_t515.py`` so that T515's own
# verified fixtures are left exactly as they were.

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from unittest import mock  # noqa: E402

sys.path.insert(0, str(HOOKS_DIR))
import keel_capture  # noqa: E402
import keel_events  # noqa: E402
import keel_gate  # noqa: E402
import keel_hook  # noqa: E402
import keel_registry  # noqa: E402
import keel_session  # noqa: E402

SESS8 = "beef0602"
SESSION = SESS8 + "-0000-0000-0000-000000000000"


def _adopt(project: Path, *, arm: bool = True) -> Path:
    """A fixture project carrying ``.keel/`` and, by default, an arming file."""
    (project / ".keel" / "plans").mkdir(parents=True, exist_ok=True)
    if arm:
        (project / ".keel" / "keel-policy.md").write_text(
            "---\ntier: 2\n---\n\n# keel policy - fixture\n", encoding="utf-8"
        )
    return project


def _session_event(kind: str, cwd: Path) -> keel_events.KeelEvent:
    return keel_events.KeelEvent(
        kind=kind,
        cwd=cwd,
        session_id=SESSION,
        raw={"hook_event_name": "SessionStart", "source": "startup"},
    )


def _audit(project: Path) -> list[dict]:
    path = keel_events.audit_path(project)
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestTheSessionBoundaryFollowsTheWalk(unittest.TestCase):
    """keel_session.run: the record that a subdirectory session used to lose.

    Before T602 this hook asked ``project_is_adopted(event.cwd)`` and returned
    0, so a session started in a subdirectory produced no session_start, no
    session_end, no orientation and no registry entry for its whole life.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = _adopt(self.root / "proj")
        self.sub = self.project / "src" / "deep"
        self.sub.mkdir(parents=True)
        self.loose = self.root / "loose"
        self.loose.mkdir()
        # The fleet registry is user-global and this test has no business in
        # the real one; ``run``'s call to it is proved separately, below.
        patch = mock.patch.object(keel_session, "registry_write", lambda *a, **k: None)
        patch.start()
        self.addCleanup(patch.stop)

    def _run(self, kind: str, cwd: Path) -> str:
        stream = io.StringIO()
        code = keel_session.run(_session_event(kind, cwd), stdout=stream, env={})
        self.assertEqual(code, 0, "the session hook never changes an outcome")
        return stream.getvalue()

    def test_a_subdirectory_session_start_is_filed_at_the_project_root(self) -> None:
        self._run("session_start", self.sub)
        kinds = [line.get("event") for line in _audit(self.project)]
        self.assertIn("session_start", kinds)

    def test_a_subdirectory_session_end_is_filed_at_the_project_root(self) -> None:
        self._run("session_end", self.sub)
        kinds = [line.get("event") for line in _audit(self.project)]
        self.assertIn("session_end", kinds)

    def test_no_state_directory_is_created_under_the_subdirectory(self) -> None:
        self._run("session_start", self.sub)
        self.assertFalse(
            (self.sub / ".keel").exists(),
            "R25: the walk may file a record higher up, never adopt a new tree",
        )

    def test_an_unadopted_tree_is_left_untouched_and_says_nothing(self) -> None:
        printed = self._run("session_start", self.loose)
        self.assertEqual(printed, "", "an unadopted project gets no injection")
        self.assertFalse((self.loose / ".keel").exists())
        self.assertEqual(_audit(self.loose), [])

    def test_the_ordinary_session_at_the_root_is_unchanged(self) -> None:
        printed = self._run("session_start", self.project)
        self.assertIn(keel_gate.session_plan_relpath(SESS8), printed)
        self.assertNotIn("../", printed, "no relative prefix where none is needed")
        kinds = [line.get("event") for line in _audit(self.project)]
        self.assertEqual(kinds, ["session_start"])

    def test_the_injected_ledger_path_is_spelled_from_where_the_session_stands(
        self,
    ) -> None:
        printed = self._run("session_start", self.sub)
        expected = "../../" + keel_gate.session_plan_relpath(SESS8)
        self.assertIn(
            expected,
            printed,
            "a subdirectory session told to write .keel/plans/... relative to "
            "ITSELF would create a ledger the gate never looks in",
        )

    def test_the_hint_is_byte_identical_at_the_root_and_relative_below_it(
        self,
    ) -> None:
        plain = keel_gate.session_plan_relpath(SESS8)
        self.assertEqual(keel_session.ledger_hint(self.project, self.project, SESS8), plain)
        self.assertEqual(
            keel_session.ledger_hint(self.project, self.project / "src", SESS8),
            "../" + plain,
        )
        self.assertEqual(
            keel_session.ledger_hint(self.project, self.sub, SESS8), "../../" + plain
        )

    def test_the_hint_refuses_a_prefix_that_is_not_a_pure_ascent(self) -> None:
        elsewhere = self.root / "other"
        elsewhere.mkdir()
        self.assertIsNone(
            keel_session.ledger_hint(self.project, elsewhere, SESS8),
            "a cwd that is not below the root cannot be given a relative "
            "ledger path, and a wrong one is worse than none",
        )

    def test_the_injected_line_carries_no_account_name_and_no_home_marker(self) -> None:
        printed = self._run("session_start", self.sub)
        self.assertNotIn(
            Path.home().name,
            printed.splitlines()[0],
            "the first cut of ledger_hint mixed a canonical root with a short-form "
            "cwd and walked the account name into the injected line",
        )
        self.assertNotIn(
            "[home-path]",
            printed,
            "an absolute ledger path would be screened to [home-path] and "
            "instruct the model to write nowhere - the reason T515 left this "
            "site alone and the reason ledger_hint is relative",
        )


class TestTheFleetRegistryRegistersTheProjectNotTheSubdirectory(unittest.TestCase):
    """keel_registry.write: the entry is a project, or there is no entry."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.project = _adopt(self.root / "proj")
        self.sub = self.project / "src"
        self.sub.mkdir()

    def _entries(self) -> list[str]:
        path = keel_registry.registry_path(home=self.home)
        if path is None or not path.is_file():
            return []
        document = json.loads(path.read_text(encoding="utf-8"))
        return [entry["path"] for entry in document["projects"]]

    def test_a_subdirectory_session_registers_its_project_root(self) -> None:
        stats = keel_registry.write(self.sub, home=self.home)
        self.assertTrue(stats["written"], "a subdirectory session used to register nothing")
        entries = self._entries()
        self.assertEqual(len(entries), 1)
        self.assertTrue(
            entries[0].endswith("proj"),
            f"the fleet lists projects, not subdirectories: {entries}",
        )

    def test_registering_from_the_root_and_from_below_it_is_one_entry(self) -> None:
        keel_registry.write(self.project, home=self.home)
        keel_registry.write(self.sub, home=self.home)
        self.assertEqual(
            len(self._entries()), 1, "T227 clause 2: a set union, not two keys"
        )

    def test_an_unadopted_directory_writes_nothing_at_all(self) -> None:
        loose = self.root / "loose"
        loose.mkdir()
        stats = keel_registry.write(loose, home=self.home)
        self.assertFalse(stats["written"])
        self.assertEqual(self._entries(), [])


class TestTheRegistrySaysWhenTheWalkRanOutOfBudget(unittest.TestCase):
    """ABSENT IS SILENT, EXHAUSTED IS SAID (convention 7), at keel_registry.write.

    ``record_root_or_none`` collapses both refusals into ONE None, and
    ``write``'s only other channel is a stats mapping whose ``written`` is
    False either way - so an exhausted walk left NO trace anywhere and a
    project silently missing from the fleet looked exactly like a directory
    keel was right to decline. ``keel_hook._recording_project``, swept in the
    same change, already states and keeps this rule; this pins the registry to
    the same one, in both directions, because a stderr line asserted only on
    the loud side would still pass if EVERY case became loud.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        (self.home / ".claude").mkdir(parents=True)
        self.project = _adopt(self.root / "proj")

    def _write(self, cwd: Path) -> tuple[dict, str]:
        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            stats = keel_registry.write(cwd, home=self.home)
        return stats, stream.getvalue()

    def _registry_exists(self) -> bool:
        path = keel_registry.registry_path(home=self.home)
        return path is not None and path.is_file()

    def test_absent_is_silent_and_writes_nothing(self) -> None:
        loose = self.root / "loose"
        loose.mkdir()
        self.assertEqual(
            keel_events.resolve_record_root(loose).state,
            keel_events.RECORD_ROOT_ABSENT,
            "fixture check: this directory must reach the walk's ceiling",
        )
        stats, printed = self._write(loose)
        self.assertFalse(stats["written"])
        self.assertFalse(self._registry_exists())
        self.assertEqual(
            printed,
            "",
            "an unadopted tree is a COMPLETE answer and keel's business to "
            "leave alone; a line here would nag every non-keel project on "
            "the machine",
        )

    def test_exhausted_is_said_and_still_writes_nothing(self) -> None:
        too_deep = self.project.joinpath(
            *["d"] * (keel_events.RECORD_WALK_MAX_LEVELS + 2)
        )
        too_deep.mkdir(parents=True)
        self.assertTrue(
            keel_events.resolve_record_root(too_deep).unknown,
            "fixture check: this directory must exhaust the walk's budget",
        )
        stats, printed = self._write(too_deep)
        self.assertFalse(stats["written"])
        self.assertFalse(
            self._registry_exists(),
            "R25 and T227 clause 1 are unchanged: saying so is not writing",
        )
        self.assertIn(
            "fleet registry not updated",
            printed,
            "the walk ran out of budget, so a project that owns this path may "
            "exist above the ceiling and the fleet is missing an entry it "
            "should have had - that is an INCOMPLETE answer, and it is said",
        )
        self.assertIn("within the walk's bound", printed)

    def test_the_two_refusals_are_told_apart_and_not_merely_both_loud(self) -> None:
        loose = self.root / "loose"
        loose.mkdir()
        too_deep = self.project.joinpath(
            *["d"] * (keel_events.RECORD_WALK_MAX_LEVELS + 2)
        )
        too_deep.mkdir(parents=True)
        _, absent = self._write(loose)
        _, exhausted = self._write(too_deep)
        self.assertNotEqual(
            absent,
            exhausted,
            "collapsing ABSENT and EXHAUSTED into one silence is the defect; "
            "collapsing them into one NOISE is the same defect wearing a "
            "stderr line",
        )
        self.assertEqual(absent, "")
        self.assertNotEqual(exhausted, "")


class TestTheWalkDoesNotRespellAPathItDidNotMove(unittest.TestCase):
    """keel_events.record_root_as_spelled - the redaction leak T602 measured.

    The walk climbs ``realpath``, so it hands back the CANONICAL spelling. On
    Windows the harness routinely supplies the 8.3 short form, and a path
    respelled out of the spelling the home directory was resolved to stops
    matching ``keel_redact``'s home collapse - the raw path then reaches
    stderr. ``tests/test_keel_compaction_t228.py`` caught this as a failure
    when the launcher's prompt hook was first swept.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = _adopt(self.root / "proj")

    def test_the_callers_own_spelling_comes_back_when_the_walk_stays_put(self) -> None:
        self.assertEqual(
            str(keel_events.record_root_as_spelled(self.project)), str(self.project)
        )

    def test_a_short_form_spelling_is_not_expanded_underneath_the_caller(self) -> None:
        given = str(self.project)
        canonical = os.path.realpath(given)
        if given == canonical:
            self.skipTest(
                "this machine's temporary directory is already canonical, so "
                "there is no respelling here to catch; the assertion above "
                "still holds and the leak this guards is Windows 8.3-specific"
            )
        self.assertEqual(str(keel_events.record_root_as_spelled(self.project)), given)
        self.assertNotEqual(str(keel_events.record_root_as_spelled(self.project)), canonical)

    def test_a_walk_that_climbed_returns_the_root_it_found(self) -> None:
        sub = self.project / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(
            str(keel_events.record_root_as_spelled(sub)),
            os.path.realpath(str(self.project)),
        )

    def test_an_unowned_path_is_still_none(self) -> None:
        loose = self.root / "loose"
        loose.mkdir()
        self.assertIsNone(keel_events.record_root_as_spelled(loose))


#: A short-form / long-form pair used by the SEAM tests below. Neither path
#: exists and neither is ever created: these tests drive the spelling decision
#: through a fabricated resolution and a stubbed ``realpath``, so they prove
#: the same thing on a machine whose temporary directory happens to be
#: canonical - where the filesystem tests can only honestly skip.
SEAM_SHORT = Path(r"C:\Users\SPELLI~1.NAM\proj")  # keel-leak: ignore - an invented name, and the pair is the fixture's subject
SEAM_LONG = Path(r"C:\Users\spelling.name\proj")  # keel-leak: ignore - an invented name, and the pair is the fixture's subject


@contextlib.contextmanager
def seam_walk_answers(root: Path, realpath: Path):
    """Make the walk answer FOUND at ``root`` and ``realpath`` answer ``realpath``.

    The walk is stubbed on ``keel_events`` AND on every hook module holding its
    own ``from keel_events import resolve_record_root`` binding, so a caller
    that reaches the walk directly is stubbed just the same and the test
    measures WHAT IT DOES WITH THE ANSWER rather than which name it used.
    ``realpath`` is stubbed on ``os.path`` for the block, so nothing here reads
    a disk: a canonicalising caller answers ``realpath``'s LONG spelling, a
    preserving one answers the SHORT one it was handed.
    """
    found = keel_events.RecordRoot(keel_events.RECORD_ROOT_FOUND, root)
    stub = lambda path, home=None: found  # noqa: E731 - one expression, named once
    holders = [
        module
        for module in (keel_events, keel_capture, keel_hook, keel_session, keel_registry)
        if getattr(module, "resolve_record_root", None) is not None
    ]
    with contextlib.ExitStack() as stack:
        for module in holders:
            stack.enter_context(mock.patch.object(module, "resolve_record_root", stub))
        stack.enter_context(
            mock.patch.object(keel_events.os.path, "realpath", lambda path: str(realpath))
        )
        yield


class TestTheSpellingPreservingEntryPointsActuallyPreserveSpelling(unittest.TestCase):
    """Membership in SPELLING_PRESERVING_ENTRY_POINTS is a claim, so it is tested.

    Without this class the split above is a LABEL: a future writer could be
    waved past the spelling pin by adding whatever helper it happens to call
    to that frozenset. Every name in the set answers here, in the one case
    that distinguishes the two kinds - the walk did NOT climb, so a
    canonicalising entry respells and a preserving one does not.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = _adopt(self.root / "proj")

    def _entry_points_answering_here(self) -> dict:
        return {
            "record_root_as_spelled": lambda p: keel_events.record_root_as_spelled(p),
            "recording_root": lambda p: keel_capture.recording_root(p),
            "_recording_project": lambda p: keel_hook._recording_project(p, "a record"),
        }

    def test_the_set_and_the_functions_exercised_here_are_the_same_names(self) -> None:
        self.assertEqual(
            set(self._entry_points_answering_here()),
            set(SPELLING_PRESERVING_ENTRY_POINTS),
            "a name added to SPELLING_PRESERVING_ENTRY_POINTS without a case "
            "here is a label, not a behaviour - which is the hole this whole "
            "split exists to close",
        )

    def test_each_one_returns_the_callers_own_spelling_when_the_walk_stays_put(
        self,
    ) -> None:
        given = str(self.project)
        canonical = os.path.realpath(given)
        for name, call in sorted(self._entry_points_answering_here().items()):
            with self.subTest(entry_point=name):
                self.assertEqual(str(call(self.project)), given)
                if given != canonical:
                    self.assertNotEqual(str(call(self.project)), canonical)
        if given == canonical:
            self.skipTest(
                "this machine's temporary directory is already canonical, so "
                "the equalities above cannot tell preservation from "
                "canonicalisation; the seam test below does not depend on the "
                "filesystem and can"
            )

    def test_each_one_preserves_the_spelling_at_the_seam_with_no_filesystem(
        self,
    ) -> None:
        """The same claim, decided purely on strings.

        The filesystem case above degrades to an honest skip where the temp
        directory is already canonical - which is most CI. This one does not:
        the walk is stubbed to answer FOUND at the LONG spelling for a SHORT
        one that names the same directory, which is precisely the Windows 8.3
        situation, and nothing is read from disk.
        """
        for name, call in sorted(self._entry_points_answering_here().items()):
            with self.subTest(entry_point=name):
                with seam_walk_answers(SEAM_LONG, SEAM_LONG):
                    answer = call(SEAM_SHORT)
                self.assertEqual(
                    str(answer),
                    str(SEAM_SHORT),
                    f"{name} respelled the caller's path out of the spelling "
                    f"the home directory was resolved to. keel_redact "
                    f"collapses the home BY STRING, so the raw path now "
                    f"reaches stderr (convention 5).",
                )

    def test_the_seam_still_returns_the_canonical_root_when_the_walk_climbed(
        self,
    ) -> None:
        """The other direction, so the seam cannot pass by returning its input.

        When the walk really did climb, the caller never held a spelling of
        the ancestor and the canonical one is the only answer there is.
        """
        parent = SEAM_LONG.parent
        for name, call in sorted(self._entry_points_answering_here().items()):
            with self.subTest(entry_point=name):
                with seam_walk_answers(parent, SEAM_LONG):
                    answer = call(SEAM_SHORT)
                self.assertEqual(str(answer), str(parent))


class TestTheRecorderShareKeepsTheSpellingItWasHanded(unittest.TestCase):
    """keel_capture.recording_root, the site FINDING 2 named.

    It returned ``resolve_record_root(cwd).root`` - the canonical root - while
    its sibling ``keel_hook._recording_project`` had already been moved onto
    ``record_root_as_spelled`` for a leak measured in
    ``tests/test_keel_compaction_t228.py``. Its own docstring said nothing
    about spelling, and every pin in this file was green.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = _adopt(self.root / "proj")

    def test_the_root_it_answers_with_is_the_one_it_was_asked_about(self) -> None:
        self.assertEqual(str(keel_capture.recording_root(self.project)), str(self.project))

    def test_it_does_not_expand_a_short_form_underneath_the_caller(self) -> None:
        given = str(self.project)
        canonical = os.path.realpath(given)
        if given == canonical:
            self.skipTest(
                "this machine's temporary directory is already canonical, so "
                "there is no respelling here to catch; the seam test below "
                "carries this claim without the filesystem"
            )
        self.assertEqual(str(keel_capture.recording_root(self.project)), given)
        self.assertNotEqual(str(keel_capture.recording_root(self.project)), canonical)

    def test_it_preserves_the_spelling_at_the_seam_with_no_filesystem(self) -> None:
        with seam_walk_answers(SEAM_LONG, SEAM_LONG):
            self.assertEqual(str(keel_capture.recording_root(SEAM_SHORT)), str(SEAM_SHORT))

    def test_it_still_climbs_and_answers_the_root_it_found(self) -> None:
        sub = self.project / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(
            str(keel_capture.recording_root(sub)), os.path.realpath(str(self.project))
        )

    def test_an_unowned_path_is_still_none(self) -> None:
        loose = self.root / "loose"
        loose.mkdir()
        self.assertIsNone(keel_capture.recording_root(loose))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
