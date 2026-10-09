"""Punto de entrada de Transcriptor.

- Sin argumentos abre la app (interfaz HTML/CSS en una ventana nativa con pywebview).
- Con --engine arranca el motor; así funciona igual dentro del .exe de PyInstaller,
  donde no hay un python.exe aparte para lanzarlo.
"""

import sys
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path[:0] = [str(ROOT / "desktop"), str(ROOT / "engine")]

if "--engine" in sys.argv:
    import engine

    engine.main()
else:
    import app

    app.App().run()
