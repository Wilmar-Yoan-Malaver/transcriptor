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

// Opciones fijas de los selectores: [valor, clave del texto] (el texto sale de i18n.js).
const OPTIONS = {
  models: [["tiny", "model.tiny"], ["base", "model.base"], ["small", "model.small"],
           ["medium", "model.medium"], ["large-v3-turbo", "model.large"]],
  liveModels: [["tiny", "liveModel.tiny"], ["base", "liveModel.base"], ["small", "liveModel.small"]],
  languages: [["", "lang.auto"], ["es", "lang.es"], ["en", "lang.en"], ["pt", "lang.pt"],
              ["fr", "lang.fr"], ["it", "lang.it"], ["de", "lang.de"]],
  qualities: [["1080p", "quality.1080p"], ["720p", "quality.720p"], ["original", "quality.original"]],
  fps: [[15, "15"], [30, "fps.30"], [60, "60"]],
};

const EXCLUDE = ["Transcriptor", "Transcriptor · grabando"];
// Funciones puras (fmtDur, shortName, pageNumbers…) y PAGE_SIZE/NAME_MAX: ver lib.js.

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
  lang: "es",  // idioma de la interfaz; cambiarlo vuelve a dibujar todas las pantallas
  engine: { ready: false, status: "", error: false },
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
  viewer: { txt: null, srt: null, lines: [], back: null, backKey: "nav.history" },
  det: { path: null, justRecorded: false, info: null, infoError: null, created: null, txt: null,
         req: null, transcribeWhenLoaded: false, tx: DET_TX_IDLE, preview: { titleKey: "det.preview", lines: [] } },
  // Transcripción de una grabación pedida desde su ficha. Vive fuera de `det` para que siga
  // (y se vea su avance) aunque el usuario cambie de pantalla o abra otra grabación.
  recTx: null,  // { job, path, phase: "running", status, pct, lines }
  // Windows bloqueó la carpeta y la grabación quedó en Recuperadas: { message, unprotected }.
  blocked: null,
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
  const el = $("#toast");
  el.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => el.classList.remove("show"), 3500);
}

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
  const status = e.status || t("engine.starting");
  $("#engineText").textContent = status;
  pill.title = status;
  pill.classList.toggle("ok", e.ready);
  pill.classList.toggle("err", e.error);
  $("#cfgEngine").textContent = s.enginePath;
  $("#aboutVersion").textContent = s.version ? t("about.version", { version: s.version }) : "";
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
    $("#srcText").textContent = t("home.audioOnlySrc");
  } else {
    const src = currentSource(s);
    $("#srcIcon").textContent = src?.kind === "window" ? G.window : G.monitor;
    $("#srcText").textContent = src?.label
      || t(c.captureKind === "window" ? "home.chooseWindow" : s.engine.ready ? "home.chooseScreen" : "home.searchingScreens");
  }
  $('#view-home [data-cfg="speaker"]').disabled = !["both", "sys"].includes(c.audioMode);
  $('#view-home [data-cfg="mic"]').disabled = !["both", "mic"].includes(c.audioMode);
  const busy = s.rec.state !== "idle";
  $("#recordBtn").disabled = busy;
  $("#recordText").textContent = t(busy ? "home.recordingBusy" : "home.start");
  $("#recordHint").textContent = t("home.savedIn", { dir: c.outputDir || "" });
}

