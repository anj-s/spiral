---
name: draw
description: >
  Draw with the user on a shared Excalidraw board instead of writing prose or a long spec:
  how the system works today, what a plan or the agent's next change will touch, or the path
  a bug takes. ≤12 boxes, every box a real file, process or store with a path:line, one colour
  per meaning. The user draws and explains in the browser; the agent reads the board back
  (their boxes, arrows, circles, questions) and draws its answer into the same file. Use
  whenever the user asks how something works, what a change, plan or spec will touch, why
  something failed, says a spec or plan is too long to follow, asks for a diagram, picture,
  figure, architecture or system view, mentions Excalidraw or a whiteboard, says draw, sketch
  or show me, or before /implement on a slice so the delta is seen before it is built.
---

# draw

`/draw <question>` → a board in `$SPEC_STORE/projects/<project>/boards/`, open in the browser, that the
user and the agent both draw on until the question is answered. Two levels, drawn in this order:

| Level | File | A box is | First question it answers |
|---|---|---|---|
| **system** (C4 container level) | `<slug>.system.excalidraw` | a separately running or stored thing, with its `[role · technology]` line: client, service, worker, store, queue, cache, external system or person. Every arrow says whether the sender waits (`call`, solid) or not (`message`, dotted) and what happens when a call across a network fails; every lane says what it separates (process, network, trust) | which running parts are involved, who waits on whom, who owns each store, and what does crossing each boundary cost? |
| **code** (C4 component/code level) | `<slug>.excalidraw` | a file at `path:line`, the data and logic inside one or two system boxes | which files, in what order, and what flows between them? |

