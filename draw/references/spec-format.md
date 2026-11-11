# The seed spec — what `draw.py new` reads

One JSON object. `code-mapper` returns it; the agent may also write it by hand for a board with no
code behind it (a plan sketch, a bug hypothesis). Every field not marked required may be omitted.

```json
{
  "title": "How a skill and its agents reach a session",
  "question": "what does ./workflow/install.sh write, where, and who reads it?",
  "mode": "as-is",
  "example": "the spec-code-reader agent, from agents/spec-code-reader.md to an Agent call",
  "lanes": [
    {"id": "repo", "label": "~/spiral — the source of truth"},
    {"id": "home", "label": "~/.claude — what a session reads"}
  ],
  "nodes": [
    {"id": "install", "label": "install.sh", "at": "workflow/install.sh:36", "lane": "repo"},
    {"id": "gen",     "label": "gen-agents.py", "at": "workflow/gen-agents.py:32", "lane": "repo", "kind": "touched", "step": 1},
    {"id": "agents_out", "label": "~/.claude/agents/<name>.md\n(tools+model added)", "lane": "home", "kind": "external", "shape": "store"},
    {"id": "session", "label": "a Claude Code session", "lane": "home", "kind": "external", "shape": "actor", "row": 3}
  ],
  "edges": [
    {"from": "install", "to": "gen", "label": "runs", "when": "install | uninstall"},
    {"from": "gen", "to": "agents_out", "label": "written with a GENERATED marker"},
    {"from": "session", "to": "agents_out", "label": "Agent(subagent_type=name)", "kind": "trace"}
  ],
  "notes": [
    {"text": "Why generated, not linked: a symlink cannot add frontmatter.", "near": "gen", "kind": "answer"}
  ],
  "omitted": [{"what": "merge-settings.py", "why": "hooks are a separate question"}]
}
```

## Fields

| Field | Required | Values | Rendered as |
|---|---|---|---|
| `title` | yes | ≤60 chars | 24 px heading at the top |
| `question` | yes | one line | grey subtitle |
| `mode` | yes | `as-is` · `plan` · `bug` | subtitle suffix; `bug` requires `example` |
| `level` | no | `system` · `code` | subtitle suffix. `system` boards carry a `tech` line per box and `detail` links down to code boards |
| `example` | bug: yes | the one concrete input carried through | subtitle |
| `lanes[]` | no | `id`, `label`, `boundary` (`process` · `network` · `trust`) | dashed column bands, label top-left with `· <boundary> boundary`; a node with no lane goes in a trailing band |
| `nodes[]` | yes, ≤12 | see below | boxes |
| `edges[]` | no | `from`, `to`, `label` ≤5 words, `when`, `kind`, `via` (`call` · `message`), `on_fail` | arrows with a bound label (`label` + `if when`); a `message` is dotted |
| `notes[]` | no | `text` ≤2 sentences, `near` node id, `kind` `answer`/`question`/`warning` | sticky in the right margin, dotted line to the node |
| `omitted[]` | no | `what`, `why` | not drawn; the agent mentions them in chat |

### A node

| Field | Required | Values | Effect |
|---|---|---|---|
| `id` | yes | slug, unique | handle `#id` in every later command; element id `n:id` |
| `label` | yes | ≤3 lines (`\n`), everyday words — see *Labels* below | line 1+ of the box text |
| `role` | system level | `person` `client` `service` `worker` `store` `queue` `cache` `external` | joins the technology line as `[role · tech]`; picks the shape (`store`/`queue`/`cache` hatched, `person` an ellipse) unless `shape` is given. Keep `role · tech` within the 34-character line budget |
| `tech` | system level | what it is made of / how it is reached | rendered as `[tech]` under the name (the C4 technology line) |
| `at` | yes unless `external`/`actor`/`new` | `path:line` relative to the repo | last line of the box text, shortened to the last two path segments; verified by `new --repo` |
| `lane` | no | a lane id | which band the box sits in |
| `kind` | no, default `unchanged` | `unchanged` `new` `touched` `removed` `failing` `external` | fill + stroke colour, dashed for `removed` |
| `shape` | no, default `box` | `box` rounded rectangle · `store` hatched square rectangle · `actor` ellipse | |
| `step` | plan only | int | black badge with the number at the box's top-left corner |
| `row` | no | int ≥0 | pins the box to that row (rows flow top→bottom); everything downstream moves below it |
| `detail` | no | slug of another board | the box links to `./<slug>.excalidraw` |
| `covers` | no | list of path globs (`draw/scripts/*`, `agents/*.md`) | the files this box stands for, beyond its `at`; `review` maps a change's files onto boxes through these |
| `unverified` | no | bool | box text gains a last line `UNVERIFIED`; `check` fails until it is cleared |

## System boards — the building blocks every box and arrow must name

A system board is only useful if a reader can see the design decisions in it, and those decisions
are made of a handful of basic ideas. Each one is a field, so it is drawn rather than implied, and
each comes with what it is allowed to get wrong. `draw.py new` warns (never fails) when a `level:
system` spec leaves one out.

