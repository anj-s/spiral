---
name: review
description: >
  Line-level code review of one pinned change (the current branch, a PR, or a base..head range)
  in any language. It names the exact commits it read, writes down what the change claims, then
  answers five questions: does it do what it says, what else did it change, where does it break,
  would the tests catch it if it were wrong, and do the comments, docs and PR text still match the
  code. Every finding carries path:line, a concrete failing scenario and evidence that was run.
  Use after /test and before /open-pr, on any PR an agent opened, and whenever the user asks to
  review a PR, a branch, a diff or "my changes". Not the plan check (/builder-review), not a
  style pass.
---

# review

`/review [<PR> | <branch> | <base>..<head>]` → a verdict line, findings with evidence, what was
checked and found fine, and which gates ran, for exactly one change. With no argument it reviews
the current branch from the point where it left the default branch.

Not this skill: whether the right files changed at all (`/builder-review`, which runs first when a
plan board exists), whether the suite passes (`/test`), or formatting and lint (the repo's own
tools answer those; the review records their exit codes and never re-checks by eye).

## What a review is for

A review answers one question for whoever merges: **is this change safe to land, and does it do
what it says?** Tests and CI only catch what someone thought to test. The review is the step that
reads the code for the failure nobody thought to test, while fixing it still costs a local commit
instead of a pushed branch, a revert, or an eval run on broken code.

It asks five questions, in this order. Each example is a real miss that a review caught and the
tests did not.

| # | Question | What a "no" looked like |
|---|---|---|
| 1 | **Does it do what it says?** | the fix landed on the path that starts a subagent, and the path that resumes one still ran shell commands without asking for approval |
| 2 | **What else did it change?** | a fix left ungraded runs out of a rate, and the score that candidates are ranked on stayed a point short |
| 3 | **Where does it break?** | pasting a two-line stack trace into a form submitted it after the first line |
| 4 | **Would the tests catch it if it were wrong?** | three tests passed only because they fed in data of a shape the real code never produces |
| 5 | **Do the words still match the code?** | a comment called startup single-threaded, and a database had already started its background threads |

A review is **not** for taste, formatting, restating the diff, or a checklist of hazards the change
cannot reach. Do not report SQL injection in a diff with no SQL. A finding names a scenario in this
change; a line that could be pasted into any review is noise.

## Step 1 — pin the change before reading a line

A review of the wrong diff reads as a pass, which is worse than no review. It has happened three
times in one project: a review aimed at one change read something else instead, once a spec, once
another branch's files, and once a different worktree. So the review starts by turning the request
into two commit SHAs.

| Asked for | Base | Head |
|---|---|---|
| a PR number or URL | the merge base of the PR head with its base branch | the PR's head SHA: `git fetch origin pull/<n>/head:pr-<n>`, or the GitHub MCP `pull_request_read` when there is no clone |
| a branch | `git merge-base origin/<default> <branch>` | the branch tip |
| `A..B` | A | B |
| nothing | `git merge-base origin/<default> HEAD` | `HEAD`, plus uncommitted changes, listed separately |

`<default>` is what `git symbolic-ref --short refs/remotes/origin/HEAD` says, never an assumed
`main`. Fetch first, because a stale `origin/<default>` puts other people's merged work into the
diff. When the request could mean two different changes, such as a local branch that has drifted
from its PR, ask one question instead of picking.

Every review opens with this line, plus `+ uncommitted changes in <k> files` when there are any:

```
Reviewing <repo> <base-sha>..<head-sha> · <n> commits · <m> files · +<added>/−<removed>
```

An empty range is the whole answer: `Nothing to review between <base> and <head>.`

When the change has a plan board, run `/builder-review` on the same range now. `RIGHT THING` gets
one line in the report. `CHECK` means each unplanned box, file outside the board, or unplanned
boundary crossing is a blocker. It stays one until the spec and board are updated (log the
drift) or the change is trimmed; paste its table under the findings. No board → write "no plan
board", so the gap is visible.

## Step 2 — write down what the change claims, before reading the diff

Question 1 needs something to check against, and it has to be written first: once the diff has been
read, every claim bends to fit it. Collect the claims from, in order of weight:

1. the linked issue, with its symptom and its repro steps;
2. the active spec step (`~/.local/state/workflow/active-spec`), with its requirements and `verify:` line;
3. the PR title and body;
4. the commit messages.

