"""Testes do trocador de IP (config, providers e verificacao)."""
from fastapi.testclient import TestClient

import app.ip_switch as ip
import app.main as main
from app.scrapers.base import ScraperError


def test_load_config_padrao(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "ip-switch.json")
    cfg = ip.load_config()
    assert cfg["provider"] == "off"
    assert cfg["auto"] is False


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "ip-switch.json")
    saved = ip.save_config({"provider": "custom", "command": "echo oi", "auto": True, "lixo": 1})
    assert saved["provider"] == "custom" and saved["auto"] is True
    assert "lixo" not in saved
    assert ip.load_config()["command"] == "echo oi"


def test_available_providers():
    providers = ip.available_providers()
    assert providers["custom"] is True
    assert isinstance(providers["warp"], bool)


def test_switch_desativado_levanta(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "CONFIG_PATH", tmp_path / "ip-switch.json")
    try:
        ip.switch_ip(lambda p, m: None)
    except ScraperError as exc:
        assert "desativada" in str(exc)
    else:
        raise AssertionError("esperava ScraperError com provider off")


def test_switch_custom_detecta_mudanca(monkeypatch):
    ips = iter(["1.1.1.1", "2.2.2.2"])
    monkeypatch.setattr(ip, "public_ip", lambda url=None: next(ips))
    cfg = {"provider": "custom", "command": "exit 0", "wait_seconds": 0}
    result = ip.switch_ip(lambda p, m: None, config=cfg)
    assert result["provider"] == "custom"
    assert result["ip_before"] == "1.1.1.1"
    assert result["ip_after"] == "2.2.2.2"
    assert result["changed"] is True


def test_switch_custom_falha(monkeypatch):
    monkeypatch.setattr(ip, "public_ip", lambda url=None: "1.1.1.1")
    cfg = {"provider": "custom", "command": "exit 3", "wait_seconds": 0}
    try:
        ip.switch_ip(lambda p, m: None, config=cfg)
    except ScraperError as exc:
        assert "falhou" in str(exc)
    else:
        raise AssertionError("esperava ScraperError do comando")


def test_endpoint_config_e_available():
    client = TestClient(main.app)
    data = client.get("/api/ip_switch").json()
    assert "config" in data and "available" in data
    assert data["available"]["custom"] is True
