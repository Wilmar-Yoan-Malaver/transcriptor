"""Arma la versión portable: Python oficial (firmado) + librerías + app + modelos.

No se compila nada, así que Smart App Control no la bloquea: lo único que se
ejecuta es pythonw.exe, firmado por la Python Software Foundation.

Uso (desde el entorno de desarrollo):
    python build\\build_portable.py [--out dist] [--models dist\\_staging\\models] [--zip]
"""

import argparse
import compileall
import hashlib
import py_compile
import shutil
import sys
import sysconfig
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_VERSION = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
EMBED_URL = f"https://www.python.org/ftp/python/{PY_VERSION}/python-{PY_VERSION}-embed-amd64.zip"
# Huella SHA-256 del Python embeddable de cada versión. Si la descarga no coincide (archivo dañado
# o alterado), el empaquetado se detiene. Al subir de versión de Python, agregar aquí la nueva
# huella (python.org la publica en la página de cada versión).
EMBED_SHA256 = {
    "3.14.7": "d297e5ff019966817ad8502465176139f2d3d840fa4ed84b13bed399a6ab1f15",
}
APP_ITEMS = ["Transcriptor.pyw", "desktop", "engine", "ui"]
# Herramientas de desarrollo que no hacen falta para usar la app.
SKIP_PACKAGES = ("pip", "setuptools", "pyinstaller", "_pyinstaller_hooks_contrib", "altgraph",
                 "pefile", "pywin32_ctypes", "customtkinter", "darkdetect",
                 "pytest", "_pytest", "pluggy", "iniconfig", "ruff", "bandit", "pip_audit")
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")
# Librerías: además se omite cuDNN (NVIDIA, no es de código abierto). ctranslate2 solo la carga
# para usar una tarjeta gráfica NVIDIA y la app transcribe en el procesador.
IGNORE_LIBS = shutil.ignore_patterns("__pycache__", "*.pyc", "cudnn*.dll")
LEGAL_FILES = ["LICENSE", "NOTICE", "THIRD_PARTY_NOTICES.md"]

LAUNCHER = '@echo off\r\nstart "" "%~dp0python\\pythonw.exe" "%~dp0app\\Transcriptor.pyw"\r\n'
README = """TRANSCRIPTOR (versión portable)
================================

Abrir la app:
  Doble clic en "Transcriptor.cmd".
  Para tener el icono en el Escritorio y en el menú Inicio:
  Configuración › General › "Crear accesos directos".

Si copiaste el .zip desde internet o un correo y Windows muestra advertencias:
  clic derecho en el .zip › Propiedades › marcar "Desbloquear" › Aceptar, y descomprímelo de nuevo.

Requisitos del PC: Windows 10/11 de 64 bits (WebView2 ya viene con Windows 11).
No necesita instalar Python ni nada más. Funciona sin internet: incluye los modelos
de Whisper tiny, base y small. Los modelos medium y large se descargan si los eliges.

Las grabaciones y transcripciones se guardan en Documentos\\Transcripciones
(se puede cambiar en Configuración). La configuración vive en %APPDATA%\\Transcriptor.
"""


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(2**20), b""):
            h.update(block)
    return h.hexdigest()


def verify_embed(path):
    expected = EMBED_SHA256.get(PY_VERSION)
    actual = sha256(path)
    if expected is None:
        sys.exit(f"Falta la huella de Python {PY_VERSION} en EMBED_SHA256 (la descargada es {actual}).\n"
                 "Compárala con la publicada en python.org y agrégala.")
    if actual != expected:
        path.unlink()
        sys.exit(f"La huella de {path.name} no coincide: se esperaba {expected} y llegó {actual}. "
                 "Se borró la descarga; vuelve a intentarlo.")


LICENSE_NAMES = ("LICENSE", "LICENCE", "COPYING", "NOTICE", "AUTHORS")


def package_license(meta):
    """(nombre, versión, licencia) de un METADATA de Python."""
    fields = {}
    classifiers = []
    for line in meta.splitlines():
        key, _, value = line.partition(":")
        if key == "Classifier" and value.strip().startswith("License"):
            classifiers.append(value.split("::")[-1].strip())
        elif key in ("Name", "Version", "License", "License-Expression") and key not in fields:
            fields[key] = value.strip()
    license_name = fields.get("License-Expression") or fields.get("License") or ", ".join(classifiers)
    return fields.get("Name", "?"), fields.get("Version", "?"), license_name or "ver archivos de licencia"


