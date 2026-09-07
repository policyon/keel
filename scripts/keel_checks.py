#!/usr/bin/env python3
"""keel repository checks — the CI gates (R2, R7, R9, R14, R18, R22, R27, R28, R33).

Contract
--------
Reads   : this repository's working tree, plus ``git ls-files``,
          ``git ls-files --others --exclude-standard``, ``git ls-files -s``
          and ``git check-ignore --stdin`` output. For ``--policy`` only, also
          ``git rev-parse``, ``git ls-tree`` and ``git show`` output, which is
          how it compares the STAGED arming file against HEAD's. For
          ``--budget`` only, also
          the session injection cap via ``hooks/keel_session.inject_cap_bytes``
          — imported rather than duplicated, so the two never disagree — which
          itself reads the ``KEEL_INJECT_CAP_BYTES`` environment variable.
Emits   : one human-readable line per check on stdout; violation detail on
          stdout beneath its check. ``--budget`` emits three figures: the
          always-loaded static total (the only one that gates this check's
          exit code), the session injection estimate, and their sum as a
          reported-only worst-case session floor — see ``.keel/keel-policy.md``
          -> Budget, which this report is shaped to match. Nothing is written
          anywhere.
          For ``--distribution`` only, also the tracked ``dist/keel`` tree
          and a fresh generation of it written into a temporary directory by
          ``keel_gen_editions.generate_distribution`` — a sibling script, not
          a third-party dependency — which is removed when the check
          finishes.
Argv    : one ``--flag`` per check in :data:`CHECKS` — ``--deps``,
          ``--symlinks``, ``--budget``, ``--names``, ``--refs``, ``--agents``,
          ``--closure``, ``--policy``, ``--leak``, ``--plugin``,
          ``--distribution`` — in any combination; with NO FLAGS, every check
          in that list runs, which is how CI invokes this script so a newly
          registered check needs no second edit to gate pushes.

Exit codes
----------
0  every selected check passed.
1  at least one selected check failed.
2  a check could not be executed (for example ``git`` is unavailable).

Failure policy
--------------
FAIL-CLOSED. This is a build gate, not a runtime guard: a check that cannot
run is a failure, never a pass. No check returns an empty result to mask an
error (convention 7). This declaration is asserted by tests/test_keel_phase0.py.

The scan set
------------
``--names``, ``--refs`` and ``--distribution`` (for the ``dist/keel`` prefix
only) read THE TREE THE NEXT COMMIT CAN SHIP, not the
tree git already tracks: git's index UNION the untracked-but-not-ignored
files (:func:`_scanned_files`, R45). A tracked-only scan is blind to the file
under test until the commit that ships it, so the run that says PASS and the
run that matters are different runs — this project paid for that five times.
On a CI checkout there is nothing untracked, so the scan set there is
unchanged and no CI behaviour moves.

Two consequences worth stating rather than discovering. Content is read from
the WORKING TREE, so an unstaged edit to a tracked file is scanned in its
edited form — stricter than CI, deliberately, because the edit is the thing
under test. And a GITIGNORED file is in no commit and therefore in no scan
set, which is the same rule that makes ``--refs`` treat a cited gitignored
path as nonexistent: present on a local disk, absent on a CI checkout.

One declared degradation: that path refinement consults git; on a bare export
where git is unavailable or errors, ``--refs`` falls back to filesystem-only
path resolution rather than crashing. The base resolution is never skipped —
only the CI-absence refinement degrades. The scan set itself does NOT degrade:
a git that cannot answer raises, because an empty file list would make every
scan pass by vacuum.

A SECOND declared degradation, for the same reason: ``--plugin``
(:func:`check_plugin_validate`, BL56) shells out to the external ``claude``
CLI, which this repository does not install and CI's own runners do not
carry. Its absence is reported as a visible SKIP line, never a silent PASS
and never counted toward the exit code — the binary is not part of this
project's own toolchain, so its absence is not this build's failure to
report, but a check that said nothing about it would be exactly the silent
pass BL56 records. On a machine that DOES have ``claude`` on PATH, the check
runs for real and gates like every other entry in :data:`CHECKS`.

Constraints
-----------
Python 3.10+, standard library only. Subprocess is invoked with an argument
list, never a shell string (R5). Every file read states UTF-8 explicitly.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import json
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
_HOOKS_DIR = str(_REPO_ROOT / "hooks")
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from keel_session import inject_cap_bytes  # noqa: E402

#: Token budget for always-loaded content, in estimated tokens — adopted as a
#: verified 1,200 gate, then re-measured in the adopter's project by
#: ``keel survey`` in Phase 4, which is what closes R9. The limit stays
#: strict; what changed in Phase 1 wave 3 is what is counted (see
#: ``check_budget``).
#:
#: RAISED 1200 -> 1400 on 2026-08-21 by
#: ``.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md``,
#: ratified by the owner, and the amendment is quoted rather than paraphrased
#: because the reason is the whole of its authority: the tree stood at 1068 of
#: 1200 — 132 tokens of headroom — while the compaction-survival layer's two
#: new hook registrations were MEASURED at 616 characters, 154 tokens. The
#: layer did not fit. The raise is sized to that measurement plus a small
#: margin (154 of need against 200 of new room), it pre-approves no future
#: raise, and clause 2 is the part that did not change: this stays a HARD CI
#: gate, so the next consumer of that room faces the same measurement-first
#: argument this one did.
BUDGET_TOKEN_LIMIT = 1400

#: Character-to-token estimator. Deliberately crude and deliberately fixed:
#: the gate must be reproducible on three operating systems with no tokenizer
#: dependency (R7).
CHARS_PER_TOKEN = 4

#: Directories never walked: caches, VCS internals, and per-project keel state.
SKIP_DIRS = frozenset(
    {".git", "__pycache__", ".keel", ".venv", "venv", "node_modules", ".pytest_cache"}
)

#: Git's file mode for a symlink blob. R2: none may exist in this repository.
GIT_SYMLINK_MODE = "120000"


def repo_root() -> Path:
    """Repository root, derived from this file's location (scripts/ is a child)."""
    return Path(__file__).resolve().parent.parent


def _iter_python_files(root: Path) -> list[Path]:
    """Every tracked-by-convention ``*.py`` file, skipping SKIP_DIRS."""
    found: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        found.append(path)
    return found


def _local_module_names(root: Path, py_files: list[Path]) -> set[str]:
    """First-party import names: module stems plus top-level package dirs.

    keel's own modules import each other; the dependency ban is on *third
    party* distributions, not on the repository itself.
    """
    names = {path.stem for path in py_files}
    for child in root.iterdir():
        if child.is_dir() and child.name not in SKIP_DIRS:
            if (child / "__init__.py").is_file():
                names.add(child.name)
    return names


