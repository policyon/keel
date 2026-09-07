---
name: log
description: Use when work worth remembering has just been done, or at a stopping point, to distill this session's observations into knowledge records and rebuild the search index.
---

# log — write the voyage into the ship's log

Distillation is yours: keel captures mechanically and makes no model calls of
its own. You read the queue, decide what is worth keeping, and write records.

## The five steps

1. **Read the queue since the watermark.** The queue is
   `.keel/queue/keel-observations.jsonl` (one JSON object per line, oldest
   first). The watermark is `.keel/queue/keel-log-watermark.txt`, holding one
   ISO-8601 timestamp: skip every line whose `ts` is not newer than it. No
   watermark means read the whole queue.
2. **Decide what is a fact worth keeping.** Keep decisions, constraints,
   defects and their causes, and anything a future session would otherwise
   have to rediscover. Drop routine edits, retries, and anything already
   written down. Silence is a legitimate outcome: an empty queue, or a queue
   of noise, produces no records and you say so.
3. **Write one record per fact** into `.keel/knowledge/`, filename
   `<identifier>.md` where the identifier is the record's `name`. The
   frontmatter schema is enforced, not suggested — see
   `references/keel-record-schema.md` for the fields and
   `references/keel-worked-example.md` for a complete record built from a
   queue line. Rules that decide the shape:
   - **One fact per record.** Two facts are two files; a record that needs
     "and" in its description is two records.
   - **Link related records** by identifier in the body, so retrieval can walk
     from one to the next.
   - **Never restate what a file says.** Cite the path instead.
   - Content the user marked `<keel-private>` never reaches a record — it was
     already dropped at capture, and it must not be reintroduced from memory.
4. **Check and derive.** Run both, in this order:
   - `python scripts/keel.py records --dir .keel/knowledge`
   - `python scripts/keel.py index rebuild`
   A schema finding is a defect in the record you just wrote: fix it and run
   again. Do not proceed with a failing check.
   (Installed as a plugin, the script is
   `"$CLAUDE_PLUGIN_ROOT/scripts/keel.py"`.)
5. **Advance the watermark and report.** Write the `ts` of the last queue line
   you read into `.keel/queue/keel-log-watermark.txt`, then report three
   numbers and nothing else: observations read, records written, records the
   index now holds.

## What not to do

Do not summarise the session for the user here — that is a hand-off, not a
log. Do not edit records you did not just write. Do not delete the queue: it
is append-only, and the watermark is what makes re-reading cheap.
