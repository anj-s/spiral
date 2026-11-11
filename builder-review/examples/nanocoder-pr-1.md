# Worked example — `/builder-review` on nanocoder PR #1

> This run used an earlier version of these skills that also had `/task` (a small change against an
> existing spec), `/deep-design` and `/open-issues`. Those are not in this repo; read `/task` as
> "make the change and log it in the spec".

This is a real run of `/builder-review` on PR #1 of nanocoder, a small coding agent that
runs in the terminal. You type a request, nanocoder sends it to a model on OpenRouter, the model
may read files through one tool, and the loop repeats until the model answers. PR #1 is the
project's first slice: five commits that took an empty repo to a working command.

Every command output below was produced by this run. Two things went wrong during it, and both
are kept in: the board itself caused a false design flag, and the flag check passed something a
reader still has to judge.

## The prompt

```
/builder-review nanocoder PR #1
```

## Step 1 — resolve the range

```sh
gh pr view 1 --json baseRefOid,headRefOid,commits
# {"base":"8e768dc","commits":5,"head":"5c847e6"}
gh pr diff 1 --name-only
```

Ten files changed: `.gitignore`, `.python-version`, `README.md`, `nanocoder/__init__.py`,
`nanocoder/agent.py`, `nanocoder/cli.py`, `nanocoder/config.py`, `pyproject.toml`,
`tests/test_agent.py` and `uv.lock`.

## Step 2 — find the plan, before reading the diff

The work has a spec, so the plan is the spec's own plan board: the code board that `/slice` drew
from the spec's build order when the PR opened. It was recovered from the spec store's history at
that moment, before review comments changed the design, because the question is "did the PR do
what the plan said when it was opened, and what changed after?"

The code board has 9 boxes, each a file at a `path:line` with `covers` globs:

| Box | Plan | What it is |
|---|---|---|
| `#agent_core` | new · step 1 | the loop: sends messages, runs the tool, feeds results back |
| `#fake_model` | new · step 1 | a scripted model that checks every tool call is answered |
| `#cli_terminal` | new · step 1 | the terminal view: each file read, then the answer |
| `#tests` | new · step 1 | the red-first tests |
| `#pyproject` | new · step 1 | zero runtime dependencies, the `nanocoder` command |
| `#python_version` | new · step 1 | pins Python 3.12 |
| `#real_model` | new · step 2 | one HTTPS POST per turn to OpenRouter, no SDK |
| `#cli_json` | new · step 3 | `--json`: one event per line, for scripts |
| `#readme` | touched · step 1 | the README |

The decisions come from the spec's `## Decisions` section: an options table, `chose … over …`,
`rejected:` and `ASSUMED:` lines.

## Step 3 — the system board, with the building blocks filled in

The spec's system board predated the building-block fields, so `draw.py new` warned 15 times:

```
WARN node user: no role — say what kind of part it is (person, client, service, worker, store, queue, cache, external)
WARN node nanocoder_process: no role — …
WARN edge nanocoder_process→openrouter: no via — does the sender wait (call) or not (message)?
…
WARN lane machine: no boundary — what separates it (process, network, trust)?
WARN lane internet: no boundary — what separates it (process, network, trust)?
```

That is 5 boxes with no `role`, 8 arrows with no `via` and 2 lanes with no `boundary`. Each was
filled in **from the code at the PR's head**, not from what the code should do:

| Part | Filled in as | Because |
|---|---|---|
| the user, at the terminal | `person` | — |
| the nanocoder command | `client` | a CLI process that holds no data of record |
| files under the start directory | `store` | read, never written, by this PR |
| the scripted fake model | `service` | answers requests, keeps no state |
| OpenRouter's chat API | `external` | not ours to change |
| nanocoder → OpenRouter | `call`, on_fail: *"HTTP error or error in the reply → error event, exit 1; no timeout, no retry"* | `urlopen` at `agent.py:165` has no timeout argument and nothing retries it |
| nanocoder → files | `call`, on_fail: *"missing, outside or relative path → error result to the model; the run continues"* | `read_file` at `agent.py:37` |
| nanocoder → the user | `message` | it prints; nothing waits on the person |
| the user's machine / internet lanes | `process` / `network` | — |

### The flag that was the board's fault

The first review with these fields filled in printed:

```
DESIGN FLAG: #openrouter now waits on #nanocoder_process across a network boundary, and nothing
says what happens when it is slow or down (timeout, retry, fallback)
```

That direction is backwards: OpenRouter never calls nanocoder. The old board drew each reply as
its own arrow (OpenRouter → nanocoder, files → nanocoder, fake → nanocoder), and marking those
`call` told the review that OpenRouter was calling in. The fix was the board, not the code:
fold each reply into its request arrow ("sends chat request JSON, gets tool_calls or answer").

> Lesson: a reply is the return of a call, not a second call. Draw one arrow per call.

## Step 4 — the comparison

```sh
D=~/spiral/draw/scripts/draw.py
python3 $D review pr-1-agent-loop.excalidraw --repo . --base 8e768dc --head 5c847e6 \
    --system pr-1-agent-loop.system.excalidraw
```

