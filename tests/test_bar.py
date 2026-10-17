"""Barra flotante: se ajusta a su contenido y, al desplegarse, no se sale de la pantalla."""

from types import SimpleNamespace

import pytest

import app

AREA = (0, 0, 1920, 1040)  # área de trabajo del monitor (sin barra de tareas)


@pytest.fixture
def bar(monkeypatch):
    """App mínima con una barra en `rect`; registra cada movimiento/redimensión."""
    state = SimpleNamespace(rect=[100, 10, 300, 56], moves=[])

    def move(_h, x, y, w=0, h=0):
        state.moves.append((x, y, w, h))
        state.rect = [x, y, x + w, y + h]

    monkeypatch.setattr(app.winutil, "hwnd_of", lambda _w: 1)
    monkeypatch.setattr(app.winutil, "outer_rect", lambda _h: tuple(state.rect))
    monkeypatch.setattr(app.winutil, "work_area_for", lambda _r: AREA)
    monkeypatch.setattr(app.winutil, "move_topmost", move)
    fake = SimpleNamespace(bar=object(), bar_home=None)
    fake.fit_bar = lambda w, h, e: app.App.fit_bar(fake, w, h, e)
    state.app = fake
    state.api = app.BarApi(fake)
    return state


def test_fit_resizes_to_content_keeping_position(bar):
    assert bar.api.fit(180, 46, False) is True
    assert bar.moves[-1] == (100, 10, 180, 46)


def test_expanding_near_right_edge_moves_left_and_collapsing_goes_back(bar):
    bar.rect = [1800, 10, 1980, 56]           # compacta, pegada al borde derecho
    bar.api.fit(400, 46, True)                # completa: no cabe a la derecha
    assert bar.moves[-1] == (1920 - 400, 10, 400, 46)
    bar.api.fit(180, 46, False)               # vuelve a compacta en su lugar original
    assert bar.moves[-1] == (1800, 10, 180, 46)


def test_expanding_with_room_stays_in_place(bar):
    bar.api.fit(400, 46, True)
    bar.api.fit(180, 46, False)
    assert [m[0] for m in bar.moves] == [100, 100]


@pytest.mark.parametrize(("w", "h"),
                         [(0, 46), (-5, 46), (5000, 46), (180, 99999), ("180", 46), (1.5, 46), (True, 46)])
def test_fit_rejects_invalid_sizes(bar, w, h):
    assert bar.api.fit(w, h, False) is False
    assert bar.moves == []
