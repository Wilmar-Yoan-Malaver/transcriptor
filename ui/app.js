/* Transcriptor · lógica de la interfaz.
 *
 * Arquitectura (patrón "store único", estilo Flux):
 *   1. Todo el estado vive en `store`. Nada más guarda datos de la app.
 *   2. Los cambios pasan por store.set(...): acciones del usuario y eventos del motor.
 *   3. Cada pantalla tiene una función render* que lee el estado y actualiza su parte del DOM.
 *      Se suscribe solo a las claves que le importan y se vuelve a ejecutar cuando cambian.
 *
 * Habla con Python por window.pywebview.api y recibe los eventos del motor en window.onEngine.
 */
"use strict";

const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];

const G = {
  monitor: "", window: "", audio: "", doc: "", video: "", play: "",
  pause: "", check: "", warn: "", info: "", copy: "", folder: "",
  eye: "", refresh: "", share: "", close: "", more: "", trash: "",
};

const OPTIONS = {
  models: [["tiny", "tiny · el más rápido"], ["base", "base · rápido"], ["small", "small · equilibrado (recomendado)"],
           ["medium", "medium · más preciso, lento"], ["large-v3-turbo", "large-v3-turbo · el más preciso"]],
  liveModels: [["tiny", "tiny · mínimo retraso"], ["base", "base · equilibrado (recomendado)"], ["small", "small · más preciso, puede atrasarse"]],
  languages: [["", "Detectar automáticamente"], ["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"],
              ["fr", "Francés"], ["it", "Italiano"], ["de", "Alemán"]],
  qualities: [["1080p", "Alta · 1080p (recomendado)"], ["720p", "Media · 720p (archivos livianos)"], ["original", "Original · resolución completa"]],
  fps: [[15, "15"], [30, "30 (recomendado)"], [60, "60"]],
};

const EXCLUDE = ["Transcriptor", "Transcriptor · grabando"];
const PAGE_SIZE = 15;   // elementos por página del historial
const NAME_MAX = 20;    // caracteres visibles de un nombre de archivo (el completo va en el tooltip)

/** "Sesión N. 5 Conexión E…" — corta nombres largos; el completo se muestra al pasar el mouse. */
const shortName = (name) => (name.length > NAME_MAX ? name.slice(0, NAME_MAX).trimEnd() + "…" : name);

/** Pone el nombre corto en el elemento y el completo como tooltip. */
function setName(el, name) {
  el.textContent = shortName(name);
  el.title = name;
}
let api = null;

// =========================================================================== store

/** Store mínimo: estado inmutable por claves de primer nivel + suscripciones por clave. */
function createStore(initial) {
  let state = initial;
  const subs = [];
  return {
    get: () => state,
    /** patch: objeto o función (estado) => objeto con las claves de primer nivel que cambian. */
    set(patch) {
      const next = typeof patch === "function" ? patch(state) : patch;
      const changed = Object.keys(next).filter((k) => next[k] !== state[k]);
      if (!changed.length) return;
      state = { ...state, ...next };
      for (const { keys, fn } of subs) if (keys.some((k) => changed.includes(k))) fn(state);
    },
    subscribe(keys, fn) { subs.push({ keys, fn }); },
  };
}

const REC_IDLE = {
  state: "idle", paused: false, saving: false, elapsed: 0, levels: { mic: 0, sys: 0 },
  audio: { mic: false, sys: false }, live: false, liveStatus: "", segments: [], sourceLabel: "", path: null,
};
const DET_TX_IDLE = { phase: "idle", status: "", pct: null };

const store = createStore({
  view: "home",
  engine: { ready: false, status: "Iniciando motor…", error: false },
  config: {},
  devices: { speakers: [], mics: [] },
  monitors: [],
  source: null,
  rec: REC_IDLE,
  picker: { open: false, tab: "monitor", monitor: [], window: [], thumbs: {}, selected: null, loading: false },
  txBusy: false,
  tx: { mode: "file", job: null, running: false, showProgress: false, status: "", pct: null, lines: [],
        txt: null, srt: null },
  // Transcripción guardada abierta desde el Historial o la ficha (pantalla de solo lectura).
  viewer: { txt: null, srt: null, lines: [], back: null, backLabel: "Historial" },
  det: { path: null, justRecorded: false, info: null, infoError: null, created: null, txt: null, job: null,
         req: null, transcribeWhenLoaded: false, tx: DET_TX_IDLE, preview: { title: "Transcripción", lines: [] } },
  history: { folder: "", items: [], page: 1 },
  version: "",
  enginePath: "",
});

/** Actualiza una clave anidada: patch("tx", { status: "…" }). */
const patch = (key, changes) => store.set((s) => ({ [key]: { ...s[key], ...changes } }));
const S = () => store.get();

// ====================================================================== utilidades

function toast(text, glyph = G.info) {
  $("#toastText").textContent = text;
  $("#toastIcon").textContent = glyph;
  const t = $("#toast");
  t.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove("show"), 3500);
}

const fmtDur = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(sec)}` : `${p(m)}:${p(sec)}`;
};
const fmtSize = (b) => b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB"
  : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : Math.round(b / 1024) + " KB";
const fmtDate = (iso) => {
  const d = new Date(iso);
  const day = d.toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" }).replace(".", "");
  return `${day} · ${d.toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit" })}`;
};
const baseName = (p) => p.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
const dirName = (p) => p.replace(/[\\/][^\\/]*$/, "");
const withExt = (p, ext) => p.replace(/\.[^.\\/]+$/, "") + ext;
const jobId = (prefix) => prefix + "-" + Math.random().toString(36).slice(2, 9);
const srcKey = (s) => `${s.kind}:${s.kind === "monitor" ? s.index : s.hwnd}`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const textLines = (text) => text.split(/\r?\n/).filter((l) => l.trim());
const liveLine = (seg) => (S().config.timestamps ? `[${fmtDur(seg.start)}] ${seg.text}` : seg.text);

/** Línea "[mm:ss] texto" con el tiempo separado. */
function lineEl(text, fresh = false) {
  const div = document.createElement("div");
  div.className = "line" + (fresh ? " new" : "");
  const m = /^\[(\d[\d:]*)\]\s?(.*)$/.exec(text);
  if (m) div.innerHTML = `<span class="ts">${m[1]}</span>${esc(m[2])}`;
  else div.textContent = text;
  return div;
}