| Idea | Field | Values, and what each may get wrong |
|---|---|---|
| **What kind of part is it?** | node `role` | `client` holds no data of record · `service` answers requests and keeps no state unless it owns a store · `worker` takes jobs from a queue or schedule, and nobody waits on it · `store` is durable and survives a restart · `queue` decouples a sender from a worker, so delivery can be late · `cache` may be stale and can be rebuilt · `external` is not ours to change · `person` |
| **Who waits on whom?** | edge `via` | `call`: the caller blocks, so a slow or down callee makes the caller slow or down · `message`: sent and not waited for, so ordering, duplicates and lost messages are the design's problem (drawn dotted) |
| **What happens when it fails?** | edge `on_fail` | one line: "10 s timeout, 3 retries, then the run is marked errored". Required in spirit on any `call` that crosses a `network` or `trust` lane |
| **Who owns the data?** | arrows into a `store`/`queue`/`cache` | every arrow *into* a store is a writer. One writer is an owner; two writers need a rule for which write wins, and the board should say it in a note |
| **What does a crossing cost?** | lane `boundary` | `process`: separate memory, so data is serialised · `network`: latency, timeouts and partial failure · `trust`: different permissions, so input crossing it must be checked |

`draw.py review --system` reads these fields back and flags the three trade-offs that are risky
unless someone chose them on purpose: a second writer to a store, a changed `call` across a
`network` or `trust` lane with no `on_fail`, and an unplanned `trust` crossing.

### Labels — the box says what the thing IS, not what the code calls it

A box whose label the reader cannot resolve is a paragraph in disguise. The `at` line already
carries the identifier; the label's job is the sentence a person would say out loud.

| ✗ | ✓ |
|---|---|
| `the exit row's verdict · _classify reads the SAME table job_runner logs to` | `how each job ended — one word from the scheduler, turned into "whose fault" by a 3-row table` |
| `child_sessions full-scans via scan_session_head` | `finding a report's child sessions — it read every event of every session` |
| `TuiArgs.resume is cloned into TabContext` | `a new tab re-runs the flags the process was started with` |

Test before writing the board: **would the reader have to open the file to know what the box is?**
If yes, the label is naming code instead of describing it.

- No bare function or field names as the subject of a line — `_classify`, `TuiArgs.resume`,
  `scan_index_prefix` go in `at`, or in an arrow label where they are the *value* that moves.
- No coined nouns the reader has not used — "exit row", "the projection", "the seam". If the
  concept needs a name, spell out what it is on first use.
- Numbers and real output beat adjectives: `455.03 ms -> 0.01 ms` and
  `| Git | v4.2.0-acme |` say more than "slow" or "leaky".
- The failing case is the best first line a box can have.

When a user draws a `question` note or an arrow at a box and asks what it means, that label failed
this test. Answer with `add note --as answer`, then fix the label — the next reader has the same
question.

### A box anchored in a changed file must be typed `touched`

The most common false `CHECK` from `draw.py review`, and it looks like a code problem rather than a
drawing one.

```
#middle   at: src/summarize.py:616   kind: unchanged      <- the PR changes summarize.py
                                                             -> "CHECK — 1 unplanned box touched"
```

`review` maps every changed file onto whatever boxes claim it (via `at` and `covers`). A box typed
`unchanged` / `failing` that sits in a file the change touches is reported `UNSPECCED`, even when
the change is entirely as planned. Four boxes on one file with mismatched kinds produce four
findings about nothing.

**The fix is almost never to retype the box** — it is usually there to say *"this part did not
move"*, which is true and worth saying. Move that onto an **arrow label** or a `note`, and delete
the box. Keep a box only when it is genuinely a distinct site the change touches.

| Symptom | What it actually means |
|---|---|
| `CHECK — n unplanned box(es) touched` and the boxes share one file | mismatched `kind`, not scope creep |
| `CHECK — m file(s) outside the board` | a real gap: usually a forgotten `docs` or `tests` box, or a missing `covers` glob |

### Colours (fill / stroke)

| kind | fill | stroke | meaning |
|---|---|---|---|
| `unchanged` | `#e9ecef` | `#868e96` | exists today, not touched |
| `new` | `#b2f2bb` | `#2f9e44` | the plan adds it |
| `touched` | `#ffec99` | `#f08c00` | exists, the plan changes it |
| `removed` | `#f8f9fa` | `#adb5bd` dashed, 60 % opacity | the plan deletes it |
| `failing` | `#ffc9c9` | `#e03131` | actual differs from expected here |
| `external` | `#a5d8ff` | `#1971c2` | outside this repo |

Arrow strokes: `unchanged` `#495057` · `new` green 3 px · `touched` orange 3 px · `removed` grey
dashed · `failing` red 3 px · `trace` blue 3 px. Notes: `answer` yellow · `question` blue ·
`warning` red. These are the same values `set --kind` writes and `diff` recognises when the user
recolours a box with Excalidraw's palette, so a recolour round-trips to a kind.

## Layout

Rows are computed as the longest path from any source (cycles are broken at the back edge),
`row` pins override upward, lanes are column bands, and boxes within a lane and row are ordered by
the average position of their predecessors. Every box is the same size, chosen from the longest
label (200–340 px wide). Arrows are straight, bound at both ends, and fan out ±14 px when several
join the same pair. On a re-run of `new` over an existing board, every box, lane and note that
still exists keeps the position it had — including positions the user dragged it to.

## What the agent stores on each element

Every element the agent draws carries `customData: {"by": "agent", "role": …, …}` — `role` is one
of `box`, `arrow`, `note`, `lane`, `badge`, `legend`; a `box` also keeps `key`, `label`, `at`,
`kind`, `shape`, `step`, `lane`, and `part` (the spec's system `role`, renamed so it cannot collide
with the element role); an `arrow` keeps `via` and `on_fail`; a `lane` keeps `boundary`. Excalidraw preserves `customData` through every edit, so a box
still knows its `path:line` after the user has moved, resized or recoloured it. `set` on a
user-drawn box adds this data (`"adopted": true`); from then on it is verified like any other.
