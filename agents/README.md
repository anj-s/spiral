# agents — one source, any harness

Every subagent the skills dispatch lives here as `<name>.md`. The file is the single source of
truth; nothing in it is specific to Claude Code, and it runs on a harness that has never heard of
subagents. This page is the contract that keeps that true, and what "dispatch `<agent>`" means
wherever a skill says it.

## The source format

| Part | Rule | Why it is portable |
|---|---|---|
| Frontmatter | `name` + `description` **only** | the subset every skill/agent parser reads; anything richer is ignored by some and rejected by others |
| Body | `**model:**` (`haiku\|sonnet\|opus`), `**tools:**` (bare tool names), `**runs:**` (which skill, which phase) | hints a harness may honour, in prose no parser chokes on |
| Prompt | one fenced block under `## Prompt`, no nested fence | the whole prompt is one copyable unit |
| Inputs | `{{snake_case}}` placeholders inside the prompt | discovered, not declared — `run-agent.py <name> --list-inputs` |
| Output | a stated shape at the end of the prompt (markdown headings or a JSON object) | the orchestrator feeds it to the next agent as an input on any host |

Validation is `workflow/gen-agents.py` (`install.sh` runs it); it refuses to write on any violation.

## The rules every prompt obeys

1. **Self-contained.** No "as discussed", no reference to another agent's reasoning. A fresh process
   has no shared context, and that is the case the prompt is written for.
2. **Never talks to the user.** Questions come back as data (the locator's JSON), and the
   **main agent** asks them. Claude Code strips `AskUserQuestion` from subagents; a CLI process has
   no user; inline would make the user's experience differ per host. So: no agent ever asks.
3. **Correct sequentially.** Parallel dispatch is an optimisation the orchestrator may take. No
   prompt depends on another agent running at the same time.
4. **Tools and model are hints.** A host that cannot scope tools or pick a model per agent runs the
   prompt with what it has. The prompt must still make sense there.
5. **Returns the stated shape, and nothing else.** Preamble in the output breaks the next input.

## The dispatch ladder — what "dispatch `<agent>`" means

A skill names the agent and its inputs and never the mechanism. The orchestrator takes the **first
rung available**:

| Rung | Where | How |
|---|---|---|
| 1 native | Claude Code | `Agent` tool with `subagent_type: <name>` — the generated `~/.claude/agents/<name>.md` |
| 1 native | other harnesses with native subagents | not generated from this source yet (parked) |
| 2 process | any harness with a shell — Codex, Gemini CLI, Copilot, a plain terminal, and Claude Code when a fresh context is wanted | `python3 ~/spiral/workflow/run-agent.py <name> --var k=v … --backend claude\|codex\|gemini` or `--backend cmd --cmd '<argv>'`; prompt on stdin, output on stdout, exit code propagated |
| 3 inline | no subagents, no CLI | `python3 ~/spiral/workflow/run-agent.py <name> --var k=v …` prints the filled prompt; the orchestrator executes it as its own next step |

```sh
# render (rung 3) — the filled prompt, ready to run as your next step
python3 ~/spiral/workflow/run-agent.py spec-code-reader \
    --var task_brief="$BRIEF" --var repo_path="$(git rev-parse --show-toplevel)"

# process (rung 2) — a fresh claude process, output saved for the next agent's input
python3 ~/spiral/workflow/run-agent.py spec-code-reader \
    --var task_brief="$BRIEF" --var repo_path="$PWD" --backend claude --out /tmp/ground-truth.md
python3 ~/spiral/workflow/run-agent.py code-mapper \
    --var task_brief="$BRIEF" --var repo_path="$PWD" --var mode=as-is --var level=code \
    --var plan='(none)' --backend claude
```

A missing input exits 2 and names it. `--allow-missing` leaves the `{{placeholder}}` in place, for a
prompt you intend to finish by hand.

## What each rung loses — say so in the report

| Rung | Loses | Consequence |
|---|---|---|
| 1 native | nothing the source promises; per-agent model only where the host supports it | — |
| 2 process | the session: no shared context, no memory of earlier turns. Tool scoping only where the CLI accepts it (`claude -p --allowedTools`; not codex/gemini) | pass everything the agent needs as inputs; nothing else changes |
| 3 inline | **independence.** A critic run inline has read the proposers' context | its report should say `ran inline`; weight the verdict accordingly (parked: make the prompt say it) |

Prompt budgets differ per host: a long input that survives intact on one may be truncated on
another. Keep agent outputs under the caps their prompts state (the code reader's 400 words, the
researcher's 350).

## The five agents and their inputs

| Agent | Dispatched by | Inputs |
|---|---|---|
| `spec-code-reader` | `/slice` phase 0 | `task_brief`, `repo_path` |
| `spec-researcher` | `/slice`, only on request or across an external-API boundary | `task_brief`, `initial_direction` |
| `spec-drafter` | its rules are the spec skeleton `/slice` writes | `task_brief`, `spec_path`, `code_reader_output`, `researcher_output`, `qa_history` |
| `code-mapper` | `/draw`, `/builder-review` | `task_brief`, `repo_path`, `mode`, `level`, `plan` |
| `spec-locator` | `/builder-review` and `/implement`, to find the active spec | none |

## Adding an agent

1. `agents/<name>.md` in the format above. 2. `./workflow/install.sh` (validates and generates).
3. `run-agent.py <name> --list-inputs` — every input has an obvious setter in the table above, or
add a row. 4. The skill that dispatches it says "dispatch `<name>` with `<input>` = …" and no more.
