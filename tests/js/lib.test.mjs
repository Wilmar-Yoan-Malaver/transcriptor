// Pruebas de las funciones puras de la interfaz (ui/lib.js). Ejecutar: node --test tests/js
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const lib = require("../../ui/lib.js");

test("shortName corta a 20 caracteres y deja los cortos igual", () => {
  const long = "Sesión N. 5 Conexión Express Agilidad y eficiencia";
  assert.equal(lib.shortName(long), "Sesión N. 5 Conexión…");
  assert.equal(lib.shortName("reunion"), "reunion");
  assert.equal(lib.shortName("x".repeat(20)), "x".repeat(20));
});

test("fmtDur formatea minutos y horas", () => {
  assert.equal(lib.fmtDur(0), "00:00");
  assert.equal(lib.fmtDur(65.9), "01:05");
  assert.equal(lib.fmtDur(3725), "1:02:05");
  assert.equal(lib.fmtDur(undefined), "00:00");
});

test("fmtSize usa KB, MB y GB", () => {
  assert.equal(lib.fmtSize(2048), "2 KB");
  assert.equal(lib.fmtSize(150908120), "143.9 MB");
  assert.equal(lib.fmtSize(3 * 2 ** 30), "3.0 GB");
});

test("rutas de Windows", () => {
  const p = "C:\\Users\\yo\\Documentos\\Demo v1.2.mp4";
  assert.equal(lib.baseName(p), "Demo v1.2");
  assert.equal(lib.dirName(p), "C:\\Users\\yo\\Documentos");
  assert.equal(lib.withExt(p, ".txt"), "C:\\Users\\yo\\Documentos\\Demo v1.2.txt");
});

test("esc escapa HTML", () => {
  assert.equal(lib.esc('<b a="1">&</b>'), "&lt;b a=&quot;1&quot;&gt;&amp;&lt;/b&gt;");
});

test("textLines ignora líneas vacías", () => {
  assert.deepEqual(lib.textLines("a\r\n\r\nb\n  \nc"), ["a", "b", "c"]);
});

test("pageCount: 15 por página y mínimo 1", () => {
  assert.equal(lib.pageCount(0), 1);
  assert.equal(lib.pageCount(15), 1);
  assert.equal(lib.pageCount(16), 2);
  assert.equal(lib.pageCount(40), 3);
});

test("pageNumbers abrevia con … y siempre muestra primera y última", () => {
  assert.deepEqual(lib.pageNumbers(1, 1), [1]);
  assert.deepEqual(lib.pageNumbers(1, 3), [1, 2, 3]);
  assert.deepEqual(lib.pageNumbers(6, 20), [1, "…", 5, 6, 7, "…", 20]);
  assert.deepEqual(lib.pageNumbers(20, 20), [1, "…", 19, 20]);
});

// --- Seguridad: nada de lo que viene de afuera (títulos de YouTube, nombres de archivo,
// transcripciones) puede convertirse en HTML o código dentro de la interfaz.

const XSS = [
  `<script>alert(1)</script>`,
  `<img src=x onerror="alert(1)">`,
  `" onmouseover="alert(1)`,
  `' onmouseover='alert(1)`,
  `</div><iframe src="javascript:alert(1)">`,
  `&lt;script&gt;`,
];

test("esc neutraliza etiquetas y atributos inyectados", () => {
  for (const payload of XSS) {
    const out = lib.esc(payload);
    assert.doesNotMatch(out, /[<>"']/, payload);
    assert.doesNotMatch(out, /&(?!amp;|lt;|gt;|quot;|#39;)/, payload);  // ningún & sin escapar
  }
  assert.equal(lib.esc(`<b>"Hola" & 'adiós'</b>`), "&lt;b&gt;&quot;Hola&quot; &amp; &#39;adiós&#39;&lt;/b&gt;");
  assert.equal(lib.esc(42), "42");
});

test("isBase64 solo acepta miniaturas base64 válidas", () => {
  assert.ok(lib.isBase64("iVBORw0KGgoAAAANSUhEUgAA+/8="));
  for (const bad of [`x" onerror="alert(1)`, "abc<def", "javascript:alert(1)", "a b", "", null, undefined, 42,
                     "abc===", "data:image/png;base64,AAAA"]) {
    assert.equal(lib.isBase64(bad), false, String(bad));
  }
});
