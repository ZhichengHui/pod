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


class RunArchiveTests(unittest.TestCase):
    def setUp(self):
        self.proj = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.proj, ".pod"))
        self.p = [mock.patch.object(cli, "PROJECT_DIR", cli.Path(self.proj))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        cli._archive_procs.clear()

    def test_runs_cmd_with_project_dir_and_reaps(self):
        out = os.path.join(self.proj, "arg")
        script = os.path.join(self.proj, "arch")
        with open(script, "w") as f:
            f.write(f'#!/bin/sh\necho "$1" > {out}\n')
        os.chmod(script, 0o755)
        with mock.patch.object(cli, "_reload_config_value", return_value=script):
            cli._run_archive()
            cli._archive_procs[0].wait(timeout=10)
            self.assertEqual(open(out).read().strip(), self.proj)
            cli._run_archive()          # reaps the finished run
            self.assertEqual(len(cli._archive_procs), 1)

    def test_unset_or_missing_cmd_is_harmless(self):
        with mock.patch.object(cli, "_reload_config_value", return_value=""):
            cli._run_archive()
        with mock.patch.object(cli, "_reload_config_value",
                               return_value="/nonexistent/archive"), \
             mock.patch.object(cli, "log"):
            cli._run_archive()
        self.assertEqual(cli._archive_procs, [])


class AdoptTests(unittest.TestCase):
    def setUp(self):
        self.agents = tempfile.mkdtemp()
        self.wt = tempfile.mkdtemp()
        self.p = mock.patch.object(cli, "AGENTS_DIR", cli.Path(self.agents))
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def _write(self, **kw):
        fields = dict(uuid="sess-9", worktree=self.wt, branch="agent/sess-9",
                      pid=999999, status="waiting_quota", backend="claude")
        fields.update(kw)
        s = _state(**fields)
        s.write()
        return s

    def test_paused_agent_keeps_everything(self):
        self._write(resuming_after_pause=True, resume_reason="unfinished",
                    unfinished_resumes=1)
        s = cli._load_adopted_state("abcd1234", os.getpid())
        self.assertEqual((s.uuid, s.worktree, s.branch, s.claimed_issue),
                         ("sess-9", self.wt, "agent/sess-9", 60))
        self.assertEqual((s.resuming_after_pause, s.resume_reason, s.unfinished_resumes),
                         (True, "unfinished", 1))
        self.assertEqual(s.pid, os.getpid())
        self.assertFalse(s.finishing)

    def test_running_session_is_resumed_not_replaced(self):
        self._write(resuming_after_pause=False, status="running")
        s = cli._load_adopted_state("abcd1234", os.getpid())
        self.assertTrue(s.resuming_after_pause)
        self.assertEqual(s.resume_reason, "restart")

    def test_nothing_to_resume_without_worktree_or_claim(self):
        self._write(resuming_after_pause=False, claimed_issue=0)
        self.assertFalse(cli._load_adopted_state("abcd1234", os.getpid())
                         .resuming_after_pause)

    def test_missing_state_file(self):
        with mock.patch.object(cli, "log"):
            self.assertIsNone(cli._load_adopted_state("nope", os.getpid()))

    def test_adopt_refuses_a_live_agent(self):
        s = self._write(resuming_after_pause=True)
        s.pid = os.getpid()
        s.pid_start_time = cli._get_pid_start_time(os.getpid())
        s.write()
        args = mock.Mock(agent_id="abcd1234")
        with mock.patch.object(cli, "spawn_agent") as spawn, \
             self.assertRaises(SystemExit):
            cli.cmd_adopt({}, args)
        spawn.assert_not_called()

    def test_adopt_spawns_for_a_dead_agent(self):
        self._write(resuming_after_pause=True)
        args = mock.Mock(agent_id="abcd1234")
        with mock.patch.object(cli, "spawn_agent", return_value=1) as spawn, \
             mock.patch.object(cli, "_pid_is_valid", return_value=False):
            cli.cmd_adopt({}, args)
        spawn.assert_called_once_with({}, agent_id="abcd1234", adopt=True)


if __name__ == "__main__":
    unittest.main()
