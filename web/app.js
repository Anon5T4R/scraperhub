const api = {
  async request(path, options) {
    const res = await fetch(path, options);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = new Error(data.detail || ("Erro " + res.status));
      err.status = res.status;
      throw err;
    }
    return data;
  },
  post(path, body) {
    return this.request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  get(path) {
    return this.request(path, {});
  },
};

const STATUS_LABEL = { pending: "Na fila", running: "Em andamento", done: "Concluida", error: "Erro", cancelled: "Cancelada" };
const $ = (id) => document.getElementById(id);

// ---- abas ------------------------------------------------------------------

const TABS = Array.from(document.querySelectorAll(".tab"));

function selectTab(tab) {
  for (const t of TABS) {
    const selected = t === tab;
    t.setAttribute("aria-selected", String(selected));
    t.tabIndex = selected ? 0 : -1;
    $(t.getAttribute("aria-controls")).hidden = !selected;
  }
  tab.focus();
}

for (const tab of TABS) tab.addEventListener("click", () => selectTab(tab));
document.querySelector(".tabs").addEventListener("keydown", (event) => {
  const index = TABS.indexOf(document.activeElement);
  if (index === -1) return;
  let next = -1;
  if (event.key === "ArrowRight") next = (index + 1) % TABS.length;
  else if (event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = TABS.length - 1;
  if (next !== -1) { event.preventDefault(); selectTab(TABS[next]); }
});

$("header-badge").addEventListener("click", () => selectTab($("tab-tasks")));

// ---- analise por aba --------------------------------------------------------

// popula os selects de force com a lista real de scrapers do backend;
// as opcoes estaticas do HTML ficam como fallback se a API falhar
async function loadScraperOptions() {
  try {
    const data = await api.get("/api/scrapers");
    for (const sel of document.querySelectorAll("select[id^='force-']")) {
      const auto = sel.querySelector("option");
      sel.replaceChildren(auto, ...data.scrapers.map((s) => new Option(s.label, s.id)));
    }
  } catch (err) { /* mantem as opcoes estaticas */ }
}

function el(tag, opts = {}, children = []) {
  const node = document.createElement(tag);
  if (opts.class) node.className = opts.class;
  if (opts.text !== undefined) node.textContent = opts.text;
  if (opts.attrs) for (const [key, value] of Object.entries(opts.attrs)) node.setAttribute(key, value);
  for (const child of children) node.appendChild(child);
  return node;
}

function setStatus(cfg, message) {
  // mensagem vai para o status da aba que originou a analise atual
  const target = (cfg && cfg.status) || $("status-manga");
  if (target) target.textContent = message;
}

function formatDuration(seconds) {
  if (!seconds) return "";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

const ANALYZERS = ["enanime", "manga", "video", "files"].map((name) => ({
  url: $(`url-${name}`),
  force: $(`force-${name}`),
  button: $(`analyze-${name}`),
  status: $(`status-${name}`),
  result: $(`result-${name}`),
  current: null, // { url, force, info, kind, scraperId }
}));

async function analyzeInto(cfg, autoTried = false) {
  const url = cfg.url.value.trim();
  const force = cfg.force.value || null;
  if (!url) { cfg.status.textContent = "Cole um link primeiro."; return; }
  cfg.status.textContent = "Analisando...";
  cfg.result.classList.add("hidden");
  cfg.result.replaceChildren();
  try {
    const info = await api.post("/api/info", { url, force });
    cfg.current = { url, force, info, kind: info.kind, scraperId: info.scraper_id };
    cfg.status.textContent = `Scraper detectado: ${info.label} (${info.kind})`;
    renderResult(cfg.result, info, info.kind, cfg);
    cfg.result.classList.remove("hidden");
  } catch (err) {
    cfg.current = null;
    cfg.status.textContent = "Erro: " + err.message;
    if (err.status === 409) {
      if (!autoTried && (ipSwitch.config || {}).auto && ipSwitchReady()) {
        setStatus(cfg, "Bloqueio detectado — trocando de IP automaticamente...");
        await switchIpAndRetry(cfg, url, force, null);
      } else {
        renderChallenge(cfg, url, force, err.message);
      }
    }
  }
}

function renderChallenge(cfg, url, force, message) {
  // painel do modo assistido: abre o navegador para o usuario resolver
  cfg.result.replaceChildren();
  const wrap = el("div");
  wrap.appendChild(el("p", { class: "error", text: message }));
  wrap.appendChild(el("p", {
    class: "muted",
    text: "Clique abaixo: o ScraperHub abre o navegador, voce resolve a verificacao e ele continua sozinho.",
  }));
  const controls = el("div", { class: "controls" });
  const button = el("button", { text: "Resolver verificacao (abrir navegador)" });
  button.addEventListener("click", () => solveChallenge(cfg, url, force, button));
  if (ipSwitchReady()) {
    const ipBtn = el("button", { class: "ghost", text: "Trocar de IP e tentar de novo" });
    ipBtn.addEventListener("click", () => switchIpAndRetry(cfg, url, force, ipBtn));
    controls.appendChild(ipBtn);
  }
  controls.appendChild(button);
  wrap.appendChild(controls);
  cfg.result.appendChild(wrap);
  cfg.result.classList.remove("hidden");
}

async function solveChallenge(cfg, url, force, button) {
  button.disabled = true;
  button.textContent = "Abrindo o navegador...";
  setStatus(cfg, "Resolva a verificacao na janela que abriu.");
  let taskId;
  try {
    const res = await api.post("/api/solve_challenge", { url, force });
    taskId = res.task_id;
  } catch (err) {
    setStatus(cfg, "Erro: " + err.message);
    button.disabled = false;
    button.textContent = "Resolver verificacao (abrir navegador)";
    return;
  }
  await pollTasks();
  try {
    await waitTask(taskId);
  } catch (err) {
    setStatus(cfg, "Erro: " + err.message);
    button.disabled = false;
    button.textContent = "Tentar de novo";
    return;
  }
  setStatus(cfg, "Verificacao resolvida. Reanalisando...");
  await analyzeInto(cfg);
}

async function waitTask(taskId, timeoutMs = 360000) {
  // espera a tarefa terminar; o backend tem timeout proprio de 5 min
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 1500));
    const task = await api.get(`/api/tasks/${taskId}`);
    if (task.status === "done") return;
    if (task.status === "error") throw new Error(task.error || "Falha ao resolver a verificacao.");
    if (task.status === "cancelled") throw new Error("Verificacao cancelada.");
  }
  throw new Error("Tempo esgotado esperando a verificacao.");
}

