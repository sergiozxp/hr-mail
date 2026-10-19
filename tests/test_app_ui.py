"""Drives the radio settings in the real Tk window (runs on the Windows CI build)."""

from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")

from hrmail import app as app_mod  # noqa: E402
from hrmail import paths, radios  # noqa: E402


@pytest.fixture
def window(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(radios, "list_com_ports", lambda: ["COM3", "COM7", "COM8"])
    monkeypatch.setattr(radios, "describe_com_ports",
                        lambda: {"COM7": "Enhanced COM Port", "COM8": "Standard COM Port"})
    monkeypatch.setattr(app_mod.App, "detect_audio", lambda self: None)
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.withdraw()
    window = app_mod.App(root)
    root.update_idletasks()
    yield window
    root.destroy()


def _visible(widget) -> bool:
    return bool(widget.winfo_manager())


def _pick_radio(w, label: str) -> None:
    w.radio_var.set(label)
    w.on_radio_selected()


def _pick_method(w, method: str) -> None:
    w.method_var.set(app_mod.METHOD_LABELS[method])
    w.on_method_selected()


def test_default_is_ic7100_cat(window):
    assert window.radio_var.get() == "ICOM IC-7100"
    assert window.method_var.get() == app_mod.METHOD_LABELS[radios.PTT_CAT]
    assert _visible(window.port_row) and _visible(window.find_btn)
    assert not _visible(window.serial_row) and not _visible(window.cm108_row)
    assert window.port_box["values"][1] == "COM7 — Enhanced COM Port"


def test_select_ft710_and_switch_methods(window):
    _pick_radio(window, "Yaesu FT-710")
    s = window.settings
    assert (s.hamlib_model, s.baud, s.cat_protocol) == (1049, 38400, radios.PROTO_YAESU)
    assert window.baud_var.get() == "38400" and "CAT RATE" in window.hint_var.get()

    window.port_var.set("COM8 — Standard COM Port")
    _pick_method(window, radios.PTT_SERIAL)
    assert s.com_port == "COM8" and _visible(window.serial_row) and not _visible(window.find_btn)

    _pick_method(window, radios.PTT_CM108)
    assert _visible(window.cm108_row) and not _visible(window.port_row)

    _pick_method(window, radios.PTT_VOX)
    assert str(window.ptt_btn["state"]) == "disabled"


def test_radio_without_cat(window):
    _pick_radio(window, app_mod.RADIO_VOX_LABEL)
    assert window.settings.ptt_method == radios.PTT_VOX
    assert app_mod.METHOD_LABELS[radios.PTT_CAT] not in window.method_box["values"]
    _pick_radio(window, "ICOM IC-7300")
    assert window.settings.ptt_method == radios.PTT_CAT and window.settings.hamlib_model == 3073


def test_model_from_full_list(window):
    models = [radios.HamlibModel(1049, "Yaesu", "FT-710"), radios.HamlibModel(3999, "Icom", "IC-Test")]
    picker = app_mod.ModelPicker(window.root, models, window.on_model_picked)
    picker.query.set("icom")
    assert picker.listbox.size() == 1
    picker.listbox.selection_set(0)
    picker.accept()
    s = window.settings
    assert (s.radio_key, s.hamlib_model, s.cat_protocol) == (radios.KEY_OTHER, 3999, radios.PROTO_ICOM)
    assert window.radio_var.get() == "Icom IC-Test" and "Icom IC-Test" in window.radio_box["values"]


def test_collect_settings_saves(window, monkeypatch):
    window.call_var.set("xq2cg")
    window.settings.input_device = window.settings.output_device = "dev"
    _pick_radio(window, "Yaesu FT-710")
    window.port_var.set("COM7 — Enhanced COM Port")
    s = window._collect_settings()
    assert s is not None and (s.callsign, s.com_port) == ("XQ2CG", "COM7")
    assert (paths.data_dir() / "settings.json").exists()
