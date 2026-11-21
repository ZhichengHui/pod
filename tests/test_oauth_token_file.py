"""`[agent.claude] oauth_token_file`: pod exports the token in that file as
CLAUDE_CODE_OAUTH_TOKEN, re-reading the setting from config.toml on disk."""

from __future__ import annotations

import os

import pytest

from pod import cli

VAR = "CLAUDE_CODE_OAUTH_TOKEN"


@pytest.fixture
def project(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    monkeypatch.setattr(cli, "CONFIG_PATH", cfg)
    monkeypatch.setattr(cli, "PROJECT_DIR", tmp_path)
    monkeypatch.setenv(VAR, "old-token")
    logs: list[str] = []
    monkeypatch.setattr(cli, "log", logs.append)
    return tmp_path, cfg, logs


def _write_config(cfg, line: str = "") -> None:
    cfg.write_text('[agent]\nbackend = "claude"\n\n[agent.claude]\nmodel = "opus"\n' + line)


def test_absent_setting_leaves_environment(project):
    _, cfg, logs = project
    _write_config(cfg)
    assert cli._apply_claude_token_file() == ""
    assert os.environ[VAR] == "old-token"
    assert logs == []


def test_absolute_path_sets_stripped_token(project):
    root, cfg, _ = project
    tok = root / "tok"
    tok.write_text("  new-token\n")
    _write_config(cfg, f'oauth_token_file = "{tok}"\n')
    assert cli._apply_claude_token_file() == str(tok)
    assert os.environ[VAR] == "new-token"


def test_relative_path_is_resolved_against_project_dir(project):
    root, cfg, _ = project
    (root / "secrets").mkdir()
    (root / "secrets" / "tok").write_text("rel-token")
    _write_config(cfg, 'oauth_token_file = "secrets/tok"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "rel-token"


def test_home_is_expanded(project, monkeypatch):
    root, cfg, _ = project
    monkeypatch.setenv("HOME", str(root))
    (root / "tok").write_text("home-token")
    _write_config(cfg, 'oauth_token_file = "~/tok"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "home-token"


def test_missing_or_empty_file_keeps_token_and_logs_without_secret(project):
    root, cfg, logs = project
    _write_config(cfg, f'oauth_token_file = "{root / "missing"}"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "old-token"
    (root / "empty").write_text("\n")
    _write_config(cfg, f'oauth_token_file = "{root / "empty"}"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "old-token"
    assert len(logs) == 2 and all("keeping the current token" in m for m in logs)


def test_new_token_and_config_take_effect_without_restart(project):
    root, cfg, _ = project
    tok = root / "tok"
    tok.write_text("first")
    _write_config(cfg, f'oauth_token_file = "{tok}"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "first"
    tok.write_text("second")
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "second"
    other = root / "other"
    other.write_text("third")
    _write_config(cfg, f'oauth_token_file = "{other}"\n')
    cli._apply_claude_token_file()
    assert os.environ[VAR] == "third"


def test_children_inherit_token(project):
    import subprocess
    import sys
    root, cfg, _ = project
    tok = root / "tok"
    tok.write_text("child-token")
    _write_config(cfg, f'oauth_token_file = "{tok}"\n')
    cli._apply_claude_token_file()
    out = subprocess.run(
        [sys.executable, "-c", f"import os; print(os.environ['{VAR}'])"],
        capture_output=True, text=True, check=True).stdout.strip()
    assert out == "child-token"
