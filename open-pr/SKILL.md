---
name: open-pr
description: >
  Creates a GitHub PR with a structured description. Use after /review returns no
  blockers.
parameters:
  draft:
    type: boolean
    description: Whether to create the PR as a draft.
    default: false
  title:
    type: string
    description: Explicit title for the PR. If not provided, it will be generated.
    required: false
---

# Open PR

Creates a GitHub pull request with a well-structured description, linking related issues and setting reviewers automatically.

**Prerequisites**: Tests pass, review has no blockers, branch is pushed to origin.

## When to invoke

- After `/review` returns "READY TO PR".

## What this skill does

1. Verifies the branch is pushed (`git status` + `git push` if needed).
2. Generates a PR description from commits and spec.
3. Scans commits for issue references (`#NNN`, `closes #NNN`, `fixes #NNN`).
4. Sets reviewers from `.github/CODEOWNERS` if it exists.
5. Creates the PR via `gh pr create`.
6. Prints the PR URL.

## PR Description Template

**The repo's own template always wins.** Before composing a body, check for
`.github/PULL_REQUEST_TEMPLATE.md` (or `.github/pull_request_template.md`, or
`docs/PULL_REQUEST_TEMPLATE.md`) in the repo root. If one exists, use *its*
sections verbatim — do not substitute the generic shape below, and do not
invent extra sections. Honor any length limits it states.

A `.github/PULL_REQUEST_TEMPLATE/` directory holds per-subtree alternates. Pick the
one matching what the diff touches (for example `api.md` for changes under `api/`,
the root `PULL_REQUEST_TEMPLATE.md` otherwise; a PR touching both keeps the sections of
both).
`gh pr create -T <name>.md` selects it interactively; with `--body-file`, copy its
sections into the body yourself.

Two rules that apply whatever the shape:

- **Respect the summary cap.** If the template caps the summary — some cap it at
  a few hundred characters, "one tight paragraph, not a changelog" — stay under
  it. Detail belongs in the diff, not the description.
- **Tick only what you actually did.** Mark N/A rather than ticking blind. Never
  tick a docs/marker-bump box without having bumped the markers.

## The Summary is always written the same way

Every PR's summary uses the same three parts, whatever the repo's template calls the section
(`## Summary`, `## What`, the opening paragraph). The template decides the sections around it; this
decides what goes inside the summary. Updating the body on a later push keeps the same shape.

```markdown
**What's wrong:** <1-2 sentences: what is missing or broken today, named in everyday words>
**The fix:** <1-2 sentences: what this PR changes>
**How it works:**
- <up to 5 bullets, one sentence each: the behaviour a reviewer should expect>
```

| Rule | Because |
|---|---|
| Write sentences, read aloud, no fragments (`/talk-like-me`) | the connective words (*so*, *because*, *only when*) are the explanation |
| Name the real things first: the file, the command, the setting a user touches | a reviewer cannot follow a mechanism whose parts they cannot name |
| No code identifier used as English; if one must appear, say what it is in the same sentence | `drain()` means nothing to a reader of the PR list |
| A feature still has a "What's wrong": what a user cannot do today. Drop a slot only when filling it would be padding | the reader needs the before as much as the after |
| Stay under the template's cap; count with `wc -m` | detail lives in Testing, the spec and the diff, not the summary |
| Test counts and docs go in their own sections, not the summary | the summary says what changed, not how it was checked |
| Never mention review results, slices or step numbers, specs, boards or skill names (`/review`, builder review) in the title, body or comments | the PR describes the change; how the work was organised is not its business |

Worked example (a fictional CLI, 526 characters against a 600 cap):

```markdown
**What's wrong:** `notes sync` re-downloads every note on each run, so a large notebook takes
minutes to sync even when nothing changed.
**The fix:** sync now keeps a small file recording when each note was last fetched, and asks the
server only for notes changed since then.
**How it works:**
- The first sync after upgrading still fetches everything, then writes the file.
- A failed sync leaves the file untouched, so the next run retries from the same point.
- `notes sync --full` ignores the file and fetches everything.
```

Fall back to this generic shape *only* when the repo has no template of its own:

```markdown
## Summary
**What's wrong:** <...>
**The fix:** <...>
**How it works:**
- <...>

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] Breaking change

## Related Issues
Closes #NNN

## Test Plan
- [ ] Unit tests pass (`npm test` / `pytest` / etc.)
- [ ] Manually verified: <brief description of what you tested>

## Notes for Reviewer
<Any context that isn't obvious from the code or commit messages>
```

## Instructions for Claude

When this skill is invoked:

1. **Branch Hygiene**:
   - Run `git status` — if there are uncommitted changes, warn and ask if they should be committed first.
   - Run `git log origin/HEAD..HEAD --oneline` — if empty, warn that no commits are ahead of origin.
   - Check if branch is pushed: `git rev-parse --abbrev-ref --symbolic-full-name @{u}`. If error, push with `git push -u origin HEAD`.

2. **Metadata Generation**:
   - **Title**: If `title` is provided, use it. Otherwise, generate one from the most descriptive commit message. Keep under 72 characters.
   - **Summary**: Read `git log origin/HEAD..HEAD --format="%s %b"` and the spec if there is one, then write it in the three-part shape from "The Summary is always written the same way". Obey the repo template's length cap and check it with `wc -m`.
   - **Type of Change**: Detect from diff and commits. Skip this section entirely if the repo's own template doesn't have it.
   - **Related Issues**: Scan for `#\d+`, `closes #\d+`, etc. Ask user for any missing ones.

3. **Reviewer Assignment**:
   - Look for `.github/CODEOWNERS`.
   - If found, extract owners for changed files and add to `gh` command.

4. **Review & Confirm**: Show the full PR description to the user and ask for confirmation.

5. **PR Creation**:
   - Run:
     ```bash
     gh pr create \
       --title "<title>" \
       --body "<description>" \
       [--draft] \
       [--reviewer <owner1,owner2>]
     ```
   - If `gh` command fails (e.g., auth error, no upstream), report clearly.

6. **Next Steps**:
   - Print the PR URL.
   - Print: "PR opened. Run /verify-ci to track CI status."
