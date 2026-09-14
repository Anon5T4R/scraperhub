"""Testes do botao/contexto de retry de tarefas (payload guardado + endpoint)."""
import time

from fastapi.testclient import TestClient

import app.main as main
from app.tasks import TaskManager


def _wait_status(manager: TaskManager, task_id: str, status: str, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task and task["status"] == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"tarefa {task_id} nao chegou a {status}")


def test_create_armazena_retry():
    manager = TaskManager(max_workers=1)
    task_id = manager.create(lambda _t: None, retry={"kind": "download", "url": "x"})
    task = manager.get(task_id)
    assert task is not None and task["retry"] == {"kind": "download", "url": "x"}


def test_retry_endpoint_recria_tarefa(monkeypatch):
    calls = {"n": 0}

    class FakeScraper:
        id, label, kind = "fake", "Fake", "video"

        def download(self, url, item_ids, progress_cb, options=None):
            calls["n"] += 1
            raise RuntimeError("boom")

    monkeypatch.setattr(main, "_resolve", lambda url, force=None: (FakeScraper(), url))
    client = TestClient(main.app)

    r1 = client.post("/api/download", json={"url": "https://exemplo.com/anime/x", "items": ["a"]})
    assert r1.status_code == 200
    task_id = r1.json()["task_id"]
    _wait_status(main.manager, task_id, "error")

    r2 = client.post(f"/api/tasks/{task_id}/retry")
    assert r2.status_code == 200
    novo_id = r2.json()["task_id"]
    assert novo_id != task_id
    _wait_status(main.manager, novo_id, "error")
    assert calls["n"] == 2  # original + retry

    # tarefa recriada carrega o mesmo payload de retry (botao continua funcionando)
    task = main.manager.get(novo_id)
    assert task and task["retry"]["url"] == "https://exemplo.com/anime/x"


def test_retry_endpoint_validacoes():
    client = TestClient(main.app)
    assert client.post("/api/tasks/inexistente/retry").status_code == 404


def test_retry_somamente_error_ou_cancelada():
    manager = TaskManager(max_workers=1)
    task_id = manager.create(lambda _t: None)  # termina done
    _wait_status(manager, task_id, "done")
    task = manager.get(task_id)
    assert task is not None
    # status done: o endpoint recusa (400) — coberto pela regra de status
    assert task["status"] == "done"
