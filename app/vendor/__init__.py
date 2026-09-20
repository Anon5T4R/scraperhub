"""Patches de compatibilidade aplicados em runtime (sem tocar no .venv).

Os arquivos vendidos aqui substituem componentes internos de bibliotecas de
terceiro: assim um upgrade da dependencia (pip install -U ...) nao perde o
patch, que deixa de viver dentro do .venv.
"""
from __future__ import annotations


def apply_ytdlp_patches() -> bool:
    """Instala em runtime o extractor do Blogger vendido (PR yt-dlp#17129).

    O extractor do Blogger esta quebrado upstream (o Google trocou a pagina
    video.g; issue yt-dlp#16044). O yt-dlp carrega extractors por lazy loading:
    a classe real so e importada do modulo na primeira instanciacao, entao
    trocar a classe no modulo original ANTES disso basta. Tambem atualizamos o
    registry (`yt_dlp.globals.extractors`) e o `_CLASS_LOOKUP` para cobrir o
    modo sem lazy loading e eventuais referencias ja montadas.

    Retorna True quando o BloggerIE foi efetivamente substituido.
    """
    from yt_dlp.extractor import blogger as blogger_module

    from .yt_dlp_blogger import BloggerIE as VendoredBloggerIE

    # 1) substitui a classe no modulo original: o lazy loading resolve por nome
    blogger_module.BloggerIE = VendoredBloggerIE

    # 2) garante o registry populado antes de mexer nele (importar apenas o
    #    submodulo blogger nao dispara a montagem da lista de extractors)
    from yt_dlp.extractor import import_extractors

    import_extractors()

    from yt_dlp.extractor import extractors as extractors_module
    from yt_dlp.globals import extractors as extractors_context

    registries = (
        extractors_context.value,
        getattr(extractors_module, '_CLASS_LOOKUP', None),
    )
    patched = False
    for registry in registries:
        if not isinstance(registry, dict) or 'BloggerIE' not in registry:
            continue
        entry = registry['BloggerIE']
        if getattr(entry, '_module', None) == 'yt_dlp.extractor.blogger':
            # classe lazy do yt-dlp: fixa a versao vendida (sobrescreve cache)
            setattr(entry, '_real_class', VendoredBloggerIE)
        else:
            registry['BloggerIE'] = VendoredBloggerIE
        patched = True
    return patched
