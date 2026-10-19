"""Radio presets, COM-port probing and PTT safety.

Mercury does the real radio control (Hamlib CAT, RTS/DTR, CM108). hr-mail only
needs to know which Hamlib model to ask for, find the right COM port and speed,
and make sure the transmitter is released when it shuts Mercury down.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import serial  # pyserial
from serial.tools import list_ports

# PTT methods, named exactly as Mercury's [ptt] method values.
PTT_CAT = "hamlib"
PTT_SERIAL = "serial"
PTT_CM108 = "cm108"
PTT_VOX = "none"
PTT_METHODS = (PTT_CAT, PTT_SERIAL, PTT_CM108, PTT_VOX)

# CAT command families hr-mail itself can speak (for probing and releasing PTT).
PROTO_ICOM = "icom"  # CI-V binary frames (Icom, Xiegu)
PROTO_YAESU = "yaesu"  # newer Yaesu ASCII CAT: FA; / TX0;
PROTO_KENWOOD = "kenwood"  # Kenwood / Elecraft ASCII CAT: FA; / RX;
PROTO_NONE = ""  # unknown: hr-mail leaves it all to Hamlib

KEY_VOX = "vox"
KEY_OTHER = "hamlib"  # a model picked from Hamlib's full list

BAUD_RATES = (4800, 9600, 19200, 38400, 57600, 115200)

CIV_CONTROLLER = 0xE0
CIV_BROADCAST = 0x00


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    hamlib_model: int
    baud: int
    protocol: str
    civ_addr: int | None = None  # Icom factory CI-V address
    hint: str = ""  # Spanish: radio menu settings to check


_ICOM_HINT = ("En la radio: CI-V USB Baud Rate = {baud} (o Auto), CI-V USB Echo Back = OFF, "
              "DATA MOD = USB, modo USB-D. USB SEND/Keying = OFF.")
_YAESU_HINT = ("En la radio: CAT RATE = {baud}, modo DATA-U con entrada de audio por USB. "
               "Use el puerto COM \"Enhanced\" (Buscar radio lo encuentra).")
_KENWOOD_HINT = "En la radio: velocidad del puerto USB/COM = {baud}, modo DATA con audio por USB."
_ELECRAFT_HINT = "En la radio: RS232/USB = {baud} baudios, modo DATA A."
_XIEGU_HINT = "En la radio: CI-V Baud = {baud}. Necesita interfaz de audio (por ejemplo Digirig o DE-19)."


def _p(key, label, model, baud, proto, civ=None, hint=""):
    return Preset(key, label, model, baud, proto, civ, hint.format(baud=baud))


# Hamlib 4.6.5 model numbers (the Hamlib bundled with Mercury 1.9.19), from riglist.h.
PRESETS: tuple[Preset, ...] = (
    # IC-7100 values verified with a real radio (SPEC.md section 1).
    _p("ic7100", "ICOM IC-7100", 3070, 19200, PROTO_ICOM, 0x88,
       "En la radio: Set > Connectors > CI-V USB Baud Rate = 19200, DATA MOD = USB, modo USB-D."),
    _p("ic7300", "ICOM IC-7300", 3073, 19200, PROTO_ICOM, 0x94, _ICOM_HINT),
    _p("ic705", "ICOM IC-705", 3085, 19200, PROTO_ICOM, 0xA4, _ICOM_HINT),
    _p("ic7610", "ICOM IC-7610", 3078, 19200, PROTO_ICOM, 0x98, _ICOM_HINT),
    _p("ic9700", "ICOM IC-9700", 3081, 19200, PROTO_ICOM, 0xA2, _ICOM_HINT),
    _p("ic7600", "ICOM IC-7600", 3063, 19200, PROTO_ICOM, 0x7A, _ICOM_HINT),
    _p("ic7410", "ICOM IC-7410", 3067, 19200, PROTO_ICOM, 0x80, _ICOM_HINT),
    _p("ic7200", "ICOM IC-7200", 3061, 19200, PROTO_ICOM, 0x76, _ICOM_HINT),
    _p("ft710", "Yaesu FT-710", 1049, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ft991", "Yaesu FT-991 / FT-991A", 1035, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ft891", "Yaesu FT-891", 1036, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ftdx10", "Yaesu FTDX10", 1042, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ftdx101", "Yaesu FTDX101D / MP", 1040, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ftdx3000", "Yaesu FTDX3000", 1037, 38400, PROTO_YAESU, None, _YAESU_HINT),
    _p("ts590sg", "Kenwood TS-590SG", 2037, 115200, PROTO_KENWOOD, None, _KENWOOD_HINT),
    _p("ts590s", "Kenwood TS-590S", 2031, 115200, PROTO_KENWOOD, None, _KENWOOD_HINT),
    _p("ts890s", "Kenwood TS-890S", 2041, 115200, PROTO_KENWOOD, None, _KENWOOD_HINT),
    _p("ts480", "Kenwood TS-480", 2028, 9600, PROTO_KENWOOD, None, _KENWOOD_HINT),
    _p("k3", "Elecraft K3 / K3S", 2029, 38400, PROTO_KENWOOD, None, _ELECRAFT_HINT),
    _p("kx3", "Elecraft KX3", 2045, 38400, PROTO_KENWOOD, None, _ELECRAFT_HINT),
    _p("kx2", "Elecraft KX2", 2044, 38400, PROTO_KENWOOD, None, _ELECRAFT_HINT),
    _p("k4", "Elecraft K4", 2047, 38400, PROTO_KENWOOD, None, _ELECRAFT_HINT),
    _p("g90", "Xiegu G90", 3088, 19200, PROTO_ICOM, None, _XIEGU_HINT),
    _p("x6100", "Xiegu X6100", 3087, 19200, PROTO_ICOM, None, _XIEGU_HINT),
)

PRESETS_BY_KEY = {p.key: p for p in PRESETS}


def protocol_for_manufacturer(mfg: str) -> str:
    """Best guess for a model from the full Hamlib list. Only Icom-style CI-V is safe to guess."""
    return PROTO_ICOM if mfg.strip().lower() in ("icom", "xiegu") else PROTO_NONE


# ---------- Hamlib model list (mercury -K) ----------

@dataclass(frozen=True)
class HamlibModel:
    id: int
    mfg: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.mfg} {self.model}"


_MODEL_LINE = re.compile(r"^\s*(\d+)\s{2}(.+)$")


def parse_model_list(text: str) -> list[HamlibModel]:
    """Parse `mercury -K` output (Hamlib's `rigctl -l` table)."""
    models = []
    for line in text.splitlines():
        match = _MODEL_LINE.match(line)
        if not match:
            continue
        rest = match[2]
        cols = re.split(r"\s{2,}", rest.strip())
        if len(cols) >= 2:
            mfg, model = cols[0], cols[1]
        else:  # a column filled its whole width: fall back to the fixed layout
            mfg, model = rest[:23].strip(), rest[23:47].strip()
        model_id = int(match[1])
        if model_id > 0 and mfg and model:
            models.append(HamlibModel(model_id, mfg, model))
    return models


def list_models(mercury_exe: Path, timeout: float = 60) -> list[HamlibModel]:
    result = subprocess.run(
        [str(mercury_exe), "-K"],
        cwd=str(mercury_exe.parent),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_no_window(),
    )
    models = parse_model_list(result.stdout)
    # Hamlib's dummy/network pseudo-radios are no use here.
    return [m for m in models if m.mfg.lower() not in ("hamlib", "dummy")]


def test_ptt(mercury_exe: Path, ini_path: Path, timeout: float = 30) -> tuple[bool, str]:
    """Key the configured PTT for one second with `mercury -Q`. Returns (ok, output)."""
    result = subprocess.run(
        [str(mercury_exe), "-C", str(ini_path), "-Q"],
        cwd=str(mercury_exe.parent),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=_no_window(),
    )
    return result.returncode == 0, (result.stdout + "\n" + result.stderr).strip()


# ---------- serial port helpers ----------

def list_com_ports() -> list[str]:
    return sorted((p.device for p in list_ports.comports()), key=_port_sort_key)


def describe_com_ports() -> dict[str, str]:
    """COM port -> Windows description, e.g. 'Silicon Labs Dual CP2105 ... Enhanced COM Port'."""
    return {p.device: (p.description or "") for p in list_ports.comports()}


def _port_sort_key(name: str):
    match = re.search(r"(\d+)$", name)
    return (name.rstrip("0123456789"), int(match[1]) if match else 0)


def _transact(port: str, baud: int, data: bytes, timeout: float, read: int = 64) -> bytes:
    ser = serial.Serial()
    ser.port, ser.baudrate = port, baud
    ser.timeout = ser.write_timeout = timeout
    # Keep RTS/DTR low from the moment the port opens: on many setups they key the radio.
    ser.rts = False
    ser.dtr = False
    ser.open()
    try:
        ser.reset_input_buffer()
        ser.write(data)
        return ser.read(read) if read else b""
    finally:
        ser.close()


def civ_frame(radio_addr: int, *payload: int) -> bytes:
    return bytes([0xFE, 0xFE, radio_addr, CIV_CONTROLLER, *payload, 0xFD])


_CIV_FREQ_REPLY = re.compile(rb"\xFE\xFE\xE0(.)\x03", re.DOTALL)
_ASCII_FREQ_REPLY = re.compile(rb"FA\d{8,11};")


def _probe_icom(port: str, baud: int, addrs: list[int]) -> int | None:
    """CI-V address of the radio that answers 'read frequency', or None."""
    for addr in addrs:
        try:
            reply = _transact(port, baud, civ_frame(addr, 0x03), 0.4)
        except (serial.SerialException, OSError, ValueError):
            return None
        match = _CIV_FREQ_REPLY.search(reply)
        if match:
            return match[1][0]
    return None


def _probe_ascii(port: str, baud: int) -> bool:
    try:
        reply = _transact(port, baud, b";FA;", 0.4)
    except (serial.SerialException, OSError, ValueError):
        return False
    return bool(_ASCII_FREQ_REPLY.search(reply))


@dataclass(frozen=True)
class ProbeResult:
    port: str
    baud: int
    civ_addr: int | None = None


def probe_port(port: str, protocol: str, first_baud: int, civ_addr: int | None = None) -> ProbeResult | None:
    """Try the usual CAT speeds on one port. Never transmits."""
    bauds = [first_baud] + [b for b in (38400, 19200, 115200, 9600, 4800, 57600) if b != first_baud]
    for baud in bauds:
        if protocol == PROTO_ICOM:
            addrs = [a for a in (civ_addr, CIV_BROADCAST) if a is not None]
            found = _probe_icom(port, baud, addrs)
            if found is not None:
                return ProbeResult(port, baud, found)
        elif protocol in (PROTO_YAESU, PROTO_KENWOOD):
            if _probe_ascii(port, baud):
                return ProbeResult(port, baud)
        else:
            return None
    return None


def find_radio(protocol: str, first_baud: int, civ_addr: int | None = None,
               ports: list[str] | None = None) -> ProbeResult | None:
    for port in ports if ports is not None else list_com_ports():
        result = probe_port(port, protocol, first_baud, civ_addr)
        if result:
            return result
    return None


def release_ptt(protocol: str, port: str, baud: int, civ_addr: int | None) -> None:
    """Best-effort 'stop transmitting' over CAT, used after Mercury is stopped."""
    if not port:
        return
    if protocol == PROTO_ICOM and civ_addr is not None:
        _transact(port, baud, civ_frame(civ_addr, 0x1C, 0x00, 0x00), 0.5, read=0)
    elif protocol == PROTO_YAESU:
        _transact(port, baud, b"TX0;", 0.5, read=0)
    elif protocol == PROTO_KENWOOD:
        _transact(port, baud, b"RX;", 0.5, read=0)


def format_civ(addr: int | None) -> str:
    return "" if addr is None else f"0x{addr:02X}"


def parse_civ(text: str) -> int | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        value = int(text, 16)
    except ValueError:
        return None
    return value if 0 <= value <= 0xFF else None


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)