Write them as a numbered list, one checkable sentence each: "pasting a two-line trace into the
bug form files both lines", not "improves the bug form". A change that claims nothing anywhere
(no body, commits named `wip` and `fix`) is itself a warning. Review it against what the diff
plainly intends, and say that is what you did.

Then read the repo's own rules for what counts as correct there: `CLAUDE.md`, `AGENTS.md`,
`CONTRIBUTING.md`, `REVIEW.md`, any invariants or conventions doc, and the PR template's checklist.
This skill carries no language rules, so those files are where language and project rules come from.
A finding that rests on one of them quotes it.

## Step 3 — answer the five questions

Read the whole diff once before writing any finding. Then take the questions in order.

A diff past about 400 changed lines is too big for one careful pass; the Cisco code-review study
run by SmartBear found that reviewers' defect-finding drops off beyond that size. Split it by
question instead: one reviewer per question, dispatched by the first rung available in
`agents/README.md`, each given the same two SHAs, the claims list and the evidence rules below.
Re-verify every finding before it enters the report, and list any file that was only skimmed under
Not reviewed.

### 1. Does it do what it says?

- Check each claim from step 2 against the code, and mark it held, partly held, or not held.
- For a bug fix, reproduce the bug on the base and show it gone on the head. A fix you have not
  seen fail and then pass is a fix you are taking on trust.
- Find every place the bug can happen, not only the one the issue names. The usual miss is a second
  path doing the same job: creating a thing and resuming it, the streaming and the non-streaming
  client, interactive and headless mode, a library and the CLI wrapped around it. Search for the
  other callers and list them in the report.
- If a user can see the change, run the built program once the way a user would and paste what it
  showed. A passing test is evidence about the code, not about the product.
- Compare the title's scope with the diff's. A PR titled "step 4" that also ships steps 5 and 7 is
  reviewed as all three, and the report says so.

### 2. What else did it change?

The diff shows where a change was made, and bugs usually show up where it lands. Follow every
changed value and behaviour to everything that reads it.

| If the diff… | Then check |
|---|---|
| changes a value that other code computes from | every number or decision derived from it, not only the one the change was about |
| starts *using* a value that was only displayed or logged before | the old code that produces it: a parsing bug that only printed wrong starts making wrong decisions |
| makes a path run more often, on every start or every request | the crashes and slow calls on that path that used to be rare: panics, unchecked unwraps, asserts, uncaught exceptions |
| adds a guard, an early return, or a new condition | that the branch it sits in front of can still be reached; a correct design behind one bad guard is dead code |
| replaces or removes a caller | that the old function, flag or setting is deleted, not left callable; an orphan that still grants something is a hole |
| changes a stored format, an event, a wire message or a public API | old data still reads, old sessions still replay the same way, and older or newer peers still understand it |
| changes a prompt, a schema, a default or rendered output | the snapshot and golden files that pin it moved in the same diff; search them for the changed text |
| adds or removes a command, tool, flag, setting or type | every registry, enum, help text, completion list and doc page that lists them |
| adds files | they are in the build: declared as a module, listed in the package, found by the test runner. CI stays green without a file it never compiles |
| fixes something and refactors on the way | the refactor on its own, bounds and limits especially; a side change inside a fix gets the fix's benefit of the doubt |
| is one of several open PRs on the same files | merge them together in a scratch worktree and run the suite; each is green on its own branch, and the bug may exist only in the combination |

### 3. Where does it break?

Hunt for the failure the author could not see. For each changed function, try the inputs and states
its tests do not:

- **The edges of the input.** Empty, one, many and huge; missing and malformed; paths that are not
  valid UTF-8; text whose on-screen width differs from its length; symlinks, relative paths, and an
  unset `HOME`.
- **The error paths.** What the caller sees when the new code fails, and whether the failure is
  reported, retried, swallowed, or turned into a crash.
- **Limits.** A cap must be checked before the work it bounds; a size check after the read is not a
  cap. Anything that grows with use (a cache, a history, a list of handles) has a bound.
- **Untrusted input.** Anything from a file, argv, the environment, the network or a model's output
  that reaches a decision is parsed, not pattern-matched, and it is bounded. Look hardest at trust and
  permission gates, secrets, and the permissions on files the change writes.
