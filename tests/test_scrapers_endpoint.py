"""Testes do endpoint /api/scrapers (fonte unica dos selects de force)."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_lista_scrapers():
    response = client.get("/api/scrapers")
    assert response.status_code == 200
    scrapers = response.json()
    assert len(scrapers) >= 10
    ids = {s["id"] for s in scrapers}
    # fallback dos selects estaticos do front precisa continuar valido
    assert {"video", "mangafire", "wpmanga", "tsundoku", "mirror", "ebook", "gallery",
            "filehost", "animestream", "enanime"} <= ids
    for s in scrapers:
        assert s["label"] and s["kind"]
