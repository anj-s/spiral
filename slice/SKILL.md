---
name: slice
description: >
  Iterative design. Designs the SMALLEST viable slice of a feature or bug fix
  before any code: confirm the work with the user, one ground-truth read, two independent
  proposals, one critique, ONE question round (≤3 questions), ≤3 build steps, then an
  implementer runs /implement → /test before /review → /open-pr → /verify-ci. Run it again once
  the slice is verified and it designs the next slice from what building the last one taught.
  Default entry point for new work and bug fixes; a full design document is the escalation, not the start.
---

# slice

`/slice <thing> [plan=<model>] [critique=<model>] [implement=<model>]` → the **next slice** of
`$SPEC_STORE/projects/<project>/specs/<slug>.spec.md`, then hand-off to the build skills. `/slice`
again once that slice is verified → the slice after it.

Not this skill: a change whose build step is already written in a spec — make that change directly.
Not this skill either: a design the escalation table below sends to a full design document.

## Why this exists

A design-everything-first process interrogates until *no remaining unknown would change the build
order*. On real tasks that was five to six rounds before a line of code, and half of those rounds asked things the
first build would have answered for free. This skill inverts the order: design the thinnest thing
that runs end to end, build it, test it, and let the built thing ask the next question.

The design half is split across models on purpose. One designer's options share its blind spots,
so two proposers design **independently**, one critic judges them **once**, and an implementer
builds what was chosen. The user approves between judging and building, never after.

## Three models — the user names them, the skill never does

| Role | Runs | Argument |
|---|---|---|
| **planning model** | the two proposers | `plan=<model>` |
| **critique model** | the critic | `critique=<model>` |
| **implementation model** | the implementer | `implement=<model>` |

Any role not given in the arguments is asked in the confirm step, in the same message as the
work summary — never guessed, never defaulted. On re-entry the spec's goal block already records
the three (`MODELS plan=… critique=… implement=…`); reuse them unless the user names new ones.
Pass each as the `model` of its `Agent` call. The code reader runs on the session's own model.

## Confirm first — before anything runs

Say what the work is in two or three plain sentences — for an issue: the issue number, what the
user sees going wrong, and how to reproduce it; for a feature: what an actor will be able to do.
If any of the three models is missing, ask for it in the same message. Then **stop and wait for a
yes** (and the models). Nothing is assigned, dispatched or written before it.

After the yes, run the repo's **on-start** steps from the per-repo hooks table (below) — for a
GitHub issue that is typically an assignee. Then the goal block.

## The goal block — first output after the yes

Before any agent runs, print this and then write it at the top of the spec:

```
GOAL       <one line: who can do what, once the whole feature exists>
DONE WHEN  <one agent-runnable check, or one observable a human confirms in under a minute>
THIS SLICE <the thinnest end-to-end path toward GOAL — switched on, even hardcoded>
NOT NOW    <what is deliberately deferred to a later slice>
BUDGET     1 question round · ≤3 questions · ≤3 build steps · 4 design agents · ≤30 min to hand-off
MODELS     plan=<model> · critique=<model> · implement=<model>
```

No goal in the prompt → the goal *is* the first question this round asks. Never design toward a
goal the user has not seen written down.

## The loop

```
/slice <thing>
   │
   ▼
 CONFIRM ── say what the work is → wait for yes → repo on-start hooks (assign)
   │
   ▼
 GOAL BLOCK ──▶ phase 0  spec-code-reader (ONE agent; spec-researcher only on request)
                    │
                    ▼
                phase 1  PROPOSE — two proposers (planning model) in parallel, each blind to the other
                    │
                    ▼
                phase 2  CRITIQUE — one critic (critique model), once: picks one, says what each misses,
                    │      runs the three slice checks on the pick
                    ▼
                phase 3  ONE question round, ≤3 questions, one AskUserQuestion call
                    │      question 1 = approve the critic's pick; not asked → ASSUMED:
                    ▼
                phase 4  write / extend the spec: this slice's FRs + ≤3 build steps
                    │      set active-spec → HAND OFF
   ┌────────────────┘
   ▼
 implementer (implementation model): /implement → /test (red first, whole suite, repo verify hooks)
   │
   ▼
 main agent: /builder-review → /review → /open-pr → /verify-ci      (all four, every PR — none skipped silently)
   │
   ▼
 /slice   ◀── re-entry: read drift log + test verdict + parked questions
              retro → which parked question did the code answer? which is moot?
              → GOAL met?  yes → stop; file issues for what is left
                           no  → next slice, same budget
```