for (const cfg of ANALYZERS) {
  cfg.button.addEventListener("click", () => analyzeInto(cfg));
  cfg.url.addEventListener("keydown", (event) => { if (event.key === "Enter") analyzeInto(cfg); });
}

function renderResult(container, info, kind, cfg) {
  container.replaceChildren();
  const head = el("div", { class: "result-head" });
  if (info.cover) head.appendChild(el("img", { class: "cover", attrs: { src: info.cover, alt: "" } }));
  const meta = el("div", { class: "result-meta" });
  meta.appendChild(el("h2", { text: info.title || "Sem titulo" }));
  meta.appendChild(el("p", { class: "muted", text: `${(info.items || []).length} item(ns) disponivel(is)` }));
  if (info.duration) meta.appendChild(el("p", { class: "muted", text: "Duracao: " + formatDuration(info.duration) }));
  head.appendChild(meta);
  container.appendChild(head);
  if (kind === "manga") container.appendChild(renderManga(info, cfg));
  else if (kind === "video") container.appendChild(renderVideo(info, cfg));
  else container.appendChild(renderGeneric(info, kind, cfg));
}

function renderGeneric(info, kind, cfg) {
  const labels = {
    image: "Baixar galeria",
    ebook: "Baixar e-book",
    file: "Baixar arquivo",
    site: "Espelhar site",
  };
  const wrap = el("div", { class: "controls" });
  const button = el("button", { text: labels[kind] || "Baixar" });
  button.addEventListener("click", () => {
    startDownload(cfg, (info.items || []).map((item) => item.id), {});
  });
  wrap.appendChild(button);
  return wrap;
}

function renderManga(info, cfg) {
  return renderSelectableList(info, [
    { id: "cbz", label: "Empacotar em CBZ" },
    { id: "cbz_only", label: "Só o CBZ (apaga as imagens avulsas)" },
    { id: "update", label: "Atualizar volumes (conferir paginas novas)" },
  ], "capitulo", cfg, info.volumes);
}

