"""DeviceManager behavior on the official client, driven by a fake client."""

from __future__ import annotations

import asyncio

import pytest
from buttplug import ButtplugConnectorError

from buttplug_st.config import Settings
from buttplug_st.core.device import DeviceManager
from buttplug_st.core.exceptions import (
    DeviceNotFoundError,
    IntifaceUnavailableError,
)

from .fake_client import FakeButtplugClient, FakeDevice


class FakeClock:
    """Controllable monotonic clock."""

    def __init__(self, start: float = 0.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class GatedSleep:
    """Sleep stand-in: records delays; blocks until the gate opens."""

    def __init__(self):
        self.delays: list[float] = []
        self.gate = asyncio.Event()
        self.gate.set()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        await self.gate.wait()


def make_manager(
    client: FakeButtplugClient,
    sleep: GatedSleep | None = None,
    clock: FakeClock | None = None,
) -> DeviceManager:
    return DeviceManager(
        Settings(),
        client_factory=lambda name: client,
        sleep_fn=sleep if sleep is not None else asyncio.sleep,
        clock_fn=clock if clock is not None else FakeClock(),
    )


# ---------- startup / Intiface down ----------


async def test_start_with_intiface_down_serves_anyway():
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("connection refused"))
    manager = make_manager(client)
    await manager.start()  # must not raise
    assert manager.is_connected is False
    snapshot = manager.status_snapshot()
    assert snapshot["intiface_connected"] is False
    assert snapshot["has_devices"] is False
    assert snapshot["active_device"] is None


async def test_command_while_disconnected_raises_unavailable():
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("connection refused"))
    manager = make_manager(client)
    await manager.start()
    with pytest.raises(IntifaceUnavailableError):
        await manager.vibrate(0.7)
    with pytest.raises(IntifaceUnavailableError):
        await manager.stop()


async def test_reconnect_attempts_are_throttled():
    clock = FakeClock()
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("refused"))
    manager = make_manager(client, clock=clock)
    await manager.start()
    assert client.connect_calls == 1

    with pytest.raises(IntifaceUnavailableError):
        await manager.ensure_ready()
    assert client.connect_calls == 1  # throttled, no new attempt

    clock.advance(5.0)
    with pytest.raises(IntifaceUnavailableError):
        await manager.ensure_ready()
    assert client.connect_calls == 2  # interval elapsed, attempt allowed


# ---------- event-driven device tracking ----------


async def test_devices_appear_via_events_without_scan():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    await client.add_device(FakeDevice(1, "Toy A"))
    await client.add_device(FakeDevice(2, "Toy B"))

    names = [d.name for d in manager.list_devices()]
    assert names == ["Toy A", "Toy B"]  # ordered by server index
    assert manager.get_active_device().name == "Toy A"  # first device auto-selected


async def test_device_removal_updates_list_and_clears_selection():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy_a = FakeDevice(1, "Toy A")
    await client.add_device(toy_a)
    await client.add_device(FakeDevice(2, "Toy B"))

    await client.remove_device(1)
    assert [d.name for d in manager.list_devices()] == ["Toy B"]
    assert manager.get_active_device() is None  # active device was removed
    with pytest.raises(DeviceNotFoundError):
        await manager.vibrate(0.5)


async def test_rescan_preserves_selection():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    for i in (1, 2, 3):
        await client.add_device(FakeDevice(i, f"Toy {i}"))

    manager.set_active_device(1)
    assert manager.get_active_device().name == "Toy 2"

    scan_task = asyncio.create_task(manager.scan())
    await asyncio.sleep(0)
    await client.finish_scanning()
    devices = await scan_task

    assert [d.name for d in devices] == ["Toy 1", "Toy 2", "Toy 3"]
    assert manager.get_active_device().name == "Toy 2"  # selection survived


async def test_listing_devices_does_not_scan():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    await client.add_device(FakeDevice(1, "Toy A"))
    manager.list_devices()
    assert client.scanning is False


async def test_server_disconnect_clears_everything_and_recovers():
    clock = FakeClock()
    client = FakeButtplugClient()
    manager = make_manager(client, clock=clock)
    await manager.start()
    await client.add_device(FakeDevice(1, "Toy A", outputs=("Vibrate",)))

    await client.server_disconnect()
    assert manager.is_connected is False
    assert manager.list_devices() == []
    assert manager.get_active_device() is None

    # Intiface comes back: the device re-announces during the reconnect
    # handshake (throttle does not apply because the successful start() reset
    # the last-attempt stamp).
    client.devices[1] = FakeDevice(1, "Toy A")  # registered server-side
    result = await manager.vibrate(0.5)
    assert result["device"] == "Toy A"
    assert manager.is_connected is True


# ---------- selection ----------


