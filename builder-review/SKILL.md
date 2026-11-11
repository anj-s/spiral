---
name: builder-review
description: >
  The architect's review of a PR, branch or commit range: two pictures and a decisions table. A
  system board shows the running parts in systems-design terms (what kind of part each is, who
  waits on whom, who owns each store, what each boundary costs) and which of them the change
  touched; a code board shows the files. Then every design decision the change took, what it was
  chosen over, and what it buys and costs, with the risky trade-offs flagged. Last, whether the
  change touched exactly what the plan said. Use whenever the user asks to review a PR
  architecturally, asks "what did this change touch", "what are the trade-offs", "why was it built
  this way", "did the agent do the right thing", "does this match the plan / spec / design", or
  before /review on any PR. Also when a PR feels bigger than its description.
---

# builder-review

`/builder-review <PR | branch | base..head>` → a system board and a code board with the change
coloured in, a table of the design decisions it took and what each one trades, and one verdict
line on whether it stayed on the plan.

Not this skill: whether each line is correct, handles its edge cases, or is tested. That is
`/review`, which runs this first.

## What a builder's review is for

Someone reading a PR can see what lines changed. What they cannot see is the shape of the system
around those lines, and the choices the change made about that shape. This review answers three
questions, in this order:

1. **What does the system look like, and what did this change touch?** Two pictures: the system
   board (the separately running parts) and the code board (the files inside them), with the
   change coloured in.
2. **What did it decide, and what does each decision trade?** A table of every design decision,
   the alternative it was chosen over, and what it buys and costs, in the terms the system board
   is drawn in. The few trade-offs that are risky unless chosen on purpose are flagged.
3. **Did it touch what the plan said, and nothing else?** A set comparison of the changed files
   against the plan board: `RIGHT THING` or `CHECK`, with the reasons named.

The third is mechanical and fast. The first two are why a builder reads this instead of the diff.

## The five building blocks every system board names

