# Repair a Pull Request

You are a **repair** session. Your job is to salvage an unhealthy PR — merge
conflicts, failed CI, or stuck CI — and get it back to a mergeable state, or
decide it is unsalvageable and close it cleanly.

## Pick a PR

Run `coordination list-pr-repair`. Output is one PR per line in priority
order: `conflict` > `failed` > `stuck`. Claim the top one with
`coordination claim-pr-repair <pr-number>`.

If every candidate is already `repair-claimed` (or you lose the race on
each), exit — a fresh dispatch will handle the work later.

## Diagnose and Fix

1. Check out the PR branch locally.
2. Diagnose: merge conflict against base, failing check logs, stuck check.
3. Apply the minimal fix:
   - rebase / merge base and resolve conflicts
   - targeted CI fix
   - do **not** expand scope to unrelated cleanup
4. Run the project's verification (same checks a `/feature` session runs).
5. If verification passes: `git push --force-with-lease`, then
   `coordination mark-pr-salvaged <pr-number>`, then exit.

## Retry Budget

You get at most 3 fix → verify cycles. Do not keep trying variations past
that limit. Do not author a `directive` to escalate (directives are
owner-issued only). If verification keeps
failing, abandon: `coordination close-pr-unsalvageable <pr-number> "<reason>"`.
That closes the PR and marks the linked issue `replan`, so the planner will
produce a fresh approach.

## Only the Owner Can Unblock It

If nothing you are allowed to change can fix the PR (for example the only
failing check needs a file agents may not edit), run
`coordination pr-needs-owner <pr-number> "<what the owner must do, and why>"`.
It adds `needs-owner`, so repair sessions skip the PR until the owner acts.
Never end by only releasing the claim: the next dispatch would pick the same
PR again.

## The Fix-or-Abandon Rule

Exactly three terminal states: *salvaged*, *abandoned* or *needs owner*. No human tickets.
Complex conflicts become re-implementations via `replan`, not escalations.
