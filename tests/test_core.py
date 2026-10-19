import json
from pathlib import Path

from hrmail import mercury, pat
from hrmail import radios
from hrmail.settings import Settings, is_valid_callsign, load, save

# Real `mercury.exe -z` output from an IC-7100 station (Windows 11).
MERCURY_Z = """Loaded configuration from mercury.ini
playback devices:
device: name: 'Speakers (Realtek(R) Audio)'  id: '{0.0.0.00000000}.{64cf1dca-de5d-433e-91d9-d933fbe7cec1}'
device: name: 'Speakers (USB Audio CODEC )'  id: '{0.0.0.00000000}.{7333e327-bdcd-4a27-89f0-f61c1a213953}'  (system default)
capture devices:
device: name: 'Microphone Array (Intel┬® Smart Sound Technology for Digital Microphones)'  id: '{0.0.1.00000000}.{1538eb52-9665-4f16-b604-a75c0930d9d0}'
device: name: 'Microphone (USB Audio CODEC )'  id: '{0.0.1.00000000}.{18f7890a-8c72-427f-8642-c63bba6b876a}'  (system default)
"""


def test_parse_devices_and_pick_radio():
    playback, capture = mercury.parse_devices(MERCURY_Z)
    assert len(playback) == 2 and len(capture) == 2
    out_dev = mercury.pick_radio_device(playback)
    in_dev = mercury.pick_radio_device(capture)
    assert out_dev.id == "{0.0.0.00000000}.{7333e327-bdcd-4a27-89f0-f61c1a213953}"
    assert out_dev.is_default
    assert in_dev.id == "{0.0.1.00000000}.{18f7890a-8c72-427f-8642-c63bba6b876a}"


def test_pick_radio_device_ambiguous_returns_none():
    devs = [mercury.AudioDevice("USB Audio CODEC", "a"), mercury.AudioDevice("USB Audio CODEC", "b")]
    assert mercury.pick_radio_device(devs) is None
    assert mercury.pick_radio_device([mercury.AudioDevice("Realtek", "x")]) is None


def test_ini_ic7100_matches_verified_baseline():
    s = Settings(callsign="XQ2CG", com_port="COM3", input_device="IN-ID", output_device="OUT-ID")
    ini = mercury.render_ini(s)
    for line in ("input_device = IN-ID", "output_device = OUT-ID", "arq_tcp_base_port = 8300",
                 "method = hamlib", "device = COM3", "hamlib_model = 3070",
                 "hamlib_serial_speed = 19200", "hamlib_conf = civaddr=0x88", "ui_enabled = false"):
        assert line in ini.splitlines()


def test_ini_vox_has_no_ptt():
    s = Settings(callsign="XQ2CG", input_device="I", output_device="O")
    s.apply_vox()
    ini = mercury.render_ini(s)
    assert "method = none" in ini.splitlines()
    assert "hamlib" not in ini


def test_pat_config_is_complete_and_p2p_ready():
    cfg = pat.build_config("XQ2CG", 54321)
    assert cfg["mycall"] == "XQ2CG"
    assert cfg["listen"] == ["varahf"]
    assert cfg["varahf"] == {"addr": "localhost:8300", "bandwidth": 2300, "rig": "", "ptt_ctrl": False}
    assert cfg["http_addr"] == "localhost:54321"
    assert cfg["version_reporting_disabled"] is True
    # Defaults must not be mutated between calls.
    assert pat.build_config("XQ2AB", 1)["mycall"] == "XQ2AB" and cfg["mycall"] == "XQ2CG"


def test_pat_command_uses_private_folders(tmp_path: Path):
    cmd = pat.command(Path("pat.exe"), "XQ2CG", tmp_path, 54321)
    assert cmd[cmd.index("--config") + 1] == str(tmp_path / "config.json")
    assert cmd[cmd.index("--mbox") + 1] == str(tmp_path / "mailbox")
    assert cmd[-3:] == ["http", "--addr", "localhost:54321"]


def test_callsigns():
    for ok in ("XQ2CG", "xq2cg", "XQ2TEST", "CE2ABC", "K1A", "XQ2CG-1"):
        assert is_valid_callsign(ok), ok
    for bad in ("", "HELLO", "XQ2CG/P", "12345678", "XQ2CG-99"):
        assert not is_valid_callsign(bad), bad


def test_settings_roundtrip(tmp_path: Path):
    path = tmp_path / "settings.json"
    s = Settings(callsign="XQ2CG", com_port="COM3", input_device="I", output_device="O")
    save(s, path)
    assert load(path) == s
    path.write_text(json.dumps({"callsign": "XQ2CG", "unknown_key": 1}))
    assert load(path).callsign == "XQ2CG"
