"""Testes do host animexnovel.com no scraper de animes."""
from app.scrapers.animestream import ANIMEXNOVEL_EP_RE, drive_url


def test_ep_re_casa_url_episodio():
    assert ANIMEXNOVEL_EP_RE.search(
        "https://www.animexnovel.com/anime/princession-orchestra/episodio-45/"
    ).group(1) == "45"


def test_ep_re_casa_episodio_um_digito():
    assert ANIMEXNOVEL_EP_RE.search(
        "https://www.animexnovel.com/anime/princession-orchestra/episodio-2/"
    ).group(1) == "2"


def test_ep_re_nao_casa_pagina_serie():
    assert ANIMEXNOVEL_EP_RE.search(
        "https://www.animexnovel.com/anime/princession-orchestra/"
    ) is None


def test_ep_re_nao_casa_sem_episodio():
    assert ANIMEXNOVEL_EP_RE.search(
        "https://www.animexnovel.com/anime/princession-orchestra/episodio/"
    ) is None


def test_drive_url_preview():
    assert drive_url(
        "https://drive.google.com/file/d/1F0WIHMRf4DM4IcemFCB7ynH5GBwqOJ4-/preview"
    ) == "https://drive.google.com/uc?id=1F0WIHMRf4DM4IcemFCB7ynH5GBwqOJ4-"


def test_drive_url_uc():
    assert drive_url(
        "https://drive.google.com/uc?id=1F0WIHMRf4DM4IcemFCB7ynH5GBwqOJ4-&export=download"
    ) == "https://drive.google.com/uc?id=1F0WIHMRf4DM4IcemFCB7ynH5GBwqOJ4-"


def test_drive_url_sem_id():
    assert drive_url("https://drive.google.com/file/d/") is None
    assert drive_url("") is None
