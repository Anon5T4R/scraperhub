"""Testes do retry de download_binary (page simulado, sem Playwright)."""
from __future__ import annotations

import pytest

from app.scrapers.browser import download_binary
from app.scrapers.base import ScraperError


class _FakeRequest:
    """Simula APIRequest do Playwright com roteiro de respostas."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls = 0

    def get(self, url: str, headers: dict) -> "_FakeResponse":
        self.calls += 1
        step = self.script.pop(0)  # IndexError = mais chamadas que o roteiro
        if isinstance(step, Exception):
            raise step
        return step


class _FakeContext:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request


class _FakePage:
    def __init__(self, request: _FakeRequest) -> None:
        self.context = _FakeContext(request)
        self.url = "https://site.test/pagina"


class _FakeResponse:
    def __init__(self, ok: bool, body: bytes = b"") -> None:
        self.ok = ok
        self.status = 403 if not ok else 200
        self._body = body

    def body(self) -> bytes:
        return self._body


def test_sucesso_na_primeira(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scrapers.browser.BINARY_BACKOFF_S", ())
    req = _FakeRequest([_FakeResponse(True, b"abc")])
    assert download_binary(_FakePage(req), "https://cdn.test/a.jpg") == b"abc"
    assert req.calls == 1


def test_retry_apos_socket_hang_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scrapers.browser.BINARY_BACKOFF_S", (0.0, 0.0))
    req = _FakeRequest([ConnectionError("socket hang up"), _FakeResponse(True, b"ok")])
    assert download_binary(_FakePage(req), "https://cdn.test/a.jpg") == b"ok"
    assert req.calls == 2


def test_retry_apos_403_e_desiste(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scrapers.browser.BINARY_BACKOFF_S", (0.0, 0.0))
    req = _FakeRequest([_FakeResponse(False), _FakeResponse(False), _FakeResponse(False)])
    with pytest.raises(ScraperError, match="403"):
        download_binary(_FakePage(req), "https://cdn.test/a.jpg")
    assert req.calls == 3


def test_referer_enviado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.scrapers.browser.BINARY_BACKOFF_S", ())
    seen: dict = {}
    req = _FakeRequest([_FakeResponse(True, b"x")])

    def get(url: str, headers: dict) -> _FakeResponse:
        seen.update(headers)
        return _FakeResponse(True, b"x")

    req.get = get  # type: ignore[method-assign]
    download_binary(_FakePage(req), "https://cdn.test/a.jpg")
    assert seen["Referer"] == "https://site.test/pagina"
