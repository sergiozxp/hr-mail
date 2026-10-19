# hr-mail

**hr-mail** (ham radio email) is a very simple Windows app for sending and receiving
short text messages directly between amateur radio stations over HF — no Internet,
no servers. It is meant for hams who just want to click, type a message and send it.

It wraps two free/open programs and hides them completely:

- [Mercury](https://github.com/Rhizomatica/mercury) — open-source HF data modem (VARA-compatible TCP interface)
- [Pat](https://github.com/la5nta/pat) — Winlink client, used only in peer-to-peer (P2P) mode

The user interface is in Spanish. See [SPEC.md](SPEC.md) for the design and the stage plan,
and [docs/pat-api.md](docs/pat-api.md) for the parts of Pat that hr-mail relies on.

## Status

**Stage 1** — diagnostic window: starts Mercury and Pat with generated configs,
queues a test message, connects to another station, shows the mailbox.

**Radios (v0.2.0)** — any radio Hamlib supports, chosen with the mouse:

- Presets with factory settings and menu hints: ICOM IC-7100, IC-7300, IC-705, IC-7610,
  IC-9700, IC-7600, IC-7410, IC-7200; Yaesu FT-710, FT-991/991A, FT-891, FTDX10,
  FTDX101D/MP, FTDX3000; Kenwood TS-590S/SG, TS-890S, TS-480; Elecraft K3/K3S, KX3,
  KX2, K4; Xiegu G90, X6100.
- "Otro modelo": the full Hamlib list from the bundled Mercury (`mercury -K`), searchable.
- PTT by CAT (Hamlib), by RTS/DTR on a COM port (Digirig, AIOC, home-brew cables),
  by CM108 GPIO, or VOX.
- "Buscar radio" finds the COM port and CAT speed (Icom CI-V, Yaesu and Kenwood/Elecraft
  ASCII CAT) without transmitting. "Probar PTT" keys the radio for one second through
  Mercury (`mercury -Q`) with the same settings the station will use.

Only the IC-7100 has been verified on the air so far; the other presets use Hamlib's
model numbers and the radios' factory CAT settings.

## Download

Get the ZIP from the [Actions](../../actions) build (artifact `hr-mail-windows`) or,
for tagged versions, from [Releases](../../releases). Unzip and run `hr-mail.exe`.

## Development

```
pip install -r requirements.txt pytest pyinstaller
python tools/fetch_bins.py        # downloads pinned Mercury and Pat into bin/
python -m pytest -q
python hr_mail.py                  # run from source (Windows)
```

Per-user data (settings, generated configs, Pat mailbox, logs) lives in
`%LOCALAPPDATA%\hr-mail`.

## License

Copyright (C) 2026 Sergio, XQ2CG.

hr-mail is free software: you can redistribute it and/or modify it under the terms of the
GNU General Public License as published by the Free Software Foundation, either version 3
of the License, or (at your option) any later version. See [LICENSE](LICENSE).

Bundled third-party programs and their licenses: [licenses/THIRD-PARTY.md](licenses/THIRD-PARTY.md).
