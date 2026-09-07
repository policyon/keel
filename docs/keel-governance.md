# keel governance

Phase 0 written rules. These bind the repository from the first commit; they
are not aspirations for later. The identifiers in brackets are the design
commitments each section discharges, defined in `docs/keel-rules.md`.

## 1. Release discipline (R29, R31)

**Every release is exactly two things plus a tag, or it is not a release:**

1. A `CHANGELOG.md` entry under a `## <version> — <title>` heading, written in
   the same change that ships the work. A release with no changelog entry is
   rejected; a changelog that goes quiet while documentation keeps moving is
   the exact failure recorded as R29.
2. A version bump in `.claude-plugin/plugin.json`. The manifest version and
   the top changelog entry must agree — `tests/test_keel_phase0.py` asserts
   this, so drift breaks the build rather than shipping.

**Releases are cut from tags only** (R31). Nothing is published from a branch,
a local working tree, or a manual copy. The tag is the artifact's identity;
`keel survey --startup` compares the running version against the manifest so
that shipped-versus-source drift is visible in one line rather than discovered
months later.

Versioning is `MAJOR.MINOR.PATCH`. A change to any file contract — the event
contract in `hooks/keel_events.py`, the record schema in
`scripts/keel_records.py`, the arming file in `templates/keel-policy.md` — is
at least a MINOR bump and says so in its changelog entry.

## 2. Issue triage (R29)

Issues are triaged **weekly**. Triage means every open issue leaves the week
with a label, a decision, and — where the decision is "not now" — a stated
reason. Closing is a legitimate outcome; leaving an issue untouched is not.
The defect this prevents is a tracker where every issue ever filed is still
open, which is a tracker that tells nobody anything.

Vulnerabilities never enter this flow in public: they go through the private
channel in `SECURITY.md`.

## 3. Documentation counts (R15, R26)

No document states a count by hand. Counts of hooks, skills, agents, tests, or
tools are generated from source in CI and the build fails on drift. A README
number that disagrees with the code is a documentation defect of the same
severity as a code defect.

## 4. Registration ownership (R30)

> keel registers hooks through exactly one path at a time — the plugin
> manifest. `keel survey` reports every registration across global, project and
> plugin scopes; arming refuses only where another gate is armed in the same
> project.

Read the two halves separately, because their strictness differs on purpose:

- **Reporting is total.** Every registration keel can see — global
  `~/.claude/settings.json`, project settings, and plugin manifests — is listed
  by `keel survey`, whether or not it conflicts. Visibility is never the thing
  that is traded away.
- **Refusal is narrow.** Registered-but-disarmed observers coexist with keel
  without complaint. Arming refuses only where *another gate is armed in the
  same project* (for example a project carrying a foreign
  `.claude/POLICY.md`), and the refusal prints the migration step rather than
  ending in a dead end. Two armed gate stacks never run over one project.

keel itself never writes hook entries into global or project settings files. The
plugin manifest is the single registration path, which is what makes uninstall
a plugin removal rather than a hunt.

## 5. Reference integrity (R15, R18)

> Every citation resolves in-repo; every documented claim has an enforced or
> testable basis; documents and the changelog never contradict the tree.

A shipped file may cite only what a reader can open. Rule and decision
identifiers resolve in `docs/keel-rules.md`; paths resolve in the working tree;
a claim about behaviour names the file or the check that makes it true. A
reference to material that is not shipped is an unfalsifiable claim, and an
auditor is right to treat it as absent.

Enforced by `keel_checks --refs` in CI: unresolvable citations and dead intra-
repository paths fail the build on all three operating systems.

## 6. Governance changes

This file is policy-locked material once the kernel lands (Phase 1). Changing
it then follows `/keel:refit`: diff, explicit ratification by the owner,
version bump, changelog entry. Until the lock exists, the same procedure is
followed by hand.

## 7. Versioned law (T230/T320)

The arming file, `.keel/keel-policy.md`, names its own version in a
frontmatter `version:` line and carries an Amendment log table. A ratified
change to the file's text moves that line and adds a row to the log; there
is no other way to change what the policy says. `keel_checks --policy`
compares the staged tree against `HEAD` and refuses a commit that edits the
policy's text without moving its version — the check passes silently where
the file does not yet exist, so an adopter mid-`/keel:lay` is never failed
on a surface it hasn't reached. Nothing lands in the arming file except
through this procedure: propose the diff, get the owner's ratification,
bump the version, log the row.
