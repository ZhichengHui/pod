# Repair a Pull Request

You are a **repair** session. Your job is to salvage an unhealthy PR — merge
conflicts, failed CI, or stuck CI — and get it back to a mergeable state, or
decide it is unsalvageable and close it cleanly.

**First, read the `pr-repair-flow` skill.** It covers the claim/diagnose/fix/
verify/push lifecycle in detail, including when to abandon. This command
only covers what is specific to starting a repair session.

## Pick a PR

```
coordination list-pr-repair
```

Output is one PR per line in priority order (`conflict` > `failed` > `stuck`).
Claim the top one:

```
coordination claim-pr-repair <pr-number>
```

If the claim output says the PR is already `repair-claimed` or you lost
the race, skip it and try the next one. If every candidate is claimed,
exit — a fresh dispatch will handle the work later.

## Three Outcomes, No Invented Escalation

Repair has exactly three terminal states:

1. **Salvaged** — you got the PR green and pushed:
   ```
   coordination mark-pr-salvaged <pr-number>
   ```
2. **Unsalvageable** — after bounded attempts, verification still fails, or
   the branch is too stale to surgery:
   ```
   coordination close-pr-unsalvageable <pr-number> "<reason>"
   ```
   This closes the PR, removes `has-pr` from the linked issue, and adds
   `replan` so the planner will produce a fresh approach.
3. **Needs owner** — nothing you are allowed to change can fix the PR (for
   example the only failing check needs a file agents may not edit):
   ```
   coordination pr-needs-owner <pr-number> "<what the owner must do, and why>"
   ```
   This adds `needs-owner`, so repair sessions skip the PR until the owner
   acts. Never end by only releasing the claim: the next dispatch would
   pick the same PR again.

**Do not escalate by inventing a `directive`.** The `directive` label
flows top-down from the project owner; agents do not author directives.
The fix-or-abandon rule is non-negotiable: complex conflicts become
re-implementations via `replan`, not human tickets.

See the `pr-repair-flow` skill for retry budget, verification rules, and
examples.