A system diagram that only shows boxes and arrows hides the decisions. These five ideas are the
vocabulary of systems design, and each one is a field on the board, so it is drawn rather than
implied. Each comes with what it is allowed to get wrong. Full definitions are in
[`draw/references/spec-format.md`](../draw/references/spec-format.md#system-boards--the-building-blocks-every-box-and-arrow-must-name).

| Question | Field | Why a reviewer cares |
|---|---|---|
| What kind of part is each box? | `role`: client, service, worker, store, queue, cache, external, person | it says what the part may get wrong: a cache may be stale, a queue may deliver late, a client holds no data of record |
| Who waits on whom? | arrow `via`: `call` (solid) or `message` (dotted) | a call couples two parts' availability: if the callee is slow or down, so is the caller. A message decouples them and moves the problem to ordering and lost messages |
| What happens when a call fails? | arrow `on_fail` | a call across a network with no timeout turns a slow neighbour into a hung process |
| Who owns each piece of data? | the arrows into a store | one writer is an owner. Two writers need a rule for which write wins |
| What does crossing a lane cost? | lane `boundary`: process, network, trust | serialising the data, a hop that can be slow or fail, or input that must be checked |

## Steps

1. **Resolve the range.** A PR number → its base and head, and the changed files. Use whichever is
   available, in this order: the GitHub MCP tools (`pull_request_read` with `get` for base and head
   and `get_files` for the list, which works with no clone), `gh pr view <n> --json
   baseRefName,headRefName` plus `gh pr diff --name-only`, or plain git when the branch is local.
   With a clone, `git fetch origin pull/<n>/head:pr-<n>` gives real refs; without one, pass the
   API's file list straight to `--files` and skip `--base/--head`. Say how many commits are in range.

2. **Find the plan and the decisions**, before reading the diff. A plan reverse-engineered from
   the code always passes.

   | Situation | The plan is | The decisions come from |
   |---|---|---|
   | the work has a spec in the store | its plan board, `<slug>.excalidraw` beside the spec (via `~/.local/state/workflow/active-spec` or `spec-locator`) | the spec's `## Decisions`: `Options considered`, `chose A over B — because`, `rejected:`, `ASSUMED:` |
   | someone else's PR, no spec (**the common case**) | **the PR's own description**: dispatch `code-mapper` with `mode=plan`, `level=code`, `{{plan}}` = the PR body verbatim, `{{task_brief}}` = "did this PR change what its description says?", then `draw.py new`. Every box is something the description promises | what the description says it chose and why; then step 5 names the choices the diff made without saying so |
   | no spec and a description too thin to draw from | nothing: map instead (`mode=as-is`) and let `review` report `MAP` | step 5, all inferred |

   A board drawn from a PR description goes to
   `$SPEC_STORE/projects/<repo>/boards/pr-<n>-<slug>.excalidraw` and is worth keeping: it is what
   the author claimed, at review time.

3. **Draw or refresh the system board.** Use the spec's `<slug>.system.excalidraw` when it exists.
   Otherwise dispatch `code-mapper` with `level=system` and `mode=as-is` on the base, so the picture
   is the system *before* the change, and write it beside the plan board. Either way, run
   `draw.py new` and read its `WARN` lines: each is a building block the board leaves unsaid (a box
   with no role, an arrow that does not say whether the sender waits, a lane that does not say what
   it separates). Fill them in from the code before reviewing, because the design flags in step 4
   are computed from them.

4. **Run the comparison.**
   ```sh
   D=~/spiral/draw/scripts/draw.py
   python3 $D review $PLAN --repo "$(git rev-parse --show-toplevel)" --base $BASE --head $HEAD --system $SYSTEM
   python3 $D review $PLAN --repo . --files <paths from the API> --system $SYSTEM   # no clone
   ```
   It prints the verdict, which running parts were touched, every boundary a touched arrow crosses
   (with what the crossing costs and whether the sender waits), and any `DESIGN FLAG`. Three kinds
   of file are set aside by default (`DEFAULT_IGNORES` in `draw.py`, printable with
   `--list-ignores`): repo plumbing (`.gitignore`, CI workflows), lockfiles, and generated or
   vendored trees. They are counted in the verdict and named in the report, never dropped
   silently. PR and issue templates, `CODEOWNERS` and the rest of `.github/` are deliberately not
   ignored, because they decide how the team works. `--ignore <glob>…` adds this repo's own
   generated paths.

5. **Write the decisions table.** One row per design decision the change took: every entry from
   step 2's source, then every choice the diff made that nobody wrote down. The usual unwritten
   ones are a new arrow (a new dependency), a `message` where a `call` was (or the reverse), a new
   writer to a store, a new store or cache, and work moved from one running part to another. Look
   for them on the system review board, where the touched arrows are coloured.

   | Decision | Chosen | Instead of | Buys | Costs | Source |
   |---|---|---|---|---|---|
   | where the retry lives | in the worker, 3 tries with backoff | in the queue's redelivery | the API returns at once | a crash mid-retry loses the job | PR body |
   | who writes the config file | the live session, when /config finishes | a separate settings service | no new process to run | replay must never call the writer | inferred from `persistence.rs:21` |

   | Rule | Because |
   |---|---|
   | every Buys and Costs names a box or arrow on the board and one of the building blocks: availability (who fails together), latency, consistency (can a reader see an old value), durability (what survives a restart), ownership, coupling, trust, operating cost | "more robust" or "simpler" cannot be checked against the picture; "the API no longer waits on the card processor" can |
   | an unwritten decision says `inferred from <path:line>` | the reader must know nobody chose it on the record |
   | a decision with no alternative anyone could name gets `Instead of: —`, and that is itself worth one line | a choice with no alternative considered is how an unchosen design ships |
   | each `DESIGN FLAG` from step 4 becomes a row, or joins the row it belongs to, with **flag** in its Costs | the three risky patterns (a second writer to a store, a changed call across a network or trust lane with no failure behaviour, an unplanned trust crossing) are fine only when chosen on purpose, and the table is where "on purpose" is written down |

   Describe trade-offs; judge only the flagged ones. A trade-off that is not flagged is the
   author's call, and the review's job is to make it visible.

6. **Read the red.** For every UNSPECCED box, file outside the board and unplanned crossing, read
   `git diff <base>..<head> -- <file>` (or the API's patch) and write **one line**: what the hunk
   does, and whether it *belongs in the plan*, should be *split out*, or shows *the board is missing
   a box*. Docs entries, ignore files and test fixtures the description forgot are usually the
   third. Say so and move on: the finding is that the description was incomplete, not that the PR
   was wrong.

7. **Show it.** Serve both review boards, each on its own free port (8766 is often another
   session's, and `draw.py serve` takes no `--port`):
   ```sh
   S=~/spiral/draw/scripts/draw_server.py
   free() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
   PS=$(free); python3 $S <slug>.system.review.excalidraw --port $PS &   # background; exits on Send
   PC=$(free); python3 $S <slug>.review.excalidraw --port $PC &
   ```
   Before giving the two URLs, `curl -s http://127.0.0.1:$PS/api/scene` and check its labels are
   that board's, since an HTTP 200 alone proves nothing. Restart on the same port so the open tab
   reconnects. Send writes the PNG. In chat, use the output contract:
   **What's wrong** is the verdict line, the red items and the flagged decisions; **The fix** is
   update the description, the spec and board, or trim the PR; **How it works** is the decisions
   table, at most five rows, with the rest in the file.

8. **Never on the PR.** Nothing from this review goes on a PR: no comment, no verdict, no board link,
   no decisions table. Serve both boards locally, put the decisions table on the board itself, and
   give the URLs in chat. Never approve or request changes on the user's behalf.

## Worked example — a flag the board caught

This system board was drawn for a PR that made a terminal app save `/config` answers to
`~/.config/<app>/config.toml`. Here it is with the building blocks filled in (the live app and a
replay command are clients, the config file and the event store are stores, and both lanes are
process boundaries), reviewed against a change that touches the live app, the replay command and
the config writer:

```
CHECK — 2 unplanned box(es) touched: #replay, #toml
review board: config-persists-960.review.excalidraw
system board: 3 running part(s) touched → config-persists-960.system.review.excalidraw
  boundary disk → you: #toml → #tui (process boundary · call) — UNPLANNED crossing
  boundary you → disk: #tui → #toml (process boundary · call) — UNPLANNED crossing
  boundary you → disk: #replay → #toml (process boundary · call) — UNPLANNED crossing
  DESIGN FLAG: 2 writers to #toml (#replay, #tui), and this change touches one: which write wins, and who is the owner?
```

The flag is the real design question in that PR. A replay rebuilds settings by calling the same
function the live app now uses to save them, so a write placed there would overwrite the user's
file. The decisions row that answers it:

| Decision | Chosen | Instead of | Buys | Costs | Source |
|---|---|---|---|---|---|
| who owns `config.toml` | only the live app writes it, and only when /config finishes; a replay reads the event store | a precedence rule between the two writers | one owner, so no rule is needed | **flag**: replay shares the setter, so the owner rule lives in one call site, not in a type | the board's own note, `persistence.rs:21` |

## Reading the verdict

| Line | Means | Do |
|---|---|---|
| `RIGHT THING — n files all land on planned boxes` | every changed file belongs to a green, yellow or dashed box | one line in chat; on to the decisions table, then `/review` |
| `… still to build: #a, #b` | planned boxes this change did not reach | fine for one step of a plan; a *finished* PR with missing boxes is incomplete, say so |
| `CHECK — k unplanned box(es) touched` | a grey box changed | step 6; the usual answers: the plan missed it (log drift in the spec, recolour the box) or the PR wandered (split) |
| `CHECK — m file(s) outside the board` | no box stands for them | step 6; if they are real parts of the mechanism, the board is missing a box: add it with `draw.py add box … --covers` and re-run |
| `boundary A → B (<boundary> · <via>): UNPLANNED crossing` | two touched running parts in different lanes, files not all planned | the loudest finding: a new network hop, serialisation or permission nobody designed. Blocker until drawn and agreed |
| `DESIGN FLAG: …` | a risky trade-off: a second writer, an unguarded call across a network or trust lane, an unplanned trust crossing | a decisions-table row marked **flag**; fine once the table says it was chosen on purpose and why |
| `MAP — n running parts touched` | no plan existed | report the parts, crossings and decisions; suggest `/slice` before the next change in this area |
| `(set aside: n plumbing/lock/generated file(s))` | matched the ignore list | listed by name under the verdict; mention one only if it looks hand-edited or surprising |

A change that lands entirely on the board but reads wrong in the hunks is `/review`'s job. A change
that reads fine but lands off the board, or makes a trade-off nobody chose, is this skill's job.
Both have to pass.

## Why the boxes carry `covers`

A box stands for its `at` file plus the `covers` globs on it (`agents/*.md`, `src/worker/**`). The
comparison is only as good as the coverage: a file no box claims is reported *outside*, which is
either scope creep or a hole in the board. Both are worth a line. `code-mapper` writes `covers` on
every box it draws; `draw.py set #box --covers …` fixes one by hand.

## Degraded modes

| Missing | Do |
|---|---|
| `gh` | the GitHub MCP tools (`pull_request_read`), else ask for base and head |
| a local clone | take the file list from the API and pass it to `--files`; the boundary check and flags still work, because they need boards, not the clone |
| a plan board | draw one from the PR description (step 2), else the `MAP` path |
| a system board | draw one (step 3). If that is impossible, give the code-level verdict only, say the boundary check and flags were skipped, and write the decisions table from the text alone |
| the building blocks on an old system board | fill them in (`draw.py set #box --role …`, or edit the spec and re-run `new`); until then the flags cannot fire, so say which are missing |
| a browser for the user | the table in chat carries the same facts; the PNG comes on the next Send |

## Rules this skill exists to enforce

1. The plan board is read, never written, by a review; drift is logged in the spec's Drift log.
2. Every system box says what kind of part it is, every arrow whether the sender waits, and every
   lane what it separates. A board missing one says so.
3. Every design decision names what it was chosen over and what it buys and costs on the board. An
   unwritten one is marked `inferred`.
4. Trade-offs are described; only the three risky patterns are judged, and each is fine once the
   table records it as chosen on purpose.
5. Every red item gets one line of judgment from the diff, not from the file name.
6. An unplanned boundary crossing blocks. Everything else is a conversation.
7. No plan board is itself a finding; say it.
8. A plan drawn from a PR description is drawn **before** the diff is read.
9. Nothing is set aside silently: ignored files are counted and named.
10. The skill reports; the human approves.
