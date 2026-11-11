#!/usr/bin/env bash
# Link the spiral skills into ~/.claude/skills and generate their subagents into
# ~/.claude/agents. Optionally add the hook that injects the talk-like-me rules into
# every turn. Nothing here can block a prompt, a tool call, or a turn.
#
#   ./install.sh               install skills + agents (idempotent, safe to re-run)
#   ./install.sh --with-hook   also merge the context hook into settings.json
#   ./install.sh --uninstall   remove the hook and generated agents
#
# Env:
#   CLAUDE_SETTINGS      settings.json to merge hooks into  (default ~/.claude/settings.json)
#   CLAUDE_SKILLS_ROOT   where skills are symlinked         (default ~/.claude/skills)
#   CLAUDE_AGENTS_ROOT   where agents are generated         (default ~/.claude/agents)
#   EXTRA_SKILLS_ROOTS   space-separated extra roots to link skills into, for a second
#                        harness that discovers skills elsewhere (default: none)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOK="$HERE/hooks/inject-context.py"
MERGE="$HERE/hooks/merge-settings.py"
GEN="$HERE/gen-agents.py"
SETTINGS="${CLAUDE_SETTINGS:-$HOME/.claude/settings.json}"
SKILLS_ROOT="${CLAUDE_SKILLS_ROOT:-$HOME/.claude/skills}"
AGENTS_SRC="$HERE/../agents"
AGENTS_ROOT="${CLAUDE_AGENTS_ROOT:-$HOME/.claude/agents}"
MARKER="workflow-v2:inject-context"

for f in "$HOOK" "$MERGE" "$GEN"; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done
chmod +x "$HOOK" "$MERGE" "$GEN"

MODE="install"
[ "${1:-}" = "--uninstall" ] && MODE="uninstall"
WITH_HOOK=0
[ "${1:-}" = "--with-hook" ] && WITH_HOOK=1

mkdir -p "$HOME/.local/state/workflow"
# The hook edits settings.json, so it is opt-in; uninstall always removes it.
if [ "$MODE" = "uninstall" ] || [ "$WITH_HOOK" = 1 ]; then
  python3 "$MERGE" "$SETTINGS" "$HOOK" "$MARKER" "$MODE"
fi

# Skills are symlinked, so edits in this repo are live immediately. Harnesses that
# follow symlinks during skill discovery pick the change up with no re-install.
link_skills() {
  local root="$1"
  mkdir -p "$root"
  # Two levels: a skill sits at <repo>/<name>/, or inside a grouping folder at
  # <repo>/<group>/<name>/ (the group itself has no SKILL.md and is skipped).
  for s in "$HERE"/../*/ "$HERE"/../*/*/; do
    [ -f "${s}SKILL.md" ] || continue
    local dest="$root/$(basename "${s%/}")"
    # A pre-existing real dir makes ln nest the link inside it instead of replacing it.
    [ -L "$dest" ] || rm -rf "$dest"
    ln -sfn "${s%/}" "$dest"
  done
  return 0
}

# Subagents are GENERATED, not symlinked: the sources carry name+description
# frontmatter only (some skill parsers ignore anything else) while Claude Code
# needs tools+model in frontmatter, and a symlink cannot add frontmatter.
python3 "$GEN" "$AGENTS_SRC" "$AGENTS_ROOT" "$MODE"

if [ "$MODE" = "install" ]; then
  link_skills "$SKILLS_ROOT"
  for extra in ${EXTRA_SKILLS_ROOTS:-}; do
    link_skills "$extra"
  done
  echo "done. start a NEW session for the hook and the agents to load."
else
  echo "done. hooks and generated agents removed; skill symlinks left in place."
fi
