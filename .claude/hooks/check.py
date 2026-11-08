"""PostToolUse (Edit|Write): ruff the edited file. Stop: ruff + format check on every changed .py, then ty.

Exit 2 sends the errors back to Claude. Stop runs too because most edits go through Bash, which
PostToolUse on Edit|Write never sees.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

data = json.load(sys.stdin)
root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=170)


def fail(msg: str) -> None:
    sys.stderr.write(msg)
    sys.exit(2)


if data.get("hook_event_name") == "PostToolUse":
    f = Path(data.get("tool_input", {}).get("file_path", ""))
    if f.suffix == ".py" and f.is_relative_to(root):
        r = run("uv", "run", "--quiet", "ruff", "check", "--output-format", "concise", str(f))
        if r.returncode == 1:
            fail(f"ruff errors in {f} (`uv run ruff check --fix` fixes the [*] ones):\n{r.stdout}")
    sys.exit(0)

if data.get("stop_hook_active"):
    sys.exit(0)
listed = run("git", "diff", "--name-only", "HEAD").stdout + run("git", "ls-files", "--others", "--exclude-standard").stdout
files = [f for f in listed.splitlines() if f.endswith(".py") and (root / f).exists()]
if not files:
    sys.exit(0)
errors = []
r = run("uv", "run", "--quiet", "ruff", "check", "--output-format", "concise", *files)
if r.returncode == 1:
    errors.append(f"ruff check (`uv run ruff check --fix` fixes the [*] ones):\n{r.stdout}")
r = run("uv", "run", "--quiet", "ruff", "format", "--check", *files)
if r.returncode == 1:
    errors.append(f"ruff format: run `uv run ruff format` on:\n{r.stdout}")
r = run("uv", "run", "--quiet", "ty", "check", "--output-format", "concise")
if r.returncode == 1:
    errors.append("ty check:\n" + "\n".join(r.stdout.splitlines()[:40]))
if errors:
    fail("Checks on the changed files failed. Fix them before finishing:\n\n" + "\n\n".join(errors))
