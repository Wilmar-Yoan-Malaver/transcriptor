"""Pruebas de integridad de datos: que nunca se pierda ni se corte una grabación o transcripción."""

import json
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
