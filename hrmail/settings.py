"""User settings, stored as JSON in the data folder."""

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from . import radios

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
    # Radio: a preset key (radios.PRESETS), radios.KEY_OTHER (model from Hamlib's list) or radios.KEY_VOX.
    radio_key: str = "ic7100"
    radio_name: str = "ICOM IC-7100"
    hamlib_model: int = 3070
    cat_protocol: str = radios.PROTO_ICOM
    ptt_method: str = radios.PTT_CAT
    com_port: str = ""  # CAT port (hamlib) or PTT port (serial), e.g. "COM3"
    baud: int = 19200
    civ_addr: str = "0x88"  # Icom/Xiegu only, "" otherwise
    serial_line: str = "rts"  # rts, dtr or both
    serial_invert: str = "none"  # none, rts, dtr or both
    cm108_gpio: int = 3
    input_device: str = ""  # Mercury capture device id (from mercury -z)
    output_device: str = ""  # Mercury playback device id (from mercury -z)

    def apply_preset(self, preset: radios.Preset) -> None:
        self.radio_key, self.radio_name = preset.key, preset.label
        self.hamlib_model, self.cat_protocol = preset.hamlib_model, preset.protocol
        self.baud, self.civ_addr = preset.baud, radios.format_civ(preset.civ_addr)
        if self.ptt_method == radios.PTT_VOX:
            self.ptt_method = radios.PTT_CAT

    def apply_hamlib_model(self, model: radios.HamlibModel) -> None:
        self.radio_key, self.radio_name = radios.KEY_OTHER, model.label
        self.hamlib_model = model.id
        self.cat_protocol = radios.protocol_for_manufacturer(model.mfg)
        self.civ_addr = ""
        if self.ptt_method == radios.PTT_VOX:
            self.ptt_method = radios.PTT_CAT

    def apply_vox(self) -> None:
        self.radio_key, self.radio_name = radios.KEY_VOX, "Radio o interfaz con VOX"
        self.hamlib_model, self.cat_protocol, self.civ_addr = 0, radios.PROTO_NONE, ""
        self.ptt_method = radios.PTT_VOX


def _migrate(raw: dict) -> dict:
    """Settings written by hr-mail 0.1.0 had radio = "ic7100" | "vox"."""
    legacy = raw.pop("radio", None)
    if legacy == "vox" and "ptt_method" not in raw:
        defaults = Settings()
        defaults.apply_vox()
        for key in ("radio_key", "radio_name", "hamlib_model", "cat_protocol", "civ_addr", "ptt_method"):
            raw[key] = getattr(defaults, key)
    return raw


def load(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    raw = _migrate(json.loads(path.read_text(encoding="utf-8")))
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in raw.items() if k in known})
    if s.ptt_method not in radios.PTT_METHODS:
        s.ptt_method = radios.PTT_CAT
    return s


def save(settings: Settings, path: Path) -> None:
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
