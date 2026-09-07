#!/usr/bin/env python3
"""BL51: the plan-file line's enforcement claim, read at the effective tier.

Contract
--------
Reads   : ``hooks/keel_session.injection_line`` directly, against real
          arming files this test writes into a scratch project - the same
          predicate (``armed_for_reminders``) the lock-line orientation
          already asks, per BL12's precedent.
Emits   : unittest results only.
Writes  : nothing outside temporary directories it creates and removes.

Failure policy
--------------
FAIL-CLOSED: an environment that cannot run a check fails the check rather
than skipping it.

Constraints
-----------
Python 3.10+, standard library only. Every file operation names its
encoding.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "hooks"))

import keel_session  # noqa: E402


def arm(project: Path, *, tier: int) -> None:
    """Write a minimal arming file at ``tier``."""
    (project / ".keel").mkdir(parents=True, exist_ok=True)
    (project / ".keel" / "keel-policy.md").write_text(
        f"---\ntier: {tier}\n---\n", encoding="utf-8"
    )


#: Words the below-tier claim must not say. T603's review finding: "observe
#: and log rather than enforce" told the model its writes were being logged
#: when no code path records them. At tier 0/1 ``keel_gate.run`` returns an
#: allow, and ``_audit`` runs only under ``if verdict.blocking`` - so an
#: ordinary write leaves no audit line, and capture watches delegation tools,
#: not file writes. Every case below asserts against the CONSTANT, which is
#: what lets a rewording drift silently; these two literals are the one place
#: a literal is the point, because they are the claim that must never return.
#: A blacklist cannot tell an assertion from a denial, so the constant is free
#: to say "none records one" - what it may not do is name watching or logging.
FORBIDDEN_IN_THE_BELOW_TIER_CLAIM = ("log", "observ")


class TestInjectionLineReadsTheEffectiveTier(unittest.TestCase):
    """BL51: the first sentence keel says to an adopter must not claim
    enforcement where nothing enforces."""

    def assertClaimsNoWriteTrail(self, line: str) -> None:
        """The below-tier claim promises no observation and no per-write record.

        Asserted on the WHOLE injected line, not just the constant: a future
        sentence added anywhere in the injection could reintroduce the same
        overclaim, and the model reads the line, not the constant.
        """
        lowered = line.casefold()
        for word in FORBIDDEN_IN_THE_BELOW_TIER_CLAIM:
            self.assertNotIn(
                word,
                lowered,
                f"the below-tier line claims a write trail via {word!r}; "
                f"nothing records an ordinary write at tier 0/1",
            )

    def test_tier_2_claims_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            line = keel_session.injection_line("abcdef12", cwd=project)
        self.assertIn(keel_session.GATES_ENFORCE_CLAIM, line)
        self.assertNotIn(keel_session.GATES_NOT_ENFORCED_CLAIM, line)

    def test_tier_1_the_default_does_not_claim_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=1)
            line = keel_session.injection_line("abcdef12", cwd=project)
        self.assertIn(keel_session.GATES_NOT_ENFORCED_CLAIM, line)
        self.assertNotIn(keel_session.GATES_ENFORCE_CLAIM, line)
        self.assertClaimsNoWriteTrail(line)

    def test_tier_0_does_not_claim_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=0)
            line = keel_session.injection_line("abcdef12", cwd=project)
        self.assertIn(keel_session.GATES_NOT_ENFORCED_CLAIM, line)
        self.assertNotIn(keel_session.GATES_ENFORCE_CLAIM, line)
        self.assertClaimsNoWriteTrail(line)

    def test_no_arming_file_does_not_claim_enforcement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".keel").mkdir(parents=True, exist_ok=True)
            line = keel_session.injection_line("abcdef12", cwd=project)
        self.assertIn(keel_session.GATES_NOT_ENFORCED_CLAIM, line)
        self.assertClaimsNoWriteTrail(line)

    def test_no_cwd_the_historic_signature_does_not_claim_enforcement(self) -> None:
        # A caller who never asked about tiers gets the fail-closed answer,
        # not the historic (unconditional) claim - "cannot tell" and "not
        # enforcing" read the same way here.
        line = keel_session.injection_line("abcdef12")
        self.assertIn(keel_session.GATES_NOT_ENFORCED_CLAIM, line)
        self.assertClaimsNoWriteTrail(line)

    def test_keel_gate_off_does_not_change_the_claim_at_tier_2(self) -> None:
        """Pinned against the lock line's own precedent
        (``_effective_lock_state``): ``KEEL_GATE`` is reported at its raw
        value on the switches line and folded into no tier predicate here
        either, so a tier-2 project's claim is unchanged by the switch."""
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            arm(project, tier=2)
            with patch.dict(os.environ, {"KEEL_GATE": "off"}):
                line = keel_session.injection_line("abcdef12", cwd=project)
        self.assertIn(keel_session.GATES_ENFORCE_CLAIM, line)


if __name__ == "__main__":
    unittest.main()
