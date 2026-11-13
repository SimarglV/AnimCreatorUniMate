"""LLM scaffolding: backend detection, loopback detection, and the no-key path for
local OpenAI-compatible servers (LM Studio / Ollama / vLLM)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def llm(monkeypatch):
    # data_process/joint_annotation/llm.py only needs `logger`; stub loguru so the
    # module imports in the studio env (which does not install UniMate's loguru).
    loguru = types.ModuleType("loguru")
    loguru.logger = types.SimpleNamespace(info=lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "loguru", loguru)
    import data_process.joint_annotation.llm as module
    return module


def test_detect_backend_routes_names_to_local_or_openai(llm):
    assert llm.detect_backend("Qwen/Qwen3-8B") == "local"
    assert llm.detect_backend("gemma-3-8b-it") == "local"
    assert llm.detect_backend("gpt-5-mini") == "openai"
    assert llm.detect_backend("deepseek-v4-flash") == "openai"


@pytest.mark.parametrize("url, expected", [
    ("http://127.0.0.1:1234/v1", True),
    ("http://localhost:1234/v1", True),
    ("http://0.0.0.0:8000/v1", True),
    ("http://[::1]:11434/v1", True),
    ("127.0.0.1:1234/v1", True),          # no scheme, still loopback
    ("https://api.deepseek.com", False),
    ("https://api.openai.com/v1", False),
    ("", False),
    (None, False),
])
def test_is_local_base_url(llm, url, expected):
    assert llm.is_local_base_url(url) is expected


def test_generate_openai_uses_a_placeholder_key_for_a_loopback_server(llm, monkeypatch):
    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured["kwargs"] = kwargs

            class Choice:
                message = types.SimpleNamespace(content="Hips")
                finish_reason = "stop"

            class Response:
                choices = [Choice()]

            return Response()

    class FakeClient:
        def __init__(self, api_key, base_url):
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            self.chat = types.SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeClient))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    out = llm.generate_openai("sys", "user", "gemma-4-12b-it", None,
                              "http://127.0.0.1:1234/v1", 512)
    assert out == "Hips"
    assert captured["api_key"] == "local"
    assert captured["base_url"] == "http://127.0.0.1:1234/v1"


def test_generate_openai_raises_without_a_key_for_a_hosted_endpoint(llm, monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=object))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.generate_openai("sys", "user", "gpt-5-mini", None, None, 512)
