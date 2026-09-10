"""Aplicacao FastAPI do ScraperHub: detecta o scraper e gerencia tarefas."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .scrapers import Scraper, ScraperError, detect
from .tasks import TaskManager

WEB_DIR = Path(__file__).resolve().parents[1] / "web"

app = FastAPI(title="ScraperHub", version="0.1.0")
manager = TaskManager(max_workers=2)


class UrlRequest(BaseModel):
    """Corpo com uma unica URL."""

    url: str = Field(min_length=1)


class DownloadRequest(BaseModel):
    """Corpo para criar uma tarefa de download."""

    url: str = Field(min_length=1)
    items: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)


def _resolve(url: str) -> Scraper:
    scraper = detect(url)
    if scraper is None:
        raise HTTPException(status_code=404, detail="Nenhum scraper reconheceu esta URL.")
    return scraper


@app.post("/api/detect")
def api_detect(payload: UrlRequest) -> dict:
    """Detecta o scraper adequado para a URL."""
    scraper = _resolve(payload.url)
    return {"scraper_id": scraper.id, "kind": scraper.kind, "label": scraper.label}


@app.post("/api/info")
def api_info(payload: UrlRequest) -> dict:
    """Retorna metadados e itens do conteudo da URL."""
    scraper = _resolve(payload.url)
    try:
        info = scraper.get_info(payload.url)
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"scraper_id": scraper.id, "kind": scraper.kind, **info}


@app.post("/api/download")
def api_download(payload: DownloadRequest) -> dict:
    """Cria uma tarefa de download em background e retorna o id."""
    scraper = _resolve(payload.url)

    def run(task_id: str) -> None:
        def progress_cb(progress: int, message: str) -> None:
            manager.update_progress(task_id, progress=progress, current_item=message, log=message)

        scraper.download(payload.url, payload.items, progress_cb, payload.options)

    return {"task_id": manager.create(run)}


@app.get("/api/tasks")
def api_tasks() -> list[dict]:
    """Lista todas as tarefas."""
    return manager.list_tasks()


@app.get("/api/tasks/{task_id}")
def api_task(task_id: str) -> dict:
    """Retorna o estado de uma tarefa."""
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada.")
    return task


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
