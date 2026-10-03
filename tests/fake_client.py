"""Scriptable stand-in for the buttplug 1.0.0 client, mirroring the adapter surface.

The fake reproduces the client behaviors DeviceManager relies on:
- event callbacks assigned before connect(); already-known devices fire
  on_device_added during connect();
- an unexpected server disconnect fires ONLY on_server_disconnect (no
  per-device removal callbacks);
- start_scanning()/stop_scanning() and client-side scanning state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from buttplug import ButtplugConnectorError, DeviceOutputCommand, OutputType


class FakeFeature:
    """Mimics DeviceFeature: outputs dict keyed by output-type name."""

    def __init__(self, outputs: tuple[str, ...], steps: tuple[int, int] = (0, 20)) -> None:
        self.outputs: dict[str, tuple[int, int]] = {name: steps for name in outputs}

    def has_output(self, output_type: OutputType | str) -> bool:
        name = output_type.value if isinstance(output_type, OutputType) else output_type
        return name in self.outputs


class FakeDevice:
    """Mimics ButtplugDevice for the surface DeviceManager uses; records commands."""

    def __init__(
        self,
        index: int,
        name: str = "Fake Vibrator",
        outputs: tuple[str, ...] = ("Vibrate",),
        feature_count: int = 1,
    ) -> None:
        self.index: int = index
        self.name: str = name
        self.display_name: str | None = None
        self.features: dict[int, FakeFeature] = {
            i: FakeFeature(outputs) for i in range(feature_count)
        }
        self.outputs_sent: list[DeviceOutputCommand] = []
        self.stop_calls: int = 0

    def has_output(self, output_type: OutputType | str) -> bool:
        return any(f.has_output(output_type) for f in self.features.values())

    async def run_output(self, command: DeviceOutputCommand) -> None:
        if not self.has_output(command.output_type):
            raise RuntimeError(f"no {command.output_type} features")
        self.outputs_sent.append(command)

    async def stop(self) -> None:
        self.stop_calls += 1


class FakeButtplugClient:
    """Mimics ButtplugClient with scripted connect failures and manual events."""

    def __init__(self, connect_error: Exception | None = None) -> None:
        self.name: str = "ButtplugST"
        self.connected: bool = False
        self.scanning: bool = False
        self.devices: dict[int, FakeDevice] = {}
        self.connect_error: Exception | None = connect_error
        self.connect_calls: int = 0
        self.disconnect_calls: int = 0

        self.on_device_added: Callable[[FakeDevice], Awaitable[None]] | None = None
        self.on_device_removed: Callable[[FakeDevice], Awaitable[None]] | None = None
        self.on_scanning_finished: Callable[[], Awaitable[None]] | None = None
        self.on_server_disconnect: Callable[[], Awaitable[None]] | None = None
        self.on_error: Callable[[Exception], Awaitable[None]] | None = None

    # ---- client API ----

    async def connect(self, _url: str) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        for device in list(self.devices.values()):
            if self.on_device_added is not None:
                await self.on_device_added(device)

    async def disconnect(self) -> None:
        self.disconnect_calls += 1
        self.connected = False
        self.scanning = False
        self.devices.clear()

    async def start_scanning(self) -> None:
        if not self.connected:
            raise ButtplugConnectorError("Not connected")
        self.scanning = True

    async def stop_scanning(self) -> None:
        self.scanning = False

    # ---- test controls ----

    async def add_device(self, device: FakeDevice) -> None:
        """Simulate the server discovering a device (during or after connect)."""
        self.devices[device.index] = device
        if self.on_device_added is not None:
            await self.on_device_added(device)

    async def remove_device(self, index: int) -> None:
        """Simulate the server dropping a device (fires on_device_removed)."""
        device = self.devices.pop(index, None)
        if device is not None and self.on_device_removed is not None:
            await self.on_device_removed(device)

    async def server_disconnect(self) -> None:
        """Simulate an unexpected server drop (on_server_disconnect only)."""
        self.connected = False
        self.scanning = False
        self.devices.clear()
        if self.on_server_disconnect is not None:
            await self.on_server_disconnect()

    async def finish_scanning(self) -> None:
        """Simulate the server's ScanningFinished message."""
        self.scanning = False
        if self.on_scanning_finished is not None:
            await self.on_scanning_finished()
