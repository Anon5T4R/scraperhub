# ScraperHub

Ferramenta pessoal de estudo (NAO comercial). Interface web local onde voce cola
um link e o scraper certo e detectado automaticamente.

## Como rodar

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
python -m uvicorn app.main:app --port 8765
```

Abra http://localhost:8765 no navegador.

Se `uv` estiver disponivel, o venv pode ser criado com `uv venv` e as
dependencias instaladas com `uv pip install -r requirements.txt`.
Depois do `pip install`, rode `python -m playwright install chromium` para
baixar o navegador usado pelo scraper de manga.

## Scrapers

- **MangaFire** (`mangafire`): sites com front no estilo mangafire.to,
  incluindo clones. O site e uma SPA renderizada por JS atras de Cloudflare,
  entao o scraper usa um Chromium headless (Playwright) em vez de HTTP puro.
  Aceita qualquer host que contenha "mangafire" e tambem URLs no formato
  `*/title/{slug}` ou `*/title/{slug}/chapter/{id}` quando nenhum outro scraper
  reconhece o host. A primeira carga de uma pagina demora ~10s (renderizacao).
- **Video** (`video`): fallback generico para qualquer URL http(s), usando
  `yt-dlp` como backend. Instale com `pip install yt-dlp` (fora do venv ou no
  PATH) e reinicie o servidor.

## Avisos

- **DRM**: videos protegidos por DRM (Widevine/criptografia) nao sao
  suportados por enquanto; o download falha com uma mensagem amigavel e o
  suporte esta pendente de autorizacao.
- Downloads de manga sao salvos em `downloads/` (pasta ignorada pelo git).
- Uso pessoal/estudo apenas: respeite os termos de uso e os direitos autorais
  dos sites acessados.