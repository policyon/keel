#!/usr/bin/env python3
"""keel command-line entry point: CLI-only, no global binary.

Contract
--------
Reads   : ``argv``. The first argument selects a subcommand; everything after
          it belongs to that subcommand and is parsed by it, so no flag has
          to be declared twice.
Emits   : whatever the selected subcommand emits. This file prints only its
          own usage line and its own error for an unknown subcommand.
Writes  : nothing, with one exception that is not a record: ``index`` derives
          ``<project>/.keel/cache/keel-index.db``, a cache with one producer
          that any reader may delete.
Argv    : ``python scripts/keel.py <command> [options]``. Commands, with the
          feature that owns each in ``scripts/keel-features.json``:

            survey      environment and registration report (R30, R9)
            doctor      synthetic hook launches and known-broken-pattern scan
            attest      reconcile a session ledger against the audit log
            leak-check  scan git-tracked files for content that must not leave
            records     check knowledge records against the governance schema
            index       derive the search index from the record files
                        (knowledge)
            chart       search the records, then read them by identifier
                        (knowledge)
            dashboard   read-only local viewer on an ephemeral loopback port
                        (viewer)
            debt        harvest keel:deferred markers left in completed work
            review      append one review verdict to the audit log

          Everything not marked otherwise is kernel-owned and present in
          every edition.

One import per invocation
-------------------------
A subcommand's module is imported when that subcommand is dispatched, never
at startup. Editions are trimmed along the feature seams of
``scripts/keel-features.json``, so an edition without the knowledge feature
carries no ``scripts/keel_chart.py`` - and a module-level import of it would
take the ENTIRE CLI down at startup, including the kernel commands that have
nothing to do with the missing feature. ``COMMANDS`` therefore maps a name to
the module that implements it and the feature that owns it, and ``load``
resolves that pair at call time.

When the owning feature is absent, the command declines in one line naming
the missing feature (``keel_features.decline``) and returns 2. Absence is
read from the LOCAL feature registry, which every bundle ships scoped to its
own edition; a ``ModuleNotFoundError`` on the way to a non-kernel subcommand
is the fallback reading of the same fact, but ONLY when the module it names is
one this edition does not carry - see ``trimmed_away``. A module the registry
declares, or a name that is not one of keel's own modules at all, is a damaged
installation or a damaged environment, and it crashes as one.

Exit codes
----------
The selected subcommand's own, unchanged - this file never invents one:

    survey      0 always (it is a report, not a gate)
    doctor      0 all synthetic launches healthy and no pattern findings and
                  no unreadable settings source,
                1 a probe, a pattern finding, or an unreadable settings
                  source says something worth a look,
                2 could not run (hooks/hooks.json unreadable)
    attest      0 clean, 1 discrepancies found, 2 could not run
    leak-check  0 clean, 1 findings, 2 could not run
    records     0 clean, 1 findings, 2 could not run
    index       0 ran, 2 could not run (never 1: it has no findings)
    chart       0 ran, INCLUDING on no matches, 2 could not run
    dashboard   0 served and stopped, 2 could not start (never 1: a viewer
                has no findings)
    debt        0 ran, INCLUDING on no markers found, 2 could not run (never
                1: it is a harvest, not a gate)
    review      0 the verdict was written, 2 could not run - an unadopted
                project, an unknown verdict, an unusable task id, or no
                session to attribute it to (never 1: it records a judgment,
                it does not make one)

2 is also returned for an unknown or missing subcommand, and for a subcommand
whose owning feature this edition does not include: a CLI that cannot run
what it was asked to run has not succeeded, and both cases are the same
answer to the caller - this command is not available here, with one line
saying why.

Failure policy
--------------
FAIL-CLOSED. This is a build-time and review-time tool, not a runtime guard:
a command that cannot run reports and returns non-zero rather than passing
quietly (convention 12). An absent feature is reported in the same spirit -
one visible line naming the feature and exit 2, never a traceback and never
silence (convention 7). A kernel module that will not import is NOT treated
as an absent feature: every edition carries kernel, so that is a broken
installation and the ImportError propagates rather than being dressed up as
an edition boundary. Neither is a module that IS included and whose own
dependency is missing: "included but broken" and "not included" are two
different facts, and reporting the first as the second would leave a user
shopping for an edition they already have. The one deliberate exception is
``survey``, which
declares its own always-zero contract in its own docstring, because a health
report that fails a build the moment it notices something is a report nobody
runs.

Constraints
-----------
Python 3.10+, standard library only (R7, R14). No network, no subprocess
here; ``leak-check`` runs git with an argument list, never a shell string
(R5). ``dashboard`` is the one subcommand that opens a socket, and it binds
the loopback interface on an ephemeral port and serves no write route (R19).
Subcommand names are matched against ``COMMANDS`` and never interpolated into
an import path: ``load`` imports the module NAMED IN THE TABLE, so no
argument the user types can reach ``importlib`` (R5).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, NamedTuple

_SCRIPTS_DIR = Path(__file__).resolve().parent
for _extra in (str(_SCRIPTS_DIR), str(_SCRIPTS_DIR.parent / "hooks")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from keel_features import declared_modules, decline, feature_absent  # noqa: E402

#: The feature every edition carries. A subcommand it owns is never declined:
#: if its module will not import, the installation is broken, not trimmed.
KERNEL_FEATURE = "kernel"

#: Every module keel itself ships is named for keel: ``keel`` or ``keel_*``
#: (a test derives this from the registry). A ``ModuleNotFoundError`` naming
#: anything else is a missing standard-library or environment module, which no
#: edition boundary explains and which ``trimmed_away`` therefore never claims.
KEEL_MODULE_NAME = "keel"
KEEL_MODULE_PREFIX = "keel_"

#: What a declined subcommand returns - the same 2 an unknown subcommand and
#: every "could not run" returns, because to the caller it is the same answer:
#: this command is not available here. One table, no invented codes.
DECLINE_EXIT_CODE = 2


class Command(NamedTuple):
    """One subcommand: the module implementing it, the feature owning it.

    ``module`` is the import name, which is also the component path this
    edition would have to carry (``scripts/<module>.py``) - derived rather
    than restated, so the table cannot disagree with itself. A test pins
    ``feature`` against ``scripts/keel-features.json``, so the ownership named
    here cannot drift from the registry the editions are cut along.
    """

    module: str
    feature: str

    @property
    def component(self) -> str:
        """The registry component path this subcommand lives at."""
        return f"scripts/{self.module}.py"


class FeatureAbsent(Exception):
    """A subcommand whose owning feature this edition does not include.

    Carries the decline sentence as its message, so a caller that only prints
    ``str(exc)`` still names the missing feature (convention 7).
    """

    def __init__(self, command: str, feature: str) -> None:
        super().__init__(decline(command, feature))
        self.command = command
        self.feature = feature


#: Subcommand name -> the module that implements it and the feature that owns
#: it. The name is what the user types; ``leak-check`` keeps its hyphen because
#: that is the command's own spelling, while the module carries the underscore
#: Python requires. Nothing here is imported until it is dispatched - see "One
#: import per invocation" above.
COMMANDS: dict[str, Command] = {
    "survey": Command("keel_survey", KERNEL_FEATURE),
    "doctor": Command("keel_doctor", KERNEL_FEATURE),
    "attest": Command("keel_attest", KERNEL_FEATURE),
    "leak-check": Command("keel_leak_check", KERNEL_FEATURE),
    "records": Command("keel_records", KERNEL_FEATURE),
    "index": Command("keel_index", "knowledge"),
    "chart": Command("keel_chart", "knowledge"),
    "dashboard": Command("keel_dashboard", "viewer"),
    "debt": Command("keel_debt", KERNEL_FEATURE),
    "review": Command("keel_review", KERNEL_FEATURE),
}


def is_keel_module(name: str) -> bool:
    """Whether an import name is one of keel's OWN modules, by its name alone.

    The only question that can be answered without the registry, and it has to
    be answered first: no edition boundary runs through ``sqlite3``.
    """
    return name == KEEL_MODULE_NAME or name.startswith(KEEL_MODULE_PREFIX)


def trimmed_away(missing: str | None, spec: Command) -> bool:
    """Whether a ``ModuleNotFoundError`` is edition-shaped rather than damage.

    THE RULE. A missing module is trimming-shaped in exactly two cases:

    1. it IS the subcommand's own module - the file this edition would have
       dropped along its feature seam;
    2. or it is another of KEEL'S OWN modules that the local registry does not
       declare. Every bundle ships a registry scoped to its own feature
       closure, so a keel module the registry does not name is one an ABSENT
       feature owns. This is the ``keel_chart`` imports ``keel_index`` case: in
       a trimmed bundle the failure arrives under a DIFFERENT name than
       ``spec.module``, and refusing to read it would turn a genuine decline
       into a traceback.

    Everything else propagates as the crash it is:

    * a name that is not keel's own module - a standard-library or environment
      dependency is missing, which is a broken environment, not a trimmed
      edition;
    * a keel module the registry DOES declare - this edition claims to carry
      it, so it is present-and-broken (corruption), and calling that an
      edition boundary would tell the user to install something they already
      have;
    * an unreadable registry (``declared_modules`` returns None - UNDECIDABLE):
      a guess in either direction is precisely the silent failure this rule
      exists to prevent;
    * an exception carrying no module name at all.

    The decline that follows names the feature owning the SUBCOMMAND, not the
    missing module: a scoped registry cannot say which absent feature owns a
    component it does not list, and the subcommand's own feature is the one the
    user asked for.
    """
    if not missing:
        return False
    if missing == spec.module:
        return True
    if not is_keel_module(missing):
        return False
    declared = declared_modules()
    if declared is None:
        return False
    return missing not in declared


def load(name: str) -> Callable[[list[str]], int]:
    """The subcommand's ``main``, imported now.

    Raises ``FeatureAbsent`` when the feature owning ``name`` is not installed
    in this edition - decided from the local registry first, and from a
    ``ModuleNotFoundError`` as the fallback reading of the same fact, but only
    for the two trimming-shaped cases ``trimmed_away`` states. Any other import
    failure, and any failure at all for a kernel-owned subcommand, propagates
    untouched: a broken installation must not be reported as a trimmed one, and
    a module that is included but cannot import its own dependency is broken.
    ``KeyError`` for a name the table does not hold, which ``main`` resolves
    before calling this.
    """
    spec = COMMANDS[name]
    kernel = spec.feature == KERNEL_FEATURE
    if not kernel and feature_absent(spec.feature, component=spec.component):
        raise FeatureAbsent(name, spec.feature)
    try:
        module = importlib.import_module(spec.module)
    except ModuleNotFoundError as exc:
        if kernel or not trimmed_away(exc.name, spec):
            raise
        raise FeatureAbsent(name, spec.feature) from exc
    return module.main


def summary(name: str) -> str:
    """One line describing a subcommand, for the usage screen.

    The subcommand's own ``main`` docstring where the feature is installed -
    generated, so help text cannot drift from the code - and the decline
    sentence where it is not, because a command listed with no explanation is
    how a trimmed edition looks broken instead of looking trimmed.
    """
    try:
        handler = load(name)
    except FeatureAbsent as exc:
        return str(exc)
    return ((handler.__doc__ or "").strip().splitlines() or [""])[0]


def usage() -> str:
    """The one-screen help, generated from COMMANDS so it cannot drift."""
    lines = ["usage: python scripts/keel.py <command> [options]", "", "commands:"]
    for name in COMMANDS:
        lines.append(f"  {name:<12} {summary(name)}")
    lines.append("")
    lines.append("run a command with --help for its own options")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Dispatch on the first argument; return the subcommand's exit code."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        print(usage())
        return 0 if args else 2
    name, rest = args[0], args[1:]
    if name not in COMMANDS:
        print(f"keel: unknown command {name!r}", file=sys.stderr)
        print(usage(), file=sys.stderr)
        return 2
    try:
        handler = load(name)
    except FeatureAbsent as exc:
        print(f"keel: {exc}", file=sys.stderr)
        return DECLINE_EXIT_CODE
    return handler(rest)


if __name__ == "__main__":
    sys.exit(main())
