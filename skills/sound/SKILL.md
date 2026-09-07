---
name: sound
description: Use before planning significant work, to interrogate the intent until shared understanding — recommended answers per question, facts looked up never asked, nothing proceeds unconfirmed.
disable-model-invocation: true
---

# sound — taking soundings before setting course

A plan written on top of a misunderstanding is a plan that fails later,
expensively. Sounding is the step before the plan: it maps what the intent
actually requires, settles every fact the tree already holds, and asks the
user only what only the user can answer. It never writes the plan itself —
that stays the ledger's job, taken up only once sounding has stopped and been
confirmed.

## The five steps

1. **Map the decision tree.** Break the intent into what must be decided and
   what each decision depends on. A choice that depends on another is a
   child in the tree, not a peer to ask about yet.
2. **Facts are found, never asked.** Anything discoverable in the
   environment — code, records, existing documentation — is not a question
   for the user. Dispatch it to the `fast` routing tier (the researcher
   agent, `agents/researcher.md`, read-only by design) or look it up
   directly. The user is never asked a question the repository can already
   answer.
3. **Decisions are the user's, asked in frontier rounds.** A round poses
   every question whose prerequisites are already settled — never a serial
   one-at-a-time crawl, and never every possible question dumped at once
   before earlier answers could have closed some of them off. Each question
   ships with a recommended answer and its one-line reason, so agreeing is
   one word, not a re-derivation.
4. **Recompute the frontier and repeat.** Every round's answers can settle or
   reshape what depends on them; recompute which questions are now
   answerable and pose the next round. Continue until the frontier is empty
   — every decision made, every fact established.
5. **Stop at the gate.** Sounding never writes the plan. It ends by
   presenting the shared understanding — decisions made, facts established,
   open risks named — and stops for the user's confirmation. The plan ledger
   is written only after that confirmation, under plan-before-write as
   always, and it cites this sounding as its basis.

## What not to do

Never act on an answer that has not been given yet — a recommended answer is
a proposal, not a default to proceed on. Never fold two independent
decisions into one leading question; each question in a round decides one
thing. Never present a recommendation as though it were already decided —
the user's confirmation is what makes it a decision. A question the user
declines to answer is recorded open, not silently answered by the
recommendation. Sounding is advisory throughout: it never invokes
enforcement itself, and it never substitutes its own confirmation for the
gates that already exist.
