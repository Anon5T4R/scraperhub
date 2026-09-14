"""Testes do modo assistido de verificacao humana (challenge/CAPTCHA)."""
import time

from fastapi.testclient import TestClient

import app.main as main
from app.scrapers.mangafire import SiteBlocked
from app.tasks import TaskManager


def _wait_status(manager: TaskManager, task_id: str, status: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task and task["status"] == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"tarefa {task_id} nao chegou a {status}")


class _ChallengeScraper:
    """Scraper falso que exige verificacao humana e sabe resolve-la."""

    id, label, kind, supports_challenge = "fake", "Fake", "manga", True

    def get_info(self, url: str) -> dict:
        raise SiteBlocked("precisa resolver")

    def solve_challenge(self, url: str, progress_cb) -> None:
        progress_cb(100, "resolvido")


class _PlainScraper:
    """Scraper falso que nao exige verificacao humana."""

    id, label, kind, supports_challenge = "plain", "Plain", "video", False


def test_info_devolve_409_em_challenge(monkeypatch):
    monkeypatch.setattr(main, "_resolve", lambda url, force=None: (_ChallengeScraper(), url))
    client = TestClient(main.app)
    r = client.post("/api/info", json={"url": "https://x.com/title/y"})
    assert r.status_code == 409
    assert "precisa resolver" in r.json()["detail"]


def test_solve_challenge_recusa_scraper_sem_suporte(monkeypatch):
    monkeypatch.setattr(main, "_resolve", lambda url, force=None: (_PlainScraper(), url))
    client = TestClient(main.app)
    r = client.post("/api/solve_challenge", json={"url": "https://x.com/y"})
    assert r.status_code == 400


def test_solve_challenge_cria_tarefa(monkeypatch):
    monkeypatch.setattr(main, "_resolve", lambda url, force=None: (_ChallengeScraper(), url))
    client = TestClient(main.app)
    r = client.post("/api/solve_challenge", json={"url": "https://x.com/title/y"})
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    _wait_status(main.manager, task_id, "done")
    task = main.manager.get(task_id)
    assert task and task["retry"]["kind"] == "solve_challenge"


def test_scrapers_expoe_supports_challenge():
    client = TestClient(main.app)
    by_id = {s["id"]: s for s in client.get("/api/scrapers").json()}
    assert by_id["mangafire"]["supports_challenge"] is True
    assert by_id["video"]["supports_challenge"] is False
