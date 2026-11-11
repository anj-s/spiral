# workflow — install, agents and the optional hook

This folder holds the scripts that connect the skills to an agent harness. Everything here uses
only the Python standard library.

| File | What it does |
|---|---|
| `install.sh` | Symlinks every skill folder into `~/.claude/skills`, generates the agents into `~/.claude/agents`, and with `--with-hook` merges the context hook into `~/.claude/settings.json` |
| `gen-agents.py` | Turns each `../agents/<name>.md` into a Claude Code subagent by adding the `tools` and `model` frontmatter Claude Code needs. It writes a `GENERATED` marker and never touches an agent file it did not generate |
| `run-agent.py` | Fills one agent's `{{inputs}}` and either prints the prompt or runs it as a fresh `claude`, `codex` or `gemini` process, for harnesses with no subagents |
| `hooks/inject-context.py` | The optional hook. On every prompt it adds an output contract, a few standing preferences and the writing rules from `talk-like-me/SKILL.md`. Edit `CONTRACT` in this file to make it yours |
| `hooks/merge-settings.py` | Adds or removes the hook entries in `settings.json`, writing a `.bak` first and leaving every other key alone |

## Install

```sh
cd ~/spiral && ./workflow/install.sh               # skills + agents
cd ~/spiral && ./workflow/install.sh --with-hook   # also the context hook
cd ~/spiral && ./workflow/install.sh --uninstall   # remove the hook and generated agents
```

Start a new session afterwards so the agents and the hook load.

## Settings

| Variable | Default | Used for |
|---|---|---|
| `SPEC_STORE` | `~/specs` | The git repo where `/slice` writes specs and boards: `$SPEC_STORE/projects/<project>/specs/` |
| `CLAUDE_SETTINGS` | `~/.claude/settings.json` | Where `--with-hook` merges the hook |
| `CLAUDE_SKILLS_ROOT` | `~/.claude/skills` | Where skills are linked |
| `CLAUDE_AGENTS_ROOT` | `~/.claude/agents` | Where agents are generated |
| `EXTRA_SKILLS_ROOTS` | none | More folders to link skills into, for a second harness |
