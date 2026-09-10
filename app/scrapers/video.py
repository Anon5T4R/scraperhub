"""Scraper de video generico usando yt-dlp como backend."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections import deque
from typing import Any

from .base import DOWNLOADS_DIR, ProgressCb, Scraper, ScraperError

PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")
DRM_HINTS = ("drm", "protected", "widevine", "encrypted")
MAX_PLAYLIST = 50
OUTPUT_TEMPLATE = "%(title)s.%(ext)s"


class VideoScraper(Scraper):
    """Baixa videos/playlists via yt-dlp; fallback para qualquer URL http."""

    id = "video"
    label = "Video (yt-dlp)"
    kind = "video"

    def match(self, url: str) -> bool:
        return url.startswith(("http://", "https://"))

    def get_info(self, url: str) -> dict:
        ytdlp = self._require_ytdlp()
        command = [ytdlp, "-J", "--flat-playlist", "--no-warnings", url]
        proc = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
        if proc.returncode != 0:
            raise ScraperError(self._friendly(proc.stderr or proc.stdout))
        try:
            data = json.loads(proc.stdout)
        except ValueError as exc:
            raise ScraperError("yt-dlp retornou um JSON invalido.") from exc
        return self._metadata(data)

    def download(
        self,
        url: str,
        item_ids: list[str],
        progress_cb: ProgressCb,
        options: dict | None = None,
    ) -> None:
        ytdlp = self._require_ytdlp()
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        command = [
            ytdlp,
            "-o",
            str(DOWNLOADS_DIR / OUTPUT_TEMPLATE),
            "--merge-output-format",
            "mp4",
            "--newline",
            "--no-warnings",
        ]
        if item_ids:
            command += ["--playlist-items", ",".join(item_ids)]
        command.append(url)
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        tail: deque[str] = deque(maxlen=20)
        last = 0
        if proc.stdout is not None:
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                tail.append(line)
                match = PROGRESS_RE.search(line)
                if match:
                    percent = int(float(match.group(1)))
                    if percent != last:
                        last = percent
                        progress_cb(percent, f"Baixando... {percent}%")
                else:
                    progress_cb(last, line[:200])
        proc.wait()
        if proc.returncode != 0:
            raise ScraperError(self._friendly("\n".join(tail)))
        progress_cb(100, "Download concluido")

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

    @staticmethod
    def _require_ytdlp() -> str:
        path = shutil.which("yt-dlp")
        if not path:
            raise ScraperError(
                "yt-dlp nao encontrado. Instale com 'pip install yt-dlp' e reinicie o servidor."
            )
        return path

    @staticmethod
    def _friendly(text: str) -> str:
        low = (text or "").lower()
        if any(hint in low for hint in DRM_HINTS):
            return (
                "Este video parece ser protegido por DRM (Widevine/criptografia). "
                "DRM nao e suportado por enquanto e esta pendente de autorizacao."
            )
        cleaned = (text or "erro desconhecido").strip()
        return f"yt-dlp falhou: {cleaned[-300:]}"
