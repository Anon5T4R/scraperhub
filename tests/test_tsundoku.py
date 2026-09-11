"""Testes das funcoes puras de parsing do scraper Tsundoku."""
from app.scrapers.tsundoku import (
    chapter_label,
    chapter_number,
    is_chapter_link,
    order_ascending,
)


def test_chapter_number_com_vol():
    assert chapter_number("/o-cacador-imortal-de-classe-sss-vol-13-cap-315-sou-um-fa-2/") == 315


def test_chapter_number_sem_vol():
    assert chapter_number("/o-cacador-imortal-de-classe-sss-cap-25-os-escolhidos-1/") == 25


def test_chapter_number_sem_cap():
    assert chapter_number("/manga/o-cacador-imortal-de-classe-sss/") is None
    assert chapter_number("") is None


def test_chapter_number_duplo_digito():
    assert chapter_number("/serie-cap-02-mas-voce-vai-morrer-1/") == 2


def test_chapter_label():
    assert chapter_label(315) == "Cap. 315"
    assert chapter_label(2) == "Cap. 2"


def test_is_chapter_link_mesmo_host():
    assert is_chapter_link(
        "https://tsundoku.com.br/o-cacador-imortal-de-classe-sss-vol-13-cap-315-sou-um-fa-2/",
        "tsundoku.com.br",
    )


def test_is_chapter_link_sem_vol():
    assert is_chapter_link(
        "https://tsundoku.com.br/o-cacador-imortal-de-classe-sss-cap-25-os-escolhidos-1/",
        "tsundoku.com.br",
    )


def test_is_chapter_link_host_diferente():
    assert not is_chapter_link(
        "https://outro.com.br/o-cacador-imortal-de-classe-sss-cap-25/",
        "tsundoku.com.br",
    )


def test_is_chapter_link_path_multisegmento():
    assert not is_chapter_link(
        "https://tsundoku.com.br/manga/o-cacador-imortal-de-classe-sss/",
        "tsundoku.com.br",
    )


def test_is_chapter_link_sem_cap():
    assert not is_chapter_link(
        "https://tsundoku.com.br/outra-pagina/",
        "tsundoku.com.br",
    )


def test_order_ascending():
    items = [
        {"id": "https://tsundoku.com.br/serie-cap-315-x/", "label": "Cap. 315"},
        {"id": "https://tsundoku.com.br/serie-cap-2-x/", "label": "Cap. 2"},
        {"id": "https://tsundoku.com.br/serie-cap-25-x/", "label": "Cap. 25"},
    ]
    assert [i["label"] for i in order_ascending(items)] == ["Cap. 2", "Cap. 25", "Cap. 315"]


def test_order_ascending_vazio():
    assert order_ascending([]) == []