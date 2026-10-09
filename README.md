# Transcriptor

Graba tu pantalla, una ventana o una reunión y conviértela en texto con Whisper, todo en tu PC.
También transcribe archivos de video/audio y links de YouTube, incluso en vivo mientras grabas.

## Estructura

```
Transcriptor.pyw   punto de entrada (abre la app; con --engine arranca el motor)
desktop/           ventana pywebview, barra flotante, borde rojo, configuración
ui/                interfaz HTML/CSS/JS (index.html, style.css, lib.js, app.js, bar.html)
engine/            motor: Whisper, captura (Windows Graphics Capture), audio, YouTube
build/             scripts de empaquetado
tests/             pruebas automáticas (pytest y node --test)
dist/              paquetes generados (no se edita a mano)
```

## Ejecutar en desarrollo

Entorno de Python: `%USERPROFILE%\.venvs\transcriptor` (Python 3.14).

```bash
%USERPROFILE%\.venvs\transcriptor\Scripts\pythonw.exe Transcriptor.pyw
```

O doble clic en `Transcriptor.lnk`. No hay que compilar: al cambiar un `.py`, `.html`, `.css`
o `.js`, cierra y vuelve a abrir la app.

Registro del motor: `%APPDATA%\Transcriptor\engine.log`.

## Calidad: linters y pruebas

Instalar las herramientas (una vez):

```bash
%USERPROFILE%\.venvs\transcriptor\Scripts\python.exe -m pip install -r requirements-dev.txt
npm install
```

Ejecutar:

```bash
%USERPROFILE%\.venvs\transcriptor\Scripts\python.exe -m ruff check .
%USERPROFILE%\.venvs\transcriptor\Scripts\python.exe -m pytest -q
npm run lint
npm test
```

- `ruff` (Python) y `ESLint` (interfaz) revisan errores comunes y estilo. La configuración está en
  `pyproject.toml` y `eslint.config.mjs`.
- `tests/` tiene pruebas del motor, de la API de la interfaz y del protocolo JSON (`pytest`), y de
  las funciones puras de `ui/lib.js` (`node --test`).
- GitHub Actions (`.github/workflows/calidad.yml`) corre todo en cada push a `main` y en cada PR.

## Empaquetar

### Portable (recomendado; Smart App Control no la bloquea)

```bash
%USERPROFILE%\.venvs\transcriptor\Scripts\python.exe build\build_portable.py --zip
```

Genera `dist\Transcriptor-portable\` y `dist\Transcriptor-portable.zip`: Python oficial firmado +
librerías + app + modelos (tiny, base, small). Se abre con `Transcriptor.cmd`.

### .exe con PyInstaller

```bash
%USERPROFILE%\.venvs\transcriptor\Scripts\python.exe -m PyInstaller build\transcriptor.spec --noconfirm --distpath dist --workpath dist\_staging\pyi
```

Genera `dist\Transcriptor\Transcriptor.exe` (copia la carpeta `dist\_staging\models` a
`dist\Transcriptor\models` para incluir los modelos). **No está firmado**: en un PC con
Smart App Control activado Windows lo bloquea hasta firmarlo con un certificado de confianza
(por ejemplo Azure Artifact Signing).

### Modelos de Whisper

Los paquetes usan la carpeta `models\` si existe (variable `TRANSCRIPTOR_MODELS`); si un modelo
no está ahí, se descarga la primera vez que se usa. Para (re)descargar los incluidos:

```python
from faster_whisper import download_model
for name in ("tiny", "base", "small"):
    download_model(name, output_dir=f"dist/_staging/models/{name}")
```
