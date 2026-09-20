"""Testes dos helpers puros do scraper de animes EN (enanime)."""
import base64

from app.scrapers.enanime import (
    ANIMEHEAVEN_EP_RE,
    ANIMEHEAVEN_GATE_RE,
    GOGOANIME_EP_RE,
    NINEANIME_EP_RE,
    animeheaven_key,
    mirror_vidmoly,
)


def test_gogoanime_ep_re_casa_episodio():
    match = GOGOANIME_EP_RE.match("https://www.gogoanime.is/one-piece-episode-1177")
    assert match is not None
    assert match.group(1) == "one-piece"
    assert match.group(2) == "1177"


def test_gogoanime_ep_re_nao_casa_pagina_serie():
    assert GOGOANIME_EP_RE.match("https://www.gogoanime.is/category/one-piece") is None


def test_gogoanime_ep_re_nao_casa_sem_numero():
    assert GOGOANIME_EP_RE.match("https://www.gogoanime.is/one-piece-episode/") is None


def test_nineanime_ep_re_casa_episodio():
    match = NINEANIME_EP_RE.match(
        "https://9anime.org.lv/that-time-i-got-reincarnated-as-a-slime-season-4-episode-22/"
    )
    assert match is not None
    assert match.group(1) == "that-time-i-got-reincarnated-as-a-slime-season-4"
    assert match.group(2) == "22"


def test_nineanime_ep_re_nao_casa_pagina_serie():
    assert NINEANIME_EP_RE.match(
        "https://9anime.org.lv/anime/that-time-i-got-reincarnated-as-a-slime-season-4/"
    ) is None


def test_animeheaven_gate_re_casa():
    match = ANIMEHEAVEN_GATE_RE.match(
        "https://animeheaven.me/gate.php?key=80e0cc3fe1c52e68e074a0e2b012903e"
    )
    assert match is not None
    assert match.group(1) == "80e0cc3fe1c52e68e074a0e2b012903e"


def test_animeheaven_gate_re_nao_casa_sem_key():
    assert ANIMEHEAVEN_GATE_RE.match("https://animeheaven.me/gate.php") is None


def test_animeheaven_key():
    assert (
        animeheaven_key("https://animeheaven.me/gate.php?key=80e0cc3fe1c52e68e074a0e2b012903e")
        == "80e0cc3fe1c52e68e074a0e2b012903e"
    )
    assert animeheaven_key("https://animeheaven.me/gate.php") is None


def test_animeheaven_ep_re_casa_onclick():
    match = ANIMEHEAVEN_EP_RE.search(
        'onclick=\'gatea("80e0cc3fe1c52e68e074a0e2b012903e")\''
    )
    assert match is not None
    assert match.group(1) == "80e0cc3fe1c52e68e074a0e2b012903e"


def test_animeheaven_ep_re_nao_casa_sem_gatea():
    assert ANIMEHEAVEN_EP_RE.search('onclick=\'outra("abc")\'') is None


def test_mirror_vidmoly_decodifica():
    iframe = '<iframe src="https://vidmoly.biz/embed-6sfu89mr8vfz.html" width="640" height="360"></iframe>'
    value = base64.b64encode(iframe.encode()).decode()
    assert mirror_vidmoly(value) == "https://vidmoly.biz/embed-6sfu89mr8vfz.html"


def test_mirror_vidmoly_ignora_outros_players():
    iframe = '<iframe src="https://megaplay.buzz/stream/s-2/3327/sub"></iframe>'
    value = base64.b64encode(iframe.encode()).decode()
    assert mirror_vidmoly(value) is None


def test_mirror_vidmoly_valor_invalido():
    assert mirror_vidmoly("") is None
    assert mirror_vidmoly("nao-base64!!!") is None
    assert mirror_vidmoly("abc") is None
