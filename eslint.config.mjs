// ESLint para la interfaz (ui/) y sus pruebas.
import js from "@eslint/js";
import globals from "globals";

// Lo que ui/lib.js deja disponible para ui/app.js (se cargan como <script> en ese orden).
const libGlobals = Object.fromEntries(
  ["PAGE_SIZE", "NAME_MAX", "shortName", "fmtDur", "fmtSize", "fmtDate", "baseName", "dirName", "withExt",
   "jobId", "srcKey", "esc", "textLines", "pageCount", "pageNumbers"].map((name) => [name, "readonly"]),
);

export default [
  js.configs.recommended,
  {
    files: ["ui/**/*.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "script",
      globals: { ...globals.browser, pywebview: "readonly" },
    },
    rules: {
      eqeqeq: ["error", "always", { null: "ignore" }],  // `x == null` cubre null y undefined
      "no-var": "error",
      "prefer-const": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
  {
    files: ["ui/lib.js"],
    languageOptions: { globals: { module: "writable" } },
    // Sus funciones se usan desde app.js, no dentro del propio archivo.
    rules: { "no-unused-vars": "off" },
  },
  { files: ["ui/app.js"], languageOptions: { globals: libGlobals } },
  { files: ["tests/js/**/*.mjs"], languageOptions: { sourceType: "module", globals: globals.node } },
];
