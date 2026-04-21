"""Tests for token resolution (env vs. file vs. dotenv)."""

from __future__ import annotations

from pathlib import Path

from samanage_mcp import config as config_mod


def _reload_settings(monkeypatch, **env):
    """Re-instantiate Settings under a controlled environment and return it."""
    for k, v in env.items():
        if v is None:
            monkeypatch.delenv(k, raising=False)
        else:
            monkeypatch.setenv(k, v)
    # Bypass .env loading by switching the env_file to a non-existent path.
    Settings = config_mod.Settings
    fresh = Settings(_env_file=None)  # type: ignore[call-arg]
    token, source = config_mod._load_token_from_file(fresh)
    return fresh, token, source


def test_token_from_env(monkeypatch) -> None:
    _, token, source = _reload_settings(
        monkeypatch,
        SAMANAGE_API_TOKEN="from-env-1234",
        SAMANAGE_API_TOKEN_FILE=None,
    )
    assert token == "from-env-1234"
    assert source == "env"


def test_token_from_file(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("from-file-token\n")
    _, token, source = _reload_settings(
        monkeypatch,
        SAMANAGE_API_TOKEN=None,
        SAMANAGE_API_TOKEN_FILE=str(token_path),
    )
    assert token == "from-file-token"
    assert source == "token_file"


def test_env_wins_over_file(monkeypatch, tmp_path: Path) -> None:
    token_path = tmp_path / "token"
    token_path.write_text("should-not-be-used")
    _, token, source = _reload_settings(
        monkeypatch,
        SAMANAGE_API_TOKEN="env-wins",
        SAMANAGE_API_TOKEN_FILE=str(token_path),
    )
    assert token == "env-wins"
    assert source == "env"


def test_missing_token(monkeypatch) -> None:
    _, token, source = _reload_settings(
        monkeypatch,
        SAMANAGE_API_TOKEN=None,
        SAMANAGE_API_TOKEN_FILE=None,
    )
    assert token is None
    assert source == "unset"


def test_missing_token_file_path(monkeypatch, tmp_path: Path) -> None:
    _, token, source = _reload_settings(
        monkeypatch,
        SAMANAGE_API_TOKEN=None,
        SAMANAGE_API_TOKEN_FILE=str(tmp_path / "does-not-exist"),
    )
    assert token is None
    assert source == "unset"
