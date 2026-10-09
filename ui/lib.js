/* Transcriptor · funciones puras de la interfaz (sin DOM ni estado).
 *
 * Se cargan antes que app.js y quedan disponibles para él. También se pueden importar
 * desde Node.js para las pruebas automáticas (tests/js/lib.test.mjs).
 */
"use strict";

const PAGE_SIZE = 15;  // elementos por página del historial
const NAME_MAX = 20;   // caracteres visibles de un nombre de archivo (el completo va en el tooltip)

/** "Sesión N. 5 Conexión…" — corta nombres largos; el completo se muestra al pasar el mouse. */
const shortName = (name) => (name.length > NAME_MAX ? name.slice(0, NAME_MAX).trimEnd() + "…" : name);

/** Segundos → "mm:ss" o "h:mm:ss". */
const fmtDur = (s) => {
  s = Math.max(0, Math.floor(s || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  const p = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${p(m)}:${p(sec)}` : `${p(m)}:${p(sec)}`;
};

/** Bytes → "143.9 MB". */
const fmtSize = (b) => (b >= 1 << 30 ? (b / (1 << 30)).toFixed(1) + " GB"
  : b >= 1 << 20 ? (b / (1 << 20)).toFixed(1) + " MB" : Math.round(b / 1024) + " KB");

/** Fecha ISO → "08 oct 2026 · 10:02 a. m." */
const fmtDate = (iso) => {
  const d = new Date(iso);
  const day = d.toLocaleDateString("es-CO", { day: "2-digit", month: "short", year: "numeric" }).replace(".", "");
  return `${day} · ${d.toLocaleTimeString("es-CO", { hour: "numeric", minute: "2-digit" })}`;
};

// Rutas de Windows (aceptan \ y /)
const baseName = (p) => p.split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
const dirName = (p) => p.replace(/[\\/][^\\/]*$/, "");
const withExt = (p, ext) => p.replace(/\.[^.\\/]+$/, "") + ext;

const jobId = (prefix) => prefix + "-" + Math.random().toString(36).slice(2, 9);
const srcKey = (s) => `${s.kind}:${s.kind === "monitor" ? s.index : s.hwnd}`;
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const textLines = (text) => text.split(/\r?\n/).filter((l) => l.trim());

/** Cantidad de páginas para `total` elementos (mínimo 1). */
const pageCount = (total, size = PAGE_SIZE) => Math.max(1, Math.ceil(total / size));

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

if (typeof module !== "undefined") {
  module.exports = { PAGE_SIZE, NAME_MAX, shortName, fmtDur, fmtSize, fmtDate, baseName, dirName, withExt,
                     jobId, srcKey, esc, textLines, pageCount, pageNumbers };
}