def _top_level_imports(tree: ast.AST) -> list[tuple[str, int]]:
    """Top-level module name and line number for every import statement."""
    imports: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name.split(".")[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            # level > 0 is an explicit relative import: first-party by definition.
            if node.level == 0 and node.module:
                imports.append((node.module.split(".")[0], node.lineno))
    return imports


def check_deps(root: Path) -> list[str]:
    """R7/R14: fail if anything outside the standard library is imported.

    Returns a list of violation strings; empty means the check passed.
    """
    py_files = _iter_python_files(root)
    if not py_files:
        raise RuntimeError(f"no Python files found under {root} - check misconfigured")
    allowed = set(sys.stdlib_module_names) | _local_module_names(root, py_files)
    violations: list[str] = []
    for path in py_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        rel = path.relative_to(root).as_posix()
        for name, lineno in _top_level_imports(tree):
            if name not in allowed:
                violations.append(f"{rel}:{lineno}: non-stdlib import '{name}'")
    return violations


def check_symlinks(root: Path) -> list[str]:
    """R2: fail if git tracks any symlink (mode 120000).

    Symlinks degrade to text stubs on Windows checkouts; the repository must
    contain none. Returns a list of violation strings; empty means passed.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-s"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed ({result.returncode}): {result.stderr.strip()}")
    violations: list[str] = []
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        mode = line.split(" ", 1)[0]
        if mode == GIT_SYMLINK_MODE:
            path = line.split("\t", 1)[-1]
            violations.append(f"symlink tracked by git: {path}")
    return violations


def _frontmatter_fields(text: str) -> dict[str, str]:
    """Parse the ``name``/``description``/``disable-model-invocation`` fields
    of a YAML frontmatter block.

    Deliberately a minimal subset parser: no YAML library exists in the
    standard library, and the budget gate only needs these scalar fields.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key in ("name", "description", "disable-model-invocation"):
            fields[key] = value.strip().strip("\"'")
    return fields


def _is_user_invoked(fields: dict[str, str]) -> bool:
    """Whether a component's frontmatter marks it as not model-invocable.

    ``disable-model-invocation: true`` is the platform-documented key for a
    skill the user types (``/keel:<name>``) rather than one the model reaches
    for on its own. A component carrying it never has its description shown
    to the model unprompted, so it contributes nothing to the always-loaded
    estimate. Absence of the key — the default — means model-invoked, and the
    component is counted as before.
    """
    return fields.get("disable-model-invocation", "").strip().lower() == "true"


def _hook_command_chars(root: Path) -> tuple[int, list[str]]:
    """Characters of every ``command`` string declared in hooks/hooks.json."""
    hooks_path = root / "hooks" / "hooks.json"
    if not hooks_path.is_file():
        return 0, []
    data = json.loads(hooks_path.read_text(encoding="utf-8"))
    commands: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            command = node.get("command")
            if isinstance(command, str):
                commands.append(command)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return sum(len(c) for c in commands), commands


def _component_frontmatter_chars(root: Path) -> tuple[int, int, int]:
    """Characters of ``name`` + ``description`` for every file under
    ``agents/`` and ``skills/`` that is reachable by the model unprompted.

    These two fields are the whole of what a harness loads unconditionally for
    a component: the body of an agent is read when it is delegated to, and the
    body of a ``SKILL.md`` when the skill triggers. A file under either
    directory that declares no ``name``/``description`` frontmatter (a
    ``references/`` page, for instance) contributes nothing and is not counted
    — that is measurement, not exemption.

    A component whose frontmatter carries ``disable-model-invocation: true``
    is user-invoked only: its description is never shown to the model before
    the user types the slash command, so it is excluded from the char total
    but still tracked in the exclusion count.

    Both directories are legitimately absent in Phase 0; absent means zero,
    not an error.

    Returns ``(total_chars, counted, excluded)``.
    """
    total = 0
    counted = 0
    excluded = 0
    candidates: list[Path] = []
    for name in ("agents", "skills"):
        directory = root / name
        if directory.is_dir():
            candidates.extend(sorted(directory.rglob("*.md")))
    for path in candidates:
        fields = _frontmatter_fields(path.read_text(encoding="utf-8"))
        if not fields:
            continue
        if _is_user_invoked(fields):
            excluded += 1
            continue
        counted += 1
        total += sum(
            len(value) for key, value in fields.items()
            if key in ("name", "description")
        )
    return total, counted, excluded


def check_budget(root: Path) -> tuple[int, list[str]]:
    """R9/R32: estimate always-loaded tokens; fail above BUDGET_TOKEN_LIMIT.

    What is counted, and why it changed
    -----------------------------------
    The always-loaded surface is exactly two things: the ``name`` and
    ``description`` frontmatter of every component under ``agents/`` and
    ``skills/``, and the ``command`` strings in ``hooks/hooks.json``. Those
    are what a harness reads into every session before the user has asked for
    anything.

    Through Phase 1 wave 2 this function also charged the first forty lines of
    ``README.md`` against the same budget. That was a PROXY, valid only where a
    README genuinely is injected into the session, and in keel it measured the
    wrong thing: no harness loads keel's README
    into a session, so the number the gate reported was not the surface the
    gate exists to protect. The proxy also dominated the reading — it stood at
    2,062 of 4,733 characters, leaving 16 tokens of headroom under a limit
    that the real surface was nowhere near — so the next agent or skill would
    have broken the build over prose. A budget that fails for the wrong reason
    teaches people to raise the budget.

    The proxy is therefore dropped and the limit was NOT relaxed to pay for
    it: the number stayed at 1,200 through that change, now spent entirely on
    content that is genuinely always loaded, which is what R9 asked for and
    what ``keel survey`` re-measures in the adopter's own project. It moved
    only later, to 1,400, and only by a ratified amendment sized to a
    measurement — see ``BUDGET_TOKEN_LIMIT`` above and
    ``.keel/decisions/2026-08-21-the-always-loaded-ceiling-rises-to-1400.md``.
    The distinction matters more than the digits: a budget raised to make a
    failing build pass teaches people to raise budgets, and a budget raised by
    a written decision that names what it is buying does not.

    What "always loaded" excludes, and why
    ---------------------------------------
    A skill a human types (``disable-model-invocation: true``) costs the
    human's attention when they read the slash command list, not the model's
    context: its description is never shown to the model unprompted, only
    surfaced once the user has already invoked it by name. Such a component
    contributes zero to this estimate — counted in the exclusion tally
    printed below, not in the char total. A component with no such key is
    model-invoked by default and counted exactly as before.

    Returns ``(tokens, violations)``. The token number is returned whether the
    check passes or fails, because the trend matters as much as the gate.
    """
    hook_chars, commands = _hook_command_chars(root)
    frontmatter_chars, component_count, excluded_count = _component_frontmatter_chars(root)
    total_chars = hook_chars + frontmatter_chars
    tokens = -(-total_chars // CHARS_PER_TOKEN)  # ceiling division
    violations: list[str] = []
    if tokens > BUDGET_TOKEN_LIMIT:
        violations.append(
            f"always-loaded budget {tokens} tokens exceeds limit {BUDGET_TOKEN_LIMIT}"
        )
    print(
        f"    hooks.json commands: {len(commands)} ({hook_chars} chars); "
        f"agent/skill frontmatter: {component_count} counted ({frontmatter_chars} chars), "
        f"{excluded_count} excluded (user-invoked)"
    )
    return tokens, violations


def session_injection_tokens(env: Mapping[str, str] | None = None) -> tuple[int, int]:
    """The session-start injection cap, converted to tokens.

    This is the budget's second figure (``.keel/keel-policy.md`` -> Budget,
    "Session injection"): the knowledge-index block ``hooks/keel_session.py``
    emits at ``SessionStart``, bounded in bytes at the injector rather than
    here. The cap is read by IMPORTING ``keel_session.inject_cap_bytes``
    rather than re-declaring its default, so this figure and the cap actually
    enforced can never drift apart — lowering ``KEEL_INJECT_CAP_BYTES`` shows
    up here immediately, exactly as the policy requires. The byte-to-token
    conversion reuses ``CHARS_PER_TOKEN``, the same crude estimator
    ``check_budget`` uses, so the two figures are commensurable.

    Returns ``(cap_bytes, tokens)``. Gates nothing — there is no violations
    list, because the policy reports this figure rather than enforcing it
    (both halves are already controlled elsewhere: this one by the injector).
    """
    cap_bytes = inject_cap_bytes(env)
    tokens = -(-cap_bytes // CHARS_PER_TOKEN)  # ceiling division
    return cap_bytes, tokens


def _report(name: str, violations: list[str]) -> bool:
    """Print one result line per check; return True when the check passed."""
    if violations:
        print(f"FAIL {name}: {len(violations)} violation(s)")
        for violation in violations:
            print(f"    {violation}")
        return False
    print(f"PASS {name}")
    return True



#: Files exempt from the name check. ``NOTICE`` records licence attribution,
#: which is a legal obligation and outranks documentation style: whatever must
#: be named there is named there.
#: The orchestration dashboard is VENDORED UI adopted byte-identical from the
#: owner's predecessor harness (owner-ruled 2026-08-12, additive-merge
#: decision): its page carries its own persona vocabulary, which is adopted
#: interface text, not the narration this check exists to keep out of shipped
#: documentation. Only the vendored file is exempt; every word keel itself
#: writes about it still passes the scan.
NAME_CHECK_EXEMPT = (
    "NOTICE",
    "scripts/keel-denied-names.json",
    "scripts/keel_orchestration_dashboard.py",
)


def check_vendor_names(root: Path) -> list[str]:
    """Fail if a text file in the scan set prints a name from the stored digest list.

    Shipped documentation should teach the rule, not narrate where the rule
    came from: a reader needs "guards ship allow-fixtures because a false
    positive gets the guard uninstalled", not a comparative review of other
    software. The names are stored hashed so this repository can enforce the
    rule without carrying the strings it forbids.

    Case-insensitive by convention 3. Single words and adjacent word-pairs are
    both candidates, so two-word names are caught. The scan set is
    :func:`_scanned_files` — what the next commit can ship, not what git
    already tracks (R45).
    """
    manifest = root / "scripts" / "keel-denied-names.json"
    if not manifest.is_file():
        return ["scripts/keel-denied-names.json missing (fail-closed)"]
    digests = set(json.loads(manifest.read_text(encoding="utf-8"))["hashes"])
    findings: list[str] = []
    for rel in _scanned_files(root):
        if rel in NAME_CHECK_EXEMPT:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            words = re.findall(r"[a-z0-9][a-z0-9-]*", line.lower())
            candidates = set(words) | {f"{a} {b}" for a, b in zip(words, words[1:])}
            if any(hashlib.sha256(c.encode()).hexdigest() in digests for c in candidates):
                findings.append(f"{rel}:{lineno}")
    return findings


def _git_paths(root: Path, args: list[str], what: str) -> list[str]:
    """``git`` NUL-separated output parsed as repo-relative POSIX paths.

    FAIL-CLOSED (module policy): git failing to answer raises rather than
    returning an empty list. An empty list here is not a harmless zero — it
    is every file-scanning check passing because it was handed nothing.

    ``-z`` and bytes, deliberately, for the reason ``_gitignored_paths``
    already gives: it disables git's ``core.quotePath`` escaping, which would
    otherwise return a non-ASCII filename C-quoted, resolve to nothing on
    disk, and let that file be SKIPPED by every scan without a word. A name
    that is not valid UTF-8 raises for the same reason — it is a file this
    checker cannot read, which is a failure, never a pass.
    """
    try:
        out = subprocess.run(
            ["git", *args, "-z"], cwd=str(root), capture_output=True, check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git {what}: {exc}") from exc
    if out.returncode != 0:
        detail = out.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {what} failed ({out.returncode}): {detail}")
    try:
        stdout = out.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"git {what} named a path this checker cannot decode as UTF-8: {exc}"
        ) from exc
    return [path for path in stdout.split("\x00") if path]


def _tracked_text_files(root: Path) -> list[str]:
    """Every path in git's index, as repo-relative POSIX strings.

    Empty means git tracks nothing here, which is a misconfiguration and not
    a clean tree: it raises rather than reporting a scan of no files.
    """
    tracked = _git_paths(root, ["ls-files"], "ls-files")
    if not tracked:
        raise RuntimeError(f"git tracks no files under {root} - check misconfigured")
    return tracked


def _untracked_text_files(root: Path) -> list[str]:
    """Every untracked, NOT-ignored path, as repo-relative POSIX strings.

    ``--exclude-standard`` applies the same ignore rules a checkout would, so
    an ignored file — which ships to no CI checkout — never enters the scan
    set. Empty is legitimate here and means exactly what it says: nothing has
    been written that git has not been told about.
    """
    return _git_paths(
        root, ["ls-files", "--others", "--exclude-standard"], "ls-files --others"
    )


def _scanned_files(root: Path) -> list[str]:
    """The tree the next commit can ship: tracked UNION untracked-not-ignored.

    R45, and the single seam ``--names`` and ``--refs`` take their file list
    from. Scanning only what git already tracks makes a check blind to the
    file under test until the commit that ships it — a green local run and a
    red CI run over the same work, five times in this project's history. A
    file that is written but not staged is in this set, so it is scanned now
    exactly as CI will scan it once committed.
    """
    return sorted(set(_tracked_text_files(root)) | set(_untracked_text_files(root)))


#: The register that defines every citable identifier. A citation anywhere in
#: the tree is resolvable only if this document carries a matching heading.
RULES_DOC = "docs/keel-rules.md"

#: A citation in prose: a rule (R), finding (F) or decision (D) identifier.
CITATION_RE = re.compile(r"\b([RFD][0-9]{1,2})\b")

#: An entry heading in the register: ``### R19 — no fixed ports``.
RULES_HEADING_RE = re.compile(r"^#{2,6}\s+([RFD][0-9]{1,2})\b", re.MULTILINE)

#: Intra-repository path references, checked in tracked markdown. The prefixes
#: are the shipped directories: a reference to one of them is a claim that a
#: file exists, and the claim is checked rather than trusted.
PATH_REF_RE = re.compile(
    r"\b((?:docs|scripts|hooks|agents|templates|tests)/[A-Za-z0-9._/-]*)"
)

#: Punctuation a path may be followed by in prose, stripped before resolving.
PATH_TRAILING = ".,;:!?)]\"'`*"

#: Append-only machine-written record streams, exempt from the CITATION half
#: of ``--refs`` and named one by one rather than matched by a glob, so the
#: exemption stays auditable. These files quote what happened — a Bash command
#: line, a tool payload — and a session that types a rule identifier into a
#: command therefore writes that identifier into the record verbatim. The
#: citation half exists to keep AUTHORED prose honest; a transcript is
#: evidence, and evidence is never edited to satisfy a documentation gate.
#: Authored files under ``.keel/`` — plans, decisions, knowledge records — are
#: NOT exempt: those are exactly the documents four of this trap's five
#: strikes were found in.
CITATION_SCAN_EXEMPT = (
    ".keel/audit/keel-audit.jsonl",
    ".keel/queue/keel-observations.jsonl",
)

#: A small, named set of path violations this check accepts rather than
#: fails on — read by ``check_refs``. JSON, and deliberately not markdown:
#: the path-resolution half of this check only scans tracked *.md* files
#: (see ``is_markdown`` below), so a waiver naming a path that does not
#: exist never becomes a citation this checker itself then tries to
#: resolve — the trap a waiver mechanism for this check would otherwise
#: fall into.
REFS_WAIVER_PATH = "scripts/keel-refs-waiver.json"


def _load_refs_waivers(root: Path) -> list[dict]:
    """The waiver entries: each names a file, a line and the exact path that
    line cites and does not resolve. No file, or a file that fails to parse,
    means no waivers — fail-closed, matching this module's stated policy."""
    path = root / REFS_WAIVER_PATH
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    return [e for e in data.get("waivers", []) if isinstance(e, dict)]


def check_refs(root: Path) -> list[str]:
    """R18/R15: every citation resolves to an entry, every path to a file.

    Thin wrapper around :func:`_check_refs_counted`, kept for callers that
    only want the final violation list (this checker's own tests among
    them). Returns a list of violation strings; empty means the check
    passed, INCLUDING when every violation found was covered by a waiver
    entry in :data:`REFS_WAIVER_PATH` — the CLI reports that suppression by
    name (see ``main``); this function does not.
    """
    findings, _found, _waived = _check_refs_counted(root)
    return findings


def _check_refs_counted(root: Path) -> tuple[list[str], int, int]:
    """As :func:`check_refs`, plus how many path violations were found
    before waiving and how many of those a waiver entry covered.

    Two failures, one check, because they are the same defect: a shipped
    document asserting something the tree cannot back. (a) Every ``R``/``F``/
    ``D`` identifier cited in any text file in the scan set must have a
    heading in ``docs/keel-rules.md`` — this half has no waiver, and its one
    exemption is :data:`CITATION_SCAN_EXEMPT`, the machine-written record
    streams, which quote commands rather than assert claims. (b) Every
    reference in scan-set markdown to a path under ``docs/``, ``scripts/``,
    ``hooks/``, ``agents/``, ``templates/`` or ``tests/`` must exist in the
    working tree — code fences included, since a dead path teaches the same
    wrong thing whether or not it is formatted as code — AND must not be
    gitignored: an ignored path is present on the local disk but absent on a
    CI checkout, so it is a violation exactly as if absent (the divergence
    that let a local pass hide a CI failure). Both halves read
    :func:`_scanned_files`, so a document is checked while it is being
    written rather than after the commit that ships it (R45); the path half's
    ignored-is-absent rule is that same scan set seen from the other side.
    A path violation matching an entry in
    :data:`REFS_WAIVER_PATH` (same file, same line, same exact path) is
    waived rather than reported — but WAIVED IS NOT HIDDEN: it is counted in
    the second return value, and the CLI prints that count. An entry whose
    named violation no longer occurs there — the path now resolves, or that
    line no longer cites it — is itself reported as a violation (a stale
    waiver), because a waiver nothing needs any more is exactly how this
    mechanism would otherwise accumulate silently and stop meaning anything.
    A new unresolved path anywhere, including a different line of a file that
    already has a waiver entry, is never covered by it and still fails.

    FAIL-CLOSED: a missing or empty register is a violation, not a pass. An
    absent register would otherwise make every citation in the tree resolvable
    by vacuum. The gitignore refinement alone is FAIL-SAFE (see the module
    docstring): without a usable git, resolution stays filesystem-only.

    Returns ``(findings, found, waived)``: ``findings`` is the final
    violation list (waived violations removed, stale-waiver violations
    added); ``found`` and ``waived`` count path violations only.
    """
    rules_path = root / RULES_DOC
    if not rules_path.is_file():
        return ([f"{RULES_DOC} is missing: no citation in the tree can resolve"], 0, 0)
    register = set(RULES_HEADING_RE.findall(rules_path.read_text(encoding="utf-8")))
    if not register:
        return ([f"{RULES_DOC} declares no entry heading"], 0, 0)

    waivers = _load_refs_waivers(root)
    matched = [False] * len(waivers)

    def _waiver_index(rel: str, lineno: int, target: str) -> int | None:
        for i, entry in enumerate(waivers):
            if (
                entry.get("file") == rel
                and entry.get("line") == lineno
                and entry.get("path") == target
            ):
                return i
        return None

    findings: list[str] = []
    found = 0
    waived = 0
    present: list[tuple[str, int, str]] = []  # claims re-checked against git
    scanned_files = list(_scanned_files(root))
    scanned = set(scanned_files)
    for rel in scanned_files:
        try:
            text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        is_markdown = rel.lower().endswith(".md")
        cites_are_claims = rel not in CITATION_SCAN_EXEMPT
        for lineno, line in enumerate(text.splitlines(), 1):
            for identifier in CITATION_RE.findall(line) if cites_are_claims else ():
                if identifier not in register:
                    findings.append(
                        f"{rel}:{lineno}: citation {identifier} has no entry in {RULES_DOC}"
                    )
            if not is_markdown:
                continue
            for reference in PATH_REF_RE.findall(line):
                target = reference.rstrip(PATH_TRAILING)
                if not target:
                    continue
                if (root / target).exists():
                    present.append((rel, lineno, target))
                    continue
                found += 1
                idx = _waiver_index(rel, lineno, target)
                if idx is not None:
                    matched[idx] = True
                    waived += 1
                else:
                    findings.append(f"{rel}:{lineno}: path does not exist: {target}")
    ignored = _gitignored_paths(root, sorted({t for _, _, t in present}))
    for rel, lineno, target in present:
        if target in ignored:
            found += 1
            idx = _waiver_index(rel, lineno, target)
            if idx is not None:
                matched[idx] = True
                waived += 1
            else:
                findings.append(
                    f"{rel}:{lineno}: path is gitignored (absent on a CI checkout): {target}"
                )
    for i, entry in enumerate(waivers):
        if matched[i]:
            continue
        if entry.get("file") not in scanned:
            # INAPPLICABLE, NOT STALE, and this distinction is what makes the
            # register portable across a published cut. A waiver is a claim
            # about a violation at a file and a line. If the file is not in
            # THIS tree's scan set, the claim is not false — it simply has
            # nothing to be true or false about here, and demanding its removal
            # would demand a register that cannot serve both the development
            # repository and a cut that ships without its records.
            # Anti-accumulation is preserved where it bites: an entry whose
            # file IS present and whose violation is gone still fails below,
            # and ``inapplicable_waivers`` keeps these counted rather than
            # hidden (the CLI prints the number).
            continue
        findings.append(
            f"{REFS_WAIVER_PATH}: stale waiver for {entry.get('file')}:"
            f"{entry.get('line')} naming {entry.get('path')!r} — that "
            "violation no longer occurs there; remove this waiver entry"
        )
    return findings, found, waived


def inapplicable_waivers(root: Path) -> list[str]:
    """Waiver entries whose named file is absent from this tree's scan set.

    Reported by the CLI as a count so that suppression stays visible: these are
    not failures, but a register accumulating entries no tree can ever match
    would be exactly the drift the stale-waiver rule exists to catch.

    Why this exists: a published cut ships the record surfaces EMPTY by
    declaration, so a waiver naming a path under the record directory can never
    match there. Before this distinction the mirror's ``refs`` check could not
    pass — 4 violations, all of them entries that are perfectly live in the
    development repository. Returns ``"<file>:<line>"`` strings, sorted.
    """
    waivers = _load_refs_waivers(root)
    scanned = set(_scanned_files(root))
    return sorted(
        f"{entry.get('file')}:{entry.get('line')}"
        for entry in waivers
        if entry.get("file") not in scanned
    )


def _gitignored_paths(root: Path, paths: list[str]) -> set[str]:
    """The subset of ``paths`` that git would ignore, in one batched call.

    An ignored path exists on the local disk but never on a CI checkout, so
    ``check_refs`` treats it as absent. FAIL-SAFE, deliberately: on a bare
    export git is unavailable or errors, and this returns the empty set so
    ``--refs`` degrades to filesystem-only resolution instead of crashing —
    the one declared degradation in the module docstring.
    """
    if not paths:
        return set()
    # NUL-separated (-z) and bytes, deliberately: a text-mode pipe on Windows
    # rewrites "\n" to "\r\n", which git reads as paths ending in CR — and -z
    # also disables output quoting. UTF-8 is stated explicitly on both sides.
    try:
        result = subprocess.run(
            ["git", "check-ignore", "--stdin", "-z"],
            cwd=str(root),
            input=b"\x00".join(p.encode("utf-8") for p in paths) + b"\x00",
            capture_output=True,
            check=False,
        )
    except OSError:
        return set()
    # check-ignore exits 0 (some path is ignored) or 1 (none is); anything
    # else means git could not answer here, and the fail-safe applies.
    if result.returncode not in (0, 1):
        return set()
    stdout = result.stdout.decode("utf-8", errors="replace")
    return {p for p in stdout.split("\x00") if p}


#: The read-only toolset a reviewer agent may hold, compared as a set —
#: order-insensitive, nothing extra, nothing missing (R22).
REVIEWER_TOOLS = frozenset({"Read", "Grep", "Glob"})

#: The house-contract headings every reviewer body carries, in this order.
REVIEWER_HEADINGS = ("Scope", "Confidence floor", "What NOT to flag", "Verdict")

#: A delegation-grade description names its trigger first, so the
#: orchestrator can route on it without reading the body.
REVIEWER_DESCRIPTION_PREFIXES = ("Use after ", "Use when ")

#: The confidence floor as a value this checker reads (R32). Deliberately
#: case-sensitive (R1): the line is a contract literal that a machine parses,
#: so its casing is part of the contract; the lowercase block-fixture under
#: tests/fixtures/agents/ covers the other case.
FLOOR_LINE_RE = re.compile(r"^Confidence floor: \d{1,3}%$")

#: The routing law's model class per singular role (R32 pattern: the
#: confidence floor above is the same shape — a contract value a checker
#: reads rather than greps for). This constant deliberately duplicates the
#: intent of the routing table in ``.keel/keel-policy.md`` (Routing section):
#: that file is model-read-only, so the mapping a machine checks against is
#: restated here rather than parsed out of prose. A role absent from this
#: mapping and not covered by ``REVIEWER_MODEL_CLASS`` below is ungoverned —
#: this check has nothing to say about its ``model:`` value.
AGENT_MODEL_CLASSES = {
    "researcher": "haiku",
    "executor": "sonnet",
    "executor-deep": "opus",
}

#: The model class every ``reviewer-*`` agent is routed to (same duplication
#: constraint as ``AGENT_MODEL_CLASSES`` above).
REVIEWER_MODEL_CLASS = "sonnet"


def _expected_model_class(stem: str) -> str | None:
    """The routing law's model class for an agent filename stem, or ``None``
    if the stem names no governed role."""
    if stem in AGENT_MODEL_CLASSES:
        return AGENT_MODEL_CLASSES[stem]
    if stem.startswith("reviewer-"):
        return REVIEWER_MODEL_CLASS
    return None

#: A second-level heading in an agent body.
BODY_HEADING_RE = re.compile(r"^## (.+?)\s*$", re.MULTILINE)


def _agent_frontmatter(text: str) -> tuple[dict[str, str], str, str | None]:
    """Parse an agent file into ``(frontmatter fields, body, error)``.

    Unlike ``_frontmatter_fields`` this keeps every top-level scalar key,
    because the agent contract is about which keys exist, not two of them.
    ``error`` is ``None`` on success, else a clause tag naming what is
    structurally wrong with the frontmatter block itself.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "", "no_frontmatter"
    fields: dict[str, str] = {}
    close: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            close = index
            break
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip("\"'")
    if close is None:
        return {}, "", "unterminated_frontmatter"
    return fields, "\n".join(lines[close + 1 :]), None


def _body_sections(body: str) -> list[tuple[str, str]]:
    """Every ``## `` heading in an agent body with its section text, in order."""
    matches = list(BODY_HEADING_RE.finditer(body))
    sections: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections.append((match.group(1), body[match.end() : end]))
    return sections


def check_agents(root: Path) -> list[str]:
    """R22/R28: agents declare explicit tools; reviewers honour the house contract.

    Three clauses, one check. (a) Every ``agents/*.md`` declares frontmatter
    with ``name``, ``description`` and an explicit, non-empty comma-separated
    ``tools`` list, and its ``name`` matches its filename stem (R22: an agent
    with no tools field inherits everything, including Write, which turns a
    reviewer into an editor on the one machine nobody checked). (b) Every
    ``reviewer-*.md`` additionally holds exactly the read-only toolset, a
    delegation-grade description, the four contract headings in order,
    exactly one floor line located inside its own section (R32), and at
    least one bullet under "What NOT to flag". (c) Every agent naming a role
    the routing law governs (``researcher``, ``executor``, ``executor-deep``,
    ``reviewer-*``) declares a ``model:`` matching ``_expected_model_class``
    for that role — a missing or mismatched value is the drift the
    ``.keel/keel-policy.md`` routing table exists to prevent silently.

    Everything is asserted structurally — frontmatter parsed, headings and
    tool lists compared as values — never by substring presence (R28: a grep
    for "80" passes on a line number or the year 1980 and guards nothing).

    An absent ``agents/`` directory is a pass, not an error: keel's checks
    never fail an adopter on day one. Returns a list of violation strings,
    each naming the file and the clause violated; empty means passed.
    """
    agents_dir = root / "agents"
    if not agents_dir.is_dir():
        return []
    violations: list[str] = []
    for path in sorted(agents_dir.glob("*.md")):
        rel = f"agents/{path.name}"
        fields, body, error = _agent_frontmatter(path.read_text(encoding="utf-8"))
        if error:
            violations.append(
                f"{rel}: {error}: frontmatter must open and close with '---'"
            )
            continue
        for key in ("name", "description", "tools"):
            if key not in fields:
                violations.append(f"{rel}: missing_{key}: no '{key}' key in frontmatter")
        tools = [t.strip() for t in fields.get("tools", "").split(",") if t.strip()]
        if "tools" in fields and not tools:
            violations.append(
                f"{rel}: empty_tools: 'tools' must be an explicit, non-empty "
                f"comma-separated list (R22)"
            )
        if "name" in fields and fields["name"] != path.stem:
            violations.append(
                f"{rel}: name_mismatch: name '{fields['name']}' is not the "
                f"filename stem '{path.stem}'"
            )
        expected_model = _expected_model_class(path.stem)
        if expected_model is not None:
            model = fields.get("model", "").strip()
            if not model:
                violations.append(
                    f"{rel}: model_missing: no 'model' key in frontmatter; "
                    f"routing law assigns '{expected_model}' to this role"
                )
            elif model != expected_model:
                violations.append(
                    f"{rel}: model_mismatch: model '{model}' does not match "
                    f"the routing law's '{expected_model}' for this role"
                )
        if not path.stem.startswith("reviewer-"):
            continue
        # -- the reviewer house contract ----------------------------------
        if "tools" in fields and set(tools) != set(REVIEWER_TOOLS):
            violations.append(
                f"{rel}: reviewer_tools: a reviewer holds exactly Read, Grep, "
                f"Glob (read-only); found '{fields['tools']}'"
            )
        description = fields.get("description", "")
        if description and not description.startswith(REVIEWER_DESCRIPTION_PREFIXES):
            violations.append(
                f"{rel}: reviewer_description: description must start with "
                f"'Use after ' or 'Use when '"
            )
        sections = _body_sections(body)
        found = [heading for heading, _ in sections]
        missing = [h for h in REVIEWER_HEADINGS if h not in found]
        for heading in missing:
            violations.append(f"{rel}: heading_missing: no '## {heading}' section")
        if not missing:
            positions = [found.index(heading) for heading in REVIEWER_HEADINGS]
            if positions != sorted(positions):
                violations.append(
                    f"{rel}: headings_out_of_order: contract headings must run "
                    f"{', '.join(REVIEWER_HEADINGS)}; found {', '.join(found)}"
                )
        by_name = dict(sections)
        floor_section = by_name.get("Confidence floor")
        if floor_section is not None:
            floor_lines = [
                line for line in floor_section.splitlines() if FLOOR_LINE_RE.match(line)
            ]
            if len(floor_lines) != 1:
                violations.append(
                    f"{rel}: floor_line: the Confidence floor section must carry "
                    f"exactly one 'Confidence floor: NN%' line; found {len(floor_lines)}"
                )
        not_flag_section = by_name.get("What NOT to flag")
        if not_flag_section is not None and not any(
            line.startswith("- ") for line in not_flag_section.splitlines()
        ):
            violations.append(
                f"{rel}: no_not_to_flag_bullet: the 'What NOT to flag' section "
                f"carries no '- ' bullet"
            )
    return violations


#: The feature registry: which shipped component belongs to which feature.
#: Editions are generated along these seams, so the registry must stay closed.
FEATURES_REGISTRY = "scripts/keel-features.json"

#: Directories whose every file must be claimed by exactly one feature. These
#: are the component trees an edition curates; a file outside any feature
#: ships in no edition, silently.
CLAIMED_DIRS = ("agents", "skills")

#: A prose invocation of a keel skill inside a SKILL.md, e.g. ``/keel:moor``.
SKILL_INVOCATION_RE = re.compile(r"/keel:([a-z][a-z0-9-]*)")


def _component_claims(component: str, rel: str) -> bool:
    """Whether a registry component path claims the repo-relative file ``rel``.

    A component is either a file path, which claims exactly itself, or a
    directory path (trailing slash optional), which claims everything
    beneath it.
    """
    base = component.rstrip("/")
    return rel == base or rel.startswith(base + "/")


def check_closure(root: Path) -> list[str]:
    """The feature registry is closed: every bundle carries what it invokes.

    Three clauses, one check, because editions are generated from this
    registry and each clause is a way an edition could ship broken. (a)
    Every component path in ``scripts/keel-features.json`` exists in the
    working tree, and every file under ``agents/`` and ``skills/`` is
    claimed by exactly one feature — an unclaimed file ships in no edition,
    a double-claimed one makes two features disagree about who owns it. (b)
    Every ``requires`` entry names a defined feature and the requirement
    graph is acyclic, because an edition is the transitive closure of what
    its features require. (c) The bundle-closure rule: every prose
    invocation of the form ``/keel:<name>`` in a ``skills/*/SKILL.md`` or a
    ``skills/*/references/*.md`` page must resolve to an existing
    ``skills/<name>/`` skill, and the invoking page's feature must equal or
    (transitively) require the feature owning the invoked skill — no
    edition may ship a page that invokes a skill the edition leaves out.

    FAIL-CLOSED: a missing, unparseable or empty registry is a violation,
    never a pass. Returns a list of violation strings, each naming the file
    and the clause violated; empty means passed.
    """
    registry_path = root / FEATURES_REGISTRY
    if not registry_path.is_file():
        return [f"{FEATURES_REGISTRY}: missing_registry: no feature registry (fail-closed)"]
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return [f"{FEATURES_REGISTRY}: malformed_registry: not valid JSON: {exc}"]
    features = data.get("features")
    if not isinstance(features, dict) or not features:
        return [f"{FEATURES_REGISTRY}: empty_registry: no non-empty 'features' table"]

    violations: list[str] = []

    def owners_of(rel: str) -> list[str]:
        """Every feature whose components claim ``rel``, sorted for stable output."""
        return sorted(
            feature
            for feature, spec in features.items()
            if any(_component_claims(c, rel) for c in spec.get("components", []))
        )

    # -- clause (a): paths exist; agents/ and skills/ files have one owner --
    for feature in sorted(features):
        for component in features[feature].get("components", []):
            if not (root / component.rstrip("/")).exists():
                violations.append(
                    f"{FEATURES_REGISTRY}: missing_component: feature "
                    f"'{feature}' names a path that does not exist: {component}"
                )
    for name in CLAIMED_DIRS:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            owners = owners_of(rel)
            if not owners:
                violations.append(
                    f"{rel}: orphan_component: claimed by no feature in {FEATURES_REGISTRY}"
                )
            elif len(owners) > 1:
                violations.append(
                    f"{rel}: double_claim: claimed by features {', '.join(owners)}"
                )

    # -- clause (b): requirements resolve, and the graph has no cycle -------
    for feature in sorted(features):
        for req in features[feature].get("requires", []):
            if req not in features:
                violations.append(
                    f"{FEATURES_REGISTRY}: unknown_requires: feature "
                    f"'{feature}' requires undefined feature '{req}'"
                )

    finished: set[str] = set()

    def walk(node: str, trail: list[str]) -> None:
        for req in features[node].get("requires", []):
            if req not in features:
                continue  # already reported as unknown_requires
            if req in trail:
                cycle = trail[trail.index(req):] + [req]
                violations.append(
                    f"{FEATURES_REGISTRY}: requires_cycle: {' -> '.join(cycle)}"
                )
                continue
            if req not in finished:
                walk(req, trail + [req])
        finished.add(node)

    for feature in sorted(features):
        if feature not in finished:
            walk(feature, [feature])

    # -- clause (c): the bundle-closure rule --------------------------------
    def closure_of(feature: str) -> set[str]:
        """The feature plus everything it transitively requires."""
        seen = {feature}
        frontier = [feature]
        while frontier:
            for req in features[frontier.pop()].get("requires", []):
                if req in features and req not in seen:
                    seen.add(req)
                    frontier.append(req)
        return seen

    skills_dir = root / "skills"
    if skills_dir.is_dir():
        # References pages ship inside their skill's bundle, so their prose
        # invocations bind the edition exactly as the SKILL.md's do.
        prose_pages = sorted(
            [*skills_dir.glob("*/SKILL.md"), *skills_dir.glob("*/references/*.md")]
        )
        for page in prose_pages:
            rel = page.relative_to(root).as_posix()
            invoker_owners = owners_of(rel)
            text = page.read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), 1):
                for name in SKILL_INVOCATION_RE.findall(line):
                    if not (root / "skills" / name / "SKILL.md").is_file():
                        violations.append(
                            f"{rel}:{lineno}: unresolved_invocation: /keel:{name} "
                            f"resolves to no skills/{name}/ skill"
                        )
                        continue
                    invoked_owners = owners_of(f"skills/{name}/SKILL.md")
                    if len(invoker_owners) != 1 or len(invoked_owners) != 1:
                        continue  # the ownership defect is already reported by clause (a)
                    if invoked_owners[0] not in closure_of(invoker_owners[0]):
                        violations.append(
                            f"{rel}:{lineno}: bundle_escape: /keel:{name} is owned "
                            f"by feature '{invoked_owners[0]}', which feature "
                            f"'{invoker_owners[0]}' neither is nor requires"
                        )
    return violations


#: The arming file's repo-relative path. Absence is a legitimate state (a
#: tier-0 tree, or a project mid-``/keel:lay``), never an error — the same
#: convention :func:`check_agents` applies to a missing ``agents/`` directory.
POLICY_FILE = ".keel/keel-policy.md"

#: The ratified decision that put this rule in force, cited in every
#: violation this check reports so the message names both what broke and
#: why it is enforced.
POLICY_VERSION_DECISION = ".keel/decisions/2026-08-25-the-law-carries-its-own-version.md"

#: The staged Amendment log table row for a version, e.g. matching
#: ``| 1.0.0 | 2026-08-25 | owner, in chat | ... |``. Anchored to the start of
#: a line so a version number appearing inside prose elsewhere in the file
#: (a decision date, a cited change) is never mistaken for its own row.
_AMENDMENT_ROW_RE_TEMPLATE = r"^\|\s*{version}\s*\|"

#: The heading the Amendment log table lives under, and the next ``## ``
#: heading (any) that closes its section.
_AMENDMENT_HEADING_RE = re.compile(r"^## Amendment log\s*$", re.MULTILINE)
_NEXT_H2_RE = re.compile(r"^## ", re.MULTILINE)


def _git_text(root: Path, args: list[str], what: str) -> str:
    """``git``'s stdout as text. FAIL-CLOSED, exactly as :func:`_git_paths` is:
    a nonzero exit RAISES rather than being read as an answer.

    ``_git_paths``' twin for the commands whose output is content rather than a
    path list (``git show``, ``git ls-tree``). Same idiom for the same reason:
    git declining to answer is a failure, and a failure that returns "nothing"
    is a check that passes because it never looked.
    """
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git {what}: {exc}") from exc
    if out.returncode != 0:
        raise RuntimeError(f"git {what} failed ({out.returncode}): {out.stderr.strip()}")
    return out.stdout


def _git_status(root: Path, args: list[str], what: str) -> tuple[int, str]:
    """A git command's exit code and stderr, for the two questions whose ANSWER
    IS an exit code rather than output. Only failing to launch git at all
    raises here; the caller says which codes mean "no" and which mean "broken",
    and every code it has not accounted for raises there.
    """
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"cannot run git {what}: {exc}") from exc
    return out.returncode, out.stderr.strip()


