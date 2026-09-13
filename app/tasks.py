"""Gerenciador de tarefas em memoria com execucao em pool de threads."""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable

from .scrapers.base import TaskCancelled

MAX_LOG_LINES = 50
MAX_FINISHED_TASKS = 50
TaskRun = Callable[[str], None]


class TaskManager:
    """Mantem tarefas em memoria e as executa em background."""

    def __init__(self, max_workers: int = 2) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def create(self, run: TaskRun) -> str:
        """Registra uma tarefa e agenda sua execucao, retornando o id."""
        task_id = uuid.uuid4().hex
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "status": "pending",
                "progress": 0,
                "current_item": None,
                "log": [],
                "error": None,
                "cancel": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        self._executor.submit(self._run, task_id, run)
        with self._lock:
            self._prune()
        return task_id

    def _prune(self) -> None:
        """Remove as tarefas finalizadas mais antigas (mantem MAX_FINISHED_TASKS).

        Deve ser chamada dentro do lock. So remove tarefas terminadas:
        pending/running nunca sao descartadas.
        """
        finalizados = [
            tid
            for tid, task in self._tasks.items()
            if task["status"] in ("done", "error", "cancelled")
        ]
        excedente = len(finalizados) - MAX_FINISHED_TASKS
        for tid in finalizados[:excedente]:  # dict preserva ordem: mais antigas primeiro
            del self._tasks[tid]

    def cancel(self, task_id: str) -> bool:
        """Marca a tarefa para cancelamento; False se ja finalizada ou inexistente."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task["status"] in ("done", "error", "cancelled"):
                return False
            task["cancel"] = True
            return True

    def is_cancelled(self, task_id: str) -> bool:
        """True se a tarefa foi marcada para cancelamento."""
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task.get("cancel"))

    def _run(self, task_id: str, run: TaskRun) -> None:
        self.update_progress(task_id, status="running")
        try:
            run(task_id)
        except TaskCancelled:
            self.update_progress(task_id, status="cancelled", current_item=None, log="Cancelada", error=None)
            return
        except Exception as exc:  # noqa: BLE001 - erro do scraper vira estado da tarefa
            message = str(exc) or exc.__class__.__name__
            self.update_progress(task_id, log=message, status="error", error=message)
            return
        self.update_progress(
            task_id, progress=100, current_item=None, log="Concluido", status="done"
        )

    def update_progress(
        self,
        task_id: str,
        progress: int | None = None,
        current_item: str | None = None,
        log: str | None = None,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        """Atualiza campos de uma tarefa; exposta ao scraper via callback."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return
            if progress is not None:
                task["progress"] = max(0, min(100, int(progress)))
            if current_item is not None:
                task["current_item"] = current_item
            if log is not None:
                self._append_log(task, log)
            if status is not None:
                task["status"] = status
            if error is not None:
                task["error"] = error

    @staticmethod
    def _append_log(task: dict[str, Any], line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        log: list[str] = task["log"]
        if log and log[-1] == text:
            return
        log.append(text)
        if len(log) > MAX_LOG_LINES:
            del log[:-MAX_LOG_LINES]

    def get(self, task_id: str) -> dict[str, Any] | None:
        """Retorna um snapshot da tarefa ou None se nao existir."""
        with self._lock:
            task = self._tasks.get(task_id)
            return None if task is None else self._snapshot(task)

    def list_tasks(self) -> list[dict[str, Any]]:
        """Retorna snapshots de todas as tarefas, mais recentes por ultimo."""
        with self._lock:
            return [self._snapshot(task) for task in self._tasks.values()]

    @staticmethod
    def _snapshot(task: dict[str, Any]) -> dict[str, Any]:
        return {**task, "log": list(task["log"])}
