"""Pruebas de seguridad de la API que la interfaz (HTML/JS) puede llamar en Python.

Supuesto de amenaza: si alguna vez se colara código malicioso en la interfaz (por ejemplo en el
título de un video de YouTube o el nombre de un archivo), ese código NO debe poder abrir
programas, leer/renombrar/borrar archivos fuera de la carpeta de grabaciones, ni darle órdenes
arbitrarias al motor.
"""

from types import SimpleNamespace

import pytest

import app


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """Carpeta de grabaciones + una carpeta "privada" al lado; registra lo que se intenta ejecutar."""
    folder = tmp_path / "Transcripciones"
    private = tmp_path / "Privado"
    folder.mkdir()
    private.mkdir()
    started, popen, runs, recycled, sent = [], [], [], [], []
    monkeypatch.setattr(app.os, "startfile", started.append, raising=False)
    monkeypatch.setattr(app.subprocess, "Popen", lambda cmd, **_kw: popen.append(cmd))
    monkeypatch.setattr(app.subprocess, "run",
                        lambda cmd, **_kw: runs.append(cmd) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(app.winutil, "send_to_recycle_bin", lambda files: recycled.extend(files) or True)
    fake_app = SimpleNamespace(cfg={"outputDir": str(folder)}, engine=SimpleNamespace(send=sent.append))
    return SimpleNamespace(api=app.Api(fake_app), folder=folder, private=private, started=started,
                           popen=popen, runs=runs, recycled=recycled, sent=sent)


def make(path, text="x"):
    path.write_text(text, encoding="utf-8")
    return path


# ----------------------------------------------------- archivos fuera de la carpeta

def outside_paths(s):
    """Formas típicas de intentar salir de la carpeta permitida."""
    secret = make(s.private / "secreto.txt", "datos privados")
    return [str(secret),
            str(s.folder / ".." / "Privado" / "secreto.txt"),   # ruta con ".."
            str(s.folder / "sub" / ".." / ".." / "Privado" / "secreto.txt")]


def test_cannot_open_files_outside_folder(setup):
    for path in outside_paths(setup):
        setup.api.open_path(path)
    assert setup.started == []


def test_cannot_read_files_outside_folder(setup):
    for path in outside_paths(setup):
        assert setup.api.read_text(path) == ""


def test_cannot_rename_or_delete_files_outside_folder(setup):
    for path in outside_paths(setup):
        assert "error" in setup.api.rename(path, "robado")
        assert "error" in setup.api.delete_recording(path)
    assert (setup.private / "secreto.txt").exists()
    assert setup.recycled == []


def test_cannot_copy_or_reveal_files_outside_folder(setup):
    for path in outside_paths(setup):
        assert setup.api.copy_file(path) is False
        setup.api.reveal(path)
    assert setup.runs == [] and setup.popen == [] and setup.started == []


# ----------------------------------------------------- programas y extensiones

@pytest.mark.parametrize("name", ["virus.exe", "script.bat", "script.ps1", "acceso.lnk", "macro.vbs"])
def test_cannot_open_programs_even_inside_folder(setup, name):
    setup.api.open_path(str(make(setup.folder / name)))
    assert setup.started == []


def test_read_text_only_reads_transcripts(setup):
    make(setup.folder / "video.mp4", "binario")
    assert setup.api.read_text(str(setup.folder / "video.mp4")) == ""
    assert setup.api.read_text(str(make(setup.folder / "ok.txt", "hola"))) == "hola"


def test_allowed_file_inside_folder_works(setup):
    video = make(setup.folder / "Reunión.mp4")
    setup.api.open_path(str(video))
    assert setup.started == [video.resolve()]


def test_reveal_folder_itself_is_allowed(setup):
    setup.api.reveal(str(setup.folder))
    assert setup.started == [setup.folder.resolve()]


# --------------------------------------------------------------------- renombrar

def test_rename_cannot_escape_folder_with_path_in_new_name(setup):
    video = make(setup.folder / "a.mp4")
    r = setup.api.rename(str(video), "..\\..\\Privado\\robado")
    assert r["path"].startswith(str(setup.folder))   # se queda en la carpeta, sin "\" ni ".."
    assert not (setup.private / "robado.mp4").exists()


@pytest.mark.parametrize("name", ["CON", "nul", "COM1", "LPT9"])
def test_rename_rejects_windows_reserved_names(setup, name):
    video = make(setup.folder / "a.mp4")
    assert "error" in setup.api.rename(str(video), name)


def test_rename_rejects_too_long_names(setup):
    video = make(setup.folder / "a.mp4")
    assert "error" in setup.api.rename(str(video), "x" * 300)


def test_rename_strips_control_characters(setup):
    video = make(setup.folder / "a.mp4")
    assert setup.api.rename(str(video), "nombre\x00\x07raro")["path"].endswith("nombre__raro.mp4")


# ------------------------------------------------------------- órdenes al motor

@pytest.mark.parametrize("msg", [
    {"cmd": "start_recording", "out_dir": "C:\\"},   # grabar va solo por el botón (método propio)
    {"cmd": "shutdown"},
    {"cmd": "__class__"},
    {"cmd": None},
    "no es un objeto",
])
def test_ui_cannot_send_arbitrary_engine_commands(setup, msg):
    assert setup.api.send(msg) is False
    assert setup.sent == []


def test_transcriptions_are_always_saved_in_the_folder(setup):
    setup.api.send({"cmd": "transcribe", "path": "C:\\video.mp4", "out_dir": "C:\\Windows\\System32"})
    assert setup.sent[-1]["out_dir"] == str(setup.folder.resolve())


def test_media_info_only_for_files_in_folder(setup):
    for path in outside_paths(setup):
        assert setup.api.send({"cmd": "media_info", "path": path, "req": "x"}) is False
    assert setup.sent == []


# ----------------------------------------------------------------- configuración

@pytest.mark.parametrize(("key", "value"), [
    ("noExiste", 1),
    ("fps", "30; rm -rf"),        # tipo incorrecto
    ("playSounds", 1),            # 1 no es True/False
    ("outputDir", "relativa"),    # debe ser una ruta absoluta
    ("barPos", [1, "2"]),
])
def test_invalid_config_is_rejected(setup, key, value):
    assert setup.api.set_config(key, value) is False
    assert key not in setup.api._app.cfg or setup.api._app.cfg.get(key) != value


def test_valid_config_is_saved(setup):
    saved = []
    cfg_class = type("Cfg", (dict,), {"save": lambda self: saved.append(dict(self))})
    setup.api._app.cfg = cfg_class({"outputDir": str(setup.folder)})
    assert setup.api.set_config("fps", 60) is True
    assert saved[-1]["fps"] == 60
