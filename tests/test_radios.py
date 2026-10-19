import json
from pathlib import Path

import pytest

from hrmail import mercury, radios, station
from hrmail.settings import Settings, load


class FakeRadio:
    """Stands in for radios._transact: one radio on one port, answering at one speed."""

    def __init__(self, port: str, baud: int, kind: str, civ_addr: int = 0x94):
        self.port, self.baud, self.kind, self.civ_addr = port, baud, kind, civ_addr
        self.writes: list[tuple[str, int, bytes]] = []

    def __call__(self, port, baud, data, timeout, read=64):
        self.writes.append((port, baud, data))
        if port != self.port or baud != self.baud:
            return b""
        if self.kind == "icom" and data[:2] == b"\xFE\xFE" and data[4] == 0x03:
            if data[2] in (self.civ_addr, 0x00):
                # Echo of our frame (USB echo on), then the radio's answer.
                return data + bytes([0xFE, 0xFE, 0xE0, self.civ_addr, 0x03, 0, 0, 0x07, 0x14, 0, 0xFD])
        if self.kind == "ascii" and b"FA;" in data:
            return b"?;FA014070000;"
        return b""


@pytest.fixture
def two_ports(monkeypatch):
    monkeypatch.setattr(radios, "list_com_ports", lambda: ["COM3", "COM7", "COM8"])


def _no_tx(fake: FakeRadio) -> None:
    for _port, _baud, data in fake.writes:
        assert b"TX1" not in data and b"TX;" not in data
        assert not (data[:2] == b"\xFE\xFE" and data[4] == 0x1C), "probing must never key the radio"


def test_find_ft710_on_enhanced_port(monkeypatch, two_ports):
    fake = FakeRadio("COM7", 38400, "ascii")
    monkeypatch.setattr(radios, "_transact", fake)
    preset = radios.PRESETS_BY_KEY["ft710"]
    found = radios.find_radio(preset.protocol, preset.baud, preset.civ_addr)
    assert found == radios.ProbeResult("COM7", 38400)
    _no_tx(fake)


def test_find_yaesu_at_factory_4800(monkeypatch, two_ports):
    fake = FakeRadio("COM8", 4800, "ascii")
    monkeypatch.setattr(radios, "_transact", fake)
    assert radios.find_radio(radios.PROTO_YAESU, 38400) == radios.ProbeResult("COM8", 4800)


def test_find_icom_with_preset_address(monkeypatch, two_ports):
    fake = FakeRadio("COM3", 115200, "icom", civ_addr=0x94)
    monkeypatch.setattr(radios, "_transact", fake)
    found = radios.find_radio(radios.PROTO_ICOM, 19200, 0x94)
    assert found == radios.ProbeResult("COM3", 115200, 0x94)
    _no_tx(fake)


def test_find_icom_style_radio_by_broadcast(monkeypatch, two_ports):
    fake = FakeRadio("COM8", 19200, "icom", civ_addr=0x88)  # e.g. a Xiegu, address unknown to us
    monkeypatch.setattr(radios, "_transact", fake)
    assert radios.find_radio(radios.PROTO_ICOM, 19200, None).civ_addr == 0x88


def test_no_probe_for_unknown_protocol(monkeypatch, two_ports):
    fake = FakeRadio("COM3", 9600, "ascii")
    monkeypatch.setattr(radios, "_transact", fake)
    assert radios.find_radio(radios.PROTO_NONE, 9600) is None
    assert fake.writes == []


@pytest.mark.parametrize("protocol, expected", [
    (radios.PROTO_ICOM, bytes([0xFE, 0xFE, 0x94, 0xE0, 0x1C, 0x00, 0x00, 0xFD])),
    (radios.PROTO_YAESU, b"TX0;"),
    (radios.PROTO_KENWOOD, b"RX;"),  # Kenwood "TX0;" would KEY the radio
])
def test_release_ptt_commands(monkeypatch, protocol, expected):
    fake = FakeRadio("COM3", 19200, "none")
    monkeypatch.setattr(radios, "_transact", fake)
    radios.release_ptt(protocol, "COM3", 19200, 0x94)
    assert fake.writes == [("COM3", 19200, expected)]


def test_release_ptt_only_for_cat(monkeypatch):
    fake = FakeRadio("COM3", 19200, "none")
    monkeypatch.setattr(radios, "_transact", fake)
    s = Settings(com_port="COM3")
    for method in (radios.PTT_SERIAL, radios.PTT_CM108, radios.PTT_VOX):
        s.ptt_method = method
        station.release_ptt(s)
    assert fake.writes == []
    s.ptt_method = radios.PTT_CAT
    s.apply_hamlib_model(radios.HamlibModel(1020, "Yaesu", "FT-817"))  # binary CAT: hr-mail stays out
    station.release_ptt(s)
    assert fake.writes == []