/** Sincroniza una lista de líneas agregando solo las nuevas (o rehaciéndola si cambió). */
function syncLines(box, lines) {
  if (box._lines && lines.length >= box._lines.length && lines.slice(0, box._lines.length).every((l, i) => l === box._lines[i])) {
    if (lines.length === box._lines.length) return;
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    for (const l of lines.slice(box._lines.length)) box.appendChild(lineEl(l, true));
    if (atBottom) box.scrollTop = box.scrollHeight;
  } else {
    box.innerHTML = "";
    for (const l of lines) box.appendChild(lineEl(l));
  }
  box._lines = lines;
}

function setProgress(el, pct) {
  el.classList.toggle("indet", pct == null);
  el.firstElementChild.style.width = pct == null ? "" : `${pct}%`;
}

const show = (el, visible) => el.classList.toggle("hidden", !visible);

// ======================================================================== renders

function renderNav(s) {
  $$("main .view").forEach((v) => show(v, v.id === `view-${s.view}`));
  // La ficha y "ver transcripción" son pantallas del Historial.
  const navKey = ["details", "transcript"].includes(s.view) ? "history" : s.view;
  $$("#nav button").forEach((b) => b.classList.toggle("active", b.dataset.nav === navKey));
  show($("#navLive"), s.rec.state !== "idle");
}

function renderEngine(s) {
  const e = s.engine, pill = $("#enginePill");
  $("#engineText").textContent = e.status;
  pill.title = e.status;
  pill.classList.toggle("ok", e.ready);
  pill.classList.toggle("err", e.error);
  $("#cfgEngine").textContent = s.enginePath;
  $("#aboutVersion").textContent = s.version ? `Versión ${s.version}` : "";
}

/** Valores de los controles enlazados con data-cfg (se sincronizan en todas las pantallas). */
function renderConfig(s) {
  for (const el of $$("[data-cfg]")) {
    const v = s.config[el.dataset.cfg];
    if (el.type === "checkbox") el.checked = !!v;
    else if (el !== document.activeElement) el.value = v ?? "";
  }
  $("#cfgOut").value = s.config.outputDir || "";
}

function renderDeviceLists(s) {
  for (const sel of $$("select[data-list]")) {
    const list = s.devices[sel.dataset.list] || [];
    sel.innerHTML = list.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
    sel.value = s.config[sel.dataset.cfg] ?? "";
  }
}

function renderHome(s) {
  const c = s.config;
  $$("[data-capture]").forEach((b) => b.classList.toggle("on", b.dataset.capture === c.captureKind));
  $$("[data-audio]").forEach((b) => {
    const on = b.dataset.audio === c.audioMode;
    b.classList.toggle("on", on);
    $("input", b).checked = on;
  });
  const audioOnly = c.captureKind === "audio";
  show($("#srcChange"), !audioOnly);
  if (audioOnly) {
    $("#srcIcon").textContent = G.audio;
    $("#srcText").textContent = "Solo audio (sin video)";
  } else {
    const src = currentSource(s);
    $("#srcIcon").textContent = src?.kind === "window" ? G.window : G.monitor;
    $("#srcText").textContent = src?.label
      || (c.captureKind === "window" ? "Elige una ventana" : s.engine.ready ? "Elige una pantalla" : "Buscando pantallas…");
  }
  $('#view-home [data-cfg="speaker"]').disabled = !["both", "sys"].includes(c.audioMode);
  $('#view-home [data-cfg="mic"]').disabled = !["both", "mic"].includes(c.audioMode);
  const busy = s.rec.state !== "idle";
  $("#recordBtn").disabled = busy;
  $("#recordText").textContent = busy ? "Grabación en curso…" : "Iniciar grabación";
  $("#recordHint").textContent = `Se guardará en ${c.outputDir || ""}`;
}

function renderPicker(s) {
  const p = s.picker;
  show($("#picker"), p.open);
  if (!p.open) return;
  $$("[data-ptab]").forEach((b) => {
    b.classList.toggle("on", b.dataset.ptab === p.tab);
    $("span", b).textContent = (b.dataset.ptab === "monitor" ? "Pantalla completa" : "Ventana") + ` (${p[b.dataset.ptab].length})`;
  });
  $("#pickOk").disabled = !p.selected;
  $("#pickSel").textContent = p.selected ? p.selected.label : "Nada seleccionado";

  const box = $("#pickTiles");
  const list = p[p.tab];
  const signature = p.loading ? "loading" : p.tab + "|" + list.map(srcKey).join(",");
  if (box._signature !== signature) {  // solo se rehacen las tarjetas si cambió la lista
    box._signature = signature;
    box.innerHTML = "";
    if (p.loading) box.innerHTML = `<div class="empty">Buscando pantallas y ventanas…</div>`;
    else if (!list.length) box.innerHTML = `<div class="empty">${p.tab === "window" ? "No hay ventanas abiertas para grabar." : "No se encontraron pantallas."}</div>`;
    for (const src of p.loading ? [] : list) {
      const b = document.createElement("button");
      b.className = "src";
      b.dataset.key = srcKey(src);
      b.title = src.label;
      b.innerHTML = `<div class="shot">${src.minimized ? "Minimizada<br>se restaurará al grabar" : "Cargando vista previa…"}</div>
        <div class="cap">${src.kind === "window" && src.app ? `<small>${esc(src.app)}</small>` : ""}<b>${esc(src.kind === "window" ? src.title : src.label)}</b></div>`;
      b.addEventListener("click", () => patch("picker", { selected: src }));
      b.addEventListener("dblclick", () => { patch("picker", { selected: src }); acceptPicker(); });
      box.appendChild(b);
    }
  }
  for (const b of $$(".src", box)) {
    const key = b.dataset.key;
    b.classList.toggle("on", !!p.selected && srcKey(p.selected) === key);
    if (key in p.thumbs && b._thumb !== p.thumbs[key]) {
      b._thumb = p.thumbs[key];
      const shot = $(".shot", b);
      if (p.thumbs[key]) shot.innerHTML = `<img src="data:image/png;base64,${p.thumbs[key]}">`;
      else if (!shot.textContent.includes("Minimizada")) shot.textContent = "Sin vista previa";
    }
  }
}

