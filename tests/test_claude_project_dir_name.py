import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pod import cli


class ClaudeProjectDirNameTests(unittest.TestCase):
    def test_every_non_alphanumeric_becomes_dash(self):
        self.assertEqual(
            cli._claude_project_dir_name("/disk/scratch/pod/QF_UF_Smt/worktrees/d159fd9e"),
            "-disk-scratch-pod-QF-UF-Smt-worktrees-d159fd9e",
        )
        self.assertEqual(
            cli._claude_project_dir_name("/home/u/.claude/jobs/x"),
            "-home-u--claude-jobs-x",
        )

    def test_jsonl_path_for_underscore_worktree(self):
        cfg = Path("/cfg")
        path = cli.get_jsonl_path("/r/QF_BV_Smt/worktrees/abc", "sid", cfg)
        self.assertEqual(path, "/cfg/projects/-r-QF-BV-Smt-worktrees-abc/sid.jsonl")

    def test_historical_cost_finds_underscore_and_dot_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            project_dir = tmp / "pod" / "QF_UF.Smt"
            config_dir = tmp / "cfg"
            for sub in ("", "-worktrees-abc"):
                d = config_dir / "projects" / (cli._claude_project_dir_name(project_dir) + sub)
                d.mkdir(parents=True)
                (d / "s.jsonl").write_text(json.dumps({
                    "type": "assistant",
                    "message": {"usage": {"input_tokens": 1_000_000, "output_tokens": 0}},
                }) + "\n")
            cfg = {"pricing": {"claude": {"default": {
                "input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_create": 6.25}}}}
            with mock.patch.object(cli, "PROJECT_DIR", project_dir), \
                    mock.patch.object(cli.Path, "home", return_value=tmp / "nohome"):
                total = cli._claude_historical_cost(cfg, config_dir)
            # two transcripts of 1M input tokens each at $5/M
            self.assertAlmostEqual(total, 10.0, places=4)


if __name__ == "__main__":
    unittest.main()
