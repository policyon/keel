#!/usr/bin/env python3
"""Edition bundle generator - build/editions/<name>/ from the feature registry.

Contract
--------
Reads   : ``scripts/keel-features.json`` (the feature/component/requires
          registry) and every path its owned features name, plus the fixed
          SHARED_PAYLOAD list of files identical across every edition, plus
          ``.claude-plugin/plugin.json`` for the fields every bundle shares.
          In ``--validate`` mode, also every generated bundle's own
          ``hooks/hooks.json``, ``.claude-plugin/plugin.json`` and
          ``scripts/keel-features.json``, read back for the validation
          assertions below - read only: ``--validate`` never writes into a
          bundle, it judges exactly what generation produced. Nothing else in
          the tree is opened.
Emits   : one ``WROTE`` line per bundle on stdout, naming the bundle path and
          the file count copied into it; on failure, one loud ``ERROR`` line
          naming the missing path and the feature that claims it. In
          ``--validate`` mode, one ``VALID <bundle> (<n> files)`` or
          ``INVALID <bundle> (<n> files): <assertion>[; <assertion>...]``
          line per requested target instead - named by the bundle
          directory, so the distribution reports as ``keel``.
Writes  : ``<out>/<bundle-name>/`` for each requested target - the source
          tree's owned files and directories copied verbatim, plus two files
          rewritten by generation itself: ``.claude-plugin/plugin.json``
          (``name`` rewritten to the edition name; ``description`` rewritten
          to the source description with this edition's EDITION_DESCRIPTIONS
          clause appended; every other field, including ``version``, copied
          through verbatim - EXCEPT under ``--distribution``, where both
          fields are the source manifest's own, verbatim: see "The
          distribution" below) and ``scripts/keel-features.json``, whose
          ``features`` table is narrowed to this edition's feature closure.
          Every bundle therefore ships a registry describing exactly its own
          contents and nothing else - see "Registry scoping" below. Any
          bundle directory that already exists at the target is replaced
          wholesale, never merged into. A generation failure leaves no
          partial bundle behind: the half-built directory is removed before
          the error is reported. In ``--validate`` mode, when ``--out`` is
          not given, bundles are generated into a temporary directory that
          is removed when validation finishes - validation never leaves a
          ``build/`` directory behind. ``--validate`` writes nothing of its
          own: with an explicit ``--out``, the bundles left behind are
          byte-for-byte what the same command without ``--validate`` would
          have left there. The source repository's own registry and manifest
          are never modified, in either mode.

Registry scoping
----------------
``scripts/keel-features.json`` is a kernel component, so every edition
carries it. It is not copied verbatim: generation rewrites the bundle's copy
with the ``features`` table narrowed to that edition's closure, every other
top-level key of the source document preserved. The reason is that the full
registry names every other edition's features, whose components this bundle
deliberately does not carry - a closure check run against a trimmed bundle
(here under ``--validate``, or at a user's site against an installed
edition) would fail on-disk existence clauses over paths the bundle never
claimed to carry. For ``keel-fleet`` the scoped registry equals the source
registry by construction: that edition's closure is every feature. Narrowing
never blunts the bundle-escape clause - a shipped page invoking a skill this
edition leaves out is still caught, because the invocation is resolved
against what actually shipped.
Argv    : ``--project DIR`` (default: this file's repo root), ``--out DIR``
          (default: ``<project>/build/editions``, or ``<project>/dist`` under
          ``--distribution``, or a temporary directory under ``--validate``
          when ``--out`` is omitted), ``--edition NAME`` (one of the keys in
          EDITIONS; default: all four), ``--distribution`` (emit the tracked
          distribution instead of the editions - mutually exclusive with
          ``--edition``; see "The distribution" below), ``--validate``
          (generate every requested target and check it rather than only
          generating it - see "Validation assertions" below).

Validation assertions
----------------------
Under ``--validate``, each requested edition is generated as normal and then
checked against four assertions; any failing assertion makes that edition
INVALID, named by which assertion failed:

(a) closure  - ``keel_checks.check_closure`` (scripts/keel_checks.py) reports
    no violation against the generated bundle root, reading the bundle's own
    ``scripts/keel-features.json`` as generation wrote it - already scoped to
    this edition's closure (see "Registry scoping" above). Validation does
    not touch that file: a bundle whose registry is missing or wrong fails
    this assertion instead of being quietly repaired.
(b) manifest - the bundle's ``.claude-plugin/plugin.json`` parses as JSON,
    its ``version`` equals the source repository's
    ``.claude-plugin/plugin.json`` ``version``, and its ``name`` and
    ``description`` are what generation was asked to write: for an edition,
    the edition name and the source description with this edition's
    EDITION_DESCRIPTIONS clause appended; for the distribution, the source
    manifest's own ``name`` and ``description``, verbatim. The distribution
    is not skipped past this assertion - it is checked against the other
    expectation, and additionally that its ``name`` equals the directory the
    bundle was written to, because that directory name is what
    ``marketplace.json`` points an install at.
(c) hooks    - the bundle carries ``hooks/hooks.json``, and every
    ``hooks/<file>.py`` path named inside its command strings exists in the
    bundle.
(d) exclusion - no file in the generated bundle sits under an
    EXCLUDED_PATHS prefix (the same vocabulary generation itself enforces,
    not duplicated here - see ``excluded_reason`` below).

Exit codes
----------
0  every requested bundle emitted (generation), or every requested target
   validated VALID (``--validate``).
1  a generation failure - a registry component or shared-payload path that
   does not exist on disk, named with its owning feature, or one that names
   (or contains) an always-excluded path, named with the exclusion rule it
   violates; under ``--validate``, at least one requested edition is
   INVALID (including one whose generation itself failed - reported as a
   failed assertion rather than escalated to exit 2).
2  cannot run at all - the registry is missing/unreadable/malformed, an
   unknown edition name was requested, or (``--validate`` only) the source
   repository's own plugin manifest cannot be read.

Editions
--------
Each edition is the transitive closure (over the registry's ``requires``
graph) of a fixed set of top-level features, and the four are strict
supersets of one another by construction:

    keel-core   = kernel + orchestration
    keel        = keel-core + knowledge
    keel-govern = keel + review
    keel-fleet  = keel-govern + viewer

The distribution
----------------
``--distribution`` emits ONE bundle, at ``<out>/keel`` (default out:
``<project>/dist``), and it is the bundle
``.claude-plugin/marketplace.json`` names as its plugin ``source``. It is
TRACKED in this repository, so a fresh clone carries an installable tree
with no build step, and an install from that manifest copies the bundle
rather than the repository - none of this repository's own records travel
with it, because EXCLUDED_PATHS is enforced over everything generation
copies. (What some other marketplace manifest elsewhere on a machine points
at is not governed by anything in this file.)

Two things make it a distribution rather than a fifth edition, and both are
deliberate:

* Its COMPONENT SET is ``DISTRIBUTION_EDITION`` - the full closure. An
  install has always carried every feature, and the edition literally named
  ``keel`` is a NARROWER closure (no ``review``, no ``viewer``): shipping it
  would silently drop the reviewer agents and the dashboard.
* Its MANIFEST keeps the source manifest's own ``name`` and ``description``,
  unrewritten, so the bundle's ``name`` EQUALS the ``name`` on the
  marketplace entry that points at it. Which of the two a harness prefers
  when they disagree is undocumented upstream, and a mismatch is reported to
  hard-error on some platforms; making them agree consults no precedence at
  all. That is the whole reason this mode exists instead of a
  ``EDITIONS["keel-dist"]`` entry - an edition's manifest is rewritten to the
  edition's name by construction.

The tracked bundle going stale is the failure this mode invites, and it is
guarded outside this file: ``keel_checks.check_distribution`` regenerates
into a temporary directory and fails when the tracked tree differs.

Failure policy
--------------
FAIL-CLOSED (convention 12). A registry component or shared file that does
not exist on disk is a loud failure naming the path and the feature that
claims it - never a silently partial bundle (convention 7). A registry that
names an EXCLUDED_PATHS path is the same kind of loud failure, not a quiet
skip: a bundle is never trimmed behind the registry's back. Under
``--validate``, a bundle failing any of the four assertions is reported
INVALID by name and assertion, never silently skipped or downgraded to a
warning; a bundle that fails to generate at all is reported INVALID with
the generation error as its failing assertion, not swallowed. The registry
itself missing, unreadable or malformed is exit 2: nothing can be generated
from a registry that cannot be read.

Constraints
-----------
Python 3.10+, standard library only (R7, R14) plus this repository's own
``scripts/keel_checks.py`` (imported for ``check_closure`` under
``--validate`` only - a sibling script, not a third-party dependency). No
subprocess for file operations - copying uses ``shutil`` directly, never a
shelled-out ``cp`` or ``git`` (R5 in spirit: no payload-derived string ever
reaches a shell). Every text file this script itself reads or writes names
its encoding explicitly (convention 6); binary/tree copies go through
``shutil``, which copies bytes without a text encoding to declare. Excluded
always, regardless of registry
contents: ``.claude-plugin/marketplace.json`` (the hosted-repo descriptor,
never a plugin payload), ``tests/``, ``docs/internal/`` (also gitignored),
``.keel/``, ``.github/``, ``.gitignore``. That claim is enforced, not merely
documented: EXCLUDED_PATHS below is checked against every registry component
path and every shared-payload path - and against everything under a named
directory - before anything is copied, so a registry naming one of them
fails generation (exit 1) instead of smuggling it into a bundle.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple

import keel_checks

#: The feature registry, relative to the project root.
FEATURES_REGISTRY = "scripts/keel-features.json"

#: The source plugin manifest; every bundle gets a copy with only ``name``
#: rewritten to the edition name (version and every other field are shared).
PLUGIN_MANIFEST = ".claude-plugin/plugin.json"

#: Files identical across every edition, copied into every bundle regardless
#: of which features it includes. ``hooks/hooks.json`` is NOT here: it is
#: already a kernel component, and every edition includes kernel.
SHARED_PAYLOAD: tuple[str, ...] = (
    "LICENSE",
    "NOTICE",
    "README.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "docs/keel-rules.md",
    "docs/keel-conventions.md",
    "docs/keel-governance.md",
    "docs/keel-why.md",
    "docs/keel-trust.md",
    "templates/keel-policy.md",
    "templates/keel-plan-contract.md",
    ".claude-plugin/keel-pins.json",
)

#: Project-relative paths no bundle may ever carry, whatever the registry
#: says. A trailing ``/`` reads as "this directory and everything under it";
#: the rest are exact files. Enforced by ``excluded_reason`` below - naming
#: one of these in the registry or in SHARED_PAYLOAD is a generation failure,
#: never a quiet omission.
EXCLUDED_PATHS: tuple[str, ...] = (
    ".claude-plugin/marketplace.json",
    "tests/",
    "docs/internal/",
    ".keel/",
    ".github/",
    ".gitignore",
)

#: One house-voice clause per edition, appended to the source manifest's
#: ``description`` (space-joined) to make each bundle's ``plugin.json``
#: describe itself rather than the whole repository. Every other manifest
#: field - including ``version`` - is the source's, untouched; only
#: ``name`` and ``description`` vary bundle to bundle.
EDITION_DESCRIPTIONS: dict[str, str] = {
    "keel-core": "Core edition: the gates and the ceremonies, nothing else.",
    "keel": (
        "Standard edition: the gates and the ceremonies, plus the knowledge "
        "that remembers them."
    ),
    "keel-govern": (
        "Govern edition: the standard edition, plus reviewers who read what "
        "shipped."
    ),
    "keel-fleet": (
        "Fleet edition: the govern edition, plus the dashboard that watches "
        "the whole fleet."
    ),
}

#: Each edition's top-level feature set, before the ``requires`` closure is
#: taken. Order here is documentation only; EDITIONS_ORDER below fixes the
#: strict-superset sequence the tests assert against.
EDITIONS: dict[str, tuple[str, ...]] = {
    "keel-core": ("kernel", "orchestration"),
    "keel": ("kernel", "orchestration", "knowledge"),
    "keel-govern": ("kernel", "orchestration", "knowledge", "review"),
    "keel-fleet": ("kernel", "orchestration", "knowledge", "review", "viewer"),
}

#: The strict-superset sequence: EDITIONS_ORDER[i] is a subset of
#: EDITIONS_ORDER[i + 1]'s bundle.
EDITIONS_ORDER: tuple[str, ...] = ("keel-core", "keel", "keel-govern", "keel-fleet")

#: The distribution's component set: the FULL closure, not the edition that
#: happens to share the plugin's name. See the module docstring's "The
#: distribution" - ``EDITIONS["keel"]`` omits ``review`` and ``viewer``, so
#: shipping it would drop the reviewer agents and the dashboard an install
#: carries today.
DISTRIBUTION_EDITION = "keel-fleet"

#: The distribution's directory name, and therefore the last segment of the
#: ``source`` in ``.claude-plugin/marketplace.json``. The bundle's manifest
#: ``name`` is NOT taken from here - it is the source manifest's own, and
#: ``--validate`` asserts the two agree rather than this file assuming it.
DISTRIBUTION_DIRNAME = "keel"

#: Where ``--distribution`` writes when ``--out`` is not given, project-
#: relative. ``build/`` is scratch and gitignored; ``dist/`` is tracked (see
#: ``.gitignore``, which says so in both directions).
DISTRIBUTION_OUT = "dist"

#: The tracked distribution, project-relative - the one path
#: ``marketplace.json`` and ``keel_checks.check_distribution`` both mean.
DISTRIBUTION_PATH = f"{DISTRIBUTION_OUT}/{DISTRIBUTION_DIRNAME}"

class Target(NamedTuple):
    """One thing to generate: whose closure, what the directory is called,
    and whether the manifest keeps the source's own name/description.

    Editions and the distribution differ in exactly these three values and
    nowhere else, which is why they run through one generation path rather
    than two.
    """

    edition: str
    bundle_name: str
    source_identity: bool


def edition_target(name: str) -> Target:
    """The target for one edition: named for itself, manifest rewritten."""
    return Target(name, name, False)


#: The distribution's target - see the module docstring's "The distribution".
DISTRIBUTION_TARGET = Target(DISTRIBUTION_EDITION, DISTRIBUTION_DIRNAME, True)


#: Matches a ``hooks/<file>.py`` path wherever it appears inside a
#: ``hooks.json`` command string - e.g. inside ``"$R/hooks/keel_hook.py"`` -
#: so ``--validate`` can check every hook script the manifest invokes is
#: actually present in the bundle.
HOOK_REFERENCE_RE = re.compile(r"hooks/([A-Za-z0-9_.-]+\.py)")


class EditionError(Exception):
    """A generation failure - always carries the offending path and reason."""


def repo_root() -> Path:
    """Repository root, derived from this file's location (scripts/ is a child)."""
    return Path(__file__).resolve().parent.parent


