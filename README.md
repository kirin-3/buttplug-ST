# ButtplugST

A bridge between SillyTavern and buttplug.io compatible devices.

This bridge allows you to control devices via [Intiface Central](https://github.com/intiface/intiface-central) and trigger them from [SillyTavern](https://github.com/SillyTavern/SillyTavern) using [Sorcery](https://github.com/p-e-w/sorcery).

## Features

- Connect to devices via Intiface Central's websocket
- Multiple device support with device selection
- Vibration control with speed, position (for dual-motor devices), and duration
- REST API with proper error handling
- Configuration via TOML files or environment variables
- Detailed status endpoint for diagnostics
- Robust error handling and reconnection

## Tested With

✅ Lovense Edge

✅ Lovense Hush 2

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/buttplug-st.git
cd buttplug-st
```

2. Install the dependencies:
```bash
pip install -r requirements.txt
```

3. Start Your Intiface Server

4. Run the server:
```bash
python run.py
```

Or use the included run script with options:
```bash
python run.py --debug
```

## Configuration

The server can be configured in several ways:

1. Edit the default configuration file at `buttplug_st/config/default.toml`
2. Create a custom configuration file and load it with the `--config` option
3. Set environment variables (prefixed with `BUTTPLUG_`)

Example configuration:
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

## Usage with SillyTavern Sorcery

Add Sorcery commands to your SillyTavern configuration(Run this JavaScript) like these examples:

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

## API Reference

### GET /status
Get detailed server and device connection status. This endpoint provides extensive information about:
- Server health
- Intiface connection status
- Connected devices
- Current device configuration

### GET /devices
List all connected devices.

### POST /device
Select the active device by index.

```json
{
  "index": 0
}
```

### GET /vibrate
Control vibration of the active device.

Parameters:
- `speed`: Vibration intensity (0.0-1.0), default: 0.5
- `position`: Position for dual-motor devices (0.0-1.0), default: none
- `duration`: Duration in seconds (0 = no limit), default: 0

### GET /stop
Stop all actuators on the active device.

### GET /scan
Scan for new devices.

## Development

For development, enable debug mode in the configuration:

```toml
[server]
debug = true
```

To test the API directly, open the included `test_vibrate.html` file in your browser.

## Troubleshooting

If your commands don't work:

1. Make sure Intiface Central is running and the WebSocket server is enabled at `ws://127.0.0.1:12345`
2. Check that devices are connected in Intiface Central
3. Verify the server is running by accessing http://localhost:3069/status
4. For SillyTavern/Sorcery issues, check your browser console for errors
5. Restart the server if it loses connection to Intiface Central
6. Check the terminal output of the server for detailed error messages

## License

MIT