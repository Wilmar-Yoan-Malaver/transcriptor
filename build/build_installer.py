"""Arma el instalador MSI a partir de la carpeta portable (build_portable.py).

Requiere WiX Toolset 5 (`dotnet tool install --global wix --version 5.0.2`).

Uso:
    python build\\build_installer.py [--portable dist\\Transcriptor-portable] [--out dist]
"""

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WXS = ROOT / "installer" / "Transcriptor.wxs"


def app_version():
    """La versión de la app (desktop/app.py: VERSION = "x.y.z")."""
    source = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION = "(\d+\.\d+\.\d+)"', source, re.M)
    if not m:
        sys.exit("No se encontró VERSION en desktop/app.py")
    return m[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portable", default=str(ROOT / "dist" / "Transcriptor-portable"))
    ap.add_argument("--out", default=str(ROOT / "dist"))
    args = ap.parse_args()

    portable = Path(args.portable)
    if not (portable / "python" / "pythonw.exe").exists():
        sys.exit(f"No está la carpeta portable en {portable}: corre antes build_portable.py")
    wix = shutil.which("wix")
    if not wix:
        sys.exit("No se encontró WiX: dotnet tool install --global wix --version 5.0.2")

    version = app_version()
    msi = Path(args.out) / f"Transcriptor-{version}.msi"
    # Solo se ejecuta `wix` (encontrado en el PATH) con argumentos fijos.
    subprocess.run([wix, "build", str(WXS), "-arch", "x64", "-d", f"Version={version}",
                    "-bindpath", f"app={portable}", "-o", str(msi)], check=True)
    msi.with_suffix(".wixpdb").unlink(missing_ok=True)  # símbolos de depuración: no se publican

    digest = hashlib.sha256(msi.read_bytes()).hexdigest()
    msi.with_name(msi.name + ".sha256").write_text(f"{digest}  {msi.name}\n", encoding="ascii")
    print(f"MSI: {msi} ({msi.stat().st_size / 2**30:.2f} GB)\nSHA-256: {digest}")


if __name__ == "__main__":
    main()
