"""Prueba de integración del protocolo JSON del motor (engine/engine.py) en un proceso real."""

import json
import subprocess
import sys
import threading
import time

import pytest
from conftest import ROOT


class EngineProcess:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "engine" / "engine.py")],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.events = []
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            self.events.append(json.loads(line))

    def send(self, **msg):
        self.proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        self.proc.stdin.flush()

    def wait(self, kind, timeout=60):
        start = time.time()
        while time.time() - start < timeout:
            for ev in list(self.events):
                if ev["type"] == kind:
                    self.events.remove(ev)
                    return ev
            time.sleep(0.05)
        raise TimeoutError(f"no llegó el evento {kind!r}")


@pytest.fixture(scope="module")
def engine():
    eng = EngineProcess()
    eng.wait("ready", timeout=120)
    yield eng
    if eng.proc.poll() is None:
        eng.proc.kill()


def test_unknown_command_reports_error(engine):
    engine.send(cmd="no_existe")
    assert "no_existe" in engine.wait("error")["message"]


def test_private_methods_cannot_be_called(engine):
    engine.send(cmd="_run_tx")
    assert engine.wait("error")


def test_save_live_without_recording_reports_error(engine):
    engine.send(cmd="save_live", path="C:/no/existe.mp4", job="j1")
    ev = engine.wait("tx_error")
    assert ev["job"] == "j1"


def test_invalid_json_does_not_kill_engine(engine):
    engine.proc.stdin.write(b"{ esto no es json\n")
    engine.proc.stdin.flush()
    engine.wait("error")
    engine.send(cmd="no_existe")  # sigue respondiendo
    assert engine.wait("error")


@pytest.mark.parametrize("raw", [
    b"123",                                   # JSON válido pero no es un objeto
    b"[1, 2, 3]",
    b'{"cmd": 42}',                           # cmd que no es texto
    b'{"cmd": null}',
    b'{"sin_cmd": true}',
    b'{"cmd": "transcribe"}',                 # faltan campos obligatorios
    b'{"cmd": "media_info", "path": 5}',
    b'{"cmd": "__init__"}',
    b"\xff\xfe basura binaria",
    b'{"cmd": "' + b"x" * 100_000 + b'"}',   # mensaje enorme
], ids=lambda raw: repr(raw[:30]))
def test_malformed_messages_do_not_kill_engine(engine, raw):
    engine.proc.stdin.write(raw + b"\n")
    engine.proc.stdin.flush()
    engine.send(cmd="no_existe_ping")         # sigue vivo y respondiendo
    deadline = time.time() + 30
    while time.time() < deadline:
        if any("no_existe_ping" in str(ev.get("message", "")) for ev in engine.events):
            break
        time.sleep(0.05)
    else:
        pytest.fail("el motor dejó de responder")
    assert engine.proc.poll() is None
    engine.events.clear()


def test_shutdown_exits_cleanly(engine):
    engine.send(cmd="shutdown")
    assert engine.proc.wait(timeout=30) == 0
