"""Testes do TaskManager: estados, erro e limites do log."""
import threading
import time

from app.tasks import MAX_LOG_LINES, TaskManager


def _wait(task_id: str, manager: TaskManager, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = manager.get(task_id)
        if task["status"] in ("done", "error"):
            return task
        time.sleep(0.01)
    raise AssertionError("tarefa nao terminou a tempo")


def test_run_instantaneo_done():
    manager = TaskManager(max_workers=1)
    task_id = manager.create(lambda _tid: None)
    task = _wait(task_id, manager)
    assert task["status"] == "done"
    assert task["progress"] == 100
    assert task["error"] is None
    assert task["log"][-1] == "Concluido"


def test_run_que_lanca_error():
    manager = TaskManager(max_workers=1)

    def falha(_tid: str) -> None:
        raise RuntimeError("explodiu")

    task_id = manager.create(falha)
    task = _wait(task_id, manager)
    assert task["status"] == "error"
    assert task["error"] == "explodiu"
    assert task["log"][-1] == "explodiu"


def test_log_dedup():
    manager = TaskManager(max_workers=1)
    libera = threading.Event()
    task_id = manager.create(lambda _tid: libera.wait(5))
    manager.update_progress(task_id, log="mesma linha")
    manager.update_progress(task_id, log="mesma linha")
    task = manager.get(task_id)
    assert task["log"].count("mesma linha") == 1
    libera.set()
    _wait(task_id, manager)


def test_log_cap_50():
    manager = TaskManager(max_workers=1)
    libera = threading.Event()
    task_id = manager.create(lambda _tid: libera.wait(5))
    for i in range(60):
        manager.update_progress(task_id, log=f"linha {i}")
    task = manager.get(task_id)
    assert len(task["log"]) == MAX_LOG_LINES
    assert task["log"][0] == "linha 10"
    assert task["log"][-1] == "linha 59"
    libera.set()
    _wait(task_id, manager)