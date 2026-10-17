// Pruebas del idioma de la interfaz (ui/i18n.js): que no falte ningún texto en español ni en inglés.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const i18n = require("../../ui/i18n.js");
const read = (file) => readFileSync(new URL(`../../ui/${file}`, import.meta.url), "utf8");

const keysOf = (lang) => Object.keys(i18n.I18N[lang]).sort();
const placeholders = (text) => [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
const exists = (key) => key in i18n.I18N.es || (`${key}.one` in i18n.I18N.es && `${key}.other` in i18n.I18N.es);

test("español e inglés tienen exactamente las mismas claves", () => {
  assert.deepEqual(keysOf("en"), keysOf("es"));
});

test("cada traducción conserva los mismos {marcadores}", () => {
  for (const key of keysOf("es")) {
    assert.deepEqual(placeholders(i18n.I18N.en[key]), placeholders(i18n.I18N.es[key]), key);
  }
});

test("ningún texto en inglés quedó sin traducir (igual al español)", () => {
  // Palabras que se escriben igual en ambos idiomas.
  const same = new Set(["set.tabGeneral", "set.tabVideo", "set.tabAudio", "about.flow2", "about.audio",
                        "status.error", "bar.audio", "nav.transcribe"]);
  const untranslated = keysOf("es").filter((k) => !same.has(k) && i18n.I18N.en[k] === i18n.I18N.es[k]);
  assert.deepEqual(untranslated, []);
});

test("todas las claves del HTML existen (index.html y bar.html)", () => {
  for (const file of ["index.html", "bar.html"]) {
    const keys = [...read(file).matchAll(/data-i18n(?:-title|-placeholder|-aria)?="([^"]+)"/g)].map((m) => m[1]);
    assert.ok(keys.length > 0, file);
    for (const key of keys) assert.ok(exists(key), `${file}: ${key}`);
  }
});

test("todas las claves que usa el código existen (app.js y bar.html)", () => {
  const namespaces = new Set(keysOf("es").map((k) => k.split(".")[0]));
  for (const file of ["app.js", "bar.html"]) {
    const code = read(file);
    // t("clave"), tn("clave", n) y claves sueltas ("det.preview") que después pasan por t().
    const literals = [...code.matchAll(/["'`]([a-zA-Z]+\.[a-zA-Z0-9.]+)["'`]/g)].map((m) => m[1])
      .filter((k) => namespaces.has(k.split(".")[0]) && !/\.(js|html|txt|srt|mp4|json)$/.test(k));
    assert.ok(literals.length > 50 || file === "bar.html", file);
    for (const key of literals) assert.ok(exists(key), `${file}: ${key}`);
  }
  for (const key of ["audio.mic", "audio.sys"]) assert.ok(exists(key));  // t(`audio.${key}`) en la barra
});

test("t() traduce, reemplaza marcadores y usa el español o la clave como respaldo", () => {
  i18n.setLang("en");
  assert.equal(i18n.t("nav.home"), "Home");
  assert.equal(i18n.t("home.savedIn", { dir: "C:\\X" }), "Will be saved in C:\\X");
  assert.equal(i18n.t("no.existe"), "no.existe");
  i18n.setLang("es");
  assert.equal(i18n.t("nav.home"), "Inicio");
});

test("tn() elige singular o plural", () => {
  i18n.setLang("es");
  assert.equal(i18n.tn("history.recordings", 1), "1 grabación");
  assert.equal(i18n.tn("history.recordings", 3), "3 grabaciones");
  i18n.setLang("en");
  assert.equal(i18n.tn("viewer.lines", 1), "1 line");
  assert.equal(i18n.tn("viewer.lines", 0), "0 lines");
  i18n.setLang("es");
});

test("un idioma desconocido o vacío deja el español", () => {
  assert.equal(i18n.setLang("fr"), "es");
  assert.equal(i18n.setLang(null), "es");
  assert.equal(i18n.setLang("en"), "en");
  assert.equal(i18n.locale(), "en-US");
  i18n.setLang("es");
});

test("ninguna pantalla pisa la función global setLang (causaba recursión infinita en la barra)", () => {
  for (const file of ["app.js", "bar.html"]) {
    assert.doesNotMatch(read(file), /window\.setLang\s*=/, file);
  }
});
