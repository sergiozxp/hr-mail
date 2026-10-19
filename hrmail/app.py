"""Stage 1 window: start Mercury + Pat, queue a test message, connect, list mail.

This is a diagnostic tool for the developer. The setup wizard (Stage 3) and the
real main window (Stage 4) replace it.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, mercury, paths, radios
from . import settings as settings_mod
from .pat import PatError
from .settings import Settings, is_valid_callsign, normalize_callsign
from .station import Station
from .station import test_ptt as run_ptt_test

RADIO_OTHER_LABEL = "Otro modelo (lista completa de hamlib)…"
RADIO_VOX_LABEL = "Otra radio sin CAT (VOX, Digirig, CM108)"
METHOD_LABELS = {
    radios.PTT_CAT: "CAT por el cable USB de la radio (recomendado)",
    radios.PTT_SERIAL: "Línea RTS/DTR de un puerto COM (Digirig, AIOC, cable casero)",
    radios.PTT_CM108: "Interfaz con chip CM108 (GPIO)",
    radios.PTT_VOX: "VOX (la radio transmite sola con el audio)",
}
METHOD_BY_LABEL = {label: key for key, label in METHOD_LABELS.items()}
LINE_LABELS = {"rts": "RTS", "dtr": "DTR", "both": "RTS y DTR"}
INVERT_LABELS = {"none": "Ninguna", "rts": "RTS", "dtr": "DTR", "both": "RTS y DTR"}
PORT_SEPARATOR = " — "


def _key_for(labels: dict[str, str], label: str, default: str) -> str:
    return next((k for k, v in labels.items() if v == label), default)


class ModelPicker:
    """Searchable list of every radio Hamlib knows, mouse-friendly."""

    def __init__(self, root: tk.Tk, models: list, on_done):
        self.models, self.on_done = models, on_done
        self.shown: list = []
        self.top = top = tk.Toplevel(root)
        top.title("Elegir modelo de radio")
        top.transient(root)
        top.geometry("520x480")
        top.protocol("WM_DELETE_WINDOW", self.cancel)
        frm = ttk.Frame(top, padding=10)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Buscar (marca o modelo):").pack(anchor="w")
        self.query = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.query)
        entry.pack(fill="x", pady=(2, 6))
        self.query.trace_add("write", lambda *_: self.filter())
        lst = ttk.Frame(frm)
        lst.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(lst, activestyle="dotbox")
        bar = ttk.Scrollbar(lst, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=bar.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda _e: self.accept())
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Cancelar", command=self.cancel).pack(side="right", padx=4)
        ttk.Button(btns, text="Elegir", command=self.accept).pack(side="right", padx=4)
        self.filter()
        entry.focus_set()
        try:
            top.grab_set()
        except tk.TclError:  # parent not viewable yet
            pass

    def filter(self) -> None:
        words = self.query.get().lower().split()
        self.shown = [m for m in self.models if all(w in f"{m.mfg} {m.model}".lower() for w in words)]
        self.listbox.delete(0, "end")
        for m in self.shown:
            self.listbox.insert("end", f"{m.mfg}  {m.model}")

    def accept(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            return
        model = self.shown[sel[0]]
        self.top.destroy()
        self.on_done(model)

    def cancel(self) -> None:
        self.top.destroy()
        self.on_done(None)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings_path = paths.data_dir() / "settings.json"
        self.settings = settings_mod.load(self.settings_path)
        self.station: Station | None = None
        self.busy = False
        self.ui_queue: queue.Queue = queue.Queue()
        self.devices: tuple[list, list] = ([], [])
        self.hamlib_models: list = []

        root.title(f"hr-mail {__version__} — diagnóstico")
        root.minsize(780, 640)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.root.after(100, self._drain_queue)
        self.refresh_ports()
        self.detect_audio()

    # ---------- layout ----------
    def _build(self) -> None:
        pad = {"padx": 6, "pady": 4}
        frm = ttk.Frame(self.root, padding=10)
        frm.pack(fill="both", expand=True)

        cfg = ttk.LabelFrame(frm, text="Estación", padding=8)
        cfg.pack(fill="x")
        cfg.columnconfigure(0, weight=1)

        row = ttk.Frame(cfg)
        row.grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="Su indicativo:", width=14).pack(side="left", **pad)
        self.call_var = tk.StringVar(value=self.settings.callsign)
        ttk.Entry(row, textvariable=self.call_var, width=12).pack(side="left", **pad)

        row = ttk.Frame(cfg)
        row.grid(row=1, column=0, sticky="w")
        ttk.Label(row, text="Radio:", width=14).pack(side="left", **pad)
        self.radio_var = tk.StringVar()
        self.radio_box = ttk.Combobox(row, textvariable=self.radio_var, width=40, state="readonly", height=20)
        self.radio_box.pack(side="left", **pad)
        self.radio_box.bind("<<ComboboxSelected>>", self.on_radio_selected)

        row = ttk.Frame(cfg)
        row.grid(row=2, column=0, sticky="w")
        ttk.Label(row, text="Conexión PTT:", width=14).pack(side="left", **pad)
        self.method_var = tk.StringVar()
        self.method_box = ttk.Combobox(row, textvariable=self.method_var, width=58, state="readonly")
        self.method_box.pack(side="left", **pad)
        self.method_box.bind("<<ComboboxSelected>>", self.on_method_selected)

        self.port_row = ttk.Frame(cfg)
        self.port_row.grid(row=3, column=0, sticky="w")
        ttk.Label(self.port_row, text="Puerto COM:", width=14).pack(side="left", **pad)
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(self.port_row, textvariable=self.port_var, width=40, state="readonly")
        self.port_box.pack(side="left", **pad)
        self.baud_label = ttk.Label(self.port_row, text="Velocidad:")
        self.baud_label.pack(side="left", **pad)
        self.baud_var = tk.StringVar(value=str(self.settings.baud))
        self.baud_box = ttk.Combobox(self.port_row, textvariable=self.baud_var, width=8, state="readonly",
                                     values=[str(b) for b in radios.BAUD_RATES])
        self.baud_box.pack(side="left", **pad)
        self.find_btn = ttk.Button(self.port_row, text="Buscar radio", command=self.find_radio)
        self.find_btn.pack(side="left", **pad)

        self.serial_row = ttk.Frame(cfg)
        self.serial_row.grid(row=4, column=0, sticky="w")
        ttk.Label(self.serial_row, text="Línea PTT:", width=14).pack(side="left", **pad)
        self.line_var = tk.StringVar()
        ttk.Combobox(self.serial_row, textvariable=self.line_var, width=10, state="readonly",
                     values=list(LINE_LABELS.values())).pack(side="left", **pad)
        ttk.Label(self.serial_row, text="Activa en nivel bajo:").pack(side="left", **pad)
        self.invert_var = tk.StringVar()
        ttk.Combobox(self.serial_row, textvariable=self.invert_var, width=10, state="readonly",
                     values=list(INVERT_LABELS.values())).pack(side="left", **pad)

        self.cm108_row = ttk.Frame(cfg)
        self.cm108_row.grid(row=5, column=0, sticky="w")
        ttk.Label(self.cm108_row, text="GPIO CM108:", width=14).pack(side="left", **pad)
        self.gpio_var = tk.StringVar()
        ttk.Combobox(self.cm108_row, textvariable=self.gpio_var, width=4, state="readonly",
                     values=["1", "2", "3", "4"]).pack(side="left", **pad)
        ttk.Label(self.cm108_row, text="(la mayoría usa 3)").pack(side="left", **pad)

        self.hint_var = tk.StringVar()
        ttk.Label(cfg, textvariable=self.hint_var, wraplength=680, foreground="#555").grid(
            row=6, column=0, sticky="w", **pad)

        row = ttk.Frame(cfg)
        row.grid(row=7, column=0, sticky="w")
        self.ptt_btn = ttk.Button(row, text="Probar PTT (transmite 1 segundo)", command=self.test_ptt)
        self.ptt_btn.pack(side="left", **pad)

        row = ttk.Frame(cfg)
        row.grid(row=8, column=0, sticky="w")
        ttk.Label(row, text="Audio:", width=14).pack(side="left", **pad)
        self.audio_var = tk.StringVar(value="(sin detectar)")
        ttk.Label(row, textvariable=self.audio_var).pack(side="left", **pad)
        ttk.Button(row, text="Detectar audio", command=self.detect_audio).pack(side="left", **pad)

        self._show_radio_settings()

        run = ttk.LabelFrame(frm, text="Prueba", padding=8)
        run.pack(fill="x", pady=(8, 0))
        self.start_btn = ttk.Button(run, text="Iniciar estación", command=self.start_station)
        self.start_btn.grid(row=0, column=0, **pad)
        self.stop_btn = ttk.Button(run, text="Detener", command=self.stop_station, state="disabled")
        self.stop_btn.grid(row=0, column=1, **pad)

        ttk.Label(run, text="Otra estación:").grid(row=1, column=0, sticky="e", **pad)
        self.peer_var = tk.StringVar(value="XQ2TEST")
        ttk.Entry(run, textvariable=self.peer_var, width=12).grid(row=1, column=1, sticky="w", **pad)
        self.compose_btn = ttk.Button(run, text="Dejar mensaje de prueba", command=self.compose_test, state="disabled")
        self.compose_btn.grid(row=1, column=2, **pad)
        self.connect_btn = ttk.Button(run, text="Conectar y enviar/recibir", command=self.connect_peer, state="disabled")
        self.connect_btn.grid(row=1, column=3, **pad)
        self.inbox_btn = ttk.Button(run, text="Ver buzón", command=self.show_mailbox, state="disabled")
        self.inbox_btn.grid(row=1, column=4, **pad)

        self.status_var = tk.StringVar(value="Detenido")
        ttk.Label(frm, textvariable=self.status_var, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(8, 2))

        self.log_text = tk.Text(frm, height=14, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)

    # ---------- thread helpers ----------
    def log(self, text: str) -> None:
        self.ui_queue.put(("log", text))

    def set_status(self, text: str) -> None:
        self.ui_queue.put(("status", text))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, value = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self.log_text.configure(state="normal")
                self.log_text.insert("end", value.rstrip() + "\n")
                self.log_text.see("end")
                self.log_text.configure(state="disabled")
            elif kind == "status":
                self.status_var.set(value)
            elif kind == "call":
                value()
        self.root.after(100, self._drain_queue)

    def in_ui(self, fn) -> None:
        self.ui_queue.put(("call", fn))

    def run_bg(self, fn) -> None:
        if self.busy:
            return
        self.busy = True

        def wrapper():
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - show any failure to the user
                self.log(f"ERROR: {exc}")
                self.set_status("Error")
            finally:
                self.busy = False
                self.in_ui(self._update_buttons)

        threading.Thread(target=wrapper, daemon=True).start()

    def _update_buttons(self) -> None:
        running = self.station is not None
        self.start_btn.configure(state="disabled" if running else "normal")
        for btn in (self.stop_btn, self.compose_btn, self.connect_btn, self.inbox_btn):
            btn.configure(state="normal" if running else "disabled")

    # ---------- actions ----------
    # ---------- radio selection ----------
    def _radio_choices(self) -> list[str]:
        choices = [p.label for p in radios.PRESETS]
        if self.settings.radio_key == radios.KEY_OTHER:
            choices.append(self.settings.radio_name)
        return choices + [RADIO_OTHER_LABEL, RADIO_VOX_LABEL]

    def _allowed_methods(self) -> list[str]:
        if self.settings.radio_key == radios.KEY_VOX:
            return [radios.PTT_VOX, radios.PTT_SERIAL, radios.PTT_CM108]
        return [radios.PTT_CAT, radios.PTT_SERIAL, radios.PTT_CM108, radios.PTT_VOX]

    def _show_radio_settings(self) -> None:
        """Put self.settings into the widgets and show only the rows the PTT method needs."""
        s = self.settings
        self.radio_box["values"] = self._radio_choices()
        self.radio_var.set(RADIO_VOX_LABEL if s.radio_key == radios.KEY_VOX else s.radio_name)
        methods = self._allowed_methods()
        if s.ptt_method not in methods:
            s.ptt_method = methods[0]
        self.method_box["values"] = [METHOD_LABELS[m] for m in methods]
        self.method_var.set(METHOD_LABELS[s.ptt_method])
        self.baud_var.set(str(s.baud))
        self.line_var.set(LINE_LABELS.get(s.serial_line, LINE_LABELS["rts"]))
        self.invert_var.set(INVERT_LABELS.get(s.serial_invert, INVERT_LABELS["none"]))
        self.gpio_var.set(str(s.cm108_gpio))

        method = s.ptt_method
        uses_port = method in (radios.PTT_CAT, radios.PTT_SERIAL)
        self.port_row.grid() if uses_port else self.port_row.grid_remove()
        self.serial_row.grid() if method == radios.PTT_SERIAL else self.serial_row.grid_remove()
        self.cm108_row.grid() if method == radios.PTT_CM108 else self.cm108_row.grid_remove()
        for widget in (self.baud_label, self.baud_box, self.find_btn):
            widget.pack_forget()
        if method == radios.PTT_CAT:
            self.baud_label.pack(side="left", padx=6, pady=4)
            self.baud_box.pack(side="left", padx=6, pady=4)
            self.find_btn.pack(side="left", padx=6, pady=4)
        self.ptt_btn.configure(state="disabled" if method == radios.PTT_VOX else "normal")
        self.hint_var.set(self._hint())

    def _hint(self) -> str:
        s = self.settings
        preset = radios.PRESETS_BY_KEY.get(s.radio_key)
        if s.ptt_method == radios.PTT_CAT:
            if preset:
                return preset.hint + " Pulse Buscar radio para encontrar el puerto y la velocidad."
            if s.cat_protocol == radios.PROTO_ICOM:
                return "Pulse Buscar radio. Si no la encuentra, elija puerto y velocidad a mano y pulse Probar PTT."
            return ("Elija el puerto COM y la velocidad CAT que tiene configurados en la radio, "
                    "y pulse Probar PTT.")
        if s.ptt_method == radios.PTT_SERIAL:
            return ("Elija el puerto COM de la interfaz (Digirig, AIOC, cable casero) o el puerto "
                    "\"Standard\" de un Yaesu. Casi siempre la línea es RTS. Pulse Probar PTT.")
        if s.ptt_method == radios.PTT_CM108:
            return "La interfaz se detecta sola. Conecte solo una interfaz CM108 y pulse Probar PTT."
        return ("VOX: la radio pasa a transmitir sola al recibir audio. Active el VOX de la radio "
                "(o de la interfaz) y use un tiempo de VOX corto.")

    def _read_radio_widgets(self) -> None:
        """Copy the widgets into self.settings (radio choice is applied when selected)."""
        s = self.settings
        s.ptt_method = METHOD_BY_LABEL.get(self.method_var.get(), s.ptt_method)
        s.com_port = self.port_var.get().split(PORT_SEPARATOR)[0].strip()
        if self.baud_var.get().isdigit():
            s.baud = int(self.baud_var.get())
        s.serial_line = _key_for(LINE_LABELS, self.line_var.get(), "rts")
        s.serial_invert = _key_for(INVERT_LABELS, self.invert_var.get(), "none")
        if self.gpio_var.get().isdigit():
            s.cm108_gpio = int(self.gpio_var.get())

    def on_radio_selected(self, _event=None) -> None:
        self._read_radio_widgets()
        choice = self.radio_var.get()
        if choice == RADIO_OTHER_LABEL:
            self.open_model_list()
        elif choice == RADIO_VOX_LABEL:
            self.settings.apply_vox()
        elif choice != self.settings.radio_name or self.settings.radio_key == radios.KEY_VOX:
            preset = next((p for p in radios.PRESETS if p.label == choice), None)
            if preset:
                self.settings.apply_preset(preset)
        self._show_radio_settings()

    def on_method_selected(self, _event=None) -> None:
        self._read_radio_widgets()
        self._show_radio_settings()

    def open_model_list(self) -> None:
        if self.hamlib_models:
            ModelPicker(self.root, self.hamlib_models, self.on_model_picked)
            return

        def work():
            self.log("Leyendo la lista de radios de hamlib…")
            models = radios.list_models(paths.mercury_exe())
            if not models:
                self.log("No se pudo leer la lista de radios de Mercury.")
                return
            self.hamlib_models = models
            self.log(f"{len(models)} modelos disponibles.")
            self.in_ui(lambda: ModelPicker(self.root, models, self.on_model_picked))
        self.run_bg(work)

    def on_model_picked(self, model: "radios.HamlibModel | None") -> None:
        if model is not None:
            self._read_radio_widgets()
            self.settings.apply_hamlib_model(model)
            self.log(f"Radio elegida: {model.label} (hamlib {model.id}).")
        self._show_radio_settings()

    # ---------- ports and PTT ----------
    def refresh_ports(self) -> None:
        described = radios.describe_com_ports()
        values = [f"{port}{PORT_SEPARATOR}{described[port]}" if described.get(port) else port
                  for port in radios.list_com_ports()]
        self.port_box["values"] = values
        current = self.settings.com_port
        match = next((v for v in values if v.split(PORT_SEPARATOR)[0] == current), None)
        self.port_var.set(match or (values[0] if values else ""))

    def _station_must_be_stopped(self) -> bool:
        if self.station is not None:
            messagebox.showinfo("hr-mail", "Primero pulse Detener: la estación está usando la radio.")
            return False
        return True

    def find_radio(self) -> None:
        if not self._station_must_be_stopped():
            return
        self._read_radio_widgets()
        s = self.settings
        if s.cat_protocol == radios.PROTO_NONE:
            messagebox.showinfo("hr-mail", "Para este modelo no hay búsqueda automática.\n"
                                "Elija el puerto y la velocidad a mano y pulse Probar PTT.")
            return
        protocol, baud, civ_addr = s.cat_protocol, s.baud, radios.parse_civ(s.civ_addr)
        preset = radios.PRESETS_BY_KEY.get(s.radio_key)
        if preset and preset.civ_addr is not None:
            civ_addr = preset.civ_addr

        def work():
            self.in_ui(self.refresh_ports)
            self.log(f"Buscando {s.radio_name} en los puertos COM (no transmite)…")
            found = radios.find_radio(protocol, baud, civ_addr)
            if found is None:
                self.log("No respondió ningún puerto. " + self._hint())
                return
            s.com_port, s.baud = found.port, found.baud
            if found.civ_addr is not None:
                s.civ_addr = radios.format_civ(found.civ_addr)
            extra = f", CI-V {s.civ_addr}" if found.civ_addr is not None else ""
            self.log(f"Radio encontrada en {found.port} a {found.baud} baudios{extra}.")
            self.in_ui(self.refresh_ports)
            self.in_ui(self._show_radio_settings)
        self.run_bg(work)

    def test_ptt(self) -> None:
        if not self._station_must_be_stopped():
            return
        self._read_radio_widgets()
        s = self.settings
        if s.ptt_method in (radios.PTT_CAT, radios.PTT_SERIAL) and not s.com_port:
            messagebox.showerror("hr-mail", "Elija el puerto COM.")
            return
        if not messagebox.askokcancel("hr-mail", "La radio va a transmitir 1 segundo.\n"
                                      "Verifique que hay una antena o carga conectada."):
            return

        def work():
            self.log(f"Probando PTT ({METHOD_LABELS[s.ptt_method]})…")
            ok, output = run_ptt_test(s)
            if ok:
                self.log("Mercury activó y soltó el PTT. ¿La radio transmitió 1 segundo? "
                         "Si no, revise los ajustes indicados arriba.")
                settings_mod.save(s, self.settings_path)
            else:
                self.log("La prueba de PTT falló:")
                for line in output.splitlines()[-8:]:
                    self.log(f"  {line}")
                self.log(self._hint())
        self.run_bg(work)

    def detect_audio(self) -> None:
        def work():
            exe = paths.mercury_exe()
            if not exe.exists():
                self.log(f"No se encontró {exe}")
                return
            playback, capture = mercury.list_devices(exe)
            self.devices = (playback, capture)
            out_dev, in_dev = mercury.pick_radio_device(playback), mercury.pick_radio_device(capture)
            if out_dev and in_dev:
                self.settings.output_device, self.settings.input_device = out_dev.id, in_dev.id
                self.in_ui(lambda: self.audio_var.set(f"{in_dev.name} / {out_dev.name}"))
                self.log(f"Audio de la radio: {in_dev.name} / {out_dev.name}")
                if out_dev.is_default:
                    self.log("AVISO: el audio de la radio es la salida predeterminada de Windows. "
                             "Los sonidos del sistema saldrían al aire. Cambie la predeterminada a sus parlantes.")
            else:
                self.in_ui(lambda: self.audio_var.set("No se encontró una tarjeta USB única"))
                self.log("Dispositivos encontrados:")
                for d in playback:
                    self.log(f"  salida:  {d.name}")
                for d in capture:
                    self.log(f"  entrada: {d.name}")
        self.run_bg(work)

    def _collect_settings(self) -> Settings | None:
        call = normalize_callsign(self.call_var.get())
        if not is_valid_callsign(call):
            messagebox.showerror("hr-mail", "Escriba un indicativo válido, por ejemplo XQ2CG.")
            return None
        self._read_radio_widgets()
        s = self.settings
        s.callsign = call
        if s.ptt_method in (radios.PTT_CAT, radios.PTT_SERIAL) and not s.com_port:
            messagebox.showerror("hr-mail", "Elija el puerto COM de la radio (o pulse Buscar radio).")
            return None
        if s.ptt_method == radios.PTT_CAT and s.hamlib_model <= 0:
            messagebox.showerror("hr-mail", "Elija el modelo de la radio.")
            return None
        if not (s.input_device and s.output_device):
            messagebox.showerror("hr-mail", "No hay audio de la radio. Pulse Detectar audio.")
            return None
        settings_mod.save(s, self.settings_path)
        return s

    def start_station(self) -> None:
        s = self._collect_settings()
        if s is None:
            return

        def work():
            station = Station(s, self.log)
            station.start(self.on_pat_event)
            self.station = station
            self.set_status(f"Escuchando en radio como {s.callsign}")
        self.run_bg(work)

    def stop_station(self) -> None:
        station = self.station

        def work():
            if station is not None:
                self.log("Deteniendo…")
                station.stop()
            self.station = None
            self.set_status("Detenido")
            self.log("Detenido.")
        self.busy = False  # stop must work even during a connect
        self.run_bg(work)

    def _peer(self) -> str | None:
        peer = normalize_callsign(self.peer_var.get())
        if not is_valid_callsign(peer):
            messagebox.showerror("hr-mail", "Escriba el indicativo de la otra estación.")
            return None
        return peer

    def compose_test(self) -> None:
        peer = self._peer()
        if peer is None or self.station is None:
            return
        station = self.station

        def work():
            station.client.compose(peer, f"Prueba hr-mail de {station.settings.callsign}",
                                   "Mensaje de prueba de hr-mail.\n73")
            self.log(f"Mensaje de prueba para {peer} guardado en Por enviar.")
        self.run_bg(work)

    def connect_peer(self) -> None:
        peer = self._peer()
        if peer is None or self.station is None:
            return
        station = self.station

        def work():
            self.set_status(f"Conectando con {peer}…")
            self.log(f"Conectando con {peer}. La radio va a transmitir.")
            try:
                received = station.client.connect(peer)
                self.log(f"Sesión con {peer} terminada. Mensajes recibidos: {received}.")
            except PatError as exc:
                self.log(f"No se pudo completar la sesión con {peer}: {exc}")
            self.set_status(f"Escuchando en radio como {station.settings.callsign}")
        self.run_bg(work)

    def show_mailbox(self) -> None:
        if self.station is None:
            return
        client = self.station.client

        def work():
            for box, label in (("in", "Recibidos"), ("out", "Por enviar"), ("sent", "Enviados")):
                msgs = client.mailbox(box)
                self.log(f"--- {label}: {len(msgs)}")
                for m in msgs:
                    sender = (m.get("From") or {}).get("Addr", "?")
                    self.log(f"  {m.get('Date', '')[:16]}  {sender}  {m.get('Subject', '')}")
                    if box == "in":
                        body = client.message("in", m["MID"]).get("Body", "")
                        for line in body.strip().splitlines():
                            self.log(f"      {line}")
        self.run_bg(work)

    def on_pat_event(self, kind: str, payload) -> None:
        if kind == "LogLine":
            self.log(f"[pat] {payload}")
        elif kind == "AutoAnswered":
            self.log("[hr-mail] Aviso de cuenta Winlink respondido automáticamente (modo P2P).")
        elif kind == "Prompt":
            self.log(f"[pat] Pregunta sin respuesta automática: {payload.get('message')}")
        elif kind == "UpdateMailbox":
            self.log("[hr-mail] El buzón cambió.")

    def on_close(self) -> None:
        if self.station is not None:
            self.status_var.set("Cerrando…")
            self.root.update()
            try:
                self.station.stop()
            except Exception:  # noqa: BLE001
                pass
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
