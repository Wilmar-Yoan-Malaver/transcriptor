"""Transcriptor: ventana principal (pywebview + HTML/CSS), barra flotante, borde y motor.

La interfaz vive en ui/ y conversa con Python por `window.pywebview.api`.
El motor (engine/engine.py) corre en otro proceso con prioridad baja, así Whisper
no le quita fluidez al resto del PC.
"""

import json
import os
import subprocess
import sys
import threading
import time
import winsound
from datetime import datetime
from pathlib import Path

import webview

import winutil
from overlay import BorderOverlay

FROZEN = getattr(sys, "frozen", False)  # empaquetado con PyInstaller
# Archivos de la app (ui/, engine/): junto al código o dentro del paquete.
ROOT = Path(sys._MEIPASS) if FROZEN else Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
ENGINE = ROOT / "engine" / "engine.py"
# Modelos de Whisper incluidos: carpeta models/ junto al .exe o junto a la app.
MODELS = (Path(sys.executable).parent if FROZEN else ROOT) / "models"
DATA = Path(os.environ["APPDATA"]) / "Transcriptor"
CONFIG_FILE = DATA / "config.json"
ENGINE_LOG = DATA / "engine.log"
VERSION = "2.0.0"

TITLE = "Transcriptor"
BAR_TITLE = "Transcriptor · grabando"
BAR_SIZE, BAR_COMPACT = (500, 62), (250, 62)
NO_WINDOW, BELOW_NORMAL = 0x08000000, 0x00004000
MEDIA_EXT = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".mp3", ".m4a", ".wav"}


def glob_escape(name):
    """Escapa [ ] * ? para usar un nombre de archivo literal en glob."""
    return "".join(f"[{c}]" if c in "[]*?" else c for c in name)

DEFAULTS = {
    "outputDir": str(Path.home() / "Documents" / "Transcripciones"),
    "captureKind": "monitor",      # monitor | window | audio
    "monitorIndex": 0,
    "audioMode": "both",           # both | sys | mic | none
    "speaker": None,
    "mic": None,
    "fps": 30,
    "quality": "1080p",
    "showCursor": True,
    "showBorder": True,
    "hideOnRecord": True,
    "playSounds": True,
    "liveTranscription": True,
    "liveModel": "base",
    "autoTranscribe": True,
    "model": "small",
    "language": "",
    "timestamps": True,
    "vad": False,
    "barPos": None,                # posición de la barra flotante [x, y]
}


class Config(dict):
    def __init__(self):
        super().__init__(DEFAULTS)
        try:
            self.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001 (sin archivo o dañado: valores por defecto)
            pass

    def save(self):
        DATA.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8")


