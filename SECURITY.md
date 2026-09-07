# Security policy

## Reporting a vulnerability

Report vulnerabilities **privately**, through GitHub security advisories:
the repository's **Security** tab → **Report a vulnerability**. That channel
opens a private advisory visible only to the maintainer and to you.

**Do not open a public issue for a vulnerability**, and do not describe one in a
pull request, discussion, or commit message. Public issues are for ordinary bugs
and feature requests only; a vulnerability filed in public is disclosed by the
act of filing it.

If the advisory channel is unavailable to you, say so in a public issue **without
technical detail** — one line asking for a private contact route is enough.

## What to include

- The version of keel (`.claude-plugin/plugin.json` → `version`) and the harness
  version it ran against.
- Operating system and Python version.
- Reproduction steps, and the smallest input that triggers the behaviour.
- What an attacker gains: which file is read, written, or executed.

## Response

- Acknowledgement within 7 days.
- An assessment, with a fix or a rejection and its reason, within 30 days.
- Fixes ship in a tagged release with a CHANGELOG entry (see
  `docs/keel-governance.md`); the advisory is published once the fix is released.
- Credit is given in the advisory unless you ask otherwise.

## Scope notes

keel is pre-alpha (Phase 0). It makes no network calls, ships no telemetry, and
has no third-party runtime dependencies, so the supply-chain and exfiltration
surfaces are intentionally near-empty. The security-relevant surface is
therefore: hook execution, the policy lock, path handling, and anything keel
writes under a project's `.keel/` directory.