# Built with the same printf as Mercury's list_models (Hamlib rigctl -l layout).
def _model_line(i, mfg, model, ver="20240101.0", status="Stable", port="RS232", macro="RIG_MODEL_X"):
    return "%6d  %-23s%-24s%-16s%-12s%-8s%s" % (i, mfg, model, ver, status, port, macro)


MERCURY_K = "\n".join([
    " Rig #  Mfg                    Model                   Version         Status      Port    Macro",
    _model_line(1, "Hamlib", "Dummy", port="None"),
    _model_line(2, "Hamlib", "NET rigctl", port="Network"),
    _model_line(1049, "Yaesu", "FT-710"),
    _model_line(3070, "Icom", "IC-7100"),
    _model_line(3088, "Xiegu", "G90"),
    _model_line(2999, "Kenwood", "A-very-long-model-name-xx"),  # fills its column completely
])


def test_parse_model_list():
    models = radios.parse_model_list(MERCURY_K)
    by_id = {m.id: m for m in models}
    assert by_id[1049] == radios.HamlibModel(1049, "Yaesu", "FT-710")
    assert by_id[3070].label == "Icom IC-7100"
    assert by_id[2999].model.startswith("A-very-long-model-name")
    assert radios.protocol_for_manufacturer(by_id[3088].mfg) == radios.PROTO_ICOM
    assert radios.protocol_for_manufacturer(by_id[1049].mfg) == radios.PROTO_NONE


def test_presets_are_consistent():
    keys = [p.key for p in radios.PRESETS]
    assert len(keys) == len(set(keys))
    assert radios.KEY_VOX not in keys and radios.KEY_OTHER not in keys
    # Spot checks against Hamlib 4.6.5 riglist.h (RIG_MAKE_MODEL(backend, n) = backend * 1000 + n).
    expected = {"ic7100": 3070, "ic7300": 3073, "ic705": 3085, "ft710": 1049, "ft991": 1035,
                "ft891": 1036, "ftdx10": 1042, "ts590sg": 2037, "kx3": 2045, "g90": 3088}
    for key, model in expected.items():
        assert radios.PRESETS_BY_KEY[key].hamlib_model == model, key
    for p in radios.PRESETS:
        assert p.hint and "{" not in p.hint and p.baud in radios.BAUD_RATES


def test_ini_ft710_cat():
    s = Settings(callsign="XQ2CG", com_port="COM7", input_device="I", output_device="O")
    s.apply_preset(radios.PRESETS_BY_KEY["ft710"])
    lines = mercury.render_ini(s).splitlines()
    for line in ("method = hamlib", "device = COM7", "hamlib_model = 1049", "hamlib_serial_speed = 38400"):
        assert line in lines
    assert not any(line.startswith("hamlib_conf") for line in lines)


def test_ini_serial_and_cm108():
    s = Settings(com_port="COM9", input_device="I", output_device="O")
    s.apply_vox()
    s.ptt_method, s.serial_line, s.serial_invert = radios.PTT_SERIAL, "both", "rts"
    lines = mercury.render_ini(s).splitlines()
    for line in ("method = serial", "device = COM9", "line = both", "invert = rts"):
        assert line in lines
    s.ptt_method, s.cm108_gpio = radios.PTT_CM108, 3
    lines = mercury.render_ini(s).splitlines()
    assert "method = cm108" in lines and "cm108_gpio = 3" in lines
    assert not any(line.startswith("device") for line in lines)


def test_choosing_a_radio_after_vox_turns_cat_back_on():
    s = Settings()
    s.apply_vox()
    assert s.ptt_method == radios.PTT_VOX and s.hamlib_model == 0
    s.apply_preset(radios.PRESETS_BY_KEY["ic7300"])
    assert (s.ptt_method, s.hamlib_model, s.civ_addr) == (radios.PTT_CAT, 3073, "0x94")


def test_settings_from_v0_1_are_migrated(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"callsign": "XQ2CG", "radio": "vox", "com_port": "", "input_device": "I"}))
    s = load(path)
    assert (s.callsign, s.radio_key, s.ptt_method, s.input_device) == ("XQ2CG", radios.KEY_VOX, radios.PTT_VOX, "I")
    path.write_text(json.dumps({"callsign": "XQ2CG", "radio": "ic7100", "com_port": "COM3"}))
    s = load(path)
    assert (s.radio_key, s.hamlib_model, s.com_port, s.civ_addr, s.baud) == ("ic7100", 3070, "COM3", "0x88", 19200)


def test_civ_format_roundtrip():
    assert radios.format_civ(0x94) == "0x94" and radios.parse_civ("0x94") == 0x94
    assert radios.parse_civ("") is None and radios.parse_civ("zz") is None
