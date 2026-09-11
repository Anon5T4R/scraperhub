"""Testes do middleware anti-CSRF/DNS-rebinding via TestClient."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, base_url="http://localhost:8765")


def test_origin_malicioso_bloqueado():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Origin": "http://evil.com"},
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Origem nao autorizada."}


def test_referer_malicioso_bloqueado():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Referer": "http://evil.com/pagina"},
    )
    assert response.status_code == 403


def test_origin_porta_errada_bloqueado():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Origin": "http://localhost:9999"},
    )
    assert response.status_code == 403


def test_sem_origin_passa():
    response = client.post("/api/detect", json={"url": "https://animeq.cloud/"})
    assert response.status_code == 200


def test_origin_localhost_8765_passa():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Origin": "http://localhost:8765"},
    )
    assert response.status_code == 200


def test_origin_127_0_0_1_8765_passa():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Origin": "http://127.0.0.1:8765"},
    )
    assert response.status_code == 200


def test_origin_localhost_sem_porta_passa():
    response = client.post(
        "/api/detect",
        json={"url": "https://animeq.cloud/"},
        headers={"Origin": "http://localhost"},
    )
    assert response.status_code == 200


def test_url_invalida_sem_origin_retorna_400():
    response = client.post("/api/detect", json={"url": "foo bar"})
    assert response.status_code == 400
    assert "URL inválida" in response.json()["detail"]