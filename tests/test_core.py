"""Pruebas del motor (engine/core.py): utilidades, transcripciones, voz y grabadora."""

import numpy as np
import pytest
from conftest import FIXTURES

import core

# --------------------------------------------------------------------- utilidades


@pytest.mark.parametrize(("seconds", "expected"), [(0, "00:00"), (65, "01:05"), (3725, "01:02:05")])
def test_short_time(seconds, expected):
    assert core.short_time(seconds) == expected


def test_srt_time_milliseconds():
    assert core.srt_time(3725.5) == "01:02:05,500"


@pytest.mark.parametrize(("name", "expected"), [
    ('Reunión: "Q3" <final>?', "Reunión_ _Q3_ _final__"),   # solo cambia lo que Windows no permite
    ("Demo v1.2 (cliente)", "Demo v1.2 (cliente)"),          # puntos y paréntesis se conservan
    ("  ...  ", "transcripcion"),                            # vacío → nombre por defecto
])
def test_safe_name(name, expected):
    assert core.safe_name(name) == expected


def test_safe_name_limits_length():
    assert len(core.safe_name("x" * 500)) == 120


# ------------------------------------------------------------------ transcripción


SEGMENTS = [(0.0, 2.5, "Hola a todos"), (2.6, 5.0, "Empecemos")]


def test_write_transcript_with_timestamps(tmp_path):
    txt, srt = core.write_transcript(tmp_path, "Demo v1.2", SEGMENTS, timestamps=True)
    assert txt.name == "Demo v1.2.txt"  # el punto del título no se toma como extensión
    assert txt.read_text(encoding="utf-8").splitlines() == ["[00:00] Hola a todos", "[00:02] Empecemos"]
    assert srt.read_text(encoding="utf-8").startswith("1\n00:00:00,000 --> 00:00:02,500\nHola a todos\n")


def test_write_transcript_without_timestamps(tmp_path):
    txt, _srt = core.write_transcript(tmp_path, "x", SEGMENTS, timestamps=False)
    assert txt.read_text(encoding="utf-8").splitlines() == ["Hola a todos", "Empecemos"]


def test_model_source_prefers_bundled_model(tmp_path, monkeypatch):
    (tmp_path / "base").mkdir()
    (tmp_path / "base" / "model.bin").write_bytes(b"")
    monkeypatch.setenv("TRANSCRIPTOR_MODELS", str(tmp_path))
    assert core.model_source("base") == str(tmp_path / "base")
    assert core.model_source("small") == "small"  # no incluido → se descarga por nombre


# ------------------------------------------------------------- detección de voz


def test_silence_has_no_speech():
    assert not core.has_speech(np.zeros(core.SAMPLE_RATE * 10, np.float32))


def test_faint_noise_has_no_speech():
    rng = np.random.default_rng(0)
    assert not core.has_speech((rng.standard_normal(core.SAMPLE_RATE * 10) * 0.003).astype(np.float32))


def test_voice_has_speech():
    assert core.has_speech(core.load_audio(FIXTURES / "voz.wav"))


# ------------------------------------------------------------------- grabadora

BLOCK = core.REC_RATE // 10  # 100 ms


@pytest.fixture
def recorder(tmp_path, monkeypatch):
    """Grabadora sin dispositivos reales: los bloques de audio se agregan a mano."""
    def fake_spawn(self, key, _device):  # sin hilo de captura: los bloques se agregan a mano
        self._chunks.setdefault(key, [])

    monkeypatch.setattr(core.sc, "get_microphone", lambda **_kw: object())
    monkeypatch.setattr(core.MeetingRecorder, "_spawn", fake_spawn)
    return core.MeetingRecorder(tmp_path, None, "Altavoces", "Micrófono", speaker_on=False, mic_on=False)


def test_pull_live_mixes_only_complete_blocks(recorder):
    recorder._chunks["mic"] = [np.full(BLOCK, 0.1, np.float32)] * 3
    recorder._chunks["sys"] = [np.full(BLOCK, 0.2, np.float32)] * 2
    mix = recorder.pull_live()
    assert len(mix) == 2 * BLOCK                # solo lo que ya llegó de ambas fuentes
    assert np.allclose(mix, 0.3)
    assert recorder.pull_live() is None         # nada nuevo todavía


def test_enabling_source_mid_recording_is_aligned_with_silence(recorder):
    recorder.set_source("mic", True)
    recorder._chunks["mic"].extend([np.full(BLOCK, 0.1, np.float32)] * 10)
    recorder.set_source("sys", True)  # se activa a mitad de la grabación
    assert len(recorder._chunks["sys"]) == 10                       # rellena con silencio hasta ahora
    assert not any(block.any() for block in recorder._chunks["sys"])
    assert recorder.active == {"mic": True, "sys": True}


def test_muting_marks_source_inactive(recorder):
    recorder.set_source("mic", True)
    recorder.set_source("mic", False)
    assert recorder.active == {"mic": False, "sys": False}


def test_enabling_source_without_device_fails(tmp_path):
    rec = core.MeetingRecorder(tmp_path, None, None, None, speaker_on=False, mic_on=False)
    with pytest.raises(RuntimeError):
        rec.set_source("mic", True)