def _git_repository(root: Path) -> bool:
    """Whether ``root`` sits inside a git repository at all.

    A tree with no repository is a legitimately-absent surface — a bare
    export, a synthetic fixture tree — and this is the one nonzero git exit
    this helper reads as an answer instead of an error. It is only read that
    way when the filesystem agrees: if ``root/.git`` EXISTS and git still
    cannot name a git directory, the repository is BROKEN rather than absent,
    which raises.
    """
    code, stderr = _git_status(root, ["rev-parse", "--git-dir"], "rev-parse --git-dir")
    if code == 0:
        return True
    if (root / ".git").exists():
        raise RuntimeError(
            f"git cannot name a git directory under {root} although .git exists "
            f"({code}): {stderr}"
        )
    return False


def _git_head_exists(root: Path) -> bool:
    """Whether ``HEAD`` names a commit at all.

    Answered from the REF DATABASE, never by resolving an object, so "no
    commit yet" and "the repository is damaged" stay distinguishable — the
    distinction ``git rev-parse --verify --quiet`` throws away, since it
    reports exit 1 for an unborn HEAD and for a ref it cannot read alike.
    Verified against fixtures rather than assumed (see
    ``tests/test_keel_policy_version_t320.py``):

    * ``git symbolic-ref --quiet HEAD`` exits 0 and names the checked-out
      branch. ``git show-ref --verify --quiet`` on that branch then exits 0
      when the branch has a commit, 1 when it does not — an UNBORN HEAD: a
      fresh repository, or ``checkout --orphan`` — and 128 when the ref exists
      but is damaged, which raises.
    * ``symbolic-ref`` exit 1 means a DETACHED HEAD, which by definition
      already names a commit. Any other exit from it raises.
    """
    code, stderr = _git_status(root, ["symbolic-ref", "--quiet", "HEAD"], "symbolic-ref HEAD")
    if code == 1:
        return True  # detached HEAD: it names a commit directly
    if code != 0:
        raise RuntimeError(f"git symbolic-ref HEAD failed ({code}): {stderr}")
    branch = _git_text(root, ["symbolic-ref", "--quiet", "HEAD"], "symbolic-ref HEAD").strip()
    code, stderr = _git_status(
        root, ["show-ref", "--verify", "--quiet", branch], f"show-ref {branch}"
    )
    if code == 0:
        return True
    if code == 1:
        return False  # unborn: the checked-out branch has no commit yet
    raise RuntimeError(f"git show-ref {branch} failed ({code}): {stderr}")


