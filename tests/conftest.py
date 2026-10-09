"""Configuración común de las pruebas: rutas de los módulos de la app."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

for folder in ("engine", "desktop"):
    sys.path.insert(0, str(ROOT / folder))

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
