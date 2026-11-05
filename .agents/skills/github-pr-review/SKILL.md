---
name: github-pr-review
description: >-
  Use this skill whenever the user asks to review a GitHub Pull Request (PR), post a PR review,
  approve a PR, request changes on a PR, or comment on a PR using the GitHub CLI (`gh`).
---

# GitHub PR Review as Bot (`antigravity-lp-reviewer[bot]`)

When posting Pull Request reviews or PR comments on GitHub, use the dedicated GitHub App bot wrapper instead of bare `gh` so that reviews come from `antigravity-lp-reviewer[bot]` rather than the user's personal GitHub account (allowing the bot to `APPROVE` or `REQUEST_CHANGES` on the user's own PRs).

## Wrapper Script Locations

The wrapper mints a short-lived GitHub App installation token, exports `GH_TOKEN`, and forwards all arguments to `gh "$@"`.

- **macOS / Linux:**
  `~/.config/gh-bot/gh-as-bot.sh` (or `node .agents/skills/github-pr-review/scripts/gh-as-bot.cjs`)
- **Windows (PowerShell):**
  `& "$HOME\.config\gh-bot\gh-as-bot.cmd"` (or `node "$HOME\.config\gh-bot\gh-as-bot.cjs"` / `node .agents/skills/github-pr-review/scripts/gh-as-bot.cjs`)
- **App ID:** `5459882`
- **Private Key:** `~/.config/gh-bot/private-key.pem` (or `~/.config/github-apps/antigravity-lp-reviewer.private-key.pem`)

## Workflow

1. **Inspect PR & Diffs:**
   Use bare `gh` or the bot wrapper for read-only inspection:
   ```bash
   gh pr view <PR_NUMBER> --json number,title,body,baseRefName,headRefName,url,files,additions,deletions
   gh pr diff <PR_NUMBER>
   ```

2. **Post PR Review with Inline File/Line Comments (Preferred):**
   When you have specific findings in files touched by the PR, **always attach inline per-file/line comments** along with a concise summary `body` using the GitHub Pull Request Reviews REST API (`gh api`).

   Write the payload to a JSON file (e.g. `review.json`) to guarantee clean, cross-platform quoting:
   ```json
   {
     "event": "COMMENT",
     "body": "## Review Summary\n...",
     "comments": [
       {
         "path": "path/to/file.ts",
         "start_line": 10,
         "line": 14,
         "side": "RIGHT",
         "body": "Explanation and optional ```suggestion block..."
       },
       {
         "path": "path/to/another-file.ts",
         "line": 42,
         "side": "RIGHT",
         "body": "Single-line inline comment..."
       }
     ]
   }
   ```

   Submit the review:
   - **macOS / Linux:**
     ```bash
     ~/.config/gh-bot/gh-as-bot.sh api repos/{owner}/{repo}/pulls/<PR_NUMBER>/reviews --method POST --input review.json
     ```
   - **Windows:**
     ```powershell
     & "$HOME\.config\gh-bot\gh-as-bot.cmd" api repos/{owner}/{repo}/pulls/<PR_NUMBER>/reviews --method POST --input review.json
     ```

   - `event`: `"COMMENT"`, `"APPROVE"`, or `"REQUEST_CHANGES"`.
   - `path`: repo-relative file path present in the PR diff.
   - `line` (and optional `start_line` for multi-line ranges): line numbers in the file on `side` (`"RIGHT"` for added/context lines in the new version, `"LEFT"` for deleted lines).
   - For findings in untouched files that are directly affected by a change in the diff, attach the inline comment to the relevant line in the modified file where the contract/type/helper changed, or include it in the top-level `body`.

3. **Summary-Only Review (Only when there are no line-specific comments, e.g. clean approval):**
   - **macOS / Linux:**
     ```bash
     ~/.config/gh-bot/gh-as-bot.sh pr review <PR_NUMBER> --approve --body "<review markdown>"
     ```
   - **Windows:**
     ```powershell
     & "$HOME\.config\gh-bot\gh-as-bot.cmd" pr review <PR_NUMBER> --approve --body "<review markdown>"
     ```
