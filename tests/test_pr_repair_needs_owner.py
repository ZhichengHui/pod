"""A PR that waits for the owner (`needs-owner`) is not a repair candidate.

Regression: a PR whose only failing check needed an owner-only change
(`tools/spec.sha256`, which agents may not edit) carried `needs-owner`,
but `list-pr-repair` only excluded `repair-claimed`. Pod dispatched a
repair session on it, the session found nothing it could fix and released
the claim, and the next dispatch claimed the same PR again: 62 claims in
four hours. `list-pr-repair` and `claim-pr-repair` now skip `needs-owner`
PRs, and `coordination pr-needs-owner` lets a repair session hand a PR to
the owner instead of only releasing the claim.
"""
from __future__ import annotations

import contextlib
import io
import json
import unittest

from pod import cli, coordination

from _gh_helpers import patch_client
from test_coordination import _gh_result, _make_ctx

_FAILED = [{"conclusion": "FAILURE"}]


def _pr(num, *labels, mergeable="MERGEABLE", checks=_FAILED):
    return {"number": num, "title": f"PR {num}", "mergeable": mergeable,
            "statusCheckRollup": checks,
            "labels": [{"name": l} for l in labels]}


def _run(fn, argv, handler=None):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), \
            patch_client(gh_cli_handler=handler) as client:
        rc = fn(_make_ctx(session_id="sess-A"), argv)
    return rc, buf.getvalue(), client


class ListPrRepairTests(unittest.TestCase):
    def test_skips_needs_owner_and_repair_claimed(self):
        prs = [_pr(1), _pr(2, "needs-owner"), _pr(3, "repair-claimed"),
               _pr(4, mergeable="CONFLICTING"),
               _pr(5, "needs-owner", mergeable="CONFLICTING")]

        def handler(*argv):
            if argv[:2] == ("pr", "list"):
                return _gh_result(stdout=json.dumps(prs))
            return _gh_result()

        rc, out, _ = _run(coordination.cmd_list_pr_repair, [], handler)
        self.assertEqual(rc, 0)
        listed = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
        self.assertEqual(listed, ["#4", "#1"])


class ClaimPrRepairTests(unittest.TestCase):
    def test_refuses_needs_owner(self):
        def handler(*argv):
            if argv[:2] == ("pr", "view"):
                return _gh_result(stdout="needs-owner")
            return _gh_result()

        rc, out, client = _run(coordination.cmd_claim_pr_repair, ["72"],
                               handler)
        self.assertEqual(rc, 1)
        self.assertIn("needs-owner", out)
        argvs = [c["argv"] for c in client.calls if c["method"] == "GH"]
        self.assertFalse(any("--add-label" in a for a in argvs))


class PrNeedsOwnerTests(unittest.TestCase):
    def test_posts_question_labels_and_releases(self):
        rc, out, client = _run(coordination.cmd_pr_needs_owner,
                               ["72", "Run check-spec.sh --update"])
        self.assertEqual(rc, 0)
        argvs = [c["argv"] for c in client.calls if c["method"] == "GH"]
        comment = next(a for a in argvs if a[:2] == ("issue", "comment"))
        body = comment[comment.index("--body") + 1]
        self.assertIn("Run check-spec.sh --update", body)
        self.assertIn("sess-A", body)
        self.assertIn(("pr", "edit", "72", "--repo", "owner/repo",
                       "--add-label", "needs-owner"), argvs)
        self.assertIn(("pr", "edit", "72", "--repo", "owner/repo",
                       "--remove-label", "repair-claimed"), argvs)

    def test_registered(self):
        self.assertIs(coordination._COMMANDS["pr-needs-owner"],
                      coordination.cmd_pr_needs_owner)


class ParserReleaseTests(unittest.TestCase):
    """`pr-needs-owner` releases the repair claim, so the session parsers
    clear `repair_pr` the same way as for mark-pr-salvaged."""

    def _state(self):
        s = cli.AgentState()
        s.worker_type = "repair"
        s.repair_pr = 72
        return s

    def test_codex(self):
        s = self._state()
        cli._parse_codex_jsonl_line(json.dumps({
            "type": "item.completed",
            "item": {"type": "command_execution",
                     "command": 'coordination pr-needs-owner 72 "q"',
                     "aggregated_output": ""}}).encode(), s)
        self.assertEqual(s.repair_pr, 0)

    def test_claude(self):
        s = self._state()
        cli._parse_claude_jsonl_line(json.dumps({
            "type": "assistant",
            "message": {"usage": {}, "content": [
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": 'coordination pr-needs-owner 72 "q"'}}]},
        }).encode(), s)
        self.assertEqual(s.repair_pr, 0)


if __name__ == "__main__":
    unittest.main()
