from typing import Optional, Dict, Any

class ButtplugSTException(Exception):
    """Base exception for all app-specific exceptions"""
    status_code: int = 500
    code: str = "internal_error"
    detail: str = "An internal error occurred"
    
    def __init__(
        self, 
        detail: Optional[str] = None, 
        code: Optional[str] = None,
        status_code: Optional[int] = None
    ):
        if detail:
            self.detail = detail
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        super().__init__(self.detail)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses"""
        return {
            "error": self.code,
            "detail": self.detail,
            "status_code": self.status_code
        }


class DeviceNotFoundError(ButtplugSTException):
    """Exception raised when no device is found or connected"""
    status_code = 404
    code = "device_not_found"
    detail = "No device found or connected"


class DeviceConnectionError(ButtplugSTException):
    """Exception raised when there's an error connecting to a device"""
    status_code = 502
    code = "device_connection_error"
    detail = "Failed to connect to device"


class IntifaceConnectionError(ButtplugSTException):
    """Exception raised when there's an error connecting to Intiface"""
    status_code = 502
    code = "intiface_connection_error"
    detail = "Failed to connect to Intiface WebSocket server"


class CommandError(ButtplugSTException):
    """Exception raised when a device command fails"""
    status_code = 500
    code = "command_error"
    detail = "Failed to execute device command"


class ValidationError(ButtplugSTException):
    """Exception raised for validation errors"""
    status_code = 400
    code = "validation_error"
    detail = "Invalid request parameters" 