// Lista com checkboxes + selecao em massa (manga, episodios etc.)
// quando info.volumes vier preenchido, mostra o toggle Capitulos | Volumes
function renderSelectableList(info, options, unit, cfg, volumes) {
  const wrap = el("div");
  const filter = el("input", { attrs: { type: "text", placeholder: "Filtrar..." } });
  filter.style.marginBottom = "8px";

  const rangeInput = el("input", { attrs: { type: "text", placeholder: "ex: 108-255", style: "max-width:180px" } });
  const rangeBtn = el("button", { class: "ghost", text: "Selecionar faixa" });
  const allBtn = el("button", { class: "ghost", text: "Todos" });
  const noneBtn = el("button", { class: "ghost", text: "Nenhum" });
  const invertBtn = el("button", { class: "ghost", text: "Inverter" });
  const rangeWrap = el("div", { class: "controls" });
  rangeWrap.append(el("span", { class: "muted", text: "Faixa:" }), rangeInput, rangeBtn, allBtn, noneBtn, invertBtn);

  const controls = el("div", { class: "controls" });
  const optionBoxes = options.map((opt) => {
    const label = el("label", { class: "check" });
    const box = el("input", { attrs: { type: "checkbox" } });
    label.append(box, el("span", { text: opt.label }));
    return { id: opt.id, box };
  });
  const button = el("button", { text: "Baixar selecionados" });
  controls.append(...optionBoxes.map((o) => o.box.closest("label")), button);

  const list = el("div", { class: "chapters" });

  function makeEntry(item, isVolume) {
    const row = el("label", { class: "chapter" });
    const box = el("input", { attrs: { type: "checkbox", value: item.id } });
    const text = isVolume && item.count ? `${item.label} \u2014 ${item.count} capitulos` : item.label;
    row.append(box, el("span", { text }));
    return { box, label: text, row, flag: (item.flag || "").toLowerCase() };
  }

  const chapterEntries = (info.items || []).map((item) => makeEntry(item, false));
  const volumeEntries = (volumes || []).map((item) => makeEntry(item, true));

  let entries = chapterEntries;

  function paint() {
    list.replaceChildren(...entries.map((entry) => entry.row));
  }

  const visibleEntries = () => entries.filter((entry) => entry.row.style.display !== "none");
  const currentUnit = () => (entries === volumeEntries ? "volume" : unit);

  // Filtro por idioma (flag do item): une os idiomas de capitulos e volumes.
  const idiomas = Array.from(new Set(chapterEntries.concat(volumeEntries).map((entry) => entry.flag).filter(Boolean))).sort();
  const langSel = el("select", { attrs: { style: "max-width:140px" } });
  langSel.append(el("option", { attrs: { value: "" }, text: "Todos os idiomas" }));
  for (const idioma of idiomas) langSel.append(el("option", { attrs: { value: idioma }, text: idioma }));

  function applyFilters() {
    const q = filter.value.trim().toLowerCase();
    const lang = langSel.value;
    for (const entry of entries) {
      const okTexto = !q || entry.label.toLowerCase().includes(q);
      const okIdioma = !lang || entry.flag === lang;
      entry.row.style.display = okTexto && okIdioma ? "" : "none";
    }
  }

  const before = [filter];
  if (idiomas.length) {
    const langWrap = el("div", { class: "controls" });
    langWrap.append(el("span", { class: "muted", text: "Idioma:" }), langSel);
    before.push(langWrap);
  }
  before.push(rangeWrap);
  if (volumeEntries.length) {
    const chaptersBtn = el("button", { text: "Capitulos" });
    const volumesBtn = el("button", { class: "ghost", text: "Volumes" });
    const setMode = (next) => {
      entries = next;
      const chaptersActive = next === chapterEntries;
      chaptersBtn.className = chaptersActive ? "" : "ghost";
      volumesBtn.className = chaptersActive ? "ghost" : "";
      chaptersBtn.setAttribute("aria-pressed", String(chaptersActive));
      volumesBtn.setAttribute("aria-pressed", String(!chaptersActive));
      filter.value = "";
      applyFilters();
      paint();
    };
    chaptersBtn.setAttribute("aria-pressed", "true");
    volumesBtn.setAttribute("aria-pressed", "false");
    chaptersBtn.addEventListener("click", () => setMode(chapterEntries));
    volumesBtn.addEventListener("click", () => setMode(volumeEntries));
    const toggle = el("div", { class: "row", style: "margin-bottom:8px" });
    toggle.append(el("span", { class: "muted", text: "Exibir:" }), chaptersBtn, volumesBtn);
    before.push(toggle);
  }

  paint();

  allBtn.addEventListener("click", () => visibleEntries().forEach((entry) => { entry.box.checked = true; }));
  noneBtn.addEventListener("click", () => visibleEntries().forEach((entry) => { entry.box.checked = false; }));
  invertBtn.addEventListener("click", () => visibleEntries().forEach((entry) => { entry.box.checked = !entry.box.checked; }));

  filter.addEventListener("input", applyFilters);
  langSel.addEventListener("change", applyFilters);

  rangeBtn.addEventListener("click", () => {
    const ranges = parseRangeSpec(rangeInput.value);
    if (!ranges) { setStatus(cfg, "Faixa invalida. Use 108, 108-255 ou 108,200-210."); return; }
    let count = 0;
    for (const entry of visibleEntries()) {
      const n = labelNum(entry.label);
      if (n === null) continue;
      if (ranges.some(([lo, hi]) => n >= lo && n <= hi)) { entry.box.checked = true; count++; }
    }
    setStatus(cfg, count ? `${count} item(ns) selecionado(s) pela faixa.` : "Nenhum item na faixa informada.");
  });

  button.addEventListener("click", () => {
    const ids = entries.filter((entry) => entry.box.checked).map((entry) => entry.box.value);
    const unitNow = currentUnit();
    if (!ids.length) { setStatus(cfg, `Selecione ao menos um ${unitNow}.`); return; }
    if (!confirm(`Baixar ${ids.length} ${unitNow}(s)?`)) return;
    const opts = {};
    for (const { id, box } of optionBoxes) opts[id] = box.checked;
    startDownload(cfg, ids, opts);
  });

  wrap.append(...before, controls, list);
  return wrap;
}

