"""Testes do patch de runtime do extractor do Blogger do yt-dlp."""
from __future__ import annotations

from app.vendor import apply_ytdlp_patches

VENDED_MODULE = "app.vendor.yt_dlp_blogger"


def test_apply_ytdlp_patches_instala_extractor_vendido():
    assert apply_ytdlp_patches() is True

    import yt_dlp.extractor.blogger as blogger_module

    assert blogger_module.BloggerIE.__module__ == VENDED_MODULE


def test_registry_instancia_o_extractor_vendido():
    assert apply_ytdlp_patches() is True

    from yt_dlp.extractor import gen_extractor_classes

    classe = next(c for c in gen_extractor_classes() if c.__name__ == "BloggerIE")
    instancia = classe()

    assert type(instancia).__module__ == VENDED_MODULE
    assert hasattr(type(instancia), "_extract_rpc_data")


def test_apply_ytdlp_patches_e_idempotente():
    assert apply_ytdlp_patches() is True
    assert apply_ytdlp_patches() is True