#: The two surfaces :func:`_git_show_path` reads, and the only two values its
#: ``rev`` argument accepts: the last commit, and git's index. Anything else is
#: a caller error, not a revision to guess at — see :func:`_git_show_path`.
_GIT_SURFACES = ("HEAD", "")


def _git_show_path(root: Path, rev: str, path: str) -> str | None:
    """Text of ``path`` at ``rev`` — ``"HEAD"`` for the last commit, ``""`` for
    git's index — or ``None`` when that surface is genuinely ABSENT.

    Absence and failure are different answers, and this helper keeps them
    apart (T320 review, 2026-08-25: the first version collapsed every nonzero
    ``git show`` into ``None``, so a corrupt object store or an unresolvable
    ref read as "the file isn't there" — which reads as a pass). ``None`` is
    returned only for absences GIT REPORTED, each established by a command
    whose exit status says so and nothing else:

    * there is no git repository at ``root`` (:func:`_git_repository`);
    * ``HEAD`` names no commit yet (:func:`_git_head_exists`) — a fresh
      repository, where the index side may still hold a staged file;
    * ``path`` is not listed at that surface: ``git ls-tree`` (for the commit)
      or ``git ls-files`` (for the index) exits 0 and names nothing.

    Everything else — git unavailable, a damaged ref, a missing object, an
    unreadable index, a path listed but unresolvable — raises
    :class:`RuntimeError`, matching :func:`_git_paths` and this module's
    FAIL-CLOSED policy, so :func:`check_policy_version` reports "check could
    not run" (exit 2) rather than passing on a broken git.

    ``rev`` is restricted to :data:`_GIT_SURFACES` and a ``ValueError`` for
    anything else, deliberately: ``git rev-parse --verify --quiet`` reports the
    same exit 1 for "does not exist yet" as for a revision it cannot parse, so
    an arbitrary rev could not be classified honestly here. The check compares
    exactly these two surfaces, and this helper refuses to pretend otherwise.
    """
    if rev not in _GIT_SURFACES:
        raise ValueError(
            f"_git_show_path reads HEAD or the index, not {rev!r} "
            f"(allowed: {_GIT_SURFACES})"
        )
    if not _git_repository(root):
        return None
    if rev:
        if not _git_head_exists(root):
            return None
        listed = _git_text(
            root, ["ls-tree", "--name-only", "-z", rev, "--", path], f"ls-tree {rev}"
        )
    else:
        listed = _git_text(root, ["ls-files", "-z", "--", path], "ls-files (index)")
    if not listed.replace("\x00", "").strip():
        return None
    return _git_text(root, ["show", f"{rev}:{path}"], f"show {rev}:{path}")


