from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import subprocess
import unittest
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "hooks" / "check.py"


def result(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def execute(
    payload: Mapping[str, object], responses: Sequence[subprocess.CompletedProcess[str] | Exception]
) -> tuple[int, str, int]:
    output = io.StringIO()
    with (
        patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(ROOT)}),
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("subprocess.run", side_effect=responses) as called,
        patch.object(Path, "exists", return_value=True),
        contextlib.redirect_stderr(output),
    ):
        try:
            runpy.run_path(str(SCRIPT), run_name="__main__")
            code = 0
        except SystemExit as exc:
            if not isinstance(exc.code, int):
                raise
            code = exc.code
    return code, output.getvalue(), called.call_count


class CheckHookTests(unittest.TestCase):
    def test_success_and_empty_changes(self) -> None:
        self.assertEqual(execute({}, [result(), result()]), (0, "", 2))
        responses = [result(stdout="sample.py\n"), result(), result(), result(), result()]
        self.assertEqual(execute({}, responses), (0, "", 5))

    def test_continuation_does_not_run_tools(self) -> None:
        self.assertEqual(execute({"stop_hook_active": True}, []), (0, "", 0))

    def test_missing_git_and_git_nonzero(self) -> None:
        code, message, _ = execute({}, [FileNotFoundError("git missing")])
        self.assertEqual(code, 2)
        self.assertIn("git missing", message)
        code, message, _ = execute({}, [result(128, stderr="no HEAD")])
        self.assertEqual(code, 2)
        self.assertIn("no HEAD", message)
        self.assertIn("exit 128", message)

    def test_non_one_tool_errors_are_reported(self) -> None:
        responses = [
            result(stdout="sample.py\n"),
            result(),
            result(2, stderr="ruff failed"),
            result(3, stderr="format failed"),
            result(4, stderr="ty failed"),
        ]
        code, message, count = execute({}, responses)
        self.assertEqual((code, count), (2, 5))
        for expected in ("ruff failed", "format failed", "ty failed", "exit 2", "exit 3", "exit 4"):
            self.assertIn(expected, message)

    def test_post_edit_non_one_and_timeout(self) -> None:
        payload = {"hook_event_name": "PostToolUse", "tool_input": {"file_path": str(ROOT / "sample.py")}}
        code, message, _ = execute(payload, [result(2, stderr="bad config")])
        self.assertEqual(code, 2)
        self.assertIn("bad config", message)
        code, message, _ = execute(payload, [subprocess.TimeoutExpired("uv", 170)])
        self.assertEqual(code, 2)
        self.assertIn("uv", message)
        self.assertIn("timed out", message)
