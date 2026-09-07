# published cut

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
