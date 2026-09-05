"""H8：LLMQuant MCP 包版本钉死 + 子进程环境隔离。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.providers import llmquant


def test_pinned_package_rejects_unversioned_and_latest(monkeypatch):
    monkeypatch.setattr(llmquant.settings, "llmquant_mcp_package", "@llmquant/data-mcp")
    assert llmquant._pinned_package() is None
    monkeypatch.setattr(llmquant.settings, "llmquant_mcp_package", "@llmquant/data-mcp@latest")
    assert llmquant._pinned_package() is None
    monkeypatch.setattr(llmquant.settings, "llmquant_mcp_package", "@llmquant/data-mcp@0.5.2")
    assert llmquant._pinned_package() == "@llmquant/data-mcp@0.5.2"


def test_sanitized_env_strips_host_secrets(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret")
    monkeypatch.setenv("JWT_SECRET", "super-secret")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LLMQUANT_EXTRA", "ok")
    monkeypatch.setattr(llmquant.settings, "llmquant_api_key", "lq-key")
    monkeypatch.setattr(llmquant.settings, "llmquant_base_url", "https://api.example.com")

    env = llmquant._sanitized_env()
    assert env["LLMQUANT_API_KEY"] == "lq-key"
    assert env["LLMQUANT_BASE_URL"] == "https://api.example.com"
    assert env["PATH"] == "/usr/bin"
    assert env["LLMQUANT_EXTRA"] == "ok"
    assert "DATABASE_URL" not in env
    assert "JWT_SECRET" not in env
    assert "DEEPSEEK_API_KEY" not in env


def test_run_mcp_uses_pinned_package_and_sanitized_env(monkeypatch):
    monkeypatch.setattr(llmquant.settings, "llmquant_enabled", True)
    monkeypatch.setattr(llmquant.settings, "llmquant_api_key", "lq-key")
    monkeypatch.setattr(llmquant.settings, "llmquant_mcp_package", "@llmquant/data-mcp@0.5.2")
    monkeypatch.setattr(llmquant.shutil, "which", lambda _name: "/usr/bin/npx")

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env")
        return MagicMock(stdout="", returncode=0)

    monkeypatch.setenv("JWT_SECRET", "must-not-leak")
    with patch("app.providers.llmquant.subprocess.run", side_effect=fake_run):
        llmquant._run_mcp([("wiki_search", {"query": "x"})])

    assert captured["cmd"] == ["/usr/bin/npx", "-y", "@llmquant/data-mcp@0.5.2"]
    assert "JWT_SECRET" not in (captured["env"] or {})
    assert captured["env"]["LLMQUANT_API_KEY"] == "lq-key"