def _policy_version(text: str) -> str | None:
    """The ``version:`` frontmatter value, or ``None`` if absent or the
    frontmatter block itself is missing/unterminated."""
    fields, _body, error = _agent_frontmatter(text)
    if error:
        return None
    return fields.get("version") or None


def _amendment_log_has_row(text: str, version: str) -> bool:
    """Whether the staged Amendment log table carries a row for ``version``."""
    heading = _AMENDMENT_HEADING_RE.search(text)
    if not heading:
        return False
    section = text[heading.end():]
    next_heading = _NEXT_H2_RE.search(section)
    if next_heading:
        section = section[: next_heading.start()]
    row_re = re.compile(_AMENDMENT_ROW_RE_TEMPLATE.format(version=re.escape(version)), re.MULTILINE)
    return bool(row_re.search(section))


def check_policy_version(root: Path) -> list[str]:
    """The arming file's law names its own version (T230/T320,
    ``POLICY_VERSION_DECISION``): a staged change to ``.keel/keel-policy.md``'s
    text must also move its ``version:`` frontmatter line, and the new
    version must gain a row in the staged Amendment log table.

    What is compared
    -----------------
    The STAGED tree (git's index) against HEAD — not the working tree,
    because the policy file is policy-locked and this check exists to gate
    the commit that would ship a ratified change, not an unstaged edit sitting
    in a locked file no tool wrote (R45's "next commit can ship" scan set
    does not apply here for that reason: an unstaged edit to a policy-locked
    file is not a state any tool produces, and staging is the act this check
    watches for).

    Absence is not a new failure class
    -----------------------------------
    When the file is absent at BOTH the index and HEAD — a tier-0 tree, or a
    project mid-``/keel:lay`` that has not adopted keel's arming file yet —
    this passes silently, the same convention :func:`check_agents` applies to
    a missing ``agents/`` directory: keel's checks never fail an adopter on a
    surface that legitimately does not exist yet. When the staged and HEAD
    texts are identical (including both entirely absent — already covered —
    or present and unchanged), there is no staged change to gate and this
    passes.

    Absent is not the same as unknown, either: a git that cannot answer
    (:func:`_git_show_path`) raises instead of reporting absence, so this
    check reports "could not run" rather than passing on a broken repository.

    The two failure clauses
    ------------------------
    Fire only when the staged text differs from HEAD's:

    (a) the staged ``version:`` line must differ from HEAD's — including the
        case where the staged text carries no ``version:`` line at all, which
        is a regression now that the baseline (1.0.0) exists rather than a
        legitimate absence, and fails just as loudly as a version that failed
        to move.
    (b) the staged Amendment log table must carry a row for the new version.

    Returns a list of violation strings, each naming the rule and
    :data:`POLICY_VERSION_DECISION`; empty means passed.
    """
    head_text = _git_show_path(root, "HEAD", POLICY_FILE)
    staged_text = _git_show_path(root, "", POLICY_FILE)
    if head_text is None and staged_text is None:
        return []
    before = head_text or ""
    after = staged_text or ""
    if before == after:
        return []

    version_before = _policy_version(before)
    version_after = _policy_version(after)
    rule = (
        "the law names its own version: the repository checks refuse a "
        "policy whose text changed without its version moving"
    )
    if version_after is None:
        return [
            f"{POLICY_FILE}: staged text carries no 'version:' frontmatter "
            f"line — {rule} (see {POLICY_VERSION_DECISION})"
        ]
    if version_after == version_before:
        return [
            f"{POLICY_FILE}: staged text changed but 'version:' did not move "
            f"(still '{version_after}') — {rule} (see {POLICY_VERSION_DECISION})"
        ]
    if not _amendment_log_has_row(after, version_after):
        return [
            f"{POLICY_FILE}: version moved to '{version_after}' but the staged "
            f"Amendment log has no row for it — {rule} (see {POLICY_VERSION_DECISION})"
        ]
    return []


