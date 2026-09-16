"""Aplicacao FastAPI do ScraperHub: detecta o scraper e gerencia tarefas."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .assembly import download_season, plan_full, plan_season
from .ip_switch import (
    available_providers as ip_switch_available,
    load_config as load_ip_switch,
    save_config as save_ip_switch,
    switch_ip,
)
from .manga_search import (
    load_sites as load_manga_sites,
    save_sites as save_manga_sites,
    search_manga,
)
from .scrapers import REGISTRY, Scraper, ScraperError, TaskCancelled, detect, get_scraper, normalize_url
from .scrapers.base import DOWNLOADS_DIR
from .search import load_sites, save_sites, search_all, verify_quality
from .tasks import TaskManager


def _web_dir() -> Path:
    """Pasta web/: dentro do pacote onefile (sys._MEIPASS) ou do projeto."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "web"  # type: ignore[attr-defined]
    return Path(__file__).resolve().parents[1] / "web"


WEB_DIR = _web_dir()

app = FastAPI(title="ScraperHub", version="1.9.3")
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
    """Corpo com o termo de busca multi-site e o idioma opcional."""

    term: str = Field(min_length=1)
    idioma: str = "qualquer"


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


class MangaSearchRequest(BaseModel):
    """Corpo com o termo de busca de mangas."""

    term: str = Field(min_length=1)


class IpSwitchRequest(BaseModel):
    """Corpo opcional para gravar a config da troca de IP."""

    provider: str | None = None
    command: str | None = None
    wait_seconds: int | None = None
    verify_url: str | None = None
    auto: bool | None = None


# Cache dos planos de montagem exibidos: o download reutiliza exatamente o
# plano que o usuario aprovou (mesmas fontes/labels), sem re-propar a web.
PLAN_TTL_S = 1800.0
_plan_cache: dict[str, tuple[float, dict]] = {}
_plan_lock = threading.Lock()


def _plan_key(term: str, idioma: str, full: bool) -> str:
    return f"{term.strip().lower()}|{idioma}|{int(full)}"


def _store_plan(key: str, plan: dict) -> None:
    with _plan_lock:
        _plan_cache[key] = (time.monotonic(), plan)
        expirados = [k for k, (when, _) in _plan_cache.items() if time.monotonic() - when > PLAN_TTL_S]
        for k in expirados:
            del _plan_cache[k]


def _cached_plan(key: str) -> dict | None:
    with _plan_lock:
        entry = _plan_cache.get(key)
        if entry is None:
            return None
        when, plan = entry
        if time.monotonic() - when > PLAN_TTL_S:
            del _plan_cache[key]
            return None
        return plan


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


@app.get("/api/scrapers")
def api_scrapers() -> list[dict]:
    """Lista os scrapers disponiveis (id, label, kind) para os selects da UI."""
    return [
        {
            "id": s.id,
            "label": s.label,
            "kind": s.kind,
            "supports_challenge": s.supports_challenge,
        }
        for s in REGISTRY
    ]


@app.get("/api/meta")
def api_meta() -> dict:
    """Versao do backend e pasta onde os downloads sao gravados."""
    return {"version": app.version, "downloads_dir": str(DOWNLOADS_DIR)}


@app.post("/api/detect")
def api_detect(payload: UrlRequest) -> dict:
    """Detecta o scraper adequado para a URL (ou o forcado informado)."""
    scraper, _ = _resolve(payload.url, payload.force)
    return {"scraper_id": scraper.id, "kind": scraper.kind, "label": scraper.label}


@app.post("/api/info")
def api_info(payload: UrlRequest) -> dict:
    """Retorna metadados e itens do conteudo da URL.

    Quando o site exige verificacao humana (challenge), devolve 409 com a
    mensagem: a UI oferece o modo assistido (/api/solve_challenge).
    """
    scraper, url = _resolve(payload.url, payload.force)
    try:
        info = scraper.get_info(url)
    except ScraperError as exc:
        status = 409 if getattr(exc, "challenge", False) else 502
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return {"scraper_id": scraper.id, "kind": scraper.kind, "label": scraper.label, **info}


def _progress_reporter(task_id: str):
    def progress_cb(progress: int, message: str) -> None:
        if manager.is_cancelled(task_id):
            raise TaskCancelled()
        manager.update_progress(task_id, progress=progress, current_item=message, log=message)

    return progress_cb


def _create_download_task(payload: DownloadRequest) -> str:
    """Cria a tarefa de download (usada pelo endpoint e pelo retry)."""
    scraper, url = _resolve(payload.url, payload.force)
    retry = {
        "kind": "download",
        "url": payload.url,
        "items": payload.items,
        "options": payload.options,
        "force": payload.force,
    }

    def run(task_id: str) -> None:
        scraper.download(url, payload.items, _progress_reporter(task_id), payload.options)

    return manager.create(run, retry=retry)


def _create_solve_task(payload: UrlRequest) -> str:
    """Cria a tarefa do modo assistido (usada pelo endpoint e pelo retry)."""
    scraper, url = _resolve(payload.url, payload.force)
    if not getattr(scraper, "supports_challenge", False):
        raise HTTPException(status_code=400, detail="Este scraper nao requer verificacao humana.")
    retry = {"kind": "solve_challenge", "url": payload.url, "force": payload.force}

    def run(task_id: str) -> None:
        scraper.solve_challenge(url, _progress_reporter(task_id))

    return manager.create(run, retry=retry)


