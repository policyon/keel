#!/usr/bin/env python3
"""Assemble a published cut of keel into an existing mirror tree.

Writes: the mirror tree named by ``--mirror``, and nothing else. Never the
development repository, never a git remote, never a commit, never a push.

WHY THIS FILE EXISTS. The procedure was a shell block in one session's
transcript for four days: reproducible by nobody, verifiable by nobody, and
already mis-described twice in the backlog entry that tracked it. A published
cut is the one artefact of this project an outsider ever sees, so the procedure
that builds it belongs in the tree it publishes.

WHAT A CUT IS. The mirror is not a filtered clone. It is a separate
single-root repository whose non-record tree is REPLACED wholesale from a
chosen commit of the development repository, while its own seeded ``.keel``
skeleton is reduced to the declaration and two empty surfaces.

IT SHIPS NO RECORDS AT ALL, ruled by the owner 2026-09-01: no decisions, no
freeze record, no watermark, no ledgers, no knowledge. Until that ruling this
script refreshed five decision records each cut and refused a mirror whose
decisions directory was empty. The ruling restores clause 3 of the publication
ruling as literally written — that clause always excluded decisions, and this
script had been the more permissive of the two. See
:data:`SHIPPED_RECORD_ALLOW`, which is the whole of what ``.keel/`` may carry.
The governing ruling is
``.keel/decisions/2026-08-22-keel-publishes-a-fresh-mirror-without-its-working-records.md``.

THE SHIPPED PRODUCT IS NOT ARMED. Ratified 2026-08-31
(``.keel/decisions/2026-08-31-the-shipped-product-is-not-armed.md``): a cut
ships NO ``.keel/keel-policy.md``. Arming is what that file's presence does —
the file says so in its own first lines — so a cut that shipped one would arm
the adopter's tree on their behalf, which is the one decision keel exists to
leave with them. ``templates/keel-policy.md`` ships instead, verified
byte-identical to the tip so nobody arms from a stale template, and the adopter
chooses their own tier.

THIS RETIRED THE CONSTRAINT THE PROCEDURE WAS BUILT AROUND, rather than
implementing it more carefully. The earlier ordering removed the arming file,
assembled, and wrote it back LAST, because a PARTIAL arming file arms a tree
with a full default lock — which is how the first assembly froze against its own
author. A cut that never writes one cannot reach that state, so there is no
window in which this tree is half-armed, no backup to restore, and no
interrupt-safety question to get wrong. It also dissolved a three-way deadlock
between the plan gate, the published-cut guard and the plan-contract guard,
which cost seven suite failures while the cut shipped armed (backlog BL13).

WHAT THIS SCRIPT REFUSES TO DO, each fail-closed and checked before the first
destructive step:

* run against a tree that does not declare itself a published cut;
* run against a mirror carrying untracked, non-ignored files outside the record
  prefix — the clear step deletes only TRACKED paths, so such a file would
  survive the rebuild and then be staged into the cut;
* run against the development repository itself, or against a tree that is not
  a git repository;
* run against a mirror that has a git remote configured — the flip is the
  owner's own act under clause 5 of the ruling above, and a script that could
  push would make that clause a convention rather than a fact;
* commit or push anything at all;
* stage a session ledger, or stage the append-only record surfaces whose
  published content is empty by declaration. ``git add -A`` on its own would
  publish both, which is how a stray local audit line reaches an adopter.

Stdlib only, by the same constraint as the rest of this directory.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

#: The file whose presence declares a tree to be a published cut. A tree
#: without it is not a mirror, and this script refuses to rebuild it — the
#: cheapest possible guard against being pointed at a working checkout.
CUT_MARKER = ".keel/published-cut.md"

#: The arming file. A published cut ships NONE — see :func:`disarm` and the
#: ratified decision it cites. Named here so the cut can prove its absence.
ARMING_FILE = ".keel/keel-policy.md"

#: What ships INSTEAD, so an adopter has something to arm from.
POLICY_TEMPLATE = "templates/keel-policy.md"

#: Everything under this prefix is the mirror's OWN, and is never deleted when
#: the non-record tree is replaced. The seeded skeleton lives here.
RECORD_PREFIX = ".keel/"

#: Tracked paths that must keep their COMMITTED content, never the working
#: tree's. These are append-only record surfaces that a published cut ships
#: empty by declaration; a local session appends to them merely by existing.
#: Excluded from staging so the cut cannot publish local record lines.
NEVER_STAGE_EXACT = (
    ".keel/audit/keel-audit.jsonl",
    ".keel/queue/keel-observations.jsonl",
)

#: Session ledgers. Scaffolding that a session may be forced to write into the
#: mirror to satisfy its plan gate, never content of a cut.
NEVER_STAGE_GLOB = (".keel/plans/keel-plan-*.md",)

#: THE ONLY ``.keel/`` PATHS A CUT MAY CARRY. Ruled by the owner 2026-09-01:
#: ship only the artifacts, with no records at all — no decisions, no freeze
#: record, no watermark. That restores clause 3 of the publication ruling as
#: literally written; the clause always excluded decisions, and this script had
#: been more permissive than the law it cites.
#:
#: What survives is not a record. :data:`CUT_MARKER` is the cut's own
#: DECLARATION — the shipped suite reads it to invert its self-hosting
#: assertions — and the two append-only surfaces plus their ``.gitkeep``
#: siblings exist so the tooling finds the shape it expects, EMPTY. A reader
#: learns nothing about this project from a zero-byte file.
SHIPPED_RECORD_ALLOW: tuple[str, ...] = (
    CUT_MARKER,
    ".keel/audit/keel-audit.jsonl",
    ".keel/queue/keel-observations.jsonl",
)

#: Basenames allowed anywhere under ``.keel/``, for the same reason.
SHIPPED_RECORD_ALLOW_NAMES: tuple[str, ...] = (".gitkeep",)

#: The declaration the cut writes into :data:`CUT_MARKER`. THE SCRIPT OWNS THIS
#: TEXT rather than preserving whatever the mirror happens to hold, because the
#: previous wording promised that "all but the cited decisions" stayed private —
#: true when five shipped, false now, and a declaration that describes an
#: earlier policy is worse than none. Owning it here means the cut cannot
#: declare one thing while doing another.
CUT_DECLARATION = """# published cut

