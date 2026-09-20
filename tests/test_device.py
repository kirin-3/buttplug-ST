"""DeviceManager behavior on the official client, driven by a fake client."""

from __future__ import annotations

import asyncio
from typing import cast

import pytest
from buttplug import ButtplugClient, ButtplugConnectorError

from buttplug_st.config import Settings
from buttplug_st.core.device import DeviceManager
from buttplug_st.core.exceptions import (
    DeviceNotFoundError,
    IntifaceUnavailableError,
)

from .fake_client import FakeButtplugClient, FakeDevice


class FakeClock:
    """Controllable monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self.now: float = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class GatedSleep:
    """Sleep stand-in: records delays; blocks until the gate opens."""

    def __init__(self) -> None:
        self.delays: list[float] = []
        self.gate: asyncio.Event = asyncio.Event()
        self.gate.set()

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        _ = await self.gate.wait()


def make_manager(
    client: FakeButtplugClient,
    sleep: GatedSleep | None = None,
    clock: FakeClock | None = None,
) -> DeviceManager:
    # The fake intentionally implements only the client surface DeviceManager
    # uses, so the factory cast is the one sanctioned seam in these tests.
    def factory(_name: str) -> ButtplugClient:
        # object-first cast: the fake deliberately is not a ButtplugClient subclass
        return cast(ButtplugClient, cast("object", client))

    return DeviceManager(
        Settings(),
        client_factory=factory,
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
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("refused"))
    manager = make_manager(client)
    await manager.start()
    with pytest.raises(IntifaceUnavailableError):
        _ = await manager.vibrate(0.7)
    with pytest.raises(IntifaceUnavailableError):
        _ = await manager.stop()


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
    active = manager.get_active_device()
    assert active is not None
    assert active.name == "Toy A"  # first device auto-selected


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
        _ = await manager.vibrate(0.5)


async def test_rescan_preserves_selection():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    for i in (1, 2, 3):
        await client.add_device(FakeDevice(i, f"Toy {i}"))

    _ = manager.set_active_device(1)
    active = manager.get_active_device()
    assert active is not None
    assert active.name == "Toy 2"

    scan_task = asyncio.create_task(manager.scan())
    _ = await asyncio.sleep(0)
    await client.finish_scanning()
    devices = await scan_task

    assert [d.name for d in devices] == ["Toy 1", "Toy 2", "Toy 3"]
    still_active = manager.get_active_device()
    assert still_active is not None
    assert still_active.name == "Toy 2"  # selection survived


async def test_listing_devices_does_not_scan():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    await client.add_device(FakeDevice(1, "Toy A"))
    _ = manager.list_devices()
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
        _ = manager.set_active_device(9)


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
    assert result.get("position") == 1.0
    assert result.get("position_applied") is True
    types = [c.output_type.value for c in toy.outputs_sent]
    assert types == ["Vibrate", "HwPositionWithDuration"]
    assert toy.outputs_sent[1].duration is not None


async def test_vibrate_position_falls_back_to_plain_position():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1, "Positioner", outputs=("Vibrate", "Position"))
    await client.add_device(toy)

    result = await manager.vibrate(0.5, position=1.0)
    assert result.get("position_applied") is True
    types = [c.output_type.value for c in toy.outputs_sent]
    assert types == ["Vibrate", "Position"]
    assert toy.outputs_sent[1].duration is None  # plain position has no duration


async def test_vibrate_position_reported_not_applied_on_vibration_only_device():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    toy = FakeDevice(1, "Plain Vibe", outputs=("Vibrate",))
    await client.add_device(toy)

    result = await manager.vibrate(0.5, position=0.8)
    assert result["device"] == "Plain Vibe"
    assert result.get("position") == 0.8
    assert result.get("position_applied") is False
    assert [c.output_type.value for c in toy.outputs_sent] == ["Vibrate"]


async def test_vibrate_on_non_vibrating_device_raises_not_found():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    await client.add_device(FakeDevice(1, "Rotator", outputs=("Rotate",)))
    with pytest.raises(DeviceNotFoundError):
        _ = await manager.vibrate(0.5)
    with pytest.raises(DeviceNotFoundError):
        _ = await manager.vibrate(0.0)  # speed-0 path gets the same treatment


async def test_actuator_count_counts_features_not_types():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    dual = FakeDevice(1, "Dual Motor", feature_count=2)
    await client.add_device(dual)
    info = manager.list_devices()[0]
    assert info.actuator_count == 2  # legacy semantics: features, not distinct types
    assert info.actuator_types == ["Vibrate"]


async def test_vibrate_with_no_devices_raises_not_found():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()
    with pytest.raises(DeviceNotFoundError):
        _ = await manager.vibrate(0.5)


# ---------- timed auto-stop ----------


async def test_auto_stop_fires_after_duration():
    sleep = GatedSleep()  # gate open: the timer completes immediately
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    result = await manager.vibrate(0.8, duration=2.0)
    assert result.get("duration") == 2.0
    timer = manager.pending_auto_stop
    assert timer is not None
    await timer
    assert toy.stop_calls == 1
    assert manager.pending_auto_stop is None


async def test_overlapping_vibrate_leaves_exactly_one_timer():
    sleep = GatedSleep()
    sleep.gate.clear()  # timers block until released
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    _ = await manager.vibrate(0.8, duration=30.0)
    stale_timer = manager.pending_auto_stop
    assert stale_timer is not None
    _ = await asyncio.sleep(0)  # let the timer start sleeping

    _ = await manager.vibrate(0.6, duration=2.0)
    fresh_timer = manager.pending_auto_stop
    assert fresh_timer is not None
    assert stale_timer is not fresh_timer
    assert stale_timer.cancelled() or stale_timer.done()
    assert not fresh_timer.done()

    sleep.gate.set()  # the fresh timer's delay elapses
    await fresh_timer
    assert toy.stop_calls == 1  # silenced exactly once, by the fresh timer


async def test_indefinite_vibrate_cancels_pending_timer():
    sleep = GatedSleep()
    sleep.gate.clear()
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    _ = await manager.vibrate(0.8, duration=30.0)
    stale_timer = manager.pending_auto_stop
    assert stale_timer is not None
    _ = await asyncio.sleep(0)  # let the timer start sleeping

    # A new indefinite command must not inherit the previous auto-stop.
    _ = await manager.vibrate(0.6)
    assert manager.pending_auto_stop is None
    assert stale_timer.cancelled()
    assert toy.outputs_sent[-1].value == pytest.approx(0.6)

    sleep.gate.set()  # the stale timer must never fire
    _ = await asyncio.sleep(0)
    _ = await asyncio.sleep(0)
    assert toy.stop_calls == 0


async def test_stop_cancels_pending_auto_stop():
    sleep = GatedSleep()
    sleep.gate.clear()
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    _ = await manager.vibrate(0.8, duration=30.0)
    timer = manager.pending_auto_stop
    assert timer is not None
    _ = await asyncio.sleep(0)

    result = await manager.stop()
    assert result["status"] == "stopped"
    assert timer.cancelled()
    assert toy.stop_calls == 1  # only the explicit stop

    sleep.gate.set()  # stale timer would fire here if it survived
    _ = await asyncio.sleep(0)
    _ = await asyncio.sleep(0)
    assert toy.stop_calls == 1


async def test_shutdown_cancels_pending_auto_stop_and_disconnects():
    sleep = GatedSleep()
    sleep.gate.clear()
    client = FakeButtplugClient()
    manager = make_manager(client, sleep=sleep)
    await manager.start()
    toy = FakeDevice(1)
    await client.add_device(toy)

    _ = await manager.vibrate(0.8, duration=30.0)
    timer = manager.pending_auto_stop
    assert timer is not None
    await manager.shutdown()
    assert timer.cancelled()
    assert manager.pending_auto_stop is None
    assert client.disconnect_calls == 1
    assert manager.list_devices() == []
    assert manager.is_connected is False


# ---------- scan ----------


async def test_scan_returns_devices_and_stops_scanning():
    client = FakeButtplugClient()
    manager = make_manager(client)
    await manager.start()

    async def discover_later():
        _ = await asyncio.sleep(0)
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
        _ = await manager.scan()
