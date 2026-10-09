"""Motor de Transcriptor: captura de pantalla/ventanas, audio, YouTube y Whisper local."""

import base64
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
import wave
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# PyAV puede estar bloqueado por políticas de Windows. No lo necesitamos:
# el audio se decodifica con ffmpeg y se le pasa a Whisper como numpy.
try:
    import av  # noqa: F401
except Exception:
    sys.modules["av"] = types.ModuleType("av")

import imageio_ffmpeg
import soundcard as sc
from faster_whisper import WhisperModel
from windows_capture import WindowsCapture

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
NO_WINDOW = subprocess.CREATE_NO_WINDOW
SAMPLE_RATE = 16000
REC_RATE = 48000
QUALITY_LIMITS = {"original": None, "1080p": (1920, 1080), "720p": (1280, 720)}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


# ---------------------------------------------------------------- utilidades

def load_audio(path):
    """Decodifica cualquier audio/video a mono 16 kHz float32 usando ffmpeg."""
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-i", str(path),
           "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-"]
    proc = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="ignore").strip() or "ffmpeg falló")
    return np.frombuffer(proc.stdout, np.float32)


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def short_time(t):
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02}:{m:02}:{s:02}" if h else f"{m:02}:{s:02}"


def safe_name(name):
    """Solo reemplaza lo que Windows no permite, para que el .txt se llame igual que el video."""
    keep = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip(" .")
    return (keep or "transcripcion")[:120]


def png_b64(bgr, max_w):
    h, w = bgr.shape[:2]
    s = min(1.0, max_w / w)
    if s < 1.0:
        bgr = cv2.resize(bgr, (max(1, int(w * s)), max(1, int(h * s))),
                         interpolation=cv2.INTER_AREA)
    ok, png = cv2.imencode(".png", bgr)
    return base64.b64encode(png).decode() if ok else None


def media_info(path, thumb_width=480):
    """Duración, resolución, fps, tamaño y miniatura (PNG base64) de un archivo."""
    path = Path(path)
    p = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True,
                       text=True, errors="ignore", creationflags=NO_WINDOW)
    info = {"path": str(path), "size": path.stat().st_size if path.exists() else 0,
            "duration": 0.0, "width": 0, "height": 0, "fps": 0, "has_video": False,
            "thumb": None}
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    if m:
        info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
    m = re.search(r"Stream .*Video: .*?(\d{2,5})x(\d{2,5})", p.stderr)
    if m:
        info.update(has_video=True, width=int(m[1]), height=int(m[2]))
        f = re.search(r"([\d.]+) fps", p.stderr)
        info["fps"] = round(float(f[1])) if f else 0
        at = min(1.0, info["duration"] / 2)
        t = subprocess.run([FFMPEG, "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
                            "-frames:v", "1", "-vf", f"scale={thumb_width}:-2",
                            "-f", "image2pipe", "-vcodec", "png", "-"],
                           capture_output=True, creationflags=NO_WINDOW)
        if t.stdout:
            info["thumb"] = base64.b64encode(t.stdout).decode()
    return info


# ------------------------------------------------------- monitores y ventanas

class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


def list_monitors():
    """Monitores en el mismo orden que usa Windows Graphics Capture (índice desde 1)."""
    mons = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(hmon, _hdc, _rect, _lp):
        info = MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(info)
        user32.GetMonitorInfoW(hmon, ctypes.byref(info))
        r = info.rcMonitor
        mons.append((r.left, r.top, r.right - r.left, r.bottom - r.top, bool(info.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, proc(cb), 0)
    return [{"kind": "monitor", "index": i, "left": x, "top": y, "width": w, "height": h,
             "primary": primary,
             "label": f"Pantalla {i}  ({w}×{h})" + ("  · principal" if primary else "")}
            for i, (x, y, w, h, primary) in enumerate(mons, 1)]


def _process_name(hwnd):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return Path(buf.value).stem
        return ""
    finally:
        kernel32.CloseHandle(h)


def list_windows(exclude_titles=()):
    """Ventanas de aplicaciones visibles (como el selector de Chrome)."""
    wins = []
    dwm = ctypes.windll.dwmapi
    skip = {"Program Manager", *exclude_titles}

    def cb(hwnd, _lp):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, 4):  # con dueño
            return True
        if user32.GetWindowLongW(hwnd, -20) & 0x80:  # WS_EX_TOOLWINDOW
            return True
        cloaked = wintypes.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        if cloaked.value:
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value
        if title in skip:
            return True
        app = _process_name(hwnd)
        wins.append({"kind": "window", "hwnd": int(hwnd), "title": title, "app": app,
                     "minimized": bool(user32.IsIconic(hwnd)),
                     "label": f"{app}: {title}" if app else title})
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(cb), 0)
    return wins


