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
Supported radios: ICOM IC-7100 (USB cable, CI-V PTT) and any radio/interface with VOX.

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
