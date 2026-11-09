// SessionStart: warn when a tool this repo's Claude setup needs isn't installed on this machine
// (e.g. the language server for the LSP plugin on a fresh Windows PC). Silent when everything is there.
// Usage: node check-tools.mjs <executable> [<executable> ...]
import { spawnSync } from 'node:child_process';

const finder = process.platform === 'win32' ? 'where' : 'which';
const missing = process.argv.slice(2).filter((bin) => spawnSync(finder, [bin], { stdio: 'ignore' }).status !== 0);
if (missing.length === 0) process.exit(0);

const install = 'npm install -g typescript-language-server typescript pyright';
const text =
  `Missing on this machine: ${missing.join(', ')}. The language server plugin can't start without it. ` +
  `Install with: ${install} (then start a new session).`;
process.stdout.write(
  JSON.stringify({
    systemMessage: text,
    hookSpecificOutput: { hookEventName: 'SessionStart', additionalContext: `${text} Tell the user once.` },
  }),
);
