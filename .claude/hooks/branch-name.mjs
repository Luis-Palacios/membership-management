// PreToolUse (Bash): block creating a branch whose name isn't feature/, fix/ or chore/ + lowercase kebab-case.
// Catches git switch -c/-C, checkout -b/-B, worktree add -b/-B and `git branch <name>` (with or without -C <repo>).
// Same file in every repo (workspace, staff-app, auth-server, membership-management, management-infra).
import { readFileSync } from 'node:fs';

const command = JSON.parse(readFileSync(0, 'utf8')).tool_input?.command ?? '';
const valid = /^(feature|fix|chore)\/[a-z0-9]+(-[a-z0-9]+)*$/;
const git = String.raw`\bgit(?:\s+-C\s+\S+)*\s+`;
const name = String.raw`['"]?([^\s'";&|)]+)`;
const patterns = [
  new RegExp(`${git}(?:switch\\s+(?:\\S+\\s+)*?-[cC]|checkout\\s+(?:\\S+\\s+)*?-[bB]|worktree\\s+add\\s+(?:\\S+\\s+)*?-[bB])\\s+${name}`, 'g'),
  new RegExp(`${git}branch\\s+(?!-)${name}`, 'g'),
];

const bad = [];
for (const re of patterns) {
  for (const m of command.matchAll(re)) if (!valid.test(m[1])) bad.push(m[1]);
}
if (bad.length) {
  process.stderr.write(
    `Branch name ${bad.map((b) => `"${b}"`).join(', ')} doesn't follow the convention: feature/, fix/ or chore/ ` +
      `+ lowercase kebab-case, e.g. feature/<spec-slug> (the docs/specs/<slug>.md name, the same in every repo). ` +
      `See "Branch names" in the workspace CLAUDE.md.`,
  );
  process.exit(2);
}