function parseRangeSpec(text) {
  // aceita "108", "108-255" e "108,200-210"; null se invalido
  const parts = String(text).split(",").map((part) => part.trim()).filter(Boolean);
  if (!parts.length) return null;
  const ranges = [];
  for (const part of parts) {
    const range = part.match(/^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/);
    if (range) {
      const a = parseFloat(range[1]);
      const b = parseFloat(range[2]);
      ranges.push([Math.min(a, b), Math.max(a, b)]);
      continue;
    }
    const single = part.match(/^(\d+(?:\.\d+)?)$/);
    if (!single) return null;
    const value = parseFloat(single[1]);
    ranges.push([value, value]);
  }
  return ranges;
}

function labelNum(label) {
  const m = String(label).match(/\d+(?:\.\d+)?/);
  return m ? parseFloat(m[0]) : null;
}

function renderVideo(info, cfg) {
  const items = info.items || [];
  if (items.length > 1) {
    return renderSelectableList(info, [], info.is_playlist ? "item" : "episodio", cfg);
  }
  const wrap = el("div", { class: "controls" });
  const button = el("button", { text: "Baixar video" });
  button.addEventListener("click", () => {
    if (!confirm("Baixar este video?")) return;
    startDownload(cfg, items.map((item) => item.id), {});
  });
  wrap.appendChild(button);
  return wrap;
}

async function startDownload(cfg, items, options) {
  if (!cfg.current) return;
  try {
    const res = await api.post("/api/download", { url: cfg.current.url, items, options, force: cfg.current.force });
    setStatus(cfg, "Tarefa criada: " + res.task_id.slice(0, 8) + " (veja a aba Tarefas)");
    await pollTasks();
  } catch (err) {
    setStatus(cfg, "Erro: " + err.message);
  }
}

// ---- tarefas ----------------------------------------------------------------

function renderTasks(tasks) {
  const container = $("tasks");
  container.replaceChildren();
  if (!tasks.length) {
    container.appendChild(el("p", { class: "muted", text: "Nenhuma tarefa ainda." }));
    return;
  }
  tasks.slice().reverse().forEach((task) => container.appendChild(renderTask(task)));
}

