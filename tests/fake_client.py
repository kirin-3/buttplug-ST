"""Scriptable stand-in for the buttplug 1.0.0 client, mirroring the adapter surface.

The fake reproduces the client behaviors DeviceManager relies on:
- event callbacks assigned before connect(); already-known devices fire
  on_device_added during connect();
- an unexpected server disconnect fires ONLY on_server_disconnect (no
  per-device removal callbacks);
- start_scanning()/stop_scanning() and client-side scanning state.
"""

from __future__ import annotations

import inspect
from typing import Any

from buttplug import ButtplugConnectorError, OutputType


class FakeFeature:
    """Mimics DeviceFeature: outputs dict keyed by output-type name."""

    def __init__(self, outputs: tuple[str, ...], steps: tuple[int, int] = (0, 20)):
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
    ):
        self.index = index
        self.name = name
        self.display_name = None
        self.features = {i: FakeFeature(outputs) for i in range(feature_count)}
        self.outputs_sent: list[Any] = []
        self.stop_calls = 0

    def has_output(self, output_type: OutputType | str) -> bool:
        return any(f.has_output(output_type) for f in self.features.values())

    async def run_output(self, command: Any) -> None:
        if not self.has_output(command.output_type):
            raise RuntimeError(f"no {command.output_type} features")
        self.outputs_sent.append(command)

    async def stop(self) -> None:
        self.stop_calls += 1


class FakeButtplugClient:
    """Mimics ButtplugClient with scripted connect failures and manual events."""

    def __init__(self, connect_error: Exception | None = None):
        self.name = "ButtplugST"
        self.connected = False
        self.scanning = False
        self.devices: dict[int, FakeDevice] = {}
        self.connect_error = connect_error
        self.connect_calls = 0
        self.disconnect_calls = 0

        self.on_device_added = None
        self.on_device_removed = None
        self.on_scanning_finished = None
        self.on_server_disconnect = None
        self.on_error = None

    # ---- client API ----

    async def connect(self, url: str) -> None:
        self.connect_calls += 1
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        for device in list(self.devices.values()):
            await self._fire(self.on_device_added, device)

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

    @staticmethod
    async def _fire(callback: Any, *args: Any) -> None:
        if callback is None:
            return
        result = callback(*args)
        if inspect.isawaitable(result):
            await result

    async def add_device(self, device: FakeDevice) -> None:
        """Simulate the server discovering a device (during or after connect)."""
        self.devices[device.index] = device
        await self._fire(self.on_device_added, device)

    async def remove_device(self, index: int) -> None:
        """Simulate the server dropping a device (fires on_device_removed)."""
        device = self.devices.pop(index, None)
        if device is not None:
            await self._fire(self.on_device_removed, device)

    async def server_disconnect(self) -> None:
        """Simulate an unexpected server drop (on_server_disconnect only)."""
        self.connected = False
        self.scanning = False
        self.devices.clear()
        await self._fire(self.on_server_disconnect)

    async def finish_scanning(self) -> None:
        """Simulate the server's ScanningFinished message."""
        self.scanning = False
        await self._fire(self.on_scanning_finished)