The system fields and what each is allowed to get wrong are in [`references/spec-format.md`](references/spec-format.md#system-boards--the-building-blocks-every-box-and-arrow-must-name).
A system box links down to its code board (`detail`). Draw the system board once per spec; draw a
code board per slice. `/draw how does X work` starts at whichever level the question is asked at and
offers the other.

Not this skill: a diagram nobody will draw on. A one-off ASCII sketch in an answer is `/talk-like-me`.

## The loop

```
 round 1                                   every later round
 ───────                                   ─────────────────
 question ──▶ code-mapper reads the code   user draws / circles / writes on the board
              (path:line on every box)       and presses  Send to Claude  (or just says so in chat)
                  │                                   │
                  ▼                                   ▼
          draw.py new  ──▶ board.excalidraw ◀── draw.py diff      "what did they draw, near what"
                  │                                   │
                  ▼                                   ▼
          draw_server.py, free port (bg)    answer IN CHAT (short) and ON THE BOARD:
          the browser opens the board         draw.py add note | add box | add arrow | set | rm
                  │                                   │
                  ▼                                   ▼
          "look at #gen first — is         serve again, same port ──▶ the open tab merges the change,
           this the box you meant?"         the user's unsaved strokes survive
```

Two scripts next to this file do all the file work; never hand-edit the JSON.

| Script | Role |
|---|---|
| `scripts/draw.py` | the agent's **eyes and hands**: `new` `describe` `diff` `add` `set` `rm` `phase` `check` `review` |
| `scripts/draw_server.py` | the **viewer**: real Excalidraw on one file, autosave, live-merge of agent writes, Send to Claude, PNG/SVG export |

## Three questions, three boards

| The user asks | Mode | Boxes | Colour that carries the answer | The first thing they should see |
|---|---|---|---|---|
| how does X work? | `as-is` | the files/processes X runs through, one lane per process or host | grey = exists · blue = outside the repo | the box where X starts and the arrow out of it |
| what will this change / plan / spec touch? | `plan` | the as-is boxes **plus** the plan's | green = added · yellow = changed · dashed = removed · badge = build step | the green and yellow boxes; everything grey is "not this PR" |
| why did X fail? | `bug` | the boxes one concrete request walked through | blue arrows = its path · red box = where actual ≠ expected | the red box and a note: *expected … / actual …* |

The mode is a colour convention, not a different tool. A plan board starts as the as-is board and gets
recoloured; a bug board is the as-is board with one request traced across it.

## Vocabulary — what makes a board readable

| Rule | Because |
|---|---|
| **≤12 boxes.** More → an overview board plus a `detail` board per box that needs opening up | a reader holds one screen; the 1,000-line spec problem is 60 boxes flattened into prose |
| **A box is something you can open**: a file at `path:line`, a process, a store, a person or service outside the repo | a box named "validation layer" or "the projection" is a paragraph in disguise (`/talk-like-me` rule 0) |
| Every box the agent draws carries `at: path:line`, verified to exist (`new --repo`, `check --repo` fail otherwise) | a board of guesses teaches the wrong system faster than prose does |
| **An arrow is a verb carrying the thing that flows**, ≤5 words, and its colour says `data` or `logic` | "uses", "depends on" tell the reader nothing about what to look for in the code |
| **One colour means one thing**, on every board. The legend is rebuilt from the live board on every write (`save` calls `rebuild_legend`) — never hand-maintain it, never hand-edit it | the user should never have to ask what yellow means, and a legend naming a colour nobody uses is worse than none: it is trusted and misread |
| **Lanes = process or host boundaries** | crossing a lane is where the interesting bugs and latency live |
| **One worked example carried through** (`example:`), mandatory on a `bug` board | "a request" is abstract; "PR #880's push event" can be traced |
| Step badges (①②③) only on a plan board, one per build step, on the box that step switches on | the build order becomes visible; step 1 must have a badge on something a user can see run |

### A box says what the code DOES; the location goes in brackets

A box label is plain English describing the functionality, readable by someone who has never opened
the file. The code location is a **reference the reader pulls up when they want it**, so it is
bracketed and last — `draw.py` renders the `at` field as `[llm_call/summarize.rs:96]` automatically.
Add the function name in brackets on the label's last line when the file holds several.

| Instead of | Write |
|---|---|
| `summarize.rs` / `summarize_span` / *(the summarizer, unchanged)* | ask the model to rewrite / the oldest messages shorter / `[summarize_span]` / `[llm_call/summarize.rs:96]` |
| ADVISORY. Returns `Option<String>`; `None` on failure, empty or interrupt. | Makes a SECOND, separate call to the same model, saying: here is the oldest stretch of this conversation, write it back shorter. It is allowed to come back empty — that is not an error. |
| AUTHORITATIVE. The durable half both triggers share: `text = summary.unwrap_or_else(plan.digest)`, stage blob, emit, spend one of 3. | Takes that shorter text — or, if the model came back empty, a plain mechanical digest — and actually swaps it in for the old messages, writing one record of the swap. |

Five tests, applied to every label, note and arrow before the board is served:

| Test | The failure it catches |
|---|---|
| **Read it aloud.** If it is not a sentence, it is not an explanation | a signature pasted where the description goes |
| **No word you coined.** ADVISORY, "the durable half", "the projection" | a label invented for the board teaches nothing (`/talk-like-me` rule 0) |
| **No identifier used as English.** `unwrap_or_else`, `Option<String>`, `ContextOverflow` may name a thing, never carry the verb | the reader has to decompile the label to read it |
| **Say what it does, then what it is allowed to get wrong** | "it is allowed to come back empty — that is not an error" is the line that stops the next question |
| **Two boxes that touch: say which one is in charge** | "the other box only supplies the words" answers *is there a relationship between them* before it is asked |

Nothing is lost to precision: the bracketed `path:line` is on the box and the identifier is one line
above it. When the user asks a box to be *clearer*, they are asking for this — not for more detail.

### An arrow is either data or logic, and the colour says which

**Box colour says what the plan did to it. Arrow colour says what moves along it.** Every arrow on
an `as-is` or `plan` board is one of two kinds:

| Kind | Colour | Means | Label reads like |
|---|---|---|---|
| `data` | teal, solid | something is **carried**: a value, an event, a payload, a file | "hands over the shorter text", "writes settings.json", "ToolCallCompleted" |
| `logic` | purple, dashed | **control only**, nothing is carried: a call, a branch, a decision | "asks for a shorter version", "tells it to do the swap", "retries the call" |

The test: *if you deleted the arrow, would a value go missing, or only an instruction?* Missing value
→ `data`. Missing instruction → `logic`. An arrow that carries a payload **and** transfers control is
`data` — name the payload in the label.

`trace` (blue) and `failing` (red) still own the `bug` board and outrank the flow colour on it.
`new` / `touched` / `removed` arrow colours remain for a plan that adds or deletes a whole hop, but
they are no longer the default: the plan's delta is already legible on the boxes.

Colours: `unchanged` grey · `new` green · `touched` yellow · `removed` dashed grey · `failing` red ·
`external` blue. Arrow kinds add `data` (teal, something is carried), `logic` (purple dashed, control
only) and `trace` (blue, the worked example's path). Full field list in
[`references/spec-format.md`](references/spec-format.md).

### Text must never overlap a box — you do the wrapping, the layout will not

`draw.py` does **not** re-wrap a box label. It splits your `label` on the `\n` you wrote, appends the
bracketed `at` line, measures the longest line, and clamps the box to `BOX_W_MAX = 340 px`
(`draw.py:80`, `:528`). A line needing more than that does not widen the box and does not wrap —
**it spills across the border and over whatever sits next to it.**

The budget, at `FS = 16` and `CHAR_W = 0.56`: `(340 - 32) / (16 x 0.56)` = **34 characters per line**.
Write <= 34, break the line yourself, and count the bracketed `at` line as one of them.

| Rule | Because |
|---|---|
| **<=34 characters per label line**, your own `\n` between them | past that the text leaves the box; nothing wraps it for you |
| **Keep line lengths even across the whole board** | every box is one uniform size taken from the *longest* line anywhere (`:528`), so a single 34-char line widens all twelve |
| **Keep line counts even too** | height is the *largest* line count anywhere (`:530`), so one four-line label makes every box four lines tall |
| **3 label lines plus the `at` line is the ceiling** | beyond that a box outgrows its row and the arrows into it start crossing neighbours |
| **Short arrow hops.** An arrow's label sits at its midpoint and is *not* collision-checked | an arrow spanning three rows drops its text straight onto whatever box lies between |

Boxes themselves cannot collide — they sit on a grid — and notes push each other down until they are
clear. **Only label text and arrow-label text can land on top of something.**

Measure it; do not eyeball it. Before serving:

```sh
python3 ~/spiral/draw/scripts/overflow-check.py <board>.excalidraw
```

Silence means every line fits; otherwise it names each line and the pixels it overruns by. If a box
genuinely needs more room, **split it into two boxes** — the cap exists because a box needing 40
characters is a paragraph asking to be a second box.

### The legend is never stale

`save` rebuilds it on every write, so `add`, `set`, `rm` and `phase` all refresh it, not just `new`.
It lists exactly the box kinds and arrow kinds present at that moment: draw the first `logic` arrow
and `LOGIC` appears; delete the last `failing` box and `failing` disappears. Verify it the same way
anything else is verified — read it back, do not assume:

```sh
python3 - <<'EOF'
import json
s = json.load(open("<board>.excalidraw"))
print([e.get("text") for e in s["elements"]
       if str(e.get("id","")).startswith(("legendt:", "legendlt:"))])
EOF
```

A save from inside the browser does not run this, so re-run any `draw.py` write after the user has
been editing if the legend looks behind.

## Round 1 — seed the board from the code

1. Dispatch `code-mapper` with `{{mode}}` = as-is | plan | bug, `{{level}}` = system | code, `{{task_brief}}`
   = the user's question verbatim, `{{repo_path}}` = `git rev-parse --show-toplevel`, `{{plan}}` = the
   spec's Build order / the plan you are about to execute / the bug report — or `(none)`. It returns the
   spec JSON. For a new spec run it twice: `system` first, then `code` for the boxes the slice touches.
2. Save it, then:
   ```sh
   D=~/spiral/draw/scripts/draw.py
   B=$SPEC_STORE/projects/<project>/boards/<slug>.excalidraw
   python3 $D new spec.json $B --repo "$(git rev-parse --show-toplevel)"     # fails on >12 boxes or a path:line that does not exist
   S=~/spiral/draw/scripts/draw_server.py
   P=$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')   # a free port: 8766 is often another session's
   python3 $S $B --port $P &                                                 # background — it exits when the user presses Send
   ```
   Restart the viewer on the **same** `$P` after each Send, so the open tab reconnects. `draw.py serve`
   takes no `--port`, so do not use it.
   A `FAIL` from `new` is fixed in the spec, not overridden: drop a box, split the board, or open the file
   and correct the line. `--allow-big` is for the user to ask for, not the agent.
3. Check `curl -s http://127.0.0.1:$P/api/scene` shows this board's labels, then tell the user the URL
   (`http://127.0.0.1:$P/`; on a VM, the port is forwarded), **which box to look
   at first and why**, and one question the board raised — never "here is the diagram".

`plan` mode, when the plan is the agent's own next change: draw it **before** touching code. A green box
the user vetoes on the board costs nothing; the same box as a PR costs a review round.

## Every later round — read the board

`python3 $D diff $B` prints what changed since the agent last looked, in the user's terms:

```
+ box #u:4d45a7 "validate the model?" (rectangle, you) near #gen
+ arrow #u:4d45a7 → #gen (you)
+ text #u:91c0e2 "why does this run every install?" (you) near #gen
~ #settings: recoloured to touched
+ circled #hook, #active_spec (you)
- arrow "runs" removed
(3 element(s) moved — layout only, kept as is)
```

`#key` is a box the agent drew; `#u:xxxxxx` is the user's. Both work in every command, as does any
unique substring of a box's text. `describe` prints the whole board when the diff lacks context.

| They drew | It means | Reply with |
|---|---|---|
| a circle or stroke around a box | *this one — explain it, or this is where it goes wrong* | `add note --near #box`, and open that file before answering |
| a box of their own | *something is missing, or I think this exists* | verify in the code; real → `set #u:… --at path:line --kind …` (adopt it); not real → `add note --as answer` saying what exists instead — **never `rm` their box** |
| an arrow from their box to yours | a proposed flow | check the code; real → adopt; wrong direction or hop → `add arrow` the real one in `touched` and a note |
| free text ending in `?` | a question | `add note --as answer --near` the question, ≤2 sentences, with a `path:line` |
| a recolour | they changed the kind — they are telling you the scope | adopt it in the plan; say so in chat |
| a box deleted | out of scope, or wrong | ask in a `question` note if unsure; do not redraw it |
| elements moved | layout only | nothing — positions are kept on every later write |

Then answer **in chat too**, short: what changed on the board and the one thing to look at next.

## Drawing back — the hands

```sh
python3 $D add note  $B --text "…" --near "#gen"     [--as answer|question|warning]
python3 $D add box   $B --label "retry queue" --at src/queue.rs:40 --kind new --near "#worker" [--lane home] [--step 2]
python3 $D add arrow $B --from "#worker" --to "retry queue" --label "requeues" [--when "exit != 0"] [--kind new|trace|failing]
python3 $D set       $B "#u:4d45a7" --kind touched --at workflow/gen-agents.py:69    # adopt the user's box as a verified one
python3 $D set       $B "#settings" --kind touched --step 1
python3 $D rm        $B "#legacy-cache"                                           # the agent's own boxes only
python3 $D phase     $B --built 1 2 3                                              # those steps shipped: boxes grey, badges green
python3 $D check     $B --repo "$(git rev-parse --show-toplevel)"                 # before every hand-off
python3 ~/spiral/draw/scripts/overflow-check.py $B                           # before every hand-off: no text over a box
```

| Convention | Because |
|---|---|
| Answer where the question is: a note **beside** their text or box, connected by a dotted line | the board stays readable as a conversation |
| Never move, restyle or delete the user's elements | it is their half of the drawing; disagreement goes in a `question` or `warning` note |
| A box the agent got wrong is fixed with `set`, not redrawn | the user may have arrows attached to it |
| Adopt what is real: a user's box that names a real thing gets `set --at path:line` | the board converges on verified facts, whoever drew them |
| ≤3 agent elements per round unless asked for a full redraw | ten new boxes at once is prose again |
| `new` again only for a full redraw; it keeps the positions of every box that already exists and, with `--keep-yours`, the user's elements | a re-layout that throws away their arrangement is a rude reply |
| After any redraw, count the arrows against the spec | a browser save can strip `customData`, and `--keep-yours` used to re-adopt the previous redraw's arrows as the user's — 17 arrows for a 13-edge spec, read as duplicates. `draw.py` now rejects agent-shaped ids here; the count is how you confirm it |

After drawing, restart the viewer in the background (`serve $B &`) if it exited; the open tab
reconnects and merges. If it is still running (`--stay`), the tab has already merged.

## With `/slice` — plan on the board, build, come back to the board

The iterative loop is `/slice`'s; the board is its picture. One board per spec, the same slug, kept
across every slice — `/slice` seeds it, each re-entry marks the shipped steps built and draws the next
slice on it, and the user answers each round by drawing.

```
/slice ── seed ──▶ board: grey = exists · green/yellow = THIS slice · badge = build step
   │                    │  agent's ≤3 questions = blue notes on the boxes they concern
   │                    ▼
   │              user recolours / draws / types ──▶ Send
   │                    │
   ▼                    ▼
/implement → /test      diff → the answers are on the board → spec written, PNG linked
   │
   ▼
/slice re-entry ── draw.py phase --built 1 2 3 ──▶ built boxes go grey, badges green
                   draw.py diff ──▶ what the user drew while it was built = the retro's ground truth
                   next slice: ≤3 new green/yellow elements, steps 4 5 6 ──▶ user draws back ──▶ /implement
```

| Rule | Because |
|---|---|
| badge number = the spec's build-order step, not a slice count | `phase --built 4 5 6` closes slice 2 and the board and the spec agree by construction |
| the next slice is drawn on the same board, never a new one | the user's earlier strokes and the grey history stay in view; a fresh board resets their mental model |
| a `question` note per `/slice` question, on the box it is about | "should retries live in the worker or the queue?" is answerable by recolouring one box |
| GOAL met → all grey, every box `path:line`-verified | the board ends as the as-is picture of the feature, the thing the next person reads first |

## Review — did the change do what the board said?

The plan board makes a builder's review a set comparison, which is why it can be quick. Run it on
any PR, branch or commit range against the spec's plan board; add the system board to see which
running parts were touched and whether a process or host boundary was crossed unplanned.

```sh
python3 $D review $SPEC_STORE/projects/<p>/boards/<slug>.excalidraw --repo "$(git rev-parse --show-toplevel)" \
        --base origin/main --head HEAD --system $SPEC_STORE/projects/<p>/boards/<slug>.system.excalidraw
```

| It prints | Meaning | On the review board (`<slug>.review.excalidraw`, the plan board is never written) |
|---|---|---|
| `RIGHT THING — n files all land on planned boxes` | every changed file belongs to a box the plan coloured green, yellow or dashed | built boxes get a green badge; planned boxes this change did not reach go dashed (*missing*, reported, not failed — a PR may be one step of the plan) |
| `CHECK — k unplanned box(es) touched` | a grey box changed | that box turns red with an UNSPECCED note listing the files |
| `CHECK — m file(s) outside the board` | changed files no box stands for | a red note at the top lists them — often the real risk |
| `boundary A → B (network boundary · call) … UNPLANNED crossing` (with `--system`) | two touched running parts in different lanes, and their files were not all on planned boxes; the brackets say what the crossing costs and whether the sender waits | the arrow turns red on the system review board |
| `DESIGN FLAG: …` (with `--system`) | a trade-off that is risky unless chosen on purpose: a second writer to a store, a changed `call` across a network or trust lane with no `on_fail`, an unplanned trust crossing. It does not change the verdict | a red DESIGN FLAG note on the box it concerns |

**Before you believe a `CHECK`, check the drawing.** The most common cause is not scope creep but a
box typed `unchanged` sitting in a file the change touches — `review` maps changed files onto every
box that claims them, so such a box is reported `UNSPECCED` even when the change is exactly as
planned. Four boxes on one file with mismatched kinds give four findings about nothing. The fix is
usually to **delete the box and move its point onto an arrow label**: "this part did not move" is
worth saying, but it is an arrow, not a box. `CHECK — m file(s) outside the board` is the one that
is nearly always real — usually a forgotten `docs` or `tests` box, or a missing `covers` glob. Both
traps and the label rules are in
[`references/spec-format.md`](references/spec-format.md).

Repo plumbing (`.gitignore`, CI workflows), lockfiles and generated or vendored trees are set aside by
default, counted in the verdict and named in the report — but never PR templates or `CODEOWNERS`
(`--list-ignores` prints the set, `--ignore` adds more, `--no-default-ignores` turns it off). Exit code 0 for RIGHT THING, 1 for CHECK, so it can gate. Below the verdict is a table, one row per
box touched or missed, ready to paste into the PR. A box stands for its `at` file plus its `covers`
globs; a change that lands on no box means the board is missing a box, which is itself a finding.

## When Send to Claude fires

The background server prints one line and exits:

```
{"file": ".../boards/<slug>.excalidraw", "event": "send", "note": "I think gen-agents should validate the model too", "png": ".../<slug>.png", "svg": ".../<slug>.svg"}
```

`note` is what they typed in the bar — treat it as the user's message. `png`/`svg` are fresh exports of
the whole board: link the PNG from the spec (`## Architecture impact` → `![](../boards/<slug>.png)`) and
from the session write-up. Then: `diff` → answer → draw → `serve … &` → reply in chat.

## Where boards live

| | |
|---|---|
| Path | `$SPEC_STORE/projects/<project>/boards/<slug>.system.excalidraw` and `<slug>.excalidraw` — same `<slug>` as the spec they belong to |
| Beside it | `<slug>.png`, `<slug>.svg` (written on Send / Export), `<slug>.spec.json` (the round-1 seed, for a redraw) |
| Commit | straight to `main` in the spec store with the spec; the board **is** the Architecture impact section from now on — the spec links the PNG instead of carrying a 160-line ASCII block |
| Never | in the code repo or a job tmp dir |

## Viewing without the server

The file is a plain `.excalidraw`; the agent reads and writes it the same way whichever editor the user
prefers. The server is only what makes a round trip take one click.

| Viewer | How | Live merge of agent writes? |
|---|---|---|
| `draw_server.py` (default) | `draw_server.py <board> --port <free>` → browser | yes |
| VS Code, Excalidraw extension (`pomdtr.excalidraw-editor`) | open the file | reloads on external change when the tab is not dirty; turn autosave on |
| excalidraw.com → Open | load the local file; save back with Ctrl/Cmd+S to the same path | no — reopen after the agent draws. Never use *Share* / export link: that uploads the board |
| Obsidian Excalidraw plugin | vault holding the spec store | reloads on change |

## Degraded modes

| Missing | Do |
|---|---|
| `Agent` tool | `python3 ~/spiral/workflow/run-agent.py code-mapper --var mode=… --var level=… --var task_brief=… --var repo_path=… --var plan='(none)' --backend claude` (or inline: drop `--backend`), save stdout as the spec |
| a browser on this machine | add `--no-open`; the user forwards the port (VS Code does; else `ssh -L $P:localhost:$P <vm>`) |
| unpkg blocked for the **browser** | `npm install --prefix ~/.cache/spiral/draw @excalidraw/excalidraw@0.17.6 react@18 react-dom@18` once; the server picks it up (or `--vendor DIR`) |
| `Send` never comes | the user talks in chat instead; run `diff` — the file autosaves on every edit anyway |

## Rules this skill exists to enforce

1. Read the code before drawing it — every agent box carries a `path:line` that exists.
2. ≤12 boxes. Split, do not shrink the font.
3. Draw the plan before building it; the delta is seen in green and yellow, not read in a build order.
4. The user's marks are the conversation: every circle, box and `?` gets a reply on the board, next to it.
5. Never touch the user's elements; adopt them with `set` when they are right.
6. The board and its PNG live in the spec store beside the spec, committed to `main`.
7. Boards replace the spec's ASCII architecture block; they do not join it.