function renderTask(task) {
  const card = el("div", { class: "task" + (task.error ? " has-error" : "") });
  if (task.error) {
    // banner de falha no TOPO: o que faltou e quais, facil de achar
    card.appendChild(el("div", { class: "task-error", text: task.error }));
  }
  const top = el("div", { class: "task-top" });
  top.append(
    el("span", { class: `badge ${task.status}`, text: STATUS_LABEL[task.status] || task.status }),
    el("span", { class: "muted", text: task.id.slice(0, 8) })
  );
  if (task.status === "running" || task.status === "pending") {
    const cancelBtn = el("button", { class: "ghost", text: "Cancelar" });
    cancelBtn.addEventListener("click", async () => {
      try {
        await api.post(`/api/tasks/${task.id}/cancel`, {});
        await pollTasks();
      } catch (err) { /* ignora */ }
    });
    top.appendChild(cancelBtn);
  } else if ((task.status === "error" || task.status === "cancelled") && task.retry) {
    if (task.error_challenge && task.retry.url) {
      const solveBtn = el("button", { text: "Resolver verificacao" });
      solveBtn.addEventListener("click", () => recoverTask(task, "solve", solveBtn));
      top.appendChild(solveBtn);
      if (ipSwitchReady()) {
        const ipBtn = el("button", { class: "ghost", text: "Trocar de IP e tentar de novo" });
        ipBtn.addEventListener("click", () => recoverTask(task, "ipswitch", ipBtn));
        top.appendChild(ipBtn);
      }
    }
    const retryBtn = el("button", { text: "Tentar de novo" });
    retryBtn.addEventListener("click", async () => {
      retryBtn.disabled = true;
      retryBtn.textContent = "Recriando...";
      try {
        await api.post(`/api/tasks/${task.id}/retry`, {});
        await pollTasks();
      } catch (err) {
        retryBtn.disabled = false;
        retryBtn.textContent = "Tentar de novo";
        alert("Erro ao repetir tarefa: " + err.message);
      }
    });
    top.appendChild(retryBtn);
  }
  const bar = el("div", { class: "bar" });
  const fill = el("div", { class: `fill ${task.status}` });
  fill.style.width = Math.max(0, Math.min(100, task.progress || 0)) + "%";
  bar.appendChild(fill);
  card.append(top, bar);
  if (task.current_item) card.appendChild(el("p", { class: "muted", text: task.current_item }));
  card.appendChild(el("pre", { class: "log", text: (task.log || []).join("\n") }));
  return card;
}

async function recoverTask(task, kind, button) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = kind === "solve" ? "Abrindo o navegador..." : "Trocando de IP...";
  let stepId;
  try {
    if (kind === "solve") {
      const res = await api.post("/api/solve_challenge", { url: task.retry.url, force: task.retry.force });
      stepId = res.task_id;
    } else {
      const res = await api.post("/api/ip_switch/run", {});
      stepId = res.task_id;
    }
  } catch (err) {
    alert("Erro: " + err.message);
    button.disabled = false;
    button.textContent = original;
    return;
  }
  await pollTasks();
  try {
    await waitTask(stepId);
  } catch (err) {
    alert("Erro: " + err.message);
    button.disabled = false;
    button.textContent = original;
    return;
  }
  try {
    await api.post(`/api/tasks/${task.id}/retry`, {});
  } catch (err) {
    alert("Erro ao repetir: " + err.message);
    button.disabled = false;
    button.textContent = original;
    return;
  }
  await pollTasks();
}

function updateHeaderBadge(tasks) {
  const active = tasks.filter((t) => t.status === "running" || t.status === "pending").length;
  const badge = $("header-badge");
  badge.hidden = active === 0;
  badge.textContent = active === 1 ? "1 download em andamento" : `${active} downloads em andamento`;
}

let hasActiveTasks = false;

async function pollTasks() {
  try {
    const tasks = await api.get("/api/tasks");
    hasActiveTasks = tasks.some((t) => t.status === "running" || t.status === "pending");
    renderTasks(tasks);
    updateHeaderBadge(tasks);
  } catch (err) {
    /* mantem a ultima lista em caso de falha temporaria */
  }
}

// ---- busca de anime -----------------------------------------------------------

function setSearchStatus(message) {
  $("search-status").textContent = message;
}

function setSitesStatus(message) {
  $("sites-status").textContent = message;
}

async function searchAnime() {
  const term = $("search").value.trim();
  const results = $("search-results");
  if (!term) { setSearchStatus("Digite um nome para buscar."); return; }
  setSearchStatus("Buscando...");
  results.classList.add("hidden");
  results.replaceChildren();
  $("assemble").classList.add("hidden");
  $("assemble-result").replaceChildren();
  setAssembleStatus("");
  try {
    const data = await api.post("/api/search", { term, idioma: $("search-lang").value || "qualquer" });
    renderSearchResults(data);
    const hosts = Object.keys(data.erros || {});
    const sufixo = hosts.length ? ` (falha: ${hosts.join(", ")})` : "";
    setSearchStatus(`${(data.resultados || []).length} resultado(s) encontrado(s)${sufixo}.`);
  } catch (err) {
    setSearchStatus("Erro: " + err.message);
  }
}

