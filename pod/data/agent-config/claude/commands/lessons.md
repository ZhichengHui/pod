# Execute a Lessons Work Item

You are a **lessons** session. Your job is to keep `LESSONS.md` useful: short guidance, distilled
from what went wrong in this repository, that keeps the same struggle or failed approach from
happening again. Workers read `LESSONS.md` before they start (see the `agent-worker-flow` skill).

**First, read the `agent-worker-flow` skill** for the standard claim/branch/verify/publish
workflow. This document only covers what is specific to lessons sessions.

## Claiming Your Issue

Use `coordination list-unclaimed --label lessons` to find work for this session type.

## The Lessons Task

### Step 1: Read the current lessons

Read `LESSONS.md` (create it if it does not exist, with a one-paragraph statement of its purpose)
and `PROGRESS.md` if it exists.

### Step 2: Survey what went wrong

Since the last `lessons` issue was closed:
- Read the entries in `progress/` (at least the last 20, sorted by filename, most recent last).
- Read the comments on issues that were skipped or labelled `replan`.
- Read the pull requests closed without merging, with their closing comments.

Look for:
- The same difficulty in several sessions
- Approaches that were tried and abandoned, and why
- Mistakes that needed a repair or a revert

### Step 3: Update `LESSONS.md`

- Add a lesson only for something likely to recur.
- Merge duplicates; remove lessons that no longer apply.
- Each lesson states what goes wrong, what to do instead, and the evidence (links to progress
  entries, issues or pull requests).

## Constraints

- Change only `LESSONS.md` (and write your progress entry). Do not modify code or other documents.
- Keep it short: guidance for real, recurring problems, not a log of everything.

## Reflect

Run `/reflect` before finishing.
