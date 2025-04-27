import asyncio
from quart import Quart, request
from buttplug.client import (
    Client as ButtplugClient,
    Device as ButtplugClientDevice
)
from buttplug.connectors import WebsocketConnector

app = Quart(__name__)

device: ButtplugClientDevice = None
client: ButtplugClient = None

async def setup_buttplug():
    global client, device
    client = ButtplugClient("QuartButtplugClient")
    connector = WebsocketConnector("ws://127.0.0.1:12345")
    await client.connect(connector)

    await client.start_scanning()
    await asyncio.sleep(2)
    await client.stop_scanning()

    if not client.devices:
        raise Exception("No devices found!")

    device = client.devices[0]
    print(f"Connected to device: {device.name}")

@app.before_serving
async def initialize():
    await setup_buttplug()
    app.buttplug_initialized = True

@app.route("/vibrate")
async def vibrate():
    print("Vibrate endpoint called")
    if not device or not device.actuators:
        print("Device or actuator not ready")
        return "Device or actuator not ready", 500

    try:
        speed = float(request.args.get('speed', 0.5))
        speed = max(0.0, min(speed, 1.0))
        duration = float(request.args.get('duration', 0))  # duration in seconds (default: 0 = no limit)
        print(f"Sending vibrate command at speed {speed} for {duration} seconds")

        actuator = device.actuators[0]
        await actuator.command(speed)
        print("Vibrate command sent")

        # If a duration is specified, schedule a stop
        if duration > 0:
            async def stop_after_delay():
                await asyncio.sleep(duration)
                await actuator.command(0)
                print("Vibration stopped after time limit")

            asyncio.create_task(stop_after_delay())

        return f"Vibrating at {speed*100:.0f}% power" + (f" for {duration} seconds" if duration > 0 else "")
    except Exception as e:
        print(f"Exception: {e}")
        return str(e), 500

@app.route("/stop")
async def stop():
    if not device:
        return "Device not ready", 500

    try:
        await device.stop()
        return "Device stopped"
    except Exception as e:
        return str(e), 500

@app.route("/linear")
async def linear():
    if not device:
        return "Device not ready", 500

    try:
        position = float(request.args.get('position', 0.5))
        duration = int(request.args.get('duration', 1000))
        position = max(0.0, min(position, 1.0))
        await device.send_linear_cmd([(0, position, duration)])
        return f"Moving to position {position*100:.0f}% over {duration}ms"
    except Exception as e:
        return str(e), 500

if __name__ == "__main__":
    app.run(host="localhost", port=3069)