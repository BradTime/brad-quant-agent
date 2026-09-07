from app.ai.deepseek import completion_options
from app.core.config import settings


def test_v4_calls_explicitly_disable_thinking(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_model", "deepseek-v4-flash")
    assert completion_options() == {
        "extra_body": {"thinking": {"type": "disabled"}}
    }


def test_legacy_models_do_not_receive_v4_options(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_model", "legacy-model")
    assert completion_options() == {}