function renderSearchResults(data) {
  const container = $("search-results");
  container.replaceChildren();
  const items = data.resultados || [];
  if (!items.length) {
    container.appendChild(el("p", { class: "muted", text: "Nenhum resultado encontrado." }));
    container.classList.remove("hidden");
    return;
  }
  for (const item of items) container.appendChild(renderSearchItem(item));
  container.classList.remove("hidden");
  $("assemble").classList.toggle("hidden", !items.length);
}

function setAssembleStatus(message) {
  $("assemble-status").textContent = message;
}

async function assembleInfo() {
  const term = $("search").value.trim();
  const idioma = $("search-lang").value || "qualquer";
  if (!term) { setAssembleStatus("Digite um nome para buscar."); return; }
  setAssembleStatus("Analisando fontes... pode levar cerca de 1 minuto.");
  $("assemble-result").replaceChildren();
  try {
    const plan = await api.post("/api/assemble_info", { term, idioma });
    renderAssembly(plan, term, idioma, false);
    setAssembleStatus(`${(plan.fontes || []).length} fonte(s), ${(plan.episodios || []).length} episodio(s).`);
  } catch (err) {
    setAssembleStatus("Erro: " + err.message);
  }
}

async function assembleFullInfo() {
  const term = $("search").value.trim();
  const idioma = $("search-lang").value || "qualquer";
  if (!term) { setAssembleStatus("Digite um nome para buscar."); return; }
  setAssembleStatus("Analisando fontes... pode levar cerca de 1 minuto.");
  $("assemble-result").replaceChildren();
  try {
    const plan = await api.post("/api/assemble_full_info", { term, idioma });
    renderAssembly(plan, term, idioma, true);
    setAssembleStatus(`${(plan.fontes || []).length} fonte(s), ${(plan.episodios || []).length} episodio(s).`);
  } catch (err) {
    setAssembleStatus("Erro: " + err.message);
  }
}

function renderAssembly(plan, term, idioma, full = false) {
  const container = $("assemble-result");
  container.replaceChildren();
  const episodios = plan.episodios || [];
  if (!episodios.length) {
    container.appendChild(el("p", { class: "muted", text: "Nenhum episodio montado." }));
    return;
  }
  const table = el("table", { class: "assemble-table" });
  const head = el("tr");
  head.append(
    el("th", { text: "Ep" }),
    el("th", { text: "Fonte escolhida" }),
    el("th", { text: "Alternativas" })
  );
  table.appendChild(head);
  for (const ep of episodios) {
    const escolhido = ep.escolhido
      ? `${ep.escolhido.site} (${ep.escolhido.qualidade || "sem qualidade"})`
      : "sem fonte";
    const alternativas = (ep.alternativas || []).map((alt) => alt.site).join(", ") || "-";
    const row = el("tr");
    row.append(
      el("td", { text: ep.label }),
      el("td", { text: escolhido }),
      el("td", { text: alternativas })
    );
    table.appendChild(row);
  }
  container.appendChild(table);
  container.appendChild(renderAssemblySources(plan.fontes || []));
  const baixar = el("button", { text: full ? "Baixar anime completo" : "Baixar temporada montada" });
  baixar.addEventListener("click", () => startAssemblyDownload(plan, term, idioma, full));
  container.appendChild(baixar);
}

function renderAssemblySources(fontes) {
  const wrap = el("div", { class: "assemble-sources" });
  wrap.appendChild(el("div", { class: "muted", text: "Fontes" }));
  for (const fonte of fontes) {
    const partes = [`${fonte.site} · ${fonte.eps_total} eps · ${fonte.qualidade || "sem qualidade"}`];
    if (fonte.erro) partes.push(`erro: ${fonte.erro}`);
    wrap.appendChild(el("div", { class: fonte.erro ? "error" : "muted", text: partes.join(" · ") }));
  }
  return wrap;
}

async function startAssemblyDownload(plan, term, idioma, full = false) {
  const labels = (plan.episodios || []).map((ep) => ep.label);
  if (!labels.length) { setAssembleStatus("Nada para baixar."); return; }
  try {
    const res = await api.post(full ? "/api/assemble_full_download" : "/api/assemble_download", { term, idioma, wanted: labels, options: {} });
    setAssembleStatus("Tarefa criada: " + res.task_id.slice(0, 8) + " (veja a aba Tarefas)");
    await pollTasks();
  } catch (err) {
    setAssembleStatus("Erro: " + err.message);
  }
}

