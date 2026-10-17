"""Runs Mercury and Pat as hidden child processes, with generated configs."""

import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Callable

from . import civ, mercury, pat, paths
from .settings import RADIO_IC7100, Settings

Log = Callable[[str], None]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


def _wait(check: Callable[[], bool], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.3)
    return False


class Child:
    def __init__(self, name: str, args: list[str], cwd: Path, log_path: Path, env: dict | None = None):
        self.name, self.args, self.cwd, self.log_path, self.env = name, args, cwd, log_path, env
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            self.args,
            cwd=str(self.cwd),
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log.close()  # the child keeps its own handle

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace: float = 5) -> None:
        if not self.running():
            return
        self.proc.terminate()
        try:
            self.proc.wait(grace)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(grace)


class Station:
    """Mercury + Pat for one callsign. start() and stop() are blocking."""

    def __init__(self, settings: Settings, log: Log):
        self.settings = settings
        self.log = log
        self.http_port = 0
        self.mercury: Child | None = None
        self.pat: Child | None = None
        self.client: pat.PatClient | None = None
        self.events: pat.PatEvents | None = None

    def start(self, on_event: Callable[[str, object], None]) -> None:
        s = self.settings
        data, logs, pdir = paths.data_dir(), paths.logs_dir(), paths.pat_dir()

        for exe in (paths.mercury_exe(), paths.pat_exe()):
            if not exe.exists():
                raise RuntimeError(f"Falta el programa {exe}")
        if _port_open(mercury.ARQ_PORT):
            raise RuntimeError(
                f"El puerto {mercury.ARQ_PORT} ya está en uso. ¿Hay otro Mercury o VARA abierto? Ciérrelo y reintente."
            )

        ini = data / "mercury.ini"
        ini.write_text(mercury.render_ini(s), encoding="utf-8")
        self.mercury = Child("Mercury", mercury.command(paths.mercury_exe(), ini),
                             paths.mercury_exe().parent, logs / "mercury.log")
        self.log("Iniciando Mercury…")
        self.mercury.start()
        if not _wait(lambda: _port_open(mercury.ARQ_PORT) or not self.mercury.running(), 20) \
                or not self.mercury.running():
            self.stop()
            raise RuntimeError(f"Mercury no arrancó. Revise {logs / 'mercury.log'}")
        self.log("Mercury listo.")

        self.http_port = free_port()
        pat.write_config(pat.build_config(s.callsign, self.http_port), pdir / "config.json")
        self.pat = Child("Pat", pat.command(paths.pat_exe(), s.callsign, pdir, self.http_port),
                         pdir, logs / "pat-console.log", pat.environment(os.environ, pdir))
        self.log("Iniciando Pat…")
        self.pat.start()
        self.client = pat.PatClient(self.http_port)
        if not _wait(lambda: self.client.is_up() or not self.pat.running(), 20) or not self.pat.running():
            self.stop()
            raise RuntimeError(f"Pat no arrancó. Revise {logs / 'pat-console.log'}")
        self.events = pat.PatEvents(self.http_port, on_event)
        self.events.start()
        self.log(f"Pat listo. Escuchando en radio como {s.callsign}.")

    def stop(self) -> None:
        if self.client is not None and self.pat is not None and self.pat.running():
            try:
                self.client.disconnect()
            except pat.PatError:
                pass
        if self.events is not None:
            self.events.stop()
        for child in (self.pat, self.mercury):
            if child is not None:
                child.stop()
        # Safety: never leave the radio keyed if Mercury was killed during TX.
        if self.settings.radio == RADIO_IC7100 and self.settings.com_port:
            try:
                civ.set_ptt(self.settings.com_port, False)
            except Exception:  # noqa: BLE001 - best effort on shutdown
                pass
        self.mercury = self.pat = self.client = self.events = None