def _wgc_kwargs(source):
    if source["kind"] == "monitor":
        return {"monitor_index": source["index"]}
    return {"window_hwnd": source["hwnd"]}


def grab_frame(source, timeout=2.0):
    """Toma una sola imagen (BGRA) de un monitor o ventana. None si no hay imagen."""
    got, done = {}, threading.Event()
    cap = WindowsCapture(cursor_capture=False, draw_border=False, **_wgc_kwargs(source))

    @cap.event
    def on_frame_arrived(frame, control):
        got["f"] = frame.frame_buffer.copy()
        done.set()
        control.stop()

    @cap.event
    def on_closed():
        done.set()

    ctl = cap.start_free_threaded()
    done.wait(timeout)
    try:
        ctl.stop()
    except Exception:  # noqa: BLE001
        pass
    return got.get("f")


def thumbnail(source, width=320):
    if source.get("minimized"):
        return None
    f = grab_frame(source, timeout=1.5)
    return None if f is None else png_b64(cv2.cvtColor(f, cv2.COLOR_BGRA2BGR), width)


# ------------------------------------------------------------- grabación

class ScreenCapture:
    """Graba un monitor o una ventana con Windows Graphics Capture → MP4 (ffmpeg).

    `clock()` devuelve los segundos grabados (sin contar pausas); el video escribe
    cuadros a ritmo constante según ese reloj para quedar sincronizado con el audio.
    """

    def __init__(self, source, out_path, clock, fps=15, quality="1080p", cursor=True):
        self.source, self.out_path, self.clock = source, Path(out_path), clock
        self.fps, self.limit, self.cursor = fps, QUALITY_LIMITS.get(quality), cursor
        self._lock = threading.Lock()
        self._latest = None
        self._stop = threading.Event()
        self._proc = None
        self._control = None
        self._writer = None
        self.error = None
        self.closed = threading.Event()

    def start(self):
        if self.source["kind"] == "window" and user32.IsIconic(self.source["hwnd"]):
            user32.ShowWindow(self.source["hwnd"], 9)  # SW_RESTORE
        cap = WindowsCapture(cursor_capture=self.cursor, draw_border=False,
                             minimum_update_interval=max(1, 1000 // self.fps),
                             **_wgc_kwargs(self.source))

        @cap.event
        def on_frame_arrived(frame, control):
            if self._stop.is_set():
                control.stop()
                return
            f = frame.frame_buffer.copy()
            with self._lock:
                self._latest = f

        @cap.event
        def on_closed():
            self.closed.set()

        self._control = cap.start_free_threaded()
        self._writer = threading.Thread(target=self._write_loop, daemon=True)
        self._writer.start()

    def _out_size(self, w, h):
        scale = 1.0
        if self.limit:
            scale = min(1.0, self.limit[0] / w, self.limit[1] / h)
        return int(w * scale) // 2 * 2, int(h * scale) // 2 * 2

    def _write_loop(self):
        n, size = 0, None
        try:
            while not self._stop.is_set():
                with self._lock:
                    f = self._latest
                if f is None:
                    time.sleep(0.02)
                    continue
                if self._proc is None:
                    size = self._out_size(f.shape[1], f.shape[0])
                    preset = "veryfast" if size[0] * size[1] <= 1920 * 1080 else "ultrafast"
                    cmd = [FFMPEG, "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                           "-s", f"{size[0]}x{size[1]}", "-framerate", str(self.fps),
                           "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", "26",
                           "-pix_fmt", "yuv420p", str(self.out_path)]
                    self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                                  stderr=subprocess.DEVNULL,
                                                  creationflags=NO_WINDOW)
                target = int(self.clock() * self.fps) + 1
                if n < target:
                    img = cv2.cvtColor(f, cv2.COLOR_BGRA2BGR)
                    if (img.shape[1], img.shape[0]) != size:
                        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
                    data = img.tobytes()
                    while n < target:
                        self._proc.stdin.write(data)
                        n += 1
                time.sleep(0.5 / self.fps)
        except Exception as e:  # noqa: BLE001
            self.error = f"Video: {e}"

    def stop(self):
        self._stop.set()
        try:
            self._control.stop()
        except Exception:  # noqa: BLE001
            pass
        if self._writer:
            self._writer.join(timeout=5)
        if self._proc:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=120)
            except Exception:  # noqa: BLE001
                self._proc.kill()
        return self.out_path if self.out_path.exists() else None


