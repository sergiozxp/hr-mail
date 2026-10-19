# hr-mail — Specification

**hr-mail** (ham radio email) is a very simple Windows app for sending and receiving
short text messages station-to-station over HF, with no Internet and no central server.

It does **not** implement a modem or a mail protocol. It wraps two existing free/open
programs and hides them completely:

- **Mercury** (Rhizomatica, GPL) — HF data modem with a VARA-compatible TCP interface.
- **Pat** (MIT) — Winlink client, used only in **P2P mode** over its `varahf` transport.

Target users are hams who do not know what a console is. They must be able to install
and use hr-mail **with the mouse only**. The most they will type is their callsign,
a destination callsign and the message text.

License: **GPL-3.0-or-later** (same family as Mercury).

Language rules: **UI in Spanish**. Code, comments, README and commit messages in English.

---

## 1. Verified baseline (manual test, 2026-10-16)

Chain tested on Windows 11 with an ICOM IC-7100:

```
Pat 1.0.0 (pat http)  --TCP localhost:8300/8301-->  Mercury 1.9.19  --Hamlib CAT (COM, 19200, CI-V 0x88)-->  IC-7100
                                                        |
                                                        +-- audio: "USB Audio CODEC" in/out (WASAPI/dsound ids from `mercury.exe -z`)
```

- Mercury `[ptt] method=hamlib`, `hamlib_model=3070`, `hamlib_conf=civaddr=0x88` keys the IC-7100 correctly.
- Pat `varahf.addr=localhost:8300`, `ptt_ctrl=false`, `listen=["varahf"]` works with Mercury.
- `pat connect varahf:///CALL` transmits, retries ~2 min, ends with `connect timeout` when nobody answers.
- Not yet verified: a full session with a second station (station B).

## 2. User experience

### 2.1 Install
Download one ZIP from GitHub Releases, unzip, double-click `hr-mail.exe`.
No installer, no admin rights, no PowerShell. Everything lives in the unzipped folder
plus a per-user data folder (`%LOCALAPPDATA%\hr-mail`).

### 2.2 First-run wizard (once)
1. **Indicativo** — text field (uppercased automatically, validated as a callsign).
2. **Radio** — mouse only (v0.2.0, see §5):
   - a preset (IC-7100, IC-7300, FT-710, TS-590SG, KX3, G90, …),
   - `Otro modelo (lista completa de hamlib)…` — searchable list from `mercury -K`,
   - `Otra radio sin CAT (VOX, Digirig, CM108)`.
   Then the PTT connection: CAT (Hamlib), RTS/DTR line, CM108 GPIO or VOX.
3. **Detección automática** (no user input):
   - Audio: run `mercury.exe -z`, pick the capture and playback devices whose name contains
     `USB Audio CODEC` (fallback: any name containing `USB`). If zero or several match,
     show a dropdown with the names only (never ids).
   - IC-7100 only: probe every COM port with the CI-V "read frequency" command
     (`FE FE 88 E0 03 FD` at 19200 baud) using pyserial; the port that answers is the radio.
     If none answers, show a Spanish message explaining the IC-7100 menu settings
     (CI-V USB Baud Rate = 19200, CI-V USB Echo Back as needed) and a "Reintentar" button.
4. **Probar transmisión** — button. The radio transmits ~3 s, then the app asks
   "¿La radio transmitió? Sí / No".
   - IC-7100: key/unkey via CI-V (`FE FE 88 E0 1C 00 01 FD` / `... 1C 00 00 FD`) while
     playing a 1500 Hz tone on the USB playback device.
   - VOX: play the 1500 Hz tone only; VOX must key the radio.
   - Release the COM port before Mercury starts.
5. Save and go to the main window.

The wizard can be reopened from a "Configuración" button.

### 2.3 Main window
- Status line: `Escuchando en radio` / `Conectando con XQ2ABC…` / `Enviando…` / error text.
- **Recibidos** — list (De, Fecha, Asunto/primer renglón); double-click opens the text.
- **Escribir** — fields **Para** (one callsign) and **Mensaje** (multiline). Subject is generated
  from the first line. Button **Guardar para enviar**.
- **Por enviar** — list of queued messages.
- **Enviar / Recibir** — asks for (or preselects) a callsign, connects to that station,
  exchanges all queued messages for it, receives anything it has for us, disconnects.
- While idle, the station is always listening: incoming P2P sessions are accepted by Pat
  and new messages appear in Recibidos.

Frequency is set by the user on the radio (agreed beforehand). hr-mail does not change
frequency in v1.

## 3. Architecture

- **Python 3.12 + Tkinter** (standard library GUI, nothing exotic to bundle).
- Extra dependencies: `pyserial`, `sounddevice` + `numpy` (test tone), `requests` (Pat API).
- Packaged with **PyInstaller** (one folder) by **GitHub Actions** on `windows-latest`.
- Release ZIP layout:
  ```
  hr-mail/
    hr-mail.exe
    bin/mercury/   (mercury.exe + its DLLs, unmodified upstream release; mercury-ui.exe left out)
    bin/pat/       (pat.exe, unmodified upstream release; Pat only ships a 32-bit Windows build)
    licenses/      (hr-mail GPL-3.0, Mercury GPL-3.0, Pat MIT, THIRD-PARTY.md with upstream source links)
  ```