function renderRecording(s) {
  const r = s.rec;
  if (r.state === "idle") return;
  $("#recHead").classList.toggle("paused", r.paused);
  $("#recTitle").textContent = r.saving ? "Guardando…" : r.paused ? "En pausa" : "Grabando";
  $("#recPause .ic").textContent = r.paused ? G.play : G.pause;
  $("#recPause span").textContent = r.paused ? "Reanudar" : "Pausar";
  $("#recStop").disabled = $("#recPause").disabled = r.saving;
  $("#recTimer").textContent = fmtDur(r.elapsed);
  $("#recSource").textContent = r.sourceLabel;
  for (const [key, id] of [["mic", "#meterMic"], ["sys", "#meterSys"]]) {
    const on = !!r.audio[key], el = $(id);
    el.classList.toggle("off", !on);
    $("small", el).textContent = on ? "activo" : "silenciado";
    el.title = `Clic para ${on ? "silenciar" : "activar"}`;
    $(".bar i", el).style.width = on ? `${Math.max(0, r.levels[key] || 0) * 100}%` : "0";
  }
  show($("#liveTag"), r.live);
  $("#liveStatus").textContent = r.liveStatus;
  syncLines($("#liveText"), r.segments.map(liveLine));
  show($("#livePlaceholder"), !r.segments.length);
  $("#livePlaceholderText").textContent = r.live
    ? "Las frases aparecerán aquí mientras hablan."
    : "La transcripción en vivo está desactivada. Actívala en Inicio › Opciones adicionales.";
}

function renderTranscribe(s) {
  const t = s.tx;
  $$("[data-src]").forEach((b) => b.classList.toggle("on", b.dataset.src === t.mode));
  $("#txInput").placeholder = t.mode === "url"
    ? "Pega el link de YouTube (https://www.youtube.com/watch?v=…)" : "Elige un archivo (MP4, MKV, MOV, MP3, WAV…)";
  show($("#txBrowse"), t.mode !== "url");
  show($("#txProgressCard"), t.showProgress);
  $("#txStatus").textContent = t.status;
  $("#txPct").textContent = t.running && t.pct != null ? `${Math.round(t.pct)}%` : "";
  setProgress($("#txBar"), t.pct);
  $("#txCancel").disabled = !t.running;
  syncLines($("#txOutput"), t.lines);
  show($("#txPlaceholder"), !t.lines.length && !t.showProgress);
  $("#txStart").disabled = s.txBusy;
  $("#txOpenTxt").disabled = !t.txt;
  $("#txOpenSrt").disabled = !t.srt;
}

/** Números de página a mostrar: 1 … 4 5 [6] 7 8 … 20 */
function pageNumbers(page, pages) {
  const set = new Set([1, pages, page - 1, page, page + 1].filter((n) => n >= 1 && n <= pages));
  const sorted = [...set].sort((a, b) => a - b), out = [];
  sorted.forEach((n, i) => {
    if (i && n - sorted[i - 1] > 1) out.push("…");
    out.push(n);
  });
  return out;
}

function renderPager(page, pages) {
  const nav = $("#histPager");
  show(nav, pages > 1);
  nav.innerHTML = "";
  if (pages <= 1) return;
  const btn = (label, target, { on = false, disabled = false, aria = "" } = {}) => {
    const b = document.createElement("button");
    b.innerHTML = label;
    b.className = on ? "on" : "";
    b.disabled = disabled;
    if (aria) b.setAttribute("aria-label", aria);
    if (on) b.setAttribute("aria-current", "page");
    b.addEventListener("click", () => setHistoryPage(target));
    nav.appendChild(b);
  };
  btn(`<i class="ic"></i>Anterior`, page - 1, { disabled: page === 1, aria: "Página anterior" });
  for (const n of pageNumbers(page, pages)) {
    if (n === "…") nav.insertAdjacentHTML("beforeend", `<span class="gap">…</span>`);
    else btn(String(n), n, { on: n === page, aria: `Página ${n}` });
  }
  btn(`Siguiente<i class="ic"></i>`, page + 1, { disabled: page === pages, aria: "Página siguiente" });
}

/** Transcripción guardada (solo lectura): no comparte nada con la página "Transcribir". */
function renderViewer(s) {
  const v = s.viewer;
  if (!v.txt) return;
  const name = baseName(v.txt);
  $("#vwBackLabel").textContent = v.backLabel;
  setName($("#vwCrumb"), name);
  setName($("#vwTitle"), name);
  $("#vwInfo").textContent = `${v.lines.length} ${v.lines.length === 1 ? "línea" : "líneas"} · ${dirName(v.txt)}`;
  syncLines($("#vwText"), v.lines);
}

