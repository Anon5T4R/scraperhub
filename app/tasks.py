"""Gerenciador de tarefas em memoria com execucao em pool de threads."""
from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .scrapers.base import TaskCancelled, app_root

MAX_LOG_LINES = 50
MAX_FINISHED_TASKS = 50
FINAL_STATUSES = ("done", "error", "cancelled")
INTERRUPTED_LOG = "Interrompida pelo reinicio do app"
STATE_FILENAME = "tasks-state.json"
TaskRun = Callable[[str], None]


class TaskManager:
    """Mantem tarefas em memoria e as executa em background.

    As tarefas finalizadas ficam em `tasks-state.json` (ao lado do exe/raiz do
    app) para sobreviver a reinicios. As filas sao separadas: downloads (N
    workers) e tarefas interativas (1 worker), para que um download lento nao
    trave o modo assistido nem a troca de IP.
    """

    def __init__(self, max_workers: int = 2, state_path: Path | None = None) -> None:
        self._tasks: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._persist_lock = threading.Lock()
        self._executors = {
            "download": ThreadPoolExecutor(max_workers=max_workers),
            "interactive": ThreadPoolExecutor(max_workers=1),
        }
        self._state_path = Path(state_path) if state_path is not None else app_root() / STATE_FILENAME
        self._load()

    def create(
        self,
        run: TaskRun,
        retry: dict[str, Any] | None = None,
        queue: str = "download",
    ) -> str:
        """Registra uma tarefa e agenda sua execucao, retornando o id.

        `retry` descreve como recriar esta tarefa (payload original do
        endpoint) e permite o botao "Tentar de novo" na UI. `queue` escolhe a
        fila: "download" (padrao) ou "interactive".
        """
        task_id = uuid.uuid4().hex
        with self._lock:
            self._tasks[task_id] = {
                "id": task_id,
                "status": "pending",
                "progress": 0,
                "current_item": None,
                "log": [],
                "error": None,
                "error_challenge": False,
                "cancel": False,
                "retry": retry,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        executor = self._executors.get(queue) or self._executors["download"]
        executor.submit(self._run, task_id, run)
        with self._lock:
            self._prune()
        self._persist()
        return task_id

    def _prune(self) -> None:
        """Remove as tarefas finalizadas mais antigas (mantem MAX_FINISHED_TASKS).

        Deve ser chamada dentro do lock. So remove tarefas terminadas:
        pending/running nunca sao descartadas.
        """
        finalizados = [
            tid
            for tid, task in self._tasks.items()
            if task["status"] in FINAL_STATUSES
        ]
        excedente = len(finalizados) - MAX_FINISHED_TASKS
        for tid in finalizados[:excedente]:  # dict preserva ordem: mais antigas primeiro
            del self._tasks[tid]

    def cancel(self, task_id: str) -> bool:
        """Marca a tarefa para cancelamento; False se ja finalizada ou inexistente."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task["status"] in FINAL_STATUSES:
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
            self.update_progress(
                task_id,
                log=message,
                status="error",
                error=message,
                # permite a UI oferecer o modo assistido em vez de so re-falhar
                error_challenge=getattr(exc, "challenge", False),
            )
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
        error_challenge: bool | None = None,
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
            if error_challenge is not None:
                task["error_challenge"] = bool(error_challenge)
            finalizou = status in FINAL_STATUSES
        if finalizou:
            self._persist()

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

    def _load(self) -> None:
        """Carrega o estado persistido, se existir.

        Tarefas que estavam pendentes/em execucao quando o app caiu viram
        `cancelled` (com o retry preservado, entao "Tentar de novo" funciona).
        As finalizadas passam pelo prune normal.
        """
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        with self._lock:
            for task_id, task in raw.items():
                if isinstance(task, dict):
                    self._tasks[str(task_id)] = self._restore(str(task_id), task)
            self._prune()
        self._persist()

    @staticmethod
    def _restore(task_id: str, task: dict[str, Any]) -> dict[str, Any]:
        """Reconstroi uma tarefa salva, interrompendo as que ficaram em voo."""
        restaurada: dict[str, Any] = {
            "id": str(task.get("id") or task_id),
            "status": str(task.get("status") or "pending"),
            "progress": int(task.get("progress") or 0),
            "current_item": task.get("current_item"),
            "log": [str(line) for line in (task.get("log") or [])],
            "error": task.get("error"),
            "error_challenge": bool(task.get("error_challenge")),
            "cancel": bool(task.get("cancel")),
            "retry": task.get("retry"),
            "created_at": str(task.get("created_at") or ""),
        }
        if restaurada["status"] in ("pending", "running"):
            restaurada["status"] = "cancelled"
            restaurada["current_item"] = None
            restaurada["progress"] = 0
            TaskManager._append_log(restaurada, INTERRUPTED_LOG)
        return restaurada

    def _persist(self) -> None:
        """Grava o estado serializavel das tarefas (sem callables).

        Chamado ao criar e ao finalizar tarefas; escrita atomica (tmp +
        replace) para nao deixar o arquivo pela metade.
        """
        with self._lock:
            payload = {
                task_id: {
                    **{key: value for key, value in task.items() if key != "run"},
                    "log": list(task.get("log") or []),
                }
                for task_id, task in self._tasks.items()
            }
        with self._persist_lock:
            path = self._state_path
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
            tmp = path.with_name(path.name + ".tmp")
            try:
                tmp.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                os.replace(tmp, path)
            except OSError:
                return
            try:
                os.chmod(path, 0o600)  # best effort: o Windows ignora parcialmente
            except OSError:
                pass
