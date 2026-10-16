"""Idioma de la app (español / inglés) en el motor y en la ventana."""

import re
from pathlib import Path
from types import SimpleNamespace

import i18n
import pytest
from conftest import ROOT

import app

PY_FILES = [ROOT / "engine" / "engine.py", ROOT / "engine" / "core.py", ROOT / "desktop" / "app.py"]


@pytest.fixture(autouse=True)
def spanish_after_each_test():
    yield
    i18n.set_language("es")


def placeholders(text):
    return sorted(re.findall(r"\{(\w+)\}", text))


def test_both_languages_have_the_same_keys():
    assert set(i18n.MESSAGES["en"]) == set(i18n.MESSAGES["es"])


def test_translations_keep_the_same_placeholders():
    for key, text in i18n.MESSAGES["es"].items():
        assert placeholders(i18n.MESSAGES["en"][key]) == placeholders(text), key


def test_every_key_used_in_the_code_exists():
    used = set()
    for path in PY_FILES:
        used |= set(re.findall(r"""tr\(\s*["']([\w.]+)["']""", Path(path).read_text(encoding="utf-8")))
    # Claves que se arman en el código (no aparecen literales dentro de tr(...)).
    used |= {"rec.enable_failed_mic", "rec.enable_failed_sys", "tx.loading_model_first"}
    assert used, "no se encontró ningún tr(...)"
    missing = sorted(k for k in used if k not in i18n.MESSAGES["es"])
    assert missing == []


def test_tr_uses_current_language_and_fills_placeholders():
    i18n.set_language("en")
    assert i18n.tr("file.name_too_long", max=150) == "The name can be at most 150 characters long."
    i18n.set_language("es")
    assert i18n.tr("file.name_too_long", max=150) == "El nombre puede tener como máximo 150 caracteres."


@pytest.mark.parametrize("value", ["fr", "", None, 1])
def test_unknown_language_falls_back_to_spanish(value):
    i18n.set_language(value)
    assert i18n.language() == "es"


@pytest.mark.parametrize(("value", "ok"),
                         [("es", True), ("en", True), ("fr", False), (None, False), (1, False)])
def test_ui_language_config_only_accepts_es_or_en(value, ok):
    assert app.valid_config_value("uiLanguage", value) is ok


def test_ui_language_defaults_to_ask_on_first_run():
    assert app.DEFAULTS["uiLanguage"] is None


def test_changing_ui_language_notifies_window_and_engine(tmp_path):
    changed = []
    cfg = type("Cfg", (dict,), {"save": lambda self: None})({**app.DEFAULTS, "outputDir": str(tmp_path)})
    api = app.Api(SimpleNamespace(cfg=cfg, set_language=changed.append))
    assert api.set_config("uiLanguage", "en") is True
    assert changed == ["en"]
    assert api.set_config("uiLanguage", "fr") is False
    assert changed == ["en"]


def test_reset_keeps_ui_language(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "CONFIG_FILE", tmp_path / "config.json")
    cfg = app.Config()
    cfg["uiLanguage"] = "en"
    api = app.Api(SimpleNamespace(cfg=cfg))
    assert api.reset_config()["uiLanguage"] == "en"


def test_recording_file_name_follows_language():
    i18n.set_language("en")
    assert i18n.tr("rec.file_name", stamp="20261016_120551") == "Recording 20261016_120551"