function renderHistory(s) {
  const { folder, items } = s.history;
  const total = items.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.min(Math.max(1, s.history.page || 1), pages);
  const first = (page - 1) * PAGE_SIZE;
  const visible = items.slice(first, first + PAGE_SIZE);

  $("#histFolder").textContent = folder;
  $("#histCount").textContent = total ? String(total) : "";
  $("#histCount").title = `${total} ${total === 1 ? "elemento" : "elementos"} en la carpeta`;
  show($("#histRange"), total > 0);
  const recordings = items.filter((i) => i.media).length;
  $("#histRange").textContent = `Mostrando ${first + 1}–${first + visible.length} de ${total} · `
    + `${recordings} ${recordings === 1 ? "grabación" : "grabaciones"}`
    + (total - recordings ? ` y ${total - recordings} ${total - recordings === 1 ? "transcripción" : "transcripciones"}` : "");
  show($("#histEmpty"), !total);
  renderPager(page, pages);

  const box = $("#histList");
  box.innerHTML = "";
  for (const it of visible) {
    const el = document.createElement("div");
    el.className = "item";
    const glyph = !it.media ? G.doc : it.audioOnly ? G.audio : G.video;
    const tag = it.media && it.txt ? `<span class="tag ok">Transcrito</span>` : !it.media ? `<span class="tag">Transcripción</span>` : "";
    el.innerHTML = `<div class="badge ${it.media ? "" : "doc"}"><i class="ic">${glyph}</i></div>
      <div class="info"><b title="${esc(it.name)}">${esc(shortName(it.name))}</b><div class="meta"><span>${fmtDate(it.date)} · ${fmtSize(it.size)}</span>${tag}</div></div>`;
    const actions = document.createElement("div");
    const add = (glyph, title, fn, danger = false) => {
      const b = document.createElement("button");
      b.className = "icon-btn" + (danger ? " danger" : "");
      b.textContent = glyph;
      b.title = title;
      b.setAttribute("aria-label", title);
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      actions.appendChild(b);
    };
    if (it.media) add(G.play, "Reproducir", () => api.open_path(it.media));
    if (it.media && !it.txt) add(G.doc, "Transcribir", () => openDetails(it.media, { transcribe: true }));
    if (it.txt) add(G.eye, "Ver transcripción", () => showTranscript(it.txt, "Historial", () => go("history")));
    add(G.folder, "Mostrar en la carpeta", () => api.reveal(it.media || it.txt));
    add(G.trash, "Eliminar", () => confirmDelete(it.media || it.txt, loadHistory), true);
    if (it.media) add(G.more, "Detalles", () => openDetails(it.media));
    el.appendChild(actions);
    el.addEventListener("click", () => (it.media ? openDetails(it.media)
      : showTranscript(it.txt, "Historial", () => go("history"))));
    box.appendChild(el);
  }
}

function renderDetails(s) {
  const d = s.det;
  if (!d.path) return;
  $("#detTitle").textContent = d.justRecorded ? "Grabación completada" : "Detalles";
  show($("#detCheck"), d.justRecorded);
  // Nombres largos: se muestran cortos (20 caracteres + "…") y completos en el tooltip.
  setName($("#detCrumb"), baseName(d.path));
  const name = $("#detName");
  if (name.readOnly) {  // no se pisa mientras se edita
    name.value = shortName(baseName(d.path));
    name.title = baseName(d.path);
  }
  $("#detFolder").textContent = dirName(d.path);
  $("#detDate").textContent = d.created ? fmtDate(d.created) : "";

  const info = d.info, img = $("#detImg");
  if (info?.thumb) { if (img._thumb !== info.thumb) { img.src = `data:image/png;base64,${info.thumb}`; img._thumb = info.thumb; } }
  show(img, !!info?.thumb);
  show($("#detAudioIcon"), !!info && !info.has_video);
  $("#detDur").textContent = info ? fmtDur(info.duration) : "";
  $("#detFmtIcon").textContent = info && !info.has_video ? G.audio : G.video;
  $("#detFmt").textContent = d.infoError ? "No se pudo leer: " + d.infoError
    : !info ? "Leyendo archivo…"
    : info.has_video ? `${info.width}×${info.height}${info.height >= 1080 ? " (Full HD)" : ""} · ${info.fps} FPS` : "Solo audio";
  $("#detSize").textContent = info ? fmtSize(info.size) : "";

  // Tarjeta "Generar transcripción": se deriva de la fase.
  const tx = d.tx;
  const titles = { idle: d.txt ? "Volver a transcribir" : "Generar transcripción", running: "Transcribiendo…",
                   done: "Transcripción lista", nospeech: "Sin voz detectada", error: "Generar transcripción",
                   canceled: "Generar transcripción" };
  $("#detTxIcon").textContent = tx.phase === "done" ? G.check : tx.phase === "nospeech" ? G.info : G.doc;
  $("#detTxTitle").textContent = titles[tx.phase];
  show($("#detTxBar"), tx.phase === "running");
  setProgress($("#detTxBar"), tx.pct);
  show($("#detTxStatus"), !!tx.status);
  $("#detTxStatus").textContent = tx.status;
  $("#detTx").disabled = tx.phase === "running" || s.txBusy;
  $("#detViewTx").disabled = !d.txt;

  show($("#detPreviewCard"), d.preview.lines.length > 0);
  $("#detPreviewTitle").textContent = d.preview.title;
  syncLines($("#detPreview"), d.preview.lines);
}

store.subscribe(["view", "rec"], renderNav);
store.subscribe(["engine", "version", "enginePath"], renderEngine);
store.subscribe(["config"], renderConfig);
store.subscribe(["devices"], renderDeviceLists);
store.subscribe(["config", "source", "monitors", "engine", "rec"], renderHome);
store.subscribe(["picker"], renderPicker);
store.subscribe(["rec", "config"], renderRecording);
store.subscribe(["tx", "txBusy"], renderTranscribe);
store.subscribe(["viewer"], renderViewer);
store.subscribe(["history"], renderHistory);
store.subscribe(["det", "txBusy"], renderDetails);

// ======================================================================= acciones

function go(view) {
  // Al salir de "Transcribir" la pantalla queda limpia para el próximo video
  // (la transcripción ya está guardada en .txt/.srt y en el Historial).
  // Si todavía está transcribiendo, se conserva para poder volver a ver el avance.
  if (S().view === "transcribe" && view !== "transcribe" && !S().tx.running) resetTranscribe();
  store.set({ view });
  $("#main").scrollTop = 0;
  if (view === "history") loadHistory();
}

/** Atrás: botón "←", Alt+← o el botón lateral del mouse. */
function goBack() {
  const s = S();
  if (s.view === "details") { go("history"); return true; }
  if (s.view === "transcript" && s.viewer.back) { s.viewer.back(); return true; }
  return false;
}

function setConfig(key, value) {
  patch("config", { [key]: value });
  api.set_config(key, value);
}

/** La fuente efectiva: con "Ventana" elegida, solo cuenta si de verdad hay una ventana. */
function currentSource(s = S()) {
  const c = s.config;
  if (c.captureKind === "audio") return null;
  if (c.captureKind === "window") return s.source?.kind === "window" ? s.source : null;
  return s.source?.kind === "monitor" ? s.source : defaultMonitor(s);
}

function defaultMonitor(s = S()) {
  return s.monitors.find((m) => m.index === s.config.monitorIndex)
    || s.monitors.find((m) => m.primary) || s.monitors[0] || null;
}

