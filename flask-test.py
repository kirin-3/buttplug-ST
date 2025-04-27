import asyncio
from flask import Flask, request
from buttplug.client import (
    Client as ButtplugClient,
    Device as ButtplugClientDevice
)
from buttplug.connectors import WebsocketConnector

app = Flask(__name__)

device: ButtplugClientDevice = None
client: ButtplugClient = None

async def setup_buttplug():
    global client, device
    client = ButtplugClient("FlaskButtplugClient")
    connector = WebsocketConnector("ws://127.0.0.1:12345")
    await client.connect(connector)

    await client.start_scanning()
    await asyncio.sleep(2)
    await client.stop_scanning()

    if not client.devices:
        raise Exception("No devices found!")

    device = client.devices[0]
    print(f"Connected to device: {device.name}")

@app.before_request
def initialize():
    if not hasattr(app, 'buttplug_initialized'):
        asyncio.run(setup_buttplug())
        app.buttplug_initialized = True

@app.route("/vibrate")
def vibrate():
    print("Vibrate endpoint called")
    if not device:
        print("Device not ready")
        return "Device not ready", 500

    try:
        speed = float(request.args.get('speed', 0.5))
        speed = max(0.0, min(speed, 1.0))
        print(f"Sending vibrate command at speed {speed}")
        asyncio.run(device.send_vibrate_cmd(speed))
        print("Vibrate command sent")
        return f"Vibrating at {speed*100:.0f}% power"
    except Exception as e:
        print(f"Exception: {e}")
        return str(e), 500

@app.route("/stop")
def stop():
    if not device:
        return "Device not ready", 500

    try:
        asyncio.run(device.stop())
        return "Device stopped"
    except Exception as e:
        return str(e), 500

@app.route("/linear")
def linear():
    if not device:
        return "Device not ready", 500

    try:
        position = float(request.args.get('position', 0.5))
        duration = int(request.args.get('duration', 1000))
        position = max(0.0, min(position, 1.0))
        asyncio.run(device.send_linear_cmd([(0, position, duration)]))
        return f"Moving to position {position*100:.0f}% over {duration}ms"
    except Exception as e:
        return str(e), 500

if __name__ == "__main__":
    app.run(host="localhost", port=3069)