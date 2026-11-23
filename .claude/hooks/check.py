"""PostToolUse (Edit|Write): ruff the edited file. Stop: ruff + format check on every changed .py, then ty.

Exit 2 sends the errors back to Claude. Stop runs too because most edits go through Bash, which
PostToolUse on Edit|Write never sees.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Never

data = json.load(sys.stdin)
root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()


def run(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=170, check=False)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired) as exc:
        fail(f"Could not run {args[0]}: {exc}\n")


def fail(msg: str) -> Never:
    sys.stderr.write(msg)
    sys.exit(2)


def details(result: subprocess.CompletedProcess[str]) -> str:
    return "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())


if data.get("hook_event_name") == "PostToolUse":
    f = Path(data.get("tool_input", {}).get("file_path", ""))
    if f.suffix == ".py" and f.is_relative_to(root):
        r = run("uv", "run", "--quiet", "ruff", "check", "--output-format", "concise", str(f))
        if r.returncode != 0:
            fail(
                f"ruff failed in {f} (exit {r.returncode}; `uv run ruff check --fix` fixes [*]):\n"
                f"{details(r)}"
            )
    sys.exit(0)

if data.get("stop_hook_active"):
    sys.exit(0)
listed = ""
for args in (("git", "diff", "--name-only", "HEAD"), ("git", "ls-files", "--others", "--exclude-standard")):
    result = run(*args)
    if result.returncode != 0:
        fail(
            f"Could not list changed files ({' '.join(args)}, exit {result.returncode}):\n{details(result)}\n"
        )
    listed += result.stdout
files = [f for f in listed.splitlines() if f.endswith(".py") and (root / f).exists()]
if not files:
    sys.exit(0)
errors = []
r = run("uv", "run", "--quiet", "ruff", "check", "--output-format", "concise", *files)
if r.returncode != 0:
    errors.append(f"ruff check (exit {r.returncode}; `uv run ruff check --fix` fixes [*]):\n{details(r)}")
r = run("uv", "run", "--quiet", "ruff", "format", "--check", *files)
if r.returncode != 0:
    errors.append(f"ruff format (exit {r.returncode}): run `uv run ruff format` on:\n{details(r)}")
r = run("uv", "run", "--quiet", "ty", "check", "--output-format", "concise")
if r.returncode != 0:
    errors.append(f"ty check (exit {r.returncode}):\n" + "\n".join(details(r).splitlines()[:40]))
if errors:
    fail("Checks on the changed files failed. Fix them before finishing:\n\n" + "\n\n".join(errors))
