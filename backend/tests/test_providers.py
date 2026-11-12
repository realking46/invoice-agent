"""Provider selection and LLM-reply parsing (no network needed)."""
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extract.llm import parse_json  # noqa: E402


def test_parse_plain_json():
    assert parse_json('{"total": 100}') == {"total": 100}


def test_parse_fenced_json():
    assert parse_json('```json\n{"total": 100}\n```') == {"total": 100}


def test_parse_json_with_prose_around_it():
    assert parse_json('Here you go: {"total": 100} hope that helps') == {"total": 100}


def test_parse_rejects_no_json():
    with pytest.raises(ValueError):
        parse_json("sorry, I can't read this")


@pytest.mark.parametrize("env,expected", [
    ({"GEMINI_API_KEY": "g"}, "gemini"),
    ({"ANTHROPIC_API_KEY": "a"}, "claude"),
    ({"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}, "gemini"),
    ({"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a", "LLM_PROVIDER": "claude"}, "claude"),
    ({}, None),
])
def test_provider_selection(monkeypatch, env, expected):
    for k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "LLM_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import dotenv
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)  # ignore the developer's real .env here
    from app import config
    importlib.reload(config)
    try:
        assert config.provider() == expected
    finally:
        for k in env:
            monkeypatch.delenv(k, raising=False)
        importlib.reload(config)


def test_busy_model_is_retried_then_backup_model_used(monkeypatch):
    """503 on the main model twice -> backup model answers; no local fallback needed."""
    import sys
    import types as pytypes

    from app import config
    from app.extract import llm

    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "main":
                raise RuntimeError("ServerError: 503 UNAVAILABLE high demand")
            return pytypes.SimpleNamespace(text='{"total": 100, "invoice_number": "X1"}', usage_metadata=None)

    class FakeClient:
        def __init__(self, **kw):
            self.models = FakeModels()

    fake_genai = pytypes.SimpleNamespace(Client=FakeClient)
    from google.genai import types as real_types
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr(sys.modules["google"], "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai.types", real_types)
    fake_genai.types = real_types
    monkeypatch.setattr(config, "GEMINI_MODEL", "main")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    ext, meta = llm._gemini(None, "text", "invoice text")
    assert calls == ["main", "main", "backup"]
    assert ext.total == 100 and meta["model"] == "backup"


def test_non_temporary_error_is_not_retried():
    from app.extract.llm import _is_temporary
    assert _is_temporary(RuntimeError("503 UNAVAILABLE"))
    assert _is_temporary(RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert _is_temporary(TimeoutError("ReadTimeout: The read operation timed out"))
    assert not _is_temporary(RuntimeError("404 NOT_FOUND model retired"))
    assert not _is_temporary(RuntimeError("400 API key not valid"))


def test_timeout_skips_straight_to_backup_model(monkeypatch):
    import sys
    import types as pytypes

    from google.genai import types as real_types

    from app import config
    from app.extract import llm

    calls = []

    class FakeModels:
        def generate_content(self, model, contents, config):
            calls.append(model)
            if model == "main":
                raise TimeoutError("ReadTimeout: The read operation timed out")
            return pytypes.SimpleNamespace(text='{"total": 5}', usage_metadata=None)

    fake_genai = pytypes.SimpleNamespace(Client=lambda **kw: pytypes.SimpleNamespace(models=FakeModels()),
                                         types=real_types)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr(sys.modules["google"], "genai", fake_genai, raising=False)
    monkeypatch.setattr(config, "GEMINI_MODEL", "main")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    ext, meta = llm._gemini(None, "text", "invoice text")
    assert calls == ["main", "backup"]          # no slow retry of the timed-out model
    assert meta["model"] == "backup"


def test_busy_ai_is_skipped_for_a_while_and_progress_is_reported(monkeypatch):
    """After a temporary AI failure, the next invoice goes straight to the local reader (no second wait)."""
    from app import config
    from app import extract as ex
    from app.extract import llm

    calls = []

    def busy(*a, **k):
        calls.append(1)
        raise RuntimeError("ServerError: 503 UNAVAILABLE high demand")

    monkeypatch.setattr(config, "extractor_mode", lambda: "llm")
    monkeypatch.setattr(config, "EXTRACTOR", "auto")
    monkeypatch.setattr(config, "LLM_CACHE", False)
    monkeypatch.setattr(llm, "extract", busy)
    monkeypatch.setitem(ex._AI_DOWN, "until", 0.0)
    first_log, second_log = [], []
    r1 = ex.extract(config.SAMPLES_DIR / "01_happy_clean.pdf", progress=first_log.append)
    r2 = ex.extract(config.SAMPLES_DIR / "03_split_po_part1.pdf", progress=second_log.append)
    assert r1.mode == r2.mode == "local" and r1.data.total and r2.data.total
    assert len(calls) == 1                                   # the second invoice did not call the AI again
    assert r2.fallback_reason.startswith("Skipped")
    assert any("falling back" in m for m in first_log)
    assert any("busy a moment ago" in m for m in second_log)
