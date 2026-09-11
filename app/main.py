"""Aplicacao FastAPI do ScraperHub: detecta o scraper e gerencia tarefas."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .assembly import download_season, plan_season
from .scrapers import Scraper, ScraperError, detect, get_scraper, normalize_url
from .search import load_sites, save_sites, search_all, verify_quality
from .tasks import TaskManager


def _web_dir() -> Path:
    """Pasta web/: dentro do pacote onefile (sys._MEIPASS) ou do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1] / "web"


WEB_DIR = _web_dir()

app = FastAPI(title="ScraperHub", version="0.1.0")
manager = TaskManager(max_workers=2)

ALLOWED_HOSTS = ("127.0.0.1", "localhost")


def _origin_ok(value: str, server_port: int | None) -> bool:
    """True se o host do Origin/Referer for o proprio servidor."""
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host not in ALLOWED_HOSTS:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    return port is None or port == server_port


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    """Bloqueia requisicoes de outras origens (CSRF/DNS-rebinding)."""
    server_port = request.url.port if request.url.port else 80
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if value and not _origin_ok(value, server_port):
            return JSONResponse(status_code=403, content={"detail": "Origem nao autorizada."})
    return await call_next(request)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Erro inesperado: devolve o detalhe em vez de um 500 mudo."""
    return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})


class UrlRequest(BaseModel):
    """Corpo com uma unica URL e o scraper forcado opcional."""

    url: str = Field(min_length=1)
    force: str | None = None


class DownloadRequest(BaseModel):
    """Corpo para criar uma tarefa de download."""

    url: str = Field(min_length=1)
    items: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    force: str | None = None


class SearchRequest(BaseModel):
    """Corpo com o termo de busca multi-site."""

    term: str = Field(min_length=1)


class SitesRequest(BaseModel):
    """Corpo com a lista de sites de busca."""

    sites: list[str] = Field(default_factory=list)


class AssembleInfoRequest(BaseModel):
    """Corpo para montar a temporada multi-fonte."""

    term: str = ""
    idioma: str = "qualquer"


class AssembleDownloadRequest(BaseModel):
    """Corpo para baixar a temporada montada."""

    term: str = ""
    idioma: str = "qualquer"
    wanted: list[str] | None = None
    options: dict[str, Any] = Field(default_factory=dict)


def _resolve(url: str, force: str | None = None) -> tuple[Scraper, str]:
    """Resolve o scraper para a URL, normalizando-a uma unica vez."""
    try:
        url = normalize_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if force:
        scraper = get_scraper(force)
        if scraper is None:
            raise HTTPException(status_code=404, detail=f"Scraper desconhecido: {force}")
        return scraper, url
    scraper = detect(url)
    if scraper is None:
        raise HTTPException(status_code=404, detail="Nenhum scraper reconheceu esta URL.")
    return scraper, url


@app.post("/api/detect")
def api_detect(payload: UrlRequest) -> dict:
    """Detecta o scraper adequado para a URL (ou o forcado informado)."""
    scraper, _ = _resolve(payload.url, payload.force)
    return {"scraper_id": scraper.id, "kind": scraper.kind, "label": scraper.label}


@app.post("/api/info")
def api_info(payload: UrlRequest) -> dict:
    """Retorna metadados e itens do conteudo da URL."""
    scraper, url = _resolve(payload.url, payload.force)
    try:
        info = scraper.get_info(url)
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"scraper_id": scraper.id, "kind": scraper.kind, **info}


@app.post("/api/download")
def api_download(payload: DownloadRequest) -> dict:
    """Cria uma tarefa de download em background e retorna o id."""
    scraper, url = _resolve(payload.url, payload.force)

    def run(task_id: str) -> None:
        def progress_cb(progress: int, message: str) -> None:
            manager.update_progress(task_id, progress=progress, current_item=message, log=message)

        scraper.download(url, payload.items, progress_cb, payload.options)

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


@app.post("/api/search")
def api_search(payload: SearchRequest) -> dict:
    """Busca o termo em todos os sites configurados."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    resultados, erros = search_all(term)
    return {"resultados": resultados, "erros": erros}


@app.get("/api/sites")
def api_sites_get() -> dict:
    """Lista os sites de busca configurados."""
    return {"sites": load_sites()}


@app.post("/api/sites")
def api_sites_post(payload: SitesRequest) -> dict:
    """Salva a lista de sites de busca e devolve a versao normalizada."""
    return {"sites": save_sites(payload.sites)}


@app.post("/api/search_verify")
def api_search_verify(payload: UrlRequest) -> dict:
    """Verifica a melhor qualidade do primeiro episodio da serie."""
    result = verify_quality(payload.url)
    if not result.get("suporte"):
        raise HTTPException(status_code=502, detail=result.get("motivo") or "Falha na verificacao.")
    return result


@app.post("/api/assemble_info")
def api_assemble_info(payload: AssembleInfoRequest) -> dict:
    """Monta o plano da temporada: fontes rankeadas e melhor fonte por episodio."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    try:
        return plan_season(term, payload.idioma or "qualquer")
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/assemble_download")
def api_assemble_download(payload: AssembleDownloadRequest) -> dict:
    """Cria a tarefa de download da temporada montada e retorna o id."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")

    def run(task_id: str) -> None:
        def progress_cb(progress: int, message: str) -> None:
            manager.update_progress(task_id, progress=progress, current_item=message, log=message)

        download_season(term, payload.idioma or "qualquer", payload.wanted, progress_cb, payload.options)

    return {"task_id": manager.create(run)}


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
