"""Device management on the official buttplug 1.0.0 client.

The device list is maintained by client events (device added/removed/server
disconnect); listing devices never triggers a scan and never resets the active
selection, which is tracked by the server-assigned device index (stable device
identity) rather than list position.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from ..config import Settings
from .buttplug_adapter import (
    ButtplugClient,
    ButtplugConnectorError,
    ButtplugDevice,
    ButtplugError,
    DeviceOutputCommand,
    OutputType,
)
from .exceptions import CommandError, DeviceNotFoundError, IntifaceUnavailableError

logger = logging.getLogger(__name__)

#: How long a POSITION_WITH_DURATION move takes to reach the target position.
POSITION_MOVE_MS = 500

SleepFn = Callable[[float], Awaitable[None]]
ClockFn = Callable[[], float]


@dataclass(frozen=True)
class DeviceInfo:
    """Public snapshot of a tracked device."""

    id: str
    name: str
    index: int
    actuator_count: int
    actuator_types: list[str] = field(default_factory=list)
    server_index: int = -1  # buttplug server-assigned identity (not part of the API shape)
    supports_position: bool = False


class DeviceManager:
    """Owns the Intiface connection, device tracking, and device commands."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[str], ButtplugClient] | None = None,
        sleep_fn: SleepFn = asyncio.sleep,
        clock_fn: ClockFn = time.monotonic,
    ) -> None:
        self.settings = settings
        self._client_factory = client_factory if client_factory is not None else ButtplugClient
        self._sleep = sleep_fn
        self._clock = clock_fn
        self._client: ButtplugClient | None = None
        self._devices: list[ButtplugDevice] = []  # kept ordered by server index
        self._active_server_index: int | None = None
        self._auto_stop_task: asyncio.Task | None = None
        self._scan_finished: asyncio.Event | None = None
        self._last_connection_attempt: float | None = None  # None = never attempted
        self._reconnect_min_interval = 5.0

    # ---------- state properties ----------

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.connected

    @property
    def has_devices(self) -> bool:
        return len(self._devices) > 0

    # ---------- lifecycle ----------

    async def start(self) -> None:
        """Attempt the initial connection. Non-fatal: the server must serve
        HTTP even when Intiface Central is down."""
        try:
            await self._connect()
        except IntifaceUnavailableError as exc:
            logger.warning("Intiface Central not reachable at startup: %s", exc)

    async def shutdown(self) -> None:
        """Cancel the pending auto-stop and disconnect cleanly."""
        await self._cancel_auto_stop()
        if self._client is not None:
            try:
                await self._client.disconnect()  # stops all devices first
            except ButtplugError as exc:
                logger.warning("Error during client disconnect: %s", exc.message)
            self._client = None
        self._devices = []
        self._active_server_index = None
        logger.debug("Device manager shut down")

    async def ensure_ready(self) -> ButtplugClient:
        """Return the connected client, attempting one throttled reconnect.

        Raises IntifaceUnavailableError when Intiface is down or the retry
        interval has not elapsed since the last attempt.
        """
        if self.is_connected:
            assert self._client is not None
            return self._client
        await self._connect()
        assert self._client is not None
        return self._client

    async def _connect(self) -> None:
        if self._last_connection_attempt is not None:
            elapsed = self._clock() - self._last_connection_attempt
            if elapsed < self._reconnect_min_interval:
                raise IntifaceUnavailableError(
                    "Intiface Central is not available "
                    f"(retry allowed in {self._reconnect_min_interval - elapsed:.1f}s)"
                )
        self._last_connection_attempt = self._clock()

        client = self._client_factory("ButtplugST")
        client.on_device_added = self._on_device_added
        client.on_device_removed = self._on_device_removed
        client.on_scanning_finished = self._on_scanning_finished
        client.on_server_disconnect = self._on_server_disconnect
        client.on_error = self._on_error
        try:
            # Already-paired devices fire on_device_added during connect().
            await client.connect(self.settings.websocket.url)
        except ButtplugConnectorError as exc:
            logger.info(
                "Could not connect to Intiface at %s: %s",
                self.settings.websocket.url,
                exc.message,
            )
            raise IntifaceUnavailableError(
                f"Could not connect to Intiface at {self.settings.websocket.url}"
            ) from exc
        except ButtplugError as exc:
            raise IntifaceUnavailableError(f"Intiface handshake failed: {exc.message}") from exc
        self._client = client
        # A successful connect proves Intiface is up again: clear the throttle.
        self._last_connection_attempt = None
        logger.info("Connected to Intiface at %s", self.settings.websocket.url)

    # ---------- client events ----------

    async def _on_device_added(self, device: ButtplugDevice) -> None:
        logger.debug("Device added: %s (server index %s)", device.name, device.index)
        # De-duplicate by server index: a device may be re-announced (e.g. on reconnect).
        self._devices = sorted(
            [d for d in self._devices if d.index != device.index] + [device],
            key=lambda d: d.index,
        )
        if self._active_server_index is None:
            self._active_server_index = device.index

    async def _on_device_removed(self, device: ButtplugDevice) -> None:
        logger.debug("Device removed: %s (server index %s)", device.name, device.index)
        self._devices = [d for d in self._devices if d.index != device.index]
        if self._active_server_index == device.index:
            self._active_server_index = None
            await self._cancel_auto_stop()

    async def _on_scanning_finished(self) -> None:
        logger.debug("Scanning finished")
        if self._scan_finished is not None:
            self._scan_finished.set()

    async def _on_server_disconnect(self) -> None:
        logger.warning("Intiface server disconnected")
        # The client clears its own device dict without per-device removal
        # callbacks, so the tracked list and selection must be cleared here.
        self._client = None
        self._devices = []
        self._active_server_index = None
        await self._cancel_auto_stop()

    async def _on_error(self, exc: Exception) -> None:
        logger.debug("Intiface server error: %s", exc)

    # ---------- devices ----------

    def list_devices(self) -> list[DeviceInfo]:
        return [self._device_info(d, i) for i, d in enumerate(self._devices)]

    def get_active_device(self) -> DeviceInfo | None:
        active = self._active_device_object()
        if active is None:
            return None
        return self._device_info(active, self._devices.index(active))

    def set_active_device(self, index: int) -> DeviceInfo:
        """Select the active device by list index."""
        if index < 0 or index >= len(self._devices):
            raise DeviceNotFoundError(f"Device index {index} out of range")
        device = self._devices[index]
        self._active_server_index = device.index
        logger.debug("Active device set to %s (server index %s)", device.name, device.index)
        return self._device_info(device, index)

    def _active_device_object(self) -> ButtplugDevice | None:
        for device in self._devices:
            if device.index == self._active_server_index:
                return device
        return None

    def _device_info(self, device: ButtplugDevice, index: int) -> DeviceInfo:
        output_features = [f for f in device.features.values() if f.outputs]
        output_types: set[str] = set()
        for feature in output_features:
            output_types.update(feature.outputs.keys())
        return DeviceInfo(
            id=str(device.index),
            name=device.name,
            index=index,
            # Legacy servers counted actuator features (a dual-motor vibrator -> 2).
            actuator_count=len(output_features),
            actuator_types=sorted(output_types),
            server_index=device.index,
            supports_position=device.has_output(OutputType.POSITION_WITH_DURATION)
            or device.has_output(OutputType.POSITION),
        )

    # ---------- scan ----------

    async def scan(self) -> list[DeviceInfo]:
        """Explicitly scan for devices, bounded by the configured timeout.

        The selection is untouched: if the active device is still present it
        stays active; if it vanished, its removal event already cleared it.
        """
        await self.ensure_ready()
        finished = asyncio.Event()
        self._scan_finished = finished
        client = self._client
        assert client is not None
        try:
            await client.start_scanning()
            # Bounded scan: on timeout report whatever arrived.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    finished.wait(), timeout=self.settings.websocket.scan_timeout
                )
        except ButtplugError as exc:
            raise IntifaceUnavailableError(f"Scan failed: {exc.message}") from exc
        finally:
            self._scan_finished = None
            if client.scanning:
                with contextlib.suppress(ButtplugError):
                    await client.stop_scanning()
        return self.list_devices()

    # ---------- commands ----------

    async def vibrate(
        self, speed: float, position: float | None = None, duration: float = 0.0
    ) -> dict:
        """Vibrate all vibration outputs of the active device.

        Position is applied only where the device supports it; the response
        reports whether it was applied.
        """
        await self.ensure_ready()
        device = self._active_device_object()
        if device is None:
            raise DeviceNotFoundError()
        if not device.has_output(OutputType.VIBRATE):
            # Legacy servers answered 404 when the active device could not vibrate.
            raise DeviceNotFoundError(f"{device.name} has no vibration outputs")

        speed = min(1.0, max(0.0, speed))
        result: dict = {"success": True, "device": device.name, "speed": speed}

        if speed == 0.0:
            # Speed 0 silences the device, same as stop.
            await self._cancel_auto_stop()
            try:
                await device.run_output(DeviceOutputCommand(OutputType.VIBRATE, 0.0))
            except ButtplugError as exc:
                raise CommandError(f"Error sending vibrate command: {exc.message}") from exc
            if duration > 0:
                result["duration"] = duration
            return result

        commands = [DeviceOutputCommand(OutputType.VIBRATE, speed)]
        if position is not None:
            position = min(1.0, max(0.0, position))
            result["position"] = position
            if device.has_output(OutputType.POSITION_WITH_DURATION):
                commands.append(
                    DeviceOutputCommand(
                        OutputType.POSITION_WITH_DURATION,
                        position,
                        duration=POSITION_MOVE_MS,
                    )
                )
                result["position_applied"] = True
            elif device.has_output(OutputType.POSITION):
                commands.append(DeviceOutputCommand(OutputType.POSITION, position))
                result["position_applied"] = True
            else:
                result["position_applied"] = False

        logger.debug(
            "Vibrating %s at %.0f%% power%s",
            device.name,
            speed * 100,
            f", position {result['position']}" if position is not None else "",
        )
        try:
            for command in commands:
                await device.run_output(command)
        except ButtplugError as exc:
            raise CommandError(f"Error sending vibrate command: {exc.message}") from exc

        if duration > 0:
            await self._schedule_auto_stop(device, duration)
            result["duration"] = duration
        return result

    async def stop(self) -> dict:
        """Stop all outputs of the active device."""
        await self.ensure_ready()
        device = self._active_device_object()
        if device is None:
            raise DeviceNotFoundError()
        await self._cancel_auto_stop()
        logger.debug("Stopping %s", device.name)
        try:
            await device.stop()
        except ButtplugError as exc:
            raise CommandError(f"Error stopping device: {exc.message}") from exc
        return {"success": True, "device": device.name, "status": "stopped"}

    # ---------- timed auto-stop ----------

    async def _schedule_auto_stop(self, device: ButtplugDevice, duration: float) -> None:
        """Replace any pending auto-stop with one new timer (single source of truth)."""
        await self._cancel_auto_stop()
        task = asyncio.create_task(self._stop_after_delay(device, duration))
        task.add_done_callback(lambda t: self._forget_auto_stop_task(t))
        self._auto_stop_task = task

    def _forget_auto_stop_task(self, task: asyncio.Task) -> None:
        if self._auto_stop_task is task:
            self._auto_stop_task = None

    async def _cancel_auto_stop(self) -> None:
        task = self._auto_stop_task
        self._auto_stop_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _stop_after_delay(self, device: ButtplugDevice, duration: float) -> None:
        await self._sleep(duration)
        logger.debug("Auto-stop firing for %s after %.1fs", device.name, duration)
        try:
            await device.stop()
        except ButtplugError as exc:
            logger.warning("Auto-stop failed for %s: %s", device.name, exc.message)

    # ---------- status ----------

    def status_snapshot(self) -> dict:
        """Truthful status regardless of Intiface state (for GET /status)."""
        active = self.get_active_device()
        if self._client is None:
            client_state = "Not created"
        elif self._client.connected:
            client_state = "Connected"
        else:
            client_state = "Disconnected"
        active_payload = None
        if active is not None:
            active_payload = {
                "id": active.id,
                "name": active.name,
                "index": active.index,
                "actuator_count": active.actuator_count,
                "actuator_types": active.actuator_types,
            }
        return {
            "status": "ok" if self.is_connected else "error",
            "server_running": True,
            "server_initialized": self.is_connected,
            "intiface_connected": self.is_connected,
            "client_state": client_state,
            "device_count": len(self._devices),
            "has_devices": bool(self._devices),
            "websocket_url": self.settings.websocket.url,
            "active_device": active_payload,
        }
