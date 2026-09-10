"""Helpers de rede/yt-dlp compartilhados pelo scraper de animes."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .base import DOWNLOADS_DIR, ProgressCb, ScraperError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
RATE_S = 0.5


def host(url: str) -> str:
    """Hostname em minusculas sem www."""
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def fetch(url: str, referer: str | None = None) -> str:
    """GET com UA de navegador; erros viram ScraperError."""
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    try:
        with httpx.Client(follow_redirects=True, timeout=30) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        raise ScraperError(f"Falha ao acessar a pagina: {exc}") from exc


def sanitize(name: str) -> str:
    """Remove caracteres invalidos para nomes de arquivo/pasta."""
    return re.sub(r'[<>:"/\\|?*]', "_", name).strip() or "Anime"


def _hook(progress_cb: ProgressCb):  # noqa: ANN202 - callback do yt-dlp
    def hook(status: dict) -> None:
        if status.get("status") != "downloading":
            return
        total = status.get("total_bytes") or status.get("total_bytes_estimate")
        done = status.get("downloaded_bytes") or 0
        percent = int(done * 100 / total) if total else 0
        filename = (status.get("filename") or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        progress_cb(percent, f"Baixando {filename}... {percent}%")

    return hook


def ytdlp(url: str, outtmpl: str, progress_cb: ProgressCb, ffmpeg: str | None) -> None:
    """Baixa uma URL via yt-dlp (mp4 direto, HLS, etc.)."""
    import yt_dlp

    options: dict[str, Any] = {
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [_hook(progress_cb)],
    }
    if ffmpeg:
        options["ffmpeg_location"] = str(Path(ffmpeg).parent)
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as exc:
        raise ScraperError(f"yt-dlp falhou: {str(exc)[-300:]}") from exc


def run_downloads(
    selected: list[dict],
    download_one: Callable[[str, str], None],
    progress_cb: ProgressCb,
) -> None:
    """Baixa os itens selecionados com progresso agregado e rate limit."""
    total = len(selected)
    for index, item in enumerate(selected, start=1):
        label = str(item["label"])
        progress_cb(int((index - 1) / total * 100), f"Iniciando {label} ({index}/{total})")
        download_one(str(item["id"]), label)
        progress_cb(int(index / total * 100), f"Concluido {label} ({index}/{total})")
        if index < total:
            time.sleep(RATE_S)


def ensure_folder(title: str) -> Path:
    """Cria (se necessario) a pasta do titulo sob downloads/."""
    folder = DOWNLOADS_DIR / sanitize(title)
    folder.mkdir(parents=True, exist_ok=True)
    return folder