function refreshDevices() {
  api.send({ cmd: "list_devices" });
  toast("Dispositivos de audio actualizados.", G.refresh);
}

async function startRecording() {
  const c = S().config;
  const source = currentSource();
  if (c.captureKind !== "audio" && !source) { openPicker(c.captureKind === "window" ? "window" : "monitor"); return; }
  patch("rec", { state: "starting" });
  const r = await api.start_recording(source);
  if (r?.error) {
    patch("rec", { state: "idle" });
    toast(r.error, G.warn);
  }
}

// --- selector de pantalla

function openPicker(tab) {
  if (!S().engine.ready) { toast("El motor todavía se está iniciando…", G.warn); return; }
  store.set({ picker: { open: true, tab, monitor: [], window: [], thumbs: {}, selected: null, loading: true } });
  api.send({ cmd: "list_sources", exclude: EXCLUDE });
}

const closePicker = () => patch("picker", { open: false });

function acceptPicker() {
  const src = S().picker.selected;
  if (!src) return;
  store.set({ source: src });
  setConfig("captureKind", src.kind);
  if (src.kind === "monitor") setConfig("monitorIndex", src.index);
  closePicker();
}

// --- transcribir

function txOptions() {
  const c = S().config;
  return { out_dir: c.outputDir, model: c.model, language: c.language, vad: c.vad, timestamps: c.timestamps };
}

