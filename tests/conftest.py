"""Configuración común de las pruebas: rutas de los módulos de la app."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

for folder in ("engine", "desktop"):
    sys.path.insert(0, str(ROOT / folder))

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


@pytest.fixture(autouse=True)
def private_tempdir(tmp_path_factory, monkeypatch):
    """Las carpetas que la app crea con `tempfile` (la grabadora crea "reunion_*") van a una
    carpeta propia de pytest, que él mismo limpia, y no al %TEMP% del usuario."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path_factory.mktemp("app-temp")))