def write_third_party_licenses(site_dir, out_file):
    """Junta la licencia de cada librería incluida (nombre, versión, licencia y sus textos)."""
    parts = ["Licencias de las librerías incluidas en Transcriptor / Licenses of bundled libraries",
             "Ver también THIRD_PARTY_NOTICES.md (FFmpeg, modelos de Whisper, componentes de Intel).", ""]
    for info in sorted(site_dir.glob("*.dist-info"), key=lambda d: d.name.lower()):
        name, version, license_name = package_license(
            (info / "METADATA").read_text(encoding="utf-8", errors="replace"))
        parts += ["=" * 78, f"{name} {version}  —  {license_name}", "=" * 78]
        texts = sorted(f for f in info.rglob("*") if f.is_file() and f.name.upper().startswith(LICENSE_NAMES))
        for lic in texts:
            text = lic.read_text(encoding="utf-8", errors="replace").strip()
            parts += [f"--- {lic.relative_to(info)} ---", text, ""]
    out_file.write_text("\n".join(parts) + "\n", encoding="utf-8")


def site_packages():
    return Path(sysconfig.get_paths()["purelib"])


def skip(name):
    low = name.lower()
    return any(low == p or low.startswith(p + "-") or low.startswith(p + ".") for p in SKIP_PACKAGES)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    ap.add_argument("--models", default=str(ROOT / "dist" / "_staging" / "models"))
    ap.add_argument("--zip", action="store_true")
    args = ap.parse_args()

    out_root = Path(args.out)
    staging = out_root / "_staging"
    staging.mkdir(parents=True, exist_ok=True)
    target = out_root / "Transcriptor-portable"
    if target.exists():
        shutil.rmtree(target)

    # 1. Python oficial "embeddable" (misma versión que el entorno de desarrollo)
    embed_zip = staging / Path(EMBED_URL).name
    if not embed_zip.exists():
        print("Descargando", EMBED_URL)
        # URL fija https de python.org; además se verifica la huella justo abajo.
        urllib.request.urlretrieve(EMBED_URL, embed_zip)  # nosec B310
    verify_embed(embed_zip)
    py_dir = target / "python"
    with zipfile.ZipFile(embed_zip) as z:
        z.extractall(py_dir)
    pth = next(py_dir.glob("python*._pth"))
    zip_name = next(py_dir.glob("python*.zip")).name
    pth.write_text(f"{zip_name}\n.\nLib\\site-packages\nimport site\n", encoding="utf-8")

    # 2. Librerías del entorno de desarrollo
    dest_sp = py_dir / "Lib" / "site-packages"
    dest_sp.mkdir(parents=True)
    for item in site_packages().iterdir():
        if skip(item.name):
            continue
        if item.is_dir():
            shutil.copytree(item, dest_sp / item.name, ignore=IGNORE_LIBS)
        else:
            shutil.copy2(item, dest_sp / item.name)
    print("Librerías copiadas")

    # 3. La app y los modelos
    app_dir = target / "app"
    app_dir.mkdir()
    for name in APP_ITEMS:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, app_dir / name, ignore=IGNORE)
        else:
            shutil.copy2(src, app_dir / name)
    models = Path(args.models)
    if models.is_dir():
        shutil.copytree(models, app_dir / "models", ignore=shutil.ignore_patterns(".cache"))
        print("Modelos incluidos:", ", ".join(p.name for p in models.iterdir()))
    else:
        print("Sin modelos incluidos (se descargarán al usarlos)")

    # 4. Lanzadores y LEEME
    (target / "Transcriptor.cmd").write_text(LAUNCHER, encoding="ascii")
    (target / "LEEME.txt").write_text(README, encoding="utf-8")

    # 5. Precompilado (.pyc). Instalada en "Archivos de programa" la app no puede escribirlos y
    #    recompilaría todo en cada arranque. "unchecked-hash": no se revalidan contra la fecha del .py.
    for folder in (dest_sp, app_dir):
        compileall.compile_dir(folder, quiet=2, workers=0,
                               invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    print("Precompilado listo")

    # 6. Licencias: la del proyecto, los avisos de terceros y la de cada librería incluida
    for name in LEGAL_FILES:
        shutil.copy2(ROOT / name, target / name)
    write_third_party_licenses(dest_sp, target / "THIRD-PARTY-LICENSES.txt")

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"Listo: {target}  ({size / 2**30:.2f} GB)")

    if args.zip:
        archive = shutil.make_archive(str(out_root / "Transcriptor-portable"), "zip",
                                      target.parent, target.name)
        print("Zip:", archive, f"({Path(archive).stat().st_size / 2**30:.2f} GB)")
        # Huella para que quien lo descargue compruebe que llegó completo y sin alterar:
        #   Get-FileHash Transcriptor-portable.zip  (PowerShell)
        digest = sha256(archive)
        Path(archive + ".sha256").write_text(f"{digest}  {Path(archive).name}\n", encoding="ascii")
        print("SHA-256:", digest)


if __name__ == "__main__":
    main()
