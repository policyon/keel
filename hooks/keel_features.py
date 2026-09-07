#!/usr/bin/env python3
"""keel feature presence - what THIS installation actually carries.

Contract
--------
Reads   : ``<install root>/scripts/keel-features.json`` - the feature registry
          the installed bundle ships - and the on-disk COMPONENT PATHS that
          registry names: their presence (``component_present``,
          ``feature_presence``), and, for the fingerprint below, their
          contents, read as bytes. Nothing else: no environment, no project
          directory, no ``sys.path``.
Emits   : values, plus one sentence. ``feature_absent`` answers the question;
          ``declared_modules`` answers the narrower one a failed import asks -
          is this module name one this edition claims to carry at all;
          ``component_fingerprint`` answers "WHICH tree is this" (T168);
          ``derived_edition`` answers "which edition do the components on disk
          actually make" rather than believing the manifest's name;
          ``decline`` composes the single sentence keel says when a component
          reaches for a feature this edition does not include. Nothing here
          prints, exits or logs - each caller owns its own channel and its own
          declared failure policy.
Writes  : nothing. Files are opened read-only, and never created.
Argv    : none. Library module; never executed as a hook or a command.

Deriving rather than asserting (T168)
-------------------------------------
Two questions used to be answered by reading a STRING out of a manifest, and
both answers were unfalsifiable:

* "which tree is running" was answered by ``version``, so two materially
  different trees carrying the same number were indistinguishable - measured
  2026-08-18, when an installed cache snapshot and a working tree differing in
  43 files both reported the same version and agreed with the same changelog.
  ``component_fingerprint`` answers it from the CONTENTS of the files the
  registry names, so two trees claiming one version print two digests.
* "which edition is this" was answered by ``plugin.json``'s ``name``.
  ``derived_edition`` answers it from which layers' components are on disk.

Both derivations read the same registry the editions are cut along, so neither
can drift from what generation actually ships.

What the fingerprint is over, exactly
-------------------------------------
Every component path the registry names, sorted; for a directory component,
every file under it, by sorted relative path. Each file contributes its path
AND its content digest, so a file that moves changes the answer. A component
the tree does not carry contributes an ``absent`` marker under its own name -
a missing file must change the digest, or a trimmed tree would fingerprint as
a whole one - and a path that could not be READ contributes an ``unreadable``
marker under its own name, which is a THIRD input and not the second: a tree
keel was refused must not digest as the tree with that file deleted, or a
permissions fault would read as a smaller edition. Nothing time-derived is read: no mtime, no size, no inode, so the
same content in two places digests identically, which is the property that
makes the value comparable at all. Line endings are normalised to LF first: a
checkout policy is not a difference in content. ``__pycache__`` and
compiled bytecode are excluded - they are products of RUNNING the tree, not
part of it, and including them would make the digest depend on whether
something had been imported yet.

Why the LOCAL registry decides
------------------------------
``scripts/keel_gen_editions.py`` writes every bundle a registry narrowed to
that bundle's own feature closure, so the registry an installation ships is a
positive statement about what is present rather than a catalogue of what
exists somewhere. That is what makes "this edition does not include the
knowledge feature" a fact a kernel component can read, instead of an
inference from a failed import.

The same property is what lets ``declared_modules`` tell a module that was
TRIMMED from one that is present and BROKEN: a scoped registry lists every
component of every feature the bundle carries, so a keel module name it does
not hold belongs to a feature this edition does not include, while one it does
hold should be on disk and importable. Those two faults must never look alike -
"buy the bigger edition" is the wrong answer to a damaged install
(convention 7).

Exit codes
----------
None of its own. This module decides nothing about a session; it answers one
question for callers that do.

Failure policy
--------------
FAIL-CLOSED, in the one sense available to a module that answers a question
rather than guarding a session: no fault here can end in a permissive silence.
Absence is reported only on positive evidence, so a caller never declines on a
guess; and a registry that cannot be read is UNDECIDABLE - ``registry_features``
returns ``None`` rather than an empty set, because "the registry could not be
read" must never be indistinguishable from "this installation carries no
features" (convention 7). An undecidable answer hands the question straight
back to the caller's own import or read, which fails loudly under the caller's
declared policy (fail-closed in ``scripts/keel.py``, fail-open with one stderr
line in ``hooks/keel_session.py``), so the quiet middle ground does not exist.
``decline`` raises ``ValueError`` rather than composing a sentence with a hole
in it. Like ``keel_events``, this is a model rather than a guard: it decides
nothing about a session and blocks nothing.

The two T168 derivations follow the same rule, and one distinction carries it:
UNREADABLE IS NOT ABSENT, at every point where a filesystem answer becomes a
presence verdict. ``component_state`` is the single place that judgement is
made - ``Path.exists()`` cannot make it, because it turns every ``OSError``
into ``False`` - and ``component_present``, ``_component_scan``,
``feature_presence`` and ``derived_edition`` all read their verdict from it, so
no two of them can disagree about what a permission-denied component means.

``component_fingerprint`` returns a digest of ``""`` - never a digest of
nothing - when the registry cannot be read, and states why in its ``note``; a
component it cannot stat, a subdirectory it cannot list, and a file it cannot
open are each counted in ``unreadable`` and marked as such inside the digest,
so an unreadable path changes the answer instead of being skipped past. Absent
components are LISTED separately, so a caller can print "40 files, 18 MISSING,
2 UNREADABLE" rather than a bare digest that looks like health.

``derived_edition`` reports ``layer=""`` plus what it actually found whenever
the components on disk match no edition on the layer ladder: an unrecognized
mix is described, never rounded to the nearest edition name. Where anything was
unreadable it goes further and refuses to derive at all
(``decidable`` is False, and the note begins "cannot derive"), because every
step of that ladder is an inference from an absence, and an absence that was
never established is not one.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no shell, no
network. Text files read here name their encoding explicitly (convention 6);
the fingerprint reads BYTES, which have no encoding to name, and normalises
line endings itself rather than decoding text it does not interpret. Component
paths handled here come from keel's own registry or its module-level
constants, never from a payload, and none of them reaches a shell (R5). The
fingerprint walk is bounded by the registry: it descends only into directories
a component names, so it can never turn into a whole-filesystem crawl.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: The feature registry, relative to the installation root. Kernel owns it, so
#: every edition carries one - see "Why the LOCAL registry decides" above.
REGISTRY_RELPATH: tuple[str, ...] = ("scripts", "keel-features.json")

#: How much of the component digest is reported. Twelve hex characters is 48
#: bits: far too short for any adversarial claim, and this is not one - the
#: question it answers is "are these two trees the same tree", asked by a human
#: reading two report lines side by side. A value nobody can read across is a
#: value nobody checks.
FINGERPRINT_HEX_CHARS = 12

#: Directory names the fingerprint never descends into, and file suffixes it
#: never digests: products of RUNNING the tree rather than parts of it. A
#: digest that moved the first time a module was imported would be reported as
#: a difference between two trees that are identical.
DIGEST_SKIP_DIRS: frozenset[str] = frozenset({"__pycache__"})
DIGEST_SKIP_SUFFIXES: tuple[str, ...] = (".pyc", ".pyo")

#: How many unreadable component paths a "cannot derive" sentence names before
#: it counts the rest. The names matter - they are what a reader fixes - and the
#: count matters too, so neither is dropped.
UNREADABLE_NAMED = 3

#: The layer ladder the four editions are cut along, weakest first. The names
#: are the registry's own ``layer`` values (``scripts/keel-features.json``) and
#: the same four words ``scripts/keel_gen_editions.py`` names its bundles
#: after; an edition is a PREFIX of this ladder, which is what makes "derive
#: the edition from what is present" a decidable question rather than a guess.
LAYER_ORDER: tuple[str, ...] = ("core", "standard", "govern", "fleet")

#: The one sentence keel says when a component reaches for a feature that is
#: not installed. One template, every caller: the CLI and the session injector
#: must not drift into two different accounts of the same absence
#: (convention 7 - the decline is visible and names what is missing).
DECLINE_TEMPLATE = "{what} needs the {feature} feature, which this edition does not include"


def install_root() -> Path:
    """The installation root: the directory holding ``hooks/`` and ``scripts/``.

    Derived from this file's own location, never from a caller's cwd. What an
    installation carries and what a project contains are two questions with
    two different answers, and confusing them is how a trimmed bundle starts
    reporting a user's project as the thing that is incomplete.
    """
    return Path(__file__).resolve().parent.parent


def registry_path(root: Path | None = None) -> Path:
    """Location of the shipped feature registry for an installation."""
    base = install_root() if root is None else Path(root)
    return base.joinpath(*REGISTRY_RELPATH)


def _feature_table(root: Path | None = None) -> dict | None:
    """The registry's ``features`` table, or None when it cannot be read as one.

    One reader for both public questions, so they can never disagree about what
    a readable registry is. Every fault - absent file, unreadable file,
    malformed JSON, a document of the wrong shape, an empty table - lands in the
    same ``None``, which each caller turns into its own UNDECIDABLE answer and
    never into an empty one.
    """
    try:
        document = json.loads(registry_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    features = document.get("features")
    if not isinstance(features, dict) or not features:
        return None
    return features


def registry_features(root: Path | None = None) -> frozenset[str] | None:
    """The feature names the local registry declares, or None when unreadable.

    ``None`` means UNDECIDABLE, never "no features". Every fault - absent
    file, unreadable file, malformed JSON, a document of the wrong shape -
    lands in the same ``None``, because the caller's next move is the same for
    all of them: decide on a component path instead, or decline to decide.
    """
    features = _feature_table(root)
    if features is None:
        return None
    return frozenset(str(name) for name in features)


def declared_modules(root: Path | None = None) -> frozenset[str] | None:
    """The Python module names this installation declares, or None when
    the registry cannot be read.

    Derived from the component paths themselves - ``scripts/keel_index.py`` is
    the module ``keel_index``, ``hooks/keel_gate.py`` is ``keel_gate`` - so the
    set cannot drift from the registry the editions are cut along, and which
    directory a module lives in does not change the answer.

    ``None`` means UNDECIDABLE, exactly as in ``registry_features``: never "this
    installation declares no modules". A registry that names features but no
    component paths is undecidable for the same reason, since it says nothing
    about any module. Callers use this to read a ``ModuleNotFoundError``
    honestly - see "Why the LOCAL registry decides" - and a ``None`` here means
    they may not read it as an edition boundary at all.
    """
    features = _feature_table(root)
    if features is None:
        return None
    modules: set[str] = set()
    for spec in features.values():
        if not isinstance(spec, dict):
            continue
        components = spec.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, str):
                continue
            path = component.replace("\\", "/").strip("/")
            if path.endswith(".py"):
                modules.add(path.rsplit("/", 1)[-1][: -len(".py")])
    if not modules:
        return None
    return frozenset(modules)


def component_path(component: str, root: Path | None = None) -> Path:
    """One registry component path resolved against the installation root.

    Takes the registry's own vocabulary - a project-relative path such as
    ``scripts/keel_index.py``, on either separator and with any trailing one -
    and resolves it against the installation root, NOT against ``sys.path``: a
    hook that has not yet extended its search path would otherwise read a
    present module as an absent feature.
    """
    base = install_root() if root is None else Path(root)
    return base / component.replace("\\", "/").strip("/")


def _stat(path: Path) -> os.stat_result:
    """The one ``stat`` call every presence verdict in this module goes through.

    A seam on purpose. Presence is decided from what this call RAISES -
    ``FileNotFoundError`` is absence, anything else is a fault - and a genuine
    permission-denied fixture is not constructible on all three operating
    systems this project's suite runs on (a POSIX ``chmod 000`` is a no-op for
    an administrator, and Windows ACLs are not portable test material). Tests
    inject the fault here and say so in their docstrings; that is a stated
    limitation of the fixture, not of the code path, which is the same one a
    real ``EACCES`` takes.
    """
    return path.stat()


def _walk_tree(base: Path, onerror: Any) -> Any:
    """The one directory walk the fingerprint uses, and the second seam.

    ``os.walk`` rather than ``Path.rglob`` deliberately: ``rglob`` swallows a
    directory it cannot list and yields nothing for it, which is precisely the
    fault that used to make a permission-denied subtree indistinguishable from
    a component the tree never carried. ``onerror`` is called with the OSError
    instead, so an unlistable subdirectory is RECORDED and the rest of the
    component is still digested.
    """
    return os.walk(base, onerror=onerror)


def component_state(component: str, root: Path | None = None) -> str:
    """``"present"``, ``"absent"`` or ``"unreadable"`` for one component path.

    The three-state answer every derivation in this module needs.
    ``Path.exists()`` cannot give it: it turns EVERY ``OSError`` -
    permission-denied included - into ``False``, so a component keel is not
    allowed to look at reads exactly like a component the bundle does not
    carry. One is a damaged or locked-down machine; the other is a trimmed
    edition, and "buy the bigger edition" is the wrong answer to the first
    (convention 7 - the same rule ``declared_modules`` follows for a trimmed
    versus a broken module).

    Absence is only ever reported on the errors that MEAN absence -
    ``FileNotFoundError`` and ``NotADirectoryError`` (a parent in the path is a
    file, so nothing can exist below it). Every other ``OSError``, and a
    ``ValueError`` from a path the platform cannot even express, is
    ``"unreadable"``: undecided, and visibly so.
    """
    try:
        _stat(component_path(component, root))
    except (FileNotFoundError, NotADirectoryError):
        return "absent"
    except (OSError, ValueError):
        return "unreadable"
    return "present"


def component_present(component: str, root: Path | None = None) -> bool:
    """Whether a registry component path is present in this installation.

    The BOOLEAN question, kept exactly as its callers already ask it - and
    exactly as narrow: ``True`` means present, and ``False`` means "not
    positively present", which covers absent and unreadable alike. That is
    sound for its one caller, ``feature_absent``, whose contract is to report
    absence only on positive evidence and which negates this value.

    Anything DERIVING a fact from the tree - :func:`feature_presence`,
    :func:`derived_edition`, :func:`component_fingerprint` - uses
    :func:`component_state` instead, because a bool cannot carry the difference
    between "not there" and "could not look".
    """
    return component_state(component, root) == "present"


def feature_absent(
    name: str, *, component: str | None = None, root: Path | None = None
) -> bool:
    """True only when this installation positively does NOT carry ``name``.

    Two kinds of evidence, in that order:

    1. the local registry - a readable registry that does not name the feature
       is a positive statement that the feature is not here (see "Why the
       LOCAL registry decides" in the module docstring);
    2. ``component``, one path the feature owns, used only when the registry
       cannot be read at all: a feature whose file is missing is not
       installed.

    Anything short of that evidence is ``False`` - "not decidably absent" - so
    no caller ever declines on a guess. Where an installation contradicts
    itself (registry names the feature, its files are gone) this returns
    False and the caller's own import or read fails under its own declared
    failure policy. Never raises.

    A component that could not be LOOKED AT is not evidence either, and is
    ``False`` for the same reason (T168): "keel was refused this path" must
    never reach a user as "buy the bigger edition". Only a filesystem answer
    that actually says "not there" counts - see :func:`component_state`.
    """
    declared = registry_features(root)
    if declared is not None:
        return name not in declared
    if component is None:
        return False
    return component_state(component, root) == "absent"


def decline(what: str, feature: str) -> str:
    """The decline sentence: what was asked for, and the feature it needs.

    Raises ``ValueError`` on a blank subject or feature: a decline naming
    neither what failed nor what is missing is exactly the silent failure this
    mechanism exists to prevent (convention 7). Both call sites pass module
    constants, so a blank can only be a defect, and a test pins the wording.
    """
    subject, missing = what.strip(), feature.strip()
    if not subject or not missing:
        raise ValueError("a decline must name both the request and the missing feature")
    return DECLINE_TEMPLATE.format(what=subject, feature=missing)


# --------------------------------------------------------------------------
# T168: which tree is this, and which edition do its components make
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentFingerprint:
    """One tree's component digest, with everything that qualifies it.

    ``digest`` is empty exactly when the answer is UNDECIDABLE, and ``note``
    then says why. ``missing`` and ``unreadable`` are the honest edge of a
    digest that IS available: both are folded into the digest itself (so two
    trees differing only in what is absent get different values) and both are
    reported, so no caller prints a digest that looks like health over a tree
    with a hole in it.
    """

    digest: str = ""
    files: int = 0
    missing: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()
    note: str = ""

    @property
    def known(self) -> bool:
        """True when a digest was actually computed."""
        return bool(self.digest)

    def summary(self) -> str:
        """The one phrase every surface prints for this value.

        Survey and the orchestration board both call it, so the fingerprint
        cannot acquire two spellings on two screens (the single-place rule
        R15 asks for).
        """
        if not self.known:
            return f"unavailable ({self.note or 'no reason given'})"
        parts = [f"{self.files} file(s)"]
        if self.missing:
            parts.append(f"{len(self.missing)} MISSING")
        if self.unreadable:
            parts.append(f"{len(self.unreadable)} UNREADABLE")
        return f"{self.digest} ({', '.join(parts)})"


@dataclass(frozen=True)
class FeaturePresence:
    """What the disk says about one registry feature.

    ``state`` is one of ``present`` (every component found), ``partial`` (some
    found - a damaged or half-copied tree, which is neither of the two answers
    a reader wants), ``absent`` (none found), ``unevidenced`` (the feature
    declares no components at all, so its presence cannot be derived from the
    tree in either direction) or ``unreadable`` (at least one component could
    not be looked at, so this feature's presence is UNDECIDED - never folded
    into ``absent``, which would turn a permissions problem into a smaller
    edition).

    ``unreadable`` counts the components that could not be looked at, and it
    outranks every other state for this feature: one component keel was refused
    is enough to make the feature's presence undecided, whatever the others
    said.
    """

    name: str
    layer: str
    state: str
    found: int
    total: int
    unreadable: int = 0


@dataclass(frozen=True)
class DerivedEdition:
    """The edition the components on disk actually make.

    ``layer`` is one of :data:`LAYER_ORDER`, or ``""`` when what is on disk
    matches no edition on the ladder - in which case ``note`` describes what
    was found. There is deliberately no "closest" edition: rounding a damaged
    or forked tree up to an edition name is the assertion this replaces.

    ``unreadable`` names the component paths that could not be looked at.
    Non-empty means the answer is UNDECIDABLE rather than unrecognized, and the
    two must read differently: "this mix is not an edition" is a statement about
    the tree, while "keel could not see part of the tree" is a statement about
    the machine. ``decidable`` is the one question a renderer has to ask to tell
    them apart.
    """

    layer: str = ""
    features: tuple[FeaturePresence, ...] = ()
    note: str = ""
    unreadable: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        """True when the ladder settled on one edition."""
        return bool(self.layer)

    @property
    def decidable(self) -> bool:
        """False when something could not be read, so no verdict is possible.

        A caller must not print an edition, or an "unrecognized mix", over a
        tree part of which was never seen - both would be conclusions drawn
        from an absence that was never established (convention 7).
        """
        return not self.unreadable and bool(self.features)

    def found_summary(self) -> str:
        """What was found, by state - the answer when ``layer`` is empty."""
        if not self.features:
            return "no features to read"
        groups: dict[str, list[str]] = {}
        for presence in self.features:
            if presence.state == "partial":
                label = f"{presence.name} ({presence.found} of {presence.total})"
            elif presence.state == "unreadable":
                label = f"{presence.name} ({presence.unreadable} of {presence.total})"
            else:
                label = presence.name
            groups.setdefault(presence.state, []).append(label)
        order = ("present", "partial", "unreadable", "absent", "unevidenced")
        return "; ".join(
            f"{state}: {', '.join(groups[state])}" for state in order if state in groups
        )


def component_paths(root: Path | None = None) -> tuple[str, ...] | None:
    """Every component path the local registry names, deduplicated and sorted.

    ``None`` means UNDECIDABLE, exactly as in :func:`registry_features`: the
    registry could not be read, which is never the same answer as "this
    installation names no components". Paths are returned in the registry's own
    project-relative POSIX vocabulary with any trailing separator dropped, so a
    directory component (``skills/log/``) and a file component are handled by
    one caller: what a component IS gets decided against the disk, not against
    the punctuation the registry happened to use.
    """
    features = _feature_table(root)
    if features is None:
        return None
    paths: set[str] = set()
    for spec in features.values():
        if not isinstance(spec, dict):
            continue
        components = spec.get("components")
        if not isinstance(components, list):
            continue
        for component in components:
            if not isinstance(component, str) or not component.strip():
                continue
            paths.add(component.replace("\\", "/").strip("/"))
    return tuple(sorted(paths))


@dataclass(frozen=True)
class ComponentScan:
    """What one component path contributed to the digest, and what it could not.

    ``state`` is the same three-word vocabulary :func:`component_state` uses,
    so one component can never be ``absent`` in the fingerprint and
    ``unreadable`` in the edition derivation. ``unreadable`` names the specific
    paths that could not be listed - a subdirectory keel was refused, not the
    whole component - so a partly-readable component still contributes every
    file it does have AND still says what it hid.
    """

    state: str
    members: tuple[tuple[str, Path], ...] = ()
    unreadable: tuple[str, ...] = ()


def _component_scan(base: Path, relpath: str, root: Path | None = None) -> ComponentScan:
    """Every file one component contributes, plus every path it could not list.

    A file component contributes itself; a directory component contributes
    every file beneath it, named by its path relative to the installation root
    so the name travels with the content into the digest. ``__pycache__`` and
    compiled bytecode are skipped (see :data:`DIGEST_SKIP_DIRS`).

    THREE outcomes, never two (the fault this replaced): ``absent`` when the
    component is not there, ``unreadable`` when the component itself cannot be
    stat'd, and ``present`` otherwise - where a subdirectory that cannot be
    LISTED mid-walk is recorded in ``unreadable`` rather than quietly
    contributing nothing. An empty directory is ``present`` with no members,
    which is what it is; only a stat that says otherwise makes a component
    absent.
    """
    target = base / relpath
    state = component_state(relpath, root)
    if state != "present":
        return ComponentScan(
            state=state, unreadable=(relpath,) if state == "unreadable" else ()
        )
    try:
        info = _stat(target)
    except (OSError, ValueError):
        return ComponentScan(state="unreadable", unreadable=(relpath,))
    if not stat.S_ISDIR(info.st_mode):
        return ComponentScan(state="present", members=((relpath, target),))
    unreadable: list[str] = []

    def onerror(exc: OSError) -> None:
        """A directory the walk could not list is EVIDENCE, not a gap."""
        offender = getattr(exc, "filename", None) or str(target)
        try:
            relative = os.path.relpath(str(offender), str(target)).replace(os.sep, "/")
        except (OSError, ValueError):
            relative = ""
        unreadable.append(
            relpath if relative in ("", ".") else f"{relpath}/{relative}"
        )

    members: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in _walk_tree(target, onerror):
        dirnames[:] = [name for name in dirnames if name not in DIGEST_SKIP_DIRS]
        for name in filenames:
            if name.endswith(DIGEST_SKIP_SUFFIXES):
                continue
            child = Path(dirpath) / name
            try:
                relative = child.relative_to(target).as_posix()
            except ValueError:  # pragma: no cover - a walk that left its own root
                continue
            members.append((f"{relpath}/{relative}", child))
    return ComponentScan(
        state="present",
        members=tuple(sorted(members)),
        unreadable=tuple(sorted(set(unreadable))),
    )


def _normalised_bytes(data: bytes) -> bytes:
    """``data`` with CRLF and lone CR folded to LF.

    The digest is over CONTENT. A checkout that landed Windows line endings on
    the same source is the same source, and a fingerprint that disagreed would
    report every cross-platform pair of trees as different - which is the
    fastest way to teach a reader to ignore the value.
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def path_digest(path: Path | str) -> str:
    """This file's own content digest, or ``""`` when it cannot be read.

    The same normalisation and the same truncation as
    :func:`component_fingerprint`, exposed for the one thing the component set
    cannot cover: a file that is not a registry component but whose staleness
    matters (the orchestration board's page source, T162/T168). One
    implementation, so two surfaces cannot digest the same bytes differently.
    """
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(_normalised_bytes(data)).hexdigest()[:FINGERPRINT_HEX_CHARS]


def component_fingerprint(root: Path | None = None) -> ComponentFingerprint:
    """A digest of the component set this installation carries.

    Never raises: every fault becomes a stated value (see the module's failure
    policy). See "What the fingerprint is over, exactly" in the module
    docstring for the derivation and for what is deliberately NOT read.

    Three kinds of input reach the digest, each under its own marker, so the
    value stays deterministic AND the three states stay distinguishable: a
    file's content, an ``absent`` component's name, and an ``unreadable``
    path's name. A tree keel was refused therefore fingerprints differently
    from the same tree with that component deleted, which is the whole point:
    ``missing`` is a trimmed edition and ``unreadable`` is a machine problem,
    and the two must never print as one number.
    """
    paths = component_paths(root)
    if paths is None:
        return ComponentFingerprint(
            note=f"no readable feature registry at {registry_path(root)}"
        )
    base = install_root() if root is None else Path(root)
    digest = hashlib.sha256()
    files = 0
    missing: list[str] = []
    unreadable: list[str] = []
    for relpath in paths:
        scan = _component_scan(base, relpath, root)
        if scan.state == "absent":
            missing.append(relpath)
            digest.update(b"absent\x00" + relpath.encode("utf-8") + b"\x00")
            continue
        for name in scan.unreadable:
            unreadable.append(name)
            digest.update(b"unreadable\x00" + name.encode("utf-8") + b"\x00")
        for name, path in scan.members:
            try:
                data = path.read_bytes()
            except (OSError, ValueError):
                unreadable.append(name)
                digest.update(b"unreadable\x00" + name.encode("utf-8") + b"\x00")
                continue
            digest.update(b"file\x00" + name.encode("utf-8") + b"\x00")
            digest.update(hashlib.sha256(_normalised_bytes(data)).digest())
            files += 1
    return ComponentFingerprint(
        digest=digest.hexdigest()[:FINGERPRINT_HEX_CHARS],
        files=files,
        missing=tuple(sorted(missing)),
        unreadable=tuple(sorted(set(unreadable))),
    )


def feature_presence(root: Path | None = None) -> tuple[FeaturePresence, ...] | None:
    """What the disk says about every feature the registry declares.

    ``None`` means the registry could not be read - UNDECIDABLE, never an
    empty tuple, for the same reason :func:`registry_features` returns ``None``.
    Ordered by the layer ladder and then by name, so two calls over one tree
    print in one order.

    Every component goes through :func:`component_state`, so a component that
    could not be LOOKED AT makes its feature ``unreadable`` rather than
    counting towards ``absent``: a presence verdict is only ever taken from an
    answer the filesystem actually gave.
    """
    features = _feature_table(root)
    if features is None:
        return None
    found: list[FeaturePresence] = []
    for name, spec in features.items():
        layer = ""
        components: list[str] = []
        if isinstance(spec, dict):
            if isinstance(spec.get("layer"), str):
                layer = spec["layer"]
            if isinstance(spec.get("components"), list):
                components = [c for c in spec["components"] if isinstance(c, str) and c.strip()]
        total = len(components)
        states = [component_state(component, root) for component in components]
        present = states.count("present")
        unreadable = states.count("unreadable")
        if unreadable:
            state = "unreadable"
        elif total == 0:
            state = "unevidenced"
        elif present == total:
            state = "present"
        elif present == 0:
            state = "absent"
        else:
            state = "partial"
        found.append(
            FeaturePresence(
                name=str(name),
                layer=layer,
                state=state,
                found=present,
                total=total,
                unreadable=unreadable,
            )
        )
    ladder = {layer: index for index, layer in enumerate(LAYER_ORDER)}
    return tuple(
        sorted(found, key=lambda p: (ladder.get(p.layer, len(LAYER_ORDER)), p.name))
    )


def derived_edition(root: Path | None = None) -> DerivedEdition:
    """The edition the components on disk make, checked against the registry.

    An edition is a PREFIX of :data:`LAYER_ORDER`, so the derivation is: walk
    the ladder from the weakest layer while every feature of each layer is
    fully present, and the last layer that held is the edition. Anything else -
    a layer missing beneath a layer that is present, a half-copied feature, a
    feature at a layer this ladder does not know - is an unrecognized mix,
    reported as what was found. Never raises.

    ONE state is checked before the ladder is walked at all: a component that
    could not be read. The ladder's every step is an inference from an ABSENCE,
    so a component keel was refused makes the whole derivation unsound - it
    would confidently report a smaller edition, which is a wrong answer that
    looks exactly like a right one. That case returns no layer, names the
    unreadable paths, and says "cannot derive".
    """
    presence = feature_presence(root)
    if presence is None:
        return DerivedEdition(
            note=f"no readable feature registry at {registry_path(root)}"
        )
    if not presence:
        return DerivedEdition(note="the feature registry declares no features")
    unreadable = tuple(
        sorted(
            component
            for component in (component_paths(root) or ())
            if component_state(component, root) == "unreadable"
        )
    )
    if unreadable:
        head = ", ".join(unreadable[:UNREADABLE_NAMED])
        more = (
            f" and {len(unreadable) - UNREADABLE_NAMED} more"
            if len(unreadable) > UNREADABLE_NAMED
            else ""
        )
        return DerivedEdition(
            features=presence,
            unreadable=unreadable,
            note=(
                f"cannot derive: {len(unreadable)} component(s) unreadable "
                f"({head}{more}) - the edition is derived from which components "
                f"are ABSENT, and a component that could not be looked at is "
                f"not evidence of absence"
            ),
        )
    unknown_layers = sorted(
        {p.layer or "(no layer)" for p in presence if p.layer not in LAYER_ORDER}
    )
    states: dict[str, set[str]] = {}
    for p in presence:
        states.setdefault(p.layer, set()).add(p.state)
    ladder = [layer for layer in LAYER_ORDER if layer in states]
    reached = ""
    for layer in ladder:
        if states[layer] == {"present"}:
            reached = layer
            continue
        break
    start = ladder.index(reached) + 1 if reached else 0
    above = [layer for layer in ladder[start:] if states[layer] != {"absent"}]
    if unknown_layers:
        return DerivedEdition(
            features=presence,
            note=(
                "the registry declares feature(s) at layer(s) outside the "
                f"edition ladder: {', '.join(unknown_layers)}"
            ),
        )
    if not reached:
        return DerivedEdition(
            features=presence,
            note="no edition's layer is completely present on disk",
        )
    if above:
        return DerivedEdition(
            features=presence,
            note=(
                f"components above the {reached} layer are present while "
                f"{reached}'s ladder is the deepest one complete: "
                f"{', '.join(above)}"
            ),
        )
    return DerivedEdition(layer=reached, features=presence)
