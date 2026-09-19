"""Quart application factory, lifecycle wiring, and the `buttplug-st` entry point."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import sys

from pydantic import ValidationError as PydanticValidationError
from quart import Quart, Response, jsonify
from quart_cors import cors
from werkzeug.exceptions import HTTPException

from . import __version__
from .api import create_blueprint
from .api.schemas import format_validation_error
from .config import Settings, SettingsError
from .core.device import DeviceManager
from .core.exceptions import ButtplugSTException

logger = logging.getLogger(__name__)


def create_app(settings: Settings, device_manager: DeviceManager | None = None) -> Quart:
    """Build the Quart app around a single Settings instance and device manager."""
    app = Quart(__name__)
    app = cors(app, allow_origin="*")

    device_mgr = device_manager if device_manager is not None else DeviceManager(settings)
    app.register_blueprint(create_blueprint(device_mgr))

    @app.errorhandler(PydanticValidationError)
    async def handle_validation_error(e: PydanticValidationError) -> tuple[Response, int]:
        return (
            jsonify(
                {
                    "error": "validation_error",
                    "detail": format_validation_error(e),
                    "status_code": 400,
                }
            ),
            400,
        )

    @app.errorhandler(ButtplugSTException)
    async def handle_domain_error(e: ButtplugSTException) -> tuple[Response, int]:
        return jsonify(e.to_dict()), e.status_code

    @app.errorhandler(HTTPException)
    async def handle_http_error(e: HTTPException) -> tuple[Response, int]:
        # Keep even unknown-route errors in the uniform JSON envelope.
        return (
            jsonify(
                {
                    "error": (e.name or "http_error").lower().replace(" ", "_"),
                    "detail": e.description or "",
                    "status_code": e.code or 500,
                }
            ),
            e.code or 500,
        )

    @app.errorhandler(Exception)
    async def handle_unexpected_error(e: Exception) -> tuple[Response, int]:
        logger.error("Unhandled exception: %s", e, exc_info=True)
        return (
            jsonify(
                {
                    "error": "internal_error",
                    "detail": "An unexpected internal error occurred",
                    "status_code": 500,
                }
            ),
            500,
        )

    @app.before_serving
    async def startup() -> None:
        # Non-fatal: the server must serve HTTP even when Intiface Central is
        # down; commands report 503 until the connection is re-established.
        await device_mgr.start()

    @app.after_serving
    async def shutdown() -> None:
        await device_mgr.shutdown()

    app.device_manager = device_mgr
    return app


async def run_server(settings: Settings) -> None:
    """Create the app and serve it until cancelled."""
    app = create_app(settings)
    await app.run_task(
        host=settings.server.host,
        port=settings.server.port,
        debug=settings.server.debug,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buttplug-st",
        description=(
            "REST bridge between SillyTavern and buttplug.io devices via Intiface Central."
        ),
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="TOML config file (default: packaged default.toml)",
    )
    parser.add_argument("--host", help="HTTP host to bind (overrides config file and environment)")
    parser.add_argument(
        "--port", type=int, help="HTTP port to bind (overrides config file and environment)"
    )
    parser.add_argument("--debug", action="store_true", help="Enable Quart debug mode")
    return parser


def load_settings(argv: list[str] | None = None) -> Settings:
    """Parse CLI arguments and resolve the single effective Settings instance.

    Precedence: CLI flags > BUTTPLUG_* environment variables > --config file >
    packaged defaults.
    """
    args = build_arg_parser().parse_args(argv)
    settings = Settings.load(args.config)
    overrides: dict[str, dict[str, object]] = {"server": {}}
    if args.host is not None:
        overrides["server"]["host"] = args.host
    if args.port is not None:
        overrides["server"]["port"] = args.port
    if args.debug:
        overrides["server"]["debug"] = True
    settings.apply_updates(overrides)
    return settings


def main(argv: list[str] | None = None) -> int:
    """Console-script entry point. Returns a process exit code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    try:
        settings = load_settings(argv)
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"ButtplugST {__version__}")
    print(
        f"  server:    host={settings.server.host} port={settings.server.port} "
        f"debug={settings.server.debug}"
    )
    print(
        f"  websocket: url={settings.websocket.url} scan_timeout={settings.websocket.scan_timeout}"
    )
    print(
        f"  device:    default_speed={settings.device.default_speed} "
        f"default_position={settings.device.default_position} "
        f"default_duration={settings.device.default_duration}"
    )

    # KeyboardInterrupt covers Ctrl+C on every platform; no loop-level
    # signal handlers are registered (they are unsupported on Windows).
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_server(settings))
    return 0