class Engine:
    """Proceso del motor: órdenes JSON por stdin, eventos JSON por stdout."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.proc = None
        self.ready = False
        self._lock = threading.Lock()

    def start(self):
        self.stop()
        DATA.mkdir(parents=True, exist_ok=True)
        log = open(ENGINE_LOG, "w", encoding="utf-8")
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        if MODELS.is_dir():
            env["TRANSCRIPTOR_MODELS"] = str(MODELS)
        if FROZEN:
            # El mismo .exe hace de motor cuando recibe --engine.
            cmd, cwd = [sys.executable, "--engine"], str(Path(sys.executable).parent)
        else:
            python = Path(sys.executable).with_name("python.exe")
            cmd = [str(python if python.exists() else sys.executable), "-u", str(ENGINE)]
            cwd = str(ENGINE.parent)
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                     cwd=cwd, env=env, creationflags=NO_WINDOW | BELOW_NORMAL)
        self.ready = False
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            if ev.get("type") == "ready":
                self.ready = True
            self.on_event(ev)
        if proc is self.proc:
            self.ready = False
            self.on_event({"type": "engine_stopped"})

    def send(self, msg):
        proc = self.proc
        if not proc or proc.poll() is not None:
            return False
        with self._lock:
            try:
                proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
                proc.stdin.flush()
                return True
            except OSError:
                return False

    def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            try:
                with self._lock:
                    proc.stdin.write(b'{"cmd":"shutdown"}\n')
                    proc.stdin.flush()
                proc.wait(20)  # si había grabación, el motor la guarda antes de salir
            except Exception:  # noqa: BLE001
                proc.kill()


class App:
    def __init__(self):
        self.cfg = Config()
        self.engine = Engine(self.on_event)
        self.main = None
        self.bar = None
        self.overlay = None
        self.rec_state = "idle"     # idle | starting | recording | paused | saving
        self.rec_source = None
        self.rec_flags = {}
        self.closing = False
        self.status = "Iniciando motor…"
        self.monitors, self.devices = [], {}

    # ------------------------------------------------------------- utilidades
    def js(self, window, fn, payload=None):
        if window is None:
            return
        try:
            window.evaluate_js(f"window.{fn} && window.{fn}({json.dumps(payload, ensure_ascii=False)})")
        except Exception:  # noqa: BLE001 (ventana cerrándose)
            pass

    def play(self, start):
        if not self.cfg["playSounds"]:
            return
        wav = Path(os.environ["WINDIR"]) / "Media" / ("Speech On.wav" if start else "Speech Off.wav")
        try:
            winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC)
        except RuntimeError:
            pass

    # ------------------------------------------------------- eventos del motor
    def on_event(self, ev):
        t = ev.get("type")
        if t == "status" and not self.engine.ready:
            self.status = ev.get("text", "")
        elif t == "ready":
            self.status = "Motor listo"
            self.engine.send({"cmd": "list_devices"})
            self.engine.send({"cmd": "list_monitors"})
        elif t == "engine_stopped":
            self.status = "El motor se detuvo"
        elif t == "devices":
            self.devices = ev
            if self.cfg["speaker"] not in ev["speakers"]:
                self.cfg["speaker"] = ev["default_speaker"]
            if self.cfg["mic"] not in ev["mics"]:
                self.cfg["mic"] = ev["default_mic"]
            self.cfg.save()
        elif t == "monitors":
            self.monitors = ev["monitors"]
        elif t == "rec_started":
            self._on_rec_started(ev)
        elif t == "rec_levels" and self.bar:
            self.js(self.bar, "update", ev)
        elif t == "rec_audio":
            self.rec_flags.update(ev["audio"])
            self.js(self.bar, "setAudio", ev["audio"])
        elif t in ("rec_paused", "rec_resumed"):
            paused = t == "rec_paused"
            self.rec_state = "paused" if paused else "recording"
            self.js(self.bar, "setPaused", paused)
            if self.overlay:
                self.overlay.set_paused(paused)
        elif t == "rec_source_closed" and self.overlay:
            self.overlay.close()
            self.overlay = None
        elif t == "rec_saving":
            self.rec_state = "saving"
            self.js(self.bar, "setSaving")
        elif t in ("rec_saved", "rec_discarded", "rec_error"):
            self._end_recording_ui()
            if t == "rec_saved":
                self.play(start=False)
            if self.closing:
                self.main.destroy()
                return
        self.js(self.main, "onEngine", ev)

    # ---------------------------------------------------------------- grabación
    def start_recording(self, source):
        if self.rec_state != "idle":
            return {"error": "Ya hay una grabación en curso."}
        if not self.engine.ready:
            return {"error": "El motor todavía se está iniciando…"}
        c = self.cfg
        if source and source.get("kind") == "window" and not winutil.is_window(source["hwnd"]):
            return {"error": "Esa ventana ya se cerró. Elige otra."}
        speaker_on = bool(c["speaker"]) and c["audioMode"] in ("both", "sys")
        mic_on = bool(c["mic"]) and c["audioMode"] in ("both", "mic")
        if not source and not (speaker_on or mic_on):
            return {"error": "Con «Solo audio» elige al menos el micrófono o el audio del sistema."}

        self.rec_state, self.rec_source = "starting", source
        live = bool(c["liveTranscription"])
        self.rec_flags = {"mic": mic_on, "sys": speaker_on, "live": live}
        if c["playSounds"]:
            self.play(start=True)
            time.sleep(0.45)  # que el sonido no quede dentro de la grabación
        # Se envían ambos dispositivos: el que no arranca activo se puede activar durante la grabación.
        self.engine.send({"cmd": "start_recording", "out_dir": c["outputDir"], "source": source,
                          "speaker": c["speaker"], "mic": c["mic"],
                          "speaker_on": speaker_on, "mic_on": mic_on,
                          "fps": c["fps"], "quality": c["quality"], "cursor": c["showCursor"],
                          "live": live, "live_model": c["liveModel"], "language": c["language"]})
        return {"ok": True}

    def toggle_audio(self, key):
        """Activa o silencia el micrófono ("mic") o el audio del sistema ("sys") en plena grabación."""
        if self.rec_state in ("recording", "paused") and key in ("mic", "sys"):
            self.engine.send({"cmd": "set_audio", "source": key, "on": not self.rec_flags.get(key)})

    def drag_bar(self):
        """Mueve la barra flotante siguiendo al mouse mientras el botón esté presionado."""
        bar = self.bar
        if not bar:
            return
        h = winutil.hwnd_of(bar)
        sx, sy = winutil.cursor_pos()
        left, top, _r, _b = winutil.outer_rect(h)
        while winutil.left_button_down() and self.bar is bar:
            x, y = winutil.cursor_pos()
            winutil.move_topmost(h, left + x - sx, top + y - sy)
            time.sleep(0.008)
        if self.bar is bar:
            self.cfg["barPos"] = list(winutil.outer_rect(h)[:2])
            self.cfg.save()

    def _on_rec_started(self, ev):
        self.rec_state = "recording"
        self.rec_flags.update(ev.get("audio", {}))
        src = self.rec_source
        if src and src["kind"] == "monitor":
            area = winutil.work_area_for((src["left"], src["top"], src["left"] + src["width"],
                                          src["top"] + src["height"]))
        elif src and (r := winutil.window_rect(src["hwnd"])):
            area = winutil.work_area_for(r)
        else:
            area = winutil.primary_work_area()

        self.bar = webview.create_window(
            BAR_TITLE, url=str(UI / "bar.html"), js_api=BarApi(self), width=BAR_SIZE[0],
            height=BAR_SIZE[1], frameless=True, easy_drag=False, on_top=True, resizable=False,
            background_color="#161B22", focus=False)

        def setup_bar(bar=self.bar):
            h = winutil.hwnd_of(bar)
            winutil.exclude_from_capture(h)
            winutil.round_corners(h)
            winutil.make_tool_window(h)
            pos = self.cfg.get("barPos")
            if pos and winutil.point_on_screen(pos[0] + 20, pos[1] + 20):
                winutil.move_topmost(h, *pos)  # donde la dejaste la última vez
            else:
                l, _t, r, _b = winutil.outer_rect(h)
                winutil.move_topmost(h, area[0] + (area[2] - area[0] - (r - l)) // 2, area[1] + 8)

        self.bar.events.shown += setup_bar
        self.bar.events.loaded += lambda bar=self.bar: self.js(bar, "init", self.rec_flags)

        if self.cfg["showBorder"] and src:
            if src["kind"] == "monitor":
                self.overlay = BorderOverlay(rect=(src["left"], src["top"], src["left"] + src["width"],
                                                   src["top"] + src["height"]))
            else:
                self.overlay = BorderOverlay(target_hwnd=src["hwnd"])

        # Con transcripción en vivo la app queda a la vista para leer el texto.
        if self.cfg["hideOnRecord"] and not ev.get("live"):
            self.main.minimize()

    def _end_recording_ui(self):
        self.rec_state = "idle"
        if self.bar:
            bar, self.bar = self.bar, None
            try:
                bar.destroy()
            except Exception:  # noqa: BLE001
                pass
        if self.overlay:
            self.overlay.close()
            self.overlay = None
        try:
            self.main.restore()
        except Exception:  # noqa: BLE001
            pass

    def pause_or_resume(self):
        if self.rec_state == "recording":
            self.engine.send({"cmd": "pause_recording"})
        elif self.rec_state == "paused":
            self.engine.send({"cmd": "resume_recording"})

    def stop_recording(self, discard=False):
        if self.rec_state in ("recording", "paused"):
            self.engine.send({"cmd": "stop_recording", "discard": discard})

    # ------------------------------------------------------------------ cierre
    def on_closing(self):
        if self.rec_state in ("recording", "paused"):
            if self.main.create_confirmation_dialog(
                    "Transcriptor", "Hay una grabación en curso. ¿Detenerla, guardarla y salir?"):
                self.closing = True
                self.stop_recording()
            return False
        if self.rec_state == "saving":
            self.closing = True
            return False
        return True

    def on_closed(self):
        if self.overlay:
            self.overlay.close()
        if self.bar:
            try:
                self.bar.destroy()
            except Exception:  # noqa: BLE001
                pass
        self.engine.stop()

    def run(self):
        self.main = webview.create_window(
            TITLE, url=str(UI / "index.html"), js_api=Api(self), width=1180, height=820,
            min_size=(1000, 700), background_color="#0D1117")
        self.main.events.shown += lambda: winutil.style_titlebar(winutil.hwnd_of(self.main))
        self.main.events.closing += self.on_closing
        self.main.events.closed += self.on_closed
        webview.start(self.engine.start, gui="edgechromium", private_mode=False,
                      storage_path=str(DATA / "webview"), icon=str(UI / "icon.ico"))


class BarApi:
    """Lo que puede pedir la barra flotante."""

    def __init__(self, app):
        self._app = app

    def pause(self):
        self._app.pause_or_resume()

    def stop(self):
        self._app.stop_recording()

    def cancel(self):
        app = self._app
        if app.bar and app.bar.create_confirmation_dialog(
                "Descartar grabación", "¿Descartar esta grabación? No se guardará nada."):
            app.stop_recording(discard=True)

    def compact(self, on):
        w, h = BAR_COMPACT if on else BAR_SIZE
        if self._app.bar:
            self._app.bar.resize(w, h)

    def show_app(self):
        self._app.main.restore()

    def toggle_audio(self, key):
        self._app.toggle_audio(key)

    def begin_drag(self):
        self._app.drag_bar()


class Api:
    """Lo que puede pedir la interfaz principal (window.pywebview.api.*)."""

    def __init__(self, app):
        self._app = app

    # ---------------------------------------------------------------- estado
    def init(self):
        a = self._app
        return {"config": dict(a.cfg), "ready": a.engine.ready, "status": a.status,
                "monitors": a.monitors, "devices": a.devices, "recState": a.rec_state,
                "version": VERSION, "engine": str(ENGINE), "python": sys.executable}

    def set_config(self, key, value):
        if key in DEFAULTS:
            self._app.cfg[key] = value
            self._app.cfg.save()

    def reset_config(self):
        keep = {k: self._app.cfg[k] for k in ("speaker", "mic")}
        self._app.cfg.clear()
        self._app.cfg.update({**DEFAULTS, **keep})
        self._app.cfg.save()
        return dict(self._app.cfg)

    def send(self, msg):
        return self._app.engine.send(msg)

    def toggle_audio(self, key):
        self._app.toggle_audio(key)

    def restart_engine(self):
        if self._app.rec_state != "idle":
            return {"error": "Termina la grabación antes de reiniciar el motor."}
        self._app.status = "Iniciando motor…"
        self._app.engine.start()
        return {"ok": True}

    # ------------------------------------------------------------- grabación
    def start_recording(self, source):
        return self._app.start_recording(source)

    def pause(self):
        self._app.pause_or_resume()

    def stop(self):
        self._app.stop_recording()

    def cancel(self):
        if self._app.main.create_confirmation_dialog(
                "Descartar grabación", "¿Descartar esta grabación? No se guardará nada."):
            self._app.stop_recording(discard=True)

    # ---------------------------------------------------------- diálogos
    def pick_folder(self):
        r = self._app.main.create_file_dialog(webview.FileDialog.FOLDER,
                                              directory=self._app.cfg["outputDir"])
        return r[0] if r else None

    def pick_media(self):
        r = self._app.main.create_file_dialog(
            webview.FileDialog.OPEN,
            file_types=("Video o audio (*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4a;*.mp3;*.wav;*.ogg;*.flac)",
                        "Todos los archivos (*.*)"))
        return r[0] if r else None

    # ------------------------------------------------------------- archivos
    def history(self):
        folder = Path(self._app.cfg["outputDir"])
        groups = {}
        if folder.is_dir():
            for f in folder.iterdir():
                if f.is_file():
                    groups.setdefault(f.stem.lower(), []).append(f)
        items = []
        for files in groups.values():
            media = next((f for f in files if f.suffix.lower() in MEDIA_EXT), None)
            txt = next((f for f in files if f.suffix.lower() == ".txt"), None)
            if not media and not txt:
                continue
            main = media or txt
            st = main.stat()
            items.append({"name": main.stem, "media": str(media) if media else None,
                          "txt": str(txt) if txt else None, "size": st.st_size,
                          "date": datetime.fromtimestamp(st.st_mtime).isoformat(),
                          "audioOnly": bool(media and media.suffix.lower() in {".mp3", ".m4a", ".wav"})})
        items.sort(key=lambda i: i["date"], reverse=True)
        return {"folder": str(folder), "items": items}

    def file_info(self, path):
        p = Path(path)
        if not p.exists():
            return None
        txt = p.with_name(p.stem + ".txt")
        return {"created": datetime.fromtimestamp(p.stat().st_ctime).isoformat(),
                "txt": str(txt) if txt.exists() else None}

    def read_text(self, path):
        return Path(path).read_text(encoding="utf-8", errors="replace")

    def rename(self, path, new_name):
        p = Path(path)
        clean = "".join("_" if c in '<>:"/\\|?*' else c for c in new_name).strip(" .")
        if not clean:
            return {"error": "El nombre no puede quedar vacío."}
        target = p.with_name(clean + p.suffix)
        if target.exists() and not os.path.samefile(target, p):  # mismo archivo = solo cambió mayúsculas
            return {"error": "Ya existe un archivo con ese nombre."}
        try:
            p.rename(target)
            for ext in (".txt", ".srt"):  # la transcripción acompaña al video
                side = p.with_name(p.stem + ext)
                if side.exists():
                    side.rename(target.with_name(target.stem + ext))
        except OSError as e:
            return {"error": f"No se pudo renombrar: {e}"}
        self._app.engine.send({"cmd": "live_moved", "old": str(p), "new": str(target)})
        return {"path": str(target)}

    def delete_recording(self, path):
        """Envía a la Papelera la grabación y su transcripción (.txt/.srt) con el mismo nombre."""
        p = Path(path)
        files = [f for f in p.parent.glob(f"{glob_escape(p.stem)}.*")
                 if f.stem.lower() == p.stem.lower() and f.suffix.lower() in MEDIA_EXT | {".txt", ".srt"}]
        if not files:
            return {"error": "El archivo ya no existe."}
        if not winutil.send_to_recycle_bin(files):
            return {"error": "No se pudo eliminar (¿está abierto en otro programa?)."}
        return {"deleted": [f.name for f in files]}

    def open_path(self, path):
        os.startfile(path)

    def reveal(self, path):
        p = Path(path)
        if p.is_file():
            subprocess.Popen(["explorer.exe", f"/select,{p}"])
        else:
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(p)

    def create_shortcuts(self):
        """Accesos directos en el Escritorio y en el menú Inicio que apuntan a esta copia de la app."""
        if FROZEN:
            target, args = Path(sys.executable), ""
        else:
            target = Path(sys.executable).with_name("pythonw.exe")
            args = f'"{ROOT / "Transcriptor.pyw"}"'
        q = lambda s: str(s).replace("'", "''")  # comillas simples para PowerShell
        script = "".join(
            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
            f"[Environment]::GetFolderPath('{folder}')+'\\Transcriptor.lnk');"
            f"$s.TargetPath='{q(target)}';$s.Arguments='{q(args)}';$s.WorkingDirectory='{q(ROOT)}';"
            f"$s.IconLocation='{q(UI / 'icon.ico')},0';$s.Description='Graba, transcribe y comparte';$s.Save();"
            for folder in ("Desktop", "Programs"))
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script], creationflags=NO_WINDOW)
        return r.returncode == 0

    def open_log(self):
        if ENGINE_LOG.exists():
            os.startfile(ENGINE_LOG)

    def copy_text(self, text):
        return winutil.copy_text(text)

    def copy_file(self, path):
        """Deja el archivo en el portapapeles para pegarlo en Teams, WhatsApp, correo…"""
        lit = path.replace("'", "''")
        r = subprocess.run(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -LiteralPath '{lit}'"],
                           creationflags=NO_WINDOW)
        return r.returncode == 0


if __name__ == "__main__":
    App().run()
