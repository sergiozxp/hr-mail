"""Minimal ICOM CI-V over a serial port (IC-7100): probe and PTT."""

import serial  # pyserial
from serial.tools import list_ports

CONTROLLER = 0xE0


def _frame(radio_addr: int, *payload: int) -> bytes:
    return bytes([0xFE, 0xFE, radio_addr, CONTROLLER, *payload, 0xFD])


def list_com_ports() -> list[str]:
    return sorted(p.device for p in list_ports.comports())


def _transact(port: str, baud: int, frame: bytes, timeout: float) -> bytes:
    with serial.Serial(port, baud, timeout=timeout, write_timeout=timeout) as ser:
        # Keep RTS/DTR low: on some setups they key the radio (see mercury.ini.example).
        ser.rts = False
        ser.dtr = False
        ser.reset_input_buffer()
        ser.write(frame)
        return ser.read(64)


def probe(port: str, radio_addr: int = 0x88, baud: int = 19200, timeout: float = 0.5) -> bool:
    """True if an ICOM radio at radio_addr answers 'read frequency' on this port."""
    try:
        reply = _transact(port, baud, _frame(radio_addr, 0x03), timeout)
    except (serial.SerialException, OSError):
        return False
    # The answer comes from the radio to us: FE FE E0 <radio> 03 ...
    return bytes([0xFE, 0xFE, CONTROLLER, radio_addr, 0x03]) in reply


def set_ptt(port: str, on: bool, radio_addr: int = 0x88, baud: int = 19200) -> None:
    _transact(port, baud, _frame(radio_addr, 0x1C, 0x00, 0x01 if on else 0x00), timeout=0.5)
