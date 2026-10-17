"""User settings, stored as JSON in the data folder."""

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

RADIO_IC7100 = "ic7100"
RADIO_VOX = "vox"

# Prefix (1-3 chars) + digit + suffix (0-4 chars), optional SSID "-1".."-15".
_CALLSIGN_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}(-([1-9]|1[0-5]))?$")


def normalize_callsign(text: str) -> str:
    return text.strip().upper()


def is_valid_callsign(text: str) -> bool:
    call = normalize_callsign(text)
    return bool(_CALLSIGN_RE.match(call)) and any(c.isalpha() for c in call)


@dataclass
class Settings:
    callsign: str = ""
    radio: str = RADIO_IC7100  # RADIO_IC7100 or RADIO_VOX
    com_port: str = ""  # IC-7100 CI-V port, e.g. "COM3"
    input_device: str = ""  # Mercury capture device id (from mercury -z)
    output_device: str = ""  # Mercury playback device id (from mercury -z)


def load(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in raw.items() if k in known})


def save(settings: Settings, path: Path) -> None:
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
