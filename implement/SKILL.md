---
name: implement
description: >
  Turns a spec into committed code one task at a time. Use after /slice or
  a design has produced a spec and you are already checked out on the correct
  branch. A spec's Build order is the task list; each step's verify: gates its tick.
parameters:
  spec_path:
    type: string
    description: Path to the spec.md file to implement.
    required: false
---

# Implement

Turns a spec into committed code, one small task at a time.

**Prerequisite**: You are already in a git worktree on the correct branch. If not, set that up before invoking this skill.

## When to invoke

- After `/slice` has written the next slice, or a full design a whole spec.
- When you want structured, checkpoint-driven implementation.

## What this skill does

1. Reads the spec (asks where it is if not found automatically).
2. Takes the spec's `## Build order` as the task checklist (decomposes only when a spec has none).
3. Presents the checklist for confirmation when it has more than three unticked steps.
4. Implements each task, then:
   - Runs linter (auto-detected from project config).
   - Runs type-checker if applicable.
   - Commits with message referencing the task (`impl: <task description>`).
5. Marks each task complete as it finishes.
6. Prints a summary of all commits made.

## Instructions for Claude

When this skill is invoked:

1. **Spec Discovery** (in this order, stop at the first hit):
   - `spec_path`, if provided.
   - `~/.local/state/workflow/active-spec` — the path `/slice` writes; if it
     names a file that exists, use it and say which spec.
   - `$SPEC_STORE/projects/<project>/specs/*.spec.md` with unticked build steps (default store
     `~/specs`); legacy `.specs/` and a root `spec.md` after that.
   - If several match or none, ask the user which — by title, never by filename.

2. **Analysis**: Read the spec and extract Requirements (or Acceptance Criteria), Build order and Architecture impact.

3. **Decomposition**:
   - If the spec has a `## Build order`, **that is the checklist** — take its unticked steps in
     order and do not re-decompose. A `/slice` spec has at most three, so skip the confirmation
     below and start; confirm only when there are more than three unticked steps.
   - Otherwise decompose into an implementation task checklist.
   - Each task should be:
     - Atomic: small enough to implement and commit in one step (roughly 10-50 lines of code).
     - Testable: independently verifiable.
     - Ordered: foundational work first.
   - Print the checklist and ask: "Does this task breakdown look right? Any changes before I start?"

4. **Iterative Implementation**:
   - Wait for confirmation, then implement tasks one by one.
   - For each task:
     a. Announce: "Starting task N: <description>"
     b. Write/edit the necessary code.
     c. **Validation**:
        - Run linter: detect from `package.json` (`lint`, `eslint`), `Makefile` (`make lint`), `.pre-commit-config.yaml`, or `pyproject.toml` (`ruff`, `flake8`).
        - Run type-checker: `tsc --noEmit`, `mypy`, `pyright`.
        - If the step carries a `verify:` clause, **run it and paste the real output**. The step is
          ticked in the spec only after that command exits 0; `verify: DISCUSS` is raised with the
          user, never ticked. If reality differed from the step, add a Drift log line
          (`MM-DD: step N needed X instead of Y; <why>`) instead of silently diverging.
        - If validation fails, attempt to fix it. If unable to fix, stop and report the blocker.
     d. **Commit**:
        - `git add -p` (stage only task-relevant files).
        - `git commit -m "impl: <task description>"`.
        - Tick the step in the spec and commit the spec to the store's `main` (the spec lives in
          `$SPEC_STORE`, a different repo from the code — two commits, no AI-attribution trailer).
        - If commit fails, inform the user.
     e. **Completion**: Mark task complete: "✓ Task N done".

5. **Final Summary**:
   - After all tasks:
     - Print list of all commits made (`git log --oneline origin/HEAD..HEAD`).
     - Print: "Implementation complete. Run /test to verify, then /review before opening a PR."
     - If the spec carries a goal block (a `/slice` spec), add: "Slice N built. After /test and
       /verify-ci pass, run /slice for the next slice."

6. **Error Handling**:
   - If a task fails (lint errors you can't fix, test failures introduced):
     - Stop and report the blocker clearly.
     - Do not commit broken code.
     - Ask the user how to proceed.
