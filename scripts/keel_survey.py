#!/usr/bin/env python3
"""environment and registration report (R30, R9) - never blocks anything.

Contract
--------
Reads   : the surveyed project (``--project``, else ``CLAUDE_PROJECT_DIR``,
          else the current directory) for its arming file - including its
          optional ``## Policy lock`` configuration section, parsed by
          ``keel_gate.policy_lock_section`` so the survey can never disagree
          with what the gate itself honours - for another harness's arming
          file, and for its audit log (``.keel/audit/keel-audit.jsonl`` - the
          policy-lock friction counts, denials and bypasses alike); this
          plugin's own
          ``.claude-plugin/plugin.json``, ``.claude-plugin/keel-pins.json``
          and ``CHANGELOG.md``; the contents of the component paths its own
          ``scripts/keel-features.json`` names, read through
          ``keel_features.component_fingerprint`` so the report can say WHICH
          tree it is describing (T168); the harness's own install record at
          ``~/.claude/plugins/installed_plugins.json`` and the ``.orphaned_at``
          /``.in_use`` markers in this installation's root, so the survey can
          check its own installation instead of assuming it;
          ``~/.claude/settings.json``,
          ``<project>/.claude/settings.json`` and every installed-plugin
          ``hooks/hooks.json`` it can find; and the three kill-switch
          environment variables. Nothing else is opened.
Emits   : a human-readable report on stdout, or exactly one line with
          ``--startup``. Every filesystem path in it passes ``keel_redact``
          first, so a survey pasted into an issue carries no username
          (convention 5).
Writes  : nothing at all. A survey that changes what it surveys is not a
          survey.
Argv    : ``--project DIR``, ``--startup`` (one line), ``--json``.

Exit codes
----------
0, ALWAYS - including when it finds a conflict. This is deliberate and is
the one documented exception to the CLI's fail-closed default: a health
report that fails the build the moment it notices something is a report
nobody runs, and R30's rule is that *reporting is total while refusal is
narrow*. Refusal belongs to arming (``/keel:lay``, ``/keel:refit``), which
reads this report; it does not belong here.

R30 - registration ownership
----------------------------
Reporting is total: every PreToolUse and Stop registration keel can see, in
any scope, is listed - whether or not it conflicts, whether or not it is
keel's. Refusal is narrow: exactly one condition is raised as a CONFLICT,
namely another gate stack ARMED over the same project. That condition is now
read from the REGISTRATIONS this same file already collects - a PreToolUse
registration on write tools, or any Stop registration, whose command does not
run one of THIS installation's own hook scripts - with the presence of
``<project>/.claude/POLICY.md`` kept as a fast path. The registration set is
the authority because it is what actually stops work: a foreign stack that
never wrote an arming file into this project still holds the write and stop
events, and a survey that printed those registrations and then said "no
conflicts" is the defect this derivation removes.

Ownership is decided STRUCTURALLY, never by looking for a product name in a
command: ``own_hook_scripts`` lists the hook scripts this installation has on
disk, and ``command_is_own`` asks whether the command references one of them
(or this installation's own ``hooks/`` directory outright), on either path
separator. A second copy of keel installed elsewhere therefore reads as keel
rather than as a rival stack, which is deliberate - two copies of one stack
are not two stacks.

A registered but disarmed observer is listed and left alone: a PreToolUse
registration whose matcher names no write tool cannot stop a write, so it is
reported and never refused. Every conflict names the SCOPE it was found in
and prints its migration step against THAT scope's file, because a migration
step aimed at the wrong file is worse than none - removing an entry from a
user/global settings file retires the other stack in every project on the
machine, and the reader has to be told which file they are being sent to.

Failure policy
--------------
FAIL-OPEN, and reported. Any source it cannot read becomes a stated
"unreadable" note in the report rather than a missing section or a crash: a
survey that goes quiet about the file it could not open is worse than no
survey (convention 7).

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No subprocess, no network.
The plugin-hook search is depth-bounded rather than a full-tree walk, so a
survey cannot turn into an accidental filesystem crawl. Every file read
names its encoding.
"""

