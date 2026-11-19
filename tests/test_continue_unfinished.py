"""A session that ends holding its claim without a PR is continued by the same
agent (no free agent slot needed), at most `monitor.max_unfinished_resumes`
times; `coordination needs-owner` hands an issue to the owner instead of
asking in the conversation, and keeps every worker off it until answered."""

from __future__ import annotations

import io
import contextlib
import tempfile
import unittest
from unittest import mock

from pod import cli, coordination

from _gh_helpers import fake_response, patch_client
from test_coordination import _gh_result, _make_ctx


def _state(**kw) -> cli.AgentState:
    s = cli.AgentState(short_id="abcd1234", uuid="sess-1",
                       worker_type="work", claimed_issue=60, pr_number=0)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class ShouldContinueTests(unittest.TestCase):
    def setUp(self):
        self.wt = tempfile.mkdtemp()
        self.cfg: dict = {}

    def ok(self, state=None, labels=frozenset({"agent-plan", "claimed"}),
           backend="claude", wt=None):
        return cli._should_continue_unfinished(
            state or _state(), self.cfg,
            set(labels) if labels is not None else None,
            backend, self.wt if wt is None else wt)

    def test_unfinished_claim_is_continued(self):
        self.assertTrue(self.ok())

    def test_only_once_by_default(self):
        self.assertFalse(self.ok(_state(unfinished_resumes=1)))

    def test_limit_is_configurable(self):
        self.cfg = {"monitor": {"max_unfinished_resumes": 2}}
        self.assertTrue(self.ok(_state(unfinished_resumes=1)))
        self.assertFalse(self.ok(_state(unfinished_resumes=2)))

    def test_not_when_released_or_handed_to_owner(self):
        self.assertFalse(self.ok(labels={"agent-plan"}))
        self.assertFalse(self.ok(labels={"agent-plan", "claimed", "needs-owner"}))

    def test_not_when_github_unreachable(self):
        self.assertFalse(self.ok(labels=None))

    def test_not_with_pr_or_without_claim(self):
        self.assertFalse(self.ok(_state(pr_number=7)))
        self.assertFalse(self.ok(_state(claimed_issue=0)))

    def test_not_for_repair_replan_or_finishing(self):
        self.assertFalse(self.ok(_state(worker_type="repair")))
        self.assertFalse(self.ok(_state(worker_type="replan")))
        self.assertFalse(self.ok(_state(finishing=True)))

    def test_not_without_resumable_backend_or_worktree(self):
        self.assertFalse(self.ok(backend="codex"))
        self.assertFalse(self.ok(wt=self.wt + "/gone"))


class IssueLabelTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(cli, "_get_repo", return_value="acme/widgets")
        p.start()
        self.addCleanup(p.stop)

    def test_reads_labels(self):
        body = {"labels": [{"name": "agent-plan"}, {"name": "claimed"}]}
        with patch_client(routes={
                ("GET", "/repos/acme/widgets/issues/60"):
                    fake_response(200, body=body)}):
            self.assertEqual(cli._issue_label_names(60),
                             {"agent-plan", "claimed"})

    def test_none_on_error(self):
        with patch_client():  # every route 404s
            self.assertIsNone(cli._issue_label_names(60))


class ResumePromptTests(unittest.TestCase):
    def test_prompt_names_issue_and_owner_command(self):
        p = cli.UNFINISHED_RESUME_PROMPT.format(issue=60)
        self.assertIn("#60", p)
        self.assertIn('coordination needs-owner 60 "', p)
        self.assertIn("Nobody reads this conversation", p)

    def test_state_round_trips_new_fields(self):
        s = _state(resume_reason="unfinished", unfinished_resumes=1)
        t = cli.AgentState.from_dict(s.to_dict())
        self.assertEqual((t.resume_reason, t.unfinished_resumes),
                         ("unfinished", 1))


class NeedsOwnerTests(unittest.TestCase):
    def test_posts_question_labels_and_releases(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), patch_client() as client:
            rc = coordination.cmd_needs_owner(
                _make_ctx(session_id="sess-A"), ["60", "Kill PID 123?"])
        self.assertEqual(rc, 0)
        argvs = [c["argv"] for c in client.calls if c["method"] == "GH"]
        comment = next(a for a in argvs if a[:2] == ("issue", "comment"))
        body = comment[comment.index("--body") + 1]
        self.assertIn("Kill PID 123?", body)
        self.assertIn("sess-A", body)
        self.assertIn(("issue", "edit", "60", "--repo", "owner/repo",
                       "--add-label", "needs-owner"), argvs)
        self.assertIn(("issue", "edit", "60", "--repo", "owner/repo",
                       "--remove-label", "claimed"), argvs)

    def test_needs_owner_issues_are_not_claimable_or_replanned(self):
        items = [{"number": 1, "labels": [{"name": "agent-plan"},
                                          {"name": "needs-owner"}]},
                 {"number": 2, "labels": [{"name": "agent-plan"}]}]
        self.assertEqual([i["number"] for i in coordination._unclaimed_filter(items)], [2])
        self.assertEqual(
            [i["number"] for i in coordination._filtered_issues(
                items, coordination._REPLAN_EXCLUDE)], [2])

    def test_claim_refuses_needs_owner(self):
        def handler(*argv):
            if argv[:2] == ("issue", "view"):
                return _gh_result(stdout="agent-plan,needs-owner")
            return _gh_result()
        buf = io.StringIO()
        with mock.patch.object(coordination, "_check_provenance",
                               return_value=(True, "")), \
                contextlib.redirect_stdout(buf), \
                patch_client(gh_cli_handler=handler):
            rc = coordination.cmd_claim(_make_ctx(), ["42"])
        self.assertEqual(rc, 1)
        self.assertIn("owner decision", buf.getvalue())

    def test_label_is_created_by_pod(self):
        self.assertIn("needs-owner", coordination.REQUIRED_LABELS)
        self.assertIn("needs-owner", cli.REQUIRED_LABELS)


if __name__ == "__main__":
    unittest.main()
