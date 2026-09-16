"""Testes do scraper de manga por pagina de serie (asurascans)."""
from app.scrapers import detect, get_scraper
from app.scrapers.seriesmanga import SERIES_PATH_RE, SeriesMangaScraper

SERIE = "https://asurascans.com/comics/surviving-the-game-as-a-barbarian-53fc8424"

SERIES_HTML = f"""
<html><body><main>
<h1>Surviving The Game as a Barbarian</h1>
<meta property="og:image" content="https://cdn.asurascans.com/capa.webp">
<img src="https://cdn.asurascans.com/asura-images/covers/capa.webp">
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/160">Cap 160</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/2">Cap 2</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/1">Cap 1</a>
<a href="/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/159.5">Cap 159.5</a>
<a href="/comics/outra-serie/chapter/3">outra serie</a>
<a href="https://asurascans.com/comics/surviving-the-game-as-a-barbarian-53fc8424/chapter/2">duplicado</a>
</main></body></html>
"""

CHAPTER_HTML = """
<html><body><main>
<img src="https://cdn.asurascans.com/asura-images/covers/capa.webp">
<img src="https://cdn.asurascans.com/asura-images/banners/banner.webp">
<img src="https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp">
<img data-src="https://cdn.asurascans.com/asura-images/chapters/serie/1/002.webp">
<img src="https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp">
</main></body></html>
"""


def test_match():
    scraper = SeriesMangaScraper()
    assert scraper.match(SERIE)
    assert scraper.match(SERIE + "/chapter/5")
    assert not scraper.match("https://mangahub.io/manga/onepunch-man")
    assert not scraper.match("https://google.com/comics/x")


def test_detect_registrado():
    scraper = detect(SERIE)
    assert scraper is not None and scraper.id == "seriesmanga"
    assert get_scraper("seriesmanga") is not None


def test_series_path_re():
    assert SERIES_PATH_RE.match("/comics/slug")
    assert not SERIES_PATH_RE.match("/comics/slug/chapter/1")
    assert not SERIES_PATH_RE.match("/manga/slug")


def test_series_url_normaliza_capitulo():
    assert (
        SeriesMangaScraper._series_url(SERIE + "/chapter/12")
        == SERIE
    )


def test_get_info_lista_e_ordena(monkeypatch):
    scraper = SeriesMangaScraper()

    class FakeResponse:
        text = SERIES_HTML
        status_code = 200
        url = SERIE

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def get(self, url: str, headers=None):
            return FakeResponse()

    monkeypatch.setattr("app.scrapers.seriesmanga.httpx.Client", FakeClient)
    info = scraper.get_info(SERIE)
    labels = [i["label"] for i in info["items"]]
    # mais novo primeiro, com decimal no lugar certo; duplicado e outra serie fora
    assert labels == ["Cap. 160", "Cap. 159.5", "Cap. 2", "Cap. 1"]
    assert info["title"] == "Surviving The Game as a Barbarian"
    assert info["cover"].endswith("capa.webp")


def test_chapter_images_filtra_capa_e_banner():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(CHAPTER_HTML, "lxml")
    urls = SeriesMangaScraper._chapter_images(soup, "/chapters/")
    assert urls == [
        "https://cdn.asurascans.com/asura-images/chapters/serie/1/001.webp",
        "https://cdn.asurascans.com/asura-images/chapters/serie/1/002.webp",
    ]


# ---- mangafire: challenge Turnstile + label com idioma ----------------------

def test_detecta_challenge_turnstile():
    from app.scrapers.mangafire import is_challenge_html

    # pagina real vista em bloqueio por taxa (Security check / Turnstile)
    assert is_challenge_html("<html><title>security check</title></html>".lower())
    assert is_challenge_html("verify you're human — click the shapes".lower())
    assert is_challenge_html("just a moment...")
    assert not is_challenge_html("<div>reader with img.reader-img pages</div>")


def test_detecta_challenge_pela_url_do_waf():
    from app.scrapers.mangafire import is_challenge_page

    # o Cloudflare redireciona a navegacao para /@waf/challenge
    url = "https://mangafire.to/@waf/challenge?return=%2Ftitle%2Fsurviving-the-game-as-a-barbarian"
    assert is_challenge_page(url, "")
    # challenge ja renderizado, mesmo sem o redirect na URL
    assert is_challenge_page("https://mangafire.to/title/x", "just a moment...")
    # pagina normal de titulo
    assert not is_challenge_page("https://mangafire.to/title/x", "<h1>Manga</h1>")


def test_items_label_inclui_idioma():
    from app.scrapers.mangafire import MangaFireScraper

    rows = [
        {"href": "/title/x/chapter/1", "num": "Ch. 49", "sub": "", "flag": "English"},
        {"href": "/title/x/chapter/2", "num": "Ch. 49", "sub": "", "flag": ""},
        {"href": "/title/x/chapter/1", "num": "Ch. 49", "sub": "", "flag": "English"},  # dup
    ]
    items = MangaFireScraper._items(rows)
    labels = [i["label"] for i in items]
    assert labels == ["Ch. 49 [English]", "Ch. 49"]


def test_match_aceita_volume():
    from app.scrapers.mangafire import MangaFireScraper

    scraper = MangaFireScraper()
    # host sem "mangafire": cai na regra de path
    assert scraper.match("https://clone.to/title/x/volume/78")
    assert scraper.match("https://clone.to/title/x/chapter/78")
    assert not scraper.match("https://clone.to/outro/path")


def test_volume_items_monta_label_contagem_e_id():
    from app.scrapers.mangafire import MangaFireScraper

    rows = [
        {"href": "/title/x/volume/78", "num": "Vol. 28", "sub": "28 chapters", "flag": "English"},
        {"href": "/title/x/volume/77", "num": "Vol. 27", "sub": "10 chapters", "flag": ""},
        {"href": "/title/x/volume/78", "num": "Vol. 28", "sub": "28 chapters", "flag": "English"},  # dup
        {"href": "/title/x/chapter/9", "num": "Ch. 9", "sub": "", "flag": ""},  # nao e volume
    ]
    items = MangaFireScraper._volume_items(rows)
    assert [i["id"] for i in items] == ["vol:78", "vol:77"]  # mais novo primeiro
    assert items[0]["label"] == "Vol. 28 [English]"
    assert items[0]["count"] == 28
    assert items[1]["label"] == "Vol. 27"
    assert items[1]["count"] == 10


def test_cooldown_reporta_e_dorme_em_passos(monkeypatch):
    import app.scrapers.mangafire as mf

    dormido: list[int] = []
    mensagens: list[str] = []
    monkeypatch.setattr(mf.time, "sleep", lambda s: dormido.append(s))
    mf.cooldown(lambda p, m: mensagens.append(m), 50, mf.CHAPTER_COOLDOWN_S)
    assert sum(dormido) == mf.CHAPTER_COOLDOWN_S
    assert all(s <= mf.COOLDOWN_STEP_S for s in dormido)
    assert len(mensagens) == len(dormido)  # reporta a cada passo (cancelavel)
    assert "esfriando" in mensagens[0]
