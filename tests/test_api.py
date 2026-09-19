"""HTTP API behavior via the Quart test client: envelope shapes, GET/POST
parity, validation errors, and status-code mapping."""

from __future__ import annotations

import pytest
from buttplug import ButtplugConnectorError

from buttplug_st.app import create_app
from buttplug_st.config import Settings
from buttplug_st.core.device import DeviceManager

from .fake_client import FakeButtplugClient, FakeDevice


def make_app(client: FakeButtplugClient):
    manager = DeviceManager(Settings(), client_factory=lambda name: client)
    app = create_app(Settings(), device_manager=manager)
    return app, manager


async def get_json(response):
    return await response.get_json()


# ---------- status ----------


async def test_status_truthful_while_intiface_down():
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("refused"))
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        response = await test_client.get("/status")
        assert response.status_code == 200
        body = await get_json(response)
        assert body["success"] is True
        assert body["data"]["intiface_connected"] is False
        assert body["data"]["has_devices"] is False
        assert body["data"]["active_device"] is None
        assert body["data"]["websocket_url"] == "ws://127.0.0.1:12345"


async def test_status_connected_with_active_device():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        response = await test_client.get("/status")
        body = await get_json(response)
        assert body["data"]["intiface_connected"] is True
        assert body["data"]["active_device"]["name"] == "Toy A"


# ---------- legacy GET compatibility ----------


async def test_legacy_get_vibrate_parity():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        toy = FakeDevice(1, "Toy A")
        await client.add_device(toy)

        response = await test_client.get("/vibrate?speed=0.7&duration=5")
        assert response.status_code == 200
        body = await get_json(response)
        assert body["success"] is True
        assert body["message"] == "Vibrating at 70% power for 5.0 seconds"
        assert body["data"] == {
            "success": True,
            "device": "Toy A",
            "speed": 0.7,
            "duration": 5.0,
        }
        assert toy.outputs_sent[0].value == pytest.approx(0.7)


async def test_get_vibrate_defaults():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        response = await test_client.get("/vibrate")
        body = await get_json(response)
        assert body["data"]["speed"] == 0.5
        assert "duration" not in body["data"]


async def test_get_devices_is_read_only():
    client = FakeButtplugClient()
    app, manager = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))

        response = await test_client.get("/devices")
        assert response.status_code == 200
        body = await get_json(response)
        assert body["data"]["devices"] == [
            {
                "id": "1",
                "name": "Toy A",
                "index": 0,
                "actuator_count": 1,
                "actuator_types": ["Vibrate"],
            }
        ]
        assert body["data"]["active_index"] == 0
        assert client.scanning is False
        assert manager.has_devices is True


async def test_get_devices_active_index_negative_when_none():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        await client.remove_device(1)
        response = await test_client.get("/devices")
        body = await get_json(response)
        assert body["data"]["active_index"] == -1


# ---------- POST endpoints ----------


async def test_post_vibrate_parity():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        toy = FakeDevice(1, "Toy A")
        await client.add_device(toy)

        response = await test_client.post("/vibrate", json={"speed": 0.7, "duration": 5})
        assert response.status_code == 200
        body = await get_json(response)
        assert body["success"] is True
        assert body["message"] == "Vibrating at 70% power for 5.0 seconds"
        assert body["data"]["device"] == "Toy A"
        assert body["data"]["speed"] == 0.7
        assert body["data"]["duration"] == 5.0


async def test_post_stop_and_get_stop():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        toy = FakeDevice(1, "Toy A")
        await client.add_device(toy)

        response = await test_client.post("/stop", json={})
        assert response.status_code == 200
        body = await get_json(response)
        assert body == {
            "success": True,
            "message": "Device stopped",
            "data": {"success": True, "device": "Toy A", "status": "stopped"},
        }
        assert toy.stop_calls == 1

        response = await test_client.get("/stop")
        assert response.status_code == 200
        assert toy.stop_calls == 2


