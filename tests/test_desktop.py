"""Pruebas de la API que usa la interfaz (desktop/app.py): renombrar, historial, eliminar."""

import json
import os
import time
from types import SimpleNamespace

import pytest

import app


@pytest.fixture
def folder(tmp_path):
    return tmp_path


@pytest.fixture
def api(folder):
    """Api con una app mínima: carpeta de salida temporal y un motor que solo anota mensajes."""
    sent = []
    fake_app = SimpleNamespace(cfg={"outputDir": str(folder)}, engine=SimpleNamespace(send=sent.append))
    instance = app.Api(fake_app)
    instance.sent = sent
    return instance


def touch(path, mtime=None, content=b"x"):
    path.write_bytes(content)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def test_glob_escape():
    assert app.glob_escape("Demo [v1.2]*?") == "Demo [[]v1.2[]][*][?]"


# -------------------------------------------------------------------- renombrar


def test_rename_moves_transcript_and_subtitles(api, folder):
    for ext in (".mp4", ".txt", ".srt"):
        touch(folder / f"Grabación 1{ext}")
    r = api.rename(str(folder / "Grabación 1.mp4"), "Reunión cliente")
    assert r == {"path": str(folder / "Reunión cliente.mp4")}
    assert sorted(p.name for p in folder.iterdir()) == ["Reunión cliente.mp4", "Reunión cliente.srt",
                                                        "Reunión cliente.txt"]
    assert api.sent[-1]["cmd"] == "live_moved"  # el motor se entera del nombre nuevo


def test_rename_only_case_change_is_allowed(api, folder):
    touch(folder / "reunion.mp4")
    assert "path" in api.rename(str(folder / "reunion.mp4"), "Reunion")
    assert [p.name for p in folder.iterdir()] == ["Reunion.mp4"]


def test_rename_rejects_existing_name(api, folder):
    touch(folder / "a.mp4")
    touch(folder / "b.mp4")
    assert "error" in api.rename(str(folder / "a.mp4"), "b")


def test_rename_replaces_invalid_characters(api, folder):
    touch(folder / "a.mp4")
    assert api.rename(str(folder / "a.mp4"), 'Q3: "final"')["path"].endswith('Q3_ _final_.mp4')


# --------------------------------------------------------------------- historial


def test_history_groups_media_with_transcript_and_sorts_by_date(api, folder):
    now = time.time()
    touch(folder / "vieja.mp4", now - 300)
    touch(folder / "vieja.txt", now - 300)
    touch(folder / "solo texto.txt", now - 200)
    touch(folder / "audio.wav", now - 100)
    touch(folder / "notas.log", now)  # no es grabación ni transcripción
    items = api.history()["items"]
    assert [i["name"] for i in items] == ["audio", "solo texto", "vieja"]
    vieja = items[2]
    assert vieja["media"].endswith("vieja.mp4") and vieja["txt"].endswith("vieja.txt")
    assert items[1]["media"] is None
    assert items[0]["audioOnly"] is True


def test_history_of_missing_folder_is_empty(api, folder):
    api._app.cfg["outputDir"] = str(folder / "no-existe")
    assert api.history()["items"] == []


# ---------------------------------------------------------------------- eliminar


def test_delete_sends_only_that_recording_to_recycle_bin(api, folder, monkeypatch):
    recycled = []
    monkeypatch.setattr(app.winutil, "send_to_recycle_bin", lambda files: recycled.extend(files) or True)
    for name in ("Demo [v1].mp4", "Demo [v1].txt", "Demo [v1].srt", "Demo [v1] copia.mp4", "Demo [v1].log"):
        touch(folder / name)
    assert "deleted" in api.delete_recording(str(folder / "Demo [v1].mp4"))
    assert sorted(p.name for p in recycled) == ["Demo [v1].mp4", "Demo [v1].srt", "Demo [v1].txt"]


def test_delete_missing_file_reports_error(api, folder):
    assert "error" in api.delete_recording(str(folder / "nada.mp4"))


# ----------------------------------------------------------------- configuración


def test_config_merges_saved_values_with_defaults(tmp_path, monkeypatch):
    file = tmp_path / "config.json"
    file.write_text(json.dumps({"model": "medium"}), encoding="utf-8")
    monkeypatch.setattr(app, "CONFIG_FILE", file)
    cfg = app.Config()
    assert cfg["model"] == "medium"                    # lo guardado
    assert cfg["fps"] == app.DEFAULTS["fps"]           # lo que falta, por defecto


def test_config_survives_corrupt_file(tmp_path, monkeypatch):
    file = tmp_path / "config.json"
    file.write_text("{ no es json", encoding="utf-8")
    monkeypatch.setattr(app, "CONFIG_FILE", file)
    assert app.Config()["model"] == app.DEFAULTS["model"]
