# ButtplugST

A REST bridge between [SillyTavern](https://github.com/SillyTavern/SillyTavern) and buttplug.io compatible devices, via [Intiface Central](https://github.com/intiface/intiface-central).

ButtplugST runs a small HTTP server on `localhost:3069` and translates requests into buttplug.io device commands — trigger your devices from [Sorcery](https://github.com/p-e-w/sorcery) commands, STscripts, `curl`, or anything that can call an HTTP endpoint.

## Features

- Connects to devices through Intiface Central's websocket
- Multiple device support with device selection
- Vibration control with speed, position (for supporting devices), and timed auto-stop
- Legacy GET endpoints and JSON POST endpoints with identical behavior
- Structured errors: `400` bad input, `404` no device, `503` Intiface down — never a raw 500 on bad input
- The server starts and keeps serving even when Intiface Central is closed, and reconnects when it comes back
- Configuration via TOML file, environment variables, or CLI flags (with deterministic precedence)

## Requirements

- **Python 3.13 or newer**
- **A current Intiface Central release** — ButtplugST uses the official `buttplug` 1.0.0 client (Buttplug protocol v4). If your Intiface Central predates early 2026, update it before connecting.
- Intiface Central's WebSocket server enabled (default `ws://127.0.0.1:12345`)

## Tested With

✅ Lovense Edge 2

✅ Lovense Hush 2

✅ Lovense Lush 2

*In theory it should work with any buttplug.io supported device.*

### A more user friendly installation guide can be found [here on my blog](https://kirin.pw/posts/sillytavern-buttplug/).

## Installation

1. Clone the repository:
```bash
git clone https://github.com/kirin-3/buttplug-st.git
cd buttplug-st
```

2. Install the package (from a Python 3.13+ environment):
```bash
pip install -e .
```

3. Start Intiface Central and make sure its WebSocket server is on.

4. Run the server:
```bash
buttplug-st
```

The `buttplug-st` command is installed by the package; `python run.py` from the repository does the same thing. Useful flags:

```bash
buttplug-st --config myconfig.toml   # load a TOML config file
buttplug-st --port 4000              # override the HTTP port
buttplug-st --host 127.0.0.1 --debug
```

## Configuration

Settings resolve with precedence (highest first):

1. CLI flags (`--host`, `--port`, `--debug`)
2. `BUTTPLUG_*` environment variables
3. The TOML file passed with `--config` (or the packaged defaults if omitted)

A `--config` file that is missing or invalid **aborts startup with an error naming the file** — the server never silently falls back to defaults.

The packaged defaults (`buttplug_st/config/default.toml`) are:

```toml
[server]
host = "localhost"
port = 3069
debug = false

[websocket]
url = "ws://127.0.0.1:12345"
scan_timeout = 2

[device]
default_speed = 0.5
default_position = 0.5
default_duration = 0
```

Every value can be overridden by an environment variable named `BUTTPLUG_<SECTION>_<KEY>`:

| Variable | Type | Values |
| --- | --- | --- |
| `BUTTPLUG_SERVER_HOST` | string | e.g. `127.0.0.1` |
| `BUTTPLUG_SERVER_PORT` | integer | e.g. `3123` |
| `BUTTPLUG_SERVER_DEBUG` | boolean | `true`/`1`/`yes` or `false`/`0`/`no` (case-insensitive) |
| `BUTTPLUG_WEBSOCKET_URL` | string | e.g. `ws://127.0.0.1:12345` |
| `BUTTPLUG_WEBSOCKET_SCAN_TIMEOUT` | number | seconds, e.g. `5` |
| `BUTTPLUG_DEVICE_DEFAULT_SPEED` | number | `0.0`–`1.0` |
| `BUTTPLUG_DEVICE_DEFAULT_POSITION` | number | `0.0`–`1.0` |
| `BUTTPLUG_DEVICE_DEFAULT_DURATION` | number | seconds |

Invalid values are rejected at startup with the variable named, e.g. `BUTTPLUG_SERVER_DEBUG: invalid value 'banana' for type bool`.

## Usage with SillyTavern Sorcery

Install Sorcery from [p-e-w/sorcery](https://github.com/p-e-w/sorcery) into SillyTavern.

Open the Sorcery tab from top menu.

Add Sorcery commands (Run this JavaScript) like these examples:

### Basic vibration
```js
fetch("http://localhost:3069/vibrate?speed=0.7&duration=5");
```

### Dual-motor vibration (for compatible devices)
```js
fetch("http://localhost:3069/vibrate?speed=0.7&position=0.5&duration=5");
```

### Stop all vibrations
```js
fetch("http://localhost:3069/stop");
```

These GET calls work exactly as they did in earlier ButtplugST releases. The same operations are available as JSON POSTs (see below).

## API Reference

Every successful response is JSON of the form:

```json
{"success": true, "message": "…", "data": {…}}
```

Every error response is:

```json
{"error": "machine_readable_code", "detail": "human-readable", "status_code": 400}
```

Status codes: `400` invalid input (the detail names the parameter), `404` no/unknown device, `503` Intiface Central unreachable or disconnected, `500` unexpected internal error.

### GET /status
Server and device connection status: Intiface connection state, tracked device count, configured websocket URL, and the active device (or `null`). Always returns `200`, even while Intiface is down.

### GET /devices
List tracked devices and the active index (`-1` when nothing is selected). This is a pure read: it never triggers a scan and never resets your selection. Devices also appear and disappear on their own while Intiface is connected — no scan required.

### GET /scan
Explicitly scan for new devices (bounded by `scan_timeout`). Your active selection is preserved if the device is still present.

### POST /device
Select the active device by index.
```json
{"index": 0}
```

### GET /vibrate or POST /vibrate
Control vibration of the active device.

| Parameter | Where | Range | Default |
| --- | --- | --- | --- |
| `speed` | query / JSON | 0.0–1.0 (clamped) | 0.5 |
| `position` | query / JSON | 0.0–1.0 | none |
| `duration` | query / JSON | seconds, 0 = until stopped | 0 |

```json
{"speed": 0.7, "position": 0.5, "duration": 5}
```

`position` is applied only on devices that support position output; on others the device still vibrates and the response reports `"position_applied": false`. A `speed` of `0` silences the device. When `duration` is set, the device is auto-stopped after the delay; a new command or `stop` cancels the pending timer (only one timer ever exists).

### GET /stop or POST /stop
Stop all outputs of the active device.

## Security note

ButtplugST binds to localhost and is meant for your machine only. The CORS policy is fully open, and the legacy GET endpoints (`/vibrate`, `/stop`) change device state — which means any webpage you visit could in principle call them from JavaScript (a CSRF-style attack). If that ever matters to you, keep the server bound to `127.0.0.1`, run it only while in use, or put it behind a authenticating reverse proxy. Token auth is a planned future feature.

## Development

Install with dev extras, then run the tests and linter:

```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
```

To test the API manually, open `tools/test_vibrate.html` in a browser, or:

```bash
curl "http://localhost:3069/vibrate?speed=0.7&duration=5"
curl -X POST http://localhost:3069/vibrate -H "Content-Type: application/json" -d "{\"speed\": 0.7, \"duration\": 5}"
curl http://localhost:3069/status
```

CI runs the same `ruff check .` + `pytest` on Windows and Python 3.13 for every push/PR to master.

## Troubleshooting

1. Make sure Intiface Central is running and the WebSocket server is enabled at `ws://127.0.0.1:12345`
2. Check that devices are connected in Intiface Central
3. Verify the server is running by accessing http://localhost:3069/status — it reports `intiface_connected: false` when Intiface is down
4. Commands made while Intiface is down return HTTP 503; the server reconnects automatically (throttled to at most one attempt every 5 seconds) once Intiface is back
5. If your Intiface Central is old, update it — ButtplugST speaks Buttplug protocol v4
6. For SillyTavern/Sorcery issues, check your browser console for errors

## License

MIT
