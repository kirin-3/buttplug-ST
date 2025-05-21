import asyncio
import logging
import os
import sys
import platform
from functools import partial
import signal

from quart import Quart, jsonify
from quart_cors import cors

from .config import Settings
from .core import DeviceManager
from .core.exceptions import ButtplugSTException
from .api import create_blueprint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)

def create_app(settings: Settings) -> Quart:
    """Create and configure the Quart application"""
    app = Quart(__name__)
    
    # Enable CORS
    app = cors(app, allow_origin="*")
    
    # Create device manager
    device_mgr = DeviceManager(settings)
    
    # Register API routes
    api_bp = create_blueprint(device_mgr)
    app.register_blueprint(api_bp)
    
    # Error handlers
    @app.errorhandler(ButtplugSTException)
    async def handle_buttplug_exception(e):
        return jsonify(e.to_dict()), e.status_code
    
    @app.errorhandler(Exception)
    async def handle_generic_exception(e):
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        return jsonify({
            "error": "internal_error",
            "detail": str(e),
            "status_code": 500
        }), 500
    
    # Startup/Shutdown handlers
    @app.before_serving
    async def startup():
        logger.info("Starting up ButtplugST server...")
        try:
            await device_mgr.initialize()
            logger.info("ButtplugST server started")
        except Exception as e:
            logger.error(f"Error during startup: {e}", exc_info=True)
    
    @app.after_serving
    async def shutdown():
        logger.info("Shutting down ButtplugST server...")
        await device_mgr.shutdown()
        logger.info("ButtplugST server stopped")
    
    app.device_manager = device_mgr
    return app

def handle_signal(app, loop, signal_name):
    """Handle termination signals"""
    logger.info(f"Received {signal_name}, shutting down...")
    loop.create_task(app.shutdown())

async def main():
    """Main application entry point"""
    # Load settings
    settings = Settings.load()
    
    # Create the application
    app = create_app(settings)
    
    # Set up signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    
    # Skip signal handlers on Windows as they're not supported
    if platform.system() != "Windows":
        try:
            for sig_name in ('SIGINT', 'SIGTERM'):
                if hasattr(signal, sig_name):
                    sig = getattr(signal, sig_name)
                    loop.add_signal_handler(
                        sig,
                        partial(handle_signal, app, loop, sig_name)
                    )
        except NotImplementedError:
            logger.warning("Signal handlers not supported on this platform")
    
    # Start the server
    logger.info(f"Starting server on {settings.server.host}:{settings.server.port}")
    await app.run_task(
        host=settings.server.host,
        port=settings.server.port,
        debug=settings.server.debug
    )

if __name__ == "__main__":
    asyncio.run(main()) 