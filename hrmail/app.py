"""Stage 1 window: start Mercury + Pat, queue a test message, connect, list mail.

This is a diagnostic tool for the developer. The setup wizard (Stage 3) and the
real main window (Stage 4) replace it.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from . import __version__, civ, mercury, paths
from . import settings as settings_mod
from .pat import PatError
from .settings import RADIO_IC7100, RADIO_VOX, Settings, is_valid_callsign, normalize_callsign
from .station import Station


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings_path = paths.data_dir() / "settings.json"
        self.settings = settings_mod.load(self.settings_path)
        self.station: Station | None = None
        self.busy = False
        self.ui_queue: queue.Queue = queue.Queue()
        self.devices: tuple[list, list] = ([], [])

        root.title(f"hr-mail {__version__} — Etapa 1 (diagnóstico)")
        root.minsize(720, 520)
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

        ttk.Label(cfg, text="Su indicativo:").grid(row=0, column=0, sticky="w", **pad)
        self.call_var = tk.StringVar(value=self.settings.callsign)
        ttk.Entry(cfg, textvariable=self.call_var, width=12).grid(row=0, column=1, sticky="w", **pad)

        ttk.Label(cfg, text="Radio:").grid(row=1, column=0, sticky="w", **pad)
        self.radio_var = tk.StringVar(value=self.settings.radio)
        ttk.Radiobutton(cfg, text="ICOM IC-7100 (cable USB)", value=RADIO_IC7100,
                        variable=self.radio_var).grid(row=1, column=1, sticky="w", **pad)
        ttk.Radiobutton(cfg, text="Otra radio / interfaz con VOX", value=RADIO_VOX,
                        variable=self.radio_var).grid(row=1, column=2, sticky="w", **pad)

        ttk.Label(cfg, text="Puerto CI-V:").grid(row=2, column=0, sticky="w", **pad)
        self.port_var = tk.StringVar(value=self.settings.com_port)
        self.port_box = ttk.Combobox(cfg, textvariable=self.port_var, width=10, state="readonly")
        self.port_box.grid(row=2, column=1, sticky="w", **pad)
        ttk.Button(cfg, text="Buscar IC-7100", command=self.find_radio).grid(row=2, column=2, sticky="w", **pad)

        ttk.Label(cfg, text="Audio:").grid(row=3, column=0, sticky="w", **pad)
        self.audio_var = tk.StringVar(value="(sin detectar)")
        ttk.Label(cfg, textvariable=self.audio_var).grid(row=3, column=1, columnspan=2, sticky="w", **pad)
        ttk.Button(cfg, text="Detectar audio", command=self.detect_audio).grid(row=3, column=3, sticky="w", **pad)

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
    def refresh_ports(self) -> None:
        ports = civ.list_com_ports()
        self.port_box["values"] = ports
        if self.port_var.get() not in ports:
            self.port_var.set(ports[0] if ports else "")

    def find_radio(self) -> None:
        def work():
            self.log("Buscando el IC-7100 en los puertos COM…")
            for port in civ.list_com_ports():
                if civ.probe(port):
                    self.log(f"IC-7100 encontrado en {port}.")
                    self.in_ui(lambda p=port: self.port_var.set(p))
                    return
            self.log("No respondió ningún puerto. En el IC-7100 revise: Set > Connectors > "
                     "CI-V USB Baud Rate = 19200.")
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
        s = self.settings
        s.callsign, s.radio, s.com_port = call, self.radio_var.get(), self.port_var.get()
        if s.radio == RADIO_IC7100 and not s.com_port:
            messagebox.showerror("hr-mail", "Elija el puerto del IC-7100 (o pulse Buscar IC-7100).")
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
