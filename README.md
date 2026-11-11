# spiral

Skills for building software with a coding agent without losing track of what it built. They
go with the post [Clearing the Context Haze](<!-- TODO: post URL -->), which explains why each
one exists.

The name comes from Barry Boehm's spiral model of software development (1986): plan a small
piece, test its riskiest assumption, review what came out, and plan the next loop from what you
learned. These skills are that loop, rebuilt for a coding agent.

The skills attack the haze from three sides. `/slice` keeps a design small enough to hold in
your head. `/draw` and `/builder-review` put the design and the change on a whiteboard you can
argue with. `/talk-like-me` makes the agent explain itself in sentences you can read once and
follow. The other five skills carry a slice from spec to merged PR.

## The nine skills

| Skill | Run it when | What you get |
|---|---|---|
| [`/slice`](slice/SKILL.md) | before writing code for anything non-trivial | a goal block, the thinnest end-to-end slice (at most three build steps), and one round of at most three questions |
| [`/draw`](draw/SKILL.md) | you want to see how something works, what a plan will touch, or where a bug goes | an Excalidraw board of at most 12 boxes, each a real file or process, that you and the agent both draw on |
| [`/implement`](implement/SKILL.md) | a spec's build steps are written | one step at a time, each ticked only after its `verify:` command passes |
| [`/test`](test/SKILL.md) | after implementing, before claiming it works | the whole suite run, failing test first, and a go/no-go verdict |
| [`/builder-review`](builder-review/SKILL.md) | before opening a PR, or on any PR an agent opened | the change coloured onto a system board and a code board, a table of the design decisions it made and what each costs, and whether it touched only what the plan said |
| [`/review`](review/SKILL.md) | after `/builder-review` | a line-level review of one pinned change, every finding with `path:line` and evidence that was run |
| [`/open-pr`](open-pr/SKILL.md) | review is clean | a PR description in the repo's own template, in plain sentences |
| [`/verify-ci`](verify-ci/SKILL.md) | the PR is open | READY or NOT READY: up to date with main, CI green, no conflicts |
| [`/talk-like-me`](talk-like-me/SKILL.md) | an answer turns into a wall of text, or always, through the hook | answers in complete sentences that name the real files first and carry one worked example |

## How they fit together

```
/slice ──▶ /draw (plan board) ──▶ /implement ──▶ /test ──▶ /builder-review ──▶ /review ──▶ /open-pr ──▶ /verify-ci
   ▲                                                                                                        │
   └──────────────────────── next slice, designed from what this one taught ────────────────────────────────┘
```

Every skill also works on its own. `/builder-review` on a teammate's PR, `/draw` to understand a
codebase, and `/talk-like-me` in any session need nothing else from this repo.

## Install

You need Python 3.10 or newer, `git`, and the GitHub CLI `gh` for the PR skills. The skills are
written for Claude Code and follow the [open skills standard](https://agentskills.io/specification),
so other agents can read them by path.

```sh
git clone https://github.com/anj-s/spiral.git ~/spiral
cd ~/spiral && ./workflow/install.sh
```

The installer symlinks each skill into `~/.claude/skills` and generates five helper agents into
`~/.claude/agents`. Start a new session afterwards. A `git pull` in `~/spiral` updates every
skill in place.

To have the `/talk-like-me` rules applied on every turn, install the hook as well. It edits
`~/.claude/settings.json` and writes a `.bak` first:

```sh
cd ~/spiral && ./workflow/install.sh --with-hook
```

The hook also adds an output contract and a short list of standing preferences. They are mine;
edit `CONTRACT` in [`workflow/hooks/inject-context.py`](workflow/hooks/inject-context.py) to make
them yours.

## Where specs and boards go

`/slice` writes each spec, and the boards beside it, into a separate git repo for notes, so
design history does not clutter the code repo. Set `SPEC_STORE` to that repo; it defaults to
`~/specs`. A spec lives at `$SPEC_STORE/projects/<project>/specs/<slug>.spec.md`.

The `/draw` board opens in your browser from a small local server on `127.0.0.1`. It loads
Excalidraw from unpkg; [`draw/SKILL.md`](draw/SKILL.md) says how to vendor it when unpkg is
blocked.

## What is in the repo

| Folder | What it holds |
|---|---|
| one folder per skill | `SKILL.md`, plus examples and scripts where the skill has them |
| `draw/scripts/` | `draw.py`, which writes and reads boards, and `draw_server.py`, which serves them; `/slice` and `/builder-review` use both |
| `agents/` | the five helper agents the skills dispatch: `spec-code-reader`, `spec-researcher`, `spec-drafter`, `code-mapper`, `spec-locator` ([how dispatch works](agents/README.md)) |
| `workflow/` | the installer, the agent generator and the optional hook ([details](workflow/README.md)) |

## License

[MIT](LICENSE)