class MeetingRecorder:
    """Graba un monitor/ventana + audio del escritorio (loopback) + micrófono → un .mp4."""

    def __init__(self, out_dir, video_source=None, speaker_name=None, mic_name=None,
                 fps=15, quality="1080p", cursor=True, speaker_on=True, mic_on=True):
        """speaker_name/mic_name son los dispositivos; *_on indica si arrancan activos.
        Cualquiera de los dos se puede activar o silenciar después con set_source()."""
        self.out_dir = Path(out_dir)
        self.video_source = video_source
        self.speaker_name, self.mic_name = speaker_name, mic_name
        self.speaker_on, self.mic_on = bool(speaker_on and speaker_name), bool(mic_on and mic_name)
        self._muted, self._failed = set(), set()
        self._src_lock = threading.Lock()
        self.fps, self.quality, self.cursor = fps, quality, cursor
        self.tmp = Path(tempfile.mkdtemp(prefix="reunion_"))
        self.stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._pause_started = 0.0
        self._paused_total = 0.0
        self._t0 = 0.0
        self._threads, self._chunks, self._screen = [], {}, None
        self._live_pos = 0
        self.levels = {}
        self.errors = []

    # Reloj de grabación: segundos efectivos, sin contar pausas.
    def elapsed(self):
        if not self._t0:  # todavía no arrancó
            return 0.0
        now = self._pause_started if self._paused.is_set() else time.time()
        return max(0.0, now - self._t0 - self._paused_total)

    def start(self):
        self._t0 = time.time()
        if self.speaker_on:
            self.set_source("sys", True)
        if self.mic_on:
            self.set_source("mic", True)
        if self.video_source:
            self._screen = ScreenCapture(self.video_source, self.tmp / "video.mp4", self.elapsed,
                                         self.fps, self.quality, self.cursor)
            self._screen.start()

    @property
    def source_closed(self):
        return bool(self._screen and self._screen.closed.is_set())

    def pause(self):
        if not self._paused.is_set():
            self._pause_started = time.time()
            self._paused.set()

    def resume(self):
        if self._paused.is_set():
            self._paused_total += time.time() - self._pause_started
            self._paused.clear()

    @property
    def active(self):
        """Qué fuentes de audio se están grabando ahora (no silenciadas)."""
        return {k: k in self._chunks and k not in self._muted and k not in self._failed
                for k in ("mic", "sys")}

    def set_source(self, key, on):
        """Activa o silencia el micrófono ("mic") o el audio del sistema ("sys") en plena grabación.

        Silenciar graba silencio (el audio sigue alineado con el video). Si la fuente
        no se usaba desde el inicio, se abre ahora y se rellena con silencio hasta este
        momento para que quede sincronizada.
        """
        with self._src_lock:
            if not on:
                self._muted.add(key)
                self.levels[key] = 0.0
                return
            name = self.speaker_name if key == "sys" else self.mic_name
            if not name:
                raise RuntimeError("no hay un dispositivo elegido en Configuración › Audio")
            self._muted.discard(key)
            if key in self._chunks and key not in self._failed:
                return
            self._failed.discard(key)
            done = max((len(c) for k, c in self._chunks.items() if k != key),
                       default=int(self.elapsed() * 10))
            self._chunks[key] = [np.zeros(REC_RATE // 10, np.float32)] * done
            device = (sc.get_microphone(id=name, include_loopback=True) if key == "sys"
                      else sc.get_microphone(id=name))
            self._spawn(key, device)

    def _spawn(self, key, device):
        self._chunks.setdefault(key, [])
        self.levels[key] = 0.0
        t = threading.Thread(target=self._record, args=(key, device), daemon=True)
        t.start()
        self._threads.append(t)

    def _record(self, key, device):
        try:
            with device.recorder(samplerate=REC_RATE, channels=1) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=REC_RATE // 10).reshape(-1)
                    if self._paused.is_set():
                        self.levels[key] = 0.0
                        continue
                    if key in self._muted:
                        data = np.zeros_like(data)  # silenciado: silencio, pero sincronizado
                    self._chunks[key].append(data)
                    self.levels[key] = float(min(1.0, np.sqrt(np.mean(data ** 2)) * 6))
        except Exception as e:  # noqa: BLE001
            self._failed.add(key)
            self.errors.append(f"Audio {key}: {e}")

    def pull_live(self):
        """Audio nuevo (mezcla mono 48 kHz) desde la última llamada, para transcribir en vivo.

        Cada fuente guarda bloques de 100 ms; solo se toman los bloques que ya llegaron
        de todas las fuentes, así la mezcla queda alineada.
        """
        # Una fuente que falló deja de crecer: no debe frenar la transcripción en vivo.
        chunks = [c for k, c in self._chunks.items() if k not in self._failed]
        if not chunks:
            return None
        avail = min(len(c) for c in chunks)
        start = self._live_pos
        if avail <= start:
            return None
        parts = [np.concatenate(c[start:avail]) for c in chunks]
        n = min(len(p) for p in parts)
        self._live_pos = avail
        return sum(p[:n] for p in parts).astype(np.float32)

    def stop(self, discard=False):
        """Detiene todo. Devuelve la ruta del .mp4 final (o None si se descartó)."""
        self.resume()
        self._stop.set()
        raw_video = self._screen.stop() if self._screen else None
        if self._screen and self._screen.error:
            self.errors.append(self._screen.error)
        for t in self._threads:
            t.join(timeout=5)
        if discard:
            return None

        tracks = [np.concatenate(c) for c in self._chunks.values() if c]
        wav_path = None
        if tracks:
            n = max(len(t) for t in tracks)
            mix = sum(np.pad(t, (0, n - len(t))) for t in tracks)
            peak = float(np.abs(mix).max()) or 1.0
            if peak > 0.99:
                mix = mix / peak * 0.99
            wav_path = self.tmp / "audio.wav"
            with wave.open(str(wav_path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(REC_RATE)
                w.writeframes((mix * 32767).astype(np.int16).tobytes())

        if not (raw_video or wav_path):
            return None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        mp4_path = self.out_dir / f"Grabación {self.stamp}.mp4"
        if raw_video and not wav_path:
            shutil.move(str(raw_video), mp4_path)
        else:
            inputs = (["-i", str(raw_video)] if raw_video else []) + ["-i", str(wav_path)]
            vcodec = ["-c:v", "copy"] if raw_video else ["-vn"]
            cmd = [FFMPEG, "-y", "-v", "error", *inputs, *vcodec,
                   "-c:a", "aac", "-b:a", "128k", str(mp4_path)]
            r = subprocess.run(cmd, capture_output=True, creationflags=NO_WINDOW)
            if r.returncode != 0 or not mp4_path.exists() or mp4_path.stat().st_size == 0:
                return self._rescue(raw_video, wav_path, mp4_path, r.stderr)
        return mp4_path if mp4_path.exists() else None

    def _rescue(self, raw_video, wav_path, failed_mp4, stderr):
        """ffmpeg no pudo unir video y audio (disco lleno, archivo dañado…): se conservan los dos
        por separado en la carpeta de salida. Sin esto, cleanup() los borraría y se perdería todo."""
        detail = (stderr or b"").decode(errors="ignore").strip()[-300:]
        self.errors.append("No se pudo unir el video y el audio" + (f" ({detail})" if detail else "")
                           + ". Se guardaron por separado para no perder la grabación.")
        failed_mp4.unlink(missing_ok=True)  # pudo quedar a medias
        saved = []
        for src, suffix in ((raw_video, " (video).mp4"), (wav_path, " (audio).wav")):
            if src and Path(src).exists():
                target = self.out_dir / f"Grabación {self.stamp}{suffix}"
                shutil.move(str(src), target)
                saved.append(target)
        return saved[0] if saved else None

    def cleanup(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


def list_devices():
    speakers = [s.name for s in sc.all_speakers()]
    mics = [m.name for m in sc.all_microphones()]
    return {"speakers": speakers, "mics": mics,
            "default_speaker": sc.default_speaker().name if speakers else None,
            "default_mic": sc.default_microphone().name if mics else None}


# ------------------------------------------------------------ transcripción

class Canceled(Exception):
    pass


class NoSpeech(Exception):
    """El audio no tiene voz: no hay nada que transcribir."""


def has_speech(audio):
    """Revisión rápida (< 1 s) con el detector de voz de Whisper antes de transcribir.

    Umbral bajo a propósito: basta con encontrar algo de voz (incluido canto con música)
    para seguir. Así una grabación en silencio termina al instante en vez de dejar a
    Whisper reintentando cada tramo de 30 s sin resultado. Se exige al menos 1 s de voz
    en total para que un ruido suelto (teclado, un golpe) no cuente como habla.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    spans = get_speech_timestamps(audio, VadOptions(threshold=0.3, min_speech_duration_ms=200))
    return sum(s["end"] - s["start"] for s in spans) >= SAMPLE_RATE * 1.0


def model_source(name):
    """Carpeta del modelo incluido en el paquete (TRANSCRIPTOR_MODELS) o su nombre para descargarlo."""
    bundled = os.environ.get("TRANSCRIPTOR_MODELS")
    if bundled and (Path(bundled) / name / "model.bin").exists():
        return str(Path(bundled) / name)
    return name


class Transcriber:
    def __init__(self):
        self.models = {}
        self._lock = threading.Lock()

    def model(self, name, status, threads=0):
        """Modelos en caché por (nombre, hilos). threads=0 usa todos los núcleos."""
        key = (name, threads)
        with self._lock:
            if key not in self.models:
                source = model_source(name)
                status(f"Cargando el modelo «{name}»…" if source != name
                       else f"Cargando el modelo «{name}» (la primera vez se descarga)…")
                self.models[key] = WhisperModel(source, device="cpu", compute_type="int8",
                                                cpu_threads=threads)
            return self.models[key]

    def transcribe(self, path, title, out_dir, model="small", language=None, vad=False,
                   timestamps=True, status=print, progress=None, segment=None,
                   cancel=None):
        """Transcribe y guarda .txt y .srt. Devuelve (ruta_txt, ruta_srt, duración)."""
        cancel = cancel or threading.Event()  # uno nuevo por llamada (no compartido entre llamadas)
        m = self.model(model, status)
        status("Preparando audio…")
        audio = load_audio(path)
        duration = len(audio) / SAMPLE_RATE
        if duration < 0.5:
            raise RuntimeError("El archivo no tiene audio o es demasiado corto.")
        status("Buscando voz en el audio…")
        if not has_speech(audio):
            raise NoSpeech()

        status("Transcribiendo…")
        started = time.time()
        # El filtro VAD acelera audios con silencios, pero descarta voz cantada o con
        # música de fondo, así que es opcional. Menos reintentos por tramo (temperature)
        # para que las partes sin voz no frenen la transcripción.
        segments, info = m.transcribe(audio, language=language, vad_filter=vad, beam_size=5,
                                      temperature=(0.0, 0.2, 0.4))
        found = []
        last = {"t": time.time(), "pos": 0.0}
        done = threading.Event()

        def heartbeat():  # señal de vida mientras Whisper avanza por partes sin voz
            while not done.wait(2):
                quiet = time.time() - last["t"]
                if quiet > 6:
                    status(f"Transcribiendo… ({short_time(last['pos'])} de {short_time(duration)}) · "
                           f"hace {int(quiet)} s sin texto nuevo: partes sin voz o con ruido")

        threading.Thread(target=heartbeat, daemon=True).start()
        try:
            for seg in segments:
                if cancel.is_set():
                    raise Canceled()
                last.update(t=time.time(), pos=seg.end)
                found.append(self._segment(seg, timestamps, segment, progress, duration, started, info))
        finally:
            done.set()

        if not any(text for _s, _e, text in found):
            raise NoSpeech()  # nada que guardar: sin .txt vacíos marcados como "Transcrito"
        txt, srt = write_transcript(out_dir, title, found, timestamps)
        return txt, srt, duration

    @staticmethod
    def _segment(seg, timestamps, segment, progress, duration, started, info):
        text = seg.text.strip()
        if segment:
            segment(f"[{short_time(seg.start)}] {text}" if timestamps else text)
        if progress:
            pct = min(seg.end / duration * 100, 100)
            elapsed = time.time() - started
            progress(pct, elapsed / max(pct, 1) * (100 - pct), info.language)
        return seg.start, seg.end, text


def atomic_write_text(path, text):
    """Escribe todo o nada: primero un temporal y luego lo reemplaza de una vez (os.replace).
    Si la app se cierra a mitad, queda el archivo anterior intacto, nunca uno cortado."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def write_transcript(out_dir, title, segments, timestamps=True):
    """Guarda .txt y .srt a partir de [(inicio, fin, texto)]."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = safe_name(title)
    txt, srt = out_dir / f"{name}.txt", out_dir / f"{name}.srt"
    lines = [f"[{short_time(s)}] {t}" if timestamps else t for s, _e, t in segments]
    atomic_write_text(txt, "\n".join(lines) + "\n")
    atomic_write_text(srt, "\n".join(f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{t}\n"
                                     for i, (s, e, t) in enumerate(segments, 1)))
    return txt, srt


class LiveTranscriber:
    """Transcribe mientras se graba.

    Junta el audio nuevo y lo corta en una pausa natural (o cada ~12 s si nadie se
    calla), lo transcribe con un modelo rápido y entrega cada frase con su tiempo
    dentro de la grabación.
    """

    MIN_SECONDS, MAX_SECONDS, TAIL = 3.0, 12.0, 0.6

    def __init__(self, recorder, transcriber, model="base", language=None, on_segment=None,
                 on_status=None, threads=None):
        self.rec, self.transcriber = recorder, transcriber
        self.model_name, self.language = model, language
        self.on_segment = on_segment or (lambda *_: None)
        self.on_status = on_status or (lambda *_: None)
        self.threads = threads or max(2, (os.cpu_count() or 4) // 2)
        self.segments = []
        self._stop = threading.Event()
        self._buf = np.empty(0, np.float32)
        self._buf_start = 0.0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def finish(self, timeout=120):
        """Detiene y transcribe lo que quedó pendiente. Devuelve los segmentos."""
        self._stop.set()
        self._thread.join(timeout=timeout)
        return self.segments

    def _pull(self):
        data = self.rec.pull_live()
        if data is None or not len(data):
            return
        n = len(data) // 3 * 3  # 48 kHz → 16 kHz
        down = data[:n].reshape(-1, 3).mean(axis=1).astype(np.float32)
        self._buf = np.concatenate([self._buf, down])

    def _run(self):
        try:
            model = self.transcriber.model(self.model_name, self.on_status, self.threads)
            self.on_status("Transcribiendo en vivo")
            while not self._stop.is_set():
                time.sleep(0.5)
                self._pull()
                dur = len(self._buf) / SAMPLE_RATE
                if dur >= self.MAX_SECONDS or (dur >= self.MIN_SECONDS and self._pause_at_end()):
                    self._transcribe(model, len(self._buf))
            self._pull()
            if len(self._buf):
                self._transcribe(model, len(self._buf))
        except Exception as e:  # noqa: BLE001
            self.on_status(f"Error en vivo: {e}")

    def _pause_at_end(self):
        tail = self._buf[-int(self.TAIL * SAMPLE_RATE):]
        rms_tail = float(np.sqrt(np.mean(tail ** 2)))
        rms_all = float(np.sqrt(np.mean(self._buf ** 2))) or 1e-9
        return rms_tail < 0.006 or rms_tail < rms_all * 0.25

    def _transcribe(self, model, cut):
        chunk, self._buf = self._buf[:cut], self._buf[cut:]
        offset = self._buf_start
        self._buf_start += cut / SAMPLE_RATE
        if float(np.sqrt(np.mean(chunk ** 2))) < 0.002:  # silencio total
            return
        prompt = " ".join(t for _s, _e, t in self.segments[-3:])[-200:] or None
        segs, _info = model.transcribe(chunk, language=self.language, vad_filter=True,
                                       beam_size=1, condition_on_previous_text=False,
                                       initial_prompt=prompt)
        for s in segs:
            text = s.text.strip()
            if text:
                seg = (offset + s.start, offset + s.end, text)
                self.segments.append(seg)
                self.on_segment(*seg)


def download_youtube(url, progress=None):
    """Descarga solo el audio. Devuelve (ruta, título, carpeta_temporal)."""
    import yt_dlp

    tmp = Path(tempfile.mkdtemp(prefix="yt_"))

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            progress(d.get("downloaded_bytes", 0) / total * 100 if total else 0)

    opts = {"format": "bestaudio/best", "outtmpl": str(tmp / "%(title).80s.%(ext)s"),
            "ffmpeg_location": FFMPEG, "quiet": True, "no_warnings": True,
            "noprogress": True, "noplaylist": True, "progress_hooks": [hook]}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        found = list(tmp.iterdir())
        if not found:
            raise RuntimeError("No se pudo descargar el audio.")
        path = found[0]
    return path, info.get("title") or path.stem, tmp