This tree is a published cut of keel. It carries the product and nothing else:
no session ledgers, no knowledge records, no decision records, no audit
history, no observation queue. Those exist, and they stay in the maintainer's
own repository.

This file is that declaration, and the suite reads it. With this file present,
every self-referential assertion INVERTS: the record surfaces are asserted to
be exactly as empty as this file says, and a tree carrying both this file and a
development corpus fails loudly. So the declaration can never quietly silence a
guard where the record actually lives.

The two files under `.keel/audit/` and `.keel/queue/` are present and empty on
purpose, so the tooling finds the shape it expects. A zero-byte file tells a
reader nothing.

keel is not armed here. Arming is what `.keel/keel-policy.md` does, and a cut
ships none: copy `templates/keel-policy.md` and choose your own tier.
"""


class CutError(RuntimeError):
    """A guard refused, or a step could not be completed."""


def _run(
    args: list[str], cwd: Path | None = None, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a command and return it. Raises :class:`CutError` on failure.

    Failure carries the command's own stderr, because a guard that reports
    only an exit code makes its caller guess.
    """
    proc = subprocess.run(
        args,
        cwd=None if cwd is None else str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and proc.returncode != 0:
        raise CutError(
            "command failed (exit %d): %s\n%s"
            % (proc.returncode, " ".join(args), (proc.stderr or "").strip())
        )
    return proc


def _git(repo: Path, *args: str, check: bool = True) -> str:
    """Run git in ``repo`` and return stdout stripped of its trailing newline."""
    return _run(["git", "-C", str(repo), *args], check=check).stdout.rstrip("\n")


def _is_git_repo(path: Path) -> bool:
    proc = _run(
        ["git", "-C", str(path), "rev-parse", "--git-dir"], check=False
    )
    return proc.returncode == 0


def guard(private: Path, mirror: Path, tip: str) -> str:
    """Refuse every way this could be pointed somewhere it must not touch.

    Runs to completion BEFORE anything is deleted, so a refusal costs nothing.
    Returns the resolved full commit id of ``tip``.
    """
    if not private.is_dir():
        raise CutError(f"development repository not found: {private}")
    if not _is_git_repo(private):
        raise CutError(f"not a git repository: {private}")

    if not mirror.is_dir():
        raise CutError(f"mirror not found: {mirror}")
    if not _is_git_repo(mirror):
        raise CutError(f"mirror is not a git repository: {mirror}")

    try:
        same = mirror.resolve() == private.resolve()
    except OSError as exc:  # pragma: no cover - unreadable path
        raise CutError(f"cannot resolve paths: {exc}") from exc
    if same:
        raise CutError(
            "mirror and development repository are the same tree; refusing to "
            "rebuild the repository this script was run from"
        )

    marker = mirror / CUT_MARKER
    if not marker.is_file():
        raise CutError(
            f"{mirror} does not declare itself a published cut ({CUT_MARKER} "
            "is absent). Refusing: this script REPLACES a tree's tracked "
            "non-record files, and it will only do that to a tree that says "
            "it exists to be replaced."
        )

    remotes = _git(mirror, "remote")
    if remotes.strip():
        raise CutError(
            "mirror has a git remote configured (%s). Refusing: publishing is "
            "the owner's own act, and this script must not be able to reach a "
            "remote. Remove the remote to re-cut, or cut into a tree that has "
            "none." % ", ".join(remotes.split())
        )

    strays = untracked_non_record(mirror)
    if strays:
        raise CutError(
            "the mirror carries %d untracked, non-ignored file(s) outside %s, and "
            "a cut cannot honestly replace them. The clear step deletes only "
            "TRACKED files, and the tip's export has nothing to copy over an "
            "unexpected path, so each of these would survive the rebuild — and "
            "then be staged, because they match no exclusion. Remove them, or "
            "add them to the mirror's .gitignore, and re-run. Found: %s"
            % (len(strays), RECORD_PREFIX, ", ".join(strays[:10]))
        )

    record_strays = untracked_records(mirror)
    if record_strays:
        raise CutError(
            "the mirror carries %d untracked record file(s), and a published cut "
            "ships NO records (ruled 2026-09-01). The strip step reads git's "
            "index, so an untracked record is invisible to it and would be staged "
            "as a NEW file by the assembly that follows. This script will NOT "
            "delete them — removing a record is the owner's call, the same call "
            "the ledger refusal below reserves to them — and it refuses HERE, "
            "before the first destructive step, rather than after rebuilding the "
            "tree. Remove them yourself and re-run. Found: %s"
            % (len(record_strays), ", ".join(record_strays[:10]))
        )

    ledgers = session_ledgers(mirror)
    if ledgers:
        raise CutError(
            "the mirror carries %d session ledger(s), and a published cut "
            "declares its record surfaces EMPTY — the suite's own published-cut "
            "guard reads the disk, so shipping this would fail it. This script "
            "will NOT delete them: removing a record is the owner's call, the "
            "same call keel's plan-contract guard already reserves to them. "
            "Remove them yourself and re-run. Found: %s"
            % (len(ledgers), ", ".join(ledgers))
        )

    resolved = _git(private, "rev-parse", "--verify", f"{tip}^{{commit}}", check=False)
    if not resolved:
        raise CutError(f"tip does not resolve in {private}: {tip}")
    return resolved


def untracked_records(mirror: Path) -> list[str]:
    """Untracked, non-ignored files UNDER the record prefix, allowlist aside.

    The mirror image of :func:`untracked_non_record`, and it exists because the
    2026-09-01 ruling changed what the record prefix means to a cut. Records
    used to be the mirror's own — preserved, refreshed, deliberately shipped —
    so an untracked one there was unremarkable. Now a cut ships none, and
    :func:`strip_records_and_declare` reads git's INDEX, so an untracked record
    is invisible to it: it survives the rebuild and is staged as a new file.

    Reported for a refusal rather than deleted, matching the ledger refusal
    beside it: removing a record is the owner's call.
    """
    listing = _git(mirror, "ls-files", "--others", "--exclude-standard", "-z")
    out: list[str] = []
    for entry in listing.split("\0"):
        rel = entry.strip().replace("\\", "/")
        if not rel or not rel.startswith(RECORD_PREFIX):
            continue
        if rel in SHIPPED_RECORD_ALLOW or Path(rel).name in SHIPPED_RECORD_ALLOW_NAMES:
            continue
        out.append(rel)
    return sorted(out)


def untracked_non_record(mirror: Path) -> list[str]:
    """Untracked, non-ignored files in the mirror outside the record prefix.

    The record prefix is excluded because a session may be FORCED to write a
    ledger there to satisfy the mirror's own plan gate, and because the seeded
    skeleton is the mirror's own. Everything else is a stray: it survives the
    clear (which reads only tracked paths) and would be staged by ``git add -A``
    into the published cut.

    ``--exclude-standard`` is what keeps this from firing on ignored build
    output, so a mirror only has to be tidy about files git would track.
    """
    listing = _git(mirror, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(
        entry.strip()
        for entry in listing.split("\0")
        if entry.strip() and not entry.strip().startswith(RECORD_PREFIX)
    )


def _archive_member_name(raw: str) -> str:
    """Normalise a tar member name to a repo-relative POSIX path.

    NEVER ``lstrip("./")``: that strips any leading run of ``.`` and ``/``
    CHARACTERS, so ``.keel/audit/x`` becomes ``keel/audit/x`` and every
    exclusion keyed on the leading dot silently stops matching. That exact
    mistake copied 146 knowledge records, 29 session ledgers and the backlog
    into a rehearsal tree — the whole development record, into the one artefact
    that exists to ship without it.
    """
    name = raw.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def _is_record_path(name: str) -> bool:
    """True for the development repository's own record directory."""
    return name == RECORD_PREFIX.rstrip("/") or name.startswith(RECORD_PREFIX)


def export_tip(private: Path, tip: str, work: Path) -> Path:
    """Extract ``tip``'s tree into ``work`` and drop its record directory.

    The development repository's own ``.keel`` never ships: the mirror keeps
    its own seeded skeleton instead.

    THREE INDEPENDENT DEFENCES, because this is the step whose silent failure
    publishes the project's private records: members under the record prefix
    are skipped during extraction; the directory is then deleted wholesale from
    the exported tree even if the skip missed it (what the original shell block
    did, and it was right); and :func:`assert_no_records_exported` refuses to
    continue if anything under that prefix survived both. A filter, a sweep,
    and an assertion, because the filter is the part that already failed once.
    """
    tree = work / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    tar_path = work / "tip.tar"
    _run(
        [
            "git",
            "-C",
            str(private),
            "archive",
            "--format=tar",
            f"--output={tar_path}",
            tip,
        ]
    )
    with tarfile.open(tar_path, "r") as archive:
        for member in archive.getmembers():
            name = _archive_member_name(member.name)
            if _is_record_path(name):
                continue
            if name.startswith("/") or ".." in Path(name).parts:
                raise CutError(f"refusing unsafe archive member: {member.name}")
            if member.issym() or member.islnk():
                # A link whose target escapes the export would let a commit in
                # the development repository write outside the temporary tree
                # when extracted. Remote — it needs a malicious commit in our
                # own history — but the check is three lines and the failure
                # would be silent.
                target = _archive_member_name(member.linkname)
                if member.linkname.startswith("/") or ".." in Path(target).parts:
                    raise CutError(
                        f"refusing archive member whose link target escapes the "
                        f"export: {member.name} -> {member.linkname}"
                    )
            archive.extract(member, path=tree)

    stray = tree / RECORD_PREFIX.rstrip("/")
    if stray.exists():
        shutil.rmtree(stray)

    assert_no_records_exported(tree)

    if not (tree / "README.md").is_file():
        raise CutError(
            "exported tree has no README.md, which every commit of this "
            "project has; the export is not what it should be"
        )
    return tree


def assert_no_records_exported(tree: Path) -> None:
    """Refuse if anything under the record prefix survived the export.

    The guard that catches the CLASS rather than the one bug that prompted it:
    however a record path comes to be in the exported tree — a normalisation
    slip, a rename of the prefix, a future filter that stops matching — the cut
    stops here rather than copying it into a tree meant for publication.
    """
    root = tree / RECORD_PREFIX.rstrip("/")
    if not root.exists():
        return
    survivors = sorted(
        str(p.relative_to(tree)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file()
    )
    raise CutError(
        "the exported tree still carries %d file(s) under %s after filtering "
        "and sweeping — refusing to assemble a published cut from it. First "
        "few: %s"
        % (len(survivors), RECORD_PREFIX, ", ".join(survivors[:5]) or "(none)")
    )


def clear_non_record_tracked(mirror: Path) -> int:
    """Delete the mirror's tracked files EXCEPT its record directory.

    Reads the MIRROR's index, not the development repository's, so the
    exclusion protects the mirror's own seeded skeleton. Returns how many
    files were removed.
    """
    listing = _git(mirror, "ls-files", "-z")
    removed = 0
    for entry in listing.split("\0"):
        rel = entry.strip()
        if not rel or rel.startswith(RECORD_PREFIX):
            continue
        target = mirror / rel
        if target.is_file() or target.is_symlink():
            target.unlink()
            removed += 1
    return removed


def prune_empty_dirs(mirror: Path) -> int:
    """Remove directories left empty by the clear, never touching git's own."""
    pruned = 0
    for current, dirnames, filenames in os.walk(mirror, topdown=False):
        here = Path(current)
        if here == mirror:
            continue
        parts = here.relative_to(mirror).parts
        if parts and parts[0] == ".git":
            continue
        if not dirnames and not filenames:
            here.rmdir()
            pruned += 1
    return pruned


def copy_tree(tree: Path, mirror: Path) -> int:
    """Copy the exported tree over the mirror. Returns files written."""
    written = 0
    for src in tree.rglob("*"):
        if src.is_dir():
            continue
        rel = src.relative_to(tree)
        dst = mirror / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        written += 1
    return written


def strip_records_and_declare(mirror: Path) -> tuple[list[str], bool]:
    """Remove every record the cut must not carry, then write the declaration.

    WHAT THIS REPLACED, and why replacing beats configuring. Until 2026-09-01
    this function was ``refresh_cited_decisions``: it rewrote the five decision
    records the mirror tracked, and REFUSED a mirror whose decisions directory
    was empty — so "ship no records" was unreachable by any argument. The owner
    ruled that a cut ships only the artifacts, which restores clause 3 of the
    publication ruling as literally written: that clause always excluded
    decisions, and this script had been more permissive than the law it cites.
    The refusal went with the function it guarded, because a guard protecting an
    invariant the project has abandoned is a trap for the next reader.

    HOW REMOVAL REACHES THE INDEX: by unlinking, and letting :func:`stage`'s
    ``git add -A`` record the deletion. Nothing here runs a destructive git verb
    against a record path — this project's own gate refuses those, correctly,
    and a cut script that needed an exemption from the rules it publishes would
    be arguing against itself.

    Returns the record paths removed, and whether the declaration changed.
    """
    listing = _git(mirror, "ls-files", "-z", RECORD_PREFIX)
    tracked = [entry.strip() for entry in listing.split("\0") if entry.strip()]
    removed: list[str] = []
    for rel in sorted(tracked):
        if rel in SHIPPED_RECORD_ALLOW or Path(rel).name in SHIPPED_RECORD_ALLOW_NAMES:
            continue
        # THE ARMING FILE IS NOT THIS STEP'S BUSINESS, even though it lives
        # under the record prefix and must not ship. :func:`disarm` owns it: it
        # carries the ratified reasoning, and it reports whether a file was
        # actually removed. Removing it here would leave that report saying
        # "was already absent" on every cut — a true sentence about a state this
        # function had silently produced, which is the least useful kind.
        if rel == ARMING_FILE:
            continue
        target = mirror / rel
        if target.is_file():
            target.unlink()
        removed.append(rel)

    marker = mirror / CUT_MARKER
    existing = marker.read_bytes() if marker.is_file() else b""
    declaration = CUT_DECLARATION.encode("utf-8")
    # EOL-folded, for the reason ``_eol_normalised`` states: a CRLF checkout
    # would otherwise report the declaration as rewritten on every single cut,
    # and a report that always says "changed" says nothing.
    rewritten = _eol_normalised(existing) != _eol_normalised(declaration)
    if rewritten:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_bytes(declaration)
    return removed, rewritten


def assert_only_declared_records_staged(mirror: Path) -> None:
    """Fail if any ``.keel/`` path outside the allowlist reached the index.

    The companion to :func:`strip_records_and_declare`: that function removes
    what must not ship, and this one proves it. Separate, because a step that
    both acts and certifies its own action cannot be trusted about either — and
    because a record can reach the index by routes this script never took, such
    as a session writing into the mirror between assembly and commit.

    Every offender is named, not the first: a caller who fixes one and re-runs
    to find another has been told the truth one item at a time.
    """
    # ``--diff-filter=d`` EXCLUDES DELETIONS, and that exclusion is the whole
    # subtlety here. ``git diff --cached --name-only`` lists a removed record
    # too — removal is staged like anything else — so without this the assertion
    # refuses the very act it exists to enforce, and refuses it on every cut,
    # since every cut removes records and the arming file. What is being
    # asserted is that no record ARRIVES in the index, never that none appears
    # in the diff.
    staged = [
        line.strip()
        for line in _git(
            mirror, "diff", "--cached", "--name-only", "--diff-filter=d"
        ).splitlines()
        if line.strip()
    ]
    offenders = [
        path
        for path in staged
        if path.replace("\\", "/").startswith(RECORD_PREFIX)
        and path not in SHIPPED_RECORD_ALLOW
        and Path(path).name not in SHIPPED_RECORD_ALLOW_NAMES
    ]
    if offenders:
        raise CutError(
            "a published cut ships no records, and these were staged: "
            + ", ".join(sorted(offenders))
            + f" (allowed: {', '.join(SHIPPED_RECORD_ALLOW)})"
        )


def disarm(mirror: Path) -> bool:
    """Remove the cut's arming file, so the shipped product is NOT armed.

    Ratified 2026-08-31 (``the shipped product is not armed``): arming is what
    this file's presence does, so a cut that shipped one would arm the adopter's
    tree on their behalf. The template ships instead and the adopter arms their
    own copy deliberately, choosing their own tier.

    Returns True if a file was removed. Idempotent: a cut of an already-disarmed
    tree is not an error.
    """
    target = mirror / ARMING_FILE
    if target.is_file():
        target.unlink()
        return True
    return False


def session_ledgers(mirror: Path) -> list[str]:
    """Session ledgers present in the tree. A cut REFUSES rather than deleting.

    A published cut declares its record surfaces EMPTY
    (``.keel/published-cut.md``), and a session ledger is a record — keeping one
    out of the INDEX is not enough, because the suite's own published-cut guard
    reads the DISK.

    THIS REFUSES INSTEAD OF DELETING, and the consistency is the point. An
    earlier version of this function unlinked them, which contradicted
    :func:`guard`'s posture in this same file — that one refuses to remove
    untracked strays on the reasoning that deleting a human's untracked files is
    the one unrecoverable loss. A session ledger IS an untracked record file,
    and it is the exact class keel's own plan-contract guard refuses to let an
    agent destroy, so that argument applies to it more strongly rather than
    less. Ratified by the owner 2026-08-31 after they caught the script deleting
    a file this session had three times said was theirs to delete.

    So the destroy decision stays with the owner, exactly where keel's own guard
    already puts it: `rm` of a ``keel-plan-*.md`` path is refused from the shell
    by filename pattern in any tree, armed or not.

    A ledger should not appear in a fresh cut at all: they got there because a
    cut once shipped an ARMED arming file, whose plan gate forced a session to
    write one before it could run any command against the tree. Cuts ship
    disarmed now (:func:`disarm`), so this is a check against a tree carrying one
    from before, not a routine cleanup step.
    """
    plans = mirror / ".keel" / "plans"
    if not plans.is_dir():
        return []
    return sorted(f".keel/plans/{p.name}" for p in plans.glob("keel-plan-*.md"))


def verify_disarmed(private: Path, mirror: Path, tip: str) -> None:
    """Refuse unless the cut is disarmed AND carries the template.

    Both halves, because either alone is a broken product: an arming file left
    behind arms the adopter's tree for them, and a missing template leaves them
    nothing to arm it WITH. The template is checked against the tip rather than
    merely for existence, so a cut cannot ship a stale one.
    """
    armed = mirror / ARMING_FILE
    if armed.exists():
        raise CutError(
            f"{ARMING_FILE} is still present after assembly. A published cut "
            "must ship UNARMED — arming is the adopter's own act."
        )

    expected = _run(
        ["git", "-C", str(private), "show", f"{tip}:{POLICY_TEMPLATE}"], check=False
    )
    if expected.returncode != 0:
        raise CutError(
            f"{POLICY_TEMPLATE} does not exist at {tip}. Refusing: a disarmed cut "
            "that also ships no template leaves an adopter nothing to arm with."
        )
    shipped = mirror / POLICY_TEMPLATE
    if not shipped.is_file():
        raise CutError(f"{POLICY_TEMPLATE} is missing from the assembled cut")
    if _eol_normalised(shipped.read_bytes()) != _eol_normalised(
        expected.stdout.encode("utf-8")
    ):
        raise CutError(
            f"{POLICY_TEMPLATE} in the cut does not match {tip}; the adopter "
            "would arm from a stale template"
        )


def _eol_normalised(body: bytes) -> bytes:
    """``body`` with CRLF collapsed to LF, for comparisons across a conversion.

    THIS COMPARISON CROSSES AN EOL BOUNDARY AND MUST NOT CARE. The shipped file
    arrives through ``git archive``, which applies the tree's end-of-line
    conversion; the expected text comes from ``git show``, which is the raw
    blob. On a repository that pins ``eol=lf`` in ``.gitattributes`` — as keel
    does — the two agree byte for byte. On one that does not, ``core.autocrlf``
    makes the archive CRLF while the blob stays LF, and a byte comparison would
    then report a stale template on every cut.

    Staleness is a claim about CONTENT. Line endings are decided by git's
    conversion rules and the platform, so folding them out is what makes this
    check answer the question it is asking. The test fixture deliberately ships
    NO ``.gitattributes`` so that the harsher case is the one under test.
    """
    return body.replace(b"\r\n", b"\n")


def stage(mirror: Path) -> tuple[int, list[str]]:
    """Stage the cut, excluding what a published cut must never carry.

    ``git add -A`` alone would stage the mirror's locally-appended audit log
    and any session ledger written to satisfy the mirror's own plan gate.
    Pathspec exclusions are used rather than staging everything and unstaging
    after, because the unstage verbs (``restore``, ``checkout``, ``reset``)
    naming a record path are refused by this project's own gate — correctly.

    Returns the staged file count and the exclusion pathspecs used.
    """
    excludes = [f":(exclude){p}" for p in NEVER_STAGE_EXACT]
    excludes += [f":(exclude){p}" for p in NEVER_STAGE_GLOB]
    _run(["git", "-C", str(mirror), "add", "-A", "--", ".", *excludes])
    staged = _git(mirror, "diff", "--cached", "--name-only")
    count = len([line for line in staged.splitlines() if line.strip()])
    return count, excludes


def assert_nothing_forbidden_staged(mirror: Path) -> None:
    """Fail if any never-stage path reached the index. The guard's own guard.

    An exclusion pathspec that silently stopped matching would otherwise
    publish exactly what it exists to withhold, and nothing else in the
    pipeline would notice.
    """
    staged = [
        line.strip()
        for line in _git(mirror, "diff", "--cached", "--name-only").splitlines()
        if line.strip()
    ]
    offenders = [p for p in staged if p in NEVER_STAGE_EXACT]
    for pattern in NEVER_STAGE_GLOB:
        # fnmatch rather than partition("*"): a hand-rolled prefix/suffix split
        # handles exactly one wildcard, and would silently UNDER-match — quietly
        # publishing what it exists to withhold — the day a pattern gained a
        # second one. The failure mode of the shortcut is invisible, so it does
        # not get to be the implementation.
        offenders += [
            p
            for p in staged
            if fnmatch.fnmatch(p, pattern) and p not in offenders
        ]
    if offenders:
        raise CutError(
            "these paths must never be staged into a published cut and were: "
            + ", ".join(sorted(offenders))
        )


def cut(private: Path, mirror: Path, tip: str, work: Path) -> dict[str, object]:
    """Run the whole assembly. Returns a report of what it did."""
    resolved = guard(private, mirror, tip)

    # NO BACKUP-AND-RESTORE DANCE ANY MORE, and its absence is the point.
    # The old ordering removed the arming file, assembled, then wrote it back
    # LAST — because a PARTIAL arming file arms a tree with a full default lock,
    # which froze the first assembly against its own author. A cut that never
    # writes one cannot reach that state at all, so the hazard is retired by
    # construction rather than guarded more carefully. The whole
    # interrupt-safety question that guarded it goes with it: there is no
    # window in which this tree is half-armed, because it is never armed.
    tree = export_tip(private, resolved, work)
    removed = clear_non_record_tracked(mirror)
    pruned = prune_empty_dirs(mirror)
    written = copy_tree(tree, mirror)
    records_removed, declared = strip_records_and_declare(mirror)
    disarmed = disarm(mirror)
    verify_disarmed(private, mirror, resolved)

    staged, excludes = stage(mirror)
    assert_nothing_forbidden_staged(mirror)
    assert_only_declared_records_staged(mirror)

    return {
        "tip": resolved,
        "removed": removed,
        "pruned": pruned,
        "written": written,
        "records_removed": records_removed,
        "declaration_rewritten": declared,
        "disarmed": disarmed,
        "staged": staged,
        "excludes": excludes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a published cut of keel into an existing mirror tree.",
    )
    parser.add_argument(
        "--mirror",
        required=True,
        help="the mirror tree to rebuild. Required and never defaulted: this "
        "script replaces a tree's tracked files, so it will not guess which.",
    )
    parser.add_argument(
        "--tip",
        default="HEAD",
        help="commit of the development repository to cut from (default HEAD).",
    )
    parser.add_argument(
        "--private",
        default=None,
        help="the development repository (default: this script's own repository).",
    )
    parser.add_argument(
        "--tmp",
        default=None,
        help="working directory for the export (default: a fresh temporary "
        "directory, removed on exit).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run every guard and report what would be done, changing nothing.",
    )
    args = parser.parse_args(argv)

    private = (
        Path(args.private).expanduser()
        if args.private
        else Path(__file__).resolve().parent.parent
    )
    mirror = Path(args.mirror).expanduser()

    try:
        if args.dry_run:
            resolved = guard(private, mirror, args.tip)
            tracked = [
                e.strip()
                for e in _git(mirror, "ls-files", "-z").split("\0")
                if e.strip()
            ]
            non_record = [p for p in tracked if not p.startswith(RECORD_PREFIX)]
            print("DRY RUN - nothing changed")
            print(f"  development repository : {private}")
            print(f"  mirror                 : {mirror}")
            print(f"  tip                    : {resolved}")
            print(f"  mirror remotes         : none (verified)")
            print(f"  would replace          : {len(non_record)} tracked file(s)")
            print(f"  would preserve         : {len(tracked) - len(non_record)} "
                  f"file(s) under {RECORD_PREFIX}")
            print(f"  would REMOVE           : {ARMING_FILE} (cut ships unarmed)")
            print(f"  would require          : {POLICY_TEMPLATE}")
            print(f"  would never stage      : "
                  f"{', '.join(NEVER_STAGE_EXACT + NEVER_STAGE_GLOB)}")
            return 0

        if args.tmp:
            work = Path(args.tmp).expanduser()
            if work.exists():
                shutil.rmtree(work)
            work.mkdir(parents=True)
            report = cut(private, mirror, args.tip, work)
        else:
            with tempfile.TemporaryDirectory(prefix="keel-cut-") as tmpdir:
                report = cut(private, mirror, args.tip, Path(tmpdir))
    except CutError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    print(f"cut {mirror} from {report['tip']}")
    print(f"  removed (tracked, non-record) : {report['removed']}")
    print(f"  empty directories pruned      : {report['pruned']}")
    print(f"  files written from the tip     : {report['written']}")
    print(f"  records removed (ship none)    : {len(report['records_removed'])}")
    for rel in report["records_removed"]:  # type: ignore[union-attr]
        print(f"      {rel}")
    print(
        f"  cut declaration                : "
        f"{'rewritten' if report['declaration_rewritten'] else 'already current'}"
    )
    print(
        f"  arming file                    : "
        f"{'REMOVED' if report['disarmed'] else 'was already absent'} — the cut "
        f"ships UNARMED (arming is the adopter's act)"
    )
    print(f"  policy template                : shipped, byte-identical to the tip")
    print("  session ledgers                : none (a cut refuses to run with any)")
    print(f"  staged                         : {report['staged']} path(s)")
    print(f"  never staged                   : "
          f"{', '.join(NEVER_STAGE_EXACT + NEVER_STAGE_GLOB)}")
    print("  committed / pushed             : nothing (the owner's own act)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
