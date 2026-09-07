# keel plan-document contract

A session ledger is what the orchestrator writes before work starts and what
the stop gate reconciles against the audit log after it ends. This page is
the contract for one task line in that ledger — what it must state to be
worth writing, and to be checkable later without asking the author what they
meant.

The ledger template lives beside the policy file; this is the reference for
its content, not a restatement of the policy itself. What a status mark
(`[ ]`, `[x]`, `[~]`, `[!]`, `[?]`) means, and the routing law behind who runs
a task, are the policy's — see the project's `keel-policy.md`. This page is
silent on both.

## Every task carries

- **An identifier and a title**, on the line that opens the task: `Tn <title
  in a few words>`. The identifier is what a report, a decision record, or a
  later task cites — a name short enough to say out loud.
- **A Route**: who implements the task, and at which tier (`standard`,
  `deep`, `orchestrator`). Naming the route is this contract's requirement;
  which name maps to which agent is the policy's routing table, not this
  page's.
- **An Accept line**: the criteria that close the task. Every criterion is
  CHECKABLE — a command that exits with a known code, a count that matches, a
  state a reader can observe on disk or in a log. "Works well," "looks
  right," and "should be fine" are not criteria. "Seven checks green," "402
  tests OK," and "budget reading drops below 1188" are.

A task missing an identifier cannot be cited by anything written after it. A
task missing a Route has no one to do it. A task whose Accept line is not
checkable cannot be closed — only asserted, which is exactly the gap a ledger
exists to remove.

## No placeholders

A task body never carries a promise to decide later. The banned vocabulary,
verbatim:

- `TBD`
- `etc.`
- `handle appropriately`
- `as needed`
- `similar to the above`

Each one hides a decision the ledger should have made. If the scope is
genuinely open, say what is open and who resolves it — a named blocker is a
task; a shrug is not.

## Global constraints, stated once

A constraint that binds every task in the ledger — a file no task may touch,
an order two tasks must run in, a budget the whole session must respect — is
stated once, at the top of the ledger, before the task list. It is not
repeated inside each task it applies to, and no task's Accept line restates
it; repetition invites the two copies to drift apart, and then neither one is
the truth.

## A task that consumes another task's output names it

When a task's work depends on what an earlier task produced — a file it
writes, a decision it records, a return value the routing rules require to be
verified — the later task names the earlier task's identifier. "The
executor's earlier findings" is not a citation; "T22's review findings" is.
This is what lets a reader (or a checker) follow a dependency without
re-reading the whole session's history.

## What this contract does not cover

Status marks, the escalation ladder, who may write which files, and how a
plan is verified against the audit log are the gate's law, living in the
project's policy file and its lock. This contract is silent on all of it by
design: a ledger can satisfy this contract task-by-task in a project running
at any enforcement tier, including tier 0, where nothing blocks yet.
