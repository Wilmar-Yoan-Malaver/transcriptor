# Componentes de terceros / Third-party components

El código de Transcriptor está bajo la licencia Apache 2.0 (ver `LICENSE`).
Los paquetes que se distribuyen (zip portable e instalador) incluyen además estos componentes,
cada uno con su propia licencia. El paquete instalado trae `THIRD-PARTY-LICENSES.txt` con el
texto de la licencia de cada librería de Python, generado automáticamente al armarlo.

*Transcriptor's own code is licensed under Apache 2.0. The distributed packages also bundle the
components below under their own licenses; `THIRD-PARTY-LICENSES.txt` in the package contains the
full license text of every bundled Python library.*

## Entorno de ejecución / Runtime

| Componente | Licencia | Origen |
|---|---|---|
| Python (distribución "embeddable" oficial, firmada por la PSF) | PSF License 2.0 | https://www.python.org |
| Microsoft Visual C++ Runtime (incluido por algunas librerías) | Biblioteca del sistema / system library | Microsoft |

## Librerías principales / Main libraries

| Componente | Licencia | Para qué se usa |
|---|---|---|
| faster-whisper | MIT | Transcripción |
| CTranslate2 | MIT | Motor de inferencia de Whisper (ver nota de Intel abajo) |
| onnxruntime | MIT | Detección de voz (Silero VAD) |
| Silero VAD (modelo, dentro de faster-whisper) | MIT | Detección de voz |
| tokenizers, huggingface_hub | Apache 2.0 | Modelos de Whisper |
| numpy | BSD-3-Clause (y otras permisivas) | Audio |
| opencv-python | Apache 2.0 (incluye FFmpeg LGPL) | Miniaturas y video |
| windows-capture | MIT | Captura de pantalla y ventanas |
| SoundCard | BSD-3-Clause | Audio del escritorio y micrófono |
| pywebview, pythonnet | BSD-3-Clause, MIT | Ventana de la app |
| yt-dlp | Unlicense | Descarga de audio de YouTube |
| imageio-ffmpeg | BSD-2-Clause | Trae el ejecutable de FFmpeg |
| certifi, tqdm | MPL 2.0 | Certificados TLS, barras de progreso |

La lista completa, con versiones, está en `THIRD-PARTY-LICENSES.txt`.

## FFmpeg — GPL v3

El ejecutable de FFmpeg que trae `imageio-ffmpeg` está compilado con `--enable-gpl --enable-version3`
(incluye x264), así que se distribuye bajo la **GNU GPL versión 3**. Transcriptor lo ejecuta como un
programa aparte (no lo enlaza). Código fuente de FFmpeg: https://ffmpeg.org/download.html ·
origen del binario: https://github.com/imageio/imageio-ffmpeg. Si necesitas el código fuente
correspondiente exacto, abre un issue en este repositorio y lo proveeremos.

*The bundled FFmpeg binary is a GPLv3 build; Transcriptor runs it as a separate program. Source:
https://ffmpeg.org/download.html. For the exact corresponding source, open an issue in this repository.*

## Modelos de Whisper / Whisper models

Los modelos `tiny`, `base` y `small` incluidos son las conversiones a CTranslate2 publicadas por
Systran (https://huggingface.co/Systran) de los modelos Whisper de OpenAI, ambos bajo licencia **MIT**.

## Componentes de Intel y NVIDIA / Intel and NVIDIA components

- **Intel oneMKL** (enlazada dentro de `ctranslate2.dll`) e **Intel OpenMP Runtime**
  (`libiomp5md.dll`, firmada por Intel) vienen incluidas en las ruedas oficiales de CTranslate2.
  **No son de código abierto**: se redistribuyen bajo la *Intel Simplified Software License*, que lo
  permite. Transcriptor no las modifica.
- **NVIDIA cuDNN** (`cudnn64_9.dll`), que también viene en la rueda de CTranslate2, **se excluye** de
  los paquetes: solo sirve para transcribir con una tarjeta gráfica NVIDIA y Transcriptor usa el procesador.

*Intel oneMKL (statically linked in `ctranslate2.dll`) and the Intel OpenMP runtime (`libiomp5md.dll`)
ship inside the official CTranslate2 wheels. They are not open source; they are redistributed under the
Intel Simplified Software License. NVIDIA cuDNN is excluded from the packages (GPU only; the app uses the CPU).*