function startPageTx() {
  const s = S(), t = s.tx;
  const input = $("#txInput").value.trim().replace(/^"|"$/g, "");
  if (s.txBusy) { toast("Ya hay una transcripción en curso.", G.warn); return; }
  if (!input) { toast(t.mode === "url" ? "Pega un link de YouTube." : "Elige un archivo.", G.warn); return; }
  if (t.mode === "url" && !/^https?:\/\//i.test(input)) { toast("Pega un link válido (https://…).", G.warn); return; }
  const job = jobId("page");
  const msg = t.mode === "url" ? { cmd: "youtube", url: input } : { cmd: "transcribe", path: input, title: baseName(input) };
  api.send({ ...msg, ...txOptions(), job });
  patch("tx", { job, running: true, showProgress: true, status: t.mode === "url" ? "Conectando con YouTube…" : "Preparando…",
                pct: null, lines: [], txt: null, srt: null });
}

function onPageTx(ev) {
  const t = S().tx;
  const finish = (status, extra = {}) => patch("tx", { job: null, running: false, status, pct: 0, ...extra });
  switch (ev.type) {
    case "tx_download": patch("tx", { status: "Descargando audio…", pct: ev.pct }); break;
    case "tx_started": patch("tx", { lines: [...t.lines, `── ${ev.title} ──`] }); break;
    case "tx_status": patch("tx", { status: ev.text, pct: null }); break;
    case "tx_progress": patch("tx", { status: `Transcribiendo… faltan ~${fmtDur(ev.eta)}`, pct: ev.pct }); break;
    case "tx_segment": patch("tx", { lines: [...t.lines, ev.line] }); break;
    case "tx_done": finish(`Listo · guardado como ${baseName(ev.txt)}.txt y .srt`, { pct: 100, txt: ev.txt, srt: ev.srt }); break;
    case "tx_canceled": finish("Transcripción cancelada."); break;
    case "tx_nospeech": finish("No se detectó voz en este audio: no hay nada que transcribir."); break;
    case "tx_error": finish("Error: " + ev.message); break;
  }
}

/** Abre una transcripción guardada en su propia pantalla (solo lectura), con "← volver". */
async function showTranscript(txt, backLabel, back) {
  const text = await api.read_text(txt);
  store.set({ viewer: { txt, srt: withExt(txt, ".srt"), lines: textLines(text), back, backLabel } });
  go("transcript");
}

function clearTranscribe() {
  if (S().tx.job) return;
  patch("tx", { txt: null, srt: null, lines: [], showProgress: false });
}

/** Deja "Transcribir" como nueva: sin texto, sin progreso y sin el archivo/link escrito. */
function resetTranscribe() {
  patch("tx", { job: null, running: false, showProgress: false, status: "", pct: null, lines: [],
                txt: null, srt: null });
  txInputs.file = txInputs.url = "";
  $("#txInput").value = "";
}

async function copyText(text) {
  if (!text.trim()) return;
  await api.copy_text(text.trim());
  toast("Texto copiado al portapapeles.", G.copy);
}

// --- historial

/** Recarga la lista conservando la página (ajustada si ya no existe, p. ej. tras eliminar). */
async function loadHistory() {
  const r = await api.history();
  const pages = Math.max(1, Math.ceil(r.items.length / PAGE_SIZE));
  store.set({ history: { ...r, page: Math.min(S().history.page || 1, pages) } });
}

function setHistoryPage(page) {
  patch("history", { page });
  $("#main").scrollTop = 0;
}

/** Pide confirmación y envía a la Papelera la grabación con su transcripción. */
function confirmDelete(path, after) {
  const s = S();
  if (s.det.tx.phase === "running" && s.det.path === path) {
    toast("Espera a que termine la transcripción de esta grabación.", G.warn);
    return;
  }
  showDialog("¿Eliminar esta grabación?",
    `«${baseName(path)}» se enviará a la Papelera de reciclaje junto con su transcripción (.txt y .srt). Podrás recuperarla desde allí.`, [
      { icon: G.trash, title: "Eliminar", text: "Mover a la Papelera de reciclaje", danger: true,
        run: async () => {
          const r = await api.delete_recording(path);
          if (r.error) { toast(r.error, G.warn); return; }
          toast(`«${baseName(path)}» se movió a la Papelera.`, G.trash);
          after();
        } },
    ]);
}

// --- detalles

async function openDetails(path, { justRecorded = false, info = null, transcribe = false } = {}) {
  const req = info ? null : jobId("info");
  store.set({ det: { path, justRecorded, info, infoError: null, created: null, txt: null, job: null, req,
                     transcribeWhenLoaded: transcribe && !info, tx: DET_TX_IDLE,
                     preview: { title: "Transcripción", lines: [] } } });
  go("details");
  if (req) api.send({ cmd: "media_info", path, req });

  const fi = await api.file_info(path);
  if (S().det.path !== path) return;  // el usuario ya se fue a otra ficha
  patch("det", { created: fi?.created || null, txt: fi?.txt || null });
  if (fi?.txt) await loadDetPreview(fi.txt);
  if (info && transcribe) startDetailsTx();
}

async function loadDetPreview(txt) {
  const text = await api.read_text(txt);
  patch("det", { preview: { title: "Transcripción", lines: textLines(text) } });
}

function startDetailsTx() {
  const d = S().det;
  if (S().txBusy) { toast("Ya hay una transcripción en curso.", G.warn); return; }
  const job = jobId("rec");
  api.send({ cmd: "transcribe", path: d.path, title: baseName(d.path), ...txOptions(), out_dir: dirName(d.path), job });
  patch("det", { job, tx: { phase: "running", status: "Preparando…", pct: null },
                 preview: { title: "Transcripción", lines: [] } });
}

function onDetailsTx(ev) {
  const d = S().det;
  const tx = (changes) => patch("det", { tx: { ...d.tx, ...changes } });
  switch (ev.type) {
    case "tx_status": tx({ status: ev.text, pct: null }); break;
    case "tx_progress": tx({ status: `${Math.round(ev.pct)}% · faltan ~${fmtDur(ev.eta)}`, pct: ev.pct }); break;
    case "tx_segment": patch("det", { preview: { ...d.preview, title: "Transcripción", lines: [...d.preview.lines, ev.line] } }); break;
    case "tx_done":
      patch("det", { job: null, txt: ev.txt, tx: { phase: "done", status: "Guardada como .txt y .srt", pct: null } });
      loadDetPreview(ev.txt);
      break;
    case "tx_nospeech":
      patch("det", { job: null, tx: { phase: "nospeech", status: "La grabación no tiene voz: no hay nada que transcribir.", pct: null } });
      break;
    case "tx_error":
    case "tx_canceled":
      patch("det", { job: null, tx: { phase: ev.type === "tx_canceled" ? "canceled" : "error",
                                      status: ev.type === "tx_canceled" ? "Cancelada" : "Error: " + ev.message, pct: null } });
      break;
  }
}

/** Al terminar de grabar: pide el nombre. Resuelve con la ruta final (renombrada o la original). */
function askRecordingName(path) {
  return new Promise((resolve) => {
    const dlg = $("#nameDialog"), input = $("#nameInput"), error = $("#nameError");
    const original = baseName(path);
    input.value = original;
    error.textContent = "";
    show(dlg, true);
    setTimeout(() => { input.focus(); input.select(); }, 50);

    const finish = (finalPath) => {
      show(dlg, false);
      $("#nameSave").onclick = $("#nameKeep").onclick = input.onkeydown = null;
      resolve(finalPath);
    };
    const save = async () => {
      const name = input.value.trim();
      if (!name || name === original) { finish(path); return; }
      $("#nameSave").disabled = true;
      const r = await api.rename(path, name);
      $("#nameSave").disabled = false;
      if (r.error) { error.textContent = r.error; input.focus(); return; }
      toast(`Grabación guardada como «${baseName(r.path)}».`, G.check);
      finish(r.path);
    };
    $("#nameSave").onclick = save;
    $("#nameKeep").onclick = () => finish(path);
    input.onkeydown = (e) => {
      if (e.key === "Enter") save();
      if (e.key === "Escape") finish(path);
    };
  });
}

/** La grabación abierta cambió de nombre (también su .txt/.srt, si tenía). */
function detailsRenamed(path) {
  const d = S().det;
  patch("det", { path, txt: d.txt ? withExt(path, ".txt") : null });
}

/** Al terminar de grabar: qué hacer con la transcripción en vivo. */
function afterRecording(ev, segments) {
  if (ev.live_segments > 0 && segments.length) {
    patch("det", { preview: { title: "Transcripción en vivo (sin guardar)", lines: segments.map(liveLine) } });
    const model = S().config.model;
    showDialog("¿Qué hacemos con la transcripción en vivo?",
      `Se transcribieron ${segments.length} frases mientras grababas.`, [
        { icon: G.check, title: "Guardar el texto en vivo", text: "Listo al instante. Un poco menos preciso.",
          run: () => {
            const job = jobId("live");
            patch("det", { job, tx: { phase: "running", status: "Guardando…", pct: null } });
            api.send({ cmd: "save_live", path: ev.path, job, timestamps: S().config.timestamps });
          } },
        { icon: G.refresh, title: "Transcribir de nuevo con más precisión", text: `Usa el modelo «${model}». Tarda más, pero queda mejor.`,
          run: startDetailsTx },
      ]);
  } else if (S().config.autoTranscribe) {
    startDetailsTx();
  }
}

// --- diálogo genérico

function showDialog(title, text, options) {
  $("#dlgTitle").textContent = title;
  $("#dlgText").textContent = text;
  const box = $("#dlgOptions");
  box.innerHTML = "";
  for (const o of options) {
    const b = document.createElement("button");
    b.className = "option" + (o.danger ? " danger" : "");
    b.innerHTML = `<i class="ic">${o.icon}</i><div><b>${esc(o.title)}</b><small>${esc(o.text)}</small></div>`;
    b.addEventListener("click", () => { closeDialog(); o.run(); });
    box.appendChild(b);
  }
  show($("#dialog"), true);
}
const closeDialog = () => show($("#dialog"), false);

// =============================================================== eventos del motor

window.onEngine = (ev) => {
  const t = ev.type;
  // Transcripciones: se enrutan a la pantalla que las pidió.
  if (t.startsWith("tx_")) {
    if (t === "tx_started") store.set({ txBusy: true });
    if (["tx_done", "tx_error", "tx_canceled", "tx_nospeech"].includes(t)) store.set({ txBusy: false });
    if (ev.job && ev.job === S().tx.job) onPageTx(ev);
    if (ev.job && ev.job === S().det.job) onDetailsTx(ev);
    return;
  }
  const rec = S().rec;
  switch (t) {
    case "status":
      if (!S().engine.ready) patch("engine", { status: ev.text });
      break;
    case "ready":
      store.set({ engine: { ready: true, status: "Motor listo", error: false } });
      break;
    case "engine_stopped":
      store.set({ engine: { ready: false, status: "El motor se detuvo. Reinícialo en Configuración › Avanzado.", error: true } });
      break;
    case "devices": {
      const c = S().config;
      store.set({ devices: ev, config: { ...c,
        speaker: ev.speakers.includes(c.speaker) ? c.speaker : ev.default_speaker,
        mic: ev.mics.includes(c.mic) ? c.mic : ev.default_mic } });
      break;
    }
    case "monitors":
      store.set({ monitors: ev.monitors });
      break;
    case "sources":
      patch("picker", { monitor: ev.monitors, window: ev.windows, loading: false });
      break;
    case "thumb":
      patch("picker", { thumbs: { ...S().picker.thumbs, [ev.key]: ev.png } });
      break;
    case "rec_started": {
      const c = S().config;
      store.set({ rec: { ...REC_IDLE, state: "recording", live: ev.live, audio: ev.audio || REC_IDLE.audio,
                         liveStatus: ev.live ? "Preparando…" : "",
                         sourceLabel: c.captureKind === "audio" ? "Solo audio" : currentSource()?.label || "" } });
      go("live");
      break;
    }
    case "rec_audio": patch("rec", { audio: ev.audio }); break;
    case "rec_levels": patch("rec", { elapsed: ev.elapsed, levels: { mic: ev.mic, sys: ev.sys } }); break;
    case "rec_paused": patch("rec", { state: "paused", paused: true }); break;
    case "rec_resumed": patch("rec", { state: "recording", paused: false }); break;
    case "rec_source_closed": toast("La ventana que grababas se cerró. El audio sigue grabándose.", G.warn); break;
    case "rec_saving": patch("rec", { saving: true }); break;
    case "live_status": patch("rec", { liveStatus: ev.text }); break;
    case "live_segment":
      patch("rec", { segments: [...rec.segments, { start: ev.start, end: ev.end, text: ev.text }] });
      break;
    case "rec_saved": {
      const segments = rec.segments;
      store.set({ rec: { ...REC_IDLE } });
      // Primero el nombre; después la transcripción (así el .txt queda con el nombre elegido).
      openDetails(ev.path, { justRecorded: true, info: ev })
        .then(() => askRecordingName(ev.path))
        .then((path) => {
          if (path !== ev.path) detailsRenamed(path);
          afterRecording({ ...ev, path }, segments);
        });
      break;
    }
    case "rec_discarded":
      store.set({ rec: { ...REC_IDLE } });
      go("home");
      toast("Grabación descartada.", G.close);
      break;
    case "rec_error":
      store.set({ rec: { ...REC_IDLE } });
      go("home");
      toast(ev.message, G.warn);
      break;
    case "media_info": {
      const d = S().det;
      if (!ev.req || ev.req !== d.req) break;
      if (ev.error) { patch("det", { req: null, infoError: ev.error }); break; }
      patch("det", { req: null, info: ev });
      if (d.transcribeWhenLoaded) startDetailsTx();
      break;
    }
    case "warning":
    case "error":
      toast(ev.message, G.warn);
      break;
  }
};

// ======================================================= eventos de la interfaz

// Navegación
$$("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.nav)));
document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) go(g.dataset.goto);
});
document.addEventListener("keydown", (e) => {
  if (e.altKey && e.key === "ArrowLeft" && goBack()) e.preventDefault();
  if (e.key === "Escape") {
    if (S().picker.open) closePicker();
    else if (!$("#dialog").classList.contains("hidden")) closeDialog();
  }
});
document.addEventListener("mouseup", (e) => { if (e.button === 3 && goBack()) e.preventDefault(); });

