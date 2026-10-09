# -*- mode: python -*-
# Empaquetado con PyInstaller: dist\Transcriptor\Transcriptor.exe (carpeta, no un solo archivo,
# porque arranca mucho más rápido con librerías tan grandes como Whisper y OpenCV).
#
#   python -m PyInstaller build\transcriptor.spec --distpath dist --workpath dist\_staging\pyi
#
# Ojo: el .exe resultante NO está firmado. En un PC con Smart App Control activado
# Windows lo bloqueará hasta que lo firmes con un certificado de confianza.

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [(str(ROOT / "ui"), "ui")]
binaries = []
hiddenimports = ["engine", "core", "app", "winutil", "overlay"]

# Paquetes con DLLs, modelos auxiliares (VAD), binarios (ffmpeg) o archivos de datos.
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "tokenizers", "soundcard",
            "imageio_ffmpeg", "webview", "pythonnet", "clr_loader", "windows_capture"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("yt_dlp")

a = Analysis(
    [str(ROOT / "Transcriptor.pyw")],
    pathex=[str(ROOT / "desktop"), str(ROOT / "engine")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "customtkinter", "matplotlib", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Transcriptor",
    icon=str(ROOT / "ui" / "icon.ico"),
    console=False,
    upx=False,
    version=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Transcriptor", upx=False)
