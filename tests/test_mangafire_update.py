"""Testes da decisao de skip do modo update (volumes conferidos na rede).

`skip_item` e pura: recebe as paginas em disco, a contagem registrada no
manifesto (so no modo update) e as paginas que o reader mostrou agora, e
decide se o item precisa ser re-baixado. Sem Playwright.
"""
from app.scrapers.mangafire import skip_item


def test_skip_item_disco_bate():
    # fluxo normal: o que esta em disco bate com o reader -> pula
    assert skip_item(on_disk=10, known_pages=None, collected=10) is True


def test_skip_item_manifesto_bate_pasta_apagada():
    # modo so-CBZ: pasta apagada (on_disk=0) e a contagem registrada bate
    # com o reader -> pula sem re-baixar as imagens
    assert skip_item(on_disk=0, known_pages=10, collected=10) is True


def test_skip_item_manifesto_bate_com_paginas_em_disco():
    # modo update em pasta com imagens: bate pelo manifesto e pelo disco
    assert skip_item(on_disk=10, known_pages=10, collected=10) is True


def test_skip_item_manifesto_divergente_rebaixa():
    # o reader agora mostra 12 paginas, o manifesto registrava 10 -> re-baixa
    assert skip_item(on_disk=0, known_pages=10, collected=12) is False


def test_skip_item_manifesto_divergente_menos_paginas():
    # o site removeu paginas (menos que o registrado) -> re-baixa do zero
    assert skip_item(on_disk=0, known_pages=10, collected=8) is False


def test_skip_item_sem_manifesto_rebaixa():
    # sem contagem registrada e sem paginas em disco -> re-baixa
    assert skip_item(on_disk=0, known_pages=None, collected=10) is False


def test_skip_item_disco_divergente_sem_manifesto():
    # biblioteca antiga sem manifesto e contagem diferente -> re-baixa
    assert skip_item(on_disk=5, known_pages=None, collected=10) is False