- **Process supervision**: hr-mail starts `mercury.exe` and `pat.exe http` as hidden child
  processes (`CREATE_NO_WINDOW`), captures their logs to `%LOCALAPPDATA%\hr-mail\logs\`,
  and kills them on exit. Only one hr-mail instance at a time (lock file / named mutex).
- **Generated config** (written on every start from hr-mail settings, never edited by users):
  - `mercury.ini` — from the verified baseline in §1; `ui_enabled=false`;
    IC-7100: `method=hamlib`, `device=<COM>`, `hamlib_model=3070`,
    `hamlib_serial_speed=19200`, `hamlib_conf=civaddr=0x88`; VOX: `method=none`.
  - Pat `config.json` in a private Pat config dir (via Pat's `--config` flag / env so it never
    touches a user's own Pat install): `mycall`, `varahf.addr=localhost:8300`,
    `ptt_ctrl=false`, `listen=["varahf"]`, `http_addr=localhost:<free port>`,
    `version_reporting_disabled=true`. Pat mailbox dir also private to hr-mail.
- **Talking to Pat**: its local HTTP API plus one permanent websocket (`/ws`) for live
  status, progress, new-mail events and prompts. Endpoints verified against the
  Pat v1.0.0 source: see `docs/pat-api.md`.
- **Account prompt**: Pat raises a `pre-account-activation` prompt on every connect
  (P2P included) when the callsign has no Winlink account, and the connect fails after
  2 min without an answer. hr-mail answers that prompt kind with `confirmed` over the
  websocket. Other prompt kinds are never auto-answered.
- **One recipient per message**: Pat only sends a message P2P when the peer is its
  *only* recipient, so "Para" takes exactly one callsign. Every message is posted with
  `p2ponly=true`.

## 4. Stages

Each stage ends with a working, testable build. Keep everything as simple as possible
but correct.

1. **Stage 1 — Skeleton + Pat API probe.** Repo layout, PyInstaller build in GitHub Actions
   producing the ZIP with Mercury and Pat bundled. A tiny script that starts Mercury and Pat
   with generated configs and exercises the verified Pat API calls (list, compose, connect).
   Document the endpoints in `docs/pat-api.md`.
2. **Stage 2 — Process manager + generated configs.** Start/stop/restart children, logs,
   single instance, clean shutdown (radio never left keyed).
3. **Stage 3 — Setup wizard.** Callsign, radio choice, audio auto-detect, IC-7100 COM probe,
   transmit test (IC-7100 and VOX).
4. **Stage 4 — Main window.** Recibidos / Escribir / Por enviar / Enviar-Recibir, status line,
   polling Pat for new mail.
5. **Stage 5 — Field test with station B** and fixes. Spanish one-page user guide with
   screenshots (`docs/guia-usuario.pdf`).

## 5. Radio support (v0.2.0)

Mercury does all radio control; hr-mail only writes its `[ptt]` section.
Mercury 1.9.19 bundles Hamlib 4.6.5 and offers `-K` (list Hamlib models) and
`-Q` (key the configured PTT for one second, release, exit).

- **Settings**: `radio_key` (preset key, `hamlib` for a model from the full list, `vox`),
  `radio_name`, `hamlib_model`, `cat_protocol` (`icom`, `yaesu`, `kenwood` or empty),
  `ptt_method` (`hamlib`, `serial`, `cm108`, `none`), `com_port`, `baud`, `civ_addr`,
  `serial_line`, `serial_invert`, `cm108_gpio`. Settings from 0.1.0 (`radio`) are migrated.
- **`[ptt]` generated**:
  - CAT: `method=hamlib`, `device=<COM>`, `hamlib_model`, `hamlib_serial_speed=<baud>`,
    and `hamlib_conf=civaddr=<addr>` for Icom-style radios (IC-7100 output is unchanged
    from the verified baseline).
  - RTS/DTR: `method=serial`, `device`, `line` (rts/dtr/both), `invert` (none/rts/dtr/both).
  - CM108: `method=cm108`, `cm108_gpio` (Mercury finds the HID device).
  - VOX: `method=none`.
- **Presets** (`hrmail/radios.py`): Hamlib model number, first CAT speed to try,
  command family, factory CI-V address, and a one-line Spanish hint about radio menus.
  Model numbers checked against Hamlib 4.6.5 `riglist.h`.
- **Buscar radio** never transmits. It tries every COM port at the preset speed first,
  then 38400, 19200, 115200, 9600, 4800, 57600, with RTS/DTR held low:
  Icom/Xiegu CI-V "read frequency" to the preset address and to broadcast 0x00
  (the reply gives the radio's real address); Yaesu and Kenwood/Elecraft `FA;`.
  Models from the full list get a search only if they are Icom/Xiegu.
- **Probar PTT** (station stopped): writes `mercury-ptt-test.ini` and runs `mercury -Q`.
- **Release on stop**: after Mercury is stopped, CAT radios get an explicit unkey
  (CI-V `1C 00 00`, Yaesu `TX0;`, Kenwood/Elecraft `RX;` — never Kenwood `TX0;`, which keys).
  Serial and CM108 lines drop when Mercury exits.

Later (not v1): frequency control,
broadcast/net messages, store-and-forward relaying between stations.