async def test_select_out_of_range_raises():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    await client.add_device(FakeDevice(1, "Toy A"))
    with pytest.raises(DeviceNotFoundError):
        manager.set_active_device(9)


# ---------- vibrate ----------


async def test_vibrate_commands_all_vibration_outputs():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1, "Dual Motor", feature_count=2)
    await client.add_device(toy)

    result = await manager.vibrate(0.7)
    assert result == {"success": True, "device": "Dual Motor", "speed": 0.7}
    assert len(toy.outputs_sent) == 1
    command = toy.outputs_sent[0]
    assert command.output_type.value == "Vibrate"
    assert command.value == pytest.approx(0.7)


async def test_vibrate_speed_clamped():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)
    result = await manager.vibrate(7.5)
    assert result["speed"] == 1.0
    assert toy.outputs_sent[0].value == 1.0


async def test_vibrate_speed_zero_silences_device():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)
    result = await manager.vibrate(0.0)
    assert result["speed"] == 0.0
    assert toy.outputs_sent[0].value == 0.0


async def test_vibrate_position_applied_on_supporting_device():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1, "Stroker", outputs=("Vibrate", "HwPositionWithDuration"))
    await client.add_device(toy)

    result = await manager.vibrate(0.5, position=1.0)
    assert result["position"] == 1.0
    assert result["position_applied"] is True
    types = [c.output_type.value for c in toy.outputs_sent]
    assert types == ["Vibrate", "HwPositionWithDuration"]
    assert toy.outputs_sent[1].duration is not None


async def test_vibrate_position_reported_not_applied_on_vibration_only_device():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1, "Plain Vibe", outputs=("Vibrate",))
    await client.add_device(toy)

    result = await manager.vibrate(0.5, position=0.8)
    assert result["device"] == "Plain Vibe"
    assert result["position"] == 0.8
    assert result["position_applied"] is False
    assert [c.output_type.value for c in toy.outputs_sent] == ["Vibrate"]


async def test_vibrate_with_no_devices_raises_not_found():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    with pytest.raises(DeviceNotFoundError):
        await manager.vibrate(0.5)


# ---------- timed auto-stop ----------


async def test_auto_stop_fires_after_duration():
    sleep = GatedSleep()  # gate open: the timer completes immediately
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    result = await manager.vibrate(0.8, duration=2.0)
    assert result["duration"] == 2.0
    assert manager._auto_stop_task is not None
    await manager._auto_stop_task
    assert toy.stop_calls == 1
    assert manager._auto_stop_task is None


async def test_overlapping_vibrate_leaves_exactly_one_timer():
    sleep = GatedSleep()
    sleep.gate.clear()  # timers block until released
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    await manager.vibrate(0.8, duration=30.0)
    stale_task = manager._auto_stop_task
    await asyncio.sleep(0)  # let the timer start sleeping

    await manager.vibrate(0.6, duration=2.0)
    fresh_task = manager._auto_stop_task
    assert stale_task is not fresh_task
    assert stale_task.cancelled() or stale_task.done()
    assert not fresh_task.done()

    sleep.gate.set()  # the fresh timer's delay elapses
    await fresh_task
    assert toy.stop_calls == 1  # silenced exactly once, by the fresh timer


async def test_stop_cancels_pending_auto_stop():
    sleep = GatedSleep()
    sleep.gate.clear()
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    await manager.vibrate(0.8, duration=30.0)
    timer = manager._auto_stop_task
    await asyncio.sleep(0)

    result = await manager.stop()
    assert result["status"] == "stopped"
    assert timer.cancelled()
    assert toy.stop_calls == 1  # only the explicit stop

    sleep.gate.set()  # stale timer would fire here if it survived
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert toy.stop_calls == 1


async def test_shutdown_cancels_pending_auto_stop_and_disconnects():
    sleep = GatedSleep()
    sleep.gate.clear()
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    await manager.vibrate(0.8, duration=30.0)
    timer = manager._auto_stop_task
    await manager.shutdown()
    assert timer.cancelled()
    assert manager._auto_stop_task is None
    assert client.disconnect_calls == 1
    assert manager.list_devices() == []
    assert manager.is_connected is False


# ---------- scan ----------


async def test_scan_returns_devices_and_stops_scanning():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()

    async def discover_later():
        await asyncio.sleep(0)
        await client.add_device(FakeDevice(1, "Toy A"))

    discover = asyncio.create_task(discover_later())
    scan_task = asyncio.create_task(manager.scan())
    await discover
    await client.finish_scanning()
    devices = await scan_task

    assert [d.name for d in devices] == ["Toy A"]
    assert client.scanning is False


async def test_scan_requires_connection():
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("refused"))
    manager = make_manager(client)
    await manager.start()
    with pytest.raises(IntifaceUnavailableError):
        await manager.scan()
