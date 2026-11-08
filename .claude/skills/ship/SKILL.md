---
name: ship
description: Run this repo's checks, update the handoff progress log, commit, and optionally push or open the PR. Use when the user says "commit", "commit and push", "create a PR" or "open the PR".
argument-hint: "[push | pr | main]"
disable-model-invocation: true
---

`$ARGUMENTS`: empty = commit; `push` = commit and push the branch; `pr` = also open the PR;
`main` = commit and push straight to `main` (only when the user says so: small fixes, handoff and spec edits).

1. Look: branch, `git status --short`, `git diff --stat`. On `main` without `main` in the arguments,
   propose a branch and ask: `feature/<spec-slug>` (the same name as in the other repos), `fix/<what>` or
   `chore/<what>`, lowercase kebab-case ("Branch names" in the workspace CLAUDE.md). Changes that
   aren't part of this work: ask which belong.
2. Checks (all must pass; don't ship with errors):
   - `uv run ruff check --fix .`, `uv run ruff format .`, `uv run ty check`.
   - Changed models: `uv run alembic check` passes, the new migration was reviewed (autogenerate drops
     tables whose model isn't imported via `data/models.py`), and `downgrade -1` + `upgrade head` round-trips.
   - Changed a table the seed covers: the seed still runs (`uv run python -m membership_management.data.seed --reset`
     on the local DB).
   - Changed an endpoint the staff app calls: say so; staff-app's API types need regenerating.
3. Handoff: if this work follows a handoff, tick the stage in its progress log in the same commit (the hash
   goes in a follow-up line once known, or in the next stage's commit), and add anything later stages need
   to "Decisions and deviations".
4. Commit, one per stage: the subject is a plain sentence saying what changed, with the stage in brackets
   when there is one, e.g. "Show the Resolved tab's filtered count (resolved period stage 2)". No
   `feat:` prefixes. A body only when the why isn't obvious.
5. Push: `git push -u origin <branch>`.
6. PR: `gh pr create --base main --title "<sentence>" --body-file <scratchpad file>`; the body is a
   `## Summary` per area, then how it was verified (checks, browser, curl). No auto-merge. Report the URL.
7. Report the hashes and the PR URL, and anything another repo must change (permission names, API types,
   token re-sync).
