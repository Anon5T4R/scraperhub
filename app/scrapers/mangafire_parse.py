"""Funcoes puras de parsing e nomes para o scraper MangaFire."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from urllib.parse import urlparse

TITLE_PATH_RE = re.compile(r"^/title/([^/?#]+)/?$", re.IGNORECASE)
CHAPTER_PATH_RE = re.compile(r"^/title/([^/?#]+)/chapter/([^/?#]+)", re.IGNORECASE)
VOLUME_PATH_RE = re.compile(r"^/title/([^/?#]+)/volume/([^/?#]+)", re.IGNORECASE)
CHAPTER_HREF_RE = re.compile(r"/chapter/([^/?#]+)", re.IGNORECASE)
VOLUME_HREF_RE = re.compile(r"/volume/([^/?#]+)", re.IGNORECASE)
INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')
SPACES_RE = re.compile(r"\s+")
ABBREV_RE = re.compile(r"\.\s+")
NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)")


def sanitize(name: str) -> str:
    """Remove caracteres invalidos para nomes de arquivo/pasta."""
    clean = INVALID_CHARS_RE.sub("_", name).strip().strip(".")
    return clean or "sem-nome"


def chapter_slug(label: str) -> str:
    """Gera o identificador de pasta do capitulo, ex: 'Ch. 270.1' -> 'Ch_270.1'."""
    clean = ABBREV_RE.sub("_", sanitize(label))
    clean = SPACES_RE.sub("_", clean).strip("_")
    return clean or "capitulo"


def numbered_folder(label: str) -> str:
    """Monta o nome da pasta pelo NUMERO real do capitulo/volume.

    O indice dentro da selecao muda entre rodadas (a mesma rodada gerou
    '001_Ch_0' e '001_Ch_166' para capitulos diferentes); o numero do capitulo
    e estavel. A parte inteira ganha zero-padding de 4 digitos e o slug do
    rotulo e mantido, ex: 'Ch. 255 — x [en]' -> '0255_Ch_255_—_x_[en]'.
    Sem numero no rotulo, cai para o slug puro.
    """
    slug = chapter_slug(label)
    number = chapter_number(label)
    if number is None:
        return slug
    texto = f"{number:.6f}".rstrip("0").rstrip(".")
    inteiro, _, decimal = texto.partition(".")
    prefixo = inteiro.zfill(4) + (f".{decimal}" if decimal else "")
    return f"{prefixo}_{slug}"


def image_extension(url: str, data: bytes) -> str:
    """Descobre a extensao pela URL ou pelos bytes (sniff PNG/JPEG/WebP)."""
    path = url.lower().split("?")[0]
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".jpg"


def parse_title_url(url: str) -> str:
    """Normaliza uma URL de titulo, capitulo ou volume para a URL do titulo."""
    parsed = urlparse(url)
    path = parsed.path or ""
    match = CHAPTER_PATH_RE.match(path) or VOLUME_PATH_RE.match(path)
    if match:
        path = f"/title/{match.group(1)}"
    base = f"{parsed.scheme}://{parsed.netloc}"
    return base + path.rstrip("/")


def parse_chapter_id(href: str) -> str | None:
    """Extrai o id do capitulo de um href '/title/{slug}/chapter/{id}'."""
    match = CHAPTER_HREF_RE.search(href or "")
    return match.group(1) if match else None


def parse_volume_id(href: str) -> str | None:
    """Extrai o id do volume de um href '/title/{slug}/volume/{id}'."""
    match = VOLUME_HREF_RE.search(href or "")
    return match.group(1) if match else None


def chapter_label(number: str, subtitle: str) -> str:
    """Monta o rotulo do capitulo: 'Ch. 270.1 — subtitulo'."""
    number = (number or "").strip()
    subtitle = (subtitle or "").strip()
    if number and subtitle:
        return f"{number} — {subtitle}"
    return number or subtitle or "Capitulo"


def chapter_number(text: str) -> float | None:
    """Extrai o numero do capitulo de um texto como 'Ch. 270.1'."""
    match = NUMBER_RE.search(text or "")
    return float(match.group(1)) if match else None


def order_items(items: list[dict]) -> list[dict]:
    """Ordena do ultimo capitulo para o primeiro quando ha numeros."""
    numbers = [chapter_number(str(item.get("label", ""))) for item in items]
    if items and all(number is not None for number in numbers):
        return sorted(
            items,
            key=lambda item: chapter_number(str(item["label"])) or 0.0,
            reverse=True,
        )
    return list(items)


def select_ascending(items: list[dict], item_ids: list[str]) -> list[dict]:
    """Filtra os itens pedidos e devolve em ordem crescente de capitulo."""
    wanted = {str(item_id) for item_id in item_ids}
    chosen = [item for item in items if str(item.get("id")) in wanted]
    numbers = [chapter_number(str(item.get("label", ""))) for item in chosen]
    if chosen and all(number is not None for number in numbers):
        return sorted(chosen, key=lambda item: chapter_number(str(item["label"])) or 0.0)
    return list(reversed(chosen))


def make_cbz(folder: Path) -> None:
    """Zip a pasta do capitulo em um arquivo .cbz ao lado."""
    cbz_path = folder.parent / f"{folder.name}.cbz"
    with zipfile.ZipFile(cbz_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for image in sorted(folder.iterdir()):
            if image.is_file():
                archive.write(image, arcname=image.name)
