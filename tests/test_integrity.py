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
    assert rec.blocked["files"] == [result] and "Acceso denegado" in rec.blocked["error"]


def test_output_folder_that_cannot_be_created_still_rescues(finished_recording, monkeypatch, tmp_path):
    rec, out = finished_recording
    rescue = tmp_path / "Recuperadas"
    monkeypatch.setattr(core, "RESCUE_DIR", rescue)
    real_mkdir = Path.mkdir

    def guarded_mkdir(self, *a, **kw):
        if self == out:
            raise FileNotFoundError(2, "El sistema no puede encontrar el archivo especificado")
        return real_mkdir(self, *a, **kw)

    def fake_ffmpeg(cmd, **_kw):
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4-final")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr(core.subprocess, "run", fake_ffmpeg)
    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    result = rec.stop()
    rec.cleanup()
    assert result.parent == rescue and result.read_bytes() == b"mp4-final"
    assert rec.blocked["files"] == [result]


# ------------------------------------- carpeta bloqueada: permitir la app o usar otra carpeta


@pytest.fixture
def blocked_app(tmp_path, monkeypatch):
    """App con una grabación rescatada en Recuperadas y la carpeta de grabaciones bloqueada."""
    rescue, folder, unprotected = tmp_path / "Recuperadas", tmp_path / "Documentos", tmp_path / "Libre"
    rescue.mkdir()
    monkeypatch.setattr(app, "RESCUE_DIR", rescue)
    monkeypatch.setattr(app, "UNPROTECTED_DIR", unprotected)
    monkeypatch.setattr(app, "CONFIG_FILE", tmp_path / "config.json")
    a = app.App()
    a.cfg["outputDir"] = str(folder)
    a.engine = SimpleNamespace(send=lambda msg: sent.append(msg))
    a.js = lambda *_a: None
    sent = []
    video = rescue / "Grabación 1.mp4"
    video.write_bytes(b"mp4")
    a.on_event({"type": "folder_blocked", "files": [str(video), str(tmp_path / "otro" / "x.mp4")]})
    return SimpleNamespace(app=a, api=app.Api(a), video=video, folder=folder, unprotected=unprotected,
                           sent=sent)


def test_only_rescue_folder_files_are_accepted(blocked_app):
    assert blocked_app.app.rescued == [blocked_app.video]   # la ruta de otra carpeta se ignora


def test_allow_app_runs_elevated_and_moves_recording(blocked_app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.winutil, "run_elevated", lambda exe, params: calls.append((exe, params)) or 0)
    r = blocked_app.api.allow_folder_access()
    target = blocked_app.folder / blocked_app.video.name
    assert r == {"path": str(target)} and target.read_bytes() == b"mp4"
    exe, params = calls[0]
    assert exe == app.POWERSHELL and "Add-MpPreference -ControlledFolderAccessAllowedApplications" in params
    assert {"cmd": "live_moved", "old": str(blocked_app.video), "new": str(target)} in blocked_app.sent


def test_declined_admin_prompt_leaves_recording_in_rescue(blocked_app, monkeypatch):
    monkeypatch.setattr(app.winutil, "run_elevated", lambda *_a: None)   # el usuario dijo "No"
    assert blocked_app.api.allow_folder_access() == {"canceled": True}
    assert blocked_app.video.exists() and blocked_app.app.rescued == [blocked_app.video]


def test_use_unprotected_folder_moves_recording_and_saves_setting(blocked_app):
    r = blocked_app.api.use_unprotected_folder()
    target = blocked_app.unprotected / blocked_app.video.name
    assert r == {"path": str(target), "folder": str(blocked_app.unprotected)}
    assert target.read_bytes() == b"mp4" and not blocked_app.video.exists()
    assert blocked_app.app.cfg["outputDir"] == str(blocked_app.unprotected)


def test_move_never_overwrites_an_existing_recording(blocked_app):
    blocked_app.unprotected.mkdir()
    (blocked_app.unprotected / blocked_app.video.name).write_bytes(b"otra")
    r = blocked_app.api.use_unprotected_folder()
    assert "error" in r and blocked_app.video.exists()
    assert (blocked_app.unprotected / blocked_app.video.name).read_bytes() == b"otra"
    assert blocked_app.app.cfg["outputDir"] == str(blocked_app.folder)   # no cambió la carpeta


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


def test_capture_retries_without_update_interval_on_windows_10(monkeypatch):
    attempts = []

    class FakeCapture:
        def __init__(self, draw_border=None, **kw):
            self.draw_border, self.kw = draw_border, kw
            attempts.append((draw_border, "minimum_update_interval" in kw))

        def event(self, fn):
            return fn

        def start_free_threaded(self):
            if self.draw_border is False:
                raise RuntimeError("Graphics capture error: Toggling the capture border is not supported")
            if "minimum_update_interval" in self.kw:
                raise RuntimeError("Graphics capture error: Setting a minimum update interval is not "
                                   "supported by the Graphics Capture API on this platform.")
            return "control"

    monkeypatch.setattr(core, "WindowsCapture", FakeCapture)
    monkeypatch.setitem(core._BORDER, "can_hide", True)
    monkeypatch.setitem(core._UPDATE_INTERVAL, "supported", True)
    source = {"kind": "monitor", "index": 0}
    assert core.start_capture(source, lambda *_: None, lambda: None, minimum_update_interval=66) == "control"
    assert attempts == [(False, True), (None, True), (None, False)]
    attempts.clear()
    core.start_capture(source, lambda *_: None, lambda: None, minimum_update_interval=66)  # ya aprendió
    assert attempts == [(None, False)]


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