- **Time and concurrency.** Slow work (disk, hashing, subprocesses, a scan of a whole store) stays off
  the thread that draws the UI or serves requests. Work repeated per item, such as a query inside a
  loop, is done once where it can be. State that two threads, tasks or processes touch is ordered by
  something, or one of them loses its write. Cancellation (Ctrl+C, abort, a timeout) still stops
  every path the change touched.
- **Logging.** Each new log line tells someone what to do, and none fires on every iteration. No
  condition is computed only so that it can be logged.

### 4. Would the tests catch it if it were wrong?

A test is only evidence if it can fail. For each test the change adds or relies on:

- It fails on the parent commit and passes on the head, for the reason its name gives. Run it both
  ways and paste both results; a regression test that also passes on the parent proves nothing.
- It drives the path that actually failed. A test of a helper does not cover a bug in its caller.
- Its fixture is shaped the way the real code produces data. A test that injects a shape production
  never emits passes forever.
- Its assertion is as strong as its message. A `>=` under a message that says "precedes" still
  passes with the order broken.
- It is not sized off the constant it tests, and it does not run only at the one width, count or
  timezone where the bug happens not to show.
- Where it is cheap, break the code on purpose (delete the new line, flip the condition) and watch a
  test go red. A change that no test notices is untested, however many tests were added.

A test that is skipped, commented out or loosened to get green is a blocker.

### 5. Do the words still match the code?

A comment, doc or PR body that the change made false will mislead the next reader, and the review is
usually the only step that compares the words with the code.

- Comments on changed code, safety and invariant comments above all: "only runs single-threaded",
  "cannot be reached", "the caller already checked this".
