import logging
from typing import Tuple, Dict, Any, Optional
from functools import wraps

from quart import Blueprint, request, jsonify
from pydantic import ValidationError as PydanticValidationError

from ..core.device import DeviceManager
from ..core.exceptions import ButtplugSTException
from .schemas import (
    VibrateRequest, 
    DeviceSelectionRequest,
    APIResponse,
    ErrorResponse
)

logger = logging.getLogger(__name__)

def create_blueprint(device_manager: DeviceManager) -> Blueprint:
    """Create a blueprint with all API routes"""
    api_bp = Blueprint("api", __name__)
    
    # Add device manager as blueprint attribute
    api_bp.device_manager = device_manager
    
    # Error handling decorator
    def handle_errors(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            try:
                return await f(*args, **kwargs)
            except PydanticValidationError as e:
                logger.error(f"Validation error: {e}")
                return jsonify(ErrorResponse(
                    error="validation_error",
                    detail=str(e),
                    status_code=400
                ).dict()), 400
            except ButtplugSTException as e:
                logger.error(f"ButtplugST error: {e}")
                return jsonify(e.to_dict()), e.status_code
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                return jsonify(ErrorResponse(
                    error="internal_error",
                    detail=str(e),
                    status_code=500
                ).dict()), 500
        return decorated_function
    
    # Ensure device manager is initialized
    @api_bp.before_request
    async def ensure_initialized():
        logger.info(f"Request received: {request.path}")
        
        try:
            if not api_bp.device_manager._initialized:
                logger.info("Device manager not initialized, initializing now...")
                await api_bp.device_manager.initialize()
                logger.info("Device manager initialization complete")
        except Exception as e:
            logger.error(f"Error during initialization: {e}")
            # Don't raise here, let the endpoint handle the error
        
        # Skip device check for status endpoint
        if request.path == "/status":
            return
        
        # For other endpoints, check if device is available
        if not api_bp.device_manager.has_devices:
            try:
                # Try scanning for devices if none are available
                logger.info("No devices available, scanning...")
                await api_bp.device_manager.scan_devices()
                logger.info(f"Device scan complete. Found {len(api_bp.device_manager._devices)} devices.")
            except Exception as e:
                logger.error(f"Error scanning for devices: {e}")
                # Don't raise here, let the endpoint handle the error
    
    @api_bp.route("/status")
    @handle_errors
    async def status() -> Tuple[Dict[str, Any], int]:
        """Get server and device status"""
        logger.info("Status endpoint called")
        
        is_connected = api_bp.device_manager.is_connected
        has_devices = api_bp.device_manager.has_devices
        active_device = api_bp.device_manager.get_active_device()
        initialized = api_bp.device_manager._initialized
        
        # Get more details
        client_state = "Not created"
        if api_bp.device_manager._client is not None:
            client_state = "Connected" if api_bp.device_manager._client.connected else "Disconnected"
            
        device_count = len(api_bp.device_manager._devices)
        
        status_data = {
            "status": "ok" if is_connected else "error",
            "server_running": True,
            "server_initialized": initialized,
            "intiface_connected": is_connected,
            "client_state": client_state,
            "device_count": device_count,
            "has_devices": has_devices,
            "websocket_url": api_bp.device_manager.settings.websocket.url,
            "active_device": None if not active_device else {
                "id": active_device.id,
                "name": active_device.name,
                "index": active_device.index,
                "actuator_count": active_device.actuator_count,
                "actuator_types": active_device.actuator_types
            }
        }
        
        logger.info(f"Status response: {status_data}")
        
        return jsonify(APIResponse(
            success=True,
            message="Server status",
            data=status_data
        ).dict()), 200
    
    @api_bp.route("/devices")
    @handle_errors
    async def list_devices() -> Tuple[Dict[str, Any], int]:
        """Get list of connected devices"""
        # Scan for devices
        await api_bp.device_manager.scan_devices()
        
        devices = api_bp.device_manager.get_all_devices()
        active_index = api_bp.device_manager._active_device_index
        
        device_list = [{
            "id": d.id,
            "name": d.name,
            "index": d.index,
            "actuator_count": d.actuator_count,
            "actuator_types": d.actuator_types
        } for d in devices]
        
        return jsonify(APIResponse(
            success=True,
            message=f"Found {len(devices)} devices",
            data={
                "devices": device_list,
                "active_index": active_index
            }
        ).dict()), 200
    
    @api_bp.route("/device", methods=["POST"])
    @handle_errors
    async def select_device() -> Tuple[Dict[str, Any], int]:
        """Select active device by index"""
        data = await request.get_json()
        req = DeviceSelectionRequest.parse_obj(data)
        
        device_info = api_bp.device_manager.set_active_device(req.index)
        
        return jsonify(APIResponse(
            success=True,
            message=f"Selected device: {device_info.name}",
            data={
                "id": device_info.id,
                "name": device_info.name,
                "index": device_info.index,
                "actuator_count": device_info.actuator_count,
                "actuator_types": device_info.actuator_types
            }
        ).dict()), 200
    
    @api_bp.route("/vibrate")
    @handle_errors
    async def vibrate() -> Tuple[Dict[str, Any], int]:
        """Control vibration of the active device"""
        # Add detailed logging for incoming request
        logger.info(f"Vibrate endpoint called with args: {request.args}")
        
        # Parse query parameters
        speed = float(request.args.get("speed", 0.5))
        position = request.args.get("position")
        position = float(position) if position is not None else None
        duration = float(request.args.get("duration", 0))
        
        logger.info(f"Parsed parameters - speed: {speed}, position: {position}, duration: {duration}")
        
        # Validate using Pydantic model
        req = VibrateRequest(
            speed=speed,
            position=position,
            duration=duration
        )
        
        # Execute vibration command
        result = await api_bp.device_manager.vibrate(
            speed=req.speed,
            position=req.position,
            duration=req.duration
        )
        
        message = f"Vibrating at {req.speed*100:.0f}% power"
        if req.position is not None:
            message += f", position {req.position*100:.0f}%"
        if req.duration > 0:
            message += f" for {req.duration} seconds"
        
        logger.info(f"Vibrate command completed: {message}")
        
        return jsonify(APIResponse(
            success=True,
            message=message,
            data=result
        ).dict()), 200
    
    @api_bp.route("/stop")
    @handle_errors
    async def stop() -> Tuple[Dict[str, Any], int]:
        """Stop all actuators on the active device"""
        result = await api_bp.device_manager.stop()
        
        return jsonify(APIResponse(
            success=True,
            message="Device stopped",
            data=result
        ).dict()), 200
    
    @api_bp.route("/scan")
    @handle_errors
    async def scan() -> Tuple[Dict[str, Any], int]:
        """Scan for devices"""
        devices = await api_bp.device_manager.scan_devices()
        
        return jsonify(APIResponse(
            success=True,
            message=f"Found {len(devices)} devices",
            data={
                "count": len(devices),
                "devices": [{
                    "id": d.id,
                    "name": d.name,
                    "index": d.index,
                    "actuator_count": d.actuator_count,
                    "actuator_types": d.actuator_types
                } for d in devices]
            }
        ).dict()), 200
    
    return api_bp 