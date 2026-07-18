"""H9：实时抓取 inflight 按 provider 分键，主源卡住时备用源仍可发起。"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.services import market


def test_inflight_is_per_provider_so_fallback_can_run(monkeypatch):
    monkeypatch.setattr(market.settings, "enable_realtime_fetch", True)
    monkeypatch.setattr(market, "_rt_inflight", {})

    started = {"slow": 0, "fast": 0}
    release = threading.Event()

    def slow():
        started["slow"] += 1
        release.wait(timeout=2)
        return ["slow"]

    def fast():
        started["fast"] += 1
        return ["fast"]

    # 占用 slow provider 的 inflight 窗口
    t = threading.Thread(
        target=lambda: market._fetch_with_timeout("quotes:slow", slow, 1.0, "slow"),
        daemon=True,
    )
    t.start()
    time.sleep(0.05)

    # 同 key 应被跳过
    assert market._fetch_with_timeout("quotes:slow", slow, 1.0, "slow") is None
    # 不同 provider key 仍可执行
    assert market._fetch_with_timeout("quotes:fast", fast, 1.0, "fast") == ["fast"]
    assert started["fast"] == 1

    release.set()
    t.join(timeout=2)


def test_fetch_quotes_tries_next_provider_when_first_inflight(monkeypatch):
    monkeypatch.setattr(market.settings, "enable_realtime_fetch", True)
    monkeypatch.setattr(market.settings, "realtime_fetch_timeout_seconds", 0.5)
    monkeypatch.setattr(market, "_rt_inflight", {"quotes:akshare": time.monotonic()})

    called = {"efinance": 0}

    def efinance_quotes():
        called["efinance"] += 1
        return ["ok"]

    providers = [
        SimpleNamespace(name="akshare", get_realtime_quotes=lambda: ["should-skip"]),
        SimpleNamespace(name="efinance", get_realtime_quotes=efinance_quotes),
    ]
    monkeypatch.setattr(market, "get_providers_for", lambda _cap: providers)

    assert market._fetch_quotes() == ["ok"]
    assert called["efinance"] == 1