function renderSearchItem(item) {
  const row = el("div", { class: "search-item" });
  const info = el("div");
  info.appendChild(el("div", { class: "search-title", text: item.title || "Sem titulo" }));
  info.appendChild(el("div", { class: "muted", text: `${item.site} · ${item.idioma}` }));
  const actions = el("div", { class: "search-actions" });
  const use = el("button", { class: "ghost", text: "Usar" });
  use.addEventListener("click", () => {
    // anime vai para a aba Video (series sao kind=video na deteccao)
    $("url-video").value = item.url;
    selectTab($("tab-video"));
    analyzeInto(ANALYZERS.find((cfg) => cfg.url.id === "url-video"));
  });
  const verify = el("button", { class: "ghost", text: "Verificar qualidade" });
  const quality = el("span", { class: "muted" });
  verify.addEventListener("click", async () => {
    quality.textContent = "Verificando...";
    try {
      const res = await api.post("/api/search_verify", { url: item.url });
      quality.textContent = `${res.qualidade} · ${res.episodios} eps`;
    } catch (err) {
      quality.textContent = err.message;
    }
  });
  actions.append(use, verify, quality);
  row.append(info, actions);
  return row;
}

async function loadSites() {
  try {
    const data = await api.get("/api/sites");
    $("sites").value = (data.sites || []).join("\n");
  } catch (err) {
    setSitesStatus("Erro: " + err.message);
  }
}

async function saveSites() {
  const urls = $("sites").value.split("\n").map((line) => line.trim()).filter(Boolean);
  try {
    const data = await api.post("/api/sites", { sites: urls });
    $("sites").value = (data.sites || []).join("\n");
    setSitesStatus("Sites salvos.");
  } catch (err) {
    setSitesStatus("Erro: " + err.message);
  }
}

// ---- busca de manga -----------------------------------------------------------

function setMangaSearchStatus(message) {
  $("manga-search-status").textContent = message;
}

function setMangaSitesStatus(message) {
  $("manga-sites-status").textContent = message;
}

async function searchManga() {
  const term = $("manga-search").value.trim();
  const results = $("manga-search-results");
  if (!term) { setMangaSearchStatus("Digite um nome para buscar."); return; }
  setMangaSearchStatus("Buscando...");
  results.classList.add("hidden");
  results.replaceChildren();
  try {
    const data = await api.post("/api/manga_search", { term });
    renderMangaSearchResults(data);
    const hosts = Object.keys(data.erros || {});
    const sufixo = hosts.length ? ` (falha: ${hosts.join(", ")})` : "";
    setMangaSearchStatus(`${(data.resultados || []).length} resultado(s) encontrado(s)${sufixo}.`);
  } catch (err) {
    setMangaSearchStatus("Erro: " + err.message);
  }
}

function renderMangaSearchResults(data) {
  const container = $("manga-search-results");
  container.replaceChildren();
  const items = data.resultados || [];
  if (!items.length) {
    container.appendChild(el("p", { class: "muted", text: "Nenhum resultado encontrado." }));
    container.classList.remove("hidden");
    return;
  }
  for (const item of items) container.appendChild(renderMangaSearchItem(item));
  container.classList.remove("hidden");
}

function renderMangaSearchItem(item) {
  const row = el("div", { class: "search-item" });
  const info = el("div");
  info.appendChild(el("div", { class: "search-title", text: item.title || "Sem titulo" }));
  info.appendChild(el("div", { class: "muted", text: `${item.site} · ${item.idioma}` }));
  const actions = el("div", { class: "search-actions" });
  const use = el("button", { class: "ghost", text: "Usar" });
  use.addEventListener("click", () => {
    // a busca ja esta na aba Manga: preenche a URL e analisa direto
    $("url-manga").value = item.url;
    analyzeInto(ANALYZERS.find((cfg) => cfg.url.id === "url-manga"));
  });
  actions.appendChild(use);
  row.append(info, actions);
  return row;
}

async function loadMangaSites() {
  try {
    const data = await api.get("/api/manga_sites");
    $("manga-sites").value = (data.sites || []).join("\n");
  } catch (err) {
    setMangaSitesStatus("Erro: " + err.message);
  }
}