## Budget — structural caps, not intentions

| Cap | Value | Why it is structural |
|---|---|---|
| Question rounds per slice | **1** | one `AskUserQuestion` call; a second call is a rule violation, not a judgement call |
| Questions per round | **≤3** | the fourth is answered by building |
| Design agents dispatched | **4** — `spec-code-reader`, 2 proposers, 1 critic | `spec-researcher` only if the user asks, or the slice crosses a vendor / external-API boundary |
| Critique rounds | **1** | the critic never sees a revised proposal; disagreement with it goes to the user's one question round |
| Build agents | **1** implementer per slice | it builds only what the spec's Build order says; anything else is drift |
| Build steps per slice | **≤3** | step 1 runs end to end; more than three is two slices |
| Spec size | **≤120 lines at slice 1; each re-entry adds ≤40** (`wc -l`) | a spec that no longer fits a screen has become a design document |
| Wall clock, yes → hand-off | **≤30 min** | `date +%H:%M` at entry; at the cap, write what you have and hand off |
| Slices before a goal check | **3** | on the third re-entry ask *GOAL met? continue / stop / escalate* before designing |

Hitting a cap is **not** a failure. Write the smallest hardcoded slice with what you have and hand
off; the build will produce more ground truth than another round would.

## Phase checklist

| Phase | Do | Exit |
|---|---|---|
| confirm | say what the work is; wait for a yes; then the repo's on-start hooks | user said yes |
| goal | print the goal block; `date +%H:%M` | user has seen GOAL and DONE WHEN |
| 0 ground truth | dispatch `spec-code-reader` with `{{task_brief}}` = goal block + the user's prompt (for a bug: the issue body, its repro and screenshots), `{{repo_path}}` = `git rev-parse --show-toplevel`. Its *Smallest end-to-end switch-on point* section **is** slice 1 | agent returns |
| 1 propose | dispatch **two proposers in one message** on the planning model, same brief each: goal block + code reader's findings + *Picking the slice* + the options-table row shape. Each returns ONE design — mechanism, files at `path:line`, ≤3 build steps, the red test it starts from, blast radius, its own `Bad, because`. Neither sees the other. Save both as `proposal-a.md`, `proposal-b.md` | both return |
| 2 critique | dispatch **one critic** on the critique model, once: both proposals + the code reader's findings. It returns a pick (A, B, or A+part of B) with a one-line reason, what each proposal gets wrong or misses, and a PASS/FAIL per **three slice checks** (below) on the pick. The brief carries the **critic's evidence rules** (below); a precise claim it could not verify is marked `UNVERIFIED:`. Save as `critique.md`. It is not re-run on a revised design | critic returns |
| 3 question | show the **options table** built from the two proposals (below), the critic's pick marked ★. Then ≤3 questions in one `AskUserQuestion` call: question 1 is *approve the critic's pick* (options: the pick, the other proposal, the critic's merge if it proposed one); the rest PRODUCT questions, each with 2–4 options and a recommendation | answers in hand |
| 4 write + hand off | new spec, or extend the existing one; skeleton below. `spec-drafter`'s rules apply verbatim (`agents/spec-drafter.md`): no prose, user-facing FRs, `verify:` and `docs:` on every step. The options table goes under `## Decisions` as `Options considered`, the loser as `rejected:`. Fix any critic FAIL inline. `printf '%s\n' "$SPEC_PATH" > ~/.local/state/workflow/active-spec`; commit spec + proposals + critique to the store's `main`; dispatch the implementer | implementer starts |

The design notes live next to the spec: `$SPEC_STORE/projects/<project>/specs/<slug>/` holds
`proposal-a.md`, `proposal-b.md`, `critique.md`, `decision.md` (the user's answers) and, once
opened, `pr-body.md`. For a bug the slug is the issue number.

## The implementer — one subagent per slice, on the implementation model

Dispatched on the implementation model with a brief of: the spec path, this slice's build steps, the repo
and worktree path, a private build directory, and the repo's verify hooks. It follows `/implement`
then `/test` inside that brief:

| Rule | Because |
|---|---|
| red first — the step's test fails before the fix, and it is shown failing | a test written after the fix only proves it compiles |
| builds only the spec's Build order; anything else is logged `UNSPECCED:` in the Drift log | the spec is the control document |
| runs the **whole suite** the way CI does, not a tier | tier lists miss targets silently |
| runs the repo's verify hooks (e.g. a real-UI probe with screenshots) | a green suite is not a user seeing it work |
| returns: diff summary, the red→green output pasted, suite counts, screenshot paths | the main agent reports what ran, never what should have |
| does not open the PR | review and the PR stay with the main agent |

A design gap the implementer hits (the spec is wrong, not the code) comes back as a question, not
a workaround; the main agent takes it to the user.

Then the main agent, in this order, on every PR:

| Step | Answers | Not a substitute for |
|---|---|---|
| `/builder-review` | did the change land on the plan and nothing else (file level) | reading the code |
| `/review` | is each hunk correct — logic, edge cases, error paths, test strength — on the diff vs its base | the plan check |
| `/open-pr` | repo template, screenshots, draft | — |
| `/verify-ci` | green on the PR's own base | a local suite run |

`/review` is **not** optional and `/builder-review` does not stand in for it: a RIGHT THING verdict
only says the right files changed. Its findings are fixed before the PR opens, or listed in the PR
body as known. Skipping it is a decision the PR body states ("Review: not run because …"); a batch
of PRs opened without it is the failure this row exists to stop.

The builder-review board is **not shown to the user, and its verdict is not reported, until
`/review` has finished on the same change.** A RIGHT THING board on its own reads as a clean bill
for code nobody has read. When the review is in, draw it onto the board — a warning note
(`draw.py add note --as warning`) on each box whose file has a finding, and one note carrying the
review's verdict line — then serve the board and report both verdicts together. Hand-off line, this shape:
`Slice N written → <path>. Implementer running. Come back with /slice when it is verified.`

## Per-repo hooks

The skill is general, so a repo's own steps live with that repo's skills, not here. Each repo in
`$EXTRA_SKILL_REPOS` may carry a `repo-hooks.md` at its root with one table in this shape:

| Repo | on-start (after the yes) | verify (implementer) | PR |
|---|---|---|---|
| `acme/app` | issue: assign yourself | whole suite as CI runs it; a user-visible change also gets a real-UI probe with before/after screenshots | repo template; screenshots in the PR body; draft |

Read every such file (`for r in $EXTRA_SKILL_REPOS; do cat "$r/repo-hooks.md" 2>/dev/null; done`)
and use the row whose Repo matches `git remote get-url origin`. No matching row → no hooks.

## Picking the slice

| Rule | Test |
|---|---|
| Walking skeleton first | slice 1 touches every layer the feature needs, thinly — hardcoded values fine, a stub surface fine, a missing layer not |
| Vertical, never horizontal | a slice named after a layer ("the data model", "the API") is wrong; one named after what an actor can now do is right |
| Demoable alone | it can be shown working before any later slice lands |
| One sitting | built, tested and reviewed in one session; if not, split it |
| Hardest seam second | after the skeleton, the slice that de-risks most goes next — not the easiest |
| Named by outcome | `<actor> can <observable outcome>` — the same test an FR has to pass |

## Options — two or three ways to build the slice, before the questions

The first thing the user sees after the goal block is not a plan but a choice. The options are the
two proposers' designs (plus the critic's merge, when it proposed one) — never options the main
agent wrote itself. One recommended (the critic's pick), in MADR's wording (`Good, because` / `Bad, because`), each tied to what it
would change on the **system board** — a different box, a different arrow, a different lane crossing.

```
| Option | What changes, at system level | Good, because | Bad, because |
|---|---|---|---|
| A. <name> ★ recommended | <box/arrow it adds or moves> | <one line> | <one line> |
| B. <name> | … | … | … |
| C. <name> | … | … | … |
```

| Rule | Because |
|---|---|
| 2–3 options, never 1, never 5 | one option is a decision already made; five is a survey nobody reads |
| each option named by its mechanism, not its virtue | "retries in the worker" vs "retries in the queue", not "simple" vs "robust" |
| the differences are visible on the system board | if two options draw the same boxes and arrows they are one option with a detail knob — say so and drop one |
| one `Good, because` and one `Bad, because` each, concrete | a con with no cost is an ad; "Bad, because it needs a migration of 3 tables" is a con |
| the recommendation carries its reason in ≤1 line | the user is choosing between reasons, not names |
| a rejected option is kept in the spec's Decisions as `rejected: <name> — <its Bad>` | six months on, the question is always "why not B?" |

On the board: the chosen option is what gets drawn; each rejected option becomes a blue `question`
note on the box where it would have differed — one recolour or one arrow from the user reopens it.

## The spec file — the drafter's skeleton, two additions

Same path, same skeleton (`agents/spec-drafter.md`), so `spec-locator`, `/implement` and the
active-spec hook all work on it unchanged.

| | |
|---|---|
| Path | `$SPEC_STORE/projects/<project>/specs/<slug>.spec.md` |
| Project | from `spec-locator`'s drill-down, or ask; never invent one |
| Commit | straight to `main` in the spec store — no branch, no PR, no AI-attribution trailer |
| Addition 1 — goal block | under the title: GOAL / DONE WHEN / BUDGET / `Slice N` |
| Addition 2 — `## Slice log` | after Drift log: one row per slice — what shipped, what building it taught, what that changed in the plan |

Sections of a slice-1 spec, in order: goal block · Surface (this slice only) · Requirements (this
slice's FRs) · Build order (≤3 steps) · Decisions (the options table as `Options considered`, then
`chose A over B — because`, `ASSUMED:` on anything not asked) · Open (parked questions) · Slice log. Omit anything empty. Add Architecture impact only when a slice
changes it — as a `/draw plan` board, linked as its PNG, not an ASCII block.

`ASSUMED:` decisions are what make one round enough. Each carries its default and *what changes if
wrong*; a wrong assumption at this size costs one slice, not a redesign.

## With `/draw` — two boards per spec, kept across every slice

`/slice` decides *what* the next slice is; `/draw` is *where the user and the agent see it and
argue about it*. Two boards, same slug, in `$SPEC_STORE/projects/<project>/boards/`:

| Board | File | Boxes are | Answers |
|---|---|---|---|
| **system** (C4 container level) | `<slug>.system.excalidraw` | separately running things — processes, CLIs, browser pages, stores, external services, people — each with a `[technology]` line and where it runs (lane) | *which running parts does this slice touch, and does it cross a process or host boundary?* |
| **code** (C4 component/code level) | `<slug>.excalidraw` | files at `path:line`, the data and logic inside one or two of the system boxes | *which files change, in what order, and what flows between them?* |

The system board comes first and is drawn once per spec; its boxes carry `detail` links to the code
board. The options table above is argued on the system board; the build order is argued on the code
board. A slice that touches one system box needs no system-board change — say so.

| `/slice` step | Board move | Who draws |
|---|---|---|
| phase 0, code reader returns | seed: `code-mapper` (mode `plan`, `{{plan}}` = goal block) → `draw.py new` → `serve &`. Grey = what exists, **green/yellow = this slice, badge = its build-order step** | agent |
| phase 1, the one question round | each of the ≤3 questions is also a blue `question` note on the box it concerns; the `AskUserQuestion` call still happens — the board is what the answer is *about* | agent asks, user answers by recolouring, drawing, or typing and pressing Send |
| phase 2, spec written | `## Architecture impact` = `![](../boards/<slug>.png)` — the export Send wrote; no ASCII block | agent |
| hand-off | `draw.py check --repo` passes; the user has seen the green boxes before a line of code | — |
| `/implement`, `/test` | nothing — the board waits; the user may keep drawing on it | user |
| re-entry, step 0 | `draw.py phase --built <this slice's step numbers>` (built boxes go grey, badges green) then `draw.py diff` — what the user drew while it was being built is ground truth for the retro | agent |
| re-entry, next slice | ≤3 new elements in green/yellow with the next step numbers; parked questions that fired become `question` notes | agent, then user draws back |
| GOAL met | the board is the as-is picture of the feature: all grey, every box with `path:line` — it outlives the spec's Slice log | — |

What this buys: the user never reads a Build order to learn what is about to change — they see it,
in colour, on the same picture every slice, and their disagreement is a stroke, not a paragraph.

## Parked questions, and how they expire

Every question not asked goes under `## Open` as
`- [ ] PARKED: <question> — ask when <trigger>`. On re-entry each is triaged exactly once:

| Now | Do |
|---|---|
| The built code answers it | tick it; record the answer in Decisions |
| It no longer matters | strike it, one-line why |
| Its trigger fired | it is a candidate for this slice's one round |
| None of the above | leave it |

This is what compounds: slice N's drift log and parked list are slice N+1's ground truth, so the
question count falls with every slice instead of resetting to a fresh interview.

## Re-entry — read before designing slice N+1

0. The board: `draw.py phase --built <steps>` then `draw.py diff` — what shipped goes grey; what the user drew meanwhile is read before anything else.
1. The spec's Drift log — every `UNSPECCED:` entry is a miss the next slice must cover.
2. `git log <last slice's commit>..HEAD` in the code repo — what actually changed.
3. The last `/test` verdict and `/verify-ci` state — a red slice is not a shipped slice; do not
   design on top of it.
4. `## Open` — triage as above.

Then write one Slice log row, decide *GOAL met / next slice / escalate*, and run the loop again.

## The three slice checks — run by the critic

A full design review would run more checks. A slice gets the three that bite small designs;
they go in the critic's brief and it reports PASS/FAIL on its pick:

| # | Check | FAIL looks like |
|---|---|---|
| 1 | NOT SWITCHABLE | step 1 is a data model, a type, a config key — anything a user cannot see run |
| 2 | REBUILDS WHAT EXISTS | a build step already covered by the code reader's *Already exists* section |
| 3 | IMPLEMENTATION-FACING FR | an FR naming a function, type, module or file instead of what an actor can do |

Any FAIL → the main agent fixes the spec in phase 4, inline. No second critique.

## The critic's evidence rules — verify, never predict

The critic is good at choosing between designs and weak at predicting precise effects. Every miss
below reached an implementer as a design gap. Each rule goes in the critic's brief; a claim that
breaks one is marked `UNVERIFIED:` in the critique instead of stated as fact.

| # | Rule | The miss it prevents |
|---|---|---|
| 1 | **Every number carries its arithmetic.** Line counts against a cap, row budgets, hidden-line counts, widths: compute them from the code and show the sum. | a "hidden lines = 2" that the renderer's per-line painting makes 1 |
| 2 | **Name what pinned output could move.** Grep golden files and snapshots for the text the change touches; list the ones that move, or say "none" with the grep. "Invisible" is a claim that needs that grep. | a "no visible change" that shifted two golden snapshots by a row |
| 3 | **The red test must fail for the stated reason and pass after.** Check the fixture loads data the way the code reads it (manifest vs database, which store directory, the spawned process's cwd); check the assertion reads the current screen, not the accumulated output that still holds the first frame; check the expected string survives wrapping, no-break spaces and Unicode width. | tests that could never go red, or never go green |
| 4 | **Know the report's environment.** Which terminal, capabilities and capture harness produced the issue's evidence; the red test reproduces under that, not an assumed one. | a design for one rendering mode when the issue ran in another; a "harness artifact" theory that was a real bug |
| 5 | **Verify the code reader's load-bearing claims** — the file, the function, the failing path — before designing on them. | a fix aimed at the wrong function or the wrong file |
| 6 | **Pins keep the whole contract.** An assertion shortened to dodge a wrap is replaced by one on the unwrapped text, not accepted. | a budget pin that stopped one word short |
| 7 | **Parallel slices name their seams.** A definition two PRs share is written out byte for byte in the first critique and copied by the second; each PR's landing plan keeps it on a base CI runs on; overlapping hunks are named with their line ranges. | a stacked PR CI never ran on; two helpers with drifting names |
| 8 | **Escalation calls quote their source.** "Changes an invariant" or "not a stored-format change" quotes the invariant row or format definition it rests on. | an escalation decided by feel |
| 9 | **Docs are named the way the repo's doc check prints them**, and the check is predicted against a freshly fetched base. | attestations CI silently ignored |

## Escalate to a full design when

| Trigger | Why a slice cannot absorb it |
|---|---|
| The slice changes a core invariant, a stored format, a wire protocol or a public API | wrong here costs a migration, not a slice |
| Two consecutive slices logged `UNSPECCED:` drift in the same area | the plan is not converging there |
| The 3-slice goal check finds GOAL further away than at slice 1 | scope is growing, not shrinking |
| The user says so | — |

Escalation hands the full design the existing spec and its Slice log; nothing is thrown away. The
reverse holds too: a full design's build order is delivered one slice at a time by this skill.

## The question relay

In Claude Code, `AskUserQuestion` is stripped from every subagent at spawn. The
code reader, proposers and critic return findings; the **main agent** writes the ≤3 questions and
asks them in one call. The implementer's design-gap questions come back the same way.

## Degraded mode — no subagents

"Dispatch" means the first rung available in `agents/README.md`: a native subagent, else a fresh
process, else inline. With no `Agent` tool:

```sh
python3 ~/spiral/workflow/run-agent.py spec-code-reader \
    --var task_brief="<goal block + prompt>" --var repo_path="$(git rev-parse --show-toplevel)" \
    --backend claude            # or codex | gemini | --backend cmd --cmd '<argv>'; drop --backend to print the prompt and run it yourself
```

The proposers, critic and implementer have no agent file: their briefs are the phase-checklist
rows above. With no `Agent` tool, run each as a fresh `claude --model <the role's model> -p "<brief>"`
process; never collapse the two proposers into one call, or the options lose their independence.

## Rules this skill exists to enforce

0. The user says yes to the work before anything is assigned or dispatched.
1. The goal is written down before anything is designed.
2. One question round. The build answers the rest.
2a. Two independent proposals, one critique, once. The user approves the pick before any code.
2b. The implementer builds; the main agent reviews and opens the PR. Neither grades its own work.
2c. Every PR gets `/builder-review` **and** `/review` before it opens. The first checks the plan, the
    second checks the code; neither replaces the other, and a skip is written in the PR body.
2d. The critic verifies its precise claims — numbers, moved snapshots, red-test mechanics, the
    report's environment — or marks them `UNVERIFIED:`.
3. Slice 1 runs end to end, switched on, even hardcoded.
4. The spec is the same control document `/implement` and the hooks already know. Nothing new to learn.
5. Every unasked question is parked with a trigger, never dropped.
6. Re-entry reads what the build taught before designing anything.
7. Hitting a cap means hand off, not another round.
8. Spec-store commits go straight to `main`; no AI-attribution trailer.
