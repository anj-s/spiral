# Worked example — `/slice` from an empty repo to a merged PR

> This run used an earlier version of these skills that also had `/task` (a small change against an
> existing spec), `/deep-design` and `/open-issues`. Those are not in this repo; read `/task` as
> "make the change and log it in the spec".

This is a real run of `/slice`. It built **nanocoder**, a small coding agent the user runs in the
terminal: you type a request, it sends it to a model on OpenRouter, the model may read files
through one tool, and the loop repeats until the model answers. The repo started with nothing but
a README. Slice 1 ended as PR #1 on a private repo, with 19 tests and
real runs against a free model. Slice 2 re-entered the same spec and shipped PR #6.

Everything quoted below happened in that session. The places where the run went wrong are kept
in, because they are the most useful part of the example.

## The prompt

```
/slice nanocoder: build a minimal coding agent from scratch, in small MVP slices, to learn how
agents work and compound learning. Must be usable by the user day to day, with a deliberately limited
feature set. The repo is empty (README only).
```

## Step by step

### 1. Confirm — say what the work is, ask for the three models, wait

The agent wrote three sentences about what nanocoder would do, and asked for the planning,
critique and implementation models, because the skill never picks them itself. The user answered
`planning=opus thinking=high critique=opus thinking=high implementation opus thinking=medium`.

> Gap found: the `Agent` tool takes a model but not a thinking level. The agent said so and wrote
> the level into each subagent's brief as a request, not a setting.

### 2. The goal block — written down before anything is designed

```
GOAL       the user can run `nanocoder` in any repo, ask for a code change in plain words, and watch it
           read files, edit them and run commands until the change is done
DONE WHEN  the user uses nanocoder to make one real change in a real repo and confirms the diff in
           under a minute
THIS SLICE one prompt → one model call → the model may call ONE tool (read a file) → the result
           goes back → the loop repeats until the model answers in plain text
NOT NOW    editing files, shell commands, permission prompts, streaming, compaction, sessions,
           a full-screen UI, more than one provider
BUDGET     1 question round · ≤3 questions · ≤3 build steps · 4 design agents · ≤30 min to hand-off
MODELS     plan=opus (high) · critique=opus (high) · implement=opus (medium)
```

The goal block went to the top of the spec, `$SPEC_STORE/projects/nanocoder/specs/agent-loop.spec.md`,
before any agent ran.

### 3. Phase 0 — one code reader establishes ground truth

`spec-code-reader` found an empty repo, so it reported what the *machine* offers instead:

- node 24 and bun 1.3 were current;
- the default `python3` was Anaconda 3.7, which is too old for the provider SDKs, but uv had
  Python 3.12 available;
- no model API key was set, and no SDK was installed.

Its "smallest switch-on point" became slice 1: one file, a prompt from the command line, one
`read_file` tool, a loop on tool calls.

> Skipped, and said so: the `/draw` board at phase 0. The board tool refuses a box whose
> `path:line` does not exist, and an empty repo has none. The boards were drawn later, at review.

### 4. Phase 1 — two proposers, blind to each other

Both ran on Opus with the same brief. Their designs were saved as `proposal-a.md` and
`proposal-b.md` next to the spec. They converged: Bun and TypeScript, the HTTP call written by
hand with `fetch` rather than an SDK, and a scripted fake model so tests need no key. They
differed only in file layout — one file, or the loop split from the command line.

### 5. Phase 2 — one critic, once

The critic picked **B plus A's file split**, and then said the thing that made the question
round useful: *these are one option with a layout knob, not two options.* It named the real
alternatives neither proposer explored — the Anthropic SDK with a hand-written loop, and Python
via uv — and listed twelve gaps both proposals shared, for example:

- `fetch` does not throw on a 400, so an API error would have printed nothing and exited 0;
- `max_tokens`, the required cap on reply length, was never pinned;
- only a normal finish should count as success; a reply cut off at the cap is an error;
- the fake model must check the same message pairing the real API enforces, or the first
  pairing bug only shows up as a 400 from the real API.

All three slice checks passed on the pick: step 1 runs end to end, nothing rebuilds existing
code, and every requirement names what the user can do rather than a function.

### 6. Phase 3 — one question round, three questions

The options table came from the critic, not from the main agent:

| Option | What changes at system level | Good, because | Bad, because |
|---|---|---|---|
| A. Raw `fetch` in Bun ★ | nanocoder sends the HTTPS request itself | the request you read is exactly what is sent | no retries: the first 429 kills a run |
| B. SDK in Bun, hand loop | the SDK sits between nanocoder and the API | typed responses, retries by default | hides headers and raw JSON; one dependency |
| C. Python via uv + SDK | a Python process replaces the Bun one | matches most tutorials | no built-in test runner or `bun link` |

The user chose raw `fetch` and the "files under the start directory only" read scope. The third
question asked where the API key would come from, and the user answered in free text: *"I am planning
to use OpenRouter. the design should support that. I want the frontend and backend separate so
make sure we script as well."*

That answer changed two things, and the one-round cap meant there was no second round to ask
about it. The agent recorded both as `ASSUMED:` decisions with what changes if wrong:

