"""Pat: config generation, command line, and a small HTTP + websocket client.

Endpoints and behaviour verified against Pat v1.0.0 source; see docs/pat-api.md.
"""

import copy
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .mercury import ARQ_PORT

# Pat 1.0.0 default config.json (as written by `pat init`). Pat does not fill in
# missing keys, so hr-mail always writes a complete config.
_PAT_DEFAULT_CONFIG = {
    "mycall": "",
    "secure_login_password": "",
    "auxiliary_addresses": [],
    "locator": "",
    "auto_download_size_limit": -1,
    "service_codes": ["PUBLIC"],
    "http_addr": "localhost:8080",
    "motd": ["Open source Winlink client - getpat.io"],
    "connect_aliases": {"telnet": "telnet://{mycall}:CMSTelnet@cms.winlink.org:8772/wl2k"},
    "listen": [],
    "hamlib_rigs": {},
    "ax25": {
        "engine": "agwpe",
        "rig": "",
        "beacon": {"every": 3600, "message": "Winlink P2P", "destination": "IDENT"},
    },
    "ax25_linux": {"port": "wl2k"},
    "agwpe": {"addr": "localhost:8000", "radio_port": 0},
    "serial-tnc": {"path": "/dev/ttyUSB0", "serial_baud": 9600, "hbaud": 1200, "type": "kenwood"},
    "ardop": {
        "addr": "localhost:8515",
        "arq_bandwidth": {"Forced": False, "Max": 500},
        "connect_requests": 10,
        "rig": "",
        "ptt_ctrl": False,
        "beacon_interval": 0,
        "cwid_enabled": True,
    },
    "pactor": {"path": "/dev/ttyUSB0", "baudrate": 57600, "rig": "", "custom_init_script": ""},
    "telnet": {"listen_addr": ":8774", "password": ""},
    "varahf": {"addr": "localhost:8300", "bandwidth": 2300, "rig": "", "ptt_ctrl": False},
    "varafm": {"addr": "localhost:8300", "rig": "", "ptt_ctrl": False},
    "gpsd": {
        "enable_http": False,
        "allow_forms": False,
        "use_server_time": False,
        "update_locator": False,
        "addr": "localhost:2947",
    },
    "schedule": {},
    "version_reporting_disabled": False,
}

PROMPT_PRE_ACCOUNT_ACTIVATION = "pre-account-activation"


def build_config(callsign: str, http_port: int) -> dict:
    config = copy.deepcopy(_PAT_DEFAULT_CONFIG)
    config["mycall"] = callsign
    config["http_addr"] = f"localhost:{http_port}"
    config["listen"] = ["varahf"]
    config["varahf"]["addr"] = f"localhost:{ARQ_PORT}"
    config["varahf"]["ptt_ctrl"] = False  # Mercury keys the radio
    config["version_reporting_disabled"] = True
    return config


def write_config(config: dict, path: Path) -> None:
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def command(pat_exe: Path, callsign: str, pat_dir: Path, http_port: int) -> list[str]:
    return [
        str(pat_exe),
        "--mycall", callsign,
        "--config", str(pat_dir / "config.json"),
        "--mbox", str(pat_dir / "mailbox"),
        "--forms", str(pat_dir / "forms"),
        "--log", str(pat_dir / "pat.log"),
        "--event-log", str(pat_dir / "eventlog.json"),
        "--listen", "varahf",
        "http", "--addr", f"localhost:{http_port}",
    ]


def environment(base_env: dict, pat_dir: Path) -> dict:
    """XDG folders for Pat's own state files, kept inside hr-mail's data folder."""
    env = dict(base_env)
    env["XDG_CONFIG_HOME"] = str(pat_dir / "xdg-config")
    env["XDG_DATA_HOME"] = str(pat_dir / "xdg-data")
    env["XDG_STATE_HOME"] = str(pat_dir / "xdg-state")
    return env


class PatError(Exception):
    pass


class PatClient:
    """Pat's local HTTP API."""

    def __init__(self, http_port: int):
        self.base = f"http://localhost:{http_port}"

    def _request(self, method: str, path: str, data: dict | None = None, timeout: float | None = 10):
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raise PatError(f"{exc.code} {exc.read().decode('utf-8', 'replace').strip()}") from exc
        except OSError as exc:
            raise PatError(str(exc)) from exc

    def is_up(self) -> bool:
        try:
            self.status()
            return True
        except PatError:
            return False

    def status(self) -> dict:
        return json.loads(self._request("GET", "/api/status")[1])

    def mailbox(self, box: str) -> list[dict]:
        """box: "in", "out", "sent" or "archive". Newest first, without body."""
        return json.loads(self._request("GET", f"/api/mailbox/{box}")[1]) or []

    def message(self, box: str, mid: str) -> dict:
        return json.loads(self._request("GET", f"/api/mailbox/{box}/{urllib.parse.quote(mid)}")[1])

    def compose(self, to: str, subject: str, body: str) -> None:
        """Queue a P2P-only message. Pat sends it P2P only if `to` is its sole recipient."""
        date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._request("POST", "/api/mailbox/out", {
            "to": to, "subject": subject, "body": body, "date": date, "p2ponly": "true",
        })

    def connect(self, callsign: str) -> int:
        """Connect to a station over Mercury and exchange mail. Blocks until done.

        Returns the number of messages received. Raises PatError on failure.
        """
        url = urllib.parse.quote(f"varahf:///{callsign}", safe="")
        _, text = self._request("POST", f"/api/connect?url={url}", timeout=None)
        return int(json.loads(text).get("NumReceived", 0))

    def disconnect(self) -> None:
        self._request("POST", "/api/disconnect")


class PatEvents:
    """Permanent websocket to Pat: live events, and auto-answer of the account prompt."""

    def __init__(self, http_port: int, on_event: Callable[[str, object], None]):
        self.url = f"ws://localhost:{http_port}/ws"
        self.on_event = on_event
        self._ws = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="pat-ws", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            self._ws.close()

    def _run(self) -> None:
        import websocket  # websocket-client

        while not self._stop.is_set():
            self._ws = websocket.WebSocketApp(self.url, on_message=self._on_message)
            self._ws.run_forever(ping_interval=30, ping_timeout=10)
            self._stop.wait(2)  # reconnect after Pat restarts or drops us

    def _on_message(self, ws, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        for kind, payload in msg.items():
            if kind == "Ping":
                continue
            if kind == "Prompt" and payload.get("kind") == PROMPT_PRE_ACCOUNT_ACTIVATION:
                # P2P only: no Winlink account is needed. Answer so the connect goes on.
                ws.send(json.dumps({"prompt_response": {"id": payload["id"], "value": "confirmed"}}))
                self.on_event("AutoAnswered", payload)
                continue
            self.on_event(kind, payload)