// Controles enlazados a la configuración
$$("[data-cfg]").forEach((el) => el.addEventListener("change", () => {
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (el.hasAttribute("data-number")) v = Number(v);
  setConfig(el.dataset.cfg, v);
}));

// Inicio
$$("[data-capture]").forEach((b) => b.addEventListener("click", () => {
  const kind = b.dataset.capture, s = S();
  if (kind === "audio") {
    setConfig("captureKind", "audio");
    if (s.config.audioMode === "none") setConfig("audioMode", "both");
  } else if (kind === "monitor" && s.monitors.length === 1) {
    store.set({ source: s.monitors[0] });
    setConfig("monitorIndex", s.monitors[0].index);
    setConfig("captureKind", "monitor");
  } else {
    openPicker(kind);
  }
}));
$$("[data-audio]").forEach((b) => b.addEventListener("click", () => {
  if (b.dataset.audio === "none" && S().config.captureKind === "audio") {
    toast("Con «Solo audio» necesitas al menos una fuente de sonido.", G.warn);
    return;
  }
  setConfig("audioMode", b.dataset.audio);
}));
$("#srcChange").addEventListener("click", () => openPicker(S().config.captureKind === "window" ? "window" : "monitor"));
$("#refreshDevices").addEventListener("click", refreshDevices);
$("#recordBtn").addEventListener("click", startRecording);

// Selector de pantalla
$$("[data-ptab]").forEach((b) => b.addEventListener("click", () => patch("picker", { tab: b.dataset.ptab })));
$("#pickRefresh").addEventListener("click", () => openPicker(S().picker.tab));
$("#pickCancel").addEventListener("click", closePicker);
$("#pickOk").addEventListener("click", acceptPicker);
$("#picker").addEventListener("mousedown", (e) => { if (e.target.id === "picker") closePicker(); });

// Grabación en curso
$("#recPause").addEventListener("click", () => api.pause());
$("#recStop").addEventListener("click", () => api.stop());
$("#recCancel").addEventListener("click", () => api.cancel());
$$("[data-audio-toggle]").forEach((b) => b.addEventListener("click", () => api.toggle_audio(b.dataset.audioToggle)));
$("#liveCopy").addEventListener("click", () => copyText(S().rec.segments.map((s) => s.text).join("\n")));