#: The record surfaces, which :func:`check_leak` does NOT gate. Ruled by the
#: owner 2026-09-01: the leak gate's scope is the SHIPPED PAYLOAD. These four
#: prefixes are out of it for two measured reasons — a published cut ships them
#: as ZERO BYTES by declaration (``.keel/published-cut.md``), so nothing in them
#: can reach an adopter; and every line that enters them passes
#: ``hooks/keel_redact.py``'s write-time screen first, which is the defence the
#: leak scan exists to back up rather than to duplicate. They also churn every
#: turn: this session alone moved them from 558 findings to 589, so gating them
#: would make the build a function of how much work happened today.
#:
#: This is a SCOPE, not an exclusion list for source. Source files carry the
#: scanner's own line-level marker instead — see ``scripts/keel_leak_check.py``'s
#: contract, which refuses per-path exclusions for exactly the reason this
#: comment has to justify itself.
LEAK_RECORD_SURFACES: tuple[str, ...] = (
    ".keel/audit/",
    ".keel/queue/",
    ".keel/plans/",
    ".keel/knowledge/",
)


def _leak_is_record_surface(rel_path: str) -> bool:
    """Whether a finding's path is a record surface rather than shipped payload."""
    normalised = rel_path.replace("\\", "/")
    return any(normalised.startswith(prefix) for prefix in LEAK_RECORD_SURFACES)


