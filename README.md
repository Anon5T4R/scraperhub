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
- **Manga WordPress** (`wpmanga`): sites WordPress server-rendered cuja home
  lista capitulos como links `/manga/{slug}-chapter-N` (ex:
  w2.chainsmokercat.website). HTTP puro, rapido.
- **Video** (`video`): fallback generico para qualquer URL http(s), usando
  `yt-dlp` (API Python embutida no executavel). O `ffmpeg` e baixado
  automaticamente ao lado do exe na primeira vez que salvar um video
  (build oficial BtbN win64 gpl); sem ele, baixa o melhor arquivo unico.

## Executavel (um arquivo so)

```powershell
.venv\Scripts\pip install pyinstaller
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --name ScraperHub --add-data "web;web" run.py
```

Gera `dist\ScraperHub.exe` (autossuficiente: FastAPI + Playwright + yt-dlp).
Dois cliques: sobe o servidor em 127.0.0.1:8765 e abre o navegador sozinho.
Na primeira execucao instala o Chromium do Playwright em `pw-browsers\`
ao lado do exe, se necessario. IMPORTANTE: ao rebuildar, apague `build\` e
`dist\` antes (um exe travado por processo em execucao impede a
sobrescrita e voce testa um build velho sem perceber).

## Avisos

- **DRM**: videos protegidos por DRM (Widevine/criptografia) nao sao
  suportados; o download falha com mensagem amigavel. O ScraperHub nao
  implementa burlar DRM sob nenhuma circunstancia.
- Downloads de manga sao salvos em `downloads/` (pasta ignorada pelo git).
- Uso pessoal/estudo apenas: respeite os termos de uso e os direitos autorais
  dos sites acessados.