// Transcribir
const txInputs = { file: "", url: "" };  // lo escrito en cada modo (el campo es del usuario)
$$("[data-src]").forEach((b) => b.addEventListener("click", () => {
  const t = S().tx;
  txInputs[t.mode] = $("#txInput").value;
  $("#txInput").value = txInputs[b.dataset.src];
  patch("tx", { mode: b.dataset.src });
}));
$("#txBrowse").addEventListener("click", async () => {
  const p = await api.pick_media();
  if (p) $("#txInput").value = p;
});
$("#txInput").addEventListener("keydown", (e) => { if (e.key === "Enter") startPageTx(); });
$("#txStart").addEventListener("click", startPageTx);
$("#txCancel").addEventListener("click", () => {
  api.send({ cmd: "cancel_transcription" });
  patch("tx", { status: "Cancelando…", running: false });
});
$("#txCopy").addEventListener("click", () => copyText(S().tx.lines.join("\n")));
$("#txOpenTxt").addEventListener("click", () => S().tx.txt && api.open_path(S().tx.txt));
$("#txOpenSrt").addEventListener("click", () => S().tx.srt && api.reveal(S().tx.srt));
$("#txFolder").addEventListener("click", () => api.reveal(S().tx.txt || S().config.outputDir));
$("#txClear").addEventListener("click", clearTranscribe);

// Ver transcripción guardada
$("#vwBack").addEventListener("click", goBack);
$("#vwCopy").addEventListener("click", () => copyText(S().viewer.lines.join("\n")));
$("#vwOpenTxt").addEventListener("click", () => api.open_path(S().viewer.txt));
$("#vwOpenSrt").addEventListener("click", () => api.reveal(S().viewer.srt));
$("#vwFolder").addEventListener("click", () => api.reveal(S().viewer.txt));

// Historial
$("#histRefresh").addEventListener("click", loadHistory);
$("#histOpen").addEventListener("click", () => api.reveal(S().config.outputDir));

// Detalles
$("#detBack").addEventListener("click", goBack);
$("#detPlay").addEventListener("click", () => api.open_path(S().det.path));
$("#detView").addEventListener("click", () => api.open_path(S().det.path));
$("#detOpenFolder").addEventListener("click", () => api.reveal(S().det.path));
$("#detShare").addEventListener("click", async () => {
  if (await api.copy_file(S().det.path)) toast("Archivo copiado. Pégalo (Ctrl+V) en Teams, WhatsApp, correo…", G.share);
});
$("#detTx").addEventListener("click", startDetailsTx);
$("#detViewTx").addEventListener("click", () => {
  const { path, txt } = S().det;
  if (txt) showTranscript(txt, "Detalles de la grabación", () => openDetails(path));
});
$("#detCopy").addEventListener("click", () => copyText(S().det.preview.lines.join("\n")));
$("#detDelete").addEventListener("click", () => confirmDelete(S().det.path, () => {
  patch("det", { path: null });
  go("history");
}));

// Cambiar nombre desde la ficha
const nameInput = $("#detName");
$("#detRename").addEventListener("click", () => {
  if (S().det.tx.phase === "running") { toast("Espera a que termine la transcripción.", G.warn); return; }
  nameInput.value = baseName(S().det.path);  // al editar se muestra el nombre completo
  nameInput.readOnly = false;
  nameInput.focus();
  nameInput.select();
});
nameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") nameInput.blur();
  if (e.key === "Escape") { nameInput.readOnly = true; renderDetails(S()); }
});
nameInput.addEventListener("blur", async () => {
  if (nameInput.readOnly) return;
  nameInput.readOnly = true;
  const path = S().det.path, name = nameInput.value.trim();
  if (!name || name === baseName(path)) { renderDetails(S()); return; }
  const r = await api.rename(path, name);
  if (r.error) { renderDetails(S()); toast(r.error, G.warn); return; }
  detailsRenamed(r.path);
  toast("Nombre actualizado.", G.check);
});

// Diálogo genérico
$("#dlgCancel").addEventListener("click", closeDialog);

// Configuración
$$("#pivot button").forEach((b) => b.addEventListener("click", () => {
  $$("#pivot button").forEach((x) => x.classList.toggle("on", x === b));
  $$("[data-panel]").forEach((p) => show(p, p.dataset.panel === b.dataset.tab));
}));
$("#cfgOutPick").addEventListener("click", async () => {
  const p = await api.pick_folder();
  if (p) setConfig("outputDir", p);
});
$("#cfgOutOpen").addEventListener("click", () => api.reveal(S().config.outputDir));
$("#cfgRefreshDevices").addEventListener("click", refreshDevices);
$("#cfgLog").addEventListener("click", () => api.open_log());
$("#cfgShortcuts").addEventListener("click", async () => {
  if (await api.create_shortcuts()) toast("Accesos directos creados en el Escritorio y en el menú Inicio.", G.check);
  else toast("No se pudieron crear los accesos directos.", G.warn);
});
$("#cfgRestart").addEventListener("click", async () => {
  const r = await api.restart_engine();
  if (r?.error) toast(r.error, G.warn);
  else store.set({ engine: { ready: false, status: "Iniciando motor…", error: false } });
});
$("#cfgReset").addEventListener("click", () => showDialog("Restablecer configuración",
  "Se vuelve a los valores por defecto (los dispositivos de audio se mantienen).", [
    { icon: G.refresh, title: "Restablecer", text: "Carpeta, video, audio y transcripción por defecto.",
      run: async () => {
        store.set({ config: await api.reset_config(), source: null });
        toast("Configuración restablecida.", G.refresh);
      } },
  ]));

// ========================================================================= arranque

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const s = await api.init();
  // Accesibilidad: los botones que solo tienen icono usan su title como nombre.
  for (const b of $$("button[title]:not([aria-label])")) b.setAttribute("aria-label", b.title);
  // Las opciones fijas de los selectores se llenan una sola vez.
  for (const sel of $$("select[data-options]")) {
    sel.innerHTML = OPTIONS[sel.dataset.options].map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
  }
  store.set({
    config: s.config,
    engine: { ready: s.ready, status: s.status, error: s.status.includes("detuvo") },
    monitors: s.monitors || [],
    devices: s.devices?.speakers ? s.devices : { speakers: [], mics: [] },
    version: s.version,
    enginePath: s.engine,
  });
  go("home");
});