def load_registry(project: Path) -> dict:
    """The parsed feature registry. Raises EditionError; never returns a stub.

    FAIL-CLOSED: a missing, unreadable or malformed registry is not a reason
    to fall back to an empty feature set (convention 7).
    """
    path = project / FEATURES_REGISTRY
    if not path.is_file():
        raise EditionError(f"no feature registry at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EditionError(f"cannot read {path}: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise EditionError(f"{path} is not valid JSON: {exc}") from exc
    features = data.get("features")
    if not isinstance(features, dict) or not features:
        raise EditionError(f"{path} declares no non-empty 'features' table")
    return features


def feature_closure(names: tuple[str, ...], features: dict) -> list[str]:
    """The given features plus everything they transitively require.

    Sorted for deterministic output. Raises EditionError on an unknown
    feature name rather than silently excluding it.
    """
    seen: set[str] = set()
    stack = list(names)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        if name not in features:
            raise EditionError(f"edition names undefined feature '{name}'")
        seen.add(name)
        stack.extend(features[name].get("requires", []))
    return sorted(seen)


def owned_components(feature_names: list[str], features: dict) -> list[tuple[str, str]]:
    """(component, owning_feature) pairs for every feature in ``feature_names``.

    Deduplicated by component path - a component owned by two of this
    edition's features is copied once, not twice.
    """
    seen: dict[str, str] = {}
    for feature in feature_names:
        for component in features[feature].get("components", []):
            seen.setdefault(component, feature)
    return sorted(seen.items())


def _normalize(path_text: str) -> str:
    """A payload path as a bare project-relative POSIX path, for comparison.

    Separators are unified, ``.`` and ``..`` segments are resolved lexically
    and leading/trailing slashes dropped, so ``./tests/``, ``tests\\x`` and
    ``docs/../tests/x`` cannot slip past a prefix comparison that only
    understands ``tests/``.
    """
    return posixpath.normpath(path_text.replace("\\", "/")).strip("/")


def excluded_reason(path_text: str) -> str | None:
    """The EXCLUDED_PATHS entry ``path_text`` violates, or None if it is clean."""
    candidate = _normalize(path_text)
    for excluded in EXCLUDED_PATHS:
        rule = _normalize(excluded)
        if candidate == rule or candidate.startswith(f"{rule}/"):
            return excluded
    return None


def excluded_conflict(project: Path, path_text: str) -> tuple[str, str] | None:
    """(offending path, exclusion rule) for a payload path, or None if clean.

    Checks the named path itself and - when it names a directory that exists -
    every path under it, so a component naming a parent directory cannot carry
    an excluded child in on its back.
    """
    rule = excluded_reason(path_text)
    if rule is not None:
        return path_text, rule
    base = _normalize(path_text)
    src = project / base
    if src.is_dir():
        for child in sorted(src.rglob("*")):
            relative = f"{base}/{child.relative_to(src).as_posix()}"
            child_rule = excluded_reason(relative)
            if child_rule is not None:
                return _normalize(relative), child_rule
    return None


def _copy_path(src: Path, dst: Path) -> int:
    """Copy one component (file or directory) into place; return file count."""
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return sum(1 for path in dst.rglob("*") if path.is_file())
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return 1


def write_plugin_manifest(
    project: Path,
    bundle: Path,
    edition_name: str,
    *,
    source_identity: bool = False,
) -> None:
    """Copy plugin.json into the bundle with 'name' and 'description' rewritten.

    ``name`` becomes the edition name; ``description`` becomes the source
    manifest's own description with this edition's EDITION_DESCRIPTIONS
    clause appended (space-joined) - so a bundle describes itself, not the
    whole repository. Every other field, including ``version``, is copied
    through verbatim.

    ``source_identity=True`` is the distribution's case and the one
    exception: both fields are left exactly as the source manifest has them,
    because the distribution IS the repository's plugin rather than a cut of
    it, and its ``name`` has to equal the marketplace entry's (module
    docstring, "The distribution"). Nothing else changes - the same copy, the
    same version, the same everything-else-verbatim rule.
    """
    src = project / PLUGIN_MANIFEST
    if not src.is_file():
        raise EditionError(f"no plugin manifest at {src}")
    try:
        manifest = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditionError(f"cannot read {src}: {exc}") from exc
    if not source_identity:
        manifest["name"] = edition_name
        base_description = manifest.get("description", "")
        clause = EDITION_DESCRIPTIONS[edition_name]
        manifest["description"] = (
            f"{base_description} {clause}" if base_description else clause
        )
    dst = bundle / PLUGIN_MANIFEST
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def write_scoped_registry(
    project: Path, bundle: Path, edition_name: str, features: dict
) -> bool:
    """Narrow the bundle's registry copy to this edition's feature closure.

    Returns True when a registry was present in the bundle - copied there by
    one of the edition's own components - and has been rewritten in place;
    False when this edition ships no registry at all, in which case nothing
    is created: generation never adds a file the registry did not claim, and
    ``--validate``'s closure assertion reports the absence rather than
    papering over it.

    The source document's other top-level keys (``v``) are preserved, so a
    bundle whose closure is every feature (``keel-fleet``) ships a registry
    equal to the source one, modulo formatting.
    """
    dst = bundle / FEATURES_REGISTRY
    if not dst.is_file():
        return False
    src = project / FEATURES_REGISTRY
    try:
        document = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditionError(f"cannot read {src}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(
        document.get("features"), dict
    ):
        raise EditionError(f"{src} declares no 'features' table to scope")
    closure = set(feature_closure(EDITIONS[edition_name], features))
    document["features"] = {
        name: spec
        for name, spec in document["features"].items()
        if name in closure
    }
    with open(dst, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    return True


def generate_edition(
    edition_name: str,
    project: Path,
    out_root: Path,
    features: dict,
    *,
    bundle_name: str | None = None,
    source_identity: bool = False,
) -> tuple[Path, int]:
    """Emit one bundle from ``edition_name``'s closure. Returns
    ``(bundle_dir, file_count)``.

    The bundle's ``scripts/keel-features.json`` is scoped to this edition's
    closure here, at generation time - it is the only registry any bundle
    ever contains, and ``--validate`` reads it without rewriting it. Scoping
    replaces a file the copy loop already counted, so ``file_count`` is
    unaffected.

    ``bundle_name`` names the directory written under ``out_root``; it
    defaults to the edition name, and the distribution is the one caller that
    differs (``dist/keel`` from the ``keel-fleet`` closure). ``source_identity``
    is passed straight to :func:`write_plugin_manifest`. Both are keyword-only
    and both default to the edition behaviour, so the four editions take
    exactly the path they took before this parameter existed.

    Raises EditionError - naming the missing path and its owning feature -
    without leaving a partial bundle directory behind: the target is removed
    before the error propagates.
    """
    if edition_name not in EDITIONS:
        raise EditionError(
            f"unknown edition '{edition_name}'; choices are {sorted(EDITIONS)}"
        )
    bundle = out_root / (bundle_name or edition_name)
    if bundle.exists():
        shutil.rmtree(bundle)
    bundle.mkdir(parents=True)
    file_count = 0
    try:
        closure = feature_closure(EDITIONS[edition_name], features)
        for component, feature in owned_components(closure, features):
            conflict = excluded_conflict(project, component)
            if conflict is not None:
                offender, rule = conflict
                raise EditionError(
                    f"feature '{feature}' names an always-excluded path: "
                    f"{offender} (exclusion rule '{rule}': never a plugin payload)"
                )
            src = project / component.rstrip("/")
            if not src.exists():
                raise EditionError(
                    f"feature '{feature}' names a path that does not exist: {component}"
                )
            file_count += _copy_path(src, bundle / component.rstrip("/"))
        for shared in SHARED_PAYLOAD:
            conflict = excluded_conflict(project, shared)
            if conflict is not None:
                offender, rule = conflict
                raise EditionError(
                    f"shared payload names an always-excluded path: "
                    f"{offender} (exclusion rule '{rule}': never a plugin payload)"
                )
            src = project / shared
            if not src.exists():
                raise EditionError(f"shared payload path does not exist: {shared}")
            file_count += _copy_path(src, bundle / shared)
        write_plugin_manifest(
            project, bundle, edition_name, source_identity=source_identity
        )
        file_count += 1
        # After every copy, so a directory component copied over the registry
        # cannot restore the verbatim (whole-repo) table behind this.
        write_scoped_registry(project, bundle, edition_name, features)
    except EditionError:
        shutil.rmtree(bundle, ignore_errors=True)
        raise
    return bundle, file_count


def generate_distribution(
    project: Path, out_root: Path, features: dict
) -> tuple[Path, int]:
    """Emit the tracked distribution at ``out_root/keel``. Returns
    ``(bundle_dir, file_count)``.

    One call, so every producer of the shipped bundle - the CLI here,
    ``keel_checks.check_distribution``, and the tests - generates the same
    bytes from the same parameters rather than each spelling them out. See
    the module docstring's "The distribution" for why the component set is
    ``keel-fleet``'s and the manifest identity is the source's.
    """
    return generate_edition(
        DISTRIBUTION_EDITION,
        project,
        out_root,
        features,
        bundle_name=DISTRIBUTION_DIRNAME,
        source_identity=True,
    )


def _bundle_files(bundle: Path) -> list[str]:
    """Every file under ``bundle``, as bundle-relative POSIX paths, sorted."""
    return sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file()
    )


def validate_edition(
    edition_name: str,
    project: Path,
    out_root: Path,
    features: dict,
    source_version: object,
    *,
    bundle_name: str | None = None,
    source_identity: bool = False,
) -> tuple[int, list[str]]:
    """Generate one edition into ``out_root`` and check it. Returns
    ``(file_count, violations)`` - an empty ``violations`` list means VALID.

    Past the generation call this is a pure reader: every assertion below
    opens bundle files read-only, so the bundle a validated ``--out`` is left
    holding is byte-for-byte the one plain generation writes.

    A generation failure is reported as a single violation (file_count 0)
    rather than raised, so the caller can validate every requested edition
    even when one of them fails to build (fail-closed, never a partial run
    that silently skips the rest).

    ``bundle_name`` and ``source_identity`` are handed to
    :func:`generate_edition` unchanged and then judged: assertion (b) below
    checks the manifest against what those two asked for, so the
    distribution is validated rather than exempted.

    See the module docstring's "Validation assertions" section for what
    (a)-(d) below check and why.
    """
    try:
        bundle, file_count = generate_edition(
            edition_name,
            project,
            out_root,
            features,
            bundle_name=bundle_name,
            source_identity=source_identity,
        )
    except EditionError as exc:
        return 0, [f"generation: {exc}"]

    violations: list[str] = []

    # (a) closure - keel_checks.check_closure reads the registry FROM the
    # bundle it is given, and generation already wrote that registry scoped
    # to this edition's closure (see write_scoped_registry). Nothing is
    # rewritten here: this assertion judges exactly what generation
    # produced, so a bundle shipping a missing or unscoped registry fails
    # rather than being silently corrected on the way past. Clause (c) of
    # check_closure still resolves every prose invocation against what
    # actually shipped, catching a skill that invokes a feature the edition
    # leaves out.
    violations.extend(f"closure: {v}" for v in keel_checks.check_closure(bundle))

    # (b) manifest sanity - parses, shares the version, and carries the name
    # and description generation was ASKED for: an edition's own name plus
    # its EDITION_DESCRIPTIONS clause, or - under source_identity, which is
    # the distribution - the source manifest's own two fields verbatim. The
    # distribution is judged here rather than exempted; the expectation is
    # what differs, not whether there is one.
    manifest_path = bundle / PLUGIN_MANIFEST
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        violations.append(f"manifest: cannot read {manifest_path}: {exc}")
    except ValueError as exc:
        violations.append(f"manifest: {manifest_path} is not valid JSON: {exc}")
    else:
        if manifest.get("version") != source_version:
            violations.append(
                f"manifest: version is {manifest.get('version')!r}, "
                f"expected {source_version!r}"
            )
        try:
            source_manifest = json.loads(
                (project / PLUGIN_MANIFEST).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            violations.append(
                f"manifest: cannot read source {project / PLUGIN_MANIFEST}: {exc}"
            )
        else:
            source_description = source_manifest.get("description", "")
            if source_identity:
                expected_name = source_manifest.get("name")
                expected_description = source_description
            else:
                expected_name = edition_name
                clause = EDITION_DESCRIPTIONS.get(edition_name, "")
                expected_description = (
                    f"{source_description} {clause}" if source_description else clause
                )
            if manifest.get("name") != expected_name:
                violations.append(
                    f"manifest: name is {manifest.get('name')!r}, "
                    f"expected {expected_name!r}"
                )
            if manifest.get("description") != expected_description:
                violations.append(
                    f"manifest: description is {manifest.get('description')!r}, "
                    f"expected {expected_description!r}"
                )
        # True of an edition by construction and of the distribution by
        # design, and asserted for both: a manifest whose name disagrees with
        # the directory it sits in would make a marketplace entry pointing at
        # that directory carry a name the bundle contradicts, which is the
        # one thing this project decided not to leave to an undocumented
        # precedence.
        if manifest.get("name") != bundle.name:
            violations.append(
                f"manifest: name is {manifest.get('name')!r} but the bundle "
                f"directory is {bundle.name!r}"
            )

    # (c) hooks/hooks.json and every hooks/<file>.py it references.
    hooks_json = bundle / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        violations.append("hooks: no hooks/hooks.json in bundle")
    else:
        try:
            hooks_text = hooks_json.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"hooks: cannot read {hooks_json}: {exc}")
        else:
            for hook_file in sorted(set(HOOK_REFERENCE_RE.findall(hooks_text))):
                if not (bundle / "hooks" / hook_file).is_file():
                    violations.append(
                        f"hooks: hooks.json references hooks/{hook_file}, "
                        f"absent from the bundle"
                    )

    # (d) exclusion - the T20 guard's own vocabulary, not duplicated here.
    offenders = [
        rel for rel in _bundle_files(bundle) if excluded_reason(rel) is not None
    ]
    if offenders:
        violations.append(f"exclusion: bundle carries excluded path(s): {offenders}")

    return file_count, violations


def _run_validation(
    project: Path, out_root: Path, targets: list[Target], features: dict
) -> int:
    """Validate every target in ``targets``, printing one VALID/INVALID line
    each. Returns 2 if the source repository's own plugin manifest cannot be
    read (nothing to compare bundle versions against), else 1 if any
    requested target is INVALID, else 0.
    """
    manifest_path = project / PLUGIN_MANIFEST
    try:
        source_version = json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "version"
        )
    except OSError as exc:
        print(
            f"ERROR gen-editions could not run: cannot read {manifest_path}: {exc}",
            file=sys.stderr,
        )
        return 2
    except ValueError as exc:
        print(
            f"ERROR gen-editions could not run: {manifest_path} is not valid JSON: "
            f"{exc}",
            file=sys.stderr,
        )
        return 2

    any_invalid = False
    for target in targets:
        file_count, violations = validate_edition(
            target.edition,
            project,
            out_root,
            features,
            source_version,
            bundle_name=target.bundle_name,
            source_identity=target.source_identity,
        )
        if violations:
            any_invalid = True
            print(
                f"INVALID {target.bundle_name} ({file_count} files): "
                f"{'; '.join(violations)}"
            )
        else:
            print(f"VALID {target.bundle_name} ({file_count} files)")

    return 1 if any_invalid else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="keel_gen_editions.py", description="generate edition bundles"
    )
    parser.add_argument("--project", type=Path, default=None, help="project root")
    parser.add_argument("--out", type=Path, default=None, help="bundle output dir")
    what = parser.add_mutually_exclusive_group()
    what.add_argument(
        "--edition", choices=sorted(EDITIONS), default=None, help="one edition only"
    )
    what.add_argument(
        "--distribution",
        action="store_true",
        help=f"emit the tracked distribution ({DISTRIBUTION_PATH}) instead of "
        f"the editions: the full closure, carrying the source manifest's own "
        f"name and description",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="generate every requested edition and validate it (closure, "
        "manifest, hooks, exclusion) instead of only generating it",
    )
    args = parser.parse_args(argv)

    project = (args.project or repo_root()).resolve()
    if args.distribution:
        targets = [DISTRIBUTION_TARGET]
    elif args.edition:
        targets = [edition_target(args.edition)]
    else:
        targets = [edition_target(name) for name in EDITIONS_ORDER]

    try:
        features = load_registry(project)
    except EditionError as exc:
        print(f"ERROR gen-editions could not run: {exc}", file=sys.stderr)
        return 2

    if args.validate:
        # No explicit --out: validate in a scratch directory that is removed
        # when it finishes, so validation never leaves build/ behind.
        if args.out is not None:
            return _run_validation(project, args.out.resolve(), targets, features)
        with tempfile.TemporaryDirectory() as tmp:
            return _run_validation(project, Path(tmp), targets, features)

    default_out = (
        project / DISTRIBUTION_OUT if args.distribution else project / "build" / "editions"
    )
    out_root = (args.out or default_out).resolve()
    failures: list[str] = []
    for target in targets:
        try:
            bundle, file_count = generate_edition(
                target.edition,
                project,
                out_root,
                features,
                bundle_name=target.bundle_name,
                source_identity=target.source_identity,
            )
        except EditionError as exc:
            print(f"ERROR gen-editions: {exc}", file=sys.stderr)
            failures.append(str(exc))
            continue
        print(f"WROTE {bundle} ({file_count} files)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
