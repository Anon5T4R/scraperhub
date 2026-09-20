"""Scraper de video generico usando yt-dlp (API Python embutida no exe)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError
from .deps import ensure_ffmpeg
from .animestream_net import SilentLogger

# Patch de compatibilidade do extractor do Blogger (PR yt-dlp#17129) aplicado em
# runtime. E opcional: se o yt-dlp mudar internamente o patch falha e o app
# segue (o download cai no erro amigavel de sempre).
try:
    from ..vendor import apply_ytdlp_patches

    apply_ytdlp_patches()
except Exception as exc:  # nao derruba o app por causa de patch opcional
    logging.getLogger(__name__).warning("Patch do yt-dlp (Blogger) nao aplicado: %s", exc)

DRM_HINTS = ("drm", "protected", "widevine", "encrypted", "clearkey")
MAX_PLAYLIST = 50
OUTPUT_TEMPLATE = "%(title)s.%(ext)s"
FORMAT_MERGED = "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"
FORMAT_SINGLE = "b"


def _friendly(text: str) -> str:
    low = (text or "").lower()
    if any(hint in low for hint in DRM_HINTS):
        return (
            "Este video e protegido por DRM (Widevine/criptografia). "
            "O ScraperHub nao realiza download de conteudo com DRM."
        )
    cleaned = (text or "erro desconhecido").strip().replace("\n", " ")
    return f"yt-dlp falhou: {cleaned[-300:]}"


class VideoScraper(Scraper):
    """Baixa videos/playlists via yt-dlp; fallback para qualquer URL http."""

    id = "video"
    label = "Video (yt-dlp)"
    kind = "video"

    def match(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    # -- interface -----------------------------------------------------

    def get_info(self, url: str) -> dict:
        import yt_dlp

        options = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist", "logger": SilentLogger()}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                data = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            raise ScraperError(_friendly(str(exc))) from exc
        except Exception as exc:  # rede, extrator quebrado etc.
            raise ScraperError(f"Falha ao analisar o video: {exc}") from exc
        if not data:
            raise ScraperError("Nao foi possivel extrair informacoes deste video.")
        return self._metadata(data)

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        import yt_dlp

        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        progress_cb(0, "Verificando ffmpeg (primeira vez baixa automaticamente)...")
        ffmpeg = ensure_ffmpeg()
        yt_options: dict[str, Any] = {
            "outtmpl": str(DOWNLOADS_DIR / OUTPUT_TEMPLATE),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": SilentLogger(),
            "progress_hooks": [self._hook(progress_cb)],
        }
        if ffmpeg:
            # com ffmpeg: melhores faixas separadas mescladas em mp4
            yt_options["format"] = FORMAT_MERGED
            yt_options["merge_output_format"] = "mp4"
            yt_options["ffmpeg_location"] = str(Path(ffmpeg).parent)
        else:
            # sem ffmpeg: melhor arquivo unico (pode ter qualidade menor)
            yt_options["format"] = FORMAT_SINGLE
            progress_cb(0, "ffmpeg indisponivel: baixando arquivo unico (qualidade reduzida)")
        if item_ids:
            yt_options["playlist_items"] = ",".join(item_ids)

        try:
            with yt_dlp.YoutubeDL(yt_options) as ydl:
                ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            raise ScraperError(_friendly(str(exc))) from exc
        progress_cb(100, "Download concluido")

    # -- helpers -------------------------------------------------------

    @staticmethod
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

    @staticmethod
    def _metadata(data: dict[str, Any]) -> dict:
        if data.get("_type") == "playlist":
            entries = [entry for entry in (data.get("entries") or []) if entry][:MAX_PLAYLIST]
            items = [
                {"id": str(index), "label": entry.get("title") or entry.get("id") or f"Item {index}"}
                for index, entry in enumerate(entries, start=1)
            ]
            cover = None
            if entries:
                thumbs = entries[0].get("thumbnails") or []
                cover = thumbs[-1].get("url") if thumbs else entries[0].get("thumbnail")
            return {
                "title": data.get("title") or "Playlist",
                "cover": cover,
                "items": items,
                "duration": None,
                "is_playlist": True,
            }
        title = data.get("title") or "Video"
        return {
            "title": title,
            "cover": data.get("thumbnail"),
            "items": [{"id": "1", "label": title}],
            "duration": data.get("duration"),
            "is_playlist": False,
        }
