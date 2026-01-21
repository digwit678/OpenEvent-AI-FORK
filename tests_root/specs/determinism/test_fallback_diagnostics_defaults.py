from __future__ import annotations

import importlib


def _reload_fallback():
    module = importlib.import_module("core.fallback")
    return importlib.reload(module)


def test_fallback_diagnostics_default_dev(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("OE_FALLBACK_DIAGNOSTICS", raising=False)
    fallback = _reload_fallback()
    assert fallback.SHOW_FALLBACK_DIAGNOSTICS is True


def test_fallback_diagnostics_default_prod(monkeypatch):
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.delenv("OE_FALLBACK_DIAGNOSTICS", raising=False)
    fallback = _reload_fallback()
    assert fallback.SHOW_FALLBACK_DIAGNOSTICS is False


def test_fallback_diagnostics_override(monkeypatch):
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.setenv("OE_FALLBACK_DIAGNOSTICS", "0")
    fallback = _reload_fallback()
    assert fallback.SHOW_FALLBACK_DIAGNOSTICS is False
