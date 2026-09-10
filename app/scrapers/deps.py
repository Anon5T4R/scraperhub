"""Dependencias compartilhadas entre scrapers (ex: ffmpeg embutido)."""
from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import httpx

from .base import app_root

FFMPEG_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-gpl.zip"
)


def _bundled_ffmpeg() -> Path:
    return app_root() / "ffmpeg.exe"


def _ffmpeg_path() -> str | None:
    """ffmpeg embutido ao lado do exe, ou do PATH, ou None."""
    bundled = _bundled_ffmpeg()
    if bundled.is_file():
        return str(bundled)
    return shutil.which("ffmpeg")


def ensure_ffmpeg() -> str | None:
    """Garante um ffmpeg; baixa o build oficial se nao existir."""
    path = _ffmpeg_path()
    if path:
        return path
    target = _bundled_ffmpeg()
    try:
        with httpx.Client(follow_redirects=True, timeout=600) as client:
            with client.stream("GET", FFMPEG_ZIP_URL) as response:
                response.raise_for_status()
                zip_path = target.with_suffix(".zip")
                with zip_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
        with zipfile.ZipFile(zip_path) as archive:
            member = next(m for m in archive.namelist() if m.endswith("/bin/ffmpeg.exe"))
            target.write_bytes(archive.read(member))
        zip_path.unlink(missing_ok=True)
        return str(target)
    except Exception:
        # sem rede/arquivo: segue sem ffmpeg (qualidade reduzida)
        return None