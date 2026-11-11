#!/usr/bin/env python3
"""Inject the output contract + standing preferences into every turn.

Context-injection only: this hook can never block a prompt, a tool call, or a
turn. Worst case it adds ~570 tokens and is ignored.

The writing rules are NOT stored here. They are read at runtime from the fenced
block in talk-like-me/SKILL.md, which is their only copy, so editing the skill
updates what every turn sees. A missing or unfenced skill falls back to a single
pointer line rather than to a stale duplicate of the rules.

Wired to UserPromptSubmit (every turn, so it survives /compact) and
SubagentStart (so subagents inherit the contract too).

SPEC_STORE names the notes/spec repo that artifacts are written to; it is
interpolated at runtime so this file carries no hardcoded personal path.
"""
import json
import os
import sys
from pathlib import Path

STATE = os.path.expanduser("~/.local/state/workflow/active-spec")
SPEC_STORE = os.environ.get("SPEC_STORE") or "~/specs"

# hooks/ -> workflow/ -> the repo root, so this resolves whether the hook is
# invoked by its real path or through the ~/.claude symlink.
SKILL = Path(__file__).resolve().parents[2] / "talk-like-me" / "SKILL.md"
FENCE_START = "<!-- hook-summary:start -->"
FENCE_END = "<!-- hook-summary:end -->"

WRITING_FALLBACK = (
    "## How to write it (standing — /talk-like-me)\n\n"
    "Invoke /talk-like-me for the rules before any long or teaching answer.\n"
)

CONTRACT = f"""\
## Output contract (standing — do not restate, just follow)

Structure every explanation, PR description, PR/issue comment and commit body as:
  **What's wrong** — 1-2 lines.
  **The fix** — 1-2 lines.
  **How it works** — <=5 bullets, one line each.
Omit any slot that is empty; never pad one. No preamble before the first slot, no
summary after the last. This is a demarcation rule, not a minimum length — a
one-line answer stays one line. Never emit walls of undifferentiated prose.

## Standing preferences (already established — never ask, never restate)

- Artifacts (specs, reports, audits, designs) go in {SPEC_STORE}, never a plan
  file or a job tmp dir. Commits there go straight to main: no branches, no PRs.
- Prefer subagents for fan-out: broad searches, log trawls, multi-file sweeps.
- Design before code for anything non-trivial. Read the code before writing the design.
- Code comments and PR bodies: 1-2 lines each, clear and concise, never paragraphs.
- Docs change with code — where the repo has a docs/SSOT checklist it is not optional.
- Never add AI-attribution trailers (no Co-Authored-By, no robot emoji) to commits,
  PRs or issues.
- A passing test is evidence about code, not about the product. Run the thing.
"""


def writing_rules() -> str:
    """The condensed writing rules, read from the skill's fenced block.

    The skill owns this text; the hook only points at it. Any failure — the file
    gone, the fences missing, the block emptied — degrades to one pointer line,
    which is the safe direction: a stale copy would be worse than a pointer.
    """
    try:
        body = SKILL.read_text(encoding="utf-8").split(FENCE_START, 1)[1].split(FENCE_END, 1)[0]
    except (OSError, IndexError):
        return WRITING_FALLBACK
    body = body.strip()
    return f"{body}\n" if body else WRITING_FALLBACK


def active_spec() -> str:
    try:
        with open(STATE, encoding="utf-8") as fh:
            path = fh.read().strip()
    except OSError:
        return ""
    if not path:
        return ""
    return (
        f"\n## Active spec\n\n`{path}` is the control document for this task. "
        "Re-open it before implementing, tick a box only after running that step's "
        "`verify:` command, and record any divergence in its Drift log.\n"
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    event = payload.get("hook_event_name") or "UserPromptSubmit"
    if event not in ("UserPromptSubmit", "SubagentStart"):
        event = "UserPromptSubmit"

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": CONTRACT + "\n" + writing_rules() + active_spec(),
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    # Never let this hook take a session down: any failure degrades to no-op.
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
