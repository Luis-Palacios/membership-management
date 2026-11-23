"""Stop: ruff + format check on every changed .py, then ty."""

import json
import subprocess
import sys
from pathlib import Path

raw = sys.stdin.read().strip()
data = json.loads(raw) if raw else {}

if data.get("continuationActive") or data.get("terminationReason") in ("USER_CANCELED", "ERROR"):
    print("{}")
    sys.exit(0)

root = Path(__file__).resolve().parents[2]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=170, check=False)  # noqa: S603


listed = (
    run("git", "diff", "--name-only", "HEAD").stdout
    + run("git", "ls-files", "--others", "--exclude-standard").stdout
)
files = [f for f in listed.splitlines() if f.endswith(".py") and (root / f).exists()]
if not files:
    print("{}")
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
    reason = "Checks on the changed files failed. Fix them before finishing:\n\n" + "\n\n".join(errors)
    print(json.dumps({"decision": "continue", "reason": reason}))
else:
    print("{}")
