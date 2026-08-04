import pytest

from webapp.app import analyzer


def _clear_deprecated_flags(monkeypatch):
    for flag in analyzer.DEPRECATED_SEMANTIC_FLAGS:
        monkeypatch.delenv(flag, raising=False)


def test_semantic_mode_valid(monkeypatch):
    _clear_deprecated_flags(monkeypatch)
    monkeypatch.setenv("SEMANTIC_MODE", "semantic_retrieval")

    mode = analyzer._load_semantic_mode_from_env()

    assert mode == "semantic_retrieval"


def test_semantic_mode_multiple_enabled(monkeypatch):
    _clear_deprecated_flags(monkeypatch)
    monkeypatch.setenv("SEMANTIC_MODE", "legacy,hybrid")

    with pytest.raises(RuntimeError, match="multiple modes"):
        analyzer._load_semantic_mode_from_env()


def test_semantic_mode_missing(monkeypatch):
    _clear_deprecated_flags(monkeypatch)
    monkeypatch.delenv("SEMANTIC_MODE", raising=False)

    with pytest.raises(RuntimeError, match="not configured"):
        analyzer._load_semantic_mode_from_env()


def test_semantic_mode_invalid(monkeypatch):
    _clear_deprecated_flags(monkeypatch)
    monkeypatch.setenv("SEMANTIC_MODE", "unknown_mode")

    with pytest.raises(RuntimeError, match="Unsupported SEMANTIC_MODE"):
        analyzer._load_semantic_mode_from_env()
