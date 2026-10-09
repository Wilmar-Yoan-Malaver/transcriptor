"""Servidor del motor: recibe órdenes JSON (una por línea) por stdin y emite eventos por stdout.

La interfaz (WPF) lanza este proceso y se comunica solo por este canal.
"""

import json
import os
import sys
import threading
import time
import traceback
from pathlib import Path

# El Python "embeddable" (versión portable) no agrega la carpeta del script a sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# El canal stdout queda reservado para el protocolo; cualquier print/aviso de librerías
# (incluido código nativo) se redirige a stderr.
_proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
os.dup2(2, 1)
sys.stdout = sys.stderr

_lock = threading.Lock()


def emit(kind, **data):
    line = json.dumps({"type": kind, **data}, ensure_ascii=False)
    with _lock:
        _proto.write(line + "\n")
        _proto.flush()


emit("status", text="Cargando motor…")
import core  # noqa: E402  (importación lenta: Whisper, OpenCV…)


class Engine:
    def __init__(self):
        self.recorder = None
        self.live = None
        self.last_live = None
        self.rec_lock = threading.Lock()
        self.transcriber = core.Transcriber()
        self.tx_thread = None
        self.tx_cancel = threading.Event()

    # ---------------------------------------------------- fuentes y dispositivos
    def list_sources(self, msg):
        monitors = core.list_monitors()
        windows = core.list_windows(msg.get("exclude", []))
        emit("sources", monitors=monitors, windows=windows)

        def thumbs():
            for src in monitors + windows:
                key = f"{src['kind']}:{src.get('index') or src.get('hwnd')}"
                try:
                    png = core.thumbnail(src)
                except Exception:  # noqa: BLE001
                    png = None
                emit("thumb", key=key, png=png)

        threading.Thread(target=thumbs, daemon=True).start()

    def list_monitors(self, _msg):
        emit("monitors", monitors=core.list_monitors())

    def list_devices(self, _msg):
        emit("devices", **core.list_devices())

    # ---------------------------------------------------------------- grabación
    def start_recording(self, msg):
        with self.rec_lock:
            if self.recorder:
                emit("rec_error", message="Ya hay una grabación en curso.")
                return
            # speaker/mic = dispositivos; speaker_on/mic_on = si arrancan activos (se pueden
            # activar o silenciar después con set_audio).
            rec = core.MeetingRecorder(msg["out_dir"], msg.get("source"), msg.get("speaker"),
                                       msg.get("mic"), int(msg.get("fps", 15)),
                                       msg.get("quality", "1080p"), bool(msg.get("cursor", True)),
                                       speaker_on=msg.get("speaker_on", True),
                                       mic_on=msg.get("mic_on", True))
            try:
                rec.start()
            except Exception as e:  # noqa: BLE001
                rec.stop(discard=True)
                rec.cleanup()
                emit("rec_error", message=f"No se pudo iniciar la grabación: {e}")
                return
            self.recorder = rec
            self.live = None
            # En vivo arranca aunque no haya audio todavía: se puede activar el micrófono después.
            if msg.get("live"):
                self.live = core.LiveTranscriber(
                    rec, self.transcriber, model=msg.get("live_model", "base"),
                    language=msg.get("language") or None,
                    on_segment=lambda s, e, t: emit("live_segment", start=round(s, 2),
                                                    end=round(e, 2), text=t),
                    on_status=lambda t: emit("live_status", text=t))
                self.live.start()
        emit("rec_started", live=self.live is not None, audio=rec.active)
        threading.Thread(target=self._levels_loop, args=(rec,), daemon=True).start()

    def _levels_loop(self, rec):
        warned, errors, audio = False, 0, rec.active
        while self.recorder is rec:
            emit("rec_levels", mic=round(rec.levels.get("mic", -1), 3),
                 sys=round(rec.levels.get("sys", -1), 3), elapsed=round(rec.elapsed(), 2))
            if rec.source_closed and not warned:
                warned = True
                emit("rec_source_closed")
            # Un dispositivo que falla en plena grabación se informa al momento.
            while errors < len(rec.errors):
                emit("warning", message=rec.errors[errors])
                errors += 1
            if rec.active != audio:
                audio = rec.active
                emit("rec_audio", audio=audio)
            time.sleep(0.15)

    def set_audio(self, msg):
        """Activa o silencia el micrófono ("mic") o el audio del sistema ("sys") mientras se graba."""
        rec = self.recorder
        if not rec:
            return
        key = msg["source"]
        try:
            rec.set_source(key, bool(msg["on"]))  # el cambio lo anuncia _levels_loop (rec_audio)
        except Exception as e:  # noqa: BLE001
            what = "el micrófono" if key == "mic" else "el audio del sistema"
            emit("warning", message=f"No se pudo activar {what}: {e}")
            emit("rec_audio", audio=rec.active)  # para que la interfaz vuelva al estado real

    def pause_recording(self, _msg):
        if self.recorder:
            self.recorder.pause()
            emit("rec_paused")

    def resume_recording(self, _msg):
        if self.recorder:
            self.recorder.resume()
            emit("rec_resumed")

    def stop_recording(self, msg):
        discard = bool(msg.get("discard"))
        with self.rec_lock:
            rec, self.recorder = self.recorder, None
            live, self.live = self.live, None
        if not rec:
            return
        emit("rec_saving")

        def finish():
            try:
                mp4 = rec.stop(discard=discard)
                for err in rec.errors:
                    emit("warning", message=err)
                live_segments = []
                if live:
                    if not discard:
                        emit("live_status", text="Terminando la transcripción en vivo…")
                    live_segments = live.finish()
                if discard:
                    emit("rec_discarded")
                elif mp4:
                    self.last_live = {"path": str(mp4), "segments": live_segments}
                    emit("rec_saved", live_segments=len(live_segments), **core.media_info(mp4))
                else:
                    emit("rec_error", message="No se grabó nada.")
            except Exception as e:  # noqa: BLE001
                emit("rec_error", message=str(e))
            finally:
                rec.cleanup()

        threading.Thread(target=finish, daemon=True).start()

    # ------------------------------------------------------------ transcripción
    def transcribe(self, msg):
        self._run_tx(msg, lambda: (msg["path"], msg.get("title") or Path(msg["path"]).stem, None))

    def youtube(self, msg):
        def fetch():
            emit("tx_status", text="Conectando con YouTube…", job=msg.get("job"))
            path, title, tmp = core.download_youtube(
                msg["url"], lambda pct: emit("tx_download", pct=round(pct, 1), job=msg.get("job")))
            return path, title, tmp

        self._run_tx(msg, fetch)

    def _run_tx(self, msg, get_source):
        if self.tx_thread and self.tx_thread.is_alive():
            emit("tx_error", message="Ya hay una transcripción en curso.", job=msg.get("job"))
            return
        self.tx_cancel.clear()
        job = msg.get("job")

        def run():
            tmp = None
            try:
                path, title, tmp = get_source()
                emit("tx_started", title=title, job=job, source=str(path))
                txt, srt, duration = self.transcriber.transcribe(
                    path, title, msg["out_dir"], model=msg.get("model", "small"),
                    language=msg.get("language") or None, vad=bool(msg.get("vad")),
                    timestamps=bool(msg.get("timestamps", True)),
                    status=lambda t: emit("tx_status", text=t, job=job),
                    progress=lambda pct, eta, lang: emit("tx_progress", pct=round(pct, 1),
                                                         eta=round(eta), language=lang, job=job),
                    segment=lambda line: emit("tx_segment", line=line, job=job),
                    cancel=self.tx_cancel)
                self._live_resolved(path)
                emit("tx_done", txt=str(txt), srt=str(srt), duration=duration, title=title, job=job)
            except core.Canceled:
                emit("tx_canceled", job=job)
            except core.NoSpeech:
                emit("tx_nospeech", job=job)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                emit("tx_error", message=str(e), job=job)
            finally:
                if tmp:
                    import shutil
                    shutil.rmtree(tmp, ignore_errors=True)

        self.tx_thread = threading.Thread(target=run, daemon=True)
        self.tx_thread.start()

    def cancel_transcription(self, _msg):
        self.tx_cancel.set()

    def save_live(self, msg):
        """Guarda como .txt/.srt lo que se transcribió en vivo durante la última grabación."""
        last = self.last_live
        if not last or last["path"] != msg["path"]:
            emit("tx_error", message="Ya no está disponible la transcripción en vivo.", job=msg.get("job"))
            return
        path = Path(last["path"])
        txt, srt = core.write_transcript(path.parent, path.stem, last["segments"],
                                         bool(msg.get("timestamps", True)))
        last["saved"] = True
        emit("tx_done", txt=str(txt), srt=str(srt), duration=0, title=path.stem, job=msg.get("job"))

    def live_moved(self, msg):
        """La grabación cambió de nombre: la transcripción en vivo pendiente la sigue."""
        if self.last_live and self.last_live["path"] == msg["old"]:
            self.last_live["path"] = msg["new"]

    def _live_resolved(self, path):
        """Ya hay una transcripción guardada para esa grabación: el texto en vivo no hace falta."""
        if self.last_live and Path(self.last_live["path"]) == Path(path):
            self.last_live["saved"] = True

    def save_pending_live(self, segments=None, path=None):
        """Al cerrar la app: guarda el texto en vivo que nadie guardó, para no perderlo.

        Usa el nombre que tenga la grabación en ese momento (por defecto, la fecha) y no
        pisa una transcripción que ya exista.
        """
        if segments is None:
            last = self.last_live
            if not last or last.get("saved") or not last["segments"]:
                return
            segments, path = last["segments"], last["path"]
        path = Path(path)
        if segments and path.exists() and not path.with_name(path.stem + ".txt").exists():
            core.write_transcript(path.parent, path.stem, segments, True)

    # -------------------------------------------------------------------- otros
    def media_info(self, msg):
        def run():
            try:
                emit("media_info", req=msg.get("req"), **core.media_info(msg["path"]))
            except Exception as e:  # noqa: BLE001
                emit("media_info", req=msg.get("req"), path=msg["path"], error=str(e))

        threading.Thread(target=run, daemon=True).start()

    def window_closed_check(self, msg):
        emit("window_alive", hwnd=msg["hwnd"], alive=bool(core.user32.IsWindow(msg["hwnd"])))


def main():
    eng = Engine()
    emit("ready", ffmpeg=core.FFMPEG)
    # Se lee el descriptor 0 directo: en el .exe sin consola sys.stdin puede ser None.
    for raw in os.fdopen(os.dup(0), "rb"):
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get("cmd", "")
            if cmd == "shutdown":
                break
            handler = getattr(eng, cmd, None)
            if handler is None or cmd.startswith("_"):
                emit("error", message=f"Orden desconocida: {cmd}")
                continue
            handler(msg)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            emit("error", message=str(e))
    # Si la interfaz se cierra con una grabación en curso, se guarda antes de salir
    # (con el nombre por fecha), junto con lo que se haya transcrito en vivo.
    if eng.recorder:
        rec, eng.recorder = eng.recorder, None
        live, eng.live = eng.live, None
        try:
            mp4 = rec.stop()
            if live and mp4:
                eng.save_pending_live(live.finish(), mp4)
        finally:
            rec.cleanup()
    try:
        eng.save_pending_live()
    except Exception:  # noqa: BLE001
        traceback.print_exc()


if __name__ == "__main__":
    main()
