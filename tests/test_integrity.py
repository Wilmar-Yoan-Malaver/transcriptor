"""Pruebas de integridad de datos: que nunca se pierda ni se corte una grabación o transcripción."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import app
import core

# ------------------------------------------------------------- escritura atómica


def test_atomic_write_keeps_previous_file_if_writing_fails(tmp_path, monkeypatch):
    target = tmp_path / "reunion.txt"
    target.write_text("transcripción buena", encoding="utf-8")

    def broken_replace(*_args):
        raise OSError("disco lleno")

    monkeypatch.setattr(core.os, "replace", broken_replace)
    with pytest.raises(OSError):
        core.atomic_write_text(target, "texto nuevo a medias")
    assert target.read_text(encoding="utf-8") == "transcripción buena"   # intacto
    assert list(tmp_path.iterdir()) == [target]                           # sin temporales sueltos


def test_atomic_write_replaces_content(tmp_path):
    target = tmp_path / "a.txt"
    target.write_text("viejo", encoding="utf-8")
    core.atomic_write_text(target, "nuevo")
    assert target.read_text(encoding="utf-8") == "nuevo"


def test_config_save_is_atomic(tmp_path, monkeypatch):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({"model": "small"}), encoding="utf-8")
    monkeypatch.setattr(app, "CONFIG_FILE", file)
    cfg = app.Config()
    cfg["model"] = "medium"

    def broken_replace(*_args):
        raise OSError("se apagó el PC")

    monkeypatch.setattr(app.os, "replace", broken_replace)
    with pytest.raises(OSError):
        cfg.save()
    assert json.loads(file.read_text(encoding="utf-8"))["model"] == "small"   # sigue siendo JSON válido


# ------------------------------------------------- grabación: unir video y audio


@pytest.fixture
def finished_recording(tmp_path):
    """Grabadora "terminada": un video temporal y 1 s de audio del micrófono, sin dispositivos."""
    out = tmp_path / "Transcripciones"
    rec = core.MeetingRecorder(out, None, None, None, speaker_on=False, mic_on=False)
    raw = rec.tmp / "video.mp4"
    raw.write_bytes(b"video-crudo")
    rec._screen = SimpleNamespace(stop=lambda: raw, error=None)
    rec._chunks["mic"] = [np.full(core.REC_RATE // 10, 0.1, np.float32)] * 10
    yield rec, out
    rec.cleanup()


def test_failed_merge_keeps_video_and_audio(finished_recording, monkeypatch):
    rec, out = finished_recording
    monkeypatch.setattr(core.subprocess, "run",
                        lambda *_a, **_k: SimpleNamespace(returncode=1, stderr=b"No space left on device"))
    result = rec.stop()
    rec.cleanup()  # el motor siempre borra la carpeta temporal después
    names = sorted(p.name for p in out.iterdir())
    assert names == [f"Grabación {rec.stamp} (audio).wav", f"Grabación {rec.stamp} (video).mp4"]
    assert result.name.endswith("(video).mp4")
    assert any("No space left" in e for e in rec.errors)   # se informa el motivo


def test_successful_merge_produces_single_mp4(finished_recording, monkeypatch):
    rec, out = finished_recording

    def fake_ffmpeg(cmd, **_kw):
        with open(cmd[-1], "wb") as f:   # ffmpeg escribe el .mp4 final
            f.write(b"mp4-final")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(core.subprocess, "run", fake_ffmpeg)
    result = rec.stop()
    assert [p.name for p in out.iterdir()] == [f"Grabación {rec.stamp}.mp4"]
    assert result.read_bytes() == b"mp4-final"
    assert rec.errors == []


def test_empty_output_counts_as_failure(finished_recording, monkeypatch):
    rec, out = finished_recording

    def empty_ffmpeg(cmd, **_kw):
        open(cmd[-1], "wb").close()   # "terminó bien" pero dejó un archivo vacío
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(core.subprocess, "run", empty_ffmpeg)
    rec.stop()
    assert f"Grabación {rec.stamp}.mp4" not in [p.name for p in out.iterdir()]
    assert len(list(out.iterdir())) == 2   # video y audio rescatados


def test_merge_never_reads_keyboard_and_has_timeout(finished_recording, monkeypatch):
    """Un ffmpeg con acceso a la entrada del motor se quedaba esperando teclas para siempre."""
    rec, _out = finished_recording
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4-final")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(core.subprocess, "run", fake_run)
    rec.stop()
    cmd, kw = calls[-1]
    assert "-nostdin" in cmd
    assert kw["stdin"] is core.subprocess.DEVNULL
    assert kw["timeout"] >= 300


def test_stuck_merge_is_cut_and_recording_rescued(finished_recording, monkeypatch):
    rec, out = finished_recording

    def stuck_ffmpeg(cmd, **kw):
        open(cmd[-1], "wb").close()   # alcanzó a crear el archivo, pero sin terminarlo
        raise core.subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(core.subprocess, "run", stuck_ffmpeg)
    result = rec.stop()
    rec.cleanup()
    names = sorted(p.name for p in out.iterdir())
    assert names == [f"Grabación {rec.stamp} (audio).wav", f"Grabación {rec.stamp} (video).mp4"]
    assert result.name.endswith("(video).mp4")
    assert any("no terminó" in e for e in rec.errors)


def test_run_ffmpeg_real_binary_ignores_stdin():
    r = core.run_ffmpeg(["-version"], timeout=30)
    assert r.returncode == 0 and b"ffmpeg version" in r.stdout


# ------------------------------------------- acceso controlado a carpetas (Windows Defender)


def test_ffmpeg_writes_merge_to_temp_folder_not_documents(finished_recording, monkeypatch):
    """Defender bloquea a ffmpeg si escribe en Documentos: escribe en la carpeta temporal."""
    rec, out = finished_recording
    targets = []

    def fake_ffmpeg(cmd, **_kw):
        targets.append(cmd[-1])
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4-final")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(core.subprocess, "run", fake_ffmpeg)
    result = rec.stop()
    assert targets[-1].startswith(str(rec.tmp))
    assert result.parent == out and result.read_bytes() == b"mp4-final"


def test_blocked_output_folder_keeps_recording_in_rescue_folder(finished_recording, monkeypatch, tmp_path):
    rec, out = finished_recording
    rescue = tmp_path / "Recuperadas"
    monkeypatch.setattr(core, "RESCUE_DIR", rescue)

    def fake_ffmpeg(cmd, **_kw):
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4-final")
        return SimpleNamespace(returncode=0, stderr=b"")

    real_move = core.shutil.move

    def guarded_move(src, dst):
        if Path(dst).parent == out:
            raise PermissionError(13, "Acceso denegado")  # como el acceso controlado a carpetas
        return real_move(src, dst)

    monkeypatch.setattr(core.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(core.shutil, "move", guarded_move)
    result = rec.stop()
    rec.cleanup()  # el motor borra la carpeta temporal: la grabación no debe estar ahí
    assert result.parent == rescue and result.read_bytes() == b"mp4-final"
    assert any(str(rescue) in e for e in rec.errors)


# --------------------------------------------------- borde amarillo de la captura de Windows


def test_capture_retries_with_border_when_windows_cannot_hide_it(monkeypatch):
    attempts = []

    class FakeCapture:
        def __init__(self, draw_border=None, **_kw):
            self.draw_border = draw_border
            attempts.append(draw_border)

        def event(self, fn):
            return fn

        def start_free_threaded(self):
            if self.draw_border is False:
                raise RuntimeError("Graphics capture error: Toggling the capture border is not supported")
            return "control"

    monkeypatch.setattr(core, "WindowsCapture", FakeCapture)
    monkeypatch.setitem(core._BORDER, "can_hide", True)
    source = {"kind": "monitor", "index": 0}
    assert core.start_capture(source, lambda *_: None, lambda: None) == "control"
    assert attempts == [False, None]
    attempts.clear()
    core.start_capture(source, lambda *_: None, lambda: None)  # ya aprendió: no reintenta
    assert attempts == [None]


def test_other_capture_errors_are_not_hidden(monkeypatch):
    class BrokenCapture:
        def __init__(self, **_kw):
            pass

        def event(self, fn):
            return fn

        def start_free_threaded(self):
            raise RuntimeError("Graphics capture error: la ventana ya no existe")

    monkeypatch.setattr(core, "WindowsCapture", BrokenCapture)
    with pytest.raises(RuntimeError, match="ventana"):
        core.start_capture({"kind": "monitor", "index": 0}, lambda *_: None, lambda: None)