async function saveMangaSites() {
  const urls = $("manga-sites").value.split("\n").map((line) => line.trim()).filter(Boolean);
  try {
    const data = await api.post("/api/manga_sites", { sites: urls });
    $("manga-sites").value = (data.sites || []).join("\n");
    setMangaSitesStatus("Sites salvos.");
  } catch (err) {
    setMangaSitesStatus("Erro: " + err.message);
  }
}

// ---- meta (versao + pasta de downloads) ---------------------------------------

async function loadMeta() {
  try {
    const data = await api.get("/api/meta");
    const parts = [];
    if (data.version) parts.push("ScraperHub " + data.version);
    if (data.downloads_dir) parts.push("Salvando em: " + data.downloads_dir);
    if (!parts.length) return;
    const node = $("manga-meta");
    node.textContent = parts.join(" \u00b7 ");
    if (data.downloads_dir) node.title = data.downloads_dir;
    node.classList.remove("hidden");
  } catch (err) { /* silencioso */ }
}

// ---- troca de IP (fallback de bloqueio) ---------------------------------------

let ipSwitch = { config: null, available: null };

async function loadIpSwitch() {
  try {
    const data = await api.get("/api/ip_switch");
    ipSwitch = data;
    const cfg = data.config || {};
    $("ip-switch-provider").value = cfg.provider || "off";
    $("ip-switch-command").value = cfg.command || "";
    $("ip-switch-auto").checked = !!cfg.auto;
    const warpOpt = $("ip-switch-provider").querySelector("option[value='warp']");
    if (warpOpt && data.available && !data.available.warp) {
      warpOpt.disabled = true;
      warpOpt.textContent = "Cloudflare WARP (warp-cli nao encontrado)";
    }
  } catch (err) { /* silencioso */ }
}

async function saveIpSwitch() {
  const provider = $("ip-switch-provider").value;
  const command = $("ip-switch-command").value.trim();
  const auto = $("ip-switch-auto").checked;
  try {
    const data = await api.post("/api/ip_switch", { provider, command, auto });
    ipSwitch.config = data.config;
    $("ip-switch-status").textContent = "Config salva.";
  } catch (err) {
    $("ip-switch-status").textContent = "Erro: " + err.message;
  }
}

function ipSwitchReady() {
  const cfg = ipSwitch.config || {};
  if (!cfg.provider || cfg.provider === "off") return false;
  if (cfg.provider === "custom" && !(cfg.command || "").trim()) return false;
  if (cfg.provider === "warp" && ipSwitch.available && !ipSwitch.available.warp) return false;
  return true;
}

async function switchIpAndRetry(cfg, url, force, button) {
  if (button) { button.disabled = true; button.textContent = "Trocando de IP..."; }
  setStatus(cfg, "Trocando de IP... (veja a aba Tarefas)");
  let taskId;
  try {
    const res = await api.post("/api/ip_switch/run", {});
    taskId = res.task_id;
  } catch (err) {
    setStatus(cfg, "Erro: " + err.message);
    if (button) { button.disabled = false; button.textContent = "Trocar de IP e tentar de novo"; }
    return;
  }
  await pollTasks();
  try {
    await waitTask(taskId);
  } catch (err) {
    setStatus(cfg, "Erro: " + err.message);
    if (button) { button.disabled = false; button.textContent = "Trocar de IP e tentar de novo"; }
    return;
  }
  setStatus(cfg, "IP trocado. Reanalisando...");
  await analyzeInto(cfg, true);
}

$("search-btn").addEventListener("click", searchAnime);
$("search").addEventListener("keydown", (event) => { if (event.key === "Enter") searchAnime(); });
$("assemble-btn").addEventListener("click", assembleInfo);
$("assemble-full-btn").addEventListener("click", assembleFullInfo);
$("sites-save").addEventListener("click", saveSites);
$("manga-search-btn").addEventListener("click", searchManga);
$("manga-search").addEventListener("keydown", (event) => { if (event.key === "Enter") searchManga(); });
$("manga-sites-save").addEventListener("click", saveMangaSites);
$("ip-switch-save").addEventListener("click", saveIpSwitch);
$("refresh").addEventListener("click", pollTasks);
loadScraperOptions();
loadSites();
loadMangaSites();
loadIpSwitch();
loadMeta();
pollTasks();
// com tarefas ativas: 1,5s; sem tarefas: uma sondagem a cada ~15s (tick 10)
let pollTick = 0;
setInterval(() => { if (hasActiveTasks || pollTick % 10 === 0) pollTasks(); pollTick++; }, 1500);
