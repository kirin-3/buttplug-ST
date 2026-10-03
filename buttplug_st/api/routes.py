"""HTTP API routes.

GET endpoints keep their legacy paths, query parameters, defaults, and response
shapes so existing SillyTavern/Sorcery `fetch` calls keep working unchanged;
POST counterparts accept JSON bodies. Both verbs funnel through the same
Pydantic models. All error mapping (400/404/503/500) lives in the app-level
error handlers — routes raise domain exceptions and return only successes.
"""

from __future__ import annotations

import json
import logging
from typing import cast

from quart import Blueprint, Response, jsonify, request

from ..core.device import DeviceInfo, DeviceManager, DevicePayload
from ..core.exceptions import ValidationError
from .schemas import DeviceSelectionRequest, VibrateRequest

logger = logging.getLogger(__name__)

_VIBRATE_PARAMS = ("speed", "position", "duration")


def create_blueprint(device_manager: DeviceManager) -> Blueprint:
    """Create a blueprint with all API routes."""
    api_bp = Blueprint("api", __name__)

    def device_payload(info: DeviceInfo) -> DevicePayload:
        return {
            "id": info.id,
            "name": info.name,
            "index": info.index,
            "actuator_count": info.actuator_count,
            "actuator_types": info.actuator_types,
        }

    async def parse_json_body() -> dict[str, object]:
        """Parse the request body as a JSON object.

        An absent/empty body yields {} (the endpoint's defaults apply); a
        malformed body is a 400 — never silently replaced by defaults.
        """
        raw = await request.get_data()
        if not raw.strip():
            return {}
        try:
            parsed = cast("object", json.loads(raw))
        except ValueError as exc:
            raise ValidationError("Request body must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValidationError("Request body must be a JSON object")
        return cast(dict[str, object], parsed)

    async def parse_vibrate_request() -> VibrateRequest:
        """Build one VibrateRequest from GET query string or POST JSON body."""
        if request.method == "GET":
            raw: dict[str, str] = {
                key: value for key, value in request.args.items() if key in _VIBRATE_PARAMS
            }
            return VibrateRequest.model_validate(raw)
        return VibrateRequest.model_validate(await parse_json_body())

    def vibrate_message(req: VibrateRequest) -> str:
        message = f"Vibrating at {req.speed * 100:.0f}% power"
        if req.position is not None:
            message += f", position {req.position * 100:.0f}%"
        if req.duration > 0:
            message += f" for {req.duration} seconds"
        return message

    @api_bp.route("/status")
    async def status() -> tuple[Response, int]:
        """Get server and device status. Always truthful, any Intiface state."""
        return jsonify(
            {
                "success": True,
                "message": "Server status",
                "data": device_manager.status_snapshot(),
            }
        ), 200

    @api_bp.route("/devices")
    async def list_devices() -> tuple[Response, int]:
        """List tracked devices. A read: never scans, never changes selection."""
        devices = device_manager.list_devices()
        active = device_manager.get_active_device()
        active_index = active.index if active is not None else -1
        return jsonify(
            {
                "success": True,
                "message": f"Found {len(devices)} devices",
                "data": {
                    "devices": [device_payload(d) for d in devices],
                    "active_index": active_index,
                },
            }
        ), 200

    @api_bp.route("/device", methods=["POST"])
    async def select_device() -> tuple[Response, int]:
        """Select the active device by index."""
        req = DeviceSelectionRequest.model_validate(await parse_json_body())
        device_info = device_manager.set_active_device(req.index)
        return jsonify(
            {
                "success": True,
                "message": f"Selected device: {device_info.name}",
                "data": device_payload(device_info),
            }
        ), 200

    @api_bp.route("/scan")
    async def scan() -> tuple[Response, int]:
        """Explicitly scan for devices."""
        devices = await device_manager.scan()
        return jsonify(
            {
                "success": True,
                "message": f"Found {len(devices)} devices",
                "data": {
                    "count": len(devices),
                    "devices": [device_payload(d) for d in devices],
                },
            }
        ), 200

    @api_bp.route("/vibrate", methods=["GET", "POST"])
    async def vibrate() -> tuple[Response, int]:
        """Control vibration of the active device (GET query or POST JSON)."""
        req = await parse_vibrate_request()
        result = await device_manager.vibrate(
            speed=req.speed,
            position=req.position,
            duration=req.duration,
        )
        return jsonify({"success": True, "message": vibrate_message(req), "data": result}), 200

    @api_bp.route("/stop", methods=["GET", "POST"])
    async def stop() -> tuple[Response, int]:
        """Stop all outputs of the active device."""
        result = await device_manager.stop()
        return jsonify({"success": True, "message": "Device stopped", "data": result}), 200

    return api_bp
