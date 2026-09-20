"""Descoberta de novas fontes de anime via busca web (DuckDuckGo HTML/Lite)."""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

import httpx
from bs4 import BeautifulSoup

from .scrapers.base import current_user_agent

DDG_URL = "https://html.duckduckgo.com/html/"
DDG_LITE_URL = "https://lite.duckduckgo.com/lite/"
GOOGLE_URL = "https://www.google.com/search"
# hosts que nunca sao fonte de episodio baixavel
BLOCKLIST = (
    "youtube.com", "youtu.be", "reddit.com", "myanimelist.net", "anilist.co",
    "facebook.com", "twitter.com", "x.com", "instagram.com", "wikipedia.org",
    "crunchyroll.com", "netflix.com", "primevideo.com", "disneyplus.com",
    "hbo.com", "max.com", "tiktok.com", "pinterest.com", "amazon.com",
    "google.com", "bing.com", "duckduckgo.com", "globo.com", "viz.com",
)
ANIME_PATH_RE = re.compile(r"^/anime/(?:a/)?[^/]+", re.IGNORECASE)
MAX_HOSTS = 6


def _search_results(term: str) -> list[str]:
    """URLs de resultado da busca do DuckDuckGo (HTML) com fallbacks em cascata.

    Cascata: DuckDuckGo HTML -> DuckDuckGo Lite -> Google (ultimo recurso).
    O lite e uma pagina de tabela sem JS/cookie wall, bem mais estavel que o
    Google (que responde consent wall/render por JS e pode nao trazer link).
    """
    try:
        with httpx.Client(
            headers={"User-Agent": current_user_agent()},
            follow_redirects=True,
            timeout=20,
        ) as client:
            response = client.get(
                DDG_URL,
                params={"q": f"{term} anime episodio online assistir"},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return _ddg_lite_results(term)
    soup = BeautifulSoup(response.text, "lxml")
    urls: list[str] = []
    for link in soup.select("a.result__a, a.result__url"):
        href = link.get("href") or ""
        # resultados vao como /l/?uddg=<url codificada>
        if "uddg=" in href:
            decoded = parse_qs(urlparse(href).query).get("uddg", [""])[0]
            if decoded:
                urls.append(decoded)
        elif href.startswith("http"):
            urls.append(href)
    return urls or _ddg_lite_results(term) or _google_results(term)


def _ddg_lite_results(term: str) -> list[str]:
    """URLs de resultado do DuckDuckGo Lite (fallback mais estavel que o Google).

    O lite devolve uma tabela simples: os resultados sao `a.result-link`
    (alguns como redirect /l/?uddg=) ou links `http` diretos na tabela.
    """
    try:
        with httpx.Client(
            headers={"User-Agent": current_user_agent()},
            follow_redirects=True,
            timeout=20,
        ) as client:
            response = client.get(
                DDG_LITE_URL,
                params={"q": f"{term} anime episodio online assistir"},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(response.text, "lxml")
    links = soup.select("a.result-link") or soup.select("a[href]")
    urls: list[str] = []
    for link in links:
        href = link.get("href") or ""
        # redirect do lite: /l/?uddg=<url codificada> (pode vir sem esquema)
        if "uddg=" in href:
            decoded = parse_qs(urlparse(href).query).get("uddg", [""])[0]
            if decoded:
                urls.append(decoded)
        elif href.startswith("http"):
            urls.append(href)
    return urls


def _google_results(term: str) -> list[str]:
    """URLs de resultado da busca do Google (fallback quando o DDG nao retorna nada)."""
    try:
        with httpx.Client(
            headers={"User-Agent": current_user_agent()},
            follow_redirects=True,
            timeout=20,
        ) as client:
            response = client.get(
                GOOGLE_URL,
                params={"q": f"{term} anime episodio online assistir", "num": 20},
            )
            response.raise_for_status()
    except httpx.HTTPError:
        return []
    soup = BeautifulSoup(response.text, "lxml")
    urls: list[str] = []
    for link in soup.select("a[href]"):
        href = link.get("href") or ""
        if "/url?q=" not in href:
            continue
        decoded = parse_qs(urlparse(href).query).get("q", [""])[0]
        if decoded.startswith("http"):
            urls.append(decoded)
    return urls


def _host_ok(url: str, conhecidos: set[str]) -> bool:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host or host in conhecidos:
        return False
    return not any(host == b or host.endswith("." + b) for b in BLOCKLIST)


def relevante(texto: str, term: str) -> bool:
    """Todos os tokens do termo (ou a juncao deles) aparecem no texto?"""
    tokens = [t for t in re.split(r"\W+", term.lower()) if len(t) >= 2]
    if not tokens:
        return True
    alvo = texto.lower()
    juntado = "".join(tokens)
    return all(t in alvo for t in tokens) or juntado in alvo.replace(" ", "").replace("-", "")


def discover_sites(term: str, conhecidos: list[str]) -> list[dict]:
    """Busca na web sites novos com o anime; valida busca ?s= antes de aceitar.

    Retorna [{site, url}] onde url e a pagina da serie encontrada.
    """
    conhecidos_set = {(urlparse(u).hostname or "").removeprefix("www.") for u in conhecidos}
    candidatos: list[str] = []
    for url in _search_results(term):
        if not _host_ok(url, conhecidos_set):
            continue
        parsed = urlparse(url)
        if not ANIME_PATH_RE.match(parsed.path or ""):
            continue  # so paginas de serie nos interessam
        host = (parsed.hostname or "").removeprefix("www.")
        entry = f"https://{host}{parsed.path}"
        if entry not in candidatos:
            candidatos.append(entry)
        if len(candidatos) >= MAX_HOSTS:
            break
    achados: list[dict] = []
    for entry in candidatos:
        host = urlparse(entry).hostname or ""
        try:
            with httpx.Client(
                headers={"User-Agent": current_user_agent()},
                follow_redirects=True,
                timeout=15,
            ) as client:
                response = client.get(entry)
                response.raise_for_status()
        except httpx.HTTPError:
            continue
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.select_one("h1")
        # rigor: h1 E url final precisam bater com o termo (alguns sites
        # quebrados mostram h1 de outro anime na pagina)
        h1_texto = title.get_text(" ", strip=True) if title else ""
        if not (relevante(h1_texto, term) and relevante(str(response.url), term)):
            continue
        achados.append({"site": host, "url": str(response.url)})
        if len(achados) >= 3:
            break
    return achados