- provider = OpenRouter, which speaks OpenAI's chat format, not Anthropic's;
- "frontend and backend separate" = the loop emits events and never prints, and two frontends
  read them — the terminal view, and `nanocoder --json` for scripts. A separate server process
  was parked, because a wire protocol is an escalation to `/deep-design`.

### 7. Phase 4 — write the spec, hand off

The spec came out at 75 lines: Surface, five FRs and one NFR each with a `verify:`, three build
steps each with a `verify:` and a `docs:`, the options table under Decisions, the rejected options
with their costs, and four parked questions, each with the trigger that should reopen it:

```
- [ ] PARKED: retry/backoff on 429/5xx — ask when a real run dies on a rate limit
- [ ] PARKED: system prompt with cwd + tool guidance — ask when the model misreads paths
```

It was committed straight to the spec store's `main`, the active-spec file was set, and one
implementer was dispatched on Opus.

> Cap blown, and said so: yes → hand-off took 73 minutes against the 30-minute cap, mostly
> waiting on the question round. Nothing was cut to make up for it.

## Build, review, and the turns nobody planned

### The implementer: red first, then three commits

The implementer wrote the tests before the loop and showed them failing
(`Cannot find module './agent'`), then built the three steps as three commits. It logged five
`UNSPECCED:` drift lines instead of quietly working around the spec — for example, *"a reply
that carries tool calls runs the tools and loops whatever its finish_reason; the spec's 'only
stop is success' would otherwise fail every tool turn."* The real-model check was reported as
**NOT RUN**, because no key was set, rather than claimed.

### `/review` found a real hole by running it

The boundary check compared path *text*. The reviewer made a symlink inside the start folder
pointing outside it and ran nanocoder on it:

```
→ read_file link.txt (15 bytes)
fake: SECRET-OUTSIDE
```

That broke FR-2, so it was a blocker. `/task` fixed it red first (resolve both paths with
`realpath` before comparing) and wrote a Drift log line; the reviewer reran the same repro and
saw it refused.

### The stack changed after the build

Before the PR opened, the user said *"I want the stack to be a python stack no typescript."* Nothing
in the design depended on the language, so this was a spec edit, not a new slice: the Decisions
section recorded the reversal, the build steps were rewritten for Python 3.12, uv and stdlib
`urllib`, and the implementer rebuilt the same behaviour — including every drift line and the
symlink fix — on a new branch. The TypeScript branch was kept as the reference and deleted after
the merge.

### `/builder-review` — skipped once, then run

The agent first skipped `/builder-review` because there was no plan board. The user caught it. The
fix was to draw the plan board from the **spec's build order**, which was written before any
Python existed, then compare the branch's changed files against it:

```
RIGHT THING — 7 changed file(s) all land on planned boxes (set aside: .gitignore, uv.lock)
system board: 2 running part(s) touched — no touched arrow crosses a lane
```

> Lesson: "no board" is not a reason to skip; it is a reason to draw one from the spec.

### PR review, real runs, merge

The user left six comments on PR #1: switch the default model to GLM 5.2, make `read_file` take
absolute paths, make `run_tool` generic so tools can take any arguments, move constants into
`config.py`, and explain `max_tokens`. They went through one `/task` run. Absolute paths forced
the parked system-prompt question open — the model has to be told the start directory — so that
item was ticked, not left to drift.

The first real run with the user's key failed with `OpenRouter 402 … can only afford 4000` tokens.
That was the error handling working as specified: OpenRouter reserves credit for `max_tokens` up
front. A trial of six free tool-capable models through the real command picked
`cohere/north-mini-code:free` (3 of 3 passes; others hit 429, 503 or 403), which became the
default. PR #1 merged as `6a2b9f6`, and `/open-issues` filed the parked items as #2–#5.

## Re-entry — slice 2 reads what slice 1 taught

`/slice` again, on the same spec. The first thing re-entry does is write one Slice log row:

| Slice | Shipped | Taught | Changed in plan |
|---|---|---|---|
| 1 | PR #1: loop, read_file, OpenRouter via urllib, terminal + `--json`, uv command; 19 tests | the SDK-free request fits in one function; OpenRouter reserves `max_tokens` credit up front; free models 429/503 often; text path checks miss symlinks and macOS `/tmp` | stack → Python; absolute paths, tool registry, system message; retry + timeout now worth a slice (#3) |

Slice 2 took issue #2, an opt-in integration test, and shipped it as PR #6. Its own row taught
that a registered pytest marker does not deselect tests on its own — `addopts` does — and that a
fake model left in a child process's environment passes with no network at all.

## What this example shows about the skill

- **The critic earns its place by collapsing options.** Two proposers converging is common; the
  critic saying "this is one option with a knob" is what put the real choice in front of the user.
- **One round is enough when answers become `ASSUMED:`.** the user's free-text answer changed the
  provider and the architecture. Writing both down with "what changes if wrong" was cheaper than
  a second interview.
- **Parked questions compound.** The system-prompt item fired during PR review, and retry +
  timeout fired on the first free-model run; both were waiting with their triggers written down.
- **Drift lines, not silent workarounds.** Every place the implementer departed from the spec is
  in the Drift log, which is how the Python rebuild could reproduce the TypeScript behaviour.
- **"Run the thing" catches what green tests miss.** The symlink escape, the 402 credit error and
  the macOS `/tmp` alias were all found by running the command, not by the suite.