```
CHECK — 1 file(s) outside the board: nanocoder/config.py (set aside: 2 plumbing/lock/generated file(s))
set aside as repo plumbing / lock / generated, not asked of the board: .gitignore, uv.lock
system board: 2 running part(s) touched → pr-1-agent-loop.system.review.excalidraw
  no touched arrow crosses a lane

| box | plan | changed files | verdict |
|---|---|---|---|
| #agent_core | new · step 1 | nanocoder/__init__.py, nanocoder/agent.py | built ✓ |
| #fake_model | new · step 1 | nanocoder/agent.py | built ✓ |
| #cli_terminal | new · step 1 | nanocoder/cli.py | built ✓ |
| #tests | new · step 1 | tests/test_agent.py | built ✓ |
| #pyproject | new · step 1 | pyproject.toml | built ✓ |
| #python_version | new · step 1 | .python-version | built ✓ |
| #real_model | new · step 2 | nanocoder/agent.py | built ✓ |
| #cli_json | new · step 3 | nanocoder/cli.py | built ✓ |
| #readme | touched · step 1 | README.md | built ✓ |
```

All 9 planned boxes were built, and nothing unplanned was touched. One file has no box at all.

### The flag that did not fire, and should be read anyway

With the reply arrows folded in, no `DESIGN FLAG` printed. The check looks for a `call` across a
network lane **with no `on_fail` line**, and this one has one. But the line it has says *"no
timeout, no retry"*. The flag checks that the failure behaviour is written down, not that it is
any good; a person still has to read it. That is why it is a row in the table below.

## Step 5 — the decisions table

Every row names a box or an arrow on the system board. Rows from the spec say so; rows nobody
wrote down say `inferred from <path:line>`.

| Decision | Chosen | Instead of | Buys | Costs | Source |
|---|---|---|---|---|---|
| how nanocoder talks to the model | one `urllib` POST, the whole request body built in one function | the SDK with a hand-written loop | the request you read is exactly what crosses the network arrow; zero runtime dependencies | no retries: one 429 or 503 on the OpenRouter arrow ends the run | spec Decisions (option A, revised to Python) |
| what happens when OpenRouter is slow | nothing: `urlopen` with no timeout | a timeout plus retry with backoff | — | **flag (by hand)**: nanocoder waits on OpenRouter across the network lane, so a stalled connection hangs the command — its availability is OpenRouter's | inferred from `agent.py:165`; filed as issue #3 |
| where the two views run | in the same process as the loop, reading its events | the loop as its own server process | no serialising, no wire protocol to design | a second frontend (an editor, a web page) will need that protocol | spec `ASSUMED:` |
| which files can cross to OpenRouter | absolute paths under the start directory, symlinks resolved | any file the user can read | file text crossing the network lane stays inside the project | the model must be told the start directory, so a system message became part of every request | spec + PR review |
| the default model | a free model, `cohere/north-mini-code:free` | the paid `z-ai/glm-5.2` | zero cost per run | free models often answer 429/503, and depending on the provider may log prompts — file contents cross to a third party | spec Drift log, PR body |
| where settings live | one constants module, `nanocoder/config.py` | values spread through `agent.py` | one place to change the model, URL, turn cap and token cap | — | PR review comment |

## Step 6 — read the red

There is one red item: `nanocoder/config.py`, a file no box stands for. Its hunk:

```diff
+DEFAULT_MODEL = "cohere/north-mini-code:free"
+OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
+MAX_TURNS = 10
+MAX_TOKENS = 4096
```

`git log 8e768dc..5c847e6 -- nanocoder/config.py` shows it arrived in the review-fix commit
`16c14b1`, answering the comment *"constants should go into a separate file"*. One line of
judgment: **it belongs; the board is missing a box.** The spec already logged it as drift, so the
finding is that the plan board was not updated after review, not that the PR wandered. The
review does not redraw the plan board itself; that goes through `/task`.

## Step 7 — show it

Both review boards were served on free ports, and each port was checked for its own labels
before the URLs were given, because an HTTP 200 alone proves nothing:

```
port 51743: ["the user's machine · process boundary", 'internet · network boundary',
             'REVIEW 8e768dc..5c847e6 — running parts touched: 2: …']
port 51744: ['nanocoder repo (one process)',
             "REVIEW 8e768dc..5c847e6 — CHECK: slice-1-python against the spec's Build order", …]
```

## The report, in the output contract

**What's wrong** — `CHECK`: `nanocoder/config.py` lands on no box. One trade-off is flagged by
hand: the OpenRouter call has no timeout, so a stalled connection hangs the command.

**The fix** — add a `config.py` box to the plan board through `/task` (the spec already logged the
drift). The timeout is not a fix for this PR; it is issue #3, already filed.

**How it works** — the decisions table above, at most five rows in chat, the rest in the file.

## What this example shows

- **The building blocks are what make flags possible.** The old board had none of them, so the
  first `new` printed 15 warnings and no flag could have fired.
- **A flag can be the board's fault.** "OpenRouter waits on nanocoder" was wrong, and reading it
  aloud showed it. The fix was one arrow per call.
- **A passing flag check is not a pass.** An `on_fail` that says "no timeout" satisfies the check.
  The decisions table is where a person writes down whether that was chosen on purpose.
- **A plan from before the review is the honest plan.** Using the board from when the PR opened is
  what surfaced `config.py`: the PR grew during review, and the plan board did not.