def _create_assemble_task(payload: AssembleDownloadRequest, full: bool) -> str:
    """Cria a tarefa de montacao+download (usada pelo endpoint e pelo retry)."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    plan = _cached_plan(_plan_key(term, payload.idioma or "qualquer", full))
    retry = {
        "kind": "assemble_full" if full else "assemble",
        "term": term,
        "idioma": payload.idioma,
        "wanted": payload.wanted,
        "options": payload.options,
    }

    def run(task_id: str) -> None:
        download_season(
            term,
            payload.idioma or "qualquer",
            payload.wanted,
            _progress_reporter(task_id),
            payload.options,
            full=full,
            plan=plan,
        )

    return manager.create(run, retry=retry)


@app.post("/api/download")
def api_download(payload: DownloadRequest) -> dict:
    """Cria uma tarefa de download em background e retorna o id."""
    return {"task_id": _create_download_task(payload)}


@app.post("/api/solve_challenge")
def api_solve_challenge(payload: UrlRequest) -> dict:
    """Cria a tarefa do modo assistido (abre a janela para resolver o CAPTCHA)."""
    return {"task_id": _create_solve_task(payload)}


@app.get("/api/ip_switch")
def api_ip_switch_get() -> dict:
    """Config atual da troca de IP + providers disponiveis nesta maquina."""
    return {"config": load_ip_switch(), "available": ip_switch_available()}


@app.post("/api/ip_switch")
def api_ip_switch_post(payload: IpSwitchRequest) -> dict:
    """Grava a config da troca de IP (usada pelo botao e pelo modo auto)."""
    data = {key: value for key, value in payload.model_dump().items() if value is not None}
    return {"config": save_ip_switch(data)}


@app.post("/api/ip_switch/run")
def api_ip_switch_run() -> dict:
    """Cria a tarefa de troca de IP e retorna o id."""

    def run(task_id: str) -> None:
        switch_ip(_progress_reporter(task_id))

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


@app.post("/api/tasks/{task_id}/cancel")
def api_task_cancel(task_id: str) -> dict:
    """Marca uma tarefa para cancelamento."""
    if not manager.cancel(task_id):
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada ou ja finalizada.")
    return {"ok": True}


@app.post("/api/search")
def api_search(payload: SearchRequest) -> dict:
    """Busca o termo em todos os sites configurados."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    resultados, erros = search_all(term, payload.idioma or "qualquer")
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
        plan = plan_season(term, payload.idioma or "qualquer")
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _store_plan(_plan_key(term, payload.idioma or "qualquer", False), plan)
    return plan


@app.post("/api/assemble_download")
def api_assemble_download(payload: AssembleDownloadRequest) -> dict:
    """Cria a tarefa de download da temporada montada e retorna o id."""
    return {"task_id": _create_assemble_task(payload, full=False)}


@app.post("/api/manga_search")
def api_manga_search(payload: MangaSearchRequest) -> dict:
    """Busca mangas por nome (MangaFire + sites WordPress)."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    resultados, erros = search_manga(term)
    return {"resultados": resultados, "erros": erros}


@app.get("/api/manga_sites")
def api_manga_sites_get() -> dict:
    """Lista os sites de manga configurados."""
    return {"sites": load_manga_sites()}


@app.post("/api/manga_sites")
def api_manga_sites_post(payload: SitesRequest) -> dict:
    """Salva a lista de sites de manga."""
    return {"sites": save_manga_sites(payload.sites)}


@app.post("/api/assemble_full_info")
def api_assemble_full_info(payload: AssembleInfoRequest) -> dict:
    """Monta o anime COMPLETO: todas as temporadas, multi-fonte."""
    term = payload.term.strip()
    if not term:
        raise HTTPException(status_code=400, detail="Informe um termo de busca.")
    try:
        plan = plan_full(term, payload.idioma or "qualquer")
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _store_plan(_plan_key(term, payload.idioma or "qualquer", True), plan)
    return plan


@app.post("/api/assemble_full_download")
def api_assemble_full_download(payload: AssembleDownloadRequest) -> dict:
    """Cria a tarefa de download do anime completo montado."""
    return {"task_id": _create_assemble_task(payload, full=True)}


@app.post("/api/tasks/{task_id}/retry")
def api_task_retry(task_id: str) -> dict:
    """Recria uma tarefa com erro/cancelada a partir do payload original."""
    task = manager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Tarefa nao encontrada.")
    if task["status"] not in ("error", "cancelled"):
        raise HTTPException(status_code=400, detail="So tarefas com erro ou canceladas podem ser repetidas.")
    retry = task.get("retry") or {}
    kind = retry.get("kind")
    if kind == "download":
        payload = DownloadRequest(
            url=retry["url"],
            items=retry.get("items") or [],
            options=retry.get("options") or {},
            force=retry.get("force"),
        )
        return {"task_id": _create_download_task(payload)}
    if kind == "solve_challenge":
        return {"task_id": _create_solve_task(UrlRequest(url=retry["url"], force=retry.get("force")))}
    if kind in ("assemble", "assemble_full"):
        payload = AssembleDownloadRequest(
            term=retry.get("term") or "",
            idioma=retry.get("idioma") or "qualquer",
            wanted=retry.get("wanted"),
            options=retry.get("options") or {},
        )
        return {"task_id": _create_assemble_task(payload, full=kind == "assemble_full")}
    raise HTTPException(status_code=400, detail="Tarefa sem dados para repetir.")


app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
