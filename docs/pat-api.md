# Pat 1.0.0 — what hr-mail uses

Verified by reading the Pat source at tag `v1.0.0`
(commit `2e6a8d14baf0268f4e2aa4d01784a54ca935cf52`) and `wl2k-go v1.0.1`.
Not yet exercised against a running `pat.exe`; Stage 1's probe script does that.

## Starting Pat

```
pat.exe --mycall <CALL> --config <dir>\config.json --mbox <dir>\mailbox
        --forms <dir>\forms --log <dir>\pat.log --event-log <dir>\eventlog.json
        --listen varahf http --addr localhost:<port>
```

Flags from `main.go` (`optionsSet`): `--mycall`, `--listen/-l`, `--config`, `--mbox`,
`--forms`, `--log`, `--event-log`, `--send-only`, `--ignore-busy`.
`http --addr/-a` is the `http` sub-command's own flag (`cli/http.go`); it overrides
`http_addr` from the config.

Pat also keeps small state files (account check, version report) in its XDG
**StateDir** (`github.com/adrg/xdg`). hr-mail sets `XDG_CONFIG_HOME`, `XDG_DATA_HOME`
and `XDG_STATE_HOME` to folders under `%LOCALAPPDATA%\hr-mail\pat\` so nothing
touches a user's own Pat install. Stage 1 must confirm adrg/xdg honours these
variables on Windows.

## HTTP endpoints (base `http://localhost:<port>`)

| Method | Path | Use in hr-mail |
|---|---|---|
| GET | `/api/status` | `{active_listeners, connected, dialing, remote_addr, http_clients, config_hash}` |
| GET | `/api/mailbox/{in,out,sent,archive}` | List messages (newest first), no body |
| GET | `/api/mailbox/{box}/{mid}` | One message, with `Body` |
| POST | `/api/mailbox/{box}/{mid}/read` | Mark as read |
| DELETE | `/api/mailbox/{box}/{mid}` | Delete |
| POST | `/api/mailbox/out` | Compose (see below) |
| POST | `/api/connect?url=varahf:///CALL` | Connect and exchange. **Blocks until the session ends.** 200 + `{"NumReceived": n}` on success, 500 `Session failure` otherwise |
| POST | `/api/disconnect` | Abort the active connection |

Message JSON fields: `MID, Date, From{Proto,Addr}, To[], Cc[], Subject, Body,
BodyHTML, Files, P2POnly, Unread`.

### Compose: `POST /api/mailbox/out`
Form fields (multipart or urlencoded):
- `to` — **exactly one callsign** (see P2P rule below)
- `subject`, `body`
- `date` — **required**, RFC 3339 (`2026-10-17T03:05:00Z`), else 400
- `p2ponly=true` — always set by hr-mail, so a message can never leave via a Winlink gateway

Returns 201.

## WebSocket `/ws`

One JSON object per frame, keyed by type:
`Status`, `Progress{bytes_transferred, bytes_total, mid, subject, receiving, ...}`,
`Notification`, `Prompt{id, kind, message, options}`, `PromptAbort`,
`UpdateMailbox` (mailbox folder changed), `LogLine` (Pat log text), `Ping`.

Reply to a prompt by sending:
```json
{"prompt_response": {"id": "<Prompt.id>", "value": "confirmed"}}
```

hr-mail keeps one websocket open all the time: it gives live status, progress,
new-mail events and the log line for the status bar, without polling.

## Two behaviours that shape hr-mail

### 1. Winlink account check on every connect (also P2P)
`app.Connect` calls `promptUnconfirmedAccount()` before dialing. If the callsign has
no Winlink account (or the check cannot confirm one), Pat raises a
`pre-account-activation` prompt and **waits up to 2 minutes**; with no answer the
connect fails. A positive answer is cached for 100 days in StateDir.

hr-mail is P2P-only, so it answers that prompt kind automatically with
`"confirmed"` over the websocket. It must not answer `account-activation` or
`password` prompts automatically; those are logged and shown as an error.

### 2. P2P only sends messages whose *only* recipient is the peer
`wl2k-go mailbox.DirHandler.GetOutbound`: in a P2P session the remote announces its
callsign as forwarder, and only outbox messages for which that callsign is the
**only** receiver are sent. A message to two callsigns is never sent P2P.

Therefore hr-mail composes **one message per destination callsign**.
