"""A running Claude session is paused when the quota check reports no quota
(e.g. usage past the helper's threshold), and later resumed with `--resume`
in the same worktree; every resumable session pauses, not only `pod once`
ones; the current "You've hit your 5-hour limit" wording counts as a quota
hit; and `quota.max_pause_secs = 0` removes the pause cap."""

from __future__ import annotations

import math
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from pod import cli


def _state(**kw) -> cli.AgentState:
    s = cli.AgentState(short_id="abcd1234", uuid="sess-1",
                       worker_type="work", claimed_issue=60, pr_number=0)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class QuotaTextTests(unittest.TestCase):
    def test_current_claude_code_wording(self):
        for text in ("You've hit your 5-hour limit · resets 3:30am (Europe/London)",
                     "You've hit your weekly limit · resets Mon",
                     "You've hit your Opus limit",
                     "hit your limit"):
            self.assertTrue(cli._is_quota_text(text), text)

    def test_ordinary_output_is_not_quota(self):
        for text in ("", "the limit of the sequence", "Error: build failed",
                     "hit your target"):
            self.assertFalse(cli._is_quota_text(text), text)


class PauseCapTests(unittest.TestCase):
    def test_default_and_configured(self):
        self.assertEqual(cli._quota_pause_cap({}), 5400.0)
        self.assertEqual(cli._quota_pause_cap({"quota": {"max_pause_secs": 60}}), 60.0)

    def test_zero_or_negative_means_no_cap(self):
        for v in (0, -1):
            self.assertTrue(math.isinf(
                cli._quota_pause_cap({"quota": {"max_pause_secs": v}})))


class PauseResumableTests(unittest.TestCase):
    def setUp(self):
        self.wt = tempfile.mkdtemp()

    def ok(self, state=None, backend="claude", wt=None):
        return cli._pause_resumable(state or _state(), {}, backend,
                                    self.wt if wt is None else wt)

    def test_ordinary_work_session_is_resumable(self):
        # Not a `pod once` agent: target_issue is 0.
        self.assertTrue(self.ok(_state(target_issue=0)))

    def test_not_without_live_unfinished_work(self):
        self.assertFalse(self.ok(_state(claimed_issue=0)))
        self.assertFalse(self.ok(_state(pr_number=5)))
        self.assertFalse(self.ok(_state(worker_type="repair")))
        self.assertFalse(self.ok(_state(worker_type="replan")))

    def test_only_claude_with_its_worktree(self):
        self.assertFalse(self.ok(backend="codex"))
        self.assertFalse(self.ok(wt="/nonexistent/worktree"))


class OverQuotaNowTests(unittest.TestCase):
    def _helper(self, code: int) -> str:
        d = tempfile.mkdtemp()
        p = os.path.join(d, "quota")
        with open(p, "w") as f:
            f.write(f"#!/bin/sh\nexit {code}\n")
        os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
        return p

    def check(self, cmd: str) -> bool:
        cfg = {"agent": {"claude": {"quota_check": cmd}}}
        with mock.patch.object(cli, "resolve_claude_credential",
                               return_value={"accountLabel": "?"}):
            return cli._over_quota_now(cfg, "claude")

    def test_only_a_definite_no_quota_counts(self):
        self.assertTrue(self.check(self._helper(1)))
        self.assertFalse(self.check(self._helper(0)))
        self.assertFalse(self.check(self._helper(2)))   # unknown

    def test_missing_or_unset_helper_does_not_interrupt(self):
        self.assertFalse(self.check("/nonexistent/quota-helper"))
        self.assertFalse(cli._over_quota_now({}, "claude"))


class InterruptSessionTests(unittest.TestCase):
    def test_sigint_stops_the_process_group(self):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                start_new_session=True)
        t = time.monotonic()
        cli._interrupt_session(proc, grace=10)
        self.assertIsNotNone(proc.poll())
        self.assertLess(time.monotonic() - t, 10)

    def test_escalates_when_sigint_is_ignored(self):
        code = ("import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
                "print('ready', flush=True); time.sleep(60)")
        proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                                start_new_session=True)
        proc.stdout.readline()
        cli._interrupt_session(proc, grace=1)
        self.assertIsNotNone(proc.poll())

    def test_already_exited(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        proc.wait()
        cli._interrupt_session(proc, grace=1)   # must not raise


if __name__ == "__main__":
    unittest.main()