from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import re
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
for _extra in (str(_SCRIPTS_DIR), str(_REPO_ROOT / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import keel_checks  # noqa: E402
from keel_attest import parse_ts_ms  # noqa: E402
from keel_events import read_audit  # noqa: E402
from keel_features import (  # noqa: E402
    ComponentFingerprint,
    component_fingerprint,
    derived_edition,
)
from keel_gate import (  # noqa: E402
    ENFORCING_TIER,
    HOLDS_ABSENT,
    HOLDS_ACTIVE,
    HOLDS_NONE,
    HOLDS_UNREADABLE,
    GateError,
    OVERRIDE_REMINDER,
    WORKSHOP_ACTIVE,
    WORKSHOP_INVALID,
    WORKSHOP_NONE,
    WORKSHOP_REFUSED,
    WORKSHOP_UNKNOWN,
    env_on,
    holds_state,
    policy_lock_section,
    policy_tier,
    workshop_state,
)
from keel_redact import redact  # noqa: E402

#: The hook events R30 asks about: the two that can stop work happening.
SCANNED_EVENTS: tuple[str, ...] = ("PreToolUse", "Stop")

#: The kill switches a reader needs to see before believing any gate is live.
KILL_SWITCHES: tuple[str, ...] = ("KEEL_GATE", "KEEL_OVERRIDE", "KEEL_PLAN_TTL_MIN")

#: Another harness's arming file. Its presence in the surveyed project is the
#: FAST PATH to the one ARMED-overlap condition keel raises as a CONFLICT
#: (R30); the registration scan below reaches the same verdict without it.
FOREIGN_POLICY_RELPATH = (".claude", "POLICY.md")

#: The tool names a PreToolUse matcher must mention before that registration
#: can stop a WRITE. Taken from the same list keel's own manifest matches on,
#: so "can stop work" means the same thing on both sides of the question.
WRITE_TOOL_NAMES: tuple[str, ...] = (
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
    "Bash",
    "PowerShell",
)

#: Matchers that select EVERY tool, and therefore every write tool. An absent
#: or blank matcher means the same thing (the harness applies the hook to all
#: tools), and is handled by the same test.
ANY_TOOL_MATCHERS: frozenset[str] = frozenset({"*", ".*", ".*?", "^.*$"})

#: What a registration's scope is CALLED to a reader, and the sentence its
#: migration step adds about the blast radius of editing THAT file. A conflict
#: whose migration names the wrong file is a refusal that damages the reader's
#: machine, which is why the scope travels with the conflict (R30).
SCOPE_LABELS: dict[str, str] = {
    "global": "user/global settings",
    "project": "project settings",
    "plugin": "an installed plugin's hook manifest",
}
SCOPE_MIGRATIONS: dict[str, str] = {
    "global": (
        "that file is the USER-WIDE one, shared by every project on this "
        "machine, so removing the entry retires the other stack EVERYWHERE - "
        "if that is wider than you meant, leave keel at tier 0 or 1 in this "
        "project instead and change nothing"
    ),
    "project": (
        "that file belongs to this project alone, so removing the entry "
        "changes nothing outside it"
    ),
    "plugin": (
        "that file belongs to an installed plugin, so retire it by disabling "
        "or uninstalling that plugin - keel never edits a plugin's manifest"
    ),
}

#: What an entry with no readable ``command`` is called in the report. Such an
#: entry is neither keel's nor safely foreign, so it becomes a scan NOTE
#: rather than a conflict or a silence (convention 7).
NO_COMMAND = "(no command)"

#: The characters that continue a path SEGMENT. A match glued to one of them
#: on either side is a prefix collision, not a path: ``hooks-legacy/`` is not
#: ``hooks/``, ``badhooks/keel_hook.py`` is not ``hooks/keel_hook.py``, and
#: ``keel_hook.pyc`` is not ``keel_hook.py``. A frozenset of single characters
#: on purpose - the empty string (the ends of the command) must read as a
#: boundary, which it does here and would NOT if this were a string.
#: Everything else a command holds - space, quote, ``$``, ``{``, ``;``, ``|``,
#: ``:`` and the separator itself - is a boundary. Used by ``mentions_path``,
#: which every ownership test goes through.
#: Upper case is listed although ``_slashed`` folds it away: a caller that
#: hands this function unfolded text must not get a WIDER answer than one
#: that follows the contract.
SEGMENT_CHARS: frozenset[str] = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.~"  # keel-leak: ignore - the allowed-character set, not a token
)

#: Depth-bounded search for installed plugins' hook manifests.
_PLUGIN_GLOBS: tuple[str, ...] = (
    "*/hooks/hooks.json",
    "*/*/hooks/hooks.json",
    "*/*/*/hooks/hooks.json",
)

#: How much of a registered command reaches the report.
COMMAND_HEAD_CHARS = 60

#: The four immutable edition names (T24) mapped to the short label the
#: report states after "edition:". Keyed by ``plugin.json``'s ``name`` field
#: - the only signal an installed bundle carries about which edition it is.
EDITION_LABELS: dict[str, str] = {
    "keel-core": "core",
    "keel": "standard",
    "keel-govern": "govern",
    "keel-fleet": "fleet",
}


@dataclass(frozen=True)
class Registration:
    """One PreToolUse or Stop hook registration, from any scope."""

    scope: str
    source: str
    event: str
    matcher: str
    command: str

    def line(self) -> str:
        """One redacted report line. Nothing here is ever executed."""
        head = self.command.replace("\n", " ")[:COMMAND_HEAD_CHARS]
        return (
            f"  {self.scope:<8} {redact(self.source)}\n"
            f"           {self.event:<11} {self.matcher or '(any tool)'} -> {redact(head)}"
        )


def project_root(argument: str | None) -> Path:
    """The surveyed project: the flag, else the harness's root, else cwd."""
    if argument and argument.strip():
        return Path(argument)
    env = os.environ.get("CLAUDE_PROJECT_DIR", "")
    return Path(env) if env.strip() else Path(os.getcwd())


def _read_json(path: Path) -> tuple[Any, str | None]:
    """``(document, error)``. An absent file is not an error; it is absence."""
    if not path.is_file():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace")), None
    except (OSError, ValueError) as exc:
        return None, f"unreadable {redact(str(path))}: {type(exc).__name__}: {exc}"


def edition_label(name: str) -> str:
    """The installed edition's report label, derived from ``plugin.json``'s
    ``name`` field alone.

    ``EDITION_LABELS`` covers the four immutable edition names (T24); any
    other name - a fork, a future edition, a manifest edited by hand - is
    reported verbatim as ``"<name> (unrecognized)"`` rather than raising: an
    unrecognized edition name is news for the reader, never a survey error
    (R30, convention 7). An empty name (no manifest, or a manifest with no
    ``name``) reports as ``"(none)"``.
    """
    if not name:
        return "(none)"
    label = EDITION_LABELS.get(name)
    return label if label is not None else f"{name} (unrecognized)"


def version_report() -> dict[str, Any]:
    """Plugin version, edition, the harness pin, and the top CHANGELOG entry
    (R31) - each one derived from the tree wherever the tree can be asked.

    Two of the fields here used to be assertions rather than measurements, and
    T168 replaced both while leaving every existing key spelled as it was:

    * ``agrees`` compares two STRINGS - the manifest's version and the
      changelog's top heading - and that comparison is true of any tree that
      carries a matching pair, however little else it carries. Measured
      2026-08-18: an installed cache snapshot and a working tree differing in
      43 files both printed ``plugin 0.6.0 | changelog top 0.6.0 (agree)``, so
      no session could say which keel governed it. ``components`` is the
      answer: a digest over the CONTENTS of the files the feature registry
      names (``keel_features.component_fingerprint``), reported beside the
      version. Two trees claiming one version now print two digests.
    * ``edition`` was ``plugin.json``'s ``name``, mapped through
      ``EDITION_LABELS``. It still is - the manifest's own claim keeps its own
      key - and ``edition_derived`` now carries what the components on disk
      actually make (``keel_features.derived_edition``), so the two can be
      shown disagreeing instead of the manifest winning by default.
    """
    manifest, manifest_error = _read_json(_REPO_ROOT / ".claude-plugin" / "plugin.json")
    pins, pins_error = _read_json(_REPO_ROOT / ".claude-plugin" / "keel-pins.json")
    changelog_top = ""
    changelog = _REPO_ROOT / "CHANGELOG.md"
    if changelog.is_file():
        entries = re.findall(
            r"^##\s+(\d+\.\d+\.\d+)\b",
            changelog.read_text(encoding="utf-8", errors="replace"),
            re.MULTILINE,
        )
        changelog_top = entries[0] if entries else ""
    version = (manifest or {}).get("version", "")
    fingerprint = component_fingerprint(_REPO_ROOT)
    derived = derived_edition(_REPO_ROOT)
    report: dict[str, Any] = {
        "plugin": version,
        "edition": edition_label((manifest or {}).get("name", "")),
        "manifest_name": (manifest or {}).get("name", ""),
        "changelog_top": changelog_top,
        "built_against": (pins or {}).get("builtAgainst", {}),
        "agrees": bool(version) and version == changelog_top,
        "components": fingerprint.summary(),
        "components_digest": fingerprint.digest,
        "components_files": fingerprint.files,
        "components_missing": list(fingerprint.missing),
        "components_unreadable": list(fingerprint.unreadable),
        "components_note": fingerprint.note,
        "edition_derived": derived.layer,
        "edition_derived_note": derived.note,
        "edition_found": derived.found_summary(),
        # Empty unless something could not be READ. A caller must not read an
        # empty ``edition_derived`` as "unrecognized mix" without asking this
        # too: one of those verdicts is about the tree and the other is about
        # the machine (``keel_features.DerivedEdition.decidable``).
        "edition_unreadable": list(derived.unreadable),
        "notes": [note for note in (manifest_error, pins_error) if note],
    }
    return report


#: The harness's own record of what it installed, under the user's home. Shape
#: (harness version 2): a top-level object with a ``plugins`` table whose keys
#: are ``<plugin name>@<marketplace>`` and whose values are lists of install
#: records carrying ``installPath`` and ``version``. Read defensively: this is
#: another program's file, and its shape is its own business, not keel's.
INSTALL_RECORD_RELPATH: tuple[str, ...] = (
    ".claude",
    "plugins",
    "installed_plugins.json",
)

#: Markers the harness leaves in a cached plugin tree. ``.orphaned_at`` says
#: the harness has written this tree off; ``.in_use`` says something loaded it.
#: A tree carrying BOTH is the state measured on 2026-08-18 - keel running out
#: of a directory its own harness had already orphaned, with nothing anywhere
#: saying so.
ORPHAN_MARKER = ".orphaned_at"
IN_USE_MARKER = ".in_use"

#: How many missing/unreadable component paths, and how many install entries,
#: reach the report before it says "and N more". A report is read; a dump is
#: not.
LIST_HEAD = 5


def install_record_path(home: Path | None = None) -> Path:
    """Where the harness's install record lives for this user."""
    base = Path.home() if home is None else Path(home)
    return base.joinpath(*INSTALL_RECORD_RELPATH)


def _same_tree(left: Any, right: Any) -> bool:
    """True when two paths name one directory, spelling and case aside."""
    try:
        return os.path.normcase(os.path.realpath(str(left))) == os.path.normcase(
            os.path.realpath(str(right))
        )
    except (OSError, ValueError):
        return False


def _marker_timestamp(path: Path) -> str:
    """What ``.orphaned_at`` says, in words a reader can act on.

    The harness writes epoch milliseconds; that is rendered as UTC alongside
    the raw value. Anything else is reported verbatim and bounded, and a marker
    with no readable content falls back to its own mtime, LABELLED as the
    fallback - a finding that cannot name the timestamp still has to name the
    orphaning (convention 7).
    """
    raw = ""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError as exc:
        raw = ""
        fallback = f"unreadable marker: {type(exc).__name__}: {exc}"
    else:
        fallback = "no timestamp in the marker"
    if raw.isdigit():
        try:
            moment = datetime.datetime.fromtimestamp(
                int(raw) / 1000.0, datetime.timezone.utc
            )
            return f"{moment.isoformat().replace('+00:00', 'Z')} (raw {raw})"
        except (OverflowError, OSError, ValueError):
            return f"raw {raw} (not a readable epoch)"
    if raw:
        return raw[:60]
    try:
        moment = datetime.datetime.fromtimestamp(
            path.stat().st_mtime, datetime.timezone.utc
        )
        return f"{fallback}; marker file mtime {moment.isoformat().replace('+00:00', 'Z')}"
    except OSError:
        return fallback


def _install_entries(document: Any, name: str, root: Path) -> list[dict[str, Any]]:
    """Every install record that could be THIS installation, with its state.

    Candidacy is decided two ways, either of which is enough: the record's
    ``installPath`` names this very tree (identity, whatever it is keyed
    under), or the entry's key is keyed to the name this installation's OWN
    manifest carries (``<name>@<marketplace>``). The second reads the local
    manifest rather than matching a hardcoded product name, so a fork keeps
    working and no name is spelled in this file (convention 3).
    """
    plugins = document.get("plugins") if isinstance(document, dict) else None
    if not isinstance(plugins, dict):
        return []
    found: list[dict[str, Any]] = []
    for key, records in plugins.items():
        if isinstance(records, dict):
            records = [records]
        if not isinstance(records, list):
            continue
        keyed_to_us = bool(name) and str(key).split("@", 1)[0] == name
        for record in records:
            if not isinstance(record, dict):
                continue
            install_path = record.get("installPath")
            install_path = install_path if isinstance(install_path, str) else ""
            is_this_tree = bool(install_path) and _same_tree(install_path, root)
            if not (keyed_to_us or is_this_tree):
                continue
            exists = False
            if install_path:
                try:
                    exists = Path(install_path).is_dir()
                except OSError:
                    exists = False
            version = record.get("version")
            found.append(
                {
                    "key": str(key),
                    "install_path": install_path,
                    "version": version if isinstance(version, str) else "",
                    "exists": exists,
                    "is_this_tree": is_this_tree,
                }
            )
    return found


def install_report(
    home: Path | None = None,
    root: Path | None = None,
    manifest_name: str = "",
    version: str = "",
    fingerprint: ComponentFingerprint | None = None,
) -> dict[str, Any]:
    """Where the harness says this installation is, against where it IS.

    keel used to survey the tree it happened to be running from and never ask
    the harness which tree it had installed. Measured 2026-08-18: the record
    named an ``installPath`` that DID NOT EXIST (the marketplace had renamed
    itself, so the recorded directory was gone), while the tree actually
    running carried both ``.orphaned_at`` and ``.in_use`` - a session governed
    by a plugin its own harness had written off, with every surface silent
    about it.

    Three answers, and the first two are FINDINGS:

    1. a recorded ``installPath`` that is not on disk;
    2. the running tree carrying ``.orphaned_at``, named with its timestamp;
    3. record and reality agreeing - one quiet line.

    A fourth follows for free once both trees are in hand: a recorded tree that
    EXISTS, is not this one, and claims the same ``version`` gets its component
    fingerprint compared with this tree's, because two trees claiming one
    version is the defect the fingerprint exists to expose.

    FAIL-SOFT on every path, and never silent: no record, an unreadable
    record, a record whose shape is not the one keel expects, no entry naming
    this installation - each is one stated line. This code runs on adopters'
    machines where none of these files need exist, so absence is a fact to
    report rather than an error to raise, and nothing here can raise: the
    ``state`` field always carries one of the documented values.
    """
    root = _REPO_ROOT if root is None else Path(root)
    record_path = install_record_path(home)
    report: dict[str, Any] = {
        "path": redact(str(record_path)),
        "root": redact(str(root)),
        "state": "",
        "line": "",
        "entries": [],
        "findings": [],
        "notes": [],
        "orphaned_at": "",
        "in_use": False,
    }

    # The running tree's own markers are read whatever the record says: a tree
    # the harness orphaned is a finding even where no record mentions it.
    try:
        orphan = root / ORPHAN_MARKER
        if orphan.is_file():
            report["orphaned_at"] = _marker_timestamp(orphan)
        report["in_use"] = (root / IN_USE_MARKER).exists()
    except OSError as exc:
        report["notes"].append(
            f"could not read the install markers in {redact(str(root))}: "
            f"{type(exc).__name__}: {exc}"
        )
    if report["orphaned_at"]:
        also = " and .in_use, so the orphaned tree is the one loaded" if report["in_use"] else ""
        report["findings"].append(
            f"the tree this survey runs from carries {ORPHAN_MARKER} "
            f"({report['orphaned_at']}){also}: the harness has written this "
            f"installation off, and a session governed by an orphaned tree "
            f"will not receive an update to it - reinstall the plugin, or run "
            f"keel from the tree the record names"
        )

    document, error = _read_json(record_path)
    if error:
        report["state"] = "unreadable"
        report["line"] = f"record unreadable - {error}"
        return report
    if document is None:
        report["state"] = "not-found"
        report["line"] = (
            f"record not found at {report['path']} - nothing to check "
            f"(this tree was not installed by a harness that keeps one, which "
            f"is the normal state of a checkout)"
        )
        return report
    if not isinstance(document, dict) or not isinstance(document.get("plugins"), dict):
        report["state"] = "malformed"
        report["line"] = (
            f"record {report['path']} carries no 'plugins' table - the "
            f"harness's record is in a shape keel does not recognise, so this "
            f"installation could not be located in it"
        )
        return report

    entries = _install_entries(document, manifest_name, root)
    report["entries"] = [
        {
            "key": entry["key"],
            "install_path": redact(entry["install_path"]),
            "version": entry["version"],
            "exists": entry["exists"],
            "is_this_tree": entry["is_this_tree"],
        }
        for entry in entries
    ]
    if not entries:
        report["state"] = "no-entry"
        subject = f"'{manifest_name}'" if manifest_name else "this installation"
        report["line"] = (
            f"record {report['path']} names no installation matching "
            f"{subject} among {len(document['plugins'])} recorded plugin(s) - "
            f"this tree is a checkout the harness never installed, or it was "
            f"installed under another name"
        )
        return report

    mine = [entry for entry in entries if entry["is_this_tree"]]
    missing = [entry for entry in entries if not entry["exists"]]
    for entry in missing[:LIST_HEAD]:
        report["findings"].append(
            f"the install record names {entry['key']} "
            f"v{entry['version'] or '(no version)'} at "
            f"{redact(entry['install_path']) or '(no installPath)'}, which DOES "
            f"NOT EXIST on disk: the harness's record points at a tree that is "
            f"not there, so nothing loads what that record describes"
        )
    if len(missing) > LIST_HEAD:
        report["findings"].append(
            f"and {len(missing) - LIST_HEAD} further recorded installPath(s) "
            f"that do not exist"
        )

    # Two trees, one version: the comparison the fingerprint exists for.
    here = component_fingerprint(root) if fingerprint is None else fingerprint
    for entry in entries:
        if entry["is_this_tree"] or not entry["exists"]:
            continue
        theirs = component_fingerprint(Path(entry["install_path"]))
        same_version = bool(version) and entry["version"] == version
        if not (here.known and theirs.known):
            report["notes"].append(
                f"the recorded tree at {redact(entry['install_path'])} could not "
                f"be fingerprinted ({theirs.note or 'no reason given'}), so it "
                f"cannot be compared with this one"
            )
            continue
        if same_version and theirs.digest != here.digest:
            report["findings"].append(
                f"two trees claim version {version}: this one fingerprints "
                f"{here.summary()} and the recorded tree at "
                f"{redact(entry['install_path'])} fingerprints "
                f"{theirs.summary()} - one version, two different sets of "
                f"components, and the version string alone cannot tell a "
                f"session which of them governs it"
            )
        elif theirs.digest == here.digest:
            report["notes"].append(
                f"the recorded tree at {redact(entry['install_path'])} carries "
                f"the same components as this one ({here.digest})"
            )
        else:
            report["notes"].append(
                f"the recorded tree at {redact(entry['install_path'])} is a "
                f"different version ({entry['version'] or '(none)'}) with a "
                f"different fingerprint ({theirs.summary()})"
            )

    if mine:
        entry = mine[0]
        agrees = entry["exists"] and not report["findings"]
        report["state"] = "agree" if agrees else "disagree"
        report["line"] = (
            f"record names {entry['key']} v{entry['version'] or '(no version)'} "
            f"at {redact(entry['install_path'])}"
            + (" - record and reality agree" if agrees else "")
        )
        return report

    report["state"] = "unrecorded-root"
    named = ", ".join(
        f"{entry['key']} v{entry['version'] or '(no version)'} at "
        f"{redact(entry['install_path'])}"
        for entry in entries[:LIST_HEAD]
    )
    report["line"] = f"record names {named}"
    report["notes"].append(
        f"this survey runs from {report['root']}, which the record does not "
        f"name: the tree being surveyed is not the tree the harness installed"
    )
    return report


def arming_report(project: Path) -> dict[str, Any]:
    """Arming state and tier of the surveyed project (R25)."""
    try:
        tier = policy_tier(project)
        note = ""
    except GateError as exc:
        tier, note = None, f"arming file present but unreadable: {exc}"
    return {
        "tier": tier,
        "armed": tier is not None and tier >= ENFORCING_TIER,
        "adopted": (project / ".keel").is_dir(),
        "note": note,
    }


def switches_report(env: dict[str, str] | None = None) -> dict[str, str]:
    """The kill switches, as values rather than as a verdict about them."""
    env = dict(os.environ) if env is None else env
    return {name: env.get(name, "") for name in KILL_SWITCHES}


def lock_config_report(project: Path) -> dict[str, Any]:
    """The '## Policy lock' configuration section and the '## Holds' section,
    or the fact there is none of either.

    Reuses ``keel_gate.policy_lock_section`` - the very parser the gate
    itself consults - so this can never show a deviation the gate would not
    also honour (R15). ``tightened``/``relaxed`` are reported as PARSED even
    when the section is invalid, because a misconfiguration is a deviation
    worth seeing; ``errors`` says why it is not actually in force.

    HOLDS RIDE ON THIS ONE READER rather than on a ``holds_report`` of their
    own, despite the name, and the reason is the drift this function exists to
    prevent. They come from the same file, the same parse and the same
    ``GateError`` path; a second reader would be a second chance to disagree
    about an unreadable arming file - which is exactly the divergence R15
    names. ``holds_state`` is carried as the gate DERIVED it (never recomputed
    by a caller), so the castoff line and the ``holds`` line below cannot
    contradict each other about one file.

    THE WORKSHOP RIDES ON IT TOO, and for the same reason, in three fields
    rather than one: ``workshop`` is the entries IN FORCE (``workshop_prefixes``
    as the gate itself reads them, so an invalid section carries none),
    ``workshop_refusals`` is the entries keel REFUSED and dropped, and
    ``workshop_state`` is which of those facts a reader is looking at. Refused
    is not absent - see THE DECLARATION IS SURFACED in ``keel_gate``. The
    declaration was enforced from T169 and reported by nothing until T176,
    which meant a session could not see which of its own source trees its model
    was permitted to rewrite.
    """
    try:
        section = policy_lock_section(project)
    except GateError as exc:
        return {
            "present": False,
            "valid": False,
            "tightened": (),
            "relaxed": (),
            "errors": (),
            # An arming file keel cannot read holds an UNKNOWN number of
            # holds, never zero. Reporting "absent" here would be the T168
            # fault at its most expensive: a standing constraint erased by the
            # very failure that should have raised the alarm.
            "holds_state": HOLDS_UNREADABLE,
            "holds": (),
            "hold_errors": (f"arming file unreadable: {exc}",),
            # An arming file keel cannot read declares an UNKNOWN workshop.
            # NOTHING is in force - the gate that could not parse this file
            # honours no prefix out of it either - but "none declared" is a
            # claim about the owner's intent that keel is not entitled to make
            # here, which is the T168 rule in the one direction that matters
            # for a loosening: say what is enforced, never guess what was asked.
            "workshop_state": WORKSHOP_UNKNOWN,
            "workshop": (),
            "workshop_refusals": (),
            "note": f"arming file unreadable: {exc}",
        }
    return {
        "present": section.present,
        "valid": section.valid,
        "tightened": section.lock,
        "relaxed": section.relax,
        "errors": section.errors,
        "holds_state": holds_state(section),
        "holds": section.holds,
        "hold_errors": section.hold_errors,
        "workshop_state": workshop_state(section),
        # IN FORCE, not as parsed: ``workshop_prefixes`` is the very property
        # ``workshop_prefix_for`` consults, so this field cannot name a prefix
        # the gate would not honour (R15). What was declared and dropped is
        # ``workshop_refusals``, reported in full beside it.
        "workshop": section.workshop_prefixes,
        "workshop_refusals": section.workshop_refusals,
        "note": "",
    }


def override_report(armed: bool = False, env: dict[str, str] | None = None) -> str:
    """The one polite nag naming how to restore the lock, or nothing.

    Reported whenever ``KEEL_OVERRIDE`` is ON, armed or not. The arming state
    used to gate this sentence, on the reasoning that an unarmed project has
    no lock for the switch to suspend; measurement retired that reasoning. A
    survey is read at ARMING TIME - ``/keel:lay`` runs it on a project that is
    unarmed by definition - so the one state the old condition hid is exactly
    the one that matters: a kill switch already set on a tree about to be
    armed one minute later. Silence there is a survey that watched the switch
    go past and said nothing (convention 7).

    ``armed`` is still accepted, and is deliberately no longer part of the
    decision: every existing caller passes it, and the survey payload's
    ``override`` key keeps its shape. This function is the one place the
    question is answered for the SURVEY; the reminders in
    ``hooks/keel_session.py`` and ``hooks/keel_stop.py`` answer a different
    question - whether to nag INSIDE a session whose lock is live - and keep
    their own arming test unchanged.

    The sentence itself is ``keel_gate.OVERRIDE_REMINDER`` verbatim, so every
    surface that nags about the override says exactly the same thing (the
    override-nag decision).
    """
    env = dict(os.environ) if env is None else env
    return OVERRIDE_REMINDER if env_on("KEEL_OVERRIDE", env) else ""


def budget_report(project: Path) -> dict[str, Any]:
    """R9 re-measured where the survey runs, never quoted from a document."""
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            tokens, violations = keel_checks.check_budget(project)
    except (OSError, ValueError) as exc:
        return {"tokens": None, "limit": keel_checks.BUDGET_TOKEN_LIMIT,
                "violations": [f"budget could not be measured: {exc}"], "detail": ""}
    return {
        "tokens": tokens,
        "limit": keel_checks.BUDGET_TOKEN_LIMIT,
        "violations": violations,
        "detail": buffer.getvalue().strip(),
    }


#: Denials at least this recent count as recent enforcement friction.
FRICTION_WINDOW_DAYS = 7

#: How many bypass path segments the composition line names before it says how
#: much is left over. Three is enough to see the shape; the remainder is
#: printed as a count rather than dropped, because a truncated total that does
#: not say it was truncated is the same defect as a silent zero (convention 7).
BYPASS_SEGMENTS_SHOWN = 3

#: What a bypass whose target names no path is called in the composition. A
#: blocked COMMAND is recorded as the opaque ``<command>`` by
#: ``keel_gate.blocked_command_detail``, and a line with no target at all has
#: to be counted somewhere visible rather than dropped out of the total.
NO_SEGMENT = "(no target)"


def bypass_segment(detail: Any) -> str:
    """The top path segment one ``gate_bypass`` line was about.

    The gate writes ``detail`` as ``{"target": ..., "switch": ...}``, where the
    target is a project-relative path (``hooks/keel_gate.py``) or the opaque
    ``<command>`` a blocked shell command is reduced to. The segment is the
    first path element with its separator kept (``hooks/``), so the composition
    reads as directories rather than as file names; a target that is not a path
    is its own segment, and anything unreadable becomes :data:`NO_SEGMENT`. A
    string ``detail`` is accepted as the target itself, so a line written by an
    older or a differently-shaped writer is still counted rather than silently
    dropped.
    """
    target: Any = None
    if isinstance(detail, dict):
        target = detail.get("target")
    elif isinstance(detail, str):
        target = detail
    if not isinstance(target, str) or not target.strip():
        return NO_SEGMENT
    text = target.strip().replace(chr(92), "/")
    head, separator, _rest = text.partition("/")
    if separator and head:
        return f"{head}/"
    return text[:60]


def friction_report(project: Path) -> dict[str, Any]:
    """Policy-lock denials AND bypasses from the audit log: the lock's burden
    and its one sanctioned hole, both measured.

    Counts every ``gate_block`` audit line whose gate is ``policy_lock`` -
    the total on record and how many fall inside the last
    ``FRICTION_WINDOW_DAYS`` days (by each line's ``ts``) - and, separately,
    every ``gate_bypass`` line the same way. A bypass is not a denial: it is
    a policy-lock refusal the user's own KEEL_OVERRIDE suspended, so it is
    reported under its own label rather than folded into the denial count.
    The log is read with the JSONL guarantee: a malformed line is skipped and
    costs exactly that line, never the report. An absent log is zero of
    both, which is a fact rather than a failure - and zero is still printed,
    because a lock whose burden is unmeasured gets debated instead of
    measured.

    Two things the count alone could not say (T168), because a bare number
    reads as a scandal without its composition:

    * ``bypasses_outrun_denials`` - whether the sanctioned hole is doing more
      work than the lock inside the window. Measured 2026-08-18 on keel's own
      project: 365 bypasses against 4 denials ever. Under the WARN band the
      render puts on that state, a reader is told the ratio rather than left to
      compute it from two lines printed neutrally side by side.
    * ``bypass_segments`` - WHAT was bypassed, by top path segment
      (:func:`bypass_segment`), most first. 308 of those 365 were writes into
      ``hooks/`` - keel's own source, under self-hosting - which is the whole
      difference between a broken lock and a project that develops the gate it
      is governed by. The composition is over every bypass on record, the same
      population as ``lock_bypasses_total``, so the numbers add up to a figure
      the reader can see.
    """
    now_ms = time.time() * 1000.0
    window_ms = FRICTION_WINDOW_DAYS * 24.0 * 60.0 * 60.0 * 1000.0
    total = 0
    recent = 0
    bypass_total = 0
    bypass_recent = 0
    segments: dict[str, int] = {}
    for entry in read_audit(project):
        event = entry.get("event")
        ts_ms = parse_ts_ms(entry.get("ts"))
        is_recent = ts_ms is not None and (now_ms - ts_ms) <= window_ms
        if event == "gate_block" and entry.get("gate") == "policy_lock":
            total += 1
            if is_recent:
                recent += 1
        elif event == "gate_bypass":
            bypass_total += 1
            if is_recent:
                bypass_recent += 1
            segment = bypass_segment(entry.get("detail"))
            segments[segment] = segments.get(segment, 0) + 1
    ranked = sorted(segments.items(), key=lambda pair: (-pair[1], pair[0]))
    return {
        "lock_denials_total": total,
        "lock_denials_recent": recent,
        "lock_bypasses_total": bypass_total,
        "lock_bypasses_recent": bypass_recent,
        "bypasses_outrun_denials": bypass_recent > recent,
        "bypass_segments": [{"segment": name, "count": n} for name, n in ranked],
        "window_days": FRICTION_WINDOW_DAYS,
    }


def bypass_composition_line(friction: dict[str, Any]) -> str:
    """The one sentence naming WHAT the bypasses were, or why there is none.

    Composed here rather than inside :func:`render` so the words can be tested
    directly and so any other surface that reports friction says the same
    thing. The head of the ranking is named and the tail is COUNTED - never
    dropped - and a population with nothing in it says so instead of printing
    an empty list.
    """
    ranked = friction.get("bypass_segments") or []
    total = friction.get("lock_bypasses_total", 0)
    if not ranked:
        return "composition: nothing bypassed on record"
    head = ranked[:BYPASS_SEGMENTS_SHOWN]
    named = ", ".join(f"{item['segment']} {item['count']}" for item in head)
    shown = sum(item["count"] for item in head)
    tail = ""
    if len(ranked) > len(head):
        tail = (
            f"; {total - shown} more across {len(ranked) - len(head)} other "
            f"segment(s)"
        )
    return f"composition of all {total} bypass(es) by target: {named}{tail}"


def registrations_in(document: Any, scope: str, source: Path) -> list[Registration]:
    """Every PreToolUse/Stop registration in one settings or hooks document."""
    found: list[Registration] = []
    hooks = (document or {}).get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return found
    for event in SCANNED_EVENTS:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            matcher = group.get("matcher") if isinstance(group.get("matcher"), str) else ""
            entries = group.get("hooks")
            entries = entries if isinstance(entries, list) else []
            for entry in entries:
                command = entry.get("command") if isinstance(entry, dict) else None
                found.append(
                    Registration(
                        scope=scope,
                        source=str(source),
                        event=event,
                        matcher=matcher,
                        command=command if isinstance(command, str) else NO_COMMAND,
                    )
                )
    return found


def plugin_manifests(home: Path) -> list[Path]:
    """Installed-plugin hook manifests, depth-bounded (never a full crawl)."""
    base = home / ".claude" / "plugins"
    found: list[Path] = []
    if not base.is_dir():
        return found
    for pattern in _PLUGIN_GLOBS:
        try:
            found.extend(sorted(base.glob(pattern)))
        except OSError:
            continue
    return found


def scan_registrations(project: Path, home: Path | None = None) -> tuple[list[Registration], list[str]]:
    """Every registration keel can see, plus a note per source it could not read."""
    home = Path.home() if home is None else home
    sources: list[tuple[str, Path]] = [
        ("global", home / ".claude" / "settings.json"),
        ("project", project / ".claude" / "settings.json"),
        ("project", project / ".claude" / "settings.local.json"),
        ("plugin", _REPO_ROOT / "hooks" / "hooks.json"),
    ]
    sources.extend(("plugin", manifest) for manifest in plugin_manifests(home))
    registrations: list[Registration] = []
    notes: list[str] = []
    seen: set[str] = set()
    for scope, path in sources:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        document, error = _read_json(path)
        if error:
            notes.append(error)
            continue
        registrations.extend(registrations_in(document, scope, path))
    return registrations, notes


def foreign_policy_path(project: Path) -> Path:
    """Where another harness's arming file would be in the surveyed project."""
    return Path(project).joinpath(*FOREIGN_POLICY_RELPATH)


def _slashed(text: str) -> str:
    """One comparable spelling of a command: forward slashes, case-folded.

    Registrations are written by hand on three operating systems, so the same
    script appears as ``hooks/keel_hook.py`` and as ``hooks\\keel_hook.py``
    within one machine's settings. Both separators are folded to ``/`` here so
    ownership is decided on the path, not on the platform that typed it. The
    backslash is spelled ``chr(92)`` on purpose: this string has a habit of
    being eaten by whatever shell or heredoc a pattern travels through, and a
    separator that quietly vanishes turns this whole check into "no Windows
    registration is ever ours".
    """
    return text.replace(chr(92), "/").casefold()


def mentions_path(haystack: str, needle: str) -> bool:
    """True when ``needle`` occurs in ``haystack`` as a WHOLE path fragment.

    Both arguments are expected already ``_slashed``. EVERY substring test in
    the ownership decision goes through here, and that is the point: an
    unbounded ``in`` fails toward the hole. It answers "this is keel's own"
    for a rival command that merely shares a prefix with something of keel's,
    and a command wrongly called ours vanishes from the conflict report
    altogether - the exact silence R30's refusal exists to prevent.

    A match is bounded when neither side is glued to a longer path segment,
    which is decided by ``SEGMENT_CHARS`` rather than by position, so the
    same rule covers a directory and a file name:

    * ``hooks-legacy/rival.py`` and ``hooksold/x.py`` do NOT satisfy
      ``.../hooks/`` - the character after the match continues the segment;
    * ``badhooks/keel_hook.py`` does NOT satisfy ``hooks/keel_hook.py`` - the
      character before it continues the segment;
    * ``hooks/keel_hook.pyc`` and ``hooks/keel_hook.py.bak`` do NOT satisfy
      ``hooks/keel_hook.py`` - a different file is a different file;
    * ``/anywhere/hooks/keel_hook.py`` DOES, on either separator. That is the
      documented tolerance, not a leak: a second copy of this installation is
      still this stack, and two copies of one stack are not two stacks.

    Every occurrence is examined, not only the first, because a command may
    name several paths and the bounded one may not come first.
    """
    if not needle:
        return False
    start = 0
    while True:
        index = haystack.find(needle, start)
        if index < 0:
            return False
        before = haystack[index - 1] if index else ""
        end = index + len(needle)
        after = haystack[end] if end < len(haystack) else ""
        if before not in SEGMENT_CHARS and after not in SEGMENT_CHARS:
            return True
        start = index + 1


def own_hook_scripts(root: Path | None = None) -> tuple[str, ...]:
    """Every hook script THIS installation ships, as ``hooks/<name>``.

    Read from disk rather than declared, so the answer to "is this command
    ours" is derived from the installation itself: a bundle that ships fewer
    hooks claims fewer commands, and a hook added tomorrow is claimed without
    editing this list. Nothing here matches on a product NAME - a foreign
    command that merely mentions keel is still foreign, and a renamed fork's
    own hooks are still its own.

    Unreadable directory: an empty tuple, which makes ``command_is_own``
    answer False and every stopping registration read as foreign. That is the
    fail-closed direction for a REPORT whose refusal protects the user from
    two armed stacks; the cost of the pessimistic answer is a conflict the
    reader can see and dismiss, never a silence.
    """
    base = (_REPO_ROOT if root is None else Path(root)) / "hooks"
    try:
        names = sorted(entry.name for entry in base.glob("*.py"))
    except OSError:
        return ()
    return tuple(_slashed(f"hooks/{name}") for name in names)


def command_is_own(command: str, root: Path | None = None) -> bool:
    """True when this registration's command runs THIS installation's hooks.

    Two structural signals, either of which is enough: the command references
    this installation's own ``hooks/`` directory by path (the shape a settings
    file that hardcodes a checkout takes), or it references one of the hook
    scripts that installation ships as ``hooks/<name>`` (the shape the plugin
    manifest takes, where the root arrives as an environment variable the
    survey must not and does not expand).

    NEITHER signal is a bare substring test. Both go through
    ``mentions_path``, and the directory one asks for the trailing separator
    as part of the needle, so a SIBLING directory that merely starts with the
    same characters - ``.../hooks-legacy/rival.py``, ``.../hooksold/x.py`` -
    is foreign, which is what it is. An unbounded match here would fail
    toward the hole: a rival command classified as ours is not a noisy
    conflict, it is a conflict that never appears at all.

    A blank command, or the ``NO_COMMAND`` sentinel a malformed entry leaves
    behind, is NOT ours - and not treated as foreign either; see
    ``conflict_scan``, which reports it as a scan note.
    """
    if not isinstance(command, str) or not command.strip():
        return False
    haystack = _slashed(command)
    own_dir = _slashed(str((_REPO_ROOT if root is None else Path(root)) / "hooks"))
    if own_dir and mentions_path(haystack, f"{own_dir}/"):
        return True
    return any(mentions_path(haystack, script) for script in own_hook_scripts(root))


def matcher_gates_writes(matcher: str) -> bool:
    """True when a PreToolUse matcher selects at least one write tool.

    An absent, blank or wildcard matcher selects every tool, which includes
    every write tool. Anything else must NAME a write tool to qualify: this is
    what keeps refusal narrow (R30) - a registration matching ``Task|Agent``
    observes delegations and cannot stop a write, so it is reported and never
    refused.
    """
    if not isinstance(matcher, str):
        return False
    text = matcher.strip()
    if not text or text in ANY_TOOL_MATCHERS:
        return True
    folded = text.casefold()
    return any(name.casefold() in folded for name in WRITE_TOOL_NAMES)


def registration_can_stop_work(registration: Registration) -> bool:
    """True when this registration is one of the two that can stop work.

    Every ``Stop`` registration can (that event exists to hold a session at
    the end of a turn); a ``PreToolUse`` one only where its matcher reaches a
    write tool.
    """
    if registration.event == "Stop":
        return True
    return registration.event == "PreToolUse" and matcher_gates_writes(registration.matcher)


def _registration_conflict(registration: Registration) -> dict[str, str]:
    """One ``armed-overlap`` conflict, naming the scope it was found in."""
    scope = registration.scope
    label = SCOPE_LABELS.get(scope, scope)
    blast = SCOPE_MIGRATIONS.get(
        scope, "check which scope that file belongs to before editing it"
    )
    where = redact(registration.source)
    head = redact(registration.command.replace("\n", " ")[:COMMAND_HEAD_CHARS])
    target = registration.matcher or "(any tool)"
    return {
        "kind": "armed-overlap",
        "scope": scope,
        "source": where,
        "event": registration.event,
        "detail": (
            f"another gate stack holds an event that can stop work over this "
            f"project: {registration.event} {target} -> {head}, registered in "
            f"{label} ({where}). Two armed gate stacks must never run over one "
            f"project (R30)."
        ),
        "migration": (
            f"leave keel at tier 0 or 1 (observe/log only, nothing blocks), OR "
            f"remove that {registration.event} entry from {label}: {where} - "
            f"THAT file, and no other: {blast}. Then raise keel's tier with "
            f"/keel:refit. keel edits none of these files on its own."
        ),
    }


def conflict_scan(
    project: Path,
    home: Path | None = None,
    registrations: list[Registration] | None = None,
    notes: list[str] | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """The narrow refusal set, plus every reason the scan may be INCOMPLETE.

    Returns ``(conflicts, notes)``. The notes are the honest edge of the
    answer: a settings file that could not be parsed, or a registration whose
    command keel could not read, means the conflict list is a floor rather
    than a total - and a caller that renders "0" without saying so is exactly
    the swallowed-error shape ``a-swallowed-error-renders-as-a-fact`` records.

    ``registrations``/``notes`` let a caller that has already scanned (the
    ``survey`` payload does) pay for one scan instead of two; passing neither
    scans here.
    """
    if registrations is None or notes is None:
        registrations, notes = scan_registrations(project, home)
    conflicts: list[dict[str, str]] = []
    scan_notes = list(notes)

    foreign = foreign_policy_path(project)
    try:
        present = foreign.is_file()
    except OSError as exc:
        present = False
        scan_notes.append(
            f"unreadable {redact(str(foreign))}: {type(exc).__name__}: {exc}"
        )
    if present:
        conflicts.append(
            {
                "kind": "armed-overlap",
                "scope": "project",
                "source": redact(str(foreign)),
                "event": "arming file",
                "detail": (
                    f"another gate stack is ARMED over this project: "
                    f"{'/'.join(FOREIGN_POLICY_RELPATH)}, found in "
                    f"{SCOPE_LABELS['project']} scope ({redact(str(foreign))}). "
                    "Two armed gate stacks must never run over one project (R30)."
                ),
                "migration": (
                    "leave keel at tier 0 or 1 (observe/log only, nothing "
                    "blocks), OR retire the other gate stack - remove that "
                    "file, and remove its PreToolUse/Stop entries from the file "
                    "each conflict below NAMES, which may be a user/global "
                    "settings file rather than this project's own - and then "
                    "raise keel's tier with /keel:refit. keel edits none of "
                    "these files on its own."
                ),
            }
        )

    for registration in registrations:
        if not registration_can_stop_work(registration):
            continue
        if registration.command.strip() in ("", NO_COMMAND):
            scan_notes.append(
                f"{registration.event} entry in {redact(registration.source)} "
                f"carries no readable command: ownership could not be decided, "
                f"so this scan is a floor rather than a total"
            )
            continue
        if command_is_own(registration.command):
            continue
        conflicts.append(_registration_conflict(registration))
    return conflicts, scan_notes


def conflicts_for(
    project: Path,
    home: Path | None = None,
    registrations: list[Registration] | None = None,
    notes: list[str] | None = None,
) -> list[dict[str, str]]:
    """The narrow refusal set: another gate stack ARMED over this project.

    Kept as the one name every caller already uses (``survey`` here,
    ``_conflict_orientation`` in ``hooks/keel_session.py``); the derivation
    lives in ``conflict_scan``, whose second return value says whether this
    list is a total or a floor. A caller that renders a COUNT must ask for
    those notes too - ``conflict_scan_notes`` is that question - because a
    partial scan reporting a bare zero is the defect this task exists to fix.
    """
    return conflict_scan(project, home, registrations, notes)[0]


def conflict_scan_notes(
    project: Path,
    home: Path | None = None,
    registrations: list[Registration] | None = None,
    notes: list[str] | None = None,
) -> list[str]:
    """Every reason the conflict scan above could be INCOMPLETE, or nothing.

    Empty means the scan read every source it looks at, so its count is a
    total. Non-empty means the count is a floor and the reader must be told
    so in the same breath as the number (convention 7).
    """
    return conflict_scan(project, home, registrations, notes)[1]


def survey(project: Path, home: Path | None = None) -> dict[str, Any]:
    """The whole report as a plain dictionary; also the ``--json`` payload."""
    registrations, notes = scan_registrations(project, home)
    # One scan, two readers: the REGISTRATIONS section below and the conflict
    # derivation, which is the same evidence read for refusal (R30). The
    # scan's own notes travel with the conflicts, so a source that could not
    # be read is stated beside the count it makes a floor rather than a total.
    conflicts, scan_notes = conflict_scan(project, home, registrations, notes)
    arming = arming_report(project)
    version = version_report()
    return {
        "project": redact(str(Path(project).resolve())),
        "version": version,
        # T168: where the harness says this installation is, against where it
        # actually is. Handed the version half's own manifest name and version
        # string, so "two trees claim one version" is decided against exactly
        # the value the version line above printed.
        "install": install_report(
            home=home,
            root=_REPO_ROOT,
            manifest_name=version.get("manifest_name", ""),
            version=version.get("plugin", ""),
        ),
        "arming": arming,
        "lock_config": lock_config_report(project),
        "override": override_report(arming["armed"]),
        "switches": switches_report(),
        "budget": budget_report(project),
        "friction": friction_report(project),
        "registrations": [
            {
                "scope": r.scope,
                "source": redact(r.source),
                "event": r.event,
                "matcher": r.matcher,
                "command": redact(r.command[:COMMAND_HEAD_CHARS]),
            }
            for r in registrations
        ],
        "registration_lines": [r.line() for r in registrations],
        "conflicts": conflicts,
        "notes": scan_notes,
    }


def startup_line(report: dict[str, Any]) -> str:
    """The <=1 line form: what a session start can afford to be told.

    The install fragment (T168) appears ONLY where the install report raised a
    finding - a recorded ``installPath`` that is not on disk, a loaded tree
    the harness has orphaned, two trees claiming one version. Those are the
    states where the session about to start is governed by a tree nobody can
    name, and a clean one-liner over them is the silence this task exists to
    remove. The quiet states stay quiet: record and reality agreeing, and a
    machine with no install record at all (an adopter's checkout), add nothing,
    because a line that always says something about the install is a line
    nobody reads.
    """
    arming = report["arming"]
    tier = "unarmed" if arming["tier"] is None else f"tier {arming['tier']}"
    budget = report["budget"]
    tokens = "?" if budget["tokens"] is None else budget["tokens"]
    conflicts = len(report["conflicts"])
    install_findings = len((report.get("install") or {}).get("findings") or [])
    install = (
        f"{install_findings} install FINDING(s), " if install_findings else ""
    )
    # The qualifier belongs to the FIGURE, not to one value of it: a count
    # from a scan that could not read every source is a floor whether it is
    # zero or three, and the one line a session start can afford is still not
    # allowed to round a floor up to a total (convention 7).
    incomplete = bool(report.get("notes"))
    if conflicts:
        tail = f"{conflicts} CONFLICT{' (scan INCOMPLETE - a floor)' if incomplete else ''}"
        tail += " - run: python scripts/keel.py survey"
    elif incomplete:
        tail = "no conflicts found but the scan was INCOMPLETE - run: python scripts/keel.py survey"
    else:
        tail = "no conflicts"
    return (
        f"keel survey: {tier}, {len(report['registrations'])} registration(s), "
        f"{tokens}/{budget['limit']} tokens, {install}{tail}"
    )


def render(report: dict[str, Any]) -> str:
    """The full report. Reporting is total; refusal is narrow (R30)."""
    out: list[str] = []
    write = out.append
    version = report["version"]
    arming = report["arming"]
    budget = report["budget"]

    write("=" * 72)
    write(f"KEEL SURVEY - {report['project']}")
    write("=" * 72)
    agreement = "agree" if version["agrees"] else "DISAGREE"
    write(
        f"version : plugin {version['plugin'] or '(none)'} | changelog top "
        f"{version['changelog_top'] or '(none)'} ({agreement}) | components "
        f"{version['components']} | built against "
        f"{json.dumps(version['built_against'], ensure_ascii=False)}"
    )
    # T168: the version above is two strings agreeing with each other; the
    # components digest is the only part of that line derived from the tree, so
    # what qualifies it prints in the same breath rather than in a footnote.
    # Two labels, two different faults, and they never share a sentence: a
    # MISSING component is a trimmed or damaged installation, an UNREADABLE one
    # is a machine keel was refused, and the reader's next step differs.
    for label, paths, consequence in (
        (
            "MISSING",
            version["components_missing"],
            "this tree is NOT a complete installation",
        ),
        (
            "UNREADABLE",
            version["components_unreadable"],
            "keel could not read part of its own tree, so what is here could "
            "not be established either way",
        ),
    ):
        if paths:
            head = ", ".join(paths[:LIST_HEAD])
            more = f" and {len(paths) - LIST_HEAD} more" if len(paths) > LIST_HEAD else ""
            write(f"          {label} component(s) - {consequence}: {head}{more}")
    if version["components_note"]:
        write(f"          NOTE {version['components_note']}")
    derived = version["edition_derived"]
    manifest_label = version["edition"]
    if version["edition_unreadable"]:
        # Not "unrecognized": an unrecognized mix is a statement about the
        # tree, and this is a statement about what keel was allowed to see.
        write(
            f"edition : CANNOT BE DERIVED - "
            f"{len(version['edition_unreadable'])} component(s) unreadable "
            f"(manifest says: {manifest_label})"
        )
        write(f"          found on disk: {version['edition_found']}")
        write(f"          NOTE {version['edition_derived_note']}")
    elif not derived:
        write(f"edition : unrecognized component mix (manifest says: {manifest_label})")
        write(f"          found on disk: {version['edition_found']}")
        if version["edition_derived_note"]:
            write(f"          NOTE {version['edition_derived_note']}")
    elif derived == manifest_label:
        write(f"edition : {derived} (derived from the components on disk; manifest agrees)")
    else:
        write(
            f"edition : {derived} (derived from the components on disk; manifest "
            f"says: {manifest_label})"
        )
    install = report["install"]
    write(f"install : {install['line']}")
    for finding in install["findings"]:
        write(f"          FINDING {finding}")
    for note in install["notes"]:
        write(f"          NOTE {note}")
    tier = "no arming file" if arming["tier"] is None else f"tier {arming['tier']}"
    state = "ARMED (enforcing)" if arming["armed"] else "not enforcing"
    write(f"arming  : {tier}, {state}; .keel/ present: {arming['adopted']}")
    if arming["note"]:
        write(f"          NOTE {arming['note']}")
    lock = report["lock_config"]
    # THE WORKSHOP SEGMENT (workshop design rule 7), COMPUTED BEFORE THE
    # PRESENCE BRANCH AND PRINTED IN BOTH DIRECTIONS.
    #
    # The position is the fix for a review finding, and the finding is worth
    # keeping in front of whoever edits this next: the segment first sat inside
    # the ``else`` below, which made ``WORKSHOP_UNKNOWN`` STRUCTURALLY
    # UNREACHABLE, because the only thing that produces it -
    # ``lock_config_report``'s ``except GateError`` path - pairs it with
    # ``present`` FALSE. An unreadable arming file therefore printed the exact
    # line a project that declared nothing gets, with the word "workshop"
    # absent altogether and the cause surviving only in a trailing NOTE. That
    # is the NONE/UNKNOWN collapse T168 closed elsewhere, rebuilt one field
    # along inside the very change meant to close it. NESTING A STATE MACHINE
    # INSIDE A CONDITION THAT EXCLUDES ONE OF ITS STATES IS THE DEFECT; the
    # holds line below never had it, because it renders from its state and
    # nothing else. This one now matches it.
    #
    # Rendered from ``workshop_state`` as the gate derived it, never from
    # ``valid`` or ``present`` here: a reader that re-decided the state beside
    # the one that decided it is how two surfaces start disagreeing about one
    # file (R15). An empty declaration is an explicit "(none)", like tighten and
    # relax; a REFUSED entry is never rendered as one, because a declaration
    # keel threw away is not a declaration nobody wrote.
    shop_state = lock["workshop_state"]
    if shop_state == WORKSHOP_ACTIVE:
        workshop = ", ".join(lock["workshop"])
    elif shop_state == WORKSHOP_NONE:
        workshop = "(none)"
    elif shop_state == WORKSHOP_REFUSED:
        workshop = (
            f"(none in force; {len(lock['workshop_refusals'])} declared "
            f"entry(ies) REFUSED, see below)"
        )
    elif shop_state == WORKSHOP_INVALID:
        # Deliberately NOT the declared entries: an invalid section carries
        # no workshop, and printing what it declared would read as a
        # permission the gate is about to refuse.
        workshop = "(none in force - the section is INVALID, so no workshop is honoured)"
    else:
        workshop = "(UNKNOWN - the arming file cannot be read, so none is in force)"
    if not lock["present"]:
        if shop_state == WORKSHOP_UNKNOWN:
            # NOT "defaults": keel never read this file, so "there is no
            # section" is a claim it has not earned, and printing it beside an
            # UNKNOWN workshop would put a false sentence next to a true one.
            # ``present`` is FALSE here for both worlds - no section, and no
            # readable file - which is the same collapse one field further
            # along; the workshop state is what lets this line tell them apart.
            write(
                "lock    : UNKNOWN - the arming file cannot be read, so neither the "
                f"lock nor the workshop can be stated; workshop: {workshop}"
            )
        else:
            # No section is no workshop either: the ``workshop:`` list lives
            # inside this very section, so "(none)" here is a statement rather
            # than a silence - the same reason tighten and relax get one.
            write(
                "lock    : defaults (no '## Policy lock' section in the arming "
                f"file); workshop: {workshop}"
            )
    else:
        lock_state = "in force" if lock["valid"] else "INVALID - full default lock applies"
        tighten = ", ".join(lock["tightened"]) or "(none)"
        relax = ", ".join(lock["relaxed"]) or "(none)"
        write(
            f"lock    : {lock_state}; tighten: {tighten}; relax: {relax}; "
            f"workshop: {workshop}"
        )
        for error in lock["errors"]:
            write(f"          ERROR {error}")
    # Refused entries are printed WHATEVER the state, and OUTSIDE the presence
    # branch for the same reason the segment is: they are facts about what the
    # owner wrote, and until T176 they were visible only on stderr at the moment
    # a gate event happened to fire.
    for refusal in lock["workshop_refusals"]:
        write(f"          REFUSED {refusal}")
    if lock["note"]:
        write(f"          NOTE {lock['note']}")
    # THE HOLDS LINE, always printed. An absent section is a printed sentence
    # saying so, never a missing line: a reader scanning this report for the
    # user's standing constraints must never have to wonder whether the
    # section was empty or the survey forgot to look (T168, convention 7).
    holds = lock["holds_state"]
    if holds == HOLDS_ACTIVE:
        write(f"holds   : {len(lock['holds'])} ACTIVE (read and surfaced; they gate nothing)")
        for hold in lock["holds"]:
            write(f"          HOLD {hold}")
    elif holds == HOLDS_NONE:
        write("holds   : none active (explicitly declared)")
    elif holds == HOLDS_ABSENT:
        write("holds   : no '## Holds' section in the arming file (nothing declared)")
    else:
        write("holds   : UNKNOWN - the section cannot be read, so this is not 'none'")
    for error in lock["hold_errors"]:
        write(f"          ERROR {error}")
    write(
        "switches: "
        + " ".join(
            f"{name}={value or '(unset)'}" for name, value in report["switches"].items()
        )
    )
    tokens = "unmeasured" if budget["tokens"] is None else budget["tokens"]
    write(f"budget  : {tokens} / {budget['limit']} always-loaded tokens (R9)")
    for violation in budget["violations"]:
        write(f"          OVER {violation}")
    friction = report["friction"]
    write(
        f"friction: {friction['lock_denials_total']} policy-lock denial(s) on "
        f"record; {friction['lock_denials_recent']} in the last "
        f"{friction['window_days']} days"
    )
    bypass_line = (
        f"{friction['lock_bypasses_total']} policy-lock bypass(es) via "
        f"KEEL_OVERRIDE on record (a bypass is not a denial); "
        f"{friction['lock_bypasses_recent']} in the last {friction['window_days']} days"
    )
    # T168: the band, in the same register as OVERRIDE ACTIVE below. Bypasses
    # outrunning denials inside the window means the sanctioned hole is doing
    # more work than the lock, which a neutrally-printed pair of counts left
    # the reader to notice for themselves - and nobody did, for 365 of them.
    if friction["bypasses_outrun_denials"]:
        write(
            f"          WARN bypasses OUTRUN denials in the last "
            f"{friction['window_days']} days "
            f"({friction['lock_bypasses_recent']} bypass(es) against "
            f"{friction['lock_denials_recent']} denial(s)): the override is "
            f"carrying more of this project's writes than the lock is refusing"
        )
    write(f"          {bypass_line}")
    write(f"          {bypass_composition_line(friction)}")
    if report["override"]:
        write(f"          OVERRIDE ACTIVE: {report['override']}")
    write("")

    write(f"REGISTRATIONS (R30) - reporting is total ... {len(report['registrations'])}")
    for line in report["registration_lines"]:
        write(line)
    if not report["registrations"]:
        write("  (none visible from here)")
    write("")

    conflicts = report["conflicts"]
    write(f"CONFLICTS - refusal is narrow ... {len(conflicts)}")
    for conflict in conflicts:
        write(f"  CONFLICT [{conflict['kind']}] {conflict['detail']}")
        write(f"  MIGRATION: {conflict['migration']}")
    if not conflicts:
        write("  none: no other gate stack is armed over this project")
    if report["notes"]:
        # Beside the count, whatever the count is: the raw notes print below
        # either way, but the sentence that says what they DO to the number
        # must not be reserved for the zero case.
        write(
            "  INCOMPLETE: the NOTE(s) below name what this scan could not "
            "read, so the count above is a floor rather than a total"
        )
    for note in report["notes"]:
        write(f"  NOTE {note}")
    write("")
    write("(read-only report; nothing was written, and exit is 0 either way.)")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    """environment, budget and registration report (never blocks)"""
    parser = argparse.ArgumentParser(
        prog="keel survey", description="environment, budget and registration report"
    )
    parser.add_argument("--project", default=None, help="project directory to survey")
    parser.add_argument("--startup", action="store_true", help="print at most one line")
    parser.add_argument("--json", dest="as_json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    try:
        report = survey(project_root(args.project))
        if args.as_json:
            print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        elif args.startup:
            print(startup_line(report))
        else:
            print(render(report))
    except Exception as exc:  # noqa: BLE001 - a report must never fail loudly
        print(f"keel survey: could not complete the report: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