def check_leak(root: Path) -> list[str]:
    """Nothing in the SHIPPED PAYLOAD may name a home path, a key, a token or a
    real address — the second line of defence behind write-time redaction, and
    the check that makes clause 4 of the publication ruling satisfiable.

    WHY THIS EXISTS AS A CHECK AT ALL. ``keel leak-check`` shipped for three
    weeks advertised as scanning "content that must not leave", referenced by
    nothing: zero hits in ``.github/`` and zero here, so it gated nothing and
    its exit 1 was this project's normal standing state. A scanner nobody runs
    is a claim, not a defence.

    WHAT IS IN SCOPE: every tracked text file except the record surfaces named
    in :data:`LEAK_RECORD_SURFACES`, which carry their own reasoning there.

    HOW A KNOWN-DELIBERATE FINDING IS DECLARED: on its own line, with the
    scanner's ``keel-leak: ignore`` marker and a reason. There is deliberately
    no register here. The marker sits where the finding is, moves with the line
    when code shifts, and cannot go stale in the way a file of line numbers
    does — the scanner's own contract argues this at length, and building a
    second mechanism beside it would mean maintaining two.

    FAIL-CLOSED, IN THREE PLACES, because every one of them otherwise produces
    the empty finding list that a genuinely clean tree produces:
    a scanner that cannot enumerate the tracked files raises, and that raise is
    a check failure rather than a pass — the same direction ``keel_leak_check``
    takes for itself with its exit code 2; an enumeration that comes back EMPTY
    raises too, inside ``tracked_files``, because a scan of zero files knows
    nothing; and a tracked file IN SCOPE that the scan never opened — absent
    from the work tree, or unreadable — is reported as a violation rather than
    counted as clean. The census printed beside the findings is what makes the
    third one visible at all (R45).
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import keel_leak_check

    try:
        tracked = keel_leak_check.tracked_files(str(root))
    except Exception as exc:  # a scan that cannot run is not a clean tree
        return [f"leak-check could not enumerate tracked files: {exc}"]

    report = keel_leak_check.scan_tree_reported(str(root), tracked, [])
    payload = [f for f in report.findings if not _leak_is_record_surface(f.path)]
    exempt = len(report.findings) - len(payload)
    # EVERY census number is taken WITHIN SCOPE. A count mixing the gated files
    # with the exempt ones cannot answer the only question the census exists to
    # answer — how much of the part this gate guards did it actually read.
    read = [path for path in report.scanned if not _leak_is_record_surface(path)]
    skipped = [(p, why) for p, why in report.skipped if not _leak_is_record_surface(p)]
    blind = [(p, why) for p, why in report.blind if not _leak_is_record_surface(p)]
    print(
        f"    shipped payload: {len(payload)} finding(s); record surfaces: "
        f"{exempt} finding(s), out of scope by ruling (see LEAK_RECORD_SURFACES)"
    )
    # The census, not the findings, is what shows a scan that went blind: an
    # unread file and a clean file both contribute nothing to the list above.
    print(
        f"    in scope: {len(read) + len(skipped) + len(blind)} file(s) — "
        f"{len(read)} read as text, {len(skipped)} skipped unread "
        f"(binary content, or a binary extension never opened), "
        f"{len(blind)} never read"
    )
    violations = [
        f"{f.path}:{f.line}: [{f.rule}] {f.excerpt} — declare it with a "
        f"'keel-leak: ignore' marker and a reason on that line, or remove it"
        for f in payload
    ]
    violations.extend(
        f"{path}: tracked but {why} — a file the scan never read cannot be "
        f"called clean; restore it, or remove it from the index"
        for path, why in blind
    )
    return violations


#: The edition validated by :func:`check_plugin_validate` — the full closure
#: (every feature), so every shipped ``agents/`` and ``skills/`` component is
#: reachable by the validator in one bundle rather than needing all four.
PLUGIN_VALIDATE_EDITION = "keel-fleet"


def check_plugin_validate(root: Path) -> tuple[list[str], bool]:
    """BL56: ask an external oracle — ``claude plugin validate`` — whether a
    generated edition bundle is loadable, because nothing else in this suite
    does. Returns ``(violations, skipped)``.

    WHY A BUNDLE, NOT THE REPOSITORY ROOT. ``claude plugin validate`` run
    against this repository's own root reads
    ``.claude-plugin/marketplace.json`` and validates only that manifest — it
    never descends into ``agents/`` or ``skills/``. A generated edition bundle
    carries no marketplace manifest (:data:`keel_gen_editions.EXCLUDED_PATHS`
    excludes it), only a plugin manifest, so the SAME validator treats the
    bundle as a plugin instead and inspects every component inside it. That
    is the entire reason BL56's fault survived six audits and a green suite:
    the only external checker this project has was always being asked the
    question that finds nothing.

    WHICH BUNDLE. :data:`PLUGIN_VALIDATE_EDITION` (``keel-fleet``) is every
    edition's transitive superset (see ``keel_gen_editions``'s module
    docstring), so one bundle, one subprocess call, covers every shipped
    agent and skill — not four calls, one per edition.

    THE ABSENT-BINARY CASE. ``claude`` is an external tool this repository
    does not install and CI's runners do not carry (see the module
    docstring's second declared degradation). Its absence returns
    ``skipped=True`` and a single violation string NAMING what was not
    checked — the caller prints that as a visible SKIP, never a silent PASS,
    and it does not gate the exit code. Every other failure here (a bundle
    that cannot be generated, a validator that cannot be parsed) is NOT this
    degradation: it raises, per the module's fail-closed policy, because
    those are failures of this project's own tooling, not of an optional
    external binary.

    Returns the validator's own errors verbatim — one per finding, prefixed
    with the file the finding names — so the message a developer reads here
    is the same one the validator printed, not a paraphrase of it.
    """
    claude_path = shutil.which("claude")
    if claude_path is None:
        return (
            [
                "the 'claude' binary is not on PATH: plugin-validate did NOT "
                "run — BL56's external oracle is unchecked this run (not a "
                "pass; see the module docstring's second declared degradation)"
            ],
            True,
        )

    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import keel_gen_editions

    with tempfile.TemporaryDirectory() as tmp:
        out_root = Path(tmp)
        try:
            features = keel_gen_editions.load_registry(root)
            bundle, _file_count = keel_gen_editions.generate_edition(
                PLUGIN_VALIDATE_EDITION, root, out_root, features
            )
        except keel_gen_editions.EditionError as exc:
            raise RuntimeError(
                f"plugin-validate could not generate the {PLUGIN_VALIDATE_EDITION} "
                f"bundle it validates: {exc}"
            ) from exc
        try:
            result = subprocess.run(
                [claude_path, "plugin", "validate", "--json", str(bundle)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except OSError as exc:
            raise RuntimeError(f"cannot run claude plugin validate: {exc}") from exc
        try:
            report = json.loads(result.stdout)
        except ValueError as exc:
            raise RuntimeError(
                f"claude plugin validate produced unparseable output "
                f"(exit {result.returncode}): {exc}\nstdout: {result.stdout}\n"
                f"stderr: {result.stderr}"
            ) from exc

        violations: list[str] = []
        manifest = report.get("manifest") or {}
        manifest_file = manifest.get(
            "file", str(bundle / ".claude-plugin" / "plugin.json")
        )
        for error in manifest.get("errors", []):
            violations.append(
                f"{manifest_file}: {error.get('path')}: {error.get('message')}"
            )
        for entry in report.get("contents", []):
            for error in entry.get("errors", []):
                violations.append(
                    f"{entry.get('file')}: {error.get('path')}: {error.get('message')}"
                )
        return violations, False


def _fresh_distribution_files(fresh: Path) -> dict[str, bytes]:
    """Every file a fresh generation emitted, keyed by bundle-relative POSIX
    path and valued by its bytes. Read as bytes, not text: the comparison is
    what an install would copy, and an encoding round-trip is not that."""
    return {
        path.relative_to(fresh).as_posix(): path.read_bytes()
        for path in fresh.rglob("*")
        if path.is_file()
    }


def _distribution_paths_on_disk(bundle_root: Path) -> list[str]:
    """Every file that PHYSICALLY sits under the distribution directory,
    bundle-relative POSIX, read from the filesystem.

    Deliberately not :func:`_scanned_files` and not ``git ls-files``, and the
    reason is BL37's own defect: a local plugin install copies the directory
    tree AS IT STANDS ON DISK - it does not consult ``.gitignore`` (measured,
    not assumed: T499/T505, T612). Any set derived from git excludes
    gitignored paths BY CONSTRUCTION, so a guard built on one makes a claim
    about the bytes an install copies while being unable to see them. That is
    the exact shape BL37 records, and until 2026-09-06 it was reproduced
    inside BL37's fix.

    Directories are not entries: only files are copied, and an empty
    directory ships nothing.
    """
    if not bundle_root.is_dir():
        return []
    return sorted(
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
    )


def check_distribution(root: Path) -> list[str]:
    """BL37: the TRACKED distribution equals a fresh generation of it.

    ``.claude-plugin/marketplace.json`` points an install at ``dist/keel``
    instead of at the repository root, so the bundle carries no ``.keel/``,
    no ``tests/`` and no internal working material
    (:data:`keel_gen_editions.EXCLUDED_PATHS` is enforced before anything is
    copied). Tracking a generated tree buys a clone that installs with no
    build step, and it costs exactly one thing: the tracked bytes can drift
    from the sources they were generated from, silently, because nothing
    about editing ``hooks/keel_gate.py`` reminds anyone to regenerate. This
    check is the whole of what stands between that and a shipped bundle that
    is a week behind the repository.

    WHAT IT COMPARES. The distribution is regenerated into a temporary
    directory through :func:`keel_gen_editions.generate_distribution` - the
    same call the CLI makes, so there is one notion of what ships - and every
    path is compared both ways, with file BYTES compared for the paths in
    both. A missing path, an extra path and an equal-path-different-bytes are
    three different ways to be stale and all three are reported, each naming
    the path.

    WHICH TREE, AND WHY NOT GIT'S. The FILESYSTEM under the bundle
    (:func:`_distribution_paths_on_disk`), never :func:`_scanned_files` and
    never ``git ls-files``. This check read the git-derived set until
    2026-09-06, and that was BL37's own defect reproduced inside BL37's fix:
    a guard reading the git-visible world to make a claim about the bytes an
    install copies. An install copies the tree as it stands on disk and does
    not consult ``.gitignore``, so a gitignored file inside the bundle - a
    ``__pycache__`` left by anything that imported from the shipped
    ``hooks/`` or ``scripts/`` - is excluded from the git-derived set by
    construction, ships to every installer, and is reported clean. The walk
    keeps the property the git read was chosen for, since a bundle written
    but not yet committed is exactly the thing under test and a walk sees it
    too, and it loses nothing: a stray now surfaces as the ordinary extra
    file below.

    ALLOWLIST, NOT DENYLIST. Closed both ways against the fresh generation,
    so an unexpected file fails by being PRESENT, whatever it is called. A
    list of ignored patterns to go looking for would need editing every time
    ``.gitignore`` moves and would still say nothing about what it had not
    been told.

    FAIL-CLOSED. An empty walk means there is no distribution on disk at
    all, which is a violation and not a vacuous pass. A generation that
    cannot run raises: that is this project's own tooling failing, not an
    optional external binary (contrast :func:`check_plugin_validate`).
    """
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import keel_gen_editions

    dist = keel_gen_editions.DISTRIBUTION_PATH
    shipped = _distribution_paths_on_disk(root / dist)
    if not shipped:
        return [
            f"{dist}/ holds no file on disk, and "
            f".claude-plugin/marketplace.json points an install at it: "
            f"regenerate it with 'python scripts/keel_gen_editions.py "
            f"--distribution' and commit the result"
        ]

    with tempfile.TemporaryDirectory() as tmp:
        try:
            features = keel_gen_editions.load_registry(root)
            fresh, _count = keel_gen_editions.generate_distribution(
                root, Path(tmp), features
            )
        except keel_gen_editions.EditionError as exc:
            raise RuntimeError(
                f"the distribution check could not generate the bundle it "
                f"compares {dist}/ against: {exc}"
            ) from exc
        generated = _fresh_distribution_files(fresh)

        differences: list[str] = []
        for rel in sorted(set(generated) - set(shipped)):
            differences.append(
                f"{dist}/{rel}: a fresh generation emits this file; the "
                f"distribution on disk does not carry it"
            )
        for rel in sorted(set(shipped) - set(generated)):
            differences.append(
                f"{dist}/{rel}: carried by the distribution on disk; a fresh "
                f"generation does not emit it - an install copies the tree as "
                f"it stands, whether or not git can see this file"
            )
        for rel in sorted(set(shipped) & set(generated)):
            on_disk_file = root / dist / rel
            try:
                on_disk_bytes = on_disk_file.read_bytes()
            except OSError as exc:
                differences.append(
                    f"{dist}/{rel}: present on disk but unreadable here "
                    f"({exc}) - a file this check cannot read is not a file "
                    f"it can call current"
                )
                continue
            if on_disk_bytes != generated[rel]:
                differences.append(
                    f"{dist}/{rel}: the bytes on disk differ from a fresh generation"
                )

    if not differences:
        return []
    return [
        f"the tracked distribution is STALE against the sources it was "
        f"generated from - regenerate with 'python "
        f"scripts/keel_gen_editions.py --distribution' and commit the result",
        *differences,
    ]


#: EVERY check this module defines, in run order: the check's name (which is
#: also its ``--flag``) and the help text that flag carries.
#:
#: ONE list feeds both the argparse options and the no-flag default, so a check
#: cannot exist as a flag and still sit out the full run. That drift is not
#: hypothetical: ``--policy`` shipped as a defined-but-uninvoked flag while CI
#: enumerated the other seven by hand (T320 review, 2026-08-25). CI runs this
#: script with NO flags, which is this list.
#:
#: REGISTERING HERE IS NOT WIRING, and this comment claimed otherwise until
#: 2026-09-01. It said a new check "gates pushes from the moment it is
#: registered here", which is false: this list drives argparse and the
#: selection, while :func:`main` invokes each check through its own explicit
#: ``if "<name>" in selected:`` line. A check registered and not dispatched is
#: SELECTED AND SILENTLY SKIPPED — one fewer PASS line and still exit 0, which
#: reads exactly like success. That is how the leak check first landed, and the
#: sentence you are reading is what made it plausible. Add the dispatch line
#: too, and count the PASS lines against the number of entries here rather than
#: trusting the exit code.
CHECKS: tuple[tuple[str, str], ...] = (
    ("deps", "stdlib-only import check (R7, R14)"),
    ("symlinks", "no tracked symlinks (R2)"),
    ("budget", "always-loaded token budget (R9)"),
    ("names", "no denied names in tracked text"),
    ("refs", "citations and paths resolve (R18)"),
    ("agents", "explicit tools lists and the reviewer house contract (R22, R28)"),
    ("closure", "the feature registry and the bundle-closure rule"),
    ("policy", "a staged policy-file change moves its version and logs it (T230/T320)"),
    ("leak", "nothing in the shipped payload names a home path, key or address"),
    (
        "plugin",
        "claude plugin validate reports no error against a generated edition "
        "bundle (BL56) — a visible SKIP, not a pass, if 'claude' is absent",
    ),
    (
        "distribution",
        "the tracked dist/keel bundle equals a fresh generation of it (BL37)",
    ),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel_checks.py", description="keel repository checks (Phase 0 CI gates)"
    )
    for name, help_text in CHECKS:
        parser.add_argument(f"--{name}", action="store_true", help=help_text)
    args = parser.parse_args(argv)

    selected = [name for name, _ in CHECKS if getattr(args, name)] or [
        name for name, _ in CHECKS
    ]

    root = repo_root()
    print(f"keel checks in {root}")
    passed = True
    try:
        if "names" in selected or "refs" in selected:
            # The scan set is reported before the checks that read it, so a
            # run can never be green about a file it never opened (R45).
            tracked = _tracked_text_files(root)
            untracked = _untracked_text_files(root)
            print(
                f"    scan set: {len(set(tracked) | set(untracked))} file(s), "
                f"{len(untracked)} of them written but not yet tracked by git"
            )
        if "deps" in selected:
            passed &= _report("deps", check_deps(root))
        if "symlinks" in selected:
            passed &= _report("symlinks", check_symlinks(root))
        if "budget" in selected:
            tokens, violations = check_budget(root)
            cap_bytes, injection_tokens = session_injection_tokens()
            worst_case_tokens = tokens + injection_tokens
            print(
                f"    always-loaded static tokens (gates this check): "
                f"{tokens} / {BUDGET_TOKEN_LIMIT}"
            )
            print(
                f"    session injection tokens (reported only, not gated): "
                f"{injection_tokens} (cap {cap_bytes} bytes)"
            )
            print(
                f"    worst-case session floor (reported only, not gated): "
                f"{worst_case_tokens} tokens"
            )
            passed &= _report("budget", violations)
        if "names" in selected:
            passed &= _report("names", check_vendor_names(root))
        if "refs" in selected:
            ref_findings, ref_found, ref_waived = _check_refs_counted(root)
            ref_inapplicable = inapplicable_waivers(root)
            print(
                f"    path violations: {ref_found} found, {ref_waived} waived "
                f"(see {REFS_WAIVER_PATH})"
            )
            if ref_inapplicable:
                # Counted, never hidden: these name files this tree does not
                # carry, which is normal in a published cut and drift anywhere
                # else.
                print(
                    f"    waivers inapplicable here (file not in the scan set): "
                    f"{len(ref_inapplicable)} — {', '.join(ref_inapplicable)}"
                )
            passed &= _report("refs", ref_findings)
        if "agents" in selected:
            passed &= _report("agents", check_agents(root))
        if "closure" in selected:
            passed &= _report("closure", check_closure(root))
        if "policy" in selected:
            passed &= _report("policy", check_policy_version(root))
        if "leak" in selected:
            passed &= _report("leak", check_leak(root))
        if "plugin" in selected:
            plugin_violations, plugin_skipped = check_plugin_validate(root)
            if plugin_skipped:
                print(f"SKIP plugin: {plugin_violations[0]}")
            else:
                passed &= _report("plugin", plugin_violations)
        if "distribution" in selected:
            passed &= _report("distribution", check_distribution(root))
    except (RuntimeError, OSError, ValueError, SyntaxError) as exc:
        print(f"ERROR check could not run: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