function renderPicker(s) {
  const p = s.picker;
  show($("#picker"), p.open);
  if (!p.open) return;
  $$("[data-ptab]").forEach((b) => {
    b.classList.toggle("on", b.dataset.ptab === p.tab);
    $("span", b).textContent = t(b.dataset.ptab === "monitor" ? "capture.monitor" : "picker.window") + ` (${p[b.dataset.ptab].length})`;
  });
  $("#pickOk").disabled = !p.selected;
  $("#pickSel").textContent = p.selected ? p.selected.label : t("picker.none");

  const box = $("#pickTiles");
  const list = p[p.tab];
  const signature = S().lang + "|" + (p.loading ? "loading" : p.tab + "|" + list.map(srcKey).join(","));
  if (box._signature !== signature) {  // solo se rehacen las tarjetas si cambió la lista
    box._signature = signature;
    box.innerHTML = "";
    if (p.loading) box.innerHTML = `<div class="empty">${esc(t("picker.loading"))}</div>`;
    else if (!list.length) box.innerHTML = `<div class="empty">${esc(t(p.tab === "window" ? "picker.noWindows" : "picker.noScreens"))}</div>`;
    for (const src of p.loading ? [] : list) {
      const b = document.createElement("button");
      b.className = "src";
      b.dataset.key = srcKey(src);
      b.title = src.label;
      b.innerHTML = `<div class="shot">${src.minimized ? `${esc(t("picker.minimized"))}<br>${esc(t("picker.minimizedHint"))}` : esc(t("picker.loadingPreview"))}</div>
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
      if (isBase64(p.thumbs[key])) shot.innerHTML = `<img src="data:image/png;base64,${p.thumbs[key]}">`;
      else if (!shot.textContent.includes(t("picker.minimized"))) shot.textContent = t("picker.noPreview");
    }
  }
}

function renderRecording(s) {
  const r = s.rec;
  if (r.state === "idle") return;
  $("#recHead").classList.toggle("paused", r.paused);
  $("#recTitle").textContent = t(r.saving ? "live.saving" : r.paused ? "live.paused" : "live.recording");
  $("#recPause .ic").textContent = r.paused ? G.play : G.pause;
  $("#recPause span").textContent = t(r.paused ? "live.resume" : "live.pause");
  $("#recStop").disabled = $("#recPause").disabled = r.saving;
  $("#recTimer").textContent = fmtDur(r.elapsed);
  $("#recSource").textContent = r.sourceLabel;
  for (const [key, id] of [["mic", "#meterMic"], ["sys", "#meterSys"]]) {
    const on = !!r.audio[key], el = $(id);
    el.classList.toggle("off", !on);
    $("small", el).textContent = t(on ? "live.on" : "live.muted");
    el.title = t(on ? "live.clickToMute" : "live.clickToUnmute");
    $(".bar i", el).style.width = on ? `${Math.max(0, r.levels[key] || 0) * 100}%` : "0";
  }
  show($("#liveTag"), r.live);
  $("#liveStatus").textContent = r.liveStatus;
  syncLines($("#liveText"), r.segments.map(liveLine));
  show($("#livePlaceholder"), !r.segments.length);
  $("#livePlaceholderText").textContent = t(r.live ? "live.placeholder" : "live.disabled");
}

function renderTranscribe(s) {
  const tx = s.tx;
  $$("[data-src]").forEach((b) => b.classList.toggle("on", b.dataset.src === tx.mode));
  $("#txInput").placeholder = t(tx.mode === "url" ? "tx.urlPlaceholder" : "tx.filePlaceholder");
  show($("#txBrowse"), tx.mode !== "url");
  show($("#txProgressCard"), tx.showProgress);
  $("#txStatus").textContent = tx.status;
  $("#txPct").textContent = tx.running && tx.pct != null ? `${Math.round(tx.pct)}%` : "";
  setProgress($("#txBar"), tx.pct);
  $("#txCancel").disabled = !tx.running;
  syncLines($("#txOutput"), tx.lines);
  show($("#txPlaceholder"), !tx.lines.length && !tx.showProgress);
  $("#txStart").disabled = s.txBusy;
  $("#txOpenTxt").disabled = !tx.txt;
  $("#txOpenSrt").disabled = !tx.srt;
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
  btn(`<i class="ic"></i>${esc(t("pager.prev"))}`, page - 1, { disabled: page === 1, aria: t("pager.prevAria") });
  for (const n of pageNumbers(page, pages)) {
    if (n === "…") nav.insertAdjacentHTML("beforeend", `<span class="gap">…</span>`);
    else btn(String(n), n, { on: n === page, aria: t("pager.page", { n }) });
  }
  btn(`${esc(t("pager.next"))}<i class="ic"></i>`, page + 1, { disabled: page === pages, aria: t("pager.nextAria") });
}

/** Transcripción guardada (solo lectura): no comparte nada con la página "Transcribir". */
function renderViewer(s) {
  const v = s.viewer;
  if (!v.txt) return;
  const name = baseName(v.txt);
  $("#vwBackLabel").textContent = t(v.backKey);
  setName($("#vwCrumb"), name);
  setName($("#vwTitle"), name);
  $("#vwInfo").textContent = `${tn("viewer.lines", v.lines.length)} · ${dirName(v.txt)}`;
  syncLines($("#vwText"), v.lines);
}

function renderHistory(s) {
  const { folder, items } = s.history;
  const total = items.length;
  const pages = pageCount(total);
  const page = Math.min(Math.max(1, s.history.page || 1), pages);
  const first = (page - 1) * PAGE_SIZE;
  const visible = items.slice(first, first + PAGE_SIZE);

  $("#histFolder").textContent = folder;
  $("#histCount").textContent = total ? String(total) : "";
  $("#histCount").title = tn("history.count", total);
  show($("#histRange"), total > 0);
  const recordings = items.filter((i) => i.media).length;
  $("#histRange").textContent = t("history.range", { from: first + 1, to: first + visible.length, total })
    + tn("history.recordings", recordings)
    + (total - recordings ? t("history.and") + tn("history.transcripts", total - recordings) : "");
  show($("#histEmpty"), !total);
  renderPager(page, pages);

  const box = $("#histList");
  box.innerHTML = "";
  for (const it of visible) {
    const el = document.createElement("div");
    el.className = "item";
    const glyph = !it.media ? G.doc : it.audioOnly ? G.audio : G.video;
    const busy = it.media && recTxFor(it.media, s);
    const tag = busy ? `<span class="tag">${esc(t("status.transcribing"))}</span>`
      : it.media && it.txt ? `<span class="tag ok">${esc(t("history.tagTranscribed"))}</span>`
      : !it.media ? `<span class="tag">${esc(t("history.tagTranscript"))}</span>` : "";
    el.innerHTML = `<div class="badge ${it.media ? "" : "doc"}"><i class="ic">${glyph}</i></div>
      <div class="info"><b title="${esc(it.name)}">${esc(shortName(it.name))}</b><div class="meta"><span>${fmtDate(it.date, locale())} · ${fmtSize(it.size)}</span>${tag}</div></div>`;
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
    if (it.media) add(G.play, t("common.play"), () => api.open_path(it.media));
    if (it.media && !it.txt && !busy) add(G.doc, t("nav.transcribe"), () => openDetails(it.media, { transcribe: true }));
    if (it.txt) add(G.eye, t("det.viewTx"), () => showTranscript(it.txt, "nav.history", () => go("history")));
    add(G.folder, t("history.reveal"), () => api.reveal(it.media || it.txt));
    add(G.trash, t("common.delete"), () => confirmDelete(it.media || it.txt, loadHistory), true);
    if (it.media) add(G.more, t("history.details"), () => openDetails(it.media));
    el.appendChild(actions);
    el.addEventListener("click", () => (it.media ? openDetails(it.media)
      : showTranscript(it.txt, "nav.history", () => go("history"))));
    box.appendChild(el);
  }
}

function renderDetails(s) {
  const d = s.det;
  if (!d.path) return;
  $("#detTitle").textContent = t(d.justRecorded ? "det.completed" : "det.details");
  show($("#detCheck"), d.justRecorded);
  // Nombres largos: se muestran cortos (20 caracteres + "…") y completos en el tooltip.
  setName($("#detCrumb"), baseName(d.path));
  const name = $("#detName");
  if (name.readOnly) {  // no se pisa mientras se edita
    name.value = shortName(baseName(d.path));
    name.title = baseName(d.path);
  }
  $("#detFolder").textContent = dirName(d.path);
  $("#detDate").textContent = d.created ? fmtDate(d.created, locale()) : "";

  const info = d.info, img = $("#detImg");
  const thumb = isBase64(info?.thumb) ? info.thumb : null;
  if (thumb && img._thumb !== thumb) { img.src = `data:image/png;base64,${thumb}`; img._thumb = thumb; }
  show(img, !!thumb);
  show($("#detAudioIcon"), !!info && !info.has_video);
  $("#detDur").textContent = info ? fmtDur(info.duration) : "";
  $("#detFmtIcon").textContent = info && !info.has_video ? G.audio : G.video;
  $("#detFmt").textContent = d.infoError ? t("det.readError", { error: d.infoError })
    : !info ? t("det.reading")
    : info.has_video ? `${info.width}×${info.height}${info.height >= 1080 ? " (Full HD)" : ""} · ${info.fps} FPS` : t("capture.audio");
  $("#detSize").textContent = info ? fmtSize(info.size) : "";

  // Tarjeta "Generar transcripción": se deriva de la fase.
  const running = recTxFor(d.path, s);
  const tx = running || d.tx;
  const otherBusy = !running && (s.txBusy || !!s.recTx);
  const titles = { idle: d.txt ? "det.retranscribe" : "det.generate", running: "status.transcribing",
                   done: "det.done", nospeech: "det.nospeech", error: "det.generate", canceled: "det.generate" };
  $("#detTxIcon").textContent = tx.phase === "done" ? G.check : tx.phase === "nospeech" ? G.info : G.doc;
  $("#detTxTitle").textContent = t(titles[tx.phase]);
  show($("#detTxBar"), tx.phase === "running");
  setProgress($("#detTxBar"), tx.pct);
  const status = tx.status || (otherBusy ? t("det.otherBusy") : "");
  show($("#detTxStatus"), !!status);
  $("#detTxStatus").textContent = status;
  $("#detTx").disabled = tx.phase === "running" || otherBusy;
  $("#detViewTx").disabled = !d.txt || !!running;

  const lines = running?.lines.length ? running.lines : d.preview.lines;
  show($("#detPreviewCard"), lines.length > 0);
  $("#detPreviewTitle").textContent = t(running?.lines.length ? "det.preview" : d.preview.titleKey);
  syncLines($("#detPreview"), lines);
}

store.subscribe(["view", "rec"], renderNav);
store.subscribe(["engine", "version", "enginePath", "lang"], renderEngine);
store.subscribe(["config", "lang"], renderConfig);
store.subscribe(["devices"], renderDeviceLists);
store.subscribe(["config", "source", "monitors", "engine", "rec", "lang"], renderHome);
store.subscribe(["picker", "lang"], renderPicker);
store.subscribe(["rec", "config", "lang"], renderRecording);
store.subscribe(["tx", "txBusy", "lang"], renderTranscribe);
store.subscribe(["viewer", "lang"], renderViewer);
store.subscribe(["history", "recTx", "lang"], renderHistory);
store.subscribe(["det", "txBusy", "recTx", "lang"], renderDetails);

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
  if (key === "uiLanguage") applyLanguage(value);
}

/** Llena los selectores de opciones fijas (modelos, idiomas…) en el idioma actual. */
function fillOptions() {
  for (const sel of $$("select[data-options]")) {
    const value = sel.value;
    sel.innerHTML = OPTIONS[sel.dataset.options]
      .map(([v, key]) => `<option value="${esc(v)}">${esc(t(key))}</option>`).join("");
    sel.value = value;
  }
}

/** Cambia el idioma de toda la interfaz: textos fijos, selectores y pantallas. */
function applyLanguage(lang) {
  setLang(lang);
  fillOptions();
  const e = S().engine;
  if (e.ready) patch("engine", { status: t("engine.ready") });
  else if (e.error) patch("engine", { status: t("engine.stopped") });
  store.set({ lang: LANG });
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
  toast(t("toast.devicesRefreshed"), G.refresh);
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
  if (!S().engine.ready) { toast(t("toast.engineStarting"), G.warn); return; }
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
  const s = S(), tx = s.tx;
  const input = $("#txInput").value.trim().replace(/^"|"$/g, "");
  if (s.txBusy) { toast(t("toast.txBusy"), G.warn); return; }
  if (!input) { toast(t(tx.mode === "url" ? "toast.pasteLink" : "toast.chooseFile"), G.warn); return; }
  if (tx.mode === "url" && !/^https?:\/\//i.test(input)) { toast(t("toast.invalidLink"), G.warn); return; }
  const job = jobId("page");
  const msg = tx.mode === "url" ? { cmd: "youtube", url: input } : { cmd: "transcribe", path: input, title: baseName(input) };
  api.send({ ...msg, ...txOptions(), job });
  patch("tx", { job, running: true, showProgress: true,
                status: t(tx.mode === "url" ? "status.connectingYoutube" : "status.preparing"),
                pct: null, lines: [], txt: null, srt: null });
}

function onPageTx(ev) {
  const tx = S().tx;
  const finish = (status, extra = {}) => patch("tx", { job: null, running: false, status, pct: 0, ...extra });
  switch (ev.type) {
    case "tx_download": patch("tx", { status: t("status.downloading"), pct: ev.pct }); break;
    case "tx_started": patch("tx", { lines: [...tx.lines, `── ${ev.title} ──`] }); break;
    case "tx_status": patch("tx", { status: ev.text, pct: null }); break;
    case "tx_progress": patch("tx", { status: t("status.remaining", { eta: fmtDur(ev.eta) }), pct: ev.pct }); break;
    case "tx_segment": patch("tx", { lines: [...tx.lines, ev.line] }); break;
    case "tx_done":
      finish(t("status.doneSaved", { name: baseName(ev.txt) }), { pct: 100, txt: ev.txt, srt: ev.srt });
      break;
    case "tx_canceled": finish(t("status.canceled")); break;
    case "tx_nospeech": finish(t("status.nospeechFile")); break;
    case "tx_error": finish(t("status.error", { error: ev.message })); break;
  }
}

/** Abre una transcripción guardada en su propia pantalla (solo lectura), con "← volver". */
async function showTranscript(txt, backKey, back) {
  const text = await api.read_text(txt);
  store.set({ viewer: { txt, srt: withExt(txt, ".srt"), lines: textLines(text), back, backKey } });
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
  toast(t("toast.copied"), G.copy);
}

// --- historial

/** Recarga la lista conservando la página (ajustada si ya no existe, p. ej. tras eliminar). */
async function loadHistory() {
  const r = await api.history();
  const pages = pageCount(r.items.length);
  store.set({ history: { ...r, page: Math.min(S().history.page || 1, pages) } });
}

function setHistoryPage(page) {
  patch("history", { page });
  $("#main").scrollTop = 0;
}

/** Pide confirmación y envía a la Papelera la grabación con su transcripción. */
function confirmDelete(path, after) {
  const s = S();
  if (recTxFor(path, s)) {
    toast(t("toast.waitThisTx"), G.warn);
    return;
  }
  showDialog(t("del.title"), t("del.text", { name: baseName(path) }), [
      { icon: G.trash, title: t("common.delete"), text: t("del.option"), danger: true,
        run: async () => {
          const r = await api.delete_recording(path);
          if (r.error) { toast(r.error, G.warn); return; }
          toast(t("toast.deleted", { name: baseName(path) }), G.trash);
          after();
        } },
    ]);
}

// --- detalles

async function openDetails(path, { justRecorded = false, info = null, transcribe = false } = {}) {
  const req = info ? null : jobId("info");
  store.set({ det: { path, justRecorded, info, infoError: null, created: null, txt: null, req,
                     transcribeWhenLoaded: transcribe && !info, tx: DET_TX_IDLE,
                     preview: { titleKey: "det.preview", lines: [] } } });
  go("details");
  if (req) api.send({ cmd: "media_info", path, req });

  const fi = await api.file_info(path);
  if (S().det.path !== path) return;  // el usuario ya se fue a otra ficha
  patch("det", { created: fi?.created || null, txt: fi?.txt || null });
  // Si se está transcribiendo de nuevo, se muestra el texto nuevo (recTx), no el anterior.
  if (fi?.txt && !recTxFor(path)) await loadDetPreview(fi.txt);
  if (info && transcribe) startDetailsTx();
}

async function loadDetPreview(txt) {
  const text = await api.read_text(txt);
  patch("det", { preview: { titleKey: "det.preview", lines: textLines(text) } });
}

/** La transcripción en curso de esta grabación, o null. */
function recTxFor(path, s = S()) {
  return path && s.recTx?.path === path ? s.recTx : null;
}

function startRecTx(path, job, status) {
  store.set({ recTx: { job, path, phase: "running", status, pct: null, lines: [] } });
}

function startDetailsTx() {
  const d = S().det;
  if (S().txBusy || S().recTx) { toast(t("toast.txBusy"), G.warn); return; }
  const job = jobId("rec");
  api.send({ cmd: "transcribe", path: d.path, title: baseName(d.path), ...txOptions(), out_dir: dirName(d.path), job });
  patch("det", { tx: DET_TX_IDLE, preview: { titleKey: "det.preview", lines: [] } });
  startRecTx(d.path, job, t("status.preparing"));
}

function onRecTx(ev) {
  const r = S().recTx;
  const update = (changes) => store.set({ recTx: { ...r, ...changes } });
  switch (ev.type) {
    case "tx_status": update({ status: ev.text, pct: null }); break;
    case "tx_progress": update({ status: t("status.pctRemaining", { pct: Math.round(ev.pct), eta: fmtDur(ev.eta) }), pct: ev.pct }); break;
    case "tx_segment": update({ lines: [...r.lines, ev.line] }); break;
    case "tx_done": finishRecTx(r, { phase: "done", status: t("status.savedTxtSrt") }, ev.txt); break;
    case "tx_nospeech": finishRecTx(r, { phase: "nospeech", status: t("status.nospeechRec") }); break;
    case "tx_error": finishRecTx(r, { phase: "error", status: t("status.error", { error: ev.message }) }); break;
    case "tx_canceled": finishRecTx(r, { phase: "canceled", status: t("status.canceledShort") }); break;
  }
}

/** Terminó la transcripción de una grabación: se refleja en su ficha y en el Historial, estén o no abiertos. */
function finishRecTx(r, result, txt = null) {
  store.set({ recTx: null });
  const s = S();
  if (s.det.path === r.path) {
    patch("det", { tx: { ...result, pct: null }, ...(txt ? { txt } : {}),
                   preview: { titleKey: "det.preview", lines: r.lines } });
    if (txt) loadDetPreview(txt);
  }
  if (!(s.view === "details" && s.det.path === r.path)) {
    const name = shortName(baseName(r.path));
    toast(txt ? t("toast.txReady", { name }) : t("toast.withName", { name, text: result.status }), txt ? G.check : G.warn);
  }
  if (s.view === "history") loadHistory();
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
      toast(t("toast.savedAs", { name: baseName(r.path) }), G.check);
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

/** Grabación guardada: primero el nombre; después la transcripción (así el .txt queda con el nombre elegido). */
function recordingSaved(ev, segments) {
  openDetails(ev.path, { justRecorded: true, info: ev })
    .then(() => askRecordingName(ev.path))
    .then((path) => {
      if (path !== ev.path) detailsRenamed(path);
      afterRecording({ ...ev, path }, segments);
    });
}

/** Windows no dejó guardar en la carpeta (acceso controlado a carpetas). Ofrece permitir la app o
 *  usar una carpeta que Windows no protege. Resuelve con la nueva ruta de la grabación cuando se
 *  movió; si el usuario cierra el diálogo, la grabación se queda en Recuperadas. */
function askBlockedFolder(blocked) {
  return new Promise((resolve) => {
    const done = (r, okText) => {
      if (r.canceled || r.error) {
        toast(r.error || t("blocked.canceled"), G.warn);
        ask();  // se puede probar la otra opción
        return;
      }
      if (r.folder) patch("config", { outputDir: r.folder });
      toast(okText(r), G.check);
      resolve(r.path);
    };
    const ask = () => showDialog(t("blocked.title"), blocked.message, [
      { icon: G.check, title: t("blocked.allow"), text: t("blocked.allowHint"),
        run: async () => done(await api.allow_folder_access(), () => t("blocked.allowed")) },
      { icon: G.folder, title: t("blocked.other"), text: t("blocked.otherHint", { folder: blocked.unprotected }),
        run: async () => done(await api.use_unprotected_folder(), (r) => t("blocked.moved", { folder: r.folder })) },
    ]);
    ask();
  });
}

/** Al terminar de grabar: qué hacer con la transcripción en vivo. */
function afterRecording(ev, segments) {
  if (ev.live_segments > 0 && segments.length) {
    patch("det", { preview: { titleKey: "det.previewLive", lines: segments.map(liveLine) } });
    const model = S().config.model;
    showDialog(t("live.dlgTitle"), tn("live.dlgText", segments.length), [
        { icon: G.check, title: t("live.keep"), text: t("live.keepHint"),
          run: () => {
            const job = jobId("live");
            startRecTx(ev.path, job, t("live.saving"));
            api.send({ cmd: "save_live", path: ev.path, job, timestamps: S().config.timestamps });
          } },
        { icon: G.refresh, title: t("live.redo"), text: t("live.redoHint", { model }),
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
  const type = ev.type;
  // Transcripciones: se enrutan a la pantalla que las pidió.
  if (type.startsWith("tx_")) {
    if (type === "tx_started") store.set({ txBusy: true });
    if (["tx_done", "tx_error", "tx_canceled", "tx_nospeech"].includes(type)) store.set({ txBusy: false });
    if (ev.job && ev.job === S().tx.job) onPageTx(ev);
    if (ev.job && ev.job === S().recTx?.job) onRecTx(ev);
    return;
  }
  const rec = S().rec;
  switch (type) {
    case "status":
      if (!S().engine.ready) patch("engine", { status: ev.text });
      break;
    case "ready":
      store.set({ engine: { ready: true, status: t("engine.ready"), error: false } });
      break;
    case "engine_stopped":
      store.set({ engine: { ready: false, status: t("engine.stopped"), error: true } });
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
                         liveStatus: ev.live ? t("status.preparing") : "",
                         sourceLabel: c.captureKind === "audio" ? t("capture.audio") : currentSource()?.label || "" } });
      go("live");
      break;
    }
    case "rec_audio": patch("rec", { audio: ev.audio }); break;
    case "rec_levels": patch("rec", { elapsed: ev.elapsed, levels: { mic: ev.mic, sys: ev.sys } }); break;
    case "rec_paused": patch("rec", { state: "paused", paused: true }); break;
    case "rec_resumed": patch("rec", { state: "recording", paused: false }); break;
    case "rec_source_closed": toast(t("toast.windowClosed"), G.warn); break;
    case "rec_saving": patch("rec", { saving: true }); break;
    case "live_status": patch("rec", { liveStatus: ev.text }); break;
    case "live_segment":
      patch("rec", { segments: [...rec.segments, { start: ev.start, end: ev.end, text: ev.text }] });
      break;
    case "folder_blocked": store.set({ blocked: ev }); break;
    case "rec_saved": {
      const segments = rec.segments, blocked = S().blocked;
      store.set({ rec: { ...REC_IDLE }, blocked: null });
      if (blocked) {
        // Quedó en Recuperadas: primero resolver dónde guardarla; después, lo de siempre.
        go("home");
        askBlockedFolder(blocked).then((path) => recordingSaved({ ...ev, path }, segments));
      } else {
        recordingSaved(ev, segments);
      }
      break;
    }
    case "rec_discarded":
      store.set({ rec: { ...REC_IDLE } });
      go("home");
      toast(t("toast.discarded"), G.close);
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
    toast(t("toast.audioOnlyNeedsSource"), G.warn);
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
  txInputs[S().tx.mode] = $("#txInput").value;
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
  patch("tx", { status: t("status.canceling"), running: false });
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
  if (await api.copy_file(S().det.path)) toast(t("toast.fileCopied"), G.share);
});
$("#detTx").addEventListener("click", startDetailsTx);
$("#detViewTx").addEventListener("click", () => {
  const { path, txt } = S().det;
  if (txt) showTranscript(txt, "det.backLabel", () => openDetails(path));
});
$("#detCopy").addEventListener("click", () => copyText(S().det.preview.lines.join("\n")));
$("#detDelete").addEventListener("click", () => confirmDelete(S().det.path, () => {
  patch("det", { path: null });
  go("history");
}));

// Cambiar nombre desde la ficha
const nameInput = $("#detName");
$("#detRename").addEventListener("click", () => {
  if (recTxFor(S().det.path)) { toast(t("toast.waitTx"), G.warn); return; }
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
  toast(t("toast.renamed"), G.check);
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
  if (await api.create_shortcuts()) toast(t("toast.shortcutsOk"), G.check);
  else toast(t("toast.shortcutsFail"), G.warn);
});
$("#cfgRestart").addEventListener("click", async () => {
  const r = await api.restart_engine();
  if (r?.error) toast(r.error, G.warn);
  else store.set({ engine: { ready: false, status: t("engine.starting"), error: false } });
});
$("#cfgReset").addEventListener("click", () => showDialog(t("set.reset"), t("set.resetText"), [
    { icon: G.refresh, title: t("set.resetOption"), text: t("set.resetOptionHint"),
      run: async () => {
        store.set({ config: await api.reset_config(), source: null });
        toast(t("toast.reset"), G.refresh);
      } },
  ]));

// ========================================================================= arranque

// Idioma de la app la primera vez que se abre (después se cambia en Configuración › General).
$$("#langDialog [data-lang]").forEach((b) => b.addEventListener("click", () => {
  show($("#langDialog"), false);
  setConfig("uiLanguage", b.dataset.lang);
}));

window.addEventListener("pywebviewready", async () => {
  api = window.pywebview.api;
  const s = await api.init();
  // Accesibilidad: los botones que solo tienen icono usan su title como nombre.
  for (const b of $$("button[title]:not([aria-label])")) b.setAttribute("aria-label", b.title);
  setLang(s.config.uiLanguage);
  fillOptions();
  store.set({
    lang: LANG,
    config: s.config,
    engine: { ready: s.ready, status: s.status, error: !!s.engineStopped },
    monitors: s.monitors || [],
    devices: s.devices?.speakers ? s.devices : { speakers: [], mics: [] },
    version: s.version,
    enginePath: s.engine,
  });
  go("home");
  if (!s.config.uiLanguage) show($("#langDialog"), true);
});