- Docs that describe the changed behaviour, and any "planned follow-up" note the change just shipped.
- A list or rule that exists in two places. The diff usually updates one of them.
- The PR body and commit messages, claim by claim. A census stated as complete ("called from X and
  nowhere else") has to be complete.

## Evidence — prove each finding, or mark it

Reviewers, human or agent, are reliably right that an area has a problem and often wrong about what
it is. In one project's audits the real defect sat next to the claimed one five times out of five.
So each finding is held to these rules.

| Rule | Because |
|---|---|
| every finding carries `path:line`, the scenario (this input or state → this wrong result), and the evidence | "this might be a problem" gives the author nothing to reproduce |
| evidence is output you ran: a probe, a failing test, or the program's own output. Paste it, then delete the probe | described output is invented output |
| a claim you could not run is written `UNVERIFIED:`, with what would settle it | the reader needs to know how much weight it bears |
| "this is fine" needs a positive control: put the bug back and show your check catches it | a check that cannot fail proves nothing in either direction |
| an argument that a case is unreachable is checked against what is about to merge, not only against the diff | one such argument was true about the code and false as soon as the next PR landed |
| every number carries its arithmetic | a reader can check a sum, but not a bare number |
| a bug in code the change did not touch is labelled `pre-existing` and checked on the base. It blocks only if this change makes it reachable | the author should not have to fix the world to land one change, but must not make it worse |
| a subagent's finding is re-verified before it enters the report | the report is yours, and an agent's confidence is not evidence |

## Gates — record what ran, never what should have

The review does not replace `/test` or CI, but it states what they said, because a review of code
that does not build is a different review. Run the build, lint and format commands that CI runs
(read the CI workflow file rather than guessing) and the tests for the code that changed, then read
CI's result on the head SHA. The full-suite result can come from a `/test` run on the same SHA.

| Rule | Because |
|---|---|
| take each exit code from the command itself, never from the end of a pipe | `cmd \| tail; echo $?` reports `tail`'s status, and that once hid a failing format check |
| never filter a failure list down to a count or a header | a filter once swallowed the name of the test that failed |
| a failure is pre-existing only if it fails the same way on the base | "flaky" is a claim; run it on the base and paste both |
| anything not run is written as not run, with the reason | "CI not read: no GitHub access" is honest; silence reads as green |

## Severity and verdict

| Level | Means | For example |
|---|---|---|
| **blocker** | fix before the PR opens, or before it merges | wrong behaviour a user or caller will hit; data loss; a security hole; the change does not do what it claims; the only test of the main claim cannot fail |
| **warning** | fix in this PR, or list it in the PR body as known and file it | an edge case with a named trigger; a stale comment, doc or PR claim; a missing test for a real path; a pre-existing bug nearby |
| **suggestion** | the author's call | a simpler shape, such as one fix point instead of five copies; a name that misleads; a cost nobody has measured yet |

Severity follows what goes wrong, not which question found it. The verdict is `READY TO PR` (a local
branch with no blockers; next is `/open-pr`), `READY TO MERGE` (an open PR with no blockers), or
`NEEDS FIXES — <n> blocker(s)`.

## The report

When the review has any finding, write it in full to
`$SPEC_STORE/projects/<project>/reviews/<YYYY-MM-DD>-<pr-N or branch>-<slug>.md` and commit it to the
store's `main`. The project is the one this repo's work is filed under; ask rather than invent one.
A clean pass on your own branch needs no file; the verdict line is enough.

```
# Review — <PR #N or branch>: <what the change does, in words>

Reviewing <repo> <base-sha>..<head-sha> · <n> commits · <m> files · +a/−b
Claims from: <issue / spec step / PR body / commits>

**Verdict:** NEEDS FIXES — 1 blocker · 2 warnings · 1 suggestion

## What it does
Two or three sentences in plain words, and whether it does what it says, claim by claim.

## Findings
1. **<the defect, as one sentence>** (blocker) `path:line`
   Scenario: <this input or state> → <this wrong result>.
   Evidence: <the probe or test, and what it printed>, or UNVERIFIED: <what would settle it>.
   Fix: <one line>.

## Checked and fine
- <what was checked> — <why it holds, with path:line>, so nobody re-reviews it.

## Gates
| Gate | Command | Result |

## Not reviewed
- <files skimmed or skipped, and why: generated, vendored, too large to read in full>
```

In chat, use the standing contract: **What's wrong** is the verdict line and the blockers, **The
fix** says what to change, and **How it works** is at most five bullets, with the rest in the file.
For the PR body, one line: `Review: <head-sha> — <n> blockers fixed; known: <warnings left, or none>`.

### One finding, in full

This one comes from a real review of a change that rewrote malformed tool-call arguments as `{}`, so
that the model provider would stop rejecting the conversation history:

```
1. **The tool now runs with `{}`, not with what the model sent.** (warning) `agent/llm_call.rs:388`
   Scenario: the rewritten response is both saved to history (here) and dispatched to the tool
   (`dispatch.rs:98` → `tools.rs:229`). A truncated `{"command":"cat > f <<EOF ...` used to fail
   with `invalid JSON arguments: EOF while parsing`, and now fails with `missing 'command' field`.
   The model is told it forgot a field when its output was cut off, so it re-sends the same long
   command. The PR body says the tool "already fails correctly", but the error it fails with has
   changed.
   Fix: keep the original string for dispatch and for the stored record, and rewrite it only where
   history is serialized for the provider. That is one place instead of five.
```

It answers question 1, because it checks a sentence in the PR body against the code. It answers
question 2, because it follows the changed value to a second reader the author did not look at. And
it hands the author a scenario they can run and a fix that removes code.

## After the review

| Situation | Do |
|---|---|
| your own branch, with blockers | fix them (logging drift in the spec when one is active), then **review the fix range again**. In one round of six reviews, fixes to findings introduced new defects twice |
| someone else's PR | put any fix on a new branch cut from the PR head, and offer it; never push to the author's branch |
| warnings left unfixed | list them in the PR body as known, and file them as issues while the context is fresh |
| GitHub | post only when asked: one comment with the verdict and the findings. Never approve or request changes on the user's behalf |

## When something is missing

| Missing | Do |
|---|---|
| `gh` | use the GitHub MCP tools: `pull_request_read` with `get` for base and head, `get_diff` for the patch, and `get_check_runs` for CI |
| a local clone | review the API's patch. Nothing can be run, so each finding that needs a run is `UNVERIFIED:`, and the verdict says so |
| a working build | review by reading, and write that the gates were not run and why |

## Rules this skill exists to enforce

1. The first line of every review names its base and head SHA. A review of an unnamed diff is not a review.
2. The claims are written down before the diff is read.
3. Every finding carries `path:line`, a scenario, and evidence that was run, or it says `UNVERIFIED:`.
4. A test counts only once it has been seen failing without the change.
5. What was checked and found fine is written down, so the next reviewer does not redo it.
6. Fixes to review findings are reviewed again.
7. The review reports and the human approves. Nothing is pushed to someone else's branch.