async def test_post_device_selection():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        await client.add_device(FakeDevice(2, "Toy B"))

        response = await test_client.post("/device", json={"index": 1})
        assert response.status_code == 200
        body = await get_json(response)
        assert body["message"] == "Selected device: Toy B"
        assert body["data"]["name"] == "Toy B"

        response = await test_client.post("/device", json={"index": 9})
        assert response.status_code == 404
        body = await get_json(response)
        assert body["error"] == "device_not_found"


# ---------- structured validation errors ----------


async def test_non_numeric_speed_maps_to_400():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        response = await test_client.get("/vibrate?speed=abc")
        assert response.status_code == 400
        body = await get_json(response)
        assert body["error"] == "validation_error"
        assert body["status_code"] == 400
        assert "speed" in body["detail"]


async def test_out_of_range_speed_maps_to_400():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        response = await test_client.get("/vibrate?speed=1.5")
        assert response.status_code == 400
        body = await get_json(response)
        assert "speed" in body["detail"]


async def test_post_vibrate_out_of_range_speed_maps_to_400():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Toy A"))
        response = await test_client.post("/vibrate", json={"speed": 42})
        assert response.status_code == 400
        body = await get_json(response)
        assert "speed" in body["detail"]


async def test_get_vibrate_position_parity():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        toy = FakeDevice(1, "Toy A", outputs=("Vibrate", "Position"))
        await client.add_device(toy)

        response = await test_client.get("/vibrate?speed=0.5&position=1.0")
        assert response.status_code == 200
        body = await get_json(response)
        assert body["message"] == "Vibrating at 50% power, position 100%"
        assert body["data"]["position"] == 1.0
        assert body["data"]["position_applied"] is True


async def test_vibrate_on_non_vibrating_device_maps_to_404():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        await client.add_device(FakeDevice(1, "Rotator", outputs=("Rotate",)))
        response = await test_client.get("/vibrate?speed=0.5")
        assert response.status_code == 404
        body = await get_json(response)
        assert body["error"] == "device_not_found"


async def test_post_vibrate_malformed_body_maps_to_400_not_defaults():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        toy = FakeDevice(1, "Toy A")
        await client.add_device(toy)

        # A truncated payload must never silently vibrate at the default speed.
        response = await test_client.post("/vibrate", data='{"speed": 0')
        assert response.status_code == 400
        body = await get_json(response)
        assert body["error"] == "validation_error"

        # An absent body is fine and uses the defaults.
        response = await test_client.post("/vibrate")
        assert response.status_code == 200
        body = await get_json(response)
        assert body["data"]["speed"] == 0.5

        # A non-object JSON body is also a 400.
        response = await test_client.post("/vibrate", json=[0.7])
        assert response.status_code == 400


# ---------- status-code mapping ----------


async def test_vibrate_without_devices_maps_to_404():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        response = await test_client.get("/vibrate?speed=0.7")
        assert response.status_code == 404
        body = await get_json(response)
        assert body["error"] == "device_not_found"


async def test_vibrate_while_intiface_down_maps_to_503():
    client = FakeButtplugClient(connect_error=ButtplugConnectorError("refused"))
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        response = await test_client.get("/vibrate?speed=0.7")
        assert response.status_code == 503
        body = await get_json(response)
        assert body["error"] == "intiface_unavailable"
        assert body["status_code"] == 503


async def test_unknown_route_returns_json_envelope():
    client = FakeButtplugClient()
    app, _ = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()
        response = await test_client.get("/nope")
        assert response.status_code == 404
        body = await get_json(response)
        assert body["error"] == "not_found"
        assert body["status_code"] == 404


# ---------- scan ----------


async def test_scan_endpoint_returns_devices():
    client = FakeButtplugClient()
    app, manager = make_app(client)
    async with app.test_app() as test_app:
        test_client = test_app.test_client()

        import asyncio

        async def discover():
            await asyncio.sleep(0)
            await client.add_device(FakeDevice(1, "Toy A"))
            await client.finish_scanning()

        discover_task = asyncio.create_task(discover())
        response = await test_client.get("/scan")
        await discover_task
        assert response.status_code == 200
        body = await get_json(response)
        assert body["data"]["count"] == 1
        assert body["data"]["devices"][0]["name"] == "Toy A"
