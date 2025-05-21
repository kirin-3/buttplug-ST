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
        position = float(request.args.get('position', 0.0))
        position = max(0.0, min(position, 1.0))
        duration = float(request.args.get('duration', 0))  # seconds

        print(f"Sending vibrate command at speed {speed}, position {position} for {duration} seconds")

        actuator = device.actuators[0]
        # Try sending both speed and position if supported
        try:
            await actuator.command(speed, position)
        except TypeError:
            # Fallback: send only speed if position is not supported
            await actuator.command(speed)
        print("Vibrate command sent")

        if duration > 0:
            async def stop_after_delay():
                await asyncio.sleep(duration)
                await actuator.command(0)
                print("Vibration stopped after time limit")
            asyncio.create_task(stop_after_delay())

        return (
            f"Vibrating at {speed*100:.0f}% power"
            + f", position {position*100:.0f}%"
            + (f" for {duration} seconds" if duration > 0 else "")
        )
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

if __name__ == "__main__":
    app.run(host="localhost", port=3069)